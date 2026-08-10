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


def _nombre_en_hint(nombre: str | None, hint: str) -> bool:
    """¿El nombre de la banda aparece como palabra dentro del hint? PURO.

    Nombres de <4 chars se descartan para no matchear por substring accidental
    ("edu" dentro de "education").
    """
    nom = (nombre or "").strip().lower()
    if len(nom) < 4:
        return False
    return f" {nom} " in f" {hint.strip().lower()} "


class BancoProvider:
    """Fotos reales del banco propio: match del hint contra nombre/handle.

    LIMITACIÓN v1: las fotos elegidas para slideshows NO se marcan `usada`
    (eso solo pasa con memes vía approval.aprobar, que marca el photo_id
    único del meme); la anti-repetición solo aplica dentro de un mismo set
    (dedup de resolver()). Consecuencia: la misma foto top-nitidez de un
    hint puede volver a elegirse en cada slideshow futuro. El contrato
    slideshow_json ya persiste ruta y source de cada slide, así que un
    marcado retroactivo es posible; el fix real llega con multi-cuenta
    Fase B.
    """

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
        if filas:
            return [ImagenCandidata(f["path"], "banco") for f in filas]
        # Dirección inversa: los hints del LLM traen el sujeto + contexto
        # ("kabala band on stage") — matchear cuando el NOMBRE/handle de la
        # banda está contenido como palabra dentro del hint.
        bandas = db.rows(self.cx, "SELECT id, nombre, ig_handle FROM bands")
        ids = [b["id"] for b in bandas
               if _nombre_en_hint(b["nombre"], hint)
               or _nombre_en_hint(b["ig_handle"], hint)]
        if not ids:
            return []
        marcas = ",".join("?" * len(ids))
        filas = db.rows(self.cx, f"""
            SELECT p.path FROM photos p
            WHERE p.band_id IN ({marcas})
              AND p.usable_meme = 1 AND p.usada = 0 AND p.descartada = 0
            ORDER BY p.nitidez DESC LIMIT ?
        """, (*ids, n))
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


class PexelsProvider:
    """Búsqueda en Pexels (API oficial, licencia limpia para uso comercial)."""

    nombre = "pexels"

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        if not config.PEXELS_API_KEY:
            return []
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": hint, "per_page": n, "orientation": "portrait"},
                headers={"Authorization": config.PEXELS_API_KEY},
                timeout=20,
            )
            r.raise_for_status()
            fotos = r.json().get("photos", [])
        except (requests.RequestException, ValueError) as e:
            print(f"[image_sources] pexels falló: {e}")
            return []
        out = []
        for f in fotos[:n]:
            url = (f.get("src") or {}).get("large2x") or (f.get("src") or {}).get("large")
            if not url:
                continue
            ruta = _descargar_cache(url)
            if ruta:
                out.append(ImagenCandidata(str(ruta), "pexels",
                                           credito=f.get("photographer")))
        return out


class PinterestProvider:
    """Búsqueda en Pinterest vía su endpoint JSON interno (SIN API oficial).

    Best-effort detrás del flag SOURCING_PINTEREST: cualquier fallo apaga el
    provider por el resto de la corrida (circuit breaker) y la cascada cae al
    siguiente (pexels). Las imágenes pueden tener copyright de terceros: la
    proveniencia queda marcada (source="pinterest") para auditar/bajar.
    """

    nombre = "pinterest"

    def __init__(self):
        self._muerto = False

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        if not config.SOURCING_PINTEREST or self._muerto:
            return []
        import json as json_mod
        try:
            r = requests.get(
                "https://www.pinterest.com/resource/BaseSearchResource/get/",
                params={
                    "source_url": f"/search/pins/?q={hint}",
                    "data": json_mod.dumps(
                        {"options": {"query": hint, "scope": "pins"}, "context": {}}),
                },
                headers={
                    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/126.0 Safari/537.36"),
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=20,
            )
            r.raise_for_status()
            resultados = (r.json().get("resource_response", {})
                          .get("data", {}).get("results", []))
            out = []
            for res in resultados:
                url = ((res.get("images") or {}).get("orig") or {}).get("url")
                if not url:
                    continue
                ruta = _descargar_cache(url)
                if ruta:
                    out.append(ImagenCandidata(str(ruta), "pinterest"))
                if len(out) >= n:
                    break
        except (requests.RequestException, ValueError, AttributeError, TypeError) as e:
            print(f"[image_sources] pinterest falló, se apaga esta corrida: {e}")
            self._muerto = True
            return []
        return out


def providers_default(cx=None) -> dict:
    """Providers disponibles. banco/covers requieren conexión a la DB."""
    out: dict = {}
    if cx is not None:
        out["banco"] = BancoProvider(cx)
        out["covers"] = CoversProvider(cx)
    out["pexels"] = PexelsProvider()
    out["pinterest"] = PinterestProvider()
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
