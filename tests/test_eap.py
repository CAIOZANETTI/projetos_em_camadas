import json

import pytest
from test_construtivos import CFG, EPSG, _dados

from camadas import construtivos, eap


def _construtivos():
    return construtivos.montar(_dados(), CFG)


def _q(quant, codigo, unidade):
    linha = quant[(quant["codigo"] == codigo) & (quant["unidade"] == unidade)]
    assert len(linha) == 1, (codigo, unidade)
    return linha.iloc[0]


def test_modelo_coerente_com_os_outros_conceitos():
    assert eap.validar() == []


def test_estrutura_tem_codigos_unicos_pais_existentes_e_respeita_o_tipo_de_obra():
    nos = eap.estrutura()
    codigos = [n["codigo"] for n in nos]
    assert len(codigos) == len(set(codigos))
    assert {n["pai"] for n in nos} - {None} <= set(codigos)
    por_codigo = {n["codigo"]: n for n in nos}
    assert por_codigo["U1.ACT600.GEO.FUN.EST"]["nivel"] == "item"
    assert "U2.AAT06.GEO.FUN.EST" not in por_codigo           # estaca não é item de obra linear
    assert "U2.AAT06.HID.TUB.RED" in por_codigo and "U1.ACT600.HID.TUB.RED" in por_codigo
    numeros = [n["numero"] for n in nos]
    assert len(numeros) == len(set(numeros))


def test_elemento_ganha_codigo_pela_classe_e_cava_alimenta_escavacao_e_reaterro():
    c = _construtivos()
    codigos = eap.anotar(c)
    assert codigos["u1-ACT600-estaca-ACT600-031"] == ["U1.ACT600.GEO.FUN.EST"]
    assert codigos["u1-FILTROS-pilar-P5"] == ["U1.FILTROS.CIV.EST.PIL"]
    assert codigos["u1-ACT600-cava-C01"] == ["U1.ACT600.GEO.MOV.ESC", "U1.ACT600.GEO.MOV.REA"]
    assert all("eap" in f["properties"] for f in c["geojson"]["features"])


def test_quantidade_deterministica_por_item_com_evidencias():
    quant = eap.quantificar(_construtivos(), EPSG)
    est = _q(quant, "U1.ACT600.GEO.FUN.EST", "m")
    assert est["quantidade"] == 12.0 and est["evidencias"] == ["u1-ACT600-estaca-ACT600-031"]
    assert _q(quant, "U1.ACT600.GEO.FUN.EST", "un")["quantidade"] == 1
    assert _q(quant, "U1.FILTROS.GEO.FUN.BLO", "m²")["quantidade"] == pytest.approx(16.0, rel=1e-3)
    assert _q(quant, "U1.ACT600.GEO.MOV.ESC", "m³")["quantidade"] == 100.0
    rea = _q(quant, "U1.ACT600.GEO.MOV.REA", "m³")                 # a cava não tem reaterro: não inventa
    assert rea["quantidade"] == 0.0 and rea["sem_valor"] == 1
    assert _q(quant, "U2.AAT06.HID.TUB.RED", "m")["quantidade"] == pytest.approx(180.0, abs=1.0)


def test_consolidar_so_soma_a_mesma_unidade_de_medida():
    quant = eap.quantificar(_construtivos(), EPSG)
    u1 = eap.consolidar(quant, "unidade")
    esc = u1[(u1["no"] == "U1") & (u1["item"] == "GEO.MOV.ESC")]
    assert esc["quantidade"].tolist() == [110.0] and esc["n_elementos"].tolist() == [2]   # C01 (ACT600) + C02 (ETA)
    assert set(u1["no"]) == {"U1", "U2"}
    sistema = eap.consolidar(quant, "sistema")
    un = sistema[(sistema["no"] == "U1.FILTROS") & (sistema["unidade"] == "un")]
    assert sorted(un["item"]) == ["CIV.EST.PIL", "GEO.FUN.BLO"]       # bloco e pilar não se somam
    assert un["quantidade"].tolist() == [1.0, 1.0]


def test_lacunas_e_elemento_sem_item():
    c = _construtivos()
    quant = eap.quantificar(c, EPSG)
    assert "CIV.EST.VIG" in eap.lacunas(quant) and "GEO.FUN.EST" not in eap.lacunas(quant)
    assert eap.sem_item(c) == []


def test_verificar_aceita_so_o_que_as_evidencias_provam():
    c = _construtivos()
    est = "u1-ACT600-estaca-ACT600-031"
    proposta = [
        {"codigo": "U1.ACT600.GEO.FUN.EST", "grandeza": "comprimento", "unidade": "m", "quantidade": 12.0, "evidencias": [est]},
        {"codigo": "U1.ACT600.GEO.FUN.EST", "grandeza": "comprimento", "unidade": "m", "quantidade": 15.0, "evidencias": [est]},
        {"codigo": "U1.ACT600.GEO.FUN.EST", "grandeza": "comprimento", "unidade": "m", "quantidade": 12.0, "evidencias": []},
        {"codigo": "U1.ACT600.GEO.FUN.EST", "grandeza": "volume", "unidade": "m³", "quantidade": 1.5, "evidencias": [est]},
        {"codigo": "U1.ACT600.CIV.EST.PIL", "grandeza": "quantidade", "unidade": "un", "quantidade": 1, "evidencias": [est]},
        {"codigo": "U9.XXX.GEO.FUN.EST", "grandeza": "quantidade", "unidade": "un", "quantidade": 1, "evidencias": [est]},
    ]
    r = eap.verificar(proposta, c, EPSG)
    assert r["status"].tolist() == ["confere", "quantidade diverge das evidências", "sem evidência",
                                    "medição não prevista no item", "evidência inválida", "código inexistente"]
    assert r["aceito"].tolist() == [True, False, False, False, False, False]
    assert r.loc[1, "calculado"] == 12.0


def test_evidencia_parcial_e_sinalizada():
    dados = _dados()
    estacas = dados["vetores"][0]["geojson"]["features"]
    estacas.append({**estacas[0], "properties": {**estacas[0]["properties"], "id": "ACT600-032"}})
    c = construtivos.montar(dados, CFG)
    r = eap.verificar([{"codigo": "U1.ACT600.GEO.FUN.EST", "unidade": "un", "quantidade": 1,
                        "evidencias": ["u1-ACT600-estaca-ACT600-031"]}], c, EPSG)
    assert r.loc[0, "status"] == "confere, parcial (faltam elementos do item)" and r.loc[0, "aceito"]


def test_prancha_vira_evidencia_do_pacote_pelo_subgrupo():
    pranchas = [{"id": "fu1", "nome": "Fundação 1", "pdf": "003-PBGE-DE-0000ETA01FUNDACAO1-R2.pdf",
                 "subgrupo": "Geotecnia e fundação"},
                {"id": "aat06_09", "nome": "AAT06 009/019", "pdf": "009-PBHI-DE-AAT06PTPER-R1.pdf", "subgrupo": "Adutoras"},
                {"id": "x", "nome": "Sem subgrupo", "pdf": "x.pdf"}]
    ev = {e["prancha"]: e["pacotes"] for e in eap.evidencias_pranchas(pranchas, {"fu1": "U1.ACT600"})}
    assert ev["fu1"] == ["U1.ACT600.GEO.FUN", "U1.ACT600.GEO.MOV"]
    assert ev["aat06_09"] == ["U2.*.HID.TUB", "U2.*.GEO.MOV"]
    assert ev["x"] == []


def test_montar_poda_a_arvore_aos_nos_com_elementos():
    dados = _dados()
    dados["construtivos"] = construtivos.montar(dados, CFG)
    pacote = eap.montar(dados, {})
    codigos = {n["codigo"] for n in pacote["nos"]}
    assert {"U1", "U1.ACT600", "U1.ACT600.GEO", "U1.ACT600.GEO.FUN", "U1.ACT600.GEO.FUN.EST"} <= codigos
    assert "U1.ACT600.CIV.EST.VIG" not in codigos
    assert all(isinstance(q["evidencias"], list) and q["evidencias"] for q in pacote["quantidades"])
    json.dumps(pacote)                                              # vai para o dados.json do HTML
    assert eap.montar({"crs": {"epsg": EPSG}}, {}) is None


# caracterização (ciclo de complexidade): fixa a saída de `validar` e de `verificar` antes da refatoração ---------------
def _item_quebrado(codigo, **campos):
    """Item da EAP geral válido (molde: o primeiro do eap_geral.jsonl) com o código e os campos trocados."""
    return {**eap.GERAL[0], "codigo": codigo, "nome": codigo, **campos}


def test_validar_lista_inteira_e_ordem_de_um_modelo_quebrado_em_cada_bloco(monkeypatch):
    import copy

    regras = copy.deepcopy(eap.REGRAS)
    regras["pranchas"]["Subgrupo fantasma"] = ["GEO.FUN", "ZZZ.NAO"]
    regras["pranchas"]["Adutoras"] = ["GEO.MOV", "HID.NAO"]
    unidades = copy.deepcopy(eap.UNIDADES)
    unidades["sistemas"]["SISBAD"] = {"unidade": "u9", "nome": "x", "vista_eap_padrao": "diagonal"}
    geral = [
        _item_quebrado("GEO.MOV.ESC"),
        _item_quebrado("GEO.FUN.EST",
                       obra=["localizada", "subterranea"], escopo=["agua", "ar"], servicos=["escavacao", "fantasma"],
                       construtivos=["cava", "classe_x"], layers=["escavacao", "layer_x"],
                       medicoes=[{"grandeza": "n", "unidade": "un", "regra": "contagem"},
                                 {"grandeza": "v", "unidade": "m³", "regra": "soma"},
                                 {"grandeza": "n", "unidade": "un", "regra": "contagem", "atributo": "a"},
                                 {"grandeza": "n", "unidade": "un", "regra": "inexistente"}]),
        _item_quebrado("GEO.MOV.ESC"),
        _item_quebrado("XXX.YYY.ZZZ"),
    ]
    monkeypatch.setattr(eap, "GERAL", geral)
    monkeypatch.setattr(eap, "REGRAS", regras)
    monkeypatch.setattr(eap, "UNIDADES", unidades)
    assert eap.validar() == [
        "código repetido: GEO.MOV.ESC",
        "XXX.YYY.ZZZ: pacote fora de eap.json",
        "GEO.FUN.EST: obra 'subterranea' desconhecida",
        "GEO.FUN.EST: escopo 'ar' desconhecido",
        "GEO.FUN.EST: serviço 'fantasma' fora de servicos.jsonl",
        "GEO.FUN.EST: classe construtiva 'classe_x' fora de unidades_construtivas",
        "GEO.FUN.EST: layer 'layer_x' fora de elementos.json",
        "GEO.FUN.EST: medição {'grandeza': 'v', 'unidade': 'm³', 'regra': 'soma'} inválida",
        "GEO.FUN.EST: medição {'grandeza': 'n', 'unidade': 'un', 'regra': 'contagem', 'atributo': 'a'} inválida",
        "GEO.FUN.EST: medição {'grandeza': 'n', 'unidade': 'un', 'regra': 'inexistente'} inválida",
        "sistema SISBAD: vista_eap_padrao 'diagonal' desconhecida; use ['linear']",
        "sistema SISBAD: unidade 'u9' inexistente",
        "pranchas: pacote 'HID.NAO' inexistente",                       # Adutoras vem antes no eap.json
        "pranchas: subgrupo 'Subgrupo fantasma' fora de disciplinas.json",
        "pranchas: pacote 'ZZZ.NAO' inexistente",
    ]


def test_validar_le_os_globais_na_chamada(monkeypatch):
    assert eap.validar() == []
    monkeypatch.setattr(eap, "GERAL", [*eap.GERAL, _item_quebrado("GEO.FUN.EST")])
    assert eap.validar() == ["código repetido: GEO.FUN.EST"]


def _proposta_e_status(linha):
    c = _construtivos()
    return eap.verificar([linha], c, EPSG).loc[0]


def test_status_da_verificacao_na_ordem_dos_retornos_antecipados():
    estaca = "u1-ACT600-estaca-ACT600-031"
    base = {"codigo": "U1.ACT600.GEO.FUN.EST", "unidade": "un", "quantidade": 1, "evidencias": [estaca]}
    casos = [
        ({**base, "codigo": "U1.ACT600.GEO.FUN"}, "código inexistente"),            # nó que não é item
        ({**base, "codigo": None}, "código inexistente"),
        ({**base, "unidade": "kg"}, "medição não prevista no item"),
        ({**base, "grandeza": "volume"}, "medição não prevista no item"),
        ({**base, "evidencias": []}, "sem evidência"),
        ({**base, "evidencias": None}, "sem evidência"),
        ({**base, "evidencias": ["inexistente"]}, "evidência inválida"),
        ({**base, "evidencias": ["u1-FILTROS-pilar-P5"]}, "evidência inválida"),    # elemento de outro item
        ({**base, "quantidade": 7}, "quantidade diverge das evidências"),
        (base, "confere"),
    ]
    for linha, esperado in casos:
        assert _proposta_e_status(linha)["status"] == esperado, linha
    assert _proposta_e_status({**base, "quantidade": 7})["calculado"] == 1.0
    assert _proposta_e_status({**base, "evidencias": []})["calculado"] is None


def test_status_sem_quantidade_proposta_nao_diverge_porque_nan_nao_compara():
    linha = {"codigo": "U1.ACT600.GEO.FUN.EST", "unidade": "un", "evidencias": ["u1-ACT600-estaca-ACT600-031"]}
    r = _proposta_e_status(linha)
    assert r["status"] == "confere" and r["aceito"] and r["calculado"] == 1.0
