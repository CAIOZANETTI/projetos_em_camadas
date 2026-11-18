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

import numpy as np

from . import eap, evidencias, gavetas, vocabulario
from .pdf_cad import CONCEITOS

CLASSES_DE_TEXTO = ("edital", "memorial", "laudo", "lista")
LEITOR_DE_TEXTO = "camadas.evidencias"
METODO = "camadas.gavetas_texto (regex de eap_geral.termos)"
TRECHO_MAX = 200
MOTIVO_SEM_TEXTO = "página sem texto (OCR é passe da escada)"
REGRAS = json.loads((CONCEITOS / "busca_texto.json").read_text(encoding="utf-8"))
NAO_E_QUANTIDADE = [
    re.compile(p) for p in REGRAS["numero_que_nao_e_quantidade"].values()
]
REGRA_TERMO_IGNORADO = "termo_ignorado"


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


def alternativas(regex: str) -> list[str]:
    """Alternativas de primeiro nível de uma regex de `termos` (o `|` fora de grupo e de colchete)."""
    saida, atual, profundidade, colchete, escapado = [], [], 0, False, False
    for c in regex:
        if escapado:
            escapado = False
        elif c == "\\":
            escapado = True
        elif colchete:
            colchete = c != "]"
        elif c == "[":
            colchete = True
        elif c in "()":
            profundidade += 1 if c == "(" else -1
        elif c == "|" and profundidade == 0:
            saida.append("".join(atual))
            atual = []
            continue
        atual.append(c)
    saida.append("".join(atual))
    return saida


def _fim_do_grupo(regex: str, inicio: int) -> int:
    """Posição logo depois do parêntese que fecha o grupo aberto em `inicio`."""
    profundidade, i = 0, inicio
    while i < len(regex):
        if regex[i] == "\\":
            i += 2
            continue
        profundidade += (regex[i] == "(") - (regex[i] == ")")
        i += 1
        if profundidade == 0:
            break
    return i


def _sem_olhar(regex: str) -> str:
    """A regex sem os `lookahead` e `lookbehind` (grupos inteiros), que não são palavra do termo."""
    saida, i = [], 0
    while i < len(regex):
        if regex.startswith(("(?!", "(?=", "(?<!", "(?<="), i):
            i = _fim_do_grupo(regex, i)
            continue
        saida.append(regex[i])
        i += 1
    return "".join(saida)


def palavras_do_termo(alternativa: str) -> list[str]:
    """Palavras (maiúsculas, sem acento) que a alternativa escreve: grupos viram a primeira opção, grupos opcionais
    somem, `\\b`, `.?` e classes de caractere não contam ('AS.?BUILT' → AS, BUILT)."""
    texto = re.sub(r"\\.", " ", _sem_olhar(alternativa))
    anterior = None
    while anterior != texto:
        anterior = texto
        texto = re.sub(
            r"\((?:\?:)?([^()|]*)(?:\|[^()]*)?\)(\?|\*)?",
            lambda m: " " if m[2] else f" {m[1]} ",
            texto,
        )
    return re.findall(r"[A-Z]{2,}", texto)


def termo_legivel(alternativa: str) -> str:
    """A alternativa como a gente procura no texto: as palavras em minúsculas ('as built')."""
    return " ".join(palavras_do_termo(alternativa)).lower()


def eh_sigla(alternativa: str) -> bool:
    """A alternativa é uma sigla presa por fronteira de palavra dos dois lados (`\\bMND\\b`, `\\bPVS?\\b`,
    `(?:^|[-(] ?)ALO\\b`): curta, mas precisa, porque a regex não casa pedaço de outra palavra. `ALO\\b` sem a fronteira
    da esquerda casa o fim de 'INTERVALO' e não é sigla."""
    return alternativa.endswith("\\b") and alternativa.startswith(("\\b", "(?:^"))


def motivo_estatico(palavras: list[str], regras: dict = REGRAS, sigla: bool = False) -> str | None:
    """Por que o termo não discrimina sem olhar o corpus: só stopwords ou poucas letras fora das stopwords (a sigla
    presa por fronteira de palavra, `eh_sigla`, não cai na regra das letras)."""
    uteis = [p for p in palavras if p.lower() not in regras["stopwords"]]
    letras = sum(len(p) for p in uteis)
    if not uteis:
        return "sem palavra útil (só stopwords)"
    if letras < regras["letras_uteis_minimas"] and not sigla:
        return f"menos de {regras['letras_uteis_minimas']} letras úteis ({letras})"
    return None


def _frequencia(padrao: re.Pattern, buscas: list[str]) -> float:
    """Frequência de documento: páginas com texto que o padrão acha ÷ páginas com texto."""
    achou = np.fromiter(
        (padrao.search(b) is not None for b in buscas), dtype=bool, count=len(buscas)
    )
    return float(achou.mean())


def _motivo_de_frequencia(
    palavras: list[str], freq: float, buscas: list[str], regras: dict
) -> str | None:
    """Por que o corpus diz que o termo não discrimina: frequência de documento acima do limiar (o das palavras úteis
    sozinhas ou, para duas palavras ou mais, o do termo composto) ou termo composto só de stopwords e palavras que
    sozinhas passam do limiar do termo composto ('da obra')."""
    composto = len(palavras) >= 2
    limiar = regras[
        "limiar_frequencia_multipalavra" if composto else "limiar_frequencia_documento"
    ]
    if freq > limiar:
        return f"frequência de documento {freq:.1%} acima de {limiar:.0%}"
    uteis = [p for p in palavras if p.lower() not in regras["stopwords"]]
    if composto and all(
        _frequencia(re.compile(rf"\b{p}\b"), buscas) > limiar for p in uteis
    ):
        return f"termo composto só de stopwords e palavras genéricas do corpus (acima de {limiar:.0%})"
    return None


def termos_da_busca(
    itens: list[dict], buscas: list[str], regras: dict = REGRAS
) -> tuple[dict, list[dict]]:
    """({código: regex das alternativas que ficam, ou None se nenhuma}, ignorados). Cada alternativa de `termos` fica ou
    sai pelo `motivo_estatico` e, com `minimo_paginas_para_frequencia` páginas com texto, pela frequência de documento
    (`buscas` = o texto de busca de cada página com texto). Cada alternativa que sai vira um registro `{item,
    alternativa, termo, motivo, frequencia}`: nada some em silêncio."""
    com_frequencia = len(buscas) >= regras["minimo_paginas_para_frequencia"]
    padroes, ignorados = {}, []
    for item in itens:
        mantidas = []
        for alternativa in alternativas(item["termos"]):
            palavras = palavras_do_termo(alternativa)
            motivo = motivo_estatico(palavras, regras, eh_sigla(alternativa))
            freq = None
            if motivo is None and com_frequencia:
                freq = _frequencia(re.compile(alternativa), buscas)
                motivo = _motivo_de_frequencia(palavras, freq, buscas, regras)
            if motivo is None:
                mantidas.append(alternativa)
                continue
            ignorados.append(
                {
                    "item": item["codigo"],
                    "alternativa": alternativa,
                    "termo": " ".join(palavras).lower(),
                    "motivo": motivo,
                    "frequencia": freq,
                }
            )
        padroes[item["codigo"]] = re.compile("|".join(mantidas)) if mantidas else None
    return padroes, ignorados


def _palavras_entre(texto: str, a: tuple[int, int], b: tuple[int, int]) -> int:
    """Palavras do texto entre dois trechos (0 se encostam ou se sobrepõem)."""
    primeiro, segundo = sorted((a, b))
    return (
        len(texto[primeiro[1] : segundo[0]].split()) if primeiro[1] < segundo[0] else 0
    )


def _sobrepoe(
    trecho_do_numero: tuple[int, int], bloqueios: list[tuple[int, int]]
) -> bool:
    """O número cai dentro de notação científica, ano, CEP, telefone, código de material ou número de página."""
    return any(
        a < trecho_do_numero[1] and trecho_do_numero[0] < b for a, b in bloqueios
    )


def _candidata_de_contagem(
    trecho: str, limpo: str, achado: re.Match, bloqueios: list[tuple[int, int]]
) -> tuple | None:
    """'Número + termo no plural' colados ('6 TUBOS', '3 PARA-RAIOS') valem `un`; o número de uma lista numerada
    ('13 CONEXAO PRIMARIO'), com palavra no meio ou termo no singular, não é contagem."""
    antes = vocabulario.QTD_ANTES.search(limpo[: achado.start()])
    fim = trecho.find(" ", achado.end())
    plural = trecho[achado.start() : fim if fim >= 0 else len(trecho)].endswith("S")
    if not (antes and plural) or _sobrepoe(antes.span(1), bloqueios):
        return None
    if vocabulario._de_outra_unidade(limpo, antes, achado.start()):
        return None
    palavras = _palavras_entre(trecho, antes.span(1), achado.span())
    if palavras:
        return None
    return (palavras, antes.start(), vocabulario.numero_br(antes[1]), "un")


def candidata_do_trecho(
    trecho: str, padrao: re.Pattern, unidades: list[str], regras: dict = REGRAS
) -> dict | None:
    """A quantidade candidata do trecho: 'número + unidade' com unidade entre as `unidades` admitidas pelo item (ou
    'número + termo no plural' colados, que vale `un`, se `un` é admitida) a no máximo `palavras_ate_o_termo` palavras do
    termo; a mais próxima do termo. Número de `numero_que_nao_e_quantidade` (notação científica, ano, CEP, telefone,
    código, página, norma e rótulo de especificação) e dimensão de especificação (DN 150) não valem.
    Devolve {valor, unidade, palavras} ou None."""
    achado = padrao.search(trecho)
    if not achado:
        return None
    limpo = vocabulario.DIMENSAO.sub(lambda d: " " * len(d[0]), trecho)
    bloqueios = [m.span() for p in NAO_E_QUANTIDADE for m in p.finditer(trecho)]
    candidatas = []
    for m in vocabulario.QTD_DEPOIS.finditer(limpo):
        valor, unidade = vocabulario.converter(
            vocabulario.numero_br(m[1]), vocabulario.GRAFIAS[m[2]]
        )
        if unidade in unidades and not _sobrepoe(m.span(1), bloqueios):
            palavras = _palavras_entre(trecho, m.span(), achado.span())
            candidatas.append((palavras, m.start(), valor, unidade))
    contagem = (
        _candidata_de_contagem(trecho, limpo, achado, bloqueios)
        if "un" in unidades
        else None
    )
    validas = [
        c
        for c in candidatas + [contagem]
        if c and c[0] <= regras["palavras_ate_o_termo"] and c[2] > 0
    ]
    if not validas:
        return None
    palavras, _, valor, unidade = min(validas)
    return {"valor": valor, "unidade": unidade, "palavras": palavras}


def forca_da_mencao(trecho: str, mantidas: list[str], unidades: list[str]) -> dict:
    """A força de uma menção (trecho de uma página): `chave` para ordenar (maior = mais forte) = (tem candidata com
    unidade admitida, palavras do termo mais específico que casa, nº de termos que casam), o `termo` mais específico que
    casa e a `candidata` (ou None)."""
    casam = [(len(palavras_do_termo(a)), a) for a in mantidas if re.search(a, trecho)]
    especifico = max(casam, default=(0, ""))
    candidata = (
        candidata_do_trecho(trecho, re.compile("|".join(mantidas)), unidades)
        if casam
        else None
    )
    return {
        "chave": (candidata is not None, especifico[0], len(casam)),
        "termo": termo_legivel(especifico[1]) if casam else None,
        "candidata": candidata,
    }


def _achados_da_pagina(medir: str, buscar: str, padroes: dict) -> dict[str, str]:
    """{item: trecho} do primeiro termo de cada item que casa na página (`padroes`: o `termos_da_busca`)."""
    achados = {}
    for codigo, padrao in padroes.items():
        m = padrao.search(buscar) if padrao else None
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


def _melhor_candidata(
    paginas: list, padrao: re.Pattern, unidades: list[str]
) -> tuple[int, dict] | None:
    """(página, candidata) da menção cuja quantidade candidata está mais perto do termo; None se nenhuma página tem."""
    achadas = [
        (n, candidata_do_trecho(trecho, padrao, unidades)) for n, trecho in paginas
    ]
    achadas = [(c["palavras"], n, c) for n, c in achadas if c]
    return min(achadas, key=lambda a: a[:2])[1:] if achadas else None


def _mencoes_do_item(
    base: dict,
    documento: dict,
    codigo: str,
    paginas: list,
    padrao: re.Pattern,
    unidades: list[str],
) -> None:
    """Objeto, fato do item, um fato `mencao` por página e, na página cuja quantidade candidata (unidade admitida pelo
    item, perto do termo) está mais perto do termo, os fatos `quantidade` e `unidade_medida`."""
    objeto_id = f"txt-{documento['documento_id']}-{codigo}"
    base["objetos"].append({"objeto_id": objeto_id, "classe": "mencao_documento"})
    primeira = f"EV-{objeto_id}#p{paginas[0][0]}"
    base["fatos"].append(_fato(objeto_id, "#item", "item_tecnico", codigo, primeira))
    for n, trecho in paginas:
        evidencia_id = f"EV-{objeto_id}#p{n}"
        base["evidencias"].append(_evidencia(evidencia_id, documento, n, trecho))
        base["fatos"].append(_fato(objeto_id, f"#p{n}", "mencao", trecho, evidencia_id))
    melhor = _melhor_candidata(paginas, padrao, unidades)
    if melhor:
        n, candidata = melhor
        evidencia_id = f"EV-{objeto_id}#p{n}"
        base["fatos"].append(
            _fato(objeto_id, "#qtd", "quantidade", candidata["valor"], evidencia_id)
        )
        base["fatos"].append(
            _fato(
                objeto_id, "#un", "unidade_medida", candidata["unidade"], evidencia_id
            )
        )


def _paginas_com_texto(
    base_documentos: list[dict], raiz: Path, base: dict, lidos: dict
) -> list[dict]:
    """Lê os PDFs de texto: uma entrada `{documento, pagina, medir, buscar}` por página com texto; arquivo ausente e
    página sem texto viram pendência, e `lidos` conta documentos e páginas."""
    paginas = []
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
        textos = paginas_do_pdf(caminho)
        if documento["classe"] == "projeto" and not any(t.strip() for t in textos):
            continue
        lidos["documentos"] += 1
        for n, texto in enumerate(textos, 1):
            lidos["paginas"] += 1
            if texto.strip():
                medir, buscar = _pagina_preparada(texto)
                paginas.append(
                    {
                        "documento": documento,
                        "pagina": n,
                        "medir": medir,
                        "buscar": buscar,
                    }
                )
                continue
            lidos["paginas_sem_texto"] += 1
            base["pendencias"].append(
                {
                    "objeto_id": gavetas.id_pagina(documento["documento_id"], n),
                    "documento": documento["documento_id"],
                    "pagina": n,
                    "motivo": MOTIVO_SEM_TEXTO,
                }
            )
    return paginas


def _pendencia_de_termo(ignorado: dict) -> dict:
    """O termo que saiu da busca como pendência `termo_ignorado` (o roteiro do próximo passe lê estas linhas)."""
    return {
        "objeto_id": f"termo:{ignorado['item']}",
        "regra": REGRA_TERMO_IGNORADO,
        "motivo": ignorado["motivo"],
        "detalhe": ignorado["alternativa"],
    }


def de_documentos(
    base_documentos: list[dict], raiz: Path, itens=None, regras: dict = REGRAS
) -> dict:
    """Base `{gaveta: [registros]}` com `objetos`, `fatos`, `evidencias` e `pendencias` das menções (mais `lidos`, as
    contagens para o `resumo`, que não é gaveta).

    A busca usa só os termos que discriminam no corpus (`termos_da_busca`); os que saíram ficam em `pendencias`
    (regra `termo_ignorado`, com o motivo). Um objeto `mencao_documento` por (documento, item com ao menos uma página);
    um fato `mencao` por página; fatos `quantidade` e `unidade_medida` só quando o trecho traz "número + unidade" admitida
    pelo item e perto do termo (a página em que a quantidade está mais perto do termo)."""
    lista = _itens_em_lista(itens)
    base = {"objetos": [], "fatos": [], "evidencias": [], "pendencias": []}
    lidos = {"documentos": 0, "paginas": 0, "paginas_sem_texto": 0}
    paginas = _paginas_com_texto(base_documentos, raiz, base, lidos)
    padroes, ignorados = termos_da_busca(lista, [p["buscar"] for p in paginas], regras)
    base["pendencias"] += [_pendencia_de_termo(i) for i in ignorados]
    unidades = {r["codigo"]: r["unidades"] for r in evidencias.roteiro()}
    por_documento: dict[str, dict[str, list]] = {}
    for p in paginas:
        for codigo, trecho in _achados_da_pagina(
            p["medir"], p["buscar"], padroes
        ).items():
            por_documento.setdefault(p["documento"]["documento_id"], {}).setdefault(
                codigo, []
            ).append((p["pagina"], trecho))
    documentos = {d["documento_id"]: d for d in base_documentos}
    for documento_id, por_item in por_documento.items():
        for codigo in sorted(por_item):
            todas = list(vocabulario.REGRAS["unidades"])
            _mencoes_do_item(
                base,
                documentos[documento_id],
                codigo,
                por_item[codigo],
                padroes[codigo],
                unidades.get(codigo, todas),
            )
    base["lidos"] = {**lidos, "termos_ignorados": len(ignorados)}
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
        "termos_ignorados": lidos.get("termos_ignorados", 0),
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
