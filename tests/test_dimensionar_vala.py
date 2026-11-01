"""L3a: dimensionador único de vala (`lineares.dimensionar_vala`), com tolerância absoluta em metros."""

import copy

import numpy as np
import pytest

from camadas import gavetas as gv
from camadas import geotecnia as geo
from camadas import lineares
from camadas import obras_lineares as ol

TOL_M = 0.001
TRECHO = {
    "local": "Entrada de água bruta",
    "dn_mm": 1000,
    "material": "FD",
    "prof_m": 2.4,
    "comp_m": 57.3,
    "metodo": "VCA",
    "sond_ini": "SP-01",
    "sond_fim": "SP-01",
    "na_m": 9.0,
    "solo": "argila",
    "pavimentos": {"grama": 57.3},
    "supressao_frac": 1.0,
}
# perfil com a profundidade (terreno − fundo) em 0, 20 e 40 m
PERFIL = {
    "pontos": [
        {"estaca": "0+00,00", "progressiva_m": 0.0, "profundidade_m": 1.5},
        {"estaca": "1+00,00", "progressiva_m": 20.0, "profundidade_m": 2.5},
        {"estaca": "2+00,00", "progressiva_m": 40.0, "profundidade_m": 1.5},
    ],
    "nao_lidos": [],
    "fonte": "texto do PDF",
}
NOVAS = {
    "largura_m",
    "profundidade_m",
    "fonte_profundidade",
    "escorado",
    "tipo_escoramento",
    "escoramento_m2",
    "esgotamento_frac",
    "tipo_esgotamento",
    "alertas",
}


def _furo(descricao, na_m=None, nspt=None, fid="SP-01"):
    return {
        "id": fid,
        "E": 0.0,
        "N": 0.0,
        "na_m": na_m,
        "nspt": nspt or [],
        "camadas": [{"de": 0.0, "ate": 8.0, "descricao": descricao}],
    }


def _sem_alertas(q):
    return {k: v for k, v in q.items() if k != "alertas"}


# ---------------------------------------------------------------- saída: a de quantificar mais os acréscimos


@pytest.mark.parametrize("metodo", ["VCA", "MND"])
def test_contem_toda_a_saida_de_quantificar_com_os_mesmos_valores(metodo):
    trecho = {**TRECHO, "metodo": metodo}
    q, d = ol.quantificar(trecho), lineares.dimensionar_vala(trecho)
    assert NOVAS <= set(d) and set(q) <= set(d)
    assert {k: d[k] for k in q if k != "alertas"} == _sem_alertas(q)
    assert (
        d["alertas"][: len(q["alertas"])] == q["alertas"]
    )  # os de quantificar vêm primeiro, iguais


def test_quantificar_delega_a_regra_unica(monkeypatch):
    chamadas = []
    original = lineares.vala_do_trecho
    monkeypatch.setattr(
        lineares, "vala_do_trecho", lambda *a: chamadas.append(a) or original(*a)
    )
    ol.quantificar(TRECHO)
    assert len(chamadas) == 1


# ---------------------------------------------------------------- profundidade: perfil, trecho ou ausente


def test_profundidade_media_do_perfil_ponderada_pela_extensao():
    np.testing.assert_allclose(
        lineares.profundidade_do_perfil(PERFIL), 2.0, atol=TOL_M
    )  # 80 m² / 40 m
    np.testing.assert_allclose(
        lineares.profundidade_do_perfil(PERFIL, 10.0, 30.0), 2.25, atol=TOL_M
    )
    np.testing.assert_allclose(
        lineares.profundidade_do_perfil(PERFIL["pontos"], 0.0, 20.0), 2.0, atol=TOL_M
    )
    assert lineares.profundidade_do_perfil(PERFIL, 10.0, 45.0) is None  # não extrapola
    assert lineares.profundidade_do_perfil({"pontos": PERFIL["pontos"][:1]}) is None


def test_profundidade_vem_do_perfil_quando_ele_cobre_o_trecho():
    d = lineares.dimensionar_vala(
        {**TRECHO, "prof_m": 1.0, "p0_m": 10.0, "p1_m": 30.0}, perfil=PERFIL
    )
    assert d["fonte_profundidade"] == "perfil longitudinal"
    np.testing.assert_allclose(
        [d["profundidade_m"], d["prof_m"]], [2.25, 2.25], atol=TOL_M
    )
    esperado = ol.quantificar({**TRECHO, "prof_m": 2.25})
    np.testing.assert_allclose(
        [d["escavacao_m3"], d["largura_m"]],
        [esperado["escavacao_m3"], 2.10],
        atol=TOL_M,
    )
    assert d["escorado"] and not any("premissa" in a for a in d["alertas"])


def test_sem_comp_m_o_comprimento_e_a_extensao_do_trecho_no_perfil():
    trecho = {k: v for k, v in TRECHO.items() if k not in ("comp_m", "pavimentos")}
    d = lineares.dimensionar_vala({**trecho, "p0_m": 0.0, "p1_m": 40.0}, perfil=PERFIL)
    np.testing.assert_allclose(
        [d["comp_m"], d["profundidade_m"]], [40.0, 2.0], atol=TOL_M
    )


def test_perfil_que_nao_cobre_o_trecho_cai_na_premissa_com_alerta():
    d = lineares.dimensionar_vala({**TRECHO, "p0_m": 30.0, "p1_m": 60.0}, perfil=PERFIL)
    assert d["fonte_profundidade"] == "premissa do trecho (prof_m)"
    np.testing.assert_allclose(d["profundidade_m"], 2.4, atol=TOL_M)
    assert any("não cobre o trecho" in a for a in d["alertas"])
    assert any("profundidade de premissa" in a for a in d["alertas"])


def test_sem_perfil_a_profundidade_e_premissa_do_trecho_com_alerta():
    d = lineares.dimensionar_vala(TRECHO)
    assert d["fonte_profundidade"] == "premissa do trecho (prof_m)"
    assert any("profundidade de premissa" in a for a in d["alertas"])
    assert not ol.quantificar(TRECHO)[
        "alertas"
    ]  # quantificar segue sem alerta (gabarito)


def test_sem_profundidade_nao_inventa():
    d = lineares.dimensionar_vala({**TRECHO, "prof_m": None, "pavimentos": {}})
    assert d["profundidade_m"] is None and d["fonte_profundidade"] == "ausente"
    assert (
        d["tipo_escoramento"] is None
        and d["tipo_esgotamento"] is None
        and d.get("escavacao_m3") is None
    )
    assert any("sem profundidade" in a for a in d["alertas"])


# ---------------------------------------------------------------- escoramento: profundidade e agravantes


@pytest.mark.parametrize(
    "profundidade_m, esperado",
    [
        (1.0, "nenhum"),
        (1.25, "nenhum"),
        (1.26, "pontaleteamento"),
        (2.0, "pontaleteamento"),
        (2.5, "descontinuo"),
        (3.0, "descontinuo"),
        (4.0, "continuo"),
        (5.0, "especial"),
        (None, "nenhum"),
    ],
)
def test_tipo_de_escoramento_pela_profundidade(profundidade_m, esperado):
    assert lineares.tipo_escoramento(profundidade_m) == esperado


def test_agravante_eleva_ao_continuo_e_nao_rebaixa_o_especial():
    assert lineares.tipo_escoramento(1.5, ["solo mole"]) == "continuo"
    assert lineares.tipo_escoramento(5.0, ["solo mole"]) == "especial"
    assert (
        lineares.tipo_escoramento(1.0, ["solo mole"]) == "nenhum"
    )  # NR-18: até 1,25 m não é obrigatório


@pytest.mark.parametrize(
    "furo, motivo",
    [
        (_furo("Areia fina"), "solo não coesivo (areia)"),
        (_furo("Argila siltosa mole"), "solo mole (designação do laudo)"),
        (
            _furo("Argila siltosa rija", nspt=[[1.0, 3], [2.0, 9], [3.0, 2]]),
            "NSPT 3 < 4",
        ),  # o de 3 m está abaixo do fundo
        (_furo("Argila siltosa rija", na_m=1.8), "fundo abaixo do NA"),
    ],
)
def test_agravantes_do_modelo_geotecnico(furo, motivo):
    d = lineares.dimensionar_vala(
        TRECHO, [furo]
    )  # 2,40 m: descontínuo pela profundidade
    assert d["tipo_escoramento"] == "continuo" and motivo in d["agravantes_escoramento"]


def test_sem_agravante_fica_a_faixa_e_vala_rasa_com_agravante_so_alerta():
    d = lineares.dimensionar_vala(
        TRECHO, [_furo("Argila siltosa rija", nspt=[[1.0, 10]])]
    )
    assert d["tipo_escoramento"] == "descontinuo" and d["agravantes_escoramento"] == []
    rasa = lineares.dimensionar_vala(
        {**TRECHO, "prof_m": 1.0}, [_furo("Argila siltosa mole")]
    )
    assert rasa["tipo_escoramento"] == "nenhum" and not rasa["escorado"]
    assert any("conferir a estabilidade" in a for a in rasa["alertas"])


def test_mnd_nao_tem_tipo_de_escoramento():
    d = lineares.dimensionar_vala({**TRECHO, "metodo": "MND"}, [_furo("Areia fina")])
    assert (
        d["tipo_escoramento"] is None
        and d["largura_m"] is None
        and d["escoramento_m2"] == 0
    )


# ---------------------------------------------------------------- esgotamento: fração, bomba × ponteiras, alerta_na


@pytest.mark.parametrize(
    "descricao, na_m, altura_m, tipo",
    [
        ("Argila siltosa rija", None, 0.0, "nenhum"),
        (
            "Argila siltosa rija",
            2.0,
            0.4,
            "bomba",
        ),  # 0,40 m de água ≤ 0,50 m em solo coesivo
        ("Argila siltosa rija", 1.5, 0.9, "ponteiras"),  # 0,90 m de água
        ("Areia fina", 2.2, 0.2, "ponteiras"),  # pouca água, mas em areia
    ],
)
def test_esgotamento_bomba_ou_ponteiras(descricao, na_m, altura_m, tipo):
    d = lineares.dimensionar_vala(TRECHO, [_furo(descricao, na_m=na_m)])
    np.testing.assert_allclose(d["altura_agua_m"], altura_m, atol=TOL_M)
    assert d["tipo_esgotamento"] == tipo
    assert d["esgotamento_frac"] == (0.0 if na_m is None else 1.0)


def test_areia_so_acima_do_na_nao_pede_ponteiras():
    furo = {
        "id": "SP-01",
        "E": 0.0,
        "N": 0.0,
        "na_m": 2.1,
        "camadas": [
            {"de": 0.0, "ate": 1.0, "descricao": "Areia fina"},
            {"de": 1.0, "ate": 8.0, "descricao": "Argila siltosa"},
        ],
    }
    assert lineares.dimensionar_vala(TRECHO, [furo])["tipo_esgotamento"] == "bomba"


def test_fracao_do_trecho_abaixo_do_na_pelos_ids_da_planilha():
    furos = [_furo("Argila", fid="SP-01"), _furo("Argila", na_m=2.0, fid="SP-02")]
    d = lineares.dimensionar_vala({**TRECHO, "sond_fim": "SP-02"}, furos)
    np.testing.assert_allclose(d["esgotamento_frac"], 0.5, atol=TOL_M)
    assert d["tipo_esgotamento"] == "bomba"


def test_alerta_na_entra_nos_alertas_do_dimensionador():
    furo = _furo("Argila siltosa", na_m=2.7)  # fundo 2,40 m, 0,30 m acima do NA
    d = lineares.dimensionar_vala(TRECHO, [furo])
    assert d["esgotamento_frac"] == 0 and d["tipo_esgotamento"] == "nenhum"
    assert geo.alerta_na(furo, 2.4) in d["alertas"]
    assert geo.alerta_na(furo, 2.4) not in ol.quantificar(TRECHO, [furo])["alertas"]
    planilha = lineares.dimensionar_vala(
        {**TRECHO, "na_m": 2.6}
    )  # sem furo: o NA digitado
    assert any("NA da planilha" in a and "sazonal" in a for a in planilha["alertas"])


def test_na_de_projeto_respeita_a_margem(monkeypatch):
    furo = _furo("Argila siltosa", na_m=2.7)
    monkeypatch.setattr(
        geo, "MARGEM_NA_M", 0.5
    )  # NA de projeto 2,20 m: o fundo fica abaixo
    d = lineares.dimensionar_vala(TRECHO, [furo])
    assert d["esgotamento_frac"] == 1.0 and d["geotecnia"]["na_min_m"] == pytest.approx(
        2.2, abs=TOL_M
    )
    np.testing.assert_allclose(d["altura_agua_m"], 0.2, atol=TOL_M)


# ---------------------------------------------------------------- impressão da regra: fecho transitivo


def test_impressao_da_regra_ve_modulo_a_dois_niveis(monkeypatch):
    regra = next(iter(gv.SERVICOS["regras"]))
    antes = gv.impressao_regra(regra)
    assert gv.impressao_regra(regra) == antes  # determinística
    from camadas import geo as geo_utm

    diretos = {
        m.__name__
        for m in vars(ol).values()
        if hasattr(m, "__name__") and type(m).__name__ == "module"
    }
    assert (
        "camadas.geo" not in diretos and "camadas.valas" in diretos
    )  # obras_lineares → valas → geo
    monkeypatch.setattr(geo_utm, "REGRAS", {"constante": 1.0}, raising=False)
    assert gv.impressao_regra(regra) != antes


def test_impressao_da_regra_ve_as_premissas_do_dimensionador(monkeypatch):
    regra = next(iter(gv.SERVICOS["regras"]))
    antes = gv.impressao_regra(regra)
    regras = copy.deepcopy(lineares.REGRAS)
    regras["vala"]["agravantes"]["nspt_min"] = 5
    monkeypatch.setattr(lineares, "REGRAS", regras)
    assert gv.impressao_regra(regra) != antes


def test_impressao_da_vala_das_redes_ve_a_tabela_do_mos(monkeypatch):
    """Lição L026: a regra `vala_rede` mora em valas, que chama lineares, que importa obras_lineares (Tabela I do MOS)
    só dentro das funções; mudar a Tabela I tem de mudar a chave do serviço."""
    antes = gv.impressao_regra("vala_rede")
    regras = copy.deepcopy(ol.REGRAS)
    regras["constante_de_teste"] = 1.0
    monkeypatch.setattr(ol, "REGRAS", regras)
    assert gv.impressao_regra("vala_rede") != antes
