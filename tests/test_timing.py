"""Timing de alto tráfico: prioridad de fuentes y arranque en frío."""
from __future__ import annotations

from datetime import datetime

from src import timing


def test_default_cuando_no_hay_audiencia() -> None:
    # Sin audiencia → usa TIMING_DEFAULTS (agenda_semanal = jueves 19h).
    ahora = datetime(2026, 6, 8, 10, 0)  # lunes
    slot = timing.elegir_slot("agenda_semanal", ahora, audiencia=[])
    assert slot.weekday() == 3 and slot.hour == 19 and slot > ahora


def test_usa_audiencia_si_existe() -> None:
    # Audiencia con pico claro sábado 21h → gana al default.
    aud = [{"dow": 5, "hora": 21, "valor": 900}, {"dow": 1, "hora": 9, "valor": 10}]
    slot = timing.elegir_slot("meme", datetime(2026, 6, 8, 10, 0), audiencia=aud)
    assert slot.weekday() == 5 and slot.hour == 21


def test_segmento_desconocido_usa_fallback() -> None:
    slot = timing.elegir_slot("formato_raro", datetime(2026, 6, 8, 10, 0), audiencia=[])
    assert slot.weekday() == 3 and slot.hour == 19
