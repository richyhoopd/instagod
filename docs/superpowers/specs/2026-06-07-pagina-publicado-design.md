# Página "Publicado" — métricas de Instagram e histórico

**Fecha:** 2026-06-07
**Estado:** Aprobado

## Objetivo

Nueva página `/publicado` en el dashboard web (FastAPI + Jinja2 + HTMX) que muestre todos los posts de la cuenta @gdlscene con sus métricas (likes, comentarios, views, reach, saves, shares), agregados por banda, para decidir a qué bandas hacerles más o menos posts. Incluye sugerencias asistidas de prioridad (el usuario aprueba con un click) e histórico de métricas por snapshots diarios.

## Decisiones tomadas

- **Sugerencias asistidas**: la página sugiere subir/bajar `bands.prioridad` según engagement; el usuario aplica con un click. El planner no cambia.
- **Cobertura**: todo el feed de la cuenta (`/me/media`), no solo posts del bot. Los del bot se ligan a su banda automáticamente; los manuales/viejos se pueden asignar a mano.
- **Refresh**: botón manual "Actualizar métricas" + auto-sync en background al cargar la página si `last_sync` > 6 horas. No hay cron en GitHub Actions: la DB SQLite es local y Actions no la puede escribir.
- **Histórico**: tabla de snapshots (máx 1 por post por día) para ver crecimiento de posts en el tiempo.

## 1. Modelo de datos (agregar a `src/schema.sql`)

```sql
-- Una fila por post en la cuenta de IG (estado actual)
CREATE TABLE ig_posts (
    id INTEGER PRIMARY KEY,
    media_id TEXT UNIQUE NOT NULL,         -- id de la Graph API
    band_id INTEGER REFERENCES bands(id),  -- NULL si es manual/viejo sin asignar
    queue_id INTEGER REFERENCES content_queue(id),  -- liga al post del bot, si aplica
    media_type TEXT,                       -- IMAGE | VIDEO | CAROUSEL_ALBUM
    permalink TEXT,
    thumbnail_url TEXT,                    -- media_url o thumbnail_url según tipo
    caption TEXT,
    timestamp TEXT,                        -- fecha de publicación ISO
    likes INTEGER, comments INTEGER, views INTEGER,
    reach INTEGER, saved INTEGER, shares INTEGER,
    last_sync TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_ig_posts_band ON ig_posts(band_id);
CREATE INDEX idx_ig_posts_timestamp ON ig_posts(timestamp);

-- Histórico: un snapshot por post por sync (máx 1 por día por post)
CREATE TABLE ig_metrics_snapshots (
    id INTEGER PRIMARY KEY,
    ig_post_id INTEGER NOT NULL REFERENCES ig_posts(id),
    fecha TEXT NOT NULL,                   -- YYYY-MM-DD
    likes INTEGER, comments INTEGER, views INTEGER,
    reach INTEGER, saved INTEGER, shares INTEGER,
    UNIQUE(ig_post_id, fecha)              -- re-sync el mismo día = actualiza, no duplica
);
```

## 2. Módulo de sync: `src/ig_insights.py`

`sync_posts()` hace, en orden:

1. **Feed**: pagina `GET /me/media?fields=id,media_type,media_url,thumbnail_url,permalink,caption,timestamp,like_count,comments_count` (Graph API `graph.instagram.com`, misma base/versión/token que `src/instagram.py` — `IG_ACCESS_TOKEN` de `.env`). Upsert en `ig_posts` por `media_id`.
2. **Insights**: por cada post, `GET /{media_id}/insights?metric=reach,saved,shares,views`. En lotes con pausa entre lotes para respetar rate limit. Posts viejos o tipos donde insights falle se quedan solo con likes/comments (no es error fatal).
3. **Vinculación a banda**: lee del Google Sheet las filas con `ig_post_id`, cruza con `content_queue.sheet_row_id` → copia `band_id` y `queue_id` al `ig_posts` correspondiente. Solo para posts con `band_id IS NULL` (nunca pisa asignaciones manuales).
4. **Snapshot**: upsert en `ig_metrics_snapshots` con la fecha de hoy.

Si la API falla a media corrida, se conserva lo sincronizado hasta ese punto y se reporta el error a la página.

## 3. Página `/publicado` (`web/app.py` + templates)

Sigue el patrón existente: ruta en `web/app.py`, template que extiende `base.html`, partials HTMX. Se agrega "Publicado" al nav de `base.html`.

### Sección: Resumen por banda (arriba)

Tabla con: banda, # posts, promedio de likes / comments / reach, engagement rate, prioridad actual, **prioridad sugerida**. Si hay sugerencia de cambio, botón "Aplicar" (HTMX POST que actualiza `bands.prioridad` y re-renderiza la fila). Sin sugerencia → sin botón. Ordenada por engagement rate desc.

### Sección: Grid de posts

Card por post: thumbnail (click → `permalink` en IG), banda, fecha, likes ♥, comments 💬, views ▶, reach, saves. Default: fecha desc. Ordenable por likes y engagement; filtrable por banda. Posts sin banda muestran dropdown para asignar banda a mano (HTMX POST → `ig_posts.band_id`).

### Refresh

- Botón "Actualizar métricas" → endpoint que corre `sync_posts()` y re-renderiza.
- Al cargar, si `MAX(last_sync)` > 6 h (o no hay datos), HTMX dispara el sync en background; la página renderiza primero con lo guardado y se refresca al terminar.
- Indicador "última actualización hace X".

## 4. Lógica de sugerencia de prioridad

Para cada banda con **≥ 2 posts en los últimos 90 días**:

- `ER` por post = `(likes + 2×comments + 3×saved) / reach`. Fallback si no hay reach: `likes / followers_ig` de la banda. Posts sin reach ni followers no cuentan.
- `ER` de la banda = promedio de sus posts elegibles.
- Comparación contra la **mediana de ER de la cuenta** (todas las bandas elegibles):
  - > 40% arriba de la mediana → sugerir **subir un nivel** de prioridad (tope: 1).
  - > 40% abajo de la mediana → sugerir **bajar un nivel** (tope: 5).
  - En medio, o ya en el tope → sin sugerencia.

La sugerencia es solo informativa hasta que el usuario aplica. Aplicar = `UPDATE bands SET prioridad = ?`.

## 5. Manejo de errores

- Fallo total de la Graph API (token vencido, red): la página carga con la data guardada y muestra el mensaje de error del sync.
- Fallo parcial (insights de un post): ese post conserva likes/comments del feed; reach/saves quedan NULL y se excluyen del cálculo de ER por reach (entra el fallback).
- Rate limit: pausas entre lotes de insights; si la API regresa error de límite, el sync para y guarda lo que lleva.

## 6. Testing (`tests/`)

Con respuestas de la API mockeadas (fixtures):

- Upsert idempotente de `ig_posts` (mismo media_id dos veces → 1 fila, métricas actualizadas).
- Snapshot: dos syncs el mismo día → 1 snapshot actualizado; días distintos → 2 snapshots.
- Vinculación Sheet ↔ `content_queue` ↔ banda, y que no pise asignaciones manuales.
- Sugerencias: casos sube / baja / sin cambio / banda con < 2 posts / posts sin reach (fallback) / banda ya en prioridad 1 o 5.

## Fuera de alcance

- Cron remoto (GitHub Actions) para sync de métricas.
- Cambios al planner / score automático por engagement.
- Gráficas de series de tiempo por post (los snapshots dejan la data lista para agregarlas después).
