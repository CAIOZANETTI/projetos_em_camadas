"""Painel da aba EAP: árvore codificada com quantidades, fatos e serviços associados, tudo em texto pt-BR.

O Python soma, ordena, conta e formata (`1.234,56`); o template só lê `dados["eap_painel"]`.
Entradas: `dados["eap_codificada"]` (`camadas.eap.montar`) e `dados["evidencias"]` (`camadas.evidencias.etapa`).
"""

from __future__ import annotations

import pandas as pd

from . import eap, evidencias
from .eap_html import br

LIMITE_TRECHO = 200
ORDEM_STATUS = [
    "conflito",
    "só menção",
    "fonte única",
    "convergente",
    "decidido",
]  # o que pede atenção primeiro
NAO_CITADO = "não citado no edital"
NOMES_SERVICO = {s["id"]: s["nome"] for s in evidencias.SERVICOS}


def _numero(valor, unidade: str | None) -> str:
    """Número formatado; contagem (`un`) sem casas decimais."""
    return br(valor, 0 if unidade == "un" else 2)


def _com_unidade(valor, unidade: str | None) -> str:
    """'345,60 m³'; sem valor (só menção, conflito) vira '—'."""
    if valor is None:
        return "—"
    return f"{_numero(valor, unidade)} {unidade}".rstrip()


def _prefixos(codigo: str) -> list[str]:
    """Códigos dos nós que contêm o item: 'U1.A.GEO.FUN.EST' → 'U1', 'U1.A', 'U1.A.GEO', 'U1.A.GEO.FUN', e ele mesmo."""
    partes = codigo.split(".")
    return [".".join(partes[:k]) for k in range(1, len(partes) + 1)]


def _grupos_do_no(quantidades: list[dict]) -> dict[str, list[dict]]:
    """Por nó, as quantidades somadas por tipo de item, grandeza e unidade (nunca se misturam: `eap.consolidar`)."""
    if not quantidades:
        return {}
    quant = pd.DataFrame(quantidades)
    soma = pd.concat(
        [eap.consolidar(quant, nivel) for nivel in eap.NIVEIS], ignore_index=True
    )
    grupos: dict[str, list[dict]] = {}
    for linha in soma.to_dict("records"):
        grupos.setdefault(linha["no"], []).append(linha)
    return grupos


def _elementos_do_no(quantidades: list[dict]) -> dict[str, list[str]]:
    """Por nó, os ids dos elementos construtivos cujo código EAP começa pelo código do nó (sem repetir, na ordem)."""
    ids: dict[str, dict[str, None]] = {}
    for q in quantidades:
        for no in _prefixos(q["codigo"]):
            ids.setdefault(no, {}).update(
                dict.fromkeys(map(str, q.get("evidencias") or []))
            )
    return {no: list(v) for no, v in ids.items()}


def _texto_quantidade(grupo: dict, nivel: str) -> str:
    """'12 un' · '16,00 m² (área em planta)'; acima do item, o código do item diz de que tipo é a quantidade."""
    texto = _com_unidade(grupo["quantidade"], grupo["unidade"])
    if grupo["grandeza"] != "quantidade":
        texto += f" ({grupo['grandeza']})"
    return texto if nivel == "item" else f"{texto} · {grupo['item']}"


def arvore(eap_codificada: dict | None) -> list[dict]:
    """Um nó por item de `eap_codificada["nos"]`, com as quantidades somadas e os elementos do nó e dos descendentes."""
    if not eap_codificada:
        return []
    quantidades = eap_codificada.get("quantidades") or []
    grupos, elementos = _grupos_do_no(quantidades), _elementos_do_no(quantidades)
    saida = []
    for no in eap_codificada.get("nos") or []:
        ids = elementos.get(no["codigo"], [])
        saida.append(
            {
                "codigo": no["codigo"],
                "numero": no["numero"],
                "nivel": no["nivel"],
                "nome": no["nome"],
                "pai": no["pai"],
                "quantidades_txt": [
                    _texto_quantidade(g, no["nivel"])
                    for g in grupos.get(no["codigo"], [])
                ],
                "elementos": ids,
                "n_elementos": len(ids),
            }
        )
    return saida


def _trecho(trechos: list | None) -> str:
    """Primeiro trecho da evidência, cortado em ~200 caracteres."""
    texto = str((trechos or [""])[0] or "")
    return (
        texto
        if len(texto) <= LIMITE_TRECHO
        else texto[: LIMITE_TRECHO - 1].rstrip() + "…"
    )


def _fato(f: dict) -> dict:
    unidade = f.get("unidade")
    pct = f.get("diferenca_pct")
    return {
        "codigo": f["codigo"],
        "servico_txt": NOMES_SERVICO.get(f.get("servico"), f.get("servico")) or "—",
        "unidade": unidade,
        "status": f["status"],
        "valor_txt": _com_unidade(f.get("valor"), unidade),
        "forca": f.get("forca"),
        "diferenca_txt": f"{br(pct, 1)} %" if pct else "",
        "afirmacoes": [
            {
                "documento": a["documento"],
                "tipo": a.get("tipo", ""),
                "valor_txt": _com_unidade(a.get("valor"), unidade),
                "trecho": _trecho(a.get("trechos")),
            }
            for a in f.get("afirmacoes") or []
        ],
        "mencoes": f.get("mencoes") or [],
        "decisoes": f.get("decisoes") or [],
    }


def fatos(lista: list[dict] | None) -> list[dict]:
    """Fatos formatados, com os conflitos primeiro; dentro do mesmo status mantém a ordem de entrada."""
    posicao = {s: k for k, s in enumerate(ORDEM_STATUS)}
    return sorted(
        map(_fato, lista or []),
        key=lambda f: posicao.get(f["status"], len(ORDEM_STATUS)),
    )


def associados(lista: list[dict] | None) -> list[dict]:
    """Serviços associados × edital com a quantidade formatada; `destaque` marca o que o edital não cita."""
    return [
        {
            "unidade": a["unidade"],
            "item": a["item"],
            "servico": NOMES_SERVICO.get(a["servico"], a["servico"]) or "—",
            "unidade_medida": a["unidade_medida"],
            "quantidade_txt": _numero(a["quantidade"], a["unidade_medida"]),
            "situacao": a["situacao"],
            "destaque": str(a["situacao"]).startswith(NAO_CITADO),
        }
        for a in lista or []
    ]


def resumo(fatos_formatados: list[dict], associados_formatados: list[dict]) -> dict:
    """Contagem de fatos por status (todos os status, na ordem de atenção) e de associados não citados no edital."""
    n_por_status = pd.Series(
        [f["status"] for f in fatos_formatados], dtype=object
    ).value_counts()
    return {
        "fatos": len(fatos_formatados),
        "por_status": [
            {"status": s, "n": int(n_por_status.get(s, 0))} for s in ORDEM_STATUS
        ],
        "associados": len(associados_formatados),
        "nao_citados": sum(a["destaque"] for a in associados_formatados),
    }


def montar(eap_codificada: dict | None, evidencias_obra: dict | None) -> dict | None:
    """`dados["eap_painel"]`: {arvore, fatos, associados, resumo}; None quando não há EAP nem evidências."""
    if eap_codificada is None and evidencias_obra is None:
        return None
    lista_fatos = fatos((evidencias_obra or {}).get("fatos"))
    lista_associados = associados((evidencias_obra or {}).get("associados"))
    return {
        "arvore": arvore(eap_codificada),
        "fatos": lista_fatos,
        "associados": lista_associados,
        "resumo": resumo(lista_fatos, lista_associados),
    }


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "eap_painel",
        "descricao": "painel da aba EAP: árvore codificada com quantidades somadas por nó, fatos com afirmações e serviços "
        "associados × edital, formatados em português do Brasil",
        "funcoes": ["arvore", "fatos", "associados", "resumo", "montar", "metadados"],
        "formato_numero": "vírgula decimal e ponto de milhar",
        "ordem_status": ORDEM_STATUS,
        "contrato": "dados['eap_painel'] = {arvore, fatos, associados, resumo}; dados['eap'] (gavetas) é outra chave",
    }
