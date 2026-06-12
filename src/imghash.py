"""pHash de imágenes (dHash 8×8) para detectar flyers visualmente iguales.

Compartido por generate_agenda (dedupe de shows al render) y
detect_releases_ig (dedupe cross-banda de releases en detección).
"""
from __future__ import annotations

from typing import Any


def phash(path) -> "Any | None":
    """Hash perceptual (dHash 8x8): 64 bits; None si la imagen no se puede leer."""
    import cv2
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    img = cv2.resize(img, (9, 8))
    return (img[:, 1:] > img[:, :-1]).flatten()


def es_duplicado(h, vistos, umbral: int = 8) -> bool:
    """True si h difiere en ≤ umbral bits de alguno de `vistos`."""
    import numpy as np
    return any(int(np.count_nonzero(h != v)) <= umbral for v in vistos)
