"""Conferência das cavas do modelo contra as seções de corte: geometria sintética e parser das notas."""

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import box

from camadas import conferencia_cavas as cc

RES = 0.25


def _grade(n=400, terreno=10.0):
    """Grade 100 × 100 m (E 0–100, N 0–100) de terreno plano."""
    return {
        "e0": 0.0,
        "n1": n * RES,
        "res": RES,
        "forma": (n, n),
        "epsg": 31981,
        "terreno": np.full((n, n), terreno, np.float32),
        "valido": np.ones((n, n), bool),
        "edificacao": np.zeros((n, n), bool),
    }


def _cava(g, x0=20.0, x1=30.0, y0=20.0, y1=40.0, profundidade=2.0):
    """Corte retangular conhecido: x0–x1 (E) × y0–y1 (N), com a profundidade dada."""
    corte = np.zeros(g["forma"], np.float32)
    lin0, lin1 = int((g["n1"] - y1) / RES), int((g["n1"] - y0) / RES)
    corte[lin0:lin1, int(x0 / RES) : int(x1 / RES)] = profundidade
    return corte


def _linha(secao, ini, fim):
    return {
        "secao": secao,
        "prancha": "es1",
        "inicio_utm": list(ini),
        "fim_utm": list(fim),
        "comprimento_m": float(np.linalg.norm(np.subtract(fim, ini))),
        "alertas": [],
    }


def _secao_projeto(secao="AA", area=20.0, fundo=8.0, largura=10.0, **extra):
    return {
        "secao": secao,
        "prancha": "009-SAA",
        "area_corte_m2": area,
        "cota_fundo_min_m": fundo,
        "largura_corte_m": largura,
        "terreno": [[0.0, 10.0], [30.0, 10.0]],
        "escavacao": [[10.0, 10.0], [10.0, 8.0], [20.0, 8.0], [20.0, 10.0]],
        "alertas": [],
        **extra,
    }


def test_perfil_do_modelo_area_e_largura_da_cava_retangular():
    g = _grade()
    p = cc.perfil_do_modelo(_linha("AA", (10, 30), (40, 30)), g, _cava(g))
    assert p["area_corte_m2"] == pytest.approx(
        10.0 * 2.0, abs=0.01
    )  # largura × profundidade
    assert p["largura_corte_m"] == pytest.approx(10.0, abs=0.01)
    assert p["cota_fundo_min_m"] == pytest.approx(8.0, abs=1e-4)
    assert p["fracao_no_mds"] == 1.0 and not p["corte_na_ponta"]
    assert p["terreno"][0][0] == pytest.approx(RES / 2, abs=0.01) and p["terreno"][0][
        1
    ] == pytest.approx(10.0)


def test_linha_fora_da_grade_sai_do_mds_e_vira_nao_conferivel():
    g = _grade()
    p = cc.perfil_do_modelo(_linha("AA", (90, 30), (140, 30)), g, _cava(g))
    assert p["fracao_no_mds"] == pytest.approx(0.2, abs=0.02)
    r = cc.conferir_secao(
        _secao_projeto(), {**p, "linha_prancha": "es1", "comprimento_linha_m": 50.0}
    )
    assert r["situacao"] == "não conferível" and "fora do MDS" in r["motivo"]


def _modelo(g, linha):
    return {
        **cc.perfil_do_modelo(linha, g, _cava(g)),
        "linha_prancha": "es1",
        "comprimento_linha_m": linha["comprimento_m"],
    }


def test_secao_confere_quando_area_fundo_e_terreno_batem():
    g = _grade()
    linha = _linha("AA", (10, 30), (40, 30))
    r = cc.conferir_secao(_secao_projeto(), _modelo(g, linha))
    assert r["situacao"] == "confere", r["motivo"]
    assert (
        r["dif_area_m2"] == pytest.approx(0.0, abs=0.05)
        and abs(r["dif_fundo_m"]) < 1e-3
    )


def test_fundo_fora_da_tolerancia_difere():
    g = _grade()
    r = cc.conferir_secao(
        _secao_projeto(fundo=8.0 - 2 * cc.TOL_FUNDO_M),
        _modelo(g, _linha("AA", (10, 30), (40, 30))),
    )
    assert r["situacao"] == "difere" and "fundo" in r["motivo"]


def test_secao_sem_linha_sem_corte_e_area_parcial_sao_nao_conferiveis():
    g = _grade()
    mod = _modelo(g, _linha("AA", (10, 30), (40, 30)))
    sem_linha = cc.conferir_secoes([_secao_projeto("ZZ")], {"AA": mod})[0]
    assert (
        sem_linha["situacao"] == "não conferível" and "sem linha" in sem_linha["motivo"]
    )
    sem_corte = cc.conferir_secao(_secao_projeto(area=0.2), mod)
    assert "sem corte no projeto" in sem_corte["motivo"]
    parcial = cc.conferir_secao(
        _secao_projeto(
            alertas=["a escavação chega à borda do quadro: a área é só a do trecho"]
        ),
        mod,
    )
    assert (
        parcial["situacao"] == "não conferível" and "área parcial" in parcial["motivo"]
    )


def test_corte_ate_a_ponta_da_linha_nao_e_conferivel():
    g = _grade()
    r = cc.conferir_secao(
        _secao_projeto(), _modelo(g, _linha("AA", (22, 30), (40, 30)))
    )  # a linha começa dentro da cava
    assert r["situacao"] == "não conferível" and "ponta" in r["motivo"]


def test_secoes_medias_dao_o_volume_exato_da_faixa():
    g, corte = _grade(), _cava(_grade())
    la, lb = _linha("AA", (10, 25), (40, 25)), _linha("BB", (10, 35), (40, 35))
    conferidas = [
        cc.conferir_secao(_secao_projeto(s), _modelo(g, l))
        for s, l in (("AA", la), ("BB", lb))
    ]
    medias = cc.secoes_medias(
        [la, lb], conferidas, {"C01": box(20, 20, 30, 40)}, g, corte
    )
    assert len(medias) == 1
    m = medias[0]
    assert m["distancia_m"] == pytest.approx(10.0)
    assert m["volume_modelo_m3"] == pytest.approx(
        10.0 * 10.0 * 2.0, rel=1e-3
    )  # largura × distância × profundidade
    assert m["volume_projeto_m3"] == pytest.approx((20.0 + 20.0) / 2 * 10.0)
    assert m["situacao"] == "confere"


def test_cava_sem_par_de_secoes_paralelas_nao_e_conferivel():
    g, corte = _grade(), _cava(_grade())
    transversal = _linha("CC", (25, 10), (25, 50))  # perpendicular às outras
    la = _linha("AA", (10, 25), (40, 25))
    conferidas = [cc.conferir_secao(_secao_projeto("AA"), _modelo(g, la))]
    medias = cc.secoes_medias(
        [la, transversal], conferidas, {"C01": box(20, 20, 30, 40)}, g, corte
    )
    assert medias == [
        {
            "cava": "C01",
            "situacao": "não conferível",
            "motivo": "sem par de seções paralelas",
        }
    ]


def test_comparar_terreno_acha_deslocamento_e_diferenca():
    x = np.arange(0, 30.01, 0.25)
    projeto = np.c_[x, 10.0 + np.sin(x / 3)]
    s = np.arange(0, 50.01, 0.25)
    modelo = np.c_[
        s, 10.5 + np.sin((s - 5.0) / 3)
    ]  # o quadro começa 5 m depois, 0,5 m mais alto
    r = cc.comparar_terreno(projeto.tolist(), modelo.tolist(), 0.25)
    assert r["dif_media_m"] == pytest.approx(0.5, abs=0.02) and r[
        "deslocamento_m"
    ] == pytest.approx(5.0, abs=0.3)


def test_talude_do_projeto_vertical_e_inclinado():
    vertical = [[10, 10], [10, 8], [20, 8], [20, 10]]
    inclinado = [[8, 10], [10, 8], [20, 8], [22, 10]]
    assert cc.talude_do_projeto(vertical) == 0.0
    assert cc.talude_do_projeto(inclinado) == 1.0


# --- tracejado da planta (sem PDF: traços sintéticos) ------------------------------------------------------------
def _traco(centro, direcao_graus, comprimento=7.1, espessura=0.6):
    t = np.radians(direcao_graus)
    u, v = np.array([np.cos(t), np.sin(t)]), np.array([-np.sin(t), np.cos(t)])
    c = np.asarray(centro, float)
    q = [
        c - u * comprimento / 2 - v * espessura / 2,
        c + u * comprimento / 2 - v * espessura / 2,
        c + u * comprimento / 2 + v * espessura / 2,
        c - u * comprimento / 2 + v * espessura / 2,
    ]
    return {
        "layer": "CORTES",
        "cor": (0.0, 0.447, 0.0),
        "preenchimento": (0.0, 0.447, 0.0),
        "partes": [np.array(q)],
    }


def test_tracejado_vira_uma_linha_com_as_pontas_certas():
    tracos = [_traco((100 + 10.6 * k, 50 + 0.1 * k), 0.5) for k in range(20)]
    tracos += [
        _traco((300, 300 + 10.6 * k), 90) for k in range(8)
    ]  # outra linha, vertical
    tracos += [
        {
            "layer": "CORTES",
            "cor": None,
            "preenchimento": (0, 0.4, 0),
            "partes": [np.zeros((9, 2))],
        }
    ]  # letra
    c, e, l = cc.tracos_do_tracejado(tracos)
    assert len(c) == 28
    rot = cc.agrupar_tracejados(c, e)
    assert len(set(rot)) == 2
    sel = rot == rot[0]
    pontas = cc._pontas_da_linha(c[sel], e[sel], l[sel])
    pontas = pontas[np.argsort(pontas[:, 0])]
    assert pontas[0][0] == pytest.approx(100 - 3.55, abs=0.2) and pontas[1][
        0
    ] == pytest.approx(100 + 10.6 * 19 + 3.55, abs=0.2)


def test_unir_linhas_funde_colineares_e_marca_quebrada():
    a = _linha("AA", (0, 0), (0, 30))
    b = {
        **_linha("AA", (0, 28), (0, 40)),
        "prancha": "es2",
    }  # continua a mesma reta noutra planta
    sem = {**_linha(None, (5, 5), (9, 9)), "alertas": ["letra não lida"]}
    unicas, alertas = cc.unir_linhas([a, b, sem])
    assert (
        len(unicas) == 1
        and unicas[0]["comprimento_m"] == pytest.approx(40.0)
        and unicas[0]["prancha"] == "es1+es2"
    )
    assert len(alertas) == 1 and "sem letra" in alertas[0]
    c = {**_linha("BB", (0, 0), (0, 10)), "prancha": "es1"}
    d = {
        **_linha("BB", (5, 5), (30, 5)),
        "prancha": "es3",
    }  # outra direção: linha quebrada
    unicas, alertas = cc.unir_linhas([c, d])
    assert unicas[0]["quebrada"] and "quebrada" in alertas[0]
    r = cc.conferir_secao(
        _secao_projeto("BB"), {**_modelo(_grade(), c), "quebrada": True}
    )
    assert r["situacao"] == "não conferível" and "quebrada" in r["motivo"]


# --- sequência executiva (texto com a fonte deslocada) -------------------------------------------------------------
INVERSA = {
    v: k
    for k, v in cc.TABELA_FONTE.items()
    if len(v) == 1 and v.islower() and k != "\x03"
}


def _codificar(texto: str) -> str:
    return "".join(INVERSA.get(c, c) for c in texto.replace(" ", "\x03"))


TEXTO_DECODIFICADO = """NOTAS
1 - scavação até a cota 237, 50;
2 - xecução das estacas;
4 - scavação até a cota 236, 80 ;base da viga de coroamentoͿ;
8 - scavação até a cota final para implantação da \x12âmara de Contato, mantendo-se os
10 - Zeaterro compactado até a cota 237, 00;
13 - Zeaterro até a cota final de implantação.
1 - scavação até a cota 239, 20;
7 - scavação até a cota final para implantação da Caixa de ^aída 01, mantendo-se os
10 - Zeaterro compactado até a cota 239, 50;
"""


def test_decodificar_texto_da_fonte_deslocada():
    assert cc.decodificar_texto(_codificar("até a cota 237")) == "até a cota 237"
    assert cc.decodificar_texto("".join(chr(0x3EC + d) for d in (2, 3, 7))) == "237"
    assert (
        cc.decodificar_texto("scavação") == "Escavação"
        and cc.decodificar_texto("Zeaterro") == "Reaterro"
    )


def test_notas_da_sequencia_executiva():
    notas = cc.notas_do_texto(cc.decodificar_texto(TEXTO_DECODIFICADO))
    esc = [
        (n["bloco"], n["fase"], n["cota_m"]) for n in notas if n["tipo"] == "escavação"
    ]
    assert esc == [
        (1, 1, 237.5),
        (1, 4, 236.8),
        (1, 8, None),
        (2, 1, 239.2),
        (2, 7, None),
    ]
    rea = [(n["bloco"], n["cota_m"]) for n in notas if n["tipo"] == "reaterro"]
    assert rea == [(1, 237.0), (1, None), (2, 239.5)]
    assert {n["estrutura"] for n in notas if n["bloco"] == 1} == {"Câmara de Contato"}
    assert {n["estrutura"] for n in notas if n["bloco"] == 2} == {"Caixa de Saída 01"}


def test_ligar_sequencia_so_com_ligacao_objetiva():
    notas = cc.notas_do_texto(cc.decodificar_texto(TEXTO_DECODIFICADO))
    cavas = [
        {"id": "C01", "fundo_m": [237.45, 237.45]},
        {"id": "C02", "fundo_m": [234.0, 235.0]},
    ]
    por_fase = {
        (n["bloco"], n["fase"], n["tipo"]): n for n in cc.ligar_sequencia(notas, cavas)
    }
    unica = por_fase[(1, 1, "escavação")]
    assert unica["situacao"] == "confere" and unica["cava"] == "C01"
    assert (
        "não diz onde" in por_fase[(1, 4, "escavação")]["motivo"]
        and por_fase[(1, 4, "escavação")]["situacao"] == "não conferível"
    )
    assert "sem valor" in por_fase[(1, 8, "escavação")]["motivo"]
    assert "reaterro" in por_fase[(1, 10, "reaterro")]["motivo"]
    duas = cc.ligar_sequencia(
        notas[:1], [*cavas, {"id": "C03", "fundo_m": [237.6, 237.6]}]
    )[0]
    assert duas["situacao"] == "não conferível" and "2 cavas" in duas["motivo"]


def test_etapa_sem_pdf_de_corte_pula_com_pendencia(tmp_path):
    log = []
    cfg = {
        "escavacao": {
            "conferencia": {
                "pranchas_corte": [str(tmp_path / "nao_existe.pdf")],
                "pranchas_planta": ["es1"],
            }
        }
    }
    assert cc.etapa(cfg, [], tmp_path, {"corte": 1}, log=log.append) is None
    assert "(pendência" in log[0]
    assert cc.etapa({"escavacao": {}}, [], tmp_path, None, log=log.append) is None


def test_para_html_formata_numeros_com_virgula():
    g = _grade()
    r = cc.conferir_secao(
        _secao_projeto(), _modelo(g, _linha("AA", (10, 30), (40, 30)))
    )
    pacote = cc.para_html({"secoes": [r], "medias": [], "sequencia": [], "alertas": []})
    s = pacote["secoes"][0]
    assert (
        s["area_projeto_txt"] == "20,0"
        and s["situacao"] == "confere"
        and s["dif_fundo_txt"].startswith(("+0,0", "-0,0"))
    )
    assert pacote["placar"] == {"confere": 1, "difere": 0, "não conferível": 0}


PDF_PLANTA_2 = Path(
    "dados/foz/projeto/UNIDADE 01/ANEXO C/2. PBGE/DE/R2/007-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO2-R2.pdf"
)


@pytest.mark.skipif(
    not PDF_PLANTA_2.exists(), reason="PDF da planta de escavação 2 ausente no disco"
)
def test_sequencia_executiva_real():
    pytest.importorskip("pymupdf")
    notas = cc.sequencia_executiva(PDF_PLANTA_2)
    cotas = sorted({n["cota_m"] for n in notas if n["cota_m"] is not None})
    assert {236.8, 237.0, 237.5, 239.2, 239.5} <= set(cotas)
    assert {n["estrutura"] for n in notas} >= {
        "Câmara de Contato",
        "Caixa de Saída 01",
        "Caixa de Saída 02",
    }


def test_mesma_cava_ligada_por_estruturas_diferentes_volta_a_nao_conferivel():
    notas = cc.notas_do_texto(cc.decodificar_texto(TEXTO_DECODIFICADO))
    cavas = [{"id": "C01", "fundo_m": [237.45, 237.45]}]
    nota_2 = {
        **notas[0],
        "bloco": 2,
        "estrutura": "Caixa de Saída 02",
    }  # a mesma cota 237,50, outra estrutura
    r = cc.ligar_sequencia([notas[0], nota_2], cavas)
    assert [x["situacao"] for x in r] == [
        "não conferível",
        "não conferível",
    ] and "não diz onde" in r[0]["motivo"]
