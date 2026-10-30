"""Reavaliação do inventário: o que cada arquivo é como fonte, se a extração saiu, e o próximo passe para o que não saiu.

    classe     = o que o arquivo é como evidência (projeto, laudo, memorial, edital, planilha, folha de dados,
                 documento de obra, cotação…) por `conceitos/fontes.json`: tipo do código Sanepar, extensão, termos
    estado     = completa | parcial | falhou | sem leitor | fora do disco, pelos campos que a classe exige
    proximo    = degrau da escada (código → Haiku → Sonnet → você) para a situação; a IA só entra depois do código
    séries     = carimbo "FOLHA 06/14": todas as folhas de 1 a 14 da mesma pasta e disciplina estão na listagem?
    registro   = cada passe gravado em `extracao.jsonl` só quando classe, estado ou o que falta muda: mostra quantas voltas
                 cada arquivo levou e quem resolveu (código ou IA), base do índice de determinismo

Rodar de novo é seguro e desejado: o inventário tem cache por arquivo e o registro não duplica.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import inventario, pdf_cad

FONTES = json.loads((pdf_cad.CONCEITOS / "fontes.json").read_text(encoding="utf-8"))
ESCADA = {d["situacao"]: d for d in FONTES["escada"]}


def classe(item: dict) -> str:
    """Classe da fonte em passadas, da mais segura à mais fraca: tipo do código Sanepar; termos de cotação e de
    documento de obra no nome; extensão; termos no nome e no título do carimbo; os mesmos termos na pasta. O nome
    vale mais que a pasta: um memorial guardado em PROJETOS/PLANTAS continua memorial."""
    cod = item.get("codigo") or {}
    ext = Path(item["arquivo"]).suffix.lower()
    nome = inventario.normalizar(f"{item['arquivo']} {(item.get('carimbo') or {}).get('titulo') or ''}").upper()
    pasta = inventario.normalizar(item.get("pasta_drive") or "").upper()
    casa = lambda c, alvo: bool(c.get("termos")) and re.search(c["termos"], alvo)
    testes = (lambda c: cod.get("tipo") in c.get("codigo_tipo", []), lambda c: c.get("prioridade") and casa(c, nome),
              lambda c: ext in c.get("extensoes", []), lambda c: casa(c, nome), lambda c: casa(c, pasta))
    for teste in testes:
        achou = next((c["id"] for c in FONTES["classes"] if teste(c)), None)
        if achou:
            return achou
    return "outro"


def _faltando(item: dict, exige: dict) -> list[str]:
    """Campos exigidos pela classe que a leitura não trouxe (carimbo.titulo, texto, abas…)."""
    faltam = []
    for campo in exige.get({"ler_pdf": "pdf", "ler_planilha": "planilha", "ler_zip": "zip"}.get(item.get("leitor"), ""), []):
        raiz, _, sub = campo.partition(".")
        valor = (item.get(raiz) or {}).get(sub) if sub else item.get(raiz)
        if raiz == "texto" and valor != "sim":
            valor = None
        if not valor:
            faltam.append(campo)
    return faltam


def avaliar(item: dict) -> dict:
    """Estado da extração do arquivo e a situação que decide o próximo passe da escada."""
    cl = next(c for c in FONTES["classes"] if c["id"] == classe(item))
    if not item["situacao"].startswith("no disco"):
        estado, situacao, faltam = "fora do disco", "fora do disco", []
    elif item.get("erro"):
        estado, situacao, faltam = "falhou", "falhou", [item["erro"]]
    elif cl.get("dispensa_leitura"):
        estado, situacao, faltam = "completa", None, []
    elif not item.get("leitor"):
        estado, situacao, faltam = "sem leitor", "sem leitor", []
    else:
        faltam = _faltando(item, cl.get("satisfatoria", {}))
        situacao = ("sem texto" if "texto" in faltam else
                    "carimbo incompleto" if any(f.startswith("carimbo.") for f in faltam) else
                    "leitura incompleta" if faltam else
                    "conteúdo não inventariado" if item.get("leitor") == "ler_zip" else None)
        estado = "parcial" if situacao else "completa"
    if cl["id"] == "outro" and estado == "completa":
        estado, situacao = "parcial", "classe desconhecida"
    passo = ESCADA.get(situacao) if situacao else None
    return {"arquivo": item["arquivo"], "pasta_drive": item.get("pasta_drive"), "id_drive": item.get("id_drive"),
            "classe": cl["id"], "fora_do_escopo": cl.get("fora_do_escopo"), "estado": estado, "faltando": faltam,
            "situacao": situacao, "proximo": passo and passo["proximo"], "acao": passo and passo["acao"]}


def series(itens: list) -> list[dict]:
    """Folhas que faltam numa série pelo carimbo 'n/m', por pasta, disciplina e unidade do código Sanepar: 06/14 e
    07/14 na listagem dizem que existem 14 folhas. Se a pasta tem arquivos fora do disco (sem carimbo lido), a folha
    que falta pode estar entre eles: a série diz quantos, e ausência só se afirma por `inventario.procurar`."""
    grupos, fora = {}, {}
    for i in itens:
        cod = i.get("codigo") or {}
        if not i["situacao"].startswith("no disco"):
            fora[i.get("pasta_drive")] = fora.get(i.get("pasta_drive"), 0) + 1
        f = (i.get("carimbo") or {}).get("folha")
        if f and "/" in f:
            n, m = (int(x) for x in f.split("/"))
            chave = (i.get("pasta_drive"), cod.get("disciplina"), cod.get("unidade"), m)
            grupos.setdefault(chave, set()).add(n)
    return [{"pasta_drive": p, "disciplina": d, "unidade": u, "total": m, "presentes": len(ns),
             "faltam": [f"{k:02d}/{m:02d}" for k in range(1, m + 1) if k not in ns],
             "fora_do_disco_na_pasta": fora.get(p, 0)}
            for (p, d, u, m), ns in sorted(grupos.items(), key=str) if len(ns) < m]


def pendencias(inv: dict) -> dict:
    """A lista que abre cada rodada: tudo que não está completo, com o próximo passe, e as séries incompletas."""
    av = [avaliar(i) for i in inv["itens"]]
    abertas = [a for a in av if a["estado"] != "completa" and not a["fora_do_escopo"]]
    fora_do_escopo = [{k: a[k] for k in ("arquivo", "pasta_drive", "classe", "fora_do_escopo")} for a in av
                      if a["fora_do_escopo"]]
    no_escopo = [a for a in av if not a["fora_do_escopo"]]
    contagem = {}
    for a in av:
        contagem[a["estado"]] = contagem.get(a["estado"], 0) + 1
    por_classe = {}
    for a in av:
        por_classe[a["classe"]] = por_classe.get(a["classe"], 0) + 1
    return {"avaliacoes": av, "pendencias": abertas, "fora_do_escopo": fora_do_escopo, "series": series(inv["itens"]),
            "por_estado": contagem, "por_classe": por_classe,
            "fracao_completa": round(sum(a["estado"] == "completa" for a in no_escopo) / max(len(no_escopo), 1), 3)}


def registrar(avaliacoes: list, caminho: Path, passe: str, executor: str = "código") -> int:
    """Acrescenta ao registro uma linha por arquivo cuja classe, estado ou lista do que falta mudou desde a última
    linha dele; devolve quantas."""
    ultimo = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                r = json.loads(linha)
                ultimo[(r["pasta_drive"], r["arquivo"])] = (r["classe"], r["estado"], r["faltando"])
    novas = [{"data": time.strftime("%Y-%m-%d %H:%M"), "passe": passe, "executor": executor,
              **{k: a[k] for k in ("arquivo", "pasta_drive", "classe", "estado", "faltando")}}
             for a in avaliacoes
             if ultimo.get((a["pasta_drive"], a["arquivo"])) != (a["classe"], a["estado"], a["faltando"])]
    if novas:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        with caminho.open("a", encoding="utf-8") as arquivo:
            arquivo.writelines(json.dumps(n, ensure_ascii=False) + "\n" for n in novas)
    return len(novas)


def metadados() -> dict:
    """Rastreabilidade das regras da reavaliação (regra 9 do estilo)."""
    return {"modulo": "extracao",
            "descricao": "classe da fonte, estado da extração, próximo passe da escada, séries de folhas e registro",
            "funcoes": ["classe", "avaliar", "series", "pendencias", "registrar"],
            "premissas": [{"aplicacao": {"classe": ["conceitos/fontes.json classes"], "avaliar": ["satisfatoria", "escada"]},
                           "fonte": FONTES["metadata"]["fonte"]}],
            "ultima_revisao": "2026-10-30"}
