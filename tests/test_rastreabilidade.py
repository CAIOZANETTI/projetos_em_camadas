import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("rastreabilidade", Path(__file__).parents[1] / "scripts" / "rastreabilidade.py")
rastreabilidade = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rastreabilidade)


def test_versao_renumerada_fica_com_o_pr_que_a_levou_a_main():
    """A 0.19.0 de uma sessão vira 0.20.0 no merge: cada versão é do commit da main em que aparece pela 1ª vez."""
    cl = {"a": "## 0.18.0 — 2026-10-30 · Actiflo\n",
          "b": "## 0.19.0 — 2026-10-30 · Arquitetura\n## 0.18.0 — 2026-10-30 · Actiflo\n",
          "c": "## 0.20.0 — 2026-10-30 · Relação de Desenhos\n## 0.19.0 — 2026-10-30 · Arquitetura\n## 0.18.0 — x · y\n"}
    lp = [("a" * 8, "2026-10-30", "Merge pull request #19 from X/sessao-um"),
          ("b" * 8, "2026-10-30", "Merge pull request #20 from X/sessao-dois"),
          ("c" * 8, "2026-10-30", "Rodada 19 (0.20.0) (#21)")]
    v = rastreabilidade.versoes_novas(lp, lambda h: cl[h[0]])
    assert [(x["versao"], x["pr"], x["ramo"]) for x in v] == [("0.18.0", "19", "sessao-um"), ("0.19.0", "20", "sessao-dois"),
                                                              ("0.20.0", "21", None)]
    t = rastreabilidade.tabela(v, {"21": "sessao-um"})
    assert t.splitlines()[2].startswith("| 0.20.0 | 2026-10-30 | #21 | `sessao-um` |")    # squash: branch pelo --ramos
