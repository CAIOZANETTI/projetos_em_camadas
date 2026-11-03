"""Conferência por bloco de linha de tabela: até 3 linhas seguidas, o par (valor, unidade) na última linha."""

import pytest
from test_evidencias_ia import MEMORIAL, _linha

from camadas import evidencias

ESTACA = "U1.*.GEO.FUN.EST"
BLOCO = "U1.*.GEO.FUN.BLO"


def _resultado(paginas, **campos) -> str:
    """'aceita' ou o motivo exato da recusa."""
    trecho = campos.setdefault("trecho", paginas[0])
    campos.setdefault("localizador", "p. 1" if trecho in paginas[0] else "p. 2")
    aceitas, recusadas = evidencias.conferir_arquivo(
        [_linha(**campos)], {MEMORIAL: paginas}
    )
    return "aceita" if aceitas else recusadas[0]["motivo"]


@pytest.mark.parametrize(
    "documento",
    [
        "Estaca hélice contínua, diâmetro 40 cm, inclusive\nmobilização e desmobilização un 250",
        "Estacas hélice contínua Ø40 cm\nQuantidade: 250 un",
        "Estacas hélice contínua Ø 40 cm\nQuantidade: 250 un",
        "Estaca hélice contínua DN 400 mm\nQuantidade: 250 un",
        "3.1 Estaca hélice contínua\ndiâmetro 40 cm, profundidade a definir\nQtde: 250 un",
        "Estaca hélice contínua\nQuantidade:\n250 un",
    ],
)
def test_bloco_de_ate_tres_linhas_com_a_quantidade_na_ultima_e_aceito(documento):
    assert _resultado([documento], valor=250.0, unidade="un") == "aceita"


def test_bloco_no_meio_da_pagina_e_aceito_e_o_texto_em_volta_nao_conta():
    pagina = "Fundações\n\nEstacas hélice contínua Ø40 cm\nQuantidade: 250 un\n\nBloco de coroamento un 30\n"
    trecho = "Estacas hélice contínua Ø40 cm\nQuantidade: 250 un"
    assert _resultado([pagina], trecho=trecho, valor=250.0, unidade="un") == "aceita"
    # o bloco vizinho, em outra linha em branco, continua sendo outro item
    assert (
        _resultado(
            [pagina],
            trecho="Bloco de coroamento un 30",
            valor=30.0,
            unidade="un",
            codigo=BLOCO,
        )
        == "aceita"
    )


def test_bloco_so_vale_com_o_par_na_ultima_linha():
    documento = "Quantidade: 250 un\nEstaca hélice contínua Ø40 cm"
    assert (
        _resultado([documento], valor=250.0, unidade="un")
        == "item não citado no trecho"
    )
    assert _resultado(
        ["Estaca hélice contínua\nQuantidade: 250 un"], valor=300.0, unidade="un"
    ) == ("valor não está no trecho")


def test_bloco_com_duas_linhas_de_tabela_de_itens_diferentes_continua_recusado():
    documento = "Estaca hélice contínua un 250\nBloco de coroamento un 30"
    assert (
        _resultado([documento], valor=30.0, unidade="un") == "item não citado no trecho"
    )
    assert (
        _resultado([documento], valor=250.0, unidade="un", codigo=BLOCO)
        == "item não citado no trecho"
    )
    # a linha de cima já afirma uma quantidade: ela encerra o bloco, mesmo com o termo do item nela
    documento3 = "Estaca hélice contínua\nBloco de coroamento\nun 30"
    assert (
        _resultado([documento3], valor=30.0, unidade="un")
        == "item não citado no trecho"
    )
    assert (
        _resultado([documento3], valor=30.0, unidade="un", codigo=BLOCO)
        == "item não citado no trecho"
    )


def test_numero_com_unidade_de_quantidade_na_linha_anterior_encerra_o_bloco():
    # 'cm' não é unidade de quantidade do vocabulário: '40 cm' solto é medida de especificação e não encerra o bloco
    assert (
        _resultado(
            ["Estaca hélice contínua 40 cm\nQuantidade: 250 un"],
            valor=250.0,
            unidade="un",
        )
        == "aceita"
    )
    # 'm', 'un' e 'estacas' contam como quantidade, com ou sem termo de item na linha
    for anterior in (
        "Estaca hélice contínua, 12 m",
        "Estaca hélice contínua, un 12",
        "12 estacas hélice contínua",
    ):
        assert (
            _resultado([anterior + "\nQuantidade: 250 un"], valor=250.0, unidade="un")
            == "item não citado no trecho"
        )


def test_bloco_de_quatro_linhas_e_recusado():
    documento = "Estaca hélice contínua\nconforme projeto\nincluindo mobilização\nQuantidade: 250 un"
    assert (
        _resultado([documento], valor=250.0, unidade="un")
        == "item não citado no trecho"
    )
    tres = "Estaca hélice contínua\nincluindo mobilização\nQuantidade: 250 un"
    assert _resultado([tres], valor=250.0, unidade="un") == "aceita"


def test_bloco_com_linha_em_branco_e_recusado():
    documento = "Estaca hélice contínua Ø40 cm\n\nQuantidade: 250 un"
    assert (
        _resultado([documento], valor=250.0, unidade="un")
        == "item não citado no trecho"
    )
    com_espacos = "Estaca hélice contínua Ø40 cm\n   \t\nQuantidade: 250 un"
    assert (
        _resultado([com_espacos], valor=250.0, unidade="un")
        == "item não citado no trecho"
    )


def test_bloco_nao_atravessa_pagina():
    paginas = ["Estaca hélice contínua Ø40 cm", "Quantidade: 250 un"]
    trecho = "Estaca hélice contínua Ø40 cm\nQuantidade: 250 un"
    assert (
        _resultado(paginas, trecho=trecho, valor=250.0, unidade="un")
        == "trecho não encontrado no documento"
    )
    # a quantidade sozinha na outra página não tem item
    assert _resultado(
        paginas,
        trecho="Quantidade: 250 un",
        valor=250.0,
        unidade="un",
        localizador="p. 2",
    ) == ("item não citado no trecho")


def test_quantidade_sozinha_de_outro_item_nao_vira_estaca():
    assert (
        _resultado(["Bloco de coroamento\nun 30"], valor=30.0, unidade="un")
        == "item não citado no trecho"
    )
    assert (
        _resultado(
            ["Bloco de coroamento\nun 30"], valor=30.0, unidade="un", codigo=BLOCO
        )
        == "aceita"
    )


def test_bloco_continua_respeitando_unidade_e_valor():
    documento = "Estaca hélice contínua Ø40 cm\nQuantidade: 250 un"
    assert (
        _resultado([documento], valor=250.0, unidade="m") == "valor não está no trecho"
    )
    assert (
        _resultado([documento], valor=25.0, unidade="un") == "valor não está no trecho"
    )


def test_marca_de_linha_em_branco_so_existe_na_pagina_normalizada():
    texto = "A linha\n\n   \nOutra linha\nTerceira"
    assert evidencias._linhas_normalizadas(texto) == [
        "A LINHA",
        "OUTRA LINHA",
        "TERCEIRA",
    ]
    marcadas = evidencias._linhas_normalizadas(texto, marcar_brancos=True)
    assert marcadas == ["A LINHA", evidencias._BRANCO, "OUTRA LINHA", "TERCEIRA"]
    assert evidencias._linhas_normalizadas("\n\nA\nB\n\n", marcar_brancos=True) == [
        "A",
        "B",
    ]


def _com_trecho(pagina, trecho, **campos) -> str:
    return _resultado([pagina], trecho=trecho, **campos)


def test_bloco_se_expande_ate_as_linhas_inteiras_da_pagina():
    # trecho recortado não esconde a quantidade que a linha inteira tem antes do recorte
    pagina = "250 un Estaca hélice contínua\n30 un Arrasamento de cabeça"
    trecho = "Estaca hélice contínua\n30 un Arrasamento de cabeça"
    assert (
        _com_trecho(pagina, trecho, valor=30.0, unidade="un")
        == "item não citado no trecho"
    )
    pagina = "Tubo PVC m 300 Estaca hélice contínua\nun 250"
    assert _com_trecho(
        pagina, "Estaca hélice contínua\nun 250", valor=250.0, unidade="un"
    ) == ("item não citado no trecho")
    # o que sobra depois do recorte entra no item mais próximo: o 30 é do bloco, não da estaca
    pagina = "Estaca hélice contínua\nun 30 Bloco de coroamento un 250"
    assert _com_trecho(
        pagina, "Estaca hélice contínua\nun 30", valor=30.0, unidade="un"
    ) == ("número pertence a outro item")
    # trecho que cobre só o meio da linha, com as linhas inteiras limpas, continua valendo
    pagina = "Estacas hélice contínua Ø40 cm\nQuantidade: 250 un"
    assert (
        _com_trecho(
            pagina, "hélice contínua Ø40 cm\nQuantidade: 250", valor=250.0, unidade="un"
        )
        == "aceita"
    )


@pytest.mark.parametrize(
    ("pagina", "valor", "unidade"),
    [
        ("FUNDAÇÕES – ESTACAS\nConcreto fck 30 MPa para blocos m³ 45", 45.0, "m³"),
        ("3. FUNDAÇÕES – ESTACAS\nBloco B1 - concreto m³ 12", 12.0, "m³"),
        ("Estacas hélice contínua\nTotal geral do orçamento un 999", 999.0, "un"),
        ("Estacas – Item Descrição Un Qtd\n3.2 Arrasamento un 30", 30.0, "un"),
        ("Estacas hélice contínua\nTotal m³ 999", 999.0, "m³"),
        ("FUNDAÇÕES – ESTACAS\nArrasamento de cabeça\nun 30", 30.0, "un"),
    ],
)
def test_titulo_ou_cabecalho_nao_vale_para_qualquer_quantidade_da_linha_de_baixo(
    pagina, valor, unidade
):
    assert (
        _resultado([pagina], valor=valor, unidade=unidade)
        == "item não citado no trecho"
    )


def test_continuacao_de_descricao_tem_dois_lados():
    # minúscula ou conectivo, com a linha de cima aberta: continua
    assert (
        _resultado(
            ["Estaca hélice contínua, inclusive\nmobilização un 250"],
            valor=250.0,
            unidade="un",
        )
        == "aceita"
    )
    assert (
        _resultado(
            ["Estaca hélice contínua\nCOM MOBILIZAÇÃO un 250"],
            valor=250.0,
            unidade="un",
        )
        == "aceita"
    )
    # a linha de cima fechada (ponto) encerra a descrição
    assert _resultado(
        ["Estaca hélice contínua.\nmobilização un 250"], valor=250.0, unidade="un"
    ) == ("item não citado no trecho")
    # maiúscula sem conectivo é outra descrição; 'Total' não é rótulo de quantidade
    assert _resultado(
        ["Estaca hélice contínua\nMobilização un 250"], valor=250.0, unidade="un"
    ) == ("item não citado no trecho")
    assert (
        _resultado(["Estaca hélice contínua\nTotal: 250 un"], valor=250.0, unidade="un")
        == "item não citado no trecho"
    )
    # rótulos de quantidade valem
    for rotulo in ("Qtd", "Qtde.", "Quant.", "QUANTIDADE:"):
        assert (
            _resultado(
                [f"Estaca hélice contínua\n{rotulo} 250 un"], valor=250.0, unidade="un"
            )
            == "aceita"
        )


@pytest.mark.parametrize(
    ("pagina", "valor", "unidade", "codigo"),
    [
        ("Tubo PVC DN 150 m 350\nun 4", 4.0, "un", "U1.*.HID.TUB.RED"),
        ("Estacas diâmetro 0,40 m 250\nun 30", 30.0, "un", ESTACA),
        ("Diâmetro 250 estacas\nun 30", 30.0, "un", ESTACA),
        ("Estacas Ø 250 un\nun 30", 30.0, "un", ESTACA),
    ],
)
def test_dimensao_so_some_com_unidade_de_comprimento_e_sem_numero_depois(
    pagina, valor, unidade, codigo
):
    assert (
        _resultado([pagina], valor=valor, unidade=unidade, codigo=codigo)
        == "item não citado no trecho"
    )


def test_dimensao_precisa_de_fronteira_de_palavra_a_esquerda():
    assert evidencias._tem_quantidade("TUBO CODN 150 M") is True
    assert evidencias._tem_quantidade("TUBO DN 150 MM") is False
    assert evidencias._tem_quantidade("ESTACAS Ø 0,40 M") is False


def test_quebra_de_pagina_dentro_do_texto_de_entrada_nao_junta_blocos():
    pagina = "Estaca hélice contínua\fQuantidade: 250 un"
    trecho = "Estaca hélice contínua\nQuantidade: 250 un"
    assert (
        _com_trecho(pagina, trecho, valor=250.0, unidade="un", localizador="p. 1")
        == "item não citado no trecho"
    )
