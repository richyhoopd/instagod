"""Guionista de video: prompt formateable, validación y lazo de reintento."""
from __future__ import annotations

import json

import pytest

from src import video_script


def _respuesta(titulo="Mi vecino tocó a las tres", cuerpo=None, caption="¿te pasó?") -> str:
    cuerpo = cuerpo if cuerpo is not None else " ".join(["palabra"] * 120)
    return json.dumps({"titulo": titulo, "cuerpo": cuerpo, "caption": caption})


def test_system_prompt_se_formatea_sin_romperse() -> None:
    """El esquema JSON del prompt lleva llaves: deben estar escapadas.

    Regresión: `{"titulo": ...}` sin escapar hacía que `.format` tratara el
    esquema como campo y reventara con KeyError en cada generación.
    """
    texto = video_script.SYSTEM_PROMPT.format(min_palabras=90, max_palabras=220)
    assert '{"titulo": str, "cuerpo": str, "caption": str}' in texto
    assert "90-220 palabras" in texto


def test_generar_guion_devuelve_guion_valido() -> None:
    llamadas: list[dict] = []

    def _llamar(prompt, system_prompt=None):
        llamadas.append({"prompt": prompt, "system": system_prompt})
        return _respuesta()

    guion = video_script.generar_guion("T original", "C original", _llamar=_llamar)
    assert guion["titulo"] == "Mi vecino tocó a las tres"
    assert guion["caption"] == "¿te pasó?"
    assert len(llamadas) == 1
    # la historia original viaja en el prompt (no se inventa desde cero)
    assert "T original" in llamadas[0]["prompt"]
    assert "C original" in llamadas[0]["prompt"]


def test_generar_guion_reintenta_con_feedback_y_acaba_bien() -> None:
    respuestas = ["no es json", _respuesta(cuerpo="muy corto"), _respuesta()]
    prompts: list[str] = []

    def _llamar(prompt, system_prompt=None):
        prompts.append(prompt)
        return respuestas.pop(0)

    guion = video_script.generar_guion("T", "C", _llamar=_llamar)
    assert guion["cuerpo"].startswith("palabra")
    assert len(prompts) == 3
    # el 2º y 3er intento le dicen al modelo QUÉ falló
    assert "JSON" in prompts[1]
    assert "palabras" in prompts[2]


def test_generar_guion_se_rinde_tras_tres_intentos() -> None:
    def _llamar(prompt, system_prompt=None):
        return _respuesta(cuerpo="corto")

    with pytest.raises(RuntimeError, match="inválido tras 3 intentos"):
        video_script.generar_guion("T", "C", _llamar=_llamar)


@pytest.mark.parametrize("data,espera", [
    ({"titulo": "", "cuerpo": " ".join(["x"] * 120)}, "falta titulo"),
    ({"titulo": "t", "cuerpo": "dos palabras"}, "mínimo"),
    ({"titulo": "t", "cuerpo": " ".join(["x"] * 400)}, "máximo"),
    ({"titulo": "t", "cuerpo": " ".join(["x"] * 120) + " **negritas**"}, "markup"),
    ({"titulo": "t", "cuerpo": " ".join(["x"] * 120) + " http://x.com"}, "markup"),
])
def test_validar_caza_guiones_inservibles(data, espera) -> None:
    errores = video_script.validar(data, min_palabras=90, max_palabras=220)
    assert any(espera in e for e in errores), errores


def test_guion_directo_limpia_sin_llm() -> None:
    """`--sin-llm` no llama al modelo pero sí quita lo que el TTS leería mal."""
    guion = video_script.guion_directo(
        "  Mi título  ",
        "Hola **mundo**\n\n## Sección\nmira http://ejemplo.com/x ya")
    assert guion["titulo"] == "Mi título"
    assert guion["cuerpo"] == "Hola mundo Sección mira ya"
    assert guion["caption"] == ""


def test_caption_system_pide_json() -> None:
    """Regresión: el cliente LLM fuerza response_format=json_object.

    Con un system prompt que pedía texto plano, el proveedor devolvía puros
    espacios y el caption salía siempre vacío.
    """
    assert '{"caption": str}' in video_script.CAPTION_SYSTEM


def test_generar_caption_extrae_el_texto_del_json() -> None:
    llamadas: list[dict] = []

    def _llamar(prompt, system_prompt=None):
        llamadas.append({"prompt": prompt, "system": system_prompt})
        return '{"caption": "¿te ha pasado algo así?"}'

    cap = video_script.generar_caption("Mi título", "La historia", _llamar=_llamar)
    assert cap == "¿te ha pasado algo así?"
    assert "Mi título" in llamadas[0]["prompt"]
    assert "La historia" in llamadas[0]["prompt"]


@pytest.mark.parametrize("respuesta", [
    "   ",                                    # el fallo real: solo espacios
    "no es json",
    '{"caption": ""}',
    '{"caption": "' + "x" * 300 + '"}',       # ignoró el límite de 200
])
def test_generar_caption_devuelve_vacio_en_vez_de_basura(respuesta) -> None:
    """Un caption malo se edita en el portal; una excepción corta el lote."""
    assert video_script.generar_caption("T", "C", _llamar=lambda *a, **k: respuesta) == ""


def test_generar_caption_no_revienta_si_el_llm_falla() -> None:
    def _explota(*a, **k):
        raise RuntimeError("502 del proveedor")

    assert video_script.generar_caption("T", "C", _llamar=_explota) == ""
