"""Migraciones del motor de segmentos: columnas y tablas nuevas, idempotentes."""
from __future__ import annotations

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_columnas_formato_en_content_queue(tmp_path) -> None:
    cx = _cx(tmp_path)
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert {"template", "formato_patron"} <= cols


def test_columna_aprobacion_y_propuesta(tmp_path) -> None:
    # La compuerta humana es una columna SEPARADA de status (status tiene un
    # CHECK fijo en la DB viva que NO se puede ampliar sin recrear la tabla).
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="meme", aprobacion="pendiente",
                    caption="hola", imagen_url="http://x/y.jpg")
    f = db.get(cx, "content_queue", qid)
    assert f["aprobacion"] == "pendiente" and f["caption"] == "hola"


def test_tablas_audience_y_segment_runs(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "audience_activity", account_id=1, dow=4, hora=19, valor=120)
    db.insert(cx, "segment_runs", segmento="agenda_semanal", account_id=1, ventana="2026-W23")
    assert db.rows(cx, "SELECT valor FROM audience_activity")[0]["valor"] == 120
    assert db.rows(cx, "SELECT segmento FROM segment_runs")[0]["segmento"] == "agenda_semanal"


def test_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # 2a corrida no truena
    assert db.rows(cx, "SELECT count(*) c FROM audience_activity")[0]["c"] == 0
