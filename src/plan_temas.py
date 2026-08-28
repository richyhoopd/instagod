"""Propuesta de temas de un plan de contenido: UNA llamada LLM → N temas curables.

Fase barata del plan masivo (spec 2026-08-28): antes de gastar imágenes y
renders, el LLM propone titulares + ganchos que el usuario cura en el portal.
Clona el patrón de slideshow_script (JSON estricto, extraer/validar puros,
3 intentos reinyectando errores) y reusa su `_llamar_llm` con system prompt
propio.

Anti-alucinación de noticias: un tema solo puede citar una URL que venga del
banco de noticias entregado; cualquier otra URL se degrada a fuente 'prompt'.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src import slideshow_script

SYSTEM_PROMPT_TEMAS = """\
Eres estratega de contenido para redes sociales. Te dan el OBJETIVO de un plan
(semanal o mensual) de una marca y, a veces, un banco de NOTICIAS recientes.
Propones una lista de temas DIVERSOS para carruseles de imágenes.

Devuelve ÚNICAMENTE un objeto JSON válido con este esquema EXACTO:
{"temas": [{"titulo": str, "formato": str, "hook": str,
            "fuente": "prompt"|"noticia", "url": str|null}]}

Reglas:
- "titulo": el tema del carrusel, concreto y con gancho, máximo 15 palabras.
- "formato": UNO de los formatos permitidos que te listan.
- "hook": el ángulo/gancho sugerido para el primer slide, máximo 12 palabras.
- "fuente": "noticia" SOLO si el tema sale de una noticia del banco (y entonces
  "url" es la URL EXACTA de esa noticia, copiada tal cual); si no, "prompt" y
  "url" null.
- Temas variados entre sí: nada de 5 variaciones del mismo ángulo.
- Español de México."""


def extraer_temas(texto: str) -> dict[str, Any] | None:
    """Primer objeto JSON en la respuesta (tolera ```json ...```). PURO."""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def validar_temas(data: dict[str, Any], *, formatos: list[str]) -> list[str]:
    """Errores del lote de temas; [] = válido. PURO.

    El conteo NO se valida aquí (el caller trunca a n; pedir el número exacto
    al LLM quema reintentos — lección del bug de slides 2026-08-28). El formato
    desconocido tampoco es error: se normaliza en `proponer`.
    """
    errores: list[str] = []
    temas = data.get("temas")
    if not isinstance(temas, list) or not temas:
        return ["temas: debe ser una lista con al menos 1 tema"]
    for i, t in enumerate(temas):
        if not isinstance(t, dict):
            errores.append(f"tema {i}: no es objeto")
            continue
        if not (t.get("titulo") or "").strip():
            errores.append(f"tema {i}: titulo vacío")
        if not (t.get("hook") or "").strip():
            errores.append(f"tema {i}: hook vacío")
    return errores


def _build_user_prompt(objetivo: str, n: int, formatos: list[str],
                       contexto: str | None, noticias: list[dict[str, Any]],
                       errores_previos: list[str]) -> str:
    partes = [
        f"OBJETIVO DEL PLAN: {objetivo}",
        f"NÚMERO DE TEMAS: {n}",
        f"FORMATOS PERMITIDOS: {', '.join(formatos)}",
    ]
    if contexto:
        partes.append(f"VOZ DE LA MARCA (síguela): {contexto}")
    if noticias:
        lineas = [f"- {t['titulo']} | {t.get('url')}"
                  + (f" | {t['resumen']}" if t.get("resumen") else "")
                  for t in noticias]
        partes.append("BANCO DE NOTICIAS (las únicas URLs citables):\n" + "\n".join(lineas))
    if errores_previos:
        partes.append("Tu respuesta anterior tuvo estos errores, corrígelos:\n"
                      + "\n".join(f"- {e}" for e in errores_previos))
    partes.append("Devuelve SOLO el objeto JSON.")
    return "\n\n".join(partes)


def proponer(objetivo: str, *, n: int, formatos: list[str],
             contexto: str | None = None,
             noticias: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """N temas normalizados, o RuntimeError tras 3 intentos.

    Normalizaciones (no queman reintentos): trunca a n, formato desconocido →
    primer formato permitido, fuente 'noticia' sin URL del banco → 'prompt'.
    """
    if not formatos:
        raise ValueError("formatos no puede estar vacío")
    noticias = noticias or []
    urls_banco = {t.get("url") for t in noticias if t.get("url")}
    errores: list[str] = []
    for _ in range(3):
        prompt = _build_user_prompt(objetivo, n, formatos, contexto, noticias, errores)
        crudo = slideshow_script._llamar_llm(prompt, system_prompt=SYSTEM_PROMPT_TEMAS)
        data = extraer_temas(crudo)
        if data is None:
            errores = ["la respuesta no contenía un objeto JSON válido"]
            continue
        errores = validar_temas(data, formatos=formatos)
        if errores:
            continue
        limpios: list[dict[str, Any]] = []
        for t in data["temas"][:n]:
            formato = t.get("formato") if t.get("formato") in formatos else formatos[0]
            url = t.get("url")
            if t.get("fuente") == "noticia" and url in urls_banco:
                fuente = "noticia"
            else:
                fuente, url = "prompt", None
            limpios.append({"titulo": t["titulo"].strip(), "formato": formato,
                            "hook": (t.get("hook") or "").strip(),
                            "fuente": fuente, "url": url})
        return limpios
    raise RuntimeError(f"El LLM no produjo temas válidos en 3 intentos: {errores}")
