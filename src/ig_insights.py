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
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


# Tolerancia al ligar por slot. El publisher DB publica ~1 min después del slot;
# el camino legacy del Sheet (GitHub Actions cada hora) llegaba a ~25 min tarde.
_TOLERANCIA_SLOT = timedelta(minutes=90)

# Estados de content_queue que representan contenido que salió o va a salir. Un
# 'borrador' o un 'descartado' NO puede corresponder a un post real de la cuenta.
_ESTADOS_PUBLICABLES = ("publicado", "programado", "en_sheet")


def _utc(iso: str | None) -> datetime | None:
    """ISO → datetime UTC, tolerando el `+0000` de la Graph API.

    La Graph API devuelve el offset SIN dos puntos (`+0000`), que ni SQLite ni
    `fromisoformat` de Python < 3.11 parsean. Contraparte en SQL de este helper:
    `engagement._JULIANDAY_TS`.
    """
    if not iso:
        return None
    txt = iso.strip()
    if len(txt) >= 5 and txt[-5] in "+-" and txt[-4:].isdigit():
        txt = txt[:-5] + txt[-5:-2] + ":" + txt[-2:]
    try:
        d = datetime.fromisoformat(txt)
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def link_por_media_id(cx) -> int:
    """Liga por `ig_media_id`: exacto, sin heurística. Devuelve cuántos ligó.

    Es el camino BUENO desde que publica el publisher DB, que guarda el
    `ig_media_id` que le devuelve la Graph API al crear el post. No depende del
    Sheet ni de comparar horas: el id o coincide o no.

    Solo toca posts con `band_id` NULL (jamás pisa una asignación manual).
    """
    cur = cx.execute("""
        UPDATE ig_posts SET
            band_id  = (SELECT q.band_id FROM content_queue q
                         WHERE q.ig_media_id = ig_posts.media_id
                           AND q.band_id IS NOT NULL LIMIT 1),
            queue_id = (SELECT q.id FROM content_queue q
                         WHERE q.ig_media_id = ig_posts.media_id
                           AND q.band_id IS NOT NULL LIMIT 1)
         WHERE band_id IS NULL
           AND EXISTS (SELECT 1 FROM content_queue q
                        WHERE q.ig_media_id = ig_posts.media_id
                          AND q.band_id IS NOT NULL)
    """)
    cx.commit()
    return cur.rowcount


def link_por_slot(cx, *, account_id: int = 1,
                  tolerancia: timedelta = _TOLERANCIA_SLOT) -> int:
    """Liga por cercanía de hora lo que no trae `ig_media_id`. Devuelve cuántos ligó.

    Existe para el residuo del camino legacy: las filas que publicó el Sheet +
    GitHub Actions nunca guardaron `ig_media_id`, y desde que se quitó
    `SHEET_ID` tampoco se pueden cruzar contra el Sheet. Sin esto, cada post que
    quede fuera de `link_por_media_id` se pierde para siempre y `band_stats`
    mide con huecos.

    Empareja UNO A UNO (greedy por menor distancia) contra las filas de la cuenta
    que representan contenido publicable, usando `publicado_en` cuando existe y
    `scheduled_datetime` si no. Nunca reusa una fila ya ligada a otro post.
    """
    libres = [p for p in db.rows(cx, """
        SELECT id, media_id, timestamp FROM ig_posts
         WHERE band_id IS NULL AND queue_id IS NULL AND timestamp IS NOT NULL
    """) if _utc(p["timestamp"])]
    if not libres:
        return 0

    placeholders = ", ".join("?" * len(_ESTADOS_PUBLICABLES))
    candidatos = [f for f in db.rows(cx, f"""
        SELECT q.id, q.band_id, COALESCE(q.publicado_en, q.scheduled_datetime) AS cuando
          FROM content_queue q
         WHERE q.account_id = ? AND q.band_id IS NOT NULL
           AND q.status IN ({placeholders})
           AND COALESCE(q.publicado_en, q.scheduled_datetime) IS NOT NULL
           AND NOT EXISTS (SELECT 1 FROM ig_posts ip WHERE ip.queue_id = q.id)
    """, (account_id, *_ESTADOS_PUBLICABLES)) if _utc(f["cuando"])]  # noqa: S608
    if not candidatos:
        return 0

    # Greedy global por menor distancia: evita que un post temprano se quede con
    # la fila que le tocaba a otro solo por venir antes en la lista.
    pares = sorted(
        ((abs(_utc(p["timestamp"]) - _utc(f["cuando"])), p, f)
         for p in libres for f in candidatos),
        key=lambda t: t[0])

    posts_usados: set[int] = set()
    filas_usadas: set[int] = set()
    n = 0
    for dist, post, fila in pares:
        if dist > tolerancia:
            break  # la lista está ordenada: de aquí en adelante todo sobra
        if post["id"] in posts_usados or fila["id"] in filas_usadas:
            continue
        cx.execute("UPDATE ig_posts SET band_id = ?, queue_id = ? WHERE id = ?",
                   (fila["band_id"], fila["id"], post["id"]))
        posts_usados.add(post["id"])
        filas_usadas.add(fila["id"])
        n += 1
    cx.commit()
    return n


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
        # account_id = 1 (gdlscene): los ids de fila del Sheet son
        # auto-incrementales POR HOJA, así que un sheet_row_id de otra marca
        # puede colisionar con uno de gdlscene. sync_posts (todo este módulo)
        # solo lee el Sheet de gdlscene en v1, así que cruzar sin filtrar por
        # cuenta ligaría posts de IG a la banda equivocada de otra marca.
        queue = cx.execute(
            "SELECT id, band_id FROM content_queue WHERE sheet_row_id = ? AND account_id = 1",
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
    # Orden deliberado: primero lo exacto (ig_media_id), luego la heurística de
    # slot para el residuo legacy, y el Sheet SOLO si la marca todavía lo usa.
    # Antes el Sheet era el único camino, así que al quitarle `SHEET_ID` a
    # gdlscene el sync diario reportaba `vinculados=0` y band_stats se degradaba
    # con cada post nuevo.
    vinculados = link_por_media_id(cx)
    vinculados += link_por_slot(cx)
    if config.account_creds("gdlscene").get("SHEET_ID"):
        try:
            vinculados += link_bands(cx, _sheet_rows())
        except Exception as exc:  # noqa: BLE001 — sin credenciales / Sheet caído
            warning = f"Sheet no disponible, vinculación por Sheet omitida: {exc}"

    # Eje formato del cerebro: etiquetar formato_patron de lo recién vinculado.
    etiquetados = 0
    try:
        from src import format_tags
        etiquetados = format_tags.etiquetar_publicados(cx)["etiquetados"]
    except Exception as exc:  # noqa: BLE001 — LLM caído no tumba el sync
        aviso = f"etiquetado de formato omitido: {exc}"
        warning = f"{warning} | {aviso}" if warning else aviso

    return {"posts": len(items), "insights_fallidos": fallidos,
            "vinculados": vinculados, "etiquetados": etiquetados,
            "warning": warning}


# ---------- entrypoint CLI (sync diario para launchd) ----------

# Log por defecto relativo al cwd: launchd corre con WorkingDirectory = repo,
# así que cae en <repo>/data/ sin depender de config (testeable vía log_path).
_LOG_DEFAULT = "data/sync_metrics.log"


def _append_log(log_path: Path, linea: str) -> None:
    """Agrega una línea al log, creando el directorio si hace falta."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(linea + "\n")


def main(db_path: str | Path | None = None,
         log_path: str | Path | None = None) -> int:
    """Corre el sync completo, imprime el resumen y lo deja en el log.

    Devuelve exit code: 0 si el sync terminó, 1 si `sync_posts` reventó (para
    que launchd lo registre como fallo). Los parámetros existen para los tests;
    en producción se usan los defaults (DB de config, log en cwd/data/).
    """
    log = Path(log_path) if log_path else Path(_LOG_DEFAULT)
    ahora = datetime.now().isoformat(timespec="seconds")

    cx = db.connect(db_path)
    try:
        db.init_db(cx)
        res = sync_posts(cx)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo = sync caído
        _append_log(log, f"{ahora} · ERROR · {exc}")
        print(f"sync falló: {exc}")
        return 1
    finally:
        cx.close()

    warning = res.get("warning") or "-"
    linea = (f"{ahora} · posts={res['posts']} "
             f"· sin_insights={res['insights_fallidos']} "
             f"· vinculados={res['vinculados']} "
             f"· etiquetados={res.get('etiquetados', 0)} · warning={warning}")
    _append_log(log, linea)
    print(linea)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
