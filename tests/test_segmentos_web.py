"""Vista /segmentos de la GUI: estado del motor + preview de contenido."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)

    bid = db.insert(cx, "bands", nombre="Karacel", ig_handle="karacel", activa=1)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Naufragio",
              fecha_evento="2026-06-09", status="nuevo")
    db.insert(cx, "content_queue", tipo="anuncio", status="borrador",
              aprobacion="pendiente", caption="La agenda de la semana…",
              imagen_url='["https://x/1.png"]', tema_semilla="shows semanal pt1")
    cx.close()

    from web.app import app
    with TestClient(app) as c:
        yield c


def test_segmentos_lista_catalogo_y_preview(client) -> None:
    r = client.get("/segmentos")
    assert r.status_code == 200
    # los 4 segmentos del catálogo
    for nombre in ("Agenda — esta semana", "Agenda — este mes",
                   "Música nueva — semana", "Música nueva — mes"):
        assert nombre in r.text
    # preview de releases muestra el release fresco con su banda
    assert "Naufragio" in r.text
    # el pendiente de aprobación del segmento de shows aparece
    assert "La agenda de la semana…" in r.text
