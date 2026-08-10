"""Guion semántico del LLM: extracción, validación y loop de reintentos."""
from __future__ import annotations

import json

import pytest

from src import slideshow_script as ss


def _guion_ok(n=3):
    slides = [{"text": "Gancho", "rol": "hook", "image_hint": "city night"}]
    for i in range(n - 2):
        slides.append({"text": f"Punto {i}", "rol": "punto", "image_hint": "coffee"})
    slides.append({"text": "Sígueme", "rol": "cta", "image_hint": "neon sign"})
    return {"tema": "café", "hook": "Gancho", "caption": "pie", "cta": "Sígueme",
            "slides": slides}


def test_extraer_guion_tolera_fences() -> None:
    texto = "```json\n" + json.dumps(_guion_ok()) + "\n```"
    assert ss.extraer_guion(texto) == _guion_ok()


def test_extraer_guion_rechaza_array_raiz() -> None:
    assert ss.extraer_guion(json.dumps([1, 2])) is None


def test_extraer_guion_rechaza_no_json() -> None:
    assert ss.extraer_guion("no hay json aquí") is None


def test_validar_guion_ok() -> None:
    assert ss.validar_guion(_guion_ok(), n_slides=3) == []


def test_validar_guion_sin_claves() -> None:
    assert ss.validar_guion({"tema": "x"}, n_slides=3)


def test_validar_guion_primer_slide_debe_ser_hook() -> None:
    g = _guion_ok()
    g["slides"][0]["rol"] = "punto"
    assert any("hook" in e for e in ss.validar_guion(g, n_slides=3))


def test_validar_guion_ultimo_slide_debe_ser_cta() -> None:
    g = _guion_ok()
    g["slides"][-1]["rol"] = "punto"
    assert any("cta" in e for e in ss.validar_guion(g, n_slides=3))


def test_validar_guion_rol_desconocido() -> None:
    g = _guion_ok()
    g["slides"][1]["rol"] = "outro"
    assert ss.validar_guion(g, n_slides=3)


def test_validar_guion_slide_sin_image_hint() -> None:
    g = _guion_ok()
    g["slides"][1]["image_hint"] = ""
    assert ss.validar_guion(g, n_slides=3)


def test_validar_guion_numero_de_slides_equivocado() -> None:
    g = _guion_ok(n=3)
    assert any("slides" in e and "pidieron" in e for e in ss.validar_guion(g, n_slides=5))


def test_generar_guion_reintenta_y_devuelve(monkeypatch) -> None:
    """1er intento: basura; 2o: guion válido → lo devuelve sin agotar intentos."""
    respuestas = iter(["esto no es json", json.dumps(_guion_ok())])
    monkeypatch.setattr(ss, "_llamar_llm", lambda prompt: next(respuestas))
    g = ss.generar_guion("café", formato="listicle", n_slides=3)
    assert g["hook"] == "Gancho"


def test_generar_guion_agota_intentos(monkeypatch) -> None:
    monkeypatch.setattr(ss, "_llamar_llm", lambda prompt: "nunca es json")
    with pytest.raises(RuntimeError):
        ss.generar_guion("café", n_slides=3)


def test_generar_guion_formato_desconocido() -> None:
    with pytest.raises(ValueError):
        ss.generar_guion("café", formato="inexistente")
