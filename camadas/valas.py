"""Valas das redes: em que superfície passa cada metro de tubo e o que demolir e recompor.

    amostras  = pontos a cada `passo_m` no eixo do tubo (faixa preenchida: a borda deslocada meia largura para dentro)
    divisas   = raios perpendiculares contam as linhas de divisa/meio-fio de cada lado
                -> pista, calçada, via sem meio-fio no desenho ou fora da via
    quadras   = entre quadras é rua; até `calcada_quadra_m` do alinhamento é calçada, além é pista
    ortofoto  = superfície existente pela cor (vegetação, solo exposto, pavimentado); a recomposição segue a superfície
                final do projeto de urbanização quando ela cobre o trecho
    vala      = largura e escoramento do dimensionador único (`lineares.dimensionar_vala`, MOS: L = D + SL + X + Y);
                profundidade h = recobrimento da classe + DE + berço
    demolição = recomposição = extensão × (b + 2 × sobrelargura de recorte)

Regras e premissas em `conceitos/valas.json`. É posição no desenho, não cadastro de pavimento: conferir em campo.
"""
from __future__ import annotations

import json
import re

import cv2
import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import LineString, Polygon, mapping

from . import geo, lineares, pdf_cad

REGRAS = json.loads((pdf_cad.CONCEITOS / "valas.json").read_text(encoding="utf-8"))
VALOR = {k: v["valor"] for k, v in REGRAS.items() if isinstance(v, dict) and "valor" in v}
MATERIAL_PADRAO = "FD"                                   # premissa até o contrato dizer o tipo do tubo


def _amostrar(linha, passo: float) -> tuple[np.ndarray, np.ndarray]:
    """Pontos no meio de cada passo e a tangente unitária neles."""
    s = np.arange(passo / 2, linha.length, passo)
    if not len(s):
        return np.empty((0, 2)), np.empty((0, 2))
    p = shapely.get_coordinates(shapely.line_interpolate_point(linha, s))
    t = (shapely.get_coordinates(shapely.line_interpolate_point(linha, np.minimum(s + 0.25, linha.length)))
         - shapely.get_coordinates(shapely.line_interpolate_point(linha, np.maximum(s - 0.25, 0))))
    return p, t / (np.linalg.norm(t, axis=1, keepdims=True) + 1e-12)


def amostras(tracos: list, layer: str, M, janela=None, passo: float | None = None, linha: bool = False) -> dict:
    """Eixo do tubo amostrado em UTM: pontos, tangentes e o comprimento que cada ponto representa.
    `linha`: rede desenhada em traço simples — preenchimentos (setas, símbolos) e traços curtos (texto SHX no mesmo
    layer) ficam de fora."""
    passo = passo or VALOR["passo_m"]
    jan = shapely.box(*janela) if janela else None
    A = np.asarray(M, float)
    cheias, linhas = [], []
    for t in tracos:
        if not re.fullmatch(layer, t["layer"]):
            continue
        for q in map(np.asarray, t["partes"]):
            if len(q) < 2:
                continue
            cheio = t["preenchimento"] is not None and len(q) >= 3
            if linha and cheio:
                continue
            g = Polygon(q).buffer(0) if cheio else LineString(q)
            if jan is not None and not g.intersects(jan):
                continue
            g = shapely.affinity.affine_transform(g if g.geom_type == "Polygon" or jan is None else g.intersection(jan),
                                                  [A[0, 0], A[0, 1], A[1, 0], A[1, 1], A[0, 2], A[1, 2]])
            (cheias if g.geom_type.endswith("Polygon") else linhas).extend(shapely.get_parts(g))
    P, T, W = [], [], []
    if cheias:                                           # polilinha com largura: eixo = borda − meia largura
        faixa = shapely.union_all(cheias).buffer(0.01)
        meia = faixa.area / faixa.length                 # largura/2 = área ÷ perímetro
        for g in shapely.get_parts(faixa):
            p, t = _amostrar(g.exterior, passo)
            n = np.c_[-t[:, 1], t[:, 0]]
            dentro = shapely.contains_xy(faixa, *(p + n * meia).T)
            P.append(p + np.where(dentro[:, None], n, -n) * meia)
            T.append(t)
            W.append(np.full(len(p), passo / 2))         # o anel passa pelos dois lados da faixa
    if linha and linhas:                                 # junta os traços contínuos; sobra curta é letra/símbolo
        linhas = [g for g in shapely.get_parts(shapely.line_merge(shapely.union_all(linhas)))
                  if g.length >= VALOR["min_parte_m"]]
    for ln in linhas:
        p, t = _amostrar(ln, passo)
        P.append(p)
        T.append(t)
        W.append(np.full(len(p), passo))
    if not P:
        return {"pts": np.empty((0, 2)), "tang": np.empty((0, 2)), "peso": np.empty(0)}
    return {"pts": np.vstack(P), "tang": np.vstack(T), "peso": np.concatenate(W)}


def cruzamentos(pts: np.ndarray, tang: np.ndarray, limite, alcance: float) -> tuple[list, list]:
    """Distâncias (ordenadas) das linhas de `limite` cruzadas por raios perpendiculares, à esquerda e à direita."""
    n = np.c_[-tang[:, 1], tang[:, 0]]
    lados = []
    for sinal in (1.0, -1.0):
        raios = shapely.linestrings(np.stack([pts + sinal * n * 0.05, pts + sinal * n * alcance], axis=1))
        xy, i = shapely.get_coordinates(shapely.intersection(raios, limite), return_index=True)
        d = np.linalg.norm(xy - pts[i], axis=1)
        lados.append([sorted(d[i == k].round(2).tolist()) for k in range(len(pts))])
    return lados[0], lados[1]


def classe_divisas(esq: list, dir: list) -> str:
    """Pela contagem de linhas de cada lado (meio-fio por dentro, alinhamento por fora)."""
    c = min(len(esq), len(dir))
    if c >= 2:
        return "pista"
    if c == 1:
        return "calcada" if esq[0] + dir[0] <= VALOR["calcada_max_m"] else "via_sem_meio_fio"
    return "fora_da_via"


def classe_quadras(esq: list, dir: list) -> str:
    """Entre quadras (linha dos dois lados) é rua; perto do alinhamento é calçada."""
    if not esq or not dir:
        return "fora_da_via"
    return "calcada" if min(esq[0], dir[0]) <= VALOR["calcada_quadra_m"] else "pista"


def classe_meio_fio(mf_e: list, mf_d: list, al_e: list, al_d: list) -> str:
    """Pela linha mais próxima de cada lado: meio-fio dos dois lados = pista; meio-fio de um lado e alinhamento do
    outro = calçada; sem meio-fio (o desenho tem o layer) = fora da via."""
    def lado(mf, al):
        if not mf and not al:
            return None
        return "mf" if mf and (not al or mf[0] <= al[0]) else "al"
    e, d = lado(mf_e, al_e), lado(mf_d, al_d)
    if e == d == "mf":
        return "pista"
    return "calcada" if {e, d} == {"mf", "al"} else "fora_da_via"


def ortofoto(caminho) -> dict:
    """Ortofoto em BGR com o georreferenciamento (canto superior esquerdo e resolução)."""
    meta = json.loads(caminho.with_suffix(".json").read_text())
    return {"img": cv2.imread(str(caminho)), "e0": meta["canto_sup_esq"][0], "n1": meta["canto_sup_esq"][1],
            "res": meta["res_m_px"]}


def classe_ortofoto(pts: np.ndarray, orto: dict) -> list[str]:
    """Superfície existente pela cor mediana numa janela em volta de cada ponto."""
    r = REGRAS["ortofoto"]
    img, res = orto["img"], orto["res"]
    h = max(1, int(r["janela_m"] / res))
    lin = ((orto["n1"] - pts[:, 1]) / res).astype(int)
    col = ((pts[:, 0] - orto["e0"]) / res).astype(int)
    out = []
    for i, j in zip(lin, col):
        if not (h <= i < img.shape[0] - h and h <= j < img.shape[1] - h):
            out.append("sem_ortofoto")
            continue
        b, g, rr = np.median(img[i - h:i + h + 1, j - h:j + h + 1].reshape(-1, 3).astype(float), axis=0)
        v, s = max(b, g, rr), (max(b, g, rr) - min(b, g, rr)) / (max(b, g, rr) + 1)
        if v >= 250:
            out.append("sem_ortofoto")
        elif (2 * g - rr - b) / (rr + g + b + 1) > r["exg_verde"]:
            out.append("vegetacao")
        elif s >= r["terra_s_min"] and v <= r["terra_v_max"] and rr > b:
            out.append("solo")
        else:
            out.append("pavimentado")
    return out


def urbanizacao(tracos: list, M, camadas: dict, janela=None) -> dict:
    """Superfície final do projeto: {nome: polígono UTM} de cada hachura (preenchida, ou em linhas fechadas por buffer)."""
    x0, y0, x1, y1 = janela or (-np.inf, -np.inf, np.inf, np.inf)
    out = {}
    for nome, layer in camadas.items():
        cheias, linhas = [], []
        for t in tracos:
            if t["layer"] != layer:
                continue
            for q in map(np.asarray, t["partes"]):
                if len(q) >= 2 and x0 <= q[:, 0].min() and q[:, 0].max() <= x1 and y0 <= q[:, 1].min() and q[:, 1].max() <= y1:
                    u = geo.aplicar(np.asarray(M), q)
                    (cheias if t["preenchimento"] is not None and len(q) >= 3 else linhas).append(u)
        if cheias:                                       # hachura preenchida: o preenchimento é a área
            out[nome] = shapely.union_all([Polygon(u).buffer(0) for u in cheias])
        else:                                            # hachura em linhas: fecha os vãos e volta
            out[nome] = shapely.union_all([LineString(u).buffer(0.5) for u in linhas]).buffer(0.05).buffer(-0.45)
    return out


def _dimensionar(classe: str, de_m: float, material: str, dn_mm: float) -> dict:
    """Vala de 1 m de tubo da classe pelo dimensionador único (`lineares.dimensionar_vala`): largura pelo MOS
    (L = D + SL + X + Y). Profundidade de premissa = recobrimento da classe + DE + berço (sem perfil)."""
    prof_m = REGRAS["recobrimento_m"][REGRAS["classes"][classe]["recobrimento"]] + de_m + VALOR["berco_m"]
    trecho = {"local": classe, "dn_mm": dn_mm, "material": material, "prof_m": round(prof_m, 3), "comp_m": 1.0,
              "metodo": "VCA"}
    return lineares.dimensionar_vala(trecho)


def secao(classe: str, de_m: float, material: str = MATERIAL_PADRAO, dn_mm: float | None = None) -> tuple[float, float]:
    """Largura e profundidade da vala (m) para a classe e o diâmetro externo, vindas do dimensionador único (MOS).
    Se a Tabela I do MOS não cobre o material e o DN, a largura cai para DE + folga (NBR 12266) e `quantificar` avisa."""
    d = _dimensionar(classe, de_m, material, dn_mm or round(de_m * 1000))
    if d["largura_m"] is None:
        lv = REGRAS["largura_vala"]
        return max(de_m + lv["folga_m"], lv["minimo_m"]), d["profundidade_m"]
    return d["largura_m"], d["profundidade_m"]


def quantificar(classes: list[str], pesos: np.ndarray, de_m: float, finais: list | None = None,
                material: str | None = None, dn_mm: float | None = None) -> list[dict]:
    """Extensão, demolição, recomposição e volume de vala por classe (e superfície final, quando há urbanização).
    Largura, profundidade e escoramento vêm do dimensionador único; `material` (padrão FD, com alerta) e `dn_mm`
    (padrão = DE) definem a largura pelo MOS. Demolição/recomposição seguem aqui: sobrelargura de recorte, classe e
    a regra 'coberta pela urbanização'."""
    alertas_rede = []
    if material is None:
        material = MATERIAL_PADRAO
        alertas_rede.append(f"material de premissa ({MATERIAL_PADRAO}): confirmar o tipo do tubo no contrato")
    dn_mm = dn_mm or round(de_m * 1000)
    grupos: dict[tuple, float] = {}
    for i, c in enumerate(classes):
        chave = (c, finais[i] if finais else None)
        grupos[chave] = grupos.get(chave, 0.0) + float(pesos[i])
    linhas = []
    for (c, final), ext in sorted(grupos.items(), key=lambda kv: -kv[1]):
        d = _dimensionar(c, de_m, material, dn_mm)
        alertas = [*alertas_rede, *d["alertas"]]
        if d["largura_m"] is None:
            b, h = secao(c, de_m, material, dn_mm)
            alertas.append(f"largura pela NBR 12266 (DE + folga): {material} DN {dn_mm} fora da Tabela I do MOS")
        else:
            b, h = d["largura_m"], d["profundidade_m"]
        faixa = b + 2 * VALOR["sobrelargura_recorte_m"]
        k = REGRAS["classes"][c]
        recomp = f"coberta pela urbanização ({final})" if final else k["recomposicao"]
        linhas.append({"classe": c, "nome": k["nome"], "final": final, "extensao_m": round(ext, 1),
                       "material": material, "dn_mm": dn_mm,
                       "largura_m": round(b, 2), "profundidade_m": round(h, 2),
                       "escorado": d["escorado"], "tipo_escoramento": d["tipo_escoramento"],
                       "alertas": alertas,
                       "demolicao": k["demolicao"], "demolicao_m2": round(ext * faixa, 1) if k["demolicao"] else 0.0,
                       "recomposicao": recomp,
                       "recomposicao_m2": round(ext * faixa, 1) if (k["recomposicao"] and not final) else 0.0,
                       "volume_vala_m3": round(ext * b * h, 1)})
    return linhas


def classificar(am: dict, criterio: str, limites: dict, orto: dict | None = None, final: dict | None = None):
    """Classe de cada amostra pelo critério da rede; na ETA, também a superfície final (urbanização) ou None."""
    alc = VALOR["alcance_m"]
    if criterio in ("divisas", "quadras"):
        esq, dir = cruzamentos(am["pts"], am["tang"], limites["limite"], alc)
        f = classe_divisas if criterio == "divisas" else classe_quadras
        return [f(e, d) for e, d in zip(esq, dir)], None
    if criterio == "meio_fio":
        mf = cruzamentos(am["pts"], am["tang"], limites["meio_fio"], alc)
        al = cruzamentos(am["pts"], am["tang"], limites["alinhamento"], alc)
        return [classe_meio_fio(*x) for x in zip(mf[0], mf[1], al[0], al[1])], None
    classes = classe_ortofoto(am["pts"], orto)
    finais = [None] * len(classes)
    for nome, g in (final or {}).items():                # a primeira superfície final que contém o ponto vence
        for i in np.flatnonzero(shapely.contains_xy(g, *am["pts"].T)):
            finais[i] = finais[i] or nome
    return classes, finais


def rede(r: dict, por_id: dict, orto: dict | None, final: dict | None) -> dict | None:
    """Uma rede (uma ou várias pranchas): amostras classificadas e o quadro por classe."""
    pts, tang, peso, classes, finais = [], [], [], [], []
    for pid in r["pranchas"]:
        p = por_id.get(pid)
        if p is None or p.get("M") is None:
            continue
        tr = pdf_cad.extrair(p["pdf"], clip=p.get("clip"))
        am = amostras(tr, r.get("layer") or re.escape(p["layer_tubo"]), p["M"], p.get("clip_mapa"), linha=bool(r.get("layer")))
        limites = {k: shapely.union_all([LineString(geo.aplicar(np.asarray(p["M"]), np.asarray(q))) for t in tr
                                         if t["layer"] == r[f"layer_{k}"] for q in t["partes"] if len(q) >= 2])
                   for k in ("limite", "meio_fio", "alinhamento") if r.get(f"layer_{k}")}
        c, f = classificar(am, r["criterio"], limites, orto, final)
        pts.append(am["pts"])
        tang.append(am["tang"])
        peso.append(am["peso"])
        classes += c
        finais += f or [None] * len(c)
    if not classes:
        return None
    peso = np.concatenate(peso)
    return {"id": r["id"], "de_mm": r["de_mm"], "fonte_de": r.get("fonte_de", ""),
            "material": r.get("material") or MATERIAL_PADRAO, "dn_mm": r.get("dn_mm") or r["de_mm"], "criterio": r["criterio"],
            "extensao_m": round(float(peso.sum()), 1), "pts": np.vstack(pts), "tang": np.vstack(tang), "peso": peso,
            "classes": classes, "quadro": quantificar(classes, peso, r["de_mm"] / 1000, finais if any(finais) else None,
                                                    r.get("material"), r.get("dn_mm"))}


def de_do_escopo(pranchas: list[str], tubo_x_desenho: list[dict]) -> tuple[int | None, str]:
    """DE (mm) do tubo principal das pranchas, pela descrição do item do contrato ligado a elas."""
    for linha in tubo_x_desenho or []:
        if linha["prancha"] in pranchas:
            m = re.search(r"\b(?:DE|DN)\s*(\d{2,4})\b", linha["descricao"])
            if m:
                return int(m[1]), f"contrato: {linha['descricao']} (tabela {', '.join(linha['tabelas'])})"
    return None, ""


def etapa(cfg: dict, pranchas: list, lista: list, escopo: dict | None, out, epsg: int, log=print) -> dict | None:
    """Etapa da obra: classifica as valas de cada rede declarada em `valas.redes` e devolve o pacote do HTML."""
    c = cfg.get("valas")
    if not c:
        return None
    clip = {l["id"]: l.get("clip_mapa") for l in lista}
    por_id = {p["id"]: {**p, "clip_mapa": clip.get(p["id"])} for p in pranchas}
    orto = ortofoto(out / "sfm" / "ortofoto.jpg")
    final = None
    u = c.get("urbanizacao")
    if u and por_id.get(u["prancha"], {}).get("M") is not None:
        pu = por_id[u["prancha"]]
        final = urbanizacao(pdf_cad.extrair(pu["pdf"], clip=pu.get("clip")), pu["M"], u["camadas"], pu["clip_mapa"])
    redes = []
    for r in c["redes"]:
        de, fonte = (r.get("de_mm"), r.get("fonte_de", "")) if r.get("de_mm") else \
            de_do_escopo(r["pranchas"], (escopo or {}).get("tubo_x_desenho"))
        if de is None:
            log(f"Valas: {r['id']} sem DE (nem no obra.json nem no contrato), fica de fora")
            continue
        v = rede({**r, "de_mm": de, "fonte_de": fonte}, por_id, orto, final)
        if v:
            redes.append(v)
            log(f"Valas {v['id']} (DE {de}): " + "; ".join(f"{q['nome']} {q['extensao_m']:.0f} m" for q in v["quadro"]))
    return para_html(redes, c, final, epsg) if redes else None


def para_html(redes: list[dict], c: dict, final: dict | None, epsg: int) -> dict:
    """Quadro por rede e camada do mapa (trechos coloridos pela classe). Só exibição no front."""
    passo = VALOR["passo_m"]
    feats = []
    for v in redes:
        for cl in sorted(set(v["classes"])):
            sel = np.array(v["classes"]) == cl
            p, t = v["pts"][sel], v["tang"][sel]
            seg = shapely.linestrings(np.stack([p - t * passo / 2, p + t * passo / 2], axis=1))
            g = shapely.line_merge(shapely.union_all(seg))
            ll = shapely.transform(g, lambda xy: np.column_stack(geo.para_lonlat(xy[:, 0], xy[:, 1], epsg)))
            feats.append({"type": "Feature", "geometry": mapping(ll),
                          "properties": {"rede": v["id"], "classe": cl, "tipo": REGRAS["classes"][cl]["nome"],
                                         "cor": REGRAS["classes"][cl]["cor"], "extensao_m": round(float(v["peso"][sel].sum()), 1),
                                         "estimado": True}})
    tabela = [{k: v[k] for k in ("id", "de_mm", "fonte_de", "criterio", "extensao_m", "quadro")}
              | {"material": v.get("material", MATERIAL_PADRAO), "dn_mm": v.get("dn_mm", v["de_mm"])} for v in redes]
    return {"redes": tabela, "classes": {k: {"nome": v["nome"], "cor": v["cor"]} for k, v in REGRAS["classes"].items()},
            "urbanizacao_m2": {n: round(g.area, 1) for n, g in (final or {}).items()},
            "fonte": c.get("fonte", ""), "fora": c.get("fora", []), "premissas": REGRAS["metadata"]["observacoes"],
            "geojson": {"type": "FeatureCollection", "features": feats}}


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "valas",
        "descricao": "classe da superfície em cada metro de tubo (desenho ou ortofoto) e o quadro de demolição, "
                     "recomposição e volume de vala por rede",
        "funcoes": ["amostras", "cruzamentos", "classe_divisas", "classe_quadras", "classe_meio_fio", "ortofoto", "classe_ortofoto",
                    "urbanizacao", "secao", "quantificar", "classificar", "rede", "de_do_escopo", "etapa", "para_html"],
        "bibliografia": [
            {"obra": "ABNT NBR 12266 — Projeto e execução de valas para assentamento de tubulação de água, esgoto ou "
                     "drenagem urbana", "ano": 1992, "editora": "ABNT",
             "aplicacao": {"secao": ["recobrimento 1,0 m via / 0,6 m passeio", "largura DE + 0,60 m só se o MOS não cobre o caso"]}},
            {"obra": "Woebbecke et al. — Color indices for weed identification (ExG = 2G − R − B)", "ano": 1995,
             "editora": "Transactions of the ASAE", "aplicacao": {"classe_ortofoto": ["exg_verde=0,06"]}},
        ],
        "premissas": [{"aplicacao": {k: [k]}, "fonte": v["fonte"], "estado": v["estado"]}
                      for k, v in REGRAS.items() if isinstance(v, dict) and "fonte" in v],
    }
