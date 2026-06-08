"""Tests del pool de cuentas scraper de IG (sin red, reloj inyectado)."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from src import ig_accounts

AHORA = datetime(2026, 6, 8, 12, 0, 0)


def _escribir(path: Path, cuentas: list[dict]) -> None:
    path.write_text(json.dumps(cuentas), encoding="utf-8")


def test_cargar_desde_json(tmp_path) -> None:
    p = tmp_path / "ig_accounts.json"
    _escribir(p, [{"label": "a", "sessionid": "s1", "ua": "UA1"}])
    cuentas = ig_accounts.cargar(p)
    assert len(cuentas) == 1
    assert cuentas[0]["label"] == "a" and cuentas[0]["sessionid"] == "s1"


def test_cargar_fallback_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ig_accounts.config, "IG_SCRAPER_SESSIONID", "envsid")
    monkeypatch.setattr(ig_accounts.config, "IG_SCRAPER_UA", "envua")
    cuentas = ig_accounts.cargar(tmp_path / "noexiste.json")
    assert len(cuentas) == 1
    assert cuentas[0]["sessionid"] == "envsid" and cuentas[0]["label"] == "env"


def test_cargar_vacio_sin_nada(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ig_accounts.config, "IG_SCRAPER_SESSIONID", None)
    monkeypatch.setattr(ig_accounts.config, "IG_SCRAPER_UA", None)
    assert ig_accounts.cargar(tmp_path / "noexiste.json") == []


def test_siguiente_sana_salta_quemadas() -> None:
    cuentas = [
        {"label": "a", "quemada_hasta": "2026-06-08T20:00:00"},  # futura → quemada
        {"label": "b", "quemada_hasta": "2026-06-08T06:00:00"},  # pasada → sana
        {"label": "c", "quemada_hasta": None},                   # nunca → sana
    ]
    assert ig_accounts.siguiente_sana(cuentas, ahora=AHORA)["label"] == "b"


def test_siguiente_sana_todas_quemadas() -> None:
    cuentas = [{"label": "a", "quemada_hasta": "2026-06-08T23:00:00"}]
    assert ig_accounts.siguiente_sana(cuentas, ahora=AHORA) is None


def test_marcar_quemada_persiste(tmp_path) -> None:
    p = tmp_path / "ig_accounts.json"
    _escribir(p, [{"label": "a", "sessionid": "s", "ua": "u", "quemada_hasta": None},
                  {"label": "b", "sessionid": "s2", "ua": "u2", "quemada_hasta": None}])
    ig_accounts.marcar_quemada("a", horas=12, path=p, ahora=AHORA)
    cuentas = {c["label"]: c for c in ig_accounts.cargar(p)}
    assert cuentas["a"]["quemada_hasta"] == "2026-06-09T00:00:00"  # +12h
    assert cuentas["b"]["quemada_hasta"] is None  # no toca a las demás


def test_marcar_quemada_default_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ig_accounts.config, "SCRAPER_COOLDOWN_HORAS", 6)
    p = tmp_path / "ig_accounts.json"
    _escribir(p, [{"label": "a", "sessionid": "s", "ua": "u", "quemada_hasta": None}])
    ig_accounts.marcar_quemada("a", path=p, ahora=AHORA)
    assert ig_accounts.cargar(p)[0]["quemada_hasta"] == "2026-06-08T18:00:00"  # +6h
