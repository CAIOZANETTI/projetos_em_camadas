"""EAP para o HTML: nós, serviços, fatos e evidências já formatados em português do Brasil.

O Python calcula e formata (`1.234,56`, unidade da propriedade); o template só lê `dados["eap_gavetas"]`.
Caminho de volta: nó da EAP → serviços → fatos usados → evidência (documento, onde, trecho, executor).
"""
from __future__ import annotations

import json

from . import gavetas


def br(valor, casas: int = 2) -> str:
    """Número no formato brasileiro (vírgula decimal, ponto de milhar); None vira '—'."""
    if valor is None:
        return "—"
    texto = f"{float(valor):,.{casas}f}"
    return texto.replace(",", "\0").replace(".", ",").replace("\0", ".")


SEM_CODIGO = "—"
SITUACOES_CONCILIACAO = ("confere", gavetas.SITUACAO_MESMA_ORIGEM, "difere", "só nas gavetas", "só na EAP codificada", "não conciliado (sem medida declarada)",
                         "fora das gavetas")


def _unidade(propriedade: str) -> str | None:
    return gavetas.REGRAS["propriedades"].get(propriedade, {}).get("unidade")


def _com_unidade(texto: str, unidade: str | None) -> str:
    return f"{texto} {unidade}" if unidade else texto


def valor_txt(propriedade: str, valor) -> str:
    """Valor de um fato com a unidade da propriedade (`gavetas.json`); dicionário e lista viram texto resumido."""
    unidade = _unidade(propriedade)
    if valor is None:
        return "—"
    if isinstance(valor, dict):
        return "; ".join(f"{k} {_com_unidade(br(v), unidade)}" for k, v in valor.items())
    if isinstance(valor, (list, tuple)) and not all(isinstance(c, dict) for c in valor):
        soma = f", {_com_unidade(br(sum(valor)), unidade)}" if unidade and all(isinstance(c, (int, float)) for c in valor) else ""
        return f"{len(valor)} amostras{soma}"          # lista por metro (classes, pesos): resumo, não a lista
    if isinstance(valor, (list, tuple)) and valor and not any("de" in c for c in valor):
        return f"{len(valor)} itens"                   # marcas de cota e bases das cavas: resumo, não a lista
    if isinstance(valor, (list, tuple)):
        return "; ".join(f"{br(c['de'])}–{_com_unidade(br(c['ate']), unidade)} {c.get('descricao', '')}".rstrip() for c in valor)
    if isinstance(valor, str):
        return valor
    if unidade == "fração":
        porcentagem = float(valor) * 100
        return f"{br(porcentagem, 0 if abs(porcentagem - round(porcentagem)) < 1e-9 else 1)} %"
    return _com_unidade(br(valor, 0 if unidade == "mm" else 2), unidade)


def onde(localizador: dict) -> str:
    """Localizador da evidência em texto legível."""
    if "aba" in localizador and "linha" in localizador:
        return f"aba {localizador['aba']}, linha {localizador['linha']}"
    if "arquivo" in localizador and "furo" in localizador:
        return f"{localizador['arquivo']}, furo {localizador['furo']}"
    if "arquivo" in localizador and "chave" in localizador:
        return f"{localizador['arquivo']}, {localizador['chave']}"
    if "pagina" in localizador and "pasta_drive" in localizador:
        return f"{localizador['pasta_drive']}, p. {localizador['pagina']}"
    if "pranchas" in localizador and "criterio" in localizador:
        partes = [f"pranchas {', '.join(map(str, localizador['pranchas']))}"]
        if localizador.get("layers"):
            partes.append(f"layers {', '.join(map(str, localizador['layers']))}")
        return "; ".join(partes + [f"critério {localizador['criterio']}"])
    return json.dumps(localizador, ensure_ascii=False, separators=(",", ":"), default=str)


def _local(base: dict, objeto_id: str, ind: dict | None = None) -> str:
    return str(gavetas.fatos_do_objeto(base, objeto_id, ind).get("local", {}).get("valor", objeto_id))


def _evidencia(ev: dict | None) -> dict:
    ev = ev or {}
    return {"classe": ev.get("classe", ""), "documento": ev.get("documento", ""),
            "onde": onde(ev.get("localizador") or {}), "trecho": ev.get("trecho") or "", "executor": ev.get("executor", "")}


def _lastro(fatos: dict, evidencias: dict, servico_id: str, fato_id: str) -> dict:
    """O fato citado pelo serviço, com a evidência dele; sem um dos dois, erro: número sem caminho de volta não vai
    para o HTML (critério 1 da rodada 23)."""
    f = fatos.get(fato_id)
    if f is None or f.get("evidencia_id") not in evidencias:
        raise ValueError(f"serviço {servico_id} cita {'fato ' + fato_id if f is None else 'fato sem evidência ' + fato_id}"
                         " que não está na base")
    return f


def _fato(f: dict, evidencias: dict) -> dict:
    return {"propriedade": f["propriedade"], "valor_txt": valor_txt(f["propriedade"], f["valor"]),
            "natureza": f["natureza"], "evidencia": _evidencia(evidencias.get(f["evidencia_id"]))}


def _por_setor(base: dict, servicos: list[dict], nos: list[dict], setor_por_objeto: dict, ind: dict) -> list[dict]:
    """`dados["eap_gavetas"]["setores"]`: os nós de cada setor formatados. A soma dos setores mais o "fora dos setores" tem de
    ser o total do nó. Tolerância: a maior entre `TOLERANCIA_SOMA_SETORES` e o erro máximo do arredondamento a 3 casas
    feito serviço a serviço nas duas somas (0,0005 × 2 × n de serviços do nó). Antes da soma, a contagem de serviços
    por nó é conferida exatamente: um serviço contado em dobro ou perdido é `ValueError`, de qualquer valor. Um
    serviço trocado de setor não muda nem a soma nem a contagem: quem o garante são os testes de `setor_de` e
    `setor_dos_servicos`."""
    ordem = [o["objeto_id"] for o in base.get("objetos", []) if o["classe"] == "setor"]
    grupos = gavetas.para_eap_por_setor(servicos, setor_por_objeto, ordem)
    for no in nos:
        contagem = sum(n["n_servicos"] for g in grupos for n in g["nos"] if n["eap"] == no["eap"])
        if contagem != len(no["servicos"]):                     # exata: pega serviço contado em dobro ou perdido
            raise ValueError(f"nó {no['eap']}: os setores somam {contagem} serviços e o nó tem {len(no['servicos'])}")
        soma = sum(n["valor"] for g in grupos for n in g["nos"] if n["eap"] == no["eap"])
        limite = max(gavetas.TOLERANCIA_SOMA_SETORES, 0.0005 * len(no["servicos"]) * 2)   # 2 somas arredondadas a 3 casas
        if abs(soma - no["valor"]) > limite:
            raise ValueError(f"nó {no['eap']}: a soma dos setores ({soma}) difere do total ({no['valor']})")
    saida = []
    for g in grupos:
        nome = "Fora dos setores" if g["setor_id"] is None else str(
            gavetas.fatos_do_objeto(base, g["setor_id"], ind).get("nome", {}).get("valor", g["setor_id"]))
        saida.append({"setor_id": g["setor_id"], "nome": nome,
                      "nos": [{"eap": n["eap"], "descricao": n["descricao"], "unidade": n["unidade"],
                               "valor_txt": br(n["valor"], 0 if n["unidade"] == "un" else 2), "n_servicos": n["n_servicos"]}
                              for n in g["nos"]]})
    return saida


SITUACOES_DOCUMENTO = (gavetas.CONFERE_DOCUMENTO, gavetas.DIFERE_DOCUMENTO, gavetas.CONFLITO_DOCUMENTO,
                       gavetas.SEM_DOCUMENTO)
ORIGEM_TXT = {"mesma": "mesma origem", "independente": "origens independentes", "indeterminada": "indeterminada"}


def _situacao_documento_txt(linha: dict, texto) -> str:
    """Situação frente ao documento com a diferença em unidade e em % (referência − documento), pronta para exibir."""
    situacao = linha.get("situacao_documento") or gavetas.SEM_DOCUMENTO
    if situacao != gavetas.DIFERE_DOCUMENTO or linha.get("diferenca_documento") is None:
        return situacao
    pct = linha.get("diferenca_documento_pct")
    return f"{situacao} (Δ {texto(linha['diferenca_documento'], linha['unidade'])}" + (
        f" · {br(pct, 1)} %)" if pct is not None else ")")


def _origem_insumos_txt(l: dict) -> str:
    """Insumos de cada lado, para o `title` da coluna Origem: "gavetas: …; codificada: …"."""
    lado = lambda nome, insumos: f"{nome}: {', '.join(insumos) if insumos else 'indeterminada'}"
    return "; ".join([lado("gavetas", l.get("origem_gavetas")), lado("codificada", l.get("origem_codificada"))])


def _decisao_txt(l: dict, texto) -> str:
    """Decisão do engenheiro, à parte do documento: "decisão de ana: 1.000,00 m³"; sem decisão, '—'."""
    return "; ".join(f"decisão de {d['autor']}: {texto(d['valor'], l['unidade'])}" for d in l.get("decisoes") or []) or "—"


def _colunas_do_documento(l: dict, texto) -> dict:
    """Terceira coluna (documento independente) em texto pronto."""
    return {"documento_txt": texto(l.get("documento"), l["unidade"]),
            "documentos_txt": "; ".join(l.get("documentos") or []) or "—", "decisao_txt": _decisao_txt(l, texto),
            "situacao_documento": l.get("situacao_documento") or gavetas.SEM_DOCUMENTO,
            "situacao_documento_txt": _situacao_documento_txt(l, texto)}


def _linha_conciliada(l: dict, texto) -> dict:
    """Uma linha da conciliação em texto pronto: três colunas de medida, situação, origem e documento."""
    mesma = l.get("origem") == "mesma" and l["situacao"] in (gavetas.SITUACAO_MESMA_ORIGEM, "difere")
    return {"codigo": l["codigo"], "unidade": l["unidade"], "gavetas_txt": texto(l["gavetas"], l["unidade"]),
            "codificada_txt": texto(l["codificada"], l["unidade"]), "diferenca_txt": texto(l["diferenca"], l["unidade"]),
            "situacao": l["situacao"], "mesma_origem": mesma,
            "origem_txt": ORIGEM_TXT.get(l.get("origem") or "indeterminada", "indeterminada"),
            "origem_insumos_txt": _origem_insumos_txt(l), "motivo": l.get("motivo") or "",
            **_colunas_do_documento(l, texto)}


def _total_conciliado(t: dict, texto) -> dict:
    """Total por unidade e item (fato com `*`): soma das linhas e terceira coluna, em texto pronto."""
    return {"codigo": t["codigo"], "unidade": t["unidade"], "n_linhas": t["n_linhas"],
            "gavetas_txt": texto(t["gavetas"], t["unidade"]), "codificada_txt": texto(t["codificada"], t["unidade"]),
            "origem_insumos_txt": _origem_insumos_txt(t), **_colunas_do_documento(t, texto)}


def conciliacao(linhas: list[dict], totais: list[dict] | None = None) -> dict:
    """`dados["eap_gavetas"]["conciliacao"]`: as linhas de `gavetas.conciliar_eap` já formatadas e a contagem por
    situação (`resumo`) e por situação frente ao documento (`resumo_documento`). Quantidade e diferença com a unidade
    do código; o que uma das EAP não mede fica '—'. `mesma_origem` marca o que o selo da aba destaca (confere sem
    independência e difere com a mesma origem). `totais` (`gavetas.conciliar_totais`): o fato `U1.*.ITEM` contra a
    soma dos sistemas, no bloco `totais`."""
    texto = lambda v, un: "—" if v is None else f"{br(v, 0 if un == 'un' else 2)} {un}"
    exibidas = [l for l in linhas if l["situacao"] != "fora das gavetas"]      # fora: só a contagem no resumo
    sem = gavetas.SEM_DOCUMENTO
    return {"resumo": {s: sum(1 for l in linhas if l["situacao"] == s) for s in SITUACOES_CONCILIACAO},
            "resumo_documento": {s: sum(1 for l in exibidas if (l.get("situacao_documento") or sem) == s)
                                 for s in SITUACOES_DOCUMENTO},
            "linhas": [_linha_conciliada(l, texto) for l in exibidas],
            "totais": [_total_conciliado(t, texto) for t in totais or []]}


def montar(base: dict, servicos: list[dict], pendencias: list[dict], resumo: dict | None = None,
           setores: dict | None = None) -> dict:
    """`dados["eap_gavetas"]`: nós, pendências e resumo, tudo em texto pronto para o HTML. Com `setores` (o mapa de
    `gavetas.setor_de`), acrescenta a chave `setores`: a EAP de cada setor."""
    ind = gavetas.indice(base)
    fatos = {f["fato_id"]: f for f in base.get("fatos", [])}
    evidencias = {e["evidencia_id"]: e for e in base.get("evidencias", [])}
    por_id = {s["servico_id"]: s for s in servicos}
    nos, totais = [], gavetas.para_eap(servicos)
    for no in totais:
        itens = []
        for sid in no["servicos"]:
            s = por_id[sid]
            itens.append({"servico_id": sid, "objeto_id": s["objeto_id"], "local": _local(base, s["objeto_id"], ind),
                          "regra": s["regra"], "versao_regra": str(s["versao_regra"]),
                          "codigo_eap": s.get("codigo_eap") or SEM_CODIGO,
                          "valor_txt": br(s["valor"], 0 if no["unidade"] == "un" else 2),
                          "fatos": [_fato(_lastro(fatos, evidencias, sid, i), evidencias) for i in s["fatos"]]})
        codigos = {i["codigo_eap"] for i in itens}
        nos.append({"eap": no["eap"], "descricao": no["descricao"], "unidade": no["unidade"],
                    "codigo_eap": codigos.pop() if len(codigos) == 1 else SEM_CODIGO,      # só se todos os serviços têm o mesmo
                    "valor_txt": br(no["valor"], 0 if no["unidade"] == "un" else 2), "servicos": itens})
    lista = [{"objeto_id": p["objeto_id"], "local": _local(base, p["objeto_id"], ind), "motivo": p["motivo"]} for p in pendencias]
    contagem = {"servicos": len(servicos), "nos": len(nos), "pendencias": len(lista), "diferencas_paridade": 0,
                "recalculados": 0, "reaproveitados": 0}
    dado = resumo or {}                                   # só as chaves do contrato; o resto do resumo fica fora do HTML
    eap = {"nos": nos, "pendencias": lista, "resumo": {k: dado.get(k, v) for k, v in contagem.items()}}
    if setores is not None:
        eap["setores"] = _por_setor(base, servicos, totais, setores, ind)
    return eap


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "eap_html",
        "descricao": "EAP lastreada formatada em português do Brasil para a aba EAP do visualizador",
        "funcoes": ["br", "valor_txt", "onde", "conciliacao", "montar"],
        "formato_numero": "vírgula decimal e ponto de milhar",
        "contrato": "dados['eap'] = {nos, pendencias, resumo} (docs/plano/2026-11-01_rodada23.md)",
    }
