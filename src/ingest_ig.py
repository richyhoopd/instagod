"""Ingesta de Instagram (Fase 2): perfiles y posts de las bandas → DB local.

Por cada banda activa con `ig_handle` baja: bio, followers, link externo, y los
posts recientes con imagen (foto + caption + fecha). Las imágenes van a
PHOTOS_DIR/<handle>/ (fuera de git) y se registran en `photos` sin clasificar
(eso es Fase 3). Idempotente: un post ya registrado no se vuelve a bajar.

Cómo habla con IG (lecciones duras de la primera sesión):
- Login por script → checkpoint + soft-block. Lo estable es importar la cookie
  `sessionid` del navegador (IG_SCRAPER_SESSIONID en .env).
- IG amarra el sessionid al user-agent del navegador de origen → IG_SCRAPER_UA
  debe ser su navigator.userAgent EXACTO ("useragent mismatch" si no).
- IG detecta el TLS de `requests` y responde 429 aunque la sesión sea válida →
  se usa `curl_cffi` imitando el TLS de Safari/Chrome.
- `web_profile_info` da el perfil (ya no incluye timeline); los posts salen de
  `/api/v1/feed/user/{id}/`. Dos requests por banda en total.

ToS de Meta: esto va contra los términos. Cuenta SECUNDARIA siempre, delays
aleatorios entre requests, límites bajos, ingesta puntual — no crawler 24/7.

Uso:
    python -m src.ingest_ig                    # todas las bandas activas con handle
    python -m src.ingest_ig banda1 banda2      # solo esos handles
    python -m src.ingest_ig --max-posts 6      # menos posts por banda
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from curl_cffi import requests as creq

import config
from src import db

_TIMEOUT = 30
# App-id web oficial de instagram.com; requerido por los endpoints /api/v1.
_IG_APP_ID = "936619743392459"
_BASE = "https://www.instagram.com/api/v1"
# Target de impersonación TLS de curl_cffi; coherente con el UA de iPhone Safari.
_IMPERSONATE = "safari184_ios"

_MEDIA_FOTO = 1
_MEDIA_VIDEO = 2
_MEDIA_CARRUSEL = 8


class IngestRateLimited(Exception):
    """IG respondió 429/401: hay que parar la sesión completa, no insistir."""


def _sleep() -> None:
    """Pausa aleatoria entre requests: el patrón humano reduce riesgo de bloqueo."""
    time.sleep(random.uniform(config.IG_INGEST_DELAY_MIN, config.IG_INGEST_DELAY_MAX))


def get_session() -> creq.Session:
    """Sesión curl_cffi con la cookie del navegador y su mismo user-agent."""
    if not (config.IG_SCRAPER_SESSIONID and config.IG_SCRAPER_UA):
        raise RuntimeError(
            "Faltan IG_SCRAPER_SESSIONID / IG_SCRAPER_UA en el .env. "
            "Saca ambos del navegador logueado: DevTools → Cookies → sessionid, "
            "y navigator.userAgent en la consola."
        )
    s = creq.Session(impersonate=_IMPERSONATE)
    s.cookies.set("sessionid", config.IG_SCRAPER_SESSIONID, domain=".instagram.com")
    s.headers.update({"x-ig-app-id": _IG_APP_ID, "User-Agent": config.IG_SCRAPER_UA})
    return s


def _get_json(session: creq.Session, url: str, params: dict | None = None) -> dict[str, Any]:
    resp = session.get(url, params=params, timeout=_TIMEOUT)
    if resp.status_code in (401, 429):
        raise IngestRateLimited(f"HTTP {resp.status_code} en {url}")
    resp.raise_for_status()
    return resp.json()


def fetch_profile(session: creq.Session, handle: str) -> dict[str, Any]:
    """Perfil de la banda (bio, followers, link, id interno) vía web_profile_info."""
    data = _get_json(session, f"{_BASE}/users/web_profile_info/", {"username": handle})
    user = data.get("data", {}).get("user")
    if not user:
        raise LookupError(f"IG no devolvió datos para @{handle} (¿handle correcto?)")
    return user


def fetch_posts(session: creq.Session, user_id: str, count: int) -> list[dict[str, Any]]:
    """Posts recientes del feed del usuario (incluye carruseles y captions)."""
    data = _get_json(session, f"{_BASE}/feed/user/{user_id}/", {"count": str(count)})
    return data.get("items", [])


def _best_url(media: dict[str, Any]) -> str | None:
    """URL de la imagen en su mayor resolución disponible."""
    candidates = media.get("image_versions2", {}).get("candidates", [])
    return candidates[0]["url"] if candidates else None


def _image_urls(item: dict[str, Any]) -> Iterator[tuple[int, str]]:
    """(índice, url) de cada imagen del post; los carruseles traen varias."""
    tipo = item.get("media_type")
    if tipo == _MEDIA_FOTO:
        url = _best_url(item)
        if url:
            yield 0, url
    elif tipo == _MEDIA_CARRUSEL:
        for i, media in enumerate(item.get("carousel_media", [])):
            if media.get("media_type") == _MEDIA_FOTO:
                url = _best_url(media)
                if url:
                    yield i, url
    # _MEDIA_VIDEO se ignora: video fuera de alcance


def _download(session: creq.Session, url: str, dest: Path) -> bool:
    """Baja una imagen a `dest`. Devuelve False (sin tronar) si falla."""
    try:
        resp = session.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as exc:  # noqa: BLE001 — un fallo de descarga no debe tirar la sesión
        print(f"   ⚠️  no se pudo bajar {url[:60]}…: {exc}")
        return False


def _resolve_user_id(session: creq.Session, cx, band: dict[str, Any]) -> str | None:
    """Devuelve el id numérico de IG de la banda, cacheándolo en `bands.ig_user_id`.

    Si ya está en caché evita la llamada a web_profile_info. Devuelve None solo
    si el perfil es privado (sin acceso a posts).
    """
    if band.get("ig_user_id"):
        return band["ig_user_id"]
    user = fetch_profile(session, band["ig_handle"])
    db.update(cx, "bands", band["id"],
              ig_user_id=user["id"],
              followers_ig=user.get("edge_followed_by", {}).get("count"),
              bio=(user.get("biography") or "").strip() or None,
              link_externo=user.get("external_url") or None)
    band["ig_user_id"] = user["id"]
    if user.get("is_private"):
        return None
    return user["id"]


def _marcar_scrapeada(cx, band_id: int) -> None:
    from datetime import datetime as _dt
    db.update(cx, "bands", band_id, scraped_at=_dt.now().isoformat(timespec="seconds"))


def _ingest_item(session: creq.Session, cx, band: dict[str, Any], band_dir: Path,
                 item: dict[str, Any]) -> list[dict[str, Any]]:
    """Baja e inserta las fotos de un post nuevo. Devuelve una fila por foto insertada.

    Asume que el post no existe aún en `photos` (el dedup lo hace quien llama).
    Cada fila trae los datos que el orquestador necesita para los pasos siguientes.
    """
    shortcode = item.get("code")
    if not shortcode:
        return []
    fecha = (datetime.fromtimestamp(item["taken_at"]).isoformat()
             if item.get("taken_at") else None)
    caption = ((item.get("caption") or {}).get("text") or "").strip() or None
    insertadas: list[dict[str, Any]] = []
    descargo = False
    for i, url in _image_urls(item):
        dest = band_dir / f"{shortcode}_{i}.jpg"
        if not dest.exists():
            if not _download(session, url, dest):
                continue
            descargo = True
        rel = str(dest.relative_to(config.BASE_DIR))
        db.insert(cx, "photos",
                  band_id=band["id"],
                  path=rel,
                  source_post_id=shortcode,
                  fecha=fecha,
                  caption_original=caption)
        insertadas.append({"band_id": band["id"], "ig_handle": band["ig_handle"],
                           "shortcode": shortcode, "caption": caption,
                           "path": rel, "fecha": fecha})
    if descargo:
        _sleep()  # pausa solo cuando realmente tocamos la red
    return insertadas


def ingest_band(session: creq.Session, cx, band: dict[str, Any], max_posts: int) -> int:
    """Ingesta una banda: actualiza el perfil y registra fotos nuevas. Devuelve cuántas."""
    handle = band["ig_handle"]
    user = fetch_profile(session, handle)

    db.update(cx, "bands", band["id"],
              ig_user_id=user["id"],
              followers_ig=user.get("edge_followed_by", {}).get("count"),
              bio=(user.get("biography") or "").strip() or None,
              link_externo=user.get("external_url") or None)
    print(f"   perfil: {user.get('edge_followed_by', {}).get('count')} followers"
          + (f" | link: {user['external_url']}" if user.get("external_url") else ""))
    if user.get("is_private"):
        print("   ⚠️  perfil privado: sin acceso a posts (síguelo desde la cuenta scraper)")
        return 0

    _sleep()
    items = fetch_posts(session, user["id"], max_posts)

    band_dir = config.resolve_photos_dir() / handle
    band_dir.mkdir(parents=True, exist_ok=True)

    nuevas = 0
    for item in items[:max_posts]:
        shortcode = item.get("code")
        if not shortcode:
            continue
        ya = db.rows(cx, "SELECT 1 FROM photos WHERE band_id = ? AND source_post_id = ?",
                     (band["id"], shortcode))
        if ya:
            continue  # post ya ingestado en una sesión anterior
        nuevas += len(_ingest_item(session, cx, band, band_dir, item))
    _marcar_scrapeada(cx, band["id"])
    return nuevas


def ingest(handles: list[str] | None = None, max_posts: int | None = None,
           rescan: bool = False) -> None:
    """Ingesta sobre bandas activas. Por default SALTA las ya scrapeadas.

    - Sin `handles`: solo bandas nuevas (scraped_at IS NULL); `rescan=True` incluye
      las ya scrapeadas (re-baja posts nuevos de todas).
    - Con `handles`: scrapea esas explícitamente, scrapeadas o no.
    """
    max_posts = max_posts or config.IG_INGEST_MAX_POSTS
    cx = db.connect()
    try:
        db.init_db(cx)
        bandas = [b for b in db.list_bands(cx) if b.get("ig_handle")]
        if handles:
            quiero = {h.lstrip("@").lower() for h in handles}
            bandas = [b for b in bandas if b["ig_handle"].lower() in quiero]
            faltan = quiero - {b["ig_handle"].lower() for b in bandas}
            for h in sorted(faltan):
                print(f"⚠️  @{h} no está en `bands` — agrégala en la GUI primero.")
        elif not rescan:
            # Default: solo las que nunca se han scrapeado (cuida la cuenta de IG).
            total = len(bandas)
            bandas = [b for b in bandas if not b.get("scraped_at")]
            saltadas = total - len(bandas)
            if saltadas:
                print(f"Saltando {saltadas} banda(s) ya scrapeada(s) (usa --rescan para incluirlas).")
        if not bandas:
            print("No hay bandas NUEVAS por scrapear. Todas las activas ya tienen fotos "
                  "(usa --rescan para re-bajar, o activa candidatas nuevas).")
            return

        session = get_session()
        print(f"Ingesta de {len(bandas)} banda(s), máx {max_posts} posts c/u…")
        for band in bandas:
            print(f"▶ @{band['ig_handle']} ({band['nombre']})")
            try:
                nuevas = ingest_band(session, cx, band, max_posts)
                print(f"   ✅ {nuevas} foto(s) nueva(s)")
            except LookupError as exc:
                print(f"   ❌ {exc}")
            except IngestRateLimited as exc:
                print(f"   ❌ {exc} — corto la sesión por seguridad; reintenta en unas horas.")
                break
            _sleep()
    finally:
        cx.close()


def novedades(handles: list[str] | None = None, max_posts: int | None = None,
              _cx=None) -> dict[str, Any]:
    """Chequeo ligero de NOVEDADES sobre bandas YA scrapeadas (Frente A).

    Por cada banda con `scraped_at IS NOT NULL` (las nuevas son territorio de
    `ingest()`): resuelve el user_id (caché de `ig_user_id` o fetch de perfil),
    baja la primera página de posts y CORTA en cuanto aparece un `source_post_id`
    ya presente en `photos` de esa banda — solo se descargan los nuevos.

    Banda que falle (sesión caída, 429, perfil 404) → se loguea y se continúa;
    el resumen lista las fallidas. `posts_nuevos` es el insumo de los pasos
    siguientes del orquestador (detección de releases, clasificación).

    `_cx`: conexión inyectable para tests; en producción se abre una nueva.
    """
    max_posts = max_posts or config.IG_INGEST_MAX_POSTS
    propia = _cx is None
    cx = _cx or db.connect()
    resumen: dict[str, Any] = {
        "bandas_revisadas": 0, "con_novedades": 0, "fotos_nuevas": 0,
        "fallidas": [], "posts_nuevos": [],
    }
    try:
        if propia:
            db.init_db(cx)
        bandas = [b for b in db.list_bands(cx)
                  if b.get("ig_handle") and b.get("scraped_at")]
        if handles:
            quiero = {h.lstrip("@").lower() for h in handles}
            bandas = [b for b in bandas if b["ig_handle"].lower() in quiero]
        if not bandas:
            print("No hay bandas scrapeadas que revisar.")
            return resumen

        session = get_session()
        print(f"Novedades de {len(bandas)} banda(s)…")
        for i, band in enumerate(bandas):
            handle = band["ig_handle"]
            print(f"▶ @{handle} ({band['nombre']})")
            resumen["bandas_revisadas"] += 1  # intentadas; las que truenan van a fallidas
            try:
                nuevos = _revisar_banda(session, cx, band, max_posts)
            except Exception as exc:  # noqa: BLE001 — una banda caída no debe tumbar la corrida
                print(f"   ❌ {exc} — se salta esta banda y se continúa.")
                resumen["fallidas"].append(handle)
            else:
                if nuevos:
                    resumen["con_novedades"] += 1
                    resumen["fotos_nuevas"] += len(nuevos)
                    resumen["posts_nuevos"].extend(nuevos)
                print(f"   ✅ {len(nuevos)} foto(s) nueva(s)")
            if i < len(bandas) - 1:
                _sleep()  # mismo delay anti-bot entre bandas
        return resumen
    finally:
        if propia:
            cx.close()


def _revisar_banda(session: creq.Session, cx, band: dict[str, Any],
                   max_posts: int) -> list[dict[str, Any]]:
    """Revisa una banda scrapeada; devuelve las filas de las fotos nuevas insertadas."""
    user_id = _resolve_user_id(session, cx, band)
    if user_id is None:
        return []  # perfil privado: nada que bajar
    items = fetch_posts(session, user_id, max_posts)

    band_dir = config.resolve_photos_dir() / band["ig_handle"]
    band_dir.mkdir(parents=True, exist_ok=True)

    nuevos: list[dict[str, Any]] = []
    for item in items:  # feed viene del más nuevo al más viejo
        shortcode = item.get("code")
        if not shortcode:
            continue
        ya = db.rows(cx, "SELECT 1 FROM photos WHERE band_id = ? AND source_post_id = ?",
                     (band["id"], shortcode))
        if ya:
            break  # primer post conocido → todo lo de aquí en adelante ya existe
        nuevos.extend(_ingest_item(session, cx, band, band_dir, item))
    _marcar_scrapeada(cx, band["id"])
    return nuevos


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingesta IG → DB local (Fase 2)")
    parser.add_argument("handles", nargs="*", help="handles específicos (vacío = todas)")
    parser.add_argument("--max-posts", type=int, default=None,
                        help=f"posts por banda (default {config.IG_INGEST_MAX_POSTS})")
    parser.add_argument("--rescan", action="store_true",
                        help="incluir bandas ya scrapeadas (default: solo nuevas)")
    parser.add_argument("--novedades", action="store_true",
                        help="modo novedades: revisa bandas ya scrapeadas y corta en post conocido")
    args = parser.parse_args()
    try:
        if args.novedades:
            res = novedades(args.handles or None, args.max_posts)
            print(f"\nResumen: {res['bandas_revisadas']} revisadas, "
                  f"{res['con_novedades']} con novedades, {res['fotos_nuevas']} fotos nuevas"
                  + (f", fallidas: {', '.join(res['fallidas'])}" if res["fallidas"] else ""))
        else:
            ingest(args.handles or None, args.max_posts, rescan=args.rescan)
    except KeyboardInterrupt:
        sys.exit("\nIngesta interrumpida.")
