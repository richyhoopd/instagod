# Deezer como fuente de releases (+ Spotify para el link)

**Fecha:** 2026-06-08
**Estado:** Aprobado

## Contexto

La Spotify Web API murió como fuente de datos en 2026 (Development Mode sin
metadata/endpoints; Extended Quota inalcanzable — ver investigación en memoria).
Decisión: **Deezer** como fuente de releases (sin auth, sin premium, sin el cap
de 23h), **manteniendo Spotify** solo para el link/embed y los `spotify_id` ya
guardados. El hueco de bandas solo-en-YouTube/BandLab lo cubre `detect_releases_ig`.

Reusa el patrón ya construido para Spotify (`spotify_match.py` + vista `/spotify`
+ `spotify_status`); este módulo es su gemelo para Deezer.

## 1. Cliente — `src/deezer.py` (módulo nuevo, sin auth)

- `buscar_artista(nombre) -> list[dict]`: `GET api.deezer.com/search/artist?q=`
  → candidatos `{id, nombre, nb_album, nb_fan, link, picture}`. Sin token.
- `albums(artist_id) -> list[dict]`: `GET api.deezer.com/artist/{id}/albums`
  paginado por `next` → `{album_id, titulo, record_type (album|ep|single),
  release_date (YYYY-MM-DD), cover_url}` (usa `cover_xl`/`cover_big`).
- Throttle suave entre llamadas (`DEEZER_THROTTLE_S=0.3`) y timeout corto.
  HTTP ≥400 → `DeezerError` (corte limpio, lo guardado queda). requests normal
  (sin curl_cffi; Deezer no hace anti-bot de TLS).

## 2. Config — `config.py`

- `DEEZER_API_BASE = "https://api.deezer.com"`, `DEEZER_THROTTLE_S = 0.3`.
- Reusa `SPOTIFY_RELEASE_DAYS` (ventana de "reciente") para Deezer también.

## 3. Match banda→Deezer — `src/deezer_match.py` + vista `/deezer`

Espejo de `spotify_match`:
- Migración: `bands.deezer_id TEXT`, `bands.deezer_status TEXT NOT NULL
  DEFAULT 'pendiente'` (`pendiente|ok|no_esta`; backfill: con deezer_id → ok),
  en `db._MIGRATIONS` + whitelist.
- `resolver_auto(cx)`: para bandas `deezer_status='pendiente'`, `buscar_artista`
  y si hay match EXACTO de nombre (casefold) → guarda `deezer_id`, `status='ok'`.
  Deezer no tiene cap, así que correr las 96 es barato. Dudosos quedan pendiente.
- Vista `GET /deezer` (nav "Deezer"): bandas `pendiente` con sus candidatos
  (search en vivo) + botones "es este" / "no está". `POST /deezer/{id}/elegir`,
  `POST /deezer/{id}/no-esta`, `POST /deezer/resolver-auto`. Templates
  `deezer.html` + `_deezer_row.html` (copia de los de spotify).

## 4. Registro de releases — en `src/deezer.py`

- `registrar_releases(cx, band_id, deezer_id, hoy=None) -> list[dict]`:
  `albums()` con `release_date` dentro de `SPOTIFY_RELEASE_DAYS` → inserta en
  `events` tipo `release`, `source_post_id='dz:{album_id}'`, `titulo`,
  `fecha_evento=release_date`, `cover_url` (portada Deezer; se cachea con
  `covers.py` — el gotcha de DNS era solo `i.scdn.co` de Spotify), `status='nuevo'`.
- **Dedup** antes de insertar:
  a) mismo `source_post_id='dz:{album_id}'` → skip.
  b) la banda ya tiene un release con título similar (casefold, sin sufijos
     (sencillo/álbum/EP), exacto o contención) y `fecha_evento` a ±30 días →
     skip — gana el que ya esté (de Spotify `sp:` o IG `ig:`). Reusa el helper
     de similitud de `detect_releases_ig` (extraer a un sitio común si aplica).

## 5. Cron y pipeline

- `src/check_releases.py` (cron diario 10:00): además del paso Spotify por
  `spotify_id`, corre el paso Deezer por `deezer_id` (bandas `deezer_status='ok'`).
  Mismo aviso por Telegram, dedup compartido en `events`.
- `src/pipeline.py`: el paso de enriquecimiento resuelve también
  `deezer_status='pendiente'` (`deezer_match.resolver_auto`), barato y sin cap.
- Spotify deja de ser la fuente principal de releases; se mantiene su match para
  el link/embed (no se quita nada existente).

## 6. Errores y tests

- Deezer caído / artista sin discografía / 0 candidatos → se salta, sigue.
- Tests (HTTP mockeado, sin red):
  - cliente: `buscar_artista`/`albums` parsean bien y paginan; HTTP≥400 → DeezerError.
  - match: auto-match exacto guarda id/ok; nombre dudoso queda pendiente;
    elegir→ok, no-esta→no_esta; enrich/cron excluyen no_esta.
  - registro: crea release con dz:{id}; dedup por album_id; dedup vs release de
    Spotify existente (título similar ±30 días) → skip; release lejano → inserta.
  - vista `/deezer` con search mockeado (TestClient).

## Fuera de alcance

- **MusicBrainz** (fallback futuro si Deezer no cubre a alguien).
- **Reels con audio** (spec aparte; ver memoria).
- No se quita ni rompe el flujo de Spotify existente.

## Criterios de éxito

- Una banda con presencia en Deezer queda `deezer_status='ok'` tras la corrida
  auto, y sus releases recientes entran a `events` sin duplicar los de Spotify/IG.
- El cron diario reporta releases de ambas fuentes sin el 429 de 23h de Spotify.
