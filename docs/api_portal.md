# API del portal (Fase 1)

Correr: `.venv/bin/uvicorn api.app:app --port 8100 --reload` → docs en `/docs`.

Primer uso:
1. `python -m api.bootstrap --nueva-master-key` → pegar en `.env` como `INSTAGOD_MASTER_KEY`.
2. `python -m api.bootstrap --admin tu@email.com` → abre la URL impresa (crea la sesión).
3. `python -m api.bootstrap --importar-env` → copia `KEY__SLUG` del `.env` a `brand_secrets`.

Endpoints: `POST /auth/magic-link`, `GET /auth/callback`, `POST /auth/logout`, `GET /auth/verify`,
`GET /me`, `GET/POST /users...` (admin), `GET/POST /brands`, `GET/PATCH /brands/{slug}`,
`GET/PUT/DELETE /brands/{slug}/secrets[/{clave}]`, `POST /brands/{slug}/{telegram|instagram|llm}/test`,
`GET /health`. Errores: `{error, detalle, campo}`.

Precedencia de credenciales por marca: DB (`brand_secrets`) → `.env` con sufijo `__SLUG` →
`.env` global (solo gdlscene). El daemon detecta cambios de token/chat cada 60 s.

## Despliegue y operación

- **Dominios**: `API_URL`, `APP_URL` y `COOKIE_DOMAIN` deben compartir dominio registrable
  (ej. `api.midominio.com` / `app.midominio.com` / `COOKIE_DOMAIN=.midominio.com`). La cookie de
  sesión usa `SameSite=Lax` y el CORS solo permite `APP_URL`; un dominio distinto no puede
  mandar la cookie ni leer la respuesta.
- **Detrás de Caddy**: correr uvicorn con `--proxy-headers --forwarded-allow-ips=<ip de caddy>`
  para que tome la IP real del cliente desde `X-Forwarded-For` — si no, el rate limit de magic
  links (5/hora por email y por IP) ve siempre la IP del proxy y bloquea a todos los usuarios
  detrás de él.
- **`INSTAGOD_MASTER_KEY`**: respáldala fuera del `.env` (gestor de secretos, vault, etc.). Sin
  ella los secretos guardados en `brand_secrets` son irrecuperables (Fernet no tiene modo de
  recuperación).
- **Ventana de recarga del daemon**: revisa cambios de token/chat cada 60 s; al recargar,
  arranca el polling con `drop_pending_updates=True`. Un botón de aprobación tocado justo en esa
  ventana (entre que cambió la credencial y que el daemon recargó) se pierde y hay que
  reintentarlo manualmente.
- **Importar/actualizar tokens de IG en DB**: `python -m api.bootstrap --importar-env` mueve
  también `IG_ACCESS_TOKEN` a `brand_secrets` (junto con el resto de `CLAVES`). Una vez ahí, el
  refresh semanal de `src/ig_token.py` lo mantiene sincronizado: lo actualiza en DB y en `.env`.

## Cola, jobs y publisher (Fase 2)

### Endpoints de cola y jobs

- `GET /brands/{slug}/queue` — lista de filas de la marca (estados de fila, ver abajo).
- `GET /brands/{slug}/queue/{qid}` — detalle de una fila (caption, medios, estado, timestamps).
- `PATCH /brands/{slug}/queue/{qid}` — editar `caption` y/o `scheduled_datetime` (reprograma) de una fila. `scheduled_datetime` acepta estado pendiente/programado/error (error es la vía para revivir una fila atorada por el publisher); `caption` solo pendiente/programado.
- `DELETE /brands/{slug}/queue/{qid}` — descartar una fila.
- `POST /brands/{slug}/queue/{qid}/aprobar` — aprobar y pasar a estado programado.
- `POST /brands/{slug}/queue/{qid}/rechazar` — rechazar (terminal).
- `POST /brands/{slug}/queue/{qid}/regenerar` — descartar fila vieja y crear una nueva (retorna nuevo `job_id` para seguimiento).
- `GET /brands/{slug}/slots/proximos?n=5` — próximos `n` slots libres de la marca, en la TZ de la marca (no UTC). `n` entre 1 y 50.
- `POST /brands/{slug}/slideshows` — crear slideshow; retorna `202 {job_id}` (use polling en `/jobs/{jid}`).
- `GET /brands/{slug}/jobs[?estado=cola|corriendo|ok|error|cancelado]` — lista de jobs; filtro opcional por estado.
- `GET /brands/{slug}/jobs/{jid}` — detalle de un job (progreso, errores, queue_id asociado).
- `POST /brands/{slug}/jobs/{jid}/cancel` — cancela el job solo si sigue en estado `cola` (uno ya `corriendo` no se puede cancelar a medias).

### Estados de la cola

Los estados de **FILA** (`content_queue`, columna derivada `estado` que ve el portal, `src/cola.py::estado_de`) son:
- `generando` — el worker está procesando (EXCLUSIVO del flujo API: `origen='api'`).
- `borrador` — fila legacy (plan mensual u otro generador viejo, `origen != 'api'`) todavía sin aprobación. Visible en el portal pero **no** aprobable desde ahí (la compuerta de aprobar/rechazar exige `pendiente`).
- `pendiente` — espera aprobación humana (botones en Telegram y portal).
- `programado` — aprobado, esperando slot.
- `publicado` — ya se publicó.
- `rechazado` — rechazado por humano (terminal).
- `error` — fallo durante worker o publisher; visible en portal para reprogramar.
- `descartado` — descartado por humano o regeneración.

Los estados de **JOB** (`jobs`, columna cruda `estado`) son otro vocabulario, no lo de arriba: `cola` (esperando worker), `corriendo`, `ok`, `error`, `cancelado`.

### Procesos worker y publisher

**Worker (procesa slideshows):**
```bash
python -m src.jobs.worker          # Corre en loop infinito
python -m src.jobs.worker --once   # Una sola pasada
```
Variables de entorno:
- `WORKER_MAX_JOBS` (default 2) — máximo de jobs en paralelo globalmente.
- Garantía: máximo 1 job por marca a la vez; huérfanos >30 min sin ping vuelven a cola una vez.

**Publisher (publica slideshows):**
```bash
python -m src.publisher            # Corre en loop infinito
python -m src.publisher --once     # Una sola pasada
```
Variables de entorno:
- `PUBLISH_EVERY` (default 300 s) — intervalo entre ciclos de publicación.
- Garantía at-most-once: marca publicada con error='[publicando]'; si muere ahí, fila queda visible en estado `error` y se revive reprogramándola desde la API. Tras 5 intentos fallidos deja de reintentar; `PATCH` resetea el contador.
- Correr **UNA sola instancia** del publisher (el claim atómico del marcador evita duplicados si por accidente hay dos, pero no es un modo soportado).

### Regla de publicación por SHEET_ID

- **Marca CON `SHEET_ID` definido**: publica automáticamente por Google Sheets / GitHub Actions. El publisher DB la salta.
- **Marca SIN `SHEET_ID`**: publica el publisher DB desde la cola en la base de datos.
- **Garantía**: un único publicador por marca activo a la vez.
- **Marcas con Sheet**: la fila queda en estado `programado` hasta que corre `sync_sheet` (que la refleja como `en_sheet`) — Actions publica igual aunque el portal todavía la muestre `programado`, no es un bug.
- **Cuidado al activar `SHEET_ID` en una marca que ya tiene filas en `programado`** (publisher DB): esas filas quedan huérfanas — ningún lado las toma (el publisher DB las salta porque la marca ya tiene Sheet; nunca se escribieron al Sheet). Re-apruébalas (para que tomen el camino `en_sheet`) o quita el `SHEET_ID` de nuevo.
- En una marca **sin Sheet**, un `anuncio` aprobado no sale instantáneo: lo toma el publisher DB en su siguiente ciclo (hasta `PUBLISH_EVERY` segundos después), no al momento de aprobar.

### Regenerar vs descartar

Al regenerar (`POST .../queue/{qid}/regenerar`), se descarta la fila vieja y se crea un nuevo job. Para seguir el progreso del nuevo slideshow, usar el `job_id` retornado:
```bash
GET /brands/{slug}/jobs/{nuevo_job_id}  # Pollear este job
```

### Convergencia de aprobaciones

Front (portal) y Telegram convergen: al aprobar o rechazar desde el portal, el bot quita los botones del mensaje de Telegram y responde en el hilo original, evitando desincronización.

## Perfil creativo y fuentes (Fase 3)

### Prompts (voz + hashtags + brief por formato)

- `GET /brands/{slug}/prompts` — `{voz, caption_extra, por_formato, hashtags}`.
- `PUT /brands/{slug}/prompts` — actualiza los cuatro campos (manager+). `por_formato` solo
  acepta formatos habilitados en la marca (`accounts.formatos`); `hashtags` cada uno debe
  empezar con `#`, máximo 30.
- `POST /brands/{slug}/prompts/probar` — genera un guion de prueba (`{tema, formato?}`) con la
  voz/prompt guardados, sin encolar nada en `content_queue` (llamada directa a
  `slideshow_script.generar_guion`, sincrónica). Falla del LLM → `502 prueba_fallida` con el
  detalle redactado (nunca expone `LLM_API_KEY`).

### Presets de estilo (con preview)

- `GET /brands/{slug}/presets` — catálogo completo visible por la marca (propios + los base del
  código), cada uno con `propio: bool`.
- `PUT /brands/{slug}/presets/{nombre}` — crea/sobreescribe un preset propio (manager+). `nombre`
  minúsculas/dígitos/guion bajo (2-32); body requiere `texto` y `roles` (dict no vacío); máximo
  32 KB serializado.
- `DELETE /brands/{slug}/presets/{nombre}` — borra un preset propio (404 si no es propio de la
  marca, aunque exista uno base con ese nombre — los presets base del código no se pueden
  borrar).
- `POST /brands/{slug}/presets/{nombre}/preview` — encola un job `preset.preview` (`202
  {job_id}`, mismo patrón de polling que slideshows); genera un PNG de muestra servido luego en
  `GET /brands/{slug}/files/previews/{nombre}.png`.

### Logo

- `POST /brands/{slug}/logo` — multipart, un archivo (manager+). Extensiones `png/svg/jpg/jpeg`,
  máx 2 MB; SVG con `<script>` se rechaza (422, riesgo XSS). Reemplaza cualquier `logo.*`
  anterior de la marca y actualiza `accounts.logo_path`.
- `GET /brands/{slug}/files/logo` — sirve el logo actual. SVG se fuerza como descarga
  (`Content-Disposition: attachment`) con `Content-Security-Policy: default-src 'none'`; los
  rasterizados van inline con `X-Content-Type-Options: nosniff`.

### Campos extra de marca

`PATCH /brands/{slug}` (ya existente, Fase 1) ahora también acepta `descripcion` (≤600),
`sitio_web` (≤200) y `hashtags_default` (≤400) — igual de opcionales que el resto de campos del
PATCH, requieren manager+.

### Fuentes de contenido (`brand_sources`)

Dos `kind`: `imagen` (cascada de proveedores para las fotos del slideshow) e `info` (temas
sugeridos). Aislamiento estricto por `account_id`: una fuente ajena a la marca da 404 en
`GET/PATCH/DELETE`.

- `GET /brands/{slug}/sources[?kind=imagen|info]`
- `POST /brands/{slug}/sources` — `{kind, provider, config?, activa?}` (manager+). `provider` debe
  existir para ese `kind`; `ig_accounts`/`rss`/`newsapi` tienen esquema de `config` obligatorio
  (ver abajo), el resto acepta `config` libre u omitido.
- `PATCH /brands/{slug}/sources/{sid}` — `{config?, activa?}` (manager+).
- `DELETE /brands/{slug}/sources/{sid}` (manager+).
- `PUT /brands/{slug}/sources/orden` — `{ids: [...]}`, reordena la cascada de un `kind`; debe ser
  exactamente el set de ids existentes de ese `kind` para esa marca, sin repetir (422 si no).
- `POST /brands/{slug}/sources/{sid}/run` — encola el job de esa fuente (`202 {job_id}`). Solo
  fuentes "ejecutables" (`rss`→`sourcing.rss_fetch`, `newsapi`→`sourcing.newsapi_fetch`,
  `ig_accounts`→`sourcing.ig_scrape`); el resto de providers son estáticos y responden 422.

**Providers de imagen** (`kind=imagen`): `carpeta`, `ig_accounts`, `pinterest`, `pexels`,
`unsplash`, `banco`, `covers`. Sin fuentes propias configuradas, `generate_slideshow.generar` cae
al `fuentes_imagen` legacy del perfil de marca (compat con marcas de antes de esta fase).

**Providers de info** (`kind=info`, alimentan `topic_suggestions`): `rss`, `newsapi`.

**Esquemas de `config` obligatorios:**
- `ig_accounts`: `{"cuentas": ["@handle", ...]}` (no vacío, cada uno con `@`); opcional
  `max_por_cuenta` (entero 1-50) y `cada_horas` (entero ≥6, sin efecto real porque este provider
  no entra al scheduler automático — ver abajo).
- `rss`: `{"urls": ["http...", ...]}` (no vacío, cada URL empieza con `http`).
- `newsapi`: `{"query": "..."}` (no vacía); opcional `idioma`, `pais` (strings).

**Claves por marca (vía `brand_secrets`, nunca en `config`):** `PEXELS_API_KEY`,
`UNSPLASH_ACCESS_KEY`, `NEWSAPI_KEY` — se guardan con `PUT /brands/{slug}/secrets/{clave}` y las
resuelve `config.account_creds(slug)` (DB → `.env` con sufijo `__SLUG` → global). Sin
`UNSPLASH_ACCESS_KEY` ese provider se omite sin llamar a la red; Pexels sin clave por marca cae a
la clave global del proceso.

### `encolar_fuentes_vencidas` (scheduler de fuentes de info)

`src/jobs/worker.py::encolar_fuentes_vencidas` corre en **cada vuelta del loop del worker**
(`python -m src.jobs.worker`), antes de tomar el siguiente job. Revisa las fuentes `kind='info'`
**activas** (solo `rss`/`newsapi` — `ig_accounts` NO entra aquí, se corre manual vía
`POST .../sources/{sid}/run`) y encola `sourcing.rss_fetch`/`sourcing.newsapi_fetch` para las que
ya vencieron: `config.cada_horas` (default 24 h) desde `ultimo_run`, o de inmediato si nunca
corrió. Dedup: si ya hay un job `cola`/`corriendo` para ese `source_id`, no encola otro.

### Fotos (banco propio de marca)

El **banco de fotos de una marca** es la carpeta `data/brands/{slug}/fotos/` — el provider
`carpeta` (`CarpetaProvider`) lee de ahí directo, sin pasar por `brand_sources`.

- `GET /brands/{slug}/photos` — lista `{nombre, tamano, mtime, url}` de la carpeta.
- `POST /brands/{slug}/photos` — multipart, hasta 10 archivos por request (manager+). Extensiones
  `jpg/jpeg/png/webp`, máx 8 MB c/u; se valida TODO el lote antes de escribir cualquier archivo
  (una foto inválida no deja fotos previas a medio guardar). El nombre en disco se **regenera
  server-side** (`uuid4().hex[:12]` + extensión) — el nombre del cliente nunca toca el
  filesystem.
- `DELETE /brands/{slug}/photos/{nombre}` (manager+).
- `GET /brands/{slug}/files/fotos/{nombre}` — sirve el archivo (autenticado, vía `marca_para`).

### Temas sugeridos (`topic_suggestions`)

- `GET /brands/{slug}/topics[?usados=false]` — bandeja de la marca: descartados siempre fuera;
  usados (`usado_en_queue_id` no nulo) fuera salvo `usados=true`.
- `POST /brands/{slug}/topics/{tid}/descartar` (manager+) — descarte terminal (`descartado=1`);
  un tema ajeno a la marca da 404.

**De tema a slideshow:** `POST /brands/{slug}/slideshows` acepta `topic_id` opcional junto al
resto del body ya existente (`tema` deja de ser obligatorio cuando se manda `topic_id`). Reglas:
- El topic debe pertenecer a la marca (404 si no) y no estar descartado (422 si sí).
- Si no se manda `tema`, se usa el `titulo` del topic; si no se manda `contexto`, se arma como
  `f"{resumen}\n{url}"`.
- Sin `topic_id` ni `tema`, 422.
- El payload del job incluye `topic_id` cuando se dio; `src/jobs/handlers.py::generar_slideshow`
  lo pasa a `generate_slideshow.generar(..., topic_id=...)`, que marca
  `topic_suggestions.usado_en_queue_id` al encolar el slideshow (tolerante si el topic ya no
  existe para entonces).
