"""Eixo e estaqueamento da obra linear: a estaca é a coordenada; E/N servem só para desenhar.

    eixo                 = polilinha E/N (m) com a progressiva acumulada em cada vértice
    estaca <-> progressiva = "12+10,00" <-> 250,00 m (passo de 20 m, `conceitos/lineares.json`)
    ponto_em             = E/N numa progressiva (interpolação linear)
    progressiva_de       = projeção ortogonal de pontos no eixo: progressiva, afastamento e lado
    segmento             = a polilinha entre duas progressivas (o trecho)
    ler_perfil           = a grade do perfil longitudinal (estaca, terreno, geratriz) lida do PDF
    dimensionar_vala     = a regra única de vala do trecho (L3a):
        profundidade     = média do perfil ponderada pela extensão; sem perfil, `prof_m` do trecho (premissa, com
                           alerta); sem nenhum, nada é calculado (alerta)
        largura          = MOS (obras_lineares.largura); escorado = NR-18 (> 1,25 m, obras_lineares.escorar)
        tipo_escoramento = faixa de profundidade, elevada a contínuo por solo não coesivo, solo mole, NSPT < 4 ou
                           fundo abaixo do NA (modelo geotécnico único)
        esgotamento      = fração do trecho com fundo abaixo do NA (geotecnia.na_m) e bomba × ponteiras
        volumes          = obras_lineares.vca / mnd (fórmulas da planilha da Giselle)

Premissas em `conceitos/lineares.json`. O eixo é uma polilinha: curvas entram como vértices próximos.
`obras_lineares` importa este módulo no topo; este importa `obras_lineares` e `valas` tarde (dentro das funções), para
não haver import circular.
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

import numpy as np

from . import geotecnia as geo

# módulos de que o cálculo depende mas que este importa só dentro das funções (para não haver ciclo de import):
# `gavetas.impressao_regra` também os percorre, para que a chave de um serviço veja a Tabela I do MOS
DEPENDENCIAS = ("camadas.obras_lineares", "camadas.valas")

REGRAS = json.loads(
    (Path(__file__).resolve().parent.parent / "conceitos" / "lineares.json").read_text(
        encoding="utf-8"
    )
)
PERFIL = REGRAS["perfil"]
VALA = REGRAS["vala"]
TRECHOS = REGRAS["trechos"]
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
    if not {"geratriz", "fundo", "profundidade"} & set(linhas):
        ausentes.append("geratriz")
    if not ausentes:
        return None
    nomes = {
        "estaca": "estaca",
        "terreno": "cota do terreno",
        "geratriz": "cota da geratriz ou do fundo da vala (e sem profundidade escrita)",
    }
    return "perfil sem a linha de " + ", ".join(nomes[a] for a in ausentes)


def _valores_da_coluna(linhas: dict, cx: float) -> dict:
    """Terreno, geratriz, fundo da vala e profundidade escrita (m) na coluna `cx`; None onde falta. ValueError se não
    for número."""
    valores = {}
    for papel in ("terreno", "geratriz", "fundo", "profundidade"):
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
    elif geratriz_m is None and valores["fundo"] is None and escrita_m is None:
        motivo = "sem cota da geratriz nem do fundo da vala na coluna"
    else:
        motivo = None
    if motivo:
        return {"estaca": texto_estaca, "motivo": motivo}
    from . import valas  # import tardio: valas passará a chamar este módulo

    berco_m = float(valas.VALOR["berco_m"])
    if (
        geratriz_m is None and valores["fundo"] is not None
    ):  # cota do fundo da vala: o berço já está dentro
        geratriz_m = valores["fundo"] + berco_m
    if escrita_m is not None:
        profundidade_m, origem = escrita_m, "escrita no perfil"
    elif valores["fundo"] is not None and valores["geratriz"] is None:
        profundidade_m, origem = terreno_m - valores["fundo"], "terreno − fundo da vala"
    else:
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


# --------------------------------------------------------------------------------------------------------------------
# Dimensionador único de vala (L3a)
# --------------------------------------------------------------------------------------------------------------------


def _virgula(valor: float) -> str:
    """Número com 2 casas e vírgula decimal, para as mensagens."""
    return f"{float(valor):.2f}".replace(".", ",")


def profundidade_do_perfil(
    perfil, p0_m: float | None = None, p1_m: float | None = None
) -> float | None:
    """Profundidade média (m) do perfil entre as progressivas `p0_m` e `p1_m`, ponderada pela extensão: integral da
    interpolação linear dos pontos ÷ extensão, ao mm. `perfil` é o retorno de `ler_perfil` (ou a lista de pontos);
    sem `p0_m`/`p1_m`, vale o perfil inteiro. None com menos de 2 pontos ou se o perfil não cobre o trecho
    (tolerância absoluta `tolerancia_m`): nunca extrapola."""
    pontos = (
        perfil.get("pontos", []) if isinstance(perfil, dict) else list(perfil or [])
    )
    pares = sorted(
        (float(p["progressiva_m"]), float(p["profundidade_m"]))
        for p in pontos
        if p.get("progressiva_m") is not None and p.get("profundidade_m") is not None
    )
    if len(pares) < 2:
        return None
    progressiva_m, profundidade_m = np.asarray(pares, dtype=np.float64).T
    inicio_m = progressiva_m[0] if p0_m is None else float(p0_m)
    fim_m = progressiva_m[-1] if p1_m is None else float(p1_m)
    if (
        fim_m - inicio_m <= TOLERANCIA_M
        or inicio_m < progressiva_m[0] - TOLERANCIA_M
        or fim_m > progressiva_m[-1] + TOLERANCIA_M
    ):
        return None
    dentro = (progressiva_m > inicio_m) & (progressiva_m < fim_m)
    x_m = np.concatenate([[inicio_m], progressiva_m[dentro], [fim_m]])
    y_m = np.interp(x_m, progressiva_m, profundidade_m)
    area_m2 = float(np.sum((y_m[1:] + y_m[:-1]) / 2 * np.diff(x_m)))
    return round(area_m2 / (fim_m - inicio_m), 3)


def _profundidade(trecho: dict, perfil) -> tuple[float | None, str, list[str]]:
    """(profundidade_m, fonte, alertas): o perfil quando cobre o trecho; senão o `prof_m` do trecho (premissa, com
    alerta); senão None e fonte 'ausente' (a falta já vira alerta nas quantidades)."""
    nomes = VALA["progressivas"]
    p0_m, p1_m = trecho.get(nomes["inicio"]), trecho.get(nomes["fim"])
    alertas = []
    if perfil is not None:
        profundidade_m = profundidade_do_perfil(perfil, p0_m, p1_m)
        if profundidade_m is not None:
            return profundidade_m, "perfil longitudinal", []
        alertas.append(
            f"perfil longitudinal não cobre o trecho ({p0_m} a {p1_m} m) ou tem menos de 2 pontos"
        )
    prof_m = trecho.get("prof_m")
    if prof_m:
        alertas.append(
            f"profundidade de premissa: prof_m do trecho ({_virgula(prof_m)} m), não do perfil longitudinal"
        )
        return float(prof_m), "premissa do trecho (prof_m)", alertas
    return None, "ausente", alertas


def _quantidades(t: dict, furos: list[dict], pts) -> dict:
    """Escoramento (NR-18), largura (MOS), volumes do método (VCA ou MND), geotecnia e alertas: exatamente o que
    `obras_lineares.quantificar` devolve (mesmos nomes e valores, gabarito da planilha da Giselle)."""
    from . import obras_lineares as ol

    prof_m, alertas = t.get("prof_m"), []
    t["escorado"] = ol.escorar(prof_m)
    geotec = ol.geotecnia(t, furos, pts)
    if not prof_m:
        alertas.append(
            "sem profundidade média: largura, escoramento e volumes não calculados"
        )
    largura_m = (
        ol.largura(t["dn_mm"], t["material"], prof_m, t["escorado"], t.get("junta"))
        if prof_m
        else None
    )
    if prof_m and largura_m is None:
        alertas.append(
            f"material {t['material']} DN {t['dn_mm']} fora da Tabela I do MOS"
        )
    q = ol.mnd(t) if t["metodo"] == "MND" else ol.vca(t, largura_m) if largura_m else {}
    if geotec["esgotamento_frac"] > 0:
        alertas.append(
            f"NA ({geotec['na_min_m']} m) acima do fundo da vala ({prof_m} m): esgotamento de vala"
        )
    if geotec["sem_sondagem_frac"] > 0:
        alertas.append(
            f"{geotec['sem_sondagem_frac']:.0%} do trecho sem sondagem dentro do raio de influência"
        )
    soma_pav_m = sum((t.get("pavimentos") or {}).values())
    if t["metodo"] == "VCA" and soma_pav_m and abs(soma_pav_m - t["comp_m"]) > 0.05:
        alertas.append(
            f"pavimentos somam {soma_pav_m:g} m e o trecho tem {t['comp_m']:g} m"
        )
    return {**t, **q, "geotecnia": geotec, "alertas": alertas}


def _agravantes(
    trecho: dict, furos: list[dict], profundidade_m: float, geotec: dict
) -> list[str]:
    """Motivos que pedem escoramento contínuo: solo não coesivo na vala, solo mole (designação do laudo ou NSPT
    abaixo do mínimo até o fundo) e fundo abaixo do NA. `furos` = os que cobrem o trecho."""
    from . import obras_lineares as ol

    ag = VALA["agravantes"]
    classes = sorted(
        c for c, f in geotec["solos"].items() if f > 0 and c in ag["solos_nao_coesivos"]
    )
    descricoes = [
        str(c.get("descricao") or "")
        for f in furos
        for c in f.get("camadas") or []
        if c.get("de") is not None and c["de"] < profundidade_m
    ]
    if not furos and trecho.get("solo"):
        descricoes.append(str(trecho["solo"]))
    golpes = [
        int(g)
        for f in furos
        for p_m, g in f.get("nspt") or []
        if p_m <= profundidade_m + TOLERANCIA_M
    ]
    motivos = [f"solo não coesivo ({', '.join(classes)})"] if classes else []
    if any(re.search(ag["regex_mole"], ol.norm(d)) for d in descricoes):
        motivos.append("solo mole (designação do laudo)")
    if golpes and min(golpes) < ag["nspt_min"]:
        motivos.append(f"NSPT {min(golpes)} < {ag['nspt_min']}")
    if geotec["esgotamento_frac"] > 0:
        motivos.append("fundo abaixo do NA")
    return motivos


def tipo_escoramento(profundidade_m: float | None, agravantes=()) -> str:
    """'nenhum' até o limite da NR-18 (`obras_lineares.escorar`, 1,25 m); acima, o tipo da faixa de profundidade
    (`conceitos/lineares.json`, vala.escoramento), elevado ao `tipo_minimo` (contínuo) se houver agravante."""
    from . import obras_lineares as ol

    if not ol.escorar(profundidade_m):
        return "nenhum"
    faixas = VALA["escoramento"]["faixas"]
    tipo = next(
        f["tipo"] for f in faixas if f["ate_m"] is None or profundidade_m <= f["ate_m"]
    )
    ordem = [f["tipo"] for f in faixas]
    minimo = VALA["agravantes"]["tipo_minimo"]
    return minimo if agravantes and ordem.index(tipo) < ordem.index(minimo) else tipo


def tipo_esgotamento(
    esgotamento_frac: float, altura_agua_m: float, solo_nao_coesivo: bool = False
) -> str:
    """'nenhum' sem água na vala; 'ponteiras' com solo não coesivo na faixa submersa ou altura de água acima de
    `altura_agua_max_bomba_m` (0,5 m); senão 'bomba' (submersível)."""
    if esgotamento_frac <= 0 or altura_agua_m <= 0:
        return "nenhum"
    limite_m = VALA["esgotamento"]["altura_agua_max_bomba_m"]
    return "ponteiras" if solo_nao_coesivo or altura_agua_m > limite_m else "bomba"


def _submerso_nao_coesivo(
    furos: list[dict], profundidade_m: float, geotec: dict
) -> bool:
    """Há solo não coesivo entre o NA de projeto e o fundo em algum furo do trecho (sem furo: o solo da planilha)."""
    nao_coesivos = set(VALA["agravantes"]["solos_nao_coesivos"])
    if not furos:
        return geotec["esgotamento_frac"] > 0 and bool(
            nao_coesivos & set(geotec["solos"])
        )
    return any(
        nivel_m is not None
        and nivel_m < profundidade_m
        and bool(nao_coesivos & set(geo.solo_na_faixa(f, nivel_m, profundidade_m)))
        for f in furos
        for nivel_m in [geo.na_m(f)]
    )


def _alertas_na(trecho: dict, furos: list[dict], profundidade_m: float) -> list[str]:
    """`geotecnia.alerta_na` de cada furo do trecho (NA sazonal); sem furo, o NA digitado na planilha."""
    if not furos and isinstance(trecho.get("na_m"), (int, float)):
        rotulo = f"{trecho.get('sond_ini') or 'sem id'} (NA da planilha)"
        furos = [{"id": rotulo, "na_m": trecho["na_m"]}]
    return list(
        dict.fromkeys(a for f in furos if (a := geo.alerta_na(f, profundidade_m)))
    )


def _acrescimos(
    t: dict, base: dict, furos: list[dict], profundidade_m, fonte: str
) -> dict:
    """O que o dimensionador acrescenta à saída de `obras_lineares.quantificar` (sem os alertas da profundidade)."""
    geotec, vca = base["geotecnia"], t["metodo"] != "MND"
    agravantes = _agravantes(t, furos, profundidade_m, geotec) if profundidade_m else []
    tipo = (
        tipo_escoramento(profundidade_m, agravantes) if vca and profundidade_m else None
    )
    na_min_m = geotec["na_min_m"]
    altura_agua_m = (
        round(max(0.0, profundidade_m - na_min_m), 3)
        if profundidade_m and na_min_m is not None and geotec["esgotamento_frac"] > 0
        else 0.0
    )
    alertas = _alertas_na(t, furos, profundidade_m) if profundidade_m else []
    if tipo == "nenhum" and agravantes:
        alertas.append(
            f"vala de {_virgula(profundidade_m)} m, sem escoramento obrigatório pela NR-18, com "
            + ", ".join(agravantes)
            + ": conferir a estabilidade das paredes"
        )
    submerso = (
        _submerso_nao_coesivo(furos, profundidade_m, geotec)
        if profundidade_m
        else False
    )
    return {
        "largura_m": base.get("largura_m"),
        "profundidade_m": profundidade_m,
        "fonte_profundidade": fonte,
        "escorado": base["escorado"],
        "tipo_escoramento": tipo,
        "agravantes_escoramento": agravantes,
        "escoramento_m2": base.get("escoramento_m2"),
        "esgotamento_frac": geotec["esgotamento_frac"],
        "altura_agua_m": altura_agua_m,
        "tipo_esgotamento": tipo_esgotamento(
            geotec["esgotamento_frac"], altura_agua_m, submerso
        )
        if profundidade_m
        else None,
        "alertas": alertas,
    }


def vala_do_trecho(
    trecho: dict,
    furos: list[dict] | None = None,
    perfil=None,
    pts: np.ndarray | None = None,
) -> tuple[dict, dict]:
    """A regra única de vala: (saída no formato de `obras_lineares.quantificar`, acréscimos do dimensionador).

    A profundidade vem do perfil (quando cobre o trecho), senão do `prof_m`; com o perfil, `prof_m` passa a ser a do
    perfil. Sem `comp_m` e com `p0_m`/`p1_m`, o comprimento é p1_m − p0_m."""
    from . import obras_lineares as ol

    profundidade_m, fonte, alertas_prof = _profundidade(trecho, perfil)
    t = {**trecho, "metodo": ol.norm(trecho.get("metodo") or "VCA")}
    if fonte == "perfil longitudinal":
        t["prof_m"] = profundidade_m
    p0_m, p1_m = (trecho.get(VALA["progressivas"][k]) for k in ("inicio", "fim"))
    if t.get("comp_m") is None and p0_m is not None and p1_m is not None:
        t["comp_m"] = round(float(p1_m) - float(p0_m), 3)
    base = _quantidades(t, furos or [], pts)
    cobertos = [f for f, _ in ol.furos_do_trecho(t, furos or [], pts) if f is not None]
    acrescimos = _acrescimos(t, base, cobertos, profundidade_m, fonte)
    acrescimos["alertas"] = base["alertas"] + alertas_prof + acrescimos["alertas"]
    return base, acrescimos


def dimensionar_vala(
    trecho: dict,
    furos: list[dict] | None = None,
    perfil=None,
    pts: np.ndarray | None = None,
) -> dict:
    """Vala do trecho pela regra única: todas as chaves de `obras_lineares.quantificar` (mesmos nomes e valores) mais
    largura_m, profundidade_m, fonte_profundidade, escorado, tipo_escoramento, agravantes_escoramento, escoramento_m2,
    esgotamento_frac, altura_agua_m, tipo_esgotamento e alertas (os de `quantificar`, a profundidade de premissa e o
    `geotecnia.alerta_na`).

    `trecho` = o dict que `obras_lineares.quantificar` recebe (local, dn_mm, material, junta, prof_m, comp_m, metodo,
    pavimentos, supressao_frac, sond_ini/sond_fim, na_m, solo; e, com perfil, p0_m/p1_m); `furos` no schema de
    `conceitos/geotecnia.json`; `perfil` = retorno de `ler_perfil`; `pts` = eixo amostrado (UTM) para a sondagem de
    cada metro. Profundidades e larguras em m, áreas em m², volumes em m³.
    """
    base, acrescimos = vala_do_trecho(trecho, furos, perfil, pts)
    return {**base, **acrescimos}


def _fronteiras_m(comprimento_m: float, cortes: dict) -> np.ndarray:
    """Progressivas (m) onde o eixo se parte: pontas, fronteiras de superfície, pontos médios entre furos
    consecutivos e PVs. Ordenadas, sem repetição e sem vão menor que `trechos.comprimento_minimo_m`."""
    minimo_m = float(TRECHOS["comprimento_minimo_m"])
    candidatas = [np.zeros(1), np.full(1, comprimento_m)]
    superficie = np.asarray(
        [(p0, p1) for p0, p1, _ in cortes.get("superficie") or []], dtype=np.float64
    )
    candidatas.append(superficie.ravel())
    furos_m = np.sort(
        np.asarray([p for p, _ in cortes.get("furos") or []], dtype=np.float64)
    )
    candidatas.append((furos_m[1:] + furos_m[:-1]) / 2)
    candidatas.append(np.asarray(cortes.get("pvs") or [], dtype=np.float64))
    todas_m = np.sort(np.concatenate(candidatas))
    interiores_m = todas_m[(todas_m > minimo_m) & (todas_m < comprimento_m - minimo_m)]
    mantidas_m: list[float] = [0.0]
    for p_m in interiores_m:
        if p_m - mantidas_m[-1] >= minimo_m:
            mantidas_m.append(float(p_m))
    mantidas_m.append(float(comprimento_m))
    return np.asarray(mantidas_m, dtype=np.float64)


def trechos(eixo_: dict, cortes: dict | None = None) -> list[dict]:
    """Segmenta o eixo em trechos homogêneos e devolve a lista de dicts, em ordem de progressiva.

    `cortes = {"superficie": [(p0_m, p1_m, classe)], "furos": [(p_m, id)], "pvs": [p_m]}` (todas as chaves opcionais;
    progressivas em m, como `estaca_para_progressiva`). O eixo parte-se:
      - nas fronteiras de cada intervalo de superfície;
      - no ponto médio entre furos consecutivos (cada trecho recebe o furo mais próximo do seu centro);
      - em cada PV.
    Fronteiras a menos de `trechos.comprimento_minimo_m` uma da outra ou das pontas se fundem; as que caem fora do
    eixo são ignoradas. Cada trecho: {p0_m, p1_m, comp_m, superficie (classe que cobre o centro, ou None),
    furo (id, ou None), estaca_inicial, estaca_final}, e sond_ini/sond_fim = furo quando há, para alimentar
    `dimensionar_vala`. Determinístico; a soma de comp_m é o comprimento do eixo."""
    cortes = cortes or {}
    comprimento_m = float(eixo_["comprimento_m"])
    limites_m = _fronteiras_m(comprimento_m, cortes)
    inicio_m, fim_m = limites_m[:-1], limites_m[1:]
    centro_m = (inicio_m + fim_m) / 2
    classes = np.full(len(centro_m), None, dtype=object)
    for p0_m, p1_m, classe in reversed(cortes.get("superficie") or []):
        classes[(centro_m > p0_m) & (centro_m < p1_m)] = (
            classe  # o primeiro intervalo declarado vence
        )
    furos = sorted(cortes.get("furos") or [], key=lambda f: f[0])
    if furos:
        furos_m = np.asarray([p for p, _ in furos], dtype=np.float64)
        proximo = np.argmin(np.abs(centro_m[:, None] - furos_m[None, :]), axis=1)
        ids = [furos[i][1] for i in proximo]
    else:
        ids = [None] * len(centro_m)
    lista = []
    for i in range(len(centro_m)):
        trecho = {
            "p0_m": float(inicio_m[i]),
            "p1_m": float(fim_m[i]),
            "comp_m": round(float(fim_m[i] - inicio_m[i]), 3),
            "superficie": classes[i],
            "furo": ids[i],
            "estaca_inicial": progressiva_para_estaca(inicio_m[i]),
            "estaca_final": progressiva_para_estaca(fim_m[i]),
        }
        if ids[i] is not None:
            trecho["sond_ini"] = trecho["sond_fim"] = ids[i]
        lista.append(trecho)
    return lista


FUNCOES = (
    "eixo",
    "estaca_para_progressiva",
    "progressiva_para_estaca",
    "ponto_em",
    "progressiva_de",
    "segmento",
    "numero_brasileiro",
    "ler_perfil",
    "profundidade_do_perfil",
    "tipo_escoramento",
    "tipo_esgotamento",
    "vala_do_trecho",
    "dimensionar_vala",
    "trechos",
    "metadados",
)


def metadados() -> dict:
    """Rastreabilidade do método e das premissas declaradas (regra 9 do estilo)."""
    meta = REGRAS["metadata"]
    return {
        "modulo": "lineares",
        "descricao": "eixo e estaqueamento da obra linear (estaca <-> progressiva <-> E/N), leitor do perfil e "
        "dimensionador único de vala",
        "funcoes": list(FUNCOES),
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
            {
                "aplicacao": {"trechos": ["trechos.comprimento_minimo_m"]},
                "fonte": TRECHOS["fonte"],
                "estado": TRECHOS["estado"],
            },
            *(
                {
                    "aplicacao": {"dimensionar_vala": [f"vala.{nome}"]},
                    "fonte": VALA[nome]["fonte"],
                    "estado": VALA[nome]["estado"],
                }
                for nome in ("progressivas", "escoramento", "agravantes", "esgotamento")
            ),
        ],
        "ultima_revisao": meta["data_referencia"],
    }
