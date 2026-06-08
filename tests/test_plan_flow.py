"""Tests del flujo de plan: prompt con feedback y regenerate con texto/feedback."""
from __future__ import annotations

from src.caption import _build_user_prompt


def test_prompt_incluye_feedback() -> None:
    p = _build_user_prompt("Kabala", "Cesar", "guitarrista", None, None, "banda",
                           "hazlo más corto y sobre comida")
    assert "RETROALIMENTACIÓN del editor" in p
    assert "hazlo más corto y sobre comida" in p


def test_prompt_sin_feedback_no_lo_menciona() -> None:
    p = _build_user_prompt("Kabala", "Cesar", "guitarrista", None, None, "banda", None)
    assert "RETROALIMENTACIÓN" not in p


def test_regenerate_texto_exacto_no_usa_llm() -> None:
    """Con texto_exacto, _regenerate devuelve ese texto tal cual (sin llamar al LLM)."""
    from unittest.mock import patch

    import generate
    item = {"row_id": 1, "caption": "viejo", "meta": {
        "banda": "Kabala", "integrante": "", "rol": "", "tema_semilla": None,
        "foto_url": "/tmp/x.jpg", "foto_inset_url": None, "tipo": "banda",
        "rechazados": [], "feedback": None, "texto_exacto": "MI TITULAR EXACTO"}}
    with patch.object(generate.compose_mod, "compose", return_value="/tmp/out.png") as comp, \
         patch.object(generate.caption_mod, "generate_caption") as gen:
        cap, png = generate._regenerate(item)
    assert cap == "MI TITULAR EXACTO"
    assert gen.call_count == 0          # no se llamó al LLM
    comp.assert_called_once()


def test_regenerate_feedback_se_pasa_al_caption() -> None:
    from unittest.mock import patch

    import generate
    item = {"row_id": 1, "caption": "viejo", "meta": {
        "banda": "Kabala", "integrante": "", "rol": "", "tema_semilla": None,
        "foto_url": "/tmp/x.jpg", "foto_inset_url": None, "tipo": "banda",
        "rechazados": [], "feedback": "más absurdo", "texto_exacto": None}}
    with patch.object(generate.compose_mod, "compose", return_value="/tmp/out.png"), \
         patch.object(generate.caption_mod, "generate_caption", return_value="nuevo") as gen:
        cap, _ = generate._regenerate(item)
    assert cap == "nuevo"
    assert gen.call_args.kwargs["feedback"] == "más absurdo"
    assert "viejo" in gen.call_args.kwargs["rechazados"]  # evita el previo
