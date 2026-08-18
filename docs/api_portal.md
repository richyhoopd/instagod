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
