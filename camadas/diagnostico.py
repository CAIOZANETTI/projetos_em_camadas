"""Ferramentas de conferência visual e de calibração — o que antes era script avulso na sessão vira função.

    recorte            = trecho da folha em PNG (pt da folha exibida)
    layers_em_volta    = traços de uma prancha em volta de um ponto (UTM), uma cor por layer, com legenda e a classe
                         de elemento — para descobrir qual layer é meio-fio, divisa, tubo…
    sobrepor           = várias famílias de linhas UTM (prancha × referência × resultado) numa imagem, opcionalmente
                         sobre a ortofoto — a conferência que não pode faltar antes de aceitar uma georreferência
    inventario_layers  = todos os layers das pranchas do obra.json com nº de traços, pranchas e classe de elemento
    afinar_ocr         = acerto do OCR por altura de letra × resolução em células de verdade conhecida

    python -m camadas.diagnostico layers exemplos/foz/obra.json aat00_03 744880 7182313 40 saida.png
    python -m camadas.diagnostico inventario-layers exemplos/foz/obra.json saida.csv
    python -m camadas.diagnostico recorte arquivo.pdf 100 200 400 500 saida.png
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from . import geo, pdf_cad

PALETA = [(220, 38, 38), (22, 163, 74), (37, 99, 235), (234, 88, 12), (147, 51, 234), (8, 145, 178), (161, 98, 7),
          (219, 39, 119), (79, 70, 229), (0, 0, 0), (120, 113, 108), (14, 116, 144)]          # RGB


def recorte(pdf: str | Path, caixa_pt, saida: str | Path, dpi: int = 200) -> Path:
    """Trecho da folha (coordenadas da folha exibida, em pt) gravado em PNG."""
    import pymupdf
    with pymupdf.open(pdf) as doc:
        doc[0].get_pixmap(dpi=dpi, clip=pymupdf.Rect(*caixa_pt)).save(str(saida))
    return Path(saida)


def _desenhar(img, linhas_utm, c, raio, res, cor, esp=1):
    for u in linhas_utm:
        u = np.asarray(u, float)
        if len(u) >= 2 and np.abs(u - c).max(1).min() <= raio:
            px = np.c_[(u[:, 0] - c[0] + raio) / res, (raio - (u[:, 1] - c[1])) / res].astype(np.int32)
            cv2.polylines(img, [px], False, cor[::-1], esp, cv2.LINE_AA)


def layers_em_volta(tracos: list, M, centro_utm, raio_m: float, saida: str | Path, res: float = 0.1,
                    destaque: str | None = None, max_legenda: int = 22) -> dict:
    """Traços de uma prancha num quadrado de lado 2·raio em volta do ponto, uma cor por layer; legenda com o nº
    de peças e a classe de elemento. Devolve {layer: peças} do recorte."""
    c, n = np.asarray(centro_utm, float), int(2 * raio_m / res)
    img = np.full((n, n, 3), 255, np.uint8)
    cores, cont = {}, Counter()
    for t in tracos:
        for q in t["partes"]:
            u = geo.aplicar(np.asarray(M), np.asarray(q, float))
            if len(u) < 2 or np.abs(u - c).max(1).min() > raio_m:
                continue
            cor = cores.setdefault(t["layer"], PALETA[len(cores) % len(PALETA)])
            cont[t["layer"]] += 1
            _desenhar(img, [u], c, raio_m, res, cor, 3 if destaque and re.search(destaque, t["layer"]) else 1)
    for k, (lay, m) in enumerate(cont.most_common(max_legenda)):
        cv2.putText(img, f"{lay} ({m}) {pdf_cad.elemento_do_layer(lay) or '?'}", (5, 18 + 16 * k),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, cores[lay][::-1], 1, cv2.LINE_AA)
    cv2.imwrite(str(saida), img)
    return dict(cont)


def linhas_utm_da_prancha(p: dict, filtro: str | None = None, sem_grafismo: bool = True) -> list[np.ndarray]:
    """Traços de uma prancha georreferenciada em UTM (opcional: só layers que casam com `filtro`; sem grafismo)."""
    graf = {c["id"] for c in pdf_cad.elementos()["classes"] if c["grupo"] == "Grafismo"} if sem_grafismo else set()
    out = []
    for t in pdf_cad.extrair(p["pdf"], clip=p.get("clip")):
        if (filtro and not re.search(filtro, t["layer"], re.IGNORECASE)) or pdf_cad.elemento_do_layer(t["layer"]) in graf:
            continue
        out += [geo.aplicar(np.asarray(p["M"]), np.asarray(q, float)) for q in t["partes"] if len(q) >= 2]
    return out


def sobrepor(familias: list[tuple], centro_utm, raio_m: float, saida: str | Path, res: float = 0.04,
             ortofoto: str | Path | None = None) -> Path:
    """Famílias [(linhas_utm, (r, g, b), espessura)] desenhadas numa imagem (ou sobre a ortofoto) em volta do ponto."""
    c, n = np.asarray(centro_utm, float), int(2 * raio_m / res)
    img = np.full((n, n, 3), 255, np.uint8)
    if ortofoto:
        meta = json.loads(Path(ortofoto).with_suffix(".json").read_text())
        o = cv2.imread(str(ortofoto))
        e0, n1, r = meta["canto_sup_esq"][0], meta["canto_sup_esq"][1], meta["res_m_px"]
        A = np.array([[res / r, 0, (c[0] - raio_m - e0) / r], [0, res / r, (n1 - (c[1] + raio_m)) / r]], np.float32)
        img = cv2.warpAffine(o, A, (n, n), flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP, borderValue=(255, 255, 255))
    for linhas, cor, *esp in familias:
        _desenhar(img, linhas, c, raio_m, res, cor, esp[0] if esp else 1)
    cv2.imwrite(str(saida), img)
    return Path(saida)


def inventario_layers(cfg: dict) -> list[dict]:
    """Todos os layers das pranchas do obra.json: traços, pranchas onde aparecem e classe de elemento."""
    cont, onde = Counter(), {}
    for p in cfg["pranchas"]:
        for t in pdf_cad.extrair(p["pdf"], clip=p.get("clip")):
            cont[t["layer"]] += len(t["partes"])
            onde.setdefault(t["layer"], set()).add(p["id"])
    classes = pdf_cad.elementos()["classes"]
    return [{"layer": lay, "tracos": n, "pranchas": " ".join(sorted(onde[lay])),
             "elemento": pdf_cad.elemento_do_layer(lay, classes) or ""} for lay, n in cont.most_common()]


def afinar_ocr(pagina, verdade: dict, alturas=(16, 18, 22, 25, 28), dpis=(400, 900),
               config: str = "--psm 7 -c tessedit_char_whitelist=0123456789,.") -> list[dict]:
    """Acerto do OCR por (altura da letra em px, dpi) em células de texto conhecido {texto: caixa_pt}."""
    import pymupdf

    from . import prancha
    out = []
    for alt in alturas:
        for dpi in dpis:
            lidos = [prancha._ocr(prancha._limpar(prancha._imagem(pagina, pymupdf.Rect(*cx), dpi), alt), config)
                     for cx in verdade.values()]
            out.append({"altura_px": alt, "dpi": dpi, "acertos": sum(a == b for a, b in zip(lidos, verdade)),
                        "total": len(verdade), "lidos": lidos})
    return out


def metadados() -> dict:
    """Rastreabilidade (regra 9 do estilo)."""
    return {"modulo": "diagnostico",
            "descricao": "conferência visual e calibração: recorte, layers em volta de um ponto, sobreposição, "
                         "inventário de layers e afinação do OCR",
            "funcoes": ["recorte", "layers_em_volta", "linhas_utm_da_prancha", "sobrepor", "inventario_layers",
                        "afinar_ocr", "main"],
            "bibliografia": [], "premissas": []}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Conferência visual e calibração das pranchas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("layers", help="layers coloridos em volta de um ponto UTM")
    a.add_argument("config"), a.add_argument("prancha"), a.add_argument("e", type=float), a.add_argument("n", type=float)
    a.add_argument("raio", type=float), a.add_argument("saida")
    b = sub.add_parser("inventario-layers", help="CSV com todos os layers e a classe de elemento")
    b.add_argument("config"), b.add_argument("saida")
    c = sub.add_parser("recorte", help="trecho da folha em PNG")
    c.add_argument("pdf"), [c.add_argument(k, type=float) for k in ("x0", "y0", "x1", "y1")], c.add_argument("saida")
    a_ = ap.parse_args(argv)
    if a_.cmd == "recorte":
        print(recorte(a_.pdf, (a_.x0, a_.y0, a_.x1, a_.y1), a_.saida))
        return
    cfg = json.loads(Path(a_.config).read_text(encoding="utf-8"))
    if a_.cmd == "inventario-layers":
        linhas = inventario_layers(cfg)
        with open(a_.saida, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(linhas[0]), delimiter=";")
            w.writeheader()
            w.writerows(linhas)
        print(f"{len(linhas)} layers, {sum(not x['elemento'] for x in linhas)} sem classe → {a_.saida}")
        return
    p = next(q for q in cfg["pranchas"] if q["id"] == a_.prancha)
    M = json.loads((Path(cfg["saida"]) / "pranchas" / f"{p['id']}.json").read_text())["M"]
    print(layers_em_volta(pdf_cad.extrair(p["pdf"], clip=p.get("clip")), np.vstack([np.asarray(M)[:2], [0, 0, 1]]),
                          (a_.e, a_.n), a_.raio, a_.saida))


if __name__ == "__main__":
    main()
