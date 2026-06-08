# Eventos por caption (independiente de la imagen) + backfill

**Fecha:** 2026-06-09
**Estado:** Aprobado

## Problema (caso @angelxcecena, post DZLcf0Rkans)

Los eventos nacen SOLO de imágenes que el clasificador puntúa como flyer
(`classify.score_flyer`). Un post cuyo póster no puntúa como flyer (o cuyo
anuncio vive solo en el caption) no genera evento — aunque el caption diga
explícitamente fecha/hora/lugar. Verificado: el post se ingirió (3 fotos) pero
`img_0` (el póster) quedó sin flyer/usable/descartada → 0 eventos, pese a que el
caption dice *"Próximo Miércoles 10 de Junio 7:30 PM, Estreno mi EP 'La 4T Del
Perreo'"*. Además `detect_releases_ig` solo lee captions de posts NUEVOS de la
corrida, así que un post ya ingerido nunca se re-analiza.

## Solución

**El caption es la señal autoritativa, no la imagen.** Extender el detector de
captions para sacar también SHOWS (no solo releases), y rellenar el hueco de
posts ya ingeridos sin evento.

### 1. `detect_releases_ig` — detectar shows además de releases

- `SYSTEM_PROMPT` extendido: el LLM devuelve
  `{es_release, es_show, titulo, fecha, lugar, ciudad, tipo}`.
  - `es_release`: como hoy (música nueva propia).
  - `es_show`: true si anuncia un EVENTO en vivo con fecha (concierto, tocada,
    estreno presencial, fiesta) — fecha/hora/lugar en el caption.
- `detectar`:
  - `es_release` → upsert release (comportamiento actual, merge por shortcode).
  - `es_show` (y no release) → si NO existe evento para ese shortcode, inserta
    `tipo='fecha'` con `fecha_evento`, `lugar`, `ciudad`, `titulo`,
    `flyer_path=post.path`, `source_post_id=<shortcode>`, `parseado_por_llm=1`.
    (Si ya existe un evento-flyer del post, lo deja para `parse_events`.)
  - ninguno → nada.
- Compatibilidad: los mocks viejos que solo ponen `es_release` siguen válidos
  (`es_show` ausente = falso).

### 2. Backfill — `backfill_eventos(cx, dias=30)`

- Para posts de los últimos `dias` que tienen fotos pero **ningún evento**
  (`source_post_id` en photos y NOT IN events), reconstruye el dict del post
  (band_id, shortcode, caption_original, path, fecha) y corre `detectar`.
- Recupera @angelxcecena y cualquier otro que se haya escapado por la imagen.
- Se puede invocar desde `novedades` (tras la detección normal) y a mano.

### 3. Errores y tests

- Tolerante (LLM caído → salta, sigue).
- Tests (LLM mockeado): show crea `tipo='fecha'` con fecha/lugar; show NO pisa
  un evento-flyer existente del mismo post; release sin cambios; backfill toma
  un post con fotos y sin evento y crea el evento; backfill ignora posts que ya
  tienen evento.

## Fuera de alcance

- Tunear `score_flyer` (el caption ya cubre el hueco; la imagen sigue como
  señal secundaria).
- Un post que es show Y release a la vez se registra como release (la fecha de
  salida cae en "Próximos lanzamientos"); no se duplica como show.
