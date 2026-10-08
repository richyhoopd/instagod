"""brand_assets nueva y brand_sources.kind acepta 'video' (migración del CHECK)."""
from __future__ import annotations

import sqlite3

import pytest

from src import db

_DDL_VIEJO = """
CREATE TABLE brand_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL,
    provider     TEXT    NOT NULL,
    config_json  TEXT    NOT NULL DEFAULT '{}',
    activa       INTEGER NOT NULL DEFAULT 1,
    orden        INTEGER NOT NULL DEFAULT 0,
    ultimo_run   TEXT,
    ultimo_error TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (kind IN ('imagen','info')),
    CHECK (activa IN (0,1))
)
"""


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx, slug="m1") -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}", nombre=slug, ciudad="GDL")


def test_brand_assets_existe_y_dedup_por_sha(cx) -> None:
    aid = _cuenta(cx)
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="a.jpg",
              sha="s1", proveedor="pexels")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="b.jpg",
                  sha="s1", proveedor="pexels")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_assets", account_id=aid, tipo="audio", archivo="c.mp3",
                  sha="s2", proveedor="pexels")


def test_brand_sources_acepta_video_en_db_nueva(cx) -> None:
    aid = _cuenta(cx)
    sid = db.insert(cx, "brand_sources", account_id=aid, kind="video", provider="pexels")
    assert db.get(cx, "brand_sources", sid)["kind"] == "video"


def test_migracion_kind_video_conserva_filas(tmp_path) -> None:
    c = db.connect(tmp_path / "v.db")
    db.init_db(c)
    aid = _cuenta(c)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("DROP TABLE brand_sources")
    c.execute(_DDL_VIEJO)
    c.execute("CREATE INDEX idx_sources_account ON brand_sources(account_id)")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("INSERT INTO brand_sources (id, account_id, kind, provider, orden, ultimo_error) "
              "VALUES (7, ?, 'imagen', 'pexels', 2, 'x'), (9, ?, 'info', 'rss', 0, NULL)",
              (aid, aid))
    c.commit()
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO brand_sources (account_id, kind, provider) VALUES (?, 'video', 'p')",
                  (aid,))
    c.rollback()

    db.init_db(c)
    db.init_db(c)  # idempotente: la segunda corrida es no-op

    filas = [dict(f) for f in c.execute(
        "SELECT id, kind, provider, orden, ultimo_error FROM brand_sources ORDER BY id")]
    assert filas == [
        {"id": 7, "kind": "imagen", "provider": "pexels", "orden": 2, "ultimo_error": "x"},
        {"id": 9, "kind": "info", "provider": "rss", "orden": 0, "ultimo_error": None},
    ]
    nuevo = db.insert(c, "brand_sources", account_id=aid, kind="video", provider="pixabay")
    assert nuevo == 10
    sql = c.execute("SELECT sql FROM sqlite_master WHERE name='brand_sources'").fetchone()[0]
    assert "'video'" in sql
    idx = c.execute("SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='brand_sources'").fetchall()
    assert ("idx_sources_account",) in [tuple(i) for i in idx]
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()
