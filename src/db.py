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
        "fuentes_imagen", "estilos_json", "voz", "formatos", "logo_path", "posting_slots",
        # Fase 3 (spec 2026-08-21): perfil extendido.
        "descripcion", "sitio_web", "hashtags_default", "prompts_json",
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
        # Motor de slideshows: contrato completo del set (JSON) para
        # regenerar/re-estilar y para el futuro export a video.
        "slideshow_json",
        # Fase 2 (portal): trazabilidad de publicación DB-driven.
        "publicado_en", "error", "creado_por", "aprobado_por", "ig_media_id",
        "origen", "tg_chat_id", "tg_message_id",
        # Fix round 1 (revisión Task 6): límite de reintentos del publisher DB.
        "intentos",
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
    # Portal de colaboradores (spec 2026-08-17)
    "users": {"email", "nombre", "is_admin", "activo", "last_login"},
    "brand_members": {"user_id", "account_id", "rol"},
    "magic_links": {"token_hash", "user_id", "expira", "usado_at"},
    "sessions": {"token_hash", "user_id", "expira", "ua"},
    "brand_secrets": {"account_id", "clave", "valor_cifrado", "updated_by", "updated_at"},
    # Fase 2 (spec 2026-08-20): cola de jobs asíncronos del portal.
    "jobs": {
        "tipo", "account_id", "payload_json", "estado", "progreso", "log",
        "resultado_json", "queue_id", "creado_por", "worker_id", "heartbeat",
        "started_at", "finished_at",
    },
    # Fase 3 (spec 2026-08-21): fuentes de contenido y temas sugeridos por marca.
    "brand_sources": {
        "account_id", "kind", "provider", "config_json", "activa", "orden",
        "ultimo_run", "ultimo_error",
    },
    "topic_suggestions": {
        "account_id", "titulo", "resumen", "url", "fuente", "publicado_en",
        "usado_en_queue_id", "descartado",
    },
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
    # check_same_thread=False: FastAPI corre la dependencia get_cx y el endpoint
    # sync en hilos distintos del threadpool, así que la conexión abierta en un
    # hilo se usa en otro. El acceso por request es serial (una conexión por
    # request, sin concurrencia sobre el mismo objeto), así que es seguro.
    cx = sqlite3.connect(path, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA foreign_keys = ON")
    # WAL + busy_timeout: varios procesos (api, daemon, worker, publisher) escriben
    # la misma DB a la vez; sin esto un writer bloquea a los demás con "database is locked".
    cx.execute("PRAGMA journal_mode = WAL")
    cx.execute("PRAGMA busy_timeout = 5000")
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
        # Motor de slideshows: contrato completo del set (JSON) para
        # regenerar/re-estilar y para el futuro export a video.
        "slideshow_json": "TEXT",
        # Fase 2 (portal, spec 2026-08-20): trazabilidad de publicación
        # DB-driven (publisher/jobs) además de la vía Sheet/Actions legacy.
        "publicado_en": "TEXT",
        "error": "TEXT",
        "creado_por": "INTEGER",
        "aprobado_por": "INTEGER",
        "ig_media_id": "TEXT",
        # Valores: 'api' (creado desde el portal, jobs/handlers.py vía
        # generate_slideshow con creado_por) | 'legacy' (default: plan
        # mensual/generadores viejos) | 'telegram' (flujo interactivo bot.py).
        "origen": "TEXT NOT NULL DEFAULT 'legacy'",
        "tg_chat_id": "TEXT",
        "tg_message_id": "TEXT",
        # Fix round 1 (revisión Task 6): reintentos fallidos de publicación;
        # filas_due excluye intentos >= MAX_INTENTOS (src/publisher.py).
        "intentos": "INTEGER NOT NULL DEFAULT 0",
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
    "accounts": {
        # Multi-marca (spec 2026-08-10): perfil completo de la marca.
        "fuentes_imagen": "TEXT",   # JSON: orden de sourcing ["pinterest","pexels"]
        "estilos_json": "TEXT",     # JSON: presets de slideshow propios (+chrome)
        "voz": "TEXT",              # system-prompt de marca (tono/compliance/imágenes)
        "formatos": "TEXT",         # JSON: formatos habilitados
        "logo_path": "TEXT",        # asset local en data/brands/<slug>/
        "posting_slots": "TEXT",    # "HH:MM,HH:MM" propio; NULL → global
        # Fase 3 (spec 2026-08-21): perfil extendido de marca (portal).
        "descripcion": "TEXT",
        "sitio_web": "TEXT",
        "hashtags_default": "TEXT",  # JSON: lista de hashtags fijos de la marca
        "prompts_json": "TEXT",      # JSON: caption_extra/por_formato/hashtags para el LLM
    },
}


# DDL "de destino" de content_queue tras el rebuild del CHECK(tipo) — congelada
# en el momento de escribir esta migración (no es schema.sql: es un punto fijo
# en el tiempo). _CONTENT_QUEUE_REBUILD_COLS es la lista de columnas que ESTE
# DDL conoce, en orden. Si content_queue gana una columna nueva más adelante
# (otra entrada en _MIGRATIONS), hay que agregarla TAMBIÉN aquí a mano — si no,
# _migrar_check_tipo_queue revienta a propósito (ver el raise abajo) en vez de
# dropear esa columna en silencio durante el rebuild.
_CONTENT_QUEUE_REBUILD_DDL = """
    CREATE TABLE content_queue_new (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo               TEXT    NOT NULL DEFAULT 'meme',
        band_id            INTEGER REFERENCES bands(id)  ON DELETE CASCADE,
        member_id          INTEGER REFERENCES members(id) ON DELETE SET NULL,
        photo_id           INTEGER REFERENCES photos(id)  ON DELETE SET NULL,
        event_id           INTEGER REFERENCES events(id)  ON DELETE SET NULL,
        tema_semilla       TEXT,
        status             TEXT    NOT NULL DEFAULT 'borrador',
        scheduled_datetime TEXT,
        sheet_row_id       TEXT,
        created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
        meme_url           TEXT,
        account_id         INTEGER NOT NULL DEFAULT 1,
        template           TEXT,
        formato_patron     TEXT,
        aprobacion         TEXT,
        caption            TEXT,
        imagen_url         TEXT,
        evento_ids         TEXT,
        rechazados         TEXT,
        slideshow_json     TEXT,
        publicado_en       TEXT,
        error              TEXT,
        creado_por         INTEGER,
        aprobado_por       INTEGER,
        ig_media_id        TEXT,
        origen             TEXT    NOT NULL DEFAULT 'legacy',
        tg_chat_id         TEXT,
        tg_message_id      TEXT,
        intentos           INTEGER NOT NULL DEFAULT 0,
        CHECK (tipo   IN ('meme','anuncio','slideshow')),
        CHECK (status IN ('borrador','listo','en_sheet','programado','publicado','descartado'))
    )
"""
_CONTENT_QUEUE_REBUILD_COLS = (
    "id", "tipo", "band_id", "member_id", "photo_id", "event_id",
    "tema_semilla", "status", "scheduled_datetime", "sheet_row_id",
    "created_at", "updated_at", "meme_url", "account_id", "template",
    "formato_patron", "aprobacion", "caption", "imagen_url", "evento_ids",
    "rechazados", "slideshow_json", "publicado_en", "error", "creado_por",
    "aprobado_por", "ig_media_id", "origen", "tg_chat_id", "tg_message_id",
    "intentos",
)


def _migrar_check_tipo_queue(cx: sqlite3.Connection) -> None:
    """Ensancha los CHECK(tipo)/CHECK(status) de content_queue.

    SQLite no soporta ALTER de un CHECK ya creado: hay que reconstruir la
    tabla (procedimiento oficial de sqlite.org "Making Other Kinds Of Table
    Schema Changes", incluye el PRAGMA foreign_key_check antes del commit).
    Idempotente: solo corre si el CHECK viejo (sin 'slideshow' o sin
    'programado') sigue en sqlite_master; en DBs nuevas ya sale de schema.sql
    con el CHECK correcto y esto es un no-op.
    """
    row = cx.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='content_queue'"
    ).fetchone()
    # OJO: no basta con buscar "slideshow"/"programado" a secas — la columna
    # slideshow_json (agregada arriba vía ALTER TABLE ADD COLUMN) ya deja esa
    # subcadena en el sql guardado aunque el CHECK siga viejo. Hay que buscar
    # el literal exacto de cada CHECK IN (...).
    if row is None or ("'slideshow'" in row[0] and "'programado'" in row[0]):
        return

    # Columnas de la tabla VIEJA (ya con todo lo que _MIGRATIONS le haya
    # agregado arriba vía ALTER). Si trae alguna que el DDL de destino no
    # conoce, NO la dropeamos en silencio: reventamos con un mensaje claro
    # para que quien agregó esa columna actualice también esta migración.
    viejas = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    nuevas = set(_CONTENT_QUEUE_REBUILD_COLS)
    huerfanas = viejas - nuevas
    if huerfanas:
        raise RuntimeError(
            "_migrar_check_tipo_queue no conoce estas columnas de la "
            f"content_queue vieja: {sorted(huerfanas)}. Actualiza "
            "_CONTENT_QUEUE_REBUILD_DDL y _CONTENT_QUEUE_REBUILD_COLS en "
            "db.py antes de correr esta migración — si no, el rebuild las "
            "dropearía en silencio."
        )
    cols_copiar = [c for c in _CONTENT_QUEUE_REBUILD_COLS if c in viejas]
    col_list = ", ".join(cols_copiar)

    # foreign_keys solo se puede tocar FUERA de una transacción — por eso va
    # antes del BEGIN y se restaura en el finally pase lo que pase.
    cx.execute("PRAGMA foreign_keys=OFF")
    try:
        cx.execute("BEGIN")
        cx.execute(_CONTENT_QUEUE_REBUILD_DDL)
        cx.execute(
            f"INSERT INTO content_queue_new ({col_list}) "
            f"SELECT {col_list} FROM content_queue"
        )
        cx.execute("DROP TABLE content_queue")
        cx.execute("ALTER TABLE content_queue_new RENAME TO content_queue")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON content_queue(status)")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_queue_band   ON content_queue(band_id)")
        cx.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_queue_updated
                AFTER UPDATE ON content_queue FOR EACH ROW
                BEGIN UPDATE content_queue SET updated_at = datetime('now') WHERE id = OLD.id; END
        """)
        # Paso final del procedimiento de sqlite.org: con foreign_keys=OFF
        # nada valida las FK del rebuild solas — hay que chequearlas a mano
        # antes del commit.
        violaciones = cx.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            raise RuntimeError(f"foreign_key_check falló tras el rebuild de "
                               f"content_queue: {[tuple(v) for v in violaciones]}")
        cx.execute("COMMIT")
    except BaseException:
        try:
            cx.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass  # sin transacción activa (p. ej. el propio BEGIN falló) — ignora
        raise
    finally:
        cx.execute("PRAGMA foreign_keys=ON")


def init_db(cx: sqlite3.Connection) -> None:
    """Crea/actualiza el esquema. Idempotente: seguro de correr varias veces."""
    cx.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    # SQLite no ALTERa vía CREATE IF NOT EXISTS: agregamos columnas nuevas a mano.
    for tabla, cols in _MIGRATIONS.items():
        existentes = {r["name"] for r in cx.execute(f"PRAGMA table_info({tabla})")}
        for col, ddl in cols.items():
            if col not in existentes:
                cx.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {ddl}")
    _migrar_check_tipo_queue(cx)
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
