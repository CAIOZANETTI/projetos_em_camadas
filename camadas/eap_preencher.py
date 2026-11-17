"""F3 da reconstrução: preencher a EAP única só pelas gavetas (docs/RECONSTRUCAO.md §0 passo 6, §3 F3, §5 decisão 1).

    itens técnicos (conceitos/eap_geral.jsonl)  ─►  quantidade lida dos fatos das gavetas, com objetos, fatos e evidências
    modelo (conceitos/eap_padrao.json: OP/OL)   ─►  cada folha soma os itens técnicos que aponta
    código da EAP única = <folha>/<item técnico>      ex.: OP.03.01/U1.ACT600.GEO.FUN.EST

Nenhuma quantidade nasce aqui sem fato por trás; sem preço, sem prazo. Só lê a base; não grava em `saida/`.

Três origens por folha, que nunca se somam entre si, em ordem de precedência da situação:

    1. medida   (fatos dos objetos e serviços das gavetas)        → "preenchida" (ou "calculada", se só há serviço de regra)
    2. calculada pelo contrato (`item_contrato` com `quantidade_calculada` do `contrato_211`, situação `calculada`)
                                                                     → "calculada"
    3. declarada (`item_contrato` com `quantidade`; `item_material` com etapa 1 + etapa 2) → "declarada"

Por quê: o que o projeto mede tem a evidência mais forte (fato com página). A calculada pelo contrato nasce de regra
determinística sobre o projeto (rede, vala, área da UC) e só existe onde a planilha deixou a quantidade vazia, então
nunca disputa a mesma linha com a declarada; ela vale mais que a declarada porque tem regra e evidências que se
conferem, enquanto a declarada é o número escrito na planilha. A linha `parcial` (cálculo incompleto) e a que a planilha
declarou e o código só conferiu (`declarada · confere/diverge`) não fecham a folha como calculada. As outras origens
seguem listadas na folha (`calculadas_contrato`, `declaradas`) com os totais por unidade, sem entrar nos `totais` medidos.

    python -m camadas.eap_preencher saida/foz
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import eap, gavetas, gavetas_construtivos, gavetas_contrato, vocabulario
from .pdf_cad import CONCEITOS

PADRAO = json.loads((CONCEITOS / "eap_padrao.json").read_text(encoding="utf-8"))
VISTA_DO_TIPO = {"obra_localizada": "localizada", "obra_linear": "linear"}
CLASSES_DO_CONTRATO = ("item_contrato", "item_material")
"""Classes das gavetas cuja quantidade é "declarada" na folha: a linha do contrato e o item da Relação de Materiais."""
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
    if "regra" in localizador:  # cálculo do contrato: a regra e o que ela usou
        citacao |= {"regra": localizador["regra"], "trecho": evidencia.get("trecho")}
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
    """({(código, saída, unidade): quantidade}, descartados): serviços das gavetas com `codigo_eap`. Um serviço não
    entra, para a mesma grandeza não ser contada por dois caminhos, e fica em `descartados` com o motivo: o serviço sem
    nome (`servicos_eap` vazio) de um item que os fatos dos objetos já medem (a cava: escavação e reaterro); o serviço
    com nome (forma, armadura, concreto…) é outra grandeza e entra. Não há descarte entre regras: cada (código, serviço)
    nasce de uma regra só (a vala sai só da `vala_rede`; `gavetas_servicos` nem calcula o que ela já dá)."""
    acumulado: dict[tuple, dict] = {}
    descartados = []
    for s in sorted(base["servicos"], key=lambda x: x["servico_id"]):
        codigo = s.get("codigo_eap")
        if not codigo:
            continue
        nomes_eap = set(s.get("servicos_eap") or [])
        if not nomes_eap and codigo.split(".", 2)[2] in medidos:
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
        q["servicos_eap"] = sorted(set(q["servicos_eap"]) | nomes_eap)
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


def _unidade_canonica(texto) -> str | None:
    """Unidade canônica do vocabulário (pç e pc contam como un, MÊS como mês); a que ele não conhece (barras, ud) segue
    na grafia da planilha, em minúsculas, sem converter. None se vazia."""
    return vocabulario.unidade_medida(texto) or (
        str(texto or "").strip().lower() or None
    )


def _quantidade_declarada(fatos: dict) -> tuple[float | None, list[dict]]:
    """(quantidade, fatos citados) declarada: o fato `quantidade` do contrato ou, na Relação de Materiais, a soma das
    quantidades da etapa 1 e da etapa 2 (só as numéricas; sem nenhuma, None)."""
    propriedades = (
        ("quantidade",)
        if "quantidade" in fatos
        else ("quantidade_etapa1", "quantidade_etapa2")
    )
    citados = [fatos[p] for p in propriedades if p in fatos]
    numeros = [f["valor"] for f in citados if _numero(f["valor"])]
    return (float(sum(numeros)) if numeros else None), citados


def _numero(valor) -> bool:
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _linha_do_contrato(
    objeto: dict, fatos: dict, citados: list[dict], por_evidencia: dict
) -> dict:
    """Campos comuns de uma linha do contrato ou da Relação de Materiais numa folha: objeto, descrição, fatos citados e
    evidências (documento, aba e linha)."""
    return {
        "objeto_id": objeto["objeto_id"],
        "descricao": fatos.get("descricao", {}).get("valor"),
        "fatos": [f["fato_id"] for f in citados],
        "evidencias": [
            _citacao(por_evidencia[i])
            for i in sorted({f["evidencia_id"] for f in citados})
            if i in por_evidencia
        ],
    }


def _declaradas(base: dict) -> dict[str, list[dict]]:
    """{folha: linhas declaradas}: cada `item_contrato` ou `item_material` com fato `folha_eap`, a quantidade declarada
    (None se a planilha não a traz; no material, etapa 1 + etapa 2), a unidade e a evidência (aba e linha)."""
    ind = gavetas.indice(base)
    por_evidencia = {e["evidencia_id"]: e for e in base["evidencias"]}
    saida: dict[str, list[dict]] = {}
    for objeto in base["objetos"]:
        if objeto["classe"] not in CLASSES_DO_CONTRATO:
            continue
        fatos = gavetas.fatos_do_objeto(base, objeto["objeto_id"], ind)
        if "folha_eap" not in fatos:
            continue
        quantidade, citados_q = _quantidade_declarada(fatos)
        unidade_medida = fatos.get("unidade_medida", {}).get("valor")
        saida.setdefault(fatos["folha_eap"]["valor"], []).append(
            {
                **_linha_do_contrato(
                    objeto, fatos, [fatos["folha_eap"], *citados_q], por_evidencia
                ),
                "classe": objeto["classe"],
                "unidade_medida": unidade_medida,
                "unidade": _unidade_canonica(unidade_medida),
                "quantidade": quantidade,
            }
        )
    return saida


def _calculadas(base: dict) -> dict[str, list[dict]]:
    """{folha: linhas calculadas pelo contrato}: cada `item_contrato` com `folha_eap` e `quantidade_calculada` (fato do
    `gavetas_contrato.aplicar_calculadas`), com a unidade, a regra, a situação do cálculo (`completa` só se `calculada`)
    e a evidência do cálculo (aba, linha, regra e o que o `contrato_211` usou)."""
    ind = gavetas.indice(base)
    por_evidencia = {e["evidencia_id"]: e for e in base["evidencias"]}
    saida: dict[str, list[dict]] = {}
    for objeto in base["objetos"]:
        if objeto["classe"] != "item_contrato":
            continue
        fatos = gavetas.fatos_do_objeto(base, objeto["objeto_id"], ind)
        if "folha_eap" not in fatos or "quantidade_calculada" not in fatos:
            continue
        if not _numero(fatos["quantidade_calculada"]["valor"]):
            continue
        citados = [fatos["folha_eap"]] + [
            fatos[p] for p in gavetas_contrato.PROPRIEDADES_CALCULO if p in fatos
        ]
        v = {p: f["valor"] for p, f in fatos.items()}
        saida.setdefault(v["folha_eap"], []).append(
            {
                **_linha_do_contrato(objeto, fatos, citados, por_evidencia),
                "quantidade": float(v["quantidade_calculada"]),
                "unidade": v.get("unidade_calculada"),
                "regra": v.get("regra_calculo"),
                "situacao_calculo": v.get("situacao_calculo"),
                "completa": v.get("situacao_calculo") == "calculada",
            }
        )
    return saida


def _totais_por_unidade(linhas: list[dict]) -> list[dict]:
    """Soma por unidade das linhas com quantidade: unidades diferentes nunca se somam."""
    somas: dict[str, float] = {}
    for linha in linhas:
        if linha["quantidade"] is not None:
            somas[linha["unidade"]] = (
                somas.get(linha["unidade"], 0.0) + linha["quantidade"]
            )
    return [
        {"unidade": u, "quantidade": round(v, 6)}
        for u, v in sorted(somas.items(), key=lambda x: str(x[0]))
    ]


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


def _medidas_da_folha(
    folha: dict, vista: str, por_item: dict[str, list[dict]], reservados: set
) -> list[dict]:
    """Quantidades medidas (fatos e serviços das gavetas) dos itens que a folha aponta (`<folha>/<código>`)."""
    escolhidas: dict[tuple, dict] = {}
    for alvo in folha["aponta"]:
        for q in por_item.get(alvo["item"], []):
            if q["n_com_valor"] and _vale(q, alvo, vista, reservados):
                escolhidas[(q["codigo"], q["grandeza"], q["unidade"], q["origem"])] = q
    campos = (
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
    return [
        {"codigo_eap": f"{folha['id']}/{q['codigo']}", **{k: q[k] for k in campos}}
        for _, q in sorted(escolhidas.items())
    ]


def _situacao(
    medidas: list[dict], calculadas: list[dict], declaradas: list[dict]
) -> str:
    """Situação da folha pela precedência medida > calculada pelo contrato > declarada (docstring do módulo): `preenchida`
    (medida de documento), `calculada` (só serviço de regra ou só quantidade calculada pelo contrato, completa),
    `declarada` (só a planilha declara) ou `a preencher`."""
    if medidas:
        return (
            "calculada"
            if all(q["origem"] == "servico" for q in medidas)
            else "preenchida"
        )
    if any(c["completa"] for c in calculadas):
        return "calculada"
    return (
        "declarada"
        if any(d["quantidade"] is not None for d in declaradas)
        else "a preencher"
    )


def _folha(
    folha: dict,
    vista: str,
    por_item: dict[str, list[dict]],
    origens: tuple[list[dict], list[dict]],
    reservados: set,
) -> dict:
    """Folha preenchida: quantidades medidas dos itens que ela aponta, as linhas calculadas pelo contrato e as declaradas
    (`origens` = (declaradas, calculadas), cada uma com totais por unidade, nunca somadas ao medido) e a situação."""
    declaradas, calculadas = origens
    medidas = _medidas_da_folha(folha, vista, por_item, reservados)
    return {
        "id": folha["id"],
        "nome": folha["nome"],
        "obrigatoria": folha["obrigatoria"],
        "escopo": folha.get("escopo", "ambos"),
        "aponta": folha["aponta"],
        "situacao": _situacao(medidas, calculadas, declaradas),
        "quantidades": medidas,
        "totais": _totais(medidas),
        "calculadas_contrato": calculadas,
        "totais_calculadas_contrato": _totais_por_unidade(
            [c for c in calculadas if c["completa"]]
        ),
        "declaradas": declaradas,
        "totais_declaradas": _totais_por_unidade(declaradas),
    }


def _completude(folhas: list[dict]) -> dict:
    """Folhas por situação, obrigatórias a preencher, % preenchida (medida de documento, com evidência) e % calculada
    (só serviço de regra, à parte como na EAP padrão atual) de um tipo de obra."""
    n = len(folhas)
    por_situacao = {
        s: sum(f["situacao"] == s for f in folhas)
        for s in ("preenchida", "calculada", "declarada", "a preencher")
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
        "pct_calculadas": round(100.0 * por_situacao["calculada"] / n, 1)
        if n
        else None,
    }


def _etapas_do_tipo(
    tipo: str, modelo: dict, por_item: dict, declaradas: dict, calculadas: dict
) -> tuple[list[dict], set, set]:
    """As etapas preenchidas de um tipo de obra, as quantidades usadas (`item|grandeza`) e os ids das folhas."""
    etapas, usadas, folhas_do_tipo = [], set(), set()
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
                (declaradas.get(f["id"], []), calculadas.get(f["id"], [])),
                reservados,
            )
            for f in etapa["folhas"]
        ]
        usadas |= {
            q["codigo_eap"].split("/", 1)[1] + "|" + q["grandeza"]
            for f in folhas
            for q in f["quantidades"]
        }
        folhas_do_tipo |= {f["id"] for f in folhas}
        etapas.append({"id": etapa["id"], "nome": etapa["nome"], "folhas": folhas})
    return etapas, usadas, folhas_do_tipo


def preencher(base: dict) -> dict:
    """Laço sobre o modelo `eap_padrao.json` (obra localizada e obra linear): cada folha soma as quantidades dos itens
    técnicos que aponta e traz as linhas do contrato calculadas (`calculadas_contrato`) e declaradas (`declaradas`, que
    inclui a Relação de Materiais), sem somar com o medido nem entre si.

    Situação, pela precedência medida > calculada pelo contrato > declarada (docstring do módulo): `preenchida` (há
    quantidade medida de documento, com fatos e evidências), `calculada` (só há serviço calculado por regra, como os
    complementares de `gavetas_servicos`, ou só quantidade calculada pelo `contrato_211`: não é medida e conta à parte),
    `declarada` (só a planilha declara quantidade), `a preencher` (nada); `obrigatoria` vem do modelo. Devolve {tipos: {tipo: {nome, prefixo, etapas, completude}},
    completude, quantidades_sem_folha, contrato_sem_folha, servicos_descartados}."""
    quantidades, descartados = _quantidades(base)
    por_item: dict[str, list[dict]] = {}
    for q in quantidades:
        por_item.setdefault(q["codigo"].split(".", 2)[2], []).append(q)
    declaradas, calculadas = _declaradas(base), _calculadas(base)
    tipos, usadas, folhas_do_modelo = {}, set(), set()
    for tipo, modelo in PADRAO["tipos"].items():
        etapas, usadas_do_tipo, folhas_do_tipo = _etapas_do_tipo(
            tipo, modelo, por_item, declaradas, calculadas
        )
        usadas |= usadas_do_tipo
        folhas_do_modelo |= folhas_do_tipo
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
            f for f in {**declaradas, **calculadas} if f not in folhas_do_modelo
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
            f"{tipo}: {c['preenchida']} preenchidas, {c['calculada']} calculadas, {c['declarada']} declaradas, "
            f"{c['a preencher']} a preencher de {c['folhas']} folhas ({c['pct_preenchidas']} % preenchidas, "
            f"{c['pct_calculadas']} % calculadas); obrigatórias a preencher: "
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
