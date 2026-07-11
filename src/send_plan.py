"""Envío del plan mensual a Telegram por el flujo ASÍNCRONO (compatible con el daemon).

Toma los borradores de memes que quedaron en `content_queue` tras planear el mes
(status='borrador', tipo='meme', sin mandar todavía → aprobacion IS NULL) y los
manda UNO POR UNO con `approval.enviar_a_telegram(..., regenerable=True)`:
compone caption+meme de la foto, sube a Cloudinary, ACTUALIZA la fila a
`aprobacion='pendiente'` y la envía con botones ✅/❌/🔄/🎨. Pausa anti-flood
entre envíos.

A diferencia del viejo `generate_plan.py` (bloqueante, abría su PROPIO poller y
chocaba con el daemon), este flujo NO abre poller: REQUIERE que el
approval-daemon (único poller permitido) esté vivo para procesar las
aprobaciones. Convive con el motor de segmentos igual que `generate_relleno`.

Uso:
    python -m src.send_plan --mes 2026-07 [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
import time as time_mod
from typing import Any

import config
from src import approval, db, host
from src import caption as caption_mod
from src import compose as compose_mod

# Pausa entre envíos: Telegram topa ~20 mensajes/min por chat (mismo valor que
# generate_relleno).
_PAUSA_ENVIO_S = 3.5


def borradores_del_mes(cx, mes: str) -> list[dict[str, Any]]:
    """Borradores de memes del mes AÚN NO enviados a aprobación.

    `aprobacion IS NULL` distingue el plan sin mandar de lo que ya fue enviado
    (aprobacion='pendiente') o resuelto. tipo='meme' evita tocar carruseles.
    """
    return db.rows(cx, """
        SELECT q.id AS qid, q.tema_semilla, q.photo_id,
               b.id AS band_id, b.nombre, b.tipo, b.ig_handle,
               p.path AS foto_path
          FROM content_queue q
          JOIN bands b ON b.id = q.band_id
          LEFT JOIN photos p ON p.id = q.photo_id
         WHERE q.status = ? AND q.aprobacion IS NULL AND q.tipo = 'meme'
           AND substr(q.scheduled_datetime,1,7) = ?
         ORDER BY q.scheduled_datetime
    """, (db.QUEUE_BORRADOR, mes))


def _componer_y_enviar(cx, fila: dict[str, Any]) -> int:
    """Caption + meme + Cloudinary + marcar pendiente + Telegram. Devuelve queue_id.

    Reusa la misma composición del flujo de memes (caption.generate_caption +
    compose + host.upload). NO inserta una fila nueva: ACTUALIZA el borrador del
    plan a 'pendiente' (una fila = un post), guardando el caption CON @handle
    (mismo contrato que approval._recomponer / generate_relleno).
    """
    if not fila.get("foto_path"):
        raise ValueError(f"queue {fila['qid']} sin foto → no se puede componer")
    cap = caption_mod.generate_caption(
        banda=fila["nombre"], tema_semilla=fila.get("tema_semilla") or None,
        tipo=fila.get("tipo") or "banda")
    template = compose_mod.random_template()
    png = compose_mod.compose(caption=cap, foto_url=fila["foto_path"],
                              template=template, row_id=f"plan{fila['qid']}")
    url = host.upload(str(png), public_id=f"plan_{fila['qid']}")
    cap_final = cap + (f"\n\n@{fila['ig_handle']}" if fila.get("ig_handle") else "")
    db.update(cx, "content_queue", fila["qid"],
              caption=cap_final, imagen_url=url, template=template,
              aprobacion="pendiente")
    approval.enviar_a_telegram(cap_final, url, fila["qid"], regenerable=True)
    return fila["qid"]


def main(mes: str, dry_run: bool = False) -> int:
    cx = db.connect()
    try:
        db.init_db(cx)
        filas = borradores_del_mes(cx, mes)
        if not filas:
            print(f"No hay borradores de meme por mandar en {mes}. "
                  "Genera/cura el plan en /plan primero.")
            return 0
        print(f"{len(filas)} borrador(es) de meme por mandar del plan {mes}:")
        for f in filas:
            print(f"  queue {f['qid']} · {f['nombre']} ({f.get('tipo') or 'banda'}) "
                  f"foto {f['photo_id']}")
        if dry_run:
            return 0
        ok, mal = 0, 0
        for i, f in enumerate(filas, 1):
            try:
                qid = _componer_y_enviar(cx, f)
                ok += 1
                print(f"  [{i}/{len(filas)}] ✅ {f['nombre']} → queue {qid} enviado")
            except Exception as exc:  # un meme fallido no tumba el lote
                mal += 1
                print(f"  [{i}/{len(filas)}] ⚠️ {f['nombre']} falló: {exc}", file=sys.stderr)
            time_mod.sleep(_PAUSA_ENVIO_S)
        print(f"Lote del plan {mes} listo: {ok} enviados a Telegram, {mal} fallidos. "
              "Aprueba/rechaza/regenera desde el chat; el daemon resuelve.")
        return 0 if mal == 0 else 1
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Envío async del plan mensual (compatible con daemon)")
    parser.add_argument("--mes", required=True, help="YYYY-MM")
    parser.add_argument("--dry-run", action="store_true", help="solo listar la selección")
    args = parser.parse_args()
    try:
        sys.exit(main(args.mes, args.dry_run))
    except KeyboardInterrupt:
        sys.exit("\nEnvío interrumpido.")
