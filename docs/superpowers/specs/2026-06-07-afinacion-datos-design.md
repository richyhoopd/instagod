# Afinación de datos: géneros LLM, Spotify ids y snapshots diarios

**Fecha:** 2026-06-07
**Estado:** Aprobado (3 frentes, ejecución en paralelo por agentes)

## Contexto / diagnóstico

Con la DB en vivo (96 bandas activas):
- `generos`: 67 con `[]`, 29 NULL, **0 reales**. Verificado en vivo: la API de
  Spotify le responde a esta app con `followers=None, popularity=None,
  genres=None` (cap de apps en dev-mode) → **Spotify no es fuente viable** para
  géneros ni followers. Los releases SÍ funcionan.
- `spotify_id`: 58 activas sin id. El match exige nombre exacto (correcto). Los
  `link_externo` son Linktree/DistroKid/YouTube; los dos primeros suelen
  contener el link de Spotify adentro.
- `ig_metrics_snapshots`: 1 solo día — el sync solo corre al abrir /publicado.

Fuera de alcance de esta etapa: `members`/`photos.member_id` (lo captura el
usuario a mano) y la calibración masiva de `prioridad` (etapa siguiente; el
mecanismo de ajuste por engagement ya existe en /publicado).

## Plomería compartida (Fase 0, antes de los agentes)

- `bands.genero_principal TEXT` (migración idempotente) — género de la taxonomía.
- `bands.generos_fuente TEXT` (`'llm'|'manual'`) — el batch nunca pisa `manual`.
- `bands.spotify_status TEXT NOT NULL DEFAULT 'pendiente'` (`'pendiente'|'ok'|'no_esta'`).
  Backfill: bandas con `spotify_id` → `'ok'`.
- `config.GENEROS`: taxonomía fija de géneros principales:
  punk, garage, indie, shoegaze/dreampop, post-punk, hardcore, metal, hip-hop,
  electrónica, experimental/noise, pop, folk/cantautor, cumbia/tropical,
  funk/soul, rock.

## Frente A — Géneros vía LLM (`src/clasifica_generos.py`)

- Por banda activa con `generos_fuente IS NULL O 'llm'`: armar contexto con
  nombre, bio, `category_ig`, tipo y hasta ~10 captions de sus fotos
  (`photos.caption_original`, las más largas primero).
- DeepSeek (mismo patrón que `parse_events`: OpenAI client + `DEEPSEEK_*` de
  config, `response_format` JSON): devuelve `{genero_principal, subtags[]}`.
  `genero_principal` DEBE ser de `config.GENEROS` (si el LLM inventa, se mapea
  al más cercano o se descarta la corrida de esa banda con log).
- Guardado directo: `genero_principal`, `generos` = JSON de subtags,
  `generos_fuente='llm'`.
- CLI: `python -m src.clasifica_generos [handles…] [--solo-faltantes]`.
- GUI: `genero_principal` como `<select>` (taxonomía) en `_band_edit.html` /
  `guardar_banda` — al guardarse desde la GUI, `generos_fuente='manual'`.
  Filtro `?genero=` en `/bandas` + chip del género en la fila.
- Errores: LLM caído/respuesta no parseable → esa banda queda sin tocar, la
  corrida sigue; resumen al final (clasificadas / falladas / saltadas-manual).
- Tests (mock del LLM): respeta taxonomía, no pisa `manual`, parseo tolerante,
  `--solo-faltantes`.

## Frente B — Spotify ids (`src/spotify_match.py` + vista GUI)

- **Resolvedor de links** (confianza dura): bandas `spotify_status='pendiente'`
  con `link_externo` de linktr.ee / distrokid / lnk.to / songwhip / linkfire:
  GET de la página (requests, timeout corto, User-Agent normal) y regex
  `open.spotify.com/artist/<id>` (reutilizar `_ARTIST_LINK` de enrich_spotify).
  Si aparece: guardar `spotify_id`, `spotify_status='ok'` y registrar releases
  (`_registrar_releases` de enrich_spotify).
- **Vista de matcheo** `/spotify` (nav: "Spotify"): bandas `pendiente`, cada una
  con top-5 de `sp.search(market=MX)` — nombre del candidato + link
  `open.spotify.com/artist/<id>` para oír — y botones:
  - **"es este"** → guarda id, `status='ok'`, registra releases (HTMX, quita la fila).
  - **"no está en Spotify"** → `status='no_esta'` (no se re-busca nunca).
- `enrich_spotify` y este módulo excluyen `no_esta`.
- `followers_spotify`/`popularity` se abandonan como objetivo (cap de la API);
  el impacto del planner ya usa `followers_ig`.
- Errores: página externa caída/timeout → banda sigue `pendiente`; rate limit
  de Spotify → corte limpio (patrón `RateLimitado` existente).
- Tests: extracción de id desde HTML fixture, transición de estados, exclusión
  de `no_esta`, vista con search mockeado.

## Frente C — Snapshots diarios (launchd)

- Entrypoint CLI: `python -m src.ig_insights` → corre `sync_posts()` con la DB
  default, imprime el resumen y append a `data/sync_metrics.log`
  (fecha · posts · fallidos · vinculados · warning). Exit code ≠ 0 si el sync
  truena por completo.
- LaunchAgent `~/Library/LaunchAgents/com.gdlscene.sync-metrics.plist`:
  `StartCalendarInterval` 21:30 (tras el slot de posteo de las 19:00);
  `WorkingDirectory` = repo; ejecuta `.venv/bin/python -m src.ig_insights`;
  stdout/err a `data/launchd_sync.log`. Si la Mac duerme, launchd lo corre al
  despertar; si está apagada, el auto-sync de /publicado cubre el hueco.
- `scripts/instalar_sync_diario.sh [--quitar]`: genera el plist con las rutas
  absolutas del repo actual, `launchctl bootstrap/bootout`, idempotente.
- Tests: el entrypoint con `sync_posts` mockeado (log escrito, exit code);
  el generador del plist produce XML válido con las rutas correctas.

## Ejecución multiagente

Fase 0 la hace el orquestador en master. Después, 3 agentes en worktrees
aislados (branch por frente) con TDD; el orquestador mergea a master, corre la
suite completa y reinicia la GUI. Conflictos esperables solo en `web/app.py`
(secciones distintas → merge automático).

## Criterios de éxito

- A: ≥80% de las 96 bandas activas con `genero_principal` de la taxonomía.
- B: 0 bandas en `pendiente` sin candidatos mostrados; las resueltas por link
  registran sus releases.
- C: snapshot nuevo cada día sin abrir el dashboard (verificable en
  `ig_metrics_snapshots` y el log).
