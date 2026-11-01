import json

import pytest

from camadas import inventario

pymupdf = pytest.importorskip("pymupdf")


def _prancha(caminho, titulo="PLANTA DE ESCAVAÇÃO", largura=2384, altura=1684):
    """Folha A1 paisagem com carimbo Sanepar em texto no canto inferior direito."""
    doc = pymupdf.open()
    pg = doc.new_page(width=largura, height=altura)
    x, y = largura - 520, altura - 260
    linhas = ["Companhia de Saneamento do Paraná", "MUNICÍPIO/SISTEMA: FOZ DO IGUAÇU - PR FOLHA N°: 06/14",
              "PROJETO / UNIDADE CONSTRUTIVA: DATA: OUTUBRO/2025", titulo, "ESCALA: 1:100"]
    for k, t in enumerate(linhas):
        pg.insert_text((x, y + 30 * k), t, fontsize=10)
    pg.insert_text((100, 100), "texto de desenho " * 10, fontsize=8)
    doc.save(caminho)


def test_formato_codigo_e_campos():
    assert inventario.formato_folha(2384, 1684)["formato"] == "A1"
    assert inventario.formato_folha(2754, 1684)["formato"] == "A1 estendido"
    assert inventario.formato_folha(3370, 2384)["formato"] == "A0"
    assert inventario.formato_folha(842, 1191)["orientacao"] == "retrato"
    c = inventario.codigo_sanepar("004-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYOUTPROCES-R5.pdf")
    assert (c["sequencia"], c["disciplina"], c["tipo"], c["revisao"]) == ("004", "PBHI", "DE", 5)
    assert inventario.codigo_sanepar("001-SAA-0017-7471-PBHI-0001ETAVILACFLUXOGRAMA01-R1.pdf")["tipo"] == "DE"
    assert inventario.codigo_sanepar("Matriz-de-risco.pdf") is None
    f = inventario.campos_carimbo("FOLHA N°: 06/14 PROJETO / UNIDADE CONSTRUTIVA: DATA: OUTUBRO/2025 "
                                  "PLANTA DE ESCAVAÇÃO ESCALA: 1:100 12/01/20")
    assert f == {"folha": "06/14", "escala": "1:100", "data": "OUTUBRO/2025", "titulo": "PLANTA DE ESCAVAÇÃO"}


def test_desembaralha_so_fonte_quebrada():
    assert inventario.desembaralhar("&RPSDQKLD\x03GH\x036DQHDPHQWR") == "Companhia de Saneamento"
    assert inventario.desembaralhar("352-(72%$6,&2") == "PROJETOBASICO"
    assert inventario.desembaralhar(")81'$d\xad2") == "FUNDAÇÃO"
    for normal in ("SETEMBRO/2020", "09/2020", "1:100", 'ETA VILA "C" (1ª ETAPA)', "PROJETO HIDRÁULICO"):
        assert inventario.desembaralhar(normal) == normal


def test_tipo_planta_detalhe_documento():
    regras = json.loads((inventario.pdf_cad.CONCEITOS / "tipos_prancha.json").read_text(encoding="utf-8"))
    assert inventario.tipo_documento("003-SAA-0017-8820-PBGE-DE-0000ETA01FUNDACAO1-R2.pdf", None, regras) == "planta"
    assert inventario.tipo_documento("009-SAA-0017-8820-PBGE-DE-0000ETA01CORTES1-R2.pdf", None, regras) == "detalhe"
    assert inventario.tipo_documento("001-SAA-0000-0000-PBEN-DE-0000AAT00PLANTAPERF01-R0.pdf", None, regras) == "planta"
    assert inventario.tipo_documento("008-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYGERAGUAPO-R2.pdf", None, regras) == "planta"
    assert inventario.tipo_documento("01-SAA-0017-8764-PMEC-MD-0001ETAVILACSISTPNEU01-R0.pdf", None, regras) == "documento"


def test_inventario_nao_perde_pdf(tmp_path):
    pasta = tmp_path / "projeto"
    (pasta / "UNIDADE 01" / "PBGE").mkdir(parents=True)
    (pasta / "OUTRA").mkdir()
    _prancha(pasta / "UNIDADE 01" / "PBGE" / "006-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO1-R2.pdf")
    _prancha(pasta / "OUTRA" / "Duplicado.pdf")
    listagem = tmp_path / "listagem.csv"
    listagem.write_text("caminho;titulo;id;mimeType;extensao;tamanho_bytes;modificado\n"
                        "UNIDADE 01/PBGE;006-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO1-R2.pdf;a;application/pdf;pdf;10;x\n"
                        "UNIDADE 01;Duplicado.pdf;b;application/pdf;pdf;10;x\n"
                        "UNIDADE 01;Grande.PDF;c;application/pdf;pdf;9000000;x\n"
                        "ANEXO B;Caderno.pdf;d;application/pdf;pdf;10;x\n"
                        "UNIDADE 01;pasta;e;application/vnd.google-apps.folder;;;x\n"
                        "ORCAMENTO;211.xlsx;f;application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;xlsx;10;x\n"
                        "UNIDADE 01;formas.zip;g;application/zip;zip;10;x\n"
                        "UNIDADE 01;planta.dwg;h;image/vnd.dwg;dwg;10;x\n"
                        "PBES/ACTIFLO 360;012-SAA-0017-8820-PBES-DE-0000ACT360FORMA1-R1.pdf;i;application/pdf;pdf;7000000;x\n",
                        encoding="utf-8")
    import zipfile

    import openpyxl
    (pasta / "ORCAMENTO").mkdir()
    wb = openpyxl.Workbook()
    wb.active.title = "MATS E EQUIP"
    wb.create_sheet("Relação de Materiais").sheet_state = "hidden"
    wb.save(pasta / "ORCAMENTO" / "211.xlsx")
    with zipfile.ZipFile(pasta / "UNIDADE 01" / "formas.zip", "w") as z:
        z.writestr("ACT360/forma1.pdf", "x")
        z.writestr("ACT360/armadura1.pdf", "x")
    (pasta / "UNIDADE 01" / "planta.dwg").write_bytes(b"AC1027")
    baixados = tmp_path / "baixados.csv"
    baixados.write_text("caminho;titulo;id;bytes;ok\nUNIDADE 01/PBGE;006;a;10;true\nUNIDADE 01;Grande.PDF;c;;false\n",
                        encoding="utf-8")
    cfg = {"inventario": {"listagem": str(listagem), "baixados": str(baixados), "pasta": str(pasta)},
           "pranchas": [{"id": "es1", "pdf": "x/006-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO1-R2.pdf"}]}
    r = inventario.inventario(cfg, tmp_path / "cache.json", ocr=False, log=lambda *a: None)
    por = {i["arquivo"]: i for i in r["itens"]}
    assert len(r["itens"]) == 8                                       # todo arquivo da listagem; pasta não
    assert r["totais"]["pdfs"] == 5 and r["totais"]["por_extensao"][".xlsx"] == 1 and r["totais"]["sem_leitor"] == 1
    assert por["211.xlsx"]["abas"][1] == {"aba": "Relação de Materiais", "estado": "hidden", "linhas": 1, "colunas": 1}
    assert por["formas.zip"]["arquivos_dentro"] == 2 and por["formas.zip"]["por_extensao"] == {".pdf": 2}
    assert por["planta.dwg"]["situacao"] == "no disco" and por["planta.dwg"]["leitor"] is None
    assert [por[k]["situacao"] for k in ("006-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO1-R2.pdf", "Duplicado.pdf",
                                         "Grande.PDF", "Caderno.pdf")] == \
        ["no disco", "no disco (mesmo nome em outra pasta)", "falhou no download", "não tentado"]
    e = por["006-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO1-R2.pdf"]
    assert e["formato"] == "A1" and e["tipo"] == "planta" and e["no_mapa"] == "es1"
    assert (e["carimbo"]["folha"], e["carimbo"]["titulo"], e["carimbo"]["escala"]) == ("06/14", "PLANTA DE ESCAVAÇÃO", "1:100")
    assert sum(l["total"] for l in r["resumo"]) == 8 and sum(l["fora_do_disco"] for l in r["resumo"]) == 3
    assert inventario.inventario(cfg, tmp_path / "cache.json", ocr=False, log=lambda *a: None)["itens"][0]["carimbo"] == e["carimbo"]


def test_ausencia_so_por_consulta_ao_inventario():
    """Lição do Actiflo 360: a forma existia e foi dada como inexistente (em Foz, as formas dos Actiflo estavam na
    listagem como PDFs acima de 5 MB, não baixados). "Não baixado" não é "não existe": `procurar` acha o arquivo em
    qualquer situação e diz qual."""
    inv = {"fonte": "listagem.csv", "itens": [
        {"arquivo": "012-SAA-0017-8820-PBES-DE-0000ACT360FORMA1-R1.pdf", "pasta_drive": "PBES/ACTIFLO 360", "mb": 7.0,
         "situacao": "não tentado", "tipo": "detalhe"},
        {"arquivo": "003-FUNDACAO1-R2.pdf", "pasta_drive": "PBGE", "mb": 1.0, "situacao": "no disco", "tipo": "planta",
         "carimbo": {"titulo": "PLANTA DE FUNDAÇÃO - ACTIFLO 600"}}]}
    r = inventario.procurar(inv, "ACT.?360.*FORMA")
    assert [a["arquivo"] for a in r["achados"]] == ["012-SAA-0017-8820-PBES-DE-0000ACT360FORMA1-R1.pdf"]
    assert "fora do disco (não tentado): existem, não foram lidos" in r["resposta"]
    assert inventario.procurar(inv, "fundação.*actiflo 600")["achados"][0]["situacao"] == "no disco"   # pelo carimbo
    assert inventario.procurar(inv, "ARMADURA")["resposta"] == \
        "nenhum dos 2 arquivos da listagem (listagem.csv) casa com 'ARMADURA'"


def _cfg_um_pdf(tmp_path):
    """Obra mínima com um PDF (`a.pdf`) na listagem e no disco."""
    pasta = tmp_path / "projeto"
    pasta.mkdir()
    _prancha(pasta / "a.pdf")
    listagem = tmp_path / "listagem.csv"
    listagem.write_text("caminho;titulo;id;mimeType;extensao;tamanho_bytes;modificado\n"
                        ";a.pdf;a;application/pdf;pdf;10;x\n", encoding="utf-8")
    return {"inventario": {"listagem": str(listagem), "pasta": str(pasta)}, "pranchas": []}, pasta / "a.pdf"


def _rodar(cfg, cache, monkeypatch, **kw):
    """Roda o inventário contando quantas vezes `ler_arquivo` foi chamado."""
    chamadas = []
    original = inventario.ler_arquivo
    monkeypatch.setattr(inventario, "ler_arquivo", lambda p, ocr=True: chamadas.append(str(p)) or original(p, ocr))
    r = inventario.inventario(cfg, cache, ocr=False, log=lambda *a: None, **kw)
    return r, chamadas


def test_cache_erro_reler_e_versao(tmp_path, monkeypatch):
    cfg, pdf = _cfg_um_pdf(tmp_path)
    cache = tmp_path / "cache.json"
    assert len(_rodar(cfg, cache, monkeypatch)[1]) == 1
    assert _rodar(cfg, cache, monkeypatch)[1] == []                                  # cache vale
    assert _rodar(cfg, cache, monkeypatch, reler={str(pdf)})[1] == [str(pdf)]        # `reler` força a leitura
    memo = json.loads(cache.read_text(encoding="utf-8"))
    assert memo[str(pdf)]["assinatura"].endswith(f":v{inventario.LEITURA_VERSAO}")
    memo[str(pdf)]["erro"] = "OSError: falha momentânea"                             # erro não é leitura definitiva
    cache.write_text(json.dumps(memo), encoding="utf-8")
    r, chamadas = _rodar(cfg, cache, monkeypatch)
    assert chamadas == [str(pdf)] and "erro" not in r["itens"][0]
    assert _rodar(cfg, cache, monkeypatch)[1] == []
    monkeypatch.setattr(inventario, "LEITURA_VERSAO", inventario.LEITURA_VERSAO + 1)  # versão nova invalida o cache
    assert _rodar(cfg, cache, monkeypatch)[1] == [str(pdf)]


def _pdf_tres_paginas(caminho):
    """Capa sem texto + 2 páginas de corpo com texto e carimbo (a 2ª com título próprio)."""
    doc = pymupdf.open()
    doc.new_page(width=2384, height=1684)
    for titulo in ("PLANTA DE ESCAVAÇÃO", "CORTE A-A"):
        pg = doc.new_page(width=2384, height=1684)
        for k, t in enumerate(["PROJETO / UNIDADE CONSTRUTIVA: DATA: OUTUBRO/2025", titulo, "ESCALA: 1:100",
                               "FOLHA N°: 02/03", "Companhia de Saneamento do Paraná"]):
            pg.insert_text((1864, 1424 + 30 * k), t, fontsize=10)
        pg.insert_text((100, 100), "texto de desenho " * 10, fontsize=8)
    doc.save(caminho)


def test_pdf_lido_inteiro_e_carimbo_por_pagina(tmp_path):
    _pdf_tres_paginas(tmp_path / "t.pdf")
    r = inventario.ler_pdf(tmp_path / "t.pdf", ocr=False)
    assert r["paginas"] == 3 and r["texto"] == "sim" and r["paginas_com_texto"] == 2
    assert [c["pagina"] for c in r["carimbos"]] == [1, 2, 3]
    assert r["carimbos"][1]["titulo"] == "PLANTA DE ESCAVAÇÃO" and r["carimbos"][2]["titulo"] == "CORTE A-A"
    assert r["carimbo"]["titulo"] is None and "pagina" not in r["carimbo"]        # `carimbo` segue sendo o da 1ª
    assert inventario.ler_pdf(tmp_path / "t.pdf", ocr=False, max_paginas=1)["texto"].startswith("pouco")
    item = {"arquivo": "t.pdf", "carimbo": r["carimbo"], "carimbos": r["carimbos"]}
    html = inventario.para_html({"resumo": [], "totais": {}, "fora_da_listagem": [], "fonte": "x", "itens": [item]})
    assert "carimbos" not in html["itens"][0]


def test_reler_carimbo_300_dpi(tmp_path, monkeypatch):
    _pdf_tres_paginas(tmp_path / "t.pdf")
    dpis = []
    monkeypatch.setattr(inventario, "ocr_carimbo",
                        lambda pg, dpi=200: dpis.append(dpi) or "FOLHA N°: 01/03 ABASTECIMENTO DE ÁGUA OUTUBRO/2025 "
                        "PLANTA GERAL DA ETA ESCALA: 1:200")
    r = inventario.reler_carimbo(tmp_path / "t.pdf")
    assert dpis == [300] and (r["folha"], r["escala"], r["titulo"]) == ("01/03", "1:200", "PLANTA GERAL DA ETA")
    assert "300" in r["fonte"]
