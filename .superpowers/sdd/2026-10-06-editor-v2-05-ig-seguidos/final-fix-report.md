# Final fix pass — plan 5 (I1, I2)

## I1 — importar_seguidos ya no usa _listar_con_pool
- `src/assets/ig_seguidos.py::importar_seguidos`: bucle propio con `SesionRotatoria`; llama `ingest_ig.fetch_profile` + `import_followees.listar_following`.
- Quema/rota solo si `_debe_quemar` (IngestRateLimited o HTTPError 401/403/429); reutiliza la funcion existente.
- 404 o perfil vacio (LookupError) -> `LookupError("la semilla @x no existe en Instagram")`, sin quemar. 5xx -> HTTPError propagado, sin quemar. Pool agotado -> IngestRateLimited.
- Concern: el 400 `checkpoint_required` ya no quema (antes si, en `_listar_con_pool`); falla el job con el HTTPError. Decision explicita pendiente si se quiere quemar solo cuando el cuerpo trae "checkpoint".
- gdlscene intacto: `git diff master --stat -- src/import_followees.py src/ingest_ig.py src/ig_accounts.py` vacio.

## I2 — tope por job + reencolado
- `MAX_CUENTAS_POR_JOB = 10` en `ig_seguidos`; `ingerir` toma las activas ordenadas por `scraped_at` (NULL primero, luego mas viejas; desempate por handle) y devuelve `pendientes`.
- Cuentas que fallan sin quemar se sellan (`scraped_at`) para no quedar como "la mas vieja" eternamente y bloquear la cadena.
- Handler `ig.ingerir`: si `pendientes` y no `cortado`, `jobs.crear("ig.ingerir", mismo account_id, {"por_cuenta"}, creado_por)`; resultado incluye `reencolado`. Con pool cortado no reencola (giraria en vacio).
- Orden: `jobs.tomar` hace `ORDER BY id`; el job nuevo tiene id mayor, queda detras de lo ya encolado. Carril IG intacto (probado: mientras corre un IG, `tomar` no entrega otro IG).
- Progreso: porcentaje sobre el lote (no el total) y mensaje final en el job con el id de continuacion.

## Tests
- Nuevos en `tests/test_ig_seguidos.py`: semilla 404/500/502 sin quema, 5xx a media paginacion, perfil vacio, 401/403/429 quema y rota, pool agotado, no usa `_listar_con_pool`, tope + pendientes + progreso del lote, orden oldest-first, sello en error, reencolado con mismos parametros, no reencola sin resto / con corte, orden de cola y carril IG.
- Fixture `following_falso` reescrito (ya no parchea `_listar_con_pool`); asserts de `ingerir` actualizados con `pendientes`.
- pytest -m "not lento": solo las 5 fallas preexistentes (ig_insights 1, scraped_mark 3, segmentos_web 1). ruff: solo 3 preexistentes (video_render/video_script).
