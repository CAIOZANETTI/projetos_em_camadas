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

from . import eap_html, extracao, gavetas, valas
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
    return {gaveta: [] for gaveta in gavetas.GAVETAS}


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


def de_valas(redes: list[dict], crs_h: str = "EPSG:31982") -> dict:
    """Redes de `valas.rede` → objetos `rede_vala` `RV-<id>`, eixo em linha, fatos e evidência (pranchas e critério).

    `de_mm` e `extensao_m` são projetados. Classe, peso e superfície final são `projetado` quando o critério é o
    desenho (divisas, quadras, meio_fio) e `inferido` quando é a ortofoto. A rede guarda um só critério, não a
    origem de cada metro: a natureza vale para a rede inteira."""
    base = _base_vazia()
    propriedades = _propriedades("eixo da rede")
    for rede in redes:
        objeto_id, evidencia_id = f"RV-{rede['id']}", f"EV-RV-{rede['id']}"
        pranchas = list(rede.get("pranchas", []))
        base["objetos"].append({"objeto_id": objeto_id, "classe": "rede_vala"})
        base["geometria"].append({"objeto_id": objeto_id, "tipo": "linha", "coords": np.round(rede["pts"], 3).tolist(),
                                  "crs_h": crs_h, "datum_v": "ortométrico"})
        base["evidencias"].append({
            "evidencia_id": evidencia_id, "classe": "projeto", "documento": ", ".join(pranchas) or str(rede["id"]),
            "localizador": {"pranchas": pranchas, "criterio": rede["criterio"]}, "trecho": rede["id"],
            "metodo": "geometria", "executor": "código"})
        dados = {"de_mm": rede["de_mm"], "extensao_m": rede["extensao_m"], "classes_por_metro": list(rede["classes"]),
                 "pesos_m": np.asarray(rede["peso"], float).tolist(), "finais": rede.get("finais")}
        amostrado = "projetado" if rede["criterio"] in CRITERIOS_DE_DESENHO else "inferido"
        for propriedade in propriedades:
            if _vazio(dados.get(propriedade)):
                continue
            natureza = "projetado" if propriedade in ("de_mm", "extensao_m") else amostrado
            base["fatos"].append(_fato(objeto_id, propriedade, dados[propriedade], natureza, evidencia_id))
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
                                   rede.get("finais"))
        esperado = {(nome, f"{q['classe']}/{q['final']}" if q["final"] else q["classe"]): q[nome]
                    for q in quadro for nome in ("demolicao_m2", "recomposicao_m2", "volume_vala_m3")
                    if q[nome] > 0 or nome == "volume_vala_m3"}
        difs += gavetas._diferencas(f"RV-{rede['id']}", obtido.get(f"RV-{rede['id']}", {}), esperado, tol)
    return difs


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
        saida = extracao.fatos_do_retorno(retorno, avaliacao)
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


def etapa(cfg: dict, furos: list[dict], out: Path, log=print, redes_vala: list[dict] | None = None) -> dict | None:
    """Etapa `gavetas` do build: extrai planilha, sondagens e decisões para as gavetas, confere, calcula os serviços,
    compara com `obras_lineares.quantificar` e grava `base/`, `paridade.json` e `resumo.json` em `out`. Devolve o resumo
    com `eap_html` (o `dados["eap"]` da aba EAP, montado e formatado em Python por `eap_html.montar`)."""
    c = cfg.get("obras_lineares")
    if not c or not Path(c["planilha"]).exists():
        if c:
            log(f"Gavetas: planilha {c['planilha']} não está no disco")
        return None
    aba = c.get("aba", "Obras Lineares")
    trechos = ol.ler_obras_lineares(c["planilha"], aba)
    escolha = {ol.norm(k): v for k, v in (c.get("metodo") or {}).items()}
    aplicados = [{**t, "metodo": escolha.get(ol.norm(t["local"]), t["metodo"])} for t in trechos]
    doc_sond = cfg["sondagens"] if isinstance(cfg.get("sondagens"), str) else "sondagens"
    executor = (cfg.get("gavetas") or {}).get("executor_sondagens", "código")
    base = juntar(de_obras_lineares(trechos, str(c["planilha"]), aba), de_sondagens(furos, doc_sond, executor),
                  de_decisoes(c.get("metodo") or {}, trechos, str(cfg.get("_caminho", "obra.json"))),
                  de_valas(redes_vala or []))
    if (Path(out) / "retornos_gavetas").is_dir():                       # fatos da IA: inferidos, com executor e trecho
        base = juntar(base, _conciliar_com_a_base(de_retornos(Path(out) / "retornos_gavetas"), base))
    erros = gavetas.conferir_base(base)
    pasta = Path(out) / "base"
    anterior = gavetas.ler(pasta)["servicos"] if (pasta / "servicos.parquet").exists() else None
    servicos, pend_calculo, est = gavetas.calcular_incremental(base, anterior)
    difs = (gavetas.paridade(base, aplicados, furos, servicos=servicos)          # compara o que vai para a EAP
            + paridade_valas(base, redes_vala or [], servicos=servicos))
    base["pendencias"] = base["pendencias"] + pend_calculo
    pasta.mkdir(parents=True, exist_ok=True)
    gavetas.gravar(pasta, {**base, "servicos": servicos})
    resumo = {**_resumo(base, erros, difs, servicos), **est}
    (Path(out) / "paridade.json").write_text(json.dumps(difs, ensure_ascii=False, indent=1), encoding="utf-8")
    (Path(out) / "resumo.json").write_text(json.dumps(resumo, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"Gavetas: {len(base['objetos'])} objetos, {len(base['fatos'])} fatos, {len(base['pendencias'])} pendências, "
        f"{len(servicos)} serviços, {len(erros)} erros de conferência, {len(difs)} diferenças de paridade")
    return {**resumo, "eap_html": eap_html.montar(base, servicos, base["pendencias"], resumo)}   # aba EAP do HTML


def metadados() -> dict:
    """Rastreabilidade do método (regra 9 do estilo)."""
    return {
        "modulo": "extrair_gavetas",
        "descricao": "leitores (planilha de obras lineares, sondagens, decisões) gravam objetos, fatos e evidências "
                     "nas gavetas; valor ausente não vira fato; retornos de IA entram como inferido e a recusa vira pendência",
        "funcoes": ["de_obras_lineares", "de_sondagens", "de_decisoes", "de_valas", "paridade_valas", "de_retornos", "juntar", "etapa"],
        "conceitos": ["gavetas.json", "de_para_extracao.json"],
    }
