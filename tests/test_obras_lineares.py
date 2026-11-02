import numpy as np
import openpyxl
import pytest
from shapely.geometry import LineString

from camadas import obras_lineares as ol

TRECHO = {"local": "Entrada de água bruta", "dn_mm": 1000, "material": "FD", "prof_m": 2.4, "comp_m": 57.3,
          "metodo": "VCA", "sond_ini": "SP-02", "sond_fim": "SP-02", "na_m": 9.0, "solo": "argila",
          "pavimentos": {"grama": 57.3}, "supressao_frac": 1.0}


def test_sobrelargura_da_tabela_i_do_mos():
    assert ol.sobrelargura("FD", 1000) == 0.90
    assert ol.sobrelargura("FD", 300) == 0.35
    assert ol.sobrelargura("FD", 350) == 0.45
    assert ol.sobrelargura("PVC", 100) == 0.35
    assert ol.sobrelargura("PEAD", 315) == 0.35                      # barras é o padrão do PEAD
    assert ol.sobrelargura("PEAD", 63, "soldada_rolo_mecanica") == 0.20
    assert ol.sobrelargura("CONCRETO", 600, "macho_femea") == 0.65
    assert ol.sobrelargura("FD", 1500) is None                         # fora da tabela


def test_largura_da_vala_confere_com_a_planilha():
    assert ol.largura(1000, "FD", 2.40, True) == pytest.approx(2.10)  # 1,0 + 0,90 + X 0,10 + Y 0,10
    assert ol.largura(200, "FD", 2.50, True) == pytest.approx(0.75)
    assert ol.largura(300, "FD", 2.50, True) == pytest.approx(0.85)
    assert ol.largura(300, "FD", 2.00, True) == pytest.approx(0.75)   # 2 m exatos: sem Y
    assert ol.largura(300, "FD", 3.10, True) == pytest.approx(0.95)   # 1,10 m além de 2 m = duas frações
    assert ol.largura(100, "PVC", 1.00, False) == pytest.approx(0.45)


def test_escoramento_acima_de_1_25_m():
    assert not ol.escorar(1.25) and ol.escorar(1.26) and not ol.escorar(None)


def test_vca_reproduz_a_linha_da_entrada_de_agua_bruta():
    q = ol.quantificar(TRECHO)
    assert q["escorado"] and q["largura_m"] == pytest.approx(2.10)
    assert q["area_m2"] == pytest.approx(120.33)
    assert q["escavacao_m3"] == pytest.approx(288.792)
    assert q["reaterro_m3"] == pytest.approx(243.789, abs=1e-3)
    assert q["bota_fora_m3"] == pytest.approx(58.504, abs=1e-3)
    assert q["pavimento_m2"] == {"grama": pytest.approx(120.33)} and q["supressao_m2"] == pytest.approx(120.33)
    assert q["geotecnia"]["solos"] == {"argila": 1.0} and q["geotecnia"]["esgotamento_frac"] == 0
    assert not q["alertas"]


def test_sem_profundidade_alerta_e_nao_inventa_volume():
    q = ol.quantificar({**TRECHO, "prof_m": None, "pavimentos": {}})
    assert q.get("escavacao_m3") is None and not q["escorado"]
    assert any("sem profundidade" in a for a in q["alertas"])


def test_mnd_so_escava_os_caximbos():
    q = ol.quantificar({**TRECHO, "metodo": "MND", "comp_m": 170, "pavimentos": {"asfalto": 120, "grama": 50}})
    assert q["caximbos"] == 3 and q["area_m2"] == pytest.approx(13.5)
    assert q["pavimento_m2"] == {"asfalto": 13.5} and q["supressao_m2"] == 0 and q["escoramento_m2"] == 0


FUROS = [{"id": "SP-02", "E": 0.0, "N": 0.0, "na_m": 9.0,
          "camadas": [{"de": 0, "ate": 1.0, "descricao": "Aterro argiloso"}, {"de": 1.0, "ate": 8, "descricao": "Argila siltosa"}]},
         {"id": "SP-15", "E": 100.0, "N": 0.0, "na_m": 1.5,
          "camadas": [{"de": 0, "ate": 2.0, "descricao": "Areia fina"}, {"de": 2.0, "ate": 5, "descricao": "Basalto alterado"}]}]


def test_solo_na_vala_pela_descricao_das_camadas():
    assert ol.solo_na_vala(FUROS[0], 2.0) == {"aterro": 0.5, "argila": 0.5}
    assert ol.solo_na_vala(FUROS[1], 2.5) == {"areia": 0.8, "rocha_alterada": pytest.approx(0.2)}
    assert ol.solo_na_vala({"camadas": [{"de": 0, "ate": 1, "descricao": "argila"}]}, 2.0)["indefinido"] == 0.5


def test_sondagem_por_posicao_e_esgotamento():
    t, pts = ol.no_eixo(TRECHO, LineString([(0, 0), (100, 0)]))
    assert t["comp_m"] == 100
    g = ol.quantificar(t, FUROS, pts)["geotecnia"]
    assert g["esgotamento_frac"] == pytest.approx(0.5, abs=0.02)        # metade mais perto do SP-15 (NA 1,5 m)
    assert g["na_min_m"] == 1.5 and g["categorias"]["2ª categoria"] > 0
    longe, pts = ol.no_eixo(TRECHO, LineString([(0, 500), (10, 500)]))
    assert ol.quantificar(longe, FUROS, pts)["geotecnia"]["sem_sondagem_frac"] == 1.0


def test_sondagem_pelos_ids_da_planilha():
    g = ol.geotecnia({**TRECHO, "sond_ini": "SP-02", "sond_fim": "SP-15"}, FUROS)
    assert ol.cobertura({"sond_ini": "SP-02", "sond_fim": "SP-15"}, FUROS) == {"SP-02": 0.5, "SP-15": 0.5}
    assert g["esgotamento_frac"] == 0.5 and g["na_min_m"] == 1.5


def test_ortofoto_verde_preto_e_cinza():
    img = np.zeros((100, 300, 3), np.uint8)                          # 30 × 10 m a 0,1 m/px
    img[:, :100] = (40, 160, 40)                                      # BGR: grama
    img[:, 100:200] = (45, 45, 45)                                    # asfalto
    img[:, 200:] = (175, 180, 180)                                    # calçada
    orto = {"img": img, "e0": 0.0, "n1": 10.0, "res": 0.1}
    t, _ = ol.no_eixo({**TRECHO, "pavimentos": {}}, LineString([(1, 5), (29, 5)]), orto)
    assert set(t["pavimentos"]) == {"grama", "asfalto", "concreto"}
    assert t["pavimentos"]["asfalto"] == pytest.approx(10, abs=1.5)
    assert t["supressao_frac"] == pytest.approx(9 / 28, abs=0.06)


def _planilha(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Obras Lineares"
    cab = ["Local", "DN do tubo", "Tipo do tubo", "Sondagem", None, "NA (m)", "Tipo de solo", "Prof. Média",
           "Escoramento", "Comprimento Total", "Método Construtivo", "Largura da vala\n(m)", "Área\n(m2)",
           "Escavação\n(m3)", "Reaterro\n(m3)", "Empolamento", "Bota Fora\n(m3)", "Supressão vegetal\n(m2)",
           "Tipo de\nPavimento 1", "Comprimento\nPavimento 1", "Área\nPavimento 1", "Observações"]
    for j, v in enumerate(cab, start=22):
        ws.cell(2, j, v)
    linhas = [["Entrada de água bruta", 1000, "FD", "SP-02", "SP-02", 9, "argila", 2.4, "sim", 57.3, "VCA", 2.1,
               120.33, 288.792, 243.789, 1.3, 58.504, 120.33, "grama", 57.3, 120.33, "Supressão vegetal - 100% do trecho"],
              ["Retorno lodo EEE flotofiltro", 150, "FD", "SP-05", "SP-09", 7.6, "argila", None, "não", 28, "VCA",
               None, 0, 0, -0.49]]
    for i, linha in enumerate(linhas, start=4):
        for j, v in enumerate(linha, start=22):
            ws.cell(i, j, v)
    cc = wb.create_sheet("CUSTO CIVIL")
    for linha in [["UNIDADE 1 - ETA Vila C"], ["1.2", None, "ENTRADA DA ADUTORA DE ÁGUA BRUTA", "M", 57.3],
                  [None, "CVCAFD1000", "ESCAVAÇÃO ... FD DN 1000", "M", 57.3],
                  ["1.5", None, "INTERLIGAÇÃO: MÓD. TRATAMENTO COM MICRO AREIA 360L COM FILTROS EXISTENTES", "M", 16,
                   None, None, "Tubulação aérea"],
                  ["1.8", None, "RETORNO LODO EEE FLOTOFILTRO", "M", 28], ["UNIDADE 02 - AAT06"],
                  ["1", None, "ADUTORA AAT 06", "M", 900]]:
        cc.append(linha)
    caminho = tmp_path / "p.xlsx"
    wb.save(caminho)
    return caminho


def test_planilha_le_confere_e_concilia(tmp_path):
    caminho = _planilha(tmp_path)
    trechos = ol.ler_obras_lineares(caminho)
    assert [t["linha"] for t in trechos] == [4, 5]
    assert trechos[0]["pavimentos"] == {"grama": 57.3} and trechos[0]["supressao_frac"] == 1.0
    assert ol.conferir(ol.quantificar(trechos[0])) == []
    assert ol.conferir(ol.quantificar(trechos[1])) == ["reaterro_m3: planilha -0.490, sem cálculo"]
    itens = ol.ler_custo_civil(caminho)
    assert [i["item"] for i in itens] == ["1.2", "1.5", "1.8"]               # só a Unidade 1
    assert itens[0]["servicos"][0]["codigo"] == "CVCAFD1000"
    conc = {c["item"]: c["situacao"] for c in ol.conciliar(trechos, itens)}
    assert conc == {"1.2": "bate", "1.5": "sem trecho na aba Obras Lineares (tubulação aérea)", "1.8": "bate"}
    df = ol.quadro([ol.quantificar(t) for t in trechos])
    assert list(df["escoramento"]) == ["sim", "não"]
    ol.principal([str(caminho), "--saida", str(tmp_path / "out")])
    assert (tmp_path / "out" / "obras_lineares_conciliacao.csv").exists()


def test_casar_actiflo_e_micro_areia_sao_o_mesmo_modulo():
    trechos = [{"local": "Interligação: adutora de água bruta com ACTIFLO 360"},
               {"local": "Interligação: adutora de água bruta com ACTIFLO 600"}, {"local": "Entrada de água bruta"}]
    casados = ol.casar("INTERLIGAÇÃO: ADUTORA DE ÁGUA BRUTA COM MÓD. TRATAMENTO COM MICRO AREIA 600L", trechos)
    assert [t["local"] for t in casados] == ["Interligação: adutora de água bruta com ACTIFLO 600"]
    assert ol.casar("DRENAGEM ACTIFLO 600 L/S", trechos) == []


def test_metadados_citam_funcoes_existentes():
    m = ol.metadados()
    assert all(hasattr(ol, f) for f in m["funcoes"]) and m["premissas"]
    assert ol.classe_solo("Basalto são")["categoria"] == "3ª categoria"
    assert ol.ler_furos(None) == []


def test_etapa_do_build_usa_as_sondagens_da_obra_e_o_metodo_do_usuario(tmp_path):
    caminho = _planilha(tmp_path)
    furos = [{**FUROS[1], "id": "SPT 2"}]                              # o 'SP-02' da planilha, com outra grafia
    cfg = {"obras_lineares": {"planilha": str(caminho), "unidade": "UNIDADE 1",
                              "metodo": {"Retorno lodo EEE flotofiltro": "MND"}}}
    pac = ol.etapa(cfg, furos, tmp_path, log=lambda *_: None)
    entrada, retorno = pac["trechos"]
    assert entrada["solos"].startswith("areia") and entrada["esgotamento_frac"] == 1.0   # NA 1,5 m < 2,4 m
    assert "esgotamento" in entrada["alertas"]
    assert retorno["metodo"] == "MND" and retorno["largura_m"] is None and retorno["caximbos"] == 2
    assert {c["item"] for c in pac["conciliacao"]} == {"1.2", "1.5", "1.8"} and pac["mnd"]
    assert (tmp_path / "obras_lineares.csv").exists()
    assert ol.etapa({}, [], tmp_path) is None
    assert ol.etapa({"obras_lineares": {"planilha": str(tmp_path / "nao.xlsx")}}, [], tmp_path, log=lambda *_: None) is None


def test_id_de_sondagem_tolerante():
    assert ol.id_furo("SP-02") == ol.id_furo("SP02") == ol.id_furo("SPT-2") == ol.id_furo("sp 2") == "SP2"
    assert ol.id_furo("SP-15") != ol.id_furo("SP-1")


def test_tubos_da_eta_sao_unidade_1_e_o_perfil_hidraulico_nao_e_linear():
    import json
    import re

    from camadas import construtivos, escopo_obra, pdf_cad
    sis = construtivos.REGRAS["sistemas"]
    assert {sis[k]["unidade"] for k in ("AB_ENTRADA", "AB_INTERLIG", "LODO_SAIDA", "LODO_RETORNO")} == {"u1"}
    assert escopo_obra._casa("AB_ENTRADA", "ENTRADA DA ADUTORA DE AGUA BRUTA")
    assert not escopo_obra._casa("AAT00", "ENTRADA DA ADUTORA DE AGUA BRUTA")
    assert not escopo_obra._casa("AB_INTERLIG", "INTERLIGACAO:MOD. TRATAMENTO COM MICRO AREIA 360L COM FILTROS EXISTENTES")
    linear = json.loads((pdf_cad.CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))["linear"]
    assert not re.search(linear, "005-SAA-0017-7471-PBHI-DE-0001ETAVILACPERFILHIDRAU-R1")
    assert re.search(linear, "001-SAA-0000-0000-PBEN-DE-0000AAT00PLANTAPERF01-R0")


def _furo_por_metro_referencia(pts, furos):
    """Implementação anterior (contra todos os furos), cópia fiel, como referência."""
    com_xy = [f for f in furos if f.get("E") is not None and f.get("N") is not None]
    if not com_xy:
        return [None] * len(pts)
    xy = np.array([[f["E"], f["N"]] for f in com_xy], float)
    d = np.linalg.norm(pts[:, None, :] - xy[None, :, :], axis=2)
    perto = d.argmin(axis=1)
    raio = ol.geo.RAIO_INFLUENCIA_M
    return [com_xy[k]["id"] if d[i, k] <= raio else None for i, k in enumerate(perto)]


def test_furo_por_metro_com_caixa_igual_a_referencia_em_casos_aleatorios():
    rng = np.random.default_rng(24)
    raio = ol.geo.RAIO_INFLUENCIA_M
    for caso in range(300):
        n = int(rng.integers(0, 30))
        base = rng.uniform(0, 600, (n, 2)).round(int(rng.integers(0, 3)))
        pts = np.column_stack([np.linspace(0, 400, 40) + 0.5, np.full(40, 100.0)]) if caso % 3 else base[:5]
        furos = [{"id": f"F{i}", "E": float(x), "N": float(y)} for i, (x, y) in enumerate(base)]
        if n:
            furos.append({"id": "SEM-XY", "E": None, "N": None})
            furos.append({"id": "NO-RAIO", "E": float(pts[0, 0] + raio), "N": float(pts[0, 1])})   # exato no raio
            furos.append({"id": "EMPATE-A", "E": float(pts[0, 0] - 3), "N": float(pts[0, 1])})
            furos.append({"id": "EMPATE-B", "E": float(pts[0, 0] + 3), "N": float(pts[0, 1])})     # distância igual
            furos.append({"id": "EMPATE-C", "E": float(pts[0, 0] - 3), "N": float(pts[0, 1])})     # idem, repetido
        esperado = _furo_por_metro_referencia(pts, furos)
        assert ol.furo_por_metro(pts, furos) == esperado
        assert ol.furo_por_metro(pts, furos, ol.furos_com_xy(furos)) == esperado
    assert ol.furo_por_metro(np.zeros((0, 2)), []) == []
    assert ol.furo_por_metro(np.zeros((0, 2)), [{"id": "A", "E": 0.0, "N": 0.0}]) == []


def test_furo_por_metro_com_linha_nan_igual_a_referencia():
    pts = np.array([[10.0, 10.0], [np.nan, np.nan], [12.0, 10.0], [np.nan, 5.0]])
    furos = [{"id": "A", "E": 10.0, "N": 11.0}, {"id": "B", "E": 12.0, "N": 12.0}]
    esperado = _furo_por_metro_referencia(pts, furos)
    assert esperado == ["A", None, "B", None]
    assert ol.furo_por_metro(pts, furos) == esperado
    assert ol.furo_por_metro(np.full((2, 2), np.nan), furos) == [None, None]


def test_id_furo_aceita_argumento_nao_hashable_e_separa_tipos():
    assert ol.id_furo(["SP-02"]) == ol.id_furo(str(["SP-02"]))
    assert ol.id_furo(None) == ol.id_furo(None)
    assert ol.id_furo(2) == "2" and ol.id_furo(2.0) == "20"
    assert ol.id_furo("SP-02") == "SP2"


def test_etapa_sem_a_aba_obras_lineares_e_pulada_com_motivo(tmp_path):
    """Achado do build real de Foz: a planilha do contrato no Drive não tem a aba do protótipo."""
    planilha = tmp_path / "contrato.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "CUSTO CIVIL"
    wb.save(planilha)
    mensagens = []
    cfg = {"obras_lineares": {"planilha": str(planilha), "aba": "Obras Lineares"}}
    assert ol.etapa(cfg, [], tmp_path, log=mensagens.append) is None
    assert any("Obras Lineares" in m and "NÃO CALCULADAS" in m for m in mensagens)
