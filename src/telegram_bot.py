"""Aprobación vía Telegram con botones inline.

Corre en polling: vive solo mientras `generate.py` está activo (no necesita
servidor). Por cada meme envía la imagen + caption y un teclado:
  ✅ Aprobar · ❌ Rechazar · 🔄 Regenerar

`run_approval_batch` envía todo el lote y espera a que resuelvas cada uno.
`regenerate_fn(item)` debe devolver (nuevo_caption, nueva_ruta_png).
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

import config

# item = {"row_id", "caption", "image_path", "meta": {...}}
Item = dict[str, Any]
RegenerateFn = Callable[[Item], "tuple[str, str] | Awaitable[tuple[str, str]]"]


def _keyboard(row_id: Any) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Aprobar", callback_data=f"approve:{row_id}"),
        InlineKeyboardButton("❌ Rechazar", callback_data=f"reject:{row_id}"),
        InlineKeyboardButton("🔄 Regenerar", callback_data=f"regen:{row_id}"),
    ]])


async def run_approval_batch(items: list[Item], regenerate_fn: RegenerateFn) -> list[dict]:
    """Envía el lote y devuelve [{row_id, action, caption}] cuando todo se resuelve."""
    if not items:
        return []

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    registry: dict[str, Item] = {str(it["row_id"]): it for it in items}
    futures: dict[str, asyncio.Future] = {}
    loop = asyncio.get_running_loop()

    async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()
        action, row_id = query.data.split(":", 1)
        item = registry.get(row_id)
        if item is None:
            return

        if action == "regen":
            await query.edit_message_caption(caption="🔄 Regenerando…")
            # regenerate_fn usa Playwright (sync): correrlo en un hilo, fuera del loop.
            if asyncio.iscoroutinefunction(regenerate_fn):
                new_caption, new_path = await regenerate_fn(item)
            else:
                new_caption, new_path = await asyncio.to_thread(regenerate_fn, item)
            item["caption"], item["image_path"] = new_caption, new_path
            with open(new_path, "rb") as fh:
                await query.edit_message_media(
                    media=InputMediaPhoto(media=fh, caption=new_caption),
                    reply_markup=_keyboard(row_id),
                )
            return

        # approve / reject → resolver
        verdict = "✅ Aprobado" if action == "approve" else "❌ Rechazado"
        await query.edit_message_caption(caption=f"{item['caption']}\n\n{verdict}")
        if not futures[row_id].done():
            futures[row_id].set_result({
                "row_id": item["row_id"],
                "action": "approved" if action == "approve" else "rejected",
                "caption": item["caption"],
            })

    app.add_handler(CallbackQueryHandler(on_callback))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        for row_id, item in registry.items():
            futures[row_id] = loop.create_future()
            with open(item["image_path"], "rb") as fh:
                await app.bot.send_photo(
                    chat_id=config.TELEGRAM_CHAT_ID,
                    photo=fh,
                    caption=item["caption"],
                    reply_markup=_keyboard(row_id),
                )
        results = await asyncio.gather(*futures.values())
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

    return list(results)
