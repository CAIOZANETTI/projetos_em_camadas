"""Serviços associados: o que a execução exige e nenhum documento cita (conceitos/servicos_associados.jsonl).

    bloco      ─► escavação, reaterro, lastro, forma, concreto, armadura (taxa)
    estaca     ─► concreto do fuste, arrasamento
    trecho     ─► camadas.calculo_vala: largura, escoramento, pavimento, escavação solo/rocha, tubo, reaterro,
                  bota-fora e água pela sondagem mais próxima
    fato laje  ─► escoramento          fato baldrame ─► escavação e reaterro

Cada regra tem base (classe do elemento construtivo ou fato consolidado), destino (item EAP + serviço), variáveis
(atributo, geometria em UTM ou valor do fato), premissas com fonte e estado (ou referência a outro conceito, ex.:
'valas.json#berco_m.valor'), cálculos intermediários e a fórmula. A fórmula é avaliada por um avaliador restrito
(números, + − × ÷ **, max, min, pi): nada de código arbitrário. Faltou variável sem padrão → o elemento fica sem valor,
nunca com zero inventado. Cada resultado vira evidência `associado` com a memória de cálculo no trecho.
"""
from __future__ import annotations

import ast
import json
import math
import operator

import numpy as np
import shapely
from shapely.geometry import shape

from . import geo
from .pdf_cad import CONCEITOS

REGRAS = [json.loads(linha) for linha in (CONCEITOS / "servicos_associados.jsonl").read_text(encoding="utf-8").splitlines()
          if linha.strip()]
DOCUMENTO = {"id": "regras:servicos_associados", "tipo": "associado",
             "nome": "serviços associados (conceitos/servicos_associados.jsonl)"}
OPERADORES = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
              ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
FUNCOES = {"max": max, "min": min}


def avaliar(expressao: str, valores: dict) -> float:
    """Valor de uma fórmula só com números, variáveis de `valores`, + − × ÷ **, max, min e pi."""
    def no(n):
        if isinstance(n, ast.Expression):
            return no(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.Name):
            if n.id == "pi":
                return math.pi
            if n.id not in valores:
                raise KeyError(n.id)
            return float(valores[n.id])
        if isinstance(n, ast.BinOp) and type(n.op) in OPERADORES:
            return OPERADORES[type(n.op)](no(n.left), no(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in OPERADORES:
            return OPERADORES[type(n.op)](no(n.operand))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCOES and not n.keywords:
            return FUNCOES[n.func.id](*map(no, n.args))
        raise ValueError(f"expressão não permitida: {ast.dump(n)}")
    return no(ast.parse(expressao, mode="eval"))


def premissa(p: dict) -> float:
    """Valor da premissa: direto (`valor`) ou referência 'arquivo.json#chave.subchave' a outro conceito."""
    if "ref" not in p:
        return float(p["valor"])
    arquivo, caminho = p["ref"].split("#")
    dado = json.loads((CONCEITOS / arquivo).read_text(encoding="utf-8"))
    for chave in caminho.split("."):
        dado = dado[chave]
    return float(dado)


def _geometria(feature: dict, medida: str, epsg: int) -> float:
    g = shapely.transform(shape(feature["geometry"]),
                          lambda xy: np.column_stack(geo.para_utm(xy[:, 0], xy[:, 1], epsg)))
    return float({"area": g.area, "perimetro": g.length, "comprimento": g.length}[medida])


def _variaveis(regra: dict, feature: dict | None, epsg: int | None, fato: float | None) -> dict | None:
    """Valores das variáveis da regra para um elemento (ou fato); None se falta uma sem padrão."""
    atributos = dict(feature["properties"]["atributos"]) if feature else {}
    valores = {}
    for nome, spec in regra["variaveis"].items():
        if spec.get("fato"):
            v = fato
        elif "geometria" in spec:
            v = _geometria(feature, spec["geometria"], epsg)
        else:
            v = atributos.get(spec["atributo"], spec.get("padrao"))
        if not isinstance(v, (int, float)):
            return None
        valores[nome] = float(v)
    return valores


def calcular(regra: dict, valores: dict) -> tuple[float, dict]:
    """(resultado, todos os valores usados): premissas, variáveis e cálculos intermediários na ordem declarada."""
    contexto = {**{k: premissa(p) for k, p in regra["premissas"].items()}, **valores}
    for nome, expr in regra["calculos"].items():
        contexto[nome] = avaliar(expr, contexto)
    return avaliar(regra["formula"], contexto), contexto


def _memoria(regra: dict, contexto: dict, resultado: float) -> str:
    usados = ", ".join(f"{k}={v:.4g}" for k, v in contexto.items())
    return f"{regra['nome']}: {regra['formula']} = {resultado:.4g} {regra['unidade']} ({usados}) · {regra['estado']}"


def _evidencia(regra: dict, codigo_base: str, localizador: str, contexto: dict, resultado: float) -> dict:
    from .evidencias import evidencia
    return evidencia(codigo=f"{codigo_base}.{regra['destino']['item']}", servico=regra["destino"]["servico"],
                     unidade=regra["unidade"], valor=round(resultado, 6), parcela=True, documento=DOCUMENTO,
                     localizador=localizador, trecho=_memoria(regra, contexto, resultado), metodo="associado",
                     regra=regra["id"])


def de_elementos(construtivos: dict, epsg: int, sondagens: list | None = None) -> tuple[list[dict], dict]:
    """Evidências dos serviços associados a cada elemento construtivo (regras por fórmula e, nos trechos de rede, o
    cálculo da vala com as `sondagens`); e {regra: elementos sem valor}."""
    saida, sem_valor = _de_trechos(construtivos, epsg, sondagens)
    for regra in (r for r in REGRAS if "classe" in r["base"]):
        for f in construtivos["geojson"]["features"]:
            p = f["properties"]
            if p["classe"] != regra["base"]["classe"]:
                continue
            valores = _variaveis(regra, f, epsg, None)
            if valores is None:
                sem_valor.setdefault(regra["id"], []).append(p["id"])
                continue
            resultado, contexto = calcular(regra, valores)
            base = f"{p['unidade'].upper()}.{p['sistema'].split('-', 1)[1]}"
            saida.append(_evidencia(regra, base, p["id"], contexto, resultado))
    return saida, sem_valor


def _de_trechos(construtivos: dict, epsg: int, sondagens: list | None) -> tuple[list[dict], dict]:
    """Uma evidência por quantidade (não detalhe) do cálculo de vala de cada trecho, com a memória do serviço."""
    from . import calculo_vala
    from .evidencias import evidencia
    saida, sem_valor = [], {}
    for f in construtivos["geojson"]["features"]:
        p = f["properties"]
        if p["classe"] != "trecho":
            continue
        trecho = calculo_vala.de_feature(f, epsg)
        if trecho is None:
            sem_valor.setdefault("calculo_vala", []).append(p["id"])
            continue
        calc = calculo_vala.calcular_trecho(trecho, sondagens)
        base = f"{p['unidade'].upper()}.{p['sistema'].split('-', 1)[1]}"
        for q in (q for q in calc["quantidades"] if q["servico"]):
            passos = "; ".join(f"{x['passo']}: {x['formula']} = {x['resultado']} {x['unidade']}".strip()
                               for x in calc["passos"] if x["segmento"] == q["segmento"])
            saida.append(evidencia(codigo=f"{base}.{q['item']}", servico=q["servico"], unidade=q["unidade"],
                                   valor=q["valor"], parcela=True, documento=DOCUMENTO,
                                   localizador=f"{p['id']} · {q['segmento']}", trecho=f"{q['descricao']} · {passos}"
                                   + (f" · alertas: {'; '.join(calc['alertas'])}" if calc["alertas"] else ""),
                                   metodo="associado", regra=f"calculo_vala.{q['servico']}"))
    return saida, sem_valor


def de_fatos(fatos) -> list[dict]:
    """Evidências dos serviços associados a fatos consolidados com valor (convergente, fonte única ou decidido).
    Fato em conflito não gera serviço associado: primeiro se resolve o conflito."""
    saida = []
    for regra in (r for r in REGRAS if "fato" in r["base"]):
        b = regra["base"]
        for f in fatos.to_dict("records") if len(fatos) else []:
            item = ".".join(f["codigo"].split(".")[2:])
            if (item, f["servico"], f["unidade"]) != (b["fato"], b["servico"], b["unidade"]) or f["valor"] is None \
                    or f["status"] not in ("convergente", "fonte única", "decidido"):
                continue
            resultado, contexto = calcular(regra, _variaveis(regra, None, None, f["valor"]))
            base = ".".join(f["codigo"].split(".")[:2])
            saida.append(_evidencia(regra, base, f"fato {f['codigo']} {f['valor']:g} {f['unidade']} ({f['status']})",
                                    contexto, resultado))
    return saida


def validar() -> list[str]:
    """Problemas das regras: id repetido, destino fora da EAP geral ou serviço não admitido, unidade desconhecida,
    fórmula que não avalia com as variáveis e premissas declaradas (valor 1 de teste)."""
    from . import eap, vocabulario
    itens, problemas = eap.itens(), []
    ids = [r["id"] for r in REGRAS]
    problemas += [f"regra repetida: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    for r in REGRAS:
        it = itens.get(r["destino"]["item"])
        if it is None:
            problemas.append(f"{r['id']}: destino {r['destino']['item']} fora da EAP geral")
        elif r["destino"]["servico"] and r["destino"]["servico"] not in it["servicos"]:
            problemas.append(f"{r['id']}: serviço {r['destino']['servico']} não admitido em {r['destino']['item']}")
        if r["unidade"] not in vocabulario.REGRAS["unidades"]:
            problemas.append(f"{r['id']}: unidade {r['unidade']} desconhecida")
        try:
            calcular(r, {k: 1.0 for k in r["variaveis"]})
        except (KeyError, ValueError, ZeroDivisionError) as erro:
            problemas.append(f"{r['id']}: fórmula não avalia ({erro})")
    return problemas
