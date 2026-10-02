"""Preview cacheado de una plantilla de DB, con datos de muestra.

Molde: `src/estilo_preview.py` (hash del contenido → nombre de archivo,
directorio de cache, limpieza de versiones viejas del mismo id). La diferencia
es la clave del hash: aquí es de `html + contrato_json + layout_json`
(`clave_de`), así que el cache se invalida solo el día que la plantilla
cambie (nueva versión), no antes.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import config

from ..image_sources import BRANDS_DIR
from . import contrato as _contrato
from . import obtener
from . import render as _render

PREVIEWS_DIR = config.BASE_DIR / "data" / "previews"
_EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp"}


def _foto_muestra(slug: str) -> str | None:
    """Primera foto del banco propio de la marca; None → sin imagen de muestra."""
    raiz = BRANDS_DIR / slug / "fotos"
    if not raiz.is_dir():
        return None
    for p in sorted(raiz.rglob("*")):
        if p.is_file() and p.suffix.lower() in _EXT_FOTO:
            return str(p)
    return None


def campos_de_muestra(contrato: dict[str, Any]) -> dict[str, Any]:
    """Un valor válido de CADA tipo que declare el contrato.

    Es lo que evita que el preview reviente con una plantilla que declara
    extras raros: mientras el valor pase `contrato.validar_campos`, el render
    corre sin importar qué tan exótico sea el contrato.
    """
    campos: dict[str, Any] = {
        "titular": "Titular de ejemplo para ver cómo se acomoda el texto",
    }
    for extra in contrato.get("extras", []) or []:
        eid = extra.get("id")
        if not eid:
            continue
        tipo = extra.get("tipo", "texto")
        if tipo == "lista":
            minimo = extra.get("min", 1)
            campos[eid] = [f"Elemento {i + 1}" for i in range(minimo)]
        elif tipo == "numero":
            campos[eid] = 0
        elif tipo == "booleano":
            campos[eid] = True
        else:  # texto, texto_largo, imagen
            campos[eid] = "Ejemplo"
    return campos


def clave_de(fila: dict[str, Any]) -> str:
    """Huella del contenido de un diseño. Si cambia, el PNG se rehace.

    Incluye el layout aunque el HTML se derive de él: así un cambio que no
    altere el HTML (por ejemplo la rejilla) tampoco resucita un PNG viejo por
    accidente.
    """
    crudo = f"{fila['html']}{fila['contrato_json']}{fila.get('layout_json') or ''}"
    return hashlib.sha1(crudo.encode()).hexdigest()[:12]


def png_de(cx, marca, template_id: int) -> Path:
    """Ruta del preview de la plantilla (la renderiza si no está en cache).

    ValueError si la plantilla no existe o no es de esta marca — mismo
    contrato que `posts.crear_post` y `plantillas.render.render`.
    """
    tpl = obtener(cx, template_id)
    if tpl is None or tpl["account_id"] != marca.id:
        raise ValueError("plantilla")

    ct = _contrato.contrato_de_json(tpl["contrato_json"])
    clave = clave_de(tpl)
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    destino = PREVIEWS_DIR / f"tpl_{marca.slug}_{template_id}_{clave}.png"
    if destino.exists():
        return destino

    campos = campos_de_muestra(ct)
    foto = _foto_muestra(marca.slug)
    if foto:
        campos["imagen"] = foto
    _render.render(cx, marca, tpl, campos, out_path=destino)

    # Previews viejos de la MISMA plantilla: fuera. El sufijo debe ser
    # EXACTAMENTE un hash (12 hex): así "tpl_x_1_..." no borra "tpl_x_10_...".
    patron = re.compile(
        rf"^tpl_{re.escape(marca.slug)}_{template_id}_[0-9a-f]{{12}}\.png$")
    for viejo in PREVIEWS_DIR.iterdir():
        if viejo != destino and patron.match(viejo.name):
            viejo.unlink(missing_ok=True)
    return destino
