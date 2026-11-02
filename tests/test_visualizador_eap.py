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


def _painel(com_conflito: bool = True) -> dict:
    from test_eap_painel import sinteticos

    from camadas import eap_painel
    return eap_painel.montar(*sinteticos(com_conflito))


def _ids_do_no(dados: dict, codigo: str) -> list[str]:
    """Os ids que o Python entregou para o nó (conferência do teste; o JS só os usa)."""
    return next(n["elementos"] for n in dados["eap_painel"]["arvore"] if n["codigo"] == codigo)


def test_aba_eap_apresenta_painel_codificado_fatos_e_associados(navegador, tmp_path):
    painel = _painel()
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap_painel": painel})   # sem `eap`: a aba aparece só pelo painel
    assert pagina.locator("#t-eap").is_visible()
    pagina.click("#t-eap")
    aba = pagina.locator("#aba-eap")
    assert aba.is_visible()
    # árvore codificada: todo código do painel, com nome e quantidades prontas
    pagina.evaluate("document.querySelectorAll('#eapCod details').forEach(d => d.open = true)")
    arvore = aba.locator("#eapCod").inner_text()
    for no in painel["arvore"]:
        assert no["codigo"] in arvore and no["nome"] in arvore
        for q in no["quantidades_txt"]:
            assert q in arvore
    assert aba.locator('#eapCod details[data-codigo="U1.FILTROS.GEO.FUN.BLO"]').count() == 1
    assert aba.locator("#eapCod [data-eap-ids]").count() == 0           # sem a camada de elementos construtivos, sem botão
    # resumo por status = os números do Python
    for s in painel["resumo"]["por_status"]:
        assert aba.locator(f'#eapFiltro b[data-k="{s["status"]}"]').inner_text() == str(s["n"])
    assert aba.locator('#eapFiltro b[data-k="todos"]').inner_text() == str(painel["resumo"]["fatos"])
    # fato em conflito: selo, e as afirmações ao abrir
    conflito = aba.locator('#eapFatos details.eap-fato[data-status="conflito"]').first
    assert "conflito" in conflito.locator("summary .st").inner_text()
    assert "U1.*.GEO.FUN.EST" in conflito.locator("summary").inner_text()
    conflito.locator("summary").click()
    texto = conflito.inner_text()
    assert "memorial_fundacoes.pdf" in texto and "250 un" in texto and "300 un" in texto and "modelo:construtivos" in texto
    assert "16,7 %" in texto
    # filtro por status: só o conflito fica visível; "todos" restaura
    total = aba.locator("#eapFatos details.eap-fato").count()
    assert total == len(painel["fatos"]) and total > 1
    aba.locator('#eapFiltro [data-eap-status="conflito"]').click()
    visiveis = aba.locator("#eapFatos details.eap-fato:visible")
    assert visiveis.count() == painel["resumo"]["por_status"][0]["n"]
    assert {visiveis.nth(i).get_attribute("data-status") for i in range(visiveis.count())} == {"conflito"}
    aba.locator('#eapFiltro [data-eap-status=""]').click()
    assert aba.locator("#eapFatos details.eap-fato:visible").count() == total
    # associados × edital
    assert aba.locator("#eapAssoc tbody tr").count() == len(painel["associados"])
    assert aba.locator("#eapAssoc tr.nao-citado").count() == painel["resumo"]["nao_citados"] > 0
    assert "não citado no edital" in aba.locator("#eapAssoc tr.nao-citado").first.inner_text()
    assert aba.locator('b[data-k="nao_citados"]').inner_text() == str(painel["resumo"]["nao_citados"])
    assert erros == []
    pagina.close()


def test_painel_ver_no_mapa_destaca_so_os_elementos_do_no(navegador, tmp_path):
    from test_construtivos import CFG, _dados

    from camadas import construtivos
    bruto = _dados()
    bruto["construtivos"] = construtivos.montar(bruto, CFG)
    dados = {**dados_minimos(), "construtivos": bruto["construtivos"], "eap_painel": _painel(com_conflito=False)}
    pagina, erros = _abrir(navegador, tmp_path, dados)
    pagina.click("#t-eap")
    pagina.evaluate("document.querySelectorAll('#eapCod details').forEach(d => d.open = true)")
    botao = pagina.locator('#eapCod details[data-codigo="U1.FILTROS.GEO.FUN.BLO"] > .eap-q [data-eap-ids]')
    assert botao.count() == 1 and "ver no mapa" in botao.inner_text()
    botao.click()
    assert pagina.evaluate("window.__viz.obra.sel") == "u1-FILTROS-bloco-P5"          # um elemento: selecionado e enquadrado
    # nó alto (vários elementos): camada ligada e halo só sobre os ids do nó
    pagina.locator('#eapCod > details[data-codigo="U1"] > .eap-q [data-eap-ids]').click()
    assert pagina.evaluate("document.querySelector('#obMapa').checked")
    n_ids = len(_ids_do_no(dados, "U1"))
    assert n_ids > 1
    assert pagina.evaluate("window.__viz.obra.halo.getLayers().length") == 2 * n_ids      # anel escuro + branco por elemento
    assert erros == []
    pagina.close()


def _dados_com_mapa(**extra) -> dict:
    from test_construtivos import CFG, _dados

    from camadas import construtivos

    bruto = _dados()
    bruto["construtivos"] = construtivos.montar(bruto, CFG)
    return {**dados_minimos(), "construtivos": bruto["construtivos"], **extra}


def test_aba_eap_com_gavetas_e_painel_juntos(navegador, tmp_path):
    eap = json.loads(EXEMPLO.read_text(encoding="utf-8"))
    painel = _painel()
    pagina, erros = _abrir(navegador, tmp_path, {**dados_minimos(), "eap_gavetas": eap, "eap_painel": painel})
    pagina.click("#t-eap")
    aba = pagina.locator("#aba-eap")
    for chave, valor in eap["resumo"].items():                              # parte das gavetas intacta
        assert aba.locator(f'b[data-k="{chave}"]').inner_text() == str(valor)
    assert aba.locator("details.eap-n:not([data-codigo])").count() == len(eap["nos"])
    for secao in ("#eapCod", "#eapFiltro", "#eapFatos", "#eapAssoc"):       # e as seções novas
        assert aba.locator(secao).count() == 1
    assert erros == []
    pagina.close()


def test_ver_no_mapa_multiplo_nao_acumula_halo_nem_deixa_popup_antigo(navegador, tmp_path):
    dados = _dados_com_mapa(eap_painel=_painel(com_conflito=False))
    pagina, erros = _abrir(navegador, tmp_path, dados)
    pagina.click("#t-eap")
    pagina.evaluate("document.querySelectorAll('#eapCod details').forEach(d => d.open = true)")
    halo = "window.__viz.obra.halo.getLayers().length"
    aberto = "!!window.__viz.obra.popup && window.__viz.map.hasLayer(window.__viz.obra.popup)"
    pagina.evaluate("window.__viz.obra.selecionar('u1-FILTROS-bloco-P5', {abrir: false})")
    assert pagina.evaluate(halo) == 2 and pagina.evaluate(aberto)
    pagina.locator('#eapCod > details[data-codigo="U1"] > .eap-q [data-eap-ids]').click()
    n_ids = len(_ids_do_no(dados, "U1"))
    assert pagina.evaluate(halo) == 2 * n_ids                               # só o anel dos elementos do nó
    pagina.evaluate("window.__viz.obra.definirSoEscopo(true)")              # refaz a camada: o anel múltiplo é refeito, não duplicado
    assert pagina.evaluate(halo) == 2 * n_ids
    assert pagina.evaluate("window.__viz.obra.sel") is None
    assert not pagina.evaluate(aberto)                                      # popup do elemento anterior fechado
    assert pagina.locator("#obFicha").inner_text().strip() == ""            # e a ficha, limpa
    pagina.evaluate("window.__viz.obra.selecionar('u1-FILTROS-pilar-P5', {abrir: false})")
    assert pagina.evaluate(halo) == 2                                       # o anel múltiplo não fica
    assert pagina.evaluate("window.__viz.obra.sel") == "u1-FILTROS-pilar-P5" and pagina.evaluate(aberto)
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
