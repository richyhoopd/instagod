"""Parametrización por marca de sheets y scheduler (sin red: _worksheet fake)."""
from __future__ import annotations

from datetime import datetime

import pytz

import config
from src import scheduler, sheets


class _FakeWS:
    def __init__(self):
        self.rows = []
        self.appended = []

    def get_all_records(self, expected_headers=None):
        return [dict(r) for r in self.rows]

    def append_row(self, row, value_input_option=None):
        self.appended.append(row)

    def row_values(self, i):
        return sheets.COLUMNS

    def batch_update(self, updates):
        self.updates = updates


def _con_fakes(monkeypatch):
    hojas = {}

    def _fake_ws(sheet_id):
        hojas.setdefault(sheet_id, _FakeWS())
        return hojas[sheet_id]

    monkeypatch.setattr(sheets, "_worksheet", _fake_ws)
    return hojas


def test_records_usa_el_sheet_pedido(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    hojas["S2"] = _FakeWS()
    hojas["S2"].rows = [{"id": 1, "status": "approved", "foto_url": ""}]
    assert sheets._records(sheet_id="S2")[0]["id"] == 1
    assert sheets._records(sheet_id="S1") == []          # otra hoja, vacía


def test_records_default_cae_a_config(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    monkeypatch.setattr(config, "SHEET_ID", "S-GLOBAL")
    sheets._records()
    assert "S-GLOBAL" in hojas


def test_append_row_va_al_sheet_de_la_marca(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    rid = sheets.append_row(banda="@pensionmas", status="approved", sheet_id="S2")
    assert rid == 1
    assert hojas["S2"].appended and not hojas.get("S1", _FakeWS()).appended


def test_get_due_rows_por_sheet(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    tz = pytz.timezone(config.TIMEZONE)
    ayer = "2026-08-10T10:00:00"
    hojas["S2"] = _FakeWS()
    hojas["S2"].rows = [{"id": 7, "status": "approved",
                         "scheduled_datetime": ayer, "foto_url": "x"}]
    now = tz.localize(datetime(2026, 8, 11, 12, 0))
    assert [r["id"] for r in sheets.get_due_rows(now, sheet_id="S2")] == [7]
    assert sheets.get_due_rows(now, sheet_id="S1") == []


def test_next_free_slot_con_malla_propia(monkeypatch) -> None:
    _con_fakes(monkeypatch)  # sheets vacíos → nada tomado
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 8, 11, 12, 0))
    slot = scheduler.next_free_slot(now, sheet_id="S2", slots=["10:00", "18:00"])
    assert slot.strftime("%H:%M") in ("10:00", "18:00")
    assert slot.date().isoformat() == "2026-08-12"       # empieza mañana


def test_taken_slots_lee_el_sheet_pedido(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    hojas["S2"] = _FakeWS()
    hojas["S2"].rows = [{"id": 1, "status": "approved",
                         "scheduled_datetime": "2026-08-12T10:00:00"}]
    assert "2026-08-12T10:00" in scheduler._taken_slots(sheet_id="S2")
    assert scheduler._taken_slots(sheet_id="S1") == set()
