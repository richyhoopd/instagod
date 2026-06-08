"""Dispatcher: dispara segmentos que tocan hoy, idempotente por ventana."""
from __future__ import annotations

from datetime import datetime

from src import db, segment_runner, segments


def test_ventana_semanal_y_mensual() -> None:
    assert segments.ventana_de("agenda_semanal", datetime(2026, 6, 8)) == "2026-W24"
    assert segments.ventana_de("releases_mensual", datetime(2026, 6, 8)) == "2026-06"


def test_dispatch_idempotente(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    corridos = []
    seg = segments.Segment("demo", "Demo", lambda cx, acc: corridos.append(1),
                           cadencia={"tipo": "semanal", "dow": 6}, ventana_trafico="meme")
    hoy = datetime(2026, 6, 14)  # domingo (dow 6) → toca
    segment_runner.dispatch(cx, [seg], ahora=hoy, account_id=1)
    segment_runner.dispatch(cx, [seg], ahora=hoy, account_id=1)  # 2a vez NO repite
    assert corridos == [1]


def test_no_dispara_si_no_toca_hoy(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    corridos = []
    seg = segments.Segment("demo", "Demo", lambda cx, acc: corridos.append(1),
                           cadencia={"tipo": "semanal", "dow": 6}, ventana_trafico="meme")
    segment_runner.dispatch(cx, [seg], ahora=datetime(2026, 6, 10), account_id=1)  # miércoles
    assert corridos == []
