import json

import pytest
from test_gavetas import _base

from camadas import eap_html as eh
from camadas import gavetas


def _montado():
    base = _base()
    servicos, pend = gavetas.calcular(base)
    return base, servicos, pend, eh.montar(base, servicos, pend)


def test_br():
    assert eh.br(1234.5) == "1.234,50"
    assert eh.br(-0.5, 1) == "-0,5"
    assert eh.br(1234567, 0) == "1.234.567"
    assert eh.br(None) == "—"


@pytest.mark.parametrize("propriedade, valor, esperado", [
    ("prof_m", 2.4, "2,40 m"), ("dn_mm", 500, "500 mm"), ("material", "FD", "FD"),
    ("supressao_frac", 0.35, "35 %"),
    ("pavimentos", {"asfalto": 12, "grama": 8}, "asfalto 12,00 m; grama 8,00 m"),
    ("camadas", [{"de": 0, "ate": 1.5, "descricao": "argila siltosa"}, {"de": 1.5, "ate": 5, "descricao": "silte"}],
     "0,00–1,50 m argila siltosa; 1,50–5,00 m silte"),
])
def test_valor_txt(propriedade, valor, esperado):
    assert eh.valor_txt(propriedade, valor) == esperado


def test_onde():
    assert eh.onde({"aba": "Obras Lineares", "linha": 7}) == "aba Obras Lineares, linha 7"
    assert eh.onde({"arquivo": "laudo.pdf", "furo": "SP-02"}) == "laudo.pdf, furo SP-02"
    assert eh.onde({"arquivo": "a.json", "chave": "k"}) == "a.json, k"
    assert eh.onde({"pagina": 3, "pasta_drive": "Projeto/Civil"}) == "Projeto/Civil, p. 3"
    assert eh.onde({"x": 1}) == '{"x":1}'


def test_caminho_de_volta_completo():
    _, servicos, _, eap = _montado()
    assert eap["nos"] and eap["resumo"]["servicos"] == len(servicos) == sum(len(n["servicos"]) for n in eap["nos"])
    for no in eap["nos"]:
        assert no["servicos"]
        for s in no["servicos"]:
            assert s["fatos"] and s["local"] == "T01"
            for f in s["fatos"]:
                assert f["evidencia"]["onde"] and f["evidencia"]["documento"] and f["evidencia"]["executor"]
                assert f["evidencia"]["trecho"] == ""


def test_valor_do_no_e_a_soma_formatada():
    _, servicos, _, eap = _montado()
    no = next(n for n in eap["nos"] if n["eap"] == "OL.01")
    esperado = sum(s["valor"] for s in servicos if gavetas.EAP["saidas"][s["saida"]]["eap"] == "OL.01")
    assert no["valor_txt"] == eh.br(esperado)


def test_pendencia_com_local_e_resumo():
    base = _base()
    base["fatos"] = [f for f in base["fatos"] if f["propriedade"] != "prof_m"]
    base["fatos"].append({"fato_id": "T01.local", "objeto_id": "T01", "propriedade": "local", "valor": "Entrada de água bruta",
                          "natureza": "projetado", "evidencia_id": "E1"})
    servicos, pend = gavetas.calcular(base)
    eap = eh.montar(base, servicos, pend, {"recalculados": 2})
    assert eap["pendencias"] == [{"objeto_id": "T01", "local": "Entrada de água bruta",
                                  "motivo": "faltam fatos obrigatórios: prof_m"}]
    assert eap["resumo"] == {"servicos": 0, "nos": 0, "pendencias": 1, "diferencas_paridade": 0, "recalculados": 2,
                             "reaproveitados": 0}


def test_serializavel_e_metadados():
    _, _, _, eap = _montado()
    assert json.loads(json.dumps(eap, ensure_ascii=False)) == eap
    assert eh.metadados()["modulo"] == "eap_html"


def test_servico_com_fato_fora_da_base_nao_vai_para_o_html():
    """Aceite da rodada 23: número sem caminho de volta é erro, não omissão silenciosa."""
    base = _base()
    servicos, pend = gavetas.calcular(base)
    servicos[0] = {**servicos[0], "fatos": servicos[0]["fatos"] + ["T01.inexistente"]}
    with pytest.raises(ValueError, match="T01.inexistente"):
        eh.montar(base, servicos, pend)
