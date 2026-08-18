# Portal de colaboradores: API JSON + frontend Next — diseño

**Fecha:** 2026-08-17
**Estado:** aprobado por Ricardo (brainstorm 2026-08-17)
**Contexto:** sub-proyecto 3 del roadmap "instagod → producto". El spec
multi-marca (2026-08-10) dejó fuera "portal multi-usuario, auth y edición de
secretos desde la GUI"; este spec lo cubre. instagod deja de ser una
herramienta local de Ricardo y pasa a ser un backend hospedado (Docker en un
servidor Linux ajeno) con un frontend en Next desde el que colaboradores
administran sus marcas y crean carruseles.

## Objetivo

- Ricardo (admin) invita colaboradores por email y les asigna marcas y rol.
- Un colaborador, desde el front, puede: ver un calendario estilo Buffer de lo
  que se publicará, crear carruseles (slideshows) con un wizard, aprobar /
  rechazar / reprogramar, y (según rol) configurar su marca: perfil, voz y
  prompts, presets de estilo (editor visual con preview), fuentes de imagen e
  información, bot de Telegram, credenciales (IG, LLM, APIs de imágenes) y
  horarios.
- instagod es solo backend: la GUI HTMX actual queda como `/legacy` admin-only.

**Criterio de éxito (E2E):** el compose corre en el servidor; Ricardo entra
con magic link, crea la marca "X", invita a `colab@x.com` como manager;
el colaborador entra, configura Telegram + IG + LLM, sube logo, ajusta un
preset con preview, agrega Unsplash + un RSS como fuentes, genera un carrusel
desde un tema sugerido, lo aprueba en el front (el bot de Telegram refleja la
aprobación), lo ve en el calendario en su slot, y el publisher lo publica en
el IG de "X" sin tocar ni las creds ni la cola de gdlscene.

## Decisiones tomadas en el brainstorm

| Tema | Decisión |
|---|---|
| Hosting | Backend contenerizado (docker-compose) en servidor Linux de un amigo de Ricardo; él instala siguiendo `docs/deploy.md`. |
| Auth | Invitación por email + magic link (Resend). Sesión en cookie httpOnly. |
| Alcance de contenido v1 | Solo carruseles/slideshows para colaboradores. Memes/agenda/anuncios/releases siguen siendo flujo gdlscene por `/legacy`. |
| Cola de publicación | `content_queue` en SQLite es la fuente de verdad. Google Sheet pasa a espejo opcional (solo si la marca tiene `SHEET_ID`). |
| Aprobación | Front y Telegram, ambos válidos, mismo estado en DB. |
| Plantillas | Editor visual de presets (`estilos_json`) con preview renderizado por el back. Sin editar HTML crudo. |
| Fuentes | Dos tipos por marca: **imagen** (banco propio: subida + scrape de cuentas IG de referencia, Pinterest, Pexels, Unsplash nuevo) e **información** (RSS y NewsAPI → temas sugeridos). X/Twitter fuera de v1. |
| Front | `frontend/` en el monorepo, Next 16 App Router, desplegado en Vercel, hablando con la API vía `rewrites`. |
| DB | SQLite se queda (WAL, volumen Docker). Sin migrar a Postgres. |
| Enfoque | A: API JSON nueva (`api/`) sobre `src/`. Descartados: extender HTMX (no cumple UX/Next), Next full-stack con DB propia (duplica modelo). |

## Recursos del servidor (medidos 2026-08-17)

Daemon 25 MB idle; API ~90 MB; publisher ~70 MB; worker en render
~550 MB pico (Chromium headless 385 MB medido); pipeline fotos gdlscene
(OpenCV + OCR onnxruntime) +400–600 MB. `data/` pesa 3.6 GB (3.5 GB fotos);
imagen Docker ~2 GB.

- **Mínimo:** 2 vCPU, 4 GB RAM, 25 GB disco, Docker + Compose, dominio con
  80/443 abiertos, salida a internet libre, IP fija de preferencia.
- **Cómodo:** 4 vCPU, 8 GB, 50 GB SSD.
- El compose fija `mem_limit` por servicio y el worker corre 1 job por marca
  y `WORKER_MAX_JOBS` global (default 2).

---

## Parte 1 — Backend y datos

### 1. Estructura y despliegue

- Paquete nuevo `api/`: `app.py` (factory, CORS mínimo, rate limit por IP en
  auth), `auth.py` (magic link, sesiones, cookies), `deps.py` (sesión → user →
  permiso por marca), `errors.py` (JSON uniforme), `bootstrap.py` (CLI: crear
  admin, importar secretos de `.env` a DB), `routers/{auth,users,brands,
  secrets,prompts,presets,sources,photos,queue,slideshows,jobs,telegram,
  system}.py`. Routers delgados: la lógica vive en `src/`.
- Módulos nuevos en `src/`: `users.py`, `secrets_store.py`, `jobs/` (modelo,
  worker, handlers), `sources.py` (brand_sources + runners), `topics.py`
  (temas sugeridos), `image_sources.py` gana `UnsplashProvider` y
  `BancoMarcaProvider`, `publisher.py` (loop que reemplaza a Actions).
- `web/` (HTMX de curación gdlscene) se monta en `/legacy` detrás de un
  middleware que exige sesión admin. Sin reescribirlo.
- `Dockerfile` único (Python 3.12 slim + Chromium de Playwright + OpenCV +
  onnxruntime + fuentes), `docker-compose.yml` con servicios `api`, `worker`,
  `daemon`, `publisher`, `caddy`; volumen `data/` (SQLite + fotos + sourcing +
  previews + brands). `Caddyfile`, `.env.server.example`, `docs/deploy.md`.
- Variables del servidor: `INSTAGOD_MASTER_KEY`, `APP_URL` (front),
  `API_URL`, `RESEND_API_KEY` + `MAIL_FROM`, `SESSION_DAYS` (30),
  `WORKER_MAX_JOBS`, más las globales existentes (Cloudinary, DeepSeek default,
  etc.).

### 2. Usuarios y permisos

Tablas nuevas (vía `db._MIGRATIONS`, idempotente):

- `users(id, email UNIQUE, nombre, is_admin, activo, created_at, last_login)`
- `brand_members(user_id, account_id, rol, PRIMARY KEY(user_id, account_id))`,
  `rol ∈ {manager, editor}`
- `magic_links(token_hash, user_id, expira, usado_at)` — TTL 15 min, un uso
- `sessions(token_hash, user_id, expira, created_at, ua)`

Roles:

- **admin** (`users.is_admin`): todo en todas las marcas; gestiona usuarios,
  invitaciones, `/legacy`, `/admin/system`.
- **manager**: configuración completa de sus marcas (perfil, prompts, presets,
  fuentes, Telegram, credenciales, horarios) + contenido.
- **editor**: solo contenido de sus marcas (crear, aprobar, rechazar,
  reprogramar, editar caption, ver calendario/library) y lectura de Perfil y
  Estilos.

Flujo: admin `POST /users/invite {email, nombre, marcas:[{slug, rol}]}` →
se crea el user + magic link → correo (Resend; en `ENV=dev` se loguea la URL)
→ `GET /auth/callback?token=` valida, marca usado, crea sesión, setea cookie
`instagod_session` (httpOnly, Secure, SameSite=Lax, 30 días), redirige a
`APP_URL`. `POST /auth/magic-link {email}` responde 200 siempre (no revela si
existe). `POST /auth/logout`, `GET /me` (user + marcas + rol por marca).
Admin puede `PATCH /users/{id}` (marcas/rol/activo) y `DELETE` sesiones.

### 3. Secretos por marca

- Tabla `brand_secrets(account_id, clave, valor_cifrado, updated_by,
  updated_at, PRIMARY KEY(account_id, clave))`. Cifrado Fernet con
  `INSTAGOD_MASTER_KEY`. Nunca se loguea el valor.
- Claves permitidas (`src/secrets_store.CLAVES`): `IG_USER_ID`,
  `IG_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `LLM_PROVIDER`,
  `LLM_API_KEY`, `LLM_MODEL`, `PEXELS_API_KEY`, `UNSPLASH_ACCESS_KEY`,
  `NEWSAPI_KEY`, `SHEET_ID` (opcional, espejo legacy).
- `config.account_creds(slug)` resuelve **DB → env con sufijo `__SLUG` → env
  global (solo gdlscene)**. El resto del código (`approval`, `publish`,
  `approval_daemon`, `slideshow_script`) no cambia de firma. `caption`/
  `slideshow_script` usan `LLM_PROVIDER/LLM_API_KEY/LLM_MODEL` de la marca si
  existen; si no, el global.
- API: `GET /brands/{slug}/secrets` → `[{clave, configurada, ultimos4,
  updated_at}]`; `PUT /brands/{slug}/secrets/{clave}` (manager+); `DELETE`.
  Pruebas: `POST /brands/{slug}/telegram/test` (manda "instagod conectado" al
  chat), `POST /brands/{slug}/instagram/test` (`GET /me` al Graph, devuelve
  username), `POST /brands/{slug}/llm/test` (completion de 5 tokens).
- El daemon relee `brand_secrets` cada 60 s (`updated_at` máximo por marca):
  token nuevo → levanta Application; token borrado → la baja; sin reinicio.
- `python -m api.bootstrap --importar-env` copia los `KEY__SLUG` y los de
  gdlscene del `.env` a `brand_secrets` (migración única).

### 4. Cola como fuente de verdad

- `content_queue` gana `publicado_en`, `error`, `creado_por`, `aprobado_por`,
  `ig_media_id`, `origen` (`api|legacy|telegram`). Estados que expone la API
  (derivados de `status` + `aprobacion`): `generando`, `pendiente`,
  `programado`, `publicado`, `rechazado`, `error`, `descartado`.
- `approval.aprobar(qid, user_id=None)`: ya no exige Sheet. Asigna slot con
  `scheduler.next_free_slot` leyendo `content_queue` de la marca (slots
  ocupados = filas `programado` de la misma `account_id`), marca
  `status='programado'`, `aprobacion='aprobado'`, `aprobado_por`. Si la marca
  tiene `SHEET_ID`, escribe también el Sheet (espejo; error del Sheet no
  bloquea, se registra en `error`). Front y Telegram llaman la misma función;
  al aprobar desde el front, el bot edita su mensaje ("✅ aprobado por
  <nombre> desde el portal") si el mensaje existe.
- `src/publisher.py`: loop cada `PUBLISH_EVERY` (300 s) → por marca activa:
  `SELECT … WHERE status='programado' AND aprobacion='aprobado' AND
  scheduled_datetime <= now` → `publish_row` con `account_creds(slug)` →
  `publicado` (+`ig_media_id`, `publicado_en`) o `error`. Reutiliza
  `publish.publish_row`. `publish.py` (Actions) queda como respaldo opcional
  para gdlscene mientras siga con Sheet; se documenta cómo apagarlo.
- Endpoints: `GET /brands/{slug}/queue?desde&hasta&estado`, `GET /queue/{id}`
  (slides, caption, guion, imágenes, job), `PATCH /queue/{id}` (`caption`,
  `scheduled_datetime` con 409 si choca con otra fila `programado` de la
  marca), `POST /queue/{id}/aprobar|rechazar|regenerar` (regenerar = job),
  `DELETE /queue/{id}` (solo `pendiente|rechazado|error`),
  `GET /brands/{slug}/slots/proximos?n=` (siguientes slots libres).

### 5. Jobs

- Tabla `jobs(id, tipo, account_id, payload_json, estado ∈ {cola, corriendo,
  ok, error, cancelado}, progreso (0-100), log TEXT, resultado_json,
  creado_por, created_at, started_at, finished_at, worker_id)`.
- Worker `python -m src.jobs.worker`: loop que toma jobs `cola` con
  `UPDATE … WHERE estado='cola' RETURNING` (atómico en SQLite), máximo 1
  corriendo por `account_id` y `WORKER_MAX_JOBS` en total; heartbeat en
  `daemon_health` estilo daemon; jobs `corriendo` huérfanos (>30 min sin
  heartbeat) vuelven a `cola` una vez y luego `error`.
- Handlers v1: `slideshow.generar` (envuelve `generate_slideshow.generar`
  con callback de progreso: guion 20 % → sourcing 50 % → render 80 % → subida
  100 %; deja la fila en `content_queue` `pendiente` y manda a Telegram),
  `slideshow.regenerar`, `sourcing.ig_scrape`, `sourcing.rss_fetch`,
  `sourcing.newsapi_fetch`, `preset.preview`.
- API: `POST /brands/{slug}/slideshows {tema, contexto?, formato, estilo,
  fuentes[], n_slides, topic_id?}` → 202 `{job_id, queue_id}`;
  `GET /jobs/{id}`; `GET /brands/{slug}/jobs?estado`; `POST /jobs/{id}/cancel`
  (solo `cola`). Front hace polling cada 2 s.

### 6. Marca: perfil, prompts, presets

- `accounts` gana `descripcion`, `sitio_web`, `hashtags_default`,
  `prompts_json`. Se conservan `voz`, `estilos_json`, `formatos`,
  `posting_slots`, `logo_path`, `fuentes_imagen` (esta última se sigue
  leyendo si la marca no tiene filas en `brand_sources`, para no romper
  gdlscene/pensionmas hasta migrarlas).
- **Prompts** = `voz` (system prompt) + `prompts_json` =
  `{caption_extra: str, por_formato: {listicle: str, libre: str, …},
  hashtags: [str]}`. `slideshow_script` concatena `voz` + `por_formato[f]` +
  `contexto`. `POST /brands/{slug}/prompts/probar {tema, formato}` genera solo
  el guion (sin render) para iterar prompts.
- **Presets** (`estilos_json`) con esquema Pydantic validado
  (`src/slideshow_model.PresetEstilo`): paleta (bg, fg, acento, overlay),
  fuentes (de `config.SLIDESHOW_FUENTES` + woff2 de la marca en
  `data/brands/<slug>/fonts/`), `overlay_opacity`, zonas de texto, `chrome`
  (`handle`, `logo`, `posicion`). `GET/PUT/DELETE /brands/{slug}/presets/
  {nombre}`, `POST /brands/{slug}/presets/{nombre}/preview {texto?}` → job
  `preset.preview` que renderiza 1 slide con texto de muestra a
  `data/previews/<slug>/<nombre>-<hash>.png`; `GET /files/previews/...` lo
  sirve. `POST /brands/{slug}/logo` y `POST /brands/{slug}/fonts` (multipart,
  límite 2 MB, solo png/svg y woff2/ttf).
- CRUD marca: `GET /brands` (admin: todas; otros: las suyas con rol),
  `POST /brands` (admin), `GET/PATCH /brands/{slug}`, `PUT /brands/{slug}/slots
  {posting_slots, timezone, posts_por_dia}`.

### 7. Fuentes de imagen e información

- Tabla `brand_sources(id, account_id, kind ∈ {imagen, info}, provider,
  config_json, activa, orden, ultimo_run, ultimo_error, created_at)`.
- **Imagen** (`resolver` recibe la lista ordenada de providers activos de la
  marca; reemplaza `fuentes_imagen`):
  - `banco`: `BancoMarcaProvider` — fotos con `photos.account_id` = marca
    (subidas por `POST /brands/{slug}/photos` multipart o scrapeadas).
    `GET /brands/{slug}/photos?origen&pagina`, `DELETE /photos/{id}`.
  - `ig_accounts`: `config {cuentas: ["@a","@b"], max_por_cuenta: 30,
    cada_horas: 24}` → job `sourcing.ig_scrape` (reusa `ingest_ig` con la
    sesión de scraper global; guarda en `photos` con `account_id` de la marca
    y `origen='ig:@a'`). Un scheduler ligero dentro del worker encola los
    jobs periódicos por `cada_horas`.
  - `pinterest` (existente, `config {query_extra}`), `pexels` (existente,
    key de la marca o global), `unsplash` (**nuevo**, API oficial
    `/search/photos`, atribución guardada en `ImagenCandidata.credito`).
- **Info**: `rss {urls: [...]}` y `newsapi {query, idioma, pais}` → jobs
  periódicos que llenan `topic_suggestions(id, account_id, titulo, resumen,
  url, fuente, publicado_en, usado_en_queue_id, created_at)` (dedup por url).
  `GET /brands/{slug}/topics?usados=0`, `POST /brands/{slug}/topics/{id}/
  descartar`. Un topic se convierte en brief del wizard (`tema` = titulo,
  `contexto` = resumen + url).
- `GET/POST /brands/{slug}/sources`, `PATCH/DELETE /brands/{slug}/sources/
  {id}`, `PUT /brands/{slug}/sources/orden [ids]`, `POST /brands/{slug}/
  sources/{id}/run` (encola el job ya).
- Fuera de v1: `x` (Twitter). El modelo lo admite como `provider='x'`.

### 8. Errores y seguridad

- Errores JSON `{error: código, detalle: str, campo?: str}`. 401 sin sesión,
  403 sin permiso en la marca, 404 recurso, 409 choque de slot / slug
  duplicado, 422 validación y **secretos faltantes con la clave exacta**
  (`{error:"cred_faltante", campo:"TELEGRAM_BOT_TOKEN"}`), 429 en auth.
- Toda consulta filtra por `account_id` de las marcas del usuario; los ids
  de `queue/jobs/photos/sources` se resuelven a su marca y se verifica
  membresía (nunca confiar en el slug de la URL solo).
- Uploads: tamaño y tipo validados, nombres regenerados, servidos desde
  `/files/*` con `Cache-Control` y sin listado.
- Rate limit en `POST /auth/magic-link` (5/hora por email e IP).

### 9. Testing backend

- Auth: magic link (uso único, expiración), sesión, `GET /me`, invitación
  admin-only, editor no puede tocar secretos/presets/fuentes (403).
- Secretos: round-trip Fernet, precedencia DB → env sufijo → global solo
  gdlscene, marca nueva jamás hereda tokens globales, respuesta nunca incluye
  el valor.
- Cola: aprobar sin Sheet asigna slot desde DB, aprobar con Sheet espejo,
  409 en choque, aprobar desde API y desde callback Telegram convergen,
  publisher publica solo filas vencidas de la marca correcta con sus creds
  (fakes de IG/Cloudinary).
- Jobs: toma atómica, límite por marca, progreso, error, huérfano → cola.
- Providers: Unsplash/RSS/NewsAPI con HTTP mockeado; `BancoMarcaProvider`
  aislado por `account_id`; migración `fuentes_imagen` → `brand_sources`.
- Presets: validación de esquema, preview smoke con Playwright.
- `/legacy` exige admin. Cero llamadas reales a servicios externos.

---

## Parte 2 — Frontend, deploy y testing

### 10. Frontend (`frontend/`)

Stack: Next 16 App Router, TypeScript, Tailwind v4, shadcn/ui, TanStack
Query, react-hook-form + zod, dnd-kit (calendario), Lucide icons.
`next.config.ts` con `rewrites` `/api/:path*` → `${API_URL}/:path*` (same-
origin: la cookie httpOnly funciona en Vercel sin dominio compartido).
`middleware.ts`: sin cookie → `/login`. Cliente API tipado en
`frontend/lib/api/` (zod para respuestas críticas). Idioma: español.

Rutas:

- `/login` — email → "revisa tu correo". `/auth/callback` — muestra estado y
  redirige (la API ya seteó la cookie).
- `/brands` — switcher visual: tarjetas con logo/handle/color, próximos posts,
  alertas de creds faltantes. Admin: "Nueva marca" → wizard 4 pasos (identidad
  → voz/prompts → preset semilla → conexiones), guardable a medias.
- `/b/[slug]` — dashboard: próximas 5 publicaciones, pendientes de aprobar,
  salud (Telegram ✅/❌, IG, LLM), temas sugeridos con "crear carrusel".
- `/b/[slug]/calendar` — semana/mes estilo Buffer: columna por día, tarjetas
  con thumbnail del slide 1 y color por estado, slots libres marcados como
  huecos con "+ crear aquí", drag-drop para reprogramar (confirmación si la
  API responde 409), click → drawer con carrusel completo, caption editable,
  aprobar / rechazar / regenerar / eliminar.
- `/b/[slug]/create` — wizard: tema (libre o tema sugerido) → formato →
  estilo (con preview del preset) → fuentes de imagen (orden) → nº de slides
  → Generar → progreso (polling de job, log legible) → resultado con carrusel
  swipeable → "Aprobar y programar" (siguiente slot libre por default,
  editable) o "Rechazar".
- `/b/[slug]/library` — todo lo generado, filtros por estado, "reusar tema".
- `/b/[slug]/settings/{perfil, prompts, estilos, fuentes, telegram,
  conexiones, horarios}` — pestañas descritas en §6-7. Conexiones muestra
  solo `configurada` + últimos 4 y botones "Probar". Fuentes: tarjetas por
  provider con orden arrastrable; galería del banco con subida drag-drop;
  sección Información con RSS/NewsAPI y últimos temas.
- `/admin/users` (invitar, marcas + rol, activar/desactivar, cerrar
  sesiones), `/admin/system` (jobs recientes, heartbeat de daemon/worker/
  publisher, versión, link a `/legacy`).
- Rol `editor`: pestañas de settings ocultas salvo Perfil y Estilos en modo
  lectura; la API rechaza igual (doble compuerta).
- Diseño: base shadcn neutra + acento por marca (`color_marca`), densidad
  tipo Linear/Buffer, empty states con CTA, dark mode por sistema, todo
  responsive (calendario colapsa a lista por día en móvil).

### 11. Deploy y migración

- Front: proyecto Vercel con root `frontend/`, env `API_URL`.
- Back: `Dockerfile`, `docker-compose.yml` (api, worker, daemon, publisher,
  caddy; `mem_limit`; `restart: unless-stopped`; healthchecks),
  `Caddyfile` (`api.<dominio>` → api:8000), `.env.server.example`,
  `docs/deploy.md` (requisitos §Recursos, pasos: clonar, `.env`, `docker
  compose up -d`, `bootstrap --admin`, apuntar dominio, verificar `/health`).
- Migración gdlscene (sección propia en `docs/deploy.md`): rsync de `data/`,
  `init_db` migra esquema, `bootstrap --importar-env`, apagar launchd
  (`instalar_*.sh` tienen `--desinstalar` o `launchctl unload`), desactivar
  `publish.yml` en Actions cuando el publisher del server esté verificado.
- CI (`.github/workflows/ci.yml`): job Python existente + job `frontend`
  (pnpm install, lint, typecheck, vitest) + build de la imagen Docker.

### 12. Testing frontend

- Vitest + Testing Library: calendario (render por estado, drag → PATCH,
  409 → diálogo), wizard (pasos, validación zod, polling de job), editor de
  presets (form → PUT, preview), guardas por rol. MSW mockea la API.
- Playwright e2e mínimo: login (magic link leído del log en modo `TEST`) →
  crear carrusel (LLM y sourcing fakes) → aprobar → aparece en calendario.
  Corre contra la API real con SQLite temporal.

## Fuera de alcance (explícito)

Memes/agenda/anuncios/releases para marcas nuevas; X/Twitter como fuente;
TikTok y video/Reels; automations por marca; billing; Postgres; websockets;
edición de HTML de plantillas; migrar `bot.py` interactivo; app móvil.

## Riesgos

- **Fuga entre marcas** (creds/cola/fotos cruzadas): toda query por
  `account_id` verificado contra membresía + tests de aislamiento.
- **Master key**: si se pierde `INSTAGOD_MASTER_KEY` se pierden los secretos;
  `docs/deploy.md` exige respaldarla aparte del `.env`.
- **SQLite con 4 procesos**: WAL + `busy_timeout` 5 s + escrituras cortas; el
  worker es el único que hace trabajo largo y no mantiene transacciones
  abiertas durante render/LLM.
- **Scraping IG por marca**: comparte la sesión global de scraper; límites
  conservadores por defecto (`max_por_cuenta` 30, `cada_horas` 24) y
  circuit breaker existente.
- **Cookie cross-site**: se evita con `rewrites` (same-origin). Si el front
  se sirve desde otro origen sin rewrites, hace falta `SameSite=None` +
  dominio compartido; documentado.
