"""Inventário → gavetas `documentos` e `paginas` (F1 da reconstrução, docs/RECONSTRUCAO.md §2.1 e §3).

Passos 1 e 2 do fluxo do Caio: o loop sobre todos os arquivos (`inventario.py`) e a classificação (`extracao.classe`,
`conceitos/fontes.json`) ganham, por arquivo, **o que extrair dele**: o `destino` lista os leitores e as gavetas que
cada um alimenta (de-para 1, `conceitos/de_para_extracao.json`, mais o que o build faz hoje fora das gavetas). Arquivo
que nenhum leitor atende leva o `motivo_sem_destino`; arquivo fora do disco vira pendência, sem documento.

    documentos : um registro por arquivo no disco; `documento_id` = sha256[:16] do conteúdo (`gavetas.id_documento`)
    paginas    : uma por página de PDF (tamanho em pt com a rotação aplicada) e, na página da prancha
                 georreferenciada, a afim `M` pt → UTM e o `prancha_id`

Arquivos de conteúdo idêntico (mesmo sha256) são um só documento; os outros caminhos ficam em `copias`.

    python -m camadas.gavetas_documentos exemplos/foz/obra.json      # monta a base, confere e imprime o resumo
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

from . import extracao, gavetas, inventario

# Leitores que o build usa hoje e que o de-para 1 ainda não cita (docs/RECONSTRUCAO.md §0, passos 3 e 4).
# Cada linha: classe da fonte → condição → leitor e gavetas. Na F2 passam a gravar nas gavetas.
LEITORES_DO_BUILD = [
    {
        "classe": "projeto",
        "so_planta_georreferenciada": True,
        "extensoes": [".pdf"],
        "leitor": "camadas.construtivos",
        "gavetas": ["objetos", "geometria", "fatos", "evidencias"],
        "estado": "fora das gavetas (a ligar na F2)",
    },
    {
        "classe": "projeto",
        "so_planta_georreferenciada": False,
        "extensoes": [".pdf"],
        "leitor": "camadas.prancha",
        "gavetas": ["fatos", "evidencias"],
        "estado": "identidade, tabelas da folha e relação de materiais",
    },
    {
        "classe": "planilha",
        "extensoes": [".xlsx", ".xlsm"],
        "leitor": "camadas.contrato_211",
        "gavetas": ["fatos", "evidencias"],
        "estado": "fora das gavetas (a ligar na F2); sem preço",
    },
    {
        "classe": "planilha",
        "extensoes": [".xlsx", ".xlsm"],
        "leitor": "camadas.escopo_obra",
        "gavetas": ["fatos", "evidencias"],
        "estado": "relação de materiais; fora das gavetas (a ligar na F2)",
    },
    {
        "classe": "lista",
        "extensoes": [".pdf", ".xlsx", ".xlsm"],
        "leitor": "camadas.escopo_obra",
        "gavetas": ["fatos", "evidencias"],
        "estado": "relação de materiais; fora das gavetas (a ligar na F2)",
    },
    {
        "classe": "memorial",
        "extensoes": [".pdf"],
        "leitor": "camadas.evidencias",
        "gavetas": ["evidencias", "fatos"],
        "estado": "texto com citação conferida",
    },
    {
        "classe": "edital",
        "extensoes": [".pdf"],
        "leitor": "camadas.evidencias",
        "gavetas": ["evidencias", "fatos"],
        "estado": "texto com citação conferida",
    },
]
# vistas do de-para 1 que só valem para planta georreferenciada (geometria em UTM); as demais valem para a classe toda
VISTAS_DE_PLANTA = {"planta", "eixo da rede", "plantas de escavação"}
EXTENSOES_PDF = {".pdf"}
EXTENSOES_PLANILHA = {".xlsx", ".xlsm"}


def _classes() -> dict:
    return {c["id"]: c for c in extracao.FONTES["classes"]}


def _gavetas_da_entrada(entrada: dict) -> list[str]:
    """Gavetas que o leitor do de-para 1 alimenta: objetos, fatos e evidências sempre; geometria se a entrada tem
    geometria; superfícies se ela grava `superficie_id`."""
    saida = ["objetos"]
    if entrada.get("geometria") or "superficie_id" in entrada["propriedades"]:
        saida.append("geometria")
    if "superficie_id" in entrada["propriedades"]:
        saida.append("superficies")
    return saida + ["fatos", "evidencias"]


def destino_do_documento(
    item: dict, classe: str, georreferenciado: bool
) -> tuple[list[dict], str | None]:
    """`(destino, motivo_sem_destino)` de um arquivo: leitores do de-para 1 da classe (filtrados por tipo de arquivo e
    por planta georreferenciada) e leitores do build. Sem nenhum leitor, o motivo diz por quê."""
    ext = Path(item["arquivo"]).suffix.lower()
    cl = _classes().get(classe, {})
    planta = item.get("tipo") == "planta"
    destino = []
    for e in extracao.DE_PARA["entradas"]:
        if e.get("classe_fontes_json") != cl.get("nome"):
            continue
        if ext not in (
            EXTENSOES_PDF if classe in ("projeto", "laudo") else EXTENSOES_PLANILHA
        ):
            continue
        if (
            classe == "projeto"
            and e["vista"] in VISTAS_DE_PLANTA
            and not (planta and georreferenciado)
        ):
            continue
        if (
            classe == "projeto"
            and e["vista"] == "perfil"
            and item.get("tipo") == "documento"
        ):
            continue
        destino.append(
            {
                "leitor": e["leitor"],
                "gavetas": _gavetas_da_entrada(e),
                "objeto": e["objeto"],
                "vista": e["vista"],
                "estado": e["estado"],
            }
        )
    for r in LEITORES_DO_BUILD:
        if r["classe"] != classe or ext not in r["extensoes"]:
            continue
        if "so_planta_georreferenciada" in r and r["so_planta_georreferenciada"] != (
            planta and georreferenciado
        ):
            continue
        destino.append(
            {
                "leitor": r["leitor"],
                "gavetas": list(r["gavetas"]),
                "estado": r["estado"],
            }
        )
    if destino:
        return destino, None
    if classe == "cotacao":
        return [], f"fora do escopo: {cl.get('fora_do_escopo', 'preço')} ({cl['nome']})"
    tem_leitor = any(
        e.get("classe_fontes_json") == cl.get("nome")
        for e in extracao.DE_PARA["entradas"]
    ) or any(r["classe"] == classe for r in LEITORES_DO_BUILD)
    if tem_leitor:
        return (
            [],
            f"nenhum leitor lê arquivo {ext or 'sem extensão'} da classe {classe}",
        )
    return (
        [],
        f"classe {classe} ({cl.get('nome', classe)}): sem leitor para as gavetas; entrega: {cl.get('entrega', 'não declarada')}",
    )


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _afim_3x3(M) -> list[list[float]] | None:
    """Afim pt → UTM como lista 3×3 (aceita 2×3 e completa a linha [0, 0, 1]); None se não for afim."""
    if M is None:
        return None
    m = np.asarray(M, dtype="float64")
    if m.shape == (2, 3):
        m = np.vstack([m, [0.0, 0.0, 1.0]])
    return m.tolist() if m.shape == (3, 3) else None


def _prancha_do_pdf(caminho: Path, pranchas: list[dict]) -> dict | None:
    """Primeira prancha do build com afim cujo `pdf` é este arquivo (mesmo caminho; senão mesmo nome normalizado)."""
    alvo, nome = caminho.resolve(), inventario.normalizar(caminho.name)
    for p in pranchas:
        if p.get("M") is None or _afim_3x3(p["M"]) is None:
            continue
        pdf = Path(p["pdf"])
        if (pdf.exists() and pdf.resolve() == alvo) or inventario.normalizar(
            pdf.name
        ) == nome:
            return p
    return None


def _caminho_relativo(caminho: Path, item: dict, raiz: Path) -> str:
    try:
        return caminho.resolve().relative_to(raiz.resolve()).as_posix()
    except ValueError:
        return (Path(item.get("pasta_drive") or "") / item["arquivo"]).as_posix()


def _paginas_do_pdf(caminho: Path) -> list[tuple[float, float]]:
    """Largura e altura (pt) de cada página, com a rotação aplicada (`page.rect`)."""
    import pymupdf

    with pymupdf.open(caminho) as doc:
        return [
            (round(float(pg.rect.width), 2), round(float(pg.rect.height), 2))
            for pg in doc
        ]


def de_inventario(
    inventario: dict, raiz: Path, pranchas: list[dict] | None = None
) -> dict:
    """Inventário → base `{gaveta: [registros]}` com `documentos`, `paginas` e `pendencias`.

    `raiz` é a pasta da obra: `arquivo` sai relativo a ela. `pranchas` é a lista do build (cada uma com `pdf`, `id`, `M`
    e, se o PDF tem várias páginas, `pagina` de 1 a n; sem ela, a 1ª): só a página da prancha recebe `M` e `prancha_id`.
    """
    raiz, pranchas = Path(raiz), pranchas or []
    base = {g: [] for g in gavetas.GAVETAS}
    por_id: dict[str, dict] = {}
    for item in sorted(
        inventario["itens"], key=lambda i: (i.get("pasta_drive") or "", i["arquivo"])
    ):
        rotulo = (Path(item.get("pasta_drive") or "") / item["arquivo"]).as_posix()
        caminho = Path(item["caminho"]) if item.get("caminho") else None
        if caminho is None or not caminho.is_file():
            motivo = (
                item.get("situacao", "fora do disco")
                if not item["situacao"].startswith("no disco")
                else "indicado no disco, arquivo não encontrado"
            )
            base["pendencias"].append(
                {
                    "objeto_id": rotulo,
                    "motivo": f"fora do disco: {motivo}",
                    "arquivo": rotulo,
                }
            )
            continue
        ext = caminho.suffix.lower()
        tamanhos = []
        if ext in EXTENSOES_PDF:
            try:
                tamanhos = _paginas_do_pdf(caminho)
            except Exception as erro:  # noqa: BLE001 — PDF corrompido não derruba a base: vira pendência com o motivo
                base["pendencias"].append(
                    {
                        "objeto_id": rotulo,
                        "arquivo": rotulo,
                        "motivo": f"PDF ilegível: {type(erro).__name__}: {erro}"[:200],
                    }
                )
                continue
        sha = _sha256(caminho)
        arquivo = _caminho_relativo(caminho, item, raiz)
        if sha[:16] in por_id:
            por_id[sha[:16]].setdefault("copias", []).append(arquivo)
            continue
        classe = extracao.classe(item)
        prancha = _prancha_do_pdf(caminho, pranchas) if tamanhos else None
        destino, motivo = destino_do_documento(
            item, classe, bool(item.get("no_mapa") or prancha)
        )
        doc = {
            "documento_id": sha[:16],
            "arquivo": arquivo,
            "sha256": sha,
            "extensao": ext,
            "classe": classe,
            "paginas": len(tamanhos) or 1,
            "tipo": item.get("tipo"),
            "destino": destino,
        }
        if item.get("codigo"):
            doc["codigo_sanepar"] = item["codigo"]
        if motivo:
            doc["motivo_sem_destino"] = motivo
        por_id[doc["documento_id"]] = doc
        base["documentos"].append(doc)
        pagina_prancha = (
            max(1, min(int(prancha.get("pagina", 1)), len(tamanhos)))
            if prancha
            else None
        )
        for n, (largura_pt, altura_pt) in enumerate(tamanhos, start=1):
            registro = {
                "pagina_id": gavetas.id_pagina(doc["documento_id"], n),
                "documento_id": doc["documento_id"],
                "pagina": n,
                "largura_pt": largura_pt,
                "altura_pt": altura_pt,
            }
            if n == pagina_prancha:
                registro.update(
                    {"M": _afim_3x3(prancha["M"]), "prancha_id": prancha.get("id")}
                )
            base["paginas"].append(registro)
    return base


def resumo(base: dict) -> dict:
    """Documentos por classe e por leitor de destino, sem destino (com os motivos), páginas e páginas georreferenciadas.
    Um documento conta uma vez em cada leitor do seu destino."""
    docs = base.get("documentos", [])
    return {
        "documentos": len(docs),
        "por_classe": dict(sorted(Counter(d["classe"] for d in docs).items())),
        "por_destino": dict(
            sorted(Counter(x["leitor"] for d in docs for x in d["destino"]).items())
        ),
        "sem_destino": sum(not d["destino"] for d in docs),
        "motivos_sem_destino": dict(
            sorted(
                Counter(
                    d["motivo_sem_destino"] for d in docs if not d["destino"]
                ).items()
            )
        ),
        "paginas": len(base.get("paginas", [])),
        "paginas_georreferenciadas": sum(
            p.get("M") is not None for p in base.get("paginas", [])
        ),
        "pendencias": len(base.get("pendencias", [])),
    }


def _pranchas_do_build(cfg: dict) -> list[dict]:
    """Pranchas do obra.json com a afim gravada pelo build em `<saida>/pranchas/<id>.json` (só as de `ok`)."""
    pasta = Path(cfg.get("saida", "saida")) / "pranchas"
    saida = []
    for p in cfg.get("pranchas", []):
        cache = pasta / f"{p['id']}.json"
        r = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
        saida.append({**p, "M": r.get("M") if r.get("ok", True) else None})
    return saida


def metadados() -> dict:
    """Rastreabilidade das regras de destino e das chaves (regra 9 do estilo)."""
    return {
        "modulo": "gavetas_documentos",
        "descricao": "inventário → gavetas documentos e paginas: classe, destino (leitor e gavetas) ou motivo de não ter, "
        "tamanho da página e afim da prancha georreferenciada",
        "funcoes": ["de_inventario", "destino_do_documento", "resumo"],
        "bibliografia": [],
        "premissas": [
            {
                "aplicacao": {
                    "destino_do_documento": [
                        "conceitos/de_para_extracao.json por classe_fontes_json",
                        "VISTAS_DE_PLANTA só com planta georreferenciada",
                    ]
                },
                "fonte": "de-para 1 (docs/MEMORIA_ESPACIAL.md), estado premissa",
            },
            {
                "aplicacao": {"destino_do_documento": ["LEITORES_DO_BUILD"]},
                "fonte": "docs/RECONSTRUCAO.md §0: o que o build lê hoje fora das gavetas (construtivos, contrato_211, "
                "escopo_obra, evidencias, prancha)",
            },
            {
                "aplicacao": {
                    "de_inventario": [
                        "documento_id = sha256[:16] do conteúdo (gavetas.id_documento)",
                        "mesmo sha256 = um documento, outros caminhos em copias",
                    ]
                },
                "fonte": "docs/RECONSTRUCAO.md §2.1 (gavetas v2)",
            },
        ],
        "ultima_revisao": "2026-11-04",
    }


def main(argv=None):
    caminho_obra = Path((argv or sys.argv[1:])[0])
    cfg = json.loads(caminho_obra.read_text(encoding="utf-8"))
    if not inventario.disponivel(cfg):
        raise SystemExit(
            "inventário indisponível: falta a listagem do Drive (pendência, nada a montar)"
        )
    t0 = time.perf_counter()
    inv = inventario.inventario(
        cfg, Path(cfg.get("saida", "saida")) / "inventario_cache.json"
    )
    t1 = time.perf_counter()
    base = de_inventario(inv, Path(cfg["inventario"]["pasta"]), _pranchas_do_build(cfg))
    t2 = time.perf_counter()
    erros = gavetas.conferir_base(base)
    print(json.dumps(resumo(base), ensure_ascii=False, indent=2))
    print(
        f"tempo: inventário {t1 - t0:.1f} s; gavetas (sha256 + páginas) {t2 - t1:.1f} s; conferência "
        f"{time.perf_counter() - t2:.1f} s"
    )
    print(f"conferir_base: {len(erros)} erro(s)")
    for e in erros[:20]:
        print(" -", e)
    for pend in base["pendencias"][:20]:
        print(" pendência:", pend["objeto_id"], "→", pend["motivo"])


if __name__ == "__main__":
    main()
