"""Testes de camadas.secoes_corte com PDF sintético (quadro de perfil, terreno e contorno de escavação)."""

import itertools
import shutil

import numpy as np
import pytest

from camadas import pdf_cad, secoes_corte

pymupdf = pytest.importorskip("pymupdf")

PT_POR_M = 20.0  # escala do quadro sintético (x e y)
X0, Y0, X1, Y1 = 50.0, 50.0, 550.0, 350.0  # quadro de 25 m x 15 m
COTA_BASE_M = 215.0
MAGENTA = (1, 0, 1)


def _y(cota_m: float) -> float:
    return Y1 - (cota_m - COTA_BASE_M) * PT_POR_M


def _x(distancia_m: float) -> float:
    return X0 + distancia_m * PT_POR_M


def _pdf(
    caminho,
    terreno_m=((0, 225), (25, 225)),
    contorno_m=(),
    com_terreno=True,
    extras=None,
    deslocar_marcas_x=(),
    rotulos=False,
):
    """Quadro sintético com ticks de 1 m (longos a cada 5 m), terreno e contorno tracejado (segmentos soltos)."""
    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=400)
    oc_q, oc_t, oc_e = (
        doc.add_ocg(n) for n in ("C-ROAD-PROF-VIEW", "TERRENO ORIGINAL", "ESCAVAÇÃO")
    )
    pg.draw_rect(pymupdf.Rect(X0, Y0, X1, Y1), color=(0, 0, 0), oc=oc_q)
    for k in range(16):  # cota: 215 .. 230
        meio = 6 if k % 5 else 12
        pg.draw_line(
            (X0 - meio / 2, _y(COTA_BASE_M + k)),
            (X0 + meio / 2, _y(COTA_BASE_M + k)),
            color=(0, 0, 0),
            oc=oc_q,
        )
        if rotulos and k % 5 == 0:
            pg.insert_text(
                (X0 - 34, _y(COTA_BASE_M + k) + 3),
                str(int(COTA_BASE_M + k)),
                fontsize=8,
            )
    for k in range(26):  # distância: 0 .. 25
        meio = 6 if k % 5 else 12
        deslocamento = 5.0 if k in deslocar_marcas_x else 0.0
        pg.draw_line(
            (_x(k) + deslocamento, Y1 - meio / 2),
            (_x(k) + deslocamento, Y1 + meio / 2),
            color=(0, 0, 0),
            oc=oc_q,
        )
    if rotulos:
        pg.draw_rect(
            pymupdf.Rect(X0 + 20, Y0 + 19, X0 + 120, Y0 + 46), color=(0, 0, 0), oc=oc_q
        )
        pg.insert_text((X0 + 26, Y0 + 40), "SEÇÃO AA", fontsize=14)
    if com_terreno:
        pg.draw_polyline(
            [(_x(d), _y(z)) for d, z in terreno_m], color=(0, 0, 0), oc=oc_t
        )
        pg.draw_rect(
            pymupdf.Rect(_x(1), _y(226), _x(2), _y(225.5)),
            color=(0, 0, 0),
            fill=(1, 1, 1),
            oc=oc_t,
        )  # etiqueta
    for (da, za), (db, zb) in contorno_m:
        pg.draw_line((_x(da), _y(za)), (_x(db), _y(zb)), color=MAGENTA, oc=oc_e)
    if extras:
        extras(pg, oc_e)
    doc.save(caminho)
    return caminho


def _tracejar(pontos_m, passo_m=0.5, vao_m=0.1):
    """Quebra a polilinha (distância, cota) em segmentos com pequenos vãos, como o tracejado do projeto."""
    segmentos = []
    for (da, za), (db, zb) in itertools.pairwise(pontos_m):
        comprimento = np.hypot(db - da, zb - za)
        n = max(1, int(np.ceil(comprimento / passo_m)))
        for i in range(n):
            t0, t1 = i / n, (i + 1) / n - vao_m / comprimento
            segmentos.append(
                (
                    (da + t0 * (db - da), za + t0 * (zb - za)),
                    (da + t1 * (db - da), za + t1 * (zb - za)),
                )
            )
    return segmentos


def _ler(caminho, **kwargs):
    return secoes_corte.ler_secoes(caminho, cota_inferior_m=COTA_BASE_M, **kwargs)


def test_retangulo_sob_terreno_plano(tmp_path):
    # fundo 4 m abaixo do terreno (cota 225 -> 221), de 3 m a 13 m; as paredes verticais não contam
    contorno = [((3, 225), (3, 221)), ((13, 225), (13, 221)), ((3, 221), (13, 221))]
    (secao,) = _ler(_pdf(tmp_path / "a.pdf", contorno_m=contorno))
    assert secao["area_corte_m2"] == pytest.approx(40.0, abs=1e-6)
    assert secao["largura_corte_m"] == pytest.approx(10.0, abs=1e-6)
    assert secao["cota_fundo_min_m"] == pytest.approx(221.0, abs=1e-6)
    assert secao["m_por_pt_x"] == pytest.approx(1 / PT_POR_M) and secao[
        "m_por_pt_y"
    ] == pytest.approx(1 / PT_POR_M)
    assert secao["residuo_calibracao_m"] < secoes_corte.TOLERANCIA_CALIBRACAO_M
    assert secao["alertas"] == [] or all("título" in a for a in secao["alertas"])
    assert np.array(secao["terreno"])[:, 1] == pytest.approx(225.0, abs=1e-6)


def test_talude_trapezoidal_com_tracejado(tmp_path):
    # base 4 m (5..9) a 3 m de profundidade, topo 10 m (2..12): área do trapézio = (10 + 4) / 2 * 3 = 21
    perfil = [(2, 225), (5, 222), (9, 222), (12, 225)]
    (secao,) = _ler(_pdf(tmp_path / "b.pdf", contorno_m=_tracejar(perfil)))
    # o vão de 0,1 m do tracejado em cada quina é fechado por reta (corta a quina: erro ~2,5e-3 m²)
    assert secao["area_corte_m2"] == pytest.approx(21.0, abs=5e-3)
    assert secao["largura_corte_m"] == pytest.approx(
        10.0, abs=0.1
    )  # o último traço termina 0,1 m antes do terreno
    assert secao["cota_fundo_min_m"] == pytest.approx(222.0, abs=1e-6)
    assert not any("vão" in a for a in secao["alertas"])


def test_terreno_inclinado_com_cruzamento(tmp_path):
    # terreno de 225 (d=0) a 221 (d=20); fundo plano em 223 entre 0 e 20: só o triângulo acima do fundo conta
    terreno = ((0, 225), (20, 221))
    (secao,) = _ler(
        _pdf(tmp_path / "c.pdf", terreno_m=terreno, contorno_m=[((0, 223), (20, 223))])
    )
    assert secao["area_corte_m2"] == pytest.approx(0.5 * 10 * 2, abs=1e-6)
    assert secao["largura_corte_m"] == pytest.approx(10.0, abs=1e-6)


def test_sem_terreno_original_nao_calcula(tmp_path):
    (secao,) = _ler(
        _pdf(tmp_path / "d.pdf", com_terreno=False, contorno_m=[((3, 221), (13, 221))])
    )
    assert secao["area_corte_m2"] is None
    assert any("TERRENO ORIGINAL" in a for a in secao["alertas"])


def test_sem_contorno_nao_calcula(tmp_path):
    (secao,) = _ler(_pdf(tmp_path / "e.pdf"))
    assert secao["area_corte_m2"] is None
    assert any("sem contorno" in a for a in secao["alertas"])


def test_texto_chamada_e_preenchimento_nao_entram_no_contorno(tmp_path):
    def extras(pg, oc_e):
        pg.draw_polyline(
            [(_x(3 + 0.1 * i), _y(224) + (i % 2) * 3) for i in range(20)],
            color=(0, 0, 0),
            oc=oc_e,
        )  # glifo
        pg.draw_line(
            (_x(1), _y(219)), (_x(4), _y(219)), color=(1, 0, 0), oc=oc_e
        )  # chamada vermelha
        pg.draw_rect(
            pymupdf.Rect(_x(3), _y(220), _x(13), _y(218)),
            color=(1, 1, 1),
            fill=(1, 1, 1),
            oc=oc_e,
        )  # fundo branco

    (secao,) = _ler(
        _pdf(tmp_path / "f.pdf", contorno_m=[((3, 221), (13, 221))], extras=extras)
    )
    assert secao["area_corte_m2"] == pytest.approx(40.0, abs=1e-6)
    assert secao["cota_fundo_min_m"] == pytest.approx(221.0, abs=1e-6)
    assert any("descartado" in a for a in secao["alertas"])


def test_vao_grande_no_contorno_vira_alerta(tmp_path):
    contorno = [((3, 221), (6, 221)), ((9, 221), (13, 221))]  # vão de 3 m
    (secao,) = _ler(_pdf(tmp_path / "g.pdf", contorno_m=contorno))
    assert any("vão" in a for a in secao["alertas"])
    assert secao["area_corte_m2"] == pytest.approx(
        3 * 4 + 4 * 4, abs=1e-6
    )  # só onde as duas linhas existem


def test_calibracao_pela_grade_de_5_m(tmp_path):
    tracos = pdf_cad.extrair(_pdf(tmp_path / "h.pdf"))
    (quadro,) = secoes_corte.quadros(tracos)
    assert (
        quadro["x0_pt"],
        quadro["y0_pt"],
        quadro["x1_pt"],
        quadro["y1_pt"],
    ) == pytest.approx((X0, Y0, X1, Y1))
    cal = secoes_corte.calibrar(quadro, tracos, cota_inferior_m=COTA_BASE_M)
    assert cal["ok"] and cal["alertas"] == []
    assert cal["m_por_pt_x"] == pytest.approx(0.05) and cal[
        "m_por_pt_y"
    ] == pytest.approx(0.05)
    assert cal["residuo_calibracao_m"] < 1e-3
    pontos = secoes_corte._para_metros(np.array([[X0, Y1], [X1, Y0]]), cal)
    assert pontos == pytest.approx(np.array([[0.0, 215.0], [25.0, 230.0]]), abs=1e-6)


def test_calibracao_sem_cota_nem_ocr_da_alerta(tmp_path):
    tracos = pdf_cad.extrair(_pdf(tmp_path / "i.pdf"))
    (quadro,) = secoes_corte.quadros(tracos)
    cal = secoes_corte.calibrar(quadro, tracos)
    assert not cal["ok"] and cal["cota_base_m"] is None
    assert any("OCR" in a for a in cal["alertas"])


def test_marcas_deslocadas_saem_do_ajuste_com_alerta(tmp_path):
    tracos = pdf_cad.extrair(_pdf(tmp_path / "j.pdf", deslocar_marcas_x=(1, 2, 3)))
    (quadro,) = secoes_corte.quadros(tracos)
    cal = secoes_corte.calibrar(quadro, tracos, cota_inferior_m=COTA_BASE_M)
    assert cal["ok"] and cal["m_por_pt_x"] == pytest.approx(0.05)
    assert any("fora da malha" in a for a in cal["alertas"])


def test_sem_marcas_nao_calibra(tmp_path):
    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=400)
    pg.draw_rect(
        pymupdf.Rect(X0, Y0, X1, Y1),
        color=(0, 0, 0),
        oc=doc.add_ocg("C-ROAD-PROF-VIEW"),
    )
    doc.save(tmp_path / "k.pdf")
    tracos = pdf_cad.extrair(tmp_path / "k.pdf")
    (quadro,) = secoes_corte.quadros(tracos)
    assert not secoes_corte.calibrar(quadro, tracos, cota_inferior_m=COTA_BASE_M)["ok"]


def test_area_de_corte_trechos_com_cruzamento_e_nan():
    x = np.array([0.0, 2.0, 4.0, 6.0])
    terreno = np.array([1.0, -1.0, 2.0, 2.0])
    fundo = np.array([0.0, 0.0, 0.0, np.nan])
    area, largura = secoes_corte.area_de_corte(x, terreno, fundo)
    # trecho 1: triângulo acima de 0 (d: 1 -> -1): 0,5 * 1 * 1; trecho 2: d: -1 -> 2, triângulo 2 * 4/3... = 2²/(2*3)*2
    assert area == pytest.approx(0.5 + 2 * 2**2 / (2 * 3), abs=1e-9)
    assert largura == pytest.approx(
        1.0 + 2 * 2 / 3, abs=1e-9
    )  # trecho 3 tem NaN: não conta


def test_tabela_e_main_escrevem_saida(tmp_path, capsys):
    secoes = [
        {
            "secao": "AA",
            "prancha": "p",
            "area_corte_m2": 40.0,
            "cota_fundo_min_m": 221.0,
            "largura_corte_m": 10.0,
            "residuo_calibracao_m": 0.002,
            "alertas": ["x"],
        },
        {
            "secao": "BB",
            "prancha": "p",
            "area_corte_m2": None,
            "cota_fundo_min_m": None,
            "largura_corte_m": None,
            "residuo_calibracao_m": None,
            "alertas": [],
        },
    ]
    texto = secoes_corte.tabela(secoes)
    assert (
        "AA" in texto
        and "40.00" in texto
        and "221.00" in texto
        and "-" in texto.splitlines()[2]
    )


sem_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="tesseract não instalado"
)


@sem_tesseract
def test_ocr_le_cota_dos_rotulos_e_titulo(tmp_path):
    pytest.importorskip("pytesseract")
    contorno = [((3, 221), (13, 221))]
    caminho = _pdf(tmp_path / "ocr.pdf", contorno_m=contorno, rotulos=True)
    (secao,) = secoes_corte.ler_secoes(
        caminho
    )  # sem cota informada: vem dos rótulos por OCR
    assert secao["secao"] == "AA"
    assert secao["area_corte_m2"] == pytest.approx(40.0, abs=1e-6)
    assert secao["cota_fundo_min_m"] == pytest.approx(221.0, abs=1e-6)


def test_alertas_sem_corte_e_borda(tmp_path):
    # fundo acima do terreno: área zero e alerta; contorno até a borda direita (25 m): alerta de borda
    (secao,) = _ler(_pdf(tmp_path / "l.pdf", contorno_m=[((3, 226), (25, 226))]))
    assert secao["area_corte_m2"] == 0.0
    assert any("sem corte" in a for a in secao["alertas"]) and any(
        "borda" in a for a in secao["alertas"]
    )
