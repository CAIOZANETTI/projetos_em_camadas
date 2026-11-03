"""EAP padrão por tipo de obra: esqueleto por etapa de execução, a preencher a cada obra.

A EAP codificada (`camadas.eap`) é por disciplina (GEO/CIV/HID/ELE → pacote → item) e continua sendo a linha mestra
técnica. O padrão de `conceitos/eap_padrao.json` é uma VISTA por etapa de execução (ordem de obra) que aponta para os
códigos da EAP codificada: não cria quantificação nova. Cada folha diz se a obra já a preencheu:

    preenchida          quantidade da EAP codificada (com elementos) ou fato com valor nos códigos apontados
    só menção           só fato sem valor (menção, conflito) ou quantidade sem elemento medido
    a preencher         nada nos códigos apontados (se `obrigatoria`, vem em destaque)
    não se aplica       declarada em obra.json → eap_padrao.nao_se_aplica [{id, justificativa, autor}]
    sem item codificado folha sem `aponta`: preenchida à mão, fora da EAP codificada

Numeração e nomes das etapas são premissa a conferir com o MOS Sanepar (que não está no repositório).
Determinístico: o Python soma, conta e formata (pt-BR); o HTML só apresenta `dados["eap_padrao"]`.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import eap
from .eap_html import br
from .pdf_cad import CONCEITOS

PADRAO = json.loads((CONCEITOS / "eap_padrao.json").read_text(encoding="utf-8"))
TIPOS = PADRAO["tipos"]
OBRA_DO_TIPO = {"obra_localizada": "localizada", "obra_linear": "linear"}
ESCOPOS = ("agua", "esgoto", "ambos")
SERVICOS = {
    json.loads(linha)["id"]: json.loads(linha)["nome"]
    for linha in (CONCEITOS / "servicos.jsonl").read_text(encoding="utf-8").splitlines()
    if linha.strip()
}

PREENCHIDA = "preenchida"
SO_MENCAO = "só menção"
A_PREENCHER = "a preencher"
NAO_SE_APLICA = "não se aplica"
SEM_ITEM = "sem item codificado"
SITUACOES = (PREENCHIDA, SO_MENCAO, A_PREENCHER, NAO_SE_APLICA, SEM_ITEM)

REGRA_TIPO = (
    "Tipo da obra: `eap_padrao.tipo` do obra.json (texto ou lista) manda. Sem ele: há obras lineares (`obras_lineares` "
    "ou `valas`) e nenhum sinal de unidade localizada (`estacas`, `elementos_declarados`, `escavacao` ou prancha de "
    "obra localizada) → obra linear; há os dois sinais → obra mista, os dois tipos; senão → obra localizada."
)
AVISO_PREMISSA = (
    "Esqueleto em estado de premissa: a numeração e os nomes das etapas são a conferir com o MOS Sanepar, "
    "que não está no repositório."
)


def _folhas_do_tipo(tipo: str) -> list[dict]:
    """Folhas do tipo, na ordem de obra, cada uma com o id e o nome da etapa."""
    return [
        {**folha, "etapa_id": etapa["id"], "etapa_nome": etapa["nome"]}
        for etapa in TIPOS[tipo]["etapas"]
        for folha in etapa["folhas"]
    ]


def _problemas_da_folha(tipo: str, folha: dict, itens: dict) -> list[str]:
    """Erros de uma folha: item inexistente ou de outro tipo de obra, serviço desconhecido ou não admitido, escopo
    inválido e folha sem item e sem observação."""
    problemas = []
    for alvo in folha["aponta"]:
        item = itens.get(alvo["item"])
        if item is None:
            problemas.append(f"{folha['id']}: item '{alvo['item']}' fora de eap_geral")
            continue
        if OBRA_DO_TIPO[tipo] not in item["obra"]:
            problemas.append(
                f"{folha['id']}: item '{alvo['item']}' não vale para {tipo}"
            )
        servico = alvo.get("servico")
        if servico and servico not in SERVICOS:
            problemas.append(
                f"{folha['id']}: serviço '{servico}' fora de servicos.jsonl"
            )
        elif servico and servico not in item["servicos"]:
            problemas.append(
                f"{folha['id']}: serviço '{servico}' não é admitido no item '{alvo['item']}'"
            )
    if not folha["aponta"] and not folha.get("observacao"):
        problemas.append(
            f"{folha['id']}: folha sem item codificado precisa de `observacao`"
        )
    if folha.get("escopo", "ambos") not in ESCOPOS:
        problemas.append(f"{folha['id']}: escopo '{folha['escopo']}' desconhecido")
    return problemas


def validar() -> tuple[list[str], list[str]]:
    """(erros, avisos) do padrão. Erro: id repetido ou fora do prefixo, item ou serviço inexistente, serviço não
    admitido pelo item, item de outro tipo de obra. Aviso: item de eap_geral do tipo de obra que nenhuma folha cita
    ("item fora do padrão")."""
    itens, erros, avisos, ids = eap.itens(), [], [], []
    for tipo, dados_tipo in TIPOS.items():
        folhas = _folhas_do_tipo(tipo)
        ids += [f["id"] for f in folhas] + [e["id"] for e in dados_tipo["etapas"]]
        erros += [
            f"{f['id']}: id fora do prefixo {dados_tipo['prefixo']}"
            for f in folhas
            if not f["id"].startswith(
                f"{dados_tipo['prefixo']}.{f['etapa_id'].split('.')[1]}."
            )
        ]
        for folha in folhas:
            erros += _problemas_da_folha(tipo, folha, itens)
        citados = {a["item"] for f in folhas for a in f["aponta"]}
        avisos += [
            f"{tipo}: item fora do padrão: {codigo}"
            for codigo, item in itens.items()
            if OBRA_DO_TIPO[tipo] in item["obra"] and codigo not in citados
        ]
    erros += [f"id repetido: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return erros, avisos


def itens_fora_do_padrao() -> list[dict]:
    """[{tipo, codigo, nome}] dos itens de eap_geral do tipo de obra que nenhuma folha do tipo cita."""
    itens = eap.itens()
    saida = []
    for tipo in TIPOS:
        citados = {a["item"] for f in _folhas_do_tipo(tipo) for a in f["aponta"]}
        saida += [
            {"tipo": tipo, "codigo": codigo, "nome": item["nome"]}
            for codigo, item in itens.items()
            if OBRA_DO_TIPO[tipo] in item["obra"] and codigo not in citados
        ]
    return saida


def _tem_prancha_localizada(cfg: dict) -> bool:
    """Alguma prancha do obra.json é de unidade de obra localizada (pelo nome do PDF, `eap._unidade_da_prancha`)."""
    unidades = eap.UNIDADES["unidades"]
    return any(
        unidades[eap._unidade_da_prancha(p).lower()]["obra"] == "localizada"
        for p in cfg.get("pranchas") or []
    )


def tipo_da_obra(cfg: dict) -> list[str]:
    """Tipos de EAP padrão da obra, na ordem do arquivo. Regra (`REGRA_TIPO`): `eap_padrao.tipo` do obra.json manda;
    senão linear = `obras_lineares` ou `valas`; localizada = `estacas`, `elementos_declarados`, `escavacao` ou prancha
    localizada; só linear → obra_linear; os dois → obra mista (lista com os dois); nenhum ou só localizada →
    obra_localizada."""
    declarado = (cfg.get("eap_padrao") or {}).get("tipo")
    if declarado:
        lista = [declarado] if isinstance(declarado, str) else list(declarado)
        desconhecidos = [t for t in lista if t not in TIPOS]
        if desconhecidos:
            raise ValueError(
                f"eap_padrao.tipo desconhecido: {desconhecidos}; use {list(TIPOS)}"
            )
        return [t for t in TIPOS if t in lista]
    linear = bool(cfg.get("obras_lineares") or cfg.get("valas"))
    localizada = bool(
        cfg.get("estacas")
        or cfg.get("elementos_declarados")
        or cfg.get("escavacao")
        or _tem_prancha_localizada(cfg)
    )
    if linear and not localizada:
        return ["obra_linear"]
    return ["obra_localizada", "obra_linear"] if linear else ["obra_localizada"]


def _mapa_declaracoes(declaracoes: list[dict] | None) -> dict[str, dict]:
    """{id da folha: declaração} do `nao_se_aplica`. Justificativa é obrigatória; id desconhecido é erro."""
    conhecidos = {f["id"] for t in TIPOS for f in _folhas_do_tipo(t)}
    mapa = {}
    for d in declaracoes or []:
        if d.get("id") not in conhecidos:
            raise ValueError(
                f"eap_padrao.nao_se_aplica: folha '{d.get('id')}' não existe no padrão"
            )
        if not str(d.get("justificativa") or "").strip():
            raise ValueError(
                f"eap_padrao.nao_se_aplica: '{d['id']}' sem justificativa (obrigatória para declarar não se aplica)"
            )
        mapa[d["id"]] = d
    return mapa


def _item_do_codigo(codigo: str) -> str:
    """'U1.ACT600.GEO.FUN.EST' → 'GEO.FUN.EST' (os dois primeiros segmentos são unidade e sistema)."""
    return ".".join(str(codigo).split(".")[2:])


def _indice_quantidades(eap_codificada: dict | None) -> dict[str, list[dict]]:
    """Quantidades da EAP codificada agrupadas pelo item (sem unidade e sistema)."""
    indice: dict[str, list[dict]] = {}
    for q in (eap_codificada or {}).get("quantidades") or []:
        indice.setdefault(_item_do_codigo(q["codigo"]), []).append(q)
    return indice


def _lista_de_fatos(evidencias: dict | list | None) -> list[dict]:
    """Aceita `dados["evidencias"]` (dict com `fatos`) ou a própria lista de fatos."""
    if isinstance(evidencias, dict):
        return evidencias.get("fatos") or []
    return evidencias or []


def _indice_fatos(evidencias: dict | list | None) -> dict[tuple[str, str], list[dict]]:
    """Fatos agrupados por (item, serviço); serviço vazio é o próprio item."""
    indice: dict[tuple[str, str], list[dict]] = {}
    for f in _lista_de_fatos(evidencias):
        chave = (_item_do_codigo(f["codigo"]), f.get("servico") or "")
        indice.setdefault(chave, []).append(f)
    return indice


def _numero(valor: float, unidade: str | None) -> str:
    """Contagem (`un`) sem casas decimais; o resto com duas, em pt-BR."""
    return br(valor, 0 if unidade == "un" else 2)


def _quantidades_codificadas(medidas: list[dict]) -> tuple[list[str], list[str], int]:
    """(textos, códigos, nº de elementos) das quantidades da EAP codificada com elemento medido. Soma só dentro da
    mesma (grandeza, unidade): unidades diferentes ficam em linhas separadas."""
    somas: dict[tuple[str, str], float] = {}
    codigos, n_elementos = [], 0
    for q in medidas:
        if not q.get("evidencias") or q["n_elementos"] <= q.get("sem_valor", 0):
            continue
        chave = (q["grandeza"], q["unidade"])
        somas[chave] = somas.get(chave, 0.0) + float(q["quantidade"])
        codigos.append(q["codigo"])
        n_elementos += len(q["evidencias"])
    textos = [
        f"{_numero(v, un)} {un}".rstrip() + (f" ({gr})" if gr != "quantidade" else "")
        for (gr, un), v in somas.items()
    ]
    return textos, codigos, n_elementos


def _quantidades_dos_fatos(fatos: list[dict]) -> tuple[list[str], list[str], int]:
    """(textos, códigos, nº de afirmações) dos fatos com valor; cada valor fica na sua linha, com o status do fato."""
    textos, codigos, n_afirmacoes = [], [], 0
    for f in fatos:
        if f.get("valor") is None:
            continue
        texto = f"{_numero(f['valor'], f['unidade'])} {f['unidade']} · {f['status']}".replace(
            "  ", " "
        )
        if texto not in textos:
            textos.append(texto)
        codigos.append(f["codigo"])
        n_afirmacoes += len(f.get("afirmacoes") or [])
    return textos, codigos, n_afirmacoes


def _dados_da_folha(
    folha: dict,
    quantidades: dict[str, list[dict]],
    fatos: dict[tuple[str, str], list[dict]],
) -> dict:
    """Quantidades (EAP codificada só no apontamento sem serviço, fatos em ambos), códigos, nº de evidências e nº de
    fatos sem valor dos códigos apontados."""
    medidas, achados = [], []
    for alvo in folha["aponta"]:
        servico = alvo.get("servico") or ""
        if not servico:
            medidas += quantidades.get(alvo["item"], [])
        achados += fatos.get((alvo["item"], servico), [])
    t_cod, c_cod, n_cod = _quantidades_codificadas(medidas)
    t_fat, c_fat, n_fat = _quantidades_dos_fatos(achados)
    return {
        "quantidades_txt": t_cod + t_fat,
        "codigos": sorted(set(c_cod + c_fat)),
        "n_evidencias": n_cod + n_fat,
        "so_mencao": bool(medidas or achados) and not (t_cod or t_fat),
    }


def _situacao(folha: dict, achados: dict, declaracao: dict | None) -> str:
    """Situação da folha, nesta ordem: declarada não se aplica; sem item codificado; preenchida; só menção; a preencher."""
    if declaracao:
        return NAO_SE_APLICA
    if not folha["aponta"]:
        return SEM_ITEM
    if achados["quantidades_txt"]:
        return PREENCHIDA
    return SO_MENCAO if achados["so_mencao"] else A_PREENCHER


def _folha_preenchida(
    folha: dict, quantidades: dict, fatos: dict, declaracoes: dict
) -> dict:
    """Uma folha com a situação, o selo de destaque e os textos já formatados."""
    declaracao = declaracoes.get(folha["id"])
    achados = _dados_da_folha(folha, quantidades, fatos)
    situacao = _situacao(folha, achados, declaracao)
    return {
        "id": folha["id"],
        "nome": folha["nome"],
        "situacao": situacao,
        "obrigatoria": folha["obrigatoria"],
        "destaque": bool(folha["obrigatoria"] and situacao == A_PREENCHER),
        "escopo": folha.get("escopo", "ambos"),
        "aponta_txt": [
            alvo["item"]
            + (f" · {SERVICOS[alvo['servico']]}" if alvo.get("servico") else "")
            for alvo in folha["aponta"]
        ],
        "quantidades_txt": achados["quantidades_txt"],
        "codigos": achados["codigos"],
        "n_evidencias": achados["n_evidencias"],
        "observacao": folha.get("observacao", ""),
        "justificativa": (declaracao or {}).get("justificativa", ""),
        "autor": (declaracao or {}).get("autor", ""),
    }


def resumir(folhas: list[dict]) -> dict:
    """Contagem por situação e % preenchido = preenchidas / (folhas − não se aplica), em Python."""
    contagem = {s: sum(f["situacao"] == s for f in folhas) for s in SITUACOES}
    aplicaveis = len(folhas) - contagem[NAO_SE_APLICA]
    pct = round(100.0 * contagem[PREENCHIDA] / aplicaveis, 1) if aplicaveis else None
    return {
        "n_folhas": len(folhas),
        "n_aplicaveis": aplicaveis,
        "n_preenchidas": contagem[PREENCHIDA],
        "por_situacao": [{"situacao": s, "n": n} for s, n in contagem.items()],
        "obrigatorias_a_preencher": sum(f["destaque"] for f in folhas),
        "pct": pct,
        "pct_txt": f"{br(pct, 1)} %" if pct is not None else "—",
    }


def preencher(
    tipo: str,
    eap_codificada: dict | None,
    evidencias: dict | list | None = None,
    declaracoes: list[dict] | None = None,
) -> dict:
    """Preenche o esqueleto do `tipo` com a EAP codificada (`dados["eap"]`, quantidades com elementos) e os fatos
    (`dados["evidencias"]`). `declaracoes` = `eap_padrao.nao_se_aplica` do obra.json ({id, justificativa, autor}); sem
    justificativa é erro. Devolve {tipo, nome, prefixo, etapas: [{id, nome, folhas, resumo}], resumo}."""
    if tipo not in TIPOS:
        raise ValueError(
            f"tipo de EAP padrão desconhecido: '{tipo}'; use {list(TIPOS)}"
        )
    mapa = _mapa_declaracoes(declaracoes)
    quantidades, fatos = _indice_quantidades(eap_codificada), _indice_fatos(evidencias)
    etapas, todas = [], []
    for etapa in TIPOS[tipo]["etapas"]:
        folhas = [
            _folha_preenchida(f, quantidades, fatos, mapa) for f in etapa["folhas"]
        ]
        etapas.append(
            {
                "id": etapa["id"],
                "nome": etapa["nome"],
                "folhas": folhas,
                "resumo": resumir(folhas),
            }
        )
        todas += folhas
    meta = TIPOS[tipo]
    return {
        "tipo": tipo,
        "nome": meta["nome"],
        "prefixo": meta["prefixo"],
        "etapas": etapas,
        "resumo": resumir(todas),
    }


def montar(dados: dict, cfg: dict, out: Path | None = None) -> dict:
    """`dados["eap_padrao"]`: um bloco por tipo da obra (`tipo_da_obra`), tudo em texto pt-BR, mais o aviso de premissa
    e os itens fora do padrão. Grava `eap_padrao.json` em `out`. Levanta ValueError se o padrão ou as declarações do
    obra.json forem inválidos (o build trata como etapa pulada)."""
    erros, avisos = validar()
    if erros:
        raise ValueError("eap_padrao.json inválido: " + "; ".join(erros))
    declaracoes = (cfg.get("eap_padrao") or {}).get("nao_se_aplica")
    tipos = tipo_da_obra(cfg)
    resultado = {
        "fonte": PADRAO["metadata"]["fonte"],
        "estado": PADRAO["metadata"]["estado"],
        "aviso": AVISO_PREMISSA,
        "regra_tipo": REGRA_TIPO,
        "tipos": [
            preencher(t, dados.get("eap"), dados.get("evidencias"), declaracoes)
            for t in tipos
        ],
        "fora_do_padrao": [i for i in itens_fora_do_padrao() if i["tipo"] in tipos],
        "avisos": avisos,
    }
    if out is not None:
        caminho = Path(out) / "eap_padrao.json"
        caminho.write_text(
            json.dumps(resultado, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return resultado


def metadados() -> dict:
    """Rastreabilidade do método e das premissas declaradas (regra 9 do estilo)."""
    return {
        "modulo": "eap_padrao",
        "descricao": "EAP padrão por tipo de obra (etapas de execução): vista que aponta para a EAP codificada e diz o "
        "que já foi preenchido, o que é só menção, o que falta e o que não se aplica",
        "funcoes": [
            "validar",
            "itens_fora_do_padrao",
            "tipo_da_obra",
            "preencher",
            "resumir",
            "montar",
            "metadados",
        ],
        "situacoes": list(SITUACOES),
        "regra_tipo": REGRA_TIPO,
        "premissas": [
            {
                "aplicacao": {"preencher": ["eap_padrao.json"]},
                "fonte": PADRAO["metadata"]["fonte"],
                "estado": PADRAO["metadata"]["estado"],
            }
        ],
    }
