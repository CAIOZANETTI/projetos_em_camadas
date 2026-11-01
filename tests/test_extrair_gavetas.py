import openpyxl
import pytest

from camadas import extrair_gavetas as eg
from camadas import gavetas
from camadas import obras_lineares as ol


def _planilha(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Obras Lineares"
    cab = ["Local", "DN do tubo", "Tipo do tubo", "Sondagem", None, "NA (m)", "Tipo de solo", "Prof. Média",
           "Escoramento", "Comprimento Total", "Método Construtivo", "Tipo de\nPavimento 1", "Comprimento\nPavimento 1",
           "Observações"]
    for j, v in enumerate(cab, start=22):
        ws.cell(2, j, v)
    linhas = [["Entrada de água bruta", 1000, "FD", "SP-02", "SP-02", 9, "argila", 2.4, "sim", 57.3, "VCA", "grama",
               57.3, "Supressão vegetal - 100% do trecho"],
              ["Retorno lodo", 150, "FD", "SP-05", "SP-09", 7.6, "argila", None, "não", 28, "VCA", None, None, None],
              ["Travessia da Rua Pará", 300, "PEAD", "SP-15", "SP-15", 1.5, "areia", 3.0, "sim", 170, "VCA", "asfalto",
               120, None]]
    for i, linha in enumerate(linhas, start=4):
        for j, v in enumerate(linha, start=22):
            ws.cell(i, j, v)
    caminho = tmp_path / "p.xlsx"
    wb.save(caminho)
    return caminho


FUROS = [{"id": "SP-02", "E": 10.0, "N": 20.0, "na_m": 9.0, "camadas": [{"de": 0, "ate": 5, "descricao": "argila"}],
          "cota_boca_m": 650.5},
         {"id": "SP-05", "na_m": 7.6, "camadas": []}]


def test_planilha_vira_tres_objetos_e_base_confere(tmp_path):
    trechos = ol.ler_obras_lineares(_planilha(tmp_path))
    base = eg.de_obras_lineares(trechos, "p.xlsx")
    assert [o["objeto_id"] for o in base["objetos"]] == ["OL-004", "OL-005", "OL-006"]
    assert gavetas.conferir_base(eg.juntar(base)) == []
    assert not base["geometria"]
    ev = {e["evidencia_id"]: e for e in base["evidencias"]}
    for f in base["fatos"]:
        loc = ev[f["evidencia_id"]]["localizador"]
        assert loc["aba"] == "Obras Lineares" and isinstance(loc["linha"], int)
    naturezas = {f["propriedade"]: f["natureza"] for f in base["fatos"]}
    assert naturezas["na_m"] == naturezas["solo"] == "observado" and naturezas["prof_m"] == "projetado"


def test_prof_vazia_nao_vira_fato(tmp_path):
    base = eg.de_obras_lineares(ol.ler_obras_lineares(_planilha(tmp_path)), "p.xlsx")
    props = {(f["objeto_id"], f["propriedade"]) for f in base["fatos"]}
    assert ("OL-005", "prof_m") not in props and ("OL-004", "prof_m") in props
    assert ("OL-005", "pavimentos") not in props


def test_furos_com_e_sem_coordenadas():
    base = eg.de_sondagens(FUROS, "sondagens.json", executor="Sonnet")
    assert base["geometria"] == [{"objeto_id": "SP-02", "tipo": "ponto", "coords": [10.0, 20.0],
                                  "crs_h": "EPSG:31982", "datum_v": "ortométrico"}]
    assert base["pendencias"] == [{"objeto_id": "SP-05", "motivo": "furo sem coordenadas: não entra pela posição"}]
    assert {e["executor"] for e in base["evidencias"]} == {"Sonnet"}
    assert base["evidencias"][0]["localizador"] == {"arquivo": "sondagens.json", "furo": "SP-02"}
    assert not any(f["objeto_id"] == "SP-05" and f["propriedade"] == "cota_boca_m" for f in base["fatos"])
    assert gavetas.conferir_base(base) == []


def test_decisao_casa_por_local_normalizado(tmp_path):
    trechos = ol.ler_obras_lineares(_planilha(tmp_path))
    base = eg.de_decisoes({"TRAVESSIA DA RUA PARA": "MND", "Local fantasma": "MND"}, trechos, "obra.json")
    fato, = base["fatos"]
    assert fato["objeto_id"] == "OL-006" and fato["natureza"] == "decidido" and fato["valor"] == "MND"
    assert base["evidencias"][0]["executor"] == "você" and base["evidencias"][0]["classe"] == "decisao"
    assert len(base["pendencias"]) == 1 and "Local fantasma" in base["pendencias"][0]["objeto_id"]


def test_juntar_idempotente_e_conflito(tmp_path):
    trechos = ol.ler_obras_lineares(_planilha(tmp_path))
    a = eg.de_obras_lineares(trechos, "p.xlsx")
    assert eg.juntar(a, a) == eg.juntar(a)
    b = eg.de_obras_lineares(trechos, "outra.xlsx")
    with pytest.raises(ValueError, match="EV-OL-4"):
        eg.juntar(a, b)
