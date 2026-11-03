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
import csv
import datetime
import decimal
import hashlib
import importlib.util
import io
import itertools
import json
import math
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from . import associados, calibracao, dimensoes, eap, vocabulario
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
    nome e, se souber, unidade ('U1'), sistema, obra e escopo; o que não souber fica '*'. Em planilha, o localizador é
    {aba, linha} e a quantidade vem das colunas Un/Qtd (ou de uma célula só), nunca de células diferentes."""
    unidade, sistema = documento.get("unidade", "*"), documento.get("sistema", "*")
    termos_dos_itens = [it["termos"] for it in eap.itens().values()]
    saida = []
    for np_, pagina in enumerate(paginas, 1):
        planilha = isinstance(pagina, PaginaPlanilha)
        for nl, bruta in enumerate(str(pagina).splitlines(), 1):
            medir, linha = preparar(bruta)
            item, servico, regra = classificar(linha, documento.get("obra"), documento.get("escopo"))
            if item is None or item.endswith(".*"):     # serviço sem item: '*' só vale em unidade e sistema
                continue
            valor, un = (_quantidade_da_planilha(pagina, nl - 1, termos_dos_itens) if planilha
                         else quantidade(medir, termos_dos_itens))
            local = {"aba": pagina.aba, "linha": pagina.linhas[nl - 1]} if planilha else f"p. {np_}, linha {nl}"
            saida.append(evidencia(codigo=_codigo(unidade, sistema, item), servico=servico, unidade=un, valor=valor,
                                   parcela=False, documento=_doc(documento), localizador=local,
                                   trecho=bruta.strip(), metodo="regex", regra=regra,
                                   escopo=documento.get("escopo")))
    return saida


def _quantidade_da_planilha(pagina: PaginaPlanilha, indice: int, termos: list[str]) -> tuple[float | None, str | None]:
    """(valor, unidade) da linha de planilha: das colunas Un/Qtd do cabeçalho; sem cabeçalho, só de uma célula (nunca
    de células diferentes). Célula marcada ou sem quantidade: (None, None), e a linha fica como menção."""
    celulas = pagina.celulas[indice]
    if any(c.problema for c in celulas):
        return None, None
    if cabecalho := pagina.cabecalhos[indice]:
        por_coluna = {c.coluna: c for c in celulas}
        qtd, un = por_coluna.get(cabecalho[1]), por_coluna.get(cabecalho[0])
        unidade = unidade_medida(un.texto) if un else None
        return vocabulario.converter(qtd.numero, unidade) if qtd and qtd.numero is not None and unidade else (None, None)
    achados = (quantidade(preparar(c.texto)[0], termos) for c in celulas)
    return next((a for a in achados if a[0] is not None), (None, None))


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
        if item is None or item.endswith(".*"):     # serviço sem item: '*' só vale em unidade e sistema
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
LINHAS_DO_BLOCO = 3         # bloco de linha de tabela: até 3 linhas seguidas do trecho, o par (valor, unidade) na última
_BRANCO = "\f"              # marca, na página normalizada, de uma ou mais linhas em branco entre duas linhas com texto
_MINUSCULA = "\v"           # marca, no início da linha da página normalizada, de linha que começava em minúscula
_CONECTIVOS = {"E", "OU", "COM", "SEM", "PARA", "DE", "DO", "DA", "EM", "INCLUSIVE", "INCLUSO", "INCLUINDO",
               "CONFORME"}   # início de linha que continua a descrição da anterior, mesmo escrito em maiúscula
_ROTULO_DE_QUANTIDADE = re.compile(r"\b(?:QUANTIDADE|QUANT|QTDE|QTD|QT)\b")   # 'TOTAL' não é rótulo: é outra grandeza
_ASPAS_E_TRACOS = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'",
                                 "–": "-", "—": "-", "−": "-"})
_UNIDADES_RE = "|".join(re.escape(g) for g in sorted(vocabulario.GRAFIAS, key=len, reverse=True))
_NUMERO_INTEIRO = vocabulario.NUMERO_INTEIRO
_NAO_E_NUMERO = vocabulario.NAO_E_NUMERO      # mesma regra do regex: "DN150", "C30", "CA-50" não são quantidades
_NUMERO_ANTES_DA_UNIDADE = re.compile(_NAO_E_NUMERO + _NUMERO_INTEIRO + r"\s*(" + _UNIDADES_RE + r")(?![A-Z0-9])")
_UNIDADE_ANTES_DO_NUMERO = re.compile(r"(?<![A-Z0-9])(" + _UNIDADES_RE + r")\s*[:|-]*\s*" + _NAO_E_NUMERO + _NUMERO_INTEIRO)
_DIMENSAO = vocabulario.DIMENSAO
_NUMERO_ANTES_DO_TERMO = re.compile(_NAO_E_NUMERO + _NUMERO_INTEIRO + r"\s*(?:\([^)]*\)\s*)?(?:[A-Z]+\s+){0,2}$")


def _linhas_normalizadas(texto, marcar_brancos: bool = False) -> list[str]:
    """Linhas não vazias do texto, normalizadas (maiúsculas, sem acento, aspas e travessões unificados); o hífen de fim
    de linha ('esta-' + 'cas') é desfeito antes. Com `marcar_brancos`, onde havia linha em branco entre duas linhas com
    texto entra a marca `_BRANCO` (o bloco de tabela não passa por ela); quebra de página (`\\f`) no meio do texto vale
    como linha em branco. Também com `marcar_brancos`, a linha que começava em minúscula leva `_MINUSCULA` na frente."""
    t = str(texto or "").translate(_ASPAS_E_TRACOS).replace("\f", "\n\n")
    t = re.sub(r"(?<=[A-Za-zÀ-ÿ])-[ \t]*\r?\n[ \t]*(?=[A-Za-zÀ-ÿ])", "", t)
    linhas, em_branco = [], False
    for original in t.splitlines():
        n = normalizar(original)
        if not n:
            em_branco = bool(linhas)
            continue
        if em_branco and marcar_brancos:
            linhas.append(_BRANCO)
        linhas.append(_MINUSCULA + n if marcar_brancos and original.lstrip()[:1].islower() else n)
        em_branco = False
    return linhas


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


def _pagina_normalizada(pagina: str) -> str:
    """Página normalizada. A de planilha mantém uma linha para cada linha de texto (sem desfazer hífen de fim de linha),
    para o mapa linha de texto → linha da planilha continuar valendo; a célula marcada (fórmula sem valor, número fora
    da faixa) não entra no texto de busca, e a linha fica recusada na conferência."""
    if not isinstance(pagina, PaginaPlanilha):
        return "\n".join(_linhas_normalizadas(pagina, marcar_brancos=True))
    return "\n".join((_MINUSCULA if cs[0].texto[:1].islower() else "")
                      + " | ".join(_norm_celula(c.texto) for c in cs if not c.problema) for cs in pagina.celulas)


def _paginas_normalizadas(paginas: list[str]) -> list[str]:
    """Texto de cada página normalizado, uma linha por linha do documento: feito uma vez por documento."""
    return [_pagina_normalizada(p) for p in paginas]


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


def _situacao_do_item(linha: str, item: dict, termos: list, donos: set, posicao: tuple[int, int] | None = None,
                      isento_antes_de: int = 0) -> str:
    """'citado', 'ausente' ou 'outro' (o número pertence a outro item). O item é citado se o termo dele (ou um sinônimo)
    está na linha; dado o número, o termo livre dele tem de estar a no máximo PALAVRAS_ATE_O_ITEM palavras e ser o termo
    de item mais próximo (empate = outro). Termo que outro número já tomou ('2 estacas') não conta. Em bloco de tabela,
    `isento_antes_de`: termo que começa antes dessa posição (linha anterior do bloco) fica isento do limite de palavras."""
    meus = [t for t in termos if t[2] == item["codigo"]]
    if not meus:
        return "citado" if re.search(item["termos"], preparar(linha)[1]) else "ausente"
    if posicao is None:
        return "citado"
    return _situacao_pelo_numero(linha, item, termos, donos, posicao, isento_antes_de, meus)


def _situacao_pelo_numero(linha: str, item: dict, termos: list, donos: set, posicao: tuple[int, int],
                          isento_antes_de: int, meus: list) -> str:
    """Situação do item dado o número na `posicao`: só os termos livres contam (`meus` já tomados só servem sem rival),
    o do item tem de estar perto o bastante e não pode haver termo de outro item mais perto (ou à mesma distância)."""
    meus_livres, outros = _termos_livres(item, termos, donos)
    candidatos = meus_livres or ([] if outros else meus)       # o termo já tomado por outro número só serve sem rival
    if not candidatos:
        return "outro" if outros else "ausente"
    perto = [t for t in candidatos if t[0] < isento_antes_de or _palavras_ate_o_numero(linha, t, posicao) <= PALAVRAS_ATE_O_ITEM]
    if not perto:
        return "ausente"
    return "outro" if outros and _distancia_minima(outros, posicao) <= _distancia_minima(perto, posicao) else "citado"


def _termos_livres(item: dict, termos: list, donos: set) -> tuple[list, list]:
    """Termos que nenhum número tomou, separados em (do item, de outros itens)."""
    livres = [t for t in termos if t not in donos]
    return [t for t in livres if t[2] == item["codigo"]], [t for t in livres if t[2] != item["codigo"]]


def _distancia_minima(termos: list, posicao: tuple[int, int]) -> int:
    """Menor distância, em caracteres, entre os termos e o número na `posicao`."""
    return min(_distancia_ao_numero(t, posicao) for t in termos)


def _distancia_ao_numero(termo: tuple, posicao: tuple[int, int]) -> int:
    """Caracteres entre o termo (início, fim, código) e o número (início, fim); 0 se encostam ou se sobrepõem."""
    return max(0, termo[0] - posicao[1], posicao[0] - termo[1])


def _palavras_ate_o_numero(linha: str, termo: tuple, posicao: tuple[int, int]) -> int:
    """Palavras entre o termo e o número (0 se um contém o outro)."""
    ini, fim = posicao
    return len((linha[termo[1]:ini] if termo[1] <= ini else linha[fim:termo[0]] if fim <= termo[0] else "").split())


def _confere_fragmento(fragmento: str, valor, unidade: str | None, item: dict) -> tuple[bool, str]:
    """(o par existe na linha, situação do item: 'citado', 'ausente' ou 'outro'). Sem valor (menção), só o item."""
    return _confere_linha(preparar(fragmento)[0], valor, unidade, item)


def _confere_linha(linha: str, valor, unidade: str | None, item: dict, a_partir_de: int = 0,
                   isento: bool = False) -> tuple[bool, str]:
    """`_confere_fragmento` sobre a linha já preparada; só valem os pares que começam em `a_partir_de` ou depois, e
    `isento` libera os termos anteriores a `a_partir_de` do limite de palavras."""
    termos = _termos_da_linha(linha)
    pares, donos = _pares_da_linha(linha, termos)
    if valor is None:
        return True, _situacao_do_item(linha, item, termos, donos)
    achados = [(pos, via) for n, u, pos, via in pares if abs(n - valor) < 1e-9 and u == unidade and pos[0] >= a_partir_de]
    situacoes = [(("citado" if via == item["codigo"] else "outro"
                   if _situacao_do_item(linha, item, termos, donos) == "citado" else "ausente")
                  if via else _situacao_do_item(linha, item, termos, donos, pos, a_partir_de if isento else 0)) for pos, via in achados]
    return bool(achados), "citado" if "citado" in situacoes else "outro" if "outro" in situacoes else "ausente"


def _tem_quantidade(linha: str) -> bool:
    """A linha afirma alguma quantidade (número com unidade ou com termo de item)? Dimensão de especificação
    ('Ø40 cm', 'DN 150', 'diâmetro 40 cm') não conta; qualquer outro número com unidade ('12 m', 'un 30') conta."""
    sem_dimensao = _DIMENSAO.sub(" ", linha)
    return bool(_pares_da_linha(sem_dimensao, _termos_da_linha(sem_dimensao))[0])


def _continua_a_descricao(anterior: str, ultima: str, comeca_em_minuscula: bool) -> bool:
    """A linha continua a descrição da anterior se não tem descrição própria (só o par, rótulo de quantidade e
    separadores), ou se a anterior não termina em '.' ou ':' e ela começa em minúscula ou com conectivo
    ('inclusive⏎mobilização e desmobilização un 250'). Título, cabeçalho e outra linha de tabela não."""
    resto = _UNIDADE_ANTES_DO_NUMERO.sub(" ", _NUMERO_ANTES_DA_UNIDADE.sub(" ", ultima))
    resto = _ROTULO_DE_QUANTIDADE.sub(" ", resto)
    palavras = re.findall(r"[A-Z]+", resto)
    if not palavras:
        return True
    return not anterior.endswith((".", ":")) and (comeca_em_minuscula or palavras[0] in _CONECTIVOS)


def _confere_bloco(linhas: list[str], valor, unidade: str | None, item: dict) -> tuple[bool, str]:
    """Conferência por bloco de linha de tabela: as `linhas` inteiras da página (2 a LINHAS_DO_BLOCO, sem linha em
    branco entre elas) valem como uma linha só, desde que as anteriores à última não afirmem nenhuma quantidade. O par
    (valor, unidade) tem de começar na última linha; o termo do item pode estar em qualquer uma, e continua valendo o
    item mais próximo do número, sem o limite de 8 palavras para o termo de linha anterior. Toda linha depois da
    primeira tem de continuar a descrição da anterior (`_continua_a_descricao`): título, cabeçalho de seção ou de
    tabela e linha de outro item (que começam em maiúscula) nunca formam bloco com a linha de baixo."""
    minusculas = [linha.startswith(_MINUSCULA) for linha in linhas]
    preparadas = [preparar(linha.lstrip(_MINUSCULA))[0] for linha in linhas]
    if any(_tem_quantidade(p) for p in preparadas[:-1]):
        return False, "ausente"
    if not all(_continua_a_descricao(preparadas[k - 1], preparadas[k], minusculas[k]) for k in range(1, len(linhas))):
        return False, "ausente"
    return _confere_linha(" ".join(preparadas), valor, unidade, item, len(" ".join(preparadas[:-1])) + 1, True)


def _linhas_inteiras(texto: str, casamento: re.Match) -> str:
    """O casamento do trecho expandido até as linhas inteiras da página normalizada."""
    inicio = texto.rfind("\n", 0, casamento.start()) + 1
    fim = texto.find("\n", casamento.end())
    return texto[inicio:] if fim < 0 else texto[inicio:fim]


def _bloco_do_trecho(casado: str) -> list[str] | None:
    """Linhas (inteiras) do trecho como candidato a bloco: 2 a LINHAS_DO_BLOCO linhas e nenhuma marca de linha em branco."""
    linhas = casado.split("\n")
    return linhas if 2 <= len(linhas) <= LINHAS_DO_BLOCO and _BRANCO not in linhas else None


def _achar(padrao: str, tokens: list[str], normalizadas: list[str], pagina: int | None) -> dict[int, list]:
    """Casamentos do trecho por página (1 = primeira). Com página citada, olha só ela se o trecho estiver lá; as
    páginas sem todas as palavras do trecho nem passam pela regex."""
    def procurar(n: int) -> list:
        texto = normalizadas[n - 1]
        return list(re.finditer(padrao, texto)) if all(t in texto for t in tokens) else []
    if pagina and 1 <= pagina <= len(normalizadas) and (achou := procurar(pagina)):
        return {pagina: achou}
    return {n: achou for n in range(1, len(normalizadas) + 1) if (achou := procurar(n))}


def _padrao_do_trecho(trecho: str, tokens: list[str]) -> str:
    """Regex do trecho normalizado: palavras separadas por espaço ou quebra, com fronteira de palavra e de número."""
    return (r"(?<![A-Z0-9])(?<![0-9][.,])" + (r"(?<!(?<![A-Z])[0-9] )" if trecho[:1].isdigit() else "")   # "1 250"; mas "M3 120" vale
            + r"[ \n\f\v]+".join(map(re.escape, tokens)) + r"(?![A-Z0-9])(?![.,][0-9])")


def _recusa_antes_da_conferencia(curto: bool, achados: dict, pagina_citada: int | None, item: dict | None, valor) -> str | None:
    """Motivo da recusa que não depende da leitura das linhas (trecho curto, ausente, fora da página citada, código sem
    item, valor inválido); `None` se a conferência de linha e bloco pode seguir."""
    if curto:
        return "trecho curto demais"
    if not achados:
        return "trecho não encontrado no documento"
    if pagina_citada is not None and pagina_citada not in achados:
        return "página citada não contém o trecho"
    if item is None:
        return "código sem item na EAP geral"
    if valor is not None and not (isinstance(valor, (int, float)) and not isinstance(valor, bool)
                                  and abs(valor) <= LIMITE_DO_VALOR):
        return "valor não está no trecho"
    return None


def _fragmentos_e_blocos(achados: dict[int, list], normalizadas: list[str], valor) -> tuple[dict, dict]:
    """Linhas do trecho (sem marcas) e, com valor, blocos de linhas inteiras da página que o trecho cobre; sem repetição."""
    casados = [m.group() for ms in achados.values() for m in ms]
    fragmentos = dict.fromkeys(f.lstrip(_MINUSCULA) for c in casados for f in c.split("\n") if f != _BRANCO)
    inteiras = [_linhas_inteiras(normalizadas[n - 1], m) for n, ms in achados.items() for m in ms]
    return fragmentos, dict.fromkeys(tuple(b) for c in inteiras if valor is not None and (b := _bloco_do_trecho(c)))


def _status_da_conferencia(achados: dict[int, list], normalizadas: list[str], valor, unidade: str | None, item: dict) -> str:
    """Confere o par e o item em cada linha do trecho e em cada bloco de linhas inteiras, uma vez cada, parando no
    primeiro que confere; devolve o status da citação a partir do conjunto dos resultados."""
    fragmentos, blocos = _fragmentos_e_blocos(achados, normalizadas, valor)
    pares = []
    for par in itertools.chain((_confere_fragmento(f, valor, unidade, item) for f in fragmentos),
                               (_confere_bloco(list(b), valor, unidade, item) for b in blocos)):
        pares.append(par)
        if par == (True, "citado"):
            break
    situacoes = [s for _, s in pares]
    if valor is not None and not any(p for p, _ in pares):
        return "valor não está no trecho"
    return ("conferida" if "citado" in situacoes else "número pertence a outro item" if "outro" in situacoes
            else "item não citado no trecho")


def _localizacao_citada(localizador, paginas: list[str]) -> tuple[int | None, int | None, str | None]:
    """(página, linha da planilha, motivo da recusa) do localizador: 'p. N' é o índice da página (ou da aba); o objeto
    {"aba", "linha"} só vale em planilha, pela aba de mesmo nome (NFC, sem espaço nas pontas) e linha inteira >= 1."""
    if isinstance(localizador, dict):
        linha, alvo = localizador.get("linha"), _nome_da_aba(localizador.get("aba"))
        if not isinstance(linha, int) or isinstance(linha, bool) or linha < 1:
            return None, None, "localizador inválido: a linha tem de ser um inteiro a partir de 1"
        abas = [_nome_da_aba(getattr(p, "aba", None)) for p in paginas]
        if alvo is None or alvo not in abas:
            return None, None, "aba citada não existe no documento"
        if abas.count(alvo) > 1:
            return None, None, "aba citada ambígua: duas abas com o mesmo nome"
        return abas.index(alvo) + 1, linha, None
    cita = re.search(r"\b(?:PAG|P)\.?\s*(\d+)", normalizar(localizador or ""))
    return (int(cita[1]) if cita else None), None, None


def _linhas_do_casamento(normalizada: str, casamento: re.Match) -> range:
    """Índices (0 = primeira) das linhas de texto da página que o casamento do trecho cobre."""
    primeira, ultima = (normalizada.count("\n", 0, i) for i in (casamento.start(), casamento.end()))
    return range(primeira, ultima + 1)


def _achados_na_linha(achados: dict[int, list], pagina: int, original: str, normalizada: str,
                      linha: int) -> tuple[dict[int, list], str | None]:
    """Só os casamentos da aba que cobrem a linha da planilha citada; sem nenhum, o motivo da recusa."""
    mapa = getattr(original, "linhas", ())
    cobertos = [m for m in achados[pagina] if linha in [mapa[i] for i in _linhas_do_casamento(normalizada, m)]]
    return ({pagina: cobertos}, None) if cobertos else (achados, "linha citada não contém o trecho")


def _mesmo_par(numero: float, unidade_celula: str, valor, unidade: str | None) -> bool:
    """O par da planilha é o proposto (com a unidade convertida para comparação, t → kg, como o regex)."""
    return any(abs(n - valor) < 1e-9 and u == unidade
               for n, u in ((numero, unidade_celula), vocabulario.converter(numero, unidade_celula)))


def _par_das_colunas(pagina: PaginaPlanilha, i: int, pecas: list[str], valor, unidade) -> tuple[str, set] | None:
    """(texto do par, peças que ele usa) pelas colunas Un/Qtd do cabeçalho da linha `i`: o valor proposto é o número da
    coluna Qtd, a unidade a da coluna Un, e as duas células estão no trecho. Preço, código e outras colunas nunca valem."""
    por_coluna = {c.coluna: c for c in pagina.celulas[i]}
    qtd, un = por_coluna.get(pagina.cabecalhos[i][1]), por_coluna.get(pagina.cabecalhos[i][0])
    medida = unidade_medida(un.texto) if un else None
    if not (qtd and qtd.numero is not None and medida and _mesmo_par(qtd.numero, medida, valor, unidade)):
        return None
    numero, texto_un = _norm_celula(qtd.texto), _norm_celula(un.texto)
    return (f"{numero} {texto_un}", {numero, texto_un}) if numero in pecas and texto_un in pecas else None


def _par_de_uma_celula(pecas: list[str], valor, unidade, item: dict) -> tuple[str, set] | None:
    """Sem cabeçalho: o par (valor, unidade) só vale dentro de uma mesma célula ('250 un'), nunca entre células."""
    peca = next((p for p in pecas if _confere_fragmento(p, valor, unidade, item)[0]), None)
    return (peca, {peca}) if peca else None


def _tem_quantidade_na_linha(pagina: PaginaPlanilha, i: int, pecas: list[str]) -> bool:
    """A linha afirma quantidade: número na coluna Qtd do cabeçalho, ou (sem cabeçalho) par dentro de uma célula."""
    if pagina.cabecalhos[i]:
        return any(c.coluna == pagina.cabecalhos[i][1] and c.numero is not None for c in pagina.celulas[i])
    return any(_tem_quantidade(p) for p in pecas)


def _pecas_da_linha(fragmentos: list[str], primeira: int, i: int) -> list[str]:
    """Células (peças entre ' | ') do trecho na linha `i`, normalizadas."""
    return fragmentos[i - primeira].lstrip(_MINUSCULA).split(" | ")


def _descricao_do_bloco(pagina: PaginaPlanilha, fragmentos: list[str], indices: range, i: int, usadas: set) -> list[str]:
    """Peças com letra, fora as do par, da linha `i` e das linhas seguidas (sem linha vazia entre elas, até
    LINHAS_DO_BLOCO no total) que o trecho cobre antes dela; o bloco pára na primeira linha que já afirma quantidade."""
    bloco = [i]
    while (len(bloco) < LINHAS_DO_BLOCO and bloco[0] - 1 in indices
           and pagina.linhas[bloco[0]] - pagina.linhas[bloco[0] - 1] == 1
           and not _tem_quantidade_na_linha(pagina, bloco[0] - 1, _pecas_da_linha(fragmentos, indices[0], bloco[0] - 1))):
        bloco.insert(0, bloco[0] - 1)
    return [p for j in bloco for p in _pecas_da_linha(fragmentos, indices[0], j) if re.search("[A-Z]", p) and p not in usadas]


def _situacao_da_linha(pagina: PaginaPlanilha, indices: range, fragmentos: list[str], i: int, item: dict, valor,
                       unidade: str | None) -> str:
    """'valor' (o par não é o da planilha), ou a situação do item ('citado', 'ausente', 'outro') com o par da linha
    `i`: as colunas Un/Qtd do cabeçalho; sem cabeçalho, uma célula só. O item é conferido numa linha sintética com a
    descrição do trecho e o par, por `_confere_fragmento`, e ';' impede que a descrição se cole ao par."""
    pecas = _pecas_da_linha(fragmentos, indices[0], i)
    par = (_par_das_colunas(pagina, i, pecas, valor, unidade) if pagina.cabecalhos[i]
           else _par_de_uma_celula(pecas, valor, unidade, item))
    if par is None:
        return "valor"
    descricao = _descricao_do_bloco(pagina, fragmentos, indices, i, par[1])
    achou, situacao = _confere_fragmento(" ".join(descricao) + " ; " + par[0], valor, unidade, item)
    return situacao if achou else "valor"


def _situacoes_do_casamento(pagina: PaginaPlanilha, normalizada: str, casamento: re.Match, item: dict, valor,
                            unidade: str | None, linha_citada: int | None) -> list[str]:
    """Situações do item, ou 'valor', ou o motivo da recusa da célula (fórmula sem valor, número fora da faixa), em cada
    linha que pode trazer o par: a citada e a última do bloco; sem linha citada, todas as que o trecho cobre."""
    indices = _linhas_do_casamento(normalizada, casamento)
    if problemas := [c.problema for i in indices for c in pagina.celulas[i] if c.problema]:
        return [problemas[0]]
    fragmentos = casamento.group().split("\n")
    if valor is None:
        return [_confere_fragmento(f.lstrip(_MINUSCULA), None, None, item)[1] for f in fragmentos]
    candidatas = [i for i in indices if linha_citada is None or pagina.linhas[i] == linha_citada or i == indices[-1]]
    return [_situacao_da_linha(pagina, indices, fragmentos, i, item, valor, unidade) for i in candidatas]


def _status_da_planilha(achados: dict[int, list], paginas: list[str], normalizadas: list[str], valor,
                        unidade: str | None, item: dict, linha_citada: int | None) -> str:
    """Status da citação em planilha. A quantidade vem das colunas Un/Qtd do cabeçalho (sem cabeçalho, de uma célula
    só); o item, do trecho, com as regras do texto (item mais próximo do número, bloco). Célula marcada recusa."""
    situacoes = [x for n, ms in achados.items() for m in ms
                 for x in _situacoes_do_casamento(paginas[n - 1], normalizadas[n - 1], m, item, valor, unidade, linha_citada)]
    if "citado" in situacoes:
        return "conferida"
    if recusa := next((x for x in situacoes if x.startswith("célula")), None):
        return recusa
    if valor is not None and all(x == "valor" for x in situacoes):
        return "valor não está no trecho"
    return "número pertence a outro item" if "outro" in situacoes else "item não citado no trecho"


def _sem_marcas(trecho: str) -> str:
    """Trecho sem as peças que são marca de célula inválida da planilha (a página de busca também não as tem)."""
    if not any(m in trecho for m in _MARCAS):
        return trecho
    return " | ".join(p for p in trecho.split(" | ") if not any(m in p for m in _MARCAS))


def conferir_citacao(ev: dict, paginas: list[str], normalizadas: list[str] | None = None) -> dict:
    """Evidência de IA conferida contra as páginas do documento (`normalizadas`: o `_paginas_normalizadas` delas, se já
    feito). O trecho (3 palavras ou 15 caracteres e uma letra) tem de estar numa página, com fronteira de palavra e de
    número ('250 estacas' não está em '1250', '1 250' nem '1.250 estacas'); pode atravessar linhas, nunca páginas. Com
    valor, o par (valor, unidade) e o termo do item do código têm de vir da MESMA linha do trecho (`_confere_fragmento`)
    ou de um BLOCO de 2 a 3 linhas inteiras da página, seguidas, que o trecho cobre (`_confere_bloco`: par na última
    linha, nenhuma quantidade nas anteriores, sem linha em branco), e o item tem de ser o termo mais próximo do número; sem valor (menção), o item
    tem de ser citado. Se o localizador
    diz 'p. N' ou 'pág. N' (índice da página no PDF), o trecho tem de estar na página N."""
    normalizadas = _paginas_normalizadas(paginas) if normalizadas is None else normalizadas
    trecho = _sem_marcas(" ".join(_linhas_normalizadas(ev.get("trecho", ""))))
    valor, unidade, item = ev.get("valor"), ev.get("unidade"), _item_do_codigo(ev.get("codigo"))
    pagina, linha, erro = _localizacao_citada(ev.get("localizador"), paginas)
    if erro:
        return {**ev, "citacao": erro}
    tokens = trecho.split()
    curto = not (re.search("[A-Z]", trecho) and (len(tokens) >= 3 or len(trecho) >= 15))
    achados = {} if curto else _achar(_padrao_do_trecho(trecho, tokens), tokens, normalizadas, pagina)
    status = _recusa_antes_da_conferencia(curto, achados, pagina, item, valor)
    if status is None and linha is not None:
        achados, status = _achados_na_linha(achados, pagina, paginas[pagina - 1], normalizadas[pagina - 1], linha)
    if status is None and paginas and all(isinstance(p, PaginaPlanilha) for p in paginas):
        status = _status_da_planilha(achados, paginas, normalizadas, valor, unidade, item, linha)
    status = status or _status_da_conferencia(achados, normalizadas, valor, unidade, item)
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


def _grupos_do_documento(doc: str, do_doc: list[dict]) -> list[tuple[str, list[dict]]]:
    """(nome, evidências) de cada afirmação de um documento: o grupo das parcelas, se houver, e um grupo por total."""
    parcelas = [e for e in do_doc if e["parcela"]]
    if doc.startswith("ia:"):         # a mesma frase em outra página é total repetido, não outra parcela
        parcelas = list({" ".join(_linhas_normalizadas(e["trecho"])): e for e in parcelas}.values())
    return ([("parcelas", parcelas)] if parcelas else []) + \
           [(f"total {e['valor']:g}", [t for t in do_doc if not t["parcela"] and t["valor"] == e["valor"]])
            for e in {e["valor"]: e for e in do_doc if not e["parcela"]}.values()]


def _afirmacoes(evs: list[dict]) -> list[dict]:
    """Uma afirmação por documento e valor: parcelas somadas; totais repetidos (mesmo valor) contam uma vez."""
    saida = []
    for doc in dict.fromkeys(e["documento"]["id"] for e in evs):
        grupos = _grupos_do_documento(doc, [e for e in evs if e["documento"]["id"] == doc])
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
    partes = [e for e in valoradas if e["documento"]["id"] not in diretos and e["codigo"] != codigo and "*" not in e["codigo"]
              and _casa(codigo, e["codigo"]) and (e["servico"], e["unidade"]) == (servico, unidade)]
    return [{**e, "parcela": True, "derivada": True} for doc in dict.fromkeys(e["documento"]["id"] for e in valoradas)
            for e in partes if e["documento"]["id"] == doc]


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


def _status_e_valor_do_fato(decisoes: list[dict], afirm: list[dict], grupos: list[list[dict]], docs: set) -> tuple[str, float | None]:
    """(status, valor) do fato: decidido (última decisão), só menção, conflito (mais de um grupo de valor), convergente
    (mais de um documento no mesmo valor) ou fonte única."""
    if decisoes:
        return "decidido", decisoes[-1]["valor"]
    if not afirm:
        return "só menção", None
    if len(grupos) > 1:
        return "conflito", None
    return ("convergente" if len(docs) > 1 else "fonte única"), grupos[0][0]["valor"]


def _fato(chave: tuple, evs: list[dict], mencoes: list[dict], tol: float) -> dict:
    """Status de um fato a partir das afirmações por documento (decisão à parte)."""
    decisoes = [e for e in evs if e["metodo"] == "decisao"]
    afirm = _afirmacoes([e for e in evs if e["metodo"] != "decisao"])
    grupos = _grupos(afirm, tol)
    valores = [a["valor"] for a in afirm]
    docs = {_fonte(a["documento"]) for a in afirm}
    status, valor = _status_e_valor_do_fato(decisoes, afirm, grupos, docs)
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


def _fato_da_chave(chave: tuple, valoradas: list[dict], mencoes: list[dict], tol: float) -> dict:
    """Fato de (código, serviço, unidade): as evidências com valor da chave, as derivadas dos sistemas e as menções."""
    evs_fato = [e for e in valoradas if (e["codigo"], e["servico"], e["unidade"]) == chave] + _derivadas(chave, valoradas)
    return _fato(chave, evs_fato, [m for m in mencoes if (m["codigo"], m["servico"]) == chave[:2]], tol)


def _fatos_so_mencao(mencoes: list[dict], com_valor: set, tol: float) -> list[dict]:
    """Um fato 'só menção' por (código, serviço) citado sem número em nenhum documento."""
    chaves = dict.fromkeys((m["codigo"], m["servico"]) for m in mencoes if (m["codigo"], m["servico"]) not in com_valor)
    return [_fato((*chave, None), [], [m for m in mencoes if (m["codigo"], m["servico"]) == chave], tol) for chave in chaves]


TOLERANCIA_RELATIVA = 0.005    # afirmações de documentos diferentes são "o mesmo valor" dentro dela


def consolidar(evs: list[dict], tol: float = TOLERANCIA_RELATIVA) -> pd.DataFrame:
    """Fatos (código, serviço, unidade) com o status: convergente, fonte única, conflito, só menção ou decidido.
    IA só entra com citação conferida. Menção (sem número) reforça o fato mas não dá valor."""
    aceitas = [e for e in _sem_ia_repetida(evs) if e["metodo"] != "ia" or e.get("citacao") == "conferida"]
    valoradas = [e for e in aceitas if e["valor"] is not None and e["unidade"]]
    mencoes = [e for e in aceitas if e["valor"] is None]
    chaves = list(dict.fromkeys((e["codigo"], e["servico"], e["unidade"]) for e in valoradas))
    fatos = [_fato_da_chave(chave, valoradas, mencoes, tol) for chave in chaves]
    return pd.DataFrame(fatos + _fatos_so_mencao(mencoes, {c[:2] for c in chaves}, tol))


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


class Celula(NamedTuple):
    """Célula não vazia de planilha: coluna (1 = A), texto como lê o leitor, número (se for número) e, se a célula não
    pode valer como dado, o motivo da recusa (`problema`)."""
    coluna: int
    texto: str
    numero: float | None = None
    problema: str | None = None


_SEM_VALOR = "célula sem valor calculado na planilha"
_FORA_DA_FAIXA = "célula com número fora da faixa legível na planilha"
_MARCA_SEM_VALOR, _MARCA_FORA_DA_FAIXA = "[fórmula sem valor]", "[número fora da faixa]"
_MARCAS = (normalizar(_MARCA_SEM_VALOR), normalizar(_MARCA_FORA_DA_FAIXA))
_ROTULOS_DE_UNIDADE = {"UN", "UND", "UNID", "UNIDADE"}
_ROTULOS_DE_QUANTIDADE = {"QTD", "QTDE", "QUANT", "QUANTIDADE"}
_PREFIXOS_DE_PRECO = ("PRECO", "VALOR", "CUSTO")
_ROTULOS_DE_PRECO = {"R$", "TOTAL", "SUBTOTAL", "BDI", "PU", "PUNIT", "PUNITARIO"}
_NUMERO_DE_TEXTO = re.compile(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?")
_LIMITE_DE_LEITURA_CSV = 0.6      # fração mínima das linhas do csv com o número de campos mais comum


def _nome_da_aba(nome) -> str | None:
    """Nome de aba comparável: NFC e sem espaço nas pontas; None se não for texto."""
    return unicodedata.normalize("NFC", nome).strip() if isinstance(nome, str) else None


def _norm_celula(texto: str) -> str:
    """Texto da célula normalizado como a página (maiúsculas, sem acento, aspas e travessões unificados)."""
    return normalizar(texto.translate(_ASPAS_E_TRACOS))


def _cabecalho_da_linha(celulas: list[Celula]) -> tuple[int, int] | None:
    """(coluna da unidade, coluna da quantidade) se a linha traz um rótulo de cada ('Un'/'Unid'/'Unidade' e
    'Qtd'/'Qtde'/'Quant'/'Quantidade')."""
    rotulos = [(c.coluna, normalizar(c.texto).strip(" .:")) for c in celulas]
    unidade = next((col for col, r in rotulos if r in _ROTULOS_DE_UNIDADE), None)
    quantidade_ = next((col for col, r in rotulos if r in _ROTULOS_DE_QUANTIDADE), None)
    return (unidade, quantidade_) if unidade is not None and quantidade_ is not None else None


def _rotulo_de_preco(texto: str) -> bool:
    """Rótulo de coluna de preço: PREÇO*, VALOR*, CUSTO*, 'R$', TOTAL, SUBTOTAL, BDI, PU, 'P. UNIT'."""
    rotulo = re.sub(r"[^A-Z0-9$]", "", normalizar(texto))
    return rotulo.startswith(_PREFIXOS_DE_PRECO) or rotulo in _ROTULOS_DE_PRECO


def _colunas_de_preco(celulas: list[Celula], colunas_un_qtd: tuple[int, int]) -> frozenset[int]:
    """Colunas de preço da linha de cabeçalho; nunca a coluna reconhecida como Un ou Qtd."""
    return frozenset(c.coluna for c in celulas
                     if c.coluna not in colunas_un_qtd and _rotulo_de_preco(c.texto))


def _sem_preco(linhas: list[tuple[int, list[Celula]]]) -> list[tuple[int, list[Celula]]]:
    """Linhas sem preço: as células das colunas de preço (do cabeçalho, rótulo incluído, até o próximo cabeçalho) e
    toda célula com 'R$' saem do texto, como se não existissem; a linha que fica vazia some."""
    preco: frozenset[int] = frozenset()
    saida = []
    for numero, celulas in linhas:
        if colunas := _cabecalho_da_linha(celulas):
            preco = _colunas_de_preco(celulas, colunas)
        if restantes := [c for c in celulas if c.coluna not in preco and "R$" not in c.texto]:
            saida.append((numero, restantes))
    return saida


def _cabecalhos(celulas_por_linha) -> tuple[tuple[int, int] | None, ...]:
    """Para cada linha, as colunas (Un, Qtd) do último cabeçalho acima dela; a própria linha de cabeçalho e as de antes
    dele ficam sem colunas."""
    atual, saida = None, []
    for celulas in celulas_por_linha:
        novo = _cabecalho_da_linha(list(celulas))
        saida.append(None if novo else atual)
        atual = novo or atual
    return tuple(saida)


class PaginaPlanilha(str):
    """Texto de uma aba (ou do csv): uma linha de texto por linha não vazia da planilha, as células não vazias unidas
    por ' | '. Guarda o nome da aba, a linha da planilha de cada linha de texto (1 = primeira linha da aba, contando as
    vazias, como no Excel), as células (sem preço: ver `_sem_preco`) e, por linha, as colunas (Un, Qtd) do cabeçalho que vale para ela."""
    aba: str
    linhas: tuple[int, ...]
    celulas: tuple[tuple[Celula, ...], ...]
    cabecalhos: tuple[tuple[int, int] | None, ...]

    def __new__(cls, aba: str, linhas: list[tuple[int, list[Celula]]]):
        linhas = _sem_preco(linhas)
        pagina = super().__new__(cls, "\n".join(" | ".join(c.texto for c in cs) for _, cs in linhas))
        pagina.aba = aba
        pagina.linhas = tuple(n for n, _ in linhas)
        pagina.celulas = tuple(tuple(cs) for _, cs in linhas)
        pagina.cabecalhos = _cabecalhos(pagina.celulas)
        return pagina


def _numero_ptbr(valor: decimal.Decimal) -> str:
    """Número como lê quem abre a planilha em pt-BR, sem arredondar: 250 → '250'; 1250.5 → '1.250,5'; -0 → '0'."""
    if valor == 0:
        return "0"
    inteira, _, fracao = format(valor, "f").partition(".")
    fracao = fracao.rstrip("0")
    sinal, inteira = ("-", inteira[1:]) if inteira.startswith("-") else ("", inteira)
    return sinal + f"{int(inteira):,}".replace(",", ".") + ("," + fracao if fracao else "")


def _legivel(valor) -> bool:
    """Número finito, zero ou com módulo entre 1e-6 e 1e15 (fora disso a representação não é confiável)."""
    try:
        v = float(valor)
    except OverflowError:
        return False
    return math.isfinite(v) and (v == 0 or 1e-6 <= abs(v) <= 1e15)


def _celula_numerica(coluna: int, valor, percentual: bool) -> Celula:
    """Célula de número: texto pt-BR exato (`repr` do float); percentual vira 'valor×100%' e não é quantidade; número
    fora da faixa legível, NaN ou infinito vira texto marcado que não confere."""
    if not _legivel(valor):
        return Celula(coluna, _MARCA_FORA_DA_FAIXA, None, _FORA_DA_FAIXA)
    exato = decimal.Decimal(repr(valor)) if isinstance(valor, float) else decimal.Decimal(valor)
    if percentual:
        return Celula(coluna, _numero_ptbr(exato * 100) + "%")
    return Celula(coluna, _numero_ptbr(exato), float(exato))


def _celula(coluna: int, valor, percentual: bool = False, formula: bool = False) -> Celula | None:
    """Célula como o leitor a vê, ou None se vazia. Fórmula sem valor guardado vira texto marcado que não confere;
    data vira dd/mm/aaaa; texto com espaços e quebras reduzidos a um espaço (e número, se for só um número em pt-BR)."""
    if hasattr(valor, "item"):                                                          # escalar do NumPy
        valor = valor.item()
    if valor is None:
        return Celula(coluna, _MARCA_SEM_VALOR, None, _SEM_VALOR) if formula else None
    if isinstance(valor, bool):
        return Celula(coluna, "VERDADEIRO" if valor else "FALSO")
    if isinstance(valor, (datetime.datetime, datetime.date)):
        return Celula(coluna, valor.strftime("%d/%m/%Y"))
    if isinstance(valor, (int, float, decimal.Decimal)):
        return _celula_numerica(coluna, valor, percentual)
    texto = " ".join(str(valor).split())
    return Celula(coluna, texto, numero_br(texto) if _NUMERO_DE_TEXTO.fullmatch(texto) else None) if texto else None


def _linhas_da_planilha(linhas_brutas) -> list[tuple[int, list[Celula]]]:
    """[(linha da planilha, células)] das linhas com alguma célula; `linhas_brutas`: [(linha, [Celula ou None])]."""
    saida = []
    for numero, celulas in linhas_brutas:
        if cs := [c for c in celulas if c is not None]:
            saida.append((numero, cs))
    return saida


def _contagem_de_campos(texto: str, separador: str) -> tuple[int, float]:
    """(número de campos mais comum, fração das linhas não vazias com esse número) do csv lido com o separador."""
    campos = [len(r) for r in csv.reader(io.StringIO(texto, newline=""), delimiter=separador) if any(c.strip() for c in r)]
    if not campos:
        return 1, 1.0
    moda = max(set(campos), key=lambda k: (campos.count(k), k))
    return moda, campos.count(moda) / len(campos)


def _separador_do_csv(texto: str) -> str:
    """Separador do csv entre ';', tabulação e ',': o que dá número de campos consistente nas linhas (a moda; ao menos 2
    campos), com ';' ganhando os empates, depois o palpite do `csv.Sniffer`. Sem nenhum consistente, o documento é
    recusado (ValueError)."""
    try:
        palpite = csv.Sniffer().sniff(texto[:4096], delimiters=";\t,").delimiter
    except csv.Error:
        palpite = ";"
    ordem = list(dict.fromkeys([";", palpite, "\t", ","]))
    contagens = {sep: _contagem_de_campos(texto, sep) for sep in ordem}
    melhor = max(ordem, key=lambda sep: (contagens[sep][0] >= 2, contagens[sep][1]))
    if contagens[melhor][0] >= 2 and contagens[melhor][1] < _LIMITE_DE_LEITURA_CSV:
        raise ValueError("csv com separador ambíguo ou número de campos inconsistente nas linhas: "
                         "salve com ';' e as mesmas colunas em todas as linhas")
    return melhor


def _pagina_do_csv(caminho: Path) -> PaginaPlanilha:
    """Página do csv (utf-8, senão latin-1); a linha vazia conta, e a quebra dentro de aspas vira espaço."""
    bruto = caminho.read_bytes()
    try:
        texto = bruto.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=_separador_do_csv(texto))
    return PaginaPlanilha(caminho.stem, _linhas_da_planilha(
        (n, [_celula(i, v) for i, v in enumerate(campos, 1)]) for n, campos in enumerate(leitor, 1)))


def _paginas_do_xls(caminho: Path) -> list[PaginaPlanilha]:
    """Abas de um .xls (pandas + xlrd); sem o xlrd instalado, o documento é recusado (ValueError)."""
    if importlib.util.find_spec("xlrd") is None:
        raise ValueError(f"{caminho.name}: ler .xls exige a biblioteca xlrd, que não está instalada; salve como .xlsx")
    abas = pd.read_excel(caminho, sheet_name=None, header=None, dtype=object)
    return [PaginaPlanilha(nome, _linhas_da_planilha(
        (i, [_celula(j, None if pd.isna(v) else v) for j, v in enumerate(linha, 1)])
        for i, linha in enumerate(df.itertuples(index=False), 1))) for nome, df in abas.items()]


def _paginas_do_xlsx(caminho: Path) -> list[PaginaPlanilha]:
    """Abas de um .xlsx/.xlsm (openpyxl, valores guardados); célula de fórmula sem valor guardado fica marcada."""
    from openpyxl import load_workbook
    from openpyxl.utils.exceptions import InvalidFileException
    try:
        formulas = load_workbook(caminho)
        valores = load_workbook(caminho, data_only=True)
    except (OSError, zipfile.BadZipFile, InvalidFileException, KeyError, ValueError) as erro:
        raise ValueError(f"{caminho.name}: planilha ilegível ({erro})") from erro
    try:
        com_formula = {a.title: {c.coordinate for linha in a.iter_rows() for c in linha if c.data_type == "f"}
                       for a in formulas.worksheets}
        return [PaginaPlanilha(aba.title, _linhas_da_planilha(
            (linha[0].row, [_celula(c.column, c.value, "%" in str(c.number_format),
                                    c.coordinate in com_formula.get(aba.title, ())) for c in linha])
            for linha in aba.iter_rows() if linha)) for aba in valores.worksheets]
    finally:
        formulas.close()
        valores.close()


def paginas_planilha(caminho: str | Path) -> list[PaginaPlanilha]:
    """Páginas de uma planilha (.xlsx, .xlsm, .xls, .csv) para a IA citar: uma por aba, na ordem do arquivo (csv = uma
    página), com uma linha de texto por linha não vazia (células não vazias unidas por ' | ', números em pt-BR sem
    arredondar). Determinístico. Levanta ValueError se o documento não pode ser lido com segurança (csv de separador
    ambíguo, .xls sem xlrd, arquivo ilegível)."""
    arquivo = Path(caminho)
    sufixo = arquivo.suffix.lower()
    if sufixo == ".csv":
        return [_pagina_do_csv(arquivo)]
    return _paginas_do_xls(arquivo) if sufixo == ".xls" else _paginas_do_xlsx(arquivo)


_EXTENSOES_DE_PLANILHA = {".xlsx", ".xlsm", ".xls", ".csv"}


def paginas_do_arquivo(caminho: str | Path) -> list[str]:
    """Páginas de um documento de leitura pela extensão: planilha (.xlsx/.xls/.csv) ou PDF."""
    if Path(caminho).suffix.lower() in _EXTENSOES_DE_PLANILHA:
        return paginas_planilha(caminho)
    return paginas_pdf(caminho)


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
    """Documentos de leitura do obra.json (`evidencias.documentos`: pdf (PDF ou planilha .xlsx/.xls/.csv), tipo, unidade?,
    sistema?), com as páginas."""
    saida = []
    for d in (cfg.get("evidencias") or {}).get("documentos", []):
        if not Path(d["pdf"]).exists():
            log(f"  evidências: {d['pdf']} não está no disco")
            continue
        try:
            paginas = paginas_do_arquivo(d["pdf"])
        except ValueError as erro:                       # planilha que não se lê com segurança: fica de fora, o build segue
            log(f"  evidências: documento recusado: {erro}")
            continue
        saida.append({"id": Path(d["pdf"]).name, "nome": Path(d["pdf"]).name, **d, "paginas": paginas})
    return saida


def _obras_lineares_da_obra(cfg: dict, furos: list | None, log=print) -> list[dict]:
    """Evidências da planilha Obras Lineares do obra.json (`obras_lineares`: planilha, aba?, eap?, metodo?): digitado e
    recálculo do MOS dos mesmos trechos, com o método escolhido para cada um. Sem planilha no disco ou sem a aba, nada."""
    from . import obras_lineares
    c = cfg.get("obras_lineares") or {}
    if not c.get("planilha") or not obras_lineares.tem_aba(c):
        if c.get("planilha"):
            log(f"  evidências: planilha {c['planilha']} ausente ou sem a aba '{c.get('aba', 'Obras Lineares')}' (pendência)")
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


def _planilha_do_contrato(esc: dict) -> tuple | None:
    """(itens, documento, catálogo) da planilha do contrato (`escopo.itens_csv` do obra.json), ou None sem o arquivo."""
    from .orcamento_sanepar import catalogo
    if not (esc.get("itens_csv") and Path(esc["itens_csv"]).exists()):
        return None
    df = pd.read_csv(esc["itens_csv"], sep=";", decimal=",", encoding="utf-8-sig")
    cat = catalogo(esc["catalogo"]) if esc.get("catalogo") else None
    return df, {"id": Path(esc["itens_csv"]).name, "tipo": "planilha", "nome": esc.get("fonte", "")}, cat


def etapa(cfg: dict, out: Path, dados: dict, log=print) -> dict | None:
    """Loop de evidências da obra: documentos, planilha do contrato, planilha Obras Lineares, pranchas medidas, IA e decisões do obra.json.
    Grava evidencias.jsonl, fatos.csv, cobertura.csv, associados.csv, dimensoes.csv e calibracao.csv em `out`; devolve o resumo para o HTML (None sem fonte)."""
    conf = cfg.get("evidencias") or {}
    planilha = _planilha_do_contrato(cfg.get("escopo") or {})
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
    tabelas["calibracao"] = calibracao.tabela(evs, consolidar([e for e in evs if e["metodo"] != "associado"]), elementos)
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


def _problemas_do_codigo_e_servico(ev: dict, item: dict | None, servico: str, ja_ha_problemas: bool) -> list[str]:
    """Código sem item na EAP geral (só se nada falhou antes), serviço que o item não admite e escopo fora do enum."""
    problemas = []
    if "codigo" in ev and item is None and not ja_ha_problemas:
        problemas.append(f"código '{ev['codigo']}' sem item na EAP geral ('*' só vale em unidade e sistema)")
    if item and servico and (servico not in item["servicos"] or servico not in {x["id"] for x in SERVICOS}):
        problemas.append(f"serviço '{servico}' não é admitido pelo item {item['codigo']}")
    if ev.get("escopo") not in SCHEMA["properties"]["escopo"]["enum"]:
        problemas.append(f"escopo '{ev.get('escopo')}' inválido")
    return problemas


def _problemas_do_valor_e_da_unidade(valor, unidade, item: dict | None, servico: str) -> list[str]:
    """Primeiro problema do par (valor, unidade): sem valor, só a unidade solta é conferida; com valor, na ordem:
    não é número, fora do intervalo, unidade fora do vocabulário, negativo, unidade que o item (ou serviço) não aceita."""
    fora_do_vocabulario = f"unidade '{unidade}' fora do vocabulário ({', '.join(vocabulario.REGRAS['unidades'])})"
    unidade_invalida = not isinstance(unidade, str) or unidade not in vocabulario.REGRAS["unidades"]
    if valor is None:
        return [fora_do_vocabulario] if unidade is not None and unidade_invalida else []
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        return [f"valor '{str(valor)[:30]}' não é número"]
    if not abs(valor) <= LIMITE_DO_VALOR:
        return [f"valor fora do intervalo (|valor| até {LIMITE_DO_VALOR:g})"]
    if unidade_invalida:
        return [fora_do_vocabulario]
    if valor < 0:
        return ["valor negativo"]
    return _problemas_da_unidade_no_item(unidade, item, servico)


def _problemas_da_unidade_no_item(unidade: str, item: dict | None, servico: str) -> list[str]:
    """Unidade que o item da EAP (ou o serviço dele) não aceita; serviço que o item não admite já é outro problema."""
    if not item or (servico and servico not in item["servicos"]):
        return []
    aceitas = _unidades_do_item(item, servico)
    if unidade in aceitas:
        return []
    return [f"unidade '{unidade}' não é aceita por {item['codigo']}" + (f" / {servico}" if servico else "")
            + f" (aceitas: {', '.join(aceitas)})"]


def _problemas_de_forma(ev: dict) -> list[str]:
    """Problemas que impedem até a leitura do resto: documento que não é objeto com id, ou campo de texto de outro tipo."""
    if not isinstance(ev.get("documento"), dict) or not ev["documento"].get("id"):
        return ["documento tem de ser um objeto com id (nome do arquivo) e tipo"]
    problemas = [f"'{k}' tem de ser texto" for k in ("codigo", "servico", "trecho", "regra")
                 if k in ev and not isinstance(ev[k], str)]
    return problemas + _problemas_do_localizador(ev["localizador"]) if "localizador" in ev else problemas


def _problemas_do_localizador(localizador) -> list[str]:
    """O localizador é texto ('p. 4') ou, em planilha, {"aba": texto, "linha": inteiro a partir de 1}."""
    if isinstance(localizador, str):
        return []
    if (isinstance(localizador, dict) and set(localizador) == {"aba", "linha"} and isinstance(localizador["aba"], str)
            and isinstance(localizador["linha"], int) and not isinstance(localizador["linha"], bool)
            and localizador["linha"] >= 1):
        return []
    return ["'localizador' tem de ser texto ou {aba, linha} (linha inteira a partir de 1)"]


def _problemas_ia(ev: dict) -> list[str]:
    """Além do schema: uma proposta de IA tem método e tipo de documento `ia`; código com item da EAP geral (`*` só em
    unidade e sistema); serviço que o item admite; escopo do enum; valor numérico não negativo com unidade do vocabulário
    e do item (ou do serviço); `parcela` booleana. Nunca levanta exceção: linha malformada vira lista de problemas."""
    problemas = _problemas_de_forma(ev)
    if problemas:
        return problemas
    problemas = validar_evidencia(ev)
    if ev.get("metodo") != "ia" or ev["documento"].get("tipo") != "ia":
        problemas.append("método e documento.tipo têm de ser 'ia'")
    servico = ev.get("servico") or ""
    item = _item_do_codigo(ev.get("codigo")) if "codigo" in ev else None
    problemas += _problemas_do_codigo_e_servico(ev, item, servico, bool(problemas))
    problemas += _problemas_do_valor_e_da_unidade(ev.get("valor"), ev.get("unidade"), item, servico)
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


def _documentos_da_linha_de_comando(pdfs: list[str], textos: list[str], log=print,
                                    planilhas: list[str] | None = None) -> dict[str, list[str]]:
    """Nome do arquivo → páginas: PDF por página; planilha por aba; texto puro por página separada por quebra de página (\\f)."""
    documentos, planilhas = {}, planilhas or []
    for caminho in pdfs + planilhas + textos:
        arquivo = Path(caminho)
        if not arquivo.exists():
            log(f"  aviso: {caminho} não existe e será ignorado")
        elif caminho in pdfs:
            documentos[arquivo.name] = paginas_pdf(arquivo)
        elif caminho in planilhas:
            try:
                documentos[arquivo.name] = paginas_planilha(arquivo)
            except ValueError as erro:
                log(f"  aviso: documento recusado: {erro}")
        else:
            documentos[arquivo.name] = arquivo.read_text(encoding="utf-8").split("\f")
    return documentos


def _comando_conferir(args, log=print) -> int:
    """`conferir`: relatório de aceitas e recusadas; grava só as aceitas em `--saida`. Saída 2 sem o arquivo de entrada."""
    entrada = Path(args.ia)
    if not entrada.exists():
        log(f"erro: o arquivo {entrada} não existe")
        return 2
    documentos = _documentos_da_linha_de_comando(args.pdf, args.texto, log, args.planilha)
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
    c.add_argument("--planilha", action="append", default=[], help="planilha .xlsx/.xls/.csv do documento (repetível)")
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
