"""Batch de memes para COMPLETAR la malla de 4/día con bandas aún no mandadas.

Elige bandas que NUNCA han pasado por aprobación (ni Sheet, ni Telegram, ni
descartadas) y que tienen fotos usables, genera caption+meme de la mejor foto
de cada una y las manda por el flujo ASÍNCRONO del motor
(approval.encolar_pendiente + enviar_a_telegram). El daemon resuelve: al
aprobar, cada meme toma el siguiente hueco libre de POSTING_SLOTS (4/día), así
que aprobar el batch va llenando la malla sin chocar horarios.

NO bloquea ni abre poller: convive con el approval-daemon.

Uso:
    python -m src.generate_relleno --dry-run     # solo lista la selección
    python -m src.generate_relleno [--max N]
"""
from __future__ import annotations

import argparse
import sys
import time as time_mod
from datetime import datetime, timedelta
from typing import Any

import pytz

import config
from src import approval, db, host
from src import caption as caption_mod
from src import compose as compose_mod

# Pausa entre envíos: Telegram topa ~20 mensajes/min por chat.
_PAUSA_ENVIO_S = 3.5


def candidatas(cx) -> list[dict[str, Any]]:
    """Una foto (la más nítida) por banda jamás enviada a aprobación.

    "Enviada" = cualquier fila de content_queue que ya vio Ricardo: mandada por
    el flujo asíncrono (aprobacion no nula) o por el plan/bot (en_sheet,
    publicado o descartado). Los borradores puros (plan de julio sin mandar) NO
    cuentan como enviados. Orden: prioridad asc, followers desc.
    """
    return db.rows(cx, """
        SELECT p.id AS photo_id, p.path, b.id AS band_id, b.nombre, b.tipo,
               b.ig_handle, b.prioridad, b.followers_ig
          FROM photos p JOIN bands b ON b.id = p.band_id
         WHERE p.usable_meme = 1 AND p.usada = 0 AND p.descartada = 0 AND b.activa = 1
           -- Los flyers NO son memes: van solo a los calendarios de eventos.
           AND NOT EXISTS (SELECT 1 FROM events e
                           WHERE e.tipo = 'flyer'
                             AND e.source_post_id = p.source_post_id)
           AND p.id NOT IN (SELECT photo_id FROM content_queue WHERE photo_id IS NOT NULL)
           AND b.id NOT IN (SELECT DISTINCT band_id FROM content_queue
                             WHERE band_id IS NOT NULL
                               AND (aprobacion IS NOT NULL
                                    OR status IN ('en_sheet', 'publicado', 'descartado')))
           -- La mejor foto de cada banda (mayor nitidez gana).
           AND p.id = (SELECT p2.id FROM photos p2
                        WHERE p2.band_id = b.id AND p2.usable_meme = 1
                          AND p2.usada = 0 AND p2.descartada = 0
                          AND NOT EXISTS (SELECT 1 FROM events e2
                                          WHERE e2.tipo = 'flyer'
                                            AND e2.source_post_id = p2.source_post_id)
                          AND p2.id NOT IN (SELECT photo_id FROM content_queue
                                             WHERE photo_id IS NOT NULL)
                        ORDER BY p2.nitidez DESC LIMIT 1)
         ORDER BY b.prioridad, b.followers_ig DESC
    """)


def huecos_del_mes(ahora: datetime) -> int:
    """Cuántos slots de POSTING_SLOTS siguen libres (vs el Sheet) hasta fin de mes.

    Misma malla que scheduler.next_free_slot: empieza MAÑANA.
    """
    from src import scheduler
    tz = pytz.timezone(config.TIMEZONE)
    slots = scheduler._slot_times()[: max(1, config.POSTS_PER_DAY)]
    taken = scheduler._taken_slots()
    libres = 0
    dia = ahora.date() + timedelta(days=1)
    while dia.month == ahora.month:
        for s in slots:
            cand = tz.localize(datetime.combine(dia, s))
            if cand > ahora and cand.strftime("%Y-%m-%dT%H:%M") not in taken:
                libres += 1
        dia += timedelta(days=1)
    return libres


def _generar_y_enviar(cx, fila: dict[str, Any]) -> int:
    """Caption + meme + Cloudinary + encolar + Telegram. Devuelve queue_id."""
    cap = caption_mod.generate_caption(banda=fila["nombre"], tipo=fila.get("tipo") or "banda")
    template = compose_mod.random_template()
    png = compose_mod.compose(caption=cap, foto_url=fila["path"],
                              template=template, row_id=f"rell{fila['photo_id']}")
    url = host.upload(str(png), public_id=f"relleno_{fila['photo_id']}")
    cap_final = cap + (f"\n\n@{fila['ig_handle']}" if fila.get("ig_handle") else "")
    qid = approval.encolar_pendiente(
        cx, tipo="meme", caption=cap_final, imagen_url=url,
        band_id=fila["band_id"], photo_id=fila["photo_id"], template=template)
    approval.enviar_a_telegram(cap_final, url, qid, regenerable=True)
    return qid


def main(max_posts: int | None = None, dry_run: bool = False) -> int:
    cx = db.connect()
    try:
        db.init_db(cx)
        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
        sel = candidatas(cx)
        if not sel:
            print("No quedan bandas sin enviar con fotos usables.")
            return 0
        if max_posts:
            sel = sel[:max_posts]
        print(f"{len(sel)} banda(s) nunca enviadas con foto usable:")
        for f in sel:
            print(f"  P{f['prioridad'] or 3} {f['nombre']} ({f.get('tipo') or 'banda'}, "
                  f"{f['followers_ig'] or 0} seguidores) foto {f['photo_id']}")
        if dry_run:
            return 0

        libres = huecos_del_mes(ahora)
        print(f"Huecos libres en la malla {config.POSTS_PER_DAY}/día hasta fin de mes: {libres}")
        ok, mal = 0, 0
        for i, f in enumerate(sel, 1):
            try:
                qid = _generar_y_enviar(cx, f)
                ok += 1
                print(f"  [{i}/{len(sel)}] ✅ {f['nombre']} → queue {qid}")
            except Exception as exc:  # un meme fallido no tumba el batch
                mal += 1
                print(f"  [{i}/{len(sel)}] ⚠️ {f['nombre']} falló: {exc}", file=sys.stderr)
            time_mod.sleep(_PAUSA_ENVIO_S)
        print(f"Batch listo: {ok} enviados a Telegram, {mal} fallidos. "
              "Aprueba/rechaza desde el chat; cada aprobado toma el siguiente hueco libre.")
        return 0 if mal == 0 else 1
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch de memes de bandas nunca enviadas")
    parser.add_argument("--max", type=int, default=None, help="tope de posts")
    parser.add_argument("--dry-run", action="store_true", help="solo listar la selección")
    args = parser.parse_args()
    try:
        sys.exit(main(args.max, args.dry_run))
    except KeyboardInterrupt:
        sys.exit("\nBatch interrumpido.")
