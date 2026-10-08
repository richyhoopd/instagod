"""Quitar fondo con rembg + BiRefNet (CPU). rembg se importa dentro de la función y la
sesión se carga una vez por proceso: importar este módulo no carga onnxruntime. El modelo
se descarga en el build de la imagen (Dockerfile: `new_session("birefnet-general")`,
REMBG_HOME=/opt/rembg; rembg 2.0.85 lee REMBG_HOME en sessions/base.py:169)."""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

from PIL import Image

MODELO = "birefnet-general"
MAX_PIXELES = 40_000_000   # tope propio: rembg y Pillow duplican el buffer varias veces
MSG_FALLO = "no se pudo recortar la imagen"
_sesion = None


class RembgNoInstalado(RuntimeError):
    pass


def _remover_real(datos: bytes) -> bytes:
    global _sesion
    try:
        from rembg import new_session, remove
    except ImportError as e:
        raise RembgNoInstalado("rembg no instalado: el recorte de fondo no está disponible") from e
    if _sesion is None:
        _sesion = new_session(MODELO)
    return remove(datos, session=_sesion)


# Punto de sustitución en pruebas.
_remover = _remover_real


def quitar_fondo(origen: Path, destino: Path) -> Path:
    """PNG RGBA recortado al bbox del alfa. ValueError (mensajes sin rutas) si el origen
    falta, es ilegible o demasiado grande, o si no queda nada."""
    origen = Path(origen)
    if not origen.is_file():
        raise ValueError("archivo del asset no encontrado")
    try:
        with Image.open(origen) as im:   # perezoso: solo la cabecera
            ancho, alto = im.size
    except Exception as e:
        raise ValueError(MSG_FALLO) from e
    if ancho * alto > MAX_PIXELES:
        raise ValueError("imagen demasiado grande para recortar")
    try:
        salida = _remover(origen.read_bytes())
        with Image.open(io.BytesIO(salida)) as im:
            rgba = im.convert("RGBA")
    except RembgNoInstalado:
        raise
    except Exception as e:
        raise ValueError(MSG_FALLO) from e
    caja = rgba.getchannel("A").getbbox()
    if caja is None:
        raise ValueError("el recorte quedó vacío")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_nombre = tempfile.mkstemp(dir=destino.parent, prefix=destino.name + ".",
                                      suffix=".part")
    tmp = Path(tmp_nombre)
    try:
        with os.fdopen(fd, "wb") as f:
            rgba.crop(caja).save(f, "PNG")
        os.replace(tmp, destino)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return destino
