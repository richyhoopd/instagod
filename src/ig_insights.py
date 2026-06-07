"""Métricas de posts publicados en Instagram (página /publicado).

Lee TODO el feed de la cuenta vía la Graph API (`/me/media`) y los insights por
media (`/{media_id}/insights`), los guarda en `ig_posts` (estado actual) y en
`ig_metrics_snapshots` (histórico, máx 1 por día). Los posts del bot se ligan a
su banda cruzando `ig_post_id` del Sheet ↔ `content_queue.sheet_row_id`.

Con eso `band_stats()` agrega engagement por banda y sugiere subir/bajar la
`prioridad` (1 = máxima) contra la mediana de la cuenta; el usuario aplica la
sugerencia desde la GUI.

Spec: docs/superpowers/specs/2026-06-07-pagina-publicado-design.md
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta
from typing import Any

import requests

import config
from src import db

_TIMEOUT = 60
# Métricas de insights por media. likes/comments vienen gratis en /me/media.
_INSIGHT_METRICS = "reach,saved,shares,views"
# Cada cuántos posts pausar al pedir insights (rate limit de la Graph API).
_BATCH = 25
_BATCH_PAUSE = 2.0

# Sugerencias: una banda debe estar >40% arriba/abajo de la mediana para que
# se proponga moverle la prioridad, con mínimo 2 posts recientes.
_MIN_POSTS = 2
_UP_FACTOR = 1.4
_DOWN_FACTOR = 0.6
_WINDOW_DAYS = 90


def _base() -> str:
    return f"{config.IG_GRAPH_BASE.rstrip('/')}/{config.IG_API_VERSION}"


def _fetch_media() -> list[dict[str, Any]]:
    """Todo el feed de la cuenta, paginado. Una llamada por página de ~25."""
    fields = ("id,media_type,media_url,thumbnail_url,permalink,caption,"
              "timestamp,like_count,comments_count")
    url = f"{_base()}/me/media"
    params: dict[str, Any] = {"fields": fields, "access_token": config.IG_ACCESS_TOKEN}
    items: list[dict[str, Any]] = []
    while url:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        _raise_for_graph(resp)
        payload = resp.json()
        items.extend(payload.get("data", []))
        url = payload.get("paging", {}).get("next")
        params = {}  # la URL `next` ya trae todos los parámetros
    return items


def _fetch_insights(media_id: str) -> dict[str, int]:
    """Insights de un media → {reach, saved, shares, views}. Lanza si la API falla."""
    resp = requests.get(
        f"{_base()}/{media_id}/insights",
        params={"metric": _INSIGHT_METRICS, "access_token": config.IG_ACCESS_TOKEN},
        timeout=_TIMEOUT,
    )
    _raise_for_graph(resp)
    out: dict[str, int] = {}
    for m in resp.json().get("data", []):
        if "total_value" in m:
            value = m["total_value"].get("value")
        else:
            values = m.get("values") or [{}]
            value = values[0].get("value")
        if value is not None:
            out[m["name"]] = int(value)
    return out


def _sheet_rows() -> list[dict[str, Any]]:
    """Filas del Sheet (id + ig_post_id). Import perezoso: solo se usa en el sync."""
    from src import sheets
    return sheets._records()


def _raise_for_graph(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:  # noqa: BLE001
            err = resp.text
        raise RuntimeError(f"Graph API {resp.status_code}: {err}")


# ---------- persistencia ----------

def upsert_post(cx, item: dict[str, Any]) -> int:
    """Crea/actualiza la fila de `ig_posts` desde un nodo de /me/media.

    Nunca toca band_id/queue_id (eso es de link_bands o asignación manual).
    """
    fields = dict(
        media_type=item.get("media_type"),
        permalink=item.get("permalink"),
        # en videos media_url puede expirar/no ser imagen: preferimos thumbnail
        thumbnail_url=item.get("thumbnail_url") or item.get("media_url"),
        caption=item.get("caption"),
        timestamp=item.get("timestamp"),
        likes=item.get("like_count"),
        comments=item.get("comments_count"),
    )
    row = cx.execute("SELECT id FROM ig_posts WHERE media_id = ?",
                     (item["id"],)).fetchone()
    if row:
        db.update(cx, "ig_posts", row["id"], **fields)
        return int(row["id"])
    return db.insert(cx, "ig_posts", media_id=item["id"], **fields)


def save_insights(cx, post_id: int, metrics: dict[str, int | None]) -> None:
    """Guarda reach/saved/shares/views del último sync en la fila del post."""
    db.update(cx, "ig_posts", post_id,
              reach=metrics.get("reach"), saved=metrics.get("saved"),
              shares=metrics.get("shares"), views=metrics.get("views"))


def snapshot(cx, post_id: int, fecha: str | None = None) -> None:
    """Copia las métricas actuales del post al histórico (upsert por día)."""
    fecha = fecha or datetime.now().strftime("%Y-%m-%d")
    cx.execute("""
        INSERT INTO ig_metrics_snapshots
               (ig_post_id, fecha, likes, comments, views, reach, saved, shares)
        SELECT id, ?, likes, comments, views, reach, saved, shares
          FROM ig_posts WHERE id = ?
        ON CONFLICT (ig_post_id, fecha) DO UPDATE SET
            likes = excluded.likes, comments = excluded.comments,
            views = excluded.views, reach = excluded.reach,
            saved = excluded.saved, shares = excluded.shares
    """, (fecha, post_id))
    cx.commit()


def link_bands(cx, sheet_rows: list[dict[str, Any]]) -> int:
    """Liga posts del bot a su banda: Sheet.ig_post_id ↔ content_queue.sheet_row_id.

    Solo toca posts con band_id NULL (jamás pisa una asignación manual).
    Devuelve cuántos posts quedaron vinculados.
    """
    n = 0
    for row in sheet_rows:
        media_id = str(row.get("ig_post_id", "")).strip()
        if not media_id:
            continue
        queue = cx.execute(
            "SELECT id, band_id FROM content_queue WHERE sheet_row_id = ?",
            (str(row.get("id", "")),)).fetchone()
        if not queue or queue["band_id"] is None:
            continue
        cur = cx.execute(
            "UPDATE ig_posts SET band_id = ?, queue_id = ? "
            "WHERE media_id = ? AND band_id IS NULL",
            (queue["band_id"], queue["id"], media_id))
        n += cur.rowcount
    cx.commit()
    return n


# ---------- agregados y sugerencias ----------

def _er(post: dict[str, Any], followers: int | None) -> float | None:
    """Engagement rate de un post; fallback likes/followers si no hay reach."""
    likes = post["likes"] or 0
    interacciones = likes + 2 * (post["comments"] or 0) + 3 * (post["saved"] or 0)
    if post["reach"]:
        return interacciones / post["reach"]
    if followers:
        return likes / followers
    return None


def _sugerir(er: float | None, mediana: float, prioridad: int, n_posts: int) -> int | None:
    if er is None or n_posts < _MIN_POSTS:
        return None
    if er > mediana * _UP_FACTOR and prioridad > 1:
        return prioridad - 1
    if er < mediana * _DOWN_FACTOR and prioridad < 5:
        return prioridad + 1
    return None


def band_stats(cx, *, days: int = _WINDOW_DAYS) -> list[dict[str, Any]]:
    """Resumen por banda de sus posts de los últimos `days` días, con sugerencia.

    Devuelve [{band_id, nombre, prioridad, n_posts, avg_likes, avg_comments,
    avg_reach, er, sugerida}], ordenado por er desc (sin er al final).
    """
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
    posts = db.rows(cx, """
        SELECT p.band_id, p.likes, p.comments, p.saved, p.reach,
               b.nombre, b.prioridad, b.followers_ig
          FROM ig_posts p JOIN bands b ON b.id = p.band_id
         WHERE p.band_id IS NOT NULL AND p.timestamp >= ?
    """, (cutoff,))

    por_banda: dict[int, list[dict]] = {}
    for p in posts:
        por_banda.setdefault(p["band_id"], []).append(p)

    stats = []
    for bid, items in por_banda.items():
        ers = [e for p in items if (e := _er(p, items[0]["followers_ig"])) is not None]
        stats.append({
            "band_id": bid,
            "nombre": items[0]["nombre"],
            "prioridad": items[0]["prioridad"],
            "n_posts": len(items),
            "avg_likes": sum(p["likes"] or 0 for p in items) / len(items),
            "avg_comments": sum(p["comments"] or 0 for p in items) / len(items),
            "avg_reach": sum(p["reach"] or 0 for p in items) / len(items),
            "er": (sum(ers) / len(ers)) if ers else None,
        })

    # Mediana solo entre bandas elegibles (suficientes posts y ER calculable).
    elegibles = [s["er"] for s in stats
                 if s["n_posts"] >= _MIN_POSTS and s["er"] is not None]
    mediana = statistics.median(elegibles) if elegibles else 0.0
    for s in stats:
        s["sugerida"] = _sugerir(s["er"], mediana, s["prioridad"], s["n_posts"])

    stats.sort(key=lambda s: (s["er"] is None, -(s["er"] or 0)))
    return stats


# ---------- orquestador ----------

def last_sync(cx) -> str | None:
    """ISO del sync más reciente (para el indicador y el auto-refresh si está viejo)."""
    row = cx.execute("SELECT MAX(last_sync) AS t FROM ig_posts").fetchone()
    return row["t"] if row else None


def sync_posts(cx) -> dict[str, Any]:
    """Sync completo: feed → upsert → insights → snapshot → vinculación a bandas.

    Tolerante a fallos parciales: un post sin insights conserva likes/comments
    del feed; si el Sheet no responde, la vinculación se salta con warning.
    """
    items = _fetch_media()
    hoy = datetime.now().strftime("%Y-%m-%d")
    ahora = datetime.now().isoformat(timespec="seconds")
    fallidos = 0
    for i, item in enumerate(items):
        pid = upsert_post(cx, item)
        try:
            save_insights(cx, pid, _fetch_insights(item["id"]))
        except Exception:  # noqa: BLE001 — posts viejos/tipos sin insights
            fallidos += 1
        db.update(cx, "ig_posts", pid, last_sync=ahora)
        snapshot(cx, pid, fecha=hoy)
        if (i + 1) % _BATCH == 0:
            time.sleep(_BATCH_PAUSE)

    warning = None
    vinculados = 0
    try:
        vinculados = link_bands(cx, _sheet_rows())
    except Exception as exc:  # noqa: BLE001 — sin credenciales / Sheet caído
        warning = f"Sheet no disponible, vinculación omitida: {exc}"

    return {"posts": len(items), "insights_fallidos": fallidos,
            "vinculados": vinculados, "warning": warning}
