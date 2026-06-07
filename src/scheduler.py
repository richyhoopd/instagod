"""Asignación de horarios de publicación.

`assign_slot()` encuentra el siguiente `scheduled_datetime` libre según
`POSTING_SLOTS` y `POSTS_PER_DAY`, sin colisionar con otros memes ya
calendarizados (approved o published).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import pytz

import config
from src import sheets


def _tz() -> "pytz.BaseTzInfo":
    return pytz.timezone(config.TIMEZONE)


def _slot_times() -> list[time]:
    """POSTING_SLOTS (["19:00", ...]) → objetos time ordenados."""
    out = []
    for s in config.POSTING_SLOTS:
        hh, mm = s.split(":")
        out.append(time(int(hh), int(mm)))
    return sorted(out) or [time(19, 0)]


def _taken_slots() -> set[str]:
    """Conjunto de scheduled_datetime (ISO, minuto) ya ocupados."""
    taken: set[str] = set()
    for r in sheets._records():
        status = str(r.get("status", "")).strip()
        if status not in (sheets.STATUS_APPROVED, sheets.STATUS_PUBLISHED):
            continue
        raw = str(r.get("scheduled_datetime", "")).strip()
        if raw:
            taken.add(raw[:16])  # YYYY-MM-DDTHH:MM
    return taken


def next_free_slot(now: datetime | None = None) -> datetime:
    """Calcula el próximo hueco libre a partir de mañana (o de `now`)."""
    tz = _tz()
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = tz.localize(now)

    slots = _slot_times()[: max(1, config.POSTS_PER_DAY)]
    taken = _taken_slots()

    day = now.date() + timedelta(days=1)  # empezamos mañana
    for _ in range(365):
        for slot in slots:
            candidate = tz.localize(datetime.combine(day, slot))
            if candidate.strftime("%Y-%m-%dT%H:%M") not in taken and candidate > now:
                return candidate
        day += timedelta(days=1)
    raise RuntimeError("No se encontró slot libre en el próximo año")


def assign_slot(row_id: int | str, *, now: datetime | None = None) -> str:
    """Asigna el próximo slot libre a `row_id`, lo escribe en el Sheet y lo devuelve (ISO)."""
    slot = next_free_slot(now)
    iso = slot.isoformat()
    sheets.update_row(row_id, scheduled_datetime=iso, status=sheets.STATUS_APPROVED)
    return iso


def next_free_slot_before(
    fecha_evento: str,
    *,
    now: datetime | None = None,
    taken: set[str] | None = None,
) -> datetime | None:
    """Modo "urgente" (anuncios): primer slot libre ANTES del evento.

    A diferencia de `next_free_slot`, considera los slots de HOY que aún no
    pasan (un anuncio no puede esperar al hueco genérico de mañana). El límite
    es el día del evento inclusive — anunciar "hoy toca X" sigue siendo útil —
    pero con tope a las 20:00 de ese día si la fecha no trae hora.
    Devuelve None si no hay slot posible (evento ya pasado).
    """
    tz = _tz()
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = tz.localize(now)

    limite = datetime.fromisoformat(fecha_evento[:10] + "T20:00")
    limite = tz.localize(limite)
    if limite <= now:
        return None

    slots = _slot_times()[: max(1, config.POSTS_PER_DAY)]
    taken = taken if taken is not None else _taken_slots()

    day = now.date()  # urgente: hoy cuenta
    while True:
        for slot in slots:
            candidate = tz.localize(datetime.combine(day, slot))
            if candidate <= now or candidate > limite:
                continue
            if candidate.strftime("%Y-%m-%dT%H:%M") not in taken:
                return candidate
        day += timedelta(days=1)
        if datetime.combine(day, time(0, 0)) > limite.replace(tzinfo=None):
            return None
