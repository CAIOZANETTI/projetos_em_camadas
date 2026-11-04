"""Terreno composto das cavas (opção D): topografia no casco das curvas, MDS corrigido fora, costura fora do casco."""

import importlib.util
import json

import cv2
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon, box

from camadas import conferencia_cavas as cc
from camadas import escavacao, supressao
from camadas import topografia as tp

RES = 0.5
N = 200  # grade de 100 m × 100 m
COTA_PLANA_M = 100.0
CASCO = (20.0, 80.0)  # casco quadrado das curvas: E e N entre 20 e 80 m
PLANO_E, PLANO_N, PLANO_A = (
    0.01,
    0.02,
    0.3,
)  # inclinação (m/m) e deslocamento (m) do MDS sobre a topografia


@pytest.fixture
def sem_rasterio(monkeypatch):
    """Faz `calcular` rodar no CI, que não tem rasterio: rasterizar e vetorizar com shapely e cv2 (só se faltar)."""
    if importlib.util.find_spec("rasterio") is not None:
        return

    def rasterizar(poly, e0, n1, res, forma):
        if poly is None or poly.is_empty:
            return np.zeros(forma, bool)
        col = e0 + (np.arange(forma[1]) + 0.5) * res
        lin = n1 - (np.arange(forma[0]) + 0.5) * res
        e, n = np.meshgrid(col, lin)
        return shapely.contains_xy(poly, e, n)

    def poligonos(mascara, e0, n1, res, min_area_m2, simplificar_m=0.3):
        contornos, _ = cv2.findContours(
            mascara.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        pols = [
            Polygon(
                [(e0 + (x + 0.5) * res, n1 - (y + 0.5) * res) for x, y in c[:, 0, :]]
            )
            for c in contornos
            if len(c) >= 3
        ]
        return [p.buffer(0) for p in pols if p.area >= min_area_m2]

    monkeypatch.setattr(supressao, "rasterizar", rasterizar)
    monkeypatch.setattr(supressao, "poligonos", poligonos)


def _centros():
    col = (np.arange(N) + 0.5) * RES
    lin = N * RES - (np.arange(N) + 0.5) * RES
    return np.meshgrid(col, lin)


def _grade(com_morro: bool = False) -> dict:
    """MDS = topografia plana + plano inclinado (+ um morro de 0,5 m sobre a borda do casco, se pedido)."""
    e, n = _centros()
    mds = COTA_PLANA_M + PLANO_A + PLANO_E * (e - 50) + PLANO_N * (n - 50)
    if com_morro:
        mds = mds + 0.5 * np.exp(-((e - 20.0) ** 2 + (n - 50.0) ** 2) / (2 * 3.0**2))
    return {
        "e0": 0.0,
        "n1": N * RES,
        "res": RES,
        "forma": (N, N),
        "epsg": 31981,
        "terreno": mds.astype(np.float32),
        "valido": np.ones((N, N), bool),
        "edificacao": np.zeros((N, N), bool),
        "vegetacao_alta": np.zeros((N, N), bool),
    }


def _topografia_plana(inclinacao_e: float = 0.0) -> np.ndarray:
    """Superfície das curvas: 100 m (mais a inclinação em E) dentro do casco quadrado, NaN fora (como o TIN)."""
    e, n = _centros()
    dentro = (e >= CASCO[0]) & (e <= CASCO[1]) & (n >= CASCO[0]) & (n <= CASCO[1])
    return np.where(dentro, COTA_PLANA_M + inclinacao_e * (e - 50), np.nan).astype(
        np.float32
    )


def _origem(nome: str) -> int:
    return tp.ORIGENS_TERRENO.index(nome)


def test_dentro_do_casco_e_exatamente_a_topografia_e_fora_o_mds_menos_o_plano():
    g, topo = _grade(), _topografia_plana()
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"], faixa_costura_m=5.0)
    c = r["plano"]["coeficientes"]
    assert c["a_m"] == pytest.approx(PLANO_A, abs=0.01)
    assert c["b_e_m_por_m"] == pytest.approx(PLANO_E, abs=1e-3)
    assert c["b_n_m_por_m"] == pytest.approx(PLANO_N, abs=1e-3)
    dentro = np.isfinite(topo)
    assert np.array_equal(
        r["terreno"][dentro], topo[dentro]
    )  # a costura não entra no casco
    assert (r["origem"][dentro] == _origem("topografia")).all()
    longe = r["origem"] == _origem("mds_corrigido")
    assert longe.any()
    esperado = g["terreno"].astype(np.float64) - tp._valor_do_plano(r["plano"], g)
    assert np.abs(r["terreno"][longe] - esperado[longe]).max() < 1e-3
    assert (
        np.abs(r["terreno"][longe] - COTA_PLANA_M).max() < 0.02
    )  # o MDS corrigido volta à cota da topografia
    assert not (r["origem"] == 0).any()


def test_costura_fica_fora_do_casco_e_suaviza_o_salto_na_borda():
    g, topo = _grade(com_morro=True), _topografia_plana()
    linha = N // 2 - 1  # N = 50 m, atravessa o morro na borda E = 20 m

    def composicao(faixa_m: float) -> dict:
        return tp.compor_terreno(g, topo, g["vegetacao_alta"], faixa_costura_m=faixa_m)

    def maior_degrau(faixa_m: float) -> float:
        return float(np.abs(np.diff(composicao(faixa_m)["terreno"][linha])).max())

    sem_faixa, com_faixa = maior_degrau(0.25), maior_degrau(5.0)
    assert sem_faixa > 0.1  # quase sem faixa: o morro vira degrau na borda
    assert (
        com_faixa < 0.08 and com_faixa < sem_faixa / 2
    )  # com 5 m só resta a inclinação do próprio morro
    r = composicao(5.0)
    costura = r["origem"] == _origem("costura")
    assert (
        costura.any() and not (costura & np.isfinite(topo)).any()
    )  # a faixa de costura está toda fora do casco
    assert (
        r["resumo"]["area_m2"]["costura"] > 0 and r["resumo"]["faixa_costura_m"] == 5.0
    )


def test_a_ponta_da_costura_e_a_topografia_da_celula_mais_proxima_do_casco():
    topo = _topografia_plana(inclinacao_e=0.02)
    dentro = np.isfinite(topo)
    estendida = tp._topografia_da_borda(topo, dentro)
    lin, primeira, ultima = N // 2, int(CASCO[0] / RES), int(CASCO[1] / RES) - 1
    assert estendida[lin, primeira - 7] == topo[lin, primeira]
    assert estendida[lin, ultima + 7] == topo[lin, ultima]
    assert np.array_equal(estendida[dentro], topo[dentro])


def test_extrapolacao_alem_do_limite_tem_origem_propria(monkeypatch):
    monkeypatch.setattr(tp, "LIMITE_EXTRAPOLACAO_M", 10.0)
    g, topo = _grade(), _topografia_plana()
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"], faixa_costura_m=5.0)
    extrapolado = r["origem"] == _origem("mds_corrigido_extrapolado")
    distancia = tp._distancia_ao_casco(np.isfinite(topo), RES)
    assert extrapolado.any() and (distancia[extrapolado] > 10.0).all()
    assert (distancia[r["origem"] == _origem("mds_corrigido")] <= 10.0).all()
    assert r["resumo"]["limite_extrapolacao_m"] == 10.0
    assert any("extrapolação" in a for a in r["resumo"]["alertas"])


def _furo(nome: str, e: float, n: float, boca: float) -> dict:
    return {"id": nome, "E": e, "N": n, "cota_boca": boca}


def test_validacao_fora_do_casco_mede_os_furos_e_declara_a_copa():
    g, topo = _grade(), _topografia_plana()
    furos = [
        _furo("SP1", 10.0, 50.0, COTA_PLANA_M),  # fora do casco, o plano acerta
        _furo("SP1A", 10.0, 50.5, COTA_PLANA_M),  # repetição de SP1: não conta
        _furo(
            "SP2", 90.0, 50.0, COTA_PLANA_M - 3.0
        ),  # fora do casco, copa: o MDS fica 3 m acima da boca
        _furo("SP3", 50.0, 50.0, COTA_PLANA_M + 0.1),
    ]  # dentro do casco
    v = tp.compor_terreno(g, topo, g["vegetacao_alta"], furos=furos)["resumo"][
        "validacao_fora_do_casco"
    ]
    assert [f["id"] for f in v["furos_fora_do_casco"]] == ["SP1", "SP2"]
    assert v["furos_fora_do_casco"][0]["mds_corrigido_menos_boca_m"] == pytest.approx(
        0.0, abs=0.02
    )
    assert v["furos_fora_do_casco"][0]["distancia_ao_casco_m"] == pytest.approx(
        10.0, abs=0.5
    )
    assert v["topografia_menos_boca_dentro_do_casco"]["n"] == 1
    assert v["topografia_menos_boca_dentro_do_casco"]["media_m"] == pytest.approx(-0.1)
    assert any("SP2" in a and "copa" in a for a in v["alertas"]) and not any(
        "SP1" in a for a in v["alertas"]
    )
    faixas = v["residuo_dentro_do_casco_por_distancia_a_borda"]
    assert faixas["0–2 m"]["n"] > 0 and abs(faixas["0–2 m"]["media_m"]) < 0.02


def test_plano_que_nao_melhora_os_furos_de_fora_e_dito_no_resultado():
    g, topo = _grade(), _topografia_plana()
    e, n = 10.0, 5.0  # fora do casco: o plano mexe -0,43 m aqui
    bruto = float(g["terreno"][int((g["n1"] - n) / RES), int(e / RES)])
    furos = [
        _furo("SP9", e, n, bruto)
    ]  # a boca coincide com o MDS bruto: o plano piora
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"], furos=furos)
    v = r["resumo"]["validacao_fora_do_casco"]
    assert (
        v["plano_melhora_furos_de_fora"] is False
        and v["rms_corrigido_m"] > v["rms_bruto_m"]
    )
    assert any("NÃO melhora" in a for a in r["resumo"]["alertas"])
    sem_furos = tp.compor_terreno(g, topo, g["vegetacao_alta"])["resumo"][
        "validacao_fora_do_casco"
    ]
    assert (
        sem_furos["plano_melhora_furos_de_fora"] is None
        and sem_furos["furos_fora_do_casco"] == []
    )


def test_edificacao_e_vegetacao_alta_fora_do_casco_ficam_sem_terreno():
    g, topo = _grade(), _topografia_plana()
    g["edificacao"][20:40, 150:170] = (
        True  # fora do casco (E de 75 m a 85 m, N de 80 a 90 m)
    )
    g["vegetacao_alta"][150:170, 20:40] = True
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"])
    assert np.isnan(r["terreno"][g["edificacao"] & np.isnan(topo)]).all()
    assert np.isnan(r["terreno"][g["vegetacao_alta"] & np.isnan(topo)]).all()
    assert (r["origem"][np.isnan(r["terreno"])] == 0).all()
    sem = r["resumo"]["sem_terreno"]
    assert sem["edificacao_m2"] > 0 and sem["vegetacao_alta_m2"] > 0
    assert sem["total_m2"] == pytest.approx(
        sem["edificacao_m2"] + sem["vegetacao_alta_m2"] + sem["fora_do_levantamento_m2"]
    )
    assert np.isfinite(
        r["terreno"][np.isfinite(topo)]
    ).all()  # dentro do casco a topografia vale mesmo assim


def test_calcular_ignora_celula_sem_terreno(sem_rasterio):
    g = _grade()
    g["edificacao"][:, 140:] = True  # prédio a partir de E = 70 m, dentro do casco
    g["terreno"][:, 180:] = np.nan  # e nada de terreno a partir de E = 90 m
    base = [{"geom": box(45, 45, 55, 55), "etapa": "1ª etapa"}]
    marca = [{"utm": [50.0, 50.0], "cota": 98.0, "topo": False}]
    r = escavacao.calcular(base, marca, [], g)
    assert len(r["cavas"]) == 1
    assert (
        np.isfinite(r["cavas"][0]["escavacao_m3"]) and r["cavas"][0]["escavacao_m3"] > 0
    )


def test_sem_a_chave_o_terreno_fica_identico_byte_a_byte(tmp_path, sem_rasterio):
    g = _grade()
    antes, chaves = g["terreno"].tobytes(), set(g)
    for c in (None, {}, {"fonte": "mds"}):
        escavacao.terreno_composto(g, c, tmp_path)
    assert g["terreno"].tobytes() == antes and set(g) == chaves
    base, marca = (
        [{"geom": box(45, 45, 55, 55), "etapa": None}],
        [{"utm": [50.0, 50.0], "cota": 98.0, "topo": False}],
    )
    assert "terreno" not in escavacao.calcular(base, marca, [], g)["parametros"]


def test_terreno_composto_liga_o_obra_json_e_guarda_a_origem(
    tmp_path, monkeypatch, sem_rasterio
):
    pdf = tmp_path / "geoplanta.pdf"
    pdf.write_bytes(b"%PDF")
    g, topo = _grade(), _topografia_plana()
    original = g["terreno"].copy()
    monkeypatch.setattr(escavacao, "_curvas_da_topografia", lambda t, out: [])
    monkeypatch.setattr(tp, "superficie", lambda curvas, grade: topo)
    c = {
        "fonte": "topografia_e_mds",
        "justificativa": "teste",
        "faixa_costura_m": 5,
        "topografia": {
            "pdf": str(pdf),
            "M": [[1, 0, 0], [0, 1, 0]],
            "layers": ["Curvas_Mestras"],
        },
    }
    mensagens = []
    escavacao.terreno_composto(
        g,
        c,
        tmp_path,
        log=mensagens.append,
        furos=[_furo("SP1", 10.0, 50.0, COTA_PLANA_M)],
    )
    assert np.array_equal(g["terreno_mds"], original) and not np.array_equal(
        g["terreno"], original
    )
    assert g["origem_terreno"].shape == g["terreno"].shape
    assert (
        g["terreno_resumo"]["fonte"] == "teste"
        and g["terreno_resumo"]["area_m2"]["topografia"] > 0
    )
    assert (
        g["terreno_resumo"]["validacao_fora_do_casco"]["furos_fora_do_casco"][0]["id"]
        == "SP1"
    )
    assert mensagens and "m² por origem" in mensagens[0]
    base, marca = (
        [{"geom": box(45, 45, 55, 55), "etapa": None}],
        [{"utm": [50.0, 50.0], "cota": 98.0, "topo": False}],
    )
    assert (
        escavacao.calcular(base, marca, [], g)["parametros"]["terreno"]["fonte"]
        == "teste"
    )


def test_furos_da_obra_le_o_json_das_sondagens(tmp_path):
    arq = tmp_path / "sondagens.json"
    arq.write_text(
        json.dumps(
            {"furos": [_furo("SP1", 1.0, 2.0, 3.0), {"id": "SP2", "E": 1, "N": 2}]}
        )
    )
    assert [f["id"] for f in escavacao._furos_da_obra({"sondagens": str(arq)})] == [
        "SP1"
    ]
    assert (
        escavacao._furos_da_obra({}) == []
        and escavacao._furos_da_obra({"sondagens": "nao_existe.json"}) == []
    )


def test_topografia_ausente_deixa_o_mds_e_avisa(tmp_path):
    g = _grade()
    antes = g["terreno"].tobytes()
    c = {
        "fonte": "topografia_e_mds",
        "topografia": {
            "pdf": str(tmp_path / "nao_existe.pdf"),
            "M": [[1, 0, 0], [0, 1, 0]],
        },
    }
    mensagens = []
    escavacao.terreno_composto(g, c, tmp_path, log=mensagens.append)
    assert g["terreno"].tobytes() == antes and "pendência" in mensagens[0]


def test_composicao_com_tin_das_curvas():
    pytest.importorskip("scipy")
    anel = [(20.0, 20.0), (80.0, 20.0), (80.0, 80.0), (20.0, 80.0), (20.0, 20.0)]
    curvas = [
        {
            "cota_m": COTA_PLANA_M,
            "coords_utm": anel,
            "layer": "Curvas_Mestras",
            "origem": "rotulo",
            "alertas": [],
        },
        {
            "cota_m": COTA_PLANA_M,
            "coords_utm": [(50.0, 20.0), (50.0, 80.0)],
            "layer": "Curvas_Auxiliares",
            "origem": "rotulo",
            "alertas": [],
        },
    ]
    g = _grade()
    topo = tp.superficie(curvas, g)
    assert np.isnan(topo[0, 0]) and topo[N // 2, N // 2] == pytest.approx(COTA_PLANA_M)
    r = tp.compor_terreno(g, topo, g["vegetacao_alta"])
    assert np.nanmax(np.abs(r["terreno"] - COTA_PLANA_M)) < 0.02


def test_regex_dos_layers_padrao_e_dados():
    assert tp._regex_dos_layers(None) == tp.CAMADAS_CURVAS
    assert tp._regex_dos_layers(["Curvas_Mestras", "A.B"]) == r"^(Curvas_Mestras|A\.B)$"


def _curva(cota, ini, fim, origem="rotulo", meio=()):
    return {
        "cota_m": cota,
        "origem": origem if cota is not None else None,
        "alertas": [],
        "coords_utm": [list(ini), *[list(m) for m in meio], list(fim)],
    }


def test_continuacao_propaga_a_cota_de_ponta_a_ponta_e_corrige_a_peca_curta():
    longa = _curva(238.0, (0, 0), (20, 0))
    sem_cota = _curva(
        None, (20, 0.02), (40, 0)
    )  # ponta a 2 cm da anterior: continuação
    peca_curta = _curva(
        237.5, (40, 0), (42, 0)
    )  # 2 m, rótulo do laço vizinho: discorda
    adiante = _curva(238.0, (42, 0), (60, 0))  # a outra ponta da peça curta
    depois = _curva(None, (60, 0), (70, 0))  # a cota anda de peça em peça
    longe = _curva(None, (0, 50), (20, 50))  # sem ponta coincidente: fica para o TIN
    discorda = _curva(None, (100, 0), (110, 0))
    discorda_a, discorda_b = (
        _curva(240.0, (90, 0), (100, 0)),
        _curva(241.0, (110, 0), (120, 0)),
    )
    curvas = [
        longa,
        sem_cota,
        peca_curta,
        adiante,
        depois,
        longe,
        discorda,
        discorda_a,
        discorda_b,
    ]
    tp.propagar_continuacoes(curvas)
    assert (
        sem_cota["cota_m"] == 238.0
        and sem_cota["origem"] == "continuacao"
        and sem_cota["alertas"]
    )
    assert peca_curta["cota_m"] == 238.0 and peca_curta["origem"] == "continuacao"
    assert depois["cota_m"] == 238.0 and depois["origem"] == "continuacao"
    assert longe["cota_m"] is None
    assert discorda["cota_m"] is None  # vizinhas de cotas diferentes: não adivinha
    assert longa["origem"] == "rotulo" and longa["alertas"] == []


def test_continuacao_nao_mexe_em_peca_longa_com_rotulo_proprio():
    a = _curva(238.0, (0, 0), (20, 0))
    b = _curva(237.5, (20, 0), (60, 0))  # 40 m: o rótulo dela vale
    tp.propagar_continuacoes([a, b])
    assert b["cota_m"] == 237.5 and b["origem"] == "rotulo"


def test_conferencia_marca_o_terreno_do_modelo_como_circular():
    g = _grade()
    g["origem_terreno"] = np.full((N, N), _origem("topografia"), np.uint8)
    g["origem_terreno"][:, 100:] = _origem("mds_corrigido")
    topo = _topografia_plana()
    g["terreno_resumo"] = tp.compor_terreno(
        g, topo, g["vegetacao_alta"], furos=[_furo("SP1", 10.0, 50.0, 100.0)]
    )["resumo"]
    linha = {
        "secao": "AA",
        "prancha": "es1",
        "inicio_utm": [10.0, 30.0],
        "fim_utm": [90.0, 30.0],
        "comprimento_m": 80.0,
    }
    p = cc.perfil_do_modelo(linha, g, np.zeros((N, N), np.float32))
    assert p["fracao_terreno_topografia"] == pytest.approx(0.5, abs=0.02)
    t = cc._terreno_do_modelo(g)
    assert t["circular_na_comparacao_de_terreno"] and "quase circular" in t["aviso"]
    sem = dict(g)
    sem.pop("terreno_resumo"), sem.pop("origem_terreno")
    assert cc._terreno_do_modelo(sem) is None
    assert (
        cc.perfil_do_modelo(linha, sem, np.zeros((N, N), np.float32))[
            "fracao_terreno_topografia"
        ]
        is None
    )


def test_html_recebe_o_terreno_do_modelo_e_a_fracao_da_secao_ja_formatados():
    g, topo = _grade(), _topografia_plana()
    resumo = tp.compor_terreno(
        g, topo, g["vegetacao_alta"], furos=[_furo("SP1", 10.0, 50.0, 100.0)]
    )["resumo"]
    t = cc.formatar_terreno_do_modelo(cc._terreno_do_modelo({"terreno_resumo": resumo}))
    assert all(
        isinstance(x["area_txt"], str) and x["area_txt"].endswith("m²")
        for x in t["areas"]
    )
    assert [x["motivo"] for x in t["sem_terreno"]] == [
        "fora do levantamento do MDS",
        "edificação",
        "vegetação alta",
    ]
    assert (
        t["furos_fora"][0]["furo"] == "SP1"
        and "," in t["furos_fora"][0]["corrigido_txt"]
    )
    assert (
        t["plano_melhora_txt"] in {"sim", "NÃO"}
        and t["faixas_borda"][0]["faixa"] == "0–2 m"
    )
    assert (
        cc._terreno_da_secao_txt(None) == "MDS"
        and cc._terreno_da_secao_txt(0.5) == "50% topografia do projeto"
    )
    linha = {
        "secao": "AA",
        "prancha": "es1",
        "situacao": "confere",
        "area_projeto_m2": 10.0,
        "fundo_projeto_m": 9.0,
        "fracao_terreno_topografia": 0.25,
    }
    assert cc.formatar_secao(linha)["terreno_modelo_txt"] == "25% topografia do projeto"
