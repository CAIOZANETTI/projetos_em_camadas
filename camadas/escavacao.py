"""Escavação e reaterro das cavas: plantas de escavação (PDF vetorial) + MDS do drone em cota.

    base       = preenchimentos do layer das estruturas projetadas (`_PROJETADOS`), em UTM pela afim da prancha
    fundo      = cota da marca de nível (`.COTA ESCAVAÇÃO`); o número é SHX, lido por OCR ao lado do símbolo (só pixels
                 pretos, a 0° e ±90°); número com 'TOPO' ao lado é crista e fica de fora
    terreno    = MDS em cota (controle vertical) com abertura morfológica; edificações (fora do chão pelo filtro
                 progressivo e sem verde na ortofoto) são parede: a cava não entra nelas
    modelo     = fundo + max(0, d − folga) ÷ talude a partir da base — dá a crista quando ela não está desenhada
    cava       = envoltória da crista desenhada (`RETALUDAMENTO`) com a borda do modelo, do lado da base
    escavação  = Σ min(terreno − fundo, d_borda ÷ talude) · área da célula, fundo da marca mais próxima na cava
    reaterro   = escavação fora da projeção da estrutura (a estrutura ocupa a base, do fundo ao terreno)

Conferência independente: a crista do modelo (só base, fundo, talude e terreno) contra a desenhada.
Regras e premissas em `conceitos/escavacao.json`. Contenção por estacas vira talude aqui: volume a maior ali.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np
import shapely
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import unary_union

from . import geo, pdf_cad, supressao

REGRAS = json.loads((pdf_cad.CONCEITOS / "escavacao.json").read_text(encoding="utf-8"))
NUMERO = re.compile(r"(\d{2,4})[,.](\d{2,3})$")
VALOR = {k: v["valor"] for k, v in REGRAS.items() if isinstance(v, dict) and "valor" in v}


def ler_cota(pagina, centro, dpi: int = 300, raio_pt: float = 50.0) -> dict | None:
    """Número de cota mais próximo do símbolo de nível, lido por OCR numa janela em volta dele."""
    import pymupdf
    import pytesseract
    from PIL import Image
    s = dpi / 72
    clip = pymupdf.Rect(centro[0] - raio_pt, centro[1] - raio_pt, centro[0] + raio_pt, centro[1] + raio_pt)
    px = pagina.get_pixmap(dpi=dpi, clip=clip)
    rgb = np.frombuffer(px.samples, np.uint8).reshape(px.h, px.w, px.n)[..., :3]
    img = Image.fromarray(np.where(rgb.max(2) < 110, 0, 255).astype(np.uint8))   # só o texto preto
    W, H = img.size
    achados = []
    for k in (0, 1, 3):                                  # 0°, 90° anti-horário, 90° horário
        d = pytesseract.image_to_data(img.rotate(90 * k, expand=True), config="--psm 11",
                                      output_type=pytesseract.Output.DICT)
        palavras = []
        for t, x, y, w, h in zip(d["text"], d["left"], d["top"], d["width"], d["height"]):
            if t.strip():
                u, v = x + w / 2, y + h / 2              # volta da imagem girada para a original
                p = (u, v) if k == 0 else (W - v, u) if k == 1 else (v, H - u)
                palavras.append((t.strip(), np.array([clip.x0 + p[0] / s, clip.y0 + p[1] / s])))
        for t, p in palavras:
            m = NUMERO.search(t)
            if m:
                topo = any("TOPO" in t2.upper() and np.linalg.norm(p2 - p) < 12 for t2, p2 in palavras)
                achados.append((float(np.linalg.norm(p - centro)), float(f"{m[1]}.{m[2]}"), topo))
    perto = [a for a in achados if a[0] <= VALOR["raio_cota_pt"]]
    if not perto:
        return None
    dist, cota, topo = min(perto)
    return {"cota": cota, "topo": topo, "dist_pt": round(dist, 1)}


def marcas(pdf: str | Path, tracos: list, layer: str, M) -> list[dict]:
    """Marcas de nível da planta (símbolo ≥ `marca_min_pt`) com a cota lida e a posição em UTM."""
    import pymupdf

    from . import georef_prancha
    pagina = pymupdf.open(pdf)[0]
    out = []
    for r in georef_prancha.linhas_da_malha(tracos, layer, max_glifo_pt=12)["rotulos"]:
        if np.ptp(np.vstack(r["partes"]), axis=0).max() < VALOR["marca_min_pt"]:
            continue                                     # planta-chave: símbolo pequeno, sem cota legível
        c = np.asarray(r["centro"], float)
        lido = ler_cota(pagina, c)
        out.append({"pt": c.round(1).tolist(), "utm": geo.aplicar(np.asarray(M), c[None])[0].round(2).tolist(),
                    **(lido or {"cota": None, "motivo": f"OCR sem número a ≤ {VALOR['raio_cota_pt']:.0f} pt"})})
    return out


def bases(tracos: list, layer: str, M, cores_etapa: dict) -> list[dict]:
    """Preenchimentos do layer das estruturas em UTM, com a etapa pela cor (convenção da prancha)."""
    out = []
    for t in tracos:
        if t["preenchimento"] is None or not re.search(layer, t["layer"], re.IGNORECASE):
            continue
        cor = np.asarray(t["preenchimento"], float)
        etapa = next((e for e, c in cores_etapa.items() if np.abs(cor - c).max() < 0.1), None)
        for q in t["partes"]:
            if len(q) >= 3:
                p = Polygon(geo.aplicar(np.asarray(M), np.asarray(q))).buffer(0)
                if p.area >= 0.5:
                    out.append({"geom": p, "etapa": etapa})
    return out


def chao_pmf(z: np.ndarray, res: float, janelas=(3, 6, 12, 24, 48), dh0: float = 0.3, inclinacao: float = 0.15,
             dh_max: float = 2.5) -> np.ndarray:
    """Células de chão pelo filtro morfológico progressivo: sai a que sobe acima da abertura mais que o limite da
    janela (dh0 + inclinação × Δjanela, até dh_max)."""
    chao, zf, w_ant = np.ones(z.shape, bool), z, 0
    for w in janelas:
        k = max(3, int(w / res) | 1)
        ab = cv2.morphologyEx(zf, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        chao &= (z - ab) <= (min(dh0 + inclinacao * (w - w_ant), dh_max) if w_ant else dh0)
        zf, w_ant = ab, w
    return chao


def grade(ortofoto: Path, mds_png: Path, vertical: dict, area_edificacao_m2: float = 50.0) -> dict:
    """Grade da ortofoto a `res_m`: terreno em cota, edificações e cobertura do levantamento."""
    res = VALOR["res_m"]
    v = supressao.mascaras_vegetacao(ortofoto, mds_png, res=res, terreno_m=VALOR["terreno_m"])
    e0, n1, forma = v["e0"], v["n1"], v["alta"].shape
    lin, col = np.indices(forma, dtype=np.float32)
    ve, vn = vertical["centro"]
    z = (supressao.mds_na_grade(Path(mds_png), e0, n1, res, forma) + vertical["offset_m"]
         + vertical["inclinacao_e"] * (e0 + (col + 0.5) * res - ve)
         + vertical["inclinacao_n"] * (n1 - (lin + 0.5) * res - vn)).astype(np.float32)
    ed = (~chao_pmf(z, res) & ~v["alta"] & ~v["rasteira"]).astype(np.uint8)
    ed = cv2.morphologyEx(ed, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, comp, st, _ = cv2.connectedComponentsWithStats(ed)
    grandes = [k for k in range(1, n) if st[k, cv2.CC_STAT_AREA] * res * res >= area_edificacao_m2]
    return {"e0": e0, "n1": n1, "res": res, "forma": forma, "epsg": v["epsg"], "valido": v["valido"],
            "terreno": supressao.terreno(z, res, VALOR["terreno_m"]), "edificacao": np.isin(comp, grandes)}


def plausiveis(ms: list[dict], g: dict) -> tuple[list[dict], int]:
    """Marcas de fundo usáveis: com cota, sem 'TOPO', dentro da grade e entre terreno − 10 m e terreno + 0,5 m."""
    ok, fora = [], 0
    for m in ms:
        if m.get("cota") is None or m.get("topo"):
            continue
        lin, col = _celula(np.array([m["utm"]]), g)[0]
        if not (0 <= lin < g["forma"][0] and 0 <= col < g["forma"][1]):
            continue
        t = g["terreno"][lin, col]
        if t - 10.0 <= m["cota"] <= t + 0.5:
            ok.append({**m, "celula": (int(lin), int(col))})
        else:
            fora += 1
    return ok, fora


def _celula(xy: np.ndarray, g: dict) -> np.ndarray:
    return np.c_[(g["n1"] - xy[:, 1]) / g["res"], (xy[:, 0] - g["e0"]) / g["res"]].astype(int)


def com_marca(bs: list[dict], ms: list[dict]) -> tuple[list[dict], np.ndarray, np.ndarray]:
    """Bases com marca de fundo a ≤ `raio_marca_m` (as outras — legenda, estrutura sem cota — ficam de fora)."""
    P = np.array([m["utm"] for m in ms], float).reshape(-1, 2)
    cotas = np.array([m["cota"] for m in ms], float)
    pts = shapely.points(P)
    return [b for b in bs if len(P) and np.any(shapely.distance(b["geom"], pts) <= VALOR["raio_marca_m"])], P, cotas


def fundo_na_grade(bs: list[dict], P: np.ndarray, cotas: np.ndarray, e0: float, n1: float, res: float, forma):
    """Cota de fundo em cada célula das bases: a da marca mais próxima entre as da própria base (a mais funda vence)."""
    fundo = np.full(forma, np.nan, np.float32)
    pts = shapely.points(P)
    for b in bs:
        perto = shapely.distance(b["geom"], pts) <= VALOR["raio_marca_m"]
        lin, col = np.nonzero(supressao.rasterizar(b["geom"], e0, n1, res, forma))
        xy = np.c_[e0 + (col + 0.5) * res, n1 - (lin + 0.5) * res]
        mais_perto = np.argmin(((xy[:, None, :] - P[perto][None]) ** 2).sum(2), axis=1)
        fundo[lin, col] = np.fmin(fundo[lin, col], cotas[perto][mais_perto])
    return fundo


def _mais_proxima(mascara: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Distância (em células) e índice linear da célula da máscara mais próxima, para cada célula da grade."""
    dist, rot = cv2.distanceTransformWithLabels(np.where(mascara, 0, 255).astype(np.uint8), cv2.DIST_L2,
                                                cv2.DIST_MASK_PRECISE, labelType=cv2.DIST_LABEL_PIXEL)
    idx = np.zeros(rot.max() + 1, np.int64)
    idx[rot[mascara]] = np.flatnonzero(mascara)          # rótulo de cada célula da máscara -> índice dela
    return dist, idx[rot]


def superficie_da_cava(fundo: np.ndarray, res: float, talude: float, folga: float, alcance_m: float = 20.0):
    """Modelo: fundo + max(0, d − folga) ÷ talude, com o fundo da célula de base mais próxima; NaN além do alcance."""
    base = ~np.isnan(fundo)
    dist, idx = _mais_proxima(base)
    d = np.maximum(dist - 0.5, 0.0) * res                # até a borda da célula de base, não até o centro dela
    sup = fundo.ravel()[idx] + np.maximum(0.0, d - folga) / talude
    return np.where(d <= alcance_m, sup, np.nan), base


def regiao(modelo: np.ndarray, muro: np.ndarray, livre: np.ndarray, base: np.ndarray, fechar_px: int) -> np.ndarray:
    """Células da cava: dentro da envoltória (crista desenhada + borda do modelo), ligadas à base sem cruzar a crista
    desenhada nem edificação."""
    borda = modelo & ~cv2.erode(modelo.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    paredes = cv2.morphologyEx((muro | borda).astype(np.uint8), cv2.MORPH_CLOSE,
                               cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (fechar_px | 1, fechar_px | 1)))
    fora = np.pad(paredes, 1)
    cv2.floodFill(fora, np.zeros((fora.shape[0] + 2, fora.shape[1] + 2), np.uint8), (0, 0), 2)
    dentro = (fora[1:-1, 1:-1] != 2) & ~muro & livre
    _, comp = cv2.connectedComponents(dentro.astype(np.uint8), connectivity=4)
    com_base = np.unique(comp[base & dentro])
    return np.isin(comp, com_base[com_base > 0])


def fundo_na_regiao(R: np.ndarray, ms: list[dict], raio_px: float) -> np.ndarray:
    """Fundo de cada célula da cava: a marca mais próxima entre as da própria cava (a ≤ `raio_px` dela)."""
    _, comp = cv2.connectedComponents(R.astype(np.uint8), connectivity=4)
    dist, idx = _mais_proxima(R)
    F = np.full(R.shape, np.nan, np.float32)
    cel = np.array([m["celula"] for m in ms], int).reshape(-1, 2)
    cotas = np.array([m["cota"] for m in ms], float)
    k_m = np.where(dist[cel[:, 0], cel[:, 1]] <= raio_px, comp.ravel()[idx[cel[:, 0], cel[:, 1]]], 0)
    for k in np.unique(k_m[k_m > 0]):
        sel = k_m == k
        lin, col = np.nonzero(comp == k)
        nn = np.argmin((lin[:, None] - cel[sel, 0]) ** 2 + (col[:, None] - cel[sel, 1]) ** 2, axis=1)
        F[lin, col] = cotas[sel][nn]
    return F


def linhas_na_grade(linhas: list, g: dict, espessura: int = 2) -> np.ndarray:
    """Linhas UTM (a crista desenhada) rasterizadas na grade."""
    m = np.zeros(g["forma"], np.uint8)
    for l in linhas:
        cv2.polylines(m, [_celula(np.asarray(l.coords), g)[:, ::-1].astype(np.int32)], False, 1, espessura)
    return m.astype(bool)


def calcular(bs: list[dict], ms: list[dict], cristas: list, g: dict) -> dict:
    """Volume de escavação e reaterro por cava, e a crista do modelo para a conferência."""
    res, talude, folga = g["res"], VALOR["talude_h_v"], VALOR["folga_m"]
    e0, n1, forma, terreno = g["e0"], g["n1"], g["forma"], g["terreno"]
    validas, fora_da_faixa = plausiveis(ms, g)
    usadas, P, cotas = com_marca(bs, validas)
    fundo = fundo_na_grade(usadas, P, cotas, e0, n1, res, forma)
    sup, base = superficie_da_cava(fundo, res, talude, folga)
    livre = g["valido"] & ~g["edificacao"]
    modelo = livre & (terreno - np.nan_to_num(sup, nan=1e9) > 0.01)
    R = regiao(modelo, linhas_na_grade(cristas, g), livre, base, int(1.0 / res))
    F = fundo_na_regiao(R, validas, VALOR["raio_marca_m"] / res)
    d = (cv2.distanceTransform(R.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) - 0.5) * res   # até a borda
    corte = np.where(R & ~np.isnan(F), np.clip(np.minimum(terreno - F, d / talude), 0, None), 0.0)
    n, comp = cv2.connectedComponents((corte > 0.01).astype(np.uint8), connectivity=8)
    cavas = [_cava(comp == k, corte, terreno, F, base, usadas, g) for k in range(1, n)
             if corte[comp == k].sum() * res * res >= 1.0]
    cavas.sort(key=lambda c: -c["escavacao_m3"])
    for i, c in enumerate(cavas, 1):
        c["id"] = f"C{i:02d}"
    return {"cavas": cavas, "modelo": unary_union(supressao.poligonos(modelo, e0, n1, res, 1.0, 0.2)),
            "modelo_m3": round(float(np.where(modelo, terreno - np.nan_to_num(sup), 0).sum() * res * res), 1),
            "bases_sem_marca": len(bs) - len(usadas),
            "marcas": {**_resumo_marcas(ms), "fora_da_faixa": fora_da_faixa, "usadas": len(validas)},
            "parametros": {"talude_h_v": talude, "folga_m": folga, "terreno_m": VALOR["terreno_m"], "res_m": res,
                           "edificacao_m2": round(float(g["edificacao"].sum() * res * res))}}


SAIDAS_CAVA = {"escavacao_cava_m3": "escavacao_m3", "reaterro_cava_m3": "reaterro_m3", "area_cava_m2": "area_m2"}


def _poligono(coords: list) -> Polygon:
    """Polígono de uma base guardada na gaveta: um anel, ou o anel externo seguido dos furos."""
    aneis = coords if coords and isinstance(coords[0][0], (list, tuple)) else [coords]
    return Polygon(aneis[0], aneis[1:])


def _marcas_da_gaveta(marcas_cota: list[dict]) -> list[dict]:
    """Marcas do fato `marcas_cota` ({E, N, cota_m, topo, prancha}) no formato de `calcular` (utm, cota, topo)."""
    return [{"utm": [m["E"], m["N"]], "cota": m.get("cota_m"), "topo": bool(m.get("topo")), "prancha": m.get("prancha")}
            for m in marcas_cota]


def _alertas_das_cavas(r: dict) -> list[str]:
    """Avisos do `calcular`: bases sem marca, marcas fora da faixa e cavas na borda do levantamento."""
    alertas = []
    if r["bases_sem_marca"]:
        alertas.append(f"{r['bases_sem_marca']} base(s) sem marca de cota de fundo a ≤ {VALOR['raio_marca_m']:g} m: "
                       "ficam fora do cálculo")
    if r["marcas"]["fora_da_faixa"]:
        alertas.append(f"{r['marcas']['fora_da_faixa']} marca(s) de cota fora da faixa do terreno "
                       "(terreno − 10 m a terreno + 0,5 m): ignoradas")
    alertas += [f"cava {c['id']} na borda do levantamento: parte sem MDS, volume a menor"
                for c in r["cavas"] if c["na_borda_do_levantamento"]]
    return alertas


def quantificar_gavetas(dados: dict, furos=None, pts=None) -> dict:
    """Função da regra `cavas` (`conceitos/de_para_servicos.json`): escavação, reaterro e área de cada cava.

    `dados`: `bases` ([{coords, etapa}]), `marcas_cota` ([{E, N, cota_m, topo, prancha}]), `cristas` ([coords], opcional) e
    `superficie` (a grade já carregada, de `gavetas.ler_superficie`). `furos` e `pts` não são usados (a assinatura é a
    de toda regra). Devolve {saída: {id da cava: valor}} e `alertas`."""
    bases_da_obra = [{"geom": _poligono(b["coords"]), "etapa": b.get("etapa")} for b in dados["bases"]]
    cristas = [LineString(c) for c in dados.get("cristas") or []]
    r = calcular(bases_da_obra, _marcas_da_gaveta(dados["marcas_cota"]), cristas, dados["superficie"])
    saidas = {saida: {c["id"]: c[campo] for c in r["cavas"]} for saida, campo in SAIDAS_CAVA.items()}
    return {**saidas, "alertas": _alertas_das_cavas(r)}


def _cava(cel, corte, terreno, F, base, usadas, g) -> dict:
    """Números de uma cava: volumes, área, profundidade na base, etapa e contorno (UTM)."""
    res = g["res"]
    na_base = cel & base
    contorno = unary_union(supressao.poligonos(cel, g["e0"], g["n1"], res, min_area_m2=0.5, simplificar_m=0.2))
    etapas = {}
    for b in usadas:
        if b["geom"].intersects(contorno):
            e = b["etapa"] or "sem cor de etapa"
            etapas[e] = etapas.get(e, 0) + b["geom"].intersection(contorno).area
    prof = (terreno - F)[na_base]
    return {"escavacao_m3": round(float(corte[cel].sum() * res * res), 1),
            "reaterro_m3": round(float(corte[cel & ~base].sum() * res * res), 1),
            "area_m2": round(float(cel.sum() * res * res), 1),
            "base_m2": round(float(na_base.sum() * res * res), 1),
            "prof_media_m": round(float(np.mean(prof)), 2) if prof.size else None,
            "prof_max_m": round(float(np.max(prof)), 2) if prof.size else None,
            "fundo_m": [round(float(np.nanmin(F[cel])), 2), round(float(np.nanmax(F[cel])), 2)],
            "etapa": max(etapas, key=etapas.get) if etapas else None,
            "na_borda_do_levantamento": bool((cv2.dilate(cel.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0)
                                             [~g["valido"]].any()),          # parte da cava sem MDS: volume a menor
            "contorno": contorno}


def _resumo_marcas(ms: list[dict]) -> dict:
    lidas = [m for m in ms if m.get("cota") is not None]
    return {"total": len(ms), "lidas": len(lidas), "topo": sum(bool(m.get("topo")) for m in lidas),
            "sem_numero": len(ms) - len(lidas)}


def conferir_crista(modelo, cristas_utm: list, passo_m: float = 0.5, perto_m: float = 10.0) -> dict:
    """Distância da crista desenhada à crista do modelo, nos trechos de crista a ≤ `perto_m` dela."""
    borda = modelo.boundary
    pts = [l.interpolate(s) for l in cristas_utm for s in np.arange(0, l.length, passo_m)]
    if borda.is_empty or not pts:
        return {"pontos": 0, "motivo": "sem crista desenhada ou sem cava"}
    d = shapely.distance(np.array(pts, dtype=object), borda)
    d = d[d <= perto_m]
    if not d.size:
        return {"pontos": 0, "motivo": f"nenhuma crista desenhada a ≤ {perto_m:.0f} m da do modelo"}
    return {"pontos": int(d.size), "comprimento_m": round(d.size * passo_m, 1), "mediana_m": round(float(np.median(d)), 2),
            "p90_m": round(float(np.percentile(d, 90)), 2), "ate_1m": round(float(np.mean(d <= 1.0)), 2)}


def linhas_utm(tracos: list, layer: str, M) -> list:
    """Traços de um layer como LineString em UTM (a crista desenhada)."""
    return [LineString(geo.aplicar(np.asarray(M), np.asarray(q))) for t in tracos
            if re.search(layer, t["layer"], re.IGNORECASE) for q in t["partes"] if len(q) >= 2]


def _entregar_as_gavetas(saida: dict, ms: list, bs: list, cristas: list, g: dict, r: dict, lidas: list) -> None:
    """Preenche o dict `saida_gavetas` com o que a memória espacial grava: marcas, bases, cristas, a grade e o resultado
    direto de `calcular` (só id e volumes de cada cava), para a paridade; `pranchas` são as efetivamente lidas."""
    campos = ("id", *SAIDAS_CAVA.values())
    saida.update(marcas=ms, bases=bs, cristas=cristas, g=g, pranchas=lidas,
                 resultado={"cavas": [{k: cv[k] for k in campos} for cv in r["cavas"]]})


def etapa(cfg: dict, pranchas: list, out: Path, vertical: dict | None, log=print,
          saida_gavetas: dict | None = None) -> dict | None:
    """Etapa da obra: lê as plantas de escavação (OCR com cache), calcula as cavas e devolve o pacote do HTML.
    `saida_gavetas`, se passado, recebe as entradas e o resultado do cálculo para as gavetas (sem mudar o retorno)."""
    c = cfg.get("escavacao")
    if not c or not vertical:
        return None
    por_id = {p["id"]: p for p in pranchas}
    cache_arq = out / "escavacao_cache.json"
    cache = json.loads(cache_arq.read_text()) if cache_arq.exists() else {}
    bs, ms, cristas, lidas = [], [], [], []
    for pid in c["pranchas"]:
        p = por_id.get(pid)
        if p is None or p.get("M") is None:
            log(f"Escavação: prancha {pid} sem georreferência, fica de fora")
            continue
        tr = pdf_cad.extrair(p["pdf"], clip=p.get("clip"))
        arq = Path(p["pdf"])
        assinatura = f"{arq.stat().st_size}:{int(arq.stat().st_mtime)}:{np.asarray(p['M']).round(6).tolist()}"
        if cache.get(pid, {}).get("assinatura") != assinatura:
            cache[pid] = {"assinatura": assinatura, "marcas": marcas(p["pdf"], tr, c["layer_marca"], p["M"])}
            cache_arq.write_text(json.dumps(cache, ensure_ascii=False))
        lidas.append(pid)
        ms += [{**m, "prancha": pid} for m in cache[pid]["marcas"]]
        bs += bases(tr, c["layer_base"], p["M"], c["cores_etapa"])
        cristas += linhas_utm(tr, c["layer_crista"], p["M"])
    g = grade(out / "sfm" / "ortofoto.jpg", out / "sfm" / "ortofoto_mds.png", vertical)
    r = calcular(bs, ms, cristas, g)
    if saida_gavetas is not None:
        _entregar_as_gavetas(saida_gavetas, ms, bs, cristas, g, r, lidas)
    r["conferencia_crista"] = conferir_crista(r.pop("modelo"), cristas)
    tot = {k: round(sum(cv[k] for cv in r["cavas"]), 1) for k in ("escavacao_m3", "reaterro_m3", "area_m2")}
    log(f"Escavação: {len(r['cavas'])} cavas, {tot['escavacao_m3']:.0f} m³ escavação, {tot['reaterro_m3']:.0f} m³ "
        f"reaterro (só o modelo: {r['modelo_m3']:.0f} m³); marcas {r['marcas']}; crista desenhada × modelo: "
        f"{r['conferencia_crista']}")
    return para_html(r, tot, c, g["epsg"])


def para_html(r: dict, tot: dict, c: dict, epsg: int) -> dict:
    """Tabela por cava + camada do mapa (lon/lat). Só exibição no front."""
    feats, linhas = [], []
    for cv in r["cavas"]:
        props = {k: v for k, v in cv.items() if k != "contorno"}
        linhas.append(props)
        feats.append({"type": "Feature", "geometry": mapping(shapely.transform(
            cv["contorno"], lambda xy: np.column_stack(geo.para_lonlat(xy[:, 0], xy[:, 1], epsg)))),
                      "properties": {"tipo": "Escavação calculada", **props, "estimado": True}})
    return {"cavas": linhas, "total": tot, "modelo_m3": r["modelo_m3"], "marcas": r["marcas"],
            "bases_sem_marca": r["bases_sem_marca"], "conferencia_crista": r["conferencia_crista"],
            "parametros": r["parametros"], "fonte": c.get("fonte", ""), "premissas": REGRAS["metadata"]["observacoes"],
            "geojson": {"type": "FeatureCollection", "features": feats}}


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "escavacao",
        "descricao": "escavação e reaterro por cava: base das estruturas + cota de fundo (OCR) + crista desenhada + "
                     "talude + MDS em cota",
        "funcoes": ["ler_cota", "marcas", "bases", "chao_pmf", "grade", "plausiveis", "com_marca", "fundo_na_grade",
                    "superficie_da_cava", "regiao", "fundo_na_regiao", "linhas_na_grade", "calcular",
                    "conferir_crista", "linhas_utm", "quantificar_gavetas", "etapa", "para_html"],
        "bibliografia": [
            {"obra": "ABNT NBR 9061 — Segurança de escavação a céu aberto", "ano": 1985, "editora": "ABNT",
             "aplicacao": {"superficie_da_cava": ["talude H:V da prancha", "folga de trabalho"]}},
            {"obra": "Soille — Morphological Image Analysis (abertura morfológica para o terreno)", "ano": 2003,
             "editora": "Springer", "aplicacao": {"grade": ["terreno_m=15"]}},
            {"obra": "Zhang et al. — A progressive morphological filter for removing nonground measurements from "
                     "airborne LIDAR data", "ano": 2003, "editora": "IEEE TGRS",
             "aplicacao": {"chao_pmf": ["janelas 3–48 m", "dh0=0,3", "inclinação=0,15", "dh_max=2,5"]}},
            {"obra": "Smith — An Overview of the Tesseract OCR Engine", "ano": 2007, "editora": "ICDAR",
             "aplicacao": {"ler_cota": ["--psm 11", "0°/±90°"]}},
        ],
        "premissas": [{"aplicacao": {k: [k]}, "fonte": v["fonte"], "estado": v["estado"]}
                      for k, v in REGRAS.items() if k != "metadata"]
                     + [{"aplicacao": {"grade": ["area_edificacao_m2=50"]}, "estado": "premissa",
                         "fonte": "edificação = fora do chão (filtro progressivo), sem verde na ortofoto, ≥ 50 m²"}],
    }
