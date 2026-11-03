"""Terceira rodada adversarial da leitura por IA: parcelas, itens vizinhos, valores gigantes e desempenho."""

import json
import time

from test_evidencias_ia import MEMORIAL, _linha

from camadas import evidencias


def _confere(paginas, **campos):
    return evidencias.conferir_arquivo([_linha(**campos)], {MEMORIAL: paginas})


def _recusa(documento: str, **campos) -> str:
    aceitas, recusadas = _confere([documento], **campos)
    return "aceita" if aceitas else recusadas[0]["motivo"]


def _fato(paginas, trechos, parcelas, valores):
    """Fato consolidado de várias propostas (trecho, parcela) lidas em `paginas` do mesmo documento."""
    linhas = [
        _linha(trecho=t, parcela=p, valor=v, localizador=f"p. {i}")
        for i, (t, p, v) in enumerate(zip(trechos, parcelas, valores), 1)
    ]
    aceitas, recusadas = evidencias.conferir_arquivo(linhas, {MEMORIAL: paginas})
    assert not recusadas
    return evidencias.consolidar(aceitas).iloc[0]


def test_parcelas_reais_iguais_somam_e_a_mesma_frase_repetida_conta_uma_vez():
    b1, b2 = "Bloco B1 com 12 estacas hélice.", "Bloco B2 com 12 estacas hélice."
    assert _fato([b1, b2], [b1, b2], [True, True], [12.0, 12.0])["valor"] == 24.0
    resumo = "Resumo: 250 estacas hélice contínua."
    assert (
        _fato([resumo, resumo], [resumo, resumo], [True, True], [250.0, 250.0])["valor"]
        == 250.0
    )


def test_parcelas_e_total_iguais_nao_viram_convergencia_falsa():
    b1, b2, total = (
        "B1: 50 estacas hélice.",
        "B2: 50 estacas hélice.",
        "Total: 50 estacas hélice.",
    )
    fato = _fato([b1, b2, total], [b1, b2, total], [True, True, False], [50.0] * 3)
    assert fato["status"] == "conflito"


def test_dedupe_por_id_so_vale_para_a_ia():
    base = {
        "codigo": "U1.*.GEO.FUN.EST",
        "servico": "",
        "unidade": "un",
        "valor": 50.0,
        "parcela": True,
        "documento": {"id": "planilha.xlsx", "tipo": "planilha"},
        "localizador": "",
        "trecho": "trecho",
        "metodo": "planilha",
        "regra": "r",
    }
    duas = [evidencias.evidencia(**base), evidencias.evidencia(**base)]
    assert (
        evidencias.consolidar(duas).iloc[0]["valor"] == 100.0
    )  # duas parcelas iguais somam
    ia = {
        **base,
        "metodo": "ia",
        "documento": {"id": "ia:memorial.pdf", "tipo": "ia"},
        "citacao": "conferida",
    }
    assert (
        evidencias.consolidar([evidencias.evidencia(**ia)] * 2).iloc[0]["valor"] == 50.0
    )


def test_id_da_ia_inclui_a_parcela_e_o_das_outras_fontes_nao_muda():
    ia = {
        "codigo": "U1.*.GEO.FUN.EST",
        "servico": "",
        "unidade": "un",
        "valor": 5.0,
        "localizador": "p. 1",
        "documento": {"id": MEMORIAL, "tipo": "ia"},
        "metodo": "ia",
        "regra": "r",
        "trecho": "5 estacas hélice",
    }
    assert (
        evidencias.evidencia(**ia, parcela=True)["id"]
        != evidencias.evidencia(**ia, parcela=False)["id"]
    )
    regex = {**ia, "metodo": "regex", "documento": {"id": MEMORIAL, "tipo": "memorial"}}
    assert (
        evidencias.evidencia(**regex, parcela=True)["id"]
        == evidencias.evidencia(**regex, parcela=False)["id"]
    )


def test_numero_de_metros_ou_unidade_no_meio_nao_e_contagem_de_itens():
    metros = "Total de 3.000 metros de estacas hélice."
    assert (
        _recusa(metros, trecho=metros, valor=3000.0, unidade="un")
        == "valor não está no trecho"
    )
    assert _recusa(metros, trecho=metros, valor=3000.0, unidade="m") == "aceita"
    estaca = "Serão 12 m de estaca hélice cravada."
    assert (
        _recusa(estaca, trecho=estaca, valor=12.0, unidade="un")
        == "valor não está no trecho"
    )
    assert _recusa(estaca, trecho=estaca, valor=12.0, unidade="m") == "aceita"


def test_valor_gigante_ou_nao_finito_vira_recusa_sem_estourar():
    documento = "Serão executadas 250 estacas hélice contínua."
    for valor in (10**400, 1e13, float("nan"), float("inf"), -1e13):
        motivo = _recusa(documento, trecho=documento, valor=valor)
        assert motivo.startswith("schema inválido: valor fora do intervalo"), valor
    aceitas, recusadas = evidencias.conferir_arquivo(
        [json.dumps({"valor": 10**400})], {}
    )
    assert not aceitas and recusadas[0]["motivo"].startswith("schema inválido")
    ev = json.loads(_linha(trecho=documento))
    assert (
        evidencias.conferir_citacao({**ev, "valor": 10**400}, [documento])["citacao"]
        == "valor não está no trecho"
    )


def test_numero_de_outro_item_na_mesma_linha_e_recusado():
    bloco = "Bloco de coroamento para 2 estacas un 12"
    assert _recusa(bloco, trecho=bloco, valor=12.0) == "número pertence a outro item"
    assert (
        _recusa(bloco, trecho=bloco, valor=12.0, codigo="U1.*.GEO.FUN.BLO") == "aceita"
    )
    assert (
        _recusa(bloco, trecho=bloco, valor=2.0) == "aceita"
    )  # o "2 estacas" é do item estacas
    linha = "Estaca hélice contínua un 250 Bloco de coroamento un 30"
    assert _recusa(linha, trecho=linha, valor=30.0) == "número pertence a outro item"
    assert (
        _recusa(linha, trecho=linha, valor=30.0, codigo="U1.*.GEO.FUN.BLO") == "aceita"
    )


def test_milhar_com_espaco_e_barrado_mas_unidade_com_algarismo_nao():
    for espaco in (" ", " ", " "):
        documento = f"Total de 1{espaco}250 estacas hélice contínua."
        motivo = _recusa(documento, trecho="250 estacas hélice contínua", valor=250.0)
        assert motivo == "trecho não encontrado no documento"
    escavacao = "Escavação mecânica m³ 120"
    assert (
        _recusa(
            escavacao,
            trecho="120",
            valor=120.0,
            unidade="m³",
            codigo="U1.*.GEO.MOV.ESC",
        )
        == "trecho curto demais"
    )
    tabela = "Escavação mecânica m³ 120 e reaterro"
    assert (
        _recusa(
            tabela,
            trecho="120 e reaterro",
            valor=120.0,
            unidade="m³",
            codigo="U1.*.GEO.MOV.ESC",
        )
        != "trecho não encontrado no documento"
    )


def test_mencao_com_unidade_fora_do_vocabulario_e_recusada():
    documento = "Serão executadas 250 estacas hélice contínua."
    motivo = _recusa(documento, trecho=documento, valor=None, unidade="banana")
    assert motivo.startswith("schema inválido: unidade 'banana' fora do vocabulário")
    assert _recusa(documento, trecho=documento, valor=None, unidade=None) == "aceita"


def test_hifen_de_fim_de_linha_em_caixa_alta():
    documento = "SERÃO EXECUTADAS 250 ESTA-\nCAS HÉLICE CONTÍNUA."
    assert (
        _recusa(
            documento,
            trecho="SERÃO EXECUTADAS 250 ESTACAS HÉLICE CONTÍNUA.",
            valor=250.0,
        )
        == "aceita"
    )


def test_localizador_aceita_pag_e_e_o_indice_da_pagina():
    paginas = [
        "Capa do memorial de fundações",
        "Serão executadas 250 estacas hélice contínua.",
    ]
    for localizador, esperado in (
        ("pág. 2", True),
        ("pag. 2", True),
        ("p. 2", True),
        ("pág. 1", False),
        ("p. 1", False),
    ):
        aceitas, recusadas = _confere(paginas, localizador=localizador)
        assert bool(aceitas) is esperado, localizador
        if not esperado:
            assert recusadas[0]["motivo"] == "página citada não contém o trecho"


def test_numero_colado_a_letra_nao_e_quantidade():
    armadura = "Armadura CA-50 das estacas: 1.200 kg no total."
    assert _recusa(
        armadura, trecho=armadura, valor=50.0, unidade="un", servico="armadura"
    ).startswith("schema inválido")
    tubo = "Estacas DN150 un 40 conforme projeto."
    assert (
        _recusa(tubo, trecho=tubo, valor=150.0, unidade="un")
        == "valor não está no trecho"
    )


def test_desempenho_com_muitas_paginas_e_evidencias():
    paginas = [
        "\n".join(
            f"Item {p}.{n} serão executadas {p * 100 + n} estacas hélice contínua, diâmetro 400 mm."
            for n in range(50)
        )
        for p in range(1, 101)
    ]
    linhas = [
        _linha(
            trecho=f"Item {p}.{n} serão executadas {p * 100 + n} estacas hélice contínua",
            valor=float(p * 100 + n),
            localizador=f"p. {p}",
        )
        for p in range(1, 101, 5)
        for n in range(0, 50, 5)
    ]
    inicio = time.perf_counter()
    aceitas, recusadas = evidencias.conferir_arquivo(linhas, {MEMORIAL: paginas})
    assert len(aceitas) == len(linhas) and not recusadas
    assert time.perf_counter() - inicio < 10
