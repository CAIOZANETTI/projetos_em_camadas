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

import argparse
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


def _id_da_evidencia(campos: dict) -> str:
    """Id estável (hash) de documento, localizador, método, código, serviço, trecho, unidade, valor e autor."""
    valor = campos.get("valor")
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            valor = float(valor)                                                       # 250 e 250.0 são o mesmo id
        except OverflowError:
            pass                                                                       # inteiro gigante: fica como está
    chaves = ("documento", "localizador", "metodo", "codigo", "servico", "trecho", "unidade", "valor", "autor")
    chave = json.dumps([{**campos, "valor": valor}.get(k) for k in chaves]
                       + ([campos.get("parcela")] if campos.get("metodo") == "ia" else []), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(chave.encode(), usedforsecurity=False).hexdigest()[:16]   # id, não segurança


def evidencia(**campos) -> dict:
    """Evidência com id estável (hash) e conferida contra o schema; levanta ValueError se não passa."""
    ev = {"id": _id_da_evidencia(campos), **campos}
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


# Conferência da citação de IA: o trecho, o par (valor, unidade) e o item têm de estar na MESMA linha do documento -------
LIMITE_DO_VALOR = 1e12       # |valor| acima disso é erro de digitação (ou ataque), não quantidade de obra
PALAVRAS_ATE_O_ITEM = 8     # número e unidade valem para o item se o termo dele está a no máximo 8 palavras, na linha
_ASPAS_E_TRACOS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                                 "–": "-", "—": "-", "−": "-"})
_UNIDADES_RE = "|".join(re.escape(g) for g in sorted(vocabulario.GRAFIAS, key=len, reverse=True))
_NUMERO_INTEIRO = vocabulario.NUMERO + r"(?![\d]|[.,]\d)"
_NAO_E_NUMERO = r"(?<![\d.,ØA-Z])(?<![A-Z]-)"      # "DN150", "C30", "CA-50" não são quantidades
_NUMERO_ANTES_DA_UNIDADE = re.compile(_NAO_E_NUMERO + _NUMERO_INTEIRO + r"\s*(" + _UNIDADES_RE + r")(?![A-Z0-9])")
_UNIDADE_ANTES_DO_NUMERO = re.compile(r"(?<![A-Z0-9])(" + _UNIDADES_RE + r")\s*[:|-]*\s*" + _NAO_E_NUMERO + _NUMERO_INTEIRO)
_NUMERO_ANTES_DO_TERMO = re.compile(_NAO_E_NUMERO + _NUMERO_INTEIRO + r"\s*(?:\([^)]*\)\s*)?(?:[A-Z]+\s+){0,2}$")


def _linhas_normalizadas(texto) -> list[str]:
    """Linhas não vazias do texto, normalizadas (maiúsculas, sem acento, aspas e travessões unificados); o hífen de fim
    de linha ('esta-' + 'cas') é desfeito antes."""
    t = str(texto or "").translate(_ASPAS_E_TRACOS)
    t = re.sub(r"(?<=[A-Za-zÀ-ÿ])-[ \t]*\r?\n[ \t]*(?=[A-Za-zÀ-ÿ])", "", t)
    return [n for n in (normalizar(linha) for linha in t.splitlines()) if n]


def _item_do_codigo(codigo) -> dict | None:
    """Item da EAP geral do código ('U1.*.GEO.FUN.EST' → GEO.FUN.EST); '*' só vale em unidade e sistema."""
    partes = codigo.split(".") if isinstance(codigo, str) else []
    return None if len(partes) < 3 or "*" in partes[2:] else eap.itens().get(".".join(partes[2:]))


def _unidades_do_item(item: dict, servico: str = "") -> list[str]:
    """Unidades aceitas: as do serviço, se houver; senão as dos serviços e das medições do item (sem nenhuma, todas)."""
    por_id = {s["id"]: s for s in SERVICOS}
    if servico:
        return list(por_id[servico]["unidades"])
    unidades = [u for s in item["servicos"] if s in por_id for u in por_id[s]["unidades"]] \
        + [m["unidade"] for m in item["medicoes"]]
    return list(dict.fromkeys(unidades)) or list(vocabulario.REGRAS["unidades"])


def _paginas_normalizadas(paginas: list[str]) -> list[str]:
    """Texto de cada página normalizado, uma linha por linha do documento: feito uma vez por documento."""
    return ["\n".join(_linhas_normalizadas(p)) for p in paginas]


def _termos_da_linha(linha: str) -> list[tuple[int, int, str]]:
    """(início, fim, código do item) de todo termo de item da EAP geral que aparece na linha normalizada."""
    return [(t.start(), t.end(), it["codigo"]) for it in eap.itens().values() for t in re.finditer(it["termos"], linha)]


def _pares_da_linha(linha: str, termos: list[tuple[int, int, str]]) -> tuple[list[tuple], set]:
    """Todos os pares (número, unidade, posição, item) que uma linha normalizada afirma, e os termos que um número já
    tomou para si. Pares: 'número unidade' (20 m²), 'unidade número' (m³ 1.250,50; un - 250) e 'número termo de item'
    (250 estacas, 250 (duzentas) estacas → un, do item do termo). O par número + termo não vale se entre os dois há uma
    unidade ('12 m de estaca' é 12 m; 'un 250 Bloco' é a quantidade da linha anterior) nem se outro termo de item está mais perto do número. Cada par também aparece
    convertido (12 t → 12000 kg). O número é um token inteiro: o 2 de M2, o 50 de CA-50, o 5 de 12,5 e o 250 de 1.250
    não contam."""
    pares = [(numero_br(m[1]), vocabulario.GRAFIAS[m[2]], m.span(), None) for m in _NUMERO_ANTES_DA_UNIDADE.finditer(linha)]
    pares += [(numero_br(m[2]), vocabulario.GRAFIAS[m[1]], m.span(), None) for m in _UNIDADE_ANTES_DO_NUMERO.finditer(linha)]
    donos, depois_de_unidade = set(), {m.start(2) for m in _UNIDADE_ANTES_DO_NUMERO.finditer(linha)}
    for ini, fim, codigo in termos:
        antes = _NUMERO_ANTES_DO_TERMO.search(linha[:ini])
        if not antes or antes.start(1) in depois_de_unidade or any(p in vocabulario.GRAFIAS for p in re.findall(r"[A-Z0-9]+", linha[antes.end(1):ini])):
            continue
        if any(antes.end(1) <= i2 < ini or (i2 == ini and c2 != codigo) for i2, _, c2 in termos):
            continue
        pares.append((numero_br(antes[1]), "un", (antes.start(), fim), codigo))
        donos.add((ini, fim, codigo))
    return pares + [(*vocabulario.converter(n, u), pos, via) for n, u, pos, via in pares
                    if u in vocabulario.REGRAS["conversoes"]], donos


def _situacao_do_item(linha: str, item: dict, termos: list, donos: set, posicao: tuple[int, int] | None = None) -> str:
    """'citado', 'ausente' ou 'outro' (o número pertence a outro item). O item é citado se o termo dele (ou um sinônimo)
    está na linha; dado o número, o termo livre dele tem de estar a no máximo PALAVRAS_ATE_O_ITEM palavras e ser o termo
    de item mais próximo (empate = outro). Termo que outro número já tomou ('2 estacas') não conta."""
    meus = [t for t in termos if t[2] == item["codigo"]]
    if not meus:
        return "citado" if re.search(item["termos"], preparar(linha)[1]) else "ausente"
    if posicao is None:
        return "citado"
    ini, fim = posicao
    livres = [t for t in termos if t not in donos]
    meus_livres, outros = [t for t in livres if t[2] == item["codigo"]], [t for t in livres if t[2] != item["codigo"]]

    def distancia(t) -> int:
        return max(0, t[0] - fim, ini - t[1])

    def palavras(t) -> int:
        return len((linha[t[1]:ini] if t[1] <= ini else linha[fim:t[0]] if fim <= t[0] else "").split())
    candidatos = meus_livres or ([] if outros else meus)       # o termo já tomado por outro número só serve sem rival
    if not candidatos:
        return "outro" if outros else "ausente"
    perto = [t for t in candidatos if palavras(t) <= PALAVRAS_ATE_O_ITEM]
    if not perto:
        return "ausente"
    return "outro" if outros and min(map(distancia, outros)) <= min(map(distancia, perto)) else "citado"


def _confere_fragmento(fragmento: str, valor, unidade: str | None, item: dict) -> tuple[bool, str]:
    """(o par existe na linha, situação do item: 'citado', 'ausente' ou 'outro'). Sem valor (menção), só o item."""
    linha = preparar(fragmento)[0]
    termos = _termos_da_linha(linha)
    pares, donos = _pares_da_linha(linha, termos)
    if valor is None:
        return True, _situacao_do_item(linha, item, termos, donos)
    achados = [(pos, via) for n, u, pos, via in pares if abs(n - valor) < 1e-9 and u == unidade]
    situacoes = [(("citado" if via == item["codigo"] else "outro"
                   if _situacao_do_item(linha, item, termos, donos) == "citado" else "ausente")
                  if via else _situacao_do_item(linha, item, termos, donos, pos)) for pos, via in achados]
    return bool(achados), "citado" if "citado" in situacoes else "outro" if "outro" in situacoes else "ausente"


def _achar(padrao: str, tokens: list[str], normalizadas: list[str], pagina: int | None) -> dict[int, list]:
    """Casamentos do trecho por página (1 = primeira). Com página citada, olha só ela se o trecho estiver lá; as
    páginas sem todas as palavras do trecho nem passam pela regex."""
    def procurar(n: int) -> list:
        texto = normalizadas[n - 1]
        return list(re.finditer(padrao, texto)) if all(t in texto for t in tokens) else []
    if pagina and 1 <= pagina <= len(normalizadas) and (achou := procurar(pagina)):
        return {pagina: achou}
    return {n: achou for n in range(1, len(normalizadas) + 1) if (achou := procurar(n))}


def conferir_citacao(ev: dict, paginas: list[str], normalizadas: list[str] | None = None) -> dict:
    """Evidência de IA conferida contra as páginas do documento (`normalizadas`: o `_paginas_normalizadas` delas, se já
    feito). O trecho (3 palavras ou 15 caracteres e uma letra) tem de estar numa página, com fronteira de palavra e de
    número ('250 estacas' não está em '1250', '1 250' nem '1.250 estacas'); pode atravessar linhas, nunca páginas. Com
    valor, o par (valor, unidade) e o termo do item do código têm de vir da MESMA linha do trecho (`_confere_fragmento`),
    e o item tem de ser o termo mais próximo do número; sem valor (menção), o item tem de ser citado. Se o localizador
    diz 'p. N' ou 'pág. N' (índice da página no PDF), o trecho tem de estar na página N."""
    normalizadas = _paginas_normalizadas(paginas) if normalizadas is None else normalizadas
    trecho = " ".join(_linhas_normalizadas(ev.get("trecho", "")))
    valor, unidade, item = ev.get("valor"), ev.get("unidade"), _item_do_codigo(ev.get("codigo"))
    cita = re.search(r"\b(?:PAG|P)\.?\s*(\d+)", normalizar(ev.get("localizador", "")))
    tokens = trecho.split()
    curto = not (re.search("[A-Z]", trecho) and (len(tokens) >= 3 or len(trecho) >= 15))
    padrao = (r"(?<![A-Z0-9])(?<![0-9][.,])" + (r"(?<!(?<![A-Z])[0-9] )" if trecho[:1].isdigit() else "")   # "1 250"; mas "M3 120" vale
              + r"[ \n]+".join(map(re.escape, tokens)) + r"(?![A-Z0-9])(?![.,][0-9])")
    achados = {} if curto else _achar(padrao, tokens, normalizadas, int(cita[1]) if cita else None)
    if curto:
        status = "trecho curto demais"
    elif not achados:
        status = "trecho não encontrado no documento"
    elif cita and int(cita[1]) not in achados:
        status = "página citada não contém o trecho"
    elif item is None:
        status = "código sem item na EAP geral"
    elif valor is not None and not (isinstance(valor, (int, float)) and not isinstance(valor, bool)
                                    and abs(valor) <= LIMITE_DO_VALOR):
        status = "valor não está no trecho"
    else:
        fragmentos = dict.fromkeys(f for ms in achados.values() for m in ms for f in m.group().split("\n"))
        pares = []
        for fragmento in fragmentos:                   # cada texto de linha só uma vez; para no primeiro que confere
            pares.append(_confere_fragmento(fragmento, valor, unidade, item))
            if pares[-1] == (True, "citado"):
                break
        status = ("valor não está no trecho" if valor is not None and not any(p for p, _ in pares)
                  else "conferida" if any(s == "citado" for _, s in pares)
                  else "número pertence a outro item" if any(s == "outro" for _, s in pares)
                  else "item não citado no trecho")
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
        if doc.startswith("ia:"):         # a mesma frase em outra página é total repetido, não outra parcela
            parcelas = list({" ".join(_linhas_normalizadas(e["trecho"])): e for e in parcelas}.values())
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


def _fonte(documento: str) -> str:
    """Documento de origem de uma afirmação: a leitura da IA (`ia:<arquivo>`) é do mesmo documento que o regex leu."""
    return documento.removeprefix("ia:")


def _grupos(afirm: list[dict], tol: float) -> list[list[dict]]:
    """Afirmações agrupadas por valor (diferença relativa até `tol`), do maior grupo para o menor."""
    grupos = []
    for a in sorted(afirm, key=lambda a: a["valor"]):
        if grupos and abs(a["valor"] - grupos[-1][0]["valor"]) <= tol * max(1.0, abs(grupos[-1][0]["valor"])):
            grupos[-1].append(a)
        else:
            grupos.append([a])
    return sorted(grupos, key=lambda g: -len({_fonte(a["documento"]) for a in g}))


def _fato(chave: tuple, evs: list[dict], mencoes: list[dict], tol: float) -> dict:
    """Status de um fato a partir das afirmações por documento (decisão à parte)."""
    decisoes = [e for e in evs if e["metodo"] == "decisao"]
    afirm = _afirmacoes([e for e in evs if e["metodo"] != "decisao"])
    grupos = _grupos(afirm, tol)
    valores = [a["valor"] for a in afirm]
    docs = {_fonte(a["documento"]) for a in afirm}
    if decisoes:
        status, valor = "decidido", decisoes[-1]["valor"]
    elif not afirm:
        status, valor = "só menção", None
    elif len(grupos) > 1:
        status, valor = "conflito", None
    else:
        status, valor = ("convergente" if len(docs) > 1 else "fonte única"), grupos[0][0]["valor"]
    return {"codigo": chave[0], "servico": chave[1], "unidade": chave[2], "status": status, "valor": valor,
            "forca": len({_fonte(a["documento"]) for a in grupos[0]}) if grupos else 0, "n_documentos": len(docs),
            "diferenca_pct": round(100 * (max(valores) - min(valores)) / max(abs(max(valores)), 1e-9), 1)
            if len(grupos) > 1 else 0.0,
            "afirmacoes": afirm, "mencoes": sorted({m["documento"]["id"] for m in mencoes}),
            "decisoes": [{"valor": d["valor"], "autor": d["autor"], "justificativa": d["justificativa"]} for d in decisoes]}


def _sem_ia_repetida(evs: list[dict]) -> list[dict]:
    """A mesma proposta de IA (mesmo id) conta uma vez; as outras fontes ficam como estão (duas parcelas iguais somam)."""
    vistos, saida = set(), []
    for e in evs:
        if e["metodo"] == "ia":
            if e["id"] in vistos:
                continue
            vistos.add(e["id"])
        saida.append(e)
    return saida


def consolidar(evs: list[dict], tol: float = 0.005) -> pd.DataFrame:
    """Fatos (código, serviço, unidade) com o status: convergente, fonte única, conflito, só menção ou decidido.
    IA só entra com citação conferida. Menção (sem número) reforça o fato mas não dá valor."""
    evs = _sem_ia_repetida(evs)
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
                     and (e["metodo"] != "ia" or e.get("citacao") == "conferida")
                     and e["codigo"].split(".")[0] in (uid.upper(), "*") and ".".join(e["codigo"].split(".")[2:]) == codigo}
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
         extras: list[dict] | None = None, recusadas_ia: list[dict] | None = None) -> list[dict]:
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
    normalizadas = {n: _paginas_normalizadas(p) for n, p in paginas.items()} if ia else {}
    for proposta in ia or []:                                  # nunca confia no selo que veio no arquivo
        conferida = _conferir_ia(proposta, paginas, normalizadas) if isinstance(proposta, dict) else \
            {"citacao": "schema inválido: a linha não é um objeto JSON", "proposta": proposta}
        if conferida["citacao"].startswith("schema inválido"):    # sem estrutura para entrar nas tabelas: só se informa
            (recusadas_ia if recusadas_ia is not None else []).append({"motivo": conferida["citacao"], "evidencia": conferida})
        else:
            evs.append(conferida)
    evs += list(decisoes or [])
    evs = _sem_ia_repetida(evs)
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


def _ler_ia(caminho: str | Path) -> list:
    """Linhas do JSONL de IA como estão; a que não é JSON vira texto (o `loop` a recusa), sem derrubar a leitura."""
    saida = []
    for linha in Path(caminho).read_text(encoding="utf-8").splitlines():
        if linha.strip():
            try:
                saida.append(json.loads(linha))
            except ValueError:
                saida.append(linha)
    return saida


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
    extras = {k: (ler if k == "decisoes" else _ler_ia)(conf[k]) if conf.get(k) and Path(conf[k]).exists() else []
              for k in ("ia", "decisoes")}
    recusadas_ia = []
    evs = loop(_documentos(cfg, log), planilha, dados.get("construtivos"), dados["crs"]["epsg"],
               extras["ia"], extras["decisoes"], dados.get("sondagens"), cfg.get("elementos_declarados"),
               _obras_lineares_da_obra(cfg, dados.get("sondagens"), log), recusadas_ia)
    for r in recusadas_ia:
        log(f"  evidências: linha de IA recusada ({r['motivo']})")
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
    log(f"  evidências: {len(evs)} · fatos {len(fatos)} · conflitos {int((fatos['status'] == 'conflito').sum()) if len(fatos) else 0}")
    return {"n_evidencias": len(evs), **{k: _registros(df) for k, df in tabelas.items()}}


def _registros(df: pd.DataFrame) -> list[dict]:
    """Linhas para o dados.json do HTML: NaN vira null (NaN não é JSON)."""
    return df.astype(object).where(pd.notna(df), None).to_dict("records")


# Leitura por IA: o roteiro diz o que procurar, a IA propõe, o código confere ------------------------------------------------
def _termos_legiveis(regex: str) -> list[str]:
    """Alternativas de uma regex de termos da EAP escritas como a gente procura no texto (sem lookahead, `\\b` nem `?`)."""
    sem_olhar = re.sub(r"\(\?[!=<][^()]*\)", "", regex)
    sem_opcionais = re.sub(r"\([^()]*\)\?|\\b|\\", "", sem_olhar)
    alternativas = re.sub(r"\.\?|\.\{[^}]*\}|\.\*", " ", sem_opcionais).replace("?", "")
    saida = []
    for alt in alternativas.split("|"):
        alt = re.sub(r"\(([^()|]*)[^()]*\)", r"\1", alt).strip().lower()
        if len(alt) > 2 and not re.search(r"[\[\]*+{}^$()]", alt) and alt not in saida:
            saida.append(alt)
    return saida


def _sinonimos_do_item(termos: str) -> list[str]:
    """Termo canônico (e variantes) de sinonimos.json que o item reconhece: o que o documento pode usar no lugar dele."""
    saida = []
    for canonico, variantes in vocabulario.REGRAS["sinonimos"].items():
        if re.search(termos, canonico):
            saida += [t.lower() for t in [canonico, *(v.replace("?", "") for v in variantes)] if t.lower() not in saida]
    return saida


def roteiro(escopo: str | None = None, obra: str | None = None) -> list[dict]:
    """O que a IA procura em cada documento: por item da EAP geral (filtrado por escopo 'agua'|'esgoto' e tipo de
    obra 'localizada'|'linear'), código, nome, termos de busca (os do item e os sinônimos), serviços admitidos com
    suas unidades e as unidades aceitas (as dos serviços e das medições; sem nenhuma, todas as do vocabulário)."""
    por_id = {s["id"]: s for s in SERVICOS}
    itens = []
    for it in eap.itens().values():
        if (escopo and escopo not in it["escopo"]) or (obra and obra not in it["obra"]):
            continue
        servicos = [{"id": s, "nome": por_id[s]["nome"], "unidades": por_id[s]["unidades"]} for s in it["servicos"] if s in por_id]
        termos = list(dict.fromkeys(_termos_legiveis(it["termos"]) + _sinonimos_do_item(it["termos"])))
        itens.append({"codigo": it["codigo"], "nome": it["nome"], "escopo": it["escopo"], "obra": it["obra"],
                      "termos": termos, "servicos": servicos, "unidades": _unidades_do_item(it)})
    return itens


def roteiro_md(itens: list[dict], escopo: str | None = None, obra: str | None = None) -> str:
    """Roteiro de leitura em Markdown, a partir de `roteiro()`: uma seção por item da EAP."""
    filtro = ", ".join(f"{k} = {v}" for k, v in (("escopo", escopo), ("obra", obra)) if v) or "sem filtro"
    linhas = ["# Roteiro de leitura para a EAP", "",
              (f"Filtro: {filtro}. Itens: {len(itens)}. Para cada item abaixo, procure o termo, os sinônimos e os serviços "
               "no documento e escreva uma evidência com o trecho copiado literalmente (skill `eap-evidencias`)."), "",
              "Unidades aceitas: " + ", ".join(f"`{u}`" for u in vocabulario.REGRAS["unidades"]) + ".", ""]
    for it in itens:
        linhas += [f"## {it['codigo']} · {it['nome']}", "",
                   f"- Termos de busca: {', '.join(it['termos']) or '—'}",
                   f"- Unidades do item: {', '.join(f'`{u}`' for u in it['unidades'])}"]
        linhas += [f"- Serviço `{s['id']}` ({s['nome']}): {', '.join(f'`{u}`' for u in s['unidades'])}" for s in it["servicos"]]
        linhas.append("")
    return "\n".join(linhas)


CAMPOS_DO_CODIGO = ("citacao", "derivada", "id", "autor", "justificativa")   # a IA não escreve: o código calcula


def _nome_do_documento(ev: dict) -> str:
    """Nome do arquivo citado em `documento.id` ('dados/x/memorial.pdf' e 'ia:memorial.pdf' → 'memorial.pdf')."""
    documento = ev.get("documento")
    return Path(str(documento.get("id") or "").removeprefix("ia:")).name if isinstance(documento, dict) else ""


def _sanear_ia(ev: dict) -> dict:
    """Proposta de IA sem os campos do código (selo `citacao`, `derivada`, `id`, `autor`, `justificativa`), com `regra`
    padrão, o documento como fonte própria (`ia:<arquivo>`, não soma com a leitura do regex) e o `id` recalculado."""
    ev = {k: v for k, v in ev.items() if k not in CAMPOS_DO_CODIGO}
    ev["regra"] = ev.get("regra") or "leitura por IA"
    if _nome_do_documento(ev):
        ev["documento"] = {"id": f"ia:{_nome_do_documento(ev)}", "tipo": ev["documento"].get("tipo"),
                           "nome": _nome_do_documento(ev)}
    return {"id": _id_da_evidencia(ev), **ev}


def _conferir_ia(ev: dict, documentos: dict[str, list[str]], normalizadas: dict[str, list[str]] | None = None) -> dict:
    """Proposta de IA saneada e conferida: `citacao` é 'conferida' ou o motivo da recusa (schema inválido, documento
    não fornecido, trecho curto demais ou não encontrado, valor fora do trecho). Serve ao `conferir` e ao build."""
    ev = _sanear_ia(ev)
    problemas = _problemas_ia(ev)
    if problemas:
        return {**ev, "citacao": "schema inválido: " + "; ".join(problemas)}
    nome = _nome_do_documento(ev)
    if nome not in documentos:
        return {**ev, "citacao": f"documento não fornecido: {nome}"}
    conferida = conferir_citacao(ev, documentos[nome], (normalizadas or {}).get(nome))
    if conferida["citacao"] == "conferida" and conferida.get("valor") is not None:      # a mesma unidade do regex (t → kg)
        valor, unidade = vocabulario.converter(float(conferida["valor"]), conferida["unidade"])
        conferida = {**conferida, "valor": valor, "unidade": unidade}
        conferida["id"] = _id_da_evidencia(conferida)
    return conferida


def _problemas_ia(ev: dict) -> list[str]:
    """Além do schema: uma proposta de IA tem método e tipo de documento `ia`; código com item da EAP geral (`*` só em
    unidade e sistema); serviço que o item admite; escopo do enum; valor numérico não negativo com unidade do vocabulário
    e do item (ou do serviço); `parcela` booleana. Nunca levanta exceção: linha malformada vira lista de problemas."""
    if not isinstance(ev.get("documento"), dict) or not ev["documento"].get("id"):
        return ["documento tem de ser um objeto com id (nome do arquivo) e tipo"]
    tipos = [f"'{k}' tem de ser texto" for k in ("codigo", "servico", "localizador", "trecho", "regra")
             if k in ev and not isinstance(ev[k], str)]
    if tipos:
        return tipos
    problemas = validar_evidencia(ev)
    if ev.get("metodo") != "ia" or ev["documento"].get("tipo") != "ia":
        problemas.append("método e documento.tipo têm de ser 'ia'")
    valor, unidade, servico = ev.get("valor"), ev.get("unidade"), ev.get("servico") or ""
    item = _item_do_codigo(ev.get("codigo")) if "codigo" in ev else None
    if "codigo" in ev and item is None and not problemas:
        problemas.append(f"código '{ev['codigo']}' sem item na EAP geral ('*' só vale em unidade e sistema)")
    if item and servico and (servico not in item["servicos"] or servico not in {x["id"] for x in SERVICOS}):
        problemas.append(f"serviço '{servico}' não é admitido pelo item {item['codigo']}")
    if ev.get("escopo") not in SCHEMA["properties"]["escopo"]["enum"]:
        problemas.append(f"escopo '{ev.get('escopo')}' inválido")
    if valor is None and unidade is not None and (not isinstance(unidade, str) or unidade not in vocabulario.REGRAS["unidades"]):
        problemas.append(f"unidade '{unidade}' fora do vocabulário ({', '.join(vocabulario.REGRAS['unidades'])})")
    if valor is not None and (isinstance(valor, bool) or not isinstance(valor, (int, float))):
        problemas.append(f"valor '{str(valor)[:30]}' não é número")
    elif valor is not None and not abs(valor) <= LIMITE_DO_VALOR:
        problemas.append(f"valor fora do intervalo (|valor| até {LIMITE_DO_VALOR:g})")
    elif valor is not None and (not isinstance(unidade, str) or unidade not in vocabulario.REGRAS["unidades"]):
        problemas.append(f"unidade '{unidade}' fora do vocabulário ({', '.join(vocabulario.REGRAS['unidades'])})")
    elif valor is not None and valor < 0:
        problemas.append("valor negativo")
    elif valor is not None and item and not (servico and servico not in item["servicos"]) \
            and unidade not in _unidades_do_item(item, servico):
        problemas.append(f"unidade '{unidade}' não é aceita por {item['codigo']}"
                         + (f" / {servico}" if servico else "") + f" (aceitas: {', '.join(_unidades_do_item(item, servico))})")
    if not isinstance(ev.get("parcela"), bool):
        problemas.append("'parcela' tem de ser true ou false")
    if not str(ev.get("trecho") or "").strip():
        problemas.append("trecho vazio")
    return problemas


def conferir_arquivo(linhas: list, documentos: dict[str, list[str]]) -> tuple[list[dict], list[dict]]:
    """Confere as evidências propostas pela IA (linhas JSON ou dicts) contra o texto dos documentos (nome do arquivo →
    páginas). Devolve (aceitas, recusadas): as aceitas levam `citacao: "conferida"`; cada recusada é
    {linha, motivo, evidencia}. Os campos do código (`citacao`, `derivada`, `id`, `autor`, `justificativa`) que vierem
    na proposta são descartados e o `id` é sempre recalculado (`_sanear_ia`)."""
    aceitas, recusadas = [], []
    normalizadas = {n: _paginas_normalizadas(p) for n, p in documentos.items()}        # uma vez por documento
    for n, bruta in enumerate((x for x in linhas if isinstance(x, dict) or str(x).strip()), 1):
        try:
            ev = bruta if isinstance(bruta, dict) else json.loads(bruta)
            if not isinstance(ev, dict):
                raise TypeError("a linha não é um objeto JSON")
        except (ValueError, TypeError) as erro:
            recusadas.append({"linha": n, "motivo": f"schema inválido: JSON inválido: {erro}", "evidencia": str(bruta)[:200]})
            continue
        conferida = _conferir_ia(ev, documentos, normalizadas)
        if conferida["citacao"] == "conferida":
            aceitas.append(conferida)
        else:
            recusadas.append({"linha": n, "motivo": conferida["citacao"], "evidencia": conferida})
    return aceitas, recusadas


def _documentos_da_linha_de_comando(pdfs: list[str], textos: list[str], log=print) -> dict[str, list[str]]:
    """Nome do arquivo → páginas: PDF por página; texto puro por página separada por quebra de página (\\f)."""
    documentos = {}
    for caminho in pdfs + textos:
        arquivo = Path(caminho)
        if not arquivo.exists():
            log(f"  aviso: {caminho} não existe e será ignorado")
        elif caminho in pdfs:
            documentos[arquivo.name] = paginas_pdf(arquivo)
        else:
            documentos[arquivo.name] = arquivo.read_text(encoding="utf-8").split("\f")
    return documentos


def _comando_conferir(args, log=print) -> int:
    """`conferir`: relatório de aceitas e recusadas; grava só as aceitas em `--saida`. Saída 2 sem o arquivo de entrada."""
    entrada = Path(args.ia)
    if not entrada.exists():
        log(f"erro: o arquivo {entrada} não existe")
        return 2
    documentos = _documentos_da_linha_de_comando(args.pdf, args.texto, log)
    aceitas, recusadas = conferir_arquivo(entrada.read_text(encoding="utf-8").splitlines(), documentos)
    log(f"Conferência de {entrada.name}: {len(aceitas)} aceitas, {len(recusadas)} recusadas "
        f"({len(documentos)} documentos fornecidos)")
    for r in recusadas:
        log(f"  recusada (linha {r['linha']}): {r['motivo']}")
    if args.saida:
        gravar(aceitas, args.saida)
        log(f"  {len(aceitas)} aceitas gravadas em {args.saida}")
    return 0


def _comando_roteiro(args, log=print) -> int:
    """`roteiro`: imprime o Markdown ou grava em `--saida`."""
    texto = roteiro_md(roteiro(args.escopo, args.obra), args.escopo, args.obra)
    if args.saida:
        Path(args.saida).write_text(texto + "\n", encoding="utf-8")
        log(f"roteiro gravado em {args.saida}")
    else:
        log(texto)
    return 0


def main(argv: list[str] | None = None) -> int:
    """`python -m camadas.evidencias roteiro|conferir …` (ver --help de cada comando)."""
    ap = argparse.ArgumentParser(prog="python -m camadas.evidencias",
                                 description="Leitura de documentos por IA com citação conferida pelo código")
    sub = ap.add_subparsers(dest="comando", required=True)
    r = sub.add_parser("roteiro", help="o que procurar em cada documento, por item da EAP")
    r.add_argument("--escopo", choices=["agua", "esgoto"])
    r.add_argument("--obra", choices=["localizada", "linear"])
    r.add_argument("--saida", help="grava o Markdown neste arquivo em vez de imprimir")
    r.set_defaults(funcao=_comando_roteiro)
    c = sub.add_parser("conferir", help="confere as evidências propostas pela IA contra os documentos")
    c.add_argument("ia", help="JSONL com as evidências propostas (uma por linha)")
    c.add_argument("--pdf", action="append", default=[], help="PDF do documento (repetível)")
    c.add_argument("--texto", action="append", default=[], help="texto puro do documento (repetível)")
    c.add_argument("--saida", help="grava só as aceitas neste JSONL")
    c.set_defaults(funcao=_comando_conferir)
    args = ap.parse_args(argv)
    return args.funcao(args)



def metadados() -> dict:
    """Rastreabilidade do método e das regras declaradas (regra 9 do estilo)."""
    return {
        "modulo": "evidencias",
        "descricao": "loop de evidências da EAP: texto, planilha + cadastro de materiais, pranchas medidas, IA com "
                     "citação conferida e decisões; fatos com convergência e conflito, cobertura projeto × edital",
        "funcoes": ["roteiro", "roteiro_md", "conferir_arquivo", "buscar_texto", "de_planilha", "de_quantificacao", "de_obras_lineares", "de_obras_lineares_mos", "conferir_citacao", "decisao", "consolidar",
                    "cobertura", "associados_x_edital", "catalogo_por_item", "loop", "etapa", "metadados"],
        "bibliografia": [],
        "premissas": [{"aplicacao": {"classificar": ["eap_geral.jsonl", "servicos.jsonl", "sinonimos.json"],
                                     "loop": ["servicos_associados.jsonl", "dimensoes.json"]},
                       "fonte": eap.REGRAS["metadata"]["fonte"], "estado": "premissa"}],
        "ultima_revisao": eap.REGRAS["metadata"]["data_referencia"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
