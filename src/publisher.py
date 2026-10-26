"""ENTRYPOINT publisher local — publica en Instagram y Facebook desde `content_queue`.

Complementa a `publish.py` (Actions, marcas CON Sheet): este proceso corre en
local/servidor propio y publica SOLO las marcas SIN SHEET_ID (la cola vive
íntegra en DB, sin espejo al Sheet). Regla anti-doble-publicación: una marca
la publica un único lado, nunca los dos.

Destinos: cada fila es de UNA plataforma (`plataforma` NULL/instagram →
Instagram; `facebook` → la Página de Facebook de la marca, solo si la marca
tiene FB_PAGE_ID + FB_PAGE_ACCESS_TOKEN y PUBLISHER_FB no vale "0"). Cada
destino corre aislado: si FB falla, IG sigue, y al revés. El resultado queda
por destino en `destinos_json`.

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
from src import facebook as _facebook_mod
from src import instagram as _instagram_mod
from src import marcas as marcas_mod

# Marca temporal en `error` mientras la llamada a IG está en vuelo: si el
# proceso muere a medias (crash window), la fila queda visible como estado
# error EN VEZ de reintentarse sola (que podría duplicar el post si en
# realidad sí se publicó) — filas_due la excluye; reprogramar() la revive.
MARCADOR_PUBLICANDO = "[publicando]"
# Tope de reintentos fallidos antes de dejar de intentar una fila sola;
# reprogramar() resetea `intentos` para revivirla.
MAX_INTENTOS = 5


def filas_due(cx, account_id: int, ahora_iso: str,
              plataforma: str = "instagram") -> list[dict]:
    """Filas de `content_queue` de la marca listas para publicar: aprobadas,
    programadas, cuyo `scheduled_datetime` ya venció, sin el marcador de
    "publicando" en vuelo (ver MARCADOR_PUBLICANDO) y con menos de
    MAX_INTENTOS fallidos. Solo la `plataforma` pedida (NULL cuenta como
    instagram) y nunca historias: tiktok y las historias del plan son
    calendario visual, se publican a mano."""
    return db.rows(cx, """
        SELECT * FROM content_queue
         WHERE account_id = ? AND status = 'programado' AND aprobacion = 'aprobado'
           AND scheduled_datetime <= ?
           AND (error IS NULL OR error NOT LIKE ? || '%')
           AND intentos < ?
           AND COALESCE(plataforma, 'instagram') = ?
           AND COALESCE(formato, '') <> 'historia'
         ORDER BY scheduled_datetime
    """, (account_id, ahora_iso, MARCADOR_PUBLICANDO, MAX_INTENTOS, plataforma))


def fb_activo(creds_marca: dict) -> bool:
    """FB es destino de la marca solo con credenciales propias y sin kill switch."""
    return (os.getenv("PUBLISHER_FB", "1") != "0"
            and _facebook_mod.tiene_creds(creds_marca))


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
    # Truncado a 200: mismo tope que approval._error_seguro y que la columna
    # `error` espera guardar (evita filas gigantes por un traceback largo).
    return msg[:200]


def _guardar_destino(cx, fila: dict, destino: str, resultado: dict) -> str:
    """Mezcla el resultado de un destino en `destinos_json` sin pisar los otros."""
    actual = db.get(cx, "content_queue", fila["id"]) or {}
    try:
        destinos = json.loads(actual.get("destinos_json") or "{}")
    except ValueError:
        destinos = {}
    destinos[destino] = {**resultado,
                         "en": datetime.now(pytz.timezone(config.TIMEZONE)).isoformat()}
    return json.dumps(destinos, ensure_ascii=False)


def _reclamar(cx, fila: dict) -> bool:
    # Claim atómico ANTES de llamar a la red (ver MARCADOR_PUBLICANDO arriba): el
    # UPDATE solo aplica si la fila SIGUE cumpliendo las condiciones de
    # filas_due en este instante. rowcount == 0 → otra instancia ya la tomó
    # (o dejó de calificar) entre el filas_due de este ciclo y esta llamada;
    # no es un modo soportado correr dos publishers a la vez, pero el claim
    # evita que un accidente duplique la publicación.
    cur = cx.execute(
        "UPDATE content_queue SET error=? WHERE id=? AND status='programado' "
        "AND aprobacion='aprobado' AND (error IS NULL OR error NOT LIKE ?||'%') "
        "AND intentos < ?",
        (MARCADOR_PUBLICANDO, fila["id"], MARCADOR_PUBLICANDO, MAX_INTENTOS),
    )
    cx.commit()
    return cur.rowcount > 0


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
    if not _reclamar(cx, fila):
        return False
    try:
        if fila.get("tipo") == "video":
            # Reel: la URL del mp4 vive en imagen_url (string plano) igual que
            # una imagen single — el motor de video la deja ahí al encolar.
            media_id = ig.publish_reel(fila.get("imagen_url") or "", caption,
                                       creds=creds)
        elif urls is not None:
            media_id = ig.publish_carousel(urls, caption, creds=creds)
        else:
            media_id = ig.publish(fila.get("imagen_url") or "", caption, creds=creds)
    except Exception as exc:  # noqa: BLE001
        error = _error_seguro(exc, creds)
        intentos = (fila.get("intentos") or 0) + 1
        # Nunca dejamos el marcador en un fallo CONOCIDO (la llamada lanzó):
        # el reintento del próximo ciclo es seguro, se sobreescribe con el
        # error real.
        db.update(cx, "content_queue", fila["id"], error=error, intentos=intentos,
                  destinos_json=_guardar_destino(cx, fila, "instagram",
                                                 {"ok": False, "error": error}))
        _notificar(cx, fila["id"], f"⚠️ Error al publicar en Instagram: {error}")
        return False
    else:
        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
        db.update(cx, "content_queue", fila["id"], status="publicado", ig_media_id=media_id,
                  publicado_en=ahora.isoformat(), error=None,
                  destinos_json=_guardar_destino(cx, fila, "instagram",
                                                 {"ok": True, "id": media_id}))
        _notificar(cx, fila["id"], "📤 Publicado en Instagram")
        return True


def publicar_fila_fb(cx, fila: dict, creds_marca: dict, *, _fb: Any = None) -> bool:
    """Publica una fila `plataforma='facebook'` en la Página de la marca.

    `creds_marca`: `config.account_creds(slug)`; sin FB_PAGE_ID/TOKEN lanza
    `SinCredencialesFB` dentro del try y queda como error de la fila (nunca
    se usan credenciales de otra marca). Video (tipo video o formato reel) →
    /videos; JSON-lista → carrusel; si no, foto. Mismo claim, reintentos y
    redacción que `publicar_fila`.
    """
    fb = _fb or _facebook_mod
    if not _reclamar(cx, fila):
        return False
    url = fila.get("imagen_url") or ""
    urls = _urls_o_none(url)
    caption = fila.get("caption") or ""
    secretos = {k: creds_marca.get(k) for k in ("FB_PAGE_ID", "FB_PAGE_ACCESS_TOKEN")}
    try:
        creds = fb.creds_de(creds_marca)
        if fila.get("tipo") == "video" or fila.get("formato") == "reel":
            res = fb.publicar_video(creds, url, caption)
        elif urls is not None:
            res = fb.publicar_carrusel(creds, urls, caption)
        else:
            res = fb.publicar_foto(creds, url, caption)
    except Exception as exc:  # noqa: BLE001
        error = _error_seguro(exc, secretos)
        db.update(cx, "content_queue", fila["id"], error=error,
                  intentos=(fila.get("intentos") or 0) + 1,
                  destinos_json=_guardar_destino(cx, fila, "facebook",
                                                 {"ok": False, "error": error}))
        _notificar(cx, fila["id"], f"⚠️ Error al publicar en Facebook: {error}")
        return False
    ahora = datetime.now(pytz.timezone(config.TIMEZONE))
    db.update(cx, "content_queue", fila["id"], status="publicado",
              publicado_en=ahora.isoformat(), error=None,
              destinos_json=_guardar_destino(cx, fila, "facebook",
                                             {"ok": True, "id": res.id, "url": res.url}))
    _notificar(cx, fila["id"], f"📤 Publicado en Facebook: {res.url}")
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


def ciclo(cx, *, ahora: datetime | None = None, _ig: Any = None,
          _fb: Any = None) -> int:
    """Un ciclo de publicación sobre todas las marcas activas.

    Anti-doble-publicación: marca CON SHEET_ID → se salta entera (la publica
    Actions vía Sheet). Por destino: sin credenciales IG se saltan sus filas
    de IG; sin credenciales FB (o PUBLISHER_FB=0) se saltan sus filas de FB,
    sin tocarlas. Un destino que revienta no detiene al otro ni a las demás
    marcas. Devuelve el número de filas publicadas en este ciclo.
    """
    ahora = ahora or datetime.now(pytz.timezone(config.TIMEZONE))
    ahora_iso = ahora.isoformat()
    publicadas = 0
    for marca in marcas_mod.listar(cx):
        creds_marca = config.account_creds(marca.slug)
        if creds_marca.get("SHEET_ID"):
            continue  # la publica Actions (Sheet) — nunca los dos lados
        publicadas += _ciclo_ig(cx, marca, creds_marca, ahora_iso, _ig)
        publicadas += _ciclo_fb(cx, marca, creds_marca, ahora_iso, _fb)
    return publicadas


def _ciclo_ig(cx, marca, creds_marca: dict, ahora_iso: str, _ig: Any) -> int:
    if not creds_marca.get("IG_USER_ID") or not creds_marca.get("IG_ACCESS_TOKEN"):
        print(f"[publisher] {marca.slug}: faltan credenciales IG, se salta IG",
              file=sys.stderr)
        return 0
    ig_creds = (None if marca.slug == "gdlscene" else
                {"user_id": creds_marca["IG_USER_ID"], "token": creds_marca["IG_ACCESS_TOKEN"]})
    n = 0
    try:
        for fila in filas_due(cx, marca.id, ahora_iso):
            if publicar_fila(cx, fila, ig_creds, _ig=_ig):
                n += 1
    except Exception as exc:  # noqa: BLE001
        print(f"[publisher] {marca.slug}: IG falló: {_error_seguro(exc, creds_marca)}",
              file=sys.stderr)
    return n


def _ciclo_fb(cx, marca, creds_marca: dict, ahora_iso: str, _fb: Any) -> int:
    if not fb_activo(creds_marca):
        return 0
    n = 0
    try:
        for fila in filas_due(cx, marca.id, ahora_iso, plataforma="facebook"):
            if publicar_fila_fb(cx, fila, creds_marca, _fb=_fb):
                n += 1
    except Exception as exc:  # noqa: BLE001
        print(f"[publisher] {marca.slug}: FB falló: {_error_seguro(exc, creds_marca)}",
              file=sys.stderr)
    return n


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
