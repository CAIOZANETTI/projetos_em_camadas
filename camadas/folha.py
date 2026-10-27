"""Pranchas de projeto em PDF -> camadas (raster por cor do CAD ou vetor por layer PDF).

Fluxo raster (funciona com qualquer PDF plotado, inclusive escaneado):
    img = renderizar_pdf("folha04.pdf", dpi=200)
    cores = cores_dominantes(img)                  # sugestão de paleta CAD
    masc = separar_por_cor(img, [c["rgb"] for c in camadas])
    pacotes = empacotar(masc)                      # 3 camadas por imagem (R, G, B)

Fluxo vetorial (PDF plotado com "criar layers PDF" ou DXF): ver `vetores_pdf`.
Coordenadas: tudo em pixel da prancha; o georreferenciamento é uma afim/
similaridade px -> UTM obtida por pontos de controle (camadas.geo.ajustar).
"""
from __future__ import annotations

import numpy as np


def renderizar_pdf(caminho: str, pagina: int = 0, dpi: int = 200) -> np.ndarray:
    """Rasteriza uma página do PDF (RGB uint8). Requer PyMuPDF (AGPL)."""
    import fitz  # PyMuPDF
    with fitz.open(caminho) as doc:
        pix = doc[pagina].get_pixmap(dpi=dpi, alpha=False)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, 3).copy()


def cores_dominantes(img: np.ndarray, n: int = 16, min_frac: float = 2e-4) -> list[dict]:
    """Cores "puras" mais frequentes, ignorando branco e pixels de antisserrilhado."""
    px = img.reshape(-1, 3)
    px = px[(px < 245).any(axis=1)]
    q = (px // 8).astype(np.int32)
    chave = q[:, 0] * 1024 + q[:, 1] * 32 + q[:, 2]
    val, cont = np.unique(chave, return_counts=True)
    ordem = np.argsort(cont)[::-1]
    out = []
    for i in ordem[:n * 4]:
        if cont[i] < min_frac * len(px):
            break
        c = np.array([val[i] // 1024, (val[i] // 32) % 32, val[i] % 32]) * 8 + 4
        if all(np.abs(c - o["rgb255"]).max() > 24 for o in out):
            out.append({"rgb255": c, "rgb": (c / 255).round(3).tolist(), "frac": float(cont[i] / len(px))})
        if len(out) == n:
            break
    return out


def separar_por_cor(img: np.ndarray, cores: list, tol: float = 40.0, fundo=(255, 255, 255)) -> list[np.ndarray]:
    """Uma máscara alfa (uint8) por camada.

    Cada camada pode ter várias cores (lista de rgb 0–1). Para cada pixel p,
    estima-se a cobertura a de uma linha de cor c sobre o fundo branco
    (p ≈ a·c + (1−a)·fundo, projeção no segmento fundo–c) e aceita-se se o
    desvio perpendicular ao segmento for < tol. Isso recupera o
    antisserrilhado das linhas finas em vez de cortar por limiar.
    O pixel vai para a camada de menor desvio.
    """
    p = img.reshape(-1, 3).astype(np.float32)
    f = np.asarray(fundo, np.float32)
    d = f - p                                       # "tinta" do pixel
    melhor = np.full(len(p), np.inf, np.float32)
    dono = np.full(len(p), -1, np.int32)
    alfa = np.zeros(len(p), np.float32)
    for k, cam in enumerate(cores):
        cam = cam if isinstance(cam[0], (list, tuple, np.ndarray)) else [cam]
        for rgb in cam:
            c = f - np.asarray(rgb, np.float32) * 255
            cc = float(c @ c)
            if cc < 1:
                continue
            a = np.clip((d @ c) / cc, 0, 1)
            desvio = np.linalg.norm(d - a[:, None] * c, axis=1)
            ok = (desvio < tol) & (a > 0.08) & (desvio < melhor)
            melhor[ok], dono[ok], alfa[ok] = desvio[ok], k, a[ok]
    h, w = img.shape[:2]
    return [np.where(dono == k, alfa * 255, 0).astype(np.uint8).reshape(h, w) for k in range(len(cores))]


def empacotar(mascaras: list[np.ndarray]) -> list[np.ndarray]:
    """Agrupa as máscaras de 3 em 3 em imagens BGR (canal R = 1ª, G = 2ª, B = 3ª).

    Gravar com webp sem perdas (cv2.IMWRITE_WEBP_QUALITY=101); o visualizador
    lê os canais R, G, B nessa ordem.
    """
    out = []
    for i in range(0, len(mascaras), 3):
        trio = mascaras[i:i + 3] + [np.zeros_like(mascaras[0])] * (3 - len(mascaras[i:i + 3]))
        out.append(np.dstack([trio[2], trio[1], trio[0]]))
    return out


def desempacotar(pacotes: list[np.ndarray], n: int) -> list[np.ndarray]:
    m = []
    for p in pacotes:
        m += [p[..., 2], p[..., 1], p[..., 0]]
    return m[:n]


def vetores_pdf(caminho: str, pagina: int = 0) -> list[dict]:
    """Traços vetoriais da página com cor, espessura e layer PDF (OCG), via PyMuPDF.

    Retorna [{"layer", "cor", "largura", "pontos": [[x, y], ...], "fechado"}] em
    pontos PDF (1/72"). Curvas Bézier são aproximadas por 8 segmentos.
    """
    import fitz
    out = []
    with fitz.open(caminho) as doc:
        for d in doc[pagina].get_drawings():
            pts = []
            for it in d["items"]:
                if it[0] == "l":
                    pts += [[it[1].x, it[1].y], [it[2].x, it[2].y]]
                elif it[0] == "c":
                    p0, p1, p2, p3 = it[1:5]
                    for t in np.linspace(0, 1, 9):
                        u = 1 - t
                        pts.append([u**3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t**3 * p3.x,
                                    u**3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t**3 * p3.y])
                elif it[0] == "re":
                    r = it[1]
                    pts += [[r.x0, r.y0], [r.x1, r.y0], [r.x1, r.y1], [r.x0, r.y1], [r.x0, r.y0]]
            if pts:
                out.append({"layer": d.get("layer") or "", "cor": d.get("color"), "largura": d.get("width"),
                            "pontos": pts, "fechado": bool(d.get("closePath"))})
    return out
