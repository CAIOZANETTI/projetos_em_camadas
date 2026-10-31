import json
import zipfile

import pytest

from camadas import escada, extracao, inventario

pymupdf = pytest.importorskip("pymupdf")

NOME = "006-SAA-0017-8820-PBGE-DE-0000ETA01ESCAVACAO1-R2.pdf"
CABECALHO = "caminho;titulo;id;mimeType;extensao;tamanho_bytes;modificado\n"


def _prancha(caminho, escala=True):
    """Folha A1 com carimbo Sanepar em texto; sem `escala` o carimbo fica incompleto."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    pg = doc.new_page(width=2384, height=1684)
    linhas = ["Companhia de Saneamento do Paraná", "MUNICÍPIO/SISTEMA: FOZ DO IGUAÇU - PR FOLHA N°: 06/14",
              "PROJETO / UNIDADE CONSTRUTIVA: DATA: OUTUBRO/2025", "PLANTA DE ESCAVAÇÃO"] + (["ESCALA: 1:100"] if escala else [])
    for k, t in enumerate(linhas):
        pg.insert_text((2384 - 520, 1684 - 260 + 30 * k), t, fontsize=10)
    pg.insert_text((100, 100), "texto de desenho " * 10, fontsize=8)
    doc.save(caminho)


def _obra(tmp_path, linhas):
    """cfg mínimo: pasta de projeto, listagem com as `linhas` e `_baixados.csv` só com o cabeçalho."""
    pasta = tmp_path / "projeto"
    pasta.mkdir(exist_ok=True)
    listagem = tmp_path / "listagem.csv"
    listagem.write_text(CABECALHO + "".join(f"{p};{t};{i};x;{t.rsplit('.', 1)[-1]};10;x\n" for p, t, i in linhas),
                        encoding="utf-8")
    (tmp_path / "_baixados.csv").write_text("caminho;titulo;id;bytes;ok\n", encoding="utf-8")
    return {"inventario": {"listagem": str(listagem), "pasta": str(pasta), "baixados": str(tmp_path / "_baixados.csv")}}, \
        pasta, tmp_path / "saida"


@pytest.fixture(autouse=True)
def _sem_ocr(monkeypatch):
    monkeypatch.setattr(inventario, "ocr_carimbo", lambda pagina, dpi=200: "")


def _lote(out, executor):
    arq = out / "lotes" / f"{executor}.jsonl"
    return [json.loads(l) for l in arq.read_text(encoding="utf-8").splitlines()] if arq.exists() else []


def test_fora_do_disco_baixa_e_completa_na_segunda_volta(tmp_path):
    cfg, pasta, out = _obra(tmp_path, [("UNIDADE 01", NOME, "abc")])
    chamadas = []

    def baixar(file_id, destino, tamanho=None):
        chamadas.append(file_id)
        _prancha(destino)
        return {"ok": True, "bytes": 1, "motivo": ""}

    r = escada.executar(cfg, out, voltas=3, baixar=baixar)
    assert chamadas == ["abc"] and r["voltas"] == 1
    assert r["por_estado"] == {"completa": 1} and r["lotes"] == {}
    passes = [json.loads(l) for l in (out / "extracao.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(x["passe"], x["estado"]) for x in passes] == [("V1", "fora do disco"), ("V2", "completa")]
    assert extracao.ler_complementos(out / "complementos.json")[f"UNIDADE 01/{NOME}"]["tentativas"] == {"código:baixar": 1}


def test_carimbo_incompleto_sobe_para_haiku(tmp_path, monkeypatch):
    cfg, pasta, out = _obra(tmp_path, [("UNIDADE 01", NOME, "abc")])
    _prancha(pasta / "UNIDADE 01" / NOME, escala=False)
    monkeypatch.setattr(inventario, "reler_carimbo", lambda caminho, dpi=300: {"folha": None, "escala": None,
                                                                              "data": None, "titulo": None})
    r = escada.executar(cfg, out, voltas=5)
    tent = extracao.ler_complementos(out / "complementos.json")[f"UNIDADE 01/{NOME}"]["tentativas"]
    assert tent == {"código:reler": 1, "código:reler_carimbo": 1}
    assert r["lotes"] == {"Haiku": 1}
    assert _lote(out, "Haiku")[0]["faltando"] == ["carimbo.escala"]
    assert _lote(out, "Haiku")[0]["retorno"] == [c for c in extracao.FONTES["classes"] if c["id"] == "projeto"][0]["retorno"]


def test_reler_carimbo_com_sucesso_completa(tmp_path, monkeypatch):
    cfg, pasta, out = _obra(tmp_path, [("UNIDADE 01", NOME, "abc")])
    _prancha(pasta / "UNIDADE 01" / NOME, escala=False)
    monkeypatch.setattr(inventario, "reler_carimbo", lambda caminho, dpi=300: {"escala": "1:100", "folha": None,
                                                                              "fonte": "OCR 300 dpi"})
    r = escada.executar(cfg, out, voltas=5)
    assert r["por_estado"] == {"completa": 1} and r["lotes"] == {}


def test_sem_leitor_vai_direto_ao_sonnet_com_retorno(tmp_path):
    cfg, pasta, out = _obra(tmp_path, [("MEMORIAIS", "Memorial descritivo.docx", "m1")])
    (pasta / "MEMORIAIS").mkdir()
    (pasta / "MEMORIAIS" / "Memorial descritivo.docx").write_bytes(b"PK")
    r = escada.executar(cfg, out)
    assert r["voltas"] == 0 and r["lotes"] == {"Sonnet": 1}
    linha = _lote(out, "Sonnet")[0]
    assert (linha["arquivo"], linha["classe"], linha["situacao"]) == ("Memorial descritivo.docx", "memorial", "sem leitor")
    assert linha["retorno"] == [c for c in extracao.FONTES["classes"] if c["id"] == "memorial"][0]["retorno"] and linha["retorno"]
    assert linha["caminho"].endswith("Memorial descritivo.docx")
    (pasta / "MEMORIAIS" / "Memorial descritivo.docx").unlink()          # lote é regravado: o que sumiu não fica
    escada.lotes(out, [], {})
    assert _lote(out, "Sonnet") == []


def test_zip_extraido_vira_itens_filhos(tmp_path):
    cfg, pasta, out = _obra(tmp_path, [("UNIDADE 01", "formas.zip", "z1")])
    _prancha(tmp_path / "ext" / NOME)
    (pasta / "UNIDADE 01").mkdir()
    with zipfile.ZipFile(pasta / "UNIDADE 01" / "formas.zip", "w") as z:
        z.write(tmp_path / "ext" / NOME, NOME)
    r = escada.executar(cfg, out)
    filhos = [i for i in r["inventario"]["itens"] if i["situacao"] == "no disco (dentro do zip)"]
    assert [(f["arquivo"], f["pasta_drive"], f["leitor"]) for f in filhos] == [(NOME, "UNIDADE 01/formas.zip!", "ler_pdf")]
    assert (pasta / "_zip" / "formas.zip" / NOME).exists()
    por_arquivo = {a["arquivo"]: a for a in r["pendencias"]["avaliacoes"]}
    assert por_arquivo[NOME]["estado"] == "completa" and por_arquivo["formas.zip"]["estado"] == "completa"
    assert r["lotes"] == {}


def test_max_tentativas_impede_loop_e_sobe_para_voce(tmp_path):
    cfg, pasta, out = _obra(tmp_path, [("UNIDADE 01", NOME, "abc"), ("UNIDADE 01", "planta.dwg", "d1")])
    chamadas = []

    def baixar(file_id, destino, tamanho=None):
        chamadas.append(file_id)
        return {"ok": False, "bytes": 0, "motivo": "privado"}

    r = escada.executar(cfg, out, voltas=10, baixar=baixar)
    assert chamadas == ["abc", "abc"]                                   # 2 tentativas e para; .dwg nem chama o drive
    tent = extracao.ler_complementos(out / "complementos.json")
    assert tent[f"UNIDADE 01/{NOME}"]["tentativas"] == {"código:baixar": 2}
    assert tent["UNIDADE 01/planta.dwg"]["tentativas"] == {"código:baixar": 2}
    assert r["voltas"] == 2 and r["lotes"] == {"você": 2}
    assert {l["arquivo"] for l in _lote(out, "você")} == {NOME, "planta.dwg"}


def test_proximo_degrau_pelas_tentativas():
    av = {"situacao": "carimbo incompleto"}
    assert escada.proximo_degrau(av, None) == {"executor": "código", "funcao": "reler", "max_tentativas": 1}
    assert escada.proximo_degrau(av, {"tentativas": {"código:reler": 1}})["funcao"] == "reler_carimbo"
    assert escada.proximo_degrau(av, {"tentativas": {"código:reler": 1, "código:reler_carimbo": 1}})["executor"] == "Haiku"
    tudo = {"código:reler": 1, "código:reler_carimbo": 1, "Haiku:None": 1, "Sonnet:None": 1}
    assert escada.proximo_degrau(av, {"tentativas": tudo}) is None
    assert escada.proximo_degrau({"situacao": None}, None) is None
    assert escada.metadados()["modulo"] == "escada"


def test_ciclo_completo_lote_da_ia_volta_e_fecha(tmp_path):
    """Integração E4 + E5: o arquivo sem leitor vai para o lote do Sonnet; o Sonnet devolve o retorno; a volta
    seguinte aplica, o item fecha, o lote some e o registro diz quem resolveu."""
    cfg, pasta, out = _obra(tmp_path, [("MEMORIAIS", "Memorial descritivo.docx", "m1")])
    (pasta / "MEMORIAIS").mkdir()
    (pasta / "MEMORIAIS" / "Memorial descritivo.docx").write_bytes(b"PK")
    assert escada.executar(cfg, out)["lotes"] == {"Sonnet": 1}
    (out / "retornos").mkdir()
    (out / "retornos" / "sonnet.jsonl").write_text(json.dumps(
        {"arquivo": "Memorial descritivo.docx", "pasta_drive": "MEMORIAIS", "executor": "Sonnet",
         "campos": {"texto": "Memorial das obras civis da ETA."}, "citacao": {"pagina": 1, "trecho": "Memorial"}},
        ensure_ascii=False) + "\n", encoding="utf-8")
    r = escada.executar(cfg, out)
    assert r["lotes"] == {} and r["por_estado"] == {"completa": 1}
    ultima = json.loads((out / "extracao.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert (ultima["estado"], ultima["executor"]) == ("completa", "Sonnet")
