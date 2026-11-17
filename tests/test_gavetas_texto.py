"""Menções da EAP nos documentos de texto (F5): PDFs sintéticos feitos com pymupdf."""

import re

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


REGRAS = gavetas_texto.REGRAS


def test_alternativas_e_palavras_do_termo():
    regex = r"\bESTACAS?\b(?!\s*\d+\s*\+)(?! (DE MADEIRA|PARA PROTECAO))|AS.?BUILT|LIMPEZA (?:DA|DE) OBRAS?"
    alts = gavetas_texto.alternativas(regex)
    assert len(alts) == 3
    assert gavetas_texto.palavras_do_termo(alts[0]) == ["ESTACAS"]
    assert gavetas_texto.palavras_do_termo(alts[1]) == ["AS", "BUILT"]
    assert gavetas_texto.termo_legivel(alts[2]) == "limpeza da obras"


def test_stopword_e_poucas_letras_ficam_fora_e_registradas():
    itens = [{"codigo": "GER.PRE.ALO", "termos": r"ADMINISTRACAO LOCAL|ALO\b|\bDAS\b"}]
    padroes, ignorados = gavetas_texto.termos_da_busca(itens, ["TEXTO"] * 3)
    assert padroes["GER.PRE.ALO"].pattern == "ADMINISTRACAO LOCAL"
    motivos = {i["termo"]: i["motivo"] for i in ignorados}
    assert "letras úteis" in motivos["alo"]
    assert "stopwords" in motivos["das"]
    assert all(i["item"] == "GER.PRE.ALO" and i["alternativa"] for i in ignorados)


def test_termo_generico_sai_pela_frequencia_do_corpus():
    buscas = ["A OBRA SEGUE O PROJETO"] * 60 + ["ESTACAS HELICE"] * 3 + ["OUTRO"] * 57
    itens = [{"codigo": "GEO.FUN.EST", "termos": r"\bOBRAS?\b|\bESTACAS?\b|DA OBRA"}]
    padroes, ignorados = gavetas_texto.termos_da_busca(itens, buscas)
    assert padroes["GEO.FUN.EST"].pattern == r"\bESTACAS?\b"
    por_termo = {i["termo"]: i for i in ignorados}
    assert por_termo["obras"]["frequencia"] == 0.5
    assert "acima de 8%" in por_termo["obras"]["motivo"]
    assert "stopwords e palavras genéricas" in por_termo["da obra"]["motivo"]


def test_corpus_pequeno_nao_decide_por_frequencia():
    itens = [{"codigo": "X", "termos": r"\bOBRAS?\b"}]
    padroes, ignorados = gavetas_texto.termos_da_busca(itens, ["A OBRA SEGUE"] * 10)
    assert padroes["X"] is not None and ignorados == []


def test_item_sem_termo_que_discrimine_fica_sem_padrao():
    padroes, ignorados = gavetas_texto.termos_da_busca(
        [{"codigo": "X", "termos": r"\bCLP\b"}], ["TEXTO"]
    )
    assert padroes["X"] is None and len(ignorados) == 1


def _candidata(trecho, termo, unidades):
    return gavetas_texto.candidata_do_trecho(trecho, re.compile(termo), unidades)


def test_candidata_so_com_unidade_admitida_pelo_item():
    trecho = "MOBILIZACAO DE CANTEIRO COM 3.160 M DE REDE"
    assert _candidata(trecho, "MOBILIZACAO", ["vb", "mês"]) is None
    achada = _candidata(trecho, "MOBILIZACAO", ["m", "vb"])
    assert achada["valor"] == 3160 and achada["unidade"] == "m"


def test_candidata_longe_do_termo_e_recusada():
    assert _candidata("ESTACAS HELICE 250 UN", "ESTACAS", ["un"])["valor"] == 250
    assert _candidata("ESTACAS " + "PALAVRA " * 9 + "250 UN", "ESTACAS", ["un"]) is None
    assert _candidata("ESTACAS " + "PALAVRA " * 8 + "250 UN", "ESTACAS", ["un"])


@pytest.mark.parametrize(
    "trecho",
    [
        "ESTACAS 4.0018E+07 UN",
        "ESTACAS EM 2022 UN",
        "ESTACAS 85.801-020 M",
        "ESTACAS TEL (45) 3523-1234 UN",
        "ESTACAS COD 42.024.049 UN",
        "ESTACAS 320342 UN",
        "ESTACAS PAGINA 3 DE 10 UN",
        "ESTACAS NBR 7675 UN",
        "ESTACAS DN 150 MM",
        "V E R S A O 2 0 1 8 ESTACAS",
    ],
)
def test_numero_que_nao_e_quantidade_nao_vira_candidata(trecho):
    assert _candidata(trecho, "ESTACAS", ["un", "m", "mm"]) is None


def test_numero_colado_ao_termo_no_plural_vale_unidade():
    assert (
        _candidata("EXECUCAO DE 250 ESTACAS HELICE", "ESTACAS?", ["un"])["valor"] == 250
    )
    assert _candidata("13 CONEXAO PRIMARIO", "CONEXA", ["un"]) is None
    assert _candidata("250 PEQUENAS ESTACAS", "ESTACAS?", ["un"]) is None


def test_de_documentos_ignora_termo_generico_e_registra(tmp_path):
    paginas = ["A obra segue o projeto."] * 119 + [
        "Foram executadas 250 estacas helice."
    ]
    _pdf(tmp_path / "m.pdf", paginas)
    itens = [{"codigo": "GEO.FUN.EST", "termos": r"\bESTACAS?\b|\bOBRAS?\b"}]
    base = gavetas_texto.de_documentos([_documento("m.pdf")], tmp_path, itens)
    mencoes = [f for f in base["fatos"] if f["propriedade"] == "mencao"]
    assert [f["fato_id"] for f in mencoes] == ["txt-d1-GEO.FUN.EST#p120"]
    qtd = [
        f for f in base["fatos"] if f["propriedade"] in ("quantidade", "unidade_medida")
    ]
    assert [f["valor"] for f in qtd] == [250, "un"]
    ignoradas = [p for p in base["pendencias"] if p.get("regra") == "termo_ignorado"]
    assert [(p["objeto_id"], p["detalhe"]) for p in ignoradas] == [
        ("termo:GEO.FUN.EST", r"\bOBRAS?\b")
    ]
    assert "acima de 8%" in ignoradas[0]["motivo"]
    assert gavetas_texto.resumo(base)["termos_ignorados"] == 1
