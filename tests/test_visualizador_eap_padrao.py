"""Aba EAP do visualizador: a seção "EAP padrão (a preencher)" só apresenta `dados["eap_padrao"]` (sem conta em JS)."""

import pytest

pytest.importorskip("playwright")
from test_eap_padrao import _fato, _q
from test_visualizador_eap import (  # noqa: F401  (fixture)
    _abrir,
    dados_minimos,
    navegador,
)

from camadas import eap_padrao


def _padrao() -> dict:
    codificada = {
        "quantidades": [_q("U1.A.CIV.EST.PIL", "quantidade", "un", 12.0, ["p1"])]
    }
    fatos = [_fato("U1.*.HID.EQP.EQU", "", "un", None, "só menção", 0)]
    cfg = {
        "eap_padrao": {
            "nao_se_aplica": [
                {"id": "OP.02.03", "justificativa": "sem lençol", "autor": "Caio"}
            ]
        }
    }
    return eap_padrao.montar({"eap": codificada, "evidencias": {"fatos": fatos}}, cfg)


def test_aba_eap_mostra_a_eap_padrao(navegador, tmp_path):  # noqa: F811
    padrao = _padrao()
    pagina, erros = _abrir(
        navegador, tmp_path, {**dados_minimos(), "eap_padrao": padrao}
    )
    assert pagina.locator("#t-eap").is_visible()
    pagina.click("#t-eap")
    secao = pagina.locator("#eapPadrao")
    assert (
        pagina.locator("#aba-eap h2", has_text="EAP padrão (a preencher)").count() == 1
    )
    assert "MOS" in pagina.locator("#eapPadAviso").inner_text()
    bloco = padrao["tipos"][0]
    etapas = secao.locator("details.eap-pad-etapa")
    assert etapas.count() == len(bloco["etapas"])
    pagina.evaluate(
        "document.querySelectorAll('#eapPadrao details').forEach(d => d.open = true)"
    )
    estrutura = secao.locator('details[data-etapa="OP.04"]')
    assert (
        bloco["etapas"][3]["resumo"]["pct_txt"]
        in estrutura.locator("summary").inner_text()
    )
    assert (
        estrutura.locator("summary .eap-pad-bar i")
        .get_attribute("style")
        .startswith("width:")
    )
    pilares = secao.locator('[data-id="OP.04.03"]')
    assert pilares.get_attribute("data-situacao") == "preenchida"
    assert (
        "12 un" in pilares.inner_text() and "U1.A.CIV.EST.PIL" in pilares.inner_text()
    )
    assert (
        secao.locator('[data-id="OP.08.01"]').get_attribute("data-situacao")
        == "só menção"
    )
    assert (
        secao.locator('[data-id="OP.02.03"]').get_attribute("data-situacao")
        == "não se aplica"
    )
    assert "sem lençol" in secao.locator('[data-id="OP.02.03"]').inner_text()
    assert (
        secao.locator('[data-id="OP.01.01"]').get_attribute("data-situacao")
        == "sem item codificado"
    )
    destaque = secao.locator(".eap-pad-folha.destaque")
    assert destaque.count() == bloco["resumo"]["obrigatorias_a_preencher"] > 0
    assert destaque.first.get_attribute("data-situacao") == "a preencher"
    assert "obrigatória" in destaque.first.inner_text()
    assert not erros
