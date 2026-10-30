"""Elementos construtivos: o que o usuário procura pelo nome (pilar P5, bloco PC12, estaca ACT600-031, AAT06 · folha 09).

    unidade  = obra localizada (u1, ETA) ou linear (u2, adutoras)
    sistema  = módulo da ETA (filtros, Actiflo...) ou rede; estaca pela `estrutura`, bloco e pilar pela ficha da forma,
               cava pela maioria das estacas dentro, mancha de etapa no sistema geral
    trecho   = uma folha da rede: o tubo das valas dentro da janela da planta; a extensão da rede (quadro das valas) é
               repartida pela posição do tubo, então é estimada. O contrato × desenho vem de `escopo.tubo_x_desenho`

Só lê `dados` (o que `obra.construir` já calculou): nenhum PDF, nenhuma conta nova de quantidade. Regras e nomes em
`conceitos/unidades_construtivas.json`. O que não se sabe fica de fora ou com o código como nome e estado premissa.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import shapely
import shapely.affinity
from shapely.geometry import Polygon, mapping, shape

from . import geo
from .pdf_cad import CONCEITOS

REGRAS = json.loads((CONCEITOS / "unidades_construtivas.json").read_text(encoding="utf-8"))


def _sistema(codigo: str) -> dict:
    """Sistema declarado; código desconhecido (estrutura nova no CSV) vira sistema da u1 com o código como nome."""
    return REGRAS["sistemas"].get(codigo) or {"unidade": "u1", "nome": codigo, "estado": "premissa"}


def _doc_id(arquivo: str | None) -> str | None:
    """Id do documento de origem = nome do PDF sem extensão (o mesmo id que `escopo_obra` usa nos links);
    'A+B' (estaca vista em dois desenhos) fica com o primeiro."""
    return Path(arquivo.split("+")[0]).stem if arquivo else None


def _adicionar(ctx: dict, codigo: str, classe: str, rotulo: str, geometria: dict, atributos: list, fonte: str,
               etapa: str | None = None, chave: str | None = None, doc: str | None = None) -> None:
    """Acrescenta uma feature no contrato; id = sistema-classe-chave, com sufixo se repetir. Valor nulo não entra.
    `doc` = id do documento (prancha, forma) de onde o elemento veio."""
    unidade = _sistema(codigo)["unidade"]
    nome = re.sub(r"\s+", "_", chave or rotulo)
    base = f"{unidade}-{codigo}-{classe}-{nome}"
    ident, n = base, 1
    while ident in ctx["usados"]:
        n += 1
        ident = f"{base}-{n}"
    ctx["usados"].add(ident)
    ctx["contagem"][(codigo, classe)] += 1
    ctx["features"].append({"type": "Feature", "geometry": geometria,
                            "properties": {"id": ident, "rotulo": rotulo, "classe": classe, "unidade": unidade,
                                           "sistema": f"{unidade}-{codigo}", "etapa": etapa,
                                           "atributos": [[k, v] for k, v in atributos if v is not None],
                                           "fonte": fonte, "doc": doc}})


def _por_sistema(indices: list, estacas: list) -> str:
    """'FILTROS 96 · ACT600 83': estacas por estrutura, da maior para a menor."""
    cont = Counter(estacas[i]["properties"]["estrutura"] for i in indices)
    return " · ".join(f"{k} {n}" for k, n in cont.most_common())


def _arquivo_ficha(dados: dict, ficha: str) -> str | None:
    """PDF de onde a ficha leu os blocos e pilares."""
    return next((f["identidade"]["arquivo"] for f in dados.get("fichas") or [] if f["id"] == ficha), None)


def _fonte_ficha(dados: dict, ficha: str) -> str:
    """Desenho de onde a ficha leu os blocos e pilares."""
    arq = _arquivo_ficha(dados, ficha)
    return f"forma {arq.removesuffix('.pdf')} (camadas.prancha)" if arq else f"ficha {ficha} (camadas.prancha)"


def _estacas(ctx: dict, estacas: list, bloco_da_estaca: dict) -> None:
    for i, f in enumerate(estacas):
        p = f["properties"]
        _adicionar(ctx, p["estrutura"], "estaca", p["id"], f["geometry"],
                   [["Diâmetro nominal (cm)", p.get("diametro_cm")], ["Comprimento (m)", p.get("comprimento_m")],
                    ["Cota de arrasamento (m)", p.get("cota_arrasamento")], ["E (m)", float(p["E"])],
                    ["N (m)", float(p["N"])], ["Bloco", bloco_da_estaca.get(i)]],
                   f"fundação {p['desenho_origem']} (estacas.csv)", doc=_doc_id(p["desenho_origem"]))


def _blocos_e_pilares(ctx: dict, dados: dict, formas: list, estacas: list, dentro: list) -> dict:
    """Bloco e pilar da forma, no sistema da ficha. Devolve {índice da estaca: rótulo do bloco}."""
    blocos = [(f, d) for f, d in zip(formas, dentro) if f["properties"]["tipo"] == "Bloco (forma)"]
    pilares = {f["properties"]["bloco"] for f in formas if f["properties"]["tipo"] == "Pilar (forma)"}
    resumo, bloco_da_estaca = {}, {}
    for f, idx in blocos:
        p = f["properties"]
        codigo = REGRAS["fichas"].get(p["ficha"], {}).get("sistema", REGRAS["sistema_geral"])
        resumo[p["rotulo"]] = _por_sistema(idx, estacas)
        outras = {estacas[i]["properties"]["estrutura"] for i in idx} - {codigo}
        for i in idx:
            bloco_da_estaca[i] = p["rotulo"]
        _adicionar(ctx, codigo, "bloco", p["rotulo"], f["geometry"],
                   [["Estacas", p.get("estacas")], ["Estacas por sistema", resumo[p["rotulo"]] or None],
                    ["Face superior (cota, m)", p.get("face_superior_m")], ["Arrasamento (cota, m)", p.get("arrasamento_m")],
                    ["Pilar", p["rotulo"] if p["rotulo"] in pilares else None], ["Ficha", p["ficha"]],
                    ["Conferir", "há estaca de outro sistema dentro do bloco" if outras else None]],
                   _fonte_ficha(dados, p["ficha"]), doc=_doc_id(_arquivo_ficha(dados, p["ficha"])))
    for f in formas:
        p = f["properties"]
        if p["tipo"] == "Pilar (forma)":
            codigo = REGRAS["fichas"].get(p["ficha"], {}).get("sistema", REGRAS["sistema_geral"])
            _adicionar(ctx, codigo, "pilar", p["bloco"], f["geometry"],
                       [["Lado (m)", p.get("lado_m")], ["Bloco", p["bloco"]],
                        ["Estacas do bloco", resumo.get(p["bloco"]) or None], ["Ficha", p["ficha"]]],
                       _fonte_ficha(dados, p["ficha"]), doc=_doc_id(_arquivo_ficha(dados, p["ficha"])))
    return bloco_da_estaca


def _sistema_da_cava(idx: list, estacas: list) -> tuple[str, str]:
    """Estrutura com mais que `cava_maioria` das estacas dentro da cava; senão o sistema geral, com o motivo."""
    geral = REGRAS["sistema_geral"]
    if not idx:
        return geral, "sem estaca dentro da cava"
    codigo, n = Counter(estacas[i]["properties"]["estrutura"] for i in idx).most_common(1)[0]
    fracao = n / len(idx)
    if fracao > REGRAS["cava_maioria"]["valor"]:
        return codigo, f"maioria das estacas dentro ({round(100 * fracao)} %)"
    return geral, f"nenhuma estrutura com maioria das estacas ({codigo} {round(100 * fracao)} %)"


def _doc_da_cava(dados: dict, geometria: dict) -> str | None:
    """Folha PBGE ESCAVAÇÃO cuja janela da planta contém a cava; sem janela que a contenha, a primeira folha de escavação."""
    folhas = [p for p in dados.get("pranchas", [])
              if re.search(r"ESCAVA[CÇ][AÃ]O", f"{p.get('pdf', '')} {p['nome']}".upper())]
    ponto = shape(geometria).representative_point()
    for p in folhas:
        janela = _janela(p, dados["crs"]["epsg"])
        if janela is not None and janela.contains(ponto):
            return _doc_id(p.get("pdf"))
    return _doc_id(folhas[0].get("pdf")) if folhas else None


def _cavas(ctx: dict, dados: dict, cavas: list, estacas: list, dentro: list) -> None:
    fonte = f"escavação calculada (camadas.escavacao) · {(dados.get('escavacao') or {}).get('fonte', '')}".rstrip(" ·")
    for f, idx in zip(cavas, dentro):
        p = f["properties"]
        codigo, criterio = _sistema_da_cava(idx, estacas)
        fundo = p.get("fundo_m")
        _adicionar(ctx, codigo, "cava", p["id"], f["geometry"],
                   [["Escavação (m³)", p.get("escavacao_m3")], ["Reaterro (m³)", p.get("reaterro_m3")],
                    ["Área (m²)", p.get("area_m2")], ["Base (m²)", p.get("base_m2")],
                    ["Profundidade média (m)", p.get("prof_media_m")], ["Profundidade máxima (m)", p.get("prof_max_m")],
                    ["Fundo (cota, m)", f"{fundo[0]:.2f} a {fundo[1]:.2f}" if fundo else None],
                    ["Etapa", p.get("etapa")],
                    ["Na borda do levantamento", None if "na_borda_do_levantamento" not in p
                     else "sim" if p["na_borda_do_levantamento"] else "não"],
                    ["Estacas dentro", _por_sistema(idx, estacas) or None], ["Sistema pelo critério", criterio]],
                   fonte, etapa=p.get("etapa"), doc=_doc_da_cava(dados, f["geometry"]))


def _estruturas(ctx: dict, dados: dict) -> None:
    """Manchas de etapa da folha 04 (vetores f004-*): sistema geral, o nome da mancha como rótulo."""
    pdfs = {p["nome"]: p.get("pdf") for p in dados.get("pranchas", [])}
    for v in dados.get("vetores", []):
        if not v["id"].startswith("f004-"):
            continue
        for n, f in enumerate(v.get("geojson", {}).get("features", []), 1):
            p = f["properties"]
            _adicionar(ctx, REGRAS["sistema_geral"], "estrutura", p["nome"], f["geometry"],
                       [["Etapa", p.get("etapa")], ["Área (m²)", p.get("area_m2")], ["Prancha", p.get("prancha")]],
                       p.get("prancha") or "folha 04 (camadas.prancha)", etapa=p.get("etapa"), chave=f"{v['id']}-{n:02d}",
                       doc=_doc_id(pdfs.get(p.get("prancha"))))


def _janela(prancha: dict, epsg: int):
    """Janela da planta (clip_mapa, em pt da página) como polígono lon/lat; None sem georreferência."""
    if prancha.get("M") is None or not prancha.get("clip_mapa"):
        return None
    x0, y0, x1, y1 = prancha["clip_mapa"]
    afim = np.asarray(prancha["M"], float).reshape(2, 3)
    canto = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) @ afim[:, :2].T + afim[:, 2]
    return Polygon(np.column_stack(geo.para_lonlat(canto[:, 0], canto[:, 1], epsg)))


def _metros(geometria, epsg: int) -> float:
    """Comprimento em metros (UTM) de uma geometria lon/lat."""
    return float(shapely.transform(geometria, lambda xy: np.column_stack(geo.para_utm(xy[:, 0], xy[:, 1], epsg))).length)


def _linhas(geometria):
    """Só as partes lineares de um recorte (o recorte pode devolver pontos soltos)."""
    return [g for g in shapely.get_parts(geometria) if g.geom_type == "LineString" and not g.is_empty]


def _regioes(janelas: dict) -> dict:
    """Região de cada folha: onde duas janelas se sobrepõem, o trecho fica com a folha de centro mais próximo."""
    centros = {pid: np.array(j.centroid.coords[0]) for pid, j in janelas.items()}
    regioes = {}
    for pid, janela in janelas.items():
        perdidos = []
        for outro, vizinha in janelas.items():
            if outro == pid:
                continue
            meio, normal = (centros[pid] + centros[outro]) / 2, centros[outro] - centros[pid]
            normal = normal / np.linalg.norm(normal)
            tangente = np.array([-normal[1], normal[0]])
            semiplano = Polygon([meio + tangente, meio - tangente, meio - tangente + normal, meio + tangente + normal])
            perdidos.append(vizinha.intersection(shapely.affinity.scale(semiplano, 1e3, 1e3, origin=tuple(meio))))
        regioes[pid] = janela.difference(shapely.union_all(perdidos)) if perdidos else janela
    return regioes


def _recortes(janelas: dict, partes: dict, epsg: int) -> dict:
    """{folha: {classe: (linhas lon/lat, fração da classe na rede)}} pelas regiões das folhas."""
    totais = {c: _metros(g, epsg) for c, g in partes.items()}
    saida = {}
    for pid, regiao in _regioes(janelas).items():
        saida[pid] = {}
        for classe, g in partes.items():
            linhas = _linhas(g.intersection(regiao))
            if linhas and totais[classe]:
                saida[pid][classe] = (linhas, _metros(shapely.multilinestrings(linhas), epsg) / totais[classe])
    return saida


def _trecho_da_folha(ctx: dict, codigo: str, rede: dict, pid: str, dados: dict, recorte: dict, rotulo: str) -> None:
    """Um trecho: geometria da folha, extensão por superfície (quadro da rede × fração) e contrato × desenho."""
    nomes = (dados.get("valas") or {}).get("classes", {})
    prancha = next(p for p in dados["pranchas"] if p["id"] == pid)
    por_classe = Counter()
    for q in rede["quadro"]:
        por_classe[q["classe"]] += q["extensao_m"]
    ext = {c: por_classe[c] * fr for c, (_, fr) in recorte.items()}
    linhas = [g for lin, _ in recorte.values() for g in lin]
    geom = shapely.line_merge(shapely.union_all(linhas))
    geom = shapely.transform(geom, lambda xy: np.round(xy, 7))
    escopo = dados.get("escopo") or {}
    tx = next((t for t in escopo.get("tubo_x_desenho") or [] if t["prancha"] == pid), None)
    superficies = [[f"{nomes.get(c, {}).get('nome', c)} (m)", round(m, 1)]
                   for c, m in sorted(ext.items(), key=lambda kv: -kv[1]) if round(m, 1) > 0]
    contrato = [] if not tx else [["Tabela(s) do contrato", ", ".join(tx["tabelas"])],
                                  ["Item do contrato", f"{tx['codigo']} · {tx['descricao']}"],
                                  ["Tubo no contrato (m)", tx["contrato_m"]], ["Tubo no desenho (m)", tx["desenho_m"]],
                                  ["Diferença desenho × contrato (%)", tx["diferenca_pct"]]]
    fonte = f"valas (camadas.valas) · {prancha['nome']}" + (f" · contrato: {escopo.get('fonte', '')}" if tx else "")
    _adicionar(ctx, codigo, "trecho", rotulo, mapping(geom),
               [["Rede", _sistema(codigo)["nome"]], ["Diâmetro (mm)", rede["de_mm"]],
                ["Fonte do diâmetro", rede.get("fonte_de") or None], ["Extensão estimada (m)", round(sum(ext.values()), 1)],
                *superficies, ["Folha", prancha["nome"]], *contrato], fonte, chave=pid, doc=_doc_id(prancha.get("pdf")))


def _rotulo_do_trecho(rede: str, prancha: dict, folhas: int) -> str:
    """'AAT06 · folha 09' pelo número da folha no nome da prancha; rede de uma folha só leva o nome da rede."""
    m = re.search(r"(\d+)\s*/\s*\d+", prancha["nome"])
    if folhas == 1:
        return rede
    return f"{rede} · folha {int(m[1]):02d}" if m else f"{rede} · {prancha['id']}"


def _trechos(ctx: dict, dados: dict, cfg: dict) -> None:
    """Um trecho por folha de cada rede declarada em `valas.redes`, com o tubo das valas dentro da janela da planta."""
    declaradas = (cfg.get("valas") or {}).get("redes", [])
    if not declaradas:
        return
    valas = (dados.get("valas") or {}).get("redes", [])
    feats = next((v["geojson"]["features"] for v in dados.get("vetores", []) if v["id"] == "valas"), [])
    epsg = dados["crs"]["epsg"]
    codigos = {s["rede"]: c for c, s in REGRAS["sistemas"].items() if "rede" in s}
    por_id = {p["id"]: p for p in dados.get("pranchas", [])}
    for declarada in declaradas:
        rede = next((r for r in valas if r["id"] == declarada["id"]), None)
        if rede is None or declarada["id"] not in codigos:
            continue
        janelas = {pid: j for pid in declarada["pranchas"] if pid in por_id and (j := _janela(por_id[pid], epsg))}
        partes = {f["properties"]["classe"]: shape(f["geometry"]) for f in feats if f["properties"]["rede"] == rede["id"]}
        for pid, recorte in _recortes(janelas, partes, epsg).items():
            if not recorte:
                continue
            _trecho_da_folha(ctx, codigos[rede["id"]], rede, pid, dados, recorte,
                             _rotulo_do_trecho(rede["id"], por_id[pid], len(janelas)))


def _arvore(contagem: Counter) -> list:
    """Unidades > sistemas > contagem por classe, na ordem do conceito; sistema sem elemento fica de fora."""
    codigos = list(REGRAS["sistemas"]) + sorted({c for c, _ in contagem} - set(REGRAS["sistemas"]))
    arvore = []
    for uid, u in REGRAS["unidades"].items():
        sistemas = []
        for codigo in codigos:
            classes = {cl: n for (c, cl), n in contagem.items() if c == codigo}
            s = _sistema(codigo)
            if classes and s["unidade"] == uid:
                sistemas.append({"id": f"{uid}-{codigo}", "nome": s["nome"], "estado": s["estado"], "classes": classes})
        arvore.append({"id": uid, "nome": u["nome"], "obra": u["obra"], "sistemas": sistemas})
    return arvore


def montar(dados: dict, cfg: dict) -> dict | None:
    """Árvore unidade > sistema > classe e FeatureCollection de todos os elementos construtivos (lon/lat); None sem nada."""
    vet = {v["id"]: v.get("geojson", {}).get("features", []) for v in dados.get("vetores", [])}
    estacas, formas, cavas = vet.get("estacas", []), vet.get("blocos_forma", []), vet.get("escavacao", [])
    pontos = np.array([f["geometry"]["coordinates"][:2] for f in estacas], float).reshape(-1, 2)

    def dentro(feicoes):
        return [np.flatnonzero(shapely.contains_xy(shape(f["geometry"]), pontos[:, 0], pontos[:, 1])).tolist()
                for f in feicoes]

    ctx = {"features": [], "usados": set(), "contagem": Counter()}
    bloco_da_estaca = _blocos_e_pilares(ctx, dados, formas, estacas, dentro(formas))
    _estacas(ctx, estacas, bloco_da_estaca)
    _cavas(ctx, dados, cavas, estacas, dentro(cavas))
    _estruturas(ctx, dados)
    _trechos(ctx, dados, cfg)
    if not ctx["features"]:
        return None
    presentes = {cl for _, cl in ctx["contagem"]}
    return {"fonte": REGRAS["metadata"]["fonte"],
            "classes": {k: v for k, v in REGRAS["classes"].items() if k in presentes},
            "arvore": _arvore(ctx["contagem"]),
            "geojson": {"type": "FeatureCollection", "features": ctx["features"]}}


def metadados() -> dict:
    """Rastreabilidade do método e das regras declaradas (regra 9 do estilo)."""
    regras = [("sistemas." + k, v) for k, v in REGRAS["sistemas"].items()] + \
             [("fichas." + k, v) for k, v in REGRAS["fichas"].items()] + [("cava_maioria", REGRAS["cava_maioria"])]
    return {
        "modulo": "construtivos",
        "descricao": "elementos construtivos (estaca, bloco, pilar, cava, estrutura, trecho de rede) por unidade e sistema, "
                     "para achar o elemento pelo nome",
        "funcoes": ["montar", "metadados"],
        "bibliografia": [],
        "premissas": [{"aplicacao": {"montar": [nome]}, "fonte": v["fonte"], "estado": v["estado"]} for nome, v in regras],
        "ultima_revisao": REGRAS["metadata"]["data_referencia"],
    }
