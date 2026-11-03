"""Dimensões dos elementos: o que cada elemento mede e que serve de base de cálculo aos serviços associados.

    elemento construtivo (estaca, bloco, pilar, trecho) ┐
    elemento declarado no obra.json (laje, viga, parede)├─► dimensões padronizadas ─► camadas.associados (regras)
    fato consolidado (laje 120 m², baldrame 80 m)       ┘   V, A_forma, A_fundo, A_escoramento, A_imperm…
                                └─► derivados: bloco → cava de fundação; baldrame → vala corrida; trecho → vala

Cada tipo (conceitos/dimensoes.json) diz de onde vem cada dimensão — valor dado, elemento pai, atributo, geometria em
UTM, padrão ou premissa — e os cálculos até as dimensões padronizadas. O que falta não é suposto: o cálculo que
depende da dimensão não sai e ela fica em `faltando`.

A vala é o único tipo com dimensionamento próprio (`dimensionar_vala`), mas ele é só um adaptador: a regra mora em
`lineares.dimensionar_vala` (profundidade, solo, rocha e NA da sondagem mais próxima pelo modelo geotécnico único,
escoramento, largura pelo MOS, escavação, reaterro, bota-fora e pavimento) e aqui só se converte a saída para as
dimensões que os serviços associados esperam (decisão do Caio 03/11/2026: dimensionador único). Uma grandeza, uma regra.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

from . import geo, geotecnia
from .formulas import avaliar, conferir, premissa
from .pdf_cad import CONCEITOS

REGRAS = json.loads((CONCEITOS / "dimensoes.json").read_text(encoding="utf-8"))
TIPOS, VP = REGRAS["tipos"], REGRAS["vala"]
VALAS = json.loads((CONCEITOS / "valas.json").read_text(encoding="utf-8"))


def item_do_tipo(tipo: str) -> str | None:
    """Item EAP cujo `construtivos` inclui o tipo (laje → CIV.EST.PIS); None se nenhum."""
    from .eap import itens
    return next((c for c, it in itens().items() if tipo in it["construtivos"]), None)


def _geometria(feature: dict, medida: str, epsg: int) -> float:
    g = shapely.transform(shape(feature["geometry"]), lambda xy: np.column_stack(geo.para_utm(xy[:, 0], xy[:, 1], epsg)))
    return float({"area": g.area, "perimetro": g.length, "comprimento": g.length}[medida])


def _origem(spec: dict, nome: str, dados: dict, pai: dict, atributos: dict, feature, epsg):
    """Valor de uma dimensão pela ordem: dado → pai → atributo (× escala) → geometria → padrão; None se não há."""
    if nome in dados:
        return dados[nome]
    if "pai" in spec:
        return pai.get(spec["pai"])
    v = atributos.get(spec.get("atributo"))
    if isinstance(v, (int, float)):
        return float(v) * spec.get("escala", 1.0)
    if "geometria" in spec and feature is not None:
        return _geometria(feature, spec["geometria"], epsg)
    return spec.get("padrao")


def dimensionar(tipo: str, dados: dict | None = None, atributos: dict | None = None, feature: dict | None = None,
                epsg: int | None = None, pai: dict | None = None) -> tuple[dict, list[str], list[str]]:
    """(dimensões, faltando, memória) de um elemento do tipo. Premissa só entra onde a dimensão não veio de outro lugar."""
    spec, dados, atributos, pai = TIPOS[tipo], dict(dados or {}), atributos or {}, pai or {}
    dims, faltando, memoria = {}, [], []
    for nome, s in spec["dimensoes"].items():
        v = _origem(s, nome, dados, pai, atributos, feature, epsg)
        if v is not None:
            dims[nome] = v
    dims.update({k: v for k, v in dados.items() if k not in dims})
    for nome, p in spec["premissas"].items():
        if nome not in dims:
            dims[nome] = premissa(p, tipo)
            memoria.append(f"{nome} = {dims[nome]} (premissa: {p.get('fonte', p.get('ref', ''))})")
    faltando = [n for n in spec["dimensoes"] if n not in dims]
    for nome, expr in spec["calculos"].items():
        if nome in dados:                                 # valor dado (ex.: o volume do dimensionador MOS) vence a conta
            continue
        try:
            dims[nome] = avaliar(expr, dims)
            memoria.append(f"{nome} = {expr} = {dims[nome]:.4g}")
        except KeyError as falta:
            faltando.append(f"{nome} (falta {falta.args[0]})")
    return dims, faltando, memoria


def elemento(ident: str, tipo: str, base: str, item: str | None, dims: tuple, fonte: str, alertas=None,
             metodo: str | None = None) -> dict:
    """Elemento dimensionado; `metodo` = método de cálculo que o gerou (a vala tem um elemento por método)."""
    d, faltando, memoria = dims
    return {"id": ident, "tipo": tipo, "base": base, "item": item, "dims": d, "faltando": faltando, "memoria": memoria,
            "alertas": list(alertas or []), "fonte": fonte, "metodo": metodo}


def _derivados(el: dict) -> list[dict]:
    """Elementos que a execução do elemento exige (cava do bloco, vala do baldrame), com as dimensões do pai."""
    return [elemento(f"{el['id']} · {d}", d, el["base"], None, dimensionar(d, pai=el["dims"]),
                     f"derivado de {el['id']}") for d in TIPOS[el["tipo"]]["derivados"]]


# vala (adaptador do dimensionador único: lineares.dimensionar_vala) --------------------------------------------------
def _faixa(tabela: list, x: float):
    """Valor da primeira faixa [limite, valor] com x ≤ limite."""
    return next(v for lim, v in tabela if x <= lim)


def material_do_tubo(texto: str) -> str | None:
    """'flexivel' (PEAD, PVC…), 'rigido' (FD, concreto…) ou None pelo texto do trecho (contrato, rede)."""
    t = str(texto or "").upper()
    if re.search(VP["tubo"]["flexiveis"]["valor"], t):
        return "flexivel"
    return "rigido" if re.search(VP["tubo"]["rigidos"]["valor"], t) else None


def classe_solo(descricao: str | None, classe: str | None = None) -> str:
    """Classe da camada pela descrição: a regra única do modelo geotécnico (`geotecnia.classe_solo`)."""
    return geotecnia.classe_solo(descricao or "", classe)["classe"]


def sondagem_proxima(geometria, furos: list) -> tuple[dict | None, float | None]:
    """Furo mais próximo do eixo do trecho (UTM) pela regra única (`geotecnia.furo_mais_proximo`, raio de influência de
    `geotecnia.json`): (furo, distância em m) dentro do raio; (None, distância) fora dele; (None, None) sem furo ou eixo."""
    pontos_m = _pontos(geometria)
    if pontos_m is None:
        return None, None
    indices, distancias_m = geotecnia.furo_mais_proximo(pontos_m, furos or [])
    k = int(distancias_m.argmin())
    if indices[k] < 0:
        return None, None
    distancia_m = round(float(distancias_m[k]), 1)
    return (furos[indices[k]], distancia_m) if distancia_m <= geotecnia.RAIO_INFLUENCIA_M else (None, distancia_m)


def _furo_na_cota_do_trecho(furo: dict, cota_terreno_m: float | None) -> dict:
    """Furo com as profundidades referidas ao terreno do trecho (profundidade do furo + cota do trecho − cota da boca);
    igual ao original sem uma das duas cotas. Só troca de referência: quem decide solo, rocha e NA é o lineares."""
    if cota_terreno_m is None or furo.get("cota_boca") is None:
        return furo
    desloc_m = float(cota_terreno_m) - float(furo["cota_boca"])
    if desloc_m == 0:
        return furo
    novo = dict(furo)
    # camada ou leitura sem profundidade numérica fica de fora (o mesmo critério de geotecnia._numero)
    novo["camadas"] = [{**c, "de": max(0.0, c["de"] + desloc_m), "ate": c["ate"] + desloc_m}
                       for c in furo.get("camadas") or []
                       if geotecnia._numero(c.get("de")) and geotecnia._numero(c.get("ate")) and c["ate"] + desloc_m > 0]
    novo["nspt"] = [[prof_m + desloc_m, golpes] for prof_m, golpes in furo.get("nspt") or []
                    if geotecnia._numero(prof_m) and prof_m + desloc_m >= 0]
    for chave in ("na_m", "profundidade_m"):
        if furo.get(chave) is not None:
            novo[chave] = float(furo[chave]) + desloc_m
    return novo


def _constantes_vala() -> dict:
    """O que o lineares não calcula: berço, envoltória, cortes do pavimento, ponteiras e reaproveitamento do solo."""
    reap = VP["volumes"]["reaproveitamento"]["valor"]
    return {"cortes": VP["pavimentos"]["cortes_por_trecho"]["valor"], "berco": VALAS["berco_m"]["valor"],
            "acima": VP["tubo"]["envoltoria_acima_m"]["valor"], "ponteiras_lados": VP["lencol"]["ponteiras_lados"]["valor"],
            "reap_solo": reap["solo"], "reap_mole": reap["mole"]}


def material_mos(texto: str) -> str | None:
    """Material na grafia da Tabela I do MOS ('TUBO PE DE 630' → 'PEAD'); None se não reconhece."""
    from .vocabulario import normalizar
    t = normalizar(texto)
    return next((m for m, rx in VP["metodos"]["mos_sanepar"]["materiais"] if re.search(rx, t)), None)


def _pontos(geometria, passo_m: float = 1.0):
    """Eixo do trecho amostrado a cada metro (UTM), para a sondagem de cada metro no dimensionador."""
    if geometria is None or geometria.length == 0:
        return None
    return np.array([geometria.interpolate(s).coords[0] for s in np.arange(0.0, geometria.length + 1e-9, passo_m)])


def _segmento_vala(sup: str, L: float, d: float, de_mm: float, material_texto: str, furos: list | None, pts,
                   profundidade: float | None) -> tuple[dict | None, list]:
    """Adaptador: dimensões de um segmento no formato do tipo `vala`, todas vindas de `lineares.dimensionar_vala`
    (largura, profundidade, escoramento, esgotamento, escavação, reaterro, bota-fora, escoramento em m² e pavimento em
    m²); (None, [motivo]) quando o material do tubo não é reconhecido. Fora da Tabela I do MOS a largura é o fallback
    do `lineares` (DE + 0,60 m, NBR 12266, D7). Daqui saem só o berço e a envoltória (regra genérica, com a
    largura do MOS), as horas de esgotamento e a divisão da escavação em solo e rocha pela fração de rocha do lineares."""
    from . import lineares
    material = material_mos(material_texto)
    if material is None:
        return None, ["MOS: material do tubo não reconhecido na Tabela I"]
    c = _constantes_vala()
    rec = VALAS["recobrimento_m"][VALAS["classes"].get(sup, {}).get("recobrimento", "outros")]
    h = profundidade if profundidade is not None else rec + d + c["berco"]
    pav_mos = VP["metodos"]["mos_sanepar"]["pavimentos"]["valor"].get(sup, "terra")
    trecho = {"local": sup, "dn_mm": de_mm, "de_mm": de_mm, "material": material, "prof_m": h, "comp_m": L,
              "metodo": "VCA", "pavimentos": {pav_mos: L}}
    r = lineares.dimensionar_vala(trecho, furos or [], pts=pts)
    if not r.get("largura_m"):
        return None, [f"MOS: {material} DN {de_mm:g} fora da Tabela I"]
    tipo = r.get("tipo_escoramento") or "nenhum"
    pav = VP["pavimentos"]["tipos"][VP["pavimentos"]["superficie_tipo"]["valor"].get(sup, "terra")]
    metodo_agua = r.get("tipo_esgotamento") or "nenhum"
    horas = L / _faixa(VP["lencol"]["produtividade_m_dia"]["valor"], de_mm) * VP["lencol"]["horas_por_dia"]["valor"] \
        if metodo_agua != "nenhum" else 0.0
    b, h = float(r["largura_m"]), float(r["profundidade_m"])
    fracao_rocha = sum(f for classe, f in r["geotecnia"]["solos"].items() if classe.startswith("rocha"))
    v_rocha = float(r["escavacao_m3"]) * fracao_rocha
    dims = {**c, "L": L, "d": d, "h": h, "b": b, "e_pav": sum(e for _, e in pav["camadas"]),
            "h_rocha": h * fracao_rocha, "h_solo": h * (1 - fracao_rocha), "escorado": 0.0 if tipo == "nenhum" else 1.0,
            "tipo_escoramento": tipo, "flexivel": 1.0 if material_do_tubo(material_texto) == "flexivel" else 0.0,
            "item_pavimento": pav["item"] or "", "pavimento": pav["nome"], "h_agua": float(r.get("altura_agua_m") or 0.0),
            "metodo_agua": metodo_agua, "horas_agua": horas, "reap": c["reap_solo"],
            "importado": 1.0 if VP["volumes"]["berco_envoltoria_importado"]["valor"] else 0.0,
            "empolamento_bota": (1 - fracao_rocha) * geotecnia.EMPOLAMENTO_SOLO + fracao_rocha * geotecnia.EMPOLAMENTO_ROCHA,
            "V_solo": float(r["escavacao_m3"]) - v_rocha, "V_rocha": v_rocha, "V_reat_mos": float(r["reaterro_m3"]),
            "V_bota_mos": float(r["bota_fora_m3"]), "A_escoramento": float(r.get("escoramento_m2") or 0.0),
            "A_demol": float(sum((r.get("pavimento_m2") or {}).values())) if pav["item"] else 0.0}
    memoria = [(f"MOS (lineares.dimensionar_vala): h = {h:.2f} m ({r.get('fonte_profundidade')}), "
                f"L = {b:.2f} m ({material} DN {de_mm:g}; fonte: {r.get('fonte_largura')})"),
               f"escoramento {VP['largura']['nomes_escoramento'].get(tipo, tipo)}"
               + (f" ({', '.join(r.get('agravantes_escoramento') or [])})" if r.get("agravantes_escoramento") else ""),
               (f"escavação {r['escavacao_m3']:g} m³ (rocha {fracao_rocha:.0%}) · reaterro do MOS (escavação − tubo) "
                f"{r['reaterro_m3']:g} m³ · "
                f"bota-fora {r['bota_fora_m3']:g} m³ · pavimento {r.get('pavimento_m2')}"),
               f"água: {dims['h_agua']:.2f} m na vala → {metodo_agua}", *r.get("alertas", [])]
    return dims, memoria


def fracao_rocha_de(dims: dict) -> float:
    """Fração de rocha da escavação do segmento (V_rocha ÷ escavação total)."""
    total_m3 = dims["V_solo"] + dims["V_rocha"]
    return dims["V_rocha"] / total_m3 if total_m3 else 0.0


def dimensionar_vala(trecho: dict, sondagens: list | None = None,
                     metodos: list[str] | None = None) -> list[tuple[str, str, tuple, list[str]]]:
    """[(segmento, método, (dimensões, faltando, memória), alertas)] de um trecho: {id, de_mm, segmentos: {superfície:
    m}, material_texto?, geometria (UTM)?, cota_terreno?, profundidade_m?}. Adaptador de `lineares.dimensionar_vala`
    (decisão do Caio 03/11/2026: dimensionador único): o único método é `mos_sanepar`; outro método pedido (ex.:
    'nbr12266') não tem regra própria e fica de fora com alerta. Material não reconhecido sai com a largura em `faltando`; tubo fora da Tabela I do MOS usa o fallback do lineares (D7)."""
    furo, dist = sondagem_proxima(trecho.get("geometria"), sondagens)
    alertas = [] if furo else [f"nenhuma sondagem a até {geotecnia.RAIO_INFLUENCIA_M:.0f} m"
                               + (f" (a mais próxima a {dist:.0f} m)" if dist else "")
                               + ": solo, rocha e NA sem informação; bombeamento não avaliado"]
    if furo and (trecho.get("cota_terreno") is None or furo.get("cota_boca") is None):
        alertas.append(f"terreno do trecho tomado na cota da boca do furo {furo.get('id')} ({dist:.0f} m)")
    if material_do_tubo(trecho.get("material_texto")) is None:
        alertas.append("material do tubo não identificado: sem envoltória (tratado como rígido)")
    furos = [_furo_na_cota_do_trecho(f, trecho.get("cota_terreno")) for f in sondagens or []]
    pts = _pontos(trecho.get("geometria"))
    saida, fora = [], []                                  # fora: método sem regra própria, avisado em todo o trecho
    for metodo in metodos or list(VP["metodos"]):
        if metodo not in VP["metodos"]:
            fora.append(f"método '{metodo}' sem regra própria: a largura sai só do MOS "
                        "(decisão do Caio 03/11/2026: dimensionador único em lineares)")
            continue
        for sup, L in trecho["segmentos"].items():
            dims, memoria = _segmento_vala(sup, L, trecho["de_mm"] / 1000, trecho["de_mm"], trecho.get("material_texto"),
                                           furos, pts, trecho.get("profundidade_m"))
            if dims is None:                              # o que falta não é suposto: só o que não depende da largura sai
                d, faltando, mem = dimensionar("vala", dados={"L": L, "d": trecho["de_mm"] / 1000})
                saida.append((sup, metodo, (d, [f"b (falta {memoria[0]})", *faltando], mem), alertas + [f"{sup}: {memoria[0]}"]))
                continue
            d, faltando, mem = dimensionar("vala", dados=dims)
            if "V_reat" in d:                             # decisão do Caio 03/11/2026 (D8): a conta do reaterro na memória
                liquido_m3 = dims["V_reat_mos"] - d["V_berco"] - d["V_env"]
                mem.append(f"reaterro = {dims['V_reat_mos']:.4g} (MOS: escavação − tubo) − berço {d['V_berco']:.4g} − "
                           f"envoltória {d['V_env']:.4g} = {liquido_m3:.4g} m³ → {d['V_reat']:.4g} m³")
                if liquido_m3 < 0:
                    alertas = [*alertas, f"{sup}: berço + envoltória superam o reaterro do MOS ({liquido_m3:.4g} m³): reaterro 0"]
            if d["importado"]:                            # decisão do Caio 03/11/2026 (D9): o solo que o berço sai também
                # o solo deslocado não passa do que havia para reaterrar (vala rasa: V_reat cortado a 0)
                extra_m3 = min(d["V_berco"] + d["V_env"], dims["V_reat_mos"]) * d["empolamento_bota"]
                mem.append(f"bota-fora = {dims['V_bota_mos']:.4g} (MOS: tubo × empolamento) + (berço {d['V_berco']:.4g} + "
                           f"envoltória {d['V_env']:.4g}) × empolamento {d['empolamento_bota']:.4g} "
                           f"({1 - fracao_rocha_de(dims):.0%} solo × {geotecnia.EMPOLAMENTO_SOLO:g} + "
                           f"{fracao_rocha_de(dims):.0%} rocha × {geotecnia.EMPOLAMENTO_ROCHA:g}) = {extra_m3:.4g} m³ extra "
                           f"→ {d['V_bota']:.4g} m³")
            alerta_agua = [f"{sup}: vala atinge o NA ({dims['h_agua']:.2f} m de água): {dims['metodo_agua']}"] \
                if dims["metodo_agua"] != "nenhum" else []
            saida.append((sup, metodo, (d, faltando, memoria + mem), alertas + alerta_agua))
    return [(sup, metodo, dims, al + list(dict.fromkeys(fora))) for sup, metodo, dims, al in saida]


def trecho_da_feature(feature: dict, epsg: int) -> dict | None:
    """Trecho para a vala a partir de um elemento `trecho` de camadas.construtivos (extensão por superfície pelos
    atributos '<nome da classe de valas> (m)'); None sem diâmetro."""
    atr = dict(feature["properties"]["atributos"])
    if not isinstance(atr.get("Diâmetro (mm)"), (int, float)):
        return None
    segmentos = {c: float(atr[f"{v['nome']} (m)"]) for c, v in VALAS["classes"].items()
                 if isinstance(atr.get(f"{v['nome']} (m)"), (int, float)) and atr[f"{v['nome']} (m)"] > 0}
    total = atr.get("Extensão estimada (m)")
    if isinstance(total, (int, float)) and total - sum(segmentos.values()) > 0.5:
        segmentos["sem_ortofoto"] = round(total - sum(segmentos.values()), 1)
    g = shapely.transform(shape(feature["geometry"]), lambda xy: np.column_stack(geo.para_utm(xy[:, 0], xy[:, 1], epsg)))
    return {"id": feature["properties"]["id"], "de_mm": float(atr["Diâmetro (mm)"]), "segmentos": segmentos,
            "material_texto": " ".join(str(v) for v in atr.values() if isinstance(v, str)), "geometria": g}


# fontes de elementos -----------------------------------------------------------------------------------------------
def de_construtivos(construtivos: dict, epsg: int, sondagens: list | None = None) -> list[dict]:
    """Elementos dimensionados a partir de camadas.construtivos (tipos de `construtivos` no conceito) e os derivados."""
    from .eap import codigos_do_elemento
    saida = []
    for f in construtivos["geojson"]["features"]:
        p = f["properties"]
        tipo = REGRAS["construtivos"].get(p["classe"])
        if tipo is None:
            continue
        base = f"{p['unidade'].upper()}.{p['sistema'].split('-', 1)[1]}"
        if tipo == "vala":
            trecho = trecho_da_feature(f, epsg)
            vals = dimensionar_vala(trecho, sondagens) if trecho else []
            saida += [elemento(f"{p['id']} · {sup} · {metodo}", "vala", base, None, dims, p["fonte"], alertas, metodo)
                      for sup, metodo, dims, alertas in vals]
            continue
        codigos = codigos_do_elemento(p)
        el = elemento(p["id"], tipo, base, codigos[0].split(".", 2)[2] if codigos else item_do_tipo(tipo),
                      dimensionar(tipo, atributos=dict(p["atributos"]), feature=f, epsg=epsg), p["fonte"])
        saida += [el, *_derivados(el)]
    return saida


def de_declarados(declarados: list[dict]) -> list[dict]:
    """Elementos do obra.json (`elementos_declarados`): {id, tipo, unidade, sistema, dimensoes: {…}, fonte}."""
    saida = []
    for d in declarados or []:
        el = elemento(d["id"], d["tipo"], f"{d.get('unidade', '*')}.{d.get('sistema', '*')}", item_do_tipo(d["tipo"]),
                      dimensionar(d["tipo"], dados=d.get("dimensoes", {})), d.get("fonte", "declarado no obra.json"))
        saida += [el, *_derivados(el)]
    return saida


def de_fatos(fatos: pd.DataFrame) -> list[dict]:
    """Elementos a partir de fatos consolidados com valor (convergente, fonte única ou decidido): laje em m², baldrame
    em m. Fato em conflito não vira elemento: primeiro se resolve o conflito."""
    saida = []
    for regra in REGRAS["de_fatos"]:
        for f in fatos.to_dict("records") if len(fatos) else []:
            item = ".".join(f["codigo"].split(".")[2:])
            if (item, f["servico"], f["unidade"]) != (regra["item"], regra["servico"], regra["unidade"]) \
                    or f["status"] not in ("convergente", "fonte única", "decidido"):
                continue
            el = elemento(f"fato {f['codigo']}", regra["tipo"], ".".join(f["codigo"].split(".")[:2]), item,
                          dimensionar(regra["tipo"], dados={regra["dimensao"]: float(f["valor"])}),
                          f"fato {f['codigo']} {f['valor']:g} {f['unidade']} ({f['status']})")
            saida += [el, *_derivados(el)]
    return saida


def tabela(elementos: list[dict]) -> pd.DataFrame:
    """Memória das dimensões: um elemento por linha, com as dimensões numéricas, o que faltou e os alertas."""
    return pd.DataFrame([{"id": e["id"], "tipo": e["tipo"], "base": e["base"], "item": e["item"],
                          "dimensoes": {k: round(v, 4) if isinstance(v, float) else v for k, v in e["dims"].items()},
                          "faltando": e["faltando"], "memoria": e["memoria"], "alertas": e["alertas"], "fonte": e["fonte"]}
                         for e in elementos])


def validar() -> list[str]:
    """Problemas do conceito: tipo derivado ou de construtivo inexistente, fato para tipo inexistente."""
    problemas = [f"{t}: derivado '{d}' inexistente" for t, s in TIPOS.items() for d in s["derivados"] if d not in TIPOS]
    problemas += [f"construtivos: '{c}' → tipo '{t}' inexistente" for c, t in REGRAS["construtivos"].items() if t not in TIPOS]
    problemas += [f"de_fatos: tipo '{r['tipo']}' inexistente" for r in REGRAS["de_fatos"] if r["tipo"] not in TIPOS]
    problemas += [f"{t}.{nome}: {erro}" for t, s in TIPOS.items() for nome, expr in s["calculos"].items()
                  if (erro := conferir(expr))]
    problemas += [f"vala.metodos: '{m}' sem código" for m in VP["metodos"] if m != "mos_sanepar"]
    return problemas
