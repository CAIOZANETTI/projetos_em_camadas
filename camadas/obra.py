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
import hashlib
import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from . import (
    conferencia_cavas,
    construtivos,
    contrato_211,
    eap,
    eap_html,
    eap_padrao,
    eap_painel,
    eap_vista,
    escavacao,
    escopo_obra,
    evidencias,
    extracao,
    extrair_gavetas,
    gavetas,
    geo,
    georef_prancha,
    geotecnia,
    inventario,
    obras_lineares,
    orcamento_sanepar,
    pdf_cad,
    prancha,
    sfm,
    valas,
    visualizador,
)

REGRAS = {"etapa_sanepar": "etapas_sanepar"}     # nome no obra.json -> conceitos/<arquivo>.json


def _regras(p: dict) -> list[dict]:
    """Regras da prancha (convenção de etapa) ou as classes genéricas de layer."""
    return pdf_cad.regras(REGRAS.get(p.get("regras", ""), "classes_genericas"))


AVISOS_DO_BUILD: list[str] = []      # etapas puladas por insumo ausente: vão ao HTML, não só ao terminal
MARCA_PENDENCIA = "(pendência"


def _log(*a):
    texto = " ".join(map(str, a))
    if MARCA_PENDENCIA in texto and texto.strip() not in AVISOS_DO_BUILD:
        AVISOS_DO_BUILD.append(texto.strip())
    print(*a, flush=True)


def _avisos_nas_pendencias(dados: dict, avisos: list[str]) -> None:
    """Etapas puladas com motivo entram em `dados["pendentes"]["Build (etapas puladas)"]`, que o HTML já mostra."""
    if avisos:
        dados.setdefault("pendentes", {}).setdefault("Build (etapas puladas)", []).extend(avisos)


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
    """Plano z_nuvem -> cota pelas cotas de boca das sondagens (`controle_vertical` no obra.json) ou por um arquivo
    `controle_vertical.pontos` ([{id, E, N, cota}] ou {"pontos": [...]}, ex.: piso já concretado com cota de projeto).
    `controle_vertical.modelo = "offset"` força só o deslocamento (pontos concentrados não sustentam inclinação)."""
    c = cfg.get("controle_vertical")
    if not c:
        return None
    pontos = {}
    for f in sondagens(cfg, epsg):
        if f.get("E") and f.get("N") and f.get(c.get("campo_cota", "cota_boca")) is not None:
            chave = f["id"].rstrip("A") if c.get("juntar_variantes_A", True) else f["id"]
            pontos.setdefault(chave, {"id": chave, "E": f["E"], "N": f["N"], "cota": f[c.get("campo_cota", "cota_boca")]})
    if c.get("pontos"):
        lidos = json.loads(Path(c["pontos"]).read_text())
        for p in lidos.get("pontos", []) if isinstance(lidos, dict) else lidos:
            pontos.setdefault(p["id"], {"id": p["id"], "E": p["E"], "N": p["N"], "cota": p["cota"]})
    xyz = np.load(out / "sfm" / "nuvem.npz")["xyz"] - [desloc[0], desloc[1], 0.0]
    ajuste = sfm.ajustar_vertical(xyz, list(pontos.values()), so_offset=c.get("modelo") == "offset")
    ajuste["fonte"] = c.get("fonte", "")
    (out / "sfm" / "ajuste_vertical.json").write_text(json.dumps(ajuste, indent=1, ensure_ascii=False))
    if ajuste["ok"]:
        _log(f"Controle vertical: {ajuste['modelo']} em {ajuste['usados']} pontos, validação cruzada "
             f"{ajuste['rms_validacao_cruzada_m']:.2f} m; descartados {ajuste['descartados']}, sem nuvem {ajuste['sem_nuvem']}")
    return ajuste if ajuste["ok"] else None


# 2 ---------------------------------------------------------------------------
def _pdf_ausente(p: dict) -> bool:
    """Prancha do obra.json cujo PDF não está no disco: pendência no log (vai ao HTML), sem derrubar o build."""
    if Path(p["pdf"]).exists():
        return False
    _log(f"Prancha {p['id']}: NÃO LIDA — PDF ausente no disco: {p['pdf']} (pendência; o build segue)")
    return True


def _registrar_prancha(p: dict, tr, pts, orto, pasta: Path, feitas: dict) -> tuple:
    """Georreferencia uma prancha pelo primeiro recurso que ela traz (afim absoluta, malha, pontos de controle ou
    prancha irmã); devolve `(resultado | None, ok, motivo)`."""
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
        if not r["ok"] and p.get("continuidade"):
            r = _malha_por_continuidade(p, tr, feitas, r["motivo"])
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
            ok2, _ = georef_prancha.aceitavel(r2, irma, max_residuo_m=0.25, min_frac=0.6)
            if ok2:
                r, ok, motivo = r2, True, f"automático (ICP) sobre a prancha {p['irma']}"
    else:
        motivo = "sem pontos de controle nem prancha irmã"
    return r, ok, motivo


def etapa_pranchas(cfg: dict, out: Path, refazer: bool) -> list[dict]:
    """Georreferencia cada prancha (cache em pranchas/<id>.json)."""
    orto = out / "sfm" / "ortofoto.jpg"
    pasta = out / "pranchas"
    pasta.mkdir(parents=True, exist_ok=True)
    feitas: dict[str, dict] = {}
    for p in cfg.get("pranchas", []):
        cache = pasta / f"{p['id']}.json"
        if not cache.exists() and _pdf_ausente(p):
            continue
        assinatura = _assinatura_georef(p)
        if cache.exists() and not refazer:
            r = json.loads(cache.read_text())
            # cache vale se foi feito com a mesma configuração; o antigo, sem assinatura, só se a prancha não traz
            # afim absoluta (ela muda no obra.json e o cache a ignorava em silêncio: a f010 ficou sem georreferência)
            if r.get("assinatura") == assinatura or ("assinatura" not in r and not p.get("M_absoluta")):
                r["M"] = np.array(r["M"]) if r.get("M") else None
                feitas[p["id"]] = {**p, **r}
                continue
        t = time.time()
        tr = pdf_cad.extrair(p["pdf"], clip=p.get("clip"))
        filtro_ref = p.get("layers_referencia", "EXIST")
        pts = georef_prancha.pontos_de_traco(tr, filtro=lambda t, f=filtro_ref: re.search(f, t["layer"], re.IGNORECASE) is not None,
                                             passo_pt=3)
        r, ok, motivo = _registrar_prancha(p, tr, pts, orto, pasta, feitas)
        info = {"ok": bool(ok), "motivo": motivo, "segundos": round(time.time() - t, 1), "assinatura": assinatura}
        if r is not None:
            info.update({k: v for k, v in r.items() if k != "M"})
        georef_prancha.salvar({"M": r["M"] if (r is not None and ok) else None, **info}, cache)
        _log(f"Prancha {p['id']}: {'OK' if ok else 'PENDENTE'} ({motivo})")
        feitas[p["id"]] = {**p, **info, "M": r["M"] if (r is not None and ok) else None}
    return list(feitas.values())


CHAVES_GEOREF = ("pdf", "clip", "M_absoluta", "malha", "escala", "continuidade", "pontos_controle", "irma",
                 "layers_irma", "layers_referencia", "res_irma")


def _assinatura_georef(p: dict) -> str:
    """Hash das chaves do obra.json que decidem a georreferência da prancha (a do cache tem de ser igual)."""
    base = json.dumps({k: p.get(k) for k in CHAVES_GEOREF}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def _malha_por_continuidade(p: dict, tr: list, feitas: dict, motivo_malha: str) -> dict:
    """Malha que não fecha (rótulo errado no próprio desenho): afins discretas com a escala declarada, decididas
    pela continuidade de um layer (o tubo) com a folha vizinha já georreferenciada (`continuidade` no obra.json)."""
    c = p["continuidade"]
    viz = feitas.get(c["vizinha"], {})
    if viz.get("M") is None:
        return {"M": None, "ok": False, "motivo": f"{motivo_malha}; vizinha {c['vizinha']} sem georreferência"}
    from shapely import Polygon
    jv = viz.get("clip") or viz.get("janela_pt")
    Mv = np.asarray(viz["M"])
    g_viz = georef_prancha.geometria_do_layer(pdf_cad.extrair(viz["pdf"], clip=viz.get("clip")), c["layer"], jv, Mv)
    janela_viz = Polygon(geo.aplicar(Mv, [[jv[0], jv[1]], [jv[2], jv[1]], [jv[2], jv[3]], [jv[0], jv[3]]]))
    r = georef_prancha.escolher_por_continuidade(georef_prancha.hipoteses_malha(tr, p["malha"], p["escala"]),
                                                 georef_prancha.geometria_do_layer(tr, c["layer"], p["clip"]), p["clip"],
                                                 g_viz, janela_viz)
    _log(f"  continuidade com {c['vizinha']}: {r['motivo']}")
    return {**r, "motivo": f"{r['motivo']} — a malha sozinha: {motivo_malha}"}


def referencia_cad(base: dict, pasta: Path, filtro: str, res: float = 0.10) -> Path:
    """Raster georreferenciado (preto sobre branco) das linhas de referência de uma prancha
    já georreferenciada — serve de "ortofoto" para registrar as pranchas irmãs."""
    import hashlib
    caminho = pasta / f"_ref_{base['id']}_{hashlib.md5(f'{filtro}|{res}'.encode(), usedforsecurity=False).hexdigest()[:6]}.png"
    if caminho.exists():
        return caminho
    tr = pdf_cad.extrair(base["pdf"], clip=base.get("clip"))
    M = np.asarray(base["M"])
    partes = [geo.aplicar(M, q) for t in tr if re.search(filtro, t["layer"], re.IGNORECASE) for q in t["partes"]]
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
    regras, tr = _regras(p) if p.get("regras") in REGRAS else None, pdf_cad.extrair(p["pdf"])
    pac = pdf_cad.pacote_vetorial(p["pdf"], regras, tracos=tr)          # simplificado: só para a tela
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
    m6 = np.asarray(M)[:2].ravel().tolist() if M is not None else None
    # medição na geometria exata: a simplificação antiga (cv2, distância à reta) encurtava 3,5–17 % por prancha
    quant = pdf_cad.quantitativos({**pdf_cad.pacote_vetorial(p["pdf"], regras, tolerancia_pt=0, tracos=tr),
                                   "M": m6, "clip_mapa": clip}) if M is not None else None
    return {"id": p["id"], "nome": p["nome"], "disciplina": p.get("disciplina", g), "grupo": g, "subgrupo": sg,
            "pdf": Path(p["pdf"]).name, **pac, "M": m6, "escala_m_pt": esc, "clip_mapa": clip,
            **({"quantitativos": quant} if quant is not None else {}),
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
def _qtd_da_planilha(v) -> tuple[float, str | None]:
    """Quantidade numérica; serial de data do Excel (≈ 2009–2036) vira alerta."""
    import pandas as pd
    if pd.isna(v):
        return 0.0, None
    v = float(v)
    if 40000 <= v <= 50000 and v == int(v):
        return 0.0, f"quantidade na planilha parece data do Excel ({int(v)})"
    return v, None


def _mesma_unidade(a, b) -> bool:
    sinonimos = {"pç": "un", "pc": "un", "peça": "un", "und": "un", "cj": "cj", "conj": "cj", "ml": "m"}
    a, b = str(a).strip().lower(), str(b).strip().lower()
    return sinonimos.get(a, a) == sinonimos.get(b, b)


def _item_do_escopo(r, unidades: dict, cat: dict) -> dict:
    """Linha da relação de materiais com quantidades por etapa, especificação do cadastro e alertas."""
    codigo = str(r.codigo).split(".")[0]
    q1, a1 = _qtd_da_planilha(r.qtd_etapa1)
    q2, a2 = _qtd_da_planilha(r.qtd_etapa2)
    alertas = [a for a in (a1, a2) if a]
    # tabela+item+código: o número do item repete entre blocos
    un_orc, q_orc = unidades.get((str(r.tabela), str(r.item), codigo), (None, None))
    if un_orc and not _mesma_unidade(r.unidade, un_orc):
        alertas.append(f"unidade diverge do orçamento ({r.unidade} × {un_orc} {q_orc})")
    espec = cat.get(codigo)
    if cat and not codigo.isdigit():
        alertas.append("item sem código de material Sanepar")
    elif cat and espec is None:
        alertas.append(f"código {codigo} fora do cadastro de materiais Sanepar")
    elif espec:
        if espec.get("unidade_medida") and not _mesma_unidade(r.unidade, espec["unidade_medida"]):
            alertas.append(f"unidade do cadastro Sanepar é {espec['unidade_medida']} (relação: {r.unidade})")
        if str(espec.get("situacao", "")).startswith("4"):          # 1/3 licitável, 6 para obra, 2 SCD: normais
            alertas.append(f"situação no cadastro: {espec['situacao']}")
    return {"tabela": r.tabela, "nome_tabela": r.nome_tabela, "item": r.item, "codigo": codigo,
            "descricao": r.descricao, "un": r.unidade, "q1": q1, "q2": q2,
            "alerta": "; ".join(alertas) or None,
            "etapa": r.etapa if isinstance(r.etapa, str) else "",
            "material": r.material_base if isinstance(r.material_base, str) else "",
            "local": r.local,
            "cadastro": {k: espec[k] for k in ("descricao", "unidade_medida", "norma_eb", "situacao", "familia",
                                               "material_base", "dn", "pn", "qtd_marcas", "marcas_homologadas")
                         if k in espec} if espec else None}


def _resumo_escopo(lin: list[dict]) -> tuple[dict, dict]:
    """Contagens por tabela e totais (itens, com quantidade na 1ª/2ª etapa, com alerta, no cadastro)."""
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
    return por_tabela, totais


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

    lin = [_item_do_escopo(r, unidades, cat) for r in rel.itertuples()]
    por_tabela, totais = _resumo_escopo(lin)
    return {"itens": lin, "por_tabela": por_tabela, "totais": totais, "desenhos_por_tabela": desenhos,
            "fonte": e.get("fonte", ""),
            "fonte_cadastro": "cadastro de materiais Sanepar (sanepar_mat, coletado em 08/2026), só especificação"
            if cat else None}


def tubo_contrato_x_desenho(escopo: dict, pranchas: list, cfg: dict) -> list[dict]:
    """Tubo principal de cada prancha: quantidade no contrato × eixo medido no desenho georreferenciado.

    A tabela do escopo aponta o desenho (`desenhos_por_tabela`); a prancha declara o layer do tubo (`layer_tubo` no
    obra.json). Tubo principal = código de família "tubo" em metros (cadastro Sanepar) com a maior quantidade
    (1ª + 2ª etapa) nas tabelas daquela prancha. A medida inclui o tubo desenhado além da linha de corte.
    Grava em cada item comparado `desenho` = {prancha, medido_m, diferenca_pct}.
    """
    import unicodedata

    def chave(nome):
        nome = re.sub(r"-R\d+(?=$|_)", "", re.sub(r"\.pdf$", "", str(nome), flags=re.IGNORECASE))
        return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower())

    layer_tubo = {q["id"]: q["layer_tubo"] for q in cfg.get("pranchas", []) if q.get("layer_tubo")}
    por_desenho = {chave(P["pdf"]): P for P in pranchas if P["id"] in layer_tubo and P.get("M") is not None}
    grupos = {}
    for it in escopo["itens"]:
        P = por_desenho.get(chave(escopo["desenhos_por_tabela"].get(it["tabela"], "")))
        c = it.get("cadastro") or {}
        if P and c.get("familia") == "tubo" and str(c.get("unidade_medida", "")).upper() == "M":
            grupos.setdefault(P["id"], {}).setdefault(it["codigo"], []).append(it)
    linhas = []
    for pid, por_codigo in grupos.items():
        P = next(q for q in pranchas if q["id"] == pid)
        medido = next((l.get("eixo_faixa_m") or l.get("comprimento_m") for l in P.get("quantitativos", [])
                       if l["layer"] == layer_tubo[pid]), None)
        codigo, itens = max(por_codigo.items(), key=lambda kv: sum(i["q1"] + i["q2"] for i in kv[1]))
        contrato = sum(i["q1"] + i["q2"] for i in itens)
        dif = round((medido / contrato - 1) * 100, 1) if medido and contrato else None
        for i in itens:
            i["desenho"] = {"prancha": pid, "medido_m": medido, "diferenca_pct": dif}
        linhas.append({"prancha": pid, "nome": P["nome"], "tabelas": sorted({i["tabela"] for i in itens}),
                       "codigo": codigo, "descricao": itens[0]["descricao"], "contrato_m": round(contrato, 2),
                       "desenho_m": medido, "diferenca_pct": dif})
    return sorted(linhas, key=lambda l: l["prancha"])


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
    pacote["referencia_z"] = ("altura sobre a decolagem (m)" if not vertical else
                              "cota (m), deslocamento ajustado aos pontos de controle" if vertical.get("modelo") == "offset"
                              else "cota (m), plano ajustado às sondagens")
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


def sondagens_3d(furos: list, origem) -> list[dict]:
    """Perfil de cada furo para o 3D, em cota (z = cota de boca − profundidade), relativo à origem do modelo.

    Só camadas com limite confirmado viram segmento próprio; o resto do furo vai num segmento "não confirmado"
    com as descrições, sem inventar fronteira entre camadas.
    """
    saida = []
    for s in furos:
        if s.get("E") is None or s.get("cota_boca") is None or not s.get("profundidade_m"):
            continue
        z0, prof, topo, seg = float(s["cota_boca"]), float(s["profundidade_m"]), 0.0, []
        for c in s.get("camadas", []):
            if c.get("de") is None or c.get("ate") is None:
                break
            seg.append({"z_topo": round(z0 - c["de"], 2), "z_base": round(z0 - c["ate"], 2), "classe": c.get("classe"),
                        "descricao": c.get("descricao"), "confirmado": True})
            topo = c["ate"]
        if topo < prof:
            resto = [c.get("descricao") for c in s.get("camadas", []) if c.get("de") is None or c.get("ate") is None]
            seg.append({"z_topo": round(z0 - topo, 2), "z_base": round(z0 - prof, 2), "classe": None,
                        "descricao": "; ".join(filter(None, resto)) or "sem descrição", "confirmado": False})
        saida.append({"id": s["id"], "x": round(s["E"] - origem[0], 2), "y": round(s["N"] - origem[1], 2),
                      "z_boca": z0, "z_fundo": round(z0 - prof, 2),
                      "z_na": round(z0 - s["na_m"], 2) if s.get("na_m") is not None else None,
                      "impenetravel": bool(s.get("impenetravel")), "segmentos": seg})
    return saida


def solidos_de_arquivos(cfg: dict, origem) -> list[dict]:
    """Sólidos do 3D lidos de JSON já georreferenciados (`solidos` no obra.json: lista de caminhos, cada um com
    `blocos: [{rotulo, contorno_utm, fundo, face_superior}]` e/ou `elementos: [{rotulo, contorno_utm, z0, z1}]` —
    paredes, pilares, lajes —, cotas em m, e `estrutura` opcional como prefixo do id),
    relativos à origem do modelo."""
    saida = []
    for caminho in cfg["solidos"]:
        d = json.loads(Path(caminho).read_text())
        prefixo = f"{d['estrutura']}-" if d.get("estrutura") else ""
        for b in d.get("blocos", []):
            saida.append({"id": prefixo + b["rotulo"], "xy": (np.array(b["contorno_utm"]) - origem[:2]).round(3).tolist(),
                          "z0": b["fundo"], "z1": b["face_superior"]})
        for e in d.get("elementos", []):
            saida.append({"id": prefixo + e["rotulo"], "xy": (np.array(e["contorno_utm"]) - origem[:2]).round(3).tolist(),
                          "z0": e["z0"], "z1": e["z1"]})
    return saida


def estacas(cfg: dict, epsg: int) -> dict | None:
    """Estacas (CSV id;E;N;diametro_cm;cota_arrasamento;comprimento_m;estrutura;...) -> vetor. A coluna opcional
    `execucao` (ex.: "escavada") dá o nome da camada; sem ela, hélice contínua (Foz)."""
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
    execucao = ", ".join(sorted(t["execucao"].dropna().unique())) if "execucao" in t else "hélice contínua"
    return {"id": "estacas", "nome": f"Estacas {execucao} ({len(feats)})", "grupo": "Civil",
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


def vetor_escavacao(esc: dict | None) -> dict | None:
    """Contorno das cavas calculadas (escavação e reaterro por cava) para o mapa."""
    if not esc:
        return None
    return {"id": "escavacao", "nome": f"Escavação calculada ({len(esc['cavas'])} cavas)", "grupo": "Intervenções",
            "subgrupo": "Movimento de terra", "visivel": False, "geojson": esc["geojson"],
            "estilo": {"color": "#92400e", "weight": 2, "fillOpacity": 0.3}}


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


def _pranchas_no_mapa(cfg: dict, pranchas: list, extensao: list, epsg: int) -> tuple[list, list, dict]:
    """Pacote vetorial de cada prancha (com quantitativos se georreferenciada), manchas de etapa e pendências."""
    lista, vetores, pendentes = [], [], {}
    for p in pranchas:
        lista.append(prancha_vetorial(p, extensao))           # com quantitativos (geometria exata) se georreferenciada
        if p.get("M") is None:
            pendentes.setdefault(p.get("disciplina", "Geral"), []).append(
                f"{p['nome']} — sem georreferência ({p.get('motivo', '')}); veja na aba Pranchas")
        elif p.get("manchas_etapa"):
            vetores += manchas_etapa(p, epsg)
    for disc, itens in cfg.get("pendentes", {}).items():
        pendentes.setdefault(disc, []).extend(itens)
    return lista, vetores, pendentes


def _ortofoto_html(out: Path, orto: dict, res_html: float, area=None) -> dict:
    """Ortofoto reduzida a `res_html` (m/px) com transparência fora da área voada e, com `area` (polígono UTM),
    fora da área da obra — recortada no retângulo dela: o satélite dá o entorno."""
    e0, _, _, n1 = orto["extensao_utm"]
    img = cv2.imread(str(out / "sfm" / "ortofoto.jpg"))
    k = orto["res_m_px"] / res_html
    small = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    alfa = cv2.resize((img.min(axis=2) < 250).astype(np.uint8) * 255, small.shape[1::-1], interpolation=cv2.INTER_NEAREST)
    if area is not None:
        dentro = np.zeros_like(alfa)
        for g in getattr(area, "geoms", [area]):
            c = np.asarray(g.exterior.coords)
            cv2.fillPoly(dentro, [np.c_[(c[:, 0] - e0) / res_html, (n1 - c[:, 1]) / res_html].round().astype(np.int32)], 255)
        alfa &= dentro
        x, y, w, h = cv2.boundingRect(dentro)
        small, alfa, e0, n1 = small[y:y + h, x:x + w], alfa[y:y + h, x:x + w], e0 + x * res_html, n1 - y * res_html
    return {"src": visualizador.data_url(np.dstack([small, alfa]), "webp", 80), "w": small.shape[1],
            "h": small.shape[0], "m": [res_html, 0, e0, 0, -res_html, n1]}


def area_da_obra(cfg: dict, vetores: list, extensao_voo, crs: dict):
    """Área da obra (polígono UTM) dentro do voo: envoltória convexa das intervenções calculadas (`area_obra.fontes`:
    regex de id de vetor — cavas, valas, supressão, blocos, manchas de etapa) + `margem_m`. Fora dela, a ortofoto do
    drone não entra no HTML (o satélite mostra o entorno). None sem `area_obra` no obra.json ou sem intervenção."""
    import shapely
    from shapely.geometry import MultiPoint, box
    c = cfg.get("area_obra")
    if not c:
        return None
    A = np.asarray(crs["ll2utm"]).reshape(2, 3)                 # lon/lat → UTM (afim da área, erro sub-mm)
    voo = box(*extensao_voo)
    pts = [shapely.get_coordinates(shapely.from_geojson(json.dumps(f["geometry"]))) @ A[:, :2].T + A[:, 2]
           for v in vetores if any(re.match(r, v["id"]) for r in c["fontes"]) for f in v["geojson"]["features"]]
    pts = np.vstack(pts) if pts else np.zeros((0, 2))
    pts = pts[shapely.contains_xy(voo, pts[:, 0], pts[:, 1])]
    if len(pts) < 3:
        return None
    return MultiPoint(pts).convex_hull.buffer(c.get("margem_m", 10.0)).intersection(voo)


def _vetor_area(area, epsg: int) -> dict:
    """Contorno da área da obra no mapa (desligado: referência do recorte da ortofoto)."""
    lon, lat = geo.para_lonlat(*np.asarray(area.exterior.coords).T, epsg)
    return {"id": "area_obra", "nome": "Área da obra (recorte da ortofoto)", "grupo": "Levantamento", "subgrupo": "Drone",
            "visivel": False, "estilo": {"color": "#f97316", "weight": 2, "fillOpacity": 0},
            "geojson": {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {
                "tipo": "Área da obra", "area_m2": round(area.area)},
                "geometry": {"type": "Polygon", "coordinates": [np.c_[lon, lat].round(7).tolist()]}}]}}


def _resumo_area(area, extensao_voo, cfg: dict) -> dict | None:
    if area is None:
        return None
    e0, n0, e1, n1 = extensao_voo
    c = cfg["area_obra"]
    return {"area_m2": round(area.area), "fracao_do_voo": round(area.area / ((e1 - e0) * (n1 - n0)), 3),
            "margem_m": c.get("margem_m", 10.0), "fontes": c["fontes"], "fonte": c.get("fonte", ""),
            "utm": np.asarray(area.exterior.coords).round(2).tolist()}


def limites_da_obra(lista: list, extensao_voo, epsg: int, margem_m: float = 200.0) -> list:
    """[[lat_s, lon_o], [lat_n, lon_l]] do voo e da área desenhada de cada prancha georreferenciada (adutoras
    incluídas) + margem: o satélite só pede tiles aí dentro."""
    e0, n0, e1, n1 = extensao_voo
    cantos = [np.array([[e0, n0], [e1, n1]])]
    for p in lista:
        if p["M"] is not None:
            x0, y0, x1, y1 = p.get("clip_mapa") or [0, 0, p["largura"], p["altura"]]
            M = np.vstack([np.asarray(p["M"]).reshape(2, 3), [0, 0, 1]])
            cantos.append(geo.aplicar(M, np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float)))
    c = np.vstack(cantos)
    lon, lat = geo.para_lonlat(c[:, 0].min() - margem_m, c[:, 1].min() - margem_m, epsg)
    lon1, lat1 = geo.para_lonlat(c[:, 0].max() + margem_m, c[:, 1].max() + margem_m, epsg)
    return [[round(lat, 6), round(lon, 6)], [round(lat1, 6), round(lon1, 6)]]


def _furos_x_nuvem(furos: list, vertical: dict | None) -> list:
    """Boca de cada furo × terreno da nuvem já em cota (usado, descartado ou sem nuvem)."""
    if not vertical:
        return furos
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
    return furos


def _terreno_dos_furos(furos: list) -> list[dict]:
    """[{id, terreno_m}] dos furos com o terreno da nuvem já em cota (`controle_vertical` de `_furos_x_nuvem`)."""
    return [{"id": f["id"], "terreno_m": f["controle_vertical"]["terreno_m"]} for f in furos
            if (f.get("controle_vertical") or {}).get("terreno_m") is not None]


def _estacas_do_csv(cfg: dict) -> list[dict]:
    """Linhas do CSV de estacas, inclusive as sem E/N (a conferência acusa `sem_coordenada`)."""
    caminho = cfg.get("estacas")
    if not caminho or not Path(caminho).exists():
        return []
    import pandas as pd
    t = pd.read_csv(caminho, sep=";", decimal=",", dtype={"id": str})
    return t.astype(object).where(t.notna(), None).to_dict("records")


def _cavas_para_conferir(esc: dict | None, epsg: int) -> list[dict]:
    """Cavas da escavação como [{id, E_m, N_m, cota_fundo_m}]: centro do contorno (lon/lat -> UTM) e o fundo mais baixo."""
    from shapely.geometry import shape
    cavas = []
    for f in ((esc or {}).get("geojson") or {}).get("features", []):
        p = f["properties"]
        if not p.get("fundo_m"):
            continue
        centro = shape(f["geometry"]).representative_point()
        e, n = geo.para_utm(centro.x, centro.y, epsg)
        cavas.append({"id": p["id"], "E_m": float(e), "N_m": float(n), "cota_fundo_m": float(min(p["fundo_m"]))})
    return cavas


def _conferencias_geotecnia(furos: list, estacas_csv: list, cavas: list, terreno: list,
                            trechos: list | None = None) -> dict | None:
    """Conferências projeto × sondagem (`geotecnia.conferir`) no formato de `dados["geotecnia"]`:
    {"conferencias": [...], "resumo": {tipo: n}}. Sem sondagens, None."""
    if not furos:
        return None
    ocorrencias = geotecnia.conferir(furos, estacas_csv, cavas, trechos=trechos, terreno=terreno)
    resumo: dict[str, int] = {}
    for o in ocorrencias:
        resumo[o["tipo"]] = resumo.get(o["tipo"], 0) + 1
    return {"conferencias": ocorrencias, "resumo": resumo}


def _info(cfg: dict, crs: dict, rel: dict, desloc, orto: dict, vertical: dict | None, lista: list) -> list:
    """Painel de informações: sistema, levantamento, posição, ortofoto, nuvem, cotas e georreferência das pranchas."""
    from . import VERSAO
    epsg, n_obl, res_html = crs["epsg"], sum(c["tipo"] == "obliqua" for c in rel["cameras"]), cfg.get("res_html", 0.06)
    return [
        ["Versão", f"projetos_em_camadas {VERSAO} · gerado em {time.strftime('%d/%m/%Y')}"],
        ["Sistema", f"{crs['nome']} (EPSG:{epsg})"],
        ["Levantamento", (f"{len(rel['cameras'])} fotos ({n_obl} oblíquas), SfM com reprojeção "
                          f"{rel['reprojecao_px']:.2f} px")],
        ["Posição absoluta", f"GPS do drone (RMSE {rel['rmse_gps_m']:.1f} m)" + (
            f"; corrigida {-desloc[0]:+.2f} m E / {-desloc[1]:+.2f} m N pelo controle "
            f"topográfico ({cfg['controle_absoluto'].get('fonte', '')})" if np.any(desloc) else
            " — sem pontos de controle em campo")],
        ["Ortofoto", (f"verdadeira (MDS da nuvem), {orto['res_m_px'] * 100:.0f} cm/px; embutida a "
                      f"{res_html * 100:.0f} cm/px")],
        ["Nuvem 3D", f"{rel['n_pontos']:,} pontos".replace(",", ".") + (
            " (Z em cota)" if vertical else " (Z = altura sobre a decolagem)")],
        *([["Cotas", (f"plano ajustado a {vertical['usados']} furos SPT ({vertical['fonte']}); validação cruzada "
                      f"{vertical['rms_validacao_cruzada_m']:.2f} m; descartados (copa/edificação) "
                      f"{', '.join(vertical['descartados']) or '—'}")]] if vertical else []),
        *[[f"Prancha {f['id']}", (f"{f['georef']['motivo']}; resíduo "
                                  f"{(f['georef']['residuo_mediano_m'] or 0) * 100:.0f} cm")]
          for f in lista if f["M"] is not None],
    ]


def _reavaliar(inv: dict, out: Path, cfg: dict, geotecnia_dados: dict | None = None) -> dict:
    """Reavaliação do inventário (`camadas.extracao`): classe de cada fonte, estado da extração, próximo passe e séries
    de folhas incompletas; grava `pendencias.json` (a lista que abre a próxima rodada, com a chave `geotecnia` das
    conferências projeto × sondagem) e o registro `extracao.jsonl`."""
    rel = extracao.aplicar_retornos(out, inv)                      # retornos da IA entram antes da avaliação
    p = extracao.pendencias(inv, cfg["inventario"].get("pastas"), extracao.ler_complementos(out / "complementos.json"))
    extracao.registrar_por_executor(p["avaliacoes"], out / "extracao.jsonl", passe="build")
    resumo = {k: p[k] for k in ("por_estado", "por_classe", "fracao_completa", "series", "fora_do_escopo")}
    resumo.update({k: p[k] for k in ("por_papel",) if k in p})
    (out / "pendencias.json").write_text(json.dumps({**resumo, "esperado": extracao.esperado_x_encontrado({"itens": p["itens"]}),
                                                     "retornos": rel, "pendencias": p["pendencias"],
                                                     "geotecnia": geotecnia_dados},
                                                    ensure_ascii=False, indent=1), encoding="utf-8")
    _log(f"Extração: {p['por_estado']}; {len(p['pendencias'])} pendência(s), {len(p['series'])} série(s) incompleta(s)")
    return {**resumo, "pendencias": p["pendencias"]}


def _conciliar_eaps(dados: dict, servicos: list | None, out: Path) -> None:
    """Confronta as quantidades das gavetas com as da EAP codificada e com os documentos independentes dos fatos
    (`dados["evidencias"]`, por isso depois do loop de evidências) com `gavetas.conciliar_eap`, grava
    `conciliacao_eap.json` e põe o resumo formatado em `dados["eap_gavetas"]["conciliacao"]`. Nunca derruba o build."""
    if not (servicos and dados.get("eap_gavetas") and dados.get("eap")):
        return
    try:
        origens = eap.origem_das_quantidades(dados["eap"]["quantidades"], dados.get("construtivos"))
        fatos = (dados.get("evidencias") or {}).get("fatos")
        linhas = gavetas.conciliar_eap(servicos, dados["eap"]["quantidades"], origens_codificada=origens, fatos=fatos)
        totais = gavetas.conciliar_totais(linhas, fatos)       # fato `U1.*.ITEM` × soma das linhas (bloco à parte)
        (out / "conciliacao_eap_totais.json").write_text(json.dumps(totais, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "conciliacao_eap.json").write_text(json.dumps(linhas, ensure_ascii=False, indent=1), encoding="utf-8")
        dados["eap_gavetas"]["conciliacao"] = eap_html.conciliacao(linhas, totais)
    except Exception as erro:  # noqa: BLE001 - a conciliação nunca derruba o build
        _log(f"Conciliação das EAP não concluída ({type(erro).__name__}: {erro})")


def _eap_padrao_no_build(dados: dict, cfg: dict, out: Path) -> None:
    """EAP padrão por tipo de obra (`camadas.eap_padrao`) em `dados["eap_padrao"]` e `eap_padrao.json`. Nunca derruba o
    build: padrão ou declaração inválida vira etapa pulada, com o motivo nas pendências do HTML."""
    try:
        dados["eap_padrao"] = eap_padrao.montar(dados, cfg, out)
    except Exception as erro:  # noqa: BLE001 - a EAP padrão nunca derruba o build
        _log(f"EAP padrão pulada (pendência: {type(erro).__name__}: {erro})")


def _contrato_211(cfg: dict, out: Path, redes_vala: list | None, vala: dict | None,
                  servicos: list | None = None) -> dict | None:
    """Quantidades do CUSTO CIVIL da planilha 211 (`camadas.contrato_211`), sem preço, para `dados["contrato_211"]`.
    A vala vem dos `servicos` das gavetas (`base["servicos"]`, objetos `RV-<id>`), nunca recalculada aqui.
    Sem a chave `obras_lineares.planilha` nada muda (obra sem contrato Sanepar); com a chave e sem o arquivo, ou com
    qualquer falha, vira pendência, e o contrato nunca derruba o build."""
    planilha = cfg.get("obras_lineares", {}).get("planilha")
    if not planilha:
        return None
    if not Path(planilha).is_file():
        _log("Contrato 211: planilha ausente (pendência)")
        return None
    try:
        linhas = contrato_211.classificar(contrato_211.ler_custo_civil(planilha))
        furos = escavacao._furos_da_obra(cfg)
        ortofoto, mds = out / "sfm" / "ortofoto.jpg", out / "sfm" / "ortofoto_mds.png"
        sup = None
        if cfg.get("supressao") and ortofoto.is_file() and mds.is_file():
            sup = contrato_211.supressao_por_uc(redes_vala, ortofoto, mds, cfg["supressao"]["faixa_m"],
                                                cfg["supressao"]["folga_unidades_m"], linhas)
        urb = (vala or {}).get("urbanizacao_m2")
        resultados = contrato_211.quantificar(linhas, contrato_211.contexto_do_build(redes_vala, furos, sup, urb, servicos))
        resumo = contrato_211.resumo_quantidades(resultados)
        _log(f"Contrato 211: {resumo['linhas']} linha(s); " + ", ".join(
            f"{situacao} {n}" for situacao, n in resumo["por_situacao"].items() if n))
        premissas = [f"{nome}: {p['descricao']} = {str(p['valor']).replace('.', ',')} {p['unidade']} ({p['estado']})"
                     for nome, p in contrato_211.DE_PARA["premissas"].items()]
        pct = f"{resumo['pct_vazias_calculadas']:.1f}".replace(".", ",") + " %"
        resumo_txt = [["Linhas", str(resumo["linhas"])],
                      *[[f"situação: {k}", str(n)] for k, n in resumo["por_situacao"].items()],
                      ["Linhas sem declarada", str(resumo["vazias"])],
                      ["Sem declarada, calculadas", str(resumo["vazias_calculadas"])],
                      ["Sem declarada, calculadas (%)", pct]]           # já em texto: o HTML só apresenta
        return {"resumo": resumo, "resumo_txt": resumo_txt, "linhas": contrato_211.para_html(resultados),
                "premissas": premissas,
                "fonte": "aba CUSTO CIVIL da planilha 211 (colunas A–E e I; sem preço)"}
    except Exception as erro:  # noqa: BLE001 - o contrato nunca derruba o build
        _log(f"Contrato 211: não concluído (pendência; {type(erro).__name__}: {erro})")
        return None


def _contrato_no_build(dados: dict, cfg: dict, out: Path, redes_vala: list | None, vala: dict | None) -> None:
    """`dados["contrato_211"]` com os serviços da base gravada em `out/base` (depois do `completar_escopo`, para a vala
    sair só das gavetas); sem base, o contrato não recalcula a vala e as linhas ficam "a preencher"."""
    servicos = None
    try:
        servicos = gavetas.ler(out / "base")["servicos"] if (out / "base").exists() else None
    except Exception as erro:  # noqa: BLE001 - base ilegível vira pendência, nunca derruba o build
        _log(f"Contrato 211: base das gavetas ilegível (pendência; {type(erro).__name__}: {erro})")
    contrato = _contrato_211(cfg, out, redes_vala, vala, servicos)
    if contrato is not None:
        dados["contrato_211"] = contrato


def _aba_projeto(dados: dict, cfg: dict, out: Path, escopo: dict | None, fichas: list | None, pacotes: dict,
                 redes_vala: list | None = None, cavas: dict | None = None) -> None:
    """Aba Projeto: fichas dos pilotos (e blocos no 3D), escavação, valas, obras lineares e inventário com a ficha em
    lote; os elementos construtivos da aba Obra (`camadas.construtivos`), que juntam tudo o que já é vetor; a EAP
    (`camadas.eap`), que dá código e quantidade a cada elemento; e o loop de evidências (`camadas.evidencias`)."""
    if cavas and cavas.get("conferencia"):                      # conferência das cavas × seções de corte (aba EAP)
        dados["conferencia_cavas"] = cavas["conferencia"]
    pacotes["obras_lineares"] = obras_lineares.etapa(cfg, dados["sondagens"], out, log=_log)   # vala (MOS) da planilha
    servicos_gavetas = None
    try:                                                       # a base das gavetas não pode derrubar o build
        dados["gavetas"] = extrair_gavetas.etapa(cfg, dados["sondagens"], out, log=_log, redes_vala=redes_vala,
                                                cavas=cavas, epsg=(dados.get("crs") or {}).get("epsg"))
        if dados["gavetas"]:                                    # aba EAP das gavetas: só apresenta o que o Python montou
            dados["eap_gavetas"] = dados["gavetas"].pop("eap_html")   # chave própria: `dados["eap"]` é a EAP codificada
            servicos_gavetas = dados["gavetas"].pop("servicos_eap", None)   # com o código completo, para a conciliação
    except Exception as erro:  # noqa: BLE001 - a etapa nova nunca derruba o build
        _log(f"Gavetas: etapa não concluída ({type(erro).__name__}: {erro})")
    if fichas:
        dados["fichas"] = prancha.para_html(fichas)
        if dados.get("vertical"):
            dados["modelo3d"]["solidos"] = prancha.solidos_3d(fichas, np.asarray(dados["modelo3d"]["origem"]))
    if cfg.get("solidos") and dados.get("vertical"):
        dados["modelo3d"].setdefault("solidos", []).extend(solidos_de_arquivos(cfg, np.asarray(dados["modelo3d"]["origem"])))
    for chave, pacote in pacotes.items():
        if pacote:
            dados[chave] = {k: v for k, v in pacote.items() if k != "geojson"}
    if cfg.get("inventario") and inventario.disponivel(cfg, log=_log):   # a listagem do Drive, com o carimbo
        inv = inventario.inventario(cfg, out / "inventario_cache.json", log=_log)
        dados["inventario"] = inventario.para_html(inv)
        dados["inventario"]["extracao"] = _reavaliar(inv, out, cfg, dados.get("geotecnia"))
        fl = prancha.lote(cfg, escopo, out, log=_log)                  # ficha leve de cada desenho no disco
        for it in dados["inventario"]["itens"]:
            it["ficha"] = prancha.resumo_lote(fl.get(f"{it['pasta_drive']}/{it['arquivo']}"))
    dados["construtivos"] = construtivos.montar(dados, cfg)        # aba Obra: unidade > sistema > elemento
    if dados["construtivos"]:                                       # escopo por unidade, decomposição e evidências
        dados["construtivos"]["escopo"] = escopo_obra.montar(dados, cfg)
    # `dados["eap_gavetas"]` = árvore das gavetas; `dados["eap"]` = EAP codificada (contrato da 0.34.0, cada um na sua chave)
    dados["eap"] = eap.montar(dados, cfg)          # elemento → item (código) → quantidade com evidência
    dados["evidencias"] = evidencias.etapa(cfg, out, dados, log=_log)   # loop nos documentos: fatos e conflitos
    try:                                           # F2–F4: escopo nas gavetas, complementares e a EAP única
        extrair_gavetas.completar_escopo(cfg, out, dados, log=_log)
    except Exception as erro:  # noqa: BLE001 - nunca derruba o build
        _log(f"Gavetas (escopo): não concluído (pendência; {type(erro).__name__}: {erro})")
    _contrato_no_build(dados, cfg, out, redes_vala, pacotes.get("valas"))   # depois das gavetas: a vala vem dos serviços
    _conciliar_eaps(dados, servicos_gavetas, out)  # gavetas × codificada × documento: `conciliacao_eap.json` e o resumo
    dados["eap_painel"] = eap_painel.montar(dados.get("eap"), dados.get("evidencias"))   # aba EAP, já em texto
    _eap_padrao_no_build(dados, cfg, out)          # esqueleto por etapa de execução, a preencher
    try:
        vista = eap_vista.montar(dados)                # aba EAP legível: seções, WBS × contrato, filtros e busca
        if vista is not None:
            dados["eap_vista"] = vista
    except Exception as erro:  # noqa: BLE001 - a vista da EAP nunca derruba o build
        _log(f"Vista da EAP: não concluída (pendência; {type(erro).__name__}: {erro})")


# 5 ---------------------------------------------------------------------------
def _sondagens_no_build(dados: dict, cfg: dict, furos: list, esc: dict | None, epsg: int, vertical) -> None:
    """Conferências projeto × sondagem em `dados["geotecnia"]` e o perfil dos furos no 3D (só com a nuvem em cota)."""
    dados["geotecnia"] = _conferencias_geotecnia(furos, _estacas_do_csv(cfg), _cavas_para_conferir(esc, epsg),
                                                 _terreno_dos_furos(furos))
    if vertical:
        dados["modelo3d"]["sondagens"] = sondagens_3d(furos, dados["modelo3d"]["origem"])


def _escavacao_e_conferencia(cfg: dict, pranchas: list, out: Path, vertical: dict | None, cavas_gavetas: dict):
    """Escavação e reaterro (`escavacao.etapa`) e, logo depois, a conferência das cavas contra as seções de corte do
    projeto (`camadas.conferencia_cavas`), que fica em `cavas_gavetas["conferencia"]`; a conferência nunca derruba o build."""
    esc = escavacao.etapa(cfg, pranchas, out, vertical, log=_log, saida_gavetas=cavas_gavetas)
    try:
        cavas_gavetas["conferencia"] = conferencia_cavas.etapa(cfg, pranchas, out, cavas_gavetas, log=_log)
    except Exception as erro:  # noqa: BLE001 - falha da conferência vira pendência, não erro do build
        _log(f"Conferência das cavas: não concluída (pendência; {type(erro).__name__}: {erro})")
    return esc


def _vetores_do_build(cfg: dict, out: Path, rel: dict, epsg: int, pranchas: list, esc, fichas, vala, extensao_utm) -> list:
    """Vetores do build além dos das pranchas: câmeras, estacas, supressão, escavação, marcos, blocos, peças e valas."""
    e0, n0, e1, n1 = extensao_utm
    return [v for v in (
        {"id": "cameras", "nome": "Fotos do drone (posição e visada)", "grupo": "Levantamento", "subgrupo": "Drone",
         "visivel": False, "geojson": vetores_cameras(rel, epsg), "fotos": True, "estilo": {"color": "#f5c518", "weight": 2}},
        estacas(cfg, epsg), vetor_supressao(cfg, out, pranchas), vetor_escavacao(esc),
        vetor_marcos(cfg, epsg, ((e0 + e1) / 2, (n0 + n1) / 2)),
        *((prancha.vetor_blocos(fichas, epsg), prancha.vetor_pecas(fichas, epsg)) if fichas else ()),
        vala and {"id": "valas", "nome": "Valas: pista, calçada e lote (calculado)", "grupo": "Intervenções",
                  "subgrupo": "Demolição e recomposição", "visivel": False, "geojson": vala["geojson"],
                  "estilo": {"color": "#dc2626", "weight": 4, "opacity": 0.9}}) if v]


def construir(cfg_path: str | Path, refazer: set[str] = frozenset()) -> Path:
    cfg = json.loads(Path(cfg_path).read_text())
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
    lista, vetores, pendentes = _pranchas_no_mapa(cfg, pranchas, orto["extensao_utm"], epsg)
    crs = visualizador.crs_info(epsg, [e0, n0, e1, n1], rel["alt_decolagem_m"])
    cavas_gavetas: dict = {}                          # o que a escavação entrega às gavetas (cavas)
    esc = _escavacao_e_conferencia(cfg, pranchas, out, vertical, cavas_gavetas)   # escavação, reaterro e conferência
    escopo = etapa_escopo(cfg)
    if escopo:
        escopo["tubo_x_desenho"] = tubo_contrato_x_desenho(escopo, lista, cfg)
    fichas = prancha.etapa(cfg, pranchas, escopo, out, log=_log)           # prancha lida em camadas (pilotos)
    redes_vala: list = []
    vala = valas.etapa(cfg, pranchas, lista, escopo, out, epsg, log=_log, redes_saida=redes_vala)   # pista × calçada × lote
    vetores += _vetores_do_build(cfg, out, rel, epsg, pranchas, esc, fichas, vala, orto["extensao_utm"])
    area = area_da_obra(cfg, vetores, orto["extensao_utm"], crs)
    vetores += [_vetor_area(area, epsg)] if area is not None else []
    furos = _furos_x_nuvem(sondagens(cfg, epsg), vertical)
    n_obl = sum(c["tipo"] == "obliqua" for c in rel["cameras"])
    dados = {
        "id": cfg["id"], "titulo": cfg["titulo"], "titulo_curto": cfg.get("titulo_curto", cfg["titulo"]),
        "subtitulo": cfg.get("subtitulo", ""), "crs": crs, "satelite": True,
        "limites_obra": limites_da_obra(lista, orto["extensao_utm"], epsg, cfg.get("area_obra", {}).get("margem_satelite_m", 200.0)),
        "area_obra": _resumo_area(area, orto["extensao_utm"], cfg),
        "bases": [{"id": "orto", "nome": f"Ortofoto drone ({len(rel['cameras']) - n_obl} fotos nadirais)",
                   "grupo": "Levantamento", **_ortofoto_html(out, orto, cfg.get("res_html", 0.06), area), "visivel": True}],
        "folhas": [], "pranchas": lista, "vetores": vetores, "pendentes": pendentes,
        "etapas": cfg.get("etapas", []),
        "grupos": pdf_cad.disciplinas()["grupos"],
        "intervencoes": json.loads((pdf_cad.CONCEITOS / "intervencoes.json").read_text(encoding="utf-8"))["intervencoes"],
        "elementos": {c["id"]: {"nome": c["nome"], "grupo": c["grupo"]} for c in pdf_cad.elementos()["classes"]},
        "escopo": escopo,
        "sondagens": furos,
        "modelo3d": modelo3d(out, rel, cfg.get("max_pontos_3d", 300_000), desloc, vertical),
        "vertical": vertical,
        "fotos": fotos_obliquas(cfg, rel),
        "anotacoes": {"type": "FeatureCollection", "features": []},
        "info": _info(cfg, crs, rel, desloc, orto, vertical, lista),
    }
    _sondagens_no_build(dados, cfg, furos, esc, epsg, vertical)
    _aba_projeto(dados, cfg, out, escopo, fichas, {"escavacao": esc, "valas": vala}, redes_vala, cavas_gavetas)
    return _gravar(cfg, out, dados, pranchas, epsg)


def nome_html(cfg: dict, data: str | None = None) -> str:
    """Nome do HTML: obra, versão do código e data do build (`nome_html` no obra.json muda o padrão; campos {id},
    {versao}, {data}). Ex.: foz-vilac_camadas_v0.14.0_2026-10-29.html — cada versão fica num arquivo próprio."""
    from . import VERSAO
    padrao = cfg.get("nome_html", "{id}_camadas_v{versao}_{data}")
    return padrao.format(id=cfg["id"], versao=VERSAO, data=data or time.strftime("%Y-%m-%d")) + ".html"


def _gravar(cfg: dict, out: Path, dados: dict, pranchas: list, epsg: int) -> Path:
    """dados.json, pacote SIG e o HTML (offline; e o do Artifact, com bibliotecas do CDN, se pedido)."""
    _avisos_nas_pendencias(dados, AVISOS_DO_BUILD)    # as etapas puladas deste build; a lista é consumida
    AVISOS_DO_BUILD.clear()
    (out / "dados.json").write_text(json.dumps(dados, ensure_ascii=False, separators=(",", ":")))
    if cfg.get("sig", True):
        etapa_sig(out, dados, pranchas, epsg)
    html = visualizador.gerar(dados, out / nome_html(cfg), "inline")
    _log(f"Visualizador: {html} ({html.stat().st_size / 1e6:.1f} MB)")
    if cfg.get("artifact"):
        visualizador.gerar(dados, out / (html.stem + "_artifact.html"), "cdn", documento=False)
    return html


def etapa_sig(out: Path, dados: dict, pranchas: list, epsg: int) -> None:
    """GeoTIFF (ortofoto, MDS e, havendo `area_obra`, os dois recortados), GeoPackage com todas as camadas e .points do QGIS."""
    from . import sig
    pasta = out / "sig"
    sig.geotiff(out / "sfm" / "ortofoto.jpg", pasta / "ortofoto.tif")
    vertical = dados.get("vertical")
    sig.geotiff(out / "sfm" / "ortofoto_mds.png", pasta / "mds.tif", mds=True, correcao_z=(
        lambda E, N: sfm.aplicar_vertical(np.c_[E.ravel(), N.ravel(), np.zeros(E.size)], vertical)[:, 2].reshape(E.shape))
        if vertical else None)
    area = dados.get("area_obra")
    if area:                                          # versões recortadas na área da obra (as inteiras ficam)
        sig.recortar(pasta / "ortofoto.tif", area["utm"], pasta / "ortofoto_obra.tif")
        sig.recortar(pasta / "mds.tif", area["utm"], pasta / "mds_obra.tif")
    for p, pv in zip(pranchas, dados["pranchas"]):
        if p.get("M") is not None:
            sig.pontos_qgis(np.asarray(p["M"]), pv["clip_mapa"], pasta / "pontos" / f"{p['id']}.points", epsg)
    sig.geopackage(dados, pasta / "obra.gpkg", epsg)
    recortes = ", ortofoto_obra.tif, mds_obra.tif" if area else ""
    _log(f"SIG: {pasta}/ (ortofoto.tif, mds.tif{recortes}, obra.gpkg, pontos/*.points)")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Constrói a obra (ortofoto, 3D, pranchas, escopo, HTML)")
    ap.add_argument("config", help="obra.json")
    ap.add_argument("--refazer", default="", help="etapas a refazer: sfm,pranchas")
    a = ap.parse_args(argv)
    construir(a.config, set(filter(None, a.refazer.split(","))))


if __name__ == "__main__":
    main()
