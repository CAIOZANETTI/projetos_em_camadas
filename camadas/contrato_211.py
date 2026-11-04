"""Linhas de serviço da aba CUSTO CIVIL da planilha do contrato Sanepar 211/2026, ligadas à EAP (sem preço).

    ler_custo_civil  = uma linha de serviço por dict, com a hierarquia unidade › UC › trecho › grupo e o projeto
    classificar      = acrescenta folha da EAP, regra, material, DN e estado (de-para `composicoes_sanepar.json`)
    resumo           = totais: linhas, declaradas, vazias e contagem por regra

**Sem preço.** A leitura toca só as colunas A a E (item, composição, descrição, unidade, quantidade) e I (projeto).
As colunas F e G (valor unitário e total), as abas de insumos e de composições nunca são abertas.

O de-para vive em `conceitos/composicoes_sanepar.json`, com o estado de cada regra (confirmado, premissa, calibrar).
Linha sem de-para recebe `regra="sem_regra"` e o `motivo`: nada é inventado.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import openpyxl

DE_PARA = json.loads(
    (
        Path(__file__).resolve().parent.parent
        / "conceitos"
        / "composicoes_sanepar.json"
    ).read_text(encoding="utf-8")
)

# serviços que a planilha escreve como título (sem unidade e sem composição), mas que se quantificam
_TITULO_SERVICO = re.compile(
    r"^(RECOMPOSICAO DE PAVIMENTO|BLOCOS? DE (APOIO|ANCORAGEM)|MEDIDORES? DE VAZ)"
)
_COLUNA_PROJETO = 9  # coluna I
_ULTIMA_COLUNA_DADOS = 5  # coluna E: F e G (valores) ficam de fora


def _sem_acento(texto: str) -> str:
    """Maiúsculas e sem acento, para comparar descrições."""
    base = unicodedata.normalize("NFD", texto.upper())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def _texto(valor) -> str:
    """Texto aparado de uma célula; inteiro vindo como float não ganha '.0'."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _numero(valor) -> float | None:
    """Quantidade numérica da célula, ou None se vazia ou não numérica."""
    if isinstance(valor, bool) or valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None


def _linhas_de_dados(xlsx, aba: str) -> list[tuple]:
    """(linha, A, B, C, D, E, I) de cada linha da aba, lendo só as colunas A–E e, à parte, a I."""
    livro = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    try:
        if aba not in livro.sheetnames:
            raise ValueError(f"aba {aba!r} não existe na planilha")
        ws = livro[aba]
        dados = ws.iter_rows(
            min_row=1, min_col=1, max_col=_ULTIMA_COLUNA_DADOS, values_only=True
        )
        projetos = ws.iter_rows(
            min_row=1,
            min_col=_COLUNA_PROJETO,
            max_col=_COLUNA_PROJETO,
            values_only=True,
        )
        saida = []
        for numero, (linha, projeto) in enumerate(
            zip(dados, projetos, strict=False), start=1
        ):
            a, b, c, d, e = (list(linha) + [None] * 5)[:5]
            saida.append((numero, a, b, c, d, e, projeto[0] if projeto else None))
        return saida
    finally:
        livro.close()


def ler_custo_civil(xlsx, aba: str = "CUSTO CIVIL") -> list[dict]:
    """Linhas de serviço da aba, cada uma com a sua hierarquia.

    Serviço é a linha com unidade em D (menos "SUBTOTAL:"), a linha de trecho (título em "M", sem composição) e os
    títulos que também se quantificam (recomposição de pavimento, blocos, medidores), com `titulo_servico=True`.
    Hierarquia: `unidade_obra` (A começa com UNIDADE), `uc` (A numérico e C texto), `trecho` (título em "M" sem
    composição), `grupo` (título sem composição e sem unidade; um trecho novo o zera). O `projeto` é o da própria
    linha ou o herdado do trecho ou do grupo, até o próximo trecho, grupo ou UC.
    """
    linhas = _linhas_de_dados(xlsx, aba)
    inicio = next(
        (n for n, a, *_ in linhas[:15] if _texto(a).upper() == "ITEM"),
        None,
    )
    if inicio is None:
        raise ValueError(
            "cabeçalho 'ITEM' não encontrado nas 15 primeiras linhas da aba"
        )

    unidade_obra = uc = grupo = trecho = None
    trecho_linha = None
    projeto_contexto = None
    servicos = []
    for numero, a, b, c, d, e, i in linhas:
        if numero <= inicio:
            continue
        item, composicao, descricao, unidade = (
            _texto(a),
            _texto(b),
            _texto(c),
            _texto(d),
        )
        projeto_proprio = _texto(i) or None
        if item.upper().startswith("UNIDADE"):
            unidade_obra, uc, grupo, trecho, trecho_linha = item, None, None, None, None
            projeto_contexto = None
            continue
        if re.fullmatch(r"\d+", item) and descricao:
            uc = f"UC {item} - {descricao}"
            grupo = trecho = trecho_linha = projeto_contexto = None
            continue
        if unidade.upper() == "SUBTOTAL:" or not (composicao or descricao or unidade):
            continue

        eh_trecho = not composicao and unidade.upper() == "M"
        titulo_servico = (
            not composicao
            and not unidade
            and bool(_TITULO_SERVICO.match(_sem_acento(descricao)))
        )
        eh_servico = bool(unidade) or bool(composicao) or titulo_servico
        if eh_trecho:
            trecho, trecho_linha, projeto_contexto = descricao, numero, projeto_proprio
            grupo = None  # o trecho abre uma seção nova: o grupo anterior não vale mais
        elif not eh_servico:  # título de grupo
            grupo, trecho, trecho_linha = descricao, None, None
            projeto_contexto = projeto_proprio
            continue
        servicos.append(
            {
                "aba": aba,
                "linha": numero,
                "unidade_obra": unidade_obra,
                "uc": uc,
                "trecho": trecho,
                "trecho_linha": trecho_linha,
                "grupo": grupo,
                "composicao": composicao or None,
                "descricao": descricao,
                "unidade": unidade or None,
                "quantidade_declarada": _numero(e),
                "projeto": projeto_proprio or projeto_contexto,
                "titulo_servico": titulo_servico,
                "eh_trecho": eh_trecho,
            }
        )
    return servicos


def _entrada_para_linha(linha: dict, de_para: dict) -> tuple[dict | None, dict]:
    """(entrada do de-para, campos extras: material e dn_mm) da linha, ou (None, {}) se não casar."""
    composicao = linha.get("composicao")
    if linha.get("eh_trecho"):
        return de_para["por_estrutura"]["titulo_de_trecho"], {}
    if composicao:
        if composicao in de_para["composicoes"]:
            return de_para["composicoes"][composicao], {}
        for padrao in de_para.get("padroes", []):
            achou = re.fullmatch(padrao["padrao"], composicao)
            if achou:
                return padrao, {
                    "material": padrao["materiais"][achou.group(1)],
                    "dn_mm": int(achou.group(2)),
                }
        return None, {}
    descricao = _sem_acento(linha.get("descricao") or "")
    for chave, entrada in de_para.get("por_descricao", {}).items():
        if descricao.startswith(chave):
            return entrada, {}
    return None, {}


def classificar(linhas: list[dict], de_para: dict | None = None) -> list[dict]:
    """Cópia das linhas com `folha_eap`, `regra`, `material`, `dn_mm`, `estado` (e `grandeza`, `motivo`).

    Linha sem de-para recebe `regra="sem_regra"` e o `motivo`; linha de `sem_regra` do próprio de-para leva o motivo
    escrito lá. `material` e `dn_mm` só existem nas composições por expressão (CVCA)."""
    de_para = DE_PARA if de_para is None else de_para
    saida = []
    for linha in linhas:
        entrada, extras = _entrada_para_linha(linha, de_para)
        nova = {**linha, "material": None, "dn_mm": None, **extras}
        if entrada is None:
            rotulo = linha.get("composicao") or linha.get("descricao")
            nova.update(
                folha_eap=None,
                regra="sem_regra",
                grandeza=None,
                estado=None,
                motivo=f"sem de-para para {rotulo!r} em composicoes_sanepar.json",
            )
        else:
            nova.update(
                folha_eap=entrada.get("folha_eap"),
                regra=entrada["regra"],
                grandeza=entrada.get("grandeza"),
                estado=entrada.get("estado"),
            )
            if entrada["regra"] == "sem_regra":
                nova["motivo"] = entrada.get("motivo", "regra não definida no de-para")
        saida.append(nova)
    return saida


def resumo(linhas: list[dict]) -> dict:
    """Totais: linhas, declaradas (com quantidade), vazias, títulos-serviço, por regra e linhas sem de-para."""
    por_regra: dict[str, int] = {}
    for linha in linhas:
        regra = linha.get("regra", "nao_classificada")
        por_regra[regra] = por_regra.get(regra, 0) + 1
    declaradas = sum(1 for linha in linhas if linha["quantidade_declarada"] is not None)
    return {
        "linhas": len(linhas),
        "declaradas": declaradas,
        "vazias": len(linhas) - declaradas,
        "com_unidade": sum(1 for linha in linhas if linha["unidade"]),
        "titulos_servico": sum(1 for linha in linhas if linha.get("titulo_servico")),
        "por_regra": dict(sorted(por_regra.items())),
        "sem_de_para": [
            {
                "linha": ln["linha"],
                "composicao": ln["composicao"],
                "descricao": ln["descricao"],
            }
            for ln in linhas
            if ln.get("regra") == "sem_regra"
            and ln.get("motivo", "").startswith("sem de-para")
        ],
    }


FUNCOES = ("ler_custo_civil", "classificar", "resumo", "metadados")


def metadados() -> dict:
    """Rastreabilidade do método e das premissas declaradas (regra 9 do estilo)."""
    meta = DE_PARA["metadata"]
    return {
        "modulo": "contrato_211",
        "descricao": "linhas de serviço da aba CUSTO CIVIL (colunas A–E e I, sem preço) ligadas à EAP padrão por "
        "composição",
        "funcoes": list(FUNCOES),
        "bibliografia": [],
        "premissas": [
            {
                "aplicacao": {"classificar": [f"composicoes.{codigo}"]},
                "fonte": meta["fonte"],
                "estado": entrada.get("estado", meta["estado"]),
            }
            for codigo, entrada in DE_PARA["composicoes"].items()
        ]
        + [
            {
                "aplicacao": {"classificar": [f"por_descricao.{chave}"]},
                "fonte": meta["fonte"],
                "estado": entrada.get("estado", meta["estado"]),
            }
            for chave, entrada in DE_PARA["por_descricao"].items()
        ],
        "ultima_revisao": meta["data_referencia"],
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m camadas.contrato_211 PLANILHA.xlsx` imprime o resumo da classificação."""
    argumentos = sys.argv[1:] if argv is None else argv
    if len(argumentos) != 1:
        print("uso: python -m camadas.contrato_211 PLANILHA.xlsx", file=sys.stderr)
        return 2
    linhas = classificar(ler_custo_civil(argumentos[0]))
    print(json.dumps(resumo(linhas), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
