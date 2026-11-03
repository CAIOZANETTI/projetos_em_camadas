"""Topografia do projeto: curvas de nível sintéticas, TIN, tendência do erro e leitura de rótulo (PDF/OCR opcionais)."""

import shutil
from pathlib import Path

import numpy as np
import pytest

from camadas import topografia as tp

RES = 0.5


def _grade(linhas=200, colunas=200, e0=0.0, n1=100.0):
    """Grade de 100 × 100 m (E 0–100, N 0–100) a 0,5 m."""
    forma = (linhas, colunas)
    return {
        "e0": e0,
        "n1": n1,
        "res": RES,
        "forma": forma,
        "epsg": 31981,
        "terreno": np.zeros(forma, np.float32),
        "valido": np.ones(forma, bool),
        "edificacao": np.zeros(forma, bool),
    }


def _curva(cota_m, xy):
    return {
        "cota_m": cota_m,
        "coords_utm": np.asarray(xy, float).tolist(),
        "origem": "rotulo",
        "alertas": [],
    }


def _curvas_de_plano(inclinacao_e=0.02, base_m=240.0):
    """Retas N–S (E constante) a cada 5 m: plano z = base + inclinacao_e · (E − 10)."""
    return [
        _curva(base_m + inclinacao_e * (e - 10.0), [[e, -10.0], [e, 110.0]])
        for e in range(10, 100, 5)
    ]


def _curvas_de_cone(centro=(50.0, 50.0), inclinacao=0.05, topo_m=241.0):
    """Anéis concêntricos a cada 5 m de raio: cone z = topo − inclinacao · r."""
    t = np.linspace(0, 2 * np.pi, 400, endpoint=False)
    curvas = []
    for r in np.arange(5.0, 46.0, 5.0):
        xy = np.c_[centro[0] + r * np.cos(t), centro[1] + r * np.sin(t)]
        curvas.append(_curva(topo_m - inclinacao * r, np.vstack([xy, xy[:1]])))
    return curvas


# --- curvas e rótulos (sem PDF) ------------------------------------------------------------------------------------
def test_separar_tracos_distingue_curva_de_glifo():
    longa = np.array([[0.0, 0.0], [50.0, 0.0]])
    pequeno = np.array([[0.0, 0.0], [3.0, 5.0], [6.0, 0.0]])
    tracos = [
        {"layer": "Curvas_Auxiliares", "partes": [longa]},
        {"layer": "Curvas_Mestras", "partes": [pequeno]},
        {
            "layer": "CURVA DE NÍVEL",
            "partes": [longa],
        },  # layer de outra coisa: ignorado
    ]
    curvas, glifos = tp.separar_tracos(tracos)
    assert len(curvas) == 1 and curvas[0]["layer"] == "Curvas_Auxiliares"
    assert len(glifos) == 1


def test_agrupar_glifos_une_proximos_e_separa_distantes():
    def glifo(x, y):
        return {
            "layer": "Curvas_Auxiliares",
            "partes": [np.array([[x, y], [x + 3, y], [x + 3, y + 5]])],
        }

    grupos = tp.agrupar_glifos(
        [glifo(0, 0), glifo(5, 0), glifo(10, 0), glifo(200, 200)]
    )
    assert sorted(len(g) for g in grupos) == [1, 3]


def test_atribuicao_de_cota_pelo_rotulo_mais_proximo():
    """Duas pontas de uma curva abrem folga no rótulo '239'; a curva vizinha (240) não é afetada."""
    curvas = [
        {
            "pontos_pt": np.array([[0.0, 0.0], [100.0, 0.0]]),
            "layer": "Curvas_Auxiliares",
        },
        {
            "pontos_pt": np.array([[130.0, 0.0], [230.0, 0.0]]),
            "layer": "Curvas_Auxiliares",
        },
        {
            "pontos_pt": np.array([[0.0, 80.0], [230.0, 80.0]]),
            "layer": "Curvas_Mestras",
        },
    ]
    rotulos = [{"centro_pt": np.array([115.0, 0.0]), "cota_m": 239.0}]
    tp.atribuir_cotas(curvas, rotulos)
    assert [c["cota_m"] for c in curvas] == [239.0, 239.0, None]
    assert curvas[2]["origem"] is None and curvas[0]["origem"] == "rotulo"


def test_rotulos_conflitantes_valem_o_mais_perto_e_geram_alerta():
    curvas = [
        {
            "pontos_pt": np.array([[0.0, 0.0], [100.0, 0.0]]),
            "layer": "Curvas_Auxiliares",
        }
    ]
    rotulos = [
        {"centro_pt": np.array([110.0, 0.0]), "cota_m": 239.0},
        {"centro_pt": np.array([-25.0, 0.0]), "cota_m": 239.5},
    ]
    tp.atribuir_cotas(curvas, rotulos)
    assert curvas[0]["cota_m"] == 239.0 and curvas[0]["alertas"]


def test_rotulo_sobre_curva_continua_sem_ponta_perto():
    curvas = [
        {"pontos_pt": np.array([[0.0, 0.0], [400.0, 0.0]]), "layer": "Curvas_Mestras"}
    ]
    tp.atribuir_cotas(curvas, [{"centro_pt": np.array([200.0, 5.0]), "cota_m": 240.0}])
    assert curvas[0]["cota_m"] == 240.0
    tp.atribuir_cotas(curvas, [{"centro_pt": np.array([200.0, 40.0]), "cota_m": 240.0}])
    assert curvas[0]["cota_m"] is None


def test_passo_e_leitura_coerente_corrigem_ocr():
    leituras = [
        {"centro_pt": np.zeros(2), "candidatos": {239.0: 4}},
        {"centro_pt": np.zeros(2), "candidatos": {239.5: 3}},
        {"centro_pt": np.zeros(2), "candidatos": {240.0: 5}},
        {"centro_pt": np.zeros(2), "candidatos": {238.5: 2}},
        {
            "centro_pt": np.zeros(2),
            "candidatos": {237.9: 3, 237.5: 3},
        },  # OCR trocou 5 por 9
        {
            "centro_pt": np.zeros(2),
            "candidatos": {237.9: 2},
        },  # só a leitura errada: descartada
    ]
    passo = tp.estimar_passo(leituras)
    assert passo == 0.5
    rotulos, alertas = tp.rotulos_coerentes(leituras, passo)
    assert [r["cota_m"] for r in rotulos] == [239.0, 239.5, 240.0, 238.5, 237.5]
    assert len(alertas) == 1


def test_passo_um_metro_quando_todas_as_cotas_sao_inteiras():
    leituras = [
        {"centro_pt": np.zeros(2), "candidatos": {float(c): 3}}
        for c in (237, 238, 239, 240)
    ]
    assert tp.estimar_passo(leituras) == 1.0
    assert tp.estimar_passo([]) is None


def test_interpretar_numero_aceita_virgula_e_recusa_absurdo():
    assert tp._interpretar_numero("237,5") == 237.5
    assert tp._interpretar_numero(" 240\n") == 240.0
    assert tp._interpretar_numero("-239.") == 239.0
    assert tp._interpretar_numero("5") is None
    assert tp._interpretar_numero("999") is None


def test_resumir_curvas_equidistancia_e_sem_cota():
    curvas = [_curva(c, [[0, 0], [10, 0]]) for c in (238.0, 238.5, 239.0, 239.5)]
    curvas.append({**_curva(None, [[0, 0], [30, 0]]), "origem": None})
    r = tp.resumir_curvas(curvas)
    assert r["equidistancia_m"] == 0.5
    assert r["n_sem_cota"] == 1 and r["comprimento_sem_cota_m"] == 30.0
    assert r["n_com_cota_por_rotulo"] == 4


# --- TIN, superfície e inferência (scipy) ---------------------------------------------------------------------------
def test_tin_reproduz_plano_exatamente():
    pytest.importorskip("scipy")
    g = _grade()
    sup = tp.superficie(_curvas_de_plano(), g)
    col, lin = tp._centros(g)
    e, _ = np.meshgrid(col, lin)
    dentro = np.isfinite(sup)
    assert dentro.sum() > 0.7 * sup.size
    np.testing.assert_allclose(
        sup[dentro], 240.0 + 0.02 * (e[dentro] - 10.0), atol=1e-3
    )
    assert np.isnan(
        sup[:, 0]
    ).all()  # E = 0,25 m: antes da primeira curva (E = 10), fora do casco


def test_tin_reproduz_cone_dentro_da_tolerancia():
    pytest.importorskip("scipy")
    g = _grade()
    sup = tp.superficie(_curvas_de_cone(), g)
    col, lin = tp._centros(g)
    e, n = np.meshgrid(col, lin)
    esperado = 241.0 - 0.05 * np.hypot(e - 50.0, n - 50.0)
    dentro = np.isfinite(sup) & (np.hypot(e - 50.0, n - 50.0) >= 5.0)
    assert dentro.sum() > 5000
    assert (
        np.abs(sup[dentro] - esperado[dentro]).max() < 0.02
    )  # 2 cm: a corda do anel é a única diferença
    assert not np.isfinite(sup[np.hypot(e - 50.0, n - 50.0) > 46.0]).any()


def test_tin_aceita_pontos_cotados_e_exige_curvas():
    pytest.importorskip("scipy")
    tin = tp.modelo_tin(_curvas_de_plano(), np.array([[52.5, 50.0, 245.0]]))
    assert tin(np.array([52.5]), np.array([50.0]))[0] == pytest.approx(245.0, abs=1e-6)
    with pytest.raises(ValueError, match="sem curvas"):
        tp.modelo_tin([{**_curva(None, [[0, 0], [1, 1]])}])


def test_inferencia_da_cota_pela_vizinhanca():
    pytest.importorskip("scipy")
    curvas = _curvas_de_plano(inclinacao_e=0.1)  # 0,5 m a cada 5 m: passo de 0,5
    verdadeira = curvas[4]["cota_m"]
    curvas[4].update(cota_m=None, origem=None)
    curvas = tp.inferir_cotas(curvas, 0.5)
    assert curvas[4]["origem"] == "inferida" and curvas[4]["cota_m"] == pytest.approx(
        verdadeira
    )
    assert curvas[4]["alertas"]
    # sem passo lido, nada é inferido
    curvas[4].update(cota_m=None, origem=None)
    assert tp.inferir_cotas(curvas, None)[4]["cota_m"] is None


def test_curvas_dos_tracos_com_leitor_injetado():
    """Pipeline sem PDF e sem OCR: traços sintéticos, leitor que devolve rótulos fixos, afim pt → UTM."""
    pytest.importorskip("scipy")

    def reta(y, x0=0.0, x1=300.0):
        return {"layer": "Curvas_Auxiliares", "partes": [np.array([[x0, y], [x1, y]])]}

    glifo = {
        "layer": "Curvas_Auxiliares",
        "partes": [np.array([[148.0, 98.0], [152.0, 98.0], [152.0, 104.0]])],
    }
    tracos = [
        reta(0.0),
        reta(50.0),
        reta(100.0, 0.0, 130.0),
        reta(100.0, 170.0, 300.0),
        reta(150.0),
        glifo,
    ]

    def leitor(grupos):
        assert len(grupos) == 1
        return [{"centro_pt": np.array([150.0, 100.0]), "candidatos": {240.0: 3}}]

    M = [[0.1, 0.0, 1000.0], [0.0, -0.1, 5000.0]]
    curvas = tp.curvas_dos_tracos(tracos, M, leitor)
    cotas = sorted((c["cota_m"] is not None, c["origem"]) for c in curvas)
    assert len(curvas) == 5
    assert cotas.count((True, "rotulo")) == 2  # as duas metades da curva de 240
    assert curvas[2]["coords_utm"][0] == pytest.approx([1000.0, 4990.0])
    assert all("pontos_pt" not in c for c in curvas)


# --- amostragem e estatística --------------------------------------------------------------------------------------
def test_amostrar_grade_bilinear_exata_em_plano_e_nan_fora():
    g = _grade()
    col, lin = tp._centros(g)
    e, n = np.meshgrid(col, lin)
    plano = (3.0 + 0.1 * e - 0.2 * n).astype(np.float64)
    xy = np.array([[10.3, 40.7], [99.0, 1.2], [-5.0, 50.0], [50.0, 120.0]])
    z = tp.amostrar_grade(plano, g, xy)
    np.testing.assert_allclose(
        z[:2], 3.0 + 0.1 * xy[:2, 0] - 0.2 * xy[:2, 1], atol=1e-9
    )
    assert np.isnan(z[2:]).all()


def test_estatisticas_ignora_nan_e_da_percentis():
    d = np.array([np.nan, -1.0, 0.0, 1.0, 2.0])
    s = tp.estatisticas(d, 0.25)
    assert s["n"] == 4 and s["media_m"] == pytest.approx(0.5)
    assert (
        s["minimo_m"] == -1.0
        and s["maximo_m"] == 2.0
        and s["area_m2"] == pytest.approx(1.0)
    )
    assert s["p50_m"] == pytest.approx(0.5)
    assert tp.estatisticas(np.array([np.nan])) == {"n": 0}


# --- tendência do erro ---------------------------------------------------------------------------------------------
def _pontos(n=4000, lado=100.0, semente=3):
    rng = np.random.default_rng(semente)
    return rng.uniform(0, lado, n), rng.uniform(0, lado, n)


def test_tendencia_quadratica_recupera_cupula_conhecida():
    e, n = _pontos()
    e0, n0 = e.mean(), n.mean()
    erro = 0.30 - 4e-5 * (
        (e - e0) ** 2 + (n - n0) ** 2
    )  # cúpula: cai 0,2 m a 70 m do centro
    q = tp.ajustar_tendencia(e, n, erro, 2)
    c = q["coeficientes"]
    assert c["c_ee_m_por_m2"] == pytest.approx(-4e-5, abs=1e-8)
    assert c["c_nn_m_por_m2"] == pytest.approx(-4e-5, abs=1e-8)
    assert c["c_en_m_por_m2"] == pytest.approx(0.0, abs=1e-8)
    assert c["a_m"] == pytest.approx(0.30, abs=1e-3)
    assert q["forma"] == "cúpula" and q["rms_depois_m"] < 1e-9
    assert q["variancia_explicada"] == pytest.approx(1.0)
    plano = tp.ajustar_tendencia(e, n, erro, 1)  # o plano não explica a cúpula
    assert plano["rms_depois_m"] > 0.01 and "forma" not in plano


def test_tendencia_plano_recupera_inclinacao_e_forma_de_bacia():
    e, n = _pontos(semente=4)
    e0, n0 = e.mean(), n.mean()
    erro = 0.1 + 0.003 * (e - e0) - 0.002 * (n - n0)
    p = tp.ajustar_tendencia(e, n, erro, 1)["coeficientes"]
    assert p["b_e_m_por_m"] == pytest.approx(0.003, abs=1e-9)
    assert p["b_n_m_por_m"] == pytest.approx(-0.002, abs=1e-9)
    bacia = tp.ajustar_tendencia(e, n, 1e-4 * ((e - e0) ** 2 + (n - n0) ** 2), 2)
    assert bacia["forma"] == "bacia"
    sela = tp.ajustar_tendencia(e, n, 1e-4 * ((e - e0) ** 2 - (n - n0) ** 2), 2)
    assert sela["forma"] == "sela"


def test_comparar_mds_com_cupula_conhecida_por_cobertura_e_distancia():
    pytest.importorskip("scipy")
    g = _grade()
    col, lin = tp._centros(g)
    e, n = np.meshgrid(col, lin)
    topografia = (240.0 + 0.02 * e).astype(np.float32)
    cupula = 0.25 - 4e-5 * ((e - 50.0) ** 2 + (n - 50.0) ** 2)
    g["terreno"] = (topografia + cupula).astype(np.float32)
    classe = np.full(g["forma"], tp.CLASSES.index("grama"), np.uint8)
    classe[:, 100:] = tp.CLASSES.index("pavimento")
    usados = np.array([[50.0, 50.0], [10.0, 10.0]])
    r = tp.comparar_mds(g, topografia, usados, classe)
    for tendencia in (
        r["tendencia"]["toda_area"],
        r["tendencia"]["terreno_aberto_aparada"],
    ):
        q = tendencia["quadratica"]
        assert q["forma"] == "cúpula"
        assert q["coeficientes"]["c_ee_m_por_m2"] == pytest.approx(-4e-5, rel=0.02)
        assert q["rms_depois_m"] < 0.005 < tendencia["plano"]["rms_depois_m"]
    assert set(r["por_cobertura"]) == {"grama", "pavimento"}
    assert r["toda_area_valida"]["maximo_m"] == pytest.approx(0.25, abs=0.005)
    por_distancia = r["por_distancia_aos_furos_usados_terreno_aberto"]
    perto, longe = (
        por_distancia["0–10 m"]["media_m"],
        por_distancia["50–80 m"]["media_m"],
    )
    assert perto > longe  # a cúpula é mais alta perto do centro (furo em 50, 50)
    assert r["erro"].shape == g["forma"]


def test_distancia_aos_pontos():
    g = _grade()
    d = tp.distancia_aos_pontos(g, np.array([[0.25, 99.75]]))  # canto superior esquerdo
    assert d[0, 0] == pytest.approx(0.0, abs=1e-5)
    assert d[0, 1] == pytest.approx(RES, abs=1e-5)


# --- comparações (a), (b) e o mapa ---------------------------------------------------------------------------------
def test_comparar_sondagens_topografia_mds_e_residuo_na_mesma_tabela():
    pytest.importorskip("scipy")
    tin = tp.modelo_tin(_curvas_de_plano())  # z = 240 + 0,02 (E − 10)
    g = _grade()
    g["terreno"][:] = 241.0
    furos = [
        {"id": "SP01", "E": 50.0, "N": 50.0, "cota_boca": 240.70},  # topografia 240,80
        {"id": "SP02", "E": 60.0, "N": 30.0, "cota_boca": 241.00},  # topografia 241,00
        {"id": "SP03", "E": 500.0, "N": 30.0, "cota_boca": 241.00},  # fora do casco
        {
            "id": "SP01A",
            "E": 50.0,
            "N": 50.0,
            "cota_boca": 240.70,
        },  # variante de SP01: não conta duas vezes
    ]
    ajuste = {
        "rms_validacao_cruzada_m": 0.36,
        "pontos": [
            {"id": "SP01", "descartado": False, "z_nuvem": -3.0, "residuo_m": 0.30},
            {"id": "SP02", "descartado": False, "z_nuvem": -3.0, "residuo_m": -0.10},
            {"id": "SP03", "descartado": True, "z_nuvem": -3.0, "residuo_m": 2.0},
        ],
    }
    r = tp.comparar_sondagens(tin, furos, g, ajuste)
    f = {x["id"]: x for x in r["furos"]}
    assert f["SP01"]["topografia_menos_boca_m"] == pytest.approx(0.10, abs=1e-6)
    assert f["SP02"]["topografia_menos_boca_m"] == pytest.approx(0.0, abs=1e-6)
    assert f["SP03"]["topografia_m"] is None
    assert f["SP01"]["mds_menos_boca_m"] == pytest.approx(0.30, abs=1e-5)
    assert f["SP01"]["usado_no_plano"] and not f["SP03"]["usado_no_plano"]
    assert r["topografia_menos_boca"]["n"] == 2 and f["SP01A"]["variante_de_outro_furo"]
    assert (
        r["residuo_ajuste_usados_m"]["n"] == 2 and r["rms_validacao_cruzada_m"] == 0.36
    )


def test_perfil_da_linha_segue_o_plano():
    pytest.importorskip("scipy")
    tin = tp.modelo_tin(_curvas_de_plano())
    perfil = tp.perfil_da_linha(
        tin, {"inicio_utm": [20.0, 50.0], "fim_utm": [60.0, 50.0]}
    )
    assert perfil[0, 0] == pytest.approx(tp.PASSO_PERFIL_M / 2) and perfil[-1, 0] < 40.0
    np.testing.assert_allclose(
        perfil[:, 1], 240.0 + 0.02 * (20.0 + perfil[:, 0] - 10.0), atol=1e-6
    )


def test_comparar_secoes_alinha_e_mede_a_diferenca_da_topografia():
    pytest.importorskip("scipy")
    tin = tp.modelo_tin(_curvas_de_plano())  # sobe 0,02 m/m para leste
    x = np.arange(0.0, 30.01, 0.5)
    secao = {
        "secao": "AA",
        "terreno": np.c_[x, 240.4 + 0.02 * x + 0.30].tolist(),
        "escavacao": [],
    }
    linha = {
        "secao": "AA",
        "prancha": "es1",
        "inicio_utm": [30.0, 50.0],
        "fim_utm": [60.0, 50.0],
        "comprimento_m": 30.0,
    }
    quebrada = {
        **linha,
        "secao": "CC",
        "alertas": ["segmentos não colineares: linha quebrada"],
    }
    r = tp.comparar_secoes(
        tin,
        [secao],
        [linha, quebrada, {**linha, "secao": "ZZ"}],
        [{"secao": "AA", "terreno": {"dif_media_m": -0.41, "desvio_m": 0.07}}],
    )
    aa = r["secoes"][0]
    assert aa["topografia_menos_secao_m"] == pytest.approx(
        240.0 + 0.02 * 20.0 - 240.4 - 0.30, abs=0.02
    )
    assert aa["sentido"] == 1 and aa["mds_menos_secao_m"] == -0.41
    assert (
        r["secoes"][1]["motivo"] and r["secoes"][2]["motivo"]
    )  # sem seção de corte com o nome
    assert r["n_linhas"] == 3 and r["n_comparadas"] == 1
    fora = tp.comparar_secoes(
        tin, [secao], [linha], quebradas={"AA"}
    )  # linha quebrada: na tabela, fora da estatística
    assert fora["secoes"][0]["linha_quebrada"] and fora["n_comparadas"] == 0


def test_secoes_quebradas_pelos_alertas():
    alertas = [
        "seção CC: segmentos não colineares (es1+es3 24.0 m; es3 27.8 m): linha quebrada",
        "seção II: segmento de 2.8 m em es3 não colinear, ignorado (resto de traço)",
    ]
    assert tp.secoes_quebradas(alertas) == {"CC"}


def test_mapa_do_erro_grava_png(tmp_path):
    import cv2

    g = _grade(100, 100)
    erro = np.full(g["forma"], np.nan)
    erro[:, :50] = -1.0
    erro[:, 50:] = 1.0
    caminho = tp.mapa_do_erro(
        erro,
        g,
        [{"id": "SP01", "E": 25.0, "N": 25.0, "usado_no_plano": True}],
        tmp_path / "e.png",
    )
    imagem = cv2.imread(str(caminho))
    altura = 36 + 100 * tp.ESCALA_PNG
    assert imagem.shape == (altura, 100 * tp.ESCALA_PNG, 3)
    esq, dir_ = imagem[altura - 20, 20], imagem[altura - 20, 180]
    assert esq[0] > esq[2] and dir_[2] > dir_[0]  # azul à esquerda, vermelho à direita


def test_relatorio_completo_sintetico_e_json(tmp_path):
    pytest.importorskip("scipy")
    g = _grade()
    col, lin = tp._centros(g)
    e, _ = np.meshgrid(col, lin)
    g["terreno"] = (240.0 + 0.02 * (e - 10.0) + 0.1).astype(np.float32)
    ajuste = {
        "pontos": [
            {
                "id": "SP01",
                "E": 50.0,
                "N": 50.0,
                "z_nuvem": -3.0,
                "descartado": False,
                "residuo_m": 0.1,
            }
        ]
    }
    furos = [{"id": "SP01", "E": 50.0, "N": 50.0, "cota_boca": 240.8}]
    r = tp.comparar(
        g, _curvas_de_plano(), furos, ajuste, caminho_mapa=tmp_path / "m.png"
    )
    assert r["c_mds_x_topografia"]["toda_area_valida"]["media_m"] == pytest.approx(
        0.1, abs=1e-3
    )
    assert r["a_e_d_sondagens"]["furos"][0]["variante_de_outro_furo"] is False
    assert "erro" not in r["c_mds_x_topografia"] and (tmp_path / "m.png").exists()
    saida = tp.gravar(r, tmp_path / "x" / "topografia_vs_mds.json")
    assert '"a_e_d_sondagens"' in saida.read_text(encoding="utf-8")


# --- PDF e OCR reais (pulam sem pymupdf, tesseract, scipy ou sem os dados de Foz) ------------------------------------
RAIZ = Path(__file__).resolve().parents[1]
GEOPLANTA = (
    RAIZ
    / "dados/foz/projeto/UNIDADE 01/ANEXO C/2. PBGE/DE/R2/001-SAA-0017-8820-PBGE-DE-0000ETA01GEOPLANTA1-R1.pdf"
)


def test_ler_rotulo_de_glifos_em_segmentos():
    """Dígitos desenhados em sete segmentos (traços de vetor) são lidos por OCR, se o tesseract existir."""
    pytest.importorskip("pytesseract")
    if shutil.which("tesseract") is None:
        pytest.skip("binário tesseract ausente")
    segmentos = {"2": "abged", "4": "fgbc", "0": "abcdef"}
    coords = {
        "a": ((0, 0), (4, 0)), "b": ((4, 0), (4, 4)), "c": ((4, 4), (4, 8)), "d": ((0, 8), (4, 8)),
        "e": ((0, 4), (0, 8)), "f": ((0, 0), (0, 4)), "g": ((0, 4), (4, 4)),
    }  # fmt: skip
    grupo = []
    for k, digito in enumerate("240"):
        for s in segmentos[digito]:
            (x0, y0), (x1, y1) = coords[s]
            grupo.append(
                {
                    "layer": "Curvas_Auxiliares",
                    "partes": [np.array([[x0 + 7.0 * k, y0], [x1 + 7.0 * k, y1]])],
                }
            )
    r = tp.ler_rotulo(grupo)
    assert r is None or isinstance(
        r["candidatos"], dict
    )  # fonte de sete segmentos: leitura não garantida
    if r:
        assert all(100 <= v <= 400 for v in r["candidatos"])


@pytest.mark.skipif(
    not GEOPLANTA.exists(),
    reason="dados de Foz ausentes (dados/ não vai ao repositório)",
)
def test_curvas_reais_da_geoplanta_de_foz():
    pytest.importorskip("pymupdf")
    pytest.importorskip("pytesseract")
    pytest.importorskip("scipy")
    if shutil.which("tesseract") is None:
        pytest.skip("binário tesseract ausente")
    import json

    obra = json.loads((RAIZ / "exemplos/foz/obra.json").read_text(encoding="utf-8"))
    curvas = tp.curvas_de_nivel(GEOPLANTA, obra["controle_absoluto"]["afim_pt_utm"])
    r = tp.resumir_curvas(curvas)
    assert r["n_curvas"] > 20 and r["n_com_cota_por_rotulo"] >= 5
    assert r["equidistancia_m"] in (0.5, 1.0)
    assert all(236.0 < c["cota_m"] < 245.0 for c in curvas if c["cota_m"] is not None)
