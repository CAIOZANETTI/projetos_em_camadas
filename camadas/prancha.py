"""Leitura da prancha em camadas de entendimento: identidade → vistas → tabelas → elementos → vínculos.

    identidade = código Sanepar, disciplina e tipo (planta/detalhe/documento) — `inventario`
    vistas     = blocos de desenho separados por espaço vazio; a escala vem do título ("ESCALA 1:100", OCR) e é
                 conferida contra a afim da prancha: escala diferente = a vista não está georreferenciada
    tabelas    = grade de linhas na imagem da folha → células → OCR; a "relação de materiais" vira itens
                 {nº, código, descrição, qtde, un}, conferidos no cadastro Sanepar e na tabela do contrato
    elementos  = classe pelo nome do layer (`conceitos/elementos.json`); layer genérico (pena) pela geometria:
                 estaca = círculo tracejado, bloco = retângulo que contém estacas
    vínculos   = balão nº → item da tabela; estaca do desenho → estaca com E/N (encaixe por RANSAC de similaridade
                 com a escala da folha) → afim da vista → blocos em UTM, com os níveis lidos nas tabelas

Tudo é algoritmo determinístico; o texto SHX (traço) é lido por OCR (tesseract).
"""
from __future__ import annotations

import functools
import itertools
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import shapely
from shapely.geometry import LineString

from . import geo, pdf_cad

MM_PT = 25.4 / 72                                       # 1 pt = 0,3528 mm
VERSAO = 6                                              # entra na assinatura do cache: mudou a leitura, refaz a ficha


def _pagina(pdf):
    import pymupdf
    return pymupdf.open(pdf)[0]


def _imagem(pagina, clip=None, dpi=300):
    """Folha (ou recorte, em pt da folha exibida) em tons de cinza."""
    px = pagina.get_pixmap(dpi=dpi, clip=clip, colorspace=__import__("pymupdf").csGRAY)
    return np.frombuffer(px.samples, np.uint8).reshape(px.h, px.w)


def _limpar(img: np.ndarray, altura_letra_px: float = 18.0) -> np.ndarray | None:
    """Célula pronta para o OCR: tira as linhas longas (bordas), corta justo na tinta, leva a letra a ~18 px de
    altura e põe margem branca. Medido em Foz (6 cotas SHX): 16–18 px leu 6/6 a 400 e a 900 dpi; 25 px leu 0/6,
    trocando todo 3 por 5 (o tamanho da letra pesa mais que a resolução)."""
    b = (img < 160).astype(np.uint8)
    h, w = b.shape
    linhas = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((1, max(3, int(w * 0.5))), np.uint8)) | \
        cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((max(3, int(h * 0.7)), 1), np.uint8))
    tinta = b & ~cv2.dilate(linhas, np.ones((3, 3), np.uint8))
    n, comp, st, _ = cv2.connectedComponentsWithStats(tinta)
    ok = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 4 and st[i, 0] > 0 and st[i, 0] + st[i, 2] < w]
    if not ok:
        return None
    x0, y0 = min(st[i, 0] for i in ok), min(st[i, 1] for i in ok)
    x1, y1 = max(st[i, 0] + st[i, 2] for i in ok), max(st[i, 1] + st[i, 3] for i in ok)
    limpo = np.where(np.isin(comp, ok), 0, 255).astype(np.uint8)[y0:y1, x0:x1]
    k = min(altura_letra_px / max(float(np.median([st[i, 3] for i in ok])), 1.0), 4000 / max(limpo.shape))
    limpo = cv2.resize(limpo, None, fx=k, fy=k, interpolation=cv2.INTER_AREA if k < 1 else cv2.INTER_CUBIC)
    return cv2.copyMakeBorder(limpo, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


def _ocr(img, config="--psm 6") -> str:
    import pytesseract
    from PIL import Image
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")    # com várias threads e outro processo na CPU, uma tabela de
                                                      # 33 s passou de 10 min (medido em Foz, folha 009)
    return pytesseract.image_to_string(Image.fromarray(img), lang="por", config=config).strip()


def vistas(tracos: list, largura: float, altura: float, fechar_pt: float = 12.0, area_min_pt2: float = 20000.0,
           excluir: str = r"CARIMBO|FORMATO|LOGO|TXT|FOLHA") -> list[list[float]]:
    """Caixas (pt) dos blocos de desenho: traços rasterizados, fechados por `fechar_pt` e separados por componentes.
    Moldura, carimbo e traços maiores que meia folha ficam de fora."""
    res = 0.25
    m = np.zeros((int(altura * res) + 1, int(largura * res) + 1), np.uint8)
    for t in tracos:
        if re.search(excluir, t["layer"], re.IGNORECASE):
            continue
        for q in map(np.asarray, t["partes"]):
            if len(q) >= 2 and np.ptp(q, axis=0).max() <= 0.5 * max(largura, altura):
                cv2.polylines(m, [(q * res).astype(np.int32)], False, 1, 1)
    k = int(fechar_pt * res) | 1
    n, _, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))))
    cx = [[st[i, 0] / res, st[i, 1] / res, (st[i, 0] + st[i, 2]) / res, (st[i, 1] + st[i, 3]) / res]
          for i in range(1, n) if st[i, 2] * st[i, 3] / res / res >= area_min_pt2]
    dentro = lambda a, b: a is not b and b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]
    return [a for a in cx if not any(dentro(a, b) for b in cx)]          # contorno interno é da mesma vista


ESCALA = re.compile(r"ESC(?:ALA|\.)?\s*[:.]?\s*1\s*[:/]\s*(\d{1,4})")


def _texto_da_faixa(pagina, x0, x1, ya, yb, tracos, textos, glifo_max_pt) -> str:
    """Texto de uma faixa da folha: palavras de fonte do PDF, senão OCR dos glifos SHX redesenhados no branco (ou
    da imagem da folha, sem `tracos`)."""
    import pymupdf
    if textos:
        dentro = sorted((round(y), x, t) for x, y, t in textos if x0 <= x <= x1 and ya <= y <= yb)
        if dentro:
            return " ".join(t for _, _, t in dentro)
    if tracos is None:
        return _ocr(_imagem(pagina, pymupdf.Rect(x0, ya, x1, yb), 300), "--psm 11")
    px = 300 / 72
    img = np.full((int((yb - ya) * px) + 1, int((x1 - x0) * px) + 1), 255, np.uint8)
    for t in tracos:
        for q in t["partes"]:
            q = np.asarray(q, float)
            if len(q) >= 2 and np.ptp(q, axis=0).max() <= glifo_max_pt and x0 <= q[:, 0].min() and \
                    q[:, 0].max() <= x1 and ya <= q[:, 1].min() and q[:, 1].max() <= yb:
                cv2.polylines(img, [((q - [x0, ya]) * px).astype(np.int32)], False, 0, 2, cv2.LINE_AA)
    return "" if img.min() == 255 else _ocr(img, "--psm 11")


def escala_do_titulo(pagina, caixa, faixa_pt: float = 60.0, tracos: list | None = None, textos: list = (),
                     glifo_max_pt: float = 15.0) -> int | None:
    """Denominador da escala do título da vista ("ESCALA 1:100", "ESC 1:50"): primeiro na faixa logo abaixo, depois
    na de cima (contenção de Foz: título em fonte acima da vista); None se não houver. Com `tracos`, o OCR lê só os
    glifos SHX da faixa (com o desenho ao fundo o tesseract levava 30–100 s por faixa); com `textos` (`palavras`),
    o texto de fonte vem direto do PDF."""
    x0, y0, x1, y1 = caixa
    for ya, yb in ((y1, min(y1 + faixa_pt, pagina.rect.height)), (max(y0 - faixa_pt, 0), y0)):
        if yb - ya < 4:                                  # vista encostada na borda: não há faixa de título
            continue
        m = ESCALA.search(_texto_da_faixa(pagina, x0, x1, ya, yb, tracos, textos, glifo_max_pt).upper())
        if m:
            return int(m[1])
    return None


def escala_da_afim(M) -> float:
    """Denominador da escala implícita na afim pt → m (média dos dois eixos)."""
    A = np.asarray(M, float)[:2, :2]
    return float(np.sqrt(abs(np.linalg.det(A)))) / (MM_PT / 1000)


def _raster(linhas_utm: list, e0: float, n1: float, res: float, forma) -> np.ndarray:
    m = np.zeros(forma, np.uint8)
    for u in linhas_utm:
        cv2.polylines(m, [np.c_[(u[:, 0] - e0) / res, (n1 - u[:, 1]) / res].astype(np.int32)], False, 1, 1)
    return m


def registrar_vista(linhas_pt: list, escala: int, ref_utm: list, res: float = 0.1, tol_m: float = 0.2,
                    margem_pico: float = 0.15) -> dict:
    """Vista de detalhe (escala própria) encaixada em linhas de referência já em UTM: rotação em passos de 90°,
    translação pela nota F1 — precisão (linhas da vista sobre a referência) × revocação (linhas da referência,
    dentro da vista, cobertas por ela). Só a precisão satura em área densa (rodada 8). Aceita quando o melhor
    supera o 2º melhor (de outra rotação ou a > 3 m) por `margem_pico`: no teste sintético o encaixe certo deu
    29 % (0,915 × 0,646) e uma referência sem o desenho 8 %; a f010 real contra a f004, 1–2 %."""
    R = np.vstack(ref_utm)
    e0, n1 = R[:, 0].min() - 5, R[:, 1].max() + 5
    forma = (int((n1 - R[:, 1].min() + 5) / res) + 1, int((R[:, 0].max() + 5 - e0) / res) + 1)
    k = int(2 * tol_m / res) | 1
    ref = _raster(ref_utm, e0, n1, res, forma).astype(np.float32)
    ref_d = cv2.dilate(ref, np.ones((k, k), np.uint8))
    c = np.vstack(linhas_pt).mean(0)
    cands = []
    for g in range(4):
        th = np.radians(90 * g)
        A = MM_PT / 1000 * escala * np.array([[np.cos(th), np.sin(th)], [np.sin(th), -np.cos(th)]])   # y do PDF desce
        loc = [(q - c) @ A.T for q in linhas_pt]
        L = np.vstack(loc)
        x0, y1 = L[:, 0].min(), L[:, 1].max()
        tpl = _raster(loc, x0, y1, res, (int((y1 - L[:, 1].min()) / res) + 1, int((L[:, 0].max() - x0) / res) + 1))
        tpl = tpl.astype(np.float32)
        if tpl.shape[0] >= ref.shape[0] or tpl.shape[1] >= ref.shape[1] or not tpl.sum():
            continue
        prec = cv2.matchTemplate(ref_d, tpl, cv2.TM_CCORR) / tpl.sum()
        rec = cv2.matchTemplate(ref, cv2.dilate(tpl, np.ones((k, k), np.uint8)), cv2.TM_CCORR) / \
            np.maximum(cv2.matchTemplate(ref, np.ones_like(tpl), cv2.TM_CCORR), 1)
        f1 = 2 * prec * rec / np.maximum(prec + rec, 1e-6)
        _, mx, _, (px, py) = cv2.minMaxLoc(f1)
        resto = f1.copy()
        cv2.circle(resto, (px, py), int(3 / res), 0, -1)
        M = np.vstack([np.c_[A, [e0 + px * res - x0, n1 - py * res - y1] - A @ c], [0, 0, 1]])
        cands.append({"rotacao": 90 * g, "f1": float(mx), "segundo_local": float(resto.max()), "M": M})
    if not cands:
        return {"ok": False, "motivo": "vista maior que a referência"}
    cands.sort(key=lambda r: -r["f1"])
    b = cands[0]
    segundo = max([b["segundo_local"]] + [r["f1"] for r in cands[1:]])
    ok = (b["f1"] - segundo) / max(b["f1"], 1e-6) >= margem_pico
    return {"ok": bool(ok), "M": b["M"] if ok else None, "rotacao": b["rotacao"], "f1": round(b["f1"], 3),
            "segundo": round(segundo, 3), "motivo": "pico claro" if ok else
            f"sem pico: melhor {b['f1']:.3f} × 2º {segundo:.3f} — a referência não tem o desenho da vista"}


def grades(pagina, dpi: float = 216, min_linhas: int = 4) -> list[dict]:
    """Tabelas da folha: componentes de linhas horizontais e verticais longas com ≥ `min_linhas` linhas que
    atravessam a largura (desenho também forma grade, mas raramente com tantas linhas de ponta a ponta)."""
    k = dpi / 72
    b = (_imagem(pagina, dpi=dpi) < 160).astype(np.uint8)
    h = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((1, 60), np.uint8))
    v = cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((20, 1), np.uint8))
    n, comp, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(h | v, np.ones((5, 5), np.uint8)))
    out = []
    for i in range(1, n):
        x, y, w, hh, _ = st[i]
        if w < 80 or hh < 40 or w > 0.9 * b.shape[1]:
            continue
        cobertura = (h[y:y + hh, x:x + w] & (comp[y:y + hh, x:x + w] == i)).sum(1) > 0.8 * w
        linhas = int(np.sum(np.diff(cobertura.astype(int)) == 1))
        if linhas >= 1:
            out.append({"caixa": [x / k, y / k, (x + w) / k, (y + hh) / k], "linhas": linhas})
    out = [t for t in _empilhar(out) if t["linhas"] >= min_linhas]
    dentro = lambda a, b: a is not b and b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]
    out = [t for t in out if not any(dentro(t["caixa"], u["caixa"]) for u in out)]   # sub-tabela fica na de fora
    return sorted(out, key=lambda t: (t["caixa"][1], t["caixa"][0]))


def _empilhar(tabelas: list[dict], tol_pt: float = 6.0, vao_pt: float = 20.0) -> list[dict]:
    """Junta grades uma sobre a outra com a mesma largura: o cabeçalho separado do corpo por linha dupla (Foz,
    folhas 009, 011…) vira uma tabela só — senão o corpo fica sem cabeçalho e nenhuma coluna é reconhecida."""
    out = []
    for t in sorted(tabelas, key=lambda t: t["caixa"][1]):
        a = next((u for u in out if abs(u["caixa"][0] - t["caixa"][0]) <= tol_pt and abs(u["caixa"][2] - t["caixa"][2])
                  <= tol_pt and 0 <= t["caixa"][1] - u["caixa"][3] <= vao_pt), None)
        if a is None:
            out.append(dict(t))
            continue
        a["caixa"] = [min(a["caixa"][0], t["caixa"][0]), a["caixa"][1], max(a["caixa"][2], t["caixa"][2]), t["caixa"][3]]
        a["linhas"] += t["linhas"]
    return sorted(out, key=lambda t: (t["caixa"][1], t["caixa"][0]))


def _cortes(soma: np.ndarray, gap: int = 3) -> list[int]:
    idx = np.flatnonzero(soma)
    return [int(g[len(g) // 2]) for g in np.split(idx, np.flatnonzero(np.diff(idx) > gap) + 1)] if len(idx) else []


RELEITURA = (                                            # célula que parece número ou lista de rótulos: relida
    (re.compile(r"^[\d,./ ]{4,}$"), "0123456789,."),     # com só os caracteres possíveis (o SHX troca 3 por 5)
    (re.compile(r"^(?:PC?[0-9/I|]{1,2}(?:[-–—]+|[aA])?)+$"), "PCAa0123456789-"),
)


def celulas(pagina, caixa, dpi: int = 400, dpi_releitura: int = 900) -> list[list[str]]:
    """Texto de cada célula, linha a linha: separa as linhas pelas horizontais que atravessam a tabela e as colunas
    pelas verticais de cada faixa (o cabeçalho tem colunas diferentes do corpo). Célula numérica ou de rótulos é
    relida em resolução maior, linha única e lista de caracteres permitidos."""
    import pymupdf
    img = _imagem(pagina, pymupdf.Rect(*caixa), dpi)
    b = (img < 160).astype(np.uint8)
    W, k = b.shape[1], 72 / dpi
    ys = _cortes(cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((1, int(W * 0.6)), np.uint8)).sum(1))
    out = []
    for y0, y1 in itertools.pairwise(ys):
        if y1 - y0 < 8:
            continue
        faixa = b[y0 + 2:y1 - 1]
        xs = [0, *_cortes(cv2.morphologyEx(faixa, cv2.MORPH_OPEN, np.ones((max(3, int((y1 - y0) * 0.8)), 1), np.uint8)).sum(0)), W]
        linha = []
        for x0, x1 in itertools.pairwise(xs):
            if x1 - x0 < 10:
                continue
            limpo = _limpar(img[y0:y1 + 1, x0:x1 + 1])
            t = "" if limpo is None else _ocr(limpo).replace("\n", " ")
            for padrao, letras in RELEITURA:
                if padrao.search(t.replace(" ", "")):
                    clip = pymupdf.Rect(caixa[0] + x0 * k, caixa[1] + y0 * k, caixa[0] + (x1 + 1) * k, caixa[1] + (y1 + 1) * k)
                    alta = _limpar(_imagem(pagina, clip, dpi_releitura))
                    t = (alta is not None and _ocr(alta, f"--psm 7 -c tessedit_char_whitelist={letras}")) or t
                    break
            linha.append(t)
        out.append(linha)
    return out


SINONIMOS_COLUNA = {"DISC": "DESC", "QUAN": "QTD", "QUNT": "QTD"}   # "DISCRIMINAÇÃO", "QUANT." (folha 042A)


def _colunas(cabecalho: list[str]) -> dict:
    """Índice de cada coluna pelas 4 primeiras letras/dígitos do título ("1ª ETAPA" → 1AET, "Nº" → NO)."""
    col = {}
    for k, c in enumerate(cabecalho):
        if c:
            chave = re.sub(r"[^A-Z0-9]", "", pdf_cad._sem_acento(c))[:4]
            col[SINONIMOS_COLUNA.get(chave, chave)] = k
    kc = next((k for c, k in col.items() if c.startswith(("ESPE", "COD"))), 0)
    if kc and not any(c in ("N", "NO", "NR", "NUM", "ITEM") for c in col):
        col["N"] = kc - 1                                 # "Nº" pequeno lido vazio (perfis AAT06): vem antes do código
    return col


def itens_da_tabela(linhas: list[list[str]]) -> list[dict]:
    """Relação de materiais: a linha com 'DESCRI'/'DISCRIM' é o cabeçalho e dá o índice de cada coluna; linha com uma
    só célula cheia é subtítulo (vários blocos na mesma tabela); linha com nº ou S/N na coluna 'N' é item. Corpo com
    uma coluna a mais que o cabeçalho e sem coluna de código: o código SAM vem logo depois do nº (folha 042A)."""
    itens, col, nh, bloco = [], {}, 0, ""
    for cel in linhas:
        cel = [c.strip() for c in cel]
        cheias = [c for c in cel if c]
        if any(re.search(r"DESCRI|DISCRIM", pdf_cad._sem_acento(c)) for c in cel):
            col, nh = _colunas(cel), len(cel)
            continue
        if len(cheias) == 1:
            bloco = cheias[0]
            continue
        kn = next((k for c, k in col.items() if c in ("N", "NO", "NR", "NUM", "ITEM")), None)   # "Nº" vira "NO"
        if kn is None or kn >= len(cel):
            continue
        n = re.sub(r"[^0-9A-Z/]", "", cel[kn].upper())                # '“4' → '4'
        if not re.fullmatch(r"S/?N", n):
            n = n.translate(str.maketrans("OSIL", "0511"))          # "OS" lido no lugar de "05"
        if not re.fullmatch(r"\d{1,3}|S/?N", n):
            continue
        c_lin = col
        if len(cel) > nh and not any(c.startswith(("ESPE", "COD")) for c in col):
            c_lin = {**{c: k + (k > kn) for c, k in col.items()}, "COD": kn + 1}
        valor = {c: cel[k] for c, k in c_lin.items() if k < len(cel)}
        pega = lambda *chaves, v=valor: next((x for c, x in v.items() if c.startswith(chaves)), "")
        # quantidade por etapa pela ordem das colunas "nª ETAPA" (o OCR leu "1ª" como "4a" na folha 009)
        et = sorted(k for c, k in c_lin.items() if re.match(r"\dA?ET", c) and k < len(cel))
        q1, q2 = ([cel[k] or None for k in et[:2]] + [None, None])[:2]
        qtde = pega("QTD") or " · ".join(f"{i}ª {q}" for i, q in ((1, q1), (2, q2)) if q)
        cod = re.sub(r"\D", "", pega("ESPE", "COD"))
        if len(cod) > 7:                                  # dois códigos (tubo + flange): fica o primeiro
            cod = re.search(r"\d{3,7}", pega("ESPE", "COD"))[0]
        itens.append({"n": "S/N" if "S" in n else n.zfill(2), "codigo": cod or None,
                      "descricao": pega("DESC"), "qtde": qtde,
                      "q1": q1, "q2": q2, "un": pega("UN"), "bloco": bloco})
    return itens


def conferir_itens(itens: list[dict], cadastro: dict, contrato: list[dict]) -> list[dict]:
    """Cada item ganha a descrição do cadastro (pelo código) e a linha do contrato com o mesmo código."""
    por_codigo = defaultdict(list)
    for c in contrato:
        por_codigo[str(c.get("codigo"))].append(c)
    out = []
    for it in itens:
        cad = cadastro.get(it["codigo"] or "")
        k = por_codigo.get(it["codigo"] or "", [])
        out.append({**it, "cadastro": cad["descricao"] if cad else None,
                    "contrato": [{"tabela": c["tabela"], "item": c["item"], "q1": c["q1"], "q2": c["q2"], "un": c["un"]}
                                 for c in k]})
    return out


def circulos(partes: list[np.ndarray], r_min: float = 3.0, r_max: float = 20.0, tol_pt: float = 3.0,
             res_max: float = 0.6) -> np.ndarray:
    """Círculos (cx, cy, r) em pt a partir de traços curtos encadeados (círculo tracejado ou explodido em arcos):
    agrupa peças cujas pontas se tocam e ajusta um círculo (Kasa) em cada grupo."""
    n = len(partes)
    pai = list(range(n))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i
    grade = defaultdict(list)
    for i, q in enumerate(partes):
        grade[tuple((q.mean(0) // 6).astype(int))].append(i)
    pontas = [np.array([q[0], q[-1]]) for q in partes]
    for (gx, gy), ids in grade.items():
        viz = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in grade.get((gx + dx, gy + dy), [])]
        for i in ids:
            for j in viz:
                if j > i and np.linalg.norm(pontas[i][:, None] - pontas[j][None], axis=2).min() < tol_pt:
                    pai[raiz(i)] = raiz(j)
    grupos = defaultdict(list)
    for i in range(n):
        grupos[raiz(i)].append(i)
    out = []
    for ids in grupos.values():
        P = np.vstack([partes[i] for i in ids])
        if len(P) < 8:
            continue
        cx, cy, c = np.linalg.lstsq(np.c_[2 * P, np.ones(len(P))], (P ** 2).sum(1), rcond=None)[0]
        r = float(np.sqrt(max(c + cx * cx + cy * cy, 0)))
        if r_min <= r <= r_max and np.abs(np.linalg.norm(P - [cx, cy], axis=1) - r).max() < res_max:
            out.append((cx, cy, r))
    return np.array(out).reshape(-1, 3)


def estacas_e_blocos(tracos: list, diametro_m: tuple = (0.25, 0.80), escala: int = 50, lado_max_m: float = 8.0) -> dict:
    """Estacas = círculos (por layer, o que tiver mais no diâmetro esperado); blocos = retângulos de até `lado_max_m`
    que contêm estacas, no layer que cobre mais estacas (empate: o de mais blocos — a moldura da folha também
    "contém" todas as estacas). Devolve centros/contornos em pt e os layers escolhidos."""
    rmin, rmax = (d / 2 / (MM_PT / 1000 * escala) for d in diametro_m)
    lado_max = lado_max_m / (MM_PT / 1000 * escala)
    por_layer = defaultdict(list)
    for t in tracos:
        for q in map(np.asarray, t["partes"]):
            if len(q) >= 2 and np.ptp(q, axis=0).max() < 2 * rmax:
                por_layer[t["layer"]].append(q.astype(float))
    cand = {lay: circulos(ps, rmin, rmax) for lay, ps in por_layer.items() if len(ps) >= 8}
    lay_e = max(cand, key=lambda k: len(cand[k]), default=None)
    est = cand.get(lay_e, np.empty((0, 3)))
    pts = shapely.points(est[:, :2])
    melhor = (0, 0, None, [])
    for lay in sorted({t["layer"] for t in tracos} - {lay_e}):
        linhas = [LineString(q) for t in tracos if t["layer"] == lay and t["preenchimento"] is None
                  for q in map(np.asarray, t["partes"]) if len(q) >= 2 and np.ptp(q, axis=0).max() > 2 * rmin]
        if not linhas:
            continue
        pol = shapely.get_parts(shapely.polygonize(shapely.get_parts(shapely.node(shapely.union_all(linhas)))))
        bl = [p for p in pol if p.area > 0 and p.minimum_rotated_rectangle.area / p.area < 1.05
              and max(np.ptp(np.asarray(p.exterior.coords), axis=0)) <= lado_max and shapely.contains(p, pts).any()]
        bl = [p for p in bl if not any(q is not p and q.area < p.area and p.contains(q.representative_point()) for q in bl)]
        cob = sum(int(shapely.contains(p, pts).sum()) for p in bl)
        if (cob, len(bl)) > melhor[:2]:
            melhor = (cob, len(bl), lay, bl)
    return {"estacas_pt": est, "layer_estacas": lay_e, "blocos_pt": melhor[3], "layer_blocos": melhor[2],
            "estacas_nos_blocos": melhor[0]}


def registrar_pontos(P_pt: np.ndarray, U: np.ndarray, escala: int, tol_m: float = 0.25) -> dict:
    """Afim pt → UTM por encaixe de pontos sem correspondência conhecida (RANSAC de similaridade): cada par de
    vizinhos do desenho contra os pares de E/N com a mesma distância na escala da folha; vence a que mais encaixa;
    refino por mínimos quadrados nos inliers. O eixo y do PDF desce: a similaridade é feita em (x, −y)."""
    s0 = MM_PT / 1000 * escala
    P = np.c_[P_pt[:, 0], -P_pt[:, 1]]
    zP, zU = P[:, 0] + 1j * P[:, 1], U[:, 0] + 1j * U[:, 1]
    D = np.abs(zP[:, None] - zP[None])
    np.fill_diagonal(D, np.inf)
    DU = np.abs(zU[:, None] - zU[None])
    np.fill_diagonal(DU, np.inf)
    melhor = (0, None)
    for i in range(len(P)):
        j = int(np.argmin(D[i]))
        for a, b in np.argwhere(np.abs(DU - D[i, j] * s0) < 0.04 * D[i, j] * s0):
            k = (zU[b] - zU[a]) / (zP[j] - zP[i])
            if abs(abs(k) / s0 - 1) > 0.05:
                continue
            d = np.abs((zP * k + zU[a] - k * zP[i])[:, None] - zU[None]).min(1)
            n = int((d < tol_m).sum())
            if n > melhor[0]:
                melhor = (n, (k, zU[a] - k * zP[i]))
    if melhor[1] is None:
        return {"ok": False, "motivo": "nenhum par de estacas com a distância da escala da folha"}
    k, t = melhor[1]
    q = np.abs((zP * k + t)[:, None] - zU[None])
    par, ok = q.argmin(1), q.min(1) < tol_m
    A = np.c_[P[ok], np.ones(ok.sum())]
    X = np.linalg.lstsq(A, U[par[ok]], rcond=None)[0]
    r = np.linalg.norm(A @ X - U[par[ok]], axis=1)
    M = np.vstack([np.c_[X[:2].T @ np.diag([1, -1]), X[2]], [0, 0, 1]])    # volta para (x, y) do PDF
    return {"ok": True, "M": M, "inliers": int(ok.sum()), "total": len(P), "par": par.tolist(), "casou": ok.tolist(),
            "residuo_mediano_m": round(float(np.median(r)), 3), "residuo_max_m": round(float(r.max()), 3),
            "escala": round(escala_da_afim(M))}


def desenho_sem_hachura(tracos: list, caixa, px_pt: float, espessura: int = 2, hachura_min_pt: float = 12.0) -> np.ndarray:
    """Trecho da folha redesenhado pelo vetor, sem a hachura (segmentos longos a 45°): o texto que fica sob a hachura
    volta a ser legível. Preenchimentos são pintados (letra SHX cheia)."""
    x0, y0, x1, y1 = caixa
    img = np.full((int((y1 - y0) * px_pt) + 1, int((x1 - x0) * px_pt) + 1), 255, np.uint8)
    for t in tracos:
        for q in (np.asarray(q, float) for q in t["partes"]):
            if len(q) < 2 or q[:, 0].max() < x0 or q[:, 0].min() > x1 or q[:, 1].max() < y0 or q[:, 1].min() > y1:
                continue
            if t["preenchimento"] is not None and len(q) >= 3:
                cv2.fillPoly(img, [((q - [x0, y0]) * px_pt).astype(np.int32)], 0)
                continue
            for a, b in itertools.pairwise(q):
                d = b - a
                if np.hypot(*d) > hachura_min_pt and abs(np.degrees(np.arctan2(d[1], d[0])) % 90 - 45) < 10:
                    continue
                cv2.line(img, tuple(((a - [x0, y0]) * px_pt).astype(int)), tuple(((b - [x0, y0]) * px_pt).astype(int)),
                         0, espessura, cv2.LINE_AA)
    return img


def _palavras(img: np.ndarray, origem, px_pt: float, padrao: str, psm: int = 11) -> list[tuple]:
    """Palavras que casam com `padrao` e o centro delas em pt da folha."""
    import pytesseract
    from PIL import Image
    d = pytesseract.image_to_data(Image.fromarray(img), config=f"--psm {psm}", output_type=pytesseract.Output.DICT)
    out = []
    for w, l, t, ww, h in zip(d["text"], d["left"], d["top"], d["width"], d["height"]):
        txt = re.sub(r"[^A-Z0-9]", "", w.upper())
        if re.fullmatch(padrao, txt):
            out.append((txt, np.array([origem[0] + (l + ww / 2) / px_pt, origem[1] + (t + h / 2) / px_pt])))
    return out


def rotulos(pagina, poligonos: list, padrao: str = r"PC?\d{1,2}", dpis=(130, 160, 200), max_pt: float = 45.0,
            tracos: list | None = None) -> list:
    """Rótulo de cada elemento (PC12, P3…).
    1ª passada: OCR da vista inteira em três resoluções (a letra perto de 18 px); cada rótulo vai ao elemento cujo
    contorno está mais perto (pares do mais próximo ao mais distante, cada um usado uma vez, até `max_pt`).
    2ª passada (com `tracos`): elemento ainda sem rótulo é relido num recorte redesenhado sem a hachura, em
    várias escalas; vale o candidato mais perto que ainda não foi usado."""
    if not len(poligonos):                               # folha sem blocos (ETL01, reforma): nada a rotular
        return []
    import pymupdf
    B = np.array([p.bounds for p in poligonos])
    x0, y0 = B[:, :2].min(0) - 60
    x1, y1 = B[:, 2:].max(0) + 60
    achados = []
    for dpi in dpis:
        for txt, c in _palavras(_imagem(pagina, pymupdf.Rect(x0, y0, x1, y1), dpi), (x0, y0), dpi / 72, padrao):
            if not any(a == txt and np.linalg.norm(b - c) < 6 for a, b in achados):
                achados.append((txt, c))
    pares = sorted((float(shapely.distance(p, shapely.Point(*c))), i, k) for i, p in enumerate(poligonos)
                   for k, (_, c) in enumerate(achados))
    out, usados = [None] * len(poligonos), set()
    for d, i, k in pares:
        if d <= max_pt and out[i] is None and k not in usados and achados[k][0] not in out:
            out[i] = achados[k][0]
            usados.add(k)
    for i, p in enumerate(poligonos):
        if out[i] is not None or tracos is None:
            continue
        bx = np.array(p.bounds) + [-70, -70, 70, 70]
        cand = [(float(shapely.distance(p, shapely.Point(*c))), txt) for px in (2.0, 2.5, 3.0, 4.0) for psm in (11, 6)
                for txt, c in _palavras(desenho_sem_hachura(tracos, bx, px), bx[:2], px, padrao, psm) if txt not in out]
        perto = sorted(c for c in cand if c[0] <= max_pt)
        out[i] = perto[0][1] if perto else None
    return out


def pilares(pagina, blocos: list, escala: int, lado_m: float = 0.40, dpi: int = 144) -> list[dict]:
    """Pilares = manchas cheias quadradas com o lado do pilar (± 25 %) dentro de um bloco: a hachura sólida do
    pilar vem em traços, então a imagem (abertura morfológica tira linhas e letras) é o caminho."""
    if not len(blocos):
        return []
    k = dpi / 72
    b = (_imagem(pagina, dpi=dpi) < 100).astype(np.uint8)
    n, _, st, cen = cv2.connectedComponentsWithStats(cv2.morphologyEx(b, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8)))
    lado = lado_m / (MM_PT / 1000 * escala)
    out = []
    for i in range(1, n):
        _, _, w, h, a = st[i]
        if 0.75 * lado <= w / k <= 1.25 * lado and 0.75 * lado <= h / k <= 1.25 * lado and a / (w * h) > 0.85:
            c = cen[i] / k
            dono = next((j for j, p in enumerate(blocos) if p.contains(shapely.Point(*c))), None)
            if dono is not None:
                out.append({"centro_pt": c.round(1).tolist(), "lado_m": round(float((w + h) / 2 / k * MM_PT / 1000 * escala), 2),
                            "bloco": dono})
    return out


def _ocr_tracos(tracos_pt: list[np.ndarray], px_pt: float = 20.0, espessura: int = 4, config: str = "--psm 8") -> str:
    """OCR de texto SHX desenhado só com os próprios traços (sem o fundo do desenho): imagem limpa, preto no branco."""
    P = np.vstack(tracos_pt)
    x0, y0 = P.min(0) - 2
    w, h = ((P.max(0) - P.min(0) + 4) * px_pt).astype(int) + 1
    img = np.full((h, w), 255, np.uint8)
    for q in tracos_pt:
        cv2.polylines(img, [((q - [x0, y0]) * px_pt).astype(np.int32)], False, 0, espessura, cv2.LINE_AA)
    return _ocr(cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255), config)


LEITURAS_NUMERO = ((20.0, 4, "--psm 8"), (30.0, 6, "--psm 13"), (12.0, 3, "--psm 7"))   # 3/5 × 1: cada uma erra um


def glifos(tracos_pt: list[np.ndarray]) -> int:
    """Quantos caracteres: traços agrupados pela sobreposição em x."""
    faixas = sorted((q[:, 0].min(), q[:, 0].max()) for q in tracos_pt)
    n, fim = 0, -np.inf
    for a, b in faixas:
        if a > fim:
            n += 1
        fim = max(fim, b)
    return n


def ler_numero(tracos_pt: list[np.ndarray], validos: set | None = None) -> str | None:
    """Número SHX lido em três configurações; só vale leitura com um dígito por glifo (senão "4" no lugar de "11"
    vira "04"); vence a mais votada entre as válidas (os nº da tabela da folha)."""
    from collections import Counter
    n = glifos(tracos_pt)
    lidos = [re.sub(r"\D", "", _ocr_tracos(tracos_pt, px, esp, f"{psm} -c tessedit_char_whitelist=0123456789"))
             for px, esp, psm in LEITURAS_NUMERO]
    lidos = [x.zfill(2) for x in lidos if len(x) == n and x.strip("0")]
    bons = [x for x in lidos if not validos or x in validos]
    return Counter(bons or lidos).most_common(1)[0][0] if (bons or lidos) else None


def palavras(pagina) -> list[tuple]:
    """Texto de fonte da folha (quando não é SHX): [(cx, cy, texto)] em pt da folha exibida."""
    import pymupdf
    out = []
    for w in pagina.get_text("words"):
        r = pymupdf.Rect(w[:4]) * pagina.rotation_matrix
        out.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, w[4]))
    return out


def _numero_do_texto(c, r: float, textos: list[tuple], validos: set | None) -> str | None:
    """Número do balão escrito em fonte: palavra de 1–3 dígitos com o centro dentro do círculo."""
    for x, y, t in textos:
        if np.hypot(x - c[0], y - c[1]) < r * 0.8 and re.fullmatch(r"\d{1,3}", t):
            n = t.zfill(2)
            if validos is None or n in validos:
                return n
    return None


def baloes(tracos: list, layer: str, layer_numero: str | None = None, diametro_pt: tuple = (7.0, 14.0),
           validos: set | None = None, textos: list[tuple] = ()) -> list[dict]:
    """Balões da lista de peças: círculo do layer; número = traços SHX dentro do círculo (do layer do texto; sem ele,
    do layer com mais traços dentro dos círculos, o do balão incluído), lidos por OCR numa imagem só com eles, ou
    texto de fonte do PDF dentro do círculo (`textos`, de `palavras`; folhas do sistema pneumático);
    peça = ponta da linha de chamada que sai do círculo."""
    partes = [np.asarray(q, float) for t in tracos if t["layer"] == layer for q in t["partes"] if len(q) >= 2]
    redondos = [q for q in partes if len(q) >= 8 and diametro_pt[0] <= np.ptp(q, axis=0).max() <= diametro_pt[1]]
    retas = [q for q in partes if len(q) == 2]
    circ = {id(q) for q in redondos}               # o número pode estar no próprio layer do balão (Foz, folha 053)
    curtas = [(t["layer"], q) for t in tracos for q in (partes if t["layer"] == layer else map(np.asarray, t["partes"]))
              if len(q) >= 2 and id(q) not in circ and np.ptp(q, axis=0).max() < diametro_pt[1]]
    if layer_numero is None and redondos and curtas:   # o layer do número = o que mais tem traço dentro dos círculos
        C = np.array([q.mean(0) for q in redondos])
        R = np.array([np.ptp(q, axis=0).max() / 2 for q in redondos])
        conta = defaultdict(int)
        for lay, q in curtas:
            conta[lay] += bool((np.linalg.norm(C - q.mean(0), axis=1) < R * 0.8).any())
        layer_numero = max(conta, key=conta.get) if max(conta.values()) else None
    letras = [q for lay, q in curtas if lay == (layer_numero or lay)]
    centros = np.array([q.mean(0) for q in letras]).reshape(-1, 2)
    out = []
    for q in redondos:
        c, r = q.mean(0), np.ptp(q, axis=0).max() / 2
        dentro = [letras[k] for k in np.flatnonzero(np.linalg.norm(centros - c, axis=1) < r * 0.8)]
        num = ler_numero(dentro, validos) if dentro else _numero_do_texto(c, r, textos, validos)   # SHX ou fonte
        ponta = next((s[int(np.argmax(np.linalg.norm(s - c, axis=1)))] for s in retas
                      if np.linalg.norm(s - c, axis=1).min() < r * 1.3 < np.linalg.norm(s - c, axis=1).max()), None)
        out.append({"centro_pt": c.round(1).tolist(), "n": num,
                    "ponta_pt": None if ponta is None else ponta.round(1).tolist()})
    return out


def identidade(pdf: str | Path) -> dict:
    """Quem é a prancha: código Sanepar, disciplina, tipo (planta/detalhe/documento), unidade e localizada × linear."""
    from . import inventario
    nome = Path(pdf).name
    regras = json.loads((pdf_cad.CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))
    grupo, subgrupo = pdf_cad.disciplina_da_prancha(nome)
    u = re.search(r"UNIDADE\s*0*(\d+)", str(pdf), re.IGNORECASE)
    return {"arquivo": nome, "codigo": inventario.codigo_sanepar(nome), "grupo": grupo, "subgrupo": subgrupo,
            "tipo": inventario.tipo_documento(nome, None, regras), "unidade": f"Unidade {u[1]}" if u else None,
            "obra": "linear" if re.search(regras["linear"], pdf_cad._sem_acento(nome)) else "localizada"}


def elementos_por_layer(tracos: list) -> dict:
    """Traços por classe de elemento (nome do layer) e os layers de cada classe."""
    cls = pdf_cad.elementos()["classes"]
    out: dict = {}
    for t in tracos:
        e = pdf_cad.elemento_do_layer(t["layer"], cls) or "sem_classe"
        d = out.setdefault(e, {"tracos": 0, "layers": set()})
        d["tracos"] += len(t["partes"])
        d["layers"].add(t["layer"])
    return {e: {"tracos": d["tracos"], "layers": sorted(d["layers"])} for e, d in out.items()}


def servicos(classes: list[str]) -> list[dict]:
    """Serviços de obra que as classes de elemento da prancha geram (`conceitos/elementos.json`)."""
    por_id = {c["id"]: c for c in pdf_cad.elementos()["classes"]}
    return [{"elemento": por_id[c]["nome"], "servicos": por_id[c]["servicos"]} for c in classes
            if por_id.get(c, {}).get("servicos")]


def rotulos_da_lista(texto: str) -> list[str]:
    """'PC9 a PC14-PC16-PC21 a PC29-P1 A P12' → PC9…PC14, PC16, PC21…PC29, P1…P12. Procura os rótulos no texto
    (ruído de OCR entre eles, como 'PC5S', é ignorado)."""
    alvo = pdf_cad._sem_acento(texto).replace(" ", "")
    out = []
    for m in re.finditer(r"(PC|P)(\d+)(?:A(?:PC|P)?(\d+))?", alvo):
        out += [f"{m[1]}{k}" for k in range(int(m[2]), int(m[3] or m[2]) + 1)]
    return out


def niveis_da_tabela(linhas: list[list[str]]) -> dict:
    """Tabela de níveis ('NÍVEL DA FACE SUPERIOR DOS BLOCOS', 'NÍVEL DE ARRASAMENTO…'): título e nível por rótulo."""
    titulo, por = "", {}
    for cel in linhas:
        cheias = [c for c in (x.strip() for x in cel) if c]
        if len(cheias) == 1:
            titulo = titulo or cheias[0]
            continue
        m = re.search(r"(\d{3})[,.](\d{1,3})", " ".join(cheias))
        if m and len(cheias) >= 2:
            for r in rotulos_da_lista(cheias[-1]):
                por[r] = float(f"{m[1]}.{m[2]}")
    return {"titulo": titulo, "por_rotulo": por}


def ficha_estrutura(f: dict, ancoras: Path, log=print) -> dict:
    """Piloto estrutura: estacas, blocos e pilares pela geometria, rótulos por OCR, encaixe nas estacas com E/N e
    níveis das tabelas."""
    import csv
    pg, tr = _pagina(f["pdf"]), pdf_cad.extrair(f["pdf"])
    g = estacas_e_blocos(tr, escala=f["escala"])
    with open(ancoras, encoding="utf-8") as fh:
        linhas = list(csv.DictReader(fh, delimiter=";"))
    U = np.array([[float(r["E"]), float(r["N"])] for r in linhas])
    reg = registrar_pontos(g["estacas_pt"][:, :2], U, f["escala"])
    nomes = rotulos(pg, g["blocos_pt"], tracos=tr)
    niveis = {}
    for t in grades(pg):
        if t["caixa"][2] - t["caixa"][0] > 0.4 * pg.rect.width:      # é desenho em grade, não tabela de níveis
            continue
        n = niveis_da_tabela(celulas(pg, t["caixa"]))
        chave = "face_superior" if "SUPERIOR" in pdf_cad._sem_acento(n["titulo"]) else \
            "arrasamento" if "ARRASA" in pdf_cad._sem_acento(n["titulo"]) else None
        if chave and n["por_rotulo"]:
            niveis[chave] = n["por_rotulo"]
    pts = shapely.points(g["estacas_pt"][:, :2])
    blocos = []
    for p, nome in zip(g["blocos_pt"], nomes):
        utm = geo.aplicar(reg["M"], np.asarray(p.exterior.coords)) if reg["ok"] else None
        blocos.append({"rotulo": nome, "estacas": int(shapely.contains(p, pts).sum()),
                       "contorno_utm": None if utm is None else utm.round(3).tolist(),
                       "face_superior": niveis.get("face_superior", {}).get(nome),
                       "arrasamento": niveis.get("arrasamento", {}).get(nome)})
    pil = []
    for q in pilares(pg, g["blocos_pt"], f["escala"]):
        c, meio = np.array(q["centro_pt"]), q["lado_m"] / 2 / (MM_PT / 1000 * f["escala"])
        quad = c + np.array([[-meio, -meio], [meio, -meio], [meio, meio], [-meio, meio], [-meio, -meio]])
        pil.append({"bloco": nomes[q["bloco"]], "lado_m": q["lado_m"],
                    "contorno_utm": geo.aplicar(reg["M"], quad).round(3).tolist() if reg["ok"] else None})
    ids = [linhas[j]["id"] for j, ok in zip(reg.get("par", []), reg.get("casou", [])) if ok]
    log(f"Ficha {f['id']}: {len(g['estacas_pt'])} estacas (layer {g['layer_estacas']}), {len(blocos)} blocos "
        f"(layer {g['layer_blocos']}, {sum(n is not None for n in nomes)} rotulados), {len(pil)} pilares, "
        f"encaixe {reg.get('inliers')}/{reg.get('total')} a {reg.get('residuo_mediano_m')} m")
    return {"estacas": len(g["estacas_pt"]), "layer_estacas": g["layer_estacas"], "layer_blocos": g["layer_blocos"],
            "estacas_nos_blocos": g["estacas_nos_blocos"], "blocos": blocos, "pilares": pil, "niveis": niveis,
            "encaixe": {k: v for k, v in reg.items() if k not in ("par", "casou", "M")} | {
                "M": None if not reg["ok"] else np.asarray(reg["M"]).round(9).tolist(),
                "estruturas": sorted({i.rsplit("-", 1)[0] for i in ids})}}


def linhas_de_desenho(tracos: list, M=None, caixa=None) -> list[np.ndarray]:
    """Traços que são desenho (não grafismo pela classe do layer: texto, cota, hachura…), em pt ou em UTM com `M`."""
    graf = {c["id"] for c in pdf_cad.elementos()["classes"] if c["grupo"] == "Grafismo"}
    cls = {lay: pdf_cad.elemento_do_layer(lay) for lay in {t["layer"] for t in tracos}}
    x0, y0, x1, y1 = caixa or (-np.inf, -np.inf, np.inf, np.inf)
    out = []
    for t in tracos:
        if cls[t["layer"]] in graf:
            continue
        for q in (np.asarray(q, float) for q in t["partes"]):
            if len(q) >= 2 and np.ptp(q, axis=0).max() > 3 and x0 <= q[:, 0].min() and q[:, 0].max() <= x1 \
                    and y0 <= q[:, 1].min() and q[:, 1].max() <= y1:
                out.append(q if M is None else geo.aplicar(np.asarray(M), q))
    return out


def ficha_hidraulica(f: dict, M, cadastro: dict, contrato: list[dict], ref_utm: list | None = None, log=print) -> dict:
    """Piloto hidráulica: vistas e escala, relação de materiais (OCR) e balões → itens. Com `ref_utm` (linhas de uma
    prancha de referência já em UTM), cada vista com escala lida é encaixada nela; vista aceita põe as peças dos
    balões no mapa."""
    pg, tr = _pagina(f["pdf"]), pdf_cad.extrair(f["pdf"])
    txt = palavras(pg)
    vs = []
    for caixa in vistas(tr, pg.rect.width, pg.rect.height):
        esc = escala_do_titulo(pg, caixa, tracos=tr, textos=txt)
        afim = round(escala_da_afim(M)) if M is not None else None
        v = {"caixa": [round(x, 1) for x in caixa], "escala_titulo": esc, "escala_afim": afim,
             "georreferenciada": bool(esc and afim and abs(afim / esc - 1) < 0.03), "M": None}
        if esc and ref_utm and not v["georreferenciada"]:
            enc = registrar_vista(linhas_de_desenho(tr, caixa=caixa), esc, ref_utm)
            v["encaixe"] = {k: x for k, x in enc.items() if k != "M"}
            v["georreferenciada"], v["M"] = enc["ok"], None if enc["M"] is None else enc["M"].round(9).tolist()
        vs.append(v)
    itens = []
    for t in grades(pg):
        it = itens_da_tabela(celulas(pg, t["caixa"]))
        if it:
            itens += conferir_itens(it, cadastro, contrato)
    numeros = {i["n"] for i in itens}
    bs = baloes(tr, f["layer_balao"], f.get("layer_numero"), validos=numeros, textos=txt)
    for b in bs:
        b["item"] = b["n"] if b["n"] in numeros else None
        p = np.array(b["ponta_pt"] or b["centro_pt"])
        v = next((v for v in vs if v["M"] and v["caixa"][0] <= p[0] <= v["caixa"][2] and v["caixa"][1] <= p[1] <= v["caixa"][3]), None)
        b["utm"] = None if v is None else geo.aplicar(np.asarray(v["M"]), p[None])[0].round(3).tolist()
    com_balao = {b["n"] for b in bs}
    log(f"Ficha {f['id']}: {len(vs)} vistas ({sum(v['georreferenciada'] for v in vs)} georreferenciadas), "
        f"{len(itens)} itens, {len(bs)} balões ({sum(b['item'] is not None for b in bs)} com item, "
        f"{sum(b['utm'] is not None for b in bs)} no mapa)")
    return {"vistas": vs, "itens": itens, "baloes": bs,
            "itens_sem_balao": sorted(i["n"] for i in itens if i["n"] != "S/N" and i["n"] not in com_balao),
            "baloes_sem_item": sorted({b["n"] or "ilegível" for b in bs if b["item"] is None})}


def etapa(cfg: dict, pranchas: list, escopo: dict | None, out: Path, log=print) -> list[dict] | None:
    """Fichas das pranchas declaradas em `fichas` no obra.json (cache por assinatura do PDF: o OCR é lento)."""
    from . import orcamento_sanepar
    if not cfg.get("fichas"):
        return None
    arq = out / "fichas_cache.json"
    cache = json.loads(arq.read_text()) if arq.exists() else {}
    por_id = {p["id"]: p for p in pranchas}
    cad = orcamento_sanepar.catalogo(cfg["escopo"]["catalogo"]) if cfg.get("escopo", {}).get("catalogo") else {}
    fichas = []
    for f in cfg["fichas"]:
        if f["piloto"] == "estrutura" and not Path(f["ancoras"]).exists():
            log(f"Ficha {f['id']}: NÃO LIDA — falta o arquivo de âncoras {f['ancoras']} (pendência; o build segue)")
            continue
        pdf = Path(f.get("pdf") or por_id[f["id"]]["pdf"])
        assinatura = f"v{VERSAO}:{pdf.stat().st_size}:{int(pdf.stat().st_mtime)}:{json.dumps(f, sort_keys=True)}"
        if cache.get(f["id"], {}).get("assinatura") != assinatura:
            f = {**f, "pdf": str(pdf)}
            tr = pdf_cad.extrair(pdf)
            ref = por_id.get(f.get("referencia_vistas") or "")
            ref_utm = linhas_de_desenho(pdf_cad.extrair(ref["pdf"], clip=ref.get("clip")), ref["M"]) \
                if ref and ref.get("M") is not None else None
            contrato = [i for i in (escopo or {}).get("itens", []) if i["tabela"] in f.get("tabelas", [])]
            corpo = ficha_estrutura(f, Path(f["ancoras"]), log) if f["piloto"] == "estrutura" else ficha_hidraulica(
                f, por_id.get(f["id"], {}).get("M"), cad, contrato, ref_utm, log)
            el = elementos_por_layer(tr)
            cache[f["id"]] = {"assinatura": assinatura, "ficha": {
                "id": f["id"], "nome": f.get("nome", pdf.stem), "piloto": f["piloto"], "identidade": identidade(pdf),
                "elementos": el, "servicos": servicos(list(el)), **corpo}}
            arq.write_text(json.dumps(cache, ensure_ascii=False))
        fichas.append(cache[f["id"]]["ficha"])
    return fichas


def ficha_leve(pdf: str | Path) -> dict:
    """Ficha sem OCR de tabela: identidade, elementos por layer, vistas e escalas lidas nos títulos, nº de tabelas
    e de balões (círculos do layer de balão)."""
    pg, tr = _pagina(pdf), pdf_cad.extrair(pdf)
    txt = palavras(pg)
    vs = vistas(tr, pg.rect.width, pg.rect.height)
    escalas = sorted({e for v in vs if (e := escala_do_titulo(pg, v, tracos=tr, textos=txt))})
    cls = {lay: pdf_cad.elemento_do_layer(lay) for lay in {t["layer"] for t in tr}}
    lay_b = [lay for lay, c in cls.items() if c == "balao"]
    n_b = sum(1 for t in tr if t["layer"] in lay_b for q in t["partes"]
              if len(q) >= 8 and 7 <= np.ptp(np.asarray(q), axis=0).max() <= 14)
    el = elementos_por_layer(tr)
    objetos = {c["id"] for c in pdf_cad.elementos()["classes"] if c["grupo"] in ("Hidráulica", "Estrutura", "Civil", "Elétrica")}
    return {"identidade": identidade(pdf), "vistas": len(vs), "escalas": escalas, "tabelas": len(grades(pg)),
            "layer_balao": (lay_b or [None])[0] if n_b else None, "baloes": n_b,
            "objetos": sorted((k for k in el if k in objetos), key=lambda k: -el[k]["tracos"]),
            "tracos": sum(v["tracos"] for v in el.values()), "genericos": el.get("generico", {}).get("tracos", 0)}


def e_desenho(nome: str, regras: dict) -> bool:
    """Prancha de desenho (entra no lote): código Sanepar do tipo DE, ou "-DE-"/"-FX-" no nome; termo de referência,
    memorial, lista e descritivo (tipo documento pelo nome) ficam de fora."""
    from . import inventario
    cod = inventario.codigo_sanepar(nome)
    if cod:
        return cod["tipo"] == "DE"
    return bool(re.search(r"-(DE|FX)-", nome.upper())) or inventario.tipo_documento(nome, None, regras) != "documento"


@functools.cache
def _cadastro(caminho: str | None) -> dict:
    from . import orcamento_sanepar
    return orcamento_sanepar.catalogo(caminho) if caminho else {}


def _ficha_do_lote(pdf: str, tabs: list[str], contrato: list[dict], catalogo: str | None) -> tuple[dict, float]:
    """Uma folha do lote (roda num processo à parte): ficha leve e, se há balões, a completa."""
    t0 = time.time()
    try:
        f = ficha_leve(pdf)
        if f["baloes"]:
            h = ficha_hidraulica({"id": Path(pdf).stem, "pdf": pdf, "layer_balao": f["layer_balao"]}, None,
                                 _cadastro(catalogo), contrato, None, log=lambda *a: None)
            f["completa"] = {"tabelas_contrato": tabs, "itens": len(h["itens"]),
                             "itens_no_contrato": sum(bool(i["contrato"]) for i in h["itens"]),
                             "baloes_com_item": sum(b["item"] is not None for b in h["baloes"]),
                             "itens_sem_balao": h["itens_sem_balao"]}
    except (RuntimeError, ValueError, IndexError, KeyError, OSError) as e:   # PDF ruim: fica o motivo
        f = {"erro": f"{type(e).__name__}: {e}"[:200]}
    return f, time.time() - t0


def lote(cfg: dict, escopo: dict | None, out: Path, log=print, processos: int | None = None) -> dict:
    """Ficha leve de todo desenho no disco (inventário), pelo caminho relativo à pasta; a completa (tabela + balões, sem georreferência) onde há
    balões, com as tabelas do contrato que apontam para o desenho. Cache por assinatura do arquivo; as folhas que
    faltam rodam em paralelo (um processo por núcleo)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed

    from . import inventario
    c = cfg.get("inventario")
    if not c or not cfg.get("fichas_lote", True):
        return {}
    arq = out / "fichas_lote_cache.json"
    cache = json.loads(arq.read_text()) if arq.exists() else {}
    chave = lambda n: re.sub(r"[^a-z0-9]", "", inventario.normalizar(re.sub(r"-R\d+$", "", Path(n).stem)))
    tabelas = {}
    for t, d in (escopo or {}).get("desenhos_por_tabela", {}).items():
        tabelas.setdefault(chave(d), []).append(t)
    regras = json.loads((pdf_cad.CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))
    pdfs = {str(p): f"v{VERSAO}:{p.stat().st_size}:{int(p.stat().st_mtime)}" for p in sorted(Path(c["pasta"]).rglob("*"))
            if p.suffix.lower() == ".pdf" and e_desenho(p.name, regras)}
    falta = [p for p, a in pdfs.items() if cache.get(p, {}).get("assinatura") != a]
    if falta:
        with ProcessPoolExecutor(processos) as ex:
            tarefas = {}
            for p in falta:
                tabs = tabelas.get(chave(p), [])
                contrato = [i for i in (escopo or {}).get("itens", []) if i["tabela"] in tabs]
                tarefas[ex.submit(_ficha_do_lote, p, tabs, contrato, cfg.get("escopo", {}).get("catalogo"))] = p
            for k, fut in enumerate(as_completed(tarefas), 1):
                p = tarefas[fut]
                f, dt = fut.result()
                cache[p] = {"assinatura": pdfs[p], "ficha": f}
                arq.write_text(json.dumps(cache, ensure_ascii=False))
                log(f"  ficha {k}/{len(falta)} {Path(p).name}: {f.get('baloes', 0)} balões, {f.get('erro', 'ok')} ({dt:.0f} s)")
    if _relacao_da_familia(cache, list(pdfs), log):
        arq.write_text(json.dumps(cache, ensure_ascii=False))
    out_lote = {Path(p).relative_to(c["pasta"]).as_posix(): cache[p]["ficha"] for p in pdfs}   # nomes repetem entre pastas
    comp = [f for f in out_lote.values() if f.get("completa")]
    log(f"Fichas em lote: {len(out_lote)} desenhos, {sum('erro' in f for f in out_lote.values())} com erro, "
        f"{len(comp)} com balões ({sum(f['completa']['baloes_com_item'] for f in comp)} balões ligados a item)")
    return out_lote


def _relacao_da_familia(cache: dict, pdfs: list[str], log=print) -> bool:
    """Balões de folha sem relação de materiais ligados à relação de uma folha irmã (mesma descrição no código
    Sanepar sem o número final, ex.: 015 a 019 "…TRATAM600LS"). Só valem os números que a irmã lista como itens sem balão na própria
    folha — a peça está desenhada em outra folha da família (Foz: itens 80–84 da 019 nos balões da 015–018).
    Devolve True se mudou alguma ficha."""
    from . import inventario
    familias = defaultdict(list)
    for p in pdfs:
        cod, comp = inventario.codigo_sanepar(Path(p).name), cache[p]["ficha"].get("completa")
        if cod and comp:
            familias[(cod["disciplina"], re.sub(r"\d+$", "", cod["descricao"]))].append(p)   # SISTPNEU02…04
    mudou = False
    for ps in familias.values():
        doadoras = [p for p in ps if cache[p]["ficha"]["completa"]["itens"]]
        validos = sorted({n for p in doadoras for n in cache[p]["ficha"]["completa"]["itens_sem_balao"]})
        for p in ps:
            comp = cache[p]["ficha"]["completa"]
            if comp["itens"] or not validos or comp.get("familia", {}).get("validos") == validos:
                continue
            bs = baloes(pdf_cad.extrair(p), cache[p]["ficha"]["layer_balao"], validos=set(validos),
                        textos=palavras(_pagina(p)))
            vistos = sorted({b["n"] for b in bs if b["n"] in validos})
            comp["familia"] = {"relacao_em": [Path(d).name for d in doadoras], "validos": validos, "itens": vistos}
            comp["baloes_com_item"] = sum(b["n"] in validos for b in bs)
            log(f"  relação da família: {Path(p).name} → {comp['baloes_com_item']} balões ligados ({', '.join(vistos)})")
            mudou = True
    return mudou


def resumo_lote(f: dict | None) -> dict | None:
    """Resumo da ficha leve para a linha do inventário (nomes das classes, sem contagens por layer)."""
    if not f:
        return None
    if "erro" in f:
        return {"erro": f["erro"]}
    nomes = {c["id"]: c["nome"] for c in pdf_cad.elementos()["classes"]}
    return {"vistas": f["vistas"], "escalas": f["escalas"], "tabelas": f["tabelas"], "baloes": f["baloes"],
            "obra": f["identidade"]["obra"], "objetos": [nomes[k] for k in f["objetos"][:6]],
            "genericos_pct": round(100 * f["genericos"] / max(f["tracos"], 1)), "completa": f.get("completa")}


def blocos_com_nivel(fichas: list[dict]) -> list[dict]:
    """Blocos das fichas de estrutura com contorno em UTM (o encaixe deu certo)."""
    return [{**b, "ficha": f["id"]} for f in fichas if f["piloto"] == "estrutura" for b in f["blocos"]
            if b.get("contorno_utm")]


def vetor_blocos(fichas: list[dict], epsg: int) -> dict | None:
    """Camada do mapa: blocos lidos na forma (rótulo, nº de estacas, níveis) e os pilares sobre eles."""
    bl = blocos_com_nivel(fichas)
    if not bl:
        return None
    feats = []
    for b in bl:
        lon, lat = geo.para_lonlat(np.array(b["contorno_utm"])[:, 0], np.array(b["contorno_utm"])[:, 1], epsg)
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [np.c_[lon, lat].tolist()]},
                      "properties": {"tipo": "Bloco (forma)", "rotulo": b["rotulo"] or "sem rótulo legível",
                                     "estacas": b["estacas"], "face_superior_m": b["face_superior"],
                                     "arrasamento_m": b["arrasamento"], "ficha": b["ficha"]}})
    for f in fichas:
        for p in f.get("pilares", []):
            if p.get("contorno_utm"):
                lon, lat = geo.para_lonlat(np.array(p["contorno_utm"])[:, 0], np.array(p["contorno_utm"])[:, 1], epsg)
                feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [np.c_[lon, lat].tolist()]},
                              "properties": {"tipo": "Pilar (forma)", "bloco": p["bloco"], "lado_m": p["lado_m"],
                                             "ficha": f["id"], "cor": "#1c1917"}})
    n_bl = sum(f["properties"]["tipo"].startswith("Bloco") for f in feats)
    return {"id": "blocos_forma", "nome": f"Blocos e pilares lidos na forma ({n_bl} + {len(feats) - n_bl})", "grupo": "Civil",
            "subgrupo": "Geotecnia e fundação", "visivel": False,
            "geojson": {"type": "FeatureCollection", "features": feats},
            "estilo": {"color": "#57534e", "weight": 1.5, "fillColor": "#a8a29e", "fillOpacity": 0.6}}


def vetor_pecas(fichas: list[dict], epsg: int) -> dict | None:
    """Camada do mapa: peças dos balões das vistas georreferenciadas, com o item da relação de materiais."""
    feats = []
    for f in fichas:
        itens = {i["n"]: i for i in f.get("itens", [])}
        for b in f.get("baloes", []):
            if b.get("utm") and b.get("item"):
                it = itens[b["item"]]
                lon, lat = geo.para_lonlat(np.array([b["utm"][0]]), np.array([b["utm"][1]]), epsg)
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [float(lon[0]), float(lat[0])]},
                              "properties": {"tipo": "Peça (balão)", "item": it["n"], "codigo": it["codigo"],
                                             "descricao": it["descricao"], "qtde": f"{it['qtde']} {it['un']}", "ficha": f["id"]}})
    if not feats:
        return None
    return {"id": "pecas_baloes", "nome": f"Peças da lista de materiais ({len(feats)})", "grupo": "Hidráulica",
            "subgrupo": "Tubulações e conexões", "visivel": False, "geojson": {"type": "FeatureCollection", "features": feats},
            "estilo": {"color": "#0e7490", "radius": 5, "weight": 2, "fillOpacity": 0.9}}


def solidos_3d(fichas: list[dict], origem) -> list[dict]:
    """Sólidos do 3D (em cota): base no nível de arrasamento das estacas, topo na face superior do bloco
    (premissa: o embutimento da estaca no bloco, ~5 cm, é desprezado); só blocos com os dois níveis."""
    return [{"id": b["rotulo"], "xy": (np.array(b["contorno_utm"]) - origem[:2]).round(3).tolist(),
             "z0": b["arrasamento"], "z1": b["face_superior"]}
            for b in blocos_com_nivel(fichas) if b["face_superior"] is not None and b["arrasamento"] is not None]


def para_html(fichas: list[dict]) -> list[dict]:
    """Fichas para a aba Projeto: elementos já com nome e grupo (ordem dos grupos do conceito) e sem os contornos
    dos blocos (já vão na camada e no 3D). O front só exibe."""
    d = pdf_cad.elementos()
    por_id, ordem = {c["id"]: c for c in d["classes"]}, {g: i for i, g in enumerate(d["grupos"])}
    out = []
    for f in fichas:
        el = [{"id": k, "nome": por_id.get(k, {}).get("nome", "Sem classe"), "grupo": por_id.get(k, {}).get("grupo", "Sem classe"),
               "tracos": v["tracos"], "layers": v["layers"]} for k, v in f["elementos"].items()]
        el.sort(key=lambda e: (ordem.get(e["grupo"], 99), -e["tracos"]))
        out.append({**f, "elementos": el,
                    "blocos": [{k: v for k, v in b.items() if k != "contorno_utm"} for b in f.get("blocos", [])],
                    "pilares": [{k: v for k, v in q.items() if k != "contorno_utm"} for q in f.get("pilares", [])]})
    return out


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "prancha",
        "descricao": "ficha da prancha: vistas e escala, tabelas por OCR, elementos por layer ou geometria, balões → "
                     "itens, estacas → E/N (RANSAC) e blocos em UTM",
        "funcoes": ["vistas", "escala_do_titulo", "escala_da_afim", "registrar_vista", "linhas_de_desenho", "grades", "celulas", "itens_da_tabela",
                    "conferir_itens", "circulos", "estacas_e_blocos", "registrar_pontos", "desenho_sem_hachura", "rotulos",
                    "pilares", "glifos", "ler_numero", "baloes",
                    "identidade", "elementos_por_layer", "servicos", "rotulos_da_lista", "niveis_da_tabela",
                    "ficha_estrutura", "ficha_hidraulica", "etapa", "ficha_leve", "lote", "resumo_lote", "blocos_com_nivel", "vetor_blocos", "vetor_pecas",
                    "solidos_3d", "para_html"],
        "bibliografia": [
            {"obra": "Fischler & Bolles — Random Sample Consensus", "ano": 1981, "editora": "Communications of the ACM",
             "aplicacao": {"registrar_pontos": ["hipótese por par de vizinhos", "tol_m=0,25"]}},
            {"obra": "Kasa — A circle fitting procedure and its error analysis", "ano": 1976,
             "editora": "IEEE Trans. Instrumentation and Measurement", "aplicacao": {"circulos": ["ajuste algébrico"]}},
            {"obra": "Smith — An Overview of the Tesseract OCR Engine", "ano": 2007, "editora": "ICDAR",
             "aplicacao": {"celulas": ["--psm 6"], "baloes": ["--psm 7, só dígitos"], "rotulos": ["--psm 11"]}},
        ],
        "premissas": [
            {"aplicacao": {"vistas": ["fechar_pt=12"]}, "estado": "premissa",
             "fonte": "vistas da folha separadas por mais de ~12 pt de vazio (f010: 7 vistas)"},
            {"aplicacao": {"solidos_3d": ["base = arrasamento"]}, "estado": "premissa",
             "fonte": "elevação genérica dos blocos (forma MOD01): estaca embutida ~5 cm no bloco, desprezado"},
            {"aplicacao": {"estacas_e_blocos": ["diametro_m=(0,25; 0,80)"]}, "estado": "premissa",
             "fonte": "estaca hélice contínua de Ø30 a Ø70 cm; o layer com mais círculos nesse diâmetro é o das estacas"},
        ],
    }
