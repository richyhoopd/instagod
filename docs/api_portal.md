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
