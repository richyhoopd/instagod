# Portal de colaboradores — Fase 2: cola como fuente de verdad, publisher y jobs

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que `content_queue` (SQLite) sea la cola oficial de publicación — aprobable desde API o Telegram, publicada por un publisher local en loop y alimentada por jobs asíncronos que generan slideshows — sin romper el flujo Sheet/Actions de gdlscene.

**Architecture:** Lógica nueva en `src/` (`cola.py`, `jobs/`, `publisher.py`, `scheduler.next_free_slot_db`); `approval.aprobar` deja de exigir Sheet (espejo opcional); los routers (`api/routers/cola.py`, `api/routers/trabajos.py`) son delgados. **Regla anti-doble-publicación (ruling):** una marca CON `SHEET_ID` sigue publicándose por el camino Sheet/Actions (el publisher DB la salta); una marca SIN `SHEET_ID` se publica 100 % desde la DB. Así hay exactamente un publicador por marca hasta la Fase 5.

**Tech Stack:** Python 3.12+, FastAPI/Pydantic v2, SQLite (WAL ya activo), python-telegram-bot (sin cambios), requests.

**Spec:** `docs/superpowers/specs/2026-08-17-portal-colaboradores-design.md` (§4 cola, §5 jobs, §8-§9). La Fase 1 ya entregó auth/roles/secretos (`api/deps.marca_para`, `config.account_creds`).

## Global Constraints

- Español en mensajes, docstrings, campos JSON y errores. Errores JSON `{"error","detalle","campo"}`.
- Commits sin firma de Claude ni Co-Authored-By; identidad `richyhoopd <theilluminatiduck@gmail.com>`.
- **NO tocar `config.py`** en esta fase (env nuevo se lee con `os.getenv` en el módulo que lo usa). No tocar `publish.py` (Actions) ni `.github/workflows/`.
- Secretos jamás en logs/respuestas. Cero llamadas reales a Telegram/IG/LLM/Cloudinary en tests (fakes/monkeypatch).
- Suite verde salvo fallos ambientales conocidos: `test_planner::test_plan_month_salta_slots_pasados`, `test_segmentos_web::test_segmentos_lista_catalogo_y_preview`, `test_scraped_mark` (x3, pool scraper en reposo). ruff limpio en archivos tocados.
- Los tests aíslan DB con `db.connect(tmp_path/...)` o fixture `api_cliente` (ya limpia env IG/TG y anula master key).
- Estados API de una fila (derivados, helper único): `generando` (job vivo sin contenido), `pendiente` (aprobacion=pendiente), `programado` (aprobado + status en_sheet|programado), `publicado`, `rechazado`, `error`, `descartado`.

---

## Mapa de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/schema.sql` + `src/db.py` (modificar) | columnas nuevas de `content_queue` (+ rebuild cols), tabla `jobs`, whitelists |
| `src/scheduler.py` (modificar, append) | `next_free_slot_db`, `slots_proximos_db` (leen content_queue, no Sheet) |
| `src/approval.py` (modificar) | `aprobar` sin Sheet obligatorio + espejo opcional + `aprobado_por`; `rechazar(user_id)`; `enviar_a_telegram` guarda `tg_chat_id/tg_message_id`; `notificar_resolucion` |
| `src/cola.py` (crear) | consultas/acciones de la cola para la API: listar, detalle, reprogramar (409), eliminar, estado derivado |
| `src/jobs/__init__.py` (crear) | modelo de jobs: crear, tomar (atómico), progresar, terminar, rescatar huérfanos |
| `src/jobs/handlers.py` (crear) | `slideshow.generar`, `slideshow.regenerar` |
| `src/jobs/worker.py` (crear) | loop del worker (`python -m src.jobs.worker [--once]`) |
| `src/generate_slideshow.py` (modificar) | `generar(...)` gana `progreso: Callable[[int,str],None] | None` y `creado_por` |
| `src/publisher.py` (crear) | loop de publicación desde DB (`python -m src.publisher [--once]`) |
| `api/routers/cola.py`, `api/routers/trabajos.py` (crear) + `api/app.py` (registrar) | endpoints de cola, slots, slideshows y jobs |
| `docs/api_portal.md` (modificar) | endpoints y operación nuevos |
| Tests: `tests/test_cola.py`, `tests/test_scheduler_db.py`, `tests/test_aprobar_sin_sheet.py`, `tests/test_jobs.py`, `tests/test_jobs_handlers.py`, `tests/test_publisher.py`, `tests/test_api_cola.py`, `tests/test_api_trabajos.py` |

---

### Task 1: Esquema — columnas de cola + tabla jobs

**Files:** Modify `src/schema.sql` (append), `src/db.py` (`TABLES`, `_MIGRATIONS["content_queue"]`, `_CONTENT_QUEUE_REBUILD_DDL` + `_CONTENT_QUEUE_REBUILD_COLS`). Test: `tests/test_fase2_schema.py`.

**Produces:** columnas nuevas en `content_queue`: `publicado_en TEXT`, `error TEXT`, `creado_por INTEGER`, `aprobado_por INTEGER`, `ig_media_id TEXT`, `origen TEXT NOT NULL DEFAULT 'legacy'`, `tg_chat_id TEXT`, `tg_message_id TEXT`. Tabla nueva:

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo         TEXT NOT NULL,
    account_id   INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT,
    estado       TEXT NOT NULL DEFAULT 'cola',
    progreso     INTEGER NOT NULL DEFAULT 0,
    log          TEXT,
    resultado_json TEXT,
    queue_id     INTEGER,
    creado_por   INTEGER,
    worker_id    TEXT,
    heartbeat    TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT,
    CHECK (estado IN ('cola','corriendo','ok','error','cancelado'))
);
CREATE INDEX IF NOT EXISTS idx_jobs_estado ON jobs(estado);
CREATE INDEX IF NOT EXISTS idx_jobs_account ON jobs(account_id);
```

Whitelist `TABLES["jobs"]` = todas las columnas menos id/created_at. **OJO:** las columnas nuevas de `content_queue` deben agregarse TANTO en `_MIGRATIONS["content_queue"]` COMO en `_CONTENT_QUEUE_REBUILD_DDL`/`_CONTENT_QUEUE_REBUILD_COLS` (el rebuild del CHECK revienta a propósito si faltan — leer el comentario en `src/db.py:200`).

- [ ] Test primero (`tests/test_fase2_schema.py`): `init_db` idempotente con las columnas nuevas (`PRAGMA table_info(content_queue)` contiene las 8), tabla `jobs` existe, CHECK de estado rechaza `'volando'` (sqlite3.IntegrityError), `db.insert(cx,"jobs",tipo="slideshow.generar",account_id=1)` funciona y `estado=='cola'`, y una DB "vieja" (crear con el schema base sin las columnas → correr `init_db` de nuevo) migra sin error. RED → implementar → GREEN.
- [ ] Correr también `tests/test_db_migracion_tipo_queue.py` y `tests/test_motor_migraciones.py` (protegen el rebuild).
- [ ] Commit: `feat(fase2): columnas de publicación en content_queue + tabla jobs`

---

### Task 2: Slots desde la DB

**Files:** Modify `src/scheduler.py` (append al final). Test: `tests/test_scheduler_db.py`.

**Produces:**
```python
def _taken_db(cx, account_id: int) -> set[str]      # "YYYY-MM-DDTHH:MM" de filas del account con
                                                    # status IN ('en_sheet','programado','publicado') y scheduled_datetime no nulo
def next_free_slot_db(cx, account_id: int, *, now: datetime | None = None,
                      slots: list[str] | None = None) -> datetime
def slots_proximos_db(cx, account_id: int, n: int = 5, *, now: datetime | None = None,
                      slots: list[str] | None = None) -> list[datetime]
```
Misma semántica que `next_free_slot` (empieza mañana, malla propia = tope diario, tz `config.TIMEZONE`, respeta `POSTS_PER_DAY` si `slots is None`) pero los ocupados salen de `content_queue`, no del Sheet. `slots_proximos_db` devuelve los N primeros huecos libres consecutivos.

- [ ] Tests: con 2 filas programadas mañana 19:00/20:00 para account 1, `next_free_slot_db` salta a el siguiente hueco de la malla; filas de OTRO account no ocupan; `status='borrador'` no ocupa; `slots_proximos_db(n=3)` devuelve 3 datetimes crecientes sin chocar con ocupados; malla propia `["10:00","18:00"]` respeta el orden. Usar `now` fijo (datetime con tz de config.TIMEZONE) para determinismo. RED → implementar → GREEN.
- [ ] Commit: `feat(fase2): next_free_slot_db y slots_proximos_db desde content_queue`

---

### Task 3: `approval.aprobar` sin Sheet + rastro de Telegram

**Files:** Modify `src/approval.py`. Tests: `tests/test_aprobar_sin_sheet.py` (nuevo); actualizar `tests/test_approval.py` / `tests/test_approval_multimarca.py` SOLO donde asuman que sin SHEET_ID truena (ese comportamiento cambia por spec §4; documentarlo en el reporte).

**Produces (firmas):**
```python
def aprobar(cx, queue_id, *, ahora=None, ventana_trafico="meme", audiencia=None,
            user_id: int | None = None,
            _escribir_sheet=None, _publicar=None, _slot_meme=None) -> datetime
def rechazar(cx, queue_id: int, *, user_id: int | None = None) -> None
def enviar_a_telegram(caption, imagen_url, queue_id, *, regenerable=False,
                      account_slug="gdlscene", cx=None) -> None   # guarda tg ids si cx
def notificar_resolucion(cx, queue_id: int, texto: str) -> bool   # edita/avisa en TG; tolerante
```
Comportamiento de `aprobar`:
1. Carga fila y marca. `sheet_id = creds.get("SHEET_ID")` — **ya no es error que falte**.
2. Slot: `tipo=='anuncio'` → inmediato (igual que hoy). Si hay `sheet_id` → hueco vía `_slot_meme or _siguiente_hueco` (camino legacy intacto, lee Sheet). Si NO hay `sheet_id` → `scheduler.next_free_slot_db(cx, fila["account_id"], now=ahora, slots=marca.posting_slots)`.
3. Con `sheet_id`: escribe el Sheet como hoy y deja `status='en_sheet'` + `sheet_row_id` (Actions sigue publicando esta marca). Si el Sheet falla (Exception) NO se revierte la aprobación: `status='programado'`, columna `error` = `"espejo sheet: <msg truncado 200>"` (accionable, no bloquea).
4. Sin `sheet_id`: `status='programado'` (el publisher DB la tomará).
5. Siempre: `aprobacion='aprobado'`, `scheduled_datetime=slot.isoformat()`, `aprobado_por=user_id`, y los efectos existentes (foto usada, eventos anunciados, `_publicar` si inmediato).
`enviar_a_telegram(cx=...)`: tras el sendMessage/sendPhoto final captura `resp.json()["result"]["message_id"]` y `chat.id` y hace `db.update(cx,"content_queue",qid, tg_chat_id=..., tg_message_id=...)`; sin `cx` (llamadas legacy) comportamiento idéntico al actual. `notificar_resolucion`: si la fila tiene tg ids y la marca tiene token, llama `editMessageReplyMarkup` (quita botones) y `sendMessage` con `reply_to_message_id` y `texto`; cualquier fallo → `False` + aviso stderr, jamás excepción.

- [ ] Tests (fakes de requests/sheet, cero red): aprobar sin SHEET_ID usa slot DB y deja `programado` + `aprobado_por`; aprobar con SHEET_ID conserva `en_sheet`+`sheet_row_id`; espejo que truena deja `programado`+`error` empezando con "espejo sheet:"; `rechazar` guarda `aprobado_por` (sí: quien rechaza también queda registrado) y `descartado`; `enviar_a_telegram` con `cx` persiste tg ids (monkeypatch `requests.post` devolviendo `{"ok":True,"result":{"message_id":42,"chat":{"id":-100}}}`); `notificar_resolucion` sin token devuelve False sin excepción. RED → implementar → GREEN. Verificar `tests/test_daemon_multibot.py` sigue verde.
- [ ] Commit: `feat(fase2): aprobar sin Sheet (slot desde DB), espejo opcional y rastro de Telegram`

---

### Task 4: `src/cola.py` — operaciones de cola para la API

**Files:** Create `src/cola.py`. Test: `tests/test_cola.py`.

**Produces:**
```python
ESTADOS = ("generando","pendiente","programado","publicado","rechazado","error","descartado")
def estado_de(fila: dict) -> str
def listar(cx, account_id, *, desde=None, hasta=None, estado=None) -> list[dict]  # + campo "estado"
def detalle(cx, queue_id) -> dict | None            # + estado + slideshow_json parseado como "slides_data"
def reprogramar(cx, queue_id, nueva_iso: str) -> None  # ValueError("choque") si otra fila programada
                                                        # del mismo account ocupa ese minuto; ValueError("estado") si no está programado/pendiente
def editar_caption(cx, queue_id, caption: str) -> None  # solo pendiente/programado
def eliminar(cx, queue_id) -> None                  # solo pendiente|rechazado|error → descartado; si no ValueError("estado")
```
`estado_de`: `descartado` si status descartado y aprobacion!=rechazado; `rechazado` si aprobacion rechazado; `publicado` si status publicado; `error` si columna error y status!='publicado' y no en_sheet; `programado` si aprobacion aprobado y status en ('en_sheet','programado'); `pendiente` si aprobacion pendiente; `generando` si aprobacion IS NULL y status borrador; fallback `pendiente`.

- [ ] Tests: matriz de `estado_de` (los 7 estados con filas sintéticas); `listar` filtra por rango de `scheduled_datetime`/`created_at` y por estado y NUNCA devuelve filas de otro account; `reprogramar` con choque lanza ValueError("choque") y con fila publicada ValueError("estado"); `eliminar` de fila programada lanza; `detalle` de id inexistente → None. RED → implementar → GREEN.
- [ ] Commit: `feat(fase2): src/cola.py — estados derivados y operaciones de cola`

---

### Task 5: Jobs — modelo, worker y handlers de slideshow

**Files:** Create `src/jobs/__init__.py`, `src/jobs/worker.py`, `src/jobs/handlers.py`. Modify `src/generate_slideshow.py` (param `progreso` y `creado_por`). Tests: `tests/test_jobs.py`, `tests/test_jobs_handlers.py`.

**Produces (`src/jobs/__init__.py`):**
```python
def crear(cx, tipo: str, account_id: int, payload: dict, *, creado_por=None) -> int
def tomar(cx, worker_id: str, *, max_global: int | None = None) -> dict | None
    # UPDATE ... WHERE id = (SELECT id FROM jobs WHERE estado='cola'
    #   AND account_id NOT IN (SELECT account_id FROM jobs WHERE estado='corriendo')
    #   ORDER BY id LIMIT 1) RETURNING *  — atómico; respeta max_global (si ya hay >= corriendo → None)
def progresar(cx, job_id, pct: int, msg: str) -> None   # progreso + heartbeat=utcnow + log append "[pct%] msg"
def terminar(cx, job_id, *, ok: bool, resultado: dict | None = None, error: str | None = None) -> None
def cancelar(cx, job_id) -> bool                        # solo estado='cola' → 'cancelado'
def rescatar_huerfanos(cx, *, max_min: int = 30) -> int # corriendo sin heartbeat hace >max_min:
    # 1ª vez → de vuelta a 'cola' (log lo anota); si ya fue rescatado (log contiene '[rescate]') → 'error'
```
`worker.py`: `main(once: bool = False)` — loop: `rescatar_huerfanos`, `tomar` (con `max_global` = `int(os.getenv("WORKER_MAX_JOBS","2"))`), si hay job → despacha por `tipo` al handler de `handlers.HANDLERS` dict; handler recibe `(cx, job)` y devuelve dict resultado; excepción → `terminar(ok=False, error=str truncado 400)`; sin job → `time.sleep(3)` (monkeypatcheable `_dormir`). `--once` procesa a lo más un job y sale.
`handlers.py`: `HANDLERS = {"slideshow.generar": generar_slideshow, "slideshow.regenerar": regenerar_slideshow}`.
- `generar_slideshow(cx, job)`: payload `{tema, formato, estilo, fuentes, n_slides, aspect, contexto}` → llama `generate_slideshow.generar(cx, tema, marca=<slug de accounts por job.account_id>, ..., progreso=lambda pct,msg: jobs.progresar(cx, job["id"], pct, msg), creado_por=job["creado_por"])` → devuelve `{"queue_id": qid}` y `db.update(cx,"jobs",job["id"],queue_id=qid)`.
- `regenerar_slideshow(cx, job)`: payload `{queue_id}` → lee la fila, `brief` de `slideshow_json` (`json.loads(...)["brief"]`), marca la fila vieja `status='descartado'`, corre `generar(...)` con el mismo brief → `{"queue_id": nuevo}`.
`generate_slideshow.generar`: params nuevos `progreso=None, creado_por=None`; llama `progreso(10,"guion")` antes del guion, `(40,"imágenes")` antes de resolver, `(60,"render")` antes de los PNG, `(85,"subiendo")` antes de Cloudinary, `(100,"listo")` al final; `encolar_pendiente` NO cambia de firma — tras encolar, `db.update(cx,"content_queue",qid, creado_por=creado_por, origen="api")` si `creado_por is not None`. `enviar_a_telegram(..., cx=cx)` para guardar tg ids.

- [ ] Tests jobs (`tests/test_jobs.py`): crear→tomar devuelve el job y lo deja corriendo con worker_id; segundo `tomar` con job corriendo del MISMO account devuelve None pero otro account sí sale; `max_global=1` con 1 corriendo → None; `progresar` acumula log y actualiza heartbeat; `terminar(ok=False)` deja error; `cancelar` solo en cola; huérfano (heartbeat viejo, monkeypatch de la función de "ahora" del módulo o insertar heartbeat antiguo a mano) vuelve a cola la 1ª vez y a error la 2ª; `worker.main(once=True)` con handler fake registra resultado (monkeypatch `handlers.HANDLERS`).
- [ ] Tests handlers (`tests/test_jobs_handlers.py`): con `generate_slideshow.generar` monkeypatcheado (registra kwargs, devuelve 77): `generar_slideshow` pasa marca/tema/progreso y guarda `queue_id=77`; `regenerar_slideshow` descarta la fila vieja y usa el brief guardado (fila con `slideshow_json='{"brief":{"tema":"x","formato":"listicle","estilo":"e","fuentes":["pexels"],"n_slides":6,"contexto":null,"aspect":"4:5","marca":"gdlscene"}}'`). Y un test de humo real de `progreso` en `generar`: monkeypatch de `slideshow_script.generar_guion`/`image_sources.resolver`/`slideshow_compile`/`compose.render_card`/`host.upload`/`approval.enviar_a_telegram` con fakes mínimos y verificar que la lista de pcts reportados es creciente y termina en 100 (dry_run=False). RED → implementar → GREEN.
- [ ] Commit: `feat(fase2): motor de jobs (worker + handlers de slideshow) y progreso en generar`

---

### Task 6: Publisher desde DB

**Files:** Create `src/publisher.py`. Test: `tests/test_publisher.py`.

**Produces:**
```python
def filas_due(cx, account_id: int, ahora_iso: str) -> list[dict]
    # status='programado' AND aprobacion='aprobado' AND scheduled_datetime <= ahora_iso
def publicar_fila(cx, fila: dict, creds: dict, *, _ig=None) -> bool
    # _ig: módulo inyectable (default src.instagram). JSON list en imagen_url → publish_carousel,
    # si no → publish. kwargs creds={"user_id","token"} salvo gdlscene (None → globals).
    # OK → status='publicado', ig_media_id, publicado_en=ahora iso, error=NULL, True.
    # Excepción → error=str truncado 300 (sin tokens: usar el mismo criterio que api/routers/pruebas._fallo:
    # reemplazar creds no vacíos por "***"), False. Además notificar por Telegram vía approval.notificar_resolucion
    # ("📤 publicado" / "⚠️ error al publicar") — tolerante.
def ciclo(cx, *, ahora=None) -> int   # por marca activa: si account_creds(slug)["SHEET_ID"] → SKIP (Actions publica);
    # si faltan IG creds → skip con aviso; publica las due; devuelve nº publicadas
def main(once: bool = False) -> None  # loop cada int(os.getenv("PUBLISH_EVERY","300")) seg; --once un ciclo
```

- [ ] Tests (fake `_ig` con publish/publish_carousel registrando llamadas): marca sin SHEET_ID publica due (single y carrusel), setea publicado/ig_media_id/publicado_en; marca CON SHEET_ID se salta (0 publicadas aunque haya due); fila no vencida no sale en `filas_due`; excepción del ig fake → fila queda programada con `error` y sin token en el texto (creds con token "tok_secreto_999" → assert not in error); reintento: siguiente `ciclo` la vuelve a intentar; marca sin IG creds → skip sin tocar filas. `main(once=True)` corre un ciclo (monkeypatch `db.connect`). RED → implementar → GREEN.
- [ ] Commit: `feat(fase2): publisher local desde content_queue (marcas sin Sheet)`

---

### Task 7: Routers de cola y trabajos

**Files:** Create `api/routers/cola.py`, `api/routers/trabajos.py`; modify `api/app.py` (registrar ambos). Tests: `tests/test_api_cola.py`, `tests/test_api_trabajos.py`.

**Endpoints `cola.py`** (todas requieren membresía vía `marca_para`; editor basta):
- `GET /brands/{slug}/queue?desde&hasta&estado` → lista de `cola.listar` (campos: id, tipo, estado, caption, imagen_url, scheduled_datetime, tema_semilla, template, error, creado_por, aprobado_por).
- `GET /brands/{slug}/queue/{qid}` → `cola.detalle` (404 si no existe o no es de la marca — comparar `account_id`).
- `PATCH /brands/{slug}/queue/{qid}` body `{caption?, scheduled_datetime?}` → `editar_caption` / `reprogramar`; ValueError("choque") → 409 `{"error":"conflicto","campo":"scheduled_datetime"}`; ValueError("estado") → 422.
- `POST .../{qid}/aprobar` → `approval.aprobar(cx, qid, user_id=user["id"])` + `notificar_resolucion(cx, qid, f"✅ Aprobado desde el portal para {slot}")`; devuelve `{"ok":True,"scheduled_datetime":slot.isoformat()}`. Solo estado `pendiente` (si no, 422).
- `POST .../{qid}/rechazar` → `approval.rechazar(..., user_id=...)` + notificación "❌ Rechazado desde el portal". Solo `pendiente`.
- `POST .../{qid}/regenerar` → crea job `slideshow.regenerar` payload `{queue_id}` → 202 `{"job_id"}`. Solo tipo slideshow + estado pendiente|rechazado.
- `DELETE .../{qid}` → `cola.eliminar` → 204; ValueError → 422.
- `GET /brands/{slug}/slots/proximos?n=5` → `[iso, ...]` de `scheduler.slots_proximos_db` con la malla de la marca.

**Endpoints `trabajos.py`:**
- `POST /brands/{slug}/slideshows` body `{tema (min 3 chars), formato?, estilo?, fuentes?: list, n_slides: int 1..10 = 6, aspect?: str = "4:5", contexto?}` → valida contra el perfil (`marcas.cargar`): formato no habilitado → 422 campo `formato`; estilo inexistente → 422 campo `estilo`; crea job `slideshow.generar` → 202 `{"job_id"}`.
- `GET /brands/{slug}/jobs?estado` → jobs de la marca (id, tipo, estado, progreso, log, queue_id, created_at, finished_at).
- `GET /brands/{slug}/jobs/{jid}` → detalle (404 si de otra marca).
- `POST /brands/{slug}/jobs/{jid}/cancel` → `jobs.cancelar`; False → 422.
(Ambos routers ubican los jobs por marca — `jobs.account_id == fila de accounts` — nunca por id suelto.)

- [ ] Tests API (fixture `api_cliente`; sembrar marca pensionmas + filas/jobs a mano con `db.insert`): editor puede listar/aprobar/crear slideshow; usuario de otra marca → 403; qid de otra marca → 404; PATCH con choque → 409; aprobar fila no pendiente → 422; POST slideshows con formato no habilitado → 422 campo formato; POST slideshows crea job en cola con payload correcto y `creado_por` = user id; cancel de job corriendo → 422; slots/proximos devuelve n ISO strings. Monkeypatch `approval.notificar_resolucion` y `approval._siguiente_hueco`/scheduler donde haga falta para no tocar red. RED → implementar → GREEN.
- [ ] Commit: `feat(api): endpoints de cola, slots, slideshows y jobs`

---

### Task 8: Docs + humo

**Files:** Modify `docs/api_portal.md`.

- [ ] Documentar: endpoints nuevos; cómo correr worker y publisher (`python -m src.jobs.worker`, `python -m src.publisher`, `--once`, `WORKER_MAX_JOBS`, `PUBLISH_EVERY`); la regla "marca con SHEET_ID publica por Actions, sin SHEET_ID publica el publisher local"; estados de la cola; que regenerar descarta la fila vieja y crea una nueva.
- [ ] Humo: `python -c "from api.app import app; print(len(app.routes))"`; suite completa + ruff en archivos tocados.
- [ ] Commit: `docs(fase2): cola, publisher y jobs en api_portal`

## Auto-revisión
Spec §4: cola fuente de verdad (T1,T3,T4,T6), endpoints (T7), slots (T2,T7), aprobar front+TG convergen y el bot refleja (T3,T7). §5: tabla jobs, worker atómico 1/marca + tope global, huérfanos, handlers slideshow con progreso, API 202+polling (T5,T7). Sin placeholders; firmas consistentes (`cola.estado_de/listar/detalle/reprogramar/editar_caption/eliminar`; `jobs.crear/tomar/progresar/terminar/cancelar/rescatar_huerfanos`; `scheduler.next_free_slot_db/slots_proximos_db`; `approval.notificar_resolucion`). Fuera de fase: sourcing/rss handlers, purga de sesiones, presets (Fase 3).
