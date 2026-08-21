-- =============================================================================
-- @gdlscene — Esquema SQLite de la base de datos de bandas
-- =============================================================================
-- Este es el DDL ACORDADO (paso 2 del brief, ver claude_code_brief.md §8).
-- Es la fuente de verdad del proyecto; el Google Sheet queda solo como UI de
-- aprobación del caption y cola de publicación del Proceso A.
--
-- Propiedades:
--   - Idempotente: usa CREATE TABLE IF NOT EXISTS (se puede correr varias veces).
--   - 5 tablas: bands, members, photos, events, content_queue.
--   - updated_at se mantiene solo vía triggers.
--   - Relación circular intencional (members.foto_principal_id <-> photos.member_id):
--     SQLite lo permite porque la verificación de FK es diferida; por eso se crea
--     `photos` antes que `members` y se referencia hacia adelante.
--
-- Uso desde Python (src/db.py):
--   con sqlite3.connect(...) as cx:
--       cx.executescript(open("src/schema.sql").read())
--   Recuerda activar FK en cada conexión:  PRAGMA foreign_keys = ON;
-- =============================================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;   -- mejor concurrencia: la GUI lee mientras la ingesta escribe

-- -----------------------------------------------------------------------------
-- bands — una fila por banda/artista que sigues y curas
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bands (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre             TEXT    NOT NULL,
    ig_handle          TEXT    UNIQUE,                 -- @sin arroba; clave para ingesta y @menciones
    -- Tipo de actor (define el ÁNGULO del chiste y el filtro de fotos) ----------
    tipo               TEXT    NOT NULL DEFAULT 'banda',-- banda|solista|foro|evento|colectivo
    category_ig        TEXT,                           -- categoría declarada en IG (señal del triage)
    spotify_id         TEXT,                           -- id de artista en Spotify (se llena en Fase 4)
    ciudad             TEXT,
    activa             INTEGER NOT NULL DEFAULT 1,      -- bool: 1 sigue activa, 0 archivada
    -- Enriquecimiento Spotify (Fase 4) ----------------------------------------
    popularity         INTEGER,                         -- 0-100 (Spotify); NULL si aún no enriquecida
    followers_spotify  INTEGER,
    generos            TEXT,                            -- JSON: ["punk","garage",...]
    -- Datos de Instagram (Fase 2) ---------------------------------------------
    followers_ig       INTEGER,
    link_externo       TEXT,                            -- link de la bio (Linktree/Spotify) → ayuda al match
    bio                TEXT,
    scraped_at         TEXT,                            -- ISO del último scrapeo; NULL = nunca scrapeada
    -- Curación manual ----------------------------------------------------------
    n_integrantes      INTEGER,
    prioridad          INTEGER NOT NULL DEFAULT 3,      -- 1-5: cuánta atención de contenido le das
    notas              TEXT,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (activa IN (0,1)),
    CHECK (tipo IN ('banda','solista','foro','evento','colectivo')),
    CHECK (prioridad BETWEEN 1 AND 5),
    CHECK (popularity IS NULL OR popularity BETWEEN 0 AND 100)
);
CREATE INDEX IF NOT EXISTS idx_bands_prioridad  ON bands(prioridad DESC, popularity DESC);
CREATE INDEX IF NOT EXISTS idx_bands_activa      ON bands(activa);

-- -----------------------------------------------------------------------------
-- photos — fotos descargadas; candidatas a meme tras clasificación
-- (se crea antes que members por la FK circular foto_principal_id)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS photos (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id            INTEGER NOT NULL REFERENCES bands(id) ON DELETE CASCADE,
    member_id          INTEGER REFERENCES members(id) ON DELETE SET NULL,  -- forward ref (OK en SQLite)
    path               TEXT    NOT NULL,                -- ruta local fuera de git
    source_post_id     TEXT,                            -- id/shortcode del post de IG de origen
    fecha              TEXT,                            -- fecha del post (ISO 8601)
    -- Señales de clasificación (Fase 3) ---------------------------------------
    faces_count        INTEGER,
    es_grupal          INTEGER,                         -- bool: >1 cara clara
    nitidez            REAL,                            -- varianza del Laplaciano (mayor = más nítida)
    usable_meme        INTEGER NOT NULL DEFAULT 0,      -- bool: pasó el filtro / aprobada en GUI
    descartada         INTEGER NOT NULL DEFAULT 0,      -- bool: lista negra MANUAL (nunca sugerir)
    caption_original   TEXT,                            -- caption del post (insumo para tema_semilla)
    usada              INTEGER NOT NULL DEFAULT 0,      -- bool: ya se usó en un meme publicado
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (usable_meme IN (0,1)),
    CHECK (usada IN (0,1)),
    CHECK (es_grupal IS NULL OR es_grupal IN (0,1)),
    UNIQUE (band_id, source_post_id, path)             -- evita duplicar la misma foto
);
CREATE INDEX IF NOT EXISTS idx_photos_band        ON photos(band_id);
CREATE INDEX IF NOT EXISTS idx_photos_usable       ON photos(usable_meme, usada);

-- -----------------------------------------------------------------------------
-- members — integrantes de cada banda (lineup; sembrado a mano o por LLM)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS members (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id            INTEGER NOT NULL REFERENCES bands(id) ON DELETE CASCADE,
    nombre             TEXT    NOT NULL,
    rol                TEXT,                            -- guitarrista, baterista, vocalista...
    ig_handle          TEXT,
    foto_principal_id  INTEGER REFERENCES photos(id) ON DELETE SET NULL,
    confiabilidad      REAL    NOT NULL DEFAULT 1.0,    -- 0-1: qué tan seguro es el mapeo nombre↔rol
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (confiabilidad BETWEEN 0 AND 1)
);
CREATE INDEX IF NOT EXISTS idx_members_band       ON members(band_id);

-- -----------------------------------------------------------------------------
-- events — fechas, flyers y releases detectados (alimenta los anuncios)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id            INTEGER NOT NULL REFERENCES bands(id) ON DELETE CASCADE,
    tipo               TEXT    NOT NULL,                -- 'fecha' | 'flyer' | 'release'
    fecha_evento       TEXT,                            -- fecha del show/lanzamiento (ISO 8601)
    titulo             TEXT,                            -- nombre del release (álbum/single); shows opcional
    cover_url          TEXT,                            -- portada del álbum (Spotify) para releases
    lugar              TEXT,                            -- venue (shows); NULL en releases
    ciudad             TEXT,
    flyer_path         TEXT,                            -- ruta local del flyer si aplica
    source_post_id     TEXT,
    parseado_por_llm   INTEGER NOT NULL DEFAULT 0,      -- bool: ya pasó por DeepSeek
    status             TEXT    NOT NULL DEFAULT 'nuevo',-- 'nuevo' | 'anunciado' | 'pasado'
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (tipo   IN ('fecha','flyer','release')),
    CHECK (status IN ('nuevo','anunciado','pasado')),
    CHECK (parseado_por_llm IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_events_band         ON events(band_id);
CREATE INDEX IF NOT EXISTS idx_events_status_fecha ON events(status, fecha_evento);

-- -----------------------------------------------------------------------------
-- content_queue — trabajos de contenido generados desde la DB.
-- Equivale a tus filas `pending`, pero como fuente de verdad. El sync los
-- escribe al Google Sheet cuando status='listo'. (Sin 'reel': video fuera de alcance.)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_queue (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo               TEXT    NOT NULL DEFAULT 'meme', -- 'meme' | 'anuncio' | 'slideshow'
    band_id            INTEGER REFERENCES bands(id)  ON DELETE CASCADE,
    member_id          INTEGER REFERENCES members(id) ON DELETE SET NULL,
    photo_id           INTEGER REFERENCES photos(id)  ON DELETE SET NULL,
    event_id           INTEGER REFERENCES events(id)  ON DELETE SET NULL,
    tema_semilla       TEXT,
    status             TEXT    NOT NULL DEFAULT 'borrador',
                                                        -- borrador|listo|en_sheet|programado|publicado|descartado
    scheduled_datetime TEXT,                            -- lo asigna scheduler.py tras aprobar
    sheet_row_id       TEXT,                            -- id de la fila en el Sheet (para rastrear)
    created_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (tipo   IN ('meme','anuncio','slideshow')),
    CHECK (status IN ('borrador','listo','en_sheet','programado','publicado','descartado'))
);
CREATE INDEX IF NOT EXISTS idx_queue_status        ON content_queue(status);
CREATE INDEX IF NOT EXISTS idx_queue_band          ON content_queue(band_id);

-- -----------------------------------------------------------------------------
-- ig_posts — espejo del feed de @gdlscene con métricas del último sync.
-- Cubre TODO el feed (también posts manuales/viejos); los del bot se ligan a su
-- banda vía Sheet.ig_post_id ↔ content_queue.sheet_row_id. Alimenta /publicado.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ig_posts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id           TEXT    NOT NULL UNIQUE,          -- id del media en la Graph API
    band_id            INTEGER REFERENCES bands(id)         ON DELETE SET NULL,
    queue_id           INTEGER REFERENCES content_queue(id) ON DELETE SET NULL,
    media_type         TEXT,                             -- IMAGE | VIDEO | CAROUSEL_ALBUM
    permalink          TEXT,
    thumbnail_url      TEXT,                             -- media_url, o thumbnail_url en videos
    caption            TEXT,
    timestamp          TEXT,                             -- fecha de publicación (ISO 8601)
    -- Métricas del último sync (NULL = insights no disponibles para ese post) --
    likes              INTEGER,
    comments           INTEGER,
    views              INTEGER,
    reach              INTEGER,
    saved              INTEGER,
    shares             INTEGER,
    last_sync          TEXT,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ig_posts_band      ON ig_posts(band_id);
CREATE INDEX IF NOT EXISTS idx_ig_posts_timestamp  ON ig_posts(timestamp);

-- -----------------------------------------------------------------------------
-- ig_metrics_snapshots — histórico: máx 1 snapshot por post por día.
-- Re-sync el mismo día actualiza la fila (upsert), no duplica.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ig_metrics_snapshots (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    ig_post_id         INTEGER NOT NULL REFERENCES ig_posts(id) ON DELETE CASCADE,
    fecha              TEXT    NOT NULL,                 -- YYYY-MM-DD
    likes              INTEGER,
    comments           INTEGER,
    views              INTEGER,
    reach              INTEGER,
    saved              INTEGER,
    shares             INTEGER,
    UNIQUE (ig_post_id, fecha)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_post      ON ig_metrics_snapshots(ig_post_id);

-- -----------------------------------------------------------------------------
-- Triggers: mantener updated_at al día (solo en tablas que lo tienen)
-- -----------------------------------------------------------------------------
CREATE TRIGGER IF NOT EXISTS trg_bands_updated
    AFTER UPDATE ON bands FOR EACH ROW
    BEGIN UPDATE bands SET updated_at = datetime('now') WHERE id = OLD.id; END;

CREATE TRIGGER IF NOT EXISTS trg_members_updated
    AFTER UPDATE ON members FOR EACH ROW
    BEGIN UPDATE members SET updated_at = datetime('now') WHERE id = OLD.id; END;

CREATE TRIGGER IF NOT EXISTS trg_events_updated
    AFTER UPDATE ON events FOR EACH ROW
    BEGIN UPDATE events SET updated_at = datetime('now') WHERE id = OLD.id; END;

CREATE TRIGGER IF NOT EXISTS trg_queue_updated
    AFTER UPDATE ON content_queue FOR EACH ROW
    BEGIN UPDATE content_queue SET updated_at = datetime('now') WHERE id = OLD.id; END;

-- -----------------------------------------------------------------------------
-- accounts — cuentas de escena (@gdlscene, @cdmxscene, @mtyscene). Multi-cuenta
-- Fase A: bands/content_queue/ig_posts cargan account_id (DEFAULT 1 = gdlscene);
-- photos/events/members heredan la cuenta vía band_id. Las CREDENCIALES nunca
-- viven aquí: van en env con sufijo (IG_ACCESS_TOKEN__CDMXSCENE...), ver config.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL UNIQUE,
    ig_handle    TEXT NOT NULL,
    nombre       TEXT NOT NULL,
    ciudad       TEXT NOT NULL,
    timezone     TEXT NOT NULL DEFAULT 'America/Mexico_City',
    voz_extra    TEXT,                                    -- textura local del caption
    color_marca  TEXT NOT NULL DEFAULT '#1b5e3f',
    activa       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (activa IN (0,1))
);

CREATE TRIGGER IF NOT EXISTS trg_accounts_updated
    AFTER UPDATE ON accounts FOR EACH ROW
    BEGIN UPDATE accounts SET updated_at = datetime('now') WHERE id = OLD.id; END;

-- -----------------------------------------------------------------------------
-- audience_activity — "seguidores en línea" de IG (online_followers) por
-- día-de-semana y hora, por cuenta. Alimenta timing de alto tráfico.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audience_activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL DEFAULT 1,
    dow         INTEGER NOT NULL,                 -- 0=lunes … 6=domingo
    hora        INTEGER NOT NULL,                 -- 0-23 (hora local de la cuenta)
    valor       INTEGER NOT NULL,                 -- seguidores online promedio
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, dow, hora)
);

-- -----------------------------------------------------------------------------
-- segment_runs — idempotencia del dispatcher: 1 corrida por segmento+ventana.
-- ventana = clave de periodo (ej. '2026-W23' semanal, '2026-06' mensual).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS segment_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    segmento    TEXT NOT NULL,
    account_id  INTEGER NOT NULL DEFAULT 1,
    ventana     TEXT NOT NULL,
    corrido_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (segmento, account_id, ventana)
);

-- =====================================================================
-- personas — grupo automático de caras dentro de una banda ("persona A de
-- Kabala"). member_id la liga a `members` cuando Ricardo le pone nombre y rol
-- en la GUI; hasta entonces es anónima pero utilizable para dar variedad.
-- =====================================================================
CREATE TABLE IF NOT EXISTS personas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id       INTEGER NOT NULL,
    member_id     INTEGER,
    etiqueta_auto TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- =====================================================================
-- face_signatures — una fila por cara detectada. `embedding` es el vector de
-- 128 float32 de SFace, L2-normalizado, como BLOB (512 bytes). Guardarlo
-- permite reagrupar con otro umbral sin volver a procesar imágenes.
-- =====================================================================
CREATE TABLE IF NOT EXISTS face_signatures (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id   INTEGER NOT NULL,
    persona_id INTEGER,
    bbox       TEXT NOT NULL,
    det_score  REAL NOT NULL,
    embedding  BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- =============================================================================
-- venues — foros canónicos. `events.lugar` es texto libre que un LLM saca del
-- OCR y trae el mismo foro con media docena de escrituras; esta tabla es la
-- identidad estable contra la que se resuelven. `ig_handle` liga al foro que ya
-- se sigue en `bands`, cuando existe.
-- Salas distintas = venues distintos (C3 Stage y C3 Rooftop son dos filas).
-- =============================================================================
CREATE TABLE IF NOT EXISTS venues (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    ciudad     TEXT,
    ig_handle  TEXT,
    activa     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- =============================================================================
-- venue_alias — cada escritura vista de un foro, normalizada. venue_id NULL =
-- alias HUÉRFANO: texto visto en un flyer que nadie ha asignado todavía; es la
-- cola de curación de la GUI. `alias_visto` guarda el texto crudo porque al
-- curar hace falta ver qué decía el flyer, no la versión normalizada.
-- origen: 'semilla' | 'visto' | 'llm' | 'manual' | 'no_es_lugar'
-- =============================================================================
CREATE TABLE IF NOT EXISTS venue_alias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id    INTEGER,
    alias_norm  TEXT NOT NULL UNIQUE,
    alias_visto TEXT NOT NULL,
    origen      TEXT NOT NULL DEFAULT 'visto',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- Portal de colaboradores (spec 2026-08-17): usuarios, roles por marca,
-- magic links, sesiones y secretos cifrados por marca. Los tokens se guardan
-- SIEMPRE hasheados (sha256); el valor de un secreto SIEMPRE cifrado (Fernet).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE,
    nombre      TEXT,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    activo      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_login  TEXT,
    CHECK (is_admin IN (0,1)), CHECK (activo IN (0,1))
);

CREATE TABLE IF NOT EXISTS brand_members (
    user_id     INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    rol         TEXT NOT NULL,
    PRIMARY KEY (user_id, account_id),
    CHECK (rol IN ('manager', 'editor'))
);

CREATE TABLE IF NOT EXISTS magic_links (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expira      TEXT NOT NULL,
    usado_at    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expira      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    ua          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS brand_secrets (
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    clave          TEXT NOT NULL,
    valor_cifrado  TEXT NOT NULL,
    updated_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (account_id, clave)
);

-- -----------------------------------------------------------------------------
-- Fase 2 (spec 2026-08-20): cola de jobs asíncronos del portal (generación de
-- sets de imágenes, publicaciones, etc). Un worker toma filas en estado
-- 'cola', reporta progreso/heartbeat mientras corre y deja el resultado en
-- resultado_json al terminar.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT NOT NULL,
    account_id   INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT,
    estado       TEXT NOT NULL DEFAULT 'cola',
    progreso     INTEGER NOT NULL DEFAULT 0,
    log          TEXT,
    resultado_json TEXT,
    queue_id     INTEGER,
    creado_por   INTEGER,
    worker_id    TEXT,
    heartbeat    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT,
    CHECK (estado IN ('cola','corriendo','ok','error','cancelado'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_estado ON jobs(estado);
CREATE INDEX IF NOT EXISTS idx_jobs_account ON jobs(account_id);
