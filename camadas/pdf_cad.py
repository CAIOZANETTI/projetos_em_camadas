"""Pranchas CAD plotadas em PDF vetorial -> traços por layer e cor -> GeoJSON.

A maioria das pranchas da Sanepar (e de projetistas que plotam do AutoCAD com
"criar layers PDF") traz os layers do CAD como OCG e o texto convertido em vetor.
Este módulo aproveita isso sem depender do DWG:

    tr = extrair("004-...LAYOUTPROCES-R5.pdf")             # traços com layer, cor, preenchimento
    resumo_layers(tr)                                       # DataFrame: layer × nº × cores
    cls = classificar(tr, REGRAS_ETAPA_SANEPAR)             # classe por layer/cor (ex.: etapa)
    img = rasterizar(tr, dpi=50, filtro=lambda t: ...)      # para registrar com a ortofoto
    fc = para_geojson(tr, M_pt_utm, epsg, filtro=...)       # FeatureCollection lon/lat

Coordenadas: "pt" = pontos PDF (1/72") com origem no canto superior esquerdo da
página (convenção do PyMuPDF, y para baixo). O georreferenciamento é uma matriz
3x3 pt -> UTM (camadas.geo.ajustar com pontos de controle ou camadas.georef_prancha).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import geo


@dataclass
class Traco:
    layer: str
    cor: tuple | None            # contorno RGB 0–1
    preenchimento: tuple | None  # preenchimento RGB 0–1
    largura: float
    partes: list = field(default_factory=list)   # lista de arrays (N, 2) em pt, uma por subcaminho
    fechado: bool = False
    tracejado: bool = False

    @property
    def bbox(self) -> tuple:
        p = np.vstack(self.partes)
        return (*p.min(0), *p.max(0))


def _rotacao(pg) -> np.ndarray | None:
    """Matriz 3x3 do espaço sem rotação (o de get_drawings/get_text) para o espaço exibido
    da página (/Rotate 90/180/270). Tudo neste módulo trabalha no espaço exibido."""
    if not pg.rotation:
        return None
    m = pg.rotation_matrix
    return np.array([[m.a, m.c, m.e], [m.b, m.d, m.f], [0, 0, 1]])


def _aplicar_rot(R: np.ndarray, p: np.ndarray) -> np.ndarray:
    return p @ R[:2, :2].T + R[:2, 2]


def _bezier(p0, p1, p2, p3, n: int) -> list:
    t = np.linspace(0, 1, n + 1)[1:, None]
    u = 1 - t
    a = np.array([[p0.x, p0.y], [p1.x, p1.y], [p2.x, p2.y], [p3.x, p3.y]])
    return list(u ** 3 * a[0] + 3 * u * u * t * a[1] + 3 * u * t * t * a[2] + t ** 3 * a[3])


def extrair(caminho: str | Path, pagina: int = 0, n_bezier: int = 6, layers: set | None = None,
            clip=None) -> list[Traco]:
    """Traços vetoriais da página separados em subcaminhos contínuos.

    Diferente de `folha.vetores_pdf`, não emenda subcaminhos (evita segmentos espúrios
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
            partes, atual, ult = [], [], None
            for it in d["items"]:
                op = it[0]
                if op == "re":
                    q = it[1]
                    partes.append(np.array([[q.x0, q.y0], [q.x1, q.y0], [q.x1, q.y1], [q.x0, q.y1], [q.x0, q.y0]]))
                    continue
                if op == "qu":
                    q = it[1]
                    partes.append(np.array([[q.ul.x, q.ul.y], [q.ur.x, q.ur.y], [q.lr.x, q.lr.y],
                                            [q.ll.x, q.ll.y], [q.ul.x, q.ul.y]]))
                    continue
                ini = it[1]
                if ult is None or abs(ini.x - ult[0]) > 1e-3 or abs(ini.y - ult[1]) > 1e-3:
                    if len(atual) > 1:
                        partes.append(np.array(atual))
                    atual = [[ini.x, ini.y]]
                if op == "l":
                    atual.append([it[2].x, it[2].y])
                elif op == "c":
                    atual += _bezier(it[1], it[2], it[3], it[4], n_bezier)
                ult = atual[-1]
            if len(atual) > 1:
                partes.append(np.array(atual))
            if not partes:
                continue
            if R is not None:
                partes = [_aplicar_rot(R, q) for q in partes]
            arr = lambda c: tuple(round(float(x), 3) for x in c) if c else None
            out.append(Traco(layer, arr(d.get("color")), arr(d.get("fill")), float(d.get("width") or 0),
                             partes, bool(d.get("closePath")) or d.get("fill") is not None,
                             bool(d.get("dashes")) and d.get("dashes") not in ("[] 0", "[] 0.0")))
    return out


def layers_pdf(caminho: str | Path) -> list[str]:
    """Nomes dos layers (OCG) do PDF."""
    import pymupdf
    with pymupdf.open(caminho) as doc:
        return [o["name"] for o in (doc.get_ocgs() or {}).values()]


def resumo_layers(tracos: list[Traco]):
    """DataFrame com nº de traços e cores mais frequentes por layer (para montar as regras)."""
    import collections
    import pandas as pd
    linhas = collections.defaultdict(lambda: {"n": 0, "cores": collections.Counter(), "preench": collections.Counter()})
    for t in tracos:
        l = linhas[t.layer]
        l["n"] += 1
        if t.cor:
            l["cores"][t.cor] += 1
        if t.preenchimento:
            l["preench"][t.preenchimento] += 1
    return pd.DataFrame([{"layer": k, "n": v["n"], "cores": v["cores"].most_common(3),
                          "preenchimentos": v["preench"].most_common(3)} for k, v in linhas.items()]
                        ).sort_values("n", ascending=False, ignore_index=True)


# --- classificação por regras -------------------------------------------------
@dataclass
class Regra:
    """Uma classe (ex.: '1ª etapa') definida por layer (regex) e/ou cor RGB 0–1."""
    classe: str
    layer: str | None = None          # regex aplicada ao nome do layer
    cor: tuple | None = None          # cor de contorno OU preenchimento
    tol: float = 0.06
    so_preenchimento: bool = False
    rotulo: str = ""
    estilo: dict = field(default_factory=dict)

    def casa(self, t: Traco) -> bool:
        if self.layer is not None and not re.search(self.layer, t.layer, re.I):
            return False
        if self.cor is None:
            return True
        cores = [t.preenchimento] if self.so_preenchimento else [t.preenchimento, t.cor]
        return any(c is not None and max(abs(a - b) for a, b in zip(c, self.cor)) <= self.tol for c in cores)


# Convenções da prancha de layout da Sanepar (ETA Vila C, folha 04): cores = etapas.
REGRAS_ETAPA_SANEPAR = [
    Regra("1ª etapa", layer=r"_PROJETADOS", cor=(0.0, 0.43, 0.87), rotulo="Projetado — 1ª etapa",
          estilo={"color": "#0b6fde", "fillOpacity": 0.45}),
    Regra("2ª etapa", layer=r"_PROJETADOS", cor=(0.66, 0.33, 0.63), rotulo="Projetado — 2ª etapa",
          estilo={"color": "#a855a1", "fillOpacity": 0.45}),
    Regra("3ª etapa (futura)", layer=r"_UNIDADES FUTURAS", rotulo="Unidades futuras — 3ª etapa",
          estilo={"color": "#ef4444", "fillOpacity": 0.15, "dashArray": "4 3"}),
    Regra("Existente a reestruturar", layer=r"_EXISTENTES A REESTRUTURAR", rotulo="Existente a restaurar/reformar",
          estilo={"color": "#5cb85c", "fillOpacity": 0.2}),
    Regra("Existente a manter", layer=r"LINHA_UNI_EXISTENTES", rotulo="Existente a manter",
          estilo={"color": "#f59e0b", "weight": 1}),
    Regra("Tubulação", layer=r"TUBULA", rotulo="Tubulações (traço preto)", estilo={"color": "#111827", "weight": 1}),
    Regra("Equipamentos", layer=r"EQUIPAMENTOS|BOMBAS|COMPORTAS|Valvulas", rotulo="Equipamentos, bombas, válvulas",
          estilo={"color": "#334155", "weight": 1}),
]


def classificar(tracos: list[Traco], regras: list[Regra]) -> list[str | None]:
    """Primeira regra que casa com cada traço (None = sem classe)."""
    return [next((r.classe for r in regras if r.casa(t)), None) for t in tracos]


# --- raster e GeoJSON ----------------------------------------------------------
def rasterizar(tracos: list[Traco], dpi: float = 50, tamanho_pt=None, espessura: int = 1,
               filtro=None, cor=255) -> tuple[np.ndarray, float]:
    """Desenha os traços (uint8, fundo 0). Retorna (imagem, px por pt)."""
    k = dpi / 72
    if tamanho_pt is None:
        b = np.array([t.bbox for t in tracos])
        tamanho_pt = (b[:, 2].max(), b[:, 3].max())
    img = np.zeros((int(tamanho_pt[1] * k) + 1, int(tamanho_pt[0] * k) + 1), np.uint8)
    for t in tracos:
        if filtro is not None and not filtro(t):
            continue
        pts = [np.round(p * k).astype(np.int32) for p in t.partes]
        if t.preenchimento is not None:
            cv2.fillPoly(img, pts, cor)
        cv2.polylines(img, pts, t.fechado, cor, espessura, cv2.LINE_AA)
    return img, k


def _simplificar(p: np.ndarray, tol: float) -> np.ndarray:
    if len(p) < 3 or tol <= 0:
        return p
    s = cv2.approxPolyDP(p.astype(np.float32).reshape(-1, 1, 2), tol, False).reshape(-1, 2)
    return s if len(s) >= 2 else p[[0, -1]]


def para_geojson(tracos: list[Traco], M: np.ndarray, epsg: int, classes: list | None = None,
                 filtro=None, propriedades: dict | None = None, simplificar_m: float = 0.05,
                 unir_poligonos: bool = False) -> dict:
    """FeatureCollection (lon/lat, RFC 7946) com os traços transformados por M (pt -> UTM).

    Cada feature leva layer, classe, cores e `propriedades`. Traços preenchidos viram
    Polygon/MultiPolygon; os demais, LineString/MultiLineString. Com unir_poligonos=True,
    os preenchimentos de mesma classe são fundidos (raster + contornos) para aliviar o HTML.
    """
    feats = []
    esc = float(np.sqrt(abs(np.linalg.det(M[:2, :2]))))      # m por pt
    tol_pt = simplificar_m / max(esc, 1e-9)

    def ll(p):
        u = geo.aplicar(M, p)
        lon, lat = geo.para_lonlat(u[:, 0], u[:, 1], epsg)
        return np.c_[lon, lat].round(8).tolist()

    for i, t in enumerate(tracos):
        if filtro is not None and not filtro(t):
            continue
        cls = classes[i] if classes is not None else None
        props = {"layer": t.layer, "classe": cls, "cor": t.cor, "preenchimento": t.preenchimento,
                 **(propriedades or {})}
        partes = [_simplificar(p, tol_pt) for p in t.partes]
        if t.preenchimento is not None and not unir_poligonos:
            aneis = [ll(np.vstack([p, p[:1]])) for p in partes if len(p) >= 3]
            if not aneis:
                continue
            g = {"type": "Polygon", "coordinates": aneis[:1]} if len(aneis) == 1 else \
                {"type": "MultiPolygon", "coordinates": [[a] for a in aneis]}
        else:
            linhas = [ll(p) for p in partes]
            g = {"type": "LineString", "coordinates": linhas[0]} if len(linhas) == 1 else \
                {"type": "MultiLineString", "coordinates": linhas}
        feats.append({"type": "Feature", "geometry": g, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def manchas(tracos: list[Traco], classes: list, classe: str, M: np.ndarray, epsg: int,
            res_m: float = 0.10, fechar_m: float = 0.3, min_area_m2: float = 2.0,
            simplificar_m: float = 0.10) -> dict:
    """Polígonos fundidos ("manchas") de todos os traços de uma classe — hachuras e
    preenchimentos viram uma área por estrutura, com área (m²) calculada no plano UTM."""
    sel = [t for t, c in zip(tracos, classes) if c == classe]
    if not sel:
        return {"type": "FeatureCollection", "features": []}
    pts = np.vstack([geo.aplicar(M, np.vstack(t.partes)) for t in sel])
    e0, n0 = pts.min(0) - 2
    e1, n1 = pts.max(0) + 2
    W, H = int((e1 - e0) / res_m) + 1, int((n1 - n0) / res_m) + 1
    img = np.zeros((H, W), np.uint8)
    for t in sel:
        cs = [np.round(np.c_[(u[:, 0] - e0) / res_m, (n1 - u[:, 1]) / res_m]).astype(np.int32)
              for u in (geo.aplicar(M, p) for p in t.partes)]
        if t.preenchimento is not None:
            cv2.fillPoly(img, cs, 255)
        cv2.polylines(img, cs, t.fechado, 255, max(1, int(0.15 / res_m)))
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


def salvar_geojson(fc: dict, caminho: str | Path) -> None:
    Path(caminho).write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# --- pacote vetorial para o visualizador ----------------------------------------
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
        d = pg.get_text("dict")
        for b in d["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    t = s["text"].strip()
                    if not t or not _texto_legivel(t):
                        continue
                    o, dr = np.array([s["origin"]], float), np.array(l["dir"], float)
                    if R is not None:
                        o, dr = _aplicar_rot(R, o), R[:2, :2] @ dr
                    ang = float(np.degrees(np.arctan2(-dr[1], dr[0])))
                    out.append({"t": t, "x": round(float(o[0, 0]), 2), "y": round(float(o[0, 1]), 2),
                                "a": round(ang, 1), "h": round(s["size"], 2), "cor": _hex(
                                    [((s["color"] >> 16) & 255) / 255, ((s["color"] >> 8) & 255) / 255,
                                     (s["color"] & 255) / 255])})
    return out


def pacote_vetorial(caminho: str | Path, regras: list[Regra] | None = None, pagina: int = 0,
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
    cls = classificar(tr, regras) if regras else [None] * len(tr)
    coords, partes = [], []
    ult = np.zeros(2, np.int32)
    for t, c in zip(tr, cls):
        li = layers.setdefault(t.layer, {"i": len(layers), "nome": t.layer, "n": 0, "cores": {}, "classe": c})
        li["n"] += 1
        cor = _hex(t.cor) or _hex(t.preenchimento) or "#000000"
        li["cores"][cor] = li["cores"].get(cor, 0) + 1
        chave = (_hex(t.cor), _hex(t.preenchimento), round(t.largura, 2))
        ei = estilos.setdefault(chave, len(estilos))
        flags = (1 if t.fechado else 0) | (2 if t.preenchimento is not None else 0)
        for p in t.partes:
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
