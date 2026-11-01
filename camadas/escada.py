"""Executor da escada: roda os degraus de código e separa o que sobra por executor (Haiku, Sonnet, você).

A escada de cada situação está em `conceitos/fontes.json` (`escada[].degraus`): código primeiro, depois IA, por último
"você". Cada volta: inventário → pendências → o próximo degrau de código de cada pendência (baixar, reler, reler o
carimbo em 300 dpi, extrair o zip) → reavaliação. As tentativas ficam em `complementos.json` (`tentativas["código:baixar"]`)
e `max_tentativas` vale para todo degrau: sem sucesso, o degrau se esgota e a pendência sobe. O que sobra para IA ou
para você vai a `saida/<obra>/lotes/<executor>.jsonl` (regravado a cada rodada), com os campos de `retorno` da classe.

    python -m camadas.escada exemplos/foz/obra.json [--voltas 3]
"""
from __future__ import annotations

import argparse
import csv
import json
import zipfile
from pathlib import Path

from . import drive, extracao, inventario, pdf_cad

SITUACAO_ZIP = "no disco (dentro do zip)"


def _chave(degrau: dict) -> str:
    """Chave do degrau em `tentativas`: 'código:baixar', 'Haiku:None'."""
    return f"{degrau['executor']}:{degrau['funcao']}"


def proximo_degrau(avaliacao: dict, complemento: dict | None) -> dict | None:
    """Primeiro degrau da situação com tentativas abaixo de `max_tentativas`; None se esgotou ou não há situação."""
    passo = extracao.ESCADA.get(avaliacao.get("situacao") or "")
    feitas = (complemento or {}).get("tentativas", {})
    for degrau in (passo or {}).get("degraus", []):
        if feitas.get(_chave(degrau), 0) < degrau["max_tentativas"]:
            return degrau
    return None


def _baixar(cfg: dict, item: dict, baixar=None) -> dict:
    """Degrau 'baixar': só PDF desce pelo link direto; outro tipo conta a tentativa e falha com o motivo."""
    c = cfg["inventario"]
    if Path(item["arquivo"]).suffix.lower() != ".pdf":
        return {"ok": False, "campos": {}, "motivo": "drive.baixar só baixa PDF"}
    if not item.get("id_drive"):
        return {"ok": False, "campos": {}, "motivo": "arquivo sem id no Drive"}
    res = (baixar or drive.baixar)(item["id_drive"], Path(c["pasta"]) / item["pasta_drive"] / item["arquivo"])
    if c.get("baixados"):                                   # a ingestão vê a tentativa, como em drive.baixar_pendentes
        novo = not Path(c["baixados"]).exists()
        with open(c["baixados"], "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter=";")
            if novo:
                w.writerow(["caminho", "titulo", "id", "bytes", "ok"])
            w.writerow([item["pasta_drive"], item["arquivo"], item["id_drive"], res["bytes"],
                        "true" if res["ok"] else "false"])
    return {"ok": res["ok"], "campos": {}, "motivo": res.get("motivo", "")}


def _reler(item: dict, reler: set) -> dict:
    """Degrau 'reler': o caminho entra em `reler` e o próximo inventário ignora o cache para ele."""
    if not item.get("caminho"):
        return {"ok": False, "campos": {}, "motivo": "arquivo sem caminho no disco"}
    reler.add(item["caminho"])
    return {"ok": True, "campos": {}, "motivo": "relido na próxima volta"}


def _reler_carimbo(item: dict) -> dict:
    """Degrau 'reler_carimbo': OCR do carimbo em 300 dpi; devolve os campos não nulos em `{"carimbo": {...}}`."""
    if Path(item["arquivo"]).suffix.lower() != ".pdf" or not item.get("caminho"):
        return {"ok": False, "campos": {}, "motivo": "só PDF no disco tem carimbo"}
    try:
        lido = inventario.reler_carimbo(item["caminho"])
    except Exception as erro:  # noqa: BLE001 — sem tesseract ou PDF ruim: o degrau falha, a escada sobe
        return {"ok": False, "campos": {}, "motivo": f"{type(erro).__name__}: {erro}"[:160]}
    campos = {k: v for k, v in lido.items() if v}
    achou = any(campos.get(k) for k in ("folha", "escala", "data", "titulo"))
    return {"ok": achou, "campos": {"carimbo": campos} if achou else {}, "motivo": "" if achou else "OCR sem campos"}


def _extrair_zip(cfg: dict, item: dict) -> dict:
    """Degrau 'extrair_zip': extrai para `<pasta do inventário>/_zip/<nome do zip>/` (sem sair dessa pasta)."""
    if not item.get("caminho") or Path(item["arquivo"]).suffix.lower() != ".zip":
        return {"ok": False, "campos": {}, "motivo": "só .zip no disco é extraído"}
    destino = (Path(cfg["inventario"]["pasta"]) / "_zip" / item["arquivo"]).resolve()
    try:
        with zipfile.ZipFile(item["caminho"]) as z:
            for membro in z.infolist():
                alvo = (destino / membro.filename).resolve()
                if destino not in alvo.parents and alvo != destino:
                    return {"ok": False, "campos": {}, "motivo": f"caminho suspeito no zip: {membro.filename}"}
            z.extractall(destino)
    except (zipfile.BadZipFile, OSError) as erro:
        return {"ok": False, "campos": {}, "motivo": f"{type(erro).__name__}: {erro}"[:160]}
    return {"ok": True, "campos": {}, "motivo": f"extraído em {destino}"}


def itens_do_zip(cfg: dict, inv: dict, memo: dict | None = None) -> dict:
    """Acrescenta ao inventário os arquivos já extraídos em `_zip/` como itens filhos (`pasta_drive` =
    '<pasta>/<zip>!', situação 'no disco (dentro do zip)'), lidos por `inventario.ler_arquivo`. A listagem do Drive
    não os tem, então isto roda a cada volta. `memo` guarda a leitura entre voltas."""
    raiz = Path(cfg["inventario"]["pasta"]) / "_zip"
    memo = {} if memo is None else memo
    regras = json.loads((pdf_cad.CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))
    filhos = []
    for pasta_zip in sorted(p for p in raiz.glob("*") if p.is_dir()):
        pai = next((i for i in inv["itens"] if i["arquivo"] == pasta_zip.name), None)
        base = f"{pai['pasta_drive']}/{pasta_zip.name}!" if pai and pai["pasta_drive"] else f"{pasta_zip.name}!"
        for p in sorted(x for x in pasta_zip.rglob("*") if x.is_file()):
            rel = p.parent.relative_to(pasta_zip).as_posix()
            item = {"arquivo": p.name, "pasta_drive": base + ("" if rel == "." else f"/{rel}"), "id_drive": None,
                    "mb": round(p.stat().st_size / 1e6, 2), "codigo": inventario.codigo_sanepar(p.name),
                    "situacao": SITUACAO_ZIP, "caminho": str(p), **inventario._leitura(memo, p, True, set())}
            titulo = (item.get("carimbo") or {}).get("titulo")
            item["tipo"] = inventario.tipo_documento(p.name, titulo, regras)
            item["grupo"], item["subgrupo"] = pdf_cad.disciplina_da_prancha(p.name, titulo or "")
            item["no_mapa"] = None
            filhos.append(item)
    return {**inv, "itens": [*inv["itens"], *filhos]}


def _zips_extraidos(cfg: dict, p: dict) -> dict:
    """Zip já extraído e com filhos inventariados deixa de ser 'conteúdo não inventariado': passa a completo."""
    raiz = Path(cfg["inventario"]["pasta"]) / "_zip"
    pastas = {a["pasta_drive"] or "" for a in p["avaliacoes"]}

    def resolvido(a):
        prefixo = f"{a['pasta_drive']}/{a['arquivo']}!" if a["pasta_drive"] else f"{a['arquivo']}!"
        return (a["situacao"] == "conteúdo não inventariado" and (raiz / a["arquivo"]).is_dir()
                and any(q.startswith(prefixo) for q in pastas))
    av = [{**a, "estado": "completa", "faltando": [], "situacao": None, "proximo": None, "acao": None}
          if resolvido(a) else a for a in p["avaliacoes"]]
    por_estado = {}
    for a in av:
        por_estado[a["estado"]] = por_estado.get(a["estado"], 0) + 1
    return {**p, "avaliacoes": av, "pendencias": [a for a in av if a["estado"] != "completa" and not a["fora_do_escopo"]],
            "por_estado": por_estado}


def _avaliar(cfg: dict, out: Path, reler: set, memo: dict) -> tuple[dict, dict, dict]:
    """Inventário (com os filhos dos zips) e as pendências com os complementos: (inv, pendências, complementos)."""
    out.mkdir(parents=True, exist_ok=True)
    inv = inventario.inventario(cfg, out / "inventario_cache.json", log=lambda *_: None, reler=set(reler))
    reler.clear()
    inv = itens_do_zip(cfg, inv, memo)
    extracao.aplicar_retornos(out, inv)              # o que a IA devolveu entra na volta, como qualquer complemento
    compl = extracao.ler_complementos(out / "complementos.json")
    p = extracao.pendencias(inv, cfg["inventario"].get("pastas"), compl)
    return inv, _zips_extraidos(cfg, p), compl


def _executar_degrau(cfg: dict, degrau: dict, item: dict, reler: set, baixar) -> dict:
    """Despacha o degrau de código pela `funcao`."""
    f = degrau["funcao"]
    if f == "baixar":
        return _baixar(cfg, item, baixar)
    if f == "reler":
        return _reler(item, reler)
    if f == "reler_carimbo":
        return _reler_carimbo(item)
    if f == "extrair_zip":
        return _extrair_zip(cfg, item)
    return {"ok": False, "campos": {}, "motivo": f"função de degrau desconhecida: {f}"}


def executar(cfg: dict, out: str | Path, voltas: int = 3, baixar=None) -> dict:
    """Roda até `voltas` voltas de degraus de código e grava os lotes. Para quando nenhuma pendência tem degrau de
    código. `baixar(id, destino)` é injetável para teste sem rede. Devolve o resumo."""
    out = Path(out)
    reler, memo, feitas = set(), {}, 0
    for n in range(1, voltas + 2):                     # a última avaliação só confere o que a última volta fez
        inv, p, compl = _avaliar(cfg, out, reler, memo)
        extracao.registrar_por_executor(p["avaliacoes"], out / "extracao.jsonl", passe=f"V{n}")
        if n > voltas:
            break
        por_chave = {(i["pasta_drive"], i["arquivo"]): i for i in inv["itens"]}
        agiu = False
        for av in p["pendencias"]:
            degrau = proximo_degrau(av, compl.get(f"{av['pasta_drive']}/{av['arquivo']}"))
            if not degrau or degrau["executor"] != "código":
                continue
            item = por_chave[(av["pasta_drive"], av["arquivo"])]
            res = _executar_degrau(cfg, degrau, item, reler, baixar)
            extracao.gravar_complemento(out / "complementos.json", item, res["campos"], "código", _chave(degrau))
            agiu = True
        if not agiu:
            break
        feitas = n
    return {"voltas": feitas, "por_estado": p["por_estado"], "lotes": lotes(out, p["pendencias"], compl, inv),
            "pendencias": p, "inventario": inv}


def lotes(out: str | Path, pendencias: list, complementos: dict, inv: dict | None = None) -> dict:
    """Grava `lotes/<executor>.jsonl` (sobrescreve; lote de rodada anterior sem pendência some) com as pendências cujo
    próximo degrau é de IA ou 'você'. Devolve {executor: quantidade}."""
    pasta = Path(out) / "lotes"
    pasta.mkdir(parents=True, exist_ok=True)
    for velho in pasta.glob("*.jsonl"):
        velho.unlink()
    classes = {c["id"]: c for c in extracao.FONTES["classes"]}
    caminhos = {(i["pasta_drive"], i["arquivo"]): i.get("caminho") for i in (inv or {}).get("itens", [])}
    linhas = {}
    for av in pendencias:
        degrau = proximo_degrau(av, complementos.get(f"{av['pasta_drive']}/{av['arquivo']}"))
        if not degrau or degrau["executor"] == "código":
            continue
        linhas.setdefault(degrau["executor"], []).append(
            {"arquivo": av["arquivo"], "pasta_drive": av["pasta_drive"], "caminho": caminhos.get((av["pasta_drive"], av["arquivo"])),
             "classe": av["classe"], "situacao": av["situacao"], "faltando": av["faltando"], "acao": av["acao"],
             "retorno": classes[av["classe"]].get("retorno", []),
             "gavetas": extracao.gavetas_da_classe(av["classe"])})
    for executor, itens in linhas.items():
        (pasta / f"{executor}.jsonl").write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in itens),
                                                 encoding="utf-8")
    return {e: len(i) for e, i in linhas.items()}


def metadados() -> dict:
    """Rastreabilidade das regras do executor (regra 9 do estilo)."""
    return {"modulo": "escada",
            "descricao": "executor da escada: degraus de código (baixar, reler, reler_carimbo, extrair_zip) com "
                         "tentativas contadas, e lotes por executor para o que sobra",
            "funcoes": ["proximo_degrau", "itens_do_zip", "executar", "lotes", "main"],
            "premissas": [{"aplicacao": {"proximo_degrau": ["conceitos/fontes.json escada[].degraus",
                                                            "max_tentativas em todo degrau"],
                                         "itens_do_zip": ["pasta_drive = '<pasta>/<zip>!'", SITUACAO_ZIP],
                                         "lotes": ["retorno da classe", "regravado a cada rodada",
                                                    "gavetas: de_para_extracao.json pela classe_fontes_json"]},
                           "fonte": "plano rodada 20, E4 (docs/ARQUITETURA.md §10); rodada 22, E3"}],
            "ultima_revisao": "2026-10-31"}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Roda a escada: degraus de código e lotes para IA")
    ap.add_argument("config")
    ap.add_argument("--voltas", type=int, default=3)
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    r = executar(cfg, Path(cfg.get("saida", "saida")), a.voltas)
    print(f"voltas de código: {r['voltas']}")
    print("por estado:", r["por_estado"])
    print("lotes por executor:", r["lotes"] or "nenhum")


if __name__ == "__main__":
    main()
