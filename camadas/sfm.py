"""Reconstrução 3D (SfM) das fotos de drone — nadirais + oblíquas — com pycolmap (CPU).

Pipeline:
  1. COLMAP: SIFT + casamento exaustivo + mapeamento incremental -> poses de todas
     as câmeras e nuvem esparsa (pycolmap 4.x, sem GPU);
  2. georreferenciamento 3D: similaridade (Umeyama) que leva os centros das câmeras
     do referencial do modelo para (E, N, Z) = (UTM SIRGAS 2000, altura relativa à
     decolagem); Z relativo evita o datum vago da altitude "absoluta" do drone;
  3. classificação nadir/oblíqua pela direção real do eixo óptico (o EXIF do DJI
     Mini 2 grava GimbalPitchDegree = 0 em todas as fotos, então não serve);
  4. densificação opcional por pares estéreo (retificação + SGBM do OpenCV), já que
     o MVS do COLMAP exige CUDA;
  5. exportação: PLY (abre no CloudCompare/Meshlab/QGIS 3D) e JSON compacto para o
     visualizador (three.js);
  6. ortofoto verdadeira: MDS da nuvem + projeção de cada pixel na foto nadiral mais a
     prumo (sem a paralaxe de prédios do mosaico 2D) + MDS em PNG 16 bits.

Uso:
    python -m camadas.sfm dados/foz/foto_drone saida/foz/sfm --denso --orto 0.04
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from . import geo
from .mosaico import ler_meta

LIMITE_NADIR_GRAUS = 20.0     # eixo óptico a menos de 20° da vertical = foto nadiral


# 1 -------------------------------------------------------------------------
def reconstruir(pasta: str | Path, trabalho: str | Path, max_lado: int = 2000,
                max_pontos: int = 8000, log=print):
    """Roda o SfM do COLMAP e devolve a maior reconstrução (pycolmap.Reconstruction)."""
    import pycolmap
    trabalho = Path(trabalho)
    trabalho.mkdir(parents=True, exist_ok=True)
    db = trabalho / "database.db"
    db.unlink(missing_ok=True)
    eo = pycolmap.FeatureExtractionOptions()
    eo.max_image_size = max_lado
    eo.sift.max_num_features = max_pontos
    ro = pycolmap.ImageReaderOptions()
    ro.camera_model = "OPENCV"            # focal + ponto principal + distorção k1 k2 p1 p2
    t = time.time()
    pycolmap.extract_features(db, pasta, camera_mode=pycolmap.CameraMode.SINGLE,
                              reader_options=ro, extraction_options=eo)
    pycolmap.match_exhaustive(db)
    mapas = pycolmap.incremental_mapping(db, pasta, trabalho)
    if not mapas:
        raise RuntimeError("SfM falhou: nenhuma reconstrução (pouca sobreposição entre fotos?)")
    rec = max(mapas.values(), key=lambda r: r.num_reg_images())
    log(f"SfM: {rec.num_reg_images()} fotos registradas, {rec.num_points3D()} pontos, "
        f"reprojeção média {rec.compute_mean_reprojection_error():.2f} px ({time.time() - t:.0f}s)")
    return rec


def _poses(rec) -> dict:
    """nome -> (R mundo->câmera 3x3, centro no referencial do modelo)."""
    out = {}
    for img in rec.images.values():
        if not img.has_pose:
            continue
        T = img.cam_from_world()
        R = T.rotation.matrix()
        out[img.name] = (R, -R.T @ T.translation)
    return out


# 2 -------------------------------------------------------------------------
def umeyama(origem: np.ndarray, destino: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Similaridade 3D (s, R, t) de mínimos quadrados: destino ≈ s·R·origem + t."""
    mo, md = origem.mean(0), destino.mean(0)
    a, b = origem - mo, destino - md
    U, S, Vt = np.linalg.svd(b.T @ a / len(a))
    D = np.eye(3)
    D[2, 2] = np.sign(np.linalg.det(U @ Vt))
    R = U @ D @ Vt
    s = float(np.trace(np.diag(S) @ D) / (a ** 2).sum(1).mean())
    return s, R, md - s * R @ mo


def georreferenciar(rec, pasta: str | Path, epsg: int | None = None) -> dict:
    """Similaridade modelo -> (E, N, Z_rel) pelos centros GPS das câmeras."""
    pasta = Path(pasta)
    poses = _poses(rec)
    metas = {n: ler_meta(pasta / n) for n in poses}
    lon0 = np.mean([m["lon"] for m in metas.values()])
    lat0 = np.mean([m["lat"] for m in metas.values()])
    epsg = epsg or geo.epsg_utm_sirgas(lon0, lat0)
    nomes = sorted(poses)
    E, N = geo.para_utm([metas[n]["lon"] for n in nomes], [metas[n]["lat"] for n in nomes], epsg)
    Z = [metas[n]["alt_rel"] or 0.0 for n in nomes]
    dest = np.c_[E, N, Z]
    orig = np.array([poses[n][1] for n in nomes])
    s, R, t = umeyama(orig, dest)
    res = np.linalg.norm((s * (R @ orig.T)).T + t - dest, axis=1)
    return {"epsg": epsg, "s": s, "R": R, "t": t, "nomes": nomes, "metas": metas, "poses": poses,
            "residuo_gps_m": dict(zip(nomes, res.round(2).tolist())),
            "rmse_gps_m": float(np.sqrt(np.mean(res ** 2))),
            "alt_decolagem_m": float(np.median([m["alt_abs"] - (m["alt_rel"] or 0) for m in metas.values()]))}


def para_mundo(g: dict, X: np.ndarray) -> np.ndarray:
    return (g["s"] * (g["R"] @ np.asarray(X, float).T)).T + g["t"]


# 3 -------------------------------------------------------------------------
def cameras(rec, g: dict, limite_nadir: float = LIMITE_NADIR_GRAUS) -> list[dict]:
    """Pose de cada foto no mundo + classificação nadir/oblíqua pelo eixo óptico."""
    cam = next(iter(rec.cameras.values()))
    out = []
    for n in g["nomes"]:
        R, C = g["poses"][n]
        Rw = g["R"] @ R.T                         # eixos da câmera no mundo (E, N, Z)
        eixo = Rw @ [0, 0, 1]                     # direção de visada
        topo = Rw @ [0, -1, 0]                    # "para cima" na imagem
        ang = float(np.degrees(np.arccos(np.clip(-eixo[2], -1, 1))))
        rumo = float(np.degrees(np.arctan2(eixo[0], eixo[1])) % 360)
        m = g["metas"][n]
        out.append({"nome": n, "centro": para_mundo(g, C[None])[0].round(3).tolist(),
                    "eixo": eixo.round(5).tolist(), "topo": topo.round(5).tolist(),
                    "angulo_vertical": round(ang, 1), "rumo_visada": round(rumo, 1),
                    "tipo": "nadir" if ang < limite_nadir else "obliqua",
                    "data": m["data"], "alt_rel": m["alt_rel"],
                    "largura": cam.width, "altura": cam.height,
                    "focal_px": float(cam.params[0]), "residuo_gps_m": g["residuo_gps_m"][n]})
    return out


# 4 -------------------------------------------------------------------------
def _intrinsecos(rec):
    cam = next(iter(rec.cameras.values()))
    fx, fy, cx, cy, k1, k2, p1, p2 = cam.params
    K = np.array([[fx, 0, cx], [0, fy, cy], [0, 0, 1]])
    return K, np.array([k1, k2, p1, p2]), (cam.width, cam.height)


def pares_estereo(g: dict, cams: list[dict], base_min: float = 0.08, base_max: float = 1.0,
                  ang_max: float = 50.0) -> list[tuple[str, str]]:
    """Pares bons para estéreo: base/altura entre limites e eixos ópticos parecidos."""
    pares = []
    for i, a in enumerate(cams):
        for b in cams[i + 1:]:
            ca, cb = np.array(a["centro"]), np.array(b["centro"])
            h = max(1.0, (ca[2] + cb[2]) / 2)
            r = np.linalg.norm(ca - cb) / h
            dang = np.degrees(np.arccos(np.clip(np.dot(a["eixo"], b["eixo"]), -1, 1)))
            if base_min <= r <= base_max and dang <= ang_max:
                pares.append((a["nome"], b["nome"]))
    return pares


def densificar(rec, g: dict, pasta: str | Path, pares: list[tuple[str, str]], lado: int = 1600,
               passo: int = 2, tol_m: float = 1.0, log=print) -> tuple[np.ndarray, np.ndarray]:
    """Nuvem densa por estéreo retificado (SGBM) em cada par; devolve (XYZ mundo, RGB).

    Base vertical (comum em voo nadiral: fotos em fila no sentido do "topo" da imagem)
    é tratada transpondo as imagens retificadas, para o SGBM varrer ao longo de x.
    A profundidade sai de Z = -f·B/d em vez do Q do OpenCV (convenção de sinal única).
    Cada par é validado contra os pontos esparsos do SfM: se a superfície densa ficar a
    mais de `tol_m` (mediana) dos pontos esparsos, o par é descartado.
    """
    esparsa, _ = nuvem_esparsa(rec, g)
    pasta = Path(pasta)
    K, D, (W, H) = _intrinsecos(rec)
    k = lado / max(W, H)
    Kr = K.copy()
    Kr[:2] *= k
    tam = (int(round(W * k)), int(round(H * k)))   # noqa: RUF046 — numpy 1.x: round(np.float64) é float
    imgs = {i.name: i for i in rec.images.values()}
    pts, cores = [], []
    for na, nb in pares:
        Ra, Ca = g["poses"][na]
        Rb, Cb = g["poses"][nb]
        R = Rb @ Ra.T                                  # câmera a -> câmera b
        T = Rb @ (Ca - Cb)
        R1, R2, P1, P2, _, _, _ = cv2.stereoRectify(Kr, D, Kr, D, tam, R, T.reshape(3, 1), alpha=0)
        eixo = 0 if abs(P2[0, 3]) > abs(P2[1, 3]) else 1          # 0: base em x, 1: base em y
        f, cx, cy = P1[0, 0], P1[0, 2], P1[1, 2]
        B = P2[eixo, 3] / P2[eixo, eixo]
        dmin, ndisp = _faixa_disparidade(rec, imgs[na], imgs[nb], Ra, Ca, R1, P1, P2, eixo)
        largura = tam[eixo]
        if ndisp is None or ndisp > 0.4 * largura:
            log(f"  denso {na} × {nb}: geometria ruim para estéreo (disparidade {dmin}…"
                f"{dmin + (ndisp or 0)} px em {largura} px), ignorado")
            continue
        ra, rb = (cv2.remap(np.dstack([cv2.resize(cv2.imread(str(pasta / n)), tam, interpolation=cv2.INTER_AREA),
                                       np.full(tam[::-1], 255, np.uint8)]),
                            *cv2.initUndistortRectifyMap(Kr, D, Rr, Pr, tam, cv2.CV_32FC1), cv2.INTER_LINEAR)
                  for n, Rr, Pr in ((na, R1, P1), (nb, R2, P2)))
        if eixo == 1:
            ra, rb = ra.transpose(1, 0, 2).copy(), rb.transpose(1, 0, 2).copy()
        ga, gb = cv2.cvtColor(ra[..., :3], cv2.COLOR_BGR2GRAY), cv2.cvtColor(rb[..., :3], cv2.COLOR_BGR2GRAY)
        # a retificação desloca os pontos principais: desloca b em dmin px para a faixa começar em 0
        desloc = np.float32([[1, 0, dmin], [0, 1, 0]])
        gb = cv2.warpAffine(gb, desloc, gb.shape[::-1])
        # pixels válidos (dentro da foto) em a e, deslocados, em b — com margem do bloco
        va = cv2.erode(ra[..., 3], np.ones((9, 9), np.uint8)) == 255
        vb = cv2.erode(cv2.warpAffine(rb[..., 3], desloc, gb.shape[::-1]), np.ones((9, 9), np.uint8)) == 255
        sg = cv2.StereoSGBM_create(minDisparity=0, numDisparities=ndisp, blockSize=5,
                                   P1=8 * 25, P2=32 * 25, uniquenessRatio=10, speckleWindowSize=100,
                                   speckleRange=2, disp12MaxDiff=1, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
        disp = sg.compute(ga, gb).astype(np.float32) / 16
        ok = (disp > 0) & va
        lin, col = np.indices(disp.shape)
        cb = np.clip(np.round(col - disp).astype(int), 0, disp.shape[1] - 1)
        ok &= vb[lin, cb]                               # correspondente em b também é válido
        disp += dmin
        sub = np.zeros_like(ok)
        sub[::passo, ::passo] = True
        v, u = np.nonzero(ok & sub)
        d = disp[v, u]
        x, y = (u, v) if eixo == 0 else (v, u)         # volta ao referencial retificado
        Z = -f * B / d
        Xr = np.c_[(x - cx) * Z / f, (y - cy) * Z / f, Z]
        frente = Z > 0
        xyz = para_mundo(g, (Ra.T @ (R1.T @ Xr[frente].T)).T + Ca)
        desvio = _desvio_vertical(xyz, esparsa)
        if not desvio < tol_m:
            log(f"  denso {na} × {nb}: descartado, superfície a {desvio:.1f} m dos pontos do SfM")
            continue
        pts.append(xyz)
        cores.append(ra[v, u, :3][frente][:, ::-1])
        log(f"  denso {na} × {nb}: {frente.sum():,} pontos (base em {'xy'[eixo]}, desvio {desvio:.2f} m)")
    if not pts:
        return np.zeros((0, 3)), np.zeros((0, 3), np.uint8)
    return np.vstack(pts), np.vstack(cores).astype(np.uint8)


def _celula(pontos: np.ndarray, origem: np.ndarray, tamanho_m: float) -> np.ndarray:
    """Chave inteira da célula de `tamanho_m` de cada ponto (x, y) — para agrupar sem dicionário."""
    k = np.floor((pontos[:, :2] - origem) / tamanho_m).astype(np.int64)
    return k[:, 0] * 1_000_003 + k[:, 1]


def _desvio_vertical(densa: np.ndarray, esparsa: np.ndarray, celula: float = 1.0) -> float:
    """Mediana de |z_densa − z_esparsa| nas células de 1 m que têm os dois."""
    if len(densa) < 100:
        return np.inf
    o = esparsa[:, :2].min(0)
    kd, ke = _celula(densa, o, celula), _celula(esparsa, o, celula)
    ordem = np.argsort(kd)
    kd, zd = kd[ordem], densa[ordem, 2]
    ini = np.searchsorted(kd, ke, "left")
    fim = np.searchsorted(kd, ke, "right")
    dif = [abs(np.median(zd[a:b]) - z) for a, b, z in zip(ini, fim, esparsa[:, 2]) if b - a >= 3]
    return float(np.median(dif)) if len(dif) >= 20 else np.inf


def _faixa_disparidade(rec, ia, ib, Ra, Ca, R1, P1, P2, eixo):
    """Disparidade mínima e número de disparidades (múltiplo de 16) pelos pontos esparsos do par."""
    ids_a = {p.point3D_id for p in ia.points2D if p.has_point3D()}
    ids_b = {p.point3D_id for p in ib.points2D if p.has_point3D()}
    comuns = list(ids_a & ids_b)
    if len(comuns) < 20:
        return 0, None
    X = np.array([rec.points3D[i].xyz for i in comuns])
    Xr = np.c_[(R1 @ Ra @ (X - Ca).T).T, np.ones(len(X))]     # referencial retificado de a
    xa, xb = Xr @ P1.T, Xr @ P2.T
    d = xa[:, eixo] / xa[:, 2] - xb[:, eixo] / xb[:, 2]
    lo, hi = np.percentile(d, [1, 99])
    dmin = int(np.floor(lo - 0.25 * (hi - lo) - 8))
    ndisp = int(np.ceil(((hi - lo) * 1.5 + 16) / 16)) * 16
    return dmin, ndisp


# 5 -------------------------------------------------------------------------
def nuvem_esparsa(rec, g: dict, max_erro_px: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    P = [(p.xyz, p.color) for p in rec.points3D.values() if p.error < max_erro_px]
    xyz = para_mundo(g, np.array([a for a, _ in P]))
    return xyz, np.array([c for _, c in P], np.uint8)


def filtrar(xyz: np.ndarray, rgb: np.ndarray, esparsa: np.ndarray | None = None, voxel: float = 0.15,
            celula: float = 5.0, abaixo_m: float = 2.0, acima_m: float = 30.0):
    """Remove pontos espúrios e reduz por voxel.

    Com a nuvem esparsa do SfM como referência, cada ponto precisa estar numa célula de
    `celula` m com apoio esparso e entre (mín − abaixo_m) e (máx + acima_m) dos pontos
    esparsos da célula: o lixo do estéreo cai quase sempre "abaixo do chão".
    """
    if len(xyz) == 0:
        return xyz, rgb
    if esparsa is not None and len(esparsa):
        o = esparsa[:, :2].min(0) - celula
        ke = _celula(esparsa, o, celula)
        cel, inv = np.unique(ke, return_inverse=True)
        zmin = np.full(len(cel), np.inf)
        zmax = np.full(len(cel), -np.inf)
        np.minimum.at(zmin, inv, esparsa[:, 2])
        np.maximum.at(zmax, inv, esparsa[:, 2])
        kd = _celula(xyz, o, celula)
        lo = np.full(len(xyz), np.inf)
        hi = np.full(len(xyz), -np.inf)
        for dx in (-1, 0, 1):                       # apoio na célula ou nas 8 vizinhas
            for dy in (-1, 0, 1):
                kv = kd + dx * 1_000_003 + dy
                i = np.clip(np.searchsorted(cel, kv), 0, len(cel) - 1)
                tem = cel[i] == kv
                lo[tem] = np.minimum(lo[tem], zmin[i[tem]])
                hi[tem] = np.maximum(hi[tem], zmax[i[tem]])
        ok = (xyz[:, 2] > lo - abaixo_m) & (xyz[:, 2] < hi + acima_m)
        xyz, rgb = xyz[ok], rgb[ok]
    chave = np.floor(xyz / voxel).astype(np.int64)
    _, idx = np.unique(chave, axis=0, return_index=True)
    return xyz[idx], rgb[idx]


def salvar_ply(caminho: str | Path, xyz: np.ndarray, rgb: np.ndarray) -> None:
    """PLY binário com coordenadas UTM (double) + cor."""
    dt = np.dtype([("x", "<f8"), ("y", "<f8"), ("z", "<f8"), ("r", "u1"), ("g", "u1"), ("b", "u1")])
    a = np.empty(len(xyz), dt)
    a["x"], a["y"], a["z"] = xyz.T
    a["r"], a["g"], a["b"] = rgb.T
    cab = ("ply\nformat binary_little_endian 1.0\n"
           f"element vertex {len(a)}\nproperty double x\nproperty double y\nproperty double z\n"
           "property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n")
    with open(caminho, "wb") as f:
        f.write(cab.encode())
        f.write(a.tobytes())


def pacote_visualizador(xyz: np.ndarray, rgb: np.ndarray, cams: list[dict], origem=None,
                        max_pontos: int = 400_000) -> dict:
    """JSON compacto: posições em cm inteiros relativas a uma origem (E0, N0, 0)."""
    if len(xyz) > max_pontos:
        sel = np.random.default_rng(0).choice(len(xyz), max_pontos, replace=False)
        xyz, rgb = xyz[sel], rgb[sel]
    o = np.array(origem if origem is not None else [np.floor(xyz[:, 0].mean()), np.floor(xyz[:, 1].mean()), 0.0])
    rel = np.round((xyz - o) * 100).astype(np.int32)
    import base64
    return {"origem": o.tolist(), "n": len(rel),
            "pos_cm_b64": base64.b64encode(rel.astype("<i4").tobytes()).decode(),
            "rgb_b64": base64.b64encode(rgb.astype(np.uint8).tobytes()).decode(),
            "cameras": [{**c, "centro": (np.array(c["centro"]) - o).round(3).tolist()} for c in cams]}


# 6 -------------------------------------------------------------------------
def mds(xyz: np.ndarray, res: float = 0.25, extensao=None, fechar_m: float = 20.0,
        fechar_telhado_m: float = 2.0) -> dict:
    """Modelo digital de superfície em grade (maior z por célula), com buracos preenchidos.

    Buracos até ~`fechar_m` são preenchidos por inpaint; o resto fica com a mediana
    do terreno (para a ortofoto continuar contínua). Retorna {"z", "e0", "n1", "res", "valido"}.
    """
    e0, n0, e1, n1 = extensao or (xyz[:, 0].min(), xyz[:, 1].min(), xyz[:, 0].max(), xyz[:, 1].max())
    W, H = int(np.ceil((e1 - e0) / res)), int(np.ceil((n1 - n0) / res))
    c = ((xyz[:, 0] - e0) / res).astype(int)
    l = ((n1 - xyz[:, 1]) / res).astype(int)
    ok = (c >= 0) & (c < W) & (l >= 0) & (l < H)
    z = np.full((H, W), -np.inf, np.float32)
    np.maximum.at(z, (l[ok], c[ok]), xyz[ok, 2].astype(np.float32))
    valido = np.isfinite(z)
    base = float(np.median(z[valido])) if valido.any() else 0.0
    # remove picos isolados; fechamento (máx -> mín) preenche buracos de telhado na cota
    # do telhado — sem isso o buraco vira "chão" e o telhado sai torto na ortofoto
    zf = np.where(valido, z, base).astype(np.float32)
    zf = np.where(valido, cv2.medianBlur(zf, 5), zf)
    k = max(3, int(round(fechar_telhado_m / res)) | 1)   # noqa: RUF046 — idem
    baixo = np.where(valido, zf, -1e4).astype(np.float32)
    fech = cv2.erode(cv2.dilate(baixo, np.ones((k, k), np.uint8)), np.ones((k, k), np.uint8))
    novos = ~valido & (fech > -1e3)
    zf[novos] = fech[novos]
    valido = valido | novos
    lo, hi = float(zf.min()), float(zf.max())
    u8 = np.uint8((zf - lo) / max(hi - lo, 1e-6) * 255)
    raio = max(3, int(fechar_m / res / 4))
    cheio = cv2.inpaint(u8, np.uint8(~valido) * 255, raio, cv2.INPAINT_TELEA).astype(np.float32)
    zf = np.where(valido, zf, cheio / 255 * (hi - lo) + lo)
    return {"z": zf, "e0": float(e0), "n1": float(n1), "res": res, "valido": valido}


def _projetar(rec, g: dict, nome: str, E, N, Z):
    """Pixel (u, v) na foto original de pontos do mundo, com o modelo OPENCV do COLMAP."""
    R, C = g["poses"][nome]
    Xw = np.stack([E, N, Z], -1).reshape(-1, 3)
    Xm = (g["R"].T @ (Xw - g["t"]).T).T / g["s"]          # mundo -> modelo
    Xc = (R @ (Xm - C).T).T                               # modelo -> câmera
    cam = next(iter(rec.cameras.values()))
    fx, fy, cx, cy, k1, k2, p1, p2 = cam.params
    z = Xc[:, 2]
    x, y = Xc[:, 0] / z, Xc[:, 1] / z
    r2 = x * x + y * y
    rad = 1 + k1 * r2 + k2 * r2 * r2
    xd = x * rad + 2 * p1 * x * y + p2 * (r2 + 2 * x * x)
    yd = y * rad + p1 * (r2 + 2 * y * y) + 2 * p2 * x * y
    u, v = fx * xd + cx, fy * yd + cy
    u[z <= 0] = -1
    return u.reshape(E.shape).astype(np.float32), v.reshape(E.shape).astype(np.float32)


def ortofoto(rec, g: dict, pasta: str | Path, xyz: np.ndarray, saida: str | Path, fotos: list[str],
             res: float = 0.04, res_mds: float = 0.25, margem: float = 0.0, log=print) -> dict:
    """Ortofoto verdadeira: cada pixel (E, N) recebe z do MDS e é projetado na foto mais a
    prumo que o vê (centro da imagem mais próximo), com costura suavizada como no mosaico.
    Sem teste de oclusão: em fotos nadirais isso só afeta paredes de prédios altos."""
    pasta, saida = Path(pasta), Path(saida)
    cam = next(iter(rec.cameras.values()))
    Wc, Hc = cam.width, cam.height
    # extensão: pegadas das fotos no plano do terreno mediano
    zmed = float(np.median(xyz[:, 2]))
    cantos = []
    for n in fotos:
        R, C = g["poses"][n]
        K = np.array([[cam.params[0], 0, cam.params[2]], [0, cam.params[1], cam.params[3]], [0, 0, 1]])
        raios = (R.T @ np.linalg.inv(K) @ np.array([[0, Wc, Wc, 0], [0, 0, Hc, Hc], [1, 1, 1, 1]])).T
        Cw = para_mundo(g, C[None])[0]
        dw = (g["R"] @ raios.T).T
        t = (zmed - Cw[2]) / dw[:, 2]
        cantos.append(Cw + t[:, None] * dw)
    cantos = np.vstack(cantos)
    e0, n0 = cantos[:, :2].min(0) - margem
    e1, n1 = cantos[:, :2].max(0) + margem
    M = mds(xyz, res_mds, (e0, n0, e1, n1))
    W, H = int(np.ceil((e1 - e0) / res)), int(np.ceil((n1 - n0) / res))
    log(f"Ortofoto {W}x{H}px a {res * 100:.1f} cm/px ({e1 - e0:.0f} x {n1 - n0:.0f} m), MDS a {res_mds} m")
    Z = cv2.resize(M["z"], (W, H), interpolation=cv2.INTER_LINEAR)
    E, N = np.meshgrid(e0 + (np.arange(W) + .5) * res, n1 - (np.arange(H) + .5) * res)
    melhor = np.full((H, W), np.inf, np.float32)
    rotulo = np.full((H, W), -1, np.int16)
    mapas = []
    for k, n in enumerate(fotos):
        u, v = _projetar(rec, g, n, E, N, Z)
        dentro = (u >= 2) & (u < Wc - 3) & (v >= 2) & (v < Hc - 3)
        d = (u - Wc / 2) ** 2 + (v - Hc / 2) ** 2
        m = dentro & (d < melhor)
        melhor[m], rotulo[m] = d[m], k
        mapas.append((u, v, dentro))
    del melhor
    sigma = max(1.0 / res, 1.0)
    acc = np.zeros((H, W, 3), np.float32)
    soma = np.zeros((H, W), np.float32)
    for k, n in enumerate(fotos):
        u, v, dentro = mapas[k]
        w = cv2.GaussianBlur((rotulo == k).astype(np.float32), (0, 0), sigma) * dentro
        img = cv2.imread(str(pasta / n), cv2.IMREAD_COLOR)
        acc += cv2.remap(img, u, v, cv2.INTER_LINEAR).astype(np.float32) * w[..., None]
        soma += w
        del img
    vazio = soma < 1e-6
    out = (acc / np.maximum(soma, 1e-6)[..., None]).clip(0, 255).astype(np.uint8)
    out[vazio] = 255
    saida.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(saida), out, [cv2.IMWRITE_JPEG_QUALITY, 90])
    info = {"tipo": "ortofoto verdadeira (SfM + MDS)", "fotos": fotos, "res_m_px": res,
            "extensao_utm": [float(e0), float(n0), float(e1), float(n1)], "largura": W, "altura": H,
            "rmse_gps_m": g["rmse_gps_m"], "mds_res_m": res_mds}
    geo.salvar_georef(saida, float(e0), float(n1), res, g["epsg"], info)
    # MDS como PNG 16 bits (cm acima de zmin) + world file, para QGIS e para o visualizador
    zmin = float(M["z"].min())
    z16 = np.clip((M["z"] - zmin) * 100, 0, 65535).astype(np.uint16)
    mds_png = saida.with_name(saida.stem + "_mds.png")
    cv2.imwrite(str(mds_png), z16)
    geo.salvar_georef(mds_png, M["e0"], M["n1"], res_mds, g["epsg"],
                      {"z_min_m": zmin, "escala": "cm acima de z_min", "z": "altura sobre a decolagem"})
    log(f"Gravado {saida} e {mds_png.name}")
    return info



def executar(pasta, saida, denso: bool = False, orto_res: float | None = None, log=print) -> dict:
    saida = Path(saida)
    rec = reconstruir(pasta, saida / "colmap", log=log)
    g = georreferenciar(rec, pasta)
    cams = cameras(rec, g)
    log(f"Georreferenciamento 3D pelo GPS: RMSE {g['rmse_gps_m']:.2f} m (EPSG:{g['epsg']}, Z = altura "
        f"sobre a decolagem; decolagem ≈ {g['alt_decolagem_m']:.0f} m no altímetro do drone)")
    log("Classificação: " + ", ".join(f"{c['nome']}={c['tipo']}({c['angulo_vertical']:.0f}°)" for c in cams))
    xyz, rgb = nuvem_esparsa(rec, g)
    if denso:
        pares = pares_estereo(g, cams)
        log(f"Densificando {len(pares)} pares estéreo…")
        d_xyz, d_rgb = densificar(rec, g, pasta, pares, log=log)
        xyz, rgb = np.vstack([xyz, d_xyz]), np.vstack([rgb, d_rgb])
    xyz, rgb = filtrar(xyz, rgb, nuvem_esparsa(rec, g)[0])
    salvar_ply(saida / "nuvem.ply", xyz, rgb)
    rel = {"epsg": g["epsg"], "rmse_gps_m": g["rmse_gps_m"], "residuo_gps_m": g["residuo_gps_m"],
           "alt_decolagem_m": g["alt_decolagem_m"], "n_pontos": len(xyz), "cameras": cams,
           "reprojecao_px": rec.compute_mean_reprojection_error()}
    (saida / "sfm.json").write_text(json.dumps(rel, indent=2, ensure_ascii=False))
    np.savez_compressed(saida / "nuvem.npz", xyz=xyz, rgb=rgb)
    log(f"Gravado {saida / 'nuvem.ply'} ({len(xyz):,} pontos) e sfm.json")
    if orto_res:
        nadir = [c["nome"] for c in cams if c["tipo"] == "nadir"]
        rel["ortofoto"] = ortofoto(rec, g, pasta, xyz, saida / "ortofoto.jpg", nadir, orto_res, log=log)
        (saida / "sfm.json").write_text(json.dumps(rel, indent=2, ensure_ascii=False))
    return rel


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reconstrução 3D (SfM) de fotos de drone")
    ap.add_argument("pasta", help="pasta com TODAS as fotos (nadirais e oblíquas)")
    ap.add_argument("saida", help="pasta de saída")
    ap.add_argument("--denso", action="store_true", help="densifica por pares estéreo (SGBM)")
    ap.add_argument("--orto", type=float, metavar="RES", help="gera ortofoto verdadeira com RES m/px (ex.: 0.04)")
    a = ap.parse_args(argv)
    executar(a.pasta, a.saida, a.denso, a.orto)


if __name__ == "__main__":
    main()


def ajustar_vertical(xyz: np.ndarray, pontos: list[dict], raio_m: float = 2.0, min_pontos: int = 30) -> dict:
    """Plano de correção z_nuvem -> cota a partir de pontos com cota conhecida no terreno (ex.: boca de sondagem).

    Terreno no ponto = percentil 10 da nuvem num raio de 2 m (até 5 m se faltar ponto): descarta telhado e copa.
    Ponto sob copa ou edificação dá diferença absurda e sai pela regra robusta (|resíduo| > max(3·MAD, 1,5 m) contra
    a mediana). Com 6 ou mais pontos válidos ajusta cota = z + a + b·(E − E0) + c·(N − N0) — o SfM georreferenciado
    pelo GPS do drone fica inclinado —; com menos, só o offset. A validação cruzada (deixa-um-fora) mede a qualidade.
    `pontos`: [{"id", "E", "N", "cota"}] no mesmo referencial horizontal da nuvem.
    """
    linhas = []
    for p in pontos:
        dist = np.hypot(xyz[:, 0] - p["E"], xyz[:, 1] - p["N"])
        for raio in (raio_m, raio_m * 1.5, raio_m * 2.5):
            perto = dist < raio
            if perto.sum() >= min_pontos:
                break
        z = float(np.percentile(xyz[perto, 2], 10)) if perto.sum() >= min_pontos else None
        linhas.append({**p, "z_nuvem": z, "n_pontos": int(perto.sum()), "raio_m": raio})
    validos = [l for l in linhas if l["z_nuvem"] is not None]
    if not validos:
        return {"ok": False, "motivo": "nenhum ponto com nuvem em volta", "pontos": linhas}
    diferenca = np.array([l["cota"] - l["z_nuvem"] for l in validos])
    mediana = np.median(diferenca)
    limite = max(3 * 1.4826 * np.median(np.abs(diferenca - mediana)), 1.5)
    for l, d in zip(validos, diferenca):
        l["descartado"] = bool(abs(d - mediana) > limite)
    usados = [l for l in validos if not l["descartado"]]
    centro = np.mean([[l["E"], l["N"]] for l in usados], axis=0)
    matriz = np.array([[1.0, l["E"] - centro[0], l["N"] - centro[1]] for l in usados])
    alvo = np.array([l["cota"] - l["z_nuvem"] for l in usados])
    colunas = 3 if len(usados) >= 6 else 1
    coef = np.zeros(3)
    coef[:colunas] = np.linalg.lstsq(matriz[:, :colunas], alvo, rcond=None)[0]
    erros_cruzados = []
    for i in range(len(usados)):
        resto = np.arange(len(usados)) != i
        ci = np.linalg.lstsq(matriz[resto, :colunas], alvo[resto], rcond=None)[0]
        erros_cruzados.append(alvo[i] - matriz[i, :colunas] @ ci)
    for l in usados:
        l["residuo_m"] = round(float(l["cota"] - l["z_nuvem"] - coef @ [1, l["E"] - centro[0], l["N"] - centro[1]]), 3)
    return {"ok": True, "modelo": "plano" if colunas == 3 else "offset", "offset_m": float(coef[0]),
            "inclinacao_e": float(coef[1]), "inclinacao_n": float(coef[2]), "centro": centro.tolist(),
            "rms_validacao_cruzada_m": float(np.sqrt(np.mean(np.square(erros_cruzados)))),
            "usados": len(usados), "descartados": [l["id"] for l in validos if l["descartado"]],
            "sem_nuvem": [l["id"] for l in linhas if l["z_nuvem"] is None], "pontos": linhas}


def aplicar_vertical(xyz: np.ndarray, ajuste: dict) -> np.ndarray:
    """z da nuvem -> cota pelo plano de `ajustar_vertical` (x, y no mesmo referencial do ajuste)."""
    e0, n0 = ajuste["centro"]
    cota = xyz.copy()
    cota[:, 2] += ajuste["offset_m"] + ajuste["inclinacao_e"] * (xyz[:, 0] - e0) + ajuste["inclinacao_n"] * (xyz[:, 1] - n0)
    return cota


def metadados() -> dict:
    """Rastreabilidade: de onde vem cada método e constante deste módulo (regra 9 do estilo)."""
    return {
        "modulo": "sfm",
        "descricao": "3D por SfM (COLMAP), estéreo SGBM, georreferência por similaridade 3D, MDS e ortofoto verdadeira",
        "funcoes": ["reconstruir", "georreferenciar", "cameras", "densificar", "filtrar", "mds", "ortofoto", "executar",
                    "ajustar_vertical", "aplicar_vertical"],
        "bibliografia": [
            {"obra": "Schönberger & Frahm — Structure-from-Motion Revisited (COLMAP)", "ano": 2016, "editora": "CVPR",
             "aplicacao": {"reconstruir": ["OPENCV (modelo de câmera)", "max_lado", "max_pontos"]}},
            {"obra": "Umeyama — Least-squares estimation of transformation parameters between two point patterns",
             "ano": 1991, "editora": "IEEE TPAMI", "aplicacao": {"umeyama": ["s", "R", "t"]}},
            {"obra": "Hirschmüller — Stereo Processing by Semiglobal Matching and Mutual Information", "ano": 2008,
             "editora": "IEEE TPAMI", "aplicacao": {"densificar": ["blockSize=5", "P1=8·25", "P2=32·25", "uniquenessRatio=10"]}},
            {"obra": "Bradski & Kaehler — Learning OpenCV (retificação estéreo, stereoRectify)", "ano": 2008,
             "editora": "O'Reilly", "aplicacao": {"densificar": ["Z = -f·B/d"]}},
        ],
        "premissas": [
            {"aplicacao": {"cameras": ["LIMITE_NADIR_GRAUS"]},
             "fonte": "medido em Foz: nadirais a 3–4°, oblíquas a 41–42° da vertical; 20° separa com folga"},
            {"aplicacao": {"densificar": ["tol_m=1,0"], "pares_estereo": ["base_min=0,08", "base_max=1,0", "ang_max=50"]},
             "fonte": "calibrado em Foz (pares validados com desvio de 3–14 cm contra o SfM)"},
            {"aplicacao": {"ajustar_vertical": ["raio_m=2,0", "min_pontos=30", "percentil 10", "max(3·MAD, 1,5 m)"]},
             "fonte": "calibrado em Foz: 12 de 16 furos SPT usados, 3 sob copa/edificação descartados, 1 sem nuvem; "
                      "plano com validação cruzada de 0,23 m contra 0,59 m do offset constante"},
            {"aplicacao": {"mds": ["fechar_telhado_m=2,0", "fechar_m=20"]},
             "fonte": "calibrado em Foz: corrigiu o prédio administrativo torto (buracos de telhado preenchidos como chão)"},
        ],
        "ultima_revisao": "2026-10-27",
    }
