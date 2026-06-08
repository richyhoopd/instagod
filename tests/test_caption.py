"""Constructor del prompt de captions (el 70% del valor del proyecto).

_build_user_prompt es PURO: arma el mensaje de usuario según qué datos hay y el
TIPO de actor, sin tocar la API. Aquí se blinda que: (a) nunca se "inventan"
datos ausentes, (b) cada tipo redefine al sujeto correctamente, (c) rechazados y
feedback se inyectan. generate_caption se prueba con el cliente LLM mockeado.
"""
from __future__ import annotations

import config
from src import caption
from src.caption import _build_user_prompt, _clean, generate_caption

# ---------- _clean ----------

def test_clean_normaliza_vacios_a_none() -> None:
    assert _clean(None) is None
    assert _clean("   ") is None
    assert _clean("") is None
    assert _clean("  Kabala  ") == "Kabala"


# ---------- _build_user_prompt: banda ----------

def test_prompt_banda_completa_no_pide_inventar() -> None:
    p = _build_user_prompt("Kabala", "Cesar", "guitarrista", None, None)
    assert "- Banda: Kabala" in p
    assert "- Integrante: Cesar" in p
    assert "- Rol: guitarrista" in p
    assert "Datos AUSENTES" not in p          # nada falta → no se pide compensar


def test_prompt_banda_sin_integrante_marca_ausentes() -> None:
    p = _build_user_prompt("Kabala", None, None, None, None)
    assert "- Banda: Kabala" in p
    assert "Datos AUSENTES" in p
    assert "integrante" in p and "rol" in p   # lista lo que falta para NO inventarlo


def test_prompt_tema_libre_cuando_no_hay_semilla() -> None:
    assert "Tema: libre" in _build_user_prompt("Kabala", None, None, None, None)


def test_prompt_usa_tema_semilla_como_pista() -> None:
    p = _build_user_prompt("Kabala", None, None, "microondas", None)
    assert "Pista de tema" in p and "microondas" in p
    assert "Tema: libre" not in p


def test_prompt_inyecta_rechazados() -> None:
    p = _build_user_prompt("Kabala", None, None, None, ["titular viejo 1", "titular viejo 2"])
    assert "RECHAZAD" in p
    assert "titular viejo 1" in p and "titular viejo 2" in p


def test_prompt_inyecta_feedback() -> None:
    p = _build_user_prompt("Kabala", None, None, None, None, feedback="más corto")
    assert "RETROALIMENTACIÓN" in p and "más corto" in p


# ---------- _build_user_prompt: tipos no-banda redefinen al sujeto ----------

def test_prompt_foro_inyecta_guia_y_no_pide_integrante() -> None:
    p = _build_user_prompt("Foro Independencia", None, None, None, None, tipo="foro")
    assert "TIPO DE SUJETO: FORO" in p          # guía específica del tipo
    assert "- Foro: Foro Independencia" in p    # etiqueta correcta del sujeto
    assert "Integrante" not in p                # un foro no tiene integrantes
    assert "Datos AUSENTES" not in p


def test_prompt_solista_conserva_integrante_y_etiqueta() -> None:
    p = _build_user_prompt("Paulina", "Paulina", None, None, None, tipo="solista")
    assert "TIPO DE SUJETO: SOLISTA" in p
    assert "- Solista: Paulina" in p


def test_prompt_evento_y_colectivo_inyectan_su_guia() -> None:
    assert "TIPO DE SUJETO: EVENTO" in _build_user_prompt("CañaFest", None, None, None, None, tipo="evento")
    assert "TIPO DE SUJETO: COLECTIVO" in _build_user_prompt("Sello X", None, None, None, None, tipo="colectivo")


# ---------- generate_caption: ruteo + limpieza, sin llamar a la API real ----------

def test_generate_caption_rutea_deepseek_y_limpia_comillas(monkeypatch) -> None:
    capturado = {}

    def fake(user_prompt, temperature):
        capturado["prompt"] = user_prompt
        capturado["temp"] = temperature
        return '  "Los Flakos exigen una disculpa formal."  '

    monkeypatch.setattr(config, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(caption, "_via_deepseek", fake)
    out = generate_caption("Los Flakos")
    assert out == "Los Flakos exigen una disculpa formal."   # sin comillas ni espacios
    assert "- Banda: Los Flakos" in capturado["prompt"]
    assert capturado["temp"] == config.CAPTION_TEMPERATURE   # usa el default de config


def test_generate_caption_rutea_claude_cuando_provider_claude(monkeypatch) -> None:
    monkeypatch.setattr(config, "LLM_PROVIDER", "claude")
    monkeypatch.setattr(caption, "_via_anthropic", lambda p, t: "Reporte: todo bien.")
    monkeypatch.setattr(caption, "_via_deepseek", lambda p, t: pytest_fail())
    assert generate_caption("Kabala") == "Reporte: todo bien."


def test_generate_caption_tipo_invalido_cae_a_banda(monkeypatch) -> None:
    capturado = {}
    monkeypatch.setattr(config, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(caption, "_via_deepseek",
                        lambda p, t: capturado.update(prompt=p) or "ok")
    generate_caption("Kabala", tipo="marciano")
    assert "- Banda: Kabala" in capturado["prompt"]   # etiqueta de fallback


def pytest_fail():  # ayuda: si se llama la rama equivocada, revienta el test
    raise AssertionError("no debió rutear a deepseek con LLM_PROVIDER=claude")
