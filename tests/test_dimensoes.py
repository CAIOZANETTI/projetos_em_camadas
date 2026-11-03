import math

import pandas as pd
import pytest
from shapely.geometry import LineString

from camadas import associados, dimensoes, formulas

LINHA = LineString([(0, 0), (100, 0)])


def _furo(**kw):
    return {"id": "SP-01", "E": 50.0, "N": 10.0, "cota_boca": 240.0, "profundidade_m": 10.0, **kw}


def _vala(segmentos, de_mm=200, material="TUBO PEAD DE 200", sondagens=(), metodos=("mos_sanepar",), **kw):
    """Elementos de vala do trecho (pelos métodos pedidos) e as evidências dos serviços (pelas regras genéricas)."""
    trecho = {"id": "t1", "de_mm": de_mm, "segmentos": segmentos, "material_texto": material, "geometria": LINHA, **kw}
    els = [dimensoes.elemento(f"t1 · {s} · {m}", "vala", "U2.AAT06", None, dims, "teste", al, m)
           for s, m, dims, al in dimensoes.dimensionar_vala(trecho, list(sondagens), list(metodos))]
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
    # largura b: antes 0,80 m (NBR 12266), agora 0,55 m (MOS: D 0,20 + SL 0,35); h = 0,90 m não muda
    # (decisão do Caio 03/11/2026: dimensionador único (lineares))
    h, b = 0.6 + 0.2 + 0.1, 0.55
    assert els[0]["dims"]["h"] == pytest.approx(h) and els[0]["dims"]["tipo_escoramento"] == "nenhum"
    assert _q(evs, "escavacao") == pytest.approx(b * h * 100, rel=1e-3)
    assert _q(evs, "demolicao") == 0 and not any(e["servico"].startswith("escoramento") for e in evs)


def test_pista_asfalto_corte_demolicao_recomposicao_e_reaterro():
    _, evs, _, detalhes = _vala({"pista": 100.0}, de_mm=300, material="TUBO FD K7", sondagens=[_furo()])
    # (decisão do Caio 03/11/2026: dimensionador único (lineares))
    # tubo: antes FD DN 630 (b NBR 1,23 m), agora FD DN 300, porque o FD DN 630 está fora da Tabela I do MOS;
    # b = D 0,30 + SL 0,35 + X 0,10 (escorada) = 0,75 m
    # demolição: antes L × (b + 0,30), agora L × b (pavimento do MOS, sem sobrelargura de recorte);
    # escavação: antes b × (h − 0,35 de pavimento) × L, agora b × h × L (profundidade inteira);
    # reaterro: antes escavação − berço − tubo, agora escavação − tubo (regra do lineares)
    h, b = 1.0 + 0.3 + 0.1, 0.75
    assert _q(evs, "corte_pavimento") == pytest.approx(200.0)
    assert _q(evs, "demolicao", "m²") == pytest.approx(100 * b, rel=1e-3)
    assert _q(evs, "recomposicao") == _q(evs, "demolicao")
    v_esc = b * h * 100
    assert _q(evs, "escavacao") == pytest.approx(v_esc, rel=1e-3)
    assert _q(evs, "envoltoria") == 0                                                    # FD rígido
    assert _q(evs, "reaterro") == pytest.approx(v_esc - math.pi * 0.3 ** 2 / 4 * 100, rel=1e-3)
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
    # b: antes 1,10 m (NBR: DE + folga 0,60 + 0,20 do contínuo), agora 0,75 m (MOS: D 0,30 + SL 0,35 + X 0,10)
    # (decisão do Caio 03/11/2026: dimensionador único (lineares))
    assert els[0]["dims"]["b"] == pytest.approx(0.3 + 0.35 + 0.1)
    assert _q(evs, "escoramento_continuo") == pytest.approx(2 * 1.4 * 50, rel=1e-3)


def test_profundidade_do_perfil_e_rocha_da_sondagem():
    furo = _furo(camadas=[{"de": 0.0, "ate": 2.0, "descricao": "argila siltosa"},
                          {"de": 2.0, "ate": 6.0, "descricao": "rocha alterada (basalto)"}], nspt=[[1, 8], [2, 12]])
    els, evs, _, _ = _vala({"fora_da_via": 100.0}, profundidade_m=3.0, sondagens=[furo])
    b = els[0]["dims"]["b"]
    assert els[0]["dims"]["tipo_escoramento"] == "descontinuo"
    # b: antes 0,90 m (NBR), agora 0,75 m (MOS); a rocha é a fração do lineares (arredondada em 3 casas: 0,333 de 3 m)
    # escavação em solo: antes 180 m³ (b × 2,0 × L), agora 150,075 m³; em rocha: antes 90 m³, agora 74,925 m³
    # escoramento: antes 400 m² (só a altura em solo), agora 600 m² (2 × h × L, a altura inteira)
    # (decisão do Caio 03/11/2026: dimensionador único (lineares))
    assert _q(evs, "escavacao_rocha") == pytest.approx(b * 1.0 * 100, rel=2e-3)
    assert _q(evs, "escavacao") == pytest.approx(b * 2.0 * 100, rel=2e-3)
    assert _q(evs, "escavacao") + _q(evs, "escavacao_rocha") == pytest.approx(b * 3.0 * 100)
    assert _q(evs, "escoramento_descontinuo") == pytest.approx(2 * 3.0 * 100)


# (decisão do Caio 03/11/2026: dimensionador único (lineares)): removido o teste `impenetravel_vira_topo_de_rocha`, que
# chamava `dimensoes.solo_na_vala` (regra própria que deixou de existir). Furo impenetrável como rocha: ver `geotecnia.topo_rocha_m`.


def test_vala_abaixo_do_na_pede_bombeamento():
    # NA do furo: antes 1,5 m com margem de 0,5 m (NA de projeto 1,0 m); agora a margem é 0 m (geotecnia.json), então o
    # mesmo NA de projeto de 1,0 m pede na_m = 1,0 (com 1,5 m a vala de 1,4 m não atinge a água e não há esgotamento)
    # (decisão do Caio 03/11/2026: dimensionador único (lineares))
    els, evs, _, _ = _vala({"pista": 80.0}, de_mm=300, sondagens=[_furo(na_m=1.0)])       # NA de projeto 1,0 m
    assert els[0]["dims"]["h_agua"] == pytest.approx(1.4 - 1.0)
    assert _q(evs, "esgotamento", "h") == pytest.approx(80 / 40 * 10)
    assert any("atinge o NA" in a for a in els[0]["alertas"])


def test_na_em_areia_pede_ponteiras():
    furo = _furo(na_m=1.0, camadas=[{"de": 0.0, "ate": 5.0, "descricao": "areia média"}])
    _, evs, _, _ = _vala({"pista": 50.0}, de_mm=300, sondagens=[furo])
    assert _q(evs, "rebaixamento", "m") == 50.0 and _q(evs, "rebaixamento", "h") > 0 and _q(evs, "esgotamento") == 0


def test_cota_do_trecho_desloca_o_na_do_furo():
    # com na_m = 1,5 sem deslocamento o NA ficaria abaixo do fundo (1,4 m) e o teste não provaria o deslocamento: usa 1,0 m
    # (NA de projeto antes 1,0 m com margem de 0,5 m; agora a margem é 0 m). decisão do Caio 03/11/2026: dimensionador único (lineares)
    sem_cota, _, _, _ = _vala({"pista": 10.0}, de_mm=300, sondagens=[_furo(na_m=1.0)])
    assert sem_cota[0]["dims"]["h_agua"] == pytest.approx(0.4)                          # sem a cota do trecho: atinge o NA
    _, evs, _, _ = _vala({"pista": 10.0}, de_mm=300, cota_terreno=242.0, sondagens=[_furo(na_m=1.0)])   # NA em 3,0 m
    assert _q(evs, "esgotamento") == 0


def test_sem_sondagem_no_raio_nao_supoe_rocha_nem_na():
    longe = _furo(E=5000.0, N=5000.0, na_m=0.5, impenetravel=True)
    els, evs, _, _ = _vala({"pista": 10.0}, sondagens=[longe])
    assert _q(evs, "escavacao_rocha") == 0 and _q(evs, "esgotamento") == 0
    assert any("nenhuma sondagem" in a for a in els[0]["alertas"])


def test_tubo_flexivel_tem_envoltoria():
    _, evs, _, _ = _vala({"fora_da_via": 10.0}, de_mm=200)
    # b: antes 0,80 m (NBR), agora 0,55 m (MOS: D 0,20 + SL 0,35); decisão do Caio 03/11/2026: dimensionador único (lineares)
    assert _q(evs, "envoltoria") == pytest.approx(0.55 * 0.5 * 10 - math.pi * 0.04 / 4 * 10, rel=1e-3)


def test_classe_do_solo_pela_palavra_principal():
    assert dimensoes.classe_solo("argila arenosa vermelha") == "argila"
    # "areia argilosa": antes "areia" (regra própria do dimensoes), agora "argila" (a 1ª regex que casa em geotecnia.json,
    # ARGIL antes de AREI); decisão do Caio 03/11/2026: dimensionador único (lineares)
    assert dimensoes.classe_solo("areia argilosa") == "argila"
    assert dimensoes.classe_solo("basalto são") == "rocha"


def test_tabela_de_dimensoes_e_de_servicos():
    els, evs, _, _ = _vala({"pista": 60.0, "calcada": 40.0}, sondagens=[_furo()])
    assert len(dimensoes.tabela(els)) == 2
    t = associados.tabela(evs)
    assert t[t["servico"] == "assentamento"]["quantidade"].sum() == 100.0


# vários métodos para a mesma vala ---------------------------------------------------------------------------------
def test_largura_pelo_mos_sanepar():
    els, _, _, _ = _vala({"pista": 100.0}, de_mm=630, material="TUBO PE DE 630", metodos=("mos_sanepar",),
                         sondagens=[_furo()])
    assert els[0]["dims"]["b"] == pytest.approx(0.63 + 0.35 + 0.10)                     # D + SL(PEAD) + X (escorada)
    assert dimensoes.material_mos("TUBO PE DE 630") == "PEAD" and dimensoes.material_mos("TUBO FD K7") == "FD"


def test_metodo_sem_regra_propria_fica_de_fora_com_alerta():
    # antes: nbr12266 e mos_sanepar davam dois elementos, duas fontes e um conflito de escavação (1,23 × 1,38 × 100 =
    # 169,74 m³ contra 1,08 × 1,73 × 100 = 186,84 m³); agora só o MOS tem regra, o NBR 12266 sai com alerta
    # (decisão do Caio 03/11/2026: dimensionador único (lineares))
    from camadas import evidencias
    els, evs, _, _ = _vala({"pista": 100.0}, de_mm=630, material="TUBO PE DE 630",
                           metodos=("nbr12266", "mos_sanepar"), sondagens=[_furo()])
    assert [e["metodo"] for e in els] == ["mos_sanepar"]
    assert {e["documento"]["id"] for e in evs} == {"metodo:mos_sanepar"}
    assert any("nbr12266" in a and "sem regra própria" in a for a in els[0]["alertas"])
    fatos = evidencias.consolidar(evs).set_index(["codigo", "servico", "unidade"])
    assert fatos.loc[("U2.AAT06.GEO.MOV.VAL", "escavacao", "m³")]["valor"] == pytest.approx(1.08 * 1.73 * 100, rel=1e-3)


def test_tubo_fora_da_tabela_do_mos_fica_com_a_largura_em_faltando():
    # antes: o NBR 12266 dava um número (b 0,80 m) para o tubo que o MOS não reconhece; agora a largura falta e só
    # sai o que não depende dela (o assentamento). decisão do Caio 03/11/2026: dimensionador único (lineares)
    els, evs, sem_valor, _ = _vala({"pista": 10.0}, material="TUBO DE MATERIAL DESCONHECIDO")
    assert [e["metodo"] for e in els] == ["mos_sanepar"] and "b" not in els[0]["dims"]
    assert any("MOS: material do tubo não reconhecido" in a for a in els[0]["alertas"])
    assert {e["servico"] for e in evs} == {"assentamento"} and "escavacao_vala" in sem_valor


def test_metodo_mos_usa_o_dimensionador_unico_da_main():
    from camadas import lineares
    els, evs, _, _ = _vala({"pista": 120.0}, de_mm=630, material="TUBO PE DE 630", metodos=("mos_sanepar",))
    r = lineares.dimensionar_vala({"local": "pista", "dn_mm": 630, "material": "PEAD", "prof_m": 1.73, "comp_m": 120.0,
                                   "metodo": "VCA", "pavimentos": {"asfalto": 120.0}}, [])
    q = {(e["servico"], e["unidade"]): e["valor"] for e in evs}
    assert q[("escavacao", "m³")] == pytest.approx(r["escavacao_m3"])          # o mesmo número do build
    assert q[("reaterro", "m³")] == pytest.approx(r["reaterro_m3"])
    assert q[("bota_fora", "m³")] == pytest.approx(r["bota_fora_m3"])
    assert q[(f"escoramento_{r['tipo_escoramento']}", "m²")] == pytest.approx(r["escoramento_m2"])
    assert q[("demolicao", "m²")] == pytest.approx(sum(r["pavimento_m2"].values()))
    assert q[("berco", "m³")] == pytest.approx(r["largura_m"] * 0.1 * 120.0)    # regra genérica, largura do MOS
    assert els[0]["dims"]["b"] == r["largura_m"]


def test_escoramento_total_compara_metodos_que_escolhem_tipos_diferentes():   # nome mantido: a lição L029 o cita
    # antes: o teste comparava dois métodos que escolhiam tipos diferentes (NBR contínuo × MOS pontaleteamento, com o
    # furo a 75 m, fora dos 60 m do MOS mas dentro dos 300 m da sondagem antiga); agora há uma regra só (raio de 60 m)
    # (decisão do Caio 03/11/2026: dimensionador único (lineares))
    camadas = [{"de": 0.0, "ate": 4.0, "descricao": "areia fina fofa"}]
    perto, _, _, _ = _vala({"pista": 120.0}, de_mm=630, material="TUBO PE DE 630", sondagens=[_furo(camadas=camadas)])
    longe, _, _, _ = _vala({"pista": 120.0}, de_mm=630, material="TUBO PE DE 630",
                           sondagens=[_furo(N=75.0, camadas=camadas)])
    assert perto[0]["dims"]["tipo_escoramento"] == "continuo"
    assert longe[0]["dims"]["tipo_escoramento"] == "pontaleteamento"
    assert any("nenhuma sondagem a até 60 m" in a for a in longe[0]["alertas"])
    # o serviço "escoramento" (total, sem tipo) sai nos dois casos, com o mesmo código: é por ele que uma fonte que não diz
    # o tipo (planilha, memorial) se compara com a vala, mesmo quando os tipos escolhidos são diferentes
    for elementos in (perto, longe):
        evs, _, _ = associados.aplicar(elementos)
        assert {e["servico"] for e in evs if e["servico"].startswith("escoramento")} \
            == {"escoramento", f"escoramento_{elementos[0]['dims']['tipo_escoramento']}"}


def test_adaptador_e_lineares_dao_a_mesma_largura_profundidade_e_escavacao():
    # decisão do Caio 03/11/2026: dimensionador único (lineares): uma grandeza, uma regra
    from camadas import lineares
    furo = _furo(na_m=1.0, camadas=[{"de": 0.0, "ate": 2.0, "descricao": "argila siltosa"},
                                    {"de": 2.0, "ate": 6.0, "descricao": "areia média"}], nspt=[[1, 8], [2, 12]])
    for de_mm, material, texto, profundidade_m in ((200, "PEAD", "TUBO PEAD DE 200", None),
                                                    (630, "PEAD", "TUBO PE DE 630", None),
                                                    (300, "FD", "TUBO FD K7", 2.6)):
        els, _, _, _ = _vala({"pista": 90.0}, de_mm=de_mm, material=texto, sondagens=[furo],
                             **({"profundidade_m": profundidade_m} if profundidade_m else {}))
        dims = els[0]["dims"]
        direto = lineares.dimensionar_vala(
            {"local": "pista", "dn_mm": de_mm, "material": material, "prof_m": dims["h"], "comp_m": 90.0,
             "metodo": "VCA", "pavimentos": {"asfalto": 90.0}}, [furo], pts=dimensoes._pontos(LINHA))
        assert dims["b"] == direto["largura_m"] and dims["h"] == direto["profundidade_m"]
        assert dims["V_solo"] + dims["V_rocha"] == pytest.approx(direto["escavacao_m3"])
        assert dims["tipo_escoramento"] == direto["tipo_escoramento"]
        assert dims["A_escoramento"] == pytest.approx(direto["escoramento_m2"])
        assert dims["V_reat"] == pytest.approx(direto["reaterro_m3"]) and dims["V_bota"] == pytest.approx(direto["bota_fora_m3"])
        assert dims["h_agua"] == pytest.approx(direto["altura_agua_m"]) and dims["metodo_agua"] == direto["tipo_esgotamento"]


def test_sondagem_proxima_usa_o_raio_do_modelo_geotecnico():
    from camadas import geotecnia
    perto, dist = dimensoes.sondagem_proxima(LINHA, [_furo(), _furo(id="SP-02", N=500.0)])
    assert perto["id"] == "SP-01" and dist == pytest.approx(10.0)
    fora, dist = dimensoes.sondagem_proxima(LINHA, [_furo(N=geotecnia.RAIO_INFLUENCIA_M + 5)])
    assert fora is None and dist == pytest.approx(geotecnia.RAIO_INFLUENCIA_M + 5)
    assert dimensoes.sondagem_proxima(LINHA, []) == (None, None)


def test_premissas_do_dimensionador_antigo_foram_removidas_do_conceito():
    # decisão do Caio 03/11/2026: dimensionador único (lineares)
    for chave in ("solo", "sondagem", "escoramento"):
        assert chave not in dimensoes.VP
    assert "empolamento" not in dimensoes.VP["volumes"] and "margem_m" not in dimensoes.VP["lencol"]
    assert list(dimensoes.VP["metodos"]) == ["mos_sanepar"]
