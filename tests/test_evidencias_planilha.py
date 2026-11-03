"""Planilha (xlsx/csv) como documento de leitura da IA: texto por linha, localizador aba/linha e as regras de sempre."""

import json

import pytest
from openpyxl import Workbook

from camadas import evidencias

NOME = "quantitativos.xlsx"
ESTACA = "Estaca hélice contínua Ø40 | un | 250"


def _xlsx(caminho, abas: dict[str, list[tuple[int, list]]]):
    """Planilha com as linhas dadas por aba: (linha da planilha, células); as linhas ausentes ficam vazias."""
    livro = Workbook()
    livro.remove(livro.active)
    for nome, linhas in abas.items():
        aba = livro.create_sheet(nome)
        for numero, celulas in linhas:
            for coluna, valor in enumerate(celulas, 1):
                aba.cell(row=numero, column=coluna, value=valor)
    livro.save(caminho)
    return caminho


@pytest.fixture
def planilha(tmp_path):
    return _xlsx(tmp_path / NOME, {
        "Fundações": [(1, ["Descrição", "Un", "Qtd"]), (2, ["Estaca hélice contínua Ø40", "un", 250.0]),
                      (4, ["Escavação de solo", "m³", 1250.5])],
        "Estruturas": [(2, ["Estaca hélice", "m", 12, "un", 250])],
    })


def _linha(**campos) -> dict:
    ev = {"codigo": "U1.*.GEO.FUN.EST", "servico": "", "unidade": "un", "valor": 250.0, "parcela": False,
          "documento": {"id": NOME, "tipo": "ia"}, "localizador": {"aba": "Fundações", "linha": 2}, "metodo": "ia",
          "trecho": ESTACA}
    return {**ev, **campos}


def _conferir(planilha, *linhas):
    return evidencias.conferir_arquivo(list(linhas), {NOME: evidencias.paginas_planilha(planilha)})


def test_texto_da_planilha_uma_pagina_por_aba_com_numeros_em_ptbr(planilha):
    paginas = evidencias.paginas_planilha(planilha)
    assert [p.aba for p in paginas] == ["Fundações", "Estruturas"]
    assert str(paginas[0]).split("\n") == ["Descrição | Un | Qtd", "Estaca hélice contínua Ø40 | un | 250",
                                           "Escavação de solo | m³ | 1.250,5"]
    assert paginas[0].linhas == (1, 2, 4)                              # a linha 3 vazia conta, como no Excel
    assert str(paginas[1]) == "Estaca hélice | m | 12 | un | 250" and paginas[1].linhas == (2,)


def test_numeros_sem_arredondar():
    formatar = evidencias._texto_da_celula
    assert [formatar(v) for v in (250.0, 250, 1250.5, 0.1, 1234567.891, -1250.25, 3.14159265358979)] == [
        "250", "250", "1.250,5", "0,1", "1.234.567,891", "-1.250,25", "3,14159265358979"]
    assert formatar(None) == "" and formatar("  a\n b ") == "a b"


def test_csv_e_uma_pagina_so_e_o_texto_e_deterministico(tmp_path):
    caminho = tmp_path / "q.csv"
    caminho.write_text("Descrição;Un;Qtd\n\nEstaca hélice contínua Ø40;un;250\n;;\n", encoding="utf-8")
    paginas = evidencias.paginas_planilha(caminho)
    assert len(paginas) == 1 and paginas[0].linhas == (1, 3)
    assert str(paginas[0]) == "Descrição | Un | Qtd\nEstaca hélice contínua Ø40 | un | 250"
    assert [str(p) for p in evidencias.paginas_planilha(caminho)] == [str(p) for p in paginas]


def test_texto_deterministico_no_xlsx(planilha):
    a, b = evidencias.paginas_planilha(planilha), evidencias.paginas_planilha(planilha)
    assert [(str(p), p.aba, p.linhas) for p in a] == [(str(p), p.aba, p.linhas) for p in b]


def test_aceita_pelo_localizador_aba_e_linha(planilha):
    aceitas, recusadas = _conferir(planilha, _linha())
    assert recusadas == [] and aceitas[0]["valor"] == 250 and aceitas[0]["unidade"] == "un"
    assert aceitas[0]["localizador"] == {"aba": "Fundações", "linha": 2}
    json.dumps(aceitas[0], ensure_ascii=False)


def test_recusa_linha_errada_aba_errada_e_aba_inexistente(planilha):
    motivos = [r["motivo"] for r in _conferir(planilha, _linha(localizador={"aba": "Fundações", "linha": 4}),
                                              _linha(localizador={"aba": "Fundações", "linha": 1}),
                                              _linha(localizador={"aba": "Estruturas", "linha": 2}))[1]]
    assert motivos == ["linha citada não contém o trecho", "linha citada não contém o trecho",
                       "página citada não contém o trecho"]
    recusa = _conferir(planilha, _linha(localizador={"aba": "Outra", "linha": 2}))[1][0]["motivo"]
    assert recusa == "aba citada não existe no documento"


def test_localizador_mal_formado_e_schema_invalido(planilha):
    for ruim in ({"aba": "Fundações"}, {"aba": "Fundações", "linha": 0}, {"aba": "Fundações", "linha": True},
                 {"aba": 3, "linha": 2}, {"aba": "Fundações", "linha": 2, "x": 1}, 5):
        motivo = _conferir(planilha, _linha(localizador=ruim))[1][0]["motivo"]
        assert motivo.startswith("schema inválido") and "localizador" in motivo


def test_localizador_p_n_vale_como_indice_da_aba(planilha):
    assert _conferir(planilha, _linha(localizador="p. 1"))[1] == []
    assert _conferir(planilha, _linha(localizador="p. 2"))[1][0]["motivo"] == "página citada não contém o trecho"


def test_aba_linha_em_documento_que_nao_e_planilha(planilha):
    ev = _linha(trecho="Serão executadas 250 estacas hélice contínua.")
    aceitas, recusadas = evidencias.conferir_arquivo([ev], {NOME: ["Serão executadas 250 estacas hélice contínua."]})
    assert not aceitas and recusadas[0]["motivo"] == "aba citada não existe no documento"


def test_regras_de_sempre_valem_no_texto_da_planilha(planilha):
    certa = _conferir(planilha, _linha(localizador={"aba": "Estruturas", "linha": 2}, valor=250.0,
                                       trecho="Estaca hélice | m | 12 | un | 250"))
    assert certa[1] == []
    errada = _conferir(planilha, _linha(localizador={"aba": "Estruturas", "linha": 2}, valor=12.0,
                                        trecho="Estaca hélice | m | 12 | un | 250"))[1][0]["motivo"]
    assert errada != "conferida" and errada


def test_pedaco_de_numero_e_numero_de_outra_linha_sao_recusados(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"A": [(1, ["Estaca hélice contínua Ø40", "un", 1250]),
                                            (2, ["Bloco de coroamento", "un", 250])]})
    inteiro = _conferir(caminho, _linha(localizador={"aba": "A", "linha": 1}, valor=1250.0,
                                        trecho="Estaca hélice contínua Ø40 | un | 1.250"))
    assert inteiro[1] == [] and inteiro[0][0]["valor"] == 1250
    parte = _conferir(caminho, _linha(localizador={"aba": "A", "linha": 1}, valor=250.0,
                                      trecho="Estaca hélice contínua Ø40 | un | 1.250"))[1][0]["motivo"]
    assert parte == "valor não está no trecho"
    outra = _conferir(caminho, _linha(localizador={"aba": "A", "linha": 2}, valor=250.0,
                                      trecho="Estaca hélice contínua Ø40 | un | 1.250"))[1][0]["motivo"]
    assert outra == "linha citada não contém o trecho"
    cola = _conferir(caminho, _linha(localizador={"aba": "A", "linha": 2}, valor=1250.0,
                                     trecho="Bloco de coroamento | un | 250"))[1][0]["motivo"]
    assert cola == "valor não está no trecho"


def test_decimal_ptbr_na_planilha(planilha):
    ev = _linha(codigo="U1.*.GEO.MOV.ESC", unidade="m³", valor=1250.5, localizador={"aba": "Fundações", "linha": 4},
                trecho="Escavação de solo | m³ | 1.250,5")
    aceitas, recusadas = _conferir(planilha, ev)
    assert aceitas and aceitas[0]["valor"] == 1250.5 and not recusadas
    pedaco = _conferir(planilha, {**ev, "valor": 250.5})[1][0]["motivo"]
    assert pedaco == "valor não está no trecho"


def test_conferir_pela_linha_de_comando_com_planilha(planilha, tmp_path, capsys):
    ia = tmp_path / "ia.jsonl"
    ia.write_text(json.dumps(_linha(), ensure_ascii=False) + "\n", encoding="utf-8")
    saida = tmp_path / "aceitas.jsonl"
    assert evidencias.main(["conferir", str(ia), "--planilha", str(planilha), "--saida", str(saida)]) == 0
    assert "1 aceitas, 0 recusadas" in capsys.readouterr().out
    assert len(evidencias.ler(saida)) == 1


def test_etapa_le_planilha_em_documentos(planilha, tmp_path):
    from test_evidencias import _dados
    ia = tmp_path / "ia.jsonl"
    ia.write_text(json.dumps(_linha(), ensure_ascii=False) + "\n", encoding="utf-8")
    cfg = {"evidencias": {"documentos": [{"pdf": str(planilha), "tipo": "memorial"}], "ia": str(ia)}}
    evidencias.etapa(cfg, tmp_path / "saida", _dados(), log=lambda *a: None)
    evs = evidencias.ler(tmp_path / "saida" / "evidencias.jsonl")
    conferidas = [e for e in evs if e.get("metodo") == "ia"]
    assert len(conferidas) == 1 and conferidas[0]["citacao"] == "conferida"
    assert conferidas[0]["documento"]["id"] == f"ia:{NOME}"
