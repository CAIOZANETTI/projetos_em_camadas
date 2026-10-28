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

from . import geo, georef_prancha, orcamento_sanepar, pdf_cad, sfm, visualizador

REGRAS = {"etapa_sanepar": "etapas_sanepar"}     # nome no obra.json -> conceitos/<arquivo>.json


def _regras(p: dict) -> list[dict]:
    """Regras da prancha (convenção de etapa) ou as classes genéricas de layer."""
    return pdf_cad.regras(REGRAS.get(p.get("regras", ""), "classes_genericas"))


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
        desloc = np.array(json.loads(arq.read_text())["deslocamento_m"])
        _aplicar_deslocamento(out, desloc)
        return desloc
    M = np.vstack([np.asarray(c["afim_pt_utm"], float), [0, 0, 1]])
    tr = pdf_cad.extrair(c["pdf"])
    pts = georef_prancha.pontos_de_traco(tr, passo_pt=4)
    orto = out / "sfm" / "ortofoto.jpg"
    r = georef_prancha.registrar(pts, orto, M_inicial=M, log=_log)
    d = geo.aplicar(r["M"], pts[::100]) - geo.aplicar(M, pts[::100])
    desloc = d.mean(0)                                # ortofoto (GPS) - absoluto
    arq.write_text(json.dumps({"deslocamento_m": desloc.round(3).tolist(), "desvio_m": d.std(0).round(3).tolist(),
                               "residuo_mediano_m": r["residuo_mediano_m"], "fonte": c.get("fonte", ""),
                               "prancha": Path(c["pdf"]).name}, indent=2, ensure_ascii=False))
    _log(f"Controle absoluto: ortofoto deslocada {-desloc[0]:+.2f} m E, {-desloc[1]:+.2f} m N "
         f"(viés do GPS do drone; desvio {d.std(0).max():.2f} m)")
    _aplicar_deslocamento(out, desloc)
    return desloc


def _aplicar_deslocamento(out: Path, desloc: np.ndarray) -> None:
    """Desloca o georreferenciamento da ortofoto e do MDS (idempotente: marca no .json)."""
    for img in (out / "sfm" / "ortofoto.jpg", out / "sfm" / "ortofoto_mds.png"):
        if not img.exists():
            continue
        meta = json.loads(img.with_suffix(".json").read_text())
        if "ajuste_absoluto_m" in meta:
            continue
        e0, n1 = meta["canto_sup_esq"]
        if "extensao_utm" in meta:
            x = meta["extensao_utm"]
            meta["extensao_utm"] = [x[0] - desloc[0], x[1] - desloc[1], x[2] - desloc[0], x[3] - desloc[1]]
        meta["ajuste_absoluto_m"] = np.round(desloc, 3).tolist()
        geo.salvar_georef(img, e0 - desloc[0], n1 - desloc[1], meta["res_m_px"], meta["epsg"],
                          {k: v for k, v in meta.items() if k not in ("epsg", "canto_sup_esq", "res_m_px")})


def etapa_controle_vertical(cfg: dict, out: Path, desloc: np.ndarray, epsg: int) -> dict | None:
    """Plano z_nuvem -> cota pelas cotas de boca das sondagens (`controle_vertical` no obra.json)."""
    c = cfg.get("controle_vertical")
    if not c:
        return None
    pontos = {}
    for f in sondagens(cfg, epsg):
        if f.get("E") and f.get("N") and f.get(c.get("campo_cota", "cota_boca")) is not None:
            chave = f["id"].rstrip("A") if c.get("juntar_variantes_A", True) else f["id"]
            pontos.setdefault(chave, {"id": chave, "E": f["E"], "N": f["N"], "cota": f[c.get("campo_cota", "cota_boca")]})
    xyz = np.load(out / "sfm" / "nuvem.npz")["xyz"] - [desloc[0], desloc[1], 0.0]
    ajuste = sfm.ajustar_vertical(xyz, list(pontos.values()))
    ajuste["fonte"] = c.get("fonte", "")
    (out / "sfm" / "ajuste_vertical.json").write_text(json.dumps(ajuste, indent=1, ensure_ascii=False))
    if ajuste["ok"]:
        _log(f"Controle vertical: {ajuste['modelo']} em {ajuste['usados']} pontos, validação cruzada "
             f"{ajuste['rms_validacao_cruzada_m']:.2f} m; descartados {ajuste['descartados']}, sem nuvem {ajuste['sem_nuvem']}")
    return ajuste if ajuste["ok"] else None


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
        filtro_ref = p.get("layers_referencia", "EXIST")
        pts = georef_prancha.pontos_de_traco(tr, filtro=lambda t, f=filtro_ref: re.search(f, t["layer"], re.I) is not None,
                                             passo_pt=3)
        r, ok, motivo = None, False, ""
        pc = p.get("pontos_controle")
        irma = feitas.get(p.get("irma", ""), {}).get("M")
        if p.get("M_absoluta"):
            # afim já conhecida (ex.: ajustada em coordenadas topográficas): usa sem ICP
            r = {"M": np.vstack([np.asarray(p["M_absoluta"], float), [0, 0, 1]]), "residuo_mediano_m": None,
                 "frac_05m": None}
            ok, motivo = True, "afim absoluta (coordenadas topográficas)"
        elif p.get("malha"):
            # malha de coordenadas impressa no próprio desenho: exata, não depende da ortofoto
            r = georef_prancha.registrar_malha(tr, p["malha"], escala=p.get("escala"), log=_log)
            ok, motivo = r["ok"], r["motivo"]
        elif pc:
            M0 = georef_prancha.matriz_inicial(pc["pt"], pc["utm"])
            r = georef_prancha.registrar(pts, orto, M_inicial=M0, log=_log) if len(pts) > 200 else \
                {"M": M0, "residuo_mediano_m": None, "frac_05m": None, "escala_m_pt": None}
            ok, motivo = True, "pontos de controle" + (" + ICP" if len(pts) > 200 else "")
        elif irma is not None:
            # referência = linhas de existentes da prancha irmã já georreferenciada (CAD × CAD)
            ref = referencia_cad(feitas[p["irma"]], pasta, p.get("layers_irma", "EXIST"), p.get("res_irma", 0.10))
            r = georef_prancha.registrar_cad(tr, ref, irma, p.get("layers_referencia", "EXIST"), log=_log)
            ok, motivo = r["ok"], f"automático sobre a prancha {p['irma']}: {r['motivo']}"
            if not ok and len(pts) > 200:                 # alternativa: ICP a partir da escala da irmã
                r2 = georef_prancha.registrar(pts, ref, M_irma=irma, log=lambda *a: None)
                ok2, m2 = georef_prancha.aceitavel(r2, irma, max_residuo_m=0.25, min_frac=0.6)
                if ok2:
                    r, ok, motivo = r2, True, f"automático (ICP) sobre a prancha {p['irma']}"
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
    import hashlib
    caminho = pasta / f"_ref_{base['id']}_{hashlib.md5(f'{filtro}|{res}'.encode()).hexdigest()[:6]}.png"
    if caminho.exists():
        return caminho
    tr = pdf_cad.extrair(base["pdf"], clip=base.get("clip"))
    M = np.asarray(base["M"])
    partes = [geo.aplicar(M, q) for t in tr if re.search(filtro, t["layer"], re.I) for q in t["partes"]]
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


def prancha_vetorial(p: dict, extensao_utm=None, margem_m: float = 25.0) -> dict:
    """Prancha inteira em vetor (layers CAD, estilos, textos) + matriz pt -> UTM se houver.

    Grupo/subgrupo da prancha e de cada layer vêm de `conceitos/disciplinas.json` (ou do
    obra.json). Recorte do mapa: `clip` explícito; senão a janela da malha de coordenadas
    (planta das adutoras, fora do voo); senão a área do levantamento + margem levada para o
    espaço da folha. Carimbo e tabelas ficam só na aba Pranchas.
    """
    pac = pdf_cad.pacote_vetorial(p["pdf"], _regras(p) if p.get("regras") in REGRAS else None)
    g, sg = pdf_cad.disciplina_da_prancha(Path(p["pdf"]).name, p["nome"])
    g, sg = p.get("grupo", g), p.get("subgrupo", sg)
    for l in pac["layers"]:
        l["grupo"], l["subgrupo"] = pdf_cad.disciplina_do_layer(l["nome"], (g, sg))
    M = p.get("M")
    clip = p.get("clip") or p.get("janela_pt")
    if clip is None and M is not None and extensao_utm is not None:
        e0, n0, e1, n1 = extensao_utm
        cantos = np.array([[e0 - margem_m, n0 - margem_m], [e1 + margem_m, n0 - margem_m],
                           [e1 + margem_m, n1 + margem_m], [e0 - margem_m, n1 + margem_m]])
        q = geo.aplicar(np.linalg.inv(np.asarray(M)), cantos)
        clip = [max(0.0, float(q[:, 0].min())), max(0.0, float(q[:, 1].min())),
                min(pac["largura"], float(q[:, 0].max())), min(pac["altura"], float(q[:, 1].max()))]
    esc = float(np.sqrt(abs(np.linalg.det(np.asarray(M)[:2, :2])))) if M is not None else None
    return {"id": p["id"], "nome": p["nome"], "disciplina": p.get("disciplina", g), "grupo": g, "subgrupo": sg,
            "pdf": Path(p["pdf"]).name, **pac,
            "M": np.asarray(M)[:2].ravel().tolist() if M is not None else None,
            "escala_m_pt": esc, "clip_mapa": clip,
            "georef": {k: p.get(k) for k in ("ok", "motivo", "residuo_mediano_m", "frac_05m", "residuo_max_m")}}


def manchas_etapa(p: dict, epsg: int) -> list:
    """Áreas fundidas por etapa (polígonos clicáveis com área) a partir das cores da prancha."""
    tr = pdf_cad.extrair(p["pdf"], clip=p.get("clip"))
    regras = _regras(p)
    cls = pdf_cad.classificar(tr, regras)
    vetores = []
    for r in regras:
        classe, rotulo = r["classe"], r.get("rotulo") or r["classe"]
        if classe not in set(cls) or ("etapa" not in classe.lower() and "reestrutur" not in classe.lower()):
            continue
        fc = pdf_cad.manchas(tr, cls, classe, np.asarray(p["M"]), epsg)
        for f in fc["features"]:
            f["properties"].update({"etapa": classe, "prancha": p["nome"], "nome": rotulo})
        vetores.append({"id": f"{p['id']}-{classe}", "nome": f"{rotulo} (áreas)",
                        "grupo": "Etapas", "subgrupo": "Áreas por etapa", "etapa": classe, "visivel": True,
                        "geojson": fc,
                        "estilo": {"color": r.get("estilo", {}).get("color", "#888"), "weight": 2, "fillOpacity": 0.25}})
    return vetores


# 3 ---------------------------------------------------------------------------
def etapa_escopo(cfg: dict) -> dict | None:
    """Escopo do contrato por etapa, sem preço (decisão do Caio, 28/10/2026).

    Itens da relação de materiais com quantidade da 1ª e da 2ª etapa, a especificação do cadastro de materiais
    Sanepar pelo código (seq_estoque) e alertas: quantidade com cara de data do Excel, unidade diferente da do
    orçamento ou do cadastro, item sem código, código fora do cadastro ou despadronizado.
    """
    e = cfg.get("escopo")
    if not e or not e.get("relacao_csv") or not Path(e["relacao_csv"]).exists():
        return None
    import pandas as pd
    rel = pd.read_csv(e["relacao_csv"], sep=";", decimal=",", encoding="utf-8-sig", dtype={"tabela": str, "item": str})
    unidades, desenhos = {}, {}
    if e.get("itens_csv") and Path(e["itens_csv"]).exists():          # Path("") = "." existe
        itens = pd.read_csv(e["itens_csv"], sep=";", decimal=",", encoding="utf-8-sig",
                            dtype={"tabela": str, "item": str, "codigo": str})
        for t, it, cod, un, q in itens[["tabela", "item", "codigo", "unidade", "quantidade"]].itertuples(index=False):
            unidades.setdefault((str(t), str(it), str(cod)), (str(un), q))
        if "projeto_desenho" in itens:
            for t, d in itens[["tabela", "projeto_desenho"]].dropna().drop_duplicates().itertuples(index=False):
                desenhos.setdefault(t, d)
    cat = orcamento_sanepar.catalogo(e["catalogo"]) if e.get("catalogo") and Path(e["catalogo"]).exists() else {}

    def qtd(v):
        """Quantidade numérica; serial de data do Excel (≈ 2009–2036) vira alerta."""
        if pd.isna(v):
            return 0.0, None
        v = float(v)
        if 40000 <= v <= 50000 and v == int(v):
            return 0.0, f"quantidade na planilha parece data do Excel ({int(v)})"
        return v, None

    def mesma_unidade(a, b):
        sinonimos = {"pç": "un", "pc": "un", "peça": "un", "und": "un", "cj": "cj", "conj": "cj", "ml": "m"}
        a, b = str(a).strip().lower(), str(b).strip().lower()
        return sinonimos.get(a, a) == sinonimos.get(b, b)

    lin = []
    for r in rel.itertuples():
        codigo = str(r.codigo).split(".")[0]
        q1, a1 = qtd(r.qtd_etapa1)
        q2, a2 = qtd(r.qtd_etapa2)
        alertas = [a for a in (a1, a2) if a]
        # tabela+item+código: o número do item repete entre blocos
        un_orc, q_orc = unidades.get((str(r.tabela), str(r.item), codigo), (None, None))
        if un_orc and not mesma_unidade(r.unidade, un_orc):
            alertas.append(f"unidade diverge do orçamento ({r.unidade} × {un_orc} {q_orc})")
        espec = cat.get(codigo)
        if cat and not codigo.isdigit():
            alertas.append("item sem código de material Sanepar")
        elif cat and espec is None:
            alertas.append(f"código {codigo} fora do cadastro de materiais Sanepar")
        elif espec:
            if espec.get("unidade_medida") and not mesma_unidade(r.unidade, espec["unidade_medida"]):
                alertas.append(f"unidade do cadastro Sanepar é {espec['unidade_medida']} (relação: {r.unidade})")
            if str(espec.get("situacao", "")).startswith("4"):          # 1/3 licitável, 6 para obra, 2 SCD: normais
                alertas.append(f"situação no cadastro: {espec['situacao']}")
        lin.append({"tabela": r.tabela, "nome_tabela": r.nome_tabela, "item": r.item, "codigo": codigo,
                    "descricao": r.descricao, "un": r.unidade, "q1": q1, "q2": q2,
                    "alerta": "; ".join(alertas) or None,
                    "etapa": r.etapa if isinstance(r.etapa, str) else "",
                    "material": r.material_base if isinstance(r.material_base, str) else "",
                    "local": r.local,
                    "cadastro": {k: espec[k] for k in ("descricao", "unidade_medida", "norma_eb", "situacao", "familia",
                                                       "material_base", "dn", "pn", "qtd_marcas", "marcas_homologadas")
                                 if k in espec} if espec else None})
    por_tabela = {}
    for item in lin:
        t = por_tabela.setdefault(item["tabela"], {"nome": item["nome_tabela"], "n": 0, "n_q1": 0, "n_q2": 0,
                                                   "n_alerta": 0})
        t["n"] += 1
        t["n_q1"] += item["q1"] > 0
        t["n_q2"] += item["q2"] > 0
        t["n_alerta"] += bool(item["alerta"])
    totais = {"itens": len(lin), "itens_q1": sum(i["q1"] > 0 for i in lin), "itens_q2": sum(i["q2"] > 0 for i in lin),
              "com_alerta": sum(bool(i["alerta"]) for i in lin),
              "no_cadastro": sum(i["cadastro"] is not None for i in lin)}
    return {"itens": lin, "por_tabela": por_tabela, "totais": totais, "desenhos_por_tabela": desenhos,
            "fonte": e.get("fonte", ""),
            "fonte_cadastro": "cadastro de materiais Sanepar (sanepar_mat, coletado em 08/2026), só especificação"
            if cat else None}


# 4 ---------------------------------------------------------------------------
def modelo3d(out: Path, rel: dict, max_pontos: int, desloc=(0.0, 0.0), vertical: dict | None = None) -> dict:
    """Nuvem e câmeras no referencial absoluto; com controle vertical, z em cota."""
    d = np.load(out / "sfm" / "nuvem.npz")
    xyz = d["xyz"] - [desloc[0], desloc[1], 0.0]
    cams = rel["cameras"]
    if vertical:
        xyz = sfm.aplicar_vertical(xyz, vertical)
        cams = [{**c, "centro": sfm.aplicar_vertical(np.array([c["centro"]], float), vertical)[0].tolist()} for c in cams]
    pacote = sfm.pacote_visualizador(xyz, d["rgb"], cams, max_pontos=max_pontos)
    pacote["referencia_z"] = "cota (m), plano ajustado às sondagens" if vertical else "altura sobre a decolagem (m)"
    return pacote


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


def estacas(cfg: dict, epsg: int) -> dict | None:
    """Estacas (CSV id;E;N;diametro_cm;cota_arrasamento;comprimento_m;estrutura;...) -> vetor."""
    caminho = cfg.get("estacas")
    if not caminho or not Path(caminho).exists():
        return None
    import pandas as pd
    t = pd.read_csv(caminho, sep=";", decimal=",", dtype={"id": str}).dropna(subset=["E", "N"])
    lon, lat = geo.para_lonlat(t["E"].to_numpy(float), t["N"].to_numpy(float), epsg)
    feats = []
    for (_, r), x, y in zip(t.iterrows(), lon, lat):
        props = {k: (None if pd.isna(v) else (float(v) if isinstance(v, (int, float, np.integer, np.floating)) else str(v)))
                 for k, v in r.items() if k not in ("x_pt_prancha", "y_pt_prancha")}
        props["tipo"] = "estaca"
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point", "coordinates": [round(float(x), 8), round(float(y), 8)]}})
    return {"id": "estacas", "nome": f"Estacas hélice contínua ({len(feats)})", "grupo": "Civil",
            "subgrupo": "Geotecnia e fundação", "visivel": False, "estacas": True,
            "geojson": {"type": "FeatureCollection", "features": feats},
            "estilo": {"color": "#7c3aed", "radius": 3, "weight": 1, "fillOpacity": 0.8}}


def vetor_supressao(cfg: dict, out: Path, pranchas: list) -> dict | None:
    """Supressão vegetal estimada na faixa de obra das pranchas com regras de etapa."""
    c = cfg.get("supressao")
    if not c:
        return None
    from . import supressao
    etapas = c.get("etapas", ["1ª etapa", "2ª etapa", "3ª etapa (futura)"])
    geoms: dict[str, list] = {}
    for p in pranchas:
        if p.get("M") is None or p.get("regras") not in REGRAS:
            continue
        tr = pdf_cad.extrair(p["pdf"], clip=p.get("clip"))
        cls = pdf_cad.classificar(tr, _regras(p))
        for e, gs in supressao.geoms_utm_de_tracos(tr, cls, np.asarray(p["M"]), {e: e for e in etapas}).items():
            geoms.setdefault(e, []).extend(gs)
    if not geoms:
        return None
    fc = supressao.estimar(out / "sfm" / "ortofoto.jpg", out / "sfm" / "ortofoto_mds.png",
                           {e: geoms[e] for e in etapas if e in geoms},
                           faixa_m=c.get("faixa_m", 4.0), folga_unidades_m=c.get("folga_unidades_m", 2.0),
                           altura_min_m=c.get("altura_min_m", 1.5))
    resumo = fc.pop("resumo")
    _log("Supressão vegetal estimada: " + "; ".join(
        f"{e}: {r['supressao_m2']:.0f} m² árvores/arbustos, {r['limpeza_m2']:.0f} m² rasteira" for e, r in resumo.items()))
    return {"id": "supressao", "nome": "Supressão vegetal estimada (faixa de obra)", "grupo": "Intervenções",
            "subgrupo": "Supressão vegetal", "visivel": False, "geojson": fc, "resumo": resumo,
            "estilo": {"color": "#dc2626", "weight": 1, "fillOpacity": 0.35}}


def vetor_marcos(cfg: dict, epsg: int, centro_utm) -> dict | None:
    """Marcos geodésicos (Sanepar MRRN/RN, IBGE, municipal, RBMC) num raio da obra."""
    c = cfg.get("referencias_geodesicas")
    if not c or not Path(c["pasta"]).exists():
        return None
    from . import sig
    lon, lat = geo.para_lonlat(centro_utm[0], centro_utm[1], epsg)
    fc = sig.marcos_proximos(c["pasta"], float(lon), float(lat), c.get("raio_m", 3000), epsg)
    _log(f"Marcos geodésicos a até {c.get('raio_m', 3000)} m: {len(fc['features'])} "
         f"(mais próximo: {fc['features'][0]['properties']['nome'] if fc['features'] else '—'})")
    return {"id": "marcos", "nome": f"Marcos geodésicos ({len(fc['features'])})", "grupo": "Levantamento",
            "subgrupo": "Referências geodésicas", "visivel": True, "geojson": fc,
            "estilo": {"color": "#0ea5e9", "radius": 5, "weight": 2, "fillOpacity": 0.9}}


def cronograma_4d(cfg: dict, dados: dict) -> dict | None:
    """Resolve os seletores de cada atividade em elementos do HTML e calcula a curva S planejada.

    Seletor: pranchas (ids), grupos ([grupo, subgrupo] dos layers), etapas (classe dos layers e manchas),
    vetores (ids), estacas (estrutura), intervencoes (tipos desenhados pelo usuário). O front só compara a data
    escolhida com início/fim — a conta (elementos e curva S) é daqui (regra 12 do estilo).
    """
    c = cfg.get("cronograma")
    if not c:
        return None
    estacas = next((v for v in dados["vetores"] if v["id"] == "estacas"), None)
    ids_vetor = {v["id"] for v in dados["vetores"]}
    atividades = []
    for a in c["atividades"]:
        sel = a.get("seletor", {})
        layers = {}
        for pr in dados["pranchas"]:
            if pr["M"] is None:
                continue
            nomes = [l["nome"] for l in pr["layers"]
                     if (pr["id"] in sel.get("pranchas", []) and not sel.get("grupos") and not sel.get("etapas"))
                     or [l.get("grupo"), l.get("subgrupo")] in sel.get("grupos", [])
                     or (l.get("classe") in sel.get("etapas", []) and not sel.get("grupos"))
                     or (pr["id"] in sel.get("pranchas", []) and [l.get("grupo"), l.get("subgrupo")] in sel.get("grupos", []))]
            if nomes:
                layers[pr["id"]] = nomes
        vetores = [v["id"] for v in dados["vetores"]
                   if v["id"] in sel.get("vetores", []) or (v.get("etapa") and v["etapa"] in sel.get("etapas", []))]
        ids_estacas = [f["properties"]["id"] for f in (estacas["geojson"]["features"] if estacas else [])
                       if f["properties"].get("estrutura") in sel.get("estacas", [])]
        n = sum(map(len, layers.values())) + len(vetores) + len(ids_estacas) + len(sel.get("intervencoes", []))
        if sel and not n:
            _log(f"  cronograma: atividade {a['id']} sem elemento no mapa (seletor {sel})")
        faltam = [v for v in sel.get("vetores", []) if v not in ids_vetor]
        atividades.append({**{k: v for k, v in a.items() if k != "seletor"},
                           "elementos": {"layers": layers, "vetores": vetores, "estacas": ids_estacas,
                                         "intervencoes": sel.get("intervencoes", [])},
                           "n_elementos": n, "vetores_ausentes": faltam})
    fim = max(a["fim_dia"] for a in atividades)
    dias = np.arange(fim + 1)
    peso = np.array([a.get("peso_pct", 0.0) for a in atividades], float)
    inicio = np.array([a["inicio_dia"] for a in atividades], float)
    termino = np.array([a["fim_dia"] for a in atividades], float)
    avanco = np.clip((dias[:, None] - inicio) / np.maximum(termino - inicio, 1), 0, 1)   # linear por atividade
    curva = avanco @ peso / max(peso.sum(), 1e-9) * 100
    return {**{k: v for k, v in c.items() if k != "atividades"}, "atividades": atividades,
            "curva_s": {"dia": dias[::5].tolist() + ([int(fim)] if fim % 5 else []),
                        "planejado_pct": np.round(np.r_[curva[::5], [curva[-1]] if fim % 5 else []], 2).tolist()},
            "peso_total_pct": round(float(peso.sum()), 2)}


# 5 ---------------------------------------------------------------------------
def construir(cfg_path: str | Path, refazer: set[str] = frozenset()) -> Path:
    cfg_path = Path(cfg_path)
    cfg = json.loads(cfg_path.read_text())
    out = Path(cfg["saida"])
    out.mkdir(parents=True, exist_ok=True)
    rel = etapa_sfm(cfg, out, "sfm" in refazer)
    epsg = rel["epsg"]
    desloc = etapa_controle_absoluto(cfg, out, "sfm" in refazer)   # remedir exige ortofoto nova
    vertical = etapa_controle_vertical(cfg, out, desloc, epsg)
    for c in rel["cameras"]:                          # câmeras no referencial absoluto
        c["centro"] = [c["centro"][0] - desloc[0], c["centro"][1] - desloc[1], c["centro"][2]]
    orto = json.loads((out / "sfm" / "ortofoto.json").read_text())
    e0, n0, e1, n1 = orto["extensao_utm"]

    pranchas = etapa_pranchas(cfg, out, "pranchas" in refazer)
    lista, vetores, pendentes = [], [], {}
    for p in pranchas:
        lista.append(prancha_vetorial(p, [e0, n0, e1, n1]))
        if lista[-1]["M"] is not None:
            lista[-1]["quantitativos"] = pdf_cad.quantitativos(lista[-1])
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
                    "subgrupo": "Drone",
                    "visivel": False, "geojson": vetores_cameras(rel, epsg), "fotos": True,
                    "estilo": {"color": "#f5c518", "weight": 2}})
    for v in (estacas(cfg, epsg), vetor_supressao(cfg, out, pranchas),
              vetor_marcos(cfg, epsg, ((e0 + e1) / 2, (n0 + n1) / 2))):
        if v:
            vetores.append(v)
    escopo = etapa_escopo(cfg)
    furos = sondagens(cfg, epsg)
    if vertical:                                      # boca do furo × terreno da nuvem já em cota, por furo
        por_id = {l["id"]: l for l in vertical["pontos"]}
        for s in furos:
            l = por_id.get(s["id"]) or por_id.get(s["id"].rstrip("A"))
            if l:
                terreno = (None if l["z_nuvem"] is None else
                           float(sfm.aplicar_vertical(np.array([[l["E"], l["N"], l["z_nuvem"]]]), vertical)[0, 2]))
                s["controle_vertical"] = {
                    "situacao": "sem nuvem" if terreno is None else "descartado" if l.get("descartado") else "usado",
                    "terreno_m": None if terreno is None else round(terreno, 2),
                    "diferenca_m": None if terreno is None else round(l["cota"] - terreno, 2)}
    n_obl = sum(c["tipo"] == "obliqua" for c in rel["cameras"])
    dados = {
        "id": cfg["id"], "titulo": cfg["titulo"], "titulo_curto": cfg.get("titulo_curto", cfg["titulo"]),
        "subtitulo": cfg.get("subtitulo", ""), "crs": crs, "satelite": True,
        "bases": [{"id": "orto", "nome": f"Ortofoto drone ({len(rel['cameras']) - n_obl} fotos nadirais)",
                   "grupo": "Levantamento", "src": visualizador.data_url(np.dstack([small, alfa]), "webp", 80),
                   "w": small.shape[1], "h": small.shape[0], "m": M_orto.ravel().tolist(), "visivel": True}],
        "folhas": [], "pranchas": lista, "vetores": vetores, "pendentes": pendentes,
        "etapas": cfg.get("etapas", []),
        "grupos": pdf_cad.disciplinas()["grupos"],
        "intervencoes": json.loads((pdf_cad.CONCEITOS / "intervencoes.json").read_text(encoding="utf-8"))["intervencoes"],
        "cronograma": None,
        "escopo": escopo,
        "sondagens": furos,
        "modelo3d": modelo3d(out, rel, cfg.get("max_pontos_3d", 300_000), desloc, vertical),
        "vertical": vertical,
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
            ["Nuvem 3D", f"{rel['n_pontos']:,} pontos".replace(",", ".") + (
                " (Z em cota)" if vertical else " (Z = altura sobre a decolagem)")],
            *([["Cotas", f"plano ajustado a {vertical['usados']} furos SPT ({vertical['fonte']}); validação cruzada "
                         f"{vertical['rms_validacao_cruzada_m']:.2f} m; descartados (copa/edificação) "
                         f"{', '.join(vertical['descartados']) or '—'}"]] if vertical else []),
            *[[f"Prancha {f['id']}", f"{f['georef']['motivo']}; resíduo "
                                     f"{(f['georef']['residuo_mediano_m'] or 0) * 100:.0f} cm"]
              for f in lista if f["M"] is not None],
        ],
    }
    dados["cronograma"] = cronograma_4d(cfg, dados)
    (out / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    if cfg.get("sig", True):
        etapa_sig(out, dados, pranchas, epsg)
    html = visualizador.gerar(dados, out / "visualizador.html", "inline")
    _log(f"Visualizador: {html} ({html.stat().st_size / 1e6:.1f} MB)")
    if cfg.get("artifact"):
        visualizador.gerar(dados, out / "visualizador_artifact.html", "cdn", documento=False)
    return html


def etapa_sig(out: Path, dados: dict, pranchas: list, epsg: int) -> None:
    """GeoTIFF (ortofoto, MDS), GeoPackage com todas as camadas e .points do QGIS."""
    from . import sig
    pasta = out / "sig"
    sig.geotiff(out / "sfm" / "ortofoto.jpg", pasta / "ortofoto.tif")
    vertical = dados.get("vertical")
    sig.geotiff(out / "sfm" / "ortofoto_mds.png", pasta / "mds.tif", mds=True, correcao_z=(
        lambda E, N: sfm.aplicar_vertical(np.c_[E.ravel(), N.ravel(), np.zeros(E.size)], vertical)[:, 2].reshape(E.shape))
        if vertical else None)
    for p, pv in zip(pranchas, dados["pranchas"]):
        if p.get("M") is not None:
            sig.pontos_qgis(np.asarray(p["M"]), pv["clip_mapa"], pasta / "pontos" / f"{p['id']}.points", epsg)
    sig.geopackage(dados, pasta / "obra.gpkg", epsg)
    _log(f"SIG: {pasta}/ (ortofoto.tif, mds.tif, obra.gpkg, pontos/*.points)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Constrói a obra (ortofoto, 3D, pranchas, escopo, HTML)")
    ap.add_argument("config", help="obra.json")
    ap.add_argument("--refazer", default="", help="etapas a refazer: sfm,pranchas")
    a = ap.parse_args(argv)
    construir(a.config, set(filter(None, a.refazer.split(","))))


if __name__ == "__main__":
    main()
