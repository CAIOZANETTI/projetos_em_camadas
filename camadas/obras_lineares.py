"""Obras lineares: vala de cada trecho de tubo pelo MOS Sanepar, com solo e lençol da sondagem e pavimento da ortofoto.

    trecho     = local, DN, material, profundidade média, comprimento, método (VCA ou MND), pavimentos e sondagens
    largura    = L = D + SL + X + Y (MOS): SL pela Tabela I, X = 0,10 m se escorado, Y = 0,10 m por metro ou fração
                 acima de 2 m
    escoramento= profundidade > 1,25 m (NR-18; fórmula da coluna AD da planilha)
    VCA        = escavação = comprimento × L × profundidade; reaterro = escavação − π·DN²/4 × comprimento;
                 bota-fora = volume do tubo × empolamento; pavimento = comprimento do tipo × L
    MND        = sem vala: só os caximbos (1 a cada 80 m, 4,5 m²) escavam e demolem
    sondagem   = cada metro na sondagem mais próxima dentro do raio de influência (com o eixo em UTM) ou metade na
                 inicial e metade na final (só os ids da planilha); solo pela descrição das camadas até o fundo da
                 vala; NA mais raso que o fundo = esgotamento
    ortofoto   = verde = grama, preto = asfalto, cinza claro = concreto/calçada (camadas.valas.classe_ortofoto)

Regras em `conceitos/obras_lineares.json`. Sem preço: só geometria e serviço associado.

    python -m camadas.obras_lineares PLANILHA.xlsx [--sondagens furos.json] [--saida pasta]
"""
from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np
import openpyxl
import pandas as pd

from . import geotecnia as geo
from . import pdf_cad, valas

REGRAS = json.loads((pdf_cad.CONCEITOS / "obras_lineares.json").read_text(encoding="utf-8"))
PAVIMENTOS = list(REGRAS["pavimentos"]["tipos"])
CAMPOS = {"local": "LOCAL", "dn_mm": "DN DO TUBO", "material": "TIPO DO TUBO", "sond_ini": "SONDAGEM", "na_m": "NA",
          "solo": "TIPO DE SOLO", "prof_m": "PROF. MEDIA", "escoramento": "ESCORAMENTO", "comp_m": "COMPRIMENTO TOTAL",
          "metodo": "METODO CONSTRUTIVO", "largura_m": "LARGURA DA VALA", "area_m2": "AREA",
          "escavacao_m3": "ESCAVACAO", "reaterro_m3": "REATERRO", "bota_fora_m3": "BOTA FORA",
          "supressao_m2": "SUPRESSAO VEGETAL", "obs": "OBSERVACOES"}


def norm(texto) -> str:
    """Maiúsculas sem acento e com espaços simples (para casar cabeçalhos e descrições)."""
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().upper()


# --------------------------------------------------------------------------------------------------------------------
# Seção da vala (MOS)
# --------------------------------------------------------------------------------------------------------------------

def sobrelargura(material: str, dn_mm: float, junta: str | None = None) -> float | None:
    """SL (m) da Tabela I do MOS pelo material, DN e junta; None quando a tabela não cobre o caso."""
    s = REGRAS["sobrelargura"]
    m = norm(material)
    junta = junta or s["junta_padrao"]["PEAD" if "PEAD" in m else "outros"]
    for linha in s["tabela"]:
        if re.search(rf"\b(?:{linha['material']})\b", m) and linha["junta"] == junta \
                and linha["dn_min"] <= dn_mm <= linha["dn_max"]:
            return linha["sl_m"]
    return None


def escorar(prof_m: float | None) -> bool:
    """Escoramento obrigatório acima de 1,25 m de profundidade."""
    return prof_m is not None and prof_m > REGRAS["escoramento"]["valor"]


def largura(dn_mm: float, material: str, prof_m: float, escorado: bool, junta: str | None = None) -> float | None:
    """L = D + SL + X + Y (m)."""
    lv = REGRAS["largura_vala"]
    sl = sobrelargura(material, dn_mm, junta)
    if sl is None:
        return None
    y = lv["Y_por_metro_m"] * math.ceil(round(prof_m - lv["Y_a_partir_de_m"], 6)) if prof_m > lv["Y_a_partir_de_m"] else 0.0
    return round(dn_mm / 1000 + sl + (lv["X_escoramento_m"] if escorado else 0.0) + y, 3)


# --------------------------------------------------------------------------------------------------------------------
# Sondagem: solo e lençol no trecho
# --------------------------------------------------------------------------------------------------------------------

def classe_solo(descricao: str, classe: str | None = None) -> dict:
    """Classe e categoria de escavação de uma camada da sondagem (delega ao modelo geotécnico único)."""
    return geo.classe_solo(descricao, classe)


def solo_na_vala(furo: dict, prof_m: float) -> dict[str, float]:
    """Fração da altura da vala (0 a prof_m) em cada classe de solo do furo (delega ao modelo geotécnico único)."""
    return geo.solo_na_faixa(furo, 0.0, prof_m)


def _id_furo_calculado(texto) -> str:
    t = re.sub(r"[^A-Z0-9]", "", norm(texto)).replace("SPT", "SP")
    return re.sub(r"(?<=[A-Z])0+(?=\d)", "", t)


_id_furo_em_cache = lru_cache(maxsize=None, typed=True)(_id_furo_calculado)


def id_furo(texto) -> str:
    """Id comparável de sondagem: 'SP-02', 'SP02', 'SPT-2' e 'SP 2' são o mesmo furo. Só str, int e float usam o
    cache (tipos separados: 2 e 2.0 não se misturam); qualquer outro tipo, mesmo não hashable, é calculado direto."""
    if type(texto) in (str, int, float):
        return _id_furo_em_cache(texto)
    return _id_furo_calculado(texto)


def furos_com_xy(furos: list[dict]) -> tuple[list[dict], np.ndarray]:
    """Os furos com E e N válidos (o mesmo critério de `geotecnia.furo_mais_proximo`), na ordem original, e a matriz
    (n, 2) das posições. Quem chama muitas vezes com a mesma lista calcula uma vez e passa em `preparado`."""
    com_xy = [f for f in furos if geo._numero(f.get("E")) and geo._numero(f.get("N"))]
    return com_xy, np.array([[f["E"], f["N"]] for f in com_xy], float).reshape(-1, 2)


def furo_por_metro(pts: np.ndarray, furos: list[dict], preparado: tuple | None = None) -> list[str | None]:
    """Id do furo mais próximo de cada ponto do eixo (UTM) dentro do raio de influência; None fora dele.

    A conta é a de `geotecnia.furo_mais_proximo` (fonte única), só sobre os furos dentro da caixa do eixo ampliada
    pelo raio (folga de 1 µm): o mais próximo de um ponto que está no raio sempre está na caixa, e a ordem original
    resolve o empate, então o resultado é o mesmo da conta contra todos os furos. `preparado`: `furos_com_xy(furos)`."""
    com_xy, xy = preparado if preparado is not None else furos_com_xy(furos)
    pts = np.asarray(pts, float).reshape(-1, 2)
    if not com_xy or len(pts) == 0:
        return [None] * len(pts)
    raio = geo.RAIO_INFLUENCIA_M
    folga = raio + 1e-6
    if np.isnan(pts).all(axis=0).any():                  # coluna sem nenhum valor: nenhum ponto tem distância
        return [None] * len(pts)
    dentro = np.all((xy >= np.nanmin(pts, axis=0) - folga) & (xy <= np.nanmax(pts, axis=0) + folga), axis=1)
    candidatos = [f for f, d in zip(com_xy, dentro, strict=True) if d]
    indices, distancias_m = geo.furo_mais_proximo(pts, candidatos)
    return [candidatos[k]["id"] if k >= 0 and d <= raio else None
            for k, d in zip(indices, distancias_m, strict=True)]


def cobertura(trecho: dict, furos: list[dict], pts: np.ndarray | None = None) -> dict[str | None, float]:
    """Fração do trecho em cada furo: pela posição (eixo amostrado) ou metade inicial/metade final (ids da planilha)."""
    if pts is not None and len(pts):
        ids = furo_por_metro(pts, furos)
        return {k: ids.count(k) / len(ids) for k in dict.fromkeys(ids)}
    ini, fim = trecho.get("sond_ini"), trecho.get("sond_fim") or trecho.get("sond_ini")
    return {ini: 1.0} if ini == fim else {ini: 0.5, fim: 0.5}


def geotecnia(trecho: dict, furos: list[dict], pts: np.ndarray | None = None) -> dict:
    """Solo (fração por classe e categoria), NA e esgotamento do trecho pelas sondagens que o cobrem; sem o arquivo
    de sondagens, o solo e o NA digitados na planilha."""
    prof = trecho.get("prof_m")
    por_id = {id_furo(f["id"]): f for f in furos}
    solos: dict[str, float] = {}
    nas, sem, esgota = [], 0.0, 0.0
    if not furos and trecho.get("solo"):
        solos[classe_solo(trecho["solo"])["classe"]] = 1.0
    for fid, frac in (cobertura(trecho, furos, pts) if furos else {}).items():
        furo = por_id.get(id_furo(fid)) if fid else None
        if furo is None:
            sem += frac
            continue
        for cl, f in (solo_na_vala(furo, prof) if prof else {}).items():
            solos[cl] = solos.get(cl, 0.0) + f * frac
        if furo.get("na_m") is not None:
            nas.append(furo["na_m"])
            esgota += frac if prof and furo["na_m"] < prof else 0.0
    if not nas and trecho.get("na_m") is not None:            # só o NA da planilha
        nas.append(trecho["na_m"])
        esgota = 1.0 - sem if prof and trecho["na_m"] < prof else 0.0
    cat = geo.CATEGORIA_POR_CLASSE
    return {"solos": {k: round(v, 3) for k, v in solos.items()},
            "categorias": {c: round(sum(v for k, v in solos.items() if cat.get(k, "a definir") == c), 3)
                           for c in sorted({cat.get(k, "a definir") for k in solos})},
            "na_min_m": min(nas) if nas else None, "esgotamento_frac": round(esgota, 3), "sem_sondagem_frac": round(sem, 3)}


# --------------------------------------------------------------------------------------------------------------------
# Pavimento pela ortofoto
# --------------------------------------------------------------------------------------------------------------------

def brilho(pts: np.ndarray, orto: dict) -> np.ndarray:
    """Brilho (máximo de B, G, R, mediana numa janela) em cada ponto; NaN fora da ortofoto."""
    img, res = orto["img"], orto["res"]
    h = max(1, int(valas.REGRAS["ortofoto"]["janela_m"] / res))
    lin = ((orto["n1"] - pts[:, 1]) / res).astype(int)
    col = ((pts[:, 0] - orto["e0"]) / res).astype(int)
    out = np.full(len(pts), np.nan)
    for k, (i, j) in enumerate(zip(lin, col)):
        if h <= i < img.shape[0] - h and h <= j < img.shape[1] - h:
            out[k] = np.median(img[i - h:i + h + 1, j - h:j + h + 1].max(axis=2))
    return out


def pavimentos_ortofoto(pts: np.ndarray, peso: np.ndarray, orto: dict) -> dict[str, float]:
    """Comprimento (m) em cada tipo de pavimento existente ao longo do eixo amostrado."""
    p = REGRAS["pavimentos"]
    classes, v = valas.classe_ortofoto(pts, orto), brilho(pts, orto)
    out: dict[str, float] = {}
    for c, b, w in zip(classes, v, peso):
        tipo = ("asfalto" if b <= p["asfalto_v_max"] else "concreto") if c == "pavimentado" else p["da_ortofoto"].get(c)
        if tipo:
            out[tipo] = round(out.get(tipo, 0.0) + float(w), 2)
    return out


def no_eixo(trecho: dict, eixo, orto: dict | None = None) -> tuple[dict, np.ndarray]:
    """Trecho com o eixo desenhado (LineString em UTM): comprimento, pavimentos e supressão pela ortofoto; devolve
    também os pontos amostrados, que dão a sondagem de cada metro em `quantificar`."""
    pts, _ = valas._amostrar(eixo, valas.VALOR["passo_m"])
    t = {**trecho, "comp_m": round(eixo.length, 2)}
    if orto is not None and len(pts):
        pav = pavimentos_ortofoto(pts, np.full(len(pts), eixo.length / len(pts)), orto)
        if pav:
            t["pavimentos"] = pav
            t["supressao_frac"] = round(pav.get("grama", 0.0) / eixo.length, 3)
    return t, pts


# --------------------------------------------------------------------------------------------------------------------
# Quantidades por trecho
# --------------------------------------------------------------------------------------------------------------------

def vca(t: dict, larg: float) -> dict:
    """Vala a céu aberto: área, escavação, reaterro, bota-fora, pavimento e supressão."""
    comp, prof = t["comp_m"], t["prof_m"]
    tubo = math.pi * (t["dn_mm"] / 1000) ** 2 / 4 * comp
    esc = comp * larg * prof
    pav = {k: round(v * larg, 2) for k, v in (t.get("pavimentos") or {}).items() if v}
    return {"largura_m": larg, "area_m2": round(comp * larg, 3), "escavacao_m3": round(esc, 3),
            "reaterro_m3": round(esc - tubo, 3), "bota_fora_m3": round(tubo * geo.EMPOLAMENTO_SOLO, 3),
            "escoramento_m2": round(2 * comp * prof, 2) if t["escorado"] else 0.0,
            "supressao_m2": round(comp * larg * (t.get("supressao_frac") or 0.0), 3),
            "pavimento_m2": pav, "caximbos": 0}


def mnd(t: dict) -> dict:
    """Método não destrutivo: só os caximbos escavam e demolem (pavimento dominante do trecho)."""
    cx = REGRAS["caximbo"]
    n = max(2, math.ceil(t["comp_m"] / cx["a_cada_m"]))
    area = n * cx["area_m2"]
    pav = t.get("pavimentos") or {}
    dom = max(pav, key=pav.get) if pav else None
    esc = area * (t.get("prof_m") or 0.0)
    return {"largura_m": None, "area_m2": area, "escavacao_m3": round(esc, 3), "reaterro_m3": round(esc, 3),
            "bota_fora_m3": 0.0, "escoramento_m2": 0.0, "supressao_m2": 0.0,
            "pavimento_m2": {dom: area} if dom else {}, "caximbos": n}


def quantificar(trecho: dict, furos: list[dict] | None = None, pts: np.ndarray | None = None) -> dict:
    """Trecho completo: escoramento, largura (MOS), quantidades do método, geotecnia e alertas."""
    t = {**trecho, "metodo": norm(trecho.get("metodo") or "VCA")}
    prof, alertas = t.get("prof_m"), []
    t["escorado"] = escorar(prof)
    geo = geotecnia(t, furos or [], pts)
    if not prof:
        alertas.append("sem profundidade média: largura, escoramento e volumes não calculados")
    larg = largura(t["dn_mm"], t["material"], prof, t["escorado"], t.get("junta")) if prof else None
    if prof and larg is None:
        alertas.append(f"material {t['material']} DN {t['dn_mm']} fora da Tabela I do MOS")
    q = mnd(t) if t["metodo"] == "MND" else vca(t, larg) if larg else {}
    if geo["esgotamento_frac"] > 0:
        alertas.append(f"NA ({geo['na_min_m']} m) acima do fundo da vala ({prof} m): esgotamento de vala")
    if geo["sem_sondagem_frac"] > 0:
        alertas.append(f"{geo['sem_sondagem_frac']:.0%} do trecho sem sondagem dentro do raio de influência")
    soma_pav = sum((t.get("pavimentos") or {}).values())
    if t["metodo"] == "VCA" and soma_pav and abs(soma_pav - t["comp_m"]) > 0.05:
        alertas.append(f"pavimentos somam {soma_pav:g} m e o trecho tem {t['comp_m']:g} m")
    return {**t, **q, "geotecnia": geo, "alertas": alertas}


# --------------------------------------------------------------------------------------------------------------------
# Planilha Sanepar (abas Obras Lineares e CUSTO CIVIL)
# --------------------------------------------------------------------------------------------------------------------

def _cabecalho(ws) -> tuple[int, dict[str, int]]:
    """Linha do cabeçalho da tabela de obras lineares (a que tem 'Local' e 'DN do tubo') e a coluna de cada campo
    (o cabeçalho pode trazer a unidade: 'Escavação (m3)')."""
    for row in ws.iter_rows(min_row=1, max_row=30):
        textos = {norm(c.value): c.column for c in row if isinstance(c.value, str)}
        if "LOCAL" in textos and "DN DO TUBO" in textos:
            col = {k: c for k, v in CAMPOS.items() for t, c in textos.items() if t == v or t.startswith(v + " (")}
            col["sond_fim"] = col["sond_ini"] + 1
            pav = sorted(c for t, c in textos.items() if t.startswith("TIPO DE PAVIMENTO"))
            col["pavimentos"] = [(c, c + 1) for c in pav]
            return row[0].row, col
    raise ValueError("tabela de obras lineares não encontrada (cabeçalho com 'Local' e 'DN do tubo')")


def _pavimentos(ws, r: int, pares: list) -> dict[str, float]:
    """Tipo de pavimento → comprimento (m) de uma linha da planilha."""
    out: dict[str, float] = {}
    for ct, cc in pares:
        tipo, comp = ws.cell(r, ct).value, ws.cell(r, cc).value
        if isinstance(tipo, str) and isinstance(comp, (int, float)) and comp:
            chave = norm(tipo).lower().replace("calcada", "concreto")
            out[chave] = out.get(chave, 0.0) + float(comp)
    return out


def ler_obras_lineares(caminho, aba: str = "Obras Lineares") -> list[dict]:
    """Trechos da tabela 'OBRAS LINEARES' (colunas V–BC): dados de entrada e, à parte, os valores da planilha.
    `metodo_lido` (célula crua) e `supressao_lida` (havia % na observação) dizem o que a planilha trouxe de fato: o
    `metodo` VCA e a `supressao_frac` 0 são padrões deste leitor, e a extração para as gavetas não os grava como fato."""
    ws = openpyxl.load_workbook(caminho, data_only=True)[aba]
    lin, col = _cabecalho(ws)
    trechos = []
    for r in range(lin + 2, ws.max_row + 1):
        v = {k: ws.cell(r, c).value for k, c in col.items() if isinstance(c, int)}
        if not v.get("local") or not isinstance(v.get("dn_mm"), (int, float)):
            continue
        obs = str(v.get("obs") or "")
        pct = re.search(r"(\d+(?:[.,]\d+)?)\s*%", obs)
        trechos.append({
            "linha": r, "local": str(v["local"]).strip(), "dn_mm": float(v["dn_mm"]), "material": str(v["material"]),
            "sond_ini": v.get("sond_ini"), "sond_fim": v.get("sond_fim"), "na_m": v.get("na_m"), "solo": v.get("solo"),
            "prof_m": v.get("prof_m") if isinstance(v.get("prof_m"), (int, float)) else None,
            "comp_m": float(v.get("comp_m") or 0), "metodo": v.get("metodo") or "VCA",
            "metodo_lido": v.get("metodo"), "supressao_lida": bool(pct),
            "pavimentos": _pavimentos(ws, r, col["pavimentos"]),
            "supressao_frac": float(pct[1].replace(",", ".")) / 100 if pct else 0.0, "obs": obs,
            "planilha": {k: v.get(k) for k in ("escoramento", "largura_m", "area_m2", "escavacao_m3", "reaterro_m3",
                                               "bota_fora_m3", "supressao_m2")}})
    return trechos


def ler_custo_civil(caminho, aba: str = "CUSTO CIVIL", unidade: str = "UNIDADE 1") -> list[dict]:
    """Itens em metro da unidade (obras lineares do orçamento) com o código de cada serviço de vala e a prancha."""
    ws = openpyxl.load_workbook(caminho, data_only=True)[aba]
    itens, dentro, atual = [], False, None
    for r in range(1, ws.max_row + 1):
        a, b, c, d, e, h, i = (ws.cell(r, k).value for k in (1, 2, 3, 4, 5, 8, 9))
        if isinstance(a, str) and norm(a).startswith("UNIDADE"):
            dentro = norm(a).startswith(norm(unidade))
        if not dentro:
            continue
        if isinstance(a, str) and re.fullmatch(r"\d+\.\d+", a.strip()) and norm(d) == "M":
            atual = {"item": a.strip(), "descricao": str(c).strip(), "comp_m": e if isinstance(e, (int, float)) else None,
                     "obs": h, "prancha": i, "servicos": []}
            itens.append(atual)
        elif atual and isinstance(b, str) and b.startswith("CVCA"):
            atual["servicos"].append({"codigo": b, "descricao": str(c).strip(), "comp_m": e})
        elif isinstance(a, str) and a.strip():
            atual = None
    return itens


def conferir(q: dict, tol: float = 0.01) -> list[str]:
    """Diferenças entre o cálculo e o valor da planilha (tolerância relativa)."""
    dif = []
    for k, v in q["planilha"].items():
        calc = ("sim" if q["escorado"] else "não") if k == "escoramento" else q.get(k)
        if isinstance(v, str) or isinstance(calc, str):
            if v is not None and norm(v) != norm(calc):
                dif.append(f"{k}: planilha {v}, cálculo {calc}")
        elif isinstance(v, (int, float)) and calc is None and v:
            dif.append(f"{k}: planilha {v:.3f}, sem cálculo")
        elif isinstance(v, (int, float)) and calc is not None and abs(v - calc) > tol * max(abs(calc), 1):
            dif.append(f"{k}: planilha {v:.3f}, cálculo {calc:.3f}")
    return dif


VAZIAS = {"COM", "ADUTORA", "INTERLIGACAO", "MOD", "TRATAMENTO"}


def _chave(texto: str) -> set[str]:
    """Palavras que identificam o trecho ('micro areia' e 'actiflo' são o mesmo módulo; '360L' = '360')."""
    t = re.sub(r"(\d+) ?L\b", r"\1", norm(texto).replace("MICRO AREIA", "ACTIFLO"))
    return {w for w in re.findall(r"[A-Z0-9]{3,}", t) if w not in VAZIAS}


def casar(descricao: str, trechos: list[dict], minimo: float = 0.6) -> list[dict]:
    """Trechos de nome mais parecido com a descrição (palavras em comum / maior conjunto); todos os empatados no topo."""
    k = _chave(descricao)
    nota = [len(k & _chave(t["local"])) / max(len(k), len(_chave(t["local"])), 1) for t in trechos]
    topo = max(nota, default=0.0)
    return [t for t, n in zip(trechos, nota) if n == topo] if topo >= minimo else []


def conciliar(trechos: list[dict], itens: list[dict]) -> list[dict]:
    """Item em metro do CUSTO CIVIL × trechos da aba Obras Lineares (pelas palavras do nome; soma os DN do item)."""
    linhas = []
    for it in itens:
        casados = casar(it["descricao"], trechos)
        soma = sum(t["comp_m"] for t in casados)
        if not casados:
            situacao = "sem trecho na aba Obras Lineares" + (" (tubulação aérea)" if "AEREA" in norm(it["obs"]) else "")
        elif it["comp_m"] is None:
            situacao = "item sem comprimento no CUSTO CIVIL"
        else:
            situacao = "bate" if abs(soma - it["comp_m"]) < 0.01 else f"difere ({it['comp_m']:g} × {soma:g} m)"
        linhas.append({"item": it["item"], "descricao": it["descricao"], "custo_civil_m": it["comp_m"],
                       "obras_lineares_m": soma if casados else None, "trechos": " + ".join(
                           f"L{t['linha']} DN{t['dn_mm']:g}" for t in casados), "prancha": it["prancha"] or "",
                       "situacao": situacao})
    return linhas


# --------------------------------------------------------------------------------------------------------------------
# Saída
# --------------------------------------------------------------------------------------------------------------------

def quadro(qs: list[dict]) -> pd.DataFrame:
    """Uma linha por trecho: entrada, seção, quantidades, geotecnia, conferência com a planilha e alertas."""
    linhas = []
    for q in qs:
        g = q["geotecnia"]
        linhas.append({
            "linha": q.get("linha"), "local": q["local"], "dn_mm": q["dn_mm"], "material": q["material"],
            "metodo": q["metodo"], "comp_m": q["comp_m"], "prof_m": q.get("prof_m"),
            "escoramento": "sim" if q["escorado"] else "não", "largura_m": q.get("largura_m"),
            **{k: q.get(k) for k in ("area_m2", "escavacao_m3", "reaterro_m3", "bota_fora_m3", "escoramento_m2",
                                     "supressao_m2", "caximbos")},
            **{f"pav_{p}_m2": (q.get("pavimento_m2") or {}).get(p, 0.0) for p in PAVIMENTOS},
            "solos": "; ".join(f"{k} {v:.0%}" for k, v in g["solos"].items()) or (q.get("solo") or ""),
            "na_m": g["na_min_m"], "esgotamento_frac": g["esgotamento_frac"],
            "confere_planilha": "; ".join(conferir(q)) if "planilha" in q else "",
            "alertas": "; ".join(q["alertas"])})
    return pd.DataFrame(linhas)


def para_html(qs: list[dict], conc: list[dict], c: dict) -> dict:
    """Pacote da aba Projeto: quadro por trecho, conciliação com o CUSTO CIVIL, premissas e orientações de MND."""
    df = quadro(qs)
    return {"trechos": df.astype(object).where(df.notna(), None).to_dict("records"), "conciliacao": conc,
            "unidade": c.get("unidade", ""), "fonte": c.get("fonte") or REGRAS["metadata"]["fonte"],
            "premissas": REGRAS["metadata"]["observacoes"], "mnd": REGRAS["mnd"]["orientacoes"]}


def etapa(cfg: dict, furos: list[dict], out: Path, log=print) -> dict | None:
    """Etapa da obra (`obras_lineares` no obra.json): lê a planilha, aplica o método escolhido pelo usuário em cada
    trecho (`metodo`: {local: 'MND'}), cruza com as sondagens da obra e grava os CSVs em `out`."""
    c = cfg.get("obras_lineares")
    if not c or not Path(c["planilha"]).exists():
        if c:
            log(f"Obras lineares: planilha {c['planilha']} não está no disco")
        return None
    escolha = {norm(k): v for k, v in (c.get("metodo") or {}).items()}
    trechos = [{**t, "metodo": escolha.get(norm(t["local"]), t["metodo"])}
               for t in ler_obras_lineares(c["planilha"], c.get("aba", "Obras Lineares"))]
    qs = [quantificar(t, furos) for t in trechos]
    conc = conciliar(trechos, ler_custo_civil(c["planilha"], c.get("aba_custo", "CUSTO CIVIL"), c.get("unidade", "UNIDADE 1")))
    for nome, df in (("obras_lineares.csv", quadro(qs)), ("obras_lineares_conciliacao.csv", pd.DataFrame(conc))):
        df.to_csv(Path(out) / nome, sep=";", decimal=",", index=False, encoding="utf-8-sig")
    log(f"Obras lineares: {len(qs)} trechos, {sum(t['comp_m'] for t in trechos):.1f} m; "
        f"{sum(bool(q['alertas']) for q in qs)} com alerta; conciliação: "
        + ", ".join(f"{l['item']} {l['situacao']}" for l in conc))
    return para_html(qs, conc, c)


def ler_furos(caminho) -> list[dict]:
    """Sondagens no formato do obra.json (lista ou {'furos': [...]}), com id, E, N, na_m e camadas."""
    if not caminho:
        return []
    furos = json.loads(Path(caminho).read_text(encoding="utf-8"))
    return furos.get("furos", []) if isinstance(furos, dict) else furos


def principal(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("planilha")
    ap.add_argument("--sondagens", help="JSON das sondagens (formato do obra.json)")
    ap.add_argument("--saida", default=".")
    a = ap.parse_args(argv)
    saida = Path(a.saida)
    saida.mkdir(parents=True, exist_ok=True)
    furos = ler_furos(a.sondagens)
    trechos = ler_obras_lineares(a.planilha)
    qs = quadro([quantificar(t, furos) for t in trechos])
    conc = pd.DataFrame(conciliar(trechos, ler_custo_civil(a.planilha)))
    for nome, df in (("obras_lineares.csv", qs), ("obras_lineares_conciliacao.csv", conc)):
        df.to_csv(saida / nome, sep=";", decimal=",", index=False, encoding="utf-8-sig")
    print(qs[["local", "dn_mm", "prof_m", "escoramento", "largura_m", "escavacao_m3", "confere_planilha", "alertas"]]
          .to_string(index=False))
    print()
    print(conc[["item", "custo_civil_m", "obras_lineares_m", "situacao"]].to_string(index=False))


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "obras_lineares",
        "descricao": "seção de vala pelo MOS Sanepar, escoramento, solo e NA pela sondagem, pavimento pela ortofoto e "
                     "quantidades VCA/MND por trecho; conferência com a planilha e conciliação com o CUSTO CIVIL",
        "funcoes": ["sobrelargura", "escorar", "largura", "classe_solo", "solo_na_vala", "furos_com_xy", "furo_por_metro", "cobertura",
                    "geotecnia", "brilho", "pavimentos_ortofoto", "no_eixo", "vca", "mnd", "quantificar", "ler_obras_lineares",
                    "ler_custo_civil", "conferir", "casar", "conciliar", "quadro", "para_html", "etapa", "id_furo"],
        "bibliografia": [
            {"obra": "Sanepar — Manual de Obras de Saneamento (MOS): largura de vala e Tabela I de sobrelargura",
             "editora": "Sanepar", "aplicacao": {"largura": ["L = D + SL + X + Y"], "sobrelargura": ["Tabela I"]}},
            {"obra": "NR-18 — Condições de segurança e saúde no trabalho na indústria da construção",
             "editora": "MTE", "aplicacao": {"escorar": ["profundidade > 1,25 m"]}},
            {"obra": "ABNT NBR 6484 — Sondagem de simples reconhecimento com SPT", "ano": 2020, "editora": "ABNT",
             "aplicacao": {"classe_solo": ["descrição da camada"]}},
        ],
        "premissas": [{"aplicacao": {k: [k]}, "fonte": v["fonte"], "estado": v["estado"]}
                      for k, v in REGRAS.items() if isinstance(v, dict) and "fonte" in v],
    }


if __name__ == "__main__":
    principal()
