"""Painel da aba EAP: soma por nó, formatação pt-BR, ordem dos fatos e contrato JSON (`camadas.eap_painel`)."""

import json

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


def test_aba_projeto_mantem_eap_das_gavetas_e_gera_o_painel(monkeypatch, tmp_path):
    """Comportamento do build: gavetas em `dados["eap_gavetas"]`, codificada em `dados["eap"]` e o painel montado dela."""
    from camadas import (
        escopo_obra,
        extrair_gavetas,
        obra,
        obras_lineares,
    )

    codificada, evid = sinteticos()
    gavetas = {"nos": [{"eap": "OL.01"}], "pendencias": [], "resumo": {"servicos": 1}}
    monkeypatch.setattr(obras_lineares, "etapa", lambda *a, **k: None)
    monkeypatch.setattr(extrair_gavetas, "etapa", lambda *a, **k: {"eap_html": gavetas})
    monkeypatch.setattr(
        construtivos, "montar", lambda *a, **k: {"geojson": {"features": []}}
    )
    monkeypatch.setattr(escopo_obra, "montar", lambda *a, **k: None)
    monkeypatch.setattr(eap, "montar", lambda *a, **k: codificada)
    monkeypatch.setattr(evidencias, "etapa", lambda *a, **k: evid)
    dados = {"sondagens": []}
    obra._aba_projeto(dados, {}, tmp_path, None, None, {})
    assert dados["eap_gavetas"] is gavetas  # não foi sobrescrita pela codificada
    assert set(dados["eap_painel"]) == {"arvore", "fatos", "associados", "resumo"}
    assert dados["eap_painel"] == eap_painel.montar(codificada, evid)
    assert dados["eap"] is codificada and "eap_codificada" not in dados


def test_decisao_vira_texto_pronto():
    fato = {
        "codigo": "U1.*.GEO.FUN.EST",
        "servico": "",
        "unidade": "un",
        "status": "decidido",
        "valor": 250.0,
        "forca": 1,
        "n_documentos": 2,
        "diferenca_pct": 0.0,
        "afirmacoes": [],
        "mencoes": [],
        "decisoes": [
            {
                "valor": 250.0,
                "autor": "Caio",
                "justificativa": "revisão R2 suprimiu 50 estacas",
            }
        ],
    }
    assert eap_painel.fatos([fato])[0]["decisoes_txt"] == [
        "250 un — Caio: revisão R2 suprimiu 50 estacas"
    ]


def test_metadados():
    meta = eap_painel.metadados()
    assert meta["modulo"] == "eap_painel" and "montar" in meta["funcoes"]


def _fato_bruto(codigo: str, status: str, unidade: str = "un") -> dict:
    return {"codigo": codigo, "status": status, "unidade": unidade}


def _eap_de(codigos_itens: list[str]) -> dict:
    """EAP mínima: um nó por prefixo de cada código de item e uma quantidade por item."""
    nos: dict[str, dict] = {}
    for codigo in codigos_itens:
        partes = codigo.split(".")
        for k in range(1, len(partes) + 1):
            c = ".".join(partes[:k])
            nos.setdefault(
                c,
                {
                    "codigo": c,
                    "numero": c,
                    "nivel": "item" if k == len(partes) else "no",
                    "nome": c,
                    "pai": ".".join(partes[: k - 1]) or None,
                },
            )
    return {
        "nos": list(nos.values()),
        "quantidades": [_q(c, "quantidade", "un", 1.0, [c]) for c in codigos_itens],
    }


def _status(fatos: list[dict], itens: list[str] | None = None) -> dict:
    """Nós por código; por padrão há estacas em U1.A e U1.B."""
    itens = itens or ["U1.A.GEO.FUN.EST", "U1.B.GEO.FUN.EST"]
    return {n["codigo"]: n for n in eap_painel.arvore(_eap_de(itens), fatos)}


def test_status_do_no_conflito_sobe_para_os_ancestrais():
    nos = _status(
        [
            _fato_bruto("U1.A.GEO.FUN.EST", "conflito"),
            _fato_bruto("U1.B.GEO.FUN.EST", "convergente"),
        ]
    )
    assert nos["U1"]["status_no"] == "conflito"  # ancestral herda o conflito
    assert nos["U1.A"]["status_no"] == "conflito"
    assert nos["U1.B"]["status_no"] == "convergente"
    assert (nos["U1"]["n_fatos"], nos["U1"]["n_conflitos"]) == (2, 1)
    assert (nos["U1.A"]["n_fatos"], nos["U1.A"]["n_conflitos"]) == (1, 1)
    assert (nos["U1.B"]["n_fatos"], nos["U1.B"]["n_conflitos"]) == (1, 0)
    assert nos["U1"]["selo_title"] == "2 fatos · 1 em conflito"
    assert nos["U1.B"]["selo_title"] == "1 fato · 0 em conflito"
    assert nos["U1.A"]["rotulo_vista"] == "Vista: U1.A · U1.A (1 elemento)"


def test_fato_com_asterisco_vale_para_os_sistemas_que_tem_o_item():
    nos = _status([_fato_bruto("U1.*.GEO.FUN.EST", "fonte única")])
    assert {nos[c]["status_no"] for c in ("U1", "U1.A", "U1.B")} == {"fonte única"}
    assert all(nos[c]["n_fatos"] == 1 for c in ("U1", "U1.A", "U1.B"))
    assert eap_painel._fato_cobre_no("U1.*.GEO.FUN.EST", "U1.A.GEO.FUN")
    assert not eap_painel._fato_cobre_no("U1.*.GEO.FUN.EST", "U1.A.CIV")
    assert not eap_painel._fato_cobre_no("U1.*.GEO.FUN.EST", "U2.A")
    assert not eap_painel._fato_cobre_no("U1.A", "U1.A.GEO")


def test_asterisco_nao_contamina_sistema_sem_o_item():
    nos = _status(
        [_fato_bruto("U1.*.GEO.FUN.EST", "conflito")],
        itens=["U1.A.GEO.FUN.EST", "U1.B.CIV.EST.PIL"],  # U1.B não tem estaca
    )
    assert nos["U1.A"]["status_no"] == "conflito"
    assert nos["U1"]["status_no"] == "conflito"
    assert nos["U1.B"]["status_no"] == "sem evidência"
    assert nos["U1.B"]["n_fatos"] == 0 and nos["U1.B"]["n_conflitos"] == 0
    assert nos["U1.B.CIV"]["status_no"] == "sem evidência"
    # fato sem `*` segue a regra de prefixo mesmo sem quantidade sob o nó
    sem_curinga = _status(
        [_fato_bruto("U1.B.GEO.FUN.EST", "conflito")], itens=["U1.B.CIV.EST.PIL"]
    )
    assert sem_curinga["U1.B"]["status_no"] == "conflito"


def test_asterisco_no_meio_e_fato_de_nivel_pacote_em_no_intermediario():
    itens = ["U1.A.GEO.FUN.EST", "U1.A.GEO.FUN.BLO", "U1.A.CIV.EST.PIL"]
    nos = _status(
        [
            _fato_bruto("U1.A.*.FUN.EST", "convergente"),  # `*` no meio
            _fato_bruto("U1.A.GEO", "conflito"),  # nível pacote: cobre o pacote e acima
        ],
        itens=itens,
    )
    assert nos["U1.A.GEO"]["status_no"] == "conflito"
    assert (
        nos["U1.A"]["status_no"] == "conflito" and nos["U1"]["status_no"] == "conflito"
    )
    assert (
        nos["U1.A.GEO.FUN"]["status_no"] == "convergente"
    )  # o fato de pacote não cobre o filho
    assert nos["U1.A.GEO.FUN.EST"]["status_no"] == "convergente"
    assert nos["U1.A.GEO.FUN.BLO"]["status_no"] == "sem evidência"
    assert nos["U1.A.CIV"]["status_no"] == "sem evidência"
    assert nos["U1.A.GEO.FUN"]["n_fatos"] == 1
    assert nos["U1.A"]["n_fatos"] == 2


def test_mesmo_codigo_com_unidades_diferentes_conta_dois_fatos():
    nos = _status(
        [
            _fato_bruto("U1.A.GEO.FUN.EST", "convergente", "un"),
            _fato_bruto("U1.A.GEO.FUN.EST", "conflito", "m"),
        ]
    )
    assert nos["U1.A"]["n_fatos"] == 2 and nos["U1.A"]["n_conflitos"] == 1
    assert nos["U1.A"]["status_no"] == "conflito"
    assert nos["U1.B"]["status_no"] == "sem evidência"


def test_no_sem_fato_e_sem_evidencia_e_so_convergentes_e_convergente():
    nos = _status(
        [
            _fato_bruto("U1.A.GEO.FUN.EST", "convergente"),
            _fato_bruto("U1.A.CIV.EST.PIL", "decidido"),
        ],
        itens=["U1.A.GEO.FUN.EST", "U1.A.CIV.EST.PIL", "U1.B.GEO.FUN.EST"],
    )
    assert nos["U1.B"]["status_no"] == "sem evidência"
    assert (nos["U1.B"]["n_fatos"], nos["U1.B"]["n_conflitos"]) == (0, 0)
    assert nos["U1.A"]["status_no"] == "convergente" and nos["U1.A"]["n_fatos"] == 2
    assert nos["U1"]["status_no"] == "convergente"
    assert _status([])["U1"]["status_no"] == "sem evidência"


def test_fonte_unica_so_mencao_e_status_desconhecido_rebaixam_convergente():
    base = _fato_bruto("U1.A.GEO.FUN.EST", "convergente")
    for status in (
        "fonte única",
        "só menção",
        "inventado",
    ):  # desconhecido cai em "fonte única", por cautela
        nos = _status([base, _fato_bruto("U1.A.GEO.FUN.EST", status)])
        assert nos["U1.A"]["status_no"] == "fonte única", status
        assert nos["U1.B"]["status_no"] == "sem evidência"
    assert (
        _status([_fato_bruto("U1.A.X.Y.Z", "fonte única")], itens=["U1.A.X.Y.Z"])["U1"][
            "status_no"
        ]
        == "fonte única"
    )
    nos = _status(
        [_fato_bruto("U1.A.X.Y.Z", "só menção"), _fato_bruto("U1.A.X.Y.W", "conflito")],
        itens=["U1.A.X.Y.Z", "U1.A.X.Y.W"],
    )
    assert nos["U1.A"]["status_no"] == "conflito"


def test_montar_passa_os_fatos_a_arvore():
    """Status exatos nos dados sintéticos: o `*` em conflito (U1.*.GEO.FUN.EST) só atinge quem tem estaca (ACT600)."""
    codificada, evid = sinteticos(com_conflito=True)
    painel = eap_painel.montar(codificada, evid)
    nos = {n["codigo"]: n for n in painel["arvore"]}
    esperado = {
        "U1": ("conflito", 17, 1),
        "U1.ACT600": ("conflito", 7, 1),
        "U1.ACT600.GEO.FUN.EST": ("conflito", 6, 1),
        "U1.ACT600.GEO.MOV": ("fonte única", 1, 0),
        "U1.ACT600.GEO.MOV.REA": ("sem evidência", 0, 0),
        "U1.FILTROS": ("fonte única", 9, 0),  # sem estacas: o conflito do `*` não chega
        "U1.ETA": ("fonte única", 1, 0),
        "U2": ("conflito", 12, 7),
        "U2.AAT06.HID": ("fonte única", 2, 0),
    }
    for codigo, (status, n_fatos, n_conflitos) in esperado.items():
        no = nos[codigo]
        assert (no["status_no"], no["n_fatos"], no["n_conflitos"]) == (
            status,
            n_fatos,
            n_conflitos,
        ), codigo
    assert nos["U1"]["selo_title"] == "17 fatos · 1 em conflito"
    sem_fatos = eap_painel.montar(codificada, None)
    assert {n["status_no"] for n in sem_fatos["arvore"]} == {"sem evidência"}


def test_subgrupos_do_codigo_por_disciplina_pacote_e_item():
    # disciplina: todo subgrupo com algum pacote GEO.*, em ordem alfabética
    geo = ["Adutoras", "Geotecnia e fundação", "Terraplenagem"]
    assert eap_painel.subgrupos_do_codigo("U1.A.GEO") == geo
    # pacote e item: só quem contém o pacote exato
    assert eap_painel.subgrupos_do_codigo("U1.A.GEO.FUN") == ["Geotecnia e fundação"]
    assert eap_painel.subgrupos_do_codigo("U1.A.GEO.FUN.EST") == [
        "Geotecnia e fundação"
    ]
    assert eap_painel.subgrupos_do_codigo("U1.A.GEO.MOV") == geo
    assert eap_painel.subgrupos_do_codigo("U1.A.HID.TUB") == [
        "Adutoras",
        "Drenagem",
        "Processo",
        "Tubulações e conexões",
    ]


def test_subgrupos_do_codigo_acima_da_disciplina_e_vazio():
    assert eap_painel.subgrupos_do_codigo("U1") == []
    assert eap_painel.subgrupos_do_codigo("U1.A") == []


def test_subgrupos_do_codigo_pacote_sem_prancha(monkeypatch):
    sem_geo_mov = {
        k: [p for p in v if p != "GEO.MOV"] for k, v in eap.REGRAS["pranchas"].items()
    }
    monkeypatch.setitem(eap.REGRAS, "pranchas", sem_geo_mov)
    assert eap_painel.subgrupos_do_codigo("U1.A.GEO.MOV.REA") == []


def test_montar_traz_subgrupos_mapa_e_texto_das_pranchas():
    codificada, evid = sinteticos()
    nos = {n["codigo"]: n for n in eap_painel.montar(codificada, evid)["arvore"]}
    assert nos["U1"]["subgrupos_mapa"] == [] and nos["U1"]["pranchas_txt"] == ""
    fun = nos["U1.FILTROS.GEO.FUN.BLO"]
    assert fun["subgrupos_mapa"] == ["Geotecnia e fundação"]
    assert fun["pranchas_txt"] == "Pranchas: Geotecnia e fundação"
    assert (
        nos["U1.ACT600.GEO.MOV"]["pranchas_txt"]
        == "Pranchas: Adutoras, Geotecnia e fundação, Terraplenagem"
    )
