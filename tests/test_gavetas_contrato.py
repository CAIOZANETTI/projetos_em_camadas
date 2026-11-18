"""Testes de `gavetas_contrato` com planilha sintética: objeto, fato e evidência por linha, pendência e nenhum preço."""

import json

import openpyxl
import pytest

from camadas import gavetas
from camadas import gavetas_contrato as gc

SENTINELA = 987654.321

# (A, B, C, D, E, I)
CUSTO = [
    ("UNIDADE 1 - ETA Teste", None, None, None, None, None),
    ("1", None, "INTERLIGAÇÕES", None, None, None),
    (None, None, "ENTRADA DA ADUTORA", "M", None, "004-SAA-0017"),
    (None, "CVCAFD1000", "ESCAVAÇÃO ... FD DN 1000", "M", None, "005-SAA-0017"),
    (None, None, "MEDIDORES DE VAZÃO", "UNI", 3, None),
]

CABECALHO_MAT = [
    "Item",
    "Sequência de estoque",
    "Local",
    "Material",
    "Descrição",
    "Unidade",
    "Quantidade\n1ª etapa",
    "Quantidade\n2ª etapa",
    "VALOR UNITÁRIO",
    "Fornecedor",
    "VALOR TOTAL",
]
# (item, seq, local, material, descrição, unidade, q1, q2)
MATERIAIS = [
    (1, "123456", "ETA", "FOFO", "TUBO FOFO DN 300 PN10", "M", 12.5, None),
    (2, "654321", "ETA", "AÇO", "REGISTRO GAVETA", "UN", None, 4),
    (3, "111111", "ETA", "PVC", "LUVA DE PVC", "UN", "a definir", None),
]


@pytest.fixture
def planilha(tmp_path):
    caminho = tmp_path / "contrato.xlsx"
    livro = openpyxl.Workbook()
    ws = livro.active
    ws.title = "CUSTO CIVIL"
    ws.append(["SANEPAR - TESTE"])
    ws.append(
        [
            "ITEM",
            "COMPOSIÇÃO",
            "DESCRIÇÃO",
            "UNID.",
            "QUANT.",
            "VALOR UNITÁRIO",
            "VALOR TOTAL",
            None,
            "PROJETO",
        ]
    )
    for a, b, c, d, e, i in CUSTO:
        ws.append([a, b, c, d, e, SENTINELA, SENTINELA, None, i])
    rel = livro.create_sheet("Relação de Materiais")
    rel.append(CABECALHO_MAT)
    for item, seq, local, mat, desc, un, q1, q2 in MATERIAIS:
        rel.append(
            [item, seq, local, mat, desc, un, q1, q2, SENTINELA, SENTINELA, SENTINELA]
        )
    contatos = livro.create_sheet("INSUMOS")
    contatos.append([SENTINELA, SENTINELA])
    livro.save(caminho)
    return caminho


def _fatos(base, objeto_id):
    return {f["propriedade"]: f for f in base["fatos"] if f["objeto_id"] == objeto_id}


def test_contrato_objeto_fato_e_evidencia_por_linha(planilha):
    base = gc.de_contrato(planilha, "doc1")
    assert {o["classe"] for o in base["objetos"]} == {"item_contrato"}
    ids = {o["objeto_id"] for o in base["objetos"]}
    assert {"c211-custo-civil-5", "c211-custo-civil-6", "c211-custo-civil-7"} <= ids
    fatos = _fatos(base, "c211-custo-civil-6")
    assert fatos["composicao"]["valor"] == "CVCAFD1000"
    assert fatos["unidade_medida"]["valor"] == "M"
    assert fatos["uc"]["valor"] == "UC 1 - INTERLIGAÇÕES"
    assert fatos["trecho"]["valor"] == "ENTRADA DA ADUTORA"
    assert fatos["dn_mm"]["valor"] == 1000 and fatos["material"]["valor"]
    assert {f["natureza"] for f in base["fatos"]} == {"projetado"}
    evidencia = next(
        e
        for e in base["evidencias"]
        if e["evidencia_id"] == fatos["composicao"]["evidencia_id"]
    )
    assert evidencia["documento"] == "doc1"
    assert evidencia["localizador"] == {"aba": "CUSTO CIVIL", "linha": 6}
    assert (
        evidencia["metodo"] == "camadas.contrato_211"
        and evidencia["executor"] == "código"
    )


def test_quantidade_declarada_ou_pendencia(planilha):
    base = gc.de_contrato(planilha, "doc1")
    declarada = _fatos(base, "c211-custo-civil-7")
    assert declarada["quantidade"]["valor"] == 3.0
    sem = _fatos(base, "c211-custo-civil-6")
    assert "quantidade" not in sem
    pendentes = {
        p["objeto_id"]
        for p in base["pendencias"]
        if p["motivo"] == "quantidade a calcular (F4)"
    }
    assert "c211-custo-civil-6" in pendentes and "c211-custo-civil-7" not in pendentes


def test_materiais_objeto_fato_e_evidencia(planilha):
    base = gc.de_materiais(planilha, "doc1")
    assert [o["objeto_id"] for o in base["objetos"]] == ["rel-2", "rel-3", "rel-4"]
    assert {o["classe"] for o in base["objetos"]} == {"item_material"}
    tubo = _fatos(base, "rel-2")
    assert tubo["codigo_material"]["valor"] == "123456"
    assert tubo["descricao"]["valor"] == "TUBO FOFO DN 300 PN10"
    assert tubo["unidade_medida"]["valor"] == "M"
    assert (
        tubo["quantidade_etapa1"]["valor"] == 12.5 and "quantidade_etapa2" not in tubo
    )
    assert tubo["dn_mm"]["valor"] == 300
    assert "dn_mm" not in _fatos(base, "rel-3")
    assert _fatos(base, "rel-3")["quantidade_etapa2"]["valor"] == 4.0
    evidencia = next(
        e
        for e in base["evidencias"]
        if e["evidencia_id"] == tubo["codigo_material"]["evidencia_id"]
    )
    assert evidencia["localizador"] == {"aba": "Relação de Materiais", "linha": 2}
    assert evidencia["documento"] == "doc1"
    motivos = [p["motivo"] for p in base["pendencias"] if p["objeto_id"] == "rel-4"]
    assert (
        any("não numérica" in m for m in motivos)
        and "sem quantidade em nenhuma etapa" in motivos
    )


def test_sentinela_de_preco_nunca_aparece(planilha):
    contrato, materiais = (
        gc.de_contrato(planilha, "doc1"),
        gc.de_materiais(planilha, "doc1"),
    )
    saida = json.dumps(
        [contrato, materiais, gc.resumo(contrato), gc.resumo(materiais)],
        ensure_ascii=False,
    )
    assert "987654" not in saida


def test_relacao_so_le_as_colunas_nomeadas(planilha, monkeypatch):
    pedidas = []
    original = openpyxl.worksheet._read_only.ReadOnlyWorksheet.iter_rows

    def espiao(self, *args, **kwargs):
        if self.title == "Relação de Materiais":
            pedidas.append((kwargs.get("min_col"), kwargs.get("max_col")))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        openpyxl.worksheet._read_only.ReadOnlyWorksheet, "iter_rows", espiao
    )
    gc.ler_relacao(planilha)
    colunas = {c for c in pedidas if c[0] is not None}
    assert colunas == {(2, 2), (3, 3), (5, 5), (6, 6), (7, 7), (8, 8)}


def test_base_confere_com_documento_registrado(planilha):
    base = gc.juntar(
        gc.de_contrato(planilha, "doc1"), gc.de_materiais(planilha, "doc1")
    )
    base["documentos"].append(
        {
            "documento_id": "doc1",
            "arquivo": "contrato.xlsx",
            "sha256": "doc1",
            "extensao": ".xlsx",
            "classe": "planilha",
            "paginas": 1,
        }
    )
    assert gavetas.conferir_base(base) == []
    resumo = gc.resumo(base)
    assert resumo["objetos_por_classe"]["item_material"] == 3
    assert resumo["objetos_por_classe"]["item_contrato"] == 3


def test_cli_roda_e_imprime_resumo(planilha, tmp_path, capsys):
    obra = tmp_path / "obra.json"
    obra.write_text(
        json.dumps({"obras_lineares": {"planilha": str(planilha)}}), encoding="utf-8"
    )
    assert gc.main([str(obra)]) == 0
    saida = json.loads(capsys.readouterr().out)
    assert saida["erros"] == [] and saida["materiais"]["objetos_por_classe"] == {
        "item_material": 3
    }
    assert "987654" not in json.dumps(saida)
