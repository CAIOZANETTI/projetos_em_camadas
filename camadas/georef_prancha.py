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
        "descricao": "prancha CAD em PDF -> UTM: pontos de controle + ICP, CAD × CAD por SIFT, busca global FFT",
        "funcoes": ["matriz_inicial", "registrar", "refinar", "registrar_cad", "registrar_imagem", "aceitavel"],
        "bibliografia": [
            {"obra": "Lowe — Distinctive Image Features from Scale-Invariant Keypoints (SIFT)", "ano": 2004,
             "editora": "IJCV", "aplicacao": {"registrar_imagem": ["SIFT_create(nfeatures=12000)", "razão 0,75"]}},
            {"obra": "Fischler & Bolles — Random Sample Consensus (RANSAC)", "ano": 1981, "editora": "CACM",
             "aplicacao": {"registrar_imagem": ["ransacReprojThreshold=6 px"]}},
            {"obra": "Besl & McKay — A Method for Registration of 3-D Shapes (ICP)", "ano": 1992,
             "editora": "IEEE TPAMI", "aplicacao": {"refinar": ["corte_m", "huber_m=0,5", "max_var_escala=0,10"]}},
            {"obra": "QGIS — Georreferenciador (transformações e arquivo .points)", "versao": "3.x",
             "editora": "QGIS.org", "aplicacao": {"matriz_inicial": ["similaridade com reflexão (y da folha ↓)"]}},
        ],
        "premissas": [
            {"aplicacao": {"registrar_cad": ["min_inliers=50", "max_residuo_m=0,15", "escala ±25 %", "rotação ±5°"]},
             "fonte": "calibrado em Foz: aceitas com 58–1491 correspondências e 3–10 cm; rejeitadas degeneradas (escala ≈ 0)"},
            {"aplicacao": {"aceitavel": ["max_residuo_m=0,6", "min_frac=0,45", "tol_rot_graus=5", "tol_escala=0,12"]},
             "fonte": "calibrado em Foz contra a ortofoto (prancha 004: 30 cm de resíduo mediano)"},
            {"aplicacao": {"mapa_bordas": ["min_compr_m=4", "sigma_m"]},
             "fonte": "bordas curtas = textura de grama/copa; média zero evita preferir escalas pequenas"},
        ],
        "ultima_revisao": "2026-10-27",
    }
