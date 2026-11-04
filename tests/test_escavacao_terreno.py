"""Terreno composto das cavas (opção D): topografia no casco das curvas, MDS corrigido fora, costura entre os dois."""

import numpy as np
import pytest
from shapely.geometry import box

from camadas import conferencia_cavas as cc
from camadas import escavacao
from camadas import topografia as tp

RES = 0.5
N = 200  # grade de 100 m × 100 m
COTA_PLANA_M = 100.0
CASCO = (20.0, 80.0)  # casco quadrado das curvas: E e N entre 20 e 80 m
PLANO_E, PLANO_N, PLANO_A = (
    0.01,
    0.02,
    0.3,
)  # inclinação (m/m) e deslocamento (m) do MDS sobre a topografia


def _centros():
    col = (np.arange(N) + 0.5) * RES
    lin = N * RES - (np.arange(N) + 0.5) * RES
    return np.meshgrid(col, lin)


def _grade(com_morro: bool = False) -> dict:
    """MDS = topografia plana + plano inclinado (+ um morro de 0,5 m sobre a borda do casco, se pedido)."""
    e, n = _centros()
    mds = COTA_PLANA_M + PLANO_A + PLANO_E * (e - 50) + PLANO_N * (n - 50)
    if com_morro:
        mds = mds + 0.5 * np.exp(-((e - 20.0) ** 2 + (n - 50.0) ** 2) / (2 * 3.0**2))
    return {
        "e0": 0.0,
        "n1": N * RES,
        "res": RES,
        "forma": (N, N),
        "epsg": 31981,
        "terreno": mds.astype(np.float32),
        "valido": np.ones((N, N), bool),
        "edificacao": np.zeros((N, N), bool),
        "vegetacao_alta": np.zeros((N, N), bool),
    }


def _topografia_plana() -> np.ndarray:
    """Superfície das curvas: plana a 100 m dentro do casco quadrado, NaN fora (como o TIN)."""
    e, n = _centros()
    dentro = (e >= CASCO[0]) & (e <= CASCO[1]) & (n >= CASCO[0]) & (n <= CASCO[1])
    return np.where(dentro, COTA_PLANA_M, np.nan).astype(np.float32)


def test_dentro_e_a_topografia_fora_e_o_mds_menos_o_plano():
    g, topo = _grade(), _topografia_plana()
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"], faixa_costura_m=5.0)
    c = r["plano"]["coeficientes"]
    assert c["a_m"] == pytest.approx(PLANO_A, abs=0.01)
    assert c["b_e_m_por_m"] == pytest.approx(PLANO_E, abs=1e-3)
    assert c["b_n_m_por_m"] == pytest.approx(PLANO_N, abs=1e-3)
    topografia_pura = r["origem"] == tp.ORIGENS_TERRENO.index("topografia")
    assert topografia_pura.sum() > 0
    assert np.array_equal(r["terreno"][topografia_pura], topo[topografia_pura])
    fora = r["origem"] == tp.ORIGENS_TERRENO.index("mds_corrigido")
    esperado = g["terreno"].astype(np.float64) - tp._valor_do_plano(r["plano"], g)
    assert np.abs(r["terreno"][fora] - esperado[fora]).max() < 1e-3
    assert (
        np.abs(r["terreno"][fora] - COTA_PLANA_M).max() < 0.02
    )  # o MDS corrigido volta à cota da topografia
    assert not (r["origem"] == 0).any()  # nada some sem motivo


def test_costura_suaviza_o_salto_na_borda_do_casco():
    g, topo = _grade(com_morro=True), _topografia_plana()
    linha = N // 2 - 1  # N = 50 m, atravessa o morro na borda E = 20 m

    def maior_degrau(faixa_m: float) -> float:
        z = tp.compor_terreno(g, topo, g["vegetacao_alta"], faixa_costura_m=faixa_m)[
            "terreno"
        ][linha]
        return float(np.abs(np.diff(z)).max())

    sem_faixa, com_faixa = maior_degrau(0.25), maior_degrau(5.0)
    assert sem_faixa > 0.1  # quase sem faixa: o morro vira um degrau na borda
    assert (
        com_faixa < 0.08 and com_faixa < sem_faixa / 2
    )  # com 5 m de faixa só resta a inclinação do próprio morro
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"], faixa_costura_m=5.0)
    assert (r["origem"] == tp.ORIGENS_TERRENO.index("costura")).any()
    assert (
        r["resumo"]["area_m2"]["costura"] > 0 and r["resumo"]["faixa_costura_m"] == 5.0
    )


def test_edificacao_e_vegetacao_alta_fora_do_casco_ficam_sem_terreno():
    g, topo = _grade(), _topografia_plana()
    g["edificacao"][20:40, 150:170] = (
        True  # fora do casco (E de 75 m a 85 m, N de 80 a 90 m)
    )
    g["vegetacao_alta"][150:170, 20:40] = True
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"])
    assert np.isnan(r["terreno"][g["edificacao"] & np.isnan(topo)]).all()
    assert np.isnan(r["terreno"][g["vegetacao_alta"] & np.isnan(topo)]).all()
    assert (r["origem"][np.isnan(r["terreno"])] == 0).all()
    sem = r["resumo"]["sem_terreno"]
    assert sem["edificacao_m2"] > 0 and sem["vegetacao_alta_m2"] > 0
    assert sem["total_m2"] == pytest.approx(
        sem["edificacao_m2"] + sem["vegetacao_alta_m2"] + sem["fora_do_levantamento_m2"]
    )
    dentro = np.isfinite(topo)
    assert np.isfinite(
        r["terreno"][dentro]
    ).all()  # dentro do casco a topografia vale mesmo assim


def test_calcular_ignora_celula_sem_terreno():
    pytest.importorskip("rasterio")
    g = _grade()
    g["edificacao"][:, 140:] = True  # prédio a partir de E = 70 m, dentro do casco
    g["terreno"][:, 180:] = np.nan  # e nada de terreno a partir de E = 90 m
    base = [{"geom": box(45, 45, 55, 55), "etapa": "1ª etapa"}]
    marca = [{"utm": [50.0, 50.0], "cota": 98.0, "topo": False}]
    r = escavacao.calcular(base, marca, [], g)
    assert len(r["cavas"]) == 1
    assert (
        np.isfinite(r["cavas"][0]["escavacao_m3"]) and r["cavas"][0]["escavacao_m3"] > 0
    )


def test_sem_a_chave_o_terreno_fica_identico_byte_a_byte(tmp_path):
    pytest.importorskip("rasterio")
    g = _grade()
    antes, chaves = g["terreno"].tobytes(), set(g)
    for c in (None, {}, {"fonte": "mds"}):
        escavacao.terreno_composto(g, c, tmp_path)
    assert g["terreno"].tobytes() == antes and set(g) == chaves
    assert (
        "terreno"
        not in escavacao.calcular(
            [{"geom": box(45, 45, 55, 55), "etapa": None}],
            [{"utm": [50.0, 50.0], "cota": 98.0, "topo": False}],
            [],
            g,
        )["parametros"]
    )


def test_terreno_composto_liga_o_obra_json_e_guarda_a_origem(tmp_path, monkeypatch):
    pytest.importorskip("rasterio")
    pdf = tmp_path / "geoplanta.pdf"
    pdf.write_bytes(b"%PDF")
    g, topo = _grade(), _topografia_plana()
    original = g["terreno"].copy()
    monkeypatch.setattr(escavacao, "_curvas_da_topografia", lambda t, out: [])
    monkeypatch.setattr(tp, "superficie", lambda curvas, grade: topo)
    c = {
        "fonte": "topografia_e_mds",
        "justificativa": "teste",
        "faixa_costura_m": 5,
        "topografia": {
            "pdf": str(pdf),
            "M": [[1, 0, 0], [0, 1, 0]],
            "layers": ["Curvas_Mestras"],
        },
    }
    mensagens = []
    escavacao.terreno_composto(g, c, tmp_path, log=mensagens.append)
    assert np.array_equal(g["terreno_mds"], original) and not np.array_equal(
        g["terreno"], original
    )
    assert g["origem_terreno"].shape == g["terreno"].shape
    assert (
        g["terreno_resumo"]["fonte"] == "teste"
        and g["terreno_resumo"]["area_m2"]["topografia"] > 0
    )
    assert mensagens and "m² por origem" in mensagens[0]
    base = [{"geom": box(45, 45, 55, 55), "etapa": None}]
    marca = [{"utm": [50.0, 50.0], "cota": 98.0, "topo": False}]
    assert (
        escavacao.calcular(base, marca, [], g)["parametros"]["terreno"]["fonte"]
        == "teste"
    )


def test_topografia_ausente_deixa_o_mds_e_avisa(tmp_path):
    g = _grade()
    antes = g["terreno"].tobytes()
    c = {
        "fonte": "topografia_e_mds",
        "topografia": {
            "pdf": str(tmp_path / "nao_existe.pdf"),
            "M": [[1, 0, 0], [0, 1, 0]],
        },
    }
    mensagens = []
    escavacao.terreno_composto(g, c, tmp_path, log=mensagens.append)
    assert g["terreno"].tobytes() == antes and "pendência" in mensagens[0]


def test_composicao_com_tin_das_curvas():
    pytest.importorskip("scipy")
    anel = [(20.0, 20.0), (80.0, 20.0), (80.0, 80.0), (20.0, 80.0), (20.0, 20.0)]
    curvas = [
        {
            "cota_m": COTA_PLANA_M,
            "coords_utm": anel,
            "layer": "Curvas_Mestras",
            "origem": "rotulo",
            "alertas": [],
        },
        {
            "cota_m": COTA_PLANA_M,
            "coords_utm": [(50.0, 20.0), (50.0, 80.0)],
            "layer": "Curvas_Auxiliares",
            "origem": "rotulo",
            "alertas": [],
        },
    ]
    g = _grade()
    topo = tp.superficie(curvas, g)
    assert np.isnan(topo[0, 0]) and topo[N // 2, N // 2] == pytest.approx(COTA_PLANA_M)
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"])
    assert np.nanmax(np.abs(r["terreno"] - COTA_PLANA_M)) < 0.02


def test_regex_dos_layers_padrao_e_dados():
    assert tp._regex_dos_layers(None) == tp.CAMADAS_CURVAS
    regex = tp._regex_dos_layers(["Curvas_Mestras", "A.B"])
    assert regex == r"^(Curvas_Mestras|A\.B)$"


def test_conferencia_marca_o_terreno_do_modelo_como_circular():
    g = _grade()
    g["origem_terreno"] = np.full(
        (N, N), tp.ORIGENS_TERRENO.index("topografia"), np.uint8
    )
    g["origem_terreno"][:, 100:] = tp.ORIGENS_TERRENO.index("mds_corrigido")
    g["terreno_resumo"] = {
        "area_m2": {"topografia": 1.0},
        "sem_terreno": {"total_m2": 0.0},
    }
    linha = {
        "secao": "AA",
        "prancha": "es1",
        "inicio_utm": [10.0, 30.0],
        "fim_utm": [90.0, 30.0],
        "comprimento_m": 80.0,
    }
    p = cc.perfil_do_modelo(linha, g, np.zeros((N, N), np.float32))
    assert p["fracao_terreno_topografia"] == pytest.approx(0.5, abs=0.02)
    t = cc._terreno_do_modelo(g)
    assert t["circular_na_comparacao_de_terreno"] and "quase circular" in t["aviso"]
    sem = dict(g)
    sem.pop("terreno_resumo"), sem.pop("origem_terreno")
    assert cc._terreno_do_modelo(sem) is None
    assert (
        cc.perfil_do_modelo(linha, sem, np.zeros((N, N), np.float32))[
            "fracao_terreno_topografia"
        ]
        is None
    )
