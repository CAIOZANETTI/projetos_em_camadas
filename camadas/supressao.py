"""Supressão vegetal estimada: vegetação alta dentro da faixa de obra do projeto.

    vegetação  = índice de verde ExG = (2G − R − B)/(R + G + B) na ortofoto
    altura     = MDS − terreno (terreno = abertura morfológica do MDS, ~15 m)
    árvore/arbusto = vegetação com altura > `altura_min_m`  -> supressão (desmatamento)
    rasteira       = vegetação baixa                         -> limpeza/roçada (só área)
    faixa de obra  = buffer das tubulações projetadas (`faixa_m`) e das unidades novas
                     (`folga_unidades_m`), por etapa

Resultado: polígonos (lon/lat) com área, altura média e etapa — uma estimativa para o
planejamento e para conferir em campo, não um levantamento florístico.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import unary_union

from . import geo


def _raster_orto(caminho: Path, res: float):
    meta = json.loads(caminho.with_suffix(".json").read_text())
    img = cv2.imread(str(caminho), cv2.IMREAD_COLOR)
    k = meta["res_m_px"] / res
    img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    e0, n1 = meta["canto_sup_esq"]
    return img, e0, n1, meta["epsg"]


def mds_na_grade(mds_png: Path, e0: float, n1: float, res: float, forma) -> np.ndarray:
    meta = json.loads(mds_png.with_suffix(".json").read_text())
    z = cv2.imread(str(mds_png), cv2.IMREAD_UNCHANGED).astype(np.float32) / 100 + meta["z_min_m"]
    me0, mn1 = meta["canto_sup_esq"]
    mres = meta["res_m_px"]
    # pixel da grade da ortofoto (res) -> pixel do MDS (mapa destino -> origem)
    A = np.array([[res / mres, 0, (e0 - me0) / mres], [0, res / mres, (mn1 - n1) / mres]], np.float32)
    return cv2.warpAffine(z, A, (forma[1], forma[0]), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                          borderMode=cv2.BORDER_REPLICATE)


def terreno(z: np.ndarray, res: float, terreno_m: float = 15.0) -> np.ndarray:
    """Terreno sob prédios e copas: abertura morfológica do MDS (elemento de `terreno_m`) suavizada."""
    k = max(3, int(terreno_m / res) | 1)
    t = cv2.morphologyEx(z, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    return cv2.GaussianBlur(t, (0, 0), k / 4)


def mascaras_vegetacao(ortofoto: str | Path, mds_png: str | Path, res: float = 0.25,
                       exg_min: float = 0.06, altura_min_m: float = 1.5, terreno_m: float = 15.0) -> dict:
    """Máscaras booleanas (grade da ortofoto reduzida a `res`): vegetação alta e rasteira."""
    img, e0, n1, epsg = _raster_orto(Path(ortofoto), res)
    b, g, r = [c.astype(np.float32) for c in cv2.split(img)]
    exg = (2 * g - r - b) / (r + g + b + 1)
    valido = img.min(axis=2) < 250
    z = mds_na_grade(Path(mds_png), e0, n1, res, img.shape[:2])
    h = z - terreno(z, res, terreno_m)
    veg = (exg > exg_min) & valido
    veg = cv2.morphologyEx(veg.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    return {"alta": veg & (h > altura_min_m), "rasteira": veg & (h <= altura_min_m), "altura": h, "valido": valido,
            "e0": e0, "n1": n1, "res": res, "epsg": epsg}


def faixa_de_obra(geoms_utm: list, faixa_m: float = 4.0, folga_unidades_m: float = 2.0):
    """Buffer das linhas (faixa/2 para cada lado) e dos polígonos (folga) — shapely, em UTM."""
    partes = []
    for g in geoms_utm:
        if g.is_empty:
            continue
        partes.append(g.buffer(folga_unidades_m) if g.geom_type in ("Polygon", "MultiPolygon")
                      else g.buffer(faixa_m / 2, cap_style="flat"))
    return unary_union(partes) if partes else None


def rasterizar(poly, e0, n1, res, forma) -> np.ndarray:
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    if poly is None or poly.is_empty:
        return np.zeros(forma, bool)
    return rasterize([(poly, 1)], out_shape=forma, transform=Affine(res, 0, e0, 0, -res, n1),
                     fill=0, dtype="uint8").astype(bool)


def poligonos(mascara: np.ndarray, e0, n1, res, min_area_m2: float, simplificar_m: float = 0.3) -> list:
    from rasterio.features import shapes
    from rasterio.transform import Affine
    out = []
    for gj, v in shapes(mascara.astype(np.uint8), mask=mascara, transform=Affine(res, 0, e0, 0, -res, n1)):
        p = shape(gj).simplify(simplificar_m)
        if p.area >= min_area_m2:
            out.append(p)
    return out


def estimar(ortofoto, mds_png, geoms_por_etapa: dict[str, list], faixa_m: float = 4.0,
            folga_unidades_m: float = 2.0, min_area_m2: float = 2.0, **kw) -> dict:
    """FeatureCollection (lon/lat) da supressão estimada por etapa + resumo de áreas."""
    m = mascaras_vegetacao(ortofoto, mds_png, **kw)
    e0, n1, res, epsg = m["e0"], m["n1"], m["res"], m["epsg"]
    forma = m["alta"].shape
    def ll(xy):
        return np.column_stack(geo.para_lonlat(xy[:, 0], xy[:, 1], epsg))
    feats, resumo, ja = [], {}, np.zeros(forma, bool)
    for etapa, geoms in geoms_por_etapa.items():       # primeira etapa listada "fica" com a área
        faixa = faixa_de_obra(geoms, faixa_m, folga_unidades_m)
        dentro = rasterizar(faixa, e0, n1, res, forma) & ~ja
        ja |= dentro
        for tipo, chave in (("Supressão vegetal (árvores/arbustos)", "alta"), ("Limpeza de vegetação rasteira", "rasteira")):
            alvo = m[chave] & dentro
            for p in poligonos(alvo, e0, n1, res, min_area_m2):
                cel = rasterizar(p, e0, n1, res, forma) & alvo
                hmed = float(np.median(m["altura"][cel])) if cel.any() else 0.0
                feats.append({"type": "Feature", "geometry": mapping(shapely.transform(p, ll)),
                              "properties": {"tipo": tipo, "categoria": "supressao" if chave == "alta" else "limpeza",
                                             "etapa": etapa, "area_m2": round(p.area, 1),
                                             "altura_m": round(hmed, 1), "estimado": True,
                                             "criterio": f"ExG + altura>{kw.get('altura_min_m', 1.5)} m na faixa de {faixa_m} m"}})
                r = resumo.setdefault(etapa, {"supressao_m2": 0.0, "limpeza_m2": 0.0})
                r["supressao_m2" if chave == "alta" else "limpeza_m2"] += p.area
    for r in resumo.values():
        r["supressao_m2"], r["limpeza_m2"] = round(r["supressao_m2"], 1), round(r["limpeza_m2"], 1)
    return {"type": "FeatureCollection", "features": feats, "resumo": resumo}


def geoms_utm_de_tracos(tracos, classes, M, classes_alvo: dict[str, str]) -> dict[str, list]:
    """Traços classificados de uma prancha -> geometrias shapely em UTM agrupadas por etapa."""
    out: dict[str, list] = {}
    for t, c in zip(tracos, classes):
        if c not in classes_alvo:
            continue
        for q in t["partes"]:
            u = geo.aplicar(M, q)
            if len(u) < 2:
                continue
            g = Polygon(u) if (t["preenchimento"] is not None and len(u) >= 3) else LineString(u)
            if not g.is_valid:
                g = g.buffer(0)
            out.setdefault(classes_alvo[c], []).append(g)
    return out


def metadados() -> dict:
    """Rastreabilidade do índice de vegetação e dos limiares da supressão estimada (regra 9 do estilo)."""
    return {
        "modulo": "supressao",
        "descricao": "supressão vegetal estimada: ExG + altura (MDS − terreno) na faixa de obra do projeto",
        "funcoes": ["terreno", "mascaras_vegetacao", "faixa_de_obra", "estimar", "geoms_utm_de_tracos", "mds_na_grade",
                    "rasterizar", "poligonos"],
        "bibliografia": [
            {"obra": "Woebbecke et al. — Color indices for weed identification under various soil, residue and "
                     "lighting conditions (ExG = 2G − R − B)", "ano": 1995, "editora": "Transactions of the ASAE",
             "aplicacao": {"mascaras_vegetacao": ["exg_min=0,06"]}},
            {"obra": "Soille — Morphological Image Analysis (abertura morfológica para o terreno)", "ano": 2003,
             "editora": "Springer", "aplicacao": {"terreno": ["terreno_m=15"]}},
        ],
        "premissas": [
            {"aplicacao": {"mascaras_vegetacao": ["altura_min_m=1,5"]},
             "fonte": "árvore/arbusto acima de 1,5 m; abaixo é limpeza/roçada — conferir com o órgão ambiental"},
            {"aplicacao": {"faixa_de_obra": ["faixa_m=4,0", "folga_unidades_m=2,0"]},
             "fonte": "faixa de serviço típica de vala para DN até 1000 e folga de escavação; ajustar por projeto"},
        ],
        "ultima_revisao": "2026-10-27",
    }
