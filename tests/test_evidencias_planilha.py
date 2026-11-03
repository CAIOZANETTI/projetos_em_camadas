"""Planilha (xlsx/csv) como documento de leitura da IA: texto por linha, localizador aba/linha, quantidade pelas colunas
Un/Qtd (nunca preço ou código) e as regras de sempre."""

import decimal
import importlib.util
import json
import math

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
        "Estruturas": [(1, ["Descrição", "Un", "Qtd"]), (2, ["Estaca hélice", "m", 12, "un", 250])],
    })


def _linha(**campos) -> dict:
    ev = {"codigo": "U1.*.GEO.FUN.EST", "servico": "", "unidade": "un", "valor": 250.0, "parcela": False,
          "documento": {"id": NOME, "tipo": "ia"}, "localizador": {"aba": "Fundações", "linha": 2}, "metodo": "ia",
          "trecho": ESTACA}
    return {**ev, **campos}


def _conferir(planilha, *linhas):
    return evidencias.conferir_arquivo(list(linhas), {NOME: evidencias.paginas_planilha(planilha)})


def _motivo(planilha, **campos) -> str | None:
    aceitas, recusadas = _conferir(planilha, _linha(**campos))
    return None if aceitas else recusadas[0]["motivo"]


# texto da planilha -------------------------------------------------------------------------------------------------
def test_texto_da_planilha_uma_pagina_por_aba_com_numeros_em_ptbr(planilha):
    paginas = evidencias.paginas_planilha(planilha)
    assert [p.aba for p in paginas] == ["Fundações", "Estruturas"]
    assert str(paginas[0]).split("\n") == ["Descrição | Un | Qtd", "Estaca hélice contínua Ø40 | un | 250",
                                           "Escavação de solo | m³ | 1.250,5"]
    assert paginas[0].linhas == (1, 2, 4)                              # a linha 3 vazia conta, como no Excel
    assert str(paginas[1]).split("\n")[1] == "Estaca hélice | m | 12 | un | 250" and paginas[1].linhas == (1, 2)


def test_formatacao_exata_das_celulas():
    texto = lambda v, **k: evidencias._celula(1, v, **k).texto
    assert [texto(v) for v in (250.0, 250, 1250.5, 0.1, 1234567.891, -1250.25, 3.14159265358979, -0.0, 0.0)] == [
        "250", "250", "1.250,5", "0,1", "1.234.567,891", "-1.250,25", "3,14159265358979", "0", "0"]
    assert texto(decimal.Decimal("1250.50")) == "1.250,5" and texto(0.15, percentual=True) == "15%"
    assert texto(0.0725, percentual=True) == "7,25%"
    assert evidencias._celula(1, None) is None and texto("  a\n b ") == "a b"


def test_numero_fora_da_faixa_nan_e_infinito_viram_celula_marcada_que_nao_confere():
    for ruim in (1e20, 1e-9, math.nan, math.inf, -math.inf, 10**400):
        celula = evidencias._celula(1, ruim)
        assert celula.problema and celula.numero is None and celula.texto.startswith("[")
    assert evidencias._celula(1, 1e15).problema is None and evidencias._celula(1, 1e-6).problema is None


def test_csv_e_uma_pagina_so_e_o_texto_e_deterministico(tmp_path):
    caminho = tmp_path / "q.csv"
    caminho.write_text("Descrição;Un;Qtd\n\nEstaca hélice contínua Ø40;un;250\n;;\n", encoding="utf-8")
    paginas = evidencias.paginas_planilha(caminho)
    assert len(paginas) == 1 and paginas[0].linhas == (1, 3)
    assert str(paginas[0]) == "Descrição | Un | Qtd\nEstaca hélice contínua Ø40 | un | 250"
    assert [str(p) for p in evidencias.paginas_planilha(caminho)] == [str(p) for p in paginas]


def test_texto_deterministico_no_xlsx(planilha):
    a, b = evidencias.paginas_planilha(planilha), evidencias.paginas_planilha(planilha)
    assert [(str(p), p.aba, p.linhas, p.celulas) for p in a] == [(str(p), p.aba, p.linhas, p.celulas) for p in b]


def test_percentual_do_xlsx_vira_texto_com_sinal(tmp_path):
    livro = Workbook()
    aba = livro.active
    aba.title = "A"
    aba["A1"], aba["B1"] = "BDI", 0.15
    aba["B1"].number_format = "0%"
    livro.save(tmp_path / "p.xlsx")
    assert str(evidencias.paginas_planilha(tmp_path / "p.xlsx")[0]) == "BDI | 15%"


# localizador aba/linha ---------------------------------------------------------------------------------------------
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
    assert _motivo(planilha, localizador={"aba": "Outra", "linha": 2}) == "aba citada não existe no documento"


def test_nome_da_aba_compara_com_nfc_e_sem_espaco_nas_pontas(planilha):
    decomposto = "Fundações"                                 # NFD de "Fundações"
    assert _motivo(planilha, localizador={"aba": f" {decomposto} ", "linha": 2}) is None


def test_localizador_mal_formado_e_schema_invalido(planilha):
    for ruim in ({"aba": "Fundações"}, {"aba": "Fundações", "linha": 0}, {"aba": "Fundações", "linha": True},
                 {"aba": 3, "linha": 2}, {"aba": "Fundações", "linha": 2, "x": 1}, 5):
        motivo = _motivo(planilha, localizador=ruim)
        assert motivo.startswith("schema inválido") and "localizador" in motivo


def test_localizacao_citada_chamada_direto_nao_levanta(planilha):
    paginas = evidencias.paginas_planilha(planilha)
    for ruim in ({}, {"aba": "Fundações"}, {"linha": 2}, {"aba": None, "linha": 2}, {"aba": "Fundações", "linha": "2"}):
        assert evidencias._localizacao_citada(ruim, paginas)[2]
    assert evidencias._localizacao_citada({"aba": "Estruturas", "linha": 2}, paginas) == (2, 2, None)


def test_localizador_p_n_vale_como_indice_da_aba(planilha):
    assert _conferir(planilha, _linha(localizador="p. 1"))[1] == []
    assert _motivo(planilha, localizador="p. 2") == "página citada não contém o trecho"


def test_aba_linha_em_documento_que_nao_e_planilha():
    ev = _linha(trecho="Serão executadas 250 estacas hélice contínua.")
    aceitas, recusadas = evidencias.conferir_arquivo([ev], {NOME: ["Serão executadas 250 estacas hélice contínua."]})
    assert not aceitas and recusadas[0]["motivo"] == "aba citada não existe no documento"


# quantidade pelas colunas Un/Qtd -----------------------------------------------------------------------------------
def test_regras_de_sempre_valem_no_texto_da_planilha(planilha):
    trecho = "Estaca hélice | m | 12 | un | 250"
    local = {"aba": "Estruturas", "linha": 2}
    assert _motivo(planilha, localizador=local, valor=12.0, unidade="m", trecho=trecho) is None      # Un=m, Qtd=12
    assert _motivo(planilha, localizador=local, valor=12.0, trecho=trecho) == "valor não está no trecho"
    assert _motivo(planilha, localizador=local, valor=250.0, trecho=trecho) == "valor não está no trecho"


def _preco(tmp_path, cabecalho, linha):
    return _xlsx(tmp_path / NOME, {"S": [(1, cabecalho), (2, linha)]})


def test_preco_nunca_vira_quantidade_qtd_un_preco(tmp_path):
    caminho = _preco(tmp_path, ["Item", "Descrição", "Qtd", "Un", "Preço"],
                     ["3.2.1", "Estaca hélice contínua Ø40", 250, "m", 1250.5])
    trecho = "3.2.1 | Estaca hélice contínua Ø40 | 250 | m | 1.250,5"
    base = {"localizador": {"aba": "S", "linha": 2}, "trecho": trecho, "unidade": "m"}
    assert _motivo(caminho, **base, valor=250.0) is None
    assert _motivo(caminho, **base, valor=1250.5) == "valor não está no trecho"
    assert _motivo(caminho, **base, valor=3.2) == "valor não está no trecho"
    assert _motivo(caminho, **{**base, "localizador": "p. 1"}, valor=1250.5) == "valor não está no trecho"


def test_un_qtd_preco_continua_valendo(tmp_path):
    caminho = _preco(tmp_path, ["Item", "Descrição", "Un", "Qtd", "Preço"],
                     ["3.2.1", "Estaca hélice contínua Ø40", "m", 250, 1250.5])
    trecho = "3.2.1 | Estaca hélice contínua Ø40 | m | 250 | 1.250,5"
    base = {"localizador": {"aba": "S", "linha": 2}, "trecho": trecho, "unidade": "m"}
    assert _motivo(caminho, **base, valor=250.0) is None
    assert _motivo(caminho, **base, valor=1250.5) == "valor não está no trecho"
    assert _motivo(caminho, **{**base, "unidade": "un"}, valor=250.0) == "valor não está no trecho"


def test_quantidade_vazia_com_preco_nao_vira_quantidade(tmp_path):
    caminho = _preco(tmp_path, ["Descrição", "Un", "Qtd", "Preço"], ["Estaca hélice contínua Ø40", "un", None, 87.3])
    for valor in (87.3, 250.0):
        assert _motivo(caminho, localizador={"aba": "S", "linha": 2}, valor=valor,
                       trecho="Estaca hélice contínua Ø40 | un | 87,3") == "valor não está no trecho"


def test_formula_sem_valor_guardado_nao_confere(tmp_path):
    livro = Workbook()
    aba = livro.active
    aba.title = "S"
    aba.append(["Descrição", "Un", "Qtd", "Preço"])
    aba.append(["Estaca hélice contínua Ø40", "un", "=2*125", 1250.5])
    livro.save(tmp_path / NOME)
    pagina = evidencias.paginas_planilha(tmp_path / NOME)[0]
    assert "[fórmula sem valor]" in str(pagina) and pagina.celulas[1][2].problema
    for trecho in ("Estaca hélice contínua Ø40 | un | [fórmula sem valor] | 1.250,5",
                   "Estaca hélice contínua Ø40 | un | 1.250,5", "Estaca hélice contínua Ø40 | un"):
        for valor in (250.0, 1250.5):
            assert _motivo(tmp_path / NOME, localizador={"aba": "S", "linha": 2}, trecho=trecho, valor=valor) == \
                "célula sem valor calculado na planilha"


def test_formula_com_valor_guardado_vale(tmp_path):
    caminho = tmp_path / NOME
    _xlsx(caminho, {"S": [(1, ["Descrição", "Un", "Qtd"]), (2, ["Estaca hélice contínua Ø40", "un", 250])]})
    assert _motivo(caminho, localizador={"aba": "S", "linha": 2}, trecho="Estaca hélice contínua Ø40 | un | 250") is None


def test_sem_cabecalho_so_vale_par_dentro_de_uma_celula(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"S": [(1, ["Estaca hélice contínua Ø40", "250 un", 1250.5]),
                                            (2, ["Estaca hélice contínua Ø40", "un", 250])]})
    assert _motivo(caminho, localizador={"aba": "S", "linha": 1}, trecho="Estaca hélice contínua Ø40 | 250 un") is None
    assert _motivo(caminho, localizador={"aba": "S", "linha": 1}, valor=1250.5,
                   trecho="Estaca hélice contínua Ø40 | 250 un | 1.250,5") == "valor não está no trecho"
    assert _motivo(caminho, localizador={"aba": "S", "linha": 2}, trecho=ESTACA) == "valor não está no trecho"


def test_cabecalho_vale_so_para_as_linhas_abaixo_e_o_ultimo_vence(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"S": [(1, ["Estaca hélice contínua Ø40", "un", 250]),
                                            (2, ["Descrição", "Un", "Qtd"]),
                                            (3, ["Estaca hélice contínua Ø40", "un", 250]),
                                            (5, ["Descrição", "Qtd", "Un"]),
                                            (6, ["Estaca hélice contínua Ø40", 250, "un"])]})
    assert _motivo(caminho, localizador={"aba": "S", "linha": 1}, trecho=ESTACA) == "valor não está no trecho"
    assert _motivo(caminho, localizador={"aba": "S", "linha": 3}, trecho=ESTACA) is None
    assert _motivo(caminho, localizador={"aba": "S", "linha": 6}, trecho="Estaca hélice contínua Ø40 | 250 | un") is None


def test_rotulos_de_cabecalho_aceitos(tmp_path):
    for un, qtd in (("Unid.", "Quant."), ("UNIDADE", "Quantidade"), ("Und", "Qtde")):
        caminho = _xlsx(tmp_path / NOME, {"S": [(1, ["Descrição", un, qtd]), (2, ["Estaca hélice contínua Ø40", "un", 250])]})
        assert _motivo(caminho, localizador={"aba": "S", "linha": 2}, trecho=ESTACA) is None


def test_item_mais_proximo_com_colunas(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"S": [(1, ["Descrição", "Un", "Qtd"]),
                                            (2, ["Bloco de coroamento", "un", 30])]})
    assert _motivo(caminho, localizador={"aba": "S", "linha": 2}, valor=30.0,
                   trecho="Bloco de coroamento | un | 30") == "item não citado no trecho"


def test_bloco_de_linhas_seguidas_com_o_par_na_ultima(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"S": [(1, ["Descrição", "Un", "Qtd"]), (2, ["Estaca hélice contínua"]),
                                            (3, ["diâmetro 40 cm", "un", 250]),
                                            (5, ["Estaca hélice contínua"]), (7, ["diâmetro 40 cm", "un", 250])]})
    trecho = "Estaca hélice contínua diâmetro 40 cm | un | 250"
    for linha in (2, 3):                                              # citar qualquer linha do bloco
        assert _motivo(caminho, localizador={"aba": "S", "linha": linha}, trecho=trecho) is None
    assert _motivo(caminho, localizador={"aba": "S", "linha": 5}, trecho=trecho) == "item não citado no trecho"
    assert _motivo(caminho, localizador={"aba": "S", "linha": 7}, trecho=trecho) == "item não citado no trecho"


def test_pedaco_de_numero_e_numero_de_outra_linha_sao_recusados(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"A": [(1, ["Descrição", "Un", "Qtd"]),
                                            (2, ["Estaca hélice contínua Ø40", "un", 1250]),
                                            (3, ["Bloco de coroamento", "un", 250])]})
    trecho = "Estaca hélice contínua Ø40 | un | 1.250"
    inteiro = _conferir(caminho, _linha(localizador={"aba": "A", "linha": 2}, valor=1250.0, trecho=trecho))
    assert inteiro[1] == [] and inteiro[0][0]["valor"] == 1250
    assert _motivo(caminho, localizador={"aba": "A", "linha": 2}, valor=250.0, trecho=trecho) == "valor não está no trecho"
    assert _motivo(caminho, localizador={"aba": "A", "linha": 3}, valor=250.0, trecho=trecho) == \
        "linha citada não contém o trecho"
    assert _motivo(caminho, localizador={"aba": "A", "linha": 3}, valor=1250.0,
                   trecho="Bloco de coroamento | un | 250") == "valor não está no trecho"


def test_decimal_ptbr_na_planilha(planilha):
    ev = _linha(codigo="U1.*.GEO.MOV.ESC", unidade="m³", valor=1250.5, localizador={"aba": "Fundações", "linha": 4},
                trecho="Escavação de solo | m³ | 1.250,5")
    aceitas, recusadas = _conferir(planilha, ev)
    assert aceitas and aceitas[0]["valor"] == 1250.5 and not recusadas
    assert _conferir(planilha, {**ev, "valor": 250.5})[1][0]["motivo"] == "valor não está no trecho"


# csv ---------------------------------------------------------------------------------------------------------------
def test_csv_ponto_e_virgula_com_virgulas_nas_descricoes(tmp_path):
    caminho = tmp_path / "q.csv"
    caminho.write_text("Item;Descrição;Un;Qtd;Preço\n3.2.1;Estaca, hélice contínua, Ø40;m;250;1.250,5\n"
                       "3.2.2;Bloco, tipo B, com armação;un;30;98,7\n", encoding="utf-8")
    pagina = evidencias.paginas_planilha(caminho)[0]
    assert str(pagina).split("\n")[1] == "3.2.1 | Estaca, hélice contínua, Ø40 | m | 250 | 1.250,5"
    ia = _linha(documento={"id": "q.csv", "tipo": "ia"}, localizador={"aba": "q", "linha": 2}, unidade="m",
                trecho="3.2.1 | Estaca, hélice contínua, Ø40 | m | 250 | 1.250,5")
    aceitas, recusadas = evidencias.conferir_arquivo([ia, {**ia, "valor": 40.0}, {**ia, "valor": 1250.5}], {"q.csv": [pagina]})
    assert len(aceitas) == 1 and [r["motivo"] for r in recusadas] == ["valor não está no trecho"] * 2


def test_csv_separadores_tabulacao_e_virgula(tmp_path):
    for sep, nome in (("\t", "t.csv"), (",", "v.csv")):
        (tmp_path / nome).write_text(f"Descrição{sep}Un{sep}Qtd\nEstaca{sep}un{sep}250\nBloco{sep}un{sep}30\n", encoding="utf-8")
        assert str(evidencias.paginas_planilha(tmp_path / nome)[0]).split("\n")[1] == "Estaca | un | 250"


def test_csv_inconsistente_e_recusado_com_mensagem(tmp_path):
    caminho = tmp_path / "ruim.csv"
    caminho.write_text("a;b;c\nx,y;z\nq\nw;e;r;t;u\nk;l\n1,2,3,4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="separador ambíguo"):
        evidencias.paginas_planilha(caminho)
    registros = []
    docs = evidencias._documentos_da_linha_de_comando([], [], registros.append, [str(caminho)])
    assert docs == {} and "documento recusado" in registros[0]


def test_csv_quebra_dentro_de_aspas_vira_espaco(tmp_path):
    caminho = tmp_path / "q.csv"
    caminho.write_text('Descrição;Un;Qtd\n"Estaca\nhélice contínua";un;250\nBloco;un;30\n', encoding="utf-8")
    pagina = evidencias.paginas_planilha(caminho)[0]
    assert str(pagina).split("\n")[1] == "Estaca hélice contínua | un | 250"
    assert pagina.linhas == (1, 2, 3)


# .xls sem xlrd -----------------------------------------------------------------------------------------------------
@pytest.mark.skipif(importlib.util.find_spec("xlrd") is not None, reason="xlrd instalado")
def test_xls_sem_xlrd_e_recusado_sem_derrubar_a_etapa(tmp_path):
    from test_evidencias import _dados
    antiga = tmp_path / "antiga.xls"
    antiga.write_bytes(b"\xd0\xcf\x11\xe0")
    with pytest.raises(ValueError, match="xlrd"):
        evidencias.paginas_planilha(antiga)
    registros = []
    cfg = {"evidencias": {"documentos": [{"pdf": str(antiga), "tipo": "memorial"}]}}
    evidencias.etapa(cfg, tmp_path / "saida", _dados(), log=registros.append)
    assert any("documento recusado" in r and "xlrd" in r for r in registros)


# regex sobre planilha ---------------------------------------------------------------------------------------------
def test_buscar_texto_em_planilha_usa_localizador_aba_linha_e_colunas(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"S": [(1, ["Item", "Descrição", "Qtd", "Un", "Preço"]),
                                            (3, ["3.2.1", "Estaca hélice contínua Ø40", 250, "m", 1250.5])]})
    documento = {"id": NOME, "tipo": "planilha", "nome": NOME, "paginas": evidencias.paginas_planilha(caminho)}
    achadas = evidencias.buscar_texto(documento, documento["paginas"])
    assert [(e["localizador"], e["valor"], e["unidade"]) for e in achadas] == [({"aba": "S", "linha": 3}, 250.0, "m")]
    assert all(evidencias.validar_evidencia(e) == [] for e in achadas)


def test_buscar_texto_em_planilha_sem_cabecalho_nao_cruza_celulas(tmp_path):
    caminho = _xlsx(tmp_path / NOME, {"S": [(1, ["3.2.1", "Estaca hélice contínua Ø40", "m", 250, 1250.5]),
                                            (2, ["Estaca hélice contínua Ø40", "250 un"])]})
    achadas = evidencias.buscar_texto({"id": NOME, "tipo": "planilha", "nome": NOME}, evidencias.paginas_planilha(caminho))
    assert [(e["localizador"]["linha"], e["valor"], e["unidade"]) for e in achadas] == [(1, None, None), (2, 250.0, "un")]


# ligações ---------------------------------------------------------------------------------------------------------
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
