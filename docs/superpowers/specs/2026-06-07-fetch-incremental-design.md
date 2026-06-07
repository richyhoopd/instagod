# Fetch incremental: modo novedades de IG + Spotify solo-nuevas

**Fecha:** 2026-06-07
**Estado:** Aprobado (ejecución multiagente: 3 frentes + orquestador del coordinador)

## Objetivo

No saturar las APIs ni re-revisar lo ya conocido:
- **Bandas nuevas**: ingesta completa (flujo actual, sin cambios — ya es el default
  por `scraped_at IS NULL`).
- **Bandas existentes**: chequeo ligero de NOVEDADES — flyers/eventos nuevos,
  releases nuevos (IG + Spotify) y fotos nuevas al pool de memes — cortando en
  cuanto aparece contenido ya visto.
- **Spotify**: búsqueda solo para bandas sin id (`spotify_status='pendiente'`);
  las que ya tienen id se consultan solo vía el cron eficiente de releases
  (artist_albums), que ya existe.

Decisiones del usuario: cron diario + botón en GUI; detectar releases también
en IG (no solo Spotify); las fotos nuevas de bandas existentes SÍ entran al
pool de memes (clasificador completo).

## Frente A — Modo novedades en `src/ingest_ig.py`

- Migración: `bands.ig_user_id TEXT` (vía `db._MIGRATIONS` + whitelist). La
  ingesta completa y el modo novedades lo guardan al resolver el perfil; si ya
  existe, se salta la llamada a `web_profile_info` (1 llamada menos por banda).
- `novedades(handles=None, max_posts=None)`: bandas activas con
  `scraped_at IS NOT NULL` (las nuevas son de `ingest()`).
  Por banda:
  1. user_id = `bands.ig_user_id` o fetch de perfil (y se persiste).
  2. `fetch_posts` primera página → iterar del más nuevo al más viejo y
     **CORTAR al primer `source_post_id` ya presente en `photos`** de esa banda.
  3. Bajar solo los nuevos (reuso del código de `ingest_band`: mismo insert de
     photos con caption_original/fecha) y actualizar `scraped_at`.
  4. Devuelve por banda: fotos nuevas + shortcodes nuevos (para los pasos
     siguientes del orquestador).
- Delays anti-bot existentes entre bandas (IG_INGEST_DELAY_*). Banda que falla
  (sesión caída, 429) → log y sigue con la siguiente; el resumen las lista.
- CLI: `python -m src.ingest_ig --novedades [handles…]`.
- Tests (red mockeada): corte en post conocido (0 llamadas extra si el primer
  post ya existe), caché de ig_user_id (sin llamada de perfil), banda fallida
  no tumba la corrida, fotos nuevas insertadas con dedup.

## Frente B — Releases desde IG: `src/detect_releases_ig.py`

- Entrada: posts nuevos (band_id, shortcode, caption, path de la foto, fecha).
- DeepSeek (patrón `parse_events`: client OpenAI + `DEEPSEEK_*`, json_object,
  temp=0): ¿el caption anuncia un release? →
  `{es_release, titulo, tipo: sencillo|album, fecha|null}`.
- Si es release: insertar `events` tipo `'release'` con
  `source_post_id='ig:{shortcode}'`, `titulo`, `fecha_evento` (la del LLM o la
  fecha del post), y `cover_url` = path local de la foto del post (las tarjetas
  ya renderizan file://).
- **Dedupe contra Spotify y contra sí mismo**: antes de insertar, si la banda
  ya tiene un release con título similar (casefold, sin sufijos
  sencillo/álbum/EP, match exacto o contención) con fecha a ±30 días → NO
  insertar (Spotify gana: trae portada buena). Mismo shortcode dos veces → no
  duplica (dedupe existente por source_post_id).
- Captions vacíos o LLM caído → ese post se salta, la corrida sigue.
- Tests (LLM mockeado): detecta release y crea evento, caption normal no crea
  nada, dedupe vs release Spotify existente, dedupe por shortcode, JSON
  malformado tolerado.

## Frente C — Pipeline Spotify solo-nuevas + GUI + cron

- `src/pipeline.py` paso spotify: en vez de `enrich_spotify.enrich(objetivo)`,
  correr `spotify_match.resolver_links(cx)` y después
  `enrich_spotify.enrich(solo de bandas spotify_status='pendiente')`
  (las `ok` no se tocan: su data viva son los releases del cron de las 10:00;
  las `no_esta` nunca). Si `enrich` no soporta ese filtro directo, agregarlo
  con un parámetro (p. ej. `solo_pendientes=True`) sin romper la firma actual.
- GUI: botón **"🔄 Novedades"** en el panel de pipeline de `/bandas` que lanza
  `python -m src.novedades` con `_lanzar_sesion`/guardia pgrep existente.
- `scripts/instalar_novedades_diario.sh`: LaunchAgent
  `com.gdlscene.novedades`, diario **09:00** (1h antes del cron de releases
  para que el dedupe Spotify-gana tenga la data del día anterior), mismo
  patrón que `instalar_sync_diario.sh` (PLIST_DEST, --solo-generar, --quitar,
  plutil -lint). No instalarlo durante la implementación.
- Tests: pipeline llama el filtro de pendientes (mocks), botón responde, plist
  válido con rutas correctas.

## Orquestador (post-merge, coordinador): `src/novedades.py`

- `main()`: (1) `ingest_ig.novedades()` → recolecta fotos/posts nuevos;
  (2) `classify.clasificar(handles con fotos nuevas)` → usables al pool,
  flyers a events; (3) `detect_releases_ig` sobre los posts nuevos;
  (4) `parse_events.parse_all()` para flyers nuevos; (5) resumen por Telegram
  (sendMessage HTTP directo sin polling, patrón `check_releases`) y a stdout.
- Guardias: no corre si `pipeline` o `bot.py` están activos (pgrep); respeta
  `spotify_lock` si toca Spotify (no debería); exit code ≠ 0 solo si TODO falló.
- Tests: orquestación con todos los pasos mockeados (orden, resumen, tolerancia
  a paso caído).

## Qué NO cambia

- Ingesta completa para bandas nuevas (default actual).
- Cron de releases Spotify de las 10:00 y cron de métricas de las 21:30.
- `--rescan` sigue disponible para re-bajar histórico a mano.

## Criterios de éxito

- Corrida de novedades sin nada nuevo: ≤1 llamada IG por banda, sin llamadas
  de perfil (ig_user_id cacheado), sin tocar Spotify ni LLM.
- Flyer nuevo publicado por una banda existente aparece en `/calendario` al día
  siguiente sin intervención.
- Release anunciado solo en IG (banda sin Spotify) aparece como evento release.
- El paso spotify del pipeline ya no toca bandas con id.
