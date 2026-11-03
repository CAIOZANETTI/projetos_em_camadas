"""Verificação da arquitetura entre dois commits: mede, junta a leitura qualitativa e gera um HTML único.

Uso:
    uv run python scripts/verificacao_noturna.py <base> [<alvo>] [--qualitativa arquivo.json] [--saida pasta]

O Python calcula tudo (métricas, contagens, veredito); o HTML só apresenta. A leitura qualitativa (regras,
arquitetura, plano) é feita por um revisor e chega pronta em JSON:
    {"itens": [{"grupo", "item", "estado": "OK|ATENÇÃO|DESVIO", "evidencia"}], "decisoes_do_caio": [...], "resumo": "..."}
Esta verificação só observa: não altera código, testes, gabaritos, plano nem arquitetura.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
# testes que guardam números de engenharia conferidos (gabaritos): mudança neles exige decisão registrada
GABARITOS = ("tests/test_obras_lineares.py", "tests/test_valas.py", "tests/test_gavetas.py", "tests/test_escavacao.py")
ESTADOS = ("DESVIO", "ATENÇÃO", "OK")


def rodar(comando: list[str], cwd: Path = RAIZ, env: dict | None = None) -> tuple[str, int, float]:
    """Saída (stdout + stderr), código de retorno e duração em segundos de um comando."""
    inicio = time.perf_counter()
    p = subprocess.run(comando, cwd=cwd, capture_output=True, text=True, env=env, check=False)
    return p.stdout + p.stderr, p.returncode, round(time.perf_counter() - inicio, 1)


def git(*args: str) -> str:
    return rodar(["git", *args])[0].strip()


def _ultimo_json(texto: str) -> dict:
    """O último objeto JSON impresso por um script (os scripts do projeto terminam com ele)."""
    fim = texto.rfind("}")
    for inicio in (m.start() for m in re.finditer(r"^\{", texto, re.MULTILINE)):
        try:
            return json.loads(texto[inicio:fim + 1])
        except json.JSONDecodeError:
            continue
    return {}


def medir_testes() -> dict:
    saida, codigo, segundos = rodar(["uv", "run", "pytest", "-q", "-p", "no:cacheprovider"])
    resumo = [li for li in saida.splitlines() if re.search(r"\d+ (passed|failed)", li)]
    contagem = {k: int(n) for n, k in re.findall(r"(\d+) (passed|failed|skipped|errors?)", resumo[-1] if resumo else "")}
    return {"passaram": contagem.get("passed", 0), "falharam": contagem.get("failed", 0) + contagem.get("error", 0)
            + contagem.get("errors", 0), "pulados": contagem.get("skipped", 0), "duracao_s": segundos, "ok": codigo == 0}


def medir_ruff() -> dict:
    saida, codigo, _ = rodar(["uv", "run", "ruff", "check", "camadas", "tests", "scripts"])
    erros = re.search(r"Found (\d+) error", saida)
    return {"ok": codigo == 0, "erros": int(erros.group(1)) if erros else 0,
            "linhas": [f"{cod} em {onde}" for cod, onde in re.findall(r"^([A-Z]+\d+) .*\n\s*-->\s*(\S+)", saida, re.MULTILINE)][:10]}


def medir_afericao() -> dict:
    saida, codigo, _ = rodar(["uv", "run", "python", "scripts/afericao.py"])
    d = _ultimo_json(saida)
    return {"ok": codigo == 0, "funcoes": d.get("funcoes"), "longas": d.get("longas", []),
            "pioras": [li for li in saida.splitlines() if "piorou" in li]}


def medir_determinismo() -> dict:
    saida, codigo, _ = rodar(["uv", "run", "python", "scripts/determinismo.py"])
    d = _ultimo_json(saida)
    return {"ok": codigo == 0, "indice_etapas": d.get("indice_etapas"), "indice_registros": d.get("indice_registros"),
            "etapas": d.get("etapas", {}), "licoes": d.get("licoes"), "licoes_com_teste": d.get("licoes_com_teste"),
            "tendencia": d.get("tendencia", {})}


def determinismo_na_base(base: str) -> dict:
    """Último registro de pdca/determinismo.jsonl no commit da base (o índice que valia então)."""
    linhas = [li for li in git("show", f"{base}:pdca/determinismo.jsonl").splitlines() if li.startswith("{")]
    return json.loads(linhas[-1]) if linhas else {}


def hash_referencia(commit: str | None) -> str | None:
    """Hash do conjunto de referência no commit (None = árvore atual), rodado numa worktree temporária."""
    if commit is None:
        return _ultimo_json(rodar(["uv", "run", "python", "-m", "camadas.referencia"])[0]).get("hash")
    with tempfile.TemporaryDirectory() as pasta:
        destino = Path(pasta) / "base"
        rodar(["git", "worktree", "add", "-q", "--detach", str(destino), commit])
        try:
            env = {**os.environ, "PYTHONPATH": str(destino)}
            saida = rodar(["uv", "run", "--project", str(RAIZ), "python", "-m", "camadas.referencia"], cwd=destino, env=env)[0]
            return _ultimo_json(saida).get("hash")
        finally:
            rodar(["git", "worktree", "remove", "--force", str(destino)])


def medir_vcm(base: str, alvo: str) -> dict:
    saida, codigo, _ = rodar(["vcm", "balanco", base, alvo])
    decisao = re.search(r"Decisão proposta: (\w+)", saida)
    cartao = re.search(r"Cartão HTML: (\S+)", saida)
    return {"ok": codigo == 0, "decisao": decisao.group(1) if decisao else None,
            "cartao": cartao.group(1) if cartao else None,
            "pioras": [li.strip() for li in saida.splitlines() if "piorou" in li and li.startswith("|")]}


def medir_git(base: str, alvo: str) -> dict:
    commits = git("log", "--first-parent", "--format=%h\t%s", f"{base}..{alvo}").splitlines()
    prs = sorted({int(n) for n in re.findall(r"#(\d+)", "\n".join(commits))})
    estat = git("diff", "--shortstat", base, alvo)
    numeros = {k: int(n) for n, k in re.findall(r"(\d+) (file|insertion|deletion)", estat)}
    return {"commits": len(git("log", "--format=%h", f"{base}..{alvo}").splitlines()), "prs": prs,
            "arquivos": numeros.get("file", 0), "inseridas": numeros.get("insertion", 0),
            "removidas": numeros.get("deletion", 0), "historia": [c.split("\t", 1) for c in commits][:40]}


def medir_gabaritos(base: str, alvo: str) -> list[dict]:
    """Linhas com número removidas ou trocadas nos testes-gabarito (asserts e constantes)."""
    achados = []
    for arquivo in GABARITOS:
        diff = git("diff", "-U0", base, alvo, "--", arquivo)
        removidas = [li[1:].strip() for li in diff.splitlines()
                     if li.startswith("-") and not li.startswith("---") and re.search(r"\d", li)]
        if removidas:
            achados.append({"arquivo": arquivo, "linhas_com_numero_alteradas": len(removidas), "exemplos": removidas[:3]})
    return achados


def medir_processo(base: str, alvo: str) -> dict:
    """Versões da janela × lições, ids duplicados e gasto dos agentes registrado na janela."""
    versoes_base = set(re.findall(r"^## (\d+\.\d+\.\d+)", git("show", f"{base}:CHANGELOG.md"), re.MULTILINE))
    cabecalhos = re.findall(r"^## (\d+\.\d+\.\d+)", git("show", f"{alvo}:CHANGELOG.md"), re.MULTILINE)
    novas = [v for v in cabecalhos if v not in versoes_base]
    licoes = [json.loads(li) for li in git("show", f"{alvo}:pdca/licoes.jsonl").splitlines() if li.startswith("{")]
    com_licao = {li.get("versao") for li in licoes}
    ids = Counter(li["id"] for li in licoes)
    return {"versoes_novas": novas, "versoes_sem_licao": [v for v in novas if v not in com_licao],
            "versoes_duplicadas": sorted(v for v, n in Counter(cabecalhos).items() if n > 1),
            "licoes_duplicadas": sorted(i for i, n in ids.items() if n > 1),
            "licoes_novas": len(licoes) - len([li for li in git("show", f"{base}:pdca/licoes.jsonl").splitlines() if li.startswith("{")]),
            "agentes": _gasto_agentes(base, alvo)}


def _gasto_agentes(base: str, alvo: str) -> list[dict]:
    """Execuções acrescentadas a results/agentes/execucoes.csv na janela, somadas por modelo."""
    cab = git("show", f"{alvo}:results/agentes/execucoes.csv").splitlines()[0]
    novas = [li[1:] for li in git("diff", "-U0", base, alvo, "--", "results/agentes/execucoes.csv").splitlines()
             if li.startswith("+") and not li.startswith("+++")]
    soma: dict[str, dict] = {}
    for linha in csv.DictReader(io.StringIO("\n".join([cab, *novas]))):
        m = soma.setdefault(linha.get("modelo") or "?", {"modelo": linha.get("modelo") or "?", "execucoes": 0, "tokens": 0})
        m["execucoes"] += 1
        m["tokens"] += int(float(linha.get("tokens") or 0))
    return sorted(soma.values(), key=lambda m: -m["tokens"])


def itens_medidos(m: dict) -> list[dict]:
    """Itens OK / ATENÇÃO / DESVIO que saem só das medições (sem leitura humana ou de IA)."""
    t, r, a, d, p = m["testes"], m["ruff"], m["afericao"], m["determinismo"], m["processo"]
    ref = m["referencia"]
    itens = [
        ("Medição", "Testes", "OK" if t["ok"] else "DESVIO", f"{t['passaram']} passaram, {t['falharam']} falharam, {t['pulados']} pulados ({t['duracao_s']} s)"),
        ("Medição", "Lint (ruff)", "OK" if r["ok"] else "ATENÇÃO", "limpo" if r["ok"] else f"{r['erros']} erro(s): " + "; ".join(r["linhas"][:3])),
        ("Medição", "Aferição (funções longas, fundas, duplicatas)", "OK" if a["ok"] else "ATENÇÃO", "aferição ok" if a["ok"] else "; ".join(a["pioras"]) or "falhou"),
        ("Medição", "Hash do conjunto de referência", "OK" if ref["igual"] else "ATENÇÃO",
         f"igual ao da base ({ref['alvo'][:12]}…)" if ref["igual"] else f"{(ref['base'] or '?')[:12]}… → {(ref['alvo'] or '?')[:12]}…: conferir a explicação no CHANGELOG"),
        ("Medição", "Balanço do vcm", {"MANTER": "OK", "REVERTER": "DESVIO"}.get(m["vcm"]["decisao"], "ATENÇÃO"),
         f"decisão proposta: {m['vcm']['decisao'] or 'não rodou'}"
         + "".join(f"; piorou: {' '.join(c.strip() for c in li.split('|')[1:2] + li.split('|')[4:7])}" for li in m["vcm"]["pioras"])),
        ("Medição", "Índice de determinismo (etapas)", "OK" if (d["indice_etapas"] or 0) >= (m["determinismo_base"].get("indice_etapas") or 0) else "ATENÇÃO",
         f"{m['determinismo_base'].get('indice_etapas')} → {d['indice_etapas']} (alvo {d['tendencia'].get('alvo')})"),
        ("Processo", "Lição formalizada por versão", "OK" if not p["versoes_sem_licao"] else "ATENÇÃO",
         f"{len(p['versoes_novas'])} versões novas; sem lição: {', '.join(p['versoes_sem_licao']) or 'nenhuma'}"),
        ("Processo", "Versões e lições sem colisão", "OK" if not (p["versoes_duplicadas"] or p["licoes_duplicadas"]) else "DESVIO",
         f"versões repetidas: {', '.join(p['versoes_duplicadas']) or 'nenhuma'}; lições repetidas: {', '.join(p['licoes_duplicadas']) or 'nenhuma'}"),
    ]
    itens += [("Gabaritos", f"Números alterados em {g['arquivo']}", "ATENÇÃO",
               f"{g['linhas_com_numero_alteradas']} linha(s); conferir se há decisão registrada. Ex.: {g['exemplos'][0][:90]}")
              for g in m["gabaritos"]]
    return [{"grupo": g, "item": i, "estado": e, "evidencia": ev, "origem": "medido"} for g, i, e, ev in itens]


def veredito(itens: list[dict]) -> tuple[str, dict]:
    contagem = Counter(i["estado"] for i in itens)
    texto = "COM DESVIOS" if contagem["DESVIO"] else "COM ATENÇÕES" if contagem["ATENÇÃO"] else "SEM DESVIO"
    return texto, {e: contagem.get(e, 0) for e in ESTADOS}


def medir(base: str, alvo: str) -> dict:
    m = {"base": git("rev-parse", "--short", base), "alvo": git("rev-parse", "--short", alvo),
         "versao_alvo": re.search(r'VERSAO = "([^"]+)"', git("show", f"{alvo}:camadas/__init__.py")).group(1),
         "git": medir_git(base, alvo), "testes": medir_testes(), "ruff": medir_ruff(), "afericao": medir_afericao(),
         "determinismo": medir_determinismo(), "determinismo_base": determinismo_na_base(base),
         "vcm": medir_vcm(base, alvo), "gabaritos": medir_gabaritos(base, alvo), "processo": medir_processo(base, alvo)}
    h_base, h_alvo = hash_referencia(base), hash_referencia(None)
    m["referencia"] = {"base": h_base, "alvo": h_alvo, "igual": h_base == h_alvo}
    return m


# ---------------------------------------------------------------- apresentação (só formata o que já foi calculado)

CSS = """
:root{--fundo:#f7f7f5;--papel:#fff;--texto:#1d1d1b;--suave:#6b6b66;--linha:#e3e2dd;--ok:#1f7a4d;--at:#a86200;--dv:#b42318;
--ok-f:#e6f4ec;--at-f:#fdf1dc;--dv-f:#fde8e6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--fundo:#141413;--papel:#1e1e1c;--texto:#ecebe6;--suave:#a3a29b;--linha:#33322f;
--ok:#5fc48f;--at:#f0b153;--dv:#f2837a;--ok-f:#173225;--at-f:#3a2a10;--dv-f:#3d1a17}}
:root[data-theme="dark"]{--fundo:#141413;--papel:#1e1e1c;--texto:#ecebe6;--suave:#a3a29b;--linha:#33322f;
--ok:#5fc48f;--at:#f0b153;--dv:#f2837a;--ok-f:#173225;--at-f:#3a2a10;--dv-f:#3d1a17}
*{box-sizing:border-box}body{margin:0;background:var(--fundo);color:var(--texto);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:32px 0 10px}
.sub{color:var(--suave);font-size:13px}.veredito{border-radius:10px;padding:16px 18px;margin:18px 0;border:1px solid var(--linha)}
.veredito b{font-size:20px}.v-DESVIO{background:var(--dv-f);border-color:var(--dv)}.v-ATENÇÃO{background:var(--at-f);border-color:var(--at)}
.v-OK{background:var(--ok-f);border-color:var(--ok)}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{background:var(--papel);border:1px solid var(--linha);border-radius:8px;padding:10px 12px}.kpi span{display:block;color:var(--suave);font-size:12px}
.kpi b{font-size:19px;font-variant-numeric:tabular-nums}.tab{overflow-x:auto;background:var(--papel);border:1px solid var(--linha);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13.5px}th,td{text-align:left;padding:7px 10px;border-bottom:1px solid var(--linha);vertical-align:top}
th{color:var(--suave);font-weight:600;font-size:12px}td.n{text-align:right;font-variant-numeric:tabular-nums}
.e{font-weight:700;font-size:12px;padding:2px 7px;border-radius:99px;white-space:nowrap}.e-OK{color:var(--ok);background:var(--ok-f)}
.e-ATENÇÃO{color:var(--at);background:var(--at-f)}.e-DESVIO{color:var(--dv);background:var(--dv-f)}
code{font-size:12.5px}ul{padding-left:20px}li{margin:4px 0}
"""


def _e(texto) -> str:
    return html.escape(str(texto))


def _tabela(cabecalho: list[str], linhas: list[list[str]], numericas: set[int] = frozenset()) -> str:
    th = "".join(f"<th>{_e(c)}</th>" for c in cabecalho)
    corpo = "".join("<tr>" + "".join(f'<td class="n">{c}</td>' if k in numericas else f"<td>{c}</td>"
                                      for k, c in enumerate(li)) + "</tr>" for li in linhas)
    return f'<div class="tab"><table><thead><tr>{th}</tr></thead><tbody>{corpo}</tbody></table></div>'


def _numero(x, casas: int = 0) -> str:
    return "—" if x is None else f"{x:,.{casas}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_html(m: dict, quali: dict, itens: list[dict]) -> str:
    texto, contagem = veredito(itens)
    classe = "DESVIO" if contagem["DESVIO"] else "ATENÇÃO" if contagem["ATENÇÃO"] else "OK"
    g, t, d, db = m["git"], m["testes"], m["determinismo"], m["determinismo_base"]
    kpis = [("Commits", _numero(g["commits"])), ("PRs na main", _numero(len(g["prs"]))), ("Versão", m["versao_alvo"]),
            ("Testes", f"{t['passaram']} ✓ / {t['falharam']} ✗"), ("Determinismo (etapas)", _numero(d["indice_etapas"], 3)),
            ("Lições novas", _numero(m["processo"]["licoes_novas"])), ("Balanço vcm", m["vcm"]["decisao"] or "—")]
    ordem = {e: k for k, e in enumerate(ESTADOS)}
    linhas = [[_e(i["grupo"]), _e(i["item"]), f'<span class="e e-{i["estado"]}">{_e(i["estado"])}</span>', _e(i["evidencia"]),
               _e(i.get("origem", "revisor"))] for i in sorted(itens, key=lambda i: (ordem[i["estado"]], i["grupo"]))]
    metricas = [["Índice de determinismo (etapas)", _numero(db.get("indice_etapas"), 3), _numero(d["indice_etapas"], 3)],
                ["Índice de determinismo (registros)", _numero(db.get("indice_registros"), 3), _numero(d["indice_registros"], 3)],
                ["Etapas código / IA / humano", " / ".join(str(db.get("etapas", {}).get(k, "—")) for k in ("codigo", "ia", "humano")),
                 " / ".join(str(d["etapas"].get(k, "—")) for k in ("codigo", "ia", "humano"))],
                ["Hash do conjunto de referência", f"<code>{_e((m['referencia']['base'] or '—')[:12])}</code>",
                 f"<code>{_e((m['referencia']['alvo'] or '—')[:12])}</code>"],
                ["Lições (com teste)", "—", f"{d['licoes']} ({d['licoes_com_teste']})"]]
    agentes = [[_e(a["modelo"]), _numero(a["execucoes"]), _numero(a["tokens"])] for a in m["processo"]["agentes"]]
    decisoes = "".join(f"<li>{_e(x)}</li>" for x in quali.get("decisoes_do_caio", [])) or "<li>Nenhuma.</li>"
    historia = [[f"<code>{_e(h)}</code>", _e(s)] for h, s in g["historia"]]
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Verificação da arquitetura</title><style>{CSS}</style></head><body><main>
<h1>Verificação da arquitetura — projetos_em_camadas</h1>
<div class="sub">{_e(m['data'])} · janela <code>{_e(m['base'])}</code> → <code>{_e(m['alvo'])}</code> (versão {_e(m['versao_alvo'])}) ·
{_numero(g['arquivos'])} arquivos, +{_numero(g['inseridas'])} / −{_numero(g['removidas'])} linhas</div>
<div class="veredito v-{classe}"><b>{_e(texto)}</b> · {contagem['DESVIO']} desvio(s), {contagem['ATENÇÃO']} atenção(ões), {contagem['OK']} ok
<p>{_e(quali.get('resumo', ''))}</p></div>
<div class="kpis">{''.join(f'<div class="kpi"><span>{_e(k)}</span><b>{_e(v)}</b></div>' for k, v in kpis)}</div>
<h2>O que o Caio precisa decidir</h2><ul>{decisoes}</ul>
<h2>Itens verificados</h2>{_tabela(['Grupo', 'Item', 'Estado', 'Evidência', 'Origem'], linhas)}
<h2>Métricas: base × agora</h2>{_tabela(['Métrica', 'Base', 'Agora'], metricas, {1, 2})}
<h2>Gasto dos agentes registrado na janela</h2>{_tabela(['Modelo', 'Execuções', 'Tokens'], agentes, {1, 2}) if agentes else '<p class="sub">Nenhuma execução registrada.</p>'}
<h2>Histórico da janela (primeiro pai)</h2>{_tabela(['Commit', 'Mensagem'], historia)}
<p class="sub">Gerado por <code>scripts/verificacao_noturna.py</code>: o Python mede e decide o veredito; esta página só apresenta.
Cartão do vcm: <code>{_e(m['vcm']['cartao'] or '—')}</code>.</p>
</main></body></html>"""


def main(argv: list[str] | None = None) -> Path:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("base")
    ap.add_argument("alvo", nargs="?", default="HEAD")
    ap.add_argument("--qualitativa", type=Path)
    ap.add_argument("--saida", type=Path, default=RAIZ / "results" / "verificacoes")
    a = ap.parse_args(argv)
    m = medir(a.base, a.alvo)
    m["data"] = datetime.now(UTC).astimezone().date().isoformat()
    quali = json.loads(a.qualitativa.read_text(encoding="utf-8")) if a.qualitativa else {}
    itens = itens_medidos(m) + [{**i, "origem": "revisor"} for i in quali.get("itens", [])]
    a.saida.mkdir(parents=True, exist_ok=True)
    destino = a.saida / f"{m['data']}.html"
    destino.write_text(gerar_html(m, quali, itens), encoding="utf-8")
    (a.saida / f"{m['data']}.json").write_text(json.dumps({"medicoes": m, "itens": itens, "veredito": veredito(itens)},
                                                         ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    print(f"{veredito(itens)[0]}: {destino}")
    return destino


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
