"""Reavaliação do inventário: o que cada arquivo é como fonte, se a extração saiu, e o próximo passe para o que não saiu.

    classe     = o que o arquivo é como evidência (projeto, laudo, memorial, edital, planilha, folha de dados,
                 documento de obra, cotação…) por `conceitos/fontes.json`: tipo do código Sanepar, extensão, termos
    estado     = completa | parcial | falhou | sem leitor | fora do disco, pelos campos que a classe exige
    proximo    = degrau da escada (código → Haiku → Sonnet → você) para a situação; a IA só entra depois do código
    séries     = carimbo "FOLHA 06/14": todas as folhas de 1 a 14 da mesma pasta e disciplina estão na listagem?
    registro   = cada passe gravado em `extracao.jsonl` só quando o estado muda: o histórico mostra quantas voltas
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
    """Classe da fonte em três passadas, da mais segura à mais fraca: termos de cotação e de documento de obra (o
    que manda no escopo ou sai dele), tipo do código Sanepar, extensão e, por fim, termos no caminho, no nome e no
    título do carimbo."""
    cod = item.get("codigo") or {}
    ext = Path(item["arquivo"]).suffix.lower()
    alvo = inventario.normalizar(f"{item.get('pasta_drive', '')} {item['arquivo']} "
                                 f"{(item.get('carimbo') or {}).get('titulo') or ''}").upper()
    casa = lambda c: bool(c.get("termos")) and re.search(c["termos"], alvo)
    testes = (lambda c: c.get("prioridade") and casa(c), lambda c: cod.get("tipo") in c.get("codigo_tipo", []),
              lambda c: ext in c.get("extensoes", []), casa)
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
    elif not item.get("leitor"):
        estado, situacao, faltam = "sem leitor", "sem leitor", []
    else:
        faltam = _faltando(item, cl.get("satisfatoria", {}))
        estado = "parcial" if faltam else "completa"
        situacao = ("sem texto" if "texto" in faltam else "carimbo incompleto" if faltam else
                    "conteúdo não inventariado" if item.get("leitor") == "ler_zip" else None)
        estado = "parcial" if situacao else estado
    if cl["id"] == "outro" and estado == "completa":
        estado, situacao = "parcial", "classe desconhecida"
    passo = ESCADA.get(situacao) if situacao else None
    return {"arquivo": item["arquivo"], "pasta_drive": item.get("pasta_drive"), "id_drive": item.get("id_drive"),
            "classe": cl["id"], "fora_do_escopo": cl.get("fora_do_escopo"), "estado": estado, "faltando": faltam,
            "situacao": situacao, "proximo": passo and passo["proximo"], "acao": passo and passo["acao"]}


def series(itens: list) -> list[dict]:
    """Folhas que faltam numa série pelo carimbo 'n/m', por pasta e disciplina: 06/14 e 07/14 na listagem dizem que
    existem 14 folhas; as que não aparecem são pendência de inventário, não ausência."""
    grupos = {}
    for i in itens:
        f = (i.get("carimbo") or {}).get("folha")
        if f and "/" in f:
            n, m = (int(x) for x in f.split("/"))
            chave = (i.get("pasta_drive"), (i.get("codigo") or {}).get("disciplina"), m)
            grupos.setdefault(chave, set()).add(n)
    return [{"pasta_drive": p, "disciplina": d, "total": m, "presentes": len(ns),
             "faltam": [f"{k:02d}/{m:02d}" for k in range(1, m + 1) if k not in ns]}
            for (p, d, m), ns in sorted(grupos.items(), key=str) if len(ns) < m]


def pendencias(inv: dict) -> dict:
    """A lista que abre cada rodada: tudo que não está completo, com o próximo passe, e as séries incompletas."""
    av = [avaliar(i) for i in inv["itens"]]
    abertas = [a for a in av if a["estado"] != "completa" and not a["fora_do_escopo"]]
    contagem = {}
    for a in av:
        contagem[a["estado"]] = contagem.get(a["estado"], 0) + 1
    por_classe = {}
    for a in av:
        por_classe[a["classe"]] = por_classe.get(a["classe"], 0) + 1
    return {"avaliacoes": av, "pendencias": abertas, "series": series(inv["itens"]), "por_estado": contagem,
            "por_classe": por_classe,
            "completas_por_codigo": round(contagem.get("completa", 0) / max(len(av), 1), 3)}


def registrar(avaliacoes: list, caminho: Path, passe: str, executor: str = "código") -> int:
    """Acrescenta ao registro uma linha por arquivo cujo estado mudou desde a última linha dele; devolve quantas."""
    ultimo = {}
    if caminho.exists():
        for linha in caminho.read_text(encoding="utf-8").splitlines():
            if linha.strip():
                r = json.loads(linha)
                ultimo[(r["pasta_drive"], r["arquivo"])] = r["estado"]
    novas = [{"data": time.strftime("%Y-%m-%d %H:%M"), "passe": passe, "executor": executor,
              **{k: a[k] for k in ("arquivo", "pasta_drive", "classe", "estado", "faltando")}}
             for a in avaliacoes if ultimo.get((a["pasta_drive"], a["arquivo"])) != a["estado"]]
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
