"""Aceite da memória espacial, rodadas 5 e 6: no build, a EAP das gavetas e a EAP codificada convivem em chaves próprias
e são conciliadas (`conciliacao_eap.json`)."""
import json

from camadas import obra


def test_aba_projeto_mantem_as_duas_eap(tmp_path, monkeypatch):
    monkeypatch.setattr(obra.obras_lineares, "etapa", lambda *a, **k: None)
    monkeypatch.setattr(obra.extrair_gavetas, "etapa", lambda *a, **k: {"servicos": 1, "eap_html": {"nos": ["g"]}})
    monkeypatch.setattr(obra.construtivos, "montar", lambda *a, **k: None)
    monkeypatch.setattr(obra.eap, "montar", lambda *a, **k: {"fonte": "camadas.eap"})
    monkeypatch.setattr(obra.evidencias, "etapa", lambda *a, **k: None)
    dados = {"sondagens": []}
    obra._aba_projeto(dados, {}, tmp_path, None, None, {})
    assert dados["eap_gavetas"] == {"nos": ["g"]} and dados["eap"] == {"fonte": "camadas.eap"}
    assert "eap_html" not in dados["gavetas"]


def _preparar(monkeypatch, servicos, quantidades):
    monkeypatch.setattr(obra.obras_lineares, "etapa", lambda *a, **k: None)
    monkeypatch.setattr(obra.extrair_gavetas, "etapa", lambda *a, **k: {"servicos": 1, "eap_html": {"nos": ["g"]},
                                                                        "servicos_eap": servicos})
    monkeypatch.setattr(obra.construtivos, "montar", lambda *a, **k: None)
    monkeypatch.setattr(obra.eap, "montar", lambda *a, **k: {"fonte": "camadas.eap", "quantidades": quantidades})
    monkeypatch.setattr(obra.evidencias, "etapa", lambda *a, **k: None)


def test_aba_projeto_concilia_as_duas_eap_e_grava_o_json(tmp_path, monkeypatch):
    servicos = [{"servico_id": "s1", "objeto_id": "o", "saida": "escavacao_cava_m3", "unidade": "m³", "valor": 10.0,
                 "codigo_eap": "U1.ETA.GEO.MOV.ESC"}]
    quantidades = [{"codigo": "U1.ETA.GEO.MOV.ESC", "grandeza": "volume", "unidade": "m³", "quantidade": 12.5}]
    _preparar(monkeypatch, servicos, quantidades)
    dados = {"sondagens": []}
    obra._aba_projeto(dados, {}, tmp_path, None, None, {})
    assert dados["eap"]["fonte"] == "camadas.eap" and dados["eap_gavetas"]["nos"] == ["g"]
    linhas = json.loads((tmp_path / "conciliacao_eap.json").read_text(encoding="utf-8"))
    assert [(l["codigo"], l["situacao"]) for l in linhas] == [("U1.ETA.GEO.MOV.ESC", "difere")]
    conciliacao = dados["eap_gavetas"]["conciliacao"]
    assert conciliacao["resumo"]["difere"] == 1
    assert conciliacao["linhas"][0]["diferenca_txt"] == "-2,50 m³" and conciliacao["linhas"][0]["gavetas_txt"] == "10,00 m³"
    assert "servicos_eap" not in dados["gavetas"] and "eap_html" not in dados["gavetas"]


def test_aba_projeto_conciliacao_com_defeito_nao_derruba_o_build(tmp_path, monkeypatch):
    _preparar(monkeypatch, [{"codigo_eap": "X", "unidade": "m³", "valor": 1.0}], [{"codigo": "X"}])   # falta a quantidade
    dados = {"sondagens": []}
    obra._aba_projeto(dados, {}, tmp_path, None, None, {})
    assert "conciliacao" not in dados["eap_gavetas"] and not (tmp_path / "conciliacao_eap.json").exists()
