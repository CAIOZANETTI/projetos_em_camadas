"""EAP para o HTML: nós, serviços, fatos e evidências já formatados em português do Brasil.

O Python calcula e formata (`1.234,56`, unidade da propriedade); o template só lê `dados["eap"]`.
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
    return json.dumps(localizador, ensure_ascii=False, separators=(",", ":"), default=str)


def _local(base: dict, objeto_id: str) -> str:
    return str(gavetas.fatos_do_objeto(base, objeto_id).get("local", {}).get("valor", objeto_id))


def _evidencia(ev: dict | None) -> dict:
    ev = ev or {}
    return {"classe": ev.get("classe", ""), "documento": ev.get("documento", ""),
            "onde": onde(ev.get("localizador") or {}), "trecho": ev.get("trecho") or "", "executor": ev.get("executor", "")}


def _fato(f: dict, evidencias: dict) -> dict:
    return {"propriedade": f["propriedade"], "valor_txt": valor_txt(f["propriedade"], f["valor"]),
            "natureza": f["natureza"], "evidencia": _evidencia(evidencias.get(f["evidencia_id"]))}


def montar(base: dict, servicos: list[dict], pendencias: list[dict], resumo: dict | None = None) -> dict:
    """`dados["eap"]`: nós, pendências e resumo, tudo em texto pronto para o HTML."""
    fatos = {f["fato_id"]: f for f in base.get("fatos", [])}
    evidencias = {e["evidencia_id"]: e for e in base.get("evidencias", [])}
    por_id = {s["servico_id"]: s for s in servicos}
    nos = []
    for no in gavetas.para_eap(servicos):
        itens = []
        for sid in no["servicos"]:
            s = por_id[sid]
            itens.append({"servico_id": sid, "objeto_id": s["objeto_id"], "local": _local(base, s["objeto_id"]),
                          "regra": s["regra"], "versao_regra": str(s["versao_regra"]), "valor_txt": br(s["valor"]),
                          "fatos": [_fato(fatos[i], evidencias) for i in s["fatos"] if i in fatos]})
        nos.append({"eap": no["eap"], "descricao": no["descricao"], "unidade": no["unidade"],
                    "valor_txt": br(no["valor"]), "servicos": itens})
    lista = [{"objeto_id": p["objeto_id"], "local": _local(base, p["objeto_id"]), "motivo": p["motivo"]} for p in pendencias]
    contagem = {"servicos": len(servicos), "nos": len(nos), "pendencias": len(lista), "diferencas_paridade": 0,
                "recalculados": 0, "reaproveitados": 0}
    dado = resumo or {}                                   # só as chaves do contrato; o resto do resumo fica fora do HTML
    return {"nos": nos, "pendencias": lista, "resumo": {k: dado.get(k, v) for k, v in contagem.items()}}


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "eap_html",
        "descricao": "EAP lastreada formatada em português do Brasil para a aba EAP do visualizador",
        "funcoes": ["br", "valor_txt", "onde", "montar"],
        "formato_numero": "vírgula decimal e ponto de milhar",
        "contrato": "dados['eap'] = {nos, pendencias, resumo} (docs/plano/2026-11-01_rodada23.md)",
    }
