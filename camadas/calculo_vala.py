"""Cálculo dos serviços associados de uma rede (vala), passo a passo e com a sondagem mais próxima.

    trecho (extensão por superfície, DE, material, posição) + sondagens + conceitos/calculo_vala.json + valas.json
    por segmento de superfície (pista, calçada, fora da via…):
      1 profundidade      h = recobrimento (da superfície) + DE + berço       (ou a profundidade do perfil)
      2 solo e água       furo mais próximo no raio: classes na faixa 0–h, NSPT mínimo, topo de rocha, NA (+ margem)
      3 escoramento       nenhum (vala rasa ≤ 1,25 m) → pontaleteamento → descontínuo → contínuo → especial;
                          areia/aterro, NSPT < 4 ou abaixo do NA ⇒ no mínimo contínuo
      4 largura           b = max(DE + folga, mínimo da profundidade) + acréscimo do escoramento
      5 pavimento         corte (2 bordas), demolição (b + 2·sobrelargura) e camadas pelo tipo (asfalto, calçada…)
      6 escavação         abaixo do pavimento, separada em solo e rocha
      7 tubo              berço, envoltória (tubo flexível), assentamento
      8 reaterro e bota-fora   com reaproveitamento (rocha e solo mole não voltam) e empolamento
      9 recomposição      mesma área demolida, camadas do tipo de pavimento
     10 água              vala abaixo do NA ⇒ esgotamento (bomba) ou rebaixamento (ponteiras), horas pelo avanço

Cada passo guarda fórmula, valores e fonte (memória de cálculo). O que não se sabe não é suposto: sem sondagem no
raio, nem rocha nem NA entram, e o resultado leva o alerta.
"""
from __future__ import annotations

import json
import math
import re

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import Point, shape

from . import geo
from .pdf_cad import CONCEITOS

P = json.loads((CONCEITOS / "calculo_vala.json").read_text(encoding="utf-8"))
VALAS = json.loads((CONCEITOS / "valas.json").read_text(encoding="utf-8"))
DESTINO = {"corte_pavimento": None, "demolicao": None, "recomposicao": None,          # None = item do pavimento
           "escavacao": "GEO.MOV.VAL", "escavacao_rocha": "GEO.MOV.VAL", "berco": "GEO.MOV.VAL",
           "envoltoria": "GEO.MOV.VAL", "reaterro": "GEO.MOV.VAL", "bota_fora": "GEO.MOV.VAL",
           "esgotamento": "GEO.MOV.VAL", "rebaixamento": "GEO.MOV.VAL", "assentamento": "HID.TUB.RED",
           **{f"escoramento_{t}": "GEO.MOV.VAL" for t in ("pontaleteamento", "descontinuo", "continuo", "especial")}}


def _faixa(tabela: list, x: float):
    """Valor da primeira faixa [limite, valor] com x ≤ limite."""
    return next(v for lim, v in tabela if x <= lim)


def material_do_tubo(texto: str) -> str | None:
    """'flexivel' (PEAD, PVC…), 'rigido' (FD, concreto…) ou None pelo texto do trecho (contrato, rede)."""
    t = str(texto or "").upper()
    if re.search(P["tubo"]["flexiveis"]["valor"], t):
        return "flexivel"
    if re.search(P["tubo"]["rigidos"]["valor"], t):
        return "rigido"
    return None


def classe_solo(descricao: str | None, classe: str | None = None) -> str | None:
    """Classe da camada (rocha, areia, argila, silte, aterro) pela palavra principal; a primeira regra que casa vence."""
    from .vocabulario import normalizar
    t = normalizar(f"{classe or ''} {descricao or ''}")
    return next((c for c, rx in P["solo"]["classes"]["valor"] if re.search(rx, t)), None)


def sondagem_proxima(geometria, furos: list) -> tuple[dict | None, float | None]:
    """Furo com E/N mais próximo da geometria do trecho (UTM) dentro do raio; (None, None) se nenhum."""
    if geometria is None:
        return None, None
    candidatos = [(geometria.distance(Point(f["E"], f["N"])), f) for f in furos or []
                  if f.get("E") is not None and f.get("N") is not None]
    if not candidatos:
        return None, None
    d, furo = min(candidatos, key=lambda c: c[0])
    return (furo, round(d, 1)) if d <= P["sondagem"]["raio_m"]["valor"] else (None, round(d, 1))


def solo_na_vala(furo: dict | None, h: float, desloc_m: float = 0.0) -> dict:
    """O que o furo diz da faixa 0–h do trecho (profundidades do furo + desloc = cota do trecho − cota da boca)."""
    if furo is None:
        return {"furo": None, "classes": [], "nao_coesivo": False, "nspt_min": None, "topo_rocha_m": None,
                "na_m": None, "confirmado": False}
    camadas = furo.get("camadas") or []
    na_faixa = [c for c in camadas if c.get("de") is None or c["de"] + desloc_m < h]
    classes = list(dict.fromkeys(filter(None, (classe_solo(c.get("descricao"), c.get("classe")) for c in na_faixa))))
    rochas = [c["de"] + desloc_m for c in camadas if c.get("de") is not None
              and classe_solo(c.get("descricao"), c.get("classe")) == "rocha"]
    if furo.get("impenetravel") and furo.get("profundidade_m") and P["solo"]["impenetravel_e_rocha"]["valor"]:
        rochas.append(float(furo["profundidade_m"]) + desloc_m)
    golpes = [g for prof, g in furo.get("nspt") or [] if prof + desloc_m <= h]
    na = furo.get("na_m")
    return {"furo": furo.get("id"), "classes": classes,
            "nao_coesivo": bool(set(classes) & set(P["escoramento"]["agravantes"]["solos_nao_coesivos"])),
            "nspt_min": min(golpes) if golpes else None, "topo_rocha_m": round(min(rochas), 2) if rochas else None,
            "na_m": round(na + desloc_m - P["lencol"]["margem_m"]["valor"], 2) if na is not None else None,
            "confirmado": all(c.get("de") is not None and c.get("ate") is not None for c in na_faixa)}


def escoramento(h: float, solo: dict) -> tuple[str, str]:
    """(tipo, motivo) pela profundidade e pelos agravantes do solo e da água."""
    tipo = _faixa(P["escoramento"]["profundidade_max_m"]["valor"], h)
    ag = P["escoramento"]["agravantes"]
    if tipo == "nenhum":
        return tipo, f"vala rasa (h = {h:.2f} m ≤ 1,25 m, NR-18)"
    motivos = [m for m, sim in (("solo não coesivo", solo["nao_coesivo"]),
                                (f"NSPT {solo['nspt_min']} < {ag['nspt_min']}", solo["nspt_min"] is not None
                                 and solo["nspt_min"] < ag["nspt_min"]),
                                ("abaixo do NA", solo["na_m"] is not None and solo["na_m"] < h)) if sim]
    ordem = [t for _, t in P["escoramento"]["profundidade_max_m"]["valor"]]
    if motivos and ordem.index(tipo) < ordem.index(ag["tipo_minimo"]):
        return ag["tipo_minimo"], f"h = {h:.2f} m e " + ", ".join(motivos)
    return tipo, f"h = {h:.2f} m" + (f" ({', '.join(motivos)})" if motivos else "")


class _Memoria:
    """Passos (fórmula, valores, resultado, fonte) e quantidades (serviço, item, unidade, valor) de um segmento."""

    def __init__(self, segmento: str):
        self.segmento, self.passos, self.quantidades = segmento, [], []

    def passo(self, nome: str, formula: str, valores: dict, resultado, unidade: str = "", fonte: str = ""):
        self.passos.append({"segmento": self.segmento, "passo": nome, "formula": formula,
                            "valores": {k: round(v, 4) if isinstance(v, float) else v for k, v in valores.items()},
                            "resultado": round(resultado, 4) if isinstance(resultado, float) else resultado,
                            "unidade": unidade, "fonte": fonte})
        return resultado

    def qtd(self, servico: str | None, item: str | None, unidade: str, valor: float, descricao: str):
        """Quantidade do segmento; servico None = detalhe da memória (não vira evidência)."""
        if valor > 1e-9:
            self.quantidades.append({"segmento": self.segmento, "servico": servico, "item": item, "unidade": unidade,
                                     "valor": round(valor, 3), "descricao": descricao})


def _geometria(m: _Memoria, sup: str, d: float, solo_fn, profundidade: float | None) -> dict:
    """Passos 1–4: profundidade, solo, escoramento e largura."""
    rec = VALAS["recobrimento_m"][VALAS["classes"].get(sup, {}).get("recobrimento", "outros")]
    berco = VALAS["berco_m"]["valor"]
    h = profundidade if profundidade is not None else \
        m.passo("profundidade", "h = recobrimento + DE + berço", {"recobrimento": rec, "DE": d, "berco": berco},
                rec + d + berco, "m", "valas.json (NBR 12266)")
    if profundidade is not None:
        m.passo("profundidade", "h = profundidade do perfil", {"h": h}, h, "m", "perfil longitudinal")
    solo = solo_fn(h)
    m.passo("solo", "furo mais próximo na faixa 0–h", {k: solo[k] for k in ("furo", "classes", "nspt_min", "topo_rocha_m",
            "na_m")}, ", ".join(solo["classes"]) or "sem informação", "", "sondagem (NA com margem sazonal)")
    tipo, motivo = escoramento(h, solo)
    m.passo("escoramento", "tipo pela profundidade e agravantes", {"h": h}, tipo, "", motivo)
    folga, bmin = VALAS["largura_vala"]["folga_m"], _faixa(P["largura"]["minimo_por_profundidade"]["valor"], h)
    acr = P["largura"]["acrescimo_escoramento_m"]["valor"][tipo]
    b = m.passo("largura", "b = max(DE + folga, b_min(h)) + acréscimo do escoramento",
                {"DE": d, "folga": folga, "b_min": bmin, "acrescimo": acr}, max(d + folga, bmin) + acr, "m",
                "valas.json + calculo_vala.json")
    return {"h": h, "b": b, "tipo": tipo, "solo": solo, "berco": berco}


def _pavimento(m: _Memoria, sup: str, L: float, b: float) -> dict:
    """Passos 5 e 9: corte, demolição e recomposição pelo tipo de pavimento da superfície."""
    tipo = P["pavimentos"]["superficie_tipo"]["valor"].get(sup, "terra")
    pav = P["pavimentos"]["tipos"][tipo]
    e = sum(esp for _, esp in pav["camadas"])
    if not pav["item"]:
        m.passo("pavimento", "sem pavimento", {"superficie": sup}, pav["nome"], "", pav["fonte"])
        return {"e": 0.0, "volume": 0.0}
    sobre = VALAS["sobrelargura_recorte_m"]["valor"]
    corte = m.passo("corte do pavimento", "cortes × L", {"cortes": P["pavimentos"]["cortes_por_trecho"]["valor"], "L": L},
                    P["pavimentos"]["cortes_por_trecho"]["valor"] * L, "m")
    area = m.passo("demolição", "A = L × (b + 2 × sobrelargura)", {"L": L, "b": b, "sobrelargura": sobre},
                   L * (b + 2 * sobre), "m²", f"{pav['nome']}: {pav['fonte']}")
    nome = pav["nome"]
    m.qtd("corte_pavimento", pav["item"], "m", corte, f"corte de {nome}")
    m.qtd("demolicao", pav["item"], "m²", area, f"demolição de {nome}")
    m.qtd(None, None, "m³", area * e, f"volume demolido de {nome} (e = {e:.2f} m)")
    m.qtd("recomposicao", pav["item"], "m²", area, f"recomposição de {nome}")
    for nome, esp in pav["camadas"]:
        m.qtd(None, None, "m³", area * esp, f"recomposição: {nome} ({esp:.2f} m)")
    return {"e": e, "volume": area * e}


def _escavacao(m: _Memoria, L: float, g: dict, e_pav: float) -> dict:
    """Passo 6: escavação abaixo do pavimento, em solo e em rocha; escoramento só na parte em solo."""
    h, b, rocha = g["h"], g["b"], g["solo"]["topo_rocha_m"]
    h_rocha = max(0.0, h - max(rocha, e_pav)) if rocha is not None else 0.0
    h_solo = max(0.0, h - e_pav - h_rocha)
    v_solo = m.passo("escavação em solo", "V = b × (h − e_pav − h_rocha) × L",
                     {"b": b, "h": h, "e_pav": e_pav, "h_rocha": h_rocha, "L": L}, b * h_solo * L, "m³")
    v_rocha = m.passo("escavação em rocha", "V = b × h_rocha × L", {"b": b, "h_rocha": h_rocha, "topo_rocha": rocha, "L": L},
                      b * h_rocha * L, "m³", "topo de rocha pela sondagem")
    m.qtd("escavacao", DESTINO["escavacao"], "m³", v_solo, "escavação de vala em solo")
    m.qtd("escavacao_rocha", DESTINO["escavacao_rocha"], "m³", v_rocha, "escavação de vala em rocha")
    if g["tipo"] != "nenhum":
        area = m.passo("escoramento", "A = paredes × (h − h_rocha) × L",
                       {"paredes": P["escoramento"]["paredes"]["valor"], "h": h, "h_rocha": h_rocha, "L": L},
                       P["escoramento"]["paredes"]["valor"] * (h - h_rocha) * L, "m²")
        m.qtd(f"escoramento_{g['tipo']}", DESTINO[f"escoramento_{g['tipo']}"], "m²", area,
              f"escoramento {P['largura']['nomes_escoramento'][g['tipo']]}")
    return {"solo": v_solo, "rocha": v_rocha}


def _tubo_e_reaterro(m: _Memoria, L: float, d: float, g: dict, material: str | None, esc: dict, v_pav: float) -> None:
    """Passos 7–8: berço, envoltória, assentamento, reaterro (próprio × importado) e bota-fora empolado."""
    b = g["b"]
    v_berco = m.passo("berço", "V = b × e_berço × L", {"b": b, "e_berco": g["berco"], "L": L}, b * g["berco"] * L, "m³")
    v_tubo = math.pi * d ** 2 / 4 * L
    acima = P["tubo"]["envoltoria_acima_m"]["valor"]
    v_env = m.passo("envoltória", "V = b × (DE + acima) × L − π DE²/4 × L (só tubo flexível)",
                    {"b": b, "DE": d, "acima": acima, "L": L, "material": material or "não identificado"},
                    (b * (d + acima) * L - v_tubo) if material == "flexivel" else 0.0, "m³", P["tubo"]["flexiveis"]["fonte"])
    m.qtd("berco", DESTINO["berco"], "m³", v_berco, "berço do tubo")
    m.qtd("envoltoria", DESTINO["envoltoria"], "m³", v_env, "envoltória do tubo")
    m.qtd("assentamento", DESTINO["assentamento"], "m", L, "assentamento do tubo")
    reaterro = m.passo("reaterro", "V = V_solo + V_rocha − V_berço − V_envoltória − V_tubo",
                       {"V_solo": esc["solo"], "V_rocha": esc["rocha"], "V_berco": v_berco, "V_env": v_env, "V_tubo": v_tubo},
                       max(0.0, esc["solo"] + esc["rocha"] - v_berco - v_env - v_tubo), "m³")
    mole = g["solo"]["nspt_min"] is not None and g["solo"]["nspt_min"] < P["escoramento"]["agravantes"]["nspt_min"]
    reap, emp = P["volumes"]["reaproveitamento"]["valor"], P["volumes"]["empolamento"]["valor"]
    proprio = min(reaterro, esc["solo"] * reap["mole" if mole else "solo"])
    bota = m.passo("bota-fora", "V = (V_solo − reaterro próprio) × emp_solo + V_rocha × emp_rocha + V_pav × emp_pav",
                   {"V_solo": esc["solo"], "proprio": proprio, "V_rocha": esc["rocha"], "V_pav": v_pav, **emp},
                   (esc["solo"] - proprio) * emp["solo"] + esc["rocha"] * emp["rocha"] + v_pav * emp["pavimento"], "m³",
                   P["volumes"]["empolamento"]["fonte"])
    m.qtd("reaterro", DESTINO["reaterro"], "m³", reaterro, "reaterro compactado de vala")
    m.qtd(None, None, "m³", reaterro - proprio, "material de reaterro importado (jazida)")
    m.qtd("bota_fora", DESTINO["bota_fora"], "m³", bota, "carga, transporte e bota-fora (empolado)")


def _agua(m: _Memoria, L: float, d_mm: float, g: dict) -> list[str]:
    """Passo 10: vala abaixo do NA → esgotamento ou rebaixamento, pelo tempo de vala aberta."""
    na, h = g["solo"]["na_m"], g["h"]
    if na is None:
        return ["sem NA da sondagem: necessidade de bombeamento não avaliada"] if g["solo"]["furo"] is None else []
    hw = m.passo("lençol", "altura de água na vala = h − NA (NA com margem)", {"h": h, "NA": na}, max(0.0, h - na), "m")
    if hw <= 0:
        return []
    metodo = "rebaixamento com ponteiras filtrantes" if g["solo"]["nao_coesivo"] else \
        _faixa(P["lencol"]["metodo"]["valor"], hw)
    dias = L / _faixa(P["lencol"]["produtividade_m_dia"]["valor"], d_mm)
    horas = m.passo("bombeamento", "horas = L / produtividade(DE) × horas por dia",
                    {"L": L, "dias": dias, "horas_dia": P["lencol"]["horas_por_dia"]["valor"], "metodo": metodo},
                    dias * P["lencol"]["horas_por_dia"]["valor"], "h", P["lencol"]["produtividade_m_dia"]["fonte"])
    if metodo.startswith("rebaixamento"):
        m.qtd("rebaixamento", DESTINO["rebaixamento"], "m", L * P["lencol"]["ponteiras_lados"]["valor"],
              "linha de ponteiras filtrantes")
        m.qtd("rebaixamento", DESTINO["rebaixamento"], "h", horas, "operação do rebaixamento")
    else:
        m.qtd("esgotamento", DESTINO["esgotamento"], "h", horas, "esgotamento com bomba submersível")
    return [f"vala atinge o NA ({hw:.2f} m de água): {metodo}"]


def calcular_trecho(trecho: dict, sondagens: list | None = None) -> dict:
    """Memória de cálculo de um trecho: `trecho` = {id, de_mm, segmentos: {superfície: extensão m}, material_texto?,
    geometria (shapely, UTM)?, cota_terreno?, profundidade_m?}. Devolve entradas, sondagem, passos, quantidades e alertas."""
    furo, dist = sondagem_proxima(trecho.get("geometria"), sondagens)
    alertas = [] if furo else [f"nenhuma sondagem a até {P['sondagem']['raio_m']['valor']:.0f} m"
                               + (f" (a mais próxima a {dist:.0f} m)" if dist else "") + ": solo, rocha e NA sem informação"]
    desloc = 0.0
    if furo and trecho.get("cota_terreno") is not None and furo.get("cota_boca") is not None:
        desloc = float(trecho["cota_terreno"]) - float(furo["cota_boca"])
    elif furo:
        alertas.append(f"terreno do trecho tomado na cota da boca do furo {furo.get('id')}")
    d, material = trecho["de_mm"] / 1000, material_do_tubo(trecho.get("material_texto"))
    if material is None:
        alertas.append("material do tubo não identificado: sem envoltória (tratado como rígido)")
    passos, quantidades = [], []
    for sup, L in trecho["segmentos"].items():
        m = _Memoria(sup)
        g = _geometria(m, sup, d, lambda h: solo_na_vala(furo, h, desloc), trecho.get("profundidade_m"))
        pav = _pavimento(m, sup, L, g["b"])
        esc = _escavacao(m, L, g, pav["e"])
        _tubo_e_reaterro(m, L, d, g, material, esc, pav["volume"])
        alertas += [f"{sup}: {a}" for a in _agua(m, L, trecho["de_mm"], g)]
        passos += m.passos
        quantidades += m.quantidades
    return {"id": trecho["id"], "de_mm": trecho["de_mm"], "material": material, "segmentos": trecho["segmentos"],
            "sondagem": {"id": furo.get("id"), "distancia_m": dist} if furo else None,
            "passos": passos, "quantidades": quantidades, "alertas": list(dict.fromkeys(alertas))}


def de_feature(feature: dict, epsg: int) -> dict | None:
    """Trecho para o cálculo a partir de um elemento `trecho` de camadas.construtivos (extensão por superfície pelos
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


def tabela(calculo: dict) -> pd.DataFrame:
    """Quantidades do trecho por serviço e unidade (somando os segmentos), com o item EAP."""
    df = pd.DataFrame(calculo["quantidades"])
    if df.empty:
        return df
    df["servico"] = df["servico"].fillna("(detalhe)")
    df["item"] = df["item"].fillna("")
    return df.groupby(["item", "servico", "descricao", "unidade"], sort=False)["valor"].sum().round(3).reset_index()


def metadados() -> dict:
    """Rastreabilidade do método e das regras declaradas (regra 9 do estilo)."""
    regras = [(f"{grupo}.{k}", v) for grupo in ("largura", "escoramento", "lencol", "tubo", "volumes", "sondagem")
              for k, v in P[grupo].items() if isinstance(v, dict) and "estado" in v]
    return {
        "modulo": "calculo_vala",
        "descricao": "serviços associados de rede por segmento de superfície: profundidade, escoramento, largura, "
                     "pavimento, escavação solo/rocha, tubo, reaterro, bota-fora e água pela sondagem mais próxima",
        "funcoes": ["calcular_trecho", "de_feature", "tabela", "escoramento", "solo_na_vala", "sondagem_proxima"],
        "bibliografia": ["NBR 12266 — projeto e execução de valas para assentamento de tubulação",
                         "NR-18 — escavações com mais de 1,25 m"],
        "premissas": [{"aplicacao": {"calcular_trecho": [nome]}, "fonte": v["fonte"], "estado": v["estado"]}
                      for nome, v in regras],
        "ultima_revisao": P["metadata"]["data_referencia"],
    }
