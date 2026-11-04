"""Vista da aba EAP (`camadas.eap_vista`): seções, contagens, contrato por UC e trecho, busca e ids de rede/prancha."""

import json

from camadas import contrato_211 as c211
from camadas import eap_vista


def _folha(id_, nome, situacao, quantidades=()):
    return {
        "id": id_,
        "nome": nome,
        "situacao": situacao,
        "situacao_txt": situacao,
        "quantidades_txt": list(quantidades),
        "obrigatoria": situacao == "a preencher",
    }


def _eap_padrao():
    ordem = [
        {"situacao": s, "n": 0} for s in ("preenchida", "calculada", "a preencher")
    ]
    etapa_a = {
        "id": "OP.02",
        "nome": "Movimento de terra",
        "folhas": [
            _folha(
                "OP.02.01", "Escavação mecânica", "preenchida", ["8.920,80 m³ (volume)"]
            ),
            _folha("OP.02.02", "Reaterro", "calculada"),
            _folha("OP.02.03", "Bota-fora", "a preencher"),
            _folha("OP.02.04", "Compactação", "a preencher"),
        ],
        "resumo": {"por_situacao": ordem},
    }
    etapa_b = {
        "id": "OP.03",
        "nome": "Fundações",
        "folhas": [_folha("OP.03.01", "Estacas", "preenchida")],
    }
    return {
        "tipos": [
            {
                "tipo": "obra_localizada",
                "nome": "Obra localizada",
                "etapas": [etapa_a, etapa_b],
            }
        ]
    }


def _evidencias():
    return [
        {
            "tipo": "rede_vala",
            "id": "R-01",
            "prancha": "f004, f009",
            "layer": "X",
            "valor": 10.0,
            "unidade": "m",
        },
        {
            "tipo": "rede_vala",
            "id": "R-02",
            "prancha": "f004",
            "layer": "X",
            "valor": 5.0,
            "unidade": "m",
        },
        {
            "tipo": "trecho_da_uc",
            "id": "TRECHO ALFA",
            "prancha": "f010",
            "layer": "Y",
            "valor": 3.0,
            "unidade": "m",
        },
        {
            "tipo": "sondagem",
            "id": "SP-1",
            "furo": "SP-1",
            "valor": 2.0,
            "unidade": "m",
        },
    ]


def _resultados():
    base = {
        "aba": "CUSTO CIVIL",
        "quantidade_declarada": None,
        "premissas": [],
        "unidade": "M3",
    }
    return [
        {
            **base,
            "linha": 15,
            "folha_eap": "OP.02.01",
            "uc": "UC 1 - ÁGUA",
            "trecho": "TRECHO ALFA",
            "composicao": "020223",
            "descricao": "ESCAVAÇÃO MECÂNICA DE VALA",
            "situacao": "calculada",
            "quantidade_calculada": 1234.5,
            "unidade_calculada": "m3",
            "evidencias": _evidencias(),
            "projeto": "PR-01",
            "motivo": None,
            "premissas": [
                {"nome": "folga_m", "valor": 0.5, "unidade": "m", "estado": "calibrar"}
            ],
        },
        {
            **base,
            "linha": 16,
            "folha_eap": "OP.02.01",
            "uc": "UC 1 - ÁGUA",
            "trecho": None,
            "composicao": "020224",
            "descricao": "Reaterro compactado",
            "situacao": "a preencher",
            "quantidade_calculada": None,
            "unidade_calculada": None,
            "evidencias": [],
            "projeto": None,
            "motivo": "sem rede medida",
        },
        {
            **base,
            "linha": 17,
            "folha_eap": "OP.02.02",
            "uc": "UC 2 - LODO",
            "trecho": "TRECHO BETA",
            "composicao": "030101",
            "descricao": "Reaterro de vala",
            "situacao": "calculada",
            "quantidade_calculada": 10.0,
            "unidade_calculada": "m3",
            "evidencias": [],
            "projeto": "PR-02",
            "motivo": None,
        },
        {
            **base,
            "linha": 18,
            "folha_eap": None,
            "uc": None,
            "trecho": None,
            "composicao": "DI",
            "descricao": "Administração",
            "situacao": "declarada",
            "quantidade_declarada": 18.0,
            "quantidade_calculada": None,
            "unidade_calculada": None,
            "evidencias": [],
            "projeto": None,
            "motivo": None,
        },
    ]


def _dados(com_extras=True):
    res = _resultados()
    dados = {
        "eap_padrao": _eap_padrao(),
        "contrato_211": {
            "resumo": {
                "por_situacao": {"calculada": 2, "a preencher": 1, "declarada": 1}
            },
            "resumo_txt": [["Linhas", "4"]],
            "premissas": ["p1"],
            "linhas": c211.para_html(res),
        },
    }
    if com_extras:
        dados["eap_painel"] = {
            "arvore": [{"codigo": "U1"}, {"codigo": "U2"}],
            "resumo": {"fatos": 1500},
        }
        dados["eap_gavetas"] = {"nos": [{}], "resumo": {"servicos": 7}}
        dados["conferencia_cavas"] = {
            "secoes": [{}],
            "placar": {"confere": 3, "difere": 0, "não conferível": 12},
        }
    return dados


def test_sem_dados_devolve_none():
    assert eap_vista.montar({}) is None
    assert eap_vista.montar({"eap_painel": {"arvore": [{}]}}) is None


def test_secoes_so_com_dado():
    vista = eap_vista.montar(_dados())
    assert [s["id"] for s in vista["secoes"]] == [
        "wbs",
        "contrato",
        "codificada",
        "gavetas",
        "cavas",
    ]
    textos = {s["id"]: s["n_txt"] for s in vista["secoes"]}
    assert textos["wbs"] == "5 folhas · 40 % preenchidas"
    assert textos["contrato"] == "4 linhas · 2 calculadas"
    assert textos["codificada"] == "2 nós · 1.500 fatos"
    assert textos["cavas"] == "3 confere · 12 não conferível"
    minimo = eap_vista.montar(_dados(com_extras=False))
    assert [s["id"] for s in minimo["secoes"]] == ["wbs", "contrato"]
    so_contrato = eap_vista.montar({"contrato_211": _dados()["contrato_211"]})
    assert [s["id"] for s in so_contrato["secoes"]] == [
        "contrato"
    ] and "wbs" not in so_contrato


def test_contagens_por_etapa_batem_com_as_folhas():
    vista = eap_vista.montar(_dados())
    tipo = vista["wbs"]["tipos"][0]
    etapa = tipo["etapas"][0]
    assert etapa["rotulo"] == "OP.02 · Movimento de terra"
    assert etapa["contagens"] == {"preenchida": 1, "calculada": 1, "a preencher": 2}
    assert (
        etapa["contagens_txt"]
        == "4 folhas · 1 preenchida · 1 calculada · 2 a preencher"
    )
    for e in tipo["etapas"]:
        assert e["contagens"] == _contar_folhas(e)
        assert sum(e["contagens"].values()) == len(e["folhas"])
    assert tipo["contagens"] == {"preenchida": 2, "calculada": 1, "a preencher": 2}
    filtros = {f["rotulo"]: f["n"] for f in vista["situacoes"]["wbs"]}
    assert filtros == tipo["contagens"]
    assert [f["rotulo"] for f in vista["situacoes"]["wbs"]] == [
        "preenchida",
        "calculada",
        "a preencher",
    ]
    assert {f["rotulo"]: f["n"] for f in vista["situacoes"]["contrato"]} == {
        "calculada": 2,
        "a preencher": 1,
        "declarada": 1,
    }


def _contar_folhas(etapa):
    contagem = {}
    for f in etapa["folhas"]:
        contagem[f["situacao"]] = contagem.get(f["situacao"], 0) + 1
    return contagem


def test_linhas_do_contrato_penduradas_na_folha_certa():
    folhas = {
        f["id"]: f
        for e in eap_vista.montar(_dados())["wbs"]["tipos"][0]["etapas"]
        for f in e["folhas"]
    }
    f1 = folhas["OP.02.01"]
    assert [c["id"] for c in f1["contrato"]] == [
        "c211-custo-civil-15",
        "c211-custo-civil-16",
    ]
    assert (
        f1["contrato"][0]["calculada"] == "1.234,50"
        and f1["contrato"][0]["unidade"] == "m3"
    )
    assert (
        f1["contrato"][1]["calculada"] == "—" and f1["contrato"][1]["unidade"] is None
    )
    assert f1["n_contrato_txt"] == "2 linhas no contrato"
    assert [c["id"] for c in folhas["OP.02.02"]["contrato"]] == ["c211-custo-civil-17"]
    assert folhas["OP.02.02"]["n_contrato_txt"] == "1 linha no contrato"
    assert (
        folhas["OP.02.03"]["contrato"] == []
        and folhas["OP.02.03"]["n_contrato_txt"] == "sem linhas no contrato"
    )
    assert f1["obrigatoria"] is False and folhas["OP.02.03"]["obrigatoria"] is True


def test_contrato_agrupado_por_uc_e_trecho():
    contrato = eap_vista.montar(_dados())["contrato"]
    assert [u["rotulo"] for u in contrato["unidades"]] == [
        "UC 1 - ÁGUA",
        "UC 2 - LODO",
        "Itens gerais (sem UC)",
    ]
    uc1 = contrato["unidades"][0]
    assert [t["rotulo"] for t in uc1["trechos"]] == [
        "TRECHO ALFA",
        "Itens gerais da UC",
    ]
    assert (
        uc1["trechos"][0]["projeto"] == "PR-01" and uc1["trechos"][1]["projeto"] is None
    )
    assert uc1["trechos"][0]["contagens_txt"] == "1 linha · 1 calculada"
    assert uc1["contagens_txt"] == "2 linhas · 1 calculada · 1 a preencher"
    assert contrato["resumo_txt"] == [["Linhas", "4"]] and contrato["premissas"] == [
        "p1"
    ]
    linha = uc1["trechos"][0]["linhas"][0]
    assert linha["linha_txt"] == "CUSTO CIVIL · 15"
    assert linha["calculada_txt"] == "1.234,50 m3"
    assert uc1["trechos"][1]["linhas"][0]["calculada_txt"] == "—"
    assert uc1["trechos"][1]["linhas"][0]["motivo"] == "sem rede medida"
    assert any("folga_m = 0,50 m (calibrar)" in d for d in linha["detalhe"])
    assert any(d.startswith("rede_vala · R-01") for d in linha["detalhe"])
    total = sum(len(t["linhas"]) for u in contrato["unidades"] for t in u["trechos"])
    assert total == 4


def test_busca_sem_acento_e_minuscula():
    vista = eap_vista.montar(_dados())
    folha = vista["wbs"]["tipos"][0]["etapas"][0]["folhas"][0]
    assert "escavacao mecanica" in folha["busca"] and "op.02.01" in folha["busca"]
    assert "8.920,80 m³" in folha["busca"] or "8.920,80 m3" in folha["busca"]
    assert "escavacao mecanica de vala" in folha["busca"]  # descrição do contrato
    assert folha["busca"] == folha["busca"].lower()
    linha = vista["contrato"]["unidades"][0]["trechos"][0]["linhas"][0]
    assert (
        "agua" in linha["busca"]
        and "á" not in linha["busca"]
        and "ç" not in linha["busca"]
    )
    assert eap_vista.normalizar(["Ação", None, "LODO"]) == "acao lodo"


def test_redes_e_pranchas_vem_das_evidencias_originais():
    html = c211.para_html(_resultados())
    com = html[0]
    assert com["redes"] == ["R-01", "R-02"]  # trecho_da_uc e furo ficam de fora
    assert com["pranchas"] == ["f004", "f009", "f010"]
    assert com["id"] == "c211-custo-civil-15"
    assert html[1]["redes"] == [] and html[1]["pranchas"] == []
    linha = eap_vista.montar(_dados())["contrato"]["unidades"][0]["trechos"][0][
        "linhas"
    ][0]
    assert linha["redes"] == ["R-01", "R-02"] and linha["pranchas"] == [
        "f004",
        "f009",
        "f010",
    ]
    assert "r-01" in linha["busca"] and "f009" in linha["busca"]


def test_serializavel_deterministico_e_metadados():
    primeira = json.dumps(eap_vista.montar(_dados()), ensure_ascii=False)
    assert primeira == json.dumps(eap_vista.montar(_dados()), ensure_ascii=False)
    assert eap_vista.metadados()["modulo"] == "eap_vista"
