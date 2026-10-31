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

import hashlib
import json
import re
import time
from pathlib import Path

from . import inventario, pdf_cad

FONTES = json.loads((pdf_cad.CONCEITOS / "fontes.json").read_text(encoding="utf-8"))
ESCADA = {d["situacao"]: d for d in FONTES["escada"]}
ESPERADOS = json.loads((pdf_cad.CONCEITOS / "documentos_esperados.json").read_text(encoding="utf-8"))["tipologias"]
SISTEMAS = json.loads((pdf_cad.CONCEITOS / "unidades_construtivas.json").read_text(encoding="utf-8"))["sistemas"]


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


def _ausentes(item: dict, campos: list) -> list[str]:
    """Campos (com ponto para o aninhado: carimbo.escala) que o item não tem; `texto` só vale com 'sim' ou com o texto
    devolvido por retorno (qualquer coisa que não seja o aviso de pouco texto)."""
    faltam = []
    for campo in campos:
        raiz, _, sub = campo.partition(".")
        valor = (item.get(raiz) or {}).get(sub) if sub else item.get(raiz)
        if raiz == "texto" and (not isinstance(valor, str) or valor.startswith("pouco ou nenhum")):
            valor = None
        if not valor:
            faltam.append(campo)
    return faltam


def _faltando(item: dict, exige: dict) -> list[str]:
    """Campos exigidos pela classe que a leitura não trouxe (carimbo.titulo, texto, abas…)."""
    return _ausentes(item, exige.get({"ler_pdf": "pdf", "ler_planilha": "planilha", "ler_zip": "zip"}.get(item.get("leitor"), ""), []))


def papel(item: dict, pastas: dict | None) -> str | None:
    """Papel da pasta raiz do arquivo (licitacao, orcamento, obra, referencia) pelo prefixo MAIS LONGO de
    `pasta_drive`, sem acento e sem caixa: '01. RECEBIDOS/ORDENS' vale mais que '01. RECEBIDOS'. O prefixo só casa
    em limite de pasta ('01. REC' não casa '01. RECEBIDOS'); prefixo vazio casa qualquer pasta e perde para qualquer prefixo mais longo. Sem casar, None: a pasta não tem papel declarado."""
    pasta = inventario.normalizar(item.get("pasta_drive") or "").strip("/")
    achados = [(len(chave), valor) for prefixo, valor in (pastas or {}).items()
               for chave in [inventario.normalizar(prefixo).strip("/")]
               if not chave or pasta == chave or pasta.startswith(chave + "/")]
    return max(achados)[1] if achados else None


def avaliar(item: dict, pastas: dict | None = None) -> dict:
    """Estado da extração do arquivo e a situação que decide o próximo passe da escada; `pastas` acrescenta o papel."""
    cl = next(c for c in FONTES["classes"] if c["id"] == classe(item))
    if not item["situacao"].startswith("no disco"):
        estado, situacao, faltam = "fora do disco", "fora do disco", []
    elif item.get("erro"):
        estado, situacao, faltam = "falhou", "falhou", [item["erro"]]
    elif cl.get("dispensa_leitura"):
        estado, situacao, faltam = "completa", None, []
    elif not item.get("leitor"):
        retorno = cl.get("retorno") or []          # sem leitor: só a IA completa, pelos campos de `retorno` da classe
        faltam = _ausentes(item, retorno) if retorno else []
        if retorno and not faltam:
            estado, situacao = "completa", None
        else:
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
            "situacao": situacao, "proximo": passo and passo["proximo"], "acao": passo and passo["acao"],
            **({"papel": papel(item, pastas)} if pastas is not None else {})}


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


def ler_complementos(caminho: str | Path) -> dict:
    """`complementos.json` da obra: {"<pasta_drive>/<arquivo>": {campos, executor, degrau, tentativas}}; vazio se não existe."""
    caminho = Path(caminho)
    return json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}


def _mesclar(base: dict, campos: dict) -> dict:
    """Cópia de `base` com `campos` por cima; dict dentro de dict (carimbo.escala) é mesclado, não substituído."""
    novo = dict(base)
    for k, v in campos.items():
        novo[k] = _mesclar(novo[k], v) if isinstance(v, dict) and isinstance(novo.get(k), dict) else v
    return novo


def gravar_complemento(caminho: str | Path, item: dict, campos: dict, executor: str, degrau: str,
                       marca: str | None = None) -> dict:
    """Acrescenta/atualiza a entrada do item em `complementos.json`: mescla `campos`, soma 1 em `tentativas[degrau]` e
    guarda `executor` e `degrau` da última vez; `marca` (hash de um retorno aplicado) entra em `retornos_aplicados`.
    O cache do inventário não é tocado. Devolve a entrada gravada."""
    caminho = Path(caminho)
    todos = ler_complementos(caminho)
    chave = f"{item.get('pasta_drive')}/{item['arquivo']}"
    antigo = todos.get(chave, {})
    tentativas = {**antigo.get("tentativas", {})}
    tentativas[degrau] = tentativas.get(degrau, 0) + 1
    aplicados = antigo.get("retornos_aplicados", []) + ([marca] if marca else [])
    todos[chave] = {**antigo, "campos": _mesclar(antigo.get("campos", {}), campos), "executor": executor,
                    "degrau": degrau, "tentativas": tentativas, **({"retornos_aplicados": aplicados} if aplicados else {})}
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(todos, ensure_ascii=False, indent=1), encoding="utf-8")
    return todos[chave]


def pendencias(inv: dict, pastas: dict | None = None, complementos: dict | None = None) -> dict:
    """A lista que abre cada rodada: tudo que não está completo, com o próximo passe, e as séries incompletas;
    com `pastas`, conta também os arquivos por papel; com `complementos` (`ler_complementos`), cada item recebe os
    campos já complementados antes de avaliar e a avaliação traz `complementado_por`; `itens` devolve os itens mesclados."""
    complementos = complementos or {}
    itens, av = [], []
    for i in inv["itens"]:
        c = complementos.get(f"{i.get('pasta_drive')}/{i['arquivo']}")
        itens.append(_mesclar(i, c["campos"]) if c else i)
        av.append({**avaliar(itens[-1], pastas), **({"complementado_por": c["executor"]} if c else {})})
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
    por_papel = {}
    for a in av if pastas is not None else []:
        rotulo = a["papel"] or "sem papel"
        por_papel[rotulo] = por_papel.get(rotulo, 0) + 1
    return {"itens": itens, "avaliacoes": av, "pendencias": abertas, "fora_do_escopo": fora_do_escopo, "series": series(itens),
            "por_estado": contagem, "por_classe": por_classe,
            **({"por_papel": por_papel} if pastas is not None else {}),
            "fracao_completa": round(sum(a["estado"] == "completa" for a in no_escopo) / max(len(no_escopo), 1), 3)}


def _texto(item: dict) -> str:
    """O que `inventario.procurar` olha em cada arquivo: pasta, nome e título do carimbo, sem acento."""
    return inventario.normalizar(f"{item['pasta_drive']} {item['arquivo']} {(item.get('carimbo') or {}).get('titulo') or ''}")


def _do_sistema(item: dict, sistema: dict) -> bool:
    """O arquivo pertence ao sistema: casa uma das `chaves` (o '~' inicial só marca chave fraca) e nenhum `exclui`."""
    texto = _texto(item)
    chaves = "|".join(f"(?:{c.lstrip('~')})" for c in sistema["chaves"])
    exclui = "|".join(f"(?:{e})" for e in sistema.get("exclui", []))
    return bool(re.search(chaves, texto, re.IGNORECASE)) and not (exclui and re.search(exclui, texto, re.IGNORECASE))


def _situacao_do_documento(achados: list, doc: dict, listagem: dict) -> tuple[str, str]:
    """no disco | fora do disco | não achado, e a resposta que cita a listagem inteira (como `procurar`)."""
    if not achados:
        return "não achado", (f"nenhum dos {len(listagem['itens'])} arquivos da listagem ({listagem.get('fonte', 'itens mesclados')}) casa "
                              f"com o sistema e '{doc['termos']}': ausência conferida na listagem inteira")
    if any(i["situacao"].startswith("no disco") for i in achados):
        return "no disco", f"{len(achados)} arquivo(s) casam"
    return "fora do disco", f"{len(achados)} arquivo(s) casam, todos fora do disco: existem, não foram lidos"


def esperado_x_encontrado(inv: dict, sistemas: dict | None = None) -> list[dict]:
    """Para cada sistema e cada documento que a tipologia exige (`documentos_esperados.json`), o que a listagem
    inteira tem: arquivos do sistema (chaves) que também casam os termos do documento. Uma linha por par."""
    linhas = []
    for chave, sis in (SISTEMAS if sistemas is None else sistemas).items():
        do_sistema = [i for i in inv["itens"] if _do_sistema(i, sis)]
        for doc in ESPERADOS.get(sis["tipologia"], {}).get("documentos", []):
            achados = [i for i in do_sistema if re.search(doc["termos"], _texto(i), re.IGNORECASE)]
            situacao, resposta = _situacao_do_documento(achados, doc, inv)
            linhas.append({"sistema": chave, "nome": sis["nome"], "tipologia": sis["tipologia"], "documento": doc["id"],
                           "situacao": situacao, "arquivos": [i["arquivo"] for i in achados], "resposta": resposta})
    return linhas


def _norm(texto: str) -> str:
    """Sem acento, minúsculas e espaços colapsados: a forma em que o trecho citado é comparado com a página."""
    return " ".join(inventario.normalizar(texto or "").lower().split())


def _confere_citacao(item: dict, citacao: dict) -> tuple[bool, str]:
    """(aceita, nota): PDF no disco com texto na página exige o trecho nela; imagem, SHX ou outro formato não se confere."""
    caminho = item.get("caminho")
    if not caminho or Path(caminho).suffix.lower() != ".pdf" or not Path(caminho).exists():
        return True, "não conferível (imagem ou sem texto)"
    import pymupdf
    pagina = int(citacao.get("pagina") or 1)
    with pymupdf.open(caminho) as doc:
        texto = doc[pagina - 1].get_text() if 1 <= pagina <= len(doc) else ""
    if not texto.strip():
        return True, "não conferível (imagem ou sem texto)"
    if _norm(citacao.get("trecho", "")) and _norm(citacao["trecho"]) in _norm(texto):
        return True, f"conferida na página {pagina}"
    return False, f"trecho não está na página {pagina}"


def _marca(linha: dict) -> str:
    """Hash da linha de retorno: identifica a mesma linha numa rodada seguinte."""
    return hashlib.sha1(json.dumps(linha, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _aninhar(campos: dict) -> dict:
    """{'carimbo.escala': '1:100'} vira {'carimbo': {'escala': '1:100'}}."""
    saida = {}
    for nome, valor in campos.items():
        alvo = saida
        *caminho, folha = nome.split(".")
        for parte in caminho:
            alvo = alvo.setdefault(parte, {})
        alvo[folha] = valor
    return saida


def _um_retorno(linha: dict, item: dict | None, out: Path, rel: dict) -> None:
    """Confere e grava uma linha de retorno, anotando recusa ou campo ignorado em `rel`. Aceito ou recusado, o retorno
    conta uma tentativa do agente (`<executor>:retorno`, a chave do degrau na escada): sem isso a pendência ficaria
    pedida ao mesmo agente para sempre."""
    arquivo, executor = linha.get("arquivo"), linha.get("executor")
    if item is None or not executor:
        rel["recusados"].append({"arquivo": arquivo, "motivo": "arquivo fora do inventário" if item is None
                                 else "retorno sem executor"})
        return
    permitidos = next(c for c in FONTES["classes"] if c["id"] == classe(item)).get("retorno") or []
    campos = {k: v for k, v in (linha.get("campos") or {}).items() if k in permitidos}
    rel["ignorados"] += [{"arquivo": arquivo, "campo": k} for k in (linha.get("campos") or {}) if k not in permitidos]
    ok, nota = _confere_citacao(item, linha.get("citacao") or {}) if campos else (False, "nenhum campo de retorno da classe")
    gravar_complemento(out / "complementos.json", item, _aninhar(campos) if ok else {}, executor, f"{executor}:retorno",
                       marca=_marca(linha))
    if not ok:
        rel["recusados"].append({"arquivo": arquivo, "motivo": nota})
        return
    rel["aceitos"] += 1
    rel["citacoes"].append({"arquivo": arquivo, "citacao": nota})


def aplicar_retornos(out: str | Path, inv: dict) -> dict:
    """Aplica as linhas de `out/retornos/*.jsonl` ({arquivo, pasta_drive, executor, campos, citacao}) ao registro:
    arquivo tem de estar no inventário, só entram campos de `retorno` da classe, e a citação é conferida na página
    (PDF com texto). Linha já aplicada (hash em `retornos_aplicados`) é pulada. Devolve aceitos, recusados, ignorados."""
    out = Path(out)
    rel = {"aceitos": 0, "recusados": [], "ignorados": [], "citacoes": []}
    por_chave = {(i.get("pasta_drive"), i["arquivo"]): i for i in inv["itens"]}
    for arq in sorted((out / "retornos").glob("*.jsonl")):
        for texto in arq.read_text(encoding="utf-8").splitlines():
            if not texto.strip():
                continue
            linha = json.loads(texto)
            item = por_chave.get((linha.get("pasta_drive"), linha.get("arquivo")))
            antigo = ler_complementos(out / "complementos.json").get(f"{linha.get('pasta_drive')}/{linha.get('arquivo')}", {})
            if _marca(linha) not in antigo.get("retornos_aplicados", []):
                _um_retorno(linha, item, out, rel)
    return rel


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


def registrar_por_executor(avaliacoes: list, caminho: Path, passe: str) -> int:
    """Registra cada avaliação com quem a completou (`complementado_por`, senão "código"): o histórico mostra o que saiu
    só por código e o que precisou de IA. Usado pelo build e pelo executor da escada."""
    quem = lambda a: a.get("complementado_por") or "código"
    return sum(registrar([a for a in avaliacoes if quem(a) == q], caminho, passe=passe, executor=q)
               for q in sorted({quem(a) for a in avaliacoes}))


def metadados() -> dict:
    """Rastreabilidade das regras da reavaliação (regra 9 do estilo)."""
    return {"modulo": "extracao",
            "descricao": "classe da fonte, estado da extração, próximo passe da escada, séries de folhas e registro",
            "funcoes": ["classe", "papel", "avaliar", "series", "ler_complementos", "gravar_complemento", "aplicar_retornos", "pendencias", "esperado_x_encontrado", "registrar"],
            "premissas": [{"aplicacao": {"classe": ["conceitos/fontes.json classes"], "avaliar": ["satisfatoria", "escada"]},
                           "fonte": FONTES["metadata"]["fonte"]},
                          {"aplicacao": {"esperado_x_encontrado": ["conceitos/documentos_esperados.json tipologias",
                                                                    "conceitos/unidades_construtivas.json chaves, exclui"]},
                           "fonte": "documentos_esperados.json (estado premissa)"},
                          {"aplicacao": {"ler_complementos": ["saida/<obra>/complementos.json"],
                                         "gravar_complemento": ["tentativas por degrau", "campos aninhados mesclados"],
                                         "pendencias": ["complementos mesclados sobre o item antes de avaliar"]},
                           "fonte": "plano rodada 20, E1 (o cache guarda só a leitura básica)"},
                          {"aplicacao": {"aplicar_retornos": ["saida/<obra>/retornos/*.jsonl", "retorno por classe em fontes.json",
                                                               "citação conferida no texto da página (pymupdf)"],
                                         "avaliar": ["arquivo sem leitor: completo se tem os campos de retorno da classe"]},
                           "fonte": "plano rodada 20, E5 (a IA devolve campos com citação; o código confere)"},
                          {"aplicacao": {"papel": ["obra.json inventario.pastas: prefixo de pasta mais longo"]},
                           "fonte": "convenção do Caio (docs/ARQUITETURA.md §2)"}],
            "ultima_revisao": "2026-10-30"}
