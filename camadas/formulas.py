"""Fórmulas declaradas nos conceitos: avaliador restrito e premissas com fonte.

    avaliar("A * e_lastro", {"A": 16, "e_lastro": 0.05})            → 0.8
    avaliar("V_env if flexivel == 1 else 0", {...})                 condicional
    premissa({"ref": "valas.json#berco_m.valor"})                   → valor de outro conceito

Só números, textos (para comparar), variáveis, + − × ÷ **, comparações, and/or/not, `a if c else b`, max, min, pi.
Nenhum código arbitrário roda: o que não está na lista levanta ValueError; variável que falta levanta KeyError.
"""
from __future__ import annotations

import ast
import json
import math
import operator

from .pdf_cad import CONCEITOS

BINARIOS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
            ast.Pow: operator.pow}
UNARIOS = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}
COMPARA = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt,
           ast.GtE: operator.ge}
FUNCOES = {"max": max, "min": min}


def _no(n, valores: dict):
    if isinstance(n, ast.Expression):
        return _no(n.body, valores)
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float, str)) and not isinstance(n.value, bool):
        return float(n.value) if isinstance(n.value, (int, float)) else n.value
    if isinstance(n, ast.Name):
        if n.id == "pi":
            return math.pi
        if n.id not in valores:
            raise KeyError(n.id)
        v = valores[n.id]
        return v if isinstance(v, str) else float(v)
    if isinstance(n, ast.BinOp) and type(n.op) in BINARIOS:
        return BINARIOS[type(n.op)](_no(n.left, valores), _no(n.right, valores))
    if isinstance(n, ast.UnaryOp) and type(n.op) in UNARIOS:
        return UNARIOS[type(n.op)](_no(n.operand, valores))
    if isinstance(n, ast.Compare) and all(type(o) in COMPARA for o in n.ops):
        esquerda, ok = _no(n.left, valores), True
        for op, direita in zip(n.ops, n.comparators):
            d = _no(direita, valores)
            ok, esquerda = ok and COMPARA[type(op)](esquerda, d), d
        return ok
    if isinstance(n, ast.BoolOp):
        vals = (_no(v, valores) for v in n.values)
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.IfExp):
        return _no(n.body, valores) if _no(n.test, valores) else _no(n.orelse, valores)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCOES and not n.keywords:
        return FUNCOES[n.func.id](*(_no(a, valores) for a in n.args))
    raise ValueError(f"expressão não permitida: {ast.dump(n)}")


def avaliar(expressao: str, valores: dict):
    """Valor de uma fórmula (número, ou bool numa condição) com as variáveis de `valores`."""
    return _no(ast.parse(expressao, mode="eval"), valores)


def conferir(expressao: str) -> str | None:
    """Problema de uma fórmula do conceito sem avaliá-la (sintaxe ou construção fora da lista); None se está boa."""
    permitidos = (ast.Expression, ast.Constant, ast.Name, ast.Load, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
                  ast.IfExp, ast.Call, ast.And, ast.Or, *BINARIOS, *UNARIOS, *COMPARA)
    try:
        arvore = ast.parse(expressao, mode="eval")
    except SyntaxError as erro:
        return f"sintaxe: {erro.msg}"
    for n in ast.walk(arvore):
        if not isinstance(n, permitidos) or (isinstance(n, ast.Call) and getattr(n.func, "id", None) not in FUNCOES):
            return f"construção não permitida: {type(n).__name__}"
    return None


def nomes(expressao: str) -> list[str]:
    """Variáveis citadas numa fórmula, na ordem em que aparecem (sem pi e sem funções)."""
    arvore = ast.parse(expressao, mode="eval")
    funcoes = {n.func.id for n in ast.walk(arvore) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    return list(dict.fromkeys(n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)
                              and n.id != "pi" and n.id not in funcoes))


def premissa(p: dict, tipo: str | None = None):
    """Valor da premissa: `valor` (ou `valor[tipo]` quando é tabela por tipo de elemento) ou referência
    'arquivo.json#chave.subchave' a outro conceito."""
    if "ref" in p:
        arquivo, caminho = p["ref"].split("#")
        dado = json.loads((CONCEITOS / arquivo).read_text(encoding="utf-8"))
        for chave in caminho.split("."):
            dado = dado[chave]
        return dado
    v = p["valor"]
    return v[tipo] if isinstance(v, dict) and tipo in v else v
