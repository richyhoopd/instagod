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
from src import db, ig_accounts

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


def get_session(cuenta: dict[str, Any] | None = None) -> creq.Session:
    """Sesión curl_cffi para una cuenta del pool (cookie + su user-agent exacto).

    Sin `cuenta` cae a la cookie del `.env` (compatibilidad con el setup viejo).
    """
    sessionid = (cuenta or {}).get("sessionid") or config.IG_SCRAPER_SESSIONID
    ua = (cuenta or {}).get("ua") or config.IG_SCRAPER_UA
    if not (sessionid and ua):
        raise RuntimeError(
            "Faltan cuentas scraper. Agrega data/ig_accounts.json o "
            "IG_SCRAPER_SESSIONID / IG_SCRAPER_UA en el .env (sácalos del "
            "navegador logueado: DevTools → Cookies → sessionid, y navigator.userAgent)."
        )
    s = creq.Session(impersonate=_IMPERSONATE)
    s.cookies.set("sessionid", sessionid, domain=".instagram.com")
    s.headers.update({"x-ig-app-id": _IG_APP_ID, "User-Agent": ua})
    return s


class SesionRotatoria:
    """Pool de cuentas scraper con rotación: al quemarse una, salta a la siguiente.

    Arranca con la primera cuenta sana del pool. `rotar_por_quemada()` marca la
    activa en reposo (persistido en el JSON) y cambia a la siguiente sana; si el
    pool queda agotado, deja `session=None`. El reposo sobrevive entre corridas.
    """

    def __init__(self, ahora=None):
        self._ahora = ahora
        self.cuentas = ig_accounts.cargar()
        self.cuenta = ig_accounts.siguiente_sana(self.cuentas, ahora=ahora)
        self.session = get_session(self.cuenta) if self.cuenta else None

    def disponible(self) -> bool:
        return self.cuenta is not None

    def rotar_por_quemada(self) -> bool:
        """Quema la cuenta activa y pasa a la siguiente sana. False si no quedan."""
        if self.cuenta:
            ig_accounts.marcar_quemada(self.cuenta["label"], ahora=self._ahora)
        self.cuentas = ig_accounts.cargar()  # relee para ver el reposo recién escrito
        self.cuenta = ig_accounts.siguiente_sana(self.cuentas, ahora=self._ahora)
        self.session = get_session(self.cuenta) if self.cuenta else None
        return self.cuenta is not None


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

        rot = SesionRotatoria()
        if not rot.disponible():
            print("No hay cuentas scraper sanas (todas en reposo o sin configurar).")
            return
        print(f"Ingesta de {len(bandas)} banda(s), máx {max_posts} c/u — cuenta '{rot.cuenta['label']}'…")
        for band in bandas:
            print(f"▶ @{band['ig_handle']} ({band['nombre']})")
            while True:
                try:
                    nuevas = ingest_band(rot.session, cx, band, max_posts)
                    print(f"   ✅ {nuevas} foto(s) nueva(s)")
                    break
                except LookupError as exc:
                    print(f"   ❌ {exc}")
                    break
                except IngestRateLimited as exc:
                    print(f"   ⚠️ {exc} — quemo '{rot.cuenta['label']}' y roto.")
                    if rot.rotar_por_quemada():
                        print(f"   ↻ ahora con cuenta '{rot.cuenta['label']}'.")
                        continue  # reintenta esta banda con la nueva cuenta
                    print("   🛑 todas las cuentas en reposo: corto la ingesta.")
                    return
            _sleep()
    finally:
        cx.close()


def novedades(handles: list[str] | None = None, max_posts: int | None = None,
              limite: int | None = None, max_bloqueos: int | None = None,
              _cx=None) -> dict[str, Any]:
    """Chequeo ligero de NOVEDADES sobre bandas YA scrapeadas (Frente A).

    Por cada banda con `scraped_at IS NOT NULL` (las nuevas son territorio de
    `ingest()`): resuelve el user_id (caché de `ig_user_id` o fetch de perfil),
    baja la primera página de posts y CORTA en cuanto aparece un `source_post_id`
    ya presente en `photos` de esa banda — solo se descargan los nuevos.

    El feed de IG soft-bloquea (401) tras ~33 llamadas por ventana, así que:
    - **Rotación por antigüedad**: sin `handles`, revisa solo las `limite` bandas
      MÁS viejas de revisar (orden por `scraped_at`); como cada éxito actualiza
      `scraped_at`, en pocas corridas pasan todas. Con `handles` explícitos no
      hay tope (es intención del usuario).
    - **Circuit breaker**: tras `max_bloqueos` 401/429 SEGUIDOS aborta la corrida
      (seguir solo profundiza el bloqueo); las no intentadas conservan su
      `scraped_at` viejo → entran primero la próxima vez.

    Banda que falle aislada → se loguea y se continúa; el resumen lista las
    fallidas. `posts_nuevos` alimenta los pasos siguientes del orquestador.

    `_cx`: conexión inyectable para tests; en producción se abre una nueva.
    """
    max_posts = max_posts or config.IG_INGEST_MAX_POSTS
    limite = limite or config.NOVEDADES_BANDAS_POR_CORRIDA
    max_bloqueos = max_bloqueos or config.NOVEDADES_MAX_BLOQUEOS
    propia = _cx is None
    cx = _cx or db.connect()
    resumen: dict[str, Any] = {
        "bandas_revisadas": 0, "con_novedades": 0, "fotos_nuevas": 0,
        "fallidas": [], "posts_nuevos": [], "pendientes": 0,
        "cortado_por_bloqueo": False,
    }
    try:
        if propia:
            db.init_db(cx)
        bandas = [b for b in db.list_bands(cx)
                  if b.get("ig_handle") and b.get("scraped_at")]
        if handles:
            quiero = {h.lstrip("@").lower() for h in handles}
            bandas = [b for b in bandas if b["ig_handle"].lower() in quiero]
        else:
            # Rotación: las más viejas de revisar primero, tope por corrida.
            bandas.sort(key=lambda b: b["scraped_at"])
            total = len(bandas)
            bandas = bandas[:limite]
            resumen["pendientes"] = max(0, total - len(bandas))
        if not bandas:
            print("No hay bandas scrapeadas que revisar.")
            return resumen

        rot = SesionRotatoria()
        if not rot.disponible():
            print("No hay cuentas scraper sanas (todas en reposo o sin configurar).")
            resumen["cortado_por_bloqueo"] = True
            resumen["pendientes"] += len(bandas)
            return resumen

        print(f"Novedades de {len(bandas)} banda(s) — cuenta '{rot.cuenta['label']}'…")
        for i, band in enumerate(bandas):
            handle = band["ig_handle"]
            print(f"▶ @{handle} ({band['nombre']})")
            resumen["bandas_revisadas"] += 1  # intentadas; las que truenan van a fallidas
            # Reintenta la MISMA banda rotando de cuenta mientras el feed dé 401/429.
            nuevos = None
            while True:
                try:
                    nuevos = _revisar_banda(rot.session, cx, band, max_posts)
                    break
                except IngestRateLimited as exc:
                    print(f"   ⚠️ {exc} — quemo '{rot.cuenta['label']}' y roto.")
                    if rot.rotar_por_quemada():
                        print(f"   ↻ ahora con cuenta '{rot.cuenta['label']}'.")
                        continue  # reintenta esta banda con la nueva cuenta
                    # Pool agotado: nadie más puede revisar. Cortar la corrida.
                    no_intentadas = len(bandas) - i  # esta inclusive
                    resumen["cortado_por_bloqueo"] = True
                    resumen["pendientes"] += no_intentadas
                    print(f"   🛑 todas las cuentas en reposo: corto ({no_intentadas} sin revisar).")
                    return resumen
                except Exception as exc:  # noqa: BLE001 — banda caída no tumba la corrida
                    print(f"   ❌ {exc} — se salta esta banda y se continúa.")
                    resumen["fallidas"].append(handle)
                    break
            if nuevos:
                resumen["con_novedades"] += 1
                resumen["fotos_nuevas"] += len(nuevos)
                resumen["posts_nuevos"].extend(nuevos)
            if nuevos is not None:
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
