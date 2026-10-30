import csv
import io

from camadas import drive


def _listagem(tmp_path, linhas):
    arq = tmp_path / "lista.csv"
    with open(arq, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["caminho", "titulo", "id", "mimeType", "extensao", "tamanho_bytes", "modificado"])
        w.writerows(linhas)
    return arq


def test_pendentes_e_so_o_que_falta(tmp_path):
    (tmp_path / "proj" / "A").mkdir(parents=True)
    (tmp_path / "proj" / "A" / "ja.pdf").write_bytes(b"%PDF")
    arq = _listagem(tmp_path, [["A", "ja.pdf", "1", "", "pdf", "4", ""], ["A/PBES", "forma.PDF", "2", "", "PDF", "9", ""],
                               ["A", "planilha.xlsx", "3", "", "xlsx", "5", ""]])
    assert [r["titulo"] for r in drive.pendentes(arq, tmp_path / "proj")] == ["forma.PDF"]
    assert drive.pendentes(arq, tmp_path / "proj", filtro="ARMADURA") == []


def test_baixar_recusa_o_que_nao_e_pdf(tmp_path, monkeypatch):
    """Arquivo privado: o link devolve a página de login (HTML) — não grava e diz o motivo."""
    monkeypatch.setattr(drive.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"<html>login</html>"))
    r = drive.baixar("x", tmp_path / "a.pdf")
    assert not r["ok"] and "privado" in r["motivo"] and not (tmp_path / "a.pdf").exists()
    monkeypatch.setattr(drive.urllib.request, "urlopen", lambda url, timeout: io.BytesIO(b"%PDF-1.5 ok"))
    assert not drive.baixar("x", tmp_path / "a.pdf", tamanho=999)["ok"]                    # cortado no meio
    assert drive.baixar("x", tmp_path / "b" / "a.pdf", tamanho=11)["ok"] and (tmp_path / "b" / "a.pdf").exists()
