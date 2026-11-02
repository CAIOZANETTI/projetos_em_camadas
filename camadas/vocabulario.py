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
QTD_DEPOIS = re.compile(r"(?<![\d.,])" + NUMERO + r"\s*("
                        + "|".join(re.escape(g) for g in sorted(GRAFIAS, key=len, reverse=True)) + r")\b")
QTD_ANTES = re.compile(r"(?<![\d.,])" + NUMERO + r"\s+(?:[A-Z]+\s+){0,2}$")


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


def quantidade(linha: str, termos: list[str]) -> tuple[float | None, str | None]:
    """Primeiro 'número unidade' da linha (300 UN, 1.250,5 M3, 12 METROS CUBICOS); senão 'número + termo' (300
    ESTACAS) → un, procurando o número antes do primeiro termo que casa. Unidade convertida para comparação."""
    m = QTD_DEPOIS.search(linha)
    if m:
        return converter(numero_br(m[1]), GRAFIAS[m[2]])
    for termo in termos:
        achado = re.search(termo, linha)
        if achado and (antes := QTD_ANTES.search(linha[:achado.start()])):
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
