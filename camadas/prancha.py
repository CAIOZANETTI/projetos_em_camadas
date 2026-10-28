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

import itertools
import json
import re
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import shapely
from shapely.geometry import LineString

from . import geo, pdf_cad

MM_PT = 25.4 / 72                                       # 1 pt = 0,3528 mm


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


def escala_do_titulo(pagina, caixa, faixa_pt: float = 60.0) -> int | None:
    """Denominador da escala escrita logo abaixo da vista ("ESCALA 1:100"); None se não houver."""
    import pymupdf
    x0, _, x1, y1 = caixa
    texto = _ocr(_imagem(pagina, pymupdf.Rect(x0, y1, x1, min(y1 + faixa_pt, pagina.rect.height)), 300), "--psm 11")
    m = re.search(r"ESC(?:ALA|\.)?\s*[:.]?\s*1\s*[:/]\s*(\d{1,4})", texto.upper().replace(" ", " "))
    return int(m[1]) if m else None


def escala_da_afim(M) -> float:
    """Denominador da escala implícita na afim pt → m (média dos dois eixos)."""
    A = np.asarray(M, float)[:2, :2]
    return float(np.sqrt(abs(np.linalg.det(A)))) / (MM_PT / 1000)


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
        if linhas >= min_linhas:
            out.append({"caixa": [x / k, y / k, (x + w) / k, (y + hh) / k], "linhas": linhas})
    dentro = lambda a, b: a is not b and b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]
    out = [t for t in out if not any(dentro(t["caixa"], u["caixa"]) for u in out)]   # sub-tabela fica na de fora
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


def itens_da_tabela(linhas: list[list[str]]) -> list[dict]:
    """Relação de materiais: a linha com 'DESCRI' é o cabeçalho e dá o índice de cada coluna; linha com uma só
    célula cheia é subtítulo (vários blocos na mesma tabela); linha com nº ou S/N na coluna 'N' é item."""
    itens, col, bloco = [], {}, ""
    for cel in linhas:
        cel = [c.strip() for c in cel]
        cheias = [c for c in cel if c]
        if any("DESCRI" in c.upper() for c in cel):
            col = {re.sub(r"[^A-Z]", "", pdf_cad._sem_acento(c))[:4]: k for k, c in enumerate(cel) if c}
            continue
        if len(cheias) == 1:
            bloco = cheias[0]
            continue
        kn = next((k for c, k in col.items() if c in ("N", "NO", "NR", "NUM", "ITEM")), None)   # "Nº" vira "NO"
        if kn is None or kn >= len(cel):
            continue
        n = cel[kn].upper().replace(" ", "")
        if not re.fullmatch(r"S/?N", n):
            n = n.translate(str.maketrans("OSIL", "0511"))          # "OS" lido no lugar de "05"
        if not re.fullmatch(r"\d{1,3}|S/?N", n):
            continue
        valor = {c: cel[k] for c, k in col.items() if k < len(cel)}
        pega = lambda *chaves, v=valor: next((x for c, x in v.items() if c.startswith(chaves)), "")
        itens.append({"n": "S/N" if "S" in n else n.zfill(2), "codigo": re.sub(r"\D", "", pega("ESPE", "COD")) or None,
                      "descricao": pega("DESC"), "qtde": pega("QTD"), "un": pega("UN"), "bloco": bloco})
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


def rotulos(pagina, poligonos: list, padrao: str = r"PC?\d{1,2}", dpis=(130, 160, 200), max_pt: float = 45.0) -> list:
    """Rótulo de cada elemento (PC12, P3…): OCR da vista inteira em três resoluções (a letra perto de 18 px), sem
    repetir a mesma palavra no mesmo lugar; depois cada rótulo vai ao elemento cujo contorno está mais perto
    (pares do mais próximo ao mais distante, cada um usado uma vez, até `max_pt`)."""
    import pymupdf
    import pytesseract
    from PIL import Image
    B = np.array([p.bounds for p in poligonos])
    x0, y0 = B[:, :2].min(0) - 60
    x1, y1 = B[:, 2:].max(0) + 60
    achados = []
    for dpi in dpis:
        d = pytesseract.image_to_data(Image.fromarray(_imagem(pagina, pymupdf.Rect(x0, y0, x1, y1), dpi)),
                                      config="--psm 11", output_type=pytesseract.Output.DICT)
        for w, l, t, ww, h in zip(d["text"], d["left"], d["top"], d["width"], d["height"]):
            txt, c = re.sub(r"[^A-Z0-9]", "", w.upper()), np.array([x0 + (l + ww / 2) * 72 / dpi, y0 + (t + h / 2) * 72 / dpi])
            if re.fullmatch(padrao, txt) and not any(a == txt and np.linalg.norm(b - c) < 6 for a, b in achados):
                achados.append((txt, c))
    pares = sorted((float(shapely.distance(p, shapely.Point(*c))), i, k) for i, p in enumerate(poligonos)
                   for k, (_, c) in enumerate(achados))
    out, usados = [None] * len(poligonos), set()
    for d, i, k in pares:
        nome = achados[k][0]
        if d <= max_pt and out[i] is None and k not in usados and nome not in out:
            out[i] = nome
            usados.add(k)
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


def baloes(tracos: list, layer: str, layer_numero: str | None = None, diametro_pt: tuple = (7.0, 14.0),
           validos: set | None = None) -> list[dict]:
    """Balões da lista de peças: círculo do layer; número = traços SHX dentro do círculo (do layer do texto, ou de
    qualquer layer), lidos por OCR numa imagem só com eles; peça = ponta da linha de chamada que sai do círculo."""
    partes = [np.asarray(q, float) for t in tracos if t["layer"] == layer for q in t["partes"] if len(q) >= 2]
    redondos = [q for q in partes if len(q) >= 8 and diametro_pt[0] <= np.ptp(q, axis=0).max() <= diametro_pt[1]]
    retas = [q for q in partes if len(q) == 2]
    letras = [np.asarray(q, float) for t in tracos if t["layer"] == (layer_numero or t["layer"]) and t["layer"] != layer
              for q in t["partes"] if len(q) >= 2 and np.ptp(np.asarray(q), axis=0).max() < diametro_pt[1]]
    centros = np.array([q.mean(0) for q in letras]).reshape(-1, 2)
    out = []
    for q in redondos:
        c, r = q.mean(0), np.ptp(q, axis=0).max() / 2
        dentro = [letras[k] for k in np.flatnonzero(np.linalg.norm(centros - c, axis=1) < r * 0.8)]
        num = ler_numero(dentro, validos) if dentro else None
        ponta = next((s[int(np.argmax(np.linalg.norm(s - c, axis=1)))] for s in retas
                      if np.linalg.norm(s - c, axis=1).min() < r * 1.3), None)
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
    """Piloto estrutura: estacas e blocos pela geometria, rótulos por OCR, encaixe nas estacas com E/N e níveis."""
    import csv
    pg, tr = _pagina(f["pdf"]), pdf_cad.extrair(f["pdf"])
    g = estacas_e_blocos(tr, escala=f["escala"])
    with open(ancoras, encoding="utf-8") as fh:
        linhas = list(csv.DictReader(fh, delimiter=";"))
    U = np.array([[float(r["E"]), float(r["N"])] for r in linhas])
    reg = registrar_pontos(g["estacas_pt"][:, :2], U, f["escala"])
    nomes = rotulos(pg, g["blocos_pt"])
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
    ids = [linhas[j]["id"] for j, ok in zip(reg.get("par", []), reg.get("casou", [])) if ok]
    log(f"Ficha {f['id']}: {len(g['estacas_pt'])} estacas (layer {g['layer_estacas']}), {len(blocos)} blocos "
        f"(layer {g['layer_blocos']}), encaixe {reg.get('inliers')}/{reg.get('total')} a {reg.get('residuo_mediano_m')} m")
    return {"estacas": len(g["estacas_pt"]), "layer_estacas": g["layer_estacas"], "layer_blocos": g["layer_blocos"],
            "estacas_nos_blocos": g["estacas_nos_blocos"], "blocos": blocos, "niveis": niveis,
            "encaixe": {k: v for k, v in reg.items() if k not in ("par", "casou", "M")} | {
                "M": None if not reg["ok"] else np.asarray(reg["M"]).round(9).tolist(),
                "estruturas": sorted({i.rsplit("-", 1)[0] for i in ids})}}


def ficha_hidraulica(f: dict, M, cadastro: dict, contrato: list[dict], log=print) -> dict:
    """Piloto hidráulica: vistas e escala, relação de materiais (OCR) e balões → itens."""
    pg, tr = _pagina(f["pdf"]), pdf_cad.extrair(f["pdf"])
    vs = []
    for caixa in vistas(tr, pg.rect.width, pg.rect.height):
        esc = escala_do_titulo(pg, caixa)
        afim = round(escala_da_afim(M)) if M is not None else None
        vs.append({"caixa": [round(x, 1) for x in caixa], "escala_titulo": esc, "escala_afim": afim,
                   "georreferenciada": bool(esc and afim and abs(afim / esc - 1) < 0.03)})
    itens = []
    for t in grades(pg):
        it = itens_da_tabela(celulas(pg, t["caixa"]))
        if it:
            itens += conferir_itens(it, cadastro, contrato)
    numeros = {i["n"] for i in itens}
    bs = baloes(tr, f["layer_balao"], f.get("layer_numero"), validos=numeros)
    for b in bs:
        b["item"] = b["n"] if b["n"] in numeros else None
    com_balao = {b["n"] for b in bs}
    log(f"Ficha {f['id']}: {len(vs)} vistas ({sum(v['georreferenciada'] for v in vs)} georreferenciadas), "
        f"{len(itens)} itens, {len(bs)} balões ({sum(b['item'] is not None for b in bs)} com item)")
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
        pdf = Path(f.get("pdf") or por_id[f["id"]]["pdf"])
        assinatura = f"{pdf.stat().st_size}:{int(pdf.stat().st_mtime)}:{json.dumps(f, sort_keys=True)}"
        if cache.get(f["id"], {}).get("assinatura") != assinatura:
            f = {**f, "pdf": str(pdf)}
            tr = pdf_cad.extrair(pdf)
            corpo = ficha_estrutura(f, Path(f["ancoras"]), log) if f["piloto"] == "estrutura" else ficha_hidraulica(
                f, por_id.get(f["id"], {}).get("M"), cad, [i for i in (escopo or {}).get("itens", []) if i["tabela"] in f.get("tabelas", [])], log)
            el = elementos_por_layer(tr)
            cache[f["id"]] = {"assinatura": assinatura, "ficha": {
                "id": f["id"], "nome": f.get("nome", pdf.stem), "piloto": f["piloto"], "identidade": identidade(pdf),
                "elementos": el, "servicos": servicos(list(el)), **corpo}}
            arq.write_text(json.dumps(cache, ensure_ascii=False))
        fichas.append(cache[f["id"]]["ficha"])
    return fichas


def blocos_com_nivel(fichas: list[dict]) -> list[dict]:
    """Blocos das fichas de estrutura com contorno em UTM (o encaixe deu certo)."""
    return [{**b, "ficha": f["id"]} for f in fichas if f["piloto"] == "estrutura" for b in f["blocos"]
            if b.get("contorno_utm")]


def vetor_blocos(fichas: list[dict], epsg: int) -> dict | None:
    """Camada do mapa: blocos lidos na forma, com rótulo, nº de estacas e níveis."""
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
    return {"id": "blocos_forma", "nome": f"Blocos de fundação lidos na forma ({len(feats)})", "grupo": "Civil",
            "subgrupo": "Geotecnia e fundação", "visivel": False,
            "geojson": {"type": "FeatureCollection", "features": feats},
            "estilo": {"color": "#57534e", "weight": 1.5, "fillColor": "#a8a29e", "fillOpacity": 0.6}}


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
                    "blocos": [{k: v for k, v in b.items() if k != "contorno_utm"} for b in f.get("blocos", [])]})
    return out


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "prancha",
        "descricao": "ficha da prancha: vistas e escala, tabelas por OCR, elementos por layer ou geometria, balões → "
                     "itens, estacas → E/N (RANSAC) e blocos em UTM",
        "funcoes": ["vistas", "escala_do_titulo", "escala_da_afim", "grades", "celulas", "itens_da_tabela",
                    "conferir_itens", "circulos", "estacas_e_blocos", "registrar_pontos", "rotulos", "glifos", "ler_numero", "baloes",
                    "identidade", "elementos_por_layer", "servicos", "rotulos_da_lista", "niveis_da_tabela",
                    "ficha_estrutura", "ficha_hidraulica", "etapa", "blocos_com_nivel", "vetor_blocos",
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
