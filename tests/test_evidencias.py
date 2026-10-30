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
    por = {(e["codigo"], e["servico"]): e for e in evs}
    assert por[("U1.FILTROS.GEO.MOV.ESC", "")]["valor"] == pytest.approx(20.0, rel=1e-3)   # (16 + 0,5·16 + 1)·0,80
    assert por[("U1.FILTROS.GEO.MOV.REA", "")]["valor"] == pytest.approx(7.2, rel=1e-3)
    assert por[("U1.FILTROS.GEO.FUN.BLO", "forma")]["valor"] == pytest.approx(12.0, rel=1e-3)
    assert por[("U2.AAT06.GEO.MOV.VAL", "escavacao")]["valor"] == pytest.approx(1.23 * 1.73 * 180, rel=1e-3)
    assert por[("U2.AAT06.CIV.PAV.REC", "demolicao")]["valor"] == pytest.approx(180 * 1.53, rel=1e-3)
    assert "f=0.5" in por[("U1.FILTROS.GEO.MOV.ESC", "")]["trecho"]          # memória de cálculo
    assert sem_valor == {}


def test_servico_associado_sem_atributo_nao_inventa_valor():
    c = _construtivos()
    bloco = next(f for f in c["geojson"]["features"] if f["properties"]["classe"] == "bloco")
    bloco["properties"]["atributos"] = [a for a in bloco["properties"]["atributos"] if a[0] != "Face superior (cota, m)"]
    evs, sem_valor = associados.de_elementos(c, EPSG)
    assert "u1-FILTROS-bloco-P5" in sem_valor["bloco_concreto"]
    assert not any(e["localizador"] == "u1-FILTROS-bloco-P5" and e["regra"] == "bloco_concreto" for e in evs)


def test_laje_gera_escoramento_e_associado_nao_citado_no_edital_e_sinalizado():
    docs = [{**PROJETO, "id": "memorial.pdf", "paginas": ["Laje de cobertura: 120,00 m2"]},
            {**PROJETO, "id": "edital.pdf", "tipo": "edital", "paginas": ["Laje de cobertura com 120 m2 de área."]}]
    evs = evidencias.loop(docs)
    esc = [e for e in evs if e["regra"] == "laje_escoramento"]
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
    assert {"fatos", "cobertura", "associados"} <= set(resumo) and resumo["n_evidencias"] > 0
    json.loads(json.dumps(resumo, allow_nan=False))                     # vai para o dados.json do HTML
    assert all((tmp_path / n).exists() for n in ("evidencias.jsonl", "fatos.csv", "cobertura.csv", "associados.csv"))
    assert all(evidencias.validar_evidencia(e) == [] for e in evidencias.ler(tmp_path / "evidencias.jsonl"))
