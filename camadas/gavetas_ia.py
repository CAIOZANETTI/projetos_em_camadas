"""F5b-E3: a leitura de IA com citação conferida entra nas gavetas ("a IA propõe, o código confere").

    linhas JSONL da IA (`evidencias.ia` do obra.json)  ─►  `evidencias.conferir_arquivo` contra o texto de cada documento
    das gavetas (casamento pelo nome do arquivo = `documento.id` da linha)  ─►  aceita: objeto `leitura_ia` com fatos
    `item_tecnico`, `codigo_evidencia`, `quantidade`, `unidade_medida`, `servico`, `parcela` (natureza `declarado`) e a
    evidência (método `IA`, executor `ia`, `citacao: conferida`, página ou aba e linha, trecho literal)
                                                           ─►  recusada: pendência com o motivo da conferência
                                                           ─►  menção sem número: objeto `mencao_documento` (o laço usa)

O selo `citacao` que vier no arquivo é descartado: o código reconfere toda linha, sempre. Idempotente: os objetos
`ia-*` da rodada anterior (e seus fatos, evidências e pendências) saem antes de os novos entrarem. Sem IA no código: só
confere. Quem decide se a leitura fecha a folha da EAP é `eap_preencher` ("declarada (documento)").
"""

from __future__ import annotations

import json
from pathlib import Path

from . import evidencias

PREFIXO = "ia-"
CLASSE_LEITURA = "leitura_ia"
CLASSE_MENCAO = "mencao_documento"
METODO = "IA"
EXECUTOR = "ia"
NATUREZA = "declarado"
MOTIVO_SEM_PAGINA = "localizador sem página: cite 'p. N' (índice da página no PDF) ou {aba, linha} em planilha"


def sem_ia(base: dict) -> dict:
    """A base sem os objetos, fatos, evidências e pendências de IA da rodada anterior (ids com prefixo `ia-`)."""
    return {
        **base,
        "objetos": [
            o for o in base["objetos"] if not o["objeto_id"].startswith(PREFIXO)
        ],
        "fatos": [f for f in base["fatos"] if not f["objeto_id"].startswith(PREFIXO)],
        "evidencias": [
            e
            for e in base["evidencias"]
            if not e["evidencia_id"].startswith(f"EV-{PREFIXO}")
        ],
        "pendencias": [
            p
            for p in base["pendencias"]
            if not str(p.get("objeto_id", "")).startswith(PREFIXO)
        ],
    }


def _nome_citado(linha) -> str:
    """Nome do arquivo que a linha de IA cita em `documento.id` ('' se a linha não é JSON de objeto)."""
    try:
        ev = linha if isinstance(linha, dict) else json.loads(linha)
    except (ValueError, TypeError):
        return ""
    return evidencias._nome_do_documento(ev) if isinstance(ev, dict) else ""


def _documento_lido(
    candidatos: list[dict], raiz: Path
) -> tuple[list | None, str | None]:
    """(páginas, motivo) do documento das gavetas que casa o nome: ambíguo, ausente do disco ou ilegível dão o motivo."""
    if len(candidatos) != 1:
        return (
            None,
            f"documento ambíguo: {len(candidatos)} arquivos das gavetas com esse nome",
        )
    caminho = Path(raiz) / candidatos[0]["arquivo"]
    if not caminho.is_file():
        return None, f"arquivo ausente: {caminho}"
    try:
        return evidencias.paginas_do_arquivo(caminho), None
    except Exception as erro:  # noqa: BLE001 — documento ilegível não derruba o build: a linha vira pendência
        return None, f"documento ilegível: {type(erro).__name__}: {erro}"[:200]


def _documentos_citados(
    linhas: list, base: dict, raiz: Path
) -> tuple[dict, dict, dict]:
    """({nome: páginas}, {nome: documento das gavetas}, {nome: motivo}) só dos documentos que as linhas citam e que as
    gavetas têm; o que não se lê fica fora das páginas e, com motivo, em `motivos`."""
    por_nome: dict[str, list[dict]] = {}
    for d in base.get("documentos", []):
        por_nome.setdefault(Path(d["arquivo"]).name, []).append(d)
    paginas, documentos, motivos = {}, {}, {}
    for nome in sorted({_nome_citado(x) for x in linhas} & por_nome.keys()):
        lidas, motivo = _documento_lido(por_nome[nome], raiz)
        if lidas is None:
            motivos[nome] = motivo
            continue
        paginas[nome], documentos[nome] = lidas, por_nome[nome][0]
    return paginas, documentos, motivos


def _localizador_das_gavetas(ev: dict, paginas: list) -> dict | None:
    """{pagina} (PDF) ou {aba, linha} (planilha) da evidência aceita, no formato v2 das gavetas; None sem página."""
    pagina, linha, _ = evidencias._localizacao_citada(ev.get("localizador"), paginas)
    if not pagina:
        return None
    if isinstance(paginas[pagina - 1], evidencias.PaginaPlanilha):
        return {"aba": paginas[pagina - 1].aba, "linha": linha} if linha else None
    return {"pagina": pagina}


def _fatos(objeto_id: str, ev: dict) -> list[dict]:
    """Fatos da leitura aceita (natureza `declarado`); sem número (`valor` None) só o item e a menção."""
    evidencia_id = f"EV-{objeto_id}"
    pares = [
        ("item_tecnico", ev["codigo"].split(".", 2)[2]),
        ("codigo_evidencia", ev["codigo"]),
    ]
    if ev.get("valor") is None:
        pares.append(("mencao", ev["trecho"].strip()[:200]))
    else:
        pares += [
            ("quantidade", float(ev["valor"])),
            ("unidade_medida", ev["unidade"]),
            ("parcela", bool(ev["parcela"])),
        ]
        pares += [("servico", ev["servico"])] if ev.get("servico") else []
    return [
        {
            "fato_id": f"{objeto_id}#{p}",
            "objeto_id": objeto_id,
            "propriedade": p,
            "valor": v,
            "natureza": NATUREZA,
            "evidencia_id": evidencia_id,
        }
        for p, v in pares
    ]


def _da_leitura(ev: dict, documento: dict, localizador: dict) -> dict:
    """Objeto, fatos e evidência de uma leitura aceita; sem número o objeto é `mencao_documento` (o laço o usa)."""
    objeto_id = f"{PREFIXO}{ev['id']}"
    classe = CLASSE_MENCAO if ev.get("valor") is None else CLASSE_LEITURA
    return {
        "objetos": [{"objeto_id": objeto_id, "classe": classe}],
        "fatos": _fatos(objeto_id, ev),
        "evidencias": [
            {
                "evidencia_id": f"EV-{objeto_id}",
                "classe": documento["classe"],
                "documento": documento["documento_id"],
                "localizador": localizador,
                "trecho": ev["trecho"],
                "metodo": METODO,
                "executor": EXECUTOR,
                "citacao": "conferida",
                "regra": ev.get("regra"),
            }
        ],
    }


def _pendencia(n: int, motivo: str, ev) -> dict:
    """Pendência de uma linha recusada: o motivo da conferência e o que a linha cita."""
    ev = ev if isinstance(ev, dict) else {}
    return {
        "objeto_id": f"{PREFIXO}linha-{n}",
        "motivo": motivo,
        "codigo": ev.get("codigo"),
        "documento": evidencias._nome_do_documento(ev) or None,
        "trecho": str(ev.get("trecho") or "")[:200],
    }


def de_ia(linhas: list, base: dict, raiz: Path) -> dict:
    """Gavetas (`objetos`, `fatos`, `evidencias`, `pendencias`) das linhas de IA conferidas contra os documentos das
    gavetas (`base["documentos"]`, arquivos em `raiz`), mais o `resumo` (linhas, aceitas, recusadas, menções).

    Cada linha é reconferida por `evidencias.conferir_arquivo`; o selo `citacao` do arquivo não vale. A mesma proposta
    (mesmo id) conta uma vez. A recusada, o documento que não se lê e a aceita sem página viram pendência."""
    linhas = [x for x in linhas if isinstance(x, dict) or str(x).strip()]
    paginas, documentos, motivos = _documentos_citados(linhas, base, Path(raiz))
    aceitas, recusadas = evidencias.conferir_arquivo(linhas, paginas)
    saida = {g: [] for g in ("objetos", "fatos", "evidencias", "pendencias")}
    vistos: set[str] = set()
    for ev in aceitas:
        nome = ev["documento"]["nome"]
        localizador = _localizador_das_gavetas(ev, paginas[nome])
        if ev["id"] in vistos:
            continue
        vistos.add(ev["id"])
        if localizador is None:
            recusadas.append({"linha": 0, "motivo": MOTIVO_SEM_PAGINA, "evidencia": ev})
            continue
        for gaveta, registros in _da_leitura(ev, documentos[nome], localizador).items():
            saida[gaveta] += registros
    saida["pendencias"] = [
        _pendencia(
            i, motivos.get(_nome_citado(r["evidencia"]), r["motivo"]), r["evidencia"]
        )
        for i, r in enumerate(recusadas, 1)
    ]
    saida["resumo"] = {
        "linhas": len(linhas),
        "aceitas": len(saida["objetos"]),
        "recusadas": len(saida["pendencias"]),
        "mencoes": sum(o["classe"] == CLASSE_MENCAO for o in saida["objetos"]),
    }
    return saida


def aplicar(base: dict, linhas: list, raiz: Path) -> tuple[dict, dict]:
    """(base com a leitura de IA, resumo): troca o que a rodada anterior gravou (idempotente) e confere a base."""
    nova = de_ia(linhas, base, raiz)
    resumo = nova.pop("resumo")
    limpa = sem_ia(base)
    return {**limpa, **{g: limpa[g] + nova[g] for g in nova}}, resumo


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "gavetas_ia",
        "descricao": "linhas de IA reconferidas pelo código contra o texto dos documentos das gavetas e gravadas como "
        "fatos declarados com evidência (documento, página ou aba e linha, trecho literal)",
        "funcoes": ["de_ia", "aplicar", "sem_ia", "metadados"],
        "conceitos": ["gavetas.json", "evidencia.schema.json"],
    }
