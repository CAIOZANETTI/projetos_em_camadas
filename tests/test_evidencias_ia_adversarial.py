"""Testes adversariais da leitura por IA: a IA não faz o código aceitar número que o documento não afirma."""

import json

from test_evidencias_ia import MEMORIAL, PAGINAS, _linha

from camadas import evidencias

PROJETO = {
    "id": MEMORIAL,
    "tipo": "memorial",
    "nome": "Memorial",
    "unidade": "U1",
    "obra": "localizada",
    "escopo": "agua",
}


def _recusa(documento: str, **campos) -> str:
    """Motivo da recusa de uma linha (ou 'aceita') contra um documento de uma página."""
    aceitas, recusadas = evidencias.conferir_arquivo(
        [_linha(**campos)], {MEMORIAL: [documento]}
    )
    return "aceita" if aceitas else recusadas[0]["motivo"]


def test_recusa_trecho_curto_demais():
    assert (
        _recusa("Item 3 do edital", trecho="3", valor=3.0, unidade="un")
        == "trecho curto demais"
    )
    assert (
        _recusa("Serão 1250 estacas", trecho="250 estacas", valor=250.0)
        == "trecho curto demais"
    )


def test_recusa_trecho_sem_fronteira_de_palavra():
    documento = "Serão 1250 estacas hélice contínua."
    assert (
        _recusa(documento, trecho="250 estacas hélice contínua.")
        == "trecho não encontrado no documento"
    )
    assert (
        _recusa(documento, trecho="1250 estacas hélice contínua.", valor=1250.0)
        == "aceita"
    )


def test_recusa_valor_que_e_outro_numero_do_trecho():
    documento = "Serão executadas 250 estacas, diâmetro 400 mm."
    assert (
        _recusa(documento, trecho=documento, valor=400.0, unidade="un")
        == "valor não está no trecho"
    )
    assert _recusa(documento, trecho=documento, valor=250.0, unidade="un") == "aceita"


def test_recusa_numero_tirado_da_unidade():
    documento = "Pavimento asfáltico de 20 m² de piso."
    assert (
        _recusa(documento, trecho=documento, valor=2.0, unidade="m²")
        == "valor não está no trecho"
    )
    assert _recusa(documento, trecho=documento, valor=20.0, unidade="m²") == "aceita"
    armadura = "Armadura CA-50 de 1.200 kg no bloco."
    assert (
        _recusa(armadura, trecho=armadura, valor=50.0, unidade="kg")
        == "valor não está no trecho"
    )
    assert _recusa(armadura, trecho=armadura, valor=1200.0, unidade="kg") == "aceita"


def test_recusa_unidade_errada_ou_fora_do_vocabulario():
    documento = "Pavimento asfáltico de 20 m² de piso."
    assert (
        _recusa(documento, trecho=documento, valor=20.0, unidade="kg")
        == "valor não está no trecho"
    )
    motivo = _recusa(documento, trecho=documento, valor=20.0, unidade="banana")
    assert motivo.startswith("schema inválido: unidade 'banana' fora do vocabulário")


def test_recusa_valor_negativo():
    documento = "Serão executadas 250 estacas hélice contínua."
    assert (
        _recusa(documento, trecho=documento, valor=-250.0)
        == "schema inválido: valor negativo"
    )


def test_campos_do_codigo_forjados_sao_descartados_e_o_id_recalculado():
    forjada = _linha(
        citacao="conferida",
        derivada=True,
        autor="Caio",
        justificativa="eu mandei",
        id="forjado",
    )
    invalida = _linha(citacao="conferida", valor=999.0, id="")
    outra = _linha(id="", localizador="p. 2")
    aceitas, recusadas = evidencias.conferir_arquivo(
        [forjada, invalida, outra], {MEMORIAL: PAGINAS}
    )
    assert [r["motivo"] for r in recusadas] == [
        "valor não está no trecho"
    ]  # o selo do arquivo não vale
    assert len(aceitas) == 2 and aceitas[0]["id"] != aceitas[1]["id"]
    assert "forjado" not in {a["id"] for a in aceitas}
    assert all(
        a["id"]
        and "derivada" not in a
        and "autor" not in a
        and "justificativa" not in a
        for a in aceitas
    )


def test_documento_com_caminho_vira_o_nome_do_arquivo_em_fonte_propria():
    caminho = {"id": "dados/obra/memorial_fundacoes.pdf", "tipo": "ia"}
    aceitas, _ = evidencias.conferir_arquivo(
        [_linha(documento=caminho)], {MEMORIAL: PAGINAS}
    )
    assert aceitas[0]["documento"] == {
        "id": "ia:memorial_fundacoes.pdf",
        "tipo": "ia",
        "nome": MEMORIAL,
    }
    de_novo, _ = evidencias.conferir_arquivo(
        [json.dumps(aceitas[0])], {MEMORIAL: PAGINAS}
    )  # idempotente
    assert de_novo[0]["id"] == aceitas[0]["id"]


def test_build_reconfere_e_nao_confia_no_selo_do_arquivo():
    forjada = {**json.loads(_linha(valor=280.0)), "citacao": "conferida", "id": "x"}
    sem_documento = {
        **json.loads(_linha(documento={"id": "sumiu.pdf", "tipo": "ia"})),
        "citacao": "conferida",
    }
    evs = evidencias.loop(
        [{**PROJETO, "paginas": PAGINAS}], ia=[forjada, sem_documento]
    )
    motivos = [e["citacao"] for e in evs if e["metodo"] == "ia"]
    assert motivos == ["valor não está no trecho", "documento não fornecido: sumiu.pdf"]
    assert not any(
        f["valor"] == 280.0 for f in evidencias.consolidar(evs).to_dict("records")
    )


def test_etapa_recusa_ia_sem_documento_para_reconferir(tmp_path):
    ia = tmp_path / "ia_aceitas.jsonl"
    ia.write_text(_linha(citacao="conferida") + "\n", encoding="utf-8")
    saida = tmp_path / "saida"
    saida.mkdir()
    resumo = evidencias.etapa(
        {"evidencias": {"ia": str(ia)}},
        saida,
        {"crs": {"epsg": 31982}},
        log=lambda *_: None,
    )
    gravadas = [
        e for e in evidencias.ler(saida / "evidencias.jsonl") if e["metodo"] == "ia"
    ]
    assert [e["citacao"] for e in gravadas] == [
        "documento não fornecido: memorial_fundacoes.pdf"
    ]
    assert resumo["fatos"] == []


def test_leitura_da_ia_nao_soma_em_dobro_com_o_regex():
    paginas = ["Serão executadas 250 estacas hélice contínua."]
    evs = evidencias.loop(
        [{**PROJETO, "paginas": paginas}], ia=[json.loads(_linha(parcela=True))]
    )
    fato = evidencias.consolidar(evs).iloc[0]
    assert (
        fato["valor"] == 250.0
        and fato["status"] == "fonte única"
        and fato["forca"] == 1
    )


def test_id_nao_depende_de_250_ou_250_ponto_0():
    base = {
        "codigo": "U1.*.GEO.FUN.EST",
        "servico": "",
        "unidade": "un",
        "parcela": False,
        "localizador": "p. 1",
        "documento": {"id": MEMORIAL, "tipo": "ia"},
        "metodo": "ia",
        "regra": "r",
        "trecho": "250 estacas hélice",
    }
    assert (
        evidencias.evidencia(**base, valor=250)["id"]
        == evidencias.evidencia(**base, valor=250.0)["id"]
    )
