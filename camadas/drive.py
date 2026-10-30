"""Download dos PDFs da listagem do Drive que ainda não estão no disco, pelo link direto do arquivo.

O conector do Drive devolve o arquivo em base64 dentro da mensagem: acima de ~5,5 MB a conexão cai e acima de
10 MB é recusado — as formas e armaduras do projeto estrutural de Foz (6 a 22 MB) nunca desciam por ele. Arquivo
compartilhado por link baixa direto de `drive.usercontent.google.com` (medido em Foz, 30/10/2026: forma ACT01 de
7,7 MB inteira, `%PDF`). Arquivo privado devolve a página de login: fica registrado como falha, com o motivo.

    python -m camadas.drive exemplos/foz/obra.json            # baixa os pendentes
    python -m camadas.drive exemplos/foz/obra.json --filtro PBES
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

URL = "https://drive.usercontent.google.com/download?id={id}&export=download&confirm=t"


def baixar(file_id: str, destino: Path, tamanho: int | None = None, timeout: float = 300.0) -> dict:
    """Um arquivo: grava em `destino` se vier um PDF do tamanho da listagem; senão devolve o motivo."""
    try:
        with urllib.request.urlopen(URL.format(id=file_id), timeout=timeout) as r:
            dados = r.read()
    except OSError as e:
        return {"ok": False, "bytes": 0, "motivo": f"{type(e).__name__}: {e}"[:160]}
    if not dados.startswith(b"%PDF"):
        return {"ok": False, "bytes": len(dados), "motivo": "não veio PDF (arquivo privado ou link inválido)"}
    if tamanho and len(dados) != tamanho:
        return {"ok": False, "bytes": len(dados), "motivo": f"tamanho {len(dados)} ≠ {tamanho} da listagem"}
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(dados)
    return {"ok": True, "bytes": len(dados), "motivo": ""}


def pendentes(listagem: str | Path, pasta: str | Path, filtro: str | None = None) -> list[dict]:
    """PDFs da listagem que não estão no disco no mesmo caminho (`filtro`: regex sobre caminho/arquivo)."""
    with open(listagem, encoding="utf-8") as fh:
        linhas = list(csv.DictReader(fh, delimiter=";"))
    return [r for r in linhas if r["extensao"].lower() == "pdf" and not (Path(pasta) / r["caminho"] / r["titulo"]).exists()
            and (not filtro or re.search(filtro, f"{r['caminho']}/{r['titulo']}", re.IGNORECASE))]


def baixar_pendentes(cfg: dict, filtro: str | None = None, processos: int = 4, log=print) -> dict:
    """Baixa os pendentes da listagem do inventário em paralelo e acrescenta cada tentativa ao `_baixados.csv`."""
    c = cfg["inventario"]
    falta = pendentes(c["listagem"], c["pasta"], filtro)
    log(f"Drive: {len(falta)} PDFs pendentes ({sum(int(r['tamanho_bytes'] or 0) for r in falta) / 1e6:.0f} MB)")
    tarefa = lambda r: (r, baixar(r["id"], Path(c["pasta"]) / r["caminho"] / r["titulo"], int(r["tamanho_bytes"] or 0) or None))
    resumo = {"ok": 0, "falha": 0, "falhas": []}
    novo = not Path(c["baixados"]).exists()
    with ThreadPoolExecutor(processos) as ex, open(c["baixados"], "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        if novo:
            w.writerow(["caminho", "titulo", "id", "bytes", "ok"])
        for k, (r, res) in enumerate(ex.map(tarefa, falta), 1):
            w.writerow([r["caminho"], r["titulo"], r["id"], res["bytes"], "true" if res["ok"] else "false"])
            fh.flush()
            resumo["ok" if res["ok"] else "falha"] += 1
            if not res["ok"]:
                resumo["falhas"].append({"arquivo": r["titulo"], "motivo": res["motivo"]})
            log(f"  {k}/{len(falta)} {r['titulo']}: {'ok' if res['ok'] else res['motivo']} ({res['bytes'] / 1e6:.1f} MB)")
    log(f"Drive: {resumo['ok']} baixados, {resumo['falha']} com falha")
    return resumo


def metadados() -> dict:
    """Rastreabilidade (regra 9 do estilo)."""
    return {"modulo": "drive", "descricao": "download dos PDFs pendentes da listagem do Drive pelo link direto",
            "funcoes": ["baixar", "pendentes", "baixar_pendentes", "main"], "bibliografia": [],
            "premissas": [{"aplicacao": {"baixar": ["link direto"]}, "estado": "confirmado",
                           "fonte": "Foz 30/10/2026: arquivos compartilhados por link descem inteiros; o conector "
                                    "derruba a conexão acima de ~5,5 MB"}]}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Baixa os PDFs pendentes da listagem do Drive")
    ap.add_argument("config")
    ap.add_argument("--filtro", help="regex sobre caminho/arquivo (ex.: PBES)")
    ap.add_argument("--processos", type=int, default=4)
    a = ap.parse_args(argv)
    print(baixar_pendentes(json.loads(Path(a.config).read_text(encoding="utf-8")), a.filtro, a.processos)["falhas"])


if __name__ == "__main__":
    main()
