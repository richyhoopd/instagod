"""Fase A multi-cuenta: tabla accounts, seed gdlscene, FKs con default 1."""
from __future__ import annotations

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_seed_gdlscene_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # segunda corrida: no duplica
    cuentas = db.rows(cx, "SELECT * FROM accounts")
    assert len(cuentas) == 1
    assert cuentas[0]["id"] == 1 and cuentas[0]["slug"] == "gdlscene"
    assert cuentas[0]["ciudad"] == "Guadalajara"


def test_bands_caen_en_gdlscene(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    fila = db.rows(cx, "SELECT account_id FROM bands WHERE id = ?", (bid,))[0]
    assert fila["account_id"] == 1


def test_queue_e_igposts_tienen_account_id(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="meme")
    assert db.rows(cx, "SELECT account_id FROM content_queue WHERE id=?", (qid,))[0]["account_id"] == 1
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(ig_posts)")}
    assert "account_id" in cols


def test_helpers_accounts(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="cdmxscene", ig_handle="cdmxscene",
              nombre="La Escena CDMX", ciudad="CDMX", activa=0)
    assert [a["slug"] for a in db.list_accounts(cx)] == ["gdlscene"]
    assert [a["slug"] for a in db.list_accounts(cx, solo_activas=False)] == ["gdlscene", "cdmxscene"]
    assert db.get_account(cx, "cdmxscene")["nombre"] == "La Escena CDMX"
    assert db.get_account(cx, "noexiste") is None


def test_account_creds_fallback_y_sufijo(monkeypatch) -> None:
    import config
    monkeypatch.setenv("IG_USER_ID", "base-user")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "base-token")
    monkeypatch.setenv("IG_ACCESS_TOKEN__CDMXSCENE", "cdmx-token")
    # gdlscene sin sufijo → cae a las vars base (compat con el .env actual)
    g = config.account_creds("gdlscene")
    assert g["IG_USER_ID"] == "base-user" and g["IG_ACCESS_TOKEN"] == "base-token"
    # otra cuenta: SOLO sufijo; lo que falte queda None (nunca hereda la base)
    c = config.account_creds("cdmxscene")
    assert c["IG_ACCESS_TOKEN"] == "cdmx-token"
    assert c["IG_USER_ID"] is None


def test_migracion_db_vieja(tmp_path) -> None:
    """Una DB creada antes de multi-cuenta gana account_id=1 al correr init_db.

    DB 'vieja' realista: lo que produce schema.sql SOLO (sin el loop de
    migraciones de init_db) — así nacieron todas las DBs reales.
    """
    import sqlite3
    vieja = tmp_path / "vieja.db"
    cx = sqlite3.connect(vieja)
    cx.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
    cx.execute("INSERT INTO bands (nombre) VALUES ('Vieja Banda')")
    cx.commit()
    cx.close()

    cx = db.connect(vieja)
    db.init_db(cx)
    fila = db.rows(cx, "SELECT account_id FROM bands WHERE nombre='Vieja Banda'")[0]
    assert fila["account_id"] == 1
    assert db.get_account(cx, "gdlscene") is not None
