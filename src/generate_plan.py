"""Envío masivo del plan mensual a Telegram (badges → aprobación).

Lee las filas `content_queue` (status='listo') del mes, genera caption + imagen
de cada una y las manda TODAS a Telegram en un solo lote. Por cada post puedes:
  ✅ Aprobar · ❌ Rechazar · 🔄 Regenerar, o responder con 'texto:'/'feedback:'.

Al aprobar: sube a Cloudinary, escribe la fila en el Sheet ya `approved` con su
`scheduled_datetime` del plan (publish.py la publica a su hora), marca la foto
`usada` y la fila de la cola `publicado`. Al rechazar: la cola queda `descartado`.

Uso:  python -m src.generate_plan --mes 2026-07
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from typing import Any

import pytz

import config
from src import caption as caption_mod
from src import compose as compose_mod
from src import db, host, sheets, telegram_bot


def _filas_listas(cx, mes: str) -> list[dict[str, Any]]:
    return db.rows(cx, """
        SELECT q.id AS qid, q.tema_semilla, q.scheduled_datetime, q.photo_id,
               b.nombre AS banda_nombre, b.tipo, b.ig_handle,
               p.path AS foto_path
          FROM content_queue q
          JOIN bands b ON b.id = q.band_id
          LEFT JOIN photos p ON p.id = q.photo_id
         WHERE q.status = ? AND substr(q.scheduled_datetime,1,7) = ?
         ORDER BY q.scheduled_datetime
    """, (db.QUEUE_LISTO, mes))


def _build_meta(row: dict[str, Any]) -> dict[str, Any] | None:
    """Item con la metadata pero SIN componer aún (composición perezosa al enviar)."""
    if not row.get("foto_path"):
        print(f"⚠️  queue {row['qid']} sin foto → la salto")
        return None
    return {
        "row_id": row["qid"],
        "caption": None,
        "image_path": None,
        "build": _compose_item,  # telegram_bot lo llama justo antes de enviar
        "meta": {
            "banda": row["banda_nombre"], "integrante": "", "rol": "",
            "tema_semilla": row.get("tema_semilla") or None,
            "foto_url": row["foto_path"], "foto_inset_url": None,
            "tipo": row.get("tipo", "banda"), "template": None, "rechazados": [],
            "feedback": None, "texto_exacto": None,
            "scheduled": row["scheduled_datetime"], "photo_id": row["photo_id"],
            "ig_handle": row.get("ig_handle"),
        },
    }


def _compose_item(item: dict[str, Any]) -> tuple[str, str]:
    """Genera caption + compone el meme de un item del plan (perezoso)."""
    meta = item["meta"]
    cap = caption_mod.generate_caption(
        banda=meta["banda"], tema_semilla=meta["tema_semilla"], tipo=meta.get("tipo", "banda"))
    template = compose_mod.random_template()
    meta["template"] = template
    png = compose_mod.compose(caption=cap, foto_url=meta["foto_url"],
                              template=template, row_id=item["row_id"])
    return cap, str(png)


def _regenerate(item: dict) -> tuple[str, str]:
    meta = item["meta"]
    if meta.get("_solo_recomponer"):
        cap = item["caption"]
    elif meta.get("texto_exacto"):
        cap = meta["texto_exacto"]
    else:
        meta["rechazados"].append(item["caption"])
        cap = caption_mod.generate_caption(
            banda=meta["banda"], tema_semilla=meta["tema_semilla"],
            rechazados=meta["rechazados"], tipo=meta.get("tipo", "banda"),
            feedback=meta.get("feedback"),
        )
    png = compose_mod.compose(caption=cap, foto_url=meta["foto_url"],
                              template=meta.get("template", "clasica"), row_id=item["row_id"])
    return cap, str(png)


_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _fecha_humana(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]} a las {d:%H:%M}"
    except ValueError:
        return iso


def _resolver(item: dict, accion: str) -> str:
    """Procesa una decisión AL INSTANTE: sube, escribe el Sheet, agenda, marca cola.

    Abre su propia conexión (corre en un hilo). Devuelve el texto de confirmación
    para Telegram, con la fecha/hora de publicación.
    """
    meta = item["meta"]
    cx = db.connect()
    try:
        if accion != "approved":
            db.update(cx, "content_queue", item["row_id"], status=db.QUEUE_DESCARTADO)
            return "❌ Rechazado (sale del plan)"
        url = host.upload(item["image_path"], public_id=f"plan_{item['row_id']}")
        cap_final = item["caption"] + (f"\n\n@{meta['ig_handle']}" if meta.get("ig_handle") else "")
        sheet_id = sheets.append_row(
            fecha_captura=datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d"),
            banda=meta["banda"], tema_semilla=meta["tema_semilla"] or "",
            caption_generado=item["caption"], caption_final=cap_final,
            imagen_compuesta_url=url, status=sheets.STATUS_APPROVED,
            scheduled_datetime=meta["scheduled"],
        )
        db.update(cx, "content_queue", item["row_id"],
                  status=db.QUEUE_PUBLICADO, sheet_row_id=str(sheet_id), meme_url=url)
        if meta.get("photo_id"):
            db.update(cx, "photos", meta["photo_id"], usada=1)
        return f"✅ Aprobado — se publica el {_fecha_humana(meta['scheduled'])}"
    finally:
        cx.close()


async def main(mes: str) -> None:
    cx = db.connect()
    try:
        db.init_db(cx)
        filas = _filas_listas(cx, mes)
        if not filas:
            print(f"No hay plan 'listo' para {mes}. Genera y manda desde /plan.")
            return
        print(f"Mandando {len(filas)} post(s) del plan {mes} (se componen y envían 1×1)…")
        items = [it for row in filas if (it := _build_meta(row))]
        # resolve_fn procesa cada aprobación AL INSTANTE (Sheet + confirmación con fecha).
        await telegram_bot.run_approval_batch(items, _regenerate, resolve_fn=_resolver)
        print("Lote del plan resuelto.")
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Envío masivo del plan mensual")
    parser.add_argument("--mes", required=True, help="YYYY-MM")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.mes))
    except KeyboardInterrupt:
        sys.exit("\nEnvío interrumpido.")
