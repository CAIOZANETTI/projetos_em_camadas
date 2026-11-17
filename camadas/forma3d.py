"""Leitura de forma estrutural (pranchas PBES, PDF vetorial de CAD) como geometria em pt da folha.

Primitivas para depois virar sólido 3D: áreas preenchidas por layer e cor, união de pedaços,
polígono sem furos, vigas como pares de traços paralelos, alinhamento folha → folha (pontos, linhas e
retângulo comum) e escora como prismas verticais. Tudo determinístico; unidades em pt da folha, exceto
`prismas_inclinados` (m).
"""

from __future__ import annotations

import itertools

import numpy as np
import pymupdf
from scipy.spatial import cKDTree
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

FRACAO_MINIMA_RECT = (
    0.4  # área do caminho / área do rect abaixo disso: caminho fora de ordem
)
RESOLUCAO_HIST_PT = 0.5  # passo do histograma de linhas
COMPRIMENTO_EIXO_PT = (
    30.0  # traço mais curto que isso não entra na correlação de linhas
)


def _pagina(pdf):
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
        ],
        "premissas": PREMISSAS,
    }
