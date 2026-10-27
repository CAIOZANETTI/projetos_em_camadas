"""Utilidades geométricas: projeções, ajuste de transformações e world files."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer


def epsg_utm_sirgas(lon: float, lat: float) -> int:
    """EPSG SIRGAS 2000 / UTM para a zona do ponto (ex.: 31982 = 22S)."""
    zona = int((lon + 180) // 6) + 1
    if lat < 0:
        return 31960 + zona          # 31978 (18S) ... 31985 (25S)
    return 31954 + zona              # 31972 (18N) ... 31976 (22N)


def para_utm(lon, lat, epsg: int):
    t = Transformer.from_crs(4326, epsg, always_xy=True)
    return t.transform(lon, lat)


def para_lonlat(e, n, epsg: int):
    t = Transformer.from_crs(epsg, 4326, always_xy=True)
    return t.transform(e, n)


def ajustar(origem: np.ndarray, destino: np.ndarray, tipo: str = "similaridade",
            pesos: np.ndarray | None = None) -> np.ndarray:
    """Ajuste por mínimos quadrados de uma transformação 2D (matriz 3x3).

    tipo: 'similaridade' (escala+rotação+translação, 4 parâmetros),
          'afim' (6 parâmetros) ou 'homografia' (8 parâmetros, DLT).
    """
    o = np.asarray(origem, float)
    d = np.asarray(destino, float)
    w = np.ones(len(o)) if pesos is None else np.asarray(pesos, float)
    sw = np.sqrt(np.repeat(w, 2))
    x, y = o[:, 0], o[:, 1]
    z, u = np.zeros_like(x), np.ones_like(x)
    if tipo == "similaridade":
        A = np.empty((2 * len(o), 4))
        A[0::2] = np.c_[x, -y, u, z]
        A[1::2] = np.c_[y, x, z, u]
        p = np.linalg.lstsq(A * sw[:, None], d.ravel() * sw, rcond=None)[0]
        a, b, tx, ty = p
        return np.array([[a, -b, tx], [b, a, ty], [0, 0, 1]])
    if tipo == "afim":
        A = np.zeros((2 * len(o), 6))
        A[0::2, 0:3] = np.c_[x, y, u]
        A[1::2, 3:6] = np.c_[x, y, u]
        p = np.linalg.lstsq(A * sw[:, None], d.ravel() * sw, rcond=None)[0]
        return np.vstack([p.reshape(2, 3), [0, 0, 1]])
    if tipo == "homografia":
        # DLT com normalização de Hartley (essencial com coordenadas UTM ~10^6)
        def norm(p):
            c = p.mean(0)
            s = np.sqrt(2) / max(np.mean(np.linalg.norm(p - c, axis=1)), 1e-12)
            return np.array([[s, 0, -s * c[0]], [0, s, -s * c[1]], [0, 0, 1]])
        No, Nd = norm(o), norm(d)
        on, dn = aplicar(No, o), aplicar(Nd, d)
        x, y, X, Y = on[:, 0], on[:, 1], dn[:, 0], dn[:, 1]
        A = np.zeros((2 * len(o), 9))
        A[0::2] = np.c_[x, y, u, z, z, z, -X * x, -X * y, -X]
        A[1::2] = np.c_[z, z, z, x, y, u, -Y * x, -Y * y, -Y]
        H = np.linalg.svd(A * sw[:, None])[2][-1].reshape(3, 3)
        H = np.linalg.inv(Nd) @ H @ No
        return H / H[2, 2]
    raise ValueError(tipo)


def aplicar(M: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, float)
    h = np.c_[pts, np.ones(len(pts))] @ M.T
    return h[:, :2] / h[:, 2:3]


def residuos(M, origem, destino) -> np.ndarray:
    return np.linalg.norm(aplicar(M, origem) - np.asarray(destino, float), axis=1)


def salvar_georef(png: Path, e0: float, n0: float, res: float, epsg: int,
                  extra: dict | None = None) -> None:
    """Grava world file (.pgw/.jgw), .prj e um .json com os metadados.

    (e0, n0) é o canto superior esquerdo do pixel (0,0); res em m/px.
    QGIS/ArcGIS/AutoCAD Map leem o par imagem + world file diretamente.
    """
    png = Path(png)
    ext = {".png": ".pgw", ".jpg": ".jgw", ".jpeg": ".jgw", ".webp": ".wld"}[png.suffix.lower()]
    png.with_suffix(ext).write_text(
        f"{res:.6f}\n0\n0\n{-res:.6f}\n{e0 + res / 2:.4f}\n{n0 - res / 2:.4f}\n")
    png.with_suffix(".prj").write_text(CRS.from_epsg(epsg).to_wkt("WKT1_ESRI"))
    meta = {"epsg": epsg, "canto_sup_esq": [e0, n0], "res_m_px": res}
    meta.update(extra or {})
    png.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
