"""Guion semántico de slideshows: el LLM emite estructura simple, sin estilos.

Clona el patrón de caption.py (proveedor agnóstico DeepSeek/Claude) pero pide
JSON ESTRICTO con objeto raíz dict (gotcha de parse_events: un array raíz se
pierde en silencio). El compilador (slideshow_compile) convierte este guion en
el contrato Slideshow completo.
"""
from __future__ import annotations

import json
import re
from typing import Any

import config

ROLES = ("hook", "punto", "cta")

SYSTEM_PROMPT = """\
Eres guionista de slideshows para redes sociales (carruseles de imágenes con \
texto grande encima, estilo TikTok/Instagram). Escribes guiones CORTOS y con \
gancho sobre CUALQUIER tema que te pidan: productos, nichos, humor, divulgación.

Devuelve ÚNICAMENTE un objeto JSON válido con este esquema EXACTO:
{"tema": str, "hook": str, "caption": str, "cta": str,
 "slides": [{"text": str, "rol": "hook"|"punto"|"cta", "image_hint": str}]}

Reglas:
- El PRIMER slide tiene rol "hook": el gancho, máximo 12 palabras, que obligue \
a pasar al siguiente slide.
- Los slides intermedios tienen rol "punto": UNA sola idea por slide, máximo \
20 palabras, rematada (nada de frases que continúan en el siguiente).
- El ÚLTIMO slide tiene rol "cta": llamada a la acción corta (seguir, comentar, \
guardar).
- "image_hint": búsqueda de imagen de fondo en 2-5 palabras EN INGLÉS \
(los bancos de imagen responden mejor en inglés). Concreta y visual: \
"vintage guitar closeup", no "music concept". Si el tema trata de un sujeto \
específico (una banda, persona, lugar o producto con nombre propio), INCLUYE \
ese nombre EXACTO tal cual (sin traducirlo) en el image_hint de los slides \
donde ese sujeto sea el foco: "kabala band on stage".
- "caption": pie del post, 1-2 frases + una pregunta que invite a comentar.
- Español de México, sin emojis en los slides (en el caption sí se permiten).
- El texto de cada slide debe funcionar SOLO, en pantalla, en letra grande."""


def extraer_guion(texto: str) -> dict[str, Any] | None:
    """Primer objeto JSON en la respuesta (tolera ```json ...```). PURO."""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def validar_guion(data: dict[str, Any], *, n_slides: int) -> list[str]:
    """Errores del guion contra el esquema; [] = válido. PURO."""
    errores: list[str] = []
    for clave in ("tema", "hook", "caption", "cta", "slides"):
        if clave not in data:
            errores.append(f"falta la clave {clave!r}")
    slides = data.get("slides") or []
    if not isinstance(slides, list) or not 1 <= len(slides) <= 20:
        errores.append(f"slides: deben ser 1-20, hay {len(slides)}")
        return errores
    if len(slides) != n_slides:
        errores.append(f"slides: se pidieron {n_slides}, llegaron {len(slides)}")
    for i, sl in enumerate(slides):
        if not isinstance(sl, dict):
            errores.append(f"slide {i}: no es objeto")
            continue
        if not (sl.get("text") or "").strip():
            errores.append(f"slide {i}: text vacío")
        if sl.get("rol") not in ROLES:
            errores.append(f"slide {i}: rol desconocido {sl.get('rol')!r}")
        if not (sl.get("image_hint") or "").strip():
            errores.append(f"slide {i}: image_hint vacío")
    if slides and slides[0].get("rol") != "hook":
        errores.append("el primer slide debe tener rol 'hook'")
    if len(slides) >= 2 and slides[-1].get("rol") != "cta":
        errores.append("el último slide debe tener rol 'cta'")
    return errores


def _build_user_prompt(tema: str, formato: str, n_slides: int,
                       contexto: str | None, rechazados: list[str] | None,
                       feedback: str | None, errores_previos: list[str]) -> str:
    partes = [
        f"TEMA: {tema}",
        f"FORMATO: {config.SLIDESHOW_FORMATOS[formato]}",
        f"NÚMERO DE SLIDES: exactamente {n_slides} (incluyendo hook y cta).",
    ]
    if contexto:
        partes.append(f"CONTEXTO/VOZ (síguelo): {contexto}")
    if rechazados:
        partes.append("Hooks ya RECHAZADOS (no los repitas ni te parezcas):\n"
                      + "\n".join(f"- {r}" for r in rechazados))
    if feedback:
        partes.append(f"RETROALIMENTACIÓN del editor (al pie de la letra): {feedback}")
    if errores_previos:
        partes.append("Tu respuesta anterior tuvo estos errores, corrígelos:\n"
                      + "\n".join(f"- {e}" for e in errores_previos))
    partes.append("Devuelve SOLO el objeto JSON.")
    return "\n\n".join(partes)


def _llamar_llm(user_prompt: str) -> str:
    """IO: una llamada al proveedor configurado. Monkeypatch-eable en tests."""
    if config.LLM_PROVIDER == "claude":
        return _via_anthropic(user_prompt)
    return _via_deepseek(user_prompt)


def _via_deepseek(user_prompt: str) -> str:
    from openai import OpenAI

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en el .env")
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user_prompt}],
        temperature=config.SLIDESHOW_TEMPERATURE,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


def _via_anthropic(user_prompt: str) -> str:
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en el .env (LLM_PROVIDER=claude)")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2000,
        temperature=min(config.SLIDESHOW_TEMPERATURE, 1.0),
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def generar_guion(tema: str, *, formato: str = "listicle", n_slides: int = 6,
                  contexto: str | None = None,
                  rechazados: list[str] | None = None,
                  feedback: str | None = None) -> dict[str, Any]:
    """Guion validado, o RuntimeError tras 3 intentos.

    En cada reintento se anexan los errores de validación al prompt para que
    el LLM se corrija (patrón del spec).
    """
    if formato not in config.SLIDESHOW_FORMATOS:
        raise ValueError(f"Formato desconocido: {formato!r}. "
                         f"Opciones: {list(config.SLIDESHOW_FORMATOS)}")
    if not 1 <= n_slides <= 10:
        raise ValueError(
            f"n_slides debe ser 1-10, llegó {n_slides}. El tope de 10 viene del "
            "carrusel de IG/Telegram (approval.py e instagram.py truncan en 10): "
            "pedir más slides quema llamadas al LLM condenadas a truncarse en silencio.")
    errores: list[str] = []
    for _ in range(3):
        prompt = _build_user_prompt(tema, formato, n_slides, contexto,
                                    rechazados, feedback, errores)
        crudo = _llamar_llm(prompt)
        data = extraer_guion(crudo)
        if data is None:
            errores = ["la respuesta no contenía un objeto JSON válido"]
            continue
        errores = validar_guion(data, n_slides=n_slides)
        if not errores:
            return data
    raise RuntimeError(f"El LLM no produjo un guion válido en 3 intentos: {errores}")


if __name__ == "__main__":
    # Prueba aislada real: python -m src.slideshow_script
    print(json.dumps(generar_guion("cafeterías de especialidad en Guadalajara",
                                   n_slides=5), ensure_ascii=False, indent=2))
