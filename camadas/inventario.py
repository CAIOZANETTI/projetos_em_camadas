"""Inventário determinístico dos projetos de uma obra: nenhum arquivo fica de fora sem aparecer.

A referência é a **listagem do Drive** (todos os itens, gravada pela ingestão), não o que foi baixado. Todo arquivo
entra (PDF, planilha, zip, DWG, imagem…); pasta não. Cada um diz o que tem pelo leitor do seu tipo (`LEITORES`) ou
fica "sem leitor", à vista. Ausência só se afirma por `procurar`: "não baixado" não é "não existe". Para cada PDF:
situação (no disco / falhou no download / não tentado), formato da folha (A0–A4, estendido), páginas, layers CAD,
texto ou SHX, código Sanepar (sequência, disciplina, tipo de documento, revisão), o carimbo lido no canto inferior
direito (texto do PDF; OCR quando o texto vem em traço) e o tipo: planta (vai ao mapa), detalhe (fica em Projeto) ou
documento.

Uso:
    python -m camadas.inventario exemplos/foz/obra.json        # imprime o resumo por disciplina
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

from . import pdf_cad

# séries ISO 216 em mm (lado maior, lado menor)
FORMATOS_MM = {"A0": (1189, 841), "A1": (841, 594), "A2": (594, 420), "A3": (420, 297), "A4": (297, 210)}
CARIMBO_MM = (200, 115)          # largura e altura da região do carimbo, a partir do canto inferior direito
LEITURA_VERSAO = 2               # sobe quando o leitor muda: o cache antigo deixa de valer e o arquivo é relido
LIMIAR_PALAVRAS = 20             # página com ao menos isto de palavras tem texto
MESES = "JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ"
# fonte ArialMT sem ToUnicode das pranchas Sanepar: caracteres acima do deslocamento de 29, lidos nas próprias folhas
# ('*(27e&1,&2' = 'GEOTÉCNICO', 'FUNDAd­O' = 'FUNDAÇÃO', 'ÈREA' = 'ÁREA', 'MÏD' = 'MÓD', '081,&Ë3,2' = 'MUNICÍPIO')
ACENTOS_FONTE = {"È": "Á", "e": "É", "d": "Ç", "\xad": "Ã", "Ï": "Ó", "Ë": "Í", "Ç": "Ê", "Ð": "Ô", "i": "á",
                 "\x83": "º"}


def normalizar(nome: str) -> str:
    """Chave de comparação de nomes de arquivo: sem acento (NFD/NFC do Drive), minúscula, sem espaço nas pontas."""
    s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
    return s.strip().lower()


def formato_folha(largura_pt: float, altura_pt: float) -> dict:
    """A0–A4 pelo lado menor (±3 %); lado maior acima do padrão = estendido. 1 pt = 25,4/72 mm."""
    mm = sorted((largura_pt * 25.4 / 72, altura_pt * 25.4 / 72), reverse=True)
    for nome, (longo, curto) in FORMATOS_MM.items():
        if abs(mm[1] / curto - 1) <= 0.03:
            sufixo = "" if mm[0] <= longo * 1.03 else " estendido"
            return {"formato": nome + sufixo, "mm": [round(mm[0]), round(mm[1])],
                    "orientacao": "paisagem" if largura_pt >= altura_pt else "retrato"}
    return {"formato": "fora do padrão", "mm": [round(mm[0]), round(mm[1])],
            "orientacao": "paisagem" if largura_pt >= altura_pt else "retrato"}


def codigo_sanepar(nome: str) -> dict | None:
    """SEQ-SAA-XXXX-XXXX-DISC[-TIPO]-DESCRIÇÃO-Rn (ex.: 004-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYOUTPROCES-R5)."""
    m = re.match(r"(?P<seq>\d{2,3}A?)-SAA-(?P<u1>\d{4})-(?P<u2>\d{4})-(?P<disc>[A-Z]{4})-(?:(?P<tipo>[A-Z]{2})-)?"
                 r"(?P<desc>.+?)-R(?P<rev>\d+)", Path(nome).stem.upper())
    if not m:
        return None
    return {"sequencia": m["seq"], "unidade": f"{m['u1']}-{m['u2']}", "disciplina": m["disc"], "tipo": m["tipo"] or "DE",
            "descricao": m["desc"], "revisao": int(m["rev"])}


def _vogais(s: str) -> float:
    letras = [c for c in s if c.isalpha()]
    return sum(c in "aeiouAEIOU" for c in letras) / len(letras) if letras else 0.0


def desembaralhar(trecho: str) -> str:
    """Fonte sem ToUnicode correto (Foz: pranchas PBGE, PBEA, PBHI 2020): cada caractere vem 29 posições abaixo
    ('&RPSDQKLD' = 'Companhia'; '352-(72' = 'PROJETO'; espaço = \\x03) e os acentos por uma tabela fixa da fonte
    (`ACENTOS_FONTE`). Só troca trecho com caractere de controle, com símbolo que não aparece dentro de palavra
    ($ & ' ( ) * + %) ou só de letras quase sem vogal, e quando o resultado tem vogais; texto normal fica intacto
    ('SETEMBRO/2020' viraria 'pbqbj_olLOMOM')."""
    if re.fullmatch(r"[\d\s/.:,\-]*", trecho):          # data e número não se mexem ('09/2020' viraria 'MVLOMOM')
        return trecho
    trocado = "".join(chr(ord(c) + 29) if ord(c) <= 93 and c not in "\n\r " else ACENTOS_FONTE.get(c, c) for c in trecho)
    controle = any(ord(c) < 32 and c not in "\n\r\t" for c in trecho)
    simbolo = any(c in "$&'()*+%" for c in trecho)          # maiúsculas embaralhadas viram pontuação ('352-(72')
    sem_vogal = sum(c.isalpha() for c in trecho) >= 4 and _vogais(trecho) < 0.15          # '6DQHDPHQWR'
    if controle or (simbolo and _vogais(trocado) >= 0.25) or (sem_vogal and _vogais(trocado) >= 0.35):
        return trocado
    return trecho


def texto_carimbo(pagina) -> tuple[str, bool]:
    """Texto da região do carimbo (canto inferior direito, na folha exibida), em ordem de leitura; e se houve reparo
    de fonte embaralhada."""
    import pymupdf
    R = pagina.rotation_matrix
    W, H = pagina.rect.width, pagina.rect.height
    larg, alt = (v * 72 / 25.4 for v in CARIMBO_MM)
    palavras, reparado = [], False
    for bloco in pagina.get_text("rawdict")["blocks"]:          # rawdict: guarda o \\x03 (espaço embaralhado)
        for linha in bloco.get("lines", []):
            for span in linha["spans"]:
                r = pymupdf.Rect(span["bbox"]) * R
                bruto = "".join(c["c"] for c in span["chars"])
                if r.x1 >= W - larg and r.y1 >= H - alt and bruto.strip():
                    t = desembaralhar(bruto)
                    reparado |= t != bruto
                    palavras.append((round(r.y0 / 4), r.x0, t.strip()))
    palavras.sort()
    return " ".join(p[2] for p in palavras), reparado


def ocr_carimbo(pagina, dpi: int = 200) -> str:
    """Carimbo em traço (SHX): renderiza a região e lê com tesseract (português)."""
    import pymupdf
    import pytesseract
    from PIL import Image
    W, H = pagina.rect.width, pagina.rect.height
    larg, alt = (v * 72 / 25.4 for v in CARIMBO_MM)
    clip = pymupdf.Rect(max(0.0, W - larg), max(0.0, H - alt), W, H)    # clip e imagem já na folha exibida
    pix = pagina.get_pixmap(dpi=dpi, clip=clip)
    if pix.width < 10 or pix.height < 10:
        return ""
    img = Image.frombytes("RGB" if pix.n < 4 else "RGBA", (pix.width, pix.height), pix.samples)
    return " ".join(pytesseract.image_to_string(img, lang="por", config="--psm 6").split())


def campos_carimbo(texto: str) -> dict:
    """Folha n/m, escala, data e título a partir do texto do carimbo. O título no modelo Sanepar fica entre
    'PROJETO / UNIDADE CONSTRUTIVA:' e 'ESCALA:'; sem esses rótulos em texto (modelo PBHI 2020, AAT06), entre
    'ABASTECIMENTO DE ÁGUA' (e a data) e a escala ou a empresa. Sem nenhum dos dois fica None (o texto bruto vai
    junto)."""
    t = " ".join(texto.split())
    folha = None
    m = re.search(r"FOLHA\s*N[°ºo]?\s*:?\s*.{0,40}?\b(\d{1,3})\s*/\s*(\d{1,3})\b(?!\s*/)", t, re.IGNORECASE)
    for a, b in ([m.groups()] if m else []) + re.findall(r"(?<![\d/.])(\d{1,3})\s*/\s*(\d{1,3})(?![\d/.])", t):
        if 0 < int(a) <= int(b) <= 300:
            folha = f"{a}/{b}"
            break
    escala = re.search(r"1\s*:\s*\d{2,5}|INDICAD[AO]|SEM ESCALA|S/\s*ESC", t, re.IGNORECASE)
    data = re.search(rf"\b\d{{2}}[/.]\d{{2}}[/.]\d{{4}}\b|\b(?:{MESES})[A-ZÇ]*\s*/\s*\d{{4}}\b|\b\d{{2}}/\d{{4}}\b", t,
                     re.IGNORECASE)
    titulo = None
    fim = r"(?:ESCALA|S/\s*ESC|INDICAD|1\s*:\s*\d|GER[ÊE]NCIA|EMPRESA|ENGENHEIROS|$)"
    m = (re.search(r"UNIDADE CONSTRUTIVA\s*:(.{8,}?)" + fim, t, re.IGNORECASE) or
         re.search(rf"ABASTECIMENTO\s*DE\s*.GUA\s+(?:(?:{MESES})[A-ZÇ]*/\d{{4}}\s+|\d{{2}}/\d{{4}}\s+)?(.{{8,}}?)"
                   + fim, t, re.IGNORECASE))
    if m:
        titulo = re.sub(rf"\bDATA\s*:|\b\d{{2}}[/.]\d{{2}}[/.]\d{{4}}\b|\b(?:{MESES})[A-ZÇ]*\s*/\s*\d{{4}}\b", "",
                        m.group(1), flags=re.IGNORECASE)
        titulo = " ".join(titulo.split()) or None
    return {"folha": folha, "escala": escala.group(0).upper() if escala else None,
            "data": data.group(0).upper() if data else None, "titulo": titulo}


def _carimbo_da_pagina(pg, ocr: bool) -> dict:
    """Campos do carimbo de uma página: texto do PDF e, só se faltar texto e `ocr`, OCR (nunca derruba a leitura)."""
    texto, reparado = texto_carimbo(pg)
    fonte = "texto do PDF" + (" (fonte embaralhada, reparada)" if reparado else "")
    if len(texto.split()) < 8 and ocr:
        try:
            texto, fonte = ocr_carimbo(pg), "OCR (carimbo em traço)"
        except ImportError:
            fonte = "sem texto e sem OCR (pip install pytesseract + tesseract-ocr-por)"
    return {**campos_carimbo(texto), "fonte": fonte, "texto": texto[:600]}


def ler_pdf(caminho: str | Path, ocr: bool = True, max_paginas: int = 20) -> dict:
    """Metadados de um PDF: páginas, formato da 1ª folha, layers, texto e carimbos. Lê até `max_paginas` porque a
    capa sem texto não pode decidir pelo documento todo: `texto` é "sim" se ≥ 50 % das páginas lidas têm texto."""
    import pymupdf
    doc = pymupdf.open(caminho)
    lidas = min(len(doc), max_paginas)
    com_texto, carimbos = 0, []
    for n in range(lidas):
        pg = doc[n]
        com_texto += len(pg.get_text("words")) >= LIMIAR_PALAVRAS
        carimbos.append({"pagina": n + 1, **_carimbo_da_pagina(pg, ocr)})
    pg = doc[0]
    return {"paginas": len(doc), **formato_folha(pg.rect.width, pg.rect.height), "layers": len(doc.get_ocgs() or {}),
            "texto": "sim" if lidas and com_texto / lidas >= 0.5 else "pouco ou nenhum (traço/SHX ou imagem)",
            "paginas_com_texto": com_texto, "carimbo": {k: v for k, v in carimbos[0].items() if k != "pagina"},
            "carimbos": carimbos}


def reler_carimbo(caminho: str | Path, dpi: int = 300) -> dict:
    """Degrau alternativo da escada: carimbo da 1ª página por OCR em `dpi` (o padrão de 200 dpi falha em traço fino).
    Devolve os campos de `campos_carimbo` + fonte."""
    import pymupdf
    texto = ocr_carimbo(pymupdf.open(caminho)[0], dpi=dpi)
    return {**campos_carimbo(texto), "fonte": f"OCR {dpi} dpi (carimbo em traço)", "texto": texto[:600]}


def ler_planilha(caminho: str | Path) -> dict:
    """Abas da planilha com a situação (visível ou oculta) e o tamanho usado: a aba oculta também é escopo."""
    import openpyxl
    wb = openpyxl.load_workbook(caminho, read_only=True)
    abas = [{"aba": ws.title, "estado": getattr(ws, "sheet_state", "visible"), "linhas": ws.max_row,
             "colunas": ws.max_column} for ws in wb.worksheets]
    wb.close()
    return {"abas": abas, "ocultas": sum(a["estado"] != "visible" for a in abas)}


def ler_zip(caminho: str | Path, amostra: int = 30) -> dict:
    """O que há dentro do zip sem extrair: contagem por extensão e os primeiros nomes. Zip é pasta, não arquivo."""
    import zipfile
    with zipfile.ZipFile(caminho) as z:
        nomes = [n for n in z.namelist() if not n.endswith("/")]
    por_ext = {}
    for n in nomes:
        e = Path(n).suffix.lower() or "(sem extensão)"
        por_ext[e] = por_ext.get(e, 0) + 1
    return {"arquivos_dentro": len(nomes), "por_extensao": por_ext, "amostra": nomes[:amostra]}


LEITORES = {".pdf": "ler_pdf", ".xlsx": "ler_planilha", ".xlsm": "ler_planilha", ".zip": "ler_zip"}


def ler_arquivo(caminho: Path, ocr: bool = True) -> dict:
    """O leitor do tipo do arquivo; sem leitor, o arquivo continua no inventário com `leitor: None`."""
    nome = LEITORES.get(caminho.suffix.lower())
    if not nome:
        return {"leitor": None}
    try:
        return {"leitor": nome, **(ler_pdf(caminho, ocr) if nome == "ler_pdf" else globals()[nome](caminho))}
    except Exception as erro:  # noqa: BLE001 — arquivo corrompido (qualquer leitor) não derruba o inventário: fica o motivo
        return {"leitor": nome, "erro": f"{type(erro).__name__}: {erro}"[:200]}


def procurar(inv: dict, padrao: str) -> dict:
    """Busca na listagem inteira (nome, pasta e título do carimbo), em qualquer situação. É a única forma de dizer
    que um documento não existe: a resposta cita a listagem, o padrão e o que está fora do disco."""
    rx = re.compile(normalizar(padrao), re.IGNORECASE)
    achados = [i for i in inv["itens"]
               if rx.search(normalizar(f"{i['pasta_drive']} {i['arquivo']} {(i.get('carimbo') or {}).get('titulo') or ''}"))]
    fora = [i for i in achados if not i["situacao"].startswith("no disco")]
    if not achados:
        resposta = f"nenhum dos {len(inv['itens'])} arquivos da listagem ({inv['fonte']}) casa com '{padrao}'"
    else:
        resposta = f"{len(achados)} arquivo(s) casam com '{padrao}'" + (
            f"; {len(fora)} fora do disco ({', '.join(sorted({i['situacao'] for i in fora}))}): existem, não foram lidos"
            if fora else "")
    return {"padrao": padrao, "achados": [{k: i.get(k) for k in ("arquivo", "pasta_drive", "mb", "situacao", "tipo")}
                                          for i in achados], "resposta": resposta}


def tipo_documento(nome: str, titulo: str | None, regras: dict) -> str:
    """planta (vai ao mapa) | detalhe (só em Projeto) | documento, por `conceitos/tipos_prancha.json`."""
    cod = codigo_sanepar(nome)
    if Path(nome).suffix.lower() != ".pdf" or (cod and cod["tipo"] != "DE"):
        return "documento"
    alvo = normalizar(f"{cod['descricao'] if cod else Path(nome).stem} {titulo or ''}").upper()
    if re.search(regras["planta"], alvo):
        return "planta"
    if cod or re.search(regras["detalhe"], alvo):
        return "detalhe"
    return "documento"


def _totais(itens: list) -> dict:
    """Contagens do inventário: arquivos por extensão, PDFs, situação, sem leitor e tipo."""
    pdfs = [i for i in itens if i["arquivo"].lower().endswith(".pdf")]
    por_extensao = {}
    for i in itens:
        e = Path(i["arquivo"]).suffix.lower() or "(sem extensão)"
        por_extensao[e] = por_extensao.get(e, 0) + 1
    totais = {"arquivos": len(itens), "por_extensao": por_extensao, "pdfs": len(pdfs),
              "sem_leitor": sum(i["situacao"].startswith("no disco") and not i.get("leitor") for i in itens),
              "no_disco": sum(i["situacao"].startswith("no disco") for i in itens),
              "falhou": sum(i["situacao"] == "falhou no download" for i in itens),
              "nao_tentado": sum(i["situacao"] == "não tentado" for i in itens),
              **{t: sum(i["tipo"] == t for i in itens) for t in ("planta", "detalhe", "documento")},
              "no_mapa": sum(bool(i["no_mapa"]) for i in itens),
              "plantas_fora_do_mapa": sum(i["tipo"] == "planta" and not i["no_mapa"] for i in itens)}
    return totais


def _leitura(memo: dict, p: Path, ocr: bool, reler: set) -> dict:
    """Leitura básica do arquivo, do cache quando vale. Assinatura = tamanho + mtime + `LEITURA_VERSAO`; entrada com
    `erro` ou caminho em `reler` é lida de novo (erro não é leitura definitiva). O cache não guarda complementos."""
    assinatura = f"{p.stat().st_size}:{int(p.stat().st_mtime)}:v{LEITURA_VERSAO}"
    antiga = memo.get(str(p), {})
    if antiga.get("assinatura") != assinatura or "erro" in antiga or str(p) in reler:
        memo[str(p)] = {"assinatura": assinatura, **ler_arquivo(p, ocr)}
    return {k: v for k, v in memo[str(p)].items() if k != "assinatura"}


COLUNAS_BAIXADOS = {"id", "ok"}


def disponivel(cfg: dict, log=print) -> bool:
    """A listagem do Drive existe e o `_baixados.csv`, se houver, tem as colunas `id` e `ok`. Senão, pendência no log
    (vai ao HTML) e o inventário fica de fora, sem derrubar o build (contêiner novo, ingestão parcial)."""
    import pandas as pd
    c = cfg["inventario"]
    if not Path(c["listagem"]).exists():
        log(f"Inventário: NÃO FEITO — falta a listagem do Drive {c['listagem']} (pendência; o build segue)")
        return False
    if c.get("baixados") and Path(c["baixados"]).exists():
        colunas = set(pd.read_csv(c["baixados"], sep=";", dtype=str, nrows=0).columns)
        if not COLUNAS_BAIXADOS <= colunas:
            log(f"Inventário: NÃO FEITO — {c['baixados']} sem as colunas {sorted(COLUNAS_BAIXADOS)} (pendência; o build segue)")
            return False
    return True


def inventario(cfg: dict, cache: Path | None = None, ocr: bool = True, log=print, reler: set | None = None) -> dict:
    """Loop determinístico sobre a listagem do Drive (`inventario.listagem` no obra.json) × arquivos em disco.

    Cache por arquivo (tamanho + data de modificação + versão da leitura) em `cache`, para não refazer OCR a cada
    build; `reler` é o conjunto de caminhos (str) que ignoram o cache.
    """
    reler = reler or set()
    import pandas as pd
    c = cfg["inventario"]
    lista = pd.read_csv(c["listagem"], sep=";", dtype=str).fillna("")
    lista = lista[lista["mimeType"] != "application/vnd.google-apps.folder"]
    falhas = set()
    if c.get("baixados") and Path(c["baixados"]).exists():
        b = pd.read_csv(c["baixados"], sep=";", dtype=str).fillna("")
        falhas = set(b.loc[b["ok"].str.lower() != "true", "id"])
    tentados = set(pd.read_csv(c["baixados"], sep=";", dtype=str)["id"]) if c.get("baixados") else set()
    locais = {}
    for p in Path(c["pasta"]).rglob("*"):
        if p.is_file() and not p.name.startswith("_"):            # _listagem_drive.csv e _baixados.csv são da ingestão
            locais.setdefault(normalizar(p.name), []).append(p)
    no_mapa = {normalizar(Path(q["pdf"]).name): q["id"] for q in cfg.get("pranchas", [])}
    regras = json.loads((pdf_cad.CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))
    memo = json.loads(cache.read_text(encoding="utf-8")) if cache and cache.exists() else {}
    itens = []
    for r in lista.itertuples():
        chave = normalizar(r.titulo)
        exato = Path(c["pasta"]) / r.caminho / r.titulo           # o disco espelha as pastas do Drive
        caminhos = [exato] if exato.exists() else locais.get(chave, [])
        item = {"arquivo": r.titulo, "pasta_drive": r.caminho, "id_drive": r.id,
                "mb": round(float(r.tamanho_bytes or 0) / 1e6, 2), "codigo": codigo_sanepar(r.titulo)}
        if caminhos:
            p = caminhos[0]
            item.update({"situacao": "no disco" if p == exato else "no disco (mesmo nome em outra pasta)", "caminho": str(p),
                         **_leitura(memo, p, ocr, reler)})
        else:
            item["situacao"] = ("falhou no download" if r.id in falhas else
                                "não tentado" if r.id not in tentados else "baixado mas não encontrado")
        titulo = (item.get("carimbo") or {}).get("titulo")
        item["tipo"] = tipo_documento(r.titulo, titulo, regras)
        item["grupo"], item["subgrupo"] = pdf_cad.disciplina_da_prancha(r.titulo, titulo or "")
        item["no_mapa"] = no_mapa.get(chave)
        itens.append(item)
    if cache:
        cache.write_text(json.dumps(memo, ensure_ascii=False), encoding="utf-8")
    sem_lista = sorted(k for k in locais if k not in {normalizar(t) for t in lista["titulo"]})
    totais = _totais(itens)
    log(f"Inventário: {totais['arquivos']} arquivos na listagem do Drive ({totais['pdfs']} PDFs), {totais['no_disco']} no "
        f"disco; {len(sem_lista)} arquivo(s) em disco fora da listagem; {totais['sem_leitor']} sem leitor")
    return {"itens": itens, "resumo": resumo(itens), "totais": totais, "fora_da_listagem": sem_lista,
            "fonte": c.get("fonte") or c["listagem"]}


def para_html(inv: dict) -> dict:
    """Versão enxuta para o visualizador (sem o texto bruto do carimbo)."""
    campos = ("arquivo", "pasta_drive", "mb", "situacao", "tipo", "grupo", "subgrupo", "no_mapa", "formato", "paginas",
              "leitor", "erro")
    return {**{k: inv[k] for k in ("resumo", "totais", "fora_da_listagem", "fonte")},
            "itens": [{**{k: i.get(k) for k in campos},
                       "carimbo": {k: (i.get("carimbo") or {}).get(k) for k in ("titulo", "folha", "data", "escala", "fonte")}}
                      for i in inv["itens"]]}


def resumo(itens: list) -> list[dict]:
    """Contagem por grupo › subgrupo: total, plantas, detalhes, documentos, no mapa e fora do disco."""
    linhas = {}
    for i in itens:
        l = linhas.setdefault((i["grupo"], i["subgrupo"]), {"grupo": i["grupo"], "subgrupo": i["subgrupo"], "total": 0,
                                                            "planta": 0, "detalhe": 0, "documento": 0, "no_mapa": 0,
                                                            "fora_do_disco": 0})
        l["total"] += 1
        l[i["tipo"]] += 1
        l["no_mapa"] += bool(i["no_mapa"])
        l["fora_do_disco"] += not i["situacao"].startswith("no disco")
    return sorted(linhas.values(), key=lambda l: (l["grupo"], l["subgrupo"]))


def metadados() -> dict:
    """Rastreabilidade das regras do inventário (regra 9 do estilo)."""
    return {
        "modulo": "inventario",
        "descricao": "inventário determinístico de todos os arquivos da obra: listagem do Drive × disco, leitor por tipo "
                     "(PDF: formato, código, carimbo; planilha: abas e ocultas; zip: conteúdo), busca que prova ausência",
        "funcoes": ["inventario", "ler_arquivo", "ler_pdf", "reler_carimbo", "ler_planilha", "ler_zip", "procurar",
                    "campos_carimbo",
                    "formato_folha", "codigo_sanepar", "tipo_documento", "desembaralhar", "resumo", "para_html"],
        "bibliografia": [
            {"obra": "ISO 216 / ABNT NBR 10068 — Folha de desenho: leiaute e dimensões", "ano": 1987,
             "editora": "ABNT", "aplicacao": {"formato_folha": ["FORMATOS_MM", "tolerância ±3 %"]}},
            {"obra": "ABNT NBR 10582 — Apresentação da folha para desenho técnico (legenda no canto inferior direito)",
             "ano": 1988, "editora": "ABNT", "aplicacao": {"texto_carimbo": ["CARIMBO_MM"]}},
            {"obra": "Smith — An Overview of the Tesseract OCR Engine", "ano": 2007, "editora": "ICDAR",
             "aplicacao": {"ocr_carimbo": ["lang=por", "--psm 6", "200 dpi"]}},
        ],
        "premissas": [
            {"aplicacao": {"campos_carimbo": ["MESES", "rótulos do modelo Sanepar"]},
             "fonte": "carimbos das pranchas da LE 211/2026 (modelo Sanepar: FOLHA N°, UNIDADE CONSTRUTIVA, DATA, ESCALA)"},
            {"aplicacao": {"desembaralhar": ["deslocamento de 29", "ACENTOS_FONTE", "vogais ≥ 0,25 / 0,35"]},
             "fonte": "pranchas PBGE de Foz: '&RPSDQKLD GH 6DQHDPHQWR' = 'Companhia de Saneamento'"},
            {"aplicacao": {"procurar": ["ausência só por consulta à listagem inteira"], "inventario": ["todo arquivo, não só PDF"]},
             "fonte": "Caio, 30/10/2026: a forma e a armadura do Actiflo 360 foram dadas como inexistentes e existiam "
                      "(pdca/licoes.jsonl L008)"},
            {"aplicacao": {"inventario": ["LEITURA_VERSAO na assinatura do cache", "erro no cache é relido", "reler"]},
             "fonte": "plano rodada 20, E1"},
            {"aplicacao": {"ler_pdf": ["max_paginas = 20", "LIMIAR_PALAVRAS = 20", "texto = sim se ≥ 50 % das páginas"],
                           "reler_carimbo": ["300 dpi"]},
             "fonte": "plano rodada 20, E2"},
        ],
        "ultima_revisao": "2026-10-30",
    }


def main(argv=None):
    cfg = json.loads(Path((argv or sys.argv[1:])[0]).read_text(encoding="utf-8"))
    r = inventario(cfg, Path(cfg.get("saida", "saida")) / "inventario_cache.json")
    print(f"{'grupo › subgrupo':45s} total planta detalhe doc. no_mapa fora_do_disco")
    for l in r["resumo"]:
        print(f"{l['grupo'] + ' › ' + l['subgrupo']:45s} {l['total']:5d} {l['planta']:6d} {l['detalhe']:7d} "
              f"{l['documento']:4d} {l['no_mapa']:7d} {l['fora_do_disco']:13d}")
    print(f"total: {len(r['itens'])}")


if __name__ == "__main__":
    main()
