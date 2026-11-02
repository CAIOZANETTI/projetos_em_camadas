"""Calibração de premissas: premissa implícita (só fórmula linear em uma premissa), tabela premissa × observado."""

import pandas as pd
import pytest

from camadas import associados, calibracao, dimensoes, evidencias

EDITAL = {"id": "edital.pdf", "tipo": "edital", "nome": "edital"}
MEMORIAL = {"id": "memorial.pdf", "tipo": "memorial", "nome": "memorial"}
VIGA = "U1.ACT600.CIV.EST.VIG"
LAJE = "U1.ACT600.CIV.EST.PIS"


def _elementos():
    """Viga 0,2 × 0,5 × 10 m (V = 1 m³) e laje apoiada no solo de 40 m² (A_fundo = 40)."""
    return dimensoes.de_declarados(
        [
            {
                "id": "v1",
                "tipo": "viga",
                "unidade": "U1",
                "sistema": "ACT600",
                "dimensoes": {"b": 0.2, "h": 0.5, "L": 10.0},
            },
            {
                "id": "l1",
                "tipo": "laje",
                "unidade": "U1",
                "sistema": "ACT600",
                "dimensoes": {"A": 40.0, "e": 0.15, "suspensa": 0.0},
            },
        ]
    )


def _fato(codigo, servico, unidade, valor, documento):
    return evidencias.evidencia(
        documento=documento,
        localizador="p1",
        metodo="regex",
        codigo=codigo,
        servico=servico,
        unidade=unidade,
        valor=valor,
        parcela=False,
        regra="teste",
        trecho=f"{servico} {valor} {unidade}",
    )


def _cenario(observados: list[tuple]):
    """(evs_associados, fatos, elementos): os associados dos elementos mais as evidências (codigo, servico, unidade,
    valor, documento) de fora."""
    elementos = _elementos()
    associados_evs, _, _ = associados.aplicar(elementos)
    externas = [_fato(*o) for o in observados]
    return associados_evs, evidencias.consolidar(associados_evs + externas), elementos


def _linha(tab, codigo, servico):
    return tab.set_index(["codigo", "servico"]).loc[(codigo, servico)]


def _taxa_viga():
    regra = next(r for r in associados.REGRAS if r["id"] == "armadura")
    return regra["premissas"]["taxa"]["valor"]["viga"]


def test_armadura_20_por_cento_acima_da_taxa_diverge_e_implica_1_2_vezes():
    evs, fatos, els = _cenario([(VIGA, "armadura", "kg", 1.2 * _taxa_viga(), EDITAL)])
    linha = _linha(calibracao.tabela(evs, fatos, els), VIGA, "armadura")
    assert linha["situacao"] == "diverge"
    assert linha["premissa"] == "taxa" and linha["valor_premissa"] == pytest.approx(
        _taxa_viga()
    )
    assert linha["razao"] == pytest.approx(1.2) and linha[
        "diferenca_pct"
    ] == pytest.approx(20.0)
    assert linha["premissa_implicita"] == pytest.approx(1.2 * _taxa_viga())
    assert linha["documentos"] == "edital.pdf"


def test_lastro_com_fato_igual_confere():
    evs, fatos, els = _cenario(
        [
            (LAJE, "lastro", "m³", 40 * 0.05, EDITAL),
            (LAJE, "lastro", "m³", 40 * 0.05, MEMORIAL),
        ]
    )
    linha = _linha(calibracao.tabela(evs, fatos, els), LAJE, "lastro")
    assert linha["situacao"] == "confere" and linha["premissa"] == "e_lastro"
    assert linha["premissa_implicita"] == pytest.approx(0.05)
    assert linha["documentos"] == "edital.pdf; memorial.pdf"


def test_regra_nao_linear_nao_calibra_e_nao_da_numero():
    regra = {
        "id": "vala_teste",
        "tipos": ["viga"],
        "formula": "max(L * largura, 3) + (1 if largura > 1 else 0)",
        "premissas": {"largura": {"valor": 0.8}},
    }
    r = calibracao.premissa_implicita(regra, _elementos(), 50.0)
    assert (
        r["premissa_implicita"] is None
        and "não calibrável por proporção" in r["motivo"]
    )
    regra_if = {**regra, "formula": "L * largura if largura > 0.5 else 0"}
    assert (
        calibracao.premissa_implicita(regra_if, _elementos(), 50.0)[
            "premissa_implicita"
        ]
        is None
    )


def test_regra_com_termo_constante_nao_passa_no_teste_de_zero():
    regra = {
        "id": "x",
        "tipos": ["viga"],
        "formula": "L * p + 2",
        "premissas": {"p": {"valor": 1.0}},
    }
    assert (
        calibracao.premissa_implicita(regra, _elementos(), 15.0)["premissa_implicita"]
        is None
    )


def test_regra_linear_direta():
    regra = {
        "id": "x",
        "tipos": ["viga"],
        "formula": "V * p",
        "premissas": {"p": {"valor": 80.0}},
    }
    r = calibracao.premissa_implicita(regra, _elementos(), 96.0)
    assert r["calculado"] == pytest.approx(80.0) and r[
        "premissa_implicita"
    ] == pytest.approx(96.0)


def test_fato_em_conflito_nao_calibra():
    evs, fatos, els = _cenario(
        [
            (VIGA, "armadura", "kg", 100.0, EDITAL),
            (VIGA, "armadura", "kg", 150.0, MEMORIAL),
        ]
    )
    linha = _linha(calibracao.tabela(evs, fatos, els), VIGA, "armadura")
    assert (
        linha["situacao"] == "não calibrável" and linha["motivo"] == "fato em conflito"
    )
    assert pd.isna(linha["premissa_implicita"]) and pd.isna(linha["observado"])


def test_associado_sem_fato_fica_fora_da_tabela():
    evs, fatos, els = _cenario([(VIGA, "armadura", "kg", 100.0, EDITAL)])
    assert list(calibracao.tabela(evs, fatos, els)["servico"]) == [
        "armadura"
    ]  # forma, lastro… sem fato: fora
    assert calibracao.tabela(evs, pd.DataFrame(), els).empty


def test_decisao_vale_como_observado_e_premissa_nao_e_alterada():
    antes = repr(associados.REGRAS)
    elementos = _elementos()
    evs_assoc, _, _ = associados.aplicar(elementos)
    decisao = evidencias.decisao(
        VIGA, "armadura", "kg", 2 * _taxa_viga(), "caio", "lista de ferros"
    )
    fatos = evidencias.consolidar(evs_assoc + [decisao])
    linha = _linha(calibracao.tabela(evs_assoc, fatos, elementos), VIGA, "armadura")
    assert (
        linha["premissa_implicita"] == pytest.approx(2 * _taxa_viga())
        and linha["documentos"] == "decisão de caio"
    )
    assert repr(associados.REGRAS) == antes


def test_o_proprio_associado_nao_calibra_a_si_mesmo():
    evs, fatos, els = _cenario([])
    assert calibracao.tabela(evs, fatos, els).empty


def test_determinismo_do_csv(tmp_path):
    saidas = []
    for i in range(2):
        evs, fatos, els = _cenario(
            [
                (VIGA, "armadura", "kg", 130.0, EDITAL),
                (LAJE, "lastro", "m³", 2.0, EDITAL),
            ]
        )
        caminho = tmp_path / f"c{i}.csv"
        calibracao.tabela(evs, fatos, els).to_csv(
            caminho, sep=";", decimal=",", encoding="utf-8-sig", index=False
        )
        saidas.append(caminho.read_bytes())
    assert saidas[0] == saidas[1] and len(saidas[0]) > 50


# --- revisão independente: agrupamento, calculado do grupo, curinga, unidades, erros ---------------------------------
def _viga(ident, unidade="U1", comprimento=10.0):
    return {
        "id": ident,
        "tipo": "viga",
        "unidade": unidade,
        "sistema": "ACT600",
        "dimensoes": {"b": 0.2, "h": 0.5, "L": comprimento},
    }


def _rodar(declarados, externas):
    elementos = dimensoes.de_declarados(declarados)
    evs, _, _ = associados.aplicar(elementos)
    todas = evs + [_fato(*o) for o in externas]
    fatos = evidencias.consolidar([e for e in todas if e["metodo"] != "associado"])
    return calibracao.tabela(todas, fatos, elementos)


def test_mesmo_id_em_duas_unidades_nao_soma_elementos():
    tab = _rodar(
        [_viga("V1", "U1"), _viga("V1", "U2")],
        [(VIGA, "armadura", "kg", _taxa_viga(), EDITAL)],
    )
    linha = _linha(tab, VIGA, "armadura")
    assert (
        linha["calculado"] == pytest.approx(_taxa_viga())
        and linha["situacao"] == "confere"
    )
    assert linha["premissa_implicita"] == pytest.approx(_taxa_viga())


def test_elementos_de_fatos_entram_no_recalculo():
    bal = "U1.ACT600.CIV.EST.BAL"
    declarado = [
        {
            "id": "b1",
            "tipo": "baldrame",
            "unidade": "U1",
            "sistema": "ACT600",
            "dimensoes": {"L": 10.0},
        }
    ]
    elementos = dimensoes.de_declarados(declarado)
    obs = [
        _fato(bal, "", "m", 30.0, EDITAL),
        _fato(bal, "armadura", "kg", 256.0, EDITAL),
    ]
    evs = evidencias.loop([], declarados=declarado, extras=obs)
    fatos = evidencias.consolidar([e for e in evs if e["metodo"] != "associado"])
    linha = _linha(calibracao.tabela(evs, fatos, elementos), bal, "armadura")
    # baldrame 0,20 × 0,40 m, 40 m (10 declarado + 30 do fato) → 3,2 m³ × 80 kg/m³ = 256 kg
    assert linha["calculado"] == pytest.approx(256.0)
    assert linha["situacao"] == "confere" and linha[
        "premissa_implicita"
    ] == pytest.approx(80.0)  # e não 320


def test_soma_que_nao_bate_vira_nao_calibravel_com_o_calculado_real():
    evs, fatos, _ = _cenario([(VIGA, "armadura", "kg", 200.0, EDITAL)])
    linha = _linha(
        calibracao.tabela(evs, fatos, []), VIGA, "armadura"
    )  # sem elementos: nada recalcula
    assert (
        linha["situacao"] == "não calibrável"
        and "sem premissa recalculável" in linha["motivo"]
    )
    assert linha["calculado"] == pytest.approx(
        _taxa_viga()
    )  # soma das evidências, não 0


def test_fato_com_curinga_soma_os_codigos_que_casam():
    tab = _rodar(
        [_viga("V1", "U1"), {**_viga("V2"), "sistema": "ACT700"}],
        [("U1.*.CIV.EST.VIG", "armadura", "kg", 2 * _taxa_viga(), EDITAL)],
    )
    linha = _linha(tab, "U1.*.CIV.EST.VIG", "armadura")
    assert (
        linha["calculado"] == pytest.approx(2 * _taxa_viga())
        and linha["situacao"] == "confere"
    )


def test_formula_com_teto_nao_reproduz_o_observado():
    el = {
        "id": "v",
        "tipo": "viga",
        "base": "U1.A",
        "item": "X",
        "dims": {"V": 1.0},
        "faltando": [],
        "memoria": [],
        "alertas": [],
    }
    regra = {
        "id": "x",
        "tipos": ["viga"],
        "formula": "min(taxa * V, 300)",
        "premissas": {"taxa": {"valor": 110.0}},
    }
    r = calibracao.premissa_implicita(regra, [el], 330.0)
    assert (
        r["premissa_implicita"] is None
        and r["motivo"] == "fórmula não reproduz o observado"
    )


def test_condicao_que_usa_a_premissa_nao_calibra():
    el = {
        "id": "v",
        "tipo": "viga",
        "base": "U1.A",
        "item": "X",
        "dims": {"V": 1.0},
        "faltando": [],
        "memoria": [],
        "alertas": [],
    }
    regra = {
        "id": "x",
        "tipos": ["viga"],
        "formula": "taxa * V",
        "condicao": "taxa > 100",
        "premissas": {"taxa": {"valor": 110.0}},
    }
    assert (
        calibracao.premissa_implicita(regra, [el], 200.0)["premissa_implicita"] is None
    )


def test_erro_de_avaliacao_e_observado_nao_positivo_nao_calibram():
    el = {
        "id": "v",
        "tipo": "viga",
        "base": "U1.A",
        "item": "X",
        "dims": {"V": 1.0},
        "faltando": [],
        "memoria": [],
        "alertas": [],
    }
    divide = {
        "id": "x",
        "tipos": ["viga"],
        "formula": "V / taxa",
        "premissas": {"taxa": {"valor": 110.0}},
    }
    assert (
        calibracao.premissa_implicita(divide, [el], 1.0)["premissa_implicita"] is None
    )
    linear = {
        "id": "x",
        "tipos": ["viga"],
        "formula": "taxa * V",
        "premissas": {"taxa": {"valor": 110.0}},
    }
    assert (
        calibracao.premissa_implicita(linear, [el], 0.0)["motivo"]
        == "observado não positivo"
    )
    assert (
        calibracao.premissa_implicita(linear, [el], -5.0)["premissa_implicita"] is None
    )


def test_fato_em_toneladas_casa_com_associado_em_kg():
    tab = _rodar([_viga("V1")], [(VIGA, "armadura", "t", 0.132, EDITAL)])
    linha = _linha(tab, VIGA, "armadura")
    assert linha["unidade"] == "kg" and linha["observado"] == pytest.approx(132.0)
    assert (
        linha["premissa_implicita"] == pytest.approx(1.2 * _taxa_viga())
        and linha["unidade_premissa"] == "kg/m³"
    )


def test_linha_nao_calibravel_mostra_o_calculado_real():
    evs, fatos, els = _cenario(
        [
            (VIGA, "armadura", "kg", 100.0, EDITAL),
            (VIGA, "armadura", "kg", 150.0, MEMORIAL),
        ]
    )
    linha = _linha(calibracao.tabela(evs, fatos, els), VIGA, "armadura")
    assert linha["motivo"] == "fato em conflito" and linha[
        "calculado"
    ] == pytest.approx(_taxa_viga())
