"""Esquema de planes de contenido masivo (spec 2026-08-28)."""
import pytest

from src import db


@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_tablas_de_planes_existen(cx):
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "content_plans" in tablas
    assert "plan_topics" in tablas


def test_content_queue_tiene_plan_id(cx):
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert "plan_id" in cols


def test_plan_id_esta_en_rebuild_de_content_queue():
    # Si content_queue gana una columna sin actualizar el DDL de rebuild,
    # _migrar_check_tipo_queue revienta a propósito. Se valida aquí en frío.
    assert "plan_id" in db._CONTENT_QUEUE_REBUILD_COLS
    assert "plan_id" in db._CONTENT_QUEUE_REBUILD_DDL


def test_crud_content_plans(cx):
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="semana",
                    periodo="2026-W36", objetivo="crecer en awareness local",
                    config_json="{}", creado_por=None)
    fila = db.get(cx, "content_plans", pid)
    assert fila["estado"] == "proponiendo"
    db.update(cx, "content_plans", pid, estado="temas")
    assert db.get(cx, "content_plans", pid)["estado"] == "temas"


def test_check_estado_content_plans(cx):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        cx.execute("INSERT INTO content_plans (account_id, tipo_periodo, periodo, "
                   "objetivo, estado) VALUES (1, 'semana', '2026-W36', 'x', 'inventado')")


def test_crud_plan_topics(cx):
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="mes",
                    periodo="2026-09", objetivo="lanzar membresía")
    tid = db.insert(cx, "plan_topics", plan_id=pid, orden=0,
                    titulo="5 razones para ir a shows locales",
                    formato="listicle", hook="nadie habla de la 4",
                    fuente="prompt")
    fila = db.get(cx, "plan_topics", tid)
    assert fila["estado"] == "propuesto"
    db.update(cx, "plan_topics", tid, estado="aprobado")
    # ON DELETE CASCADE del plan
    cx.execute("DELETE FROM content_plans WHERE id = ?", (pid,))
    cx.commit()
    assert db.get(cx, "plan_topics", tid) is None


def test_queue_acepta_plan_id(cx):
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="semana",
                    periodo="2026-W36", objetivo="x")
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
                    caption="c", imagen_url="[]", plan_id=pid)
    assert db.get(cx, "content_queue", qid)["plan_id"] == pid
