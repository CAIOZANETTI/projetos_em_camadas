import numpy as np
import pytest

from camadas import geo
from camadas.pdf_cad import desempacotar, empacotar, separar_por_cor


@pytest.mark.parametrize("tipo", ["similaridade", "afim", "homografia"])
def test_ajustar_recupera_transformacao(tipo):
    rng = np.random.default_rng(1)
    a, t = np.radians(37), [546_800.0, 7_183_600.0]
    M = np.array([[0.02 * np.cos(a), -0.02 * np.sin(a), t[0]], [0.02 * np.sin(a), 0.02 * np.cos(a), t[1]], [0, 0, 1]])
    orig = rng.uniform(0, 4000, (12, 2))
    dest = geo.aplicar(M, orig)
    R = geo.ajustar(orig, dest, tipo)
    assert geo.residuos(R, orig, dest).max() < 1e-4


def test_epsg_utm_irati():
    assert geo.epsg_utm_sirgas(-50.5335, -25.4645) == 31982


def test_utm_ida_e_volta():
    e, n = geo.para_utm(-50.5335, -25.4645, 31982)
    lon, lat = geo.para_lonlat(e, n, 31982)
    assert abs(lon + 50.5335) < 1e-9 and abs(lat + 25.4645) < 1e-9


def test_separar_por_cor_com_antisserrilhado():
    h, w = 60, 80
    vermelho, azul = np.zeros((h, w)), np.zeros((h, w))
    vermelho[10:12, :] = 1.0
    vermelho[12, :] = 0.4                 # borda antisserrilhada
    azul[:, 30:32] = 1.0
    img = np.full((h, w, 3), 255.0)
    for m, c in [(vermelho, [255, 0, 0]), (azul, [0, 0, 255])]:
        img = img * (1 - m[..., None]) + np.array(c) * m[..., None]
    img = img.round().astype(np.uint8)
    mv, ma = separar_por_cor(img, [[1, 0, 0], [0, 0, 1]])
    assert mv[11, 5] == 255 and 90 < mv[12, 5] < 115   # alfa recuperado ~0,4
    assert ma[40, 30] == 255 and mv[40, 30] == 0
    assert (mv[30:, 40:] == 0).all()


def test_empacotar_ida_e_volta():
    ms = [np.full((4, 4), v, np.uint8) for v in (10, 20, 30, 40)]
    assert [m[0, 0] for m in desempacotar(empacotar(ms), 4)] == [10, 20, 30, 40]
