import json
import zipfile

import cv2
import numpy as np
import pytest

from camadas import geo, obra, pdf_cad, sig


def _kmz(caminho, marcos):
    blocos = "".join(
        f"<Placemark><name>{nome}</name><description><![CDATA[<table><tr><td>CLASSIFICAÇÃO</td><td>{classe}</td></tr>"
        f"<tr><td>OBS</td><td>&lt;Null&gt;</td></tr></table>]]></description>"
        f"<Point><coordinates> {lon},{lat},0</coordinates></Point></Placemark>" for nome, classe, lon, lat in marcos)
    with zipfile.ZipFile(caminho, "w") as z:
        z.writestr("doc.kml", f"<kml><Document>{blocos}</Document></kml>")


def test_ler_kmz_e_marcos_proximos(tmp_path):
    lon0, lat0 = geo.para_lonlat(745800.0, 7182900.0, 31981)
    perto = geo.para_lonlat(745850.0, 7182900.0, 31981)
    longe = geo.para_lonlat(749800.0, 7182900.0, 31981)
    _kmz(tmp_path / "REDE_DE_REFERENCIA_CADASTRAL_SANEPAR_FEV_2026.kmz",
         [("MRRN1", "MRRN", *perto), ("MRRN9", "MRRN", *longe)])
    marcos = sig.ler_kmz(tmp_path / "REDE_DE_REFERENCIA_CADASTRAL_SANEPAR_FEV_2026.kmz")
    assert marcos[0]["nome"] == "MRRN1" and marcos[0]["atributos"] == {"CLASSIFICAÇÃO": "MRRN", "OBS": None}
    fc = sig.marcos_proximos(tmp_path, float(lon0), float(lat0), 1000, 31981)
    assert [f["properties"]["nome"] for f in fc["features"]] == ["MRRN1"]
    assert fc["features"][0]["properties"]["distancia_m"] == pytest.approx(50, abs=0.5)
    assert fc["features"][0]["properties"]["rede"] == "Sanepar"


def test_disciplinas_por_codigo_e_por_layer():
    assert pdf_cad.disciplina_da_prancha("003-SAA-PBGE-DE-ETA01FUNDACAO1-R2.pdf") == ("Civil", "Geotecnia e fundação")
    assert pdf_cad.disciplina_da_prancha("021-PBEA-DE-ETAVILACPLATERRA-R0.pdf") == ("Elétrica e automação", "Aterramento e SPDA")
    assert pdf_cad.disciplina_da_prancha("006-PBHI-DE-ETAVILACLAYDRENAG-R2.pdf") == ("Civil", "Drenagem")
    hidraulica = ("Hidráulica", "Tubulações e conexões")
    assert pdf_cad.disciplina_do_layer("CISM_50_DRENAGEM DN400", hidraulica) == ("Civil", "Drenagem")
    assert pdf_cad.disciplina_do_layer("CARIMBO", hidraulica) == hidraulica
    grupos = pdf_cad.disciplinas()["grupos"]
    assert {"Fundação" in s or "fundação" in s for s in grupos["Civil"]} == {True, False}
    assert all(r["subgrupo"] in grupos[r["grupo"]] for r in pdf_cad.disciplinas()["layer"] + pdf_cad.disciplinas()["prancha"])


def test_regras_de_etapa_vem_do_conceito():
    regras = pdf_cad.regras("etapas_sanepar")
    assert [r["classe"] for r in regras][:3] == ["1ª etapa", "2ª etapa", "3ª etapa (futura)"]
    azul = {"layer": "_PROJETADOS", "cor": None, "preenchimento": (0.0, 0.43, 0.87)}
    roxo = {"layer": "_PROJETADOS", "cor": (0.66, 0.33, 0.63), "preenchimento": None}
    assert pdf_cad.classificar([azul, roxo], regras) == ["1ª etapa", "2ª etapa"]


def test_cronograma_resolve_elementos_e_curva_s():
    dados = {"pranchas": [{"id": "fu1", "M": [1, 0, 0, 0, -1, 0], "layers": [
                {"nome": "ESTACAS", "grupo": "Civil", "subgrupo": "Geotecnia e fundação", "classe": None},
                {"nome": "_PROJETADOS", "grupo": "Hidráulica", "subgrupo": "Tubulações e conexões", "classe": "1ª etapa"}]}],
             "vetores": [{"id": "supressao", "geojson": {"features": []}},
                         {"id": "estacas", "geojson": {"features": [{"properties": {"id": "A-1", "estrutura": "ACT360"}}]}}]}
    cfg = {"cronograma": {"data_os": "2027-01-04", "atividades": [
        {"id": "A", "nome": "fundação", "inicio_dia": 0, "fim_dia": 100, "peso_pct": 25,
         "seletor": {"grupos": [["Civil", "Geotecnia e fundação"]], "estacas": ["ACT360"]}},
        {"id": "B", "nome": "tubos 1ª etapa", "inicio_dia": 100, "fim_dia": 200, "peso_pct": 75,
         "seletor": {"etapas": ["1ª etapa"], "vetores": ["supressao"]}}]}}
    c = obra.cronograma_4d(cfg, dados)
    a, b = c["atividades"]
    assert a["elementos"]["layers"] == {"fu1": ["ESTACAS"]} and a["elementos"]["estacas"] == ["A-1"]
    assert b["elementos"]["layers"] == {"fu1": ["_PROJETADOS"]} and b["elementos"]["vetores"] == ["supressao"]
    curva = dict(zip(c["curva_s"]["dia"], c["curva_s"]["planejado_pct"]))
    assert curva[0] == 0 and curva[100] == pytest.approx(25) and curva[150] == pytest.approx(62.5) and curva[200] == 100


def _georef(caminho, e0, n1, res, extra=None):
    geo.salvar_georef(caminho, e0, n1, res, 31981, extra or {})


def test_supressao_so_dentro_da_faixa_e_so_vegetacao_alta(tmp_path):
    res, n = 0.25, 200                                   # 50 × 50 m
    img = np.full((n, n, 3), (90, 90, 90), np.uint8)    # asfalto
    img[:, 100:140] = (40, 160, 40)                     # faixa verde (árvores em parte, grama no resto)
    cv2.imwrite(str(tmp_path / "orto.jpg"), img)
    _georef(tmp_path / "orto.jpg", 1000.0, 2050.0, res)
    z = np.zeros((n, n), np.float32)
    z[:100, 100:140] = 6.0                              # copa de 6 m só na metade norte
    cv2.imwrite(str(tmp_path / "mds.png"), np.uint16(z * 100))
    _georef(tmp_path / "mds.png", 1000.0, 2050.0, res, {"z_min_m": 0.0})
    from shapely.geometry import LineString

    from camadas import supressao
    tubo = LineString([(1030.0, 2049.0), (1030.0, 2001.0)])        # passa pelo meio da faixa verde
    fc = supressao.estimar(tmp_path / "orto.jpg", tmp_path / "mds.png", {"1ª etapa": [tubo]}, faixa_m=4.0)
    r = fc["resumo"]["1ª etapa"]
    assert r["supressao_m2"] == pytest.approx(4 * 25, rel=0.15)    # 4 m de faixa × 25 m de copa
    assert r["limpeza_m2"] == pytest.approx(4 * 23, rel=0.2)       # metade sul: grama


def test_geotiff_tem_crs_e_transformacao(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    cv2.imwrite(str(tmp_path / "o.jpg"), np.full((40, 60, 3), 120, np.uint8))
    _georef(tmp_path / "o.jpg", 745700.0, 7183000.0, 0.04)
    sig.geotiff(tmp_path / "o.jpg", tmp_path / "o.tif")
    with rasterio.open(tmp_path / "o.tif") as t:
        assert t.crs.to_epsg() == 31981 and t.count == 4
        assert t.transform.c == pytest.approx(745700.0) and t.transform.a == pytest.approx(0.04)
    json.loads((tmp_path / "o.json").read_text())


def test_recortar_ortofoto_zera_o_alfa_fora_do_poligono(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    cv2.imwrite(str(tmp_path / "o.jpg"), np.full((100, 200, 3), 120, np.uint8))        # 20 × 10 m a 0,1 m/px
    _georef(tmp_path / "o.jpg", 1000.0, 2010.0, 0.1)
    sig.geotiff(tmp_path / "o.jpg", tmp_path / "o.tif")
    triangulo = [[1005.0, 2002.0], [1015.0, 2002.0], [1005.0, 2008.0], [1005.0, 2002.0]]      # meio retângulo 10 × 6 m
    saida = sig.recortar(tmp_path / "o.tif", triangulo, tmp_path / "obra" / "o_obra.tif")
    with rasterio.open(saida) as t:
        assert t.crs.to_epsg() == 31981 and t.count == 4 and (t.width, t.height) == (100, 60)
        assert t.transform.c == pytest.approx(1005.0) and t.transform.f == pytest.approx(2008.0)
        assert t.transform.a == pytest.approx(0.1) and len(t.overviews(1)) == 4
        assert t.colorinterp[3].name == "alpha"
        alfa = t.read(4)
        assert alfa[5, 5] == 255 and alfa[55, 5] == 255 and alfa[5, 95] == 0      # dentro, dentro, fora (hipotenusa)
        assert (t.read(1)[alfa == 0] == 0).all() and (t.read(1)[alfa == 255] == 120).all()


def test_recortar_mds_deixa_nodata_fora_do_poligono(tmp_path):
    rasterio = pytest.importorskip("rasterio")
    cota = np.full((100, 200), 5.0, np.float32)
    cv2.imwrite(str(tmp_path / "m.png"), np.uint16(cota * 100))
    _georef(tmp_path / "m.png", 1000.0, 2010.0, 0.1, {"z_min_m": 0.0})
    sig.geotiff(tmp_path / "m.png", tmp_path / "m.tif", mds=True)
    quadrado = [[1002.0, 2002.0], [1012.0, 2002.0], [1012.0, 2008.0], [1002.0, 2008.0], [1002.0, 2002.0]]
    with rasterio.open(sig.recortar(tmp_path / "m.tif", quadrado, tmp_path / "m_obra.tif")) as t:
        assert t.count == 1 and t.nodata == -9999.0 and t.dtypes[0] == "float32"
        assert (t.width, t.height) == (100, 60) and t.transform.c == pytest.approx(1002.0)
        z = t.read(1)
        assert (z == 5.0).all()                                       # o retângulo inteiro está dentro
    triangulo = [[1002.0, 2002.0], [1012.0, 2002.0], [1002.0, 2008.0], [1002.0, 2002.0]]
    with rasterio.open(sig.recortar(tmp_path / "m.tif", triangulo, tmp_path / "m_tri.tif")) as t:
        z = t.read(1)
        assert z[5, 5] == pytest.approx(5.0) and z[5, 95] == -9999.0 and (z == -9999.0).mean() == pytest.approx(0.5, abs=0.05)


def test_reestruturar_nao_e_estrutura():
    hidraulica = ("Hidráulica", "Tubulações e conexões")
    assert pdf_cad.disciplina_do_layer("_EXISTENTES A REESTRUTURAR", hidraulica) == ("Geral", "Existente")
    assert pdf_cad.disciplina_do_layer("CISM_08_LINHA_CONCRETO", hidraulica) == ("Civil", "Estrutura")


@pytest.mark.parametrize("modulo", ["sfm", "georef_prancha", "supressao"])
def test_constantes_tecnicas_tem_fonte(modulo):
    """Regra 9.1: toda constante UPPERCASE do módulo aparece em alguma aplicação de metadados()."""
    import ast
    import importlib
    from pathlib import Path
    mod = importlib.import_module(f"camadas.{modulo}")
    arvore = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
    constantes = {alvo.id for no in ast.walk(arvore) if isinstance(no, ast.Assign) for alvo in no.targets
                  if isinstance(alvo, ast.Name) and alvo.id.isupper() and len(alvo.id) > 3}
    meta = mod.metadados()
    citadas = json.dumps(meta["bibliografia"] + meta.get("premissas", []), ensure_ascii=False)
    assert all(c in citadas for c in constantes), constantes
    assert set(meta["funcoes"]) <= set(dir(mod))


def test_marco_destruido_normalizado():
    campos = sig._campos_marco({"DENOMINAÇÃO": "RN07A", "CLASSIFICAÇÃO": "RN", "SITUAÇÃO ÚLTIMA VISITA": "DESTRUIDO",
                                "MUNICÍPIO": "FOZ DO IGUACU", "DATA ÚLTIMA VISITA": "01/02/2020"})
    assert campos["destruido"] and campos["municipio"] == "FOZ DO IGUACU" and campos["ultima_visita"] == "01/02/2020"
    assert sig._campos_marco({"SITUACAO": "BOM", "TEMA": "GPS"})["destruido"] is False


def test_malha_recupera_afim_e_descarta_leitura_errada():
    from camadas import georef_prancha
    M = georef_prancha.matriz_inicial([[0, 0], [100, 0], [0, 100]],
                                      [[745400.0, 7182800.0], [745435.278, 7182800.0], [745400.0, 7182764.722]])
    Minv = np.linalg.inv(M)
    obs = []
    for chave, (eixo, valor) in enumerate([("E", 745400.0), ("E", 745600.0), ("N", 7182600.0), ("N", 7182800.0),
                                            ("N", 7182400.0), ("E", 745800.0)]):
        fixo = valor
        for t in (-300.0, 300.0):                      # duas pontas de cada linha da malha
            u = [fixo, 7182600.0 + t] if eixo == "E" else [745600.0 + t, fixo]
            obs.append({"p": geo.aplicar(Minv, [u])[0], "eixo": eixo, "chave": chave,
                        "valor": 745000.0 if chave == 5 else valor})          # a última foi lida errado
    r = georef_prancha._ajustar_malha(obs, 0.5, 4)
    assert r["descartadas"] == ["E 745000"]
    assert np.allclose(r["M"], M, atol=1e-6)
    assert georef_prancha._ajustar_malha(obs[:6], 0.5, 4)["M"] is None      # 3 valores fecham sem sobra


def test_linhas_da_malha_funde_colineares_e_agrupa_glifos():
    from camadas import georef_prancha
    glifo = [np.array([[0.0, 0.0], [0.0, 6.0]]), np.array([[0.0, 0.0], [3.0, 0.0], [3.0, 6.0]])]
    rotulo = [g + [100 + 4 * i, 50] for i in range(6) for g in glifo[i % 2:i % 2 + 1]]
    tracos = [{"layer": "GRADE", "partes": [np.array([[0.0, 60.0], [300.0, 60.0]]), np.array([[320.0, 60.0], [600.0, 60.0]]),
                                             np.array([[200.0, 0.0], [200.0, 500.0]])] + rotulo},
              {"layer": "OUTRO", "partes": [np.array([[0.0, 0.0], [900.0, 0.0]])]}]
    m = georef_prancha.linhas_da_malha(tracos, "GRADE")
    horizontais = [l for l in m["linhas"] if l["angulo"] < 1]
    assert len(m["linhas"]) == 2 and len(horizontais) == 1
    assert np.allclose(horizontais[0]["p0"], [0, 60]) and np.allclose(horizontais[0]["p1"], [600, 60])
    assert len(m["rotulos"]) == 1 and min(m["rotulos"][0]["angulo"], 180 - m["rotulos"][0]["angulo"]) < 5


def test_escopo_sem_preco_e_com_cadastro_sanepar(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from camadas import orcamento_sanepar
    wb = openpyxl.Workbook()
    mat = wb.active
    mat.title = "sanepar_mat"
    mat.append(["seq_estoque", "descricao", "unidade_medida", "situacao", "familia", "dn", "preco_unitario"])
    mat.append([301218, "TUBO POLIETILENO PE 100 PN 10 DE 315", "M", "1 - Licitável", "tubo", None, 99.9])
    mat.append([134562, "TUBO FD K7 JE DN 1000", "M", "6 - Para Obra", "tubo", 1000, 5000])
    wb.create_sheet("sanepar_preços").append(["seq_estoque", "preco_unitario"])
    wb.save(tmp_path / "estudo.xlsx")
    assert orcamento_sanepar.gravar_catalogo(tmp_path / "estudo.xlsx", tmp_path / "cat.jsonl.gz") == 2
    cat = orcamento_sanepar.catalogo(tmp_path / "cat.jsonl.gz")
    assert set(cat) == {"301218", "134562"} and "preco_unitario" not in cat["301218"]
    cab = "tabela;nome_tabela;item;codigo;descricao;unidade;qtd_etapa1;qtd_etapa2;etapa;material_base;local\n"
    (tmp_path / "rel.csv").write_text(cab + "01;ADUTORA;01;301218;TUBO PE DE 315;m;498,5;0;1ª etapa;pead;AAT\n"
                                            "01;ADUTORA;02;134562;TUBO FD DN1000;pç;7;0;1ª etapa;fd;ETA\n"
                                            "02;CIVIL;01;-;BLOCO DE APOIO;un;46054;3;;;ETA\n", encoding="utf-8")
    e = obra.etapa_escopo({"escopo": {"relacao_csv": str(tmp_path / "rel.csv"), "catalogo": str(tmp_path / "cat.jsonl.gz")}})
    texto = json.dumps(e, ensure_ascii=False)
    assert "preco" not in texto and "valor" not in texto and "R$" not in texto
    a, b, c = e["itens"]
    assert a["alerta"] is None and a["cadastro"]["unidade_medida"] == "M"
    assert "unidade do cadastro Sanepar é M" in b["alerta"]                     # pç × M
    assert "sem código" in c["alerta"] and "data do Excel" in c["alerta"] and c["q1"] == 0
    assert e["totais"] == {"itens": 3, "itens_q1": 2, "itens_q2": 1, "com_alerta": 2, "no_cadastro": 2}


def test_continuidade_escolhe_pela_coincidencia_na_area_comum():
    """A folha 2 desenha um L; a folha 1 desenha a cauda do mesmo L além da emenda. Deslizar a folha 2 ao longo da
    própria rua também encosta, mas a esquina deixa de coincidir."""
    from shapely import LineString, Polygon

    from camadas import georef_prancha
    vizinha = LineString([(0, 0), (100, 0), (100, -40)])           # folha 1 em UTM: rua + cauda que dobra a esquina
    janela_viz = Polygon([(-10, -60), (130, -60), (130, 20), (-10, 20)])
    l_pt = LineString([(100, 0), (100, -40), (100, -200)])         # folha 2 em pt: começa na esquina e desce
    janela_pt = (80, -220, 140, 10)
    def M(ty):
        return np.array([[1.0, 0, 0], [0, 1.0, ty], [0, 0, 1]])
    hip = [M(0), M(-30), M(300)]                                   # certa, deslizada 30 m pela rua, longe
    r = georef_prancha.escolher_por_continuidade(hip, l_pt, janela_pt, vizinha, janela_viz)
    assert r["ok"] and r["M"][1, 2] == 0
    assert r["hipoteses"][0]["coincide_m"] >= 3 * r["hipoteses"][1]["coincide_m"] and r["hipoteses"][2]["comum_m"] == 0
    r = georef_prancha.escolher_por_continuidade([M(300)], l_pt, janela_pt, vizinha, janela_viz)
    assert not r["ok"] and r["M"] is None


def test_sondagens_3d_em_cota_sem_inventar_limite():
    furos = [{"id": "SP-01", "E": 1010.0, "N": 2020.0, "cota_boca": 240.0, "profundidade_m": 13.5, "na_m": 9.0,
              "impenetravel": True, "camadas": [{"de": 0.0, "ate": 0.45, "classe": "aterro", "descricao": "aterro"},
                                                 {"de": None, "ate": None, "classe": "argila", "descricao": "argila mole"}]},
             {"id": "SP-99", "E": None, "N": None, "cota_boca": 239.0, "profundidade_m": 5.0}]
    s = obra.sondagens_3d(furos, [1000.0, 2000.0, 0.0])
    assert len(s) == 1 and (s[0]["x"], s[0]["y"], s[0]["z_na"], s[0]["z_fundo"]) == (10.0, 20.0, 231.0, 226.5)
    a, b = s[0]["segmentos"]
    assert (a["z_topo"], a["z_base"], a["confirmado"]) == (240.0, 239.55, True)
    assert (b["z_topo"], b["z_base"], b["confirmado"], b["descricao"]) == (239.55, 226.5, False, "argila mole")


def test_tubo_contrato_x_desenho():
    escopo = {"desenhos_por_tabela": {"94": "010-SAA-0017-7471-PBHI-DE-AAT06PTPER-R1", "95": "outro-desenho"},
              "itens": [{"tabela": "94", "codigo": "309244", "q1": 540.0, "q2": 0.0, "descricao": "TUBO PE DE 630",
                         "cadastro": {"familia": "tubo", "unidade_medida": "M"}},
                        {"tabela": "94", "codigo": "312059", "q1": 2.0, "q2": 0.0, "descricao": "CURVA",
                         "cadastro": {"familia": "curva", "unidade_medida": "UN"}}]}
    pranchas = [{"id": "aat06_10", "nome": "AAT06 10", "pdf": "010-SAA-0017-7471-PBHI-DE-AAT06PTPER-R2.pdf", "M": [1, 0, 0, 0, -1, 0],
                 "quantitativos": [{"layer": "_PERFIL_", "eixo_faixa_m": 542.0, "comprimento_m": 3.0}]}]
    linhas = obra.tubo_contrato_x_desenho(escopo, pranchas, {"pranchas": [{"id": "aat06_10", "layer_tubo": "_PERFIL_"}]})
    assert linhas == [{"prancha": "aat06_10", "nome": "AAT06 10", "tabelas": ["94"], "codigo": "309244",
                       "descricao": "TUBO PE DE 630", "contrato_m": 540.0, "desenho_m": 542.0, "diferenca_pct": 0.4}]
    assert escopo["itens"][0]["desenho"]["diferenca_pct"] == 0.4 and "desenho" not in escopo["itens"][1]


def test_area_da_obra_recorta_a_ortofoto(tmp_path):
    """Área da obra = envoltória das intervenções dentro do voo + margem; a ortofoto do HTML fica só nela."""
    crs = {"ll2utm": [1, 0, 0, 0, 1, 0]}                        # coordenadas já em "UTM" no teste
    feat = lambda tipo, c: {"type": "Feature", "properties": {}, "geometry": {"type": tipo, "coordinates": c}}
    vetores = [{"id": "escavacao", "geojson": {"type": "FeatureCollection", "features": [
                   feat("Polygon", [[[1020, 2020], [1040, 2020], [1040, 2040], [1020, 2040], [1020, 2020]]])]}},
               {"id": "valas", "geojson": {"type": "FeatureCollection", "features": [
                   feat("LineString", [[1030, 2030], [1030, 2060], [5000, 9000]])]}},       # sai do voo: só conta o trecho dentro
               {"id": "cameras", "geojson": {"type": "FeatureCollection", "features": [feat("Point", [1090, 2090])]}}]
    cfg = {"area_obra": {"fontes": ["escavacao$", "valas$"], "margem_m": 5.0}}
    area = obra.area_da_obra(cfg, vetores, [1000, 2000, 1100, 2100], crs)
    assert area.bounds == pytest.approx((1015, 2015, 1045, 2065), abs=0.01)   # buffer em segmentos
    assert obra.area_da_obra({}, vetores, [1000, 2000, 1100, 2100], crs) is None
    (tmp_path / "sfm").mkdir()
    cv2.imwrite(str(tmp_path / "sfm" / "ortofoto.jpg"), np.random.default_rng(1).integers(0, 240, (1000, 1000, 3), np.uint8))   # 0,1 m/px
    b = obra._ortofoto_html(tmp_path, {"extensao_utm": [1000, 2000, 1100, 2100], "res_m_px": 0.1}, 0.5, area)
    assert (b["w"], b["h"]) == (61, 101) and b["m"] == pytest.approx([0.5, 0, 1015, 0, -0.5, 2065])
    inteira = obra._ortofoto_html(tmp_path, {"extensao_utm": [1000, 2000, 1100, 2100], "res_m_px": 0.1}, 0.5)
    assert (inteira["w"], inteira["h"]) == (200, 200) and len(b["src"]) < len(inteira["src"])


def test_versao_e_nome_do_html():
    """A versão do código é a do topo do CHANGELOG e entra no nome do HTML com a obra e a data."""
    import re
    from pathlib import Path

    from camadas import VERSAO
    topo = re.search(r"^## (\d+\.\d+\.\d+)", (Path(__file__).parents[1] / "CHANGELOG.md").read_text(), re.MULTILINE)[1]
    assert VERSAO == topo
    assert obra.nome_html({"id": "foz-vilac"}, "2026-10-29") == f"foz-vilac_camadas_v{VERSAO}_2026-10-29.html"
    assert obra.nome_html({"id": "x", "nome_html": "{id}-{versao}"}) == f"x-{VERSAO}.html"
