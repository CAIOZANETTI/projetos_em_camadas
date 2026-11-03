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
    assert it[0] == {"n": "01", "codigo": "306106", "descricao": "TUBO FD DN600", "qtde": "01", "q1": None, "q2": None, "un": "pç",
                     "bloco": "BLOCO A"}
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


def _planta_sintetica(rng):
    """Planta irregular (paredes, tubos) em pt: várias peças retas de tamanhos distintos — sem simetria."""
    linhas = [np.array([[0, 0], [300, 0], [300, 120], [180, 120], [180, 200], [0, 200], [0, 0]], float),
              np.array([[40, 30], [40, 170]], float), np.array([[90, 60], [260, 60]], float),
              np.array([[220, 150], [280, 150], [280, 190]], float)]
    linhas += [np.array([p, p + rng.uniform(-30, 30, 2)]) for p in rng.uniform(10, 290, (25, 2)) * [1, 0.65]]
    return linhas


def test_encaixe_de_vista_com_escala_propria():
    rng = np.random.default_rng(3)
    vista = _planta_sintetica(rng)
    s = 0.3528e-3 * 100
    A = s * np.array([[0.0, -1.0], [-1.0, 0.0]])                  # vista girada 90° na folha (y do PDF desce)
    ref = [q @ A.T + [745100.0, 7182900.0] for q in vista]
    ref += [p + np.array([[0, 0], [6, 0]]) for p in rng.uniform([745085, 7182885], [745115, 7182915], (40, 2))]   # vizinhança
    r = prancha.registrar_vista(vista, 100, ref)
    assert r["ok"], r["motivo"]
    assert np.allclose(geo_aplicar(r["M"], vista[0]), ref[0], atol=0.25)
    longe = [q + [500.0, 0] for q in ref[len(vista):]]             # referência sem o desenho da vista
    assert not prancha.registrar_vista(vista, 100, longe)["ok"]


def test_desenho_sem_hachura_mantem_o_texto():
    hach = [{"layer": "5", "partes": [np.array([[x, 0.0], [x + 40, 40]]) for x in range(0, 100, 6)], "preenchimento": None}]
    letra = [{"layer": "5", "partes": [np.array([[50, 15.0], [50, 25], [54, 25]])], "preenchimento": None}]
    img = prancha.desenho_sem_hachura(hach + letra, (0, 0, 140, 40), 4)
    assert (img[60:100, 198:202] < 128).any()                      # o traço curto (letra) ficou
    assert (img < 128).sum() < 400                                 # a hachura saiu


def test_pilares_na_folha():
    pymupdf = pytest.importorskip("pymupdf")
    from shapely.geometry import box
    doc = pymupdf.open()
    pg = doc.new_page(width=400, height=300)
    for x0 in (50, 220):
        pg.draw_rect(pymupdf.Rect(x0, 50, x0 + 110, 160))          # bloco
    pg.draw_rect(pymupdf.Rect(93.6, 93.6, 116.4, 116.4), fill=(0, 0, 0))   # pilar 40 cm a 1:50 (22,7 pt) no 1º bloco
    pg.draw_rect(pymupdf.Rect(300, 220, 360, 280), fill=(0, 0, 0))         # mancha grande fora dos blocos
    p = prancha.pilares(pg, [box(50, 50, 160, 160), box(220, 50, 330, 160)], 50)
    assert len(p) == 1 and p[0]["bloco"] == 0 and p[0]["lado_m"] == pytest.approx(0.40, abs=0.03)


def test_resumo_do_lote():
    f = {"identidade": {"obra": "localizada"}, "vistas": 3, "escalas": [100], "tabelas": 1, "baloes": 12,
         "objetos": ["tubo", "valvula"], "tracos": 1000, "genericos": 600, "completa": {"itens": 5}}
    r = prancha.resumo_lote(f)
    assert r["objetos"] == ["Tubulação", "Válvula / registro / ventosa / descarga"] and r["genericos_pct"] == 60
    assert prancha.resumo_lote({"erro": "x"}) == {"erro": "x"} and prancha.resumo_lote(None) is None


def test_cabecalho_separado_e_quantidade_por_etapa():
    """Folha 009 de Foz: o cabeçalho é uma grade à parte (linha dupla) e a quantidade vem em 1ª e 2ª etapa."""
    g = prancha._empilhar([{"caixa": [1866, 136, 2345, 180], "linhas": 2}, {"caixa": [1867, 190, 2345, 693], "linhas": 40},
                           {"caixa": [100, 100, 400, 300], "linhas": 5}])
    assert [t["caixa"] for t in g] == [[100, 100, 400, 300], [1866, 136, 2345, 693]] and g[1]["linhas"] == 42
    linhas = [["INTERLIGAÇÕES / ADUTORA ÁGUA BRUTA"], ["Nº", "ESPECIF/ COD SAM", "DESCRIÇÃO", "4a ETAPA", "2a ETAPA", "UN"],
              ["02", "306859", "TUBO FD K-9 PP (6,8M) DN1000", "00", "1,00", "m"]]
    it = prancha.itens_da_tabela(linhas)
    assert it == [{"n": "02", "codigo": "306859", "descricao": "TUBO FD K-9 PP (6,8M) DN1000", "qtde": "1ª 00 · 2ª 1,00",
                   "q1": "00", "q2": "1,00", "un": "m", "bloco": "INTERLIGAÇÕES / ADUTORA ÁGUA BRUTA"}]


def test_layer_do_numero_do_balao(monkeypatch):
    """Sem `layer_numero`, vale o layer com mais traços dentro dos círculos — o do próprio balão incluído (folha
    053 de Foz) — e o desenho que cruza o balão fica de fora."""
    monkeypatch.setattr(prancha, "ler_numero", lambda dentro, validos=None: str(len(dentro)))
    a = np.linspace(0, 2 * np.pi, 17)
    circulo = np.c_[50 + 5 * np.cos(a), 50 + 5 * np.sin(a)]
    digito = [np.array([[49.0, 48.0], [49.0, 52.0]]), np.array([[51.0, 48.0], [51.0, 52.0]])]
    tubo = np.array([[30.0, 49.0], [70.0, 49.0]])                      # desenho atrás do balão: longo, fica de fora
    tracos = [{"layer": "BALAO", "partes": [circulo, *digito, np.array([[55.0, 50.0], [80.0, 60.0]])]},
              {"layer": "TUBO", "partes": [tubo, np.array([[90.0, 90.0], [91.0, 91.0]])]}]
    b = prancha.baloes(tracos, "BALAO")
    assert len(b) == 1 and b[0]["n"] == "2" and b[0]["ponta_pt"] == [80.0, 60.0]
    texto = {"layer": "TEXTO", "partes": [np.array([[48.0, 49.0], [48.5, 51.0]]) for _ in range(3)]}
    assert prancha.baloes([*tracos, texto], "BALAO")[0]["n"] == "3"


def test_o_que_entra_no_lote():
    import json
    regras = json.loads((prancha.pdf_cad.CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))
    sim = ["004-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYOUTPROCES-R5.pdf", "SAA-0000-4087-ESTR-DE-BLANCORAGEMTIPO18-018-R0.PDF",
           "SAA-0017-8764-PMEC-FX-0001ETAVILACSISTPNEU01-R0.pdf", "PLANTA_GERAL_SONDAGEM_FOZ_IGUAÇU_01.pdf"]
    nao = ["001-SAA-0017-8764-PBEA-LC-01ETAVILACLISTACA-R0.pdf", "Anexo_A_Termo_de_Referencia_SAA_de_Foz_do_Iguacu.pdf",
           "LISTA_VALVULAS_ETA_VILA_C_.pdf", "Descritivo Tecnico - Obra Civil_ETA_VilaC.pdf"]
    assert [prancha.e_desenho(n, regras) for n in sim + nao] == [True] * 4 + [False] * 4


def test_relacao_na_folha_irma(monkeypatch):
    """Folha sem relação (015) liga seus balões aos itens que a irmã (019) lista sem balão; número fora disso fica
    sem item; família diferente não entra."""
    monkeypatch.setattr(prancha.pdf_cad, "extrair", lambda p: [])
    monkeypatch.setattr(prancha, "_pagina", lambda p: None)
    monkeypatch.setattr(prancha, "palavras", lambda pg: [])
    monkeypatch.setattr(prancha, "baloes", lambda tr, lay, layer_numero=None, validos=None, textos=():
                        [{"n": "80"}, {"n": "84"}, {"n": "84"}, {"n": "34"}])
    comp = lambda itens, sem: {"completa": {"itens": itens, "baloes_com_item": 0, "itens_sem_balao": sem},
                               "layer_balao": "B"}
    cache = {"a/019-SAA-0017-7471-PBHI-DE-0001ETAVILACTRATAM600LS-R1.pdf": {"ficha": comp(54, ["80", "81", "84"])},
             "a/015-SAA-0017-7471-PBHI-DE-0001ETAVILACTRATAM600LS-R2.pdf": {"ficha": comp(0, [])},
             "a/011-SAA-0017-7471-PBHI-DE-0001ETAVILACTRATAM360LS-R1.pdf": {"ficha": comp(0, [])}}
    assert prancha._relacao_da_familia(cache, list(cache), log=lambda *a: None)
    f015 = cache["a/015-SAA-0017-7471-PBHI-DE-0001ETAVILACTRATAM600LS-R2.pdf"]["ficha"]["completa"]
    assert f015["baloes_com_item"] == 3 and f015["familia"]["itens"] == ["80", "84"]
    assert f015["familia"]["relacao_em"] == ["019-SAA-0017-7471-PBHI-DE-0001ETAVILACTRATAM600LS-R1.pdf"]
    assert "familia" not in cache["a/011-SAA-0017-7471-PBHI-DE-0001ETAVILACTRATAM360LS-R1.pdf"]["ficha"]["completa"]
    assert not prancha._relacao_da_familia(cache, list(cache), log=lambda *a: None)      # nada novo: não refaz


def test_relacao_com_discriminacao_e_codigo_sem_coluna():
    """Folha 042A: cabeçalho 'Nº · DISCRIMINAÇÃO · QUANT. · UND.' e o código SAM numa coluna sem título."""
    linhas = [["RELAÇÃO DE MATERIAIS"], ["Nº", "DISCRIMINAÇÃO", "QUANT.", "UND."],
              ["03", "13609", "TE FD FFF PN10 DN300", "01", "Pç"], ["“4", "10251", "REDUCAO FD FF DN300 DN250", "01", "PÇ"],
              ["10", "314465 308608", "TUBO ESPECIAL + FLANGE", "01", "PÇ"]]
    it = prancha.itens_da_tabela(linhas)
    assert [(i["n"], i["codigo"], i["qtde"], i["un"]) for i in it] == [("03", "13609", "01", "Pç"), ("04", "10251", "01", "PÇ"),
                                                                       ("10", "314465", "01", "PÇ")]
    assert it[0]["descricao"] == "TE FD FFF PN10 DN300"


def test_numero_do_item_sem_titulo_lido():
    linhas = [["", "", "ESPECIF/ COD SAM", "DESCRIÇÃO", "QTDE", "UN"],
              ["", "01", "309244", "TUBO POLIETILENO PE 100 PN 10 DE 630", "540,00", "m"]]
    assert [(i["n"], i["codigo"], i["qtde"]) for i in prancha.itens_da_tabela(linhas)] == [("01", "309244", "540,00")]


def test_numero_do_balao_em_fonte():
    """Sistema pneumático (PMEC): o número do balão é texto de fonte, não traço."""
    a = np.linspace(0, 2 * np.pi, 17)
    tracos = [{"layer": "BALAO", "partes": [np.c_[50 + 4.5 * np.cos(a), 50 + 4.5 * np.sin(a)]]}]
    textos = [(50.3, 49.9, "3"), (120.0, 40.0, "07")]
    assert prancha.baloes(tracos, "BALAO", textos=textos)[0]["n"] == "03"
    assert prancha.baloes(tracos, "BALAO", textos=textos, validos={"01"})[0]["n"] is None


def test_escala_em_fonte_acima_da_vista():
    """Contenção de Foz: o título ("… ESC 1:50") é texto de fonte e fica acima da vista; abaixo vale primeiro."""
    pytest.importorskip("pymupdf")
    class Pagina:
        rect = type("R", (), {"height": 1000.0})()
    textos = [(130.0, 122.0, "ESC"), (150.0, 122.0, "1:50"), (900.0, 122.0, "ESC"), (920.0, 122.0, "1:20")]
    assert prancha.escala_do_titulo(Pagina(), [100, 150, 500, 400], tracos=[], textos=textos) == 50
    abaixo = [*textos, (200.0, 420.0, "ESCALA"), (240.0, 420.0, "1:100")]
    assert prancha.escala_do_titulo(Pagina(), [100, 150, 500, 400], tracos=[], textos=abaixo) == 100
    assert prancha.escala_do_titulo(Pagina(), [100, 500, 500, 700], tracos=[], textos=textos) is None


def test_folha_sem_blocos_nao_quebra():
    """ETL01 (reforma do edifício do lodo): estacas sem bloco novo — rótulos e pilares vazios, sem IndexError."""
    assert prancha.rotulos(None, []) == [] and prancha.pilares(None, [], 50) == []


def test_ficha_de_estrutura_sem_ancoras_e_pulada_com_motivo(tmp_path):
    """Sem o CSV de âncoras (estacas.csv) a ficha de estrutura não é lida, mas o build segue (build real de Foz)."""
    pdf = tmp_path / "forma.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    cfg = {"fichas": [{"id": "forma", "piloto": "estrutura", "pdf": str(pdf),
                       "ancoras": str(tmp_path / "estacas.csv")}]}
    mensagens = []
    assert prancha.etapa(cfg, [], None, tmp_path, log=mensagens.append) == []
    assert any("forma" in m and "estacas.csv" in m for m in mensagens)
