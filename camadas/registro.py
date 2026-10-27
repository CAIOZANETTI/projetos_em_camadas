"""Registro automático imagem↔imagem (SIFT + RANSAC).

Usos típicos:
  - alinhar um mosaico novo a um mosaico/ortofoto anterior (acompanhamento de obra);
  - alinhar uma prancha que já tem uma foto sobreposta (como o HTML-conceito)
    ao mosaico georreferenciado, herdando as coordenadas UTM;
  - alinhar imagem de satélite e drone.

Para prancha CAD × foto não há textura em comum: usar pontos de controle
(`camadas.geo.ajustar`) clicados no visualizador ou definidos em YAML.
"""
from __future__ import annotations

import cv2
import numpy as np

from . import geo


def _preparar(img: np.ndarray, lado: int) -> tuple[np.ndarray, float]:
    if img.ndim == 3:
        img = cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY)
    k = min(1.0, lado / max(img.shape[:2]))
    if k < 1:
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(2.0, (8, 8)).apply(img), k


def registrar(movel: np.ndarray, referencia: np.ndarray, tipo: str = "similaridade",
              lado: int = 2400, mascara_movel: np.ndarray | None = None) -> dict:
    """Encontra a transformação 3x3 que leva pixels de `movel` para pixels de `referencia`.

    Retorna {"M", "inliers", "residuo_px" (mediana, em px da referência), "pts_movel", "pts_ref"}.
    """
    a, ka = _preparar(movel, lado)
    b, kb = _preparar(referencia, lado)
    m = None
    if mascara_movel is not None:
        m = cv2.resize(mascara_movel.astype(np.uint8) * 255, a.shape[::-1], interpolation=cv2.INTER_NEAREST)
    sift = cv2.SIFT_create(nfeatures=12000)
    kpa, da = sift.detectAndCompute(a, m)
    kpb, db = sift.detectAndCompute(b, None)
    pares = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64}).knnMatch(da, db, k=2)
    bons = [p[0] for p in pares if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    pa = np.float32([kpa[g.queryIdx].pt for g in bons]) / ka
    pb = np.float32([kpb[g.trainIdx].pt for g in bons]) / kb
    if tipo == "homografia":
        M, inl = cv2.findHomography(pa, pb, cv2.RANSAC, 6.0 / kb)
    elif tipo == "afim":
        M, inl = cv2.estimateAffine2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=6.0 / kb)
    else:
        M, inl = cv2.estimateAffinePartial2D(pa, pb, method=cv2.RANSAC, ransacReprojThreshold=6.0 / kb)
    if M is None:
        raise RuntimeError("Registro falhou: poucos pontos em comum")
    inl = inl.ravel().astype(bool)
    M = M if M.shape == (3, 3) else np.vstack([M, [0, 0, 1]])
    # refina por mínimos quadrados só com os inliers
    M = geo.ajustar(pa[inl], pb[inl], tipo)
    r = geo.residuos(M, pa[inl], pb[inl])
    return {"M": M, "inliers": int(inl.sum()), "residuo_px": float(np.median(r)),
            "pts_movel": pa[inl], "pts_ref": pb[inl]}
