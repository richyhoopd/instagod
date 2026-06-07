"""Tests de Fase 5: extracción JSON, copy fiel y scheduler urgente (sin red)."""
from __future__ import annotations

from datetime import datetime

import pytz

import config
from src.generate_anuncios import copy_anuncio, fecha_legible
from src.parse_events import extraer_json
from src.scheduler import next_free_slot_before


def test_extraer_json_tolerante() -> None:
    assert extraer_json('{"fecha": "2026-06-21"}') == {"fecha": "2026-06-21"}
    assert extraer_json('```json\n{"lugar": "C3 Stage"}\n```') == {"lugar": "C3 Stage"}
    assert extraer_json("no hay json aquí") is None
    assert extraer_json("[1, 2, 3]") is None  # lista no es objeto


def test_fecha_legible() -> None:
    assert fecha_legible("2026-06-21") == "domingo 21 de junio"
    assert fecha_legible("fecha-rara") == "fecha-rara"


def test_copy_anuncio_es_fiel() -> None:
    evento = {"tipo": "fecha", "fecha_evento": "2026-06-21",
              "lugar": "C3 Stage", "ciudad": "Guadalajara"}
    for v in range(4):
        copy = copy_anuncio(evento, "Kabala", variante=v)
        # El dato real SIEMPRE presente y sin distorsión, en cualquier variante.
        assert "Kabala" in copy
        assert "21 de junio" in copy
        assert "C3 Stage" in copy
        assert "Guadalajara" in copy


def test_copy_anuncio_sin_lugar_ni_ciudad() -> None:
    evento = {"tipo": "fecha", "fecha_evento": "2026-06-21", "lugar": None, "ciudad": None}
    copy = copy_anuncio(evento, "Los Baxters")
    assert "Los Baxters" in copy and "None" not in copy


def test_copy_release() -> None:
    evento = {"tipo": "release", "fecha_evento": "2026-06-01"}
    copy = copy_anuncio(evento, "Extraño Enemigo")
    assert "Extraño Enemigo" in copy and "1 de junio" in copy


def test_slot_urgente_antes_del_evento(monkeypatch) -> None:
    # Aislar del .env real: un solo slot diario a las 19:00.
    monkeypatch.setattr(config, "POSTING_SLOTS", ["19:00"])
    monkeypatch.setattr(config, "POSTS_PER_DAY", 1)
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 6, 4, 12, 0))
    # Evento en 3 días, sin slots tomados → el slot de HOY (19:00) es el urgente.
    slot = next_free_slot_before("2026-06-07", now=now, taken=set())
    assert slot is not None
    assert slot.strftime("%Y-%m-%dT%H:%M") == "2026-06-04T19:00"
    # Slot de hoy tomado → cae a mañana, sigue antes del evento.
    slot2 = next_free_slot_before("2026-06-07", now=now, taken={"2026-06-04T19:00"})
    assert slot2.strftime("%Y-%m-%dT%H:%M") == "2026-06-05T19:00"


def test_slot_urgente_evento_pasado_o_imposible(monkeypatch) -> None:
    monkeypatch.setattr(config, "POSTING_SLOTS", ["19:00"])
    monkeypatch.setattr(config, "POSTS_PER_DAY", 1)
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 6, 4, 12, 0))
    assert next_free_slot_before("2026-06-01", now=now, taken=set()) is None  # ya pasó
    # Evento hoy: el slot de las 19:00 entra (antes de las 20:00 del evento).
    slot = next_free_slot_before("2026-06-04", now=now, taken=set())
    assert slot is not None and slot.strftime("%H:%M") == "19:00"
    # Evento hoy pero el slot de hoy ya está tomado → no hay manera.
    assert next_free_slot_before("2026-06-04", now=now, taken={"2026-06-04T19:00"}) is None
