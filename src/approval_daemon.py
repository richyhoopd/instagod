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

import sys

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
from src import approval, audience, db, poller_lock


def _pretty(slot_iso: str) -> str:
    from datetime import datetime
    try:
        return datetime.fromisoformat(slot_iso).strftime("%d/%m a las %H:%M") + " (CDMX)"
    except ValueError:
        return slot_iso


def _aprobar_sync(qid: int) -> dict:
    """Abre+usa+cierra la conexión EN ESTE hilo (SQLite no cruza hilos).

    Corre vía asyncio.to_thread; por eso la conexión NO puede venir del hilo del
    event-loop — debe nacer aquí, donde se usa.
    Devuelve dict con {slot, inmediato} para que el caller arme el mensaje correcto.
    """
    cx = db.connect()
    try:
        aud = audience.cargar(cx)
        # Leemos el tipo ANTES de aprobar para saber si es inmediato.
        fila = db.get(cx, "content_queue", qid)
        inmediato = fila.get("tipo") == "anuncio"
        slot = approval.aprobar(cx, qid, audiencia=aud)
        return {"slot": slot, "inmediato": inmediato}
    finally:
        cx.close()


def _rechazar_sync(qid: int) -> None:
    cx = db.connect()
    try:
        approval.rechazar(cx, qid)
    finally:
        cx.close()


async def _resolver_msg(query, texto: str) -> None:
    """Edita el mensaje del callback sea texto o caption; si no se puede, ignora."""
    from telegram.error import BadRequest
    try:
        await query.edit_message_text(texto)
    except BadRequest:
        try:
            await query.edit_message_caption(caption=texto)
        except BadRequest:
            pass


async def on_aprobacion(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Resuelve los callbacks `aprobar:{qid}` / `rechazar:{qid}` del flujo asíncrono."""
    import asyncio

    query = update.callback_query
    await query.answer()
    accion, qid = approval.parsear_callback(query.data)

    if accion == "aprobar":
        resultado = await asyncio.to_thread(_aprobar_sync, qid)
        slot = resultado["slot"]
        if resultado["inmediato"]:
            texto = "✅ Aprobado — publicando ahora"
        else:
            texto = f"✅ Aprobado — se publica el {_pretty(slot.isoformat())}"
        await _resolver_msg(query, texto)
    else:
        await asyncio.to_thread(_rechazar_sync, qid)
        await _resolver_msg(query, "❌ Rechazado")


def main() -> None:
    if not config.TELEGRAM_CHAT_ID:
        raise RuntimeError("Falta TELEGRAM_CHAT_ID en el .env")
    poller_lock.adquirir()

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    solo_tu = filters.Chat(int(config.TELEGRAM_CHAT_ID))

    # Flujo asíncrono (motor): SOLO aprobar/rechazar (patrón estricto para no
    # tragarse los callbacks del flujo interactivo de bot.py).
    app.add_handler(CallbackQueryHandler(on_aprobacion, pattern=r"^(aprobar|rechazar):"))

    # Flujo interactivo REUSADO de bot.py (foto + approve/reject/regen/tpl +
    # replies 'texto:'/'feedback:' sobre la foto generada).
    app.add_handler(MessageHandler(filters.PHOTO & solo_tu, bot.on_photo))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & solo_tu, bot.on_reply))
    app.add_handler(CallbackQueryHandler(bot.on_callback,
                                         pattern=r"^(approve|reject|regen|tpl):"))
    app.add_error_handler(bot.on_error)

    print("Daemon de aprobación (único poller) escuchando. Ctrl+C para salir.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    sys.exit(main())
