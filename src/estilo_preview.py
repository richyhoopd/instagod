"""Miniaturas de estilos de marca para la GUI /slideshows.

png_de() renderiza UN slide de muestra (hook, texto fijo) con el preset real
y lo cachea en data/previews/ con el hash del preset en el nombre: editar el
preset en /marcas invalida el cache solo (y borra la miniatura vieja).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image

import config
from src import compose, marcas
from src import slideshow_compile as sc
from src.image_sources import BRANDS_DIR, ImagenCandidata

PREVIEWS_DIR = config.BASE_DIR / "data" / "previews"
_ANCHO_MINIATURA = 360
_EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp"}

# Un guion mínimo: el hook es el slide más representativo del estilo.
_GUION_MUESTRA = {
    "tema": "muestra", "hook": "Así se ve este estilo",
    "caption": "", "cta": "Así se ve este estilo",
    "slides": [{"text": "Así se ve este estilo", "rol": "hook",
                "image_hint": "muestra"}],
}


def _foto_muestra(slug: str) -> str | None:
    """Primera foto del banco propio de la marca; None → fondo sólido."""
    raiz = BRANDS_DIR / slug / "fotos"
    if not raiz.is_dir():
        return None
    for p in sorted(raiz.rglob("*")):
        if p.is_file() and p.suffix.lower() in _EXT_FOTO:
            return str(p)
    return None


def png_de(cx, marca_slug: str, estilo: str) -> Path:
    """Ruta de la miniatura del estilo (la renderiza si no está en cache).

    KeyError si el estilo no existe para la marca (mismo contrato que
    compilar); ValueError si la marca no existe.
    """
    m = marcas.cargar(cx, marca_slug)
    catalogo = marcas.estilos_de(m)
    preset = catalogo[estilo]  # KeyError a propósito
    clave = hashlib.sha1(
        json.dumps(preset, sort_keys=True).encode()).hexdigest()[:12]
    PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    destino = PREVIEWS_DIR / f"{marca_slug}_{estilo}_{clave}.png"
    if destino.exists():
        return destino
    foto = _foto_muestra(marca_slug)
    imagenes = [ImagenCandidata(foto, "manual")] if foto else [None]
    show = sc.compilar(_GUION_MUESTRA, estilo=estilo, imagenes=imagenes,
                       estilos=catalogo, account_slug=marca_slug)
    ctx = sc.contexto_slide(show, 0)
    crudo = destino.with_suffix(".full.png")
    compose.render_card("slide.html", ctx, out_path=crudo)
    with Image.open(crudo) as img:
        alto = round(img.height * _ANCHO_MINIATURA / img.width)
        img.resize((_ANCHO_MINIATURA, alto)).save(destino)
    crudo.unlink(missing_ok=True)
    # Miniaturas de versiones anteriores del mismo estilo: fuera. El sufijo
    # debe ser EXACTAMENTE un hash (12 hex): así "marca_x" no borra "marca_x_bold".
    import re
    patron = re.compile(rf"^{re.escape(marca_slug)}_{re.escape(estilo)}_[0-9a-f]{{12}}\.png$")
    for viejo in PREVIEWS_DIR.iterdir():
        if viejo != destino and patron.match(viejo.name):
            viejo.unlink(missing_ok=True)
    return destino
