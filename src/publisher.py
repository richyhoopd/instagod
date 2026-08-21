"""ENTRYPOINT publisher local — publica en Instagram desde `content_queue`.

Complementa a `publish.py` (Actions, marcas CON Sheet): este proceso corre en
local/servidor propio y publica SOLO las marcas SIN SHEET_ID (la cola vive
íntegra en DB, sin espejo al Sheet). Regla anti-doble-publicación: una marca
la publica un único lado, nunca los dos.

Uso:  python -m src.publisher [--once]
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from typing import Any

import pytz
import requests

import config
from src import approval, db
from src import instagram as _instagram_mod
from src import marcas as marcas_mod


def filas_due(cx, account_id: int, ahora_iso: str) -> list[dict]:
    """Filas de `content_queue` de la marca listas para publicar: aprobadas,
    programadas y cuyo `scheduled_datetime` ya venció."""
    return db.rows(cx, """
        SELECT * FROM content_queue
         WHERE account_id = ? AND status = 'programado' AND aprobacion = 'aprobado'
           AND scheduled_datetime <= ?
         ORDER BY scheduled_datetime
    """, (account_id, ahora_iso))


def _urls_o_none(imagen_url: str) -> list[str] | None:
    """JSON-lista (carrusel) → list de urls; string plano (single) → None."""
    crudo = (imagen_url or "").strip()
    if not crudo.startswith("["):
        return None
    try:
        val = json.loads(crudo)
    except ValueError:
        return None
    return val if isinstance(val, list) else None


def _error_seguro(exc: Exception, creds: dict | None) -> str:
    """Texto de error SIN secretos, mismo criterio que
    `api/routers/pruebas._fallo` / `approval._error_seguro`: HTTPError → solo
    el status code; cualquier otro texto con los valores de `creds` (o, si
    `creds` es None -por ser gdlscene-, las credenciales globales) redactados.
    """
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    msg = str(exc)
    secretos = list(creds.values()) if creds else [config.IG_ACCESS_TOKEN, config.IG_USER_ID]
    for secreto in secretos:
        if secreto:
            msg = msg.replace(str(secreto), "***")
    return msg[:300]


def publicar_fila(cx, fila: dict, creds: dict | None, *, _ig: Any = None) -> bool:
    """Publica una fila due en Instagram y actualiza su estado.

    `creds`: kwargs `{"user_id", "token"}` de la marca, o None (gdlscene:
    `src.instagram` usa las credenciales globales de config).

    OK → status='publicado', ig_media_id, publicado_en, error=NULL, True.
    Excepción → status sin tocar (sigue 'programado', reintento el próximo
    ciclo), error redactado y truncado, False. Ambos casos notifican por
    Telegram (tolerante: `approval.notificar_resolucion` nunca lanza).
    """
    ig = _ig or _instagram_mod
    urls = _urls_o_none(fila.get("imagen_url") or "")
    caption = fila.get("caption") or ""
    try:
        if urls is not None:
            media_id = ig.publish_carousel(urls, caption, creds=creds)
        else:
            media_id = ig.publish(fila.get("imagen_url") or "", caption, creds=creds)
    except Exception as exc:  # noqa: BLE001
        error = _error_seguro(exc, creds)
        db.update(cx, "content_queue", fila["id"], error=error)
        _notificar(cx, fila["id"], f"⚠️ Error al publicar: {error}")
        return False
    else:
        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
        db.update(cx, "content_queue", fila["id"], status="publicado", ig_media_id=media_id,
                  publicado_en=ahora.isoformat(), error=None)
        _notificar(cx, fila["id"], "📤 Publicado en Instagram")
        return True


def _notificar(cx, queue_id: int, texto: str) -> None:
    """Envuelve `approval.notificar_resolucion` con tolerancia extra: nunca
    debe tumbar el publisher (ya es tolerante por dentro, pero un fallo
    inesperado -p. ej. de import- tampoco debe propagar)."""
    try:
        approval.notificar_resolucion(cx, queue_id, texto)
    except Exception as exc:  # noqa: BLE001
        print(f"[publisher] notificar_resolucion falló para queue {queue_id}: {exc}",
              file=sys.stderr)


def ciclo(cx, *, ahora: datetime | None = None, _ig: Any = None) -> int:
    """Un ciclo de publicación sobre todas las marcas activas.

    Anti-doble-publicación: marca CON SHEET_ID → se salta entera (la publica
    Actions vía Sheet). Marca sin credenciales IG → se salta con aviso, sin
    tocar sus filas. Devuelve el número de filas publicadas en este ciclo.
    """
    ahora = ahora or datetime.now(pytz.timezone(config.TIMEZONE))
    ahora_iso = ahora.isoformat()
    publicadas = 0
    for marca in marcas_mod.listar(cx):
        creds_marca = config.account_creds(marca.slug)
        if creds_marca.get("SHEET_ID"):
            continue  # la publica Actions (Sheet) — nunca los dos lados
        if not creds_marca.get("IG_USER_ID") or not creds_marca.get("IG_ACCESS_TOKEN"):
            print(f"[publisher] {marca.slug}: faltan credenciales IG, se salta",
                  file=sys.stderr)
            continue
        ig_creds = (None if marca.slug == "gdlscene" else
                    {"user_id": creds_marca["IG_USER_ID"], "token": creds_marca["IG_ACCESS_TOKEN"]})
        for fila in filas_due(cx, marca.id, ahora_iso):
            if publicar_fila(cx, fila, ig_creds, _ig=_ig):
                publicadas += 1
    return publicadas


def _dormir(segundos: float) -> None:
    time.sleep(segundos)


def main(once: bool = False) -> None:
    """Loop del publisher: un ciclo cada `PUBLISH_EVERY` segundos (default 300).
    `--once`/`once=True`: corre un solo ciclo y termina (cron/systemd)."""
    cx = db.connect()
    try:
        while True:
            n = ciclo(cx)
            if n:
                print(f"[publisher] publicadas {n} fila(s)", file=sys.stderr)
            if once:
                return
            _dormir(int(os.getenv("PUBLISH_EVERY", "300")))
    finally:
        cx.close()


if __name__ == "__main__":
    main(once="--once" in sys.argv)
