"""Serviços complementares pelas gavetas (F4 da reconstrução, docs/RECONSTRUCAO.md §0 passo 7, §3 F4).

O que a execução do elemento exige e o escopo não traz (forma, armadura, lastro, arrasamento, cava do bloco, vala do
trecho com demolição, escoramento, berço, reaterro, recomposição por pavimento…) sai das regras de
`conceitos/servicos_associados.jsonl`, que já existiam. Aqui elas passam a ler **só** os fatos e a geometria das gavetas
e a gravar nas gavetas:

    gavetas (objetos + fatos + geometria) ─ elementos ─► dimensões (camadas.dimensoes) ─► regras (camadas.associados)
        ─► servicos (codigo_eap = U.SISTEMA.DISC.PAC.ITEM, fatos usados) + evidencias (classe "associado") + pendencias

Dimensão que falta não é suposta: o serviço sai sem valor e a pendência diz o que faltou (cadeia `V ← h ← face`). Sem
preço e sem prazo. O resultado entra nas folhas da EAP única por `camadas.eap_preencher` (situação `calculada`).

    python -m camadas.gavetas_servicos saida/foz

Só lê a base; não grava em `saida/`.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
from shapely import geometry as sg

from . import associados, dimensoes, eap, gavetas, gavetas_construtivos
from .formulas import nomes, premissa

TOLERANCIA = 1e-3
"""Tolerância absoluta da paridade com o `associados.csv` (unidade da própria quantidade)."""
PROPRIEDADE_GEOMETRICA = {
    "area": "area_planta_m2",
    "perimetro": "perimetro_m",
    "comprimento": "comprimento_m",
}
"""Medida geométrica de `dimensoes.json` → propriedade que a extração grava como fato (`gavetas_construtivos._medidas`)."""
CLASSE_PARA_TIPO = dimensoes.REGRAS["construtivos"]
"""Classe do objeto da gaveta → tipo de `dimensoes.json` (estaca, bloco, pilar; o `trecho` vira vala)."""
CLASSE_DO_FURO = "furo_sondagem"
CLASSE_DO_TRECHO = "trecho"


def _mapa_de_dimensoes() -> dict[str, dict[str, tuple[str, float]]]:
    """{tipo: {dimensão: (propriedade da gaveta, fator da propriedade para a dimensão)}}.

    Sai de `dimensoes.json` com os rótulos de `gavetas_construtivos.ROTULOS`, para as duas tabelas não divergirem: a
    dimensão que vem de um atributo passa pelo rótulo (o valor da gaveta já está na unidade da propriedade, e a escala
    da dimensão volta para a unidade dela); a que vem da geometria usa a medida gravada como fato. Dimensão cujo
    atributo não tem rótulo (o lado do pilar) fica de fora e entra em `faltando`, nunca como zero."""
    mapa: dict[str, dict[str, tuple[str, float]]] = {}
    for tipo, spec in dimensoes.TIPOS.items():
        mapa[tipo] = {}
        for nome, origem in spec["dimensoes"].items():
            rotulo = gavetas_construtivos.ROTULOS.get(origem.get("atributo"))
            if rotulo:
                propriedade, fator, _ = rotulo
                mapa[tipo][nome] = (propriedade, origem.get("escala", 1.0) / fator)
            elif origem.get("geometria") in PROPRIEDADE_GEOMETRICA:
                mapa[tipo][nome] = (PROPRIEDADE_GEOMETRICA[origem["geometria"]], 1.0)
    return mapa


MAPA_DE_DIMENSOES = _mapa_de_dimensoes()


def _numero(fato: dict | None) -> bool:
    return (
        fato is not None
        and isinstance(fato["valor"], (int, float))
        and not isinstance(fato["valor"], bool)
    )


def _rastro(
    tipo: str, usados: dict[str, list[str]], pai: dict[str, list[str]] | None = None
) -> dict[str, list[str]]:
    """{dimensão: ids dos fatos de que ela depende}: as dimensões base citam o fato lido (ou o do elemento pai, na
    derivada) e cada cálculo reúne os fatos das dimensões que a fórmula usa. Premissa não tem fato."""
    spec, rastro = dimensoes.TIPOS[tipo], {}
    for nome, origem in spec["dimensoes"].items():
        rastro[nome] = (
            (pai or {}).get(origem["pai"], [])
            if "pai" in origem
            else usados.get(nome, [])
        )
    for nome, expressao in spec["calculos"].items():
        rastro[nome] = sorted({f for n in nomes(expressao) for f in rastro.get(n, [])})
    return rastro


def _unidade_e_sistema(objeto: dict, fatos: dict) -> tuple[str | None, str | None]:
    """(unidade, sistema `u1-ETA`) do objeto, pelo registro ou pelos fatos; None se faltar um dos dois."""
    unidade = objeto.get("unidade") or fatos.get("unidade", {}).get("valor")
    sistema = objeto.get("sistema") or fatos.get("sistema", {}).get("valor")
    if not unidade or not sistema:
        return None, None
    return unidade, sistema if "-" in sistema else f"{unidade}-{sistema}"


def _com_rastro(
    el: dict, objeto_id: str, rastro: dict, chave: str | None = None
) -> dict:
    return {**el, "objeto_id": objeto_id, "rastro": rastro, "chave": chave}


def _elemento_construtivo(
    objeto: dict, fatos: dict, tipo: str, unidade: str, sistema: str
) -> list[dict]:
    """O elemento (estaca, bloco, pilar) e os derivados (cava do bloco), com as dimensões lidas dos fatos."""
    objeto_id = objeto["objeto_id"]
    dados, usados = {}, {}
    for dimensao, (propriedade, fator) in MAPA_DE_DIMENSOES[tipo].items():
        fato = fatos.get(propriedade)
        if _numero(fato):
            dados[dimensao] = float(fato["valor"]) * fator
            usados[dimensao] = [fato["fato_id"]]
    codigos = eap.codigos_do_elemento(
        {"classe": objeto["classe"], "unidade": unidade, "sistema": sistema}
    )
    el = dimensoes.elemento(
        objeto_id,
        tipo,
        f"{unidade.upper()}.{sistema.split('-', 1)[1]}",
        codigos[0].split(".", 2)[2] if codigos else dimensoes.item_do_tipo(tipo),
        dimensoes.dimensionar(tipo, dados=dados),
        f"gavetas: objeto {objeto_id}",
    )
    rastro = _rastro(tipo, usados)
    derivados = dimensoes._derivados(el)
    return [_com_rastro(el, objeto_id, rastro)] + [
        _com_rastro(d, objeto_id, _rastro(d["tipo"], {}, rastro)) for d in derivados
    ]


def _trecho(
    objeto: dict, fatos: dict, geometria: dict | None, eixo_partes: list | None
) -> tuple[dict | None, list[str]]:
    """(trecho no formato de `dimensoes.dimensionar_vala`, motivos do que faltou) a partir dos fatos do objeto.

    Faltou diâmetro, metros ou eixo → sem trecho e com o motivo (a vala não sai). A extensão que as superfícies
    não cobrem vira `sem_ortofoto`, como em `dimensoes.trecho_da_feature`; material ausente segue vazio e a vala
    sai só com o que não depende da largura."""
    motivos = []
    if not _numero(fatos.get("dn_mm")):
        motivos.append("sem diâmetro (dn_mm): a vala não sai")
    pavimentos = fatos.get("pavimentos", {}).get("valor")
    pavimentos = pavimentos if isinstance(pavimentos, dict) else {}
    if not pavimentos and not _numero(fatos.get("extensao_m")):
        motivos.append(
            "sem metros por superfície (pavimentos) nem extensão: a vala não sai"
        )
    if geometria is None or geometria["tipo"] != "linha":
        motivos.append(
            "sem eixo (linha) na geometria: sondagem e superfície não se medem"
        )
    if motivos:
        return None, motivos
    segmentos = {
        c: float(m)
        for c, m in pavimentos.items()
        if c in dimensoes.VALAS["classes"] and isinstance(m, (int, float)) and m > 0
    }
    total = fatos.get("extensao_m", {}).get("valor")
    if isinstance(total, (int, float)) and total - sum(segmentos.values()) > 0.5:
        segmentos["sem_ortofoto"] = round(total - sum(segmentos.values()), 1)
    partes = eixo_partes or [geometria["coords"]]
    eixo = (
        sg.MultiLineString([np.asarray(p, float)[:, :2].tolist() for p in partes])
        if len(partes) > 1
        else sg.LineString(np.asarray(partes[0], float)[:, :2])
    )
    return {
        "id": objeto["objeto_id"],
        "de_mm": float(fatos["dn_mm"]["valor"]),
        "segmentos": segmentos,
        "material_texto": str(fatos.get("material", {}).get("valor") or ""),
        "geometria": eixo,
    }, []


def _elementos_da_vala(
    objeto: dict,
    fatos: dict,
    geometria: dict | None,
    unidade: str,
    sistema: str,
    furos: list[dict],
) -> tuple[list[dict], list[tuple[str, str | None]]]:
    """Um elemento por superfície do trecho (o dimensionador único é `lineares.dimensionar_vala`, via `dimensoes`)."""
    trecho, motivos = _trecho(
        objeto, fatos, geometria, fatos.get("eixo_partes", {}).get("valor")
    )
    if trecho is None:
        return [], [(m, None) for m in motivos]
    usados = [
        fatos[p]["fato_id"]
        for p in ("dn_mm", "pavimentos", "extensao_m", "material", "eixo_partes")
        if p in fatos
    ]
    furo, _ = dimensoes.sondagem_proxima(trecho["geometria"], furos)
    usados += furo["fatos"] if furo else []
    base = f"{unidade.upper()}.{sistema.split('-', 1)[1]}"
    elementos = []
    for superficie, metodo, dims, alertas in dimensoes.dimensionar_vala(trecho, furos):
        el = dimensoes.elemento(
            f"{objeto['objeto_id']} · {superficie} · {metodo}",
            "vala",
            base,
            None,
            dims,
            f"gavetas: objeto {objeto['objeto_id']}",
            alertas,
            metodo,
        )
        rastro = {
            n: sorted(set(usados))
            for n in (*el["dims"], *dimensoes.TIPOS["vala"]["calculos"])
        }
        elementos.append(_com_rastro(el, objeto["objeto_id"], rastro, superficie))
    avisos = sorted({a for e in elementos for a in e["alertas"]})
    return elementos, [(f"vala: {a}", None) for a in avisos]


def _montar(base: dict, epsg: int) -> tuple[list[dict], list[dict]]:
    """(elementos, pendências) de todos os objetos das classes que `dimensoes.json` conhece."""
    ind = gavetas.indice(base)
    furos = [
        f
        for f in gavetas.furos(base, CLASSE_DO_FURO, ind)
        if f["E"] is not None and f["N"] is not None
    ]
    elementos, pendencias = [], []

    def pendencia(objeto_id: str, motivo: str, detalhe: str | None = None) -> None:
        pendencias.append(
            {
                "objeto_id": objeto_id,
                "motivo": motivo,
                **({"detalhe": detalhe} if detalhe else {}),
            }
        )

    for objeto in base["objetos"]:
        tipo = CLASSE_PARA_TIPO.get(objeto["classe"])
        if tipo is None:
            continue
        objeto_id = objeto["objeto_id"]
        fatos = gavetas.fatos_de_codigo(base, objeto_id, ind)
        unidade, sistema = _unidade_e_sistema(objeto, fatos)
        if not unidade:
            pendencia(
                objeto_id, "unidade e sistema não definidos: sem serviço complementar"
            )
            continue
        geometria = ind["geometria"].get(objeto_id)
        if geometria and geometria.get("crs_h") not in (None, f"EPSG:{epsg}"):
            pendencia(
                objeto_id,
                "geometria fora do CRS da obra: sem serviço complementar",
                f"{geometria.get('crs_h')} no lugar de EPSG:{epsg}",
            )
            continue
        if tipo == "vala":
            novos, avisos = _elementos_da_vala(
                objeto, fatos, geometria, unidade, sistema, furos
            )
            elementos += novos
            for motivo, detalhe in avisos:
                pendencia(objeto_id, motivo, detalhe)
        else:
            elementos += _elemento_construtivo(objeto, fatos, tipo, unidade, sistema)
    return elementos, pendencias


def elementos(base: dict, epsg: int) -> list[dict]:
    """Os elementos no formato que `associados.aplicar` espera, montados só dos fatos e da geometria das gavetas.

    Estaca, bloco e pilar pelas dimensões padronizadas de `dimensoes.json` (propriedade da gaveta → dimensão em
    `MAPA_DE_DIMENSOES`) e as derivações (bloco → cava de fundação); trecho → vala, um elemento por superfície, pelo
    dimensionador único com as sondagens da própria base. Cada elemento traz também `objeto_id` (o objeto da gaveta),
    `rastro` ({dimensão: ids dos fatos}) e `chave` (a superfície da vala). Dimensão sem fato fica em `faltando`."""
    return _montar(base, epsg)[0]


# --------------------------------------------------------------------------------------------------------------------
# regras → serviços, evidências e pendências
# --------------------------------------------------------------------------------------------------------------------


def versao_da_regra(regra: dict) -> str:
    """Hash curto (sha1, 12 hex) do JSON da regra: mudou a fórmula, a premissa ou o destino, mudou a versão."""
    corpo = json.dumps(regra, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha1(corpo, usedforsecurity=False).hexdigest()[:12]


VERSOES = {r["id"]: versao_da_regra(r) for r in associados.REGRAS}
POR_ID = {r["id"]: r for r in associados.REGRAS}


def _premissas(regra: dict, el: dict) -> list[str]:
    """Premissas citadas no cálculo: as da regra (com estado e fonte) e as das dimensões do elemento."""
    citadas = []
    for nome, p in regra.get("premissas", {}).items():
        valor = premissa(p, el["tipo"])
        citadas.append(
            f"{nome} = {valor} {p.get('unidade', '')}".rstrip()
            + f" ({p.get('estado', 'premissa')}: {p.get('fonte', p.get('ref', ''))})"
        )
    return citadas + [m for m in el["memoria"] if "(premissa:" in m]


def _falta(texto: str) -> str:
    """A cadeia do que faltou de 'elemento (falta V ← h ← face)'."""
    achado = re.search(r"\(falta (.*)\)$", texto)
    return achado.group(1) if achado else texto


def _identificadores(grupos: list[tuple]) -> list[str]:
    """`<objeto_id>.<regra>`; quando o objeto tem mais de um destino na mesma regra (as superfícies da vala, a
    recomposição de pista e de calçada), acrescenta a superfície, o serviço e o item até desfazer a repetição."""
    por_base = Counter(f"{g[0]}.{g[1]}" for g in grupos)
    ids = []
    for objeto_id, regra, chave, codigo, saida in grupos:
        base = f"{objeto_id}.{regra}"
        if por_base[base] > 1:
            base += f".{chave}" if chave else ""
        ids.append(base)
    repetidos = Counter(ids)
    ids = [
        i if repetidos[i] == 1 else f"{i}.{g[4]}"
        for i, g in zip(ids, grupos, strict=True)
    ]
    repetidos = Counter(ids)
    return [
        i if repetidos[i] == 1 else f"{i}.{g[3]}"
        for i, g in zip(ids, grupos, strict=True)
    ]


def complementares(base: dict, epsg: int) -> dict:
    """Aplica as regras de `servicos_associados.jsonl` aos elementos das gavetas.

    Devolve {servicos, evidencias, pendencias, resumo} nos formatos das gavetas (`conceitos/gavetas.json`):
    - `servicos`: `servico_id` = `<objeto_id>.<regra>`, `regra` = `associado:<id>`, `versao_regra` (hash da regra),
      `saida` (o serviço; a regra sem serviço usa o id da regra), `valor`, `unidade`, `fatos` (ids dos fatos de que o
      valor depende), `codigo_eap` (item técnico completo `U.SISTEMA.DISC.PAC.ITEM`; None se o item não existe na EAP
      instanciada), `servicos_eap` ([serviço], para casar com o `aponta.servico` do modelo), `chave` (superfície da
      vala) e `evidencia_id`;
    - `evidencias`: classe `associado`, com a memória de cálculo no `trecho` e as `premissas` citadas;
    - `pendencias`: o que faltou (dimensão que não existe nas gavetas, objeto sem unidade e sistema, código fora da EAP).
    Sem dimensão o serviço não sai (nunca zero inventado). A base devolvida por `com_complementares` passa em
    `gavetas.conferir_base`."""
    elementos_, pendencias = _montar(base, epsg)
    validos = {n["codigo"] for n in eap.estrutura() if n["nivel"] == "item"}
    grupos: dict[tuple, dict] = {}
    for el in elementos_:
        evs, sem_valor, _ = associados.aplicar([el])
        for regra, textos in sem_valor.items():
            pendencias += [
                {
                    "objeto_id": el["objeto_id"],
                    "motivo": f"serviço sem valor: {regra}",
                    "detalhe": f"falta {_falta(t)} ({el['id']})",
                }
                for t in textos
            ]
        for ev in evs:
            regra = POR_ID[ev["regra"]]
            chave = (
                el["objeto_id"],
                ev["regra"],
                el["chave"],
                ev["codigo"],
                ev["servico"] or ev["regra"],
            )
            usados = sorted(
                {
                    f
                    for n in nomes(regra["formula"])
                    + nomes(regra.get("condicao") or "1")
                    for f in el["rastro"].get(n, [])
                }
            )
            g = grupos.setdefault(
                chave,
                {
                    "valor": 0.0,
                    "fatos": set(),
                    "trechos": [],
                    "premissas": [],
                    "documento": ev["documento"]["id"],
                    "servico": ev["servico"],
                    "unidade": ev["unidade"],
                },
            )
            g["valor"] += ev["valor"]
            g["fatos"] |= set(usados)
            g["trechos"].append(ev["trecho"])
            g["premissas"] += [
                p for p in _premissas(regra, el) if p not in g["premissas"]
            ]
    chaves = sorted(grupos)
    servicos, evidencias = [], []
    for sid, chave in zip(_identificadores(chaves), chaves, strict=True):
        objeto_id, regra_id, superficie, codigo, saida = chave
        g = grupos[chave]
        evidencia_id = f"EV-AS-{sid}"
        valido = codigo if codigo in validos else None
        if valido is None:
            pendencias.append(
                {
                    "objeto_id": objeto_id,
                    "motivo": "código fora da EAP instanciada: serviço sem codigo_eap",
                    "detalhe": codigo,
                }
            )
        servicos.append(
            {
                "servico_id": sid,
                "objeto_id": objeto_id,
                "regra": f"associado:{regra_id}",
                "versao_regra": VERSOES[regra_id],
                "saida": saida,
                "valor": round(g["valor"], 6),
                "unidade": g["unidade"],
                "fatos": sorted(g["fatos"]),
                "codigo_eap": valido,
                "servicos_eap": [g["servico"]] if g["servico"] else [],
                **({"chave": superficie} if superficie else {}),
                "evidencia_id": evidencia_id,
            }
        )
        evidencias.append(
            {
                "evidencia_id": evidencia_id,
                "classe": "associado",
                "documento": g["documento"],
                "localizador": {"regra": regra_id, "objeto_id": objeto_id},
                "trecho": " | ".join(g["trechos"]),
                "metodo": "camadas.associados",
                "executor": "código",
                "premissas": g["premissas"],
            }
        )
    return {
        "servicos": servicos,
        "evidencias": evidencias,
        "pendencias": pendencias,
        "resumo": _resumo(servicos, pendencias),
    }


def _somar(base: dict, c: dict) -> dict:
    """Cópia da base com os servicos, evidencias e pendencias de `c` (resultado de `complementares`) somados."""
    nova = {g: list(base.get(g, [])) for g in gavetas.GAVETAS}
    for gaveta in ("servicos", "evidencias", "pendencias"):
        nova[gaveta] += c[gaveta]
    return nova


def com_complementares(base: dict, epsg: int) -> tuple[dict, list[str]]:
    """(base com os serviços, evidências e pendências somados, erros de `gavetas.conferir_base`). Não altera a original."""
    nova = _somar(base, complementares(base, epsg))
    return nova, gavetas.conferir_base(nova)


def _resumo(servicos: list[dict], pendencias: list[dict]) -> dict:
    return {
        "servicos": len(servicos),
        "por_regra": dict(sorted(Counter(s["regra"] for s in servicos).items())),
        "sem_codigo_eap": sum(s["codigo_eap"] is None for s in servicos),
        "pendencias": len(pendencias),
        "pendencias_por_motivo": dict(
            Counter(p["motivo"] for p in pendencias).most_common()
        ),
    }


# --------------------------------------------------------------------------------------------------------------------
# paridade com o caminho atual (associados.csv)
# --------------------------------------------------------------------------------------------------------------------


def somas(servicos: list[dict]) -> dict[tuple, float]:
    """{(unidade, item, serviço, unidade de medida): soma} dos serviços com `codigo_eap`, como o `associados.csv`."""
    saida: dict[tuple, float] = {}
    for s in servicos:
        if not s.get("codigo_eap"):
            continue
        unidade, _, item = s["codigo_eap"].split(".", 2)
        servico = (s.get("servicos_eap") or [""])[0]
        chave = (unidade, item, servico, s["unidade"])
        saida[chave] = saida.get(chave, 0.0) + float(s["valor"])
    return saida


def ler_associados(caminho) -> dict[tuple, float]:
    """{(unidade, item, serviço, unidade de medida): quantidade} do `associados.csv` (`;`, vírgula decimal, com BOM)."""
    with open(caminho, encoding="utf-8-sig", newline="") as arquivo:
        linhas = list(csv.DictReader(arquivo, delimiter=";"))
    saida: dict[tuple, float] = {}
    for r in linhas:
        chave = (r["unidade"], r["item"], r["servico"], r["unidade_medida"])
        saida[chave] = saida.get(chave, 0.0) + float(r["quantidade"].replace(",", "."))
    return saida


def paridade(servicos: list[dict], associados_csv) -> list[str]:
    """Diferenças entre as gavetas e o `associados.csv` do caminho atual, somando por (unidade, item, serviço, unidade
    de medida) com tolerância absoluta `TOLERANCIA`. Vazio = paridade. Cada linha do csv tem de sair igual; linha só das
    gavetas também é diferença."""
    esperado, obtido = ler_associados(associados_csv), somas(servicos)
    problemas = []
    for chave in sorted(esperado.keys() | obtido.keys()):
        rotulo = "/".join(chave)
        if chave not in obtido:
            problemas.append(f"{rotulo}: falta nas gavetas (csv {esperado[chave]:.3f})")
        elif chave not in esperado:
            problemas.append(f"{rotulo}: só nas gavetas ({obtido[chave]:.3f})")
        elif abs(obtido[chave] - esperado[chave]) > TOLERANCIA:
            problemas.append(
                f"{rotulo}: gavetas {obtido[chave]:.3f} × csv {esperado[chave]:.3f} "
                f"(diferença {obtido[chave] - esperado[chave]:+.3f})"
            )
    return problemas


def _pasta_da_base(caminho: str) -> Path:
    """`saida/foz` ou `saida/foz/base`: a pasta com as gavetas."""
    pasta = Path(caminho)
    return pasta / "base" if (pasta / "base").is_dir() else pasta


def _epsg_da_base(base: dict, pasta: Path) -> int:
    """EPSG da obra: `crs.epsg` do `dados.json` ao lado da base; sem ele, o CRS único da geometria dos objetos que viram
    elemento (a base de Foz tem sondagens em outra zona). ValueError se não houver um só."""
    dados = pasta.parent / "dados.json"
    if dados.exists():
        return int(json.loads(dados.read_text(encoding="utf-8"))["crs"]["epsg"])
    classes = {
        o["objeto_id"] for o in base["objetos"] if o["classe"] in CLASSE_PARA_TIPO
    }
    crs = {g["crs_h"] for g in base["geometria"] if g["objeto_id"] in classes}
    if len(crs) != 1:
        raise ValueError(
            f"a geometria dos elementos precisa de um CRS só; achei {sorted(crs)}"
        )
    return int(crs.pop().split(":")[1])


def _imprimir_completude(base: dict) -> None:
    """A completude da EAP única com os complementares nas gavetas (folhas por situação, por tipo de obra)."""
    from . import eap_preencher

    for tipo, v in eap_preencher.preencher(base)["completude"].items():
        print(
            f"EAP {tipo}: {v['preenchida']} preenchidas, {v['calculada']} calculadas, {v['declarada']} declaradas, "
            f"{v['a preencher']} a preencher de {v['folhas']} folhas"
        )


def principal(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("obra", help="saida/<obra> (ou a pasta base/ com as gavetas)")
    p.add_argument("--associados", help="associados.csv (padrão: o da pasta da obra)")
    a = p.parse_args(argv)
    pasta = _pasta_da_base(a.obra)
    base = gavetas.ler(pasta)
    epsg = _epsg_da_base(base, pasta)
    resultado = complementares(base, epsg)
    nova = _somar(base, resultado)
    erros = gavetas.conferir_base(nova)
    r = resultado["resumo"]
    print(
        f"{r['servicos']} serviços complementares ({r['sem_codigo_eap']} sem codigo_eap), {r['pendencias']} pendências"
    )
    for regra, n in r["por_regra"].items():
        print(f"  {regra:42} {n}")
    for motivo, n in r["pendencias_por_motivo"].items():
        print(f"  pendência ({n}): {motivo}")
    print(f"conferência das gavetas: {len(erros)} erros")
    for e in erros[:20]:
        print("  ERRO", e)
    _imprimir_completude(nova)
    csv_associados = (
        Path(a.associados) if a.associados else pasta.parent / "associados.csv"
    )
    if not csv_associados.exists():
        print(f"sem {csv_associados}: paridade não conferida")
        return 1 if erros else 0
    diferencas = paridade(resultado["servicos"], csv_associados)
    total = len(ler_associados(csv_associados))
    so_nas_gavetas = sum("só nas gavetas" in d for d in diferencas)
    batem = total - (len(diferencas) - so_nas_gavetas)
    print(
        f"paridade com {csv_associados.name}: {batem} de {total} linhas batem; {so_nas_gavetas} só nas gavetas"
    )
    for d in diferencas:
        print("  DIFERE", d)
    return 1 if diferencas or erros else 0


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "gavetas_servicos",
        "descricao": "serviços complementares (forma, armadura, lastro, arrasamento, cava, vala, demolição, escoramento, "
        "recomposição…) calculados pelas regras de servicos_associados.jsonl só dos fatos e da geometria das gavetas, "
        "gravados em servicos/evidencias/pendencias, com paridade contra o associados.csv",
        "funcoes": [
            "elementos",
            "complementares",
            "com_complementares",
            "paridade",
            "metadados",
        ],
        "conceitos": ["servicos_associados.jsonl", "dimensoes.json", "gavetas.json"],
        "tolerancia_paridade": TOLERANCIA,
        "mapa_de_dimensoes": {t: sorted(m) for t, m in MAPA_DE_DIMENSOES.items() if m},
    }


if __name__ == "__main__":
    raise SystemExit(principal())
