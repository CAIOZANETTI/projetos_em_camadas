"""F4: serviços complementares lendo e gravando nas gavetas (elementos, regras, evidências, pendências, paridade)."""

import json
import math

import numpy as np
import pytest

from camadas import associados, dimensoes, eap, gavetas, geo
from camadas import eap_preencher as ep
from camadas import gavetas_construtivos as gc
from camadas import gavetas_servicos as gs

EPSG = 31982
DOC = "003-SAA-FUNDACAO1-R2"
BLOCO_UTM = [
    [500100.0, 7000000.0],
    [500102.0, 7000000.0],
    [500102.0, 7000003.0],
    [500100.0, 7000003.0],
    [500100.0, 7000000.0],
]
EIXO_UTM = [[500200.0, 7000000.0], [500300.0, 7000000.0]]
OUTRA_PARTE_UTM = [[500300.0, 7000050.0], [500340.0, 7000050.0]]


def _lonlat(utm: list[list[float]]) -> list[list[float]]:
    pts = np.asarray(utm, float)
    lon, lat = geo.para_lonlat(pts[:, 0], pts[:, 1], EPSG)
    return np.column_stack([lon, lat]).tolist()


def _feature(
    identificador, classe, geometria, atributos, unidade="u1", sistema="FILTROS"
):
    return {
        "type": "Feature",
        "geometry": geometria,
        "properties": {
            "id": identificador,
            "rotulo": identificador,
            "classe": classe,
            "unidade": unidade,
            "sistema": f"{unidade}-{sistema}",
            "etapa": None,
            "atributos": atributos,
            "fonte": f"fundação {DOC} (camadas.prancha)",
            "doc": DOC,
        },
    }


def _bloco(identificador="u1-FILTROS-bloco-PC6", topo=237.317, arrasamento=236.667):
    atributos = [["Estacas", 4]]
    if topo is not None:
        atributos.append(["Face superior (cota, m)", topo])
    if arrasamento is not None:
        atributos.append(["Arrasamento (cota, m)", arrasamento])
    geometria = {"type": "Polygon", "coordinates": [_lonlat(BLOCO_UTM)]}
    return _feature(identificador, "bloco", geometria, atributos)


def _estaca(identificador="u1-FILTROS-estaca-E1", comprimento=6.0):
    atributos = [["Diâmetro nominal (cm)", 40.0]]
    if comprimento is not None:
        atributos.append(["Comprimento (m)", comprimento])
    ponto = {"type": "Point", "coordinates": _lonlat([[500101.0, 7000001.0]])[0]}
    return _feature(identificador, "estaca", ponto, atributos)


def _pilar(identificador="u1-FILTROS-pilar-P1"):
    geometria = {"type": "Polygon", "coordinates": [_lonlat(BLOCO_UTM)]}
    return _feature(identificador, "pilar", geometria, [["Lado (m)", 0.41]])


def _trecho(identificador="u2-AAT00-trecho-t1", material=True, partes=1):
    atributos = [
        ["Diâmetro (mm)", 315],
        ["Extensão estimada (m)", 100.0],
        ["Pista (leito carroçável) (m)", 60.0],
        ["Calçada (passeio) (m)", 40.0],
    ]
    if material:
        atributos.append(
            [
                "Item do contrato",
                "301218 · TUBO POLIETILENO PE 100 PN10 (BARRA COM 6,0 M) DE 315",
            ]
        )
    if partes == 1:
        geometria = {"type": "LineString", "coordinates": _lonlat(EIXO_UTM)}
    else:
        geometria = {
            "type": "MultiLineString",
            "coordinates": [_lonlat(EIXO_UTM), _lonlat(OUTRA_PARTE_UTM)],
        }
    return _feature(
        identificador, "trecho", geometria, atributos, unidade="u2", sistema="AAT00"
    )


def _base(*features) -> dict:
    construtivos = {
        "geojson": {"type": "FeatureCollection", "features": list(features)}
    }
    return gc.de_construtivos(construtivos, [], {}, EPSG)


def _servicos(resultado: dict, objeto_id: str, regra: str) -> list[dict]:
    return [
        s
        for s in resultado["servicos"]
        if s["objeto_id"] == objeto_id and s["regra"] == f"associado:{regra}"
    ]


def _unico(resultado: dict, objeto_id: str, regra: str) -> dict:
    achados = _servicos(resultado, objeto_id, regra)
    assert len(achados) == 1, achados
    return achados[0]


# --- o mapeamento propriedade da gaveta → dimensão ------------------------------------------------------------------


def test_mapa_de_dimensoes_segue_os_rotulos_da_extracao():
    assert gs.MAPA_DE_DIMENSOES["estaca"] == {
        "d": ("diametro_m", pytest.approx(1.0)),
        "L": ("comprimento_m", 1.0),
    }
    assert gs.MAPA_DE_DIMENSOES["bloco"] == {
        "A": ("area_planta_m2", 1.0),
        "P": ("perimetro_m", 1.0),
        "face": ("cota_topo_m", 1.0),
        "arr": ("cota_arrasamento_m", 1.0),
    }
    # o lado e a altura do pilar não têm rótulo na extração: ficam fora, nunca como zero
    assert gs.MAPA_DE_DIMENSOES["pilar"] == {}
    todas = {p for m in gs.MAPA_DE_DIMENSOES.values() for p, _ in m.values()}
    assert todas <= set(gavetas.REGRAS["propriedades"])


# --- elementos -------------------------------------------------------------------------------------------------------


def test_elemento_do_bloco_vem_dos_fatos_e_da_geometria_das_gavetas():
    base = _base(_bloco())
    el, cava = gs.elementos(base, EPSG)
    assert (el["tipo"], el["objeto_id"], el["base"], el["item"]) == (
        "bloco",
        "u1-FILTROS-bloco-PC6",
        "U1.FILTROS",
        "GEO.FUN.BLO",
    )
    assert el["dims"]["A"] == pytest.approx(6.0) and el["dims"]["P"] == pytest.approx(
        10.0
    )
    assert el["dims"]["h"] == pytest.approx(237.317 - 236.667 + 0.05)
    assert el["dims"]["V"] == pytest.approx(6.0 * 0.7)
    assert el["faltando"] == []
    assert cava["tipo"] == "cava_fundacao" and cava["id"].endswith(" · cava_fundacao")
    folga = dimensoes.TIPOS["cava_fundacao"]["premissas"]["f"]
    assert cava["dims"]["A"] == pytest.approx(6.0) and "f" in cava["dims"] and folga


def test_elemento_sem_dimensao_fica_com_faltando():
    base = _base(_bloco(topo=None))
    el = gs.elementos(base, EPSG)[0]
    assert "face" in el["faltando"] and "h (falta face)" in el["faltando"]
    assert "V" not in el["dims"]


def test_trecho_vira_um_elemento_de_vala_por_superficie():
    base = _base(_trecho())
    vala = [e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala"]
    assert sorted(e["chave"] for e in vala) == ["calcada", "pista"]
    assert {e["objeto_id"] for e in vala} == {"u2-AAT00-trecho-t1"}
    pista = next(e for e in vala if e["chave"] == "pista")
    assert pista["dims"]["L"] == pytest.approx(60.0)
    assert pista["base"] == "U2.AAT00" and pista["metodo"] == "mos_sanepar"


# --- complementares --------------------------------------------------------------------------------------------------


def test_estaca_gera_concreto_armadura_e_arrasamento_com_o_codigo_da_eap_unica():
    base = _base(_estaca())
    r = gs.complementares(base, EPSG)
    volume = math.pi * 0.4**2 / 4 * 6.0
    concreto = _unico(r, "u1-FILTROS-estaca-E1", "concreto")
    assert concreto["valor"] == pytest.approx(volume, abs=1e-6)
    assert (concreto["unidade"], concreto["saida"], concreto["servicos_eap"]) == (
        "m³",
        "concreto",
        ["concreto"],
    )
    assert concreto["codigo_eap"] == "U1.FILTROS.GEO.FUN.EST"
    assert concreto["servico_id"] == "u1-FILTROS-estaca-E1.concreto"
    assert concreto["fatos"] == [
        "u1-FILTROS-estaca-E1.comprimento_m",
        "u1-FILTROS-estaca-E1.diametro_m",
    ]
    armadura = _unico(r, "u1-FILTROS-estaca-E1", "armadura")
    assert (
        armadura["valor"] == pytest.approx(40.0 * volume, abs=1e-6)
        and armadura["unidade"] == "kg"
    )
    assert _unico(r, "u1-FILTROS-estaca-E1", "arrasamento")["valor"] == 1.0
    # arrasamento não depende de dimensão: não cita fato
    assert _unico(r, "u1-FILTROS-estaca-E1", "arrasamento")["fatos"] == []


def test_bloco_gera_forma_lastro_e_a_cava_com_os_fatos_que_cada_valor_usa():
    base = _base(_bloco())
    r = gs.complementares(base, EPSG)
    oid = "u1-FILTROS-bloco-PC6"
    assert _unico(r, oid, "forma")["valor"] == pytest.approx(10.0 * 0.7, abs=1e-6)
    assert _unico(r, oid, "lastro")["valor"] == pytest.approx(6.0 * 0.05, abs=1e-6)
    escavacao = _unico(r, oid, "escavacao_cava")
    assert (escavacao["codigo_eap"], escavacao["servicos_eap"], escavacao["saida"]) == (
        "U1.FILTROS.GEO.MOV.ESC",
        [],
        "escavacao_cava",
    )
    assert _unico(r, oid, "reaterro_cava")["codigo_eap"] == "U1.FILTROS.GEO.MOV.REA"
    # o lastro depende só da área; a forma, do perímetro, da cota do topo e do arrasamento
    assert _unico(r, oid, "lastro")["fatos"] == [f"{oid}.area_planta_m2"]
    assert _unico(r, oid, "forma")["fatos"] == [
        f"{oid}.cota_arrasamento_m",
        f"{oid}.cota_topo_m",
        f"{oid}.perimetro_m",
    ]


def test_sem_dimensao_o_servico_nao_sai_e_a_pendencia_diz_o_que_faltou():
    base = _base(_bloco(topo=None), _estaca(comprimento=None), _pilar())
    r = gs.complementares(base, EPSG)
    assert not _servicos(r, "u1-FILTROS-bloco-PC6", "concreto")
    assert not _servicos(r, "u1-FILTROS-estaca-E1", "concreto")
    assert not _servicos(r, "u1-FILTROS-pilar-P1", "concreto")
    assert all(s["valor"] > 0 for s in r["servicos"])  # nunca zero inventado
    pendencias = {(p["objeto_id"], p["motivo"]): p["detalhe"] for p in r["pendencias"]}
    detalhe = pendencias[("u1-FILTROS-bloco-PC6", "serviço sem valor: concreto")]
    assert detalhe.startswith("falta V ← h ← face")
    assert pendencias[
        ("u1-FILTROS-estaca-E1", "serviço sem valor: concreto")
    ].startswith("falta V ← L")
    assert ("u1-FILTROS-pilar-P1", "serviço sem valor: concreto") in pendencias
    # o que o bloco sem topo ainda tem: o lastro só precisa da área
    assert _unico(r, "u1-FILTROS-bloco-PC6", "lastro")["valor"] > 0


def test_objeto_sem_unidade_e_sistema_vira_pendencia():
    base = _base(_estaca())
    base["objetos"][0].pop("unidade"), base["objetos"][0].pop("sistema")
    base["fatos"] = [
        f for f in base["fatos"] if f["propriedade"] not in ("unidade", "sistema")
    ]
    r = gs.complementares(base, EPSG)
    assert r["servicos"] == []
    assert r["pendencias"] == [
        {
            "objeto_id": "u1-FILTROS-estaca-E1",
            "motivo": "unidade e sistema não definidos: sem serviço complementar",
        }
    ]


def test_geometria_em_outro_crs_nao_vira_servico():
    base = _base(_bloco())
    r = gs.complementares(base, 31981)
    assert r["servicos"] == []
    assert (
        r["pendencias"][0]["motivo"]
        == "geometria fora do CRS da obra: sem serviço complementar"
    )


def test_evidencia_do_servico_traz_a_memoria_e_as_premissas():
    base = _base(_bloco())
    r = gs.complementares(base, EPSG)
    oid = "u1-FILTROS-bloco-PC6"
    armadura = _unico(r, oid, "armadura")
    ev = next(
        e for e in r["evidencias"] if e["evidencia_id"] == armadura["evidencia_id"]
    )
    assert (ev["classe"], ev["executor"], ev["metodo"]) == (
        "associado",
        "código",
        "camadas.associados",
    )
    assert ev["localizador"] == {"regra": "armadura", "objeto_id": oid}
    assert "taxa * V" in ev["trecho"] and "V = A * h" in ev["trecho"]
    assert any(p.startswith("taxa = 80.0 kg/m³ (calibrar:") for p in ev["premissas"])
    assert any(p.startswith("emb = 0.05 (premissa:") for p in ev["premissas"])
    assert len(r["evidencias"]) == len(r["servicos"])


def test_versao_da_regra_e_o_hash_do_json():
    regra = associados.REGRAS[0]
    assert gs.versao_da_regra(regra) == gs.VERSOES[regra["id"]]
    assert len(gs.versao_da_regra(regra)) == 12
    assert gs.versao_da_regra({**regra, "formula": "2 * V"}) != gs.versao_da_regra(
        regra
    )
    base = _base(_estaca())
    versoes = {
        s["regra"]: s["versao_regra"] for s in gs.complementares(base, EPSG)["servicos"]
    }
    assert versoes["associado:concreto"] == gs.VERSOES["concreto"]


def test_com_complementares_passa_na_conferencia_das_gavetas_e_nao_altera_a_original():
    base = _base(_bloco(), _estaca(), _trecho())
    antes = json.dumps(base, sort_keys=True, default=str)
    nova, erros = gs.com_complementares(base, EPSG)
    assert erros == []
    assert json.dumps(base, sort_keys=True, default=str) == antes
    assert len(nova["servicos"]) > 0 and len(nova["evidencias"]) > len(
        base["evidencias"]
    )
    ids = [s["servico_id"] for s in nova["servicos"]]
    assert len(ids) == len(set(ids))
    obrigatorios = gavetas.REGRAS["gavetas"]["servicos"]["obrigatorios"]
    assert all(
        s.get(c) not in (None, "")
        for s in nova["servicos"]
        for c in obrigatorios
        if c != "fatos"
    )


def test_complementares_e_deterministico():
    base = _base(_bloco(), _estaca(), _trecho())
    a, b = gs.complementares(base, EPSG), gs.complementares(base, EPSG)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_codigo_eap_e_um_item_tecnico_da_eap_instanciada():
    validos = {n["codigo"] for n in eap.estrutura() if n["nivel"] == "item"}
    r = gs.complementares(_base(_bloco(), _estaca(), _trecho()), EPSG)
    assert r["servicos"] and all(s["codigo_eap"] in validos for s in r["servicos"])
    assert r["resumo"]["sem_codigo_eap"] == 0


# --- vala (trecho) ---------------------------------------------------------------------------------------------------


def test_trecho_gera_a_vala_por_superficie_com_demolicao_e_recomposicao_por_pavimento():
    base = _base(_trecho())
    r = gs.complementares(base, EPSG)
    oid = "u2-AAT00-trecho-t1"
    por_codigo = {}
    for s in r["servicos"]:
        por_codigo.setdefault(
            (s["codigo_eap"], s["servicos_eap"][0] if s["servicos_eap"] else ""), 0.0
        )
        por_codigo[
            (s["codigo_eap"], s["servicos_eap"][0] if s["servicos_eap"] else "")
        ] += s["valor"]
    assert por_codigo[("U2.AAT00.CIV.PAV.REC", "corte_pavimento")] > 0
    assert por_codigo[("U2.AAT00.CIV.PAV.CAL", "corte_pavimento")] > 0
    # a pista (60 m) e a calçada (40 m) do trecho, cada uma com a sua recomposição
    assert (
        por_codigo[("U2.AAT00.CIV.PAV.REC", "recomposicao")]
        > por_codigo[("U2.AAT00.CIV.PAV.CAL", "recomposicao")] * 0.5
    )
    assert por_codigo[("U2.AAT00.HID.TUB.RED", "assentamento")] == pytest.approx(100.0)
    for servico in ("escavacao", "berco", "envoltoria", "reaterro", "bota_fora"):
        assert por_codigo[("U2.AAT00.GEO.MOV.VAL", servico)] > 0
    assert {s["chave"] for s in r["servicos"] if s["objeto_id"] == oid} == {
        "pista",
        "calcada",
    }
    # a vala por superfície: o mesmo objeto e a mesma regra, ids separados pela superfície
    escavacoes = _servicos(r, oid, "escavacao_vala")
    assert sorted(s["servico_id"] for s in escavacoes) == [
        f"{oid}.escavacao_vala.calcada",
        f"{oid}.escavacao_vala.pista",
    ]
    assert all("dn_mm" in " ".join(s["fatos"]) for s in escavacoes)


def test_trecho_sem_material_nao_inventa_a_largura():
    base = _base(_trecho(material=False))
    r = gs.complementares(base, EPSG)
    oid = "u2-AAT00-trecho-t1"
    assert not _servicos(
        r, oid, "escavacao_vala"
    )  # sem a largura da vala (MOS) não há escavação
    assert _servicos(r, oid, "assentamento")  # o que não depende dela sai
    motivos = {p["motivo"] for p in r["pendencias"] if p["objeto_id"] == oid}
    assert "serviço sem valor: escavacao_vala" in motivos


def test_trecho_sem_diametro_nao_gera_vala():
    base = _base(_trecho())
    base["fatos"] = [f for f in base["fatos"] if f["propriedade"] != "dn_mm"]
    r = gs.complementares(base, EPSG)
    assert r["servicos"] == []
    assert any("sem diâmetro" in p["motivo"] for p in r["pendencias"])


def test_eixo_de_varias_partes_fica_na_gaveta_e_a_vala_usa_todas():
    base = _base(_trecho(partes=2))
    fatos = {
        f["propriedade"]: f["valor"]
        for f in base["fatos"]
        if f["objeto_id"] == "u2-AAT00-trecho-t1"
    }
    assert len(fatos["eixo_partes"]) == 2
    assert fatos["pavimentos"] == {"pista": 60.0, "calcada": 40.0}
    trecho, motivos = gs._trecho(
        base["objetos"][0],
        {k: {"valor": v, "fato_id": k} for k, v in fatos.items()},
        {"tipo": "linha", "coords": EIXO_UTM},
        fatos["eixo_partes"],
    )
    assert motivos == [] and trecho["geometria"].geom_type == "MultiLineString"
    assert trecho["geometria"].length == pytest.approx(140.0, abs=0.01)


def test_extracao_fecha_as_lacunas_do_trecho():
    base = _base(_trecho(), _bloco())
    fatos = {
        f["propriedade"]: f
        for f in base["fatos"]
        if f["objeto_id"] == "u2-AAT00-trecho-t1"
    }
    assert fatos["pavimentos"]["valor"] == {"pista": 60.0, "calcada": 40.0}
    assert fatos["material"]["valor"].startswith("301218 · TUBO POLIETILENO PE 100")
    assert (
        "eixo_partes" not in fatos
    )  # linha única: a gaveta geometria já tem o eixo inteiro
    pendencias = [
        p["motivo"]
        for p in base["pendencias"]
        if p["objeto_id"] == "u2-AAT00-trecho-t1"
    ]
    assert not any(
        "Pista" in m or "Calçada" in m or "Item do contrato" in m for m in pendencias
    )
    assert gavetas.conferir_base(base) == []


# --- paridade com o caminho atual -----------------------------------------------------------------------------------


def _csv(caminho, linhas):
    cabecalho = (
        "unidade;item;servico;unidade_medida;quantidade;n_elementos;regras;situacao"
    )
    corpo = [
        f"{u};{i};{s};{m};{str(q).replace('.', ',')};1;[];x" for u, i, s, m, q in linhas
    ]
    caminho.write_text("﻿" + "\n".join([cabecalho, *corpo]) + "\n", encoding="utf-8")
    return caminho


def test_paridade_sem_diferenca(tmp_path):
    r = gs.complementares(_base(_bloco(), _estaca(), _trecho()), EPSG)
    arquivo = _csv(
        tmp_path / "associados.csv",
        [
            (*chave, round(valor, 3))
            for chave, valor in sorted(gs.somas(r["servicos"]).items())
        ],
    )
    assert gs.paridade(r["servicos"], arquivo) == []


def test_paridade_aponta_falta_sobra_e_diferenca(tmp_path):
    r = gs.complementares(_base(_estaca()), EPSG)
    volume = math.pi * 0.4**2 / 4 * 6.0
    arquivo = _csv(
        tmp_path / "associados.csv",
        [
            ("U1", "GEO.FUN.EST", "concreto", "m³", round(volume + 0.5, 3)),
            ("U1", "GEO.FUN.EST", "forma", "m²", 1.0),
        ],
    )
    diferencas = gs.paridade(r["servicos"], arquivo)
    assert any(
        d.startswith("U1/GEO.FUN.EST/concreto/m³: gavetas") and "diferença -0.500" in d
        for d in diferencas
    )
    assert "U1/GEO.FUN.EST/forma/m²: falta nas gavetas (csv 1.000)" in diferencas
    assert any(
        d.startswith("U1/GEO.FUN.EST/armadura/kg: só nas gavetas") for d in diferencas
    )


def test_paridade_tolera_o_arredondamento_do_csv(tmp_path):
    r = gs.complementares(_base(_estaca()), EPSG)
    volume = math.pi * 0.4**2 / 4 * 6.0
    linhas = [
        ("U1", "GEO.FUN.EST", "concreto", "m³", round(volume, 3)),
        ("U1", "GEO.FUN.EST", "armadura", "kg", round(40 * volume, 3)),
        ("U1", "GEO.FUN.EST", "arrasamento", "un", 1.0),
    ]
    assert gs.paridade(r["servicos"], _csv(tmp_path / "a.csv", linhas)) == []


# --- entrada nas folhas da EAP única ---------------------------------------------------------------------------------


def _folha(resultado: dict, folha_id: str) -> dict:
    return next(
        f
        for t in resultado["tipos"].values()
        for e in t["etapas"]
        for f in e["folhas"]
        if f["id"] == folha_id
    )


def test_complementares_entram_nas_folhas_que_apontam_o_servico():
    base = _base(_bloco(), _estaca())
    nova, erros = gs.com_complementares(base, EPSG)
    assert erros == []
    r = ep.preencher(nova)
    for folha, servico, grandeza in (
        ("OP.04.07", "concreto", "m³"),
        ("OP.04.06", "armadura", "kg"),
        ("OP.04.05", "forma", "m²"),
        ("OP.03.06", "lastro", "m³"),
        ("OP.03.02", "arrasamento", "un"),
    ):
        f = _folha(r, folha)
        assert f["situacao"] == "calculada", folha
        assert {q["unidade"] for q in f["quantidades"]} == {grandeza}
        assert all(q["origem"] == "servico" and q["servicos"] for q in f["quantidades"])
        assert all(
            q["codigo_eap"].startswith(f"{folha}/U1.FILTROS.") for q in f["quantidades"]
        )
    concreto = _folha(r, "OP.04.07")["quantidades"]
    assert {q["codigo_eap"] for q in concreto} == {
        "OP.04.07/U1.FILTROS.GEO.FUN.BLO",
        "OP.04.07/U1.FILTROS.GEO.FUN.EST",
    }
    # sem cava medida pelos fatos, a escavação e o reaterro da cava do bloco entram na folha da cava
    assert r["servicos_descartados"] == []
    assert _folha(r, "OP.02.01")["situacao"] == "calculada"
    assert _folha(r, "OP.02.04")["situacao"] == "calculada"


def test_cada_servico_complementar_cita_fatos_que_existem_na_base():
    base = _base(_bloco(), _estaca(), _trecho())
    nova, _ = gs.com_complementares(base, EPSG)
    fatos = {f["fato_id"] for f in nova["fatos"]}
    for s in nova["servicos"]:
        assert set(s["fatos"]) <= fatos
        ev = next(
            e for e in nova["evidencias"] if e["evidencia_id"] == s["evidencia_id"]
        )
        assert ev["classe"] == "associado"


def test_metadados_citam_as_funcoes_e_o_mapa():
    m = gs.metadados()
    assert {"elementos", "complementares", "paridade"} <= set(m["funcoes"])
    assert m["mapa_de_dimensoes"]["estaca"] == ["L", "d"]
