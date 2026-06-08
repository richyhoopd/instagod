"""Selector de slot de alto tráfico (núcleo PURO).

Prioridad de fuente: (1) audiencia de IG (online_followers) si hay datos →
(2) [futuro] desempeño por hora de tus posts → (3) default por segmento.
Hoy IG devuelve online_followers VACÍO (<100 seguidores), así que arranca en (3);
el módulo ya consume (1) en cuanto audience.py la pueble.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import config


def _proximo(ahora: datetime, dow: int, hora: int) -> datetime:
    """Próximo datetime futuro que caiga en ese día-de-semana y hora."""
    cand = ahora.replace(hour=hora, minute=0, second=0, microsecond=0)
    dias = (dow - ahora.weekday()) % 7
    cand += timedelta(days=dias)
    if cand <= ahora:
        cand += timedelta(days=7)
    return cand


def elegir_slot(segmento: str, ahora: datetime, *,
                audiencia: list[dict[str, Any]] | None = None) -> datetime:
    """Próximo slot de alto tráfico para el segmento. PURO."""
    if audiencia:
        pico = max(audiencia, key=lambda a: a["valor"])
        return _proximo(ahora, pico["dow"], pico["hora"])
    dow, hora = config.TIMING_DEFAULTS.get(segmento, config.TIMING_DEFAULT_FALLBACK)
    return _proximo(ahora, dow, hora)
