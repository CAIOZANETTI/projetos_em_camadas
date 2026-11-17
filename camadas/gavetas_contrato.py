"""Planilha do contrato → gavetas (F2 da reconstrução): itens da CUSTO CIVIL e da Relação de Materiais, sem preço.

Cada função devolve uma base `{gaveta: [registros]}` (contrato em `conceitos/gavetas.json`). Só entram as colunas de
identificação e quantidade: a CUSTO CIVIL pelo leitor `contrato_211` (colunas A–E e I) e a Relação de Materiais pelo
leitor daqui, que lê cada coluna nomeada (sequência de estoque, local, descrição, unidade, quantidades das etapas e
subcategoria do cadastro) e nenhuma outra. Valor, fornecedor, marca e as demais abas nunca são abertos. Quantidade vazia
não vira fato: vira pendência (o `contrato_211` calcula, e `aplicar_calculadas` devolve o resultado às gavetas).

Cada linha do contrato e cada material ganha a `folha_eap` da obra da sua unidade (U1 → OP, U2 → OL; conceitos
`equivalencia_obra_linear` e `materiais` de `composicoes_sanepar.json`).

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

from . import contrato_211, eap_padrao, evidencias, gavetas
from . import orcamento_sanepar as orc
from .vocabulario import preparar

ABA_CONTRATO = "CUSTO CIVIL"
ABA_MATERIAIS = "Relação de Materiais"
METODO_CONTRATO = "camadas.contrato_211"
PENDENCIA_A_CALCULAR = "quantidade a calcular (F4)"
CLASSES_DO_CONTRATO = ("item_contrato", "item_material")
METODO_MATERIAIS = "camadas.gavetas_contrato"
MATERIAIS = contrato_211.DE_PARA["materiais"]
PROPRIEDADES_CALCULO = (
    "quantidade_calculada",
    "unidade_calculada",
    "regra_calculo",
    "situacao_calculo",
)
"""Fatos que o `contrato_211` devolve às gavetas (`aplicar_calculadas`), na natureza `calculado`."""
PROPRIEDADES_CONTRATO = (
    "composicao",
    "descricao",
    "unidade_medida",
    "unidade",
    "folha_eap",
    "trecho",
    "uc",
    "dn_mm",
    "material",
)


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
    `folha_eap`, `dn_mm` e `material` vêm do de-para `composicoes_sanepar.json`, quando ele casa; a `folha_eap` é a da
    obra da unidade da linha (fato `unidade`: u1 ou u2)."""
    base = gavetas.base_vazia()
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
        valores = {
            **linha,
            "unidade_medida": linha.get("unidade"),
            "unidade": contrato_211.unidade_da_linha(linha),
        }
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
                {"objeto_id": objeto_id, "motivo": PENDENCIA_A_CALCULAR}
            )
    return base


def _normalizar(texto) -> str:
    """Minúsculas, sem acento e sem ordinal (1ª → 1a), espaços simples: para comparar cabeçalhos."""
    base = unicodedata.normalize("NFKD", str(texto or "")).lower()
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", base).strip()


def _colunas_da_relacao(cabecalho: tuple) -> dict:
    """{campo: índice da coluna (1 a n)} pelos nomes do cabeçalho; só os campos de identificação e quantidade. `local` e
    `subcategoria` (cadastro Sanepar) são opcionais: sem eles o material fica sem unidade de obra ou sem subcategoria."""
    achados = {}
    for indice, celula in enumerate(cabecalho, start=1):
        nome = _normalizar(celula)
        if nome.startswith("sequencia de estoque"):
            achados.setdefault("codigo", indice)
        elif nome == "local":
            achados.setdefault("local", indice)
        elif nome == "subcategoria":
            achados.setdefault("subcategoria", indice)
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
    """Itens da aba 'Relação de Materiais': `linha`, `codigo`, `local`, `descricao`, `unidade`, `subcategoria`, `qtd_etapa1`,
    `qtd_etapa2` (texto não numérico em `texto_etapa1`/`texto_etapa2`). Lê a linha do cabeçalho e depois uma coluna de cada vez, só as
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
            "local": orc.txt(celula.get("local")),
            "descricao": orc.txt(celula["descricao"]),
            "unidade": orc.txt(celula["unidade"]),
            "subcategoria": orc.txt(celula.get("subcategoria")),
        }
        for etapa in ("etapa1", "etapa2"):
            numero = orc.num(celula[etapa])
            item[f"qtd_{etapa}"] = numero
            item[f"texto_{etapa}"] = orc.txt(celula[etapa]) if numero is None else ""
        itens.append(item)
    return itens


def unidade_do_local(local: str) -> str | None:
    """Unidade construtiva (`u1`, `u2`) do material pelo Local da Relação de Materiais (padrões de `materiais.locais`);
    None se nenhum padrão casa."""
    texto = _normalizar(local)
    return next(
        (e["unidade"] for e in MATERIAIS["locais"] if re.search(e["padrao"], texto)),
        None,
    )


def _item_do_material(
    descricao: str, subcategoria: str, obra: str | None
) -> str | None:
    """Item técnico da EAP geral do material. Com subcategoria do cadastro Sanepar, vale o `catalogo` do item (conexão,
    válvula, registro e flange são HID.TUB.VAL; tubo é HID.TUB.RED), e a subcategoria que nenhum item acolhe (fixação,
    borracharia…) não leva folha. Sem cadastro (`materiais.subcategoria_sem_cadastro`), valem os termos dos itens
    (`evidencias.classificar`, o vocabulário do projeto), na obra da unidade."""
    if subcategoria and subcategoria not in MATERIAIS["subcategoria_sem_cadastro"]:
        return evidencias.item_do_material(
            {"subcategoria": subcategoria, "descricao": descricao}
        )
    item = evidencias.classificar(preparar(descricao)[1], obra)[0]
    return None if item is None or item.endswith(".*") else item


def folha_do_item(item: str, unidade: str) -> str | None:
    """Primeira folha da EAP padrão da obra da unidade que aponta para o item inteiro (sem serviço): VAL cai em OP.07.02
    (U1) ou OL.07.03 (U2). None se a unidade é desconhecida ou a folha não existe."""
    obra = eap_padrao.OBRA_DA_UNIDADE.get(unidade)
    tipo = next((t for t, o in eap_padrao.OBRA_DO_TIPO.items() if o == obra), None)
    folhas = [
        f for e in eap_padrao.TIPOS.get(tipo, {}).get("etapas", []) for f in e["folhas"]
    ]
    return next(
        (
            f["id"]
            for f in folhas
            if any(a["item"] == item and not a.get("servico") for a in f["aponta"])
        ),
        None,
    )


def classificar_material(item: dict) -> tuple[dict, str | None]:
    """({fato: valor} de unidade, item técnico e folha_eap do material, motivo da pendência ou None). A unidade vem do
    Local; só os itens de `materiais.itens_com_folha` ganham folha; o resto, e o Local sem unidade, vira pendência com
    o motivo (nunca chute)."""
    unidade = unidade_do_local(item["local"])
    achados = {"local": item["local"], "subcategoria": item["subcategoria"]}
    if unidade is None:
        return (
            achados,
            f"Local {item['local']!r} sem unidade de obra (materiais.locais)",
        )
    obra = eap_padrao.OBRA_DA_UNIDADE.get(unidade)
    tecnico = _item_do_material(item["descricao"], item["subcategoria"], obra)
    achados |= {"unidade": unidade, "item_tecnico": tecnico}
    if tecnico not in MATERIAIS["itens_com_folha"]:
        return (
            achados,
            f"material sem folha da EAP neste passe (item {tecnico or 'não identificado'})",
        )
    achados["folha_eap"] = folha_do_item(tecnico, unidade)
    return achados, None if achados[
        "folha_eap"
    ] else f"item {tecnico} sem folha na obra de {unidade}"


def _serial_de_data(item: dict) -> list[str]:
    """Motivos das quantidades da Relação que parecem data do Excel (número inteiro no intervalo de
    `materiais.serial_de_data_excel`: 46023 é 01/01/2026) numa unidade de contagem (`unidades_contagem`: peça, unidade;
    46 mil peças de um item é implausível, 46 mil metros de tubo não): a quantidade sai do item (fica `None`) e o motivo
    vira pendência, para o serial não inflar o total da folha. Quantidade fracionária, fora do intervalo ou em outra
    unidade segue como está."""
    menor, maior = MATERIAIS["serial_de_data_excel"]
    motivos = []
    if str(item.get("unidade") or "").strip().lower() not in MATERIAIS["unidades_contagem"]:
        return motivos
    for etapa in ("etapa1", "etapa2"):
        quantidade = item[f"qtd_{etapa}"]
        if (
            quantidade is not None
            and quantidade == int(quantidade)
            and menor <= quantidade <= maior
        ):
            motivos.append(
                f"quantidade da {etapa[-1]}ª etapa parece data do Excel (serial {int(quantidade)})"
            )
            item[f"qtd_{etapa}"] = None
    return motivos


def de_materiais(planilha: Path, documento_id: str) -> dict:
    """Itens da Relação de Materiais → objetos `item_material` `rel-<linha>`, fatos e evidência (aba e linha).

    Quantidade de etapa só vira fato quando é número; vazia ou em texto vira pendência. `dn_mm` só quando a descrição
    traz `DN <n>` (extrator `orcamento_sanepar.extrair_dn`). Local, subcategoria, unidade de obra, item técnico e
    `folha_eap` vêm de `classificar_material`: conexões, peças especiais e válvulas (HID.TUB.VAL) e tubos (HID.TUB.RED)
    caem na folha da obra da unidade; o que não se resolve vira pendência com o motivo."""
    base = gavetas.base_vazia()
    for item in ler_relacao(planilha):
        objeto_id = f"rel-{item['linha']}"
        suspeitas = _serial_de_data(item)
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
        classificacao, motivo = classificar_material(item)
        valores |= classificacao
        for texto in [motivo, *suspeitas]:
            if texto:
                base["pendencias"].append({"objeto_id": objeto_id, "motivo": texto})
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


def sem_contrato(base: dict) -> dict:
    """A base sem os objetos `item_contrato` e `item_material` da rodada anterior, com os fatos (inclusive os calculados),
    as evidências e as pendências deles: refazer o contrato (`de_contrato`, `de_materiais`) sobre uma base que já o tem
    não deixa fato velho para trás (quantidade que a regra passou a recusar, folha que deixou de valer)."""
    ids = {
        o["objeto_id"] for o in base["objetos"] if o["classe"] in CLASSES_DO_CONTRATO
    }
    evidencias_dos_ids = {f"EV-{i}{sufixo}" for i in ids for sufixo in ("", "-calc")}
    return {
        **base,
        "objetos": [o for o in base["objetos"] if o["objeto_id"] not in ids],
        "fatos": [f for f in base["fatos"] if f["objeto_id"] not in ids],
        "pendencias": [p for p in base["pendencias"] if p.get("objeto_id") not in ids],
        "evidencias": [
            e for e in base["evidencias"] if e["evidencia_id"] not in evidencias_dos_ids
        ],
    }


def _sem_calculadas(base: dict) -> dict:
    """A base sem os fatos e as evidências de cálculo da rodada anterior (as pendências ficam como estão)."""
    sufixos = tuple(f".{p}" for p in PROPRIEDADES_CALCULO)
    return {
        **base,
        "fatos": [f for f in base["fatos"] if not f["fato_id"].endswith(sufixos)],
        "evidencias": [
            e for e in base["evidencias"] if not e["evidencia_id"].endswith("-calc")
        ],
    }


def _calculo_da_linha(
    resultado: dict, documento_id: str, objeto_id: str
) -> tuple[dict, list[dict]]:
    """(evidência, fatos) da quantidade que o `contrato_211` calculou para a linha: natureza `calculado`, executor código;
    a evidência cita aba, linha e regra no localizador e, no trecho, a regra, as evidências e as premissas que o cálculo
    usou (as mesmas que o HTML mostra)."""
    texto = contrato_211.para_html([resultado])[0]
    usado = "; ".join([*texto["evidencias"], *texto["premissas"]])
    evidencia = {
        "evidencia_id": f"EV-{objeto_id}-calc",
        "classe": "planilha",
        "documento": documento_id,
        "localizador": {
            "aba": resultado["aba"],
            "linha": resultado["linha"],
            "regra": resultado["regra"],
        },
        "metodo": f"{METODO_CONTRATO}.{resultado['regra']}",
        "executor": "código",
        "trecho": f"regra {resultado['regra']}" + (f"; {usado}" if usado else ""),
    }
    valores = {
        "quantidade_calculada": resultado["quantidade_calculada"],
        "unidade_calculada": resultado["unidade_calculada"],
        "regra_calculo": resultado["regra"],
        "situacao_calculo": resultado["situacao"],
    }
    fatos = [
        {**_fato(objeto_id, p, v, evidencia["evidencia_id"]), "natureza": "calculado"}
        for p, v in valores.items()
        if not _vazio(v)
    ]
    return evidencia, fatos


def aplicar_calculadas(base: dict, resultados: list[dict]) -> dict:
    """A base com a quantidade calculada pelo `contrato_211` (`quantificar`) em cada `item_contrato` que existe nela:
    fatos `quantidade_calculada`, `unidade_calculada`, `regra_calculo` e `situacao_calculo` (natureza `calculado`) com a
    evidência `EV-<objeto>-calc`. Só entra linha com quantidade calculada (a verba e a "a preencher" não). Idempotente:
    o que a rodada anterior gravou é trocado, e linha que deixou de ser calculada perde o fato. A pendência "quantidade
    a calcular" sai do objeto que a situação `calculada` resolveu. O documento é o da evidência da própria linha."""
    base = _sem_calculadas(base)
    objetos = {o["objeto_id"] for o in base["objetos"]}
    documento = {e["evidencia_id"]: e["documento"] for e in base["evidencias"]}
    novos, calculados = {"evidencias": [], "fatos": []}, set()
    for r in resultados:
        objeto_id = contrato_211._id_da_linha(r["aba"], r["linha"])
        doc = documento.get(f"EV-{objeto_id}")
        if r.get("quantidade_calculada") is None or objeto_id not in objetos or not doc:
            continue
        evidencia, fatos = _calculo_da_linha(r, doc, objeto_id)
        novos["evidencias"].append(evidencia)
        novos["fatos"] += fatos
        if r["situacao"] == "calculada":
            calculados.add(objeto_id)
    pendencias = [
        p
        for p in base["pendencias"]
        if not (p["objeto_id"] in calculados and p["motivo"] == PENDENCIA_A_CALCULAR)
    ]
    return {
        **base,
        "fatos": base["fatos"] + novos["fatos"],
        "evidencias": base["evidencias"] + novos["evidencias"],
        "pendencias": pendencias,
    }


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
