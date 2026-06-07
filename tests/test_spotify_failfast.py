"""Ante 429, enrich corta la corrida con mensaje en vez de colgarse."""
from __future__ import annotations

import pytest
from spotipy import SpotifyException

from src.enrich_spotify import RateLimitado, _checar_429


def test_checar_429_convierte_y_lee_retry_after() -> None:
    exc = SpotifyException(429, -1, "rate", headers={"Retry-After": "120"})
    try:
        _checar_429(exc)
        raise AssertionError("debió levantar RateLimitado")
    except RateLimitado as rl:
        assert rl.retry_after == 120


def test_checar_429_ignora_otros_errores() -> None:
    exc = SpotifyException(404, -1, "not found", headers={})
    _checar_429(exc)  # no levanta: el caller decide qué hacer con el 404


def test_checar_429_sin_retry_after() -> None:
    exc = SpotifyException(429, -1, "rate", headers={})
    with pytest.raises(RateLimitado) as ri:
        _checar_429(exc)
    assert ri.value.retry_after is None
