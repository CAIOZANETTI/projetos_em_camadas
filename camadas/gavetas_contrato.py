"""Planilha do contrato → gavetas (F2 da reconstrução): itens da CUSTO CIVIL e da Relação de Materiais, sem preço.

Cada função devolve uma base `{gaveta: [registros]}` (contrato em `conceitos/gavetas.json`). Só entram as colunas de
identificação e quantidade: a CUSTO CIVIL pelo leitor `contrato_211` (colunas A–E e I) e a Relação de Materiais pelo
leitor daqui, que lê cada coluna nomeada (sequência de estoque, descrição, unidade, quantidades das etapas) e nenhuma
outra. Valor, fornecedor, marca e as demais abas nunca são abertos. Quantidade vazia não vira fato: vira pendência
(a F4 calcula).

    python -m camadas.gavetas_contrato exemplos/foz/obra.json
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import openpyxl

from . import contrato_211, gavetas
from . import orcamento_sanepar as orc

ABA_CONTRATO = "CUSTO CIVIL"
ABA_MATERIAIS = "Relação de Materiais"
METODO_CONTRATO = "camadas.contrato_211"
METODO_MATERIAIS = "camadas.gavetas_contrato"
PROPRIEDADES_CONTRATO = (
    "composicao",
    "descricao",
    "unidade_medida",
    "folha_eap",
    "trecho",
    "uc",
    "dn_mm",
    "material",
)


def _base_vazia() -> dict:
    return {gaveta: [] for gaveta in gavetas.GAVETAS}


def _vazio(valor) -> bool:
    return valor is None or (isinstance(valor, str) and not valor.strip())


def _fato(objeto_id: str, propriedade: str, valor, evidencia_id: str) -> dict:
    return {
        "fato_id": f"{objeto_id}.{propriedade}",
        "objeto_id": objeto_id,
        "propriedade": propriedade,
        "valor": valor,
        "natureza": "projetado",
        "evidencia_id": evidencia_id,
    }


def _evidencia(
    objeto_id: str, documento_id: str, aba: str, linha: int, metodo: str, trecho=None
) -> dict:
    evidencia = {
        "evidencia_id": f"EV-{objeto_id}",
        "classe": "planilha",
        "documento": documento_id,
        "localizador": {"aba": aba, "linha": linha},
        "metodo": metodo,
        "executor": "código",
    }
    if trecho:
        evidencia["trecho"] = trecho
    return evidencia


def de_contrato(planilha: Path, documento_id: str) -> dict:
    """Linhas de serviço da CUSTO CIVIL → objetos `item_contrato` `c211-<aba>-<linha>`, fatos e evidência (aba e linha).

    `quantidade` só existe quando a planilha a declara; senão a linha vira pendência "quantidade a calcular (F4)".
    `folha_eap`, `dn_mm` e `material` vêm do de-para `composicoes_sanepar.json`, quando ele casa."""
    base = _base_vazia()
    for linha in contrato_211.classificar(
        contrato_211.ler_custo_civil(planilha, ABA_CONTRATO)
    ):
        objeto_id = contrato_211._id_da_linha(linha["aba"], linha["linha"])
        base["objetos"].append({"objeto_id": objeto_id, "classe": "item_contrato"})
        evidencia = _evidencia(
            objeto_id,
            documento_id,
            linha["aba"],
            linha["linha"],
            METODO_CONTRATO,
            linha.get("trecho"),
        )
        base["evidencias"].append(evidencia)
        valores = {**linha, "unidade_medida": linha.get("unidade")}
        for propriedade in PROPRIEDADES_CONTRATO:
            if not _vazio(valores.get(propriedade)):
                base["fatos"].append(
                    _fato(
                        objeto_id,
                        propriedade,
                        valores[propriedade],
                        evidencia["evidencia_id"],
                    )
                )
        if linha["quantidade_declarada"] is not None:
            base["fatos"].append(
                _fato(
                    objeto_id,
                    "quantidade",
                    linha["quantidade_declarada"],
                    evidencia["evidencia_id"],
                )
            )
        else:
            base["pendencias"].append(
                {"objeto_id": objeto_id, "motivo": "quantidade a calcular (F4)"}
            )
    return base


def _normalizar(texto) -> str:
    """Minúsculas, sem acento e sem ordinal (1ª → 1a), espaços simples: para comparar cabeçalhos."""
    base = unicodedata.normalize("NFKD", str(texto or "")).lower()
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", base).strip()


def _colunas_da_relacao(cabecalho: tuple) -> dict:
    """{campo: índice da coluna (1 a n)} pelos nomes do cabeçalho; só os campos de identificação e quantidade."""
    achados = {}
    for indice, celula in enumerate(cabecalho, start=1):
        nome = _normalizar(celula)
        if nome.startswith("sequencia de estoque"):
            achados.setdefault("codigo", indice)
        elif nome == "descricao":
            achados.setdefault("descricao", indice)
        elif nome == "unidade":
            achados.setdefault("unidade", indice)
        elif nome.startswith("quantidade") and "1a etapa" in nome:
            achados.setdefault("etapa1", indice)
        elif nome.startswith("quantidade") and "2a etapa" in nome:
            achados.setdefault("etapa2", indice)
    faltam = [
        c
        for c in ("codigo", "descricao", "unidade", "etapa1", "etapa2")
        if c not in achados
    ]
    if faltam:
        raise ValueError(f"aba {ABA_MATERIAIS!r}: cabeçalho sem as colunas {faltam}")
    return achados


def ler_relacao(planilha: Path) -> list[dict]:
    """Itens da aba 'Relação de Materiais': `linha`, `codigo`, `descricao`, `unidade`, `qtd_etapa1`, `qtd_etapa2` (texto
    não numérico em `texto_etapa1`/`texto_etapa2`). Lê a linha do cabeçalho e depois uma coluna de cada vez, só as
    nomeadas; as demais colunas (valor, marca, fornecedor) nunca são pedidas ao arquivo."""
    livro = openpyxl.load_workbook(planilha, read_only=True, data_only=True)
    try:
        if ABA_MATERIAIS not in livro.sheetnames:
            raise ValueError(f"aba {ABA_MATERIAIS!r} não existe na planilha")
        ws = livro[ABA_MATERIAIS]
        cabecalho = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
        colunas = _colunas_da_relacao(cabecalho)
        lidas = {
            campo: [
                linha[0]
                for linha in ws.iter_rows(
                    min_row=2, min_col=indice, max_col=indice, values_only=True
                )
            ]
            for campo, indice in colunas.items()
        }
    finally:
        livro.close()
    itens = []
    for n in range(max((len(v) for v in lidas.values()), default=0)):
        celula = {
            campo: (valores[n] if n < len(valores) else None)
            for campo, valores in lidas.items()
        }
        if all(_vazio(v) for v in celula.values()):
            continue
        item = {
            "linha": n + 2,
            "codigo": orc.txt(celula["codigo"]),
            "descricao": orc.txt(celula["descricao"]),
            "unidade": orc.txt(celula["unidade"]),
        }
        for etapa in ("etapa1", "etapa2"):
            numero = orc.num(celula[etapa])
            item[f"qtd_{etapa}"] = numero
            item[f"texto_{etapa}"] = orc.txt(celula[etapa]) if numero is None else ""
        itens.append(item)
    return itens


def de_materiais(planilha: Path, documento_id: str) -> dict:
    """Itens da Relação de Materiais → objetos `item_material` `rel-<linha>`, fatos e evidência (aba e linha).

    Quantidade de etapa só vira fato quando é número; vazia ou em texto vira pendência. `dn_mm` só quando a descrição
    traz `DN <n>` (extrator `orcamento_sanepar.extrair_dn`)."""
    base = _base_vazia()
    for item in ler_relacao(planilha):
        objeto_id = f"rel-{item['linha']}"
        base["objetos"].append({"objeto_id": objeto_id, "classe": "item_material"})
        evidencia = _evidencia(
            objeto_id, documento_id, ABA_MATERIAIS, item["linha"], METODO_MATERIAIS
        )
        base["evidencias"].append(evidencia)
        dn_mm, tipo, _ = orc.extrair_dn(item["descricao"])
        valores = {
            "codigo_material": item["codigo"],
            "descricao": item["descricao"],
            "unidade_medida": item["unidade"],
            "quantidade_etapa1": item["qtd_etapa1"],
            "quantidade_etapa2": item["qtd_etapa2"],
            "dn_mm": dn_mm if tipo == "DN" else None,
        }
        for propriedade, valor in valores.items():
            if not _vazio(valor):
                base["fatos"].append(
                    _fato(objeto_id, propriedade, valor, evidencia["evidencia_id"])
                )
        for etapa in ("etapa1", "etapa2"):
            if item[f"texto_{etapa}"]:
                base["pendencias"].append(
                    {
                        "objeto_id": objeto_id,
                        "motivo": f"quantidade da {etapa[-1]}ª etapa não numérica",
                    }
                )
        if item["qtd_etapa1"] is None and item["qtd_etapa2"] is None:
            base["pendencias"].append(
                {"objeto_id": objeto_id, "motivo": "sem quantidade em nenhuma etapa"}
            )
    return base


def resumo(base: dict) -> dict:
    """Contagens da base: objetos por classe, fatos por propriedade, evidências e pendências por motivo."""
    return {
        "objetos_por_classe": dict(
            sorted(Counter(o["classe"] for o in base["objetos"]).items())
        ),
        "fatos_por_propriedade": dict(
            sorted(Counter(f["propriedade"] for f in base["fatos"]).items())
        ),
        "evidencias": len(base["evidencias"]),
        "pendencias_por_motivo": dict(
            sorted(Counter(p["motivo"] for p in base["pendencias"]).items())
        ),
    }


def juntar(*bases: dict) -> dict:
    """Concatena as gavetas de várias bases."""
    return {
        gaveta: [r for b in bases for r in b.get(gaveta, [])]
        for gaveta in gavetas.GAVETAS
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: lê a planilha de `cfg["obras_lineares"]["planilha"]`, monta as duas bases, confere e imprime o resumo."""
    argumentos = sys.argv[1:] if argv is None else argv
    if len(argumentos) != 1:
        print("uso: python -m camadas.gavetas_contrato OBRA.json", file=sys.stderr)
        return 2
    cfg = json.loads(Path(argumentos[0]).read_text(encoding="utf-8"))
    planilha = Path(cfg["obras_lineares"]["planilha"])
    documento_id = gavetas.id_documento(planilha)
    contrato, materiais = (
        de_contrato(planilha, documento_id),
        de_materiais(planilha, documento_id),
    )
    base = juntar(contrato, materiais)
    base["documentos"].append(
        {
            "documento_id": documento_id,
            "arquivo": planilha.name,
            "sha256": documento_id,
            "extensao": planilha.suffix,
            "classe": "planilha",
            "paginas": 1,
        }
    )
    erros = gavetas.conferir_base(base)
    saida = {
        "documento_id": documento_id,
        "contrato": resumo(contrato),
        "materiais": resumo(materiais),
        "erros": erros,
    }
    print(json.dumps(saida, ensure_ascii=False, indent=2))
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
