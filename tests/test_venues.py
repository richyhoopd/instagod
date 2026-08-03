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


def test_migracion_crea_venues_y_alias(cx) -> None:
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"venues", "venue_alias"} <= tablas
    assert "venue_id" in {r["name"] for r in cx.execute("PRAGMA table_info(events)")}
    assert "venues" in db.TABLES and "venue_alias" in db.TABLES
    assert "venue_id" in db.TABLES["events"]


def test_alias_norm_es_unico(cx) -> None:
    import sqlite3
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    db.insert(cx, "venue_alias", venue_id=vid, alias_norm="hake al rey",
              alias_visto="Hake al Rey", origen="semilla")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "venue_alias", venue_id=vid, alias_norm="hake al rey",
                  alias_visto="HAKE AL REY", origen="llm")


def test_migracion_es_idempotente(cx) -> None:
    db.init_db(cx)
    db.init_db(cx)
    vid = db.insert(cx, "venues", nombre="Cuerda", ciudad="Guadalajara")
    assert db.get(cx, "venues", vid)["nombre"] == "Cuerda"
