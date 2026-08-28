# Planes de contenido masivo — diseño

Fecha: 2026-08-28 · Estado: aprobado en conversación (enfoque A), pendiente de plan de implementación

## Objetivo

Que cualquier marca del portal pueda crear un **plan de contenido** semanal o mensual:
a partir de un objetivo en texto libre (y opcionalmente fuentes de información), el
sistema propone N temas baratos de curar; el usuario aprueba/edita/descarta temas; el
sistema genera en masa los carruseles de los temas aprobados; el usuario cura el lote
(editar slide por slide, descartar carruseles completos) y lo aprueba en bloque; el
publisher existente publica en los slots de la marca.

Marca piloto: **gdlscene** (ya migrada al publisher DB el 2026-08-28: `SHEET_ID`
eliminado del `.env` de la VM, workflow `publish.yml` deshabilitado).

## Qué se reutiliza (no se reescribe)

| Pieza | Dónde |
|---|---|
| Generar un carrusel completo (LLM → imágenes → render → Cloudinary → cola) | `src/generate_slideshow.py::generar` (ya acepta `progreso` y `fuentes`) |
| Editar slide por slide + re-render sin LLM | `src/cola.py::editar_slides` + handler `slideshow.rerender` + `frontend/app/b/[slug]/calendar/_components/slide-editor.tsx` |
| Aprobar una pieza (asigna slot y programa) | `approval.aprobar(cx, qid, user_id)` vía `POST /brands/{slug}/queue/{qid}/aprobar` |
| Slots libres sin choques, en bloque | `src/scheduler.py::slots_proximos_db(cx, account_id, n)` |
| Fuentes de imagen con keys por marca cifradas | `src/image_sources.py` + `brand_sources` + `brand_secrets` (Pexels, Unsplash, carpeta local, banco, covers; Pinterest sigue detrás de `SOURCING_PINTEREST` y bloqueado en la VM) |
| Fuentes de información | `src/topics.py` (RSS, NewsAPI) → `topic_suggestions` |
| Infraestructura de jobs con progreso y heartbeat | `src/jobs/` + `useJob` (polling con backoff) |
| Publicación | `src/publisher.py` (sin cambios) |

## Modelo de datos

Todo en `src/schema.sql` (`CREATE TABLE IF NOT EXISTS`) + `db.TABLES` (whitelist).

### Tabla nueva `content_plans`

```
content_plans(
  id INTEGER PK,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  tipo_periodo TEXT CHECK (tipo_periodo IN ('semana','mes')),
  periodo TEXT NOT NULL,              -- '2026-W36' | '2026-09' (formato de src/segments.py::ventana_de)
  objetivo TEXT NOT NULL,
  config_json TEXT,                   -- {n_piezas, n_slides, aspect, formatos[], fuentes_imagen[], fuentes_info[]}
  estado TEXT CHECK (estado IN ('proponiendo','temas','generando','curacion','aprobado','error'))
         DEFAULT 'proponiendo',
  error TEXT,
  creado_por INTEGER REFERENCES users(id),
  creado_en TEXT
)
```

- Sin UNIQUE(account_id, periodo): pueden coexistir dos planes del mismo periodo; el
  front avisa si ya hay uno. La idempotencia dura (estilo `segment_runs`) queda para
  cuando haya planes automáticos programados (futuro, fuera de alcance).
- `estado` se mueve solo por los jobs y los endpoints; no hay edición libre.

### Tabla nueva `plan_topics`

```
plan_topics(
  id INTEGER PK,
  plan_id INTEGER NOT NULL REFERENCES content_plans(id),
  orden INTEGER,
  titulo TEXT NOT NULL,
  formato TEXT,                       -- clave de config.SLIDESHOW_FORMATOS
  hook TEXT,                          -- ángulo/gancho sugerido por el LLM, editable
  fuente TEXT CHECK (fuente IN ('prompt','noticia','manual')),
  url TEXT,                           -- si viene de una noticia
  topic_suggestion_id INTEGER,        -- FK suave a topic_suggestions si aplica
  estado TEXT CHECK (estado IN ('propuesto','aprobado','descartado','generado','error'))
         DEFAULT 'propuesto',
  error TEXT,
  queue_id INTEGER                    -- fila de content_queue una vez generado
)
```

### `content_queue`: columna nueva `plan_id`

- `ALTER TABLE` vía `_MIGRATIONS` en `src/db.py` **y además** en
  `_CONTENT_QUEUE_REBUILD_DDL` + `_CONTENT_QUEUE_REBUILD_COLS` (si no, el rebuild del
  CHECK lanza `RuntimeError` a propósito). También en `db.TABLES["content_queue"]`.
- Las piezas del plan nacen `tipo='slideshow'` (el CHECK de `tipo` NO se toca),
  `origen='api'`, `aprobacion='pendiente'`, `plan_id` set, **sin** `scheduled_datetime`
  (se asigna al aprobar, como hoy).

## Jobs nuevos (en `src/jobs/handlers.py::HANDLERS`)

### `plan.proponer_temas` — payload `{plan_id}`

1. Carga plan + marca (`src/marcas.py`). Junta contexto de información según
   `config_json.fuentes_info`:
   - `'noticias'`: `topic_suggestions` no usados ni descartados de la marca (si la
     marca tiene `brand_sources` de kind `info`, primero corre el fetch vencido —
     mismo código que `encolar_fuentes_vencidas`, ejecutado inline).
   - `'prompt'`: solo el objetivo + voz de marca.
2. **Una sola llamada LLM** (nuevo módulo `src/plan_temas.py`, mismo patrón que
   `slideshow_script.py`: prompt de sistema, JSON estricto, `extraer`/`validar` puros,
   3 intentos con reinyección de errores): devuelve `n_piezas` temas
   `{titulo, formato, hook, fuente, url?}` diversos entre sí, respetando
   `config_json.formatos` si viene acotado.
3. Inserta `plan_topics` en `orden`; `plan.estado='temas'`.
4. Falla del LLM → `plan.estado='error'` + `plan.error` (sin secretos: patrón
   `_error_seguro`).

### `plan.generar` — payload `{plan_id}`

1. Valida `estado='temas'` y ≥1 topic `aprobado`. `plan.estado='generando'`.
2. **Un solo job** itera los topics aprobados en `orden` (así respeta el aislamiento
   de un-job-por-cuenta del worker y el techo de RAM del render):
   - por topic: `generate_slideshow.generar(cx, tema=titulo, marca=…,
     formato=topic.formato, fuentes=config_json.fuentes_imagen o None,
     n_slides=config_json.n_slides, aspect=config_json.aspect,
     contexto=hook + objetivo del plan, creado_por=plan.creado_por)`
   - al crearse la fila: `db.update(content_queue, qid, plan_id=…)`;
     `topic.estado='generado'`, `topic.queue_id=qid`.
   - progreso agregado: `jobs.progresar(cx, job_id, pct=i/N, msg="pieza i/N: titulo")`
     (mantiene heartbeat < 30 min por pieza → `rescatar_huerfanos` no lo mata).
   - **tolerante a fallos**: una pieza que truena marca `topic.estado='error'` +
     `topic.error` y sigue con la siguiente; el job termina `ok` si ≥1 pieza salió.
3. Al terminar: `plan.estado='curacion'`.
4. Las piezas NO se mandan a Telegram (la curación del lote vive en el portal;
   `generate_slideshow.generar` gana un flag `notificar_telegram=True` que el plan
   pasa en `False` — default preserva el comportamiento actual del wizard).

### Fix acompañante: tolerancia de conteo de slides

`slideshow_script.validar_guion` hoy rechaza el guion si el LLM devuelve n±1 slides y
quema los 3 intentos (visto en prod 2026-08-28: 2 de 8 jobs perdidos por "se pidieron
6, llegaron 7"). Cambio: aceptar `n_slides ± 1` recortando por el final si sobra
(nunca recortar el slide con `rol='cta'`; si falta 1, se acepta tal cual). Con test.

## API (router nuevo `api/routers/planes.py`, `prefix="/brands/{slug}"`, registrado en `api/app.py`)

Todos con `marca_para(slug, cx, user, minimo=…)`. Errores con `ApiError`.

| Endpoint | Rol mínimo | Qué hace |
|---|---|---|
| `POST /plans` | editor | Valida payload (`n_piezas` 1–30, `n_slides` 1–10, `aspect` en `ASPECT_RATIOS`, `formatos` ⊂ `SLIDESHOW_FORMATOS`, `fuentes_imagen` ⊂ fuentes válidas de la marca, `fuentes_info` ⊂ {prompt, noticias}), crea plan + job `plan.proponer_temas` → `{plan_id, job_id}` |
| `GET /plans` | editor | Lista con estado, periodo, conteos (topics aprobados, piezas generadas/curadas) |
| `GET /plans/{pid}` | editor | Detalle: plan + topics + resumen de piezas (id, estado, primera imagen) |
| `POST /plans/{pid}/topics` | editor | Agrega tema manual (`fuente='manual'`, `estado='aprobado'`) |
| `PATCH /plans/{pid}/topics/{tid}` | editor | Edita `titulo/formato/hook`, o `estado` ∈ {aprobado, descartado}; solo mientras el topic no esté `generado` |
| `POST /plans/{pid}/generar` | editor | Valida y encola `plan.generar` → `{job_id}`; 409 si ya hay job vivo del plan |
| `POST /plans/{pid}/aprobar` | editor | **Aprobación en lote server-side**: piezas del plan aún `pendiente` (opcional `queue_ids` para un subset), en orden, llamando `approval.aprobar(cx, qid, user_id)` una por una en la misma request; devuelve `{aprobadas: [{queue_id, slot}], fallidas: [...]}`. Al quedar 0 pendientes → `plan.estado='aprobado'` |

Descartar/regenerar/editar piezas individuales usa los endpoints existentes de cola
(`/queue/{qid}/rechazar`, `/regenerar`, `PUT /queue/{qid}/slides`); no se duplican.

Nota de escala: `slots_proximos_db` vía endpoint topa en 50; la aprobación en lote
usa `approval.aprobar` directo (server-side), así que el tope real es `n_piezas ≤ 30`
por plan, que cabe.

## Frontend (se escribe en `instagod/frontend/` y se sincroniza al repo `instagod-web-app-front`)

- `app/b/[slug]/layout.tsx`: entrada "Planes" en `NAV` (visible para editor+).
- `app/b/[slug]/plans/page.tsx`: lista de planes + diálogo de creación (objetivo
  textarea, periodo semana/mes con selector, `n_piezas`, fuentes de info como toggles,
  fuentes de imagen preseleccionadas del orden de la marca, `n_slides`, aspecto).
  Aviso si ya existe plan del periodo.
- `app/b/[slug]/plans/[pid]/page.tsx`: una pantalla, tres fases según `plan.estado`:
  1. **Temas** (`temas`): lista editable inline (título/hook/formato), aprobar/descartar
     por fila y en lote, agregar manual, botón "Generar N aprobados" con confirmación.
  2. **Generando** (`proponiendo`/`generando`): progreso agregado con `useJob`
     (componente `progreso-job.tsx` existente).
  3. **Curación** (`curacion`): grid de cards; cada card = `ImageCarousel` existente +
     abrir el drawer/`slide-editor.tsx` existentes para editar slide por slide;
     descartar carrusel completo (rechazar); regenerar; al final **"Aprobar plan"**
     con `AlertDialog` que muestra cuántas piezas y desde qué slot arrancan
     (`useSlotsProximos`), llamando `POST /plans/{pid}/aprobar`.
- `hooks/use-plans.ts`: `usePlans/usePlan/useCrearPlan/usePatchTopic/useAgregarTopic/
  useGenerarPlan/useAprobarPlan`, invalidaciones sobre `["plans", slug]` y
  `["queue", slug]`.
- Convenciones: textos en español sin jerga, acciones irreversibles con confirmación,
  gates de estado espejo del backend (patrón `EDITABLES`/`ELIMINABLES` de
  `queue-drawer.tsx`).

## Fuera de alcance (explícito)

- Planes automáticos recurrentes (enganchar a `src/segments.py`): futuro; el modelo
  de `periodo` ya es compatible.
- Mezcla de topics con % y cupos por tipo (estilo content studio de Daisies): cabe
  después como campos de `config_json` sin migración.
- Ingesta Pinterest como fuente de info, métricas de engagement, memes legacy de
  gdlscene (145 `borrador` + 125 `listo` siguen intactos; se reconectan aparte).
- Notificación Telegram del lote.

## Pruebas

Backend (pytest, mismo estilo unitario sin red, fixture `api_cliente`):

- `tests/test_planes_schema.py`: migración (`plan_id` en `content_queue` + rebuild
  constants), whitelist `TABLES`, CHECKs de las tablas nuevas.
- `tests/test_plan_temas.py`: `extraer`/`validar` puros de `src/plan_temas.py`;
  reinyección de errores; respeto de `formatos` acotados.
- `tests/test_jobs_plan.py`: `plan.proponer_temas` (LLM mockeado) y `plan.generar`
  (con `generate_slideshow.generar` monkeypatcheado): progreso agregado, tolerancia a
  fallos por pieza, estados del plan y de topics, `notificar_telegram=False`.
- `tests/test_api_planes.py`: auth/roles (editor sí, marca ajena 404), validaciones
  del payload, 409 con job vivo, aprobación en lote (slots asignados en orden, subset
  por `queue_ids`, transición a `aprobado`).
- `tests/test_slideshow_script.py`: casos nuevos de tolerancia n±1 (recorte sin tirar
  el CTA, aceptar n-1).

Frontend: sin framework de tests en el repo; `pnpm lint` como hoy.

Prueba real de punta a punta: un plan semanal de gdlscene en prod, curado por Ricardo.

## Despliegue

`git archive master` → VM Oracle (`instagod-vm`) → rebuild compose (patrón de
`docs/deploy.md`); las migraciones corren solas en el lifespan de la API y en el
worker. Front: rsync a `instagod-web-app-front` + push (Vercel auto-deploy).
