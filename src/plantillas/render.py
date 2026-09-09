"""Render de una plantilla de DB: arma el contexto y dispara Chromium.

Separado de `contrato` y `generador` a propósito: aquí sí hay disco y
navegador. Los otros dos son puros para poder validar la salida del LLM en
milisegundos sin levantar nada.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import config

from .. import compose, db
from . import contrato as _contrato
from . import filtros

# Misma carpeta que sirve `api/routers/fuentes_api.py` (`BRANDS_DIR`) y a la
# que escribe `src/jobs/handlers.py`: fotos y stickers subidos por la marca,
# NO `config.PHOTOS_DIR` (esa es la de fotos scrapeadas de IG, otro concepto).
BRANDS_DIR = config.BASE_DIR / "data" / "brands"


class CamposInvalidos(ValueError):
    """Los valores no cumplen el contrato de la plantilla."""


def _fuentes_de_marca(cx, account_id: int) -> list[dict[str, Any]]:
    return db.rows(cx, "SELECT familia, archivo FROM brand_fonts WHERE account_id = ?",
                   (account_id,))


def contexto(marca, campos: dict[str, Any], *,
             fonts_dir: str | None = None, fotos_dir: str | None = None) -> dict[str, Any]:
    """Campos del contrato + el núcleo base inyectado desde la marca."""
    ctx = dict(campos)
    # OJO: lo vacío va como "" y nunca como None. _to_src(None) devuelve "",
    # y Jinja escribiría el None de Python como el texto "None" dentro del CSS.
    # Verificado comparando el PNG contra el del camino viejo.
    ctx["imagen"] = compose._to_src(campos.get("imagen"))
    handle = (marca.ig_handle or "").lstrip("@")
    ctx["handle"] = f"@{handle}" if handle else ""
    ctx["logo"] = compose._to_src(marca.logo_path)
    ctx["color_marca"] = marca.color_marca
    ctx["fonts_dir"] = fonts_dir or compose.FONTS_DIR.as_uri()
    ctx["fotos_dir"] = fotos_dir or (BRANDS_DIR / marca.slug / "fotos").as_uri()
    return ctx


def render(cx, marca, plantilla: dict[str, Any], campos: dict[str, Any], *,
           out_path: Path | None = None, row_id: str | None = None) -> Path:
    ct = _contrato.contrato_de_json(plantilla["contrato_json"])
    errores = _contrato.validar_campos(campos, ct)
    if errores:
        raise CamposInvalidos("; ".join(errores))

    fuentes = _fuentes_de_marca(cx, marca.id)
    ctx = contexto(marca, campos)
    ctx["brand_fonts"] = fuentes

    tpl = filtros.entorno().from_string(plantilla["html"])
    html = tpl.render(**ctx)
    return compose.render_html(html, aspecto=ct.get("aspecto", "4:5"),
                               out_path=out_path, row_id=row_id, prefix="post")
