"""Hosting público de media en Cloudinary.

Instagram Graph API exige una URL pública al publicar (`image_url` para
imágenes, `video_url` para Reels); subimos el archivo local a Cloudinary y
devolvemos su URL `https://res.cloudinary.com/...`.
"""
from __future__ import annotations

from pathlib import Path

import cloudinary
import cloudinary.uploader

import config

_configured = False
# Reels de 60 s pesan decenas de MB. La subida síncrona de un archivo así se
# queda colgada sin error ni tráfico (verificado en vivo: 10 min, 0% CPU y
# cero conexiones abiertas con mp4 de ~60 MB), así que el umbral va bajo y
# casi todo reel entra por upload_large (chunked, con reintento por trozo).
_CHUNK_UMBRAL = 20 * 1024 * 1024
_CHUNK_SIZE = 6 * 1024 * 1024
# Sin timeout explícito el SDK espera para siempre: mejor fallar y reintentar.
_TIMEOUT_S = 600


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


def upload_video(video_path: str | Path, public_id: str | None = None) -> str:
    """Sube el mp4 y devuelve la URL pública (secure_url) para `video_url`.

    `resource_type="video"` (no "image": Cloudinary rechaza el mp4 como
    imagen) y SIN `format=`: el mp4 que produce `video_render` ya cumple el
    perfil de Reels (H.264/AAC, yuv420p, faststart) y transcodificar otra vez
    solo degrada. Archivos grandes van por `upload_large` (chunked), porque la
    subida síncrona se corta con reels largos.
    """
    _ensure_config()
    ruta = Path(video_path)
    opciones = dict(folder="gdlscene", public_id=public_id, overwrite=True,
                    resource_type="video", timeout=_TIMEOUT_S)
    if ruta.stat().st_size > _CHUNK_UMBRAL:
        result = cloudinary.uploader.upload_large(
            str(ruta), chunk_size=_CHUNK_SIZE, **opciones)
    else:
        result = cloudinary.uploader.upload(str(ruta), **opciones)
    url = (result or {}).get("secure_url")
    if not url:
        raise RuntimeError(f"Cloudinary no devolvió secure_url para {ruta.name}")
    return url
