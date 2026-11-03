"""Número colado a letra ou hífen (DN150, C30, CA-50) não é quantidade no método regex."""

import pytest

from camadas.vocabulario import normalizar, quantidade

TERMOS = ["ESTACA", "ESCAVACAO"]


@pytest.mark.parametrize(
    "linha, esperado",
    [
        ("Tubo PVC DN150 m 320", (None, None)),
        ("Concreto C30 m³ 45", (None, None)),
        ("Armação aço CA-50 kg 1.200", (None, None)),
        ("Armação aço CA50 kg 1.200", (None, None)),
        ("Concreto fck 30 MPa 45 m³", (45.0, "m³")),
        ("Tubo DN 150 320 m", (320.0, "m")),
        ("Tubo Ø 40 cm 12 m", (12.0, "m")),
        ("Escavação 120 m³", (120.0, "m³")),
        ("250 estacas", (250.0, "un")),
        ("Escavação (120 m³)", (120.0, "m³")),
        ("Volume: 120 m³", (120.0, "m³")),
    ],
)
def test_quantidade_ignora_numero_colado(linha, esperado):
    assert quantidade(normalizar(linha), TERMOS) == esperado
