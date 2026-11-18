"""F5b-E3: a leitura de IA com citação conferida entra nas gavetas e fecha a folha como "declarada (documento)"."""

import json
from pathlib import Path

import pytest

from camadas import eap_laco, gavetas, gavetas_ia
from camadas import eap_preencher as ep

pymupdf = pytest.importorskip("pymupdf")

NOME = "memorial_fundacoes.pdf"
DOCUMENTO_ID = "0123456789abcdef"
PAGINAS = [
    "Fundacoes\nSerao executadas 250 estacas helice continua.",
    "Bloco B1 com 12 estacas helice continua.\nBloco B2 com 12 estacas helice continua.",
    "Resumo: 250 estacas helice continua.",
    "As estacas helice continua serao cravadas com mesa de perfuracao.",
]
FOLHA = "OP.03.01"  # aponta GEO.FUN.EST


@pytest.fixture
def raiz(tmp_path) -> Path:
    with pymupdf.open() as pdf:
        for texto in PAGINAS:
            pdf.new_page().insert_text((72, 72), texto, fontsize=11)
        pdf.save(tmp_path / NOME)
    return tmp_path


@pytest.fixture
def base() -> dict:
    b = gavetas.base_vazia()
    b["documentos"].append(
        {
            "documento_id": DOCUMENTO_ID,
            "arquivo": NOME,
            "sha256": DOCUMENTO_ID,
            "extensao": ".pdf",
            "classe": "memorial",
            "paginas": len(PAGINAS),
        }
    )
    b["paginas"] += [
        {
            "pagina_id": gavetas.id_pagina(DOCUMENTO_ID, n),
            "documento_id": DOCUMENTO_ID,
            "pagina": n,
            "largura_pt": 595.0,
            "altura_pt": 842.0,
        }
        for n in range(1, len(PAGINAS) + 1)
    ]
    return b


def _linha(**campos) -> dict:
    ev = {
        "codigo": "U1.*.GEO.FUN.EST",
        "servico": "",
        "unidade": "un",
        "valor": 250.0,
        "parcela": False,
        "documento": {"id": NOME, "tipo": "ia"},
        "localizador": "p. 1",
        "metodo": "ia",
        "trecho": "Serao executadas 250 estacas helice continua.",
    }
    return {**ev, **campos}


def _folha(eap: dict, folha_id: str) -> dict:
    return next(
        f
        for t in eap["tipos"].values()
        for e in t["etapas"]
        for f in e["folhas"]
        if f["id"] == folha_id
    )


def test_linha_aceita_fecha_a_folha_como_declarada_do_documento(base, raiz):
    nova, resumo = gavetas_ia.aplicar(base, [_linha()], raiz)
    assert resumo == {"linhas": 1, "aceitas": 1, "recusadas": 0, "mencoes": 0}
    assert gavetas.conferir_base(nova) == []
    fatos = {f["propriedade"]: f for f in nova["fatos"]}
    assert (
        fatos["quantidade"]["valor"] == 250.0
        and fatos["quantidade"]["natureza"] == "declarado"
    )
    assert (
        fatos["item_tecnico"]["valor"] == "GEO.FUN.EST"
        and fatos["unidade_medida"]["valor"] == "un"
    )
    evidencia = nova["evidencias"][0]
    assert (evidencia["metodo"], evidencia["executor"], evidencia["citacao"]) == (
        "IA",
        "ia",
        "conferida",
    )
    assert evidencia["documento"] == DOCUMENTO_ID and evidencia["localizador"] == {
        "pagina": 1
    }
    folha = _folha(ep.preencher(nova), FOLHA)
    assert (
        folha["situacao"] == "declarada"
        and folha["fonte_declarada"] == "declarada (documento)"
    )
    assert folha["quantidades"] == [] and folha["totais_declaradas_documento"] == [
        {"unidade": "un", "quantidade": 250.0}
    ]
    citacao = folha["declaradas_documento"][0]["citacoes"][0]
    assert citacao["documento"] == DOCUMENTO_ID and citacao["pagina"] == 1
    assert citacao["trecho"] == "Serao executadas 250 estacas helice continua."


def test_o_portao_do_laco_conta_a_folha_como_declarada(base, raiz):
    nova, _ = gavetas_ia.aplicar(base, [_linha()], raiz)
    eap = ep.preencher(nova)
    portao = eap_laco.portao(eap, eap_laco.destinos(eap, nova))
    assert portao["completude"]["obra_localizada"]["declaradas"] >= 1
    assert FOLHA not in {t["folha"] for t in portao["trava"]}


def test_linha_recusada_vira_pendencia_com_o_motivo_e_nao_fecha(base, raiz):
    inventada = _linha(
        valor=300.0, trecho="Serao executadas 300 estacas helice continua."
    )
    nova, resumo = gavetas_ia.aplicar(base, [inventada], raiz)
    assert resumo["aceitas"] == 0 and resumo["recusadas"] == 1
    assert nova["objetos"] == [] and nova["fatos"] == []
    assert nova["pendencias"][0]["motivo"] == "trecho não encontrado no documento"
    assert _folha(ep.preencher(nova), FOLHA)["situacao"] == "a preencher"


def test_selo_citacao_vindo_de_fora_e_ignorado(base, raiz):
    falsa = _linha(
        valor=300.0,
        trecho="Serao executadas 300 estacas helice continua.",
        citacao="conferida",
    )
    nova, resumo = gavetas_ia.aplicar(base, [falsa], raiz)
    assert resumo["aceitas"] == 0 and nova["evidencias"] == []
    assert nova["pendencias"][0]["motivo"] == "trecho não encontrado no documento"


def test_documento_fora_das_gavetas_vira_pendencia(base, raiz):
    nova, resumo = gavetas_ia.aplicar(
        base, [_linha(documento={"id": "outro.pdf", "tipo": "ia"})], raiz
    )
    assert resumo["recusadas"] == 1 and "outro.pdf" in nova["pendencias"][0]["motivo"]


def test_mencao_sem_numero_nao_fecha_a_folha_mas_e_mencao_para_o_laco(base, raiz):
    mencao = _linha(
        valor=None,
        unidade=None,
        localizador="p. 4",
        trecho="As estacas helice continua serao cravadas com mesa de perfuracao.",
    )
    nova, resumo = gavetas_ia.aplicar(base, [mencao], raiz)
    assert resumo["aceitas"] == 1 and resumo["mencoes"] == 1
    assert [o["classe"] for o in nova["objetos"]] == ["mencao_documento"]
    assert _folha(ep.preencher(nova), FOLHA)["situacao"] == "a preencher"
    menções = eap_laco._mencoes_por_item(nova)["GEO.FUN.EST"]
    assert menções[0]["documento_id"] == DOCUMENTO_ID and menções[0]["paginas"] == [4]


def test_parcelas_somam_e_o_total_repetido_em_outra_pagina_conta_uma_vez(base, raiz):
    b1 = _linha(
        valor=12.0,
        parcela=True,
        localizador="p. 2",
        trecho="Bloco B1 com 12 estacas helice continua.",
    )
    b2 = _linha(
        valor=12.0,
        parcela=True,
        localizador="p. 2",
        trecho="Bloco B2 com 12 estacas helice continua.",
    )
    nova, _ = gavetas_ia.aplicar(base, [b1, b2], raiz)
    assert _folha(ep.preencher(nova), FOLHA)["totais_declaradas_documento"] == [
        {"unidade": "un", "quantidade": 24.0}
    ]
    total_1 = _linha()
    total_2 = _linha(localizador="p. 3", trecho="Resumo: 250 estacas helice continua.")
    nova, resumo = gavetas_ia.aplicar(base, [total_1, total_2], raiz)
    assert resumo["aceitas"] == 2
    folha = _folha(ep.preencher(nova), FOLHA)
    assert folha["totais_declaradas_documento"] == [
        {"unidade": "un", "quantidade": 250.0}
    ]
    assert not folha["declaradas_documento"][0]["conflito"]


def test_totais_que_divergem_no_documento_sao_conflito_e_nao_fecham(base, raiz):
    outra = _linha(
        valor=280.0, localizador="p. 3", trecho="Resumo: 250 estacas helice continua."
    )
    nova, _ = gavetas_ia.aplicar(base, [_linha(), outra], raiz)
    assert [p["motivo"] for p in nova["pendencias"]] == ["valor não está no trecho"]
    nova, _ = gavetas_ia.aplicar(
        base,
        [
            _linha(),
            _linha(
                localizador="p. 2",
                valor=12.0,
                trecho="Bloco B1 com 12 estacas helice continua.",
            ),
        ],
        raiz,
    )
    folha = _folha(ep.preencher(nova), FOLHA)
    linha = folha["declaradas_documento"][0]
    assert (
        linha["conflito"]
        and linha["quantidade"] is None
        and linha["valores_afirmados"] == [12.0, 250.0]
    )
    assert folha["situacao"] == "a preencher"


def test_fonte_mais_forte_vence_a_leitura_de_ia(base, raiz):
    nova, _ = gavetas_ia.aplicar(base, [_linha()], raiz)
    nova["objetos"].append({"objeto_id": "c211-0", "classe": "item_contrato"})
    nova["evidencias"].append(
        {
            "evidencia_id": "EV-c211-0",
            "classe": "planilha",
            "documento": "planilha1",
            "localizador": {"aba": "CUSTO CIVIL", "linha": 5},
            "metodo": "planilha",
            "executor": "código",
        }
    )
    for propriedade, valor in (
        ("folha_eap", FOLHA),
        ("unidade_medida", "UN"),
        ("quantidade", 99.0),
    ):
        nova["fatos"].append(
            {
                "fato_id": f"c211-0.{propriedade}",
                "objeto_id": "c211-0",
                "propriedade": propriedade,
                "valor": valor,
                "natureza": "projetado",
                "evidencia_id": "EV-c211-0",
            }
        )
    folha = _folha(ep.preencher(nova), FOLHA)
    assert (
        folha["situacao"] == "declarada"
        and folha["fonte_declarada"] == "declarada (contrato)"
    )
    assert folha["totais_declaradas"] == [{"unidade": "un", "quantidade": 99.0}]
    assert folha["totais_declaradas_documento"] == [
        {"unidade": "un", "quantidade": 250.0}
    ]  # listada, nunca somada
    nova["objetos"].append(
        {"objeto_id": "e1", "classe": "estaca", "unidade": "u1", "sistema": "u1-ACT600"}
    )
    nova["evidencias"].append(
        {
            "evidencia_id": "EV-e1",
            "classe": "projeto",
            "documento": DOCUMENTO_ID,
            "localizador": {"pagina": 3},
            "metodo": "camadas.prancha",
            "executor": "código",
        }
    )
    nova["fatos"].append(
        {
            "fato_id": "e1.rotulo",
            "objeto_id": "e1",
            "propriedade": "rotulo",
            "valor": "e1",
            "natureza": "projetado",
            "evidencia_id": "EV-e1",
        }
    )
    assert _folha(ep.preencher(nova), FOLHA)["situacao"] == "preenchida"


def test_servico_da_leitura_so_vale_na_folha_que_o_pede(base, raiz):
    arrasamento = _linha(servico="arrasamento", unidade="un", valor=250.0)
    nova, resumo = gavetas_ia.aplicar(base, [arrasamento], raiz)
    assert resumo["aceitas"] == 1, nova["pendencias"]
    eap = ep.preencher(nova)
    assert _folha(eap, "OP.03.02")["situacao"] == "declarada"
    assert _folha(eap, FOLHA)["situacao"] == "a preencher"


def test_idempotente_e_sem_ia_limpa(base, raiz):
    linhas = [
        _linha(),
        _linha(valor=300.0, trecho="Serao executadas 300 estacas helice continua."),
    ]
    uma, _ = gavetas_ia.aplicar(base, linhas, raiz)
    duas, _ = gavetas_ia.aplicar(uma, linhas, raiz)
    assert json.dumps(uma, sort_keys=True, default=str) == json.dumps(
        duas, sort_keys=True, default=str
    )
    assert gavetas.conferir_base(duas) == []
    assert gavetas_ia.sem_ia(duas) == base


def test_a_base_com_leitura_de_ia_faz_ida_e_volta_no_parquet(base, raiz, tmp_path):
    nova, _ = gavetas_ia.aplicar(base, [_linha()], raiz)
    gavetas.gravar(tmp_path / "base", nova)
    lida = gavetas.ler(tmp_path / "base")
    assert gavetas.conferir_base(lida) == []
    assert (
        _folha(ep.preencher(lida), FOLHA)["fonte_declarada"] == "declarada (documento)"
    )


def test_fechar_eap_aplica_a_leitura_de_ia_e_sem_ela_nada_muda(base, raiz, tmp_path):
    from camadas import extrair_gavetas

    out = tmp_path / "saida"
    base["objetos"].append(
        {"objeto_id": "e0", "classe": "estaca"}
    )  # a gaveta vazia não deixa arquivo (`fechar_eap` exige a base)
    gavetas.gravar(out / "base", base)
    arquivo = tmp_path / "ia.jsonl"
    inventada = _linha(valor=300.0, trecho="inventado 300 estacas")
    arquivo.write_text(
        json.dumps(_linha()) + "\n" + json.dumps(inventada) + "\n", encoding="utf-8"
    )
    cfg = {"inventario": {"pasta": str(raiz)}, "evidencias": {"ia": str(arquivo)}}
    mensagens = []
    resumo = extrair_gavetas.fechar_eap(cfg, out, {}, mensagens.append, [])
    assert resumo["leitura_ia"] == {
        "aplicada": True,
        "linhas": 2,
        "aceitas": 1,
        "recusadas": 1,
        "mencoes": 0,
    }
    assert (
        resumo["eap_unica"]["completude"]["obra_localizada"]["declarada_documento"] == 1
    )
    assert any("Leitura de IA: 2 linha(s), 1 aceita(s)" in m for m in mensagens)
    de_novo = extrair_gavetas.fechar_eap(cfg, out, {}, lambda *_: None, [])
    assert (
        de_novo["leitura_ia"]["aceitas"] == 1
        and len(gavetas.ler(out / "base")["objetos"]) == 2
    )  # idempotente
    sem = extrair_gavetas.fechar_eap(
        {"inventario": cfg["inventario"]}, out, {}, mensagens.append, []
    )
    assert (
        sem["leitura_ia"]["aplicada"] is False
        and "sem evidencias.ia" in sem["leitura_ia"]["motivo"]
    )
    assert [o["objeto_id"] for o in gavetas.ler(out / "base")["objetos"]] == ["e0"]


def _linha_da_folha(codigo, quantidade, conflito=False):
    return {"codigo": codigo, "servico": "", "unidade": "un", "citacoes": [{"documento": codigo}],
            "quantidade": quantidade, "valores_afirmados": [quantidade] if quantidade is not None else [],
            "conflito": conflito}


def test_total_com_asterisco_e_partes_por_sistema_nao_somam():
    from camadas import eap_preencher as ep

    partes = [_linha_da_folha("U1.ACT360.GEO.FUN.EST", 100.0), _linha_da_folha("U1.ACT600.GEO.FUN.EST", 150.0)]
    assert sum(x["quantidade"] for x in ep._sem_dupla_contagem(partes)) == 250.0  # só partes: somam
    confere = ep._sem_dupla_contagem([_linha_da_folha("U1.*.GEO.FUN.EST", 250.0), *partes])
    assert len(confere) == 1 and confere[0]["quantidade"] == 250.0 and not confere[0]["conflito"]
    diverge = ep._sem_dupla_contagem([_linha_da_folha("U1.*.GEO.FUN.EST", 300.0), *partes])
    assert len(diverge) == 1 and diverge[0]["quantidade"] is None and diverge[0]["conflito"]
    assert diverge[0]["valores_afirmados"] == [250.0, 300.0]
