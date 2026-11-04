"""Testes sintéticos do CAD × CAD com escala fixa (folha de detalhe 1:100 sobre a base já georreferenciada)."""

import cv2
import numpy as np
import pytest

from camadas import geo, georef_prancha

ESCALA_M_PT = 100 * 0.0254 / 72  # título 1:100
RES_M_PX = 0.10


def _estrutura(semente: int = 7, n: int = 70, lado_m: float = 90.0) -> list[np.ndarray]:
    """Caixas, tubos de par de linhas e 'L' espalhados, sem simetria: o SIFT precisa de cantos distintos."""
    rng = np.random.default_rng(semente)
    linhas = []
    for _ in range(n):
        x, y = rng.uniform(0, lado_m, 2)
        w, h = rng.uniform(1.5, 9.0, 2)
        tipo = rng.integers(0, 3)
        if tipo == 0:  # caixa
            linhas.append(
                np.array([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])
            )
        elif tipo == 1:  # tubo: par de linhas de largura 0,53 m
            linhas.append(np.array([(x, y), (x + 3 * w, y)]))
            linhas.append(np.array([(x, y + 0.53), (x + 3 * w, y + 0.53)]))
        else:  # L
            linhas.append(np.array([(x, y), (x, y + 2 * h), (x + w, y + 2 * h)]))
    return linhas


def _traco(partes_pt: list[np.ndarray], layer: str = "CISM_09_LINHA_ALVENARIA") -> dict:
    return {"layer": layer, "partes": partes_pt, "fechado": False}


def _afim_verdadeira(
    graus: float, escala_m_pt: float, e0: float, n0: float
) -> np.ndarray:
    """pt -> UTM com reflexão (y da folha para baixo), como a das pranchas reais."""
    t = np.radians(graus)
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    A = escala_m_pt * R @ np.diag([1.0, -1.0])
    M = np.eye(3)
    M[:2, :2] = A
    M[:2, 2] = [e0, n0]
    return M


@pytest.fixture(scope="module")
def cenario(tmp_path_factory):
    """Base rasterizada (UTM) + folha de detalhe gerada por uma afim conhecida a partir da mesma estrutura."""
    pasta = tmp_path_factory.mktemp("ref")
    e0, n0 = 745000.0, 7183000.0
    estrutura_utm = [u + [e0, n0 - 120.0] for u in _estrutura()]
    # referência: raster das linhas (preto sobre cinza 230), 10 cm/px, com o canto superior esquerdo em (e0, n_topo)
    n_topo = n0 - 120.0 + 100.0
    img = np.full((1100, 1300), 230, np.uint8)
    for u in estrutura_utm:
        q = np.round(
            np.c_[(u[:, 0] - e0) / RES_M_PX, (n_topo - u[:, 1]) / RES_M_PX]
        ).astype(np.int32)
        cv2.polylines(img, [q], False, 0, 2, cv2.LINE_AA)
    caminho = pasta / "_ref.png"
    cv2.imwrite(str(caminho), img)
    geo.salvar_georef(caminho, e0, n_topo, RES_M_PX, 31981)
    # detalhe: mesma geometria em pt, por uma afim conhecida (rotação de 90°, escala 1:100, folha deslocada), mais
    # linhas que a base não tem (a folha de detalhe sempre desenha mais que o layout)
    M_ver = _afim_verdadeira(90.0, ESCALA_M_PT, e0 + 40.0, n_topo - 10.0)
    inv = np.linalg.inv(M_ver)
    rng = np.random.default_rng(3)
    extras = [rng.uniform(0, 90, (2, 2)) + [e0, n0 - 120.0] for _ in range(25)]
    tracos = [_traco([geo.aplicar(inv, u) for u in estrutura_utm + extras])]
    return {
        "ref": caminho,
        "tracos": tracos,
        "M_ver": M_ver,
        "estrutura": estrutura_utm,
    }


def test_ajustar_rigido_recupera_rotacao_e_translacao():
    rng = np.random.default_rng(1)
    pts = rng.uniform(0, 50, (30, 2))
    t = np.radians(37.0)
    R = np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    M = georef_prancha.ajustar_rigido(pts, pts @ R.T + [12.0, -4.0])
    np.testing.assert_allclose(M[:2, :2], R, atol=1e-9)
    np.testing.assert_allclose(M[:2, 2], [12.0, -4.0], atol=1e-9)
    assert np.isclose(np.linalg.det(M[:2, :2]), 1.0)  # sem reflexão e sem escala


def test_detalhe_1_para_100_e_recuperado_com_escala_fixa(cenario):
    r = georef_prancha.registrar_cad_escala_fixa(
        cenario["tracos"], cenario["ref"], ESCALA_M_PT, "ALVENARIA", log=lambda *a: None
    )
    assert r["ok"], r["motivo"]
    M = r["M"]
    # a escala é a do título (não foi ajustada) e a posição bate com a afim verdadeira, em m (tolerância absoluta)
    assert np.isclose(np.sqrt(abs(np.linalg.det(M[:2, :2]))), ESCALA_M_PT, rtol=1e-9)
    assert np.linalg.det(M[:2, :2]) < 0  # reflexão preservada
    pontos_pt = np.array(
        [[0.0, 0.0], [800.0, 0.0], [800.0, 600.0], [0.0, 600.0], [400.0, 300.0]]
    )
    erro_m = np.linalg.norm(
        geo.aplicar(M, pontos_pt) - geo.aplicar(cenario["M_ver"], pontos_pt), axis=1
    )
    assert erro_m.max() <= 0.15
    assert r["residuo_mediano_m"] <= 0.15
    assert r["inliers"] >= 15
    assert abs(r["escala_sift"] - 1.0) <= 0.02


def test_janela_recorta_os_tracos_da_vista(cenario):
    """A janela escolhe a vista: sem traço com centro dentro dela, o registro recusa em vez de inventar."""
    r = georef_prancha.registrar_cad_escala_fixa(
        cenario["tracos"],
        cenario["ref"],
        ESCALA_M_PT,
        "ALVENARIA",
        janela_pt=[-9e3, -9e3, -8e3, -8e3],
        log=lambda *a: None,
    )
    assert not r["ok"] and r["M"] is None and "sem traços" in r["motivo"]


def test_layer_inexistente_e_recusado(cenario):
    r = georef_prancha.registrar_cad_escala_fixa(
        cenario["tracos"],
        cenario["ref"],
        ESCALA_M_PT,
        "TUBULACAO_QUE_NAO_EXISTE",
        log=lambda *a: None,
    )
    assert not r["ok"] and r["M"] is None


def test_escala_que_nao_bate_e_rejeitada(cenario):
    """Folha de detalhe (1:100) declarada na escala do layout (1:250): a escala que o SIFT acha é 0,4 e não 1."""
    errada = 250 * 0.0254 / 72
    r = georef_prancha.registrar_cad_escala_fixa(
        cenario["tracos"], cenario["ref"], errada, "ALVENARIA", log=lambda *a: None
    )
    assert not r["ok"] and r["M"] is None
    assert "escala" in r["motivo"]
