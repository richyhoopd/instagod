"""Dominio de planes de contenido (src/planes.py)."""
import pytest

from src import db, planes


@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _plan(cx, **extra):
    base = dict(tipo_periodo="semana", periodo="2026-W36",
                objetivo="crecer awareness", config={"n_piezas": 3}, creado_por=None)
    base.update(extra)
    return planes.crear(cx, 1, **base)


def test_validar_periodo():
    assert planes.validar_periodo("semana", "2026-W36")
    assert planes.validar_periodo("mes", "2026-09")
    assert not planes.validar_periodo("semana", "2026-09")
    assert not planes.validar_periodo("mes", "2026-W36")
    assert not planes.validar_periodo("mes", "septiembre")


def test_crear_y_detalle(cx):
    pid = _plan(cx)
    d = planes.detalle(cx, pid)
    assert d["estado"] == "proponiendo"
    assert d["topics"] == [] and d["piezas"] == []
    assert planes.config_de(d)["n_piezas"] == 3


def test_crear_periodo_invalido(cx):
    with pytest.raises(ValueError, match="periodo"):
        _plan(cx, periodo="2026-09")


def test_listar_con_conteos(cx):
    pid = _plan(cx)
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="a", estado="aprobado")
    db.insert(cx, "plan_topics", plan_id=pid, orden=1, titulo="b")
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
                    caption="c", imagen_url="[]", plan_id=pid, aprobacion="pendiente")
    db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
              caption="d", imagen_url="[]", plan_id=pid, status="descartado")
    fila = planes.listar(cx, 1)[0]
    assert fila["id"] == pid
    assert fila["topics_total"] == 2 and fila["topics_aprobados"] == 1
    assert fila["piezas"] == 1 and fila["piezas_pendientes"] == 1
    assert qid  # la descartada no cuenta


def test_agregar_topic_manual_nace_aprobado(cx):
    pid = _plan(cx)
    tid = planes.agregar_topic(cx, pid, titulo="tema manual", hook="gancho")
    t = db.get(cx, "plan_topics", tid)
    assert t["estado"] == "aprobado" and t["fuente"] == "manual" and t["orden"] == 0
    tid2 = planes.agregar_topic(cx, pid, titulo="otro")
    assert db.get(cx, "plan_topics", tid2)["orden"] == 1


def test_editar_topic_bloquea_generados(cx):
    pid = _plan(cx)
    tid = planes.agregar_topic(cx, pid, titulo="t")
    planes.editar_topic(cx, tid, titulo="t2", estado="descartado")
    assert db.get(cx, "plan_topics", tid)["titulo"] == "t2"
    db.update(cx, "plan_topics", tid, estado="generado", queue_id=99)
    with pytest.raises(ValueError, match="estado"):
        planes.editar_topic(cx, tid, titulo="t3")


def test_editar_topic_valida_campos_y_estado(cx):
    pid = _plan(cx)
    tid = planes.agregar_topic(cx, pid, titulo="t")
    with pytest.raises(ValueError):
        planes.editar_topic(cx, tid, queue_id=5)
    with pytest.raises(ValueError):
        planes.editar_topic(cx, tid, estado="generado")


def test_config_de_tolerante():
    assert planes.config_de({"config_json": None}) == {}
    assert planes.config_de({"config_json": "basura{"}) == {}
    assert planes.config_de({"config_json": "[1,2]"}) == {}
