"""Ensanchar CHECK(aspecto) de brand_templates a '1:1' sin perder diseños ni versiones."""
from __future__ import annotations

import sqlite3

import pytest

from src import db

_NUEVO = "CHECK (aspecto IN ('4:5','9:16','1:1')),"
_VIEJO = "CHECK (aspecto IN ('4:5','9:16')),"
_SCHEMA_REAL = db.SCHEMA_PATH.read_text(encoding="utf-8")
assert _NUEVO in _SCHEMA_REAL, "cambió el CHECK de brand_templates en schema.sql"
_OLD_SCHEMA = _SCHEMA_REAL.replace(_NUEVO, _VIEJO)


def _db_vieja(path, plantillas: int = 1) -> None:
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    cx.executescript(_OLD_SCHEMA)
    cx.execute("INSERT OR IGNORE INTO accounts (id, slug, ig_handle, nombre, ciudad) "
               "VALUES (1,'gdlscene','gdlscene','La Escena GDL','Guadalajara')")
    cx.execute("INSERT INTO brand_templates (id, account_id, slug, nombre, aspecto, "
               "contrato_json, html, layout_json, estado) VALUES "
               "(7, 1, 'onion', 'Onion', '9:16', '{}', '<div class=\"card\"></div>', "
               "'{\"v\": 1}', 'activa')")
    cx.execute("INSERT INTO template_versions (template_id, version, html, contrato_json) "
               "VALUES (7, 1, '<div class=\"card\"></div>', '{}')")
    for i in range(1, plantillas):
        cx.execute("INSERT INTO brand_templates (account_id, slug, nombre, aspecto, "
                   "contrato_json, html, version_actual) VALUES (1, ?, ?, ?, '{}', 'h', 3)",
                   (f"p{i}", f"P{i}", "4:5" if i % 2 else "9:16"))
        tid = cx.execute("SELECT id FROM brand_templates WHERE slug = ?",
                         (f"p{i}",)).fetchone()[0]
        for v in (1, 2, 3):
            cx.execute("INSERT INTO template_versions (template_id, version, html, "
                       "contrato_json, mensaje_usuario) VALUES (?, ?, 'h', '{}', ?)",
                       (tid, v, f"msg {i}.{v}"))
    with pytest.raises(sqlite3.IntegrityError):
        cx.execute("INSERT INTO brand_templates (account_id, slug, nombre, aspecto, "
                   "contrato_json, html) VALUES (1, 'q', 'Q', '1:1', '{}', 'x')")
    cx.commit()
    cx.close()


def test_migra_el_check_sin_perder_nada(tmp_path):
    path = tmp_path / "vieja.db"
    _db_vieja(path)
    cx = db.connect(path)
    db.init_db(cx)

    fila = db.rows(cx, "SELECT id, slug, aspecto, layout_json, estado FROM brand_templates")
    assert fila == [{"id": 7, "slug": "onion", "aspecto": "9:16",
                     "layout_json": '{"v": 1}', "estado": "activa"}]
    assert db.rows(cx, "SELECT template_id, version FROM template_versions") == [
        {"template_id": 7, "version": 1}]

    nuevo = db.insert(cx, "brand_templates", account_id=1, slug="cuadrado", nombre="C",
                      aspecto="1:1", contrato_json="{}", html="x")
    assert db.get(cx, "brand_templates", nuevo)["aspecto"] == "1:1"
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_templates", account_id=1, slug="ancho", nombre="A",
                  aspecto="16:9", contrato_json="{}", html="x")

    # El índice volvió y la cascada de versiones sigue viva.
    indices = {r["name"] for r in cx.execute("PRAGMA index_list(brand_templates)")}
    assert "idx_templates_cuenta" in indices
    cx.execute("DELETE FROM brand_templates WHERE id = 7")
    assert db.rows(cx, "SELECT * FROM template_versions") == []


def test_es_idempotente(tmp_path):
    path = tmp_path / "vieja.db"
    _db_vieja(path)
    cx = db.connect(path)
    db.init_db(cx)
    db.init_db(cx)
    assert db.rows(cx, "SELECT count(*) AS n FROM brand_templates") == [{"n": 1}]


def test_datos_con_forma_real_integridad_e_indices(tmp_path):
    path = tmp_path / "vieja.db"
    _db_vieja(path, plantillas=6)
    cx = sqlite3.connect(path)
    cx.row_factory = sqlite3.Row
    antes_t = [tuple(r) for r in cx.execute("SELECT * FROM brand_templates ORDER BY id")]
    antes_v = [tuple(r) for r in cx.execute("SELECT * FROM template_versions ORDER BY id")]
    cx.close()
    assert len(antes_t) == 6 and len(antes_v) == 16

    cx = db.connect(path)
    db.init_db(cx)
    despues_t = [tuple(r) for r in cx.execute("SELECT * FROM brand_templates ORDER BY id")]
    despues_v = [tuple(r) for r in cx.execute("SELECT * FROM template_versions ORDER BY id")]
    assert despues_t == antes_t            # mismas filas, mismo orden de columnas
    assert despues_v == antes_v
    assert cx.execute("PRAGMA foreign_key_check").fetchall() == []
    assert cx.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert cx.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not cx.in_transaction
    indices = {r["name"] for r in cx.execute("PRAGMA index_list(brand_templates)")}
    assert "idx_templates_cuenta" in indices
    # AUTOINCREMENT sigue contando desde el último id, no desde 1.
    nuevo = db.insert(cx, "brand_templates", account_id=1, slug="z", nombre="Z",
                      aspecto="1:1", contrato_json="{}", html="x")
    assert nuevo > max(r[0] for r in antes_t)
    # UNIQUE (account_id, slug) sigue vivo.
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_templates", account_id=1, slug="z", nombre="Z",
                  aspecto="4:5", contrato_json="{}", html="x")


def test_tabla_new_sobrante_de_una_corrida_abortada(tmp_path):
    path = tmp_path / "vieja.db"
    _db_vieja(path)
    cx = sqlite3.connect(path)
    cx.execute("CREATE TABLE brand_templates_new (basura TEXT)")
    cx.execute("INSERT INTO brand_templates_new VALUES ('x')")
    cx.commit()
    cx.close()

    cx = db.connect(path)
    db.init_db(cx)
    assert db.rows(cx, "SELECT slug FROM brand_templates") == [{"slug": "onion"}]
    assert cx.execute("SELECT name FROM sqlite_master WHERE name = "
                      "'brand_templates_new'").fetchone() is None
    assert db.insert(cx, "brand_templates", account_id=1, slug="c", nombre="C",
                     aspecto="1:1", contrato_json="{}", html="x")


def test_si_falla_a_la_mitad_no_deja_la_base_a_medias(tmp_path):
    path = tmp_path / "vieja.db"
    _db_vieja(path)
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = OFF")     # versión huérfana: rompe el FK check
    cx.execute("INSERT INTO template_versions (template_id, version, html, contrato_json) "
               "VALUES (99, 1, 'h', '{}')")
    cx.commit()
    cx.close()

    cx = db.connect(path)
    with pytest.raises(RuntimeError, match="foreign_key_check"):
        db.init_db(cx)
    assert cx.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not cx.in_transaction
    sql = cx.execute("SELECT sql FROM sqlite_master WHERE name = 'brand_templates'"
                     ).fetchone()[0]
    assert "'1:1'" not in sql                   # sigue la tabla vieja, intacta
    assert cx.execute("SELECT count(*) FROM brand_templates").fetchone()[0] == 1
    assert cx.execute("SELECT name FROM sqlite_master WHERE name = "
                      "'brand_templates_new'").fetchone() is None
    idx = {r["name"] for r in cx.execute("PRAGMA index_list(brand_templates)")}
    assert "idx_templates_cuenta" in idx
