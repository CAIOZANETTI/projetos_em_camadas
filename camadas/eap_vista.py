"""Vista da aba EAP pronta para o HTML: seções, árvore WBS, Contrato 211 por UC e trecho, filtros e índice de busca.

O Python conta, agrupa, formata (`1.234,56`) e normaliza o texto de busca; o template só lê `dados["eap_vista"]`.
Entradas (já montadas no build): `eap_padrao`, `contrato_211`, `eap_painel`, `eap_gavetas`, `conferencia_cavas`.
Sem preço e sem número inventado: o que falta aparece como "—" ou como situação.
"""

from __future__ import annotations

import re
import unicodedata

from .eap_html import br

SEM_UC = "Itens gerais (sem UC)"
SEM_TRECHO = "Itens gerais da UC"
SEM_VALOR = "—"

_PLURAL = {  # situação no singular → plural, para "3 preenchidas"
    "preenchida": "preenchidas",
    "preenchida (manual)": "preenchidas (manual)",
    "calculada": "calculadas",
    "declarada": "declaradas",
    "declarada · confere": "declaradas · confere",
    "declarada · diverge": "declaradas · divergem",
}
_PREENCHIDAS = ("preenchida", "preenchida (manual)")
_ROTULOS_SECAO = {
    "wbs": "WBS · EAP padrão",
    "contrato": "Contrato 211",
    "codificada": "EAP codificada",
    "gavetas": "Gavetas",
    "cavas": "Conferência das cavas",
}


def normalizar(texto) -> str:
    """Minúsculas e sem acento, para a busca; vários textos viram um só, separados por espaço."""
    if isinstance(texto, (list, tuple)):
        texto = " ".join(str(t) for t in texto if t)
    base = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in base if unicodedata.category(c) != "Mn")


def _id_da_situacao(situacao: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(situacao)).strip("-")


def _contagem_txt(n: int, rotulo: str) -> str:
    """'3 preenchidas', '1 preenchida', '2 a preencher'."""
    return f"{br(n, 0)} {_PLURAL.get(rotulo, rotulo) if n != 1 else rotulo}"


def _contar(situacoes: list[str]) -> dict:
    """{situação: n} só das que aparecem, na ordem da primeira aparição."""
    contagem: dict = {}
    for situacao in situacoes:
        contagem[situacao] = contagem.get(situacao, 0) + 1
    return contagem


def _contagens_txt(total: int, substantivo: str, contagem: dict) -> str:
    """'5 folhas · 3 preenchidas · 2 a preencher'."""
    plural = substantivo if total == 1 else substantivo + "s"
    return " · ".join(
        [
            f"{br(total, 0)} {plural}",
            *(_contagem_txt(n, s) for s, n in contagem.items()),
        ]
    )


def _filtros(situacoes: list[str], ordem: list[str] | None = None) -> list[dict]:
    """Lista de filtros `{id, rotulo, n}` por situação existente; as da `ordem` primeiro."""
    contagem = _contar(situacoes)
    ordenadas = [s for s in (ordem or []) if s in contagem] + [
        s for s in contagem if s not in (ordem or [])
    ]
    return [
        {"id": _id_da_situacao(s), "rotulo": s, "n": contagem[s]} for s in ordenadas
    ]


def _linha_do_contrato(linha: dict) -> dict:
    """Linha do Contrato 211 para a vista; o texto de busca junta tudo o que o leitor pode procurar."""
    calculada = linha.get("calculada") or ""
    calculada_txt = (
        f"{calculada} {linha.get('unidade_calculada') or ''}".strip()
        if calculada
        else SEM_VALOR
    )
    detalhe = [*(linha.get("evidencias") or []), *(linha.get("premissas") or [])]
    numero = linha.get("linha")
    return {
        "id": linha.get("id")
        or f"c211-{_id_da_situacao(str(linha.get('aba')))}-{numero}",
        "linha_txt": f"{linha.get('aba')} · {numero}",
        "composicao": linha.get("composicao"),
        "descricao": linha.get("descricao"),
        "unidade": linha.get("unidade"),
        "declarada": linha.get("declarada") or SEM_VALOR,
        "calculada_txt": calculada_txt,
        "situacao": linha.get("situacao"),
        "motivo": linha.get("motivo"),
        "detalhe": detalhe,
        "projeto": linha.get("projeto"),
        "folha_eap": linha.get("folha_eap"),
        "redes": list(linha.get("redes") or []),
        "pranchas": list(linha.get("pranchas") or []),
        "busca": normalizar(
            [
                linha.get("id"),
                linha.get("composicao"),
                linha.get("descricao"),
                linha.get("uc"),
                linha.get("trecho"),
                linha.get("folha_eap"),
                linha.get("situacao"),
                linha.get("motivo"),
                linha.get("projeto"),
                *detalhe,
                *(linha.get("redes") or []),
                *(linha.get("pranchas") or []),
            ]
        ),
    }


def _projetos(linhas: list[dict]) -> str | None:
    distintos = list(dict.fromkeys(l["projeto"] for l in linhas if l.get("projeto")))
    return " · ".join(distintos) or None


def _contrato(contrato: dict | None) -> dict | None:
    """Contrato 211 em `unidades` → `trechos` → `linhas`, na ordem da planilha."""
    if not contrato or not contrato.get("linhas"):
        return None
    grupos: dict = {}
    for bruta in contrato["linhas"]:
        uc = bruta.get("uc") or SEM_UC
        trecho = bruta.get("trecho") or SEM_TRECHO
        grupos.setdefault(uc, {}).setdefault(trecho, []).append(bruta)
    unidades = []
    for i, (uc, trechos) in enumerate(grupos.items(), start=1):
        nos = []
        for trecho, brutas in trechos.items():
            contagem = _contar([b["situacao"] for b in brutas])
            nos.append(
                {
                    "rotulo": trecho,
                    "n": len(brutas),
                    "contagens": contagem,
                    "contagens_txt": _contagens_txt(len(brutas), "linha", contagem),
                    "projeto": _projetos(brutas),
                    "linhas": [_linha_do_contrato(b) for b in brutas],
                }
            )
        todas = [b for brutas in trechos.values() for b in brutas]
        contagem = _contar([b["situacao"] for b in todas])
        unidades.append(
            {
                "id": f"c211-uc-{i}",
                "rotulo": uc,
                "n": len(todas),
                "contagens": contagem,
                "contagens_txt": _contagens_txt(len(todas), "linha", contagem),
                "trechos": nos,
            }
        )
    return {
        "resumo_txt": contrato.get("resumo_txt") or [],
        "premissas": contrato.get("premissas") or [],
        "unidades": unidades,
    }


def _folha(folha: dict, do_contrato: list[dict]) -> dict:
    """Folha da EAP padrão com as linhas (brutas, de `contrato_211`) penduradas nela."""
    enxutas = []
    for bruta in do_contrato:
        vista = _linha_do_contrato(bruta)
        enxutas.append(
            {
                "id": vista["id"],
                "descricao": bruta["descricao"],
                "calculada": bruta.get("calculada") or SEM_VALOR,
                "unidade": bruta.get("unidade_calculada")
                if bruta.get("calculada")
                else None,
                "calculada_txt": vista["calculada_txt"],
                "situacao": bruta["situacao"],
            }
        )
    n = len(enxutas)
    return {
        "id": folha["id"],
        "rotulo": f"{folha['id']} · {folha['nome']}",
        "situacao": folha["situacao"],
        "situacao_txt": folha.get("situacao_txt") or folha["situacao"],
        "quantidades_txt": folha.get("quantidades_txt") or [],
        "obrigatoria": bool(folha.get("obrigatoria")),
        "contrato": enxutas,
        "n_contrato_txt": "sem linhas no contrato"
        if not n
        else f"{br(n, 0)} {'linha' if n == 1 else 'linhas'} no contrato",
        "busca": normalizar(
            [
                folha["id"],
                folha["nome"],
                *(folha.get("quantidades_txt") or []),
                *(l["descricao"] for l in enxutas),
            ]
        ),
    }


def _wbs(
    eap_padrao: dict | None, linhas_por_folha: dict
) -> tuple[dict | None, list[str]]:
    """Árvore tipo → etapa → folha e a lista de situações das folhas (para os filtros)."""
    if not eap_padrao or not eap_padrao.get("tipos"):
        return None, []
    todas: list[str] = []
    tipos = []
    for tipo in eap_padrao["tipos"]:
        etapas = []
        folhas_do_tipo: list[str] = []
        for etapa in tipo.get("etapas", []):
            folhas = [
                _folha(f, linhas_por_folha.get(f["id"], []))
                for f in etapa.get("folhas", [])
            ]
            situacoes = [f["situacao"] for f in folhas]
            contagem = _contar(situacoes)
            folhas_do_tipo += situacoes
            etapas.append(
                {
                    "id": etapa["id"],
                    "rotulo": f"{etapa['id']} · {etapa['nome']}",
                    "n_folhas": len(folhas),
                    "contagens": contagem,
                    "contagens_txt": _contagens_txt(len(folhas), "folha", contagem),
                    "folhas": folhas,
                }
            )
        todas += folhas_do_tipo
        contagem = _contar(folhas_do_tipo)
        tipos.append(
            {
                "id": tipo["tipo"],
                "rotulo": tipo["nome"],
                "n_folhas": len(folhas_do_tipo),
                "contagens": contagem,
                "contagens_txt": _contagens_txt(len(folhas_do_tipo), "folha", contagem),
                "etapas": etapas,
            }
        )
    return {"tipos": tipos}, todas


def _secoes(dados: dict, wbs_situacoes: list[str], contrato: dict | None) -> list[dict]:
    """Só as seções que têm dado, na ordem de leitura."""
    secoes = []
    if wbs_situacoes:
        pct = (
            100
            * sum(1 for s in wbs_situacoes if s in _PREENCHIDAS)
            / len(wbs_situacoes)
        )
        secoes.append(
            ("wbs", f"{br(len(wbs_situacoes), 0)} folhas · {br(pct, 0)} % preenchidas")
        )
    if contrato:
        todas = [
            l["situacao"]
            for u in contrato["unidades"]
            for t in u["trechos"]
            for l in t["linhas"]
        ]
        calculadas = sum(1 for s in todas if s == "calculada")
        secoes.append(
            ("contrato", f"{br(len(todas), 0)} linhas · {br(calculadas, 0)} calculadas")
        )
    painel = dados.get("eap_painel") or {}
    if painel.get("arvore"):
        fatos = (painel.get("resumo") or {}).get("fatos", 0)
        secoes.append(
            ("codificada", f"{br(len(painel['arvore']), 0)} nós · {br(fatos, 0)} fatos")
        )
    gavetas = dados.get("eap_gavetas") or {}
    if gavetas.get("nos"):
        servicos = (gavetas.get("resumo") or {}).get("servicos", 0)
        secoes.append(
            (
                "gavetas",
                f"{br(len(gavetas['nos']), 0)} nós · {br(servicos, 0)} serviços",
            )
        )
    cavas = dados.get("conferencia_cavas") or {}
    if cavas.get("secoes"):
        placar = cavas.get("placar") or {}
        resumo = " · ".join(f"{br(n, 0)} {nome}" for nome, n in placar.items() if n)
        secoes.append(("cavas", resumo or f"{br(len(cavas['secoes']), 0)} seções"))
    return [
        {"id": i, "rotulo": _ROTULOS_SECAO[i], "n_txt": n_txt} for i, n_txt in secoes
    ]


def _ordem_das_situacoes(eap_padrao: dict | None) -> list[str]:
    """Ordem canônica das situações da EAP padrão (a do `resumo` da primeira etapa que a traz)."""
    for tipo in (eap_padrao or {}).get("tipos", []):
        for etapa in tipo.get("etapas", []):
            if etapa.get("resumo", {}).get("por_situacao"):
                return [s["situacao"] for s in etapa["resumo"]["por_situacao"]]
    return []


def montar(dados: dict) -> dict | None:
    """Vista da aba EAP (`dados["eap_vista"]`); None sem EAP padrão e sem Contrato 211."""
    contrato = _contrato(dados.get("contrato_211"))
    linhas_por_folha: dict = {}
    for bruta in (
        (dados.get("contrato_211") or {}).get("linhas", []) if contrato else []
    ):
        if bruta.get("folha_eap"):
            linhas_por_folha.setdefault(bruta["folha_eap"], []).append(bruta)
    wbs, situacoes_wbs = _wbs(dados.get("eap_padrao"), linhas_por_folha)
    if wbs is None and contrato is None:
        return None
    ordem_wbs = _ordem_das_situacoes(dados.get("eap_padrao"))
    ordem_contrato = list(
        ((dados.get("contrato_211") or {}).get("resumo") or {}).get("por_situacao", {})
    )
    situacoes_contrato = (
        [
            l["situacao"]
            for u in contrato["unidades"]
            for t in u["trechos"]
            for l in t["linhas"]
        ]
        if contrato
        else []
    )
    vista = {
        "secoes": _secoes(dados, situacoes_wbs, contrato),
        "situacoes": {
            "wbs": _filtros(situacoes_wbs, ordem_wbs),
            "contrato": _filtros(situacoes_contrato, ordem_contrato),
        },
    }
    if wbs is not None:
        vista["wbs"] = wbs
    if contrato is not None:
        vista["contrato"] = contrato
    return vista


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "eap_vista",
        "descricao": "vista da aba EAP: seções, árvore WBS com o Contrato 211 pendurado nas folhas, Contrato por UC e "
        "trecho, filtros por situação e texto de busca normalizado, tudo pronto em pt-BR para o HTML apresentar",
        "funcoes": ["normalizar", "montar", "metadados"],
        "entradas": [
            "eap_padrao",
            "contrato_211",
            "eap_painel",
            "eap_gavetas",
            "conferencia_cavas",
        ],
        "premissas": [
            {
                "aplicacao": {"montar": ["secoes", "situacoes", "wbs", "contrato"]},
                "fonte": "apresentação; nenhum número novo: só contagem e formatação do que os módulos de origem calcularam",
                "estado": "confirmado",
            }
        ],
    }
