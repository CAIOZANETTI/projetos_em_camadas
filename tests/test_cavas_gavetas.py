"""Cavas nas gavetas (memória espacial, rodada 5, E1): superfície em .npz, regra `cavas`, paridade e etapa."""
import copy
import importlib.util
import json

import numpy as np
import pytest
from shapely.geometry import LineString, box

from camadas import escavacao, gavetas
from camadas import extrair_gavetas as eg

# o escavacao.calcular desenha o contorno da cava por camadas.supressao, que usa rasterio (dependência opcional, extra
# `sig` do pyproject); sem ela, estes testes pulam, como os de tests/test_escavacao.py (lição L016)
precisa_rasterio = pytest.mark.skipif(importlib.util.find_spec("rasterio") is None, reason="rasterio não instalado")

CRS = "EPSG:31981"


def _grade(terreno=10.0, n=400, res=0.25):
    return {"e0": 0.0, "n1": n * res, "res": res, "forma": (n, n), "epsg": 31981,
            "terreno": np.full((n, n), terreno, np.float32), "valido": np.ones((n, n), bool),
            "edificacao": np.zeros((n, n), bool)}


def _entradas():
    bases = [{"geom": box(45, 45, 55, 55), "etapa": "1ª etapa"}]
    marcas = [{"utm": [50.0, 50.0], "cota": 8.0, "topo": False, "prancha": "P1"},
              {"utm": [50.0, 52.0], "cota": 9.5, "topo": True, "prancha": "P1"}]
    cristas = [LineString([(40, 40), (60, 40), (60, 60), (40, 60), (40, 40)])]
    return marcas, bases, cristas


def _base_das_cavas(pasta, grade=None):
    """(base, grade, resultado direto de `calcular`) com a superfície gravada em `pasta`."""
    grade = grade or _grade()
    marcas, bases, cristas = _entradas()
    registro = gavetas.gravar_superficie(pasta, "SUP-MDS", grade)
    base = eg.de_cavas(marcas, bases, cristas, registro, ["P1"], CRS, mds="sfm/ortofoto_mds.png", layers=["BASE", "COTA"])
    return base, grade, escavacao.calcular(bases, marcas, cristas, grade)


@precisa_rasterio
def test_paridade_zero_e_conferencias_vazias(tmp_path):
    base, _, direto = _base_das_cavas(tmp_path)
    assert gavetas.conferir_base(base) == [] and gavetas.conferir_de_para() == []
    servicos, pendencias = gavetas.calcular(base, tmp_path)
    assert pendencias == [] and {s["saida"] for s in servicos} == set(escavacao.SAIDAS_CAVA)
    assert direto["cavas"] and eg.paridade_cavas(base, direto, servicos) == []
    assert eg.paridade_cavas(base, direto, pasta_base=tmp_path) == []
    defasado = copy.deepcopy(direto)
    defasado["cavas"][0]["escavacao_m3"] += 1.0
    assert [d["saida"] for d in eg.paridade_cavas(base, defasado, servicos)] == ["escavacao_cava_m3"]


@precisa_rasterio
def test_nos_cv_na_eap_e_fatos_projetados(tmp_path):
    base, _, _ = _base_das_cavas(tmp_path)
    servicos, _ = gavetas.calcular(base, tmp_path)
    assert {"CV.01.C01", "CV.02.C01", "CV.03.C01"} <= {n["eap"] for n in gavetas.para_eap(servicos)}
    assert base["objetos"] == [{"objeto_id": "CAVAS", "classe": "conjunto_cavas"}]
    assert {f["propriedade"]: f["natureza"] for f in base["fatos"]} == {
        "marcas_cota": "projetado", "bases": "projetado", "cristas": "projetado", "superficie_id": "projetado"}
    evidencias = {e["evidencia_id"]: e for e in base["evidencias"]}
    assert evidencias["EV-CAVAS"]["localizador"]["layers"] == ["BASE", "COTA"]
    sup = evidencias[base["superficies"][0]["evidencia_id"]]
    assert (sup["classe"], sup["metodo"], sup["executor"], sup["documento"]) == (
        "ortofoto", "geometria", "código", "sfm/ortofoto_mds.png")


def test_npz_deterministico_e_ida_e_volta(tmp_path):
    r1 = gavetas.gravar_superficie(tmp_path / "a", "SUP-MDS", _grade())
    r2 = gavetas.gravar_superficie(tmp_path / "b", "SUP-MDS", _grade())
    assert r1["sha256"] == r2["sha256"] and r1 == r2
    assert r1["arquivo"] == "superficies/SUP-MDS.npz" and r1["crs_h"] == CRS and r1["res_m"] == 0.25
    assert (tmp_path / "a" / r1["arquivo"]).read_bytes() == (tmp_path / "b" / r2["arquivo"]).read_bytes()
    g = gavetas.ler_superficie(tmp_path / "a", r1)
    original = _grade()
    assert g["forma"] == (400, 400) and (g["e0"], g["n1"], g["res"]) == (0.0, 100.0, 0.25)
    for chave in ("terreno", "valido", "edificacao"):
        assert g[chave].dtype == original[chave].dtype and np.array_equal(g[chave], original[chave])
    with pytest.raises(ValueError):
        gavetas.gravar_superficie(tmp_path, "../fora", _grade())


@precisa_rasterio
@pytest.mark.parametrize("formato", gavetas.REGRAS["formato"]["implementados"])
def test_gaveta_superficies_vai_e_volta_em_todo_formato(tmp_path, formato):
    base, _, _ = _base_das_cavas(tmp_path / "npz")
    pasta = tmp_path / formato
    gavetas.gravar(pasta, {**eg._base_vazia(), **base}, formato)
    assert gavetas.ler(pasta, formato)["superficies"] == base["superficies"]


@precisa_rasterio
def test_validar_e_conferir_base_cobrem_superficies(tmp_path):
    base, _, _ = _base_das_cavas(tmp_path)
    ruim = copy.deepcopy(base)
    ruim["superficies"][0].update(tipo="nuvem", evidencia_id="EV-NADA")
    ruim["superficies"].append({"superficie_id": "S2", "tipo": "mds"})
    erros = gavetas.conferir_base(ruim)
    assert any("tipo 'nuvem'" in e for e in erros) and any("EV-NADA" in e for e in erros)
    assert any("S2: falta arquivo" in e for e in erros) and any("S2: falta evidencia_id" in e for e in erros)


@precisa_rasterio
def test_terreno_diferente_muda_o_sha_e_recalcula(tmp_path):
    base, grade, _ = _base_das_cavas(tmp_path)
    servicos, _, est = gavetas.calcular_incremental(base, pasta_base=tmp_path)
    assert est == {"recalculados": 1, "reaproveitados": 0}
    _, _, est2 = gavetas.calcular_incremental(base, servicos, tmp_path)
    assert est2 == {"recalculados": 0, "reaproveitados": 1}
    grade["terreno"][100, 100] += 0.5                              # um valor do terreno, longe da cava
    novo = gavetas.gravar_superficie(tmp_path, "SUP-MDS", grade)
    assert novo["sha256"] != base["superficies"][0]["sha256"]
    mudada = {**base, "superficies": [novo]}
    _, _, est3 = gavetas.calcular_incremental(mudada, servicos, tmp_path)
    assert est3 == {"recalculados": 1, "reaproveitados": 0}


@precisa_rasterio
def test_npz_adulterado_vira_pendencia_sem_servico(tmp_path):
    base, _, _ = _base_das_cavas(tmp_path)
    arquivo = tmp_path / base["superficies"][0]["arquivo"]
    corpo = bytearray(arquivo.read_bytes())
    corpo[-1] ^= 0xFF
    arquivo.write_bytes(bytes(corpo))
    with pytest.raises(ValueError, match="sha256"):
        gavetas.ler_superficie(tmp_path, base["superficies"][0])
    servicos, pendencias = gavetas.calcular(base, tmp_path)
    assert servicos == [] and len(pendencias) == 1 and "sha256" in pendencias[0]["motivo"]
    arquivo.unlink()                                               # arquivo ausente
    assert gavetas.calcular(base, tmp_path)[0] == []
    sem_pasta, motivo = gavetas.calcular(base)                     # sem a pasta da base não há como ler
    assert sem_pasta == [] and "pasta da base" in motivo[0]["motivo"]
    sem_registro = {**base, "superficies": []}
    assert "não está na gaveta" in gavetas.calcular(sem_registro, tmp_path)[1][0]["motivo"]


@precisa_rasterio
def test_quantificar_gavetas_alerta_base_sem_marca_e_marca_fora_da_faixa():
    _, bases, cristas = _entradas()
    dados = {"bases": [{"coords": list(b["geom"].exterior.coords), "etapa": b["etapa"]} for b in bases]
             + [{"coords": list(box(200, 200, 205, 205).exterior.coords), "etapa": None}],
             "marcas_cota": [{"E": 50.0, "N": 50.0, "cota_m": 8.0}, {"E": 52.0, "N": 50.0, "cota_m": 38.75}],
             "cristas": [list(c.coords) for c in cristas], "superficie": _grade()}
    q = escavacao.quantificar_gavetas(dados)
    assert set(q) == {*escavacao.SAIDAS_CAVA, "alertas", "pontos"} and list(q["pontos"]) == ["C01"] and list(q["escavacao_cava_m3"]) == ["C01"]
    assert any("sem marca" in a for a in q["alertas"]) and any("fora da faixa" in a for a in q["alertas"])
    borda = _grade()
    borda["valido"][:, 230:] = False                               # levantamento termina em E = 57,5 m
    com_borda = escavacao.quantificar_gavetas({**dados, "superficie": borda})
    assert any("borda do levantamento" in a for a in com_borda["alertas"])


def _saida_da_escavacao():
    marcas, bases, cristas = _entradas()
    g = _grade()
    direto = escavacao.calcular(bases, marcas, cristas, g)
    campos = ("id", *escavacao.SAIDAS_CAVA.values())
    return {"marcas": marcas, "bases": bases, "cristas": cristas, "g": g, "pranchas": ["P1"],
            "resultado": {"cavas": [{k: c[k] for k in campos} for c in direto["cavas"]]}}


@precisa_rasterio
def test_etapa_das_gavetas_com_cavas_grava_a_superficie(tmp_path):
    out = tmp_path / "saida"
    out.mkdir()
    cfg = {"escavacao": {"layer_base": "BASE", "layer_marca": "COTA", "layer_crista": "CRISTA"}}
    resumo = eg.etapa(cfg, [], out, log=lambda *_: None, cavas=_saida_da_escavacao())
    assert [p.name for p in (out / "base" / "superficies").glob("*.npz")] == ["SUP-MDS.npz"]
    assert resumo["objetos_por_classe"] == {"conjunto_cavas": 1} and resumo["erros_conferencia"] == []
    assert json.loads((out / "paridade.json").read_text(encoding="utf-8")) == []
    lido = gavetas.ler(out / "base")
    assert len(lido["superficies"]) == 1 and {s["saida"] for s in lido["servicos"]} == set(escavacao.SAIDAS_CAVA)
    assert {"CV.01.C01", "CV.03.C01"} <= {n["eap"] for n in resumo["eap_html"]["nos"]}
    assert resumo["recalculados"] == 1
    outra = eg.etapa(cfg, [], out, log=lambda *_: None, cavas=_saida_da_escavacao())    # 2ª rodada: nada recalcula
    assert outra["reaproveitados"] == 1 and outra["recalculados"] == 0


def test_etapa_sem_cavas_e_sem_planilha_continua_none(tmp_path):
    assert eg.etapa({}, [], tmp_path, cavas={}) is None


def test_cada_cava_cai_no_seu_setor_pelo_ponto_do_servico():
    """Gerente (rodada 5): o conjunto de cavas é um objeto só; cada cava entra no setor pelo ponto do serviço."""
    from camadas import gavetas
    servicos = [{"servico_id": "CAVAS:cavas:escavacao_cava_m3:C01", "objeto_id": "CAVAS", "regra": "cavas",
                 "versao_regra": "1", "saida": "escavacao_cava_m3", "chave": "C01", "valor": 10.0, "unidade": "m³",
                 "fatos": [], "ponto": [5.0, 5.0]},
                {"servico_id": "CAVAS:cavas:escavacao_cava_m3:C02", "objeto_id": "CAVAS", "regra": "cavas",
                 "versao_regra": "1", "saida": "escavacao_cava_m3", "chave": "C02", "valor": 4.0, "unidade": "m³",
                 "fatos": [], "ponto": [50.0, 5.0]}]
    base = {g: [] for g in gavetas.GAVETAS}
    for sid, x0 in (("SET-A", 0.0), ("SET-B", 20.0)):
        base["objetos"].append({"objeto_id": sid, "classe": "setor"})
        base["geometria"].append({"objeto_id": sid, "tipo": "poligono", "crs_h": "EPSG:31982", "datum_v": "ortométrico",
                                  "coords": [[x0, 0], [x0 + 10, 0], [x0 + 10, 10], [x0, 10]]})
    mapa, pend = gavetas.setor_dos_servicos(base, servicos)
    assert mapa == {"CAVAS:cavas:escavacao_cava_m3:C01": "SET-A", "CAVAS:cavas:escavacao_cava_m3:C02": None} and pend == []
    grupos = {g["setor_id"]: g["nos"] for g in gavetas.para_eap_por_setor(servicos, {"CAVAS": None, **mapa}, ["SET-A", "SET-B"])}
    assert grupos["SET-A"][0]["valor"] == 10.0 and grupos[None][0]["valor"] == 4.0 and grupos["SET-B"] == []


@precisa_rasterio
def test_etapa_grava_o_crs_da_obra_na_geometria_dos_furos(tmp_path):
    """A geometria dos furos (e das redes de vala) leva a EPSG da obra, não o padrão do `de_*` (Foz é 31981): com o
    padrão 31982, os serviços complementares descartavam toda a vala por 'geometria fora do CRS da obra'."""
    out = tmp_path / "saida"
    out.mkdir()
    cfg = {"escavacao": {"layer_base": "BASE", "layer_marca": "COTA", "layer_crista": "CRISTA"}}
    furo = {"id": "SP-01", "E": 10.0, "N": 20.0, "cota_boca": 100.0}
    eg.etapa(cfg, [furo], out, log=lambda *_: None, cavas=_saida_da_escavacao(), epsg=31981)
    lido = gavetas.ler(out / "base")
    assert {g["crs_h"] for g in lido["geometria"] if g["objeto_id"] == "SP-01"} == {"EPSG:31981"}
