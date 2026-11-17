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


# --- montagem declarativa (estruturas_3d) ---

AZUL = (0.0, 0.0, 1.0)


def _pdf_formas(tmp_path, nome, formas):
    """formas: (layer, tipo, dados, cor); tipos: preenchido (pontos), poligono/poligono_re (contorno), circulo ((cx, cy), raio)."""
    doc = pymupdf.open()
    pagina = doc.new_page(width=600, height=600)
    xrefs = {l: doc.add_ocg(l) for l in {f[0] for f in formas}}
    for layer, tipo, dados, cor in formas:
        forma = pagina.new_shape()
        if tipo == "circulo":
            forma.draw_circle(pymupdf.Point(*dados[0]), dados[1])
            forma.finish(color=(0, 0, 0), closePath=True, oc=xrefs[layer])
        elif (
            tipo == "poligono"
        ):  # contorno em traços `l` (o polígono se fecha só pelo polygonize)
            for a, b in itertools.pairwise([*dados, dados[0]]):
                forma.draw_line(pymupdf.Point(*a), pymupdf.Point(*b))
            forma.finish(color=cor, closePath=False, oc=xrefs[layer])
        else:
            forma.draw_polyline([pymupdf.Point(*p) for p in dados])
            if tipo == "preenchido":
                forma.finish(fill=cor, color=None, closePath=True, oc=xrefs[layer])
            else:  # "poligono_re": o PyMuPDF grava o contorno retangular como `re`
                forma.finish(color=cor, closePath=True, oc=xrefs[layer])
        forma.commit()
    caminho = tmp_path / nome
    doc.save(caminho)
    return caminho


def _retangulo_pontos(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def test_matriz_da_folha_compoe_prancha_translacao_e_matriz():
    prancha = np.array([[0.02, 0, 500000.0], [0, -0.02, 7000000.0], [0, 0, 1]])
    folhas = {
        "a": {"transformacao": {"prancha": "p", "translacao_pt": [10, 5]}},
        "b": {"transformacao": {"folha": "a", "translacao_pt": [40, 30]}},
        "c": {"transformacao": {"folha": "b", "matriz_pt": [[0, -1, 7], [1, 0, 3]]}},
    }
    m = forma3d.matriz_da_folha("b", folhas, {"p": prancha})
    assert m[:2] @ [0, 0, 1] == pytest.approx(
        [500000 + 0.02 * 50, 7000000 - 0.02 * 35], abs=1e-6
    )
    # c: gira 90° e translada (7, 3) até a folha b; depois b -> a -> UTM
    mc = forma3d.matriz_da_folha("c", folhas, {"p": prancha})
    ponto_b = np.array([0 * 1 - 1 * 2 + 7, 1 * 1 + 0 * 2 + 3])  # (1, 2) da folha c
    esperado = prancha[:2] @ [ponto_b[0] + 50, ponto_b[1] + 35, 1]
    assert mc[:2] @ [1, 2, 1] == pytest.approx(esperado, abs=1e-6)


def test_matriz_da_folha_ciclo_e_erros_claros():
    folhas = {
        "a": {"transformacao": {"folha": "b"}},
        "b": {"transformacao": {"folha": "a"}},
        "c": {"transformacao": {"prancha": "inexistente"}},
    }
    with pytest.raises(ValueError, match="ciclo"):
        forma3d.matriz_da_folha("a", folhas, {})
    with pytest.raises(ValueError, match="sem M_absoluta"):
        forma3d.matriz_da_folha("c", folhas, {})
    with pytest.raises(ValueError, match="não declarada"):
        forma3d.matriz_da_folha("z", folhas, {})


def test_atribuir_rotulos_um_a_um_mesmo_com_ponto_mais_perto_de_outro_bloco():
    centros = [(0, 0), (10, 0), (20, 0)]
    rotulos = {
        "P3": [19, 1],
        "P1": [-1, 1],
        "P2": [4.9, 0],
    }  # P2 está mais perto do bloco 0 que do 1
    atribuicao = forma3d.atribuir_rotulos(centros, rotulos)
    assert atribuicao == {0: "P1", 1: "P2", 2: "P3"}
    assert forma3d.atribuir_rotulos(centros[:2], {"A": [0, 0]}) == {
        0: "A"
    }  # sobra bloco sem rótulo


def test_circulos_e_blocos_fechados(tmp_path):
    formas = [
        ("2", "circulo", ((130, 120), 11.5), (0, 0, 0)),
        ("2", "circulo", ((130, 120), 11.5), (0, 0, 0)),  # duplicata
        ("2", "circulo", ((300, 300), 40), (0, 0, 0)),  # grande demais: não é estaca
        (
            "3",
            "poligono",
            [(100, 100), (160, 100), (160, 140), (130, 150), (100, 140)],
            (0, 0, 0),
        ),
        ("3", "poligono_re", _retangulo_pontos(300, 100, 360, 140), (0, 0, 0)),
        (
            "3",
            "poligono",
            _retangulo_pontos(300, 300, 305, 305),
            (0, 0, 0),
        ),  # pequeno demais
    ]
    pdf = _pdf_formas(tmp_path, "fund.pdf", formas)
    centros = forma3d.circulos(pdf, "2", (22, 23.5), REGIAO)
    assert centros.shape == (1, 2) and centros[0] == pytest.approx([130, 120], abs=0.1)
    blocos = forma3d.blocos_fechados(pdf, "3", REGIAO, 200)
    assert [round(b.area) for b in blocos] == [2700, 2400]
    assert forma3d.bloco_de_cada_estaca([[130, 120], [500, 500]], blocos) == [0, None]


def test_z0_pelos_blocos_minimo_moda_e_sem_bloco():
    blocos = [
        (box(0, 0, 1, 1), 800.75),
        (box(2, 0, 3, 1), 800.55),
        (box(2, 2, 3, 3), 800.55),
        (box(10, 10, 11, 11), 790.0),
    ]
    perto = box(0.5, 0.5, 2.5, 0.8)  # toca os dois primeiros
    assert forma3d.z0_pelos_blocos(perto, blocos, "minimo", 700.0) == 800.55
    grande = box(-1, -1, 3.5, 3.5)  # centros de três blocos dentro
    assert forma3d.z0_pelos_blocos(grande, blocos, "moda", 700.0) == 800.55
    assert (
        forma3d.z0_pelos_blocos(box(50, 50, 51, 51), blocos, "minimo", 700.0) == 700.0
    )
    assert forma3d.z0_pelos_blocos(box(50, 50, 51, 51), blocos, "moda", 700.0) == 700.0
    with pytest.raises(ValueError):
        forma3d.z0_pelos_blocos(perto, blocos, "media", 0)


def test_fatiar_por_zonas_usa_o_z_da_zona_e_o_do_elemento_fora_dela():
    espec = {
        "z0": 1.0,
        "z1": 5.0,
        "zonas": [{"regiao_pt": [50, 0, 200, 100], "z1": 9.0, "z0": 2.0}],
    }
    fatias = forma3d._fatiar_por_zonas(box(0, 0, 100, 10), espec)
    por_z = {(z0, z1): p.area for p, z0, z1 in fatias}
    assert por_z == {(2.0, 9.0): pytest.approx(500), (1.0, 5.0): pytest.approx(500)}
    nivel = forma3d._cotas_do_elemento({"nivel": 800.75, "altura_m": 0.5})
    assert nivel == pytest.approx((800.25, 800.75))


def test_conferir_folha_aceita_translacao_certa_e_reprova_a_errada(tmp_path):
    centros = [(130, 120), (330, 120), (130, 320), (350, 320)]
    base = _pdf_formas(
        tmp_path,
        "base.pdf",
        [
            (
                "12",
                "preenchido",
                _retangulo_pontos(x - 6, y - 6, x + 6, y + 6),
                VERMELHO,
            )
            for x, y in centros
        ],
    )
    folha = _pdf_formas(
        tmp_path,
        "folha.pdf",
        [
            (
                "12",
                "preenchido",
                _retangulo_pontos(x - 46, y - 36, x - 34, y - 24),
                VERMELHO,
            )
            for x, y in centros
        ],
    )
    conferencia = {
        "chave": ["12", list(VERMELHO)],
        "regiao_pt": list(REGIAO),
        "tol_pt": 0.5,
    }
    certa = forma3d.conferir_folha(
        folha, base, np.array([[1, 0, 40], [0, 1, 30], [0, 0, 1.0]]), conferencia
    )
    assert certa["ok"] and certa["casados"] == 4 and certa["diferenca_pt"] < 0.1
    errada = forma3d.conferir_folha(
        folha, base, np.array([[1, 0, 43], [0, 1, 30], [0, 0, 1.0]]), conferencia
    )
    assert not errada["ok"] and errada["diferenca_pt"] == pytest.approx(3, abs=0.1)
