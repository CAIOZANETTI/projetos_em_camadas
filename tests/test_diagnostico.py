import numpy as np
import pytest

from camadas import diagnostico


def test_layers_em_volta_conta_e_desenha(tmp_path):
    tr = [{"layer": "SJMH_ADUTORA_TUBO", "partes": [np.array([[0, 0], [100, 0.0]])]},
          {"layer": "SJMH_ADUTORA_DIVISAS", "partes": [np.array([[0, 10], [100, 10.0]]), np.array([[0, -30], [100, -30.0]])]},
          {"layer": "LONGE", "partes": [np.array([[5000, 0], [5100, 0.0]])]}]
    M = np.array([[0.1, 0, 1000.0], [0, 0.1, 2000.0], [0, 0, 1]])
    cont = diagnostico.layers_em_volta(tr, M, (1005.0, 2000.0), 8.0, tmp_path / "l.png", res=0.05)
    assert cont == {"SJMH_ADUTORA_TUBO": 1, "SJMH_ADUTORA_DIVISAS": 2} and (tmp_path / "l.png").exists()


def test_sobrepor_e_recorte(tmp_path):
    pymupdf = pytest.importorskip("pymupdf")
    a = [np.array([[0.0, 0], [10, 0]])]
    p = diagnostico.sobrepor([(a, (255, 0, 0), 2), ([q + [0, 1] for q in a], (0, 0, 255))], (5.0, 0.0), 6.0, tmp_path / "s.png", res=0.05)
    import cv2
    img = cv2.imread(str(p))
    assert img.shape[:2] == (240, 240) and (img[:, :, 2] > 200).sum() > 0
    doc = pymupdf.open()
    doc.new_page(width=200, height=100).draw_line((10, 10), (190, 90))
    doc.save(tmp_path / "f.pdf")
    assert diagnostico.recorte(tmp_path / "f.pdf", (0, 0, 100, 50), tmp_path / "r.png", 72).exists()
