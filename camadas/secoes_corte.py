"""Seções de CORTE de escavação (pranchas vetoriais) -> área de corte e cota de fundo por seção.

É uma testemunha independente do volume das cavas calculado pelo MDS do drone: aqui só entra o que o
projetista desenhou na prancha (vista de perfil do Civil 3D), lido dos traços vetoriais por layer
(`camadas.pdf_cad.extrair`). Nada de `camadas.escavacao`, nada de IA no caminho do número.

Como cada seção é lida:

1. **Quadro** (`quadros`): retângulo do layer da vista de perfil (`C-ROAD-PROF-VIEW`), um por seção.
2. **Calibração** (`calibrar`): as marcas (ticks) da moldura são traços curtos do mesmo layer.
   Na lateral esquerda há uma marca a cada 1 m de cota (a cada 5 m, mais longa e com rótulo); na base,
   uma marca a cada 1 m de distância. As posições em pt são ajustadas por mínimos quadrados (m por pt
   e resíduo em m). A cota absoluta vem dos RÓTULOS das marcas longas, lidos por OCR (tesseract): cada
   rótulo dá uma candidata a cota da marca inferior; vale a candidata que pelo menos
   `MIN_ROTULOS_CONCORDANTES` rótulos confirmam. Isso também confere o passo de 5 m entre marcas
   longas. Sem OCR/rótulos concordantes: sem cota, alerta, nenhuma área.
3. **Terreno**: o traço mais largo do layer `TERRENO ORIGINAL` dentro do quadro (os demais traços do
   layer são etiquetas de cota, pequenas).
4. **Contorno da escavação**: o layer `ESCAVAÇÃO` mistura o contorno (tracejado desenhado como
   segmentos soltos de 2 a poucos pontos), textos em vetor (glifos pretos com dezenas de pontos),
   chamadas em outra cor e preenchimentos brancos. Separação: só traços ABERTOS, SEM preenchimento,
   com no máximo `MAX_PONTOS_SEGMENTO` pontos, na COR do contorno, que é a cor de maior comprimento
   total na prancha inteira (não por quadro, para uma seção com poucas marcas não eleger a cor errada).
   Os segmentos formam o envelope inferior (menor cota) por x; vãos entre traços de até
   `LACUNA_MAXIMA_M` são fechados por interpolação (vão do tracejado); vãos maiores viram alerta.
5. **Área** = integral em x de max(0, z_terreno - z_escavacao), exata para polilinhas (trapézios, com
   o ponto de cruzamento tratado), só onde as duas linhas existem. NumPy vetorizado.

Uso: python -m camadas.secoes_corte PDF [PDF ...] --saida secoes.json
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

import numpy as np

LAYER_QUADRO = "C-ROAD-PROF-VIEW"
LAYER_TERRENO = "TERRENO ORIGINAL"
LAYER_ESCAVACAO = "ESCAVAÇÃO"

TAMANHO_MINIMO_QUADRO_PT = (
    100.0  # menor lado de um quadro de seção; descarta caixinhas do mesmo layer
)
TOLERANCIA_EIXO_PT = (
    0.05  # retângulo/tick "alinhado ao eixo" (erro de arredondamento do PDF)
)
TOLERANCIA_TICK_BORDA_PT = (
    1.0  # o centro do tick fica sobre a borda do quadro (folga em pt)
)
PASSO_TICK_M = 1.0  # a moldura tem uma marca a cada 1 m (cota e distância)
PASSO_ROTULO_M = 5.0  # marca longa (com rótulo) a cada 5 m
FATOR_TICK_LONGO = 1.5  # tick longo = comprimento > 1,5 x o mais curto
TOLERANCIA_CALIBRACAO_M = (
    0.02  # resíduo máximo do ajuste das marcas; 2 cm = ~0,6 pt, bem acima do
)
#                                    arredondamento do PDF (0,1 pt) e bem abaixo de qualquer decisão de projeto
TOLERANCIA_ESCALA_REL = (
    0.01  # x e y com a mesma escala dentro de 1%; senão é exagero vertical (declarado)
)
SALTO_MARCAS = 10  # distância (em marcas) usada na inclinação robusta inicial
MIN_ROTULOS_CONCORDANTES = (
    2  # rótulos de cota que precisam confirmar a mesma cota da base
)
LARGURA_MINIMA_TERRENO_REL = (
    0.5  # o traço do terreno cobre ao menos metade da largura do quadro
)
MAX_PONTOS_SEGMENTO = 8  # segmento do tracejado; glifos de texto têm dezenas de pontos
LACUNA_MAXIMA_M = 1.0  # vão do tracejado que ainda se fecha por interpolação
TOLERANCIA_BORDA_M = (
    0.05  # contorno a menos de 5 cm da borda do quadro conta como "chega à borda"
)
AREA_MINIMA_M2 = (
    0.1  # abaixo disso o contorno só tangencia o terreno (ruído de traço): "sem corte"
)
OCR_DPI = 400
RAIO_ROTULO_PT = 9.0  # meia altura do recorte do rótulo de cota em torno da marca
LARGURA_ROTULO_PT = 26.0  # largura do recorte do rótulo, à esquerda da moldura
ALTURA_TITULO_PT = (
    60.0  # recorte do título "SEÇÃO XX" no canto superior esquerdo do quadro
)
LARGURA_TITULO_PT = 170.0


def _fora(x_pt: float, y_pt: float, quadro: dict, folga_pt: float = 0.5) -> bool:
    return not (
        quadro["x0_pt"] - folga_pt <= x_pt <= quadro["x1_pt"] + folga_pt
        and quadro["y0_pt"] - folga_pt <= y_pt <= quadro["y1_pt"] + folga_pt
    )


def _dentro(traco: dict, quadro: dict) -> bool:
    """Todos os pontos do traço estão dentro do quadro (folga de 0,5 pt)."""
    pontos = np.vstack(traco["partes"])
    minimo, maximo = pontos.min(0), pontos.max(0)
    return not (
        _fora(minimo[0], minimo[1], quadro) or _fora(maximo[0], maximo[1], quadro)
    )


def quadros(tracos: list[dict]) -> list[dict]:
    """Quadros das seções: retângulos alinhados aos eixos do layer da vista de perfil, em ordem de leitura."""
    achados = []
    for traco in tracos:
        if traco["layer"] != LAYER_QUADRO:
            continue
        for parte in traco["partes"]:
            if len(parte) not in (4, 5):
                continue
            extensao = np.ptp(parte, axis=0)
            alinhado = (
                np.ptp(parte[:, 0]) > 0
                and np.ptp(parte[:, 1]) > 0
                and len(np.unique(np.round(parte[:, 0], 2))) == 2
                and len(np.unique(np.round(parte[:, 1], 2))) == 2
            )
            if alinhado and extensao.min() >= TAMANHO_MINIMO_QUADRO_PT:
                (x0, y0), (x1, y1) = parte.min(0), parte.max(0)
                achados.append(
                    {
                        "x0_pt": float(x0),
                        "y0_pt": float(y0),
                        "x1_pt": float(x1),
                        "y1_pt": float(y1),
                    }
                )
    achados.sort(key=lambda q: (round(q["y0_pt"] / 100.0), q["x0_pt"]))
    for indice, quadro in enumerate(achados):
        quadro["indice"] = indice
    return achados


def _ticks(
    tracos: list[dict], quadro: dict, horizontal: bool
) -> tuple[np.ndarray, np.ndarray]:
    """Posição (pt, ao longo do eixo da marcação) e comprimento (pt) dos ticks da borda esquerda (horizontais)
    ou da borda inferior (verticais) do quadro, ordenados do começo da escala (base / esquerda) para o fim."""
    posicoes, comprimentos = [], []
    for traco in tracos:
        if traco["layer"] != LAYER_QUADRO:
            continue
        for parte in traco["partes"]:
            if len(parte) != 2:
                continue
            (xa, ya), (xb, yb) = parte
            if (
                horizontal
                and abs(ya - yb) <= TOLERANCIA_EIXO_PT
                and abs((xa + xb) / 2 - quadro["x0_pt"]) <= TOLERANCIA_TICK_BORDA_PT
                and quadro["y0_pt"] - 1 <= ya <= quadro["y1_pt"] + 1
            ):
                posicoes.append(ya)
                comprimentos.append(abs(xa - xb))
            elif (
                not horizontal
                and abs(xa - xb) <= TOLERANCIA_EIXO_PT
                and abs((ya + yb) / 2 - quadro["y1_pt"]) <= TOLERANCIA_TICK_BORDA_PT
                and quadro["x0_pt"] - 1 <= xa <= quadro["x1_pt"] + 1
            ):
                posicoes.append(xa)
                comprimentos.append(abs(ya - yb))
    posicoes, comprimentos = (
        np.array(posicoes, dtype=np.float64),
        np.array(comprimentos, dtype=np.float64),
    )
    ordem = np.argsort(
        -posicoes if horizontal else posicoes
    )  # cota: de baixo (y grande) para cima
    return posicoes[ordem], comprimentos[ordem]


def _ajustar_marcas(
    posicoes_pt: np.ndarray,
) -> tuple[float, float, float, np.ndarray, np.ndarray]:
    """Ajusta posicao_pt = a + b*k nas marcas da malha regular (k = passos de PASSO_TICK_M a partir da 1ª marca).

    Há quadros em que algumas marcas ficam deslocadas da malha de 1 m (ex.: as 5 primeiras da distância na
    seção HH). Por isso a reta inicial é robusta (mediana das inclinações entre marcas a `SALTO_MARCAS`
    passos) e só as marcas a até TOLERANCIA_CALIBRACAO_M dela entram no ajuste de mínimos quadrados; as
    outras viram alerta, não são "corrigidas". Devolve (a_pt, m_por_pt, resíduo_m, k, máscara das usadas).
    """
    passo_aprox_pt = float(np.median(np.abs(np.diff(posicoes_pt))))
    k = np.round(np.abs(posicoes_pt - posicoes_pt[0]) / passo_aprox_pt)
    sinal = np.sign(posicoes_pt[-1] - posicoes_pt[0])
    salto = min(SALTO_MARCAS, len(k) - 1)
    inclinacao = (
        float(np.median(np.diff(posicoes_pt[::salto]) / np.diff(sinal * k[::salto])))
        if len(k) > salto
        else passo_aprox_pt
    )
    a0 = float(np.median(posicoes_pt - inclinacao * sinal * k))
    tolerancia_pt = TOLERANCIA_CALIBRACAO_M / PASSO_TICK_M * abs(inclinacao)
    dentro = np.abs(posicoes_pt - (a0 + inclinacao * sinal * k)) <= tolerancia_pt
    b, a = np.polyfit(k[dentro], posicoes_pt[dentro], 1)
    residuo_pt = float(np.max(np.abs(posicoes_pt[dentro] - (a + b * k[dentro]))))
    m_por_pt = PASSO_TICK_M / abs(b)
    return float(a), float(m_por_pt), residuo_pt * m_por_pt, k.astype(int), dentro


def _sem_fragmentos_da_borda(imagem: np.ndarray) -> np.ndarray:
    """Apaga os componentes escuros que tocam a borda do recorte: traços vizinhos cortados pelo recorte
    (ticks, rótulos do quadro ao lado) que o OCR leria como dígito sobrando ("1235" em vez de "235")."""
    import cv2

    n, rotulos, estat, _ = cv2.connectedComponentsWithStats(
        (imagem < 128).astype(np.uint8), connectivity=8
    )
    limpo = imagem.copy()
    altura, largura = imagem.shape
    for i in range(1, n):
        x, y, w, h = estat[i, :4]
        if x == 0 or y == 0 or x + w == largura or y + h == altura:
            limpo[rotulos == i] = 255
    return limpo


def _imagem_ocr(
    pagina, caixa_pt: tuple, dpi: int = OCR_DPI, limpar_borda: bool = False
) -> np.ndarray:
    """Recorte da página (pt) em tons de cinza, com borda branca para o tesseract."""
    import cv2
    import pymupdf

    pixmap = pagina.get_pixmap(
        dpi=dpi, clip=pymupdf.Rect(*caixa_pt), colorspace=pymupdf.csGRAY
    )
    imagem = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
        pixmap.height, pixmap.width
    )
    if limpar_borda:
        imagem = _sem_fragmentos_da_borda(imagem)
    return cv2.copyMakeBorder(imagem, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)


def _ler_rotulos_cota(
    pagina, quadro: dict, y_longos_pt: np.ndarray
) -> list[int | None]:
    """OCR do número à esquerda de cada tick longo; None onde não leu."""
    import pytesseract

    lidos = []
    for y_pt in y_longos_pt:
        caixa = (
            quadro["x0_pt"] - 15 - LARGURA_ROTULO_PT,
            y_pt - RAIO_ROTULO_PT,
            quadro["x0_pt"] - 15,
            y_pt + RAIO_ROTULO_PT,
        )
        texto = pytesseract.image_to_string(
            _imagem_ocr(pagina, caixa, limpar_borda=True),
            config="--psm 7 -c tessedit_char_whitelist=0123456789",
        ).strip()
        lidos.append(int(texto) if texto.isdigit() else None)
    return lidos


def _cota_da_base(
    lidos: list[int | None], k_longos: np.ndarray
) -> tuple[float | None, list[str]]:
    """Cota da marca inferior (k = 0) a partir dos rótulos; k_longos = índice (em passos de 1 m) de cada marca longa.
    Vale a candidata confirmada por pelo menos MIN_ROTULOS_CONCORDANTES rótulos e pela maioria dos lidos."""
    candidatas = [
        valor - PASSO_TICK_M * int(k)
        for valor, k in zip(lidos, k_longos)
        if valor is not None
    ]
    if not candidatas:
        return None, ["nenhum rótulo de cota lido por OCR"]
    cota, votos = collections.Counter(candidatas).most_common(1)[0]
    if votos < MIN_ROTULOS_CONCORDANTES or votos * 2 <= len(candidatas):
        return None, [
            f"rótulos de cota sem concordância (melhor candidata com {votos} voto(s) de {len(candidatas)})"
        ]
    alertas = (
        []
        if votos == len(candidatas)
        else [f"{len(candidatas) - votos} rótulo(s) de cota divergem da cota da base"]
    )
    return float(cota), alertas


def _cota_da_calibracao(
    pagina,
    quadro: dict,
    y_longos_pt: np.ndarray,
    k_longos: np.ndarray,
    cota_inferior_m: float | None,
) -> tuple[float | None, list[str]]:
    """Cota da marca inferior: a informada ou, sem ela, a lida dos rótulos por OCR (com alertas)."""
    if cota_inferior_m is not None:
        return cota_inferior_m, []
    if pagina is None:
        return None, ["sem página para OCR dos rótulos de cota"]
    try:
        return _cota_da_base(_ler_rotulos_cota(pagina, quadro, y_longos_pt), k_longos)
    except Exception as erro:  # noqa: BLE001 - sem tesseract/pymupdf a seção fica sem cota, com alerta
        return None, [f"OCR indisponível: {erro.__class__.__name__}"]


def _conferir_malha(
    quadro: dict,
    comp_y: np.ndarray,
    k_y: np.ndarray,
    usadas: tuple[np.ndarray, np.ndarray],
    x_origem_pt: float,
    escalas: tuple[float, float],
) -> tuple[list[str], np.ndarray, bool]:
    """Alertas da malha de marcas, índices das marcas longas usadas e se a calibração é duvidosa."""
    alertas = []
    descartadas = int(sum((~u).sum() for u in usadas))
    if descartadas:
        alertas.append(
            f"{descartadas} marca(s) da moldura fora da malha regular de 1 m descartada(s) do ajuste"
        )
    longos_y = np.flatnonzero((comp_y > FATOR_TICK_LONGO * comp_y.min()) & usadas[0])
    duvidosa = len(longos_y) < 2 or not np.all(
        k_y[longos_y] % int(PASSO_ROTULO_M / PASSO_TICK_M) == 0
    )
    if duvidosa:
        alertas.append("marcas longas fora do passo de 5 m: calibração duvidosa")
    if abs(x_origem_pt - quadro["x0_pt"]) > TOLERANCIA_TICK_BORDA_PT:
        alertas.append(
            "a primeira marca de distância não coincide com a borda esquerda do quadro"
        )
    m_x, m_y = escalas
    if abs(m_x - m_y) / m_y > TOLERANCIA_ESCALA_REL:
        alertas.append(
            f"escalas diferentes (exagero vertical): x {m_x:.5f} m/pt, y {m_y:.5f} m/pt"
        )
    return alertas, longos_y, duvidosa


def calibrar(
    quadro: dict, tracos: list[dict], pagina=None, cota_inferior_m: float | None = None
) -> dict:
    """Transformação pt -> (distância_m, cota_m) do quadro, a partir das marcas da moldura.

    `cota_inferior_m`: cota da marca inferior, se já conhecida (pula o OCR). Senão, lida dos rótulos pelo
    OCR da `pagina` (pymupdf). Devolve {ok, m_por_pt_x, m_por_pt_y, x_origem_pt, y_base_pt, cota_base_m,
    residuo_calibracao_m, alertas}. `ok` só é True com resíduo <= TOLERANCIA_CALIBRACAO_M e cota conhecida.
    """
    vazio = dict.fromkeys(
        (
            "m_por_pt_x",
            "m_por_pt_y",
            "x_origem_pt",
            "y_base_pt",
            "cota_base_m",
            "residuo_calibracao_m",
        )
    )
    y_marcas, comp_y = _ticks(tracos, quadro, horizontal=True)
    x_marcas, _ = _ticks(tracos, quadro, horizontal=False)
    if len(y_marcas) < 3 or len(x_marcas) < 3:
        return {
            "ok": False,
            **vazio,
            "alertas": ["marcas da moldura não encontradas: sem calibração"],
        }
    y_base, m_y, resid_y, k_y, usado_y = _ajustar_marcas(y_marcas)
    x_origem, m_x, resid_x, _, usado_x = _ajustar_marcas(x_marcas)
    alertas, longos_y, duvidosa = _conferir_malha(
        quadro, comp_y, k_y, (usado_y, usado_x), x_origem, (m_x, m_y)
    )
    residuo = max(resid_y, resid_x, 1.0 if duvidosa else 0.0)
    cota, alertas_cota = _cota_da_calibracao(
        pagina, quadro, y_marcas[longos_y], k_y[longos_y], cota_inferior_m
    )
    alertas += alertas_cota
    if residuo > TOLERANCIA_CALIBRACAO_M:
        alertas.append(
            f"resíduo da calibração {residuo:.3f} m acima de {TOLERANCIA_CALIBRACAO_M} m"
        )
    return {
        "ok": bool(cota is not None and residuo <= TOLERANCIA_CALIBRACAO_M),
        "m_por_pt_x": m_x,
        "m_por_pt_y": m_y,
        "x_origem_pt": x_origem,
        "y_base_pt": y_base,
        "cota_base_m": cota,
        "residuo_calibracao_m": float(residuo),
        "alertas": alertas,
    }


def _para_metros(pontos_pt: np.ndarray, cal: dict) -> np.ndarray:
    """(N, 2) em pt -> (N, 2) em (distância_m, cota_m)."""
    distancia_m = (pontos_pt[:, 0] - cal["x_origem_pt"]) * cal["m_por_pt_x"]
    cota_m = (
        cal["cota_base_m"] + (cal["y_base_pt"] - pontos_pt[:, 1]) * cal["m_por_pt_y"]
    )
    return np.column_stack([distancia_m, cota_m])


def _terreno(tracos: list[dict], quadro: dict) -> np.ndarray | None:
    """Pontos (pt) do traço mais largo do layer do terreno dentro do quadro; None se não houver."""
    melhor, largura = None, 0.0
    for traco in tracos:
        if traco["layer"] != LAYER_TERRENO or not _dentro(traco, quadro):
            continue
        for parte in traco["partes"]:
            if len(parte) >= 2 and np.ptp(parte[:, 0]) > largura:
                melhor, largura = parte, float(np.ptp(parte[:, 0]))
    minimo = LARGURA_MINIMA_TERRENO_REL * (quadro["x1_pt"] - quadro["x0_pt"])
    return melhor if melhor is not None and largura >= minimo else None


def cor_do_contorno(tracos: list[dict], lista_quadros: list[dict]) -> tuple | None:
    """Cor de maior comprimento total entre os segmentos candidatos a contorno em todos os quadros da prancha."""
    comprimento = collections.Counter()
    for traco in tracos:
        for parte in _segmentos_candidatos(traco, lista_quadros):
            comprimento[traco["cor"]] += float(np.hypot(*np.ptp(parte, axis=0)))
    return comprimento.most_common(1)[0][0] if comprimento else None


def _segmentos_candidatos(traco: dict, lista_quadros: list[dict]) -> list[np.ndarray]:
    """Partes do traço que podem ser contorno: layer da escavação, aberto, sem preenchimento, poucos pontos."""
    if (
        traco["layer"] != LAYER_ESCAVACAO
        or traco["fechado"]
        or traco["preenchimento"] is not None
    ):
        return []
    if not any(_dentro(traco, quadro) for quadro in lista_quadros):
        return []
    return [
        parte for parte in traco["partes"] if 2 <= len(parte) <= MAX_PONTOS_SEGMENTO
    ]


def _contorno(
    tracos: list[dict], quadro: dict, cor: tuple | None
) -> tuple[list[np.ndarray], int]:
    """Segmentos (pt) do contorno no quadro e quantidade de traços descartados por serem de outra cor/forma."""
    segmentos, descartados = [], 0
    for traco in tracos:
        if traco["layer"] != LAYER_ESCAVACAO or not _dentro(traco, quadro):
            continue
        candidatos = _segmentos_candidatos(traco, [quadro])
        if candidatos and traco["cor"] == cor:
            segmentos += candidatos
        else:
            descartados += 1
    return segmentos, descartados


def _envelope_inferior(segmentos_m: list[np.ndarray], x_m: np.ndarray) -> np.ndarray:
    """Menor cota entre os segmentos (polilinhas em metros) que cobrem cada x; NaN onde nenhum cobre."""
    pares = [np.column_stack([p[:-1], p[1:]]) for p in segmentos_m]
    trechos = np.vstack(pares)  # (n, 4): xa, za, xb, zb
    xa, za, xb, zb = (trechos[:, i][None, :] for i in range(4))
    xmin, xmax = np.minimum(xa, xb), np.maximum(xa, xb)
    x = x_m[:, None]
    cobre = (x >= xmin - 1e-9) & (x <= xmax + 1e-9) & (xmax - xmin > 1e-9)
    t = np.where(cobre, (x - xa) / np.where(xb - xa == 0, 1.0, xb - xa), 0.0)
    z = np.where(cobre, za + t * (zb - za), np.inf)
    minimo = z.min(axis=1)
    return np.where(np.isfinite(minimo), minimo, np.nan)


def _faixas_cobertas(segmentos_m: list[np.ndarray]) -> np.ndarray:
    """Faixas [x_min, x_max] (m) cobertas pelo contorno; vãos de até LACUNA_MAXIMA_M entre traços são fechados."""
    xs = np.vstack(
        [
            np.column_stack(
                [np.minimum(p[:-1, 0], p[1:, 0]), np.maximum(p[:-1, 0], p[1:, 0])]
            )
            for p in segmentos_m
        ]
    )
    xs = xs[np.argsort(xs[:, 0], kind="stable")]
    fim_acumulado = np.maximum.accumulate(xs[:, 1])
    novo_grupo = np.concatenate(
        [[True], xs[1:, 0] - fim_acumulado[:-1] > LACUNA_MAXIMA_M]
    )
    grupo = np.cumsum(novo_grupo) - 1
    inicio = np.array([xs[grupo == g, 0].min() for g in range(grupo[-1] + 1)])
    fim = np.array([fim_acumulado[grupo == g].max() for g in range(grupo[-1] + 1)])
    return np.column_stack([inicio, fim])


def _em_faixas(x_m: np.ndarray, faixas: np.ndarray) -> np.ndarray:
    """True onde x está dentro de alguma faixa (extremos incluídos, com folga numérica)."""
    return np.any(
        (x_m[:, None] >= faixas[None, :, 0] - 1e-9)
        & (x_m[:, None] <= faixas[None, :, 1] + 1e-9),
        axis=1,
    )


def area_de_corte(
    x_m: np.ndarray,
    z_terreno_m: np.ndarray,
    z_fundo_m: np.ndarray,
    trecho_valido: np.ndarray | None = None,
) -> tuple[float, float]:
    """(área m², largura m) onde o terreno está acima do fundo. Polilinhas lineares por trecho: integral exata
    (trapézio; no trecho com cruzamento, só o triângulo acima). Trechos com NaN numa ponta, ou fora de
    `trecho_valido` (ex.: dentro de um vão sem contorno), não contam."""
    d = z_terreno_m - z_fundo_m
    d0, d1, largura_trecho = d[:-1], d[1:], np.diff(x_m)
    valido = ~(np.isnan(d0) | np.isnan(d1)) & (largura_trecho > 0)
    if trecho_valido is not None:
        valido &= trecho_valido
    d0, d1, w = (
        np.where(valido, d0, 0.0),
        np.where(valido, d1, 0.0),
        np.where(valido, largura_trecho, 0.0),
    )
    ambos_positivos = (d0 >= 0) & (d1 >= 0)
    cruza = d0 * d1 < 0
    soma_abs = np.where(cruza, np.abs(d0) + np.abs(d1), 1.0)
    positivo = np.maximum(d0, d1)
    area = np.where(
        ambos_positivos,
        (d0 + d1) / 2 * w,
        np.where(cruza, positivo**2 / (2 * soma_abs) * w, 0.0),
    )
    largura = np.where(
        ambos_positivos & ((d0 > 0) | (d1 > 0)),
        w,
        np.where(cruza, positivo / soma_abs * w, 0.0),
    )
    return float(area.sum()), float(largura.sum())


def _medir(terreno_m: np.ndarray, contorno_m: list[np.ndarray]) -> dict:
    """Área, largura, cota mínima do fundo e vãos, com o terreno e o contorno já em metros."""
    ordem = np.argsort(terreno_m[:, 0], kind="stable")
    xt, zt = terreno_m[ordem, 0], terreno_m[ordem, 1]
    xs = np.unique(np.concatenate([xt, *[p[:, 0] for p in contorno_m]]))
    faixas = _faixas_cobertas(contorno_m)
    z_bruto = _envelope_inferior(contorno_m, xs)
    valido = ~np.isnan(z_bruto)
    z_fundo = np.where(
        _em_faixas(xs, faixas), np.interp(xs, xs[valido], z_bruto[valido]), np.nan
    )
    z_terreno = np.where((xs >= xt[0]) & (xs <= xt[-1]), np.interp(xs, xt, zt), np.nan)
    trecho_coberto = _em_faixas((xs[:-1] + xs[1:]) / 2, faixas)
    area_m2, largura_m = area_de_corte(xs, z_terreno, z_fundo, trecho_coberto)
    return {
        "area_corte_m2": area_m2,
        "largura_corte_m": largura_m,
        "lacunas": len(faixas) - 1,
        "cota_fundo_min_m": float(np.nanmin(z_bruto)),
        "escavacao": np.column_stack([xs, z_fundo])[~np.isnan(z_fundo)],
    }


def _ler_titulo(pagina, quadro: dict) -> str | None:
    """OCR do título "SEÇÃO XX" (recorte do retângulo do título, canto superior esquerdo do quadro).

    O nome é de duas letras iguais (AA, BB, ... convenção do projeto); o OCR confunde 0/O e 1/I, trocados só
    aqui. Leitura fora desse padrão -> None (a seção fica com nome "Q#" e um alerta).
    """
    if pagina is None:
        return None
    try:
        import pytesseract

        caixa = (
            quadro["x0_pt"] + 22,
            quadro["y0_pt"] + 19,
            quadro["x0_pt"] + 130,
            quadro["y0_pt"] + 46,
        )
        texto = pytesseract.image_to_string(
            _imagem_ocr(pagina, caixa), lang="por", config="--psm 7"
        )
    except Exception:  # noqa: BLE001 - sem tesseract: seção sem nome lido
        return None
    achado = re.search(r"SE\S{1,2}O\s*([A-Z01]{2})", texto.upper())
    nome = achado.group(1).translate(str.maketrans("01", "OI")) if achado else None
    return nome if nome and nome[0] == nome[1] else None


def _alertas_da_medida(medidas: dict, terreno_m: np.ndarray) -> list[str]:
    """Alertas sobre o resultado: vãos no contorno, contorno que não corta o terreno, escavação aberta na borda."""
    alertas = []
    if medidas["lacunas"]:
        alertas.append(
            f"contorno com {medidas['lacunas']} vão(s) maior(es) que {LACUNA_MAXIMA_M} m: área parcial"
        )
    if medidas["area_corte_m2"] < AREA_MINIMA_M2:
        alertas.append(
            "o contorno de ESCAVAÇÃO não fica abaixo do terreno: sem corte nesta seção"
        )
    esc_x = medidas["escavacao"][:, 0]
    if (
        esc_x.max() >= terreno_m[:, 0].max() - TOLERANCIA_BORDA_M
        or esc_x.min() <= terreno_m[:, 0].min() + TOLERANCIA_BORDA_M
    ):
        alertas.append(
            "a escavação chega à borda do quadro: a área é só a do trecho desenhado"
        )
    return alertas


def _secao(
    quadro: dict,
    tracos: list[dict],
    cor: tuple | None,
    pagina,
    nome_prancha: str,
    cota_inferior_m: float | None,
) -> dict:
    """Resultado de um quadro: calibração, terreno, contorno, área e alertas."""
    cal = calibrar(quadro, tracos, pagina, cota_inferior_m)
    alertas = list(cal["alertas"])
    nome = _ler_titulo(pagina, quadro)
    if nome is None:
        alertas.append("título da seção não lido por OCR")
    saida = {
        "secao": nome or f"Q{quadro['indice'] + 1}",
        "prancha": nome_prancha,
        "quadro_pt": [
            quadro["x0_pt"],
            quadro["y0_pt"],
            quadro["x1_pt"],
            quadro["y1_pt"],
        ],
        "m_por_pt_x": cal["m_por_pt_x"],
        "m_por_pt_y": cal["m_por_pt_y"],
        "residuo_calibracao_m": cal["residuo_calibracao_m"],
        "terreno": [],
        "escavacao": [],
        "area_corte_m2": None,
        "cota_fundo_min_m": None,
        "largura_corte_m": None,
        "alertas": alertas,
    }
    if not cal["ok"]:
        alertas.append("sem calibração confiável: área não calculada")
        return saida
    terreno_pt = _terreno(tracos, quadro)
    if terreno_pt is None:
        alertas.append("sem traço de TERRENO ORIGINAL no quadro: área não calculada")
        return saida
    saida["terreno"] = np.round(_para_metros(terreno_pt, cal), 4).tolist()
    segmentos, descartados = _contorno(tracos, quadro, cor)
    if descartados:
        alertas.append(
            f"{descartados} traço(s) do layer ESCAVAÇÃO descartado(s) (texto, chamada, outra cor)"
        )
    if not segmentos:
        alertas.append("sem contorno de ESCAVAÇÃO no quadro: área não calculada")
        return saida
    medidas = _medir(
        np.array(saida["terreno"]), [_para_metros(s, cal) for s in segmentos]
    )
    alertas += _alertas_da_medida(medidas, np.array(saida["terreno"]))
    saida.update(
        area_corte_m2=round(medidas["area_corte_m2"], 4),
        largura_corte_m=round(medidas["largura_corte_m"], 4),
        cota_fundo_min_m=round(medidas["cota_fundo_min_m"], 4),
        escavacao=np.round(medidas["escavacao"], 4).tolist(),
    )
    return saida


def ler_secoes(
    pdf: str | Path, pagina: int = 0, cota_inferior_m: float | None = None
) -> list[dict]:
    """Seções de corte de uma prancha: ver o docstring do módulo. `cota_inferior_m` dispensa o OCR da cota."""
    import pymupdf

    from .pdf_cad import extrair

    tracos = extrair(pdf, pagina=pagina)
    lista = quadros(tracos)
    cor = cor_do_contorno(tracos, lista)
    with pymupdf.open(pdf) as doc:
        return [
            _secao(q, tracos, cor, doc[pagina], Path(pdf).stem, cota_inferior_m)
            for q in lista
        ]


def _formatar(valor, casas: int = 2) -> str:
    return "-" if valor is None else f"{valor:.{casas}f}"


def tabela(secoes: list[dict]) -> str:
    """Tabela de texto: seção, área m², fundo m, largura m, resíduo m, alertas."""
    linhas = [
        f"{'prancha':<12}{'seção':<7}{'área m²':>10}{'fundo m':>10}{'larg. m':>9}{'resíduo m':>11}  alertas"
    ]
    for s in secoes:
        linhas.append(
            f"{s['prancha'][:11]:<12}{s['secao']:<7}{_formatar(s['area_corte_m2']):>10}"
            f"{_formatar(s['cota_fundo_min_m']):>10}{_formatar(s['largura_corte_m']):>9}"
            f"{_formatar(s['residuo_calibracao_m'], 4):>11}  {'; '.join(s['alertas'])}"
        )
    return "\n".join(linhas)


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        description="Área de corte e cota de fundo por seção, de pranchas de corte em PDF vetorial."
    )
    analisador.add_argument("pdf", nargs="+", help="PDF(s) das pranchas de corte")
    analisador.add_argument("--saida", help="JSON de saída com todas as seções")
    argumentos = analisador.parse_args(argv)
    todas = []
    for caminho in argumentos.pdf:
        todas += ler_secoes(caminho)
    print(tabela(todas))
    if argumentos.saida:
        Path(argumentos.saida).write_text(
            json.dumps(todas, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
