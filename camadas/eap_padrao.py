"""EAP padrão por tipo de obra: esqueleto por etapa de execução, a preencher a cada obra.

A EAP codificada (`camadas.eap`) é por disciplina (GEO/CIV/HID/ELE → pacote → item) e continua sendo a linha mestra
técnica. O padrão de `conceitos/eap_padrao.json` é uma VISTA por etapa de execução (ordem de obra) que aponta para os
códigos da EAP codificada: não cria quantificação nova. Cada folha diz se a obra já a preencheu:

    preenchida          medição da EAP codificada (pranchas) ou afirmação de documento/decisão nos códigos apontados
    preenchida (manual) folha sem item codificado, preenchida pelo obra.json com documento citado
    calculada           só serviço associado (fórmula): não é documento nem medição; fora do % preenchido
    só menção           só fato sem valor, quantidade sem elemento medido ou unidade não atribuível
    a preencher         nada nos códigos apontados (se `obrigatoria`, vem em destaque)
    sem item codificado folha sem `aponta` e sem preenchimento manual
    não se aplica       declarada em obra.json → eap_padrao.nao_se_aplica [{id, justificativa, autor}]
    fora do escopo      folha de esgoto em obra só de água (ou o contrário); fora do denominador
    conflito            declarada não se aplica, mas há quantidade; fica no denominador, em destaque

Numeração e nomes das etapas são premissa a conferir com o MOS Sanepar (que não está no repositório).
Determinístico: o Python soma, conta e formata (pt-BR); o HTML só apresenta `dados["eap_padrao"]`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import eap
from .eap_html import br
from .pdf_cad import CONCEITOS

PADRAO = json.loads((CONCEITOS / "eap_padrao.json").read_text(encoding="utf-8"))
TIPOS = PADRAO["tipos"]
OBRA_DO_TIPO = {"obra_localizada": "localizada", "obra_linear": "linear"}
OBRA_DA_UNIDADE = {k: u["obra"] for k, u in eap.UNIDADES["unidades"].items()}
ESCOPOS = ("agua", "esgoto", "ambos")
SERVICOS = {
    json.loads(linha)["id"]: json.loads(linha)["nome"]
    for linha in (CONCEITOS / "servicos.jsonl").read_text(encoding="utf-8").splitlines()
    if linha.strip()
}

PREENCHIDA = "preenchida"
MANUAL = "preenchida (manual)"
CALCULADA = "calculada"
SO_MENCAO = "só menção"
A_PREENCHER = "a preencher"
SEM_ITEM = "sem item codificado"
NAO_SE_APLICA = "não se aplica"
FORA_ESCOPO = "fora do escopo"
CONFLITO = "conflito: declarada não se aplica, mas há quantidade"
SITUACOES = (
    PREENCHIDA,
    MANUAL,
    CALCULADA,
    SO_MENCAO,
    A_PREENCHER,
    SEM_ITEM,
    NAO_SE_APLICA,
    FORA_ESCOPO,
    CONFLITO,
)
CLASSES = dict(
    zip(
        SITUACOES,
        (
            "preenchida",
            "manual",
            "calculada",
            "so-mencao",
            "a-preencher",
            "sem-item",
            "nao-se-aplica",
            "fora-do-escopo",
            "conflito",
        ),
    )
)
"""Classe CSS de cada situação, calculada aqui para o HTML não derivar nada."""
COM_DADO_REAL = (PREENCHIDA, MANUAL, CALCULADA)

REGRA_TIPO = (
    "Tipo da obra: `eap_padrao.tipo` do obra.json (texto ou lista) manda. Sem ele, pelas unidades de "
    "unidades_construtivas.json: prancha de unidade linear (nome do PDF casa com `linear` de tipos_prancha.json, ou `eap` "
    "declarado) ou `valas` → linear; `estacas`, `elementos_declarados`, `escavacao` ou prancha de unidade localizada → "
    "localizada; os dois sinais → obra mista (os dois tipos); nenhum → localizada. `obras_lineares` dentro de unidade "
    "localizada (tubos internos da ETA) não é sinal de obra linear."
)
AVISO_PREMISSA = (
    "Esqueleto em estado de premissa: a numeração e os nomes das etapas são a conferir com o MOS Sanepar, "
    "que não está no repositório."
)
CAMPOS_DECLARACAO = "{id, justificativa, autor}"
CAMPOS_MANUAL = "{id, quantidade, unidade, documento, autor}"


# ----------------------------------------------------------------------------------------------------------------
# validação do padrão
# ----------------------------------------------------------------------------------------------------------------
def _folhas_do_tipo(tipo: str) -> list[dict]:
    """Folhas do tipo, na ordem de obra, cada uma com o id e o nome da etapa."""
    return [
        {**folha, "etapa_id": etapa["id"], "etapa_nome": etapa["nome"]}
        for etapa in TIPOS[tipo]["etapas"]
        for folha in etapa["folhas"]
    ]


def _problemas_do_alvo(folha: dict, alvo: dict, tipo: str, itens: dict) -> list[str]:
    """Erros de um apontamento: item inexistente ou de outro tipo de obra ou de outro escopo, serviço desconhecido ou
    não admitido pelo item."""
    item = itens.get(alvo["item"])
    if item is None:
        return [f"{folha['id']}: item '{alvo['item']}' fora de eap_geral"]
    problemas = []
    if OBRA_DO_TIPO[tipo] not in item["obra"]:
        problemas.append(f"{folha['id']}: item '{alvo['item']}' não vale para {tipo}")
    escopo = folha.get("escopo", "ambos")
    if escopo != "ambos" and escopo not in item["escopo"]:
        problemas.append(
            f"{folha['id']}: escopo '{escopo}' fora do escopo do item '{alvo['item']}'"
        )
    servico = alvo.get("servico")
    if servico and servico not in SERVICOS:
        problemas.append(f"{folha['id']}: serviço '{servico}' fora de servicos.jsonl")
    elif servico and servico not in item["servicos"]:
        problemas.append(
            f"{folha['id']}: serviço '{servico}' não é admitido no item '{alvo['item']}'"
        )
    return problemas


def _problemas_da_folha(tipo: str, folha: dict, itens: dict) -> list[str]:
    """Erros de uma folha: apontamentos, `obrigatoria` ausente ou não booleana, escopo inválido e folha sem item e sem
    observação."""
    problemas = []
    for alvo in folha["aponta"]:
        problemas += _problemas_do_alvo(folha, alvo, tipo, itens)
    if not isinstance(folha.get("obrigatoria"), bool):
        problemas.append(f"{folha['id']}: `obrigatoria` ausente ou não booleana")
    if not folha["aponta"] and not folha.get("observacao"):
        problemas.append(
            f"{folha['id']}: folha sem item codificado precisa de `observacao`"
        )
    if folha.get("escopo", "ambos") not in ESCOPOS:
        problemas.append(f"{folha['id']}: escopo '{folha['escopo']}' desconhecido")
    return problemas


def _servicos_fora_do_padrao(tipo: str, itens: dict) -> list[str]:
    """Pares (item, serviço) admitidos pelo item que nenhuma folha do tipo cita. Item que alguma folha aponta sem
    serviço já cobre todos os serviços dele e não gera aviso."""
    pares = {
        (a["item"], a.get("servico", ""))
        for f in _folhas_do_tipo(tipo)
        for a in f["aponta"]
    }
    cobertos = {item for item, servico in pares if not servico}
    return [
        f"{tipo}: serviço fora do padrão: {codigo} · {servico}"
        for codigo, item in itens.items()
        if OBRA_DO_TIPO[tipo] in item["obra"] and codigo not in cobertos
        for servico in item["servicos"]
        if (codigo, servico) not in pares
    ]


def validar() -> tuple[list[str], list[str]]:
    """(erros, avisos) do padrão. Erro: id repetido ou fora do prefixo, item ou serviço inexistente, serviço não
    admitido pelo item, item de outro tipo de obra, escopo da folha fora do escopo do item, `obrigatoria` ausente.
    Aviso (não erro): item de `eap_geral` do tipo de obra que nenhuma folha cita ("item fora do padrão") e par
    (item, serviço) admitido que nenhuma folha cobre ("serviço fora do padrão")."""
    itens, erros, avisos, ids = eap.itens(), [], [], []
    for tipo, meta in TIPOS.items():
        folhas = _folhas_do_tipo(tipo)
        ids += [f["id"] for f in folhas] + [e["id"] for e in meta["etapas"]]
        erros += [
            f"{f['id']}: id fora do prefixo {meta['prefixo']}"
            for f in folhas
            if not f["id"].startswith(
                f"{meta['prefixo']}.{f['etapa_id'].split('.')[1]}."
            )
        ]
        for folha in folhas:
            erros += _problemas_da_folha(tipo, folha, itens)
        avisos += [
            f"{tipo}: item fora do padrão: {i['codigo']}"
            for i in itens_fora_do_padrao(tipo)
        ]
        avisos += _servicos_fora_do_padrao(tipo, itens)
    erros += [f"id repetido: {i}" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return erros, avisos


def itens_fora_do_padrao(tipo: str | None = None) -> list[dict]:
    """[{tipo, codigo, nome}] dos itens de eap_geral do tipo de obra que nenhuma folha do tipo cita."""
    itens = eap.itens()
    saida = []
    for t in [tipo] if tipo else TIPOS:
        citados = {a["item"] for f in _folhas_do_tipo(t) for a in f["aponta"]}
        saida += [
            {"tipo": t, "codigo": codigo, "nome": item["nome"]}
            for codigo, item in itens.items()
            if OBRA_DO_TIPO[t] in item["obra"] and codigo not in citados
        ]
    return saida


# ----------------------------------------------------------------------------------------------------------------
# tipo e escopo da obra
# ----------------------------------------------------------------------------------------------------------------
def _obra_da_prancha(prancha: dict) -> str | None:
    """Tipo de obra da unidade da prancha: `eap` declarado no obra.json ou o nome do PDF (tipos_prancha.json)."""
    referencia = prancha.get("eap")
    unidade = (
        referencia.split(".")[0] if referencia else eap._unidade_da_prancha(prancha)
    )
    return OBRA_DA_UNIDADE.get(unidade.lower())


def _obra_da_referencia(texto) -> str | None:
    """Tipo de obra da unidade citada num texto ('UNIDADE 1', 'U1.LINEARES'); None se não cita unidade conhecida."""
    achado = re.search(r"(\d+)", str(texto or ""))
    return OBRA_DA_UNIDADE.get(f"u{int(achado.group(1))}") if achado else None


def _obras_lineares_sao_lineares(cfg: dict) -> bool:
    """`obras_lineares` só é sinal de obra linear se a unidade dela não for localizada (a aba Obras Lineares da
    planilha também traz os tubos internos da ETA, que são da unidade localizada)."""
    lineares = cfg.get("obras_lineares")
    if not lineares:
        return False
    referencia = (
        (lineares.get("eap") or lineares.get("unidade"))
        if isinstance(lineares, dict)
        else None
    )
    return _obra_da_referencia(referencia) != "localizada"


def _padrao_do_cfg(cfg: dict) -> dict:
    """Bloco `eap_padrao` do obra.json; qualquer coisa que não seja objeto vale como ausente."""
    bloco = cfg.get("eap_padrao")
    return bloco if isinstance(bloco, dict) else {}


def _tipos_declarados(declarado, avisos: list[str] | None) -> list[str] | None:
    """Tipos de `eap_padrao.tipo` (texto ou lista). Desconhecido: ValueError, ou aviso e dedução se há `avisos`."""
    lista = [declarado] if isinstance(declarado, str) else list(declarado)
    desconhecidos = [t for t in lista if t not in TIPOS]
    if not desconhecidos:
        return [t for t in TIPOS if t in lista]
    mensagem = f"eap_padrao.tipo desconhecido: {desconhecidos}; use {list(TIPOS)}"
    if avisos is None:
        raise ValueError(mensagem)
    avisos.append(mensagem + " (tipo deduzido)")
    return None


def tipo_da_obra(cfg: dict, avisos: list[str] | None = None) -> list[str]:
    """Tipos de EAP padrão da obra, na ordem do arquivo. Regra (`REGRA_TIPO`): `eap_padrao.tipo` do obra.json manda
    (lista vazia ou desconhecida: aviso em `avisos` e dedução); senão, pelas unidades: linear = prancha de unidade
    linear, `valas` ou `obras_lineares` fora de unidade localizada; localizada = `estacas`, `elementos_declarados`,
    `escavacao` ou prancha de unidade localizada; só linear → obra_linear; os dois → obra mista; nenhum ou só
    localizada → obra_localizada."""
    padrao = _padrao_do_cfg(cfg)
    declarado = padrao.get("tipo")
    if declarado:
        tipos = _tipos_declarados(declarado, avisos)
        if tipos:
            return tipos
    elif "tipo" in padrao and avisos is not None:
        avisos.append("eap_padrao.tipo vazio: tipo deduzido do obra.json")
    obras = {_obra_da_prancha(p) for p in cfg.get("pranchas") or []}
    linear = (
        "linear" in obras or bool(cfg.get("valas")) or _obras_lineares_sao_lineares(cfg)
    )
    localizada = "localizada" in obras or any(
        cfg.get(k) for k in ("estacas", "elementos_declarados", "escavacao")
    )
    if linear and not localizada:
        return ["obra_linear"]
    return ["obra_localizada", "obra_linear"] if linear else ["obra_localizada"]


def escopos_do_tipo(
    tipo: str, cfg: dict, avisos: list[str] | None = None
) -> set[str] | None:
    """Escopos (agua, esgoto) em que a obra desse tipo atua: `eap_padrao.escopo` do obra.json ou o escopo das
    unidades do tipo em unidades_construtivas.json. None = qualquer (unidade sem escopo)."""
    declarado = _padrao_do_cfg(cfg).get("escopo")
    if declarado:
        lista = {declarado} if isinstance(declarado, str) else set(declarado)
        if lista <= set(ESCOPOS[:2]):
            return lista
        if avisos is not None:
            avisos.append(
                f"eap_padrao.escopo inválido: {declarado}; use agua e/ou esgoto (escopo das unidades)"
            )
    escopos = {
        u.get("escopo")
        for u in eap.UNIDADES["unidades"].values()
        if u["obra"] == OBRA_DO_TIPO[tipo]
    }
    return None if None in escopos or not escopos else escopos


# ----------------------------------------------------------------------------------------------------------------
# declarações do obra.json (não se aplica, preenchimento manual)
# ----------------------------------------------------------------------------------------------------------------
def _problema_do_registro(
    d, rotulo: str, campos: str, vistos: set, conferir
) -> str | None:
    """Problema de um registro do obra.json: não é objeto, folha inexistente, repetido ou campo inválido."""
    if not isinstance(d, dict):
        return f"{rotulo} deve ser um objeto {campos}; veio {type(d).__name__}"
    conhecidas = {f["id"]: f for t in TIPOS for f in _folhas_do_tipo(t)}
    if not isinstance(d.get("id"), str) or d["id"] not in conhecidas:
        return f"{rotulo}: folha '{d.get('id')}' não existe no padrão"
    if d["id"] in vistos:
        return f"{rotulo}: declaração duplicada para '{d['id']}'"
    return conferir(d, conhecidas[d["id"]], rotulo)


def _separar(lista, chave: str, campos: str, conferir) -> tuple[list[dict], list[str]]:
    """(registros válidos, problemas) de uma lista do obra.json. Lista malformada ou registro inválido vira problema
    com mensagem clara; os registros válidos seguem."""
    if lista is None:
        return [], []
    if not isinstance(lista, list):
        return [], [
            f"eap_padrao.{chave} deve ser uma lista de objetos {campos}; veio {type(lista).__name__}"
        ]
    validos, problemas, vistos = [], [], set()
    for k, d in enumerate(lista):
        problema = _problema_do_registro(
            d, f"eap_padrao.{chave}[{k}]", campos, vistos, conferir
        )
        if problema:
            problemas.append(problema)
        else:
            vistos.add(d["id"])
            validos.append(d)
    return validos, problemas


def _conferir_declaracao(d: dict, folha: dict, rotulo: str) -> str | None:
    """Justificativa é obrigatória para declarar não se aplica."""
    if not str(d.get("justificativa") or "").strip():
        return f"{rotulo}: '{d['id']}' sem justificativa (obrigatória para declarar não se aplica)"
    return None


def _conferir_manual(d: dict, folha: dict, rotulo: str) -> str | None:
    """Preenchimento manual: só folha sem item codificado, com quantidade positiva, unidade e documento."""
    if folha["aponta"]:
        return f"{rotulo}: '{d['id']}' tem item codificado; o preenchimento manual é só para folha sem item"
    quantidade = d.get("quantidade")
    if (
        isinstance(quantidade, bool)
        or not isinstance(quantidade, (int, float))
        or not quantidade > 0
    ):
        return f"{rotulo}: '{d['id']}' precisa de `quantidade` numérica maior que zero"
    for campo in ("unidade", "documento"):
        if not str(d.get(campo) or "").strip():
            return f"{rotulo}: '{d['id']}' sem `{campo}` (documento de origem é obrigatório)"
    return None


def separar_declaracoes(lista) -> tuple[list[dict], list[str]]:
    """(válidas, problemas) de `eap_padrao.nao_se_aplica`."""
    return _separar(lista, "nao_se_aplica", CAMPOS_DECLARACAO, _conferir_declaracao)


def separar_manuais(lista) -> tuple[list[dict], list[str]]:
    """(válidos, problemas) de `eap_padrao.preenchimento_manual`."""
    return _separar(lista, "preenchimento_manual", CAMPOS_MANUAL, _conferir_manual)


def _so_dos_tipos(
    registros: list[dict], tipos: list[str], chave: str, avisos: list[str]
) -> list[dict]:
    """Registros das folhas dos tipos da obra; os de outro tipo viram aviso (não ficam em silêncio)."""
    ids = {f["id"] for t in tipos for f in _folhas_do_tipo(t)}
    avisos += [
        f"eap_padrao.{chave}: '{r['id']}' ignorada, a obra não tem o tipo dessa folha ({', '.join(tipos)})"
        for r in registros
        if r["id"] not in ids
    ]
    return [r for r in registros if r["id"] in ids]


# ----------------------------------------------------------------------------------------------------------------
# preenchimento
# ----------------------------------------------------------------------------------------------------------------
def _item_do_codigo(codigo: str) -> str:
    """'U1.ACT600.GEO.FUN.EST' → 'GEO.FUN.EST' (os dois primeiros segmentos são unidade e sistema)."""
    return ".".join(str(codigo).split(".")[2:])


def _indice_quantidades(eap_codificada: dict | None) -> dict[str, list[dict]]:
    """Quantidades da EAP codificada agrupadas pelo item (sem unidade e sistema)."""
    indice: dict[str, list[dict]] = {}
    for q in (eap_codificada or {}).get("quantidades") or []:
        indice.setdefault(_item_do_codigo(q["codigo"]), []).append(q)
    return indice


def _indice_fatos(evidencias: dict | list | None) -> dict[str, list[dict]]:
    """Fatos agrupados pelo item; aceita `dados["evidencias"]` (dict com `fatos`) ou a própria lista de fatos."""
    lista = evidencias.get("fatos") if isinstance(evidencias, dict) else evidencias
    indice: dict[str, list[dict]] = {}
    for f in lista or []:
        indice.setdefault(_item_do_codigo(f["codigo"]), []).append(f)
    return indice


def _numero(valor: float, unidade: str | None) -> str:
    """Contagem (`un`) sem casas decimais; o resto com duas, em pt-BR."""
    return br(valor, 0 if unidade == "un" else 2)


def _separar_por_unidade(registros: list[dict], tipo: str) -> tuple[list[dict], int]:
    """(registros da unidade do tipo de obra, nº de unidade não atribuível). O código com `*` ou unidade desconhecida
    não é atribuível a nenhum tipo e não soma; o de unidade do outro tipo de obra fica de fora."""
    do_tipo, indefinidas = [], 0
    for r in registros:
        obra = OBRA_DA_UNIDADE.get(str(r["codigo"]).split(".")[0].lower())
        if obra is None:
            indefinidas += 1
        elif obra == OBRA_DO_TIPO[tipo]:
            do_tipo.append(r)
    return do_tipo, indefinidas


def _categoria_do_fato(fato: dict) -> str:
    """PREENCHIDA (medição do projeto, documento ou decisão), CALCULADA (todas as afirmações são serviço associado,
    isto é, fórmula) ou SO_MENCAO (fato sem valor: menção ou conflito)."""
    if fato.get("valor") is None:
        return SO_MENCAO
    afirmacoes = fato.get("afirmacoes") or []
    so_formula = bool(afirmacoes) and all(
        a.get("tipo") == "associado" for a in afirmacoes
    )
    return CALCULADA if so_formula and not fato.get("decisoes") else PREENCHIDA


def _texto_do_fato(fato: dict, categoria: str) -> str:
    """'Fornecimento 12 un · convergente [U1.*.HID.EQP.EQU]': um texto por fato, com o serviço e o código."""
    valor = f"{_numero(fato['valor'], fato['unidade'])} {fato['unidade']}".rstrip()
    servico = SERVICOS.get(fato.get("servico"), fato.get("servico") or "")
    rotulo = "calculada (fórmula)" if categoria == CALCULADA else fato["status"]
    return f"{servico + ' ' if servico else ''}{valor} · {rotulo} [{fato['codigo']}]"


def _quantidades_codificadas(
    medidas: list[dict],
) -> tuple[list[str], list[str], int, int]:
    """(textos, códigos, nº de elementos, nº de elementos sem valor) das quantidades da EAP codificada com elemento
    medido. Soma só dentro da mesma (grandeza, unidade): unidades diferentes ficam em linhas separadas."""
    somas: dict[tuple[str, str], float] = {}
    codigos, n_elementos, sem_valor = [], 0, 0
    for q in medidas:
        if not q.get("evidencias") or q["n_elementos"] <= q.get("sem_valor", 0):
            continue
        chave = (q["grandeza"], q["unidade"])
        somas[chave] = somas.get(chave, 0.0) + float(q["quantidade"])
        codigos.append(q["codigo"])
        n_elementos += len(q["evidencias"])
        sem_valor += q.get("sem_valor", 0)
    textos = [
        f"{_numero(v, un)} {un}".rstrip() + (f" ({gr})" if gr != "quantidade" else "")
        for (gr, un), v in somas.items()
    ]
    return textos, codigos, n_elementos, sem_valor


def _candidatos(
    folha: dict, tipo: str, quantidades: dict, fatos: dict
) -> tuple[list[dict], list[dict], int]:
    """(medidas, fatos, nº não atribuíveis) dos códigos apontados, só da unidade do tipo de obra. Apontamento sem
    serviço lê a quantidade do item e os fatos de qualquer serviço dele; com serviço, só os fatos daquele serviço."""
    medidas, achados = [], []
    for alvo in folha["aponta"]:
        item, servico = alvo["item"], alvo.get("servico")
        if not servico:
            medidas += quantidades.get(item, [])
        achados += [
            f for f in fatos.get(item, []) if not servico or f.get("servico") == servico
        ]
    medidas, indef_m = _separar_por_unidade(medidas, tipo)
    achados, indef_f = _separar_por_unidade(achados, tipo)
    return medidas, achados, indef_m + indef_f


def _classe_dos_dados(
    tem_medida: bool, por_categoria: dict, medidas: list, indefinidas: int
) -> tuple[str, str]:
    """(situação pelos dados, motivo) na ordem: preenchida, calculada, só menção, a preencher."""
    if tem_medida or por_categoria[PREENCHIDA]:
        return PREENCHIDA, ""
    if por_categoria[CALCULADA]:
        return (
            CALCULADA,
            "só serviço associado (fórmula): sem documento nem medição do projeto",
        )
    if por_categoria[SO_MENCAO]:
        conflito = any(f["status"] == "conflito" for f in por_categoria[SO_MENCAO])
        return (
            SO_MENCAO,
            "fato em conflito, sem valor" if conflito else "citado sem valor",
        )
    if medidas:
        return SO_MENCAO, "elemento medido sem valor"
    if indefinidas:
        return SO_MENCAO, "unidade não atribuível"
    return A_PREENCHER, ""


def _dados_manuais(manual: dict) -> dict:
    """Dados de uma folha sem item preenchida pelo obra.json: a quantidade e o documento citado."""
    autor = f" ({manual['autor']})" if manual.get("autor") else ""
    texto = f"{_numero(manual['quantidade'], manual['unidade'])} {manual['unidade']} · manual: {manual['documento']}{autor}"
    return {
        "classe": MANUAL,
        "motivo": "",
        "quantidades_txt": [texto],
        "codigos": [],
        "n_evidencias": 1,
        "parcial": 0,
    }


def _dados_da_folha(
    folha: dict, tipo: str, quantidades: dict, fatos: dict, manual: dict | None
) -> dict:
    """Situação pelos dados, motivo, quantidades (EAP codificada e um texto por fato), códigos, nº de evidências e nº de
    elementos sem valor, dos códigos apontados."""
    if manual:
        return _dados_manuais(manual)
    if not folha["aponta"]:
        return {
            "classe": SEM_ITEM,
            "motivo": "",
            "quantidades_txt": [],
            "codigos": [],
            "n_evidencias": 0,
            "parcial": 0,
        }
    medidas, achados, indefinidas = _candidatos(folha, tipo, quantidades, fatos)
    t_cod, c_cod, n_cod, parcial = _quantidades_codificadas(medidas)
    por_categoria = {c: [] for c in (PREENCHIDA, CALCULADA, SO_MENCAO)}
    for f in achados:
        por_categoria[_categoria_do_fato(f)].append(f)
    valoradas = [(f, c) for c in (PREENCHIDA, CALCULADA) for f in por_categoria[c]]
    classe, motivo = _classe_dos_dados(bool(t_cod), por_categoria, medidas, indefinidas)
    return {
        "classe": classe,
        "motivo": motivo,
        "quantidades_txt": t_cod + [_texto_do_fato(f, c) for f, c in valoradas],
        "codigos": sorted(set(c_cod + [f["codigo"] for f, _ in valoradas])),
        "n_evidencias": n_cod
        + sum(len(f.get("afirmacoes") or []) for f, _ in valoradas),
        "parcial": parcial,
    }


def _situacao(folha: dict, dados: dict, declarada: bool, fora_do_escopo: bool) -> str:
    """Situação final: declarada não se aplica (com dado real vira conflito), fora do escopo sem dado real, ou a
    situação pelos dados."""
    real = dados["classe"] in COM_DADO_REAL
    if declarada:
        return CONFLITO if real else NAO_SE_APLICA
    if fora_do_escopo and not real:
        return FORA_ESCOPO
    return dados["classe"]


def _folha_preenchida(folha: dict, tipo: str, indices: tuple, contexto: dict) -> dict:
    """Uma folha com a situação, a classe e o destaque, os textos já formatados e a origem de cada número."""
    declaracao = contexto["declaracoes"].get(folha["id"])
    dados = _dados_da_folha(folha, tipo, *indices, contexto["manuais"].get(folha["id"]))
    escopo = folha.get("escopo", "ambos")
    escopos = contexto["escopos"]
    fora = escopo != "ambos" and escopos is not None and escopo not in escopos
    situacao = _situacao(folha, dados, bool(declaracao), fora)
    parcial = situacao == PREENCHIDA and dados["parcial"]
    return {
        "id": folha["id"],
        "nome": folha["nome"],
        "situacao": situacao,
        "situacao_txt": f"{situacao} (parcial: {dados['parcial']} sem valor)"
        if parcial
        else situacao,
        "classe": CLASSES[situacao],
        "obrigatoria": folha["obrigatoria"],
        "destaque": situacao == CONFLITO
        or (folha["obrigatoria"] and situacao == A_PREENCHER),
        "escopo": escopo,
        "aponta_txt": [
            alvo["item"]
            + (f" · {SERVICOS[alvo['servico']]}" if alvo.get("servico") else "")
            for alvo in folha["aponta"]
        ],
        "quantidades_txt": dados["quantidades_txt"],
        "codigos": dados["codigos"],
        "n_evidencias": dados["n_evidencias"],
        "motivo": dados["motivo"],
        "observacao": folha.get("observacao", ""),
        "justificativa": (declaracao or {}).get("justificativa", ""),
        "autor": (declaracao or {}).get("autor", ""),
    }


def _pct(n: int, denominador: int) -> float | None:
    """Percentual com uma casa; None sem denominador."""
    return round(100.0 * n / denominador, 1) if denominador else None


def _pct_txt(pct: float | None) -> str:
    """'33,3 %' ou '—'."""
    return f"{br(pct, 1)} %" if pct is not None else "—"


def resumir(folhas: list[dict]) -> dict:
    """Contagem por situação e percentuais, em Python. Denominador = folhas − não se aplica − fora do escopo (conflito,
    calculada, só menção, a preencher e sem item ficam nele). % preenchido = (preenchidas + manuais) / denominador;
    % calculada à parte (fórmula não é preenchimento); teto = % se todas as folhas com item fossem preenchidas e as
    sem item ficassem como estão."""
    contagem = {s: sum(f["situacao"] == s for f in folhas) for s in SITUACOES}
    aplicaveis = len(folhas) - contagem[NAO_SE_APLICA] - contagem[FORA_ESCOPO]
    preenchidas = contagem[PREENCHIDA] + contagem[MANUAL]
    pct, pct_calculada = (
        _pct(preenchidas, aplicaveis),
        _pct(contagem[CALCULADA], aplicaveis),
    )
    teto = _pct(aplicaveis - contagem[SEM_ITEM], aplicaveis)
    return {
        "n_folhas": len(folhas),
        "n_aplicaveis": aplicaveis,
        "n_preenchidas": preenchidas,
        "n_calculadas": contagem[CALCULADA],
        "n_sem_item": contagem[SEM_ITEM],
        "por_situacao": [{"situacao": s, "n": n} for s, n in contagem.items()],
        "obrigatorias_a_preencher": sum(
            f["destaque"] and f["situacao"] == A_PREENCHER for f in folhas
        ),
        "conflitos": contagem[CONFLITO],
        "pct": pct,
        "pct_txt": _pct_txt(pct),
        "pct_calculada": pct_calculada,
        "pct_calculada_txt": f"{br(pct_calculada, 1)} % calculada"
        if contagem[CALCULADA]
        else "",
        "teto_pct": teto,
        "teto_txt": f"teto sem preenchimento manual: {_pct_txt(teto)}"
        if contagem[SEM_ITEM]
        else "",
    }


def _levantar(problemas: list[str]) -> None:
    """Modo estrito de `preencher`: o primeiro problema das declarações vira ValueError."""
    if problemas:
        raise ValueError(problemas[0])


def preencher(
    tipo: str,
    eap_codificada: dict | None,
    evidencias: dict | list | None = None,
    declaracoes: list[dict] | None = None,
    escopos: set[str] | None = None,
    manuais: list[dict] | None = None,
) -> dict:
    """Preenche o esqueleto do `tipo` com a EAP codificada (`dados["eap"]`, só unidades do tipo de obra) e os fatos
    (`dados["evidencias"]`). `declaracoes` = `eap_padrao.nao_se_aplica` ({id, justificativa, autor}); `manuais` =
    `eap_padrao.preenchimento_manual` (folha sem item, com documento); `escopos` = escopos da obra (None = todos).
    Registro inválido é ValueError claro (o `montar` converte em aviso). Devolve {tipo, nome, prefixo, etapas:
    [{id, nome, folhas, resumo}], resumo}."""
    if tipo not in TIPOS:
        raise ValueError(
            f"tipo de EAP padrão desconhecido: '{tipo}'; use {list(TIPOS)}"
        )
    validas, problemas = separar_declaracoes(declaracoes)
    _levantar(problemas)
    validos, problemas = separar_manuais(manuais)
    _levantar(problemas)
    contexto = {
        "declaracoes": {d["id"]: d for d in validas},
        "manuais": {m["id"]: m for m in validos},
        "escopos": escopos,
    }
    indices = (_indice_quantidades(eap_codificada), _indice_fatos(evidencias))
    etapas, todas = [], []
    for etapa in TIPOS[tipo]["etapas"]:
        folhas = [
            _folha_preenchida(f, tipo, indices, contexto) for f in etapa["folhas"]
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


def _configuracao(
    cfg: dict, avisos: list[str]
) -> tuple[list[str], list[dict], list[dict]]:
    """(tipos, declarações, manuais) do obra.json. Bloco malformado, registro inválido e registro de folha de tipo que a
    obra não tem viram aviso; o resto segue."""
    if cfg.get("eap_padrao") is not None and not isinstance(cfg["eap_padrao"], dict):
        avisos.append(
            f"eap_padrao do obra.json deve ser um objeto; veio {type(cfg['eap_padrao']).__name__}"
        )
    padrao = _padrao_do_cfg(cfg)
    tipos = tipo_da_obra(cfg, avisos)
    declaracoes, p1 = separar_declaracoes(padrao.get("nao_se_aplica"))
    manuais, p2 = separar_manuais(padrao.get("preenchimento_manual"))
    avisos += p1 + p2
    return (
        tipos,
        _so_dos_tipos(declaracoes, tipos, "nao_se_aplica", avisos),
        _so_dos_tipos(manuais, tipos, "preenchimento_manual", avisos),
    )


def montar(dados: dict, cfg: dict, out: Path | None = None) -> dict:
    """`dados["eap_padrao"]`: um bloco por tipo da obra (`tipo_da_obra`), tudo em texto pt-BR, mais o aviso de premissa,
    os itens fora do padrão e os `avisos` (declaração inválida ou de tipo ausente, tipo vazio, itens e serviços fora do
    padrão). Declaração inválida não derruba a seção: vira aviso e o resto é preenchido. Grava `eap_padrao.json` em
    `out`. Levanta ValueError só se o próprio conceito `eap_padrao.json` for inválido."""
    erros, avisos = validar()
    if erros:
        raise ValueError("eap_padrao.json inválido: " + "; ".join(erros))
    tipos, declaracoes, manuais = _configuracao(cfg, avisos)
    resultado = {
        "fonte": PADRAO["metadata"]["fonte"],
        "estado": PADRAO["metadata"]["estado"],
        "aviso": AVISO_PREMISSA,
        "regra_tipo": REGRA_TIPO,
        "tipos": [
            preencher(
                t,
                dados.get("eap"),
                dados.get("evidencias"),
                declaracoes,
                escopos_do_tipo(t, cfg, avisos),
                manuais,
            )
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
        "que já foi preenchido, o que foi só calculado, o que é só menção, o que falta e o que não se aplica",
        "funcoes": [
            "validar",
            "itens_fora_do_padrao",
            "tipo_da_obra",
            "escopos_do_tipo",
            "separar_declaracoes",
            "separar_manuais",
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
