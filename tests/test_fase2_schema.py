"""Fase 2 (portal): columnas de publicación en content_queue + tabla jobs."""
from __future__ import annotations

import sqlite3

import pytest

from src import db

_COLS_NUEVAS = {
    "publicado_en", "error", "creado_por", "aprobado_por",
    "ig_media_id", "origen", "tg_chat_id", "tg_message_id", "intentos",
}


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_columnas_publicacion_en_content_queue(tmp_path) -> None:
    cx = _cx(tmp_path)
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert _COLS_NUEVAS <= cols


def test_origen_default_legacy(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="meme", caption="x", imagen_url="http://x/1.jpg")
    assert db.get(cx, "content_queue", qid)["origen"] == "legacy"


def test_init_db_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # segunda corrida: no truena
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert _COLS_NUEVAS <= cols


def test_tabla_jobs_existe(tmp_path) -> None:
    cx = _cx(tmp_path)
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "jobs" in tablas


def test_jobs_check_estado_rechaza_valor_invalido(tmp_path) -> None:
    cx = _cx(tmp_path)
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "jobs", tipo="slideshow.generar", account_id=1, estado="volando")


def test_jobs_insert_default_estado_cola(tmp_path) -> None:
    cx = _cx(tmp_path)
    jid = db.insert(cx, "jobs", tipo="slideshow.generar", account_id=1)
    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "cola"
    assert fila["progreso"] == 0


def test_jobs_indices_existen(tmp_path) -> None:
    cx = _cx(tmp_path)
    indices = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='jobs'")}
    assert {"idx_jobs_estado", "idx_jobs_account"} <= indices


def test_migracion_db_vieja_sin_columnas_nuevas(tmp_path) -> None:
    """DB vieja creada antes de esta migración: init_db de nuevo migra sin error."""
    path = tmp_path / "vieja.db"
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    schema_viejo = db.SCHEMA_PATH.read_text(encoding="utf-8")
    cx.executescript(schema_viejo)
    for col, ddl in db._MIGRATIONS["content_queue"].items():
        if col not in _COLS_NUEVAS:
            cx.execute(f"ALTER TABLE content_queue ADD COLUMN {col} {ddl}")
    cx.execute("INSERT OR IGNORE INTO accounts (id, slug, ig_handle, nombre, ciudad) "
               "VALUES (1,'gdlscene','gdlscene','La Escena GDL','Guadalajara')")
    cx.execute("INSERT INTO content_queue (tipo, caption, imagen_url, status) "
               "VALUES ('meme','vieja','http://x/1.jpg','borrador')")
    cx.commit()
    cx.close()

    cx = db.connect(path)
    db.init_db(cx)  # no debe reventar

    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert _COLS_NUEVAS <= cols
    fila = db.rows(cx, "SELECT tipo, caption, origen FROM content_queue WHERE tipo='meme'")[0]
    assert fila == {"tipo": "meme", "caption": "vieja", "origen": "legacy"}
    cx.close()


def test_migracion_check_status_admite_programado(tmp_path) -> None:
    """DB vieja con CHECK(status) sin 'programado': init_db debe ensancharlo.

    Antes de esta migración, 'programado' (el status que usa el publisher DB
    sin Sheet, Task 3) reventaba con IntegrityError al no estar en el CHECK.
    """
    path = tmp_path / "vieja_status.db"
    schema_viejo = db.SCHEMA_PATH.read_text(encoding="utf-8").replace(
        "CHECK (status IN ('borrador','listo','en_sheet','programado','publicado','descartado'))",
        "CHECK (status IN ('borrador','listo','en_sheet','publicado','descartado'))",
    )
    assert "'programado'" not in schema_viejo, (
        "el reemplazo del schema viejo no tumbó el CHECK(status) con "
        "'programado' (¿cambió el formato en schema.sql?)"
    )
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    cx.executescript(schema_viejo)
    for col, ddl in db._MIGRATIONS["content_queue"].items():
        cx.execute(f"ALTER TABLE content_queue ADD COLUMN {col} {ddl}")
    cx.execute("INSERT OR IGNORE INTO accounts (id, slug, ig_handle, nombre, ciudad) "
               "VALUES (1,'gdlscene','gdlscene','La Escena GDL','Guadalajara')")
    cx.commit()
    cx.close()

    cx = db.connect(path)
    db.init_db(cx)

    qid = db.insert(cx, "content_queue", tipo="meme", caption="x", imagen_url="http://x/1.jpg",
                    status="borrador", aprobacion="pendiente")
    db.update(cx, "content_queue", qid, status="programado")  # antes: IntegrityError
    assert db.get(cx, "content_queue", qid)["status"] == "programado"

    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "content_queue", tipo="meme", caption="x", imagen_url="x",
                  status="basura")

    db.init_db(cx)  # segunda corrida: idempotente, no revienta
    cx.close()
