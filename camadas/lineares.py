"""Eixo e estaqueamento da obra linear: a estaca é a coordenada; E/N servem só para desenhar.

    eixo                 = polilinha E/N (m) com a progressiva acumulada em cada vértice
    estaca <-> progressiva = "12+10,00" <-> 250,00 m (passo de 20 m, `conceitos/lineares.json`)
    ponto_em             = E/N numa progressiva (interpolação linear)
    progressiva_de       = projeção ortogonal de pontos no eixo: progressiva, afastamento e lado
    segmento             = a polilinha entre duas progressivas (o trecho)

Premissas em `conceitos/lineares.json`. O eixo é uma polilinha: curvas entram como vértices próximos.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

REGRAS = json.loads(
    (Path(__file__).resolve().parent.parent / "conceitos" / "lineares.json").read_text(
        encoding="utf-8"
    )
)
PASSO_M = float(REGRAS["passo_estaca_m"])
TOLERANCIA_M = float(REGRAS["tolerancia_m"])

_PADRAO_ESTACA = re.compile(
    r"(?:EST|E)?\.?\s*(\d+)\s*(?:\+\s*(\d+(?:[.,]\d+)?))?", re.IGNORECASE
)


def eixo(pontos_m) -> dict:
    """Eixo a partir da polilinha E/N (m), em ordem: vértices repetidos saem e a progressiva acumula do zero."""
    pontos = np.asarray(pontos_m, dtype=np.float64)
    if pontos.ndim != 2 or pontos.shape[1] != 2:
        raise ValueError(
            "os pontos do eixo devem ser uma matriz (n, 2) de E/N em metros"
        )
    if len(pontos):
        passos_m = np.linalg.norm(np.diff(pontos, axis=0), axis=1)
        manter = np.concatenate([[True], passos_m > TOLERANCIA_M])
        pontos = pontos[manter]
    if len(pontos) < 2:
        raise ValueError("o eixo precisa de ao menos 2 pontos distintos")
    comprimentos_m = np.linalg.norm(np.diff(pontos, axis=0), axis=1)
    progressiva_m = np.concatenate([[0.0], np.cumsum(comprimentos_m)])
    return {
        "pontos_m": pontos,
        "progressiva_m": progressiva_m,
        "comprimento_m": float(progressiva_m[-1]),
    }


def estaca_para_progressiva(texto: str, passo_m: float = PASSO_M) -> float:
    """Progressiva (m) de uma estaca escrita: '12+10,00', '12+10.00', '12+10', '12', 'E12+10,00', 'EST. 12 + 10,00'."""
    achado = _PADRAO_ESTACA.fullmatch(str(texto).strip())
    if achado is None:
        raise ValueError(
            f"estaca não reconhecida: {texto!r} (formato esperado: 'N+DD,DD', por exemplo '12+10,00')"
        )
    inteiras = int(achado.group(1))
    resto_m = float(achado.group(2).replace(",", ".")) if achado.group(2) else 0.0
    return inteiras * float(passo_m) + resto_m


def progressiva_para_estaca(progressiva_m: float, passo_m: float = PASSO_M) -> str:
    """Estaca escrita 'N+DD,DD' (vírgula decimal, 2 casas) de uma progressiva em metros."""
    if progressiva_m < 0:
        raise ValueError("a progressiva não pode ser negativa")
    centimetros = round(float(progressiva_m) * 100)
    passo_cm = round(float(passo_m) * 100)
    inteiras, resto_cm = divmod(centimetros, passo_cm)
    return f"{inteiras}+{resto_cm / 100:05.2f}".replace(".", ",")


def _verificar_dentro(eixo_: dict, progressiva_m: np.ndarray) -> None:
    """Erro em português se alguma progressiva cai fora de [0, comprimento] (com a tolerância)."""
    comprimento_m = eixo_["comprimento_m"]
    if np.any(progressiva_m < -TOLERANCIA_M) or np.any(
        progressiva_m > comprimento_m + TOLERANCIA_M
    ):
        raise ValueError(
            f"progressiva fora do eixo: deve estar entre 0 e {comprimento_m:.3f} m"
        )


def ponto_em(eixo_: dict, progressiva_m) -> np.ndarray:
    """E/N (m) na(s) progressiva(s): escalar dá (2,), vetor dá (n, 2); interpolação linear ao longo do eixo."""
    alvo_m = np.asarray(progressiva_m, dtype=np.float64)
    _verificar_dentro(eixo_, alvo_m)
    alvo_m = np.clip(alvo_m, 0.0, eixo_["comprimento_m"])
    base_m = eixo_["progressiva_m"]
    pontos = eixo_["pontos_m"]
    este_m = np.interp(alvo_m, base_m, pontos[:, 0])
    norte_m = np.interp(alvo_m, base_m, pontos[:, 1])
    return np.stack([este_m, norte_m], axis=-1)


def progressiva_de(eixo_: dict, e_m, n_m) -> dict:
    """Projeção ortogonal no segmento mais próximo: progressiva, afastamento ao eixo e lado ('esquerdo'/'direito').

    O lado é visto no sentido do estaqueamento; ponto sobre o eixo conta como 'direito'. Vetorizado: escalares dão
    escalares, vetores dão vetores."""
    escalar = np.ndim(e_m) == 0 and np.ndim(n_m) == 0
    consulta = np.stack(
        [
            np.atleast_1d(np.asarray(e_m, dtype=np.float64)),
            np.atleast_1d(np.asarray(n_m, dtype=np.float64)),
        ],
        axis=-1,
    )
    inicio = eixo_["pontos_m"][:-1]
    direcao = eixo_["pontos_m"][1:] - inicio
    comprimento2_m2 = np.sum(direcao**2, axis=1)
    relativo = consulta[:, None, :] - inicio[None, :, :]
    fracao = np.clip(
        np.sum(relativo * direcao[None], axis=2) / comprimento2_m2[None], 0.0, 1.0
    )
    pe = inicio[None] + fracao[..., None] * direcao[None]
    distancia_m = np.linalg.norm(consulta[:, None, :] - pe, axis=2)
    melhor = np.argmin(distancia_m, axis=1)
    linhas = np.arange(len(consulta))
    comprimento_seg_m = np.sqrt(comprimento2_m2[melhor])
    progressiva_m = (
        eixo_["progressiva_m"][melhor] + fracao[linhas, melhor] * comprimento_seg_m
    )
    produto = (
        direcao[melhor, 0] * relativo[linhas, melhor, 1]
        - direcao[melhor, 1] * relativo[linhas, melhor, 0]
    )
    lado = np.where(produto > TOLERANCIA_M * comprimento_seg_m, "esquerdo", "direito")
    afastamento_m = distancia_m[linhas, melhor]
    if escalar:
        return {
            "progressiva_m": float(progressiva_m[0]),
            "afastamento_m": float(afastamento_m[0]),
            "lado": str(lado[0]),
        }
    return {
        "progressiva_m": progressiva_m,
        "afastamento_m": afastamento_m,
        "lado": lado,
    }


def segmento(eixo_: dict, p0_m: float, p1_m: float) -> np.ndarray:
    """Polilinha E/N entre duas progressivas: as pontas interpoladas e os vértices do eixo no meio."""
    if p1_m <= p0_m:
        raise ValueError("a progressiva final deve ser maior que a inicial")
    base_m = eixo_["progressiva_m"]
    dentro_m = base_m[(base_m > p0_m + TOLERANCIA_M) & (base_m < p1_m - TOLERANCIA_M)]
    return ponto_em(eixo_, np.concatenate([[p0_m], dentro_m, [p1_m]]))


def metadados() -> dict:
    """Rastreabilidade do método e das premissas declaradas (regra 9 do estilo)."""
    meta = REGRAS["metadata"]
    return {
        "modulo": "lineares",
        "descricao": "eixo e estaqueamento da obra linear: estaca <-> progressiva <-> E/N",
        "funcoes": [
            "eixo",
            "estaca_para_progressiva",
            "progressiva_para_estaca",
            "ponto_em",
            "progressiva_de",
            "segmento",
            "metadados",
        ],
        "bibliografia": [],
        "premissas": [
            {
                "aplicacao": {
                    "estaca_para_progressiva": ["passo_estaca_m"],
                    "progressiva_para_estaca": ["passo_estaca_m"],
                },
                "fonte": meta["fonte"],
                "estado": meta["estado"],
            },
            {
                "aplicacao": {"eixo": ["tolerancia_m"]},
                "fonte": meta["fonte"],
                "estado": meta["estado"],
            },
        ],
        "ultima_revisao": meta["data_referencia"],
    }
