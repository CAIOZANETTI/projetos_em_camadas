"""Evidências da EAP: o loop que passa por todos os documentos e preenche cada fato com o que cada um afirma.

    EAP geral (conceitos/eap_geral.jsonl) + banco de serviços (conceitos/servicos.jsonl) + vocabulário
        │   (conceitos/sinonimos.json): termos por item e serviço, sinônimos, abreviações, unidades, cadastro
        ▼
    para cada documento:  edital/memorial (texto)  ─ regex ─┐
                          planilha do contrato     ─ cadastro de materiais + regex ─┤
                          pranchas medidas         ─ eap.quantificar ─┼─► evidências (evidencia.schema.json)
                          serviços associados      ─ associados (fórmulas) ─┤
                          planilha Obras Lineares  ─ digitado × recálculo do MOS, mesmos trechos ─┤
                          IA (com citação literal) ─ conferir_citacao ─┤
                          decisão do engenheiro    ─ decisao ──────────┘
        ▼
    consolidar: fato = (código EAP, serviço, unidade) → afirmações por documento → convergente | fonte única |
                conflito | só menção | decidido;  cobertura: item × (projeto, edital);
                associados_x_edital: serviço que a execução exige e o edital não cita

O código não escolhe a verdade: extrai de forma reprodutível, guarda todas as afirmações com o trecho literal e
mostra onde concordam (mais documentos = mais força) e onde divergem (ex.: 300 estacas no projeto × 250 no memorial).
Escolher um valor é uma evidência `decisao`, com autor e justificativa, que não apaga as outras.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import pandas as pd

from . import associados, dimensoes, eap, vocabulario
from .construtivos import REGRAS as UNIDADES
from .pdf_cad import CONCEITOS
from .vocabulario import (
    NUMERO,
    normalizar,
    numero_br,
    preparar,
    quantidade,
    unidade_medida,
)

SCHEMA = json.loads((CONCEITOS / "evidencia.schema.json").read_text(encoding="utf-8"))
SERVICOS = [json.loads(linha) for linha in (CONCEITOS / "servicos.jsonl").read_text(encoding="utf-8").splitlines()
            if linha.strip()]
TIPOS_EDITAL, TIPOS_PROJETO = {"edital", "memorial", "planilha"}, {"projeto", "geometria"}


def escopo_do_texto(texto: str) -> set[str]:
    """{'agua', 'esgoto'} citados: código Sanepar SAA/SES e palavras de cada sistema."""
    t = normalizar(texto)
    saida = set()
    if re.search(r"\bSAA\b|ABASTECIMENTO DE AGUA|AGUA TRATADA|\bETA\b|ADUTORA|REDE DE DISTRIBUICAO", t):
        saida.add("agua")
    if re.search(r"\bSES\b|ESGOT|\bETE\b|COLETOR|INTERCEPTOR|EMISSARIO|POCO DE VISITA", t):
        saida.add("esgoto")
    return saida


def validar_evidencia(ev: dict) -> list[str]:
    """Problemas de uma evidência contra o schema (campos obrigatórios, enums, decisão com autor)."""
    props = SCHEMA["properties"]
    problemas = [f"falta '{k}'" for k in SCHEMA["required"] if k not in ev]
    tipo = (ev.get("documento") or {}).get("tipo")
    if tipo not in props["documento"]["properties"]["tipo"]["enum"]:
        problemas.append(f"tipo de documento '{tipo}' inválido")
    if ev.get("metodo") not in props["metodo"]["enum"]:
        problemas.append(f"método '{ev.get('metodo')}' inválido")
    if "codigo" in ev and not re.fullmatch(props["codigo"]["pattern"], ev["codigo"]):
        problemas.append(f"código '{ev['codigo']}' fora do padrão")
    if ev.get("metodo") == "decisao" and not (ev.get("autor") and ev.get("justificativa")):
        problemas.append("decisão sem autor ou justificativa")
    return problemas


def evidencia(**campos) -> dict:
    """Evidência com id estável (hash) e conferida contra o schema; levanta ValueError se não passa."""
    chave = json.dumps([campos.get(k) for k in ("documento", "localizador", "metodo", "codigo", "servico", "trecho",
                                                 "unidade", "valor", "autor")], ensure_ascii=False, sort_keys=True)
    ev = {"id": hashlib.sha1(chave.encode(), usedforsecurity=False).hexdigest()[:16], **campos}   # id, não segurança
    problemas = validar_evidencia(ev)
    if problemas:
        raise ValueError(f"evidência inválida: {problemas} — {ev}")
    return ev


def _itens_ordenados(obra: str | None, escopo: str | None) -> list[dict]:
    return sorted((it for it in eap.itens().values() if (obra is None or obra in it["obra"])
                   and (escopo is None or escopo in it["escopo"])), key=lambda it: it["prioridade"])


def classificar(linha: str, obra: str | None = None, escopo: str | None = None) -> tuple[str | None, str, str]:
    """(item EAP, serviço, regra) de uma linha normalizada. O item é o primeiro que casa por prioridade; o serviço,
    o primeiro do banco que o item admite. Sem item, um serviço com pacote dá 'PACOTE.*' (ex.: forma → CIV.EST.*)."""
    for it in _itens_ordenados(obra, escopo):
        if re.search(it["termos"], linha):
            servico = next((s["id"] for s in SERVICOS if s["id"] in it["servicos"] and re.search(s["termos"], linha)), "")
            return it["codigo"], servico, f"item {it['codigo']}" + (f" · serviço {servico}" if servico else "")
    for s in SERVICOS:
        if s["pacote"] and re.search(s["termos"], linha):
            return f"{s['pacote']}.*", s["id"], f"serviço {s['id']} (sem item)"
    return None, "", ""


def _codigo(unidade: str, sistema: str, item: str) -> str:
    return f"{unidade}.{sistema}.{item}"


def buscar_texto(documento: dict, paginas: list[str]) -> list[dict]:
    """Evidências de um documento de texto (edital, memorial, relatório), linha a linha. `documento` traz id, tipo,
    nome e, se souber, unidade ('U1'), sistema, obra e escopo; o que não souber fica '*'."""
    unidade, sistema = documento.get("unidade", "*"), documento.get("sistema", "*")
    saida = []
    for np_, pagina in enumerate(paginas, 1):
        for nl, bruta in enumerate(str(pagina).splitlines(), 1):
            medir, linha = preparar(bruta)
            item, servico, regra = classificar(linha, documento.get("obra"), documento.get("escopo"))
            if item is None:
                continue
            valor, un = quantidade(medir, [it["termos"] for it in eap.itens().values()])
            saida.append(evidencia(codigo=_codigo(unidade, sistema, item), servico=servico, unidade=un, valor=valor,
                                   parcela=False, documento=_doc(documento), localizador=f"p. {np_}, linha {nl}",
                                   trecho=bruta.strip(), metodo="regex", regra=regra,
                                   escopo=documento.get("escopo")))
    return saida


def _doc(documento: dict) -> dict:
    return {k: documento[k] for k in ("id", "tipo", "nome") if k in documento}


def _casa_catalogo(filtro: dict | None, espec: dict) -> bool:
    if not filtro:
        return False
    return (espec.get("subcategoria") in filtro.get("subcategoria", []) or espec.get("familia") in filtro.get("familia", [])
            or bool(filtro.get("termos") and re.search(filtro["termos"], normalizar(espec.get("descricao")))))


def item_do_material(espec: dict) -> str | None:
    """Item EAP de um material do cadastro Sanepar pela subcategoria, família ou termos do item (EAP geral)."""
    return next((it["codigo"] for it in _itens_ordenados(None, None) if _casa_catalogo(it["catalogo"], espec)), None)


def escopo_do_material(espec: dict) -> str | None:
    """'esgoto' se a descrição diz esgoto, 'agua' se diz água; None = serve aos dois."""
    escopos = escopo_do_texto(espec.get("descricao", ""))
    return next(iter(escopos)) if len(escopos) == 1 else None


def catalogo_por_item(catalogo: dict, escopo: str | None = None) -> pd.DataFrame:
    """Quantos materiais do cadastro balizam cada item EAP (os do outro escopo ficam de fora), com exemplos."""
    linhas = {}
    for espec in catalogo.values():
        item = item_do_material(espec)
        if item and (escopo is None or escopo_do_material(espec) in (None, escopo)):
            linhas.setdefault(item, []).append(espec)
    nomes = eap.itens()
    return pd.DataFrame([{"item": c, "nome": nomes[c]["nome"], "n_materiais": len(m),
                          "exemplos": [e["descricao"] for e in m[:3]]} for c, m in linhas.items()])


def _unidade_da_planilha(texto) -> str:
    m = re.search(r"UNIDADE\s*(\d+)", normalizar(texto))
    return f"U{m[1]}" if m else "*"


def de_planilha(itens: pd.DataFrame, documento: dict, catalogo: dict | None = None) -> list[dict]:
    """Evidências do contrato (escopo_itens.csv de camadas.orcamento_sanepar): uma parcela por linha. O item vem do
    cadastro de materiais pelo código, senão pela descrição; quantidade em branco = item previsto sem número."""
    catalogo, saida = catalogo or {}, []
    for r in itens.itertuples(index=False):
        linha, espec = preparar(r.descricao)[1], catalogo.get(str(r.codigo).split(".")[0])
        unidade = _unidade_da_planilha(r.unidade_obra)
        obra = UNIDADES["unidades"].get(unidade.lower(), {}).get("obra")
        item, servico, regra = classificar(linha, obra)
        if espec and (pelo_cadastro := item_do_material(espec)):
            item, regra = pelo_cadastro, f"cadastro Sanepar {r.codigo} ({espec.get('subcategoria')}) → {pelo_cadastro}"
        if item is None:
            continue
        valor, un = (None, None) if pd.isna(r.quantidade) or not unidade_medida(r.unidade) else \
            vocabulario.converter(float(r.quantidade), unidade_medida(r.unidade))
        saida.append(evidencia(codigo=_codigo(unidade, "*", item), servico=servico, unidade=un, valor=valor,
                               parcela=True, documento=_doc(documento), localizador=f"{r.aba} linha {r.linha_origem}",
                               trecho=str(r.descricao), metodo="catalogo" if espec else "planilha", regra=regra,
                               escopo=escopo_do_material(espec) if espec else None))
    return saida


def de_quantificacao(quant: pd.DataFrame) -> list[dict]:
    """Evidências das pranchas medidas (eap.quantificar): um total por item e grandeza, com os elementos."""
    doc = {"id": "modelo:construtivos", "tipo": "geometria",
           "nome": "elementos construtivos medidos nas pranchas (camadas.eap.quantificar)"}
    return [evidencia(codigo=r.codigo, servico="", unidade=r.unidade, valor=float(r.quantidade), parcela=False,
                      documento=doc, localizador=f"{r.n_elementos} elementos: {', '.join(r.evidencias[:10])}"
                      + (" …" if len(r.evidencias) > 10 else ""),
                      trecho="; ".join(r.fontes), metodo="geometria", regra=f"eap.quantificar · {r.grandeza}")
            for r in quant.itertuples(index=False) if r.n_elementos > r.sem_valor]


# Planilha Obras Lineares: o que o trecho traz digitado × o que o MOS recalcula para o mesmo trecho ------------------------
GRANDEZAS_LINEARES = (
    # (campo, item EAP, serviço, unidade): 'escoramento_m2' só existe no recálculo (a planilha traz sim/não)
    ("comp_m", "HID.TUB.RED", "assentamento", "m"),
    ("escavacao_m3", "GEO.MOV.VAL", "escavacao", "m³"),
    ("reaterro_m3", "GEO.MOV.VAL", "reaterro", "m³"),
    ("bota_fora_m3", "GEO.MOV.VAL", "bota_fora", "m³"),
    ("escoramento_m2", "GEO.MOV.VAL", "escoramento", "m²"),
    ("supressao_m2", "GEO.MOV.SUP", "", "m²"),
)
DOCUMENTO_MOS = {"id": "metodo:mos_sanepar:obras_lineares", "tipo": "associado",   # distinto do das valas dos elementos
                 "nome": "MOS Sanepar (lineares.dimensionar_vala) recalculando os trechos da planilha Obras Lineares"}


def _de_trechos_lineares(trechos: list[dict], valores_do_trecho, documento: dict, metodo: str, regra: str,
                         base: str) -> list[dict]:
    """Uma evidência `parcela` por trecho e grandeza com valor numérico não nulo. `valores_do_trecho(trecho)` devolve
    {campo: valor} (e, opcional, 'memoria': texto que acompanha o trecho literal)."""
    saida = []
    for t in trechos:
        valores = valores_do_trecho(t)
        local = f"{t.get('local', '')}" + (f", linha {t['linha']}" if t.get("linha") else "")
        for campo, item, servico, unidade in GRANDEZAS_LINEARES:
            valor = valores.get(campo)
            if not isinstance(valor, (int, float)) or isinstance(valor, bool) or not math.isfinite(valor) \
                    or abs(valor) <= 1e-9:
                continue
            texto = f"{t.get('local', '')}: {servico or 'supressão vegetal'} {valor:.6g} {unidade}"
            saida.append(evidencia(codigo=f"{base}.{item}", servico=servico, unidade=unidade, valor=round(float(valor), 6),
                                   parcela=True, documento=documento, localizador=local,
                                   trecho=texto + (f" ({valores['memoria']})" if valores.get("memoria") else ""),
                                   metodo=metodo, regra=regra))
    return saida


def de_obras_lineares(trechos: list[dict], documento: dict, base: str = "U1.LINEARES") -> list[dict]:
    """Evidências da planilha Obras Lineares (`obras_lineares.ler_obras_lineares`): o comprimento digitado
    (`comp_m`) e os valores do campo `planilha` (escavação, reaterro, bota-fora, supressão). O escoramento da
    planilha é sim/não, sem área: não gera evidência. Valor em branco ou zero não entra."""
    return _de_trechos_lineares(trechos, lambda t: {"comp_m": t.get("comp_m"), **(t.get("planilha") or {})},
                                documento, "planilha", "obras_lineares.planilha", base)


def de_obras_lineares_mos(trechos: list[dict], furos: list[dict] | None = None, base: str = "U1.LINEARES") -> list[dict]:
    """Recálculo dos mesmos trechos pelo MOS (`lineares.dimensionar_vala`): escavação, reaterro e bota-fora da planilha,
    mais o escoramento em m² (serviço `escoramento`, o total). O comprimento não entra: o MOS só o copia da entrada,
    e repeti-lo daria uma confirmação falsa (o assentamento fica só com a planilha). Trecho em VCA sem profundidade ou
    com material fora da Tabela I do MOS (sem largura) não tem recálculo; em MND a largura não existe, e vale o método."""
    from . import lineares, obras_lineares
    campos = [k for k, *_ in GRANDEZAS_LINEARES if k not in ("comp_m", "supressao_m2")]

    def recalcular(trecho: dict) -> dict:
        r = lineares.dimensionar_vala(trecho, furos or [])
        mnd = obras_lineares.norm(trecho.get("metodo") or "VCA") == "MND"
        if not mnd and not r.get("largura_m"):
            return {}
        partes = [f"L = {r['largura_m']:g} m"] if r.get("largura_m") else ["MND: só os caximbos escavam"]
        partes += [f"h = {r['profundidade_m']:g} m"] if r.get("profundidade_m") else []
        partes.append(r.get("tipo_escoramento") or "sem escoramento")
        return {**{k: r.get(k) for k in campos}, "memoria": "MOS: " + ", ".join(partes)}
    return _de_trechos_lineares(trechos, recalcular, DOCUMENTO_MOS, "associado", "obras_lineares.mos_sanepar", base)


def conferir_citacao(ev: dict, paginas: list[str]) -> dict:
    """Evidência de IA conferida: o trecho tem de estar no documento e o valor tem de estar no trecho."""
    texto, trecho = normalizar(" ".join(map(str, paginas))), normalizar(ev.get("trecho", ""))
    numeros = [numero_br(n) for n in re.findall(NUMERO, trecho)]
    if not trecho or trecho not in texto:
        status = "trecho não encontrado no documento"
    elif ev.get("valor") is not None and not any(abs(n - ev["valor"]) < 1e-9 for n in numeros):
        status = "valor não está no trecho"
    else:
        status = "conferida"
    return {**ev, "citacao": status}


def decisao(codigo: str, servico: str, unidade: str, valor: float, autor: str, justificativa: str) -> dict:
    """Valor adotado pelo engenheiro para um fato: entra como evidência, não apaga as afirmações dos documentos."""
    return evidencia(codigo=codigo, servico=servico, unidade=unidade, valor=valor, parcela=False,
                     documento={"id": f"decisao:{autor}", "tipo": "decisao"}, localizador="", trecho=justificativa,
                     metodo="decisao", regra="decisão do engenheiro", autor=autor, justificativa=justificativa)


def _casa(padrao: str, codigo: str) -> bool:
    """U1.*.GEO.FUN.EST casa U1.ACT600.GEO.FUN.EST: '*' vale qualquer segmento; o comprimento tem de ser igual."""
    p, c = padrao.split("."), codigo.split(".")
    return len(p) == len(c) and all(a in ("*", b) for a, b in zip(p, c))


def _afirmacoes(evs: list[dict]) -> list[dict]:
    """Uma afirmação por documento e valor: parcelas somadas; totais repetidos (mesmo valor) contam uma vez."""
    saida = []
    for doc in dict.fromkeys(e["documento"]["id"] for e in evs):
        do_doc = [e for e in evs if e["documento"]["id"] == doc]
        parcelas = [e for e in do_doc if e["parcela"]]
        grupos = ([("parcelas", parcelas)] if parcelas else []) + \
                 [(f"total {e['valor']:g}", [t for t in do_doc if not t["parcela"] and t["valor"] == e["valor"]])
                  for e in {e["valor"]: e for e in do_doc if not e["parcela"]}.values()]
        saida += [{"documento": doc, "tipo": g[0]["documento"]["tipo"],
                   "valor": sum(e["valor"] for e in g) if nome == "parcelas" else g[0]["valor"],
                   "evidencias": [e["id"] for e in g], "trechos": [e["trecho"] for e in g][:3],
                   "derivada": any(e.get("derivada") for e in g)} for nome, g in grupos]
    return saida


def _derivadas(chave: tuple, valoradas: list[dict]) -> list[dict]:
    """Para um fato com '*', o total de cada documento que só fala dos códigos concretos (soma dos sistemas)."""
    codigo, servico, unidade = chave
    if "*" not in codigo:
        return []
    diretos = {e["documento"]["id"] for e in valoradas if (e["codigo"], e["servico"], e["unidade"]) == chave}
    saida = []
    for doc in dict.fromkeys(e["documento"]["id"] for e in valoradas):
        partes = [e for e in valoradas if e["documento"]["id"] == doc and e["codigo"] != codigo and "*" not in e["codigo"]
                  and _casa(codigo, e["codigo"]) and e["servico"] == servico and e["unidade"] == unidade]
        if partes and doc not in diretos:
            saida += [{**e, "parcela": True, "derivada": True} for e in partes]
    return saida


def _grupos(afirm: list[dict], tol: float) -> list[list[dict]]:
    """Afirmações agrupadas por valor (diferença relativa até `tol`), do maior grupo para o menor."""
    grupos = []
    for a in sorted(afirm, key=lambda a: a["valor"]):
        if grupos and abs(a["valor"] - grupos[-1][0]["valor"]) <= tol * max(1.0, abs(grupos[-1][0]["valor"])):
            grupos[-1].append(a)
        else:
            grupos.append([a])
    return sorted(grupos, key=lambda g: -len({a["documento"] for a in g}))


def _fato(chave: tuple, evs: list[dict], mencoes: list[dict], tol: float) -> dict:
    """Status de um fato a partir das afirmações por documento (decisão à parte)."""
    decisoes = [e for e in evs if e["metodo"] == "decisao"]
    afirm = _afirmacoes([e for e in evs if e["metodo"] != "decisao"])
    grupos = _grupos(afirm, tol)
    valores = [a["valor"] for a in afirm]
    docs = {a["documento"] for a in afirm}
    if decisoes:
        status, valor = "decidido", decisoes[-1]["valor"]
    elif not afirm:
        status, valor = "só menção", None
    elif len(grupos) > 1:
        status, valor = "conflito", None
    else:
        status, valor = ("convergente" if len(docs) > 1 else "fonte única"), grupos[0][0]["valor"]
    return {"codigo": chave[0], "servico": chave[1], "unidade": chave[2], "status": status, "valor": valor,
            "forca": len({a["documento"] for a in grupos[0]}) if grupos else 0, "n_documentos": len(docs),
            "diferenca_pct": round(100 * (max(valores) - min(valores)) / max(abs(max(valores)), 1e-9), 1)
            if len(grupos) > 1 else 0.0,
            "afirmacoes": afirm, "mencoes": sorted({m["documento"]["id"] for m in mencoes}),
            "decisoes": [{"valor": d["valor"], "autor": d["autor"], "justificativa": d["justificativa"]} for d in decisoes]}


def consolidar(evs: list[dict], tol: float = 0.005) -> pd.DataFrame:
    """Fatos (código, serviço, unidade) com o status: convergente, fonte única, conflito, só menção ou decidido.
    IA só entra com citação conferida. Menção (sem número) reforça o fato mas não dá valor."""
    aceitas = [e for e in evs if e["metodo"] != "ia" or e.get("citacao") == "conferida"]
    valoradas = [e for e in aceitas if e["valor"] is not None and e["unidade"]]
    mencoes = [e for e in aceitas if e["valor"] is None]
    chaves = list(dict.fromkeys((e["codigo"], e["servico"], e["unidade"]) for e in valoradas))
    fatos = []
    for chave in chaves:
        evs_fato = [e for e in valoradas if (e["codigo"], e["servico"], e["unidade"]) == chave] + _derivadas(chave, valoradas)
        fatos.append(_fato(chave, evs_fato, [m for m in mencoes if (m["codigo"], m["servico"]) == chave[:2]], tol))
    com_valor = {c[:2] for c in chaves}
    for chave in dict.fromkeys((m["codigo"], m["servico"]) for m in mencoes if (m["codigo"], m["servico"]) not in com_valor):
        fatos.append(_fato((*chave, None), [], [m for m in mencoes if (m["codigo"], m["servico"]) == chave], tol))
    return pd.DataFrame(fatos)


def cobertura(evs: list[dict]) -> pd.DataFrame:
    """Para cada unidade e item da EAP geral (tipo de obra e escopo da unidade): há evidência no projeto? no edital?
    Item só no projeto → verificar se o edital o considera; só no edital → sem evidência no projeto."""
    linhas = []
    for uid, u in UNIDADES["unidades"].items():
        for codigo, it in eap.itens().items():
            if u["obra"] not in it["obra"] or (u.get("escopo") and u["escopo"] not in it["escopo"]):
                continue
            tipos = {e["documento"]["tipo"] for e in evs if e["metodo"] != "decisao"
                     and e["codigo"].split(".")[0] in (uid.upper(), "*") and ".".join(e["codigo"].split(".")[2:]) == codigo
                     and (e["metodo"] != "ia" or e.get("citacao") == "conferida")}
            projeto, edital = bool(tipos & TIPOS_PROJETO), bool(tipos & TIPOS_EDITAL)
            situacao = {(True, True): "projeto e edital", (True, False): "só projeto: verificar se o edital considera",
                        (False, True): "só edital: sem evidência no projeto", (False, False): "sem evidência"}
            linhas.append({"unidade": uid.upper(), "item": codigo, "nome": it["nome"], "tipos": sorted(tipos),
                           "situacao": situacao[(projeto, edital)]})
    return pd.DataFrame(linhas)


def associados_x_edital(evs: list[dict]) -> pd.DataFrame:
    """Serviços associados (exigidos pela execução) × edital/planilha/memorial: o mesmo item e serviço citado em
    algum documento do edital, na mesma unidade ou em '*'? Se não, 'não citado no edital: incluir ou confirmar'."""
    edital = {(e["codigo"].split(".")[0], ".".join(e["codigo"].split(".")[2:]), e["servico"]) for e in evs
              if e["documento"]["tipo"] in TIPOS_EDITAL}
    linhas = {}
    for e in (e for e in evs if e["metodo"] == "associado"):
        u, item = e["codigo"].split(".")[0], ".".join(e["codigo"].split(".")[2:])
        chave = (u, item, e["servico"], e["unidade"])
        linha = linhas.setdefault(chave, {"unidade": u, "item": item, "servico": e["servico"], "unidade_medida": e["unidade"],
                                          "quantidade": 0.0, "n_elementos": 0, "regras": set()})
        linha["quantidade"] += e["valor"]
        linha["n_elementos"] += 1
        linha["regras"].add(e["regra"])
    for (u, item, servico, _), linha in linhas.items():
        citado = (u, item, servico) in edital or ("*", item, servico) in edital
        linha.update(regras=sorted(linha["regras"]), quantidade=round(linha["quantidade"], 3),
                     situacao="citado no edital" if citado else "não citado no edital: incluir ou confirmar")
    return pd.DataFrame(linhas.values())


def gravar(evs: list[dict], caminho: str | Path) -> Path:
    """Registro JSONL (uma evidência por linha), sem repetir id."""
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    unicas = {e["id"]: e for e in evs}
    caminho.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in unicas.values()), encoding="utf-8")
    return caminho


def ler(caminho: str | Path) -> list[dict]:
    return [json.loads(linha) for linha in Path(caminho).read_text(encoding="utf-8").splitlines() if linha.strip()]


def paginas_pdf(caminho: str | Path) -> list[str]:
    """Texto de cada página de um PDF (PyMuPDF, opcional)."""
    import pymupdf
    with pymupdf.open(caminho) as doc:
        return [pg.get_text("text") for pg in doc]


def loop(documentos: list[dict], planilha: tuple | None = None, construtivos: dict | None = None,
         epsg: int | None = None, ia: list[dict] | None = None, decisoes: list[dict] | None = None,
         sondagens: list | None = None, declarados: list[dict] | None = None,
         extras: list[dict] | None = None) -> list[dict]:
    """Passa por todos os documentos e junta as evidências, na ordem: texto (`documentos`: [{id, tipo, nome,
    paginas, unidade?, sistema?, obra?, escopo?}]), planilha ((DataFrame, documento, catálogo)), pranchas medidas
    (`construtivos`), serviços associados aos elementos construtivos e aos `declarados` (a vala usa as `sondagens`),
    `extras` (evidências já prontas, como as da planilha Obras Lineares), IA (citação conferida no documento citado),
    decisões; por fim os serviços associados aos fatos consolidados."""
    evs = [e for d in documentos for e in buscar_texto(d, d["paginas"])]
    evs += de_planilha(*planilha) if planilha else []
    evs += de_quantificacao(eap.quantificar(construtivos, epsg)) if construtivos else []
    evs += associados.de_elementos(construtivos, epsg, sondagens, declarados)[0]
    evs += list(extras or [])
    paginas = {d["id"]: d["paginas"] for d in documentos}
    evs += [conferir_citacao(e, paginas.get(e["documento"]["id"], [])) for e in ia or []]
    evs += list(decisoes or [])
    return evs + associados.de_fatos(consolidar(evs))


def _documentos(cfg: dict, log=print) -> list[dict]:
    """Documentos de texto do obra.json (`evidencias.documentos`: pdf, tipo, unidade?, sistema?), com as páginas."""
    saida = []
    for d in (cfg.get("evidencias") or {}).get("documentos", []):
        if not Path(d["pdf"]).exists():
            log(f"  evidências: {d['pdf']} não está no disco")
            continue
        saida.append({"id": Path(d["pdf"]).name, "nome": Path(d["pdf"]).name, **d, "paginas": paginas_pdf(d["pdf"])})
    return saida


def _obras_lineares_da_obra(cfg: dict, furos: list | None, log=print) -> list[dict]:
    """Evidências da planilha Obras Lineares do obra.json (`obras_lineares`: planilha, aba?, eap?, metodo?): digitado e
    recálculo do MOS dos mesmos trechos, com o método escolhido para cada um. Sem planilha no disco, nada."""
    from . import obras_lineares
    c = cfg.get("obras_lineares") or {}
    if not c.get("planilha") or not Path(c["planilha"]).exists():
        return []
    aba, escolha = c.get("aba", "Obras Lineares"), {obras_lineares.norm(k): v for k, v in (c.get("metodo") or {}).items()}
    trechos = [{**t, "metodo": escolha.get(obras_lineares.norm(t["local"]), t["metodo"])}
               for t in obras_lineares.ler_obras_lineares(c["planilha"], aba)]
    base, documento = c.get("eap", "U1.LINEARES"), {"id": Path(c["planilha"]).name, "tipo": "planilha", "nome": f"aba {aba}"}
    evs = de_obras_lineares(trechos, documento, base) + de_obras_lineares_mos(trechos, furos, base)
    log(f"  evidências: planilha {aba}: {len(trechos)} trechos, {len(evs)} evidências (digitado × MOS)")
    return evs


def etapa(cfg: dict, out: Path, dados: dict, log=print) -> dict | None:
    """Loop de evidências da obra: documentos, planilha do contrato, planilha Obras Lineares, pranchas medidas, IA e decisões do obra.json.
    Grava evidencias.jsonl, fatos.csv, cobertura.csv, associados.csv e dimensoes.csv em `out`; devolve o resumo para o HTML (None sem fonte)."""
    from .orcamento_sanepar import catalogo
    conf, esc = cfg.get("evidencias") or {}, cfg.get("escopo") or {}
    planilha = None
    if esc.get("itens_csv") and Path(esc["itens_csv"]).exists():
        df = pd.read_csv(esc["itens_csv"], sep=";", decimal=",", encoding="utf-8-sig")
        cat = catalogo(esc["catalogo"]) if esc.get("catalogo") else None
        planilha = (df, {"id": Path(esc["itens_csv"]).name, "tipo": "planilha", "nome": esc.get("fonte", "")}, cat)
    extras = {k: ler(conf[k]) if conf.get(k) and Path(conf[k]).exists() else [] for k in ("ia", "decisoes")}
    evs = loop(_documentos(cfg, log), planilha, dados.get("construtivos"), dados["crs"]["epsg"],
               extras["ia"], extras["decisoes"], dados.get("sondagens"), cfg.get("elementos_declarados"),
               _obras_lineares_da_obra(cfg, dados.get("sondagens"), log))
    if not evs:
        return None
    gravar(evs, out / "evidencias.jsonl")
    elementos = (dimensoes.de_construtivos(dados["construtivos"], dados["crs"]["epsg"], dados.get("sondagens"))
                 if dados.get("construtivos") else []) + dimensoes.de_declarados(cfg.get("elementos_declarados"))
    tabelas = {"fatos": consolidar(evs), "cobertura": cobertura(evs), "associados": associados_x_edital(evs),
               "dimensoes": dimensoes.tabela(elementos)}
    for nome, df in tabelas.items():
        df.drop(columns=[c for c in ("afirmacoes",) if c in df]).to_csv(out / f"{nome}.csv", sep=";", decimal=",",
                                                                       encoding="utf-8-sig", index=False)
    fatos = tabelas["fatos"]
    log(f"  evidências: {len(evs)} · fatos {len(fatos)} · conflitos {int((fatos['status'] == 'conflito').sum())}")
    return {"n_evidencias": len(evs), **{k: _registros(df) for k, df in tabelas.items()}}


def _registros(df: pd.DataFrame) -> list[dict]:
    """Linhas para o dados.json do HTML: NaN vira null (NaN não é JSON)."""
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


def metadados() -> dict:
    """Rastreabilidade do método e das regras declaradas (regra 9 do estilo)."""
    return {
        "modulo": "evidencias",
        "descricao": "loop de evidências da EAP: texto, planilha + cadastro de materiais, pranchas medidas, IA com "
                     "citação conferida e decisões; fatos com convergência e conflito, cobertura projeto × edital",
        "funcoes": ["buscar_texto", "de_planilha", "de_quantificacao", "de_obras_lineares", "de_obras_lineares_mos", "conferir_citacao", "decisao", "consolidar",
                    "cobertura", "associados_x_edital", "catalogo_por_item", "loop", "etapa", "metadados"],
        "bibliografia": [],
        "premissas": [{"aplicacao": {"classificar": ["eap_geral.jsonl", "servicos.jsonl", "sinonimos.json"],
                                     "loop": ["servicos_associados.jsonl", "dimensoes.json"]},
                       "fonte": eap.REGRAS["metadata"]["fonte"], "estado": "premissa"}],
        "ultima_revisao": eap.REGRAS["metadata"]["data_referencia"],
    }
