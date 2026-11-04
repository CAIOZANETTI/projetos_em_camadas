"""F3: a EAP única preenchida só pelas gavetas (itens técnicos, folhas do modelo, contrato declarado, paridade)."""

import json

import numpy as np
import pytest

from camadas import eap_preencher as ep
from camadas import gavetas, geo
from camadas import gavetas_construtivos as gc

DOC_ID = "a1b2c3d4e5f60718"


def _base() -> dict:
    return {g: [] for g in gavetas.GAVETAS}


def _evidencia(
    base: dict, evidencia_id: str, localizador=None, documento=DOC_ID
) -> None:
    base["evidencias"].append(
        {
            "evidencia_id": evidencia_id,
            "classe": "projeto",
            "documento": documento,
            "localizador": localizador or {"pagina": 3},
            "metodo": "camadas.prancha",
            "executor": "código",
        }
    )


def _fato(
    base: dict, objeto_id: str, propriedade: str, valor, evidencia_id: str
) -> None:
    base["fatos"].append(
        {
            "fato_id": f"{objeto_id}.{propriedade}",
            "objeto_id": objeto_id,
            "propriedade": propriedade,
            "valor": valor,
            "natureza": "projetado",
            "evidencia_id": evidencia_id,
        }
    )


def _elemento(
    base: dict, objeto_id: str, classe: str, unidade: str, sistema: str, **fatos
) -> None:
    """Objeto da classe no sistema, com a evidência EV-<id> e um fato por propriedade dada."""
    base["objetos"].append(
        {
            "objeto_id": objeto_id,
            "classe": classe,
            "unidade": unidade,
            "sistema": f"{unidade}-{sistema}",
        }
    )
    _evidencia(base, f"EV-{objeto_id}")
    _fato(base, objeto_id, "rotulo", objeto_id, f"EV-{objeto_id}")
    for propriedade, valor in fatos.items():
        _fato(base, objeto_id, propriedade, valor, f"EV-{objeto_id}")


def _servico(
    base: dict,
    servico_id: str,
    saida: str,
    valor: float,
    codigo_eap,
    servicos_eap,
    unidade="m²",
    chave="pista",
) -> None:
    base["servicos"].append(
        {
            "servico_id": servico_id,
            "objeto_id": "RV-1",
            "regra": "vala_rede",
            "versao_regra": "1",
            "saida": saida,
            "chave": chave,
            "valor": valor,
            "unidade": unidade,
            "fatos": ["RV-1.de_mm"],
            "servicos_eap": servicos_eap,
            "codigo_eap": codigo_eap,
        }
    )


def _quantidade(itens: list[dict], codigo: str, grandeza: str) -> dict:
    return next(q for q in itens if q["codigo"] == codigo and q["grandeza"] == grandeza)


def _folha(resultado: dict, folha_id: str) -> dict:
    return next(
        f
        for t in resultado["tipos"].values()
        for e in t["etapas"]
        for f in e["folhas"]
        if f["id"] == folha_id
    )


@pytest.fixture
def base() -> dict:
    b = _base()
    _elemento(b, "e1", "estaca", "u1", "ACT600", comprimento_m=10.0)
    _elemento(b, "e2", "estaca", "u1", "ACT600", comprimento_m=12.5)
    _elemento(b, "e3", "estaca", "u1", "FILTROS", comprimento_m=8.0)
    _elemento(b, "b1", "bloco", "u1", "ACT600", area_planta_m2=2.25)
    _elemento(b, "c1", "cava", "u1", "ACT600", escavacao_m3=100.0, reaterro_m3=40.0)
    _elemento(b, "c2", "cava", "u1", "FILTROS", escavacao_m3=50.5, reaterro_m3=20.0)
    _elemento(b, "t1", "trecho", "u2", "AAT00", extensao_m=500.0)
    _elemento(b, "t2", "trecho", "u2", "AAT00", extensao_m=250.5)
    return b


def test_itens_tecnicos_leem_os_fatos_por_sistema(base):
    itens = ep.itens_tecnicos(base)
    comprimento = _quantidade(itens, "U1.ACT600.GEO.FUN.EST", "comprimento")
    assert comprimento["quantidade"] == pytest.approx(22.5)
    assert comprimento["unidade"] == "m" and comprimento["origem"] == "fatos"
    assert comprimento["objetos"] == ["e1", "e2"]
    assert comprimento["fatos"] == ["e1.comprimento_m", "e2.comprimento_m"]
    assert _quantidade(itens, "U1.ACT600.GEO.FUN.EST", "quantidade")["quantidade"] == 2
    assert _quantidade(itens, "U1.FILTROS.GEO.FUN.EST", "comprimento")[
        "quantidade"
    ] == pytest.approx(8.0)
    assert _quantidade(itens, "U1.ACT600.GEO.FUN.BLO", "área em planta")[
        "quantidade"
    ] == pytest.approx(2.25)
    assert _quantidade(itens, "U2.AAT00.HID.TUB.RED", "extensão")[
        "quantidade"
    ] == pytest.approx(750.5)


def test_cava_vira_escavacao_e_reaterro_por_sistema(base):
    itens = ep.itens_tecnicos(base)
    assert _quantidade(itens, "U1.ACT600.GEO.MOV.ESC", "volume")[
        "quantidade"
    ] == pytest.approx(100.0)
    assert _quantidade(itens, "U1.FILTROS.GEO.MOV.ESC", "volume")[
        "quantidade"
    ] == pytest.approx(50.5)
    assert _quantidade(itens, "U1.ACT600.GEO.MOV.REA", "volume")[
        "quantidade"
    ] == pytest.approx(40.0)


def test_cada_quantidade_cita_fatos_e_evidencias_com_documento_e_pagina(base):
    q = _quantidade(ep.itens_tecnicos(base), "U1.ACT600.GEO.FUN.EST", "comprimento")
    assert q["evidencias"] == [
        {"evidencia_id": "EV-e1", "documento": DOC_ID, "pagina": 3},
        {"evidencia_id": "EV-e2", "documento": DOC_ID, "pagina": 3},
    ]


def test_contagem_cita_o_fato_de_identificacao(base):
    q = _quantidade(ep.itens_tecnicos(base), "U1.ACT600.GEO.FUN.EST", "quantidade")
    assert q["fatos"] == ["e1.rotulo", "e2.rotulo"] and len(q["evidencias"]) == 2


def test_objeto_sem_o_fato_conta_em_sem_valor_e_nao_soma(base):
    _elemento(base, "e4", "estaca", "u1", "ACT600")
    q = _quantidade(ep.itens_tecnicos(base), "U1.ACT600.GEO.FUN.EST", "comprimento")
    assert (
        q["quantidade"] == pytest.approx(22.5)
        and q["sem_valor"] == 1
        and q["n_com_valor"] == 2
    )


def test_unidade_e_sistema_vem_dos_fatos_quando_o_objeto_nao_os_traz():
    b = _base()
    b["objetos"].append({"objeto_id": "e1", "classe": "estaca"})
    _evidencia(b, "EV-e1")
    for propriedade, valor in (
        ("unidade", "u1"),
        ("sistema", "ACT600"),
        ("comprimento_m", 9.0),
    ):
        _fato(b, "e1", propriedade, valor, "EV-e1")
    assert _quantidade(ep.itens_tecnicos(b), "U1.ACT600.GEO.FUN.EST", "comprimento")[
        "quantidade"
    ] == pytest.approx(9.0)


def test_servico_de_vala_entra_no_seu_codigo_com_os_fatos():
    b = _base()
    _evidencia(b, "EV-RV-1", {"pagina": 7})
    _fato(b, "RV-1", "de_mm", 315.0, "EV-RV-1")
    _servico(
        b,
        "RV-1:vala:demolicao_m2:pista",
        "demolicao_m2",
        100.0,
        "U2.AAT00.CIV.PAV.REC",
        ["demolicao"],
    )
    _servico(
        b,
        "RV-1:vala:demolicao_m2:calcada",
        "demolicao_m2",
        20.5,
        "U2.AAT00.CIV.PAV.REC",
        ["demolicao"],
        chave="calcada",
    )
    _servico(b, "RV-1:vala:sem_codigo", "area_x", 5.0, None, [])
    q = _quantidade(ep.itens_tecnicos(b), "U2.AAT00.CIV.PAV.REC", "demolicao_m2")
    assert q["quantidade"] == pytest.approx(120.5) and q["origem"] == "servico"
    assert sorted(q["servicos"]) == [
        "RV-1:vala:demolicao_m2:calcada",
        "RV-1:vala:demolicao_m2:pista",
    ]
    assert q["por_chave"] == {"pista": 100.0, "calcada": 20.5}
    assert q["fatos"] == ["RV-1.de_mm"] and q["evidencias"][0]["pagina"] == 7
    assert q["servicos_eap"] == ["demolicao"]


def test_servico_de_item_ja_medido_pelos_fatos_nao_soma_de_novo(base):
    _servico(
        base,
        "CAVAS:esc:C01",
        "escavacao_cava_m3",
        999.0,
        "U1.ETA.GEO.MOV.ESC",
        [],
        unidade="m³",
        chave="C01",
    )
    resultado = ep.preencher(base)
    assert [d["servico_id"] for d in resultado["servicos_descartados"]] == [
        "CAVAS:esc:C01"
    ]
    assert not [
        q for q in ep.itens_tecnicos(base) if q["codigo"] == "U1.ETA.GEO.MOV.ESC"
    ]


def test_servico_de_cava_entra_quando_os_fatos_nao_medem_o_item():
    b = _base()
    _servico(
        b,
        "CAVAS:esc:C01",
        "escavacao_cava_m3",
        321.0,
        "U1.ETA.GEO.MOV.ESC",
        [],
        unidade="m³",
        chave="C01",
    )
    assert (
        _quantidade(ep.itens_tecnicos(b), "U1.ETA.GEO.MOV.ESC", "escavacao_cava_m3")[
            "quantidade"
        ]
        == 321.0
    )


def test_folha_soma_os_itens_que_aponta_e_traz_o_codigo_da_eap_unica(base):
    estacas = _folha(ep.preencher(base), "OP.03.01")
    assert estacas["situacao"] == "preenchida"
    codigos = {q["codigo_eap"] for q in estacas["quantidades"]}
    assert codigos == {
        "OP.03.01/U1.ACT600.GEO.FUN.EST",
        "OP.03.01/U1.FILTROS.GEO.FUN.EST",
    }
    totais = {(t["grandeza"], t["unidade"]): t["quantidade"] for t in estacas["totais"]}
    assert (
        totais[("comprimento", "m")] == pytest.approx(30.5)
        and totais[("quantidade", "un")] == 3
    )


def test_obra_linear_nao_recebe_quantidade_da_unidade_localizada(base):
    resultado = ep.preencher(base)
    assert (
        _folha(resultado, "OP.07.01")["situacao"] == "a preencher"
    )  # a rede é da unidade U2, de obra linear
    assert _folha(resultado, "OL.04.02")["totais"] == [
        {"grandeza": "extensão", "unidade": "m", "quantidade": 750.5}
    ]


def test_folha_sem_nada_fica_a_preencher_e_a_obrigatoria_e_listada(base):
    resultado = ep.preencher(base)
    assert _folha(resultado, "OP.04.04")["situacao"] == "a preencher"
    assert (
        "OP.04.04"
        in resultado["completude"]["obra_localizada"]["obrigatorias_a_preencher"]
    )


def test_contrato_declarado_nao_soma_com_o_medido(base):
    for k, (folha, quantidade) in enumerate(
        (("OP.03.01", 99.0), ("OP.04.04", 7.0), ("OP.04.06", None))
    ):
        oid = f"c211-{k}"
        base["objetos"].append({"objeto_id": oid, "classe": "item_contrato"})
        _evidencia(
            base,
            f"EV-{oid}",
            {"aba": "CUSTO CIVIL", "linha": 5 + k},
            documento="planilha1",
        )
        _fato(base, oid, "folha_eap", folha, f"EV-{oid}")
        _fato(base, oid, "unidade_medida", "UN", f"EV-{oid}")
        if quantidade is not None:
            _fato(base, oid, "quantidade", quantidade, f"EV-{oid}")
    resultado = ep.preencher(base)
    medida_e_declarada = _folha(resultado, "OP.03.01")
    assert medida_e_declarada["situacao"] == "preenchida"
    assert {(t["grandeza"], t["quantidade"]) for t in medida_e_declarada["totais"]} == {
        ("comprimento", 30.5),
        ("quantidade", 3.0),
    }
    assert medida_e_declarada["declaradas"][0]["quantidade"] == 99.0
    so_declarada = _folha(resultado, "OP.04.04")
    assert so_declarada["situacao"] == "declarada" and so_declarada["quantidades"] == []
    assert so_declarada["declaradas"][0]["evidencias"] == [
        {
            "evidencia_id": "EV-c211-1",
            "documento": "planilha1",
            "pagina": None,
            "aba": "CUSTO CIVIL",
            "linha": 6,
        }
    ]
    sem_quantidade = _folha(resultado, "OP.04.06")
    assert (
        sem_quantidade["situacao"] == "a preencher"
        and sem_quantidade["declaradas"][0]["quantidade"] is None
    )


def test_contrato_em_folha_fora_do_modelo_e_listado(base):
    base["objetos"].append({"objeto_id": "c211-9", "classe": "item_contrato"})
    _evidencia(base, "EV-c211-9", {"aba": "X", "linha": 1})
    _fato(base, "c211-9", "folha_eap", "OP.99.99", "EV-c211-9")
    assert ep.preencher(base)["contrato_sem_folha"] == ["OP.99.99"]


def test_servico_pedido_pelo_nome_nao_conta_de_novo_na_folha_do_item_inteiro():
    b = _base()
    _servico(b, "s1", "demolicao_m2", 100.0, "U2.AAT00.CIV.PAV.REC", ["demolicao"])
    _servico(b, "s2", "recomposicao_m2", 80.0, "U2.AAT00.CIV.PAV.REC", ["recomposicao"])
    resultado = ep.preencher(b)
    assert [t["grandeza"] for t in _folha(resultado, "OL.02.02")["totais"]] == [
        "demolicao_m2"
    ]
    assert [t["grandeza"] for t in _folha(resultado, "OL.08.01")["totais"]] == [
        "recomposicao_m2"
    ]


def test_completude_conta_folhas_por_tipo(base):
    c = ep.preencher(base)["completude"]
    localizada = c["obra_localizada"]
    assert (
        localizada["folhas"]
        == localizada["preenchida"]
        + localizada["declarada"]
        + localizada["a preencher"]
    )
    assert (
        localizada["preenchida"] == 4
    )  # estacas, blocos, escavação e reaterro (a rede U2 é linear)
    assert c["obra_linear"]["folhas"] == 32 and c["obra_linear"]["preenchida"] >= 1
    assert localizada["pct_preenchidas"] == round(
        100.0 * localizada["preenchida"] / localizada["folhas"], 1
    )


def test_quantidade_medida_sempre_cai_em_alguma_folha(base):
    assert ep.preencher(base)["quantidades_sem_folha"] == []


def test_preencher_e_deterministico(base):
    assert json.dumps(ep.preencher(base), sort_keys=True) == json.dumps(
        ep.preencher(base), sort_keys=True
    )


def test_paridade_sem_diferenca(base):
    golden = {
        "quantidades": {
            "U1.ACT600.GEO.FUN.EST|comprimento": {"quantidade": 22.5, "unidade": "m"},
            "U1.ACT600.GEO.MOV.ESC|volume": {"quantidade": 100.0005, "unidade": "m³"},
        }
    }
    assert ep.paridade(ep.itens_tecnicos(base), golden) == []


def test_paridade_aponta_diferenca_unidade_e_falta(base):
    golden = {
        "quantidades": {
            "U1.ACT600.GEO.FUN.EST|comprimento": {"quantidade": 22.6, "unidade": "m"},
            "U1.ACT600.GEO.FUN.EST|quantidade": {"quantidade": 2.0, "unidade": "m"},
            "U1.ZZZ.GEO.FUN.EST|quantidade": {"quantidade": 1.0, "unidade": "un"},
        }
    }
    problemas = ep.paridade(ep.itens_tecnicos(base), golden)
    assert len(problemas) == 3
    assert "22.5" in problemas[0] and "unidade m no lugar" not in problemas[0]
    assert "unidade un no lugar de m" in problemas[1]
    assert "falta nas gavetas" in problemas[2]


def test_paridade_aceita_a_secao_ou_o_dicionario_de_quantidades(base):
    q = {"U1.ACT600.GEO.FUN.EST|quantidade": {"quantidade": 2.0, "unidade": "un"}}
    itens = ep.itens_tecnicos(base)
    assert ep.paridade(itens, q) == ep.paridade(itens, {"quantidades": q}) == []


def test_rotulos_de_escavacao_e_reaterro_chegam_as_gavetas_pela_extracao():
    """A lacuna que a F3 achou: 'Escavação (m³)' e 'Reaterro (m³)' da cava não viravam fato."""
    utm = [
        [500100.0, 7000000.0],
        [500110.0, 7000000.0],
        [500110.0, 7000010.0],
        [500100.0, 7000010.0],
        [500100.0, 7000000.0],
    ]
    lon, lat = geo.para_lonlat(np.asarray(utm)[:, 0], np.asarray(utm)[:, 1], 31982)
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [np.column_stack([lon, lat]).tolist()],
        },
        "properties": {
            "id": "u1-ETA-cava-C01",
            "rotulo": "C01",
            "classe": "cava",
            "unidade": "u1",
            "sistema": "u1-ETA",
            "etapa": None,
            "fonte": "escavação calculada (camadas.escavacao)",
            "atributos": [["Escavação (m³)", 321.5], ["Reaterro (m³)", 100.25]],
        },
    }
    base = gc.de_construtivos({"geojson": {"features": [feature]}}, [], {}, 31982)
    assert gavetas.conferir_base(base) == []
    itens = ep.itens_tecnicos(base)
    assert _quantidade(itens, "U1.ETA.GEO.MOV.ESC", "volume")[
        "quantidade"
    ] == pytest.approx(321.5)
    assert _quantidade(itens, "U1.ETA.GEO.MOV.REA", "volume")[
        "quantidade"
    ] == pytest.approx(100.25)


def test_area_do_bloco_nao_perde_precisao_na_extracao():
    """A soma das áreas arredondadas a 1e-3 por bloco estourava a tolerância da paridade (1e-3 na soma)."""
    utm = [
        [500100.0, 7000000.0],
        [500100.7, 7000000.0],
        [500100.7, 7000000.9],
        [500100.0, 7000000.9],
        [500100.0, 7000000.0],
    ]
    medidas = gc._medidas({"type": "Polygon"}, [np.asarray(utm)])
    assert medidas["area_planta_m2"] == pytest.approx(0.63, abs=1e-9)


def test_principal_imprime_completude_e_paridade(base, tmp_path, capsys):
    pasta = tmp_path / "obra"
    gavetas.gravar(pasta / "base", base)
    golden = tmp_path / "golden.json"
    golden.write_text(
        json.dumps(
            {
                "eap": {
                    "quantidades": {
                        "U1.ACT600.GEO.FUN.EST|quantidade": {
                            "quantidade": 2.0,
                            "unidade": "un",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert ep.principal([str(pasta), "--golden", str(golden)]) == 0
    saida = capsys.readouterr().out
    assert (
        "obra_localizada" in saida
        and "obra_linear" in saida
        and "1 de 1 quantidades batem" in saida
    )
    golden.write_text(
        json.dumps(
            {
                "eap": {
                    "quantidades": {
                        "U1.ACT600.GEO.FUN.EST|quantidade": {
                            "quantidade": 3.0,
                            "unidade": "un",
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert ep.principal([str(pasta), "--golden", str(golden)]) == 1
    assert "DIFERE" in capsys.readouterr().out


def test_metadados():
    m = ep.metadados()
    assert m["modulo"] == "eap_preencher" and m["funcoes"] == [
        "itens_tecnicos",
        "preencher",
        "paridade",
        "metadados",
    ]
    assert m["tolerancia_paridade"] == 1e-3
