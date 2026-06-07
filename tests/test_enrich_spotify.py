"""Tests de Fase 4: lógica pura del match de Spotify (sin red)."""
from __future__ import annotations

from datetime import datetime, timedelta

import config
from src.enrich_spotify import artist_id_de_link, elegir_match, es_release_reciente


def test_artist_id_de_link() -> None:
    assert artist_id_de_link("https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb") \
        == "4Z8W4fKeB5YxbusRsdQVPb"
    assert artist_id_de_link("https://open.spotify.com/intl-es/artist/4Z8W4fKeB5Yx?si=x") \
        == "4Z8W4fKeB5Yx"
    assert artist_id_de_link("https://beacons.ai/kabala") is None
    assert artist_id_de_link(None) is None


def test_elegir_match_prefiere_nombre_exacto() -> None:
    candidatos = [
        {"name": "Kabala Tribute", "id": "a"},
        {"name": "kabala ", "id": "b"},
        {"name": "Otra", "id": "c"},
    ]
    assert elegir_match("Kabala", candidatos)["id"] == "b"
    # sin exacto → el primero (orden de relevancia de Spotify)
    assert elegir_match("Los Baxters", candidatos)["id"] == "a"
    assert elegir_match("X", []) is None


def test_es_release_reciente() -> None:
    hoy = datetime(2026, 6, 4)
    dentro = (hoy - timedelta(days=config.SPOTIFY_RELEASE_DAYS - 1)).strftime("%Y-%m-%d")
    fuera = (hoy - timedelta(days=config.SPOTIFY_RELEASE_DAYS + 1)).strftime("%Y-%m-%d")
    assert es_release_reciente(dentro, hoy=hoy)
    assert not es_release_reciente(fuera, hoy=hoy)
    # precisión de solo año/mes (Spotify a veces da "2026" o "2026-06")
    assert es_release_reciente("2026-06", hoy=hoy)
    assert not es_release_reciente("2025", hoy=hoy)
    assert not es_release_reciente(None, hoy=hoy)
    assert not es_release_reciente("fecha-rara", hoy=hoy)
