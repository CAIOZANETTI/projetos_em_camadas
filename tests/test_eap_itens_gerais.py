"""Itens codificados das folhas da EAP padrão que não tinham item (GER, CIV.ACA, CIV.PAV.URB, HID.TUB.*): estrutura,
validação, `classificar` com frases típicas de planilha e memorial (e com frases que NÃO devem casar) e evidência de
texto com quantidade (vb, mês, m, un)."""

import json
import re

import pytest

from camadas import eap, eap_padrao, evidencias, vocabulario

FOLHA_PARA_ITEM = {
    "OP.01.01": ["GER.PRE.MOB"],
    "OP.01.02": ["GER.PRE.TOP"],
    "OP.06.02": ["CIV.ACA.ACB"],
    "OP.10.03": ["CIV.PAV.URB"],
    "OP.11.02": ["GER.CTL.ENS"],
    "OP.11.03": ["GER.CTL.COM"],
    "OP.12.01": ["GER.FIN.LIM"],
    "OP.12.02": ["GER.FIN.CAD"],
    "OP.12.03": ["GER.FIN.DES"],
    "OL.01.01": ["GER.PRE.MOB"],
    "OL.01.02": ["GER.PRE.TOP"],
    "OL.01.03": ["GER.PRE.SIN"],
    "OL.04.04": ["HID.TUB.ANC"],
    "OL.06.01": ["HID.TUB.TRV"],
    "OL.06.02": ["HID.TUB.MND"],
    "OL.07.02": ["HID.TUB.CAM"],
    "OL.09.02": ["GER.CTL.DSF"],
    "OL.09.03": ["GER.CTL.CFT"],
    "OL.11.01": ["GER.FIN.CAD"],
    "OL.11.02": ["GER.FIN.FAI", "GER.FIN.LIM"],
    "OL.11.03": ["GER.FIN.DES"],
}
NOVOS = {i for itens in FOLHA_PARA_ITEM.values() for i in itens}


def _classificar(texto, obra=None, escopo=None):
    return evidencias.classificar(vocabulario.preparar(texto)[1], obra, escopo)


def test_estrutura_nova_valida_e_sem_duplicata():
    assert eap.validar() == []
    assert vocabulario.validar() == []
    assert eap_padrao.validar() == ([], [])
    codigos = [it["codigo"] for it in eap.GERAL]
    assert len(codigos) == len(set(codigos))
    disciplinas = {
        d["codigo"]: [p["codigo"] for p in d["pacotes"]]
        for d in eap.REGRAS["disciplinas"]
    }
    assert disciplinas["GER"] == ["PRE", "CTL", "FIN"] and "ACA" in disciplinas["CIV"]
    assert NOVOS <= set(eap.itens())
    for it in eap.GERAL:
        re.compile(it["termos"])


def test_toda_folha_do_padrao_aponta_para_item_codificado():
    folhas = {
        f["id"]: f for t in eap_padrao.TIPOS for f in eap_padrao._folhas_do_tipo(t)
    }
    assert [i for i, f in folhas.items() if not f["aponta"]] == []
    for folha, itens in FOLHA_PARA_ITEM.items():
        assert [a["item"] for a in folhas[folha]["aponta"]] == itens
        assert "observacao" not in folhas[folha]


def test_item_so_vale_para_o_tipo_de_obra_da_folha_que_o_cita():
    itens = eap.itens()
    for folha, alvos in FOLHA_PARA_ITEM.items():
        obra = "localizada" if folha.startswith("OP") else "linear"
        assert all(obra in itens[i]["obra"] for i in alvos)
    assert itens["GER.CTL.DSF"]["escopo"] == ["agua"] and itens["GER.CTL.CFT"][
        "escopo"
    ] == ["esgoto"]


def test_servicos_novos_tem_unidade_do_vocabulario():
    servicos = [
        json.loads(linha)
        for linha in (evidencias.CONCEITOS / "servicos.jsonl")
        .read_text("utf-8")
        .splitlines()
    ]
    for s in servicos:
        assert set(s["unidades"]) <= set(vocabulario.REGRAS["unidades"]), s["id"]
    assert {u for s in servicos for u in s["unidades"]} >= {"vb", "mês"}


@pytest.mark.parametrize(
    "texto, obra, item, servico",
    [
        (
            "MOBILIZACAO E DESMOBILIZACAO DE EQUIPAMENTOS",
            None,
            "GER.PRE.MOB",
            "mobilizacao",
        ),
        ("Mobilização de equipe e equipamentos", None, "GER.PRE.MOB", "mobilizacao"),
        (
            "Instalação do canteiro de obras (barracão e almoxarifado)",
            None,
            "GER.PRE.MOB",
            "canteiro",
        ),
        (
            "Placa de obra em chapa galvanizada 3,00 x 1,50 m",
            None,
            "GER.PRE.MOB",
            "placa_obra",
        ),
        (
            "Mobilização de equipamentos para escavação de cava",
            "localizada",
            "GER.PRE.MOB",
            "mobilizacao",
        ),
        ("Desmobilização do canteiro de obras", None, "GER.FIN.DES", "desmobilizacao"),
        ("DESMOBILIZACAO", None, "GER.FIN.DES", "desmobilizacao"),
        (
            "Retirada do canteiro e desmobilização",
            None,
            "GER.FIN.DES",
            "desmobilizacao",
        ),
        ("Locação topográfica da obra", None, "GER.PRE.TOP", "locacao_topografia"),
        (
            "LOCACAO E NIVELAMENTO DA REDE COLETORA",
            None,
            "GER.PRE.TOP",
            "locacao_topografia",
        ),
        (
            "Levantamento topográfico planialtimétrico",
            None,
            "GER.PRE.TOP",
            "locacao_topografia",
        ),
        (
            "Sinalização de obra com cones de sinalização e fita zebrada",
            "linear",
            "GER.PRE.SIN",
            "sinalizacao_obra",
        ),
        ("SINALIZACAO NOTURNA E DIURNA", "linear", "GER.PRE.SIN", "sinalizacao_obra"),
        (
            "Ensaios de compactação do reaterro",
            "localizada",
            "GER.CTL.ENS",
            "ensaio_tecnologico",
        ),
        (
            "Controle tecnológico do concreto",
            "localizada",
            "GER.CTL.ENS",
            "ensaio_tecnologico",
        ),
        (
            "Comissionamento e operação assistida da elevatória",
            "localizada",
            "GER.CTL.COM",
            "comissionamento",
        ),
        (
            "Teste de funcionamento das bombas",
            "localizada",
            "GER.CTL.COM",
            "comissionamento",
        ),
        (
            "Limpeza e desinfecção da adutora DN 300",
            "linear",
            "GER.CTL.DSF",
            "desinfeccao",
        ),
        (
            "Desinfecção da rede de água DN 100 a 200",
            "linear",
            "GER.CTL.DSF",
            "desinfeccao",
        ),
        (
            "Inspeção por CFTV da rede coletora",
            "linear",
            "GER.CTL.CFT",
            "inspecao_cftv",
        ),
        ("Vídeo inspeção de coletor DN 400", "linear", "GER.CTL.CFT", "inspecao_cftv"),
        ("Limpeza final da obra", None, "GER.FIN.LIM", "limpeza_final"),
        ("Limpeza geral da obra e entrega", None, "GER.FIN.LIM", "limpeza_final"),
        (
            "Limpeza e recomposição final da faixa de servidão",
            "linear",
            "GER.FIN.FAI",
            "limpeza_final",
        ),
        ("Recomposição da faixa", "linear", "GER.FIN.FAI", "recomposicao_faixa"),
        ("As built da rede coletora", None, "GER.FIN.CAD", "cadastro_as_built"),
        (
            "Cadastro técnico da adutora (AS-BUILT)",
            None,
            "GER.FIN.CAD",
            "cadastro_as_built",
        ),
        ("Cadastro técnico georreferenciado", None, "GER.FIN.CAD", "cadastro_as_built"),
        (
            "Execução de MND DN 200 PEAD",
            "linear",
            "HID.TUB.MND",
            "metodo_nao_destrutivo",
        ),
        (
            "Perfuração direcional (HDD) DN 315",
            "linear",
            "HID.TUB.MND",
            "metodo_nao_destrutivo",
        ),
        (
            "Furo direcional sob a avenida",
            "linear",
            "HID.TUB.MND",
            "metodo_nao_destrutivo",
        ),
        ("Travessia de rodovia com tubo camisa", "linear", "HID.TUB.TRV", "travessia"),
        ("Travessia de córrego DN 300", "linear", "HID.TUB.TRV", "travessia"),
        (
            "Bloco de ancoragem em concreto para curva 90 graus",
            "linear",
            "HID.TUB.ANC",
            "bloco_ancoragem",
        ),
        (
            "Ancoragem de tubulação em concreto",
            "linear",
            "HID.TUB.ANC",
            "bloco_ancoragem",
        ),
        (
            "Caixa de descarga em alvenaria DN 100",
            "linear",
            "HID.TUB.CAM",
            "caixa_camara",
        ),
        ("Câmara de ventosa", "linear", "HID.TUB.CAM", "caixa_camara"),
        ("Caixa para registro DN 150", "linear", "HID.TUB.CAM", "caixa_camara"),
        (
            "Revestimento cerâmico de paredes",
            "localizada",
            "CIV.ACA.ACB",
            "revestimento",
        ),
        (
            "Pintura látex acrílica em paredes internas",
            "localizada",
            "CIV.ACA.ACB",
            "pintura",
        ),
        (
            "Esquadrias de alumínio, portas e janelas",
            "localizada",
            "CIV.ACA.ACB",
            "esquadria",
        ),
        (
            "Cobertura metálica em telha trapezoidal",
            "localizada",
            "CIV.ACA.ACB",
            "cobertura",
        ),
        ("Telhado de fibrocimento", "localizada", "CIV.ACA.ACB", "cobertura"),
        (
            "Drenagem superficial com sarjeta e canaleta",
            "localizada",
            "CIV.PAV.URB",
            "drenagem_superficial",
        ),
        (
            "Cercamento em tela de arame galvanizado",
            "localizada",
            "CIV.PAV.URB",
            "cercamento",
        ),
        ("Paisagismo e plantio de grama", "localizada", "CIV.PAV.URB", "paisagismo"),
    ],
)
def test_frase_tipica_cai_no_item_novo(texto, obra, item, servico):
    assert _classificar(texto, obra)[:2] == (item, servico)


@pytest.mark.parametrize(
    "texto, obra, item",
    [
        # o item principal da linha vence "inclusive mobilização", "inclusive ensaios" etc.
        (
            "Estaca hélice contínua D=40 cm, inclusive mobilização e desmobilização",
            "localizada",
            "GEO.FUN.EST",
        ),
        (
            "Assentamento de tubo PVC DN 200, inclusive teste de estanqueidade e desinfecção",
            "linear",
            "HID.TUB.RED",
        ),
        (
            "Escavação de vala, inclusive escoramento e ensaios de compactação",
            "linear",
            "GEO.MOV.VAL",
        ),
        (
            "Assentamento de tubo DN 200 inclusive blocos de ancoragem",
            "linear",
            "HID.TUB.RED",
        ),
        (
            "Estaca hélice contínua com mobilização de equipamentos",
            "localizada",
            "GEO.FUN.EST",
        ),
        # vocabulário que já era de outro item
        ("Reaterro compactado a 95% do Proctor normal", "localizada", "GEO.MOV.REA"),
        ("Teste hidrostático da adutora", "linear", "HID.TUB.RED"),
        ("Prova de carga em estacas", "localizada", "GEO.FUN.EST"),
        ("Recomposição de pavimento na faixa de rolamento", "linear", "CIV.PAV.REC"),
        ("Canteiro central: recomposição de meio-fio", "linear", "CIV.PAV.REC"),
        ("Calçada em concreto, recomposição", "linear", "CIV.PAV.CAL"),
        (
            "Cobertura mínima de 1,20 m sobre a geratriz do tubo",
            "linear",
            "HID.TUB.RED",
        ),
        ("Cerca de 50 m de tubo DN 200", "linear", "HID.TUB.RED"),
        ("Pintura de ligação (RR-1C)", "linear", None),
    ],
)
def test_frase_que_nao_deve_ir_para_item_novo(texto, obra, item):
    achado = _classificar(texto, obra)[0]
    assert achado not in NOVOS
    if item is not None:
        assert achado == item


@pytest.mark.parametrize(
    "texto",
    [
        "LIMPEZA",
        "Locação de caminhão basculante",
        "Cone de Abrams (slump)",
        "Cadastro de materiais Sanepar",
        "Cobertura de atendimento de esgoto",
        "Desinfecção da água tratada",
        "Porta de visita do poço",
        "Corpos de prova de concreto",
        "Entrada em operação do sistema",
    ],
)
def test_termo_solto_nao_vira_item(texto):
    item = _classificar(texto)[0]
    assert item is None or item.endswith(".*")


def test_item_de_obra_linear_nao_casa_em_obra_localizada_e_o_inverso():
    assert (
        _classificar("Inspeção por CFTV da rede coletora", "localizada")[0]
        != "GER.CTL.CFT"
    )
    assert _classificar("Execução de MND DN 200", "localizada")[0] != "HID.TUB.MND"
    assert (
        _classificar("Comissionamento e operação assistida", "linear")[0]
        != "GER.CTL.COM"
    )
    assert _classificar("Pintura látex em paredes", "linear")[0] != "CIV.ACA.ACB"
    assert (
        _classificar("Desinfecção da rede de água", "linear", "esgoto")[0]
        != "GER.CTL.DSF"
    )
    assert (
        _classificar("Inspeção por CFTV da rede coletora", "linear", "agua")[0]
        != "GER.CTL.CFT"
    )


def test_mes_e_unidade_do_vocabulario():
    assert [vocabulario.unidade_medida(t) for t in ("mês", "MES", "meses")] == [
        "mês"
    ] * 3
    assert vocabulario.quantidade(
        vocabulario.preparar("Manutenção do canteiro 12 meses")[0], []
    ) == (12.0, "mês")


@pytest.mark.parametrize(
    "linha, codigo, servico, valor, unidade",
    [
        (
            "Mobilização e desmobilização de equipamentos, 1 vb",
            "U2.*.GER.PRE.MOB",
            "mobilizacao",
            1.0,
            "vb",
        ),
        (
            "Manutenção do canteiro de obras 12 meses",
            "U2.*.GER.PRE.MOB",
            "canteiro",
            12.0,
            "mês",
        ),
        (
            "Placa de obra em chapa galvanizada, 2 un",
            "U2.*.GER.PRE.MOB",
            "placa_obra",
            2.0,
            "un",
        ),
        (
            "Desinfecção da rede de água 1.250 m",
            "U2.*.GER.CTL.DSF",
            "desinfeccao",
            1250.0,
            "m",
        ),
        (
            "Cadastro técnico (as built), 1 vb",
            "U2.*.GER.FIN.CAD",
            "cadastro_as_built",
            1.0,
            "vb",
        ),
        (
            "Perfuração direcional DN 200, 80 m",
            "U2.*.HID.TUB.MND",
            "metodo_nao_destrutivo",
            80.0,
            "m",
        ),
        (
            "Bloco de ancoragem em concreto 6 un",
            "U2.*.HID.TUB.ANC",
            "bloco_ancoragem",
            6.0,
            "un",
        ),
    ],
)
def test_texto_com_item_novo_vira_evidencia_com_quantidade(
    linha, codigo, servico, valor, unidade
):
    documento = {
        "id": "memorial.pdf",
        "tipo": "memorial",
        "nome": "Memorial",
        "unidade": "U2",
        "obra": "linear",
        "escopo": "agua",
    }
    evs = evidencias.buscar_texto(documento, [linha])
    assert len(evs) == 1
    e = evs[0]
    assert (e["codigo"], e["servico"], e["valor"], e["unidade"]) == (
        codigo,
        servico,
        valor,
        unidade,
    )
    assert evidencias.validar_evidencia(e) == []


def test_cftv_so_em_documento_de_esgoto_e_comissionamento_so_em_obra_localizada():
    esgoto = {
        "id": "m.pdf",
        "tipo": "memorial",
        "nome": "M",
        "unidade": "U2",
        "obra": "linear",
        "escopo": "esgoto",
    }
    ev = evidencias.buscar_texto(esgoto, ["Inspeção por CFTV da rede coletora 800 m"])
    assert [(e["codigo"], e["valor"], e["unidade"]) for e in ev] == [
        ("U2.*.GER.CTL.CFT", 800.0, "m")
    ]
    localizada = {
        "id": "m.pdf",
        "tipo": "memorial",
        "nome": "M",
        "unidade": "U1",
        "obra": "localizada",
        "escopo": "agua",
    }
    ev = evidencias.buscar_texto(
        localizada, ["Comissionamento e operação assistida, 1 vb"]
    )
    assert [(e["codigo"], e["valor"], e["unidade"]) for e in ev] == [
        ("U1.*.GER.CTL.COM", 1.0, "vb")
    ]
    assert (
        evidencias.buscar_texto(
            {**esgoto, "obra": "localizada"}, ["Inspeção por CFTV 800 m"]
        )
        == []
    )


def test_itens_gerais_aparecem_na_estrutura_so_no_tipo_de_obra_certo():
    de_u1 = {
        n["codigo"].split(".", 2)[2]
        for n in eap.estrutura()
        if n["codigo"].startswith("U1.") and n["nivel"] == "item"
    }
    de_u2 = {
        n["codigo"].split(".", 2)[2]
        for n in eap.estrutura()
        if n["codigo"].startswith("U2.") and n["nivel"] == "item"
    }
    assert {"GER.PRE.MOB", "GER.CTL.COM", "CIV.ACA.ACB", "CIV.PAV.URB"} <= de_u1
    assert {"GER.PRE.MOB", "GER.PRE.SIN", "HID.TUB.MND", "GER.CTL.DSF"} <= de_u2
    assert not ({"GER.CTL.COM", "CIV.ACA.ACB"} & de_u2) and "HID.TUB.MND" not in de_u1
