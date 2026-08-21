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
