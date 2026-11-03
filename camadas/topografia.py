"""Topografia do projeto (curvas de nível do PDF) como testemunha do terreno do MDS do drone.

O MDS herda a altitude das sondagens (plano ajustado às cotas de boca) e soma o erro de forma
do SfM. Aqui entra a outra fonte de terreno que o projeto tem: as curvas de nível da GEOPLANTA e
das plantas de escavação (layers `Curvas_Mestras` e `Curvas_Auxiliares`, vetoriais). Este módulo
só dá evidência; nenhum cálculo de volume muda.

    curvas   = curvas_de_nivel(pdf, M, clip)           # [{cota_m, coords_utm, origem, alertas}]
    resumo   = resumir_curvas(curvas)                    # equidistância lida e curvas sem cota
    tin      = modelo_tin(curvas)                        # TIN linear (scipy)
    topo     = superficie(curvas, grade_do_mds)          # no e0, n1 e res do MDS; NaN fora do casco
    relatorio = comparar(...)                            # tabelas (a), (b), (c) e (d)

Como a cota de cada curva é lida: o número da curva é desenhado como traços de vetor no próprio
layer (a curva abre uma folga onde o rótulo fica). Os traços pequenos viram rótulos, agrupados por
proximidade; cada rótulo é redesenhado na horizontal (eixo principal do texto) e lido por OCR, com
voto entre variações de espessura e de modo do tesseract. A equidistância sai das próprias leituras:
o maior passo de que quase todas as cotas são múltiplas; leitura incoerente com ele é trocada pela
segunda mais votada ou descartada. Cada rótulo dá a cota às curvas com ponta perto dele. Curva sem
rótulo recebe a cota da vizinhança (TIN das curvas já datadas, arredondada ao passo) só se a
interpolação cair perto do passo, e fica com alerta.

Limite conhecido: TIN de curvas de nível faz triângulos chatos entre pontos da mesma curva (cristas
e fundos de vale), e o erro da interpolação em terreno quase plano é da ordem de metade da
equidistância. Por isso as comparações devem ser lidas como evidência, não como verdade.
"""

from __future__ import annotations

import collections
import itertools
import json
import re
from pathlib import Path

import cv2
import numpy as np

from . import pdf_cad

# --- constantes e tolerâncias (cada uma com o porquê) ---------------------------------------------------------------
CAMADAS_CURVAS = r"^Curvas_(Mestras|Auxiliares)$"  # layers de curva de nível das plantas Sanepar/Bassani
LIMITE_GLIFO_PT = (
    10.0  # traço com extensão menor é glifo de rótulo (texto ~7 pt); curva é bem maior
)
RAIO_AGRUPAR_GLIFOS_PT = 4.5  # glifos a menos disso (dilatação) formam o mesmo rótulo
RAIO_ROTULO_PT = 30.0  # rótulo vale para a curva com ponta a até isto (como o raio de cota da escavação)
FATOR_PONTA_MAIS_PERTO = (
    1.6  # além da ponta mais perta, só vale ponta a até 1,6x (lado oposto da folga)
)
RAIO_ROTULO_SOBRE_CURVA_PT = (
    12.0  # rótulo sobre curva contínua (sem folga): distância ao traço
)
FAIXA_COTA_M = (
    100.0,
    400.0,
)  # altitude plausível do sítio; descarta leitura de OCR absurda
PASSOS_EQUIDISTANCIA_M = (5.0, 2.0, 1.0, 0.5, 0.25)  # candidatos, do maior ao menor
FRACAO_MULTIPLOS_MINIMA = (
    0.8  # fração das leituras que deve ser múltipla do passo escolhido
)
FRACAO_DECIMAIS_MINIMA = 0.5  # idem, só entre os rótulos fracionários (poucos, e o OCR erra o dígito depois da vírgula)
VOTOS_PARA_PARAR = 3  # leituras iguais numa orientação bastam; não testa as outras
ESCALA_OCR_PX_PT = 8  # pixels por pt do rótulo redesenhado (o glifo tem ~7 pt)
ESPESSURAS_OCR_PX = (3, 5)  # traço do glifo redesenhado; varia para o voto
ESTICAR_X_OCR = (
    1.0,
    1.5,
)  # a fonte é condensada: esticar o texto em x ajuda o tesseract (testado em Foz)
MODO_OCR = 7  # modo de página do tesseract: uma linha de texto
N_PONTOS_FORMA = 24  # pontos da forma do glifo reamostrada por comprimento de arco
TAMANHO_MINIMO_GLIFO_PT = (
    3.0  # glifo com caixa menor (ponto decimal) não entra no eixo do texto
)
TOLERANCIA_AGRUPAR_FORMA_PT = (
    0.5  # glifos a menos disso (média ponto a ponto) são o mesmo caractere
)
TOLERANCIA_GLIFO_PT = 0.8  # glifo casa com o alfabeto até esta distância (texto de ~7 pt; traço solto fica longe)
VOTOS_MINIMOS_CLASSE = (
    2  # classe de glifo só entra no alfabeto com pelo menos isto de votos do OCR
)
VOTOS_ALFABETO = 3  # peso da leitura pelo alfabeto aprendido ao lado dos votos do OCR
INFERENCIA_TOLERANCIA_REL = (
    0.2  # curva sem rótulo: cota interpolada a até 0,2 passo de um múltiplo
)
INFERENCIA_RODADAS = 3  # inferência em cascata: curva datada ajuda a datar a vizinha
ESPACAMENTO_PONTOS_M = (
    1.0  # a curva entra no TIN com pontos a cada 1 m (o PDF dá ~0,5 m)
)
PASSO_PERFIL_M = 0.25  # amostragem do perfil de seção (a mesma res do MDS)
LIMITE_MAPA_M = 1.0  # escala de cor do mapa do erro: ±1 m
ESCALA_TENDENCIA_M = (
    100.0  # E,N centrados e divididos por isto no ajuste (condiciona a quadrática)
)
MAX_AMOSTRAS_TENDENCIA = 400_000  # amostras do ajuste: passo regular sobre as células válidas (determinístico)
FAIXAS_DISTANCIA_M = (
    0.0,
    10.0,
    20.0,
    35.0,
    50.0,
    80.0,
    np.inf,
)  # distância à sondagem usada no plano
PERCENTIS = (5, 50, 95)
CLASSES_TERRENO_ABERTO = (
    "grama",
    "pavimento",
    "solo",
)  # sem copa nem telhado: o MDS vê o chão
APARAR_MAD = 2.5  # ajuste aparado: descarta amostras a mais de 2,5 desvios-MAD (≈ 2,5 σ) do ajuste
RODADAS_APARAR = 4  # repetições do ajuste aparado (converge em 2 a 3)
ESCALA_PNG = 2  # pixels do PNG por célula da grade (o mapa é lido a olho)
CLASSES = ("edificacao", "vegetacao", "grama", "solo", "pavimento", "sem_classe")
LIMITE_TOLERANCIA_SONDAGEM_M = (
    0.30  # tolerância de terreno da conferência das cavas (TOL_TERRENO_M)
)


# --- curvas e rótulos no PDF ----------------------------------------------------------------------------------------
def _matriz3(M) -> np.ndarray:
    M = np.asarray(M, float)
    return np.vstack([M, [0, 0, 1]]) if M.shape == (2, 3) else M


def _para_utm(pontos_pt: np.ndarray, M) -> np.ndarray:
    h = np.c_[pontos_pt, np.ones(len(pontos_pt))] @ _matriz3(M).T
    return h[:, :2] / h[:, 2:3]


def separar_tracos(
    tracos: list[dict],
    camadas: str = CAMADAS_CURVAS,
    glifo_max_pt: float = LIMITE_GLIFO_PT,
) -> tuple[list[dict], list[dict]]:
    """Traços dos layers de curva: (curvas, glifos). Curva = {pontos_pt, layer} de cada subcaminho com ≥ 2 pontos e
    extensão ≥ `glifo_max_pt`; glifo = traço inteiro menor que isso (peça de texto)."""
    curvas, glifos = [], []
    for t in tracos:
        if not re.search(camadas, t["layer"]):
            continue
        if np.ptp(np.vstack(t["partes"]), axis=0).max() < glifo_max_pt:
            glifos.append(t)
            continue
        for p in t["partes"]:
            p = np.asarray(p, float)
            if len(p) >= 2 and np.ptp(p, axis=0).max() >= glifo_max_pt:
                curvas.append({"pontos_pt": p, "layer": t["layer"]})
    return curvas, glifos


def agrupar_glifos(
    glifos: list[dict], raio_pt: float = RAIO_AGRUPAR_GLIFOS_PT
) -> list[list[dict]]:
    """Glifos próximos formam um rótulo: desenha os traços, dilata `raio_pt` e separa os componentes conexos."""
    if not glifos:
        return []
    todos = np.vstack([np.vstack(t["partes"]) for t in glifos])
    x0, y0 = np.floor(todos.min(0)) - raio_pt - 2
    m = np.zeros(
        (
            int(np.ceil(todos[:, 1].max() - y0 + raio_pt + 2)),
            int(np.ceil(todos[:, 0].max() - x0 + raio_pt + 2)),
        ),
        np.uint8,
    )
    for t in glifos:
        for p in t["partes"]:
            cv2.polylines(
                m, [(np.asarray(p) - [x0, y0]).round().astype(np.int32)], False, 255, 1
            )
    k = 2 * round(raio_pt) + 1
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    _, rotulo = cv2.connectedComponents(m)
    grupos = collections.defaultdict(list)
    for t in glifos:
        x, y = np.asarray(t["partes"][0])[0] - [
            x0,
            y0,
        ]  # primeiro vértice: sempre sobre o traço
        grupos[int(rotulo[round(y), round(x)])].append(t)
    return [grupos[k] for k in sorted(grupos)]


def _interpretar_numero(texto: str) -> float | None:
    """'237,5' / '239' -> float, só se for plausível (`FAIXA_COTA_M`); o traço solto do OCR é ignorado."""
    limpo = re.sub(r"[^0-9,.]", "", texto).strip(".,")
    achado = re.fullmatch(r"(\d{3})(?:[.,](\d{1,2}))?", limpo)
    if not achado:
        return None
    valor = float(f"{achado[1]}.{achado[2] or '0'}")
    return valor if FAIXA_COTA_M[0] <= valor <= FAIXA_COTA_M[1] else None


def _orientacoes(grupo: list[dict]):
    """Rotações que deixam o texto na horizontal: a reta pelos centros dos glifos grandes (a linha de base; o ponto
    decimal e os traços soltos ficam de fora), mais o giro de 180° e os de ±90°."""
    caixas = np.array(
        [(np.vstack(t["partes"]).min(0), np.vstack(t["partes"]).max(0)) for t in grupo]
    )
    reais = np.array(
        [len(np.vstack(t["partes"])) >= 3 for t in grupo]
    )  # reta de 2 vértices: resto da curva
    grandes = reais & ((caixas[:, 1] - caixas[:, 0]).max(1) >= TAMANHO_MINIMO_GLIFO_PT)
    centros = (
        caixas[grandes].mean(1)
        if grandes.sum() >= 2
        else np.vstack([np.vstack(t["partes"]) for t in grupo])
    )
    _, _, vt = np.linalg.svd(centros - centros.mean(0), full_matrices=False)
    angulo = np.arctan2(vt[0, 1], vt[0, 0])
    for extra in (0.0, np.pi, np.pi / 2, -np.pi / 2):
        a = -(angulo + extra)
        yield np.array([[np.cos(a), -np.sin(a)], [np.sin(a), np.cos(a)]])


def _imagem_do_rotulo(
    grupo: list[dict],
    centro: np.ndarray,
    R: np.ndarray,
    espessura_px: int,
    esticar_x: float,
) -> np.ndarray:
    """Rótulo redesenhado em preto sobre branco, na horizontal, a `ESCALA_OCR_PX_PT`, com o texto esticado em x (a
    fonte das plantas é condensada e o tesseract lê melhor mais larga)."""
    alto, largo = 60 * ESCALA_OCR_PX_PT, 160 * ESCALA_OCR_PX_PT
    imagem = np.full((alto, largo), 255, np.uint8)
    meio = np.array([largo / 2, alto / 2])
    escala = np.array([esticar_x, 1.0]) * ESCALA_OCR_PX_PT
    for t in grupo:
        for p in t["partes"]:
            q = ((np.asarray(p) - centro) @ R.T) * escala + meio
            cv2.polylines(imagem, [q.round().astype(np.int32)], False, 0, espessura_px)
    return imagem


def _votos_da_orientacao(
    grupo: list[dict], centro: np.ndarray, R: np.ndarray
) -> collections.Counter:
    """Votos do OCR (espessura × esticamento) para um rótulo numa orientação."""
    import pytesseract

    votos: collections.Counter = collections.Counter()
    for espessura, esticar in itertools.product(ESPESSURAS_OCR_PX, ESTICAR_X_OCR):
        texto = pytesseract.image_to_string(
            _imagem_do_rotulo(grupo, centro, R, espessura, esticar),
            config=f"--psm {MODO_OCR} -c tessedit_char_whitelist=0123456789,.",
        )
        valor = _interpretar_numero(texto)
        if valor is not None:
            votos[valor] += 1
    return votos


def ler_rotulo(grupo: list[dict]) -> dict | None:
    """Lê o número de um rótulo por OCR (tesseract): {centro_pt, candidatos {cota_m: votos}, grupo, R} ou None.
    Vale a orientação (eixo do texto, giro de 180° ou de ±90°) com a leitura mais votada.

    Exige `pytesseract` e o binário `tesseract`."""
    pontos = np.vstack([np.vstack(t["partes"]) for t in grupo])
    centro = pontos.mean(0)
    melhor = None
    for R in _orientacoes(grupo):
        votos = _votos_da_orientacao(grupo, centro, R)
        if votos and (melhor is None or max(votos.values()) > max(melhor[0].values())):
            melhor = (votos, R)
        if votos and max(votos.values()) >= VOTOS_PARA_PARAR:
            break
    if melhor is None:
        return None
    return {
        "centro_pt": centro,
        "candidatos": dict(melhor[0]),
        "grupo": grupo,
        "R": melhor[1],
    }


# --- alfabeto aprendido: a fonte das plantas é a mesma em todos os rótulos --------------------------------------------
def _forma_do_glifo(traco: dict, centro: np.ndarray, R: np.ndarray) -> dict | None:
    """Glifo na horizontal: posição x e forma reamostrada em `N_PONTOS_FORMA` pontos por comprimento de arco, centrada
    na caixa (pt). None se o traço não tem comprimento."""
    p = (np.vstack(traco["partes"]) - centro) @ R.T
    arco = np.r_[0.0, np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))]
    if arco[-1] < 1e-9:
        return None
    t = np.linspace(0.0, arco[-1], N_PONTOS_FORMA)
    q = np.c_[np.interp(t, arco, p[:, 0]), np.interp(t, arco, p[:, 1])]
    meio = (q.min(0) + q.max(0)) / 2
    return {"x": float(meio[0]), "forma": q - meio}


def _distancia_formas(a: np.ndarray, b: np.ndarray) -> float:
    """Distância média ponto a ponto (pt) entre duas formas, vendo o traço nos dois sentidos."""
    return float(
        min(
            np.linalg.norm(a - b, axis=1).mean(),
            np.linalg.norm(a - b[::-1], axis=1).mean(),
        )
    )


def _glifos_em_ordem(grupo: list[dict], R: np.ndarray) -> list[dict]:
    """Glifos do rótulo da esquerda para a direita; o traço reto de 2 vértices é resto da curva, não caractere (todo
    caractere da fonte tem ≥ 3 vértices)."""
    centro = np.vstack([np.vstack(t["partes"]) for t in grupo]).mean(0)
    formas = [
        f
        for f in (
            _forma_do_glifo(t, centro, R)
            for t in grupo
            if len(np.vstack(t["partes"])) >= 3
        )
        if f
    ]
    return sorted(formas, key=lambda f: f["x"])


def _classe_da_forma(classes: list[dict], forma: np.ndarray) -> dict:
    """Classe de glifo cuja forma está a até `TOLERANCIA_AGRUPAR_FORMA_PT`; cria a classe se não houver."""
    for c in classes:
        if _distancia_formas(c["forma"], forma) <= TOLERANCIA_AGRUPAR_FORMA_PT:
            return c
    classes.append({"forma": forma, "votos": collections.Counter()})
    return classes[-1]


def aprender_alfabeto(leituras: list[dict], passo_m: float | None = None) -> list[dict]:
    """Alfabeto {forma, caractere} a partir dos rótulos que o OCR leu: o i-ésimo glifo, da esquerda para a direita,
    recebe o i-ésimo caractere de cada leitura candidata (peso = votos) quando a contagem confere. Glifos de forma
    igual (distância ≤ `TOLERANCIA_AGRUPAR_FORMA_PT`) formam uma classe; vale o caractere mais votado, com pelo menos
    `VOTOS_MINIMOS_CLASSE` votos. Com `passo_m`, só contam leituras múltiplas dele (o OCR lê 237,9 onde é 237,5)."""
    classes: list[dict] = []
    for r in leituras:
        glifos = _glifos_em_ordem(r["grupo"], r["R"])
        for valor, votos in r["candidatos"].items():
            texto = f"{valor:g}"
            if len(texto) != len(glifos) or (passo_m and not _multiplo(valor, passo_m)):
                continue
            for g, caractere in zip(glifos, texto):
                _classe_da_forma(classes, g["forma"])["votos"][caractere] += votos
    return [
        {"forma": c["forma"], "caractere": c["votos"].most_common(1)[0][0]}
        for c in classes
        if sum(c["votos"].values()) >= VOTOS_MINIMOS_CLASSE
    ]


def decodificar_rotulo(grupo: list[dict], alfabeto: list[dict]) -> dict | None:
    """Lê o rótulo pelo alfabeto aprendido, em cada orientação. Glifo que não casa com nenhuma classe e fica numa ponta
    do rótulo é traço solto e sai; no meio do texto invalida a orientação (caractere desconhecido). Vale a de menor
    distância média cuja leitura é um número plausível."""
    if not alfabeto:
        return None
    pontos = np.vstack([np.vstack(t["partes"]) for t in grupo])
    melhor = None
    for R in _orientacoes(grupo):
        casados = []
        for g in _glifos_em_ordem(grupo, R):
            d = [_distancia_formas(a["forma"], g["forma"]) for a in alfabeto]
            casados.append((alfabeto[int(np.argmin(d))]["caractere"], min(d)))
        while (
            casados and casados[0][1] > TOLERANCIA_GLIFO_PT
        ):  # traço solto antes ou depois do texto
            casados.pop(0)
        while casados and casados[-1][1] > TOLERANCIA_GLIFO_PT:
            casados.pop()
        distancias = [d for _, d in casados]
        texto = (
            "".join(c for c, _ in casados)
            if casados and max(distancias) <= TOLERANCIA_GLIFO_PT
            else ""
        )
        valor = _interpretar_numero(texto)
        if valor is not None and (melhor is None or np.mean(distancias) < melhor[0]):
            melhor = (float(np.mean(distancias)), valor)
    return (
        {"centro_pt": pontos.mean(0), "candidatos": {melhor[1]: VOTOS_ALFABETO}}
        if melhor
        else None
    )


def ler_rotulos(grupos: list[list[dict]], ocr=ler_rotulo) -> list[dict]:
    """Leituras de todos os rótulos: OCR em cada um (`ocr`, injetável), equidistância do que o OCR leu, alfabeto
    aprendido com as leituras múltiplas dela, e a leitura pelo alfabeto somada (`VOTOS_ALFABETO`) ao OCR; o rótulo que
    o OCR não leu sai só pelo alfabeto."""
    lidas = [(g, ocr(g)) for g in grupos]
    do_ocr = [r for _, r in lidas if r]
    alfabeto = aprender_alfabeto(do_ocr, estimar_passo(do_ocr))
    saida = []
    for g, r in lidas:
        d = decodificar_rotulo(g, alfabeto)
        candidatos = collections.Counter(r["candidatos"] if r else {})
        candidatos.update(d["candidatos"] if d else {})
        if candidatos:
            saida.append(
                {"centro_pt": (r or d)["centro_pt"], "candidatos": dict(candidatos)}
            )
    return saida


def _multiplo(valor: float, passo: float) -> bool:
    return abs(valor / passo - round(valor / passo)) * passo <= 0.01


def estimar_passo(leituras: list[dict]) -> float | None:
    """Equidistância lida dos rótulos. Com rótulos de cota fracionária, vale o maior passo (< 1 m) de que
    `FRACAO_DECIMAIS_MINIMA` deles têm alguma leitura candidata múltipla: a curva de 1 m (mestra) é a maioria, mas só
    os rótulos fracionários distinguem 0,5 de 1. Sem fracionários, o maior passo de `PASSOS_EQUIDISTANCIA_M` de que
    `FRACAO_MULTIPLOS_MINIMA` dos rótulos têm candidata múltipla (o OCR erra um dígito, não todas as leituras)."""
    if not leituras:
        return None
    fracionarios = [r for r in leituras if any(c % 1 > 0.01 for c in r["candidatos"])]
    alvo, minimo = (
        (fracionarios, FRACAO_DECIMAIS_MINIMA)
        if fracionarios
        else (leituras, FRACAO_MULTIPLOS_MINIMA)
    )
    for passo in PASSOS_EQUIDISTANCIA_M:
        if fracionarios and passo >= 1.0:
            continue
        if (
            np.mean([any(_multiplo(c, passo) for c in r["candidatos"]) for r in alvo])
            >= minimo
        ):
            return passo
    return None


def rotulos_coerentes(
    leituras: list[dict], passo_m: float | None
) -> tuple[list[dict], list[str]]:
    """Cota de cada rótulo: a mais votada que for múltipla do passo (a de maior cota-vizinha em empate não existe:
    desempate pelo menor valor). Rótulo sem leitura coerente sai da lista, com alerta."""
    saida, alertas = [], []
    for r in leituras:
        ordem = sorted(r["candidatos"].items(), key=lambda kv: (-kv[1], kv[0]))
        escolha = [c for c, _ in ordem if passo_m is None or _multiplo(c, passo_m)]
        if escolha:
            saida.append({"centro_pt": r["centro_pt"], "cota_m": escolha[0]})
        else:
            alertas.append(
                f"rótulo em {np.round(r['centro_pt'], 0).tolist()} pt descartado: {r['candidatos']}"
            )
    return saida, alertas


# --- cota de cada curva ----------------------------------------------------------------------------------------------
def _dist_ao_traco(ponto: np.ndarray, pontos: np.ndarray) -> float:
    """Menor distância do ponto a uma polilinha (segmentos), em pt."""
    a, b = pontos[:-1], pontos[1:]
    ab = b - a
    t = np.clip(((ponto - a) * ab).sum(1) / np.maximum((ab * ab).sum(1), 1e-12), 0, 1)
    return float(np.linalg.norm(a + t[:, None] * ab - ponto, axis=1).min())


def _curvas_do_rotulo(
    centro: np.ndarray, curvas: list[dict]
) -> list[tuple[int, float]]:
    """Curvas que o rótulo data: com ponta perto (ponta mais perta e as até `FATOR_PONTA_MAIS_PERTO` vezes isso, até
    `RAIO_ROTULO_PT`); sem ponta perto, a curva contínua mais próxima a até `RAIO_ROTULO_SOBRE_CURVA_PT`."""
    pontas = np.array(
        [min(np.linalg.norm(c["pontos_pt"][[0, -1]] - centro, axis=1)) for c in curvas],
        float,
    )
    if pontas.min() <= RAIO_ROTULO_PT:
        limite = min(RAIO_ROTULO_PT, FATOR_PONTA_MAIS_PERTO * pontas.min())
        return [(i, float(d)) for i, d in enumerate(pontas) if d <= limite]
    d = np.array([_dist_ao_traco(centro, c["pontos_pt"]) for c in curvas])
    return (
        [(int(np.argmin(d)), float(d.min()))]
        if d.min() <= RAIO_ROTULO_SOBRE_CURVA_PT
        else []
    )


def atribuir_cotas(curvas: list[dict], rotulos: list[dict]) -> list[dict]:
    """Cota da curva pelo rótulo mais próximo. Curva com rótulos de cotas diferentes fica com o mais perto e alerta.
    Preenche `cota_m`, `origem` ('rotulo' ou None) e `alertas` em cada curva."""
    votos: dict[int, list[tuple[float, float]]] = collections.defaultdict(list)
    for r in rotulos:
        for i, d in _curvas_do_rotulo(r["centro_pt"], curvas):
            votos[i].append((d, r["cota_m"]))
    for i, c in enumerate(curvas):
        c["alertas"] = []
        if i not in votos:
            c.update(cota_m=None, origem=None)
            continue
        d, cota = min(votos[i])
        c.update(cota_m=cota, origem="rotulo")
        if len({v[1] for v in votos[i]}) > 1:
            c["alertas"].append(
                f"rótulos conflitantes {sorted({v[1] for v in votos[i]})}: vale o mais perto"
            )
    return curvas


def modelo_tin(curvas: list[dict], pontos_cotados: np.ndarray | None = None):
    """TIN linear (`scipy.interpolate.LinearNDInterpolator`) das curvas com cota, em UTM; NaN fora do casco convexo.
    `pontos_cotados` opcional: array (N, 3) E, N, cota."""
    from scipy.interpolate import LinearNDInterpolator

    xyz = [_pontos_da_curva(c) for c in curvas if c.get("cota_m") is not None]
    if pontos_cotados is not None:
        xyz.append(np.asarray(pontos_cotados, float).reshape(-1, 3))
    if not xyz:
        raise ValueError("sem curvas com cota: o TIN não pode ser montado")
    pts = np.vstack(xyz)
    pts = pts[
        np.unique(pts[:, :2].round(3), axis=0, return_index=True)[1]
    ]  # um z por posição
    return LinearNDInterpolator(pts[:, :2], pts[:, 2])


def _densificar(xy: np.ndarray, passo: float) -> np.ndarray:
    """Pontos da polilinha com espaçamento ≤ `passo` (vértices originais incluídos)."""
    seg = np.linalg.norm(np.diff(xy, axis=0), axis=1)
    n = np.maximum(np.ceil(seg / passo).astype(int), 1)
    partes = [
        xy[i] + (xy[i + 1] - xy[i]) * (np.arange(k) / k)[:, None]
        for i, k in enumerate(n)
    ]
    return np.vstack(partes + [xy[-1:]])


def _pontos_da_curva(c: dict) -> np.ndarray:
    xy = _densificar(np.asarray(c["coords_utm"], float), ESPACAMENTO_PONTOS_M)
    return np.c_[xy, np.full(len(xy), float(c["cota_m"]))]


def inferir_cotas(curvas: list[dict], passo_m: float | None) -> list[dict]:
    """Curva sem rótulo: cota = mediana da interpolação (TIN das datadas) arredondada ao passo, aceita se a mediana
    e o desvio ficam a até `INFERENCIA_TOLERANCIA_REL` × passo. Repete `INFERENCIA_RODADAS` vezes. `origem` 'inferida'
    e alerta. Sem passo ou sem curva datada, nada muda."""
    from scipy.spatial import QhullError

    if passo_m is None:
        return curvas
    for _ in range(INFERENCIA_RODADAS):
        pendentes = [c for c in curvas if c["cota_m"] is None]
        if not pendentes or all(c["cota_m"] is None for c in curvas):
            break
        try:
            tin = modelo_tin(curvas)
        except QhullError:  # curvas datadas alinhadas ou poucas: não há TIN
            break
        mudou = False
        for c in pendentes:
            z = tin(_densificar(np.asarray(c["coords_utm"], float), 5.0))
            z = z[np.isfinite(z)]
            if len(z) < 3:
                continue
            candidata = round(float(np.median(z)) / passo_m) * passo_m
            tol = INFERENCIA_TOLERANCIA_REL * passo_m
            if abs(float(np.median(z)) - candidata) <= tol and float(z.std()) <= tol:
                c.update(cota_m=round(candidata, 3), origem="inferida")
                c["alertas"].append(
                    f"cota {candidata:.2f} m inferida pela vizinhança (mediana {np.median(z):.2f}, desvio {z.std():.2f})"
                )
                mudou = True
        if not mudou:
            break
    return curvas


def curvas_dos_tracos(tracos: list[dict], M, ler=ler_rotulos) -> list[dict]:
    """Curvas de nível em UTM a partir dos traços de uma prancha: separa, lê rótulos (`ler(grupos)`, injetável), data as
    curvas, infere as sem rótulo e converte pela afim `M` (pt → UTM). Devolve [{cota_m, coords_utm, layer, origem,
    alertas}]."""
    curvas, glifos = separar_tracos(tracos)
    leituras = ler(agrupar_glifos(glifos))
    passo = estimar_passo(leituras)
    rotulos, alertas_rotulos = rotulos_coerentes(leituras, passo)
    if not curvas:
        return []
    atribuir_cotas(curvas, rotulos)
    for c in curvas:
        c["coords_utm"] = _para_utm(c["pontos_pt"], M).round(3).tolist()
    inferir_cotas(curvas, passo)
    for c in curvas:
        c.pop("pontos_pt")
        c["passo_lido_m"] = passo
        c["alertas_prancha"] = alertas_rotulos
    return curvas


def curvas_de_nivel(pdf: str | Path, M, clip=None) -> list[dict]:
    """Curvas de nível de uma prancha PDF vetorial, cada uma com a sua cota: [{cota_m, coords_utm, layer, origem,
    alertas}]. `M`: afim pt → UTM (2×3 ou 3×3); `clip`: janela [x0, y0, x1, y1] em pt (planta com dois desenhos).
    `cota_m` None = curva sem cota. Exige pymupdf, tesseract e scipy."""
    return curvas_dos_tracos(pdf_cad.extrair(pdf, clip=clip), M)


def resumir_curvas(curvas: list[dict]) -> dict:
    """Equidistância lida (passo mais frequente entre as cotas distintas), contagens por origem e curvas sem cota."""
    cotas = sorted({c["cota_m"] for c in curvas if c["cota_m"] is not None})
    passos = collections.Counter(np.round(np.diff(cotas), 3).tolist())
    por_origem = collections.Counter(c["origem"] or "sem_cota" for c in curvas)
    return {
        "n_curvas": len(curvas),
        "n_com_cota_por_rotulo": por_origem.get("rotulo", 0),
        "n_com_cota_inferida": por_origem.get("inferida", 0),
        "n_sem_cota": por_origem.get("sem_cota", 0),
        "equidistancia_m": passos.most_common(1)[0][0] if passos else None,
        "passos_entre_cotas_m": dict(passos),
        "cotas_m": cotas,
        "comprimento_sem_cota_m": round(
            sum(_comprimento(c) for c in curvas if c["cota_m"] is None), 1
        ),
    }


def _comprimento(c: dict) -> float:
    return float(
        np.linalg.norm(
            np.diff(np.asarray(c["coords_utm"], float), axis=0), axis=1
        ).sum()
    )


# --- superfície ------------------------------------------------------------------------------------------------------
def _centros(g: dict) -> tuple[np.ndarray, np.ndarray]:
    """E das colunas e N das linhas (centros das células) da grade do MDS."""
    col = g["e0"] + (np.arange(g["forma"][1]) + 0.5) * g["res"]
    lin = g["n1"] - (np.arange(g["forma"][0]) + 0.5) * g["res"]
    return col, lin


def superficie(
    curvas: list[dict], g: dict, pontos_cotados: np.ndarray | None = None, tin=None
) -> np.ndarray:
    """Superfície topográfica na grade do MDS (`g`: e0, n1, res, forma): TIN linear das curvas (mais pontos cotados
    opcionais); NaN fora do casco convexo. Devolve float32 (linhas × colunas)."""
    tin = tin or modelo_tin(curvas, pontos_cotados)
    col, lin = _centros(g)
    saida = np.full(g["forma"], np.nan, np.float32)
    for i in range(0, len(lin), 64):  # em blocos de linhas: memória limitada
        bloco = lin[i : i + 64]
        e, n = np.meshgrid(col, bloco)
        saida[i : i + 64] = tin(e, n)
    return saida


def amostrar_grade(grade: np.ndarray, g: dict, xy: np.ndarray) -> np.ndarray:
    """Valor da grade em pontos UTM (interpolação bilinear entre centros de célula); NaN fora ou sobre NaN."""
    xy = np.asarray(xy, float).reshape(-1, 2)
    c = (xy[:, 0] - g["e0"]) / g["res"] - 0.5
    r = (g["n1"] - xy[:, 1]) / g["res"] - 0.5
    c0, r0 = np.floor(c).astype(int), np.floor(r).astype(int)
    fc, fr = c - c0, r - r0
    dentro = (c0 >= 0) & (c0 + 1 < g["forma"][1]) & (r0 >= 0) & (r0 + 1 < g["forma"][0])
    c0, r0 = np.clip(c0, 0, g["forma"][1] - 2), np.clip(r0, 0, g["forma"][0] - 2)
    z = (
        grade[r0, c0] * (1 - fc) * (1 - fr)
        + grade[r0, c0 + 1] * fc * (1 - fr)
        + grade[r0 + 1, c0] * (1 - fc) * fr
        + grade[r0 + 1, c0 + 1] * fc * fr
    )
    return np.where(dentro, z, np.nan)


def estatisticas(dif: np.ndarray, area_celula_m2: float | None = None) -> dict:
    """Média, desvio, rms, mínimo/máximo e percentis (m) de uma diferença; ignora NaN."""
    d = np.asarray(dif, float)
    d = d[np.isfinite(d)]
    if not len(d):
        return {"n": 0}
    p = np.percentile(d, PERCENTIS)
    saida = {
        "n": len(d),
        "media_m": float(d.mean()),
        "desvio_m": float(d.std()),
        "rms_m": float(np.sqrt((d**2).mean())),
        "minimo_m": float(d.min()),
        "maximo_m": float(d.max()),
        **{f"p{q}_m": float(v) for q, v in zip(PERCENTIS, p)},
    }
    if area_celula_m2:
        saida["area_m2"] = float(len(d) * area_celula_m2)
    return saida


# --- (a) e (d): sondagens --------------------------------------------------------------------------------------------
def _linha_do_furo(
    f: dict, boca: float, topo: float, mds: float, ponto: dict, variante: bool
) -> dict:
    """Linha da tabela (a)+(d) de um furo; `ponto` = registro do furo em `ajuste_vertical.json` (vazio se não houver)."""
    return {
        "id": f["id"],
        "variante_de_outro_furo": variante,
        "E": f["E"],
        "N": f["N"],
        "cota_boca_m": boca,
        "topografia_m": _ou_none(topo),
        "topografia_menos_boca_m": _ou_none(topo - boca),
        "mds_m": _ou_none(mds),
        "mds_menos_boca_m": _ou_none(mds - boca),
        "mds_menos_topografia_m": _ou_none(mds - topo),
        "residuo_ajuste_m": ponto.get("residuo_m"),
        "usado_no_plano": (not ponto.get("descartado"))
        and ponto.get("z_nuvem") is not None
        if ponto
        else None,
    }


def comparar_sondagens(
    tin, furos: list[dict], g: dict | None = None, ajuste: dict | None = None
) -> dict:
    """(a) topografia × cota de boca de cada furo, e (d) MDS × cota de boca na mesma tabela.

    Por furo: cota de boca, cota da topografia (TIN, no ponto), diferença; se `g` (com `terreno`), o MDS no ponto;
    se `ajuste` (`ajuste_vertical.json`), o resíduo do plano e se o furo foi usado. O furo fora do casco do TIN fica
    com a topografia None e não entra nas estatísticas, e a variante 'A' de um furo (mesma boca) não conta duas
    vezes."""
    xy = np.array([[f["E"], f["N"]] for f in furos], float)
    boca = np.array([f["cota_boca"] for f in furos], float)
    topo = np.asarray(tin(xy[:, 0], xy[:, 1]), float)
    mds = (
        amostrar_grade(g["terreno"], g, xy)
        if g is not None
        else np.full(len(furos), np.nan)
    )
    pontos = {p["id"]: p for p in (ajuste or {}).get("pontos", [])}
    ids = {f["id"] for f in furos}
    variante = np.array(
        [f["id"].endswith("A") and f["id"][:-1] in ids for f in furos]
    )  # SP02A repete SP02
    linhas = [
        _linha_do_furo(
            f,
            float(boca[i]),
            topo[i],
            mds[i],
            pontos.get(f["id"], {}),
            bool(variante[i]),
        )
        for i, f in enumerate(furos)
    ]
    residuos = [
        r["residuo_ajuste_m"]
        for r in linhas
        if r["usado_no_plano"] and r["residuo_ajuste_m"] is not None
    ]
    return {
        "furos": linhas,
        "topografia_menos_boca": estatisticas((topo - boca)[~variante]),
        "mds_menos_boca": estatisticas((mds - boca)[~variante]),
        "mds_menos_boca_nos_furos_dentro_da_topografia": estatisticas(
            (mds - boca)[~variante & np.isfinite(topo)]
        ),
        "mds_menos_topografia_nos_furos": estatisticas((mds - topo)[~variante]),
        "residuo_ajuste_usados_m": estatisticas(np.array(residuos)),
        "rms_validacao_cruzada_m": (ajuste or {}).get("rms_validacao_cruzada_m"),
    }


def _ou_none(x) -> float | None:
    return float(x) if np.isfinite(x) else None


# --- (b): seções de corte --------------------------------------------------------------------------------------------
def perfil_da_linha(tin, linha: dict, passo_m: float = PASSO_PERFIL_M) -> np.ndarray:
    """Topografia ao longo da linha de seção (UTM): [[s_m, cota_m]] nas amostras dentro do casco do TIN."""
    ini, fim = (
        np.asarray(linha["inicio_utm"], float),
        np.asarray(linha["fim_utm"], float),
    )
    comprimento = float(np.linalg.norm(fim - ini))
    n = max(round(comprimento / passo_m), 1)
    s = (np.arange(n) + 0.5) * comprimento / n
    xy = ini + (fim - ini) * (s / max(comprimento, 1e-9))[:, None]
    z = np.asarray(tin(xy[:, 0], xy[:, 1]), float)
    return np.c_[s, z][np.isfinite(z)]


def secoes_quebradas(alertas: list[str]) -> set[str]:
    """Nomes das seções cuja linha de planta é quebrada, pelos alertas de `conferencia_cavas` ('seção CC: segmentos não
    colineares ...'): um perfil reto não representa essas linhas."""
    return {
        m[1]
        for a in alertas
        if (m := re.match(r"seção (\w+): segmentos não colineares", a))
    }


def _secao_comparada(tin, sec: dict, linha: dict, mds: dict, quebrada: bool) -> dict:
    """Uma linha da tabela (b): topografia − seção (alinhada), com a diferença MDS − seção ao lado."""
    from . import conferencia_cavas as cc

    reg = {"secao": linha["secao"], "prancha": linha.get("prancha")}
    perfil = perfil_da_linha(tin, linha)
    if len(perfil) < 4:
        return {**reg, "motivo": "linha fora do casco da topografia"}
    r = cc.comparar_terreno(
        sec["terreno"], perfil.tolist(), PASSO_PERFIL_M, cc.corte_x_do_projeto(sec)
    )
    conferida = mds.get(linha["secao"], {})
    terreno_mds = conferida.get("terreno") or {}
    return {
        **reg,
        "linha_quebrada": quebrada,
        "fracao_da_linha_na_topografia": float(
            len(perfil) * PASSO_PERFIL_M / linha["comprimento_m"]
        ),
        "topografia_menos_secao_m": r and r["dif_media_m"],
        "desvio_m": r and r["desvio_m"],
        "sentido": r and r["sentido"],
        "deslocamento_m": r and r["deslocamento_m"],
        "mds_menos_secao_m": terreno_mds.get(
            "dif_media_m", conferida.get("dif_terreno_m")
        ),
        "mds_desvio_m": terreno_mds.get("desvio_m"),
        "mds_situacao": conferida.get("motivo") or conferida.get("situacao"),
    }


def comparar_secoes(
    tin,
    secoes: list[dict],
    linhas: list[dict],
    conferidas: list[dict] | None = None,
    quebradas: set[str] | None = None,
) -> dict:
    """(b) topografia × TERRENO ORIGINAL das seções de corte, ao longo das linhas de seção da planta.

    O perfil da topografia desliza sobre o da seção nos dois sentidos (`conferencia_cavas.comparar_terreno`, o mesmo
    alinhamento do MDS); a diferença é topografia − seção, só no trecho do corte quando ele existe. `conferidas`
    (saída de `conferencia_cavas`) põe ao lado a diferença MDS − seção. Linha de planta quebrada (`quebradas`, de
    `secoes_quebradas`) fica na tabela e fora das estatísticas; sem seção correspondente, sai com o motivo. Em
    terreno quase plano o alinhamento é pouco determinado, mas a diferença média quase não depende dele."""
    mds = {c["secao"]: c for c in (conferidas or [])}
    por_nome = {s["secao"]: s for s in secoes if s.get("terreno")}
    tabela = []
    for linha in linhas:
        sec = por_nome.get(linha["secao"])
        if sec is None:
            tabela.append(
                {
                    "secao": linha["secao"],
                    "prancha": linha.get("prancha"),
                    "motivo": "sem seção de corte com esse nome",
                }
            )
        else:
            tabela.append(
                _secao_comparada(
                    tin, sec, linha, mds, linha["secao"] in (quebradas or set())
                )
            )
    validas = [
        r
        for r in tabela
        if r.get("topografia_menos_secao_m") is not None and not r["linha_quebrada"]
    ]
    do_mds = [
        r["mds_menos_secao_m"] for r in validas if r["mds_menos_secao_m"] is not None
    ]
    return {
        "secoes": tabela,
        "topografia_menos_secao": estatisticas(
            np.array([r["topografia_menos_secao_m"] for r in validas])
        ),
        "mds_menos_secao": estatisticas(np.array(do_mds)),
        "n_linhas": len(linhas),
        "n_comparadas": len(validas),
    }


# --- (c): MDS × topografia em toda a área válida ---------------------------------------------------------------------
def _base_da_tendencia(
    x: np.ndarray, y: np.ndarray, grau: int
) -> tuple[np.ndarray, list[str], list[float]]:
    """Matriz do ajuste (1, x, y [, x², xy, y²]), nomes dos coeficientes e fator que os volta para m, m/m e m/m²."""
    k = 1 / ESCALA_TENDENCIA_M
    colunas, nomes, fator = (
        [np.ones_like(x), x, y],
        ["a_m", "b_e_m_por_m", "b_n_m_por_m"],
        [1.0, k, k],
    )
    if grau == 2:
        colunas += [x * x, x * y, y * y]
        nomes += ["c_ee_m_por_m2", "c_en_m_por_m2", "c_nn_m_por_m2"]
        fator += [k * k] * 3
    return np.stack(colunas, axis=1), nomes, fator


def ajustar_tendencia(
    e: np.ndarray,
    n: np.ndarray,
    erro: np.ndarray,
    grau: int,
    aparar_mad: float | None = None,
) -> dict:
    """Ajuste por mínimos quadrados do erro em E, N: grau 1 (plano) ou 2 (quadrática). E, N são centrados na média e
    divididos por `ESCALA_TENDENCIA_M`; os coeficientes voltam em m, m/m e m/m². Dá também o rms antes e depois, a
    amplitude da superfície ajustada na área e, na quadrática, a curvatura (autovalores: ambos negativos = cúpula).
    Com `aparar_mad`, repete `RODADAS_APARAR` vezes descartando as amostras a mais de `aparar_mad` desvios-MAD do
    ajuste (objetos acima do chão não puxam a forma do terreno); rms e variância valem só para as amostras mantidas."""
    e0, n0 = float(e.mean()), float(n.mean())
    A, nomes, fator = _base_da_tendencia(
        (e - e0) / ESCALA_TENDENCIA_M, (n - n0) / ESCALA_TENDENCIA_M, grau
    )
    usado = np.ones(len(erro), bool)
    for _ in range(RODADAS_APARAR if aparar_mad else 1):
        coef, *_ = np.linalg.lstsq(A[usado], erro[usado], rcond=None)
        residuo = erro - A @ coef
        if aparar_mad:
            centro = np.median(residuo[usado])
            mad = 1.4826 * np.median(np.abs(residuo[usado] - centro))
            usado = np.abs(residuo - centro) <= aparar_mad * mad
    ajustado, z = A @ coef, erro[usado]
    variancia = ((z - z.mean()) ** 2).sum()
    saida = {
        "grau": grau,
        "centro_utm": [e0, n0],
        "coeficientes": {k: float(v * f) for k, v, f in zip(nomes, coef, fator)},
        "n_usado": int(usado.sum()),
        "rms_antes_m": float(np.sqrt((z**2).mean())),
        "rms_depois_m": float(np.sqrt(((residuo[usado]) ** 2).mean())),
        "amplitude_ajustada_m": float(ajustado.max() - ajustado.min()),
        "variancia_explicada": float(1 - (residuo[usado] ** 2).sum() / variancia)
        if variancia > 0
        else None,
    }
    if grau == 2:
        c = saida["coeficientes"]
        hessiana = np.array(
            [
                [2 * c["c_ee_m_por_m2"], c["c_en_m_por_m2"]],
                [c["c_en_m_por_m2"], 2 * c["c_nn_m_por_m2"]],
            ]
        )
        autovalores = np.linalg.eigvalsh(hessiana)
        saida["curvatura_autovalores_m_por_m2"] = autovalores.tolist()
        saida["forma"] = (
            "cúpula"
            if autovalores.max() < 0
            else "bacia"
            if autovalores.min() > 0
            else "sela"
        )
    return saida


def distancia_aos_pontos(g: dict, pontos_xy: np.ndarray) -> np.ndarray:
    """Distância (m) de cada célula da grade ao ponto mais próximo; em blocos de linhas."""
    col, lin = _centros(g)
    saida = np.empty(g["forma"], np.float32)
    for i in range(0, len(lin), 64):
        e, n = np.meshgrid(col, lin[i : i + 64])
        d = np.hypot(e[..., None] - pontos_xy[:, 0], n[..., None] - pontos_xy[:, 1])
        saida[i : i + 64] = d.min(-1)
    return saida


def por_grupo(erro: np.ndarray, rotulo: np.ndarray, nomes: dict, res: float) -> dict:
    """Estatísticas do erro por grupo (`rotulo` inteiro por célula; `nomes` {código: nome})."""
    return {
        nome: estatisticas(erro[rotulo == k], res * res)
        for k, nome in nomes.items()
        if (rotulo == k).any()
    }


def classes_de_cobertura(g: dict, vegetacao: dict, cor_bgr: np.ndarray) -> np.ndarray:
    """Cobertura por célula (índice em `CLASSES`): edificação (grade do MDS) > vegetação alta > grama (rasteira) >
    solo > pavimento, com as máscaras de `supressao.mascaras_vegetacao` e a regra de cor de `valas` (a mesma da
    classe de superfície das valas, vetorizada). `cor_bgr`: ortofoto na grade do MDS."""
    from .valas import REGRAS

    r = REGRAS["ortofoto"]
    b, _, rr = [cor_bgr[..., k].astype(np.float32) for k in range(3)]
    v = cor_bgr.max(-1).astype(np.float32)
    s = (v - cor_bgr.min(-1)) / (v + 1)
    solo = (s >= r["terra_s_min"]) & (v <= r["terra_v_max"]) & (rr > b)
    classe = np.full(g["forma"], CLASSES.index("pavimento"), np.uint8)
    classe[solo] = CLASSES.index("solo")
    classe[vegetacao["rasteira"]] = CLASSES.index("grama")
    classe[vegetacao["alta"]] = CLASSES.index("vegetacao")
    classe[g["edificacao"]] = CLASSES.index("edificacao")
    classe[~g["valido"]] = CLASSES.index("sem_classe")
    return classe


def classes_de_ortofoto(g: dict, ortofoto: Path, mds_png: Path) -> np.ndarray:
    """Cobertura de cada célula da grade do MDS (`classes_de_cobertura`) a partir da ortofoto e do MDS em arquivo."""
    from . import supressao

    veg = supressao.mascaras_vegetacao(ortofoto, mds_png, res=g["res"])
    cor, *_ = supressao._raster_orto(Path(ortofoto), g["res"])
    return classes_de_cobertura(g, veg, cor)


def _tendencias(
    g: dict, erro: np.ndarray, mascara: np.ndarray, aparar_mad: float | None
) -> dict:
    """Plano e quadrática do erro nas células da máscara (passo regular até `MAX_AMOSTRAS_TENDENCIA` amostras)."""
    col, lin = _centros(g)
    li, ci = np.nonzero(mascara)
    passo = max(1, len(li) // MAX_AMOSTRAS_TENDENCIA)
    li, ci = li[::passo], ci[::passo]
    e, n, z = col[ci], lin[li], erro[li, ci]
    return {
        "n_amostras": len(z),
        "plano": ajustar_tendencia(e, n, z, 1, aparar_mad),
        "quadratica": ajustar_tendencia(e, n, z, 2, aparar_mad),
    }


def comparar_mds(
    g: dict,
    topografia: np.ndarray,
    pontos_usados: np.ndarray,
    classe: np.ndarray | None = None,
) -> dict:
    """(c) MDS (`g['terreno']`, o que entra no volume) × topografia, em toda a área válida: estatísticas, tendência
    espacial (plano e quadrática em E, N), erro por cobertura e por distância aos furos usados no plano. Erro = MDS −
    topografia. A tendência sai de três formas: em toda a área (mínimos quadrados), sem edificação e, com a
    cobertura, só no terreno aberto (grama, pavimento, solo; ajuste aparado em `APARAR_MAD` MAD), onde a forma do
    terreno não se confunde com objetos. Devolve também `erro` (grade) para o mapa."""
    valido = g["valido"] & np.isfinite(topografia) & np.isfinite(g["terreno"])
    erro = np.where(valido, g["terreno"].astype(np.float64) - topografia, np.nan)
    sem_edif = valido & ~g["edificacao"]
    aberto = sem_edif
    saida = {
        "toda_area_valida": estatisticas(erro[valido], g["res"] ** 2),
        "sem_edificacao": estatisticas(erro[sem_edif], g["res"] ** 2),
        "tendencia": {"toda_area": _tendencias(g, erro, valido, None)},
    }
    if classe is not None:
        aberto = valido & np.isin(
            classe, [CLASSES.index(c) for c in CLASSES_TERRENO_ABERTO]
        )
        saida["por_cobertura"] = por_grupo(
            np.where(valido, erro, np.nan), classe, dict(enumerate(CLASSES)), g["res"]
        )
    saida["terreno_aberto"] = estatisticas(erro[aberto], g["res"] ** 2)
    saida["tendencia"]["terreno_aberto_aparada"] = _tendencias(
        g, erro, aberto, APARAR_MAD
    )
    faixa = np.digitize(
        distancia_aos_pontos(g, pontos_usados), FAIXAS_DISTANCIA_M[1:-1]
    )
    nomes = {
        k: f"{FAIXAS_DISTANCIA_M[k]:.0f}–{FAIXAS_DISTANCIA_M[k + 1]:.0f} m"
        for k in range(len(FAIXAS_DISTANCIA_M) - 1)
    }
    saida["por_distancia_aos_furos_usados_terreno_aberto"] = por_grupo(
        np.where(aberto, erro, np.nan), faixa, nomes, g["res"]
    )
    saida["erro"] = erro
    return saida


def mapa_do_erro(
    erro: np.ndarray,
    g: dict,
    furos: list[dict],
    caminho: Path,
    limite_m: float = LIMITE_MAPA_M,
) -> Path:
    """PNG do erro (MDS − topografia) a `ESCALA_PNG` px por célula: azul = MDS abaixo, vermelho = acima, branco = sem
    dado; furos como círculos (cheio = usado no plano) e faixa de legenda no topo. Desenhado aqui; o HTML só mostra
    a imagem."""
    t = np.clip((np.nan_to_num(erro) / limite_m + 1) / 2, 0, 1)
    azul, vermelho = np.array([200, 90, 30]), np.array([40, 40, 210])  # BGR
    cor = np.where(
        t[..., None] < 0.5,
        255 - (255 - azul) * (1 - 2 * t)[..., None],
        255 - (255 - vermelho) * (2 * t - 1)[..., None],
    ).astype(np.uint8)
    cor[~np.isfinite(erro)] = 255
    cor = cv2.resize(
        cor, None, fx=ESCALA_PNG, fy=ESCALA_PNG, interpolation=cv2.INTER_NEAREST
    )
    faixa = np.full((36, cor.shape[1], 3), 255, np.uint8)
    cv2.putText(
        faixa,
        f"MDS - topografia (m): azul = -{limite_m:g}, vermelho = +{limite_m:g}. Circulo cheio = furo usado no plano",
        (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
    )  # fmt: skip
    for f in furos:
        if f.get("variante_de_outro_furo"):
            continue
        c, r = (
            int((f["E"] - g["e0"]) / g["res"] * ESCALA_PNG),
            int((g["n1"] - f["N"]) / g["res"] * ESCALA_PNG),
        )
        cv2.circle(cor, (c, r), 6, (0, 0, 0), -1 if f.get("usado_no_plano") else 2)
        cv2.putText(
            cor,
            f["id"],
            (c + 8, r - 6),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(caminho), np.vstack([faixa, cor]))
    return Path(caminho)


def comparar(
    g: dict,
    curvas: list[dict],
    furos: list[dict],
    ajuste: dict,
    secoes: list[dict] | None = None,
    linhas: list[dict] | None = None,
    conferencia: dict | None = None,
    ortofoto_e_mds: tuple[Path, Path] | None = None,
    caminho_mapa: Path | None = None,
) -> dict:
    """Relatório completo (a)–(d). `g`: grade do MDS (`escavacao.grade`); `curvas`: `curvas_de_nivel`; `furos`:
    `dados/foz/geotec/sondagens.json["furos"]`; `ajuste`: `ajuste_vertical.json`; `secoes`: `secoes_corte.ler_secoes`;
    `linhas`: linhas de seção em UTM; `conferencia`: `conferencia_cavas.json` (MDS × seção ao lado e seções quebradas);
    `ortofoto_e_mds`: (ortofoto, MDS em PNG) para a cobertura (`classes_de_ortofoto`); sem ele, o erro não sai por cobertura. Tudo em dicionário (JSON)."""
    tin = modelo_tin(curvas)
    topografia = superficie(curvas, g, tin=tin)
    usados = np.array(
        [
            [p["E"], p["N"]]
            for p in ajuste["pontos"]
            if not p.get("descartado") and p.get("z_nuvem") is not None
        ],
        float,
    )
    conferencia = conferencia or {}
    classe = classes_de_ortofoto(g, *ortofoto_e_mds) if ortofoto_e_mds else None
    sondagens = comparar_sondagens(tin, furos, g, ajuste)
    mds = comparar_mds(g, topografia, usados, classe)
    erro = mds.pop("erro")
    if caminho_mapa is not None:
        mapa_do_erro(erro, g, sondagens["furos"], caminho_mapa)
    quebradas = secoes_quebradas(conferencia.get("alertas", []))
    return {
        "curvas": resumir_curvas(curvas),
        "a_e_d_sondagens": sondagens,
        "b_secoes": comparar_secoes(
            tin, secoes or [], linhas or [], conferencia.get("secoes"), quebradas
        ),
        "c_mds_x_topografia": mds,
        "cobertura_da_topografia_m2": float(
            np.isfinite(topografia).sum() * g["res"] ** 2
        ),
    }


def gravar(relatorio: dict, caminho: Path) -> Path:
    """Grava o relatório em JSON (UTF-8)."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=1, default=float),
        encoding="utf-8",
    )
    return caminho
