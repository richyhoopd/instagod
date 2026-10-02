"""Filtros Jinja2 de plantillas: `resaltar` y el entorno de validación.

Sin DB, sin Playwright real (solo se importa `compose` para comparar HTML).
"""
from __future__ import annotations

import pytest
from markupsafe import Markup

from src import compose
from src.plantillas import contrato as c
from src.plantillas import filtros


def _contrato_minimo() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


@pytest.mark.parametrize("texto", [
    "Los Ejemplo tocan hoy en el Foro X",
    "¡Nuevo sencillo de la banda!",
    "Boletos disponibles para el evento del sábado",
])
def test_resaltar_coincide_con_onion_html_de_compose(texto: str) -> None:
    assert str(filtros.resaltar(texto)) == compose._onion_html(texto)


def test_resaltar_devuelve_markup_y_jinja_no_lo_reescapa() -> None:
    resultado = filtros.resaltar("Los Ejemplo tocan hoy")
    assert isinstance(resultado, Markup)
    env = filtros.entorno()
    render = env.from_string("{{ titular | resaltar }}").render(titular="Los Ejemplo")
    assert "&lt;span" not in render
    assert "<span" in render


def test_entorno_registra_resaltar() -> None:
    assert "resaltar" in filtros.entorno().filters


def test_validar_html_acepta_el_filtro_resaltar() -> None:
    ct = _contrato_minimo()
    c.validar_html("<div class='card'>{{ titular | resaltar }}</div>", ct)


def test_validar_html_rechaza_un_filtro_inventado() -> None:
    ct = _contrato_minimo()
    with pytest.raises(c.ContratoInvalido):
        c.validar_html("<div class='card'>{{ titular | noexiste }}</div>", ct)
