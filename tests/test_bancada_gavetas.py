import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bancada_gavetas as bg  # noqa: E402

CHAVES = {"rodada", "data", "km", "formato", "ordem", "bytes", "gravar_s", "ler_s", "ida_e_volta", "ram_mb",
          "consultas", "pyarrow", "duckdb", "repeticoes", "semente"}


def _linha(formato, bytes_=100, ler_s=1.0, ram=10.0, ida=True, p95=1.0, km=100, ordem="original", nativo_p95=None):
    q = {c: {"p50_ms": 0.1, "p95_ms": p95} for c in bg.CRITERIO["consultas"]}
    n = {c: {"p50_ms": 0.1, "p95_ms": nativo_p95 or p95} for c in bg.CRITERIO["consultas"]}
    return {"km": km, "formato": formato, "ordem": ordem, "bytes": bytes_, "ler_s": ler_s, "ram_mb": ram,
            "ida_e_volta": ida, "consultas": {"motor": q, "nativo": n}}


def test_bancada_roda_jsonl_e_csv_com_todas_as_chaves():
    pytest.importorskip("duckdb")
    linhas = bg.rodar([0.2], ["jsonl", "csv"], 1, 0, avisar=lambda *_: None)
    assert [(l["formato"], l["ordem"]) for l in linhas] == [(f, o) for f in ("jsonl", "csv") for o in bg.ORDENS]
    for l in linhas:
        assert CHAVES <= set(l) and l["ida_e_volta"] and l["bytes"] > 0
        assert set(l["consultas"]) == {"motor", "nativo"}
        for m in bg.MOTORES:
            assert set(l["consultas"][m]) == set(bg.CRITERIO["consultas"])
            assert all({"p50_ms", "p95_ms"} == set(q) for q in l["consultas"][m].values())
    assert "| jsonl | por_progressiva |" in bg.quadro(linhas)


def test_por_progressiva_ordena_e_mantem_o_conteudo():
    from camadas import sintetico
    base = sintetico.base_linear(1)
    ordenada = bg.ordenar(base)
    assert sorted(map(str, base["fatos"])) == sorted(map(str, ordenada["fatos"]))
    ids = [o["objeto_id"] for o in ordenada["objetos"]]
    assert ids[:2] == ["SP-001", "T00001"] and len(ids) == len(base["objetos"])


def test_formato_sem_dependencia_e_pulado_com_aviso(monkeypatch):
    avisos = []
    monkeypatch.setattr(bg, "dependencia_ok", lambda f: "falta pyarrow")
    assert bg.rodar([0.2], ["parquet"], 1, 0, avisar=avisos.append) == []
    assert "pulado" in avisos[0]


def test_decidir_reprova_sem_ida_e_volta():
    r = bg.decidir([_linha("jsonl"), _linha("csv", ida=False)])
    assert r["vencedor"]["formato"] == "jsonl"
    assert any(m.startswith("csv: reprovado no critério 1") for m in r["motivos"])


def test_decidir_reprova_p95_acima_de_50_ms_na_maior_carga():
    linhas = [_linha("jsonl", p95=80), _linha("csv", km=5, p95=80), _linha("csv"), _linha("parquet", p95=60, nativo_p95=10)]
    r = bg.decidir(linhas)
    assert any(m.startswith("jsonl: reprovado no critério 2") for m in r["motivos"])
    assert "csv: cumpre os critérios 1 e 2" in r["motivos"]
    assert "parquet: cumpre os critérios 1 e 2" in r["motivos"]     # o melhor entre motor comum e nativo


def test_decidir_ranking_por_soma_de_posicoes():
    linhas = [_linha("jsonl", 300, 3, 3), _linha("parquet", 100, 1, 1), _linha("duckdb", 200, 2, 2)]
    r = bg.decidir(linhas)
    assert [x["formato"] for x in r["ranking"]] == ["parquet", "duckdb", "jsonl"]
    assert r["ranking"][0]["soma_posicoes"] == 3
    assert r["vencedor"] == {"formato": "parquet", "ordem": "original"}


def test_decidir_desempate_por_menos_dependencias():
    linhas = [_linha("duckdb", 100, 1.0, 10), _linha("jsonl", 110, 1.1, 11), _linha("parquet", 105, 1.05, 10.5)]
    r = bg.decidir(linhas)
    assert r["ranking"][0]["formato"] == "duckdb"
    assert r["vencedor"]["formato"] == "jsonl"
    assert any("desempate" in m for m in r["motivos"])


def test_decidir_sem_aprovado_nao_tem_vencedor():
    r = bg.decidir([_linha("jsonl", ida=False)])
    assert r["vencedor"] is None and r["ranking"] == []


def test_ram_enxerga_a_memoria_nativa(tmp_path):
    """L017: o pico de RSS vê o pool do pyarrow, que o tracemalloc não vê."""
    pytest.importorskip("pyarrow")
    import tracemalloc
    from camadas import gavetas, sintetico
    gavetas.gravar(tmp_path, sintetico.base_linear(1), "parquet")
    tracemalloc.start()
    gavetas.ler(tmp_path, "parquet")
    python_mb = tracemalloc.get_traced_memory()[1] / 1e6
    tracemalloc.stop()
    assert bg.ram_subprocesso(tmp_path, "parquet") > python_mb
