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
