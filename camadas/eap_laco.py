"""F5 da reconstrução: o laço até a EAP completa (docs/RECONSTRUCAO.md §0 passo 8, §3 F5).

    EAP única (eap_preencher)  ─►  cada folha "a preencher" ganha um destino na escada (código → IA → humano)
    portão "EAP completa"      ─►  toda folha obrigatória preenchida, calculada, declarada ou "ausente do projeto" confirmada
    roteiro do próximo passe   ─►  uma linha por documento × folha, no formato da skill `eap-evidencias`

O laço só decide e escreve o roteiro. Não há IA aqui: a leitura por IA é um passe externo da escada, e só entra na EAP
com a citação conferida por `camadas.evidencias` ("a IA propõe, o código confere"). Nada é preenchido por este módulo
e nada é inventado: sem menção e sem documento esperado, o destino é "ausente do projeto" e quem confirma é o Caio, por
`exemplos/<obra>/decisoes_eap.json` (lido se existir; este módulo não o cria).

    python -m camadas.eap_laco saida/foz [--decisoes exemplos/foz/decisoes_eap.json]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from . import eap as eap_geral
from . import eap_preencher, evidencias, extracao, gavetas
from .pdf_cad import CONCEITOS

RAIZ = Path(__file__).resolve().parent.parent
SITUACOES_FECHADAS = ("preenchida", "calculada", "declarada")
"""Situações que dispensam destino: a folha já tem quantidade (medida, calculada por regra ou declarada pelo contrato)."""

DEGRAU_CODIGO = "código"
DEGRAU_IA = "IA com citação conferida"
DEGRAU_HUMANO = "humano (Caio)"
"""Degraus da escada de `conceitos/fontes.json`: código primeiro, IA depois, humano por último."""

CANDIDATA = "candidata a declarada (documento)"
MENCAO = "menção em documento"
ESPERADO = "documento esperado ausente"
AUSENTE = "ausente do projeto"
PRECEDENCIA = (CANDIDATA, MENCAO, ESPERADO, AUSENTE)
"""Destino principal da folha = a primeira da lista que existir entre as ações dela."""

PREFIXO_TIPOLOGIAS = {
    "GEO.FUN": ["estrutura_concreto", "bloco_concreto", "edificacao"],
    "CIV.EST": ["estrutura_concreto", "bloco_concreto", "edificacao"],
    "CIV.ACA": ["edificacao"],
    "HID.TUB": ["rede", "rede_eta", "drenagem"],
    "GEO.MOV.VAL": ["rede", "rede_eta", "drenagem"],
}
"""Premissa do laço (estado `premissa`): quais tipologias de `documentos_esperados.json` valem para um item técnico,
pelo prefixo do código. Item de outro prefixo (gerais, elétrica, terraplenagem de cava) não tem documento esperado."""

CLASSE_MENCAO = "mencao_documento"


# --------------------------------------------------------------------------------------------------------------------
# o que as gavetas já sabem: menções de texto e documentos esperados
# --------------------------------------------------------------------------------------------------------------------


def _mencoes_por_item(base: dict) -> dict[str, list[dict]]:
    """{item técnico: menções}: cada objeto `mencao_documento` com seu fato `item_tecnico`. A menção traz documento_id,
    as páginas (um fato `mencao` por página, com o trecho) e, se o texto trouxe número com unidade, quantidade e unidade
    com a página e o trecho em que apareceram."""
    por_evidencia = {e["evidencia_id"]: e for e in base.get("evidencias", [])}
    fatos_do_objeto: dict[str, list[dict]] = {}
    for f in base.get("fatos", []):
        fatos_do_objeto.setdefault(f["objeto_id"], []).append(f)

    def pagina_e_trecho(fato: dict) -> tuple[int | None, str | None, str | None]:
        ev = por_evidencia.get(fato.get("evidencia_id"), {})
        loc = ev.get("localizador")
        pagina = loc.get("pagina") if isinstance(loc, dict) else None
        return pagina, ev.get("trecho"), ev.get("documento")

    saida: dict[str, list[dict]] = {}
    for objeto in sorted(base.get("objetos", []), key=lambda o: o["objeto_id"]):
        if objeto["classe"] != CLASSE_MENCAO:
            continue
        fatos = fatos_do_objeto.get(objeto["objeto_id"], [])
        item = next(
            (f["valor"] for f in fatos if f["propriedade"] == "item_tecnico"), None
        )
        if not item:
            continue
        paginas, documento_id, trechos = [], None, []
        for f in fatos:
            if f["propriedade"] != "mencao":
                continue
            pagina, trecho, doc = pagina_e_trecho(f)
            documento_id = documento_id or doc
            if pagina is not None:
                paginas.append(int(pagina))
            if trecho:
                trechos.append(trecho)
        quantidade = next((f for f in fatos if f["propriedade"] == "quantidade"), None)
        unidade = next(
            (f["valor"] for f in fatos if f["propriedade"] == "unidade_medida"), None
        )
        medida = None
        if (
            quantidade is not None
            and isinstance(quantidade["valor"], (int, float))
            and not isinstance(quantidade["valor"], bool)
            and unidade
        ):
            pagina_q, trecho_q, doc_q = pagina_e_trecho(quantidade)
            documento_id = documento_id or doc_q
            medida = {
                "quantidade": float(quantidade["valor"]),
                "unidade_medida": unidade,
                "pagina": pagina_q,
                "trecho": trecho_q,
            }
        saida.setdefault(item, []).append(
            {
                "objeto_id": objeto["objeto_id"],
                "documento_id": documento_id,
                "paginas": sorted(set(paginas)),
                "trechos": trechos,
                "medida": medida,
            }
        )
    return saida


def _itens_do_catalogo_de_documentos(base: dict) -> list[dict]:
    """Os documentos da gaveta no formato de arquivo que `extracao` entende (pasta, nome); sem carimbo."""
    itens = []
    for d in base.get("documentos", []):
        caminho = str(d.get("arquivo") or "")
        pasta, _, nome = caminho.rpartition("/")
        itens.append(
            {"pasta_drive": pasta, "arquivo": nome or caminho, "carimbo": None}
        )
    return itens


def _documentos_do_sistema(base: dict) -> dict[str, dict[str, list[str]]]:
    """{sistema: {documento esperado (id): arquivos que o casam}} só dos sistemas que o projeto tem (algum documento da
    gaveta casa as `chaves` do sistema), para cada documento que a tipologia do sistema exige. Um sistema que nenhum
    documento da gaveta cita não entra: não se cobra planta de um sistema que o projeto não traz."""
    itens = _itens_do_catalogo_de_documentos(base)
    saida: dict[str, dict[str, list[str]]] = {}
    for chave, sistema in extracao.SISTEMAS.items():
        do_sistema = [i for i in itens if extracao._do_sistema(i, sistema)]
        if not do_sistema:
            continue
        exigidos = extracao.ESPERADOS.get(sistema["tipologia"], {}).get(
            "documentos", []
        )
        saida[chave] = {
            doc["id"]: [
                i["arquivo"]
                for i in do_sistema
                if re.search(doc["termos"], extracao._texto(i), re.IGNORECASE)
            ]
            for doc in exigidos
        }
    return saida


def _esperados_ausentes(
    item: str, presentes: dict[str, dict[str, list[str]]]
) -> list[dict]:
    """Documentos que a tipologia dos sistemas do projeto exige para o item e que nenhum arquivo da gaveta traz.
    Uma linha por documento esperado, com os sistemas que o perderam."""
    tipologias = next(
        (t for prefixo, t in PREFIXO_TIPOLOGIAS.items() if item.startswith(prefixo)), []
    )
    faltas: dict[str, dict] = {}
    for chave, docs in presentes.items():
        tipologia = extracao.SISTEMAS[chave]["tipologia"]
        if tipologia not in tipologias:
            continue
        nomes = {
            d["id"]: d["nome"] for d in extracao.ESPERADOS[tipologia]["documentos"]
        }
        for doc_id, arquivos in docs.items():
            if not arquivos:
                faltas.setdefault(
                    doc_id, {"documento": doc_id, "nome": nomes[doc_id], "sistemas": []}
                )["sistemas"].append(chave)
    return [faltas[k] for k in sorted(faltas)]


# --------------------------------------------------------------------------------------------------------------------
# destinos
# --------------------------------------------------------------------------------------------------------------------


def _folhas(eap_unica: dict):
    """(tipo, etapa, folha) de toda a EAP, na ordem do modelo."""
    for tipo, v in eap_unica["tipos"].items():
        for etapa in v["etapas"]:
            for folha in etapa["folhas"]:
                yield tipo, etapa, folha


def ler_decisoes(caminho: str | Path | None) -> dict[str, dict]:
    """{folha: decisão} de `decisoes_eap.json`, se o arquivo existir (senão {}). Aceita `{"decisoes": [...]}` ou
    `{"decisoes": {folha: {...}}}`; cada decisão traz `folha`, `decisao` ("ausente_do_projeto"), `motivo`,
    `confirmado_por` e `data`. Só vale a decisão com `confirmado_por` preenchido."""
    if not caminho or not Path(caminho).is_file():
        return {}
    bruto = json.loads(Path(caminho).read_text(encoding="utf-8")).get("decisoes", [])
    if isinstance(bruto, dict):
        bruto = [{"folha": k, **v} for k, v in bruto.items()]
    return {
        d["folha"]: d
        for d in bruto
        if d.get("folha")
        and d.get("decisao") == "ausente_do_projeto"
        and d.get("confirmado_por")
    }


def _acoes(
    itens_info: list[dict], mencoes: dict, presentes: dict, documentos: dict
) -> list[dict]:
    """Ações da folha na ordem da escada: código (classes que alimentam os itens), IA (menções, com página), humano
    (documento esperado ausente ou confirmar que a folha não se aplica)."""
    acoes = []
    classes = sorted({c for i in itens_info for c in i["construtivos"] + i["layers"]})
    if classes:
        acoes.append(
            {
                "degrau": DEGRAU_CODIGO,
                "destino": "objetos das classes do item",
                "classes": classes,
                "texto": "a folha aponta itens alimentados pelas classes "
                + ", ".join(classes)
                + ": nenhum objeto delas deu quantidade nas gavetas",
            }
        )
    achou_mencao = False
    for item in itens_info:
        for m in mencoes.get(item["codigo"], []):
            achou_mencao = True
            arquivo = documentos.get(m["documento_id"], m["documento_id"])
            acoes.append(
                {
                    "degrau": DEGRAU_IA,
                    "destino": MENCAO,
                    "item": item["codigo"],
                    "documento_id": m["documento_id"],
                    "documento": arquivo,
                    "paginas": m["paginas"],
                    "objeto_id": m["objeto_id"],
                    "texto": f"ler {arquivo} nas páginas {m['paginas'] or 'a localizar'}: quantidade e unidade da "
                    f"medição do item {item['codigo']}",
                }
            )
            if m["medida"]:
                acoes.append(
                    {
                        "degrau": DEGRAU_IA,
                        "destino": CANDIDATA,
                        "item": item["codigo"],
                        "documento_id": m["documento_id"],
                        "documento": arquivo,
                        "paginas": [m["medida"]["pagina"]]
                        if m["medida"]["pagina"]
                        else m["paginas"],
                        "quantidade": m["medida"]["quantidade"],
                        "unidade_medida": m["medida"]["unidade_medida"],
                        "trecho": m["medida"]["trecho"],
                        "objeto_id": m["objeto_id"],
                        "texto": f"o texto traz {m['medida']['quantidade']:g} {m['medida']['unidade_medida']}: "
                        "candidata a declarada (documento), à espera da citação conferida",
                    }
                )
    achou_esperado = False
    for item in itens_info:
        for falta in _esperados_ausentes(item["codigo"], presentes):
            achou_esperado = True
            acoes.append(
                {
                    "degrau": DEGRAU_HUMANO,
                    "destino": ESPERADO,
                    "item": item["codigo"],
                    "documento_esperado": falta["documento"],
                    "sistemas": falta["sistemas"],
                    "texto": f"documento esperado ausente: {falta['nome']} ({', '.join(falta['sistemas'])}); "
                    "pedir ao Caio",
                }
            )
    if not achou_mencao and not achou_esperado:
        codigos = ", ".join(i["codigo"] for i in itens_info) or "nenhum item"
        acoes.append(
            {
                "degrau": DEGRAU_HUMANO,
                "destino": AUSENTE,
                "texto": f"ausente do projeto: nenhuma menção a {codigos} nos documentos lidos e nenhum documento "
                "esperado faltando; confirmar que não se aplica",
            }
        )
    return acoes


def destinos(eap: dict, base: dict, decisoes: dict | None = None) -> list[dict]:
    """O que fazer com cada folha "a preencher" (obrigatórias primeiro, depois a ordem do modelo), nos degraus
    código → IA → humano. Cada destino: folha, tipo, etapa, nome, obrigatoria, itens (código, nome, classes que os
    alimentam, serviços), `acoes` (ordem da escada), `destino` (o principal: candidata a declarada, menção em documento,
    documento esperado ausente ou ausente do projeto) e `degrau` do principal. Em "ausente do projeto" a decisão
    confirmada do Caio (`decisoes`, de `ler_decisoes`) entra como `confirmado_por`. Não preenche nada."""
    decisoes = decisoes or {}
    catalogo = eap_geral.itens()
    mencoes = _mencoes_por_item(base)
    documentos = {d["documento_id"]: d["arquivo"] for d in base.get("documentos", [])}
    presentes = _documentos_do_sistema(base)
    saida = []
    for tipo, etapa, folha in _folhas(eap):
        if folha["situacao"] != "a preencher":
            continue
        itens_info = []
        for alvo in folha["aponta"]:
            item = catalogo.get(alvo["item"], {})
            itens_info.append(
                {
                    "codigo": alvo["item"],
                    "servico": alvo.get("servico"),
                    "nome": item.get("nome"),
                    "construtivos": list(item.get("construtivos", [])),
                    "layers": list(item.get("layers", [])),
                    "servicos": list(item.get("servicos", [])),
                }
            )
        acoes = _acoes(itens_info, mencoes, presentes, documentos)
        principal = next(a for d in PRECEDENCIA for a in acoes if a["destino"] == d)
        destino = {
            "folha": folha["id"],
            "tipo": tipo,
            "etapa": etapa["id"],
            "nome": folha["nome"],
            "obrigatoria": folha["obrigatoria"],
            "itens": itens_info,
            "acoes": acoes,
            "destino": principal["destino"],
            "degrau": principal["degrau"],
            "texto": principal["texto"],
        }
        decisao = decisoes.get(folha["id"])
        if principal["destino"] == AUSENTE and decisao:
            destino["confirmado_por"] = decisao["confirmado_por"]
            destino["motivo_confirmado"] = decisao.get("motivo")
        elif decisao:
            destino["decisao_ignorada"] = (
                f"a folha tem destino '{principal['destino']}': a decisão de ausência só vale sem menção "
                "e sem documento esperado faltando"
            )
        saida.append(destino)
    return sorted(saida, key=lambda d: not d["obrigatoria"])


# --------------------------------------------------------------------------------------------------------------------
# portão e roteiro
# --------------------------------------------------------------------------------------------------------------------


def portao(eap: dict, destinos: list[dict]) -> dict:
    """Portão "EAP completa": `fechada` é verdadeiro quando toda folha obrigatória está preenchida, calculada ou
    declarada, ou tem destino "ausente do projeto" com `confirmado_por`. Devolve `fechada`, `trava` (as obrigatórias que
    seguram, com destino, degrau e texto) e `completude` por tipo: folhas, preenchidas, calculadas, declaradas,
    a_preencher, `com_destino` (a preencher com caminho: menção, candidata, documento esperado, ou ausência confirmada),
    `sem_destino` (a preencher só com "ausente do projeto" ainda sem confirmação) e as obrigatórias que travam."""
    por_folha = {d["folha"]: d for d in destinos}
    completude, trava = {}, []
    for tipo, v in eap["tipos"].items():
        folhas = [f for e in v["etapas"] for f in e["folhas"]]
        contagem = {
            s: sum(f["situacao"] == s for f in folhas) for s in SITUACOES_FECHADAS
        }
        a_preencher = [
            por_folha[f["id"]] for f in folhas if f["situacao"] == "a preencher"
        ]
        confirmadas = [d for d in a_preencher if d.get("confirmado_por")]
        sem_destino = [
            d
            for d in a_preencher
            if d["destino"] == AUSENTE and not d.get("confirmado_por")
        ]
        travam = [
            d for d in a_preencher if d["obrigatoria"] and not d.get("confirmado_por")
        ]
        trava += [
            {
                "tipo": tipo,
                "folha": d["folha"],
                "nome": d["nome"],
                "destino": d["destino"],
                "degrau": d["degrau"],
                "texto": d["texto"],
            }
            for d in travam
        ]
        completude[tipo] = {
            "folhas": len(folhas),
            "preenchidas": contagem["preenchida"],
            "calculadas": contagem["calculada"],
            "declaradas": contagem["declarada"],
            "a_preencher": len(a_preencher),
            "ausentes_confirmadas": len(confirmadas),
            "com_destino": len(a_preencher) - len(sem_destino),
            "sem_destino": len(sem_destino),
            "obrigatorias_que_travam": [d["folha"] for d in travam],
        }
    return {"fechada": not trava, "trava": trava, "completude": completude}


def roteiro(destinos: list[dict]) -> list[dict]:
    """Linhas do próximo passe de leitura por IA, uma por documento × folha, no formato que a skill `eap-evidencias`
    espera: o `documento` (nome do arquivo, o `documento.id` da evidência), as `paginas` (índice no PDF, 1 = primeira
    folha, para o `localizador` "p. N"), e por item o `codigo` com `*` nos segmentos que o documento não diz
    (`*.*.GEO.FUN.EST`), termos de busca, serviços e unidades aceitas (de `evidencias.roteiro`). A IA devolve uma linha
    JSON por afirmação, com o trecho copiado literalmente; `evidencias conferir` decide o que entra."""
    por_codigo = {r["codigo"]: r for r in evidencias.roteiro()}
    linhas: dict[tuple, dict] = {}
    for d in destinos:
        for a in d["acoes"]:
            if a["destino"] != MENCAO:
                continue
            chave = (a["documento_id"], d["folha"])
            linha = linhas.setdefault(
                chave,
                {
                    "documento_id": a["documento_id"],
                    "documento": Path(str(a["documento"])).name,
                    "folha": d["folha"],
                    "tipo": d["tipo"],
                    "obrigatoria": d["obrigatoria"],
                    "paginas": [],
                    "itens": [],
                    "procurar": "quantidade e unidade da medição de cada item; sem número, valor e unidade nulos",
                },
            )
            linha["paginas"] = sorted(set(linha["paginas"]) | set(a["paginas"]))
            if all(i["item"] != a["item"] for i in linha["itens"]):
                rot = por_codigo.get(a["item"], {})
                linha["itens"].append(
                    {
                        "item": a["item"],
                        "codigo": f"*.*.{a['item']}",
                        "nome": rot.get("nome"),
                        "termos": rot.get("termos", []),
                        "servicos": rot.get("servicos", []),
                        "unidades": rot.get("unidades", []),
                    }
                )
    return sorted(
        linhas.values(),
        key=lambda x: (not x["obrigatoria"], x["folha"], x["documento"]),
    )


# --------------------------------------------------------------------------------------------------------------------
# linha de comando
# --------------------------------------------------------------------------------------------------------------------


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("obra", help="saida/<obra> (ou a pasta base/ com as gavetas)")
    p.add_argument(
        "--decisoes",
        default=None,
        help="decisoes_eap.json (padrão: exemplos/<obra>/decisoes_eap.json, se existir)",
    )
    a = p.parse_args(argv)
    pasta = eap_preencher._pasta_da_base(a.obra)
    base = gavetas.ler(pasta)
    pasta_obra = Path(a.obra)
    pronta = pasta_obra / "eap_unica.json"
    eap_unica = (
        json.loads(pronta.read_text(encoding="utf-8"))
        if pronta.is_file()
        else eap_preencher.preencher(base)
    )
    obra = pasta_obra.name if pasta_obra.name != "base" else pasta_obra.parent.name
    decisoes = ler_decisoes(
        a.decisoes or RAIZ / "exemplos" / obra / "decisoes_eap.json"
    )
    destinados = destinos(eap_unica, base, decisoes)
    resultado = portao(eap_unica, destinados)
    print(f"EAP completa: {'SIM' if resultado['fechada'] else 'NÃO'}")
    for tipo, c in resultado["completude"].items():
        print(
            f"{tipo}: {c['folhas']} folhas; {c['preenchidas']} preenchidas, {c['calculadas']} calculadas, "
            f"{c['declaradas']} declaradas, {c['a_preencher']} a preencher "
            f"({c['com_destino']} com destino, {c['sem_destino']} sem destino, "
            f"{c['ausentes_confirmadas']} ausentes confirmadas); "
            f"{len(c['obrigatorias_que_travam'])} obrigatórias travam"
        )
    print("obrigatórias que travam:")
    for t in resultado["trava"]:
        print(f"  {t['folha']:9} {t['nome'][:44]:44} {t['destino']} [{t['degrau']}]")
    print(
        f"roteiro do próximo passe: {len(roteiro(destinados))} linhas (documento × folha)"
    )
    return 0


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "eap_laco",
        "descricao": "laço da F5: destino de cada folha a preencher na escada código → IA → humano, portão EAP completa "
        "e roteiro do próximo passe de leitura por IA; sem IA no laço, nada é preenchido",
        "funcoes": ["destinos", "portao", "roteiro", "ler_decisoes", "metadados"],
        "conceitos": [
            "eap_geral.jsonl",
            "eap_padrao.json",
            "documentos_esperados.json",
            "fontes.json",
        ],
        "premissas": [
            {
                "aplicacao": {"destinos": ["PREFIXO_TIPOLOGIAS"]},
                "fonte": "convenção do laço: prefixo do item técnico → tipologias de documentos_esperados.json",
                "estado": "premissa",
            },
            {
                "aplicacao": {"destinos": ["documentos_esperados.json"]},
                "fonte": json.loads(
                    (CONCEITOS / "documentos_esperados.json").read_text(
                        encoding="utf-8"
                    )
                )["metadata"]["fonte"],
                "estado": "premissa",
            },
        ],
    }


if __name__ == "__main__":
    raise SystemExit(principal())
