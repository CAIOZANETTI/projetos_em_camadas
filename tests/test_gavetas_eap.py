"""Memória espacial, rodada 6: código completo da EAP codificada em cada serviço, unidade e sistema do objeto e
conciliação das duas EAP."""
import pytest
from test_gavetas import _base, _ev, _fato

from camadas import gavetas as gv


def _serv(saida, valor=1.0, chave=None, objeto="T01", **extra):
    sid = ":".join(x for x in (objeto, "r", saida, chave) if x)
    return {"servico_id": sid, "objeto_id": objeto, "regra": "vala_aberta", "versao_regra": "1", "saida": saida,
            "valor": valor, "unidade": gv.EAP["saidas"][saida]["unidade"], "fatos": [],
            **({"chave": chave} if chave else {}), **extra}


def test_codigo_eap_normal_por_chave_e_item_nulo():
    assert gv.codigo_eap(_serv("escavacao_m3"), "u1", "AB_ENTRADA") == "U1.AB_ENTRADA.GEO.MOV.VAL"
    assert gv.codigo_eap(_serv("pavimento_m2", chave="asfalto"), "u2", "AAT01") == "U2.AAT01.CIV.PAV.REC"
    assert gv.codigo_eap(_serv("pavimento_m2", chave="calcada"), "u1", "AB_ENTRADA") == "U1.AB_ENTRADA.CIV.PAV.CAL"
    assert gv.codigo_eap(_serv("demolicao_m2", chave="calcada/grama"), "u1", "ETA") == "U1.ETA.CIV.PAV.CAL"
    assert gv.codigo_eap(_serv("caximbos"), "u1", "AB_ENTRADA") is None            # sem item na EAP codificada
    assert gv.codigo_eap(_serv("area_cava_m2"), "u1", "ETA") is None
    assert gv.codigo_eap(_serv("escavacao_m3"), None, "ETA") is None               # falta unidade ou sistema
    assert gv.codigo_eap(_serv("escavacao_m3"), "u1", None) is None


def test_codigo_eap_tem_o_formato_de_eap_estrutura():
    eap = pytest.importorskip("camadas.eap")
    codigos = {n["codigo"] for n in eap.estrutura()}
    for saida, unidade, sistema, chave in [("escavacao_m3", "u1", "AB_ENTRADA", None), ("supressao_m2", "u1", "ETA", None),
                                           ("escavacao_cava_m3", "u1", "ACT600", None), ("reaterro_cava_m3", "u1", "FILTROS", None),
                                           ("pavimento_m2", "u1", "ETA", "calcada"), ("escavacao_m3", "u2", "AAT01", None),
                                           ("recomposicao_m2", "u2", "AAT01", "asfalto")]:
        codigo = gv.codigo_eap(_serv(saida, chave=chave), unidade, sistema)
        assert codigo in codigos, codigo


def test_todo_item_do_de_para_existe_na_eap_codificada():
    eap = pytest.importorskip("camadas.eap")
    itens = set(eap.itens())
    for nome, no in gv.EAP["saidas"].items():
        c = no["codigo_eap"]
        if c:
            assert {c["item"], *c.get("por_chave", {}).values()} <= itens, nome


def _base_us(local="Entrada de água bruta", setor_fatos=(), objeto_fora=False):
    """Um setor (x 0-50) e um trecho com `local`; o trecho está dentro do setor, ou fora dele."""
    quadro = [[0, 0], [50, 0], [50, 40], [0, 40], [0, 0]]
    linha = [[200, 20], [210, 20]] if objeto_fora else [[10, 20], [20, 20]]
    meta = {"crs_h": "EPSG:31982", "datum_v": "ortométrico"}
    fatos = [_fato("SET-A", p, v, "decidido", "E1") for p, v in setor_fatos]
    if local:
        fatos.append(_fato("T01", "local", local, "projetado"))
    return {"objetos": [{"objeto_id": "SET-A", "classe": "setor"}, {"objeto_id": "T01", "classe": "trecho_tubo"},
                        {"objeto_id": "SP-1", "classe": "furo_sondagem"}],
            "geometria": [{"objeto_id": "SET-A", "tipo": "poligono", "coords": quadro, **meta},
                          {"objeto_id": "T01", "tipo": "linha", "coords": linha, **meta},
                          {"objeto_id": "SP-1", "tipo": "ponto", "coords": [1, 1], **meta}],
            "fatos": fatos, "evidencias": [_ev("E1")], "pendencias": [], "servicos": []}


def test_unidade_sistema_pelo_setor_vence_o_local_e_o_padrao():
    base = _base_us(setor_fatos=[("unidade", "u1"), ("sistema", "ACT600")])
    cfg = {"gavetas": {"unidade_sistema_padrao": {"unidade": "u2", "sistema": "AAT01"}}}
    mapa, pend = gv.unidade_sistema(base, gv.indice(base), cfg)
    assert mapa == {"T01": ("u1", "ACT600")} and pend == []          # sondagem não tem regra: fora do mapa


def test_unidade_sistema_pelo_local_com_chave():
    mapa, pend = gv.unidade_sistema(_base_us(), None, {})
    assert mapa == {"T01": ("u1", "AB_ENTRADA")} and pend == []


def test_unidade_sistema_pelo_padrao():
    base = _base_us(local="Trecho sem nome de sistema")
    cfg = {"gavetas": {"unidade_sistema_padrao": {"unidade": "u1", "sistema": "ETA"}}}
    assert gv.unidade_sistema(base, None, cfg) == ({"T01": ("u1", "ETA")}, [])


def test_unidade_sistema_sem_nenhum_e_pendencia():
    mapa, pend = gv.unidade_sistema(_base_us(local="Trecho sem nome de sistema"), None, {})
    assert mapa == {} and [(p["objeto_id"], p["motivo"]) for p in pend] == [("T01", "unidade e sistema não definidos")]
    assert gv.unidade_sistema(_base_us(local=None), None, {"gavetas": {}})[1][0]["motivo"] == "unidade e sistema não definidos"


def test_unidade_sistema_duas_chaves_e_pendencia():
    cfg = {"gavetas": {"unidade_sistema_padrao": {"unidade": "u1", "sistema": "ETA"}}}
    mapa, pend = gv.unidade_sistema(_base_us(local="Drenagem do pátio"), None, cfg)
    assert mapa == {}                                                  # o padrão não resolve a ambiguidade
    assert pend[0]["motivo"] == "mais de um sistema pelo local: DREN_DN400, DREN_DN300"


@pytest.mark.parametrize("fonte", ["setor", "padrao"])
def test_unidade_sistema_de_outra_unidade_e_pendencia(fonte):
    if fonte == "setor":
        base, cfg = _base_us(setor_fatos=[("unidade", "u2"), ("sistema", "ACT600")]), {}
    else:
        base = _base_us(local="x")
        cfg = {"gavetas": {"unidade_sistema_padrao": {"unidade": "u2", "sistema": "ACT600"}}}
    mapa, pend = gv.unidade_sistema(base, None, cfg)
    assert mapa == {} and pend[0]["motivo"] == "sistema ACT600 não pertence à unidade u2"
    inexistente = {"gavetas": {"unidade_sistema_padrao": {"unidade": "u1", "sistema": "XYZ"}}}
    assert "não existe" in gv.unidade_sistema(_base_us(local="x"), None, inexistente)[1][0]["motivo"]


def test_unidade_sistema_do_setor_do_servico_com_ponto():
    base = _base_us(objeto_fora=True, setor_fatos=[("unidade", "u1"), ("sistema", "ACT600")])
    servico = _serv("escavacao_cava_m3", valor=5.0, chave="c1", objeto="T01", ponto=[10, 10])
    mapa, pend = gv.unidade_sistema(base, None, {}, {servico["servico_id"]: "SET-A"}, [servico])
    assert mapa[servico["servico_id"]] == ("u1", "ACT600")           # o objeto está fora do setor; o ponto do serviço, dentro
    assert mapa["T01"] == ("u1", "AB_ENTRADA") and pend == []


def test_anotar_codigo_eap_marca_sem_codigo_e_so_pendencia_de_quem_tem_item():
    servicos = [_serv("escavacao_m3", objeto="A"), _serv("caximbos", objeto="B"), _serv("reaterro_m3", objeto="C")]
    pendencias = [{"objeto_id": "B", "regra": "r", "motivo": "unidade e sistema não definidos"},
                  {"objeto_id": "C", "regra": "r", "motivo": "unidade e sistema não definidos"}]
    sem_codigo, pend = gv.anotar_codigo_eap(servicos, {"A": ("u1", "ETA")}, pendencias)
    assert sem_codigo == {"caximbos": 1}
    assert [p["objeto_id"] for p in pend] == ["C"]                    # B não tem item: não é falta de unidade e sistema
    assert [s["codigo_eap"] for s in servicos] == ["U1.ETA.GEO.MOV.VAL", None, None]
    assert servicos[0]["servicos_eap"] == ["escavacao"] and servicos[1]["servicos_eap"] == []


def test_anotar_nao_muda_a_chave_do_incremental():
    base = _base()
    servicos, _, _ = gv.calcular_incremental(base)
    chaves = [s["chave_calculo"] for s in servicos]
    gv.anotar_codigo_eap(servicos, {"T01": ("u1", "AB_ENTRADA")}, [])
    novos, _, est = gv.calcular_incremental(base, servicos)
    assert est["recalculados"] == 0 and est["reaproveitados"] == 1
    assert [s["chave_calculo"] for s in novos] == chaves


def test_conciliar_eap_as_situacoes_e_so_a_medida_do_item():
    """Só a saída marcada `mede` entra (escavação de vala em GEO.MOV.VAL não soma com nada); item que as gavetas não
    medem (estacas) é "fora das gavetas"."""
    servicos = [dict(_serv("escavacao_cava_m3", 100.004), codigo_eap="U1.ACT600.GEO.MOV.ESC"),
                dict(_serv("escavacao_cava_m3", 50.0, objeto="T2"), codigo_eap="U1.ACT600.GEO.MOV.ESC"),
                dict(_serv("reaterro_cava_m3", 30.0), codigo_eap="U1.ACT600.GEO.MOV.REA"),
                dict(_serv("escavacao_cava_m3", 12.0, objeto="T3"), codigo_eap="U1.FILTROS.GEO.MOV.ESC"),
                dict(_serv("escavacao_m3", 7.0), codigo_eap="U1.ETA.GEO.MOV.VAL"),
                dict(_serv("reaterro_m3", 5.0), codigo_eap="U1.ETA.GEO.MOV.VAL"),
                dict(_serv("caximbos", 3.0), codigo_eap=None)]
    codificada = [{"codigo": "U1.ACT600.GEO.MOV.ESC", "grandeza": "volume", "unidade": "m³", "quantidade": 150.0},
                  {"codigo": "U1.ACT600.GEO.MOV.REA", "grandeza": "volume", "unidade": "m³", "quantidade": 25.0},
                  {"codigo": "U1.ACT360.GEO.MOV.ESC", "grandeza": "volume", "unidade": "m³", "quantidade": 80.0},
                  {"codigo": "U1.ACT600.GEO.FUN.EST", "grandeza": "contagem", "unidade": "un", "quantidade": 48.0}]
    linhas = {l["codigo"]: l for l in gv.conciliar_eap(servicos, codificada)}
    assert linhas["U1.ACT600.GEO.MOV.ESC"]["situacao"] == "confere"            # 150,004 contra 150,0: dentro de 0,01
    assert linhas["U1.ACT600.GEO.MOV.REA"]["situacao"] == "difere"
    assert linhas["U1.ACT600.GEO.MOV.REA"]["diferenca"] == pytest.approx(5.0)
    assert linhas["U1.FILTROS.GEO.MOV.ESC"]["situacao"] == "só nas gavetas"
    assert linhas["U1.ACT360.GEO.MOV.ESC"]["situacao"] == "só na EAP codificada"
    assert linhas["U1.ACT600.GEO.FUN.EST"]["situacao"] == "fora das gavetas"
    assert "U1.ETA.GEO.MOV.VAL" not in linhas                                  # vala: sem medida no item, não soma
    assert [l["codigo"] for l in gv.conciliar_eap(servicos, codificada)] == sorted(linhas)
    assert {l["situacao"] for l in gv.conciliar_eap(servicos, codificada, tol=10.0)
            if l["codigo"].endswith("MOV.REA")} == {"confere"}


def test_conciliar_eap_nao_mistura_unidades():
    servicos = [dict(_serv("escavacao_cava_m3", 10.0), codigo_eap="U1.ETA.GEO.MOV.ESC")]           # m³
    codificada = [{"codigo": "U1.ETA.GEO.MOV.ESC", "grandeza": "area", "unidade": "m²", "quantidade": 10.0}]
    linhas = gv.conciliar_eap(servicos, codificada)
    assert [(l["unidade"], l["situacao"]) for l in linhas] == [("m²", "só na EAP codificada"), ("m³", "só nas gavetas")]
