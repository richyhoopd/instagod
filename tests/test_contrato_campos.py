"""Validación de los VALORES contra el contrato. Sin DB, sin red."""
from __future__ import annotations

from src.plantillas import contrato as c


def _ct(extras=None) -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}


def test_campos_minimos_validos() -> None:
    assert c.validar_campos({"titular": "Hola"}, _ct()) == []


def test_titular_vacio() -> None:
    errs = c.validar_campos({"titular": "   "}, _ct())
    assert errs and "titular" in errs[0]


def test_titular_ausente() -> None:
    errs = c.validar_campos({}, _ct())
    assert errs and "titular" in errs[0]


def test_lista_con_cantidad_incorrecta() -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    errs = c.validar_campos({"titular": "x", "pasos": ["a", "b"]}, ct)
    assert errs and "pasos" in errs[0]


def test_lista_correcta() -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    assert c.validar_campos({"titular": "x", "pasos": ["a", "b", "c"]}, ct) == []


def test_extra_opcional_puede_faltar() -> None:
    ct = _ct([{"id": "badge", "tipo": "texto", "opcional": True}])
    assert c.validar_campos({"titular": "x"}, ct) == []


def test_extra_obligatorio_no_puede_faltar() -> None:
    ct = _ct([{"id": "badge", "tipo": "texto"}])
    errs = c.validar_campos({"titular": "x"}, ct)
    assert errs and "badge" in errs[0]


def test_numero_como_texto_es_error() -> None:
    ct = _ct([{"id": "precio", "tipo": "numero"}])
    errs = c.validar_campos({"titular": "x", "precio": "1200"}, ct)
    assert errs and "precio" in errs[0]


def test_numero_correcto() -> None:
    ct = _ct([{"id": "precio", "tipo": "numero"}])
    assert c.validar_campos({"titular": "x", "precio": 1200}, ct) == []


def test_campo_desconocido() -> None:
    errs = c.validar_campos({"titular": "x", "inventado": "y"}, _ct())
    assert errs and "inventado" in errs[0]


def test_acumula_todos_los_errores() -> None:
    """El LLM se autocorrige con la lista completa, no de uno en uno."""
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3},
              {"id": "badge", "tipo": "texto"}])
    errs = c.validar_campos({"pasos": []}, ct)
    assert len(errs) == 3  # titular ausente, pasos corta, badge ausente


def test_contrato_de_json_valido() -> None:
    assert c.contrato_de_json('{"aspecto": "4:5"}') == {"aspecto": "4:5"}


def test_contrato_de_json_roto() -> None:
    assert c.contrato_de_json("{esto no es json") == {}


def test_contrato_de_json_none() -> None:
    assert c.contrato_de_json(None) == {}


def test_contrato_de_json_lista() -> None:
    assert c.contrato_de_json("[1, 2, 3]") == {}
