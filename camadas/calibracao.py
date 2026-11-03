"""Calibração de premissas pela evidência: o que a premissa teria de valer para reproduzir o observado.

    serviço associado (fórmula × premissa)  ─┐
                                             ├─► razão = observado / calculado ─► premissa implícita = p × razão
    fato do edital/planilha/IA conferida    ─┘

Só informa: **nunca sobrescreve** a premissa (`conceitos/servicos_associados.jsonl` e `dimensoes.json` não são
tocados). A proporção só vale quando a fórmula é **linear numa única premissa** (armadura = taxa × V; lastro =
A_fundo × e). A linearidade é testada de forma determinística, avaliando a fórmula de cada elemento com a premissa em
0, p/2, p e 2p (tolerância relativa `TOLERANCIA_LINEAR`); fórmula com `max`, `if` ou patamar não passa e fica
"não calibrável por proporção", sem número. Depois, a fórmula com a premissa implícita tem de reproduzir o observado.

Casamento: a tabela parte dos fatos. Um fato (código com ou sem `*`, serviço, unidade) casa com os associados de todos
os códigos que o padrão cobre (mesma regra de `evidencias._casa`), na mesma unidade depois de `vocabulario.converter`
(t → kg). O **calculado** é a soma das evidências associadas do grupo (o que a EAP mostra); o recálculo por elemento
serve para achar a premissa e a linearidade e tem de bater com essa soma. Os elementos vêm dos construtivos e
declarados (pelo par id + base, nunca só pelo id) e dos fatos (`dimensoes.de_fatos`); se ainda assim a soma não bate,
a linha fica `não calibrável`. O observado vem só de documentos que não são os próprios serviços associados (senão a
conferência seria circular): convergente ou fonte única, ou decisão; conflito não calibra.
"""

from __future__ import annotations

import math

import pandas as pd

from . import associados, dimensoes, vocabulario
from .formulas import avaliar, premissa

TOLERANCIA_LINEAR = 1e-9  # relativa: f(2p) = 2 f(p), f(p/2) = f(p)/2 e f(0) = 0
TOLERANCIA_CONFERE = 0.05  # relativa: observado dentro de 5 % do calculado → confere
TOLERANCIA_FATO = (
    0.005  # agrupamento de afirmações do mesmo valor (igual à consolidação)
)
TOLERANCIA_SOMA = 1e-6  # relativa (mais o arredondamento de 6 casas das evidências): recálculo × evidências
COLUNAS = [
    "codigo",
    "servico",
    "unidade",
    "regra",
    "premissa",
    "unidade_premissa",
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
ERROS_DE_CALCULO = (ZeroDivisionError, ValueError, OverflowError, TypeError)


def _premissas_do_elemento(regra: dict, el: dict) -> dict:
    return {k: premissa(p, el["tipo"]) for k, p in regra.get("premissas", {}).items()}


def _valor_do_elemento(
    regra: dict, el: dict, nome: str | None = None, fator: float = 1.0
) -> float:
    """Valor da fórmula num elemento, com a premissa `nome` multiplicada por `fator` (na condição também). 0 se a
    condição é falsa ou falta dimensão (o serviço não sai); NaN se a avaliação falha (divisão por zero, domínio)."""
    premissas = _premissas_do_elemento(regra, el)
    if nome is not None:
        premissas[nome] = premissas[nome] * fator
    contexto = {**premissas, **el["dims"]}
    try:
        if regra.get("condicao") and not avaliar(regra["condicao"], contexto):
            return 0.0
        return float(avaliar(regra["formula"], contexto))
    except KeyError:
        return 0.0
    except ERROS_DE_CALCULO:
        return math.nan


def _proporcional(regra: dict, el: dict, nome: str) -> bool:
    """A fórmula é linear em `nome` neste elemento: dobra com 2p, cai à metade com p/2 e dá 0 com p = 0."""
    v1 = _valor_do_elemento(regra, el, nome, 1.0)
    escala = max(abs(v1), 1e-12)
    for fator, esperado in ((2.0, 2 * v1), (0.5, v1 / 2), (0.0, 0.0)):
        v = _valor_do_elemento(regra, el, nome, fator)
        if not math.isfinite(v) or abs(v - esperado) > TOLERANCIA_LINEAR * escala:
            return False
    return math.isfinite(v1)


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


def _reproduz(
    regra: dict, elementos: list[dict], nome: str, razao: float, valor_observado: float
) -> bool:
    """A fórmula com a premissa multiplicada por `razao` dá o observado (pega teto como min(taxa × V, 300))."""
    total = sum(_valor_do_elemento(regra, el, nome, razao) for el in elementos)
    return math.isfinite(total) and abs(
        total - valor_observado
    ) <= TOLERANCIA_SOMA * max(abs(valor_observado), 1.0)


def premissa_implicita(
    regra: dict, elementos: list[dict], valor_observado: float
) -> dict:
    """Valor da premissa que reproduziria `valor_observado` nos `elementos` aos quais a regra se aplica.

    Devolve {premissa, valor_premissa, calculado, premissa_implicita, motivo}. `valor_premissa` é a premissa em uso
    (média ponderada pelo calculado quando varia por tipo de elemento); `premissa_implicita = valor × observado /
    calculado`, conferida reavaliando a fórmula. Sem número (None) e com `motivo` quando a fórmula não é proporcional
    à premissa, falha na avaliação, não reproduz o observado, não há calculado ou o observado não é positivo."""
    elementos = [el for el in elementos if el["tipo"] in regra["tipos"]]
    calculos = [_valor_do_elemento(regra, el) for el in elementos]
    calculado = sum(calculos)
    if not math.isfinite(calculado):
        return _sem_numero("erro na avaliação da fórmula", 0.0)
    nome, motivo = _escolher_premissa(regra, elementos)
    if nome is None:
        return _sem_numero(motivo, calculado)
    if calculado <= 0:
        return _sem_numero("sem valor calculado", calculado, nome)
    if valor_observado <= 0:
        return _sem_numero("observado não positivo", calculado, nome)
    razao = valor_observado / calculado
    if not _reproduz(regra, elementos, nome, razao, valor_observado):
        return _sem_numero("fórmula não reproduz o observado", calculado, nome)
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
        "premissa_implicita": valor * razao,
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


def _elementos_do_grupo(grupo: list[dict], por_id: dict) -> list[dict]:
    """Elementos que geraram as evidências do grupo: mesmo id e a base do código da evidência (id sozinho repete entre
    unidades e sistemas)."""
    achados = {}
    for e in grupo:
        for el in por_id.get(e["localizador"], []):
            if e["codigo"].startswith(el["base"] + "."):
                achados[id(el)] = el
    return list(achados.values())


def _soma_confere(recalculado: float, soma_nativa: float, n: int) -> bool:
    """Recálculo por elemento = soma das evidências (que carregam arredondamento de 6 casas cada uma)."""
    return (
        abs(recalculado - soma_nativa)
        <= TOLERANCIA_SOMA * max(abs(soma_nativa), 1.0) + 5e-7 * n
    )


def _calibrar(
    ids: list[str],
    grupo: list[dict],
    observado_nativo: float,
    por_id: dict,
    regras: dict,
) -> dict:
    """Resultado de `premissa_implicita` para o grupo, ou o motivo de não calibrar antes dela."""
    motivo = _motivo_do_grupo(ids, regras)
    if motivo:
        return _sem_numero(motivo)
    r = premissa_implicita(
        regras[ids[0]], _elementos_do_grupo(grupo, por_id), observado_nativo
    )
    soma_nativa = sum(e["valor"] for e in grupo)
    if not _soma_confere(r["calculado"], soma_nativa, len(grupo)):
        return _sem_numero(
            "parte do calculado vem de elemento sem premissa recalculável (de fatos/método)",
            0.0,
        )
    return r


def _linha(
    fato: dict, grupo: list[dict], observado: tuple, por_id: dict, regras: dict
) -> dict:
    """Linha da tabela de um fato e dos associados que ele cobre. O calculado é a soma das evidências do grupo."""
    valor, motivo_fato, documentos = observado
    ids = sorted({e["regra"] for e in grupo})
    convertidos = [vocabulario.converter(e["valor"], e["unidade"]) for e in grupo]
    calculado, unidade = sum(v for v, _ in convertidos), convertidos[0][1]
    observado_conv = (
        vocabulario.converter(valor, fato["unidade"])[0] if valor is not None else None
    )
    if observado_conv is None:
        r = _sem_numero(motivo_fato)
    else:
        soma_nativa = sum(e["valor"] for e in grupo)
        r = _calibrar(
            ids,
            grupo,
            observado_conv * soma_nativa / calculado
            if calculado > 0
            else observado_conv,
            por_id,
            regras,
        )
    ok = observado_conv is not None and calculado > 0
    razao = observado_conv / calculado if ok else None
    return {
        "codigo": fato["codigo"],
        "servico": fato["servico"],
        "unidade": unidade,
        "regra": "; ".join(ids),
        "unidade_premissa": regras[ids[0]]["premissas"][r["premissa"]].get(
            "unidade", ""
        )
        if r["premissa"]
        else "",
        "observado": observado_conv,
        "documentos": "; ".join(documentos),
        "razao": razao,
        "diferenca_pct": 100 * (observado_conv - calculado) / calculado if ok else None,
        **r,
        "calculado": calculado,
        "situacao": _situacao(r, razao),
    }


def _linha_do_fato(
    fato: dict, evs: list[dict], por_id: dict, regras: dict
) -> dict | None:
    from .evidencias import _casa

    observado = _observado(fato)
    if observado is None:
        return None
    unidade = vocabulario.converter(1.0, fato["unidade"])[1]
    grupo = [
        e
        for e in evs
        if e["servico"] == fato["servico"]
        and _casa(fato["codigo"], e["codigo"])
        and vocabulario.converter(1.0, e["unidade"])[1] == unidade
    ]
    return _linha(fato, grupo, observado, por_id, regras) if grupo else None


def _por_id(elementos: list[dict], fatos: pd.DataFrame) -> dict[str, list[dict]]:
    """Elementos por id: os dados e os que a consolidação dos fatos gera (`dimensoes.de_fatos`), sem repetir."""
    todos = {}
    for el in [*elementos, *(dimensoes.de_fatos(fatos) if len(fatos) else [])]:
        todos.setdefault((el["id"], el["base"], el.get("metodo")), el)
    por_id: dict[str, list[dict]] = {}
    for el in todos.values():
        por_id.setdefault(el["id"], []).append(el)
    return por_id


def tabela(
    evs_associados: list[dict], fatos: pd.DataFrame, elementos: list[dict]
) -> pd.DataFrame:
    """Premissa × observado por fato de fora com valor que cobre serviços associados (código, serviço, unidade).

    Colunas em COLUNAS. Situação: `confere` (observado/calculado dentro de 5 %), `diverge` ou `não calibrável` (com
    `motivo`). Associado sem fato correspondente não entra. Nunca altera a premissa: só informa."""
    regras = {r["id"]: r for r in associados.REGRAS}
    evs = [e for e in evs_associados if e["metodo"] == "associado"]
    por_id = _por_id(elementos, fatos)
    linhas = [
        linha
        for f in (fatos.to_dict("records") if len(fatos) else [])
        if (linha := _linha_do_fato(f, evs, por_id, regras)) is not None
    ]
    df = pd.DataFrame(linhas, columns=COLUNAS)
    return df.sort_values(["codigo", "servico", "unidade"], kind="stable").reset_index(
        drop=True
    )
