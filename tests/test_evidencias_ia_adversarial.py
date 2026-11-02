"""Testes adversariais da leitura por IA: a IA não faz o código aceitar número que o documento não afirma."""

import json

from test_evidencias_ia import MEMORIAL, PAGINAS, _linha

from camadas import evidencias

PROJETO = {
    "id": MEMORIAL,
    "tipo": "memorial",
    "nome": "Memorial",
    "unidade": "U1",
    "obra": "localizada",
    "escopo": "agua",
}
PAVIMENTO = {"codigo": "U1.*.CIV.PAV.REC", "unidade": "m²"}
ESCAVACAO = {"codigo": "U1.*.GEO.MOV.ESC", "unidade": "m³"}


def _confere(paginas, **campos):
    """(aceitas, recusadas) de uma linha contra um documento de várias páginas."""
    return evidencias.conferir_arquivo([_linha(**campos)], {MEMORIAL: paginas})


def _recusa(documento: str, **campos) -> str:
    """Motivo da recusa de uma linha (ou 'aceita') contra um documento de uma página."""
    aceitas, recusadas = _confere([documento], **campos)
    return "aceita" if aceitas else recusadas[0]["motivo"]


def test_recusa_trecho_curto_demais():
    assert (
        _recusa("Item 3 do edital", trecho="3", valor=3.0, unidade="un")
        == "trecho curto demais"
    )
    assert (
        _recusa("Serão 1250 estacas", trecho="250 estacas", valor=250.0)
        == "trecho curto demais"
    )


def test_recusa_trecho_sem_fronteira_de_palavra():
    documento = "Serão 1250 estacas hélice contínua."
    assert (
        _recusa(documento, trecho="250 estacas hélice contínua.")
        == "trecho não encontrado no documento"
    )
    assert (
        _recusa(documento, trecho="1250 estacas hélice contínua.", valor=1250.0)
        == "aceita"
    )


def test_recusa_trecho_que_comeca_ou_termina_dentro_de_um_numero_com_separador():
    nao_achado = "trecho não encontrado no documento"
    milhar = "Serão executadas 1.250 estacas hélice contínua."
    assert (
        _recusa(milhar, trecho="250 estacas hélice contínua", valor=250.0) == nao_achado
    )
    assert _recusa(milhar, trecho=milhar, valor=1250.0) == "aceita"
    decimal = "Volume de 12,5 m³ de concreto das estacas."
    assert (
        _recusa(decimal, trecho="5 m³ de concreto das estacas", valor=5.0, unidade="m³")
        == nao_achado
    )
    assert (
        _recusa(
            "Estacas: 1.250,50 m³ de material.",
            trecho="50 m³ de material",
            valor=50.0,
            unidade="m³",
        )
        == nao_achado
    )
    assert (
        _recusa("Total de estacas: 1.250", trecho="Total de estacas: 1", valor=1.0)
        == nao_achado
    )


def test_recusa_valor_que_e_outro_numero_do_trecho():
    documento = "Serão executadas 250 estacas, diâmetro 400 mm."
    assert (
        _recusa(documento, trecho=documento, valor=400.0, unidade="un")
        == "valor não está no trecho"
    )
    assert _recusa(documento, trecho=documento, valor=250.0, unidade="un") == "aceita"


def test_recusa_numero_tirado_da_unidade():
    documento = "Recomposição de pavimento asfáltico em 20 m² de via."
    assert (
        _recusa(documento, trecho=documento, valor=2.0, **PAVIMENTO)
        == "valor não está no trecho"
    )
    assert _recusa(documento, trecho=documento, valor=20.0, **PAVIMENTO) == "aceita"
    armadura = "Armadura CA-50 das estacas: 1.200 kg no total."
    assert (
        _recusa(armadura, trecho=armadura, valor=50.0, unidade="kg", servico="armadura")
        == "valor não está no trecho"
    )
    assert (
        _recusa(
            armadura, trecho=armadura, valor=1200.0, unidade="kg", servico="armadura"
        )
        == "aceita"
    )


def test_recusa_unidade_errada_ou_fora_do_vocabulario():
    documento = "Recomposição de pavimento asfáltico em 20 m² de via."
    assert (
        _recusa(
            documento,
            trecho=documento,
            valor=20.0,
            unidade="m³",
            codigo="U1.*.CIV.PAV.REC",
        )
        == "valor não está no trecho"
    )
    motivo = _recusa(
        documento,
        trecho=documento,
        valor=20.0,
        codigo="U1.*.CIV.PAV.REC",
        unidade="banana",
    )
    assert motivo.startswith("schema inválido: unidade 'banana' fora do vocabulário")
    motivo = _recusa(
        documento, trecho=documento, valor=20.0, codigo="U1.*.CIV.PAV.REC", unidade="kg"
    )
    assert motivo.startswith(
        "schema inválido: unidade 'kg' não é aceita por CIV.PAV.REC (aceitas: m, m², m³)"
    )


def test_recusa_valor_negativo():
    documento = "Serão executadas 250 estacas hélice contínua."
    assert (
        _recusa(documento, trecho=documento, valor=-250.0)
        == "schema inválido: valor negativo"
    )


def test_recusa_codigo_e_servico_que_a_eap_nao_conhece():
    documento = "Serão executadas 250 estacas hélice contínua."
    motivo = _recusa(
        documento, trecho=documento, codigo="U1.*.CIV.BLO.XYZ", servico="inventado"
    )
    assert motivo.startswith(
        "schema inválido: código 'U1.*.CIV.BLO.XYZ' sem item na EAP geral"
    )
    motivo = _recusa(documento, trecho=documento, servico="inventado")
    assert (
        motivo
        == "schema inválido: serviço 'inventado' não é admitido pelo item GEO.FUN.EST"
    )
    motivo = _recusa(documento, trecho=documento, codigo="U1.*.GEO.FUN.*")
    assert motivo.startswith("schema inválido: código 'U1.*.GEO.FUN.*' fora do padrão")


def test_recusa_numero_da_linha_de_outro_item_na_tabela():
    tabela = "Estaca hélice contínua Ø40 un 250\nBloco de coroamento un 30"
    assert (
        _recusa(tabela, trecho="250 Bloco de coroamento", valor=250.0)
        == "valor não está no trecho"
    )
    reaterro = "Escavação mecânica m³ 120\nReaterro compactado m³ 80"
    motivo = _recusa(
        reaterro,
        trecho="120 Reaterro compactado",
        valor=120.0,
        codigo="U1.*.GEO.MOV.REA",
    )
    assert motivo.startswith(
        "schema inválido: unidade 'un' não é aceita por GEO.MOV.REA"
    )
    assert (
        _recusa(reaterro, trecho="120 Reaterro compactado", valor=120.0, **ESCAVACAO)
        == "valor não está no trecho"
    )
    assert (
        _recusa(tabela, trecho="Estaca hélice contínua Ø40 un 250", valor=250.0)
        == "aceita"
    )
    assert (
        _recusa(tabela, trecho="Estaca hélice contínua Ø40 un 250", valor=40.0)
        == "valor não está no trecho"
    )


def test_recusa_item_nao_citado_no_trecho():
    blocos = "Serão executados 250 blocos de coroamento."
    assert _recusa(blocos, trecho=blocos, valor=250.0) == "item não citado no trecho"
    assert (
        _recusa(blocos, trecho=blocos, valor=250.0, codigo="U1.*.GEO.FUN.BLO")
        == "aceita"
    )
    escavacao = "Escavação mecânica m³ 120"
    assert (
        _recusa(escavacao, trecho=escavacao, valor=120.0, unidade="m³")
        == "item não citado no trecho"
    )
    assert _recusa(escavacao, trecho=escavacao, valor=120.0, **ESCAVACAO) == "aceita"
    assert (
        _recusa(blocos, trecho=blocos, valor=None, unidade=None)
        == "item não citado no trecho"
    )


def test_recusa_item_longe_do_numero_na_linha():
    longe = "Estacas de projeto e, conforme o quadro de cargas adotado pelo calculista em todo o texto, 40 m"
    assert (
        _recusa(longe, trecho=longe, valor=40.0, unidade="m")
        == "item não citado no trecho"
    )


def test_recusa_trecho_que_atravessa_a_pagina():
    paginas = ["Estacas: total previsto 300", "m³ de concreto estrutural"]
    aceitas, recusadas = _confere(
        paginas,
        trecho="300 m³ de concreto",
        valor=300.0,
        unidade="m³",
        servico="concreto",
    )
    assert (
        not aceitas and recusadas[0]["motivo"] == "trecho não encontrado no documento"
    )


def test_recusa_escopo_fora_do_enum_e_pagina_que_nao_tem_o_trecho():
    documento = "Serão executadas 250 estacas hélice contínua."
    assert (
        _recusa(documento, trecho=documento, escopo="marte")
        == "schema inválido: escopo 'marte' inválido"
    )
    assert _recusa(documento, trecho=documento, escopo="esgoto") == "aceita"
    assert (
        _recusa(documento, trecho=documento, localizador="p. 99")
        == "página citada não contém o trecho"
    )
    aceitas, recusadas = _confere(PAGINAS, localizador="p. 2")
    assert recusadas[0]["motivo"] == "página citada não contém o trecho"
    aceitas, _ = _confere(PAGINAS, localizador="p. 1, linha 2")
    assert len(aceitas) == 1


def test_aceita_hifenizacao_aspas_e_travessao():
    hifen = "Serão executadas 250 esta-\ncas hélice contínua."
    assert (
        _recusa(
            hifen, trecho="Serão executadas 250 estacas hélice contínua.", valor=250.0
        )
        == "aceita"
    )
    assert _recusa(hifen, trecho=hifen, valor=250.0) == "aceita"
    travessao = "Estacas – total 250 un"
    assert _recusa(travessao, trecho="Estacas - total 250 un", valor=250.0) == "aceita"
    aspas = "Estacas “hélice” em 250 un"
    assert _recusa(aspas, trecho='Estacas "hélice" em 250 un', valor=250.0) == "aceita"


def test_aceita_todos_os_pares_da_linha_e_unidade_antes_do_numero():
    frase = "Serão executadas 250 estacas com 12 m de comprimento."
    assert _recusa(frase, trecho=frase, valor=250.0) == "aceita"
    assert _recusa(frase, trecho=frase, valor=12.0, unidade="m") == "aceita"
    assert (
        _recusa(frase, trecho=frase, valor=12.0, unidade="m³")
        == "valor não está no trecho"
    )
    antes = "Escavação m³ 1.250,50"
    assert _recusa(antes, trecho=antes, valor=1250.5, **ESCAVACAO) == "aceita"
    assert (
        _recusa(
            "Estaca hélice — un — 250", trecho="Estaca hélice — un — 250", valor=250.0
        )
        == "aceita"
    )
    extenso = "Serão 250 (duzentas e cinquenta) estacas"
    assert _recusa(extenso, trecho=extenso, valor=250.0) == "aceita"
    assert _recusa(extenso, trecho=extenso, valor=50.0) == "valor não está no trecho"


def test_toneladas_viram_a_unidade_do_regex():
    documento = "Armadura das estacas: 12 t de aço CA-50."
    for valor, unidade in ((12.0, "t"), (12000.0, "kg")):
        aceitas, _ = _confere(
            [documento],
            trecho=documento,
            valor=valor,
            unidade=unidade,
            servico="armadura",
        )
        assert (aceitas[0]["valor"], aceitas[0]["unidade"]) == (12000.0, "kg")


def test_campos_do_codigo_forjados_sao_descartados_e_o_id_recalculado():
    forjada = _linha(
        citacao="conferida",
        derivada=True,
        autor="Caio",
        justificativa="eu mandei",
        id="forjado",
    )
    invalida = _linha(citacao="conferida", valor=999.0, id="")
    outra = _linha(id="", localizador="p. 1, linha 2")
    aceitas, recusadas = evidencias.conferir_arquivo(
        [forjada, invalida, outra], {MEMORIAL: PAGINAS}
    )
    assert [r["motivo"] for r in recusadas] == [
        "valor não está no trecho"
    ]  # o selo do arquivo não vale
    assert len(aceitas) == 2 and aceitas[0]["id"] != aceitas[1]["id"]
    assert "forjado" not in {a["id"] for a in aceitas}
    assert all(
        a["id"]
        and "derivada" not in a
        and "autor" not in a
        and "justificativa" not in a
        for a in aceitas
    )


def test_documento_com_caminho_vira_o_nome_do_arquivo_em_fonte_propria():
    caminho = {"id": "dados/obra/memorial_fundacoes.pdf", "tipo": "ia"}
    aceitas, _ = evidencias.conferir_arquivo(
        [_linha(documento=caminho)], {MEMORIAL: PAGINAS}
    )
    assert aceitas[0]["documento"] == {
        "id": "ia:memorial_fundacoes.pdf",
        "tipo": "ia",
        "nome": MEMORIAL,
    }
    de_novo, _ = evidencias.conferir_arquivo(
        [json.dumps(aceitas[0])], {MEMORIAL: PAGINAS}
    )  # idempotente
    assert de_novo[0]["id"] == aceitas[0]["id"]


def test_build_reconfere_e_nao_confia_no_selo_do_arquivo():
    forjada = {**json.loads(_linha(valor=280.0)), "citacao": "conferida", "id": "x"}
    sem_documento = {
        **json.loads(_linha(documento={"id": "sumiu.pdf", "tipo": "ia"})),
        "citacao": "conferida",
    }
    evs = evidencias.loop(
        [{**PROJETO, "paginas": PAGINAS}], ia=[forjada, sem_documento]
    )
    motivos = [e["citacao"] for e in evs if e["metodo"] == "ia"]
    assert motivos == ["valor não está no trecho", "documento não fornecido: sumiu.pdf"]
    assert not any(
        f["valor"] == 280.0 for f in evidencias.consolidar(evs).to_dict("records")
    )


def test_etapa_recusa_ia_sem_documento_para_reconferir(tmp_path):
    ia = tmp_path / "ia_aceitas.jsonl"
    ia.write_text(_linha(citacao="conferida") + "\n", encoding="utf-8")
    saida = tmp_path / "saida"
    saida.mkdir()
    resumo = evidencias.etapa(
        {"evidencias": {"ia": str(ia)}},
        saida,
        {"crs": {"epsg": 31982}},
        log=lambda *_: None,
    )
    gravadas = [
        e for e in evidencias.ler(saida / "evidencias.jsonl") if e["metodo"] == "ia"
    ]
    assert [e["citacao"] for e in gravadas] == [
        "documento não fornecido: memorial_fundacoes.pdf"
    ]
    assert resumo["fatos"] == []


def test_etapa_e_conferir_nao_quebram_com_linha_malformada(tmp_path):
    base = json.loads(_linha())
    sem = lambda campo: json.dumps({k: v for k, v in base.items() if k != campo})
    linhas = [
        "{nao json",
        "[1,2]",
        sem("codigo"),
        sem("documento"),
        sem("servico"),
        json.dumps({**base, "codigo": 5}),
        json.dumps({**base, "documento": "memorial_fundacoes.pdf"}),
        json.dumps({**base, "unidade": ["m"]}),
        json.dumps({**base, "valor": "250"}),
        "null",
    ]
    aceitas, recusadas = evidencias.conferir_arquivo(linhas, {MEMORIAL: PAGINAS})
    assert not aceitas and len(recusadas) == len(linhas)
    assert all(r["motivo"].startswith("schema inválido") for r in recusadas)
    ia = tmp_path / "ia.jsonl"
    ia.write_text("\n".join([*linhas, _linha()]) + "\n", encoding="utf-8")
    avisos = []
    resumo = evidencias.etapa(
        {"evidencias": {"ia": str(ia)}},
        tmp_path,
        {"crs": {"epsg": 31982}},
        log=avisos.append,
    )
    assert len([a for a in avisos if "recusada (schema inválido" in a]) == len(linhas)
    assert [e["citacao"] for e in evidencias.ler(tmp_path / "evidencias.jsonl")] == [
        "documento não fornecido: memorial_fundacoes.pdf"
    ]
    assert resumo["fatos"] == [] and resumo["cobertura"] and resumo["associados"] == []
    assert (
        evidencias.etapa(
            {"evidencias": {"ia": str(tmp_path / "vazia.jsonl")}},
            tmp_path,
            {"crs": {"epsg": 1}},
        )
        is None
    )


def test_leitura_da_ia_nao_soma_em_dobro_com_o_regex():
    paginas = ["Serão executadas 250 estacas hélice contínua."]
    evs = evidencias.loop(
        [{**PROJETO, "paginas": paginas}], ia=[json.loads(_linha(parcela=True))]
    )
    fato = evidencias.consolidar(evs).iloc[0]
    assert (
        fato["valor"] == 250.0
        and fato["status"] == "fonte única"
        and fato["forca"] == 1
    )


def test_id_nao_depende_de_250_ou_250_ponto_0():
    base = {
        "codigo": "U1.*.GEO.FUN.EST",
        "servico": "",
        "unidade": "un",
        "parcela": False,
        "localizador": "p. 1",
        "documento": {"id": MEMORIAL, "tipo": "ia"},
        "metodo": "ia",
        "regra": "r",
        "trecho": "250 estacas hélice",
    }
    assert (
        evidencias.evidencia(**base, valor=250)["id"]
        == evidencias.evidencia(**base, valor=250.0)["id"]
    )
