"""F5b-E1: folha pela unidade (U1 → OP, U2 → OL), quantidade calculada do contrato e Relação de Materiais na EAP única."""

import json

import openpyxl
import pytest

from camadas import contrato_211 as c211
from camadas import eap_preencher as ep
from camadas import extrair_gavetas, gavetas
from camadas import gavetas_contrato as gc

SENTINELA = 987654.321
DOC = "doc1"

# (A, B, C, D, E, I)
CUSTO = [
    ("UNIDADE 1 - ETA Teste", None, None, None, None, None),  # linha 3
    ("1", None, "INTERLIGAÇÕES", None, None, None),  # 4
    (None, "DI", "ADMINISTRAÇÃO LOCAL DA OBRA", "MÊS", 18, None),  # 5
    (None, "161301", "LIMPEZA DE OBRA LINEAR", "M", None, None),  # 6
    ("UNIDADE 02 - AAT06 / ANEIS", None, None, None, None, None),  # 7
    ("2", None, "ADUTORA", None, None, None),  # 8
    (None, "DI", "ADMINISTRAÇÃO LOCAL DA OBRA", "MÊS", 12, None),  # 9
]
LINHA_ALO_U1, LINHA_LIMPEZA, LINHA_ALO_U2 = 5, 6, 9

CABECALHO_MAT = [
    "Item",
    "Sequência de estoque",
    "Local",
    "Material",
    "Descrição",
    "Unidade",
    "Quantidade\n1ª etapa",
    "Quantidade\n2ª etapa",
    "VALOR UNITÁRIO",
    "subcategoria",
]
# (seq, local, descrição, unidade, q1, q2, subcategoria)
MATERIAIS = [
    ("1", "ETA VILA C", "CURVA FD JE 2GS BB 45 DN1000", "PÇ", 3, 2, "conexao"),  # rel-2
    (
        "2",
        "AAT 06",
        "VALVULA BORBOLETA BIEXCENTRICA FD DN600",
        "UN",
        1,
        None,
        "valvula",
    ),  # rel-3
    ("3", "ETA VILA C", "TUBO FD K-9 PP (6,8M) DN1000", "m", 6.5, 0, "tubo"),  # rel-4
    ("4", "ETA VILA C", "GUARDA CORPO PRFV", "M", 10, None, "#N/A"),  # rel-5
    (
        "5",
        "LOCAL NOVO",
        "CURVA FD JE 2GS BB 45 DN800",
        "PÇ",
        1,
        None,
        "conexao",
    ),  # rel-6
    (
        "6",
        "ETA VILA C",
        "EXTREMIDADE FD PF 700MM COM ABA DN1200",
        "PÇ",
        4,
        1,
        "conexao",
    ),  # rel-7 (cadastro)
    ("7", "AAT 06", "CURVA FD JE 2GS BB 90 DN600", "PC", 2, 2, "conexao"),  # rel-8
    (
        "8",
        "ETA VILA C",
        "TUBO ESPECIAL ACO CARBONO DN250",
        "PÇ",
        46054,
        None,
        "#N/A",
    ),  # rel-9 (serial de data)
    (
        "9",
        "ETA VILA C",
        "KIT PARAFUSO PORCA ARRUELA FLANGE",
        "UN",
        8,
        None,
        "fixacao",
    ),  # rel-10 (sem folha)
]


@pytest.fixture
def planilha(tmp_path):
    caminho = tmp_path / "contrato.xlsx"
    livro = openpyxl.Workbook()
    ws = livro.active
    ws.title = "CUSTO CIVIL"
    ws.append(["SANEPAR - TESTE"])
    ws.append(
        [
            "ITEM",
            "COMPOSIÇÃO",
            "DESCRIÇÃO",
            "UNID.",
            "QUANT.",
            "VALOR UNITÁRIO",
            "VALOR TOTAL",
            None,
            "PROJETO",
        ]
    )
    for a, b, c, d, e, i in CUSTO:
        ws.append([a, b, c, d, e, SENTINELA, SENTINELA, None, i])
    rel = livro.create_sheet("Relação de Materiais")
    rel.append(CABECALHO_MAT)
    for k, (seq, local, desc, un, q1, q2, sub) in enumerate(MATERIAIS, start=1):
        rel.append([k, seq, local, "FOFO", desc, un, q1, q2, SENTINELA, sub])
    livro.save(caminho)
    return caminho


def _documento() -> dict:
    return {
        "documento_id": DOC,
        "arquivo": "contrato.xlsx",
        "sha256": DOC,
        "extensao": ".xlsx",
        "classe": "planilha",
        "paginas": 1,
    }


@pytest.fixture
def base(planilha):
    b = gc.juntar(gc.de_contrato(planilha, DOC), gc.de_materiais(planilha, DOC))
    b["documentos"].append(_documento())
    return b


def _resultados(planilha, calculadas: dict[int, tuple[float, str, str]]) -> list[dict]:
    """Resultados do `quantificar` fabricados para as linhas dadas ({linha: (quantidade, unidade, situação)})."""
    saida = []
    for linha in c211.classificar(c211.ler_custo_civil(planilha, "CUSTO CIVIL")):
        quantidade, unidade, situacao = calculadas.get(
            linha["linha"], (None, None, "a preencher")
        )
        saida.append(
            {
                **linha,
                "quantidade_calculada": quantidade,
                "unidade_calculada": unidade,
                "situacao": situacao,
                "motivo": None,
                "conferencia": None,
                "evidencias": [
                    {"tipo": "trecho_da_uc", "id": "T1", "valor": 246.3, "unidade": "m"}
                ]
                if quantidade is not None
                else [],
                "premissas": [
                    {"nome": "folga", "valor": 0, "unidade": "m", "estado": "calibrar"}
                ]
                if quantidade is not None
                else [],
            }
        )
    return saida


def _fatos(base: dict, objeto_id: str) -> dict:
    return {f["propriedade"]: f for f in base["fatos"] if f["objeto_id"] == objeto_id}


def _folha(resultado: dict, folha_id: str) -> dict:
    return next(
        f
        for t in resultado["tipos"].values()
        for e in t["etapas"]
        for f in e["folhas"]
        if f["id"] == folha_id
    )


# --------------------------------------------------------------------------------------------------------------------
# 1. folha pela unidade
# --------------------------------------------------------------------------------------------------------------------


def test_unidade_da_linha_le_o_titulo_da_unidade_de_obra():
    assert c211.unidade_da_linha({"unidade_obra": "UNIDADE 1 - ETA Vila C"}) == "u1"
    assert c211.unidade_da_linha({"unidade_obra": "UNIDADE 02 - AAT06 / ANEIS"}) == "u2"
    assert c211.unidade_da_linha({"unidade_obra": None}) is None


def test_alo_da_u2_vai_para_a_folha_linear_e_a_da_u1_fica_na_localizada(planilha):
    linhas = c211.classificar(c211.ler_custo_civil(planilha, "CUSTO CIVIL"))
    folha = {linha["linha"]: linha["folha_eap"] for linha in linhas}
    assert folha[LINHA_ALO_U1] == "OP.00.01"
    assert folha[LINHA_ALO_U2] == "OL.00.01"
    assert folha[LINHA_LIMPEZA] == "OP.12.01"  # U1 continua na obra localizada


def test_folha_sem_par_na_obra_linear_fica_como_esta():
    de_para = c211.DE_PARA
    assert c211.folha_da_unidade("OP.02.06", "u2", de_para) == "OP.02.06"
    assert c211.folha_da_unidade("OP.07.02", "u2", de_para) == "OL.07.03"
    assert c211.folha_da_unidade("OP.07.02", "u1", de_para) == "OP.07.02"
    assert c211.folha_da_unidade(None, "u2", de_para) is None


def test_equivalencia_so_aponta_folhas_que_existem_nos_dois_modelos():
    folhas = {
        tipo: {f["id"] for e in m["etapas"] for f in e["folhas"]}
        for tipo, m in ep.PADRAO["tipos"].items()
    }
    tabela = c211.DE_PARA["equivalencia_obra_linear"]["folhas"]
    assert set(tabela) <= folhas["obra_localizada"]
    assert set(tabela.values()) <= folhas["obra_linear"]
    assert len(set(tabela.values())) == len(tabela)  # duas OP nunca caem na mesma OL


def test_alo_nas_gavetas_declara_a_folha_da_unidade(base):
    u1, u2 = _fatos(base, "c211-custo-civil-5"), _fatos(base, "c211-custo-civil-9")
    assert (u1["unidade"]["valor"], u1["folha_eap"]["valor"]) == ("u1", "OP.00.01")
    assert (u2["unidade"]["valor"], u2["folha_eap"]["valor"]) == ("u2", "OL.00.01")
    resultado = ep.preencher(base)
    assert _folha(resultado, "OP.00.01")["totais_declaradas"] == [
        {"unidade": "mês", "quantidade": 18.0}
    ]
    assert _folha(resultado, "OL.00.01")["totais_declaradas"] == [
        {"unidade": "mês", "quantidade": 12.0}
    ]
    assert _folha(resultado, "OL.00.01")["situacao"] == "declarada"


# --------------------------------------------------------------------------------------------------------------------
# 2. calculada do contrato
# --------------------------------------------------------------------------------------------------------------------


def test_aplicar_calculadas_grava_fatos_calculados_com_regra_e_evidencia(
    planilha, base
):
    resultados = _resultados(planilha, {LINHA_LIMPEZA: (246.3, "m", "calculada")})
    nova = gc.aplicar_calculadas(base, resultados)
    fatos = _fatos(nova, "c211-custo-civil-6")
    assert (
        fatos["quantidade_calculada"]["valor"] == 246.3
        and fatos["unidade_calculada"]["valor"] == "m"
    )
    assert fatos["regra_calculo"]["valor"] == "soma_trechos"
    assert {fatos[p]["natureza"] for p in gc.PROPRIEDADES_CALCULO} == {"calculado"}
    evidencia = next(
        e
        for e in nova["evidencias"]
        if e["evidencia_id"] == "EV-c211-custo-civil-6-calc"
    )
    assert evidencia["executor"] == "código" and evidencia["documento"] == DOC
    assert evidencia["localizador"] == {
        "aba": "CUSTO CIVIL",
        "linha": 6,
        "regra": "soma_trechos",
    }
    assert (
        "soma_trechos" in evidencia["trecho"]
        and "T1" in evidencia["trecho"]
        and "folga" in evidencia["trecho"]
    )
    assert gavetas.conferir_base(nova) == []
    pendentes = {
        p["objeto_id"]
        for p in nova["pendencias"]
        if p["motivo"] == gc.PENDENCIA_A_CALCULAR
    }
    assert "c211-custo-civil-6" not in pendentes  # calculada: a pendência sai


def test_linha_sem_quantidade_calculada_nao_ganha_fato(planilha, base):
    nova = gc.aplicar_calculadas(base, _resultados(planilha, {}))
    assert not [f for f in nova["fatos"] if f["propriedade"] in gc.PROPRIEDADES_CALCULO]


def test_aplicar_calculadas_e_idempotente_e_troca_o_que_deixou_de_valer(planilha, base):
    resultados = _resultados(planilha, {LINHA_LIMPEZA: (246.3, "m", "calculada")})
    uma = gc.aplicar_calculadas(base, resultados)
    assert gc.aplicar_calculadas(uma, resultados) == uma
    outra = gc.aplicar_calculadas(
        uma, _resultados(planilha, {LINHA_LIMPEZA: (300.0, "m", "calculada")})
    )
    assert _fatos(outra, "c211-custo-civil-6")["quantidade_calculada"]["valor"] == 300.0
    assert len(outra["fatos"]) == len(uma["fatos"])
    sem = gc.aplicar_calculadas(uma, _resultados(planilha, {}))
    assert not [f for f in sem["fatos"] if f["propriedade"] in gc.PROPRIEDADES_CALCULO]
    assert not [e for e in sem["evidencias"] if e["evidencia_id"].endswith("-calc")]


def test_folha_calculada_pelo_contrato_cita_linha_e_regra(planilha, base):
    nova = gc.aplicar_calculadas(
        base, _resultados(planilha, {LINHA_LIMPEZA: (246.3, "m", "calculada")})
    )
    folha = _folha(ep.preencher(nova), "OP.12.01")
    assert folha["situacao"] == "calculada" and folha["quantidades"] == []
    assert folha["totais_calculadas_contrato"] == [
        {"unidade": "m", "quantidade": 246.3}
    ]
    linha = folha["calculadas_contrato"][0]
    assert linha["regra"] == "soma_trechos" and linha["completa"] is True
    citacao = next(e for e in linha["evidencias"] if "regra" in e)
    assert (citacao["aba"], citacao["linha"], citacao["regra"]) == (
        "CUSTO CIVIL",
        6,
        "soma_trechos",
    )
    assert "T1" in citacao["trecho"]


def test_sem_o_calculo_a_folha_segue_a_preencher(base):
    assert _folha(ep.preencher(base), "OP.12.01")["situacao"] == "a preencher"


def test_parcial_ou_declarada_conferida_nao_fecha_a_folha_como_calculada(
    planilha, base
):
    nova = gc.aplicar_calculadas(
        base, _resultados(planilha, {LINHA_LIMPEZA: (100.0, "m", "parcial")})
    )
    folha = _folha(ep.preencher(nova), "OP.12.01")
    assert (
        folha["situacao"] == "a preencher"
    )  # o parcial aparece na folha, sem fechá-la
    assert (
        folha["calculadas_contrato"][0]["completa"] is False
        and folha["totais_calculadas_contrato"] == []
    )
    conferida = gc.aplicar_calculadas(
        base,
        _resultados(planilha, {LINHA_ALO_U1: (18.0, "mês", "declarada · confere")}),
    )
    assert _folha(ep.preencher(conferida), "OP.00.01")["situacao"] == "declarada"


def test_precedencia_medido_calculada_declarada_sem_somar(planilha, base):
    """OP.12.01 recebe o calculado do contrato e, de outra linha, uma declarada: a calculada manda e nada se soma;
    com um serviço medido no mesmo código, a medida manda sobre as duas."""
    nova = gc.aplicar_calculadas(
        base, _resultados(planilha, {LINHA_LIMPEZA: (246.3, "m", "calculada")})
    )
    nova["objetos"].append({"objeto_id": "extra", "classe": "item_contrato"})
    nova["evidencias"].append(
        {
            "evidencia_id": "EV-extra",
            "classe": "planilha",
            "documento": DOC,
            "localizador": {"aba": "CUSTO CIVIL", "linha": 99},
            "metodo": "camadas.contrato_211",
            "executor": "código",
        }
    )
    for propriedade, valor in (
        ("folha_eap", "OP.12.01"),
        ("quantidade", 50.0),
        ("unidade_medida", "M"),
    ):
        nova["fatos"].append(
            {
                "fato_id": f"extra.{propriedade}",
                "objeto_id": "extra",
                "propriedade": propriedade,
                "valor": valor,
                "natureza": "projetado",
                "evidencia_id": "EV-extra",
            }
        )
    folha = _folha(ep.preencher(nova), "OP.12.01")
    assert folha["situacao"] == "calculada"
    assert folha["totais_calculadas_contrato"] == [
        {"unidade": "m", "quantidade": 246.3}
    ]
    assert folha["totais_declaradas"] == [{"unidade": "m", "quantidade": 50.0}]
    assert folha["totais"] == []  # nada do contrato entra nos totais medidos
    # medida de documento no mesmo código (GER.FIN.LIM) vence a calculada
    nova["servicos"].append(
        {
            "servico_id": "s1",
            "objeto_id": "extra",
            "regra": "r",
            "versao_regra": "1",
            "saida": "limpeza_m",
            "valor": 10.0,
            "unidade": "m",
            "fatos": [],
            "codigo_eap": "U1.ETA.GER.FIN.LIM",
            "servicos_eap": [],
        }
    )
    com_servico = _folha(ep.preencher(nova), "OP.12.01")
    assert com_servico["quantidades"] and com_servico["calculadas_contrato"]
    assert com_servico["totais_calculadas_contrato"] == [
        {"unidade": "m", "quantidade": 246.3}
    ]


# --------------------------------------------------------------------------------------------------------------------
# 3. Relação de Materiais nas folhas
# --------------------------------------------------------------------------------------------------------------------


def test_material_ganha_local_unidade_item_e_folha(base):
    curva = _fatos(base, "rel-2")
    assert curva["local"]["valor"] == "ETA VILA C" and curva["unidade"]["valor"] == "u1"
    assert (
        curva["item_tecnico"]["valor"] == "HID.TUB.VAL"
        and curva["folha_eap"]["valor"] == "OP.07.02"
    )
    assert (
        _fatos(base, "rel-3")["folha_eap"]["valor"] == "OL.07.03"
    )  # válvula da AAT: obra linear
    assert _fatos(base, "rel-4")["folha_eap"]["valor"] == "OP.07.01"  # tubo
    assert (
        _fatos(base, "rel-7")["folha_eap"]["valor"] == "OP.07.02"
    )  # termos não casam; a subcategoria do cadastro sim


def test_material_que_nao_se_resolve_vira_pendencia_com_motivo(base):
    motivos = {
        p["objeto_id"]: p["motivo"]
        for p in base["pendencias"]
        if p["objeto_id"] in ("rel-5", "rel-6")
    }
    assert (
        "folha_eap" not in _fatos(base, "rel-5") and "HID.TUB" not in motivos["rel-5"]
    )
    assert "sem folha" in motivos["rel-5"]
    assert (
        "folha_eap" not in _fatos(base, "rel-6")
        and "sem unidade de obra" in motivos["rel-6"]
    )


def test_quantidade_que_parece_data_do_excel_nao_entra_e_vira_pendencia(base):
    fatos = _fatos(base, "rel-9")
    assert (
        "quantidade_etapa1" not in fatos and fatos["folha_eap"]["valor"] == "OP.07.01"
    )
    motivos = [p["motivo"] for p in base["pendencias"] if p["objeto_id"] == "rel-9"]
    assert any("parece data do Excel (serial 46054)" in m for m in motivos)
    assert (
        _fatos(base, "rel-2")["quantidade_etapa1"]["valor"] == 3.0
    )  # inteiro pequeno segue como quantidade


def test_subcategoria_do_cadastro_que_nenhum_item_acolhe_nao_leva_folha(base):
    assert "folha_eap" not in _fatos(base, "rel-10")
    motivo = next(p["motivo"] for p in base["pendencias"] if p["objeto_id"] == "rel-10")
    assert "sem folha" in motivo


def test_sem_contrato_tira_objetos_fatos_evidencias_e_pendencias_do_contrato(
    planilha, base
):
    nova = gc.aplicar_calculadas(
        base, _resultados(planilha, {LINHA_LIMPEZA: (246.3, "m", "calculada")})
    )
    limpa = gc.sem_contrato(nova)
    assert not [o for o in limpa["objetos"] if o["classe"] in gc.CLASSES_DO_CONTRATO]
    assert not limpa["fatos"] and not limpa["evidencias"] and not limpa["pendencias"]
    refeita = extrair_gavetas._substituir(
        limpa, gc.de_contrato(planilha, DOC), gc.de_materiais(planilha, DOC)
    )
    assert {f["fato_id"] for f in refeita["fatos"]} == {
        f["fato_id"] for f in base["fatos"]
    }


def test_materiais_somam_etapa1_mais_etapa2_por_unidade_na_folha(base):
    resultado = ep.preencher(base)
    conexoes_u1 = _folha(resultado, "OP.07.02")
    assert {
        (t["unidade"], t["quantidade"]) for t in conexoes_u1["totais_declaradas"]
    } == {("un", 10.0)}  # (3+2)+(4+1)
    assert conexoes_u1["situacao"] == "declarada" and conexoes_u1["quantidades"] == []
    curva = next(d for d in conexoes_u1["declaradas"] if d["objeto_id"] == "rel-2")
    assert (
        curva["quantidade"] == 5.0
        and curva["classe"] == "item_material"
        and curva["unidade_medida"] == "PÇ"
    )
    assert {fid.split(".")[1] for fid in curva["fatos"]} == {
        "folha_eap",
        "quantidade_etapa1",
        "quantidade_etapa2",
    }
    assert (
        curva["evidencias"][0]["aba"] == "Relação de Materiais"
        and curva["evidencias"][0]["linha"] == 2
    )
    conexoes_u2 = _folha(resultado, "OL.07.03")
    assert {
        (t["unidade"], t["quantidade"]) for t in conexoes_u2["totais_declaradas"]
    } == {("un", 5.0)}  # 1 + (2+2)
    tubos = _folha(resultado, "OP.07.01")
    assert tubos["totais_declaradas"] == [{"unidade": "m", "quantidade": 6.5}]


def test_material_declarado_nunca_soma_com_o_medido(base):
    base["objetos"].append(
        {"objeto_id": "t1", "classe": "trecho", "unidade": "u2", "sistema": "u2-AAT00"}
    )
    base["evidencias"].append(
        {
            "evidencia_id": "EV-t1",
            "classe": "projeto",
            "documento": DOC,
            "localizador": {"pagina": 1},
            "metodo": "x",
            "executor": "código",
        }
    )
    base["fatos"].append(
        {
            "fato_id": "t1.extensao_m",
            "objeto_id": "t1",
            "propriedade": "extensao_m",
            "valor": 100.0,
            "natureza": "projetado",
            "evidencia_id": "EV-t1",
        }
    )
    base["documentos"][0]["paginas"] = 1
    folha = _folha(ep.preencher(base), "OL.04.02")
    assert folha["situacao"] == "preenchida"
    assert folha["totais"] == [
        {"grandeza": "extensão", "unidade": "m", "quantidade": 100.0}
    ]


def test_sentinela_de_preco_nunca_chega_a_eap(planilha, base):
    nova = gc.aplicar_calculadas(
        base, _resultados(planilha, {LINHA_LIMPEZA: (246.3, "m", "calculada")})
    )
    assert "987654" not in json.dumps(
        [nova, ep.preencher(nova)], ensure_ascii=False, default=str
    )


def test_unidade_do_local_pelo_conceito():
    assert gc.unidade_do_local("ETA VILA C") == "u1"
    assert gc.unidade_do_local("AAT 02 VILA A") == "u2"
    assert gc.unidade_do_local("Outro lugar") is None


# --------------------------------------------------------------------------------------------------------------------
# fechar_eap: a ordem do build e a idempotência
# --------------------------------------------------------------------------------------------------------------------


def test_fechar_eap_leva_o_calculado_a_folha_e_e_idempotente(planilha, base, tmp_path):
    out = tmp_path / "saida"
    out.mkdir()
    gavetas.gravar(out / "base", base)
    resultados = _resultados(planilha, {LINHA_LIMPEZA: (246.3, "m", "calculada")})
    log = []
    primeiro = extrair_gavetas.fechar_eap(
        {}, out, {}, log=log.append, resultados_contrato=resultados
    )
    base_1 = gavetas.ler(out / "base")
    eap_1 = (out / "eap_unica.json").read_text(encoding="utf-8")
    assert (
        primeiro["erros"] == [] and primeiro["calculadas_do_contrato"] == 1
    )  # a linha da limpeza
    assert json.loads(eap_1)["tipos"]["obra_localizada"]["completude"]["calculada"] >= 1
    folha = _folha(json.loads(eap_1), "OP.12.01")
    assert folha["situacao"] == "calculada"
    extrair_gavetas.fechar_eap(
        {}, out, {}, log=log.append, resultados_contrato=resultados
    )
    base_2 = gavetas.ler(out / "base")
    assert {g: len(base_1[g]) for g in gavetas.GAVETAS} == {
        g: len(base_2[g]) for g in gavetas.GAVETAS
    }
    assert (out / "eap_unica.json").read_text(encoding="utf-8") == eap_1
    assert (
        json.loads((out / "gavetas_escopo.json").read_text(encoding="utf-8"))["laco"][
            "roteiro"
        ]
        >= 0
    )


def test_fechar_eap_sem_base_devolve_none(tmp_path):
    assert extrair_gavetas.fechar_eap({}, tmp_path, {}, log=lambda *a: None) is None
