"""Calibração de premissas pela evidência: o que a premissa teria de valer para reproduzir o observado.

    serviço associado (fórmula × premissa)  ─┐
                                             ├─► razão = observado / calculado ─► premissa implícita = p × razão
    fato do edital/planilha/IA conferida    ─┘

Só informa: **nunca sobrescreve** a premissa (`conceitos/servicos_associados.jsonl` e `dimensoes.json` não são
tocados). A proporção só vale quando a fórmula é **linear numa única premissa** (armadura = taxa × V; lastro =
A_fundo × e). A linearidade é testada de forma determinística, avaliando a fórmula de cada elemento com a premissa em
0, p/2, p e 2p (tolerância relativa `TOLERANCIA_LINEAR`); fórmula com `max`, `if` ou patamar não passa e fica
"não calibrável por proporção", sem número. O observado vem só de documentos que não são os próprios serviços
associados (senão a conferência seria circular): convergente ou fonte única, ou decisão; conflito não calibra.
"""

from __future__ import annotations

import pandas as pd

from . import associados
from .formulas import avaliar, premissa

TOLERANCIA_LINEAR = 1e-9  # relativa: f(2p) = 2 f(p), f(p/2) = f(p)/2 e f(0) = 0
TOLERANCIA_CONFERE = (
    0.05  # relativa: observado dentro de 5 % do calculado → a premissa confere
)
TOLERANCIA_FATO = (
    0.005  # agrupamento de afirmações do mesmo valor (igual à consolidação)
)
COLUNAS = [
    "codigo",
    "servico",
    "unidade",
    "regra",
    "premissa",
    "valor_premissa",
    "calculado",
    "observado",
    "razao",
    "premissa_implicita",
    "diferenca_pct",
    "situacao",
    "motivo",
    "documentos",
]
NAO_CALIBRAVEL = "não calibrável"


def _premissas_do_elemento(regra: dict, el: dict) -> dict:
    return {k: premissa(p, el["tipo"]) for k, p in regra.get("premissas", {}).items()}


def _valor_do_elemento(
    regra: dict, el: dict, nome: str | None = None, fator: float = 1.0
) -> float:
    """Valor da fórmula num elemento, com a premissa `nome` multiplicada por `fator`; 0 se a condição é falsa ou falta
    dimensão (o serviço não sai)."""
    premissas = _premissas_do_elemento(regra, el)
    try:
        if regra.get("condicao") and not avaliar(
            regra["condicao"], {**premissas, **el["dims"]}
        ):
            return 0.0
        if nome is not None:
            premissas[nome] = premissas[nome] * fator
        return float(avaliar(regra["formula"], {**premissas, **el["dims"]}))
    except KeyError:
        return 0.0


def _proporcional(regra: dict, el: dict, nome: str) -> bool:
    """A fórmula é linear em `nome` neste elemento: dobra com 2p, cai à metade com p/2 e dá 0 com p = 0."""
    v1 = _valor_do_elemento(regra, el, nome, 1.0)
    escala = max(abs(v1), 1e-12)
    for fator, esperado in ((2.0, 2 * v1), (0.5, v1 / 2), (0.0, 0.0)):
        if (
            abs(_valor_do_elemento(regra, el, nome, fator) - esperado)
            > TOLERANCIA_LINEAR * escala
        ):
            return False
    return True


def _numerica(regra: dict, elementos: list[dict], nome: str) -> bool:
    return all(
        isinstance(_premissas_do_elemento(regra, el).get(nome), (int, float))
        for el in elementos
    )


def _premissas_lineares(regra: dict, elementos: list[dict]) -> list[str]:
    return [
        nome
        for nome in regra.get("premissas", {})
        if _numerica(regra, elementos, nome)
        and all(_proporcional(regra, el, nome) for el in elementos)
    ]


def _sem_numero(motivo: str, calculado: float = 0.0, nome: str | None = None) -> dict:
    return {
        "premissa": nome,
        "valor_premissa": None,
        "calculado": calculado,
        "premissa_implicita": None,
        "motivo": motivo,
    }


def _escolher_premissa(
    regra: dict, elementos: list[dict]
) -> tuple[str | None, str | None]:
    """(nome da premissa calibrável, motivo de não haver): exatamente uma premissa em que a fórmula é linear."""
    if not regra.get("premissas"):
        return None, "regra sem premissa"
    lineares = _premissas_lineares(regra, elementos)
    if not lineares:
        return (
            None,
            "não calibrável por proporção: fórmula não é linear em nenhuma premissa (patamar, max ou if)",
        )
    if len(lineares) > 1:
        return (
            None,
            f"não calibrável por proporção: mais de uma premissa proporcional ({', '.join(lineares)})",
        )
    return lineares[0], None


def premissa_implicita(
    regra: dict, elementos: list[dict], valor_observado: float
) -> dict:
    """Valor da premissa que reproduziria `valor_observado` nos `elementos` aos quais a regra se aplica.

    Devolve {premissa, valor_premissa, calculado, premissa_implicita, motivo}. `valor_premissa` é a premissa em uso
    (média ponderada pelo calculado quando varia por tipo de elemento); `premissa_implicita = valor × observado /
    calculado`. Sem número (None) e com `motivo` quando a fórmula não é proporcional à premissa ou não há calculado."""
    elementos = [el for el in elementos if el["tipo"] in regra["tipos"]]
    calculos = [_valor_do_elemento(regra, el) for el in elementos]
    calculado = sum(calculos)
    nome, motivo = _escolher_premissa(regra, elementos)
    if nome is None:
        return _sem_numero(motivo, calculado)
    if calculado <= 0:
        return _sem_numero("sem valor calculado", calculado, nome)
    valor = (
        sum(
            _premissas_do_elemento(regra, el)[nome] * c
            for el, c in zip(elementos, calculos)
        )
        / calculado
    )
    return {
        "premissa": nome,
        "valor_premissa": valor,
        "calculado": calculado,
        "premissa_implicita": valor * valor_observado / calculado,
        "motivo": None,
    }


def _observado(fato: dict) -> tuple[float | None, str, list[str]] | None:
    """(valor, motivo, documentos) do fato sem contar os serviços associados (circular); None se nada de fora."""
    from .evidencias import _fonte, _grupos

    if fato.get("decisoes"):
        return (
            float(fato["decisoes"][-1]["valor"]),
            "",
            [f"decisão de {fato['decisoes'][-1]['autor']}"],
        )
    afirmacoes = [a for a in fato.get("afirmacoes") or [] if a["tipo"] != "associado"]
    if not afirmacoes:
        return None
    documentos = sorted({_fonte(a["documento"]) for a in afirmacoes})
    grupos = _grupos(afirmacoes, TOLERANCIA_FATO)
    if len(grupos) > 1:
        return None, "fato em conflito", documentos
    return float(grupos[0][0]["valor"]), "", documentos


def _situacao(r: dict, razao: float | None) -> str:
    if r["premissa_implicita"] is None or razao is None:
        return NAO_CALIBRAVEL
    return "confere" if abs(razao - 1) <= TOLERANCIA_CONFERE else "diverge"


def _motivo_do_grupo(ids: list[str], regras: dict) -> str | None:
    """Por que o grupo não calibra antes de olhar a fórmula: regra de fora do conceito ou várias no mesmo serviço."""
    if any(i not in regras for i in ids):
        return "regra fora de servicos_associados.jsonl"
    if len(ids) > 1:
        return f"várias regras no mesmo serviço ({'; '.join(ids)})"
    return None


def _linha(
    chave: tuple, ids: list[str], regras: dict, elementos: list[dict], observado: tuple
) -> dict:
    """Linha da tabela: uma regra calibra; mais de uma no mesmo serviço não se separa; observado nulo é conflito."""
    valor_observado, motivo_fato, documentos = observado
    linha = {
        "codigo": chave[0],
        "servico": chave[1],
        "unidade": chave[2],
        "regra": "; ".join(ids),
        "observado": valor_observado,
        "documentos": "; ".join(documentos),
        "razao": None,
        "diferenca_pct": None,
    }
    if valor_observado is None:
        return {**linha, **_sem_numero(motivo_fato), "situacao": NAO_CALIBRAVEL}
    r = _sem_numero(_motivo_do_grupo(ids, regras))
    if r["motivo"] is None:
        r = premissa_implicita(regras[ids[0]], elementos, valor_observado)
    calculado = r["calculado"]
    if calculado > 0:
        linha.update(
            razao=valor_observado / calculado,
            diferenca_pct=100 * (valor_observado - calculado) / calculado,
        )
    return {**linha, **r, "situacao": _situacao(r, linha["razao"])}


def _grupos_associados(evs_associados: list[dict]) -> dict[tuple, list[dict]]:
    grupos: dict[tuple, list[dict]] = {}
    for e in evs_associados:
        if e["metodo"] == "associado":
            grupos.setdefault((e["codigo"], e["servico"], e["unidade"]), []).append(e)
    return grupos


def _linha_do_grupo(
    chave: tuple, evs: list[dict], fato: dict, por_id: dict, regras: dict
) -> dict | None:
    observado = _observado(fato)
    if observado is None:
        return None
    ids = sorted({e["regra"] for e in evs})
    elementos = [
        el
        for i in dict.fromkeys(e["localizador"] for e in evs)
        for el in por_id.get(i, [])
    ]
    return _linha(chave, ids, regras, elementos, observado)


def tabela(
    evs_associados: list[dict], fatos: pd.DataFrame, elementos: list[dict]
) -> pd.DataFrame:
    """Premissa × observado por (código, serviço, unidade) de serviço associado que tem fato de fora com valor.

    Colunas em COLUNAS. Situação: `confere` (observado/calculado dentro de 5 %), `diverge` ou `não calibrável` (com
    `motivo`). Associado sem fato correspondente não entra. Nunca altera a premissa: só informa."""
    regras = {r["id"]: r for r in associados.REGRAS}
    por_id: dict[str, list[dict]] = {}
    for el in elementos:
        por_id.setdefault(el["id"], []).append(el)
    fatos_por_chave = (
        {(f["codigo"], f["servico"], f["unidade"]): f for f in fatos.to_dict("records")}
        if len(fatos)
        else {}
    )
    linhas = [
        linha
        for chave, evs in _grupos_associados(evs_associados).items()
        if chave in fatos_por_chave
        and (
            linha := _linha_do_grupo(chave, evs, fatos_por_chave[chave], por_id, regras)
        )
        is not None
    ]
    df = pd.DataFrame(linhas, columns=COLUNAS)
    return df.sort_values(["codigo", "servico", "unidade"], kind="stable").reset_index(
        drop=True
    )
