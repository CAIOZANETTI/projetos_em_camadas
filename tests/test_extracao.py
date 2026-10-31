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
    assert extracao.series(itens) == [{"pasta_drive": "PBGE", "disciplina": "PBGE", "unidade": "0017-8820", "total": 5,
                                       "presentes": 3, "faltam": ["03/05", "05/05"], "fora_do_disco_na_pasta": 0}]


def test_pendencias_e_registro_so_quando_muda(tmp_path):
    inv = {"itens": [_item("Memorial.docx", leitor=None), _item("proposta.pdf", "04. COTAÇÕES", situacao="não tentado"),
                     _item("Planilha.xlsx", leitor="ler_planilha", abas=[{"aba": "A"}])]}
    p = extracao.pendencias(inv)
    assert [a["arquivo"] for a in p["pendencias"]] == ["Memorial.docx"]          # cotação fica fora do escopo
    assert p["por_estado"] == {"sem leitor": 1, "fora do disco": 1, "completa": 1} and p["fracao_completa"] == 0.5
    assert p["fora_do_escopo"] == [{"arquivo": "proposta.pdf", "pasta_drive": "04. COTAÇÕES", "classe": "cotacao",
                                    "fora_do_escopo": "preço"}]                       # listada à parte, não some
    registro = tmp_path / "extracao.jsonl"
    assert extracao.registrar(p["avaliacoes"], registro, "P1") == 3
    assert extracao.registrar(p["avaliacoes"], registro, "P1") == 0                 # nada mudou, nada novo
    resolvido = [{**p["avaliacoes"][0], "estado": "completa", "faltando": []}]
    assert extracao.registrar(resolvido, registro, "P2", "Sonnet") == 1
    ultima = json.loads(registro.read_text(encoding="utf-8").splitlines()[-1])
    assert (ultima["passe"], ultima["executor"], ultima["estado"]) == ("P2", "Sonnet", "completa")
    menos_falta = [{**p["avaliacoes"][2], "estado": "completa", "faltando": ["x"]}]
    assert extracao.registrar(menos_falta, registro, "P3") == 1                    # mesmo estado, falta outra coisa


def test_casos_reais_da_revisao_independente():
    """Casos apontados pelo Fable (30/10): termo sem fronteira, pasta mandando mais que o nome, classe sem exigência
    saindo completa sem nada lido, foto mandada para a IA mais cara."""
    cl = lambda nome, pasta="": extracao.classe(_item(nome, pasta))
    assert cl("Informacoes complementares ao edital.pdf", "EDITAL") == "edital"          # FORMA não casa INFORMAÇÕES
    assert cl("Perfil de sondagem SP-01.pdf", "GEOTECNIA") == "laudo"
    assert cl("Memorial descritivo hidraulico.pdf", "PROJETOS/PLANTAS") == "memorial"
    assert cl("004-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYOUTPROCES-R5.pdf", "OBRA/ORDENS DE SERVIÇO") == "projeto"
    assert cl("004-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYOUTPROCES-R5.pdf", "04. COTAÇÕES") == "projeto"
    assert cl("Atas de reuniao.pdf", "OBRA/ATAS") == "documento_obra"
    assert cl("Relatorio de medicao 03.pdf") == "documento_obra"
    assert cl("Planilha do contrato.pdf") == "planilha"
    os_escaneada = _item("OS 015-2027.pdf", leitor="ler_pdf", texto="pouco ou nenhum (traço/SHX ou imagem)")
    assert (extracao.avaliar(os_escaneada)["estado"], extracao.avaliar(os_escaneada)["situacao"]) == ("parcial", "sem texto")
    foto = extracao.avaliar(_item("DJI_0249.JPG", "fotos_drone", leitor=None))
    assert (foto["estado"], foto["proximo"]) == ("completa", None)
    vazia = extracao.avaliar(_item("Quantitativos.xlsx", leitor="ler_planilha", abas=[]))
    assert (vazia["situacao"], vazia["proximo"]) == ("leitura incompleta", "código")


def test_series_por_unidade_e_com_aviso_de_fora_do_disco():
    a = _item("001-SAA-0017-8820-PBGE-DE-0000X-R2.pdf", "PBGE", carimbo={"folha": "01/02"})
    b = _item("001-SAA-0017-7471-PBGE-DE-0000Y-R2.pdf", "PBGE", carimbo={"folha": "01/02"})   # outra unidade
    c = _item("002-SAA-0017-7471-PBGE-DE-0000Z-R2.pdf", "PBGE", situacao="não tentado")
    s = extracao.series([a, b, c])
    assert [(x["unidade"], x["faltam"], x["fora_do_disco_na_pasta"]) for x in s] == \
        [("0017-7471", ["02/02"], 1), ("0017-8820", ["02/02"], 1)]


def _inv(*itens):
    return {"itens": list(itens), "fonte": "teste"}


def _sis(tipologia="estrutura_concreto", **extra):
    return {"S1": {"nome": "Sistema 1", "tipologia": tipologia, "chaves": ["~MOD ?01(?!\\d)"], **extra}}


def test_esperado_x_encontrado_no_disco_fora_do_disco_e_nao_achado():
    inv = _inv(_item("001-SAA-MOD01FORMA-R1.pdf", "PBES"),
               _item("002-SAA-MOD01ARMADURA-R1.pdf", "PBES", situacao="não tentado"),
               _item("003-SAA-MOD02FORMA-R1.pdf", "PBES"))                       # outro módulo: não conta
    linhas = {l["documento"]: l for l in extracao.esperado_x_encontrado(inv, _sis())}
    assert linhas["forma"]["situacao"] == "no disco" and linhas["forma"]["arquivos"] == ["001-SAA-MOD01FORMA-R1.pdf"]
    assert linhas["armadura"]["situacao"] == "fora do disco"
    assert linhas["locacao_cargas"]["situacao"] == "não achado" and "listagem inteira" in linhas["locacao_cargas"]["resposta"]
    assert linhas["locacao_cargas"]["arquivos"] == [] and linhas["forma"]["tipologia"] == "estrutura_concreto"


def test_rede_exige_so_planta_e_perfil_e_geral_nada():
    inv = _inv(_item("PLANTA E PERFIL REDE R1.pdf", "REDE1"))
    rede = {"R": {"nome": "Rede", "tipologia": "rede", "chaves": ["REDE ?1"]}}
    geral = {"G": {"nome": "Geral", "tipologia": "geral", "chaves": ["REDE ?1"]}}
    linhas = extracao.esperado_x_encontrado(inv, rede)
    assert [(l["documento"], l["situacao"]) for l in linhas] == [("planta", "no disco"), ("perfil", "no disco")]   # sem "forma"
    assert extracao.esperado_x_encontrado(inv, geral) == []                                   # geral não exige nada
    assert extracao.esperado_x_encontrado(_inv(), rede)[0]["situacao"] == "não achado"


def test_exclui_do_sistema_tira_o_arquivo():
    inv = _inv(_item("MOD01 FORMA EEE FILTROS.pdf", "PBES"), _item("MOD01 FORMA.pdf", "PBES"))
    linhas = extracao.esperado_x_encontrado(inv, _sis(exclui=["EEE ?FILTROS"]))
    assert [l["arquivos"] for l in linhas if l["documento"] == "forma"] == [["MOD01 FORMA.pdf"]]


def test_todas_as_tipologias_tem_documentos_esperados():
    tipologias = json.loads((extracao.pdf_cad.CONCEITOS / "construcao_civil.json").read_text(encoding="utf-8"))["tipologias"]
    assert set(tipologias) == set(extracao.ESPERADOS) and extracao.ESPERADOS["geral"]["documentos"] == []
    assert {d["id"] for d in extracao.ESPERADOS["rede"]["documentos"]} == {"planta", "perfil"}


def test_papel_pelo_prefixo_mais_longo_sem_acento():
    pastas = {"01. RECEBIDOS": "licitacao", "01. RECEBIDOS/ORDENS": "obra", "05. ORÇAMENTO": "orcamento"}
    papel = lambda pasta: extracao.papel(_item("a.pdf", pasta), pastas)
    assert papel("01. RECEBIDOS/ORDENS/2027") == "obra" and papel("01. RECEBIDOS/EDITAL") == "licitacao"
    assert papel("05. ORCAMENTO/planilhas") == "orcamento" and papel("05. orçamento") == "orcamento"
    assert papel("01. RECEBIDOS EXTRAS") is None and papel("OUTRA") is None and extracao.papel(_item("a.pdf"), None) is None
    av = extracao.avaliar(_item("a.pdf", "05. ORÇAMENTO"), pastas)
    assert av["papel"] == "orcamento" and "papel" not in extracao.avaliar(_item("a.pdf"))
    p = extracao.pendencias(_inv(_item("a.pdf", "05. ORÇAMENTO"), _item("b.pdf", "X")), pastas)
    assert p["por_papel"] == {"orcamento": 1, "sem papel": 1}


def test_papel_prefixo_vazio_casa_tudo_e_perde_para_o_mais_longo():
    pastas = {"": "licitacao", "05. ORÇAMENTO": "orcamento"}
    papel = lambda pasta: extracao.papel(_item("a.pdf", pasta), pastas)
    assert papel("UNIDADE 01") == "licitacao" and papel("ANEXO A/sub") == "licitacao" and papel("") == "licitacao"
    assert papel("05. ORCAMENTO/x") == "orcamento"


def test_complemento_completa_o_item_e_sobrevive_a_nova_volta(tmp_path):
    inv = _inv(_item("004-SAA-0017-7471-PBHI-DE-0001ETAVILACLAYOUTPROCES-R5.pdf", leitor="ler_pdf", texto="sim",
                     carimbo={"titulo": "LAYOUT"}))
    caminho = tmp_path / "saida" / "complementos.json"
    assert extracao.ler_complementos(caminho) == {}
    antes = extracao.pendencias(inv, complementos=extracao.ler_complementos(caminho))["avaliacoes"][0]
    assert antes["estado"] == "parcial" and "complementado_por" not in antes
    item = inv["itens"][0]
    extracao.gravar_complemento(caminho, item, {"carimbo": {"escala": "1:100"}}, "Haiku", "ia")
    e = extracao.gravar_complemento(caminho, item, {"carimbo": {"folha": "01/01"}}, "Sonnet", "ia")
    assert e["tentativas"] == {"ia": 2} and e["executor"] == "Sonnet"
    assert e["campos"] == {"carimbo": {"escala": "1:100", "folha": "01/01"}}
    for _ in range(2):                                       # nova volta com o mesmo inventário
        p = extracao.pendencias(inv, complementos=extracao.ler_complementos(caminho))
        assert p["avaliacoes"][0]["estado"] == "completa" and p["avaliacoes"][0]["complementado_por"] == "Sonnet"
    assert inv["itens"][0]["carimbo"] == {"titulo": "LAYOUT"}   # o item do inventário não é alterado
    assert "extracao.jsonl" not in [x.name for x in tmp_path.rglob("*")]
