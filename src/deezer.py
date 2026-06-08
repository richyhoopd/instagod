"""Cliente de Deezer y registro de releases (fuente primaria, SIN auth).

La Spotify Web API murió como fuente de datos en 2026 (ver memoria/spec); Deezer
es la API pública de catálogo: sin token, sin premium, sin el cap de 23h. De aquí
salen los releases (discografía por artista con fecha y tipo). Spotify queda solo
para el link/embed.

Spec: docs/superpowers/specs/2026-06-08-deezer-releases-design.md
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import requests

import config
from src import db
from src.detect_releases_ig import _es_dupe

_TIMEOUT = 20


class DeezerError(RuntimeError):
    """La API de Deezer respondió error o no se pudo contactar."""


def _throttle() -> None:
    time.sleep(config.DEEZER_THROTTLE_S)


def _get(url: str, params: dict | None = None) -> requests.Response:
    return requests.get(url, params=params, timeout=_TIMEOUT)


def _json(url: str, params: dict | None = None) -> dict[str, Any]:
    resp = _get(url, params)
    if resp.status_code >= 400:
        raise DeezerError(f"Deezer HTTP {resp.status_code} en {url}")
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        raise DeezerError(f"Deezer error: {data['error']}")
    return data


def buscar_artista(nombre: str) -> list[dict[str, Any]]:
    """Candidatos de artista por nombre (sin auth). Vacío si no hay match."""
    data = _json(f"{config.DEEZER_API_BASE}/search/artist", {"q": nombre})
    out = []
    for a in data.get("data", []):
        out.append({
            "id": str(a["id"]),
            "nombre": a.get("name", ""),
            "nb_album": a.get("nb_album"),
            "nb_fan": a.get("nb_fan"),
            "link": a.get("link", ""),
            "picture": a.get("picture_xl") or a.get("picture_big") or "",
        })
    return out


def albums(artist_id: str) -> list[dict[str, Any]]:
    """Discografía completa del artista (paginada por `next`)."""
    url = f"{config.DEEZER_API_BASE}/artist/{artist_id}/albums"
    out: list[dict[str, Any]] = []
    while url:
        data = _json(url)
        for al in data.get("data", []):
            out.append({
                "album_id": str(al["id"]),
                "titulo": al.get("title", ""),
                "record_type": al.get("record_type"),  # album|ep|single
                "release_date": al.get("release_date"),  # YYYY-MM-DD
                "cover_url": al.get("cover_xl") or al.get("cover_big") or "",
            })
        url = data.get("next")
        if url:
            _throttle()
    return out


def registrar_releases(cx, band_id: int, deezer_id: str,
                       hoy: datetime | None = None) -> list[dict[str, Any]]:
    """Inserta en `events` los releases recientes de la banda. Devuelve los nuevos.

    Ventana: SPOTIFY_RELEASE_DAYS. Dedup vs lo que ya exista (Spotify `sp:`, IG
    `ig:` o el propio `dz:`) por title+fecha cercanos — gana el que ya esté.
    """
    hoy = hoy or datetime.now()
    nuevos: list[dict[str, Any]] = []
    for al in albums(deezer_id):
        fecha = al.get("release_date")
        if not _reciente(fecha, hoy):
            continue
        spid = f"dz:{al['album_id']}"
        if _es_dupe(cx, band_id, spid, al["titulo"], fecha):
            continue
        db.insert(cx, "events", band_id=band_id, tipo="release",
                  titulo=al["titulo"], fecha_evento=fecha,
                  cover_url=al.get("cover_url") or None,
                  source_post_id=spid, status="nuevo")
        nuevos.append(al)
    return nuevos


def _reciente(fecha: str | None, hoy: datetime) -> bool:
    if not fecha:
        return False
    try:
        d = datetime.strptime(str(fecha)[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return 0 <= (hoy - d).days <= config.SPOTIFY_RELEASE_DAYS
