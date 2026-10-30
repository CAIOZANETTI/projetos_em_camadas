import json

from camadas import extracao


def _item(arquivo, pasta="UNIDADE 01", situacao="no disco", **extra):
    return {"arquivo": arquivo, "pasta_drive": pasta, "id_drive": arquivo[:3], "situacao": situacao,
            "codigo": extracao.inventario.codigo_sanepar(arquivo), **extra}


def test_classe_da_fonte_pelo_sinal_mais_seguro():
    assert extracao.classe(_item("004-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYOUTPROCES-R5.pdf")) == "projeto"
    assert extracao.classe(_item("01-SAA-0017-8764-PMEC-MD-0001ETAVILACPLANTA01-R0.pdf")) == "memorial"   # MD vence PLANTA
    assert extracao.classe(_item("Relatorio sondagem Geoazimute.pdf")) == "laudo"
    assert extracao.classe(_item("211 - SAA Foz.xlsx", "05. ORÇAMENTO")) == "planilha"
    assert extracao.classe(_item("proposta.pdf", "04. COTAÇÕES")) == "cotacao"
    assert extracao.classe(_item("OS 015-2027 esgoto.pdf", "OBRA/ORDENS DE SERVIÇO")) == "documento_obra"
    assert extracao.classe(_item("Folha de dados bomba B-01.pdf")) == "folha_de_dados"
    assert extracao.classe(_item("Anexo A - Termo de Referência R20.pdf")) == "edital"
    assert extracao.classe(_item("xyz.bin")) == "outro"


def test_estado_e_proximo_passe_da_escada():
    completo = _item("003-SAA-0017-8820-PBGE-DE-0000ETA01FUNDACAO1-R2.pdf", leitor="ler_pdf", texto="sim",
                     carimbo={"titulo": "FUNDAÇÃO 1", "folha": "03/14", "escala": "1:100"})
    sem_escala = {**completo, "carimbo": {"titulo": "FUNDAÇÃO 1", "folha": "03/14", "escala": None}}
    laudo_imagem = _item("Relatorio sondagem.pdf", leitor="ler_pdf", texto="pouco ou nenhum (traço/SHX ou imagem)")
    av = {k: extracao.avaliar(v) for k, v in {
        "completo": completo, "sem_escala": sem_escala, "laudo_imagem": laudo_imagem,
        "fora": _item("ACT360FORMA.pdf", situacao="não tentado"),
        "docx": _item("Memorial.docx", leitor=None),
        "zip": _item("formas.zip", leitor="ler_zip", arquivos_dentro=2),
        "erro": _item("x.pdf", leitor="ler_pdf", erro="FileDataError: broken")}.items()}
    assert av["completo"]["estado"] == "completa" and av["completo"]["proximo"] is None
    assert (av["sem_escala"]["estado"], av["sem_escala"]["faltando"], av["sem_escala"]["proximo"]) == \
        ("parcial", ["carimbo.escala"], "código")
    assert (av["laudo_imagem"]["situacao"], av["laudo_imagem"]["proximo"]) == ("sem texto", "código")
    assert (av["fora"]["estado"], av["fora"]["proximo"]) == ("fora do disco", "código")
    assert (av["docx"]["estado"], av["docx"]["proximo"]) == ("sem leitor", "Sonnet")
    assert (av["zip"]["estado"], av["zip"]["situacao"]) == ("parcial", "conteúdo não inventariado")
    assert av["erro"]["estado"] == "falhou"


def test_serie_de_folhas_aponta_as_que_faltam():
    itens = [_item(f"{n:03d}-SAA-0017-8820-PBGE-DE-0000ETA01X{n}-R2.pdf", "PBGE", carimbo={"folha": f"{n:02d}/05"})
             for n in (1, 2, 4)]
    itens.append(_item("001-SAA-0017-7471-PBHI-DE-0001A-R1.pdf", "PBHI", carimbo={"folha": "01/01"}))
    assert extracao.series(itens) == [{"pasta_drive": "PBGE", "disciplina": "PBGE", "total": 5, "presentes": 3,
                                       "faltam": ["03/05", "05/05"]}]


def test_pendencias_e_registro_so_quando_muda(tmp_path):
    inv = {"itens": [_item("Memorial.docx", leitor=None), _item("proposta.pdf", "04. COTAÇÕES", situacao="não tentado"),
                     _item("Planilha.xlsx", leitor="ler_planilha", abas=[{"aba": "A"}])]}
    p = extracao.pendencias(inv)
    assert [a["arquivo"] for a in p["pendencias"]] == ["Memorial.docx"]          # cotação fica fora do escopo
    assert p["por_estado"] == {"sem leitor": 1, "fora do disco": 1, "completa": 1} and p["completas_por_codigo"] == 0.333
    registro = tmp_path / "extracao.jsonl"
    assert extracao.registrar(p["avaliacoes"], registro, "P1") == 3
    assert extracao.registrar(p["avaliacoes"], registro, "P1") == 0                 # nada mudou, nada novo
    resolvido = [{**p["avaliacoes"][0], "estado": "completa", "faltando": []}]
    assert extracao.registrar(resolvido, registro, "P2", "Sonnet") == 1
    ultima = json.loads(registro.read_text(encoding="utf-8").splitlines()[-1])
    assert (ultima["passe"], ultima["executor"], ultima["estado"]) == ("P2", "Sonnet", "completa")
