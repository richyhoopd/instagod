"""Motor de jobs: cola, toma atómica, progreso, rescate de huérfanos y worker."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src import db, jobs
from src.jobs import handlers, worker


@pytest.fixture()
def dbfile(tmp_path):
    return tmp_path / "t.db"


def _conexion_cruda(dbfile):
    """Nueva conexión al mismo archivo, con row_factory como el db.connect real
    (para que el worker.main() bajo test lea filas dict-like)."""
    c = sqlite3.connect(dbfile)
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture()
def cx(dbfile):
    c = db.connect(dbfile)
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield c
    c.close()


def test_crear_deja_el_job_en_cola(cx) -> None:
    jid = jobs.crear(cx, "slideshow.generar", 1, {"tema": "café"}, creado_por=5)
    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "cola"
    assert fila["account_id"] == 1
    assert fila["creado_por"] == 5
    assert fila["payload_json"] == '{"tema": "café"}'


def test_tomar_devuelve_el_job_y_lo_deja_corriendo(cx) -> None:
    jid = jobs.crear(cx, "slideshow.generar", 1, {"tema": "x"})
    job = jobs.tomar(cx, "worker-1")
    assert job["id"] == jid
    assert job["estado"] == "corriendo"
    assert job["worker_id"] == "worker-1"
    assert job["started_at"]
    assert job["heartbeat"]
    assert jobs.tomar(cx, "worker-1") is None  # ya no hay nada en cola


def test_tomar_respeta_aislamiento_por_cuenta(cx) -> None:
    j1 = jobs.crear(cx, "slideshow.generar", 1, {})
    j2 = jobs.crear(cx, "slideshow.generar", 2, {})
    tomado1 = jobs.tomar(cx, "w1")
    assert tomado1["id"] == j1
    # el account 1 ya tiene un job corriendo → el siguiente tomar salta a la
    # cuenta 2, NO puede devolver otro job de la cuenta 1 (no hay más ahí)
    tomado2 = jobs.tomar(cx, "w2")
    assert tomado2["id"] == j2


def test_tomar_no_saca_dos_jobs_de_la_misma_cuenta_corriendo(cx) -> None:
    jobs.crear(cx, "slideshow.generar", 1, {})
    jobs.crear(cx, "slideshow.generar", 1, {})
    primero = jobs.tomar(cx, "w1")
    assert primero is not None
    segundo = jobs.tomar(cx, "w2")  # mismo account_id, ya corriendo uno → None
    assert segundo is None


def test_tomar_max_global(cx) -> None:
    jobs.crear(cx, "slideshow.generar", 1, {})
    jobs.crear(cx, "slideshow.generar", 2, {})
    assert jobs.tomar(cx, "w1", max_global=1) is not None
    assert jobs.tomar(cx, "w2", max_global=1) is None  # ya hay 1 corriendo


def test_progresar_acumula_log_y_heartbeat(cx) -> None:
    jid = jobs.crear(cx, "slideshow.generar", 1, {})
    jobs.tomar(cx, "w1")
    jobs.progresar(cx, jid, 10, "guion")
    jobs.progresar(cx, jid, 40, "imágenes")
    fila = db.get(cx, "jobs", jid)
    assert fila["progreso"] == 40
    assert "[10%] guion" in fila["log"]
    assert "[40%] imágenes" in fila["log"]
    assert fila["log"].index("[10%]") < fila["log"].index("[40%]")
    assert fila["heartbeat"]


def test_terminar_ok(cx) -> None:
    jid = jobs.crear(cx, "slideshow.generar", 1, {})
    jobs.tomar(cx, "w1")
    jobs.terminar(cx, jid, ok=True, resultado={"queue_id": 7})
    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "ok"
    assert fila["resultado_json"] == '{"queue_id": 7}'
    assert fila["finished_at"]


def test_terminar_error_deja_error_y_estado(cx) -> None:
    jid = jobs.crear(cx, "slideshow.generar", 1, {})
    jobs.tomar(cx, "w1")
    jobs.terminar(cx, jid, ok=False, error="algo truene")
    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "error"
    assert "algo truene" in fila["resultado_json"]
    assert "algo truene" in (fila["log"] or "")
    assert fila["finished_at"]


def test_cancelar_solo_en_cola(cx) -> None:
    jid = jobs.crear(cx, "slideshow.generar", 1, {})
    jobs.tomar(cx, "w1")
    assert jobs.cancelar(cx, jid) is False  # ya está corriendo
    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "corriendo"

    jid2 = jobs.crear(cx, "slideshow.generar", 1, {})
    assert jobs.cancelar(cx, jid2) is True
    assert db.get(cx, "jobs", jid2)["estado"] == "cancelado"


def test_rescatar_huerfanos_primera_vez_vuelve_a_cola_segunda_a_error(cx, monkeypatch) -> None:
    t0 = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(jobs, "_ahora", lambda: t0)
    viejo = (t0 - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S")

    jid = db.insert(cx, "jobs", tipo="slideshow.generar", account_id=1, payload_json="{}")
    db.update(cx, "jobs", jid, estado="corriendo", worker_id="w1", heartbeat=viejo)

    n = jobs.rescatar_huerfanos(cx, max_min=30)
    assert n == 1
    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "cola"
    assert "[rescate]" in fila["log"]

    # se vuelve a correr y a quedar huérfano una segunda vez
    db.update(cx, "jobs", jid, estado="corriendo", worker_id="w1", heartbeat=viejo)
    n2 = jobs.rescatar_huerfanos(cx, max_min=30)
    assert n2 == 1
    fila2 = db.get(cx, "jobs", jid)
    assert fila2["estado"] == "error"


def test_rescatar_huerfanos_ignora_jobs_con_heartbeat_reciente(cx, monkeypatch) -> None:
    t0 = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(jobs, "_ahora", lambda: t0)
    reciente = (t0 - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    jid = db.insert(cx, "jobs", tipo="slideshow.generar", account_id=1, payload_json="{}")
    db.update(cx, "jobs", jid, estado="corriendo", worker_id="w1", heartbeat=reciente)
    assert jobs.rescatar_huerfanos(cx, max_min=30) == 0
    assert db.get(cx, "jobs", jid)["estado"] == "corriendo"


def test_worker_main_once_despacha_al_handler_y_registra_resultado(cx, dbfile, monkeypatch) -> None:
    jid = jobs.crear(cx, "fake.tipo", 1, {"x": 1})
    llamadas = []

    def _handler(cx_, job):
        llamadas.append(job["id"])
        return {"ok": True}

    monkeypatch.setattr(handlers, "HANDLERS", {"fake.tipo": _handler})
    monkeypatch.setattr(worker.db, "connect", lambda *a, **k: _conexion_cruda(dbfile))

    worker.main(once=True)

    assert llamadas == [jid]
    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "ok"
    assert fila["resultado_json"] == '{"ok": true}'


def test_worker_main_once_sin_job_no_bloquea(cx, dbfile, monkeypatch) -> None:
    dormido = []
    monkeypatch.setattr(worker, "_dormir", lambda seg: dormido.append(seg))
    monkeypatch.setattr(worker.db, "connect", lambda *a, **k: _conexion_cruda(dbfile))

    worker.main(once=True)

    assert dormido == []  # once=True no debe entrar al sleep-loop


def test_worker_main_once_excepcion_del_handler_termina_con_error(cx, dbfile, monkeypatch) -> None:
    jid = jobs.crear(cx, "fake.tipo", 1, {})

    def _handler(cx_, job):
        raise RuntimeError("boom " * 100)  # más largo que 400 chars

    monkeypatch.setattr(handlers, "HANDLERS", {"fake.tipo": _handler})
    monkeypatch.setattr(worker.db, "connect", lambda *a, **k: _conexion_cruda(dbfile))

    worker.main(once=True)

    fila = db.get(cx, "jobs", jid)
    assert fila["estado"] == "error"
    assert len(fila["resultado_json"]) <= 450  # truncado a 400 + envoltorio json
