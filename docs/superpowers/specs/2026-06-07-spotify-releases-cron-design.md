# Releases de Spotify: anti-saturación + cron de fondo

**Fecha:** 2026-06-07 · **Estado:** aprobado por Ricardo

## Contexto

El rate limit de Spotify ya NO está activo (verificado: search y artist_albums responden 200 con portadas). El "trabado" anterior era situacional: dos procesos llamando Spotify a la vez (enrich manual durante pipeline) + spotipy reintentando con backoff infinito → cuelgue aparente. popularity/genres/followers siguen capados permanentemente (Extended Quota); releases + portadas funcionan.

Fuente de artistas: la DB (`bands` activas con `spotify_id`) — el following de IG ya es la curaduría vía `import_followees.py` → candidatas → activar → enrich. No se necesita playlist.

Estado al diseñar: 96 bandas activas, 38 con `spotify_id`, 13 releases en `events`.

## Componentes

### 1. Anti-saturación en `src/enrich_spotify.py`

- Cliente spotipy con `retries=0` (fail-fast). Ante 429: capturar, leer `Retry-After`, abortar la corrida con mensaje claro. Lo procesado queda guardado; la siguiente corrida continúa.
- Throttle ~0.6s entre bandas (configurable `SPOTIFY_THROTTLE_S`).
- Lock file `data/.spotify.lock`: todo proceso que llame Spotify (pipeline, cron, botón ♻ GUI) lo adquiere antes. Si está tomado, el cron se salta la corrida en silencio; el enrich manual avisa y aborta.

### 2. Match de las 58 bandas activas sin `spotify_id`

Corrida única de enrich (ya con throttle). Match exacto o link en bio → se guarda. Dudosas/sin match → lista para corrección manual en GUI. Foros/colectivos sin Spotify quedan fuera del cron naturalmente.

### 3. Cron de releases: `src/check_releases.py` (nuevo)

- Itera bandas activas con `spotify_id` → `artist_albums` → inserta releases nuevos en `events` (tipo=release, `cover_url`), reusando `_registrar_releases` (dedupe por id de álbum).
- Si hay nuevos: mensaje simple a Telegram vía `sendMessage` HTTP directo (SIN polling → no choca con bot.py).
- launchd `~/Library/LaunchAgents/com.gdlscene.releases.plist`: 1×/día ~10:00, corre al prender la Mac si se perdió la hora. Log en `data/logs/releases.log`.

### 4. Calendario con portadas

Sin cambios: `generate_agenda.py --modo releases` ya usa `cover_url`. Solo verificar al final con releases reales.

## Coordinación

Archivos tocados: `enrich_spotify.py`, `check_releases.py` (nuevo), `config.py` (solo agregar vars al final), plist nuevo. NO tocar `planner.py` / `web/` (sistema de prioridad en curso por otra sesión). NO hacer `git commit` (working tree compartido con cambios ajenos).
