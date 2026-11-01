"""Conjunto de referência do projeto: cálculos de engenharia vigiados a cada iteração.

A última linha impressa é um JSON com o hash dos resultados (reprodutibilidade: mesma entrada,
mesmos bytes), o tempo de execução e o pico de memória. O `vcm balanco` compara esses valores
antes × depois de cada iteração.

Aqui entram só cálculos puros, com entradas fixas ou geradas com semente, que não dependem das
dependências opcionais (pymupdf, rasterio, pycolmap):

- obras lineares: largura de vala pelo MOS Sanepar e quantificação de um trecho;
- valas das redes: seção e quantitativos por classe de superfície;
- escavação: superfície da cava com talude e filtro de chão (PMF) sobre um MDS sintético.

Se um destes resultados mudar sem querer, o hash muda e o balanço acusa.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time

import numpy as np

from camadas import escavacao, obras_lineares, valas

SEMENTE = 42


def caso_largura_de_vala() -> np.ndarray:
    """Largura de vala (m) para DN × profundidade × material, pela regra L = D + SL + X + Y."""
    larguras_m = []
    for dn_mm in (100, 200, 300, 400, 600, 800, 1000):
        for prof_m in np.round(np.arange(0.8, 4.01, 0.1), 2):
            escorado = obras_lineares.escorar(float(prof_m))
            for material in ("FD", "PVC", "PEAD", "CONCRETO"):
                largura_m = obras_lineares.largura(dn_mm, material, float(prof_m), escorado)
                larguras_m.append(-1.0 if largura_m is None else largura_m)
    return np.asarray(larguras_m, dtype=np.float64)


def caso_trecho_de_adutora() -> bytes:
    """Quantificação completa de um trecho (escavação, reaterro, pavimento, esgotamento)."""
    trecho = {"local": "Entrada de água bruta", "dn_mm": 1000, "material": "FD", "prof_m": 2.4,
              "comp_m": 57.3, "metodo": "VCA", "sond_ini": "SP-02", "sond_fim": "SP-02",
              "na_m": 9.0, "solo": "argila", "pavimentos": {"grama": 57.3}, "supressao_frac": 1.0}
    return json.dumps(obras_lineares.quantificar(trecho), sort_keys=True, default=str).encode()


def caso_valas_por_classe() -> bytes:
    """Extensão, demolição, recomposição e volume de vala por classe de superfície."""
    gerador = np.random.default_rng(SEMENTE)
    classes = sorted(valas.REGRAS["classes"])
    sorteio = gerador.integers(0, len(classes), 2_000)
    pesos_m = gerador.uniform(0.5, 2.0, 2_000)
    linhas = valas.quantificar([classes[i] for i in sorteio], pesos_m, de_m=0.168)
    return json.dumps(linhas, sort_keys=True).encode()


def caso_superficie_da_cava() -> np.ndarray:
    """Superfície da cava (m) com talude 1:1 e folga de 0,5 m, numa grade de 0,25 m."""
    fundo_m = np.full((160, 160), np.nan)
    fundo_m[60:100, 60:100] = 742.35                     # base da estrutura, cota de fundo
    superficie_m, _ = escavacao.superficie_da_cava(fundo_m, res=0.25, talude=1.0, folga=0.5)
    return np.nan_to_num(superficie_m, nan=-9999.0)


def caso_chao_pmf() -> np.ndarray:
    """Células de chão pelo filtro morfológico progressivo num MDS sintético com edificações."""
    gerador = np.random.default_rng(SEMENTE)
    eixo_m = np.linspace(0.0, 100.0, 200)
    mds_m = (750.0 + 0.02 * eixo_m[None, :] + gerador.normal(0.0, 0.05, (200, 200))).astype(np.float32)
    mds_m[50:80, 50:90] += 6.0                           # edificação
    mds_m[120:140, 30:45] += 3.5                         # árvore / obstáculo
    return escavacao.chao_pmf(mds_m, res=0.5).astype(np.float64)


def calcular_resultados() -> list[bytes]:
    """Bytes canônicos de cada caso, em ordem fixa."""
    return [
        caso_largura_de_vala().tobytes(),
        caso_trecho_de_adutora(),
        caso_valas_por_classe(),
        caso_superficie_da_cava().tobytes(),
        caso_chao_pmf().tobytes(),
    ]


def hash_resultados(resultados: list[bytes]) -> str:
    """sha256 dos bytes canônicos, em ordem."""
    resumo = hashlib.sha256()
    for conteudo in resultados:
        resumo.update(conteudo)
    return resumo.hexdigest()


def pico_ram_mb() -> float | None:
    """Pico de memória do processo (MB). Linux: KiB; macOS: bytes; Windows: psutil, se houver."""
    try:
        import resource
    except ImportError:  # Windows
        try:
            import psutil
        except ImportError:
            return None
        return psutil.Process().memory_info().peak_wset / 2**20
    pico = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return pico / 2**20 if sys.platform == "darwin" else pico / 1024


def executar() -> dict:
    """Roda o conjunto de referência e devolve hash, tempo (ms) e pico de RAM (MB)."""
    inicio_s = time.perf_counter()
    resultados = calcular_resultados()
    tempo_ms = (time.perf_counter() - inicio_s) * 1000.0
    return {"hash": hash_resultados(resultados), "tempo_ms": tempo_ms, "pico_ram_mb": pico_ram_mb()}


if __name__ == "__main__":
    print(json.dumps(executar()))
