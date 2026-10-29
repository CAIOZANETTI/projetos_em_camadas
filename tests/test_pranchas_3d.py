import base64
import gzip
import json
from itertools import pairwise

import cv2
import numpy as np
import pytest

from camadas import geo, georef_prancha, sfm

pymupdf = pytest.importorskip("pymupdf")
from camadas import pdf_cad


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
    pac = pdf_cad.pacote_vetorial(pdf_com_layers, tolerancia_pt=0)
    assert (pac["largura"], pac["altura"]) == (300, 400)
    d = np.frombuffer(gzip.decompress(base64.b64decode(pac["coords"])), "<i4")
    assert len(d) % 2 == 0                                    # por coluna: todos os dx, depois todos os dy
    pts, partes = pdf_cad.decodificar_pacote(pac)
    assert np.allclose(pts, np.cumsum(d.reshape(2, -1).T.astype(np.int64), axis=0) / 10)
    assert partes[:, 0].sum() == len(pts)
    tr = pdf_cad.extrair(pdf_com_layers)
    assert np.allclose(pts[: len(tr[0]["partes"][0])], np.round(tr[0]["partes"][0] * 10) / 10)
    assert [t["t"] for t in pac["textos"]] == ["TUBO PEAD DN 630"]
    assert {l["nome"] for l in pac["layers"]} >= {"EXISTENTES", "_PROJETADOS"}


def _simplifica(p, tol):
    return pdf_cad.simplificar_partes([p], tol)[0]


def _desvio_max(original: np.ndarray, simples: np.ndarray) -> float:
    """Maior distância de um ponto do original à poligonal simplificada (pt)."""
    def distancia(p, a, b):
        u = b - a
        t = np.clip((p - a) @ u / max(u @ u, 1e-12), 0, 1)
        return np.hypot(*(p - a - t * u))
    return max(min(distancia(p, a, b) for a, b in pairwise(simples)) for p in original)


def test_simplificar_partes_arco_vira_poucos_pontos():
    t = np.linspace(0, np.pi / 2, 400)
    arco = np.c_[500 * np.cos(t), 500 * np.sin(t)]                 # arco de 785 pt com 400 pontos
    s = _simplifica(arco, 0.25)
    assert 2 < len(s) < 60
    assert np.allclose(s[0], arco[0]) and np.allclose(s[-1], arco[-1])
    assert _desvio_max(arco, s) <= 0.25 + 1e-3                      # garantia do Douglas–Peucker
    assert _simplifica(arco, 0) is arco               # 0 = sem simplificar


def test_simplificar_partes_fechada_continua_fechada():
    t = np.linspace(0, 2 * np.pi, 361)
    circulo = np.c_[100 + 50 * np.cos(t), 100 + 50 * np.sin(t)]
    circulo[-1] = circulo[0]
    s = _simplifica(circulo, 0.25)
    assert 3 < len(s) < 60 and np.array_equal(s[0], s[-1])
    retangulo = np.array([[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]], float)
    assert np.array_equal(_simplifica(retangulo, 0.25), retangulo)   # mantém o último lado
    minusculo = np.array([[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1], [0, 0]], float)  # menor que a tolerância
    assert len(_simplifica(minusculo, 0.25)) >= 3


def test_simplificar_partes_segmento_igual():
    seg = np.array([[1.0, 2.0], [30.5, 7.25]])
    assert np.array_equal(_simplifica(seg, 0.25), seg)
    quase_reta = np.array([[0, 0], [50, 0.01], [100, 0]], float)
    assert len(_simplifica(quase_reta, 0.25)) == 2
    assert len(_simplifica(np.ones((3, 2)), 0.25)) == 2              # pontos todos iguais: nunca 1 ponto


def test_simplificar_partes_em_lote_nao_corta_retraco_nem_apaga_ponto():
    t = np.linspace(0, 2 * np.pi, 25)
    ponto = np.c_[100 + 0.06 * np.cos(t), 200 + 0.06 * np.sin(t)]      # símbolo-ponto de 0,12 pt (25 pts)
    ponto[-1] = ponto[0]
    retraco = np.array([[0, 0], [5, 0], [3, 0]], float)                # avança até 5 e volta a 3 pela mesma reta
    segmento = np.array([[1.0, 2.0], [9.0, 2.0]])
    s = pdf_cad.simplificar_partes([retraco, ponto, segmento], 0.25)
    assert np.array_equal(s[0], retraco)                               # a distância é ao segmento, não à reta
    assert len(s[1]) == 4 and np.array_equal(s[1][0], s[1][-1])        # triângulo fechado, não 1 ponto
    assert np.array_equal(s[2], segmento)


def test_pacote_vetorial_tolerancia_reduz_pontos_e_mantem_fechamento(tmp_path):
    doc = pymupdf.open()
    pg = doc.new_page(width=400, height=300)
    t = np.linspace(0, 2 * np.pi, 361)
    anel = [pymupdf.Point(200 + 100 * np.cos(a), 150 + 100 * np.sin(a)) for a in t]
    pg.draw_polyline(anel, color=(0, 0, 0), fill=(0.8, 0.8, 0.8), closePath=True)
    pg.draw_line((10, 10), (390, 20), color=(0, 0, 0))
    doc.save(tmp_path / "circulo.pdf")
    inteiro, simples = (pdf_cad.pacote_vetorial(tmp_path / "circulo.pdf", tolerancia_pt=t) for t in (0, 0.25))
    assert simples["n_pontos"] < inteiro["n_pontos"] / 2
    assert simples["n_partes"] == inteiro["n_partes"]
    pts, partes = pdf_cad.decodificar_pacote(simples)
    assert partes[:, 3].tolist() == pdf_cad.decodificar_pacote(inteiro)[1][:, 3].tolist()   # flags iguais
    anel = pts[: partes[0, 0]]
    assert partes[0, 3] & 2 and np.array_equal(anel[0], anel[-1])
    assert partes[1, 0] == 2


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
    c = int(round((m["n1"] - 15) / 0.25)), int(round((15 - m["e0"]) / 0.25))   # noqa: RUF046 — numpy 1.x
    assert m["z"][c] == pytest.approx(8.0, abs=0.01)


def test_sondagens_aceita_formato_meta_furos(tmp_path):
    from camadas import obra
    arq = tmp_path / "s.json"
    arq.write_text(json.dumps({"meta": {}, "furos": [{"id": "SP-01", "E": 745814.56, "N": 7182953.79,
                                                     "epsg_inferido": 31981}]}))
    f = obra.sondagens({"sondagens": str(arq)}, 31981)
    assert f[0]["id"] == "SP-01" and -54.6 < f[0]["lon"] < -54.5 and -25.5 < f[0]["lat"] < -25.4


def test_quantitativos_por_layer_em_metros(pdf_com_layers):
    pac = pdf_cad.pacote_vetorial(pdf_com_layers, tolerancia_pt=0)
    pac["M"] = [0.1, 0, 1000.0, 0, -0.1, 2000.0]          # 0,1 m por pt
    pac["clip_mapa"] = None
    pac["layers"] = [{**l, "grupo": "Civil", "subgrupo": "Estrutura"} for l in pac["layers"]]
    q = {l["layer"]: l for l in pdf_cad.quantitativos(pac)}
    assert q["EXISTENTES"]["comprimento_m"] == pytest.approx(30.0, abs=0.01)     # 300 pt
    assert q["_PROJETADOS"]["area_m2"] == pytest.approx(10.0 * 6.0, abs=0.01)    # 100 × 60 pt


def test_quantitativos_eixo_de_faixa_triangulada(tmp_path):
    """Polilinha com largura chega como triângulos preenchidos: o eixo sai da união, não da soma dos perímetros."""
    doc = pymupdf.open()
    pg = doc.new_page(width=400, height=300)
    tubo = doc.add_ocg("ADUTORA_TUBO")
    for x in range(20, 380, 40):                      # faixa de 360 × 3 pt em 18 triângulos
        pg.draw_polyline([(x, 100), (x + 40, 100), (x + 40, 103), (x, 100)], color=None, fill=(0.6, 0, 0.8), oc=tubo, closePath=True)
        pg.draw_polyline([(x, 100), (x + 40, 103), (x, 103), (x, 100)], color=None, fill=(0.6, 0, 0.8), oc=tubo, closePath=True)
    doc.save(tmp_path / "faixa.pdf")
    pac = pdf_cad.pacote_vetorial(tmp_path / "faixa.pdf", tolerancia_pt=0)
    pac["M"], pac["clip_mapa"] = [0.1, 0, 0.0, 0, -0.1, 0.0], None
    q = pdf_cad.quantitativos(pac)[0]
    assert q["eixo_faixa_m"] == pytest.approx(36.0 + 0.3, abs=0.2)      # meio perímetro: comprimento + largura
    assert q["area_m2"] == pytest.approx(36.0 * 0.3, rel=0.02)
