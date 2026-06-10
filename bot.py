"""ENTRYPOINT — Bot de ingesta + generación (Proceso A, versión Telegram-first).

Le mandas una FOTO al bot con los datos en la descripción (separados por comas,
todos opcionales):

    banda, integrante, rol[, tema]

El bot: descarga la foto → genera el caption (DeepSeek) → compone el meme → te lo
manda con botones ✅ Aprobar · ❌ Rechazar · 🔄 Regenerar. Al aprobar: sube el
meme a Cloudinary, agenda el horario y escribe la fila en el Sheet. Reemplaza el
llenado manual del Sheet y a generate.py.

Uso:  python bot.py        (queda escuchando; Ctrl+C para salir)
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from src import caption as caption_mod
from src import compose as compose_mod
from src import db, host, poller_lock, scheduler, sheets

# token (= message_id del usuario) → item en proceso de aprobación
PENDING: dict[str, dict] = {}
# message_id de la FOTO que mandó el bot → token (para resolver replies)
MSG_TO_TOKEN: dict[int, str] = {}


def parse_reply_command(text: str | None) -> tuple[str, str] | None:
    """'texto: X' / 'feedback: Y' → (comando, contenido). PURO.

    None si no es un comando o viene vacío (un reply normal no dispara nada).
    """
    t = (text or "").strip()
    low = t.lower()
    for cmd in ("texto", "feedback"):
        if low.startswith(cmd + ":"):
            contenido = t.split(":", 1)[1].strip()
            return (cmd, contenido) if contenido else None
    return None


def _keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprobar", callback_data=f"approve:{token}"),
            InlineKeyboardButton("❌ Rechazar", callback_data=f"reject:{token}"),
        ],
        [
            InlineKeyboardButton("🔄 Regenerar", callback_data=f"regen:{token}"),
            InlineKeyboardButton("🎨 Plantilla", callback_data=f"tpl:{token}"),
        ],
    ])


# Alias de plantilla → key real. Se pone como prefijo "keyword:" al inicio del mensaje.
TEMPLATE_ALIASES = {
    "clasica": "clasica", "clásica": "clasica", "classic": "clasica", "normal": "clasica", "1": "clasica",
    "verde": "verde", "green": "verde", "2": "verde",
    "onion": "onion", "the onion": "onion", "3": "onion",
}


def parse_caption(text: str | None) -> dict:
    """'[plantilla:] banda, integrante, rol, tema' → dict.

    Plantilla opcional como prefijo 'verde:' / 'onion:' (default clásica). Campos
    posicionales separados por comas; vacíos/ausentes = None.
    """
    text = (text or "").strip()
    template = None  # None = elegir con pesos (clásica casi siempre, verde/onion ocasional)
    head = text.split(",", 1)[0]  # parte antes de la primera coma
    if ":" in head:
        kw, rest = text.split(":", 1)
        if kw.strip().lower() in TEMPLATE_ALIASES:
            template = TEMPLATE_ALIASES[kw.strip().lower()]
            text = rest.strip()
    if template is None:
        template = compose_mod.random_template()

    # @handles de Instagram → para etiquetar al artista en el post (no en el texto del meme).
    menciones = re.findall(r"@[A-Za-z0-9_.]+", text)
    if menciones:
        text = re.sub(r"@[A-Za-z0-9_.]+", "", text)

    parts = [p.strip() for p in text.split(",")]
    def at(i: int) -> str | None:
        return parts[i] if i < len(parts) and parts[i] else None
    return {"template": template, "banda": at(0), "integrante": at(1), "rol": at(2),
            "tema": at(3), "menciones": menciones}


def _generate(item: dict) -> tuple[str, str]:
    """Sync (Playwright): genera caption + compone meme desde la foto local."""
    cap = caption_mod.generate_caption(
        banda=item["banda"], integrante=item["integrante"], rol=item["rol"],
        tema_semilla=item["tema"], rechazados=item.get("rechazados") or None,
        tipo=db.tipo_de_actor(item["banda"]),
    )
    png = compose_mod.compose(
        caption=cap, foto_url=item["photo_path"], template=item.get("template", "clasica")
    )
    return cap, str(png)


def _approve(item: dict) -> str:
    """Sube el meme, crea la fila y le asigna horario. Devuelve el slot ISO.

    La caption FINAL (la que se publica en IG) lleva el texto del meme + los @handles
    para etiquetar al artista. El texto del meme (la imagen) queda limpio, sin @.
    """
    meme_url = host.upload(item["image_path"])
    menciones = item.get("menciones") or []
    caption_final = item["caption"]
    if menciones:
        caption_final = f"{item['caption']}\n\n{' '.join(menciones)}"
    row_id = sheets.append_row(
        banda=item["banda"] or "",
        integrante=item["integrante"] or "",
        rol=item["rol"] or "",
        tema_semilla=item["tema"] or "",
        caption_generado=item["caption"],
        caption_final=caption_final,
        imagen_compuesta_url=meme_url,
        status=sheets.STATUS_PENDING,
        notas="ingresado por Telegram",
    )
    return scheduler.assign_slot(row_id)  # → status=approved + scheduled_datetime


def _pretty(slot_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(slot_iso)
        return dt.strftime("%d/%m a las %H:%M") + " (CDMX)"
    except ValueError:
        return slot_iso


async def on_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    data = parse_caption(msg.caption)

    # descarga la foto de mayor resolución
    tg_file = await msg.photo[-1].get_file()
    compose_mod.OUT_DIR.mkdir(exist_ok=True)
    photo_path = compose_mod.OUT_DIR / f"in_{tg_file.file_unique_id}.jpg"
    await tg_file.download_to_drive(str(photo_path))

    quien = " · ".join(v for v in (data["banda"], data["integrante"], data["rol"]) if v) or "(sin datos)"
    tags = f" · etiquetar: {' '.join(data['menciones'])}" if data.get("menciones") else ""
    await msg.reply_text(f"📥 Recibí la foto [{quien}] · plantilla: {data['template']}{tags}. Generando…")

    item = {**data, "photo_path": str(photo_path), "rechazados": []}
    cap, png = await asyncio.to_thread(_generate, item)
    item["caption"], item["image_path"] = cap, png

    token = str(msg.message_id)
    PENDING[token] = item
    with open(png, "rb") as fh:
        sent = await msg.reply_photo(photo=fh, caption=cap, reply_markup=_keyboard(token))
    MSG_TO_TOKEN[sent.message_id] = token


async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    action, token = query.data.split(":", 1)
    item = PENDING.get(token)
    if item is None:
        await query.edit_message_caption(caption="(este meme ya expiró, vuelve a mandar la foto)")
        return

    if action == "regen":
        await query.edit_message_caption(caption="🔄 Regenerando…")
        item["rechazados"].append(item["caption"])
        cap, png = await asyncio.to_thread(_generate, item)
        item["caption"], item["image_path"] = cap, png
        with open(png, "rb") as fh:
            await query.edit_message_media(
                media=InputMediaPhoto(media=fh, caption=cap),
                reply_markup=_keyboard(token),
            )
        return

    if action == "tpl":
        # Cambia la plantilla SIN regenerar el caption (recompone la misma imagen).
        item["template"] = compose_mod.siguiente_template(item.get("template", "clasica"))
        await query.edit_message_caption(caption=f"🎨 Plantilla → {item['template']}…")
        png = await asyncio.to_thread(
            compose_mod.compose, caption=item["caption"],
            foto_url=item["photo_path"], template=item["template"])
        item["image_path"] = str(png)
        with open(png, "rb") as fh:
            await query.edit_message_media(
                media=InputMediaPhoto(media=fh, caption=item["caption"]),
                reply_markup=_keyboard(token),
            )
        return

    if action == "reject":
        await query.edit_message_caption(caption=f"{item['caption']}\n\n❌ Rechazado")
        PENDING.pop(token, None)
        return

    # approve
    await query.edit_message_caption(caption=f"{item['caption']}\n\n⏳ Subiendo y agendando…")
    slot = await asyncio.to_thread(_approve, item)
    await query.edit_message_caption(
        caption=f"{item['caption']}\n\n✅ Aprobado — se publica el {_pretty(slot)}"
    )
    PENDING.pop(token, None)


async def on_reply(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Responder la foto del bot con 'texto: …' (caption exacto, sin LLM) o
    'feedback: …' (regenera siguiendo la guía) y se edita el mismo mensaje."""
    msg = update.message
    if msg is None or msg.reply_to_message is None:
        return
    cmd = parse_reply_command(msg.text)
    if cmd is None:
        return  # reply normal: no es para nosotros
    token = MSG_TO_TOKEN.get(msg.reply_to_message.message_id)
    item = PENDING.get(token) if token else None
    if item is None:
        await msg.reply_text("(no encuentro ese meme — expiró o no es del flujo de fotos; "
                             "vuelve a mandar la foto)")
        return

    tipo, contenido = cmd
    await msg.reply_text("✍️ Editando…" if tipo == "texto" else "🔄 Regenerando con tu guía…")
    if tipo == "texto":
        item["caption"] = contenido
        png = await asyncio.to_thread(
            compose_mod.compose, caption=contenido,
            foto_url=item["photo_path"], template=item.get("template", "clasica"))
    else:
        def _regen_feedback():
            cap = caption_mod.generate_caption(
                banda=item["banda"], integrante=item["integrante"], rol=item["rol"],
                tema_semilla=item["tema"], rechazados=item.get("rechazados") or None,
                tipo=db.tipo_de_actor(item["banda"]), feedback=contenido)
            p = compose_mod.compose(caption=cap, foto_url=item["photo_path"],
                                    template=item.get("template", "clasica"))
            return cap, p
        cap, png = await asyncio.to_thread(_regen_feedback)
        item["caption"] = cap
    item["image_path"] = str(png)
    with open(png, "rb") as fh:
        await ctx.bot.edit_message_media(
            chat_id=msg.chat_id, message_id=msg.reply_to_message.message_id,
            media=InputMediaPhoto(media=fh, caption=item["caption"]),
            reply_markup=_keyboard(token),
        )


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Reporta cualquier error del handler al chat, en vez de fallar en silencio."""
    import traceback
    err = "".join(traceback.format_exception_only(type(ctx.error), ctx.error)).strip()
    print("ERROR:", err)
    traceback.print_exception(type(ctx.error), ctx.error, ctx.error.__traceback__)
    try:
        if isinstance(update, Update) and update.effective_chat:
            await ctx.bot.send_message(update.effective_chat.id, f"⚠️ Error generando: {err}")
    except Exception:
        pass


def main() -> None:
    if not config.TELEGRAM_CHAT_ID:
        raise RuntimeError("Falta TELEGRAM_CHAT_ID en el .env")
    poller_lock.exigir_daemon_libre("bot.py")
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    solo_tu = filters.Chat(int(config.TELEGRAM_CHAT_ID))  # ignora a cualquier otro
    app.add_handler(MessageHandler(filters.PHOTO & solo_tu, on_photo))
    app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & solo_tu, on_reply))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_error_handler(on_error)
    print("Bot escuchando. Mándale una foto con 'banda, integrante, rol' en la descripción.")
    print("Ctrl+C para salir.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
