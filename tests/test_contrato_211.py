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


# ---------------------------------------------------------------------------------------------------------------
# E2: quantificar
# ---------------------------------------------------------------------------------------------------------------

import numpy as np

from camadas import lineares, valas

LINHAS_E2 = [
    ("UNIDADE 1 - ETA Teste", None, None, None, None, None),
    ("1", None, "UC A", None, None, None),
    (None, "CSUPVEG", "SUPRESSÃO VEGETAL", "M2", None, None),
    (None, "030403", "RASPAGEM", "M2", None, None),
    (None, "020223", "LOCAÇÃO", "M2", None, None),
    (None, "CSONDREDE", "SONDAGEM", "UN", None, None),
    (None, None, "TRECHO UM", "M", None, ENTRADA),
    (None, "CVCAFD300", "ESCAVAÇÃO FD DN 300", "M", None, VALA),
    (None, "CVCAFD200", "ESCAVAÇÃO FD DN 200", "M", None, None),
    (None, "041801", "CARGA E DESCARGA", "M3", None, None),
    (None, "900603", "BOTA-FORA", "M3", None, None),
    (None, "041901", "TRANSPORTE", "M3XKM", None, None),
    (None, "CRELF1", "REBAIXAMENTO", "VB", None, None),
    (None, "900506", "ESCORAMENTO", "UN", None, None),
    (None, None, "RECOMPOSIÇÃO DE PAVIMENTO", None, None, None),
    (None, None, "BLOCOS DE ANCORAGEM", None, None, None),
    (None, None, "BLOCOS DE APOIO", None, 4, None),
    (None, None, "TRECHO DOIS", "M", None, None),
    (None, "161301", "LIMPEZA", "M", None, None),
    (None, None, "TRECHO TRES", "M", None, None),
    (None, "041801", "CARGA E DESCARGA 3", "M3", None, None),
    ("2", None, "UC B", None, None, None),
    (None, None, "TRECHO QUATRO", "M", 150, None),
    (None, "162004", "LAVAGEM", "M", None, None),
    (None, "100207", "ASFALTO", "M2", 2704, None),
    (None, "100229", "GUIA", "M", 796, None),
    (None, "DI", "ADMINISTRAÇÃO LOCAL", "MÊS", 18, None),
    (None, "PLANILHA", "HIDROMECÂNICA", "VB", 1, None),
]


def _rede(id_, trecho, dn_mm, classes, origem=(0.0, 0.0)):
    """Rede sintética no formato de `valas.rede`: quadro real de `valas.quantificar`, amostras a cada 1 m em E."""
    de_mm = dn_mm + 22
    quadro = valas.quantificar(
        classes, np.ones(len(classes)), de_mm / 1000, None, "FD", dn_mm
    )
    n = len(classes)
    pts = np.column_stack([origem[0] + np.arange(n), np.full(n, origem[1])])
    return {
        "id": id_,
        "de_mm": de_mm,
        "dn_mm": dn_mm,
        "material": "FD",
        "extensao_m": float(n),
        "pranchas": [f"prancha-{id_}"],
        "layers": [f"layer-{id_}"],
        "pts": pts,
        "peso": np.ones(n),
        "quadro": quadro,
        "trecho_contrato": trecho,
    }


@pytest.fixture
def linhas_e2(tmp_path):
    caminho = _planilha(tmp_path, linhas=LINHAS_E2)
    return c211.classificar(c211.ler_custo_civil(caminho))


@pytest.fixture
def redes():
    return [
        _rede("R300", "TRECHO UM", 300, ["pista"] * 60 + ["calcada"] * 40),
        _rede("R200", "TRECHO UM", 200, ["pista"] * 30),
        _rede("R2", "TRECHO DOIS", 150, ["calcada"] * 20, origem=(0.0, 50.0)),
    ]


def _furo(id_="F1", e=0.0, n=0.0, boca=100.0, na=0.5):
    return {"id": id_, "E": e, "N": n, "cota_boca": boca, "na_m": na}


def _quant(linhas, redes, furos=(), **extra):
    contexto = c211.contexto_do_build(redes, list(furos), **extra)
    return c211.quantificar(linhas, contexto)


def _linha(res, composicao=None, descricao=None, trecho=None):
    achadas = [
        r
        for r in res
        if (composicao is None or r["composicao"] == composicao)
        and (descricao is None or r["descricao"] == descricao)
        and (trecho is None or r["trecho"] == trecho)
    ]
    return achadas[0]


def test_comprimento_do_trecho_e_filtro_por_dn(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    trecho = _linha(res, descricao="TRECHO UM")
    assert trecho["situacao"] == "calculada"
    assert trecho["quantidade_calculada"] == pytest.approx(130.0)
    assert trecho["unidade_calculada"] == "m"
    assert _linha(res, "CVCAFD300")["quantidade_calculada"] == pytest.approx(100.0)
    dn200 = _linha(res, "CVCAFD200")
    assert dn200["quantidade_calculada"] == pytest.approx(30.0)
    evidencia = dn200["evidencias"][0]
    assert evidencia["id"] == "R200" and evidencia["prancha"] == "prancha-R200"
    assert evidencia["layer"] == "layer-R200" and evidencia["unidade"] == "m"


def test_trecho_sem_rede_fica_a_preencher_com_motivo(linhas_e2, redes):
    res = _quant(linhas_e2, redes[:1])  # só a rede DN 300: o DN 200 não tem rede
    dn200 = _linha(res, "CVCAFD200")
    assert dn200["situacao"] == "a preencher"
    assert dn200["quantidade_calculada"] is None
    assert "sem rede medida na prancha" in dn200["motivo"]
    sem_rede = _linha(res, descricao="CARGA E DESCARGA 3")
    assert sem_rede["situacao"] == "a preencher" and sem_rede["motivo"]


def test_escavacao_e_bota_fora_pelo_dimensionador_unico(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    esperado = {"escavacao_m3": 0.0, "bota_fora_m3": 0.0}
    for rede in redes[:2]:
        for q in rede["quadro"]:
            vala = lineares.dimensionar_vala(
                {
                    "local": q["classe"],
                    "dn_mm": rede["dn_mm"],
                    "de_mm": rede["de_mm"],
                    "material": "FD",
                    "prof_m": q["profundidade_m"],
                    "comp_m": 1.0,
                    "metodo": "VCA",
                }
            )
            for chave in esperado:
                esperado[chave] += vala[chave] * q["extensao_m"]
    carga = _linha(res, "041801", trecho="TRECHO UM")
    bota = _linha(res, "900603")
    assert carga["situacao"] == bota["situacao"] == "calculada"
    assert carga["quantidade_calculada"] == pytest.approx(
        esperado["escavacao_m3"], abs=1e-2
    )
    assert bota["quantidade_calculada"] == pytest.approx(
        esperado["bota_fora_m3"], abs=1e-2
    )
    assert carga["unidade_calculada"] == "m3"
    assert {e["id"] for e in carga["evidencias"]} == {"R300", "R200"}


def test_transporte_usa_a_dmt_como_premissa(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    bota = _linha(res, "900603")["quantidade_calculada"]
    transporte = _linha(res, "041901")
    assert transporte["quantidade_calculada"] == pytest.approx(bota * 10, abs=0.05)
    assert transporte["unidade_calculada"] == "m3.km"
    premissa = transporte["premissas"][0]
    assert premissa["nome"] == "dmt_bota_fora_km" and premissa["valor"] == 10
    assert premissa["unidade"] == "km" and premissa["estado"] == "calibrar"


def test_escoramento_em_meses_com_as_premissas(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    escorada_m = sum(
        q["extensao_m"] for r in redes[:2] for q in r["quadro"] if q["escorado"]
    )
    esc = _linha(res, "900506")
    assert escorada_m > 0
    assert esc["quantidade_calculada"] == pytest.approx(
        escorada_m / (8 * 22) * 1, abs=1e-3
    )
    assert {p["nome"] for p in esc["premissas"]} == {
        "produtividade_vala_escorada_m_por_dia",
        "dias_uteis_por_mes",
        "jogos_de_escoramento",
    }


def test_recomposicao_soma_o_quadro_do_trecho(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    esperado = sum(q["recomposicao_m2"] for r in redes[:2] for q in r["quadro"])
    linha = _linha(res, descricao="RECOMPOSIÇÃO DE PAVIMENTO")
    assert esperado > 0
    assert linha["quantidade_calculada"] == pytest.approx(esperado, abs=1e-2)
    assert linha["unidade_calculada"] == "m2"


def test_rebaixamento_um_quando_o_na_esta_acima_do_fundo(linhas_e2, redes):
    res = _quant(linhas_e2, redes, [_furo(na=0.5)])
    linha = _linha(res, "CRELF1")
    assert linha["quantidade_calculada"] == 1.0 and linha["situacao"] == "calculada"
    tipos = {e["tipo"]: e for e in linha["evidencias"]}
    assert tipos["furo_mais_proximo"]["furo"] == "F1"
    assert tipos["cota_na"]["valor"] == pytest.approx(99.5)
    assert tipos["cota_na"]["valor"] > tipos["cota_fundo_vala"]["valor"]
    assert linha["premissas"][0]["nome"] == "margem_na_m"


def test_rebaixamento_zero_quando_o_na_esta_abaixo_do_fundo(linhas_e2, redes):
    res = _quant(linhas_e2, redes, [_furo(na=20.0)])
    linha = _linha(res, "CRELF1")
    assert linha["quantidade_calculada"] == 0.0 and linha["situacao"] == "calculada"


def test_rebaixamento_usa_o_furo_mais_proximo_do_trecho(linhas_e2, redes):
    perto_seco = _furo("PERTO", e=10.0, n=3.0, na=20.0)
    longe_molhado = _furo("LONGE", e=5000.0, n=5000.0, na=0.2)
    res = _quant(linhas_e2, redes, [longe_molhado, perto_seco])
    linha = _linha(res, "CRELF1")
    assert linha["quantidade_calculada"] == 0.0
    distancia = next(e for e in linha["evidencias"] if e["tipo"] == "furo_mais_proximo")
    assert distancia["furo"] == "PERTO" and distancia["valor"] == pytest.approx(3.0)


def test_rebaixamento_sem_na_ou_sem_furo_fica_a_preencher(linhas_e2, redes):
    sem_na = _linha(_quant(linhas_e2, redes, [_furo(na=None)]), "CRELF1")
    assert sem_na["situacao"] == "a preencher" and "nível d'água" in sem_na["motivo"]
    assert sem_na["quantidade_calculada"] is None
    sem_coordenada = {"id": "F9", "E": None, "N": None, "cota_boca": 100.0, "na_m": 1.0}
    contexto = c211.contexto_do_build(redes, [sem_coordenada])
    assert contexto["furos"] == [] and contexto["furos_sem_coordenada"] == ["F9"]
    sem_furo = _linha(c211.quantificar(linhas_e2, contexto), "CRELF1")
    assert sem_furo["situacao"] == "a preencher" and "sondagem" in sem_furo["motivo"]


def test_soma_trechos_parcial_lista_os_que_faltam(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    limpeza = _linha(res, "161301")  # UC A: UM (130) + DOIS (20); TRES sem rede
    assert limpeza["situacao"] == "parcial"
    assert limpeza["quantidade_calculada"] == pytest.approx(150.0)
    assert "TRECHO TRES" in limpeza["motivo"]
    assert {e["id"] for e in limpeza["evidencias"]} == {"TRECHO UM", "TRECHO DOIS"}


def test_soma_trechos_completa_e_toda_faltando(linhas_e2, redes):
    completa = [*redes, _rede("R3", "TRECHO TRES", 150, ["pista"] * 10, (0, 90))]
    res = _quant(linhas_e2, completa)
    limpeza = _linha(res, "161301")
    assert limpeza["situacao"] == "calculada"
    assert limpeza["quantidade_calculada"] == pytest.approx(160.0)
    lavagem = _linha(res, "162004")  # UC B: TRECHO QUATRO sem rede
    assert lavagem["situacao"] == "a preencher" and "TRECHO QUATRO" in lavagem["motivo"]


def test_area_da_uc_com_a_premissa_da_faixa(linhas_e2, redes):
    esperado = sum(q["extensao_m"] * q["largura_m"] for r in redes for q in r["quadro"])
    linha = _linha(_quant(linhas_e2, redes), "020223")
    assert linha["situacao"] == "parcial"  # TRECHO TRES sem rede
    assert linha["quantidade_calculada"] == pytest.approx(esperado, abs=0.1)
    assert linha["premissas"][0]["nome"] == "folga_locacao_lateral_m"
    completa = [*redes, _rede("R3", "TRECHO TRES", 150, ["pista"] * 10, (0, 90))]
    assert _linha(_quant(linhas_e2, completa), "020223")["situacao"] == "calculada"


def test_supressao_do_contexto_ou_a_preencher(linhas_e2, redes):
    ausente = _linha(_quant(linhas_e2, redes), "CSUPVEG")
    assert ausente["situacao"] == "a preencher" and "supressão" in ausente["motivo"]
    por_uc = {"UC 1 - UC A": {"arvores_m2": 120.5, "rasteira_m2": 300.0}}
    res = _quant(linhas_e2, redes, supressao_por_uc=por_uc)
    assert _linha(res, "CSUPVEG")["quantidade_calculada"] == pytest.approx(120.5)
    assert _linha(res, "030403")["quantidade_calculada"] == pytest.approx(300.0)
    assert _linha(res, "030403")["evidencias"][0]["tipo"] == "supressao_ortofoto"


def test_supressao_por_uc_chama_o_estimador_com_as_faixas_da_uc(
    linhas_e2, redes, monkeypatch
):
    from camadas import supressao

    chamadas = {}

    def estimar_falso(ortofoto, mds_png, geoms_por_etapa, faixa_m, folga_unidades_m):
        chamadas.update(
            etapas={k: len(v) for k, v in geoms_por_etapa.items()},
            faixa_m=faixa_m,
            folga=folga_unidades_m,
        )
        return {"resumo": {"UC 1 - UC A": {"supressao_m2": 10.0, "limpeza_m2": 20.0}}}

    monkeypatch.setattr(supressao, "estimar", estimar_falso)
    saida = c211.supressao_por_uc(redes, "orto.jpg", "mds.png", 4.0, 2.0, linhas_e2)
    assert chamadas["etapas"] == {"UC 1 - UC A": 3}  # UC B não tem rede medida
    assert chamadas["faixa_m"] == 4.0 and chamadas["folga"] == 0.0  # a faixa já vai pronta
    assert saida["UC 1 - UC A"]["arvores_m2"] == 10.0
    assert saida["UC 1 - UC A"]["rasteira_m2"] == 20.0
    assert c211.supressao_por_uc([], "o", "m", 4.0, 2.0, linhas_e2) == {}


def test_conferencia_confere_e_diverge(linhas_e2, redes):
    confere = _quant(linhas_e2, redes, urbanizacao={"asfalto novo (H01)": 2780.0})
    linha = _linha(confere, "100207")  # declarada 2704: 2,81 %, tolerância de área 5 %
    assert linha["situacao"] == "declarada · confere"
    assert linha["quantidade_calculada"] == pytest.approx(2780.0)
    assert linha["conferencia"]["diferenca_abs"] == pytest.approx(76.0)
    assert linha["conferencia"]["diferenca_pct"] == pytest.approx(2.81, abs=0.01)
    assert linha["conferencia"]["tolerancia_pct"] == 5
    diverge = _quant(linhas_e2, redes, urbanizacao={"asfalto novo (H01)": 3500.0})
    assert _linha(diverge, "100207")["situacao"] == "declarada · diverge"
    assert _linha(diverge, "100207")["conferencia"]["confere"] is False


def test_declarada_sem_calculo_e_conferencia_de_comprimento(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    assert _linha(res, "100207")["situacao"] == "declarada"
    assert _linha(res, "100207")["motivo"]
    assert _linha(res, "DI")["situacao"] == "declarada"
    perto = _quant(linhas_e2, redes, urbanizacao={"guia pré-moldada": 790.0})
    guia = _linha(perto, "100229")  # comprimento: tolerância de 2 %
    assert guia["situacao"] == "declarada · confere"
    assert guia["conferencia"]["tolerancia_pct"] == 2
    longe = _quant(linhas_e2, redes, urbanizacao={"guia pré-moldada": 700.0})
    assert _linha(longe, "100229")["situacao"] == "declarada · diverge"


def test_trecho_declarado_confere_com_o_comprimento_das_redes(linhas_e2):
    perto = [_rede("R4", "TRECHO QUATRO", 150, ["pista"] * 151)]
    res = _quant(linhas_e2, perto)
    assert _linha(res, descricao="TRECHO QUATRO")["situacao"] == "declarada · confere"
    longe = [_rede("R4", "TRECHO QUATRO", 150, ["pista"] * 100)]
    res = _quant(linhas_e2, longe)
    assert _linha(res, descricao="TRECHO QUATRO")["situacao"] == "declarada · diverge"


def test_blocos_verba_e_sem_regra(linhas_e2, redes):
    res = _quant(linhas_e2, redes)
    ancoragem = _linha(res, descricao="BLOCOS DE ANCORAGEM")
    assert ancoragem["situacao"] == "a preencher" and "fase B" in ancoragem["motivo"]
    apoio = _linha(res, descricao="BLOCOS DE APOIO")
    assert apoio["situacao"] == "declarada" and apoio["quantidade_declarada"] == 4
    verba = _linha(res, "PLANILHA")
    assert verba["situacao"] == "verba"
    assert verba["motivo"] == "VB: fora da quantificação"
    assert verba["quantidade_calculada"] is None
    sondagem = _linha(res, "CSONDREDE")
    assert sondagem["situacao"] == "a preencher" and "execução" in sondagem["motivo"]


def test_todo_resultado_tem_os_campos_e_motivo_quando_nao_calculada(linhas_e2, redes):
    res = _quant(linhas_e2, redes, [_furo()])
    assert len(res) == len(linhas_e2)
    for r in res:
        assert r["situacao"] in c211.SITUACOES
        assert {
            "quantidade_calculada",
            "unidade_calculada",
            "evidencias",
            "premissas",
        } <= set(r)
        if r["situacao"] != "calculada" and not r["situacao"].startswith("declarada ·"):
            assert r["motivo"]
        if r["situacao"] == "calculada":
            assert r["evidencias"]


def test_quantificar_e_deterministico(linhas_e2, redes):
    furos = [_furo()]
    primeira = json.dumps(_quant(linhas_e2, redes, furos), default=str)
    assert primeira == json.dumps(_quant(linhas_e2, redes, furos), default=str)


def test_resumo_quantidades_e_para_html(linhas_e2, redes):
    res = _quant(linhas_e2, redes, [_furo()])
    resumo = c211.resumo_quantidades(res)
    assert resumo["linhas"] == len(res)
    assert sum(resumo["por_situacao"].values()) == len(res)
    vazias = [r for r in res if r["quantidade_declarada"] is None]
    calculadas = [r for r in vazias if r["situacao"] == "calculada"]
    assert resumo["vazias"] == len(vazias)
    assert resumo["vazias_calculadas"] == len(calculadas)
    esperado_pct = 100 * len(calculadas) / len(vazias)
    assert resumo["pct_vazias_calculadas"] == pytest.approx(esperado_pct, abs=0.05)
    html = c211.para_html(res)
    assert len(html) == len(res)
    trecho = next(h for h in html if h["descricao"] == "TRECHO UM")
    assert trecho["calculada"] == "130,00" and trecho["declarada"] == ""
    assert trecho["folha_eap"] == "OP.02.06" and trecho["evidencias"]
    asfalto = next(h for h in html if h["composicao"] == "100207")
    assert asfalto["declarada"] == "2.704,00"
    assert c211._ptbr(1234567.891) == "1.234.567,89"


def test_sentinela_de_preco_continua_fora_da_quantificacao(tmp_path, redes):
    caminho = _planilha(tmp_path, linhas=LINHAS_E2)
    linhas = c211.classificar(c211.ler_custo_civil(caminho))
    res = _quant(linhas, redes, [_furo()])
    saida = json.dumps(
        {"res": res, "html": c211.para_html(res), "meta": c211.metadados()},
        ensure_ascii=False,
        default=str,
    )
    assert "987654" not in saida


def test_premissas_e_tolerancias_vivem_no_conceito():
    premissas = c211.DE_PARA["premissas"]
    esperado = {
        "dmt_bota_fora_km": 10,
        "produtividade_vala_escorada_m_por_dia": 8,
        "dias_uteis_por_mes": 22,
        "jogos_de_escoramento": 1,
    }
    for nome, valor in esperado.items():
        assert premissas[nome]["valor"] == valor
        assert premissas[nome]["estado"] == "calibrar"
        assert "04/11/2026" in premissas[nome]["fonte"]
    t = c211.DE_PARA["tolerancias"]
    assert (t["comprimento"], t["area"], t["volume"], t["unidade"]) == (2, 5, 5, 0)


def test_conceito_alternativo_muda_a_premissa(linhas_e2, redes):
    conceito = json.loads(json.dumps(c211.DE_PARA))
    conceito["premissas"]["dmt_bota_fora_km"]["valor"] = 20
    contexto = c211.contexto_do_build(redes, [])
    base = _linha(c211.quantificar(linhas_e2, contexto), "041901")
    dobro = _linha(c211.quantificar(linhas_e2, contexto, conceito), "041901")
    assert dobro["quantidade_calculada"] == pytest.approx(
        2 * base["quantidade_calculada"], abs=0.1
    )


def test_faixa_dos_trechos_tem_area(linhas_e2, redes, monkeypatch):
    """A faixa que vai ao estimador não pode ser vazia: o buffer plano de ponto dá área 0 (zerava a supressão)."""
    from camadas import supressao

    faixas = {}

    def estimar_falso(ortofoto, mds_png, geoms_por_etapa, faixa_m, folga_unidades_m):
        for uc, geoms in geoms_por_etapa.items():
            faixas[uc] = supressao.faixa_de_obra(geoms, faixa_m, folga_unidades_m)
        return {"resumo": {}}

    monkeypatch.setattr(supressao, "estimar", estimar_falso)
    c211.supressao_por_uc(redes, "orto.jpg", "mds.png", 4.0, 2.0, linhas_e2)
    assert faixas and all(f is not None and f.area > 0 for f in faixas.values())
