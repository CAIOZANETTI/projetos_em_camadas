"""Leitores → gavetas: transforma o que os leitores já extraem em objetos, fatos e evidências da memória espacial.

Cada função devolve uma base `{gaveta: [registros]}` (contrato em `conceitos/gavetas.json`). Valor ausente (None ou
vazio) não vira fato: a falta aparece como pendência no cálculo, nada é inventado. As propriedades de cada entrada
vêm do de-para 1 (`conceitos/de_para_extracao.json`), não de uma lista copiada aqui.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

from . import eap_html, escavacao, extracao, gavetas, valas
from . import obras_lineares as ol

OBSERVADAS_NA_PLANILHA = ("na_m", "solo")      # transcritas do laudo para a planilha


def _vazio(valor) -> bool:
    """None, texto vazio, dicionário ou lista vazios não são fato."""
    return valor is None or (isinstance(valor, (str, dict, list)) and len(valor) == 0)


def _propriedades(vista: str) -> list[str]:
    """Propriedades permitidas pelo de-para 1 para a vista dada."""
    entrada = next(e for e in gavetas.EXTRACAO["entradas"] if e["vista"] == vista)
    return entrada["propriedades"]


def _base_vazia() -> dict:
    """Apelido de `gavetas.base_vazia` (os testes importam este nome)."""
    return gavetas.base_vazia()


def _fato(objeto_id: str, propriedade: str, valor, natureza: str, evidencia_id: str) -> dict:
    """A decisão tem id próprio (`.decidido`): convive com o fato da planilha e vence pela natureza."""
    sufixo = ".decidido" if natureza == "decidido" else ""
    return {"fato_id": f"{objeto_id}.{propriedade}{sufixo}", "objeto_id": objeto_id, "propriedade": propriedade,
            "valor": valor, "natureza": natureza, "evidencia_id": evidencia_id}


def _inventado(trecho: dict, propriedade: str, valor) -> bool:
    """Valor que o leitor pôs no lugar de uma célula vazia (comp 0, método VCA, supressão 0, material 'None')."""
    if propriedade == "comp_m":
        return not valor
    if propriedade == "metodo":
        return "metodo_lido" in trecho and _vazio(trecho["metodo_lido"])
    if propriedade == "supressao_frac":
        return not trecho.get("supressao_lida", True)
    return propriedade == "material" and str(valor).strip() in ("None", "")


def de_obras_lineares(trechos: list[dict], documento: str, aba: str = "Obras Lineares") -> dict:
    """Trechos de `ler_obras_lineares` → objetos `trecho_tubo` `OL-<linha>`, fatos e evidência (aba e linha)."""
    base = _base_vazia()
    propriedades = _propriedades("aba Obras Lineares")
    for trecho in trechos:
        linha = trecho["linha"]
        objeto_id, evidencia_id = f"OL-{linha:03d}", f"EV-OL-{linha}"
        base["objetos"].append({"objeto_id": objeto_id, "classe": "trecho_tubo"})
        base["evidencias"].append({
            "evidencia_id": evidencia_id, "classe": "planilha", "documento": documento,
            "localizador": {"aba": aba, "linha": linha}, "trecho": trecho.get("local"), "metodo": "planilha",
            "executor": "código"})
        for propriedade in propriedades:
            valor = trecho.get(propriedade)
            if _vazio(valor) or _inventado(trecho, propriedade, valor):
                continue
            natureza = "observado" if propriedade in OBSERVADAS_NA_PLANILHA else "projetado"
            base["fatos"].append(_fato(objeto_id, propriedade, valor, natureza, evidencia_id))
    return base


def de_sondagens(furos: list[dict], documento: str, executor: str = "código", crs_h: str = "EPSG:31982") -> dict:
    """Furos de `ler_furos` → objetos `furo_sondagem`; ponto só com E e N, senão pendência."""
    base = _base_vazia()
    propriedades = _propriedades("sondagem SPT")
    for furo in furos:
        objeto_id = str(furo["id"])
        evidencia_id = f"EV-{objeto_id}"
        base["objetos"].append({"objeto_id": objeto_id, "classe": "furo_sondagem"})
        base["evidencias"].append({
            "evidencia_id": evidencia_id, "classe": "laudo", "documento": documento,
            "localizador": {"arquivo": documento, "furo": objeto_id}, "metodo": "json", "executor": executor})
        if furo.get("E") is not None and furo.get("N") is not None:
            base["geometria"].append({"objeto_id": objeto_id, "tipo": "ponto", "coords": [furo["E"], furo["N"]],
                                      "crs_h": crs_h, "datum_v": "ortométrico"})
        else:
            base["pendencias"].append({"objeto_id": objeto_id,
                                       "motivo": "furo sem coordenadas: entra só pelo nome citado na planilha, não pela posição no eixo"})
        for propriedade in propriedades:
            if not _vazio(furo.get(propriedade)):
                base["fatos"].append(_fato(objeto_id, propriedade, furo[propriedade], "observado", evidencia_id))
    return base


def de_decisoes(metodo_por_local: dict, trechos: list[dict], documento: str) -> dict:
    """Escolha `{local: "MND"}` do obra.json → fato `metodo` `decidido` em todo trecho de mesmo `local` (sem acento/caixa)."""
    base = _base_vazia()
    for local, metodo in metodo_por_local.items():
        casados = [t for t in trechos if ol.norm(t["local"]) == ol.norm(local)]
        if not casados:
            base["pendencias"].append({"objeto_id": str(local),
                                       "motivo": f"decisão de método '{metodo}' sem trecho de mesmo local na planilha"})
        for trecho in casados:
            objeto_id, evidencia_id = f"OL-{trecho['linha']:03d}", f"EV-DEC-{trecho['linha']}"
            base["evidencias"].append({
                "evidencia_id": evidencia_id, "classe": "decisao", "documento": documento,
                "localizador": {"arquivo": documento, "chave": "obras_lineares.metodo"}, "trecho": local,
                "metodo": "decisão", "executor": "você"})
            base["fatos"].append(_fato(objeto_id, "metodo", metodo, "decidido", evidencia_id))
    return base


CRITERIOS_DE_DESENHO = ("divisas", "quadras", "meio_fio")


def _evidencia_da_ortofoto(rede: dict, ortofoto: str | Path | None) -> dict:
    """Segunda evidência da rede: a classe por metro sai da cor da ortofoto, não do desenho."""
    documento = str(ortofoto) if ortofoto else "ortofoto"
    return {"evidencia_id": f"EV-RV-{rede['id']}-ORTO", "classe": "ortofoto", "documento": documento,
            "localizador": {"arquivo": documento, "chave": "classe por metro pela cor da ortofoto"},
            "trecho": rede["id"], "metodo": "geometria", "executor": "código"}


def de_valas(redes: list[dict], crs_h: str = "EPSG:31982", ortofoto: str | Path | None = None) -> dict:
    """Redes de `valas.rede` → objetos `rede_vala` `RV-<id>`, eixo em linha, fatos e evidência (pranchas, layers e critério).

    `de_mm`, `dn_mm` (só quando o DN nominal difere do DE), `extensao_m`, `pesos_m` (traço do tubo) e `finais` (prancha de
    urbanização) são projetados e apontam para a
    evidência da prancha. A classe de cada metro é `projetado` quando o critério é o desenho (divisas, quadras, meio_fio);
    quando é a ortofoto, é `inferido` e aponta para uma segunda evidência (classe "ortofoto", documento = `ortofoto`,
    método "geometria"). A rede guarda um só critério, não a origem de cada metro: a natureza vale para a rede inteira.
    `local` é o nome da rede (obra.json e pranchas): dá unidade e sistema pelas chaves de unidades_construtivas.json."""
    base = _base_vazia()
    propriedades = _propriedades("eixo da rede")
    for rede in redes:
        objeto_id, evidencia_id = f"RV-{rede['id']}", f"EV-RV-{rede['id']}"
        pranchas = list(rede.get("pranchas", []))
        por_desenho = rede["criterio"] in CRITERIOS_DE_DESENHO
        base["objetos"].append({"objeto_id": objeto_id, "classe": "rede_vala"})
        base["geometria"].append({"objeto_id": objeto_id, "tipo": "linha", "coords": np.round(rede["pts"], 3).tolist(),
                                  "crs_h": crs_h, "datum_v": "ortométrico"})
        base["evidencias"].append({
            "evidencia_id": evidencia_id, "classe": "projeto", "documento": ", ".join(pranchas) or str(rede["id"]),
            "localizador": {"pranchas": pranchas, "layers": list(rede.get("layers", [])), "criterio": rede["criterio"]},
            "trecho": rede["id"], "metodo": "geometria", "executor": "código"})
        if not por_desenho:
            base["evidencias"].append(_evidencia_da_ortofoto(rede, ortofoto))
        dados = {"local": str(rede["id"]), "de_mm": rede["de_mm"], "extensao_m": rede["extensao_m"],
                 "classes_por_metro": list(rede["classes"]),
                 "pesos_m": np.asarray(rede["peso"], float).tolist(), "finais": rede.get("finais"),
                 "material": rede.get("material_declarado"),   # só o do obra.json ou do contrato, nunca o FD de premissa
                 "dn_mm": rede["dn_mm"] if rede.get("dn_mm") not in (None, rede["de_mm"]) else None}   # DN nominal (MOS)
        for propriedade in propriedades:
            if _vazio(dados.get(propriedade)):
                continue
            nasce_do_desenho = por_desenho or propriedade != "classes_por_metro"   # pesos: traço; finais: urbanização; material: contrato
            base["fatos"].append(_fato(objeto_id, propriedade, dados[propriedade],
                                       "projetado" if nasce_do_desenho else "inferido",
                                       evidencia_id if nasce_do_desenho else f"{evidencia_id}-ORTO"))
    return base


def paridade_valas(base: dict, redes: list[dict], tol: float = 0.1, servicos: list[dict] | None = None) -> list[dict]:
    """Diferenças entre os serviços `vala_rede` das gavetas e `valas.quantificar` de cada rede (`RV-<id>`).
    `servicos`: os gravados, que vão para a EAP (inclusive os reaproveitados); sem eles, calcula a base."""
    servicos = gavetas.calcular(base)[0] if servicos is None else servicos
    obtido: dict[str, dict] = {}
    for s in servicos:
        if s["regra"] == "vala_rede":
            obtido.setdefault(s["objeto_id"], {})[(s["saida"], s.get("chave"))] = s["valor"]
    difs = []
    for rede in redes:
        quadro = valas.quantificar(rede["classes"], np.asarray(rede["peso"], float), rede["de_mm"] / 1000,
                                   rede.get("finais"), rede.get("material_declarado"), rede.get("dn_mm"))
        esperado = {(nome, f"{q['classe']}/{q['final']}" if q["final"] else q["classe"]): q[nome]
                    for q in quadro for nome in ("demolicao_m2", "recomposicao_m2", "volume_vala_m3")
                    if q[nome] > 0 or nome == "volume_vala_m3"}
        difs += gavetas._diferencas(f"RV-{rede['id']}", obtido.get(f"RV-{rede['id']}", {}), esperado, tol)
    return difs


def de_setores(setores: list[dict], documento: str, crs_h: str = "EPSG:31982") -> dict:
    """Setores `{id, nome, coords}` do obra.json (`gavetas.setores`) → objetos `setor` `SET-<id>` com polígono, fato
    `nome` decidido e evidência "decisao" (executor "você"). Polígono inválido (menos de 3 pontos ou autointerseção)
    vira pendência, sem objeto."""
    from shapely import geometry as sg
    base = _base_vazia()
    for setor in setores:
        objeto_id, evidencia_id = f"SET-{setor['id']}", f"EV-SET-{setor['id']}"
        coords = setor.get("coords") or []
        try:
            valido = len(coords) >= 3 and sg.Polygon(coords).is_valid
        except (TypeError, ValueError):
            valido = False
        if not valido:
            base["pendencias"].append({"objeto_id": objeto_id,
                                       "motivo": "setor com polígono inválido (menos de 3 pontos ou autointerseção)"})
            continue
        base["objetos"].append({"objeto_id": objeto_id, "classe": "setor"})
        base["geometria"].append({"objeto_id": objeto_id, "tipo": "poligono", "coords": [list(p) for p in coords],
                                  "crs_h": crs_h, "datum_v": "ortométrico"})
        base["evidencias"].append({
            "evidencia_id": evidencia_id, "classe": "decisao", "documento": documento,
            "localizador": {"arquivo": documento, "chave": "gavetas.setores"}, "trecho": str(setor.get("nome", "")),
            "metodo": "decisão", "executor": "você"})
        for propriedade in _propriedades("setores da obra"):
            if not _vazio(setor.get(propriedade)):
                base["fatos"].append(_fato(objeto_id, propriedade, setor[propriedade], "decidido", evidencia_id))
    return base


SUPERFICIE_CAVAS = "SUP-MDS"        # a superfície do terreno (MDS do drone) usada pelas cavas


def _coords_da_base(geom) -> list:
    """Anel externo da base (ou o externo e os furos); polígono múltiplo vira uma lista de partes de uma só base."""
    partes = list(geom.geoms) if hasattr(geom, "geoms") else [geom]
    return [[list(map(float, xy)) for xy in p.exterior.coords] if not p.interiors else
            [[list(map(float, xy)) for xy in anel.coords] for anel in (p.exterior, *p.interiors)] for p in partes]


def _bases_da_gaveta(bases: list[dict]) -> list[dict]:
    """Bases `{coords, etapa}` (ou `{geom, etapa}` do `escavacao.bases`); sem arredondar, para o cálculo repetir o direto."""
    saida = []
    for b in bases:
        for coords in ([b["coords"]] if "coords" in b else _coords_da_base(b["geom"])):
            saida.append({"coords": coords, "etapa": b.get("etapa")})
    return saida


def _marcas_da_planta(marcas: list[dict]) -> list[dict]:
    """Marcas `{E, N, cota_m, texto, topo, prancha}` a partir das do `escavacao.marcas` (`utm`, `cota`, `topo`)."""
    saida = []
    for m in marcas:
        e, n = (m["E"], m["N"]) if "E" in m else m["utm"]
        cota = m.get("cota_m", m.get("cota"))
        texto = m.get("texto") or (None if cota is None else f"{cota:.2f}".replace(".", ",") + (" TOPO" if m.get("topo") else ""))
        saida.append({"E": e, "N": n, "cota_m": cota, "texto": texto, "topo": bool(m.get("topo")), "prancha": m.get("prancha")})
    return saida


def _evidencias_das_cavas(superficie: dict, pranchas: list[str], layers: list[str], crs_h: str, mds: str,
                          fonte_terreno: str | None = None) -> list[dict]:
    """A evidência das plantas (pranchas e layers) e a da superfície (MDS do drone, `metodo` geometria). Com
    `fonte_terreno`, o terreno é composto (topografia + MDS) e a evidência diz isso."""
    return [{"evidencia_id": "EV-CAVAS", "classe": "projeto", "documento": ", ".join(pranchas) or "plantas de escavação",
             "localizador": {"pranchas": list(pranchas), "layers": list(layers), "criterio": "plantas de escavação",
                             "crs_h": crs_h, "etapa_origem": "escavacao"},
             "trecho": "cavas", "metodo": "geometria", "executor": "código"},
            {"evidencia_id": superficie["evidencia_id"], "classe": "ortofoto", "documento": mds,
             "localizador": {"arquivo": mds, "chave": "terreno em cota (MDS), válido e edificação"
                             + (f"; terreno composto: {fonte_terreno}" if fonte_terreno else "")},
             "trecho": superficie["superficie_id"], "metodo": "geometria", "executor": "código"}]


def de_cavas(marcas: list[dict], bases: list[dict], cristas: list, superficie_registro: dict, pranchas: list[str],
             crs_h: str = "EPSG:31982", mds: str | Path | None = None, layers: list[str] | None = None,
             fonte_terreno: str | None = None) -> dict:
    """Plantas de escavação → objeto `conjunto_cavas` `CAVAS`, os fatos `marcas_cota`, `bases`, `cristas` e `superficie_id`
    (todos `projetado`), a evidência nas pranchas e layers e a superfície com a sua.

    `marcas`, `bases` e `cristas` vêm do `escavacao.marcas`, `bases` e `linhas_utm` (ou já no formato do fato). A superfície
    é o registro de `gavetas.gravar_superficie`; a evidência dela é classe "ortofoto", método "geometria", executor "código",
    com o MDS do sfm (`mds`) por documento. `marcas_cota` e `bases` ficam sem arredondar: o cálculo pelas gavetas repete o direto."""
    base = _base_vazia()
    superficie = dict(superficie_registro)
    documento_mds = str(mds) if mds else "sfm/ortofoto_mds.png"
    base["objetos"].append({"objeto_id": "CAVAS", "classe": "conjunto_cavas"})
    base["superficies"].append(superficie)
    base["evidencias"] += _evidencias_das_cavas(superficie, pranchas, layers or [], crs_h, documento_mds, fonte_terreno)
    valores = {"marcas_cota": _marcas_da_planta(marcas), "bases": _bases_da_gaveta(bases),
               "cristas": [[list(map(float, xy)) for xy in (c.coords if hasattr(c, "coords") else c)] for c in cristas],
               "superficie_id": superficie["superficie_id"]}
    for propriedade in _propriedades("plantas de escavação"):
        if not _vazio(valores.get(propriedade)):
            evidencia = superficie["evidencia_id"] if propriedade == "superficie_id" else "EV-CAVAS"
            base["fatos"].append(_fato("CAVAS", propriedade, valores[propriedade], "projetado", evidencia))
    return base


def paridade_cavas(base: dict, resultado_calcular: dict, servicos: list[dict] | None = None, tol: float = 0.1,
                   pasta_base=None) -> list[dict]:
    """Diferenças entre os serviços `cavas` das gavetas e o `escavacao.calcular` direto (`resultado_calcular["cavas"]`).
    `servicos`: os gravados, que vão para a EAP (inclusive os reaproveitados); sem eles, calcula a base em `pasta_base`."""
    servicos = gavetas.calcular(base, pasta_base)[0] if servicos is None else servicos
    obtido = {(s["saida"], s.get("chave")): s["valor"] for s in servicos if s["regra"] == "cavas"}
    esperado = {(saida, c["id"]): c[campo] for c in resultado_calcular["cavas"]
                for saida, campo in escavacao.SAIDAS_CAVA.items()}
    return gavetas._diferencas("CAVAS", obtido, esperado, tol)


def juntar(*bases: dict) -> dict:
    """Une as gavetas; chave repetida idêntica entra uma vez, com conteúdo diferente é `ValueError`."""
    unida = _base_vazia()
    for gaveta in gavetas.GAVETAS:
        chave = gavetas.REGRAS["gavetas"][gaveta]["chave"]
        registros = [r for base in bases for r in base.get(gaveta, [])]
        unida[gaveta] = _sem_repeticao(gaveta, chave, registros)
    return unida


def _sem_repeticao(gaveta: str, chave: str | None, registros: list[dict]) -> list[dict]:
    """Registros sem repetição idêntica; mesma chave com conteúdo diferente é `ValueError`."""
    vistos: dict = {}
    for registro in registros:
        rotulo = registro[chave] if chave else repr(registro)      # pendências não têm chave: só duplicata exata
        if rotulo in vistos and vistos[rotulo] != registro:
            raise ValueError(f"{gaveta}: {chave} {rotulo} repetido com conteúdo diferente")
        vistos.setdefault(rotulo, registro)
    return list(vistos.values())


MOTIVO_RECUSA_IA = "retorno de IA recusado"


def _recusa(retorno: dict, objeto_id, propriedade, motivo: str) -> dict:
    """Pendência de um fato da IA que não entra: o motivo e a propriedade ficam no texto."""
    return {"objeto_id": str(objeto_id or retorno.get("arquivo") or "retorno"),
            "motivo": f"{MOTIVO_RECUSA_IA}: {motivo} ({propriedade})"}


def _ler_retornos(pasta: Path) -> tuple[list[dict], list[dict]]:
    """Linhas dos `*.jsonl` em ordem alfabética de arquivo e de linha; linha inválida vira pendência."""
    retornos, pendencias = [], []
    for arquivo in sorted(Path(pasta).glob("*.jsonl")):
        for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), start=1):
            if not linha.strip():
                continue
            try:
                retorno = json.loads(linha)
            except ValueError:
                retorno = None
            if isinstance(retorno, dict):
                retornos.append(retorno)
            else:
                pendencias.append({"objeto_id": arquivo.name,
                                   "motivo": f"{MOTIVO_RECUSA_IA}: linha {numero} não é um retorno JSON (-)"})
    return retornos, pendencias


def _classe_calculada(retorno: dict, avaliacao: dict | None) -> str | None:
    """Classe (id de fontes.json) do arquivo do retorno, calculada pelo código e não declarada pela IA: a da
    `avaliacao`, quando dada, senão o classificador do inventário (`extracao.classe`) sobre arquivo, pasta e carimbo.
    None quando não há como classificar (sem nome de arquivo, ou classe `outro`)."""
    if avaliacao and avaliacao.get("classe"):
        return _id_da_classe(avaliacao["classe"])
    if not retorno.get("arquivo"):
        return None
    calculada = extracao.classe({"arquivo": str(retorno["arquivo"]), "pasta_drive": retorno.get("pasta_drive"),
                                 "carimbo": retorno.get("carimbo"), "codigo": retorno.get("codigo")})
    return None if calculada == "outro" else calculada


def _id_da_classe(classe: str | None) -> str | None:
    """O id da classe em fontes.json (aceita o id ou o nome); texto desconhecido fica como está."""
    return next((c["id"] for c in extracao.FONTES["classes"] if classe in (c["id"], c["nome"])), classe)


def _recusa_de_classe(retorno: dict, avaliacao: dict | None) -> dict | None:
    """Pendência que recusa o retorno inteiro quando a classe declarada pela IA não é a calculada pelo código."""
    declarada, calculada = _id_da_classe(retorno.get("classe")), _classe_calculada(retorno, avaliacao)
    if calculada is not None and declarada == calculada:
        return None
    return _recusa(retorno, retorno.get("arquivo"), "classe",
                   f"classe do arquivo não conferida: declarada {declarada}, calculada {calculada or 'não classificável'}")


def de_retornos(pasta: Path, avaliacoes: dict | None = None) -> dict:
    """Retornos de IA (`pasta/*.jsonl`) → base com fatos `inferido`, evidências (executor e trecho) e objetos.

    Cada linha passa por `extracao.fatos_do_retorno`; as recusas (fora do de-para, sem trecho, sem valor) viram
    pendência com motivo, nunca fato. `avaliacoes` é `{"<pasta_drive>/<arquivo>": avaliação}` (ou só `<arquivo>`).
    Objeto citado com classes diferentes entre retornos: o primeiro vale e o outro vira pendência."""
    base = _base_vazia()
    retornos, base["pendencias"] = _ler_retornos(pasta)
    classes: dict[str, str] = {}
    for retorno in retornos:
        chave = f"{retorno.get('pasta_drive')}/{retorno.get('arquivo')}"
        avaliacao = (avaliacoes or {}).get(chave) or (avaliacoes or {}).get(retorno.get("arquivo"))
        recusa = _recusa_de_classe(retorno, avaliacao)
        if recusa:                                     # a classe do arquivo é do código, não da IA: retorno inteiro fora
            base["pendencias"].append(recusa)
            continue
        saida = extracao.fatos_do_retorno(retorno, avaliacao or {"classe": _classe_calculada(retorno, None)})
        base["pendencias"] += [_recusa(retorno, r.get("objeto_id"), r["propriedade"], r["motivo"])
                               for r in saida["recusas"]]
        classe_do_objeto = {o["objeto_id"]: o["classe"] for o in saida["objetos"]}
        divergentes = {i for i, c in classe_do_objeto.items() if classes.setdefault(i, c) != c}
        for objeto_id in sorted(divergentes):
            base["pendencias"].append(_recusa(retorno, objeto_id, "classe",
                                              f"classe {classe_do_objeto[objeto_id]} difere de {classes[objeto_id]}"))
        saida = _sem_objetos(saida, divergentes)
        for gaveta in ("fatos", "evidencias", "objetos"):
            base[gaveta] += saida[gaveta]
    return {**base, **{g: _sem_repeticao(g, gavetas.REGRAS["gavetas"][g]["chave"], base[g])
                       for g in ("fatos", "evidencias", "objetos")}}


def _sem_objetos(base: dict, objetos: set[str]) -> dict:
    """Tira os objetos dados, seus fatos e as evidências que ficaram sem fato."""
    if not objetos:
        return base
    fatos = [f for f in base["fatos"] if f["objeto_id"] not in objetos]
    usadas = {f["evidencia_id"] for f in fatos}
    return {**base, "fatos": fatos, "objetos": [o for o in base["objetos"] if o["objeto_id"] not in objetos],
            "evidencias": [e for e in base["evidencias"] if e["evidencia_id"] in usadas]}


def _conciliar_com_a_base(ia: dict, base: dict) -> dict:
    """Objeto da IA que já existe na base não se duplica (mesma classe) ou vira pendência (classe diferente)."""
    existentes = {o["objeto_id"]: o["classe"] for o in base["objetos"]}
    divergentes = {o["objeto_id"] for o in ia["objetos"]
                   if o["objeto_id"] in existentes and existentes[o["objeto_id"]] != o["classe"]}
    pendencias = [{"objeto_id": i, "motivo": f"{MOTIVO_RECUSA_IA}: classe difere da do objeto existente "
                                              f"{existentes[i]} (classe)"} for i in sorted(divergentes)]
    ia = _sem_objetos({**ia, "objetos": ia["objetos"]}, divergentes)
    return {**ia, "pendencias": ia["pendencias"] + pendencias,
            "objetos": [o for o in ia["objetos"] if o["objeto_id"] not in existentes]}


def _resumo(base: dict, erros: list[str], difs: list[dict], servicos: list[dict]) -> dict:
    """Contagens da base: objetos, fatos (por natureza e por executor da evidência), pendências, paridade e EAP."""
    executor = {e["evidencia_id"]: e["executor"] for e in base["evidencias"]}
    metodo = {e["evidencia_id"]: e.get("metodo") for e in base["evidencias"]}
    return {
        "objetos_por_classe": dict(Counter(o["classe"] for o in base["objetos"])),
        "fatos_por_natureza": dict(Counter(f["natureza"] for f in base["fatos"])),
        "fatos_por_executor": dict(Counter(executor.get(f["evidencia_id"]) for f in base["fatos"])),
        "pendencias_por_motivo": dict(Counter(p["motivo"].split(":")[0] for p in base["pendencias"])),
        "fatos_ia": sum(1 for f in base["fatos"] if f["natureza"] == "inferido" and metodo.get(f["evidencia_id"]) == "IA"),
        "recusas_ia": sum(1 for p in base["pendencias"] if p["motivo"].startswith(MOTIVO_RECUSA_IA)),
        "erros_conferencia": erros, "diferencas_paridade": len(difs), "servicos": len(servicos),
        "eap": gavetas.para_eap(servicos)}


def _fonte_do_terreno(g: dict) -> str | None:
    """Texto da fonte do terreno composto (topografia + MDS) com as áreas por origem; None quando é o MDS puro."""
    r = g.get("terreno_resumo")
    if r is None:
        return None
    areas = ", ".join(f"{nome} {m2:g} m²" for nome, m2 in r["area_m2"].items())
    return f"topografia do projeto no casco das curvas, MDS corrigido fora, costura de {r['faixa_costura_m']:g} m ({areas})"


def _base_das_cavas(cfg: dict, out: Path, pasta: Path, cavas: dict) -> dict:
    """Grava a superfície em `pasta/superficies/` e devolve as gavetas das cavas (`de_cavas`)."""
    registro = gavetas.gravar_superficie(pasta, SUPERFICIE_CAVAS, cavas["g"])
    c = cfg.get("escavacao") or {}
    layers = [c[k] for k in ("layer_base", "layer_marca", "layer_crista") if c.get(k)]
    return de_cavas(cavas["marcas"], cavas["bases"], cavas["cristas"], registro, cavas.get("pranchas", []),
                    registro["crs_h"], mds=Path(out) / "sfm" / "ortofoto_mds.png", layers=layers,
                    fonte_terreno=_fonte_do_terreno(cavas["g"]))


def _anotar_codigo_eap(base: dict, servicos: list[dict], cfg: dict, por_servico: dict) -> dict:
    """Código completo da EAP codificada em cada serviço (anotação, fora da chave do incremental). Unidade e sistema
    sem definição viram pendência da base. Devolve {saída: n} dos serviços sem item na EAP codificada."""
    mapa, pendencias = gavetas.unidade_sistema(base, gavetas.indice(base), cfg, por_servico, servicos)
    sem_codigo, pend_codigo = gavetas.anotar_codigo_eap(servicos, mapa, pendencias)
    base["pendencias"] = base["pendencias"] + pend_codigo
    return sem_codigo


def _base_da_etapa(cfg: dict, furos: list[dict], out: Path, trechos: list[dict], aba: str | None,
                   redes_vala: list[dict] | None, cavas: dict | None, epsg: int | None) -> dict:
    """As gavetas da etapa juntas: trechos da planilha, sondagens, decisões, redes de vala, cavas e setores, com a EPSG
    da obra na geometria (sem ela, o padrão de cada `de_*`)."""
    c = cfg.get("obras_lineares")
    doc_sond = cfg["sondagens"] if isinstance(cfg.get("sondagens"), str) else "sondagens"
    executor = (cfg.get("gavetas") or {}).get("executor_sondagens", "código")
    setores = (cfg.get("gavetas") or {}).get("setores")
    crs = {"crs_h": f"EPSG:{epsg}"} if epsg else {}
    caminho = str(cfg.get("_caminho", "obra.json"))
    return juntar(de_obras_lineares(trechos, str(c["planilha"]) if c else "", aba or "Obras Lineares"),
                  de_sondagens(furos, doc_sond, executor, **crs),
                  de_decisoes((c or {}).get("metodo") or {}, trechos, caminho),
                  de_valas(redes_vala or [], ortofoto=Path(out) / "sfm" / "ortofoto.jpg", **crs),
                  _base_das_cavas(cfg, out, Path(out) / "base", cavas) if cavas else _base_vazia(),
                  de_setores(setores or [], caminho, **crs))


def etapa(cfg: dict, furos: list[dict], out: Path, log=print, redes_vala: list[dict] | None = None,
          cavas: dict | None = None, epsg: int | None = None) -> dict | None:
    """Etapa `gavetas` do build: extrai planilha, sondagens e decisões para as gavetas, confere, calcula os serviços,
    compara com `obras_lineares.quantificar` e grava `base/`, `paridade.json` e `resumo.json` em `out`. Devolve o resumo
    com `eap_html` (o `dados["eap_gavetas"]` da aba EAP, montado e formatado em Python por `eap_html.montar`).
    `cavas`: o `saida_gavetas` de `escavacao.etapa` (marcas, bases, cristas, grade e resultado); grava a superfície em
    `base/superficies/`, junta `de_cavas` e soma a paridade com o `escavacao.calcular` direto. `epsg`: o CRS da obra,
    gravado na geometria dos furos, das redes de vala e dos setores (sem ele, o padrão de cada `de_*`)."""
    c = cfg.get("obras_lineares")
    tem_planilha = bool(c) and ol.tem_aba(c)
    if c and not tem_planilha:
        log(f"Gavetas: sem trechos da planilha ({c['planilha']} ausente ou sem a aba '{c.get('aba', 'Obras Lineares')}')")
    if not tem_planilha and not cavas:
        return None
    aba = c.get("aba", "Obras Lineares") if tem_planilha else None
    trechos = ol.ler_obras_lineares(c["planilha"], aba) if tem_planilha else []
    escolha = {ol.norm(k): v for k, v in ((c or {}).get("metodo") or {}).items()}
    aplicados = [{**t, "metodo": escolha.get(ol.norm(t["local"]), t["metodo"])} for t in trechos]
    pasta = Path(out) / "base"
    setores = (cfg.get("gavetas") or {}).get("setores")
    base = _base_da_etapa(cfg, furos, out, trechos, aba, redes_vala, cavas, epsg)
    if (Path(out) / "retornos_gavetas").is_dir():                       # fatos da IA: inferidos, com executor e trecho
        base = juntar(base, _conciliar_com_a_base(de_retornos(Path(out) / "retornos_gavetas"), base))
    erros = gavetas.conferir_base(base)
    por_setor, pend_setores = gavetas.setor_de(base) if setores else (None, [])
    base["pendencias"] = base["pendencias"] + pend_setores
    anterior = gavetas.ler(pasta)["servicos"] if (pasta / "servicos.parquet").exists() else None
    servicos, pend_calculo, est = gavetas.calcular_incremental(base, anterior, pasta)
    difs = (gavetas.paridade(base, aplicados, furos, servicos=servicos)          # compara o que vai para a EAP
            + paridade_valas(base, redes_vala or [], servicos=servicos)
            + (paridade_cavas(base, cavas["resultado"], servicos) if cavas else []))
    base["pendencias"] = base["pendencias"] + pend_calculo
    pasta.mkdir(parents=True, exist_ok=True)
    contagem_setores = dict(Counter(x or "fora" for x in por_setor.values())) if por_setor is not None else None
    por_servico: dict = {}
    if por_setor is not None:                                            # serviço com ponto (cada cava) cai no seu setor
        por_servico, pend_servicos = gavetas.setor_dos_servicos(base, servicos)
        por_setor = {**por_setor, **por_servico}
        base["pendencias"] = base["pendencias"] + pend_servicos
    sem_codigo = _anotar_codigo_eap(base, servicos, cfg, por_servico)
    pdfs = {q["id"]: q["pdf"] for q in cfg.get("pranchas", []) if q.get("id") and q.get("pdf")}
    gavetas.anotar_origem(servicos, base, pdfs)  # fato → evidência → documento/etapa: a origem do número na conciliação
    gavetas.gravar(pasta, {**base, "servicos": servicos})
    resumo = {**_resumo(base, erros, difs, servicos), **est, "sem_codigo_eap": sem_codigo}
    if por_setor is not None:
        resumo["objetos_por_setor"] = contagem_setores
    (Path(out) / "paridade.json").write_text(json.dumps(difs, ensure_ascii=False, indent=1), encoding="utf-8")
    (Path(out) / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Gavetas: {len(base['objetos'])} objetos, {len(base['fatos'])} fatos, {len(base['pendencias'])} pendências, "
        f"{len(servicos)} serviços, {len(erros)} erros de conferência, {len(difs)} diferenças de paridade")
    # `eap_html` é a aba EAP do HTML; `servicos_eap` (com o código completo) alimenta a conciliação em `obra`; ambos saem do resumo lá
    return {**resumo, "eap_html": eap_html.montar(base, servicos, base["pendencias"], resumo, por_setor),
            "servicos_eap": servicos}


def _substituir(base: dict, *partes: dict) -> dict:
    """Junta as `partes` à `base` trocando o que já existia com a mesma chave (e as pendências dos mesmos objetos): rodar
    a extração de novo sobre uma base que já a contém dá o mesmo resultado (idempotente), em vez de colidir."""
    novas = juntar(*partes)
    limpa = {}
    for gaveta in gavetas.GAVETAS:
        chave = gavetas.REGRAS["gavetas"][gaveta]["chave"]
        if chave:
            ids = {r[chave] for r in novas[gaveta]}
            limpa[gaveta] = [r for r in base.get(gaveta, []) if r.get(chave) not in ids]
        else:
            objetos = {r.get("objeto_id") for r in novas[gaveta]} | {o["objeto_id"] for o in novas["objetos"]}
            limpa[gaveta] = [r for r in base.get(gaveta, []) if r.get("objeto_id") not in objetos]
    return juntar(limpa, novas)


def _sem_os_que_ja_tem(registros: dict, base: dict) -> dict:
    """Só os documentos e páginas que a base ainda não tem (o inventário prevalece sobre o registro mínimo de um leitor)."""
    ja = {g: {r[gavetas.REGRAS["gavetas"][g]["chave"]] for r in base.get(g, [])} for g in ("documentos", "paginas")}
    return {g: [r for r in registros.get(g, []) if r[gavetas.REGRAS["gavetas"][g]["chave"]] not in ja[g]]
            for g in ("documentos", "paginas")}


def completar_escopo(cfg: dict, out: Path, dados: dict, log=print) -> dict | None:
    """F2 da reconstrução (docs/RECONSTRUCAO.md): completa a base das gavetas com todo o escopo extraído — documentos e
    páginas do inventário (`gavetas_documentos`), linhas do contrato e itens de material (`gavetas_contrato`, sem preço) e
    elementos construtivos (`gavetas_construtivos`) —, confere e regrava `base/`. Roda depois dos `construtivos`. Devolve
    o resumo (gravado em `gavetas_escopo.json`); nada muda no `dados` do HTML. Sem inventário, planilha ou elementos, a
    parte que falta só não entra (e o resumo diz)."""
    pasta = Path(out) / "base"
    base = gavetas.ler(pasta) if (pasta / "objetos.parquet").exists() else _base_vazia()
    faltou = []
    base = _escopo_inventario(cfg, out, base, faltou)
    base = _escopo_contrato(cfg, base, faltou)
    base = _escopo_construtivos(cfg, dados, base, faltou)
    complementares = _complementares(base, dados, out, log) if (dados.get("crs") or {}).get("epsg") else None
    if complementares:
        base = complementares.pop("base")
    erros = gavetas.conferir_base(base)
    gavetas.gravar(pasta, base)
    resumo = _resumo_escopo(base, faltou, erros)
    com_pagina = resumo["fatos_com_pagina"]
    resumo["complementares"] = complementares
    resumo["eap_unica"] = _eap_unica(base, dados, out, log)
    resumo["laco"] = _laco(base, cfg, out, log)
    (Path(out) / "gavetas_escopo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Gavetas (escopo): {len(base['documentos'])} documentos, {len(base['paginas'])} páginas, "
        f"{len(base['objetos'])} objetos, {len(base['fatos'])} fatos ({com_pagina} com página ou aba e linha), "
        f"{len(base['pendencias'])} pendências, {len(erros)} erros de conferência"
        + (f"; faltou: {', '.join(faltou)}" if faltou else ""))
    return resumo


def _escopo_inventario(cfg: dict, out: Path, base: dict, faltou: list) -> dict:
    """Documentos e páginas do inventário do Drive e as menções do texto (F5); acrescenta ao `faltou` o que não houve."""
    from . import gavetas_documentos, inventario

    partes = []
    if cfg.get("inventario") and inventario.disponivel(cfg):
        inv = inventario.inventario(cfg, Path(out) / "inventario_cache.json")
        partes.append(gavetas_documentos.de_inventario(inv, Path(cfg["inventario"]["pasta"]),
                                                       gavetas_documentos._pranchas_do_build(cfg)))
    else:
        faltou.append("inventário (sem a listagem do Drive)")
    base = _substituir(base, *partes)
    if partes and base["documentos"]:                               # F5: menções do texto (edital, memorial, laudo), por página
        from . import gavetas_texto

        texto = gavetas_texto.de_documentos(base["documentos"], Path(cfg["inventario"]["pasta"]))
        texto.pop("lidos", None)
        base = _substituir(base, texto)
    return base


def _escopo_contrato(cfg: dict, base: dict, faltou: list) -> dict:
    """Linhas do contrato e itens de material da planilha (sem preço); sem planilha, acrescenta ao `faltou`."""
    from . import gavetas_contrato

    planilha = Path((cfg.get("obras_lineares") or {}).get("planilha") or "")
    if planilha.is_file():
        doc = gavetas.id_documento(planilha)
        base = _substituir(base, gavetas_contrato.de_contrato(planilha, doc), gavetas_contrato.de_materiais(planilha, doc),
                      _sem_os_que_ja_tem({"documentos": [{"documento_id": doc, "arquivo": planilha.name, "sha256": doc,
                                                          "extensao": planilha.suffix, "classe": "planilha", "paginas": 1}]},
                                         base))
    else:
        faltou.append("planilha do contrato")
    return base


def _escopo_construtivos(cfg: dict, dados: dict, base: dict, faltou: list) -> dict:
    """Elementos construtivos das pranchas; sem eles ou sem PDF de prancha, acrescenta ao `faltou`."""
    from . import gavetas_construtivos

    tem_pdf = any(q.get("pdf") for q in cfg.get("pranchas", []))
    if (dados.get("construtivos") or {}).get("geojson") and tem_pdf:
        nomes = {Path(d["arquivo"]).name: d["documento_id"] for d in base["documentos"]}
        ids, registros = gavetas_construtivos._documentos_citados(dados["construtivos"],
                                                                  gavetas_construtivos._raiz_de_dados(cfg, Path.cwd() / "obra.json"))
        base = _substituir(base, gavetas_construtivos.de_construtivos(dados["construtivos"], dados.get("pranchas", []),
                                                                 {**ids, **nomes}, dados["crs"]["epsg"]),
                      _sem_os_que_ja_tem(registros, base))
    else:
        faltou.append("elementos construtivos" if tem_pdf else "elementos construtivos (sem PDF de prancha no obra.json)")
    return base


def _resumo_escopo(base: dict, faltou: list, erros: list) -> dict:
    """Contagens da base completada (gavetas, classes, fatos com página) para o `gavetas_escopo.json`."""
    ev = {e["evidencia_id"]: e for e in base["evidencias"]}
    com_pagina = sum(1 for f in base["fatos"] if gavetas._localizador_com_pagina((ev.get(f["evidencia_id"]) or {}).get("localizador")))
    return {"gavetas": {g: len(base[g]) for g in gavetas.GAVETAS},
            "objetos_por_classe": dict(sorted(Counter(o["classe"] for o in base["objetos"]).items())),
            "fatos_com_pagina": com_pagina, "fatos": len(base["fatos"]),
            "documentos_por_classe": dict(sorted(Counter(d.get("classe") for d in base["documentos"]).items())),
            "faltou": faltou, "erros": erros}


def _complementares(base: dict, dados: dict, out: Path, log=print) -> dict:
    """F4: serviços complementares (`gavetas_servicos`, regras de `servicos_associados.jsonl`) calculados das gavetas e
    gravados nelas (idempotente: os da rodada anterior são trocados), com a paridade contra o `associados.csv` deste build."""
    from . import gavetas_servicos

    r = gavetas_servicos.complementares(base, dados["crs"]["epsg"])
    nova = _substituir(base, {g: r.get(g, []) for g in ("servicos", "evidencias", "pendencias")})
    csv = Path(out) / "associados.csv"
    associados = [s for s in nova["servicos"] if str(s.get("regra", "")).startswith("associado:")]
    difs = gavetas_servicos.paridade(associados, csv) if csv.exists() else None
    vala = gavetas_servicos.paridade_da_vala(associados, csv) if csv.exists() else None   # vala: da rede, muda por decisão
    log(f"Complementares (pelas gavetas): {len(r.get('servicos', []))} serviços, {len(r.get('pendencias', []))} pendências; "
        + (f"paridade com o associados.csv (fora a vala): {len(difs)} diferença(s); vala da rede: {len(vala)} serviço(s) "
           f"mudaram" if difs is not None else "sem associados.csv no build"))
    return {"base": nova, "servicos": len(r.get("servicos", [])), "pendencias": len(r.get("pendencias", [])),
            "paridade_associados": len(difs) if difs is not None else None, "diferencas": (difs or [])[:20],
            "vala_mudou": len(vala) if vala is not None else None}


def _eap_unica(base: dict, dados: dict, out: Path, log=print) -> dict:
    """F3: a EAP única preenchida só pelas gavetas (`eap_preencher`), gravada em `eap_unica.json`, com a paridade contra a
    EAP codificada deste mesmo build (`dados["eap"]`, quando já montada): cada quantidade dela tem de sair igual."""
    from . import eap_preencher

    eap = eap_preencher.preencher(base)
    codificada = {f"{q['codigo']}|{q['grandeza']}": {"quantidade": q["quantidade"], "unidade": q["unidade"]}
                  for q in ((dados.get("eap") or {}).get("quantidades") or []) if q.get("quantidade") is not None}
    difs = eap_preencher.paridade(eap_preencher.itens_tecnicos(base), codificada) if codificada else []
    (Path(out) / "eap_unica.json").write_text(json.dumps({**eap, "paridade_eap_codificada": difs}, ensure_ascii=False,
                                                         indent=1), encoding="utf-8")
    comp = {t: f"{c.get('preenchida', 0)} preenchidas + {c.get('calculada', 0)} calculadas + {c.get('declarada', 0)} "
               f"declaradas de {c.get('folhas', 0)}" for t, c in eap["completude"].items()}
    log(f"EAP única (pelas gavetas): {comp}; paridade com a EAP codificada: "
        + (f"{len(difs)} diferença(s)" if codificada else "sem EAP codificada no build"))
    return {"completude": eap["completude"], "paridade_eap_codificada": len(difs) if codificada else None,
            "quantidades_comparadas": len(codificada)}


def _laco(base: dict, cfg: dict, out: Path, log=print) -> dict:
    """F5: o laço até a EAP completa (`eap_laco`): o destino de cada folha a preencher (código → IA com citação conferida
    → Caio), o portão "EAP completa" em `eap_laco.json` e o roteiro do próximo passe de leitura em `proximo_passe.jsonl`.
    As decisões de "ausente do projeto" vêm do arquivo de `cfg["decisoes_eap"]`, se houver."""
    from . import eap_laco, eap_preencher

    eap = eap_preencher.preencher(base)
    destinos = eap_laco.destinos(eap, base, eap_laco.ler_decisoes(cfg.get("decisoes_eap")))
    portao = eap_laco.portao(eap, destinos)
    roteiro = eap_laco.roteiro(destinos)
    (Path(out) / "eap_laco.json").write_text(json.dumps({"portao": portao, "destinos": destinos}, ensure_ascii=False,
                                                        indent=1), encoding="utf-8")
    (Path(out) / "proximo_passe.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in roteiro),
                                                   encoding="utf-8")
    log(f"Laço da EAP: {'EAP COMPLETA' if portao['fechada'] else 'EAP aberta'}; {len(portao.get('trava', []))} "
        f"obrigatória(s) travam; próximo passe: {len(roteiro)} leitura(s) de documento")
    return {"fechada": portao["fechada"], "trava": len(portao.get("trava", [])), "roteiro": len(roteiro)}


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "extrair_gavetas",
        "descricao": "leitores (planilha de obras lineares, sondagens, decisões) gravam objetos, fatos e evidências "
                     "nas gavetas; valor ausente não vira fato; retornos de IA entram como inferido e a recusa vira pendência",
        "funcoes": ["de_obras_lineares", "de_sondagens", "de_decisoes", "de_setores", "de_valas", "paridade_valas",
                    "de_cavas", "paridade_cavas", "de_retornos", "juntar", "etapa"],
        "conceitos": ["gavetas.json", "de_para_extracao.json"],
    }
