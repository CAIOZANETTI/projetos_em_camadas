"""Testes do schema do furo, da validação e do leitor de laudo de sondagem (camadas/geotecnia.py)."""

import copy
from itertools import pairwise
import json

import pytest

from camadas import geotecnia as geo

TOLERANCIA_M = 0.01

COORDENADAS = [
    "TABELA DE COORDENADAS DOS FUROS (SIRGAS 2000 / UTM 22S)",
    "Furo     E (m)         N (m)          Cota (m)",
    "SP-01    654.321,50    7.321.456,25   215,40",
    "SP-02    654.380,00    7.321.500,10   214,85",
    "SP-03    654.450,75    7.321.390,00   216,10",
]
PERFIS = {
    "SP-01": [
        "PERFIL INDIVIDUAL DE SONDAGEM - SP-01",
        "0,00 - 1,50 Aterro argiloso marrom",
        "1,50 - 4,00 Argila siltosa vermelha",
        "N.A.: 2,30 m",
        "Profundidade (m)   NSPT",
        "1,00  4",
        "2,00  6",
        "3,00  9",
    ],
    "SP-02": [
        "PERFIL INDIVIDUAL DE SONDAGEM - SP-02",
        "de 0,00 a 2,00 m Areia fina fofa",
        "de 2,00 a 5,50 m Basalto alterado",
        "NÍVEL D'ÁGUA: NÃO ATINGIDO",
        "1,00  3",
        "2,00  12",
    ],
    "SP-03": [
        "PERFIL INDIVIDUAL DE SONDAGEM - SP-03",
        "0,00 - 3,00 Silte arenoso",
        "3,00 - 3,80 Rocha sã",
        "N.A. 1,10 m",
        "Limite de sondagem: IMPENETRÁVEL ao amostrador",
        "1,00  5",
        "2,00  8",
    ],
}


def _gerar_pdf(caminho, paginas):
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    for linhas in paginas:
        pagina = doc.new_page()
        for i, linha in enumerate(linhas):
            pagina.insert_text((50, 60 + 18 * i), linha, fontsize=10)
    doc.save(caminho)
    doc.close()
    return caminho


@pytest.fixture
def laudo(tmp_path):
    return _gerar_pdf(
        tmp_path / "laudo.pdf",
        [COORDENADAS, PERFIS["SP-01"] + [""] + PERFIS["SP-02"], PERFIS["SP-03"]],
    )


def test_laudo_sintetico_le_tres_furos(laudo):
    r = geo.ler_laudo(laudo)
    assert r["paginas_lidas"] == 3 and r["nao_lidos"] == []
    f = {x["id"]: x for x in r["furos"]}
    assert set(f) == {"SP-01", "SP-02", "SP-03"}
    assert (
        abs(f["SP-01"]["E"] - 654321.50) <= TOLERANCIA_M
        and abs(f["SP-01"]["N"] - 7321456.25) <= TOLERANCIA_M
    )
    assert (
        abs(f["SP-03"]["E"] - 654450.75) <= TOLERANCIA_M
        and abs(f["SP-03"]["N"] - 7321390.00) <= TOLERANCIA_M
    )
    assert abs(f["SP-02"]["cota_boca"] - 214.85) <= TOLERANCIA_M


def test_laudo_na_impenetravel_camadas_e_nspt(laudo):
    f = {x["id"]: x for x in geo.ler_laudo(laudo)["furos"]}
    assert f["SP-01"]["na_m"] == pytest.approx(2.30, abs=TOLERANCIA_M)
    assert f["SP-02"]["na_m"] is None  # "NÃO ATINGIDO"
    assert f["SP-03"]["na_m"] == pytest.approx(1.10, abs=TOLERANCIA_M)
    assert f["SP-03"]["impenetravel"] is True and f["SP-01"]["impenetravel"] is False
    for furo in f.values():
        camadas = furo["camadas"]
        assert all(c["ate"] > c["de"] for c in camadas)
        assert all(a["ate"] <= b["de"] + TOLERANCIA_M for a, b in pairwise(camadas))
    assert [c["descricao"] for c in f["SP-02"]["camadas"]] == [
        "Areia fina fofa",
        "Basalto alterado",
    ]
    assert f["SP-01"]["nspt"] == [[1.0, 4], [2.0, 6], [3.0, 9]]
    assert f["SP-01"]["profundidade_m"] == pytest.approx(4.0, abs=TOLERANCIA_M)


def test_furo_citado_sem_coordenada_vai_para_nao_lidos(tmp_path):
    perfil_extra = [
        "PERFIL INDIVIDUAL DE SONDAGEM - SP-09",
        "0,00 - 2,00 Argila mole",
        "N.A.: 1,00 m",
    ]
    pdf = _gerar_pdf(
        tmp_path / "l.pdf",
        [COORDENADAS, PERFIS["SP-01"], PERFIS["SP-02"] + PERFIS["SP-03"], perfil_extra],
    )
    r = geo.ler_laudo(pdf)
    assert len(r["furos"]) == 3
    assert [n["id"] for n in r["nao_lidos"]] == ["SP-09"]
    assert "coordenada" in r["nao_lidos"][0]["motivo"]


def test_furo_com_coordenada_sem_camadas_vai_para_nao_lidos(tmp_path):
    pdf = _gerar_pdf(
        tmp_path / "l.pdf", [COORDENADAS, PERFIS["SP-01"], PERFIS["SP-02"]]
    )
    r = geo.ler_laudo(pdf)
    assert [x["id"] for x in r["furos"]] == ["SP-01", "SP-02"]
    assert [n["id"] for n in r["nao_lidos"]] == ["SP-03"]
    assert "camadas" in r["nao_lidos"][0]["motivo"]


def test_cli_grava_sondagens_json(laudo, tmp_path, capsys):
    saida = tmp_path / "sondagens.json"
    geo.main([str(laudo), "--saida", str(saida)])
    assert "3 furos lidos" in capsys.readouterr().out
    dados = json.loads(saida.read_text(encoding="utf-8"))
    validos, erros = geo.validar_furos(dados)
    assert len(validos) == 3 and erros == []


FURO_FOZ = {
    "id": "SP-02",
    "E": 654380.0,
    "N": 7321500.1,
    "epsg": 31982,
    "cota_boca": 214.85,
    "na_m": 9.0,
    "profundidade_m": 8.0,
    "impenetravel": False,
    "camadas": [
        {"de": 0, "ate": 1.0, "descricao": "Aterro argiloso", "classe": "aterro"},
        {"de": 1.0, "ate": 8, "descricao": "Argila siltosa"},
    ],
    "nspt": [[1.0, 4], [2.0, 6]],
    "fonte": "laudo.pdf",
}


def _motivos(**mudancas):
    furo = copy.deepcopy(FURO_FOZ)
    furo.update(mudancas)
    validos, erros = geo.validar_furos([furo])
    return validos, [e["motivo"] for e in erros]


def test_validar_aceita_furo_no_formato_de_foz():
    for entrada in ([FURO_FOZ], {"meta": {}, "furos": [FURO_FOZ]}):
        validos, erros = geo.validar_furos(entrada)
        assert validos == [FURO_FOZ] and erros == []
    sem_opcionais = {"id": "SP-1", "E": 1.0, "N": 2.0, "na_m": None}
    assert geo.validar_furos([sem_opcionais])[0] == [sem_opcionais]
    assert validos[0] is FURO_FOZ  # nada é copiado nem renomeado


def test_validar_acusa_cada_erro():
    assert "sem id" in _motivos(id="")[1]
    assert any("E ausente" in m for m in _motivos(E=None)[1])
    assert any("N ausente" in m for m in _motivos(N="abc")[1])
    assert any(
        "ate <= de" in m
        for m in _motivos(camadas=[{"de": 2.0, "ate": 1.0, "descricao": "x"}])[1]
    )
    fora = [
        {"de": 3.0, "ate": 5.0, "descricao": "x"},
        {"de": 0.0, "ate": 2.0, "descricao": "y"},
    ]
    assert any(
        "fora de ordem" in m for m in _motivos(camadas=fora, profundidade_m=5.0)[1]
    )
    assert any("na_m" in m for m in _motivos(na_m=-1.0)[1])
    assert any("profundidade_m" in m for m in _motivos(profundidade_m=7.5)[1])
    assert _motivos(profundidade_m=7.995)[1] == []  # dentro da tolerância de 0,01 m
    validos, erros = geo.validar_furos([{"E": 1, "N": 2}, FURO_FOZ])
    assert validos == [FURO_FOZ] and erros[0]["id"] is None


def test_premissas_da_decisao_d1():
    dados = json.loads(geo.CONCEITOS.read_text(encoding="utf-8"))
    for chave in ("fonte", "estado", "data_referencia", "observacoes"):
        assert dados["metadata"][chave]
    premissas = dados["premissas"]
    assert premissas["raio_influencia_m"]["valor"] == 60
    assert premissas["margem_na_m"]["valor"] == 0
    assert (
        premissas["empolamento"]["solo"] == 1.30
        and premissas["empolamento"]["rocha"] == 1.50
    )
    assert all(premissas[p]["fonte"] and premissas[p]["estado"] for p in premissas)
    schema = dados["schema_furo"]
    for campo in (
        "id",
        "E",
        "N",
        "epsg",
        "cota_boca",
        "na_m",
        "profundidade_m",
        "impenetravel",
        "camadas",
        "nspt",
        "fonte",
    ):
        assert {"tipo", "unidade", "obrigatorio"} <= set(schema[campo])
    assert schema["E"]["unidade"] == "m" and schema["id"]["obrigatorio"] is True


def test_metadados():
    assert geo.metadados()["modulo"] == "geotecnia"
