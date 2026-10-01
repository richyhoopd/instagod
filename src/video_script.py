"""Guion del video narrado: historia cruda → título + cuerpo locutable.

Reusa el cliente LLM de `slideshow_script` (DeepSeek/Claude, agnóstico) con
otro system prompt: aquí no se inventa contenido, se REESCRIBE una historia
real (de `topic_suggestions`, p. ej. una fuente de Reddit) para que suene bien
hablada y quepa en un reel.

Por qué reescribir y no narrar el texto crudo: el original trae markdown,
"EDIT:", agradecimientos, links y párrafos de 200 palabras que el TTS lee como
un bloque sin aire. El modelo lo deja en primera persona, con frases cortas y
un gancho al inicio.
"""
from __future__ import annotations

import json
from typing import Any

import config
from src.slideshow_script import _llamar_llm, extraer_guion

SYSTEM_PROMPT = """\
Eres guionista de videos verticales narrados (estilo "historias de Reddit" de \
TikTok/Reels). Recibes una historia real y la reescribes para que la lea una \
voz en off.

Devuelve ÚNICAMENTE un objeto JSON válido con este esquema EXACTO:
{{"titulo": str, "cuerpo": str, "caption": str}}

Reglas:
- "titulo": el gancho que aparece en la tarjeta inicial. Máximo 14 palabras, \
en forma de pregunta o afirmación que obligue a quedarse. NO uses comillas.
- "cuerpo": la historia hablada, en PRIMERA persona, {min_palabras}-{max_palabras} \
palabras. Frases CORTAS (máximo 15 palabras cada una) separadas por punto: la \
voz respira en los puntos y los subtítulos cortan ahí.
- Abre el cuerpo directo en la acción, sin "hola", sin "les cuento", sin \
presentarte.
- Conserva los hechos de la historia original: puedes cortar, resumir y \
reordenar, pero NO inventes datos nuevos ni cambies el desenlace.
- Español de México, tono conversacional. Nada de emojis, hashtags, markdown, \
asteriscos ni links DENTRO de titulo o cuerpo.
- Escribe los números con letra ("treinta y dos", no "32") y evita siglas sin \
deletrear: el TTS las lee mal.
- "caption": pie del post, 1-2 frases + una pregunta para comentarios. Aquí SÍ \
puedes usar emojis.
"""

_MAX_INTENTOS = 3


def _prompt(titulo: str, cuerpo: str, *, min_palabras: int, max_palabras: int,
            contexto: str | None, feedback: str | None) -> str:
    partes = [f"Historia original (título): {titulo}",
              f"Historia original (cuerpo):\n{cuerpo}"]
    if contexto:
        partes.append(f"Contexto de la marca: {contexto}")
    partes.append(f"El cuerpo debe tener entre {min_palabras} y {max_palabras} palabras.")
    if feedback:
        partes.append(f"Corrige esto del intento anterior: {feedback}")
    return "\n\n".join(partes)


def validar(data: dict[str, Any], *, min_palabras: int, max_palabras: int) -> list[str]:
    """Problemas del guion devuelto por el LLM. Lista vacía = usable."""
    errores: list[str] = []
    titulo = (data.get("titulo") or "").strip()
    cuerpo = (data.get("cuerpo") or "").strip()
    if not titulo:
        errores.append("falta titulo")
    elif len(titulo.split()) > 20:
        errores.append("titulo de más de 20 palabras")
    n = len(cuerpo.split())
    if not cuerpo:
        errores.append("falta cuerpo")
    elif n < min_palabras:
        errores.append(f"cuerpo de {n} palabras, mínimo {min_palabras}")
    elif n > max_palabras:
        errores.append(f"cuerpo de {n} palabras, máximo {max_palabras}")
    # El TTS lee el markdown en voz alta ("asterisco asterisco"), así que un
    # cuerpo con markup es un guion inválido, no un detalle cosmético.
    for simbolo in ("*", "#", "](", "http"):
        if simbolo in cuerpo:
            errores.append(f"cuerpo con markup/link ({simbolo!r})")
            break
    return errores


def generar_guion(titulo: str, cuerpo: str, *, min_palabras: int = 90,
                  max_palabras: int = 220, contexto: str | None = None,
                  _llamar=None) -> dict[str, Any]:
    """Guion validado `{titulo, cuerpo, caption}`, o RuntimeError tras 3 intentos.

    Mismo lazo de reintento con feedback que `slideshow_script.generar_guion`:
    si el modelo se pasa de palabras o mete markdown, se le dice qué falló y
    se reintenta en vez de aceptar un guion que el TTS va a leer mal.
    """
    llamar = _llamar or _llamar_llm
    system = SYSTEM_PROMPT.format(min_palabras=min_palabras,
                                  max_palabras=max_palabras)
    feedback: str | None = None
    ultimos: list[str] = ["sin respuesta del LLM"]
    for _ in range(_MAX_INTENTOS):
        crudo = llamar(_prompt(titulo, cuerpo, min_palabras=min_palabras,
                               max_palabras=max_palabras, contexto=contexto,
                               feedback=feedback),
                       system_prompt=system)
        data = extraer_guion(crudo)
        if data is None:
            ultimos = ["respuesta no es JSON válido"]
            feedback = "Devuelve SOLO el objeto JSON, sin texto alrededor."
            continue
        ultimos = validar(data, min_palabras=min_palabras, max_palabras=max_palabras)
        if not ultimos:
            return {"titulo": (data.get("titulo") or "").strip(),
                    "cuerpo": (data.get("cuerpo") or "").strip(),
                    "caption": (data.get("caption") or "").strip()}
        feedback = "; ".join(ultimos)
    raise RuntimeError(f"Guion de video inválido tras {_MAX_INTENTOS} intentos: "
                       f"{'; '.join(ultimos)}")


def guion_directo(titulo: str, cuerpo: str) -> dict[str, Any]:
    """Guion SIN LLM: usa la historia tal cual (modo `--sin-llm`).

    Útil para probar el render sin gastar tokens y para historias ya curadas a
    mano. Solo limpia lo que el TTS leería en voz alta (markdown y links).
    """
    import re
    limpio = re.sub(r"https?://\S+", "", cuerpo)
    limpio = re.sub(r"[*#_`>]+", "", limpio)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    return {"titulo": titulo.strip(), "cuerpo": limpio, "caption": ""}


CAPTION_SYSTEM = """\
Escribes el caption de Instagram de un reel de historias narradas.

Devuelve ÚNICAMENTE un objeto JSON con este esquema EXACTO:
{"caption": str}

Reglas:
- Español de México, 1 o 2 frases. Máximo 200 caracteres.
- Engancha o pregunta algo que invite a comentar. Nada de resumir la historia:
  el video ya la cuenta.
- Sin hashtags (los pone la marca aparte) y sin comillas alrededor.
- Nada de "dale like", "sígueme" ni lenguaje de locutor."""

_CAPTION_MAX = 200


def generar_caption(titulo: str, cuerpo: str, *, contexto: str | None = None,
                    _llamar=None) -> str:
    """Caption suelto para un reel YA renderizado (importado del prototipo).

    A diferencia de `generar_guion`, aquí no se reescribe la narración: el
    audio ya existe. Si el LLM falla o devuelve algo inservible, regresa ""
    en vez de reventar: un caption vacío se edita en el portal, una excepción
    corta la importación del lote.
    """
    llamar = _llamar or _llamar_llm
    partes = [f"Título: {titulo}", f"Historia: {cuerpo[:1500]}"]
    if contexto:
        partes.append(f"Sobre la marca: {contexto}")
    try:
        crudo = llamar("\n\n".join(partes), system_prompt=CAPTION_SYSTEM)
    except Exception:  # noqa: BLE001 — el caption es opcional, no corta el lote
        return ""
    # El cliente de slideshow_script pide response_format=json_object al
    # proveedor, así que la respuesta SIEMPRE es JSON: pedir texto plano aquí
    # devolvía puros espacios.
    data = extraer_guion(crudo) or {}
    texto = str(data.get("caption") or "").strip().strip('"').strip()
    # Una respuesta kilométrica es el modelo ignorando el formato: mejor vacío
    # que un caption que hay que borrar a mano.
    return texto if 0 < len(texto) <= _CAPTION_MAX else ""
