"""Catálogo de foros canónicos: resuelve el texto libre de `events.lugar`.

`events.lugar` lo extrae un LLM del OCR y del caption, así que el mismo foro
llega escrito de media docena de formas: "Staditche", "@staditche",
"Staditche (Espacio Cultural)", "HAKE AL REY", "REY". Sin una identidad estable,
dos flyers del mismo evento salen como dos slides distintos en la agenda.

El diseño separa dos cosas a propósito:

- `normalizar()` barre lo MECÁNICO (mayúsculas, arrobas, paréntesis, acentos,
  prefijos y sufijos de tipo de local). Es pura y determinista.
- La tabla `venue_alias` captura lo que la normalización NO puede: "REY" es un
  OCR truncado de "Hake Al Rey" y ninguna regla de texto razonable las une sin
  unir también cosas que no debe. Eso se resuelve UNA vez por alias, a mano o
  con el LLM de la siembra, y queda resuelto para siempre.

La resolución en caliente es una búsqueda exacta: sin LLM, sin fuzzy, mismo
resultado siempre y auditable.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Palabras de "tipo de local" que no distinguen un foro de otro. Se quita como
# máximo UNA al inicio y UNA al final: "Foro Sala Diana" es "sala diana", no
# "diana" — encadenar borrados fusionaría lugares distintos.
_GENERICOS = (
    "centro cultural", "espacio cultural", "concert room", "concert hall",
    "el foro", "foro", "salon", "sala", "bar", "pub",
)

# Artículos españoles. Si después de podar genéricos queda solo un artículo,
# conservamos el texto original: "El Foro" → "el foro", no "el".
_ARTICULOS = ("el", "la", "los", "las")


def normalizar(s: str | None) -> str:
    """Clave de comparación de un lugar. PURA.

    Cadena vacía significa "no hay lugar" — nunca "lugar irreconocible".
    """
    if not s:
        return ""
    # Paréntesis y su contenido: "Staditche (Espacio Cultural)" → "Staditche".
    s = re.sub(r"\([^)]*\)", " ", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return ""

    completo = s  # antes de podar genéricos, por si el lugar ES un genérico
    for pref in _GENERICOS:  # como máximo UN prefijo
        if s.startswith(pref + " "):
            s = s[len(pref) + 1:].strip()
            break
    for suf in _GENERICOS:  # como máximo UN sufijo
        if s.endswith(" " + suf):
            s = s[: -(len(suf) + 1)].strip()
            break
    # Si el lugar era SOLO una palabra genérica ("Foro"), conservamos el texto:
    # "" está reservado para "no hay lugar" y confundir ambos casos haría que
    # todos los eventos sin lugar se fusionaran entre sí.
    # También si el resultado es solo un artículo ("El Foro" → "el"), conservamos.
    return s if s and s not in _ARTICULOS else completo


def sugerencias(texto: str, candidatos: list[tuple[int, str]],
                tope: int = 3) -> list[tuple[int, str, float]]:
    """(venue_id, nombre, score) de los foros más parecidos. PURA.

    Para la cola de curación de la GUI. `difflib` en vez de LLM: es instantáneo,
    gratis y determinista, y aquí solo necesitamos ORDENAR candidatos para que
    Ricardo elija — no acertar solo.
    """
    clave = normalizar(texto)
    puntuadas = [
        (vid, nombre, difflib.SequenceMatcher(None, clave, normalizar(nombre)).ratio())
        for vid, nombre in candidatos
    ]
    puntuadas.sort(key=lambda t: (-t[2], t[0]))
    return puntuadas[:tope]
