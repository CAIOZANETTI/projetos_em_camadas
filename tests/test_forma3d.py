"""Testes de camadas.forma3d com PDFs sintéticos (PyMuPDF), sem dados reais."""

import itertools

import numpy as np
import pymupdf
import pytest
from shapely.geometry import Polygon, box

from camadas import forma3d

REGIAO = (0, 0, 600, 600)
VERMELHO = (1.0, 0.0, 0.0)


def _pdf(tmp_path, nome, desenhos, layers=("12",)):
    """desenhos: lista de (layer, tipo, pontos, cor)."""
    doc = pymupdf.open()
    pagina = doc.new_page(width=600, height=600)
    xrefs = {n: doc.add_ocg(n) for n in layers}
    for layer, tipo, pontos, cor in desenhos:
        forma = pagina.new_shape()
        if tipo == "preenchido":
            forma.draw_polyline([pymupdf.Point(*p) for p in pontos])
            forma.finish(fill=cor, color=None, closePath=True, oc=xrefs[layer])
        else:
            forma.draw_line(pymupdf.Point(*pontos[0]), pymupdf.Point(*pontos[1]))
            forma.finish(color=cor, closePath=False, oc=xrefs[layer])
        forma.commit()
    caminho = tmp_path / nome
    doc.save(caminho)
    return caminho


def _triangulos(x0, y0, x1, y1):
    return [
        ("12", "preenchido", [(x0, y0), (x1, y0), (x1, y1)], VERMELHO),
        ("12", "preenchido", [(x0, y0), (x1, y1), (x0, y1)], VERMELHO),
    ]


def test_unir_pilar_em_dois_triangulos(tmp_path):
    pdf = _pdf(tmp_path, "a.pdf", _triangulos(100, 100, 130, 120))
    lido = forma3d.preenchidos(pdf, [("12", VERMELHO)], REGIAO)[("12", VERMELHO)]
    assert len(lido) == 2
    partes = forma3d.unir(lido)
    assert len(partes) == 1
    assert partes[0].area == pytest.approx(30 * 20, rel=0.005)
    assert len(partes[0].exterior.coords) == 5


def test_preenchimento_duplicado_nao_dobra(tmp_path):
    pdf = _pdf(tmp_path, "b.pdf", _triangulos(100, 100, 130, 120) * 2)
    lido = forma3d.preenchidos(pdf, [("12", VERMELHO)], REGIAO)[("12", VERMELHO)]
    assert len(lido) == 2
    assert sum(p.area for p in forma3d.unir(lido)) == pytest.approx(600, rel=0.005)


def test_regiao_e_chave_filtram(tmp_path):
    pdf = _pdf(
        tmp_path,
        "c.pdf",
        _triangulos(100, 100, 130, 120) + _triangulos(500, 500, 590, 590),
    )
    lido = forma3d.preenchidos(
        pdf, [("12", VERMELHO), ("12", (0.0, 0.0, 1.0))], (0, 0, 300, 300)
    )
    assert len(lido[("12", VERMELHO)]) == 2
    assert lido[("12", (0.0, 0.0, 1.0))] == []


def test_caminho_fora_de_ordem_cai_no_rect(tmp_path):
    gravata = [(100, 100), (120, 120), (120, 100), (100, 120)]
    pdf = _pdf(tmp_path, "d.pdf", [("12", "preenchido", gravata, VERMELHO)])
    lido = forma3d.preenchidos(pdf, [("12", VERMELHO)], REGIAO)[("12", VERMELHO)]
    assert len(lido) == 1
    assert lido[0].area == pytest.approx(400, rel=0.005)


def test_sem_furos_laje_com_duas_aberturas():
    laje = (
        box(0, 0, 100, 60)
        .difference(box(20, 20, 40, 40))
        .difference(box(60, 10, 80, 50))
    )
    assert len(laje.interiors) == 2
    pecas = forma3d.sem_furos(laje)
    assert all(len(p.interiors) == 0 for p in pecas)
    assert sum(p.area for p in pecas) == pytest.approx(laje.area, rel=1e-9)
    assert len(pecas) > 1


def _par(distancia_pt, comprimento_pt=100.0):
    return [
        ("12", "traco", [(100, 100), (100 + comprimento_pt, 100)], (0, 0, 0)),
        (
            "12",
            "traco",
            [(100, 100 + distancia_pt), (100 + comprimento_pt, 100 + distancia_pt)],
            (0, 0, 0),
        ),
    ]


def test_viga_por_par_de_tracos(tmp_path):
    pdf = _pdf(tmp_path, "e.pdf", _par(11.3))
    segs = forma3d.tracos(pdf, ["12"], REGIAO)
    assert len(segs) == 2
    vigas = forma3d.vigas_por_pares(segs)
    assert len(vigas) == 1
    xmin, ymin, xmax, ymax = vigas[0].bounds
    assert ymax - ymin == pytest.approx(11.3, abs=1e-3)
    assert xmax - xmin == pytest.approx(100, abs=1e-3)


def test_tracos_afastados_nao_viram_viga(tmp_path):
    pdf = _pdf(tmp_path, "f.pdf", _par(30))
    assert forma3d.vigas_por_pares(forma3d.tracos(pdf, ["12"], REGIAO)) == []


def test_alinhar_por_pontos_com_espurios():
    rng = np.random.default_rng(1)
    a = rng.uniform(0, 500, (30, 2))
    verdadeira = np.array([12.37, -8.91])
    b = a - verdadeira + rng.normal(0, 0.02, a.shape)
    b[:9] = rng.uniform(0, 500, (9, 2))  # 30 % de pontos espúrios
    r = forma3d.alinhar_por_pontos(a, b)
    assert np.allclose(r["translacao_pt"], verdadeira, atol=0.1)
    assert r["casados"] >= 21 and r["total"] == 30
    assert r["residuo_mediano_pt"] < 0.1


def _linhas(deslocamento):
    dx, dy = deslocamento
    ys, xs = [100, 180, 260, 410, 455], [90, 200, 220, 350, 505]
    h = [
        ("12", "traco", [(50 + dx, y + dy), (550 + dx, y + dy)], (0, 0, 0)) for y in ys
    ]
    v = [
        ("12", "traco", [(x + dx, 50 + dy), (x + dx, 550 + dy)], (0, 0, 0)) for x in xs
    ]
    return h + v


def test_alinhar_por_linhas(tmp_path):
    pdf_a = _pdf(tmp_path, "g_a.pdf", _linhas((0, 0)))
    pdf_b = _pdf(tmp_path, "g_b.pdf", _linhas((-17.0, 9.5)))  # b = a deslocado
    r = forma3d.alinhar_por_linhas(pdf_a, pdf_b, (0, 0, 600, 600))
    assert np.allclose(r["translacao_pt"], [17.0, -9.5], atol=0.5)
    assert r["pico_x"] > 1.5 * r["segundo_pico_x"]
    assert r["pico_y"] > 1.5 * r["segundo_pico_y"]


def _retangulo(centro, largura, altura, graus):
    t = np.radians(graus)
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    cantos = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * [largura / 2, altura / 2]
    return Polygon(cantos @ R.T + centro)


def test_alinhar_por_retangulo_rotacao_e_translacao():
    ret_b = _retangulo((100, 200), 30, 12, 0)
    ret_a = _retangulo((340, 260), 30, 12, 3)
    M = forma3d.alinhar_por_retangulo(ret_a, ret_b)
    assert M.shape == (2, 3)
    assert np.degrees(np.arctan2(M[1, 0], M[0, 0])) == pytest.approx(3, abs=1e-6)
    assert M @ [100, 200, 1] == pytest.approx([340, 260], abs=1e-6)


def test_alinhar_por_retangulo_escolhe_entre_theta_e_theta_mais_180():
    ret_b = _retangulo((100, 200), 30, 12, 0)
    ret_a = _retangulo((340, 260), 30, 12, 3)
    perto_de_3 = forma3d.alinhar_por_retangulo(ret_a, ret_b, angulo_aprox_graus=0)
    perto_de_183 = forma3d.alinhar_por_retangulo(ret_a, ret_b, angulo_aprox_graus=180)
    assert np.degrees(np.arctan2(perto_de_3[1, 0], perto_de_3[0, 0])) == pytest.approx(
        3, abs=1e-6
    )
    assert abs(
        np.degrees(np.arctan2(perto_de_183[1, 0], perto_de_183[0, 0]))
    ) == pytest.approx(177, abs=1e-6)
    assert perto_de_183 @ [100, 200, 1] == pytest.approx([340, 260], abs=1e-6)


def test_prismas_inclinados():
    base, topo = (10.0, 20.0), (13.0, 24.0)
    prismas = forma3d.prismas_inclinados(base, 1.0, topo, 3.5, 0.4, n=14)
    assert len(prismas) == 14
    assert prismas[0]["z0"] == pytest.approx(1.0) and prismas[-1][
        "z1"
    ] == pytest.approx(3.5)
    for anterior, seguinte in itertools.pairwise(prismas):
        assert seguinte["z0"] == pytest.approx(anterior["z1"])
    primeiro = np.array(prismas[0]["contorno"])
    ultimo = np.array(prismas[-1]["contorno"])
    assert np.allclose((primeiro[0] + primeiro[3]) / 2, base)
    assert np.allclose((ultimo[1] + ultimo[2]) / 2, topo)
    assert np.linalg.norm(primeiro[0] - primeiro[3]) == pytest.approx(0.4)


def test_metadados():
    m = forma3d.metadados()
    assert m["modulo"] == "forma3d"
    assert all(hasattr(forma3d, f) for f in m["funcoes"])
    assert all("fonte" in p and "aplicacao" in p for p in m["premissas"])
