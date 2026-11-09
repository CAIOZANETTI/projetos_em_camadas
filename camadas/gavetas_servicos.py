"""Serviços complementares pelas gavetas (F4 da reconstrução, docs/RECONSTRUCAO.md §0 passo 7, §3 F4).

O que a execução do elemento exige e o escopo não traz (forma, armadura, lastro, arrasamento, cava do bloco, vala do
rede com escoramento, berço, reaterro, rebaixamento, bota-fora…) sai das regras de
`conceitos/servicos_associados.jsonl`, que já existiam. Aqui elas passam a ler **só** os fatos e a geometria das gavetas
e a gravar nas gavetas:

    gavetas (objetos + fatos + geometria) ─ elementos ─► dimensões (camadas.dimensoes) ─► regras (camadas.associados)
        ─► servicos (codigo_eap = U.SISTEMA.DISC.PAC.ITEM, fatos usados) + evidencias (classe "associado") + pendencias

A vala vem só da rede (`rede_vala`, regra `vala_rede`; decisão 5 de docs/RECONSTRUCAO.md §5): um elemento por (classe de
superfície, furo mais próximo). Demolição, recomposição e escavação da vala já são da `vala_rede` e não são geradas aqui.

Dimensão que falta não é suposta: o serviço sai sem valor e a pendência diz o que faltou (cadeia `V ← h ← face`). Sem
preço e sem prazo. O resultado entra nas folhas da EAP única por `camadas.eap_preencher` (situação `calculada`).

    python -m camadas.gavetas_servicos saida/foz

Só lê a base; não grava em `saida/`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import shapely
from shapely import geometry as sg

from . import associados, dimensoes, eap, gavetas, gavetas_construtivos, geotecnia
from .eap_preencher import _pasta_da_base, _unidade_e_sistema
from .formulas import nomes, premissa

TOLERANCIA = 1e-3
"""Tolerância absoluta da paridade com o `associados.csv` (unidade da própria quantidade)."""
PROPRIEDADE_GEOMETRICA = {
    "area": "area_planta_m2",
    "perimetro": "perimetro_m",
    "comprimento": "comprimento_m",
}
"""Medida geométrica de `dimensoes.json` → propriedade que a extração grava como fato (`gavetas_construtivos._medidas`)."""
CLASSE_PARA_TIPO = dimensoes.REGRAS["construtivos"]
"""Classe do objeto da gaveta → tipo de `dimensoes.json` (estaca, bloco, pilar). O `trecho` também consta, como vala, mas
não gera elemento: a vala vem da rede (`CLASSE_DA_REDE`)."""
CLASSE_DO_FURO = "furo_sondagem"
CLASSE_DA_REDE = "rede_vala"
FATOS_DA_REDE = ("de_mm", "classes_por_metro", "pesos_m", "extensao_m", "local")
"""Fatos da `rede_vala` de que o elemento de vala depende (o rastro dos serviços)."""
TOLERANCIA_EIXO = 0.01
"""Tolerância relativa entre o comprimento do eixo da rede e a soma de `pesos_m` para posicionar as amostras (1 %)."""
MOTIVO_SEM_REDE = "sem rede de vala (vala_rede): a vala não sai"
SERVICOS_DA_VALA_REDE = frozenset(
    servico
    for saida in gavetas.SERVICOS["regras"]["vala_rede"]["saidas"]
    for servico in (gavetas.EAP["saidas"][saida].get("codigo_eap") or {}).get(
        "servicos", []
    )
)
"""Serviços da EAP que a regra `vala_rede` já calcula (demolição, recomposição e escavação da vala), lidos do de-para."""
REGRAS_DE_VALA = frozenset(r["id"] for r in associados.REGRAS if "vala" in r["tipos"])
"""Regras associadas ao elemento de vala (a paridade com o `associados.csv` separa a vala do resto)."""
REGRAS_JA_DA_VALA_REDE = frozenset(
    r["id"]
    for r in associados.REGRAS
    if r["id"] in REGRAS_DE_VALA and r["destino"]["servico"] in SERVICOS_DA_VALA_REDE
)
"""Regras da vala que repetiriam o que a `vala_rede` dá (mesmo serviço da EAP): nem são aplicadas aos elementos."""


def _mapa_de_dimensoes() -> dict[str, dict[str, tuple[str, float]]]:
    """{tipo: {dimensão: (propriedade da gaveta, fator da propriedade para a dimensão)}}.

    Sai de `dimensoes.json` com os rótulos de `gavetas_construtivos.ROTULOS`, para as duas tabelas não divergirem: a
    dimensão que vem de um atributo passa pelo rótulo (o valor da gaveta já está na unidade da propriedade, e a escala
    da dimensão volta para a unidade dela); a que vem da geometria usa a medida gravada como fato. Dimensão cujo
    atributo não tem rótulo (o lado do pilar) fica de fora e entra em `faltando`, nunca como zero."""
    mapa: dict[str, dict[str, tuple[str, float]]] = {}
    for tipo, spec in dimensoes.TIPOS.items():
        mapa[tipo] = {}
        for nome, origem in spec["dimensoes"].items():
            rotulo = gavetas_construtivos.ROTULOS.get(origem.get("atributo"))
            if rotulo:
                propriedade, fator, _ = rotulo
                mapa[tipo][nome] = (propriedade, origem.get("escala", 1.0) / fator)
            elif origem.get("geometria") in PROPRIEDADE_GEOMETRICA:
                mapa[tipo][nome] = (PROPRIEDADE_GEOMETRICA[origem["geometria"]], 1.0)
    return mapa


MAPA_DE_DIMENSOES = _mapa_de_dimensoes()


def _numero(fato: dict | None) -> bool:
    return (
        fato is not None
        and isinstance(fato["valor"], (int, float))
        and not isinstance(fato["valor"], bool)
    )


def _rastro(
    tipo: str, usados: dict[str, list[str]], pai: dict[str, list[str]] | None = None
) -> dict[str, list[str]]:
    """{dimensão: ids dos fatos de que ela depende}: as dimensões base citam o fato lido (ou o do elemento pai, na
    derivada) e cada cálculo reúne os fatos das dimensões que a fórmula usa. Premissa não tem fato."""
    spec, rastro = dimensoes.TIPOS[tipo], {}
    for nome, origem in spec["dimensoes"].items():
        rastro[nome] = (
            (pai or {}).get(origem["pai"], [])
            if "pai" in origem
            else usados.get(nome, [])
        )
    for nome, expressao in spec["calculos"].items():
        rastro[nome] = sorted({f for n in nomes(expressao) for f in rastro.get(n, [])})
    return rastro


def _com_rastro(
    el: dict, objeto_id: str, rastro: dict, chave: str | None = None
) -> dict:
    return {**el, "objeto_id": objeto_id, "rastro": rastro, "chave": chave}


def _elemento_construtivo(
    objeto: dict, fatos: dict, tipo: str, unidade: str, sistema: str
) -> list[dict]:
    """O elemento (estaca, bloco, pilar) e os derivados (cava do bloco), com as dimensões lidas dos fatos."""
    objeto_id = objeto["objeto_id"]
    dados, usados = {}, {}
    for dimensao, (propriedade, fator) in MAPA_DE_DIMENSOES[tipo].items():
        fato = fatos.get(propriedade)
        if _numero(fato):
            dados[dimensao] = float(fato["valor"]) * fator
            usados[dimensao] = [fato["fato_id"]]
    codigos = eap.codigos_do_elemento(
        {"classe": objeto["classe"], "unidade": unidade, "sistema": sistema}
    )
    el = dimensoes.elemento(
        objeto_id,
        tipo,
        f"{unidade.upper()}.{sistema.split('-', 1)[1]}",
        codigos[0].split(".", 2)[2] if codigos else dimensoes.item_do_tipo(tipo),
        dimensoes.dimensionar(tipo, dados=dados),
        f"gavetas: objeto {objeto_id}",
    )
    rastro = _rastro(tipo, usados)
    derivados = dimensoes._derivados(el)
    return [_com_rastro(el, objeto_id, rastro)] + [
        _com_rastro(d, objeto_id, _rastro(d["tipo"], {}, rastro)) for d in derivados
    ]


def _par_da_unidade(
    objeto: dict, fatos: dict, mapa: dict
) -> tuple[str | None, str | None]:
    """(unidade, sistema `u2-AAT00`) do objeto: pelo registro ou pelos fatos; senão pelo mapa que dá o `codigo_eap` aos
    serviços (`gavetas.unidade_sistema`: setor ou `local`). (None, None) se nenhum resolve."""
    unidade, sistema = _unidade_e_sistema(objeto, fatos)
    if unidade:
        return unidade, sistema
    achado = mapa.get(objeto["objeto_id"])
    if not achado:
        return None, None
    unidade, sistema = achado
    return unidade, sistema if "-" in sistema else f"{unidade}-{sistema}"


def _amostras_da_rede(fatos: dict, xy: np.ndarray | None) -> tuple:
    """(classes, pesos_m, pontos_m, bloqueios, avisos) das amostras da rede: uma classe e os metros de cada amostra, e o
    ponto de cada uma quando o eixo (`xy`, E/N) tem um vértice por amostra (é assim que a extração o grava: o eixo da
    rede são os pontos das amostras); senão `pontos_m` é None. Amostra de classe fora de `conceitos/valas.json` ou sem
    peso sai da conta com aviso; sem diâmetro ou sem amostra, bloqueio."""
    classes, pesos = (
        fatos.get(p, {}).get("valor") for p in ("classes_por_metro", "pesos_m")
    )
    bloqueios = (
        [] if _numero(fatos.get("de_mm")) else ["sem diâmetro (de_mm): a vala não sai"]
    )
    if not (
        isinstance(classes, list)
        and isinstance(pesos, list)
        and classes
        and len(classes) == len(pesos)
    ):
        bloqueios.append(
            "sem classes por metro e pesos (classes_por_metro, pesos_m) de mesmo tamanho: a vala não sai"
        )
        return None, None, None, bloqueios, []
    classes = np.asarray(classes, dtype=str)
    pesos_m = np.array(
        [p if isinstance(p, (int, float)) else np.nan for p in pesos], dtype=float
    )
    vale = (
        np.isfinite(pesos_m)
        & (pesos_m > 0)
        & np.isin(classes, list(dimensoes.VALAS["classes"]))
    )
    avisos = (
        []
        if vale.all()
        else [
            f"{int((~vale).sum())} amostra(s) sem peso ou de classe fora de valas.json ficam fora da vala"
        ]
    )
    if not vale.any():
        bloqueios.append("nenhuma amostra com classe e peso válidos: a vala não sai")
    pontos_m = xy[vale] if xy is not None and len(xy) == len(vale) else None
    return classes[vale], pesos_m[vale], pontos_m, bloqueios, avisos


def _grupo(classe: str, geometria, furo: dict | None, metros_m: float) -> dict:
    return {
        "classe": classe,
        "metros": round(float(metros_m), 3),
        "geometria": geometria,
        "furo": furo,
    }


def _pedacos_nos_pontos(
    pontos_m: np.ndarray, pesos_m: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(meios, pedaços (n, 2, 2)): a amostra i é o próprio ponto; o pedaço é o trecho de `peso_i` metros centrado nele,
    na direção do eixo ali (diferença central dos pontos vizinhos; sem vizinho distinto, a direção E)."""
    if len(pontos_m) > 1:
        tangente = np.gradient(pontos_m, axis=0)
    else:
        tangente = np.zeros_like(pontos_m)
    norma = np.linalg.norm(tangente, axis=1, keepdims=True)
    unitaria = np.where(
        norma > 0, tangente / np.where(norma > 0, norma, 1.0), [1.0, 0.0]
    )
    meio = (unitaria * pesos_m[:, None] / 2)[:, None, :]
    return pontos_m, pontos_m[:, None, :] + np.concatenate([-meio, meio], axis=1)


def _pedacos_no_eixo(
    xy: np.ndarray, pesos_m: np.ndarray, acumulado_m: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """(meios, pedaços (n, 2, 2)) pela posição ao longo do eixo: a amostra i fica no trecho entre `soma(pesos[:i])` e
    `soma(pesos[:i+1])` metros do início (escalado ao comprimento do eixo)."""
    limites_m = np.concatenate([[0.0], np.cumsum(pesos_m)]) * (
        acumulado_m[-1] / pesos_m.sum()
    )

    def ponto(s_m: np.ndarray) -> np.ndarray:
        return np.column_stack(
            [
                np.interp(s_m, acumulado_m, xy[:, 0]),
                np.interp(s_m, acumulado_m, xy[:, 1]),
            ]
        )

    inicio, fim = ponto(limites_m[:-1]), ponto(limites_m[1:])
    return (inicio + fim) / 2, np.stack([inicio, fim], axis=1)


def _grupos_da_rede(
    classes: np.ndarray,
    pesos_m: np.ndarray,
    pontos_m: np.ndarray | None,
    xy: np.ndarray,
    furos: list[dict],
) -> tuple[list[dict], list[str]]:
    """([{classe, metros, geometria, furo}], avisos): as amostras agrupadas por (classe, furo mais próximo).

    A posição de cada amostra, em ordem de confiança: (1) o vértice do eixo, quando há um por amostra (`pontos_m`);
    (2) o ponto a `soma(pesos[:i]) + peso_i/2` metros ao longo do eixo, se o comprimento do eixo confere com a soma dos
    pesos dentro de `TOLERANCIA_EIXO`; (3) nenhuma: um grupo por classe, com o furo mais próximo do eixo inteiro e um
    aviso. O furo de cada amostra é o mais próximo (regra única `geotecnia.furo_mais_proximo`) dentro do raio de
    influência; fora dele o grupo fica sem furo (`furo` None) e o dimensionador avisa."""
    acumulado_m = np.concatenate(
        [[0.0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
    )
    total_m, eixo_m = float(pesos_m.sum()), float(acumulado_m[-1])
    if pontos_m is not None:
        meios, pedacos = _pedacos_nos_pontos(pontos_m, pesos_m)
    elif abs(eixo_m - total_m) <= TOLERANCIA_EIXO * total_m:
        meios, pedacos = _pedacos_no_eixo(xy, pesos_m, acumulado_m)
    else:
        eixo = sg.LineString(xy)
        furo, _ = dimensoes.sondagem_proxima(eixo, furos)
        aviso = (
            f"eixo de {eixo_m:.1f} m não confere com a soma dos pesos ({total_m:.1f} m) a {TOLERANCIA_EIXO:.0%} e não "
            "tem um vértice por amostra: a posição das amostras não se conhece; sondagem única, a mais próxima do eixo"
        )
        return [
            _grupo(c, eixo, furo, pesos_m[classes == c].sum())
            for c in dict.fromkeys(classes.tolist())
        ], [aviso]
    indices, distancias_m = geotecnia.furo_mais_proximo(meios, furos)
    indices = np.where(distancias_m <= geotecnia.RAIO_INFLUENCIA_M, indices, -1)
    grupos = []
    for classe, indice in sorted(
        set(zip(classes.tolist(), indices.tolist(), strict=True))
    ):
        sel = (classes == classe) & (indices == indice)
        geometria = shapely.line_merge(
            shapely.multilinestrings(shapely.linestrings(pedacos[sel]))
        )
        grupos.append(
            _grupo(
                classe,
                geometria,
                furos[indice] if indice >= 0 else None,
                pesos_m[sel].sum(),
            )
        )
    return grupos, []


def _texto(fato: dict | None) -> bool:
    return fato is not None and bool(str(fato["valor"] or "").strip())


def _material_da_rede(rede: dict, trechos: list[dict]) -> tuple[dict | None, list[str]]:
    """(fato `material`, avisos) da rede: o dela, se tiver; senão o dos trechos do mesmo (unidade, sistema), preferindo
    os de mesmo diâmetro, e dentre eles o material de maior extensão. None sem nenhum: a largura da vala (MOS) não sai."""
    if _texto(rede["fatos"].get("material")):
        return rede["fatos"]["material"], []
    do_sistema = [
        t
        for t in trechos
        if (t["unidade"], t["sistema"]) == (rede["unidade"], rede["sistema"])
        and _texto(t["fatos"].get("material"))
    ]
    de_mm = rede["fatos"]["de_mm"]["valor"]
    candidatos = [
        t for t in do_sistema if t["fatos"].get("dn_mm", {}).get("valor") == de_mm
    ] or do_sistema
    if not candidatos:
        return None, [
            f"sem material do tubo: nem a rede nem os trechos de {rede['sistema']} o trazem"
        ]
    extensao_m: dict[str, float] = {}
    fato_de: dict[str, dict] = {}
    for t in candidatos:
        fato = t["fatos"]["material"]
        texto = str(fato["valor"])
        fato_de.setdefault(texto, fato)
        extensao_m[texto] = extensao_m.get(texto, 0.0) + float(
            t["fatos"].get("extensao_m", {}).get("valor") or 0.0
        )
    escolhido = max(extensao_m, key=extensao_m.get)
    avisos = (
        [
            f"{len(extensao_m)} materiais no sistema {rede['sistema']}: tomado o de maior extensão"
        ]
        if len(extensao_m) > 1
        else []
    )
    return fato_de[escolhido], avisos


def _elementos_do_grupo(
    g: dict,
    rede: dict,
    material_texto: str,
    usados_da_rede: list[str],
    furos: list[dict],
) -> list[dict]:
    """Os elementos de vala de um grupo (classe, furo): o dimensionador único recebe só o furo do grupo (ou, sem furo no
    raio, todos, para o alerta dizer a distância) e a geometria só dos metros do grupo."""
    objeto_id, base = (
        rede["objeto"]["objeto_id"],
        f"{rede['unidade'].upper()}.{rede['sistema'].split('-', 1)[1]}",
    )
    trecho = {
        "id": objeto_id,
        "de_mm": float(rede["fatos"]["de_mm"]["valor"]),
        "segmentos": {g["classe"]: g["metros"]},
        "material_texto": material_texto,
        "geometria": g["geometria"],
    }
    usados = sorted({*usados_da_rede, *(g["furo"]["fatos"] if g["furo"] else [])})
    rotulo = g["furo"]["id"] if g["furo"] else "sem furo"
    elementos = []
    for superficie, metodo, dims, alertas in dimensoes.dimensionar_vala(
        trecho, [g["furo"]] if g["furo"] else furos
    ):
        el = dimensoes.elemento(
            f"{objeto_id} · {superficie} · {rotulo} · {metodo}",
            "vala",
            base,
            None,
            dims,
            f"gavetas: objeto {objeto_id}",
            alertas,
            metodo,
        )
        rastro = {
            n: usados for n in (*el["dims"], *dimensoes.TIPOS["vala"]["calculos"])
        }
        elementos.append(_com_rastro(el, objeto_id, rastro, superficie))
    return elementos


def _elementos_da_rede(
    rede: dict, trechos: list[dict], furos: list[dict]
) -> tuple[list[dict], list[tuple[str, str | None]]]:
    """Um elemento de vala por (classe de superfície, furo) da rede `rede_vala` (`RV-<id>`), pelo dimensionador único
    (`dimensoes.dimensionar_vala`), com o rastro dos fatos da rede, do material (do trecho de onde veio) e do furo.
    Devolve também (motivo, detalhe) do que faltou ou foi avisado."""
    fatos, geometria = rede["fatos"], rede["geometria"]
    com_eixo = (
        geometria is not None
        and geometria["tipo"] == "linha"
        and len(geometria["coords"]) >= 2
    )
    xy = np.asarray(geometria["coords"], dtype=float)[:, :2] if com_eixo else None
    classes, pesos_m, pontos_m, bloqueios, avisos = _amostras_da_rede(fatos, xy)
    if not com_eixo:
        bloqueios.append(
            "sem eixo (linha) na geometria: sondagem e superfície não se medem"
        )
    if bloqueios:
        return [], [(m, None) for m in bloqueios]
    material, avisos_material = _material_da_rede(rede, trechos)
    grupos, avisos_grupos = _grupos_da_rede(classes, pesos_m, pontos_m, xy, furos)
    usados_da_rede = [fatos[p]["fato_id"] for p in FATOS_DA_REDE if p in fatos]
    usados_da_rede += [material["fato_id"]] if material else []
    elementos = []
    for g in grupos:
        elementos += _elementos_do_grupo(
            g, rede, str(material["valor"]) if material else "", usados_da_rede, furos
        )
    alertas = sorted({a for e in elementos for a in e["alertas"]})
    todos = [
        *avisos,
        *avisos_material,
        *avisos_grupos,
        *(f"vala: {a}" for a in alertas),
    ]
    return elementos, [(m, None) for m in todos]


def _pendencia(objeto_id: str, motivo: str, detalhe: str | None = None) -> dict:
    return {
        "objeto_id": objeto_id,
        "motivo": motivo,
        **({"detalhe": detalhe} if detalhe else {}),
    }


def _vala_das_redes(
    redes: list[dict], trechos: list[dict], furos: list[dict]
) -> tuple[list[dict], list[dict]]:
    """(elementos, pendências) da vala de todas as redes; o trecho de (unidade, sistema) sem rede vira pendência."""
    elementos, pendencias = [], []
    for rede in redes:
        novos, avisos = _elementos_da_rede(rede, trechos, furos)
        elementos += novos
        pendencias += [_pendencia(rede["objeto"]["objeto_id"], m, d) for m, d in avisos]
    com_rede = {(r["unidade"], r["sistema"]) for r in redes}
    pendencias += [
        _pendencia(t["objeto"]["objeto_id"], MOTIVO_SEM_REDE)
        for t in trechos
        if (t["unidade"], t["sistema"]) not in com_rede
    ]
    return elementos, pendencias


def _registro(
    base: dict, objeto: dict, epsg: int, ind: dict, mapa: dict
) -> tuple[dict | None, dict | None]:
    """(registro, pendência) do objeto: {objeto, fatos, geometria, unidade, sistema}; sem unidade e sistema ou com a
    geometria fora do CRS da obra, só a pendência."""
    objeto_id = objeto["objeto_id"]
    fatos = gavetas.fatos_de_codigo(base, objeto_id, ind)
    unidade, sistema = _par_da_unidade(objeto, fatos, mapa)
    if not unidade:
        return None, _pendencia(
            objeto_id, "unidade e sistema não definidos: sem serviço complementar"
        )
    geometria = ind["geometria"].get(objeto_id)
    if geometria and geometria.get("crs_h") not in (None, f"EPSG:{epsg}"):
        return None, _pendencia(
            objeto_id,
            "geometria fora do CRS da obra: sem serviço complementar",
            f"{geometria.get('crs_h')} no lugar de EPSG:{epsg}",
        )
    return {
        "objeto": objeto,
        "fatos": fatos,
        "geometria": geometria,
        "unidade": unidade,
        "sistema": sistema,
    }, None


def _montar(base: dict, epsg: int) -> tuple[list[dict], list[dict]]:
    """(elementos, pendências) dos objetos que `dimensoes.json` conhece (estaca, bloco, pilar) e das redes de vala.

    A vala vem só dos objetos `rede_vala`; o `trecho` não gera vala: sem rede do mesmo (unidade, sistema) vira
    pendência. A unidade e o sistema da rede saem dos fatos ou, sem eles, do mesmo mecanismo do `codigo_eap`."""
    ind = gavetas.indice(base)
    furos = [
        f
        for f in gavetas.furos(base, CLASSE_DO_FURO, ind)
        if f["E"] is not None and f["N"] is not None
    ]
    mapa, _ = gavetas.unidade_sistema(base, ind, {})
    elementos, pendencias, redes, trechos = [], [], [], []
    for objeto in base["objetos"]:
        tipo = CLASSE_PARA_TIPO.get(objeto["classe"])
        if tipo is None and objeto["classe"] != CLASSE_DA_REDE:
            continue
        registro, pendencia = _registro(base, objeto, epsg, ind, mapa)
        if pendencia:
            pendencias.append(pendencia)
        elif objeto["classe"] == CLASSE_DA_REDE:
            redes.append(registro)
        elif tipo == "vala":
            trechos.append(registro)
        else:
            elementos += _elemento_construtivo(
                objeto,
                registro["fatos"],
                tipo,
                registro["unidade"],
                registro["sistema"],
            )
    da_vala, pendencias_da_vala = _vala_das_redes(redes, trechos, furos)
    return elementos + da_vala, pendencias + pendencias_da_vala


def elementos(base: dict, epsg: int) -> list[dict]:
    """Os elementos no formato que `associados.aplicar` espera, montados só dos fatos e da geometria das gavetas.

    Estaca, bloco e pilar pelas dimensões padronizadas de `dimensoes.json` (propriedade da gaveta → dimensão em
    `MAPA_DE_DIMENSOES`) e as derivações (bloco → cava de fundação); rede de vala → um elemento por (classe, furo mais
    próximo), pelo dimensionador único com as sondagens da própria base. Cada elemento traz também `objeto_id` (o objeto da gaveta),
    `rastro` ({dimensão: ids dos fatos}) e `chave` (a superfície da vala). Dimensão sem fato fica em `faltando`."""
    return _montar(base, epsg)[0]


# --------------------------------------------------------------------------------------------------------------------
# regras → serviços, evidências e pendências
# --------------------------------------------------------------------------------------------------------------------


def versao_da_regra(regra: dict) -> str:
    """Hash curto (sha1, 12 hex) do JSON da regra: mudou a fórmula, a premissa ou o destino, mudou a versão."""
    corpo = json.dumps(regra, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(corpo, usedforsecurity=False).hexdigest()[:12]


VERSOES = {r["id"]: versao_da_regra(r) for r in associados.REGRAS}
POR_ID = {r["id"]: r for r in associados.REGRAS}


def _premissas(regra: dict, el: dict) -> list[str]:
    """Premissas citadas no cálculo: as da regra (com estado e fonte) e as das dimensões do elemento."""
    citadas = []
    for nome, p in regra.get("premissas", {}).items():
        valor = premissa(p, el["tipo"])
        citadas.append(
            f"{nome} = {valor} {p.get('unidade', '')}".rstrip()
            + f" ({p.get('estado', 'premissa')}: {p.get('fonte', p.get('ref', ''))})"
        )
    return citadas + [m for m in el["memoria"] if "(premissa:" in m]


def _falta(texto: str) -> str:
    """A cadeia do que faltou de 'elemento (falta V ← h ← face)'."""
    achado = re.search(r"\(falta (.*)\)$", texto)
    return achado.group(1) if achado else texto


def _identificadores(grupos: list[tuple]) -> list[str]:
    """`<objeto_id>.<regra>`; quando o objeto tem mais de um destino na mesma regra (as superfícies da vala, a
    recomposição de pista e de calçada), acrescenta a superfície, o serviço e o item até desfazer a repetição."""
    por_base = Counter(f"{g[0]}.{g[1]}" for g in grupos)
    ids = []
    for objeto_id, regra, chave, codigo, saida in grupos:
        base = f"{objeto_id}.{regra}"
        if por_base[base] > 1:
            base += f".{chave}" if chave else ""
        ids.append(base)
    repetidos = Counter(ids)
    ids = [
        i if repetidos[i] == 1 else f"{i}.{g[4]}"
        for i, g in zip(ids, grupos, strict=True)
    ]
    repetidos = Counter(ids)
    return [
        i if repetidos[i] == 1 else f"{i}.{g[3]}"
        for i, g in zip(ids, grupos, strict=True)
    ]


def _agrupar_servicos(
    elementos_: list[dict], pendencias: list[dict]
) -> dict[tuple, dict]:
    """Aplica as regras a cada elemento e agrupa os serviços por (objeto, regra, superfície, código, saída); o que
    ficou sem valor entra em `pendencias` (alterada no lugar)."""
    grupos: dict[tuple, dict] = {}
    for el in elementos_:
        evs, sem_valor, _ = associados.aplicar([el], ignorar=REGRAS_JA_DA_VALA_REDE)
        for regra, textos in sem_valor.items():
            pendencias += [
                {
                    "objeto_id": el["objeto_id"],
                    "motivo": f"serviço sem valor: {regra}",
                    "detalhe": f"falta {_falta(t)} ({el['id']})",
                }
                for t in textos
            ]
        for ev in evs:
            regra = POR_ID[ev["regra"]]
            chave = (
                el["objeto_id"],
                ev["regra"],
                el["chave"],
                ev["codigo"],
                ev["servico"] or ev["regra"],
            )
            usados = sorted(
                {
                    f
                    for n in nomes(regra["formula"])
                    + nomes(regra.get("condicao") or "1")
                    for f in el["rastro"].get(n, [])
                }
            )
            g = grupos.setdefault(
                chave,
                {
                    "valor": 0.0,
                    "fatos": set(),
                    "trechos": [],
                    "premissas": [],
                    "documento": ev["documento"]["id"],
                    "servico": ev["servico"],
                    "unidade": ev["unidade"],
                },
            )
            g["valor"] += ev["valor"]
            g["fatos"] |= set(usados)
            g["trechos"].append(ev["trecho"])
            g["premissas"] += [
                p for p in _premissas(regra, el) if p not in g["premissas"]
            ]
    return grupos


def _registros_do_grupo(
    sid: str, chave: tuple, g: dict, validos: set, pendencias: list[dict]
) -> tuple[dict, dict]:
    """O serviço e a evidência de um grupo; o código fora da EAP vira pendência (alterada no lugar)."""
    objeto_id, regra_id, superficie, codigo, saida = chave
    evidencia_id = f"EV-AS-{sid}"
    valido = codigo if codigo in validos else None
    if valido is None:
        pendencias.append(
            {
                "objeto_id": objeto_id,
                "motivo": "código fora da EAP instanciada: serviço sem codigo_eap",
                "detalhe": codigo,
            }
        )
    servico = {
        "servico_id": sid,
        "objeto_id": objeto_id,
        "regra": f"associado:{regra_id}",
        "versao_regra": VERSOES[regra_id],
        "saida": saida,
        "valor": round(g["valor"], 6),
        "unidade": g["unidade"],
        "fatos": sorted(g["fatos"]),
        "codigo_eap": valido,
        "servicos_eap": [g["servico"]] if g["servico"] else [],
        **({"chave": superficie} if superficie else {}),
        "evidencia_id": evidencia_id,
    }
    evidencia = {
        "evidencia_id": evidencia_id,
        "classe": "associado",
        "documento": g["documento"],
        "localizador": {"regra": regra_id, "objeto_id": objeto_id},
        "trecho": " | ".join(g["trechos"]),
        "metodo": "camadas.associados",
        "executor": "código",
        "premissas": g["premissas"],
    }
    return servico, evidencia


def complementares(base: dict, epsg: int) -> dict:
    """Aplica as regras de `servicos_associados.jsonl` aos elementos das gavetas.

    Devolve {servicos, evidencias, pendencias, resumo} nos formatos das gavetas (`conceitos/gavetas.json`):
    - `servicos`: `servico_id` = `<objeto_id>.<regra>`, `regra` = `associado:<id>`, `versao_regra` (hash da regra),
      `saida` (o serviço; a regra sem serviço usa o id da regra), `valor`, `unidade`, `fatos` (ids dos fatos de que o
      valor depende), `codigo_eap` (item técnico completo `U.SISTEMA.DISC.PAC.ITEM`; None se o item não existe na EAP
      instanciada), `servicos_eap` ([serviço], para casar com o `aponta.servico` do modelo), `chave` (superfície da
      vala) e `evidencia_id`;
    - `evidencias`: classe `associado`, com a memória de cálculo no `trecho` e as `premissas` citadas;
    - `pendencias`: o que faltou (dimensão que não existe nas gavetas, objeto sem unidade e sistema, código fora da EAP).
    Sem dimensão o serviço não sai (nunca zero inventado). A base devolvida por `com_complementares` passa em
    `gavetas.conferir_base`."""
    elementos_, pendencias = _montar(base, epsg)
    validos = {n["codigo"] for n in eap.estrutura() if n["nivel"] == "item"}
    grupos = _agrupar_servicos(elementos_, pendencias)
    chaves = sorted(grupos)
    servicos, evidencias = [], []
    for sid, chave in zip(_identificadores(chaves), chaves, strict=True):
        servico, evidencia = _registros_do_grupo(
            sid, chave, grupos[chave], validos, pendencias
        )
        servicos.append(servico)
        evidencias.append(evidencia)
    return {
        "servicos": servicos,
        "evidencias": evidencias,
        "pendencias": pendencias,
        "resumo": _resumo(servicos, pendencias),
    }


def _somar(base: dict, c: dict) -> dict:
    """Cópia da base com os servicos, evidencias e pendencias de `c` (resultado de `complementares`) somados."""
    nova = {g: list(base.get(g, [])) for g in gavetas.GAVETAS}
    for gaveta in ("servicos", "evidencias", "pendencias"):
        nova[gaveta] += c[gaveta]
    return nova


def com_complementares(base: dict, epsg: int) -> tuple[dict, list[str]]:
    """(base com os serviços, evidências e pendências somados, erros de `gavetas.conferir_base`). Não altera a original."""
    nova = _somar(base, complementares(base, epsg))
    return nova, gavetas.conferir_base(nova)


def _resumo(servicos: list[dict], pendencias: list[dict]) -> dict:
    return {
        "servicos": len(servicos),
        "por_regra": dict(sorted(Counter(s["regra"] for s in servicos).items())),
        "sem_codigo_eap": sum(s["codigo_eap"] is None for s in servicos),
        "pendencias": len(pendencias),
        "pendencias_por_motivo": dict(
            Counter(p["motivo"] for p in pendencias).most_common()
        ),
    }


# --------------------------------------------------------------------------------------------------------------------
# paridade com o caminho atual (associados.csv)
# --------------------------------------------------------------------------------------------------------------------


def _regra_de_vala(regra: str) -> bool:
    return str(regra).removeprefix("associado:") in REGRAS_DE_VALA


def somas(servicos: list[dict], de_vala: bool | None = None) -> dict[tuple, float]:
    """{(unidade, item, serviço, unidade de medida): soma} dos serviços com `codigo_eap`, como o `associados.csv`.
    `de_vala`: True só os serviços das regras de vala, False só os demais, None todos."""
    saida: dict[tuple, float] = {}
    for s in servicos:
        if not s.get("codigo_eap") or de_vala not in (None, _regra_de_vala(s["regra"])):
            continue
        unidade, _, item = s["codigo_eap"].split(".", 2)
        servico = (s.get("servicos_eap") or [""])[0]
        chave = (unidade, item, servico, s["unidade"])
        saida[chave] = saida.get(chave, 0.0) + float(s["valor"])
    return saida


def ler_associados(caminho, de_vala: bool | None = None) -> dict[tuple, float]:
    """{(unidade, item, serviço, unidade de medida): quantidade} do `associados.csv` (`;`, vírgula decimal, com BOM).
    `de_vala`: True só as linhas de regras de vala (coluna `regras`), False só as demais, None todas."""
    with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo, delimiter=";"))
    saida: dict[tuple, float] = {}
    for r in linhas:
        if de_vala is not None and de_vala != any(
            f"'{i}'" in r["regras"] for i in REGRAS_DE_VALA
        ):
            continue
        chave = (r["unidade"], r["item"], r["servico"], r["unidade_medida"])
        saida[chave] = saida.get(chave, 0.0) + float(r["quantidade"].replace(",", "."))
    return saida


def _diferencas(esperado: dict[tuple, float], obtido: dict[tuple, float]) -> list[str]:
    problemas = []
    for chave in sorted(esperado.keys() | obtido.keys()):
        rotulo = "/".join(chave)
        if chave not in obtido:
            problemas.append(f"{rotulo}: falta nas gavetas (csv {esperado[chave]:.3f})")
        elif chave not in esperado:
            problemas.append(f"{rotulo}: só nas gavetas ({obtido[chave]:.3f})")
        elif abs(obtido[chave] - esperado[chave]) > TOLERANCIA:
            problemas.append(
                f"{rotulo}: gavetas {obtido[chave]:.3f} × csv {esperado[chave]:.3f} "
                f"(diferença {obtido[chave] - esperado[chave]:+.3f})"
            )
    return problemas


def paridade(servicos: list[dict], associados_csv) -> list[str]:
    """Diferenças entre as gavetas e o `associados.csv` do caminho atual nos serviços que não são de vala (estaca, bloco,
    pilar, cava…), somando por (unidade, item, serviço, unidade de medida) com tolerância absoluta `TOLERANCIA`. Vazio =
    paridade. Cada linha do csv tem de sair igual; linha só das gavetas também é diferença. A vala não entra: o csv vem do
    caminho antigo (trecho) e a vala agora sai só da rede; `paridade_da_vala` conta o que mudou."""
    return _diferencas(ler_associados(associados_csv, False), somas(servicos, False))


def paridade_da_vala(servicos: list[dict], associados_csv) -> list[str]:
    """Como `paridade`, só nos serviços de vala: o que mudou da vala do trecho (csv) para a vala da rede (gavetas)."""
    return _diferencas(ler_associados(associados_csv, True), somas(servicos, True))


def _epsg_da_base(base: dict, pasta: Path) -> int:
    """EPSG da obra: `crs.epsg` do `dados.json` ao lado da base; sem ele, o CRS único da geometria dos objetos que viram
    elemento (a base de Foz tem sondagens em outra zona). ValueError se não houver um só."""
    dados = pasta.parent / "dados.json"
    if dados.exists():
        return int(json.loads(dados.read_text(encoding="utf-8"))["crs"]["epsg"])
    classes = {
        o["objeto_id"]
        for o in base["objetos"]
        if o["classe"] in {*CLASSE_PARA_TIPO, CLASSE_DA_REDE}
    }
    crs = {g["crs_h"] for g in base["geometria"] if g["objeto_id"] in classes}
    if len(crs) != 1:
        raise ValueError(
            f"a geometria dos elementos precisa de um CRS só; achei {sorted(crs)}"
        )
    return int(crs.pop().split(":")[1])


def _imprimir_completude(base: dict) -> None:
    """A completude da EAP única com os complementares nas gavetas (folhas por situação, por tipo de obra)."""
    from . import eap_preencher

    for tipo, v in eap_preencher.preencher(base)["completude"].items():
        print(
            f"EAP {tipo}: {v['preenchida']} preenchidas, {v['calculada']} calculadas, {v['declarada']} declaradas, "
            f"{v['a preencher']} a preencher de {v['folhas']} folhas"
        )


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("obra", help="saida/<obra> (ou a pasta base/ com as gavetas)")
    p.add_argument("--associados", help="associados.csv (padrão: o da pasta da obra)")
    a = p.parse_args(argv)
    pasta = _pasta_da_base(a.obra)
    base = gavetas.ler(pasta)
    epsg = _epsg_da_base(base, pasta)
    resultado = complementares(base, epsg)
    nova = _somar(base, resultado)
    erros = gavetas.conferir_base(nova)
    r = resultado["resumo"]
    print(
        f"{r['servicos']} serviços complementares ({r['sem_codigo_eap']} sem codigo_eap), {r['pendencias']} pendências"
    )
    for regra, n in r["por_regra"].items():
        print(f"  {regra:42} {n}")
    for motivo, n in r["pendencias_por_motivo"].items():
        print(f"  pendência ({n}): {motivo}")
    print(f"conferência das gavetas: {len(erros)} erros")
    for e in erros[:20]:
        print("  ERRO", e)
    _imprimir_completude(nova)
    csv_associados = (
        Path(a.associados) if a.associados else pasta.parent / "associados.csv"
    )
    if not csv_associados.exists():
        print(f"sem {csv_associados}: paridade não conferida")
        return 1 if erros else 0
    diferencas = paridade(resultado["servicos"], csv_associados)
    total = len(ler_associados(csv_associados, False))
    so_nas_gavetas = sum("só nas gavetas" in d for d in diferencas)
    batem = total - (len(diferencas) - so_nas_gavetas)
    print(
        f"paridade com {csv_associados.name}: {batem} de {total} linhas batem; {so_nas_gavetas} só nas gavetas"
    )
    for d in diferencas:
        print("  DIFERE", d)
    print(
        f"vala (rede no lugar do trecho): {len(paridade_da_vala(resultado['servicos'], csv_associados))} "
        "serviço(s) mudaram em relação ao csv, por decisão"
    )
    return 1 if diferencas or erros else 0


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "gavetas_servicos",
        "descricao": "serviços complementares (forma, armadura, lastro, arrasamento, cava, vala, demolição, escoramento, "
        "recomposição…) calculados pelas regras de servicos_associados.jsonl só dos fatos e da geometria das gavetas, "
        "gravados em servicos/evidencias/pendencias, com paridade contra o associados.csv",
        "funcoes": [
            "elementos",
            "complementares",
            "com_complementares",
            "paridade",
            "paridade_da_vala",
            "metadados",
        ],
        "conceitos": ["servicos_associados.jsonl", "dimensoes.json", "gavetas.json"],
        "tolerancia_paridade": TOLERANCIA,
        "mapa_de_dimensoes": {t: sorted(m) for t, m in MAPA_DE_DIMENSOES.items() if m},
    }


if __name__ == "__main__":
    raise SystemExit(principal())
