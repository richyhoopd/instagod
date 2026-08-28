"""Handlers de jobs de planes (plan.proponer_temas, plan.generar)."""
import json

import pytest

from src import db, jobs, planes
from src.jobs import handlers


@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _job(cx, tipo, plan_id, account_id=1):
    jid = jobs.crear(cx, tipo, account_id, {"plan_id": plan_id})
    fila = jobs.tomar(cx, "w-test")
    assert fila and fila["id"] == jid
    return fila


def _plan(cx, **cfg):
    config = {"n_piezas": 2, "n_slides": 6, "aspect": "4:5",
              "formatos": ["listicle"], "fuentes_info": ["prompt"]}
    config.update(cfg)
    fila = cx.execute("SELECT id FROM users WHERE email = 'plan@x.mx'").fetchone()
    uid = fila["id"] if fila else db.insert(cx, "users", email="plan@x.mx")
    return planes.crear(cx, 1, tipo_periodo="semana", periodo="2026-W36",
                        objetivo="objetivo de prueba", config=config, creado_por=uid)


def test_proponer_temas_ok(cx, monkeypatch):
    pid = _plan(cx)
    monkeypatch.setattr(handlers.plan_temas, "proponer",
                        lambda *a, **k: [
                            {"titulo": "t1", "formato": "listicle", "hook": "h1",
                             "fuente": "prompt", "url": None},
                            {"titulo": "t2", "formato": "listicle", "hook": "h2",
                             "fuente": "prompt", "url": None}])
    res = handlers.plan_proponer_temas(cx, _job(cx, "plan.proponer_temas", pid))
    assert res["temas"] == 2
    plan = db.get(cx, "content_plans", pid)
    assert plan["estado"] == "temas"
    topics = db.rows(cx, "SELECT * FROM plan_topics WHERE plan_id = ? ORDER BY orden", (pid,))
    assert [t["titulo"] for t in topics] == ["t1", "t2"]
    assert all(t["estado"] == "propuesto" for t in topics)


def test_proponer_temas_liga_topic_suggestion(cx, monkeypatch):
    pid = _plan(cx, fuentes_info=["prompt", "noticias"])
    tid = db.insert(cx, "topic_suggestions", account_id=1, titulo="nota",
                    url="https://ejemplo.mx/nota")
    monkeypatch.setattr(handlers, "_refrescar_fuentes_info", lambda *a, **k: None)
    monkeypatch.setattr(handlers.plan_temas, "proponer",
                        lambda *a, **k: [
                            {"titulo": "t1", "formato": "listicle", "hook": "h",
                             "fuente": "noticia", "url": "https://ejemplo.mx/nota"}])
    handlers.plan_proponer_temas(cx, _job(cx, "plan.proponer_temas", pid))
    topic = db.rows(cx, "SELECT * FROM plan_topics WHERE plan_id = ?", (pid,))[0]
    assert topic["topic_suggestion_id"] == tid


def test_proponer_temas_error_marca_plan(cx, monkeypatch):
    pid = _plan(cx)

    def _revienta(*a, **k):
        raise RuntimeError("LLM caído")
    monkeypatch.setattr(handlers.plan_temas, "proponer", _revienta)
    with pytest.raises(RuntimeError):
        handlers.plan_proponer_temas(cx, _job(cx, "plan.proponer_temas", pid))
    assert db.get(cx, "content_plans", pid)["estado"] == "error"


def test_plan_generar_tolerante_a_fallos(cx, monkeypatch):
    pid = _plan(cx)
    db.update(cx, "content_plans", pid, estado="temas")
    t1 = db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="ok",
                   formato="listicle", estado="aprobado")
    t2 = db.insert(cx, "plan_topics", plan_id=pid, orden=1, titulo="falla",
                   formato="listicle", estado="aprobado")
    db.insert(cx, "plan_topics", plan_id=pid, orden=2, titulo="descartado",
              estado="descartado")

    def _generar_fake(cx_, tema, **kwargs):
        assert kwargs["notificar_telegram"] is False
        assert kwargs["creado_por"] == db.get(cx_, "content_plans", pid)["creado_por"]
        if tema == "falla":
            raise RuntimeError("pexels caído")
        return db.insert(cx_, "content_queue", tipo="slideshow", account_id=1,
                         caption="c", imagen_url="[]", aprobacion="pendiente",
                         origen="api")

    monkeypatch.setattr(handlers.generate_slideshow, "generar", _generar_fake)
    res = handlers.plan_generar(cx, _job(cx, "plan.generar", pid))
    assert res == {"generadas": 1, "fallidas": 1}
    plan = db.get(cx, "content_plans", pid)
    assert plan["estado"] == "curacion"
    f1, f2 = db.get(cx, "plan_topics", t1), db.get(cx, "plan_topics", t2)
    assert f1["estado"] == "generado" and f1["queue_id"]
    assert db.get(cx, "content_queue", f1["queue_id"])["plan_id"] == pid
    assert f2["estado"] == "error" and "pexels" in (f2["error"] or "")


def test_plan_generar_redacta_secretos_en_error(cx, monkeypatch):
    pid = _plan(cx)
    db.update(cx, "content_plans", pid, estado="temas")
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="x",
              formato="listicle", estado="aprobado")
    db.insert(cx, "plan_topics", plan_id=pid, orden=1, titulo="y",
              formato="listicle", estado="aprobado")
    monkeypatch.setattr(handlers.config, "account_creds",
                        lambda slug: {"PEXELS_API_KEY": "sk-secreta"})

    llamadas = {"n": 0}

    def _generar_fake(cx_, tema, **kwargs):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            raise RuntimeError("falló con key sk-secreta expuesta")
        return db.insert(cx_, "content_queue", tipo="slideshow", account_id=1,
                         caption="c", imagen_url="[]", aprobacion="pendiente")

    monkeypatch.setattr(handlers.generate_slideshow, "generar", _generar_fake)
    handlers.plan_generar(cx, _job(cx, "plan.generar", pid))
    con_error = db.rows(cx, "SELECT * FROM plan_topics WHERE plan_id = ? "
                            "AND estado = 'error'", (pid,))[0]
    assert "sk-secreta" not in (con_error["error"] or "")
    assert "***" in con_error["error"]


def test_plan_generar_todo_falla_es_error(cx, monkeypatch):
    pid = _plan(cx)
    db.update(cx, "content_plans", pid, estado="temas")
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="x",
              formato="listicle", estado="aprobado")

    def _revienta(*a, **k):
        raise RuntimeError("todo mal")
    monkeypatch.setattr(handlers.generate_slideshow, "generar", _revienta)
    with pytest.raises(RuntimeError):
        handlers.plan_generar(cx, _job(cx, "plan.generar", pid))
    assert db.get(cx, "content_plans", pid)["estado"] == "error"


def test_plan_generar_exige_estado_temas(cx):
    pid = _plan(cx)  # sigue en 'proponiendo'
    with pytest.raises(ValueError):
        handlers.plan_generar(cx, _job(cx, "plan.generar", pid))


def test_plan_de_valida_cuenta(cx):
    pid = _plan(cx)  # cuenta 1
    otra = db.insert(cx, "accounts", slug="otra", ig_handle="@otra",
                     nombre="Otra", ciudad="CDMX")
    with pytest.raises(ValueError):
        handlers.plan_generar(cx, _job(cx, "plan.generar", pid, account_id=otra))


def test_regenerar_preserva_plan_id(cx, monkeypatch):
    pid = _plan(cx)
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
                    caption="c", imagen_url="[]", plan_id=pid,
                    slideshow_json=json.dumps({"brief": {"tema": "t", "n_slides": 6}}))
    tid = db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="t",
                    estado="generado", queue_id=qid)
    nuevo = {"valor": None}

    def _generar_fake(cx_, tema, **kwargs):
        nuevo["valor"] = db.insert(cx_, "content_queue", tipo="slideshow",
                                   account_id=1, caption="c2", imagen_url="[]")
        return nuevo["valor"]

    monkeypatch.setattr(handlers.generate_slideshow, "generar", _generar_fake)
    jobs.crear(cx, "slideshow.regenerar", 1, {"queue_id": qid})
    fila = jobs.tomar(cx, "w-test")
    handlers.regenerar_slideshow(cx, fila)
    assert db.get(cx, "content_queue", nuevo["valor"])["plan_id"] == pid
    assert db.get(cx, "plan_topics", tid)["queue_id"] == nuevo["valor"]
