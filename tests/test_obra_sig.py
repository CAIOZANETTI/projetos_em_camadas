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
