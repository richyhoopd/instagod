"""Generación de campos por contrato. El LLM va mockeado: cero red."""
from __future__ import annotations

import json

import pytest

from src.plantillas import contrato as c
from src.plantillas import generador as g


class _MarcaFalsa:
    id = 1
    slug = "tips"
    nombre = "Cuenta de Tips"
    ig_handle = "tips"
    voz = "Tono cercano, directo, sin tecnicismos."
    prompts = {"caption_extra": "Nunca prometas resultados médicos.", "por_formato": {}}


def _ct(extras=None) -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}


def test_describir_contrato_menciona_cada_extra() -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3,
               "desc": "Tres pasos accionables"}])
    txt = g.describir_contrato(ct)
    assert "titular" in txt and "pasos" in txt
    assert "3" in txt and "Tres pasos accionables" in txt


def test_extraer_campos_tolera_fences() -> None:
    assert g.extraer_campos('```json\n{"titular": "Hola"}\n```') == {"titular": "Hola"}


def test_extraer_campos_devuelve_none_si_no_hay_json() -> None:
    assert g.extraer_campos("lo siento, no puedo") is None


def test_generar_campos_feliz(monkeypatch) -> None:
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: json.dumps({"titular": "Tres trucos"}))
    out = g.generar_campos(_ct(), marca=_MarcaFalsa(), tema="ahorro")
    assert out == {"titular": "Tres trucos"}


def test_generar_campos_reintenta_con_los_errores(monkeypatch) -> None:
    """El 1er intento devuelve una lista corta; el 2o corrige. El prompt del
    2o intento tiene que mencionar el error del 1o."""
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    prompts: list[str] = []
    respuestas = [json.dumps({"titular": "x", "pasos": ["a"]}),
                  json.dumps({"titular": "x", "pasos": ["a", "b", "c"]})]

    def fake(prompt, **kw):
        prompts.append(prompt)
        return respuestas[len(prompts) - 1]

    monkeypatch.setattr(g, "_pedir_al_llm", fake)
    out = g.generar_campos(ct, marca=_MarcaFalsa(), tema="ahorro")
    assert out["pasos"] == ["a", "b", "c"]
    assert len(prompts) == 2
    assert "pasos" in prompts[1]


def test_generar_campos_se_rinde_tras_los_intentos(monkeypatch) -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: json.dumps({"titular": "x", "pasos": []}))
    with pytest.raises(RuntimeError, match="pasos"):
        g.generar_campos(ct, marca=_MarcaFalsa(), tema="ahorro")


def test_el_prompt_lleva_la_voz_de_la_marca(monkeypatch) -> None:
    capturado: list[str] = []
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: capturado.append(prompt)
                        or json.dumps({"titular": "ok"}))
    g.generar_campos(_ct(), marca=_MarcaFalsa(), tema="ahorro")
    assert "Tono cercano" in capturado[0]
    assert "Nunca prometas" in capturado[0]


def test_no_hereda_el_prompt_de_gdlscene(monkeypatch) -> None:
    """Regresión: una marca de tips no debe recibir el prompt de la escena."""
    capturado: list[str] = []
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: capturado.append(prompt)
                        or json.dumps({"titular": "ok"}))
    g.generar_campos(_ct(), marca=_MarcaFalsa(), tema="ahorro")
    bajo = capturado[0].lower()
    assert "gdlscene" not in bajo and "guadalajara" not in bajo
