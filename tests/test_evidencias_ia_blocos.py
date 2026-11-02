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
        == "número pertence a outro item"
    )
    assert _resultado([documento3], valor=30.0, unidade="un", codigo=BLOCO) == "aceita"


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
