"""Salud del approval-daemon: latido + criterio de reinicio (watchdog anti-zombie).

El daemon es el ÚNICO poller de Telegram y corre bajo launchd con KeepAlive, que
solo revive el proceso cuando SALE. El modo de falla observado (7/jul→14/jul) fue
distinto: un error de red sin manejar mató el loop de polling pero el proceso NO
salió (quedó colgado, vivo), así que KeepAlive nunca lo recuperó y el bot quedó
sordo horas.

Prevención: el daemon escribe un LATIDO periódico sólo mientras el updater está
corriendo (`updater.running`); un watchdog externo (launchd cada pocos minutos)
reinicia el daemon si el latido falta o envejece. Cubre las dos fallas:
  - loop congelado  → no se escribe latido → viejo.
  - updater muerto pero loop vivo → el guard omite la escritura → viejo.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytz

import config

# Ruta del latido (fuera de git; junto a la DB).
HEARTBEAT_PATH = Path(config.resolve_db_path()).parent / ".approval_daemon_heartbeat"

# El daemon late cada 60s; 300s de silencio = poller muerto con margen holgado.
LATIDO_INTERVALO_SEG = 60
UMBRAL_REINICIO_SEG = 300


def _tz() -> "pytz.BaseTzInfo":
    return pytz.timezone(config.TIMEZONE)


def escribir_latido(ahora: datetime | None = None, *, path: Path | None = None) -> None:
    """Escribe el timestamp actual (ISO, tz de la escena) de forma atómica."""
    ahora = ahora or datetime.now(_tz())
    path = Path(path) if path is not None else HEARTBEAT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".hb_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(ahora.isoformat())
        os.replace(tmp, path)  # atómico: nunca deja un latido a medias
    finally:
        Path(tmp).unlink(missing_ok=True)


def leer_latido(*, path: Path | None = None) -> str | None:
    """Devuelve el ISO del último latido, o None si no existe/ilegible."""
    path = Path(path) if path is not None else HEARTBEAT_PATH
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except (FileNotFoundError, OSError):
        return None


def necesita_reinicio(
    heartbeat_iso: str | None,
    ahora: datetime,
    *,
    umbral_seg: int = UMBRAL_REINICIO_SEG,
) -> bool:
    """True si el latido falta, es ilegible, o es más viejo que `umbral_seg`."""
    if not heartbeat_iso:
        return True
    try:
        hb = datetime.fromisoformat(heartbeat_iso)
    except ValueError:
        return True
    if hb.tzinfo is None:
        hb = _tz().localize(hb)
    if ahora.tzinfo is None:
        ahora = _tz().localize(ahora)
    return (ahora - hb).total_seconds() > umbral_seg
