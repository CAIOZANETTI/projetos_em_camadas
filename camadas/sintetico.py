"""Base sintética de adutora para a bancada de formatos das gavetas (rodada 21, E1).

Gera as seis gavetas de `conceitos/gavetas.json` para uma obra linear de `km` quilômetros: um eixo em UTM com
curvas suaves, um objeto `trecho_tubo` por intervalo de `passo_m` e um `furo_sondagem` a cada `furo_a_cada_m`.
Tudo sai de `numpy.random.default_rng(semente)`: a mesma semente dá sempre a mesma base.

    from camadas import sintetico
    base = sintetico.base_linear(5)      # 250 trechos e 26 furos
"""
from __future__ import annotations

import numpy as np

from . import gavetas

SUBDIVISOES = 4                      # vértices por trecho (a polilinha tem um vértice a cada passo_m / 4)
DNS = [300, 400, 500]
MATERIAIS = ["FD", "PEAD"]
SOLOS = ["argila siltosa", "silte arenoso", "areia fina", "alteração de rocha"]   # do mais raso ao mais fundo
EIXO_ID = "AD-01"
DATUM_V = "ortométrico"


def _eixo(rng, comp_m: float, passo_m: float, origem: tuple) -> tuple[np.ndarray, np.ndarray]:
    """Progressivas e vértices (E, N) do eixo: o rumo varia aos poucos, com curvatura de raio da ordem de 300 m."""
    ds = passo_m / SUBDIVISOES
    n = int(np.ceil(comp_m / ds - 1e-9))
    s = np.minimum(np.arange(n + 1) * ds, comp_m)
    janela = np.ones(40) / 40
    curvatura = np.convolve(rng.normal(size=n), janela, mode="same") * 0.02
    rumo = rng.uniform(0, 2 * np.pi) + np.concatenate([[0.0], np.cumsum(curvatura * np.diff(s))])
    passos = np.diff(s)[:, None] * np.column_stack([np.cos(rumo[:-1]), np.sin(rumo[:-1])])
    xy = np.asarray(origem, float) + np.vstack([[0.0, 0.0], np.cumsum(passos, axis=0)])
    return s, xy


def _por_blocos(rng, prog: np.ndarray, comp_m: float, opcoes: list, bloco_km: tuple = (2.0, 6.0)) -> list:
    """Um valor de `opcoes` por trecho, trocando a cada `bloco_km` (sorteado) quilômetros de eixo."""
    limites = np.cumsum(rng.uniform(*bloco_km, size=int(comp_m / 1000 / bloco_km[0]) + 2) * 1000)
    escolhas = rng.integers(0, len(opcoes), size=len(limites))
    return [opcoes[escolhas[np.searchsorted(limites, p, side="right")]] for p in prog]


def _evidencia(eid: str, classe: str, documento: str, localizador: dict) -> dict:
    return {"evidencia_id": eid, "classe": classe, "documento": documento, "localizador": localizador,
            "metodo": "sintetico", "executor": "código"}


def _geometria(oid: str, tipo: str, coords: list, crs_h: str, extra: dict | None = None) -> dict:
    return {"objeto_id": oid, "tipo": tipo, "coords": coords, "crs_h": crs_h, "datum_v": DATUM_V, **(extra or {})}


def _fato(oid: str, propriedade: str, valor, natureza: str) -> dict:
    return {"fato_id": f"{oid}.{propriedade}", "objeto_id": oid, "propriedade": propriedade, "valor": valor,
            "natureza": natureza, "evidencia_id": f"EV-{oid}"}


def _gavetas_vazias() -> dict:
    return {g: [] for g in ("objetos", "geometria", "fatos", "evidencias")}


def _trechos(rng, s: np.ndarray, xy: np.ndarray, crs_h: str) -> dict:
    """Objetos, geometria, fatos (projetado) e evidências dos trechos de tubo."""
    sub, comp = SUBDIVISOES, float(s[-1])
    n = int(np.ceil((len(s) - 1) / sub))
    ini = np.array([s[i * sub] for i in range(n)])
    dn = _por_blocos(rng, ini, comp, DNS)
    material = _por_blocos(rng, ini, comp, MATERIAIS, (5.0, 15.0))
    prof, asfalto, supressao = rng.uniform(1.0, 3.5, n), rng.uniform(0, 1, n), rng.uniform(0, 1, n)
    saida = _gavetas_vazias()
    for i in range(n):
        oid, a, b = f"T{i + 1:05d}", i * sub, min((i + 1) * sub, len(s) - 1)
        c = round(float(s[b] - s[a]), 3)
        asf = round(c * float(asfalto[i]), 3)
        props = {"dn_mm": int(dn[i]), "material": material[i], "prof_m": round(float(prof[i]), 2), "comp_m": c,
                 "pavimentos": {"asfalto": asf, "grama": round(c - asf, 3)},
                 "supressao_frac": round(float(supressao[i]), 2)}
        saida["objetos"].append({"objeto_id": oid, "classe": "trecho_tubo"})
        saida["geometria"].append(_geometria(
            oid, "linha", np.round(xy[a:b + 1], 3).tolist(), crs_h,
            {"eixo_id": EIXO_ID, "prog_ini_m": round(float(s[a]), 3), "prog_fim_m": round(float(s[b]), 3)}))
        saida["fatos"] += [_fato(oid, p, v, "projetado") for p, v in props.items()]
        saida["evidencias"].append(_evidencia(f"EV-{oid}", "planilha", "sintetico.xlsx",
                                              {"aba": "Obras Lineares", "linha": i + 1}))
    return saida


def _camadas(rng) -> list[dict]:
    """De 2 a 4 camadas contíguas desde 0 m, em ordem de profundidade."""
    n = int(rng.integers(2, 5))
    nomes = [SOLOS[k] for k in sorted(rng.choice(len(SOLOS), size=n, replace=False))]
    fundos = np.cumsum(rng.uniform(1.0, 4.0, n))
    de = np.concatenate([[0.0], fundos[:-1]])
    return [{"de": round(float(d), 2), "ate": round(float(a), 2), "descricao": nm}
            for d, a, nm in zip(de, fundos, nomes)]


def _posicoes_furos(rng, s: np.ndarray, xy: np.ndarray, furo_a_cada_m: float) -> np.ndarray:
    """Posição (E, N) de cada furo: na progressiva, 3 a 15 m para um dos lados do eixo."""
    comp = float(s[-1])
    n = int(np.floor(comp / furo_a_cada_m + 1e-9)) + 1
    prog = np.minimum(np.arange(n) * furo_a_cada_m, comp)

    def no_eixo(p):
        return np.column_stack([np.interp(p, s, xy[:, 0]), np.interp(p, s, xy[:, 1])])

    tang = no_eixo(np.minimum(prog + 1, comp)) - no_eixo(np.maximum(prog - 1, 0))
    tang /= np.maximum(np.linalg.norm(tang, axis=1), 1e-9)[:, None]
    desloc = rng.uniform(3, 15, n) * rng.choice([-1.0, 1.0], n)
    return no_eixo(prog) + np.column_stack([-tang[:, 1], tang[:, 0]]) * desloc[:, None]


def _furos(rng, s: np.ndarray, xy: np.ndarray, furo_a_cada_m: float, crs_h: str) -> dict:
    """Furos de sondagem (geometria de ponto, fatos observados, evidência de laudo)."""
    pos = _posicoes_furos(rng, s, xy, furo_a_cada_m)
    cota = 750 + np.cumsum(rng.normal(0, 1.5, len(pos)))
    saida = _gavetas_vazias()
    for i in range(len(pos)):
        oid = f"SP-{i + 1:03d}"
        props = {"na_m": round(float(rng.uniform(0.5, 6.0)), 2), "camadas": _camadas(rng),
                 "cota_boca_m": round(float(cota[i]), 2)}
        saida["objetos"].append({"objeto_id": oid, "classe": "furo_sondagem"})
        saida["geometria"].append(_geometria(oid, "ponto", np.round(pos[i], 3).tolist(), crs_h))
        saida["fatos"] += [_fato(oid, p, v, "observado") for p, v in props.items()]
        saida["evidencias"].append(_evidencia(f"EV-{oid}", "laudo", "sintetico_sondagens.pdf", {"pagina": i + 1}))
    return saida


def base_linear(km: float, passo_m: float = 20.0, furo_a_cada_m: float = 200.0, semente: int = 0,
                origem: tuple = (500000.0, 7200000.0), crs_h: str = "EPSG:31982") -> dict:
    """Base de adutora sintética com as seis gavetas: trechos de `passo_m` e furos de sondagem ao longo do eixo."""
    rng = np.random.default_rng(semente)
    s, xy = _eixo(rng, km * 1000.0, passo_m, origem)
    trechos = _trechos(rng, s, xy, crs_h)
    furos = _furos(rng, s, xy, furo_a_cada_m, crs_h)
    base = {g: trechos[g] + furos[g] for g in trechos}
    vazias = {g: [] for g in gavetas.GAVETAS if g not in base}     # todas as gavetas do contrato, mesmo vazias
    return {**base, **vazias}


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "sintetico",
        "descricao": "base sintética de adutora (eixo em UTM, trechos e furos) para a bancada de formatos das gavetas",
        "funcoes": ["base_linear"],
        "eixo": {"id": EIXO_ID, "vertices_por_trecho": SUBDIVISOES, "curvatura": "ruído suavizado, raio da ordem de 300 m"},
        "dn_mm": DNS, "materiais": MATERIAIS, "solos": SOLOS,
        "gerador": "numpy.random.default_rng(semente)",
        "estado": "premissa",
    }
