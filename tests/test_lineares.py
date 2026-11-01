"""L1: eixo e estaqueamento da obra linear (tolerância absoluta de 1 mm)."""

import shutil

import numpy as np
import pytest

from camadas import lineares

TOL_M = 0.001
# eixo em L: 100 m para leste, curva de 90 graus, 60 m para norte (sentido do estaqueamento)
EIXO_L = [[1000.0, 2000.0], [1100.0, 2000.0], [1100.0, 2060.0]]


@pytest.fixture
def eixo_l():
    return lineares.eixo(EIXO_L)


@pytest.mark.parametrize(
    "texto, esperado_m",
    [
        ("12+10,00", 250.0),
        ("12+10.00", 250.0),
        ("12+10", 250.0),
        ("12", 240.0),
        ("E12+10,00", 250.0),
        ("EST. 12 + 10,00", 250.0),
        ("0+00,00", 0.0),
        ("3+5,5", 65.5),
    ],
)
def test_estaca_para_progressiva(texto, esperado_m):
    np.testing.assert_allclose(
        lineares.estaca_para_progressiva(texto), esperado_m, atol=TOL_M
    )


@pytest.mark.parametrize("texto", ["12+10,00", "0+00,00", "7+19,99", "100+05,50"])
def test_ida_e_volta_estaca(texto):
    assert (
        lineares.progressiva_para_estaca(lineares.estaca_para_progressiva(texto))
        == texto
    )


def test_estaca_com_arredondamento_e_passo():
    assert lineares.progressiva_para_estaca(39.999) == "2+00,00"
    assert lineares.progressiva_para_estaca(250.0, passo_m=10.0) == "25+00,00"
    assert lineares.estaca_para_progressiva("2+5", passo_m=10.0) == 25.0


def test_eixo_acumula_progressiva_e_remove_repetidos():
    eixo = lineares.eixo([[0, 0], [0, 0], [30, 40], [30, 40], [30, 90]])
    np.testing.assert_allclose(eixo["progressiva_m"], [0, 50, 100], atol=TOL_M)
    assert len(eixo["pontos_m"]) == 3
    np.testing.assert_allclose(eixo["comprimento_m"], 100.0, atol=TOL_M)


def test_ponto_em_no_meio_dos_segmentos_e_no_vertice(eixo_l):
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, 50.0), [1050.0, 2000.0], atol=TOL_M
    )
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, 100.0), [1100.0, 2000.0], atol=TOL_M
    )
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, 130.0), [1100.0, 2030.0], atol=TOL_M
    )
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, [0.0, 160.0]),
        [[1000, 2000], [1100, 2060]],
        atol=TOL_M,
    )


def test_progressiva_de_esquerda_e_direita(eixo_l):
    esq = lineares.progressiva_de(eixo_l, 1050.0, 2003.0)
    assert esq["lado"] == "esquerdo"
    np.testing.assert_allclose(
        [esq["progressiva_m"], esq["afastamento_m"]], [50.0, 3.0], atol=TOL_M
    )
    dire = lineares.progressiva_de(eixo_l, 1050.0, 1996.0)
    assert dire["lado"] == "direito"
    np.testing.assert_allclose(
        [dire["progressiva_m"], dire["afastamento_m"]], [50.0, 4.0], atol=TOL_M
    )
    # no segundo segmento (rumo norte) a esquerda é o oeste
    seg2 = lineares.progressiva_de(eixo_l, 1095.0, 2030.0)
    assert seg2["lado"] == "esquerdo"
    np.testing.assert_allclose(
        [seg2["progressiva_m"], seg2["afastamento_m"]], [130.0, 5.0], atol=TOL_M
    )


def test_progressiva_de_vetorizado(eixo_l):
    res = lineares.progressiva_de(
        eixo_l, np.array([1050.0, 1105.0]), np.array([2003.0, 2030.0])
    )
    np.testing.assert_allclose(res["progressiva_m"], [50.0, 130.0], atol=TOL_M)
    np.testing.assert_allclose(res["afastamento_m"], [3.0, 5.0], atol=TOL_M)
    assert list(res["lado"]) == ["esquerdo", "direito"]


def test_progressiva_de_fora_da_ponta_fica_na_ponta(eixo_l):
    res = lineares.progressiva_de(eixo_l, 990.0, 2000.0)
    np.testing.assert_allclose(
        [res["progressiva_m"], res["afastamento_m"]], [0.0, 10.0], atol=TOL_M
    )


def test_ida_e_volta_ponto_progressiva_ponto(eixo_l):
    progressivas_m = np.array([0.0, 12.5, 100.0, 133.3, 160.0])
    pontos = lineares.ponto_em(eixo_l, progressivas_m)
    res = lineares.progressiva_de(eixo_l, pontos[:, 0], pontos[:, 1])
    np.testing.assert_allclose(res["progressiva_m"], progressivas_m, atol=TOL_M)
    np.testing.assert_allclose(res["afastamento_m"], 0.0, atol=TOL_M)
    np.testing.assert_allclose(
        lineares.ponto_em(eixo_l, res["progressiva_m"]), pontos, atol=TOL_M
    )


def test_segmento_tem_comprimento_p1_menos_p0(eixo_l):
    trecho = lineares.segmento(eixo_l, 70.0, 140.0)
    np.testing.assert_allclose(
        trecho, [[1070, 2000], [1100, 2000], [1100, 2040]], atol=TOL_M
    )
    comprimento_m = np.linalg.norm(np.diff(trecho, axis=0), axis=1).sum()
    np.testing.assert_allclose(comprimento_m, 70.0, atol=TOL_M)


def test_erros_em_portugues(eixo_l):
    with pytest.raises(ValueError, match="2 pontos distintos"):
        lineares.eixo([[0, 0]])
    with pytest.raises(ValueError, match="2 pontos distintos"):
        lineares.eixo([[5, 5], [5, 5]])
    with pytest.raises(ValueError, match="estaca não reconhecida"):
        lineares.estaca_para_progressiva("abc")
    with pytest.raises(ValueError, match="fora do eixo"):
        lineares.ponto_em(eixo_l, 160.5)
    with pytest.raises(ValueError, match="fora do eixo"):
        lineares.ponto_em(eixo_l, -1.0)
    with pytest.raises(ValueError, match="maior que a inicial"):
        lineares.segmento(eixo_l, 50.0, 50.0)


def test_metadados():
    meta = lineares.metadados()
    assert meta["modulo"] == "lineares"
    assert all(p["estado"] == "premissa" for p in meta["premissas"])


# ---------------------------------------------------------------- L2: leitor do perfil

ESTACAS = ["0+00,00", "1+00,00", "2+00,00", "2+10,50", "4+00,00"]
TERRENO = ["745,20", "744,80", "743,10", "742,95", "741,00"]
GERATRIZ = ["743,90", "743,40", "741,60", "741,40", "739,50"]
PROFUNDIDADE = ["1,50", "1,60", "1,60", "1,65", "1,60"]
PROGRESSIVAS_M = [0.0, 20.0, 40.0, 50.5, 80.0]


def _berco_m() -> float:
    from camadas import valas

    return float(valas.VALOR["berco_m"])


def _pdf_perfil(caminho, linhas, tamanho_pt=9, so_imagem=False):
    """PDF sintético: rótulos à esquerda e, na coluna de cada estaca, o valor centrado (None = célula vazia)."""
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    pagina = doc.new_page(width=842, height=595)
    pagina.draw_line((30, 380), (800, 380))
    for k, (rotulo, valores) in enumerate(linhas):
        y = 400 + 22 * k
        pagina.insert_text((30, y), rotulo, fontsize=tamanho_pt, fontname="helv")
        for i, valor in enumerate(valores):
            if valor is None:
                continue
            largura = pymupdf.get_text_length(valor, "helv", tamanho_pt)
            pagina.insert_text(
                (230 + 110 * i - largura / 2, y),
                valor,
                fontsize=tamanho_pt,
                fontname="helv",
            )
    if so_imagem:
        imagem = pagina.get_pixmap(dpi=200)
        doc = pymupdf.open()
        nova = doc.new_page(width=842, height=595)
        nova.insert_image(nova.rect, pixmap=imagem)
    doc.save(caminho)
    doc.close()
    return caminho


def test_ler_perfil_texto_calcula_profundidade(tmp_path):
    pdf = _pdf_perfil(
        tmp_path / "perfil.pdf",
        [
            ("ESTACA", ESTACAS),
            ("COTA DO TERRENO", TERRENO),
            ("COTA DA GERATRIZ INFERIOR", GERATRIZ),
        ],
    )
    perfil = lineares.ler_perfil(pdf)
    assert perfil["fonte"] == "texto do PDF"
    assert perfil["nao_lidos"] == []
    assert len(perfil["pontos"]) == 5
    for ponto, estaca, terr, ger, prog in zip(
        perfil["pontos"], ESTACAS, TERRENO, GERATRIZ, PROGRESSIVAS_M
    ):
        terreno_m = float(terr.replace(",", "."))
        geratriz_m = float(ger.replace(",", "."))
        assert ponto["estaca"] == estaca
        np.testing.assert_allclose(ponto["progressiva_m"], prog, atol=TOL_M)
        np.testing.assert_allclose(ponto["cota_terreno_m"], terreno_m, atol=TOL_M)
        np.testing.assert_allclose(ponto["cota_geratriz_m"], geratriz_m, atol=TOL_M)
        np.testing.assert_allclose(
            ponto["profundidade_m"], terreno_m - geratriz_m + _berco_m(), atol=TOL_M
        )
        assert ponto["fonte_profundidade"] == "terreno − geratriz + berço"


def test_ler_perfil_usa_profundidade_escrita(tmp_path):
    pdf = _pdf_perfil(
        tmp_path / "perfil.pdf",
        [
            ("ESTAQUEAMENTO", ESTACAS),
            ("TERRENO", TERRENO),
            ("GERATRIZ INFERIOR", GERATRIZ),
            ("PROFUNDIDADE", PROFUNDIDADE),
        ],
    )
    perfil = lineares.ler_perfil(pdf)
    assert len(perfil["pontos"]) == 5
    for ponto, escrita in zip(perfil["pontos"], PROFUNDIDADE):
        np.testing.assert_allclose(
            ponto["profundidade_m"], float(escrita.replace(",", ".")), atol=TOL_M
        )
        assert ponto["fonte_profundidade"] == "escrita no perfil"


def test_ler_perfil_sem_geratriz(tmp_path):
    pdf = _pdf_perfil(
        tmp_path / "perfil.pdf", [("ESTACA", ESTACAS), ("COTA DO TERRENO", TERRENO)]
    )
    perfil = lineares.ler_perfil(pdf)
    assert perfil["pontos"] == []
    assert len(perfil["nao_lidos"]) == 1
    assert "geratriz" in perfil["nao_lidos"][0]["motivo"]


def test_ler_perfil_geratriz_superior_nao_vale(tmp_path):
    pdf = _pdf_perfil(
        tmp_path / "perfil.pdf",
        [
            ("ESTACA", ESTACAS),
            ("COTA DO TERRENO", TERRENO),
            ("GERATRIZ SUPERIOR", GERATRIZ),
        ],
    )
    perfil = lineares.ler_perfil(pdf)
    assert perfil["pontos"] == []
    assert "geratriz" in perfil["nao_lidos"][0]["motivo"]


def test_ler_perfil_coluna_com_valor_faltando(tmp_path):
    geratriz = list(GERATRIZ)
    geratriz[2] = None
    pdf = _pdf_perfil(
        tmp_path / "perfil.pdf",
        [("ESTACA", ESTACAS), ("COTA DO TERRENO", TERRENO), ("COTA DO TUBO", geratriz)],
    )
    perfil = lineares.ler_perfil(pdf)
    assert [p["estaca"] for p in perfil["pontos"]] == [
        e for i, e in enumerate(ESTACAS) if i != 2
    ]
    assert len(perfil["nao_lidos"]) == 1
    assert perfil["nao_lidos"][0]["estaca"] == ESTACAS[2]
    assert "geratriz" in perfil["nao_lidos"][0]["motivo"]


def test_ler_perfil_progressiva_fora_de_ordem(tmp_path):
    estacas = list(ESTACAS)
    estacas[3] = "1+10,00"  # 30 m, depois da estaca 2+00 (40 m)
    pdf = _pdf_perfil(
        tmp_path / "perfil.pdf",
        [
            ("ESTACA", estacas),
            ("COTA DO TERRENO", TERRENO),
            ("COTA DO FUNDO", GERATRIZ),
        ],
    )
    perfil = lineares.ler_perfil(pdf)
    assert [p["estaca"] for p in perfil["pontos"]] == [
        "0+00,00",
        "1+00,00",
        "2+00,00",
        "4+00,00",
    ]
    assert perfil["nao_lidos"][0]["estaca"] == "1+10,00"
    assert "fora de ordem" in perfil["nao_lidos"][0]["motivo"]


@pytest.mark.parametrize(
    "texto, esperado",
    [("745,20", 745.2), ("1.234,56", 1234.56), ("745.20", 745.2), ("1.234", 1234.0)],
)
def test_numero_brasileiro(texto, esperado):
    np.testing.assert_allclose(lineares.numero_brasileiro(texto), esperado, atol=TOL_M)
    with pytest.raises(ValueError, match="número não reconhecido"):
        lineares.numero_brasileiro("abc")


def test_ler_perfil_ocr(tmp_path):
    pytest.importorskip("pytesseract")
    if shutil.which("tesseract") is None:
        pytest.skip("binário do tesseract ausente")
    pdf = _pdf_perfil(
        tmp_path / "perfil_imagem.pdf",
        [
            ("ESTACA", ESTACAS),
            ("COTA DO TERRENO", TERRENO),
            ("COTA DA GERATRIZ INFERIOR", GERATRIZ),
        ],
        tamanho_pt=14,
        so_imagem=True,
    )
    perfil = lineares.ler_perfil(pdf)
    assert perfil["fonte"] == "OCR"
    assert (
        len(perfil["pontos"]) >= 3
    )  # o OCR pode errar uma célula; o que sai tem que ser coerente
    for ponto in perfil["pontos"]:
        i = ESTACAS.index(ponto["estaca"])
        np.testing.assert_allclose(
            ponto["profundidade_m"],
            float(TERRENO[i].replace(",", "."))
            - float(GERATRIZ[i].replace(",", "."))
            + _berco_m(),
            atol=TOL_M,
        )
