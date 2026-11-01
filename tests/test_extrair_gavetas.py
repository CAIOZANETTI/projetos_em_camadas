import json

import openpyxl
import pytest

from camadas import extrair_gavetas as eg
from camadas import gavetas
from camadas import obras_lineares as ol


def _planilha(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Obras Lineares"
    cab = ["Local", "DN do tubo", "Tipo do tubo", "Sondagem", None, "NA (m)", "Tipo de solo", "Prof. Média",
           "Escoramento", "Comprimento Total", "Método Construtivo", "Tipo de\nPavimento 1", "Comprimento\nPavimento 1",
           "Observações"]
    for j, v in enumerate(cab, start=22):
        ws.cell(2, j, v)
    linhas = [["Entrada de água bruta", 1000, "FD", "SP-02", "SP-02", 9, "argila", 2.4, "sim", 57.3, "VCA", "grama",
               57.3, "Supressão vegetal - 100% do trecho"],
              ["Retorno lodo", 150, "FD", "SP-05", "SP-09", 7.6, "argila", None, "não", 28, "VCA", None, None, None],
              ["Travessia da Rua Pará", 300, "PEAD", "SP-15", "SP-15", 1.5, "areia", 3.0, "sim", 170, "VCA", "asfalto",
               120, None]]
    for i, linha in enumerate(linhas, start=4):
        for j, v in enumerate(linha, start=22):
            ws.cell(i, j, v)
    caminho = tmp_path / "p.xlsx"
    wb.save(caminho)
    return caminho


FUROS = [{"id": "SP-02", "E": 10.0, "N": 20.0, "na_m": 9.0, "camadas": [{"de": 0, "ate": 5, "descricao": "argila"}],
          "cota_boca_m": 650.5},
         {"id": "SP-05", "na_m": 7.6, "camadas": []}]


def test_planilha_vira_tres_objetos_e_base_confere(tmp_path):
    trechos = ol.ler_obras_lineares(_planilha(tmp_path))
    base = eg.de_obras_lineares(trechos, "p.xlsx")
    assert [o["objeto_id"] for o in base["objetos"]] == ["OL-004", "OL-005", "OL-006"]
    assert gavetas.conferir_base(eg.juntar(base)) == []
    assert not base["geometria"]
    ev = {e["evidencia_id"]: e for e in base["evidencias"]}
    for f in base["fatos"]:
        loc = ev[f["evidencia_id"]]["localizador"]
        assert loc["aba"] == "Obras Lineares" and isinstance(loc["linha"], int)
    naturezas = {f["propriedade"]: f["natureza"] for f in base["fatos"]}
    assert naturezas["na_m"] == naturezas["solo"] == "observado" and naturezas["prof_m"] == "projetado"


def test_prof_vazia_nao_vira_fato(tmp_path):
    base = eg.de_obras_lineares(ol.ler_obras_lineares(_planilha(tmp_path)), "p.xlsx")
    props = {(f["objeto_id"], f["propriedade"]) for f in base["fatos"]}
    assert ("OL-005", "prof_m") not in props and ("OL-004", "prof_m") in props
    assert ("OL-005", "pavimentos") not in props


def test_furos_com_e_sem_coordenadas():
    base = eg.de_sondagens(FUROS, "sondagens.json", executor="Sonnet")
    assert base["geometria"] == [{"objeto_id": "SP-02", "tipo": "ponto", "coords": [10.0, 20.0],
                                  "crs_h": "EPSG:31982", "datum_v": "ortométrico"}]
    assert base["pendencias"] == [{"objeto_id": "SP-05", "motivo": "furo sem coordenadas: entra só pelo nome citado na planilha, não pela posição no eixo"}]
    assert {e["executor"] for e in base["evidencias"]} == {"Sonnet"}
    assert base["evidencias"][0]["localizador"] == {"arquivo": "sondagens.json", "furo": "SP-02"}
    assert not any(f["objeto_id"] == "SP-05" and f["propriedade"] == "cota_boca_m" for f in base["fatos"])
    assert gavetas.conferir_base(base) == []


def test_decisao_casa_por_local_normalizado(tmp_path):
    trechos = ol.ler_obras_lineares(_planilha(tmp_path))
    base = eg.de_decisoes({"TRAVESSIA DA RUA PARA": "MND", "Local fantasma": "MND"}, trechos, "obra.json")
    fato, = base["fatos"]
    assert fato["objeto_id"] == "OL-006" and fato["natureza"] == "decidido" and fato["valor"] == "MND"
    assert base["evidencias"][0]["executor"] == "você" and base["evidencias"][0]["classe"] == "decisao"
    assert len(base["pendencias"]) == 1 and "Local fantasma" in base["pendencias"][0]["objeto_id"]


def test_juntar_idempotente_e_conflito(tmp_path):
    trechos = ol.ler_obras_lineares(_planilha(tmp_path))
    a = eg.de_obras_lineares(trechos, "p.xlsx")
    assert eg.juntar(a, a) == eg.juntar(a)
    b = eg.de_obras_lineares(trechos, "outra.xlsx")
    with pytest.raises(ValueError, match="EV-OL-4"):
        eg.juntar(a, b)


def test_decisao_convive_com_o_metodo_da_planilha_e_comp_zero_nao_vira_fato():
    from camadas import gavetas
    trechos = [{"linha": 7, "local": "Entrada de água bruta", "dn_mm": 300.0, "material": "FD", "prof_m": 2.0,
                "comp_m": 10.0, "metodo": "VCA"},
               {"linha": 8, "local": "Descarga", "dn_mm": 200.0, "material": "FD", "prof_m": 1.5, "comp_m": 0.0,
                "metodo": "VCA"}]
    base = eg.juntar(eg.de_obras_lineares(trechos, "p.xlsx"),
                     eg.de_decisoes({"ENTRADA DE AGUA BRUTA": "MND"}, trechos, "obra.json"))
    assert gavetas.conferir_base(base) == []
    assert gavetas.fatos_do_objeto(base, "OL-007")["metodo"]["natureza"] == "decidido"
    assert "comp_m" not in gavetas.fatos_do_objeto(base, "OL-008")


def _cfg(tmp_path, **extra):
    planilha = _planilha(tmp_path)
    return {"obras_lineares": {"planilha": str(planilha), "metodo": {"TRAVESSIA DA RUA PARA": "MND"}},
            "sondagens": "sondagens.json", **extra}


def test_etapa_grava_base_paridade_e_resumo(tmp_path):
    furos = [{"id": "SP-02", "E": 0.0, "N": 0.0, "na_m": 9.0,
              "camadas": [{"de": 0, "ate": 8, "descricao": "Argila siltosa"}]}]
    out = tmp_path / "saida"
    out.mkdir()
    mensagens = []
    resumo = eg.etapa(_cfg(tmp_path), furos, out, log=mensagens.append)
    assert list(out.glob("base/*.parquet")) and mensagens
    assert json.loads((out / "paridade.json").read_text(encoding="utf-8")) == []
    gravado = json.loads((out / "resumo.json").read_text(encoding="utf-8"))
    assert {"objetos_por_classe", "fatos_por_natureza", "fatos_por_executor", "pendencias_por_motivo",
            "erros_conferencia", "diferencas_paridade", "servicos", "eap"} <= set(gravado)
    assert resumo["fatos_por_natureza"]["decidido"] == 1 and resumo["erros_conferencia"] == []
    assert resumo["objetos_por_classe"] == {"trecho_tubo": 3, "furo_sondagem": 1}
    assert gavetas.conferir_base(gavetas.ler(out / "base")) == []
    eap = resumo["eap_html"]                                   # rodada 23: o dados["eap"] da aba EAP
    assert eap["nos"] and set(eap["resumo"]) == {"servicos", "nos", "pendencias", "diferencas_paridade",
                                                  "recalculados", "reaproveitados"}
    assert all(f["evidencia"]["onde"] for n in eap["nos"] for s in n["servicos"] for f in s["fatos"])
    assert "eap_html" not in gravado and json.dumps(eap)       # o resumo.json fica leve; o HTML embute o eap


def test_etapa_sem_planilha_devolve_none(tmp_path):
    assert eg.etapa({}, [], tmp_path) is None
    cfg = {"obras_lineares": {"planilha": str(tmp_path / "nao_existe.xlsx")}}
    assert eg.etapa(cfg, [], tmp_path, log=lambda *_: None) is None


def test_decisao_vale_para_todos_os_trechos_do_mesmo_local():
    trechos = [{"linha": 4, "local": "Rede B", "dn_mm": 160.0, "material": "PEAD", "comp_m": 10.0, "metodo": "VCA"},
               {"linha": 5, "local": "rede b", "dn_mm": 160.0, "material": "PEAD", "comp_m": 20.0, "metodo": "VCA"}]
    base = eg.de_decisoes({"REDE B": "MND"}, trechos, "obra.json")
    assert [f["fato_id"] for f in base["fatos"]] == ["OL-004.metodo.decidido", "OL-005.metodo.decidido"]
    assert [e["evidencia_id"] for e in base["evidencias"]] == ["EV-DEC-4", "EV-DEC-5"]
    assert {f["evidencia_id"] for f in base["fatos"]} == {e["evidencia_id"] for e in base["evidencias"]}
    assert base["pendencias"] == []


def _planilha_em_branco(tmp_path):
    """Uma linha com método, material e observação em branco (e uma com tudo preenchido)."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Obras Lineares"
    cab = ["Local", "DN do tubo", "Tipo do tubo", "Sondagem", None, "NA (m)", "Tipo de solo", "Prof. Média",
           "Escoramento", "Comprimento Total", "Método Construtivo", "Observações"]
    for j, v in enumerate(cab, start=22):
        ws.cell(2, j, v)
    for i, linha in enumerate([["Vazio", 200, None, "SP-02", "SP-02", 9, "argila", 2.0, "não", 10, None, None],
                               ["Cheio", 200, "FD", "SP-02", "SP-02", 9, "argila", 2.0, "não", 10, "VCA", "Supressão - 50%"]],
                              start=4):
        for j, v in enumerate(linha, start=22):
            ws.cell(i, j, v)
    caminho = tmp_path / "branco.xlsx"
    wb.save(caminho)
    return caminho


def test_leitor_guarda_o_cru_e_celula_em_branco_nao_vira_fato(tmp_path):
    trechos = ol.ler_obras_lineares(_planilha_em_branco(tmp_path))
    vazio, cheio = trechos
    assert vazio["metodo"] == "VCA" and vazio["metodo_lido"] is None and vazio["supressao_lida"] is False
    assert cheio["metodo_lido"] == "VCA" and cheio["supressao_lida"] is True
    base = eg.de_obras_lineares(trechos, "branco.xlsx")
    props = {(f["objeto_id"], f["propriedade"]) for f in base["fatos"]}
    assert not {("OL-004", "metodo"), ("OL-004", "supressao_frac"), ("OL-004", "material")} & props
    assert {("OL-005", "metodo"), ("OL-005", "supressao_frac"), ("OL-005", "material")} <= props
    _, pend = gavetas.calcular(eg.juntar(base))
    motivos = [p["motivo"] for p in pend if p["objeto_id"] == "OL-004"]
    assert motivos == ["faltam fatos obrigatórios: material"]


def test_trecho_sem_as_chaves_novas_mantem_o_comportamento_antigo():
    t = {"linha": 7, "local": "A", "dn_mm": 300.0, "material": "FD", "prof_m": 2.0, "comp_m": 10.0, "metodo": "VCA",
         "supressao_frac": 0.0}
    props = {f["propriedade"] for f in eg.de_obras_lineares([t], "p.xlsx")["fatos"]}
    assert {"metodo", "supressao_frac", "material"} <= props


def test_etapa_com_gavetas_nulo_nao_quebra(tmp_path):
    out = tmp_path / "saida"
    out.mkdir()
    resumo = eg.etapa(_cfg(tmp_path, gavetas=None), [], out, log=lambda *_: None)
    assert resumo is not None


def test_etapa_segunda_rodada_no_mesmo_out_nao_recalcula_nada(tmp_path):
    cfg = _cfg(tmp_path)
    out = tmp_path / "out"
    r1 = eg.etapa(cfg, [], out, log=lambda *_: None)
    assert r1["recalculados"] > 0 and r1["reaproveitados"] == 0
    r2 = eg.etapa(cfg, [], out, log=lambda *_: None)
    assert r2["recalculados"] == 0 and r2["reaproveitados"] == r1["recalculados"]
    assert json.loads((out / "resumo.json").read_text(encoding="utf-8"))["recalculados"] == 0


def _rede_vala(n=40, criterio="divisas"):
    import numpy as np
    return {"id": "R1", "de_mm": 300, "fonte_de": "t", "criterio": criterio, "pranchas": ["P1", "P2"],
            "extensao_m": float(n), "pts": np.c_[np.arange(n) + 0.5, np.zeros(n)], "tang": np.tile([1.0, 0.0], (n, 1)),
            "peso": np.ones(n), "classes": ["pista"] * 25 + ["calcada"] * 10 + ["vegetacao"] * 5,
            "finais": [None] * 35 + ["grama"] * 5, "quadro": []}


def test_rede_de_vala_passa_por_gavetas_e_paridade():
    rede = _rede_vala()
    base = eg.de_valas([rede])
    assert gavetas.conferir_base(base) == [] and base["objetos"] == [{"objeto_id": "RV-R1", "classe": "rede_vala"}]
    assert {f["propriedade"]: f["natureza"] for f in base["fatos"]} == {
        "de_mm": "projetado", "extensao_m": "projetado", "classes_por_metro": "projetado", "pesos_m": "projetado",
        "finais": "projetado"}
    ev = base["evidencias"][0]
    assert ev["classe"] == "projeto" and ev["localizador"] == {"pranchas": ["P1", "P2"], "criterio": "divisas"}
    servicos, pend = gavetas.calcular(base)
    assert pend == [] and {s["saida"] for s in servicos} == {"demolicao_m2", "recomposicao_m2", "volume_vala_m3"}
    assert eg.paridade_valas(base, [rede]) == []
    assert {"RD.01.pista", "RD.02.calcada", "RD.03.vegetacao/grama"} <= {n["eap"] for n in gavetas.para_eap(servicos)}
    assert gavetas.conferir_de_para() == []
    assert eg.paridade_valas(base, [{**rede, "peso": rede["peso"] * 1.5}])      # base defasada: a paridade acusa
    por_ortofoto = eg.de_valas([_rede_vala(criterio="ortofoto")])
    assert {f["natureza"] for f in por_ortofoto["fatos"] if f["propriedade"] == "pesos_m"} == {"inferido"}


def test_etapa_com_redes_vala_grava_servicos(tmp_path):
    out = tmp_path / "saida"
    out.mkdir()
    resumo = eg.etapa(_cfg(tmp_path), [], out, log=lambda *_: None, redes_vala=[_rede_vala()])
    assert resumo["objetos_por_classe"]["rede_vala"] == 1 and resumo["erros_conferencia"] == []
    servicos = gavetas.ler(out / "base")["servicos"]
    assert {s["saida"] for s in servicos if s["objeto_id"] == "RV-R1"} == {"demolicao_m2", "recomposicao_m2", "volume_vala_m3"}
    assert json.loads((out / "paridade.json").read_text(encoding="utf-8")) == []


# --- E3 (rodada 24): fatos da IA na etapa ---------------------------------------------------------------------------

def _linha_ia(**extra):
    return {"arquivo": "laudo.pdf", "pasta_drive": "SONDAGENS", "executor": "Sonnet", "classe": "laudo",
            "citacao": {"pagina": 2, "trecho": "N.A. a 1,80 m"},
            "fatos": [{"objeto_id": "SP-77", "propriedade": "na_m", "valor": 1.8},
                      {"objeto_id": "SP-77", "propriedade": "dn_mm", "valor": 300}], **extra}


def _jsonl(pasta, nome="a.jsonl", linhas=()):
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / nome).write_text("\n".join(l if isinstance(l, str) else json.dumps(l) for l in linhas) + "\n",
                              encoding="utf-8")
    return pasta


def test_retorno_com_fato_permitido_e_fato_fora_do_de_para(tmp_path):
    base = eg.de_retornos(_jsonl(tmp_path / "r", linhas=[_linha_ia()]))
    assert len(base["fatos"]) == 1
    fato, ev = base["fatos"][0], base["evidencias"][0]
    assert (fato["propriedade"], fato["natureza"], fato["executor"]) == ("na_m", "inferido", "Sonnet")
    assert ev["executor"] == "Sonnet" and ev["trecho"] == "N.A. a 1,80 m" and ev["metodo"] == "IA"
    assert [p["objeto_id"] for p in base["pendencias"]] == ["SP-77"]
    motivo = base["pendencias"][0]["motivo"]
    assert motivo.startswith("retorno de IA recusado: ") and "(dn_mm)" in motivo
    assert gavetas.conferir_base(eg.juntar(base)) == []


def test_retorno_sem_trecho_vira_so_pendencia(tmp_path):
    base = eg.de_retornos(_jsonl(tmp_path / "r", linhas=[_linha_ia(citacao={"pagina": 1, "trecho": ""})]))
    assert base["fatos"] == [] and base["objetos"] == [] and len(base["pendencias"]) == 2
    assert all("sem trecho citado" in p["motivo"] for p in base["pendencias"])


def test_linha_invalida_vira_pendencia_e_a_leitura_segue(tmp_path):
    pasta = _jsonl(tmp_path / "r", linhas=["{isto nao e json", _linha_ia()])
    base = eg.de_retornos(pasta)
    assert len(base["fatos"]) == 1
    assert any(p["objeto_id"] == "a.jsonl" and "linha 1" in p["motivo"] for p in base["pendencias"])
    assert eg.de_retornos(pasta) == base                                           # determinístico


def test_objeto_ia_ja_existente_nao_duplica_e_classe_diferente_vira_pendencia(tmp_path):
    existente = eg.de_sondagens(FUROS, "sondagens.json")
    linha = _linha_ia(fatos=[{"objeto_id": "SP-02", "propriedade": "cota_boca_m", "valor": 651.0}])
    ia = eg._conciliar_com_a_base(eg.de_retornos(_jsonl(tmp_path / "r", linhas=[linha])), existente)
    base = eg.juntar(existente, ia)
    assert [o["objeto_id"] for o in base["objetos"]].count("SP-02") == 1 and gavetas.conferir_base(base) == []
    trecho = {"objeto_id": "SP-02", "classe": "trecho_tubo"}
    ia = eg._conciliar_com_a_base({**ia, "objetos": [trecho], "pendencias": []}, existente)
    assert ia["objetos"] == [] and "classe difere" in ia["pendencias"][0]["motivo"]


def test_etapa_com_retornos_conta_fatos_e_recusas_da_ia(tmp_path):
    out = tmp_path / "saida"
    _jsonl(out / "retornos_gavetas", linhas=[_linha_ia()])
    resumo = eg.etapa(_cfg(tmp_path), [{"id": "SP-02", "E": 0.0, "N": 0.0, "na_m": 9.0, "camadas": []}], out,
                      log=lambda *_: None)
    assert resumo["fatos_ia"] == 1 and resumo["recusas_ia"] == 1 and resumo["erros_conferencia"] == []
    assert resumo["fatos_por_natureza"]["inferido"] == 1
    assert gavetas.conferir_base(gavetas.ler(out / "base")) == []


def test_na_do_laudo_observado_vence_o_inferido_da_ia(tmp_path):
    laudo = eg.de_sondagens(FUROS, "sondagens.json")
    linha = _linha_ia(fatos=[{"objeto_id": "SP-02", "propriedade": "na_m", "valor": 3.3}])
    ia = eg._conciliar_com_a_base(eg.de_retornos(_jsonl(tmp_path / "r", linhas=[linha])), laudo)
    base = eg.juntar(laudo, ia)
    assert sum(f["propriedade"] == "na_m" and f["objeto_id"] == "SP-02" for f in base["fatos"]) == 2
    escolhido = gavetas.fatos_do_objeto(base, "SP-02")["na_m"]
    assert escolhido["natureza"] == "observado" and escolhido["valor"] == 9.0
