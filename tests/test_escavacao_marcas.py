"""Ligação marca ↔ base da escavação (A4): o fundo de cada base pela sua marca, não pela vizinha."""
import importlib.util
import shutil

import numpy as np
import pytest
from shapely.geometry import box

from camadas import escavacao

precisa_rasterio = pytest.mark.skipif(importlib.util.find_spec("rasterio") is None, reason="rasterio não instalado")
precisa_ocr = pytest.mark.skipif(
    importlib.util.find_spec("pymupdf") is None or importlib.util.find_spec("pytesseract") is None
    or shutil.which("tesseract") is None, reason="pymupdf, pytesseract ou tesseract não instalado")

BASE = {"geom": box(45, 45, 55, 55), "etapa": "2ª etapa"}


def _marca(e, n, cota, **extra):
    return {"utm": [e, n], "cota": cota, "topo": False, **extra}


def _grade(terreno=10.0, n=400, res=0.25):
    return {"e0": 0.0, "n1": n * res, "res": res, "forma": (n, n), "epsg": 31981,
            "terreno": np.full((n, n), terreno, np.float32), "valido": np.ones((n, n), bool),
            "edificacao": np.zeros((n, n), bool)}


def _ligacao(simbolos, escritas=None, base=BASE):
    return escavacao.ligar_marcas([base], simbolos, escritas)[0]


def test_marca_interna_vale_mesmo_com_vizinha_mais_perto_da_borda():
    lig = _ligacao([_marca(47, 50, 8.0), _marca(55.3, 50, 9.0)])
    assert lig["origem"] == "marca_interna" and lig["cotas"].tolist() == [8.0] and lig["alerta"] is None


def test_sem_marca_interna_vale_a_cota_escrita_e_nao_a_vizinha():
    lig = _ligacao([_marca(55.5, 50, 9.5)], [_marca(56, 50, 8.5, escrita=True)])
    assert lig["origem"] == "cota_escrita" and lig["cotas"].tolist() == [8.5]
    assert lig["dist_m"] == pytest.approx(1.0) and lig["alerta"] is None


def test_varias_escritas_perto_valem_a_mais_baixa_e_a_de_longe_fica_de_fora():
    escritas = [_marca(56, 50, 9.0), _marca(56.5, 52, 8.0), _marca(60, 50, 7.0)]      # a última está a 5 m
    lig = _ligacao([], escritas)
    assert lig["origem"] == "cota_escrita" and lig["cotas"].tolist() == [8.0]
    assert _ligacao([_marca(60, 50, 9.0)], [_marca(60, 50, 7.0)])["origem"] == "sem_marca"


def test_so_com_vizinha_vale_a_mais_perto_e_gera_alerta():
    lig = _ligacao([_marca(55.5, 50, 9.0), _marca(57.5, 50, 7.0)])
    assert lig["origem"] == "marca_vizinha" and lig["cotas"].tolist() == [9.0]
    assert lig["dist_m"] == pytest.approx(0.5) and lig["alerta"] == "fundo pela marca vizinha a 0,5 m"


def test_sem_marca_alguma_a_base_fica_sem_marca():
    lig = _ligacao([_marca(80, 50, 9.0)])
    assert lig["origem"] == "sem_marca" and lig["cotas"].size == 0 and lig["dist_m"] is None


def test_duas_marcas_internas_ficam_so_com_as_suas():
    lig = _ligacao([_marca(47, 50, 8.0), _marca(53, 50, 9.0), _marca(55.2, 50, 7.0)])
    assert lig["origem"] == "marca_interna" and sorted(lig["cotas"].tolist()) == [8.0, 9.0]


def test_cota_escrita_que_repete_a_de_uma_marca_vizinha_e_do_simbolo():
    """O número repetido ao lado do símbolo é o rótulo da estrutura dele: não vira fundo da base encostada."""
    outra = {"geom": box(56, 45, 60, 55), "etapa": "2ª etapa"}
    simbolo = _marca(57, 50, 8.0)                                    # dentro da outra base
    repetida = _marca(55.5, 50, 8.0, escrita=True)                   # a 0,5 m de BASE e a 1,5 m do símbolo, mesma cota
    ligadas = escavacao.ligar_marcas([BASE, outra], [simbolo], [repetida])
    assert ligadas[0]["origem"] == "marca_vizinha" and ligadas[1]["origem"] == "marca_interna"
    outra_cota = escavacao.ligar_marcas([BASE, outra], [simbolo], [_marca(55.5, 50, 7.0, escrita=True)])
    assert outra_cota[0]["origem"] == "cota_escrita"                 # cota diferente da do símbolo: é de BASE


@precisa_rasterio
def test_fundo_na_grade_faz_degrau_so_entre_as_marcas_da_propria_base():
    g = _grade()
    ligadas = escavacao.ligar_marcas([BASE], [_marca(47, 50, 8.0), _marca(53, 50, 9.0), _marca(55.4, 50, 7.0)])
    fundo = escavacao.fundo_na_grade(ligadas, g["e0"], g["n1"], g["res"], g["forma"])
    lin, col_esq, col_dir = int((g["n1"] - 50) / g["res"]), int(46 / g["res"]), int(54 / g["res"])
    assert fundo[lin, col_esq] == 8.0 and fundo[lin, col_dir] == 9.0
    assert np.nanmin(fundo) == 8.0 and np.nanmax(fundo) == 9.0       # a vizinha de 7,0 m não entra


@precisa_rasterio
def test_calcular_com_marca_interna_ignora_a_vizinha_mais_perto_da_borda():
    r = escavacao.calcular([BASE], [_marca(47, 50, 8.0), _marca(55.3, 50, 9.0)], [], _grade())
    assert r["cavas"][0]["fundo_m"] == [8.0, 8.0] and r["origem_fundo"]["marca_interna"] == 1
    assert r["alertas_fundo"] == [] and r["bases_fundo"][0]["origem"] == "marca_interna"


@precisa_rasterio
def test_calcular_com_cota_escrita_usa_a_escrita_e_conta_na_resumo_das_marcas():
    ms = [_marca(55.5, 50, 9.5), _marca(56, 50, 8.5, escrita=True)]
    r = escavacao.calcular([BASE], ms, [], _grade())
    assert r["cavas"][0]["fundo_m"] == [8.5, 8.5] and r["origem_fundo"]["cota_escrita"] == 1
    assert r["marcas"]["cotas_escritas"] == 1 and r["marcas"]["total"] == 1      # a escrita não conta como símbolo


@precisa_rasterio
def test_calcular_so_com_vizinha_usa_a_vizinha_e_alerta():
    r = escavacao.calcular([BASE], [_marca(56, 50, 9.0)], [], _grade())
    assert r["cavas"][0]["fundo_m"] == [9.0, 9.0] and r["origem_fundo"]["marca_vizinha"] == 1
    assert len(r["alertas_fundo"]) == 1 and "fundo pela marca vizinha a 1,0 m" in r["alertas_fundo"][0]
    assert "marca vizinha" in escavacao._alertas_das_cavas(r)[0]


@precisa_rasterio
def test_calcular_com_duas_marcas_internas_faz_degrau_na_cava():
    r = escavacao.calcular([BASE], [_marca(47, 50, 8.0), _marca(53, 50, 9.0), _marca(56, 50, 7.0)], [], _grade())
    assert r["cavas"][0]["fundo_m"] == [8.0, 9.0] and r["bases_fundo"][0]["cota_m"] == [8.0, 9.0]


def test_cota_escrita_das_gavetas_volta_a_ser_escrita_pelo_texto():
    marcas_cota = [{"E": 56.0, "N": 50.0, "cota_m": 8.5, "texto": "8,50" + escavacao.SUFIXO_ESCRITA},
                   {"E": 47.0, "N": 50.0, "cota_m": 8.0, "texto": "8,00"}]
    ms = escavacao._marcas_da_gaveta(marcas_cota)
    assert [m["escrita"] for m in ms] == [True, False]
    simbolos, escritas = escavacao._separar_escritas(ms)
    assert [m["cota"] for m in simbolos] == [8.0] and [m["cota"] for m in escritas] == [8.5]


def _glifos_de_rotulo(x0, y0, n=6):
    """n glifos de 3 × 6 pt em fila (um rótulo de cota desenhado em traço), com passo de 5 pt."""
    return [np.array([[x0 + 5 * k, y0], [x0 + 5 * k + 3, y0], [x0 + 5 * k + 3, y0 + 6], [x0 + 5 * k, y0 + 6]], float)
            for k in range(n)]


@precisa_ocr
def test_cotas_escritas_le_o_rotulo_perto_da_base_e_pula_o_do_simbolo_e_o_de_longe(tmp_path):
    import pymupdf
    doc = pymupdf.open()
    pg = doc.new_page(width=400, height=300)
    pg.insert_text((136, 103), "235,35", fontsize=9)                  # rótulo a (150, 100) pt
    pg.insert_text((236, 103), "236,00", fontsize=9)                  # rótulo longe de qualquer base
    M = np.array([[0.05, 0, 100.0], [0, -0.05, 200.0], [0, 0, 1.0]])    # pt -> UTM: (150, 100) -> (107,5; 195,0)
    tracos = [{"layer": "TEXTO", "partes": _glifos_de_rotulo(137, 97) + _glifos_de_rotulo(237, 97)}]
    base = [{"geom": box(100, 190, 107, 200), "etapa": None}]          # o rótulo fica a 0,5 m da borda
    caminho = tmp_path / "rotulos.pdf"
    doc.save(caminho)
    achadas = escavacao.cotas_escritas(caminho, tracos, M, base, [])
    assert [a["cota"] for a in achadas] == [235.35]
    assert achadas[0]["utm"] == pytest.approx([107.5, 195.0], abs=0.3)
    com_simbolo = escavacao.cotas_escritas(caminho, tracos, M, base, [{"pt": [152.0, 100.0]}])
    assert com_simbolo == []                                          # o número já é de um símbolo (a ≤ 30 pt)
