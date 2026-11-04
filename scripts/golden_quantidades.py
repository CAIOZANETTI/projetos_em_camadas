"""Golden das quantidades do build de Foz: congela, do dados.json, só quantidades e contagens.

A reconstrução (F0 de docs/RECONSTRUCAO.md §3) só prova que não perdeu nada se houver um retrato do que o build
produz hoje. O resumo leva números e os textos de situação, unidade e código; não leva preço, nem texto livre
de fonte ou premissa.

    python scripts/golden_quantidades.py saida/foz/dados.json --gravar tests/golden_foz/quantidades_foz.json
    python scripts/golden_quantidades.py saida/foz/dados.json

Sem `--gravar` compara com o golden (`--golden`) e sai com código 1 se houver diferença.
"""

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GOLDEN_PADRAO = RAIZ / "tests" / "golden_foz" / "quantidades_foz.json"
TOL_ABS_PADRAO = 1e-3
CASAS_DECIMAIS = 6


def _arredonda(valor):
    """Float com seis casas decimais; o resto passa como está (inteiro, texto, None)."""
    if isinstance(valor, float):
        return round(valor, CASAS_DECIMAIS)
    return valor


def _numero(valor) -> bool:
    """Verdadeiro para int e float; bool não conta como número."""
    return isinstance(valor, (int, float)) and not isinstance(valor, bool)


def _escavacao(escavacao: dict) -> dict:
    """Escavação e reaterro do total e de cada cava, por id."""
    cavas = {
        cava["id"]: {
            "escavacao_m3": _arredonda(cava["escavacao_m3"]),
            "reaterro_m3": _arredonda(cava["reaterro_m3"]),
        }
        for cava in escavacao["cavas"]
    }
    total = escavacao["total"]
    return {
        "total": {
            "escavacao_m3": _arredonda(total["escavacao_m3"]),
            "reaterro_m3": _arredonda(total["reaterro_m3"]),
        },
        "cavas": cavas,
    }


def _valas(valas: dict) -> dict:
    """Extensão de cada rede e soma dos volumes de vala dos trechos do quadro (m³)."""
    redes = {}
    for rede in valas["redes"]:
        volumes = [trecho["volume_vala_m3"] for trecho in rede["quadro"]]
        redes[rede["id"]] = {
            "extensao_m": _arredonda(rede["extensao_m"]),
            "volume_vala_m3": None if None in volumes else _arredonda(sum(volumes)),
        }
    return {"redes": redes}


def _contrato_211(contrato: dict) -> dict:
    """Situação e quantidades de cada linha da planilha 211, por aba e número da linha."""
    linhas = {
        f"{linha['aba']}|{linha['linha']}": {
            "situacao": linha["situacao"],
            "calculada": _arredonda(linha["calculada"]),
            "unidade_calculada": linha["unidade_calculada"],
            "declarada": linha["declarada"],
        }
        for linha in contrato["linhas"]
    }
    return {"linhas": linhas}


def _construtivos(construtivos: dict) -> dict:
    """Contagem de elementos por sistema e por classe, a partir da árvore de unidades."""
    por_sistema = {}
    total_por_classe = {}
    for unidade in construtivos["arvore"]:
        for sistema in unidade["sistemas"]:
            contagem = dict(sorted(sistema["classes"].items()))
            por_sistema[sistema["id"]] = contagem
            for classe, n in contagem.items():
                total_por_classe[classe] = total_por_classe.get(classe, 0) + n
    return {
        "por_sistema": dict(sorted(por_sistema.items())),
        "total_por_classe": dict(sorted(total_por_classe.items())),
    }


def _eap_padrao(eap_padrao: dict) -> dict:
    """Situação e textos de quantidade de cada folha do esqueleto padrão, por id."""
    folhas = {}
    for tipo in eap_padrao["tipos"]:
        for etapa in tipo["etapas"]:
            for folha in etapa["folhas"]:
                folhas[folha["id"]] = {
                    "situacao": folha["situacao"],
                    "quantidades_txt": folha["quantidades_txt"],
                }
    return {"folhas": folhas}


def _eap(eap: dict) -> dict:
    """Quantidade e unidade de cada código da EAP codificada, com a grandeza no código da chave.

    O mesmo código pode ter mais de uma grandeza (por exemplo, a quantidade em un e a área em m²), por isso a chave
    é `codigo|grandeza`.
    """
    quantidades = {
        f"{item['codigo']}|{item['grandeza']}": {
            "quantidade": _arredonda(item["quantidade"]),
            "unidade": item["unidade"],
        }
        for item in eap["quantidades"]
    }
    return {"quantidades": quantidades}


def _gavetas(gavetas: dict) -> dict:
    """As contagens de `gavetas`: valores inteiros e dicionários de inteiros. Listas ficam de fora."""
    resumo = {}
    for chave, valor in sorted(gavetas.items()):
        if isinstance(valor, dict):
            resumo[chave] = {k: v for k, v in sorted(valor.items()) if _numero(v)}
        elif _numero(valor):
            resumo[chave] = valor
    return resumo


def extrair(dados: dict) -> dict:
    """Resumo só de quantidades e contagens do dados.json do build, com chaves em ordem estável."""
    return {
        "escavacao": _escavacao(dados["escavacao"]),
        "valas": _valas(dados["valas"]),
        "contrato_211": _contrato_211(dados["contrato_211"]),
        "construtivos": _construtivos(dados["construtivos"]),
        "eap_padrao": _eap_padrao(dados["eap_padrao"]),
        "eap": _eap(dados["eap"]),
        "gavetas": _gavetas(dados["gavetas"]),
    }


def _comparar_no(esperado, atual, caminho: str, tol_abs: float, diferencas: list[str]) -> None:
    """Acumula em `diferencas` o que diverge entre `esperado` e `atual`, percorrendo dicionários e listas."""
    if isinstance(esperado, dict) and isinstance(atual, dict):
        for chave in sorted(set(esperado) | set(atual), key=str):
            sub = f"{caminho}/{chave}"
            if chave not in atual:
                diferencas.append(f"chave ausente: {sub}")
            elif chave not in esperado:
                diferencas.append(f"chave a mais: {sub}")
            else:
                _comparar_no(esperado[chave], atual[chave], sub, tol_abs, diferencas)
        return
    if isinstance(esperado, list) and isinstance(atual, list):
        if len(esperado) != len(atual):
            diferencas.append(f"tamanho da lista diferente em {caminho}: esperado {len(esperado)}, atual {len(atual)}")
        for i, (e, a) in enumerate(zip(esperado, atual)):
            _comparar_no(e, a, f"{caminho}[{i}]", tol_abs, diferencas)
        return
    if _numero(esperado) and _numero(atual):
        if abs(esperado - atual) > tol_abs:
            diferencas.append(
                f"número fora da tolerância em {caminho}: esperado {esperado}, atual {atual} (tol {tol_abs})"
            )
        return
    if esperado != atual or type(esperado) is not type(atual):
        diferencas.append(f"texto ou tipo diferente em {caminho}: esperado {esperado!r}, atual {atual!r}")


def comparar(esperado: dict, atual: dict, tol_abs: float = TOL_ABS_PADRAO) -> list[str]:
    """Diferenças legíveis entre o golden e o resumo atual; lista vazia quando batem.

    Números valem dentro de `tol_abs` (absoluta, na unidade do campo); textos, listas e chaves são exatos.
    """
    diferencas: list[str] = []
    _comparar_no(esperado, atual, "", tol_abs, diferencas)
    return diferencas


def _texto_json(resumo: dict) -> str:
    """JSON com chaves ordenadas e terminação em nova linha, para o mesmo resumo dar os mesmos bytes."""
    return json.dumps(resumo, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def principal(argv: list[str] | None = None) -> int:
    """Grava o golden (com `--gravar`) ou compara o dados.json com ele. Código 1 quando há diferença."""
    parser = argparse.ArgumentParser(description="Golden das quantidades do build (dados.json).")
    parser.add_argument("dados", type=Path, help="dados.json do build, ex.: saida/foz/dados.json")
    parser.add_argument("--gravar", type=Path, help="grava o resumo neste caminho, em vez de comparar")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PADRAO, help="golden usado na comparação")
    parser.add_argument("--tol-abs", type=float, default=TOL_ABS_PADRAO, help="tolerância absoluta dos números")
    args = parser.parse_args(argv)

    atual = extrair(json.loads(args.dados.read_text(encoding="utf-8")))

    if args.gravar:
        args.gravar.parent.mkdir(parents=True, exist_ok=True)
        args.gravar.write_text(_texto_json(atual), encoding="utf-8")
        print(f"golden gravado em {args.gravar} ({len(atual)} seções)")
        return 0

    esperado = json.loads(args.golden.read_text(encoding="utf-8"))
    diferencas = comparar(esperado, atual, args.tol_abs)
    for linha in diferencas:
        print(linha)
    print(f"{len(diferencas)} diferença(s) em relação a {args.golden}")
    return 1 if diferencas else 0


if __name__ == "__main__":
    sys.exit(principal())
