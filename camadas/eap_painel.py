"""Painel da aba EAP: árvore codificada com quantidades, fatos e serviços associados, tudo em texto pt-BR.

O Python soma, ordena, conta e formata (`1.234,56`); o template só lê `dados["eap_painel"]`.
Entradas: `dados["eap"]` (EAP codificada, `camadas.eap.montar`) e `dados["evidencias"]` (`camadas.evidencias.etapa`).
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


POS_DISCIPLINA = eap.NIVEIS.index(
    "disciplina"
)  # segmento da disciplina no código (U1.A.GEO.FUN.EST → 2)
POS_PACOTE = eap.NIVEIS.index("pacote")


def subgrupos_do_codigo(codigo: str) -> list[str]:
    """Subgrupos de prancha (`conceitos/disciplinas.json`) que são evidência do nó, em ordem alfabética, pela chave
    `pranchas` de `eap.json` (subgrupo → pacotes 'DISC.PAC'). Nó de disciplina: subgrupos com algum pacote da
    disciplina; nó de pacote ou item: subgrupos que contêm o pacote. Acima da disciplina (unidade, sistema): vazio."""
    partes = codigo.split(".")
    if len(partes) <= POS_DISCIPLINA:
        return []
    disciplina = partes[POS_DISCIPLINA]
    if len(partes) == POS_DISCIPLINA + 1:
        casa = lambda pacote: pacote.startswith(disciplina + ".")
    else:
        alvo = f"{disciplina}.{partes[POS_PACOTE]}"
        casa = lambda pacote: pacote == alvo
    return sorted(
        (
            sub
            for sub, pacotes in eap.REGRAS["pranchas"].items()
            if any(map(casa, pacotes))
        ),
        key=str.casefold,
    )


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


SEM_EVIDENCIA = "sem evidência"
STATUS_CONFIRMADOS = {"convergente", "decidido"}


def _casa(fato: tuple[str, ...], outro: tuple[str, ...]) -> bool:
    """Casa segmento a segmento (`*` do fato casa qualquer segmento); `outro` precisa ter o nível do fato ou mais."""
    return len(outro) >= len(fato) and all(f in ("*", o) for f, o in zip(fato, outro))


def _fato_cobre_no(codigo_fato: str, codigo_no: str) -> bool:
    """O fato vale para o nó quando casa segmento a segmento com o código do nó: `*` casa qualquer segmento e o fato
    precisa ser do nível do nó ou mais profundo (fato de item vale para o item e para os ancestrais, não para os filhos)."""
    fato, no = tuple(codigo_fato.split(".")), tuple(codigo_no.split("."))
    return len(fato) >= len(no) and all(f in ("*", n) for f, n in zip(fato, no))


def _indexar_fatos(lista_fatos: list[dict]) -> dict[str, list[tuple]]:
    """Fatos com o código já dividido, agrupados pelo primeiro segmento (a unidade); `*` na unidade vale em todos os grupos
    e fica em `"*"`. Cada item é (segmentos, status, tem_curinga)."""
    indice: dict[str, list[tuple]] = {}
    for f in lista_fatos:
        partes = tuple(str(f["codigo"]).split("."))
        indice.setdefault(partes[0], []).append((partes, f["status"], "*" in partes))
    return indice


def _codigos_sob_no(quantidades: list[dict]) -> dict[str, list[tuple[str, ...]]]:
    """Por nó, os códigos (divididos, sem repetir) das quantidades que estão sob ele."""
    sob: dict[str, dict[tuple[str, ...], None]] = {}
    for codigo in dict.fromkeys(q["codigo"] for q in quantidades):
        partes = tuple(codigo.split("."))
        for no in _prefixos(codigo):
            sob.setdefault(no, {})[partes] = None
    return {no: list(v) for no, v in sob.items()}


def _cobre(fato: tuple, no: tuple[str, ...], sob_no: list[tuple[str, ...]]) -> bool:
    """Fato sem `*`: regra do nó. Fato com `*` só cobre o nó se houver, sob ele, alguma quantidade cujo código case com o
    fato (o curinga não contamina sistema que não tem o item)."""
    partes, _, curinga = fato
    if len(partes) < len(no) or not all(f in ("*", n) for f, n in zip(partes, no)):
        return False
    return not curinga or any(_casa(partes, q) for q in sob_no)


def status_do_no(
    codigo_no: str,
    indice_fatos: dict[str, list[tuple]],
    codigos_sob_no: list[tuple[str, ...]],
) -> dict:
    """Status agregado dos fatos que cobrem o nó: conflito > fonte única (inclui só menção e status desconhecido) >
    convergente (inclui decidido); sem fato, "sem evidência". Devolve `n_fatos`, `n_conflitos` e `selo_title`
    (texto do selo, com o plural certo)."""
    no = tuple(codigo_no.split("."))
    candidatos = indice_fatos.get(no[0], []) + indice_fatos.get("*", [])
    status = [f[1] for f in candidatos if _cobre(f, no, codigos_sob_no)]
    n_conflitos = status.count("conflito")
    if not status:
        agregado = SEM_EVIDENCIA
    elif n_conflitos:
        agregado = "conflito"
    elif any(s not in STATUS_CONFIRMADOS for s in status):
        agregado = "fonte única"
    else:
        agregado = "convergente"
    n = len(status)
    return {
        "status_no": agregado,
        "n_fatos": n,
        "n_conflitos": n_conflitos,
        "selo_title": f"{n} {'fato' if n == 1 else 'fatos'} · {n_conflitos} em conflito",
    }


def arvore(
    eap_codificada: dict | None, lista_fatos: list[dict] | None = None
) -> list[dict]:
    """Um nó por item de `eap_codificada["nos"]`: quantidades somadas, elementos do nó e dos descendentes e o status
    agregado dos `lista_fatos` brutos (`evidencias["fatos"]`) que cobrem o nó."""
    if not eap_codificada:
        return []
    quantidades = eap_codificada.get("quantidades") or []
    indice_fatos = _indexar_fatos(lista_fatos or [])
    sob_no = _codigos_sob_no(quantidades)
    grupos, elementos = _grupos_do_no(quantidades), _elementos_do_no(quantidades)
    saida = []
    for no in eap_codificada.get("nos") or []:
        subgrupos = subgrupos_do_codigo(no["codigo"])
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
                "subgrupos_mapa": subgrupos,
                "pranchas_txt": f"Pranchas: {', '.join(subgrupos)}"
                if subgrupos
                else "",
                **status_do_no(
                    no["codigo"], indice_fatos, sob_no.get(no["codigo"], [])
                ),
                "rotulo_vista": f"Vista: {no['codigo']} · {no['nome']} ({len(ids)} {'elemento' if len(ids) == 1 else 'elementos'})",
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
        "decisoes_txt": [
            f"{_com_unidade(d.get('valor'), unidade)} — {d.get('autor', '')}: {d.get('justificativa', '')}"
            for d in f.get("decisoes") or []
        ],
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
    fatos_brutos = (evidencias_obra or {}).get("fatos")
    lista_fatos = fatos(fatos_brutos)
    lista_associados = associados((evidencias_obra or {}).get("associados"))
    return {
        "arvore": arvore(eap_codificada, fatos_brutos),
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
        "funcoes": [
            "subgrupos_do_codigo",
            "status_do_no",
            "arvore",
            "fatos",
            "associados",
            "resumo",
            "montar",
            "metadados",
        ],
        "formato_numero": "vírgula decimal e ponto de milhar",
        "ordem_status": ORDEM_STATUS,
        "contrato": "dados['eap_painel'] = {arvore, fatos, associados, resumo}; dados['eap'] (gavetas) é outra chave",
    }
