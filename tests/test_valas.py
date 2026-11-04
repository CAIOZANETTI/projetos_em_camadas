import numpy as np
import pytest
import shapely
from shapely.geometry import LineString

from camadas import lineares, valas

M = np.array([[1.0, 0, 0], [0, 1.0, 0]])               # pt = m, para o teste


def _traco(layer, pts, cheio=False):
    return {"layer": layer, "partes": [np.asarray(pts, float)], "preenchimento": (0, 0, 0) if cheio else None}


def _classes(tubo_y, linhas_y, criterio="divisas"):
    am = valas.amostras([_traco("T", [(0, tubo_y), (100, tubo_y)])], "T", M)
    lim = shapely.union_all([LineString([(-10, y), (110, y)]) for y in linhas_y])
    return set(valas.classificar(am, criterio, {"limite": lim})[0])


def test_faixa_preenchida_vira_eixo_com_o_comprimento_certo():
    faixa = [_traco("T", [(0, 9.8), (100, 9.8), (100, 10.2)], True), _traco("T", [(0, 9.8), (100, 10.2), (0, 10.2)], True)]
    am = valas.amostras(faixa, "T", M)
    assert am["peso"].sum() == pytest.approx(100, abs=2)
    assert np.abs(am["pts"][:, 1] - 10).max() < 0.05     # no eixo, não na borda


def test_rede_em_linha_descarta_letras_do_mesmo_layer():
    letras = [_traco("R", [(x, 5), (x + 0.15, 5.3)]) for x in np.arange(10, 30, 0.5)]
    am = valas.amostras([_traco("R", [(0, 0), (50, 0)]), *letras], "R", M, linha=True)
    assert am["peso"].sum() == pytest.approx(50, abs=1)


def test_divisas_pista_calcada_e_fora():
    assert _classes(0, [1, 3, -6, -12]) == {"pista"}     # entre os meios-fios
    assert _classes(2, [1, 3, -6, -12]) == {"calcada"}   # entre meio-fio (1) e alinhamento (3)
    assert _classes(5, [1, 3, -6, -12]) == {"fora_da_via"}
    assert _classes(0, [4, -4]) == {"via_sem_meio_fio"}  # só cercas, vão de 8 m


def test_meio_fio_e_alinhamento_em_layers_separados():
    assert valas.classe_meio_fio([1.0], [6.0], [3.0], [12.0]) == "pista"
    assert valas.classe_meio_fio([1.0], [1.0, 8.0], [3.0], [12.0]) == "pista"
    assert valas.classe_meio_fio([2.0], [0.5], [1.0], [8.0]) == "calcada"
    assert valas.classe_meio_fio([], [3.0], [2.0], [5.0]) == "calcada"         # alinhamento × meio-fio
    assert valas.classe_meio_fio([], [8.0], [2.0], [5.0]) == "fora_da_via"     # no lote, entre alinhamentos


def test_quadras():
    assert _classes(0, [6.5, -6.5], "quadras") == {"pista"}
    assert _classes(4.5, [6.5, -6.5], "quadras") == {"calcada"}
    assert _classes(10, [6.5, -6.5], "quadras") == {"fora_da_via"}


def test_quadro_da_vala():
    # D2, plano da rodada 25: gabarito muda da NBR 12266 (b = DE + 0,60) para o MOS Sanepar (L = D + SL + X + Y).
    # Antes (NBR): largura 0,90, demolição e recomposição 12,0, volume 12,6. Agora (MOS, FD DN 300, vala de 1,40 m
    # escorada): largura 0,75, demolição e recomposição 10,5, volume 10,5. A profundidade (1,40 m) não mudou.
    q = valas.quantificar(["pista"] * 10, np.ones(10), 0.3)[0]
    assert q["largura_m"] == pytest.approx(0.75, abs=0.001) and q["profundidade_m"] == pytest.approx(1.4, abs=0.001)
    assert q["demolicao_m2"] == pytest.approx(10.5, abs=0.05) and q["recomposicao_m2"] == pytest.approx(10.5, abs=0.05)
    assert q["volume_vala_m3"] == pytest.approx(10.5, abs=0.05)
    coberta = valas.quantificar(["pavimentado"] * 4, np.ones(4), 0.3, ["asfalto novo"] * 4)[0]
    assert coberta["demolicao_m2"] > 0 and coberta["recomposicao_m2"] == 0 and "urbanização" in coberta["recomposicao"]
    verde = valas.quantificar(["vegetacao"], np.ones(1), 0.3)[0]
    assert verde["demolicao_m2"] == 0 and verde["recomposicao_m2"] > 0


def test_superficie_pela_cor_da_ortofoto():
    img = np.zeros((40, 160, 3), np.uint8)
    img[:, 0:40] = (60, 140, 70)        # BGR: grama
    img[:, 40:80] = (110, 113, 120)     # asfalto
    img[:, 80:120] = (50, 66, 100)      # terra vermelha
    img[:, 120:160] = 255               # fora da ortofoto
    orto = {"img": img, "e0": 0.0, "n1": 4.0, "res": 0.1}
    pts = np.array([[2.0, 2.0], [6.0, 2.0], [10.0, 2.0], [14.0, 2.0]])
    assert valas.classe_ortofoto(pts, orto) == ["vegetacao", "pavimentado", "solo", "sem_ortofoto"]


def test_camada_do_mapa_soma_a_extensao_da_rede():
    """Faixa amostrada dos dois lados (peso de meio passo): a extensão por superfície na camada do mapa soma a da
    rede, não o dobro (AAT00 saía 6 518 m para 3 259 m)."""
    faixa = [_traco("T", [(0, 9.8), (100, 9.8), (100, 10.2)], True), _traco("T", [(0, 9.8), (100, 10.2), (0, 10.2)], True)]
    am = valas.amostras(faixa, "T", M)
    cl = next(iter(valas.REGRAS["classes"]))
    rede = {"id": "R", "de_mm": 300, "fonte_de": "", "criterio": "divisas", "extensao_m": round(float(am["peso"].sum()), 1),
            "pts": am["pts"], "tang": am["tang"], "peso": am["peso"], "classes": [cl] * len(am["pts"]), "quadro": []}
    h = valas.para_html([rede], {}, None, 31982)
    assert sum(f["properties"]["extensao_m"] for f in h["geojson"]["features"]) == pytest.approx(rede["extensao_m"], abs=0.2)


def test_largura_e_profundidade_vem_do_dimensionador_unico():
    d = lineares.dimensionar_vala({"local": "x", "dn_mm": 300, "material": "FD", "prof_m": 1.4, "comp_m": 1.0,
                                   "metodo": "VCA"})
    q = valas.quantificar(["pista"] * 4, np.ones(4), 0.3)[0]
    assert q["largura_m"] == pytest.approx(d["largura_m"], abs=0.001)
    assert q["profundidade_m"] == pytest.approx(d["profundidade_m"], abs=0.001)
    assert valas.secao("pista", 0.3) == pytest.approx((d["largura_m"], d["profundidade_m"]), abs=0.001)
    assert q["escorado"] is True and q["tipo_escoramento"] == d["tipo_escoramento"]


def test_material_padrao_avisa_e_material_declarado_nao():
    padrao = valas.quantificar(["pista"], np.ones(1), 0.3)[0]
    assert padrao["material"] == "FD" and padrao["dn_mm"] == 300
    assert any("material de premissa" in a for a in padrao["alertas"])
    pead = valas.quantificar(["pista"], np.ones(1), 0.3, material="PEAD", dn_mm=315)[0]
    assert pead["material"] == "PEAD" and pead["dn_mm"] == 315
    assert not any("material de premissa" in a for a in pead["alertas"])


def test_fora_da_tabela_do_mos_cai_na_largura_da_nbr_com_alerta():
    q = valas.quantificar(["pista"], np.ones(1), 3.0, material="FD", dn_mm=3000)[0]
    assert q["largura_m"] == pytest.approx(3.6, abs=0.001)
    assert any("Tabela I do MOS" in a for a in q["alertas"])


def _rede_sintetica(criterio="divisas", finais=None):
    n = 40
    pts = np.c_[np.arange(n) + 0.5, np.zeros(n)]
    classes = ["pista"] * 25 + ["calcada"] * 10 + ["vegetacao"] * 5
    return {"id": "R1", "de_mm": 300, "fonte_de": "teste", "criterio": criterio, "pranchas": ["P1", "P2"],
            "extensao_m": float(n), "pts": pts, "tang": np.tile([1.0, 0.0], (n, 1)), "peso": np.ones(n),
            "classes": classes, "finais": finais, "quadro": []}


def test_quantificar_gavetas_bate_com_quantificar():
    r = _rede_sintetica(finais=[None] * 35 + ["grama"] * 5)
    q = valas.quantificar(r["classes"], r["peso"], 0.3, r["finais"])
    g = valas.quantificar_gavetas({"classes_por_metro": r["classes"], "pesos_m": r["peso"].tolist(), "de_mm": 300,
                                   "finais": r["finais"]})
    assert g["alertas"] == [] and sum(g["volume_vala_m3"].values()) == pytest.approx(sum(x["volume_vala_m3"] for x in q))
    assert sum(g["demolicao_m2"].values()) == pytest.approx(sum(x["demolicao_m2"] for x in q))
    assert sum(g["recomposicao_m2"].values()) == pytest.approx(sum(x["recomposicao_m2"] for x in q))
    assert "vegetacao/grama" in g["volume_vala_m3"] and "vegetacao/grama" not in g["recomposicao_m2"]
    verde = valas.quantificar_gavetas({"classes_por_metro": ["vegetacao"], "pesos_m": [1], "de_mm": 300})
    assert "vegetacao" not in verde["demolicao_m2"] and "vegetacao" in verde["recomposicao_m2"]


def test_etapa_devolve_as_redes_calculadas(monkeypatch, tmp_path):
    r = _rede_sintetica()
    monkeypatch.setattr(valas, "ortofoto", lambda caminho: None)
    monkeypatch.setattr(valas, "rede", lambda *a, **k: r)
    saida: list = []
    pacote = valas.etapa({"valas": {"redes": [{"id": "R1", "pranchas": ["P1"], "criterio": "divisas", "de_mm": 300}]}},
                         [], [], None, tmp_path, 31982, log=lambda *_: None, redes_saida=saida)
    assert saida == [r] and pacote["redes"][0]["id"] == "R1"


def test_rede_devolve_os_layers_lidos(monkeypatch):
    tracos = [_traco("T", [(0, 10), (100, 10)]), _traco("T2", [(0, 20), (100, 20)]),
              _traco("LIM", [(0, 5), (100, 5)]), _traco("LIM", [(0, 15), (100, 15)])]
    monkeypatch.setattr(valas.pdf_cad, "extrair", lambda pdf, clip=None: tracos)
    pranchas = {pid: {"id": pid, "pdf": "x.pdf", "layer_tubo": layer, "M": np.eye(3), "clip": None, "clip_mapa": None}
                for pid, layer in (("P1", "T"), ("P2", "T2"))}
    v = valas.rede({"id": "R1", "pranchas": ["P1", "P2"], "criterio": "divisas", "de_mm": 300, "layer_limite": "LIM"},
                   pranchas, None, None)
    assert v["layers"] == ["T", "T2", "LIM"]
    v = valas.rede({"id": "R2", "pranchas": ["P1"], "criterio": "divisas", "de_mm": 300, "layer": "T", "layer_limite": "LIM"},
                   pranchas, None, None)
    assert v["layers"] == ["T", "LIM"]


def _tubo_de_dois_contornos(y, largura, barras, vao=0.16, comp=7.0, layer="G"):
    """Tubo horizontal em y (eixo) com `barras` peças de `comp` m separadas por `vao` (a bolsa não tem contorno)."""
    x, saida = 0.0, []
    for _ in range(barras):
        saida += [_traco(layer, [(x, y - largura / 2), (x + comp, y - largura / 2)]),
                  _traco(layer, [(x, y + largura / 2), (x + comp, y + largura / 2)]),
                  _traco(layer, [(x + comp, y - largura), (x + comp, y + largura)])]    # junta, perpendicular ao tubo
        x += comp + vao
    return saida


def test_eixo_por_pares_mede_o_comprimento_exato_e_cobre_o_vao_das_bolsas():
    tracos = _tubo_de_dois_contornos(10, 1.048, 3) + _tubo_de_dois_contornos(30, 0.5, 2)   # o 2º tubo é outro DN
    am = valas.eixos_por_pares(tracos, "G", M, 1.048)
    assert am["peso"].sum() == pytest.approx(3 * 7.0 + 2 * 0.16, abs=0.001)      # barras + vãos, sem o tubo de 0,5 m
    assert np.abs(am["pts"][:, 1] - 10).max() < 1e-6                              # no eixo, não no contorno
    assert valas.eixos_por_pares(tracos, "G", M, 0.5)["peso"].sum() == pytest.approx(2 * 7.0 + 0.16, abs=0.001)


def test_eixo_por_pares_respeita_layer_janela_e_tolerancia():
    tracos = _tubo_de_dois_contornos(10, 1.048, 3) + _tubo_de_dois_contornos(40, 1.048, 1, layer="outro")
    assert valas.eixos_por_pares(tracos, "G", M, 1.048, [[-1, 0, 7.5, 20]])["peso"].sum() == pytest.approx(7.0, abs=0.001)
    assert valas.eixos_por_pares(tracos, "G", M, 1.048, tol=0.03, janelas_pt=[[-1, 0, 100, 20]])["peso"].sum() > 20
    assert len(valas.eixos_por_pares(tracos, "G", M, 1.20)["pts"]) == 0           # 14 % fora da tolerância
    diagonal = [_traco("G", [(0, 0), (10, 10)]), _traco("G", [(0.12, -0.12), (10.12, 9.88)])]   # par a 0,1697 m, 45°
    assert valas.eixos_por_pares(diagonal, "G", M, 0.17, tol=0.06)["peso"].sum() == pytest.approx(14.14, abs=0.02)
    assert len(valas.eixos_por_pares(diagonal, "G", M, 0.17, tol=0.0001)["pts"]) == 0


def test_rede_por_pares_leva_o_trecho_do_contrato_e_o_dn(monkeypatch):
    monkeypatch.setattr(valas.pdf_cad, "extrair", lambda pdf, clip=None: _tubo_de_dois_contornos(10, 1.048, 2))
    orto = {"img": np.full((40, 40, 3), (60, 140, 70), np.uint8), "e0": -5.0, "n1": 25.0, "res": 1.0}   # grama
    prancha = {"P": {"id": "P", "pdf": "x.pdf", "M": np.eye(3), "clip": None, "clip_mapa": None}}
    r = {"id": "T", "pranchas": ["P"], "layer": "G", "criterio": "ortofoto", "par_mm": 1048, "de_mm": 1048, "dn_mm": 1000,
         "material": "FD", "trecho_contrato": "ENTRADA DA ADUTORA DE ÁGUA BRUTA", "janelas_pt": [[-1, 0, 20, 20]]}
    v = valas.rede(r, prancha, orto, None)
    assert v["trecho_contrato"] == "ENTRADA DA ADUTORA DE ÁGUA BRUTA" and v["dn_mm"] == 1000 and v["material"] == "FD"
    assert v["extensao_m"] == pytest.approx(14.16, abs=0.05) and set(v["classes"]) == {"vegetacao"}
    assert valas.para_html([v], {}, None, 31982)["redes"][0]["trecho_contrato"] == r["trecho_contrato"]
    sem = valas.rede({k: x for k, x in r.items() if k != "trecho_contrato"}, prancha, orto, None)
    assert "trecho_contrato" not in sem                                           # as redes antigas não ganham campo


def test_obra_foz_declara_os_trechos_internos_da_eta():
    import json

    from camadas import pdf_cad
    obra = json.loads((pdf_cad.CONCEITOS.parent / "exemplos" / "foz" / "obra.json").read_text(encoding="utf-8"))
    trechos = [r for r in obra["valas"]["redes"] if r.get("trecho_contrato")]
    assert {r["trecho_contrato"] for r in trechos} == {
        "ENTRADA DA ADUTORA DE ÁGUA BRUTA", "SAÍDA DO LODO DECANTADO", "RETORNO LODO EEE FLOTOFILTRO",
        "DRENAGEM ACTIFLO 600 L/S", "INTERLIGAÇÃO: ADUTORA DE ÁGUA BRUTA COM MÓD. TRATAMENTO COM MICRO AREIA 360L",
        "INTERLIGAÇÃO: ADUTORA DE ÁGUA BRUTA COM MÓD. TRATAMENTO COM MICRO AREIA 600L",
        "INTERLIGAÇÃO:MÓD. TRATAMENTO COM MICRO AREIA 360L COM FILTROS EXISTENTES (VELHOS)"}
    assert all(r["material"] == "FD" and r["de_mm"] and r["dn_mm"] and r["fonte_de"] and r["janelas_pt"] for r in trechos)
    assert all(r["par_mm"] / 1000 <= r["de_mm"] / 1000 + 1e-9 for r in trechos)


def test_eixo_por_pares_recorta_o_contorno_que_atravessa_a_caixa_da_valvula():
    """Contorno de uma linha só de 0 a 30 m que passa por uma caixa (10 a 14 m): sem `recortar` a janela exige os dois
    extremos dentro dela e nada sobra; com `recortar` o contorno é cortado na parede e a caixa fica de fora."""
    tracos = _tubo_de_dois_contornos(10, 1.048, 1, comp=30.0)
    janelas = [[-1, 0, 10, 20], [14, 0, 31, 20]]
    assert len(valas.eixos_por_pares(tracos, "G", M, 1.048, janelas)["pts"]) == 0
    assert valas.eixos_por_pares(tracos, "G", M, 1.048, janelas, recortar=True)["peso"].sum() == pytest.approx(10 + 16, abs=0.001)
    sem_janela = valas.eixos_por_pares(tracos, "G", M, 1.048)["peso"].sum()
    assert sem_janela == pytest.approx(30.0, abs=0.001)                         # sem janela o recorte não muda nada
    assert valas.eixos_por_pares(tracos, "G", M, 1.048, [[-1, 0, 31, 20]], recortar=True)["peso"].sum() == pytest.approx(30.0, abs=0.001)
    # contorno que só toca a caixa por fora ou paralelo fora dela não entra
    assert len(valas.eixos_por_pares(tracos, "G", M, 1.048, [[40, 0, 50, 20]], recortar=True)["pts"]) == 0


def test_rede_com_janelas_recortadas_usa_o_parametro_da_rede(monkeypatch):
    monkeypatch.setattr(valas.pdf_cad, "extrair", lambda pdf, clip=None: _tubo_de_dois_contornos(10, 1.048, 1, comp=30.0))
    orto = {"img": np.full((40, 40, 3), (60, 140, 70), np.uint8), "e0": -5.0, "n1": 25.0, "res": 1.0}
    prancha = {"P": {"id": "P", "pdf": "x.pdf", "M": np.eye(3), "clip": None, "clip_mapa": None}}
    r = {"id": "T", "pranchas": ["P"], "layer": "G", "criterio": "ortofoto", "par_mm": 1048, "de_mm": 1048, "dn_mm": 1000,
         "janelas_pt": [[-1, 0, 10, 20], [14, 0, 31, 20]]}
    assert valas.rede(r, prancha, orto, None) is None                           # sem recorte: nenhum contorno cabe
    assert valas.rede({**r, "recortar_janelas": True}, prancha, orto, None)["extensao_m"] == pytest.approx(26.0, abs=0.05)


def test_obra_foz_leva_as_interligacoes_para_as_redes_e_tira_de_fora():
    import json

    from camadas import pdf_cad
    obra = json.loads((pdf_cad.CONCEITOS.parent / "exemplos" / "foz" / "obra.json").read_text(encoding="utf-8"))
    por_id = {p["id"]: p for p in obra["pranchas"]}
    inter = [r for r in obra["valas"]["redes"] if r["pranchas"][0] in ("f009", "f009_600", "f010")]
    assert sorted((r["pranchas"][0], r["dn_mm"]) for r in inter) == [("f009", 1000), ("f009_600", 1000), ("f010", 500), ("f010", 600)]
    de_iso2531 = {500: 532, 600: 635, 1000: 1048}
    for r in inter:
        assert por_id[r["pranchas"][0]].get("M_absoluta")                       # a afim vem da E1, não do ICP
        assert r["de_mm"] == r["par_mm"] == de_iso2531[r["dn_mm"]] and r["material"] == "FD" and r["criterio"] == "ortofoto"
        assert r["layer"] == "CISM_11_LINHA_TUBULAÇÃO 01" and r["janelas_pt"] and r["obs"] and r["fonte_de"]
    assert [r["recortar_janelas"] for r in inter if r["pranchas"] == ["f009_600"]] == [True]
    fora = " ".join(obra["valas"]["fora"])
    assert "módulo 360 L (folha 09" not in fora and "módulo 600 L (folha 09" not in fora   # saíram de `fora`
    assert "planta 600" in fora and "sem afim" in fora                                      # o que ficou de fora tem motivo
