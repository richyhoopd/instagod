from __future__ import annotations

from pathlib import Path

import pytest

from src import db


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_migracion_crea_personas_y_firmas(cx) -> None:
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"personas", "face_signatures"} <= tablas
    assert "persona_id" in {r["name"] for r in cx.execute("PRAGMA table_info(photos)")}
    # Sin registro en TABLES, db.insert las rechaza.
    assert "personas" in db.TABLES and "face_signatures" in db.TABLES
    assert "persona_id" in db.TABLES["photos"]


def test_migracion_es_idempotente(cx) -> None:
    db.init_db(cx)
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    assert db.get(cx, "personas", pid)["band_id"] == bid
