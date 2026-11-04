"""Dados do painel da EAP padrão, reproduzíveis: planilha do contrato + cadastro, sem pranchas.

Roda a cadeia como a obra declara (`escopo.itens_csv` e `escopo.catalogo` do obra.json, trechos lineares de
`eap_padrao.trechos_lineares`): `evidencias.loop` -> `consolidar` -> `eap_padrao.montar` -> `tabelas_do_painel`, e grava
`resumo.json`, `situacoes.json`, `etapas.json` e `folhas.json` na pasta de saída. O painel só lê esses JSON.

    uv run python scripts/painel_eap_padrao.py <obra.json> <saida/> [--planilha <xlsx>]

Com `--planilha`, o csv é regerado por `orcamento_sanepar` em pasta temporária e vale no lugar de `escopo.itens_csv`
(necessário quando o csv do disco é de uma versão antiga, sem a coluna `titulo_etapa`).
Sem pranchas (`dados["eap"]`): o painel mostra o que a planilha e o cadastro dizem, não o que as pranchas medem.
"""

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from camadas import eap_padrao, evidencias, orcamento_sanepar


def itens_csv_da_planilha(planilha: Path, pasta: Path) -> Path:
    """Gera `escopo_itens.csv` em `pasta` com `orcamento_sanepar` a partir da planilha do contrato; devolve o csv."""
    shutil.copy(planilha, pasta / "principal.xlsx")
    orcamento_sanepar.main(str(pasta))
    return pasta / "escopo_itens.csv"


def cadeia(cfg: dict) -> tuple[dict, list[dict], list[dict], list[dict]]:
    """(dados de entrada de `montar`, evidências, fatos, recusadas) a partir só da planilha do contrato."""
    trechos = eap_padrao.trechos_do_cfg(cfg)
    planilha = evidencias.planilha_do_contrato(cfg.get("escopo") or {}, trechos)
    if planilha is None:
        raise SystemExit(
            "planilha do contrato ausente: o csv de escopo.itens_csv não existe (use --planilha <xlsx>)"
        )
    if trechos and "titulo_etapa" not in planilha[0].columns:
        print(
            "AVISO: o csv da planilha não tem a coluna titulo_etapa (versão antiga): a declaração "
            "eap_padrao.trechos_lineares não terá efeito; regere com --planilha <xlsx>"
        )
    recusadas: list[dict] = []
    evs = evidencias.loop([], planilha, trechos_lineares=trechos, recusadas=recusadas)
    fatos = evidencias.consolidar(evs)
    dados = {
        "evidencias": {
            "fatos": evidencias._registros(fatos),
            "titulos_etapa": evidencias._titulos_do_contrato(planilha),
        }
    }
    return dados, evs, dados["evidencias"]["fatos"], recusadas


def hash_do_resultado(resultado: dict) -> str:
    """sha256 do resultado de `montar` sem os avisos (mesma conferência dos ciclos anteriores)."""
    sem_avisos = {k: v for k, v in resultado.items() if k != "avisos"}
    texto = json.dumps(sem_avisos, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def gravar_tabelas(tabelas: dict[str, list[dict]], saida: Path) -> None:
    """Um JSON por tabela, UTF-8, na ordem determinística de `tabelas_do_painel`."""
    saida.mkdir(parents=True, exist_ok=True)
    for nome, linhas in tabelas.items():
        (saida / f"{nome}.json").write_text(
            json.dumps(linhas, ensure_ascii=False), encoding="utf-8"
        )


def relatar(resultado: dict, evs: list, fatos: list, recusadas: list) -> None:
    """Imprime evidências, fatos, preenchidas/aplicáveis por tipo, recusadas, avisos e o hash."""
    print(f"evidências: {len(evs)} · fatos: {len(fatos)}")
    for bloco in resultado["tipos"]:
        r = bloco["resumo"]
        print(
            f"{bloco['tipo']}: preenchidas {r['n_preenchidas']}/{r['n_aplicaveis']} aplicáveis "
            f"(folhas {r['n_folhas']}, calculadas {r['n_calculadas']})"
        )
    print(f"recusadas: {len(recusadas)}")
    for recusada in recusadas:
        print(f"  - {recusada['motivo']}")
    print(f"avisos: {len(resultado['avisos'])}")
    for aviso in resultado["avisos"]:
        print(f"  - {aviso}")
    print(f"hash: {hash_do_resultado(resultado)}")


def principal() -> None:
    analisador = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analisador.add_argument("obra_json", type=Path)
    analisador.add_argument("saida", type=Path)
    analisador.add_argument(
        "--planilha",
        type=Path,
        help="xlsx do contrato; regera o csv de escopo em pasta temporária e o usa no lugar de escopo.itens_csv",
    )
    args = analisador.parse_args()
    cfg = json.loads(args.obra_json.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory() as temporaria:
        esc = cfg.setdefault("escopo", {})
        if args.planilha:
            esc["itens_csv"] = str(
                itens_csv_da_planilha(args.planilha, Path(temporaria))
            )
        dados, evs, fatos, recusadas = cadeia(cfg)
    resultado = eap_padrao.montar(dados, cfg)
    gravar_tabelas(eap_padrao.tabelas_do_painel(resultado), args.saida)
    relatar(resultado, evs, fatos, recusadas)


if __name__ == "__main__":
    principal()
