import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bancada_calculo as bc

CHAVES = {"rodada", "data", "km", "semente", "python", "pyarrow", "numpy"} | set(bc.CHAVES_MEDIDAS)


def _linha(**mudancas):
    base = {"km": 100, "t_calculo_1_s": 30.0, "t_calculo_2_s": 1.0, "recalculados_2": 0, "recalculados_3": 1,
            "t_montar_s": 2.0, "pico_rss_mb": 500.0}
    return {**base, **mudancas}


def test_bancada_roda_numa_carga_pequena():
    pytest.importorskip("pyarrow")
    linhas = bc.rodar([0.2], 0, avisar=lambda *_: None)
    assert len(linhas) == 1
    l = linhas[0]
    assert CHAVES <= set(l)
    assert l["recalculados_2"] == 0 and l["recalculados_3"] == 1
    assert l["n_objetos"] > 0 and l["n_servicos"] > 0 and l["bytes"] > 0 and l["pico_rss_mb"] > 0
    assert "| 0.2 |" in bc.quadro(linhas)


def test_avaliar_aprova_quando_todos_passam():
    r = bc.avaliar([_linha(km=5, t_calculo_1_s=999.0), _linha()])
    assert r["passou"] and len(r["motivos"]) == 6
    assert all("limite" in m and "medido" in m and "passou" in m for m in r["motivos"])


@pytest.mark.parametrize("mudanca", [
    {"t_calculo_1_s": 61.0, "t_calculo_2_s": 1.0},
    {"t_calculo_2_s": 3.5},                       # 3,5 > 10 % de 30
    {"recalculados_2": 1},
    {"recalculados_3": 2},
    {"recalculados_3": 0},
    {"t_montar_s": 5.5},
    {"pico_rss_mb": 1024.0},
])
def test_avaliar_reprova_cada_criterio(mudanca):
    r = bc.avaliar([_linha(**mudanca)])
    assert not r["passou"]
    assert sum("REPROVOU" in m for m in r["motivos"]) == 1


def test_avaliar_usa_a_maior_carga():
    r = bc.avaliar([_linha(km=5, pico_rss_mb=5000.0), _linha(km=100)])
    assert r["passou"]
