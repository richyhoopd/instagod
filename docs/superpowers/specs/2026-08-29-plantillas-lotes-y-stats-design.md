# Plantillas por marca, lotes desde la UI y estadísticas — diseño

Fecha: 2026-08-29 · Rama: `plantillas-y-lotes`

## Problema

instagod son hoy **dos sistemas que no se hablan**.

| | Sistema A (viejo) | Sistema B (nuevo) |
|---|---|---|
| UI | `web/app.py` + htmx. Mono-marca, sin auth, solo localhost, no está en `docker-compose.yml` | `api/` FastAPI + `frontend/` Next 16. Multi-marca, roles, en prod |
| Contenido | posts de una imagen (`src/compose.py` → `clasica`/`verde`/`onion`/`anuncio`) | slideshows/carruseles por LLM (`content_plans` → `jobs`) |
| Selección | `src/planner.py` + `src/engagement.py` (`score_plan`) | curación manual de temas |
| Aprobación | Telegram (`src/approval_daemon.py`) | botones en el portal |
| Estadísticas | `/publicado` (`ig_insights.band_stats`) | ninguna |
| Tablas | `bands`, `photos`, `members`, `events`, `ig_posts` | `accounts`, `content_queue`, `brand_sources`, `jobs` |

Todo lo que funciona de gdlscene vive en A. Todo lo multi-marca vive en B. El pedido
—posts simples para cualquier marca, plantillas por marca diseñadas con un LLM, lotes
desde la UI, dashboard y estadísticas por marca— no es una lista de features: es
**absorber A dentro de B**.

La buena noticia: el motor de render ya es genérico. `src/compose.py`, `templates/*.html`
y el screenshot con Playwright no tienen ni una referencia a bandas o eventos. El
acoplamiento a gdlscene está en la capa que *alimenta* al motor (`generate.py`,
`src/caption.py`, tablas de dominio musical), no en el que *dibuja*.

## Decisiones tomadas

| # | Decisión | Alternativa descartada |
|---|---|---|
| 1 | Entidad genérica por marca (`brand_entities`), opcional pero disponible para todas | Medir solo por plantilla/formato; dejar `bands` como caso especial |
| 2 | `brand_entities` es tabla nueva; `bands` y sus 5 tablas colgadas **no se tocan** | Migrar `bands` dentro de `brand_entities`; VIEW de compatibilidad |
| 3 | Contrato de plantilla **híbrido**: núcleo garantizado + extras declarados por la plantilla | Contrato fijo para todas; esquema totalmente libre |
| 4 | El portal es canónico; Telegram se activa **por marca** si tiene bot configurado. Ambos caminos pueden disparar y aprobar | Reemplazar Telegram; dejarlo obligatorio |
| 5 | Diseñador de plantillas = **chat con versiones**, una plantilla a la vez | Lote de variantes; ambos |
| 6 | Tipografías: catálogo local, ampliable por marca (`brand_fonts`) | Google Fonts en tiempo de diseño; Google Fonts en vivo |
| 7 | Las 3 plantillas de gdlscene entran a la DB como plantillas normales, editables, con su original como v1 | Congeladas; se quedan en archivo |
| 8 | Formatos del post simple: **4:5 (1080×1350) y 9:16 (1080×1920)** | Agregar 1:1 |
| 9 | Estadísticas: por entidad, por plantilla, por horario, y evolución de la cuenta | Solo por entidad |
| 10 | Se portan **las 13 vistas** del htmx | Portar solo lotes y estadísticas |
| 11 | Sandbox de render **apagado por defecto**, tras flag `TEMPLATE_RENDER_SANDBOX` | Sandbox estricto obligatorio; sanitizado con allowlist |
| 12 | Una sola rama larga con 5 hitos internos | Fases desplegables por separado |

### Sobre la decisión 11

El HTML que produzca DeepSeek se renderiza en el mismo Chromium que hoy carga plantillas
con `file://` y rutas locales de fotos y fuentes. Una plantilla alucinada o maliciosa
podría leer archivos del servidor y mandarlos afuera. Ricardo decidió no restringirlo por
ahora, con el contexto completo.

Mitigación acordada: el bloqueo de red se implementa igual, como `context.route("**", ...)`
sobre el `BrowserContext` de Playwright, con allowlist de `file://` y `data:`, detrás de la
variable `TEMPLATE_RENDER_SANDBOX` (default `0`). No cambia nada hoy; el día que entre una
marca de un tercero es una variable de entorno, no un refactor.

Esto importa porque la respuesta a "¿esto lo usa gente fuera de tu equipo?" fue
**"clientes externos pronto"**. La deuda queda declarada y con el interruptor puesto.

## Arquitectura

Cinco abstracciones. Cuatro ya existen.

| Abstracción | Tabla | Qué es | Estado |
|---|---|---|---|
| Marca | `accounts` | El tenant | existe |
| Entidad | `brand_entities` | El sujeto del contenido: banda, propiedad, producto, tema recurrente | nueva |
| Plantilla | `brand_templates` | El look: HTML+CSS + contrato de variables, versionada | nueva |
| Pieza | `content_queue` | Lo que se publica | existe, +5 columnas |
| Job | `jobs` | Ejecución asíncrona con progreso y heartbeat | existe |

### La jugada de reuso central: un lote es un `content_plan`

`content_plans` → `plan_topics` → jobs → `content_queue` ya implementa creación, curación de
temas, curación de piezas, generación en lote, aprobación masiva con asignación de slots, y
tiene UI completa (`frontend/app/b/[slug]/plans/`, `curador-temas.tsx`, `curador-piezas.tsx`).

En vez de construir un segundo sistema de lotes, se le agrega un **despachador de estrategias**
al job `plan.proponer_temas`:

| Estrategia | Fuente de los temas | Estado |
|---|---|---|
| `llm` | DeepSeek propone temas a partir del objetivo del plan | existe (`src/plan_temas.py`) |
| `entidades` | `brand_entities` ordenadas por pesos configurables | nueva — reusa `engagement.score_plan` |
| `agenda` | `events` con fecha próxima o flyer recién detectado | nueva — reusa `src/generate_anuncios.py` |

Los pesos viven en `content_plans.criterio_json`. Los botones que pidió Ricardo
("más tiempo sin publicarse", "mejor engagement", "novedades y agenda") son **presets** de
esos pesos, y los sliders exponen la mezcla cruda.

Consecuencia: cero UI de lotes desde cero, cero segundo camino de aprobación, y el criterio
`engagement` deja de ser CLI-only. Hoy el botón del htmx llama `planner.plan_month()` sin
pasar `criterio`, así que la GUI siempre usa `impacto` (prioridad manual + followers) e
ignora por completo el desempeño real de la cuenta (`web/app.py:638-643`).

## Schema

Todas las migraciones son `ALTER TABLE` idempotentes en el dict `_MIGRATIONS` de `src/db.py`,
siguiendo el patrón existente. Los `CREATE TABLE` van a `src/schema.sql` con `IF NOT EXISTS`.

### Tablas nuevas

```sql
CREATE TABLE IF NOT EXISTS brand_entities (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    tipo          TEXT    NOT NULL,           -- 'banda' | 'propiedad' | 'producto' | 'tema' | libre
    nombre        TEXT    NOT NULL,
    slug          TEXT    NOT NULL,
    prioridad     INTEGER NOT NULL DEFAULT 3, -- 1..5, igual semántica que bands.prioridad
    activa        INTEGER NOT NULL DEFAULT 1,
    atributos_json TEXT,                      -- libre por marca (followers_ig, m2, precio...)
    band_id       INTEGER REFERENCES bands(id) ON DELETE SET NULL,  -- puente gdlscene
    creado_en     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, slug)
);
CREATE INDEX IF NOT EXISTS ix_entities_cuenta ON brand_entities(account_id, activa);
CREATE INDEX IF NOT EXISTS ix_entities_band   ON brand_entities(band_id);

CREATE TABLE IF NOT EXISTS brand_templates (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    slug           TEXT    NOT NULL,
    nombre         TEXT    NOT NULL,
    descripcion    TEXT,
    aspecto        TEXT    NOT NULL DEFAULT '4:5',   -- '4:5' | '9:16'
    contrato_json  TEXT    NOT NULL,
    html           TEXT    NOT NULL,
    estado         TEXT    NOT NULL DEFAULT 'borrador', -- borrador|activa|archivada
    version_actual INTEGER NOT NULL DEFAULT 1,
    origen         TEXT    NOT NULL DEFAULT 'manual',   -- seed|llm|manual
    creado_por     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now')),
    actualizado_en TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, slug),
    CHECK (aspecto IN ('4:5','9:16')),
    CHECK (estado  IN ('borrador','activa','archivada'))
);

-- Es a la vez el historial de versiones y el log del chat de diseño.
CREATE TABLE IF NOT EXISTS template_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id     INTEGER NOT NULL REFERENCES brand_templates(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    mensaje_usuario TEXT,           -- NULL en la v1 de un seed
    html            TEXT NOT NULL,
    contrato_json   TEXT NOT NULL,
    preview_path    TEXT,
    llm_meta        TEXT,           -- modelo, tokens, latencia
    creado_en       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (template_id, version)
);

CREATE TABLE IF NOT EXISTS brand_fonts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    familia    TEXT    NOT NULL,
    archivo    TEXT    NOT NULL,   -- ruta bajo data/brands/<slug>/fonts/
    creado_en  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, familia)
);
```

### Columnas nuevas

```
content_queue  += template_id INTEGER, template_version INTEGER,
                  entity_id INTEGER, campos_json TEXT, aspecto TEXT
content_plans  += estrategia TEXT DEFAULT 'llm', criterio_json TEXT
plan_topics    += entity_id INTEGER
photos         += entity_id INTEGER
```

`content_queue.template` (TEXT) **ya existe** desde el motor de segmentos y guarda el nombre
de la plantilla usada. Se conserva y se llena en paralelo a `template_id` para no romper el
código que ya lo lee; `template_id` es la referencia dura.

### El CHECK de `content_queue.tipo`

`tipo` tiene `CHECK (tipo IN ('meme','anuncio','slideshow'))`. Se agrega `'post'` usando
`_migrar_check_tipo_queue` (`src/db.py:332`), la reconstrucción de tabla que ya existe
para exactamente este caso y que ya está cubierta por `tests/test_db_migracion_tipo_queue.py`.

Se agrega `'post'` en vez de reusar `'meme'` porque "meme" es el nombre equivocado para la
pieza de una inmobiliaria o una cuenta de tips, y la maquinaria de migración ya está pagada.

## Contrato de plantilla

```json
{
  "aspecto": "4:5",
  "base": ["titular", "imagen", "handle", "logo", "color_marca"],
  "extras": [
    {"id": "pasos",  "tipo": "lista", "min": 3, "max": 3,
     "desc": "Tres pasos accionables, máximo 60 caracteres cada uno"},
    {"id": "badge",  "tipo": "texto", "opcional": true, "desc": "Etiqueta superior"}
  ]
}
```

Tipos de campo: `texto`, `texto_largo`, `lista`, `numero`, `imagen`, `booleano`.

El núcleo `base` está garantizado en toda plantilla: el motor siempre lo inyecta, así que
ninguna plantilla puede quedarse sin el logo o el handle de la marca.

`contrato_json` es a la vez **el schema del render y el schema que se le pide a DeepSeek al
generar contenido**. Una sola fuente de verdad: si la plantilla declara tres bullets, el
generador de contenido pide exactamente tres bullets. Ese acoplamiento deliberado es lo que
hace que una plantilla nueva funcione sin tocar el generador.

## Flujo del post simple

```
entidad | tema libre
      ↓
DeepSeek(marca.voz + marca.prompts_json + contrato_json)  →  campos_json
      ↓
imagen: fuentes.orden_imagen(marca) | photos de la entidad | subida manual
      ↓
compose.render_desde_db(html, campos, aspecto)  →  PNG
      ↓
content_queue(tipo='post', template_id, template_version, entity_id, campos_json)
      ↓
portal: editar campo por campo  →  re-render en vivo
      ↓
aprobar  →  scheduler asigna slot  →  publisher DB  →  Instagram
```

La edición manual reusa el patrón exacto de `PUT /brands/{slug}/queue/{qid}/slides`
(`api/routers/cola.py:93`): aplica valores, re-encola el render, no llama al LLM.

Guardar `campos_json` (y no solo el PNG) es lo que permite re-renderizar una pieza con otra
plantilla sin volver a generar el texto.

## Motor de render

`src/compose.py` gana:

```python
def render_desde_db(html: str, contexto: dict, aspecto: str, *, sandbox: bool = False) -> Path
```

Renderiza HTML que viene de la DB en vez de un archivo de `templates/`. Comparte
`_screenshot_card` con el camino actual, incluido el `window.__captionFitted` que espera al
auto-fit del texto antes de capturar.

El dict `TEMPLATES` de `src/compose.py:28-33` se conserva durante toda la rama como camino de
respaldo y para los tests existentes. Se retira en H5, cuando las plantillas de la DB estén
verificadas contra piezas reales.

Dimensiones por aspecto: `4:5 → 1080×1350` (el actual), `9:16 → 1080×1920`.

Fuentes: el contexto recibe `fonts_dir` global más las de `brand_fonts` de la marca. El
diseñador solo puede referirse a familias de ese catálogo; el prompt las recibe enumeradas.

## Diseñador de plantillas con DeepSeek

Job `template.disenar`. Entrada: `(account_id, template_id | None, mensaje_usuario)`.

1. Arma el prompt con: contrato base, catálogo de fuentes disponibles, paleta y logo de la
   marca, ejemplos de plantillas existentes como referencia de estructura, y **solo el HTML
   de la versión anterior** si es una iteración.
2. DeepSeek devuelve `{"nombre", "descripcion", "html", "contrato_json"}`.
3. Se valida: Jinja2 parsea, todo `{{ var }}` está declarado en el contrato, el contrato
   incluye el núcleo base, las familias tipográficas están en el catálogo.
4. Se renderiza un preview con fotos y textos de muestra (reusa `src/estilo_preview.py`).
5. Se inserta `template_versions(version = version_actual + 1)` y se actualiza
   `brand_templates.version_actual`.

**Nunca se manda el historial completo del chat.** Iterar diez veces sobre una plantilla debe
costar diez llamadas de tamaño constante, no diez llamadas cada vez más caras. El historial
está en `template_versions` para que el usuario vuelva a cualquier versión; el LLM solo ve la
última.

Si la validación del paso 3 falla, se reintenta una vez con el error como contexto. Al
segundo fallo el job termina en `error` con el HTML crudo guardado en el log, para poder
inspeccionarlo.

## Estadísticas — `src/stats.py`

| Vista | Fuente | Responde |
|---|---|---|
| Por entidad | generaliza `ig_insights.band_stats` sobre `brand_entities` | ER, alcance, guardados, compartidos, días sin publicar, sugerencia de subir o bajar prioridad |
| Por plantilla | `ig_posts.queue_id → content_queue.template_id` | qué diseño rinde: verde vs blanca vs onion vs las del LLM |
| Por horario | `content_queue.scheduled_datetime` × ER, cruzado con `audience_activity` | a qué hora y qué día publicar |
| Evolución | `ig_metrics_snapshots` | serie semanal de alcance, seguidores y ER de la cuenta |

Las estadísticas por plantilla **no requieren columnas nuevas**: `ig_posts.queue_id` ya apunta
a `content_queue` y `content_queue.template` ya existe y se escribe en `src/send_plan.py:71-73`
y `src/approval.py:251`.

✅ **Cobertura histórica medida el 2026-08-30** (Task 10 de H1, contra
`data/gdlscene.db` con mtime del mismo día, 132 de 132 `ig_posts` ligados):

| | |
|---|---|
| Piezas con `status='publicado'` | 132 |
| Con `template` registrado | 89 (67%) |
| Desglose | `clasica` 58 · `onion` 18 · `verde` 13 · sin dato 43 |
| Primera con dato | 2026-06-12 |

Una medición anterior de esta misma sesión dio 0% de cobertura; fue contra una
copia previa al refresco de ese día y queda descartada.

Consecuencias para el diseño:
- La vista arranca **con histórico usable desde 2026-06-12**, no en cero.
- Las 43 piezas sin plantilla vienen del camino legacy del Sheet. La UI las
  agrupa como "sin dato" en vez de excluirlas en silencio: un promedio sobre
  las 89 presentado como si fuera sobre las 132 mentiría.
- La muestra está desbalanceada (`clasica` es el 65% de lo registrado). La vista
  muestra el **n de cada plantilla junto a su ER**; comparar promedios crudos
  entre una plantilla con 58 posts y otra con 13 es ruido, no señal.
- Hacia adelante el dato es completo: `post.generar` escribe `template_id` y
  `template_version` siempre.

Todas las vistas aceptan `?dias=` y `?orden=` y se ordenan en el servidor.

## API — endpoints nuevos

```
GET    /brands/{slug}/entities
POST   /brands/{slug}/entities
PATCH  /brands/{slug}/entities/{eid}
DELETE /brands/{slug}/entities/{eid}
GET    /brands/{slug}/entities/{eid}          detalle + integrantes + fotos

GET    /brands/{slug}/templates
POST   /brands/{slug}/templates               crea manual o dispara template.disenar
GET    /brands/{slug}/templates/{tid}
PATCH  /brands/{slug}/templates/{tid}         estado, nombre, activar versión
DELETE /brands/{slug}/templates/{tid}
GET    /brands/{slug}/templates/{tid}/versions
POST   /brands/{slug}/templates/{tid}/chat    mensaje → job template.disenar
POST   /brands/{slug}/templates/{tid}/revert  vuelve a una versión
GET    /brands/{slug}/templates/{tid}/preview.png

GET    /brands/{slug}/fonts
POST   /brands/{slug}/fonts
DELETE /brands/{slug}/fonts/{fid}

POST   /brands/{slug}/posts                   crea pieza tipo 'post' (job post.generar)
PUT    /brands/{slug}/queue/{qid}/campos      edita campos_json y re-renderiza

GET    /brands/{slug}/stats/entities
GET    /brands/{slug}/stats/templates
GET    /brands/{slug}/stats/slots
GET    /brands/{slug}/stats/account
POST   /brands/{slug}/stats/sync              dispara ig_insights (job)

GET    /brands/{slug}/events
POST   /brands/{slug}/events
PATCH  /brands/{slug}/events/{evid}
GET    /brands/{slug}/venues
POST   /brands/{slug}/venues/merge
GET    /brands/{slug}/personas
POST   /brands/{slug}/personas/merge
```

`POST /brands/{slug}/plans` gana `estrategia` y `criterio_json` en el body.

Todos pasan por `marca_para(slug, cx, user, minimo)` (`api/deps.py:35`). Mínimos: `editor`
para leer y crear piezas; `manager` para plantillas, entidades, fuentes y horarios.

## Jobs nuevos

| Handler | Qué hace |
|---|---|
| `post.generar` | genera un post simple end-to-end |
| `post.rerender` | re-renderiza con campos editados o con otra plantilla |
| `template.disenar` | itera una plantilla con DeepSeek |
| `template.preview` | renderiza el preview de una versión |
| `stats.sync` | corre `ig_insights` para la marca |

Se registran en el dict `HANDLERS` de `src/jobs/handlers.py:458-468`. El aislamiento por
cuenta de `jobs.tomar()` (una marca no corre dos jobs a la vez) aplica tal cual.

## Portal — páginas

| Ruta | Qué | Reemplaza |
|---|---|---|
| `/b/[slug]` | dashboard: paneles actuales + tarjetas de stats + accesos directos a lotes | — |
| `/b/[slug]/stats` | cuatro pestañas ordenables | `/publicado` |
| `/b/[slug]/templates` | galería, chat de diseño, versiones, preview | — |
| `/b/[slug]/entities` | alta y edición de entidades e integrantes | `/bandas`, `/banda/{id}`, `/members` |
| `/b/[slug]/agenda` | eventos, flyers, fechas | `/calendario`, `/eventos` |
| `/b/[slug]/photos` | banco, caras, personas, venues | `/caras`, `/personas/*`, `/venues` |
| `/b/[slug]/plans` | + selector de estrategia y sliders de mezcla | `/plan` |
| `/b/[slug]/create` | + paso "post simple" con selector de plantilla | — |

Stack existente sin cambios: Next 16 App Router, React 19, Tailwind 4, shadcn (`radix-nova`),
TanStack Query, react-hook-form + zod, dnd-kit, sonner. Un hook por recurso en
`frontend/hooks/`, siguiendo `use-plans.ts` y `use-presets.ts`.

`PRODUCT.md` manda sobre la UI: cero jerga técnica visible, estado visible en cinco segundos,
acciones irreversibles protegidas y explicadas, progressive disclosure, vocabulario
consistente. El chat de plantillas no debe exponer HTML crudo salvo bajo un "ver código".

## Telegram por marca

- Una marca tiene Telegram si hay `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en
  `brand_secrets` o en env con sufijo `__SLUG`. Se expone como interruptor en Settings →
  Conexiones, que ya existe (`tab-conexiones.tsx`, `POST /brands/{slug}/telegram/test`).
- **Bug a corregir**: `src/send_plan.py:74` llama `approval.enviar_a_telegram(...)` sin `cx`,
  así que `tg_chat_id` y `tg_message_id` quedan NULL para todo lo mandado por el flujo de
  lotes. Consecuencia hoy: aprobar o rechazar desde el portal no puede editar la tarjeta
  original de Telegram y `approval.notificar_resolucion` falla en silencio
  (`src/approval.py:407-409`). Con ambos caminos activos eso produce estados divergentes:
  la pieza aprobada en el portal sigue mostrando sus botones en Telegram.
- Se pasa `cx` y se agrega un test que verifica que las dos columnas quedan pobladas.

## Hitos

| # | Hito | Terminado cuando |
|---|---|---|
| H1 | Schema, migraciones y seeds | tests verdes; `bands` de gdlscene sembradas como entidades; las 4 plantillas HTML en `brand_templates` con su v1; prod intacto |
| H2 | Post simple end-to-end | se genera, edita, aprueba y publica un post de gdlscene **y** uno de melaquecapital desde el portal |
| H3 | Diseñador con DeepSeek | se crea una plantilla de inmobiliaria hablándole, se itera tres veces y se vuelve a la v2 |
| H4 | Lotes por estrategia + Telegram por marca | el lote del mes se arma desde la UI con sliders, sin CLI y sin pedírselo a un agente; `tg_message_id` poblado |
| H5 | Estadísticas y port del htmx | las 13 vistas viven en el portal; `web/app.py` se puede apagar; `TEMPLATES` retirado |

Cada hito cierra con tests verdes y migración idempotente verificada corriendo `init_db` dos
veces, para que una rama estancada nunca deje la DB a medias.

## Riesgos

1. **`web/app.py` es mono-marca y sin auth.** Cada query asume `account_id = 1`. Portarlo es
   reescribir, no copiar. H5 es el hito más caro de los cinco y el más fácil de subestimar.
2. **`photos` no tiene `account_id`**, hereda vía `band_id`. El backfill de `photos.entity_id`
   tiene que preservar las filas ya ligadas; se verifica por conteo antes y después.
3. **Rama larga.** Fue decisión explícita. Se mitiga con los cinco hitos y la regla de tests
   verdes por hito, no con merges parciales.
4. **Producción.** Nada toca la VM sin aprobación explícita en el momento. Las migraciones se
   prueban contra una copia de `/opt/instagod/data/gdlscene.db` antes de tocar la real, y se
   deja backup con fecha como en el precedente de `gdlscene.db.bak-20260829-0831`.
5. **HTML del LLM sin sandbox.** Decisión 11. El interruptor queda implementado y apagado.
6. **Muestra desbalanceada de plantillas.** Medido: 89 de 132 piezas publicadas
   registran plantilla, y `clasica` es el 65% de esas. Comparar ER promedio entre
   plantillas con n muy distinto induce a error; la vista muestra el n al lado.
7. **Cuotas de LLM.** "Clientes externos pronto" implica que el diseñador de plantillas es un
   vector de gasto por marca. No se implementan cuotas en esta rama; queda anotado como lo
   primero a agregar antes de dar de alta una marca de un tercero.

## Fuera de alcance

- Carruseles y slideshows: no se tocan, siguen por su camino actual.
- Reels y video.
- Formato 1:1.
- Cuotas de generación y aislamiento duro de archivos entre marcas.
- Onboarding self-service de marcas nuevas.
- Retirar el Sheet legacy de GitHub Actions (ya deshabilitado el 2026-08-28).

## Verificación

- Migraciones: `init_db` dos veces sobre `tmp_path`, patrón de `tests/test_motor_migraciones.py`.
- Render: smoke con Playwright real (existe y pesa >10 KB), patrón de `tests/test_slide_render.py`.
  Además, validación de contrato sin Chromium para la salida del LLM.
- Estrategias de lote: unitarias sobre la selección con DB sembrada, sin red ni LLM.
- Estadísticas: fixtures de `ig_posts` con métricas conocidas y aserción sobre los agregados.
- Telegram: test de que `send_plan` puebla `tg_chat_id` y `tg_message_id`.
- Endpoints: cliente de prueba de FastAPI con usuarios de distintos roles, verificando 403.
