# Multi-cuenta (Fase A): schema + seed + helpers

**Fecha:** 2026-06-07 · **Estado:** aprobado por Ricardo

## Contexto y meta

El proyecto va a operar varias cuentas de escena (@gdlscene, @cdmxscene, @mtyscene) con curadores externos y deploy en server. Hoy todo el modelo es single-tenant. Fase A agrega la dimensión "cuenta" al schema **sin cambiar ningún comportamiento** (todo cae al default gdlscene): la operación no se detiene.

Decisiones cerradas con Ricardo:
- **1 banda = 1 cuenta** (FK directa; el crossover de gira se maneja editorialmente).
- **Un solo chat de Telegram** para aprobaciones, con prefijo `[CDMX]` (Fase B).
- **Un solo Google Sheet** con columna `cuenta`; publish resuelve creds por fila (Fase B).
- Front actual (FastAPI+HTMX) se queda; portal de curadores en Next llegará después contra la API (decisión de arquitectura de 2026-06-07).

## Diseño (tenancy opción A: FK solo en tablas raíz)

### Tabla nueva `accounts` (append al final de `schema.sql`)
```sql
CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL UNIQUE,       -- 'gdlscene' | 'cdmxscene' | 'mtyscene'
    ig_handle    TEXT NOT NULL,              -- para tarjetas y captions
    nombre       TEXT NOT NULL,              -- "La Escena GDL"
    ciudad       TEXT NOT NULL,
    timezone     TEXT NOT NULL DEFAULT 'America/Mexico_City',
    voz_extra    TEXT,                       -- textura local del caption (Fase B la puebla)
    color_marca  TEXT NOT NULL DEFAULT '#1b5e3f',
    activa       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (activa IN (0,1))
);
```
+ trigger `trg_accounts_updated` (mismo patrón que las demás).

### FKs nuevas (vía `db._MIGRATIONS`, el patrón idempotente existente)
- `bands.account_id INTEGER NOT NULL DEFAULT 1` (sin cláusula REFERENCES: SQLite prohíbe ADD COLUMN con FK + default no-NULL bajo foreign_keys=ON; la integridad la cuida la app, FK dura llegará con Postgres)
- `content_queue.account_id` y `ig_posts.account_id` igual.
- `photos`/`events`/`members`: SIN columna — heredan cuenta vía `band_id` (sus queries ya joinean bands).
- `bands.ig_handle` sigue UNIQUE global (un handle de IG es único en el mundo).
- Índices `idx_*_account` creados POST-migración en `init_db` (no en schema.sql: en DBs viejas la columna aún no existe cuando corre executescript).

### Seed (en `init_db`, idempotente)
`INSERT OR IGNORE` de la cuenta 1: slug `gdlscene`, ig_handle `gdlscene`, nombre "La Escena GDL", ciudad Guadalajara. Todo lo existente queda en gdlscene vía DEFAULT 1 — cero UPDATEs de datos.

### Credenciales: NUNCA en la DB
Env con sufijo de slug en mayúsculas: `IG_USER_ID__GDLSCENE`, `IG_ACCESS_TOKEN__CDMXSCENE`, `IG_SCRAPER_SESSIONID__MTYSCENE`… Helper `config.account_creds(slug) -> dict` que resuelve por sufijo y, para `gdlscene`, **cae a las vars sin sufijo** (compat con el .env y secrets actuales). En el server con curadores, la DB no contiene tokens.

### Helpers de acceso
- `db.list_accounts(cx, solo_activas=True)`
- `db.get_account(cx, slug)`
- `accounts` entra a la whitelist `TABLES` de db.py.

## Fases siguientes (fuera de este spec)
- **Fase B**: parametrizar caption (voz_extra), plantillas (color/handle), publish multi-creds + columna `cuenta` en Sheet, crons `--cuenta`, prefijo Telegram.
- **Fase C**: alta real de cdmxscene/mtyscene (creds, followees, ingesta).
- **GUI selector de cuenta**: coordinar con el agente que trabaja `web/`.

## Coordinación entre agentes
- Cambios a `db.py`/`schema.sql` son ADITIVOS y montados en el patrón `_MIGRATIONS` existente; no se reescribe nada.
- No tocar `web/` ni `planner.py` en esta fase.
- No commitear sin pedirlo Ricardo (otros agentes mergean worktrees a master).

## Criterio de éxito (Fase A)
1. Suite completa verde sin cambios en tests existentes.
2. DB viva migrada: `accounts` con gdlscene id=1; `bands/content_queue/ig_posts` con `account_id=1` en todas las filas.
3. Flujos actuales (GUI, generación, publish) corren idéntico sin tocarlos.
