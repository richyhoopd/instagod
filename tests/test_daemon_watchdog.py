"""Tests del watchdog: decide reiniciar según el latido, sin tocar launchctl real."""
from datetime import datetime, timedelta

import pytz

from src import daemon_health, daemon_watchdog

TZ = pytz.timezone("America/Mexico_City")


def _ahora():
    return TZ.localize(datetime(2026, 7, 14, 12, 0, 0))


def test_no_actua_si_latido_fresco(monkeypatch):
    fresco = (_ahora() - timedelta(seconds=30)).isoformat()
    monkeypatch.setattr(daemon_health, "leer_latido", lambda **k: fresco)
    llamado = {"kick": False}
    monkeypatch.setattr(daemon_watchdog, "_kickstart", lambda: (llamado.__setitem__("kick", True), ("", ""))[1])
    assert daemon_watchdog.revisar(ahora=_ahora()) is False
    assert llamado["kick"] is False


def test_reinicia_si_latido_viejo(monkeypatch):
    viejo = (_ahora() - timedelta(seconds=600)).isoformat()
    monkeypatch.setattr(daemon_health, "leer_latido", lambda **k: viejo)
    kicks = {"n": 0}
    monkeypatch.setattr(daemon_watchdog, "_kickstart", lambda: (kicks.__setitem__("n", kicks["n"] + 1), (True, ""))[1])
    avisos = []
    monkeypatch.setattr(daemon_watchdog, "_avisar", lambda t: avisos.append(t))
    assert daemon_watchdog.revisar(ahora=_ahora()) is True
    assert kicks["n"] == 1
    assert avisos and "approval-daemon" in avisos[0]


def test_reinicia_si_latido_ausente(monkeypatch):
    monkeypatch.setattr(daemon_health, "leer_latido", lambda **k: None)
    kicks = {"n": 0}
    monkeypatch.setattr(daemon_watchdog, "_kickstart", lambda: (kicks.__setitem__("n", kicks["n"] + 1), (True, ""))[1])
    monkeypatch.setattr(daemon_watchdog, "_avisar", lambda t: None)
    assert daemon_watchdog.revisar(ahora=_ahora()) is True
    assert kicks["n"] == 1


def test_dry_run_no_reinicia(monkeypatch):
    monkeypatch.setattr(daemon_health, "leer_latido", lambda **k: None)
    kicks = {"n": 0}
    monkeypatch.setattr(daemon_watchdog, "_kickstart", lambda: (kicks.__setitem__("n", kicks["n"] + 1), (True, ""))[1])
    assert daemon_watchdog.revisar(dry_run=True, ahora=_ahora()) is True
    assert kicks["n"] == 0
