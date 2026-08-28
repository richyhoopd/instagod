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


def test_generar_guion_n_slides_arriba_de_10_no_llama_llm(monkeypatch) -> None:
    monkeypatch.setattr(ss, "_llamar_llm",
                        lambda prompt: (_ for _ in ()).throw(AssertionError("no debió llamarse")))
    with pytest.raises(ValueError):
        ss.generar_guion("x", n_slides=11)


def test_generar_guion_n_slides_cero_no_llama_llm(monkeypatch) -> None:
    monkeypatch.setattr(ss, "_llamar_llm",
                        lambda prompt: (_ for _ in ()).throw(AssertionError("no debió llamarse")))
    with pytest.raises(ValueError):
        ss.generar_guion("x", n_slides=0)


# --- Tolerancia n±1 (fix del bug de prod 2026-08-28) ---


def _slides_n(n):
    """n slides válidos: hook + puntos + cta."""
    mids = [{"text": f"punto {i}", "rol": "punto", "image_hint": "gig photo"}
            for i in range(n - 2)]
    return ([{"text": "el hook", "rol": "hook", "image_hint": "band stage"}]
            + mids
            + [{"text": "sígueme", "rol": "cta", "image_hint": "crowd"}])


def _guion_n(n):
    return {"tema": "t", "hook": "h", "caption": "c", "cta": "x",
            "slides": _slides_n(n)}


def test_validar_tolera_un_slide_de_mas() -> None:
    assert ss.validar_guion(_guion_n(7), n_slides=6) == []


def test_validar_tolera_un_slide_de_menos() -> None:
    assert ss.validar_guion(_guion_n(5), n_slides=6) == []


def test_validar_rechaza_dos_de_mas() -> None:
    errores = ss.validar_guion(_guion_n(8), n_slides=6)
    assert any("±1" in e for e in errores)


def test_recortar_slide_extra_quita_un_punto_no_el_cta() -> None:
    recortados = ss.recortar_slide_extra(_slides_n(7))
    assert len(recortados) == 6
    assert recortados[0]["rol"] == "hook"
    assert recortados[-1]["rol"] == "cta"


def test_recortar_sin_puntos_no_rompe() -> None:
    slides = [{"text": "h", "rol": "hook", "image_hint": "x"},
              {"text": "c", "rol": "cta", "image_hint": "x"}]
    assert ss.recortar_slide_extra(slides) == slides


def test_generar_guion_recorta_cuando_llegan_de_mas(monkeypatch) -> None:
    monkeypatch.setattr(ss, "_llamar_llm", lambda *a, **k: json.dumps(_guion_n(7)))
    guion = ss.generar_guion("tema", n_slides=6)
    assert len(guion["slides"]) == 6
    assert guion["slides"][-1]["rol"] == "cta"


def test_generar_guion_acepta_uno_de_menos(monkeypatch) -> None:
    monkeypatch.setattr(ss, "_llamar_llm", lambda *a, **k: json.dumps(_guion_n(5)))
    guion = ss.generar_guion("tema", n_slides=6)
    assert len(guion["slides"]) == 5
