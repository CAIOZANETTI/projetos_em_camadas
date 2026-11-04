"""Escavação e reaterro das cavas: plantas de escavação (PDF vetorial) + MDS do drone em cota.

    base       = preenchimentos do layer das estruturas projetadas (`_PROJETADOS`), em UTM pela afim da prancha
    fundo      = cota da marca de nível (`.COTA ESCAVAÇÃO`); o número é SHX, lido por OCR ao lado do símbolo (só pixels
                 pretos, a 0° e ±90°); número com 'TOPO' ao lado é crista e fica de fora
    ligação    = cada base tem o seu fundo, nesta ordem: (a) as marcas DENTRO dela; (b) a cota escrita sem símbolo (rótulo
                 numérico) dentro dela ou junto da borda; (c) a marca vizinha mais perto, com alerta. A origem fica
                 registrada por base: marca_interna, cota_escrita, marca_vizinha ou sem_marca
    terreno    = MDS em cota (controle vertical) com abertura morfológica; edificações (fora do chão pelo filtro
                 progressivo e sem verde na ortofoto) são parede: a cava não entra nelas
    modelo     = fundo + max(0, d − folga) ÷ talude a partir da base — dá a crista quando ela não está desenhada
    cava       = envoltória da crista desenhada (`RETALUDAMENTO`) com a borda do modelo, do lado da base
    escavação  = Σ min(terreno − fundo, d_borda ÷ talude) · área da célula, fundo da base mais próxima na cava
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
ORIGENS_FUNDO = ("marca_interna", "cota_escrita", "marca_vizinha", "sem_marca")
VERSAO_COTAS_ESCRITAS = 1                    # sobe quando muda a leitura da cota escrita (o cache antigo é relido)
SUFIXO_ESCRITA = " (escrita)"                # no `texto` da marca: é como a cota escrita viaja pelas gavetas
GLIFOS_DO_ROTULO = (5, 7)                    # "235,35": 3 dígitos + vírgula + 2 dígitos (a vírgula pode fundir)
LADO_MAIOR_ROTULO_PT = (10.0, 45.0)          # caixa de um rótulo de cota (altura de texto ~ 5–8 pt)
LADO_MENOR_ROTULO_PT = (3.0, 12.0)
GLIFO_MAX_PT = 12.0                          # maior lado de um glifo (acima, é desenho, não letra)
TOLERANCIA_DENTRO_M = 1e-6                   # distância até a base que ainda é "dentro" dela
TOLERANCIA_COTA_IGUAL_M = 0.005              # cotas escritas com 2 casas: diferença menor que isso é o mesmo número


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


def _glifos_perto(tracos: list, regiao_pt) -> list[np.ndarray]:
    """Glifos (partes de até `GLIFO_MAX_PT`) cujo centro cai na região (polígono em pt), de qualquer layer."""
    x0, y0, x1, y1 = regiao_pt.bounds
    glifos = []
    for t in tracos:
        for q in t["partes"]:
            q = np.asarray(q, float)
            if len(q) < 2 or not (x0 - GLIFO_MAX_PT <= q[0, 0] <= x1 + GLIFO_MAX_PT
                                  and y0 - GLIFO_MAX_PT <= q[0, 1] <= y1 + GLIFO_MAX_PT):
                continue
            if np.ptp(q, axis=0).max() <= GLIFO_MAX_PT:
                glifos.append(q)
    if not glifos:
        return []
    centros = np.array([(g.min(0) + g.max(0)) / 2 for g in glifos])
    return [g for g, dentro in zip(glifos, shapely.contains_xy(regiao_pt, centros[:, 0], centros[:, 1])) if dentro]


def _rotulos_de_cota(glifos: list[np.ndarray]) -> list[np.ndarray]:
    """Centros (pt) dos grupos de glifos com cara de rótulo de cota: 5 a 7 glifos numa caixa de texto."""
    from . import georef_prancha
    achados = georef_prancha.linhas_da_malha([{"layer": "", "partes": glifos}], "", max_glifo_pt=GLIFO_MAX_PT)["rotulos"]
    saida = []
    for r in achados:
        caixa = np.ptp(np.vstack(r["partes"]), axis=0)
        if (GLIFOS_DO_ROTULO[0] <= len(r["partes"]) <= GLIFOS_DO_ROTULO[1]
                and LADO_MAIOR_ROTULO_PT[0] <= caixa.max() <= LADO_MAIOR_ROTULO_PT[1]
                and LADO_MENOR_ROTULO_PT[0] <= caixa.min() <= LADO_MENOR_ROTULO_PT[1]):
            saida.append(np.asarray(r["centro"], float))
    return saida


def cotas_escritas(pdf: str | Path, tracos: list, M, bs: list[dict], simbolos: list[dict]) -> list[dict]:
    """Cotas de nível escritas sem o símbolo de marca (rótulo numérico de 3 dígitos, vírgula e 2 dígitos) perto das
    bases, lidas por OCR de recorte como `ler_cota`. Só olha os glifos a ≤ `raio_cota_escrita_m` de alguma base e deixa de
    fora o número que já é de um símbolo (centro a ≤ `raio_cota_pt` dele, de `simbolos`, com o campo `pt`) e o 'TOPO'.
    Devolve {pt, utm, cota, topo, dist_pt} em UTM pela afim da prancha."""
    import pymupdf
    M3 = np.asarray(M, float)
    M3 = M3 if M3.shape == (3, 3) else np.vstack([M3, [0, 0, 1]])
    inversa = np.linalg.inv(M3)
    escala_m_pt = float(np.sqrt(abs(np.linalg.det(M3[:2, :2]))))
    if not bs:
        return []
    regiao = unary_union([shapely.transform(b["geom"], lambda xy: geo.aplicar(inversa, xy)) for b in bs])
    regiao = regiao.buffer(VALOR["raio_cota_escrita_m"] / escala_m_pt)
    pagina = pymupdf.open(pdf)[0]
    centros_simbolo = np.array([m["pt"] for m in simbolos], float).reshape(-1, 2)
    out = []
    for c in _rotulos_de_cota(_glifos_perto(tracos, regiao)):
        if len(centros_simbolo) and np.linalg.norm(centros_simbolo - c, axis=1).min() <= VALOR["raio_cota_pt"]:
            continue                                     # o número do símbolo já foi lido por `marcas`
        lido = ler_cota(pagina, c)
        if (lido is None or lido["topo"] or lido["dist_pt"] > VALOR["tolerancia_rotulo_pt"]
                or not 100.0 <= lido["cota"] < 1000.0):
            continue
        out.append({"pt": c.round(1).tolist(), "utm": geo.aplicar(M3, c[None])[0].round(2).tolist(), **lido})
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
            "terreno": supressao.terreno(z, res, VALOR["terreno_m"]), "edificacao": np.isin(comp, grandes),
            "vegetacao_alta": v["alta"]}


def plausiveis(ms: list[dict], g: dict) -> tuple[list[dict], int]:
    """Marcas de fundo usáveis: com cota, sem 'TOPO', dentro da grade e entre terreno − `faixa_abaixo_do_terreno_m` e
    terreno + `faixa_acima_do_terreno_m` (10 m e 0,5 m)."""
    ok, fora = [], 0
    for m in ms:
        if m.get("cota") is None or m.get("topo"):
            continue
        lin, col = _celula(np.array([m["utm"]]), g)[0]
        if not (0 <= lin < g["forma"][0] and 0 <= col < g["forma"][1]):
            continue
        t = g["terreno"][lin, col]
        if t - VALOR["faixa_abaixo_do_terreno_m"] <= m["cota"] <= t + VALOR["faixa_acima_do_terreno_m"]:
            ok.append({**m, "celula": (int(lin), int(col))})
        else:
            fora += 1
    return ok, fora


def _celula(xy: np.ndarray, g: dict) -> np.ndarray:
    return np.c_[(g["n1"] - xy[:, 1]) / g["res"], (xy[:, 0] - g["e0"]) / g["res"]].astype(int)


def _pontos_e_cotas(ms: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    return np.array([m["utm"] for m in ms], float).reshape(-1, 2), np.array([m["cota"] for m in ms], float)


def _ligar_base(b: dict, simbolos: tuple, escritas: tuple) -> dict:
    """Fundo de uma base e a sua origem, nesta ordem: (a) as marcas dentro dela; (b) a cota escrita sem símbolo, dentro
    dela ou a ≤ `raio_cota_escrita_m` da borda (a mais baixa); (c) a marca vizinha mais perto, a ≤ `raio_marca_m`, com
    alerta; senão `sem_marca`. `pontos` e `cotas` são as marcas que valem para a base."""
    (ps, cs), (pe, ce) = simbolos, escritas
    ds = shapely.distance(b["geom"], shapely.points(ps)) if len(ps) else np.empty(0)
    de = shapely.distance(b["geom"], shapely.points(pe)) if len(pe) else np.empty(0)
    ligacao = {"base": b, "origem": "sem_marca", "pontos": np.empty((0, 2)), "cotas": np.empty(0), "dist_m": None,
               "alerta": None}
    dentro, perto_escrita = ds <= TOLERANCIA_DENTRO_M, de <= VALOR["raio_cota_escrita_m"]
    if dentro.any():
        return {**ligacao, "origem": "marca_interna", "pontos": ps[dentro], "cotas": cs[dentro], "dist_m": 0.0}
    if perto_escrita.any():
        k = int(np.flatnonzero(perto_escrita)[np.argmin(ce[perto_escrita])])
        return {**ligacao, "origem": "cota_escrita", "pontos": pe[[k]], "cotas": ce[[k]], "dist_m": float(de[k])}
    if (ds <= VALOR["raio_marca_m"]).any():
        k = int(np.argmin(ds))
        return {**ligacao, "origem": "marca_vizinha", "pontos": ps[[k]], "cotas": cs[[k]], "dist_m": float(ds[k]),
                "alerta": f"fundo pela marca vizinha a {ds[k]:.1f} m".replace(".", ",")}
    return ligacao


def _escritas_sem_dono(simbolos: tuple, escritas: tuple) -> np.ndarray:
    """Cotas escritas que NÃO repetem a cota de uma marca com símbolo a ≤ `raio_marca_m` delas: o número repetido ao lado
    do símbolo é o rótulo da estrutura daquela marca (a curva da cava dela), não o fundo de outra base encostada."""
    (ps, cs), (pe, ce) = simbolos, escritas
    if not len(ps) or not len(pe):
        return np.ones(len(pe), bool)
    perto = np.linalg.norm(pe[:, None, :] - ps[None], axis=2) <= VALOR["raio_marca_m"]
    igual = np.abs(ce[:, None] - cs[None]) < TOLERANCIA_COTA_IGUAL_M
    return ~(perto & igual).any(axis=1)


def ligar_marcas(bs: list[dict], simbolos: list[dict], escritas: list[dict] | None = None) -> list[dict]:
    """Uma ligação por base (`_ligar_base`): `simbolos` são as marcas com símbolo e `escritas` as cotas escritas sem
    símbolo, ambas já plausíveis (`plausiveis`). A base com 2 ou mais marcas internas fica com todas (fundo em degraus,
    só entre elas); a marca de fora da base só entra na falta de marca interna e de cota escrita; a cota escrita que
    repete a de uma marca vizinha é desse símbolo (`_escritas_sem_dono`) e não vale para a base."""
    s, e = _pontos_e_cotas(simbolos), _pontos_e_cotas(escritas or [])
    livres = _escritas_sem_dono(s, e)
    return [_ligar_base(b, s, (e[0][livres], e[1][livres])) for b in bs]


def fundo_na_grade(ligacoes: list[dict], e0: float, n1: float, res: float, forma) -> np.ndarray:
    """Cota de fundo em cada célula das bases: a da marca mais próxima entre as da PRÓPRIA base (degraus quando ela tem
    mais de uma marca interna). Onde duas bases se sobrepõem, a mais funda vence."""
    fundo = np.full(forma, np.nan, np.float32)
    for lig in ligacoes:
        if lig["origem"] == "sem_marca":
            continue
        lin, col = np.nonzero(supressao.rasterizar(lig["base"]["geom"], e0, n1, res, forma))
        xy = np.c_[e0 + (col + 0.5) * res, n1 - (lin + 0.5) * res]
        mais_perto = np.argmin(((xy[:, None, :] - lig["pontos"][None]) ** 2).sum(2), axis=1)
        fundo[lin, col] = np.fmin(fundo[lin, col], lig["cotas"][mais_perto])
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


def fundo_na_regiao(R: np.ndarray, fundo: np.ndarray) -> np.ndarray:
    """Fundo de cada célula da cava: o da célula de base mais próxima dentro da mesma região (a mesma regra da
    superfície do talude); a base é a das marcas ligadas, não a marca mais perto."""
    _, comp = cv2.connectedComponents(R.astype(np.uint8), connectivity=4)
    F = np.full(R.shape, np.nan, np.float32)
    for k in range(1, comp.max() + 1):
        base_k = (comp == k) & ~np.isnan(fundo)
        if not base_k.any():
            continue
        _, idx = _mais_proxima(base_k)
        F[comp == k] = fundo.ravel()[idx[comp == k]]
    return F


def linhas_na_grade(linhas: list, g: dict, espessura: int = 2) -> np.ndarray:
    """Linhas UTM (a crista desenhada) rasterizadas na grade."""
    m = np.zeros(g["forma"], np.uint8)
    for l in linhas:
        cv2.polylines(m, [_celula(np.asarray(l.coords), g)[:, ::-1].astype(np.int32)], False, 1, espessura)
    return m.astype(bool)


def _separar_escritas(ms: list[dict]) -> tuple[list[dict], list[dict]]:
    """(marcas com símbolo, cotas escritas sem símbolo): a escrita traz `escrita` verdadeiro ou o `texto` com o sufixo."""
    escrita = [bool(m.get("escrita")) or str(m.get("texto") or "").endswith(SUFIXO_ESCRITA) for m in ms]
    return [m for m, e in zip(ms, escrita) if not e], [m for m, e in zip(ms, escrita) if e]


def _bases_fundo(ligadas: list[dict]) -> list[dict]:
    """Registro por base do fundo e da origem dele (`ORIGENS_FUNDO`), com o alerta da marca vizinha."""
    saida = []
    for i, lig in enumerate(ligadas):
        e, n = (round(v, 1) for v in lig["base"]["geom"].representative_point().coords[0])
        saida.append({"base": i, "etapa": lig["base"]["etapa"], "origem": lig["origem"], "E": e, "N": n,
                      "area_m2": round(float(lig["base"]["geom"].area), 1),
                      "cota_m": [round(float(c), 3) for c in lig["cotas"]], "dist_m": lig["dist_m"],
                      "alerta": None if lig["alerta"] is None else f"base {i} (E {e}, N {n}): {lig['alerta']}"})
    return saida


def calcular(bs: list[dict], ms: list[dict], cristas: list, g: dict) -> dict:
    """Volume de escavação e reaterro por cava, e a crista do modelo para a conferência. `ms` mistura as marcas com
    símbolo e as cotas escritas sem símbolo (`escrita`); cada base fica com o fundo das suas (`ligar_marcas`)."""
    res, talude, folga = g["res"], VALOR["talude_h_v"], VALOR["folga_m"]
    e0, n1, forma, terreno = g["e0"], g["n1"], g["forma"], g["terreno"]
    simbolos, escritas = _separar_escritas(ms)
    validas, fora_da_faixa = plausiveis(simbolos, g)
    ligadas = ligar_marcas(bs, validas, plausiveis(escritas, g)[0])
    usadas = [lig["base"] for lig in ligadas if lig["origem"] != "sem_marca"]
    fundo = fundo_na_grade(ligadas, e0, n1, res, forma)
    sup, base = superficie_da_cava(fundo, res, talude, folga)
    livre = g["valido"] & ~g["edificacao"] & np.isfinite(terreno)       # NaN = sem terreno (terreno composto)
    modelo = livre & (terreno - np.nan_to_num(sup, nan=1e9) > 0.01)
    R = regiao(modelo, linhas_na_grade(cristas, g), livre, base, int(1.0 / res))
    F = fundo_na_regiao(R, fundo)
    d = (cv2.distanceTransform(R.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE) - 0.5) * res   # até a borda
    corte = np.where(R & ~np.isnan(F), np.clip(np.minimum(terreno - F, d / talude), 0, None), 0.0)
    n, comp = cv2.connectedComponents((corte > 0.01).astype(np.uint8), connectivity=8)
    cavas = [_cava(comp == k, corte, terreno, F, base, usadas, g) for k in range(1, n)
             if corte[comp == k].sum() * res * res >= 1.0]
    cavas.sort(key=lambda c: -c["escavacao_m3"])
    for i, c in enumerate(cavas, 1):
        c["id"] = f"C{i:02d}"
    bases_fundo = _bases_fundo(ligadas)
    return {"cavas": cavas, "corte": corte, "modelo": unary_union(supressao.poligonos(modelo, e0, n1, res, 1.0, 0.2)),
            "modelo_m3": round(float(np.where(modelo, terreno - np.nan_to_num(sup), 0).sum() * res * res), 1),
            "bases_sem_marca": len(bs) - len(usadas), "bases_fundo": bases_fundo,
            "origem_fundo": {o: sum(b["origem"] == o for b in bases_fundo) for o in ORIGENS_FUNDO},
            "alertas_fundo": [b["alerta"] for b in bases_fundo if b["alerta"]],
            "marcas": {**_resumo_marcas(simbolos), "fora_da_faixa": fora_da_faixa, "usadas": len(validas),
                       **({"cotas_escritas": len(escritas)} if escritas else {})},
            "parametros": {"talude_h_v": talude, "folga_m": folga, "terreno_m": VALOR["terreno_m"], "res_m": res,
                           "edificacao_m2": round(float(g["edificacao"].sum() * res * res)),
                           **({"terreno": g["terreno_resumo"]} if "terreno_resumo" in g else {})}}


SAIDAS_CAVA = {"escavacao_cava_m3": "escavacao_m3", "reaterro_cava_m3": "reaterro_m3", "area_cava_m2": "area_m2"}


def _poligono(coords: list) -> Polygon:
    """Polígono de uma base guardada na gaveta: um anel, ou o anel externo seguido dos furos."""
    aneis = coords if coords and isinstance(coords[0][0], (list, tuple)) else [coords]
    return Polygon(aneis[0], aneis[1:])


def _marcas_da_gaveta(marcas_cota: list[dict]) -> list[dict]:
    """Marcas do fato `marcas_cota` ({E, N, cota_m, topo, prancha}) no formato de `calcular` (utm, cota, topo); a cota
    escrita sem símbolo se reconhece pelo sufixo do `texto` e volta a ser `escrita`."""
    return [{"utm": [m["E"], m["N"]], "cota": m.get("cota_m"), "topo": bool(m.get("topo")), "prancha": m.get("prancha"),
             "escrita": str(m.get("texto") or "").endswith(SUFIXO_ESCRITA)} for m in marcas_cota]


def _alertas_das_cavas(r: dict) -> list[str]:
    """Avisos do `calcular`: bases sem marca, marcas fora da faixa e cavas na borda do levantamento."""
    alertas = []
    if r["alertas_fundo"]:
        alertas.append(f"{len(r['alertas_fundo'])} base(s) com o fundo pela marca vizinha (sem marca interna nem cota "
                       f"escrita): {'; '.join(r['alertas_fundo'])}")
    if r["bases_sem_marca"]:
        alertas.append(f"{r['bases_sem_marca']} base(s) sem marca de cota de fundo (dentro, escrita ou a ≤ "
                       f"{VALOR['raio_marca_m']:g} m): ficam fora do cálculo")
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
    de toda regra). Devolve {saída: {id da cava: valor}}, `pontos` ({id: [E, N]}, um ponto dentro de cada cava, para o
    setor) e `alertas`."""
    bases_da_obra = [{"geom": _poligono(b["coords"]), "etapa": b.get("etapa")} for b in dados["bases"]]
    cristas = [LineString(c) for c in dados.get("cristas") or []]
    r = calcular(bases_da_obra, _marcas_da_gaveta(dados["marcas_cota"]), cristas, dados["superficie"])
    saidas = {saida: {c["id"]: c[campo] for c in r["cavas"]} for saida, campo in SAIDAS_CAVA.items()}
    pontos = {c["id"]: [round(v, 3) for v in c["contorno"].representative_point().coords[0]]
              for c in r["cavas"] if not c["contorno"].is_empty}          # onde cada cava está (setor da ETA)
    return {**saidas, "pontos": pontos, "alertas": _alertas_das_cavas(r)}


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
    saida.update(marcas=ms, bases=bs, cristas=cristas, g=g, pranchas=lidas, corte=r["corte"], bases_fundo=r["bases_fundo"],
                 contornos={cv["id"]: cv["contorno"] for cv in r["cavas"]},
                 cavas_info=[{"id": cv["id"], "fundo_m": cv["fundo_m"]} for cv in r["cavas"]],
                 resultado={"cavas": [{k: cv[k] for k in campos} for cv in r["cavas"]]})


def _curvas_da_topografia(t: dict, out: Path) -> list[dict]:
    """Curvas de nível da prancha de topografia (`topografia.curvas_de_nivel`); a leitura por OCR fica em cache em
    `out/topografia_curvas_cache.json`, com assinatura da versão da leitura, do PDF, da afim e dos layers (sem a versão, um
    cache antigo era reaproveitado em silêncio depois de mudar a leitura)."""
    from . import topografia

    arq = Path(t["pdf"])
    assinatura = (f"v{topografia.VERSAO_LEITURA_CURVAS}:{arq.stat().st_size}:{int(arq.stat().st_mtime)}:"
                  f"{np.asarray(t['M']).round(6).tolist()}:{t.get('layers')}")
    cache_arq = out / "topografia_curvas_cache.json"
    cache = json.loads(cache_arq.read_text()) if cache_arq.exists() else {}
    if cache.get("assinatura") != assinatura:
        curvas = topografia.curvas_de_nivel(arq, t["M"], layers=t.get("layers"))
        cache = {"assinatura": assinatura, "curvas": curvas}
        cache_arq.write_text(json.dumps(cache, ensure_ascii=False, default=float))
    return cache["curvas"]


def _furos_da_obra(cfg: dict) -> list[dict]:
    """Furos de sondagem (`sondagens` do obra.json) com E, N e cota_boca; vazio se o arquivo não existe."""
    arq = Path(cfg.get("sondagens", ""))
    if not arq.is_file():
        return []
    return [f for f in json.loads(arq.read_text(encoding="utf-8"))["furos"] if "cota_boca" in f]


def terreno_composto(g: dict, c: dict | None, out: Path, log=print, furos: list[dict] | None = None) -> None:
    """Troca `g["terreno"]` pelo terreno composto quando o `obra.json` pede (`escavacao.terreno.fonte` =
    "topografia_e_mds"): topografia do projeto dentro do casco das curvas, MDS corrigido fora, costura de
    `faixa_costura_m` (`topografia.compor_terreno`). Guarda em `g` o MDS original (`terreno_mds`), a origem por célula
    (`origem_terreno`, índice em `topografia.ORIGENS_TERRENO`) e o resumo (`terreno_resumo`, m²). Sem a chave, nada muda.
    `furos` (id, E, N, cota_boca) validam o MDS corrigido fora do casco. Sem scipy ou sem o PDF, fica o MDS e o log diz
    que a topografia não foi aplicada (pendência)."""
    if not c or c.get("fonte") != "topografia_e_mds":
        return
    from . import topografia

    t = c["topografia"]
    if not Path(t["pdf"]).exists():
        log(f"Terreno das cavas: PDF da topografia ausente ({t['pdf']}); fica o MDS (pendência)")
        return
    try:
        curvas = _curvas_da_topografia(t, out)
        topo = topografia.superficie(curvas, g)
    except ImportError as erro:
        log(f"Terreno das cavas: topografia NÃO aplicada, falta {erro.name} (pendência; fica o MDS)")
        return
    alta = g.get("vegetacao_alta", np.zeros(g["forma"], bool))
    comp = topografia.compor_terreno(g, topo, alta, c.get("faixa_costura_m", topografia.FAIXA_COSTURA_PADRAO_M), furos)
    g.update(terreno_mds=g["terreno"], terreno=comp["terreno"], origem_terreno=comp["origem"],
             terreno_resumo={**comp["resumo"], "fonte": c.get("justificativa", ""), "plano_mds": comp["plano"]})
    r = comp["resumo"]
    log(f"Terreno das cavas: topografia no casco, MDS corrigido fora (plano {comp['plano']['coeficientes']}); "
        f"m² por origem {r['area_m2']}; sem terreno {r['sem_terreno']}")
    for aviso in r["alertas"]:
        log(f"Terreno das cavas: ALERTA {aviso}")


def etapa(cfg: dict, pranchas: list, out: Path, vertical: dict | None, log=print,
          saida_gavetas: dict | None = None) -> dict | None:
    """Etapa da obra: lê as plantas de escavação (OCR com cache), calcula as cavas e devolve o pacote do HTML.
    `saida_gavetas`, se passado, recebe as entradas e o resultado do cálculo para as gavetas (sem mudar o retorno)."""
    c = cfg.get("escavacao")
    if c and not vertical:     # sem sondagens não há controle vertical: as cavas não saem, e isso tem de aparecer
        log("Escavação: NÃO CALCULADA — sem controle vertical, faltam as sondagens (pendência; o build segue)")
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
        bs_da_prancha = bases(tr, c["layer_base"], p["M"], c["cores_etapa"])
        if cache.get(pid, {}).get("assinatura") != assinatura:
            cache[pid] = {"assinatura": assinatura, "marcas": marcas(p["pdf"], tr, c["layer_marca"], p["M"])}
        if cache[pid].get("versao_cotas_escritas") != VERSAO_COTAS_ESCRITAS:        # leitura nova ou mudada: relê só ela
            cache[pid] |= {"versao_cotas_escritas": VERSAO_COTAS_ESCRITAS, "cotas_escritas": cotas_escritas(
                p["pdf"], tr, p["M"], bs_da_prancha, cache[pid]["marcas"])}
            cache_arq.write_text(json.dumps(cache, ensure_ascii=False))
        lidas.append(pid)
        ms += [{**m, "prancha": pid} for m in cache[pid]["marcas"]]
        ms += [{**m, "prancha": pid, "escrita": True, "texto": f"{m['cota']:.2f}".replace(".", ",") + SUFIXO_ESCRITA}
               for m in cache[pid]["cotas_escritas"]]
        bs += bs_da_prancha
        cristas += linhas_utm(tr, c["layer_crista"], p["M"])
    g = grade(out / "sfm" / "ortofoto.jpg", out / "sfm" / "ortofoto_mds.png", vertical)
    terreno_composto(g, c.get("terreno"), out, log, _furos_da_obra(cfg))
    r = calcular(bs, ms, cristas, g)
    if saida_gavetas is not None:
        _entregar_as_gavetas(saida_gavetas, ms, bs, cristas, g, r, lidas)
    r["conferencia_crista"] = conferir_crista(r.pop("modelo"), cristas)
    tot = {k: round(sum(cv[k] for cv in r["cavas"]), 1) for k in ("escavacao_m3", "reaterro_m3", "area_m2")}
    log(f"Escavação: {len(r['cavas'])} cavas, {tot['escavacao_m3']:.0f} m³ escavação, {tot['reaterro_m3']:.0f} m³ "
        f"reaterro (só o modelo: {r['modelo_m3']:.0f} m³); marcas {r['marcas']}; origem do fundo por base "
        f"{r['origem_fundo']}; crista desenhada × modelo: {r['conferencia_crista']}")
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
            "bases_sem_marca": r["bases_sem_marca"], "origem_fundo": r["origem_fundo"],
            "alertas_fundo": r["alertas_fundo"], "conferencia_crista": r["conferencia_crista"],
            "parametros": r["parametros"], "fonte": c.get("fonte", ""), "premissas": REGRAS["metadata"]["observacoes"],
            "geojson": {"type": "FeatureCollection", "features": feats}}


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "escavacao",
        "descricao": "escavação e reaterro por cava: base das estruturas + cota de fundo (OCR) + crista desenhada + "
                     "talude + MDS em cota",
        "funcoes": ["ler_cota", "marcas", "cotas_escritas", "bases", "chao_pmf", "grade", "plausiveis", "ligar_marcas",
                    "fundo_na_grade",
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
