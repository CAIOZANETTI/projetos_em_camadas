"""Aceite da memória espacial, rodada 5: no build, a EAP das gavetas e a EAP codificada convivem em chaves próprias."""
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
