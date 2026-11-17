"""Leitura de forma estrutural (pranchas PBES, PDF vetorial de CAD) como geometria em pt da folha.

Primitivas para depois virar sólido 3D: áreas preenchidas por layer e cor, união de pedaços,
polígono sem furos, vigas como pares de traços paralelos, alinhamento folha → folha (pontos, linhas e
retângulo comum) e escora como prismas verticais. Tudo determinístico; unidades em pt da folha, exceto
`prismas_inclinados` (m).
"""

from __future__ import annotations

import csv
import itertools
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, LineString, Polygon, box
from shapely.ops import polygonize, unary_union

FRACAO_MINIMA_RECT = (
    0.4  # área do caminho / área do rect abaixo disso: caminho fora de ordem
)
RESOLUCAO_HIST_PT = 0.5  # passo do histograma de linhas
COMPRIMENTO_EIXO_PT = (
    30.0  # traço mais curto que isso não entra na correlação de linhas
)
BUFFER_BLOCO_M = (
    0.6  # "z0_pelos_blocos": o elemento enxerga os blocos a até 0,6 m (UTM)
)
BUFFER_DESCONTO_PT = 1.0  # "descontar_blocos": folga em volta do bloco, em pt da folha
AREA_MINIMA_ELEMENTO_M2 = (
    1e-3  # sobra de recorte menor que isso (10 cm²) não vira elemento
)
REDONDEZA_ESTACA = 0.1  # círculo: |largura − altura| ≤ 10 % da largura


def _pagina(pdf):
    """Primeira página do PDF (pymupdf importado aqui: extra `pdf`)."""
    import pymupdf

    return pymupdf.open(pdf)[0]


def _dentro(rect, regiao_pt) -> bool:
    x0, y0, x1, y1 = regiao_pt
    return x0 <= rect.x0 and rect.x1 <= x1 and y0 <= rect.y0 and rect.y1 <= y1


def _poligono_do_desenho(desenho) -> Polygon | None:
    """Polígono de um desenho preenchido: `re`, `qu` ou caminho de `l` (cai no `rect` se sair fora de ordem)."""
    pontos, ultimo = [], None
    for item in desenho["items"]:
        if item[0] == "re":
            return box(*item[1])
        if item[0] == "qu":
            q = item[1]
            return Polygon(
                [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)]
            )
        if item[0] == "l":
            pontos.append((item[1].x, item[1].y))
            ultimo = (item[2].x, item[2].y)
    if len(pontos) < 2:
        return None
    poligono = Polygon([*pontos, ultimo]).buffer(0)
    r = desenho["rect"]
    if poligono.is_empty or poligono.area < FRACAO_MINIMA_RECT * r.width * r.height:
        return box(*r)
    return poligono


def preenchidos(pdf, chaves, regiao_pt) -> dict:
    """{(layer, cor): [Polygon]} das áreas preenchidas dentro de `regiao_pt` (x0, y0, x1, y1), sem duplicata exata."""
    saida = {tuple(k): [] for k in chaves}
    for d in _pagina(pdf).get_drawings():
        if d.get("fill") is None or not _dentro(d["rect"], regiao_pt):
            continue
        chave = (d.get("layer"), tuple(round(c, 2) for c in d["fill"]))
        if chave not in saida:
            continue
        p = _poligono_do_desenho(d)
        if (
            p is not None
            and not p.is_empty
            and not any(p.equals_exact(o, 0.05) for o in saida[chave])
        ):
            saida[chave].append(p)
    return saida


def _partes(geometria) -> list[Polygon]:
    """Polígonos não vazios da geometria (ou da lista de polígonos), em ordem estável (x e y mínimos)."""
    if isinstance(geometria, (list, tuple)):
        geometria = GeometryCollection(list(geometria))
    partes = [
        g
        for g in getattr(geometria, "geoms", [geometria])
        if isinstance(g, Polygon) and not g.is_empty
    ]
    return sorted(partes, key=lambda p: (round(p.bounds[0], 6), round(p.bounds[1], 6)))


def unir(poligonos, folga_pt: float = 0.05) -> list[Polygon]:
    """União com buffer +folga/−folga (fecha a costura de dois triângulos); devolve as partes."""
    if not len(poligonos):
        return []
    mais = [p.buffer(folga_pt, join_style=2) for p in poligonos]
    return _partes(unary_union(mais).buffer(-folga_pt, join_style=2))


def sem_furos(poligono: Polygon) -> list[Polygon]:
    """Parte o polígono em faixas verticais (cortes nos x das bordas dos furos): nenhuma peça tem `interiors`."""
    if not poligono.interiors:
        return [poligono]
    xs = {poligono.bounds[0], poligono.bounds[2]}
    for furo in poligono.interiors:
        xs.update((furo.bounds[0], furo.bounds[2]))
    xs = sorted(xs)
    _, y0, _, y1 = poligono.bounds
    pecas = []
    for xa, xb in itertools.pairwise(xs):
        if xb - xa > 1e-9:
            pecas += [
                p
                for p in _partes(poligono.intersection(box(xa, y0, xb, y1)))
                if p.area > 1e-9
            ]
    return pecas


def tracos(pdf, layers, regiao_pt, minimo_pt: float = 20) -> list[tuple]:
    """[(a, b, layer)] dos segmentos `l` dos layers dados, dentro da região, mais longos que `minimo_pt`."""
    saida = []
    for d in _pagina(pdf).get_drawings():
        if d.get("layer") not in layers or not _dentro(d["rect"], regiao_pt):
            continue
        for item in d["items"]:
            if item[0] != "l":
                continue
            a, b = np.array([item[1].x, item[1].y]), np.array([item[2].x, item[2].y])
            if np.linalg.norm(b - a) > minimo_pt:
                saida.append((a, b, d.get("layer")))
    return saida


def _retangulo_do_par(s1, s2, largura_pt, sobreposicao_pt) -> Polygon | None:
    a1, b1, _ = s1
    a2, b2, _ = s2
    comp = np.linalg.norm(b1 - a1)
    u = (b1 - a1) / comp
    v = (b2 - a2) / np.linalg.norm(b2 - a2)
    if abs(abs(u @ v) - 1) > 1e-4:
        return None
    n = np.array([-u[1], u[0]])
    d = (a2 - a1) @ n
    if not largura_pt[0] <= abs(d) <= largura_pt[1]:
        return None
    t = sorted([(a2 - a1) @ u, (b2 - a1) @ u])
    t0, t1 = max(0.0, t[0]), min(comp, t[1])
    if t1 - t0 < sobreposicao_pt:
        return None
    p0, p1 = a1 + u * t0, a1 + u * t1
    return Polygon([p0, p1, p1 + n * d, p0 + n * d])


def vigas_por_pares(
    tracos, largura_pt=(10.5, 12.5), sobreposicao_pt: float = 15
) -> list[Polygon]:
    """Vigas como pares de traços paralelos: retângulo da sobreposição projetada (a borda da viga não fecha face)."""
    saida = []
    for i, s1 in enumerate(tracos):
        for s2 in tracos[i + 1 :]:
            r = _retangulo_do_par(s1, s2, largura_pt, sobreposicao_pt)
            if r is not None:
                saida.append(r)
    return saida


def alinhar_por_pontos(pontos_a, pontos_b, tol_pt: float = 1.0) -> dict:
    """Translação que leva `pontos_b` sobre `pontos_a`: a diferença candidata a−b que casa mais pontos, refinada pela mediana."""
    a, b = np.asarray(pontos_a, float), np.asarray(pontos_b, float)
    from scipy.spatial import cKDTree  # extra `topografia`

    arvore = cKDTree(a)
    candidatas = (a[:, None, :] - b[None, :, :]).reshape(-1, 2)
    melhor, melhor_n = None, -1
    for d in candidatas:
        n = int((arvore.query(b + d)[0] <= tol_pt).sum())
        if n > melhor_n:
            melhor, melhor_n = d, n
    dist, idx = arvore.query(b + melhor)
    casados = dist <= tol_pt
    translacao = np.median(a[idx[casados]] - b[casados], axis=0)
    residuo = np.linalg.norm(a[idx[casados]] - (b[casados] + translacao), axis=1)
    return {
        "translacao_pt": [float(translacao[0]), float(translacao[1])],
        "casados": int(casados.sum()),
        "total": len(b),
        "residuo_mediano_pt": float(np.median(residuo)),
    }


def _posicoes_eixos(pdf, regiao_pt, layers) -> tuple[tuple, tuple]:
    """((y, comprimento) dos horizontais, (x, comprimento) dos verticais) com comprimento > 30 pt."""
    horizontais, verticais = [], []
    for d in _pagina(pdf).get_drawings():
        if (layers is not None and d.get("layer") not in layers) or not _dentro(
            d["rect"], regiao_pt
        ):
            continue
        for item in d["items"]:
            if item[0] != "l":
                continue
            dx, dy = item[2].x - item[1].x, item[2].y - item[1].y
            comp = float(np.hypot(dx, dy))
            if comp <= COMPRIMENTO_EIXO_PT:
                continue
            if abs(dy) < 1e-3 * comp:
                horizontais.append((item[1].y, comp))
            elif abs(dx) < 1e-3 * comp:
                verticais.append((item[1].x, comp))
    return np.array(horizontais, float).reshape(-1, 2), np.array(
        verticais, float
    ).reshape(-1, 2)


def _histograma(posicoes_comprimentos, inicio, n_bins) -> np.ndarray:
    h = np.zeros(n_bins)
    idx = np.clip(
        ((posicoes_comprimentos[:, 0] - inicio) / RESOLUCAO_HIST_PT).astype(int),
        0,
        n_bins - 1,
    )
    np.add.at(h, idx, posicoes_comprimentos[:, 1])
    return np.convolve(h, [1.0, 2.0, 1.0], mode="same")


def _correlacao_1d(pa, pb, alcance_pt) -> tuple[float, float, float]:
    """(deslocamento_pt, pico, segundo pico) que leva `pb` sobre `pa` pelo histograma de posições."""
    if not len(pa) or not len(pb):
        return 0.0, 0.0, 0.0
    folga = alcance_pt + 2
    inicio = min(pa[:, 0].min(), pb[:, 0].min()) - folga
    n_bins = (
        int((max(pa[:, 0].max(), pb[:, 0].max()) + folga - inicio) / RESOLUCAO_HIST_PT)
        + 2
    )
    ha, hb = _histograma(pa, inicio, n_bins), _histograma(pb, inicio, n_bins)
    k_max = int(alcance_pt / RESOLUCAO_HIST_PT)
    ks = np.arange(-k_max, k_max + 1)
    pontuacao = np.array(
        [
            float(
                ha[max(0, k) : n_bins + min(0, k)] @ hb[max(0, -k) : n_bins - max(0, k)]
            )
            for k in ks
        ]
    )
    i = int(pontuacao.argmax())
    fora = np.abs(ks - ks[i]) > 3
    segundo = float(pontuacao[fora].max()) if fora.any() else 0.0
    return float(ks[i] * RESOLUCAO_HIST_PT), float(pontuacao[i]), segundo


def alinhar_por_linhas(
    pdf_a, pdf_b, regiao_pt, layers=None, alcance_pt: float = 60
) -> dict:
    """Translação de b para a pela correlação 1D dos histogramas de posição dos traços horizontais (y) e verticais (x)."""
    ha, va = _posicoes_eixos(pdf_a, regiao_pt, layers)
    hb, vb = _posicoes_eixos(pdf_b, regiao_pt, layers)
    dy, pico_y, segundo_y = _correlacao_1d(ha, hb, alcance_pt)
    dx, pico_x, segundo_x = _correlacao_1d(va, vb, alcance_pt)
    return {
        "translacao_pt": [dx, dy],
        "pico_x": pico_x,
        "pico_y": pico_y,
        "segundo_pico_x": segundo_x,
        "segundo_pico_y": segundo_y,
    }


def _centro_e_angulo(retangulo) -> tuple[np.ndarray, float]:
    """Centroide e direção (rad, módulo π) do lado maior do retângulo mínimo (aresta do casco de menor área)."""
    poligono = (
        retangulo
        if isinstance(retangulo, Polygon)
        else Polygon(np.asarray(retangulo, float))
    )
    casco = np.array(poligono.convex_hull.exterior.coords)
    melhor = None
    for aresta in np.diff(casco, axis=0):
        u = aresta / np.linalg.norm(aresta)
        proj = casco @ np.array([u, [-u[1], u[0]]]).T
        ext = proj.max(axis=0) - proj.min(axis=0)
        if melhor is None or ext.prod() < melhor[0] - 1e-9:
            melhor = (ext.prod(), u if ext[0] >= ext[1] else np.array([-u[1], u[0]]))
    return np.array(poligono.centroid.coords[0]), float(
        np.arctan2(melhor[1][1], melhor[1][0]) % np.pi
    )


def alinhar_por_retangulo(ret_a, ret_b, angulo_aprox_graus: float = 0.0) -> np.ndarray:
    """Afim rígida 2x3 pt_b → pt_a pelo mesmo retângulo nas duas folhas; a ambiguidade de 180° segue o ângulo aproximado."""
    ca, ta = _centro_e_angulo(ret_a)
    cb, tb = _centro_e_angulo(ret_b)
    aprox = np.radians(angulo_aprox_graus)
    candidatos = [ta - tb, ta - tb + np.pi]
    theta = min(
        candidatos, key=lambda t: abs((t - aprox + np.pi) % (2 * np.pi) - np.pi)
    )
    c, s = np.cos(theta), np.sin(theta)
    R = np.array([[c, -s], [s, c]])
    return np.c_[R, ca - R @ cb]


def prismas_inclinados(
    base_xy, z_base, topo_xy, z_topo, largura_m, n: int = 14
) -> list[dict]:
    """Peça inclinada (escora) como `n` prismas verticais ao longo do eixo, de largura `largura_m` perpendicular a ele."""
    base, topo = np.asarray(base_xy, float), np.asarray(topo_xy, float)
    eixo = topo - base
    u = eixo / np.linalg.norm(eixo)
    meia = np.array([-u[1], u[0]]) * largura_m / 2
    t = np.linspace(0.0, 1.0, n + 1)
    pontos = base + t[:, None] * eixo
    z = z_base + t * (z_topo - z_base)
    return [
        {
            "contorno": [
                list(map(float, p))
                for p in (
                    pontos[i] - meia,
                    pontos[i + 1] - meia,
                    pontos[i + 1] + meia,
                    pontos[i] + meia,
                )
            ],
            "z0": float(min(z[i], z[i + 1])),
            "z1": float(max(z[i], z[i + 1])),
        }
        for i in range(n)
    ]


# --- montagem declarativa de uma estrutura (chave `estruturas_3d` do obra.json) ---


def _chave(chave) -> tuple:
    """`["12", [0.8, 0.85, 0.8]]` do JSON -> ("12", (0.8, 0.85, 0.8)), a chave de `preenchidos`."""
    return (chave[0], tuple(round(float(c), 2) for c in chave[1]))


def _matriz3(matriz_2x3) -> np.ndarray:
    return np.vstack([np.asarray(matriz_2x3, float).reshape(2, 3), [0.0, 0.0, 1.0]])


def _afim_da_folha(transformacao: dict) -> np.ndarray:
    """Afim 3x3 pt da folha -> pt da base: `matriz_pt` (2x3) ou `translacao_pt` (padrão: nula)."""
    if transformacao.get("matriz_pt") is not None:
        return _matriz3(transformacao["matriz_pt"])
    afim = np.eye(3)
    afim[:2, 2] = transformacao.get("translacao_pt", [0.0, 0.0])
    return afim


def matrizes_das_pranchas(pranchas: list[dict]) -> dict[str, np.ndarray]:
    """{id: afim 3x3 pt -> UTM} das pranchas do obra.json que declaram `M_absoluta`."""
    return {p["id"]: _matriz3(p["M_absoluta"]) for p in pranchas if p.get("M_absoluta")}


def matriz_da_folha(
    id_folha, folhas: dict, matrizes_pranchas: dict, pilha=()
) -> np.ndarray:
    """Afim 3x3 pt da folha -> UTM: a base (`prancha` ou outra `folha`) composta com a translação/matriz em pt.
    Erro claro se a cadeia tiver ciclo, folha não declarada ou prancha sem `M_absoluta`."""
    if id_folha in pilha:
        raise ValueError(
            "ciclo nas transformações das folhas: " + " -> ".join([*pilha, id_folha])
        )
    if id_folha not in folhas:
        raise ValueError(f"folha {id_folha} não declarada em `folhas`")
    transformacao = folhas[id_folha]["transformacao"]
    if "prancha" in transformacao:
        if transformacao["prancha"] not in matrizes_pranchas:
            raise ValueError(
                f"prancha {transformacao['prancha']} sem M_absoluta no obra.json (folha {id_folha})"
            )
        base = matrizes_pranchas[transformacao["prancha"]]
    elif "folha" in transformacao:
        base = matriz_da_folha(
            transformacao["folha"], folhas, matrizes_pranchas, (*pilha, id_folha)
        )
    else:
        raise ValueError(
            f"folha {id_folha}: a transformação precisa de `prancha` ou `folha`"
        )
    return base @ _afim_da_folha(transformacao)


def _aplicar(matriz, pontos) -> np.ndarray:
    return np.asarray(pontos, float).reshape(-1, 2) @ matriz[:2, :2].T + matriz[:2, 2]


def _para_utm(geometria, matriz):
    m = matriz
    return affine_transform(
        geometria, [m[0, 0], m[0, 1], m[1, 0], m[1, 1], m[0, 2], m[1, 2]]
    )


def _escala_m_por_pt(matriz) -> float:
    return float(np.sqrt(abs(np.linalg.det(matriz[:2, :2]))))


def centros_das_pecas(pdf, chave, regiao_pt) -> np.ndarray:
    """Centroides (pt) das peças preenchidas da `chave` (layer, cor) na região, já unidas."""
    lidos = preenchidos(pdf, [_chave(chave)], regiao_pt)[_chave(chave)]
    return np.array([p.centroid.coords[0] for p in unir(lidos)], float).reshape(-1, 2)


def conferir_folha(pdf_folha, pdf_base, afim_pt, conferencia: dict) -> dict:
    """Recalcula a translação folha -> base pelos centros das peças da `chave`: `afim_pt` (3x3, declarada) leva a
    folha à base; o resíduo é a translação extra que `alinhar_por_pontos` ainda acha. Passa se a diferença ≤ `tol_pt`
    e se casaram ao menos min(3, total) peças."""
    regiao, tol_pt = conferencia["regiao_pt"], float(conferencia.get("tol_pt", 0.5))
    base = centros_das_pecas(pdf_base, conferencia["chave"], regiao)
    folha = _aplicar(
        afim_pt, centros_das_pecas(pdf_folha, conferencia["chave"], regiao)
    )
    if not len(base) or not len(folha):
        return {
            "casados": 0,
            "total": len(folha),
            "ok": False,
            "tol_pt": tol_pt,
            "diferenca_pt": None,
        }
    r = alinhar_por_pontos(base, folha)
    diferenca = float(np.hypot(*r["translacao_pt"]))
    ok = r["casados"] >= min(3, r["total"]) and diferenca <= tol_pt
    return {
        "casados": r["casados"],
        "total": r["total"],
        "residuo_mediano_pt": r["residuo_mediano_pt"],
        "translacao_declarada_pt": [float(afim_pt[0, 2]), float(afim_pt[1, 2])],
        "diferenca_pt": diferenca,
        "tol_pt": tol_pt,
        "ok": bool(ok),
    }


def _conferencias(est: dict, pdfs: dict) -> dict:
    """{folha: conferência} das folhas que declaram `conferencia`; a base é a `folha` da transformação."""
    saida = {}
    for id_folha, folha in est["folhas"].items():
        if not folha.get("conferencia"):
            continue
        base = folha["transformacao"].get("folha")
        if base is None:
            raise ValueError(
                f"folha {id_folha}: `conferencia` exige transformação por `folha`"
            )
        saida[id_folha] = conferir_folha(
            pdfs[id_folha],
            pdfs[base],
            _afim_da_folha(folha["transformacao"]),
            folha["conferencia"],
        )
    return saida


def _caixas_dos_subcaminhos(desenho) -> list[tuple]:
    """Caixas (x0, y0, x1, y1) de cada subcaminho contínuo (`l`/`c`) e de cada `re` do desenho."""
    caixas, pontos, fim = [], [], None
    for item in desenho["items"]:
        if item[0] == "re":
            caixas.append(tuple(item[1]))
            continue
        if item[0] not in ("l", "c"):
            continue
        if fim is None or np.hypot(item[1].x - fim[0], item[1].y - fim[1]) > 1e-3:
            if pontos:
                caixas.append((*np.min(pontos, axis=0), *np.max(pontos, axis=0)))
            pontos = []
        pontos += [(p.x, p.y) for p in item[1:]]
        fim = (item[-1].x, item[-1].y)
    if pontos:
        caixas.append((*np.min(pontos, axis=0), *np.max(pontos, axis=0)))
    return caixas


def circulos(pdf, layer, diametro_pt, regiao_pt) -> np.ndarray:
    """Centros (pt) dos círculos do layer cuja largura cai em `diametro_pt` (mín, máx); sem duplicata a 0,5 pt."""
    centros = []
    for d in _pagina(pdf).get_drawings():
        if d.get("layer") != layer or not _dentro(d["rect"], regiao_pt):
            continue
        for x0, y0, x1, y1 in _caixas_dos_subcaminhos(d):
            largura, altura = x1 - x0, y1 - y0
            redondo = abs(largura - altura) <= REDONDEZA_ESTACA * largura
            centro = ((x0 + x1) / 2, (y0 + y1) / 2)
            if (
                diametro_pt[0] <= largura <= diametro_pt[1]
                and redondo
                and not any(
                    np.hypot(centro[0] - o[0], centro[1] - o[1]) < 0.5 for o in centros
                )
            ):
                centros.append(centro)
    return np.array(sorted(centros), float).reshape(-1, 2)


def _fechadas_do_layer(pdf, layer, regiao_pt) -> list[Polygon]:
    """Itens `re` e `qu` dos desenhos do layer (o PyMuPDF devolve um contorno de 4 traços ou retangular assim)."""
    saida = []
    for d in _pagina(pdf).get_drawings():
        if d.get("layer") != layer or not _dentro(d["rect"], regiao_pt):
            continue
        for item in d["items"]:
            if item[0] == "re":
                saida.append(box(*item[1]))
            elif item[0] == "qu":
                q = item[1]
                saida.append(Polygon([q.ul, q.ur, q.lr, q.ll]))
    return saida


def blocos_fechados(pdf, layer, regiao_pt, area_min_pt2: float) -> list[Polygon]:
    """Blocos do layer com área ≥ `area_min_pt2`: polígonos fechados pelos traços (polygonize) e contornos `re`/`qu`."""
    segmentos = tracos(pdf, [layer], regiao_pt, minimo_pt=0)
    fechados = []
    if segmentos:
        linhas = unary_union([LineString([a, b]) for a, b, _ in segmentos])
        fechados = list(polygonize(linhas))
    candidatos = [
        p
        for p in [*fechados, *_fechadas_do_layer(pdf, layer, regiao_pt)]
        if p.area >= area_min_pt2
    ]
    unicos = []
    for p in candidatos:
        if not any(p.equals_exact(o, 0.05) for o in unicos):
            unicos.append(p)
    return _partes(unicos)


def atribuir_rotulos(centros_pt, rotulos_pt: dict) -> dict[int, str]:
    """{índice do centro: rótulo}, 1 a 1 (`linear_sum_assignment`) pela menor distância total até os pontos de
    `rotulos_pt`. Sobra sem rótulo o que exceder a quantidade menor."""
    nomes = list(rotulos_pt)
    centros = np.asarray(centros_pt, float).reshape(-1, 2)
    if not len(centros) or not nomes:
        return {}
    from scipy.optimize import linear_sum_assignment  # extra `topografia`
    from scipy.spatial.distance import cdist

    custo = cdist(centros, np.asarray([rotulos_pt[n] for n in nomes], float))
    linhas, colunas = linear_sum_assignment(custo)
    return {int(i): nomes[j] for i, j in zip(linhas, colunas)}


def bloco_de_cada_estaca(centros_pt, poligonos) -> list[int | None]:
    """Índice do primeiro polígono que contém o centro da estaca (None se nenhum contém)."""
    saida = []
    for x, y in np.asarray(centros_pt, float).reshape(-1, 2):
        pontos = box(x, y, x, y)
        saida.append(
            next((i for i, p in enumerate(poligonos) if p.contains(pontos)), None)
        )
    return saida


def _chave_natural(texto: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", texto)]


def _blocos_da_fundacao(fund, poligonos, rotulos, donos, matriz) -> tuple[list, dict]:
    """Blocos {rotulo, contorno_utm, estacas, face_superior, fundo, arrasamento, estacas_utm} e {índice: bloco}."""
    por_bloco = {}
    for k, dono in enumerate(donos):
        por_bloco.setdefault(dono, []).append(k)
    blocos = []
    for i, rotulo in rotulos.items():
        if rotulo not in fund["niveis"]:
            raise ValueError(f"bloco {rotulo} sem `niveis` na fundação")
        niveis = fund["niveis"][rotulo]
        blocos.append(
            {
                "rotulo": rotulo,
                "contorno_utm": _aplicar(matriz, poligonos[i].exterior.coords)
                .round(3)
                .tolist(),
                "estacas": len(por_bloco.get(i, [])),
                "face_superior": niveis["face_superior"],
                "fundo": round(niveis["face_superior"] - fund["altura_bloco_m"], 3),
                "arrasamento": niveis["arrasamento"],
                "estacas_utm": [],
                "_indice": i,
            }
        )
    return sorted(blocos, key=lambda b: _chave_natural(b["rotulo"])), por_bloco


def _linhas_de_estacas(
    fund, estrutura, pdf, centros_utm, blocos, por_bloco, donos
) -> list[dict]:
    """Estacas na ordem dos blocos (n = 1, 2, ... por bloco, na ordem x, y do desenho); as sem bloco vão no fim."""
    modelo = {
        **fund["estaca"],
        "estrutura": estrutura,
        "desenho_origem": Path(str(pdf)).name,
    }
    linhas = []
    for b in blocos:
        for n, k in enumerate(por_bloco.get(b["_indice"], []), 1):
            b.setdefault("estacas_utm", []).append(centros_utm[k].round(3).tolist())
            linhas.append(
                _linha_de_estaca(
                    f"{estrutura}-{b['rotulo']}-{n}", centros_utm[k], b, modelo
                )
            )
    soltas = [k for k, d in enumerate(donos) if d not in {b["_indice"] for b in blocos}]
    return linhas + [
        _linha_de_estaca(f"{estrutura}-SB-{n}", centros_utm[k], None, modelo)
        for n, k in enumerate(soltas, 1)
    ]


def _linha_de_estaca(id_estaca, centro_utm, bloco, modelo) -> dict:
    return {
        "id": id_estaca,
        "E": round(float(centro_utm[0]), 3),
        "N": round(float(centro_utm[1]), 3),
        "diametro_cm": modelo["diametro_cm"],
        "cota_arrasamento": bloco["arrasamento"] if bloco else None,
        "comprimento_m": modelo["comprimento_m"],
        "estrutura": modelo["estrutura"],
        "bloco": bloco["rotulo"] if bloco else None,
        "execucao": modelo.get("execucao"),
        "desenho_origem": modelo["desenho_origem"],
    }


def montar_fundacao(fund: dict, estrutura: str, pdfs: dict, matrizes: dict) -> dict:
    """Blocos e estacas da fundação: círculos do layer das estacas, polígonos fechados do layer dos blocos, rótulo
    do ponto de `rotulos_pt` mais próximo (1 a 1), níveis de `niveis`, `fundo = face_superior − altura_bloco_m`."""
    pdf, matriz, regiao = (
        pdfs[fund["folha"]],
        matrizes[fund["folha"]],
        fund["regiao_pt"],
    )
    centros = circulos(
        pdf, fund["estacas"]["layer"], fund["estacas"]["diametro_pt"], regiao
    )
    poligonos = blocos_fechados(
        pdf, fund["blocos"]["layer"], regiao, fund["blocos"]["area_min_pt2"]
    )
    rotulos = atribuir_rotulos(
        [p.centroid.coords[0] for p in poligonos], fund["rotulos_pt"]
    )
    donos = bloco_de_cada_estaca(centros, poligonos)
    blocos, por_bloco = _blocos_da_fundacao(fund, poligonos, rotulos, donos, matriz)
    estacas = _linhas_de_estacas(
        fund, estrutura, pdf, _aplicar(matriz, centros), blocos, por_bloco, donos
    )
    diagnostico = {
        "blocos_lidos": len(poligonos),
        "blocos_sem_rotulo": len(poligonos) - len(rotulos),
        "rotulos_sem_bloco": sorted(
            set(fund["rotulos_pt"]) - set(rotulos.values()), key=_chave_natural
        ),
        "estacas_lidas": len(centros),
        "estacas_sem_bloco": sum(d is None or d not in rotulos for d in donos),
    }
    for b in blocos:
        b.pop("_indice")
    return {"blocos": blocos, "estacas": estacas, "diagnostico": diagnostico}


def _cotas_do_elemento(espec: dict) -> tuple:
    if "nivel" in espec:
        return espec["nivel"] - espec["altura_m"], espec["nivel"]
    return espec.get("z0"), espec.get("z1")


def _fatiar_por_zonas(poligono, espec) -> list[tuple]:
    """[(Polygon pt, z0, z1)]: o polígono partido pelas `zonas` (cada parte com o z da zona); o resto com o z do elemento."""
    z0, z1 = _cotas_do_elemento(espec)
    fatias, resto = [], poligono
    for zona in espec.get("zonas", []):
        caixa = box(*zona["regiao_pt"])
        fatias += [
            (p, zona.get("z0", z0), zona.get("z1", z1))
            for p in _partes(resto.intersection(caixa))
        ]
        resto = resto.difference(caixa)
    fatias += [(p, z0, z1) for p in _partes(resto)]
    return sorted(
        fatias, key=lambda f: (round(f[0].bounds[0], 6), round(f[0].bounds[1], 6))
    )


def z0_pelos_blocos(poligono_utm, blocos: list[tuple], modo: str, padrao):
    """z0 de um elemento pelos blocos (lista de (Polygon UTM, face_superior)): "minimo" = menor face dos que tocam o
    elemento (buffer de 0,6 m); "moda" = face mais comum dos blocos com o centro dentro dele. Sem bloco, `padrao`."""
    if modo == "minimo":
        zona = poligono_utm.buffer(BUFFER_BLOCO_M)
        faces = [f for p, f in blocos if zona.intersects(p)]
        return min(faces) if faces else padrao
    if modo == "moda":
        faces = [round(f, 2) for p, f in blocos if poligono_utm.contains(p.centroid)]
        if not faces:
            return padrao
        contagem = Counter(faces)
        return min(contagem, key=lambda f: (-contagem[f], f))
    raise ValueError(f"`z0_pelos_blocos` deve ser 'minimo' ou 'moda', veio {modo!r}")


def _a_remover(espec, ctx):
    """União do que sai do elemento: blocos (folga de 1 pt) e/ou os pilares já gerados."""
    remover = []
    if espec.get("descontar_blocos"):
        folga_m = BUFFER_DESCONTO_PT * _escala_m_por_pt(ctx["matrizes"][espec["folha"]])
        remover += [p.buffer(folga_m) for p, _ in ctx["blocos"]]
    if espec.get("recortar_pilares"):
        remover += [
            Polygon(e["contorno_utm"]) for e in ctx["elementos"] if e["tipo"] == "pilar"
        ]
    return unary_union(remover) if remover else None


def _pecas_recortadas(poligono, remover, tirar_furos: bool) -> list[Polygon]:
    partes = _partes(poligono.difference(remover) if remover is not None else poligono)
    partes = [p for p in partes if p.area >= AREA_MINIMA_ELEMENTO_M2]
    return [q for p in partes for q in (sem_furos(p) if tirar_furos else [p])]


def _finalizar(fatias, espec, ctx) -> list[dict]:
    """Fatias UTM [(Polygon, z0, z1)] -> elementos {rotulo, tipo, contorno_utm, z0, z1}: recorta (blocos, pilares),
    tira furos, ajusta o z0 pelos blocos e numera os rótulos."""
    remover = _a_remover(espec, ctx)
    modo = espec.get("z0_pelos_blocos")
    pecas = []
    for poligono, z0, z1 in fatias:
        for p in _pecas_recortadas(poligono, remover, espec.get("sem_furos", False)):
            pecas.append(
                (p, z0_pelos_blocos(p, ctx["blocos"], modo, z0) if modo else z0, z1)
            )
    tipo = espec.get("elemento", espec["tipo"])
    base = (
        f"{tipo} {espec['rotulo']}" if "rotulo" in espec else espec.get("nome") or tipo
    )
    rotulos = (
        [base]
        if len(pecas) == 1 and "rotulo" in espec
        else [f"{base} {n}" for n in range(1, len(pecas) + 1)]
    )
    return [
        _elemento(r, tipo, p.exterior.coords, z0, z1)
        for r, (p, z0, z1) in zip(rotulos, pecas)
    ]


def _elemento(rotulo, tipo, contorno, z0, z1) -> dict:
    if z0 is None or z1 is None:
        raise ValueError(
            f"elemento '{rotulo}' sem z0/z1 (declare `z0`/`z1`, `nivel`+`altura_m` ou `z0_pelos_blocos`)"
        )
    return {
        "rotulo": rotulo,
        "tipo": tipo,
        "contorno_utm": np.asarray(contorno, float).round(3).tolist(),
        "z0": round(float(z0), 3),
        "z1": round(float(z1), 3),
    }


def _el_preenchido(espec, ctx) -> list[dict]:
    pdf, matriz = ctx["pdfs"][espec["folha"]], ctx["matrizes"][espec["folha"]]
    lidos = preenchidos(pdf, [_chave(espec["chave"])], espec["regiao_pt"])[
        _chave(espec["chave"])
    ]
    polis = unir(lidos) if espec.get("unir") else _partes(lidos)
    fatias = [
        (_para_utm(p, matriz), z0, z1)
        for poli in polis
        for p, z0, z1 in _fatiar_por_zonas(poli, espec)
    ]
    return _finalizar(fatias, espec, ctx)


def _el_pares(espec, ctx) -> list[dict]:
    pdf, matriz = ctx["pdfs"][espec["folha"]], ctx["matrizes"][espec["folha"]]
    segmentos = [
        s
        for regiao in espec["regioes_pt"]
        for s in tracos(pdf, espec["layers"], regiao)
    ]
    vigas = vigas_por_pares(segmentos, tuple(espec.get("largura_pt", (10.5, 12.5))))
    z0, z1 = _cotas_do_elemento(espec)
    return _finalizar([(_para_utm(v, matriz), z0, z1) for v in vigas], espec, ctx)


def _retangulo_orientado(centro, dimensoes_m, angulo_rad) -> Polygon:
    u = np.array([np.cos(angulo_rad), np.sin(angulo_rad)])
    n = np.array([-u[1], u[0]])
    a, b = dimensoes_m[0] / 2, dimensoes_m[1] / 2
    return Polygon(
        [
            centro + u * a + n * b,
            centro - u * a + n * b,
            centro - u * a - n * b,
            centro + u * a - n * b,
        ]
    )


def _bloco_por_rotulo(ctx, rotulo) -> Polygon:
    if rotulo not in ctx["rotulos_blocos"]:
        raise ValueError(f"bloco {rotulo} inexistente na fundação da estrutura")
    return ctx["rotulos_blocos"][rotulo]


def _el_retangulo(espec, ctx) -> list[dict]:
    """Retângulo de `dimensoes_m` (lado maior na direção do bloco) no centro de um bloco (`centro_bloco`) ou de um
    ponto da folha (`centro_pt`); `orientacao_bloco` escolhe o bloco que dá a direção (padrão: `centro_bloco`)."""
    if "centro_bloco" in espec:
        bloco = _bloco_por_rotulo(ctx, espec["centro_bloco"])
        centro = np.array(bloco.centroid.coords[0])
    else:
        centro = _aplicar(ctx["matrizes"][espec["folha"]], [espec["centro_pt"]])[0]
    rotulo_direcao = espec.get("orientacao_bloco", espec.get("centro_bloco"))
    angulo = (
        _centro_e_angulo(_bloco_por_rotulo(ctx, rotulo_direcao))[1]
        if rotulo_direcao
        else 0.0
    )
    z0, z1 = _cotas_do_elemento(espec)
    return _finalizar(
        [(_retangulo_orientado(centro, espec["dimensoes_m"], angulo), z0, z1)],
        espec,
        ctx,
    )


def _el_escora(espec, ctx) -> list[dict]:
    matriz = ctx["matrizes"][espec["folha"]]
    base, topo = _aplicar(matriz, [espec["base_pt"], espec["topo_pt"]])
    prismas = prismas_inclinados(
        base,
        espec["z_base"],
        topo,
        espec["z_topo"],
        espec["largura_m"],
        espec.get("n", 14),
    )
    tipo = espec.get("elemento", "escora")
    return [
        _elemento(
            f"{tipo} {espec['rotulo']} {n}",
            tipo,
            [*pr["contorno"], pr["contorno"][0]],
            pr["z0"],
            pr["z1"],
        )
        for n, pr in enumerate(prismas, 1)
    ]


TIPOS_DE_ELEMENTO = {
    "preenchido": _el_preenchido,
    "pares": _el_pares,
    "retangulo": _el_retangulo,
    "escora": _el_escora,
}


def _montar_elementos(est: dict, ctx: dict) -> list[dict]:
    for espec in est.get("elementos", []):
        if espec["tipo"] not in TIPOS_DE_ELEMENTO:
            raise ValueError(
                f"tipo de elemento desconhecido: {espec['tipo']!r} (use {sorted(TIPOS_DE_ELEMENTO)})"
            )
        ctx["elementos"] += TIPOS_DE_ELEMENTO[espec["tipo"]](espec, ctx)
    return ctx["elementos"]


def _contexto(est, pdfs, matrizes, fundacao) -> dict:
    blocos = [
        (Polygon(b["contorno_utm"]), b["face_superior"]) for b in fundacao["blocos"]
    ]
    return {
        "pdfs": pdfs,
        "matrizes": matrizes,
        "blocos": blocos,
        "rotulos_blocos": {
            b["rotulo"]: p for b, (p, _) in zip(fundacao["blocos"], blocos)
        },
        "elementos": [],
    }


def montar_estrutura(est: dict, matrizes_pranchas: dict) -> dict:
    """Monta uma estrutura do `estruturas_3d`: transformações das folhas, conferências, fundação (blocos e estacas) e
    elementos. Devolve {estrutura, gerada, metadata, blocos, elementos, estacas}; com conferência fora da tolerância,
    `gerada` é False (e o motivo vai em `metadata["motivo"]`), sem blocos, elementos nem estacas."""
    pdfs = {f: d["pdf"] for f, d in est["folhas"].items()}
    matrizes = {
        f: matriz_da_folha(f, est["folhas"], matrizes_pranchas) for f in est["folhas"]
    }
    conferencias = _conferencias(est, pdfs)
    metadata = {
        "estrutura": est["id"],
        "folhas": {
            f: {
                "pdf": str(pdfs[f]),
                "transformacao": est["folhas"][f]["transformacao"],
                "matriz_utm": matrizes[f][:2].tolist(),
            }
            for f in pdfs
        },
        "conferencias": conferencias,
    }
    reprovadas = [f for f, c in conferencias.items() if not c["ok"]]
    if reprovadas:
        metadata["motivo"] = "conferência fora da tolerância nas folhas " + ", ".join(
            reprovadas
        )
        return {
            "estrutura": est["id"],
            "gerada": False,
            "metadata": metadata,
            "blocos": [],
            "elementos": [],
            "estacas": [],
        }
    vazia = {"blocos": [], "estacas": [], "diagnostico": {}}
    fundacao = (
        montar_fundacao(est["fundacao"], est["id"], pdfs, matrizes)
        if est.get("fundacao")
        else vazia
    )
    elementos = _montar_elementos(est, _contexto(est, pdfs, matrizes, fundacao))
    metadata["fundacao"] = fundacao["diagnostico"]
    metadata["contagens"] = {
        "blocos": len(fundacao["blocos"]),
        "estacas": len(fundacao["estacas"]),
        "elementos": dict(Counter(e["tipo"] for e in elementos)),
    }
    return {
        "estrutura": est["id"],
        "gerada": True,
        "metadata": metadata,
        "blocos": fundacao["blocos"],
        "elementos": elementos,
        "estacas": fundacao["estacas"],
    }


COLUNAS_ESTACAS = [
    "id",
    "E",
    "N",
    "diametro_cm",
    "cota_arrasamento",
    "comprimento_m",
    "estrutura",
    "bloco",
    "execucao",
    "desenho_origem",
]
CASAS_ESTACAS = {"E": 3, "N": 3, "cota_arrasamento": 2, "comprimento_m": 2}


def _campo_csv(coluna, valor) -> str:
    if valor is None:
        return ""
    if coluna in CASAS_ESTACAS:
        return f"{valor:.{CASAS_ESTACAS[coluna]}f}".replace(".", ",")
    return f"{valor:g}".replace(".", ",") if isinstance(valor, float) else str(valor)


def gravar_estacas_csv(estacas: list[dict], caminho) -> None:
    """CSV de estacas no formato que o build lê (`;`, decimal vírgula)."""
    with Path(caminho).open("w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=";", lineterminator="\n")
        escritor.writerow(COLUNAS_ESTACAS)
        escritor.writerows(
            [_campo_csv(c, e.get(c)) for c in COLUNAS_ESTACAS] for e in estacas
        )


def gravar_estrutura(resultado: dict, caminho) -> None:
    """JSON da estrutura no formato de `obra.solidos_de_arquivos` (`estrutura`, `metadata`, `blocos`, `elementos`)."""
    corpo = {k: resultado[k] for k in ("estrutura", "metadata", "blocos", "elementos")}
    Path(caminho).write_text(
        json.dumps(corpo, ensure_ascii=False, indent=1), encoding="utf-8"
    )


PREMISSAS = [
    {
        "aplicacao": {"preenchidos": ["FRACAO_MINIMA_RECT=0,4", "duplicata a 0,05 pt"]},
        "estado": "premissa",
        "fonte": "caminho de linhas fora de ordem vira o rect do desenho; sem duplicata exata (sombra, folha 003)",
    },
    {
        "aplicacao": {"unir": ["folga_pt=0,05"]},
        "estado": "premissa",
        "fonte": "pilar desenhado como dois triângulos pela diagonal (folha 018); laje sobreposta (004)",
    },
    {
        "aplicacao": {"sem_furos": ["faixas verticais nos x das bordas dos furos"]},
        "estado": "premissa",
        "fonte": "o visualizador só extruda o contorno externo",
    },
    {
        "aplicacao": {
            "vigas_por_pares": ["largura_pt=(10,5; 12,5)", "sobreposicao_pt=15"]
        },
        "estado": "premissa",
        "fonte": "a borda da viga não fecha face (folha 018); largura de 20 cm na escala da folha",
    },
    {
        "aplicacao": {"alinhar_por_pontos": ["tol_pt=1,0"]},
        "estado": "premissa",
        "fonte": "pilares casados folha a folha: 13 de 13 a 0,1 pt (017/018 → 016), 8 de 8 (004 → 003)",
    },
    {
        "aplicacao": {
            "alinhar_por_linhas": [
                "resolução 0,5 pt",
                "traço > 30 pt",
                "alcance_pt=60",
            ]
        },
        "estado": "premissa",
        "fonte": "correlação de traços de eixo e cota (019 → 018); a de vigas dá dois picos, por isso o segundo pico",
    },
    {
        "aplicacao": {
            "alinhar_por_retangulo": ["ambiguidade de 180° pelo ângulo aproximado"]
        },
        "estado": "premissa",
        "fonte": "pilar P7 da EEB09 desenhado na folha 026: rotação de 3,04°",
    },
    {
        "aplicacao": {
            "circulos": ["redondeza 10 %", "sem duplicata a 0,5 pt"],
            "blocos_fechados": ["polygonize dos traços do layer"],
        },
        "estado": "premissa",
        "fonte": "estaca = círculo de largura declarada no layer das estacas; bloco = polígono fechado do layer dos blocos",
    },
    {
        "aplicacao": {
            "z0_pelos_blocos": ["buffer 0,6 m", "moda: empate pela menor face"],
            "montar_estrutura": ["descontar_blocos: folga 1 pt"],
        },
        "estado": "premissa",
        "fonte": "fundo de parede e pilar = face dos blocos sob eles (EEB10 e EEB09)",
    },
    {
        "aplicacao": {
            "conferir_folha": [
                "tol_pt declarada por folha (padrão 0,5)",
                "mínimo de min(3, total) peças casadas",
            ]
        },
        "estado": "premissa",
        "fonte": "conferência pilar × estaca ≤ 0,5 pt do ciclo 1 (docs/PLANO_IRATI.md); reprovada, a estrutura sai do 3D",
    },
    {
        "aplicacao": {"prismas_inclinados": ["n=14"]},
        "estado": "premissa",
        "fonte": "escora aproximada por prismas verticais, único sólido que o visualizador extruda",
    },
]


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "forma3d",
        "descricao": "leitura de forma estrutural PBES (PDF vetorial) como geometria em pt da folha: áreas preenchidas, "
        "vigas por pares de traços, alinhamento folha → folha e escora em prismas",
        "funcoes": [
            "preenchidos",
            "unir",
            "sem_furos",
            "tracos",
            "vigas_por_pares",
            "alinhar_por_pontos",
            "alinhar_por_linhas",
            "alinhar_por_retangulo",
            "prismas_inclinados",
            "matriz_da_folha",
            "conferir_folha",
            "circulos",
            "blocos_fechados",
            "atribuir_rotulos",
            "bloco_de_cada_estaca",
            "z0_pelos_blocos",
            "montar_estrutura",
            "gravar_estrutura",
            "gravar_estacas_csv",
        ],
        "premissas": PREMISSAS,
    }
