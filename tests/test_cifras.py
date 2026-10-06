"""Validación de cifras contra facts y menciones de unverified (PURO)."""
from __future__ import annotations

import pytest

from src import cifras
from tests.fixtures.feed_mwrs import item

FACTS = item()["facts"]  # precio "$1,450,000 MXN", m2 300, regimen "ejidal"


@pytest.mark.parametrize("texto", ["3,000,000", "3'000,000", "3.000.000",
                                   "3 millones", "3 mdp", "3M", "3000000"])
def test_formatos_equivalentes(texto):
    assert cifras.numeros(texto) == [3000000.0]


def test_ruido_no_cuenta():
    assert cifras.numeros("1,200 m2 en melaquecapital.com/lote-3 @mwrs2") == [1200.0]


def test_cifras_dentro_de_facts_pasan_en_cualquier_formato():
    textos = ["Precio: 1.45 millones de pesos", "$1,450,000 MXN", "300 m²"]
    assert cifras.cifras_fuera(textos, FACTS) == []


def test_cifra_inventada_se_reporta():
    assert cifras.cifras_fuera(["A 5 minutos de la playa, 300 m2"], FACTS) == ["5"]


def test_enumerador_de_slide_se_ignora():
    guion = {"hook": "Lote", "slides": [{"text": "2. Mide 300 m2", "image_hint": "a 7"}]}
    assert cifras.cifras_fuera(cifras.textos_de_guion(guion), FACTS) == []


def test_facts_recursivos():
    assert cifras.numeros_de_facts({"a": {"b": ["10 mil", 2.5]}, "x": True}) == {10000.0, 2.5}


def test_unverified_por_clave_o_valor():
    assert cifras.menciones_no_verificadas(["Régimen claro"], FACTS, ["regimen"]) == ["regimen"]
    assert cifras.menciones_no_verificadas(["Es EJIDAL"], FACTS, ["regimen"]) == ["regimen"]
    assert cifras.menciones_no_verificadas(["Lote esquina"], FACTS, ["regimen"]) == []
    assert cifras.menciones_no_verificadas(["escritura lista"], {}, ["escritura"]) == ["escritura"]
