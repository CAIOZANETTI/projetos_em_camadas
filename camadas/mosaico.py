"""Mosaico georreferenciado a partir de fotos nadirais de drone.

Pipeline (sem GPU, só numpy + OpenCV + pyproj):
  1. lê EXIF/XMP (GPS, altitude, rumo) e monta, para cada foto, uma posição
     "a priori" no terreno (GPS + rumo do voo + GSD pela altitude);
  2. detecta pontos SIFT e casa todos os pares (RANSAC); um par só é aceito se
     a transformação encontrada for coerente com o GPS (descarta casamentos
     espúrios em mata/água e permite aceitar pares fracos porém corretos);
  3. para cada grupo de fotos ligadas, resolve num único sistema linear a
     geometria relativa pelos pontos casados (sem acúmulo de erro em cadeia) e
     leva o grupo às posições GPS por uma similaridade; fotos sem vizinho
     casado entram posicionadas só pelo GPS + rumo + GSD;
  4. reamostra tudo numa grade norte-para-cima em m/px (SIRGAS 2000 / UTM),
     escolhendo em cada pixel a foto mais "a prumo" (centro mais próximo),
     com costura suavizada;
  5. grava JPG/PNG + world file + .prj + relatório JSON.

Não é ortofoto (não corrige relevo nem paralaxe de árvores e edificações):
para isso usar OpenDroneMap. Serve bem para sobrepor projeto em obras pequenas.

Uso:
    python -m camadas.mosaico PASTA_FOTOS saida/mosaico.jpg --res 0.04
"""
from __future__ import annotations

import argparse
import itertools
import re
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from . import geo

EXTENSOES = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}


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


def _dms(v, ref) -> float:
    g = float(v[0]) + float(v[1]) / 60 + float(v[2]) / 3600
    return -g if ref in ("S", "W") else g


def ler_meta(caminho: str | Path) -> dict:
    """GPS, altitude relativa (XMP DJI), rumo do voo e câmera; `gsd` em m/px para voo nadiral sobre plano."""
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

    meta = {"arquivo": str(caminho), "largura": im.width, "altura": im.height,
            "modelo": str(ex.get(272, "")).strip("\x00 "), "focal_mm": float(sub.get(0x920A, 0) or 0),
            "lat": _dms(gps[2], gps[1]), "lon": _dms(gps[4], gps[3]), "alt_abs": float(gps.get(6, 0) or 0),
            "alt_rel": xmp["RelativeAltitude"], "rumo": xmp["FlightYawDegree"], "data": sub.get(0x9003)}
    sensor = SENSOR_MM.get(meta["modelo"])
    meta["gsd"] = (meta["alt_rel"] * sensor / (meta["focal_mm"] * meta["largura"])
                   if sensor and meta["alt_rel"] and meta["focal_mm"] else None)
    return meta



def _bloco(pts: np.ndarray, tipo: str) -> np.ndarray:
    """Linhas (2N, k) do sistema linear: [x', y'] intercalados = B · parâmetros."""
    x, y = pts[:, 0], pts[:, 1]
    z, u = np.zeros_like(x), np.ones_like(x)
    if tipo == "similaridade":
        B = np.empty((2 * len(pts), 4))
        B[0::2] = np.c_[x, -y, u, z]
        B[1::2] = np.c_[y, x, z, u]
    else:
        B = np.zeros((2 * len(pts), 6))
        B[0::2, 0:3] = np.c_[x, y, u]
        B[1::2, 3:6] = np.c_[x, y, u]
    return B


def _params(M: np.ndarray, tipo: str) -> np.ndarray:
    if tipo == "similaridade":
        return np.array([M[0, 0], M[1, 0], M[0, 2], M[1, 2]])
    return M[:2].ravel()


def _matriz(p: np.ndarray, tipo: str) -> np.ndarray:
    if tipo == "similaridade":
        a, b, tx, ty = p
        return np.array([[a, -b, tx], [b, a, ty], [0, 0, 1]])
    return np.vstack([p.reshape(2, 3), [0, 0, 1]])


def _angulo(M: np.ndarray) -> float:
    return float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))



def _centro(f: dict) -> list:
    return [[f["img"].shape[1] / 2, f["img"].shape[0] / 2]]


def carregar(pasta: str | Path, lado: int = 1600, epsg: int | None = None, log=print) -> dict:
    """Estado do mosaico em dict. Referencial "local": metros, X = leste, Y = sul (y para baixo, como imagem).
    Cada foto: meta, nome, img (escala de trabalho, BGR), escala (trabalho / original),
    prior (3x3 px de trabalho -> metros locais pelo GPS/rumo/GSD), kp, desc e T (3x3 ajustada)."""
    pasta = Path(pasta)
    arqs = sorted(p for p in pasta.iterdir() if p.suffix.lower() in EXTENSOES)
    if len(arqs) < 2:
        raise SystemExit(f"Preciso de pelo menos 2 fotos em {pasta}")
    metas = [ler_meta(a) for a in arqs]
    lon0 = np.mean([m["lon"] for m in metas])
    lat0 = np.mean([m["lat"] for m in metas])
    epsg = epsg or geo.epsg_utm_sirgas(lon0, lat0)
    E, N = geo.para_utm([m["lon"] for m in metas], [m["lat"] for m in metas], epsg)
    E0, N0 = float(np.floor(min(E))) - 100, float(np.ceil(max(N))) + 100
    fotos = []
    for a, m, e, n in zip(arqs, metas, E, N):
        img = cv2.imread(str(a), cv2.IMREAD_COLOR)
        k = lado / max(img.shape[:2])
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        # prior: topo da imagem aponta para o rumo do voo; escala = GSD
        s = (m["gsd"] or 0.03) / k
        h = np.radians(m["rumo"] or 0.0)
        R = np.array([[s * np.cos(h), -s * np.sin(h)], [s * np.sin(h), s * np.cos(h)]])
        c = np.array([img.shape[1] / 2, img.shape[0] / 2])
        t = np.array([e - E0, N0 - n]) - R @ c
        fotos.append({"meta": m, "nome": a.name, "img": img, "escala": k,
                      "prior": np.vstack([np.c_[R, t], [0, 0, 1]]), "kp": None, "desc": None, "T": None})
    log(f"{len(fotos)} fotos carregadas; referencial EPSG:{epsg}; "
        f"GSD pelo EXIF ≈ {np.median([m['gsd'] or np.nan for m in metas])*100:.2f} cm/px")
    return {"fotos": fotos, "pares": [], "relatorio": {"epsg": epsg}, "epsg": epsg, "E0": E0, "N0": N0, "log": log}


def casar(mos: dict, min_inliers: int = 15, tol_gps_m: float = 8.0):
    """SIFT + RANSAC em todos os pares que o GPS diz que se sobrepõem; o par só entra se for coerente com o GPS."""
    fotos = mos["fotos"]
    sift = cv2.SIFT_create(nfeatures=6000)
    clahe = cv2.createCLAHE(2.0, (8, 8))
    for f in fotos:
        cinza = clahe.apply(cv2.cvtColor(f["img"], cv2.COLOR_BGR2GRAY))
        kp, f["desc"] = sift.detectAndCompute(cinza, None)
        f["kp"] = np.float32([k.pt for k in kp])
    matcher = cv2.FlannBasedMatcher({"algorithm": 1, "trees": 5}, {"checks": 64})
    rejeitados = []
    for i, j in itertools.combinations(range(len(fotos)), 2):
        a, b = fotos[i], fotos[j]
        # pula pares que, pelo GPS, nem se sobrepõem
        ca, cb = geo.aplicar(a["prior"], _centro(a))[0], geo.aplicar(b["prior"], _centro(b))[0]
        # escala do prior = sqrt|det| (prior[0,0] = s·cos(rumo) zera/inverte com rumo ≈ 90°)
        diag = np.hypot(*a["img"].shape[:2]) * np.sqrt(abs(np.linalg.det(a["prior"][:2, :2])))
        if np.linalg.norm(ca - cb) > diag:
            continue
        m = matcher.knnMatch(a["desc"], b["desc"], k=2)
        bons = [p[0] for p in m if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(bons) < min_inliers:
            continue
        pa = a["kp"][[g.queryIdx for g in bons]]
        pb = b["kp"][[g.trainIdx for g in bons]]
        M, inl = cv2.estimateAffinePartial2D(pb, pa, method=cv2.RANSAC,
                                             ransacReprojThreshold=4.0, maxIters=5000)
        if M is None:
            continue
        inl = inl.ravel().astype(bool)
        n = int(inl.sum())
        if n < min_inliers:
            continue
        # coerência com o GPS: onde o par põe o centro de b, comparado ao GPS
        M3 = np.vstack([M, [0, 0, 1]])
        pred = geo.aplicar(a["prior"] @ M3, _centro(b))[0]
        desvio = float(np.linalg.norm(pred - cb))
        dang = abs((_angulo(a["prior"] @ M3) - _angulo(b["prior"]) + 180) % 360 - 180)
        if desvio > tol_gps_m or dang > 15:
            rejeitados.append(f"{i}-{j}({n}; {desvio:.0f} m, {dang:.0f}°)")
            continue
        mos["pares"].append({"i": i, "j": j, "n": n, "pa": pa[inl], "pb": pb[inl],
                             "desvio_gps_m": round(desvio, 2)})
    mos["log"](f"{len(mos['pares'])} pares aceitos: " +
               ", ".join(f"{p['i']}-{p['j']}({p['n']})" for p in mos["pares"]))
    if rejeitados:
        mos["log"]("Pares rejeitados por incoerência com o GPS: " + ", ".join(rejeitados))


def ajustar_global(mos: dict, tipo: str = "similaridade", sigma_gps_m: float = 1.5, max_pts_par: int = 300):
    """Duas etapas, para cada grupo de fotos ligadas por casamentos:
    (a) geometria relativa só pelos pontos casados, com uma foto âncora fixa
        (todas as transformações resolvidas juntas, sem erro em cadeia);
    (b) uma única similaridade leva o grupo inteiro às posições GPS.
    Ajustar GPS e casamentos no mesmo sistema não funciona bem: encolher a
    escala reduz todos os resíduos de costura e o ajuste "trapaceia".
    Fotos sem nenhum par ficam só com o prior (GPS + rumo + GSD).
    """
    fotos, pares = mos["fotos"], mos["pares"]
    k = 4 if tipo == "similaridade" else 6
    rng = np.random.default_rng(0)
    for grupo in _grupos(len(fotos), pares):
        g = sorted(grupo)
        idx = {f: c for c, f in enumerate(g)}
        ref = _foto_central(fotos, pares, g)
        if len(g) == 1:
            fotos[ref]["T"] = fotos[ref]["prior"].copy()
            continue
        linhas, rhs = [], []

        def bloco_foto(i, B, g=g, idx=idx):
            L = np.zeros((len(B), k * len(g)))
            L[:, idx[i] * k:(idx[i] + 1) * k] = B
            return L

        for p in pares:
            if p["i"] not in idx:
                continue
            sel = rng.permutation(len(p["pa"]))[:max_pts_par]
            # peso por par limitado: pares fortes não esmagam os fracos
            w = np.sqrt(min(p["n"], 60) / len(sel))
            L = bloco_foto(p["i"], _bloco(p["pa"][sel], tipo)) - bloco_foto(p["j"], _bloco(p["pb"][sel], tipo))
            linhas.append(L * w)
            rhs.append(np.zeros(len(L)))
        ancora = np.zeros((k, k * len(g)))
        ancora[:, idx[ref] * k:(idx[ref] + 1) * k] = np.eye(k) * 1e6
        linhas.append(ancora)
        rhs.append(_params(np.eye(3), tipo) * 1e6)
        sol = np.linalg.lstsq(np.vstack(linhas), np.concatenate(rhs), rcond=None)[0]
        rel = {i: _matriz(sol[idx[i] * k:(idx[i] + 1) * k], tipo) for i in g}   # px de ref
        # (b) grupo -> metros locais: similaridade ajustada aos centros GPS
        orig = np.array([geo.aplicar(rel[i], _centro(fotos[i]))[0] for i in g])
        dest = np.array([geo.aplicar(fotos[i]["prior"], _centro(fotos[i]))[0] for i in g])
        if np.ptp(dest, axis=0).max() > 3 * sigma_gps_m:
            S = geo.ajustar(orig, dest, "similaridade")
        else:   # fotos muito próximas: GPS não define rotação/escala, usa o prior da âncora
            S = fotos[ref]["prior"].copy()
            S[:2, 2] += (dest - geo.aplicar(S, orig)).mean(0)
        for i in g:
            fotos[i]["T"] = S @ rel[i]

    # diagnóstico
    res = []
    for p in pares:
        d = geo.aplicar(fotos[p["i"]]["T"], p["pa"]) - geo.aplicar(fotos[p["j"]]["T"], p["pb"])
        r = np.linalg.norm(d, axis=1)
        p["residuo_m"] = round(float(np.median(r)), 3)
        res.append(r)
    r = np.concatenate(res) if res else np.zeros(1)
    gps = {f["nome"]: round(float(np.linalg.norm(geo.aplicar(f["T"], _centro(f))[0] -
                                                 geo.aplicar(f["prior"], _centro(f))[0])), 2)
           for f in fotos}
    grupos = [sorted(fotos[i]["nome"] for i in gr) for gr in _grupos(len(fotos), pares)]
    isoladas = [gr[0] for gr in grupos if len(gr) == 1]
    escala = float(np.median([np.sqrt(abs(np.linalg.det(f["T"][:2, :2]))) * f["escala"] for f in fotos]))
    a = mos["relatorio"]["ajuste"] = {
        "tipo": tipo,
        "grupos": grupos,
        "residuo_costura_m": {"mediana": float(np.median(r)), "p95": float(np.percentile(r, 95))},
        "desvio_para_gps_m": gps,
        "rmse_gps_m": float(np.sqrt(np.mean(np.square(list(gps.values()))))),
        "gsd_ajustado_m": escala,
        "gsd_exif_m": float(np.median([f["meta"]["gsd"] for f in fotos if f["meta"]["gsd"]])),
        "fotos_so_por_gps": isoladas,
    }
    mos["log"](f"Ajuste global ({tipo}): costura mediana {a['residuo_costura_m']['mediana']*100:.1f} cm, "
               f"p95 {a['residuo_costura_m']['p95']*100:.1f} cm; RMSE vs GPS {a['rmse_gps_m']:.2f} m; "
               f"GSD ajustado {escala*100:.2f} cm/px (EXIF {a['gsd_exif_m']*100:.2f})")
    if len(grupos) > 1:
        mos["log"](f"ATENÇÃO: {len(grupos)} grupos sem ligação entre si; cada um foi posicionado "
                   "pelo GPS (erro de metros entre grupos): " + " | ".join(", ".join(gr) for gr in grupos))


def _grupos(n: int, pares: list) -> list[set[int]]:
    """Componentes conexas do grafo de pares aceitos."""
    viz = {i: set() for i in range(n)}
    for p in pares:
        viz[p["i"]].add(p["j"])
        viz[p["j"]].add(p["i"])
    vistos, grupos = set(), []
    for s in viz:
        if s in vistos:
            continue
        comp, pilha = set(), [s]
        while pilha:
            v = pilha.pop()
            if v not in comp:
                comp.add(v)
                pilha.extend(viz[v] - comp)
        vistos |= comp
        grupos.append(comp)
    return grupos


def _foto_central(fotos: list, pares: list, conj) -> int:
    """Foto com mais vizinhos casados (desempate: mais perto do centro GPS)."""
    conj = sorted(conj)
    grau = {i: sum(i in (p["i"], p["j"]) for p in pares) for i in conj}
    pos = {i: geo.aplicar(fotos[i]["prior"], _centro(fotos[i]))[0] for i in conj}
    c = np.mean(list(pos.values()), axis=0)
    return min(conj, key=lambda i: (-grau[i], np.linalg.norm(pos[i] - c)))


def renderizar(mos: dict, res: float, saida: str | Path, suavizar_m: float = 1.0) -> Path:
    """Gera a imagem norte-para-cima em `res` m/px e grava o georreferenciamento."""
    saida = Path(saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    fs, E0, N0, epsg = mos["fotos"], mos["E0"], mos["N0"], mos["epsg"]
    cantos = np.vstack([geo.aplicar(f["T"], [[0, 0], [f["img"].shape[1], 0],
                                             [f["img"].shape[1], f["img"].shape[0]], [0, f["img"].shape[0]]])
                        for f in fs])
    x0, y0 = cantos.min(0)
    x1, y1 = cantos.max(0)
    W, H = int(np.ceil((x1 - x0) / res)), int(np.ceil((y1 - y0) / res))
    P = np.array([[1 / res, 0, -x0 / res], [0, 1 / res, -y0 / res], [0, 0, 1]])
    # foto original (resolução total) -> pixel da saída
    Ms = [P @ f["T"] @ np.diag([f["escala"], f["escala"], 1.0]) for f in fs]
    mos["log"](f"Renderizando {W}x{H}px a {res*100:.1f} cm/px ({x1-x0:.0f} x {y1-y0:.0f} m)")

    def cobertura(k):
        f = fs[k]
        m = cv2.warpAffine(np.full((f["meta"]["altura"], f["meta"]["largura"]), 255, np.uint8),
                           Ms[k][:2], (W, H), flags=cv2.INTER_NEAREST)
        return cv2.erode(m, np.ones((5, 5), np.uint8)) > 0

    # rótulo = foto cujo centro está mais próximo (mais a prumo) em cada pixel
    melhor = np.full((H, W), np.inf, np.float32)
    rotulo = np.full((H, W), -1, np.int16)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    for k, f in enumerate(fs):
        c = geo.aplicar(Ms[k], [[f["meta"]["largura"] / 2, f["meta"]["altura"] / 2]])[0]
        d = (xx - c[0]) ** 2 + (yy - c[1]) ** 2
        m = cobertura(k) & (d < melhor)
        melhor[m] = d[m]
        rotulo[m] = k
    del melhor, xx, yy

    # mistura com pesos suavizados nas costuras
    sigma = max(suavizar_m / res, 1.0)
    acc = np.zeros((H, W, 3), np.float32)
    soma = np.zeros((H, W), np.float32)
    for k, f in enumerate(fs):
        w = cv2.GaussianBlur((rotulo == k).astype(np.float32), (0, 0), sigma) * cobertura(k)
        img = cv2.imread(f["meta"]["arquivo"], cv2.IMREAD_COLOR)
        # reduz antes do warp para não serrilhar quando a saída é bem mais grossa
        red = min(1.0, 1.5 * res / np.sqrt(abs(np.linalg.det(f["T"][:2, :2]))) * f["escala"])
        if red < 1:
            img = cv2.resize(img, None, fx=red, fy=red, interpolation=cv2.INTER_AREA)
        M = Ms[k] @ np.diag([1 / red, 1 / red, 1.0])
        warp = cv2.warpAffine(img, M[:2], (W, H), flags=cv2.INTER_LINEAR)
        acc += warp.astype(np.float32) * w[..., None]
        soma += w
        del img, warp
    vazio = soma < 1e-6
    out = (acc / np.maximum(soma, 1e-6)[..., None]).clip(0, 255).astype(np.uint8)
    if saida.suffix.lower() == ".png":
        cv2.imwrite(str(saida), np.dstack([out, np.where(vazio, 0, 255).astype(np.uint8)]))
    else:
        out[vazio] = 255
        cv2.imwrite(str(saida), out, [cv2.IMWRITE_JPEG_QUALITY, 90])

    e0, n1 = E0 + x0, N0 - y0          # canto superior esquerdo em UTM
    e1, n0 = E0 + x1, N0 - y1
    mos["relatorio"].update({
        "fotos": [{**f["meta"], "arquivo": f["nome"]} for f in fs],
        "pares": [{k: p[k] for k in ("i", "j", "n", "desvio_gps_m", "residuo_m")} for p in mos["pares"]],
        "saida": {"arquivo": saida.name, "largura": W, "altura": H, "res_m_px": res,
                  "extensao_utm": [e0, n0, e1, n1],
                  "cantos_lonlat_NO_NE_SE_SO": [geo.para_lonlat(e, n, epsg) for e, n in
                                                [(e0, n1), (e1, n1), (e1, n0), (e0, n0)]]},
        # pixel da foto original -> UTM (para reprojetar anotações feitas nas fotos)
        "foto_para_utm": {f["nome"]: (np.array([[1, 0, E0], [0, -1, N0], [0, 0, 1]])
                                      @ f["T"] @ np.diag([f["escala"], f["escala"], 1])).tolist() for f in fs},
    })
    geo.salvar_georef(saida, e0, n1, res, epsg, mos["relatorio"])
    mos["log"](f"Gravado {saida} (+ world file, .prj e .json)")
    return saida


def executar(pasta, saida, res: float = 0.04, epsg: int | None = None, lado: int = 1600,
             tipo: str = "similaridade", min_inliers: int = 15, sigma_gps_m: float = 1.5,
             tol_gps_m: float = 8.0, log=print) -> dict:
    """Carrega, casa, ajusta e renderiza; devolve o relatório (com `epsg`)."""
    t = time.time()
    mos = carregar(pasta, lado, epsg, log)
    casar(mos, min_inliers, tol_gps_m)
    ajustar_global(mos, tipo, sigma_gps_m)
    renderizar(mos, res, saida)
    log(f"Concluído em {time.time() - t:.0f}s")
    return mos["relatorio"]


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mosaico georreferenciado de fotos de drone")
    ap.add_argument("pasta", help="pasta com as fotos (JPG com GPS no EXIF)")
    ap.add_argument("saida", help="arquivo de saída .jpg ou .png (com transparência)")
    ap.add_argument("--res", type=float, default=0.04, help="resolução de saída em m/px (padrão 0.04)")
    ap.add_argument("--lado", type=int, default=1600, help="lado da imagem na escala de trabalho")
    ap.add_argument("--tipo", choices=["similaridade", "afim"], default="similaridade")
    ap.add_argument("--sigma-gps", type=float, default=1.5, help="incerteza do GPS do drone (m)")
    ap.add_argument("--epsg", type=int, help="EPSG de saída (padrão: SIRGAS 2000 / UTM da zona)")
    ap.add_argument("--min-inliers", type=int, default=15, help="pontos mínimos para aceitar um par")
    ap.add_argument("--tol-gps", type=float, default=8.0,
                    help="desvio máximo (m) entre o par casado e o GPS; aumente com GPS ruim/voo rápido")
    a = ap.parse_args(argv)
    executar(a.pasta, a.saida, a.res, a.epsg, a.lado, a.tipo, a.min_inliers, a.sigma_gps, a.tol_gps)


if __name__ == "__main__":
    main()
