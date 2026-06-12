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
from src.detect_releases_ig import (
    _VENTANA_DIAS,
    _es_dupe,
    _normaliza_titulo,
    _parse_fecha,
    _titulos_similares,
)

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


def _album_para(titulo: str | None, fecha_evento: str | None,
                discografia: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Álbum con cover cuyo título coincide (normalizado) y fecha cae cerca."""
    norm = _normaliza_titulo(titulo)
    f_ev = _parse_fecha(fecha_evento)
    for al in discografia:
        if not al.get("cover_url"):
            continue
        if not _titulos_similares(norm, _normaliza_titulo(al.get("titulo"))):
            continue
        f_al = _parse_fecha(al.get("release_date"))
        # Mismo criterio que _es_dupe: sin fechas comparables, el título manda.
        if f_ev is None or f_al is None or abs((f_ev - f_al).days) <= _VENTANA_DIAS:
            return al
    return None


def mejorar_covers_ig(cx) -> int:
    """Releases con cover local (foto del post de IG) → artwork oficial de Deezer.

    detect_releases_ig guarda la foto del post como cover_url; aquí se reemplaza
    por la portada real cuando la discografía trae el mismo título con fecha
    cercana. Sin match no se toca nada (la foto de IG queda de fallback);
    flyer_path y source_post_id no cambian (GUI y dedupe siguen igual).
    """
    pend = db.rows(cx, """
        SELECT e.id, e.titulo, e.fecha_evento, b.deezer_id
          FROM events e JOIN bands b ON b.id = e.band_id
         WHERE e.tipo='release' AND b.deezer_id IS NOT NULL
           AND e.cover_url IS NOT NULL AND e.cover_url NOT LIKE 'http%'
    """)
    cache: dict[str, list[dict[str, Any]]] = {}
    n = 0
    for p in pend:
        did = p["deezer_id"]
        if did not in cache:
            try:
                cache[did] = albums(did)
            except DeezerError as exc:
                print(f"⚠ covers IG: Deezer falló para artista {did} ({exc})")
                cache[did] = []
        al = _album_para(p["titulo"], p["fecha_evento"], cache[did])
        if al:
            db.update(cx, "events", p["id"], cover_url=al["cover_url"])
            n += 1
    return n


def _reciente(fecha: str | None, hoy: datetime) -> bool:
    if not fecha:
        return False
    try:
        d = datetime.strptime(str(fecha)[:10], "%Y-%m-%d")
    except ValueError:
        return False
    return 0 <= (hoy - d).days <= config.SPOTIFY_RELEASE_DAYS
