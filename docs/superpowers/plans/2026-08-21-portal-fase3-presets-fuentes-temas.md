# Portal de colaboradores — Fase 3: presets, prompts, fuentes (imagen/info), fotos y temas

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un manager configure TODO el perfil creativo de su marca desde la API — voz y prompts por formato, presets de estilo con preview renderizado, logo, fuentes de imagen ordenables (banco de carpeta, IG de referencia, Pinterest, Pexels, Unsplash), y fuentes de información (RSS/NewsAPI) que alimentan "temas sugeridos" convertibles en slideshows.

**Architecture:** Lógica en `src/` (`fuentes.py`, `topics.py`, providers nuevos en `image_sources.py`, campo `prompts` en `marcas.Marca`); routers delgados (`api/routers/perfil.py`, `api/routers/fuentes_api.py`). El banco de fotos de la marca ES la carpeta `data/brands/<slug>/fotos` (reutiliza `CarpetaProvider` existente). Previews de presets se generan con un job (`preset.preview`) y se sirven con endpoint autenticado. **Rulings previos:** subida de fuentes tipográficas (woff2) queda FUERA (manual, como hoy); scrape de IG usa `ingest` existente solo para cuentas ya en `bands` — para marcas nuevas el provider `ig_accounts` guarda las fotos en la carpeta de la marca vía el scraper de sesión global (best-effort, breaker).

**Tech Stack:** Python 3.12+, FastAPI multipart, SQLite, requests (Unsplash/NewsAPI), `xml.etree` para RSS (sin dependencia nueva), Playwright (preview).

**Spec:** `docs/superpowers/specs/2026-08-17-portal-colaboradores-design.md` (§6, §7). Fases 1-2 ya entregaron auth/roles/secretos/cola/jobs (`api/deps.marca_para`, `src/jobs` con `HANDLERS`, `config.account_creds` con claves `UNSPLASH_ACCESS_KEY`, `NEWSAPI_KEY`, `PEXELS_API_KEY`).

## Global Constraints

- Español en mensajes/docstrings/campos JSON/errores; errores `{"error","detalle","campo"}`.
- Commits sin firma de Claude; identidad `richyhoopd <theilluminatiduck@gmail.com>`.
- **NO tocar `config.py`, `publish.py`, `.github/`**. Env por marca vía `config.account_creds`.
- Secretos jamás en logs/respuestas; providers redactan errores (patrón `_error_seguro`).
- Cero llamadas reales a red/LLM/Playwright en tests (fakes; preview con `compose.render_card` monkeypatcheado; UN smoke real de render está permitido si corre <10 s).
- Fallos ambientales conocidos: test_planner, test_segmentos_web (y test_scraped_mark si el pool duerme). Ruff limpio en tocados.
- Uploads: multipart, tamaño máx 2 MB logo / 8 MB foto, extensiones whitelist, nombre regenerado (`uuid4().hex[:12] + ext` seguro), jamás path del cliente. Servir archivos SOLO vía endpoints autenticados con `marca_para` (no StaticFiles global).
- Aislamiento por marca en todo (sources/fotos/topics por `account_id`; archivos bajo `data/brands/<slug>/`).

## Mapa de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/schema.sql` + `src/db.py` | tablas `brand_sources`, `topic_suggestions`; columnas `accounts`: `descripcion, sitio_web, hashtags_default, prompts_json` |
| `src/marcas.py` | `Marca.prompts` (dict tolerante de `prompts_json`), campos nuevos en `_fila_a_marca` |
| `src/fuentes.py` (crear) | CRUD de `brand_sources` + `orden_imagen(cx, marca) -> list[str]` + validación de `config_json` por provider |
| `src/image_sources.py` | `UnsplashProvider`, `providers_default` acepta `creds` por marca (keys pexels/unsplash) |
| `src/topics.py` (crear) | `topic_suggestions` CRUD + `fetch_rss(url) -> list[dict]` (xml.etree) + `fetch_newsapi(query, key, ...)` + dedup por url |
| `src/jobs/handlers.py` | handlers `sourcing.rss_fetch`, `sourcing.newsapi_fetch`, `sourcing.ig_scrape`, `preset.preview` |
| `src/jobs/worker.py` | `encolar_fuentes_vencidas(cx)` en el loop (fuentes info con `cada_horas` vencidas → job) |
| `src/generate_slideshow.py` | fuentes default desde `fuentes.orden_imagen`; contexto del guion suma `prompts.por_formato[formato]` y `prompts.caption_extra`; `topic_id` opcional marca el topic usado |
| `api/routers/perfil.py` (crear) | prompts GET/PUT + probar; presets GET/PUT/DELETE + preview; logo upload; archivos (previews/fotos) servidos autenticados |
| `api/routers/fuentes_api.py` (crear) | sources CRUD/orden/run; fotos de marca upload/list/delete; topics list/descartar |
| `api/app.py` | registrar routers |
| `docs/api_portal.md` | sección Fase 3 |
| Tests | `tests/test_fase3_schema.py`, `tests/test_fuentes.py`, `tests/test_unsplash_banco.py`, `tests/test_topics.py`, `tests/test_handlers_sourcing.py`, `tests/test_api_perfil.py`, `tests/test_api_fuentes.py` |

---

### Task 1: Esquema F3

**Files:** `src/schema.sql` (append), `src/db.py` (TABLES + `_MIGRATIONS["accounts"]`), test `tests/test_fase3_schema.py`.

```sql
CREATE TABLE IF NOT EXISTS brand_sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,            -- 'imagen' | 'info'
    provider    TEXT NOT NULL,            -- imagen: carpeta|ig_accounts|pinterest|pexels|unsplash|banco|covers ; info: rss|newsapi
    config_json TEXT,
    activa      INTEGER NOT NULL DEFAULT 1,
    orden       INTEGER NOT NULL DEFAULT 0,
    ultimo_run  TEXT,
    ultimo_error TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (kind IN ('imagen','info')), CHECK (activa IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_sources_account ON brand_sources(account_id);

CREATE TABLE IF NOT EXISTS topic_suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    titulo      TEXT NOT NULL,
    resumen     TEXT,
    url         TEXT,
    fuente      TEXT,
    publicado_en TEXT,
    usado_en_queue_id INTEGER,
    descartado  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (descartado IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_topics_account ON topic_suggestions(account_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_topics_url ON topic_suggestions(account_id, url);
```
`_MIGRATIONS["accounts"]` += `descripcion TEXT`, `sitio_web TEXT`, `hashtags_default TEXT`, `prompts_json TEXT`. TABLES: `brand_sources` (todas menos id/created_at), `topic_suggestions` (ídem), accounts += las 4. `src/marcas.py`: `Marca` gana `prompts: dict` (default `{}`) parseado tolerante de `prompts_json` (`{caption_extra:"", por_formato:{}, hashtags:[]}` como base), y `descripcion/sitio_web/hashtags_default` NO van al dataclass (se leen de la fila cruda en la API).

- [ ] Test: tablas existen e idempotente; unique (account_id,url) en topics (2º insert misma url → IntegrityError); CHECK kind; accounts migra las 4 columnas en DB vieja; `marcas.cargar` con `prompts_json='{"caption_extra":"x"}'` → `m.prompts["caption_extra"]=="x"` y con JSON roto → `{}` base. RED→GREEN→commit `feat(fase3): brand_sources, topic_suggestions y perfil extendido de accounts`.

---

### Task 2: `src/fuentes.py` + orden de imagen en generar

**Files:** crear `src/fuentes.py`; modificar `src/generate_slideshow.py`; test `tests/test_fuentes.py`.

```python
PROVIDERS_IMAGEN = ("carpeta","ig_accounts","pinterest","pexels","unsplash","banco","covers")
PROVIDERS_INFO = ("rss","newsapi")
def crear(cx, account_id, kind, provider, config: dict | None = None, *, orden=None) -> int
    # ValueError("provider") si no está en el catálogo del kind; valida config:
    # ig_accounts: {"cuentas":[@...], "max_por_cuenta":int<=50, "cada_horas":int>=6}
    # rss: {"urls":[http...]} no vacía; newsapi: {"query":str no vacía, "idioma"?: str, "pais"?: str}
    # otros: config opcional. ValueError("config") si inválida.
def listar(cx, account_id, kind=None) -> list[dict]      # orden asc, config parseado
def actualizar(cx, source_id, *, config=None, activa=None) -> None
def borrar(cx, source_id) -> None
def reordenar(cx, account_id, ids: list[int]) -> None    # ValueError("ids") si no son exactamente sus sources
def orden_imagen(cx, marca) -> list[str]
    # providers de filas activas kind='imagen' en orden; si la marca no tiene filas → marca.fuentes (compat)
```
`generate_slideshow.generar`: `fuentes = tuple(fuentes) if fuentes else tuple(fuentes_mod.orden_imagen(cx, m))`; el contexto del guion pasa a `"\n\n".join(x for x in (m.voz, m.prompts.get("por_formato",{}).get(formato), contexto) if x)`; nuevo kwarg `topic_id=None` → al encolar, `db.update(cx,"topic_suggestions",topic_id, usado_en_queue_id=qid)` (tolerante si no existe). El caption final suma `m.prompts.get("caption_extra")` y hashtags: si `m.prompts.get("hashtags")` no vacío, append `" ".join(hashtags)` al caption del show antes de encolar.

- [ ] Tests: validaciones de crear (provider/config inválidos), reordenar con id ajeno → ValueError, `orden_imagen` con filas (orden y solo activas) y sin filas (fallback a m.fuentes); generar (con todo lo remoto fakeado como en test_jobs_handlers) usa `orden_imagen`, concatena prompt por formato en el contexto del guion, agrega hashtags al caption y marca el topic. RED→GREEN→commit `feat(fase3): fuentes por marca (brand_sources) y prompts por formato en generar`.

---

### Task 3: Providers Unsplash + creds por marca

**Files:** `src/image_sources.py` (append/modify `providers_default`), test `tests/test_unsplash_banco.py`.

```python
class UnsplashProvider:
    nombre = "unsplash"
    def __init__(self, access_key: str | None = None): ...
    def buscar(self, hint, n=3) -> list[ImagenCandidata]
    # GET https://api.unsplash.com/search/photos?query=&per_page=&client_id=key
    # → ImagenCandidata(url regular, "unsplash", credito=f"{user.name} / Unsplash")
    # sin key → [] con aviso; errores → [] (nunca lanza); timeout 15
```
`ImagenCandidata` gana campo opcional `credito: str | None = None` (default None; no rompe usos existentes). `providers_default(cx=None, slug=None, creds: dict | None = None)`: `creds` (dict estilo `account_creds`) alimenta `UnsplashProvider(creds.get("UNSPLASH_ACCESS_KEY"))` y `PexelsProvider` — PexelsProvider gana `__init__(self, api_key=None)` usando `api_key or config.PEXELS_API_KEY` (compat). `generate_slideshow.generar` llama `resolver(..., providers=image_sources.providers_default(cx, slug=m.slug, creds=config.account_creds(m.slug)))`.

- [ ] Tests (requests mockeado): Unsplash parsea resultados y credito; sin key → []; HTTP error → [] sin excepción y sin key en el texto impreso; providers_default con creds inyecta keys por marca; PexelsProvider key por marca gana a la global; compat: llamadas existentes sin creds siguen igual (test de firma). RED→GREEN→commit `feat(fase3): provider Unsplash y credenciales de imagen por marca`.

---

### Task 4: `src/topics.py` + handlers de sourcing

**Files:** crear `src/topics.py`; modificar `src/jobs/handlers.py` (+HANDLERS), `src/jobs/worker.py`; tests `tests/test_topics.py`, `tests/test_handlers_sourcing.py`.

```python
# topics.py
def fetch_rss(url: str, *, _get=None) -> list[dict]   # xml.etree: RSS2 (item) y Atom (entry);
    # → [{titulo, resumen (texto plano, 500 max), url, publicado_en}] ; errores → [] con aviso
def fetch_newsapi(query: str, key: str, *, idioma="es", pais=None, _get=None) -> list[dict]
    # GET https://newsapi.org/v2/everything?q=&language=&apiKey= (top 20)
def guardar(cx, account_id, items: list[dict], fuente: str) -> int  # INSERT OR IGNORE (unique url); devuelve nuevos
def listar(cx, account_id, *, incluir_usados=False) -> list[dict]   # descartado=0; usados fuera salvo flag
def descartar(cx, topic_id) -> None
```
Handlers (en `handlers.py`): `sourcing.rss_fetch` payload `{source_id}` → lee la source (validar que es del `job.account_id`, si no ValueError), por cada url `fetch_rss`, `guardar`, actualizar `ultimo_run`/`ultimo_error` de la source; `sourcing.newsapi_fetch` ídem con la key de `config.account_creds(slug)["NEWSAPI_KEY"]` (falta → terminar el job en error accionable "Falta NEWSAPI_KEY"); `sourcing.ig_scrape` payload `{source_id}` → por cada `@cuenta` de config usa `ingest_ig.get_session()` + descarga hasta `max_por_cuenta` fotos del perfil a `data/brands/<slug>/fotos/` (reusar el fetch de posts del scraper si existe una función utilizable; si el scraper no da sesión sana → error accionable, jamás loop); `preset.preview` payload `{nombre, texto}` → carga marca, `estilos_de`, `slideshow_compile.compilar` de un guion sintético de 1 slide (hook = texto o "Así se ve tu preset") + `compose.render_card("slide.html", ctx, prefix=f"preview_{slug}_{nombre}")` → copia a `data/previews/<slug>/<nombre>.png` → resultado `{"path": ...}`.
`worker.py`: en cada iteración del loop, `encolar_fuentes_vencidas(cx)`: fuentes info activas con `cada_horas` en config (default 24) y `ultimo_run` NULL o más viejo → `jobs.crear` (si no hay ya un job cola/corriendo de esa source — buscar por payload LIKE `%"source_id": N%` o registrar tipo+account y dedup simple).

- [ ] Tests: fetch_rss con XML RSS y Atom de fixture (string inline), malformado → []; fetch_newsapi mock; guardar dedup por url; handlers con fakes (source de otra cuenta → error; newsapi sin key → job error accionable; preview con render_card monkeypatcheado escribe el PNG destino); encolar_fuentes_vencidas crea job solo cuando toca y no duplica. RED→GREEN→commit `feat(fase3): temas sugeridos (rss/newsapi), scrape a carpeta y preview de presets como jobs`.

---

### Task 5: Router de perfil (prompts, presets, logo, archivos)

**Files:** crear `api/routers/perfil.py`; modificar `api/app.py`; test `tests/test_api_perfil.py`.

Endpoints (manager+ salvo lectura, que es editor+):
- `GET /brands/{slug}/prompts` → `{voz, caption_extra, por_formato, hashtags}` (de `Marca`); `PUT` (manager) valida: voz str ≤4000, caption_extra ≤500, por_formato dict[str,str] con claves ∈ formatos de la marca, hashtags list[str] ≤30 items empezando con "#": guarda `voz` y `prompts_json`.
- `POST /brands/{slug}/prompts/probar {tema, formato?}` (manager) → llama `slideshow_script.generar_guion(tema, formato=..., n_slides=4, contexto=<voz+por_formato>)` y devuelve el guion (LLM real en prod; en tests se monkeypatchea). Errores → 502 `{"error":"prueba_fallida"}` redactado.
- `GET /brands/{slug}/presets` (editor) → `marcas.estilos_de(m)` con flag `propio: bool` por preset; `PUT /brands/{slug}/presets/{nombre}` (manager): nombre `^[a-z0-9_]{2,32}$`, body dict con al menos `texto` y `roles` (dict no vacío) → merge en `accounts.estilos_json`; `DELETE` solo presets propios (404 si es global).
- `POST /brands/{slug}/presets/{nombre}/preview {texto?}` (manager) → job `preset.preview` → 202 `{job_id}`; el PNG luego por `GET /brands/{slug}/files/previews/{nombre}.png` (editor; `marca_para` + path construido server-side, jamás del cliente).
- `POST /brands/{slug}/logo` (manager, multipart, png/svg/jpg ≤2 MB) → `data/brands/<slug>/logo.<ext>` + `accounts.logo_path`; `GET /brands/{slug}/files/logo` lo sirve.
- `PATCH /brands/{slug}` ya existe en brands.py — AÑADIR ahí (mismo task, cambio mínimo) los campos `descripcion` (≤600), `sitio_web` (≤200), `hashtags_default` (≤400).

- [ ] Tests: roles (editor lee prompts pero PUT → 403), validaciones (por_formato con formato no habilitado → 422 campo, hashtags sin # → 422), probar con generar_guion monkeypatcheado, preset propio CRUD + no poder borrar global, preview crea job y file endpoint sirve el PNG (crear el archivo a mano) con 404 para otra marca, logo upload valida tamaño/extensión y rechaza .exe, path traversal (`nombre="../x"`) → 404/422. RED→GREEN→commit `feat(api): prompts, presets con preview, logo y perfil extendido`.

---

### Task 6: Router de fuentes, fotos y temas

**Files:** crear `api/routers/fuentes_api.py`; modificar `api/app.py`; test `tests/test_api_fuentes.py`.

Endpoints (manager+ para mutar, editor+ para leer):
- `GET /brands/{slug}/sources[?kind=]`; `POST /brands/{slug}/sources {kind, provider, config?, activa?}` → `fuentes.crear` (ValueError provider/config → 422 con campo); `PATCH /brands/{slug}/sources/{id} {config?, activa?}`; `DELETE`; `PUT /brands/{slug}/sources/orden {ids:[...]}`; `POST /brands/{slug}/sources/{id}/run` → job del tipo correcto según provider (`rss→sourcing.rss_fetch`, `newsapi→sourcing.newsapi_fetch`, `ig_accounts→sourcing.ig_scrape`; imagen estáticos como pexels/unsplash/carpeta → 422 "no ejecutable") → 202 `{job_id}`. Ownership: source de otra marca → 404.
- `GET /brands/{slug}/photos` → lista de `data/brands/<slug>/fotos` (nombre, tamaño, mtime, url de archivo); `POST /brands/{slug}/photos` (multipart, jpg/png/webp ≤8 MB, hasta 10 por request) → guarda con nombre regenerado; `DELETE /brands/{slug}/photos/{nombre}` (valida nombre `^[a-z0-9_.-]+$`, sin path traversal); `GET /brands/{slug}/files/fotos/{nombre}` sirve autenticado.
- `GET /brands/{slug}/topics[?usados=1]`; `POST /brands/{slug}/topics/{id}/descartar`. Topic de otra marca → 404.

- [ ] Tests: CRUD + orden + run (job correcto por provider; pexels → 422); fotos upload (extensión/tamaño/n>10 → 422; nombre regenerado; list y delete; traversal `../` → 422/404; foto de otra marca no accesible); topics list/descartar/ownership. RED→GREEN→commit `feat(api): fuentes de imagen/info, banco de fotos y temas sugeridos`.

---

### Task 7: `POST /brands/{slug}/slideshows` acepta `topic_id`

**Files:** modificar `api/routers/trabajos.py`; test en `tests/test_api_trabajos.py` (append).

Body gana `topic_id: int | None`; si viene: el topic debe ser de la marca y no descartado (404/422), el payload del job lo incluye y además `tema`/`contexto` defaultean a `titulo`/`resumen+url` del topic si no vienen. El handler `slideshow.generar` pasa `topic_id` a `generar(...)` (Task 2 ya lo consume).

- [ ] Tests: con topic de la marca crea job con tema del topic; topic ajeno → 404; topic descartado → 422. RED→GREEN→commit `feat(api): slideshows desde tema sugerido (topic_id)`.

---

### Task 8: Docs + humo

- [ ] `docs/api_portal.md`: sección "Perfil creativo y fuentes (Fase 3)" — endpoints nuevos, regla del banco de carpeta, providers de imagen disponibles y sus claves (`PEXELS_API_KEY`/`UNSPLASH_ACCESS_KEY`/`NEWSAPI_KEY` por marca vía secrets), preview como job, `cada_horas` y `encolar_fuentes_vencidas`, subida de fotos y límites, `topic_id` en slideshows. Humo: rutas cargan; suite completa; ruff.
- [ ] Commit `docs(fase3): perfil creativo, fuentes y temas en api_portal`.

## Auto-revisión
Spec §6: prompts (T5), presets+preview (T4,T5), logo (T5), campos extra de accounts (T1,T5) — fuentes tipográficas excluidas por ruling. §7: brand_sources (T1,T2), providers imagen incl. unsplash y banco-carpeta (T2,T3), ig_accounts scrape (T4), rss/newsapi→topics (T4,T6), run manual (T6), topic→slideshow (T7). Firmas cruzadas consistentes (fuentes.crear/listar/actualizar/borrar/reordenar/orden_imagen; topics.fetch_rss/fetch_newsapi/guardar/listar/descartar; providers_default(cx, slug, creds)). Sin placeholders.
