"""Painel da aba EAP: soma por nó, formatação pt-BR, ordem dos fatos e contrato JSON (`camadas.eap_painel`)."""

import json
from pathlib import Path

from test_construtivos import CFG, EPSG, _dados
from test_evidencias import PROJETO

from camadas import construtivos, eap, eap_painel, evidencias


def sinteticos(com_conflito: bool = False) -> tuple[dict, dict]:
    """(eap_codificada, evidencias) como `eap.montar` e `evidencias.etapa` os entregam, com os dados sintéticos.
    Com `com_conflito`: 300 estacas medidas nas pranchas × 250 no memorial."""
    dados = _dados()
    if com_conflito:
        estacas = dados["vetores"][0]["geojson"]["features"]
        estacas += [
            {
                **estacas[0],
                "properties": {**estacas[0]["properties"], "id": f"ACT600-{i:03d}"},
            }
            for i in range(100, 399)
        ]
    dados["construtivos"] = construtivos.montar(dados, CFG)
    codificada = eap.montar(dados, CFG)
    paginas = (
        ["Serão executadas 250 estacas, conforme sondagem SP-04."]
        if com_conflito
        else []
    )
    docs = [{**PROJETO, "paginas": paginas}] if com_conflito else []
    evs = evidencias.loop(docs, construtivos=dados["construtivos"], epsg=EPSG)
    registros = {
        "fatos": evidencias.consolidar(evs),
        "associados": evidencias.associados_x_edital(evs),
    }
    return codificada, {k: evidencias._registros(df) for k, df in registros.items()}


def _eap(quantidades: list[dict]) -> dict:
    nos = [
        {"codigo": c, "numero": n, "nivel": nv, "nome": c, "pai": p}
        for c, n, nv, p in [
            ("U1", "1", "unidade", None),
            ("U1.A", "1.1", "sistema", "U1"),
            ("U1.B", "1.2", "sistema", "U1"),
        ]
    ]
    return {"nos": nos, "quantidades": quantidades}


def _q(codigo, grandeza, unidade, quantidade, ids):
    return {
        "codigo": codigo,
        "grandeza": grandeza,
        "unidade": unidade,
        "quantidade": quantidade,
        "n_elementos": len(ids),
        "sem_valor": 0,
        "evidencias": ids,
    }


def test_none_quando_nao_ha_nada():
    assert eap_painel.montar(None, None) is None


def test_so_um_dos_dois_ainda_monta():
    codificada, evid = sinteticos()
    so_eap = eap_painel.montar(codificada, None)
    assert so_eap["arvore"] and so_eap["fatos"] == [] and so_eap["resumo"]["fatos"] == 0
    so_fatos = eap_painel.montar(None, evid)
    assert so_fatos["arvore"] == [] and so_fatos["fatos"]


def test_texto_em_pt_br_com_virgula_e_unidade():
    codificada, evid = sinteticos()
    painel = eap_painel.montar(codificada, evid)
    textos = [t for n in painel["arvore"] for t in n["quantidades_txt"]]
    assert "1 un · GEO.FUN.BLO" in textos  # contagem sem casas
    assert (
        "16,00 m² (área em planta) · GEO.FUN.BLO" in textos
    )  # vírgula decimal, grandeza e tipo de item
    assert not any("." in t.split(" ")[0] for t in textos)
    assert {"12,00 m³", "1,51 m³"} <= {
        a["quantidade_txt"] + " " + a["unidade_medida"] for a in painel["associados"]
    }
    assert eap_painel.br(1234.5) == "1.234,50"
    item = next(
        n for n in painel["arvore"] if n["nivel"] == "item" and n["quantidades_txt"]
    )
    assert not any(
        "·" in t for t in item["quantidades_txt"]
    )  # no item o código do item é o próprio nó


def test_soma_por_no_sem_misturar_unidades_nem_tipos_de_item():
    quantidades = [
        _q("U1.A.GEO.FUN.BLO", "quantidade", "un", 2.0, ["b1", "b2"]),
        _q(
            "U1.B.GEO.FUN.BLO", "quantidade", "un", 10.0, ["b3"]
        ),  # mesmo item em outro sistema: soma na U1
        _q(
            "U1.A.GEO.FUN.BLO", "volume", "m³", 100.5, ["b1", "b2"]
        ),  # outra unidade de medida: não soma com un
        _q(
            "U1.A.CIV.EST.PIL", "quantidade", "un", 3.0, ["p1"]
        ),  # un de pilar não soma com un de bloco
        _q("U1.B.GEO.MOV.ESC", "volume", "m³", 1245.5, ["c1"]),
    ]
    arvore = {n["codigo"]: n for n in eap_painel.arvore(_eap(quantidades))}
    u1 = arvore["U1"]["quantidades_txt"]
    assert "12 un · GEO.FUN.BLO" in u1 and "3 un · CIV.EST.PIL" in u1
    assert (
        "100,50 m³ (volume) · GEO.FUN.BLO" in u1
        and "1.245,50 m³ (volume) · GEO.MOV.ESC" in u1
    )
    assert len(u1) == 4
    assert sorted(arvore["U1.A"]["quantidades_txt"]) == sorted(
        ["2 un · GEO.FUN.BLO", "100,50 m³ (volume) · GEO.FUN.BLO", "3 un · CIV.EST.PIL"]
    )


def test_elementos_por_prefixo_do_codigo():
    quantidades = [
        _q("U1.A.GEO.FUN.BLO", "quantidade", "un", 2.0, ["b1", "b2"]),
        _q(
            "U1.A.GEO.FUN.BLO", "volume", "m³", 8.0, ["b1", "b2"]
        ),  # os mesmos ids em outra grandeza
        _q("U1.B.GEO.FUN.BLO", "quantidade", "un", 1.0, ["b3"]),
    ]
    arvore = {n["codigo"]: n for n in eap_painel.arvore(_eap(quantidades))}
    assert (
        arvore["U1"]["elementos"] == ["b1", "b2", "b3"]
        and arvore["U1"]["n_elementos"] == 3
    )
    assert arvore["U1.A"]["elementos"] == ["b1", "b2"] and arvore["U1.B"][
        "elementos"
    ] == ["b3"]
    assert _eap([])["nos"] and all(
        n["quantidades_txt"] == [] and n["elementos"] == []
        for n in eap_painel.arvore(_eap([]))
    )


def test_prefixo_respeita_o_limite_do_segmento():
    quantidades = [_q("U10.A.GEO.FUN.BLO", "quantidade", "un", 5.0, ["x"])]
    assert (
        eap_painel.arvore(_eap(quantidades))[0]["elementos"] == []
    )  # nó U1 não contém U10


def test_nos_da_eap_real_trazem_os_ids_dos_elementos():
    codificada, _ = sinteticos()
    arvore = {n["codigo"]: n for n in eap_painel.arvore(codificada)}
    assert [n["codigo"] for n in eap_painel.arvore(codificada)] == [
        n["codigo"] for n in codificada["nos"]
    ]
    assert arvore["U1.FILTROS.GEO.FUN.BLO"]["elementos"] == ["u1-FILTROS-bloco-P5"]
    assert "u1-FILTROS-bloco-P5" in arvore["U1"]["elementos"]


def test_fatos_com_conflito_primeiro_e_afirmacoes_formatadas():
    codificada, evid = sinteticos(com_conflito=True)
    painel = eap_painel.montar(codificada, evid)
    status = [f["status"] for f in painel["fatos"]]
    assert status[0] == "conflito"
    ordem = eap_painel.ORDEM_STATUS
    assert [ordem.index(s) for s in status] == sorted(ordem.index(s) for s in status)
    conflito = painel["fatos"][0]
    assert conflito["codigo"] == "U1.*.GEO.FUN.EST" and conflito["valor_txt"] == "—"
    assert conflito["servico_txt"] == "—" and conflito["diferenca_txt"] == "16,7 %"
    afirmado = {a["documento"]: a["valor_txt"] for a in conflito["afirmacoes"]}
    assert afirmado == {
        "memorial_fundacoes.pdf": "250 un",
        "modelo:construtivos": "300 un",
    }
    assert all(
        len(a["trecho"]) <= eap_painel.LIMITE_TRECHO for a in conflito["afirmacoes"]
    )
    assert painel["resumo"]["por_status"][0] == {
        "status": "conflito",
        "n": status.count("conflito"),
    }
    assert (
        sum(s["n"] for s in painel["resumo"]["por_status"])
        == painel["resumo"]["fatos"]
        == len(status)
    )


def test_ordem_dos_status_e_nome_do_servico_e_corte_do_trecho():
    def fato(status, servico="escavacao", trecho="x", valor=1.0):
        return {
            "codigo": "U1.A.GEO.MOV.VAL",
            "servico": servico,
            "unidade": "m³",
            "status": status,
            "valor": valor,
            "forca": 1,
            "n_documentos": 1,
            "diferenca_pct": 0.0,
            "mencoes": [],
            "decisoes": [],
            "afirmacoes": [
                {
                    "documento": "d.pdf",
                    "tipo": "edital",
                    "valor": valor,
                    "trechos": [trecho, "outro"],
                }
            ],
        }

    lista = [
        fato(s)
        for s in ("decidido", "convergente", "fonte única", "só menção", "conflito")
    ]
    lista[0] = fato("decidido", "", "y" * 500, 1234.5)
    fatos = eap_painel.fatos(lista)
    assert [f["status"] for f in fatos] == [
        "conflito",
        "só menção",
        "fonte única",
        "convergente",
        "decidido",
    ]
    assert fatos[0]["servico_txt"] == "Escavação" and fatos[-1]["servico_txt"] == "—"
    assert fatos[-1]["valor_txt"] == "1.234,50 m³" and fatos[-1]["diferenca_txt"] == ""
    trecho = fatos[-1]["afirmacoes"][0]["trecho"]
    assert len(trecho) == eap_painel.LIMITE_TRECHO and trecho.endswith("…")


def test_associados_formatados_e_contagem_de_nao_citados():
    codificada, evid = sinteticos()
    painel = eap_painel.montar(codificada, evid)
    assert painel["associados"] and painel["resumo"]["associados"] == len(
        painel["associados"]
    )
    nao = [a for a in painel["associados"] if a["destaque"]]
    assert nao and all(a["situacao"].startswith("não citado no edital") for a in nao)
    assert painel["resumo"]["nao_citados"] == len(nao)
    assert all(
        a["servico"] != "" and isinstance(a["quantidade_txt"], str)
        for a in painel["associados"]
    )


def test_serializavel_em_json():
    for com_conflito in (False, True):
        painel = eap_painel.montar(*sinteticos(com_conflito))
        assert json.loads(json.dumps(painel, allow_nan=False)) == painel


def test_chaves_eap_e_eap_codificada_convivem_em_dados():
    """A aba EAP lê `dados["eap"]` (gavetas) e o painel nasce de `dados["eap_codificada"]`: uma não apaga a outra."""
    codificada, evid = sinteticos()
    gavetas = {"nos": [{"eap": "OL.01"}], "pendencias": [], "resumo": {"servicos": 1}}
    dados = {"eap": gavetas, "eap_codificada": codificada, "evidencias": evid}
    dados["eap_painel"] = eap_painel.montar(
        dados.get("eap_codificada"), dados.get("evidencias")
    )
    assert dados["eap"] is gavetas and set(dados["eap"]) == {
        "nos",
        "pendencias",
        "resumo",
    }
    assert {"fonte", "nos", "quantidades", "pranchas", "lacunas", "sem_item"} <= set(
        dados["eap_codificada"]
    )
    assert set(dados["eap_painel"]) == {"arvore", "fatos", "associados", "resumo"}


def test_metadados():
    meta = eap_painel.metadados()
    assert meta["modulo"] == "eap_painel" and "montar" in meta["funcoes"]


def test_build_nao_sobrescreve_a_eap_das_gavetas():
    """Guarda da colisão de chave: a EAP codificada tem chave própria em `obra.py`."""
    fonte = (Path(__file__).resolve().parent.parent / "camadas" / "obra.py").read_text(
        encoding="utf-8"
    )
    assert (
        'dados["eap"] = eap.montar' not in fonte
        and 'dados["eap_codificada"] = eap.montar' in fonte
    )
    assert fonte.count('dados["eap"] =') == 1
