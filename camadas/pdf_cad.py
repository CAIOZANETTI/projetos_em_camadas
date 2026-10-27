"""Pranchas CAD plotadas em PDF vetorial -> traços por layer e cor -> GeoJSON.

A maioria das pranchas da Sanepar (e de projetistas que plotam do AutoCAD com
"criar layers PDF") traz os layers do CAD como OCG e o texto convertido em vetor.
Este módulo aproveita isso sem depender do DWG:

    tr = extrair("004-...LAYOUTPROCES-R5.pdf")             # traços (dict) com layer, cor, preenchimento
    cls = classificar(tr, regras("etapas_sanepar"))         # classe por layer/cor (conceitos/*.json)
    img, k = rasterizar(tr, dpi=50, filtro=lambda t: ...)   # para registrar com a ortofoto
    pac = pacote_vetorial(pdf)                              # prancha inteira em vetor para o HTML

Traço = dict {"layer", "cor", "preenchimento", "largura", "partes", "fechado", "tracejado"}:
cores RGB 0–1 (ou None) e `partes` = lista de arrays (N, 2) em pt, uma por subcaminho.

Coordenadas: "pt" = pontos PDF (1/72") com origem no canto superior esquerdo da
página (convenção do PyMuPDF, y para baixo). O georreferenciamento é uma matriz
3x3 pt -> UTM (camadas.geo.ajustar com pontos de controle ou camadas.georef_prancha).
"""
from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import cv2
import numpy as np

from . import geo


CONCEITOS = Path(__file__).resolve().parents[1] / "conceitos"


def caixa(traco: dict) -> tuple:
    """(x0, y0, x1, y1) em pt de todas as partes do traço."""
    pontos = np.vstack(traco["partes"])
    return (*pontos.min(0), *pontos.max(0))


def _rotacao(pg) -> np.ndarray | None:
    """Matriz 3x3 do espaço sem rotação (o de get_drawings/get_text) para o espaço exibido
    da página (/Rotate 90/180/270). Tudo neste módulo trabalha no espaço exibido."""
    if not pg.rotation:
        return None
    m = pg.rotation_matrix
    return np.array([[m.a, m.c, m.e], [m.b, m.d, m.f], [0, 0, 1]])


def _aplicar_rot(R: np.ndarray, p: np.ndarray) -> np.ndarray:
    return p @ R[:2, :2].T + R[:2, 2]


def _cor(c) -> tuple | None:
    return tuple(round(float(x), 3) for x in c) if c else None


def _bezier(p0, p1, p2, p3, n: int) -> list:
    t = np.linspace(0, 1, n + 1)[1:, None]
    u = 1 - t
    a = np.array([[p0.x, p0.y], [p1.x, p1.y], [p2.x, p2.y], [p3.x, p3.y]])
    return list(u ** 3 * a[0] + 3 * u * u * t * a[1] + 3 * u * t * t * a[2] + t ** 3 * a[3])


def _partes_do_desenho(itens: list, n_bezier: int) -> list[np.ndarray]:
    """Itens de um desenho do PyMuPDF (l, c, re, qu) -> subcaminhos contínuos (arrays N×2 em pt)."""
    partes, atual, ultimo = [], [], None
    for item in itens:
        operacao = item[0]
        if operacao == "re":
            q = item[1]
            partes.append(np.array([[q.x0, q.y0], [q.x1, q.y0], [q.x1, q.y1], [q.x0, q.y1], [q.x0, q.y0]]))
            continue
        if operacao == "qu":
            q = item[1]
            partes.append(np.array([[q.ul.x, q.ul.y], [q.ur.x, q.ur.y], [q.lr.x, q.lr.y], [q.ll.x, q.ll.y],
                                    [q.ul.x, q.ul.y]]))
            continue
        inicio = item[1]
        if ultimo is None or abs(inicio.x - ultimo[0]) > 1e-3 or abs(inicio.y - ultimo[1]) > 1e-3:
            if len(atual) > 1:
                partes.append(np.array(atual))
            atual = [[inicio.x, inicio.y]]
        if operacao == "l":
            atual.append([item[2].x, item[2].y])
        elif operacao == "c":
            atual += _bezier(item[1], item[2], item[3], item[4], n_bezier)
        ultimo = atual[-1]
    if len(atual) > 1:
        partes.append(np.array(atual))
    return partes


def extrair(caminho: str | Path, pagina: int = 0, n_bezier: int = 6, layers: set | None = None,
            clip=None) -> list[dict]:
    """Traços vetoriais da página separados em subcaminhos contínuos.

    Não emenda subcaminhos (evita segmentos espúrios
    entre peças desconexas do mesmo bloco). `clip` = (x0, y0, x1, y1) em pt para
    ignorar carimbo e tabelas. Requer PyMuPDF.
    """
    import pymupdf
    out = []
    with pymupdf.open(caminho) as doc:
        pg = doc[pagina]
        R = _rotacao(pg)
        if clip is not None and R is not None:
            # clip é dado no espaço exibido; leva para o espaço sem rotação do PyMuPDF
            q = _aplicar_rot(np.linalg.inv(R), np.array([[clip[0], clip[1]], [clip[2], clip[3]]]))
            clip = (*q.min(0), *q.max(0))
        for d in pg.get_drawings():
            layer = d.get("layer") or ""
            if layers is not None and layer not in layers:
                continue
            r = d.get("rect")
            if clip is not None and r is not None and (r.x1 < clip[0] or r.x0 > clip[2] or r.y1 < clip[1] or r.y0 > clip[3]):
                continue
            partes = _partes_do_desenho(d["items"], n_bezier)
            if not partes:
                continue
            if R is not None:
                partes = [_aplicar_rot(R, q) for q in partes]
            out.append({"layer": layer, "cor": _cor(d.get("color")), "preenchimento": _cor(d.get("fill")),
                        "largura": float(d.get("width") or 0), "partes": partes,
                        "fechado": bool(d.get("closePath")) or d.get("fill") is not None,
                        "tracejado": bool(d.get("dashes")) and d.get("dashes") not in ("[] 0", "[] 0.0")})
    return out


def layers_pdf(caminho: str | Path) -> list[str]:
    """Nomes dos layers (OCG) do PDF."""
    import pymupdf
    with pymupdf.open(caminho) as doc:
        return [o["name"] for o in (doc.get_ocgs() or {}).values()]


def regras(nome: str) -> list[dict]:
    """Regras de classificação de `conceitos/<nome>.json` (classe por layer regex e/ou cor)."""
    dados = json.loads((CONCEITOS / f"{nome}.json").read_text(encoding="utf-8"))
    return [{**r, "cor": tuple(r["cor"]) if r.get("cor") else None} for r in dados["regras"]]


def casa(regra: dict, traco: dict) -> bool:
    """O traço pertence à classe da regra? Layer por regex; cor de contorno ou preenchimento."""
    if regra.get("layer") is not None and not re.search(regra["layer"], traco["layer"], re.I):
        return False
    if regra.get("cor") is None:
        return True
    tolerancia = regra.get("tol", 0.06)
    return any(c is not None and max(abs(a - b) for a, b in zip(c, regra["cor"])) <= tolerancia
               for c in (traco["preenchimento"], traco["cor"]))


def classificar(tracos: list[dict], lista_regras: list[dict]) -> list[str | None]:
    """Primeira regra que casa com cada traço (None = sem classe)."""
    return [next((r["classe"] for r in lista_regras if casa(r, t)), None) for t in tracos]


@functools.lru_cache(maxsize=1)
def disciplinas() -> dict:
    """`conceitos/disciplinas.json`: grupos, regras de prancha e de layer (com metadata e fonte)."""
    return json.loads((CONCEITOS / "disciplinas.json").read_text(encoding="utf-8"))


def disciplina_da_prancha(nome: str, titulo: str = "") -> tuple[str, str]:
    """(grupo, subgrupo) pelo código Sanepar no nome do arquivo (PBGE, PBES, PARQ, PBHI, PBME, PBEA) e pelo título."""
    alvo = f"{nome} {titulo}".upper()
    for regra in disciplinas()["prancha"]:
        if re.search(regra["regex"], alvo):
            return regra["grupo"], regra["subgrupo"]
    return "Geral", "Base / outros"


def disciplina_do_layer(nome_layer: str, padrao: tuple[str, str]) -> tuple[str, str]:
    """Grupo do layer pelo nome (ex.: DRENAGEM numa prancha hidráulica vai para Civil › Drenagem);
    sem casamento, herda o da prancha."""
    alvo = nome_layer.upper()
    for regra in disciplinas()["layer"]:
        if re.search(regra["regex"], alvo):
            return regra["grupo"], regra["subgrupo"]
    return padrao


def rasterizar(tracos: list[dict], dpi: float = 50, tamanho_pt=None, espessura: int = 1,
               filtro=None, cor=255) -> tuple[np.ndarray, float]:
    """Desenha os traços (uint8, fundo 0). Retorna (imagem, px por pt)."""
    k = dpi / 72
    if tamanho_pt is None:
        b = np.array([caixa(t) for t in tracos])
        tamanho_pt = (b[:, 2].max(), b[:, 3].max())
    img = np.zeros((int(tamanho_pt[1] * k) + 1, int(tamanho_pt[0] * k) + 1), np.uint8)
    for t in tracos:
        if filtro is not None and not filtro(t):
            continue
        pts = [np.round(p * k).astype(np.int32) for p in t["partes"]]
        if t["preenchimento"] is not None:
            cv2.fillPoly(img, pts, cor)
        cv2.polylines(img, pts, t["fechado"], cor, espessura, cv2.LINE_AA)
    return img, k


def manchas(tracos: list[dict], classes: list, classe: str, M: np.ndarray, epsg: int,
            res_m: float = 0.10, fechar_m: float = 0.3, min_area_m2: float = 2.0,
            simplificar_m: float = 0.10) -> dict:
    """Polígonos fundidos ("manchas") de todos os traços de uma classe — hachuras e
    preenchimentos viram uma área por estrutura, com área (m²) calculada no plano UTM."""
    sel = [t for t, c in zip(tracos, classes) if c == classe]
    if not sel:
        return {"type": "FeatureCollection", "features": []}
    pts = np.vstack([geo.aplicar(M, np.vstack(t["partes"])) for t in sel])
    e0, n0 = pts.min(0) - 2
    e1, n1 = pts.max(0) + 2
    W, H = int((e1 - e0) / res_m) + 1, int((n1 - n0) / res_m) + 1
    img = np.zeros((H, W), np.uint8)
    for t in sel:
        cs = [np.round(np.c_[(u[:, 0] - e0) / res_m, (n1 - u[:, 1]) / res_m]).astype(np.int32)
              for u in (geo.aplicar(M, p) for p in t["partes"])]
        if t["preenchimento"] is not None:
            cv2.fillPoly(img, cs, 255)
        cv2.polylines(img, cs, t["fechado"], 255, max(1, int(0.15 / res_m)))
    k = max(1, int(fechar_m / res_m)) * 2 + 1
    img = cv2.morphologyEx(img, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
    cont, hier = cv2.findContours(img, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    feats = []
    for i, c in enumerate(cont):
        if hier[0][i][3] != -1:
            continue                                   # buracos entram como anéis internos
        aneis = [c] + [cont[j] for j in range(len(cont)) if hier[0][j][3] == i]
        area = (cv2.contourArea(c) - sum(cv2.contourArea(a) for a in aneis[1:])) * res_m ** 2
        if area < min_area_m2:
            continue
        coords = []
        for a in aneis:
            a = cv2.approxPolyDP(a, simplificar_m / res_m, True).reshape(-1, 2).astype(float)
            if len(a) < 3:
                continue
            E, N = e0 + a[:, 0] * res_m, n1 - a[:, 1] * res_m
            lon, lat = geo.para_lonlat(E, N, epsg)
            r = np.c_[lon, lat].round(8).tolist()
            coords.append(r + r[:1])
        if coords:
            feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": coords},
                          "properties": {"classe": classe, "area_m2": round(float(area), 1)}})
    return {"type": "FeatureCollection", "features": feats}


def _hex(c) -> str | None:
    return None if c is None else "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c[:3])


def _b64gz(a: np.ndarray) -> str:
    import base64
    import gzip
    return base64.b64encode(gzip.compress(np.ascontiguousarray(a).tobytes(), 6)).decode()


def _texto_legivel(t: str) -> bool:
    """Descarta spans de fonte sem ToUnicode (viram lixo tipo '\x18ŝŵĞŶƐĆŽ')."""
    ok = sum(c.isascii() and c.isprintable() or c in "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇºª°²³±Ø∅" for c in t)
    return ok / len(t) >= 0.9


def textos_pdf(caminho: str | Path, pagina: int = 0) -> list[dict]:
    """Textos "de verdade" da página (spans), com posição, direção, altura e layer
    quando o PDF informa. Em pranchas com texto convertido em curvas a lista vem vazia
    — o texto continua visível como vetor nos layers de texto."""
    import pymupdf
    out = []
    with pymupdf.open(caminho) as doc:
        pg = doc[pagina]
        R = _rotacao(pg)
        spans = ((linha, span) for bloco in pg.get_text("dict")["blocks"]
                 for linha in bloco.get("lines", []) for span in linha["spans"])
        for linha, span in spans:
            texto = span["text"].strip()
            if not texto or not _texto_legivel(texto):
                continue
            origem, direcao = np.array([span["origin"]], float), np.array(linha["dir"], float)
            if R is not None:
                origem, direcao = _aplicar_rot(R, origem), R[:2, :2] @ direcao
            cor = span["color"]
            out.append({"t": texto, "x": round(float(origem[0, 0]), 2), "y": round(float(origem[0, 1]), 2),
                        "a": round(float(np.degrees(np.arctan2(-direcao[1], direcao[0]))), 1),
                        "h": round(span["size"], 2),
                        "cor": _hex([((cor >> 16) & 255) / 255, ((cor >> 8) & 255) / 255, (cor & 255) / 255])})
    return out


def pacote_vetorial(caminho: str | Path, lista_regras: list[dict] | None = None, pagina: int = 0,
                    simplificar_pt: float = 0.25) -> dict:
    """Prancha inteira em vetor, compacta, para o visualizador (sem rasterizar nada).

    Retorna:
      largura/altura (pt), layers [{nome, n, cor, classe}], estilos [{s, f, w}],
      geometria (gzip+base64):
        coords: Int32 com deltas de (x, y)·10 — 0,1 pt de precisão, encadeados entre partes
        partes: Uint32 [n_pontos, layer, estilo, flags] por subcaminho (flags: 1 fechado, 2 preenchido)
      textos: spans de texto com posição (pt), ângulo e altura.
    """
    import pymupdf
    with pymupdf.open(caminho) as doc:
        r = doc[pagina].rect
        largura, altura = float(r.width), float(r.height)
    tr = extrair(caminho, pagina)
    layers, estilos = {}, {}
    cls = classificar(tr, lista_regras) if lista_regras else [None] * len(tr)
    coords, partes = [], []
    ult = np.zeros(2, np.int32)
    for t, c in zip(tr, cls):
        li = layers.setdefault(t["layer"], {"i": len(layers), "nome": t["layer"], "n": 0, "cores": {}, "classe": c})
        li["n"] += 1
        cor = _hex(t["cor"]) or _hex(t["preenchimento"]) or "#000000"
        li["cores"][cor] = li["cores"].get(cor, 0) + 1
        chave = (_hex(t["cor"]), _hex(t["preenchimento"]), round(t["largura"], 2))
        ei = estilos.setdefault(chave, len(estilos))
        flags = (1 if t["fechado"] else 0) | (2 if t["preenchimento"] is not None else 0)
        for p in t["partes"]:
            q = p if simplificar_pt <= 0 or len(p) < 3 else \
                cv2.approxPolyDP(p.astype(np.float32).reshape(-1, 1, 2), simplificar_pt, False).reshape(-1, 2)
            qi = np.round(q * 10).astype(np.int32)
            d = np.diff(np.vstack([ult, qi]), axis=0)
            ult = qi[-1]
            coords.append(d)
            partes.append((len(qi), li["i"], ei, flags))
    coords = np.vstack(coords).astype("<i4")      # Int32: saltos entre partes passam de 3276 pt
    lista_layers = sorted(layers.values(), key=lambda l: l["i"])
    return {
        "largura": largura, "altura": altura,
        "layers": [{"nome": l["nome"], "n": l["n"], "classe": l["classe"],
                    "cor": max(l["cores"], key=l["cores"].get)} for l in lista_layers],
        "estilos": [{"s": s, "f": f, "w": w} for (s, f, w) in estilos],
        "coords": _b64gz(coords), "partes": _b64gz(np.array(partes, "<u4")),
        "n_partes": len(partes), "n_pontos": int(len(coords)),
        "textos": textos_pdf(caminho, pagina),
    }


def separar_por_cor(img: np.ndarray, cores: list, tol: float = 40.0, fundo=(255, 255, 255)) -> list[np.ndarray]:
    """Uma máscara alfa (uint8) por camada.

    Cada camada pode ter várias cores (lista de rgb 0–1). Para cada pixel p,
    estima-se a cobertura a de uma linha de cor c sobre o fundo branco
    (p ≈ a·c + (1−a)·fundo, projeção no segmento fundo–c) e aceita-se se o
    desvio perpendicular ao segmento for < tol. Isso recupera o
    antisserrilhado das linhas finas em vez de cortar por limiar.
    O pixel vai para a camada de menor desvio.
    """
    p = img.reshape(-1, 3).astype(np.float32)
    f = np.asarray(fundo, np.float32)
    d = f - p                                       # "tinta" do pixel
    melhor = np.full(len(p), np.inf, np.float32)
    dono = np.full(len(p), -1, np.int32)
    alfa = np.zeros(len(p), np.float32)
    for k, cam in enumerate(cores):
        cam = cam if isinstance(cam[0], (list, tuple, np.ndarray)) else [cam]
        for rgb in cam:
            c = f - np.asarray(rgb, np.float32) * 255
            cc = float(c @ c)
            if cc < 1:
                continue
            a = np.clip((d @ c) / cc, 0, 1)
            desvio = np.linalg.norm(d - a[:, None] * c, axis=1)
            ok = (desvio < tol) & (a > 0.08) & (desvio < melhor)
            melhor[ok], dono[ok], alfa[ok] = desvio[ok], k, a[ok]
    h, w = img.shape[:2]
    return [np.where(dono == k, alfa * 255, 0).astype(np.uint8).reshape(h, w) for k in range(len(cores))]


def empacotar(mascaras: list[np.ndarray]) -> list[np.ndarray]:
    """Agrupa as máscaras de 3 em 3 em imagens BGR (canal R = 1ª, G = 2ª, B = 3ª).

    Gravar com webp sem perdas (cv2.IMWRITE_WEBP_QUALITY=101); o visualizador
    lê os canais R, G, B nessa ordem.
    """
    out = []
    for i in range(0, len(mascaras), 3):
        trio = mascaras[i:i + 3] + [np.zeros_like(mascaras[0])] * (3 - len(mascaras[i:i + 3]))
        out.append(np.dstack([trio[2], trio[1], trio[0]]))
    return out


def desempacotar(pacotes: list[np.ndarray], n: int) -> list[np.ndarray]:
    m = []
    for p in pacotes:
        m += [p[..., 2], p[..., 1], p[..., 0]]
    return m[:n]


def decodificar_pacote(pacote: dict) -> tuple[np.ndarray, np.ndarray]:
    """Inverso de `pacote_vetorial`: (pontos em pt (N×2), partes (P×4): n_pontos, layer, estilo, flags)."""
    import base64
    import gzip
    deltas = np.frombuffer(gzip.decompress(base64.b64decode(pacote["coords"])), "<i4").reshape(-1, 2)
    partes = np.frombuffer(gzip.decompress(base64.b64decode(pacote["partes"])), "<u4").reshape(-1, 4)
    return np.cumsum(deltas.astype(np.int64), axis=0) / 10, partes


def quantitativos(pacote: dict) -> list[dict]:
    """Comprimento de traço (m) e área preenchida (m²) por layer CAD dentro de `clip_mapa`, pela afim pt -> UTM.

    É medida do desenho, não do objeto: tubulação em linha dupla conta duas vezes, hachura e texto em curvas ficam
    de fora (só a contagem). Serve para conferir ordem de grandeza contra o orçamento, não para substituí-lo.
    """
    pontos_pt, partes = decodificar_pacote(pacote)
    afim = np.asarray(pacote["M"], float).reshape(2, 3)
    utm = pontos_pt @ afim[:, :2].T + afim[:, 2]
    n_pontos = partes[:, 0].astype(np.int64)
    inicio = np.r_[0, np.cumsum(n_pontos)[:-1]]
    x0, y0, x1, y1 = pacote["clip_mapa"] or (0, 0, pacote["largura"], pacote["altura"])
    dentro = ((np.maximum.reduceat(pontos_pt[:, 0], inicio) >= x0) & (np.minimum.reduceat(pontos_pt[:, 0], inicio) <= x1)
              & (np.maximum.reduceat(pontos_pt[:, 1], inicio) >= y0) & (np.minimum.reduceat(pontos_pt[:, 1], inicio) <= y1))
    segmento = np.r_[np.hypot(*np.diff(utm, axis=0).T), 0.0]
    segmento[np.cumsum(n_pontos) - 1] = 0.0                      # sem o salto entre o fim de uma parte e a próxima
    comprimento = np.add.reduceat(segmento, inicio)
    cruzado = utm[:, 0] * np.roll(utm[:, 1], -1) - np.roll(utm[:, 0], -1) * utm[:, 1]
    fim = np.cumsum(n_pontos) - 1
    cruzado[fim] = utm[fim, 0] * utm[inicio, 1] - utm[inicio, 0] * utm[fim, 1]   # fecha cada anel no próprio início
    area = np.abs(np.add.reduceat(cruzado, inicio)) / 2
    preenchido = (partes[:, 3] & 2) > 0
    linhas = []
    for indice, layer in enumerate(pacote["layers"]):
        sel = dentro & (partes[:, 1] == indice)
        if not sel.any():
            continue
        ignorado = bool(re.search(r"HACHURA|TEXTO|TXT|CARIMBO|LOGO", layer["nome"], re.I))
        linhas.append({"layer": layer["nome"], "grupo": layer.get("grupo"), "subgrupo": layer.get("subgrupo"),
                       "classe": layer.get("classe"), "n_partes": int(sel.sum()),
                       "comprimento_m": None if ignorado else round(float(comprimento[sel & ~preenchido].sum()), 2),
                       "area_m2": None if ignorado else round(float(area[sel & preenchido].sum()), 2)})
    return sorted(linhas, key=lambda l: -(l["comprimento_m"] or 0))
