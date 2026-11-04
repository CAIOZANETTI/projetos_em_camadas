import importlib.util
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("golden_quantidades", RAIZ / "scripts" / "golden_quantidades.py")
golden = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(golden)

GOLDEN = RAIZ / "tests" / "golden_foz" / "quantidades_foz.json"
DADOS_FOZ = Path.cwd() / "saida" / "foz" / "dados.json"


def _resumo_sintetico():
    return {
        "escavacao": {"total": {"escavacao_m3": 10.0, "reaterro_m3": 4.0}, "cavas": {"C01": {"escavacao_m3": 10.0}}},
        "contagem": 3,
        "situacao": "calculada",
    }


def test_comparar_igual_nao_tem_diferenca():
    atual = _resumo_sintetico()
    assert golden.comparar(_resumo_sintetico(), atual) == []


def test_comparar_numero_dentro_da_tolerancia_passa():
    atual = _resumo_sintetico()
    atual["escavacao"]["total"]["escavacao_m3"] = 10.0005
    assert golden.comparar(_resumo_sintetico(), atual, tol_abs=1e-3) == []


def test_comparar_numero_fora_da_tolerancia_aponta_o_caminho():
    atual = _resumo_sintetico()
    atual["escavacao"]["total"]["escavacao_m3"] = 10.01
    diferencas = golden.comparar(_resumo_sintetico(), atual, tol_abs=1e-3)
    assert len(diferencas) == 1
    assert "número fora da tolerância" in diferencas[0]
    assert "/escavacao/total/escavacao_m3" in diferencas[0]


def test_comparar_chave_a_mais_e_a_menos():
    esperado = _resumo_sintetico()
    atual = _resumo_sintetico()
    del atual["contagem"]
    atual["nova"] = 1
    diferencas = golden.comparar(esperado, atual)
    assert any(d.startswith("chave ausente") and "/contagem" in d for d in diferencas)
    assert any(d.startswith("chave a mais") and "/nova" in d for d in diferencas)


def test_comparar_texto_diferente():
    atual = _resumo_sintetico()
    atual["situacao"] = "declarada"
    diferencas = golden.comparar(_resumo_sintetico(), atual)
    assert len(diferencas) == 1
    assert "texto ou tipo diferente" in diferencas[0]


def test_comparar_lista_com_tamanho_diferente():
    diferencas = golden.comparar({"a": [1, 2]}, {"a": [1]})
    assert diferencas and "tamanho da lista" in diferencas[0]


def test_golden_nao_tem_texto_de_preco():
    texto = GOLDEN.read_text(encoding="utf-8")
    for proibido in ("R$", "preço", "valor_unit"):
        assert proibido not in texto


@pytest.mark.skipif(not DADOS_FOZ.exists(), reason="saida/foz/dados.json ausente neste repositório")
def test_build_de_foz_bate_com_o_golden():
    dados = json.loads(DADOS_FOZ.read_text(encoding="utf-8"))
    esperado = json.loads(GOLDEN.read_text(encoding="utf-8"))
    diferencas = golden.comparar(esperado, golden.extrair(dados))
    assert diferencas == [], "\n".join(diferencas)
