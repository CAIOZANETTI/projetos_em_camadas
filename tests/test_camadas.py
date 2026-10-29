import copy

import numpy as np
import pytest

from camadas import geo
from camadas.pdf_cad import desempacotar, empacotar, separar_por_cor
from camadas.visualizador import arredondar_geojson


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


def test_mosaico_ajuste_global_com_estado_em_dict():
    from camadas import mosaico
    s = 0.1                                                    # m/px
    def foto(nome, tx):
        return {"meta": {"gsd": s}, "nome": nome, "img": np.zeros((100, 100, 3), np.uint8), "escala": 1.0,
                "prior": np.array([[s, 0, tx], [0, s, 5.0], [0, 0, 1]]), "kp": None, "desc": None, "T": None}
    pa = np.random.default_rng(1).uniform(40, 100, (50, 2))
    mos = {"fotos": [foto("a.jpg", 5.0), foto("b.jpg", 8.4)],  # GPS de b 0,4 m fora (verdade: 8,0)
           "pares": [{"i": 0, "j": 1, "n": 50, "pa": pa, "pb": pa - [30, 0]}],
           "relatorio": {}, "log": lambda *a: None}
    mosaico.ajustar_global(mos, "similaridade", sigma_gps_m=1.5)
    a = mos["relatorio"]["ajuste"]
    assert a["residuo_costura_m"]["mediana"] < 1e-6 and a["fotos_so_por_gps"] == []
    Ta, Tb = mos["fotos"][0]["T"], mos["fotos"][1]["T"]
    assert Tb[0, 2] - Ta[0, 2] == pytest.approx(3.0, abs=1e-6)   # 30 px × 0,1 m
    assert a["gsd_ajustado_m"] == pytest.approx(s)


def test_arredondar_geojson_coordenadas_copia_e_properties():
    ponto = {"type": "Feature", "properties": {"nome": "PV-1", "cota": 703.791234567890123},
             "geometry": {"type": "Point", "coordinates": [-54.559761257087651, -25.464500123456789]}}
    poligono = {"type": "Feature", "properties": {"nome": "cava"},
                "geometry": {"type": "MultiPolygon", "coordinates": [[[
                    [-50.533512345678901, -25.464512345678910], [-50.533599999999999, -25.464500000000001],
                    [-50.533512345678901, -25.464512345678910]]]]}}
    dados = {"titulo": "teste", "vetores": [
        {"id": "pv", "geojson": {"type": "FeatureCollection", "features": [ponto]}},
        {"id": "cava", "geojson": {"type": "FeatureCollection", "features": [poligono]}}]}
    original = copy.deepcopy(dados)
    arredondado = arredondar_geojson(dados)
    geom_pv = arredondado["vetores"][0]["geojson"]["features"][0]["geometry"]
    geom_cava = arredondado["vetores"][1]["geojson"]["features"][0]["geometry"]
    assert geom_pv["coordinates"] == [-54.5597613, -25.4645001]
    assert geom_cava["coordinates"][0][0][0] == [-50.5335123, -25.4645123]
    assert arredondado["vetores"][0]["geojson"]["features"][0]["properties"] == ponto["properties"]
    assert arredondado["titulo"] == "teste"
    assert dados == original
    nula = {"vetores": [{"id": "x", "geojson": {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": None}]}}]}
    tupla = {"vetores": [{"id": "t", "geojson": {"type": "FeatureCollection", "features": [{"type": "Feature",
        "properties": {}, "geometry": {"type": "LineString", "coordinates": ((-54.123456789, -25.1), (-54.2, -25.987654321))}}]}}]}
    assert arredondar_geojson(tupla)["vetores"][0]["geojson"]["features"][0]["geometry"]["coordinates"] == [
        [-54.1234568, -25.1], [-54.2, -25.9876543]]
    assert arredondar_geojson(nula) == nula and arredondar_geojson({"titulo": "sem vetores"})["vetores"] == []
