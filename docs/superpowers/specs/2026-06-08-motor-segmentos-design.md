# Motor de segmentos + cerebro de engagement (Pieza 1)

**Fecha:** 2026-06-08 · **Estado:** aprobado por Ricardo

## Visión

@gdlscene (y futuras @cdmxscene/@mtyscene) debe producir contenido recurrente con consistencia ("como reloj"), no cuando Ricardo se acuerde de dispararlo. Cada formato (agenda, releases, premios, versus, encuestas, horóscopo, cruces con datos, y memes de declaraciones) se genera solo en su cadencia, llega a Telegram para que Ricardo o cualquier curador lo apruebe, y se publica en horario de alto tráfico. La aprobación humana NUNCA se elimina.

Dos exigencias de Ricardo, centrales al diseño:
1. **Lo que llega a Telegram ya viene filtrado por un algoritmo de engagement** con DOS ejes: a quién conviene hacer contenido (banda) y QUÉ formato conviene (eje formato, énfasis fuerte).
2. **Lo calendarizado es dinámico**: los slots futuros aún no publicados se reordenan según el desempeño que va entrando.

Insight del propio Ricardo, validado con sus 18 posts: los 2 de mayor reach (1,368 / 1,140) son el mismo formato (integrante + objeto cotidiano absurdo); el de Karacel tuvo 30 shares. **Shares = métrica de crecimiento** (un reshare regala la audiencia de la banda). Reglas ganadoras ya descubiertas → política de arranque en frío.

## Alcance de esta pieza (Pieza 1 — el backbone)

INCLUYE: cerebro de engagement (2 ejes), etiquetado de formato, registro/dispatcher de segmentos, daemon de aprobación no-bloqueante, selector de timing, re-ranker de cola dinámica, y migración de los 4 segmentos vivos (agenda/releases semana/mes) como prueba.

NO INCLUYE (specs aparte, Pieza 2, ya sobre esta base): los formatos nuevos (premios, versus, clasificados, encuestas, horóscopo, cruces con datos). Tampoco Fase B multi-cuenta ni contenerización (specs propios).

## Principios de arquitectura (exigidos: modular y sostenible)

- **Núcleo puro vs IO**: scoring, timing y selección son funciones PURAS (entrada = filas de datos, salida = scores/rankings/datetime), sin tocar DB/Telegram/IG adentro. Una capa delgada de acceso a datos los alimenta. → testeables sin red ni mocks pesados.
- **Una responsabilidad por módulo**, interfaz declarada, comprensible y editable en aislamiento.
- **Arranque en frío explícito y reemplazable**: una *estrategia* decide "¿hay datos suficientes?" → reglas vs aprendido. Cambiar el umbral o las reglas no toca el resto.
- **Multi-cuenta desde el diseño**: `account_id` fluye por las firmas; nada hardcodea gdlscene aunque el cableado multi-cuenta (Fase B) sea otro spec.
- **Reusar patrones existentes**: el etiquetador de formato copia el patrón de `src/clasifica_generos.py` (LLM temp=0 + taxonomía cerrada + `response_format=json_object`); el scoring extiende `ig_insights.band_stats`.

## Componentes

### 1. Etiquetado de formato (`src/format_tags.py` + migración schema)
El eje formato necesita que cada post conozca sus atributos. Tres orígenes:
- **Derivable hoy** (join `ig_posts.queue_id → content_queue`): `tiene_integrante` (member_id no nulo), `tiene_tema` (tema_semilla no vacío).
- **A capturar en generación**: `template` (clasica/verde/onion) — hoy NO se persiste; agregar columna `content_queue.template` y escribirla al generar/aprobar.
- **Semántico vía LLM**: `patron` de una taxonomía CERRADA (`config.FORMATO_PATRONES`, ej. `absurdo_domestico`, `declaracion_personaje`, `dato_falso`, `comunicado`, `otro`). Etiquetador estilo `clasifica_generos`: temp=0, json, mapea contra la taxonomía o `None`. Retroactivo (etiqueta los 18 existentes) + nuevos.
- **Helper de join**: `format_tags.atributos_por_post(cx)` → filas {media_id, reach, shares, saved, tiene_integrante, tiene_tema, template, patron} para que el cerebro aprenda. PURO sobre lo que le pasan.

### 2. Cerebro de engagement (`src/engagement.py`) — núcleo PURO
Dos funciones de scoring + una estrategia de arranque en frío:
- `score_bandas(stats, *, cold_start) -> ranking`: extiende `band_stats` (ER ya pondera saved×3); agrega **peso a shares** y **anti-repetición** (penaliza bandas publicadas recientemente — hoy ninguna tiene >1, hay que repartir). Cold-start cuando `n_posts < umbral`: cae a `(prioridad, followers_ig)`. Hook futuro para reshare-reward (Pieza 3).
- `score_formatos(atributos) -> pesos por patrón/atributo`: aprende qué formato rinde (reach + shares). Cold-start = REGLAS de Ricardo: `absurdo_domestico ↑`, `integrante+tema ↑`, shares pesa triple, taguear siempre. La estrategia mezcla reglas↔aprendido según volumen de datos.
- `elegir_candidatos(cx, n, *, account_id) -> [{band, formato, foto}]`: combina ambos ejes → qué generar. Es lo que pre-filtra lo que llega a Telegram.
- `rerank_cola(cx, *, account_id) -> orden`: re-puntúa los items futuros NO publicados de content_queue y devuelve el nuevo orden.
Todo el scoring PURO; un wrapper delgado (`engagement_io.py` o funciones `_cargar_*` en el mismo módulo, claramente separadas) hace las queries.

### 3. Registro de segmentos (`src/segments.py`) — declarativo
Catálogo: cada segmento = `Segment(clave, nombre, generador, cadencia, ventana_trafico, activo)`. `cadencia` = {tipo: semanal|mensual|diario, dia_semana, dia_mes}. `generador` = callable que produce propuesta(s) y las encola pendientes (no publica, no bloquea). Agregar formato nuevo (Pieza 2) = escribir generador + una entrada aquí. Los 4 vivos (agenda/releases ×2) se registran aquí.

### 4. Dispatcher (`src/segment_runner.py`)
Lee el registro, dispara los segmentos que tocan hoy, idempotente (no regenera el de esta semana si ya corrió — marca de última corrida por segmento+ventana). Es lo que el cron/launchd invoca. CLI `python -m src.segment_runner [--cuenta gdlscene] [--force]`.

### 5. Flujo de aprobación asíncrono (no-bloqueante)
- **Generadores**: arman propuesta → la guardan en content_queue con status nuevo `pendiente_aprobacion` → mandan a Telegram con botones vía `sendMessage` directo (SIN poller). Terminan en segundos.
- **Daemon de aprobación** (`src/approval_daemon.py`): el ÚNICO proceso que hace `getUpdates`. Maneja callbacks ✓/✗ de cualquier curador + pliega el flujo interactivo de memes de `bot.py` (no puede haber dos pollers por token). Al aprobar: `timing.elegir_slot` → escribe Sheet approved + content_queue `en_sheet` con `scheduled_datetime` de alto tráfico. Al rechazar: `descartado`.
- En el server migra a webhook; en la Mac corre como daemon persistente. `publish.py` no cambia.
- Estado nuevo: `content_queue.status` gana `pendiente_aprobacion` (CHECK ampliado vía migración).

### 6. Timing de alto tráfico (`src/timing.py`) — núcleo PURO
`elegir_slot(segmento, ahora, *, fuente) -> datetime`. Prioridad de fuente (estrategia): (a) `online_followers` de IG si poblada → (b) desempeño de tus posts por hora/día cuando haya volumen → (c) **default por segmento** (cold-start; Ricardo lo ajusta). Loguea qué fuente usó. NOTA OBJETIVA: hoy `online_followers` responde 200 pero VACÍO (IG la puebla con ~100+ seguidores) y los posts son pocos → arranca en (c). El módulo ya consume las 3; se auto-activan al haber datos. Un fetcher read-only (`src/audience.py`) guarda `online_followers` en una tabla nueva `audience_activity` cuando IG empiece a darla.

### 7. Re-ranker dinámico
Job (cron semanal) que llama `engagement.rerank_cola` y reordena los `scheduled_datetime` de items futuros no publicados, para que formatos/bandas que despegan ganen los próximos slots. Lo publicado no se toca.

## Datos / migraciones (aditivas, patrón `db._MIGRATIONS`)
- `content_queue`: + `template TEXT`, + `formato_patron TEXT`; CHECK de status amplía con `pendiente_aprobacion`.
- Tabla `audience_activity (account_id, dow, hora, valor, updated_at)` para online_followers.
- Tabla `segment_runs (segmento, account_id, ventana, corrido_at)` para idempotencia del dispatcher.
- Sin tocar FKs duras (SQLite); todo `ADD COLUMN`/`CREATE TABLE IF NOT EXISTS`.

## Errores y resiliencia
- Generadores: si un segmento falla, loguea y sigue con los demás (un formato roto no tumba la tanda).
- Daemon: reconexión ante caída de red; un solo poller (guardia para no arrancar dos).
- LLM etiquetador: si no mapea a la taxonomía → `otro`, nunca inventa categoría.
- Cold-start siempre tiene salida (reglas/default), nunca queda sin decisión por falta de datos.

## Pruebas
- Núcleo puro (engagement scoring, timing, mapeo de taxonomía, rerank) con fixtures sintéticas, sin red.
- Idempotencia del dispatcher y del etiquetado.
- Flujo de aprobación: simular callback de botón → verifica transición de estado + slot asignado.
- Migración sobre DB "vieja" (patrón ya usado en test_multicuenta).

## Criterio de éxito (Pieza 1)
1. Los 4 segmentos vivos corren por dispatcher en su cadencia y llegan a Telegram sin bloquear; cualquier curador aprueba; se publican en slot de alto tráfico.
2. Lo que se propone para memes ya viene elegido por el cerebro (banda+formato), repartiendo bandas y sesgando a formatos ganadores.
3. El re-ranker mueve slots futuros según desempeño.
4. Suite verde; núcleo testeado en aislamiento.
