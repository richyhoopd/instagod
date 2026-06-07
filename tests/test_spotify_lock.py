"""Lock de Spotify: exclusión entre procesos, locks muertos se roban."""
from __future__ import annotations

import os

import pytest

from src.enrich_spotify import SpotifyOcupado, spotify_lock


def test_lock_exclusivo(tmp_path) -> None:
    lock = tmp_path / "s.lock"
    with spotify_lock(lock):
        with pytest.raises(SpotifyOcupado):
            with spotify_lock(lock):
                pass
    # al salir se libera
    with spotify_lock(lock):
        pass


def test_lock_muerto_se_roba(tmp_path) -> None:
    lock = tmp_path / "s.lock"
    lock.write_text("99999999")  # pid que no existe
    with spotify_lock(lock):  # no debe levantar
        assert lock.read_text() == str(os.getpid())
