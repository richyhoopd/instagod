"""next_free_slot_db / slots_proximos_db: huecos libres desde content_queue (DB), no Sheet."""
from __future__ import annotations

from datetime import datetime

import pytz

import config
from src import db, scheduler


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _seed_queue(cx, account_id: int, status: str, scheduled_datetime: str | None) -> int:
    return db.insert(cx, "content_queue", tipo="meme", account_id=account_id,
                     status=status, scheduled_datetime=scheduled_datetime,
                     caption="x", imagen_url="http://x/1.jpg")


def test_next_free_slot_db_salta_ocupados_del_mismo_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "POSTING_SLOTS", ["19:00", "20:00", "21:00"])
    monkeypatch.setattr(config, "POSTS_PER_DAY", 3)
    cx = _cx(tmp_path)
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 8, 20, 12, 0))
    manana = "2026-08-21"
    _seed_queue(cx, 1, "publicado", f"{manana}T19:00:00")
    _seed_queue(cx, 1, "en_sheet", f"{manana}T20:00:00")

    slot = scheduler.next_free_slot_db(cx, 1, now=now)

    assert slot.strftime("%Y-%m-%dT%H:%M") == f"{manana}T21:00"


def test_next_free_slot_db_ignora_filas_de_otro_account(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "POSTING_SLOTS", ["19:00"])
    monkeypatch.setattr(config, "POSTS_PER_DAY", 1)
    cx = _cx(tmp_path)
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 8, 20, 12, 0))
    manana = "2026-08-21"
    # Ocupa el único slot del account 2, no del 1.
    db.insert(cx, "accounts", slug="otra", ig_handle="@otra", nombre="Otra", ciudad="CDMX")
    _seed_queue(cx, 2, "publicado", f"{manana}T19:00:00")

    slot = scheduler.next_free_slot_db(cx, 1, now=now)

    assert slot.strftime("%Y-%m-%dT%H:%M") == f"{manana}T19:00"


def test_next_free_slot_db_ignora_status_borrador(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "POSTING_SLOTS", ["19:00"])
    monkeypatch.setattr(config, "POSTS_PER_DAY", 1)
    cx = _cx(tmp_path)
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 8, 20, 12, 0))
    manana = "2026-08-21"
    _seed_queue(cx, 1, "borrador", f"{manana}T19:00:00")

    slot = scheduler.next_free_slot_db(cx, 1, now=now)

    assert slot.strftime("%Y-%m-%dT%H:%M") == f"{manana}T19:00"


def test_next_free_slot_db_respeta_malla_propia(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 8, 20, 12, 0))

    slot = scheduler.next_free_slot_db(cx, 1, now=now, slots=["10:00", "18:00"])

    assert slot.strftime("%H:%M") == "10:00"
    assert slot.date().isoformat() == "2026-08-21"


def test_slots_proximos_db_devuelve_n_huecos_crecientes_sin_chocar(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "POSTING_SLOTS", ["19:00"])
    monkeypatch.setattr(config, "POSTS_PER_DAY", 1)
    cx = _cx(tmp_path)
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 8, 20, 12, 0))
    _seed_queue(cx, 1, "en_sheet", "2026-08-21T19:00:00")

    slots = scheduler.slots_proximos_db(cx, 1, n=3, now=now)

    assert [s.strftime("%Y-%m-%dT%H:%M") for s in slots] == [
        "2026-08-22T19:00", "2026-08-23T19:00", "2026-08-24T19:00",
    ]
    assert slots == sorted(slots)
