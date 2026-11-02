"""Aba EAP do visualizador: só apresenta o que vem em `dados["eap_gavetas"]` (sem conta em JS); `dados["eap"]` é a EAP codificada."""
import json
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import Error as ErroPlaywright
from playwright.sync_api import sync_playwright

from camadas import visualizador

EXEMPLO = Path(__file__).resolve().parent.parent / "exemplos" / "eap_exemplo.json"
IDENTIDADE = [1, 0, 0, 0, 1, 0]


def dados_minimos() -> dict:
    """O menor `dados` que o template aceita: identificação, CRS identidade (com nome e k) e listas vazias de vetores, folhas e bases."""
    return {
        "id": "teste", "titulo": "Teste EAP", "subtitulo": "", "vetores": [], "folhas": [], "bases": [],
        "crs": {"nome": "teste", "k": 1.0, "ll2utm": IDENTIDADE, "utm2ll": IDENTIDADE},
    }


def _valores_txt(no) -> list[str]:
    """Todos os `valor_txt` do exemplo, em qualquer profundidade."""
    achados = []
    if isinstance(no, dict):
        achados += [v for k, v in no.items() if k == "valor_txt"]
        for v in no.values():
            achados += _valores_txt(v)
    elif isinstance(no, list):
        for v in no:
            achados += _valores_txt(v)
    return achados


@pytest.fixture(scope="module")
def navegador():
    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except ErroPlaywright:
            b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        yield b
        b.close()


def _abrir(navegador, tmp_path, dados):
    html = visualizador.gerar(dados, tmp_path / "v.html")
    pagina = navegador.new_page()
    erros = []
    pagina.on("pageerror", lambda e: erros.append(str(e)))
    pagina.on("console", lambda m: erros.append(m.text) if m.type == "error" else None)
    pagina.goto(html.as_uri())
    pagina.wait_for_timeout(500)
    return pagina, erros


def test_aba_eap_apresenta_arvore(navegador, tmp_path):
    eap = json.loads(EXEMPLO.read_text(encoding="utf-8"))
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap_gavetas": eap})
    assert pagina.locator("#t-eap").is_visible()
    pagina.click("#t-eap")
    aba = pagina.locator("#aba-eap")
    assert aba.is_visible()
    # resumo
    for chave, valor in eap["resumo"].items():
        assert aba.locator(f'b[data-k="{chave}"]').inner_text() == str(valor)
    # nó -> serviço -> fato -> evidência
    no = aba.locator("details.eap-n").first
    no.locator("summary").first.click()
    serv = no.locator("details.eap-s").first
    assert serv.is_visible()
    serv.locator("summary").first.click()
    fato = serv.locator("details.eap-f").first
    fato.locator("summary").first.click()
    onde = eap["nos"][0]["servicos"][0]["fatos"][0]["evidencia"]["onde"]
    assert onde in fato.inner_text()
    assert "“Entrada de água bruta”" in fato.inner_text()
    # todo valor_txt aparece igual no DOM (abre tudo para ler o texto)
    pagina.evaluate("document.querySelectorAll('#aba-eap details').forEach(d => d.open = true)")
    texto = aba.inner_text()
    for v in _valores_txt(eap):
        assert v in texto, v
    # pendência
    pend = eap["pendencias"][0]
    assert pend["motivo"] in texto and pend["local"] in texto
    assert erros == []
    pagina.close()


def test_aba_eap_mostra_uma_tabela_por_setor(navegador, tmp_path):
    eap = json.loads(EXEMPLO.read_text(encoding="utf-8"))
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap_gavetas": eap})
    pagina.click("#t-eap")
    tabelas = pagina.locator("#aba-eap table.eap-setor")
    assert tabelas.count() == len(eap["setores"])
    texto = pagina.locator("#aba-eap").inner_text()
    for setor in eap["setores"]:
        assert setor["nome"] in texto
        for no in setor["nos"]:
            assert f"{no['valor_txt']} {no['unidade']}" in texto
    assert erros == []
    pagina.close()


def test_sem_setores_nao_ha_tabela_por_setor(navegador, tmp_path):
    eap = {k: v for k, v in json.loads(EXEMPLO.read_text(encoding="utf-8")).items() if k != "setores"}
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap_gavetas": eap})
    pagina.click("#t-eap")
    assert pagina.locator("#aba-eap table.eap-setor").count() == 0
    assert erros == []
    pagina.close()


def test_sem_eap_a_aba_fica_escondida(navegador, tmp_path):
    pagina, erros = _abrir(navegador, tmp_path, dados_minimos())
    assert pagina.locator("#t-eap").is_hidden()
    assert erros == []
    pagina.close()


def test_eap_codificada_em_dados_eap_nao_some_com_a_aba_das_gavetas(navegador, tmp_path):
    """Aceite da rodada 5: as duas EAP convivem; a aba das gavetas lê `eap_gavetas`, não a EAP codificada."""
    eap = json.loads(EXEMPLO.read_text(encoding="utf-8"))
    codificada = {"fonte": "camadas.eap", "nos": [{"codigo": "X"}], "quantidades": []}
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap": codificada, "eap_gavetas": eap})
    pagina.click("#t-eap")
    assert eap["nos"][0]["valor_txt"] in pagina.locator("#aba-eap").inner_text() and not erros


def test_aba_eap_mostra_o_codigo_real_ao_lado_do_provisorio_e_a_conciliacao(navegador, tmp_path):
    eap = json.loads(EXEMPLO.read_text(encoding="utf-8"))
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap_gavetas": eap})
    pagina.click("#t-eap")
    aba = pagina.locator("#aba-eap")
    no = aba.locator("details.eap-n").first
    assert no.locator("summary .cod").first.inner_text() == eap["nos"][0]["eap"]          # provisório
    assert no.locator('summary [data-cod="no"]').inner_text() == eap["nos"][0]["codigo_eap"] == "—"   # serviços com códigos diferentes
    no2 = aba.locator("details.eap-n").nth(1)
    assert no2.locator('summary [data-cod="no"]').inner_text() == "U1.AB_ENTRADA.GEO.MOV.VAL"
    pagina.evaluate("document.querySelectorAll('#aba-eap details').forEach(d => d.open = true)")
    codigos = aba.locator('[data-cod="servico"]').all_inner_texts()
    assert codigos == [s["codigo_eap"] for n in eap["nos"] for s in n["servicos"]]
    tabela = aba.locator("table.eap-conc")
    assert tabela.count() == 1
    texto = tabela.inner_text()
    for linha in eap["conciliacao"]["linhas"]:
        for campo in ("codigo", "gavetas_txt", "codificada_txt", "diferenca_txt", "situacao"):
            assert linha[campo] in texto, linha[campo]
    assert aba.locator("table.eap-setor").count() == len(eap["setores"])     # a tabela da conciliação não é de setor
    assert erros == []
    pagina.close()


def test_sem_conciliacao_nao_ha_tabela(navegador, tmp_path):
    eap = {k: v for k, v in json.loads(EXEMPLO.read_text(encoding="utf-8")).items() if k != "conciliacao"}
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap_gavetas": eap})
    pagina.click("#t-eap")
    assert pagina.locator("#aba-eap table.eap-conc").count() == 0 and erros == []
    pagina.close()
