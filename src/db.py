"""Base de datos local SQLite: fuente de verdad de bandas, fotos, eventos y cola.

El esquema vive en `src/schema.sql` (DDL acordado, idempotente). El Sheet queda
solo como UI de aprobación del Proceso A; estas tablas alimentan al Sheet vía
`src/sync_sheet.py`.

Diseño: helpers genéricos (insert/update/select) con whitelist de columnas por
tabla, para no repetir CRUD a mano cinco veces. Cada conexión activa FK.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# Columnas editables por tabla (whitelist: protege contra typos e inyección de
# nombres de columna). id/created_at/updated_at se manejan solos.
TABLES: dict[str, set[str]] = {
    "accounts": {
        "slug", "ig_handle", "nombre", "ciudad", "timezone",
        "voz_extra", "color_marca", "activa",
    },
    "bands": {
        "nombre", "ig_handle", "tipo", "category_ig", "spotify_id", "ciudad", "activa",
        "popularity", "followers_spotify", "generos",
        "genero_principal", "generos_fuente", "spotify_status",
        "deezer_id", "deezer_status",
        "followers_ig", "link_externo", "bio", "scraped_at", "ig_user_id",
        "n_integrantes", "prioridad", "notas", "account_id",
    },
    "members": {
        "band_id", "nombre", "rol", "ig_handle", "foto_principal_id", "confiabilidad",
    },
    "photos": {
        "band_id", "member_id", "path", "source_post_id", "fecha",
        "faces_count", "es_grupal", "nitidez", "usable_meme", "descartada",
        "caption_original", "usada", "evento_analizado", "persona_id",
    },
    "personas": {"band_id", "member_id", "etiqueta_auto", "centroide"},
    "face_signatures": {"photo_id", "persona_id", "bbox", "det_score", "embedding"},
    "events": {
        "band_id", "tipo", "fecha_evento", "titulo", "cover_url", "lugar", "ciudad",
        "flyer_path", "source_post_id", "parseado_por_llm", "status", "al_final",
        "irrelevante", "creditos", "venue_id",
    },
    "content_queue": {
        "tipo", "band_id", "member_id", "photo_id", "event_id",
        "tema_semilla", "status", "scheduled_datetime", "sheet_row_id", "meme_url",
        "account_id",
        # Motor de segmentos (Task A)
        "template", "formato_patron", "aprobacion", "caption", "imagen_url",
        # Motor de frescura (Task X2): ids de events incluidos en el carrusel,
        # para marcarlos 'anunciado' al aprobar.
        "evento_ids",
        # Historial de captions rechazados con 🔄 (flujo asíncrono).
        "rechazados",
    },
    "ig_posts": {
        "media_id", "band_id", "queue_id", "media_type", "permalink",
        "thumbnail_url", "caption", "timestamp",
        "likes", "comments", "views", "reach", "saved", "shares", "last_sync",
        "account_id",
    },
    "ig_metrics_snapshots": {
        "ig_post_id", "fecha",
        "likes", "comments", "views", "reach", "saved", "shares",
    },
    # Motor de segmentos (Task A)
    "audience_activity": {"account_id", "dow", "hora", "valor", "updated_at"},
    "segment_runs": {"segmento", "account_id", "ventana", "corrido_at"},
    "venues": {"nombre", "ciudad", "ig_handle", "activa"},
    "venue_alias": {"venue_id", "alias_norm", "alias_visto", "origen"},
}

# Estados de content_queue (espejo del CHECK en schema.sql).
QUEUE_BORRADOR = "borrador"
QUEUE_LISTO = "listo"
QUEUE_EN_SHEET = "en_sheet"
QUEUE_PUBLICADO = "publicado"
QUEUE_DESCARTADO = "descartado"

# Tipos de actor que SÍ son artistas musicales: solo estos van a Spotify
# (foro/evento/colectivo no graban discos). Deezer y demás no se restringen.
TIPOS_MUSICALES = ("banda", "solista")


def es_musical(band: dict[str, Any]) -> bool:
    """True si la banda es un artista grabable (banda/solista) → elegible a Spotify."""
    return (band.get("tipo") or "banda") in TIPOS_MUSICALES


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Conexión SQLite con FK activas y filas como dict-like (sqlite3.Row)."""
    path = Path(db_path) if db_path else config.resolve_db_path()
    cx = sqlite3.connect(path)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    return cx


# Columnas agregadas después del esquema inicial → ALTER idempotente para DBs viejas.
_MIGRATIONS = {
    "bands": {
        "tipo": "TEXT NOT NULL DEFAULT 'banda'",
        "category_ig": "TEXT",
        "scraped_at": "TEXT",
        # Caché del id numérico de IG: evita una llamada a web_profile_info por
        # banda en el modo novedades (Frente A del fetch incremental).
        "ig_user_id": "TEXT",
        # Afinación de datos: género de taxonomía fija (config.GENEROS), origen
        # del dato ('llm'|'manual'; el batch nunca pisa manual) y estado del
        # match de Spotify ('pendiente'|'ok'|'no_esta').
        "genero_principal": "TEXT",
        "generos_fuente": "TEXT",
        "spotify_status": "TEXT NOT NULL DEFAULT 'pendiente'",
        # Deezer: fuente primaria de releases (espejo de spotify_id/status).
        "deezer_id": "TEXT",
        "deezer_status": "TEXT NOT NULL DEFAULT 'pendiente'",
        # Multi-cuenta Fase A: todo lo existente cae a la cuenta 1 (gdlscene).
        # SIN cláusula REFERENCES: SQLite prohíbe ADD COLUMN con FK y default
        # no-NULL bajo foreign_keys=ON; la integridad la cuida la app (igual
        # que el resto de columnas migradas). FK dura llegará con Postgres.
        "account_id": "INTEGER NOT NULL DEFAULT 1",
    },
    "events": {
        "titulo": "TEXT",
        "cover_url": "TEXT",
        "al_final": "INTEGER NOT NULL DEFAULT 0",
        # lista negra manual: fechas pasadas o fotos que no son flyers; la
        # clasificación recrearía el evento si se borrara, por eso es una marca.
        "irrelevante": "INTEGER NOT NULL DEFAULT 0",
        # Dedupe cross-banda de releases: JSON list de band_ids que publicaron
        # el mismo flyer (post colab); el caption los acredita con (con @handles).
        "creditos": "TEXT",
        # Catálogo de foros: identidad estable del venue (NULL = sin resolver).
        "venue_id": "INTEGER",
    },
    "content_queue": {
        "meme_url": "TEXT",
        # Multi-cuenta Fase A: ver nota en bands.account_id arriba.
        "account_id": "INTEGER NOT NULL DEFAULT 1",
        # Motor de segmentos: etiquetado de formato y compuerta de aprobación.
        # La compuerta es columna separada (status tiene CHECK fijo en la DB viva).
        "template": "TEXT",
        "formato_patron": "TEXT",
        "aprobacion": "TEXT",            # NULL | 'pendiente' | 'aprobado' | 'rechazado'
        "caption": "TEXT",               # caption de la propuesta (hasta aprobarse)
        "imagen_url": "TEXT",            # URL Cloudinary de la propuesta (o JSON-list si carrusel)
        # Motor de frescura (Task X2): JSON list de events.id incluidos en el
        # carrusel, para marcarlos 'anunciado' al aprobar.
        "evento_ids": "TEXT",
        # Flujo asíncrono: historial JSON de captions rechazados con 🔄, para
        # que el LLM no los repita (equivalente al `rechazados` en memoria del
        # flujo interactivo de bot.py).
        "rechazados": "TEXT",
    },
    "ig_posts": {
        # Multi-cuenta Fase A: ver nota en bands.account_id arriba.
        "account_id": "INTEGER NOT NULL DEFAULT 1",
    },
    "photos": {
        "descartada": "INTEGER NOT NULL DEFAULT 0",
        # El caption de este post ya pasó por el detector de eventos/releases
        # (sea cual sea el resultado). Hace el backfill idempotente: nunca re-LLM.
        "evento_analizado": "INTEGER NOT NULL DEFAULT 0",
        # Banco por persona: cara dominante de la foto (NULL = sin cara o sin agrupar).
        "persona_id": "INTEGER",
    },
    "personas": {
        # Vector medio (128 float32, mismo formato que face_signatures.embedding)
        # de las firmas del grupo AL MOMENTO de crearlo. Persistido en la fila y
        # no solo derivado de las firmas vivas: así una persona nombrada a mano
        # sobrevive un reproceso aunque sus firmas desaparezcan (dedup, fotos
        # descartadas) — el batch nunca pisa lo manual.
        "centroide": "BLOB",
    },
}


def init_db(cx: sqlite3.Connection) -> None:
    """Crea/actualiza el esquema. Idempotente: seguro de correr varias veces."""
    cx.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # SQLite no ALTERa vía CREATE IF NOT EXISTS: agregamos columnas nuevas a mano.
    for tabla, cols in _MIGRATIONS.items():
        existentes = {r["name"] for r in cx.execute(f"PRAGMA table_info({tabla})")}
        for col, ddl in cols.items():
            if col not in existentes:
                cx.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {ddl}")
    # Multi-cuenta Fase A: seed de la cuenta original e índices post-migración
    # (los índices van aquí y no en schema.sql: en DBs viejas la columna
    # account_id no existe todavía cuando corre executescript).
    cx.execute("""INSERT OR IGNORE INTO accounts (id, slug, ig_handle, nombre, ciudad)
                  VALUES (1, 'gdlscene', 'gdlscene', 'La Escena GDL', 'Guadalajara')""")
    for idx in ("CREATE INDEX IF NOT EXISTS idx_bands_account ON bands(account_id)",
                "CREATE INDEX IF NOT EXISTS idx_queue_account ON content_queue(account_id)",
                "CREATE INDEX IF NOT EXISTS idx_igposts_account ON ig_posts(account_id)",
                "CREATE INDEX IF NOT EXISTS idx_personas_band ON personas(band_id)",
                "CREATE INDEX IF NOT EXISTS idx_firmas_photo ON face_signatures(photo_id)",
                "CREATE INDEX IF NOT EXISTS idx_firmas_persona ON face_signatures(persona_id)",
                "CREATE INDEX IF NOT EXISTS idx_alias_venue ON venue_alias(venue_id)",
                "CREATE INDEX IF NOT EXISTS idx_events_venue ON events(venue_id)"):
        cx.execute(idx)
    # Backfill idempotente: banda que ya tiene spotify_id/deezer_id cuenta 'ok'.
    cx.execute("UPDATE bands SET spotify_status = 'ok' "
               "WHERE spotify_id IS NOT NULL AND spotify_id != '' "
               "  AND spotify_status = 'pendiente'")
    cx.execute("UPDATE bands SET deezer_status = 'ok' "
               "WHERE deezer_id IS NOT NULL AND deezer_id != '' "
               "  AND deezer_status = 'pendiente'")
    cx.commit()


def _check_cols(table: str, fields: dict[str, Any]) -> None:
    if table not in TABLES:
        raise KeyError(f"Tabla desconocida: {table}")
    bad = set(fields) - TABLES[table]
    if bad:
        raise KeyError(f"Columnas desconocidas en {table}: {sorted(bad)}")


def insert(cx: sqlite3.Connection, table: str, **fields: Any) -> int:
    """INSERT genérico. Devuelve el id de la fila nueva."""
    _check_cols(table, fields)
    cols = ", ".join(fields)
    marks = ", ".join("?" * len(fields))
    cur = cx.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(fields.values()))
    cx.commit()
    return int(cur.lastrowid)


def update(cx: sqlite3.Connection, table: str, row_id: int, **fields: Any) -> None:
    """UPDATE genérico por id. Lanza si la fila no existe."""
    _check_cols(table, fields)
    sets = ", ".join(f"{c} = ?" for c in fields)
    cur = cx.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*fields.values(), row_id])
    if cur.rowcount == 0:
        raise ValueError(f"No existe {table}.id={row_id}")
    cx.commit()


def get(cx: sqlite3.Connection, table: str, row_id: int) -> dict[str, Any] | None:
    """Una fila por id, como dict (None si no existe)."""
    if table not in TABLES:
        raise KeyError(f"Tabla desconocida: {table}")
    row = cx.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
    return dict(row) if row else None


def rows(cx: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
    """SELECT libre → lista de dicts. Para queries con JOIN/orden específicos."""
    return [dict(r) for r in cx.execute(sql, params).fetchall()]


# ---------- Consultas de uso frecuente ----------

def list_accounts(cx: sqlite3.Connection, solo_activas: bool = True) -> list[dict[str, Any]]:
    """Cuentas de escena, en orden de id (gdlscene primero)."""
    q = "SELECT * FROM accounts"
    if solo_activas:
        q += " WHERE activa = 1"
    return rows(cx, q + " ORDER BY id")


def get_account(cx: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    """Cuenta por slug, o None si no existe."""
    r = rows(cx, "SELECT * FROM accounts WHERE slug = ?", (slug,))
    return r[0] if r else None


def upsert_band(cx: sqlite3.Connection, nombre: str, ig_handle: str | None = None,
                **fields: Any) -> int:
    """Crea la banda o actualiza la existente (match por ig_handle, luego nombre)."""
    row = None
    if ig_handle:
        row = cx.execute("SELECT id FROM bands WHERE ig_handle = ?", (ig_handle,)).fetchone()
    if row is None:
        row = cx.execute("SELECT id FROM bands WHERE nombre = ?", (nombre,)).fetchone()
    if row:
        update(cx, "bands", row["id"], nombre=nombre, ig_handle=ig_handle, **fields)
        return int(row["id"])
    return insert(cx, "bands", nombre=nombre, ig_handle=ig_handle, **fields)


def list_bands(cx: sqlite3.Connection, *, solo_activas: bool = True,
               order: str = "prioridad") -> list[dict[str, Any]]:
    """Bandas ordenadas para la GUI: por prioridad o popularity (desc)."""
    col = {"prioridad": "prioridad DESC, popularity DESC",
           "popularity": "popularity DESC, prioridad DESC",
           "nombre": "nombre COLLATE NOCASE"}.get(order, "prioridad DESC")
    where = "WHERE activa = 1" if solo_activas else ""
    return rows(cx, f"SELECT * FROM bands {where} ORDER BY {col}")


def queue_listos(cx: sqlite3.Connection) -> list[dict[str, Any]]:
    """Filas de content_queue listas para sincronizar al Sheet, con sus joins."""
    return rows(cx, """
        SELECT q.*,
               b.nombre     AS banda_nombre,
               m.nombre     AS member_nombre,
               m.rol        AS member_rol,
               p.path       AS photo_path,
               p.usable_meme AS photo_usable,
               p.caption_original AS photo_caption
          FROM content_queue q
          LEFT JOIN bands   b ON b.id = q.band_id
          LEFT JOIN members m ON m.id = q.member_id
          LEFT JOIN photos  p ON p.id = q.photo_id
         WHERE q.status = ?
         ORDER BY q.id
    """, (QUEUE_LISTO,))


def tipo_de_actor(nombre: str | None, db_path: str | Path | None = None) -> str:
    """Tipo del actor por nombre (para que generate.py pase el ángulo a caption).

    Abre su propia conexión (lo llaman entrypoints sin cx a la mano). Default
    'banda' si no existe en la DB (p. ej. foto manual de una banda no registrada).
    """
    if not nombre:
        return "banda"
    cx = connect(db_path)
    try:
        row = cx.execute("SELECT tipo FROM bands WHERE nombre = ? COLLATE NOCASE",
                         (nombre.strip(),)).fetchone()
        return row["tipo"] if row and row["tipo"] else "banda"
    finally:
        cx.close()


def generos_list(band: dict[str, Any]) -> list[str]:
    """Campo `generos` (JSON en texto) → lista de strings, tolerante a NULL."""
    raw = band.get("generos")
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return [str(g) for g in val] if isinstance(val, list) else []
    except (ValueError, TypeError):
        return []


if __name__ == "__main__":
    # Prueba aislada sobre una DB temporal:  python -m src.db
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        cx = connect(Path(tmp) / "test.db")
        init_db(cx)
        bid = upsert_band(cx, "Noisy Room", "noisyroom.mx", ciudad="Guadalajara", prioridad=5)
        mid = insert(cx, "members", band_id=bid, nombre="Carlos Virgen", rol="guitarrista")
        pid = insert(cx, "photos", band_id=bid, member_id=mid, path="/tmp/foto.jpg",
                     usable_meme=1)
        qid = insert(cx, "content_queue", band_id=bid, member_id=mid, photo_id=pid,
                     tema_semilla="series de TV", status=QUEUE_LISTO)
        # upsert sobre la misma banda no debe duplicar
        assert upsert_band(cx, "Noisy Room", "noisyroom.mx", prioridad=4) == bid
        assert len(list_bands(cx)) == 1
        listos = queue_listos(cx)
        assert len(listos) == 1 and listos[0]["banda_nombre"] == "Noisy Room"
        update(cx, "content_queue", qid, status=QUEUE_EN_SHEET, sheet_row_id="7")
        assert get(cx, "content_queue", qid)["status"] == QUEUE_EN_SHEET
        cx.close()
    print("✅ src/db.py: esquema, CRUD, upsert y cola funcionan.")
