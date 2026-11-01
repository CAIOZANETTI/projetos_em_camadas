import numpy as np
import pytest

from camadas import gavetas as gv
from camadas import sintetico as sn


@pytest.fixture(scope="module")
def base5():
    return sn.base_linear(5)


def _trechos(base):
    return [o for o in base["objetos"] if o["classe"] == "trecho_tubo"]


def _geom(base, classe):
    ids = {o["objeto_id"] for o in base["objetos"] if o["classe"] == classe}
    return [g for g in base["geometria"] if g["objeto_id"] in ids]


def test_5km_tem_250_trechos_26_furos_e_confere(base5):
    assert len(_trechos(base5)) == 250
    assert len([o for o in base5["objetos"] if o["classe"] == "furo_sondagem"]) == 26
    assert gv.conferir_base(base5) == []
    assert base5["pendencias"] == [] and base5["servicos"] == []


def test_comprimentos_e_progressivas(base5):
    geoms = _geom(base5, "trecho_tubo")
    comps = {f["objeto_id"]: f["valor"] for f in base5["fatos"] if f["propriedade"] == "comp_m"}
    assert sum(comps.values()) == pytest.approx(5000, abs=1e-6)
    assert all(c == pytest.approx(20, abs=1e-6) for c in comps.values())
    assert geoms[-1]["prog_fim_m"] == pytest.approx(5000, abs=1e-6)
    assert geoms[0]["prog_ini_m"] == 0 and all(a["prog_fim_m"] == b["prog_ini_m"] for a, b in zip(geoms, geoms[1:]))
    pavs = {f["objeto_id"]: f["valor"] for f in base5["fatos"] if f["propriedade"] == "pavimentos"}
    assert all(sum(p.values()) == pytest.approx(comps[o], abs=1e-6) for o, p in pavs.items())


def test_eixo_continuo_em_utm_com_curvas(base5):
    coords = np.vstack([g["coords"] for g in _geom(base5, "trecho_tubo")])
    passos = np.linalg.norm(np.diff(coords, axis=0), axis=1)
    assert passos[passos > 0].sum() == pytest.approx(5000, rel=1e-3)     # coordenadas arredondadas a 3 casas
    assert coords[0].tolist() == pytest.approx([500000, 7200000])
    assert np.linalg.norm(coords[-1] - coords[0]) < 5000                  # não é reta
    assert {g["crs_h"] for g in base5["geometria"]} == {"EPSG:31982"}


def test_furos_ao_lado_do_eixo_com_camadas_contiguas(base5):
    eixo = np.vstack([g["coords"] for g in _geom(base5, "trecho_tubo")])
    furos = _geom(base5, "furo_sondagem")
    assert all(g["tipo"] == "ponto" for g in furos)
    dist = [np.min(np.linalg.norm(eixo - g["coords"], axis=1)) for g in furos]
    assert 2.5 < min(dist) and max(dist) < 16
    for f in base5["fatos"]:
        if f["propriedade"] == "camadas":
            cs = f["valor"]
            assert 2 <= len(cs) <= 4 and cs[0]["de"] == 0
            assert all(a["ate"] == b["de"] for a, b in zip(cs, cs[1:]))
        assert f["natureza"] == ("observado" if f["objeto_id"].startswith("SP") else "projetado")


def test_determinismo():
    assert sn.base_linear(2, semente=7) == sn.base_linear(2, semente=7)
    assert sn.base_linear(2, semente=7) != sn.base_linear(2, semente=8)


def test_calcular_roda_sem_faltar_fato_e_cobre_todos_os_trechos():
    base = sn.base_linear(1)
    servicos, pendencias = gv.calcular(base)
    assert not [p for p in pendencias if "faltam fatos obrigatórios" in p["motivo"]]
    assert {s["objeto_id"] for s in servicos} >= {o["objeto_id"] for o in _trechos(base)}


def test_100km_gera_5000_trechos():
    base = sn.base_linear(100)
    assert len(_trechos(base)) == 5000
    assert len([o for o in base["objetos"] if o["classe"] == "furo_sondagem"]) == 501


def test_metadados():
    assert sn.metadados()["modulo"] == "sintetico"
