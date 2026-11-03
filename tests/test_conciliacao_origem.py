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
    }
    evidencias = {
        "EV-CAVAS": {
            "documento": "pbge_01, pbge_02",
            "localizador": {"criterio": "plantas de escavação"},
        },
        "EV-MDS": {
            "documento": "/saida/sfm/ortofoto_mds.PNG",
            "localizador": {"arquivo": "x"},
        },
    }
    assert gv.origem_do_servico({"fatos": ["F1", "F2"]}, fatos, evidencias) == [
        "arquivo:ortofoto_mds",
        "arquivo:pbge_01",
        "arquivo:pbge_02",
        "etapa:escavacao",
    ]
    assert (
        gv.origem_do_servico({"fatos": ["F1", "F9"]}, fatos, evidencias) is None
    )  # fato fora da base
    assert (
        gv.origem_do_servico({"fatos": []}, fatos, evidencias) is None
    )  # sem fatos: sem origem
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


def test_cadeia_completa_cava_das_gavetas_e_da_codificada_se_reconhecem():
    """Os dois lados declaram a mesma etapa: é o caso da escavação de Foz."""
    from camadas import extrair_gavetas as eg

    marcas = [
        {
            "E": 0.0,
            "N": 0.0,
            "cota_m": 10.0,
            "texto": "10,00",
            "topo": False,
            "prancha": "pbge_esc",
        }
    ]
    bases = [{"coords": [[0, 0], [10, 0], [10, 10], [0, 10]], "etapa": None}]
    base = eg.de_cavas(
        marcas,
        bases,
        [],
        {"superficie_id": "S", "evidencia_id": "EV-S", "crs_h": "EPSG:31982"},
        ["pbge_esc"],
        mds="/x/sfm/ortofoto_mds.png",
        layers=["BASE"],
    )
    servico = {"fatos": [f["fato_id"] for f in base["fatos"]]}
    gv.anotar_origem([servico], base)
    assert (
        "etapa:escavacao" in servico["origem"]
        and "arquivo:ortofoto_mds" in servico["origem"]
    )
    props = {
        "id": "c",
        "doc": "pbge_esc",
        "fonte": "escavação calculada (camadas.escavacao) · levantamento",
    }
    assert (
        gv.comparar_origens(servico["origem"], sorted(eap.origem_do_elemento(props)))
        == "mesma"
    )


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


def test_ia_e_decisao_valem_como_documento():
    ia = _doc([_fato(afirmacoes=[("ia:edital.pdf", "ia", 100.0)])])
    assert ia["situacao_documento"] == "confere com documento"
    decisao = _doc(
        [_fato(afirmacoes=[("a.xlsx", "planilha", 80.0)], decisoes=[(100.0, "maria")])]
    )
    assert decisao["situacao_documento"] == "confere com documento" and decisao[
        "documentos"
    ] == ["decisão de maria"]


def test_curinga_do_codigo_casa_o_sistema():
    r = _doc(
        [_fato(codigo="U1.*.GEO.MOV.ESC", afirmacoes=[("a.xlsx", "planilha", 100.0)])]
    )
    assert r["situacao_documento"] == "confere com documento"


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
        and l["origem_insumos_txt"] == "etapa:escavacao"
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
