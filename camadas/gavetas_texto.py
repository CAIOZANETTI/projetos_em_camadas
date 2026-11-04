"""Menções da EAP nos documentos de texto (F5 da reconstrução, `docs/RECONSTRUCAO.md`): em que documento e página
cada item técnico de `conceitos/eap_geral.jsonl` aparece, e com que quantidade quando o texto diz.

Só código (texto do PDF + regex dos `termos` do item); sem OCR e sem IA. Página sem texto vira pendência: ler imagem é
passe posterior da escada. A quantidade é a de `vocabulario.quantidade` ("número + unidade" no mesmo trecho).

    python -m camadas.gavetas_texto saida/<obra>      # lê saida/<obra>/base/documentos e confere as menções
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

from . import eap, gavetas, vocabulario

CLASSES_DE_TEXTO = ("edital", "memorial", "laudo", "lista")
LEITOR_DE_TEXTO = "camadas.evidencias"
METODO = "camadas.gavetas_texto (regex de eap_geral.termos)"
TRECHO_MAX = 200
MOTIVO_SEM_TEXTO = "página sem texto (OCR é passe da escada)"


def _le_texto(documento: dict) -> bool:
    """Documento cujo texto vale ler: classe de texto, ou projeto que cita o leitor de evidências no destino."""
    if str(documento.get("extensao", "")).lower() != ".pdf":
        return False
    if documento.get("classe") in CLASSES_DE_TEXTO:
        return True
    destino = documento.get("destino") or []
    return documento.get("classe") == "projeto" and any(
        d.get("leitor") == LEITOR_DE_TEXTO for d in destino
    )


def paginas_do_pdf(caminho: Path) -> list[str]:
    """Texto de cada página do PDF (pymupdf `get_text`), sem OCR."""
    import pymupdf

    with pymupdf.open(caminho) as pdf:
        return [pagina.get_text("text") for pagina in pdf]


def _pagina_preparada(texto: str) -> tuple[str, str]:
    """(texto para medir, texto para buscar): linhas normalizadas e unidas por espaço; a busca vê também os
    sinônimos canônicos de cada linha (HELICE CONTINUA → ESTACA)."""
    medidas, buscas = [], []
    for linha in texto.splitlines():
        if linha.strip():
            medir, classificar = vocabulario.preparar(linha)
            medidas.append(medir)
            buscas.append(classificar)
    return " ".join(medidas), " ".join(buscas)


def _trecho(texto: str, inicio: int, fim: int) -> str:
    """Até `TRECHO_MAX` caracteres em volta do termo, cortado em fronteira de palavra."""
    folga = max(0, (TRECHO_MAX - (fim - inicio)) // 2)
    a, b = max(0, inicio - folga), min(len(texto), fim + folga)
    if a > 0 and texto[a - 1] != " ":
        a = min(inicio, texto.find(" ", a) + 1 or a)
    if b < len(texto) and texto[b] != " ":
        corte = texto.rfind(" ", fim, b)
        b = corte if corte > 0 else b
    return texto[a:b].strip()[:TRECHO_MAX]


def _achados_da_pagina(texto: str, padroes: dict) -> dict[str, str]:
    """{item: trecho} do primeiro termo de cada item que casa na página."""
    medir, buscar = _pagina_preparada(texto)
    achados = {}
    for codigo, padrao in padroes.items():
        m = padrao.search(buscar)
        if m:
            # o sinônimo canônico fica depois do fim da linha medida: o trecho ancora no fim do texto medido
            inicio = min(m.start(), max(0, len(medir) - 1))
            fim = max(min(m.end(), len(medir)), inicio + 1)
            achados[codigo] = _trecho(medir, inicio, fim)
    return achados


def _evidencia(evidencia_id: str, documento: dict, pagina: int, trecho: str) -> dict:
    return {
        "evidencia_id": evidencia_id,
        "classe": documento["classe"],
        "documento": documento["documento_id"],
        "localizador": {"pagina": pagina},
        "trecho": trecho,
        "metodo": METODO,
        "executor": "código",
    }


def _fato(
    objeto_id: str, sufixo: str, propriedade: str, valor, evidencia_id: str
) -> dict:
    return {
        "fato_id": f"{objeto_id}{sufixo}",
        "objeto_id": objeto_id,
        "propriedade": propriedade,
        "valor": valor,
        "natureza": "projetado",
        "evidencia_id": evidencia_id,
    }


def _itens_em_lista(itens) -> list[dict]:
    itens = eap.itens() if itens is None else itens
    lista = list(itens.values()) if isinstance(itens, dict) else list(itens)
    return sorted(lista, key=lambda it: it["codigo"])


def _mencoes_do_item(
    base: dict, documento: dict, codigo: str, paginas: list, termos: list[str]
) -> None:
    """Objeto, fato do item, um fato `mencao` por página e, na primeira página com "número + unidade", a quantidade."""
    objeto_id = f"txt-{documento['documento_id']}-{codigo}"
    base["objetos"].append({"objeto_id": objeto_id, "classe": "mencao_documento"})
    primeira = f"EV-{objeto_id}#p{paginas[0][0]}"
    base["fatos"].append(_fato(objeto_id, "#item", "item_tecnico", codigo, primeira))
    quantidade_feita = False
    for n, trecho in paginas:
        evidencia_id = f"EV-{objeto_id}#p{n}"
        base["evidencias"].append(_evidencia(evidencia_id, documento, n, trecho))
        base["fatos"].append(_fato(objeto_id, f"#p{n}", "mencao", trecho, evidencia_id))
        if not quantidade_feita:
            valor, unidade = vocabulario.quantidade(trecho, termos)
            if valor and valor > 0:
                base["fatos"].append(
                    _fato(objeto_id, "#qtd", "quantidade", valor, evidencia_id)
                )
                base["fatos"].append(
                    _fato(objeto_id, "#un", "unidade_medida", unidade, evidencia_id)
                )
                quantidade_feita = True


def de_documentos(base_documentos: list[dict], raiz: Path, itens=None) -> dict:
    """Base `{gaveta: [registros]}` com `objetos`, `fatos`, `evidencias` e `pendencias` das menções (mais `lidos`, as
    contagens para o `resumo`, que não é gaveta).

    Um objeto `mencao_documento` por (documento, item com ao menos uma página); um fato `mencao` por página; fatos
    `quantidade` e `unidade_medida` só quando o trecho traz "número + unidade" (a primeira página que traz)."""
    lista = _itens_em_lista(itens)
    padroes = {it["codigo"]: re.compile(it["termos"]) for it in lista}
    termos = {it["codigo"]: [it["termos"]] for it in lista}
    base = {"objetos": [], "fatos": [], "evidencias": [], "pendencias": []}
    lidos = {"documentos": 0, "paginas": 0, "paginas_sem_texto": 0}
    for documento in base_documentos:
        if not _le_texto(documento):
            continue
        caminho = Path(raiz) / documento["arquivo"]
        if not caminho.exists():
            base["pendencias"].append(
                {
                    "objeto_id": documento["documento_id"],
                    "motivo": f"arquivo ausente: {caminho}",
                }
            )
            continue
        paginas = paginas_do_pdf(caminho)
        if documento["classe"] == "projeto" and not any(p.strip() for p in paginas):
            continue
        lidos["documentos"] += 1
        por_item: dict[str, list[tuple[int, str]]] = {}
        for n, texto in enumerate(paginas, 1):
            lidos["paginas"] += 1
            if not texto.strip():
                lidos["paginas_sem_texto"] += 1
                base["pendencias"].append(
                    {
                        "objeto_id": gavetas.id_pagina(documento["documento_id"], n),
                        "documento": documento["documento_id"],
                        "pagina": n,
                        "motivo": MOTIVO_SEM_TEXTO,
                    }
                )
                continue
            for codigo, trecho in _achados_da_pagina(texto, padroes).items():
                por_item.setdefault(codigo, []).append((n, trecho))
        for codigo in sorted(por_item):
            _mencoes_do_item(base, documento, codigo, por_item[codigo], termos[codigo])
    base["lidos"] = lidos
    return base


def resumo(base: dict) -> dict:
    """Documentos e páginas lidos, páginas sem texto, itens mencionados por documento, menções e menções com quantidade."""
    lidos = base.get("lidos", {})
    fatos = base.get("fatos", [])
    itens_por_documento = Counter(
        o["objeto_id"].split("-")[1]
        for o in base.get("objetos", [])
        if o.get("classe") == "mencao_documento"
    )
    itens = Counter(f["valor"] for f in fatos if f["propriedade"] == "item_tecnico")
    return {
        "documentos_lidos": lidos.get("documentos", 0),
        "paginas_lidas": lidos.get("paginas", 0),
        "paginas_sem_texto": lidos.get("paginas_sem_texto", 0),
        "mencoes": sum(f["propriedade"] == "mencao" for f in fatos),
        "mencoes_com_quantidade": sum(f["propriedade"] == "quantidade" for f in fatos),
        "itens_por_documento": dict(sorted(itens_por_documento.items())),
        "itens_mais_mencionados": itens.most_common(10),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Menções dos itens da EAP nos documentos de texto de uma obra."
    )
    ap.add_argument(
        "saida",
        help="pasta de saída da obra (ex.: saida/foz); a base fica em <saida>/base",
    )
    ap.add_argument(
        "--raiz",
        help="pasta dos documentos (padrão: inventario.pasta do exemplos/<obra>/obra.json)",
    )
    args = ap.parse_args(argv)
    saida = Path(args.saida)
    if args.raiz:
        raiz = Path(args.raiz)
    else:
        cfg = json.loads(
            (Path("exemplos") / saida.name / "obra.json").read_text(encoding="utf-8")
        )
        raiz = Path(cfg["inventario"]["pasta"])
    documentos = gavetas.ler(saida / "base")["documentos"]
    t0 = time.perf_counter()
    base = de_documentos(documentos, raiz)
    t1 = time.perf_counter()
    conferencia = {
        "documentos": documentos,
        **{g: base[g] for g in ("objetos", "fatos", "evidencias", "pendencias")},
    }
    erros = gavetas.conferir_base(conferencia)
    r = resumo(base)
    por_documento = sorted(r.pop("itens_por_documento").values())
    if por_documento:
        r["itens_por_documento (mín, mediana, máx)"] = [
            por_documento[0],
            por_documento[len(por_documento) // 2],
            por_documento[-1],
        ]
    print(json.dumps(r, ensure_ascii=False, indent=2))
    print(
        f"tempo: leitura e busca {t1 - t0:.1f} s; conferência {time.perf_counter() - t1:.1f} s"
    )
    print(f"conferir_base: {len(erros)} erro(s)")
    for e in erros[:20]:
        print(" -", e)
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
