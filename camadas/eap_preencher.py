"""F3 da reconstrução: preencher a EAP única só pelas gavetas (docs/RECONSTRUCAO.md §0 passo 6, §3 F3, §5 decisão 1).

    itens técnicos (conceitos/eap_geral.jsonl)  ─►  quantidade lida dos fatos das gavetas, com objetos, fatos e evidências
    modelo (conceitos/eap_padrao.json: OP/OL)   ─►  cada folha soma os itens técnicos que aponta
    código da EAP única = <folha>/<item técnico>      ex.: OP.03.01/U1.ACT600.GEO.FUN.EST

Nenhuma quantidade nasce aqui sem fato por trás; sem preço, sem prazo. O contrato (`item_contrato` com `folha_eap`)
entra como "declarada" e nunca se soma com o medido. Só lê a base; não grava em `saida/`.

    python -m camadas.eap_preencher saida/foz
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import eap, gavetas, gavetas_construtivos
from .pdf_cad import CONCEITOS

PADRAO = json.loads((CONCEITOS / "eap_padrao.json").read_text(encoding="utf-8"))
VISTA_DO_TIPO = {"obra_localizada": "localizada", "obra_linear": "linear"}
TOLERANCIA = 1e-3
"""Tolerância absoluta da paridade com o golden (unidade da própria quantidade)."""
IDENTIFICACAO = ("rotulo", "sistema", "unidade")
"""Fatos que identificam o objeto: a contagem cita o primeiro que existir."""
PROPRIEDADE_GEOMETRICA = {"area": "area_planta_m2", "comprimento": "comprimento_m"}
"""Medida geométrica da regra → propriedade que a extração já grava como fato (`gavetas_construtivos._medidas`)."""
GOLDEN = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "golden_foz"
    / "quantidades_foz.json"
)


def _unidade_e_sistema(objeto: dict, fatos: dict) -> tuple[str | None, str | None]:
    """(unidade, sistema `u1-ETA`) do objeto, pelo registro ou pelos fatos; None se faltar um dos dois."""
    unidade = objeto.get("unidade") or fatos.get("unidade", {}).get("valor")
    sistema = objeto.get("sistema") or fatos.get("sistema", {}).get("valor")
    if not unidade or not sistema:
        return None, None
    return unidade, sistema if "-" in sistema else f"{unidade}-{sistema}"


def _propriedade_da_medicao(medicao: dict) -> tuple[str | None, float]:
    """(propriedade das gavetas, fator da propriedade para a unidade da medição): o `atributo` da regra `soma` passa por
    `ROTULOS`; área e comprimento são as medidas já gravadas como fato. None se não houver propriedade."""
    if medicao["regra"] == "soma":
        propriedade, fator, _ = gavetas_construtivos.ROTULOS.get(
            medicao["atributo"], (None, 1.0, None)
        )
        return propriedade, fator
    return PROPRIEDADE_GEOMETRICA.get(medicao["regra"]), 1.0


def _valor_do_objeto(medicao: dict, fatos: dict) -> tuple[float | None, list[str]]:
    """(valor, ids dos fatos citados) de um objeto numa medição; valor None se o fato não existe ou não é número."""
    if medicao["regra"] == "contagem":
        citado = next((fatos[p] for p in IDENTIFICACAO if p in fatos), None)
        return 1.0, [citado["fato_id"]] if citado else []
    propriedade, fator = _propriedade_da_medicao(medicao)
    fato = fatos.get(propriedade) if propriedade else None
    if (
        fato is None
        or isinstance(fato["valor"], bool)
        or not isinstance(fato["valor"], (int, float))
    ):
        return None, []
    return float(fato["valor"]) / fator, [fato["fato_id"]]


def _citacao(evidencia: dict) -> dict:
    """Documento e página (ou aba e linha, em planilha) de uma evidência; página None na evidência de texto (v1)."""
    localizador = evidencia.get("localizador")
    localizador = localizador if isinstance(localizador, dict) else {}
    citacao = {
        "evidencia_id": evidencia["evidencia_id"],
        "documento": evidencia.get("documento"),
        "pagina": localizador.get("pagina"),
    }
    if "aba" in localizador:
        citacao |= {"aba": localizador["aba"], "linha": localizador.get("linha")}
    return citacao


def _novo(codigo: str, grandeza: str, unidade: str, origem: str) -> dict:
    return {
        "codigo": codigo,
        "grandeza": grandeza,
        "unidade": unidade,
        "quantidade": 0.0,
        "origem": origem,
        "servicos_eap": [],
        "n_objetos": 0,
        "n_com_valor": 0,
        "sem_valor": 0,
        "objetos": [],
        "fatos": [],
        "evidencias": [],
        "servicos": [],
        "por_chave": {},
    }


def _de_objetos(base: dict, ind: dict, modelo: dict) -> dict[tuple, dict]:
    """{(código, grandeza, unidade): quantidade} lidas dos fatos dos objetos cuja classe alimenta um item técnico."""
    classes = {c for item in modelo.values() for c in item["construtivos"]}
    codigos: dict[tuple, list[str]] = {}
    acumulado: dict[tuple, dict] = {}
    for objeto in base["objetos"]:
        if objeto["classe"] not in classes:
            continue
        fatos = gavetas.fatos_do_objeto(base, objeto["objeto_id"], ind)
        unidade, sistema = _unidade_e_sistema(objeto, fatos)
        if not unidade:
            continue
        chave_classe = (objeto["classe"], unidade, sistema)
        if chave_classe not in codigos:
            codigos[chave_classe] = eap.codigos_do_elemento(
                {"classe": objeto["classe"], "unidade": unidade, "sistema": sistema}
            )
        for codigo in codigos[chave_classe]:
            for medicao in modelo[codigo.split(".", 2)[2]]["medicoes"]:
                q = acumulado.setdefault(
                    (codigo, medicao["grandeza"], medicao["unidade"]),
                    _novo(codigo, medicao["grandeza"], medicao["unidade"], "fatos"),
                )
                valor, citados = _valor_do_objeto(medicao, fatos)
                q["n_objetos"] += 1
                q["objetos"].append(objeto["objeto_id"])
                if valor is None:
                    q["sem_valor"] += 1
                    continue
                q["n_com_valor"] += 1
                q["quantidade"] += valor
                q["fatos"] += citados
    return acumulado


def _de_servicos(base: dict, medidos: set[str]) -> tuple[dict[tuple, dict], list[dict]]:
    """({(código, saída, unidade): quantidade}, descartados): serviços das gavetas com `codigo_eap`. O serviço de um item
    que os fatos dos objetos já medem (a cava: escavação e reaterro) não soma de novo; fica em `descartados`."""
    acumulado: dict[tuple, dict] = {}
    descartados = []
    for s in sorted(base["servicos"], key=lambda x: x["servico_id"]):
        codigo = s.get("codigo_eap")
        if not codigo:
            continue
        if codigo.split(".", 2)[2] in medidos:
            descartados.append(
                {
                    "servico_id": s["servico_id"],
                    "codigo": codigo,
                    "valor": s["valor"],
                    "unidade": s["unidade"],
                    "motivo": "o item já é medido pelos fatos dos objetos",
                }
            )
            continue
        q = acumulado.setdefault(
            (codigo, s["saida"], s["unidade"]),
            _novo(codigo, s["saida"], s["unidade"], "servico"),
        )
        q["quantidade"] += float(s["valor"])
        q["n_objetos"] += 1
        q["n_com_valor"] += 1
        q["objetos"].append(s["objeto_id"])
        q["fatos"] += s.get("fatos", [])
        q["servicos"].append(s["servico_id"])
        q["servicos_eap"] = sorted(
            set(q["servicos_eap"]) | set(s.get("servicos_eap") or [])
        )
        chave = str(s.get("chave") or "")
        q["por_chave"][chave] = round(
            q["por_chave"].get(chave, 0.0) + float(s["valor"]), 6
        )
    return acumulado, descartados


def _fechar(quantidades: dict[tuple, dict], base: dict) -> list[dict]:
    """Fatos e objetos sem repetição, evidências dos fatos (com documento e página), soma arredondada, em ordem."""
    por_fato = {f["fato_id"]: f["evidencia_id"] for f in base["fatos"]}
    por_evidencia = {e["evidencia_id"]: e for e in base["evidencias"]}
    for q in quantidades.values():
        q["objetos"] = sorted(set(q["objetos"]))
        q["fatos"] = sorted(set(q["fatos"]) & por_fato.keys())
        q["evidencias"] = [
            _citacao(por_evidencia[i])
            for i in sorted({por_fato[f] for f in q["fatos"]})
            if i in por_evidencia
        ]
        q["quantidade"] = round(q["quantidade"], 6)
    return sorted(
        quantidades.values(), key=lambda q: (q["codigo"], q["grandeza"], q["unidade"])
    )


def _quantidades(base: dict) -> tuple[list[dict], list[dict]]:
    """(quantidades dos itens técnicos, serviços descartados por já estarem medidos pelos fatos)."""
    modelo = eap.itens()
    ind = gavetas.indice(base)
    dos_objetos = _de_objetos(base, ind, modelo)
    medidos = {
        q["codigo"].split(".", 2)[2] for q in dos_objetos.values() if q["n_com_valor"]
    }
    dos_servicos, descartados = _de_servicos(base, medidos)
    return _fechar({**dos_objetos, **dos_servicos}, base), descartados


def itens_tecnicos(base: dict) -> list[dict]:
    """Quantidade de cada item técnico `U.SISTEMA.DISC.PAC.ITEM` e grandeza, lida só dos fatos das gavetas.

    Para cada objeto cuja `classe` está em `construtivos` do item (unidade e sistema pelo objeto ou pelos fatos, como
    `eap.codigos_do_elemento`): `contagem` conta o objeto; `soma` soma a propriedade do `atributo` (`ROTULOS`); `area` e
    `comprimento` somam a medida geométrica gravada como fato. Os serviços das gavetas com `codigo_eap` (vala, pavimento)
    entram como quantidades do seu código, citando o `servico_id` e os fatos dele; o serviço de um item que os fatos já
    medem (cava) não soma de novo (`preencher` lista os descartados).

    Cada linha: codigo, grandeza, unidade, quantidade, origem (`fatos` | `servico`), servicos_eap, n_objetos,
    n_com_valor, sem_valor, objetos, fatos, evidencias [{evidencia_id, documento, pagina}], servicos, por_chave."""
    return _quantidades(base)[0]


# --------------------------------------------------------------------------------------------------------------------
# folhas do modelo
# --------------------------------------------------------------------------------------------------------------------


def _vale(q: dict, alvo: dict, vista: str, reservados: set[tuple]) -> bool:
    """A quantidade pertence ao apontamento da folha: mesmo item, mesma vista de obra e, se o apontamento pede um serviço,
    só a quantidade de serviço que o traz (`servicos_eap`). Sem serviço vale o item inteiro, menos o serviço que outra folha
    do mesmo tipo pede pelo nome (`reservados`: pares item-serviço): a demolição não conta de novo na recomposição."""
    item = q["codigo"].split(".", 2)[2]
    if item != alvo["item"] or eap.vista_do_codigo(q["codigo"]) != vista:
        return False
    servico = alvo.get("servico")
    if servico:
        return q["origem"] == "servico" and servico in q["servicos_eap"]
    return not any((item, s) in reservados for s in q["servicos_eap"])


def _declaradas(base: dict) -> dict[str, list[dict]]:
    """{folha: linhas do contrato}: cada `item_contrato` com fato `folha_eap`, a quantidade declarada (None se a planilha
    não a traz) e a evidência (aba e linha)."""
    ind = gavetas.indice(base)
    por_evidencia = {e["evidencia_id"]: e for e in base["evidencias"]}
    saida: dict[str, list[dict]] = {}
    for objeto in base["objetos"]:
        if objeto["classe"] != "item_contrato":
            continue
        fatos = gavetas.fatos_do_objeto(base, objeto["objeto_id"], ind)
        if "folha_eap" not in fatos:
            continue
        quantidade = fatos.get("quantidade", {}).get("valor")
        citados = [fatos[p] for p in ("folha_eap", "quantidade") if p in fatos]
        saida.setdefault(fatos["folha_eap"]["valor"], []).append(
            {
                "objeto_id": objeto["objeto_id"],
                "descricao": fatos.get("descricao", {}).get("valor"),
                "unidade_medida": fatos.get("unidade_medida", {}).get("valor"),
                "quantidade": float(quantidade)
                if isinstance(quantidade, (int, float))
                else None,
                "fatos": [f["fato_id"] for f in citados],
                "evidencias": [
                    _citacao(por_evidencia[i])
                    for i in sorted({f["evidencia_id"] for f in citados})
                    if i in por_evidencia
                ],
            }
        )
    return saida


def _totais(quantidades: list[dict]) -> list[dict]:
    """Soma por (grandeza, unidade): grandezas e unidades diferentes nunca se somam."""
    somas: dict[tuple, float] = {}
    for q in quantidades:
        somas[(q["grandeza"], q["unidade"])] = (
            somas.get((q["grandeza"], q["unidade"]), 0.0) + q["quantidade"]
        )
    return [
        {"grandeza": g, "unidade": u, "quantidade": round(v, 6)}
        for (g, u), v in sorted(somas.items())
    ]


def _folha(
    folha: dict,
    vista: str,
    por_item: dict[str, list[dict]],
    declaradas: list[dict],
    reservados: set,
) -> dict:
    """Folha preenchida: quantidades dos itens que ela aponta (`<folha>/<código>`), contrato declarado e situação."""
    escolhidas: dict[tuple, dict] = {}
    for alvo in folha["aponta"]:
        for q in por_item.get(alvo["item"], []):
            if q["n_com_valor"] and _vale(q, alvo, vista, reservados):
                escolhidas[(q["codigo"], q["grandeza"], q["unidade"], q["origem"])] = q
    medidas = [
        {
            "codigo_eap": f"{folha['id']}/{q['codigo']}",
            **{
                k: q[k]
                for k in (
                    "grandeza",
                    "unidade",
                    "quantidade",
                    "origem",
                    "n_objetos",
                    "sem_valor",
                    "objetos",
                    "fatos",
                    "evidencias",
                    "servicos",
                    "por_chave",
                )
            },
        }
        for _, q in sorted(escolhidas.items())
    ]
    declarou = any(d["quantidade"] is not None for d in declaradas)
    situacao = "preenchida" if medidas else "declarada" if declarou else "a preencher"
    return {
        "id": folha["id"],
        "nome": folha["nome"],
        "obrigatoria": folha["obrigatoria"],
        "escopo": folha.get("escopo", "ambos"),
        "aponta": folha["aponta"],
        "situacao": situacao,
        "quantidades": medidas,
        "totais": _totais(medidas),
        "declaradas": declaradas,
    }


def _completude(folhas: list[dict]) -> dict:
    """Folhas por situação, obrigatórias a preencher e % preenchida (medida com evidência) de um tipo de obra."""
    n = len(folhas)
    por_situacao = {
        s: sum(f["situacao"] == s for f in folhas)
        for s in ("preenchida", "declarada", "a preencher")
    }
    obrigatorias = [f for f in folhas if f["obrigatoria"]]
    return {
        "folhas": n,
        **por_situacao,
        "obrigatorias": len(obrigatorias),
        "obrigatorias_a_preencher": [
            f["id"] for f in obrigatorias if f["situacao"] == "a preencher"
        ],
        "pct_preenchidas": round(100.0 * por_situacao["preenchida"] / n, 1)
        if n
        else None,
    }


def preencher(base: dict) -> dict:
    """Laço sobre o modelo `eap_padrao.json` (obra localizada e obra linear): cada folha soma as quantidades dos itens
    técnicos que aponta e traz as linhas do contrato como "declarada" (sem somar com o medido).

    Situação: `preenchida` (há quantidade medida, com fatos e evidências), `declarada` (só o contrato declara quantidade),
    `a preencher` (nada); `obrigatoria` vem do modelo. Devolve {tipos: {tipo: {nome, prefixo, etapas, completude}},
    completude, quantidades_sem_folha, contrato_sem_folha, servicos_descartados}."""
    quantidades, descartados = _quantidades(base)
    por_item: dict[str, list[dict]] = {}
    for q in quantidades:
        por_item.setdefault(q["codigo"].split(".", 2)[2], []).append(q)
    declaradas = _declaradas(base)
    tipos, usadas, folhas_do_modelo = {}, set(), set()
    for tipo, modelo in PADRAO["tipos"].items():
        etapas = []
        reservados = {
            (a["item"], a["servico"])
            for e in modelo["etapas"]
            for f in e["folhas"]
            for a in f["aponta"]
            if a.get("servico")
        }
        for etapa in modelo["etapas"]:
            folhas = [
                _folha(
                    f,
                    VISTA_DO_TIPO[tipo],
                    por_item,
                    declaradas.get(f["id"], []),
                    reservados,
                )
                for f in etapa["folhas"]
            ]
            usadas |= {
                q["codigo_eap"].split("/", 1)[1] + "|" + q["grandeza"]
                for f in folhas
                for q in f["quantidades"]
            }
            folhas_do_modelo |= {f["id"] for f in folhas}
            etapas.append({"id": etapa["id"], "nome": etapa["nome"], "folhas": folhas})
        todas = [f for e in etapas for f in e["folhas"]]
        tipos[tipo] = {
            "nome": modelo["nome"],
            "prefixo": modelo["prefixo"],
            "etapas": etapas,
            "completude": _completude(todas),
        }
    return {
        "tipos": tipos,
        "completude": {t: v["completude"] for t, v in tipos.items()},
        "quantidades_sem_folha": [
            f"{q['codigo']}|{q['grandeza']}"
            for q in quantidades
            if q["n_com_valor"] and f"{q['codigo']}|{q['grandeza']}" not in usadas
        ],
        "contrato_sem_folha": sorted(
            f for f in declaradas if f not in folhas_do_modelo
        ),
        "servicos_descartados": descartados,
    }


def paridade(itens: list[dict], golden_eap: dict) -> list[str]:
    """Diferenças entre as quantidades das gavetas e as da EAP codificada atual (seção `eap` do golden). Chave
    `codigo|grandeza`, tolerância absoluta `TOLERANCIA`; cada quantidade do golden tem de sair igual. Vazio = paridade."""
    esperado = golden_eap.get("quantidades", golden_eap)
    obtido = {f"{q['codigo']}|{q['grandeza']}": q for q in itens if q["n_com_valor"]}
    problemas = []
    for chave, g in sorted(esperado.items()):
        q = obtido.get(chave)
        if q is None:
            problemas.append(
                f"{chave}: falta nas gavetas (golden {g['quantidade']} {g['unidade']})"
            )
        elif q["unidade"] != g["unidade"]:
            problemas.append(
                f"{chave}: unidade {q['unidade']} no lugar de {g['unidade']}"
            )
        elif abs(q["quantidade"] - g["quantidade"]) > TOLERANCIA:
            problemas.append(
                f"{chave}: gavetas {q['quantidade']} × golden {g['quantidade']} {g['unidade']} "
                f"(diferença {q['quantidade'] - g['quantidade']:+.6f})"
            )
    return problemas


def _pasta_da_base(caminho: str) -> Path:
    """`saida/foz` ou `saida/foz/base`: a pasta com as gavetas."""
    pasta = Path(caminho)
    return pasta / "base" if (pasta / "base").is_dir() else pasta


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("obra", help="saida/<obra> (ou a pasta base/ com as gavetas)")
    p.add_argument(
        "--golden", default=str(GOLDEN), help="quantidades_foz.json (seção eap)"
    )
    a = p.parse_args(argv)
    base = gavetas.ler(_pasta_da_base(a.obra))
    resultado = preencher(base)
    for tipo, v in resultado["tipos"].items():
        c = v["completude"]
        print(
            f"{tipo}: {c['preenchida']} preenchidas, {c['declarada']} declaradas, {c['a preencher']} a preencher "
            f"de {c['folhas']} folhas ({c['pct_preenchidas']} % preenchidas); obrigatórias a preencher: "
            f"{', '.join(c['obrigatorias_a_preencher']) or 'nenhuma'}"
        )
        for etapa in v["etapas"]:
            for f in etapa["folhas"]:
                print(
                    f"  {f['id']:9} {f['situacao']:12} {'*' if f['obrigatoria'] else ' '} {f['nome']}"
                )
    print(
        f"quantidades sem folha: {len(resultado['quantidades_sem_folha'])}; "
        f"serviços descartados (item já medido): {len(resultado['servicos_descartados'])}; "
        f"contrato em folha fora do modelo: {resultado['contrato_sem_folha'] or 'nenhum'}"
    )
    golden = json.loads(Path(a.golden).read_text(encoding="utf-8"))["eap"]
    diferencas = paridade(itens_tecnicos(base), golden)
    total = len(golden["quantidades"])
    print(
        f"paridade com o golden: {total - len(diferencas)} de {total} quantidades batem"
    )
    for d in diferencas:
        print("  DIFERE", d)
    return 1 if diferencas else 0


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "eap_preencher",
        "descricao": "EAP única preenchida só pelas gavetas: itens técnicos de eap_geral.jsonl lidos dos fatos (e dos serviços "
        "com codigo_eap), folhas do modelo eap_padrao.json (OP/OL) somando os itens que apontam, contrato como declarada, "
        "paridade com o golden da EAP codificada",
        "funcoes": ["itens_tecnicos", "preencher", "paridade", "metadados"],
        "conceitos": ["eap_geral.jsonl", "eap_padrao.json", "gavetas.json"],
        "tolerancia_paridade": TOLERANCIA,
        "premissas": [
            {
                "aplicacao": {"preencher": ["eap_padrao.json"]},
                "fonte": PADRAO["metadata"]["fonte"],
                "estado": PADRAO["metadata"].get("estado"),
            }
        ],
    }


if __name__ == "__main__":
    raise SystemExit(principal())
