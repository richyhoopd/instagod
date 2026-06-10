"""Lock compartido del ÚNICO poller de Telegram (getUpdates).

Telegram solo admite un getUpdates por bot: dos pollers vivos chocan con
`telegram.error.Conflict: terminated by other getUpdates request` y se quedan
en bucle de error hasta que matas uno (pasó: un generador viejo huérfano peleó
12 h con el daemon). Este módulo centraliza el lock para que:

  - el daemon de aprobación (único poller permanente) lo ADQUIERA al arrancar, y
  - cualquier otro entrypoint que quiera abrir su PROPIO poller VERIFIQUE que no
    haya daemon vivo antes (`exigir_daemon_libre`), abortando limpio en vez de
    chocar y colgarse.

Un lock huérfano (su PID ya no corre) se pisa sin drama.
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path

LOCK_PATH = Path("/tmp/instagod_approval_daemon.lock")


def _pid_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)  # señal 0: solo comprueba existencia, no envía nada
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe (de otro usuario): cuenta como vivo
    return True


def daemon_pid() -> int | None:
    """PID del poller dueño del lock si sigue vivo; None si libre u huérfano."""
    if not LOCK_PATH.exists():
        return None
    try:
        pid = int(LOCK_PATH.read_text().strip())
    except (ValueError, OSError):
        return None
    return pid if _pid_vivo(pid) else None


def adquirir() -> None:
    """Para el daemon: toma el lock o aborta si ya hay otro poller vivo."""
    pid = daemon_pid()
    if pid is not None and pid != os.getpid():
        raise SystemExit(f"Ya hay un poller de Telegram corriendo (PID {pid}).")
    LOCK_PATH.write_text(str(os.getpid()))
    atexit.register(lambda: LOCK_PATH.unlink(missing_ok=True))


def exigir_daemon_libre(quien: str = "este proceso") -> None:
    """Para entrypoints que abren su PROPIO poller (bot.py, generate_*): si el
    daemon ya es el poller, aborta limpio en vez de chocar con Conflict."""
    pid = daemon_pid()
    if pid is None:
        return
    raise SystemExit(
        f"⛔ El daemon de aprobación ya es el poller de Telegram (PID {pid}).\n"
        f"   {quien} abriría un SEGUNDO poller → telegram.error.Conflict.\n"
        f"   • Memes a mano: manda la foto directo al bot; el daemon la procesa.\n"
        f"   • Agenda/música nueva: usa el flujo del motor (--segmento).\n"
        f"   • Si de verdad necesitas correr esto a mano, detén el daemon antes:\n"
        f"     launchctl unload ~/Library/LaunchAgents/com.gdlscene.approval-daemon.plist"
    )
