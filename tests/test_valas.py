import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from camadas import lineares, valas

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
    # D2, plano da rodada 25: gabarito muda da NBR 12266 (b = DE + 0,60) para o MOS Sanepar (L = D + SL + X + Y).
    # Antes (NBR): largura 0,90, demolição e recomposição 12,0, volume 12,6. Agora (MOS, FD DN 300, vala de 1,40 m
    # escorada): largura 0,75, demolição e recomposição 10,5, volume 10,5. A profundidade (1,40 m) não mudou.
    q = valas.quantificar(["pista"] * 10, np.ones(10), 0.3)[0]
    assert q["largura_m"] == pytest.approx(0.75, abs=0.001) and q["profundidade_m"] == pytest.approx(1.4, abs=0.001)
    assert q["demolicao_m2"] == pytest.approx(10.5, abs=0.05) and q["recomposicao_m2"] == pytest.approx(10.5, abs=0.05)
    assert q["volume_vala_m3"] == pytest.approx(10.5, abs=0.05)
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


def test_largura_e_profundidade_vem_do_dimensionador_unico():
    d = lineares.dimensionar_vala({"local": "x", "dn_mm": 300, "material": "FD", "prof_m": 1.4, "comp_m": 1.0,
                                   "metodo": "VCA"})
    q = valas.quantificar(["pista"] * 4, np.ones(4), 0.3)[0]
    assert q["largura_m"] == pytest.approx(d["largura_m"], abs=0.001)
    assert q["profundidade_m"] == pytest.approx(d["profundidade_m"], abs=0.001)
    assert valas.secao("pista", 0.3) == pytest.approx((d["largura_m"], d["profundidade_m"]), abs=0.001)
    assert q["escorado"] is True and q["tipo_escoramento"] == d["tipo_escoramento"]


def test_material_padrao_avisa_e_material_declarado_nao():
    padrao = valas.quantificar(["pista"], np.ones(1), 0.3)[0]
    assert padrao["material"] == "FD" and padrao["dn_mm"] == 300
    assert any("material de premissa" in a for a in padrao["alertas"])
    pead = valas.quantificar(["pista"], np.ones(1), 0.3, material="PEAD", dn_mm=315)[0]
    assert pead["material"] == "PEAD" and pead["dn_mm"] == 315
    assert not any("material de premissa" in a for a in pead["alertas"])


def test_fora_da_tabela_do_mos_cai_na_largura_da_nbr_com_alerta():
    q = valas.quantificar(["pista"], np.ones(1), 3.0, material="FD", dn_mm=3000)[0]
    assert q["largura_m"] == pytest.approx(3.6, abs=0.001)
    assert any("Tabela I do MOS" in a for a in q["alertas"])
