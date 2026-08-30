"""Filtros Jinja2 del motor de render de plantillas.

Módulo puro: sin DB, sin Playwright, sin `db` ni SQLite. `resaltar` sustituye
a `src/compose.py:_onion_html` para la plantilla onion — mismo HTML, ahora
como filtro Jinja (`{{ titular | resaltar }}`) en vez de precómputo en Python
antes de renderizar. `src/compose.py` NO se toca: sigue vivo con su propia
copia hasta H5.
"""
from __future__ import annotations

import html as _html_mod
from typing import Callable

import jinja2
from markupsafe import Markup

# Copia literal de `src/compose.py:_STOPWORDS`: mismo criterio de qué
# palabra se resalta, para no cambiar el render de gdlscene.
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
    "y", "o", "u", "e", "que", "en", "con", "por", "para", "su", "sus", "se", "lo",
    "le", "les", "es", "son", "fue", "ha", "han", "como", "más", "pero", "tras",
}


def resaltar(texto: str) -> Markup:
    """Envuelve cada palabra de contenido en <span class='hl'>; las de función, en <span> simple.

    Copia literal de la lógica de `src/compose.py:_onion_html`. Se envuelve
    en `Markup` para que Jinja no vuelva a escapar las etiquetas `<span>`
    al renderizar (autoescape las trataría como texto plano si no).
    """
    out = []
    for word in (texto or "").split():
        core = word.strip(".,;:¡!¿?\"'()—–-").lower()
        cls = "" if core in _STOPWORDS else "hl"
        safe = _html_mod.escape(word)
        out.append(f'<span class="{cls}">{safe}</span>' if cls else f"<span>{safe}</span>")
    return Markup(" ".join(out))


FILTROS: dict[str, Callable] = {"resaltar": resaltar}


def entorno() -> jinja2.Environment:
    """`Environment` con `FILTROS` ya registrados en `.filters`."""
    env = jinja2.Environment()
    env.filters.update(FILTROS)
    return env
