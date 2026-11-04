"""Menções da EAP nos documentos de texto (F5): PDFs sintéticos feitos com pymupdf."""

import pytest

pymupdf = pytest.importorskip("pymupdf")

from camadas import gavetas, gavetas_texto

ITENS = [
    {"codigo": "GEO.FUN.EST", "termos": r"\bESTACAS?\b"},
    {"codigo": "HID.TUB.VAL", "termos": r"VALVULA"},
]


def _pdf(caminho, paginas):
    """PDF com uma página por texto; texto vazio deixa a página em branco (como traço ou imagem)."""
    doc = pymupdf.open()
    for texto in paginas:
        pagina = doc.new_page()
        if texto:
            pagina.insert_text((50, 100), texto, fontsize=10)
    doc.save(str(caminho))
    doc.close()


def _documento(arquivo, classe="memorial", documento_id="d1", destino=None):
    return {
        "documento_id": documento_id,
        "arquivo": arquivo,
        "sha256": "ab" * 32,
        "extensao": ".pdf",
        "classe": classe,
        "paginas": 3,
        "destino": destino or [],
    }


def _base(tmp_path, paginas, **kw):
    _pdf(tmp_path / "m.pdf", paginas)
    doc = _documento("m.pdf", **kw)
    return doc, gavetas_texto.de_documentos([doc], tmp_path, ITENS)


def test_mencao_por_pagina_com_trecho_e_evidencia(tmp_path):
    _, base = _base(
        tmp_path,
        [
            "Fundação em estacas helicoidais",
            "Sem nada aqui",
            "As ESTACAS seguem o projeto",
        ],
    )
    assert [o["objeto_id"] for o in base["objetos"]] == ["txt-d1-GEO.FUN.EST"]
    assert base["objetos"][0]["classe"] == "mencao_documento"
    mencoes = [f for f in base["fatos"] if f["propriedade"] == "mencao"]
    assert [f["fato_id"] for f in mencoes] == [
        "txt-d1-GEO.FUN.EST#p1",
        "txt-d1-GEO.FUN.EST#p3",
    ]
    assert all(
        "ESTACAS" in f["valor"]
        and len(f["valor"]) <= 200
        and f["natureza"] == "projetado"
        for f in mencoes
    )
    item = [f for f in base["fatos"] if f["propriedade"] == "item_tecnico"]
    assert [f["valor"] for f in item] == ["GEO.FUN.EST"]
    ev = {e["evidencia_id"]: e for e in base["evidencias"]}
    assert ev[mencoes[1]["evidencia_id"]]["localizador"] == {"pagina": 3}
    assert ev[mencoes[1]["evidencia_id"]]["documento"] == "d1"
    assert ev[mencoes[1]["evidencia_id"]]["classe"] == "memorial"
    assert ev[mencoes[1]["evidencia_id"]]["executor"] == "código"
    assert ev[mencoes[1]["evidencia_id"]]["metodo"].startswith("camadas.gavetas_texto")
    assert ev[mencoes[1]["evidencia_id"]]["trecho"] == mencoes[1]["valor"]


def test_trecho_limitado_a_200_caracteres(tmp_path):
    texto = "\n".join(
        ["palavra solta de enchimento"] * 40
        + ["estacas"]
        + ["outra palavra de enchimento"] * 40
    )
    _, base = _base(tmp_path, [texto])
    trecho = next(f["valor"] for f in base["fatos"] if f["propriedade"] == "mencao")
    assert 0 < len(trecho) <= 200 and "ESTACAS" in trecho


def test_quantidade_so_com_numero_e_unidade(tmp_path):
    _, base = _base(
        tmp_path, ["Cravar 120 UN de estacas", "Válvula de retenção na linha"]
    )
    props = {
        f["propriedade"]: f["valor"]
        for f in base["fatos"]
        if f["objeto_id"] == "txt-d1-GEO.FUN.EST"
    }
    assert props["quantidade"] == 120 and props["unidade_medida"] == "un"
    qtd = next(f for f in base["fatos"] if f["propriedade"] == "quantidade")
    assert qtd["evidencia_id"].endswith("#p1")
    sem = [f for f in base["fatos"] if f["objeto_id"] == "txt-d1-HID.TUB.VAL"]
    assert {f["propriedade"] for f in sem} == {"item_tecnico", "mencao"}


def test_pagina_sem_texto_vira_pendencia(tmp_path):
    _, base = _base(tmp_path, ["estacas", "", "estacas"])
    assert [(p["objeto_id"], p["motivo"]) for p in base["pendencias"]] == [
        ("d1#p2", "página sem texto (OCR é passe da escada)")
    ]
    assert gavetas_texto.resumo(base)["paginas_sem_texto"] == 1


def test_documento_de_projeto_fica_fora(tmp_path):
    _pdf(tmp_path / "p.pdf", ["estacas"])
    sem_destino = _documento("p.pdf", classe="projeto", documento_id="p1")
    com_destino = _documento(
        "p.pdf",
        classe="projeto",
        documento_id="p2",
        destino=[{"leitor": "camadas.evidencias", "gavetas": ["fatos"]}],
    )
    base = gavetas_texto.de_documentos([sem_destino, com_destino], tmp_path, ITENS)
    assert {o["objeto_id"] for o in base["objetos"]} == {"txt-p2-GEO.FUN.EST"}


def test_ids_estaveis_e_conferir_base(tmp_path):
    doc, base = _base(tmp_path, ["estacas 10 un", "", "válvula e estacas"])
    de_novo = gavetas_texto.de_documentos([doc], tmp_path, ITENS)
    assert {g: base[g] for g in ("objetos", "fatos", "evidencias", "pendencias")} == {
        g: de_novo[g] for g in ("objetos", "fatos", "evidencias", "pendencias")
    }
    conferencia = {
        "documentos": [doc],
        **{g: base[g] for g in ("objetos", "fatos", "evidencias", "pendencias")},
    }
    assert gavetas.conferir_base(conferencia) == []
    r = gavetas_texto.resumo(base)
    assert r["documentos_lidos"] == 1 and r["paginas_lidas"] == 3 and r["mencoes"] == 3
    assert r["mencoes_com_quantidade"] == 1
    assert r["itens_por_documento"] == {"d1": 2}
