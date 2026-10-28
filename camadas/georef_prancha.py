"""Georreferenciamento automático de prancha CAD (PDF vetorial) sobre a ortofoto.

Prancha CAD e foto não têm textura em comum, mas têm *geometria* em comum: meios-fios,
contornos de edificações e tanques existentes. Este módulo casa as linhas da prancha
(ex.: layer de existentes) com as bordas da ortofoto:

  1. busca global: para cada rotação (em torno do norte da prancha) e escala (m/pt),
     a translação sai da correlação cruzada (FFT) entre o raster das linhas e um
     mapa de "proximidade de borda" da ortofoto; fica o melhor pico normalizado;
  2. refinamento tipo ICP robusto: cada ponto da prancha vai para a borda mais
     próxima (transformada de distância com rótulos) e uma similaridade é reajustada
     com pesos de Huber, várias iterações, em resolução crescente;
  3. relatório: resíduo mediano, fração de pontos a < 0,5 m de uma borda, escala.

Quando a prancha traz malha de coordenadas impressa, `registrar_malha` dispensa a foto: lê os
rótulos (OCR) e ajusta a afim às linhas da malha — é a georreferência do próprio CAD.

Uso típico:
    tr = pdf_cad.extrair(pdf, clip=...)
    pts = pontos_de_traco(tr, filtro=lambda t: "EXISTENTES" in t["layer"])
    r = registrar(pts, "saida/foz/sfm/ortofoto.jpg", rot_norte_graus=90, escalas=(0.05, 0.2))
    r["M"]  # 3x3 pt -> UTM

`rot_norte_graus` = para onde aponta o norte na prancha, medido do "para cima" da
folha no sentido horário (norte para a esquerda = 270; leste para cima = 270 também).
Sem a rosa dos ventos, use faixa_rot=180 (busca completa, mais lenta).
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import cv2
import numpy as np

from . import geo


def pontos_de_traco(tracos, filtro=None, passo_pt: float = 2.0) -> np.ndarray:
    """Amostra pontos a cada `passo_pt` ao longo dos traços (pt)."""
    out = []
    for t in tracos:
        if filtro is not None and not filtro(t):
            continue
        for p in t["partes"]:
            seg = np.diff(p, axis=0)
            comp = np.hypot(*seg.T)
            for a, d, c in zip(p[:-1], seg, comp):
                n = max(1, int(c / passo_pt))
                out.append(a + d * (np.arange(n)[:, None] / n))
    return np.vstack(out) if out else np.zeros((0, 2))


def _ortofoto(caminho: str | Path):
    caminho = Path(caminho)
    img = cv2.imread(str(caminho), cv2.IMREAD_COLOR)
    meta = json.loads(caminho.with_suffix(".json").read_text())
    e0, n1 = meta["canto_sup_esq"]
    return img, e0, n1, meta["res_m_px"], meta["epsg"]


def mapa_bordas(img: np.ndarray, res: float, res_alvo: float, sigma_m: float = 0.6, min_compr_m: float = 4.0):
    """Bordas (Canny) reduzidas a `res_alvo`, sem componentes curtos, e mapa de
    proximidade exp(-d²/2σ²) com média zero (fora da foto = penalidade)."""
    k = res / res_alvo
    g = cv2.cvtColor(cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
    g = cv2.GaussianBlur(g, (0, 0), 1.0)
    v = np.median(g)
    bordas = cv2.Canny(g, int(max(10, 0.66 * v * 0.5)), int(min(255, 1.33 * v * 0.6)))
    vazio = cv2.erode((img.min(axis=2) < 250).astype(np.uint8), np.ones((5, 5), np.uint8))
    vazio = cv2.resize(vazio, bordas.shape[::-1], interpolation=cv2.INTER_NEAREST) == 0
    bordas[vazio] = 0
    # só bordas "longas" (meio-fio, parede, tanque): componentes curtos são textura de grama/copa
    n, lab, st, _ = cv2.connectedComponentsWithStats(bordas, connectivity=8)
    compr = np.maximum(st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT]) * res_alvo
    bordas[(compr < min_compr_m)[lab]] = 0
    d = cv2.distanceTransform(255 - bordas, cv2.DIST_L2, 5) * res_alvo
    prox = np.exp(-d ** 2 / (2 * sigma_m ** 2)).astype(np.float32)
    # média zero na área válida: cair sobre textura densa não rende pontos, só casar linha com linha
    prox[~vazio] -= prox[~vazio].mean()
    prox[vazio] = 0
    return bordas, prox, (~vazio).astype(np.float32)


def _matriz(theta: float, s: float, t=(0.0, 0.0)) -> np.ndarray:
    """pt -> metros "imagem" (x leste, y sul): rotação horária theta + escala s."""
    c, si = np.cos(theta), np.sin(theta)
    return np.array([[s * c, -s * si, t[0]], [s * si, s * c, t[1]], [0, 0, 1]])


def busca_global(pts: np.ndarray, prox: np.ndarray, valido: np.ndarray, res: float, rot_centro: float,
                 faixa_rot: float, escalas: tuple, passo_rot: float = 1.0, n_escalas: int = 24,
                 min_dentro: float = 0.35, log=print) -> dict:
    """Melhor (rotação, escala, translação) por correlação FFT em `res` m/px.

    Score = proximidade média dos pontos que caem dentro da foto (a prancha costuma
    cobrir área maior que o voo), exigindo pelo menos `min_dentro` dos pontos dentro.
    """
    H, W = prox.shape
    F_prox = F_val = None
    melhor = {"score": -1}
    esc = np.geomspace(*escalas, n_escalas)
    rots = np.radians(np.arange(rot_centro - faixa_rot, rot_centro + faixa_rot + 1e-6, passo_rot))
    pc = pts - pts.mean(0)
    for s in esc:
        for th in rots:
            q = (_matriz(th, s / res)[:2, :2] @ pc.T).T
            q -= q.min(0)
            w, h = int(q[:, 0].max()) + 2, int(q[:, 1].max()) + 2
            if w >= 2 * W or h >= 2 * H:
                continue
            S = int(2 ** np.ceil(np.log2(max(W + w, H + h))))
            if F_prox is None or F_prox.shape[0] != S:
                pad = np.zeros((S, S), np.float32)
                pad[:H, :W] = prox
                F_prox = np.fft.rfft2(pad)
                pad = np.zeros((S, S), np.float32)
                pad[:H, :W] = valido
                F_val = np.fft.rfft2(pad)
            r = np.zeros((S, S), np.float32)
            qi = np.round(q).astype(int)
            np.add.at(r, (qi[:, 1], qi[:, 0]), 1.0)
            Fr = np.conj(np.fft.rfft2(r))
            corr = np.fft.irfft2(F_prox * Fr, s=(S, S))
            dentro = np.fft.irfft2(F_val * Fr, s=(S, S))
            corr = np.where(dentro > min_dentro * len(qi), corr / np.maximum(dentro, 1), -1)
            iy, ix = np.unravel_index(np.argmax(corr), corr.shape)
            score = float(corr[iy, ix])
            if score > melhor["score"]:
                dx = ix if ix < S - w else ix - S          # deslocamento circular -> translação
                dy = iy if iy < S - h else iy - S
                A = _matriz(th, s / res)
                q0 = (A[:2, :2] @ pc.T).T.min(0)
                # pt -> centrado -> rotação/escala -> canto em 0 -> deslocamento do pico
                T_px = (np.array([[1, 0, dx - q0[0]], [0, 1, dy - q0[1]], [0, 0, 1]]) @ A
                        @ np.array([[1, 0, -pts.mean(0)[0]], [0, 1, -pts.mean(0)[1]], [0, 0, 1]]))
                melhor = {"score": score, "theta": float(th), "s": float(s), "T_px": T_px}
    log(f"Busca global: rotação {np.degrees(melhor['theta']):.1f}°, escala {melhor['s']:.4f} m/pt, "
        f"score {melhor['score']:.3f}")
    return melhor


def refinar(pts: np.ndarray, bordas: np.ndarray, T_px: np.ndarray, res: float, iter: int = 30,
            corte_m: float = 3.0, huber_m: float = 0.5, max_var_escala: float = 0.10) -> tuple[np.ndarray, dict]:
    """ICP robusto (similaridade) dos pontos da prancha contra as bordas (px a `res`).
    A escala não pode variar mais que `max_var_escala` em relação à inicial."""
    d, lab = cv2.distanceTransformWithLabels(255 - bordas, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(bordas)
    coord = np.zeros((lab.max() + 1, 2), np.float32)
    coord[lab[ys, xs]] = np.c_[xs, ys]
    H, W = bordas.shape
    T = T_px.copy()
    esc0 = np.sqrt(abs(np.linalg.det(T[:2, :2])))
    for _ in range(iter):
        q = geo.aplicar(T, pts)
        dentro = (q[:, 0] >= 0) & (q[:, 0] < W - 1) & (q[:, 1] >= 0) & (q[:, 1] < H - 1)
        qi = np.round(q[dentro]).astype(int)
        alvo = coord[lab[qi[:, 1], qi[:, 0]]]
        dist = d[qi[:, 1], qi[:, 0]] * res
        ok = dist < corte_m
        if ok.sum() < 30:
            break
        w = np.where(dist[ok] < huber_m, 1.0, huber_m / np.maximum(dist[ok], 1e-6))
        Tn = geo.ajustar(pts[dentro][ok], alvo[ok], "similaridade", pesos=w)
        if abs(np.sqrt(abs(np.linalg.det(Tn[:2, :2]))) / esc0 - 1) > max_var_escala:
            break                                        # ICP "encolhendo" sobre textura: para
        mudou = np.abs(geo.aplicar(Tn, pts[::50]) - geo.aplicar(T, pts[::50])).max()
        T = Tn
        if mudou < 0.05:
            break
    q = geo.aplicar(T, pts)
    dentro = (q[:, 0] >= 0) & (q[:, 0] < W - 1) & (q[:, 1] >= 0) & (q[:, 1] < H - 1)
    qi = np.round(q[dentro]).astype(int)
    dist = d[qi[:, 1], qi[:, 0]] * res
    return T, {"residuo_mediano_m": float(np.median(dist)), "frac_05m": float((dist < 0.5).mean()),
               "frac_1m": float((dist < 1.0).mean()), "pontos": int(dentro.sum())}


def matriz_inicial(pontos_pt, pontos_utm, tipo: str = "similaridade") -> np.ndarray:
    """pt -> UTM a partir de pontos de controle (>= 2 para similaridade).

    PDF tem y para baixo e UTM tem N para cima: pt -> UTM contém uma reflexão, que a
    similaridade não representa. O ajuste é feito contra (E, -N) e a reflexão é reposta.
    """
    F = np.diag([1.0, -1.0, 1.0])
    u = np.asarray(pontos_utm, float) * [1, -1]
    return F @ geo.ajustar(np.asarray(pontos_pt, float), u, tipo)


def registrar(pts: np.ndarray, ortofoto: str | Path, rot_norte_graus: float | None = None,
              escalas=(0.03, 0.3), faixa_rot: float = 12.0, M_inicial: np.ndarray | None = None,
              M_irma: np.ndarray | None = None, cortes_m=(3.0, 1.5), log=print) -> dict:
    """Pontos da prancha (pt) -> matriz 3x3 pt -> UTM, com diagnóstico.

    Dois modos:
      - automático: `rot_norte_graus` (direção do norte na prancha, horário a partir do
        topo da folha) + faixa de `escalas` (m/pt) -> busca global FFT + ICP;
      - semiautomático (mais robusto): `M_inicial` de 2+ pontos de controle
        (`matriz_inicial`) -> só ICP. Use quando a prancha cobre área bem maior que o voo
        ou há muitas estruturas repetidas;
      - prancha irmã: `M_irma` = matriz de outra prancha do mesmo projeto já
        georreferenciada (mesma escala de plotagem e rotação, enquadramento diferente):
        rotação e escala vêm dela, a translação sai da busca FFT, depois ICP.
    """
    img, e0, n1, res0, epsg = _ortofoto(ortofoto)
    score = None
    if M_irma is not None and M_inicial is None:
        Ti = np.linalg.inv(np.array([[0.25, 0, e0], [0, -0.25, n1], [0, 0, 1]])) @ M_irma
        rot = float(np.degrees(np.arctan2(Ti[1, 0], Ti[0, 0])))
        esc = float(np.sqrt(abs(np.linalg.det(Ti[:2, :2])))) * 0.25
        _, prox, val = mapa_bordas(img, res0, 0.25, sigma_m=0.8)
        g = busca_global(pts[::2], prox, val, 0.25, rot, 1.5, (esc * 0.95, esc * 1.05),
                         passo_rot=0.5, n_escalas=7, log=log)
        T, score = g["T_px"], g["score"]
    elif M_inicial is None:
        # 1. grosso a 0,5 m/px; 2. fino a 0,25 m/px numa faixa estreita
        _, prox, val = mapa_bordas(img, res0, 0.5, sigma_m=1.5)
        g = busca_global(pts[::3], prox, val, 0.5, -rot_norte_graus, faixa_rot, escalas, passo_rot=1.0, log=log)
        _, prox, val = mapa_bordas(img, res0, 0.25, sigma_m=0.8)
        s0 = g["s"]
        g = busca_global(pts[::2], prox, val, 0.25, np.degrees(g["theta"]), 1.5, (s0 * 0.96, s0 * 1.04),
                         passo_rot=0.25, n_escalas=9, log=log)
        T, score = g["T_px"], g["score"]
    else:
        T = np.linalg.inv(np.array([[0.25, 0, e0], [0, -0.25, n1], [0, 0, 1]])) @ M_inicial
    # 3. ICP em 0,25 e depois 0,10 m/px
    r_ant = 0.25
    for r, corte in zip((0.25, 0.10), cortes_m):
        T = np.diag([r_ant / r, r_ant / r, 1.0]) @ T
        bordas, _, _ = mapa_bordas(img, res0, r)
        T, diag = refinar(pts, bordas, T, r, corte_m=corte)
        r_ant = r
    M = np.array([[r_ant, 0, e0], [0, -r_ant, n1], [0, 0, 1]]) @ T      # px -> UTM
    esc = float(np.sqrt(abs(np.linalg.det(M[:2, :2]))))
    rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    log(f"Refinado: resíduo mediano {diag['residuo_mediano_m'] * 100:.0f} cm, "
        f"{diag['frac_05m'] * 100:.0f}% dos pontos a < 0,5 m de uma borda; escala {esc * 1000:.2f} mm/pt")
    return {"M": M, "epsg": epsg, "escala_m_pt": esc, "rotacao_graus": rot, "score_global": score, **diag}


def _preparar(img: np.ndarray, lado: int) -> tuple[np.ndarray, float]:
    if img.ndim == 3:
        img = cv2.cvtColor(img[..., :3], cv2.COLOR_BGR2GRAY)
    k = min(1.0, lado / max(img.shape[:2]))
    if k < 1:
        img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return cv2.createCLAHE(2.0, (8, 8)).apply(img), k


def registrar_imagem(movel: np.ndarray, referencia: np.ndarray, tipo: str = "similaridade",
              lado: int = 2400, mascara_movel: np.ndarray | None = None) -> dict:
    """Registro imagem↔imagem por SIFT + RANSAC (ex.: prancha com foto -> mosaico, CAD × CAD).
    Encontra a transformação 3x3 que leva pixels de `movel` para pixels de `referencia`.

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


def registrar_cad(tracos, referencia: str | Path, M_base: np.ndarray, padrao_layers: str = "EXIST",
                  min_inliers: int = 50, max_residuo_m: float = 0.15, log=print) -> dict:
    """Prancha irmã contra o raster georreferenciado das linhas de outra prancha do mesmo
    modelo CAD (CAD × CAD): SIFT + RANSAC de similaridade nos cantos das linhas.

    Muito mais estável que o ICP quando a escala de plotagem muda entre folhas (0,077 a
    0,095 m/pt em Foz). Retorna {"M" (pt -> UTM) | None, "ok", "motivo", diagnóstico}.
    """
    import re
    from . import pdf_cad
    referencia = Path(referencia)
    meta = json.loads(referencia.with_suffix(".json").read_text())
    e0, n1 = meta["canto_sup_esq"]
    res = meta["res_m_px"]
    ref = cv2.imread(str(referencia), cv2.IMREAD_GRAYSCALE)
    esc_base = float(np.sqrt(abs(np.linalg.det(M_base[:2, :2]))))
    rot_base = float(np.degrees(np.arctan2(M_base[1, 0], M_base[0, 0])))
    k = esc_base / res                                    # px por pt na escala da base
    img, _ = pdf_cad.rasterizar(tracos, dpi=72 * k, espessura=2,
                                filtro=lambda t: re.search(padrao_layers, t["layer"], re.I) is not None)
    if img.max() == 0:
        return {"M": None, "ok": False, "motivo": f"sem traços nos layers '{padrao_layers}'"}
    try:
        r = registrar_imagem(cv2.cvtColor(255 - img, cv2.COLOR_GRAY2BGR), cv2.cvtColor(ref, cv2.COLOR_GRAY2BGR),
                          "similaridade", lado=3000)
    except RuntimeError as e:
        return {"M": None, "ok": False, "motivo": str(e)}
    M = np.array([[res, 0, e0], [0, -res, n1], [0, 0, 1]]) @ r["M"] @ np.diag([k, k, 1.0])
    esc = float(np.sqrt(abs(np.linalg.det(M[:2, :2]))))
    rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    drot = abs((rot - rot_base + 180) % 360 - 180)
    d = {"inliers": r["inliers"], "residuo_mediano_m": r["residuo_px"] * res, "escala_m_pt": esc,
         "rotacao_graus": rot, "frac_05m": None}
    falhas = []
    if r["inliers"] < min_inliers:
        falhas.append(f"{r['inliers']} correspondências")
    if d["residuo_mediano_m"] > max_residuo_m:
        falhas.append(f"resíduo {d['residuo_mediano_m']:.2f} m")
    if not 0.75 < esc / esc_base < 1.25 or drot > 5:
        falhas.append(f"escala {esc:.4f} m/pt / rotação {rot:.1f}° incoerentes com a base")
    ok = not falhas
    log(f"  CAD×CAD: {r['inliers']} correspondências, resíduo {d['residuo_mediano_m'] * 100:.0f} cm, "
        f"escala {esc:.4f} m/pt, rotação {rot:.1f}° -> {'OK' if ok else 'rejeitado'}")
    return {"M": M if ok else None, "ok": ok, "motivo": "CAD×CAD (SIFT)" if ok else "; ".join(falhas), **d}


def linhas_da_malha(tracos, padrao_layer: str, min_compr_pt: float = 100.0, max_glifo_pt: float = 15.0) -> dict:
    """Linhas retas longas do layer de grade (segmentos colineares fundidos) e glifos curtos agrupados em rótulos.

    Os rótulos da malha costumam vir em fonte SHX, isto é, desenhados como traço e não como texto do PDF.
    Retorna {"linhas": [{"p0", "p1", "angulo"}], "rotulos": [{"centro", "angulo", "partes"}]} em pt e graus.
    """
    import re
    partes = [np.asarray(q, float) for t in tracos if re.search(padrao_layer, t["layer"], re.IGNORECASE)
              for q in t["partes"] if len(q) >= 2]
    segmentos, glifos = [], []
    for q in partes:
        if np.ptp(q, axis=0).max() <= max_glifo_pt:
            glifos.append(q)
            continue
        for a, b in itertools.pairwise(q):
            if np.hypot(*(b - a)) >= min_compr_pt:
                segmentos.append((a, b))
    # colineares: mesmo ângulo (±0,5°) e mesma distância à origem (±1 pt) viram uma linha só
    linhas = []
    for a, b in segmentos:
        ang = float(np.degrees(np.arctan2(*(b - a)[::-1])) % 180)
        n = np.array([-np.sin(np.radians(ang)), np.cos(np.radians(ang))])
        rho = float(n @ a)
        for l in linhas:
            if abs((l["angulo"] - ang + 90) % 180 - 90) < 0.5 and abs(l["rho"] - rho) < 1.0:
                l["pontos"] += [a, b]
                break
        else:
            linhas.append({"angulo": ang, "rho": rho, "pontos": [a, b]})
    for l in linhas:
        d = np.array([np.cos(np.radians(l["angulo"])), np.sin(np.radians(l["angulo"]))])
        p = np.array(l.pop("pontos"))
        s = p @ d
        l["p0"], l["p1"] = p[s.argmin()], p[s.argmax()]
    return {"linhas": linhas, "rotulos": _agrupar_glifos(glifos)}


def _agrupar_glifos(glifos: list) -> list[dict]:
    """Glifos vizinhos formam um rótulo: vão ≤ 0,8 × o maior lado do maior dos dois (o "1" é estreito e abre o
    vão). A direção do texto é a componente principal dos pontos. Rótulo com menos de 3 glifos não é número."""
    caixas = [np.r_[g.min(0), g.max(0)] for g in glifos]
    lado = [max(c[2] - c[0], c[3] - c[1]) for c in caixas]
    grupo = list(range(len(glifos)))

    def raiz(i):
        while grupo[i] != i:
            grupo[i] = grupo[grupo[i]]
            i = grupo[i]
        return i

    for i, j in itertools.combinations(range(len(caixas)), 2):
        ci, cj, vao = caixas[i], caixas[j], 0.8 * max(lado[i], lado[j])
        if ci[0] - vao <= cj[2] and cj[0] - vao <= ci[2] and ci[1] - vao <= cj[3] and cj[1] - vao <= ci[3]:
            grupo[raiz(i)] = raiz(j)
    rotulos = {}
    for i, g in enumerate(glifos):
        rotulos.setdefault(raiz(i), []).append(g)
    saida = []
    for gs in rotulos.values():
        if len(gs) < 3:
            continue
        p = np.vstack(gs)
        autoval, autovet = np.linalg.eigh(np.cov((p - p.mean(0)).T))
        eixo = autovet[:, autoval.argmax()]                       # direção da linha de texto
        saida.append({"centro": p.mean(0), "angulo": float(np.degrees(np.arctan2(eixo[1], eixo[0])) % 180),
                      "partes": gs})
    return saida


def ler_rotulo(rotulo: dict, angulo: float, dpi: float = 600) -> str | None:
    """OCR (tesseract) de um rótulo numérico desenhado em traço, girado para a horizontal pelo `angulo` da linha
    que ele acompanha; tenta os dois sentidos de leitura."""
    import pytesseract
    k = dpi / 72
    for giro in (angulo, angulo + 180):
        c, s_ = np.cos(np.radians(-giro)), np.sin(np.radians(-giro))
        partes = [(q - rotulo["centro"]) @ np.array([[c, s_], [-s_, c]]) for q in rotulo["partes"]]
        p = np.vstack(partes)
        x0, y0 = p.min(0)
        x1, y1 = p.max(0)
        img = np.full((int((y1 - y0) * k) + 41, int((x1 - x0) * k) + 41), 255, np.uint8)
        for q in partes:
            cv2.polylines(img, [np.int32((q - [x0, y0]) * k + 20)], False, 0, max(2, int(k / 2.5)), cv2.LINE_AA)
        txt = pytesseract.image_to_string(img, config="--psm 7 -c tessedit_char_whitelist=0123456789").strip()
        if 6 <= len(txt) <= 7 and txt.isdigit() and txt[0] != "0":     # UTM não começa com 0 (leitura de ponta-cabeça)
            return txt
    return None


def _ajustar_malha(obs: list, max_residuo_m: float, min_valores: int) -> dict:
    """Similaridade com reflexão sobre observações {"p" (pt), "eixo" "E"|"N", "valor", "chave"}:
    E = a·x − b·y + c ; N = −b·x − a·y − d. Descarta a chave (linha ou rótulo) de maior resíduo enquanto passar de
    `max_residuo_m`. Devolve {"M", "obs", "descartadas"} ou {"M": None, "motivo"}."""
    obs, descartadas = list(obs), []
    while True:
        eixos = {e: sorted({o["valor"] for o in obs if o["eixo"] == e}) for e in ("E", "N")}
        if not eixos["E"] or not eixos["N"] or len(eixos["E"]) + len(eixos["N"]) < min_valores:
            return {"M": None, "motivo": f"malha insuficiente (E {eixos['E']}, N {eixos['N']}; "
                    f"descartadas {descartadas or '—'})"}
        A = [[o["p"][0], -o["p"][1], 1, 0] if o["eixo"] == "E" else [-o["p"][1], -o["p"][0], 0, -1] for o in obs]
        a, b, c, d = np.linalg.lstsq(np.array(A), np.array([o["valor"] for o in obs]), rcond=None)[0]
        M = np.array([[a, -b, c], [-b, -a, -d], [0, 0, 1]])
        for o in obs:
            o["residuo_m"] = abs(float(geo.aplicar(M, [o["p"]])[0, 0 if o["eixo"] == "E" else 1]) - o["valor"])
        pior = max(obs, key=lambda o: o["residuo_m"])
        if pior["residuo_m"] <= max_residuo_m:
            return {"M": M, "obs": obs, "eixos": eixos, "descartadas": descartadas}
        descartadas.append(f"{pior['eixo']} {pior['valor']:.0f}")          # leitura errada do OCR (ou do desenho)
        obs = [o for o in obs if o["chave"] != pior["chave"]]


def _eixo_por_familia(itens: list) -> list:
    """[(angulo, textos, extra)] -> [(eixo, valor, extra)]: o eixo é o da família de paralelas (maioria: 7 dígitos =
    N, 6 = E); leitura com dígito a mais ou a menos sai, e cada item fica com o valor mais votado."""
    from collections import Counter
    familias, saida = {}, []
    for ang, textos, extra in itens:
        familias.setdefault(round(ang) % 180, []).append((textos, extra))
    for fam in familias.values():
        tam = Counter(len(t) for textos, _ in fam for t in textos).most_common(1)[0][0]
        for textos, extra in fam:
            votos = Counter(t for t in textos if len(t) == tam)
            if votos:
                saida.append(("N" if tam == 7 else "E", float(votos.most_common(1)[0][0]), extra))
    return saida


def _obs_da_malha(malha: dict, ler, modo: str) -> list:
    """Observações para `_ajustar_malha`. "linhas": cada linha com os rótulos alinhados (≤ 12 pt da reta, ±10°),
    pelas duas pontas. "rótulos": cada rótulo lido, pelo centro."""
    if modo == "rótulos":
        itens = [(rt["angulo"], [ler(i, rt["angulo"])], (i, rt)) for i, rt in enumerate(malha["rotulos"])]
        return [{"p": rt["centro"], "eixo": e, "valor": v, "chave": i}
                for e, v, (i, rt) in _eixo_por_familia([x for x in itens if x[1][0]])]
    itens = []
    for l in malha["linhas"]:
        d = np.array([np.cos(np.radians(l["angulo"])), np.sin(np.radians(l["angulo"]))])
        n = np.array([-d[1], d[0]])
        comp = (l["p1"] - l["p0"]) @ d
        textos = [ler(i, l["angulo"]) for i, r in enumerate(malha["rotulos"])
                  if abs((r["angulo"] - l["angulo"] + 90) % 180 - 90) < 10 and abs((r["centro"] - l["p0"]) @ n) < 12
                  and -60 < (r["centro"] - l["p0"]) @ d < comp + 60]
        if any(textos):
            itens.append((l["angulo"], [t for t in textos if t], l))
    return [{"p": p, "eixo": e, "valor": v, "chave": id(l)} for e, v, l in _eixo_por_familia(itens)
            for p in (l["p0"], l["p1"])]


def registrar_malha(tracos, padrao_layer: str, escala: float | None = None, max_residuo_m: float = 0.5,
                    log=print) -> dict:
    """Prancha com malha de coordenadas impressa -> pt -> UTM, sem ortofoto nem prancha irmã.

    Linhas da malha: cada uma recebe os rótulos alinhados com ela (≤ 12 pt da reta), por voto, e entra pelas duas
    pontas. Malha só na moldura (sem linhas): cada rótulo entra pelo centro, com incerteza de meia altura do texto.
    O eixo vem da família de paralelas: 7 dígitos = N, 6 dígitos = E (UTM no Brasil). Sem `escala` (denominador
    declarado, ex. 1000) exige 4 valores distintos, porque 3 fecham o ajuste sem sobra; com ela bastam 3 e a escala
    medida tem de bater em ±0,5 %.
    Retorna {"M" | None, "ok", "motivo", "linhas", "residuo_max_m", "escala_m_pt", "rotacao_graus", "janela_pt"}.
    """
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return {"M": None, "ok": False, "motivo": "OCR indisponível (pip install pytesseract + tesseract-ocr)"}
    malha = linhas_da_malha(tracos, padrao_layer)
    lidos = {}

    def ler(i, angulo):
        chave = (i, round(angulo))
        if chave not in lidos:
            lidos[chave] = ler_rotulo(malha["rotulos"][i], angulo)
        return lidos[chave]

    for modo in ("linhas", "rótulos"):                   # malha só na moldura: o rótulo marca a coordenada
        r = _ajustar_malha(_obs_da_malha(malha, ler, modo), max_residuo_m, 3 if escala else 4)
        if r["M"] is not None:
            break
    incerteza = 0.0
    if r["M"] is not None and modo == "rótulos":
        alturas = [np.ptp(np.vstack(malha["rotulos"][o["chave"]]["partes"]) @ np.array(
            [-np.sin(np.radians(malha["rotulos"][o["chave"]]["angulo"])),
             np.cos(np.radians(malha["rotulos"][o["chave"]]["angulo"]))])) for o in r["obs"]]
        incerteza = 0.5 * float(np.median(alturas)) * float(np.hypot(*r["M"][0, :2]))
    if r["M"] is None:
        return {"M": None, "ok": False, "motivo": f"{r['motivo']}; {len(malha['rotulos'])} rótulos, "
                f"{len(malha['linhas'])} linhas"}
    M = r["M"]
    esc = float(np.hypot(*M[0, :2]))
    rot = float(np.degrees(np.arctan2(M[1, 0], M[0, 0])))
    res_max = max(o["residuo_m"] for o in r["obs"])
    esc_decl = escala * 0.0254 / 72 if escala else None              # 1 pt = 1/72 pol
    ok = esc_decl is None or abs(esc / esc_decl - 1) <= 0.005
    motivo = (f"malha de coordenadas impressa ({modo}, OCR)" if ok else
              f"escala medida 1:{esc / 0.0254 * 72:.0f} ≠ declarada 1:{escala:.0f}")
    log(f"  malha ({modo}): E {r['eixos']['E']}, N {r['eixos']['N']}, resíduo máx {res_max:.3f} m, "
        f"escala {esc:.4f} m/pt (1:{esc / 0.0254 * 72:.0f}); descartadas {r['descartadas'] or '—'} -> "
        f"{'OK' if ok else 'rejeitada'}")
    pts = np.array([o["p"] for o in r["obs"]])
    linhas = {}
    for o in r["obs"]:
        linhas.setdefault(o["chave"], {"eixo": o["eixo"], "valor": o["valor"], "residuo_m": 0.0})
        linhas[o["chave"]]["residuo_m"] = round(max(linhas[o["chave"]]["residuo_m"], o["residuo_m"]), 4)
    return {"M": M if ok else None, "ok": ok, "motivo": motivo, "modo": modo, "linhas": list(linhas.values()),
            "descartadas": r["descartadas"], "residuo_max_m": res_max, "incerteza_rotulo_m": round(incerteza, 2),
            "residuo_mediano_m": float(np.median([o["residuo_m"] for o in r["obs"]])), "frac_05m": None,
            "escala_m_pt": esc, "rotacao_graus": rot, "janela_pt": [*pts.min(0).tolist(), *pts.max(0).tolist()]}


def aceitavel(r: dict, M_ref: np.ndarray | None = None, max_residuo_m: float = 0.6, min_frac: float = 0.45,
              tol_rot_graus: float = 5.0, tol_escala: float = 0.12) -> tuple[bool, str]:
    """Critérios para aceitar um registro automático; senão a prancha pede pontos de controle."""
    if r["residuo_mediano_m"] > max_residuo_m or r["frac_05m"] < min_frac:
        return False, f"resíduo {r['residuo_mediano_m']:.2f} m / {r['frac_05m'] * 100:.0f}% a < 0,5 m"
    if M_ref is not None:
        rot_ref = np.degrees(np.arctan2(M_ref[1, 0], M_ref[0, 0]))
        esc_ref = np.sqrt(abs(np.linalg.det(M_ref[:2, :2])))
        drot = abs((r["rotacao_graus"] - rot_ref + 180) % 360 - 180)
        if drot > tol_rot_graus or abs(r["escala_m_pt"] / esc_ref - 1) > tol_escala:
            return False, f"rotação/escala fora da prancha irmã (Δrot {drot:.1f}°, escala {r['escala_m_pt']:.4f})"
    return True, "ok"


def salvar(r: dict, caminho: str | Path, extra: dict | None = None) -> None:
    d = {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in r.items()}
    d.update(extra or {})
    Path(caminho).write_text(json.dumps(d, indent=2, ensure_ascii=False))


def metadados() -> dict:
    """Rastreabilidade dos métodos e limiares de georreferência de prancha (regra 9 do estilo)."""
    return {
        "modulo": "georef_prancha",
        "descricao": "prancha CAD em PDF -> UTM: malha de coordenadas impressa (OCR), pontos de controle + ICP, "
                     "CAD × CAD por SIFT, busca global FFT",
        "funcoes": ["matriz_inicial", "registrar", "refinar", "registrar_cad", "registrar_imagem", "aceitavel",
                    "linhas_da_malha", "ler_rotulo", "registrar_malha"],
        "bibliografia": [
            {"obra": "Lowe — Distinctive Image Features from Scale-Invariant Keypoints (SIFT)", "ano": 2004,
             "editora": "IJCV", "aplicacao": {"registrar_imagem": ["SIFT_create(nfeatures=12000)", "razão 0,75"]}},
            {"obra": "Fischler & Bolles — Random Sample Consensus (RANSAC)", "ano": 1981, "editora": "CACM",
             "aplicacao": {"registrar_imagem": ["ransacReprojThreshold=6 px"]}},
            {"obra": "Besl & McKay — A Method for Registration of 3-D Shapes (ICP)", "ano": 1992,
             "editora": "IEEE TPAMI", "aplicacao": {"refinar": ["corte_m", "huber_m=0,5", "max_var_escala=0,10"]}},
            {"obra": "Smith — An Overview of the Tesseract OCR Engine", "ano": 2007, "editora": "ICDAR",
             "aplicacao": {"ler_rotulo": ["--psm 7 (uma linha)", "só dígitos", "600 dpi"]}},
            {"obra": "QGIS — Georreferenciador (transformações e arquivo .points)", "versao": "3.x",
             "editora": "QGIS.org", "aplicacao": {"matriz_inicial": ["similaridade com reflexão (y da folha ↓)"]}},
        ],
        "premissas": [
            {"aplicacao": {"registrar_cad": ["min_inliers=50", "max_residuo_m=0,15", "escala ±25 %", "rotação ±5°"]},
             "fonte": "calibrado em Foz: aceitas com 58–1491 correspondências e 3–10 cm; rejeitadas degeneradas (escala ≈ 0)"},
            {"aplicacao": {"aceitavel": ["max_residuo_m=0,6", "min_frac=0,45", "tol_rot_graus=5", "tol_escala=0,12"]},
             "fonte": "calibrado em Foz contra a ortofoto (prancha 004: 30 cm de resíduo mediano)"},
            {"aplicacao": {"registrar_malha": ["max_residuo_m=0,5", "rótulo a ≤ 12 pt da linha", "7 dígitos = N",
                                               "≥ 4 valores (3 com escala declarada, ±0,5 %)"],
                           "linhas_da_malha": ["min_compr_pt=100", "max_glifo_pt=15", "vão ≤ 0,8 × lado do glifo"]},
             "fonte": "calibrado em Foz: 15 folhas com resíduo de 0 a 29 cm; marcos E/N da AAT00-01 a 0,20 e 0,23 m; "
                      "escala igual à da GEOPLANTA (sondagens) em 0,1 %"},
            {"aplicacao": {"registrar": ["escala inicial medida na foto"]},
             "fonte": "lição de Foz (rodada 5): f004 iniciada com 0,095 m/pt ficou 7,9 % grande e o ICP não corrigiu "
                      "(trava de ±10 %; bordas da foto não discriminam: ~47 % dos traços a < 0,5 m de uma borda em "
                      "qualquer das duas escalas). Prefira malha, coordenadas topográficas ou CAD × CAD sobre prancha "
                      "absoluta"},
            {"aplicacao": {"mapa_bordas": ["min_compr_m=4", "sigma_m"]},
             "fonte": "bordas curtas = textura de grama/copa; média zero evita preferir escalas pequenas"},
        ],
        "ultima_revisao": "2026-10-28",
    }
