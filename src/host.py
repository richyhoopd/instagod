"""Hosting público de imágenes en Cloudinary.

Instagram Graph API exige un `image_url` público al publicar; subimos el PNG
compuesto a Cloudinary y devolvemos su URL `https://res.cloudinary.com/...`.
"""
from __future__ import annotations

from pathlib import Path

import cloudinary
import cloudinary.uploader

import config

_configured = False


def _ensure_config() -> None:
    global _configured
    if _configured:
        return
    if not (config.CLOUD_NAME and config.CLOUDINARY_API_KEY and config.CLOUDINARY_API_SECRET):
        raise RuntimeError("Faltan credenciales de Cloudinary en el .env")
    cloudinary.config(
        cloud_name=config.CLOUD_NAME,
        api_key=config.CLOUDINARY_API_KEY,
        api_secret=config.CLOUDINARY_API_SECRET,
        secure=True,
    )
    _configured = True


def upload(image_path: str | Path, public_id: str | None = None) -> str:
    """Sube la imagen y devuelve la URL pública (secure_url), SIEMPRE como JPEG.

    La Content Publishing API de IG solo acepta JPEG: un carrusel con PNGs
    falla con "Media URI doesn't meet our requirements" (code 9004). Cloudinary
    transcodifica al subir con format="jpg".
    """
    _ensure_config()
    result = cloudinary.uploader.upload(
        str(image_path),
        folder="gdlscene",
        public_id=public_id,
        overwrite=True,
        resource_type="image",
        format="jpg",
    )
    return result["secure_url"]
