"""Bancada do cálculo incremental (rodada 24, E2, experimento G08): tempo, reaproveitamento e RAM por carga.

Cada carga (km de adutora sintética) roda num subprocesso próprio, para o pico de RSS ser o da carga e não o do pai
(VmHWM zerado depois dos imports). Mede: cálculo completo, 2º cálculo sem mudança, 3º cálculo com 1 fato mudado
(`prof_m` de um trecho no meio da adutora), `eap_html.montar`, gravação e leitura em parquet.

    python scripts/bancada_calculo.py --km 5 100 [--saida pdca/bancada_calculo.jsonl] [--quadro quadro.md] [--semente 0]
"""
import argparse
import importlib
import json
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))

from bancada_gavetas import _versao  # mesma leitura de versão da bancada anterior

# Critério fixado ANTES de medir (vale na maior carga; mudar aqui exige mudar o plano).
CRITERIO = {
    "fonte": "docs/plano/2026-11-01_rodada24.md §Critério 2",
    "calculo_1_max_s": 60.0,
    "calculo_2_max_fracao": 0.10,      # 2º cálculo ≤ 10 % do tempo do 1º
    "recalculados_2": 0,
    "recalculados_3": 1,
    "montar_max_s": 5.0,
    "pico_rss_max_mb": 1024.0,
}
CHAVES_MEDIDAS = ["n_objetos", "n_fatos", "n_servicos", "t_calculo_1_s", "t_calculo_2_s", "recalculados_2",
                  "t_calculo_3_s", "recalculados_3", "t_montar_s", "t_gravar_s", "t_ler_s", "bytes", "pico_rss_mb"]


def _kb(campo: str) -> int:
    """Valor em kB de um campo de /proc/self/status (VmRSS, VmHWM)."""
    for linha in Path("/proc/self/status").read_text().splitlines():
        if linha.startswith(campo + ":"):
            return int(linha.split()[1])
    return 0


def _cronometrar(funcao, *args):
    """(resultado, segundos) de uma chamada."""
    t = time.perf_counter()
    resultado = funcao(*args)
    return resultado, round(time.perf_counter() - t, 4)


def _mudar_prof(base: dict) -> tuple[dict, str]:
    """Cópia da base com o `prof_m` do trecho do meio da adutora alterado; devolve (base, objeto_id)."""
    trechos = [o["objeto_id"] for o in base["objetos"] if o["classe"] == "trecho_tubo"]
    alvo = trechos[len(trechos) // 2]
    fatos = []
    for f in base["fatos"]:
        if f["objeto_id"] == alvo and f["propriedade"] == "prof_m":
            f = {**f, "valor": round(float(f["valor"]) + 0.5, 2)}
        fatos.append(f)
    return {**base, "fatos": fatos}, alvo


def medir_carga(km: float, semente: int) -> dict:
    """Mede uma carga no processo atual (chamado dentro do subprocesso, depois de zerar o pico de RSS)."""
    from camadas import eap_html, gavetas, sintetico
    base = sintetico.base_linear(km, semente=semente)
    (servicos, pendencias, _), t1 = _cronometrar(gavetas.calcular_incremental, base)
    (_, _, est2), t2 = _cronometrar(lambda: gavetas.calcular_incremental(base, anterior=servicos))
    base_mudada, _ = _mudar_prof(base)
    (_, _, est3), t3 = _cronometrar(lambda: gavetas.calcular_incremental(base_mudada, anterior=servicos))
    _, t_montar = _cronometrar(eap_html.montar, base, servicos, pendencias)
    with tempfile.TemporaryDirectory() as pasta:
        arquivos, t_gravar = _cronometrar(gavetas.gravar, pasta, base, "parquet")
        _, t_ler = _cronometrar(gavetas.ler, pasta, "parquet")
        tamanho = sum(a.stat().st_size for a in arquivos)
    return {"n_objetos": len(base["objetos"]), "n_fatos": len(base["fatos"]), "n_servicos": len(servicos),
            "t_calculo_1_s": t1, "t_calculo_2_s": t2, "recalculados_2": est2["recalculados"],
            "t_calculo_3_s": t3, "recalculados_3": est3["recalculados"], "t_montar_s": t_montar,
            "t_gravar_s": t_gravar, "t_ler_s": t_ler, "bytes": tamanho,
            "pico_rss_mb": round(_kb("VmHWM") / 1024, 1)}


def _trabalhador(km: float, semente: int) -> None:
    """Corpo do subprocesso: importa tudo, zera o pico (VmHWM), mede e imprime o JSON."""
    from camadas import eap_html, gavetas, sintetico  # noqa: F401 — só para pagar os imports antes do zero
    importlib.import_module("pyarrow")
    Path("/proc/self/clear_refs").write_text("5")
    print(json.dumps(medir_carga(km, semente)))


def rodar_carga(km: float, semente: int) -> dict:
    """Uma linha da bancada: roda `--trabalhador` num subprocesso novo."""
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--trabalhador", str(km), str(semente)],
                       capture_output=True, text=True, cwd=RAIZ, check=True)
    medidas = json.loads(r.stdout.strip().splitlines()[-1])
    return {"rodada": "rodada 24", "data": str(date.today()), "km": km, "semente": semente,
            "python": sys.version.split()[0], "pyarrow": _versao("pyarrow"), "numpy": _versao("numpy"), **medidas}


def rodar(kms: list, semente: int, avisar=print) -> list[dict]:
    """Todas as linhas, uma por carga."""
    linhas = []
    for km in kms:
        linhas.append(rodar_carga(km, semente))
        avisar(f"{km} km: cálculo {linhas[-1]['t_calculo_1_s']} s, pico {linhas[-1]['pico_rss_mb']} MB")
    return linhas


def avaliar(linhas: list[dict], criterio: dict = CRITERIO) -> dict:
    """Aplica o critério na maior carga. Devolve {"passou", "motivos"}; cada motivo diz limite, medido e se passou."""
    l = max(linhas, key=lambda x: x["km"])
    limite_2 = criterio["calculo_2_max_fracao"] * l["t_calculo_1_s"]
    testes = [
        ("cálculo completo", f"≤ {criterio['calculo_1_max_s']} s", f"{l['t_calculo_1_s']} s",
         l["t_calculo_1_s"] <= criterio["calculo_1_max_s"]),
        ("2º cálculo sem mudança", f"≤ {criterio['calculo_2_max_fracao']:.0%} do 1º ({limite_2:.4g} s)",
         f"{l['t_calculo_2_s']} s", l["t_calculo_2_s"] <= limite_2),
        ("recalculados no 2º cálculo", f"= {criterio['recalculados_2']}", str(l["recalculados_2"]),
         l["recalculados_2"] == criterio["recalculados_2"]),
        ("recalculados após mudar 1 fato", f"= {criterio['recalculados_3']}", str(l["recalculados_3"]),
         l["recalculados_3"] == criterio["recalculados_3"]),
        ("eap_html.montar", f"≤ {criterio['montar_max_s']} s", f"{l['t_montar_s']} s",
         l["t_montar_s"] <= criterio["montar_max_s"]),
        ("pico de RSS", f"< {criterio['pico_rss_max_mb']} MB", f"{l['pico_rss_mb']} MB",
         l["pico_rss_mb"] < criterio["pico_rss_max_mb"]),
    ]
    motivos = [f"{nome}: limite {limite}, medido {medido} a {l['km']} km: {'passou' if ok else 'REPROVOU'}"
               for nome, limite, medido, ok in testes]
    return {"passou": all(t[3] for t in testes), "motivos": motivos}


def quadro(linhas: list[dict]) -> str:
    """Tabela Markdown: uma linha por carga."""
    cab = ["km", "objetos", "fatos", "serviços", "cálculo 1 (s)", "cálculo 2 (s)", "recalc. 2", "cálculo 3 (s)",
           "recalc. 3", "montar (s)", "gravar (s)", "ler (s)", "bytes", "pico RSS (MB)"]
    saida = ["| " + " | ".join(cab) + " |", "|" + "---|" * len(cab)]
    for l in linhas:
        cel = [l["km"], l["n_objetos"], l["n_fatos"], l["n_servicos"], l["t_calculo_1_s"], l["t_calculo_2_s"],
               l["recalculados_2"], l["t_calculo_3_s"], l["recalculados_3"], l["t_montar_s"], l["t_gravar_s"],
               l["t_ler_s"], l["bytes"], l["pico_rss_mb"]]
        saida.append("| " + " | ".join(str(c) for c in cel) + " |")
    return "\n".join(saida)


def principal(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--km", type=float, nargs="+", default=[5])
    p.add_argument("--saida", default=str(RAIZ / "pdca" / "bancada_calculo.jsonl"))
    p.add_argument("--quadro", default=None)
    p.add_argument("--semente", type=int, default=0)
    p.add_argument("--trabalhador", nargs=2, metavar=("KM", "SEMENTE"), help=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.trabalhador:
        _trabalhador(float(a.trabalhador[0]), int(a.trabalhador[1]))
        return
    linhas = rodar(a.km, a.semente)
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    with open(a.saida, "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(l, ensure_ascii=False) + "\n" for l in linhas)
    texto = quadro(linhas)
    if a.quadro:
        Path(a.quadro).write_text(texto + "\n", encoding="utf-8")
    print(texto)
    print(json.dumps(avaliar(linhas), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    principal()
