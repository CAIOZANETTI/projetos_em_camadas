import itertools
import shutil

import numpy as np
import pytest

from camadas import pdf_cad, prancha


def _circulo_tracejado(c, r, n=24):
    """Círculo explodido em arcos curtos com vãos (como o tracejado do PDF)."""
    a = np.linspace(0, 2 * np.pi, 2 * n + 1)
    return [np.c_[c[0] + r * np.cos(a[k:k + 2]), c[1] + r * np.sin(a[k:k + 2])] for k in range(0, 2 * n, 2)]


def _retangulo(x0, y0, x1, y1):
    return np.array([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)], float)


def test_lista_de_rotulos_e_niveis():
    assert prancha.rotulos_da_lista("PC1-PC2-PC5S—PC6") == ["PC1", "PC2", "PC5", "PC6"]
    assert prancha.rotulos_da_lista("PC9 a PC11-PC16-P1 A P3") == ["PC9", "PC10", "PC11", "PC16", "P1", "P2", "P3"]
    linhas = [["NÍVEL DA FACE SUPERIOR DOS BLOCOS"], ["NÍVEL", "BLOCO PARA:"], ["237,317", "PC1-PC2"], ["235,617", "PC3 a PC4"], ["", ""]]
    n = prancha.niveis_da_tabela(linhas)
    assert n["titulo"].startswith("NÍVEL DA FACE") and n["por_rotulo"] == {"PC1": 237.317, "PC2": 237.317, "PC3": 235.617, "PC4": 235.617}


def test_itens_da_relacao_de_materiais():
    linhas = [["", "RELAÇÃO DE MATERIAIS", ""], ["", "BLOCO A", ""], ["", "Nº", "ESPECIF/ COD SAM", "DESCRIÇÃO", "QTDE", "UN"],
              ["", "01", "306106", "TUBO FD DN600", "01", "pç"], ["", "OS", "308649", "TUBO ACO", "396,3", "kg/m"],
              ["", "S/N", "91596", "ARRUELA", "06", "pç"], ["", "texto solto", "", "", "", ""]]
    it = prancha.itens_da_tabela(linhas)
    assert [i["n"] for i in it] == ["01", "05", "S/N"]                 # "OS" lido no lugar de "05"
    assert it[0] == {"n": "01", "codigo": "306106", "descricao": "TUBO FD DN600", "qtde": "01", "un": "pç", "bloco": "BLOCO A"}
    cad = {"306106": {"descricao": "TUBO FD K9 DN 600"}}
    contrato = [{"codigo": "306106", "tabela": "16", "item": "01", "q1": 1.0, "q2": 0.0, "un": "pç"}]
    c = prancha.conferir_itens(it, cad, contrato)
    assert c[0]["cadastro"] == "TUBO FD K9 DN 600" and c[0]["contrato"][0]["tabela"] == "16" and c[1]["contrato"] == []


def test_estacas_e_blocos_pela_geometria():
    """2 blocos com 4 e 2 estacas (Ø40 a 1:50 = 22,7 pt) + a moldura da folha, que também 'contém' as estacas."""
    tr = [{"layer": "4", "partes": [_retangulo(0, 0, 110, 110), _retangulo(200, 0, 240, 110), _retangulo(-500, -500, 900, 900)],
           "preenchimento": None}]
    centros = [(25, 25), (85, 25), (25, 85), (85, 85), (220, 25), (220, 85)]
    tr.append({"layer": "3", "partes": [q for c in centros for q in _circulo_tracejado(c, 11.35)], "preenchimento": None})
    g = prancha.estacas_e_blocos(tr, escala=50)
    assert len(g["estacas_pt"]) == 6 and g["layer_estacas"] == "3"
    assert np.allclose(sorted(map(tuple, g["estacas_pt"][:, :2].round(1))), sorted(centros), atol=0.2)
    assert g["layer_blocos"] == "4" and sorted(round(p.area) for p in g["blocos_pt"]) == [4400, 12100]


def test_encaixe_de_estacas_sem_correspondencia():
    rng = np.random.default_rng(1)
    P = np.array([(x, y) for x in range(0, 600, 60) for y in range(0, 300, 60)], float) + rng.normal(0, 0.2, (50, 2))
    s, th = 0.3528e-3 * 50, np.radians(90)
    R = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    U = (np.c_[P[:, 0], -P[:, 1]] * s) @ R.T + [745000.0, 7180000.0]
    U = np.vstack([U[5:], [[745010.0, 7180020.0], [744990.0, 7179990.0]]])   # 5 faltando no E/N e 2 a mais
    r = prancha.registrar_pontos(P, U, 50)
    assert r["ok"] and r["inliers"] == 45 and r["residuo_mediano_m"] < 0.02 and r["escala"] == 50
    assert np.allclose(geo_aplicar(r["M"], P[10:12]), U[5:7], atol=0.02)


def geo_aplicar(M, p):
    return (np.c_[p, np.ones(len(p))] @ np.asarray(M).T)[:, :2]


def test_glifos_escala_e_vistas():
    um, dois = np.array([[0, 0], [0, 5.0]]), np.array([[2, 0], [3, 5], [4, 0.0]])
    assert prancha.glifos([um, dois]) == 2 and prancha.glifos([dois, dois + [0.5, 0]]) == 1
    assert prancha.escala_da_afim([[0.03528, 0, 0], [0, -0.03528, 0]]) == pytest.approx(100, rel=1e-3)
    tr = [{"layer": "A", "partes": [_retangulo(100, 100, 400, 300), _retangulo(120, 120, 380, 280)]},
          {"layer": "A", "partes": [_retangulo(600, 100, 900, 300)]},
          {"layer": "CARIMBO", "partes": [_retangulo(950, 400, 1180, 580)]}]
    v = sorted(prancha.vistas(tr, 1200, 600))
    assert len(v) == 2 and v[0][0] == pytest.approx(100, abs=4) and v[1][0] == pytest.approx(600, abs=4)


def test_classe_de_elemento_pelo_layer():
    casos = {"SJMH_ADUTORA_TUBO": "tubo", "SGC-Valvulas (Linhas Externas)": "valvula", "CISM_36_BOLSAS e FLANGES": "conexao",
             "DETALHE TIRANTE - TUBO MANCHETE": "tirante", "CISM_18_BLOCO_LISTA_PEÇAS": "balao", "COTA ARMADURA": "cota",
             "INDICAÇÃO DE BLOCO": "chamada", "VIGA DE COROAMENTO": "viga", "_EXISTENTES A REESTRUTURAR": "existente",
             "CISM_04_LINHA_PROJEÇÃO": "generico", "3": "generico", "SEÇÃO GEOLÓGICA": "topografia", "_MF_": "meio_fio",
             "_GSE200_": None}
    assert {k: pdf_cad.elemento_do_layer(k) for k in casos} == casos


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract não instalado")
def test_tabela_desenhada_lida_por_ocr():
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    pg = doc.new_page(width=600, height=400)
    xs, ys = [50, 90, 170, 420, 480, 530], [50, 75, 100, 125, 150]
    for y in ys:
        pg.draw_line((xs[0], y), (xs[-1], y))
    for x in xs:
        pg.draw_line((x, ys[0]), (x, ys[-1]))
    linhas = [["Nº", "COD SAM", "DESCRIÇÃO", "QTDE", "UN"], ["01", "306106", "TUBO FD DN600", "01", "pç"],
              ["02", "307847", "REDUCAO FD DN600", "02", "pç"], ["S/N", "91596", "ARRUELA", "06", "pç"]]
    for (_, y1), lin in zip(itertools.pairwise(ys), linhas):
        for x0, txt in zip(xs[:-1], lin):
            pg.insert_text((x0 + 4, y1 - 8), txt, fontsize=9)
    g = prancha.grades(pg)
    assert len(g) == 1 and g[0]["caixa"][0] == pytest.approx(50, abs=3)
    it = prancha.itens_da_tabela(prancha.celulas(pg, g[0]["caixa"]))
    assert [(i["n"], i["codigo"]) for i in it] == [("01", "306106"), ("02", "307847"), ("S/N", "91596")]
