"""Conferência das cavas do modelo (MDS × fundo das marcas) contra as seções de corte do projeto.

    O volume das cavas vem de `escavacao.calcular` (MDS do drone × fundo interpolado das marcas de cota). As pranchas de
    corte (009 e 010) são uma testemunha independente: cada seção traz o terreno original, o contorno da escavação, a
    área de corte e a cota de fundo (`secoes_corte`). Aqui as duas coisas se encontram:

    linhas       = linha de cada seção na planta de escavação (traço-ponto verde do layer `CORTES` + letra, lida por OCR
                   do recorte) em UTM pela afim da prancha. O layer `INDICAÇÃO  SEÇÃO` não é de corte: traz as cotas
                   "TRECHO AA – Comprimento do Trecho" da contenção por estacas.
    modelo       = o corte do modelo amostrado ao longo da linha (passo = resolução da grade): área, fundo, largura, terreno
    seções       = diferença de área, de fundo e de terreno por seção; situação `confere` / `difere` / `não conferível`
    seções médias = onde duas linhas quase paralelas cortam a mesma cava: V = (A1 + A2)/2 · d contra o corte do modelo
                   na faixa entre as linhas
    sequência    = cotas da sequência executiva escritas nas notas da planta (texto vetorial decodificado)

Nada é inventado: o que não dá para conferir vira "não conferível" com o motivo. Python calcula; o HTML só apresenta
(`para_html` formata os números).
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path

import numpy as np
import shapely

from . import escavacao, geo

# --- tolerâncias (cotas e coordenadas: tolerância absoluta, regra do projeto) --------------------------------------
TOL_FUNDO_M = 0.30  # fundo: a marca de cota é lida por OCR (centímetro) e o terreno do MDS tem ±0,3 m de controle vertical
TOL_TERRENO_M = 0.30  # terreno médio MDS × TERRENO ORIGINAL do corte: o controle vertical do MDS é desse porte
TOL_AREA_REL = 0.15  # área: a diferença de talude e o erro de traçado do projeto pesam ~15 % da área de corte
TOL_VOLUME_REL = 0.20  # seções médias: o método das áreas médias já erra alguns % numa cava que não é prismática
AREA_MINIMA_M2 = 1.0  # corte com menos de 1 m² de área no projeto é "sem corte" (a seção só passa pela borda da cava)
FRACAO_MINIMA_NO_MDS = (
    0.8  # a linha precisa ter ≥ 80 % do comprimento dentro da grade válida do MDS
)
FRACAO_MINIMA_LINHA = 0.8  # sem alinhamento do terreno: a linha precisa ter ≥ 80 % da largura do quadro do corte
FOLGA_COBERTURA_M = 1.0  # a linha cobre o corte do projeto com esta folga nas pontas (erro de traçado e de alinhamento)
DISTANCIA_MAXIMA_QUEBRA_M = 3.0  # segmento não colinear só quebra a linha se encostar nela (a ≤ isto); longe é outro desenho
FRACAO_MAXIMA_EDIFICACAO = 0.20  # mais que 20 % das amostras da linha sobre edificação: a linha não mede terreno natural
DESVIO_MAXIMO_TERRENO_M = 0.30  # desvio-padrão (modelo − projeto) do terreno acima disto: MDS irregular na linha
ANGULO_PARALELO_GRAUS = 5.0  # duas linhas de seção são "quase paralelas" abaixo disso
DIVERGENCIA_LINHA_M = (
    0.5  # a mesma seção em duas plantas: as linhas não podem divergir mais que isto
)

# --- leitura das linhas na planta --------------------------------------------------------------------------------
LAYER_CORTES = "CORTES"
VERSAO_LEITURA_LINHAS = 2  # sobe quando muda a leitura das linhas (OCR das letras): invalida o cache em disco
TRACO_MIN_PT, TRACO_MAX_PT, ESPESSURA_MAX_PT = (
    4.0,
    10.0,
    1.0,
)  # um traço do tracejado: quadro fino de ~7 × 0,6 pt
VIZINHO_MAX_PT = 16.0  # entre dois traços do tracejado (passo ~10,6 pt)
ALINHAMENTO_MAX_PT = 1.0  # desvio lateral de um traço em relação ao eixo do vizinho
ANGULO_TRACO_MAX_GRAUS = 3.0
TRACOS_MINIMOS = (
    6  # menos que isso não é linha de seção (a seta e a legenda têm poucos traços)
)
RAIO_LETRA_PT = 45.0  # a letra fica a até isto da ponta da linha
OCR_DPI = 400
MODOS_OCR = (
    10,
    8,
)  # modos de segmentação do tesseract tentados por rotação: um caractere / uma palavra
DOMINIO_VERDE = 70  # verde − max(vermelho, azul) mínimo do pixel da letra (0, 114, 0); a hachura clara fica abaixo
TRACO_FINO_RAZAO = 3.5  # letra mais alta que 3,5 × a largura é a barra do "I"
SEGMENTO_MINIMO_M = 5.0  # segmento de seção não colinear com menos que isto é resto de traço, não outra parte da linha
COLINEAR_GRAUS = 2.0  # segmentos da mesma seção em plantas diferentes: mesma reta se o ângulo for menor que isto
LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
ROTACOES_GRAUS = (
    0,
    90,
    180,
    270,
)  # a letra da seção acompanha a linha: nas linhas E-W em UTM aparece deitada na folha
CONFIANCA_PARECIDA = 5.0  # duas rotações com letras diferentes e pontuação a ≤ isto uma da outra: leitura ambígua
VANTAGEM_ESPERADA = 20.0  # pontos a mais para a leitura na rotação esperada pela geometria (A lido como V ao girar)
SITUACAO_SEQUENCIA = "compatível por valor"  # a nota não diz onde: só o valor da cota é compatível com o fundo da cava
SITUACOES_SECAO = ("confere", "difere", "não conferível")


def _eixo_do_quadro(q: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Eixo maior de um quadro (4 vértices): direção unitária, comprimento e espessura em pt."""
    c = q - q.mean(0)
    _, v = np.linalg.eigh(c.T @ c)
    eixo = v[:, 1]
    p = c @ eixo, c @ v[:, 0]
    return eixo, float(np.ptp(p[0])), float(np.ptp(p[1]))


def tracos_do_tracejado(
    tracos: list[dict],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Traços do tracejado de corte: centros (n, 2), eixos unitários (n, 2) e comprimentos (n,), em pt.

    Cada traço é um quadro preenchido fino (`TRACO_MIN_PT`–`TRACO_MAX_PT` de comprimento, até `ESPESSURA_MAX_PT`) do
    layer `CORTES`; as letras (sem cor de traço) e os lados da seta (curtos ou de outro ângulo) ficam de fora."""
    centros, eixos, comprimentos = [], [], []
    for t in tracos:
        if t["layer"] != LAYER_CORTES or t["preenchimento"] is None or t["cor"] is None:
            continue
        for parte in t["partes"]:
            q = np.asarray(parte, float)
            if len(q) != 4:
                continue
            eixo, comp, esp = _eixo_do_quadro(q)
            if TRACO_MIN_PT <= comp <= TRACO_MAX_PT and esp <= ESPESSURA_MAX_PT:
                centros.append(q.mean(0))
                eixos.append(eixo)
                comprimentos.append(comp)
    return (
        np.array(centros).reshape(-1, 2),
        np.array(eixos).reshape(-1, 2),
        np.array(comprimentos),
    )


def _componentes(vizinho: np.ndarray) -> np.ndarray:
    """Rótulo de componente conexo de uma matriz de adjacência booleana (busca em largura)."""
    n = len(vizinho)
    rotulo = np.full(n, -1)
    k = 0
    for i in range(n):
        if rotulo[i] >= 0:
            continue
        rotulo[i] = k
        fila = [i]
        while fila:
            j = fila.pop()
            novos = np.flatnonzero(vizinho[j] & (rotulo < 0))
            rotulo[novos] = k
            fila.extend(novos.tolist())
        k += 1
    return rotulo


def agrupar_tracejados(centros: np.ndarray, eixos: np.ndarray) -> np.ndarray:
    """Rótulo de linha de cada traço: vizinhos a ≤ `VIZINHO_MAX_PT`, de mesmo ângulo e alinhados pelo centro."""
    if not len(centros):
        return np.zeros(0, int)
    d = centros[None, :, :] - centros[:, None, :]
    dist = np.linalg.norm(d, axis=2)
    cos = np.abs((eixos[:, None, :] * eixos[None, :, :]).sum(2))
    lateral = np.abs(
        d[..., 0] * eixos[:, None, 1] - d[..., 1] * eixos[:, None, 0]
    )  # desvio lateral em relação a i
    vizinho = (
        (dist <= VIZINHO_MAX_PT)
        & (cos >= np.cos(np.radians(ANGULO_TRACO_MAX_GRAUS)))
        & (lateral <= ALINHAMENTO_MAX_PT)
    )
    return _componentes(vizinho)


def _pontas_da_linha(
    centros: np.ndarray, eixos: np.ndarray, comprimentos: np.ndarray
) -> np.ndarray:
    """Duas pontas (pt) de um grupo de traços: os extremos projetados no eixo médio, mais meio traço."""
    eixo = eixos[0] * np.sign(eixos @ eixos[0]).reshape(-1, 1)
    eixo = eixo.mean(0)
    eixo /= np.linalg.norm(eixo)
    s = (centros - centros[0]) @ eixo
    meio = comprimentos / 2
    i0, i1 = int(np.argmin(s - meio)), int(np.argmax(s + meio))
    centro_lateral = centros.mean(0) - ((centros.mean(0) - centros[0]) @ eixo) * eixo
    return np.array(
        [
            centro_lateral + (s[i0] - meio[i0]) * eixo,
            centro_lateral + (s[i1] + meio[i1]) * eixo,
        ]
    )


def letras_do_layer(tracos: list[dict]) -> list[np.ndarray]:
    """Contornos (pt) das letras do layer `CORTES`: quadros preenchidos sem cor de traço (os traços do tracejado e da
    seta têm cor)."""
    return [
        np.asarray(p, float)
        for t in tracos
        if t["layer"] == LAYER_CORTES
        and t["preenchimento"] is not None
        and t["cor"] is None
        for p in t["partes"]
    ]


def _caixa_da_letra(ponta: np.ndarray, letras: list[np.ndarray]) -> tuple | None:
    """Caixa (x0, y0, x1, y1; pt) da letra mais próxima da ponta: o contorno mais perto e os que o tocam."""
    if not letras:
        return None
    centros = np.array([q.mean(0) for q in letras])
    d = np.linalg.norm(centros - ponta, axis=1)
    if d.min() > RAIO_LETRA_PT:
        return None
    base = letras[int(np.argmin(d))]
    perto = [
        q for q, c in zip(letras, centros) if np.linalg.norm(c - base.mean(0)) <= 6.0
    ]
    todos = np.vstack(perto)
    return (*(todos.min(0) - 1.0), *(todos.max(0) + 1.0))


def rotacao_esperada(
    ponta_pt: np.ndarray, centro_letra_pt: np.ndarray, eixo: np.ndarray
) -> int:
    """Rotação (graus anti-horários, múltiplo de 90) que deixa a letra de pé, pela geometria da marca de seção: o
    "alto" da letra aponta da linha para a letra, perpendicular à linha (a letra fica no lado da seta). Coordenadas
    da folha (y para baixo)."""
    v = np.asarray(centro_letra_pt, float) - np.asarray(ponta_pt, float)
    normal = np.array([-eixo[1], eixo[0]])
    alto = (v @ normal) * normal
    angulo = np.degrees(
        np.arctan2(-alto[1], alto[0])
    )  # y da folha desce: inverte para o plano usual
    return round((90.0 - angulo) / 90.0) % 4 * 90


def escolher_letra(
    leituras: list[tuple[str, float, int]], esperada: int = 0
) -> tuple[str | None, str | None, bool]:
    """(letra, alerta, na_esperada): a letra de maior pontuação entre as leituras por rotação [(letra, confiança,
    graus)], o alerta, se houver, e se a letra escolhida foi lida na rotação esperada.

    Só vale letra A–Z. A leitura na rotação `esperada` pela geometria ganha `VANTAGEM_ESPERADA` pontos: o OCR lê a
    letra girada como outra (A como V, C como O). Se outra rotação deu letra diferente a ≤ `CONFIANCA_PARECIDA` pontos
    da melhor, a leitura é ambígua: sem letra e com alerta."""
    validas = [
        (c + (VANTAGEM_ESPERADA if graus == esperada else 0.0), t)
        for t, c, graus in leituras
        if len(t) == 1 and t in LETRAS
    ]
    if not validas:
        return None, None, False
    melhor_pontos, melhor = max(validas)
    rivais = {
        t
        for pontos, t in validas
        if t != melhor and melhor_pontos - pontos <= CONFIANCA_PARECIDA
    }
    if rivais:
        return None, f"letra ambígua entre rotações: {sorted({melhor, *rivais})}", False
    return melhor, None, any(t == melhor and g == esperada for t, _, g in leituras)


def _leituras_por_rotacao(img: np.ndarray) -> list[tuple[str, float, int]]:
    """OCR da letra (imagem 0/255, letra preta) em cada rotação de `ROTACOES_GRAUS`: [(letra, confiança, graus)].
    Em cada rotação vale o melhor dos modos de segmentação `MODOS_OCR` (o modo 10 às vezes não lê um P que o 8 lê)."""
    import pytesseract
    from PIL import Image

    leituras = []
    for graus in ROTACOES_GRAUS:
        giro = Image.fromarray(np.ascontiguousarray(np.rot90(img, graus // 90)))
        melhor = None
        for modo in MODOS_OCR:
            d = pytesseract.image_to_data(
                giro,
                config=f"--psm {modo} -c tessedit_char_whitelist={LETRAS}",
                output_type=pytesseract.Output.DICT,
            )
            for texto, conf in zip(d["text"], d["conf"]):
                achados = re.findall(r"[A-Z]", str(texto).upper())
                if (
                    achados
                    and float(conf) >= 0
                    and (melhor is None or float(conf) > melhor[1])
                ):
                    melhor = (achados[0], float(conf), graus)
        if melhor:
            leituras.append(melhor)
    return leituras


def ler_letra(
    pagina, caixa_pt: tuple, esperada: int = 0
) -> tuple[str | None, str | None, bool]:
    """OCR de uma letra (recorte de `caixa_pt`) nas quatro rotações: (letra, alerta, lida na rotação esperada).

    A letra acompanha a linha da seção e nas linhas E-W em UTM aparece deitada: vale a rotação de maior confiança
    (`escolher_letra`). Barra fina, em pé ou deitada, é o "I" (o OCR não lê um I isolado)."""
    import pymupdf

    px = pagina.get_pixmap(dpi=OCR_DPI, clip=pymupdf.Rect(*caixa_pt))
    rgb = (
        np.frombuffer(px.samples, np.uint8)
        .reshape(px.h, px.w, px.n)[..., :3]
        .astype(int)
    )
    verde = (
        (rgb[..., 1] - np.maximum(rgb[..., 0], rgb[..., 2]) > DOMINIO_VERDE)
        & (rgb[..., [0, 2]].max(2) < 110)
    )  # só o verde escuro da letra: sem a hachura clara nem as linhas pretas de outros layers atrás dela
    linhas, colunas = np.nonzero(verde)
    if linhas.size:
        alto, largo = np.ptp(linhas) + 1, np.ptp(colunas) + 1
        if max(alto, largo) > TRACO_FINO_RAZAO * min(alto, largo):
            return "I", None, True
    img = np.pad(np.where(verde, 0, 255).astype(np.uint8), 25, constant_values=255)
    return escolher_letra(_leituras_por_rotacao(img), esperada)


def _conciliar_pontas(lidas: list[tuple]) -> list[tuple[str | None, str | None]]:
    """(letra, alerta) das duas pontas. As duas pontas trazem a mesma letra: se discordam e só uma foi lida na rotação
    esperada pela geometria, vale essa e a outra (leitura de fundo sujo) é descartada com alerta."""
    letras = {t for t, _, _ in lidas if t}
    fortes = [i for i, (t, _, na_esperada) in enumerate(lidas) if t and na_esperada]
    if len(letras) > 1 and len(fortes) == 1:
        return [
            (t, a)
            if i == fortes[0]
            else (None, f"ponta com a letra {t}, fora da rotação esperada, descartada")
            for i, (t, a, _) in enumerate(lidas)
        ]
    return [(t, a) for t, a, _ in lidas]


def _ler_pontas(pagina, pontas: np.ndarray, caixas: list) -> list[tuple]:
    """Letra (e alerta) de cada ponta da linha, lida na rotação esperada pela geometria da marca."""
    eixo = (pontas[1] - pontas[0]) / np.linalg.norm(pontas[1] - pontas[0])
    lidas = []
    for ponta, cx in zip(pontas, caixas):
        if cx is None:
            lidas.append((None, None, False))
            continue
        centro = np.array([(cx[0] + cx[2]) / 2, (cx[1] + cx[3]) / 2])
        lidas.append(ler_letra(pagina, cx, rotacao_esperada(ponta, centro, eixo)))
    return _conciliar_pontas(lidas)


def linhas_da_planta(
    pdf: str | Path, M: np.ndarray, clip=None, prancha: str = ""
) -> list[dict]:
    """Linhas de seção de uma planta: [{secao, prancha, inicio_utm, fim_utm, comprimento_m, alertas}].

    O rótulo é a letra das duas pontas (OCR do recorte), dobrada ("A" -> "AA", o nome do corte); se as pontas
    discordam ou o OCR falha, a linha sai com `secao` None e um alerta."""
    import pymupdf

    from .pdf_cad import extrair

    tracos = extrair(pdf, clip=clip)
    centros, eixos, comprimentos = tracos_do_tracejado(tracos)
    rotulo = agrupar_tracejados(centros, eixos)
    letras = letras_do_layer(tracos)
    saida = []
    with pymupdf.open(pdf) as doc:
        pagina = doc[0]
        for k in np.unique(rotulo):
            sel = rotulo == k
            if sel.sum() < TRACOS_MINIMOS:
                continue
            pontas = _pontas_da_linha(centros[sel], eixos[sel], comprimentos[sel])
            caixas = [_caixa_da_letra(p, letras) for p in pontas]
            if not any(caixas):
                continue  # tracejado sem letra perto das pontas (eixo, quadra): não é seção
            lidas = _ler_pontas(pagina, pontas, caixas)
            saida.append(
                _linha(
                    pontas,
                    [t for t, _ in lidas],
                    M,
                    prancha,
                    [a for _, a in lidas if a],
                )
            )
    return saida


def _linha(
    pontas_pt: np.ndarray,
    lidas: list,
    M: np.ndarray,
    prancha: str,
    alertas_ocr: list[str] | None = None,
) -> dict:
    """Linha em UTM com o nome da seção a partir das letras lidas nas duas pontas (`alertas_ocr`: ambiguidades)."""
    utm = geo.aplicar(np.asarray(M), pontas_pt)
    distintas = {v for v in lidas if v}
    alertas = list(alertas_ocr or [])
    if len(distintas) == 1:
        secao = distintas.pop() * 2
        if None in lidas:
            alertas.append("letra lida só numa das pontas")
    else:
        secao = None
        alertas.append(
            "letra não lida"
            if not distintas
            else f"letras discordam nas pontas: {sorted(distintas)}"
        )
    return {
        "secao": secao,
        "prancha": prancha,
        "inicio_utm": utm[0].round(3).tolist(),
        "fim_utm": utm[1].round(3).tolist(),
        "comprimento_m": round(float(np.linalg.norm(utm[1] - utm[0])), 3),
        "alertas": alertas,
    }


# --- seção do modelo -----------------------------------------------------------------------------------------------
def _amostrar_linha(linha: dict, g: dict) -> tuple:
    """Pontos da linha a cada `res` (no centro de cada passo): s (m), xy (UTM), passo, linha e coluna da grade e se
    caem na grade."""
    ini, fim = (
        np.asarray(linha["inicio_utm"], float),
        np.asarray(linha["fim_utm"], float),
    )
    comprimento = float(np.linalg.norm(fim - ini))
    n = max(round(comprimento / g["res"]), 1)
    passo = comprimento / n
    s = (np.arange(n) + 0.5) * passo
    xy = ini + (fim - ini) * (s / max(comprimento, 1e-9))[:, None]
    lin = np.floor((g["n1"] - xy[:, 1]) / g["res"]).astype(int)
    col = np.floor((xy[:, 0] - g["e0"]) / g["res"]).astype(int)
    dentro = (lin >= 0) & (lin < g["forma"][0]) & (col >= 0) & (col < g["forma"][1])
    return (
        s,
        xy,
        passo,
        np.clip(lin, 0, g["forma"][0] - 1),
        np.clip(col, 0, g["forma"][1] - 1),
        dentro,
    )


ORIGENS_DA_TOPOGRAFIA = (
    1,
    3,
)  # `topografia.ORIGENS_TERRENO`: topografia e costura (mistura com a topografia)


def _fracao_da_topografia(g: dict, lin, col, valido: np.ndarray) -> float | None:
    """Parte das amostras válidas da linha cujo terreno do modelo é (ou mistura) a topografia do projeto. None quando o
    terreno é o MDS puro (`g` sem `origem_terreno`). Perto de 1, comparar o terreno do modelo com o TERRENO ORIGINAL
    da seção é quase circular: as duas coisas vêm do mesmo projeto."""
    origem = g.get("origem_terreno")
    if origem is None:
        return None
    return (
        float(np.isin(origem[lin, col], ORIGENS_DA_TOPOGRAFIA)[valido].mean())
        if valido.any()
        else 0.0
    )


def perfil_do_modelo(linha: dict, g: dict, corte: np.ndarray) -> dict:
    """Seção do modelo ao longo da linha: área de corte (∫ corte ds), fundo mínimo (terreno − corte onde há corte),
    largura do corte e terreno [[s_m, z_m]]; `fracao_no_mds` é a parte da linha dentro da grade válida,
    `fracao_edificacao` a parte das amostras sobre edificação existente e `corte_na_ponta` diz se o corte vai até uma
    das pontas (a cava continua além da linha)."""
    s, _, passo, lin, col, dentro = _amostrar_linha(linha, g)
    valido = (
        dentro & g["valido"][lin, col] & np.isfinite(g["terreno"][lin, col])
    )  # NaN = sem terreno
    c = np.where(valido, corte[lin, col], 0.0).astype(float)
    z = np.where(valido, g["terreno"][lin, col], np.nan).astype(float)
    edificacao = g.get("edificacao", np.zeros(g["forma"], bool))
    com_corte = c > 0.01
    fundo = float(np.min(z[com_corte] - c[com_corte])) if com_corte.any() else None
    return {
        "area_corte_m2": float(c.sum() * passo),
        "cota_fundo_min_m": fundo,
        "largura_corte_m": float(com_corte.sum() * passo),
        "terreno": np.c_[s, z][valido].round(3).tolist(),
        "fracao_no_mds": float(valido.mean()),
        "fracao_edificacao": float((valido & edificacao[lin, col]).mean()),
        "fracao_terreno_topografia": _fracao_da_topografia(g, lin, col, valido),
        "amostras_edificacao": (valido & edificacao[lin, col]).tolist(),
        "corte_na_ponta": bool(com_corte[0] or com_corte[-1]),
        "passo_m": float(passo),
    }


def comparar_terreno(
    terreno_projeto: list,
    terreno_modelo: list,
    passo_m: float,
    corte_x_m: tuple[float, float] | None = None,
) -> dict | None:
    """Terreno do MDS contra o TERRENO ORIGINAL do corte. A largura do quadro e o comprimento da linha podem diferir e
    o sentido da seta não é lido: o perfil mais curto desliza sobre o mais longo, nos dois sentidos, e vale o ajuste de
    menor desvio-padrão da diferença. Devolve a diferença média (modelo − projeto), o desvio, o sentido e o deslocamento.

    Com `corte_x_m` (intervalo x do corte do projeto, nas coordenadas do terreno do projeto), a diferença média e o
    desvio valem só nesse trecho alinhado (os da linha inteira ficam em `*_total_m`) e `trecho_s_m` traz o trecho na
    coordenada s da linha do modelo (pode passar das pontas da linha)."""
    p, m = (
        np.asarray(terreno_projeto, float).reshape(-1, 2),
        np.asarray(terreno_modelo, float).reshape(-1, 2),
    )
    if len(p) < 2 or len(m) < 2:
        return None
    larg_p, larg_m = float(p[-1, 0] - p[0, 0]), float(m[-1, 0] - m[0, 0])
    modelo_e_o_longo = larg_m >= larg_p
    curto, longo = (p, m) if modelo_e_o_longo else (m, p)
    folga = abs(larg_m - larg_p)
    xs = np.arange(0.0, float(curto[-1, 0] - curto[0, 0]) + 1e-9, passo_m)
    zc = np.interp(xs, curto[:, 0] - curto[0, 0], curto[:, 1])
    extensao = float(longo[-1, 0] - longo[0, 0])
    melhor = None
    for sentido in (1, -1):
        for desloc in np.arange(0.0, folga + 1e-9, passo_m):
            pos = desloc + xs if sentido == 1 else extensao - desloc - xs
            zl = np.interp(pos + longo[0, 0], longo[:, 0], longo[:, 1])
            dif = (zl - zc) if modelo_e_o_longo else (zc - zl)  # modelo − projeto
            if melhor is None or dif.std() < melhor["desvio_m"]:
                melhor = {
                    "dif_media_m": float(dif.mean()),
                    "desvio_m": float(dif.std()),
                    "sentido": sentido,
                    "deslocamento_m": float(desloc),
                    # s da linha do modelo = a + b · (x do projeto − início do terreno do projeto)
                    "_a": float(
                        m[0, 0] + extensao - desloc
                        if sentido == -1
                        else m[0, 0] + (desloc if modelo_e_o_longo else -desloc)
                    ),
                    "_b": float(sentido),
                }
    a, b = melhor.pop("_a"), melhor.pop("_b")
    resultado = {**melhor, "largura_projeto_m": larg_p, "comprimento_linha_m": larg_m}
    if corte_x_m is not None:
        resultado.update(_trecho_do_corte(p, m, passo_m, corte_x_m, a, b, resultado))
    return resultado


def _trecho_do_corte(
    p, m, passo_m: float, corte_x_m: tuple, a: float, b: float, total: dict
) -> dict:
    """Diferença média e desvio do terreno só no trecho do corte do projeto, e o trecho na coordenada s da linha."""
    x0, x1 = corte_x_m[0] - p[0, 0], corte_x_m[1] - p[0, 0]
    trecho_s = sorted((a + b * x0, a + b * x1))
    xr = np.arange(max(x0, 0.0), min(x1, p[-1, 0] - p[0, 0]) + 1e-9, passo_m)
    s = a + b * xr
    dentro = (s >= m[0, 0]) & (s <= m[-1, 0])
    saida = {
        "trecho_s_m": trecho_s,
        "dif_media_total_m": total["dif_media_m"],
        "desvio_total_m": total["desvio_m"],
    }
    if dentro.sum() >= 2:
        dif = np.interp(s[dentro], m[:, 0], m[:, 1]) - np.interp(
            xr[dentro] + p[0, 0], p[:, 0], p[:, 1]
        )
        saida.update(dif_media_m=float(dif.mean()), desvio_m=float(dif.std()))
    return saida


def talude_do_projeto(escavacao_xz: list) -> float | None:
    """Talude H:V das paredes do contorno de escavação do corte: o recuo horizontal da parede dividido pela queda, a
    mediana das duas paredes; 0 é parede vertical (contenção por estacas). None sem contorno."""
    e = np.asarray(escavacao_xz, float).reshape(-1, 2)
    if len(e) < 3:
        return None
    no_fundo = np.flatnonzero(e[:, 1] <= e[:, 1].min() + 0.05)
    esq, dire = e[: no_fundo[0] + 1], e[no_fundo[-1] :][::-1]
    valores = [
        abs(w[-1, 0] - w[0, 0]) / (w[0, 1] - w[-1, 1])
        for w in (esq, dire)
        if w[0, 1] - w[-1, 1] > 0.3
    ]
    return round(float(np.median(valores)), 2) if valores else None


# --- conferência por seção -----------------------------------------------------------------------------------------
def marca_proxima_da_linha(linha: dict, marcas: list[dict]) -> dict | None:
    """Marca de cota (com valor, sem 'TOPO') mais próxima da linha: {cota_m, distancia_m}; só registro, não entra no
    cálculo do fundo. None sem marca."""
    uteis = [m for m in marcas if m.get("cota") is not None and not m.get("topo")]
    if not uteis:
        return None
    reta = shapely.LineString([linha["inicio_utm"], linha["fim_utm"]])
    d = shapely.distance(
        reta, shapely.points(np.array([m["utm"] for m in uteis], float))
    )
    k = int(np.argmin(d))
    return {"cota_m": float(uteis[k]["cota"]), "distancia_m": float(d[k])}


def corte_x_do_projeto(sec: dict) -> tuple[float, float] | None:
    """Intervalo x (m) onde o projeto tem corte: a extensão do contorno de escavação da seção; None sem contorno."""
    e = np.asarray(sec.get("escavacao", []), float).reshape(-1, 2)
    return (float(e[:, 0].min()), float(e[:, 0].max())) if len(e) >= 2 else None


def _edificacao_no_trecho(mod: dict, terr: dict | None) -> float:
    """Fração das amostras sobre edificação no trecho alinhado ao corte do projeto (a linha inteira sem trecho)."""
    amostras = np.asarray(mod.get("amostras_edificacao", []), bool)
    if not terr or "trecho_s_m" not in terr or not amostras.size:
        return float(mod.get("fracao_edificacao", 0.0))
    s = (np.arange(amostras.size) + 0.5) * mod["passo_m"]
    no_trecho = (s >= terr["trecho_s_m"][0]) & (s <= terr["trecho_s_m"][1])
    return float(amostras[no_trecho].mean()) if no_trecho.any() else 0.0


def _motivo_terreno(mod: dict, terr: dict | None) -> str | None:
    """Motivo de a linha não medir terreno natural no trecho do corte: edificação existente ou MDS irregular."""
    fracao = _edificacao_no_trecho(mod, terr)
    if fracao > FRACAO_MAXIMA_EDIFICACAO:
        return f"edificação existente na linha ({_txt(100 * fracao, 0)} % das amostras do corte)"
    if terr and terr["desvio_m"] > DESVIO_MAXIMO_TERRENO_M:
        return (
            f"terreno do MDS irregular na linha (desvio {_txt(terr['desvio_m'])} m, "
            f"diferença média {_txt(terr['dif_media_m'], 2, True)} m)"
        )
    return None


def _motivo_nao_conferivel(
    sec: dict, mod: dict | None, terr: dict | None = None
) -> str | None:
    """Motivo de a seção não ser conferível (ou None): sem linha, sem corte, área parcial, fora do MDS, linha incompleta,
    edificação ou terreno irregular na linha, cava continua."""
    if mod is None:
        return "sem linha de seção na planta de escavação"
    if mod.get("quebrada"):
        return "linha de seção quebrada na planta (segmentos não colineares): um perfil reto não a representa"
    if sec["area_corte_m2"] < AREA_MINIMA_M2:
        return f"sem corte no projeto (área < {AREA_MINIMA_M2:g} m²)"
    parcial = [
        a
        for a in sec.get("alertas", [])
        if "área parcial" in a or "borda do quadro" in a
    ]
    if parcial:
        return "área parcial no projeto (" + parcial[0] + ")"
    if mod["fracao_no_mds"] < FRACAO_MINIMA_NO_MDS:
        return f"linha fora do MDS ({mod['fracao_no_mds']:.0%} dentro da grade válida)"
    return _motivo_da_linha(sec, mod, terr)


def _linha_incompleta(sec: dict, mod: dict, terr: dict | None) -> str | None:
    """Motivo de a linha não cobrir o corte do projeto (ou None). Com o terreno alinhado: o intervalo do corte, na
    coordenada da linha, tem de caber nela com `FOLGA_COBERTURA_M` nas pontas; sem alinhamento, vale ≥
    `FRACAO_MINIMA_LINHA` da largura do quadro."""
    comprimento_m = mod.get("comprimento_linha_m")
    if comprimento_m is None:
        return None
    if terr and "trecho_s_m" in terr:
        ini, fim = terr["trecho_s_m"]
        if ini >= -FOLGA_COBERTURA_M and fim <= comprimento_m + FOLGA_COBERTURA_M:
            return None
        coberto = max(min(fim, comprimento_m) - max(ini, 0.0), 0.0)
        return f"linha incompleta na planta (cobre {_txt(coberto, 1)} m de {_txt(fim - ini, 1)} m do corte)"
    largura_m = (
        sec["terreno"][-1][0] - sec["terreno"][0][0]
    )  # eixo x do quadro do corte
    if comprimento_m < FRACAO_MINIMA_LINHA * largura_m:
        return f"linha incompleta na planta ({_txt(comprimento_m, 1)} m de {_txt(largura_m, 1)} m)"
    return None


def _motivo_da_linha(sec: dict, mod: dict, terr: dict | None) -> str | None:
    """Motivos ligados à linha amostrada (juntos, com "; "): linha incompleta, edificação ou terreno irregular, cava
    até a ponta. Com a linha incompleta o corte "ir até a ponta" não é motivo (a cava continua além da linha porque
    a linha é curta)."""
    incompleta = _linha_incompleta(sec, mod, terr)
    motivos = [incompleta] if incompleta else []
    motivo_terreno = _motivo_terreno(mod, terr)
    if motivo_terreno:
        motivos.append(motivo_terreno)
    if mod["corte_na_ponta"] and not incompleta:
        motivos.append(
            "o corte do modelo vai até a ponta da linha (a cava continua além dela)"
        )
    return "; ".join(motivos) or None


def _area_corrigida(sec: dict, mod: dict, terr: dict | None) -> dict:
    """Área do modelo corrigida pelo terreno: A − (terreno modelo − projeto) × largura do corte do modelo. Informação para
    o humano separar o efeito do terreno; não muda a situação."""
    if terr is None:
        return {}
    corrigida = mod["area_corte_m2"] - terr["dif_media_m"] * mod["largura_corte_m"]
    return {
        "area_modelo_corrigida_terreno_m2": corrigida,
        "dif_area_corrigida_rel": (corrigida - sec["area_corte_m2"])
        / max(sec["area_corte_m2"], 1e-9),
    }


def _falhas(
    sec: dict, mod: dict, terr: dict | None, dif_area: float, tol_area: float
) -> list[str]:
    """Falhas de tolerância (área, fundo, terreno) de uma seção conferível."""
    falhas = []
    if abs(dif_area) > tol_area:
        falhas.append(
            f"área {_txt(dif_area, 1, True)} m² (tolerância ±{_txt(tol_area, 1)})"
        )
    if mod["cota_fundo_min_m"] is None:
        falhas.append("o modelo não tem cava na linha")
        return falhas
    dif_fundo = mod["cota_fundo_min_m"] - sec["cota_fundo_min_m"]
    if abs(dif_fundo) > TOL_FUNDO_M:
        texto = f"fundo {_txt(dif_fundo, 2, True)} m (tolerância ±{_txt(TOL_FUNDO_M)})"
        marca = mod.get("marca_proxima")
        if marca:
            texto += (
                f"; marca de cota mais próxima da linha: {_txt(marca['cota_m'])} m "
                f"a {_txt(marca['distancia_m'], 1)} m"
            )
        falhas.append(texto)
    if terr and abs(terr["dif_media_m"]) > TOL_TERRENO_M:
        falhas.append(
            f"terreno {_txt(terr['dif_media_m'], 2, True)} m (tolerância ±{_txt(TOL_TERRENO_M)})"
        )
    return falhas


def conferir_secao(sec: dict, mod: dict | None) -> dict:
    """Uma linha da conferência: números do projeto e do modelo, diferenças e situação."""
    linha = {
        "secao": sec["secao"],
        "prancha": sec["prancha"][:3],
        "area_projeto_m2": sec["area_corte_m2"],
        "fundo_projeto_m": sec["cota_fundo_min_m"],
        "largura_projeto_m": sec["largura_corte_m"],
        "talude_projeto_h_v": talude_do_projeto(sec["escavacao"]),
        "alertas_projeto": sec.get("alertas", []),
    }
    terr = None
    if mod is not None:
        terr = comparar_terreno(
            sec["terreno"], mod["terreno"], mod["passo_m"], corte_x_do_projeto(sec)
        )
        linha.update(
            area_modelo_m2=mod["area_corte_m2"],
            fundo_modelo_m=mod["cota_fundo_min_m"],
            largura_modelo_m=mod["largura_corte_m"],
            fracao_terreno_topografia=mod.get("fracao_terreno_topografia"),
            linha_prancha=mod.get("linha_prancha"),
            comprimento_linha_m=mod.get("comprimento_linha_m"),
            dif_terreno_m=terr and terr["dif_media_m"],
            **_area_corrigida(sec, mod, terr),
        )
    motivo = _motivo_nao_conferivel(sec, mod, terr)
    if motivo:
        return {**linha, "situacao": "não conferível", "motivo": motivo}
    dif_area = mod["area_corte_m2"] - sec["area_corte_m2"]
    tol_area = max(
        TOL_AREA_REL * sec["area_corte_m2"], TOL_TERRENO_M * sec["largura_corte_m"]
    )
    falhas = _falhas(sec, mod, terr, dif_area, tol_area)
    return {
        **linha,
        "dif_area_m2": dif_area,
        "dif_area_rel": dif_area / sec["area_corte_m2"],
        "tol_area_m2": tol_area,
        "dif_fundo_m": None
        if mod["cota_fundo_min_m"] is None
        else mod["cota_fundo_min_m"] - sec["cota_fundo_min_m"],
        "terreno": terr,
        "situacao": "difere" if falhas else "confere",
        "motivo": "; ".join(falhas),
    }


def conferir_secoes(projeto: list[dict], modelo: dict[str, dict]) -> list[dict]:
    """Conferência por seção: `projeto` = saída de `secoes_corte.ler_secoes`; `modelo` = {seção: perfil do modelo} só das
    seções com linha na planta."""
    return [conferir_secao(s, modelo.get(s["secao"])) for s in projeto]


# --- linhas das várias plantas -------------------------------------------------------------------------------------
def _colineares(a: dict, b: dict) -> bool:
    """Dois segmentos na mesma reta: ângulo < `COLINEAR_GRAUS` e as pontas de b a ≤ `DIVERGENCIA_LINHA_M` da reta de a."""
    pa, ua, _ = _direcao(a)
    pb = np.array([b["inicio_utm"], b["fim_utm"]], float)
    ub = (pb[1] - pb[0]) / np.linalg.norm(pb[1] - pb[0])
    angulo = np.degrees(np.arccos(min(abs(ua @ ub), 1.0)))
    lateral = np.abs((pb - pa) @ np.array([-ua[1], ua[0]]))
    return bool(angulo < COLINEAR_GRAUS and lateral.max() <= DIVERGENCIA_LINHA_M)


def _fundir(a: dict, b: dict) -> dict:
    """União de dois segmentos colineares: os extremos ao longo da direção de a."""
    pa, ua, _ = _direcao(a)
    pts = np.array(
        [a["inicio_utm"], a["fim_utm"], b["inicio_utm"], b["fim_utm"]], float
    )
    s = (pts - pa) @ ua
    ini, fim = pa + s.min() * ua, pa + s.max() * ua
    prancha = (
        a["prancha"]
        if b["prancha"] in a["prancha"].split("+")
        else f"{a['prancha']}+{b['prancha']}"
    )
    return {
        **a,
        "prancha": prancha,
        "inicio_utm": ini.round(3).tolist(),
        "fim_utm": fim.round(3).tolist(),
        "comprimento_m": round(float(s.max() - s.min()), 3),
        "alertas": sorted({*a["alertas"], *b["alertas"]}),
    }


def _distancia_entre_linhas(a: dict, b: dict) -> float:
    """Menor distância (m) entre dois segmentos de linha."""
    ra = shapely.LineString([a["inicio_utm"], a["fim_utm"]])
    rb = shapely.LineString([b["inicio_utm"], b["fim_utm"]])
    return float(shapely.distance(ra, rb))


def unir_linhas(linhas: list[dict]) -> tuple[list[dict], list[str]]:
    """Uma linha por seção. A mesma seção em mais de um segmento (plantas diferentes, ou quebrada por uma estrutura)
    se funde quando os segmentos são colineares (< `COLINEAR_GRAUS` e a ≤ `DIVERGENCIA_LINHA_M`); se não são, a linha é
    de seção quebrada: sai com `quebrada` e nenhum perfil reto a representa. Linhas sem letra lida saem nos alertas."""
    unicas, alertas = {}, []
    for l in linhas:
        if not l["secao"]:
            alertas.append(
                f"linha sem letra em {l['prancha']} ({l['comprimento_m']:.1f} m): {'; '.join(l['alertas'])}"
            )
        elif l["secao"] not in unicas:
            unicas[l["secao"]] = l
        elif _colineares(unicas[l["secao"]], l):
            unicas[l["secao"]] = _fundir(unicas[l["secao"]], l)
        elif l["comprimento_m"] < SEGMENTO_MINIMO_M:
            alertas.append(
                f"seção {l['secao']}: segmento de {l['comprimento_m']:.1f} m em {l['prancha']} não colinear, "
                "ignorado (resto de traço)"
            )
        elif (
            d := _distancia_entre_linhas(unicas[l["secao"]], l)
        ) > DISTANCIA_MAXIMA_QUEBRA_M:
            alertas.append(
                f"seção {l['secao']}: segmento com a letra {l['secao'][0]} a {d:.1f} m da linha principal "
                f"({l['prancha']} {l['comprimento_m']:.1f} m), descartado"
            )
        else:
            a = unicas[l["secao"]]
            unicas[l["secao"]] = {**a, "quebrada": True}
            alertas.append(
                f"seção {l['secao']}: segmentos não colineares ({a['prancha']} {a['comprimento_m']:.1f} m; "
                f"{l['prancha']} {l['comprimento_m']:.1f} m): linha quebrada"
            )
    return sorted(unicas.values(), key=lambda l: l["secao"]), alertas


# --- seções médias -------------------------------------------------------------------------------------------------
def _direcao(linha: dict) -> tuple[np.ndarray, np.ndarray, float]:
    ini, fim = (
        np.asarray(linha["inicio_utm"], float),
        np.asarray(linha["fim_utm"], float),
    )
    v = fim - ini
    comp = float(np.linalg.norm(v))
    return ini, v / comp, comp


def volume_na_faixa(
    la: dict, lb: dict, contorno, g: dict, corte: np.ndarray
) -> tuple[float, float] | None:
    """(distância d entre as linhas, soma do corte na faixa entre elas dentro da cava), ou None se não houver faixa.
    A faixa vai de uma linha à outra, limitada ao trecho que as duas têm em comum ao longo da direção da primeira."""
    pa, ua, ca = _direcao(la)
    n = np.array([-ua[1], ua[0]])
    extremos_b = (np.array([lb["inicio_utm"], lb["fim_utm"]], float) - pa) @ ua
    d = float((np.asarray(lb["inicio_utm"], float) - pa) @ n)
    u0, u1 = max(0.0, extremos_b.min()), min(ca, extremos_b.max())
    if abs(d) < 1.0 or u1 - u0 < 1.0:
        return None
    x0, y0, x1, y1 = contorno.bounds
    c0, c1 = (
        max(int((x0 - g["e0"]) / g["res"]) - 1, 0),
        min(int((x1 - g["e0"]) / g["res"]) + 2, g["forma"][1]),
    )
    r0, r1 = (
        max(int((g["n1"] - y1) / g["res"]) - 1, 0),
        min(int((g["n1"] - y0) / g["res"]) + 2, g["forma"][0]),
    )
    lin, col = np.mgrid[r0:r1, c0:c1]
    x, y = g["e0"] + (col + 0.5) * g["res"], g["n1"] - (lin + 0.5) * g["res"]
    rel = np.stack([x - pa[0], y - pa[1]], -1)
    u, t = rel @ ua, rel @ n
    faixa = (
        (u >= u0)
        & (u <= u1)
        & (t >= min(0, d))
        & (t <= max(0, d))
        & shapely.contains_xy(contorno, x, y)
    )
    return abs(d), float(corte[lin, col][faixa].sum() * g["res"] ** 2)


def _pares_paralelos(cortam: list[dict]) -> list[tuple[dict, dict]]:
    """Pares vizinhos de linhas quase paralelas: agrupa pela direção da primeira ainda sem grupo e ordena pelo
    afastamento lateral."""
    restantes, pares = list(cortam), []
    while restantes:
        ref = restantes.pop(0)
        p0, u0, _ = _direcao(ref)
        grupo = [(0.0, ref)]
        for l in list(restantes):
            p, u, _ = _direcao(l)
            if np.degrees(np.arccos(min(abs(u @ u0), 1.0))) < ANGULO_PARALELO_GRAUS:
                grupo.append((float((p - p0) @ np.array([-u0[1], u0[0]])), l))
                restantes.remove(l)
        grupo.sort(key=lambda x: x[0])
        pares += [(a[1], b[1]) for a, b in itertools.pairwise(grupo)]
    return pares


def _media_do_par(
    cid: str, la: dict, lb: dict, contorno, por_secao: dict, g: dict, corte: np.ndarray
) -> dict:
    """Linha das seções médias para o par (la, lb) de uma cava."""
    a, b = por_secao.get(la["secao"]), por_secao.get(lb["secao"])
    base = {"cava": cid, "secoes": [la["secao"], lb["secao"]]}
    ruins = [  # seção da linha sem corte no projeto (a letra lida não existe nas pranchas de corte) também entra
        l["secao"]
        for l, x in ((la, a), (lb, b))
        if x is None or x["situacao"] == "não conferível"
    ]
    if ruins:
        return {
            **base,
            "situacao": "não conferível",
            "motivo": f"seção sem área completa no projeto: {', '.join(ruins)}",
        }
    faixa = volume_na_faixa(la, lb, contorno, g, corte)
    if faixa is None:
        return {
            **base,
            "situacao": "não conferível",
            "motivo": "as linhas não têm faixa em comum (< 1 m)",
        }
    d, v_modelo = faixa
    v_projeto = (a["area_projeto_m2"] + b["area_projeto_m2"]) / 2 * d
    dif = v_modelo - v_projeto
    return {
        **base,
        "distancia_m": d,
        "volume_projeto_m3": v_projeto,
        "volume_modelo_m3": v_modelo,
        "dif_m3": dif,
        "dif_rel": dif / v_projeto,
        "situacao": "confere" if abs(dif) <= TOL_VOLUME_REL * v_projeto else "difere",
        "motivo": "",
    }


def secoes_medias(
    linhas: list[dict], conferidas: list[dict], cavas: dict, g: dict, corte: np.ndarray
) -> list[dict]:
    """Seções médias por cava: onde ≥ 2 linhas quase paralelas (< `ANGULO_PARALELO_GRAUS`) cortam a mesma cava,
    V_projeto = (A1 + A2)/2 · d e V_modelo = corte na faixa entre as linhas (pares vizinhos). `cavas` = {id: contorno}."""
    por_secao = {c["secao"]: c for c in conferidas}
    saida = []
    for cid, contorno in cavas.items():
        cortam = [
            l
            for l in linhas
            if shapely.intersects(
                contorno, shapely.LineString([l["inicio_utm"], l["fim_utm"]])
            )
        ]
        pares = _pares_paralelos(cortam)
        if not pares:
            saida.append(
                {
                    "cava": cid,
                    "situacao": "não conferível",
                    "motivo": "sem par de seções paralelas",
                }
            )
        saida += [
            _media_do_par(cid, la, lb, contorno, por_secao, g, corte)
            for la, lb in pares
        ]
    return saida


# --- sequência executiva (notas da planta) ------------------------------------------------------------------------
# A fonte das notas tem codificação deslocada: letras minúsculas e dígitos saem em pontos de código fixos; as
# maiúsculas iniciais saem como controles ou símbolos (só se restaura o que se conhece por palavra).
TABELA_FONTE = {
    "Ɛ": "s",
    "Đ": "c",
    "Ă": "a",
    "ǀ": "v",
    "ĕ": "ç",
    "Ć": "ã",
    "Ž": "o",
    "ŝ": "i",
    "Ŷ": "n",
    "ũ": "j",
    "Ğ": "e",
    "ǆ": "x",
    "Ƶ": "u",
    "ƚ": "t",
    "Ś": "h",
    "Ġ": "é",
    "ů": "l",
    "ş": "í",
    "ŵ": "m",
    "ƌ": "r",
    "Ě": "d",
    "Ɖ": "p",
    "ď": "b",
    "Ő": "g",
    "Ĩ": "f",
    "ǌ": "z",
    "Ƌ": "q",
    "ſ": "ó",
    "ġ": "ê",
    "ą": "â",
    "Ɓ": "õ",
    "͕": ",",
    "Ͳ": "-",
    "͘": ".",
    "͖": ";",
    "Ϳ": ")",
    "\x03": " ",
}
TABELA_FONTE.update({chr(0x3EC + d): str(d) for d in range(10)})
NOTA = re.compile(r"(?m)^(\d+)\s*-\s*(Escavação|Reaterro)\b(.*)$")
COTA = re.compile(r"cota\s+(\d{3})\s*[,.]\s*(\d{2})")
ESTRUTURA = re.compile(r"(Câmara de Contato|Caixa de Saída \d+)")
INICIO_DE_LISTA = re.compile(r"(?m)^1\s*-\s*")


def decodificar_texto(texto: str) -> str:
    """Texto das notas com a fonte deslocada decodificada. Restaura só o que a tabela não tem e se conhece por palavra:
    o 'E' inicial perdido de 'Escavação' e 'Execução', e o 'R', 'S' e 'C' iniciais de 'Reaterro', 'Saída' e 'Câmara'."""
    t = "".join(TABELA_FONTE.get(c, c) for c in texto)
    t = re.sub(r";(?=base da viga)", "(", t)
    t = re.sub(r"(?<![A-Za-zÀ-ÿ])scavação", "Escavação", t)
    t = re.sub(r"(?<![A-Za-zÀ-ÿ])xecução", "Execução", t)
    t = re.sub(r"(?<![A-Za-zÀ-ÿ])Zeaterro", "Reaterro", t)
    t = t.replace("^aída", "Saída")
    return re.sub(r"\x12(?=âmara|aixa|ontato)", "C", t)


def notas_do_texto(texto: str) -> list[dict]:
    """Notas de escavação e reaterro de um texto já decodificado: [{bloco, fase, tipo, cota_m, estrutura, texto}].
    `bloco` numera as listas (a numeração recomeça em 1); `fase` é o número da nota; `estrutura` é a citada no mesmo
    bloco ou None; `cota_m` é None onde a nota diz só 'cota final'."""
    inicios = [m.start() for m in INICIO_DE_LISTA.finditer(texto)] + [len(texto)]
    notas, bloco = [], 0
    for ini, fim in itertools.pairwise(inicios):
        achada = ESTRUTURA.search(texto[ini:fim])
        achadas = list(NOTA.finditer(texto, ini, fim))
        bloco += bool(
            achadas
        )  # só as listas com notas de escavação ou reaterro são numeradas
        for m in achadas:
            cota = COTA.search(m[3])
            notas.append(
                {
                    "bloco": bloco,
                    "fase": int(m[1]),
                    "tipo": m[2].lower(),
                    "cota_m": float(f"{cota[1]}.{cota[2]}") if cota else None,
                    "estrutura": achada[1] if achada else None,
                    "texto": f"{m[2]}{m[3]}".strip(),
                }
            )
    return notas


def sequencia_executiva(pdf: str | Path) -> list[dict]:
    """Notas da sequência executiva de uma planta (texto vetorial decodificado por `decodificar_texto`)."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return notas_do_texto(decodificar_texto(doc[0].get_text()))


def ligar_sequencia(notas: list[dict], cavas: list[dict]) -> list[dict]:
    """Compara cada cota de escavação com o fundo do modelo só onde a ligação é objetiva: exatamente uma cava com
    fundo mínimo a ±`TOL_FUNDO_M` da cota. A situação é "compatível por valor" (não "confere"): a nota não diz onde, então
    só o valor casa. O resto é "não conferível" com o
    motivo: reaterro (o modelo não tem cota de reaterro), cota final sem valor, nenhuma cava ou várias com esse fundo."""
    saida = []
    for n in notas:
        r = {**n, "situacao": "não conferível", "cava": None}
        if n["tipo"] != "escavação":
            r["motivo"] = "o modelo não tem cota de reaterro"
        elif n["cota_m"] is None:
            r["motivo"] = "a nota diz 'cota final' sem valor numérico"
        else:
            perto = [
                c for c in cavas if abs(c["fundo_m"][0] - n["cota_m"]) <= TOL_FUNDO_M
            ]
            if len(perto) == 1:
                r.update(
                    situacao=SITUACAO_SEQUENCIA,
                    cava=perto[0]["id"],
                    motivo=(
                        f"fundo do modelo na cava {perto[0]['id']}: {perto[0]['fundo_m'][0]:.2f} m "
                        f"(a ±{TOL_FUNDO_M:.2f} m; ligação só por valor)"
                    ),
                )
            else:
                onde = f"{len(perto)} cavas" if perto else "nenhuma cava"
                r["motivo"] = (
                    f"{onde} com fundo a ±{TOL_FUNDO_M:.2f} m da cota: a nota não diz onde"
                )
        saida.append(r)
    return _sem_ligacao_repetida(saida)


def _sem_ligacao_repetida(linhas: list[dict]) -> list[dict]:
    """A mesma cava ligada por notas de estruturas diferentes (cotas iguais escritas para estruturas distintas) não
    prova onde a cota vale: essas ligações voltam a "não conferível"."""
    estruturas: dict[str, set] = {}
    for r in linhas:
        if r["cava"]:
            estruturas.setdefault(r["cava"], set()).add(r["estrutura"])
    for r in linhas:
        if r["cava"] and len(estruturas[r["cava"]]) > 1:
            r["motivo"] = (
                f"a cava {r['cava']} também casa com notas de {len(estruturas[r['cava']]) - 1} outra(s) "
                "estrutura(s): a nota não diz onde"
            )
            r["situacao"], r["cava"] = "não conferível", None
    return linhas


# --- apresentação (texto pronto para o HTML) -----------------------------------------------------------------------
def _txt(valor, casas: int = 2, sinal: bool = False) -> str:
    """Número com vírgula decimal; '—' onde não há valor. Formata só o número (nunca uma frase inteira)."""
    if valor is None:
        return "—"
    return f"{valor:{'+' if sinal else ''}.{casas}f}".replace(".", ",")


def _numero(valor: float) -> str:
    """Número sem zeros à direita, com vírgula decimal."""
    return f"{valor:g}".replace(".", ",")


def _pct(valor) -> str:
    """Fração em porcentagem com sinal e vírgula decimal; '—' onde não há valor."""
    return "—" if valor is None else f"{valor:+.0%}".replace(".", ",")


def _terreno_da_secao_txt(fracao: float | None) -> str:
    """De onde vem o terreno do modelo ao longo da seção: MDS puro, ou a parte que é topografia do projeto."""
    return (
        "MDS"
        if fracao is None
        else f"{fracao:.0%} topografia do projeto".replace(".", ",")
    )


def formatar_secao(r: dict) -> dict:
    """Linha de seção da conferência com os números já em texto (o HTML só mostra)."""
    return {
        "secao": r["secao"],
        "prancha": r["prancha"],
        "situacao": r["situacao"],
        "motivo": r.get("motivo", ""),
        "area_projeto_txt": _txt(r["area_projeto_m2"], 1),
        "area_modelo_txt": _txt(r.get("area_modelo_m2"), 1),
        "dif_area_txt": _txt(r.get("dif_area_m2"), 1, True),
        "dif_area_rel_txt": _pct(r.get("dif_area_rel")),
        "area_corrigida_txt": _txt(r.get("area_modelo_corrigida_terreno_m2"), 1),
        "dif_area_corrigida_rel_txt": _pct(r.get("dif_area_corrigida_rel")),
        "fundo_projeto_txt": _txt(r["fundo_projeto_m"]),
        "fundo_modelo_txt": _txt(r.get("fundo_modelo_m")),
        "dif_fundo_txt": _txt(r.get("dif_fundo_m"), 2, True),
        "dif_terreno_txt": _txt(r.get("dif_terreno_m"), 2, True),
        "terreno_modelo_txt": _terreno_da_secao_txt(r.get("fracao_terreno_topografia")),
        "talude_projeto_txt": _txt(r.get("talude_projeto_h_v"), 2),
    }


def formatar_media(r: dict) -> dict:
    """Linha de seção média com os números em texto."""
    return {
        "cava": r["cava"],
        "secoes": " e ".join(r.get("secoes", [])) or "—",
        "situacao": r["situacao"],
        "motivo": r.get("motivo", ""),
        "distancia_txt": _txt(r.get("distancia_m"), 1),
        "volume_projeto_txt": _txt(r.get("volume_projeto_m3"), 0),
        "volume_modelo_txt": _txt(r.get("volume_modelo_m3"), 0),
        "dif_rel_txt": _pct(r.get("dif_rel")),
    }


def formatar_nota(n: dict) -> dict:
    """Linha da sequência executiva com a cota em texto."""
    return {
        "bloco": n["bloco"],
        "fase": n["fase"],
        "tipo": n["tipo"],
        "cota_txt": _txt(n["cota_m"]),
        "estrutura": n["estrutura"] or "—",
        "situacao": n["situacao"],
        "motivo": n["motivo"],
    }


def placar(
    linhas: list[dict], situacoes: tuple[str, ...] = SITUACOES_SECAO
) -> dict[str, int]:
    """Contagem por situação (seções: confere / difere / não conferível)."""
    return {s: sum(l["situacao"] == s for l in linhas) for s in situacoes}


def placar_sequencia(notas: list[dict]) -> dict[str, int]:
    """Placar da sequência executiva: 'compatível por valor' (a nota não diz onde) × não conferível."""
    return placar(notas, (SITUACAO_SEQUENCIA, "não conferível"))


def _tolerancias_txt() -> list[str]:
    return [
        f"fundo ±{_txt(TOL_FUNDO_M)} m (absoluta)",
        f"terreno médio MDS × TERRENO ORIGINAL ±{_txt(TOL_TERRENO_M)} m (absoluta)",
        f"área: o maior entre {TOL_AREA_REL:.0%} da área do projeto e {_txt(TOL_TERRENO_M)} m × largura do corte",
        f"seções médias: volume ±{TOL_VOLUME_REL:.0%}",
        f"corte com área < {AREA_MINIMA_M2:g} m²: sem corte no projeto",
        f"linha que não cobre o corte do projeto (folga de {_txt(FOLGA_COBERTURA_M, 1)} m): linha incompleta",
        (
            f"mais de {FRACAO_MAXIMA_EDIFICACAO:.0%} do trecho do corte sobre edificação, ou desvio do terreno acima de "
            f"{_txt(DESVIO_MAXIMO_TERRENO_M)} m: não conferível"
        ),
    ]


# --- etapa do build ------------------------------------------------------------------------------------------------
def _assinatura(pdf: str | Path, extra="") -> str:
    arq = Path(pdf)
    return f"{arq.stat().st_size}:{int(arq.stat().st_mtime)}:{extra}"


def _com_cache(cache: dict, chave: str, assinatura: str, calcular):
    """Resultado em cache (a leitura de PDF e o OCR são lentos), recalculado se a assinatura do arquivo mudou."""
    if cache.get(chave, {}).get("assinatura") != assinatura:
        cache[chave] = {"assinatura": assinatura, "valor": calcular()}
    return cache[chave]["valor"]


def _ler_pdfs(
    c: dict, pranchas: list, cache: dict, log
) -> tuple[list[dict], list[dict], list[dict]]:
    """Seções do projeto (pranchas de corte), linhas das plantas e notas da sequência executiva."""
    from . import secoes_corte

    projeto = []
    for pdf in c["pranchas_corte"]:
        projeto += _com_cache(
            cache,
            f"corte:{pdf}",
            _assinatura(pdf),
            lambda pdf=pdf: secoes_corte.ler_secoes(pdf),
        )
    linhas, notas = [], []
    por_id = {p["id"]: p for p in pranchas}
    for pid in c["pranchas_planta"]:
        p = por_id.get(pid)
        if p is None or p.get("M") is None or not Path(p["pdf"]).exists():
            log(
                f"Conferência das cavas: planta {pid} sem georreferência ou sem PDF, fica de fora"
            )
            continue
        M = np.asarray(p["M"], float)
        linhas += _com_cache(
            cache,
            f"linhas:{pid}",
            _assinatura(p["pdf"], f"v{VERSAO_LEITURA_LINHAS}:{M.round(6).tolist()}"),
            lambda p=p, M=M: linhas_da_planta(p["pdf"], M, p.get("clip"), p["id"]),
        )
        notas += _com_cache(
            cache,
            f"notas:{pid}",
            _assinatura(p["pdf"]),
            lambda p=p: sequencia_executiva(p["pdf"]),
        )
    return projeto, linhas, notas


AVISO_TERRENO_CIRCULAR = (
    "terreno do modelo = topografia do projeto (curvas da GEOPLANTA) dentro do casco e MDS corrigido fora: a diferença "
    "de terreno entre o modelo e o TERRENO ORIGINAL das seções é quase circular onde o terreno é a topografia; "
    "área e fundo seguem informativos"
)


def _terreno_do_modelo(g: dict) -> dict | None:
    """Declaração da fonte do terreno do modelo quando ele é composto (topografia + MDS); None quando é o MDS puro."""
    resumo = g.get("terreno_resumo")
    if resumo is None:
        return None
    return {
        "fonte": "topografia do projeto no casco, MDS corrigido fora",
        "circular_na_comparacao_de_terreno": True,
        "area_m2": resumo["area_m2"],
        "sem_terreno": resumo["sem_terreno"],
        "faixa_costura_m": resumo.get("faixa_costura_m"),
        "limite_extrapolacao_m": resumo.get("limite_extrapolacao_m"),
        "validacao_fora_do_casco": resumo.get("validacao_fora_do_casco"),
        "alertas": resumo.get("alertas", []),
        "aviso": AVISO_TERRENO_CIRCULAR,
    }


NOMES_DAS_ORIGENS = {
    "topografia": "topografia do projeto (dentro do casco)",
    "costura": "costura (faixa fora do casco)",
    "mds_corrigido": "MDS corrigido pelo plano",
    "mds_corrigido_extrapolado": "MDS corrigido, plano extrapolado",
    "sem_terreno": "sem terreno (pendência)",
}
NOMES_DOS_MOTIVOS = {
    "fora_do_levantamento_m2": "fora do levantamento do MDS",
    "edificacao_m2": "edificação",
    "vegetacao_alta_m2": "vegetação alta",
}


def formatar_terreno_do_modelo(t: dict) -> dict:
    """Terreno composto do modelo já em texto para a aba: área por origem, pendência "sem terreno" por motivo, validação
    fora do casco (resíduo por distância à borda e furos) e os avisos. O HTML só mostra."""
    v = t.get("validacao_fora_do_casco") or {}
    topo_bocas = v.get("topografia_menos_boca_dentro_do_casco") or {}
    return {
        "fonte": t["fonte"],
        "aviso": t["aviso"],
        "areas": [
            {"origem": NOMES_DAS_ORIGENS.get(k, k), "area_txt": f"{_txt(m2, 0)} m²"}
            for k, m2 in t["area_m2"].items()
        ],
        "sem_terreno": [
            {
                "motivo": NOMES_DOS_MOTIVOS[k],
                "area_txt": f"{_txt(t['sem_terreno'][k], 0)} m²",
            }
            for k in NOMES_DOS_MOTIVOS
        ],
        "sem_terreno_total_txt": f"{_txt(t['sem_terreno']['total_m2'], 0)} m²",
        "topografia_x_bocas_txt": (
            f"topografia − boca dos furos dentro do casco: n {topo_bocas.get('n', 0)}, "
            f"média {_txt(topo_bocas.get('media_m'), 2, True)} m, rms {_txt(topo_bocas.get('rms_m'), 2)} m"
        ),
        "faixas_borda": [
            {
                "faixa": nome,
                "n": e["n"],
                "media_txt": _txt(e["media_m"], 2, True),
                "mediana_txt": _txt(e["mediana_m"], 2, True),
            }
            for nome, e in (
                v.get("residuo_dentro_do_casco_por_distancia_a_borda") or {}
            ).items()
        ],
        "furos_fora": [
            {
                "furo": f["id"],
                "distancia_txt": _txt(f["distancia_ao_casco_m"], 1),
                "mds_txt": _txt(f["mds_menos_boca_m"], 2, True),
                "corrigido_txt": _txt(f["mds_corrigido_menos_boca_m"], 2, True),
                "composto_txt": _txt(f["composto_menos_boca_m"], 2, True),
            }
            for f in v.get("furos_fora_do_casco", [])
        ],
        "plano_melhora_txt": {
            True: "sim",
            False: "NÃO",
            None: "sem furos fora do casco",
        }[v.get("plano_melhora_furos_de_fora")],
        "alertas": list(t.get("alertas", [])),
    }


def conferir(projeto: list, linhas: list, notas: list, saida: dict) -> dict:
    """Junta tudo: `saida` é o que a escavação entregou (`g`, `corte`, `contornos`, `resultado`)."""
    g, corte = saida["g"], saida["corte"]
    unicas, alertas = unir_linhas(linhas)
    retas = [l for l in unicas if not l.get("quebrada")]
    modelo = {
        l["secao"]: {
            **perfil_do_modelo(l, g, corte),
            "linha_prancha": l["prancha"],
            "comprimento_linha_m": l["comprimento_m"],
            "quebrada": bool(l.get("quebrada")),
            "marca_proxima": marca_proxima_da_linha(l, saida.get("marcas", [])),
        }
        for l in unicas
    }
    secoes = conferir_secoes(projeto, modelo)
    medias = secoes_medias(retas, secoes, saida["contornos"], g, corte)
    terreno_do_modelo = _terreno_do_modelo(g)
    if terreno_do_modelo:
        alertas = [*alertas, AVISO_TERRENO_CIRCULAR, *terreno_do_modelo["alertas"]]
    return {
        **({"terreno_do_modelo": terreno_do_modelo} if terreno_do_modelo else {}),
        "secoes": secoes,
        "medias": medias,
        "sequencia": ligar_sequencia(notas, saida["cavas_info"]),
        "linhas": unicas,
        "alertas": alertas,
    }


def etapa(
    cfg: dict, pranchas: list, out: Path, saida_gavetas: dict | None, log=print
) -> dict | None:
    """Etapa do build: confere as cavas do modelo contra as seções de corte do projeto. Grava
    `conferencia_cavas.json` e devolve o pacote do HTML (números já em texto). Sem PDF de corte no disco ou sem as
    cavas calculadas, pula com a pendência no log."""
    c = (cfg.get("escavacao") or {}).get("conferencia")
    if not c:
        return None
    if not any(Path(p).exists() for p in c["pranchas_corte"]):
        log(
            "Conferência das cavas: PDFs das pranchas de corte ausentes no disco (pendência; o build segue sem ela)"
        )
        return None
    if not saida_gavetas or "corte" not in saida_gavetas:
        log(
            "Conferência das cavas: a escavação não foi calculada (pendência; o build segue sem ela)"
        )
        return None
    cache_arq = out / "conferencia_cavas_cache.json"
    cache = json.loads(cache_arq.read_text()) if cache_arq.exists() else {}
    c = {**c, "pranchas_corte": [p for p in c["pranchas_corte"] if Path(p).exists()]}
    projeto, linhas, notas = _ler_pdfs(c, pranchas, cache, log)
    cache_arq.write_text(json.dumps(cache, ensure_ascii=False))
    r = conferir(projeto, linhas, notas, saida_gavetas)
    (out / "conferencia_cavas.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=1, default=float)
    )
    p = placar(r["secoes"])
    log(
        f"Conferência das cavas: {len(r['secoes'])} seções — {p['confere']} confere, {p['difere']} difere, "
        f"{p['não conferível']} não conferível; seções médias {placar(r['medias'])}; sequência "
        f"{placar_sequencia(r['sequencia'])}; {len(r['alertas'])} alerta(s)"
    )
    return para_html(r)


def para_html(r: dict) -> dict:
    """Pacote do HTML: linhas já formatadas em Python (o front só apresenta)."""
    return {
        "placar": placar(r["secoes"]),
        "placar_sequencia": placar_sequencia(r["sequencia"]),
        **(
            {"terreno_do_modelo": formatar_terreno_do_modelo(r["terreno_do_modelo"])}
            if r.get("terreno_do_modelo")
            else {}
        ),
        "secoes": [formatar_secao(s) for s in r["secoes"]],
        "medias": [formatar_media(m) for m in r["medias"]],
        "sequencia": [formatar_nota(n) for n in r["sequencia"]],
        "alertas": r["alertas"],
        "tolerancias": _tolerancias_txt(),
        "nota": f"O modelo usa talude {_numero(escavacao.VALOR['talude_h_v'])}H:1V; onde o projeto tem "
        "contenção por estacas (talude ~0) a área do modelo tende a ser maior.",
    }
