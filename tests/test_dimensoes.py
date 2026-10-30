import math

import pandas as pd
import pytest
from shapely.geometry import LineString

from camadas import associados, dimensoes, formulas

LINHA = LineString([(0, 0), (100, 0)])


def _furo(**kw):
    return {"id": "SP-01", "E": 50.0, "N": 10.0, "cota_boca": 240.0, "profundidade_m": 10.0, **kw}


def _vala(segmentos, de_mm=200, material="TUBO PEAD DE 200", sondagens=(), **kw):
    """Elementos de vala do trecho e as evidências dos serviços (pelas regras genéricas)."""
    trecho = {"id": "t1", "de_mm": de_mm, "segmentos": segmentos, "material_texto": material, "geometria": LINHA, **kw}
    els = [dimensoes.elemento(f"t1 · {s}", "vala", "U2.AAT06", None, dims, "teste", al)
           for s, dims, al in dimensoes.dimensionar_vala(trecho, list(sondagens))]
    evs, sem_valor, detalhes = associados.aplicar(els)
    return els, evs, sem_valor, detalhes


def _q(evs, servico, unidade=None):
    return sum(e["valor"] for e in evs if e["servico"] == servico and unidade in (None, e["unidade"]))


def _declarado(tipo, **dims):
    els = dimensoes.de_declarados([{"id": f"x-{tipo}", "tipo": tipo, "unidade": "U1", "sistema": "ACT600",
                                    "dimensoes": dims}])
    evs, sem_valor, _ = associados.aplicar(els)
    return els, {(e["codigo"], e["servico"]): e["valor"] for e in evs}, sem_valor


def test_conceitos_coerentes():
    assert dimensoes.validar() == [] and associados.validar() == []


def test_avaliador_so_aceita_o_permitido():
    assert formulas.avaliar("max(a, 2) * pi", {"a": 1}) == pytest.approx(2 * math.pi)
    assert formulas.avaliar("1 if t == 'bomba' and h > 0 else 0", {"t": "bomba", "h": 0.3}) == 1
    for perigosa in ("__import__('os')", "a.real", "[1, 2]", "open('x')"):
        with pytest.raises(ValueError):
            formulas.avaliar(perigosa, {"a": 1.0})
    with pytest.raises(KeyError):
        formulas.avaliar("x + 1", {})
    assert formulas.conferir("A * e_lastro") is None
    assert formulas.conferir("__import__('os')").startswith("construção não permitida")
    assert formulas.conferir("A *").startswith("sintaxe")


# elementos estruturais -------------------------------------------------------------------------------------------
def test_laje_suspensa_tem_forma_de_fundo_escoramento_e_sem_lastro():
    _, q, _ = _declarado("laje", A=100.0, e=0.2, P=40.0)
    assert q[("U1.ACT600.CIV.EST.PIS", "concreto")] == pytest.approx(20.0)
    assert q[("U1.ACT600.CIV.EST.PIS", "forma")] == pytest.approx(100 + 40 * 0.2)      # fundo + bordas
    assert q[("U1.ACT600.CIV.EST.PIS", "escoramento")] == pytest.approx(100.0)
    assert ("U1.ACT600.CIV.EST.PIS", "lastro") not in q
    assert q[("U1.ACT600.CIV.EST.PIS", "armadura")] == pytest.approx(90 * 20.0)        # taxa da laje


def test_laje_de_fundo_apoiada_tem_lastro_e_impermeabilizacao_sem_escoramento():
    _, q, _ = _declarado("laje", A=100.0, e=0.3, suspensa=0.0, imperm=1.0)
    assert q[("U1.ACT600.CIV.EST.PIS", "lastro")] == pytest.approx(100 * 0.05)
    assert q[("U1.ACT600.CIV.EST.PIS", "impermeabilizacao")] == pytest.approx(100.0)
    assert ("U1.ACT600.CIV.EST.PIS", "escoramento") not in q


def test_parede_tem_forma_nas_duas_faces_e_impermeabilizacao_interna():
    _, q, _ = _declarado("parede", L=10.0, h=4.0, e=0.3)
    assert q[("U1.ACT600.CIV.EST.PAR", "forma")] == pytest.approx(80.0)
    assert q[("U1.ACT600.CIV.EST.PAR", "impermeabilizacao")] == pytest.approx(40.0)
    assert q[("U1.ACT600.CIV.EST.PAR", "concreto")] == pytest.approx(12.0)


def test_baldrame_gera_vala_corrida_com_escavacao_e_reaterro():
    els, q, _ = _declarado("baldrame", L=50.0)                                          # b, h por premissa
    assert [e["tipo"] for e in els] == ["baldrame", "cava_linear"]
    assert q[("U1.ACT600.GEO.MOV.ESC", "")] == pytest.approx(50 * (0.2 + 0.6) * 0.45)
    assert q[("U1.ACT600.GEO.MOV.REA", "")] == pytest.approx(50 * 0.6 * 0.45)
    assert q[("U1.ACT600.CIV.EST.BAL", "lastro")] == pytest.approx(50 * 0.2 * 0.05)
    assert any("premissa" in m for m in els[0]["memoria"])


def test_dimensao_dada_vence_a_premissa():
    els, q, _ = _declarado("baldrame", L=10.0, b=0.3, h=0.6)
    assert els[0]["dims"]["b"] == 0.3 and q[("U1.ACT600.CIV.EST.BAL", "concreto")] == pytest.approx(1.8)


def test_viga_sem_altura_so_calcula_o_que_nao_depende_dela():
    _, q, sem_valor = _declarado("viga", b=0.2, L=6.0)
    assert q == {("U1.ACT600.CIV.EST.VIG", "escoramento"): pytest.approx(1.2)}           # b × L
    assert "x-viga (falta V ← h)" in sem_valor["concreto"]


def test_laje_vinda_de_fato_so_tem_o_que_a_area_permite():
    fatos = pd.DataFrame([{"codigo": "U1.*.CIV.EST.PIS", "servico": "", "unidade": "m²", "valor": 120.0,
                           "status": "convergente"},
                          {"codigo": "U1.*.CIV.EST.BAL", "servico": "", "unidade": "m", "valor": 80.0, "status": "conflito"}])
    els = dimensoes.de_fatos(fatos)
    assert [e["tipo"] for e in els] == ["laje"]                                          # baldrame em conflito: não
    evs, sem_valor, _ = associados.aplicar(els)
    assert {(e["servico"], e["valor"]) for e in evs} == {("escoramento", 120.0)}
    assert any("falta V ← e" in s for s in sem_valor["concreto"])


# vala -----------------------------------------------------------------------------------------------------------
def test_vala_rasa_em_terra_sem_escoramento_e_sem_pavimento():
    els, evs, _, _ = _vala({"fora_da_via": 100.0}, sondagens=[_furo(na_m=8.0)])
    h, b = 0.6 + 0.2 + 0.1, 0.8
    assert els[0]["dims"]["h"] == pytest.approx(h) and els[0]["dims"]["tipo_escoramento"] == "nenhum"
    assert _q(evs, "escavacao") == pytest.approx(b * h * 100, rel=1e-3)
    assert _q(evs, "demolicao") == 0 and not any(e["servico"].startswith("escoramento") for e in evs)


def test_pista_asfalto_corte_demolicao_recomposicao_e_reaterro():
    _, evs, _, detalhes = _vala({"pista": 100.0}, de_mm=630, material="TUBO FD K7", sondagens=[_furo()])
    h, b = 1.0 + 0.63 + 0.1, 1.23
    assert _q(evs, "corte_pavimento") == pytest.approx(200.0)
    assert _q(evs, "demolicao", "m²") == pytest.approx(100 * (b + 0.3), rel=1e-3)
    assert _q(evs, "recomposicao") == _q(evs, "demolicao")
    v_esc = b * (h - 0.35) * 100
    assert _q(evs, "escavacao") == pytest.approx(v_esc, rel=1e-3)
    assert _q(evs, "envoltoria") == 0                                                    # FD rígido
    assert _q(evs, "reaterro") == pytest.approx(v_esc - b * 0.1 * 100 - math.pi * 0.63 ** 2 / 4 * 100, rel=1e-3)
    assert _q(evs, "assentamento") == 100.0
    assert {e["codigo"] for e in evs if e["servico"] == "demolicao"} == {"U2.AAT06.CIV.PAV.REC"}
    assert any(d["regra"] == "volume_demolido" for d in detalhes)


def test_calcada_vai_para_o_item_de_calcada():
    _, evs, _, _ = _vala({"calcada": 40.0}, sondagens=[_furo()])
    assert {e["codigo"] for e in evs if e["servico"] in ("demolicao", "recomposicao")} == {"U2.AAT06.CIV.PAV.CAL"}


def test_areia_pede_escoramento_continuo_e_alarga_a_vala():
    furo = _furo(camadas=[{"de": 0.0, "ate": 4.0, "descricao": "areia fina fofa"}])
    els, evs, _, _ = _vala({"pista": 50.0}, de_mm=300, sondagens=[furo])
    assert els[0]["dims"]["tipo_escoramento"] == "continuo"
    assert els[0]["dims"]["b"] == pytest.approx(0.9 + 0.2)
    assert _q(evs, "escoramento_continuo") == pytest.approx(2 * 1.4 * 50, rel=1e-3)


def test_profundidade_do_perfil_e_rocha_da_sondagem():
    furo = _furo(camadas=[{"de": 0.0, "ate": 2.0, "descricao": "argila siltosa"},
                          {"de": 2.0, "ate": 6.0, "descricao": "rocha alterada (basalto)"}], nspt=[[1, 8], [2, 12]])
    els, evs, _, _ = _vala({"fora_da_via": 100.0}, profundidade_m=3.0, sondagens=[furo])
    b = els[0]["dims"]["b"]
    assert els[0]["dims"]["tipo_escoramento"] == "descontinuo"
    assert _q(evs, "escavacao_rocha") == pytest.approx(b * 1.0 * 100, rel=1e-3)
    assert _q(evs, "escavacao") == pytest.approx(b * 2.0 * 100, rel=1e-3)
    assert _q(evs, "escoramento_descontinuo") == pytest.approx(2 * 2.0 * 100, rel=1e-3)   # só em solo


def test_impenetravel_vira_topo_de_rocha():
    assert dimensoes.solo_na_vala(_furo(impenetravel=True, profundidade_m=1.2), 2.0)["topo_rocha_m"] == 1.2


def test_vala_abaixo_do_na_pede_bombeamento():
    els, evs, _, _ = _vala({"pista": 80.0}, de_mm=300, sondagens=[_furo(na_m=1.5)])       # NA de projeto 1,0 m
    assert els[0]["dims"]["h_agua"] == pytest.approx(1.4 - 1.0)
    assert _q(evs, "esgotamento", "h") == pytest.approx(80 / 40 * 10)
    assert any("atinge o NA" in a for a in els[0]["alertas"])


def test_na_em_areia_pede_ponteiras():
    furo = _furo(na_m=1.0, camadas=[{"de": 0.0, "ate": 5.0, "descricao": "areia média"}])
    _, evs, _, _ = _vala({"pista": 50.0}, de_mm=300, sondagens=[furo])
    assert _q(evs, "rebaixamento", "m") == 50.0 and _q(evs, "rebaixamento", "h") > 0 and _q(evs, "esgotamento") == 0


def test_cota_do_trecho_desloca_o_na_do_furo():
    _, evs, _, _ = _vala({"pista": 10.0}, de_mm=300, cota_terreno=242.0, sondagens=[_furo(na_m=1.5)])
    assert _q(evs, "esgotamento") == 0


def test_sem_sondagem_no_raio_nao_supoe_rocha_nem_na():
    longe = _furo(E=5000.0, N=5000.0, na_m=0.5, impenetravel=True)
    els, evs, _, _ = _vala({"pista": 10.0}, sondagens=[longe])
    assert _q(evs, "escavacao_rocha") == 0 and _q(evs, "esgotamento") == 0
    assert any("nenhuma sondagem" in a for a in els[0]["alertas"])


def test_tubo_flexivel_tem_envoltoria():
    _, evs, _, _ = _vala({"fora_da_via": 10.0}, de_mm=200)
    assert _q(evs, "envoltoria") == pytest.approx(0.8 * 0.5 * 10 - math.pi * 0.04 / 4 * 10, rel=1e-3)


def test_classe_do_solo_pela_palavra_principal():
    assert dimensoes.classe_solo("argila arenosa vermelha") == "argila"
    assert dimensoes.classe_solo("areia argilosa") == "areia"
    assert dimensoes.classe_solo("basalto são") == "rocha"


def test_tabela_de_dimensoes_e_de_servicos():
    els, evs, _, _ = _vala({"pista": 60.0, "calcada": 40.0}, sondagens=[_furo()])
    assert len(dimensoes.tabela(els)) == 2
    t = associados.tabela(evs)
    assert t[t["servico"] == "assentamento"]["quantidade"].sum() == 100.0
