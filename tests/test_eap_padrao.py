"""EAP padrão por tipo de obra: validação do JSON real, situações das folhas, % por etapa, unidades e tipo da obra."""

import json

import pytest

from camadas import eap_padrao


def _q(codigo, grandeza, unidade, quantidade, ids, sem_valor=0):
    return {
        "codigo": codigo,
        "grandeza": grandeza,
        "unidade": unidade,
        "quantidade": quantidade,
        "n_elementos": len(ids),
        "sem_valor": sem_valor,
        "evidencias": ids,
    }


def _fato(codigo, servico, unidade, valor, status="fonte única", n=1):
    return {
        "codigo": codigo,
        "servico": servico,
        "unidade": unidade,
        "valor": valor,
        "status": status,
        "afirmacoes": [{"documento": f"d{k}"} for k in range(n)],
    }


def _folhas(bloco):
    return {f["id"]: f for e in bloco["etapas"] for f in e["folhas"]}


def test_json_real_sem_erros_e_sem_item_fora_do_padrao():
    erros, avisos = eap_padrao.validar()
    assert erros == []
    assert avisos == [] and eap_padrao.itens_fora_do_padrao() == []


def test_ids_unicos_e_etapas_ordenadas():
    for tipo, meta in eap_padrao.TIPOS.items():
        ids = [e["id"] for e in meta["etapas"]]
        assert ids == sorted(ids) and len(ids) == len(set(ids))
        assert len({f["id"] for f in eap_padrao._folhas_do_tipo(tipo)}) == len(
            eap_padrao._folhas_do_tipo(tipo)
        )


def test_validar_reprova_item_servico_e_id_invalidos(monkeypatch):
    ruim = json.loads(json.dumps(eap_padrao.PADRAO["tipos"]))
    folhas = ruim["obra_linear"]["etapas"][0]["folhas"]
    folhas[0]["aponta"] = [{"item": "XXX.YYY.ZZZ"}]
    folhas[1]["aponta"] = [{"item": "GEO.MOV.SUP", "servico": "concreto"}]
    folhas[2]["id"] = folhas[1]["id"]
    monkeypatch.setattr(eap_padrao, "TIPOS", ruim)
    erros, _ = eap_padrao.validar()
    texto = " | ".join(erros)
    assert (
        "fora de eap_geral" in texto
        and "não é admitido" in texto
        and "id repetido" in texto
    )


def test_validar_avisa_item_fora_do_padrao(monkeypatch):
    mudo = json.loads(json.dumps(eap_padrao.PADRAO["tipos"]))
    for etapa in mudo["obra_linear"]["etapas"]:
        for folha in etapa["folhas"]:
            folha["aponta"] = [a for a in folha["aponta"] if a["item"] != "HID.TUB.LIG"]
            folha["observacao"] = "a preencher manualmente"
    monkeypatch.setattr(eap_padrao, "TIPOS", mudo)
    erros, avisos = eap_padrao.validar()
    assert erros == []
    assert "obra_linear: item fora do padrão: HID.TUB.LIG" in avisos


def test_situacoes_das_folhas():
    codificada = {
        "quantidades": [
            _q("U1.ACT600.CIV.EST.PIL", "quantidade", "un", 12.0, ["p1", "p2"]),
            _q("U1.ACT600.GEO.FUN.BLO", "quantidade", "un", 3.0, ["b1"], sem_valor=0),
            _q("U1.ACT600.GEO.FUN.EST", "comprimento", "m", 0.0, ["e1"], sem_valor=1),
        ]
    }
    fatos = [_fato("U1.*.HID.EQP.EQU", "", "un", None, "só menção", 0)]
    bloco = eap_padrao.preencher("obra_localizada", codificada, {"fatos": fatos})
    f = _folhas(bloco)
    assert f["OP.04.03"]["situacao"] == "preenchida" and f["OP.04.03"][
        "quantidades_txt"
    ] == ["12 un"]
    assert (
        f["OP.04.03"]["codigos"] == ["U1.ACT600.CIV.EST.PIL"]
        and f["OP.04.03"]["n_evidencias"] == 2
    )
    assert f["OP.03.04"]["situacao"] == "preenchida"
    assert f["OP.03.01"]["situacao"] == "só menção"  # elemento sem valor: só evidência
    assert f["OP.08.01"]["situacao"] == "só menção"  # fato sem valor
    assert (
        f["OP.02.01"]["situacao"] == "a preencher" and f["OP.02.01"]["destaque"] is True
    )
    assert (
        f["OP.03.02"]["situacao"] == "a preencher"
        and f["OP.03.02"]["destaque"] is False
    )
    assert (
        f["OP.01.01"]["situacao"] == "sem item codificado"
        and f["OP.01.01"]["destaque"] is False
    )


def test_fato_com_valor_por_servico_preenche_a_folha_do_servico():
    fatos = [_fato("U1.*.GEO.MOV.ESC", "bota_fora", "m³", 1234.5, "convergente", 2)]
    f = _folhas(eap_padrao.preencher("obra_localizada", None, fatos))
    assert f["OP.02.05"]["situacao"] == "preenchida"
    assert (
        f["OP.02.05"]["quantidades_txt"] == ["1.234,50 m³ · convergente"]
        and f["OP.02.05"]["n_evidencias"] == 2
    )
    assert f["OP.02.01"]["situacao"] == "a preencher"  # o serviço não preenche o item


def test_nao_se_aplica_com_justificativa_e_sem():
    ok = [
        {
            "id": "OP.02.01",
            "justificativa": "terreno em aterro existente",
            "autor": "Caio",
        }
    ]
    f = _folhas(eap_padrao.preencher("obra_localizada", None, None, ok))
    assert (
        f["OP.02.01"]["situacao"] == "não se aplica"
        and f["OP.02.01"]["destaque"] is False
    )
    assert (
        f["OP.02.01"]["justificativa"] == "terreno em aterro existente"
        and f["OP.02.01"]["autor"] == "Caio"
    )
    for ruim in ({"id": "OP.02.01"}, {"id": "OP.02.01", "justificativa": "   "}):
        with pytest.raises(ValueError, match="sem justificativa"):
            eap_padrao.preencher("obra_localizada", None, None, [ruim])
    with pytest.raises(ValueError, match="não existe no padrão"):
        eap_padrao.preencher(
            "obra_localizada", None, None, [{"id": "OP.99.99", "justificativa": "x"}]
        )


def test_percentual_por_etapa_e_total_excluem_nao_se_aplica():
    codificada = {
        "quantidades": [
            _q("U1.A.CIV.EST.PIS", "quantidade", "un", 1.0, ["l"]),
            _q("U1.A.CIV.EST.PAR", "quantidade", "un", 4.0, ["w"]),
        ]
    }
    declaracoes = [
        {"id": "OP.04.02", "justificativa": "sem vigas"},
        {"id": "OP.04.03", "justificativa": "sem pilares"},
    ]
    bloco = eap_padrao.preencher("obra_localizada", codificada, None, declaracoes)
    estrutura = next(e for e in bloco["etapas"] if e["id"] == "OP.04")
    r = estrutura["resumo"]
    assert (r["n_folhas"], r["n_aplicaveis"], r["n_preenchidas"]) == (8, 6, 2)
    assert r["pct"] == pytest.approx(33.3, abs=0.05) and r["pct_txt"] == "33,3 %"
    total = bloco["resumo"]
    assert (
        total["n_folhas"] == 42
        and total["n_aplicaveis"] == 40
        and total["n_preenchidas"] == 2
    )
    assert total["pct_txt"] == "5,0 %"
    assert sum(s["n"] for s in total["por_situacao"]) == 42
    assert total["obrigatorias_a_preencher"] == sum(
        f["destaque"] for e in bloco["etapas"] for f in e["folhas"]
    )


def test_etapa_toda_nao_se_aplica_nao_divide_por_zero():
    r = eap_padrao.resumir([{"situacao": "não se aplica", "destaque": False}])
    assert r["n_aplicaveis"] == 0 and r["pct"] is None and r["pct_txt"] == "—"


def test_unidades_diferentes_nao_se_somam():
    codificada = {
        "quantidades": [
            _q("U1.A.GEO.FUN.EST", "quantidade", "un", 100.0, ["a"]),
            _q("U1.B.GEO.FUN.EST", "quantidade", "un", 150.0, ["b"]),
            _q("U1.A.GEO.FUN.EST", "comprimento", "m", 1800.0, ["a"]),
        ]
    }
    f = _folhas(eap_padrao.preencher("obra_localizada", codificada))["OP.03.01"]
    assert f["quantidades_txt"] == ["250 un", "1.800,00 m (comprimento)"]
    assert f["codigos"] == ["U1.A.GEO.FUN.EST", "U1.B.GEO.FUN.EST"]


def test_tipo_da_obra():
    assert eap_padrao.tipo_da_obra({}) == ["obra_localizada"]
    assert eap_padrao.tipo_da_obra({"obras_lineares": {"a": 1}}) == ["obra_linear"]
    assert eap_padrao.tipo_da_obra({"valas": [{}]}) == ["obra_linear"]
    assert eap_padrao.tipo_da_obra({"valas": [{}], "estacas": "estacas.csv"}) == [
        "obra_localizada",
        "obra_linear",
    ]
    assert eap_padrao.tipo_da_obra(
        {"obras_lineares": {}, "elementos_declarados": [{}]}
    ) == ["obra_localizada"]
    assert eap_padrao.tipo_da_obra(
        {"eap_padrao": {"tipo": "obra_linear"}, "estacas": "x"}
    ) == ["obra_linear"]
    assert eap_padrao.tipo_da_obra(
        {"eap_padrao": {"tipo": ["obra_linear", "obra_localizada"]}}
    ) == [
        "obra_localizada",
        "obra_linear",
    ]
    with pytest.raises(ValueError, match="desconhecido"):
        eap_padrao.tipo_da_obra({"eap_padrao": {"tipo": "ponte"}})


def test_montar_grava_json_e_formata(tmp_path):
    dados = {
        "eap": {
            "quantidades": [_q("U2.AAT06.HID.TUB.RED", "extensão", "m", 1500.5, ["t1"])]
        }
    }
    cfg = {
        "obras_lineares": {"x": 1},
        "eap_padrao": {
            "nao_se_aplica": [{"id": "OL.06.01", "justificativa": "sem travessia"}]
        },
    }
    resultado = eap_padrao.montar(dados, cfg, tmp_path)
    assert [t["tipo"] for t in resultado["tipos"]] == ["obra_linear"]
    f = _folhas(resultado["tipos"][0])
    assert f["OL.04.02"]["situacao"] == "preenchida" and f["OL.04.02"][
        "quantidades_txt"
    ] == ["1.500,50 m (extensão)"]
    assert f["OL.06.01"]["situacao"] == "não se aplica"
    assert (
        resultado["estado"] == "premissa"
        and "MOS" in resultado["aviso"]
        and resultado["fora_do_padrao"] == []
    )
    assert (
        json.loads((tmp_path / "eap_padrao.json").read_text(encoding="utf-8"))
        == resultado
    )


def test_metadados():
    assert eap_padrao.metadados()["modulo"] == "eap_padrao"


def test_build_nao_cai_com_declaracao_sem_justificativa(tmp_path):
    from camadas import obra

    dados = {}
    cfg = {"eap_padrao": {"nao_se_aplica": [{"id": "OP.02.01"}]}}
    obra._eap_padrao_no_build(dados, cfg, tmp_path)
    assert "eap_padrao" not in dados
    assert any("sem justificativa" in a for a in obra.AVISOS_DO_BUILD)
    obra._eap_padrao_no_build(dados, {}, tmp_path)
    assert (
        dados["eap_padrao"]["tipos"][0]["tipo"] == "obra_localizada"
        and (tmp_path / "eap_padrao.json").exists()
    )
