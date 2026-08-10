"""Sourcing de imágenes multi-fuente para slideshows.

Protocolo: un provider tiene .nombre y .buscar(hint, n) -> [ImagenCandidata].
resolver() recorre las fuentes en el orden del brief con fallback en cascada
y nunca repite la misma imagen dentro de un set. Un provider que falla
devuelve [] (o su excepción se traga aquí): el set nunca truena por sourcing.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

import config
from src import covers, db

SOURCING_DIR = config.BASE_DIR / "data" / "sourcing"

# Bytes mágicos aceptados (JPEG, PNG, WEBP/RIFF).
_MAGIA = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF")


@dataclass
class ImagenCandidata:
    ruta_o_url: str            # path local o URL https
    source: str                # "banco"|"covers"|"pexels"|"pinterest"|"manual"
    credito: str | None = None


def _descargar_cache(url: str) -> Path | None:
    """Descarga con cache en data/sourcing/<sha1[:16]>.jpg. None si falla."""
    SOURCING_DIR.mkdir(parents=True, exist_ok=True)
    destino = SOURCING_DIR / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
    if destino.exists():
        return destino
    try:
        r = requests.get(url, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 (Macintosh)"})
        r.raise_for_status()
    except requests.RequestException:
        return None
    data = r.content
    if not data or not data.startswith(_MAGIA):
        return None
    fd, tmp = tempfile.mkstemp(dir=str(SOURCING_DIR), suffix=".part")
    os.close(fd)  # solo queremos el nombre único
    Path(tmp).write_bytes(data)
    Path(tmp).rename(destino)  # escritura atómica
    return destino


class BancoProvider:
    """Fotos reales del banco propio: match del hint contra nombre/handle."""

    nombre = "banco"

    def __init__(self, cx):
        self.cx = cx

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        like = f"%{hint.strip()}%"
        filas = db.rows(self.cx, """
            SELECT p.path FROM photos p
            JOIN bands b ON b.id = p.band_id
            WHERE (b.nombre LIKE ? COLLATE NOCASE
                   OR b.ig_handle LIKE ? COLLATE NOCASE)
              AND p.usable_meme = 1 AND p.usada = 0 AND p.descartada = 0
            ORDER BY p.nitidez DESC LIMIT ?
        """, (like, like, n))
        return [ImagenCandidata(f["path"], "banco") for f in filas]


class CoversProvider:
    """Portadas de releases (events.cover_url) vía el cache anti-DNS de covers."""

    nombre = "covers"

    def __init__(self, cx):
        self.cx = cx

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        like = f"%{hint.strip()}%"
        filas = db.rows(self.cx, """
            SELECT e.cover_url, e.titulo FROM events e
            JOIN bands b ON b.id = e.band_id
            WHERE e.cover_url IS NOT NULL
              AND (e.titulo LIKE ? COLLATE NOCASE
                   OR b.nombre LIKE ? COLLATE NOCASE)
            ORDER BY e.fecha_evento DESC LIMIT ?
        """, (like, like, n))
        out = []
        for f in filas:
            ruta = covers.asegurar_cover(f["cover_url"])
            if ruta:
                out.append(ImagenCandidata(str(ruta), "covers", credito=f["titulo"]))
        return out


def providers_default(cx=None) -> dict:
    """Providers disponibles. banco/covers requieren conexión a la DB."""
    out: dict = {}
    if cx is not None:
        out["banco"] = BancoProvider(cx)
        out["covers"] = CoversProvider(cx)
    return out


def resolver(hints: list[str], fuentes: list[str], *, cx=None,
             providers: dict | None = None) -> list[ImagenCandidata | None]:
    """Una candidata (o None) por hint, sin repetir imagen dentro del set."""
    provs = providers if providers is not None else providers_default(cx)
    usadas: set[str] = set()
    out: list[ImagenCandidata | None] = []
    for hint in hints:
        elegida = None
        for fuente in fuentes:
            prov = provs.get(fuente)
            if prov is None:
                continue
            try:
                candidatas = prov.buscar(hint, n=4)
            except Exception as e:  # noqa: BLE001 — el set no truena por sourcing
                print(f"[image_sources] provider {fuente} falló: {e}")
                continue
            for c in candidatas:
                if c.ruta_o_url not in usadas:
                    elegida = c
                    break
            if elegida:
                break
        if elegida:
            usadas.add(elegida.ruta_o_url)
        out.append(elegida)
    return out
