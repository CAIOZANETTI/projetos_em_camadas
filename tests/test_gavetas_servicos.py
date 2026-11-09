"""F4: serviços complementares lendo e gravando nas gavetas (elementos, regras, evidências, pendências, paridade)."""

import json
import math

import numpy as np
import pytest

from camadas import associados, dimensoes, eap, gavetas, geo, valas
from camadas import eap_preencher as ep
from camadas import extrair_gavetas as eg
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


def _rede(n=100, classes=None, pts=None, id="AAT00", de_mm=315, material=None):
    """Rede `AAT00` (u2) com `n` amostras de 1 m, 60 de pista e o resto de calçada. Padrão: um vértice por amostra num
    eixo reto de `n` m (como a extração grava); `pts` troca os vértices."""
    classes = classes or ["pista"] * 60 + ["calcada"] * (n - 60)
    if pts is None:
        pts = np.c_[500200.0 + np.linspace(0, n, n), np.full(n, 7000000.0)]
    return {
        "id": id,
        "de_mm": de_mm,
        "material_declarado": material,
        "fonte_de": "teste",
        "criterio": "divisas",
        "pranchas": ["P1"],
        "layers": ["TUBO"],
        "extensao_m": float(n),
        "pts": pts,
        "tang": np.tile([1.0, 0.0], (n, 1)),
        "peso": np.ones(n),
        "classes": classes,
        "finais": None,
        "quadro": [],
    }


FUROS = [
    {
        "id": "SP-A",
        "E": 500210.0,
        "N": 7000010.0,
        "na_m": 9.0,
        "camadas": [{"de": 0, "ate": 5, "descricao": "argila"}],
    },
    {
        "id": "SP-B",
        "E": 500290.0,
        "N": 7000010.0,
        "na_m": 1.0,
        "camadas": [{"de": 0, "ate": 5, "descricao": "argila"}],
    },
]
RV = "RV-AAT00"
TRECHO = "u2-AAT00-trecho-t1"


def _base_rede(*features, rede=None, furos=FUROS) -> dict:
    """Rede + furos + os objetos construtivos dados (o trecho traz o material, o diâmetro e a extensão)."""
    partes = [eg.de_valas([rede or _rede()]), _base(*features)]
    return eg.juntar(
        *partes, *([eg.de_sondagens(furos, "sondagens.json")] if furos else [])
    )


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


def test_rede_vira_um_elemento_de_vala_por_classe_e_furo_mais_proximo():
    base = _base_rede(_trecho())
    vala = [e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala"]
    # amostra a amostra: x < 50 m → SP-A, x >= 50 m → SP-B (a pista vai até 60 m)
    metros = {(e["chave"], e["id"].split(" · ")[2]): e["dims"]["L"] for e in vala}
    assert metros == {
        ("pista", "SP-A"): pytest.approx(50.0),
        ("pista", "SP-B"): pytest.approx(10.0),
        ("calcada", "SP-B"): pytest.approx(40.0),
    }
    assert {e["objeto_id"] for e in vala} == {RV}  # o trecho não gera elemento de vala
    pista = next(e for e in vala if e["chave"] == "pista" and "SP-A" in e["id"])
    assert pista["base"] == "U2.AAT00" and pista["metodo"] == "mos_sanepar"
    assert (
        "RV-AAT00.pesos_m" in pista["rastro"]["L"]
        and "SP-A.camadas" in pista["rastro"]["L"]
    )


def test_material_da_rede_vem_do_trecho_do_mesmo_sistema_e_o_fato_entra_no_rastro():
    base = _base_rede(_trecho())
    material = next(
        f
        for f in base["fatos"]
        if f["objeto_id"] == TRECHO and f["propriedade"] == "material"
    )
    el = next(e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala")
    assert material["fato_id"] in el["rastro"]["b"]
    assert not any("material do tubo não identificado" in a for a in el["alertas"])


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


# --- vala (rede) -----------------------------------------------------------------------------------------------------


def _por_codigo(servicos: list[dict]) -> dict[tuple, float]:
    saida: dict[tuple, float] = {}
    for s in servicos:
        chave = (s["codigo_eap"], s["servicos_eap"][0] if s["servicos_eap"] else "")
        saida[chave] = saida.get(chave, 0.0) + s["valor"]
    return saida


def test_rede_gera_a_vala_sem_repetir_demolicao_recomposicao_e_escavacao_da_vala_rede():
    r = gs.complementares(_base_rede(_trecho()), EPSG)
    por_codigo = _por_codigo(r["servicos"])
    assert por_codigo[("U2.AAT00.CIV.PAV.REC", "corte_pavimento")] > 0
    assert por_codigo[("U2.AAT00.CIV.PAV.CAL", "corte_pavimento")] > 0
    assert por_codigo[("U2.AAT00.HID.TUB.RED", "assentamento")] == pytest.approx(100.0)
    for servico in ("berco", "envoltoria", "reaterro", "bota_fora", "esgotamento"):
        assert por_codigo[("U2.AAT00.GEO.MOV.VAL", servico)] > 0
    # o que a regra `vala_rede` já dá nem é calculado aqui
    assert gs.SERVICOS_DA_VALA_REDE == {"demolicao", "recomposicao", "escavacao"}
    assert gs.REGRAS_JA_DA_VALA_REDE == {
        "demolicao_pavimento",
        "volume_demolido",
        "recomposicao_pavimento",
        "escavacao_vala",
    }
    regras = {s["regra"].removeprefix("associado:") for s in r["servicos"]}
    assert not regras & gs.REGRAS_JA_DA_VALA_REDE
    assert not any("escavacao_vala" in p["motivo"] for p in r["pendencias"])
    assert {s["objeto_id"] for s in r["servicos"]} == {RV}
    assert {s["chave"] for s in r["servicos"]} == {"pista", "calcada"}
    # uma classe com dois furos soma num serviço só, com os fatos dos dois furos
    berco = _servicos(r, RV, "berco")
    pista = next(s for s in berco if s["chave"] == "pista")
    assert {"SP-A.camadas", "SP-B.camadas"} <= set(pista["fatos"])
    assert any(f.startswith(f"{TRECHO}.material") for f in pista["fatos"])


def test_zero_caminho_paralelo_cada_codigo_e_servico_vem_de_uma_regra_so():
    base = _base_rede(_trecho())
    primarios, _ = gavetas.calcular(base)
    mapa, pend = gavetas.unidade_sistema(
        base, gavetas.indice(base), {}, None, primarios
    )
    gavetas.anotar_codigo_eap(primarios, mapa, pend)
    complementares = gs.complementares(base, EPSG)
    todos = [*primarios, *complementares["servicos"]]
    regras: dict[tuple, set] = {}
    for s in todos:
        for nome in s["servicos_eap"] or [s["saida"]]:
            regras.setdefault((s["codigo_eap"], nome), set()).add(
                s["regra"].split(":")[-1]
            )
    assert {k: v for k, v in regras.items() if len(v) > 1} == {}
    assert (
        "U2.AAT00.GEO.MOV.VAL",
        "escavacao",
    ) in regras  # a escavação da vala é só da vala_rede
    assert regras[("U2.AAT00.GEO.MOV.VAL", "escavacao")] == {"vala_rede"}
    assert any(s["regra"] == "vala_rede" for s in todos)
    assert all(
        e["objeto_id"] == RV for e in gs.elementos(base, EPSG) if e["tipo"] == "vala"
    )
    nova = gs._somar({**base, "servicos": primarios}, complementares)
    assert ep.preencher(nova)["servicos_descartados"] == []


def test_trecho_sem_rede_do_mesmo_sistema_vira_pendencia_e_nao_gera_vala():
    base = _base(_trecho())
    r = gs.complementares(base, EPSG)
    assert r["servicos"] == []
    assert [(p["objeto_id"], p["motivo"]) for p in r["pendencias"]] == [
        (TRECHO, gs.MOTIVO_SEM_REDE)
    ]
    assert gs.MOTIVO_SEM_REDE == "sem rede de vala (vala_rede): a vala não sai"


def test_rede_sem_material_usa_a_premissa_da_vala_rede_com_alerta_e_premissa_na_evidencia():
    base = _base_rede(rede=_rede())
    r = gs.complementares(base, EPSG)
    assert _servicos(
        r, RV, "berco"
    )  # a largura sai pelo material de premissa (FD), a mesma da vala_rede
    assert _servicos(r, RV, "assentamento")
    assert not any(
        p["motivo"].startswith("serviço sem valor")
        for p in r["pendencias"]
        if p["objeto_id"] == RV
    )
    motivos = {p["motivo"] for p in r["pendencias"] if p["objeto_id"] == RV}
    assert (
        f"material de premissa ({valas.MATERIAL_PADRAO}): confirmar o tipo do tubo no contrato"
        in motivos
    )
    evidencias = {e["evidencia_id"]: e for e in r["evidencias"]}
    berco = _servicos(r, RV, "berco")[0]
    assert any(
        "premissa" in p and "material do tubo" in p
        for p in evidencias[berco["evidencia_id"]]["premissas"]
    )


def test_material_do_fato_da_rede_vale_mais_que_o_do_trecho():
    rede = _rede(de_mm=315, material="TUBO FD DN 300")
    base = _base_rede(_trecho(), rede=rede)  # o trecho do sistema diz PEAD
    el = next(e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala")
    fato = next(
        f
        for f in base["fatos"]
        if f["objeto_id"] == RV and f["propriedade"] == "material"
    )
    assert fato["fato_id"] in el["rastro"]["b"]
    largura_fd = valas.secao("pista", 0.315, "FD", 315)[0]
    assert el["dims"]["b"] == pytest.approx(largura_fd, abs=1e-6)


def test_largura_da_demolicao_da_vala_rede_e_a_dos_elementos_dos_complementares():
    redes = [
        _rede(id="AAT00", de_mm=450, material="TUBO POLIETILENO PE 100 DE 450"),
        _rede(
            id="AAT01", de_mm=400, material=None
        ),  # sem material: premissa FD nos dois cálculos
    ]
    base = eg.juntar(
        eg.de_valas(redes),
        eg.de_sondagens(FUROS, "sondagens.json"),
    )
    assert valas.secao("pista", 0.45, "FD", 450)[0] != pytest.approx(
        valas.secao("pista", 0.45, "TUBO POLIETILENO PE 100 DE 450", 450)[0]
    )
    vala = [e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala"]
    assert {e["objeto_id"] for e in vala} == {"RV-AAT00", "RV-AAT01"}
    for rede in redes:
        oid, de_m = f"RV-{rede['id']}", rede["de_mm"] / 1000
        material, _ = valas.material_da_rede(rede["material_declarado"])
        quadro = valas.quantificar(
            rede["classes"],
            np.asarray(rede["peso"], float),
            de_m,
            None,
            rede["material_declarado"],
        )
        largura_da_demolicao = {q["classe"]: q["largura_m"] for q in quadro}
        proprios = [e for e in vala if e["objeto_id"] == oid]
        assert {e["chave"] for e in proprios} == set(largura_da_demolicao)
        for e in proprios:
            esperada = valas.secao(e["chave"], de_m, material, rede["de_mm"])[0]
            assert e["dims"]["b"] == pytest.approx(esperada, abs=1e-6)
            assert round(e["dims"]["b"], 2) == pytest.approx(
                largura_da_demolicao[e["chave"]], abs=1e-6
            )


def test_rede_sem_diametro_nao_gera_vala():
    base = _base_rede(_trecho())
    base["fatos"] = [
        f
        for f in base["fatos"]
        if not (f["objeto_id"] == RV and f["propriedade"] == "de_mm")
    ]
    r = gs.complementares(base, EPSG)
    assert r["servicos"] == []
    assert any("sem diâmetro" in p["motivo"] for p in r["pendencias"])


def test_um_vertice_por_amostra_posiciona_cada_amostra_mesmo_com_saltos_no_eixo():
    # as 40 amostras da calçada ficam 5 km ao norte (o eixo da extração junta partes distantes): o comprimento do eixo
    # não confere com os pesos, mas há um vértice por amostra e o furo de cada uma sai do seu ponto
    pts = np.c_[500200.0 + np.linspace(0, 100, 100), np.full(100, 7000000.0)]
    pts[60:, 1] += 5000.0
    base = _base_rede(_trecho(), rede=_rede(pts=pts))
    r = gs.complementares(base, EPSG)
    vala = [e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala"]
    assert {(e["chave"], e["id"].split(" · ")[2]) for e in vala} == {
        ("pista", "SP-A"),
        ("pista", "SP-B"),
        ("calcada", "sem furo"),
    }
    assert not any("não confere" in p["motivo"] for p in r["pendencias"])


def test_eixo_sem_vertice_por_amostra_que_nao_confere_com_os_pesos_usa_um_furo_so_e_avisa():
    pts = np.c_[
        500200.0 + np.linspace(0, 80, 5), np.full(5, 7000000.0)
    ]  # 5 vértices, 100 amostras, 80 m
    base = _base_rede(_trecho(), rede=_rede(pts=pts))
    vala = [e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala"]
    assert sorted(e["chave"] for e in vala) == ["calcada", "pista"]
    assert len({e["id"].split(" · ")[2] for e in vala}) == 1
    r = gs.complementares(base, EPSG)
    assert any(
        "não confere com a soma dos pesos" in p["motivo"] for p in r["pendencias"]
    )


def test_sem_vertice_por_amostra_o_eixo_que_confere_posiciona_pela_distancia_acumulada():
    pts = np.c_[
        500200.0 + np.linspace(0, 100, 5), np.full(5, 7000000.0)
    ]  # 5 vértices, 100 amostras, 100 m
    vala = gs.elementos(_base_rede(_trecho(), rede=_rede(pts=pts)), EPSG)
    metros = {
        (e["chave"], e["id"].split(" · ")[2]): e["dims"]["L"]
        for e in vala
        if e["tipo"] == "vala"
    }
    assert metros == {
        ("pista", "SP-A"): pytest.approx(50.0),
        ("pista", "SP-B"): pytest.approx(10.0),
        ("calcada", "SP-B"): pytest.approx(40.0),
    }


def test_sem_furo_no_raio_o_grupo_fica_sem_sondagem_e_o_alerta_diz_a_distancia():
    longe = [{**FUROS[0], "E": 600000.0, "N": 7100000.0}]
    r = gs.complementares(_base_rede(_trecho(), furos=longe), EPSG)
    assert any("nenhuma sondagem a até" in p["motivo"] for p in r["pendencias"])
    assert _servicos(r, RV, "berco")  # a vala sai; solo e NA ficam sem informação


def test_amostra_de_classe_desconhecida_fica_de_fora_com_aviso():
    classes = ["pista"] * 60 + ["lunar"] * 40
    r = gs.complementares(_base_rede(_trecho(), rede=_rede(classes=classes)), EPSG)
    assert any("ficam fora da vala" in p["motivo"] for p in r["pendencias"])
    assert {s["chave"] for s in r["servicos"]} == {"pista"}


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
        f"{u};{i};{s};{m};{str(q).replace('.', ',')};1;{(regras or ['[]'])[0]};x"
        for u, i, s, m, q, *regras in linhas
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


def test_paridade_deixa_a_vala_de_fora_e_a_vala_e_contada_a_parte(tmp_path):
    r = gs.complementares(_base_rede(_trecho(), _estaca()), EPSG)
    construtivos = [
        (*chave, round(valor, 3))
        for chave, valor in sorted(gs.somas(r["servicos"], False).items())
    ]
    assert construtivos and all(c[1].startswith("GEO.FUN") for c in construtivos)
    vala_do_csv = [
        (
            "U2",
            "GEO.MOV.VAL",
            "berco",
            "m³",
            1.0,
            "['berco']",
        ),  # o trecho dava outro número
        (
            "U2",
            "GEO.MOV.VAL",
            "escavacao",
            "m³",
            9.0,
            "['escavacao_vala']",
        ),  # a rede não calcula mais aqui
    ]
    arquivo = _csv(tmp_path / "associados.csv", construtivos + vala_do_csv)
    assert gs.paridade(r["servicos"], arquivo) == []
    mudou = gs.paridade_da_vala(r["servicos"], arquivo)
    assert any(d.startswith("U2/GEO.MOV.VAL/berco/m³: gavetas") for d in mudou)
    assert "U2/GEO.MOV.VAL/escavacao/m³: falta nas gavetas (csv 9.000)" in mudou
    assert any(
        d.startswith("U2/GEO.MOV.VAL/reaterro/m³: só nas gavetas") for d in mudou
    )


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


def test_dn_nominal_da_rede_da_a_mesma_largura_na_vala_rede_e_nos_complementares():
    """DE 326 com DN 300 (lodo da ETA): a Tabela I do MOS é pelo DN nominal; a regra `vala_rede` (serviços das gavetas),
    o quadro de `valas.rede` (HTML) e os complementares usam o mesmo DN, e a largura difere da que sairia do DE."""
    rede = {**_rede(id="AAT01", de_mm=326), "dn_mm": 300}
    base = eg.juntar(eg.de_valas([rede]), eg.de_sondagens(FUROS, "sondagens.json"))
    fatos = {f["propriedade"]: f["valor"] for f in base["fatos"] if f["objeto_id"] == "RV-AAT01"}
    assert fatos["dn_mm"] == 300
    pelo_dn = valas.secao("pista", 0.326, valas.MATERIAL_PADRAO, 300)[0]
    assert pelo_dn != pytest.approx(valas.secao("pista", 0.326, valas.MATERIAL_PADRAO, 326)[0])
    quadro = valas.quantificar(rede["classes"], rede["peso"], 0.326, None, None, 300)
    servicos = {(s["saida"], s.get("chave")): s["valor"] for s in gavetas.calcular(base)[0] if s["regra"] == "vala_rede"}
    for q in quadro:
        assert servicos[("demolicao_m2", q["classe"])] == pytest.approx(q["demolicao_m2"], abs=1e-6)
    pista = [e for e in gs.elementos(base, EPSG) if e["tipo"] == "vala" and e["chave"] == "pista"]
    assert pista and all(e["dims"]["b"] == pytest.approx(pelo_dn, abs=1e-6) for e in pista)


def test_rede_sem_sistema_pelo_local_usa_o_trecho_do_contrato():
    """'ETA entrada adutora água bruta DN1000' não casa com as chaves; o trecho do contrato a que a rede pertence
    ('ENTRADA DA ADUTORA DE ÁGUA BRUTA') casa com AB_ENTRADA: a rede ganha unidade, sistema e os complementares."""
    rede = {**_rede(id="ETA entrada adutora água bruta DN1000", de_mm=1048), "dn_mm": 1000,
            "trecho_contrato": "ENTRADA DA ADUTORA DE ÁGUA BRUTA"}
    base = eg.juntar(eg.de_valas([rede]), eg.de_sondagens(FUROS, "sondagens.json"))
    oid = "RV-ETA entrada adutora água bruta DN1000"
    mapa, pendencias = gavetas.unidade_sistema(base, None, {})
    assert mapa[oid] == ("u1", "AB_ENTRADA") and not [p for p in pendencias if p["objeto_id"] == oid]
    sem_trecho = eg.juntar(eg.de_valas([{**rede, "trecho_contrato": None}]), eg.de_sondagens(FUROS, "sondagens.json"))
    assert oid not in gavetas.unidade_sistema(sem_trecho, None, {})[0]
    assert any(e["objeto_id"] == oid for e in gs.elementos(base, EPSG) if e["tipo"] == "vala")
