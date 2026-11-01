"""Testes do schema do furo, da validação e do leitor de laudo de sondagem (camadas/geotecnia.py)."""

import copy
import json
from itertools import pairwise

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


def test_preposicao_na_nao_vira_nivel_dagua():
    """Revisão do Fable (rodada 25): "na" em maiúsculas na descrição da camada não é N.A.; o NA sai da linha certa."""
    linhas = ["0,00 - 2,00 ARGILA MOLE NA COTA 3,00 M", "N.A.: 1,00 m"]
    achou, na_m = geo._nivel_dagua(linhas)
    assert achou and na_m == pytest.approx(1.0, abs=0.001)
    assert geo._nivel_dagua(["AREIA FINA NA BASE"]) == (False, None)
    achou, na_m = geo._nivel_dagua(["NA: 2,40"])
    assert achou and na_m == pytest.approx(2.4, abs=0.001)
    assert geo._nivel_dagua(["LENÇOL FREÁTICO NÃO ATINGIDO"]) == (True, None)


# --------------------------------------------------------------------------------------------------------------------
# G2: modelo geotécnico único
# --------------------------------------------------------------------------------------------------------------------


def _furo(**mudancas):
    """Furo sintético: aterro 0-1, argila 1-3, areia 3-5, basalto alterado 5-6, rocha 6-8; NA a 2 m; boca na cota 100."""
    furo = {
        "id": "SP-01",
        "E": 1000.0,
        "N": 2000.0,
        "cota_boca": 100.0,
        "na_m": 2.0,
        "profundidade_m": 8.0,
        "camadas": [
            {"de": 0.0, "ate": 1.0, "descricao": "Aterro de entulho"},
            {"de": 1.0, "ate": 3.0, "descricao": "Argila siltosa vermelha"},
            {"de": 3.0, "ate": 5.0, "descricao": "Areia fina"},
            {"de": 5.0, "ate": 6.0, "descricao": "Basalto alterado"},
            {"de": 6.0, "ate": 8.0, "descricao": "Basalto são"},
        ],
    }
    return {**furo, **mudancas}


def test_classe_solo_regras_vem_do_json():
    assert geo.classe_solo("Argila siltosa")["classe"] == "argila"
    assert (
        geo.classe_solo("Aterro argiloso")["classe"] == "aterro"
    )  # a 1ª regra que casa decide
    alterado = geo.classe_solo("Basalto alterado")
    assert (alterado["classe"], alterado["categoria"]) == (
        "rocha_alterada",
        "2ª categoria",
    )
    assert geo.classe_solo("Basalto são")["categoria"] == "3ª categoria"
    assert geo.classe_solo("x", "AREIA")["classe"] == "areia"  # classe já dada
    assert geo.classe_solo("") == {"classe": "indefinido", "categoria": "a definir"}
    arquivo = json.loads(geo.CONCEITOS.read_text(encoding="utf-8"))
    assert geo.REGRAS["solos"]["classes"] == arquivo["solos"]["classes"]


def test_obras_lineares_nao_tem_regra_propria_de_solo():
    from camadas import obras_lineares as ol

    assert "solos" not in ol.REGRAS and "raio_influencia_m" not in ol.REGRAS
    assert "empolamento" not in ol.REGRAS
    assert ol.classe_solo("Areia fina") == geo.classe_solo("Areia fina")
    assert ol.solo_na_vala(_furo(), 4.0) == geo.solo_na_faixa(_furo(), 0.0, 4.0)


def test_solo_na_faixa_fracoes():
    f = geo.solo_na_faixa(_furo(), 0.0, 4.0)
    assert f["aterro"] == pytest.approx(0.25, abs=1e-9)
    assert f["argila"] == pytest.approx(0.5, abs=1e-9)
    assert f["areia"] == pytest.approx(0.25, abs=1e-9)
    # faixa que não começa na boca
    g = geo.solo_na_faixa(_furo(), 2.0, 4.0)
    assert g == {"argila": pytest.approx(0.5), "areia": pytest.approx(0.5)}
    # além do fim da sondagem: o resto é indefinido
    h = geo.solo_na_faixa(_furo(), 6.0, 10.0)
    assert h["rocha"] == pytest.approx(0.5, abs=1e-9)
    assert h["indefinido"] == pytest.approx(0.5, abs=1e-9)
    assert sum(h.values()) == pytest.approx(1.0, abs=1e-9)
    assert geo.solo_na_faixa(_furo(), 3.0, 3.0) == {}


def test_categoria_escavacao_fracoes():
    c = geo.categoria_escavacao(_furo(), 0.0, 8.0)
    assert c["1ª categoria"] == pytest.approx(5 / 8, abs=1e-9)
    assert c["2ª categoria"] == pytest.approx(1 / 8, abs=1e-9)
    assert c["3ª categoria"] == pytest.approx(2 / 8, abs=1e-9)
    assert geo.categoria_escavacao(_furo(), 0.0, 10.0)["a definir"] == pytest.approx(
        0.2, abs=1e-9
    )


def test_na_m_com_e_sem_margem_e_nao_atingido():
    assert geo.na_m(_furo()) == pytest.approx(2.0, abs=1e-9)  # margem padrão 0 m
    assert geo.na_m(_furo(), margem_m=0.5) == pytest.approx(1.5, abs=1e-9)
    assert geo.na_m(_furo(), margem_m=5.0) == pytest.approx(0.0, abs=1e-9)
    assert geo.na_m(_furo(na_m=None)) is None


def test_topo_rocha_m():
    assert geo.topo_rocha_m(_furo()) == pytest.approx(
        6.0, abs=1e-9
    )  # alterada não conta
    sem_rocha = _furo(camadas=_furo()["camadas"][:3], profundidade_m=5.0)
    assert geo.topo_rocha_m(sem_rocha) is None
    assert geo.topo_rocha_m({**sem_rocha, "impenetravel": True}) == pytest.approx(
        5.0, abs=1e-9
    )
    assert geo.topo_rocha_m({"camadas": [], "impenetravel": True}) is None
    assert geo.topo_rocha_m({"id": "x"}) is None


def test_perfil_em_vetorizado_e_raio():
    furos = [_furo(), _furo(id="SP-02", E=1100.0, N=2000.0)]
    p = geo.perfil_em(1010.0, 2000.0, furos)
    assert p["furo"]["id"] == "SP-01"
    assert p["distancia_m"] == pytest.approx(10.0, abs=1e-6)
    assert p["dentro_do_raio"] and p["alerta"] is None
    p = geo.perfil_em(1070.0, 2000.0, furos)  # SP-02 a 30 m
    assert p["furo"]["id"] == "SP-02" and p["distancia_m"] == pytest.approx(
        30.0, abs=1e-6
    )
    fora = geo.perfil_em(1000.0, 2200.0, furos)  # 200 m do SP-01
    assert fora["furo"]["id"] == "SP-01" and not fora["dentro_do_raio"]
    assert (
        fora["distancia_m"] == pytest.approx(200.0, abs=1e-6)
        and "raio" in fora["alerta"]
    )
    assert geo.perfil_em(0.0, 0.0, []) is None
    assert geo.perfil_em(0.0, 0.0, [{"id": "sem coordenada"}]) is None
    assert geo.perfil_em(1000.0, 2200.0, furos, raio_m=300.0)["dentro_do_raio"]


def test_furo_mais_proximo_varios_pontos():
    furos = [_furo(), _furo(id="SP-02", E=1100.0)]
    indices, distancias_m = geo.furo_mais_proximo(
        [[1000, 2000], [1090, 2000], [1500, 2000]], furos
    )
    assert list(indices) == [0, 1, 1]
    assert distancias_m == pytest.approx([0.0, 10.0, 400.0], abs=1e-6)


def test_alerta_na_sazonal():
    f = _furo()  # NA a 2,0 m
    assert geo.alerta_na(f, 1.4) is None  # 0,6 m acima do NA
    assert geo.alerta_na(f, 1.5) is None  # exatamente na folga
    assert "a menos de 0,5 m do NA" in geo.alerta_na(f, 1.8)
    assert "abaixo do NA" in geo.alerta_na(f, 3.0)
    assert geo.alerta_na(_furo(na_m=None), 5.0) is None  # NA não atingido
    assert geo.alerta_na(f, 1.0, folga_m=1.5) is not None


def test_validar_acusa_camadas_que_nao_e_lista():
    validos, erros = geo.validar_furos(
        [_furo(camadas="argila"), _furo(camadas={"de": 0})]
    )
    assert validos == [] and len(erros) == 2
    assert all(e["motivo"] == "camadas não é uma lista" for e in erros)
    validos, erros = geo.validar_furos([_furo(camadas=["argila"])])
    assert validos == [] and "item" in erros[0]["motivo"]
    assert geo.validar_furos([_furo()])[1] == []


def test_metadados_citam_funcoes_existentes():
    m = geo.metadados()
    assert all(hasattr(geo, f) for f in m["funcoes"])


# --------------------------------------------------------------------------------------------------------------------
# G3: conferências projeto × sondagem
# --------------------------------------------------------------------------------------------------------------------
# topo da rocha a 6 m de profundidade, boca na cota 100: cota do topo = 94; NA a 2 m: cota 98


def _estaca(id_, ponta_m, E=1010.0, N=2000.0):
    """Estaca com arrasamento na cota 99 e comprimento tal que a ponta fique na cota `ponta_m`."""
    return {
        "id": id_,
        "E": E,
        "N": N,
        "cota_arrasamento": 99.0,
        "comprimento_m": 99.0 - ponta_m,
    }


def test_conferir_estaca_nao_chega_e_passa_e_cala_no_caso_bom():
    estacas = [
        _estaca("E1", 95.0),
        _estaca("E2", 92.5),
        _estaca("E3", 94.05),
        _estaca("E4", 93.95),
    ]
    r = geo.conferir([_furo()], estacas=estacas)
    por_id = {o["objeto_id"]: o for o in r}
    assert set(por_id) == {"E1", "E2"}  # E3 e E4 dentro de 0,10 m
    assert (
        por_id["E1"]["valores"]["situacao"] == "nao_chega"
        and "não chega" in por_id["E1"]["mensagem"]
    )
    assert por_id["E1"]["valores"]["diferenca_m"] == pytest.approx(1.0, abs=1e-6)
    assert (
        por_id["E2"]["valores"]["situacao"] == "passa"
        and "passa do impenetrável" in por_id["E2"]["mensagem"]
    )
    assert por_id["E2"]["valores"]["diferenca_m"] == pytest.approx(-1.5, abs=1e-6)
    assert por_id["E1"]["valores"]["cota_topo_impenetravel_m"] == pytest.approx(
        94.0, abs=1e-6
    )
    assert (
        por_id["E1"]["tipo"] == "estaca_x_impenetravel"
        and por_id["E1"]["furo"] == "SP-01"
    )
    assert por_id["E1"]["distancia_m"] == pytest.approx(10.0, abs=1e-3)


def test_conferir_estaca_tolerancia_configuravel():
    estaca = _estaca("E1", 94.5)  # 0,5 m acima do topo
    assert geo.conferir([_furo()], estacas=[estaca]) != []
    assert geo.conferir([_furo()], estacas=[estaca], tolerancia_m=0.6) == []
    assert geo.TOLERANCIA_CONFERENCIA_M == pytest.approx(0.10, abs=1e-12)


def test_conferir_estaca_usa_impenetravel_e_o_furo_mais_proximo():
    impenetravel = _furo(
        id="SP-02",
        E=1100.0,
        impenetravel=True,
        profundidade_m=10.0,
        camadas=_furo()["camadas"][:3],
    )
    estacas = [_estaca("E1", 90.0, E=1095.0)]  # topo em 90 (100 - 10): ponta no topo
    assert geo.conferir([_furo(), impenetravel], estacas=estacas) == []
    estacas = [_estaca("E1", 94.0, E=1095.0)]
    r = geo.conferir([_furo(), impenetravel], estacas=estacas)
    assert r[0]["furo"] == "SP-02" and r[0]["valores"]["situacao"] == "nao_chega"


def test_conferir_estaca_sem_dados_ou_fora_do_raio():
    sem_rocha = _furo(camadas=_furo()["camadas"][:3], profundidade_m=5.0)
    assert (
        geo.conferir([sem_rocha], estacas=[_estaca("E1", 95.0)]) == []
    )  # sem rocha: nada a conferir
    sem_cota = {k: v for k, v in _furo().items() if k != "cota_boca"}
    assert geo.conferir([sem_cota], estacas=[_estaca("E1", 95.0)]) == []
    r = geo.conferir([_furo()], estacas=[_estaca("E9", 95.0, E=1500.0)])  # a 500 m
    assert [o["tipo"] for o in r] == ["sem_furo_no_raio"]
    assert r[0]["distancia_m"] == pytest.approx(500.0, abs=1e-3)
    assert geo.conferir([], estacas=[_estaca("E9", 95.0)])[0]["furo"] is None


def test_conferir_cava_abaixo_do_na_pede_esgotamento():
    cavas = [
        {
            "id": "C1",
            "E_m": 1005.0,
            "N_m": 2000.0,
            "cota_fundo_m": 96.5,
        },  # NA na cota 98: 1,5 m abaixo
        {"id": "C2", "E_m": 1005.0, "N_m": 2000.0, "cota_fundo_m": 98.5},  # acima do NA
        {
            "id": "C3",
            "E_m": 1005.0,
            "N_m": 2000.0,
            "cota_fundo_m": 97.95,
        },  # 0,05 m abaixo: dentro da tolerância
    ]
    r = geo.conferir([_furo()], cavas=cavas)
    assert [o["objeto_id"] for o in r] == ["C1"]
    assert r[0]["tipo"] == "cava_x_na" and "esgotamento necessário" in r[0]["mensagem"]
    assert r[0]["valores"]["diferenca_m"] == pytest.approx(1.5, abs=1e-6)
    assert r[0]["valores"]["cota_na_m"] == pytest.approx(98.0, abs=1e-6)
    assert r[0]["furo"] == "SP-01" and r[0]["distancia_m"] == pytest.approx(
        5.0, abs=1e-3
    )


def test_conferir_cava_na_nao_atingido_ou_fora_do_raio():
    cava = {"id": "C1", "E_m": 1005.0, "N_m": 2000.0, "cota_fundo_m": 90.0}
    assert geo.conferir([_furo(na_m=None)], cavas=[cava]) == []
    longe = {**cava, "id": "C2", "E_m": 1400.0}
    assert [o["tipo"] for o in geo.conferir([_furo()], cavas=[longe])] == [
        "sem_furo_no_raio"
    ]


def test_conferir_trecho_sem_furo_no_raio():
    furos = [_furo()]  # em (1000, 2000), raio 60 m
    dentro = {"id": "T1", "pontos_m": [[1000.0, 2000.0], [1050.0, 2000.0]]}
    assert geo.conferir(furos, trechos=[dentro]) == []
    # 200 m em linha reta a partir do furo: ~60 m de 200 m dentro do raio
    longo = {"id": "T2", "pontos_m": [[1000.0, 2000.0], [1200.0, 2000.0]]}
    r = geo.conferir(furos, trechos=[longo])
    assert (
        len(r) == 1 and r[0]["tipo"] == "trecho_sem_furo" and r[0]["objeto_id"] == "T2"
    )
    assert r[0]["valores"]["fracao_sem_furo"] == pytest.approx(0.7, abs=0.01)
    assert r[0]["furo"] == "SP-01" and r[0]["distancia_m"] == pytest.approx(
        200.0, abs=1e-3
    )
    # polilinha com curva e sem nenhum furo
    sem = geo.conferir(
        [], trechos=[{"id": "T3", "pontos_m": [[0, 0], [10, 0], [10, 10]]}]
    )
    assert sem[0]["valores"]["fracao_sem_furo"] == pytest.approx(1.0, abs=1e-9)
    assert sem[0]["furo"] is None


def test_conferir_sem_entradas_e_formato_da_ocorrencia():
    assert geo.conferir([_furo()]) == []
    o = geo.conferir([_furo()], estacas=[_estaca("E1", 95.0)])[0]
    assert set(o) == {"tipo", "objeto_id", "furo", "distancia_m", "mensagem", "valores"}
    json.dumps(o)  # serializável


# --------------------------------------------------------------------------------------------------------------------
# F: boca do furo × terreno e estaca sem coordenada


def test_conferir_boca_x_terreno_acusa_alem_da_tolerancia_e_cala_dentro():
    # boca na cota 100; terreno do MDS 99,2 (boca 0,8 m acima) e 100,3 (dentro de 0,50 m)
    r = geo.conferir([_furo()], terreno=[{"id": "SP-01", "terreno_m": 99.2}])
    assert [o["tipo"] for o in r] == ["boca_x_terreno"]
    assert r[0]["objeto_id"] == "SP-01" and r[0]["furo"] == "SP-01"
    assert r[0]["valores"]["diferenca_m"] == pytest.approx(0.8)
    assert "acima" in r[0]["mensagem"]
    abaixo = geo.conferir([_furo()], terreno=[{"id": "SP-01", "terreno_m": 100.9}])
    assert "abaixo" in abaixo[0]["mensagem"]
    assert geo.conferir([_furo()], terreno=[{"id": "SP-01", "terreno_m": 100.3}]) == []
    # a tolerância é configurável e absoluta
    estreita = geo.conferir(
        [_furo()], terreno=[{"id": "SP-01", "terreno_m": 100.3}], tolerancia_boca_m=0.2
    )
    assert estreita[0]["tipo"] == "boca_x_terreno"


def test_conferir_boca_x_terreno_sem_dados_nao_acusa():
    sem_cota = _furo()
    sem_cota.pop("cota_boca")
    assert geo.conferir([sem_cota], terreno=[{"id": "SP-01", "terreno_m": 90.0}]) == []
    assert geo.conferir([_furo()], terreno=[{"id": "SP-01", "terreno_m": None}]) == []
    assert geo.conferir([_furo()], terreno=[{"id": "OUTRO", "terreno_m": 90.0}]) == []
    assert geo.PREMISSAS["tolerancia_boca_m"]["valor"] == 0.5


def test_conferir_estaca_sem_coordenada_vira_ocorrencia():
    sem_en = _estaca("E7", 95.0)
    sem_en["E"] = None
    nan = _estaca("E8", 95.0)
    nan["N"] = float("nan")
    r = geo.conferir([_furo()], estacas=[sem_en, nan, _estaca("E1", 94.0)])
    assert [(o["tipo"], o["objeto_id"]) for o in r] == [
        ("sem_coordenada", "E7"),
        ("sem_coordenada", "E8"),
    ]
    assert r[0]["furo"] is None and "sem coordenada" in r[0]["mensagem"]
    json.dumps(r)
