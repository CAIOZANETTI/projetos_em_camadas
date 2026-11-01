"""O conjunto de referência deve ser determinístico."""

from camadas.referencia import calcular_resultados, hash_resultados


def test_hash_estavel_em_duas_chamadas():
    assert hash_resultados(calcular_resultados()) == hash_resultados(calcular_resultados())
