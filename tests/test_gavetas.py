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


def test_ler_pasta_de_outro_formato_avisa_em_vez_de_devolver_vazio(tmp_path):
    gv.gravar(tmp_path, _base(), "jsonl")
    with pytest.raises(ValueError, match="só em jsonl"):
        gv.ler(tmp_path, "parquet")
    assert gv.ler(tmp_path / "nao_existe", "parquet")["fatos"] == []


def test_nome_de_tabela_so_de_gaveta_conhecida():
    assert gv._tabela_sql("fatos") == '"fatos"'
    with pytest.raises(ValueError):
        gv._tabela_sql('fatos"; DROP TABLE objetos; --')


# --------------------------------------------------------------------------------------------------------------------
# Paridade com obras_lineares (trechos sem eixo, sondagens pelos nomes da planilha)
# --------------------------------------------------------------------------------------------------------------------

def _trechos_planilha():
    """Os trechos aplicados da etapa: VCA, MND (a planilha diz VCA; a decisão troca, e o aplicado já vem MND) e prof vazia."""
    comum = {"material": "PEAD", "na_m": None, "solo": None, "supressao_frac": 0.0}
    return [{"linha": 7, "local": "Rede A", "dn_mm": 200.0, "sond_ini": "SP-01", "sond_fim": "SP 02", "prof_m": 2.0,
             "comp_m": 40.0, "metodo": "VCA", "pavimentos": {"asfalto": 40.0}, **comum},
            {"linha": 8, "local": "Rede B", "dn_mm": 160.0, "sond_ini": "SP-02", "sond_fim": "SP-02", "prof_m": 2.5,
             "comp_m": 60.0, "metodo": "MND", "pavimentos": {"concreto": 60.0}, **comum},
            {"linha": 9, "local": "Rede C", "dn_mm": 200.0, "sond_ini": "SP-01", "sond_fim": "SP-01", "prof_m": None,
             "comp_m": 25.0, "metodo": "VCA", "pavimentos": {}, **comum}]


def _base_planilha():
    """Base à mão equivalente a `_trechos_planilha` (sem geometria nos trechos) e dois furos com camadas e NA."""
    fatos, objetos, evidencias = [], [], [_ev("E1"), _ev("E2", "laudo", "Sonnet"), _ev("D1", "decisao", "você")]
    for t in _trechos_planilha():
        obj = f"OL-{t['linha']:03d}"
        objetos.append({"objeto_id": obj, "classe": "trecho_tubo"})
        for p in ("local", "dn_mm", "material", "sond_ini", "sond_fim", "prof_m", "comp_m", "pavimentos"):
            if t[p] not in (None, {}):
                fatos.append(_fato(obj, p, t[p]))
    fatos.append(_fato("OL-008", "metodo", "MND", "decidido", ev="D1"))
    camadas = [{"de": 0, "ate": 6, "descricao": "argila siltosa"}]
    for sp, na in (("SP-01", 1.0), ("SP-02", 5.0)):              # SP-01: NA acima do fundo da vala (2,0 m)
        objetos.append({"objeto_id": sp, "classe": "furo_sondagem"})
        fatos += [_fato(sp, "na_m", na, "observado", "E2"), _fato(sp, "camadas", camadas, "observado", "E2")]
    geometria = [{"objeto_id": "SP-01", "tipo": "ponto", "coords": [0, 0], "crs_h": "EPSG:31982", "datum_v": "ortométrico"},
                 {"objeto_id": "SP-02", "tipo": "ponto", "coords": [30, 0], "crs_h": "EPSG:31982", "datum_v": "ortométrico"}]
    return {"objetos": objetos, "geometria": geometria, "fatos": fatos, "evidencias": evidencias, "pendencias": [],
            "servicos": []}


def _furos_planilha():
    camadas = [{"de": 0, "ate": 6, "descricao": "argila siltosa"}]
    return [{"id": "SP-01", "E": 0, "N": 0, "na_m": 1.0, "camadas": camadas},
            {"id": "SP-02", "E": 30, "N": 0, "na_m": 5.0, "camadas": camadas}]


def test_paridade_planilha_vca_mnd_e_prof_vazia_sem_diferencas():
    base = _base_planilha()
    assert gv.conferir_base(base) == []
    servicos, pend = gv.calcular(base)
    assert {s["regra"] for s in servicos if s["objeto_id"] == "OL-008"} == {"mnd"}
    assert {s["objeto_id"] for s in servicos} == {"OL-007", "OL-008"}                 # OL-009 sem prof_m: pendência
    assert any(p["objeto_id"] == "OL-009" for p in pend)
    q = ol.quantificar(_trechos_planilha()[0], _furos_planilha())
    assert q["geotecnia"]["esgotamento_frac"] > 0                                      # SP-01 tem o NA acima do fundo
    assert gv.paridade(base, _trechos_planilha(), _furos_planilha()) == []


def test_furo_citado_em_sond_ini_entra_nos_fatos_do_trecho_sem_eixo():
    servicos, _ = gv.calcular(_base_planilha())
    do_trecho = [s for s in servicos if s["objeto_id"] == "OL-007"]
    assert do_trecho and all("SP-01.na_m.observado" in s["fatos"] and "SP-02.camadas.observado" in s["fatos"]
                             for s in do_trecho)                                       # "SP 02" casa com SP-02 por id_furo
    do_mnd = [s for s in servicos if s["objeto_id"] == "OL-008"]
    assert all("SP-02.na_m.observado" in s["fatos"] and "SP-01.na_m.observado" not in s["fatos"] for s in do_mnd)


def test_paridade_devolve_a_diferenca_quando_so_a_base_muda():
    base = copy.deepcopy(_base_planilha())
    for f in base["fatos"]:
        if f["objeto_id"] == "OL-007" and f["propriedade"] == "comp_m":
            f["valor"] = 50.0
    difs = gv.paridade(base, _trechos_planilha(), _furos_planilha())
    esc = next(d for d in difs if d["objeto_id"] == "OL-007" and d["saida"] == "escavacao_m3")
    q = ol.quantificar(_trechos_planilha()[0], _furos_planilha())
    assert esc["obras_lineares"] == pytest.approx(q["escavacao_m3"])
    assert esc["gavetas"] > esc["obras_lineares"] and esc["chave"] is None
    assert {d["objeto_id"] for d in difs} == {"OL-007"}


def test_paridade_trecho_sem_servico_so_difere_se_o_quantificar_calculou():
    base = _base_planilha()
    trechos = _trechos_planilha()
    assert gv.paridade(base, trechos, _furos_planilha()) == []                         # OL-009: nenhum lado calcula
    trechos[2]["prof_m"] = 2.0                                                         # a planilha tem prof, a base não
    difs = gv.paridade(base, trechos, _furos_planilha())
    assert any(d["objeto_id"] == "OL-009" and d["saida"] == "escavacao_m3" and d["gavetas"] is None
               and d["obras_lineares"] > 0 for d in difs)


def test_paridade_usa_o_metodo_do_trecho_recebido():
    base = _base_planilha()
    trechos = _trechos_planilha()
    trechos[1]["metodo"] = "VCA"                                  # o aplicado diz VCA, a base decidiu MND
    difs = gv.paridade(base, trechos, _furos_planilha())
    met = [d for d in difs if d["saida"] == "metodo"]
    assert met == [{"objeto_id": "OL-008", "saida": "metodo", "chave": None, "gavetas": "MND", "obras_lineares": "VCA"}]


def test_paridade_dois_trechos_do_mesmo_local_com_decisao_mnd():
    from camadas import extrair_gavetas as eg
    base = _base_planilha()
    base["fatos"] = [f for f in base["fatos"] if f["propriedade"] != "metodo"]
    trechos = _trechos_planilha()
    trechos[0]["local"] = trechos[1]["local"] = "Rede B"
    for t in trechos[:2]:
        t["metodo"] = "MND"
    base = eg.juntar(base, eg.de_decisoes({"rede b": "MND"}, trechos, "obra.json"))
    servicos, _ = gv.calcular(base)
    assert {s["regra"] for s in servicos if s["objeto_id"] in ("OL-007", "OL-008")} == {"mnd"}
    assert gv.paridade(base, trechos, _furos_planilha()) == []
    base["fatos"] = [f for f in base["fatos"] if f["fato_id"] != "OL-007.metodo.decidido"]
    assert any(d["objeto_id"] == "OL-007" and d["saida"] == "metodo" for d in gv.paridade(base, trechos, _furos_planilha()))


def _base_furo_citado(com_furo=True):
    t = {"linha": 3, "local": "X", "dn_mm": 200.0, "material": "PEAD", "sond_ini": "SP-03", "sond_fim": "SP-03",
         "prof_m": 2.0, "comp_m": 10.0, "metodo": "VCA", "pavimentos": {}, "na_m": None, "solo": None}
    fatos = [_fato("OL-003", p, t[p]) for p in ("dn_mm", "material", "sond_ini", "sond_fim", "prof_m", "comp_m")]
    objetos = [{"objeto_id": "OL-003", "classe": "trecho_tubo"}]
    if com_furo:                                                  # furo citado, sem geometria (sem E/N)
        objetos.append({"objeto_id": "SP-03", "classe": "furo_sondagem"})
        fatos += [_fato("SP-03", "na_m", 0.5, "observado", "E2"),
                  _fato("SP-03", "camadas", [{"de": 0, "ate": 6, "descricao": "argila"}], "observado", "E2")]
    return t, {"objetos": objetos, "geometria": [], "fatos": fatos, "evidencias": [_ev("E1"), _ev("E2", "laudo", "Sonnet")],
               "pendencias": [], "servicos": []}


def test_furo_sem_geometria_entra_so_pelo_nome_e_a_geotecnia_tem_paridade():
    t, base = _base_furo_citado()
    furos_ol = [{"id": "SP-03", "E": None, "N": None, "na_m": 0.5, "camadas": [{"de": 0, "ate": 6, "descricao": "argila"}]}]
    assert gv.furos(base, "furo_sondagem")[0]["E"] is None
    assert ol.quantificar(t, furos_ol)["geotecnia"]["esgotamento_frac"] == 1.0
    assert gv.paridade(base, [t], furos_ol) == []
    _, sem = _base_furo_citado(False)
    difs = gv.paridade(sem, [t], furos_ol)
    esg = next(d for d in difs if d["saida"] == "geotecnia.esgotamento_frac")
    assert esg["gavetas"] == 0.0 and esg["obras_lineares"] == 1.0


def test_furo_sem_geometria_e_ignorado_quando_ha_eixo():
    base = _base()
    base["objetos"].append({"objeto_id": "SP-99", "classe": "furo_sondagem"})
    base["fatos"].append(_fato("SP-99", "na_m", 0.1, "observado", "E2"))
    e = gv.entrada(base, base["objetos"][0])
    assert e["pts"] is not None and "SP-99" not in {i for f in e["fatos"] for i in [f.split(".")[0]]}


# --- recálculo incremental (chave = regra + versão + dados + fatos + furos usados) ---

def _base_tres():
    """A base da planilha com a profundidade do 3º trecho preenchida: os 3 trechos têm serviços."""
    base = _base_planilha()
    base["fatos"].append(_fato("OL-009", "prof_m", 2.0))
    return base


def _muda_fato(base, obj, prop, valor):
    nova = copy.deepcopy(base)
    for f in nova["fatos"]:
        if f["objeto_id"] == obj and f["propriedade"] == prop:
            f["valor"] = valor
    return nova


def _por_objeto(servicos):
    saida = {}
    for s in servicos:
        saida.setdefault(s["objeto_id"], []).append(s)
    return saida


def test_incremental_primeira_vez_recalcula_e_segunda_reaproveita():
    base = _base_tres()
    s1, p1, e1 = gv.calcular_incremental(base)
    assert e1 == {"recalculados": 3, "reaproveitados": 0}
    assert all(s["chave_calculo"] for s in s1)
    s2, p2, e2 = gv.calcular_incremental(base, s1)
    assert e2 == {"recalculados": 0, "reaproveitados": 3}
    assert s2 == s1 and p2 == p1
    assert gv.calcular(base) == (s1, p1)


def test_incremental_mudar_prof_de_um_trecho_recalcula_so_ele():
    base = _base_tres()
    s1, _, _ = gv.calcular_incremental(base)
    s2, _, est = gv.calcular_incremental(_muda_fato(base, "OL-007", "prof_m", 3.1), s1)
    assert est == {"recalculados": 1, "reaproveitados": 2}
    a, b = _por_objeto(s1), _por_objeto(s2)
    assert a["OL-007"] != b["OL-007"]
    assert a["OL-008"] == b["OL-008"] and a["OL-009"] == b["OL-009"]


def test_incremental_mudar_versao_da_regra_recalcula_tudo(monkeypatch):
    base = _base_tres()
    s1, _, _ = gv.calcular_incremental(base)
    regras = copy.deepcopy(gv.SERVICOS)
    for r in regras["regras"].values():
        r["versao"] = r["versao"] + "-nova"
    monkeypatch.setattr(gv, "SERVICOS", regras)
    _, _, est = gv.calcular_incremental(base, s1)
    assert est == {"recalculados": 3, "reaproveitados": 0}


def test_incremental_mudar_na_do_furo_recalcula_so_quem_cita():
    base = _base_tres()
    s1, _, _ = gv.calcular_incremental(base)
    _, _, est = gv.calcular_incremental(_muda_fato(base, "SP-02", "na_m", 1.5), s1)
    assert est == {"recalculados": 2, "reaproveitados": 1}       # SP-02 é citado por OL-007 e OL-008; OL-009 cita SP-01


def test_incremental_reaproveitar_nao_chama_a_funcao_da_regra(monkeypatch):
    base = _base_tres()
    s1, p1, _ = gv.calcular_incremental(base)
    chamadas = []
    original = ol.quantificar
    monkeypatch.setattr(ol, "quantificar", lambda *a, **k: chamadas.append(1) or original(*a, **k))
    _, p2, est = gv.calcular_incremental(base, s1)
    assert chamadas == [] and est["reaproveitados"] == 3 and p2 == p1
    gv.calcular_incremental(_muda_fato(base, "OL-007", "prof_m", 3.1), s1)
    assert len(chamadas) == 1


def test_chave_servico_deterministica_e_sensivel_a_cada_parte():
    f = [{"id": "SP", "na_m": 1.0}]
    k = gv.chave_servico("r", "1", {"a": 1}, ["F1"], f)
    assert k == gv.chave_servico("r", "1", {"a": 1}, ["F1"], f) and len(k) == 12
    outras = {gv.chave_servico("r", "2", {"a": 1}, ["F1"], f), gv.chave_servico("r", "1", {"a": 2}, ["F1"], f),
              gv.chave_servico("r", "1", {"a": 1}, ["F2"], f),
              gv.chave_servico("r", "1", {"a": 1}, ["F1"], [{"id": "SP", "na_m": 2.0}])}
    assert k not in outras and len(outras) == 4


def test_incremental_ve_as_constantes_da_regra(monkeypatch):
    """Aceite da rodada 23: mudar uma constante do MOS (empolamento) muda a chave e recalcula, sem subir a versão."""
    base = _base()
    servicos, _, _ = gv.calcular_incremental(base)
    # desde a rodada 25 o empolamento mora no modelo geotécnico (conceitos/geotecnia.json), de que o MOS depende;
    # PREMISSAS é lido do JSON no import, então trocar o atributo equivale a trocar o arquivo
    from camadas import geotecnia as geo
    premissas = copy.deepcopy(geo.PREMISSAS)
    premissas["empolamento"]["solo"] = premissas["empolamento"]["solo"] * 2
    monkeypatch.setattr(geo, "PREMISSAS", premissas)
    monkeypatch.setattr(geo, "EMPOLAMENTO_SOLO", geo.EMPOLAMENTO_SOLO * 2)
    novos, _, est = gv.calcular_incremental(base, anterior=servicos)
    assert est["reaproveitados"] == 0 and est["recalculados"] >= 1
    antes = {s["servico_id"]: s["valor"] for s in servicos}
    depois = {s["servico_id"]: s["valor"] for s in novos}
    assert depois["T01:vala_aberta:bota_fora_m3"] == pytest.approx(2 * antes["T01:vala_aberta:bota_fora_m3"], abs=0.002)


def test_paridade_compara_os_servicos_gravados():
    """Aceite da rodada 23: valor adulterado (ou velho) nos serviços que vão para a EAP aparece na paridade."""
    base = _base()
    base["objetos"][0]["objeto_id"] = "OL-007"
    for g in ("geometria", "fatos"):
        for r in base[g]:
            if r["objeto_id"] == "T01":
                r["objeto_id"] = "OL-007"
    trechos = [{"linha": 7, "local": "x", "dn_mm": 1000, "material": "FD", "prof_m": 2.4, "comp_m": 57.3,
                "metodo": "VCA", "pavimentos": {"grama": 57.3}, "supressao_frac": 1.0, "sond_ini": None, "sond_fim": None,
                "na_m": None, "solo": None}]
    furos = [f for f in gv.furos(base, "furo_sondagem")]
    servicos, _ = gv.calcular(base)
    velhos = [{**s, "valor": 999.0} if s["saida"] == "escavacao_m3" else s for s in servicos]
    assert any(d["saida"] == "escavacao_m3" for d in gv.paridade(base, trechos, furos, servicos=velhos))
