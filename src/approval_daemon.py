"""Daemon de aprobación: el ÚNICO poller de Telegram (reemplaza correr bot.py
y los generate_* a mano para resolver).

Multi-marca: una Application PTB por marca (con bot propio en .env),
todas corriendo en un solo event loop (`correr`). Sigue siendo el ÚNICO
poller — ahora con N bots en vez de uno.

Dos flujos conviven sobre cada polling:

  1. Flujo ASÍNCRONO (motor de segmentos): los generadores encolan propuestas con
     `approval.encolar_pendiente` y las mandan con `approval.enviar_a_telegram`
     (botones `aprobar:{qid}` / `rechazar:{qid}`). Este daemon los resuelve:
     aprobar → `approval.aprobar` (slot de alto tráfico, Sheet approved, en_sheet);
     rechazar → `approval.rechazar`. Estos handlers están en TODAS las marcas.

  2. Flujo INTERACTIVO (memes a mano): se REUSAN tal cual los handlers de `bot.py`
     (foto → genera → ✅/❌/🔄/🎨). No se mueve su lógica para no romper el flujo
     vivo; el daemon solo los registra. Sus callbacks usan prefijos distintos
     (`approve`/`reject`/`regen`/`tpl`) así que no chocan con `aprobar`/`rechazar`.
     Este flujo es SOLO de gdlscene (la marca original).

Guardia: un lock por archivo evita arrancar dos daemons (que compitan por el
mismo getUpdates).

Verificación manual (no hay test del poller, sí de sus helpers puros en
tests/test_approval.py y del ciclo de vida en tests/test_daemon_multibot.py):
  1. Asegúrate de que NO esté corriendo bot.py ni otro daemon.
  2. `.venv/bin/python -m src.approval_daemon`
  3. Manda una foto al bot de gdlscene → debe responder y generar (flujo
     interactivo intacto, solo esa marca).
  4. Encola una propuesta desde un generador de cualquier marca → llega el
     mensaje con Aprobar/Rechazar al bot de esa marca; al tocar Aprobar, la
     fila pasa a en_sheet con slot, y aparece la confirmación.
"""
from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
import time

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
from src import approval, audience, daemon_health, db, poller_lock
from src import marcas as marcas_mod


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


def _recomponer_sync(qid: int, accion: str) -> tuple[str, str]:
    """Regenera caption (🔄) o cicla plantilla (🎨); conexión nace en este hilo."""
    cx = db.connect()
    try:
        if accion == "regenerar":
            return approval.regenerar_meme(cx, qid)
        return approval.cambiar_plantilla(cx, qid)
    finally:
        cx.close()


async def on_recomponer(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Callbacks `regenerar:{qid}` / `plantilla:{qid}`: edita la MISMA foto del chat."""
    import asyncio

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto

    query = update.callback_query
    accion, qid = approval.parsear_callback(query.data)
    await query.answer("🎨 Recomponiendo…" if accion == "plantilla" else "🔄 Regenerando…")
    try:
        cap, url = await asyncio.to_thread(_recomponer_sync, qid, accion)
    except Exception as exc:  # LLM/Cloudinary caídos: avisar sin tumbar el daemon
        await query.message.reply_text(f"⚠️ No se pudo recomponer queue {qid}: {exc}")
        return
    teclado = InlineKeyboardMarkup(
        [[InlineKeyboardButton(b["text"], callback_data=b["callback_data"]) for b in fila]
         for fila in approval.construir_botones(qid, regenerable=True)])
    await query.edit_message_media(
        media=InputMediaPhoto(media=url, caption=cap[:1024]), reply_markup=teclado)


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


def marcas_con_bot(lista, creds_de=None):
    """PURO: (marca, creds) de las que tienen bot completo; avisa las que no."""
    creds_de = creds_de or config.account_creds
    pares = []
    for m in lista:
        creds = creds_de(m.slug)
        if creds.get("TELEGRAM_BOT_TOKEN") and creds.get("TELEGRAM_CHAT_ID"):
            pares.append((m, creds))
        else:
            faltan = [f"TELEGRAM_BOT_TOKEN__{m.slug.upper()}"
                      if not creds.get("TELEGRAM_BOT_TOKEN") else None,
                      f"TELEGRAM_CHAT_ID__{m.slug.upper()}"
                      if not creds.get("TELEGRAM_CHAT_ID") else None]
            print(f"[daemon] marca {m.slug} sin bot: faltan "
                  + ", ".join(v for v in faltan if v))
    return pares


def construir_app(token: str, chat_id: str, slug: str,
                  *, interactivo: bool = False) -> Application:
    """Una Application PTB por marca, con los mismos handlers de aprobación.

    Los handlers interactivos de bot.py (foto→meme, replies) son gdlscene-only.
    """
    app = Application.builder().token(token).build()
    app.bot_data["slug"] = slug
    app.add_handler(CallbackQueryHandler(on_aprobacion, pattern=r"^(aprobar|rechazar):"))
    app.add_handler(CallbackQueryHandler(on_recomponer, pattern=r"^(regenerar|plantilla):"))
    if interactivo:
        # int(chat_id) vive aquí adentro (único uso): un TELEGRAM_CHAT_ID no
        # numérico en una marca no-interactiva ya no revienta el arranque de
        # TODAS las marcas.
        solo_tu = filters.Chat(int(chat_id))
        app.add_handler(MessageHandler(filters.PHOTO & solo_tu, bot.on_photo))
        app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & solo_tu, bot.on_reply))
        app.add_handler(CallbackQueryHandler(bot.on_callback,
                                             pattern=r"^(approve|reject|regen|tpl):"))
    app.add_error_handler(bot.on_error)
    return app


def _todos_corriendo(apps) -> bool:
    return all(getattr(a.updater, "running", False) for a in apps)


async def _latido_loop_multi(apps) -> None:
    """Latido SOLO si TODOS los updaters corren: un bot caído = latido viejo →
    el watchdog reinicia el daemon completo (todas las marcas)."""
    daemon_health.escribir_latido()  # latido inicial: cubre el arranque
    while True:
        try:
            if _todos_corriendo(apps):
                daemon_health.escribir_latido()
        except Exception as e:  # el latido jamás tumba el daemon
            print(f"WARNING latido: {e}", file=sys.stderr)
        await asyncio.sleep(daemon_health.LATIDO_INTERVALO_SEG)


async def _esperar_senal() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()


RECARGA_SEG = 60   # cada cuánto revisa si cambiaron tokens/chats de marcas


def _huella(pares) -> tuple:
    """Huella de (slug, token, chat) de las marcas con bot: cambia → recargar."""
    return tuple(sorted((m.slug, c.get("TELEGRAM_BOT_TOKEN"), c.get("TELEGRAM_CHAT_ID"))
                        for m, c in pares))


def _pares_actuales() -> list:
    """Se llama cada RECARGA_SEG (60s): solo lee, sin migrar (init_db ya corrió
    una vez en main() antes del bucle)."""
    cx = db.connect()
    try:
        lista = marcas_mod.listar(cx)
    finally:
        cx.close()
    return marcas_con_bot(lista)


def _dormir(seg: float) -> None:
    time.sleep(seg)


async def _esperar_senal_o_cambio(huella, calcular, cada: float = RECARGA_SEG) -> str:
    """Termina con 'senal' (SIGINT/SIGTERM) o 'recarga' (cambió la huella)."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    while not stop.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=cada)
        if stop.is_set():
            break
        try:
            if await asyncio.to_thread(calcular) != huella:
                return "recarga"
        except Exception as e:  # noqa: BLE001 — un fallo de DB no tumba el daemon
            print(f"WARNING recarga: {e}", file=sys.stderr)
    return "senal"


async def correr(apps, *, esperar=None) -> str:
    """Ciclo de vida de N Applications en un solo loop.

    El `try` arranca ANTES de `initialize`: si una marca falla al arrancar
    (token revocado, etc.), las que ya levantaron igual se apagan en el
    `finally` — no queda un long-poll huérfano que choque (Conflict) en el
    siguiente arranque. La excepción original se propaga tras apagar todo.

    La task del latido se crea ANTES del bucle de `start_polling` (no después):
    si el bootstrap de una marca se atasca (`bootstrap_retries=-1` + red caída),
    el latido ya está corriendo y sigue cubriendo la ventana de arranque; el
    guard `_todos_corriendo` evita que escriba un latido falso mientras alguna
    marca todavía no levanta.

    `esperar` (corutina sin args) decide cuándo terminar; por default espera
    señal. Devuelve el motivo ('senal' | 'recarga') para que main() decida si
    reconstruir los bots.
    """
    latido = None
    motivo = "senal"
    try:
        for app in apps:
            await app.initialize()
        for app in apps:
            await app.start()
        latido = asyncio.create_task(_latido_loop_multi(apps))
        for app in apps:
            # bootstrap_retries=-1: parpadeo de red al arrancar reintenta indefinido
            await app.updater.start_polling(drop_pending_updates=True,
                                            bootstrap_retries=-1)
        motivo = await (esperar() if esperar else _esperar_senal()) or "senal"
    finally:
        if latido is not None:
            latido.cancel()
        for app in reversed(apps):
            with contextlib.suppress(Exception):
                await app.updater.stop()
        for app in reversed(apps):
            with contextlib.suppress(Exception):
                await app.stop()
        for app in reversed(apps):
            with contextlib.suppress(Exception):
                await app.shutdown()
    return motivo


def main() -> None:
    poller_lock.adquirir()
    cx = db.connect()
    try:
        db.init_db(cx)
    finally:
        cx.close()
    while True:
        pares = _pares_actuales()
        if not pares:
            print("[daemon] ninguna marca tiene TELEGRAM_BOT_TOKEN/CHAT_ID; "
                  f"reviso de nuevo en {RECARGA_SEG}s")
            _dormir(RECARGA_SEG)
            continue
        huella = _huella(pares)
        apps = [construir_app(creds["TELEGRAM_BOT_TOKEN"], creds["TELEGRAM_CHAT_ID"],
                              m.slug, interactivo=(m.slug == "gdlscene"))
                for m, creds in pares]
        print(f"Daemon multi-bot: {len(apps)} marca(s) — "
              + ", ".join(m.slug for m, _ in pares))

        async def _esperar(h=huella):
            return await _esperar_senal_o_cambio(
                h, lambda: _huella(_pares_actuales()), cada=RECARGA_SEG)
        motivo = asyncio.run(correr(apps, esperar=_esperar))
        if motivo != "recarga":
            break
        print("[daemon] cambiaron credenciales de Telegram: recargando bots")


if __name__ == "__main__":
    sys.exit(main())
