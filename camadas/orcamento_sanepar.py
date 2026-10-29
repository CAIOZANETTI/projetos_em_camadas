#!/usr/bin/env python3
"""
camadas/orcamento_sanepar.py
============================
Extrai e estrutura o escopo de materiais/serviços da licitação Sanepar
LE 211/2026 - SAA Foz do Iguaçu (ETA Vila C + adutoras AAT06/AAT02/Vila C).

Lê as planilhas .xlsx LOCAIS (baixadas do Drive) e gera CSVs
(sep=';', decimal=',', utf-8-sig):

  escopo_itens.csv             um item folha por linha (MATS E EQUIP + CUSTO CIVIL)
  escopo_resumo.csv            nº de itens por unidade_obra x disciplina
  escopo_resumo_etapa.csv      nº de itens por unidade_obra x etapa_indicada x disciplina
  relacao_materiais_etapas.csv aba oculta 'Relação de Materiais' (qtd 1ª / 2ª etapa)
  cotacoes_itens.csv           itens das duas planilhas de cotação (sem preço)

Escopo do contrato, sem preço: nenhuma coluna de valor (unitário, total, montagem,
fornecedor) sai daqui — decisão do Caio (28/10/2026). A especificação vem do cadastro de
materiais Sanepar (`referencias/sanepar/catalogo_materiais.jsonl.gz`, gerado por
`gravar_catalogo` só com colunas de especificação).

Uso:
    python -m camadas.orcamento_sanepar PASTA
    python -m camadas.orcamento_sanepar --catalogo estudo_plan_orcamento.xlsx referencias/sanepar/catalogo_materiais.jsonl.gz

PASTA (padrão: a pasta deste script) deve conter:
    principal.xlsx                  (211 - SAA Foz do Iguaçú.xlsx)
    cotacao_materiais.xlsx          (Cotação de materiais)
    cotacao_pecas_especiais.xlsx    (Cotação de peças especiais; neste caso foi
                                     reconstruída a partir do texto do conector Drive
                                     por ../reconstruir_pecas_especiais.py)

Estrutura do orçamento principal (descoberta na análise):
  * 'MATS E EQUIP'  -> lista de materiais/equipamentos (as colunas de preço são ignoradas).
        cabeçalho na linha 6; blocos: ETA VILA C, ADUTORA AAT 06,
        ADUTORA AAT 02 VILA C, (XXX), ADUTORA AAT 02 VILA A, SISTEMA ACTIFLO
        (comportas/válvulas/juntas) e SISTEMA PNEUMÁTICO; dentro de cada bloco
        há "tabelas" numeradas (coluna F) ligadas a um desenho (coluna E).
  * 'CUSTO CIVIL'   -> serviços civis por Unidade > UC (unid. construtiva) >
        subgrupo. Quase todas as quantidades estão em branco (só urbanização
        está quantificada).
  * 'Relação de Materiais' (OCULTA) -> mesmas tabelas, com 'Quantidade 1ª
        etapa' e 'Quantidade 2ª etapa' (única indicação explícita de etapa).
  * 'Medição e Faturamento' / 'Marcos Cont.' -> Unidades Construtivas (UC 1..8)
        e "Fases executivas (licitações)".
"""
import os
import re
import sys
from collections import defaultdict

import openpyxl
import pandas as pd

# --------------------------------------------------------------------------
# Utilitários genéricos
# --------------------------------------------------------------------------

def num(x):
    """Converte para float se for numérico; senão None (texto/vazio/erro)."""
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    return None


def num_flex(x):
    """Como num(), mas aceita texto tipo '01 / 13,76' (pega o 1º número)."""
    v = num(x)
    if v is not None:
        return v
    if isinstance(x, str):
        m = re.search(r"\d+(?:[.,]\d+)?", x)
        if m:
            return float(m.group(0).replace(",", "."))
    return None


def txt(x):
    """Texto limpo (strip, sem quebras de linha) ou ''."""
    if x is None:
        return ""
    return re.sub(r"\s+", " ", str(x)).strip()


def achar_cabecalho(ws, rotulo="ITEM", max_linhas=15):
    """Localiza a linha de cabeçalho (célula == rotulo na coluna A..C).
    Retorna (linha, {nome_normalizado: indice_coluna_1based})."""
    for r in range(1, max_linhas + 1):
        vals = [txt(ws.cell(r, c).value).upper() for c in range(1, ws.max_column + 1)]
        if rotulo in vals[:3] and any("DESCRI" in v for v in vals):
            cols = {}
            for c, v in enumerate(vals, start=1):
                if v:
                    cols.setdefault(v, c)
            return r, cols
    raise ValueError(f"cabeçalho '{rotulo}' não encontrado em {ws.title}")


# --------------------------------------------------------------------------
# Extração de atributos da descrição: DN, material, disciplina
# --------------------------------------------------------------------------

def extrair_dn(desc):
    """Retorna (dn_mm, dn_tipo, dn_mm_2).
    - 'DN 300' / 'DN300' -> (300, 'DN', None); redução 'DN600 DN400' -> 2º em dn_mm_2
    - sem DN, mas 'DE 630' / 'DE32MM' (PEAD/PVC) -> (630, 'DE', None)
    """
    d = desc or ""
    dns = [int(x) for x in re.findall(r"\bDN\s*[:=]?\s*(\d{2,4})\b", d, re.IGNORECASE)]
    if dns:
        return dns[0], "DN", (dns[1] if len(dns) > 1 and dns[1] != dns[0] else None)
    des = re.findall(r"\bDE\s*[:=]?\s*(\d{2,4})(?:\s*MM)?\b", d, re.IGNORECASE)
    if des:
        return int(des[0]), "DE", None
    return None, "", None


# material pela coluna 'MATERIAL' da planilha (categoria do orçamento)
MAT_POR_CATEGORIA = {
    "TUBO FD": "FoFo/FD", "CONEXÃO FD": "FoFo/FD",
    "AÇO CARBONO": "Aço carbono", "AÇO INOX": "Aço inox",
    "FIBRA DE VIDRO": "PRFV",
    "TUBO PEAD": "PEAD", "CONEXÃO PEAD": "PEAD",
    "TUBO PVC": "PVC", "CONEXÃO PVC": "PVC",
    "CONCRETO": "Concreto",
}

# material por palavra-chave na descrição (ordem importa)
MAT_REGRAS = [
    (r"PRFV|FIBRA DE VIDRO", "PRFV"),
    (r"POLIETILENO|\bPEAD\b|\bPE\s?100\b", "PEAD"),
    (r"\bCPVC\b", "CPVC"),
    (r"\bPVC", "PVC"),
    (r"A[ÇC]O/FD", "Aço/FD"),
    (r"\bFD\b|FERRO D[ÚU]CTIL|FERRO FUNDIDO", "FoFo/FD"),
    (r"A[ÇC]O INOX|INOX|AISI", "Aço inox"),
    (r"A[ÇC]O CARBONO|ASTM A\d", "Aço carbono"),
    (r"GALV", "Aço galvanizado"),
    (r"\bFG\b", "Ferro galvanizado"),
    (r"ALUM[ÍI]NIO", "Alumínio"),
    (r"COBRE|BRONZE|LAT[ÃA]O", "Cobre/bronze/latão"),
    (r"CONCRETO|ASFALTO", "Concreto/asfalto"),
    (r"BORRACHA|EPDM", "Borracha"),
]


def classificar_material(categoria, desc):
    """Material predominante: 1) categoria da planilha; 2) palavras-chave."""
    cat = txt(categoria).upper()
    if cat in MAT_POR_CATEGORIA:
        return MAT_POR_CATEGORIA[cat]
    d = (desc or "").upper()
    for rx, mat in MAT_REGRAS:
        if re.search(rx, d):
            return mat
    if cat == "FIXAÇÃO":
        return "Aço (fixação)"
    return ""


def disciplina_mats(categoria, desc, bloco):
    """Disciplina de uma linha de MATS E EQUIP."""
    cat = txt(categoria).upper()
    d = (desc or "").upper()
    if cat in ("BOMBA", "BOMBA DOSADORA", "EQUIPAMENTO", "ACTIFLO", "MEDIDOR"):
        return "Equipamentos"
    if cat == "ELÉTRICA":
        if "POSTE" in d or "ILUMINA" in d:
            return "Elétrica"
        return "Automação"          # QEP / comando pneumático
    if cat == "AR COMPRIMIDO":
        if re.search(r"COMPRESSOR|CENTRAL DE PREPARA|RESERVAT[ÓO]RIO", d):
            return "Equipamentos"
        return "Hidromecânica"
    if cat == "CONCRETO":
        return "Civil"
    if cat == "FIBRA DE VIDRO":
        # guarda-corpo, escada, grade de piso: acessos/estrutura leve
        return "Civil"
    if cat == "DIVERSOS":
        if "PORTA" in d:
            return "Arquitetura"
        return "Hidromecânica" if re.search(r"TORNEIRA|MANGUEIRA|ADAPTADOR", d) else "Outros"
    if cat == "AÇO CARBONO" and re.search(r"GUARDA.?CORPO|ESCADA|GRADE|TAMPA DE PISO", d):
        return "Civil"
    if cat in ("TUBO FD", "CONEXÃO FD", "AÇO CARBONO", "AÇO INOX", "FIXAÇÃO", "TUBO PEAD",
               "CONEXÃO PEAD", "TUBO PVC", "CONEXÃO PVC", "JUNTA", "VÁLVULA", "REGISTRO",
               "TAMPÃO", "FG", "COMPORTA", "VENTOSA", "MANOMETRO"):
        return "Hidromecânica"
    return "Outros"


def disciplina_civil(cod, desc, grupo, subgrupo):
    """Disciplina de uma linha de CUSTO CIVIL (por código/descrição)."""
    d = (desc or "").upper()
    c = (cod or "").upper()
    s = (subgrupo or "").upper()
    if c == "PLANILHA":
        return "Hidromecânica"      # remete a MATS E EQUIP (fornec. + montagem)
    if c == "EMPREITA":
        return "Elétrica"
    if c == "DI" or "ADMINISTRAÇÃO LOCAL" in d:
        return "Serviços gerais"
    if "SONDAGEM" in d:
        return "Geotecnia"
    if re.search(r"ESTACA|FUNDA[ÇC]|SAPATA|RADIER|BLOCOS? DE (APOIO|ANCORAGEM)", d) or \
            re.search(r"BLOCOS? DE (APOIO|ANCORAGEM)", s):
        return "Fundação"
    if re.search(r"ESCAVA|REATERRO|ESCORAMENTO|REBAIXAMENTO|CARGA E DESCARGA|TRANSPORTE DE SOLOS|"
                 r"BOTA.?FORA|RASPAGEM|SUPRESS", d):
        return "Terraplenagem"
    if re.search(r"PAVIMENT|ASFALTO|GUIA DE CONCRETO|MEIO.?FIO", d) or "RECOMPOSIÇÃO DE PAVIMENTO" in s:
        return "Pavimentação"
    if re.search(r"CONCRETO|ARMA[ÇC][ÃA]O|FORMA|ESTRUTURA", d):
        return "Estrutura"
    if re.search(r"ALVENARIA|REVESTIMENTO|ESQUADRIA|PINTURA|COBERTURA|FORRO|PORTA|JANELA", d) or \
            re.search(r"GUARITA|ABRIGO|REFORMA", s):
        return "Arquitetura"
    if re.search(r"LOCA[ÇC][ÃA]O|ROÇADA|CA[ÇC]AMBA|INTERFER|LIMPEZA|LAVAGEM|CADASTRO|MOBILIZA", d):
        return "Serviços gerais"
    if "MEDIDOR" in d or "MEDIDORES" in s:
        return "Equipamentos"
    return "Outros"


def fonte_civil(cod):
    """Origem do preço em CUSTO CIVIL (inferida pelo padrão do código)."""
    c = txt(cod)
    if c.upper() in ("PLANILHA",):
        return "MATS E EQUIP (lump-sum)"
    if c.upper() == "EMPREITA":
        return "Empreita (cotação elétrica/automação)"
    if c.upper() == "DI":
        return "Custos indiretos (DI)"
    if re.fullmatch(r"\d{6}", c):
        return "SANEPAR tabela jun/2025 (inferido: código numérico em COMPOSIÇÕES)"
    if c:
        return "Composição própria (código alfanumérico)"
    return ""


# --------------------------------------------------------------------------
# Aba 'MATS E EQUIP'
# --------------------------------------------------------------------------

BLOCOS_TOPO = re.compile(r"^(ETA VILA C|ADUTORA AAT.*|XXX|SISTEMA ACTIFLO)$", re.IGNORECASE)


def unidade_do_bloco(bloco):
    """Unidade de obra (nomenclatura do edital/Resumo)."""
    b = (bloco or "").upper()
    if b.startswith("ADUTORA") or b == "XXX":
        return "UNIDADE 2 - Adutora de água tratada (AAT06/anéis)"
    return "UNIDADE 1 - ETA Vila C"


def etapa_da_descricao(desc):
    m = re.search(r"(\d)\s*ª\s*ETAPA", desc or "", re.IGNORECASE)
    return f"{m.group(1)}ª etapa" if m else ""


def extrair_mats(wb):
    """Itens folha de 'MATS E EQUIP' (linha com descrição e quantidade numérica)."""
    ws = wb["MATS E EQUIP"]
    hdr, cols = achar_cabecalho(ws)
    C = lambda nome: cols[nome]
    c_item, c_cod, c_loc, c_mat = C("ITEM"), C("CÓDIGO USMA"), C("LOCAL"), C("MATERIAL")
    c_proj, c_tab, c_desc, c_un, c_q = C("PROJETO"), C("TABELA"), C("DESCRIÇÃO"), C("UNID."), C("QUANT.")

    linhas = []
    bloco = ""
    tabela = ""
    nome_tabela = ""
    proj_hdr = ""
    sub_extra = ""      # sub-cabeçalho dentro do SISTEMA ACTIFLO / PNEUMÁTICO
    for r in range(hdr + 1, ws.max_row + 1):
        g = txt(ws.cell(r, c_desc).value)
        q = num(ws.cell(r, c_q).value)
        loc = txt(ws.cell(r, c_loc).value)
        e = txt(ws.cell(r, c_proj).value)
        f = txt(ws.cell(r, c_tab).value)
        if not g:
            continue
        if q is None:
            # ------ linha de cabeçalho (sem quantidade) ------
            if not e and not f and not loc:
                if BLOCOS_TOPO.match(g):
                    bloco, tabela, nome_tabela, sub_extra, proj_hdr = g, "", "", "", ""
                else:
                    sub_extra = g          # COMPORTAS / VÁLVULAS / MÓDULOS...
            elif loc.upper() == "PNEUMÁTICO" and g.upper().startswith("SISTEMA"):
                bloco, tabela, nome_tabela, sub_extra, proj_hdr = "SISTEMA PNEUMÁTICO", "", "", "", e
            elif loc.upper() == "PNEUMÁTICO":
                sub_extra = re.sub(r"^PROJETO:\s*", "", g, flags=re.IGNORECASE)
            else:
                tabela, nome_tabela, proj_hdr = f, g, e
                sub_extra = ""
            continue
        # ------ item folha ------
        desc = txt(ws.cell(r, c_desc).value)
        cat = txt(ws.cell(r, c_mat).value)
        if tabela:
            subgrupo = f"T{tabela} - {nome_tabela}"
        else:
            subgrupo = sub_extra
        dn, dn_tipo, dn2 = extrair_dn(desc)
        linhas.append({
            "aba": "MATS E EQUIP",
            "item": txt(ws.cell(r, c_item).value),
            "codigo": txt(ws.cell(r, c_cod).value),
            "fonte": "Orçamento (MATS E EQUIP)",
            "descricao": desc,
            "unidade": txt(ws.cell(r, c_un).value),
            "quantidade": q,
            "unidade_obra": unidade_do_bloco(bloco),
            "grupo": bloco,
            "subgrupo": subgrupo,
            "disciplina": disciplina_mats(cat, desc, bloco),
            "material": classificar_material(cat, desc),
            "dn_mm": dn,
            "etapa_indicada": etapa_da_descricao(desc),
            # ---- colunas extras (rastreabilidade) ----
            "dn_tipo": dn_tipo,
            "dn_mm_2": dn2,
            "categoria_planilha": cat,
            "local": loc,
            "tabela": f if f not in ("-",) else "",
            "projeto_desenho": e or proj_hdr,
            "etapa_fonte": "descrição do item" if etapa_da_descricao(desc) else "",
            "qtd_etapa1": None, "qtd_etapa2": None, "etapa_qtd_confere": "",
            "observacao": "",
            "linha_origem": r,
        })
    return linhas


# --------------------------------------------------------------------------
# Aba oculta 'Relação de Materiais' (quantidades por etapa)
# --------------------------------------------------------------------------

def extrair_relacao(wb):
    """Linhas da aba 'Relação de Materiais' com qtd 1ª/2ª etapa e etapa."""
    ws = wb["Relação de Materiais"]
    out = []
    for r in range(2, ws.max_row + 1):
        v = [ws.cell(r, c).value for c in range(1, 20)]
        if not any(x not in (None, "") for x in v):
            continue
        q1, q2 = num_flex(v[6]), num_flex(v[7])
        if (q1 or 0) > 0 and not (q2 or 0) > 0:
            et = "1ª etapa"
        elif (q2 or 0) > 0 and not (q1 or 0) > 0:
            et = "2ª etapa"
        elif (q1 or 0) > 0 and (q2 or 0) > 0:
            et = "1ª e 2ª etapa"
        else:
            et = ""
        out.append({
            "linha_origem": r, "item": txt(v[0]), "codigo": txt(v[1]), "local": txt(v[2]),
            "material_cat": txt(v[3]), "descricao": txt(v[4]), "unidade": txt(v[5]),
            "qtd_etapa1": q1, "qtd_etapa2": q2, "qtd_etapa2_texto": txt(v[7]) if num(v[7]) is None else "",
            "etapa": et, "tabela": txt(v[8]), "nome_tabela": txt(v[9]),
            "descricao_sanepar": txt(v[10]), "unidade_sanepar": txt(v[11]),
            "marcas_homologadas": txt(v[13]), "familia": txt(v[15]), "categoria": txt(v[16]),
            "subcategoria": txt(v[17]), "material_base": txt(v[18]),
        })
    return out


def anexar_etapas(mats, relacao):
    """Cruza MATS E EQUIP x Relação de Materiais pela chave (tabela, item, código),
    consumindo em ordem quando a chave se repete. Preenche etapa_indicada."""
    idx = defaultdict(list)
    for rr in relacao:
        idx[(rr["tabela"], rr["item"], rr["codigo"])].append(rr)
    casados = 0
    for m in mats:
        chave = (m["tabela"], m["item"], m["codigo"])
        lista = idx.get(chave)
        if not lista:
            continue
        rr = lista.pop(0)
        casados += 1
        m["qtd_etapa1"], m["qtd_etapa2"] = rr["qtd_etapa1"], rr["qtd_etapa2"]
        # Na prática o orçamento usa a quantidade da 1ª etapa (812 de 833 itens conferem
        # com 'Quantidade 1ª etapa'); a soma 1ª+2ª só é testada como alternativa.
        q1, q2 = rr["qtd_etapa1"] or 0, rr["qtd_etapa2"] or 0
        if abs(q1 - m["quantidade"]) < 1e-6:
            m["etapa_qtd_confere"] = "sim (=qtd 1ª etapa)"
        elif abs(q1 + q2 - m["quantidade"]) < 1e-6:
            m["etapa_qtd_confere"] = "sim (=1ª+2ª)"
        else:
            m["etapa_qtd_confere"] = "NÃO"
        if rr["etapa"]:
            if m["etapa_indicada"] and m["etapa_indicada"] != rr["etapa"]:
                m["observacao"] = f"descrição diz '{m['etapa_indicada']}', Relação diz '{rr['etapa']}'"
            else:
                m["etapa_indicada"] = rr["etapa"]
                m["etapa_fonte"] = "Relação de Materiais (aba oculta): Quantidade 1ª/2ª etapa"
    return casados


# --------------------------------------------------------------------------
# Aba 'CUSTO CIVIL'
# --------------------------------------------------------------------------

def extrair_custo_civil(wb):
    """Itens folha de 'CUSTO CIVIL': linhas com código de composição na col. B,
    ou com quantidade numérica sem código (ex.: BLOCOS DE APOIO = 4 un)."""
    ws = wb["CUSTO CIVIL"]
    hdr, _ = achar_cabecalho(ws)
    unidade = grupo = subgrupo = ""
    trecho = ""          # último subgrupo "de verdade" (trecho/sistema), p/ itens sem código
    proj = ""
    out = []
    # cabeçalhos sem código/quantidade que são marcadores de escopo (viram linha própria)
    marcador = re.compile(r"^(RECOMPOSI[ÇC][ÃA]O DE PAVIMENTO|BLOCOS? DE (APOIO|ANCORAGEM)|MEDIDORES? DE VAZ)", re.IGNORECASE)
    for r in range(hdr + 1, ws.max_row + 1):
        a, b, c, d, e, _, _, h, i = [ws.cell(r, k).value for k in range(1, 10)]   # F e G = preço/total: ignorados
        a, b, c, d = txt(a), txt(b), txt(c), txt(d)
        if a.upper().startswith("UNIDADE"):
            unidade, grupo, subgrupo = a, "", ""
            continue
        if re.fullmatch(r"\d+", a) and c:
            grupo, subgrupo, trecho = f"UC {a} - {c}", "", ""
            continue
        marcador_scope = False
        if not b and c:
            q = num(e)
            if q is None and marcador.match(c):
                marcador_scope = True           # marcador de escopo sem quantidade
            elif q is None:                     # cabeçalho de subgrupo
                subgrupo = trecho = c
                proj = txt(i) or proj
                continue
        if not (b or c):
            continue
        q = num(e)
        cod_up = b.upper()
        desc = c
        dn, dn_tipo, dn2 = extrair_dn(desc)
        obs = txt(h)
        if cod_up in ("PLANILHA", "EMPREITA"):
            obs = (obs + " | " if obs else "") + "item global detalhado em outra aba"
        sub_item = trecho if (not b and c) else subgrupo     # itens sem código: usa o trecho
        if marcador_scope:
            obs = (obs + " | " if obs else "") + "marcador de escopo: sem código, sem quantidade"
        out.append({
            "aba": "CUSTO CIVIL", "item": "", "codigo": b, "fonte": fonte_civil(b),
            "descricao": desc, "unidade": d, "quantidade": q,
            "unidade_obra": ("UNIDADE 1 - ETA Vila C" if "UNIDADE 1" in unidade.upper()
                             else "UNIDADE 2 - Adutora de água tratada (AAT06/anéis)"),
            "grupo": grupo, "subgrupo": sub_item,
            "disciplina": disciplina_civil(b, desc, grupo, sub_item),
            "material": classificar_material("", desc) if re.search(r"FD|PVC|PEAD|CONCRETO|ASFALTO", desc.upper()) else "",
            "dn_mm": dn, "etapa_indicada": "",
            "dn_tipo": dn_tipo, "dn_mm_2": dn2, "categoria_planilha": "", "local": "", "tabela": "",
            "projeto_desenho": proj,
            "etapa_fonte": "", "qtd_etapa1": None, "qtd_etapa2": None, "etapa_qtd_confere": "",
            "observacao": obs + (" | quantidade em branco na planilha" if q is None and b and cod_up not in ("DI",) else ""),
            "linha_origem": r,
        })
    return out


# --------------------------------------------------------------------------
# Planilhas de cotação
# --------------------------------------------------------------------------

def extrair_cotacao(caminho, rotulo_arquivo):
    """Itens de uma planilha de cotação (layout ITEM, CÓDIGO USMA, LOCAL, MATERIAL,
    PROJETO, TABELA, DESCRIÇÃO, UNID., QUANT.). As colunas depois de QUANT. (preço e
    fornecedor) ficam de fora."""
    wb = openpyxl.load_workbook(caminho, data_only=True)
    out = []
    for ws in wb.worksheets:
        try:
            hdr, cols = achar_cabecalho(ws)
        except ValueError:
            continue
        c_q = cols.get("QUANT.")
        for r in range(hdr + 1, ws.max_row + 1):
            desc = txt(ws.cell(r, cols["DESCRIÇÃO"]).value)
            q = num(ws.cell(r, c_q).value)
            if not desc or q is None:
                continue
            cat = txt(ws.cell(r, cols["MATERIAL"]).value)
            dn, dn_tipo, _ = extrair_dn(desc)
            out.append({
                "arquivo": rotulo_arquivo, "aba": ws.title,
                "item": txt(ws.cell(r, cols["ITEM"]).value),
                "codigo": txt(ws.cell(r, cols["CÓDIGO USMA"]).value),
                "local": txt(ws.cell(r, cols["LOCAL"]).value),
                "categoria_planilha": cat,
                "projeto": txt(ws.cell(r, cols["PROJETO"]).value),
                "tabela": txt(ws.cell(r, cols["TABELA"]).value),
                "descricao": desc, "unidade": txt(ws.cell(r, cols["UNID."]).value),
                "quantidade": q, "material": classificar_material(cat, desc),
                "dn_mm": dn, "dn_tipo": dn_tipo, "linha_origem": r,
            })
    return out


# --------------------------------------------------------------------------
# Saída
# --------------------------------------------------------------------------

COLUNAS_ESCOPO = ["aba", "item", "codigo", "fonte", "descricao", "unidade", "quantidade",
                  "unidade_obra", "grupo", "subgrupo", "disciplina",
                  "material", "dn_mm", "etapa_indicada",
                  # extras
                  "dn_tipo", "dn_mm_2", "categoria_planilha", "local", "tabela",
                  "projeto_desenho", "etapa_fonte", "qtd_etapa1", "qtd_etapa2", "etapa_qtd_confere",
                  "observacao", "linha_origem"]


def gravar_csv(df, caminho):
    """CSV com ';' como separador, ',' decimal, utf-8-sig (abre direto no Excel BR)."""
    df = df.copy()
    for col in ("dn_mm", "dn_mm_2", "linha_origem"):          # inteiros sem ',0'
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    df.to_csv(caminho, sep=";", decimal=",", encoding="utf-8-sig", index=False)


def resumir(df, chaves):
    g = df.groupby(chaves, dropna=False)
    return g.agg(n_itens=("descricao", "size"),
                 n_sem_quantidade=("quantidade", lambda s: int(s.isna().sum()))).reset_index()


def main(pasta):
    wb = openpyxl.load_workbook(os.path.join(pasta, "principal.xlsx"), data_only=True)

    mats = extrair_mats(wb)
    relacao = extrair_relacao(wb)
    casados = anexar_etapas(mats, relacao)
    civil = extrair_custo_civil(wb)
    print(f"MATS E EQUIP: {len(mats)} itens | CUSTO CIVIL: {len(civil)} itens | "
          f"Relação de Materiais: {len(relacao)} linhas | cruzados com etapa: {casados}")

    df = pd.DataFrame(mats + civil).reindex(columns=COLUNAS_ESCOPO)
    gravar_csv(df, os.path.join(pasta, "escopo_itens.csv"))

    gravar_csv(resumir(df, ["unidade_obra", "disciplina"]), os.path.join(pasta, "escopo_resumo.csv"))
    df2 = df.copy()
    df2["etapa_indicada"] = df2["etapa_indicada"].replace("", "(sem indicação)")
    gravar_csv(resumir(df2, ["unidade_obra", "etapa_indicada", "disciplina"]),
               os.path.join(pasta, "escopo_resumo_etapa.csv"))
    gravar_csv(pd.DataFrame(relacao), os.path.join(pasta, "relacao_materiais_etapas.csv"))

    cot = []
    for arq, rot in (("cotacao_materiais.xlsx", "Cotação de materiais"),
                     ("cotacao_pecas_especiais.xlsx", "Cotação de peças especiais")):
        p = os.path.join(pasta, arq)
        if os.path.exists(p):
            cot += extrair_cotacao(p, rot)
    gravar_csv(pd.DataFrame(cot), os.path.join(pasta, "cotacoes_itens.csv"))
    print(f"cotações: {len(cot)} itens")
    return df


# --------------------------------------------------------------------------
# Cadastro de materiais Sanepar (só especificação)
# --------------------------------------------------------------------------

COLUNAS_CATALOGO = ["seq_estoque", "classe", "descricao", "unidade_medida", "norma_eb", "ref_material",
                    "embalagem", "situacao", "ind_projetista", "orgao_inspetor", "armazenamento", "qtd_marcas",
                    "cod_marcas_homologadas", "marcas_homologadas", "coletado_em", "familia", "categoria",
                    "subcategoria", "material_base", "dn", "pn", "diametro_pol", "tags"]


def gravar_catalogo(xlsx, saida):
    """Aba `sanepar_mat` do estudo de orçamento -> JSONL gzip só com colunas de especificação.

    Preço, cotação e fornecedor (abas `*preços`, `pesquisa`, `*forn`) não são lidos: o
    repositório guarda escopo, não valor, e as abas de fornecedor trazem contatos pessoais."""
    import gzip
    import json
    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    linhas = wb["sanepar_mat"].iter_rows(values_only=True)
    cab = [txt(c) for c in next(linhas)]
    idx = {c: cab.index(c) for c in COLUNAS_CATALOGO if c in cab}
    n = 0
    with gzip.open(saida, "wt", encoding="utf-8") as f:
        for lin in linhas:
            if lin[idx["seq_estoque"]] in (None, ""):
                continue
            reg = {c: lin[i] for c, i in idx.items() if lin[i] not in (None, "")}
            reg["seq_estoque"] = str(int(float(reg["seq_estoque"])))
            if "coletado_em" in reg:
                reg["coletado_em"] = str(reg["coletado_em"])[:10]
            f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")
            n += 1
    return n


def catalogo(caminho="referencias/sanepar/catalogo_materiais.jsonl.gz") -> dict:
    """seq_estoque (texto) -> especificação do cadastro Sanepar."""
    import gzip
    import json
    with gzip.open(caminho, "rt", encoding="utf-8") as f:
        return {r["seq_estoque"]: r for r in map(json.loads, f)}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--catalogo":
        print(f"{gravar_catalogo(sys.argv[2], sys.argv[3])} materiais gravados em {sys.argv[3]}")
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__)))
