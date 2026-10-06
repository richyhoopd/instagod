"""Feeds de contenido por marca: contrato v1 → brand_entities (spec 2026-10-06).

Pull: instagod pide `GET url?since=<cursor>` (token opcional como
`Authorization: Bearer`, clave FEED_TOKEN en brand_secrets). Cada item válido
se upsertea en `brand_entities` (`tipo`←type, `slug`←id, el resto en
`atributos_json`); los inválidos se saltan y se registran, nunca tumban el lote.
La media de imagen sube a Cloudinary con el hash de la URL como public_id y no
se resube si ya está en `atributos.media_cdn`.

3 fallas seguidas (red o sobre inválido) → aviso al Telegram de la marca.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable

from src import db, entidades

VERSION = 1
ESTADOS = ("active", "archived", "sold")
FALLAS_PARA_AVISO = 3
CLAVE_TOKEN = "FEED_TOKEN"


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _iso_valido(v: Any) -> bool:
    if not isinstance(v, str) or not v.strip():
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _url_abs(v: Any) -> bool:
    return isinstance(v, str) and v.startswith(("http://", "https://"))


def validar_item(item: Any) -> list[str]:
    """Errores del item contra el contrato v1; [] = válido. PURO."""
    if not isinstance(item, dict):
        return ["no es objeto"]
    err: list[str] = []
    if not isinstance(item.get("id"), str) or not item["id"].strip():
        err.append("id: requerido (string)")
    if not isinstance(item.get("type"), str) or not item["type"].strip():
        err.append("type: requerido (string)")
    if not _iso_valido(item.get("updated_at")):
        err.append("updated_at: requerido (ISO 8601)")
    if item.get("status") not in ESTADOS:
        err.append(f"status: debe ser uno de {ESTADOS}")
    t = item.get("title")
    if isinstance(t, dict):
        if not any(isinstance(x, str) and x.strip() for x in t.values()):
            err.append("title: objeto sin textos")
    elif not (isinstance(t, str) and t.strip()):
        err.append("title: requerido (string o {es, en})")
    if not _url_abs(item.get("url")):
        err.append("url: requerida y absoluta")
    media = item.get("media")
    if media is not None:
        if not isinstance(media, list):
            err.append("media: debe ser lista")
        else:
            for i, m in enumerate(media):
                if not isinstance(m, dict) or not _url_abs(m.get("url")):
                    err.append(f"media[{i}]: url absoluta requerida")
                elif m.get("kind", "image") not in ("image", "video"):
                    err.append(f"media[{i}]: kind debe ser image|video")
    if item.get("facts") is not None and not isinstance(item["facts"], dict):
        err.append("facts: debe ser objeto")
    for campo in ("unverified", "tags"):
        v = item.get(campo)
        if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            err.append(f"{campo}: debe ser lista de strings")
    return err


def validar_sobre(data: Any) -> list[str]:
    """Errores del sobre `{version, brand, cursor, items}`. PURO."""
    if not isinstance(data, dict):
        return ["la respuesta no es un objeto JSON"]
    err = []
    if data.get("version") != VERSION:
        err.append(f"version: se esperaba {VERSION}, llegó {data.get('version')!r}")
    if not isinstance(data.get("items"), list):
        err.append("items: debe ser lista")
    return err


def titulo_de(item: dict, locale: str = "es") -> str:
    t = item.get("title")
    if isinstance(t, dict):
        return (t.get(locale) or t.get(item.get("locale") or "")
                or next((x for x in t.values() if x), "")).strip()
    return str(t or "").strip()


def clave_media(url: str) -> str:
    return "feed_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def _atributos(item: dict, previos: dict, feed_id: int) -> dict:
    """Todo lo del item menos id/type, + lo que instagod ya calculó (media_cdn)."""
    attrs = {k: v for k, v in item.items() if k not in ("id", "type")}
    attrs["fuente"] = "feed"
    attrs["feed_id"] = feed_id
    attrs["media_cdn"] = dict(previos.get("media_cdn") or {})
    return attrs


def _subir_media(attrs: dict, subir: Callable[..., str] | None, log: list[str]) -> int:
    """Sube las imágenes nuevas; devuelve cuántas subió. Nunca levanta."""
    if subir is None:
        return 0
    cdn = attrs["media_cdn"]
    subidas = 0
    for m in attrs.get("media") or []:
        url = m.get("url")
        if m.get("kind", "image") != "image" or not url or url in cdn:
            continue
        try:
            cdn[url] = subir(url, public_id=clave_media(url))
            subidas += 1
        except Exception as e:  # noqa: BLE001 — una foto rota no tumba el item
            log.append(f"media {url}: {type(e).__name__}: {str(e)[:120]}")
    return subidas


def upsert_item(cx, account_id: int, feed_id: int, item: dict, *,
                subir: Callable[..., str] | None = None,
                log: list[str] | None = None) -> tuple[int, bool]:
    """Crea o actualiza la entidad del item. Devuelve (entity_id, creada)."""
    log = log if log is not None else []
    slug = item["id"].strip()
    previa = entidades.por_slug(cx, account_id, slug)
    previos = entidades.atributos_de(previa) if previa else {}
    attrs = _atributos(item, previos, feed_id)
    _subir_media(attrs, subir, log)
    nombre = titulo_de(item) or slug
    activa = 1 if item["status"] == "active" else 0
    if previa:
        entidades.editar(cx, previa["id"], nombre=nombre, tipo=item["type"],
                         activa=activa, atributos=attrs)
        return previa["id"], False
    eid = entidades.crear(cx, account_id, nombre, item["type"], atributos=attrs,
                          slug=slug)
    if not activa:
        entidades.archivar(cx, eid)
    return eid, True


def _http_get_default(url: str, *, params: dict, headers: dict) -> Any:
    import requests
    r = requests.get(url, params=params, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()


def _token_de(cx, account_id: int) -> str | None:
    try:
        from src import secrets_store
        return secrets_store.leer(cx, account_id, CLAVE_TOKEN)
    except Exception:  # noqa: BLE001 — sin master key / sin fila: feed público
        return None


def _avisar_default(slug: str, texto: str) -> bool:
    from src import avisos_marca
    return avisos_marca.enviar_texto(slug, texto)


def _subir_default(url: str, *, public_id: str) -> str:
    from src import host
    return host.upload(url, public_id=public_id)


def _error_seguro(e: Exception, token: str | None) -> str:
    msg = f"{type(e).__name__}: {e}"
    if token:
        msg = msg.replace(token, "***")
    return msg[:500]


def sincronizar(cx, feed_id: int, *,
                http_get: Callable[..., Any] | None = None,
                subir: Callable[..., str] | None = _subir_default,
                avisar: Callable[[str, str], bool] | None = None) -> dict:
    """Corre un sync del feed. Devuelve resumen; levanta solo si el feed no existe.

    Fallas (red, JSON, sobre inválido) NO levantan: se registran en la fila,
    suben `fallas_seguidas` y al llegar a 3 avisan al Telegram de la marca.
    """
    feed = db.get(cx, "brand_feeds", feed_id)
    if feed is None:
        raise ValueError(f"feed {feed_id} no existe")
    http_get = http_get or _http_get_default
    avisar = avisar or _avisar_default
    slug = (db.rows(cx, "SELECT slug FROM accounts WHERE id = ?",
                    (feed["account_id"],)) or [{"slug": "?"}])[0]["slug"]
    token = _token_de(cx, feed["account_id"])
    params = {"since": feed["cursor"]} if feed["cursor"] else {}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    db.update(cx, "brand_feeds", feed_id, ultimo_intento=_ahora())

    try:
        data = http_get(feed["url"], params=params, headers=headers)
        errores = validar_sobre(data)
        if errores:
            raise ValueError("sobre inválido: " + "; ".join(errores))
    except Exception as e:  # noqa: BLE001
        fallas = int(feed["fallas_seguidas"] or 0) + 1
        msg = _error_seguro(e, token)
        db.update(cx, "brand_feeds", feed_id, ultimo_error=msg,
                  fallas_seguidas=fallas)
        avisado = False
        if fallas == FALLAS_PARA_AVISO:
            avisado = bool(avisar(slug, f"⚠️ instagod: el feed de {slug} lleva "
                                        f"{fallas} fallas seguidas.\n{feed['url']}\n{msg}"))
        print(f"[feeds] {slug} feed {feed_id} falló ({fallas} seguidas): {msg}",
              file=sys.stderr)
        return {"ok": False, "error": msg, "fallas_seguidas": fallas,
                "avisado": avisado}

    creadas = actualizadas = 0
    invalidos: list[dict] = []
    log: list[str] = []
    max_updated = None
    for i, item in enumerate(data["items"]):
        errores = validar_item(item)
        if errores:
            ident = item.get("id") if isinstance(item, dict) else None
            invalidos.append({"indice": i, "id": ident, "errores": errores})
            print(f"[feeds] {slug} item {ident or i} inválido: {errores}",
                  file=sys.stderr)
            continue
        _, creada = upsert_item(cx, feed["account_id"], feed_id, item,
                                subir=subir, log=log)
        creadas += creada
        actualizadas += not creada
        if max_updated is None or item["updated_at"] > max_updated:
            max_updated = item["updated_at"]
    for linea in log:
        print(f"[feeds] {slug}: {linea}", file=sys.stderr)

    cursor = data.get("cursor") if isinstance(data.get("cursor"), str) and data.get("cursor") \
        else (max_updated or feed["cursor"])
    db.update(cx, "brand_feeds", feed_id, cursor=cursor, ultimo_ok=_ahora(),
              ultimo_error=(f"{len(invalidos)} items inválidos" if invalidos else None),
              fallas_seguidas=0)
    return {"ok": True, "creadas": creadas, "actualizadas": actualizadas,
            "invalidos": invalidos, "media_errores": log, "cursor": cursor}


def vencidos(cx, ahora: datetime | None = None) -> list[dict]:
    """Feeds activos cuyo `intervalo_min` ya pasó desde el último intento."""
    ahora = ahora or datetime.now(timezone.utc)
    out = []
    for f in db.rows(cx, "SELECT * FROM brand_feeds WHERE activa = 1"):
        if not f["ultimo_intento"]:
            out.append(f)
            continue
        try:
            ultimo = datetime.strptime(f["ultimo_intento"], "%Y-%m-%d %H:%M:%S") \
                .replace(tzinfo=timezone.utc)
        except ValueError:
            out.append(f)
            continue
        if (ahora - ultimo).total_seconds() >= max(15, int(f["intervalo_min"] or 360)) * 60:
            out.append(f)
    return out


def encolar_vencidos(cx, ahora: datetime | None = None) -> int:
    """Encola `feeds.sync` por feed vencido sin job cola/corriendo. Devuelve cuántos."""
    from src import jobs
    pendientes = set()
    for m in db.rows(cx, "SELECT payload_json FROM jobs WHERE tipo = 'feeds.sync' "
                         "AND estado IN ('cola', 'corriendo')"):
        try:
            pendientes.add(json.loads(m["payload_json"] or "{}").get("feed_id"))
        except (TypeError, ValueError):
            pass
    creados = 0
    for f in vencidos(cx, ahora):
        if f["id"] in pendientes:
            continue
        jobs.crear(cx, "feeds.sync", f["account_id"], {"feed_id": f["id"]})
        creados += 1
    return creados
