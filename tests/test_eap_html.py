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
    assert eh.onde({"pranchas": ["AAT00_01", "AAT00_02"], "layers": ["X", "Y"], "criterio": "divisas"}) == \
        "pranchas AAT00_01, AAT00_02; layers X, Y; critério divisas"
    assert eh.onde({"pranchas": ["P1"], "criterio": "ortofoto"}) == "pranchas P1; critério ortofoto"


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


def _com_setores():
    from test_gavetas import _base_com_setores, _servicos_por_setor
    base, servicos = _base_com_setores(), _servicos_por_setor()
    base["fatos"].append({"fato_id": "SET-A.nome.decidido", "objeto_id": "SET-A", "propriedade": "nome", "valor": "Decantação",
                          "natureza": "decidido", "evidencia_id": "E1"})
    base["evidencias"].append({"evidencia_id": "E1", "classe": "decisao", "documento": "obra.json", "localizador": {},
                               "metodo": "decisão", "executor": "você"})
    return base, servicos, gavetas.setor_de(base)[0]


def test_montar_com_setores_formata_e_confere_a_soma():
    base, servicos, mapa = _com_setores()
    eap = eh.montar(base, servicos, [], None, mapa)
    assert [s["setor_id"] for s in eap["setores"]] == ["SET-A", "SET-B", None]
    assert eap["setores"][0]["nome"] == "Decantação" and eap["setores"][2]["nome"] == "Fora dos setores"
    escavacao = {s["setor_id"]: next(n for n in s["nos"] if n["unidade"] == "m³") for s in eap["setores"]}
    assert escavacao[None]["valor_txt"] == "5,25" and escavacao["SET-B"]["valor_txt"] == "20,50"
    assert "setores" not in eh.montar(base, servicos, [], None)
    json.dumps(eap)


def test_soma_dos_setores_diferente_do_total_e_erro(monkeypatch):
    base, servicos, mapa = _com_setores()
    original = gavetas.para_eap_por_setor

    def torta(*args, **kwargs):
        grupos = original(*args, **kwargs)
        grupos[0]["nos"][0]["valor"] += 1.0
        return grupos
    monkeypatch.setattr(gavetas, "para_eap_por_setor", torta)
    with pytest.raises(ValueError, match="soma dos setores"):
        eh.montar(base, servicos, [], None, mapa)


def test_servico_contado_em_dobro_num_no_grande_e_erro(monkeypatch):
    """2º aceite da rodada 5: num nó com milhares de serviços a tolerância da soma é larga; a contagem exata pega a dobra."""
    base, servicos, mapa = _com_setores()
    servicos = servicos + [{**servicos[0], "servico_id": f"{servicos[0]['servico_id']}:{i}", "valor": 0.001}
                           for i in range(40000)]
    original = gavetas.para_eap_por_setor

    def dobrada(*args, **kwargs):
        grupos = original(*args, **kwargs)
        no = grupos[0]["nos"][0]
        no["n_servicos"] += 1                      # um serviço a mais num setor
        no["valor"] = round(no["valor"] + 5.0, 3)  # 5 m³: abaixo do limite de 0,0005 × 2 × 40 001 = 40
        return grupos
    monkeypatch.setattr(gavetas, "para_eap_por_setor", dobrada)
    with pytest.raises(ValueError, match="serviços"):
        eh.montar(base, servicos, [], None, mapa)
