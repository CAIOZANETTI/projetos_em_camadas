import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from camadas import valas

M = np.array([[1.0, 0, 0], [0, 1.0, 0]])               # pt = m, para o teste


def _traco(layer, pts, cheio=False):
    return {"layer": layer, "partes": [np.asarray(pts, float)], "preenchimento": (0, 0, 0) if cheio else None}


def _classes(tubo_y, linhas_y, criterio="divisas"):
    am = valas.amostras([_traco("T", [(0, tubo_y), (100, tubo_y)])], "T", M)
    lim = shapely.union_all([LineString([(-10, y), (110, y)]) for y in linhas_y])
    return set(valas.classificar(am, criterio, {"limite": lim})[0])


def test_faixa_preenchida_vira_eixo_com_o_comprimento_certo():
    faixa = [_traco("T", [(0, 9.8), (100, 9.8), (100, 10.2)], True), _traco("T", [(0, 9.8), (100, 10.2), (0, 10.2)], True)]
    am = valas.amostras(faixa, "T", M)
    assert am["peso"].sum() == pytest.approx(100, abs=2)
    assert np.abs(am["pts"][:, 1] - 10).max() < 0.05     # no eixo, não na borda


def test_rede_em_linha_descarta_letras_do_mesmo_layer():
    letras = [_traco("R", [(x, 5), (x + 0.15, 5.3)]) for x in np.arange(10, 30, 0.5)]
    am = valas.amostras([_traco("R", [(0, 0), (50, 0)]), *letras], "R", M, linha=True)
    assert am["peso"].sum() == pytest.approx(50, abs=1)


def test_divisas_pista_calcada_e_fora():
    assert _classes(0, [1, 3, -6, -12]) == {"pista"}     # entre os meios-fios
    assert _classes(2, [1, 3, -6, -12]) == {"calcada"}   # entre meio-fio (1) e alinhamento (3)
    assert _classes(5, [1, 3, -6, -12]) == {"fora_da_via"}
    assert _classes(0, [4, -4]) == {"via_sem_meio_fio"}  # só cercas, vão de 8 m


def test_meio_fio_e_alinhamento_em_layers_separados():
    assert valas.classe_meio_fio([1.0], [6.0], [3.0], [12.0]) == "pista"
    assert valas.classe_meio_fio([1.0], [1.0, 8.0], [3.0], [12.0]) == "pista"
    assert valas.classe_meio_fio([2.0], [0.5], [1.0], [8.0]) == "calcada"
    assert valas.classe_meio_fio([], [3.0], [2.0], [5.0]) == "calcada"         # alinhamento × meio-fio
    assert valas.classe_meio_fio([], [8.0], [2.0], [5.0]) == "fora_da_via"     # no lote, entre alinhamentos


def test_quadras():
    assert _classes(0, [6.5, -6.5], "quadras") == {"pista"}
    assert _classes(4.5, [6.5, -6.5], "quadras") == {"calcada"}
    assert _classes(10, [6.5, -6.5], "quadras") == {"fora_da_via"}


def test_quadro_da_vala():
    q = valas.quantificar(["pista"] * 10, np.ones(10), 0.3)[0]
    assert q["largura_m"] == pytest.approx(0.9) and q["profundidade_m"] == pytest.approx(1.4)
    assert q["demolicao_m2"] == pytest.approx(12.0) and q["recomposicao_m2"] == pytest.approx(12.0)
    assert q["volume_vala_m3"] == pytest.approx(12.6)
    coberta = valas.quantificar(["pavimentado"] * 4, np.ones(4), 0.3, ["asfalto novo"] * 4)[0]
    assert coberta["demolicao_m2"] > 0 and coberta["recomposicao_m2"] == 0 and "urbanização" in coberta["recomposicao"]
    verde = valas.quantificar(["vegetacao"], np.ones(1), 0.3)[0]
    assert verde["demolicao_m2"] == 0 and verde["recomposicao_m2"] > 0


def test_superficie_pela_cor_da_ortofoto():
    img = np.zeros((40, 160, 3), np.uint8)
    img[:, 0:40] = (60, 140, 70)        # BGR: grama
    img[:, 40:80] = (110, 113, 120)     # asfalto
    img[:, 80:120] = (50, 66, 100)      # terra vermelha
    img[:, 120:160] = 255               # fora da ortofoto
    orto = {"img": img, "e0": 0.0, "n1": 4.0, "res": 0.1}
    pts = np.array([[2.0, 2.0], [6.0, 2.0], [10.0, 2.0], [14.0, 2.0]])
    assert valas.classe_ortofoto(pts, orto) == ["vegetacao", "pavimentado", "solo", "sem_ortofoto"]


def test_camada_do_mapa_soma_a_extensao_da_rede():
    """Faixa amostrada dos dois lados (peso de meio passo): a extensão por superfície na camada do mapa soma a da
    rede, não o dobro (AAT00 saía 6 518 m para 3 259 m)."""
    faixa = [_traco("T", [(0, 9.8), (100, 9.8), (100, 10.2)], True), _traco("T", [(0, 9.8), (100, 10.2), (0, 10.2)], True)]
    am = valas.amostras(faixa, "T", M)
    cl = next(iter(valas.REGRAS["classes"]))
    rede = {"id": "R", "de_mm": 300, "fonte_de": "", "criterio": "divisas", "extensao_m": round(float(am["peso"].sum()), 1),
            "pts": am["pts"], "tang": am["tang"], "peso": am["peso"], "classes": [cl] * len(am["pts"]), "quadro": []}
    h = valas.para_html([rede], {}, None, 31982)
    assert sum(f["properties"]["extensao_m"] for f in h["geojson"]["features"]) == pytest.approx(rede["extensao_m"], abs=0.2)


def _rede_sintetica(criterio="divisas", finais=None):
    n = 40
    pts = np.c_[np.arange(n) + 0.5, np.zeros(n)]
    classes = ["pista"] * 25 + ["calcada"] * 10 + ["vegetacao"] * 5
    return {"id": "R1", "de_mm": 300, "fonte_de": "teste", "criterio": criterio, "pranchas": ["P1", "P2"],
            "extensao_m": float(n), "pts": pts, "tang": np.tile([1.0, 0.0], (n, 1)), "peso": np.ones(n),
            "classes": classes, "finais": finais, "quadro": []}


def test_quantificar_gavetas_bate_com_quantificar():
    r = _rede_sintetica(finais=[None] * 35 + ["grama"] * 5)
    q = valas.quantificar(r["classes"], r["peso"], 0.3, r["finais"])
    g = valas.quantificar_gavetas({"classes_por_metro": r["classes"], "pesos_m": r["peso"].tolist(), "de_mm": 300,
                                   "finais": r["finais"]})
    assert g["alertas"] == [] and sum(g["volume_vala_m3"].values()) == pytest.approx(sum(x["volume_vala_m3"] for x in q))
    assert sum(g["demolicao_m2"].values()) == pytest.approx(sum(x["demolicao_m2"] for x in q))
    assert sum(g["recomposicao_m2"].values()) == pytest.approx(sum(x["recomposicao_m2"] for x in q))
    assert "vegetacao/grama" in g["volume_vala_m3"] and "vegetacao/grama" not in g["recomposicao_m2"]
    verde = valas.quantificar_gavetas({"classes_por_metro": ["vegetacao"], "pesos_m": [1], "de_mm": 300})
    assert "vegetacao" not in verde["demolicao_m2"] and "vegetacao" in verde["recomposicao_m2"]


def test_etapa_devolve_as_redes_calculadas(monkeypatch, tmp_path):
    r = _rede_sintetica()
    monkeypatch.setattr(valas, "ortofoto", lambda caminho: None)
    monkeypatch.setattr(valas, "rede", lambda *a, **k: r)
    saida: list = []
    pacote = valas.etapa({"valas": {"redes": [{"id": "R1", "pranchas": ["P1"], "criterio": "divisas", "de_mm": 300}]}},
                         [], [], None, tmp_path, 31982, log=lambda *_: None, redes_saida=saida)
    assert saida == [r] and pacote["redes"][0]["id"] == "R1"
