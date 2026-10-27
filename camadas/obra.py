"""Construtor de obra: um `obra.json` -> pasta de saída com ortofoto, 3D, camadas e HTML.

Junta todos os módulos num pipeline reproduzível e com cache (cada etapa grava seu
resultado e só refaz se a saída não existir ou com --refazer):

    fotos ─► sfm (poses, nuvem, ortofoto verdadeira, classificação nadir/oblíqua)
    pranchas PDF ─► georref (pontos de controle | prancha irmã + ICP) ─► camadas por classe
    orçamento CSV ─► escopo por etapa       sondagens JSON ─► furos com NSPT
                         └──────────► dados do visualizador ─► HTML único

Uso:
    python -m camadas.obra exemplos/foz/obra.json [--refazer sfm,pranchas]

Formato do obra.json: ver `exemplos/foz/obra.json` (comentado em docs/OBRA_JSON.md).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from . import geo, georef_prancha, pdf_cad, sfm, visualizador

REGRAS = {"etapa_sanepar": pdf_cad.REGRAS_ETAPA_SANEPAR}

# Classes genéricas para pranchas sem convenção de etapa: agrupam layers por função.
REGRAS_GENERICAS = [
    pdf_cad.Regra("Projetado", layer=r"PROJET|NOVO|_PROJ", rotulo="Projetado"),
    pdf_cad.Regra("Existente", layer=r"EXIST", rotulo="Existente"),
    pdf_cad.Regra("Tubulação", layer=r"TUBUL|TUB_|REDE|ADUTORA|DRENAG", rotulo="Tubulações e redes"),
    pdf_cad.Regra("Estrutura", layer=r"CONCRETO|ESTRUT|FORMA|PILAR|VIGA|ESTACA|BLOCO|SAPATA|FUND", rotulo="Estrutura / fundação"),
    pdf_cad.Regra("Equipamentos", layer=r"EQUIP|BOMBA|VALV|COMPORT", rotulo="Equipamentos"),
    pdf_cad.Regra("Elétrica", layer=r"ELET|CABO|ELETROD|ILUMIN|ATERR|SPDA|FORCA|COMANDO", rotulo="Elétrica"),
    pdf_cad.Regra("Terraplenagem", layer=r"TERRAP|TALUDE|CURVA|PLATAF|CORTE|ATERRO", rotulo="Terraplenagem"),
    pdf_cad.Regra("Linhas gerais", layer=r"LINHA|ALVENARIA|PROJE", rotulo="Linhas gerais"),
]
def _log(*a):
    print(*a, flush=True)


# 1 ---------------------------------------------------------------------------
def etapa_sfm(cfg: dict, out: Path, refazer: bool) -> dict:
    pasta = out / "sfm"
    if refazer or not (pasta / "sfm.json").exists() or not (pasta / "ortofoto.jpg").exists():
        sfm.executar(cfg["fotos"], pasta, denso=cfg.get("sfm", {}).get("denso", True),
                     orto_res=cfg.get("sfm", {}).get("orto_res", 0.04), log=_log)
    return json.loads((pasta / "sfm.json").read_text())


def etapa_controle_absoluto(cfg: dict, out: Path, refazer: bool) -> np.ndarray:
    """Leva ortofoto/3D do GPS do drone para o referencial topográfico do projeto.

    `controle_absoluto` = prancha cuja afim pt -> UTM vem de pontos com coordenadas
    absolutas (ex.: furos de sondagem locados por topografia). O ICP dessa prancha contra a
    ortofoto mede o viés do GPS do drone; a ortofoto é deslocada (world file e .json) e o
    deslocamento fica em sfm/ajuste_absoluto.json para aplicar à nuvem 3D e às câmeras.
    """
    c = cfg.get("controle_absoluto")
    arq = out / "sfm" / "ajuste_absoluto.json"
    if not c:
        return np.zeros(2)
    if arq.exists() and not refazer:
        return np.array(json.loads(arq.read_text())["deslocamento_m"])
    M = np.vstack([np.asarray(c["afim_pt_utm"], float), [0, 0, 1]])
    tr = pdf_cad.extrair(c["pdf"])
    pts = georef_prancha.pontos_de_traco(tr, passo_pt=4)
    orto = out / "sfm" / "ortofoto.jpg"
    r = georef_prancha.registrar(pts, orto, M_inicial=M, log=_log)
    d = geo.aplicar(r["M"], pts[::100]) - geo.aplicar(M, pts[::100])
    desloc = d.mean(0)                                # ortofoto (GPS) - absoluto
    meta = json.loads(orto.with_suffix(".json").read_text())
    e0, n1 = meta["canto_sup_esq"]
    e0, n1 = e0 - desloc[0], n1 - desloc[1]
    ext = meta["extensao_utm"]
    meta["extensao_utm"] = [ext[0] - desloc[0], ext[1] - desloc[1], ext[2] - desloc[0], ext[3] - desloc[1]]
    meta["ajuste_absoluto_m"] = desloc.round(3).tolist()
    geo.salvar_georef(orto, e0, n1, meta["res_m_px"], meta["epsg"],
                      {k: v for k, v in meta.items() if k not in ("epsg", "canto_sup_esq", "res_m_px")})
    arq.write_text(json.dumps({"deslocamento_m": desloc.round(3).tolist(), "desvio_m": d.std(0).round(3).tolist(),
                               "residuo_mediano_m": r["residuo_mediano_m"], "fonte": c.get("fonte", ""),
                               "prancha": Path(c["pdf"]).name}, indent=2, ensure_ascii=False))
    _log(f"Controle absoluto: ortofoto deslocada {-desloc[0]:+.2f} m E, {-desloc[1]:+.2f} m N "
         f"(viés do GPS do drone; desvio {d.std(0).max():.2f} m)")
    return desloc


# 2 ---------------------------------------------------------------------------
def etapa_pranchas(cfg: dict, out: Path, refazer: bool) -> list[dict]:
    """Georreferencia cada prancha (cache em pranchas/<id>.json)."""
    orto = out / "sfm" / "ortofoto.jpg"
    pasta = out / "pranchas"
    pasta.mkdir(parents=True, exist_ok=True)
    feitas: dict[str, dict] = {}
    for p in cfg.get("pranchas", []):
        cache = pasta / f"{p['id']}.json"
        if cache.exists() and not refazer:
            r = json.loads(cache.read_text())
            r["M"] = np.array(r["M"]) if r.get("M") else None
            feitas[p["id"]] = {**p, **r}
            continue
        t = time.time()
        tr = pdf_cad.extrair(p["pdf"], clip=p.get("clip"))
        filtro_ref = p.get("layers_referencia", "EXISTENTE")
        pts = georef_prancha.pontos_de_traco(tr, filtro=lambda t, f=filtro_ref: f.upper() in t.layer.upper(),
                                             passo_pt=3)
        r, ok, motivo = None, False, ""
        pc = p.get("pontos_controle")
        irma = feitas.get(p.get("irma", ""), {}).get("M")
        if p.get("M_absoluta"):
            # afim já conhecida (ex.: ajustada em coordenadas topográficas): usa sem ICP
            r = {"M": np.vstack([np.asarray(p["M_absoluta"], float), [0, 0, 1]]), "residuo_mediano_m": None,
                 "frac_05m": None}
            ok, motivo = True, "afim absoluta (coordenadas topográficas)"
        elif pc:
            M0 = georef_prancha.matriz_inicial(pc["pt"], pc["utm"])
            r = georef_prancha.registrar(pts, orto, M_inicial=M0, log=_log) if len(pts) > 200 else \
                {"M": M0, "residuo_mediano_m": None, "frac_05m": None, "escala_m_pt": None}
            ok, motivo = True, "pontos de controle" + (" + ICP" if len(pts) > 200 else "")
        elif irma is not None and len(pts) > 200:
            # referência = linhas de existentes da prancha irmã já georreferenciada (CAD × CAD)
            ref = referencia_cad(feitas[p["irma"]], pasta, filtro_ref)
            r = georef_prancha.registrar(pts, ref, M_irma=irma, log=lambda *a: None)
            ok, motivo = georef_prancha.aceitavel(r, irma, max_residuo_m=0.25, min_frac=0.6)
            motivo = f"automático sobre a prancha {p['irma']} ({motivo})"
        else:
            motivo = "sem pontos de controle nem prancha irmã"
        info = {"ok": bool(ok), "motivo": motivo, "segundos": round(time.time() - t, 1)}
        if r is not None:
            info.update({k: v for k, v in r.items() if k != "M"})
        georef_prancha.salvar({"M": r["M"] if (r is not None and ok) else None, **info}, cache)
        _log(f"Prancha {p['id']}: {'OK' if ok else 'PENDENTE'} ({motivo})")
        feitas[p["id"]] = {**p, **info, "M": r["M"] if (r is not None and ok) else None}
    return list(feitas.values())


def referencia_cad(base: dict, pasta: Path, filtro: str, res: float = 0.10) -> Path:
    """Raster georreferenciado (preto sobre branco) das linhas de referência de uma prancha
    já georreferenciada — serve de "ortofoto" para registrar as pranchas irmãs."""
    caminho = pasta / f"_ref_{base['id']}.png"
    if caminho.exists():
        return caminho
    tr = pdf_cad.extrair(base["pdf"], clip=base.get("clip"))
    M = np.asarray(base["M"])
    partes = [geo.aplicar(M, q) for t in tr if filtro.upper() in t.layer.upper() for q in t.partes]
    todos = np.vstack(partes)
    e0, n0 = todos.min(0) - 20
    e1, n1 = todos.max(0) + 20
    # fundo cinza 230: georef_prancha trata >= 250 como "fora da foto"
    img = np.full((int((n1 - n0) / res) + 1, int((e1 - e0) / res) + 1, 3), 230, np.uint8)
    for u in partes:
        q = np.round(np.c_[(u[:, 0] - e0) / res, (n1 - u[:, 1]) / res]).astype(np.int32)
        cv2.polylines(img, [q], False, (0, 0, 0), 2, cv2.LINE_AA)
    cv2.imwrite(str(caminho), img)
    geo.salvar_georef(caminho, float(e0), float(n1), res, int(base.get("epsg", 31981)), {"origem": base["id"]})
    return caminho


def prancha_vetorial(p: dict) -> dict:
    """Prancha inteira em vetor (layers CAD, estilos, textos) + matriz pt -> UTM se houver."""
    pac = pdf_cad.pacote_vetorial(p["pdf"], REGRAS.get(p.get("regras", "")))
    M = p.get("M")
    esc = float(np.sqrt(abs(np.linalg.det(np.asarray(M)[:2, :2])))) if M is not None else None
    return {"id": p["id"], "nome": p["nome"], "disciplina": p.get("disciplina", "Geral"),
            "pdf": Path(p["pdf"]).name, **pac,
            "M": np.asarray(M)[:2].ravel().tolist() if M is not None else None,
            "escala_m_pt": esc, "clip_mapa": p.get("clip"),
            "georef": {k: p.get(k) for k in ("ok", "motivo", "residuo_mediano_m", "frac_05m")}}


def manchas_etapa(p: dict, epsg: int) -> list:
    """Áreas fundidas por etapa (polígonos clicáveis com área) a partir das cores da prancha."""
    tr = pdf_cad.extrair(p["pdf"], clip=p.get("clip"))
    regras = REGRAS.get(p.get("regras", ""), REGRAS_GENERICAS)
    cls = pdf_cad.classificar(tr, regras)
    vetores = []
    for r in regras:
        if r.classe not in set(cls) or ("etapa" not in r.classe.lower() and "reestrutur" not in r.classe.lower()):
            continue
        fc = pdf_cad.manchas(tr, cls, r.classe, np.asarray(p["M"]), epsg)
        for f in fc["features"]:
            f["properties"].update({"etapa": r.classe, "prancha": p["nome"], "nome": r.rotulo or r.classe})
        vetores.append({"id": f"{p['id']}-{r.classe}", "nome": f"{r.rotulo or r.classe} (áreas)",
                        "grupo": "Etapas", "etapa": r.classe, "visivel": True, "geojson": fc,
                        "estilo": {"color": r.estilo.get("color", "#888"), "weight": 2, "fillOpacity": 0.25}})
    return vetores


# 3 ---------------------------------------------------------------------------
def etapa_escopo(cfg: dict) -> dict | None:
    """Itens do orçamento com quantidades por etapa (CSV de camadas.orcamento_sanepar)."""
    e = cfg.get("escopo")
    if not e or not Path(e.get("relacao_csv", "")).exists():
        return None
    import pandas as pd
    rel = pd.read_csv(e["relacao_csv"], sep=";", decimal=",", encoding="utf-8-sig", dtype={"tabela": str, "item": str})
    itens = None
    if Path(e.get("itens_csv", "")).exists():
        itens = pd.read_csv(e["itens_csv"], sep=";", decimal=",", encoding="utf-8-sig",
                            dtype={"tabela": str, "item": str, "codigo": str})
    lin = []
    for r in rel.itertuples():
        preco = None
        if itens is not None:
            m = itens[(itens.tabela == r.tabela) & (itens.item == r.item)]
            if len(m):
                preco = m.iloc[0].get("preco_unit")
        q1 = float(r.qtd_etapa1) if pd.notna(r.qtd_etapa1) else 0.0
        q2 = float(r.qtd_etapa2) if pd.notna(r.qtd_etapa2) else 0.0
        lin.append({"tabela": r.tabela, "nome_tabela": r.nome_tabela, "item": r.item, "codigo": str(r.codigo),
                    "descricao": r.descricao, "un": r.unidade, "q1": q1, "q2": q2,
                    "etapa": r.etapa if isinstance(r.etapa, str) else "",
                    "material": r.material_base if isinstance(r.material_base, str) else "",
                    "local": r.local, "preco": float(preco) if preco is not None and pd.notna(preco) else None})
    # tabela -> desenho (para ligar item a prancha/camada no mapa)
    desenhos = {}
    if itens is not None and "projeto_desenho" in itens:
        for t, d in itens[["tabela", "projeto_desenho"]].dropna().drop_duplicates().itertuples(index=False):
            desenhos.setdefault(t, d)
    return {"itens": lin, "desenhos_por_tabela": desenhos, "fonte": e.get("fonte", "")}


# 4 ---------------------------------------------------------------------------
def modelo3d(out: Path, rel: dict, max_pontos: int, desloc=(0.0, 0.0)) -> dict:
    d = np.load(out / "sfm" / "nuvem.npz")
    xyz = d["xyz"] - [desloc[0], desloc[1], 0.0]
    return sfm.pacote_visualizador(xyz, d["rgb"], rel["cameras"], max_pontos=max_pontos)


def fotos_obliquas(cfg: dict, rel: dict, lado: int = 1400) -> dict:
    out = {}
    for c in rel["cameras"]:
        img = cv2.imread(str(Path(cfg["fotos"]) / c["nome"]))
        k = lado / max(img.shape[:2])
        out[c["nome"]] = visualizador.data_url(cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA),
                                               "webp", 72)
    return out


def vetores_cameras(rel: dict, epsg: int) -> dict:
    """Posição e direção de visada de cada foto (ponto + seta de 15 m) em lon/lat."""
    feats = []
    for c in rel["cameras"]:
        C = np.array(c["centro"])
        d = np.array(c["eixo"][:2])
        d = d / max(np.linalg.norm(d), 1e-9) * (15 if c["tipo"] == "obliqua" else 3)
        pts = np.array([C[:2], C[:2] + d])
        lon, lat = geo.para_lonlat(pts[:, 0], pts[:, 1], epsg)
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": np.c_[lon, lat].round(8).tolist()},
                      "properties": {"nome": c["nome"], "tipo": c["tipo"], "foto": c["nome"],
                                     "angulo_vertical": c["angulo_vertical"], "altura_m": round(C[2], 1)}})
    return {"type": "FeatureCollection", "features": feats}


def sondagens(cfg: dict, epsg: int) -> list:
    caminho = cfg.get("sondagens")
    if not caminho or not Path(caminho).exists():
        return []
    furos = json.loads(Path(caminho).read_text())
    if isinstance(furos, dict):                      # {"meta": ..., "furos": [...]}
        furos = furos.get("furos", [])
    for f in furos:
        if f.get("E") and f.get("N"):
            lon, lat = geo.para_lonlat(f["E"], f["N"], f.get("epsg") or f.get("epsg_inferido") or epsg)
            f["lon"], f["lat"] = round(float(lon), 8), round(float(lat), 8)
    return furos


# 5 ---------------------------------------------------------------------------
def construir(cfg_path: str | Path, refazer: set[str] = frozenset()) -> Path:
    cfg_path = Path(cfg_path)
    cfg = json.loads(cfg_path.read_text())
    out = Path(cfg["saida"])
    out.mkdir(parents=True, exist_ok=True)
    rel = etapa_sfm(cfg, out, "sfm" in refazer)
    epsg = rel["epsg"]
    desloc = etapa_controle_absoluto(cfg, out, bool({"sfm", "controle"} & refazer))
    for c in rel["cameras"]:                          # câmeras no referencial absoluto
        c["centro"] = [c["centro"][0] - desloc[0], c["centro"][1] - desloc[1], c["centro"][2]]
    orto = json.loads((out / "sfm" / "ortofoto.json").read_text())
    e0, n0, e1, n1 = orto["extensao_utm"]

    pranchas = etapa_pranchas(cfg, out, "pranchas" in refazer)
    lista, vetores, pendentes = [], [], {}
    for p in pranchas:
        lista.append(prancha_vetorial(p))
        if p.get("M") is None:
            pendentes.setdefault(p.get("disciplina", "Geral"), []).append(
                f"{p['nome']} — sem georreferência ({p.get('motivo', '')}); veja na aba Pranchas")
        elif p.get("manchas_etapa"):
            vetores += manchas_etapa(p, epsg)
    for disc, itens in cfg.get("pendentes", {}).items():
        pendentes.setdefault(disc, []).extend(itens)

    # ortofoto reduzida para o HTML
    res_html = cfg.get("res_html", 0.06)
    img = cv2.imread(str(out / "sfm" / "ortofoto.jpg"))
    k = orto["res_m_px"] / res_html
    small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    alfa = cv2.resize((img.min(axis=2) < 250).astype(np.uint8) * 255, small.shape[1::-1], interpolation=cv2.INTER_NEAREST)
    M_orto = np.array([[res_html, 0, e0], [0, -res_html, n1]])

    crs = visualizador.crs_info(epsg, [e0, n0, e1, n1], rel["alt_decolagem_m"])
    vetores.append({"id": "cameras", "nome": "Fotos do drone (posição e visada)", "grupo": "Levantamento",
                    "visivel": False, "geojson": vetores_cameras(rel, epsg), "fotos": True,
                    "estilo": {"color": "#f5c518", "weight": 2}})
    escopo = etapa_escopo(cfg)
    n_obl = sum(c["tipo"] == "obliqua" for c in rel["cameras"])
    dados = {
        "id": cfg["id"], "titulo": cfg["titulo"], "titulo_curto": cfg.get("titulo_curto", cfg["titulo"]),
        "subtitulo": cfg.get("subtitulo", ""), "crs": crs, "satelite": True,
        "bases": [{"id": "orto", "nome": f"Ortofoto drone ({len(rel['cameras']) - n_obl} fotos nadirais)",
                   "grupo": "Levantamento", "src": visualizador.data_url(np.dstack([small, alfa]), "webp", 80),
                   "w": small.shape[1], "h": small.shape[0], "m": M_orto.ravel().tolist(), "visivel": True}],
        "folhas": [], "pranchas": lista, "vetores": vetores, "pendentes": pendentes,
        "etapas": cfg.get("etapas", []),
        "escopo": escopo,
        "sondagens": sondagens(cfg, epsg),
        "modelo3d": modelo3d(out, rel, cfg.get("max_pontos_3d", 300_000), desloc),
        "fotos": fotos_obliquas(cfg, rel),
        "anotacoes": {"type": "FeatureCollection", "features": []},
        "info": [
            ["Sistema", f"{crs['nome']} (EPSG:{epsg})"],
            ["Levantamento", f"{len(rel['cameras'])} fotos ({n_obl} oblíquas), SfM com reprojeção "
                             f"{rel['reprojecao_px']:.2f} px"],
            ["Posição absoluta", f"GPS do drone (RMSE {rel['rmse_gps_m']:.1f} m)" + (
                f"; corrigida {-desloc[0]:+.2f} m E / {-desloc[1]:+.2f} m N pelo controle "
                f"topográfico ({cfg['controle_absoluto'].get('fonte', '')})" if np.any(desloc) else
                " — sem pontos de controle em campo")],
            ["Ortofoto", f"verdadeira (MDS da nuvem), {orto['res_m_px'] * 100:.0f} cm/px; embutida a "
                         f"{res_html * 100:.0f} cm/px"],
            ["Nuvem 3D", f"{rel['n_pontos']:,} pontos (Z = altura sobre a decolagem)".replace(",", ".")],
            *[[f"Prancha {f['id']}", f"{f['georef']['motivo']}; resíduo "
                                     f"{(f['georef']['residuo_mediano_m'] or 0) * 100:.0f} cm"]
              for f in lista if f["M"] is not None],
        ],
    }
    (out / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    html = visualizador.gerar(dados, out / "visualizador.html", "inline")
    _log(f"Visualizador: {html} ({html.stat().st_size / 1e6:.1f} MB)")
    if cfg.get("artifact"):
        visualizador.gerar(dados, out / "visualizador_artifact.html", "cdn", documento=False)
    return html


def main(argv=None):
    ap = argparse.ArgumentParser(description="Constrói a obra (ortofoto, 3D, pranchas, escopo, HTML)")
    ap.add_argument("config", help="obra.json")
    ap.add_argument("--refazer", default="", help="etapas a refazer: sfm,pranchas")
    a = ap.parse_args(argv)
    construir(a.config, set(filter(None, a.refazer.split(","))))


if __name__ == "__main__":
    main()
