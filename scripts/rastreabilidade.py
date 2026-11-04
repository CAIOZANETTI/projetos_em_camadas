"""Tabela de rastreabilidade: cada versão do CHANGELOG com a data, o PR e o branch (a sessão) que a trouxe à main.

Percorre a linha principal da main (primeiro pai, do mais antigo ao mais novo) e registra, em cada commit, as versões
que aparecem no CHANGELOG pela primeira vez. Assim a versão renumerada num merge (a 0.19.0 de uma sessão que virou
0.20.0) fica com o PR que de fato a levou à main. PR em squash não traz o branch na mensagem: o nome vem de
`--ramos` (JSON {número do PR: branch}), se dado.

    python scripts/rastreabilidade.py                       # imprime a tabela em Markdown
    python scripts/rastreabilidade.py --gravar docs/RASTREABILIDADE.md --ramos ramos.json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

INICIO, FIM = "<!-- versoes:inicio -->", "<!-- versoes:fim -->"
CABECALHO = re.compile(r"^## (\d+\.\d+\.\d+) — (\S+) · (.*)$", re.MULTILINE)


def _git(*args: str, exigir: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True, check=exigir)
    return r.stdout if r.returncode == 0 else ""


def versoes_novas(linha_principal: list[tuple[str, str, str]], changelog_em) -> list[dict]:
    """[(hash, data, assunto)] do mais antigo ao mais novo; `changelog_em(hash)` devolve o CHANGELOG naquele commit.
    Uma linha por versão, no commit em que ela apareceu pela primeira vez."""
    vistos, out = set(), []
    for h, data, assunto in linha_principal:
        for versao, _, titulo in CABECALHO.findall(changelog_em(h)):
            if versao in vistos:
                continue
            vistos.add(versao)
            pr, ramo = re.search(r"#(\d+)", assunto), re.search(r"from \S+?/(\S+)", assunto)
            out.append({"versao": versao, "data": data, "pr": pr[1] if pr else None,
                        "ramo": ramo[1] if ramo else None, "commit": h[:7], "titulo": titulo.strip()})
    return sorted(out, key=lambda v: tuple(int(x) for x in v["versao"].split(".")))


def tabela(versoes: list[dict], ramos: dict | None = None) -> str:
    """Markdown: versão · data · PR · branch · tema (mais nova primeiro)."""
    ramos = ramos or {}
    linhas = ["| Versão | Data | PR | Branch (sessão) | Tema |", "|---|---|---|---|---|"]
    for v in reversed(versoes):
        ramo = v["ramo"] or ramos.get(v["pr"] or "") or "—"
        linhas.append(f"| {v['versao']} | {v['data']} | {'#' + v['pr'] if v['pr'] else '—'} | `{ramo}` | {v['titulo']} |")
    return "\n".join(linhas)


def linha_principal(ref: str) -> list[tuple[str, str, str]]:
    """[(hash, data, assunto)] da linha principal de `ref` (primeiro pai), do commit mais antigo ao mais novo."""
    saida = _git("log", "--first-parent", "--reverse", "--format=%H|%ad|%s", "--date=short", ref)
    return [tuple(x.split("|", 2)) for x in saida.splitlines()]


def regravar(caminho: Path, tabela_md: str) -> None:
    """Substitui, no Markdown, o trecho entre os marcadores de início e fim pela tabela."""
    s = caminho.read_text(encoding="utf-8")
    i, j = s.index(INICIO) + len(INICIO), s.index(FIM)
    caminho.write_text(s[:i] + "\n" + tabela_md + "\n" + s[j:], encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Versões do CHANGELOG × PR × branch, a partir do git")
    ap.add_argument("--ref", default="origin/main")
    ap.add_argument("--ramos", help="JSON {PR: branch} para os PRs em squash")
    ap.add_argument("--gravar", help="Markdown com os marcadores de início e fim da tabela, para substituir")
    a = ap.parse_args(argv)
    t = tabela(versoes_novas(linha_principal(a.ref), lambda h: _git("show", f"{h}:CHANGELOG.md", exigir=False)),
               json.loads(Path(a.ramos).read_text()) if a.ramos else None)
    if not a.gravar:
        print(t)
        return
    regravar(Path(a.gravar), t)
    print(f"{a.gravar}: tabela de versões regravada")


if __name__ == "__main__":
    main()
