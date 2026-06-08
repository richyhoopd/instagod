"""Tests de la vista /deezer (matcheo manual)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import db, deezer_match


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala", activa=1)
    cx.close()

    monkeypatch.setattr(deezer_match, "candidatos",
                        lambda cx, band_id: [{"id": "111", "nombre": "Kabala",
                                              "link": "https://deezer.com/artist/111",
                                              "nb_album": 2, "nb_fan": 9}])
    from web.app import app
    with TestClient(app) as c:
        c._bid = bid
        yield c


def test_deezer_view_lista_pendientes(client) -> None:
    r = client.get("/deezer")
    assert r.status_code == 200
    assert "Kabala" in r.text and "deezer.com/artist/111" in r.text


def test_deezer_elegir(client, monkeypatch) -> None:
    monkeypatch.setattr(deezer_match, "elegir", lambda cx, bid, did: None)
    r = client.post(f"/deezer/{client._bid}/elegir", data={"deezer_id": "111"})
    assert r.status_code == 200


def test_deezer_no_esta(client) -> None:
    r = client.post(f"/deezer/{client._bid}/no-esta")
    assert r.status_code == 200
    cx = db.connect()
    assert cx.execute("SELECT deezer_status FROM bands WHERE id=?",
                      (client._bid,)).fetchone()["deezer_status"] == "no_esta"
    cx.close()


def test_deezer_resolver_auto(client, monkeypatch) -> None:
    llamado = {}

    def fake(cx):
        llamado["si"] = True
        return {"revisadas": 1, "ok": 1, "dudosas": 0}

    monkeypatch.setattr(deezer_match, "resolver_auto", fake)
    r = client.post("/deezer/resolver-auto")
    assert r.status_code in (200, 303)
    assert llamado.get("si")
