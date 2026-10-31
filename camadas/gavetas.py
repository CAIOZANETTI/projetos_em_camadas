"""Gavetas da memória espacial: cada fato extraído tem um lugar, com evidência; os serviços saem só dessas gavetas.

O fluxo é o de `docs/MEMORIA_ESPACIAL.md`, com os três de-para em `conceitos/`:

1. **documento → gaveta** (`de_para_extracao.json`): o que cada leitor pode gravar;
2. **gaveta → serviço** (`de_para_servicos.json`): de quais fatos cada regra depende;
3. **serviço → EAP** (`de_para_eap.json`): em que nó cada quantidade entra.

O contrato das gavetas (`gavetas.json`) é lógico. O formato físico é experimento: `gravar` e `ler` aceitam os
formatos de `formato.implementados`, e o resto do código não muda com a troca. A base em memória é um dict
`{gaveta: [registros]}`.

    python -m camadas.gavetas saida/<obra>/base      # confere a base e calcula os serviços
"""
from __future__ import annotations

import argparse
import csv
import importlib
import json
from pathlib import Path

import numpy as np

from . import obras_lineares as ol
from .pdf_cad import CONCEITOS


def _ler(nome: str) -> dict:
    return json.loads((CONCEITOS / f"{nome}.json").read_text(encoding="utf-8"))


REGRAS = _ler("gavetas")
EXTRACAO = _ler("de_para_extracao")
SERVICOS = _ler("de_para_servicos")
EAP = _ler("de_para_eap")
GAVETAS = list(REGRAS["gavetas"])


# --------------------------------------------------------------------------------------------------------------------
# Conferência: base e de-para
# --------------------------------------------------------------------------------------------------------------------

def validar(gaveta: str, registro: dict) -> list[str]:
    """Campos obrigatórios e valores permitidos de um registro."""
    g = REGRAS["gavetas"].get(gaveta)
    if g is None:
        return [f"gaveta {gaveta} não existe em conceitos/gavetas.json"]
    rotulo = registro.get(g["chave"]) if g["chave"] else registro.get("objeto_id")
    erros = [f"{gaveta} {rotulo}: falta {c}" for c in g["obrigatorios"] if registro.get(c) in (None, "")]
    regras = {("fatos", "natureza"): REGRAS["naturezas"], ("fatos", "propriedade"): list(REGRAS["propriedades"]),
              ("evidencias", "executor"): REGRAS["executores"], ("geometria", "tipo"): REGRAS["tipos_geometria"]}
    for (gav, campo), permitidos in regras.items():
        if gav == gaveta and registro.get(campo) not in (None, "") and registro[campo] not in permitidos:
            erros.append(f"{gaveta} {rotulo}: {campo} '{registro[campo]}' fora de {permitidos}")
    return erros


def conferir_base(base: dict) -> list[str]:
    """Todo registro válido; todo fato aponta para objeto e evidência existentes; chave sem repetição."""
    erros = [e for gav in GAVETAS for r in base.get(gav, []) for e in validar(gav, r)]
    erros += [f"gaveta {g} não existe em conceitos/gavetas.json" for g in base if g not in REGRAS["gavetas"]]
    objetos = {o["objeto_id"] for o in base.get("objetos", [])}
    evidencias = {e["evidencia_id"] for e in base.get("evidencias", [])}
    for f in base.get("fatos", []):
        if f.get("objeto_id") not in objetos:
            erros.append(f"fatos {f.get('fato_id')}: objeto {f.get('objeto_id')} não está em objetos")
        if f.get("evidencia_id") and f["evidencia_id"] not in evidencias:
            erros.append(f"fatos {f.get('fato_id')}: evidência {f['evidencia_id']} não existe")
    for gav, g in REGRAS["gavetas"].items():
        ids = [r.get(g["chave"]) for r in base.get(gav, [])] if g["chave"] else []
        erros += [f"{gav}: {g['chave']} {i} repetido" for i in sorted({i for i in ids if ids.count(i) > 1})]
    return erros


def conferir_de_para() -> list[str]:
    """Os três de-para só citam propriedades, gavetas, funções e nós que existem."""
    props = set(REGRAS["propriedades"])
    erros = [f"de_para_extracao: propriedade {p} não existe" for e in EXTRACAO["entradas"]
             for p in e["propriedades"] if p not in props]
    for nome, r in SERVICOS["regras"].items():
        erros += [f"de_para_servicos.{nome}: propriedade {p} não existe" for p in r["exige"] + r["opcionais"]
                  if p not in props]
        erros += [f"de_para_servicos.{nome}: saída {s} sem nó em de_para_eap" for s in r["saidas"]
                  if s not in EAP["saidas"]]
        modulo, _, funcao = r["funcao"].rpartition(".")
        if not hasattr(importlib.import_module(modulo), funcao):
            erros.append(f"de_para_servicos.{nome}: função {r['funcao']} não existe")
        objetos = {e["objeto"] for e in EXTRACAO["entradas"]}
        erros += [f"de_para_servicos.{nome}: nenhum leitor grava o objeto {o}"
                  for o in (r["objeto"], r.get("sondagens")) if o and o not in objetos]
    return erros


# --------------------------------------------------------------------------------------------------------------------
# Formato físico (experimento G05): o mesmo contrato em qualquer formato
# --------------------------------------------------------------------------------------------------------------------

def gravar(pasta, base: dict, formato: str | None = None) -> list[Path]:
    """Uma gaveta por arquivo: `<gaveta>.jsonl` (um registro por linha) ou `<gaveta>.csv` (célula em JSON)."""
    formato = formato or REGRAS["formato"]["atual"]
    if formato not in REGRAS["formato"]["implementados"]:
        raise ValueError(f"formato {formato} não implementado: {REGRAS['formato']['implementados']}")
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    feitos = []
    for gav in GAVETAS:
        regs, arq = base.get(gav, []), pasta / f"{gav}.{formato}"
        if formato == "jsonl":
            arq.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in regs), encoding="utf-8")
        else:
            colunas = list(dict.fromkeys(k for r in regs for k in r))
            with open(arq, "w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(colunas)
                w.writerows([[json.dumps(r.get(c), ensure_ascii=False) for c in colunas] for r in regs])
        feitos.append(arq)
    return feitos


def ler(pasta, formato: str | None = None) -> dict:
    """A base gravada por `gravar`; gaveta sem arquivo volta vazia."""
    formato = formato or REGRAS["formato"]["atual"]
    base = {}
    for gav in GAVETAS:
        arq = Path(pasta) / f"{gav}.{formato}"
        if not arq.exists():
            base[gav] = []
        elif formato == "jsonl":
            base[gav] = [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines() if l.strip()]
        else:
            with open(arq, newline="", encoding="utf-8") as fh:
                linhas = list(csv.reader(fh, delimiter=";"))
            base[gav] = [{c: json.loads(v) for c, v in zip(linhas[0], l) if json.loads(v) is not None}
                         for l in linhas[1:]]
    return base


# --------------------------------------------------------------------------------------------------------------------
# Da gaveta ao serviço (de-para 2)
# --------------------------------------------------------------------------------------------------------------------

def fatos_do_objeto(base: dict, objeto_id: str) -> dict[str, dict]:
    """Um fato por propriedade: a natureza mais forte vence (decidido > observado > projetado > inferido)."""
    ordem = {n: i for i, n in enumerate(REGRAS["prioridade_natureza"])}
    escolhidos: dict[str, dict] = {}
    for f in base.get("fatos", []):
        if f["objeto_id"] != objeto_id:
            continue
        atual = escolhidos.get(f["propriedade"])
        if atual is None or ordem[f["natureza"]] <= ordem[atual["natureza"]]:
            escolhidos[f["propriedade"]] = f
    return escolhidos


def _geometria(base: dict, objeto_id: str) -> dict | None:
    return next((g for g in base.get("geometria", []) if g["objeto_id"] == objeto_id), None)


def furos(base: dict, classe: str) -> list[dict]:
    """Sondagens colocadas no local: objetos da classe com geometria de ponto, no formato de `obras_lineares`."""
    saida = []
    for o in base.get("objetos", []):
        g = _geometria(base, o["objeto_id"])
        if o["classe"] != classe or not g or g["tipo"] != "ponto":
            continue
        fatos = fatos_do_objeto(base, o["objeto_id"])
        saida.append({"id": o["objeto_id"], "E": g["coords"][0], "N": g["coords"][1],
                      "na_m": fatos.get("na_m", {}).get("valor"), "camadas": fatos.get("camadas", {}).get("valor", []),
                      "fatos": [f["fato_id"] for f in fatos.values()]})
    return saida


def eixo(geometria: dict | None, passo_m: float = 1.0) -> np.ndarray | None:
    """Pontos do eixo a cada `passo_m` (meio de cada metro), em UTM; None sem linha."""
    if not geometria or geometria["tipo"] != "linha" or len(geometria["coords"]) < 2:
        return None
    xy = np.asarray(geometria["coords"], float)[:, :2]
    acum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))])
    s = np.arange(passo_m / 2, acum[-1], passo_m)
    return np.column_stack([np.interp(s, acum, xy[:, 0]), np.interp(s, acum, xy[:, 1])])


def regra_de(classe: str, fatos: dict) -> str | None:
    """A regra do objeto pelo fato `metodo` (`quando`); sem o fato, a primeira regra da classe."""
    candidatas = [n for n, r in SERVICOS["regras"].items() if r["objeto"] == classe]
    metodo = ol.norm(fatos.get("metodo", {}).get("valor") or "")
    casou = [n for n in candidatas if metodo and ol.norm(SERVICOS["regras"][n]["quando"]["metodo"]) == metodo]
    return (casou or candidatas or [None])[0]


def entrada(base: dict, objeto: dict) -> dict:
    """Tudo o que a regra precisa, lido só das gavetas: dados, furos, eixo, fatos usados e o que falta."""
    fatos = fatos_do_objeto(base, objeto["objeto_id"])
    nome = regra_de(objeto["classe"], fatos)
    if nome is None:
        return {"regra": None}
    r = SERVICOS["regras"][nome]
    usados = [p for p in r["exige"] + r["opcionais"] if p in fatos]
    pts = eixo(_geometria(base, objeto["objeto_id"]))
    fs = furos(base, r["sondagens"]) if r.get("sondagens") else []
    perto = set(ol.furo_por_metro(pts, fs)) if pts is not None and fs else set()
    return {"regra": nome, "dados": {"local": objeto["objeto_id"], **{p: fatos[p]["valor"] for p in usados}},
            "furos": fs, "pts": pts, "faltam": [p for p in r["exige"] if p not in fatos],
            "fatos": [fatos[p]["fato_id"] for p in usados] + [i for f in fs if f["id"] in perto for i in f["fatos"]]}


def _servicos(objeto_id: str, nome: str, q: dict, fatos: list[str]) -> list[dict]:
    """Uma linha por saída da regra (dicionário abre uma linha por chave), com a memória de cálculo."""
    r, linhas = SERVICOS["regras"][nome], []
    for saida in r["saidas"]:
        valor = q.get(saida)
        partes = valor.items() if isinstance(valor, dict) else [(None, valor)]
        for chave, v in partes:
            if v is None:
                continue
            sid = ":".join(x for x in (objeto_id, nome, saida, chave) if x)
            linhas.append({"servico_id": sid, "objeto_id": objeto_id, "regra": nome, "versao_regra": r["versao"],
                           "saida": saida, **({"chave": chave} if chave else {}), "valor": v, "unidade": EAP["saidas"][saida]["unidade"],
                           "fatos": fatos})
    return linhas


def calcular(base: dict) -> tuple[list[dict], list[dict]]:
    """Serviços de todos os objetos com regra; faltou fato obrigatório: pendência e nenhum serviço do objeto."""
    servicos, pendencias = [], []
    for o in base.get("objetos", []):
        e = entrada(base, o)
        if e["regra"] is None:
            continue
        if e["faltam"]:
            pendencias.append({"objeto_id": o["objeto_id"], "regra": e["regra"],
                               "motivo": "faltam fatos obrigatórios: " + ", ".join(e["faltam"])})
            continue
        modulo, _, funcao = SERVICOS["regras"][e["regra"]]["funcao"].rpartition(".")
        q = getattr(importlib.import_module(modulo), funcao)(e["dados"], e["furos"], e["pts"])
        servicos += _servicos(o["objeto_id"], e["regra"], q, e["fatos"])
        pendencias += [{"objeto_id": o["objeto_id"], "regra": e["regra"], "motivo": a} for a in q.get("alertas", [])]
    return servicos, pendencias


# --------------------------------------------------------------------------------------------------------------------
# Do serviço à EAP (de-para 3)
# --------------------------------------------------------------------------------------------------------------------

def para_eap(servicos: list[dict]) -> list[dict]:
    """Soma por nó da EAP, com os serviços e objetos que a lastreiam (o caminho de volta até a evidência)."""
    nos: dict[str, dict] = {}
    for s in servicos:
        n = EAP["saidas"][s["saida"]]
        cod = f"{n['eap']}.{s['chave']}" if s.get("chave") else n["eap"]
        no = nos.setdefault(cod, {"eap": cod, "descricao": n["descricao"] + (f" — {s['chave']}" if s.get("chave") else ""),
                                  "unidade": n["unidade"], "valor": 0.0, "servicos": [], "objetos": []})
        no["valor"] = round(no["valor"] + s["valor"], 3)
        no["servicos"].append(s["servico_id"])
        no["objetos"] = list(dict.fromkeys(no["objetos"] + [s["objeto_id"]]))
    return [nos[k] for k in sorted(nos)]


def metadados() -> dict:
    """Rastreabilidade do método e das constantes (regra 9 do estilo)."""
    return {
        "modulo": "gavetas",
        "descricao": "memória espacial: gavetas com evidência, serviços calculados só a partir delas e EAP lastreada",
        "funcoes": ["validar", "conferir_base", "conferir_de_para", "gravar", "ler", "fatos_do_objeto", "furos",
                    "eixo", "regra_de", "entrada", "calcular", "para_eap"],
        "conceitos": ["gavetas.json", "de_para_extracao.json", "de_para_servicos.json", "de_para_eap.json"],
        "formato": REGRAS["formato"]["atual"],
        "estado": REGRAS["metadata"]["estado"],
    }


def principal(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("pasta")
    p.add_argument("--formato", default=None)
    a = p.parse_args(argv)
    base = ler(a.pasta, a.formato)
    erros = conferir_base(base) + conferir_de_para()
    for e in erros:
        print("ERRO", e)
    servicos, pendencias = calcular(base)
    gravar(a.pasta, {**base, "servicos": servicos, "pendencias": base.get("pendencias", []) + pendencias}, a.formato)
    for no in para_eap(servicos):
        print(f"{no['eap']:<16} {no['descricao']:<55} {no['valor']:>12.3f} {no['unidade']}")
    print(f"{len(servicos)} serviços, {len(pendencias)} pendências, {len(erros)} erros")


if __name__ == "__main__":
    principal()
