"""Leitura de metadados de fotos de drone (EXIF + XMP DJI).

Extrai o que o mosaico precisa: posição GPS, altitude relativa, rumo do voo,
distância focal e tamanho do sensor (para estimar o GSD).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

from PIL import Image

# Largura do sensor (mm) por modelo de câmera DJI. Completar conforme novos drones.
SENSOR_MM = {
    "FC7303": 6.17,   # DJI Mini 2  (1/2.3")
    "FC3582": 9.70,   # DJI Mini 3 Pro (1/1.3")
    "FC3411": 13.2,   # DJI Air 2S (1")
    "FC6310": 13.2,   # Phantom 4 Pro (1")
    "L1D-20c": 13.2,  # Mavic 2 Pro (1")
    "FC220": 6.17,    # Mavic Pro
}

_XMP_TAGS = ("RelativeAltitude", "AbsoluteAltitude", "FlightYawDegree",
             "GimbalYawDegree", "GimbalPitchDegree")


@dataclass
class FotoMeta:
    arquivo: str
    largura: int
    altura: int
    modelo: str
    focal_mm: float
    lat: float
    lon: float
    alt_abs: float
    alt_rel: float | None
    rumo: float | None          # FlightYawDegree, graus a partir do norte
    data: str | None

    @property
    def gsd(self) -> float | None:
        """Tamanho do pixel no terreno (m/px) em voo nadiral sobre terreno plano."""
        sensor = SENSOR_MM.get(self.modelo)
        if not (sensor and self.alt_rel and self.focal_mm):
            return None
        return self.alt_rel * sensor / (self.focal_mm * self.largura)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["gsd"] = self.gsd
        return d


def _dms(v, ref) -> float:
    g = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
    return -g if ref in ("S", "W") else g


def ler_meta(caminho: str | Path) -> FotoMeta:
    caminho = Path(caminho)
    im = Image.open(caminho)
    ex = im.getexif()
    gps = ex.get_ifd(0x8825)
    sub = ex.get_ifd(0x8769)
    if 2 not in gps:
        raise ValueError(f"{caminho.name}: foto sem GPS no EXIF")

    # O XMP da DJI fica no início do arquivo; 256 kB é suficiente.
    with open(caminho, "rb") as f:
        bruto = f.read(256_000).decode("latin1")
    xmp = {}
    for tag in _XMP_TAGS:
        m = re.search(rf'drone-dji:{tag}="([^"]+)"', bruto)
        xmp[tag] = float(m.group(1)) if m else None

    return FotoMeta(
        arquivo=str(caminho),
        largura=im.width,
        altura=im.height,
        modelo=str(ex.get(272, "")).strip("\x00 "),
        focal_mm=float(sub.get(0x920A, 0) or 0),
        lat=_dms(gps[2], gps[1]),
        lon=_dms(gps[4], gps[3]),
        alt_abs=float(gps.get(6, 0) or 0),
        alt_rel=xmp["RelativeAltitude"],
        rumo=xmp["FlightYawDegree"],
        data=sub.get(0x9003),
    )
