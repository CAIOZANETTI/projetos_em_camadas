"""Leitura por IA: o roteiro diz o que procurar; `conferir` só aceita a citação que está no documento."""

import json

from camadas import evidencias

MEMORIAL = "memorial_fundacoes.pdf"
PAGINAS = [
    "Fundações\nSerão executadas 250 estacas hélice contínua.",
    "Escavação de 1.200,5 m³ de solo na cava.",
]


def _linha(**campos) -> str:
    ev = {
        "codigo": "U1.*.GEO.FUN.EST",
        "servico": "",
        "unidade": "un",
        "valor": 250.0,
        "parcela": False,
        "documento": {"id": MEMORIAL, "tipo": "ia"},
        "localizador": "p. 1",
        "metodo": "ia",
        "trecho": "Serão executadas 250 estacas hélice contínua.",
    }
    return json.dumps({**ev, **campos}, ensure_ascii=False)


def test_roteiro_filtra_por_escopo_e_traz_servicos_e_unidades():
    esgoto = {i["codigo"]: i for i in evidencias.roteiro("esgoto")}
    agua = {i["codigo"] for i in evidencias.roteiro("agua")}
    assert (
        "GER.CTL.CFT" in esgoto and "GER.CTL.CFT" not in agua
    )  # PVS vale para os dois escopos
    assert "HID.TUB.PVS" in esgoto and "HID.TUB.PVS" in agua
    estaca = esgoto["GEO.FUN.EST"]
    assert "estaca" in estaca["termos"] and "helice continua" in estaca["termos"]
    assert {s["id"]: s["unidades"] for s in estaca["servicos"]}["concreto"] == ["m³"]
    assert {"un", "m³", "kg"} <= set(estaca["unidades"])


def test_roteiro_filtra_por_tipo_de_obra():
    lineares = {i["codigo"] for i in evidencias.roteiro(obra="linear")}
    assert "GEO.MOV.VAL" in lineares and "GEO.FUN.EST" not in lineares


def test_conferir_arquivo_aceita_a_citacao_certa_e_recusa_as_falhas():
    linhas = [
        _linha(),
        _linha(
            trecho="Serão executadas 300 estacas.", valor=300.0
        ),  # trecho inexistente
        _linha(valor=280.0),  # valor fora do trecho
        _linha(documento={"id": "outro.pdf", "tipo": "ia"}),  # documento ausente
        _linha(metodo="regex"),  # fora do schema
        json.dumps({"codigo": "U1.*.GEO.FUN.EST"}),  # faltam campos
        "isto não é json",
    ]
    aceitas, recusadas = evidencias.conferir_arquivo(linhas, {MEMORIAL: PAGINAS})
    assert [e["citacao"] for e in aceitas] == ["conferida"] and aceitas[0]["id"]
    motivos = [r["motivo"] for r in recusadas]
    assert motivos[0] == "trecho não encontrado no documento"
    assert motivos[1] == "valor não está no trecho"
    assert motivos[2].startswith("documento não fornecido")
    assert all(m.startswith("schema inválido") for m in motivos[3:5])
    assert motivos[5].startswith("schema inválido: JSON inválido")
    assert [r["linha"] for r in recusadas] == [2, 3, 4, 5, 6, 7]


def test_conferir_arquivo_aceita_mencao_sem_valor():
    aceitas, recusadas = evidencias.conferir_arquivo(
        [_linha(valor=None, unidade=None, trecho="executadas 250 estacas")],
        {MEMORIAL: PAGINAS},
    )
    assert len(aceitas) == 1 and not recusadas


def test_cli_conferir_grava_so_as_aceitas(tmp_path, capsys):
    documento = tmp_path / "memorial_fundacoes.txt"
    documento.write_text("\f".join(PAGINAS), encoding="utf-8")
    ia = tmp_path / "ia.jsonl"
    ia.write_text(
        "".join(
            _linha(documento={"id": documento.name, "tipo": "ia"}, **extra) + "\n"
            for extra in ({}, {"valor": 280.0})
        ),
        encoding="utf-8",
    )
    saida = tmp_path / "aceitas.jsonl"
    codigo = evidencias.main(
        ["conferir", str(ia), "--texto", str(documento), "--saida", str(saida)]
    )
    texto = capsys.readouterr().out
    assert (
        codigo == 0
        and "1 aceitas, 1 recusadas" in texto
        and "valor não está no trecho" in texto
    )
    gravadas = evidencias.ler(saida)
    assert (
        len(gravadas) == 1
        and gravadas[0]["valor"] == 250.0
        and gravadas[0]["citacao"] == "conferida"
    )


def test_cli_conferir_sem_arquivo_de_entrada_sai_com_2(tmp_path, capsys):
    assert evidencias.main(["conferir", str(tmp_path / "nao_existe.jsonl")]) == 2
    assert "não existe" in capsys.readouterr().out


def test_cli_roteiro_gera_markdown_com_os_codigos(tmp_path, capsys):
    arquivo = tmp_path / "roteiro.md"
    assert (
        evidencias.main(["roteiro", "--escopo", "esgoto", "--saida", str(arquivo)]) == 0
    )
    md = arquivo.read_text(encoding="utf-8")
    assert (
        "## GER.CTL.CFT" in md and "## GEO.FUN.EST" in md and "Unidades aceitas" in md
    )
    capsys.readouterr()
    assert evidencias.main(["roteiro", "--escopo", "agua"]) == 0
    assert (
        "GER.CTL.CFT" not in capsys.readouterr().out
    )  # PVS agora vale para água também


def test_ia_conferida_entra_na_consolidacao():
    aceitas, _ = evidencias.conferir_arquivo([_linha()], {MEMORIAL: PAGINAS})
    fatos = evidencias.consolidar(aceitas)
    assert fatos.iloc[0]["status"] == "fonte única" and fatos.iloc[0]["valor"] == 250.0
