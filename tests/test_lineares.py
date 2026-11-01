"""L1: eixo e estaqueamento da obra linear (tolerância absoluta de 1 mm)."""

import numpy as np
import pytest

from camadas import lineares

TOL_M = 0.001
# eixo em L: 100 m para leste, curva de 90 graus, 60 m para norte (sentido do estaqueamento)
EIXO_L = [[1000.0, 2000.0], [1100.0, 2000.0], [1100.0, 2060.0]]


@pytest.fixture
def eixo_l():
    return lineares.eixo(EIXO_L)


@pytest.mark.parametrize(
    "texto, esperado_m",
    [
        ("12+10,00", 250.0),
        ("12+10.00", 250.0),
        ("12+10", 250.0),
        ("12", 240.0),
        ("E12+10,00", 250.0),
        ("EST. 12 + 10,00", 250.0),
        ("0+00,00", 0.0),
        ("3+5,5", 65.5),
    ],
)
def test_estaca_para_progressiva(texto, esperado_m):
    np.testing.assert_allclose(
        lineares.estaca_para_progressiva(texto), esperado_m, atol=TOL_M
    )


@pytest.mark.parametrize("texto", ["12+10,00", "0+00,00", "7+19,99", "100+05,50"])
def test_ida_e_volta_estaca(texto):
    assert (
        lineares.progressiva_para_estaca(lineares.estaca_para_progressiva(texto))
        == texto
    )


def test_estaca_com_arredondamento_e_passo():
    assert lineares.progressiva_para_estaca(39.999) == "2+00,00"
    assert lineares.progressiva_para_estaca(250.0, passo_m=10.0) == "25+00,00"
    assert lineares.estaca_para_progressiva("2+5", passo_m=10.0) == 25.0


def test_eixo_acumula_progressiva_e_remove_repetidos():
    eixo = lineares.eixo([[0, 0], [0, 0], [30, 40], [30, 40], [30, 90]])
    np.testing.assert_allclose(eixo["progressiva_m"], [0, 50, 100], atol=TOL_M)
    assert len(eixo["pontos_m"]) == 3
    np.testing.assert_allclose(eixo["comprimento_m"], 100.0, atol=TOL_M)


def test_ponto_em_no_meio_dos_segmentos_e_no_vertice(eixo_l):
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, 50.0), [1050.0, 2000.0], atol=TOL_M
    )
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, 100.0), [1100.0, 2000.0], atol=TOL_M
    )
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, 130.0), [1100.0, 2030.0], atol=TOL_M
    )
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, [0.0, 160.0]),
        [[1000, 2000], [1100, 2060]],
        atol=TOL_M,
    )


def test_progressiva_de_esquerda_e_direita(eixo_l):
    esq = lineares.progressiva_de(eixo_l, 1050.0, 2003.0)
    assert esq["lado"] == "esquerdo"
    np.testing.assert_allclose(
        [esq["progressiva_m"], esq["afastamento_m"]], [50.0, 3.0], atol=TOL_M
    )
    dire = lineares.progressiva_de(eixo_l, 1050.0, 1996.0)
    assert dire["lado"] == "direito"
    np.testing.assert_allclose(
        [dire["progressiva_m"], dire["afastamento_m"]], [50.0, 4.0], atol=TOL_M
    )
    # no segundo segmento (rumo norte) a esquerda é o oeste
    seg2 = lineares.progressiva_de(eixo_l, 1095.0, 2030.0)
    assert seg2["lado"] == "esquerdo"
    np.testing.assert_allclose(
        [seg2["progressiva_m"], seg2["afastamento_m"]], [130.0, 5.0], atol=TOL_M
    )


def test_progressiva_de_vetorizado(eixo_l):
    res = lineares.progressiva_de(
        eixo_l, np.array([1050.0, 1105.0]), np.array([2003.0, 2030.0])
    )
    np.testing.assert_allclose(res["progressiva_m"], [50.0, 130.0], atol=TOL_M)
    np.testing.assert_allclose(res["afastamento_m"], [3.0, 5.0], atol=TOL_M)
    assert list(res["lado"]) == ["esquerdo", "direito"]


def test_progressiva_de_fora_da_ponta_fica_na_ponta(eixo_l):
    res = lineares.progressiva_de(eixo_l, 990.0, 2000.0)
    np.testing.assert_allclose(
        [res["progressiva_m"], res["afastamento_m"]], [0.0, 10.0], atol=TOL_M
    )


def test_ida_e_volta_ponto_progressiva_ponto(eixo_l):
    progressivas_m = np.array([0.0, 12.5, 100.0, 133.3, 160.0])
    pontos = lineares.ponto_em(eixo_l, progressivas_m)
    res = lineares.progressiva_de(eixo_l, pontos[:, 0], pontos[:, 1])
    np.testing.assert_allclose(res["progressiva_m"], progressivas_m, atol=TOL_M)
    np.testing.assert_allclose(res["afastamento_m"], 0.0, atol=TOL_M)
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, res["progressiva_m"]), pontos, atol=TOL_M
    )


def test_segmento_tem_comprimento_p1_menos_p0(eixo_l):
    trecho = lineares.segmento(eixo_l, 70.0, 140.0)
    np.testing.assert_allclose(
        trecho, [[1070, 2000], [1100, 2000], [1100, 2040]], atol=TOL_M
    )
    comprimento_m = np.linalg.norm(np.diff(trecho, axis=0), axis=1).sum()
    np.testing.assert_allclose(comprimento_m, 70.0, atol=TOL_M)


def test_erros_em_portugues(eixo_l):
    with pytest.raises(ValueError, match="2 pontos distintos"):
        lineares.eixo([[0, 0]])
    with pytest.raises(ValueError, match="2 pontos distintos"):
        lineares.eixo([[5, 5], [5, 5]])
    with pytest.raises(ValueError, match="estaca não reconhecida"):
        lineares.estaca_para_progressiva("abc")
    with pytest.raises(ValueError, match="fora do eixo"):
        lineares.ponto_em(eixo_l, 160.5)
    with pytest.raises(ValueError, match="fora do eixo"):
        lineares.ponto_em(eixo_l, -1.0)
    with pytest.raises(ValueError, match="maior que a inicial"):
        lineares.segmento(eixo_l, 50.0, 50.0)


def test_metadados():
    meta = lineares.metadados()
    assert meta["modulo"] == "lineares"
    assert all(p["estado"] == "premissa" for p in meta["premissas"])
