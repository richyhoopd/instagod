"""Tests de la página /publicado: render, asignar banda y aplicar prioridad."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import db, ig_insights


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)

    bid = db.insert(cx, "bands", nombre="Noisy Room", prioridad=2)
    pid = ig_insights.upsert_post(cx, {
        "id": "M1", "media_type": "IMAGE", "media_url": "https://cdn.example/m1.jpg",
        "permalink": "https://instagram.com/p/M1/", "caption": "hola",
        "timestamp": "2026-06-01T19:00:00+0000", "like_count": 12, "comments_count": 3,
    })
    db.update(cx, "ig_posts", pid, band_id=bid)
    ig_insights.upsert_post(cx, {  # post manual sin banda
        "id": "M2", "media_type": "IMAGE", "media_url": "https://cdn.example/m2.jpg",
        "permalink": "https://instagram.com/p/M2/", "caption": "viejo",
        "timestamp": "2026-05-01T19:00:00+0000", "like_count": 5, "comments_count": 0,
    })
    cx.close()

    from web.app import app
    with TestClient(app) as c:
        c._band_id = bid  # type: ignore[attr-defined]
        c._post_id = pid  # type: ignore[attr-defined]
        yield c


def test_publicado_renderiza(client) -> None:
    resp = client.get("/publicado")
    assert resp.status_code == 200
    assert "Noisy Room" in resp.text          # resumen y/o card
    assert "instagram.com/p/M1" in resp.text  # link al post


def test_asignar_banda_a_post_manual(client) -> None:
    cx = db.connect()
    pid = cx.execute("SELECT id FROM ig_posts WHERE media_id='M2'").fetchone()["id"]
    cx.close()
    resp = client.post(f"/publicado/{pid}/banda", data={"band_id": client._band_id})
    assert resp.status_code == 200
    cx = db.connect()
    assert cx.execute("SELECT band_id FROM ig_posts WHERE id=?",
                      (pid,)).fetchone()["band_id"] == client._band_id
    cx.close()


def test_aplicar_prioridad_sugerida(client) -> None:
    resp = client.post(f"/publicado/banda/{client._band_id}/prioridad",
                       data={"prioridad": 1})
    assert resp.status_code == 200
    cx = db.connect()
    assert cx.execute("SELECT prioridad FROM bands WHERE id=?",
                      (client._band_id,)).fetchone()["prioridad"] == 1
    cx.close()


def test_sync_endpoint_usa_sync_posts(client, monkeypatch) -> None:
    llamado = {}

    def fake_sync(cx):
        llamado["si"] = True
        return {"posts": 2, "insights_fallidos": 0, "vinculados": 1, "warning": None}

    monkeypatch.setattr(ig_insights, "sync_posts", fake_sync)
    resp = client.post("/publicado/sync")
    assert resp.status_code == 200
    assert llamado.get("si")
