"""Aprobación vía Telegram con botones inline.

Corre en polling: vive solo mientras `generate.py` está activo (no necesita
servidor). Por cada meme envía la imagen + caption y un teclado:
  ✅ Aprobar · ❌ Rechazar · 🔄 Regenerar

Además puedes RESPONDER a la imagen con un comando de texto:
  • "texto: el titular exacto que quiero"  → fija ese caption tal cual.
  • "feedback: hazlo más corto y sobre X"  → regenera el caption con esa guía.

`run_approval_batch` envía todo el lote y espera a que resuelvas cada uno.
`regenerate_fn(item)` lee item["meta"]["feedback"]/["texto_exacto"] y devuelve
(nuevo_caption, nueva_ruta_png).
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config

# item = {"row_id", "caption", "image_path", "meta": {...}}
Item = dict[str, Any]
RegenerateFn = Callable[[Item], "tuple[str, str] | Awaitable[tuple[str, str]]"]


def _keyboard(row_id: Any) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve:{row_id}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject:{row_id}"),
        ],
        [
            InlineKeyboardButton("🔄 Regenerar", callback_data=f"regen:{row_id}"),
            InlineKeyboardButton("🎨 Plantilla", callback_data=f"tpl:{row_id}"),
        ],
    ])


async def request_carousel_approval(caption: str, image_paths: list[str]) -> bool:
    """Manda un set de slides (galería) + botones y devuelve True si lo apruebas.

    Para posts de varias imágenes (agenda/música nueva en carrusel). Determinista:
    no hay 'regenerar' (el contenido sale de la DB).
    """
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()

    async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        action = query.data.split(":", 1)[0]
        await query.edit_message_text(
            f"{'✅ Aprobado' if action == 'approve' else '❌ Rechazado'} "
            f"({len(image_paths)} slide(s))")
        if not fut.done():
            fut.set_result(action == "approve")

    app.add_handler(CallbackQueryHandler(on_callback))
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)
    try:
        # Galería con todas las slides (así ves el carrusel completo de un jalón).
        abiertos = [open(p, "rb") for p in image_paths]
        try:
            media = [InputMediaPhoto(media=fh) for fh in abiertos]
            for i in range(0, len(media), 10):  # IG/Telegram topan en 10 por grupo
                await app.bot.send_media_group(chat_id=config.TELEGRAM_CHAT_ID,
                                               media=media[i:i + 10])
        finally:
            for fh in abiertos:
                fh.close()
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Aprobar", callback_data="approve:c"),
            InlineKeyboardButton("❌ Rechazar", callback_data="reject:c"),
        ]])
        await app.bot.send_message(chat_id=config.TELEGRAM_CHAT_ID,
                                   text=f"{caption}\n\n¿Publicar este carrusel?",
                                   reply_markup=kb)
        return await fut
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


async def run_approval_batch(items: list[Item], regenerate_fn: RegenerateFn,
                             resolve_fn=None) -> list[dict]:
    """Envía el lote y devuelve [{row_id, action, caption}] cuando todo se resuelve.

    `resolve_fn(item, action)` (opcional): se llama AL INSTANTE en cada aprobación/
    rechazo (no al final), hace los efectos (subir, escribir Sheet, agendar) y
    devuelve el texto de confirmación a mostrar en Telegram (con fecha/hora).
    """
    if not items:
        return []

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    registry: dict[str, Item] = {str(it["row_id"]): it for it in items}
    futures: dict[str, asyncio.Future] = {}
    msg_to_row: dict[int, str] = {}   # message_id de la foto → row_id (para replies)
    loop = asyncio.get_running_loop()

    async def _recompose(item: Item, row_id: str, msg) -> None:
        """Corre regenerate_fn y actualiza el mensaje de la foto con buttons."""
        if asyncio.iscoroutinefunction(regenerate_fn):
            new_caption, new_path = await regenerate_fn(item)
        else:
            new_caption, new_path = await asyncio.to_thread(regenerate_fn, item)
        item["caption"], item["image_path"] = new_caption, new_path
        with open(new_path, "rb") as fh:
            edited = await msg.edit_media(
                media=InputMediaPhoto(media=fh, caption=new_caption),
                reply_markup=_keyboard(row_id),
            )
        msg_to_row[edited.message_id] = row_id

    async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        action, row_id = query.data.split(":", 1)
        item = registry.get(row_id)
        if item is None:
            return

        if action == "regen":
            item.setdefault("meta", {})["feedback"] = None
            item["meta"]["texto_exacto"] = None
            item["meta"]["_solo_recomponer"] = False
            await query.edit_message_caption(caption="🔄 Regenerando…")
            await _recompose(item, row_id, query.message)
            return

        if action == "tpl":
            # Cambia la plantilla SIN tocar el caption (recompone la misma imagen).
            from src import compose as _compose
            meta = item.setdefault("meta", {})
            meta["template"] = _compose.siguiente_template(meta.get("template", "clasica"))
            meta["_solo_recomponer"] = True
            await query.edit_message_caption(caption=f"🎨 Plantilla → {meta['template']}…")
            await _recompose(item, row_id, query.message)
            meta["_solo_recomponer"] = False
            return

        accion = "approved" if action == "approve" else "rejected"
        # Efectos AL INSTANTE (subir/escribir Sheet/agendar) → confirmación con fecha.
        if resolve_fn is not None:
            await query.edit_message_caption(caption=f"{item['caption']}\n\n⏳ Procesando…")
            try:
                verdict = await asyncio.to_thread(resolve_fn, item, accion)
            except Exception as exc:  # noqa: BLE001
                verdict = f"⚠️ Error al procesar: {str(exc)[:120]}"
        else:
            verdict = "✅ Aprobado" if action == "approve" else "❌ Rechazado"
        await query.edit_message_caption(caption=f"{item['caption']}\n\n{verdict}")
        if not futures[row_id].done():
            futures[row_id].set_result({
                "row_id": item["row_id"], "action": accion, "caption": item["caption"],
            })

    async def on_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """Responder la foto con 'texto: …' o 'feedback: …' edita ese caption."""
        msg = update.message
        if not msg or not msg.reply_to_message:
            return
        row_id = msg_to_row.get(msg.reply_to_message.message_id)
        item = registry.get(row_id) if row_id else None
        if item is None:
            return
        texto = (msg.text or "").strip()
        low = texto.lower()
        item.setdefault("meta", {})
        if low.startswith("texto:"):
            item["meta"]["texto_exacto"] = texto.split(":", 1)[1].strip()
            item["meta"]["feedback"] = None
        elif low.startswith("feedback:"):
            item["meta"]["feedback"] = texto.split(":", 1)[1].strip()
            item["meta"]["texto_exacto"] = None
        else:
            return  # respuesta sin comando reconocido: la ignoramos
        await msg.reply_text("🔄 Aplicando…")
        await _recompose(item, row_id, msg.reply_to_message)

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT, on_reply))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        for row_id, item in registry.items():
            futures[row_id] = loop.create_future()
            # Composición PEREZOSA: si el item trae `build`, se compone justo antes
            # de enviarlo (así el primer meme llega en segundos, no tras componer todos).
            if not item.get("image_path") and item.get("build"):
                cap, path = await asyncio.to_thread(item["build"], item)
                item["caption"], item["image_path"] = cap, path
            with open(item["image_path"], "rb") as fh:
                sent = await app.bot.send_photo(
                    chat_id=config.TELEGRAM_CHAT_ID,
                    photo=fh,
                    caption=item["caption"],
                    reply_markup=_keyboard(row_id),
                )
            msg_to_row[sent.message_id] = row_id
        results = await asyncio.gather(*futures.values())
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    return list(results)
