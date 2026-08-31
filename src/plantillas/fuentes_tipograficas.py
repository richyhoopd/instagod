"""Qué tipografías puede usar una marca: las globales más las suyas.

El diseñador con LLM recibe esta lista y solo puede pedir de aquí. Es lo que
hace el render determinista y offline: nada de webfonts externas que el día
que falle el DNS dejen un post publicado con la tipografía equivocada.
"""
from __future__ import annotations

from typing import Any

import config

from .. import db


def catalogo(cx, account_id: int) -> list[dict[str, Any]]:
    """Globales + propias de la marca. Las propias pisan por nombre."""
    fuentes: dict[str, dict[str, Any]] = {
        familia: {"familia": familia, "archivo": archivo, "propia": False}
        for familia, archivo in config.SLIDESHOW_FUENTES.items()
    }
    for fila in db.rows(cx, "SELECT familia, archivo FROM brand_fonts "
                            "WHERE account_id = ? ORDER BY familia", (account_id,)):
        fuentes[fila["familia"]] = {"familia": fila["familia"],
                                    "archivo": fila["archivo"], "propia": True}
    return sorted(fuentes.values(), key=lambda f: f["familia"])


def familias(cx, account_id: int) -> set[str]:
    return {f["familia"] for f in catalogo(cx, account_id)}


def css_font_faces(cx, account_id: int, fonts_dir: str) -> str:
    """Bloque de @font-face para inyectar en el HTML de una plantilla."""
    piezas = []
    for f in catalogo(cx, account_id):
        ruta = f["archivo"] if f["propia"] else f"{fonts_dir}/{f['archivo']}"
        piezas.append(
            f"@font-face{{font-family:'{f['familia']}';src:url('{ruta}');"
            "font-display:block;}"
        )
    return "\n".join(piezas)
