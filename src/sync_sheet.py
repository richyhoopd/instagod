"""Sincronización content_queue (SQLite) ↔ Google Sheet.

Ida (`sync`): filas de `content_queue` con status='listo' se escriben en el
Sheet con el formato que `generate.py` ya consume. Tras escribir, guarda el id
de la fila del Sheet en `sheet_row_id` y marca la cola como 'en_sheet'
(idempotente: correrlo dos veces no duplica filas).

Regreso (`pull_status`): lee el Sheet y refleja en la DB lo que pasó con cada
fila enviada — un rechazo libera la foto (usada=0) y descarta la fila de la
cola; un published la marca publicada.

La foto se manda como ruta local absoluta: `compose._to_src()` ya convierte
rutas locales a file:// para Playwright, así que el Proceso A no cambia.

Uso:
    python -m src.sync_sheet           # ida: cola → Sheet
    python -m src.sync_sheet --pull    # regreso: Sheet → cola/fotos
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pytz

import config
from src import db, sheets


def _abs_path(path: str | None) -> str:
    """Ruta de foto en DB (posiblemente relativa al repo) → absoluta para el Sheet."""
    if not path:
        return ""
    p = Path(path)
    return str(p if p.is_absolute() else (config.BASE_DIR / p))


def to_sheet_fields(q: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Mapea una fila de `db.queue_listos()` a columnas del Sheet (función pura)."""
    now = now or datetime.now(pytz.timezone(config.TIMEZONE))
    return {
        "fecha_captura": now.strftime("%Y-%m-%d"),
        "banda": q.get("banda_nombre") or "",
        "integrante": q.get("member_nombre") or "",
        "rol": q.get("member_rol") or "",
        "foto_url": _abs_path(q.get("photo_path")),
        "tema_semilla": q.get("tema_semilla") or "",
        "status": sheets.STATUS_PENDING,
    }


def sync(cx=None) -> int:
    """Empuja todas las filas 'listo' al Sheet. Devuelve cuántas sincronizó."""
    own = cx is None
    cx = cx or db.connect()
    try:
        listos = db.queue_listos(cx)
        if not listos:
            print("No hay filas 'listo' en content_queue. Nada que sincronizar.")
            return 0

        print(f"Sincronizando {len(listos)} fila(s) al Sheet…")
        n = 0
        for q in listos:
            fields = to_sheet_fields(q)
            if not fields["foto_url"]:
                print(f"⚠️  queue id={q['id']} sin foto → la salto (asigna photo_id en la GUI)")
                continue
            if q.get("photo_id") and not q.get("photo_usable"):
                # Solo van al Sheet fotos que pasaron el filtro (o que marcaste a mano).
                print(f"⚠️  queue id={q['id']}: foto no usable → la salto "
                      "(márcala 'usable para meme' en la GUI si sí sirve)")
                continue
            sheet_id = sheets.append_row(**fields)
            db.update(cx, "content_queue", q["id"],
                      status=db.QUEUE_EN_SHEET, sheet_row_id=str(sheet_id))
            if q.get("photo_id"):
                # Marcar la foto como usada evita reproponerla en futuras filas.
                db.update(cx, "photos", q["photo_id"], usada=1)
            print(f"✅ queue id={q['id']} → Sheet id={sheet_id} ({fields['banda']})")
            n += 1
        return n
    finally:
        if own:
            cx.close()


# Mapeo status del Sheet → status de content_queue (None = no cambiar).
_PULL_STATUS = {
    sheets.STATUS_REJECTED: db.QUEUE_DESCARTADO,
    sheets.STATUS_PUBLISHED: db.QUEUE_PUBLICADO,
    sheets.STATUS_ERROR: None,       # lo resuelves a mano; no tocamos la cola
    sheets.STATUS_APPROVED: None,    # sigue su curso normal hacia published
    sheets.STATUS_PENDING: None,
}


def pull_status(cx=None) -> int:
    """Refleja en la DB los status del Sheet. Devuelve cuántas filas cambió."""
    own = cx is None
    cx = cx or db.connect()
    try:
        # account_id = 1 (gdlscene): los ids de fila del Sheet son
        # auto-incrementales POR HOJA, así que un sheet_row_id de otra marca
        # puede colisionar con uno de gdlscene. pull_status solo lee el Sheet
        # de gdlscene (v1), así que cruzar sheet_row_id sin filtrar por cuenta
        # contaminaría filas de otras marcas con el status equivocado.
        enviadas = db.rows(cx, """
            SELECT id, photo_id, sheet_row_id, status FROM content_queue
             WHERE sheet_row_id IS NOT NULL
               AND status IN (?, ?)
               AND account_id = 1
        """, (db.QUEUE_EN_SHEET, db.QUEUE_PUBLICADO))
        if not enviadas:
            print("No hay filas enviadas al Sheet que rastrear.")
            return 0
        por_sheet_id = {str(q["sheet_row_id"]): q for q in enviadas}

        cambios = 0
        for r in sheets._records():
            q = por_sheet_id.get(str(r.get("id")))
            if q is None:
                continue
            nuevo = _PULL_STATUS.get(str(r.get("status", "")).strip().lower())
            if nuevo is None or nuevo == q["status"]:
                continue
            db.update(cx, "content_queue", q["id"], status=nuevo)
            if nuevo == db.QUEUE_DESCARTADO and q["photo_id"]:
                # El meme no salió: la foto vuelve a estar disponible.
                db.update(cx, "photos", q["photo_id"], usada=0)
            print(f"↩ queue id={q['id']}: {q['status']} → {nuevo}"
                  + (" (foto liberada)" if nuevo == db.QUEUE_DESCARTADO and q["photo_id"] else ""))
            cambios += 1
        if not cambios:
            print("Sin cambios: el Sheet y la cola ya están alineados.")
        return cambios
    finally:
        if own:
            cx.close()


if __name__ == "__main__":
    # Uso real:  python -m src.sync_sheet  |  python -m src.sync_sheet --pull
    import argparse
    parser = argparse.ArgumentParser(description="Sync cola ↔ Sheet")
    parser.add_argument("--pull", action="store_true",
                        help="regreso: reflejar status del Sheet en la DB")
    args = parser.parse_args()
    pull_status() if args.pull else sync()
