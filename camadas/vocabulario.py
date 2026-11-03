"""Vocabulário comum dos documentos: normalização, abreviações, sinônimos e unidades (conceitos/sinonimos.json).

    texto bruto ─ normalizar (maiúsculas, sem acento, ² → 2) ─ abreviações (EST. → ESTACA) ─► texto para medir
                                                             └ + canônicos dos sinônimos ─► texto para classificar
    "300,5 M3" / "MC" / "metros cúbicos" ─► m³        t ─► kg (conversões para comparar)

A linha original continua sendo o trecho da evidência: o vocabulário só ajuda a achar, não reescreve o documento.
"""
from __future__ import annotations

import json
import re
import unicodedata

from .pdf_cad import CONCEITOS

REGRAS = json.loads((CONCEITOS / "sinonimos.json").read_text(encoding="utf-8"))
GRAFIAS = {g: canonica for canonica, grafias in REGRAS["unidades"].items() for g in grafias}
NUMERO = r"(\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:,\d+)?)"
NUMERO_INTEIRO = NUMERO + r"(?![\d]|[.,]\d)"
NAO_E_NUMERO = r"(?<![\d.,ØA-Z])(?<![A-Z]-)"      # "DN150", "C30", "CA-50", "Ø40" colados não são quantidades
DIMENSAO = re.compile(r"(?<![A-Z0-9])(?:Ø|DN|DIAMETRO|DIAM\.?)\s*[:=]?\s*" + NUMERO_INTEIRO
                      + r"(?:\s*(?:MM|CM|M|POL)(?![A-Z0-9])(?!\s*[:=]?\s*\d)|(?![ ]*[A-Z]))")   # "DN 150", "Ø 40 cm"
QTD_DEPOIS = re.compile(NAO_E_NUMERO + NUMERO + r"\s*("
                        + "|".join(re.escape(g) for g in sorted(GRAFIAS, key=len, reverse=True)) + r")\b")
QTD_ANTES = re.compile(NAO_E_NUMERO + NUMERO + r"\s+(?:[A-Z]+\s+){0,2}$")

UNIDADE_ANTES = re.compile(r"(?<![A-Z0-9])(?:" + "|".join(re.escape(g) for g in sorted(GRAFIAS, key=len, reverse=True))
                           + r")\s*[:|-]*\s*$")


def normalizar(texto) -> str:
    """Maiúsculas, sem acento e espaços simples: a forma em que os termos dos conceitos são escritos (² vira 2)."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).upper().strip()


def abreviacoes(linha: str) -> str:
    """Expande as abreviações de uma linha já normalizada (EST. → ESTACA, CONC. → CONCRETO)."""
    for padrao, expansao in REGRAS["abreviacoes"]:
        linha = re.sub(padrao, expansao, linha)
    return re.sub(r"\s+", " ", linha).strip()


def canonicos(linha: str) -> list[str]:
    """Termos canônicos cujas variantes aparecem na linha (HELICE CONTINUA → ESTACA; CIMBRAMENTO → ESCORAMENTO)."""
    return [c for c, variantes in REGRAS["sinonimos"].items()
            if any(re.search(rf"(?<![A-Z]){v}(?![A-Z])", linha) for v in variantes)]


def preparar(texto) -> tuple[str, str]:
    """(texto para medir, texto para classificar): normalizado com abreviações; e o mesmo + ' | ' + canônicos."""
    linha = abreviacoes(normalizar(texto))
    extras = [c for c in canonicos(linha) if not re.search(rf"\b{c}\b", linha)]
    return linha, (linha + " | " + " ".join(extras)) if extras else linha


def unidade_medida(texto) -> str | None:
    """Unidade canônica (un, m, m², m³, kg, t, vb, cj, m³xkm, h, dia) de qualquer grafia; None se não reconhece."""
    t = normalizar(texto).replace(".", "").strip()
    return GRAFIAS.get(t) or GRAFIAS.get(t.replace(" ", ""))


def converter(valor: float, unidade: str) -> tuple[float, str]:
    """Leva à unidade de comparação (t → kg); as outras ficam como estão."""
    if unidade in REGRAS["conversoes"]:
        para, fator = REGRAS["conversoes"][unidade]
        return valor * fator, para
    return valor, unidade


def numero_br(texto: str) -> float:
    """'1.250,5' → 1250.5; '12,5' → 12.5; '300' → 300."""
    return float(texto.replace(".", "").replace(",", "."))


def _de_outra_unidade(linha: str, antes: re.Match, inicio_termo: int) -> bool:
    """O número do fallback 'número + termo' pertence a outra unidade: vem logo depois de uma unidade ('m³ 45',
    'un: 250') ou há uma unidade entre ele e o termo ('3.000 metros de estacas')."""
    if UNIDADE_ANTES.search(linha[:antes.start(1)]):
        return True
    return any(p in GRAFIAS for p in re.findall(r"[A-Z0-9]+", linha[antes.end(1):inicio_termo]))


def quantidade(linha: str, termos: list[str]) -> tuple[float | None, str | None]:
    """Primeiro 'número unidade' da linha (300 UN, 1.250,5 M3, 12 METROS CUBICOS); senão 'número + termo' (300
    ESTACAS) → un (se o número não é de outra unidade), procurando o número antes do primeiro termo que casa. Unidade convertida para comparação.
    Número colado a letra ou hífen (DN150, C30, CA-50) e dimensão de especificação (DN 150, Ø 40 cm) não são
    quantidade. Só vale 'número unidade' (e 'número termo'): 'DN150 m 320' fica sem quantidade."""
    linha = DIMENSAO.sub(lambda d: " " * len(d[0]), linha)
    m = QTD_DEPOIS.search(linha)
    if m:
        return converter(numero_br(m[1]), GRAFIAS[m[2]])
    for termo in termos:
        achado = re.search(termo, linha)
        antes = QTD_ANTES.search(linha[:achado.start()]) if achado else None
        if antes and not _de_outra_unidade(linha, antes, achado.start()):
            return numero_br(antes[1]), "un"
    return None, None


def validar() -> list[str]:
    """Problemas do vocabulário: regex que não compila, grafia de unidade repetida, conversão para unidade inexistente."""
    problemas = []
    for padrao in [p for p, _ in REGRAS["abreviacoes"]] + [v for vs in REGRAS["sinonimos"].values() for v in vs]:
        try:
            re.compile(padrao)
        except re.error as erro:
            problemas.append(f"regex '{padrao}': {erro}")
    todas = [g for gs in REGRAS["unidades"].values() for g in gs]
    problemas += [f"grafia de unidade repetida: {g}" for g in sorted({g for g in todas if todas.count(g) > 1})]
    problemas += [f"conversão {de} → {para}: unidade desconhecida" for de, (para, _) in REGRAS["conversoes"].items()
                  if de not in REGRAS["unidades"] or para not in REGRAS["unidades"]]
    return problemas
