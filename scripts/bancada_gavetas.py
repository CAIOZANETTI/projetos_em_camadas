"""Bancada de formatos das gavetas (rodada 21, E3): mede cada formato de `gavetas` na carga sintética de uma adutora.

Por carga (km), formato e variante de ordem mede: tamanho em disco, tempo de gravação e de leitura (mediana de
`--repeticoes`), ida e volta sem perda, RAM de pico da leitura e três consultas (p50 e p95 de 200 sorteios), feitas pelo
motor comum (DuckDB lendo os arquivos gravados) e pela leitura nativa (`gavetas.ler` uma vez e Python puro).

Variantes de ordem: `original` grava as gavetas como o gerador as entrega; `por_progressiva` ordena objetos, geometria,
fatos e evidências pela progressiva do objeto (o furo entra pela progressiva do vértice do eixo mais próximo).

    python scripts/bancada_gavetas.py --km 5 100 --repeticoes 5 [--formatos jsonl csv] [--quadro quadro.md]
"""
import argparse
import importlib
import json
import statistics
import sys
import tempfile
import time
import subprocess
import tracemalloc
from datetime import date
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from camadas import gavetas, sintetico  # noqa: E402

# Critério fixado ANTES de medir (não espalhar pelo código; mudar aqui exige mudar o plano).
CRITERIO = {
    "fonte": "docs/plano/2026-10-31_rodada21.md §4 (Critério de decisão)",
    "consultas": ["fatos_objeto", "intervalo_prog", "furos_raio"],
    "p95_max_ms": 50.0,
    "motores_criterio_2": ["motor"],   # emenda de 01/11 (aceite do Fable): o nativo é Python puro sobre a base já lida
                                       # e não depende do formato; o critério 2 vale pelo motor comum (DuckDB no arquivo)
    "empate": 0.20,
    "ranking": ["bytes", "ler_s", "ram_mb"],
    "dependencias": {"jsonl": 0, "csv": 0, "parquet": 1, "geoparquet": 2, "duckdb": 3},
}
SORTEIOS = 200
RAIO_M = 60.0
JANELA_M = 100.0
ORDENS = ["original", "por_progressiva"]
MOTORES = ["motor", "nativo"]


# --------------------------------------------------------------------------------------------------------------------
# Variante de ordem
# --------------------------------------------------------------------------------------------------------------------

def progressivas(base: dict) -> dict:
    """Progressiva de cada objeto: a do trecho; a do furo é a do vértice do eixo mais próximo dele."""
    geoms = {g["objeto_id"]: g for g in base["geometria"]}
    prog = {i: g["prog_ini_m"] for i, g in geoms.items() if "prog_ini_m" in g}
    vertices = np.array([g["coords"][0] for g in geoms.values() if "prog_ini_m" in g])
    progs = np.array([g["prog_ini_m"] for g in geoms.values() if "prog_ini_m" in g])
    for i, g in geoms.items():
        if "prog_ini_m" not in g:
            prog[i] = float(progs[np.argmin(np.linalg.norm(vertices - g["coords"], axis=1))])
    return prog


def ordenar(base: dict) -> dict:
    """Objetos, geometria, fatos e evidências ordenados pela progressiva do objeto (estável; empate por id)."""
    prog = progressivas(base)

    def chave(campo):
        return lambda r: (prog.get(str(r[campo]).removeprefix("EV-"), float("inf")), str(r[campo]))

    return {**base, "objetos": sorted(base["objetos"], key=chave("objeto_id")),
            "geometria": sorted(base["geometria"], key=chave("objeto_id")),
            "fatos": sorted(base["fatos"], key=chave("objeto_id")),
            "evidencias": sorted(base["evidencias"], key=chave("evidencia_id"))}


# --------------------------------------------------------------------------------------------------------------------
# Sorteios e consultas
# --------------------------------------------------------------------------------------------------------------------

def sortear(base: dict, semente: int) -> dict:
    """Os mesmos sorteios para todos os formatos: objetos, janelas de 100 m e pontos do eixo."""
    rng = np.random.default_rng(semente)
    ids = [o["objeto_id"] for o in base["objetos"]]
    trechos = [g for g in base["geometria"] if "prog_ini_m" in g]
    fim = max(g["prog_fim_m"] for g in trechos)
    pontos = [trechos[i]["coords"][0] for i in rng.integers(0, len(trechos), SORTEIOS)]
    return {"fatos_objeto": [ids[i] for i in rng.integers(0, len(ids), SORTEIOS)],
            "intervalo_prog": [(a, a + JANELA_M) for a in rng.uniform(0, max(fim - JANELA_M, 1), SORTEIOS)],
            "furos_raio": pontos}


def consultas_nativas(base: dict) -> dict:
    """As três consultas em Python puro sobre a base lida."""
    geoms = base["geometria"]

    def fatos_objeto(oid):
        return [f for f in base["fatos"] if f["objeto_id"] == oid]

    def intervalo_prog(par):
        a, b = par
        return [g["objeto_id"] for g in geoms if g.get("prog_ini_m", b) < b and g.get("prog_fim_m", a) > a]

    def furos_raio(p):
        return [g["objeto_id"] for g in geoms if g["tipo"] == "ponto"
                and (g["coords"][0] - p[0]) ** 2 + (g["coords"][1] - p[1]) ** 2 <= RAIO_M ** 2]

    return {"fatos_objeto": fatos_objeto, "intervalo_prog": intervalo_prog, "furos_raio": furos_raio}


def _fonte(formato: str, pasta: Path, gaveta: str) -> str:
    """Trecho de SQL que lê a gaveta gravada no formato (o DuckDB lê os arquivos sem importar)."""
    arq = pasta / f"{gaveta}.{'parquet' if formato == 'geoparquet' else formato}"
    if formato == "jsonl":
        return f"read_json_auto('{arq}', format='newline_delimited')"
    if formato == "csv":
        return f"read_csv('{arq}', delim=';', header=true, all_varchar=true)"
    if formato in ("parquet", "geoparquet"):
        return f"read_parquet('{arq}')"
    return f'b."{gaveta}"'


def consultas_motor(formato: str, pasta: Path):
    """As três consultas em SQL (DuckDB) sobre os arquivos gravados; devolve (conexão, {nome: função})."""
    import duckdb
    con = duckdb.connect()
    if formato == "duckdb":
        con.execute(f"ATTACH '{pasta / 'base.duckdb'}' AS b (READ_ONLY)")
    txt = (lambda c: f"json_extract_string({c}, '$')") if formato == "csv" else (lambda c: c)
    num = lambda c: f"TRY_CAST({c} AS DOUBLE)"  # noqa: E731
    xy = lambda i: num(f"json_extract(CAST(coords AS JSON), '$[{i}]')")  # noqa: E731
    F, G = _fonte(formato, pasta, "fatos"), _fonte(formato, pasta, "geometria")
    sql = {"fatos_objeto": f"SELECT * FROM {F} WHERE {txt('objeto_id')} = ?",
           "intervalo_prog": f"SELECT {txt('objeto_id')} FROM {G} WHERE {num('prog_ini_m')} < ? AND {num('prog_fim_m')} > ?",
           "furos_raio": f"SELECT {txt('objeto_id')} FROM {G} WHERE {txt('tipo')} = 'ponto' "
                         f"AND power({xy(0)} - ?, 2) + power({xy(1)} - ?, 2) <= {RAIO_M ** 2}"}
    args = {"fatos_objeto": lambda x: [x], "intervalo_prog": lambda x: [x[1], x[0]],
            "furos_raio": lambda x: [x[0], x[1]]}
    return con, {n: (lambda x, n=n: con.execute(sql[n], args[n](x)).fetchall()) for n in sql}


def cronometrar(consulta, sorteios: list) -> dict:
    """p50 e p95 (ms) da consulta nos sorteios."""
    ms = []
    for s in sorteios:
        t = time.perf_counter()
        consulta(s)
        ms.append((time.perf_counter() - t) * 1000)
    return {"p50_ms": round(float(np.percentile(ms, 50)), 3), "p95_ms": round(float(np.percentile(ms, 95)), 3)}


# --------------------------------------------------------------------------------------------------------------------
# Medição
# --------------------------------------------------------------------------------------------------------------------

def dependencia_ok(formato: str) -> str | None:
    """Motivo de pular o formato (dependência que não importa), ou None."""
    for pacote in {"parquet": ["pyarrow"], "geoparquet": ["pyarrow", "shapely"], "duckdb": ["pyarrow", "duckdb"]}.get(formato, []):
        try:
            importlib.import_module(pacote)
        except ImportError:
            return f"falta {pacote}"
    return None


def _versao(pacote: str) -> str | None:
    try:
        return importlib.import_module(pacote).__version__
    except ImportError:
        return None


_RSS = """
import importlib, re, sys
from camadas import gavetas
for p in {"parquet": ["pyarrow"], "geoparquet": ["pyarrow", "shapely", "pyproj"], "duckdb": ["duckdb", "pyarrow"]}.get(sys.argv[2], []):
    importlib.import_module(p)
def kb(campo):
    return int(re.search(campo + r":\\s+(\\d+)", open("/proc/self/status").read()).group(1))
open("/proc/self/clear_refs", "w").write("5")   # zera o pico (VmHWM) depois dos imports
antes = kb("VmRSS")
gavetas.ler(sys.argv[1], sys.argv[2])
print(kb("VmHWM") - antes)
"""


def ram_subprocesso(pasta: Path, formato: str) -> float:
    """Crescimento do pico de RSS (MB) ao ler a base num processo novo, já com as bibliotecas importadas: enxerga a
    memória nativa do pyarrow e do DuckDB, que o tracemalloc não vê. Linux: o pico (VmHWM) é zerado por
    /proc/self/clear_refs depois dos imports."""
    raiz = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, "-c", _RSS, str(pasta), formato], capture_output=True, text=True, cwd=raiz,
                       check=True)
    return round(int(r.stdout.strip().splitlines()[-1]) / 1024, 2)


def medir_io(base: dict, formato: str, repeticoes: int) -> tuple[dict, Path, tempfile.TemporaryDirectory]:
    """Tamanho, gravação, leitura, ida e volta e RAM do formato; devolve também a pasta da última gravação."""
    tempos, tmp = [], None
    for _ in range(repeticoes):
        tmp = tempfile.TemporaryDirectory()
        t = time.perf_counter()
        arqs = gavetas.gravar(tmp.name, base, formato)
        tempos.append(time.perf_counter() - t)
    leituras, lida = [], None
    for _ in range(repeticoes):
        t = time.perf_counter()
        lida = gavetas.ler(tmp.name, formato)
        leituras.append(time.perf_counter() - t)
    tracemalloc.start()
    gavetas.ler(tmp.name, formato)
    pico = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    medidas = {"bytes": sum(a.stat().st_size for a in arqs), "gravar_s": round(statistics.median(tempos), 4),
               "ler_s": round(statistics.median(leituras), 4), "ida_e_volta": lida == base,
               "ram_mb": ram_subprocesso(Path(tmp.name), formato), "ram_python_mb": round(pico / 1e6, 2)}
    return medidas, Path(tmp.name), tmp


def medir_consultas(base: dict, formato: str, pasta: Path, semente: int) -> dict:
    """p50 e p95 das três consultas, pelo motor comum (DuckDB) e pelo nativo."""
    sorteios = sortear(base, semente)
    nativas = consultas_nativas(gavetas.ler(pasta, formato))
    con, motor = consultas_motor(formato, pasta)
    saida = {"nativo": {n: cronometrar(nativas[n], sorteios[n]) for n in nativas}}
    try:
        saida["motor"] = {n: cronometrar(motor[n], sorteios[n]) for n in motor}
    except Exception as erro:  # a leitura do formato pelo DuckDB falhou: fica registrado, a bancada segue
        saida["motor"], saida["erro_motor"] = None, f"{type(erro).__name__}: {str(erro)[:200]}"
    con.close()
    return saida


def medir(base: dict, km: float, formato: str, ordem: str, repeticoes: int, semente: int) -> dict:
    """Uma linha da bancada: (km, formato, ordem)."""
    escrita = ordenar(base) if ordem == "por_progressiva" else base
    io, pasta, tmp = medir_io(escrita, formato, repeticoes)
    linha = {"rodada": "rodada 21", "data": str(date.today()), "km": km, "formato": formato, "ordem": ordem,
             "repeticoes": repeticoes, "semente": semente, "pyarrow": _versao("pyarrow"), "duckdb": _versao("duckdb"),
             **io, "consultas": medir_consultas(base, formato, pasta, semente)}
    tmp.cleanup()
    return linha


def rodar(kms: list, formatos: list, repeticoes: int, semente: int, avisar=print) -> list[dict]:
    """Todas as linhas da bancada; formato sem dependência é pulado com aviso."""
    linhas = []
    for km in kms:
        base = sintetico.base_linear(km, semente=semente)
        for formato in formatos:
            motivo = dependencia_ok(formato)
            if motivo:
                avisar(f"AVISO: formato {formato} pulado ({motivo})")
                continue
            for ordem in ORDENS:
                linhas.append(medir(base, km, formato, ordem, repeticoes, semente))
                avisar(f"{km} km {formato:<10} {ordem:<16} ler {linhas[-1]['ler_s']}s")
    return linhas


# --------------------------------------------------------------------------------------------------------------------
# Decisão (critério do plano) e quadro
# --------------------------------------------------------------------------------------------------------------------

def _p95(linha: dict, consulta: str, motores: list = MOTORES) -> tuple[float, str]:
    """Melhor p95 entre os `motores` (motor comum e/ou nativo), e qual foi."""
    opcoes = [(linha["consultas"][m][consulta]["p95_ms"], m) for m in motores if linha["consultas"].get(m)]
    return min(opcoes) if opcoes else (float("inf"), "-")


def _reprovacao(linhas: list, maior: float, criterio: dict) -> str | None:
    """Motivo da reprovação do formato (ida e volta em qualquer carga; p95 na maior), ou None."""
    if not all(l["ida_e_volta"] for l in linhas):
        return "reprovado no critério 1: ida e volta com perda"
    lentas = []
    for l in (x for x in linhas if x["km"] == maior):
        lentas += [f"{c} {p:.1f} ms ({m})" for c in criterio["consultas"]
                   for p, m in [_p95(l, c, criterio.get("motores_criterio_2", MOTORES))]
                   if p > criterio["p95_max_ms"]]
    return f"reprovado no critério 2: p95 > {criterio['p95_max_ms']} ms em " + ", ".join(lentas) if lentas else None


def decidir(linhas: list[dict], criterio: dict = CRITERIO) -> dict:
    """Aplica o critério do plano: 1 ida e volta; 2 p95 ≤ limite nas três consultas na maior carga; 3 menor soma de
    posições em bytes, ler_s e ram_mb. Empate: dentro de `empate` do líder (soma das razões ao melhor de cada métrica),
    vence a que tem menos dependências. Devolve {"vencedor", "ranking", "motivos"}."""
    maior = max(l["km"] for l in linhas)
    motivos, aprovados = [], []
    for formato in dict.fromkeys(l["formato"] for l in linhas):
        do_formato = [l for l in linhas if l["formato"] == formato]
        erro = _reprovacao(do_formato, maior, criterio)
        motivos.append(f"{formato}: {erro}" if erro else f"{formato}: cumpre os critérios 1 e 2")
        aprovados += [] if erro else [l for l in do_formato if l["km"] == maior]
    ranking = _ranking(aprovados, criterio)
    return {"vencedor": _vencedor(ranking, criterio, motivos), "ranking": ranking, "motivos": motivos}


def _ranking(candidatas: list, criterio: dict) -> list[dict]:
    """Soma das posições (e das razões ao melhor) por (formato, ordem), do melhor para o pior."""
    if not candidatas:
        return []
    metricas = criterio["ranking"]
    posicoes = {id(l): 0 for l in candidatas}
    razoes = {id(l): 0.0 for l in candidatas}
    for m in metricas:
        ordem = sorted(candidatas, key=lambda l: l[m])
        melhor = max(ordem[0][m], 1e-12)
        for i, l in enumerate(ordem, 1):
            posicoes[id(l)] += i
            razoes[id(l)] += l[m] / melhor
    ranking = [{"formato": l["formato"], "ordem": l["ordem"], "soma_posicoes": posicoes[id(l)],
                "soma_razoes": round(razoes[id(l)], 3), **{m: l[m] for m in metricas}} for l in candidatas]
    return sorted(ranking, key=lambda r: (r["soma_posicoes"], r["soma_razoes"]))


def _vencedor(ranking: list, criterio: dict, motivos: list) -> dict | None:
    """O líder do ranking, ou, havendo empate (< `empate`), o de menos dependências."""
    if not ranking:
        motivos.append("nenhum formato cumpre os critérios 1 e 2")
        return None
    lider = ranking[0]
    finalistas = [r for r in ranking if r["soma_razoes"] <= lider["soma_razoes"] * (1 + criterio["empate"])]
    escolhido = min(finalistas, key=lambda r: (criterio["dependencias"].get(r["formato"], 99), r["soma_posicoes"]))
    if escolhido is not lider:
        motivos.append(f"desempate (< {criterio['empate']:.0%}): {escolhido['formato']} tem menos dependências "
                       f"que {lider['formato']}")
    motivos.append(f"vencedor: {escolhido['formato']} ({escolhido['ordem']})")
    return {"formato": escolhido["formato"], "ordem": escolhido["ordem"]}


def quadro(linhas: list[dict]) -> str:
    """Tabela Markdown: uma linha por (km, formato, ordem), consultas em 'p50/p95 ms' por motor e nativo."""
    consultas = CRITERIO["consultas"]
    cab = ["km", "formato", "ordem", "bytes", "gravar_s", "ler_s", "ida e volta", "ram_mb"]
    cab += [f"{c} {m}" for c in consultas for m in MOTORES]
    saida = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for l in linhas:
        cel = [str(l["km"]), l["formato"], l["ordem"], str(l["bytes"]), str(l["gravar_s"]), str(l["ler_s"]),
               "sim" if l["ida_e_volta"] else "NÃO", str(l["ram_mb"])]
        for c in consultas:
            for m in MOTORES:
                q = (l["consultas"].get(m) or {}).get(c)
                cel.append(f"{q['p50_ms']}/{q['p95_ms']}" if q else "-")
        saida.append("| " + " | ".join(cel) + " |")
    return "\n".join(saida)


def principal(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--km", type=float, nargs="+", default=[5])
    p.add_argument("--repeticoes", type=int, default=5)
    p.add_argument("--formatos", nargs="+", default=gavetas.REGRAS["formato"]["implementados"])
    p.add_argument("--saida", default=str(RAIZ / "pdca" / "bancada_gavetas.jsonl"))
    p.add_argument("--quadro", default=None)
    p.add_argument("--semente", type=int, default=0)
    a = p.parse_args(argv)
    linhas = rodar(a.km, a.formatos, a.repeticoes, a.semente)
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    with open(a.saida, "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas)
    texto = quadro(linhas)
    if a.quadro:
        Path(a.quadro).write_text(texto + "\n", encoding="utf-8")
    print(texto)
    print(json.dumps(decidir(linhas), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    principal()
