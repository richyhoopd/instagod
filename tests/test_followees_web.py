"""Tests del endpoint /followees/sync (importar seguidas de IG como candidatas)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import db, import_followees
from src.ingest_ig import IngestRateLimited


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    from web.app import app
    with TestClient(app) as c:
        yield c


def test_sync_reporta_nuevas(client, monkeypatch) -> None:
    monkeypatch.setattr(import_followees, "importar",
                        lambda *a, **k: {"nuevas": 5, "ya": 97, "total": 102})
    resp = client.post("/followees/sync")
    assert resp.status_code == 200
    assert "5" in resp.text and "candidatas nuevas" in resp.text
    assert "/bandas?todas=1" in resp.text


def test_sync_sin_nuevas(client, monkeypatch) -> None:
    monkeypatch.setattr(import_followees, "importar",
                        lambda *a, **k: {"nuevas": 0, "ya": 97, "total": 97})
    resp = client.post("/followees/sync")
    assert resp.status_code == 200
    assert "Sin cuentas nuevas" in resp.text


def test_sync_rate_limited_avisa(client, monkeypatch) -> None:
    def _boom(*a, **k):
        raise IngestRateLimited("HTTP 429 listando following")

    monkeypatch.setattr(import_followees, "importar", _boom)
    resp = client.post("/followees/sync")
    assert resp.status_code == 200
    assert "IG limitó la sesión" in resp.text


def test_importar_inserta_candidatas_y_es_idempotente(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    cx = db.connect()
    db.init_db(cx)
    db.insert(cx, "bands", nombre="Ya Existe", ig_handle="ya_existe", activa=1)
    cx.close()

    monkeypatch.setattr(import_followees, "_listar_con_pool", lambda cuenta, lim: [
        {"username": "ya_existe", "full_name": "Ya Existe"},
        {"username": "banda_nueva", "full_name": "Banda Nueva"},
    ])

    r = import_followees.importar()
    assert r == {"nuevas": 1, "ya": 1, "total": 2}

    cx = db.connect()
    fila = db.rows(cx, "SELECT * FROM bands WHERE ig_handle = 'banda_nueva'")[0]
    cx.close()
    assert fila["activa"] == 0
    assert "candidata" in fila["notas"]
