"""Conciliação das duas EAP sem "confere" circular: origem das duas trilhas e terceira coluna (documento independente)."""

import pytest

from camadas import eap, eap_html
from camadas import gavetas as gv


def _serv(
    saida="escavacao_cava_m3",
    valor=100.0,
    codigo="U1.ETA.GEO.MOV.ESC",
    origem=("etapa:escavacao",),
    objeto="CAVAS",
    chave=None,
):
    sid = ":".join(x for x in (objeto, "cavas", saida, chave) if x)
    return {
        "servico_id": sid,
        "objeto_id": objeto,
        "regra": "cavas",
        "saida": saida,
        "valor": valor,
        "unidade": gv.EAP["saidas"][saida]["unidade"],
        "fatos": [],
        "codigo_eap": codigo,
        "origem": None if origem is None else list(origem),
    }


def _quant(codigo="U1.ETA.GEO.MOV.ESC", valor=100.0, unidade="m³"):
    return {
        "codigo": codigo,
        "grandeza": "volume",
        "unidade": unidade,
        "quantidade": valor,
    }


def _linha(servicos, quantidades, **kw):
    return gv.conciliar_eap(servicos, quantidades, **kw)[0]


# --- origem das duas trilhas -------------------------------------------------------------------------------------------


def test_circular_mesma_origem_nao_e_confere_simples():
    linha = _linha(
        [_serv()],
        [_quant()],
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["etapa:escavacao"]},
    )
    assert linha["situacao"] == gv.SITUACAO_MESMA_ORIGEM == "confere (mesma origem)"
    assert linha["origem"] == "mesma" and linha["diferenca"] == 0
    assert (
        "não é conferência independente" in linha["motivo"]
        and "etapa:escavacao" in linha["motivo"]
    )


def test_origem_parcialmente_compartilhada_ainda_e_mesma_origem():
    """Uma trilha com a planilha e a ortofoto, a outra só com a ortofoto: o insumo repetido não foi conferido."""
    linha = _linha(
        [_serv(origem=("arquivo:ortofoto_mds", "arquivo:planilha"))],
        [_quant()],
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["arquivo:ortofoto_mds"]},
    )
    assert linha["situacao"] == gv.SITUACAO_MESMA_ORIGEM


def test_origens_diferentes_confere_independente():
    linha = _linha(
        [_serv(origem=("arquivo:planilha",))],
        [_quant()],
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["arquivo:prancha_01"]},
    )
    assert (
        linha["situacao"] == "confere"
        and linha["origem"] == "independente"
        and linha["motivo"] == ""
    )


def test_difere_com_mesma_origem_continua_difere_e_destaca_o_motivo():
    linha = _linha(
        [_serv(valor=110.0)],
        [_quant()],
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["etapa:escavacao"]},
    )
    assert (
        linha["situacao"] == "difere"
        and linha["origem"] == "mesma"
        and linha["diferenca"] == pytest.approx(10.0)
    )
    assert "erro de cálculo" in linha["motivo"] and "mais grave" in linha["motivo"]


def test_origem_indeterminada_nao_inventa_nada():
    sem_gavetas = _linha(
        [_serv(origem=None)],
        [_quant()],
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["etapa:x"]},
    )
    sem_codificada = _linha(
        [_serv()], [_quant()], origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): None}
    )
    sem_mapa = _linha([_serv()], [_quant()])
    for linha in (sem_gavetas, sem_codificada, sem_mapa):
        assert (
            linha["situacao"] == "confere"
            and linha["origem"] == "indeterminada"
            and linha["motivo"] == ""
        )
    um_sem_origem = _linha(
        [_serv(), _serv(origem=None, objeto="C2")],
        [_quant(valor=200.0)],
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["etapa:escavacao"]},
    )
    assert (
        um_sem_origem["origem"] == "indeterminada"
        and um_sem_origem["origem_gavetas"] is None
    )


def test_origem_do_servico_pela_cadeia_fato_evidencia_documento():
    fatos = {
        "F1": {"fato_id": "F1", "evidencia_id": "EV-CAVAS"},
        "F2": {"fato_id": "F2", "evidencia_id": "EV-MDS"},
        "F3": {"fato_id": "F3", "evidencia_id": "EV-TXT"},
    }
    evidencias = {
        "EV-CAVAS": {
            "documento": "es1, es2",
            "localizador": {
                "pranchas": ["es1", "es2"],
                "criterio": "plantas de escavação",
            },
        },
        "EV-MDS": {
            "documento": "/saida/sfm/ortofoto_mds.PNG",
            "localizador": {"arquivo": "x"},
        },
        "EV-TXT": {"documento": "Memorial, rev. 2.pdf", "localizador": "p. 3"},
    }
    pdfs = {
        "es1": "dados/PBGE/ESCAVACAO-01-R2.pdf",
        "es2": "dados/PBGE/ESCAVACAO-02-R2.pdf",
    }
    assert gv.origem_do_servico({"fatos": ["F1", "F2"]}, fatos, evidencias, pdfs) == [
        "arquivo:escavacao-01-r2",
        "arquivo:escavacao-02-r2",
        "arquivo:ortofoto_mds",
        "etapa:escavacao",
    ]
    # sem o mapa, o id da prancha fica como está; o critério ainda dá a etapa
    assert gv.origem_do_servico({"fatos": ["F1"]}, fatos, evidencias) == [
        "arquivo:es1",
        "arquivo:es2",
        "etapa:escavacao",
    ]
    # sem lista de pranchas o documento inteiro é UM insumo (não se separa por vírgula)
    assert gv.origem_do_servico({"fatos": ["F3"]}, fatos, evidencias) == [
        "arquivo:memorial, rev. 2"
    ]
    assert gv.origem_do_servico({"fatos": ["F1", "F9"]}, fatos, evidencias) is None
    assert gv.origem_do_servico({"fatos": []}, fatos, evidencias) is None
    base = {
        "fatos": list(fatos.values()),
        "evidencias": [{"evidencia_id": k, **v} for k, v in evidencias.items()],
    }
    servicos = [{"fatos": ["F2"]}]
    gv.anotar_origem(servicos, base)
    assert servicos[0]["origem"] == ["arquivo:ortofoto_mds"]


def test_origem_da_eap_codificada_pelos_elementos_construtivos():
    def feat(i, doc, fonte):
        return {"properties": {"id": i, "doc": doc, "fonte": fonte}}

    construtivos = {
        "geojson": {
            "features": [
                feat(
                    "c1",
                    "PBGE-ESC-01.pdf",
                    "escavação calculada (camadas.escavacao) · Foz",
                ),
                feat("c2", None, "escavação calculada (x)"),
                feat("b1", None, "ficha"),
            ]
        }
    }
    quant = [
        _quant("U1.ETA.GEO.MOV.ESC") | {"evidencias": ["c1", "c2"]},
        _quant("U1.ETA.GEO.FUN.BLO", unidade="un") | {"evidencias": ["b1"]},
        _quant("U1.ETA.GEO.MOV.REA") | {"evidencias": ["c1", "sumiu"]},
        _quant("U1.ETA.GEO.MOV.VAL"),
    ]
    origens = eap.origem_das_quantidades(quant, construtivos)
    assert origens[("U1.ETA.GEO.MOV.ESC", "m³")] == [
        "arquivo:pbge-esc-01",
        "etapa:escavacao",
    ]
    assert (
        origens[("U1.ETA.GEO.FUN.BLO", "un")] is None
    )  # sem documento nem etapa conhecida
    assert origens[("U1.ETA.GEO.MOV.REA", "m³")] is None  # elemento fora do contrato
    assert origens[("U1.ETA.GEO.MOV.VAL", "m³")] is None  # sem elementos
    assert eap.origem_das_quantidades(quant, None)[("U1.ETA.GEO.MOV.ESC", "m³")] is None


def _gavetas_das_cavas(pranchas, mds="/x/sfm/ortofoto_mds.png"):
    from camadas import extrair_gavetas as eg

    marcas = [
        {
            "E": 0.0,
            "N": 0.0,
            "cota_m": 10.0,
            "texto": "10,00",
            "topo": False,
            "prancha": pranchas[0],
        }
    ]
    bases = [{"coords": [[0, 0], [10, 0], [10, 10], [0, 10]], "etapa": None}]
    return eg.de_cavas(
        marcas,
        bases,
        [],
        {"superficie_id": "S", "evidencia_id": "EV-S", "crs_h": "EPSG:31982"},
        pranchas,
        mds=mds,
        layers=["BASE"],
    )


def test_cadeia_completa_com_nomes_reais_id_de_prancha_diferente_do_stem_do_pdf():
    """Foz: as gavetas citam `es1`; o construtivo grava o stem do PDF. O mapa id → PDF faz os dois falarem o mesmo nome."""
    base = _gavetas_das_cavas(["es1", "es2", "es3"])
    servico = {"fatos": [f["fato_id"] for f in base["fatos"]]}
    stem = "006-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO1-R2"
    pdfs = {
        "es1": f"dados/foz/projeto/2. PBGE/{stem}.pdf",
        "es2": "dados/foz/x/ESC2-R2.pdf",
        "es3": "dados/foz/x/ESC3-R2.pdf",
    }
    gv.anotar_origem([servico], base, pdfs)
    assert (
        f"arquivo:{stem.lower()}" in servico["origem"]
        and "arquivo:es1" not in servico["origem"]
    )
    assert (
        "arquivo:ortofoto_mds" in servico["origem"]
        and "etapa:escavacao" in servico["origem"]
    )
    props = {
        "id": "c",
        "doc": stem,
        "origem_etapa": "escavacao",
        "fonte": "qualquer texto",
    }
    origem_codificada = sorted(eap.origem_do_elemento(props))
    assert origem_codificada == [f"arquivo:{stem.lower()}", "etapa:escavacao"]
    assert gv.comparar_origens(servico["origem"], origem_codificada) == "mesma"
    # só o documento em comum (sem etapa em nenhum dos dois lados) já basta, porque o nome agora é o mesmo
    so_arquivo = [i for i in servico["origem"] if i.startswith("arquivo:")]
    assert gv.comparar_origens(so_arquivo, [f"arquivo:{stem.lower()}"]) == "mesma"


def test_mudar_a_fonte_do_elemento_continua_mesma_origem_e_o_texto_so_e_reserva():
    props = {
        "id": "c",
        "doc": "pbge",
        "origem_etapa": "escavacao",
        "fonte": "texto reescrito sem a palavra-chave",
    }
    assert "etapa:escavacao" in eap.origem_do_elemento(props)
    antigo = {
        "id": "c",
        "doc": None,
        "fonte": "escavação calculada (camadas.escavacao) · PBGE",
    }  # sem o campo
    assert eap.origem_do_elemento(antigo) == {"etapa:escavacao"}
    sem_nada = {"id": "c", "doc": None, "fonte": "escavação (reescrita)"}
    assert eap.origem_do_elemento(sem_nada) is None
    base = _gavetas_das_cavas(["es1"])
    servico = {"fatos": [f["fato_id"] for f in base["fatos"]]}
    gv.anotar_origem([servico], base)
    assert (
        gv.comparar_origens(servico["origem"], sorted(eap.origem_do_elemento(props)))
        == "mesma"
    )


def test_construtivos_grava_a_etapa_estruturada_da_cava():
    from camadas import construtivos

    ctx = {
        "usados": set(),
        "contagem": __import__("collections").Counter(),
        "features": [],
    }
    construtivos._adicionar(
        ctx,
        "ETA",
        "cava",
        "c1",
        {"type": "Point", "coordinates": [0, 0]},
        [],
        "f",
        origem_etapa="escavacao",
    )
    construtivos._adicionar(
        ctx, "ETA", "cava", "c2", {"type": "Point", "coordinates": [0, 0]}, [], "f"
    )
    assert ctx["features"][0]["properties"]["origem_etapa"] == "escavacao"
    assert "origem_etapa" not in ctx["features"][1]["properties"]


# --- terceira coluna: documento independente -------------------------------------------------------------------------


def _fato(
    codigo="U1.ETA.GEO.MOV.ESC", unidade="m³", afirmacoes=(), servico="", decisoes=()
):
    return {
        "codigo": codigo,
        "servico": servico,
        "unidade": unidade,
        "status": "fonte única",
        "afirmacoes": [
            {"documento": d, "tipo": t, "valor": v} for d, t, v in afirmacoes
        ],
        "decisoes": [{"valor": v, "autor": a} for v, a in decisoes],
    }


def _doc(fatos, referencia=100.0, **kw):
    return gv.documento_independente(
        fatos, "U1.ETA.GEO.MOV.ESC", kw.pop("unidade", "m³"), referencia, **kw
    )


def test_documento_de_planilha_que_confere():
    r = _doc([_fato(afirmacoes=[("CUSTO CIVIL.xlsx", "planilha", 100.004)])])
    assert r["situacao_documento"] == "confere com documento" and r[
        "documento"
    ] == pytest.approx(100.004)
    assert r["documentos"] == ["CUSTO CIVIL.xlsx"]


def test_documento_que_difere_traz_delta_e_percentual():
    r = _doc([_fato(afirmacoes=[("CUSTO CIVIL.xlsx", "planilha", 80.0)])])
    assert r["situacao_documento"] == "difere do documento"
    assert r["diferenca_documento"] == pytest.approx(20.0) and r[
        "diferenca_documento_pct"
    ] == pytest.approx(25.0)


def test_documentos_em_conflito_e_sem_documento():
    conflito = _doc(
        [_fato(afirmacoes=[("a.xlsx", "planilha", 80.0), ("b.pdf", "memorial", 120.0)])]
    )
    assert (
        conflito["situacao_documento"] == "documento em conflito"
        and conflito["documento"] is None
    )
    assert conflito["documentos"] == ["a.xlsx", "b.pdf"]
    assert (
        _doc([])["situacao_documento"] == "sem documento"
        and _doc(None)["documento"] is None
    )
    assert (
        _doc(
            [
                _fato(
                    codigo="U1.ETA.GEO.MOV.REA",
                    afirmacoes=[("a.xlsx", "planilha", 100.0)],
                )
            ]
        )["situacao_documento"]
        == "sem documento"
    )  # outro código
    assert (
        _doc([_fato(afirmacoes=[("a.xlsx", "planilha", 100.0)], servico="forma")])[
            "situacao_documento"
        ]
        == "sem documento"
    )  # serviço, não o item


def test_documento_dois_documentos_concordando_nao_e_conflito():
    r = _doc(
        [
            _fato(
                afirmacoes=[("a.xlsx", "planilha", 100.0), ("b.pdf", "edital", 100.005)]
            )
        ]
    )
    assert (
        r["situacao_documento"] == "confere com documento" and len(r["documentos"]) == 2
    )


@pytest.mark.parametrize("tipo", ["associado", "geometria", "projeto"])
def test_fato_nao_independente_e_ignorado(tipo):
    r = _doc([_fato(afirmacoes=[("modelo:construtivos", tipo, 100.0)])])
    assert r["situacao_documento"] == "sem documento" and r["documentos"] == []
    misto = _doc(
        [
            _fato(
                afirmacoes=[
                    ("modelo:construtivos", tipo, 100.0),
                    ("a.xlsx", "planilha", 80.0),
                ]
            )
        ]
    )
    assert (
        misto["situacao_documento"] == "difere do documento"
    )  # só a planilha conta, não conflita com a geometria


def test_ia_vale_como_documento_e_decisao_fica_a_parte():
    ia = _doc([_fato(afirmacoes=[("ia:edital.pdf", "ia", 100.0)])])
    assert ia["situacao_documento"] == "confere com documento"
    decisao = _doc(
        [_fato(afirmacoes=[("a.xlsx", "planilha", 80.0)], decisoes=[(100.0, "maria")])]
    )
    assert decisao["situacao_documento"] == "difere do documento" and decisao[
        "documentos"
    ] == ["a.xlsx"]
    assert decisao["decisoes"] == [{"valor": 100.0, "autor": "maria"}]
    so_decisao = _doc([_fato(decisoes=[(100.0, "maria")])])
    assert (
        so_decisao["situacao_documento"] == "sem documento"
        and so_decisao["documento"] is None
    )
    assert so_decisao["decisoes"] == [{"valor": 100.0, "autor": "maria"}]


def test_fato_com_curinga_nao_vale_para_uma_linha_de_um_sistema():
    fatos = [
        _fato(codigo="U1.*.GEO.MOV.ESC", afirmacoes=[("a.xlsx", "planilha", 100.0)])
    ]
    assert (
        _doc(fatos)["situacao_documento"] == "sem documento"
    )  # o total da unidade não é o do sistema ETA


def test_concreto_e_curinga_nunca_viram_conflito_entre_si():
    fatos = [
        _fato(
            codigo="U1.*.GEO.MOV.ESC", afirmacoes=[("contrato.csv", "planilha", 1000.0)]
        ),
        _fato(afirmacoes=[("memorial.pdf", "memorial", 600.0)]),
    ]
    r = _doc(fatos, 600.0)
    assert r["situacao_documento"] == "confere com documento" and r["documentos"] == [
        "memorial.pdf"
    ]


def test_tolerancia_dos_documentos_e_a_relativa_do_consolidar():
    from camadas import evidencias

    assert evidencias.TOLERANCIA_RELATIVA == 0.005
    perto = _doc(
        [
            _fato(
                afirmacoes=[("a.csv", "planilha", 1000.0), ("b.pdf", "edital", 1004.0)]
            )
        ],
        1000.0,
    )
    assert (
        perto["situacao_documento"] != "documento em conflito"
    )  # 4 de 1000 < 0,5 %, apesar de > 0,01 absoluto
    longe = _doc(
        [
            _fato(
                afirmacoes=[("a.csv", "planilha", 1000.0), ("b.pdf", "edital", 1010.0)]
            )
        ],
        1000.0,
    )
    assert longe["situacao_documento"] == "documento em conflito"


def _linhas_do_sistema(**g):
    return [
        {
            "codigo": c,
            "unidade": "m³",
            "gavetas": v,
            "codificada": v,
            "origem_gavetas": ["etapa:a"],
            "origem_codificada": ["etapa:a"],
        }
        for c, v in g.items()
    ]


def test_total_do_curinga_contra_a_soma_das_linhas():
    linhas = _linhas_do_sistema(
        **{
            "U1.ETA.GEO.MOV.ESC": 600.0,
            "U1.GERAL.GEO.MOV.ESC": 400.0,
            "U2.X.GEO.MOV.ESC": 7.0,
        }
    )
    fatos = [
        _fato(
            codigo="U1.*.GEO.MOV.ESC", afirmacoes=[("contrato.csv", "planilha", 1000.0)]
        )
    ]
    (total,) = gv.conciliar_totais(linhas, fatos)
    assert (
        total["codigo"] == "U1.*.GEO.MOV.ESC" and total["n_linhas"] == 2
    )  # U2 não casa
    assert (
        total["gavetas"] == 1000.0
        and total["situacao_documento"] == "confere com documento"
    )
    assert total["origem_gavetas"] == ["etapa:a"]
    errado = [
        _fato(
            codigo="U1.*.GEO.MOV.ESC", afirmacoes=[("contrato.csv", "planilha", 900.0)]
        )
    ]
    assert (
        gv.conciliar_totais(linhas, errado)[0]["situacao_documento"]
        == "difere do documento"
    )
    assert (
        gv.conciliar_totais(linhas, [_fato(codigo="U1.ETA.GEO.MOV.ESC")]) == []
    )  # sem curinga: sem total
    assert (
        gv.conciliar_totais(
            linhas,
            [
                _fato(
                    codigo="U1.*.GEO.MOV.ESC",
                    unidade="kg",
                    afirmacoes=[("a", "planilha", 1.0)],
                )
            ],
        )
        == []
    )


def test_total_sem_um_dos_lados_nao_soma_parcial():
    linhas = _linhas_do_sistema(**{"U1.ETA.GEO.MOV.ESC": 600.0})
    linhas.append(
        {
            "codigo": "U1.GERAL.GEO.MOV.ESC",
            "unidade": "m³",
            "gavetas": None,
            "codificada": 400.0,
            "origem_gavetas": None,
            "origem_codificada": ["etapa:a"],
        }
    )
    fatos = [
        _fato(
            codigo="U1.*.GEO.MOV.ESC", afirmacoes=[("contrato.csv", "planilha", 1000.0)]
        )
    ]
    (total,) = gv.conciliar_totais(linhas, fatos)
    assert (
        total["gavetas"] is None and total["codificada"] == 1000.0
    )  # cai para a codificada, inteira
    assert (
        total["origem_gavetas"] is None
        and total["situacao_documento"] == "confere com documento"
    )


def test_unidade_t_contra_kg():
    r = gv.documento_independente(
        [
            _fato(
                codigo="U1.ETA.ARM.X.Y",
                unidade="kg",
                afirmacoes=[("a.xlsx", "planilha", 2500.0)],
            )
        ],
        "U1.ETA.ARM.X.Y",
        "t",
        2.5,
    )
    assert r["situacao_documento"] == "confere com documento" and r[
        "documento"
    ] == pytest.approx(2.5)
    r = gv.documento_independente(
        [
            _fato(
                codigo="U1.ETA.ARM.X.Y",
                unidade="kg",
                afirmacoes=[("a.xlsx", "planilha", 2000.0)],
            )
        ],
        "U1.ETA.ARM.X.Y",
        "t",
        2.5,
    )
    assert r["situacao_documento"] == "difere do documento" and r[
        "diferenca_documento"
    ] == pytest.approx(0.5)
    metros = gv.documento_independente(
        [_fato(unidade="m", afirmacoes=[("a.xlsx", "planilha", 100.0)])],
        "U1.ETA.GEO.MOV.ESC",
        "m³",
        100.0,
    )
    assert (
        metros["situacao_documento"] == "sem documento"
    )  # unidade diferente nunca se mistura


def test_conciliar_traz_a_terceira_coluna_por_linha():
    fatos = [_fato(afirmacoes=[("CUSTO CIVIL.xlsx", "planilha", 90.0)])]
    linha = _linha(
        [_serv(origem=("arquivo:a",))],
        [_quant()],
        fatos=fatos,
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["arquivo:b"]},
    )
    assert (
        linha["situacao"] == "confere"
        and linha["situacao_documento"] == "difere do documento"
    )
    assert linha["documento"] == pytest.approx(90.0)
    assert (
        _linha([_serv()], [_quant()])["situacao_documento"] == "sem documento"
    )  # sem fatos de evidências


# --- formatação em Python ---------------------------------------------------------------------------------------------


def test_conciliacao_formata_origem_documento_e_resumo():
    fatos = [_fato(afirmacoes=[("CUSTO CIVIL.xlsx", "planilha", 80.0)])]
    linhas = gv.conciliar_eap(
        [_serv(valor=1234.5)],
        [_quant(valor=1234.5)],
        fatos=fatos,
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["etapa:escavacao"]},
    )
    c = eap_html.conciliacao(linhas)
    l = c["linhas"][0]
    assert l["situacao"] == "confere (mesma origem)" and l["mesma_origem"] is True
    assert (
        l["origem_txt"] == "mesma origem"
        and l["origem_insumos_txt"]
        == "gavetas: etapa:escavacao; codificada: etapa:escavacao"
    )
    assert (
        l["documento_txt"] == "80,00 m³" and l["documentos_txt"] == "CUSTO CIVIL.xlsx"
    )
    assert (
        l["situacao_documento_txt"] == "difere do documento (Δ 1.154,50 m³ · 1.443,1 %)"
    )
    assert c["resumo"]["confere (mesma origem)"] == 1 and c["resumo"]["confere"] == 0
    assert (
        c["resumo_documento"]["difere do documento"] == 1
        and c["resumo_documento"]["sem documento"] == 0
    )
    assert "confere (mesma origem)" in eap_html.SITUACOES_CONCILIACAO


def test_difere_com_mesma_origem_tambem_e_destacado_no_selo():
    linhas = gv.conciliar_eap(
        [_serv(valor=110.0)],
        [_quant()],
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["etapa:escavacao"]},
    )
    l = eap_html.conciliacao(linhas)["linhas"][0]
    assert (
        l["situacao"] == "difere"
        and l["mesma_origem"] is True
        and "erro de cálculo" in l["motivo"]
    )
    independente = eap_html.conciliacao(gv.conciliar_eap([_serv()], [_quant()]))[
        "linhas"
    ][0]
    assert (
        independente["mesma_origem"] is False
        and independente["origem_txt"] == "indeterminada"
    )


def test_conciliacao_formata_origem_por_lado_decisao_e_totais():
    fatos = [
        _fato(decisoes=[(100.0, "ana")]),
        _fato(codigo="U1.*.GEO.MOV.ESC", afirmacoes=[("c.csv", "planilha", 100.0)]),
    ]
    linhas = gv.conciliar_eap(
        [_serv(origem=("arquivo:a",))],
        [_quant()],
        fatos=fatos,
        origens_codificada={("U1.ETA.GEO.MOV.ESC", "m³"): ["arquivo:b"]},
    )
    c = eap_html.conciliacao(linhas, gv.conciliar_totais(linhas, fatos))
    l = c["linhas"][0]
    assert l["origem_insumos_txt"] == "gavetas: arquivo:a; codificada: arquivo:b"
    assert (
        l["decisao_txt"] == "decisão de ana: 100,00 m³"
        and l["situacao_documento"] == "sem documento"
    )
    (total,) = c["totais"]
    assert (
        total["codigo"] == "U1.*.GEO.MOV.ESC" and total["documento_txt"] == "100,00 m³"
    )
    assert (
        total["situacao_documento_txt"] == "confere com documento"
        and total["n_linhas"] == 1
    )
    sem = eap_html.conciliacao(gv.conciliar_eap([_serv(origem=None)], [_quant()]))[
        "linhas"
    ][0]
    assert (
        sem["origem_insumos_txt"] == "gavetas: indeterminada; codificada: indeterminada"
        and sem["decisao_txt"] == "—"
    )
