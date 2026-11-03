import pytest

from camadas import construtivos, geo

EPSG = 31981
E0, N0 = 745000.0, 7182000.0


def _ll(e, n):
    return list(geo.para_lonlat(E0 + e, N0 + n, EPSG))


def _quadrado(e, n, lado):
    pontos = [_ll(e - lado, n - lado), _ll(e + lado, n - lado), _ll(e + lado, n + lado), _ll(e - lado, n + lado)]
    return {"type": "Polygon", "coordinates": [pontos + [pontos[0]]]}


def _prancha(pid, nome, x0, x1):
    return {"id": pid, "nome": nome, "M": [1, 0, E0, 0, 1, N0], "clip_mapa": [x0, 0, x1, 100]}


def _dados(folhas=(("aat06_09", "Adutora AAT06 · planta e perfil 009/019", 0, 200),)):
    """1 estaca (ACT600) dentro de 1 bloco, 1 pilar, 1 cava e 1 rede de 180 m em `folhas`."""
    vala = {"type": "MultiLineString", "coordinates": [[_ll(10, 50), _ll(190, 50)]]}
    return {
        "crs": {"epsg": EPSG},
        "vetores": [
            {"id": "estacas", "geojson": {"features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": _ll(50, 50)},
             "properties": {"id": "ACT600-031", "E": "745050.0", "N": "7182050.0", "diametro_cm": 40.0,
                            "cota_arrasamento": None, "comprimento_m": 12.0, "estrutura": "ACT600",
                            "desenho_origem": "003-FUNDACAO1", "tipo": "estaca"}}]}},
            {"id": "blocos_forma", "geojson": {"features": [
                {"type": "Feature", "geometry": _quadrado(50, 50, 2),
                 "properties": {"tipo": "Bloco (forma)", "rotulo": "P5", "estacas": 1, "face_superior_m": 237.3,
                                "arrasamento_m": 236.6, "ficha": "mod01_forma"}},
                {"type": "Feature", "geometry": _quadrado(50, 50, 0.2),
                 "properties": {"tipo": "Pilar (forma)", "bloco": "P5", "lado_m": 0.41, "ficha": "mod01_forma"}}]}},
            {"id": "escavacao", "geojson": {"features": [
                {"type": "Feature", "geometry": _quadrado(50, 50, 10),
                 "properties": {"id": "C01", "escavacao_m3": 100.0, "fundo_m": [235.0, 236.5], "etapa": "2ª etapa"}},
                {"type": "Feature", "geometry": _quadrado(150, 20, 5), "properties": {"id": "C02", "escavacao_m3": 10.0}}]}},
            {"id": "valas", "geojson": {"features": [{"type": "Feature", "geometry": vala,
             "properties": {"rede": "AAT06", "classe": "pista"}}]}},
        ],
        "pranchas": [_prancha(*f) for f in folhas],
        "fichas": [{"id": "mod01_forma", "identidade": {"arquivo": "001-MOD01FORMA-R1.pdf"}}],
        "valas": {"redes": [{"id": "AAT06", "de_mm": 630, "fonte_de": "contrato: DE 630", "extensao_m": 180.0,
                             "quadro": [{"classe": "pista", "extensao_m": 180.0}]}],
                  "classes": {"pista": {"nome": "Pista (leito carroçável)"}}},
        "escopo": {"fonte": "planilha", "tubo_x_desenho": [{"prancha": "aat06_09", "tabelas": ["93"], "codigo": "309244",
                   "descricao": "TUBO PE DE 630", "contrato_m": 170.0, "desenho_m": 175.0, "diferenca_pct": 2.9}]},
    }


CFG = {"valas": {"redes": [{"id": "AAT06", "pranchas": ["aat06_09"]}]}}


def _por_id(saida):
    return {f["properties"]["id"]: f for f in saida["geojson"]["features"]}


def test_ids_unicos_e_contagem_da_arvore_bate():
    saida = construtivos.montar(_dados(), CFG)
    ids = [f["properties"]["id"] for f in saida["geojson"]["features"]]
    assert len(ids) == len(set(ids)) == 6                 # estaca, bloco, pilar, 2 cavas e 1 trecho
    contagem = {}
    for unidade in saida["arvore"]:
        for s in unidade["sistemas"]:
            for classe, n in s["classes"].items():
                contagem[classe] = contagem.get(classe, 0) + n
                assert sum(1 for f in saida["geojson"]["features"]
                           if f["properties"]["sistema"] == s["id"] and f["properties"]["classe"] == classe) == n
    assert contagem == {"estaca": 1, "bloco": 1, "pilar": 1, "cava": 2, "trecho": 1}
    assert set(saida["classes"]) == set(contagem)


def test_pilar_e_bloco_no_sistema_da_ficha_e_estaca_pela_estrutura():
    por_id = _por_id(construtivos.montar(_dados(), CFG))
    pilar = por_id["u1-FILTROS-pilar-P5"]["properties"]
    assert pilar["rotulo"] == "P5" and pilar["sistema"] == "u1-FILTROS" and pilar["unidade"] == "u1"
    assert dict(pilar["atributos"])["Lado (m)"] == 0.41 and dict(pilar["atributos"])["Bloco"] == "P5"
    assert pilar["fonte"] == "forma 001-MOD01FORMA-R1 (camadas.prancha)"
    bloco = por_id["u1-FILTROS-bloco-P5"]["properties"]
    assert dict(bloco["atributos"])["Estacas por sistema"] == "ACT600 1"
    assert "Conferir" in dict(bloco["atributos"])          # a estaca dentro é de outro sistema: não reclassifica, avisa
    estaca = por_id["u1-ACT600-estaca-ACT600-031"]["properties"]
    assert estaca["sistema"] == "u1-ACT600" and dict(estaca["atributos"])["Bloco"] == "P5"


def test_cava_pela_maioria_das_estacas_ou_no_sistema_geral():
    por_id = _por_id(construtivos.montar(_dados(), CFG))
    assert por_id["u1-ACT600-cava-C01"]["properties"]["etapa"] == "2ª etapa"
    assert dict(por_id["u1-ACT600-cava-C01"]["properties"]["atributos"])["Fundo (cota, m)"] == "235.00 a 236.50"
    vazia = por_id["u1-ETA-cava-C02"]["properties"]
    assert dict(vazia["atributos"])["Sistema pelo critério"] == "sem estaca dentro da cava"


def test_propriedades_no_contrato():
    saida = construtivos.montar(_dados(), CFG)
    assert set(saida) == {"fonte", "classes", "arvore", "geojson"}
    for f in saida["geojson"]["features"]:
        p = f["properties"]
        assert set(p) - {"origem_etapa"} == {"id", "rotulo", "classe", "unidade", "sistema", "etapa", "atributos", "fonte", "doc"}
        assert ("origem_etapa" in p) == (p["classe"] == "cava")      # só a cava grava a etapa estruturada da conciliação
        assert p["classe"] in saida["classes"] and p["id"].startswith(p["sistema"])
        assert all(isinstance(par, list) and len(par) == 2 and par[1] is not None for par in p["atributos"])
    assert [u["id"] for u in saida["arvore"]] == ["u1", "u2"]
    assert saida["arvore"][1]["obra"] == "linear"
    assert {c["geometria"] for c in saida["classes"].values()} == {"ponto", "poligono", "linha"}


def test_doc_de_origem_de_cada_elemento():
    dados = _dados()
    dados["pranchas"][0]["pdf"] = "009-SAA-AAT06PTPER-R1.pdf"
    dados["pranchas"].append({"id": "es1", "nome": "Escavação 1", "pdf": "006-SAA-ETA01ESCAVACAO1-R2.pdf",
                              "M": [1, 0, E0, 0, 1, N0], "clip_mapa": [0, 0, 100, 100]})
    dados["vetores"][0]["geojson"]["features"][0]["properties"]["desenho_origem"] = "003-FUNDACAO1+005-FUNDACAO3"
    por_id = _por_id(construtivos.montar(dados, CFG))
    doc = {i: f["properties"]["doc"] for i, f in por_id.items()}
    assert doc["u1-ACT600-estaca-ACT600-031"] == "003-FUNDACAO1"                   # estaca em dois desenhos: o primeiro
    assert doc["u1-FILTROS-bloco-P5"] == doc["u1-FILTROS-pilar-P5"] == "001-MOD01FORMA-R1"      # a forma da ficha
    assert doc["u2-AAT06-trecho-aat06_09"] == "009-SAA-AAT06PTPER-R1"
    assert doc["u1-ACT600-cava-C01"] == "006-SAA-ETA01ESCAVACAO1-R2"              # a folha de escavação que contém a cava
    assert doc["u1-ETA-cava-C02"] == "006-SAA-ETA01ESCAVACAO1-R2"                  # fora das janelas: a primeira folha de escavação


def test_trecho_de_rede_com_contrato_e_desenho():
    p = _por_id(construtivos.montar(_dados(), CFG))["u2-AAT06-trecho-aat06_09"]["properties"]
    a = dict(p["atributos"])
    assert p["rotulo"] == "AAT06" and p["sistema"] == "u2-AAT06"            # rede de uma folha só leva o nome da rede
    assert a["Diâmetro (mm)"] == 630 and a["Extensão estimada (m)"] == pytest.approx(180.0, abs=0.1)
    assert a["Pista (leito carroçável) (m)"] == pytest.approx(180.0, abs=0.1)
    assert a["Tubo no contrato (m)"] == 170.0 and a["Tubo no desenho (m)"] == 175.0 and a["Tabela(s) do contrato"] == "93"


def test_extensao_reparte_entre_folhas_sem_perder_metro():
    folhas = (("aat06_09", "Adutora AAT06 · planta e perfil 009/019", 0, 120), ("aat06_10", "Adutora AAT06 · planta e perfil 010/019", 80, 200))
    cfg = {"valas": {"redes": [{"id": "AAT06", "pranchas": ["aat06_09", "aat06_10"]}]}}
    trechos = [f for f in construtivos.montar(_dados(folhas), cfg)["geojson"]["features"] if f["properties"]["classe"] == "trecho"]
    assert [t["properties"]["rotulo"] for t in trechos] == ["AAT06 · folha 09", "AAT06 · folha 10"]
    extensoes = [dict(t["properties"]["atributos"])["Extensão estimada (m)"] for t in trechos]
    assert sum(extensoes) == pytest.approx(180.0, abs=0.2)
    assert extensoes[0] == pytest.approx(extensoes[1], abs=1.0)           # a sobreposição fica com a folha de centro mais próximo


def test_sem_dado_devolve_none_e_sigla_desconhecida_vira_premissa():
    assert construtivos.montar({"vetores": []}, {}) is None
    dados = _dados()
    dados["vetores"][0]["geojson"]["features"][0]["properties"]["estrutura"] = "XYZ"
    saida = construtivos.montar(dados, CFG)
    sistema = next(s for u in saida["arvore"] for s in u["sistemas"] if s["id"] == "u1-XYZ")
    assert sistema["nome"] == "XYZ" and sistema["estado"] == "premissa"


def test_conceito_cobre_unidades_estados_e_fontes():
    regras = construtivos.REGRAS
    assert all(s["unidade"] in regras["unidades"] and s["estado"] in ("confirmado", "premissa", "calibrar") and s["fonte"]
               for s in regras["sistemas"].values())
    assert regras["sistema_geral"] in regras["sistemas"] and regras["sistemas"]["EEE_FILTROS_NOVOS"]["estado"] == "premissa"
    assert all(f["sistema"] in regras["sistemas"] for f in regras["fichas"].values())
    assert regras["metadata"]["fonte"] and all(c["geometria"] in ("ponto", "poligono", "linha") for c in regras["classes"].values())
    meta = construtivos.metadados()
    assert set(meta["funcoes"]) <= set(dir(construtivos)) and meta["premissas"]


def test_unidade_da_relacao_sem_geometria_entra_na_arvore_com_classes_vazias():
    dados = _dados()
    sem = {s["id"] for u in construtivos.montar(dados, CFG)["arvore"] for s in u["sistemas"]}
    assert "u1-CAMARA_CONTATO" not in sem                                             # sem a Relação no inventário, sistema vazio fica de fora
    dados["inventario"] = {"itens": [{"arquivo": "Relação de Desenhos.pdf", "pasta_drive": "UNIDADE 01/QUANTITATIVOS"}]}
    saida = construtivos.montar(dados, CFG)
    sistemas = {s["id"]: s for u in saida["arvore"] for s in u["sistemas"]}
    for sid in ("u1-CAMARA_CONTATO", "u1-CANAL_AT", "u1-EEE_LODO", "u1-RECALD_RECALF", "u1-BLOCOS_APOIO", "u1-CX_SAIDA", "u1-CX_CHEGADA"):
        assert sistemas[sid]["classes"] == {} and sistemas[sid]["estado"] == "confirmado"
    assert sistemas["u1-CX_SAIDA"]["nome"] == "Caixas de saída de água tratada"
    assert sistemas["u1-CX_CHEGADA"]["nome"] == "Caixas de chegada de água bruta"
    assert "u1-TORRE_ELEV" not in sistemas and len(saida["geojson"]["features"]) == 6        # contrato intacto: só entra o que não tem feição
