"""Dimensões dos elementos: o que cada elemento mede e que serve de base de cálculo aos serviços associados.

    elemento construtivo (estaca, bloco, pilar, trecho) ┐
    elemento declarado no obra.json (laje, viga, parede)├─► dimensões padronizadas ─► camadas.associados (regras)
    fato consolidado (laje 120 m², baldrame 80 m)       ┘   V, A_forma, A_fundo, A_escoramento, A_imperm…
                                └─► derivados: bloco → cava de fundação; baldrame → vala corrida; trecho → vala

Cada tipo (conceitos/dimensoes.json) diz de onde vem cada dimensão — valor dado, elemento pai, atributo, geometria em
UTM, padrão ou premissa — e os cálculos até as dimensões padronizadas. O que falta não é suposto: o cálculo que
depende da dimensão não sai e ela fica em `faltando`.

A vala é o único tipo com dimensionamento próprio (`dimensionar_vala`), porque depende de decisões e não só de
contas: profundidade, solo, rocha e NA da sondagem mais próxima, escoramento (NR-18 e agravantes), largura e tipo de
pavimento. A largura sai de cada método de `vala.metodos` (NBR 12266, MOS Sanepar…): um elemento por método, e cada
método é uma fonte de evidência — o código não escolhe, a consolidação mostra convergência ou conflito.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point, shape

from . import geo
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


# vala --------------------------------------------------------------------------------------------------------------
def _faixa(tabela: list, x: float):
    """Valor da primeira faixa [limite, valor] com x ≤ limite."""
    return next(v for lim, v in tabela if x <= lim)


def material_do_tubo(texto: str) -> str | None:
    """'flexivel' (PEAD, PVC…), 'rigido' (FD, concreto…) ou None pelo texto do trecho (contrato, rede)."""
    t = str(texto or "").upper()
    if re.search(VP["tubo"]["flexiveis"]["valor"], t):
        return "flexivel"
    return "rigido" if re.search(VP["tubo"]["rigidos"]["valor"], t) else None


def classe_solo(descricao: str | None, classe: str | None = None) -> str | None:
    """Classe da camada (rocha, areia, argila, silte, aterro) pela palavra principal; a primeira regra que casa vence."""
    from .vocabulario import normalizar
    t = normalizar(f"{classe or ''} {descricao or ''}")
    return next((c for c, rx in VP["solo"]["classes"]["valor"] if re.search(rx, t)), None)


def sondagem_proxima(geometria, furos: list) -> tuple[dict | None, float | None]:
    """Furo com E/N mais próximo da geometria do trecho (UTM) dentro do raio; (None, distância) fora dele."""
    candidatos = [(geometria.distance(Point(f["E"], f["N"])), f) for f in furos or []
                  if geometria is not None and f.get("E") is not None and f.get("N") is not None]
    if not candidatos:
        return None, None
    d, furo = min(candidatos, key=lambda c: c[0])
    return (furo, round(d, 1)) if d <= VP["sondagem"]["raio_m"]["valor"] else (None, round(d, 1))


def solo_na_vala(furo: dict | None, h: float, desloc_m: float = 0.0) -> dict:
    """O que o furo diz da faixa 0–h do trecho (profundidades do furo + desloc = cota do trecho − cota da boca)."""
    if furo is None:
        return {"furo": None, "classes": [], "nao_coesivo": False, "nspt_min": None, "topo_rocha_m": None, "na_m": None}
    camadas = furo.get("camadas") or []
    classes = list(dict.fromkeys(filter(None, (classe_solo(c.get("descricao"), c.get("classe")) for c in camadas
                                               if c.get("de") is None or c["de"] + desloc_m < h))))
    rochas = [c["de"] + desloc_m for c in camadas if c.get("de") is not None
              and classe_solo(c.get("descricao"), c.get("classe")) == "rocha"]
    if furo.get("impenetravel") and furo.get("profundidade_m") and VP["solo"]["impenetravel_e_rocha"]["valor"]:
        rochas.append(float(furo["profundidade_m"]) + desloc_m)
    golpes = [g for prof, g in furo.get("nspt") or [] if prof + desloc_m <= h]
    na = furo.get("na_m")
    return {"furo": furo.get("id"), "classes": classes,
            "nao_coesivo": bool(set(classes) & set(VP["escoramento"]["agravantes"]["solos_nao_coesivos"])),
            "nspt_min": min(golpes) if golpes else None, "topo_rocha_m": round(min(rochas), 2) if rochas else None,
            "na_m": round(na + desloc_m - VP["lencol"]["margem_m"]["valor"], 2) if na is not None else None}


def escoramento(h: float, solo: dict) -> tuple[str, str]:
    """(tipo, motivo) pela profundidade e pelos agravantes do solo e da água."""
    tipo = _faixa(VP["escoramento"]["profundidade_max_m"]["valor"], h)
    ag = VP["escoramento"]["agravantes"]
    if tipo == "nenhum":
        return tipo, f"vala rasa (h = {h:.2f} m ≤ 1,25 m, NR-18)"
    motivos = [m for m, sim in (("solo não coesivo", solo["nao_coesivo"]),
                                (f"NSPT {solo['nspt_min']} < {ag['nspt_min']}", solo["nspt_min"] is not None
                                 and solo["nspt_min"] < ag["nspt_min"]),
                                ("abaixo do NA", solo["na_m"] is not None and solo["na_m"] < h)) if sim]
    ordem = [t for _, t in VP["escoramento"]["profundidade_max_m"]["valor"]]
    if motivos and ordem.index(tipo) < ordem.index(ag["tipo_minimo"]):
        return ag["tipo_minimo"], f"h = {h:.2f} m e " + ", ".join(motivos)
    return tipo, f"h = {h:.2f} m" + (f" ({', '.join(motivos)})" if motivos else "")


def _agua(h: float, solo: dict, L: float, de_mm: float) -> tuple[float, str, float]:
    """(altura de água, método 'nenhum' | 'bomba' | 'ponteiras', horas) pela vala abaixo do NA."""
    hw = max(0.0, h - solo["na_m"]) if solo["na_m"] is not None else 0.0
    if hw <= 0:
        return 0.0, "nenhum", 0.0
    metodo = "ponteiras" if solo["nao_coesivo"] or _faixa(VP["lencol"]["metodo"]["valor"], hw).startswith("rebaix") \
        else "bomba"
    horas = L / _faixa(VP["lencol"]["produtividade_m_dia"]["valor"], de_mm) * VP["lencol"]["horas_por_dia"]["valor"]
    return hw, metodo, horas


def _constantes_vala() -> dict:
    emp, reap = VP["volumes"]["empolamento"]["valor"], VP["volumes"]["reaproveitamento"]["valor"]
    return {"sobre": VALAS["sobrelargura_recorte_m"]["valor"], "cortes": VP["pavimentos"]["cortes_por_trecho"]["valor"],
            "berco": VALAS["berco_m"]["valor"], "acima": VP["tubo"]["envoltoria_acima_m"]["valor"],
            "paredes": VP["escoramento"]["paredes"]["valor"], "ponteiras_lados": VP["lencol"]["ponteiras_lados"]["valor"],
            "emp_solo": emp["solo"], "emp_rocha": emp["rocha"], "emp_pav": emp["pavimento"], "reap_solo": reap["solo"],
            "reap_mole": reap["mole"]}


def _largura_nbr(d: float, de_mm: float, h: float, tipo: str, material_texto: str) -> tuple[float | None, str]:
    """NBR 12266: b = max(DE + folga, mínimo da profundidade) + acréscimo do tipo de escoramento."""
    bmin = _faixa(VP["largura"]["minimo_por_profundidade"]["valor"], h)
    b = max(d + VALAS["largura_vala"]["folga_m"], bmin) + VP["largura"]["acrescimo_escoramento_m"]["valor"][tipo]
    return b, f"b (NBR 12266) = max(DE + folga, b_min {bmin}) + acréscimo do escoramento = {b:.2f} m"


def material_mos(texto: str) -> str | None:
    """Material na grafia da Tabela I do MOS ('TUBO PE DE 630' → 'PEAD'); None se não reconhece."""
    from .vocabulario import normalizar
    t = normalizar(texto)
    return next((m for m, rx in VP["metodos"]["mos_sanepar"]["materiais"] if re.search(rx, t)), None)


LARGURAS = {"nbr12266": _largura_nbr}


def _segmento_vala(sup: str, L: float, d: float, de_mm: float, material_texto: str, solo_fn, profundidade,
                   metodo: str = "nbr12266") -> tuple[dict | None, list]:
    """Dimensões de um segmento de vala pelo método de largura (as decisões) e a memória de cada uma; (None, [motivo])
    quando o método não se aplica (material fora da tabela)."""
    c = _constantes_vala()
    rec = VALAS["recobrimento_m"][VALAS["classes"].get(sup, {}).get("recobrimento", "outros")]
    h = profundidade if profundidade is not None else rec + d + c["berco"]
    solo = solo_fn(h)
    tipo, motivo = escoramento(h, solo)
    b, texto_b = _largura_nbr(d, de_mm, h, tipo, material_texto)
    if b is None:
        return None, [texto_b]
    flexivel = material_do_tubo(material_texto) == "flexivel"
    pav = VP["pavimentos"]["tipos"][VP["pavimentos"]["superficie_tipo"]["valor"].get(sup, "terra")]
    e_pav = sum(esp for _, esp in pav["camadas"])
    rocha = solo["topo_rocha_m"]
    h_rocha = max(0.0, h - max(rocha, e_pav)) if rocha is not None else 0.0
    hw, metodo, horas = _agua(h, solo, L, de_mm)
    mole = solo["nspt_min"] is not None and solo["nspt_min"] < VP["escoramento"]["agravantes"]["nspt_min"]
    dims = {**c, "L": L, "d": d, "h": h, "b": b, "e_pav": e_pav, "h_rocha": h_rocha, "h_solo": max(0.0, h - e_pav - h_rocha),
            "escorado": 0.0 if tipo == "nenhum" else 1.0, "tipo_escoramento": tipo, "flexivel": 1.0 if flexivel else 0.0,
            "item_pavimento": pav["item"] or "", "pavimento": pav["nome"], "h_agua": hw, "metodo_agua": metodo,
            "horas_agua": horas, "reap": c["reap_mole"] if mole else c["reap_solo"]}
    origem_h = "perfil longitudinal" if profundidade is not None else f"recobrimento {rec} + DE {d} + berço {c['berco']}"
    memoria = [f"h = {origem_h} = {h:.2f} m",
               (f"solo (furo {solo['furo']}): {', '.join(solo['classes']) or 'sem informação'}; "
                f"NSPT mín {solo['nspt_min']}; topo de rocha {rocha}; NA de projeto {solo['na_m']}"),
               f"escoramento {VP['largura']['nomes_escoramento'][tipo]}: {motivo}",
               texto_b,
               f"pavimento: {pav['nome']} (e = {e_pav:.2f} m) → {pav['item'] or 'sem item'}",
               f"h_rocha = {h_rocha:.2f} m; h_solo = {dims['h_solo']:.2f} m",
               f"água: {hw:.2f} m na vala → {metodo}" + (f", {horas:.0f} h" if horas else "")]
    return dims, memoria


def _pontos(geometria, passo_m: float = 1.0):
    """Eixo do trecho amostrado a cada metro (UTM), para a sondagem de cada metro no dimensionador MOS."""
    if geometria is None or geometria.length == 0:
        return None
    return np.array([geometria.interpolate(s).coords[0] for s in np.arange(0.0, geometria.length + 1e-9, passo_m)])


def _segmento_mos(sup: str, L: float, d: float, de_mm: float, material_texto: str, furos: list | None, pts,
                  profundidade, furo_proximo: dict | None) -> tuple[dict | None, list]:
    """Dimensões de um segmento pelo dimensionador único da main (`lineares.dimensionar_vala`, MOS): largura,
    escoramento, escavação, reaterro, bota-fora, escoramento (m²), pavimento e esgotamento são os dele; as dimensões
    dadas vencem os cálculos genéricos do tipo `vala`, e berço/envoltória saem da regra genérica com a largura do MOS."""
    from . import lineares
    material = material_mos(material_texto)
    if material is None:
        return None, ["MOS: material do tubo não reconhecido na Tabela I"]
    c = _constantes_vala()
    rec = VALAS["recobrimento_m"][VALAS["classes"].get(sup, {}).get("recobrimento", "outros")]
    h = profundidade if profundidade is not None else rec + d + c["berco"]
    pav_mos = VP["metodos"]["mos_sanepar"]["pavimentos"]["valor"].get(sup, "terra")
    trecho = {"local": sup, "dn_mm": de_mm, "material": material, "prof_m": h, "comp_m": L, "metodo": "VCA",
              "pavimentos": {pav_mos: L}, "sond_ini": (furo_proximo or {}).get("id")}
    r = lineares.dimensionar_vala(trecho, furos or [], pts=pts)
    if not r.get("largura_m"):
        return None, [f"MOS: {material} DN {de_mm:g} fora da Tabela I"]
    tipo = r.get("tipo_escoramento") or "nenhum"
    pav = VP["pavimentos"]["tipos"][VP["pavimentos"]["superficie_tipo"]["valor"].get(sup, "terra")]
    metodo_agua = r.get("tipo_esgotamento") or "nenhum"
    horas = L / _faixa(VP["lencol"]["produtividade_m_dia"]["valor"], de_mm) * VP["lencol"]["horas_por_dia"]["valor"] \
        if metodo_agua != "nenhum" else 0.0
    b = float(r["largura_m"])
    dims = {**c, "L": L, "d": d, "h": float(r["profundidade_m"]), "b": b, "e_pav": sum(e for _, e in pav["camadas"]),
            "h_rocha": 0.0, "h_solo": float(r["profundidade_m"]), "escorado": 0.0 if tipo == "nenhum" else 1.0,
            "tipo_escoramento": tipo, "flexivel": 1.0 if material_do_tubo(material_texto) == "flexivel" else 0.0,
            "item_pavimento": pav["item"] or "", "pavimento": pav["nome"], "h_agua": float(r.get("altura_agua_m") or 0.0),
            "metodo_agua": metodo_agua, "horas_agua": horas, "reap": c["reap_solo"],
            "V_solo": float(r["escavacao_m3"]), "V_rocha": 0.0, "V_reat": float(r["reaterro_m3"]),
            "V_bota": float(r["bota_fora_m3"]), "A_escoramento": float(r.get("escoramento_m2") or 0.0),
            "A_demol": float(sum((r.get("pavimento_m2") or {}).values())) if pav["item"] else 0.0}
    memoria = [(f"MOS (lineares.dimensionar_vala): h = {dims['h']:.2f} m ({r.get('fonte_profundidade')}), "
                f"L = {b:.2f} m ({material} DN {de_mm:g})"),
               f"escoramento {VP['largura']['nomes_escoramento'].get(tipo, tipo)}"
               + (f" ({', '.join(r.get('agravantes_escoramento') or [])})" if r.get("agravantes_escoramento") else ""),
               (f"escavação {r['escavacao_m3']:g} m³ · reaterro {r['reaterro_m3']:g} m³ · "
                f"bota-fora {r['bota_fora_m3']:g} m³ · pavimento {r.get('pavimento_m2')}"),
               f"água: {dims['h_agua']:.2f} m na vala → {metodo_agua}", *r.get("alertas", [])]
    return dims, memoria


def dimensionar_vala(trecho: dict, sondagens: list | None = None,
                     metodos: list[str] | None = None) -> list[tuple[str, str, tuple, list[str]]]:
    """[(segmento, método, (dimensões, faltando, memória), alertas)] de um trecho: {id, de_mm, segmentos: {superfície:
    m}, material_texto?, geometria (UTM)?, cota_terreno?, profundidade_m?}, por método de largura (todos os de
    `vala.metodos` por padrão). Método que não se aplica ao tubo fica de fora com alerta."""
    furo, dist = sondagem_proxima(trecho.get("geometria"), sondagens)
    alertas = [] if furo else [f"nenhuma sondagem a até {VP['sondagem']['raio_m']['valor']:.0f} m"
                               + (f" (a mais próxima a {dist:.0f} m)" if dist else "")
                               + ": solo, rocha e NA sem informação; bombeamento não avaliado"]
    desloc = 0.0
    if furo and trecho.get("cota_terreno") is not None and furo.get("cota_boca") is not None:
        desloc = float(trecho["cota_terreno"]) - float(furo["cota_boca"])
    elif furo:
        alertas.append(f"terreno do trecho tomado na cota da boca do furo {furo.get('id')} ({dist:.0f} m)")
    material = material_do_tubo(trecho.get("material_texto"))
    if material is None:
        alertas.append("material do tubo não identificado: sem envoltória (tratado como rígido)")
    saida, fora = [], []                                  # fora: método que não se aplica, avisado em todo o trecho
    pts = _pontos(trecho.get("geometria"))
    for metodo in metodos or list(VP["metodos"]):
        for sup, L in trecho["segmentos"].items():
            if metodo == "mos_sanepar":
                dims, memoria = _segmento_mos(sup, L, trecho["de_mm"] / 1000, trecho["de_mm"], trecho.get("material_texto"),
                                              sondagens, pts, trecho.get("profundidade_m"), furo)
            else:
                dims, memoria = _segmento_vala(sup, L, trecho["de_mm"] / 1000, trecho["de_mm"],
                                               trecho.get("material_texto"), lambda h: solo_na_vala(furo, h, desloc),
                                               trecho.get("profundidade_m"), metodo)
            if dims is None:
                fora.append(f"{sup}: {memoria[0]}")
                continue
            d, faltando, mem = dimensionar("vala", dados=dims)
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
    problemas += [f"vala.metodos: '{m}' sem código" for m in VP["metodos"] if m not in (*LARGURAS, "mos_sanepar")]
    return problemas
