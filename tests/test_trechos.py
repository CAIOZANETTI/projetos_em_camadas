"""L3b: `lineares.trechos` segmenta o eixo por superfície, furo e PV (tolerância absoluta em metros)."""

import itertools

import pytest

from camadas import lineares

TOL_M = 0.001


def _eixo_100m():
    return lineares.eixo([(0.0, 0.0), (60.0, 0.0), (60.0, 40.0)])  # 100 m com uma curva


def test_sem_cortes_e_um_so():
    lista = lineares.trechos(_eixo_100m())
    assert len(lista) == 1
    assert lista[0]["p0_m"] == 0.0 and lista[0]["p1_m"] == pytest.approx(100.0)
    assert lista[0]["superficie"] is None and lista[0]["furo"] is None
    assert lista[0]["estaca_inicial"] == "0+00,00"
    assert lista[0]["estaca_final"] == "5+00,00"


def test_por_superficie():
    cortes = {"superficie": [(0.0, 30.0, "pista"), (30.0, 100.0, "calcada")]}
    lista = lineares.trechos(_eixo_100m(), cortes)
    assert [(t["p0_m"], t["p1_m"], t["superficie"]) for t in lista] == [
        (0.0, 30.0, "pista"),
        (30.0, 100.0, "calcada"),
    ]
    sem_cobertura = lineares.trechos(
        _eixo_100m(), {"superficie": [(20.0, 50.0, "pista")]}
    )
    assert [t["superficie"] for t in sem_cobertura] == [None, "pista", None]


def test_por_furos_corta_no_ponto_medio():
    cortes = {"furos": [(10.0, "SP-01"), (50.0, "SP-02"), (90.0, "SP-03")]}
    lista = lineares.trechos(_eixo_100m(), cortes)
    assert [(t["p0_m"], t["p1_m"], t["furo"]) for t in lista] == [
        (0.0, 30.0, "SP-01"),
        (30.0, 70.0, "SP-02"),
        (70.0, 100.0, "SP-03"),
    ]
    assert lista[1]["sond_ini"] == "SP-02"


def test_por_pvs():
    lista = lineares.trechos(_eixo_100m(), {"pvs": [25.0, 75.0]})
    assert [(t["p0_m"], t["p1_m"]) for t in lista] == [
        (0.0, 25.0),
        (25.0, 75.0),
        (75.0, 100.0),
    ]
    assert lista[1]["estaca_inicial"] == "1+05,00"
    assert lista[1]["estaca_final"] == "3+15,00"


def test_combinados_somam_o_comprimento_do_eixo():
    cortes = {
        "superficie": [(0.0, 40.0, "pista"), (40.0, 100.0, "calcada")],
        "furos": [(10.0, "SP-01"), (80.0, "SP-02")],
        "pvs": [60.0, 100.0, 0.0, 150.0],  # pontas e fora do eixo são ignoradas
    }
    lista = lineares.trechos(_eixo_100m(), cortes)
    assert [t["p0_m"] for t in lista] == [0.0, 40.0, 45.0, 60.0]
    assert [t["p1_m"] for t in lista] == [40.0, 45.0, 60.0, 100.0]
    assert [t["furo"] for t in lista] == ["SP-01", "SP-01", "SP-02", "SP-02"]
    assert [t["superficie"] for t in lista] == [
        "pista",
        "calcada",
        "calcada",
        "calcada",
    ]
    assert sum(t["comp_m"] for t in lista) == pytest.approx(100.0, abs=TOL_M)
    assert all(a["p1_m"] == b["p0_m"] for a, b in itertools.pairwise(lista))


def test_sem_vao_menor_que_o_minimo():
    minimo_m = lineares.TRECHOS["comprimento_minimo_m"]
    cortes = {"pvs": [30.0, 30.0 + minimo_m / 2, 100.0 - minimo_m / 2]}
    lista = lineares.trechos(_eixo_100m(), cortes)
    assert [(t["p0_m"], t["p1_m"]) for t in lista] == [(0.0, 30.0), (30.0, 100.0)]
    assert min(t["comp_m"] for t in lista) >= minimo_m


def test_alimentam_o_dimensionador_de_vala():
    cortes = {"furos": [(10.0, "SP-01"), (80.0, "SP-02")], "pvs": [50.0]}
    for t in lineares.trechos(_eixo_100m(), cortes):
        trecho = {**t, "dn_mm": 300, "material": "FD", "prof_m": 2.0, "metodo": "VCA"}
        vala = lineares.dimensionar_vala(trecho)
        assert vala["comp_m"] == t["comp_m"]
        assert vala["largura_m"] > 0.3 and vala["escavacao_m3"] > 0
