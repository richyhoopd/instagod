"""Fase 3 (spec 2026-08-21): brand_sources, topic_suggestions y perfil
extendido de accounts (descripcion/sitio_web/hashtags_default/prompts_json)."""
from __future__ import annotations

import sqlite3

import pytest

from src import db

_COLS_ACCOUNTS_NUEVAS = {"descripcion", "sitio_web", "hashtags_default", "prompts_json"}


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_tablas_existen_e_init_es_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # segunda vez: no truena
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"brand_sources", "topic_suggestions"} <= tablas


def test_accounts_gana_columnas_de_perfil(tmp_path) -> None:
    cx = _cx(tmp_path)
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(accounts)")}
    assert _COLS_ACCOUNTS_NUEVAS <= cols


def test_brand_sources_check_kind(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "brand_sources", account_id=1, kind="imagen", provider="pexels")
    db.insert(cx, "brand_sources", account_id=1, kind="info", provider="rss")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_sources", account_id=1, kind="video", provider="pexels")


def test_brand_sources_indice_account(tmp_path) -> None:
    cx = _cx(tmp_path)
    indices = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='brand_sources'")}
    assert "idx_sources_account" in indices


def test_brand_sources_activa_default_y_check(tmp_path) -> None:
    cx = _cx(tmp_path)
    sid = db.insert(cx, "brand_sources", account_id=1, kind="imagen", provider="pexels")
    assert db.get(cx, "brand_sources", sid)["activa"] == 1
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_sources", account_id=1, kind="imagen", provider="pexels", activa=2)


def test_topic_suggestions_unique_account_url(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "topic_suggestions", account_id=1, titulo="a",
              url="http://x.com/1", fuente="rss")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "topic_suggestions", account_id=1, titulo="b",
                  url="http://x.com/1", fuente="rss")


def test_topic_suggestions_misma_url_otra_cuenta_ok(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="otra", ig_handle="otra", nombre="Otra", ciudad="CDMX")
    db.insert(cx, "topic_suggestions", account_id=1, titulo="a",
              url="http://x.com/1", fuente="rss")
    db.insert(cx, "topic_suggestions", account_id=2, titulo="a",
              url="http://x.com/1", fuente="rss")


def test_topic_suggestions_descartado_default_y_check(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = db.insert(cx, "topic_suggestions", account_id=1, titulo="a")
    assert db.get(cx, "topic_suggestions", tid)["descartado"] == 0
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "topic_suggestions", account_id=1, titulo="b", descartado=2)


def test_topic_suggestions_indice_account(tmp_path) -> None:
    cx = _cx(tmp_path)
    indices = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='topic_suggestions'")}
    assert "idx_topics_account" in indices


def test_migracion_db_vieja_sin_columnas_nuevas_de_accounts(tmp_path) -> None:
    """DB vieja creada antes de esta migración: init_db de nuevo migra sin error."""
    path = tmp_path / "vieja.db"
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    schema_viejo = db.SCHEMA_PATH.read_text(encoding="utf-8")
    cx.executescript(schema_viejo)
    for col, ddl in db._MIGRATIONS["accounts"].items():
        if col not in _COLS_ACCOUNTS_NUEVAS:
            cx.execute(f"ALTER TABLE accounts ADD COLUMN {col} {ddl}")
    cx.commit()
    cx.close()

    cx = db.connect(path)
    db.init_db(cx)  # no debe reventar

    cols = {r["name"] for r in cx.execute("PRAGMA table_info(accounts)")}
    assert _COLS_ACCOUNTS_NUEVAS <= cols
    cx.close()
