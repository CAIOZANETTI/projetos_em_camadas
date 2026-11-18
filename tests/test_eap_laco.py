"""F5: o laço até a EAP completa (destino de cada folha a preencher, portão e roteiro), com bases sintéticas."""

import json

from camadas import eap_laco as laco
from camadas import gavetas, gavetas_texto

DOC = "doc0000000000001"


def _base() -> dict:
    return {g: [] for g in gavetas.GAVETAS}


def _documento(base: dict, arquivo: str, documento_id: str = DOC) -> None:
    base["documentos"].append(
        {"documento_id": documento_id, "arquivo": arquivo, "classe": "memorial"}
    )


def _mencao(
    base: dict,
    item: str,
    paginas: tuple = (3,),
    quantidade: float | None = None,
    unidade: str | None = None,
    documento_id: str = DOC,
) -> None:
    """Objeto `mencao_documento` como a E1 grava: um fato `mencao` por página; quantidade e unidade quando há."""
    oid = f"txt-{documento_id}-{item}"
    base["objetos"].append({"objeto_id": oid, "classe": "mencao_documento"})

    def fato(propriedade, valor, evidencia_id):
        base["fatos"].append(
            {
                "fato_id": f"{oid}.{propriedade}.{evidencia_id}",
                "objeto_id": oid,
                "propriedade": propriedade,
                "valor": valor,
                "natureza": "observado",
                "evidencia_id": evidencia_id,
            }
        )

    for pagina in paginas:
        ev = f"EV-{oid}-p{pagina}"
        base["evidencias"].append(
            {
                "evidencia_id": ev,
                "documento": documento_id,
                "localizador": {"pagina": pagina},
                "trecho": f"trecho da página {pagina} sobre {item}",
            }
        )
        fato("mencao", True, ev)
    fato("item_tecnico", item, f"EV-{oid}-p{paginas[0]}")
    if quantidade is not None:
        fato("quantidade", quantidade, f"EV-{oid}-p{paginas[0]}")
        fato("unidade_medida", unidade, f"EV-{oid}-p{paginas[0]}")


def _folha(folha_id: str, item: str, situacao="a preencher", obrigatoria=True) -> dict:
    return {
        "id": folha_id,
        "nome": f"Folha {folha_id}",
        "obrigatoria": obrigatoria,
        "aponta": [{"item": item}],
        "situacao": situacao,
    }


def _eap(*folhas: dict) -> dict:
    return {
        "tipos": {
            "obra_localizada": {
                "etapas": [{"id": "OP.01", "nome": "Etapa", "folhas": list(folhas)}]
            }
        }
    }


def _destino(destinos: list[dict], folha_id: str) -> dict:
    return next(d for d in destinos if d["folha"] == folha_id)


def test_menção_vira_roteiro_de_ia_com_documento_e_paginas():
    base = _base()
    _documento(base, "MEMORIAL/memorial_fundacoes.pdf")
    _mencao(base, "GEO.FUN.EST", paginas=(4, 7))
    eap = _eap(_folha("OP.03.01", "GEO.FUN.EST"))
    d = _destino(laco.destinos(eap, base), "OP.03.01")
    assert d["destino"] == laco.MENCAO
    assert d["degrau"] == laco.DEGRAU_IA
    ia = next(a for a in d["acoes"] if a["destino"] == laco.MENCAO)
    assert ia["documento"] == "MEMORIAL/memorial_fundacoes.pdf"
    assert ia["paginas"] == [4, 7]
    # a classe de objeto que alimenta o item aparece como degrau de código, antes da IA
    assert d["acoes"][0]["degrau"] == laco.DEGRAU_CODIGO
    assert "estaca" in d["acoes"][0]["classes"]

    linhas = laco.roteiro(laco.destinos(eap, base))
    assert len(linhas) == 1
    linha = linhas[0]
    assert linha["documento"] == "memorial_fundacoes.pdf"
    assert linha["paginas"] == [4, 7]
    assert linha["itens"][0]["codigo"] == "*.*.GEO.FUN.EST"
    assert "un" in linha["itens"][0]["unidades"]


def test_menção_com_quantidade_é_candidata_a_declarada_sem_preencher():
    base = _base()
    _documento(base, "memorial.pdf")
    _mencao(base, "GEO.FUN.EST", quantidade=250, unidade="un")
    eap = _eap(_folha("OP.03.01", "GEO.FUN.EST"))
    d = _destino(laco.destinos(eap, base), "OP.03.01")
    assert d["destino"] == laco.CANDIDATA
    candidata = next(a for a in d["acoes"] if a["destino"] == laco.CANDIDATA)
    assert (candidata["quantidade"], candidata["unidade_medida"]) == (250.0, "un")
    assert candidata["paginas"] == [3]
    # só diz: a EAP de entrada não muda
    assert (
        eap["tipos"]["obra_localizada"]["etapas"][0]["folhas"][0]["situacao"]
        == "a preencher"
    )


def test_documento_esperado_ausente_vai_para_o_humano():
    base = _base()
    # o módulo de filtros (estrutura de concreto) tem a forma, mas não a armadura, a locação nem a fundação
    _documento(base, "TRATAM_FILTROS/MOD01FORMA-R1.pdf")
    eap = _eap(_folha("OP.03.01", "GEO.FUN.EST"))
    d = _destino(laco.destinos(eap, base), "OP.03.01")
    assert d["destino"] == laco.ESPERADO
    assert d["degrau"] == laco.DEGRAU_HUMANO
    faltas = {
        a["documento_esperado"] for a in d["acoes"] if a["destino"] == laco.ESPERADO
    }
    assert {"armadura", "fundacao", "locacao_cargas"} <= faltas
    assert "forma" not in faltas
    assert "documento esperado ausente" in d["texto"]


def test_sem_menção_e_sem_documento_esperado_é_ausente_do_projeto():
    base = _base()
    eap = _eap(_folha("OP.01.01", "GER.PRE.MOB"))
    d = _destino(laco.destinos(eap, base), "OP.01.01")
    assert d["destino"] == laco.AUSENTE
    assert d["degrau"] == laco.DEGRAU_HUMANO
    assert "confirmado_por" not in d
    assert "confirmar que não se aplica" in d["texto"]


def test_obrigatorias_vem_primeiro_e_folha_fechada_nao_tem_destino():
    base = _base()
    eap = _eap(
        _folha("OP.01.04", "GEO.MOV.SUP", obrigatoria=False),
        _folha("OP.01.01", "GER.PRE.MOB"),
        _folha("OP.01.02", "GER.PRE.TOP", situacao="preenchida"),
    )
    destinos = laco.destinos(eap, base)
    assert [d["folha"] for d in destinos] == ["OP.01.01", "OP.01.04"]


def test_portao_aberto_e_fechado_pela_decisao_de_nao_se_aplica(tmp_path):
    base = _base()
    eap = _eap(
        _folha("OP.01.01", "GER.PRE.MOB"),
        _folha("OP.01.02", "GER.PRE.TOP", situacao="declarada"),
        _folha("OP.01.04", "GEO.MOV.SUP", obrigatoria=False),
    )
    aberto = laco.portao(eap, laco.destinos(eap, base))
    assert aberto["fechada"] is False
    assert [t["folha"] for t in aberto["trava"]] == ["OP.01.01"]
    c = aberto["completude"]["obra_localizada"]
    assert (c["declaradas"], c["a_preencher"], c["sem_destino"], c["com_destino"]) == (
        1,
        2,
        2,
        0,
    )

    arquivo = tmp_path / "decisoes_eap.json"
    arquivo.write_text(
        json.dumps(
            {
                "decisoes": [
                    {
                        "folha": "OP.01.01",
                        "decisao": "ausente_do_projeto",
                        "motivo": "canteiro fora do escopo do contrato",
                        "confirmado_por": "Caio",
                    },
                    {"folha": "OP.01.04", "decisao": "ausente_do_projeto"},
                ]
            }
        ),
        encoding="utf-8",
    )
    decisoes = laco.ler_decisoes(arquivo)
    assert set(decisoes) == {"OP.01.01"}  # sem confirmado_por não vale
    fechado = laco.portao(eap, laco.destinos(eap, base, decisoes))
    assert fechado["fechada"] is True
    assert fechado["trava"] == []
    assert fechado["completude"]["obra_localizada"]["ausentes_confirmadas"] == 1


def test_decisao_nao_fecha_folha_que_tem_menção():
    base = _base()
    _documento(base, "memorial.pdf")
    _mencao(base, "GEO.FUN.EST")
    eap = _eap(_folha("OP.03.01", "GEO.FUN.EST"))
    decisoes = {"OP.03.01": {"confirmado_por": "Caio", "decisao": "ausente_do_projeto"}}
    destinos = laco.destinos(eap, base, decisoes)
    assert "confirmado_por" not in destinos[0]
    assert "decisao_ignorada" in destinos[0]
    assert laco.portao(eap, destinos)["fechada"] is False


def test_sem_arquivo_de_decisoes_nada_e_lido(tmp_path):
    assert laco.ler_decisoes(tmp_path / "nao_existe.json") == {}
    assert laco.ler_decisoes(None) == {}


def test_roteiro_une_itens_e_paginas_da_mesma_folha_e_documento():
    base = _base()
    _documento(base, "pasta/laudo.pdf")
    _mencao(base, "GEO.FUN.EST", paginas=(2,))
    _mencao(base, "GEO.FUN.BLO", paginas=(5, 2))
    folha = _folha("OP.03.01", "GEO.FUN.EST")
    folha["aponta"].append({"item": "GEO.FUN.BLO"})
    linhas = laco.roteiro(laco.destinos(_eap(folha), base))
    assert len(linhas) == 1
    assert linhas[0]["paginas"] == [2, 5]
    assert [i["item"] for i in linhas[0]["itens"]] == ["GEO.FUN.EST", "GEO.FUN.BLO"]
    assert linhas[0]["documento"] == "laudo.pdf"


def _mencao_com_trechos(
    base: dict, item: str, trechos: dict, documento_id: str = DOC
) -> None:
    """Menção com um trecho próprio por página ({pagina: trecho}), como `gavetas_texto` grava."""
    oid = f"txt-{documento_id}-{item}"
    base["objetos"].append({"objeto_id": oid, "classe": "mencao_documento"})
    paginas = sorted(trechos)
    for pagina in paginas:
        ev = f"EV-{oid}-p{pagina}"
        base["evidencias"].append(
            {
                "evidencia_id": ev,
                "documento": documento_id,
                "localizador": {"pagina": pagina},
                "trecho": trechos[pagina],
            }
        )
        base["fatos"].append(
            {
                "fato_id": f"{oid}.mencao.{pagina}",
                "objeto_id": oid,
                "propriedade": "mencao",
                "valor": trechos[pagina],
                "natureza": "observado",
                "evidencia_id": ev,
            }
        )
    base["fatos"].append(
        {
            "fato_id": f"{oid}.item",
            "objeto_id": oid,
            "propriedade": "item_tecnico",
            "valor": item,
            "natureza": "observado",
            "evidencia_id": f"EV-{oid}-p{paginas[0]}",
        }
    )


def _roteiro_de_estacas(trechos: dict, regras=None, pendencias=()) -> list[dict]:
    base = _base()
    _documento(base, "pasta/memorial.pdf")
    _mencao_com_trechos(base, "GEO.FUN.EST", trechos)
    base["pendencias"] += list(pendencias)
    destinos = laco.destinos(_eap(_folha("OP.03.01", "GEO.FUN.EST")), base)
    return laco.roteiro(destinos, regras) if regras else laco.roteiro(destinos)


def test_roteiro_ranqueia_paginas_pela_forca_e_corta_no_teto():
    trechos = {n: "AS ESTACAS SEGUEM O PROJETO" for n in range(1, 9)}
    trechos[6] = "FORNECIMENTO DE 250 ESTACAS HELICE"
    trechos[4] = "ESTACAS HELICE CONTINUA CONFORME PROJETO"
    regras = {**gavetas_texto.REGRAS, "teto_paginas_por_documento_folha": 3}
    (linha,) = _roteiro_de_estacas(trechos, regras)
    assert linha["paginas"] == [6, 1, 2]
    assert linha["paginas_cortadas"] == 5
    primeira = linha["paginas_ranqueadas"][0]
    assert primeira["pagina"] == 6 and primeira["candidata"]["valor"] == 250
    assert linha["forca"][0] == 1


def test_roteiro_usa_o_teto_declarado_no_conceito():
    trechos = {n: "AS ESTACAS SEGUEM O PROJETO" for n in range(1, 10)}
    (linha,) = _roteiro_de_estacas(trechos)
    teto = gavetas_texto.REGRAS["teto_paginas_por_documento_folha"]
    assert len(linha["paginas"]) == teto
    assert linha["paginas_cortadas"] == 9 - teto
    assert laco.resumo_do_roteiro([linha])["paginas_cortadas"] == 9 - teto


def test_roteiro_diz_quais_termos_foram_ignorados_e_por_que():
    ignorado = {
        "objeto_id": "termo:GEO.FUN.EST",
        "regra": gavetas_texto.REGRA_TERMO_IGNORADO,
        "motivo": "frequência de documento 14.4% acima de 8%",
        "detalhe": r"\bESTACAS?\b(?!\s*\d+\s*\+)(?! (DE MADEIRA|PARA PROTECAO))",
    }
    (linha,) = _roteiro_de_estacas({3: "ESTACAS HELICE"}, pendencias=[ignorado])
    item = linha["itens"][0]
    assert item["termos_ignorados"] == [
        {"termo": "estacas", "motivo": ignorado["motivo"]}
    ]
    assert "estacas" not in item["termos"]
    assert laco.resumo_do_roteiro([linha])["termos_ignorados"] == 1


def test_roteiro_nao_traz_fragmento_de_regex_como_termo():
    (linha,) = _roteiro_de_estacas({3: "ESTACAS HELICE"})
    termos = linha["itens"][0]["termos"]
    assert "estacas" in termos
    assert all(not t.startswith("(") and len(t.replace(" ", "")) >= 4 for t in termos)


def test_item_global_confirmado_fecha_a_folha_mesmo_com_mencao(tmp_path):
    """Canteiro a preço global: o TR cita o item, sem quantidade. A decisão 'item_global' do Caio fecha a folha; sem
    `confirmado_por` ela não vale e o portão segue aberto."""
    base = _base()
    _documento(base, "memorial.pdf")
    _mencao(base, "GER.PRE.MOB")
    eap = _eap(_folha("OP.01.01", "GER.PRE.MOB"))
    arquivo = tmp_path / "decisoes_eap.json"
    proposta = {"folha": "OP.01.01", "decisao": "item_global", "motivo": "TR p. 25: por preço global"}
    arquivo.write_text(json.dumps({"decisoes": [proposta]}), encoding="utf-8")
    assert laco.ler_decisoes(arquivo) == {}
    assert laco.portao(eap, laco.destinos(eap, base, laco.ler_decisoes(arquivo)))["fechada"] is False
    arquivo.write_text(json.dumps({"decisoes": [{**proposta, "confirmado_por": "Caio"}]}), encoding="utf-8")
    destinos = laco.destinos(eap, base, laco.ler_decisoes(arquivo))
    assert destinos[0]["decisao"] == "item global (verba)" and destinos[0]["confirmado_por"] == "Caio"
    assert laco.portao(eap, destinos)["fechada"] is True
