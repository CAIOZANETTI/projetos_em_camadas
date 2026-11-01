import copy
import json

import pytest

from camadas import gavetas as gv
from camadas import obras_lineares as ol


def _ev(i, classe="planilha", executor="código"):
    return {"evidencia_id": i, "classe": classe, "documento": "OL-FOZ.xlsx", "localizador": {"aba": "Obras Lineares", "linha": 7},
            "metodo": "planilha", "executor": executor}


def _fato(obj, prop, valor, natureza="projetado", ev="E1"):
    return {"fato_id": f"{obj}.{prop}.{natureza}", "objeto_id": obj, "propriedade": prop, "valor": valor,
            "natureza": natureza, "evidencia_id": ev}


def _base():
    """Trecho da entrada de água bruta (o mesmo de test_obras_lineares) com eixo de 57,3 m e um furo a 10 m dele."""
    t = "T01"
    fatos = [_fato(t, "dn_mm", 1000), _fato(t, "material", "FD"), _fato(t, "prof_m", 2.4), _fato(t, "comp_m", 57.3),
             _fato(t, "pavimentos", {"grama": 57.3}), _fato(t, "supressao_frac", 1.0),
             _fato("SP-02", "na_m", 9.0, "observado", "E2"),
             _fato("SP-02", "camadas", [{"de": 0, "ate": 5, "descricao": "argila siltosa"}], "observado", "E2")]
    return {"objetos": [{"objeto_id": t, "classe": "trecho_tubo"}, {"objeto_id": "SP-02", "classe": "furo_sondagem"}],
            "geometria": [{"objeto_id": t, "tipo": "linha", "coords": [[0, 0], [57.3, 0]], "crs_h": "EPSG:31982", "datum_v": "ortométrico"},
                          {"objeto_id": "SP-02", "tipo": "ponto", "coords": [20, 10], "crs_h": "EPSG:31982", "datum_v": "ortométrico"}],
            "fatos": fatos, "evidencias": [_ev("E1"), _ev("E2", "laudo", "Sonnet")], "pendencias": [], "servicos": []}


def test_de_para_so_cita_o_que_existe():
    assert gv.conferir_de_para() == []


def test_base_de_exemplo_confere():
    assert gv.conferir_base(_base()) == []


def test_fato_sem_evidencia_ou_fora_do_contrato_reprova():
    base = _base()
    base["fatos"].append(_fato("T01", "cor", "azul", "chutado", ev="E9"))
    erros = gv.conferir_base(base)
    assert "fatos T01.cor.chutado: evidência E9 não existe" in erros
    assert any("propriedade 'cor'" in e for e in erros) and any("natureza 'chutado'" in e for e in erros)
    base["fatos"].append({**_fato("T02", "dn_mm", 300), "evidencia_id": None})
    erros = gv.conferir_base(base)
    assert "fatos T02.dn_mm.projetado: falta evidencia_id" in erros
    assert "fatos T02.dn_mm.projetado: objeto T02 não está em objetos" in erros


def test_calculo_so_das_gavetas_bate_com_obras_lineares():
    servicos, _ = gv.calcular(_base())
    v = {s["servico_id"]: s["valor"] for s in servicos}
    TRECHO = {"dn_mm": 1000, "material": "FD", "prof_m": 2.4, "comp_m": 57.3, "pavimentos": {"grama": 57.3},
              "supressao_frac": 1.0}
    q = ol.quantificar(TRECHO)
    assert v["T01:vala_aberta:escavacao_m3"] == pytest.approx(q["escavacao_m3"])
    assert v["T01:vala_aberta:reaterro_m3"] == pytest.approx(q["reaterro_m3"])
    assert v["T01:vala_aberta:pavimento_m2:grama"] == pytest.approx(q["pavimento_m2"]["grama"])


def test_sondagem_entra_pela_posicao_e_fica_na_memoria_de_calculo():
    base = _base()
    servicos, pend = gv.calcular(base)
    assert "SP-02.na_m.observado" in servicos[0]["fatos"]                 # o furo a 10 m do eixo lastreia a vala
    assert not [p for p in pend if "sem sondagem" in p["motivo"]]
    base["geometria"][1]["coords"] = [20, 5000]                          # furo longe: fora do raio de influência
    servicos, pend = gv.calcular(base)
    assert "SP-02.na_m.observado" not in servicos[0]["fatos"]
    assert [p for p in pend if "sem sondagem" in p["motivo"]]


def test_fato_obrigatorio_faltando_vira_pendencia_e_nenhum_servico():
    base = _base()
    base["fatos"] = [f for f in base["fatos"] if f["propriedade"] != "prof_m"]
    servicos, pend = gv.calcular(base)
    assert servicos == []
    assert pend == [{"objeto_id": "T01", "regra": "vala_aberta", "motivo": "faltam fatos obrigatórios: prof_m"}]


def test_decisao_troca_o_metodo_sem_reler_documento():
    base = _base()
    base["evidencias"].append(_ev("D1", "decisao", "você"))
    base["fatos"].append(_fato("T01", "metodo", "MND", "decidido", ev="D1"))
    servicos, _ = gv.calcular(base)
    assert {s["regra"] for s in servicos} == {"mnd"}
    assert next(s for s in servicos if s["saida"] == "caximbos")["valor"] >= 2
    assert all("T01.metodo.decidido" in s["fatos"] for s in servicos)


def test_natureza_mais_forte_vence():
    base = _base()
    base["evidencias"].append(_ev("E3", "laudo"))
    base["fatos"].append(_fato("T01", "prof_m", 3.0, "observado", ev="E3"))
    assert gv.fatos_do_objeto(base, "T01")["prof_m"]["valor"] == 3.0


DEPENDENCIA = {"parquet": ["pyarrow"], "geoparquet": ["pyarrow", "shapely", "pyproj"], "duckdb": ["pyarrow", "duckdb"]}
NOVOS = ["parquet", "geoparquet", "duckdb"]


def _exige(formato):
    for mod in DEPENDENCIA.get(formato, []):
        pytest.importorskip(mod)


@pytest.mark.parametrize("formato", ["jsonl", "csv"] + NOVOS)
def test_formato_fisico_ida_e_volta_sem_perda(tmp_path, formato):
    _exige(formato)
    base = _base()
    gv.gravar(tmp_path, base, formato)
    lida = gv.ler(tmp_path, formato)
    assert lida == {g: base.get(g, []) for g in gv.GAVETAS}


def test_formato_nao_implementado_avisa(tmp_path):
    with pytest.raises(ValueError, match="sqlite"):
        gv.gravar(tmp_path, _base(), "sqlite")


def test_eap_soma_e_guarda_o_caminho_de_volta():
    base = _base()
    t2 = copy.deepcopy([f for f in base["fatos"] if f["objeto_id"] == "T01"])
    base["objetos"].append({"objeto_id": "T02", "classe": "trecho_tubo"})
    base["fatos"] += [{**f, "objeto_id": "T02", "fato_id": f["fato_id"].replace("T01", "T02")} for f in t2]
    servicos, _ = gv.calcular(base)
    eap = {n["eap"]: n for n in gv.para_eap(servicos)}
    um = {s["servico_id"]: s["valor"] for s in servicos}["T01:vala_aberta:escavacao_m3"]
    assert eap["OL.01"]["valor"] == pytest.approx(2 * um)
    assert eap["OL.01"]["objetos"] == ["T01", "T02"] and len(eap["OL.01"]["servicos"]) == 2
    assert eap["OL.06.grama"]["unidade"] == "m²"


def test_eixo_amostra_cada_metro():
    pts = gv.eixo({"tipo": "linha", "coords": [[0, 0], [3, 0], [3, 2]]})
    assert len(pts) == 5 and pts[0].tolist() == [0.5, 0] and pts[-1].tolist() == [3, 1.5]
    assert gv.eixo({"tipo": "ponto", "coords": [0, 0]}) is None


@pytest.mark.parametrize("formato", ["jsonl", "csv"] + NOVOS)
def test_coluna_mista_e_chave_ausente_voltam_iguais(tmp_path, formato):
    _exige(formato)
    base = _base()
    valores = [1, 2.5, "texto", {"a": [1, 2]}, [1, "b"], True, 3.0, 7]
    base["fatos"] = [{**_fato("T01", "dn_mm", v), "fato_id": f"F{i}"} for i, v in enumerate(valores)]
    base["fatos"].append({"fato_id": "F9", "objeto_id": "T01", "propriedade": "dn_mm", "natureza": "projetado"})  # sem valor
    gv.gravar(tmp_path, base, formato)
    lida = gv.ler(tmp_path, formato)["fatos"]
    assert lida == base["fatos"] and "valor" not in lida[-1]
    assert [type(f["valor"]) for f in lida[:-1]] == [type(v) for v in valores]


@pytest.mark.parametrize("formato", NOVOS)
def test_coluna_escalar_homogenea_fica_nativa(tmp_path, formato):
    _exige(formato)
    gv.gravar(tmp_path, _base(), formato)
    if formato == "duckdb":
        import duckdb
        con = duckdb.connect(str(tmp_path / "base.duckdb"), read_only=True)
        assert ("evidencias", "localizador") in con.execute("SELECT gaveta, coluna FROM _codificacao").fetchall()
        tipos = dict(con.execute("SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'fatos'").fetchall())
        con.close()
        assert tipos["fato_id"] == "VARCHAR" and tipos["valor"] == "VARCHAR"
    else:
        import pyarrow.parquet as pq
        esquema = pq.read_schema(tmp_path / "evidencias.parquet")
        assert json.loads(esquema.metadata[b"gavetas"]) == {"json": ["localizador"]}
        assert str(esquema.field("evidencia_id").type) == "string"


@pytest.mark.parametrize("formato", NOVOS)
def test_gaveta_vazia_nao_deixa_registro_velho(tmp_path, formato):
    _exige(formato)
    gv.gravar(tmp_path, _base(), formato)
    assert len(gv.ler(tmp_path, formato)["fatos"]) == 8
    gv.gravar(tmp_path, {**_base(), "fatos": []}, formato)
    lida = gv.ler(tmp_path, formato)
    assert lida["fatos"] == [] and len(lida["objetos"]) == 2
    if formato != "duckdb":
        assert not (tmp_path / "fatos.parquet").exists()


def test_geoparquet_metadados_geo_e_wkb(tmp_path):
    pq = pytest.importorskip("pyarrow.parquet")
    shapely = pytest.importorskip("shapely")
    pytest.importorskip("pyproj")
    base = _base()
    gv.gravar(tmp_path, base, "geoparquet")
    tabela = pq.read_table(tmp_path / "geometria.parquet")
    geo = json.loads(tabela.schema.metadata[b"geo"])
    col = geo["columns"]["geometry"]
    assert geo["version"] == "1.1.0" and geo["primary_column"] == "geometry"
    assert col["encoding"] == "WKB" and col["geometry_types"] == ["LineString", "Point"]
    assert col["crs"]["id"] == {"authority": "EPSG", "code": 31982}
    geoms = [shapely.from_wkb(b) for b in tabela.column("geometry").to_pylist()]
    assert list(geoms[0].coords) == [(0, 0), (57.3, 0)] and list(geoms[1].coords) == [(20, 10)]
    assert "geometry" not in gv.ler(tmp_path, "geoparquet")["geometria"][0]
    base["geometria"][1]["crs_h"] = "EPSG:31983"                      # CRS misto: crs desconhecido (null), não inventado
    gv.gravar(tmp_path, base, "geoparquet")
    assert json.loads(pq.read_schema(tmp_path / "geometria.parquet").metadata[b"geo"])["columns"]["geometry"]["crs"] is None


def test_geoparquet_poligono_com_furo(tmp_path):
    shapely = pytest.importorskip("shapely")
    pq = pytest.importorskip("pyarrow.parquet")
    pytest.importorskip("pyproj")
    anel = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    furo = [[2, 2], [4, 2], [4, 4], [2, 2]]
    reg = {"objeto_id": "B1", "tipo": "poligono", "coords": [anel, furo], "crs_h": "EPSG:31982", "datum_v": "x"}
    gv.gravar(tmp_path, {"geometria": [reg]}, "geoparquet")
    g = shapely.from_wkb(pq.read_table(tmp_path / "geometria.parquet").column("geometry")[0].as_py())
    assert g.area == pytest.approx(100 - 2) and gv.ler(tmp_path, "geoparquet")["geometria"] == [reg]
