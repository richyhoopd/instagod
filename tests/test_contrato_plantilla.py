"""Validación del contrato de plantilla. Sin DB, sin red, sin Chromium."""
from __future__ import annotations

import pytest

from src.plantillas import contrato as c


def _contrato_minimo() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


def test_contrato_minimo_es_valido() -> None:
    c.validar(_contrato_minimo())


def test_falta_un_campo_base() -> None:
    malo = _contrato_minimo()
    malo["base"] = ["titular", "imagen"]
    with pytest.raises(c.ContratoInvalido, match="base"):
        c.validar(malo)


def test_aspecto_desconocido() -> None:
    malo = _contrato_minimo()
    malo["aspecto"] = "16:9"
    with pytest.raises(c.ContratoInvalido, match="aspecto"):
        c.validar(malo)


def test_tipo_de_extra_desconocido() -> None:
    malo = _contrato_minimo()
    malo["extras"] = [{"id": "x", "tipo": "video"}]
    with pytest.raises(c.ContratoInvalido, match="tipo"):
        c.validar(malo)


def test_extra_que_pisa_un_campo_base() -> None:
    malo = _contrato_minimo()
    malo["extras"] = [{"id": "titular", "tipo": "texto"}]
    with pytest.raises(c.ContratoInvalido, match="titular"):
        c.validar(malo)


def test_lista_con_min_mayor_que_max() -> None:
    malo = _contrato_minimo()
    malo["extras"] = [{"id": "pasos", "tipo": "lista", "min": 5, "max": 3}]
    with pytest.raises(c.ContratoInvalido, match="min"):
        c.validar(malo)


def test_variables_declaradas_incluye_base_y_extras() -> None:
    ct = _contrato_minimo()
    ct["extras"] = [{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}]
    assert c.variables_declaradas(ct) == set(c.CAMPOS_BASE) | {"pasos"}


def test_html_con_variable_no_declarada() -> None:
    ct = _contrato_minimo()
    html = "<div class='card'>{{ titular }} {{ inventada }}</div>"
    with pytest.raises(c.ContratoInvalido, match="inventada"):
        c.validar_html(html, ct)


def test_html_puede_usar_variables_de_sistema() -> None:
    ct = _contrato_minimo()
    c.validar_html(
        "<div class='card'>{{ titular }}<img src='{{ fonts_dir }}/a.ttf'></div>", ct)


def test_html_roto_de_jinja() -> None:
    ct = _contrato_minimo()
    with pytest.raises(c.ContratoInvalido, match="Jinja"):
        c.validar_html("<div class='card'>{{ titular </div>", ct)


def test_html_sin_card_se_rechaza() -> None:
    ct = _contrato_minimo()
    html = "<html><body><div class='otra'>{{ titular }}</div></body></html>"
    with pytest.raises(c.ContratoInvalido, match="marco"):
        c.validar_html(html, ct)


def test_html_con_card_y_otras_clases_se_acepta() -> None:
    """`page.locator(".card")` encuentra `class="foo card"` igual que
    `class="card"` a secas; el validador no debe exigir el valor exacto."""
    ct = _contrato_minimo()
    c.validar_html("<div class=\"marco card\">{{ titular }}</div>", ct)


def test_dimensiones() -> None:
    assert c.dimensiones("4:5") == (1080, 1350)
    assert c.dimensiones("9:16") == (1080, 1920)


def test_html_con_card_como_prefijo_se_rechaza() -> None:
    """`class="card-top"` no lo encuentra `page.locator(".card")`: si pasara,
    el render devolvería un PNG vacío en silencio."""
    ct = _contrato_minimo()
    with pytest.raises(c.ContratoInvalido, match="marco"):
        c.validar_html('<div class="card-top">{{ titular }}</div>', ct)


def test_assets_dir_es_variable_de_sistema() -> None:
    """La biblioteca de la marca se pide como {{ assets_dir }}/<archivo>."""
    c.validar_html(
        "<html><body><div class='card' "
        "style=\"background:url('{{ assets_dir }}/a.png')\"></div></body></html>",
        _contrato_minimo())
