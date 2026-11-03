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
    monkeypatch.setattr(obra.eap_painel, "montar", lambda *a, **k: None)   # o painel da EAP codificada é outra entrega


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


def test_aba_projeto_concilia_com_origem_e_documento(tmp_path, monkeypatch):
    """Caso de Foz: as duas trilhas partem da mesma etapa de escavação; a planilha do contrato é a conferência independente."""
    servicos = [{"servico_id": "s1", "objeto_id": "o", "saida": "escavacao_cava_m3", "unidade": "m³", "valor": 10.0,
                 "codigo_eap": "U1.ETA.GEO.MOV.ESC", "origem": ["arquivo:ortofoto_mds", "etapa:escavacao"]}]
    quantidades = [{"codigo": "U1.ETA.GEO.MOV.ESC", "grandeza": "volume", "unidade": "m³", "quantidade": 10.0,
                    "evidencias": ["c1"]}]
    _preparar(monkeypatch, servicos, quantidades)
    fatos = [{"codigo": "U1.ETA.GEO.MOV.ESC", "servico": "", "unidade": "m³", "decisoes": [],
              "afirmacoes": [{"documento": "CUSTO CIVIL.xlsx", "tipo": "planilha", "valor": 9.0}]}]
    monkeypatch.setattr(obra.evidencias, "etapa", lambda *a, **k: {"fatos": fatos})
    construtivos = {"geojson": {"features": [{"properties": {
        "id": "c1", "doc": "pbge_esc", "fonte": "escavação calculada (camadas.escavacao) · levantamento"}}]}}
    monkeypatch.setattr(obra.construtivos, "montar", lambda *a, **k: construtivos)
    monkeypatch.setattr(obra.escopo_obra, "montar", lambda *a, **k: None)
    dados = {"sondagens": []}
    obra._aba_projeto(dados, {}, tmp_path, None, None, {})
    linhas = json.loads((tmp_path / "conciliacao_eap.json").read_text(encoding="utf-8"))
    assert [(l["situacao"], l["origem"], l["situacao_documento"]) for l in linhas] == [
        ("confere (mesma origem)", "mesma", "difere do documento")]
    linha = dados["eap_gavetas"]["conciliacao"]["linhas"][0]
    assert linha["mesma_origem"] and linha["documento_txt"] == "9,00 m³"
    assert linha["situacao_documento_txt"] == "difere do documento (Δ 1,00 m³ · 11,1 %)"


def test_aba_projeto_conciliacao_com_defeito_nao_derruba_o_build(tmp_path, monkeypatch):
    _preparar(monkeypatch, [{"codigo_eap": "X", "unidade": "m³", "valor": 1.0}], [{"codigo": "X"}])   # falta a quantidade
    dados = {"sondagens": []}
    obra._aba_projeto(dados, {}, tmp_path, None, None, {})
    assert "conciliacao" not in dados["eap_gavetas"] and not (tmp_path / "conciliacao_eap.json").exists()


def test_etapa_pulada_com_pendencia_vai_aos_pendentes_do_html(capsys):
    """Revisão do Fable: a etapa pulada por insumo ausente aparecia só no terminal."""
    from camadas import obra

    obra.AVISOS_DO_BUILD.clear()
    obra._log("Ficha f1: NÃO LIDA — falta o arquivo de âncoras estacas.csv (pendência; o build segue)")
    obra._log("Ficha f1: NÃO LIDA — falta o arquivo de âncoras estacas.csv (pendência; o build segue)")  # repetida
    obra._log("Gavetas: 30 objetos")
    dados = {"pendentes": {"Estrutura": ["formas"]}}
    obra._avisos_nas_pendencias(dados, obra.AVISOS_DO_BUILD)
    assert dados["pendentes"]["Build (etapas puladas)"] == [
        "Ficha f1: NÃO LIDA — falta o arquivo de âncoras estacas.csv (pendência; o build segue)"]
    assert dados["pendentes"]["Estrutura"] == ["formas"]
    obra.AVISOS_DO_BUILD.clear()


def test_prancha_com_pdf_ausente_e_pulada_com_pendencia(tmp_path):
    """Build real de Foz (conferência das cavas): uma prancha citada e não baixada derrubava etapa_pranchas."""
    from camadas import obra

    obra.AVISOS_DO_BUILD.clear()
    cfg = {"pranchas": [{"id": "el_im", "pdf": str(tmp_path / "nao_existe.pdf")}]}
    assert obra.etapa_pranchas(cfg, tmp_path, refazer=False) == []
    assert any("el_im" in a and "PDF ausente" in a for a in obra.AVISOS_DO_BUILD)
    obra.AVISOS_DO_BUILD.clear()


def test_inventario_sem_listagem_ou_com_baixados_de_outro_formato_e_pulado(tmp_path):
    """Contêiner novo com ingestão parcial: sem _listagem_drive.csv, ou com _baixados.csv de outras colunas."""
    from camadas import inventario

    msgs = []
    cfg = {"inventario": {"listagem": str(tmp_path / "_listagem_drive.csv"), "baixados": str(tmp_path / "_baixados.csv")}}
    assert inventario.disponivel(cfg, log=msgs.append) is False and "listagem" in msgs[-1]
    (tmp_path / "_listagem_drive.csv").write_text("id;name;mimeType\n")
    (tmp_path / "_baixados.csv").write_text("caminho;fileId;bytes\n")
    assert inventario.disponivel(cfg, log=msgs.append) is False and "colunas" in msgs[-1]
    (tmp_path / "_baixados.csv").write_text("id;ok\n")
    assert inventario.disponivel(cfg, log=msgs.append) is True


def test_escavacao_sem_controle_vertical_avisa(tmp_path):
    """As cavas sumiam do build sem aviso quando faltavam as sondagens."""
    from camadas import escavacao

    msgs = []
    assert escavacao.etapa({"escavacao": {"pranchas": []}}, [], tmp_path, None, log=msgs.append) is None
    assert any("NÃO CALCULADA" in m and "(pendência" in m for m in msgs)
