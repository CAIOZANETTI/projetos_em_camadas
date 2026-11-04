"""EAP padrão por tipo de obra: validação do JSON real, situações das folhas, unidade × tipo de obra, calculada ×
preenchida, manual, escopo, % por etapa, unidades e tipo da obra."""

import json
from pathlib import Path

import pytest

from camadas import eap_padrao

FOZ = Path(__file__).resolve().parent.parent / "exemplos" / "foz" / "obra.json"


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


def _fato(codigo, servico, unidade, valor, status="fonte única", n=1, tipo="edital"):
    return {
        "codigo": codigo,
        "servico": servico,
        "unidade": unidade,
        "valor": valor,
        "status": status,
        "afirmacoes": [{"documento": f"d{k}", "tipo": tipo} for k in range(n)],
    }


def _folhas(bloco):
    return {f["id"]: f for e in bloco["etapas"] for f in e["folhas"]}


def _mutar(monkeypatch, funcao):
    """Troca TIPOS por uma cópia alterada por `funcao(tipos)`."""
    copia = json.loads(json.dumps(eap_padrao.PADRAO["tipos"]))
    funcao(copia)
    monkeypatch.setattr(eap_padrao, "TIPOS", copia)


ANTIGAS_SEM_ITEM = (
    "OP.01.01",
    "OP.01.02",
    "OP.06.02",
    "OP.10.03",
    "OP.11.02",
    "OP.11.03",
    "OP.12.01",
    "OP.12.02",
    "OP.12.03",
)
"""Folhas da obra localizada que já não tinham item codificado antes de GER/ACA/URB: o padrão real hoje aponta todas,
então os testes da situação "sem item codificado" voltam a deixá-las sem item por `sem_item`."""


def sem_item(monkeypatch, *ids):
    """Deixa as folhas `ids` sem item codificado (com observação), como eram antes dos itens gerais."""

    def esvaziar(tipos):
        for etapa in tipos["obra_localizada"]["etapas"]:
            for folha in etapa["folhas"]:
                if folha["id"] in ids:
                    folha["aponta"] = []
                    folha["observacao"] = "Sem item codificado (teste)."

    _mutar(monkeypatch, esvaziar)


def so_de_esgoto(monkeypatch, folha_id="OP.07.03"):
    """Marca a folha como só de esgoto (o poço de visita agora vale para água e esgoto; as folhas com escopo restrito
    que sobraram são só as de testes da obra linear), para exercitar "fora do escopo" na obra localizada. Parte do
    TIPOS vigente, então vale depois de `sem_item`."""
    copia = json.loads(json.dumps(eap_padrao.TIPOS))
    for etapa in copia["obra_localizada"]["etapas"]:
        for folha in etapa["folhas"]:
            if folha["id"] == folha_id:
                folha["escopo"] = "esgoto"
    monkeypatch.setattr(eap_padrao, "TIPOS", copia)


def test_json_real_sem_erros_e_sem_aviso():
    erros, avisos = eap_padrao.validar()
    assert erros == [] and avisos == []
    assert eap_padrao.itens_fora_do_padrao() == []


def test_ids_unicos_e_etapas_ordenadas():
    for tipo, meta in eap_padrao.TIPOS.items():
        ids = [e["id"] for e in meta["etapas"]]
        assert ids == sorted(ids) and len(ids) == len(set(ids))
        assert len({f["id"] for f in eap_padrao._folhas_do_tipo(tipo)}) == len(
            eap_padrao._folhas_do_tipo(tipo)
        )


def test_validar_reprova_item_servico_id_obrigatoria_e_escopo(monkeypatch):
    def ruim(tipos):
        # etapa 0 agora é a administração local (1 folha); as folhas a estragar passam para a etapa 1
        folhas = tipos["obra_linear"]["etapas"][1]["folhas"]
        folhas[0]["aponta"] = [{"item": "XXX.YYY.ZZZ"}]
        folhas[1]["aponta"] = [{"item": "GEO.MOV.SUP", "servico": "concreto"}]
        folhas[2]["id"] = folhas[1]["id"]
        folhas[3]["obrigatoria"] = "sim"
        del folhas[3]["obrigatoria"]
        # poço de visita vale para água e esgoto: o item só de esgoto é GER.CTL.CFT
        folha_escopo = tipos["obra_linear"]["etapas"][2]["folhas"][0]
        folha_escopo["escopo"] = "agua"
        folha_escopo["aponta"] = [{"item": "GER.CTL.CFT"}]

    _mutar(monkeypatch, ruim)
    texto = " | ".join(eap_padrao.validar()[0])
    assert (
        "fora de eap_geral" in texto
        and "não é admitido" in texto
        and "id repetido" in texto
    )
    assert "`obrigatoria` ausente" in texto and "fora do escopo do item" in texto


def test_validar_avisa_item_e_servico_fora_do_padrao(monkeypatch):
    def sem_ligacao_e_sem_berco(tipos):
        for etapa in tipos["obra_linear"]["etapas"]:
            for folha in etapa["folhas"]:
                folha["aponta"] = [
                    a
                    for a in folha["aponta"]
                    if a["item"] != "HID.TUB.LIG" and a.get("servico") != "berco"
                ]
                folha["observacao"] = "a preencher manualmente"

    _mutar(monkeypatch, sem_ligacao_e_sem_berco)
    erros, avisos = eap_padrao.validar()
    assert erros == []
    assert "obra_linear: item fora do padrão: HID.TUB.LIG" in avisos
    assert "obra_linear: serviço fora do padrão: GEO.MOV.VAL · berco" in avisos


def test_servico_fora_do_padrao_nao_avisa_se_algum_folha_aponta_o_item_sem_servico(
    monkeypatch,
):
    def item_inteiro(tipos):
        for etapa in tipos["obra_linear"]["etapas"]:
            for folha in etapa["folhas"]:
                folha["aponta"] = [
                    a for a in folha["aponta"] if a.get("servico") != "berco"
                ]
                folha["observacao"] = "x"
        tipos["obra_linear"]["etapas"][2]["folhas"][0]["aponta"].append(
            {"item": "GEO.MOV.VAL"}
        )

    _mutar(monkeypatch, item_inteiro)
    assert not [a for a in eap_padrao.validar()[1] if "GEO.MOV.VAL · berco" in a]


def test_situacoes_das_folhas(monkeypatch):
    sem_item(monkeypatch, *ANTIGAS_SEM_ITEM)
    codificada = {
        "quantidades": [
            _q("U1.ACT600.CIV.EST.PIL", "quantidade", "un", 12.0, ["p1", "p2"]),
            _q("U1.ACT600.GEO.FUN.BLO", "quantidade", "un", 3.0, ["b1"]),
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
    assert (
        f["OP.03.01"]["situacao"] == "só menção"
        and f["OP.03.01"]["motivo"] == "elemento medido sem valor"
    )
    assert (
        f["OP.08.01"]["situacao"] == "só menção"
        and f["OP.08.01"]["motivo"] == "citado sem valor"
    )
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
    assert (
        f["OP.04.03"]["classe"] == "preenchida"
        and f["OP.01.01"]["classe"] == "sem-item"
    )


def test_obra_mista_nao_conta_a_mesma_quantidade_nas_duas_vistas():
    codificada = {
        "quantidades": [
            _q("U1.AB_ENTRADA.HID.TUB.RED", "extensão", "m", 150.0, ["t1"]),
            _q("U2.AAT06.HID.TUB.RED", "extensão", "m", 5000.0, ["t2"]),
        ]
    }
    loc = _folhas(eap_padrao.preencher("obra_localizada", codificada))["OP.07.01"]
    lin = _folhas(eap_padrao.preencher("obra_linear", codificada))["OL.04.02"]
    assert loc["quantidades_txt"] == ["150,00 m (extensão)"] and loc["codigos"] == [
        "U1.AB_ENTRADA.HID.TUB.RED"
    ]
    assert lin["quantidades_txt"] == ["5.000,00 m (extensão)"] and lin["codigos"] == [
        "U2.AAT06.HID.TUB.RED"
    ]


def test_fato_de_unidade_do_outro_tipo_nao_conta_e_asterisco_nao_soma():
    fatos = [
        _fato("U2.*.GEO.MOV.SUP", "", "m²", 8000.0),
        _fato("*.*.HID.TUB.RED", "", "m", 9000.0),
    ]
    f = _folhas(eap_padrao.preencher("obra_localizada", None, fatos))
    assert (
        f["OP.01.04"]["situacao"] == "a preencher"
    )  # U2 é linear: não vale para a obra localizada
    assert (
        f["OP.07.01"]["situacao"] == "só menção"
        and f["OP.07.01"]["motivo"] == "unidade não atribuível"
    )
    assert f["OP.07.01"]["quantidades_txt"] == []
    lin = _folhas(eap_padrao.preencher("obra_linear", None, fatos))
    assert lin["OL.01.04"]["situacao"] == "preenchida"


def test_servico_associado_e_calculada_nao_preenchida():
    fatos = [
        _fato("U1.ACT600.CIV.EST.PIS", "forma", "m²", 420.0, tipo="associado"),
        _fato("U1.ACT600.CIV.EST.PIS", "concreto", "m³", 80.0, tipo="associado"),
        _fato("U1.ACT600.CIV.EST.PIS", "concreto", "m³", 80.0, tipo="planilha"),
        _fato("U1.ACT600.CIV.EST.PIS", "armadura", "kg", 5000.0, tipo="associado"),
    ]
    fatos[3]["decisoes"] = [{"valor": 5000.0, "autor": "Caio", "justificativa": "x"}]
    bloco = eap_padrao.preencher("obra_localizada", None, fatos)
    f = _folhas(bloco)
    assert (
        f["OP.04.05"]["situacao"] == "calculada"
        and "calculada (fórmula)" in f["OP.04.05"]["quantidades_txt"][0]
    )
    assert f["OP.04.07"]["situacao"] == "preenchida"  # a planilha também afirma
    assert f["OP.04.06"]["situacao"] == "preenchida"  # decisão do engenheiro
    assert f["OP.04.05"]["destaque"] is False
    r = bloco["resumo"]
    assert (
        r["n_calculadas"] == 1
        and r["pct_calculada_txt"] == "2,2 % calculada"
        and r["pct_txt"] == "6,7 %"
    )
    assert (
        r["n_preenchidas"] == 3 and r["n_aplicaveis"] == 45
    )  # calculada fica no denominador


def test_item_sem_servico_aceita_fato_de_qualquer_servico_e_com_servico_so_o_dele():
    fatos = [
        _fato("U1.*.HID.EQP.EQU", "fornecimento", "un", 12.0, "convergente"),
        _fato("U1.*.GEO.MOV.VAL", "escavacao", "m³", 300.0),
        _fato("U1.*.GEO.MOV.ESC", "escavacao_rocha", "m³", 80.0),
    ]
    f = _folhas(eap_padrao.preencher("obra_localizada", None, fatos))
    assert f["OP.08.01"]["situacao"] == "preenchida"
    assert f["OP.08.01"]["quantidades_txt"] == [
        "Fornecimento 12 un · convergente [U1.*.HID.EQP.EQU]"
    ]
    assert f["OP.02.06"]["situacao"] == "preenchida"  # valas internas: item sem serviço
    assert (
        f["OP.02.01"]["situacao"] == "preenchida"
    )  # item ESC sem serviço aceita escavacao_rocha
    assert (
        f["OP.02.02"]["situacao"] == "a preencher"
    )  # escoramento só olha o serviço escoramento


def test_fatos_distintos_nao_se_fundem_e_mostram_o_codigo():
    fatos = [
        _fato("U1.ACT600.GEO.FUN.EST", "", "un", 250.0),
        _fato("U1.*.GEO.FUN.EST", "", "un", 250.0),
    ]
    f = _folhas(eap_padrao.preencher("obra_localizada", None, fatos))["OP.03.01"]
    assert len(f["quantidades_txt"]) == 2 and f["codigos"] == [
        "U1.*.GEO.FUN.EST",
        "U1.ACT600.GEO.FUN.EST",
    ]


def test_quantidade_parcial_mostra_quantos_elementos_sem_valor():
    codificada = {
        "quantidades": [
            _q(
                "U1.A.CIV.EST.PIL",
                "quantidade",
                "un",
                5.0,
                ["a", "b", "c"],
                sem_valor=2,
            )
        ]
    }
    f = _folhas(eap_padrao.preencher("obra_localizada", codificada))["OP.04.03"]
    assert (
        f["situacao"] == "preenchida"
        and f["situacao_txt"] == "preenchida (parcial: 2 sem valor)"
    )


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
    duplicada = [
        {"id": "OP.02.01", "justificativa": "a"},
        {"id": "OP.02.01", "justificativa": "b"},
    ]
    with pytest.raises(ValueError, match="duplicada"):
        eap_padrao.preencher("obra_localizada", None, None, duplicada)


def test_nao_se_aplica_com_quantidade_real_vira_conflito_no_denominador():
    codificada = {
        "quantidades": [_q("U1.A.CIV.EST.PIL", "quantidade", "un", 12.0, ["p1"])]
    }
    declaracoes = [{"id": "OP.04.03", "justificativa": "sem pilares"}]
    bloco = eap_padrao.preencher("obra_localizada", codificada, None, declaracoes)
    f = _folhas(bloco)["OP.04.03"]
    assert (
        f["situacao"].startswith("conflito: declarada não se aplica")
        and f["destaque"] is True
    )
    assert f["classe"] == "conflito" and f["quantidades_txt"] == ["12 un"]
    assert bloco["resumo"]["n_aplicaveis"] == 45 and bloco["resumo"]["conflitos"] == 1
    assert bloco["resumo"]["n_preenchidas"] == 0


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
    r = next(e for e in bloco["etapas"] if e["id"] == "OP.04")["resumo"]
    assert (r["n_folhas"], r["n_aplicaveis"], r["n_preenchidas"]) == (8, 6, 2)
    assert r["pct"] == pytest.approx(33.3, abs=0.05) and r["pct_txt"] == "33,3 %"
    total = bloco["resumo"]
    assert (
        total["n_folhas"] == 45
        and total["n_aplicaveis"] == 43
        and total["n_preenchidas"] == 2
    )
    assert total["pct_txt"] == "4,7 %"
    assert sum(s["n"] for s in total["por_situacao"]) == 45


def test_etapa_toda_fora_do_denominador_nao_divide_por_zero():
    r = eap_padrao.resumir([{"situacao": "não se aplica", "destaque": False}])
    assert (
        r["n_aplicaveis"] == 0
        and r["pct"] is None
        and r["pct_txt"] == "—"
        and r["teto_txt"] == ""
    )


def test_preenchimento_manual_de_folha_sem_item_com_documento(monkeypatch):
    sem_item(monkeypatch, *ANTIGAS_SEM_ITEM)
    manual = [
        {
            "id": "OP.12.02",
            "quantidade": 1,
            "unidade": "vb",
            "documento": "As built 01",
            "autor": "Ana",
        }
    ]
    bloco = eap_padrao.preencher("obra_localizada", None, None, None, None, manual)
    f = _folhas(bloco)["OP.12.02"]
    assert f["situacao"] == "preenchida (manual)" and f["classe"] == "manual"
    assert f["quantidades_txt"] == ["1,00 vb · manual: As built 01 (Ana)"]
    r = bloco["resumo"]
    assert (
        r["n_preenchidas"] == 1
        and r["n_sem_item"] == 8
        and r["teto_pct"] == pytest.approx(82.2, abs=0.05)
    )
    assert r["teto_txt"] == "teto sem preenchimento manual: 82,2 %"
    problemas = {
        "documento": {"id": "OP.12.02", "quantidade": 1, "unidade": "vb"},
        "com item": {
            "id": "OP.07.01",
            "quantidade": 1,
            "unidade": "vb",
            "documento": "x",
        },
        "quantidade": {
            "id": "OP.12.02",
            "quantidade": 0,
            "unidade": "vb",
            "documento": "x",
        },
    }
    for trecho, ruim in problemas.items():
        with pytest.raises(
            ValueError,
            match={
                "documento": "sem `documento`",
                "com item": "tem item codificado",
                "quantidade": "`quantidade`",
            }[trecho],
        ):
            eap_padrao.preencher("obra_localizada", None, None, None, None, [ruim])


def test_escopo_da_folha_fora_do_escopo_da_obra_sai_do_denominador(monkeypatch):
    so_de_esgoto(monkeypatch)
    bloco = eap_padrao.preencher("obra_localizada", None, escopos={"agua"})
    f = _folhas(bloco)
    assert (
        f["OP.07.03"]["situacao"] == "fora do escopo"
        and f["OP.07.03"]["destaque"] is False
    )
    assert bloco["resumo"]["n_aplicaveis"] == 44
    com_esgoto = eap_padrao.preencher(
        "obra_localizada", None, escopos={"agua", "esgoto"}
    )
    assert _folhas(com_esgoto)["OP.07.03"]["situacao"] == "a preencher"
    com_dado = [_fato("U1.*.HID.TUB.PVS", "", "un", 4.0)]
    assert (
        _folhas(
            eap_padrao.preencher("obra_localizada", None, com_dado, escopos={"agua"})
        )["OP.07.03"]["situacao"]
        == "preenchida"
    )
    assert eap_padrao.escopos_do_tipo("obra_localizada", {}) == {"agua"}
    assert eap_padrao.escopos_do_tipo(
        "obra_linear", {"eap_padrao": {"escopo": ["esgoto"]}}
    ) == {"esgoto"}


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


def test_obras_lineares_em_unidade_localizada_nao_e_sinal_de_obra_linear():
    dentro_da_eta = {
        "obras_lineares": {"unidade": "UNIDADE 1", "eap": "U1.LINEARES"},
        "estacas": "e.csv",
    }
    assert eap_padrao.tipo_da_obra(dentro_da_eta) == ["obra_localizada"]
    adutora = {"obras_lineares": {"unidade": "UNIDADE 2"}, "estacas": "e.csv"}
    assert eap_padrao.tipo_da_obra(adutora) == ["obra_localizada", "obra_linear"]
    prancha_linear = {
        "pranchas": [
            {"id": "a", "pdf": "x-AAT06-PLANTA.pdf"},
            {"id": "b", "pdf": "ETA01FUNDACAO.pdf"},
        ]
    }
    assert eap_padrao.tipo_da_obra(prancha_linear) == ["obra_localizada", "obra_linear"]
    so_linear = {"pranchas": [{"id": "a", "pdf": "x-AAT06-PLANTA.pdf"}]}
    assert eap_padrao.tipo_da_obra(so_linear) == ["obra_linear"]
    declarada = {"pranchas": [{"id": "a", "pdf": "qualquer.pdf", "eap": "U2.AAT06"}]}
    assert eap_padrao.tipo_da_obra(declarada) == ["obra_linear"]


def test_foz_continua_mista_pelas_pranchas_das_adutoras():
    cfg = json.loads(FOZ.read_text(encoding="utf-8"))
    assert eap_padrao.tipo_da_obra(cfg) == ["obra_localizada", "obra_linear"]
    sem_adutoras = {
        **cfg,
        "pranchas": [p for p in cfg["pranchas"] if not p["id"].startswith("aat")],
        "valas": None,
    }
    assert eap_padrao.tipo_da_obra(sem_adutoras) == [
        "obra_localizada"
    ]  # obras_lineares da Foz é da U1 (ETA)


def test_tipo_vazio_ou_desconhecido_vira_aviso_e_deduz():
    avisos = []
    assert eap_padrao.tipo_da_obra(
        {"eap_padrao": {"tipo": []}, "valas": [{}]}, avisos
    ) == ["obra_linear"]
    assert eap_padrao.tipo_da_obra({"eap_padrao": {"tipo": "ponte"}}, avisos) == [
        "obra_localizada"
    ]
    assert any("vazio" in a for a in avisos) and any(
        "desconhecido" in a for a in avisos
    )


def test_montar_grava_json_e_formata(tmp_path):
    dados = {
        "eap": {
            "quantidades": [_q("U2.AAT06.HID.TUB.RED", "extensão", "m", 1500.5, ["t1"])]
        }
    }
    cfg = {
        "valas": [{}],
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
        f["OL.09.03"]["situacao"] == "fora do escopo"
    )  # o teste de esgoto (CFT) não vale: a unidade U2 é de água
    assert (
        resultado["estado"] == "premissa"
        and "MOS" in resultado["aviso"]
        and resultado["fora_do_padrao"] == []
    )
    assert (
        json.loads((tmp_path / "eap_padrao.json").read_text(encoding="utf-8"))
        == resultado
    )


def test_montar_declaracao_invalida_vira_aviso_e_o_resto_e_preenchido(tmp_path):
    cfg = {
        "eap_padrao": {
            "nao_se_aplica": [
                {"id": "OP.02.01"},
                "OP.02.02",
                {"id": "OP.02.03", "justificativa": "sem lençol"},
                {"id": "OP.02.03", "justificativa": "de novo"},
                {"id": "OL.06.01", "justificativa": "linear não está na obra"},
            ],
            "preenchimento_manual": {"id": "OP.12.02"},
        }
    }
    resultado = eap_padrao.montar({}, cfg, tmp_path)
    f = _folhas(resultado["tipos"][0])
    assert (
        f["OP.02.03"]["situacao"] == "não se aplica"
        and f["OP.02.01"]["situacao"] == "a preencher"
    )
    texto = " | ".join(resultado["avisos"])
    for esperado in (
        "sem justificativa",
        "deve ser um objeto",
        "duplicada",
        "ignorada, a obra não tem o tipo",
        "preenchimento_manual deve ser uma lista",
    ):
        assert esperado in texto
    assert eap_padrao.montar({}, {"eap_padrao": ["x"]})["avisos"][0].startswith(
        "eap_padrao do obra.json deve ser um objeto"
    )


def test_build_nao_cai_com_declaracao_sem_justificativa(tmp_path):
    from camadas import obra

    dados = {}
    cfg = {"eap_padrao": {"nao_se_aplica": [{"id": "OP.02.01"}]}}
    obra._eap_padrao_no_build(dados, cfg, tmp_path)
    assert any("sem justificativa" in a for a in dados["eap_padrao"]["avisos"])
    assert (
        dados["eap_padrao"]["tipos"][0]["tipo"] == "obra_localizada"
        and (tmp_path / "eap_padrao.json").exists()
    )


def test_metadados():
    assert eap_padrao.metadados()["modulo"] == "eap_padrao"


def test_foz_declara_a_agua_potavel_da_u1_como_trecho_linear():
    cfg = json.loads(FOZ.read_text(encoding="utf-8"))
    trechos = eap_padrao.trechos_do_cfg(cfg)
    assert [(t["unidade"], t["titulo_etapa"], t["sistema"]) for t in trechos] == [
        ("U1", "ÁGUA POTÁVEL", "AGUA_POTAVEL")
    ]
    assert "D11" in trechos[0]["justificativa"]
    resultado = eap_padrao.montar({}, cfg)
    assert [t["tipo"] for t in resultado["tipos"]] == ["obra_localizada", "obra_linear"]
    assert not [a for a in resultado["avisos"] if "trecho" in a.lower()]
    fato = {
        "codigo": "U1.AGUA_POTAVEL.GEO.MOV.VAL", "servico": "escavacao", "unidade": "m",
        "status": "convergente", "valor": 622.0, "afirmacoes": [], "decisoes": [],
    }  # fmt: skip
    mista = eap_padrao.montar({"evidencias": {"fatos": [fato]}}, cfg)
    assert not [
        a for a in mista["avisos"] if "trecho" in a.lower()
    ]  # declarada: obra mista, sem aviso


# Tabelas do painel ------------------------------------------------------------------------------------------------
def _montar_do_painel():
    """Obra mista sintética: parcial, só menção, citada no contrato, não se aplica e fora do escopo."""
    dados = {
        "eap": {
            "quantidades": [
                _q("U1.A.CIV.EST.PIL", "quantidade", "un", 5.0, ["a", "b", "c"], 2),
                _q("U2.AAT06.HID.TUB.RED", "extensão", "m", 1500.5, ["t1"]),
            ]
        },
        "evidencias": {
            "fatos": [_fato("U1.*.GER.PRE.TOP", None, "un", None, "sem valor")],
            "titulos_etapa": [
                {
                    "unidade": "U1",
                    "aba": "CUSTO CIVIL",
                    "linha": 7,
                    "titulo_etapa": "URBANIZAÇÃO",
                    "descricao": "MURO DE ARRIMO",
                    "item": None,
                    "servico": "",
                }
            ],
        },
    }
    cfg = {
        "valas": [{}],
        "estacas": [{}],
        "eap_padrao": {
            "nao_se_aplica": [{"id": "OL.06.01", "justificativa": "sem travessia"}]
        },
    }
    return eap_padrao.montar(dados, cfg)


def test_tabelas_do_painel_batem_com_o_resumo_de_cada_tipo():
    resultado = _montar_do_painel()
    tabelas = eap_padrao.tabelas_do_painel(resultado)
    assert list(tabelas) == ["resumo", "situacoes", "etapas", "folhas"]
    assert [r["tipo"] for r in tabelas["resumo"]] == [
        t["tipo"] for t in resultado["tipos"]
    ]
    for linha, bloco in zip(tabelas["resumo"], resultado["tipos"]):
        r = bloco["resumo"]
        assert (
            linha["folhas"]
            == r["n_folhas"]
            == len([f for e in bloco["etapas"] for f in e["folhas"]])
        )
        assert linha["aplicaveis"] == r["n_aplicaveis"]
        assert linha["preenchidas"] == r["n_preenchidas"]
        assert linha["calculadas"] == r["n_calculadas"]
        assert linha["pct_txt"] == r["pct_txt"]
        assert linha["obrigatorias_a_preencher"] == r["obrigatorias_a_preencher"]
        assert linha["conflitos"] == r["conflitos"]
        assert linha["pct_preenchida"] == round(
            r["n_preenchidas"] / r["n_aplicaveis"], 4
        )


def test_tabelas_do_painel_situacoes_somam_as_folhas_e_so_tem_n_positivo():
    resultado = _montar_do_painel()
    tabelas = eap_padrao.tabelas_do_painel(resultado)
    assert all(s["n"] > 0 for s in tabelas["situacoes"])
    assert all(s["situacao"] in eap_padrao.SITUACOES for s in tabelas["situacoes"])
    for resumo in tabelas["resumo"]:
        soma = sum(s["n"] for s in tabelas["situacoes"] if s["tipo"] == resumo["tipo"])
        assert soma == resumo["folhas"]
    assert sum(s["n"] for s in tabelas["situacoes"]) == len(tabelas["folhas"])


def test_tabelas_do_painel_uma_linha_por_folha_e_por_etapa_na_ordem_do_padrao():
    resultado = _montar_do_painel()
    tabelas = eap_padrao.tabelas_do_painel(resultado)
    ids = [
        f["id"] for b in resultado["tipos"] for e in b["etapas"] for f in e["folhas"]
    ]
    assert [f["folha"] for f in tabelas["folhas"]] == ids
    assert len(set(ids)) == len(ids)
    etapas = [e["id"] for b in resultado["tipos"] for e in b["etapas"]]
    assert [e["etapa"] for e in tabelas["etapas"]] == etapas
    for etapa in tabelas["etapas"]:
        folhas = [f for f in tabelas["folhas"] if f["etapa"] == etapa["etapa"]]
        assert etapa["folhas"] == len(folhas)
        assert etapa["preenchidas"] == sum(
            f["situacao"] == "preenchida" for f in folhas
        )
        assert etapa["mencao"] == sum(f["situacao"] == "só menção" for f in folhas)


def test_tabelas_do_painel_situacao_constante_texto_parcial_e_valores():
    tabelas = eap_padrao.tabelas_do_painel(_montar_do_painel())
    folhas = {f["folha"]: f for f in tabelas["folhas"]}
    parcial = folhas["OP.04.03"]
    assert parcial["situacao"] == "preenchida"
    assert parcial["situacao_txt"] == "preenchida (parcial: 2 sem valor)"
    assert parcial["aponta"].startswith("CIV.EST.PIL")
    assert "5 un" in parcial["quantidade"]
    assert folhas["OL.04.02"]["quantidade"] == "1.500,50 m (extensão)"
    assert folhas["OL.04.02"]["obrigatoria"] in ("sim", "não")
    assert folhas["OL.06.01"]["situacao"] == "não se aplica"
    assert folhas["OP.01.02"]["situacao"] == "só menção"
    assert folhas["OL.04.02"]["evidencias"] == 1


def test_tabelas_do_painel_etapa_citada_no_contrato_e_mencao():
    tabelas = eap_padrao.tabelas_do_painel(_montar_do_painel())
    etapas = {e["etapa"]: e for e in tabelas["etapas"]}
    assert etapas["OP.10"]["citada_no_contrato"] == "sim"
    assert etapas["OP.10"]["linhas_citadas"] == 1
    assert etapas["OP.00"]["citada_no_contrato"] == "não"
    assert etapas["OP.00"]["linhas_citadas"] == 0
    assert etapas["OP.01"]["mencao"] == 1
    folhas = {f["folha"]: f for f in tabelas["folhas"]}
    assert (
        folhas["OP.01.02"]["motivo"] == "citado sem valor"
    )  # aceite do Fable: a razão da só menção aparece


def test_tabelas_do_painel_percentual_com_zero_aplicaveis():
    bloco = {
        "tipo": "obra_linear",
        "nome": "x",
        "etapas": [],
        "resumo": eap_padrao.resumir(
            [{"situacao": "não se aplica", "destaque": False}]
        ),
    }
    linha = eap_padrao.tabelas_do_painel({"tipos": [bloco]})["resumo"][0]
    assert linha["aplicaveis"] == 0 and linha["pct_preenchida"] == 0
    assert linha["pct_txt"] == "—"


def test_tabelas_do_painel_nao_tem_preco_e_esta_nos_metadados():
    tabelas = eap_padrao.tabelas_do_painel(_montar_do_painel())
    chaves = {c for linhas in tabelas.values() for linha in linhas for c in linha}
    assert not [
        c for c in chaves if any(p in c for p in ("preco", "valor_unit", "custo"))
    ]
    assert "R$" not in json.dumps(tabelas, ensure_ascii=False)
    assert "tabelas_do_painel" in eap_padrao.metadados()["funcoes"]
