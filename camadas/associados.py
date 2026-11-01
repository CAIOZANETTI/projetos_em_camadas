"""Serviços associados: o que a execução de cada elemento exige, declarado ou não no escopo do projeto.

    elementos (camadas.dimensoes) ─ dimensões padronizadas ─► regras (conceitos/servicos_associados.jsonl)
        bloco    V, A_forma, A_fundo        ─► concreto, forma, armadura (taxa), lastro
        cava     V_esc, V_reat (derivada)   ─► escavação, reaterro
        laje     V, A_forma, A_escoramento, A_imperm ─► concreto, forma, escoramento, impermeabilização
        parede   V, A_forma, A_imperm       ─► concreto, forma, impermeabilização
        vala     V_solo, V_rocha, A_demol, A_escoramento, V_bota, horas_agua… ─► corte, demolição, escavação,
                 escoramento por tipo, berço, envoltória, assentamento, reaterro, bota-fora, esgotamento

Uma regra vale para os `tipos` que lista e usa só dimensões: a mesma regra de forma serve a bloco, pilar, viga e
parede. `condicao` filtra (vala escorada, pavimento existente, água na vala); destino e serviço aceitam modelo
('{item}' = item EAP do elemento, '{item_pavimento}', 'escoramento_{tipo_escoramento}'). Faltou dimensão → o serviço
fica sem valor com o que faltou, nunca com zero inventado. Cada resultado vira evidência `associado` com a memória
de cálculo no trecho; `detalhe` fica só na memória (volume demolido, reaterro importado).
"""
from __future__ import annotations

import json

import pandas as pd

from . import dimensoes
from .formulas import avaliar, conferir, nomes, premissa
from .pdf_cad import CONCEITOS

REGRAS = [json.loads(linha) for linha in (CONCEITOS / "servicos_associados.jsonl").read_text(encoding="utf-8").splitlines()
          if linha.strip()]
DOCUMENTO = {"id": "regras:servicos_associados", "tipo": "associado",
             "nome": "serviços associados (camadas.associados, conceitos/servicos_associados.jsonl)"}


def _documento(el: dict) -> dict:
    """Fonte da evidência: o método de cálculo do elemento (cada método da vala é uma fonte independente, para a
    consolidação comparar), ou as regras gerais."""
    if not el.get("metodo"):
        return DOCUMENTO
    nome = dimensoes.VP["metodos"].get(el["metodo"], {}).get("nome", el["metodo"])
    return {"id": f"metodo:{el['metodo']}", "tipo": "associado", "nome": f"serviços associados · {nome}"}


def _textos(el: dict) -> dict:
    return {"item": el["item"] or "", **{k: v for k, v in el["dims"].items() if isinstance(v, str)}}


def _cadeia(el: dict, nome: str) -> str:
    """Da dimensão que a regra pediu até a que faltou na origem: 'V ← h ← face'."""
    causas = {f.split(" (falta ")[0]: f.split(" (falta ")[1].rstrip(")") for f in el["faltando"] if " (falta " in f}
    cadeia = [nome]
    while cadeia[-1] in causas and causas[cadeia[-1]] not in cadeia:
        cadeia.append(causas[cadeia[-1]])
    return " ← ".join(cadeia)


def calcular(regra: dict, el: dict) -> dict:
    """Uma regra num elemento: {valor, item, servico, contexto} ou {falta} ou {} (condição falsa / resultado nulo)."""
    contexto = {**{k: premissa(p, el["tipo"]) for k, p in regra.get("premissas", {}).items()}, **el["dims"]}
    try:
        if regra.get("condicao") and not avaliar(regra["condicao"], contexto):
            return {}
        valor = float(avaliar(regra["formula"], contexto))
    except KeyError as falta:
        return {"falta": _cadeia(el, falta.args[0])}
    item = regra["destino"]["item"].format(**_textos(el))
    if not item:
        return {"falta": "item EAP do elemento"}
    if valor <= 1e-9:
        return {}
    return {"valor": valor, "item": item, "servico": regra["destino"]["servico"].format(**_textos(el)),
            "contexto": {k: contexto[k] for k in nomes(regra["formula"]) if k in contexto}}


def _memoria(regra: dict, el: dict, r: dict) -> str:
    usados = ", ".join(f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v}" for k, v in r["contexto"].items())
    texto = f"{regra['nome']}: {regra['formula']} = {r['valor']:.4g} {regra['unidade']} ({usados}) · {regra['estado']}"
    if el["memoria"]:                                     # a cadeia das dimensões do elemento até a fórmula
        texto += " · " + "; ".join(el["memoria"])
    return texto + (f" · alertas: {'; '.join(el['alertas'])}" if el["alertas"] else "")


def aplicar(elementos: list[dict]) -> tuple[list[dict], dict, list[dict]]:
    """(evidências, {regra: ['elemento (falta x)']}, detalhes) de todas as regras em todos os elementos."""
    from .evidencias import evidencia
    evs, sem_valor, detalhes = [], {}, []
    for regra in REGRAS:
        for el in (e for e in elementos if e["tipo"] in regra["tipos"]):
            r = calcular(regra, el)
            if "falta" in r:
                sem_valor.setdefault(regra["id"], []).append(f"{el['id']} (falta {r['falta']})")
            elif r and regra.get("detalhe"):
                detalhes.append({"elemento": el["id"], "regra": regra["id"], "nome": regra["nome"],
                                 "unidade": regra["unidade"], "valor": round(r["valor"], 3)})
            elif r:
                evs.append(evidencia(codigo=f"{el['base']}.{r['item']}", servico=r["servico"], unidade=regra["unidade"],
                                     valor=round(r["valor"], 6), parcela=True, documento=_documento(el),
                                     localizador=el["id"], trecho=_memoria(regra, el, r), metodo="associado",
                                     regra=regra["id"]))
    return evs, sem_valor, detalhes


def de_elementos(construtivos: dict, epsg: int, sondagens: list | None = None,
                 declarados: list[dict] | None = None) -> tuple[list[dict], dict]:
    """Evidências dos serviços associados aos elementos construtivos (e derivados) e aos declarados no obra.json; e
    {regra: elementos sem valor}."""
    elementos = (dimensoes.de_construtivos(construtivos, epsg, sondagens) if construtivos else []) + \
        dimensoes.de_declarados(declarados)
    evs, sem_valor, _ = aplicar(elementos)
    return evs, sem_valor


def de_fatos(fatos: pd.DataFrame) -> list[dict]:
    """Evidências dos serviços associados a fatos consolidados (laje → escoramento, baldrame → escavação…)."""
    return aplicar(dimensoes.de_fatos(fatos))[0]


def tabela(evs: list[dict]) -> pd.DataFrame:
    """Serviços associados somados por código, serviço e unidade (com o número de elementos)."""
    df = pd.DataFrame([e for e in evs if e["metodo"] == "associado"])
    if df.empty:
        return df
    return df.groupby(["codigo", "servico", "unidade"], sort=False).agg(
        quantidade=("valor", "sum"), n_elementos=("localizador", "nunique"), regras=("regra", lambda r: sorted(set(r)))
    ).reset_index()


def validar() -> list[str]:
    """Problemas das regras: id repetido, tipo inexistente, destino fora da EAP geral ou serviço não admitido no item,
    unidade desconhecida, fórmula com dimensão que nenhum tipo listado produz."""
    from . import eap, vocabulario
    itens, problemas = eap.itens(), []
    ids = [r["id"] for r in REGRAS]
    problemas += [f"regra repetida: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for r in REGRAS:
        problemas += [f"{r['id']}: tipo '{t}' fora de dimensoes.json" for t in r["tipos"] if t not in dimensoes.TIPOS]
        problemas += [f"{r['id']}: {erro}" for expr in (r["formula"], r.get("condicao") or "1") if (erro := conferir(expr))]
        if r["unidade"] not in vocabulario.REGRAS["unidades"]:
            problemas.append(f"{r['id']}: unidade {r['unidade']} desconhecida")
        destinos = [r["destino"]["item"]] if "{" not in r["destino"]["item"] else \
            [dimensoes.item_do_tipo(t) for t in r["tipos"] if r["destino"]["item"] == "{item}"]
        for item in filter(None, destinos):
            servico = r["destino"]["servico"]
            if item not in itens:
                problemas.append(f"{r['id']}: destino {item} fora da EAP geral")
            elif servico and "{" not in servico and servico not in itens[item]["servicos"]:
                problemas.append(f"{r['id']}: serviço {servico} não admitido em {item}")
        for t in (t for t in r["tipos"] if t in dimensoes.TIPOS):
            spec = dimensoes.TIPOS[t]
            conhecidas = set(spec["dimensoes"]) | set(spec["premissas"]) | set(spec["calculos"]) | set(r.get("premissas", {}))
            if spec.get("dimensionador") == "vala":
                continue                                                  # dimensões dadas por dimensionar_vala
            faltam = [n for n in nomes(r["formula"]) if n not in conhecidas]
            problemas += [f"{r['id']}: '{t}' não produz {faltam}"] if faltam else []
    return problemas
