import json
import re

import pytest

from camadas import escopo_obra, geo

EPSG = 31981
E0, N0 = 745000.0, 7182000.0
FRASE_REGRA = ("Desta forma, para fins de orçamentação, as unidades a executar na 1ª etapa de obra, conforme o referido "
               "Desenho 004, são as que estão representadas nas seguintes Convenções.")
FRASE_600 = "Observa-se que os dois Módulos de Tratamento com Micro Areia de 600 L/s terão a estrutura civil implantada em 1ª etapa de obra."
DESCRITIVO = ("DESCRITIVO TÉCNICO\n\n4. INFRAESTRUTURA PARA OS SISTEMAS DE MICROAREIA 360 E 600 L/s\n\n"
              "Execução de obra civil de fundações, estruturas e revestimento da superfície para implantação de módulo de "
              "tratamento. Deve-se atentar ao escoramento, ao reaterro e à compactação dos solos escavados.\n\n"
              "5. SISTEMA DE MICROAREIA 360 L/s\n\nEngenharia básica e detalhada do módulo de clarificação, com valor de R$ 100,00 por item.\n")
CORPUS = {"textos": {"Escopo_1etapa.pdf": [f"Observação sobre a obra.\n\n{FRASE_REGRA}\n\n{FRASE_600}"],
                     "Descritivo.pdf": [DESCRITIVO]},
          "relacao": {"arquivo": "Relacao de Desenhos.pdf", "linhas": [
              {"pagina": 1, "folha": "08/21", "stem": "008-ACT01ARMADURA-R0", "conteudo": "ARMADURA DAS LAJES DO FUNDO",
               "unidade": "ACTIFLO 600 LITROS"},
              {"pagina": 1, "folha": "09/21", "stem": "009-ACT01ARMADURA-R0", "conteudo": "ARMADURA DAS PAREDES: PAR1 a PAR3",
               "unidade": "ACTIFLO 600 LITROS"},
              {"pagina": 1, "folha": "04/12", "stem": "004-ACT02ARMADURA-R0", "conteudo": "ARMADURA DAS LAJES DO FUNDO",
               "unidade": "ACTIFLO 360 LITROS"}]}}


def _ll(e, n):
    return list(geo.para_lonlat(E0 + e, N0 + n, EPSG))


def _quadrado(e, n, lado):
    pontos = [_ll(e - lado, n - lado), _ll(e + lado, n - lado), _ll(e + lado, n + lado), _ll(e - lado, n + lado)]
    return {"type": "Polygon", "coordinates": [pontos + [pontos[0]]]}


def _ponto(e, n):
    return {"type": "Point", "coordinates": _ll(e, n)}


def _f(sistema, classe, geometria, doc):
    return {"type": "Feature", "geometry": geometria,
            "properties": {"id": f"{sistema}-{classe}", "classe": classe, "sistema": sistema, "doc": doc}}


def _mancha(classe, e, n, lado):
    return {"id": f"f004-{classe}", "geojson": {"features": [{"type": "Feature", "geometry": _quadrado(e, n, lado),
                                                                "properties": {"classe": classe, "etapa": classe}}]}}


def _item(arquivo, pasta, tipo="documento", titulo=None):
    return {"arquivo": arquivo, "pasta_drive": pasta, "situacao": "no disco", "tipo": tipo, "carimbo": {"titulo": titulo}}


def _dados(q1=440.0, q2=0.0):
    """ACT600 (1ª etapa), ETL (2ª etapa), GUARITA (fora de toda mancha) e a rede AAT06 com 1 tabela de contrato."""
    feicoes = [_f("u1-ACT600", "estaca", _ponto(50, 50), "003-FUNDACAO1"), _f("u1-ACT600", "estaca", _ponto(60, 50), "003-FUNDACAO1"),
               _f("u1-ETL", "estaca", _ponto(300, 50), "005-FUNDACAO3"), _f("u1-ETL", "estaca", _ponto(310, 50), "005-FUNDACAO3"),
               _f("u1-GUARITA", "estaca", _ponto(900, 50), "005-FUNDACAO3"),
               _f("u2-AAT06", "trecho", {"type": "LineString", "coordinates": [_ll(0, 500), _ll(100, 500)]}, "009-AAT06PTPER-R1")]
    sistemas = lambda *ids: [{"id": i, "nome": i, "estado": "confirmado", "classes": {}} for i in ids]
    return {
        "crs": {"epsg": EPSG},
        "construtivos": {"arvore": [{"id": "u1", "sistemas": sistemas("u1-ACT600", "u1-ETL", "u1-GUARITA")},
                                    {"id": "u2", "sistemas": sistemas("u2-AAT06")}],
                         "geojson": {"type": "FeatureCollection", "features": feicoes}},
        "vetores": [_mancha("1ª etapa", 55, 50, 30), _mancha("2ª etapa", 305, 50, 30)],
        "pranchas": [{"id": "f004", "nome": "Folha 04 · Layout de processo", "pdf": "004-LAYOUT-R5.pdf"},
                     {"id": "fu1", "nome": "Fundação 1", "pdf": "003-FUNDACAO1.pdf"}],
        "inventario": {"itens": [_item("Escopo_1etapa.pdf", "UNIDADE 01/ANEXO C"), _item("Descritivo.pdf", "UNIDADE 01"),
                                 _item("Relacao de Desenhos.pdf", "UNIDADE 01/QUANTITATIVOS"),
                                 _item("008-ACT01ARMADURA-R0.PDF", "UNIDADE 01/ACT600", "detalhe"),
                                 _item("004-LAYOUT-R5.pdf", "UNIDADE 01/PBHI", "planta"),
                                 _item("003-FUNDACAO1.pdf", "UNIDADE 01/PBGE", "planta")]},
        "escopo": {"fonte": "211 - SAA.xlsx — aba MATS", "desenhos_por_tabela": {"93": "009-AAT06PTPER-R1"},
                   "tubo_x_desenho": [{"prancha": "aat06_09", "tabelas": ["93"]}],
                   "itens": [{"tabela": "93", "nome_tabela": "ADUTORA", "item": "01", "codigo": "309244",
                              "descricao": "TUBO POLIETILENO PE 100 PN 10 DE 630", "un": "m", "q1": q1, "q2": q2}]},
    }


def _cfg(tmp_path, manual=None):
    lista = tmp_path / "listagem.csv"
    lista.write_text("caminho;titulo;id;mimeType\nUNIDADE 01/ANEXO C;Escopo_1etapa.pdf;ID_ESCOPO;application/pdf\n"
                     "UNIDADE 01;Descritivo.pdf;ID_DESC;application/pdf\n"
                     "UNIDADE 01/ACT600;008-ACT01ARMADURA-R0.PDF;ID_ARM8;application/pdf\n", encoding="utf-8")
    return {"inventario": {"listagem": str(lista)}, "valas": {"redes": [{"id": "AAT06", "pranchas": ["aat06_09"]}]},
            "escopo_unidades": {"regra": "1ª etapa = convenções do desenho 004", "documento_regra": "Escopo_1etapa.pdf",
                                **({"manual": manual} if manual else {})}}


def _montar(tmp_path, manual=None, **kw):
    return escopo_obra.montar(_dados(**kw), _cfg(tmp_path, manual), CORPUS)


def _parte(sistema, pid):
    return next(p for p in sistema["decomposicao"] if p["id"] == pid)


def test_estado_pela_convencao_da_folha_04(tmp_path):
    s = _montar(tmp_path)["sistemas"]
    assert (s["u1-ACT600"]["estado"], s["u1-ACT600"]["origem"]) == ("dentro", "convenção")
    assert "100 % na mancha '1ª etapa'" in s["u1-ACT600"]["motivo"]
    assert (s["u1-ETL"]["estado"], s["u1-ETL"]["origem"]) == ("fora", "convenção")
    assert "2ª etapa" in s["u1-ETL"]["motivo"]
    guarita = s["u1-GUARITA"]
    assert (guarita["estado"], guarita["origem"]) == ("a definir", "sem regra")
    assert "não toca nenhuma mancha" in guarita["motivo"]


def test_regra_e_documento_da_regra_com_trecho_real(tmp_path):
    saida = _montar(tmp_path)
    assert saida["regra"].startswith("1ª etapa") and saida["documento_regra"] == "Escopo_1etapa"
    evs = saida["sistemas"]["u1-ACT600"]["evidencias"]
    assert evs[0]["doc"] == "Escopo_1etapa" and evs[0]["pagina"] == 1
    assert "as unidades a executar na 1ª etapa" in evs[0]["trecho"]
    assert {"doc": "004-LAYOUT-R5", "trecho": None, "pagina": None} in evs                    # o desenho 004 das manchas
    assert any(e["trecho"] and "dois Módulos" in e["trecho"] for e in evs)                    # a frase do 600 L/s


def test_manual_sobrepoe_a_convencao(tmp_path):
    manual = {"ACT600": {"estado": "fora", "fonte": "Caio, 30/10/2026: fora do escopo"}}
    s = _montar(tmp_path, manual)["sistemas"]["u1-ACT600"]
    assert (s["estado"], s["origem"]) == ("fora", "manual")
    assert "Caio, 30/10/2026" in s["motivo"] and "convenção" in s["motivo"]                  # diz também o que a convenção daria
    assert _montar(tmp_path, manual)["sistemas"]["u1-ETL"]["origem"] == "convenção"            # os outros seguem a regra


def test_rede_pelo_contrato(tmp_path):
    dentro = _montar(tmp_path)["sistemas"]["u2-AAT06"]
    assert (dentro["estado"], dentro["origem"]) == ("dentro", "contrato")
    assert dentro["evidencias"][0] == {"doc": "contrato-T93", "pagina": None,
                                       "trecho": "01 · 309244 · TUBO POLIETILENO PE 100 PN 10 DE 630 · 440 / 0 (m)"}
    assert _montar(tmp_path, q1=0.0, q2=120.0)["sistemas"]["u2-AAT06"]["estado"] == "fora"       # só 2ª etapa
    sem = _dados()
    sem["escopo"]["itens"] = []
    assert escopo_obra.montar(sem, _cfg(tmp_path), CORPUS)["sistemas"]["u2-AAT06"]["estado"] == "a definir"


def test_parte_com_geometria_com_documento_e_sem_evidencia(tmp_path):
    act = _montar(tmp_path)["sistemas"]["u1-ACT600"]
    assert act["tipologia"] == "estrutura_concreto"
    estacas = _parte(act, "estacas")
    assert (estacas["estado"], estacas["n_geometria"]) == ("geometria", 2)
    assert estacas["evidencias"] == [{"doc": "003-FUNDACAO1", "trecho": None, "pagina": None}]
    laje = _parte(act, "laje_fundo")
    assert laje["estado"] == "documento" and laje["n_geometria"] == 0
    assert laje["evidencias"][0]["doc"] == "008-ACT01ARMADURA-R0"                           # o desenho da Relação, não a Relação
    assert laje["evidencias"][0]["trecho"] == "Relação de Desenhos · ACTIFLO 600 LITROS · 08/21 · ARMADURA DAS LAJES DO FUNDO"
    impermeabilizacao = _parte(act, "impermeabilizacao")                                      # nada no corpus: o buraco aparece
    assert impermeabilizacao["estado"] == "sem evidência" and impermeabilizacao["evidencias"] == []


def test_frase_do_titulo_conjunto_vale_para_360_e_600_e_do_360_so_para_ele(tmp_path):
    s = _montar(tmp_path)["sistemas"]
    escoramento = _parte(s["u1-ACT600"], "escoramento")["evidencias"]
    assert len(escoramento) == 1 and escoramento[0]["doc"] == "Descritivo" and escoramento[0]["pagina"] == 1
    assert "escoramento" in escoramento[0]["trecho"]
    lajes = _parte(s["u1-ACT600"], "laje_fundo")["evidencias"]
    assert [e["trecho"].split(" · ")[-2] for e in lajes] == ["08/21"]                         # a laje do 360 (04/12) não entra no 600


def test_ambiguidade_entre_modulos_e_familias():
    casa = lambda codigo, texto: escopo_obra._casa(codigo, escopo_obra._norm(texto))
    assert casa("ACT600", "ACTIFLO 600 LITROS") and not casa("ACT360", "ACTIFLO 600 LITROS")
    assert casa("ACT600", "MOD_TRATAM_MICRO_AREIA_600Ls") and casa("ACT360", "0001ETAVILACTRATAM360LS")
    assert casa("ACT600", "MICROAREIA 360 e 600 L/s") and casa("ACT360", "MICROAREIA 360 e 600 L/s")
    assert casa("FILTROS", "módulo de filtros novos") and not casa("FILTROS", "EEE_FILTROS_NOVOS")
    assert casa("EEE_FILTROS_NOVOS", "EEE_FILTROS_NOVOS")
    assert casa("DREN_DN400", "TUBO DE CONCRETO DN400 da DRENAGEM") is True
    assert casa("DREN_DN300", "DRENAGEM DN300") and not casa("DREN_DN300", "DRENAGEM DN400")
    assert not casa("DEPOSITO", "depósito de materiais do canteiro") and casa("DEPOSITO", "001-DEP01FORMA-R0")
    assert casa("AAT06", "AAT-06 planta e perfil") and not casa("AAT00", "AAT06PTPER")


def test_link_do_drive_montado_do_id(tmp_path):
    docs = _montar(tmp_path)["documentos"]
    assert docs["Escopo_1etapa"]["link"] == "https://drive.google.com/file/d/ID_ESCOPO/view"
    assert docs["Escopo_1etapa"]["tipo"] == "memorial" and docs["Escopo_1etapa"]["arquivo"] == "Escopo_1etapa.pdf"
    assert docs["008-ACT01ARMADURA-R0"]["link"] == "https://drive.google.com/file/d/ID_ARM8/view"
    assert docs["004-LAYOUT-R5"]["link"] is None                                              # fora da listagem: sem link inventado
    assert (docs["004-LAYOUT-R5"]["tipo"], docs["004-LAYOUT-R5"]["prancha"]) == ("prancha", "f004")
    assert docs["003-FUNDACAO1"]["prancha"] == "fu1" and docs["003-FUNDACAO1"]["titulo"] == "Fundação 1"
    contrato = docs["contrato-T93"]
    assert (contrato["tipo"], contrato["titulo"], contrato["link"]) == ("contrato", "ADUTORA", None)


def test_todo_documento_citado_existe_e_trecho_cabe_em_200(tmp_path):
    saida = _montar(tmp_path)
    for s in saida["sistemas"].values():
        for ev in s["evidencias"] + [e for p in s["decomposicao"] for e in p["evidencias"]]:
            assert ev["doc"] in saida["documentos"] and set(ev) == {"doc", "trecho", "pagina"}
            assert ev["trecho"] is None or len(ev["trecho"]) <= 200
    assert all(set(d) == {"titulo", "arquivo", "tipo", "link", "prancha"} for d in saida["documentos"].values())


def test_trecho_longo_e_cortado_em_torno_do_casamento():
    frase = "Início da frase " + "palavra " * 60 + "ESCORAMENTO no meio " + "outra " * 60 + "fim."
    corte = escopo_obra._trecho(frase, frase.index("ESCORAMENTO"))
    assert len(corte) <= 200 and "ESCORAMENTO" in corte and corte.startswith("…") and corte.endswith("…")
    assert escopo_obra._trecho("curta") == "curta"


def test_sem_preco(tmp_path):
    saida = _montar(tmp_path)
    texto = json.dumps(saida, ensure_ascii=False)
    assert "R$" not in texto and "100,00" not in texto                                         # a frase com R$ nem vira passagem
    assert not re.search(r"pre[cç]o|valor_unit", texto, re.IGNORECASE)
    dados = _dados()
    dados["escopo"]["itens"][0]["preco"] = 12.3
    assert "12.3" not in json.dumps(escopo_obra.montar(dados, _cfg(tmp_path), CORPUS))


def test_cabecalho_e_rodape_repetidos_saem_do_texto():
    paginas = [f"SANEPAR – Informação Pública\nPágina {n} de 4\n\nExecução de escoramento da vala {n}.\n" for n in range(1, 5)]
    frases = [p["frase"] for p in escopo_obra._passagens("doc", paginas)]
    assert frases == [f"Execução de escoramento da vala {n}." for n in range(1, 5)]


def test_clausula_repetida_no_meio_das_paginas_fica():
    clausula = "Deve-se atentar ao escoramento, ao reaterro e à compactação dos solos escavados."
    miolo = "\n".join(f"Linha de miolo {k} com texto suficiente" for k in range(10))
    paginas = [f"Cabeçalho\n{miolo}\n\n{clausula}\n{miolo}\nPágina {n} de 5" for n in range(1, 6)]
    frases = [p["frase"] for p in escopo_obra._passagens("doc", paginas)]
    assert sum(clausula in f for f in frases) == 5 and not any("Cabeçalho" in f or "Página" in f for f in frases)


def test_titulo_da_secao_vale_so_para_os_proximos_paragrafos():
    paragrafos = "\n\n".join(f"Parágrafo número {n} sem nenhum assunto especial." for n in range(12))
    passagens = escopo_obra._passagens("doc", [f"3.2 GUARITA\n\n{paragrafos}"])
    assert escopo_obra._casa("GUARITA", passagens[0]["cab"]) and passagens[-1]["cab"] == ""


def test_sem_construtivos_devolve_none():
    assert escopo_obra.montar({"vetores": []}, {}, {"textos": {}, "relacao": None}) is None


def test_conceito_coerente_com_as_regras_de_unidades():
    civil, sistemas = escopo_obra.CIVIL, escopo_obra.SISTEMAS
    assert all(s["tipologia"] in civil["tipologias"] and s["chaves"] for s in sistemas.values())
    for t in civil["tipologias"].values():
        assert t["fonte"] and t["estado"] in ("confirmado", "premissa", "calibrar") and set(t["partes"]) <= set(civil["partes"])
    for p in civil["partes"].values():
        assert p["estado"] in ("confirmado", "premissa", "calibrar") and p["fonte"] and re.compile(p["palavras"])
        assert set(p["classes_geometria"]) <= set(escopo_obra.construtivos.REGRAS["classes"])
    assert set(civil["escopo"]["convencoes"].values()) == {"dentro", "fora"}
    meta = escopo_obra.metadados()
    assert set(meta["funcoes"]) <= set(dir(escopo_obra)) and meta["premissas"]


@pytest.mark.parametrize("classes,esperado", [(["estaca"], 2), (["bloco"], 0), (["estaca", "trecho"], 2)])
def test_n_geometria_conta_so_as_classes_da_parte(tmp_path, classes, esperado):
    feicoes = _dados()["construtivos"]["geojson"]["features"]
    n, evs = escopo_obra._geometria({"saida": {}, "registro": {}, "pranchas": {}},
                                    [f for f in feicoes if f["properties"]["sistema"] == "u1-ACT600"], classes)
    assert n == esperado and len(evs) == (1 if esperado else 0)
