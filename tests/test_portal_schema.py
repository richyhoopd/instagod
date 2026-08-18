"""Tablas del portal (users, membresías, magic links, sesiones, secretos)."""
from __future__ import annotations

import sqlite3

import pytest

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_tablas_existen_y_init_es_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # segunda vez: no truena
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "brand_members", "magic_links", "sessions",
            "brand_secrets"} <= tablas


def test_email_unico_y_rol_valido(tmp_path) -> None:
    cx = _cx(tmp_path)
    uid = db.insert(cx, "users", email="a@x.com", nombre="A")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "users", email="a@x.com", nombre="dup")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_members", user_id=uid, account_id=1, rol="dios")
    db.insert(cx, "brand_members", user_id=uid, account_id=1, rol="editor")


def test_secretos_pk_compuesta(tmp_path) -> None:
    cx = _cx(tmp_path)
    cx.execute("INSERT INTO brand_secrets(account_id, clave, valor_cifrado) "
               "VALUES (1, 'IG_USER_ID', 'x')")
    with pytest.raises(sqlite3.IntegrityError):
        cx.execute("INSERT INTO brand_secrets(account_id, clave, valor_cifrado) "
                   "VALUES (1, 'IG_USER_ID', 'y')")
