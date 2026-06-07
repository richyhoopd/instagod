"""Generación de anuncios (Fase 5): eventos parseados → tarjeta → Telegram → Sheet.

Toma eventos `status='nuevo'` con `fecha_evento` futura, compone la tarjeta
(plantilla `anuncio`: flyer completo + línea informativa) y la manda a aprobar
por Telegram, igual que los memes. Al aprobar:
- sube a Cloudinary,
- escribe la fila en el Sheet ya `approved` con slot URGENTE (antes del evento;
  `publish.py` la publica sin cambios),
- registra la fila en `content_queue` (tipo='anuncio') y marca el evento
  como 'anunciado'.

Regla editorial innegociable: la fecha y el lugar van FIELES. El sello
@gdlscene está en la plantilla y el tono, nunca en distorsionar el dato.

Uso:  python -m src.generate_anuncios
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from typing import Any

import pytz

import config
from src import compose as compose_mod
from src import db, host, sheets, telegram_bot

# Variantes deadpan-informativas. La rotación es la "regeneración": el dato no
# cambia, solo el encuadre. {banda} {fecha} {lugar} {ciudad} se rellenan fieles.
_VARIANTES_FECHA = [
    "Confirmado: {banda} toca este {fecha}{en_lugar}{en_ciudad}.",
    "{banda} se presenta el {fecha}{en_lugar}{en_ciudad}. El dato es real.",
    "Aviso a la escena: {banda}, {fecha}{en_lugar}{en_ciudad}.",
    "Esto sí está pasando: {banda} en vivo el {fecha}{en_lugar}{en_ciudad}.",
]
_VARIANTES_RELEASE = [
    "{banda} estrena material nuevo. Disponible desde el {fecha}.",
    "Hay música nueva de {banda} desde el {fecha}. Procedan con normalidad.",
    "Aviso: {banda} lanzó algo nuevo el {fecha}.",
]

_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
          "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def fecha_legible(iso: str) -> str:
    """'2026-06-21' → 'domingo 21 de junio'. Si no parsea, regresa el ISO tal cual."""
    try:
        d = datetime.fromisoformat(iso[:10])
        return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]}"
    except ValueError:
        return iso


def copy_anuncio(evento: dict[str, Any], banda: str, *, variante: int = 0) -> str:
    """Línea informativa del anuncio. Fecha y lugar SIEMPRE fieles al evento."""
    fecha = fecha_legible(evento["fecha_evento"])
    if evento.get("tipo") == "release":
        plantillas = _VARIANTES_RELEASE
        return plantillas[variante % len(plantillas)].format(banda=banda, fecha=fecha)
    plantillas = _VARIANTES_FECHA
    return plantillas[variante % len(plantillas)].format(
        banda=banda,
        fecha=fecha,
        en_lugar=f" en {evento['lugar']}" if evento.get("lugar") else "",
        en_ciudad=f", {evento['ciudad']}" if evento.get("ciudad") else "",
    )


def _eventos_anunciables(cx) -> list[dict[str, Any]]:
    hoy = datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d")
    return db.rows(cx, """
        SELECT e.*, b.nombre AS banda_nombre, b.ig_handle AS banda_handle
          FROM events e JOIN bands b ON b.id = e.band_id
         WHERE e.status = 'nuevo' AND e.fecha_evento IS NOT NULL
           AND e.fecha_evento >= ? AND e.irrelevante = 0
         ORDER BY e.fecha_evento
    """, (hoy,))


def _build_item(evento: dict[str, Any]) -> dict[str, Any] | None:
    """Compone la tarjeta del anuncio y arma el item de aprobación."""
    if not evento.get("flyer_path"):
        print(f"⚠️  evento #{evento['id']} sin flyer → lo salto (los release sin "
              "flyer se anuncian con foto de la banda en una iteración futura)")
        return None
    cap = copy_anuncio(evento, evento["banda_nombre"])
    png = compose_mod.compose(
        caption=cap,
        foto_url=evento["flyer_path"],
        template="anuncio",
        badge_text="agenda",
        row_id=f"ev{evento['id']}",
    )
    return {
        "row_id": f"ev{evento['id']}",
        "caption": cap,
        "image_path": str(png),
        "meta": {"evento": evento, "variante": 0},
    }


def _regenerate(item: dict[str, Any]) -> tuple[str, str]:
    """Siguiente variante del copy (el dato no cambia) y recompone la tarjeta."""
    meta = item["meta"]
    meta["variante"] += 1
    ev = meta["evento"]
    cap = copy_anuncio(ev, ev["banda_nombre"], variante=meta["variante"])
    png = compose_mod.compose(caption=cap, foto_url=ev["flyer_path"],
                              template="anuncio", badge_text="agenda",
                              row_id=item["row_id"])
    return cap, str(png)


async def main() -> None:
    cx = db.connect()
    try:
        db.init_db(cx)
        eventos = _eventos_anunciables(cx)
        if not eventos:
            print("No hay eventos nuevos con fecha futura. Parsea flyers o cura fechas en la GUI.")
            return

        print(f"Generando {len(eventos)} anuncio(s)…")
        items = []
        for ev in eventos:
            item = await asyncio.to_thread(_build_item, ev)
            if item:
                items.append(item)
        if not items:
            return
        registry = {it["row_id"]: it for it in items}

        decisions = await telegram_bot.run_approval_batch(items, _regenerate)

        for d in decisions:
            item = registry[str(d["row_id"])]
            ev = item["meta"]["evento"]
            if d["action"] != "approved":
                # El evento queda 'nuevo': corrígelo en la GUI y vuelve a correr.
                print(f"❌ evento #{ev['id']} rechazado (queda 'nuevo'; edítalo en la GUI)")
                continue

            # Un anuncio caduca: se publica DE INMEDIATO (el worker corre cada
            # hora y toma todo lo approved ya vencido). Esperar el slot genérico
            # le quita el valor de "me enteré a tiempo".
            ahora = datetime.now(pytz.timezone(config.TIMEZONE))
            url = host.upload(item["image_path"], public_id=f"anuncio_ev{ev['id']}")
            caption_final = d["caption"]
            if ev.get("banda_handle"):
                caption_final += f"\n\n@{ev['banda_handle']}"
            sheet_id = sheets.append_row(
                fecha_captura=datetime.now(pytz.timezone(config.TIMEZONE)).strftime("%Y-%m-%d"),
                banda=ev["banda_nombre"],
                tema_semilla=f"anuncio evento #{ev['id']}",
                caption_generado=item["caption"],
                caption_final=caption_final,
                imagen_compuesta_url=url,
                status=sheets.STATUS_APPROVED,
                scheduled_datetime=ahora.isoformat(),
            )
            db.insert(cx, "content_queue", tipo="anuncio", band_id=ev["band_id"],
                      event_id=ev["id"], status=db.QUEUE_EN_SHEET,
                      sheet_row_id=str(sheet_id))
            db.update(cx, "events", ev["id"], status="anunciado")
            print(f"✅ evento #{ev['id']} → Sheet id={sheet_id}, publica en la "
                  "próxima corrida del worker (≤1h)")
    finally:
        cx.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit("\nSesión interrumpida.")
