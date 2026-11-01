"""Geotecnia: schema do furo de sondagem, validação e leitor de laudo (PDF) pelo texto.

O furo canônico (dict puro, nomes já em uso no projeto) está em `conceitos/geotecnia.json`:

    id, E, N (m, SIRGAS 2000/UTM), epsg, cota_boca (m), na_m (m a partir da boca; None = não atingido),
    profundidade_m, impenetravel, camadas [{de, ate, descricao, classe}] (m), nspt [[profundidade_m, golpes]], fonte

Heurística do leitor de laudo (`ler_laudo`), só pelo texto do PDF (pymupdf), sem OCR e sem inventar:

    (a) tabela de coordenadas: id de furo (`SP-?\\d+`, `SPT-?\\d+`, `F-?\\d+`) seguido de dois números, o de 6 dígitos
        inteiros (E) e o de 7 (N), e, se houver, a cota da boca; aceita ponto de milhar e vírgula decimal;
    (b) perfil por furo: o trecho começa numa linha que cita o id (com FURO/SONDAGEM/PERFIL, ou só o id) e vai até o
        próximo furo citado. Nele: NA por "N.A." / "NÍVEL D'ÁGUA" + número em m, ou "NÃO ATINGIDO"/"SECO" (= None);
        impenetrável por "IMPENETRÁVEL"; camadas por "de X a Y m descrição" ou "X,XX – Y,YY descrição"; NSPT por
        linhas "profundidade golpes".

Furo sem coordenada ou sem camadas vai para `nao_lidos` com o motivo. Todo furo lido passa por `validar_furos`.

Modelo geotécnico único (premissas e regras em `conceitos/geotecnia.json`; obras lineares, estacas e cavas leem daqui):

    classe_solo, solo_na_faixa, categoria_escavacao    solo/rocha e categoria de escavação (1ª/2ª/3ª) por faixa
    na_m, topo_rocha_m, alerta_na                      nível d'água (com margem), topo da rocha/impenetrável, NA sazonal
    perfil_em, furo_mais_proximo                       furo mais próximo (vetorizado), com distância e raio de influência
    conferir                                           projeto × sondagem: estaca × impenetrável, cava × NA, trecho sem furo

    python -m camadas.geotecnia laudo.pdf [--saida sondagens.json]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import unicodedata
from pathlib import Path

import numpy as np

CONCEITOS = Path(__file__).resolve().parent.parent / "conceitos" / "geotecnia.json"
REGRAS = json.loads(CONCEITOS.read_text(encoding="utf-8"))
PREMISSAS = REGRAS["premissas"]
RAIO_INFLUENCIA_M = PREMISSAS["raio_influencia_m"]["valor"]
MARGEM_NA_M = PREMISSAS["margem_na_m"]["valor"]
EMPOLAMENTO_SOLO = PREMISSAS["empolamento"]["solo"]
EMPOLAMENTO_ROCHA = PREMISSAS["empolamento"]["rocha"]
FOLGA_NA_SAZONAL_M = PREMISSAS["folga_na_sazonal_m"]["valor"]
TOLERANCIA_CONFERENCIA_M = PREMISSAS["tolerancia_conferencia_m"]["valor"]
PASSO_AMOSTRAGEM_M = PREMISSAS["passo_amostragem_m"]["valor"]
CATEGORIA_POR_CLASSE = {c["classe"]: c["categoria"] for c in REGRAS["solos"]["classes"]}
CATEGORIA_INDEFINIDA = "a definir"
TOLERANCIA_PROFUNDIDADE_M = 0.01

_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
_ID = r"(?:SPT|SP|F)-?\s?\d+"
_RE_ID = re.compile(rf"\b({_ID})\b", re.IGNORECASE)
_RE_NUM = re.compile(_NUM)
_RE_COORD = re.compile(
    rf"\b(?P<id>{_ID})\b(?P<resto>(?:\s+(?:{_NUM}))+)", re.IGNORECASE
)
# "N.A." com ponto, "NA" seguido de ':', '=' ou '(', ou a expressão por extenso; "NA" solto é a preposição "na" em
# maiúsculas ("ARGILA MOLE NA COTA 3,00") e não pode virar nível d'água (revisão do Fable, rodada 25)
_RE_NA = re.compile(
    r"\bN\.\s?A\.?|\bNA\b(?=\s*[:=(])|NIVEL\s+D['’`]?\s?AGUA|LENCOL\s+FREATICO"
)
_RE_SEM_NA = re.compile(r"NAO\s+ATINGID|\bSECO\b|NAO\s+ENCONTRAD|AUSENTE")
_RE_NUM_M = re.compile(rf"(?<![\d.,])({_NUM})(?:\s*m\b)?", re.IGNORECASE)
_RE_CAMADA = re.compile(
    rf"^\s*(?:de\s+)?({_NUM})\s*(?:m\s*)?(?:a|at[ée]|[–—-])\s*({_NUM})\s*m?\b\s*[:\-–—]?\s*(.*\S)\s*$",
    re.IGNORECASE,
)
_RE_NSPT = re.compile(
    rf"^\s*({_NUM})\s*(?:m\s+)?(\d{{1,3}})\s*(?:golpes)?\s*$", re.IGNORECASE
)
_RE_PROF = re.compile(
    rf"PROFUNDIDADE\s+(?:FINAL|TOTAL|ATINGIDA)[^\d\n]{{0,20}}({_NUM})"
)
_RE_COTA = re.compile(
    rf"COTA(?:\s+DA\s+BOCA|\s+DO\s+TERRENO|\s+DE\s+BOCA)?[^\d\n]{{0,20}}({_NUM})"
)


def metadados() -> dict:
    """Rastreabilidade (regra 9 do estilo)."""
    premissas = json.loads(CONCEITOS.read_text(encoding="utf-8"))["premissas"]
    return {
        "modulo": "geotecnia",
        "descricao": "schema do furo de sondagem, validação, leitor de laudo em PDF pelo texto, modelo geotécnico "
        "único (solo, NA, rocha, furo mais próximo) e conferências projeto × sondagem",
        "funcoes": [
            "validar_furos",
            "ler_laudo",
            "classe_solo",
            "solo_na_faixa",
            "categoria_escavacao",
            "na_m",
            "topo_rocha_m",
            "furo_mais_proximo",
            "perfil_em",
            "alerta_na",
            "conferir",
            "metadados",
            "main",
        ],
        "bibliografia": [],
        "premissas": [
            {
                "aplicacao": {nome: [str(p.get("valor", p))]},
                "estado": p["estado"],
                "fonte": p["fonte"],
            }
            for nome, p in premissas.items()
        ],
    }


# --------------------------------------------------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------------------------------------------------


def _numero(valor) -> bool:
    """Verdadeiro para número real finito (bool não conta)."""
    return (
        isinstance(valor, (int, float))
        and not isinstance(valor, bool)
        and math.isfinite(valor)
    )


def _motivos_camadas(furo: dict) -> list[str]:
    """Motivos de erro nas camadas: ordem e limites. Camada sem `de`/`ate` (None) é não confirmada e fica fora."""
    motivos, anterior_ate = [], None
    for i, c in enumerate(furo.get("camadas") or []):
        de, ate = c.get("de"), c.get("ate")
        if de is None or ate is None:
            continue
        if not (_numero(de) and _numero(ate)):
            motivos.append(f"camada {i + 1} com limite não numérico")
        elif ate <= de:
            motivos.append(f"camada {i + 1} com ate <= de ({de} a {ate})")
        elif anterior_ate is not None and de < anterior_ate - TOLERANCIA_PROFUNDIDADE_M:
            motivos.append(
                f"camada {i + 1} fora de ordem (de {de} antes do fim da anterior, {anterior_ate})"
            )
        if _numero(de) and _numero(ate) and ate > de:
            anterior_ate = ate
    return motivos


def _motivos_furo(furo) -> list[str]:
    """Todos os motivos pelos quais o furo não é válido (lista vazia = válido)."""
    if not isinstance(furo, dict):
        return ["furo não é um objeto"]
    motivos = []
    if not str(furo.get("id") or "").strip():
        motivos.append("sem id")
    for eixo in ("E", "N"):
        if not _numero(furo.get(eixo)):
            motivos.append(f"{eixo} ausente ou não numérico")
    na = furo.get("na_m")
    if na is not None and (not _numero(na) or na < 0):
        motivos.append(f"na_m inválido ({na})")
    camadas = furo.get("camadas")
    if camadas is not None and not isinstance(camadas, list):
        motivos.append("camadas não é uma lista")
        camadas = []
    elif any(not isinstance(c, dict) for c in camadas or []):
        motivos.append("camadas com item que não é um objeto")
        camadas = []
    motivos += _motivos_camadas({"camadas": camadas})
    ates = [c["ate"] for c in (camadas or []) if _numero(c.get("ate"))]
    prof = furo.get("profundidade_m")
    if ates and _numero(prof) and prof < max(ates) - TOLERANCIA_PROFUNDIDADE_M:
        motivos.append(
            f"profundidade_m ({prof}) menor que a última camada ({max(ates)})"
        )
    return motivos


def validar_furos(furos) -> tuple[list, list]:
    """Separa os furos válidos dos inválidos, sem alterar nomes nem valores.

    Aceita a lista de furos ou `{"meta": ..., "furos": [...]}`. Devolve (válidos, erros), com
    erros = [{"id", "motivo"}], um por motivo. Profundidade com tolerância absoluta de 0,01 m.
    """
    if isinstance(furos, dict):
        furos = furos.get("furos", [])
    validos, erros = [], []
    for furo in furos or []:
        motivos = _motivos_furo(furo)
        if not motivos:
            validos.append(furo)
            continue
        fid = furo.get("id") if isinstance(furo, dict) else None
        erros += [{"id": fid, "motivo": m} for m in motivos]
    return validos, erros


# --------------------------------------------------------------------------------------------------------------------
# Modelo geotécnico único: solo, categoria, NA, rocha e furo mais próximo
# --------------------------------------------------------------------------------------------------------------------


def _norm(texto) -> str:
    """Maiúsculas sem acento e com espaços simples (para casar as regex de `conceitos/geotecnia.json`)."""
    t = (
        unicodedata.normalize("NFKD", str(texto or ""))
        .encode("ascii", "ignore")
        .decode()
    )
    return re.sub(r"\s+", " ", t).strip().upper()


def _br(valor: float, casas: int = 2) -> str:
    """Número com vírgula decimal para as mensagens."""
    return f"{valor:.{casas}f}".replace(".", ",")


def classe_solo(descricao: str, classe: str | None = None) -> dict:
    """Classe e categoria de escavação de uma camada pela descrição (ou pela classe já dada): a 1ª regex que casa."""
    texto = _norm(f"{classe or ''} {descricao or ''}")
    for c in REGRAS["solos"]["classes"]:
        if re.search(c["regex"], texto):
            return c
    return {"classe": "indefinido", "categoria": CATEGORIA_INDEFINIDA}


def solo_na_faixa(furo: dict, de_m: float, ate_m: float) -> dict[str, float]:
    """Fração da faixa [de_m, ate_m] (profundidades a partir da boca) em cada classe de solo do furo.

    O que a sondagem não cobre entra como `indefinido`, de modo que as frações somam 1.
    """
    espessura_m = ate_m - de_m
    if espessura_m <= 0:
        return {}
    fatias: dict[str, float] = {}
    for c in furo.get("camadas") or []:
        topo_m, base_m = c.get("de"), c.get("ate")
        if topo_m is None or base_m is None or topo_m >= ate_m or base_m <= de_m:
            continue
        classe = classe_solo(c.get("descricao"), c.get("classe"))["classe"]
        fatias[classe] = (
            fatias.get(classe, 0.0)
            + (min(base_m, ate_m) - max(topo_m, de_m)) / espessura_m
        )
    resto = 1.0 - sum(fatias.values())
    if resto > 1e-6:
        fatias["indefinido"] = fatias.get("indefinido", 0.0) + resto
    return fatias


def categoria_escavacao(furo: dict, de_m: float, ate_m: float) -> dict[str, float]:
    """Fração da faixa [de_m, ate_m] em cada categoria de escavação (1ª, 2ª, 3ª categoria ou `a definir`)."""
    categorias: dict[str, float] = {}
    for classe, fracao in solo_na_faixa(furo, de_m, ate_m).items():
        categoria = CATEGORIA_POR_CLASSE.get(classe, CATEGORIA_INDEFINIDA)
        categorias[categoria] = categorias.get(categoria, 0.0) + fracao
    return categorias


def na_m(furo: dict, margem_m: float | None = None) -> float | None:
    """Profundidade do NA de projeto (m a partir da boca): o NA do furo menos a margem (que sobe o NA, a favor da
    segurança), nunca negativa. None = NA não atingido. Margem padrão (planilha): 0 m."""
    nivel_m = furo.get("na_m")
    if nivel_m is None:
        return None
    margem_m = MARGEM_NA_M if margem_m is None else margem_m
    return max(0.0, float(nivel_m) - margem_m)


def topo_rocha_m(furo: dict) -> float | None:
    """Profundidade (m) do topo da rocha: o `de` da primeira camada de classe rocha; se não houver e o furo for
    `impenetravel`, a profundidade final; senão None."""
    for c in furo.get("camadas") or []:
        if c.get("de") is None:
            continue
        if classe_solo(c.get("descricao"), c.get("classe"))["classe"] == "rocha":
            return float(c["de"])
    if furo.get("impenetravel"):
        if _numero(furo.get("profundidade_m")):
            return float(furo["profundidade_m"])
        ates = [c["ate"] for c in furo.get("camadas") or [] if _numero(c.get("ate"))]
        return float(max(ates)) if ates else None
    return None


def furo_mais_proximo(
    pontos_m: np.ndarray, furos: list[dict]
) -> tuple[np.ndarray, np.ndarray]:
    """Para cada ponto (n, 2) em E/N (m), o índice, em `furos`, do furo mais próximo e a distância (m).

    Só entram furos com E e N. Sem furos: índices -1 e distâncias infinitas. Vetorizado.
    """
    pontos_m = np.asarray(pontos_m, dtype="float64").reshape(-1, 2)
    indices = [
        i for i, f in enumerate(furos) if _numero(f.get("E")) and _numero(f.get("N"))
    ]
    if not indices:
        return np.full(len(pontos_m), -1, dtype=int), np.full(len(pontos_m), np.inf)
    xy_m = np.array([[furos[i]["E"], furos[i]["N"]] for i in indices], dtype="float64")
    distancias_m = np.linalg.norm(pontos_m[:, None, :] - xy_m[None, :, :], axis=2)
    perto = distancias_m.argmin(axis=1)
    return np.array(indices)[perto], distancias_m[np.arange(len(pontos_m)), perto]


def perfil_em(
    e_m: float, n_m: float, furos: list[dict], raio_m: float | None = None
) -> dict | None:
    """Furo mais próximo do ponto (E, N em m): {furo, distancia_m, dentro_do_raio, alerta}.

    O furo além do raio de influência (padrão 60 m) entra com a distância e um alerta. None se não há furo com E/N.
    """
    raio_m = RAIO_INFLUENCIA_M if raio_m is None else raio_m
    indices, distancias_m = furo_mais_proximo(np.array([[e_m, n_m]]), furos)
    if indices[0] < 0:
        return None
    furo, distancia_m = furos[indices[0]], float(distancias_m[0])
    dentro = distancia_m <= raio_m
    alerta = None
    if not dentro:
        alerta = f"furo {furo.get('id')} a {_br(distancia_m)} m, além do raio de influência de {_br(raio_m, 0)} m"
    return {
        "furo": furo,
        "distancia_m": distancia_m,
        "dentro_do_raio": dentro,
        "alerta": alerta,
    }


def alerta_na(furo: dict, fundo_m: float, folga_m: float | None = None) -> str | None:
    """Alerta quando o fundo da escavação (m a partir da boca) fica a menos de `folga_m` (0,5 m) do NA, ou abaixo
    dele: o NA é sazonal. Só avisa; o cálculo segue com a margem de 0 m. None se não há alerta."""
    nivel_m = na_m(furo)
    folga_m = FOLGA_NA_SAZONAL_M if folga_m is None else folga_m
    if nivel_m is None or fundo_m <= nivel_m - folga_m:
        return None
    situacao = (
        "abaixo do NA" if fundo_m > nivel_m else f"a menos de {_br(folga_m, 1)} m do NA"
    )
    return (
        f"furo {furo.get('id')}: fundo a {_br(fundo_m)} m, {situacao} ({_br(nivel_m)} m); "
        "o NA é sazonal, conferir o esgotamento"
    )


# --------------------------------------------------------------------------------------------------------------------
# Conferências projeto × sondagem
# --------------------------------------------------------------------------------------------------------------------


def _cota_boca_m(furo: dict) -> float | None:
    return float(furo["cota_boca"]) if _numero(furo.get("cota_boca")) else None


def _ocorrencia(tipo, objeto_id, furo, distancia_m, mensagem, **valores) -> dict:
    return {
        "tipo": tipo,
        "objeto_id": objeto_id,
        "furo": None if furo is None else furo.get("id"),
        "distancia_m": None if distancia_m is None else round(float(distancia_m), 3),
        "mensagem": mensagem,
        "valores": valores,
    }


def _sem_furo(rotulo, objeto_id, furos, i, distancia_m, raio_m, o_que) -> dict:
    furo = furos[i] if i >= 0 else None
    return _ocorrencia(
        "sem_furo_no_raio",
        objeto_id,
        furo,
        distancia_m if i >= 0 else None,
        f"{rotulo} {objeto_id}: nenhum furo dentro de {_br(raio_m, 0)} m, não dá para conferir {o_que}",
        raio_m=raio_m,
    )


def _estaca_x_topo(
    estaca: dict, furo: dict, distancia_m: float, tolerancia_m: float
) -> dict | None:
    """Ocorrência da estaca contra o topo do impenetrável/rocha do furo; None se confere ou não há dados."""
    topo_m, boca_m = topo_rocha_m(furo), _cota_boca_m(furo)
    arrasamento_m, comprimento_m = (
        estaca.get("cota_arrasamento"),
        estaca.get("comprimento_m"),
    )
    if (
        topo_m is None
        or boca_m is None
        or not (_numero(arrasamento_m) and _numero(comprimento_m))
    ):
        return None
    eid, cota_topo_m = str(estaca.get("id")), boca_m - topo_m
    ponta_m = float(arrasamento_m) - float(comprimento_m)
    diferenca_m = ponta_m - cota_topo_m  # > 0: a ponta fica acima do topo (não chega)
    if abs(diferenca_m) <= tolerancia_m:
        return None
    situacao, verbo, lado = (
        ("nao_chega", "não chega ao", "acima")
        if diferenca_m > 0
        else ("passa", "passa do", "abaixo")
    )
    msg = (
        f"estaca {eid} {verbo} impenetrável do furo {furo.get('id')}: "
        f"ponta {_br(abs(diferenca_m))} m {lado} do topo"
    )
    return _ocorrencia(
        "estaca_x_impenetravel",
        eid,
        furo,
        distancia_m,
        msg,
        situacao=situacao,
        cota_ponta_m=ponta_m,
        cota_topo_impenetravel_m=cota_topo_m,
        diferenca_m=diferenca_m,
    )


def _conferir_estacas(furos, estacas, tolerancia_m, raio_m) -> list[dict]:
    """Ponta da estaca (cota_arrasamento − comprimento_m) × topo do impenetrável/rocha do furo mais próximo."""
    estacas = [e for e in estacas if _numero(e.get("E")) and _numero(e.get("N"))]
    if not estacas:
        return []
    indices, distancias_m = furo_mais_proximo(
        np.array([[e["E"], e["N"]] for e in estacas]), furos
    )
    saidas = []
    for estaca, i, distancia_m in zip(estacas, indices, distancias_m, strict=True):
        if i < 0 or distancia_m > raio_m:
            saidas.append(
                _sem_furo(
                    "estaca",
                    str(estaca.get("id")),
                    furos,
                    i,
                    distancia_m,
                    raio_m,
                    "o impenetrável",
                )
            )
        elif (
            o := _estaca_x_topo(estaca, furos[i], float(distancia_m), tolerancia_m)
        ) is not None:
            saidas.append(o)
    return saidas


def _conferir_cavas(furos, cavas, tolerancia_m, raio_m) -> list[dict]:
    """Fundo da cava × cota do NA (cota da boca − NA) do furo mais próximo: abaixo do NA pede esgotamento."""
    cavas = [c for c in cavas if _numero(c.get("E_m")) and _numero(c.get("N_m"))]
    if not cavas:
        return []
    indices, distancias_m = furo_mais_proximo(
        np.array([[c["E_m"], c["N_m"]] for c in cavas]), furos
    )
    saidas = []
    for cava, i, distancia_m in zip(cavas, indices, distancias_m, strict=True):
        cid = str(cava.get("id"))
        if i < 0 or distancia_m > raio_m:
            saidas.append(_sem_furo("cava", cid, furos, i, distancia_m, raio_m, "o NA"))
            continue
        furo = furos[i]
        nivel_m, boca_m = na_m(furo), _cota_boca_m(furo)
        if nivel_m is None or boca_m is None or not _numero(cava.get("cota_fundo_m")):
            continue
        cota_na_m = boca_m - nivel_m
        diferenca_m = cota_na_m - float(cava["cota_fundo_m"])  # > 0: fundo abaixo do NA
        if diferenca_m > tolerancia_m:
            msg = f"cava {cid}: fundo {_br(diferenca_m)} m abaixo do NA do furo {furo.get('id')}, esgotamento necessário"
            saidas.append(
                _ocorrencia(
                    "cava_x_na",
                    cid,
                    furo,
                    distancia_m,
                    msg,
                    cota_fundo_m=float(cava["cota_fundo_m"]),
                    cota_na_m=cota_na_m,
                    diferenca_m=diferenca_m,
                )
            )
    return saidas


def _amostrar_trecho(pontos_m: np.ndarray) -> np.ndarray:
    """Pontos a cada `passo_amostragem_m` ao longo da polilinha (inclui as pontas)."""
    if len(pontos_m) < 2:
        return pontos_m
    acumulado_m = np.concatenate(
        [[0.0], np.cumsum(np.linalg.norm(np.diff(pontos_m, axis=0), axis=1))]
    )
    n = max(2, int(np.ceil(acumulado_m[-1] / PASSO_AMOSTRAGEM_M)) + 1)
    alvo_m = np.linspace(0.0, acumulado_m[-1], n)
    return np.column_stack(
        [np.interp(alvo_m, acumulado_m, pontos_m[:, k]) for k in (0, 1)]
    )


def _conferir_trechos(furos, trechos, raio_m) -> list[dict]:
    """Fração de cada trecho (polilinha em E/N) sem furo dentro do raio de influência."""
    saidas = []
    for trecho in trechos:
        tid = str(trecho.get("id"))
        amostras_m = _amostrar_trecho(
            np.asarray(trecho["pontos_m"], dtype="float64").reshape(-1, 2)
        )
        indices, distancias_m = furo_mais_proximo(amostras_m, furos)
        fora = distancias_m > raio_m
        if not fora.any():
            continue
        fracao = float(fora.mean())
        pior = int(np.argmax(distancias_m))
        furo = furos[indices[pior]] if indices[pior] >= 0 else None
        distancia_m = float(distancias_m[pior]) if furo is not None else None
        if furo is None:
            msg = f"trecho {tid}: sem nenhum furo de sondagem"
        else:
            msg = f"trecho {tid}: {_br(fracao * 100, 0)}% do comprimento sem furo dentro de {_br(raio_m, 0)} m"
        saidas.append(
            _ocorrencia(
                "trecho_sem_furo",
                tid,
                furo,
                distancia_m,
                msg,
                fracao_sem_furo=fracao,
                raio_m=raio_m,
            )
        )
    return saidas


def conferir(
    furos: list[dict],
    estacas: list[dict] | None = None,
    cavas: list[dict] | None = None,
    trechos: list[dict] | None = None,
    tolerancia_m: float | None = None,
) -> list[dict]:
    """Conferências projeto × sondagem. Devolve ocorrências {tipo, objeto_id, furo, distancia_m, mensagem, valores}.

    - `estacas` (linhas do CSV: id, E, N, cota_arrasamento, comprimento_m): ponta = cota_arrasamento − comprimento_m
      contra o topo do impenetrável/rocha (cota_boca − topo_rocha_m) do furo mais próximo; acusa "não chega" e
      "passa" além de `tolerancia_m` (padrão 0,10 m, tolerância absoluta);
    - `cavas` ([{id, E_m, N_m, cota_fundo_m}]): fundo abaixo da cota do NA = esgotamento necessário, com a diferença;
    - `trechos` ([{id, pontos_m (n, 2)}]): fração do trecho sem furo dentro do raio de influência.

    Estaca ou cava sem furo dentro do raio vira `sem_furo_no_raio` (não há como conferir). Furo sem cota_boca, sem NA
    ou sem rocha/impenetrável não gera ocorrência. Tipos: estaca_x_impenetravel, cava_x_na, trecho_sem_furo.
    """
    tolerancia_m = TOLERANCIA_CONFERENCIA_M if tolerancia_m is None else tolerancia_m
    furos = [f for f in furos or [] if isinstance(f, dict)]
    return (
        _conferir_estacas(furos, estacas or [], tolerancia_m, RAIO_INFLUENCIA_M)
        + _conferir_cavas(furos, cavas or [], tolerancia_m, RAIO_INFLUENCIA_M)
        + _conferir_trechos(furos, trechos or [], RAIO_INFLUENCIA_M)
    )


# --------------------------------------------------------------------------------------------------------------------
# Leitor de laudo
# --------------------------------------------------------------------------------------------------------------------


def _sem_acento(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )


def _para_float(token: str) -> float:
    """'654.321,50' -> 654321.5; '12,30' -> 12.3; '654321.50' -> 654321.5."""
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token):
        token = token.replace(".", "")
    return float(token.replace(",", "."))


def _chave(identificador: str) -> str:
    """Chave comparável do id: 'SP-01', 'SP01' e 'SPT-1' são o mesmo furo."""
    t = re.sub(r"[^A-Z0-9]", "", identificador.upper()).replace("SPT", "SP")
    return re.sub(r"(?<=[A-Z])0+(?=\d)", "", t)


def _id_limpo(identificador: str) -> str:
    return re.sub(r"\s+", "", identificador.upper())


def _coordenadas(texto: str) -> dict[str, dict]:
    """Tabela de coordenadas: {chave: {id, E, N, cota_boca?}}; vale a primeira ocorrência de cada furo."""
    achados = {}
    plano = re.sub(r"\s+", " ", texto)
    for m in _RE_COORD.finditer(plano):
        valores = [_para_float(t) for t in _RE_NUM.findall(m.group("resto"))]
        este = next((i for i, v in enumerate(valores) if 1e5 <= v < 1e6), None)
        if (
            este is None
            or este + 1 >= len(valores)
            or not 1e6 <= valores[este + 1] < 1e7
        ):
            continue
        item = {
            "id": _id_limpo(m.group("id")),
            "E": valores[este],
            "N": valores[este + 1],
        }
        if este + 2 < len(valores) and 0 <= valores[este + 2] < 1e4:
            item["cota_boca"] = valores[este + 2]
        achados.setdefault(_chave(m.group("id")), item)
    return achados


def _trechos_por_furo(texto: str) -> dict[str, dict]:
    """Divide o texto em trechos por furo citado: {chave: {id, linhas}}. Cada trecho vai até o próximo furo."""
    trechos, atual = {}, None
    for linha in texto.splitlines():
        m = _RE_ID.search(linha)
        cabecalho = (
            m
            and not re.search(r"\d{6,}", linha.replace(".", "").replace(",", ""))
            and (
                re.search(r"FURO|SONDAGEM|PERFIL", _sem_acento(linha).upper())
                or linha.strip() == m.group(1)
            )
        )
        if cabecalho:
            atual = trechos.setdefault(
                _chave(m.group(1)), {"id": _id_limpo(m.group(1)), "linhas": []}
            )
        elif atual is not None:
            atual["linhas"].append(linha)
    return trechos


def _nivel_dagua(linhas: list[str]):
    """(achou, na_m): NA em m, ou None se 'não atingido'/'seco'. achou=False se o laudo não cita o NA."""
    for i, linha in enumerate(linhas):
        norm = _sem_acento(linha).upper()
        m = _RE_NA.search(norm)
        if not m:
            continue
        resto = norm[m.end() :] or (
            _sem_acento(linhas[i + 1]).upper() if i + 1 < len(linhas) else ""
        )
        sem, num = _RE_SEM_NA.search(resto), _RE_NUM_M.search(resto)
        if num and (not sem or num.start() < sem.start()):
            return True, _para_float(num.group(1))
        if sem:
            return True, None
    return False, None


def _perfil(linhas: list[str]) -> dict:
    """Camadas, NSPT, profundidade e cota do trecho de um furo."""
    camadas, nspt = [], []
    for linha in linhas:
        c, n = _RE_CAMADA.match(linha), _RE_NSPT.match(linha)
        if c:
            camadas.append(
                {
                    "de": _para_float(c.group(1)),
                    "ate": _para_float(c.group(2)),
                    "descricao": c.group(3).strip(),
                }
            )
        elif n and _para_float(n.group(1)) <= 60:
            nspt.append([_para_float(n.group(1)), int(n.group(2))])
    texto = _sem_acento("\n".join(linhas)).upper()
    prof, cota = _RE_PROF.search(texto), _RE_COTA.search(texto)
    return {
        "camadas": camadas,
        "nspt": nspt,
        "impenetravel": "IMPENETRAVEL" in texto,
        "profundidade_m": _para_float(prof.group(1))
        if prof
        else (camadas[-1]["ate"] if camadas else None),
        "cota_boca": _para_float(cota.group(1)) if cota else None,
    }


def _montar_furo(coord: dict | None, trecho: dict | None, fonte: str) -> dict:
    perfil = _perfil(trecho["linhas"]) if trecho else {"camadas": [], "nspt": []}
    achou_na, na = _nivel_dagua(trecho["linhas"]) if trecho else (False, None)
    furo = {"id": (coord or trecho)["id"], "E": coord["E"], "N": coord["N"]}
    cota = coord.get("cota_boca", perfil.get("cota_boca"))
    if cota is not None:
        furo["cota_boca"] = cota
    furo["na_m"] = na if achou_na else None
    for campo in ("profundidade_m", "impenetravel", "camadas", "nspt"):
        if perfil.get(campo) not in (None, []):
            furo[campo] = perfil[campo]
    furo["fonte"] = fonte
    return furo


def ler_laudo(caminho_pdf) -> dict:
    """Lê um laudo de sondagem em PDF pelo texto.

    Devolve {"furos": [...], "nao_lidos": [{"id", "motivo"}], "paginas_lidas": n}. Nada é inventado: furo sem
    coordenada, sem camadas ou reprovado em `validar_furos` vai para `nao_lidos` com o motivo.
    """
    import pymupdf

    caminho = Path(caminho_pdf)
    with pymupdf.open(caminho) as doc:
        texto = "\n".join(pagina.get_text() for pagina in doc)
        paginas = len(doc)
    coordenadas, trechos = _coordenadas(texto), _trechos_por_furo(texto)
    candidatos, nao_lidos = [], []
    for chave in sorted(set(coordenadas) | set(trechos)):
        coord, trecho = coordenadas.get(chave), trechos.get(chave)
        rotulo = (coord or trecho)["id"]
        if coord is None:
            nao_lidos.append(
                {
                    "id": rotulo,
                    "motivo": "sem coordenada (E/N) na tabela de coordenadas",
                }
            )
        elif not trecho or not _perfil(trecho["linhas"])["camadas"]:
            nao_lidos.append({"id": rotulo, "motivo": "sem camadas no perfil"})
        else:
            candidatos.append(_montar_furo(coord, trecho, caminho.name))
    furos, erros = validar_furos(candidatos)
    nao_lidos += [
        {"id": e["id"], "motivo": f"reprovado na validação: {e['motivo']}"}
        for e in erros
    ]
    return {"furos": furos, "nao_lidos": nao_lidos, "paginas_lidas": paginas}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Lê um laudo de sondagem (PDF) e devolve os furos no schema canônico"
    )
    ap.add_argument("laudo")
    ap.add_argument(
        "--saida", help="grava {meta, furos} neste JSON (formato de sondagens.json)"
    )
    a = ap.parse_args(argv)
    r = ler_laudo(a.laudo)
    print(
        f"{len(r['furos'])} furos lidos, {len(r['nao_lidos'])} não lidos, {r['paginas_lidas']} páginas"
    )
    for f in r["furos"]:
        na = (
            "NA não atingido"
            if f["na_m"] is None
            else f"NA {f['na_m']:.2f} m".replace(".", ",")
        )
        print(
            f"  {f['id']}: E={f['E']:.2f} N={f['N']:.2f}, {len(f.get('camadas', []))} camadas, {na}"
        )
    for n in r["nao_lidos"]:
        print(f"  NÃO LIDO {n['id']}: {n['motivo']}")
    if a.saida:
        meta = {
            "fonte": Path(a.laudo).name,
            "nao_lidos": r["nao_lidos"],
            "paginas_lidas": r["paginas_lidas"],
        }
        Path(a.saida).write_text(
            json.dumps(
                {"meta": meta, "furos": r["furos"]}, ensure_ascii=False, indent=1
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
