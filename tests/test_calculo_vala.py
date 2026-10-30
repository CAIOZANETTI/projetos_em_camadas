import math

import pytest
from shapely.geometry import LineString

from camadas import calculo_vala as cv

LINHA = LineString([(0, 0), (100, 0)])


def _furo(**kw):
    return {"id": "SP-01", "E": 50.0, "N": 10.0, "cota_boca": 240.0, "profundidade_m": 10.0, **kw}


def _trecho(segmentos, de_mm=200, material="TUBO PEAD DE 200", **kw):
    return {"id": "t1", "de_mm": de_mm, "segmentos": segmentos, "material_texto": material, "geometria": LINHA, **kw}


def _q(calc, servico, unidade=None):
    return sum(q["valor"] for q in calc["quantidades"] if q["servico"] == servico and unidade in (None, q["unidade"]))


def _passo(calc, nome, segmento=None):
    return next(p for p in calc["passos"] if p["passo"] == nome and segmento in (None, p["segmento"]))


def test_vala_rasa_em_terra_sem_escoramento_e_sem_pavimento():
    calc = cv.calcular_trecho(_trecho({"fora_da_via": 100.0}), [_furo(na_m=8.0)])
    h = 0.6 + 0.2 + 0.1                                            # recobrimento outros + DE + berço
    assert _passo(calc, "profundidade")["resultado"] == pytest.approx(h)
    assert _passo(calc, "escoramento")["resultado"] == "nenhum"
    b = max(0.2 + 0.6, 0.6)
    assert _q(calc, "escavacao") == pytest.approx(b * h * 100, rel=1e-3)
    assert _q(calc, "demolicao") == 0 and _q(calc, "corte_pavimento") == 0
    assert not any(q["servico"] and q["servico"].startswith("escoramento") for q in calc["quantidades"])


def test_pista_com_asfalto_corte_demolicao_recomposicao_e_reaterro():
    calc = cv.calcular_trecho(_trecho({"pista": 100.0}, de_mm=630, material="TUBO FD K7"), [_furo()])
    h, b = 1.0 + 0.63 + 0.1, 1.23
    assert _q(calc, "corte_pavimento") == pytest.approx(200.0)               # duas bordas
    assert _q(calc, "demolicao", "m²") == pytest.approx(100 * (b + 0.3), rel=1e-3)
    assert _q(calc, "recomposicao", "m²") == _q(calc, "demolicao", "m²")
    v_esc = b * (h - 0.35) * 100
    assert _q(calc, "escavacao") == pytest.approx(v_esc, rel=1e-3)
    assert _q(calc, "envoltoria") == 0                                        # FD é rígido: só berço
    v_tubo = math.pi * 0.63 ** 2 / 4 * 100
    assert _q(calc, "reaterro") == pytest.approx(v_esc - b * 0.1 * 100 - v_tubo, rel=1e-3)
    assert _q(calc, "assentamento") == 100.0
    assert next(q for q in calc["quantidades"] if q["servico"] == "demolicao")["item"] == "CIV.PAV.REC"


def test_calcada_vai_para_o_item_de_calcada():
    calc = cv.calcular_trecho(_trecho({"calcada": 40.0}), [_furo()])
    assert {q["item"] for q in calc["quantidades"] if q["servico"] in ("demolicao", "recomposicao")} == {"CIV.PAV.CAL"}


def test_areia_pede_escoramento_continuo_e_alarga_a_vala():
    furo = _furo(camadas=[{"de": 0.0, "ate": 4.0, "descricao": "areia fina fofa", "classe": None}])
    calc = cv.calcular_trecho(_trecho({"pista": 50.0}, de_mm=300), [furo])
    assert _passo(calc, "escoramento")["resultado"] == "continuo"            # 1,40 m em areia
    assert _passo(calc, "largura")["resultado"] == pytest.approx(max(0.9, 0.6) + 0.2)
    assert _q(calc, "escoramento_continuo") == pytest.approx(2 * 1.4 * 50, rel=1e-3)


def test_profundidade_do_perfil_e_rocha_da_sondagem():
    furo = _furo(camadas=[{"de": 0.0, "ate": 2.0, "descricao": "argila siltosa"},
                          {"de": 2.0, "ate": 6.0, "descricao": "rocha alterada (basalto)"}], nspt=[[1, 8], [2, 12]])
    calc = cv.calcular_trecho(_trecho({"fora_da_via": 100.0}, profundidade_m=3.0), [furo])
    b = _passo(calc, "largura")["resultado"]
    assert _passo(calc, "escoramento")["resultado"] == "descontinuo"
    assert _q(calc, "escavacao_rocha") == pytest.approx(b * 1.0 * 100, rel=1e-3)   # de 2,0 a 3,0 m
    assert _q(calc, "escavacao") == pytest.approx(b * 2.0 * 100, rel=1e-3)
    assert _q(calc, "escoramento_descontinuo") == pytest.approx(2 * 2.0 * 100, rel=1e-3)   # só a parte em solo
    bota = next(p for p in calc["passos"] if p["passo"] == "bota-fora")
    assert bota["valores"]["V_rocha"] == pytest.approx(b * 100)               # rocha não volta como reaterro


def test_impenetravel_vira_topo_de_rocha():
    solo = cv.solo_na_vala(_furo(impenetravel=True, profundidade_m=1.2), 2.0)
    assert solo["topo_rocha_m"] == 1.2


def test_vala_abaixo_do_na_pede_bombeamento_pelo_tempo_de_vala_aberta():
    calc = cv.calcular_trecho(_trecho({"pista": 80.0}, de_mm=300), [_furo(na_m=1.5)])   # NA de projeto 1,0 m
    h = 1.0 + 0.3 + 0.1
    assert _passo(calc, "lençol")["resultado"] == pytest.approx(h - 1.0)
    assert _q(calc, "esgotamento", "h") == pytest.approx(80 / 40 * 10)                  # 40 m/dia, 10 h/dia
    assert any("atinge o NA" in a for a in calc["alertas"])


def test_na_em_areia_pede_ponteiras():
    furo = _furo(na_m=1.0, camadas=[{"de": 0.0, "ate": 5.0, "descricao": "areia média"}])
    calc = cv.calcular_trecho(_trecho({"pista": 50.0}, de_mm=300), [furo])
    assert _q(calc, "rebaixamento", "m") == 50.0 and _q(calc, "rebaixamento", "h") > 0
    assert _q(calc, "esgotamento") == 0


def test_cota_do_trecho_desloca_o_na_do_furo():
    furo = _furo(na_m=1.5)                                          # boca em 240
    alto = cv.calcular_trecho(_trecho({"pista": 10.0}, de_mm=300, cota_terreno=242.0), [furo])
    assert _q(alto, "esgotamento") == 0                             # 2 m mais alto: NA a 3,0 m no trecho


def test_sem_sondagem_no_raio_nao_supoe_rocha_nem_na():
    longe = _furo(E=5000.0, N=5000.0, na_m=0.5, impenetravel=True)
    calc = cv.calcular_trecho(_trecho({"pista": 10.0}), [longe])
    assert calc["sondagem"] is None
    assert _q(calc, "escavacao_rocha") == 0 and _q(calc, "esgotamento") == 0
    assert any("nenhuma sondagem" in a for a in calc["alertas"])
    assert any("bombeamento não avaliada" in a for a in calc["alertas"])


def test_tubo_flexivel_tem_envoltoria():
    calc = cv.calcular_trecho(_trecho({"fora_da_via": 10.0}, de_mm=200), [])
    b = 0.8
    assert _q(calc, "envoltoria") == pytest.approx(b * (0.2 + 0.3) * 10 - math.pi * 0.04 / 4 * 10, rel=1e-3)


def test_classe_do_solo_pela_palavra_principal():
    assert cv.classe_solo("argila arenosa vermelha") == "argila"
    assert cv.classe_solo("areia argilosa") == "areia"
    assert cv.classe_solo("basalto são") == "rocha"
    assert cv.classe_solo("silte argiloso") == "silte"


def test_tabela_soma_segmentos_e_separa_detalhes():
    calc = cv.calcular_trecho(_trecho({"pista": 60.0, "calcada": 40.0}), [_furo()])
    t = cv.tabela(calc)
    assert t[(t["servico"] == "assentamento")]["valor"].sum() == 100.0
    assert (t["servico"] == "(detalhe)").any()
