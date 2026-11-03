"""Título de etapa da planilha Sanepar: a hierarquia do CUSTO CIVIL (unidade, frente, trecho, etapa) vira as colunas
`titulo_etapa` e `titulo_trecho`; a etapa marca o localizador da evidência e alimenta o EAP padrão (citada no contrato,
item fora da etapa do título). Planilhas sintéticas, sem preço."""

import json

import pandas as pd
import pytest
from openpyxl import Workbook

from camadas import eap_padrao, evidencias, orcamento_sanepar

PRECO_F, PRECO_G = 12345.67, 99999.0
CABECALHO = [
    "ITEM",
    "COMPOSIÇÃO",
    "DESCRIÇÃO",
    "UNID.",
    "QUANT.",
    "PREÇO",
    "TOTAL",
    "OBS",
    "PROJETO",
]


def _planilha(linhas: list[tuple]):
    """Livro com a aba CUSTO CIVIL: título na linha 1, cabeçalho na 2 e `linhas` (A, B, C, D, E) a partir da 3.
    As colunas F e G levam valores de preço que nenhuma saída pode conter."""
    livro = Workbook()
    aba = livro.active
    aba.title = "CUSTO CIVIL"
    aba.append(["PLANILHA DE TESTE"])
    aba.append(CABECALHO)
    for a, b, c, d, e in linhas:
        aba.append([a, b, c, d, e, PRECO_F, PRECO_G])
    return livro


HIERARQUIA = [
    ("UNIDADE 1 - ETA Vila C", None, None, None, None),  # linha 3
    (None, None, "ADMINISTRAÇÃO LOCAL DE OBRA - ALO", None, None),  # 4
    (None, "DI", "ADMINISTRAÇÃO LOCAL DA OBRA", "MÊS", 18),  # 5
    (1, None, "FRENTE UM", None, None),  # 6
    (
        None,
        None,
        "serviços  preliminares",
        None,
        None,
    ),  # 7  etapa (caixa e espaço livres)
    (None, "020223", "LOCAÇÃO DA OBRA", "M2", None),  # 8
    (None, None, "ENTRADA DA ADUTORA", "M", None),  # 9  trecho: zera a etapa
    (None, "CVCAFD1000", "ESCAVAÇÃO, ESCORAMENTO E REATERRO", "M", None),  # 10
    (
        None,
        None,
        "RECOMPOSIÇÃO DE PAVIMENTO",
        None,
        None,
    ),  # 11 marcador que também é etapa
    (None, None, "MEDIDORES DE VAZÃO", "UNI", 3),  # 12 bloco próprio: encerra a etapa
    (
        None,
        None,
        "BLOCOS DE APOIO",
        "UNI",
        4,
    ),  # 13 linha com quantidade que é título de etapa
    (None, None, "OUTRO TRECHO", "M", None),  # 14
    (None, None, "SERVIÇOS FINAIS", None, None),  # 15
    (None, "161301", "LIMPEZA DE OBRA LINEAR", "M", None),  # 16
    (2, None, "FRENTE DOIS", None, None),  # 17 troca de frente: zera etapa e trecho
    (None, "030403", "RASPAGEM DA CAMADA VEGETAL", "M2", None),  # 18
    ("UNIDADE 02 - AAT06", None, None, None, None),  # 19
    (
        None,
        "DI",
        "ADMINISTRAÇÃO LOCAL DA OBRA",
        "MÊS",
        12,
    ),  # 20 sem título acima: unidade nova zera
]


@pytest.fixture
def custo_civil():
    return {
        l["linha_origem"]: l
        for l in orcamento_sanepar.extrair_custo_civil(_planilha(HIERARQUIA))
    }


def _titulos(linha):
    return linha["titulo_etapa"], linha["titulo_trecho"]


def test_hierarquia_unidade_frente_trecho_etapa(custo_civil):
    esperado = {
        5: ("ADMINISTRAÇÃO LOCAL DE OBRA - ALO", ""),
        8: (
            "serviços preliminares",
            "",
        ),  # o texto da planilha (espaços colapsados), sem normalizar caixa
        10: ("", "ENTRADA DA ADUTORA"),  # trecho novo: a etapa anterior não vale mais
        11: (
            "RECOMPOSIÇÃO DE PAVIMENTO",
            "ENTRADA DA ADUTORA",
        ),  # o marcador é linha e título
        12: ("", "ENTRADA DA ADUTORA"),
        13: ("BLOCOS DE APOIO", "ENTRADA DA ADUTORA"),
        16: (
            "SERVIÇOS FINAIS",
            "OUTRO TRECHO",
        ),  # etapa dentro do trecho, o trecho continua
        18: ("", ""),  # troca de frente
        20: ("", ""),  # troca de unidade
    }
    assert {n: _titulos(custo_civil[n]) for n in esperado} == esperado


def test_colunas_novas_ficam_no_fim_sem_reordenar_as_antigas():
    antigas = [
        "aba", "item", "codigo", "fonte", "descricao", "unidade", "quantidade", "unidade_obra", "grupo",
        "subgrupo", "disciplina", "material", "dn_mm", "etapa_indicada", "dn_tipo", "dn_mm_2",
        "categoria_planilha", "local", "tabela", "projeto_desenho", "etapa_fonte", "qtd_etapa1", "qtd_etapa2",
        "etapa_qtd_confere", "observacao", "linha_origem",
    ]  # fmt: skip
    assert orcamento_sanepar.COLUNAS_ESCOPO == antigas + [
        "titulo_etapa",
        "titulo_trecho",
    ]


def test_grupo_e_subgrupo_continuam_como_eram(custo_civil):
    assert custo_civil[8]["grupo"] == "UC 1 - FRENTE UM"
    assert (
        custo_civil[8]["subgrupo"] == "serviços preliminares"
    )  # o último título, de qualquer tipo
    assert (
        custo_civil[16]["subgrupo"] == "SERVIÇOS FINAIS"
    )  # mistura de etapa e trecho, como sempre


def test_mats_e_equip_fica_com_as_colunas_vazias():
    linhas = [{"aba": "MATS E EQUIP", "descricao": "x"}]
    df = pd.DataFrame(linhas).reindex(columns=orcamento_sanepar.COLUNAS_ESCOPO)
    assert df[["titulo_etapa", "titulo_trecho"]].isna().all().all()


def test_a_fonte_unica_dos_titulos_e_o_eap_padrao():
    assert eap_padrao.eh_titulo_de_etapa("  Serviços   FINAIS ")
    assert eap_padrao.eh_titulo_de_etapa("Urbanizacao")
    assert not eap_padrao.eh_titulo_de_etapa("ENTRADA DA ADUTORA DE ÁGUA BRUTA")
    assert not eap_padrao.eh_titulo_de_etapa(None)
    # título repetido em várias etapas devolve todas, só as do tipo pedido
    assert eap_padrao.etapas_do_titulo("MATERIAIS EQUIPAMENTOS", "obra_localizada") == [
        "OP.07",
        "OP.08",
    ]
    assert eap_padrao.etapas_do_titulo("ÁGUA POTÁVEL", "obra_linear") == [
        "OL.03",
        "OL.04",
        "OL.05",
    ]
    assert eap_padrao.etapas_do_titulo("ÁGUA POTÁVEL", "obra_localizada") == []


def test_nenhuma_coluna_de_preco_e_lida_nem_sai(custo_civil):
    """F e G (preço, total) não são lidas depois do cabeçalho e nenhum valor delas aparece na saída."""

    class Aba:
        def __init__(self, aba):
            self._aba, self.lidas = aba, set()

        def cell(self, linha, coluna):
            self.lidas.add((linha, coluna))
            return self._aba.cell(linha, coluna)

        def __getattr__(self, nome):
            return getattr(self._aba, nome)

    aba = Aba(_planilha(HIERARQUIA)["CUSTO CIVIL"])
    itens = orcamento_sanepar.extrair_custo_civil({"CUSTO CIVIL": aba})
    assert len(itens) == len(custo_civil)
    assert {c for linha, c in aba.lidas if linha > 2} == {1, 2, 3, 4, 5, 8, 9}
    saida = json.dumps(itens, ensure_ascii=False, default=str)
    assert str(PRECO_F) not in saida and str(PRECO_G) not in saida


# evidência ---------------------------------------------------------------------------------------------------------
DOC = {"id": "planilha.xlsx", "tipo": "planilha", "nome": "contrato"}


def _escopo(*linhas) -> pd.DataFrame:
    """escopo_itens.csv mínimo: (linha, descrição, título de etapa, unidade_obra)."""
    return pd.DataFrame(
        {
            "aba": "CUSTO CIVIL",
            "codigo": "",
            "descricao": [d for _, d, _, _ in linhas],
            "unidade": "",
            "quantidade": float("nan"),
            "unidade_obra": [u for _, _, _, u in linhas],
            "linha_origem": [n for n, _, _, _ in linhas],
            "titulo_etapa": [t for _, _, t, _ in linhas],
        }
    )


U1, U2 = "UNIDADE 1 - ETA Vila C", "UNIDADE 2 - Adutora de água tratada (AAT06/anéis)"


def test_evidencia_grava_o_titulo_de_etapa_no_localizador_sem_mudar_a_classificacao():
    com = _escopo(
        (
            8,
            "LOCAÇÃO DA OBRA COM AUXÍLIO DE EQUIPAMENTO TOPOGRÁFICO",
            "SERVIÇOS PRELIMINARES",
            U1,
        )
    )
    sem = com.assign(titulo_etapa=float("nan"))
    [ev_com], [ev_sem] = (
        evidencias.de_planilha(com, DOC),
        evidencias.de_planilha(sem, DOC),
    )
    assert ev_com["localizador"] == {
        "aba": "CUSTO CIVIL",
        "linha": 8,
        "titulo_etapa": "SERVIÇOS PRELIMINARES",
    }
    assert ev_sem["localizador"] == "CUSTO CIVIL linha 8"  # sem título, como sempre foi
    assert {k: ev_com[k] for k in ("codigo", "servico", "valor", "regra")} == {
        k: ev_sem[k] for k in ("codigo", "servico", "valor", "regra")
    }
    assert (
        evidencias.de_planilha(com.drop(columns="titulo_etapa"), DOC)[0]["localizador"]
        == "CUSTO CIVIL linha 8"
    )


def test_titulos_da_planilha_inclui_a_linha_sem_item():
    itens = _escopo(
        (
            8,
            "LOCAÇÃO DA OBRA COM AUXÍLIO DE EQUIPAMENTO TOPOGRÁFICO",
            "SERVIÇOS PRELIMINARES",
            U1,
        ),
        (9, "SONDAGEM PARA EXECUÇÃO DA REDE", "SERVIÇOS PRELIMINARES", U1),
        (10, "RASPAGEM DA CAMADA VEGETAL", "", U1),
    )
    assert evidencias.titulos_da_planilha(itens.drop(columns="titulo_etapa")) == []
    achados = evidencias.titulos_da_planilha(itens)
    assert [(a["linha"], a["item"], a["unidade"]) for a in achados] == [
        (8, "GER.PRE.TOP", "U1"),
        (9, None, "U1"),
    ]
    assert achados[1]["titulo_etapa"] == "SERVIÇOS PRELIMINARES"


# EAP padrão --------------------------------------------------------------------------------------------------------
def _linha(titulo, descricao, item, unidade="U1", linha=1):
    return {
        "unidade": unidade, "aba": "CUSTO CIVIL", "linha": linha, "titulo_etapa": titulo,
        "descricao": descricao, "item": item, "servico": "",
    }  # fmt: skip


def _etapas(bloco):
    return {e["id"]: e for e in bloco["etapas"]}


def _situacoes(bloco):
    return {f["id"]: f["situacao"] for e in bloco["etapas"] for f in e["folhas"]}


def test_a_item_da_etapa_do_titulo_nada_muda():
    linhas = [_linha("SERVIÇOS PRELIMINARES", "LOCAÇÃO DA OBRA", "GER.PRE.TOP")]
    base = eap_padrao.preencher("obra_localizada", None, {"fatos": []})
    com = eap_padrao.preencher(
        "obra_localizada", None, {"fatos": [], "titulos_etapa": linhas}
    )
    assert com == base
    assert (
        not _etapas(com)["OP.01"]["citada_no_contrato"]
        and _etapas(com)["OP.01"]["avisos_titulo"] == []
    )


def test_b_sem_item_a_etapa_fica_citada_no_contrato_sem_quantidade():
    linhas = [
        _linha(
            "URBANIZAÇÃO", "EXECUÇÃO DE GUIA DE CONCRETO PRÉ-MOLDADA", None, linha=184
        ),
        _linha(
            "URBANIZAÇÃO", "EXECUÇÃO DE GUIA DE CONCRETO PRÉ-MOLDADA", None, linha=300
        ),
        _linha("urbanização", "MURO DE ARRIMO", None, linha=301),
    ]
    base = eap_padrao.preencher("obra_localizada", None, {"fatos": []})
    bloco = eap_padrao.preencher(
        "obra_localizada", None, {"fatos": [], "titulos_etapa": linhas}
    )
    etapa = _etapas(bloco)["OP.10"]
    assert etapa["citada_no_contrato"] is True and etapa["n_linhas_citadas"] == 3
    assert etapa["exemplos_citados"] == [
        "EXECUÇÃO DE GUIA DE CONCRETO PRÉ-MOLDADA",
        "MURO DE ARRIMO",
    ]
    assert etapa["citada_txt"].startswith(
        "Citada no contrato (título «URBANIZAÇÃO»): 3 linha(s) sem item"
    )
    assert "MURO DE ARRIMO" in etapa["citada_txt"]
    assert _situacoes(bloco) == _situacoes(
        base
    )  # indicador por etapa, a folha não muda
    assert [e["citada_no_contrato"] for e in bloco["etapas"]].count(True) == 1


def test_c_item_de_outra_etapa_vira_aviso_sem_mudar_a_folha():
    linhas = [
        _linha("SERVIÇOS FINAIS", "BOMBA CENTRÍFUGA", "HID.EQP.EQU", linha=40),
        _linha("SERVIÇOS FINAIS", "BOMBA CENTRÍFUGA", "HID.EQP.EQU", linha=41),
        _linha(
            "SERVIÇOS FINAIS", "CADASTRO TÉCNICO", "GER.FIN.CAD", linha=42
        ),  # da própria etapa: nada
    ]
    base = eap_padrao.preencher("obra_localizada", None, {"fatos": []})
    bloco = eap_padrao.preencher(
        "obra_localizada", None, {"fatos": [], "titulos_etapa": linhas}
    )
    etapa = _etapas(bloco)["OP.12"]
    assert etapa["avisos_titulo"] == [
        "Item fora da etapa do título «SERVIÇOS FINAIS»: «BOMBA CENTRÍFUGA» classificada em HID.EQP.EQU (2 linhas)"
    ]
    assert not etapa["citada_no_contrato"]
    assert _situacoes(bloco) == _situacoes(base)


def test_titulo_em_mais_de_uma_etapa_basta_o_item_de_uma_delas():
    linhas = [
        _linha("MATERIAIS EQUIPAMENTOS", "REGISTRO", "HID.TUB.VAL"),  # OP.07: serve
        _linha(
            "MATERIAIS EQUIPAMENTOS", "FORNECIMENTO E MONTAGEM", None
        ),  # sem item: cita as duas
    ]
    etapas = _etapas(
        eap_padrao.preencher(
            "obra_localizada", None, {"fatos": [], "titulos_etapa": linhas}
        )
    )
    assert (
        etapas["OP.07"]["citada_no_contrato"] and etapas["OP.08"]["citada_no_contrato"]
    )
    assert etapas["OP.07"]["avisos_titulo"] == etapas["OP.08"]["avisos_titulo"] == []


def test_linha_de_unidade_do_outro_tipo_ou_titulo_sem_etapa_no_tipo_nao_conta():
    linhas = [
        _linha(
            "URBANIZAÇÃO", "GUIA", None, unidade="U2"
        ),  # U2 é linear: o padrão localizado a ignora
        _linha(
            "BLOCOS DE ANCORAGEM", "BLOCOS", None
        ),  # só a obra linear lista esse título
        _linha("ENTRADA DA ADUTORA", "GUIA", None),  # não é título de etapa
    ]
    localizada = eap_padrao.preencher(
        "obra_localizada", None, {"fatos": [], "titulos_etapa": linhas}
    )
    assert not any(e["citada_no_contrato"] for e in localizada["etapas"])
    linear = eap_padrao.preencher(
        "obra_linear", None, {"fatos": [], "titulos_etapa": linhas}
    )
    assert not any(
        e["citada_no_contrato"] for e in linear["etapas"] if e["id"] != "OL.04"
    )
    assert (
        _etapas(linear)["OL.04"]["citada_no_contrato"] is False
    )  # a linha dele é U1 (localizada)


def test_montar_apresenta_o_texto_pronto_e_serializa():
    dados = {
        "evidencias": {
            "fatos": [],
            "titulos_etapa": [_linha("URBANIZAÇÃO", "GUIA", None)],
        }
    }
    cfg = json.loads(
        (eap_padrao.CONCEITOS.parent / "exemplos" / "foz" / "obra.json").read_text(
            encoding="utf-8"
        )
    )
    resultado = eap_padrao.montar(dados, cfg)
    etapa = _etapas(
        next(t for t in resultado["tipos"] if t["tipo"] == "obra_localizada")
    )["OP.10"]
    assert "Citada no contrato" in etapa["citada_txt"]
    assert json.loads(json.dumps(resultado))["tipos"]


def test_template_do_visualizador_so_apresenta_os_textos_do_python():
    html = (
        eap_padrao.CONCEITOS.parent / "camadas" / "templates" / "visualizador.html"
    ).read_text(encoding="utf-8")
    assert "e.citada_txt" in html and "e.avisos_titulo" in html
    assert "n_linhas_citadas" not in html  # nenhuma conta ou texto montado em JS
