"""Migra las cuatro plantillas HTML de gdlscene al catálogo de DB.

No toca los archivos de `templates/`: los lee, renombra sus variables al
vocabulario canónico del contrato y escribe el resultado en `brand_templates`.
El dict TEMPLATES de src/compose.py sigue vivo y sin cambios hasta H5.

Idempotente por slug.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import plantillas
from ..entidades import slugificar
from ..plantillas import contrato as c

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

# Del vocabulario del código viejo al canónico del contrato.
_RENOMBRES: tuple[tuple[str, str], ...] = (
    ("caption_html", "titular | resaltar"),   # antes que `caption`, es prefijo
    ("foto_inset_url", "inset"),              # antes que `foto_url`
    ("foto_url", "imagen"),
    ("badge_text", "badge"),
    ("tag_text", "handle"),
    ("caption", "titular"),
)

# Cualquier tag de Jinja: {{ expresión }} o {% sentencia %}. El renombre solo
# se aplica DENTRO de estos tags (por eso una palabra como el id de DOM
# "caption" en <div id="caption"> o en getElementById('caption') no se toca:
# eso es HTML/JS plano, no una variable de plantilla).
_JINJA_TAG = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")

_EXTRA_BADGE = {"id": "badge", "tipo": "texto", "opcional": True,
                "desc": "Etiqueta corta en la esquina superior"}
_EXTRA_INSET = {"id": "inset", "tipo": "imagen", "opcional": True,
                "desc": "Foto secundaria en círculo"}

_SEEDS: tuple[dict[str, Any], ...] = (
    {"archivo": "meme.html", "nombre": "Clásica",
     "descripcion": "Fondo blanco, texto negro, franja verde. La original de gdlscene.",
     "extras": [_EXTRA_BADGE, _EXTRA_INSET]},
    {"archivo": "meme_verde.html", "nombre": "Verde",
     "descripcion": "La clásica invertida: fondo verde de marca, texto blanco.",
     "extras": [_EXTRA_BADGE, _EXTRA_INSET]},
    {"archivo": "meme_onion.html", "nombre": "Onion",
     "descripcion": "Titular encimado sobre la foto, con resaltes en verde.",
     "extras": []},
    {"archivo": "anuncio.html", "nombre": "Anuncio",
     "descripcion": "Flyer completo sobre fondo negro, para fechas y eventos.",
     "extras": [_EXTRA_BADGE]},
)


def _canonizar_tag(tag: str) -> str:
    """Renombra los identificadores viejos dentro de un solo tag de Jinja.

    Usa límites de palabra (`\\b`) en vez de exigir que la variable sea todo
    el contenido del tag: eso es lo que permite renombrar tanto
    `{{ foto_url }}` como `{{ foto_inset_url }}` dentro de `{% if
    foto_inset_url %}` (una sentencia, no una impresión) y `caption_html` aun
    cuando trae un filtro pegado como `{{ caption_html|safe }}`.
    """
    for viejo, nuevo in _RENOMBRES:
        tag = re.sub(r"\b" + re.escape(viejo) + r"\b", nuevo, tag)
    return tag


def _canonizar(html: str) -> str:
    """Renombra {{ viejo }} / {% viejo %} -> vocabulario canónico."""
    return _JINJA_TAG.sub(lambda m: _canonizar_tag(m.group(0)), html)


def sembrar(cx, account_id: int = 1) -> dict[str, int]:
    creadas = existentes = 0
    for seed in _SEEDS:
        nombre = seed["nombre"]
        # OJO: el slug lo calcula plantillas.crear con slugificar(), que quita
        # acentos ("Clásica" -> "clasica"). Buscar por nombre.lower() aquí
        # rompería la idempotencia y resembraría duplicados en cada corrida.
        slug = slugificar(nombre)
        if plantillas.por_slug(cx, account_id, slug) is not None:
            existentes += 1
            continue
        html = _canonizar((TEMPLATES_DIR / seed["archivo"]).read_text(encoding="utf-8"))
        contrato = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE),
                    "extras": seed["extras"]}
        tid = plantillas.crear(cx, account_id, nombre, html, contrato,
                               descripcion=seed["descripcion"], origen="seed",
                               mensaje_usuario=None)
        plantillas.activar(cx, tid)
        creadas += 1
    return {"creadas": creadas, "existentes": existentes}


if __name__ == "__main__":  # pragma: no cover
    from .. import db
    cx = db.connect()
    db.init_db(cx)
    print(sembrar(cx))
