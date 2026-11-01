"""Escopo da obra: cada sistema construtivo dentro ou fora do escopo, decomposto em tudo o que se constrói, com a
evidência de cada parte e o link do projeto de onde veio.

    estado   = convenção do desenho 004 (pegada do sistema × manchas de etapa), manual (obra.json) ou contrato (redes);
               sem regra que se aplique, 'a definir'
    partes   = decomposição da tipologia do sistema (`conceitos/construcao_civil.json`); cada parte é 'geometria' (há
               elemento vetor da classe no sistema), 'documento' (só há trecho de texto) ou 'sem evidência'
    evidência = trecho real, nunca deduzido: linha da Relação de Desenhos, frase de memorial/descritivo/TR, item do
               contrato (sem preço) ou desenho da geometria. Uma frase vale para o sistema quando ela, ou o título da
               seção em que está, cita o sistema pelas `chaves` de `conceitos/unidades_construtivas.json`
    desenhos  = cada linha da Relação de Desenhos pertence a um sistema pela regra `desenhos` (código no nome do desenho
               e, quando o código se repete, a coluna unidade); `entregue` = o desenho existe na listagem do Drive

Lê `dados` (o que `obra.construir` já calculou) e os PDFs de texto do inventário que estão em disco (PyMuPDF). Sem
IA: só regex e geometria.
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from functools import cache
from pathlib import Path

import numpy as np
import shapely
from shapely import make_valid
from shapely.geometry import shape

from . import construtivos, geo
from .inventario import normalizar
from .pdf_cad import CONCEITOS

CIVIL = json.loads((CONCEITOS / "construcao_civil.json").read_text(encoding="utf-8"))
SISTEMAS = construtivos.REGRAS["sistemas"]
LINK = "https://drive.google.com/file/d/{}/view"
RANK = {"geometria": 0, "contrato": 1, "relacao": 2, "frase": 3, "cabecalho": 4, "arquivo": 5}
FRASES = re.compile(r"(?<=[.;])\s+(?=[A-ZÀ-Ý•\-–])")
MARCADOR = re.compile(r"^[•\-–—]\s")
RUIDO = re.compile(CIVIL["documentos"]["ruido"])
CODIGO = re.compile(construtivos.REGRAS["relacao"]["codigo"])
REVISAO = re.compile(r"-R(\d+)$", re.IGNORECASE)
UNIDADES = re.compile(r"\bL/s\b|\bm[²³]\b|\bmm\b|\bkV\b")


@cache
def _char(c: str) -> str:
    n = unicodedata.normalize("NFKD", c).encode("ascii", "ignore").decode()
    return n[:1].upper() if n else " "


def _norm(texto: str) -> str:
    """Sem acento, maiúsculas, '_' como espaço, do mesmo tamanho do original (o índice do casamento vale no texto)."""
    return "".join(" " if c == "_" else _char(c) for c in texto)


@cache
def _regras(codigo: str):
    """(fortes, ambíguas, exclui) do sistema, compiladas; '~' marca a chave ambígua."""
    s = SISTEMAS.get(codigo, {})
    chaves = s.get("chaves", [])
    junta = lambda lista: re.compile("|".join(lista)) if lista else None
    return (junta([c for c in chaves if not c.startswith("~")]), junta([c[1:] for c in chaves if c.startswith("~")]),
            junta(s.get("exclui", [])))


def _casa(codigo: str, norm: str) -> bool:
    """O texto (já normalizado) cita o sistema: chave forte, ou chave ambígua sem nenhum `exclui`."""
    forte, ambigua, exclui = _regras(codigo)
    if forte and forte.search(norm):
        return True
    return bool(ambigua and ambigua.search(norm) and not (exclui and exclui.search(norm)))


def _excluido(codigo: str, norm: str) -> bool:
    """O texto cita outro sistema da mesma família (ex.: DN300 para a drenagem DN400)."""
    exclui = _regras(codigo)[2]
    return bool(exclui and exclui.search(norm))


def _trecho(frase: str, inicio: int = 0) -> str:
    """Até `trecho_caracteres` do texto original, centrado no casamento, com reticências nas pontas cortadas."""
    n = CIVIL["limites"]["trecho_caracteres"] - 2
    if len(frase) <= n + 2:
        return frase
    ini = max(0, min(inicio - n // 3, len(frase) - n))
    corte = frase[ini:ini + n]
    if ini:
        corte = corte.split(" ", 1)[-1]
    if ini + n < len(frase):
        corte = corte.rsplit(" ", 1)[0]
    return ("…" if ini else "") + corte.strip() + ("…" if ini + n < len(frase) else "")


def _pdfs_drive(cfg: dict) -> list:
    """[{pasta, arquivo, id}] dos PDFs da listagem recursiva (`inventario.listagem`); vazio se não houver."""
    caminho = Path((cfg.get("inventario") or {}).get("listagem") or "")
    if not caminho.is_file():
        return []
    nfc = lambda texto: unicodedata.normalize("NFC", texto)
    with caminho.open(encoding="utf-8", newline="") as f:
        return [{"pasta": nfc(r["caminho"]), "arquivo": nfc(r["titulo"]), "id": r["id"]}
                for r in csv.DictReader(f, delimiter=";") if r["mimeType"] == "application/pdf"]


def _ids_drive(cfg: dict) -> dict:
    """{(pasta, arquivo): id do Drive} da listagem."""
    return {(d["pasta"], d["arquivo"]): d["id"] for d in _pdfs_drive(cfg)}


def _registro(dados: dict, cfg: dict) -> dict:
    """{doc_id: documento} dos PDFs do inventário; id = nome sem extensão (com a pasta quando o nome se repete)."""
    itens = (dados.get("inventario") or {}).get("itens") or []
    ids = _ids_drive(cfg)
    repetidos = {k for k, n in Counter(Path(i["arquivo"]).stem for i in itens).items() if n > 1}
    pranchas = {normalizar(Path(p["pdf"]).stem): p for p in dados.get("pranchas", []) if p.get("pdf")}
    registro = {}
    for i in itens:
        stem = Path(i["arquivo"]).stem
        ident = f"{stem} · {i['pasta_drive']}" if stem in repetidos else stem
        drive = ids.get((unicodedata.normalize("NFC", i["pasta_drive"]), unicodedata.normalize("NFC", i["arquivo"])))
        p = pranchas.get(normalizar(stem))
        registro[ident] = {"titulo": p["nome"] if p else stem, "arquivo": i["arquivo"], "link": LINK.format(drive) if drive else None,
                           "prancha": p["id"] if p else None, "tipo": "prancha" if p else
                           "memorial" if re.search(CIVIL["documentos"]["memorial"], _norm(i["arquivo"])) else "documento",
                           "item": i}
    return registro


def _publicar(ctx: dict, doc: str) -> str:
    """Põe o documento no resultado (sem os campos internos) e devolve o id; id fora do inventário vira documento sem link."""
    if doc not in ctx["saida"]:
        d = ctx["registro"].get(doc)
        if d is None:
            p = ctx["pranchas"].get(normalizar(doc))
            d = {"titulo": p["nome"] if p else doc, "arquivo": f"{doc}.pdf", "link": None,
                 "prancha": p["id"] if p else None, "tipo": "prancha" if p else "documento"}
        ctx["saida"][doc] = {k: d[k] for k in ("titulo", "arquivo", "tipo", "link", "prancha")}
    return doc


def _doc_contrato(ctx: dict, tabela: str) -> str:
    """Um documento por tabela do contrato: título = nome da tabela; prancha = o desenho da tabela, se estiver no mapa."""
    ident = f"contrato-T{tabela}"
    if ident not in ctx["saida"]:
        itens = ctx["itens"][tabela]
        stem = (ctx["escopo"].get("desenhos_por_tabela") or {}).get(tabela)
        p = ctx["pranchas"].get(normalizar(stem)) if stem else None
        planilha = re.match(r"(.*?\.xlsx)", ctx["escopo"].get("fonte") or "")
        ctx["saida"][ident] = {"titulo": itens[0]["nome_tabela"], "arquivo": planilha[1] if planilha else "contrato",
                               "tipo": "contrato", "link": None, "prancha": p["id"] if p else None}
    return ident


def _ev(ctx: dict, doc: str, trecho: str | None = None, pagina: int | None = None) -> dict:
    """Evidência {doc, trecho, pagina}; o documento entra no resultado."""
    if not doc.startswith("contrato-T"):
        _publicar(ctx, doc)
    return {"doc": doc, "trecho": trecho, "pagina": pagina}


def _eh_titulo(linha: str) -> bool:
    """Linha curta quase toda em maiúsculas ('3.2 GUARITA', 'ADUTORA DE ÁGUA BRUTA AAT06')."""
    letras = [c for c in UNIDADES.sub("", linha) if c.isalpha()]
    return (len(letras) >= 4 and len(linha) <= 140 and not linha.endswith((".", ";", ","))
            and sum(c.isupper() for c in letras) / len(letras) >= 0.85)


def _blocos(texto: str) -> list:
    """[('titulo'|'texto', linha ou parágrafo)] de uma página; parágrafo = linhas coladas até a linha em branco."""
    saida, atual = [], []

    def fechar():
        if atual:
            saida.append(("texto", " ".join(atual)))
            atual.clear()

    for linha in texto.splitlines():
        linha = " ".join(linha.split())
        if not linha:
            fechar()
        elif _eh_titulo(linha):
            fechar()
            saida.append(("titulo", linha))
        else:
            if MARCADOR.match(linha):
                fechar()
            atual.append(linha)
    fechar()
    return saida


def _sem_cabecalho(paginas: list) -> list:
    """Tira de cada página o cabeçalho/rodapé: linha que se repete em 40 % das páginas (mínimo 3) e está nas 8 primeiras ou
    5 últimas linhas da página, e 'Página N de M'. Parágrafo repetido no meio do texto (cláusula de cada UC) fica."""
    paginas_linhas = [[" ".join(x.split()) for x in texto.splitlines()] for texto in paginas]
    pontas = [{l for l in [l for l in ls if l][:8] + [l for l in ls if l][-5:]} for ls in paginas_linhas]
    contagem = Counter(l for conjunto in pontas for l in conjunto)
    repetida = {l for l, n in contagem.items() if n >= max(3, 0.4 * len(paginas))}
    return ["\n".join(l for l in ls if l not in repetida and not re.match(r"P[áa]gina\s+\d+", l)) for ls in paginas_linhas]


def _frases(doc: str, pagina: int, paragrafo: str, cab: str) -> list:
    """Frases úteis de um parágrafo: 25+ caracteres, sem preço ('R$') e sem a sujeira de tabela de medição."""
    saida = []
    for frase in FRASES.split(re.sub(r"\s*-{3,}>?\s*", " ", paragrafo)):
        if len(frase) >= 25 and "R$" not in frase and not RUIDO.search(_norm(frase)):
            saida.append({"doc": doc, "pagina": pagina, "frase": frase, "n": _norm(frase), "cab": _norm(cab)})
    return saida


def _passagens(doc: str, paginas: list) -> list:
    """Frases de um documento com a página e o título da seção (o último título visto, números soltos '3.' colam no próximo).

    O título vale para os `titulo_blocos` parágrafos seguintes; depois dele a seção é dada por encerrada."""
    saida, cab, prefixo, restante = [], "", "", 0
    for n, texto in enumerate(_sem_cabecalho(paginas), 1):
        for tipo, conteudo in _blocos(texto):
            restante = CIVIL["limites"]["titulo_blocos"] if tipo == "titulo" else restante - 1
            if tipo == "titulo":
                numero = re.fullmatch(r"\d+(\.\d+)*\.?", conteudo)
                prefixo, cab = (conteudo + " ", cab) if numero else ("", prefixo + conteudo)
                continue
            cab = cab if restante >= 0 else ""
            saida += _frases(doc, n, conteudo, cab)
    return saida


def _ler_relacao(caminho: Path) -> list:
    """Linhas da Relação de Desenhos pelas coordenadas das palavras: folha, arquivo, conteúdo e unidade construtiva."""
    import pymupdf
    linhas = []
    for n, pagina in enumerate(pymupdf.open(caminho), 1):
        palavras = pagina.get_text("words")
        for a in (w for w in palavras if re.match(r"\d{3}A?-SAA-", w[4])):
            y = (a[1] + a[3]) / 2
            mesma = sorted((w for w in palavras if abs((w[1] + w[3]) / 2 - y) < 4.5), key=lambda w: w[0])
            conteudo, unidade, anterior = [], [], None
            for w in (w for w in mesma if w[0] > a[2] + 1):
                destino = unidade if unidade or (anterior is not None and w[0] - anterior > 60) else conteudo
                destino.append(w[4])
                anterior = w[2]
            folha = " ".join(w[4] for w in mesma if w[0] < a[0] - 5)
            linhas.append({"pagina": n, "folha": folha, "stem": a[4], "conteudo": " ".join(conteudo), "unidade": " ".join(unidade)})
    return linhas


def _chave_desenho(stem: str) -> str:
    """Nome do desenho sem acento, minúsculo e sem a revisão: a Relação cita o R0 e o Drive pode ter o R1."""
    return REVISAO.sub("", normalizar(stem))


def _revisao(stem: str) -> str | None:
    m = REVISAO.search(stem)
    return f"R{m[1]}" if m else None


def _dono(r: dict) -> str | None:
    """Sistema da linha da Relação pela regra `desenhos`: código no nome do desenho (regex inteira) e, se a regra tem
    `unidade`, a coluna unidade (CXA01 e CXA02 existem em duas unidades). None quando nenhum sistema declara o código."""
    m = CODIGO.search(r["stem"].upper())
    unidade = _norm(r["unidade"])
    for codigo, s in SISTEMAS.items():
        for regra in s.get("desenhos", []):
            if m and re.fullmatch(regra["codigo"], m[1]) and re.search(regra.get("unidade", ""), unidade):
                return codigo
    return None


def _entrega(ctx: dict, stem: str, codigo: str, compartilhado: bool) -> tuple[dict | None, str | None]:
    """(arquivo da listagem do Drive, observação) do desenho citado. Vale o nome sem a revisão. Nome citado por mais de
    uma unidade: só o sistema cuja `pasta_drive` casa com a pasta do arquivo o recebe; os outros ficam sem entrega."""
    achados = ctx["drive"].get(_chave_desenho(stem), [])
    if compartilhado:
        pasta = SISTEMAS[codigo].get("pasta_drive")
        proprios = [d for d in achados if pasta and re.search(pasta, _norm(d["pasta"]))]
        if not proprios:
            return None, (f"Mesmo nome de arquivo em mais de uma unidade da Relação; o do Drive está em "
                          f"'{achados[0]['pasta'].rsplit('/', 1)[-1]}', de outra unidade" if achados else None)
        achados = proprios
    if not achados:
        return None, None
    d = next((d for d in achados if normalizar(Path(d["arquivo"]).stem) == normalizar(stem)), achados[0])
    rev_drive, rev_relacao = _revisao(Path(d["arquivo"]).stem), _revisao(stem)
    return d, (f"Drive tem a revisão {rev_drive}; a Relação cita {rev_relacao}" if rev_drive != rev_relacao else None)


def _doc_drive(ctx: dict, d: dict) -> str:
    """Id do documento de um arquivo do Drive: o do inventário; arquivo fora do inventário entra no registro com o link."""
    ident = ctx["por_arquivo"].get((d["pasta"], d["arquivo"]))
    if ident:
        return ident
    stem = Path(d["arquivo"]).stem
    p = ctx["pranchas"].get(normalizar(stem))
    ctx["registro"].setdefault(stem, {"titulo": p["nome"] if p else stem, "arquivo": d["arquivo"], "link": LINK.format(d["id"]),
                                      "prancha": p["id"] if p else None, "tipo": "prancha" if p else "documento"})
    return stem


def _desenhos(ctx: dict, corpus: dict) -> list:
    """Linhas da Relação de Desenhos com o sistema dono, o documento do Drive quando entregue (senão None) e a observação."""
    linhas = (corpus.get("relacao") or {}).get("linhas", [])
    donos = [_dono(r) for r in linhas]
    quem = defaultdict(set)
    for r, dono in zip(linhas, donos):
        quem[_chave_desenho(r["stem"])].add(dono)
    saida = []
    for r, dono in zip(linhas, donos):
        d, obs = _entrega(ctx, r["stem"], dono, len(quem[_chave_desenho(r["stem"])]) > 1) if dono else (None, None)
        saida.append({**r, "dono": dono, "doc": _doc_drive(ctx, d) if d else None, "obs": obs})
    return saida


def _lista_desenhos(ctx: dict, codigo: str) -> list:
    """Desenhos do sistema: arquivo, folha, conteúdo, se foi entregue e o documento (com link do Drive) quando foi."""
    return [{"arquivo": r["stem"], "folha": r["folha"], "conteudo": r["conteudo"], "entregue": bool(r["doc"]),
             "doc": _publicar(ctx, r["doc"]) if r["doc"] else None, **({"obs": r["obs"]} if r["obs"] else {})}
            for r in ctx["desenhos"] if r["dono"] == codigo]


def _contagem(ctx: dict, codigo: str) -> str:
    """'4 desenhos citados, 2 entregues' do sistema."""
    citados = [r for r in ctx["desenhos"] if r["dono"] == codigo]
    n, m = len(citados), sum(bool(r["doc"]) for r in citados)
    return f"{n} {'desenho citado' if n == 1 else 'desenhos citados'}, {m} {'entregue' if m == 1 else 'entregues'}"


def _ler_corpus(dados: dict, cfg: dict) -> dict:
    """{'textos': {arquivo: [texto por página]}, 'relacao': {'arquivo', 'linhas'}} dos PDFs de texto em disco."""
    import pymupdf
    pasta = Path((cfg.get("inventario") or {}).get("pasta") or "")
    textos, relacao = {}, None
    for i in (dados.get("inventario") or {}).get("itens", []):
        caminho = pasta / i["pasta_drive"] / i["arquivo"]
        alvo = _norm(i["arquivo"])
        if i["tipo"] != "documento" or not i["situacao"].startswith("no disco") or not caminho.is_file():
            continue
        if re.search(CIVIL["documentos"]["relacao"], alvo):
            relacao = {"arquivo": i["arquivo"], "linhas": _ler_relacao(caminho)}
        elif not re.search(CIVIL["documentos"]["ignorar"], alvo):
            textos[i["arquivo"]] = [p.get_text() for p in pymupdf.open(caminho)]
    return {"textos": textos, "relacao": relacao}


def _utm(geometria, epsg: int):
    return shapely.transform(geometria, lambda xy: np.column_stack(geo.para_utm(xy[:, 0], xy[:, 1], epsg)))


def _manchas(dados: dict, epsg: int) -> dict:
    """{classe: geometria UTM} das convenções de etapa da folha 04 (vetores f004-*), só as que a regra mapeia."""
    por = defaultdict(list)
    for v in dados.get("vetores", []):
        for f in v.get("geojson", {}).get("features", []) if v["id"].startswith("f004-") else []:
            if f["properties"].get("classe") in CIVIL["escopo"]["convencoes"]:
                por[f["properties"]["classe"]].append(make_valid(_utm(shape(f["geometry"]), epsg)))
    return {c: shapely.union_all(g) for c, g in por.items()}


def _pegada(feicoes: list, epsg: int):
    """(envoltória UTM, classes usadas): estacas, blocos e pilares; sem eles, as cavas; None sem nenhum."""
    regra = CIVIL["escopo"]["pegada"]
    for classes in (regra["classes"], regra["alternativa"]):
        gs = [_utm(shape(f["geometry"]), epsg) for f in feicoes if f["properties"]["classe"] in classes]
        if gs:
            uniao = shapely.union_all(gs)
            hull = uniao.convex_hull
            return (hull if hull.area >= 1 else uniao.buffer(regra["folga_m"])), "/".join(classes)
    return None, None


def _convencao(feicoes: list, manchas: dict, epsg: int) -> dict | None:
    """Sobreposição da pegada com cada mancha: {estado, classe, fracao, outras, area, base}; None sem pegada."""
    pegada, base = _pegada(feicoes, epsg)
    if pegada is None or not manchas:
        return None
    fracoes = {c: round(pegada.intersection(g).area / pegada.area, 3) for c, g in manchas.items()}
    fracoes = {c: f for c, f in sorted(fracoes.items(), key=lambda kv: -kv[1]) if f >= 0.01}
    classe, fracao = next(iter(fracoes.items()), (None, 0.0))
    valido = fracao >= CIVIL["escopo"]["fracao_minima"]["valor"]
    return {"estado": CIVIL["escopo"]["convencoes"][classe] if valido else "a definir", "classe": classe, "fracao": fracao,
            "outras": {c: f for c, f in fracoes.items() if c != classe}, "area": round(pegada.area, 1), "base": base}


def _texto_convencao(c: dict) -> str:
    """Frase do motivo: pegada, mancha dominante, o que a convenção diz e as manchas menores que também toca."""
    pct = lambda f: f"{round(100 * f)} %"
    outras = "; também toca " + ", ".join(f"'{k}' {pct(v)}" for k, v in c["outras"].items()) if c["outras"] else ""
    if c["classe"] is None:
        return f"pegada ({c['area']} m², {c['base']}) não toca nenhuma mancha de convenção da folha 04"
    if c["estado"] == "a definir":
        return (f"pegada ({c['area']} m², {c['base']}) cobre no máximo {pct(c['fracao'])} de uma mancha de convenção da "
                f"folha 04 (mínimo {pct(CIVIL['escopo']['fracao_minima']['valor'])})" + outras)
    lado = "está na 1ª etapa" if c["estado"] == "dentro" else "fica fora da 1ª etapa"
    return (f"pegada ({c['area']} m², {c['base']}) cai {pct(c['fracao'])} na mancha '{c['classe']}' da folha 04, "
            f"convenção que {lado}" + outras)


def _tabelas(ctx: dict, codigo: str, redes: list) -> list:
    """Tabelas do contrato do sistema: pelo nome da tabela (chaves ou `tabelas`), pelo desenho da tabela ou, nas redes,
    por tubo × desenho."""
    escopo = ctx["escopo"]
    desenhos = escopo.get("desenhos_por_tabela") or {}
    nome = SISTEMAS.get(codigo, {}).get("tabelas", {}).get("nome")
    achadas = {t for t, itens in ctx["itens"].items()
               if _casa(codigo, _norm(itens[0]["nome_tabela"])) or (t in desenhos and _casa(codigo, _norm(desenhos[t])))
               or (nome and re.search(nome, _norm(itens[0]["nome_tabela"])))}
    pranchas = {p for r in redes if r["id"] == SISTEMAS.get(codigo, {}).get("rede", codigo) for p in r["pranchas"]}
    achadas |= {t for x in escopo.get("tubo_x_desenho") or [] if x["prancha"] in pranchas for t in x["tabelas"]}
    return sorted((t for t in achadas if t in ctx["itens"]), key=lambda t: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", t)])


def _linha_item(i: dict) -> str:
    """'item · código · descrição · qtde 1ª/2ª etapa (un)', sem preço."""
    return _trecho(f"{i['item']} · {i['codigo']} · {i['descricao']} · {i['q1']:g} / {i['q2']:g} ({i['un']})")


def _itens_do_sistema(ctx: dict, codigo: str, tabelas: list) -> list:
    """Itens das tabelas do sistema, sem os que citam outra família (DN300 na drenagem DN400)."""
    return [(t, i) for t in tabelas for i in ctx["itens"][t] if not _excluido(codigo, _norm(i["descricao"]))]


def _escopo_contrato(ctx: dict, codigo: str, redes: list, unidade: bool = False) -> dict | None:
    """Escopo pelo contrato: q1 > 0 dentro, só q2 fora. Rede sem tabela fica 'a definir'; unidade localizada sem tabela
    devolve None (a regra não se aplica)."""
    tabelas = _tabelas(ctx, codigo, redes)
    itens = _itens_do_sistema(ctx, codigo, tabelas)
    if not itens:
        return None if unidade else {
            "estado": "a definir", "origem": "sem regra", "evidencias": [],
            "motivo": "Rede sem tabela de itens no contrato ligada ao desenho (escopo.tubo_x_desenho, desenhos_por_tabela)"}
    n1, n2 = sum(i["q1"] > 0 for _, i in itens), sum(i["q2"] > 0 for _, i in itens)
    estado = "dentro" if n1 else "fora"
    nomes = "; ".join(f"T{t} {ctx['itens'][t][0]['nome_tabela']}" for t in tabelas)
    motivo = f"Contrato: {len(itens)} itens nas tabelas {nomes}, {n1} com quantidade na 1ª etapa e {n2} na 2ª; "
    if unidade:
        motivo += (f"unidade '{estado}' pelo contrato, pois a convenção da folha 04 não a decide ({_contagem(ctx, codigo)}): "
                   f"{SISTEMAS[codigo]['tabelas']['fonte']}")
        destaque = [next((t, i) for t, i in itens if t == tabela) for tabela in dict.fromkeys(t for t, _ in itens)][:2]
    else:
        motivo += f"rede '{estado}' pela regra de rede: o contrato é o escopo da obra linear"
        destaque = sorted(itens, key=lambda ti: not re.search(r"\bTUBOS?\b", _norm(ti[1]["descricao"])))[:2]
    return {"estado": estado, "origem": "contrato", "motivo": motivo,
            "evidencias": [_ev(ctx, _doc_contrato(ctx, t), _linha_item(i)) for t, i in destaque]}


def _evidencia_regra(ctx: dict) -> list:
    """O documento da regra de etapa (frase real da 1ª etapa) e o desenho 004 de onde vêm as manchas."""
    arquivo = (ctx["cfg_escopo"].get("documento_regra") or "")
    evs = []
    p = next((p for p in ctx["passagens"] if p["doc"] == Path(arquivo).stem
              and re.search(CIVIL["escopo"]["trecho_regra"], p["n"])), None)
    if arquivo:
        evs.append(_ev(ctx, Path(arquivo).stem, _trecho(p["frase"]) if p else None, p["pagina"] if p else None))
    f004 = ctx["pranchas_id"].get("f004")
    if f004 and f004.get("pdf"):
        evs.append(_ev(ctx, Path(f004["pdf"]).stem))
    return evs


def _frases_de_escopo(ctx: dict, codigo: str) -> list:
    """Frases que citam o sistema e falam de etapa/escopo/execução (as de ETAPA primeiro), no máximo 3."""
    palavras = re.compile(CIVIL["escopo"]["palavras_escopo"])
    base = ctx["por_sistema"][codigo]
    achadas = [p for p in base["frase"] + base["cabecalho"] if palavras.search(p["n"])]
    achadas.sort(key=lambda p: "ETAPA" not in p["n"])
    return [_ev(ctx, p["doc"], _trecho(p["frase"], palavras.search(p["n"]).start()), p["pagina"]) for p in achadas[:3]]


def _escopo_sistema(ctx: dict, codigo: str, feicoes: list) -> dict:
    """Estado do sistema, origem, motivo e evidências: manual > rede (contrato) > convenção > unidade pelo contrato >
    sem regra."""
    s = SISTEMAS.get(codigo, {})
    cfg_e = ctx["cfg_escopo"]
    manual = (cfg_e.get("manual") or {}).get(codigo)
    tipologia = CIVIL["tipologias"].get(s.get("tipologia"), {})
    conv = None
    if "rede" not in s and tipologia.get("pegada", True) and ctx["manchas"]:
        conv = _convencao(feicoes, ctx["manchas"], ctx["epsg"])
    if manual:
        pela = f" (pela convenção do desenho 004, a {_texto_convencao(conv)})" if conv and conv["estado"] != "a definir" else ""
        return {"estado": manual["estado"], "origem": "manual", "motivo": f"Definido à mão: {manual['fonte']}{pela}",
                "evidencias": _evidencia_regra(ctx) if conv else []}
    if "rede" in s:
        r = _escopo_contrato(ctx, codigo, ctx["redes"])
        return {**r, "evidencias": r["evidencias"] + _frases_de_escopo(ctx, codigo)}
    if conv and conv["estado"] != "a definir":
        return {"estado": conv["estado"], "origem": "convenção", "motivo": "A " + _texto_convencao(conv) + ".",
                "evidencias": _evidencia_regra(ctx) + _frases_de_escopo(ctx, codigo)}
    if s.get("tabelas") and (r := _escopo_contrato(ctx, codigo, ctx["redes"], unidade=True)):
        return {**r, "evidencias": r["evidencias"] + _frases_de_escopo(ctx, codigo)}
    evidencias = _frases_de_escopo(ctx, codigo)
    if not tipologia.get("pegada", True):
        motivo = "Sistema geral: agrupa cavas e manchas de várias etapas, sem pegada única"
    elif conv:
        motivo = "A " + _texto_convencao(conv)
    elif not feicoes:
        motivo = f"Sem geometria no mapa (sem pegada para a convenção da folha 04); {_contagem(ctx, codigo)}"
        evidencias = [r["ev"] for r in ctx["por_sistema"][codigo]["relacao"][:1]] + evidencias
    else:
        motivo = "Sem estaca, bloco, pilar ou cava para medir a pegada"
    return {"estado": "a definir", "origem": "sem regra", "motivo": motivo + "; nenhuma regra se aplica.",
            "evidencias": evidencias}


def _geometria(ctx: dict, feicoes: list, classes: list) -> tuple[int, list]:
    """(nº de elementos, evidências): os documentos de origem dos elementos das classes, o mais frequente primeiro."""
    docs = Counter(f["properties"].get("doc") for f in feicoes if f["properties"]["classe"] in classes)
    n = sum(docs.values())
    return n, [_ev(ctx, d) for d, _ in docs.most_common() if d]


def _candidatas(ctx: dict, codigo: str, regex, contrato: bool) -> list:
    """(tipo, posição, evidência) das linhas da Relação, itens do contrato, frases e nomes de arquivo que casam a parte."""
    achadas, base = [], ctx["por_sistema"][codigo]
    for t, i in (base["itens"] if contrato else []):
        if m := regex.search(_norm(i["descricao"])):
            achadas.append(("contrato", m.start(), _ev(ctx, _doc_contrato(ctx, t), _linha_item(i))))
    for r in base["relacao"]:
        if m := regex.search(r["n"]):
            achadas.append(("relacao", m.start(), r["ev"]))
    for chave in ("frase", "cabecalho"):
        for p in base[chave]:
            if m := regex.search(p["n"]):
                achadas.append((chave, m.start(), _ev(ctx, p["doc"], _trecho(p["frase"], m.start()), p["pagina"])))
    for a in base["arquivo"]:
        if m := regex.search(a["n"]):
            achadas.append(("arquivo", m.start(), _ev(ctx, a["doc"], a["titulo"] if regex.search(a["nt"]) else None)))
    return achadas


def _escolher(achadas: list, geom: list) -> list:
    """Geometria primeiro, depois contrato, Relação, frases e arquivos; sem repetir (doc, trecho); respeita os limites."""
    lim = CIVIL["limites"]
    vistos, saida, relacao = set(), [], 0
    for ev in geom + [e for _, _, e in sorted(achadas, key=lambda a: RANK[a[0]])]:          # estável: ordem do documento
        chave = (ev["doc"], ev["trecho"])
        eh_relacao = (ev["trecho"] or "").startswith("Relação de Desenhos")
        if chave in vistos or len(saida) >= lim["evidencias_por_parte"] or (eh_relacao and relacao >= lim["relacao_por_parte"]):
            continue
        vistos.add(chave)
        relacao += eh_relacao
        saida.append(ev)
    return saida


def _decompor(ctx: dict, codigo: str, tipologia: str, feicoes: list) -> list:
    """Partes da tipologia do sistema com estado (geometria | documento | sem evidência), nº de elementos e evidências."""
    saida = []
    for pid in CIVIL["tipologias"].get(tipologia, {}).get("partes", []):
        parte = CIVIL["partes"][pid]
        n, geom = _geometria(ctx, feicoes, parte["classes_geometria"])
        evs = _escolher(_candidatas(ctx, codigo, re.compile(parte["palavras"]), parte.get("contrato", False)), geom)
        saida.append({"id": pid, "grupo": parte["grupo"], "nome": parte["nome"], "n_geometria": n, "evidencias": evs,
                      "estado": "geometria" if n else "documento" if evs else "sem evidência"})
    return saida


def _indice(ctx: dict, codigos: list, corpus: dict) -> dict:
    """Por sistema: itens do contrato, linhas da Relação, frases (próprias e do título da seção) e nomes de arquivo."""
    por = {c: {"itens": [], "relacao": [], "frase": [], "cabecalho": [], "arquivo": []} for c in codigos}
    redes = ctx["redes"]
    for c in codigos:
        por[c]["itens"] = _itens_do_sistema(ctx, c, _tabelas(ctx, c, redes))
    rel = corpus.get("relacao") or {}
    doc_rel = Path(rel.get("arquivo") or "").stem
    for r in ctx["desenhos"]:
        txt = " · ".join(x for x in ("Relação de Desenhos", r["unidade"], r["folha"], r["conteudo"]) if x)
        for c in codigos:
            if c == r["dono"] or _casa(c, _norm(f"{r['unidade']} {r['stem']}")):
                ev = _ev(ctx, r["doc"] or doc_rel, _trecho(txt), None if r["doc"] else r["pagina"])
                por[c]["relacao"].append({"n": _norm(r["conteudo"]), "ev": ev})
    for arquivo, paginas in corpus.get("textos", {}).items():
        doc = Path(arquivo).stem
        for p in _passagens(doc, paginas):
            for c in codigos:
                if _casa(c, p["n"]):
                    por[c]["frase"].append(p)
                elif p["cab"] and _casa(c, p["cab"]):
                    por[c]["cabecalho"].append(p)
    for i in (ctx["dados"].get("inventario") or {}).get("itens", []):
        _indexar_arquivo(por, codigos, i)
    return por


def _indexar_arquivo(por: dict, codigos: list, item: dict) -> None:
    """Nome do arquivo (e título do carimbo) como passagem; a última pasta só serve se o nome não identifica sistema."""
    doc = Path(item["arquivo"]).stem
    titulo = ((item.get("carimbo") or {}).get("titulo") or "")
    nt = _norm(f"{doc} {titulo}")
    donos = [c for c in codigos if _casa(c, nt)]
    donos = donos or [c for c in codigos if _casa(c, _norm(item["pasta_drive"].rsplit("/", 1)[-1]))]
    for c in donos:
        por[c]["arquivo"].append({"doc": doc, "n": nt, "nt": _norm(titulo), "titulo": _trecho(titulo) if titulo else None})


def _contexto(dados: dict, cfg: dict, corpus: dict) -> dict:
    """Tudo o que as funções precisam sem reler: registro de documentos, contrato por tabela, manchas, redes, passagens."""
    itens = defaultdict(list)
    for i in (dados.get("escopo") or {}).get("itens", []):
        itens[i["tabela"]].append(i)
    epsg = (dados.get("crs") or {}).get("epsg")
    registro, drive = _registro(dados, cfg), defaultdict(list)
    for d in _pdfs_drive(cfg):
        drive[_chave_desenho(Path(d["arquivo"]).stem)].append(d)
    nfc = lambda texto: unicodedata.normalize("NFC", texto)
    ctx = {"dados": dados, "saida": {}, "registro": registro, "itens": dict(itens), "drive": drive,
           "por_arquivo": {(nfc(v["item"]["pasta_drive"]), nfc(v["item"]["arquivo"])): k for k, v in registro.items()},
           "escopo": dados.get("escopo") or {}, "cfg_escopo": cfg.get("escopo_unidades") or {}, "epsg": epsg,
           "pranchas": {normalizar(Path(p["pdf"]).stem): p for p in dados.get("pranchas", []) if p.get("pdf")},
           "pranchas_id": {p["id"]: p for p in dados.get("pranchas", [])},
           "redes": (cfg.get("valas") or {}).get("redes", []),
           "manchas": _manchas(dados, epsg) if epsg else {}, "passagens": []}
    for arquivo, paginas in corpus.get("textos", {}).items():
        if Path(arquivo).stem == Path(ctx["cfg_escopo"].get("documento_regra") or "").stem:
            ctx["passagens"] = _passagens(Path(arquivo).stem, paginas)
    return ctx


def montar(dados: dict, cfg: dict, corpus: dict | None = None) -> dict | None:
    """Escopo por sistema: estado, origem, motivo, evidências e decomposição da tipologia. None sem construtivos.

    `corpus` ({'textos', 'relacao'}) vem dos PDFs em disco; o teste passa um corpus pequeno em vez de ler PDF.
    """
    c = dados.get("construtivos") or construtivos.montar(dados, cfg)
    if not c:
        return None
    corpus = _ler_corpus(dados, cfg) if corpus is None else corpus
    ctx = _contexto(dados, cfg, corpus)
    ctx["desenhos"] = _desenhos(ctx, corpus)
    sistemas = [(s["id"], s["id"].split("-", 1)[1]) for u in c["arvore"] for s in u["sistemas"]]
    ctx["por_sistema"] = _indice(ctx, [cod for _, cod in sistemas], corpus)
    feicoes = defaultdict(list)
    for f in c["geojson"]["features"]:
        feicoes[f["properties"]["sistema"]].append(f)
    saida = {}
    for sid, codigo in sistemas:
        tipologia = SISTEMAS.get(codigo, {}).get("tipologia")
        saida[sid] = {**_escopo_sistema(ctx, codigo, feicoes[sid]), "tipologia": tipologia or "desconhecida",
                      "decomposicao": _decompor(ctx, codigo, tipologia, feicoes[sid]),
                      "desenhos": _lista_desenhos(ctx, codigo)}
    regra = ctx["cfg_escopo"].get("documento_regra")
    na_arvore = [d for s in saida.values() for d in s["desenhos"]]
    entregues = sum(d["entregue"] for d in na_arvore)
    return {"regra": ctx["cfg_escopo"].get("regra") or CIVIL["escopo"]["fonte"],
            "documento_regra": _publicar(ctx, Path(regra).stem) if regra else None,
            "documentos": ctx["saida"], "sistemas": saida,
            "desenhos_resumo": {"citados": len(na_arvore), "entregues": entregues, "nao_entregues": len(na_arvore) - entregues},
            "desenhos_sem_sistema": [{"arquivo": r["stem"], "folha": r["folha"], "conteudo": r["conteudo"]}
                                     for r in ctx["desenhos"] if r["dono"] not in {cod for _, cod in sistemas}]}


def metadados() -> dict:
    """Rastreabilidade do método e das regras declaradas (regra 9 do estilo)."""
    regras = [("escopo.convencoes", CIVIL["escopo"]), ("escopo.pegada", CIVIL["escopo"]["pegada"]),
              ("escopo.fracao_minima", CIVIL["escopo"]["fracao_minima"]), ("escopo.rede", CIVIL["escopo"]["rede"]),
              ("escopo.contrato_unidade", CIVIL["escopo"]["contrato_unidade"]),
              ("desenhos.codigo", construtivos.REGRAS["relacao"])]
    regras += [(f"tipologias.{k}", v) for k, v in CIVIL["tipologias"].items()]
    regras += [(f"partes.{k}", v) for k, v in CIVIL["partes"].items()]
    return {
        "modulo": "escopo_obra",
        "descricao": "escopo por sistema construtivo (dentro/fora pela convenção da folha 04, manual ou contrato) e decomposição "
                     "em partes com evidência de documento, contrato ou geometria",
        "funcoes": ["montar", "metadados"],
        "bibliografia": [],
        "premissas": [{"aplicacao": {"montar": [nome]}, "fonte": v["fonte"], "estado": v["estado"]} for nome, v in regras],
        "ultima_revisao": CIVIL["metadata"]["data_referencia"],
    }
