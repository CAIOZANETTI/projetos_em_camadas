"""Eixo e estaqueamento da obra linear: a estaca é a coordenada; E/N servem só para desenhar.

    eixo                 = polilinha E/N (m) com a progressiva acumulada em cada vértice
    estaca <-> progressiva = "12+10,00" <-> 250,00 m (passo de 20 m, `conceitos/lineares.json`)
    ponto_em             = E/N numa progressiva (interpolação linear)
    progressiva_de       = projeção ortogonal de pontos no eixo: progressiva, afastamento e lado
    segmento             = a polilinha entre duas progressivas (o trecho)
    ler_perfil           = a grade do perfil longitudinal (estaca, terreno, geratriz) lida do PDF

Premissas em `conceitos/lineares.json`. O eixo é uma polilinha: curvas entram como vértices próximos.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np

REGRAS = json.loads(
    (Path(__file__).resolve().parent.parent / "conceitos" / "lineares.json").read_text(
        encoding="utf-8"
    )
)
PERFIL = REGRAS["perfil"]
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


_NUMERO = re.compile(r"[+-]?\d+(?:[.,]\d+)*")
_VALOR = re.compile(r"\d+(?:\+\d+(?:[.,]\d+)?)?(?:[.,]\d+)*")


def _sem_acento_maiusculo(texto: str) -> str:
    """Rótulo normalizado: sem acento, em maiúsculas, sem parênteses/pontuação e com espaços únicos."""
    base = unicodedata.normalize("NFD", str(texto))
    base = "".join(c for c in base if unicodedata.category(c) != "Mn")
    base = re.sub(r"\(.*?\)", " ", base)
    return " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", base).upper().split())


def numero_brasileiro(texto: str) -> float:
    """Número em formato brasileiro: '1.234,56' -> 1234.56, '745,20' -> 745.2; só com ponto, '745.20' é decimal e
    '1.234' (grupos de 3 dígitos) é milhar. Erro de ValueError se não for número."""
    t = str(texto).strip().replace("\u2212", "-")
    if not _NUMERO.fullmatch(t):
        raise ValueError(f"número não reconhecido: {texto!r}")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    return float(t)


def _palavras_do_pdf(caminho, pagina: int) -> tuple[list[tuple], str]:
    """Palavras (cx, cy, texto) em pt da folha: texto do PDF; com poucas palavras, OCR dos glifos (`fonte`)."""
    import pymupdf

    with pymupdf.open(caminho) as doc:
        pg = doc[pagina]
        palavras = []
        for x0, y0, x1, y1, texto, *_ in pg.get_text("words"):
            r = pymupdf.Rect(x0, y0, x1, y1) * pg.rotation_matrix
            palavras.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, texto))
        if len(palavras) >= PERFIL["min_palavras_texto"]:
            return palavras, "texto do PDF"
        # sem texto suficiente (SHX/traço): rasteriza a página, igual a `prancha._imagem`, e lê com tesseract
        from . import prancha

        dpi = float(PERFIL["dpi_ocr"])
        imagem = prancha._imagem(pg, dpi=int(dpi))
    import pytesseract

    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    dados = pytesseract.image_to_data(
        imagem, lang="por", config="--psm 11", output_type=pytesseract.Output.DICT
    )
    pt_por_px = 72.0 / dpi
    palavras = [
        (
            (dados["left"][i] + dados["width"][i] / 2) * pt_por_px,
            (dados["top"][i] + dados["height"][i] / 2) * pt_por_px,
            dados["text"][i].strip(),
        )
        for i in range(len(dados["text"]))
        if dados["text"][i].strip()
    ]
    return palavras, "OCR"


def _linhas_rotuladas(palavras: list[tuple]) -> dict:
    """Linhas da grade por papel: {papel: [(cx, valor_texto)]}. A linha é o grupo de palavras na mesma ordenada
    (tolerância `tolerancia_linha_pt`); o rótulo são as palavras iniciais que não são valor e deve ser igual a um
    sinônimo (então 'GERATRIZ SUPERIOR' não vira 'GERATRIZ'). Se o papel aparece em mais de uma linha, vale a de cima."""
    tol_pt = float(PERFIL["tolerancia_linha_pt"])
    sinonimos = {
        _sem_acento_maiusculo(s): papel
        for papel, lista in PERFIL["rotulos"].items()
        for s in lista
    }
    grupos: list[list[tuple]] = []
    for p in sorted(palavras, key=lambda p: p[1]):
        if grupos and abs(p[1] - grupos[-1][0][1]) <= tol_pt:
            grupos[-1].append(p)
        else:
            grupos.append([p])
    achadas: dict = {}
    for grupo in grupos:
        grupo = sorted(grupo, key=lambda p: p[0])
        n = 0
        while n < len(grupo) and not _VALOR.fullmatch(grupo[n][2]):
            n += 1
        papel = sinonimos.get(_sem_acento_maiusculo(" ".join(p[2] for p in grupo[:n])))
        valores = [(p[0], p[2]) for p in grupo[n:]]
        if papel and valores and papel not in achadas:
            achadas[papel] = valores
    return achadas


def _na_coluna(valores: list[tuple], cx: float) -> str | None:
    """Valor da linha cuja abscissa é a mais próxima de `cx`, dentro de `tolerancia_coluna_pt`; None se não há."""
    if not valores:
        return None
    cx_valor, texto = min(valores, key=lambda v: abs(v[0] - cx))
    return (
        texto if abs(cx_valor - cx) <= float(PERFIL["tolerancia_coluna_pt"]) else None
    )


def _linhas_ausentes(linhas: dict) -> str | None:
    """Motivo se faltam linhas essenciais (estaca, terreno, geratriz ou profundidade escrita); None se está completo."""
    ausentes = [p for p in ("estaca", "terreno") if p not in linhas]
    if "geratriz" not in linhas and "profundidade" not in linhas:
        ausentes.append("geratriz")
    if not ausentes:
        return None
    nomes = {
        "estaca": "estaca",
        "terreno": "cota do terreno",
        "geratriz": "cota da geratriz (e sem profundidade escrita)",
    }
    return "perfil sem a linha de " + ", ".join(nomes[a] for a in ausentes)


def _valores_da_coluna(linhas: dict, cx: float) -> dict:
    """Terreno, geratriz e profundidade escrita (m) na coluna `cx`; None onde falta. ValueError se não for número."""
    valores = {}
    for papel in ("terreno", "geratriz", "profundidade"):
        texto = _na_coluna(linhas.get(papel, []), cx)
        valores[papel] = numero_brasileiro(texto) if texto else None
    return valores


def _ponto_da_coluna(
    linhas: dict, cx: float, texto_estaca: str, passo_m: float, ultima_m: float
) -> dict:
    """Ponto do perfil na coluna `cx` da estaca, ou {"estaca", "motivo"} se não dá para ler (nunca inventa)."""
    try:
        progressiva_m = estaca_para_progressiva(texto_estaca, passo_m)
        valores = _valores_da_coluna(linhas, cx)
    except ValueError as erro:
        return {"estaca": texto_estaca, "motivo": str(erro)}
    terreno_m, geratriz_m, escrita_m = (
        valores["terreno"],
        valores["geratriz"],
        valores["profundidade"],
    )
    if progressiva_m <= ultima_m + TOLERANCIA_M:
        motivo = f"progressiva {progressiva_m:.2f} m fora de ordem (anterior {ultima_m:.2f} m)"
    elif terreno_m is None:
        motivo = "sem cota do terreno na coluna"
    elif geratriz_m is None and escrita_m is None:
        motivo = "sem cota da geratriz na coluna"
    else:
        motivo = None
    if motivo:
        return {"estaca": texto_estaca, "motivo": motivo}
    if escrita_m is not None:
        profundidade_m, origem = escrita_m, "escrita no perfil"
    else:
        from . import valas  # import tardio: valas passará a chamar este módulo

        berco_m = float(valas.VALOR["berco_m"])
        profundidade_m = terreno_m - (geratriz_m - berco_m)
        origem = "terreno − geratriz + berço"
    return {
        "estaca": texto_estaca,
        "progressiva_m": progressiva_m,
        "cota_terreno_m": terreno_m,
        "cota_geratriz_m": geratriz_m,
        "profundidade_m": float(profundidade_m),
        "fonte_profundidade": origem,
    }


def ler_perfil(caminho_pdf, pagina: int = 0, passo_m: float = PASSO_M) -> dict:
    """Perfil longitudinal lido da grade sob o desenho: {"pontos", "nao_lidos", "fonte"}.

    Algoritmo (premissas em `conceitos/lineares.json`, chave `perfil`):
      1. palavras com posição: texto do PDF (pymupdf `get_text("words")`); se a página tem menos de
         `min_palavras_texto` palavras, OCR da página rasterizada (tesseract, a mesma imagem de `prancha._imagem`)
         e `fonte = "OCR"`; senão `fonte = "texto do PDF"`;
      2. acha as linhas-rótulo (estaca, terreno, geratriz, profundidade) pelos sinônimos, sem acento e em maiúsculas;
      3. para cada valor da linha de estacas pega, na mesma coluna (abscissa a menos de `tolerancia_coluna_pt`),
         o valor das linhas de terreno, geratriz e profundidade;
      4. monta {estaca, progressiva_m, cota_terreno_m, cota_geratriz_m, profundidade_m, fonte_profundidade} com
         cota_geratriz_m = geratriz INFERIOR e profundidade_m = cota_terreno_m - (cota_geratriz_m - berco_m); se a
         linha de profundidade está escrita ela vale ("escrita no perfil"), senão "terreno − geratriz + berço".
    Não inventa: sem linha de estaca, de terreno, ou sem geratriz e sem profundidade escrita, `pontos` fica vazio e
    `nao_lidos` traz o motivo; coluna sem valor, estaca ilegível ou progressiva que não cresce vai para `nao_lidos`
    com a `estaca` e o `motivo`. Números em formato brasileiro, estaca 'N+DD,DD'. Cotas e profundidades em metros.
    """
    palavras, fonte = _palavras_do_pdf(caminho_pdf, pagina)
    linhas = _linhas_rotuladas(palavras)
    resultado = {"pontos": [], "nao_lidos": [], "fonte": fonte}
    motivo = _linhas_ausentes(linhas)
    if motivo:
        resultado["nao_lidos"].append({"motivo": motivo})
        return resultado
    ultima_m = -np.inf
    for cx, texto_estaca in sorted(linhas["estaca"]):
        lido = _ponto_da_coluna(linhas, cx, texto_estaca, passo_m, ultima_m)
        if "motivo" in lido:
            resultado["nao_lidos"].append(lido)
        else:
            resultado["pontos"].append(lido)
            ultima_m = lido["progressiva_m"]
    return resultado


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
            "numero_brasileiro",
            "ler_perfil",
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
            {
                "aplicacao": {
                    "ler_perfil": [
                        "perfil.rotulos",
                        "perfil.tolerancia_linha_pt",
                        "perfil.tolerancia_coluna_pt",
                        "perfil.min_palavras_texto",
                        "perfil.dpi_ocr",
                    ]
                },
                "fonte": PERFIL["fonte"],
                "estado": PERFIL["estado"],
            },
        ],
        "ultima_revisao": meta["data_referencia"],
    }
