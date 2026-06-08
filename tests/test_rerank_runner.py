"""Re-ranker dinámico de la cola: capa IO alrededor del núcleo PURO de engagement.

El reordenamiento puro (engagement.rerank_cola) ya está cubierto en
test_engagement. Aquí se blindan los lectores/diff del runner: qué items se
consideran "futuros" y el proxy de band_score por banda.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from src import db, rerank_runner


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _futuro(dias: int) -> str:
    return (datetime.now() + timedelta(days=dias)).isoformat()


def test_items_futuros_solo_devuelve_en_sheet_y_futuros(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.upsert_band(cx, "Kabala", "kabala", followers_ig=1000)
    # futuro, en_sheet → entra
    db.insert(cx, "content_queue", band_id=bid, status=db.QUEUE_EN_SHEET,
              formato_patron="absurdo_domestico", scheduled_datetime=_futuro(3),
              sheet_row_id="A")
    # pasado, en_sheet → fuera
    db.insert(cx, "content_queue", band_id=bid, status=db.QUEUE_EN_SHEET,
              formato_patron="comunicado", scheduled_datetime=_futuro(-3))
    # futuro pero borrador → fuera (no tiene slot asignado)
    db.insert(cx, "content_queue", band_id=bid, status=db.QUEUE_BORRADOR,
              formato_patron="comunicado", scheduled_datetime=_futuro(5))

    items = rerank_runner._items_futuros(cx, account_id=1)
    assert len(items) == 1
    assert items[0]["patron"] == "absurdo_domestico"
    assert items[0]["sheet_row_id"] == "A"
    cx.close()


def test_items_futuros_ordenados_por_scheduled(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.upsert_band(cx, "Kabala", "kabala")
    db.insert(cx, "content_queue", band_id=bid, status=db.QUEUE_EN_SHEET,
              formato_patron="otro", scheduled_datetime=_futuro(10))
    db.insert(cx, "content_queue", band_id=bid, status=db.QUEUE_EN_SHEET,
              formato_patron="otro", scheduled_datetime=_futuro(2))
    items = rerank_runner._items_futuros(cx, account_id=1)
    fechas = [i["scheduled"] for i in items]
    assert fechas == sorted(fechas)   # ascendente: el más cercano primero
    cx.close()


def test_band_score_map_cold_start_usa_followers(tmp_path) -> None:
    # Banda activa sin posts (cold-start) → score = followers/1_000_000.
    cx = _cx(tmp_path)
    bid = db.upsert_band(cx, "Grande", "grande", followers_ig=5_000_000, prioridad=3)
    bscore = rerank_runner._band_score_map(cx, account_id=1)
    assert bscore[bid] == 5_000_000 / 1_000_000
    cx.close()


def test_band_score_map_devuelve_float_por_banda(tmp_path) -> None:
    cx = _cx(tmp_path)
    b1 = db.upsert_band(cx, "A", "a", followers_ig=1000)
    b2 = db.upsert_band(cx, "B", "b", followers_ig=2000)
    bscore = rerank_runner._band_score_map(cx, account_id=1)
    assert {b1, b2} <= set(bscore)
    assert all(isinstance(v, float) for v in bscore.values())
    cx.close()
