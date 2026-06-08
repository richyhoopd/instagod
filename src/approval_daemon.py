"""Daemon de aprobación: el ÚNICO poller de Telegram (reemplaza correr bot.py
y los generate_* a mano para resolver).

Dos flujos conviven sobre un solo polling:

  1. Flujo ASÍNCRONO (motor de segmentos): los generadores encolan propuestas con
     `approval.encolar_pendiente` y las mandan con `approval.enviar_a_telegram`
     (botones `aprobar:{qid}` / `rechazar:{qid}`). Este daemon los resuelve:
     aprobar → `approval.aprobar` (slot de alto tráfico, Sheet approved, en_sheet);
     rechazar → `approval.rechazar`.

  2. Flujo INTERACTIVO (memes a mano): se REUSAN tal cual los handlers de `bot.py`
     (foto → genera → ✅/❌/🔄/🎨). No se mueve su lógica para no romper el flujo
     vivo; el daemon solo los registra. Sus callbacks usan prefijos distintos
     (`approve`/`reject`/`regen`/`tpl`) así que no chocan con `aprobar`/`rechazar`.

Guardia: un lock por archivo evita arrancar dos daemons (que compitan por el
mismo getUpdates). `run_polling()`.

Verificación manual (no hay test del poller, sí de sus helpers puros en
tests/test_approval.py):
  1. Asegúrate de que NO esté corriendo bot.py ni otro daemon.
  2. `.venv/bin/python -m src.approval_daemon`
  3. Manda una foto al bot → debe responder y generar (flujo interactivo intacto).
  4. Encola una propuesta desde un generador → llega el mensaje con Aprobar/Rechazar;
     al tocar Aprobar, la fila pasa a en_sheet con slot, y aparece la confirmación.
"""
from __future__ import annotations

import atexit
import os
import sys
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import bot  # se REUSAN sus handlers (no se mueve su lógica)
import config
from src import approval, audience, db

LOCK_PATH = Path("/tmp/instagod_approval_daemon.lock")


def _adquirir_lock() -> None:
    """Evita dos pollers vivos: si el lock existe y su PID corre, aborta."""
    if LOCK_PATH.exists():
        try:
            pid = int(LOCK_PATH.read_text().strip())
            os.kill(pid, 0)  # señal 0: solo comprueba que el proceso existe
        except (ValueError, ProcessLookupError):
            pass  # lock huérfano: lo pisamos
        except PermissionError:
            raise SystemExit("Ya hay un daemon de aprobación corriendo (otro usuario).")
        else:
            raise SystemExit(f"Ya hay un daemon de aprobación corriendo (PID {pid}).")
    LOCK_PATH.write_text(str(os.getpid()))
    atexit.register(lambda: LOCK_PATH.unlink(missing_ok=True))


def _pretty(slot_iso: str) -> str:
    from datetime import datetime
    try:
        return datetime.fromisoformat(slot_iso).strftime("%d/%m a las %H:%M") + " (CDMX)"
    except ValueError:
        return slot_iso


async def on_aprobacion(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Resuelve los callbacks `aprobar:{qid}` / `rechazar:{qid}` del flujo asíncrono."""
    query = update.callback_query
    await query.answer()
    accion, qid = approval.parsear_callback(query.data)

    cx = db.connect()
    try:
        if accion == "aprobar":
            aud = audience.cargar(cx)
            slot = await _to_thread(approval.aprobar, cx, qid, audiencia=aud)
            await query.edit_message_text(
                f"✅ Aprobado — se publica el {_pretty(slot.isoformat())}")
        else:
            await _to_thread(approval.rechazar, cx, qid)
            await query.edit_message_text("❌ Rechazado")
    finally:
        cx.close()


async def _to_thread(fn, *args, **kwargs):
    import asyncio
    return await asyncio.to_thread(fn, *args, **kwargs)


def main() -> None:
    if not config.TELEGRAM_CHAT_ID:
        raise RuntimeError("Falta TELEGRAM_CHAT_ID en el .env")
    _adquirir_lock()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    solo_tu = filters.Chat(int(config.TELEGRAM_CHAT_ID))

    # Flujo asíncrono (motor): SOLO aprobar/rechazar (patrón estricto para no
    # tragarse los callbacks del flujo interactivo de bot.py).
    app.add_handler(CallbackQueryHandler(on_aprobacion, pattern=r"^(aprobar|rechazar):"))

    # Flujo interactivo REUSADO de bot.py (foto + approve/reject/regen/tpl).
    app.add_handler(MessageHandler(filters.PHOTO & solo_tu, bot.on_photo))
    app.add_handler(CallbackQueryHandler(bot.on_callback,
                                         pattern=r"^(approve|reject|regen|tpl):"))
    app.add_error_handler(bot.on_error)

    print("Daemon de aprobación (único poller) escuchando. Ctrl+C para salir.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    sys.exit(main())
