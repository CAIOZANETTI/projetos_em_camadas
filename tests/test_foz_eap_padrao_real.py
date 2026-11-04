"""Ciclo da primeira passada com dado real (planilha do contrato Sanepar 211/26, Foz do Iguaçu): ALO, poço de visita em
água, macromedidor × ligação predial, títulos de etapa da Sanepar e classificações corrigidas. As frases são descrições de
material ou serviço; não há preço."""

import pandas as pd
import pytest

from camadas import eap, eap_padrao, evidencias, vocabulario


def _classificar(texto, obra=None, escopo=None):
    return evidencias.classificar(vocabulario.preparar(texto)[1], obra, escopo)[:2]


def test_alo_item_servico_e_folhas_obrigatorias_nos_dois_tipos():
    assert eap.itens()["GER.PRE.ALO"]["acessorio"] is True
    for tipo, folha in (("obra_localizada", "OP.00.01"), ("obra_linear", "OL.00.01")):
        folhas = {f["id"]: f for f in eap_padrao._folhas_do_tipo(tipo)}
        assert folhas[folha]["aponta"] == [{"item": "GER.PRE.ALO"}]
        assert folhas[folha]["obrigatoria"] is True
        assert eap_padrao.TIPOS[tipo]["etapas"][0]["id"] == folha[:5]
    assert eap_padrao.validar() == ([], [])


@pytest.mark.parametrize(
    "texto",
    [
        "ADMINISTRAÇÃO LOCAL DA OBRA",
        "ADMINISTRAÇÃO LOCAL DE OBRA - ALO",
        "Administração local de obra (ALO)",
    ],
)
def test_alo_classifica(texto):
    assert _classificar(texto) == ("GER.PRE.ALO", "administracao_local")


@pytest.mark.parametrize(
    "texto",
    ["ESTACA HELICE CONTINUA, INCLUSIVE ADMINISTRACAO LOCAL", "PORTA DE ALUMINIO ALO"],
)
def test_alo_nao_pega_o_que_nao_e_alo(texto):
    assert _classificar(texto)[0] != "GER.PRE.ALO"


def test_linha_real_da_alo_vira_fato_de_mes_e_preenche_a_folha():
    """A ALO abre cada unidade na planilha: U1 (ETA, localizada) 18 meses e U2 (rede, linear) 12 meses."""
    itens = pd.DataFrame(
        {
            "aba": ["CUSTO CIVIL"] * 2,
            "descricao": ["ADMINISTRAÇÃO LOCAL DA OBRA"] * 2,
            "codigo": ["", ""],
            "unidade": ["MÊS", "MÊS"],
            "unidade_obra": ["UNIDADE 1 - ETA Vila C", "UNIDADE 2 - Adutora"],
            "quantidade": [18.0, 12.0],
            "linha_origem": [12, 300],
        }
    )
    evs = evidencias.de_planilha(itens, {"id": "contrato.xlsx", "tipo": "planilha"})
    assert [(e["codigo"], e["unidade"], e["valor"]) for e in evs] == [
        ("U1.*.GER.PRE.ALO", "mês", 18.0),
        ("U2.*.GER.PRE.ALO", "mês", 12.0),
    ]
    fatos = evidencias.consolidar(evs).to_dict("records")
    for tipo, folha, texto in (
        ("obra_localizada", "OP.00.01", "18,00 mês"),
        ("obra_linear", "OL.00.01", "12,00 mês"),
    ):
        bloco = eap_padrao.preencher(tipo, None, fatos)
        f = next(f for e in bloco["etapas"] for f in e["folhas"] if f["id"] == folha)
        assert f["situacao"] == "preenchida" and texto in f["quantidades_txt"][0]


def test_poco_de_visita_vale_para_agua_e_esgoto():
    assert eap.itens()["HID.TUB.PVS"]["escopo"] == ["agua", "esgoto"]
    for texto in (
        "POÇO DE VISITA MOS MODULO 09 DN 2000",
        "TAMPAO FD CLASSE 50 PARA POCO DE VISITA PADRAO SANEPAR",
    ):
        assert _classificar(texto, escopo="agua")[0] == "HID.TUB.PVS"
    for tipo, folha in (("obra_localizada", "OP.07.03"), ("obra_linear", "OL.07.01")):
        f = next(f for f in eap_padrao._folhas_do_tipo(tipo) if f["id"] == folha)
        assert f.get("escopo", "ambos") == "ambos"


@pytest.mark.parametrize(
    "texto",
    [
        "HIDROMETRO ULTRASSONICO Q3 400,0 M3/HORA SAIDA PULSADA/MODBUS DN200 POL 8",
        "Macromedidor eletromagnético DN 300",
        "Medidor de vazão ultrassônico DN 100",
        "HIDROMETRO WOLTMANN DN 80",
    ],
)
def test_macromedidor_vai_para_instrumentacao_e_nao_para_ligacao(texto):
    assert _classificar(texto)[0] == "ELE.FOR.INS"
    assert _classificar(texto, "linear")[0] == "ELE.FOR.INS"


@pytest.mark.parametrize(
    "texto",
    [
        'Hidrômetro 3/4" classe B',
        'HIDRÔMETRO ¾" Q3 2,5',
        "Hidrômetro DN 20 mm",
        'Hidrômetro unijato 1"',
        "Cavalete com hidrômetro",
        "Instalação de hidrômetro na ligação de água",
        "Ligação predial de água",
        "Ramal predial de esgoto",
    ],
)
def test_hidrometro_de_ligacao_continua_sendo_ligacao(texto):
    assert _classificar(texto, "linear")[0] == "HID.TUB.LIG"


def test_folha_de_macromedidores_na_obra_linear():
    f = next(
        f for f in eap_padrao._folhas_do_tipo("obra_linear") if f["id"] == "OL.07.04"
    )
    assert f["aponta"] == [{"item": "ELE.FOR.INS"}] and f["obrigatoria"] is False


@pytest.mark.parametrize(
    ("texto", "item"),
    [
        ("GRADE DE PISO PRFV VAO 0,5 X 0,6M GR 0,7 X 0,8M (IN LOCO)", "CIV.ACA.ACB"),
        (
            'TALHA MANUAL DE CORRENTE COM TROLEY - CAPACIDADE DE 2000KG MONOVIA VIGA "I" 6800 MM',
            "HID.EQP.EQU",
        ),
        ("REVESTIMENTO COM ASFALTO (TERCEIRIZADO)", "CIV.PAV.REC"),
        (
            "VALVULA ESFERA 3 VIAS DUPLA UNIAO HORIZONTAL TIPO T EM CPVC JS PN16",
            "HID.TUB.VAL",
        ),
        (
            "Válvula Direcional inline 5/2 vias monoestável; Acionamento elétrico",
            "HID.TUB.VAL",
        ),
        ("TAMPA PLASTICA PARA REGISTRO PASSEIO - TPP PADRAO SANEPAR", "HID.TUB.VAL"),
        (
            "Central de Preparação de ar comprimido, com secador por refrigeração",
            "HID.EQP.EQU",
        ),
        (
            "ESCAVAÇÃO, ESCORAMENTO, ASSENTAMENTO, REATERRO E REMOÇÃO DE PAVIMENTOS - FD DN 300",
            "GEO.MOV.VAL",
        ),
    ],
)
def test_classificacoes_corrigidas_do_dado_real(texto, item):
    assert _classificar(texto)[0] == item


@pytest.mark.parametrize(
    "texto",
    [
        "Plaquetas de identificação dos quadros, em acrílico, com fixação via rebite ou parafuso",
        "MARCADOR OVAL / PORTA MARCADOR (identificação de tubos)",
        "união passa-muro",
        "TORNEIRA PAREDE BICA RETA CORPO BRONZE LATAO CROMADA POL 3/4",
    ],
)
def test_frases_que_nao_sao_pavimento_porta_nem_parede(texto):
    assert _classificar(texto)[0] not in {"CIV.PAV.REC", "CIV.ACA.ACB", "CIV.EST.PAR"}


@pytest.mark.parametrize(
    ("texto", "item"),
    [
        ("PAREDE DE CONCRETO ARMADO", "CIV.EST.PAR"),
        ("MURO DE ARRIMO", "CIV.EST.PAR"),
        ("LAJE DE PISO", "CIV.EST.PIS"),
        ("VIGA DE CONCRETO", "CIV.EST.VIG"),
        ("RECOMPOSICAO DE PAVIMENTO EM VIAS PUBLICAS", "CIV.PAV.REC"),
        ("PORTA DE ALUMINIO", "CIV.ACA.ACB"),
        ("CALCADA DE CONCRETO", "CIV.PAV.CAL"),
    ],
)
def test_correcoes_nao_tiram_o_que_estava_certo(texto, item):
    assert _classificar(texto)[0] == item


@pytest.mark.parametrize(
    "texto", ["PORTA DE MADEIRA 0,9 X 2,1M", "PORTA DE ALUMINIO", "PORTA"]
)
def test_porta_de_verdade_continua_esquadria(texto):
    assert _classificar(texto)[0] == "CIV.ACA.ACB"


def test_titulos_sanepar_existem_em_toda_etapa_e_validar_confere_o_formato(monkeypatch):
    for meta in eap_padrao.TIPOS.values():
        for etapa in meta["etapas"]:
            assert isinstance(etapa["titulos_sanepar"], list)
    todos = {
        t
        for m in eap_padrao.TIPOS.values()
        for e in m["etapas"]
        for t in e["titulos_sanepar"]
    }
    assert {
        "SERVIÇOS PRELIMINARES",
        "SERVIÇOS FINAIS",
        "URBANIZAÇÃO",
        "BLOCOS DE ANCORAGEM",
    } <= todos
    assert "contrato Sanepar 211/26" in eap_padrao.PADRAO["metadata"]["fonte"]

    def estragar(tipos):
        tipos["obra_linear"]["etapas"][1]["titulos_sanepar"] = ["", "A"]
        tipos["obra_localizada"]["etapas"][1]["titulos_sanepar"] = "texto solto"
        del tipos["obra_localizada"]["etapas"][2][
            "titulos_sanepar"
        ]  # ausente é permitido

    copia = __import__("json").loads(
        __import__("json").dumps(eap_padrao.PADRAO["tipos"])
    )
    estragar(copia)
    monkeypatch.setattr(eap_padrao, "TIPOS", copia)
    erros = " | ".join(eap_padrao.validar()[0])
    assert erros.count("titulos_sanepar") == 2  # a ausência não é erro


# ----------------------------------------------------------------------------------------------------------------
# D10: bloco de ancoragem e bloco de apoio são um item só, HID.TUB.ANC, em qualquer unidade
# ----------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("obra", [None, "localizada", "linear"])
@pytest.mark.parametrize(
    "texto",
    [
        "BLOCO DE APOIO DE TUBULAÇÃO DN 300",
        "BLOCOS DE APOIO PARA CURVA DN 400",
        "Bloco de apoio para peça especial",
        "BLOCOS DE APOIO E ANCORAGEM",
        "BLOCO DE ANCORAGEM EM CONCRETO PARA CURVA DN 300",
    ],
)
def test_d10_bloco_de_apoio_e_de_ancoragem_casam_o_mesmo_item(texto, obra):
    assert _classificar(texto, obra)[0] == "HID.TUB.ANC"


def test_d10_bloco_de_apoio_de_equipamento_nao_e_ancoragem_de_tubulacao():
    assert _classificar("BLOCO DE APOIO DE EQUIPAMENTO")[0] != "HID.TUB.ANC"


def test_d10_item_vale_nas_duas_obras_e_a_folha_localizada_existe():
    item = eap.itens()["HID.TUB.ANC"]
    assert item["obra"] == ["localizada", "linear"] and item["acessorio"] is True
    assert "apoio" in item["nome"].lower()
    folha = next(
        f
        for f in eap_padrao._folhas_do_tipo("obra_localizada")
        if f["id"] == "OP.07.04"
    )
    assert (
        folha["aponta"] == [{"item": "HID.TUB.ANC"}] and folha["obrigatoria"] is False
    )
    linear = next(
        f for f in eap_padrao._folhas_do_tipo("obra_linear") if f["id"] == "OL.04.04"
    )
    assert linear["aponta"] == [{"item": "HID.TUB.ANC"}]  # continua
    for titulo in ("BLOCOS DE ANCORAGEM", "BLOCOS DE APOIO"):
        assert eap_padrao.etapas_do_titulo(titulo, "obra_localizada") == ["OP.07"]
        assert eap_padrao.etapas_do_titulo(titulo, "obra_linear") == ["OL.04"]
    assert eap_padrao.validar() == ([], [])


def test_d10_linha_de_bloco_de_apoio_preenche_a_folha_na_u1_e_na_u2():
    itens = pd.DataFrame(
        {
            "aba": ["CUSTO CIVIL"] * 2,
            "descricao": ["BLOCO DE APOIO DE TUBULAÇÃO DN 300"] * 2,
            "codigo": ["", ""],
            "unidade": ["UN", "UN"],
            "unidade_obra": ["UNIDADE 1 - ETA Vila C", "UNIDADE 2 - Adutora"],
            "quantidade": [6.0, 14.0],
            "linha_origem": [20, 310],
        }
    )
    evs = evidencias.de_planilha(itens, {"id": "contrato.xlsx", "tipo": "planilha"})
    assert [e["codigo"] for e in evs] == ["U1.*.HID.TUB.ANC", "U2.*.HID.TUB.ANC"]
    fatos = evidencias.consolidar(evs).to_dict("records")
    for tipo, folha, texto in (
        ("obra_localizada", "OP.07.04", "6 un"),
        ("obra_linear", "OL.04.04", "14 un"),
    ):
        bloco = eap_padrao.preencher(tipo, None, fatos)
        f = next(f for e in bloco["etapas"] for f in e["folhas"] if f["id"] == folha)
        assert f["situacao"] == "preenchida" and texto in f["quantidades_txt"][0]
