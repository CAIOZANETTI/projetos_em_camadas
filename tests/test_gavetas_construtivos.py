"""Elementos construtivos nas gavetas (F2): objeto, geometria UTM, fatos, evidência com página e retângulo, pendências."""

import numpy as np
import pytest

from camadas import gavetas, geo
from camadas import gavetas_construtivos as gc

EPSG = 31982
E0, N1 = 500000.0, 7000100.0  # canto superior esquerdo da prancha sintética (UTM)
M = [0.1, 0.0, E0, 0.0, -0.1, N1]  # pt → UTM: 0,1 m/pt, y do PDF para baixo
DOC = "003-SAA-FUNDACAO1-R2"
DOC_ID = "a1b2c3d4e5f60718"
PRANCHA = {
    "id": "fu1",
    "pdf": f"{DOC}.pdf",
    "M": M,
    "largura": 3000.0,
    "altura": 2000.0,
}


def _lonlat(utm: list[list[float]]) -> list[list[float]]:
    pts = np.asarray(utm, float)
    lon, lat = geo.para_lonlat(pts[:, 0], pts[:, 1], EPSG)
    return np.column_stack([lon, lat]).tolist()


def _feature(
    identificador, classe, geometria, atributos, doc=DOC, rotulo="PC6", extra=None
):
    propriedades = {
        "id": identificador,
        "rotulo": rotulo,
        "classe": classe,
        "unidade": "u1",
        "sistema": "u1-FILTROS",
        "etapa": None,
        "atributos": atributos,
        "fonte": f"fundação {doc} (camadas.prancha)",
        "doc": doc,
        "eap": ["U1.FILTROS.GEO.FUN.BLO"],
    }
    return {
        "type": "Feature",
        "geometry": geometria,
        "properties": {**propriedades, **(extra or {})},
    }


BLOCO_UTM = [
    [500100.0, 7000000.0],
    [500102.0, 7000000.0],
    [500102.0, 7000003.0],
    [500100.0, 7000003.0],
    [500100.0, 7000000.0],
]


def _bloco(**kwargs):
    atributos = kwargs.pop(
        "atributos",
        [
            ["Estacas", 4],
            ["Estacas por sistema", "FILTROS 4"],
            ["Face superior (cota, m)", 237.317],
            ["Arrasamento (cota, m)", 236.667],
            ["Ficha", "mod01_forma"],
        ],
    )
    geometria = {"type": "Polygon", "coordinates": [_lonlat(BLOCO_UTM)]}
    return _feature("u1-FILTROS-bloco-PC6", "bloco", geometria, atributos, **kwargs)


def _construtivos(*features):
    return {"geojson": {"type": "FeatureCollection", "features": list(features)}}


def _gerar(*features, documentos=None, pranchas=None):
    documentos = {DOC: DOC_ID} if documentos is None else documentos
    pranchas = [PRANCHA] if pranchas is None else pranchas
    return gc.de_construtivos(_construtivos(*features), pranchas, documentos, EPSG)


def _fatos(base, objeto_id):
    return {f["propriedade"]: f for f in base["fatos"] if f["objeto_id"] == objeto_id}


def _com_documentos(base):
    """Acrescenta `documentos` e `paginas` para a conferência exigir a página no localizador."""
    return {
        **base,
        "documentos": [
            {
                "documento_id": DOC_ID,
                "arquivo": f"{DOC}.pdf",
                "sha256": "ab" * 32,
                "extensao": ".pdf",
                "classe": "projeto",
                "paginas": 1,
            }
        ],
        "paginas": [
            {
                "pagina_id": gavetas.id_pagina(DOC_ID, 1),
                "documento_id": DOC_ID,
                "pagina": 1,
                "largura_pt": 3000.0,
                "altura_pt": 2000.0,
            }
        ],
    }


def test_objeto_com_classe_unidade_e_sistema():
    base = _gerar(_bloco())
    assert base["objetos"] == [
        {
            "objeto_id": "u1-FILTROS-bloco-PC6",
            "classe": "bloco",
            "unidade": "u1",
            "sistema": "u1-FILTROS",
        }
    ]


def test_geometria_em_utm_ida_e_volta():
    base = _gerar(_bloco())
    g = base["geometria"][0]
    assert (g["tipo"], g["crs_h"], g["datum_v"]) == (
        "poligono",
        "EPSG:31982",
        "ortométrico",
    )
    np.testing.assert_allclose(
        g["coords"], BLOCO_UTM, atol=0.002
    )  # tolerância absoluta (m)
    volta = _lonlat(g["coords"])
    original = _bloco()["geometry"]["coordinates"][0]
    np.testing.assert_allclose(volta, original, atol=1e-7)  # ~1 cm em graus


def test_estaca_vira_ponto_e_a_posicao_nao_vira_pendencia():
    ponto = {"type": "Point", "coordinates": _lonlat([[500050.0, 7000050.0]])[0]}
    estaca = _feature(
        "u1-FILTROS-estaca-E1",
        "estaca",
        ponto,
        [
            ["Diâmetro nominal (cm)", 40.0],
            ["Comprimento (m)", 6.0],
            ["E (m)", 500050.0],
            ["N (m)", 7000050.0],
        ],
        rotulo="E1",
    )
    base = _gerar(estaca)
    assert base["geometria"][0]["tipo"] == "ponto"
    np.testing.assert_allclose(
        base["geometria"][0]["coords"], [500050.0, 7000050.0], atol=0.002
    )
    fatos = _fatos(base, "u1-FILTROS-estaca-E1")
    assert fatos["diametro_m"]["valor"] == pytest.approx(0.4, abs=1e-9)  # cm → m
    assert fatos["comprimento_m"]["valor"] == 6.0
    assert base["pendencias"] == []
    assert "area_planta_m2" not in fatos


def test_fatos_dos_atributos_mapeados():
    fatos = _fatos(_gerar(_bloco()), "u1-FILTROS-bloco-PC6")
    assert fatos["estacas_n"]["valor"] == 4
    assert fatos["cota_topo_m"]["valor"] == 237.317
    assert fatos["cota_arrasamento_m"]["valor"] == 236.667
    assert fatos["rotulo"]["valor"] == "PC6"
    assert fatos["unidade"]["valor"] == "u1"
    assert (
        fatos["sistema"]["valor"] == "FILTROS"
    )  # a chave de unidades_construtivas.json
    assert all(f["natureza"] in ("projetado", "inferido") for f in fatos.values())
    assert {f["evidencia_id"] for f in fatos.values()} == {"EV-CO-u1-FILTROS-bloco-PC6"}


def test_medidas_da_geometria_como_fatos_projetados():
    fatos = _fatos(_gerar(_bloco()), "u1-FILTROS-bloco-PC6")
    assert fatos["area_planta_m2"]["valor"] == pytest.approx(6.0, abs=0.01)
    assert fatos["perimetro_m"]["valor"] == pytest.approx(10.0, abs=0.01)
    assert fatos["area_planta_m2"]["natureza"] == "projetado"


def test_area_do_atributo_vence_e_diferenca_grande_vira_pendencia():
    cava = _bloco(atributos=[["Área (m²)", 20.0]])
    base = _gerar(cava)
    fato = _fatos(base, "u1-FILTROS-bloco-PC6")["area_planta_m2"]
    assert fato["valor"] == 20.0
    assert [f["fato_id"] for f in base["fatos"]].count(fato["fato_id"]) == 1
    assert any("difere da geometria" in p["motivo"] for p in base["pendencias"])


def test_retangulo_em_pt_pela_inversa_da_afim():
    evidencia = _gerar(_bloco())["evidencias"][0]
    assert evidencia["documento"] == DOC_ID
    assert evidencia["classe"] == "projeto"
    assert (evidencia["metodo"], evidencia["executor"]) == ("camadas.prancha", "código")
    loc = evidencia["localizador"]
    assert loc["pagina"] == 1
    # x = (E - E0) / 0,1 ; y = (N1 - N) / 0,1
    esperado = [
        (500100 - E0) / 0.1,
        (N1 - 7000003) / 0.1,
        (500102 - E0) / 0.1,
        (N1 - 7000000) / 0.1,
    ]
    np.testing.assert_allclose(loc["retangulo_pt"], esperado, atol=0.05)
    # idas e voltas: a afim aplicada ao canto do retângulo devolve o UTM
    m = np.vstack([np.reshape(M, (2, 3)), [0, 0, 1]])
    canto = geo.aplicar(m, np.array([loc["retangulo_pt"][:2]]))[0]
    np.testing.assert_allclose(canto, [500100.0, 7000003.0], atol=0.01)


def test_afim_3x3_e_nome_com_extensao_em_qualquer_caixa():
    prancha = {
        **PRANCHA,
        "M": np.vstack([np.reshape(M, (2, 3)), [0, 0, 1]]).tolist(),
        "pdf": f"{DOC}.PDF",
    }
    base = _gerar(_bloco(), documentos={f"{DOC}.pdf": DOC_ID}, pranchas=[prancha])
    assert "retangulo_pt" in base["evidencias"][0]["localizador"]


def test_atributo_sem_propriedade_vira_pendencia_e_nao_vira_fato():
    base = _gerar(_bloco())
    motivos = [p["motivo"] for p in base["pendencias"]]
    assert "atributo sem propriedade em gavetas.json: Ficha" in motivos
    assert "atributo sem propriedade em gavetas.json: Estacas por sistema" in motivos
    assert all(p["objeto_id"] == "u1-FILTROS-bloco-PC6" for p in base["pendencias"])
    assert not {"ficha", "estacas_por_sistema"} & set(
        _fatos(base, "u1-FILTROS-bloco-PC6")
    )


def test_faixa_de_texto_em_propriedade_numerica_vira_pendencia():
    cava = _bloco(atributos=[["Fundo (cota, m)", "235.05 a 237.50"]])
    base = _gerar(cava)
    assert "cota_fundo_m" not in _fatos(base, "u1-FILTROS-bloco-PC6")
    pendencia = next(
        p for p in base["pendencias"] if "valor não numérico" in p["motivo"]
    )
    assert "235.05 a 237.50" in pendencia["detalhe"]


def test_prancha_sem_documento_vira_evidencia_v1_e_pendencia():
    base = _gerar(_bloco(), documentos={})
    evidencia = base["evidencias"][0]
    assert evidencia["documento"] == DOC and isinstance(evidencia["localizador"], str)
    assert any("fora da gaveta documentos" in p["motivo"] for p in base["pendencias"])
    assert gavetas.conferir_base(base) == []


def test_prancha_fora_do_build_vira_evidencia_v1_e_pendencia():
    base = _gerar(_bloco(), pranchas=[])
    assert isinstance(base["evidencias"][0]["localizador"], str)
    assert any("fora das pranchas do build" in p["motivo"] for p in base["pendencias"])


def test_prancha_sem_afim_fica_so_com_a_pagina():
    base = _gerar(_bloco(), pranchas=[{**PRANCHA, "M": None}])
    assert base["evidencias"][0]["localizador"] == {"pagina": 1}
    assert any("sem afim" in p["motivo"] for p in base["pendencias"])


def test_elemento_fora_da_pagina_nao_inventa_retangulo():
    base = _gerar(_bloco(), pranchas=[{**PRANCHA, "largura": 100.0, "altura": 100.0}])
    assert base["evidencias"][0]["localizador"] == {"pagina": 1}
    assert any("fora da página" in p["motivo"] for p in base["pendencias"])


def test_trecho_multilinha_fica_com_a_mais_longa_e_avisa():
    partes = [
        _lonlat([[500000.0, 7000000.0], [500050.0, 7000000.0]]),
        _lonlat([[500050.0, 7000000.0], [500060.0, 7000000.0]]),
        _lonlat([[500200.0, 7000200.0], [500210.0, 7000200.0]]),
    ]
    trecho = _feature(
        "u2-AAT00-trecho-aat00_01",
        "trecho",
        {"type": "MultiLineString", "coordinates": partes},
        [
            ["Diâmetro (mm)", 315],
            ["Extensão estimada (m)", 30.0],
            ["Rede", "Adutora AAT00"],
        ],
        rotulo="AAT00 · folha 01",
    )
    base = _gerar(trecho)
    g = base["geometria"][0]
    assert g["tipo"] == "linha"
    np.testing.assert_allclose(g["coords"][0], [500000.0, 7000000.0], atol=0.002)
    np.testing.assert_allclose(
        g["coords"][-1], [500060.0, 7000000.0], atol=0.002
    )  # as duas primeiras se uniram
    fatos = _fatos(base, "u2-AAT00-trecho-aat00_01")
    assert (
        fatos["extensao_m"]["natureza"] == "inferido"
        and fatos["dn_mm"]["valor"] == 315.0
    )
    assert "comprimento_m" not in fatos  # o traço desenhado não é o tubo
    assert any("multipartes" in p["motivo"] for p in base["pendencias"])
    # o retângulo cobre as três partes, não só a linha guardada
    x0, y0, x1, y1 = base["evidencias"][0]["localizador"]["retangulo_pt"]
    assert x1 - x0 == pytest.approx(2100.0, abs=0.05) and y1 - y0 == pytest.approx(
        2000.0, abs=0.05
    )


def test_linha_sem_extensao_declarada_leva_o_comprimento_medido():
    reta = _feature(
        "u2-x-trecho-1",
        "trecho",
        {
            "type": "LineString",
            "coordinates": _lonlat([[500000.0, 7000000.0], [500030.0, 7000040.0]]),
        },
        [],
    )
    fatos = _fatos(_gerar(reta), "u2-x-trecho-1")
    assert fatos["comprimento_m"]["valor"] == pytest.approx(50.0, abs=0.01)
    assert fatos["comprimento_m"]["natureza"] == "projetado"


def test_base_confere_sem_erro_com_documentos_e_paginas():
    base = _com_documentos(_gerar(_bloco()))
    assert gavetas.conferir_base(base) == []
    sem_pagina = _com_documentos(_gerar(_bloco(), pranchas=[]))
    sem_pagina["evidencias"][0]["documento"] = (
        DOC_ID  # documento registrado com localizador de texto: a conferência reprova
    )
    assert any("sem página" in e for e in gavetas.conferir_base(sem_pagina))


def test_determinismo_e_resumo():
    features = [_bloco(), _bloco(atributos=[["Estacas", 2]])]
    features[1]["properties"]["id"] = "u1-FILTROS-bloco-PC7"
    a, b = _gerar(*features), _gerar(*features)
    assert a == b
    r = gc.resumo(a)
    assert r["objetos"] == 2 and r["objetos_por_classe"] == {"bloco": 2}
    assert r["fatos_por_propriedade"]["estacas_n"] == 2
    assert r["elementos_com_pagina"] == r["elementos_com_pagina_e_retangulo"] == 2
    assert r["pendencias"] == sum(r["pendencias_por_motivo"].values())
