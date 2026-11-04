"""EAP (WBS) codificada: a linha mestra que liga elemento construtivo, prancha e quantidade.

    código = UNIDADE.SISTEMA.DISCIPLINA.PACOTE.ITEM          ex.: U1.ACT600.GEO.FUN.EST (estacas do Actiflo 600)
    unidade, sistema   ← conceitos/unidades_construtivas.json (obra localizada × linear, escopo água × esgoto)
    disciplina, pacote ← conceitos/eap.json (GEO, CIV, HID, ELE)
    item               ← conceitos/eap_geral.jsonl (EAP geral: um item por linha, regra do loop de evidências)

    elemento construtivo (camadas.construtivos) ─► item EAP pela classe ─► quantidade pela regra do item
    prancha (grupo/subgrupo de disciplinas.json) ─► pacote EAP de que é evidência
    proposta de IA ─► `verificar` refaz a conta pelas evidências citadas: só passa o que confere

Determinístico: nenhuma quantidade nasce aqui sem um elemento (id) por trás; o que falta fica em `lacunas`, o que
não tem item fica em `sem_item`. O código mnemônico é a chave estável; o numérico (1.3.1.1.1) é só ordem.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

from . import geo
from .construtivos import REGRAS as UNIDADES
from .construtivos import _sistema
from .pdf_cad import CONCEITOS

REGRAS = json.loads((CONCEITOS / "eap.json").read_text(encoding="utf-8"))
GERAL = [json.loads(linha) for linha in (CONCEITOS / "eap_geral.jsonl").read_text(encoding="utf-8").splitlines()
         if linha.strip()]
NIVEIS = REGRAS["niveis"][1:]                       # unidade, sistema, disciplina, pacote, item (obra é a raiz)


def itens() -> dict:
    """{'GEO.FUN.EST': item da EAP geral + nomes da disciplina e do pacote}, na ordem da hierarquia (eap.json) e,
    dentro do pacote, na ordem do eap_geral.jsonl."""
    saida = {}
    for d in REGRAS["disciplinas"]:
        for p in d["pacotes"]:
            for it in GERAL:
                if it["codigo"].rsplit(".", 1)[0] == f"{d['codigo']}.{p['codigo']}":
                    saida[it["codigo"]] = {**it, "disciplina": d["nome"], "pacote": p["nome"]}
    return saida


def validar() -> list[str]:
    """Problemas do modelo (vazio = coerente): código repetido, regra, classe, layer ou subgrupo desconhecidos."""
    problemas = _problemas_de_codigos()
    problemas += _problemas_dos_itens()
    problemas += _problemas_de_vista()
    problemas += _problemas_de_pranchas()
    return problemas


def _problemas_de_codigos() -> list[str]:
    """Códigos repetidos na EAP geral (em ordem alfabética) e códigos cujo pacote não está em eap.json (na ordem do
    eap_geral.jsonl)."""
    codigos = [it["codigo"] for it in GERAL]
    problemas = [f"código repetido: {c}" for c in sorted({c for c in codigos if codigos.count(c) > 1})]
    modelo = itens()
    problemas += [f"{c}: pacote fora de eap.json" for c in codigos if c not in modelo]
    return problemas


def _problemas_dos_itens() -> list[str]:
    """Problemas de cada item da hierarquia (obra, escopo, serviço, classe, layer, medição), item a item, na ordem
    de `itens()`; lê servicos.jsonl e elementos.json na chamada."""
    servicos = {json.loads(linha)["id"] for linha in (CONCEITOS / "servicos.jsonl").read_text(encoding="utf-8").splitlines()
                if linha.strip()}
    classes = set(UNIDADES["classes"])
    layers = {c["id"] for c in json.loads((CONCEITOS / "elementos.json").read_text(encoding="utf-8"))["classes"]}
    problemas = []
    for codigo, it in itens().items():
        problemas += _problemas_de_obra_e_escopo(codigo, it)
        problemas += _problemas_de_referencias(codigo, it, servicos, classes, layers)
        problemas += _problemas_de_medicoes(codigo, it)
    return problemas


def _problemas_de_obra_e_escopo(codigo: str, it: dict) -> list[str]:
    """Tipo de obra fora de localizada | linear e escopo fora de `REGRAS["escopos"]`, nessa ordem."""
    problemas = [f"{codigo}: obra '{o}' desconhecida" for o in it["obra"] if o not in ("localizada", "linear")]
    problemas += [f"{codigo}: escopo '{e}' desconhecido" for e in it["escopo"] if e not in REGRAS["escopos"]]
    return problemas


def _problemas_de_referencias(codigo: str, it: dict, servicos: set, classes: set, layers: set) -> list[str]:
    """Serviço, classe construtiva e layer do item que não existem nos conceitos, nessa ordem."""
    problemas = [f"{codigo}: serviço '{v}' fora de servicos.jsonl" for v in it["servicos"] if v not in servicos]
    problemas += [f"{codigo}: classe construtiva '{c}' fora de unidades_construtivas" for c in it["construtivos"]
                  if c not in classes]
    problemas += [f"{codigo}: layer '{c}' fora de elementos.json" for c in it["layers"] if c not in layers]
    return problemas


def _problemas_de_medicoes(codigo: str, it: dict) -> list[str]:
    """Medições com regra desconhecida ou com `atributo` incoerente (só a regra `soma` leva atributo)."""
    return [f"{codigo}: medição {m} inválida" for m in it["medicoes"]
            if m["regra"] not in REGRAS["regras_medicao"] or (m["regra"] == "soma") != ("atributo" in m)]


def _problemas_de_pranchas() -> list[str]:
    """Subgrupos de prancha fora de disciplinas.json e pacotes-alvo inexistentes, subgrupo a subgrupo."""
    subgrupos = {s for g in json.loads((CONCEITOS / "disciplinas.json").read_text(encoding="utf-8"))["grupos"].values()
                 for s in g}
    pacotes = {f"{d['codigo']}.{p['codigo']}" for d in REGRAS["disciplinas"] for p in d["pacotes"]}
    problemas = []
    for sub, alvos in REGRAS["pranchas"].items():
        if sub not in subgrupos:
            problemas.append(f"pranchas: subgrupo '{sub}' fora de disciplinas.json")
        problemas += [f"pranchas: pacote '{a}' inexistente" for a in alvos if a not in pacotes]
    return problemas


VISTAS_DO_SISTEMA = ("linear",)
"""Valores admitidos para `vista_eap_padrao` de um sistema em `unidades_construtivas.json`."""


@lru_cache(maxsize=1)
def _vistas_dos_sistemas() -> dict[tuple[str, str], str]:
    """{(unidade, sistema em minúsculas): vista} dos sistemas com `vista_eap_padrao`."""
    return {(s["unidade"], c.lower()): s["vista_eap_padrao"]
            for c, s in UNIDADES["sistemas"].items() if s.get("vista_eap_padrao")}


def vista_do_codigo(codigo: str) -> str | None:
    """Vista da EAP padrão (localizada | linear) de um código `U1.SISTEMA.ITEM`: o sistema com `vista_eap_padrao` da
    própria unidade manda; senão vale a obra da unidade. None se a unidade é desconhecida (`U*`). Função só do código:
    o mesmo número nunca cai em duas vistas."""
    partes = (str(codigo).lower().split(".") + ["*"])[:2]
    return _vistas_dos_sistemas().get(tuple(partes)) or UNIDADES["unidades"].get(partes[0], {}).get("obra")


def eh_trecho_linear(codigo: str) -> bool:
    """O código é de sistema com vista linear dentro de unidade localizada (trecho declarado, D11)."""
    unidade = str(codigo).split(".")[0].lower()
    return vista_do_codigo(codigo) != UNIDADES["unidades"].get(unidade, {}).get("obra")


def _problemas_de_vista() -> list[str]:
    """Sistemas com `vista_eap_padrao` desconhecida ou em unidade inexistente."""
    problemas = []
    for codigo, s in UNIDADES["sistemas"].items():
        vista = s.get("vista_eap_padrao")
        if vista is not None and vista not in VISTAS_DO_SISTEMA:
            problemas.append(f"sistema {codigo}: vista_eap_padrao '{vista}' desconhecida; use {list(VISTAS_DO_SISTEMA)}")
        if vista is not None and s["unidade"] not in UNIDADES["unidades"]:
            problemas.append(f"sistema {codigo}: unidade '{s['unidade']}' inexistente")
    return problemas


def _sistemas() -> list[tuple[str, str, dict]]:
    """[(id da unidade, código do sistema, sistema)] na ordem do conceito de unidades."""
    return [(s["unidade"], codigo, s) for codigo, s in UNIDADES["sistemas"].items()]


def estrutura(sistemas: list[str] | None = None) -> list[dict]:
    """Nós da EAP instanciada: unidade > sistema > disciplina > pacote > item, só os itens do tipo de obra da
    unidade. `sistemas` (códigos) restringe e acrescenta sistemas fora do conceito, na ordem dada."""
    lista = [(u, c, s) for u, c, s in _sistemas() if sistemas is None or c in sistemas]
    lista += [(_sistema(c)["unidade"], c, _sistema(c)) for c in sistemas or [] if c not in UNIDADES["sistemas"]]
    nos = []
    for iu, (uid, u) in enumerate(UNIDADES["unidades"].items(), 1):
        cu = uid.upper()
        nos.append({"codigo": cu, "numero": f"{iu}", "nivel": "unidade", "nome": u["nome"], "pai": None, "obra": u["obra"]})
        for js, (_, cs, s) in enumerate([x for x in lista if x[0] == uid], 1):
            nos.append({"codigo": f"{cu}.{cs}", "numero": f"{iu}.{js}", "nivel": "sistema", "nome": s["nome"],
                        "pai": cu, "obra": u["obra"]})
            nos += _disciplinas(f"{cu}.{cs}", f"{iu}.{js}", u["obra"], u.get("escopo"))
    return nos


def _do_pacote(pacote: str, obra: str, escopo: str | None) -> list[tuple[int, dict]]:
    """[(ordem no pacote, item)] da EAP geral que valem para o tipo de obra e o escopo (None = qualquer escopo)."""
    todos = [it for it in GERAL if it["codigo"].rsplit(".", 1)[0] == pacote]
    return [(k, it) for k, it in enumerate(todos, 1) if obra in it["obra"] and (escopo is None or escopo in it["escopo"])]


def _disciplinas(pai: str, numero: str, obra: str, escopo: str | None) -> list[dict]:
    """Disciplina > pacote > item sob um sistema; pacote e disciplina sem item do tipo de obra/escopo ficam de fora."""
    nos = []
    for kd, d in enumerate(REGRAS["disciplinas"], 1):
        sub = []
        for kp, p in enumerate(d["pacotes"], 1):
            folhas = _do_pacote(f"{d['codigo']}.{p['codigo']}", obra, escopo)
            if not folhas:
                continue
            cp, npac = f"{pai}.{d['codigo']}.{p['codigo']}", f"{numero}.{kd}.{kp}"
            sub.append({"codigo": cp, "numero": npac, "nivel": "pacote", "nome": p["nome"],
                        "pai": f"{pai}.{d['codigo']}", "obra": obra})
            sub += [{"codigo": f"{pai}.{it['codigo']}", "numero": f"{npac}.{ki}", "nivel": "item", "nome": it["nome"],
                     "pai": cp, "obra": obra, "medicoes": it["medicoes"]} for ki, it in folhas]
        if sub:
            nos += [{"codigo": f"{pai}.{d['codigo']}", "numero": f"{numero}.{kd}", "nivel": "disciplina",
                     "nome": d["nome"], "pai": pai, "obra": obra}, *sub]
    return nos


def codigos_do_elemento(props: dict) -> list[str]:
    """Itens EAP de um elemento construtivo pela classe (uma cava alimenta escavação e reaterro)."""
    unidade, sistema = props["unidade"].upper(), props["sistema"].split("-", 1)[1]
    u = UNIDADES["unidades"].get(props["unidade"], {})
    return [f"{unidade}.{sistema}.{c}" for c, it in itens().items() if props["classe"] in it["construtivos"]
            and u.get("obra") in it["obra"] and (u.get("escopo") is None or u["escopo"] in it["escopo"])]


def anotar(construtivos: dict) -> dict:
    """Grava `eap` (lista de códigos) nas propriedades de cada elemento; devolve {id do elemento: códigos}."""
    saida = {}
    for f in construtivos["geojson"]["features"]:
        f["properties"]["eap"] = saida[f["properties"]["id"]] = codigos_do_elemento(f["properties"])
    return saida


def _utm(geometria: dict, epsg: int):
    g = shape(geometria)
    return shapely.transform(g, lambda xy: np.column_stack(geo.para_utm(xy[:, 0], xy[:, 1], epsg)))


def medir(feature: dict, medicao: dict, epsg: int) -> float | None:
    """Valor de um elemento numa medição do item; None se o elemento não tem o atributo pedido."""
    regra = medicao["regra"]
    if regra == "contagem":
        return 1.0
    if regra == "soma":
        valor = dict(feature["properties"]["atributos"]).get(medicao["atributo"])
        return float(valor) if isinstance(valor, (int, float)) else None
    g = _utm(feature["geometry"], epsg)
    return float(g.length if regra == "comprimento" else g.area)


def _linhas_de_medicao(features: list, epsg: int) -> list[dict]:
    """Uma linha por (elemento, item, medição): o valor medido e de onde veio."""
    modelo, linhas = itens(), []
    for f in features:
        p = f["properties"]
        for codigo in codigos_do_elemento(p):
            for m in modelo[codigo.split(".", 2)[2]]["medicoes"]:
                linhas.append({"codigo": codigo, "grandeza": m["grandeza"], "unidade": m["unidade"],
                               "valor": medir(f, m, epsg), "elemento": p["id"], "fonte": p["fonte"]})
    return linhas


def quantificar(construtivos: dict, epsg: int) -> pd.DataFrame:
    """Quantidade por item EAP e grandeza, com o número de elementos, os sem valor e as evidências (ids)."""
    colunas = ["codigo", "grandeza", "unidade", "quantidade", "n_elementos", "sem_valor", "evidencias", "fontes"]
    df = pd.DataFrame(_linhas_de_medicao(construtivos["geojson"]["features"], epsg))
    if df.empty:
        return pd.DataFrame(columns=colunas)
    q = df.groupby(["codigo", "grandeza", "unidade"], sort=False).agg(
        quantidade=("valor", lambda v: float(v.dropna().sum())), n_elementos=("elemento", "size"),
        sem_valor=("valor", lambda v: int(v.isna().sum())), evidencias=("elemento", list),
        fontes=("fonte", lambda v: sorted(set(v)))).reset_index()
    return q[colunas]


ETAPA_DA_FONTE = {"escavação calculada": "escavacao"}
"""Reserva: começo do texto `fonte` do elemento construtivo → etapa do build que o produziu, para elementos sem o
campo `origem_etapa`. É a mesma etapa que as gavetas declaram: as duas trilhas de uma escavação se reconhecem por ela."""


def origem_do_elemento(props: dict) -> set[str] | None:
    """Insumos de um elemento construtivo: `arquivo:<nome>` do documento (`doc`, o stem do PDF) e `etapa:<nome>` do
    campo estruturado `origem_etapa` que o `construtivos` grava; só de reserva, para elementos antigos, o começo do
    texto `fonte` (`ETAPA_DA_FONTE`). None (indeterminada) se não houver nenhum dos dois."""
    from . import gavetas
    insumos = {f"arquivo:{gavetas.nome_de_arquivo(props['doc'])}"} if props.get("doc") else set()
    etapa = props.get("origem_etapa")
    if not etapa:
        fonte = str(props.get("fonte") or "")
        etapa = next((e for inicio, e in ETAPA_DA_FONTE.items() if fonte.startswith(inicio)), None)
    return insumos | ({f"etapa:{etapa}"} if etapa else set()) or None


def origem_das_quantidades(quantidades: list[dict], construtivos: dict | None) -> dict[tuple, list[str] | None]:
    """{(código, unidade): insumos} de cada quantidade da EAP codificada, pela união dos insumos dos elementos que a
    compõem (`evidencias` = ids dos elementos). None se faltar o elemento ou a origem de algum deles."""
    features = {f["properties"]["id"]: f["properties"]
                for f in ((construtivos or {}).get("geojson") or {}).get("features", [])}
    saida: dict[tuple, list[str] | None] = {}
    for q in quantidades:
        chave = (q["codigo"], q["unidade"])
        partes = [origem_do_elemento(features[i]) if i in features else None for i in q.get("evidencias") or []]
        uniao = None if not partes or any(p is None for p in partes) else sorted(set().union(*partes))
        anterior = saida.get(chave, uniao)          # duas grandezas do mesmo (código, unidade): união; indeterminada contamina
        saida[chave] = None if anterior is None or uniao is None else sorted(set(anterior) | set(uniao))
    return saida


def consolidar(quant: pd.DataFrame, nivel: str) -> pd.DataFrame:
    """Soma no nível pedido (unidade, sistema, disciplina, pacote) sempre por tipo de item, grandeza e unidade de
    medida: 'estacas da U1' soma as estacas de todos os sistemas; un de bloco e un de pilar, ou m³ de escavação e
    de reaterro, nunca se somam."""
    partes = quant["codigo"].str.split(".")
    df = quant.assign(no=partes.str[:NIVEIS.index(nivel) + 1].str.join("."), item=partes.str[2:].str.join("."))
    return df.groupby(["no", "item", "grandeza", "unidade"], sort=False).agg(
        quantidade=("quantidade", "sum"), n_elementos=("n_elementos", "sum"), sem_valor=("sem_valor", "sum")
    ).reset_index()


def _unidade_da_prancha(prancha: dict) -> str:
    """Unidade linear se o nome do PDF casa com `linear` de tipos_prancha.json; senão a localizada."""
    linear = json.loads((CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))["linear"]
    tipo = "linear" if re.search(linear, prancha.get("pdf", "") or prancha.get("nome", ""), re.IGNORECASE) else "localizada"
    return next(uid.upper() for uid, u in UNIDADES["unidades"].items() if u["obra"] == tipo)


def evidencias_pranchas(pranchas: list, declarado: dict | None = None) -> list[dict]:
    """Pacotes EAP de que cada prancha é evidência: subgrupo → pacote; sistema '*' (qualquer) salvo se o obra.json
    declara `eap` na prancha (ex.: 'U1.ACT600'). Prancha sem subgrupo conhecido fica com pacotes vazio."""
    declarado = declarado or {}
    saida = []
    for p in pranchas:
        base = declarado.get(p["id"]) or f"{_unidade_da_prancha(p)}.*"
        saida.append({"prancha": p["id"], "nome": p["nome"], "subgrupo": p.get("subgrupo"),
                      "pacotes": [f"{base}.{alvo}" for alvo in REGRAS["pranchas"].get(p.get("subgrupo"), [])]})
    return saida


def lacunas(quant: pd.DataFrame) -> list[str]:
    """Itens do modelo sem nenhum elemento medido em nenhum sistema: o que o projeto ainda não evidencia."""
    medidos = {c.split(".", 2)[2] for c in quant["codigo"]}
    return [c for c in itens() if c not in medidos]


def sem_item(construtivos: dict) -> list[str]:
    """Elementos sem item EAP e que não são só evidência de sistema: classe a encaixar no modelo."""
    return [f["properties"]["id"] for f in construtivos["geojson"]["features"]
            if not codigos_do_elemento(f["properties"]) and f["properties"]["classe"] not in REGRAS["so_evidencia"]]


def _medicao_prevista(linha: dict, nos: dict) -> tuple[str | None, dict | None]:
    """(recusa, medição): o item da linha na estrutura e a medição (unidade e grandeza) que ele prevê; a recusa é o
    status se o código não é item ou se o item não prevê a medição."""
    item = nos.get(linha.get("codigo"))
    if item is None or item["nivel"] != "item":
        return "código inexistente", None
    medicao = next((m for m in item["medicoes"] if m["unidade"] == linha.get("unidade")
                    and m["grandeza"] == linha.get("grandeza", m["grandeza"])), None)
    if medicao is None:
        return "medição não prevista no item", None
    return None, medicao


def _recusa_das_evidencias(linha: dict, por_id: dict) -> str | None:
    """Status de recusa se a linha não cita evidência ou cita elemento que não existe ou não é do item; senão None."""
    ids = linha.get("evidencias") or []
    if not ids:
        return "sem evidência"
    if any(i not in por_id or linha["codigo"] not in codigos_do_elemento(por_id[i]["properties"]) for i in ids):
        return "evidência inválida"
    return None


def _status(linha: dict, nos: dict, por_id: dict, quant: pd.DataFrame, epsg: int, tol: float) -> tuple[str, float | None]:
    """Status de uma linha da proposta e o valor refeito pelas evidências citadas."""
    recusa, medicao = _medicao_prevista(linha, nos)
    if recusa:
        return recusa, None
    recusa = _recusa_das_evidencias(linha, por_id)
    if recusa:
        return recusa, None
    valores = [medir(por_id[i], medicao, epsg) for i in linha["evidencias"]]
    refeito = float(sum(v for v in valores if v is not None))
    if abs(refeito - float(linha.get("quantidade", np.nan))) > tol * max(1.0, abs(refeito)):
        return "quantidade diverge das evidências", refeito
    total = quant[(quant["codigo"] == linha["codigo"]) & (quant["unidade"] == medicao["unidade"])
                  & (quant["grandeza"] == medicao["grandeza"])]["quantidade"]
    completo = not total.empty and abs(float(total.iloc[0]) - refeito) <= tol * max(1.0, abs(refeito))
    return ("confere" if completo else "confere, parcial (faltam elementos do item)"), refeito


def verificar(proposta: list[dict], construtivos: dict, epsg: int, tol: float = 1e-6) -> pd.DataFrame:
    """Confere uma proposta (de IA ou de pessoa) contra o cálculo: cada linha {codigo, grandeza, unidade, quantidade,
    evidencias: [ids]}. A conta é refeita só com os elementos citados; sem evidência não passa."""
    feats = construtivos["geojson"]["features"]
    por_id = {f["properties"]["id"]: f for f in feats}
    sistemas = list(dict.fromkeys(f["properties"]["sistema"].split("-", 1)[1] for f in feats))
    nos = {n["codigo"]: n for n in estrutura(sistemas)}
    quant = quantificar(construtivos, epsg)
    linhas = []
    for linha in proposta:
        status, refeito = _status(linha, nos, por_id, quant, epsg, tol)
        linhas.append({"codigo": linha.get("codigo"), "grandeza": linha.get("grandeza"), "unidade": linha.get("unidade"),
                       "proposto": linha.get("quantidade"), "calculado": refeito, "status": status,
                       "aceito": status.startswith("confere")})
    return pd.DataFrame(linhas)


def montar(dados: dict, cfg: dict) -> dict | None:
    """Pacote da EAP para o HTML: nós com evidência e quantidades, pranchas por pacote, lacunas e sem item.
    Anota `eap` em cada elemento construtivo. None sem elementos construtivos."""
    construtivos = dados.get("construtivos")
    if not construtivos:
        return None
    anotar(construtivos)
    epsg = dados["crs"]["epsg"]
    quant = quantificar(construtivos, epsg)
    sistemas = list(dict.fromkeys(f["properties"]["sistema"].split("-", 1)[1]
                                  for f in construtivos["geojson"]["features"]))
    medidos = set(quant["codigo"])
    nos = [n for n in estrutura(sistemas) if any(m == n["codigo"] or m.startswith(n["codigo"] + ".") for m in medidos)]
    declarado = {p["id"]: p["eap"] for p in cfg.get("pranchas", []) if p.get("eap")}
    return {"fonte": REGRAS["metadata"]["fonte"], "nos": nos,
            "quantidades": quant.drop(columns="fontes").to_dict("records"),
            "pranchas": evidencias_pranchas(dados.get("pranchas", []), declarado),
            "lacunas": lacunas(quant), "sem_item": sem_item(construtivos)}


def metadados() -> dict:
    """Rastreabilidade do método e das regras declaradas (regra 9 do estilo)."""
    return {
        "modulo": "eap",
        "descricao": "EAP codificada (unidade.sistema.disciplina.pacote.item): elemento construtivo → item → quantidade "
                     "determinística; prancha → pacote; verificação de propostas pelas evidências",
        "funcoes": ["itens", "validar", "estrutura", "anotar", "quantificar", "origem_do_elemento",
                    "origem_das_quantidades", "consolidar", "evidencias_pranchas",
                    "lacunas", "sem_item", "verificar", "montar", "metadados"],
        "bibliografia": ["PMI — Practice Standard for Work Breakdown Structures, 3ª ed. (regra dos 100 %)"],
        "premissas": [{"aplicacao": {"montar": ["eap.json"]}, "fonte": REGRAS["metadata"]["fonte"],
                       "estado": REGRAS["metadata"]["estado"]}],
        "ultima_revisao": REGRAS["metadata"]["data_referencia"],
    }
