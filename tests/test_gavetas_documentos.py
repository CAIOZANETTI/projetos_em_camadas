"""Inventário → gavetas `documentos` e `paginas` (F1): PDFs sintéticos em tmp_path e inventário mínimo."""

import hashlib

import pytest

from camadas import gavetas, gavetas_documentos

pymupdf = pytest.importorskip("pymupdf")   # extra `pdf`: sem ele (CI) o arquivo é pulado, como os outros testes de PDF


def _pdf(caminho, paginas=((842, 595),), texto="x"):
    doc = pymupdf.open()
    for largura, altura in paginas:
        doc.new_page(width=largura, height=altura).insert_text((50, 50), texto)
    doc.save(caminho)
    doc.close()
    return caminho


def _item(caminho, tipo="documento", **extra):
    return {
        "arquivo": caminho.name,
        "pasta_drive": "PROJETOS",
        "situacao": "no disco",
        "caminho": str(caminho),
        "tipo": tipo,
        "codigo": None,
        "no_mapa": None,
        **extra,
    }


def test_documento_com_classe_destino_e_sha256(tmp_path):
    pdf = _pdf(tmp_path / "Memorial Descritivo.pdf", [(595, 842), (595, 842)])
    base = gavetas_documentos.de_inventario({"itens": [_item(pdf)]}, tmp_path)
    (doc,) = base["documentos"]
    assert doc["arquivo"] == "Memorial Descritivo.pdf"
    assert doc["sha256"] == hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert doc["documento_id"] == gavetas.id_documento(pdf) == doc["sha256"][:16]
    assert (
        doc["extensao"] == ".pdf"
        and doc["classe"] == "memorial"
        and doc["paginas"] == 2
    )
    assert [d["leitor"] for d in doc["destino"]] == ["camadas.evidencias"]
    assert "motivo_sem_destino" not in doc
    assert gavetas.conferir_base(base) == []


def test_pagina_com_tamanho_e_rotacao(tmp_path):
    pdf = tmp_path / "a.pdf"
    doc = pymupdf.open()
    doc.new_page(width=800, height=400).set_rotation(90)
    doc.save(pdf)
    doc.close()
    base = gavetas_documentos.de_inventario({"itens": [_item(pdf)]}, tmp_path)
    (pg,) = base["paginas"]
    assert (pg["largura_pt"], pg["altura_pt"]) == (400.0, 800.0)
    assert pg["pagina_id"] == gavetas.id_pagina(
        base["documentos"][0]["documento_id"], 1
    )
    assert "M" not in pg


def test_pagina_georreferenciada_so_na_pagina_da_prancha(tmp_path):
    pdf = _pdf(tmp_path / "planta.pdf", [(2384, 1684)] * 3)
    M = [[0.1, 0.0, 700000.0], [0.0, -0.1, 7180000.0], [0.0, 0.0, 1.0]]
    item = _item(pdf, tipo="planta", codigo={"tipo": "DE"})
    sem_pagina = gavetas_documentos.de_inventario(
        {"itens": [item]}, tmp_path, [{"id": "p1", "pdf": str(pdf), "M": M}]
    )
    com_pagina = gavetas_documentos.de_inventario(
        {"itens": [item]},
        tmp_path,
        [{"id": "p1", "pdf": str(pdf), "M": M, "pagina": 2}],
    )
    assert [p.get("prancha_id") for p in sem_pagina["paginas"]] == ["p1", None, None]
    assert [p.get("prancha_id") for p in com_pagina["paginas"]] == [None, "p1", None]
    assert com_pagina["paginas"][1]["M"] == M
    assert resumo_geo(com_pagina) == 1
    assert gavetas.conferir_base(com_pagina) == []
    # planta georreferenciada: vala, escavação e construtivos entram no destino
    leitores = " | ".join(d["leitor"] for d in com_pagina["documentos"][0]["destino"])
    for esperado in ("camadas.valas.rede", "camadas.escavacao", "camadas.construtivos"):
        assert esperado in leitores


def resumo_geo(base):
    return gavetas_documentos.resumo(base)["paginas_georreferenciadas"]


def test_planta_sem_georreferencia_nao_vai_para_valas(tmp_path):
    pdf = _pdf(tmp_path / "planta.pdf")
    base = gavetas_documentos.de_inventario(
        {"itens": [_item(pdf, tipo="planta")]}, tmp_path
    )
    leitores = {d["leitor"] for d in base["documentos"][0]["destino"]}
    assert "camadas.valas.rede" not in leitores and "camadas.prancha" in leitores


def test_arquivo_fora_do_disco_vira_pendencia(tmp_path):
    itens = [
        {
            "arquivo": "Edital.pdf",
            "pasta_drive": "LICITACAO",
            "situacao": "falhou no download",
            "tipo": "documento",
        },
        _item(_pdf(tmp_path / "Edital Termo de Referencia.pdf")),
    ]
    base = gavetas_documentos.de_inventario({"itens": itens}, tmp_path)
    assert len(base["documentos"]) == 1
    (pendencia,) = base["pendencias"]
    assert (
        pendencia["objeto_id"] == "LICITACAO/Edital.pdf"
        and "falhou no download" in pendencia["motivo"]
    )
    assert gavetas.conferir_base(base) == []


def test_sem_leitor_leva_motivo(tmp_path):
    foto = tmp_path / "foto.jpg"
    foto.write_bytes(b"jpg")
    cotacao = _pdf(tmp_path / "Cotacao fornecedor.pdf")
    base = gavetas_documentos.de_inventario(
        {"itens": [_item(foto), _item(cotacao)]}, tmp_path
    )
    por_arquivo = {d["arquivo"]: d for d in base["documentos"]}
    assert (
        por_arquivo["foto.jpg"]["destino"] == []
        and por_arquivo["foto.jpg"]["paginas"] == 1
    )
    assert por_arquivo["foto.jpg"]["motivo_sem_destino"]
    assert (
        "fora do escopo" in por_arquivo["Cotacao fornecedor.pdf"]["motivo_sem_destino"]
    )
    r = gavetas_documentos.resumo(base)
    assert (
        r["sem_destino"] == 2
        and r["documentos"] == 2
        and len(r["motivos_sem_destino"]) == 2
    )


def test_conteudo_identico_e_um_documento_com_copias(tmp_path):
    a = _pdf(tmp_path / "a.pdf", texto="igual")
    b = tmp_path / "b.pdf"
    b.write_bytes(a.read_bytes())
    base = gavetas_documentos.de_inventario({"itens": [_item(a), _item(b)]}, tmp_path)
    assert len(base["documentos"]) == 1 and base["documentos"][0]["copias"] == ["b.pdf"]
    assert gavetas.conferir_base(base) == []


def test_id_estavel_e_ordem_deterministica(tmp_path):
    a, b = _pdf(tmp_path / "a.pdf", texto="um"), _pdf(tmp_path / "b.pdf", texto="dois")
    um = gavetas_documentos.de_inventario({"itens": [_item(a), _item(b)]}, tmp_path)
    dois = gavetas_documentos.de_inventario({"itens": [_item(b), _item(a)]}, tmp_path)
    assert um == dois
    assert [d["arquivo"] for d in um["documentos"]] == ["a.pdf", "b.pdf"]


def test_resumo_conta_classes_destinos_e_paginas(tmp_path):
    memorial = _pdf(tmp_path / "Memorial.pdf", [(595, 842)] * 2)
    planilha = tmp_path / "Contrato.xlsx"
    planilha.write_bytes(b"xlsx")
    base = gavetas_documentos.de_inventario(
        {"itens": [_item(memorial), _item(planilha)]}, tmp_path
    )
    r = gavetas_documentos.resumo(base)
    assert r["por_classe"] == {"memorial": 1, "planilha": 1}
    assert (
        r["por_destino"]["camadas.evidencias"] == 1
        and r["por_destino"]["camadas.contrato_211"] == 1
    )
    assert (
        r["paginas"] == 2
        and r["paginas_georreferenciadas"] == 0
        and r["sem_destino"] == 0
    )


def test_metadados():
    m = gavetas_documentos.metadados()
    assert m["modulo"] == "gavetas_documentos" and "de_inventario" in m["funcoes"]
