"""Testes do leitor da CUSTO CIVIL do contrato 211, com planilha sintética (sem preço)."""

import json

import openpyxl
import pytest

from camadas import contrato_211 as c211

SENTINELA = 987654.321
ENTRADA = "004-SAA-0017-PBHI-LAYOUT-R5"
VALA = "005-SAA-0017-PBHI-PERFIL-R1"

# (A, B, C, D, E, I)
LINHAS = [
    ("UNIDADE 1 - ETA Teste", None, None, None, None, None),
    (None, None, "ADMINISTRAÇÃO LOCAL DE OBRA - ALO", None, None, None),
    (None, "DI", "ADMINISTRAÇÃO LOCAL DA OBRA", "MÊS", 18, None),
    ("1", None, "INTERLIGAÇÕES", None, None, None),
    (None, None, "SERVIÇOS PRELIMINARES", None, None, None),
    (None, "CSUPVEG", "SUPRESSÃO VEGETAL", "M2", None, None),
    (None, None, "ENTRADA DA ADUTORA", "M", None, ENTRADA),
    (None, "CVCAFD1000", "ESCAVAÇÃO ... FD DN 1000", "M", None, VALA),
    (None, "041801", "CARGA E DESCARGA DE SOLOS", "M3", None, None),
    (None, None, "RECOMPOSIÇÃO DE PAVIMENTO", None, None, None),
    (None, None, "BLOCOS DE ANCORAGEM", None, None, None),
    (None, None, "MEDIDORES DE VAZÃO", "UNI", 3, None),
    (None, None, "BLOCOS DE APOIO", None, 4, None),
    (None, None, "SAÍDA DO LODO", "M", None, None),
    (None, "CVCAFD200", "ESCAVAÇÃO ... FD DN 200", "M", None, None),
    (None, None, "ÁGUA POTÁVEL", None, None, "008-SAA-AGUA"),
    (None, "CVCAPVC25", "ESCAVAÇÃO ... PVC DN 25", "M", 622, None),
    (None, "XYZ999", "COMPOSIÇÃO DESCONHECIDA", "UN", None, None),
    ("2", None, "OUTRA UC", None, None, None),
    (None, "PLANILHA", "FORNECIMENTO E MONTAGEM HIDROMECÂNICA", "VB", 1, None),
    (None, None, None, "SUBTOTAL:", None, None),
]


def _planilha(tmp_path, linhas=LINHAS, preco=SENTINELA):
    """Planilha com o layout real: A ITEM, B COMPOSIÇÃO, C DESCRIÇÃO, D UNID., E QUANT., F e G preço, I projeto."""
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
    for a, b, c, d, e, i in linhas:
        ws.append([a, b, c, d, e, preco, preco, None, i])
    insumos = livro.create_sheet("INSUMOS")
    insumos.append([preco, preco])
    livro.save(caminho)
    return caminho


@pytest.fixture
def servicos(tmp_path):
    return c211.ler_custo_civil(_planilha(tmp_path))


def _por_descricao(servicos, descricao, ocorrencia=0):
    return [s for s in servicos if s["descricao"] == descricao][ocorrencia]


def test_sentinela_de_preco_nunca_aparece(tmp_path):
    servicos = c211.ler_custo_civil(_planilha(tmp_path))
    classificadas = c211.classificar(servicos)
    saida = json.dumps(
        {
            "linhas": classificadas,
            "resumo": c211.resumo(classificadas),
            "meta": c211.metadados(),
        },
        ensure_ascii=False,
    )
    assert str(SENTINELA) not in saida
    assert "987654" not in saida


def test_so_as_colunas_a_ate_e_e_i_sao_lidas(tmp_path, monkeypatch):
    colunas_pedidas = []
    original = openpyxl.worksheet._read_only.ReadOnlyWorksheet.iter_rows

    def espiao(self, *args, **kwargs):
        colunas_pedidas.append((kwargs.get("min_col"), kwargs.get("max_col")))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        openpyxl.worksheet._read_only.ReadOnlyWorksheet, "iter_rows", espiao
    )
    c211.ler_custo_civil(_planilha(tmp_path))
    assert sorted(colunas_pedidas) == [(1, 5), (9, 9)]


def test_hierarquia_unidade_uc_grupo_trecho(servicos):
    alo = _por_descricao(servicos, "ADMINISTRAÇÃO LOCAL DA OBRA")
    assert alo["unidade_obra"] == "UNIDADE 1 - ETA Teste"
    assert alo["uc"] is None and alo["grupo"] == "ADMINISTRAÇÃO LOCAL DE OBRA - ALO"
    assert alo["quantidade_declarada"] == 18.0

    supressao = _por_descricao(servicos, "SUPRESSÃO VEGETAL")
    assert supressao["uc"] == "UC 1 - INTERLIGAÇÕES"
    assert supressao["grupo"] == "SERVIÇOS PRELIMINARES"
    assert supressao["trecho"] is None

    trecho = _por_descricao(servicos, "ENTRADA DA ADUTORA")
    assert trecho["eh_trecho"] and trecho["unidade"] == "M"
    assert (
        trecho["trecho"] == "ENTRADA DA ADUTORA"
        and trecho["trecho_linha"] == trecho["linha"]
    )
    assert trecho["grupo"] is None

    vala = _por_descricao(servicos, "ESCAVAÇÃO ... FD DN 1000")
    assert (
        vala["trecho"] == "ENTRADA DA ADUTORA"
        and vala["trecho_linha"] == trecho["linha"]
    )
    assert not vala["eh_trecho"]

    outra = _por_descricao(servicos, "FORNECIMENTO E MONTAGEM HIDROMECÂNICA")
    assert outra["uc"] == "UC 2 - OUTRA UC" and outra["trecho"] is None


def test_titulos_servico_entram_sem_unidade(servicos):
    for descricao in (
        "RECOMPOSIÇÃO DE PAVIMENTO",
        "BLOCOS DE ANCORAGEM",
        "BLOCOS DE APOIO",
    ):
        s = _por_descricao(servicos, descricao)
        assert s["titulo_servico"] and s["composicao"] is None
        assert s["trecho"] == "ENTRADA DA ADUTORA"
    assert _por_descricao(servicos, "RECOMPOSIÇÃO DE PAVIMENTO")["unidade"] is None
    assert _por_descricao(servicos, "BLOCOS DE APOIO")["quantidade_declarada"] == 4.0

    medidores = _por_descricao(servicos, "MEDIDORES DE VAZÃO")
    assert medidores["unidade"] == "UNI" and medidores["quantidade_declarada"] == 3.0
    assert not medidores["titulo_servico"] and not medidores["eh_trecho"]


def test_titulo_de_grupo_e_subtotal_nao_sao_servico(servicos):
    descricoes = [s["descricao"] for s in servicos]
    for titulo in (
        "SERVIÇOS PRELIMINARES",
        "INTERLIGAÇÕES",
        "ÁGUA POTÁVEL",
        "OUTRA UC",
    ):
        assert titulo not in descricoes
    assert "" not in descricoes
    assert all(s["unidade"] != "SUBTOTAL:" for s in servicos)


def test_projeto_proprio_ou_herdado_do_trecho(servicos):
    trecho = _por_descricao(servicos, "ENTRADA DA ADUTORA")
    assert trecho["projeto"] == ENTRADA
    assert _por_descricao(servicos, "ESCAVAÇÃO ... FD DN 1000")["projeto"] == VALA
    assert _por_descricao(servicos, "CARGA E DESCARGA DE SOLOS")["projeto"] == ENTRADA
    assert _por_descricao(servicos, "RECOMPOSIÇÃO DE PAVIMENTO")["projeto"] == ENTRADA
    # trecho novo sem projeto não herda o do anterior
    assert _por_descricao(servicos, "SAÍDA DO LODO")["projeto"] is None
    assert _por_descricao(servicos, "ESCAVAÇÃO ... FD DN 200")["projeto"] is None
    # o grupo ÁGUA POTÁVEL traz o projeto na própria linha de título
    assert (
        _por_descricao(servicos, "ESCAVAÇÃO ... PVC DN 25")["projeto"] == "008-SAA-AGUA"
    )


def test_classificar_cvca_material_e_dn(servicos):
    por_composicao = {
        s["composicao"]: s for s in c211.classificar(servicos) if s["composicao"]
    }
    fd = por_composicao["CVCAFD1000"]
    assert (fd["material"], fd["dn_mm"], fd["regra"], fd["folha_eap"]) == (
        "ferro_fundido",
        1000,
        "comprimento_trecho",
        "OP.02.06",
    )
    pvc = por_composicao["CVCAPVC25"]
    assert (pvc["material"], pvc["dn_mm"]) == ("pvc", 25)
    assert por_composicao["CVCAFD200"]["dn_mm"] == 200


def test_classificar_regras_por_composicao_estrutura_e_descricao(servicos):
    classificadas = c211.classificar(servicos)
    por_descricao = {s["descricao"]: s for s in classificadas}
    assert por_descricao["ENTRADA DA ADUTORA"]["regra"] == "comprimento_trecho"
    assert por_descricao["ADMINISTRAÇÃO LOCAL DA OBRA"]["regra"] == "declarada"
    assert por_descricao["SUPRESSÃO VEGETAL"]["folha_eap"] == "OP.01.04"
    assert por_descricao["CARGA E DESCARGA DE SOLOS"]["folha_eap"] == "OP.02.05"
    assert por_descricao["RECOMPOSIÇÃO DE PAVIMENTO"]["folha_eap"] == "OP.10.01"
    assert por_descricao["BLOCOS DE ANCORAGEM"]["regra"] == "contagem_blocos"
    assert por_descricao["BLOCOS DE APOIO"]["folha_eap"] == "OP.07.04"
    assert por_descricao["FORNECIMENTO E MONTAGEM HIDROMECÂNICA"]["regra"] == "verba"
    medidores = por_descricao["MEDIDORES DE VAZÃO"]
    assert medidores["regra"] == "sem_regra" and medidores["motivo"]


def test_linha_sem_de_para_leva_motivo(servicos):
    desconhecida = next(
        s for s in c211.classificar(servicos) if s["composicao"] == "XYZ999"
    )
    assert desconhecida["regra"] == "sem_regra"
    assert desconhecida["folha_eap"] is None and desconhecida["estado"] is None
    assert "XYZ999" in desconhecida["motivo"]


def test_resumo(servicos):
    classificadas = c211.classificar(servicos)
    r = c211.resumo(classificadas)
    assert r["linhas"] == len(classificadas)
    assert r["declaradas"] + r["vazias"] == r["linhas"]
    assert r["declaradas"] == 5  # ALO, medidores, blocos de apoio, PVC 25 e PLANILHA
    assert r["titulos_servico"] == 3
    assert r["por_regra"]["comprimento_trecho"] == 5
    assert [x["composicao"] for x in r["sem_de_para"]] == ["XYZ999"]
    assert sum(r["por_regra"].values()) == r["linhas"]


def test_de_para_aponta_para_folhas_existentes():
    eap = json.loads(
        (
            c211.Path(c211.__file__).parent.parent / "conceitos" / "eap_padrao.json"
        ).read_text("utf-8")
    )
    ids = set()

    def varrer(no):
        if isinstance(no, dict):
            if "id" in no:
                ids.add(no["id"])
            for v in no.values():
                varrer(v)
        elif isinstance(no, list):
            for v in no:
                varrer(v)

    varrer(eap)
    entradas = [
        *c211.DE_PARA["composicoes"].values(),
        *c211.DE_PARA["padroes"],
        *c211.DE_PARA["por_estrutura"].values(),
        *c211.DE_PARA["por_descricao"].values(),
    ]
    for entrada in entradas:
        assert entrada["estado"] in ("confirmado", "premissa", "calibrar")
        assert entrada["folha_eap"] is None or entrada["folha_eap"] in ids
        if entrada["regra"] == "sem_regra":
            assert entrada["motivo"]


def test_aba_inexistente_e_cabecalho_ausente(tmp_path):
    caminho = _planilha(tmp_path)
    with pytest.raises(ValueError, match="não existe"):
        c211.ler_custo_civil(caminho, aba="OUTRA")
    livro = openpyxl.Workbook()
    livro.active.title = "CUSTO CIVIL"
    livro.active.append(["sem cabeçalho"])
    livro.save(tmp_path / "vazia.xlsx")
    with pytest.raises(ValueError, match="cabeçalho"):
        c211.ler_custo_civil(tmp_path / "vazia.xlsx")


def test_metadados_e_cli(tmp_path, capsys):
    meta = c211.metadados()
    assert meta["modulo"] == "contrato_211"
    assert meta["premissas"] and meta["ultima_revisao"]
    assert c211.main([str(_planilha(tmp_path))]) == 0
    assert json.loads(capsys.readouterr().out)["linhas"] == 14
    assert c211.main([]) == 2
