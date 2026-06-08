# Pool de cuentas scraper de IG con rotación automática

**Fecha:** 2026-06-08
**Estado:** Aprobado

## Objetivo

Hoy `ingest_ig.get_session()` usa UNA cookie (`IG_SCRAPER_SESSIONID` + `IG_SCRAPER_UA`
del `.env`). Cuando IG la soft-bloquea (401/429 en el feed, ~33 llamadas/ventana)
la corrida se corta. Queremos un **pool de cuentas scraper** que rote a otra sana
cuando la activa se quema, y que recuerde el reposo entre corridas.

Alcance: SOLO cuentas *scraper* de lectura. La cuenta de publicación
(`IG_ACCESS_TOKEN` de @gdlscene) no se toca.

## 1. Registro — `data/ig_accounts.json` (gitignored)

```json
[
  {"label": "tulana",  "sessionid": "...", "ua": "Mozilla/5.0 ...", "quemada_hasta": null},
  {"label": "cuenta2", "sessionid": "...", "ua": "...",            "quemada_hasta": "2026-06-08T22:00:00"}
]
```
- `quemada_hasta`: ISO 8601 hasta cuándo está en reposo; `null`/pasado = sana.
  Lo escribe el sistema; el usuario solo agrega cuentas con `sessionid`+`ua`.
- Va en `.gitignore` (contiene cookies de sesión = secretos).

## 2. Gestor del pool — `src/ig_accounts.py` (módulo nuevo)

- `cargar(path=None) -> list[dict]`: lee el JSON. Si no existe, arma un pool de 1
  con `config.IG_SCRAPER_SESSIONID`/`IG_SCRAPER_UA` (label "env") → compatibilidad
  total con el setup actual. Si tampoco hay cookie en `.env`, lista vacía.
- `siguiente_sana(cuentas, ahora=None) -> dict | None`: primera cuenta con
  `quemada_hasta` nulo o ya vencido (compara ISO). `None` si todas en reposo.
- `marcar_quemada(label, horas=None, path=None, ahora=None) -> None`: setea
  `quemada_hasta = ahora + horas` (default `config.SCRAPER_COOLDOWN_HORAS=12`) y
  reescribe el JSON de forma ATÓMICA (tmp + replace). Persiste entre corridas.
- `ahora` inyectable para tests (sin tocar reloj real).

## 3. Config — `config.py`

- `SCRAPER_COOLDOWN_HORAS = int(_get("SCRAPER_COOLDOWN_HORAS", "12"))`.
- `IG_ACCOUNTS_PATH = _get("IG_ACCOUNTS_PATH", "./data/ig_accounts.json")` + helper
  `resolve_ig_accounts_path()`.

## 4. Rotación en `src/ingest_ig.py`

- `get_session(cuenta: dict) -> creq.Session`: recibe la cuenta (sessionid+ua) en
  vez de leer `config`. Mantiene el resto igual (impersonate, x-ig-app-id).
- **Proveedor de sesión rotatorio** usado por los loops de `ingest()` y
  `novedades()`: arranca con `siguiente_sana()`; expone la cuenta activa y su
  sesión. Al recibir `IngestRateLimited` en una banda:
  1. `marcar_quemada(cuenta_activa)` (12h).
  2. `siguiente_sana()` → si hay otra, reconstruye la sesión y **reintenta la
     MISMA banda** con la cuenta nueva; sigue de corrido.
  3. Si no hay otra (`None`) → **para la corrida** (pool agotado). Este es el
     nuevo circuit breaker; reemplaza al de "3 strikes" (`NOVEDADES_MAX_BLOQUEOS`
     deja de usarse en novedades — un 401 de feed = cuenta quemada, sin contador).
- Un 401/429 marca la cuenta quemada inmediatamente (el soft-block es un muro
  duro, no intermitente: en el incidente fueron 33 OK y luego TODO 401).
- Para evitar bucle infinito si una banda específica siempre da 401 con toda
  cuenta: cada banda se reintenta a lo más una vez por cuenta sana disponible.

## 5. Reporte (orquestador `src/novedades.py`)

- El resumen de Telegram distingue "pool agotado" de "terminó normal": si se cortó
  por pool agotado, lo dice ("todas las cuentas en reposo; retomo cuando enfríen")
  y reporta pendientes. Las bandas sin revisar conservan su `scraped_at` viejo →
  entran primero la próxima corrida.

## 6. Capacidad

- `NOVEDADES_BANDAS_POR_CORRIDA` sigue configurable; con N cuentas sanas el
  presupuesto efectivo es ~33×N llamadas de feed, así que el tope se puede subir
  conforme se agreguen cuentas. No se auto-escala (YAGNI); queda como knob.

## 7. Tests (`tests/test_ig_accounts.py` + extensión de novedades)

Sin red, reloj inyectado:
- `cargar` lee JSON; sin archivo cae al `.env` (pool de 1); sin nada → vacío.
- `siguiente_sana` salta quemadas, respeta vencimiento del cooldown, orden estable.
- `marcar_quemada` escribe `quemada_hasta` correcto y persiste (re-`cargar` lo ve).
- Rotación en `novedades`: cuenta activa da 401 → se marca quemada, rota a la
  siguiente y la banda se procesa con la nueva; pool agotado → corrida para con
  `cortado_por_bloqueo=True`.
- Fallback: sin JSON y con cookie en `.env`, `novedades` corre con esa única cuenta.

## Fuera de alcance

- Cuenta de publicación (`IG_ACCESS_TOKEN`).
- Login por script para generar cookies (sigue siendo manual desde el navegador,
  como hoy — login por script quema cuentas; ver memoria del proyecto).
- Rotación de proxies/IP (solo identidades de sesión).
