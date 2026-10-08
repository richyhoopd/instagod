"""Biblioteca de assets por marca (editor v2): búsqueda en proveedores, import al
disco de la marca, recorte de fondo. Paralelo a src/image_sources.py (slideshow v1),
que no se toca."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

import config
from src import image_sources

TIPOS = ("imagen", "video")
# Módulo-nivel para que las pruebas lo monkeypatcheen (mismo patrón que perfil.BRANDS_DIR).
# Los submódulos lo leen como `assets.BRANDS_DIR` en tiempo de llamada, nunca lo copian.
BRANDS_DIR = image_sources.BRANDS_DIR
CACHE_DIR = config.BASE_DIR / "data" / "cache" / "assets"


# Fotos sueltas en brands/<slug>/fotos (v1): una sola definición, la importan carpeta y biblioteca.
# Mismo patrón que api/routers/brands.py (_SLUG_RE).
SLUG_RE = re.compile(r"^[a-z0-9_]{2,32}\Z")
EXT_FOTO = frozenset({".jpg", ".jpeg", ".png", ".webp"})
NOMBRE_FOTO_RE = re.compile(r"^[a-z0-9_.-]+\Z")


@dataclass
class Candidata:
    proveedor: str
    id_origen: str
    tipo: str          # "imagen" | "video"
    url: str
    preview_url: str
    ancho: int | None
    alto: int | None
    autor: str | None
    licencia: str | None
    url_origen: str | None
    ig_handle: str | None = None
    source_post_id: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)
