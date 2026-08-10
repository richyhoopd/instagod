"""Migración del CHECK(tipo) de content_queue: DB vieja -> nueva sin perder nada.

db.init_db() sobre una DB fresca (creada desde el schema.sql ya ensanchado)
nunca ejercita el cuerpo de _migrar_check_tipo_queue: el CHECK ya trae
'slideshow' desde el arranque. Este test arma a mano una DB con el DDL VIEJO
(CHECK(tipo) sin 'slideshow', sin la columna slideshow_json) + filas + una FK
desde ig_posts, y corre el init_db() real encima para probar el rebuild.
"""
from __future__ import annotations

import sqlite3

import pytest

from src import db

# Reconstruye el schema.sql VIEJO (pre-'slideshow') a partir del real: los
# únicos cambios de esta migración en schema.sql fueron el comentario y el
# CHECK de content_queue.tipo, así que revertir esas dos líneas y correr el
# resto del DDL real (todas las tablas/índices/triggers tal cual) simula
# fielmente una DB vieja sin mantener un stub de esquema aparte. OJO: hay que
# tumbar también el comentario -- 'meme' | 'anuncio' | 'slideshow' — sqlite
# guarda el DDL verbatim en sqlite_master.sql, comentario incluido, y el
# guard de _migrar_check_tipo_queue busca el literal 'slideshow' en ESE texto.
_OLD_SCHEMA = (
    db.SCHEMA_PATH.read_text(encoding="utf-8")
    .replace("-- 'meme' | 'anuncio' | 'slideshow'", "-- 'meme' | 'anuncio'")
    .replace("CHECK (tipo   IN ('meme','anuncio','slideshow')),",
             "CHECK (tipo   IN ('meme','anuncio')),")
)
assert "slideshow" not in _OLD_SCHEMA, (
    "el reemplazo del schema viejo no tumbó todas las menciones a 'slideshow' "
    "(¿cambió el formato en schema.sql?)"
)

# Columnas que _MIGRATIONS["content_queue"] agrega vía ALTER, tal como
# estaban ANTES de esta migración (todo excepto slideshow_json, que es
# exactamente la columna nueva de esta tarea).
_OLD_MIGRATED_COLS = {c: ddl for c, ddl in db._MIGRATIONS["content_queue"].items()
                      if c != "slideshow_json"}


def _preparar_db_vieja(path) -> None:
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    cx.executescript(_OLD_SCHEMA)
    for col, ddl in _OLD_MIGRATED_COLS.items():
        cx.execute(f"ALTER TABLE content_queue ADD COLUMN {col} {ddl}")
    cx.execute("INSERT OR IGNORE INTO accounts (id, slug, ig_handle, nombre, ciudad) "
               "VALUES (1,'gdlscene','gdlscene','La Escena GDL','Guadalajara')")
    cx.execute("INSERT INTO content_queue (tipo, caption, imagen_url, status, aprobacion) "
               "VALUES ('meme','meme viejo','http://x/1.jpg','borrador','pendiente')")
    cx.execute("INSERT INTO content_queue "
               "(tipo, caption, imagen_url, status, scheduled_datetime) "
               "VALUES ('anuncio','anuncio viejo','http://x/2.jpg','en_sheet',"
               "'2026-01-01T00:00:00')")
    cx.execute("INSERT INTO ig_posts (media_id, queue_id) VALUES ('m1', 1)")
    cx.commit()
    cx.close()


def test_migra_check_tipo_sin_perder_datos(tmp_path) -> None:
    path = tmp_path / "vieja.db"
    _preparar_db_vieja(path)

    cx = db.connect(path)
    db.init_db(cx)

    filas = db.rows(cx, "SELECT id, tipo, caption, imagen_url, status, "
                        "scheduled_datetime, aprobacion FROM content_queue ORDER BY id")
    assert filas == [
        {"id": 1, "tipo": "meme", "caption": "meme viejo", "imagen_url": "http://x/1.jpg",
         "status": "borrador", "scheduled_datetime": None, "aprobacion": "pendiente"},
        {"id": 2, "tipo": "anuncio", "caption": "anuncio viejo", "imagen_url": "http://x/2.jpg",
         "status": "en_sheet", "scheduled_datetime": "2026-01-01T00:00:00", "aprobacion": None},
    ]

    # ig_posts.queue_id sigue apuntando a la fila 1: la FK sobrevivió el rebuild.
    assert db.rows(cx, "SELECT queue_id FROM ig_posts WHERE media_id='m1'") == [
        {"queue_id": 1},
    ]

    # tipo='slideshow' ahora insertable (antes reventaba con CHECK constraint failed).
    qid = db.insert(cx, "content_queue", tipo="slideshow", caption="ss",
                    imagen_url="[]", status="borrador", aprobacion="pendiente",
                    slideshow_json="{}")
    assert db.get(cx, "content_queue", qid)["tipo"] == "slideshow"

    # el CHECK sigue vivo: un tipo inventado se sigue rechazando.
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "content_queue", tipo="basura", caption="x", imagen_url="x")

    # el trigger de updated_at sigue funcionando tras el rebuild.
    db.update(cx, "content_queue", 1, caption="editado")
    assert db.get(cx, "content_queue", 1)["updated_at"] is not None

    # los índices sobrevivieron el rebuild.
    indices = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='content_queue'")}
    assert {"idx_queue_status", "idx_queue_band"} <= indices

    # sin residuo de la tabla temporal del rebuild.
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "content_queue_new" not in tablas

    # segundo init_db es no-op limpio (idempotente): no revienta ni cambia nada.
    filas_antes = db.rows(cx, "SELECT * FROM content_queue ORDER BY id")
    db.init_db(cx)
    filas_despues = db.rows(cx, "SELECT * FROM content_queue ORDER BY id")
    assert filas_antes == filas_despues

    cx.close()


def test_columna_vieja_desconocida_revienta_en_vez_de_perderse(tmp_path) -> None:
    """Si content_queue trae una columna que _CONTENT_QUEUE_REBUILD_COLS no
    conoce (p. ej. una agregada a _MIGRATIONS sin actualizar la lista del
    rebuild), la migración debe reventar con RuntimeError en vez de
    dropearla en silencio — el bug real que motivó este test."""
    path = tmp_path / "vieja_con_columna_futura.db"
    _preparar_db_vieja(path)
    cx = sqlite3.connect(path)
    # Simula una columna agregada a _MIGRATIONS en el futuro, todavía no
    # reflejada en _CONTENT_QUEUE_REBUILD_COLS/_CONTENT_QUEUE_REBUILD_DDL.
    cx.execute("ALTER TABLE content_queue ADD COLUMN columna_del_futuro TEXT")
    cx.commit()
    cx.close()

    cx = db.connect(path)
    with pytest.raises(RuntimeError, match="columna_del_futuro"):
        db.init_db(cx)
    cx.close()
