import math
import shutil

import numpy as np
import pytest
from shapely.geometry import LineString, box

from camadas import escavacao


def _grade(terreno=10.0, n=400, res=0.25):
    return {"e0": 0.0, "n1": n * res, "res": res, "forma": (n, n), "epsg": 31981,
            "terreno": np.full((n, n), terreno, np.float32), "valido": np.ones((n, n), bool),
            "edificacao": np.zeros((n, n), bool)}


def _cava_padrao():
    base = [{"geom": box(45, 45, 55, 55), "etapa": "1ª etapa"}]
    marca = [{"utm": [50.0, 50.0], "cota": 8.0, "topo": False}]
    return base, marca


def test_volume_tronco_de_piramide():
    """Base 10×10, 2 m de profundidade, folga 0,5 m, talude 1,5:1: volume = h·A' + P'·h·r/2 + π·r²·h/3."""
    h, t, f = 2.0, escavacao.VALOR["talude_h_v"], escavacao.VALOR["folga_m"]
    a, r = 10 + 2 * f, h * t
    esperado = h * a * a + 4 * a * h * r / 2 + math.pi * r * r * h / 3
    base, marca = _cava_padrao()
    res = escavacao.calcular(base, marca, [], _grade())
    assert len(res["cavas"]) == 1
    c = res["cavas"][0]
    assert c["escavacao_m3"] == pytest.approx(esperado, rel=0.03)
    assert c["reaterro_m3"] == pytest.approx(esperado - h * 100, rel=0.05)    # estrutura ocupa a base até o terreno
    assert c["prof_media_m"] == pytest.approx(2.0, abs=0.01)
    assert c["etapa"] == "1ª etapa" and c["fundo_m"] == [8.0, 8.0]


def test_crista_desenhada_e_edificacao_limitam_a_cava():
    base, marca = _cava_padrao()
    livre = escavacao.calcular(base, marca, [], _grade())["cavas"][0]
    crista = [LineString([(43, 43), (57, 43), (57, 57), (43, 57), (43, 43)])]   # crista a 2 m da base
    cortada = escavacao.calcular(base, marca, crista, _grade())["cavas"][0]
    assert cortada["escavacao_m3"] < livre["escavacao_m3"]
    assert cortada["contorno"].within(box(42.5, 42.5, 57.5, 57.5))
    g = _grade()
    g["edificacao"][:, 232:] = True                     # prédio a partir de E = 58 m
    perto = escavacao.calcular(base, marca, [], g)["cavas"][0]
    assert perto["contorno"].bounds[2] <= 58.0 and perto["escavacao_m3"] < livre["escavacao_m3"]


def test_marcas_impossiveis_e_topo_ficam_de_fora():
    g = _grade()
    ms = [{"utm": [50, 50], "cota": 8.0}, {"utm": [50, 50], "cota": 38.75},           # dígito perdido no OCR
          {"utm": [50, 50], "cota": 9.5, "topo": True}, {"utm": [500, 50], "cota": 8.0}, {"utm": [50, 50], "cota": None}]
    ok, fora = escavacao.plausiveis(ms, g)
    assert [m["cota"] for m in ok] == [8.0] and fora == 1
    base, _ = _cava_padrao()
    sem = escavacao.calcular(base, [ms[1]], [], g)
    assert sem["cavas"] == [] and sem["bases_sem_marca"] == 1


def test_chao_pmf_tira_predio_maior_que_a_abertura():
    z = np.full((300, 300), 100.0, np.float32)
    z[100:220, 80:240] += 6.0                           # prédio de 30 × 40 m (res 0,25)
    chao = escavacao.chao_pmf(z, 0.25)
    assert not chao[160, 160] and chao[20, 20]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract não instalado")
def test_ler_cota_ao_lado_do_simbolo():
    pymupdf = pytest.importorskip("pymupdf")
    pytest.importorskip("pytesseract")
    doc = pymupdf.open()
    pg = doc.new_page(width=300, height=200)
    pg.draw_circle((100, 100), 4.5, color=(1, 0, 0), fill=(1, 0, 0))
    pg.insert_text((108, 97), "237,45", fontsize=9)
    pg.insert_text((100, 160), "239,20 TOPO", fontsize=9)
    assert escavacao.ler_cota(pg, np.array([100.0, 100.0]))["cota"] == pytest.approx(237.45)
    assert escavacao.ler_cota(pg, np.array([30.0, 30.0])) is None
