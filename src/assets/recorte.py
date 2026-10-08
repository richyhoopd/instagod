"""Quitar fondo con rembg + BiRefNet (CPU). rembg se importa dentro de la función y la
sesión se carga una vez por proceso: importar este módulo no carga onnxruntime. El modelo
se descarga en el build de la imagen (Dockerfile: `rembg d birefnet-general`,
REMBG_HOME=/opt/rembg; rembg 2.0.85 lee REMBG_HOME en sessions/base.py:169)."""
from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image

MODELO = "birefnet-general"
_sesion = None


def _remover_real(datos: bytes) -> bytes:
    global _sesion
    try:
        from rembg import new_session, remove
    except ImportError as e:
        raise RuntimeError("rembg no instalado: el recorte de fondo no está disponible") from e
    if _sesion is None:
        _sesion = new_session(MODELO)
    return remove(datos, session=_sesion)


# Punto de sustitución en pruebas.
_remover = _remover_real


def quitar_fondo(origen: Path, destino: Path) -> Path:
    """PNG RGBA recortado al bbox del alfa. ValueError si no queda nada."""
    salida = _remover(Path(origen).read_bytes())
    with Image.open(io.BytesIO(salida)) as im:
        rgba = im.convert("RGBA")
    caja = rgba.getchannel("A").getbbox()
    if caja is None:
        raise ValueError("el recorte quedó vacío")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    rgba.crop(caja).save(tmp, "PNG")
    os.replace(tmp, destino)
    return destino
