"""Registro declarativo de segmentos de contenido recurrente.

Cada Segment ata una CLAVE a su generador, su cadencia y su ventana de tráfico.
Agregar un formato nuevo (Pieza 2) = escribir el generador + registrar aquí.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


@dataclass(frozen=True)
class Segment:
    clave: str
    nombre: str
    generador: Callable[[Any, int], None]   # (cx, account_id) -> encola propuestas
    cadencia: dict                           # {"tipo": "semanal"|"mensual"|"diario", "dow"?, "dia_mes"?}
    ventana_trafico: str                     # clave en config.TIMING_DEFAULTS
    activo: bool = True


def ventana_de(clave: str, ahora: datetime) -> str:
    """Clave de periodo para idempotencia. Mensual si la clave termina en _mensual, semanal si no."""
    if clave.endswith("_mensual"):
        return f"{ahora.year}-{ahora.month:02d}"
    iso = ahora.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def ventana_mensual(ahora: datetime) -> str:
    return f"{ahora.year}-{ahora.month:02d}"


def toca_hoy(seg: Segment, ahora: datetime) -> bool:
    c = seg.cadencia
    if c["tipo"] == "diario":
        return True
    if c["tipo"] == "semanal":
        return ahora.weekday() == c["dow"]
    if c["tipo"] == "mensual":
        return ahora.day == c.get("dia_mes", 1)
    return False


def ventana_actual(seg: Segment, ahora: datetime) -> str:
    """Clave de ventana apropiada para el segmento dado su tipo de cadencia."""
    return ventana_mensual(ahora) if seg.cadencia["tipo"] == "mensual" else ventana_de(seg.clave, ahora)
