import base64
import gzip
import json

import cv2
import numpy as np
import pytest

from camadas import geo, georef_prancha, sfm

pymupdf = pytest.importorskip("pymupdf")
from camadas import pdf_cad  # noqa: E402


@pytest.fixture
def pdf_com_layers(tmp_path):
    """Folha 400×300 pt com dois layers (OCG), um retângulo preenchido e texto; /Rotate 90."""
    doc = pymupdf.open()
    pg = doc.new_page(width=400, height=300)
    a, b = doc.add_ocg("EXISTENTES"), doc.add_ocg("_PROJETADOS")
    pg.draw_line((50, 50), (350, 50), color=(1, 0.5, 0), oc=a)
    pg.draw_rect(pymupdf.Rect(100, 100, 200, 160), color=(0, 0.43, 0.87), fill=(0, 0.43, 0.87), oc=b)
    pg.insert_text((60, 250), "TUBO PEAD DN 630", fontsize=10)
    pg.set_rotation(90)
    caminho = tmp_path / "folha.pdf"
    doc.save(caminho)
    return caminho


def test_extrair_layers_no_espaco_exibido(pdf_com_layers):
    assert set(pdf_cad.layers_pdf(pdf_com_layers)) == {"EXISTENTES", "_PROJETADOS"}
    tr = pdf_cad.extrair(pdf_com_layers)
    por_layer = {t["layer"]: t for t in tr}
    linha = por_layer["EXISTENTES"]["partes"][0]
    # /Rotate 90: a folha exibida tem 300 de largura e 400 de altura; a linha horizontal vira vertical
    assert np.allclose(linha[:, 0], linha[0, 0], atol=1e-3)
    assert np.ptp(linha[:, 1]) == pytest.approx(300, abs=1e-3)
    cls = pdf_cad.classificar(tr, pdf_cad.regras("etapas_sanepar"))
    assert cls[tr.index(por_layer["_PROJETADOS"])] == "1ª etapa"


def test_pacote_vetorial_ida_e_volta(pdf_com_layers):
    pac = pdf_cad.pacote_vetorial(pdf_com_layers, simplificar_pt=0)
    assert (pac["largura"], pac["altura"]) == (300, 400)
    d = np.frombuffer(gzip.decompress(base64.b64decode(pac["coords"])), "<i4").reshape(-1, 2)
    partes = np.frombuffer(gzip.decompress(base64.b64decode(pac["partes"])), "<u4").reshape(-1, 4)
    pts = np.cumsum(d.astype(np.int64), axis=0) / 10
    assert partes[:, 0].sum() == len(pts)
    tr = pdf_cad.extrair(pdf_com_layers)
    assert np.allclose(pts[: len(tr[0]["partes"][0])], np.round(tr[0]["partes"][0] * 10) / 10)
    assert [t["t"] for t in pac["textos"]] == ["TUBO PEAD DN 630"]
    assert {l["nome"] for l in pac["layers"]} >= {"EXISTENTES", "_PROJETADOS"}


def test_matriz_inicial_tem_reflexao():
    # norte para a esquerda da folha, leste para cima, 0,1 m/pt
    pt = [[0, 0], [100, 0], [0, 100]]
    utm = [[1000, 2000], [1000, 1990], [990, 2000]]
    M = georef_prancha.matriz_inicial(pt, utm)
    assert np.allclose(geo.aplicar(M, pt), utm, atol=1e-6)
    assert np.linalg.det(M[:2, :2]) < 0


def test_refinar_recupera_deslocamento():
    rng = np.random.default_rng(3)
    bordas = np.zeros((400, 400), np.uint8)
    pts = []
    for _ in range(12):                                  # retângulos = "prédios"
        x, y = rng.integers(40, 300, 2)
        w, h = rng.integers(20, 70, 2)
        cv2.rectangle(bordas, (int(x), int(y)), (int(x + w), int(y + h)), 255, 1)
        t = np.linspace(0, 1, 40)[:, None]
        for a, b in [((x, y), (x + w, y)), ((x + w, y), (x + w, y + h)), ((x, y + h), (x + w, y + h)), ((x, y), (x, y + h))]:
            pts.append(np.array(a) + t * (np.array(b) - np.array(a)))
    pts = np.vstack(pts).astype(float)
    T0 = np.array([[1, 0, 3.0], [0, 1, -2.0], [0, 0, 1]])       # chute errado em 3,6 px
    T, diag = georef_prancha.refinar(pts, bordas, T0, res=0.1, corte_m=1.0)
    assert np.abs(T[:2, 2]).max() < 0.6
    assert diag["frac_05m"] > 0.95


def test_umeyama_recupera_similaridade():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(30, 3))
    a = np.radians(33)
    R = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    Y = 2.5 * (R @ X.T).T + [745_000, 7_182_000, 90]
    s, Rr, t = sfm.umeyama(X, Y)
    assert s == pytest.approx(2.5) and np.allclose(Rr, R) and np.allclose(t, [745_000, 7_182_000, 90])


def test_mds_fecha_buraco_de_telhado():
    # telhado 10×10 m a 8 m com um buraco de 1 m no meio, terreno a 0
    g = np.mgrid[0:30:0.1, 0:30:0.1].reshape(2, -1).T
    z = np.where((np.abs(g[:, 0] - 15) < 5) & (np.abs(g[:, 1] - 15) < 5), 8.0, 0.0)
    buraco = (np.abs(g[:, 0] - 15) < 0.5) & (np.abs(g[:, 1] - 15) < 0.5)
    xyz = np.c_[g, z][~buraco]
    m = sfm.mds(xyz, res=0.25)
    c = int(round((m["n1"] - 15) / 0.25)), int(round((15 - m["e0"]) / 0.25))
    assert m["z"][c] == pytest.approx(8.0, abs=0.01)


def test_sondagens_aceita_formato_meta_furos(tmp_path):
    from camadas import obra
    arq = tmp_path / "s.json"
    arq.write_text(json.dumps({"meta": {}, "furos": [{"id": "SP-01", "E": 745814.56, "N": 7182953.79,
                                                     "epsg_inferido": 31981}]}))
    f = obra.sondagens({"sondagens": str(arq)}, 31981)
    assert f[0]["id"] == "SP-01" and -54.6 < f[0]["lon"] < -54.5 and -25.5 < f[0]["lat"] < -25.4
