"""Fetch de cuentas ajenas por la API OFICIAL de Meta (Business Discovery).

Alternativa LEGAL y sin cookies a `ingest_ig`: en vez de la cookie `sessionid`
de una cuenta scraper (que IG mata cada ~10 días y topa a ~33 llamadas de feed
por ventana), consulta el endpoint oficial

    GET /{ig-user-id}?fields=business_discovery.username(HANDLE){...}

que devuelve perfil + media pública de la cuenta objetivo en UNA sola llamada,
con el límite normal de Graph (~200 req/hora) y sin riesgo de bloqueo.

Requisitos (una vez, ver `diagnostico()`):
1. @gdlscene vinculada a la Página de Facebook (FB_PAGE_ID).
2. El token de Página con scope `instagram_basic` — el que hay hoy solo trae
   permisos de Páginas, y sin `instagram_basic` el campo
   `instagram_business_account` viene vacío.

Límite del método (de Meta, no del código): la cuenta OBJETIVO debe ser
Business o Creator. Las personales devuelven error → se reportan aparte para
caer al camino de scraping o a Deezer.

Las fotos se guardan igual que `ingest_ig` (PHOTOS_DIR/<handle>/<shortcode>_<i>.jpg
y fila en `photos` con `source_post_id` = shortcode del permalink), así que el
dedup y la clasificación posterior funcionan sin cambios.

Uso:
    python -m src.business_discovery --check              # diagnóstico de permisos
    python -m src.business_discovery handle1 handle2      # trae y registra
    python -m src.business_discovery --archivo nuevas.txt --activar
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests

import config
from src import banco, db

_TIMEOUT = 60
# Pausa corta entre cuentas: Graph no necesita ritmo humano, solo no ráfaga.
_PAUSA_S = 0.3

_CAMPOS_PERFIL = ("id,username,name,biography,website,followers_count,"
                  "follows_count,media_count,profile_picture_url")
_CAMPOS_MEDIA = ("id,media_type,media_url,permalink,caption,timestamp,"
                 "like_count,comments_count,children{media_type,media_url}")

_RE_SHORTCODE = re.compile(r"/(?:p|reel|tv)/([^/?#]+)")


class BusinessDiscoveryNoDisponible(Exception):
    """Falta el vínculo Página↔IG o el scope `instagram_basic` en el token."""


class NoEsBusiness(Exception):
    """La cuenta objetivo es personal: Business Discovery no la cubre."""


class GraphRateLimited(Exception):
    """Graph limitó la app (429 / código 4 o 17): parar y reintentar más tarde."""


# ---------- HTTP (inyectable en tests) ----------

def _base() -> str:
    return f"{config.FB_GRAPH_BASE.rstrip('/')}/{config.FB_API_VERSION}"


def _get(url: str, params: dict[str, Any]) -> Any:
    return requests.get(url, params=params, timeout=_TIMEOUT)


def _token() -> str:
    tok = config.FB_PAGE_ACCESS_TOKEN
    if not tok:
        raise BusinessDiscoveryNoDisponible(
            "Falta FB_PAGE_ACCESS_TOKEN en el .env (token PERMANENTE de la Página).")
    return tok


def clasificar_error(payload: dict[str, Any]) -> Exception | None:
    """Traduce el `error` de Graph a la excepción del dominio (None si no hay error).

    Función PURA: toda la interpretación de errores de Meta vive aquí para que
    los tests no necesiten red.
    """
    err = payload.get("error")
    if not err:
        return None
    msg = str(err.get("message", ""))
    code = err.get("code")
    bajo = msg.lower()
    if code in (4, 17, 32, 613) or "rate limit" in bajo or "request limit" in bajo:
        return GraphRateLimited(msg)
    if "business" in bajo or "creator" in bajo:
        # (#110) ... requires a Business or Creator account
        return NoEsBusiness(msg)
    if "instagram_basic" in bajo or "permission" in bajo or code == 200:
        return BusinessDiscoveryNoDisponible(
            f"{msg} — falta el scope `instagram_basic` en el token de Página.")
    if "does not exist" in bajo or "cannot be found" in bajo or "invalid user" in bajo:
        return LookupError(msg)
    return RuntimeError(f"Graph error {code}: {msg}")


def _pedir(url: str, params: dict[str, Any]) -> dict[str, Any]:
    resp = _get(url, params)
    payload = resp.json()
    exc = clasificar_error(payload)
    if exc:
        raise exc
    return payload


# ---------- resolución del ig-user-id ----------

def ig_user_id() -> str:
    """Id de la cuenta de IG Business vinculada a la Página (cacheable en .env).

    `FB_IG_USER_ID` en el .env evita la llamada; si no está, se resuelve contra
    la Página. Un campo vacío significa SIEMPRE lo mismo: falta el vínculo o el
    scope, no que la Página no exista.
    """
    if getattr(config, "FB_IG_USER_ID", None):
        return str(config.FB_IG_USER_ID)
    if not config.FB_PAGE_ID:
        raise BusinessDiscoveryNoDisponible("Falta FB_PAGE_ID en el .env.")
    data = _pedir(f"{_base()}/{config.FB_PAGE_ID}",
                  {"fields": "instagram_business_account", "access_token": _token()})
    cuenta = data.get("instagram_business_account") or {}
    if not cuenta.get("id"):
        raise BusinessDiscoveryNoDisponible(
            "La Página no expone `instagram_business_account`. Falta vincular "
            "@gdlscene a la Página en Ajustes de IG, o re-autorizar la app con "
            "el scope `instagram_basic` y regenerar el token de Página.")
    return str(cuenta["id"])


# ---------- consulta ----------

def fetch_cuenta(handle: str, *, max_posts: int | None = None,
                 ig_id: str | None = None) -> dict[str, Any]:
    """Perfil + media pública de `handle` en UNA llamada.

    Devuelve el bloque `business_discovery` tal cual lo manda Graph.
    """
    max_posts = max_posts or config.IG_INGEST_MAX_POSTS
    ig_id = ig_id or ig_user_id()
    handle = handle.lstrip("@")
    campos = (f"business_discovery.username({handle})"
              f"{{{_CAMPOS_PERFIL},media.limit({max_posts}){{{_CAMPOS_MEDIA}}}}}")
    data = _pedir(f"{_base()}/{ig_id}", {"fields": campos, "access_token": _token()})
    bd = data.get("business_discovery")
    if not bd:
        raise LookupError(f"Graph no devolvió business_discovery para @{handle}")
    return bd


# ---------- parseo (puro) ----------

def shortcode_de_permalink(permalink: str | None) -> str | None:
    """`https://www.instagram.com/p/ABC123/` → `ABC123`.

    Mismo identificador que usa `ingest_ig` como `source_post_id`, para que una
    cuenta traída por los dos caminos no duplique fotos.
    """
    if not permalink:
        return None
    m = _RE_SHORTCODE.search(permalink)
    return m.group(1) if m else None


def urls_de_media(media: dict[str, Any]) -> list[tuple[int, str]]:
    """(índice, url) de cada IMAGEN del post. Video se ignora (fuera de alcance)."""
    tipo = media.get("media_type")
    if tipo == "IMAGE":
        url = media.get("media_url")
        return [(0, url)] if url else []
    if tipo == "CAROUSEL_ALBUM":
        hijos = (media.get("children") or {}).get("data") or []
        return [(i, h["media_url"]) for i, h in enumerate(hijos)
                if h.get("media_type") == "IMAGE" and h.get("media_url")]
    return []


def _fecha(ts: str | None) -> str | None:
    """`2026-07-18T16:02:21+0000` → ISO local sin tz (como lo guarda ingest_ig)."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z").astimezone().replace(
            tzinfo=None).isoformat(timespec="seconds")
    except ValueError:
        return ts[:19] or None


# ---------- persistencia ----------

def _path_guardable(dest: Path) -> str:
    """Ruta relativa a BASE_DIR (como la guarda ingest_ig), absoluta si cae fuera.

    PHOTOS_DIR normalmente vive dentro del repo, pero apuntarlo afuera no debe
    tumbar el lote a media descarga.
    """
    try:
        return str(dest.relative_to(config.BASE_DIR))
    except ValueError:
        return str(dest)


def _descargar(url: str, dest: Path) -> bool:
    """Baja una imagen del CDN (URL pública, sin token). False si falla."""
    try:
        resp = requests.get(url, timeout=_TIMEOUT)
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return True
    except Exception as exc:  # noqa: BLE001 — una descarga rota no tumba el lote
        print(f"   ⚠️  no se pudo bajar {url[:60]}…: {exc}")
        return False


def registrar_banda(cx, bd: dict[str, Any], *, activar: bool = False) -> int:
    """Crea/actualiza la banda desde el perfil de business_discovery.

    NUNCA pisa `activa` ni `prioridad` de una banda existente: la curación de
    Ricardo manda. `activar` solo aplica al ALTA.
    """
    handle = bd["username"]
    datos = {
        "ig_user_id": str(bd.get("id")) if bd.get("id") else None,
        "followers_ig": bd.get("followers_count"),
        "bio": (bd.get("biography") or "").strip() or None,
        "link_externo": bd.get("website") or None,
    }
    fila = db.rows(cx, "SELECT id FROM bands WHERE ig_handle = ?", (handle,))
    if fila:
        db.update(cx, "bands", fila[0]["id"], **datos)
        return int(fila[0]["id"])
    nombre = (bd.get("name") or "").strip() or handle
    return db.insert(cx, "bands", nombre=nombre, ig_handle=handle,
                     activa=1 if activar else 0,
                     notas=None if activar else "candidata (business discovery)",
                     **datos)


def guardar_media(cx, band_id: int, handle: str, medias: list[dict[str, Any]],
                  *, _descargador: Callable[[str, Path], bool] | None = None
                  ) -> list[dict[str, Any]]:
    """Baja e inserta en `photos` las imágenes de posts aún no registrados."""
    bajar = _descargador or _descargar
    band_dir = config.resolve_photos_dir() / handle
    band_dir.mkdir(parents=True, exist_ok=True)

    insertadas: list[dict[str, Any]] = []
    for media in medias:
        shortcode = shortcode_de_permalink(media.get("permalink")) or media.get("id")
        if not shortcode:
            continue
        ya = db.rows(cx, "SELECT 1 FROM photos WHERE band_id = ? AND source_post_id = ?",
                     (band_id, shortcode))
        if ya:
            continue
        caption = (media.get("caption") or "").strip() or None
        fecha = _fecha(media.get("timestamp"))
        for i, url in urls_de_media(media):
            dest = band_dir / f"{shortcode}_{i}.jpg"
            if not dest.exists() and not bajar(url, dest):
                continue
            rel = _path_guardable(dest)
            db.insert(cx, "photos", band_id=band_id, path=rel,
                      source_post_id=shortcode, fecha=fecha, caption_original=caption)
            insertadas.append({"band_id": band_id, "shortcode": shortcode, "path": rel,
                               "likes": media.get("like_count"),
                               "comments": media.get("comments_count")})
    return insertadas


def _podar_fuera_del_banco(cx, band_id: int, shortcodes_nuevos: set[str]) -> list[dict]:
    """Borra de disco y de la DB las fotos RECIÉN traídas que no entraron al banco.

    Solo toca lo de esta corrida (`shortcodes_nuevos`): una foto vieja que salga
    del cupo se marca `usable_meme=0` pero NUNCA se borra — regla del spec.

    Invariante real, independiente de cualquier `limite` que reciba
    `procesar_banda`: NO SE BORRA LO QUE NO SE JUZGÓ. `procesar_banda` solo
    escribe `nitidez` en las fotos que efectivamente analizó; una fila con
    `nitidez IS NULL` nunca compitió por el cupo (quedó fuera del análisis),
    así que se salta aquí aunque `usable_meme` traiga el 0 de default de
    columna — ese 0 no significa "perdió", significa "no se sabe todavía".

    Devuelve solo las fotos DE ESTA CORRIDA (`shortcodes_nuevos`) que
    sobrevivieron a la poda, no el total de fotos vivas de la banda — para
    que el resumen de `traer` no infle el conteo con fotos viejas ya
    conservadas de corridas anteriores.
    """
    fuera = db.rows(cx, """
        SELECT id, path, source_post_id, nitidez FROM photos
         WHERE band_id = ? AND usable_meme = 0
    """, (band_id,))
    borradas = 0
    for fila in fuera:
        if fila["nitidez"] is None:
            continue  # nunca se juzgó: no se borra lo que no se juzgó
        if fila["source_post_id"] not in shortcodes_nuevos:
            continue
        p = Path(fila["path"])
        if not p.is_absolute():
            p = config.BASE_DIR / p
        p.unlink(missing_ok=True)
        cx.execute("DELETE FROM face_signatures WHERE photo_id = ?", (fila["id"],))
        cx.execute("DELETE FROM photos WHERE id = ?", (fila["id"],))
        borradas += 1
    cx.commit()
    if borradas:
        print(f"   🗑  {borradas} descarga(s) fuera del cupo, borradas")
    if not shortcodes_nuevos:
        return []
    marcadores = ",".join("?" * len(shortcodes_nuevos))
    return db.rows(cx, f"""
        SELECT id, source_post_id FROM photos
         WHERE band_id = ? AND source_post_id IN ({marcadores})
    """, (band_id, *shortcodes_nuevos))


# ---------- orquestación ----------

def traer(handles: list[str], *, max_posts: int | None = None, activar: bool = False,
          selectivo: bool = False, _cx=None) -> dict[str, Any]:
    """Trae y registra varias cuentas. Una caída aislada no tumba el lote.

    Corta en seco ante GraphRateLimited (insistir solo empeora la cuota).

    `selectivo=True`: mira `BD_POSTS_A_MIRAR` posts, corre el banco por persona y
    BORRA las descargas que no entraron al cupo. Pedir 50 posts cuesta lo mismo
    en cuota que pedir 12 — lo caro es guardar, no consultar.
    """
    propia = _cx is None
    cx = _cx or db.connect()
    resumen: dict[str, Any] = {
        "ok": [], "fotos": 0, "personales": [], "no_encontradas": [],
        "errores": [], "cortado_por_cuota": False,
    }
    try:
        if propia:
            db.init_db(cx)
        ig_id = ig_user_id()  # una sola resolución para todo el lote
        for i, handle in enumerate(handles):
            handle = handle.lstrip("@")
            print(f"▶ @{handle}")
            mirar = config.BD_POSTS_A_MIRAR if selectivo else max_posts
            try:
                bd = fetch_cuenta(handle, max_posts=mirar, ig_id=ig_id)
            except NoEsBusiness:
                print("   ⏭  cuenta personal: fuera del alcance de Business Discovery")
                resumen["personales"].append(handle)
                continue
            except LookupError as exc:
                print(f"   ❌ {exc}")
                resumen["no_encontradas"].append(handle)
                continue
            except GraphRateLimited as exc:
                print(f"   🛑 cuota de Graph agotada: {exc} — corto el lote.")
                resumen["cortado_por_cuota"] = True
                return resumen
            except Exception as exc:  # noqa: BLE001
                print(f"   ❌ {exc}")
                resumen["errores"].append(handle)
                continue

            band_id = registrar_banda(cx, bd, activar=activar)
            medias = (bd.get("media") or {}).get("data") or []
            nuevas = guardar_media(cx, band_id, handle, medias)
            if selectivo:
                try:
                    # El fetch selectivo es deliberado: aquí sí se juzga TODO lo
                    # vivo de la banda, no las 40 mejores por default — si el
                    # cupo por defecto se queda corto, las recién bajadas con
                    # nitidez aún NULL nunca competirían (ver _podar_fuera_del_banco).
                    total_vivas = db.rows(cx, """
                        SELECT count(*) AS n FROM photos
                         WHERE band_id = ? AND descartada = 0
                    """, (band_id,))[0]["n"]
                    if total_vivas:
                        banco.procesar_banda(cx, band_id, limite=total_vivas)
                        nuevas = _podar_fuera_del_banco(
                            cx, band_id, {n["shortcode"] for n in nuevas})
                except Exception as exc:  # noqa: BLE001 — el banco no debe tumbar el lote
                    print(f"   ❌ el banco falló para @{handle}: {exc}")
                    resumen["errores"].append(handle)
                    continue
            db.update(cx, "bands", band_id,
                      scraped_at=datetime.now().isoformat(timespec="seconds"))
            resumen["ok"].append({"handle": handle, "band_id": band_id,
                                  "followers": bd.get("followers_count"),
                                  "fotos": len(nuevas)})
            resumen["fotos"] += len(nuevas)
            print(f"   ✅ {bd.get('followers_count')} followers · {len(nuevas)} foto(s) nueva(s)")
            if i < len(handles) - 1:
                time.sleep(_PAUSA_S)
        return resumen
    finally:
        if propia:
            cx.close()


def diagnostico() -> dict[str, Any]:
    """Verifica los tres requisitos y dice EXACTAMENTE qué falta."""
    out: dict[str, Any] = {"token": False, "vinculo": False, "consulta": False,
                           "ig_user_id": None, "detalle": []}
    try:
        _token()
        out["token"] = True
        out["detalle"].append("✅ FB_PAGE_ACCESS_TOKEN presente")
    except BusinessDiscoveryNoDisponible as exc:
        out["detalle"].append(f"❌ {exc}")
        return out
    try:
        uid = ig_user_id()
        out["vinculo"] = True
        out["ig_user_id"] = uid
        out["detalle"].append(f"✅ Página vinculada a la cuenta de IG {uid}")
    except Exception as exc:  # noqa: BLE001
        out["detalle"].append(f"❌ {exc}")
        return out
    try:
        bd = fetch_cuenta("gdlscene", max_posts=1, ig_id=out["ig_user_id"])
        out["consulta"] = True
        out["detalle"].append(
            f"✅ Business Discovery responde (@{bd.get('username')}, "
            f"{bd.get('followers_count')} followers)")
    except Exception as exc:  # noqa: BLE001
        out["detalle"].append(f"❌ consulta de prueba falló: {exc}")
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fetch de cuentas por la API oficial (Business Discovery)")
    parser.add_argument("handles", nargs="*", help="handles a traer")
    parser.add_argument("--archivo", help="archivo con un handle por línea")
    parser.add_argument("--max-posts", type=int, default=None,
                        help=f"posts por cuenta (default {config.IG_INGEST_MAX_POSTS})")
    parser.add_argument("--activar", action="store_true",
                        help="dar de alta como activa=1 (default: candidata para curar)")
    parser.add_argument("--check", action="store_true", help="solo diagnóstico de permisos")
    parser.add_argument("--selectivo", action="store_true",
                        help=(f"mira {config.BD_POSTS_A_MIRAR} posts, corre el banco y BORRA "
                              "del disco las descargas que no entren al cupo"))
    args = parser.parse_args()

    if args.check:
        for linea in diagnostico()["detalle"]:
            print(linea)
        sys.exit(0)

    objetivos = list(args.handles)
    if args.archivo:
        objetivos += [ln.strip() for ln in Path(args.archivo).read_text().splitlines()
                      if ln.strip() and not ln.startswith("#")]
    if not objetivos:
        sys.exit("Nada que traer: pasa handles o --archivo.")
    try:
        res = traer(objetivos, max_posts=args.max_posts, activar=args.activar,
                    selectivo=args.selectivo)
    except BusinessDiscoveryNoDisponible as exc:
        sys.exit(f"❌ {exc}\nCorre `python -m src.business_discovery --check` para el detalle.")
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido.")
    print(f"\nResumen: {len(res['ok'])} cuenta(s), {res['fotos']} foto(s) nuevas"
          + (f" · {len(res['personales'])} personales (fuera de alcance)" if res["personales"] else "")
          + (f" · {len(res['no_encontradas'])} no encontradas" if res["no_encontradas"] else "")
          + (f" · {len(res['errores'])} con error" if res["errores"] else ""))
    if res["personales"]:
        print("Personales → caen al camino de scraping o a Deezer: "
              + ", ".join(res["personales"]))
