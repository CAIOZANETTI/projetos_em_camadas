import json

import pandas as pd
import pytest
from test_construtivos import CFG, EPSG, _dados

from camadas import associados, construtivos, eap, evidencias, vocabulario

PROJETO = {"id": "memorial_fundacoes.pdf", "tipo": "memorial", "nome": "Memorial de fundações", "unidade": "U1",
           "obra": "localizada", "escopo": "agua"}


def _construtivos():
    return construtivos.montar(_dados(), CFG)


def test_conceitos_coerentes():
    assert eap.validar() == []
    assert vocabulario.validar() == []
    assert associados.validar() == []
    linhas = (evidencias.CONCEITOS / "eap_geral.jsonl").read_text(encoding="utf-8").splitlines()
    assert all(json.loads(linha)["codigo"] for linha in linhas if linha.strip())


@pytest.mark.parametrize("texto, esperado", [
    ("1.250,50 m³", (1250.5, "m³")), ("12 METROS CUBICOS", (12.0, "m³")), ("450,00 m²", (450.0, "m²")),
    ("12,5 t", (12500.0, "kg")), ("300 und", (300.0, "un")), ("30 MPa", (None, None)), ("DN 300 mm", (None, None)),
])
def test_unidades_por_sinonimo_e_conversao(texto, esperado):
    assert vocabulario.quantidade(vocabulario.preparar(texto)[0], []) == esperado


def test_abreviacao_e_sinonimo_levam_ao_item_e_servico():
    assert evidencias.classificar(vocabulario.preparar("Conc. fck 30 MPa p/ blocos de coroamento")[1])[:2] == \
        ("GEO.FUN.BLO", "concreto")
    assert evidencias.classificar(vocabulario.preparar("Cimbramento metálico de lajes")[1])[:2] == \
        ("CIV.EST.PIS", "escoramento")
    assert evidencias.classificar(vocabulario.preparar("Hélice contínua D=40 cm")[1])[0] == "GEO.FUN.EST"
    assert evidencias.classificar(vocabulario.preparar("Forma plana em compensado plastificado")[1])[:2] == \
        ("CIV.EST.*", "forma")
    assert evidencias.classificar(vocabulario.preparar("estaca 12+10,00 do perfil")[1])[0] is None   # estaqueamento


def test_texto_vira_evidencia_com_trecho_e_localizador():
    evs = evidencias.buscar_texto(PROJETO, ["Serão executadas 250 estacas hélice contínua.\nTexto sem item."])
    assert len(evs) == 1
    e = evs[0]
    assert (e["codigo"], e["servico"], e["unidade"], e["valor"]) == ("U1.*.GEO.FUN.EST", "", "un", 250.0)
    assert e["localizador"] == "p. 1, linha 1" and e["trecho"].startswith("Serão executadas")
    assert evidencias.validar_evidencia(e) == []


def test_projeto_300_x_memorial_250_e_conflito_e_mostra_as_duas_afirmacoes():
    dados = _dados()
    estacas = dados["vetores"][0]["geojson"]["features"]
    estacas += [{**estacas[0], "properties": {**estacas[0]["properties"], "id": f"ACT600-{i:03d}"}} for i in range(100, 399)]
    c = construtivos.montar(dados, CFG)
    evs = evidencias.loop([{**PROJETO, "paginas": ["Serão executadas 250 estacas, conforme sondagem SP-04."]}],
                          construtivos=c, epsg=EPSG)
    fatos = evidencias.consolidar(evs)
    fato = fatos[(fatos["codigo"] == "U1.*.GEO.FUN.EST") & (fatos["unidade"] == "un") & (fatos["servico"] == "")].iloc[0]
    assert fato["status"] == "conflito" and pd.isna(fato["valor"])
    valores = sorted((a["documento"], a["valor"]) for a in fato["afirmacoes"])
    assert valores == [("memorial_fundacoes.pdf", 250.0), ("modelo:construtivos", 300.0)]
    assert fato["diferenca_pct"] == pytest.approx(16.7)


def test_mais_documentos_concordando_reforcam_o_fato():
    docs = [{**PROJETO, "id": "memorial.pdf", "paginas": ["Total de 300 estacas."]},
            {**PROJETO, "id": "edital.pdf", "tipo": "edital", "paginas": ["Execução de 300 estacas hélice."]},
            {**PROJETO, "id": "relatorio.pdf", "paginas": ["As estacas seguem a NBR 6122."]}]
    fato = evidencias.consolidar(evidencias.loop(docs)).iloc[0]
    assert (fato["status"], fato["valor"], fato["forca"], fato["n_documentos"]) == ("convergente", 300.0, 2, 2)
    assert fato["mencoes"] == ["relatorio.pdf"]


def test_decisao_registra_o_valor_adotado_sem_apagar_o_conflito():
    docs = [{**PROJETO, "id": "a.pdf", "paginas": ["300 estacas"]}, {**PROJETO, "id": "b.pdf", "paginas": ["250 estacas"]}]
    dec = evidencias.decisao("U1.*.GEO.FUN.EST", "", "un", 250.0, "Caio", "revisão R2 da fundação suprimiu 50 estacas")
    fato = evidencias.consolidar(evidencias.loop(docs, decisoes=[dec])).iloc[0]
    assert fato["status"] == "decidido" and fato["valor"] == 250.0 and len(fato["afirmacoes"]) == 2
    with pytest.raises(ValueError):
        evidencias.decisao("U1.*.GEO.FUN.EST", "", "un", 250.0, "", "")


def test_ia_so_entra_com_citacao_conferida():
    paginas = ["Serão executadas 250 estacas."]
    base = {"codigo": "U1.*.GEO.FUN.EST", "servico": "", "unidade": "un", "parcela": False, "localizador": "p. 1",
            "documento": {"id": "memorial_fundacoes.pdf", "tipo": "ia"}, "metodo": "ia", "regra": "leitura por IA"}
    ok = evidencias.evidencia(**base, valor=250.0, trecho="executadas 250 estacas")
    inventada = evidencias.evidencia(**base, valor=280.0, trecho="executadas 280 estacas")
    numero_errado = evidencias.evidencia(**base, valor=280.0, trecho="executadas 250 estacas")
    evs = evidencias.loop([{**PROJETO, "paginas": paginas}], ia=[ok, inventada, numero_errado])
    citacoes = [e["citacao"] for e in evs if e["metodo"] == "ia"]
    assert citacoes == ["conferida", "trecho não encontrado no documento", "valor não está no trecho"]
    fato = evidencias.consolidar(evs).iloc[0]
    assert fato["status"] == "fonte única" and fato["valor"] == 250.0       # a de 280 não conta
    assert len(fato["afirmacoes"]) == 1 and len(fato["afirmacoes"][0]["evidencias"]) == 2   # IA lendo o mesmo
    #                                     memorial não é fonte independente: reforça a leitura, não a força do fato


def test_planilha_parcelas_somam_e_cadastro_de_materiais_classifica():
    itens = pd.DataFrame([
        {"aba": "MATS E EQUIP", "codigo": "309244", "descricao": "TUBO PE DE 630", "unidade": "M", "quantidade": 100.0,
         "unidade_obra": "UNIDADE 2 - Adutora", "linha_origem": 10},
        {"aba": "MATS E EQUIP", "codigo": "309245", "descricao": "TUBO PE DE 630 PN10", "unidade": "ML", "quantidade": 80.0,
         "unidade_obra": "UNIDADE 2 - Adutora", "linha_origem": 11},
        {"aba": "CUSTO CIVIL", "codigo": "020101", "descricao": "ESCAVACAO MECANICA DE VALA", "unidade": "M3",
         "quantidade": None, "unidade_obra": "UNIDADE 2 - Adutora", "linha_origem": 40}])
    cat = {"309244": {"descricao": "TUBO PEAD PE 100 DE 630", "subcategoria": "tubo"}}
    doc = {"id": "escopo_itens.csv", "tipo": "planilha"}
    evs = evidencias.de_planilha(itens, doc, cat)
    assert [e["codigo"] for e in evs] == ["U2.*.HID.TUB.RED"] * 2 + ["U2.*.GEO.MOV.VAL"]
    assert evs[0]["metodo"] == "catalogo" and evs[1]["metodo"] == "planilha"
    assert evs[2]["valor"] is None and evs[2]["servico"] == "escavacao"     # previsto sem quantidade
    fatos = evidencias.consolidar(evs + evidencias.loop([], construtivos=_construtivos(), epsg=EPSG))
    tubo = fatos[(fatos["codigo"] == "U2.*.HID.TUB.RED") & (fatos["unidade"] == "m")].iloc[0]
    assert sorted(a["valor"] for a in tubo["afirmacoes"]) == [180.0, 180.0]   # planilha 100 + 80 × desenho 180
    assert tubo["status"] == "convergente"


def test_servicos_associados_por_formula():
    evs, sem_valor = associados.de_elementos(_construtivos(), EPSG)
    por = {(e["codigo"], e["servico"]): e for e in evs if e["documento"]["id"] != "metodo:mos_sanepar"}
    assert por[("U1.FILTROS.GEO.MOV.ESC", "")]["valor"] == pytest.approx(20.0, rel=1e-3)   # (16 + 0,5·16 + 1)·0,80
    assert por[("U1.FILTROS.GEO.MOV.REA", "")]["valor"] == pytest.approx(7.2, rel=1e-3)
    assert por[("U1.FILTROS.GEO.FUN.BLO", "forma")]["valor"] == pytest.approx(12.0, rel=1e-3)
    assert por[("U1.FILTROS.GEO.FUN.BLO", "lastro")]["valor"] == pytest.approx(16 * 0.05, rel=1e-3)   # área × e
    # vala (camadas.dimensoes): escavação abaixo dos 0,35 m de pavimento; demolição em b + 2 × 0,15
    assert por[("U2.AAT06.GEO.MOV.VAL", "escavacao")]["valor"] == pytest.approx(1.23 * (1.73 - 0.35) * 180, rel=1e-3)
    assert por[("U2.AAT06.CIV.PAV.REC", "demolicao")]["valor"] == pytest.approx(180 * 1.53, rel=1e-3)
    assert por[("U2.AAT06.GEO.MOV.VAL", "escoramento_pontaleteamento")]["valor"] == pytest.approx(2 * 1.73 * 180, rel=1e-3)
    assert "Af = A + f * P + 4 * f ** 2 = 25" in por[("U1.FILTROS.GEO.MOV.ESC", "")]["trecho"]   # memória de cálculo
    assert "u1-FILTROS-pilar-P5 (falta A_forma ← h)" in sem_valor["forma"]            # o pilar não tem altura: não inventa


def test_servico_associado_sem_atributo_nao_inventa_valor():
    c = _construtivos()
    bloco = next(f for f in c["geojson"]["features"] if f["properties"]["classe"] == "bloco")
    bloco["properties"]["atributos"] = [a for a in bloco["properties"]["atributos"] if a[0] != "Face superior (cota, m)"]
    evs, sem_valor = associados.de_elementos(c, EPSG)
    assert "u1-FILTROS-bloco-P5 (falta V ← h ← face)" in sem_valor["concreto"]
    assert not any(e["localizador"] == "u1-FILTROS-bloco-P5" and e["regra"] == "concreto" for e in evs)
    assert any(e["localizador"] == "u1-FILTROS-bloco-P5" and e["regra"] == "lastro" for e in evs)   # A_fundo não depende de h


def test_laje_gera_escoramento_e_associado_nao_citado_no_edital_e_sinalizado():
    docs = [{**PROJETO, "id": "memorial.pdf", "paginas": ["Laje de cobertura: 120,00 m2"]},
            {**PROJETO, "id": "edital.pdf", "tipo": "edital", "paginas": ["Laje de cobertura com 120 m2 de área."]}]
    evs = evidencias.loop(docs)
    esc = [e for e in evs if e["regra"] == "escoramento"]
    assert len(esc) == 1 and esc[0]["codigo"] == "U1.*.CIV.EST.PIS" and esc[0]["valor"] == 120.0
    tabela = evidencias.associados_x_edital(evs)
    assert tabela.iloc[0]["situacao"] == "não citado no edital: incluir ou confirmar"
    evs2 = evidencias.loop(docs + [{**PROJETO, "id": "planilha.pdf", "tipo": "edital",
                                    "paginas": ["Escoramento de lajes 120 m2"]}])
    assert evidencias.associados_x_edital(evs2).iloc[0]["situacao"] == "citado no edital"


def test_cobertura_projeto_x_edital():
    evs = evidencias.loop([{**PROJETO, "id": "edital.pdf", "tipo": "edital", "paginas": ["Bombas centrífugas 4 un"]}],
                          construtivos=_construtivos(), epsg=EPSG)
    cob = evidencias.cobertura(evs).set_index(["unidade", "item"])["situacao"]
    assert cob[("U1", "GEO.FUN.EST")] == "só projeto: verificar se o edital considera"
    assert cob[("U1", "HID.EQP.EQU")] == "só edital: sem evidência no projeto"
    assert cob[("U1", "CIV.EST.VIG")] == "sem evidência"
    assert ("U2", "GEO.FUN.EST") not in cob.index                          # estaca não é item de obra linear


def test_catalogo_baliza_itens_e_separa_escopo():
    cat = {"1": {"descricao": "TUBO FD K7 DN 300", "subcategoria": "tubo"},
           "2": {"descricao": "TUBO FD PARA ESGOTO DN 300", "subcategoria": "tubo"},
           "3": {"descricao": "ANEL DE CONCRETO PARA POCO DE VISITA", "subcategoria": "nao_classificado"},
           "4": {"descricao": "MOTOBOMBA CENTRIFUGA 50 CV", "subcategoria": "motobomba"}}
    agua = evidencias.catalogo_por_item(cat, "agua").set_index("item")["n_materiais"]
    assert agua.to_dict() == {"HID.TUB.RED": 1, "HID.EQP.EQU": 1}
    esgoto = evidencias.catalogo_por_item(cat, "esgoto").set_index("item")["n_materiais"]
    assert esgoto.to_dict() == {"HID.TUB.RED": 2, "HID.TUB.PVS": 1, "HID.EQP.EQU": 1}


def test_registro_jsonl_sem_repetir(tmp_path):
    evs = evidencias.loop([{**PROJETO, "paginas": ["300 estacas"]}] * 2)
    caminho = evidencias.gravar(evs, tmp_path / "evidencias.jsonl")
    assert len(evidencias.ler(caminho)) == 1


def test_etapa_grava_registro_e_tabelas(tmp_path):
    dados = _dados()
    dados["construtivos"] = construtivos.montar(dados, CFG)
    resumo = evidencias.etapa({}, tmp_path, dados, log=lambda *a: None)
    assert {"fatos", "cobertura", "associados", "dimensoes"} <= set(resumo) and resumo["n_evidencias"] > 0
    json.loads(json.dumps(resumo, allow_nan=False))                     # vai para o dados.json do HTML
    assert all((tmp_path / n).exists() for n in ("evidencias.jsonl", "fatos.csv", "cobertura.csv", "associados.csv", "dimensoes.csv"))
    assert all(evidencias.validar_evidencia(e) == [] for e in evidencias.ler(tmp_path / "evidencias.jsonl"))


# planilha Obras Lineares como fonte ----------------------------------------------------------------------------------
DOC_PLANILHA = {"id": "planilha_sanepar.xlsx", "tipo": "planilha", "nome": "aba Obras Lineares"}


def _trecho_linear(**planilha):
    """Trecho no formato de `ler_obras_lineares`: entrada + `planilha` com o que foi digitado (escoramento é sim/não)."""
    return {"linha": 4, "local": "Entrada de água bruta", "dn_mm": 1000.0, "material": "FD", "prof_m": 2.4, "comp_m": 57.3,
            "metodo": "VCA", "pavimentos": {"grama": 57.3}, "supressao_frac": 1.0,
            "planilha": {"escoramento": "sim", "largura_m": 2.1, "area_m2": 120.33, "escavacao_m3": 288.792,
                         "reaterro_m3": 243.789, "bota_fora_m3": 58.504, "supressao_m2": 120.33, **planilha}}


def _fatos_lineares(trecho):
    evs = evidencias.de_obras_lineares([trecho], DOC_PLANILHA) + evidencias.de_obras_lineares_mos([trecho], [])
    assert all(evidencias.validar_evidencia(e) == [] for e in evs)
    return evidencias.consolidar(evs).set_index(["codigo", "servico", "unidade"])


def test_planilha_obras_lineares_vira_evidencia_por_trecho_e_grandeza():
    evs = evidencias.de_obras_lineares([_trecho_linear(reaterro_m3=None)], DOC_PLANILHA)
    q = {(e["codigo"], e["servico"], e["unidade"]): e["valor"] for e in evs}
    assert q == {("U1.LINEARES.HID.TUB.RED", "assentamento", "m"): 57.3,
                 ("U1.LINEARES.GEO.MOV.VAL", "escavacao", "m³"): 288.792,
                 ("U1.LINEARES.GEO.MOV.VAL", "bota_fora", "m³"): 58.504,
                 ("U1.LINEARES.GEO.MOV.SUP", "", "m²"): 120.33}                 # sem reaterro (None) e sem escoramento
    assert all(e["parcela"] and e["metodo"] == "planilha" and e["regra"] == "obras_lineares.planilha" for e in evs)
    assert all(e["localizador"] == "Entrada de água bruta, linha 4" and e["trecho"].startswith("Entrada de água bruta")
               for e in evs)
    assert all(evidencias.validar_evidencia(e) == [] for e in evs)
    outra = evidencias.de_obras_lineares([_trecho_linear(escavacao_m3=0.0)], DOC_PLANILHA, base="U3.REDE")
    assert {e["codigo"] for e in outra} == {"U3.REDE.HID.TUB.RED", "U3.REDE.GEO.MOV.VAL", "U3.REDE.GEO.MOV.SUP"}
    assert not any(e["servico"] == "escavacao" for e in outra)                  # zero digitado não entra


def test_mos_recalcula_os_mesmos_fatos_com_o_escoramento_total():
    mos = evidencias.de_obras_lineares_mos([_trecho_linear()], [])
    assert {e["documento"]["id"] for e in mos} == {"metodo:mos_sanepar:obras_lineares"}
    assert {e["metodo"] for e in mos} == {"associado"}
    q = {(e["servico"], e["unidade"]): e["valor"] for e in mos}
    assert q[("escavacao", "m³")] == pytest.approx(288.792) and q[("escoramento", "m²")] == pytest.approx(275.04)
    assert ("", "m²") not in q                                                  # supressão não é recalculada
    assert ("assentamento", "m") not in q                                       # o comprimento é só cópia da entrada
    assert not any("None" in e["trecho"] for e in mos)
    assert evidencias.de_obras_lineares_mos([{**_trecho_linear(), "material": "AMIANTO"}], []) == []


def test_planilha_x_mos_do_mesmo_trecho_converge_quando_o_digitado_bate():
    fatos = _fatos_lineares(_trecho_linear())
    for chave in (("U1.LINEARES.GEO.MOV.VAL", "escavacao", "m³"), ("U1.LINEARES.GEO.MOV.VAL", "reaterro", "m³"),
                  ("U1.LINEARES.GEO.MOV.VAL", "bota_fora", "m³")):
        assert fatos.loc[chave]["status"] == "convergente" and fatos.loc[chave]["forca"] == 2
    assert fatos.loc[("U1.LINEARES.HID.TUB.RED", "assentamento", "m")]["status"] == "fonte única"   # sem conferência
    assert fatos.loc[("U1.LINEARES.GEO.MOV.VAL", "escoramento", "m²")]["status"] == "fonte única"   # só o MOS
    assert fatos.loc[("U1.LINEARES.GEO.MOV.SUP", "", "m²")]["status"] == "fonte única"              # só a planilha


def test_planilha_x_mos_do_mesmo_trecho_e_conflito_quando_o_digitado_difere():
    fatos = _fatos_lineares(_trecho_linear(escavacao_m3=320.0))
    f = fatos.loc[("U1.LINEARES.GEO.MOV.VAL", "escavacao", "m³")]
    assert f["status"] == "conflito" and f["n_documentos"] == 2
    assert {a["documento"]: a["valor"] for a in f["afirmacoes"]} == {
        "planilha_sanepar.xlsx": 320.0, "metodo:mos_sanepar:obras_lineares": pytest.approx(288.792)}
    assert f["diferenca_pct"] == pytest.approx(100 * (320 - 288.792) / 320, abs=0.1)
    assert fatos.loc[("U1.LINEARES.GEO.MOV.VAL", "reaterro", "m³")]["status"] == "convergente"      # os outros seguem


def test_etapa_soma_a_planilha_obras_lineares_quando_ela_esta_no_disco(tmp_path):
    from test_obras_lineares import _planilha
    caminho = _planilha(tmp_path)
    dados = _dados()
    cfg = {"obras_lineares": {"planilha": str(caminho), "eap": "U1.LINEARES"}}
    evidencias.etapa(cfg, tmp_path / "saida", dados, log=lambda *a: None)
    evs = evidencias.ler(tmp_path / "saida" / "evidencias.jsonl")
    assert {"p.xlsx", "metodo:mos_sanepar:obras_lineares"} <= {e["documento"]["id"] for e in evs}
    fatos = pd.read_csv(tmp_path / "saida" / "fatos.csv", sep=";", decimal=",", encoding="utf-8-sig")
    esc = fatos[(fatos["codigo"] == "U1.LINEARES.GEO.MOV.VAL") & (fatos["servico"] == "escavacao")]
    assert esc["status"].tolist() == ["convergente"]
    sem = evidencias.etapa({"obras_lineares": {"planilha": str(tmp_path / "nao_existe.xlsx")}}, tmp_path / "s2", dados,
                           log=lambda *a: None)
    assert sem is None


def test_mnd_tem_recalculo_sem_largura_e_vca_sem_largura_nao():
    mnd = {**_trecho_linear(), "metodo": "MND"}
    q = {(e["servico"], e["unidade"]): e["valor"] for e in evidencias.de_obras_lineares_mos([mnd], [])}
    assert q[("escavacao", "m³")] > 0 and q[("reaterro", "m³")] > 0 and ("bota_fora", "m³") not in q   # só os caximbos
    assert evidencias.de_obras_lineares_mos([{**_trecho_linear(), "prof_m": None}], []) == []          # VCA sem profundidade
    fatos = _fatos_lineares(mnd)
    assert fatos.loc[("U1.LINEARES.GEO.MOV.VAL", "escavacao", "m³")]["status"] == "conflito"           # valas × caximbos


def test_valas_dos_elementos_e_trechos_da_planilha_no_mesmo_codigo_nao_somam_no_mesmo_documento():
    from test_dimensoes import _furo, _vala
    _, vala, _, _ = _vala({"fora_da_via": 100.0}, de_mm=300, material="TUBO FD K7", metodos=("mos_sanepar",),
                          sondagens=[_furo()])
    planilha = evidencias.de_obras_lineares_mos([_trecho_linear()], [], base="U2.AAT06")
    fatos = evidencias.consolidar(vala + planilha).set_index(["codigo", "servico", "unidade"])
    esc = fatos.loc[("U2.AAT06.GEO.MOV.VAL", "escavacao", "m³")]
    por_doc = {a["documento"]: a["valor"] for a in esc["afirmacoes"]}
    assert set(por_doc) == {"metodo:mos_sanepar", "metodo:mos_sanepar:obras_lineares"}
    assert por_doc["metodo:mos_sanepar:obras_lineares"] == pytest.approx(288.792)         # só o trecho, sem somar as valas


def test_aba_obras_lineares_conta_como_edital_na_cobertura_e_nos_associados():
    evs = evidencias.de_obras_lineares([_trecho_linear()], DOC_PLANILHA) + \
        evidencias.de_obras_lineares_mos([_trecho_linear()], [])
    ass = evidencias.associados_x_edital(evs).set_index(["item", "servico"])
    assert ass.loc[("GEO.MOV.VAL", "escavacao"), "situacao"] == "citado no edital"
    assert ass.loc[("GEO.MOV.VAL", "escoramento"), "situacao"].startswith("não citado no edital")   # a aba não traz m²
    cob = evidencias.cobertura(evs).set_index(["unidade", "item"])
    assert cob.loc[("U1", "GEO.MOV.VAL"), "situacao"] == "só edital: sem evidência no projeto"


def test_planilha_sem_a_aba_obras_lineares_nao_gera_evidencia_nem_erro(tmp_path):
    """Achado do build real de Foz: a planilha do contrato não tem a aba do protótipo."""
    import openpyxl

    planilha = tmp_path / "contrato.xlsx"
    openpyxl.Workbook().save(planilha)
    mensagens = []
    cfg = {"obras_lineares": {"planilha": str(planilha), "aba": "Obras Lineares"}}
    assert evidencias._obras_lineares_da_obra(cfg, [], log=mensagens.append) == []
    assert any("sem a aba" in m for m in mensagens)


def test_item_so_com_pacote_vira_evidencia_valida():
    """Achado do build real de Foz: classificar devolve 'CIV.EST.*' (serviço sem item), e o schema recusava o '*'."""
    import pandas as pd

    itens = pd.DataFrame([{"descricao": "Forma plana em compensado plastificado", "codigo": "", "unidade_obra": "UNIDADE 2",
                           "quantidade": 3.0, "unidade": "UN", "aba": "MATS E EQUIP", "linha_origem": 808}])
    evs = evidencias.de_planilha(itens, {"id": "escopo_itens.csv", "tipo": "planilha", "nome": "contrato"})
    assert [e["codigo"] for e in evs] == ["U2.*.CIV.EST.*"]
    assert evidencias.validar_evidencia(evs[0]) == []
