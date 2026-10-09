# 2026-10-09 — Fuentes de contenido por marca (texto → campos de plantilla)

Estado: borrador para revisión de Ricardo.
Subproyecto 2 de 3. Los otros: 1) editor escena v2
(`2026-10-06-editor-escena-v2-design.md`), 3) compositor de video sobre escena
(`2026-10-09-compositor-video-escena-design.md`).

## Problema

- Ya existen fuentes de texto (`kind='info'`): `PROVIDERS_INFO = ("rss","newsapi","reddit")`
  (`src/fuentes.py:20-23`). Alimentan `topic_suggestions` (`src/schema.sql:433-445`).
- Pero el texto de la fuente **no llega a los campos de la plantilla**:
  - `generador.generar_campos(contrato, marca, tema, entidad, rechazados, intentos=3)`
    solo recibe `tema` (`src/plantillas/generador.py:78`); el prompt usa voz,
    `caption_extra`, entidad y TEMA (`generador.py:57-75`).
  - `plan_generar` pasa solo el título del tema (`src/jobs/handlers.py:585-640`).
  - `topic_suggestions.resumen` (hasta `_HISTORIA_MAX=6000` en Reddit,
    `src/topics.py:26`) se pierde.
- Reddit está a medias:
  - backend sí: `fetch_reddit` (`src/topics.py:252-327`), handler
    `sourcing_reddit_fetch` (`handlers.py:262-295`), cron (`src/jobs/worker.py:27-28`).
  - `POST /sources/{sid}/run` responde 422 para reddit: falta en
    `_JOB_TIPO_POR_PROVIDER` (`api/routers/fuentes_api.py:38-42`, `:183-192`).
  - `estado_fuentes` no lista reddit (`fuentes_api.py:108-123`).
  - El portal no lo ofrece: `PROVIDERS.info = ["rss","newsapi"]`
    (`frontend/app/b/[slug]/settings/_components/fuente-dialog.tsx:34-37`);
    `frontend/lib/fuentes.ts` no tiene etiqueta para reddit, ig_seguidos ni x.
- X: solo publicación (`src/x_twitter.py:37-102`, tweepy OAuth1). Cero lectura.
  `_ACCOUNT_CRED_KEYS` no tiene llaves de X ni de Reddit (`config.py:400-407`).
- IA con prompt por marca: no existe como fuente. Lo más cercano es
  `marca.prompts.caption_extra` (`src/marcas.py:55`) y los temas de `plan_temas`.

## Objetivo

- Cada marca configura N fuentes de texto (Reddit por subreddit, IA con prompt, RSS, X).
- Cada fuente produce **material** (título + cuerpo + atribución) en `topic_suggestions`.
- Al crear un post desde un tema, el material se usa para llenar los `campo` del
  `contrato_json` de la plantilla, no solo el título.

## Decisiones

| Decisión | Elección propuesta | Por qué |
|---|---|---|
| Dónde vive una fuente | `brand_sources` `kind='info'` (existente) | Ya tiene `config_json`, `activa`, `orden`, `ultimo_run`, `ultimo_error` (`schema.sql:418-431`) |
| Dónde vive el material | `topic_suggestions` + columnas nuevas nullable | Ya tiene dedupe `(account_id,url)` (`schema.sql:447`) y lo listan `/topics` y el plan |
| Fuente IA | provider `ia_prompt`, sin URL real → url sintética `ia://<source_id>/<hash>` | Reusa el UNIQUE sin cambiar la tabla |
| X | provider `x`, API v2 oficial, apagado por default | Sin scraping; costo y tier sin verificar |
| Reddit | se queda en RSS público (como hoy) | OAuth exige aprobación (docstring `topics.py:261-263`) |
| Texto → campos | parámetro opcional `material` en `generar_campos` | Fix mínimo; sin `material` el comportamiento queda igual |
| `plan_topics.fuente` | NO tocar el CHECK `prompt|noticia|manual` (`schema.sql:470-486`) | Cambiarlo en SQLite exige reconstruir la tabla; se usa `noticia` + `topic_suggestion_id` |

## 1. Modelo de datos (migración no destructiva)

Solo `ALTER TABLE ... ADD COLUMN` en `src/db.py`, como las migraciones existentes.

`topic_suggestions`, columnas nuevas (todas nullable):

| Columna | Tipo | Uso |
|---|---|---|
| `source_id` | INTEGER | qué `brand_sources` lo trajo (hoy solo hay `fuente` texto) |
| `autor` | TEXT | u/…, @…, autor RSS; para atribución |
| `licencia` | TEXT | `desconocida` por default; ver riesgos |
| `meta_json` | TEXT | extra por provider (subreddit, tweet id, prompt usado, modelo) |

- `brand_sources.config_json` por provider nuevo:
  - `ia_prompt`: `{prompt, n_por_corrida, cada_horas, modelo?}`.
  - `x`: `{consultas: [...], cuentas: [...], cada_horas}`.
- Validación en `fuentes.validar_config` (`src/fuentes.py:51-100`), mismo patrón
  que reddit (`:90-100`). `cada_horas` ≥ 6 ya se aplica (`fuentes.py:43-48`).
- Llaves de X: agregar a `_ACCOUNT_CRED_KEYS` (`config.py:400-407`) para que se
  resuelvan por marca vía `brand_secrets` (`config.py:439-455`). Sin fallback a
  env global salvo gdlscene, igual que hoy.

## 2. API

Todo bajo `/brands/{slug}` (`fuentes_api.py:17`), `marca_para(..., minimo=manager)`
para escribir (`api/deps.py:36-44`).

| Cambio | Archivo | Detalle |
|---|---|---|
| Reddit en run manual | `fuentes_api.py:38-42` | agregar `reddit → sourcing.reddit_fetch` |
| `ia_prompt` y `x` en run manual | idem | `sourcing.ia_prompt`, `sourcing.x_fetch` |
| `estado_fuentes` | `fuentes_api.py:108-123` | agregar reddit, ia_prompt, x con motivo (`_MOTIVO_KEY`, `:103-105`) |
| `GET /topics` | `fuentes_api.py:293` | exponer `source_id`, `autor`, `licencia` |
| `POST /posts` | `api/routers/posts.py:15-37` | `NuevoPost.topic_id?` opcional |
| `POST /topics/{tid}/probar` (nuevo) | — | dry-run: llena campos de una plantilla con el material, sin render ni cola |

## 3. Jobs

Patrón existente: handler en `src/jobs/handlers.py::HANDLERS` (`:833-855`), sella
`ultimo_run` en `finally` (como `sourcing_rss_fetch`, `:205`).

| Job | Qué hace | Notas |
|---|---|---|
| `sourcing.reddit_fetch` | ya existe (`handlers.py:262-295`) | solo cableado manual + UI |
| `sourcing.ia_prompt` (nuevo) | LLM con `prompt` de la fuente + voz de marca → N temas con cuerpo | `topics.guardar` (`topics.py:330`) con url sintética |
| `sourcing.x_fetch` (nuevo) | API v2 → posts recientes por consulta/cuenta | sin llaves → `ultimo_error`, no lanza |
| `post.generar` | pasa `topic_id` → carga `resumen` → `material` | `handlers.py:174-191`, `src/posts.py:39-75` |
| `plan.generar` | si `plan_topics.topic_suggestion_id`, pasa material | `handlers.py:585-640` |

- Cron: `encolar_fuentes_vencidas` (`worker.py:58-120`) usa `_TIPO_POR_PROVIDER`
  (`worker.py:27-28`); agregar `ia_prompt` y `x`.
- Aislamiento de cola: una corrida por cuenta ya lo garantiza `tomar`
  (`src/jobs/__init__.py:52-97`). X no entra a `TIPOS_IG` (`:48`).
- Espera entre subreddits: `_ESPERA_ENTRE_SUBREDDITS = 8.0` (`handlers.py:51`);
  el comentario reporta 429 en el segundo subreddit en prueba en vivo.

### Texto → campos

- `generar_campos(..., material: dict | None = None)`.
- `material = {titulo, cuerpo, autor, url}`; `cuerpo` recortado a un tope (decisión abierta).
- Prompt: bloque `MATERIAL (no inventes datos fuera de esto)` antes del contrato.
- Campos `texto`/`texto_largo`/`lista` (`contrato.py:25-26`) salen del material;
  `imagen` sigue por `resolver_imagen`.
- Si el contrato declara un campo `fuente` o `credito`, se llena determinista con
  `autor` + dominio de `url`, sin LLM.
- `validar_campos` (`contrato.py:255`) sin cambios.

## 4. Frontend

Base real: `frontend/app/b/[slug]/` (el spec v1 citaba `app/(portal)/[marca]/…`, ruta que no existe).

- `settings/_components/fuente-dialog.tsx:34-37`: `info` += `reddit`, `ia_prompt`, `x`.
  - Reddit: lista de subreddits + `min_palabras` (rango `20..400`, `fuentes.py:90-100`).
  - IA: textarea de prompt + n por corrida.
  - X: consultas/cuentas; aviso de costo si la marca no tiene llaves.
- `frontend/lib/fuentes.ts`: etiquetas para reddit, ig_seguidos, ia_prompt, x;
  quitar el comentario viejo de "no expuesto en este build" (`:1-4`).
- `create/_components/paso-tema.tsx`: mostrar cuerpo recortado + autor; al elegir,
  manda `topic_id` en `POST /posts`.
- `_components/temas-panel.tsx`: filtro por fuente.

## 5. Aislamiento por marca

- Fuentes, temas y llaves se filtran por `account_id`; `marca_para` en cada endpoint.
- `topic_suggestions` UNIQUE `(account_id,url)` (`schema.sql:447`): el mismo link en dos marcas son dos filas.
- La fuente IA usa solo `marca.voz`/`marca.prompts` de su marca.
- Las llaves de X por `brand_secrets`; una marca sin llaves no hereda las de otra.
- Prueba explícita: marca A no ve ni corre fuentes de B (404, no 403).

## 6. Riesgos

| Riesgo | Mitigación |
|---|---|
| Reddit: el RSS público no es API oficial; 429 y posible bloqueo (`topics.py:252-327`, `handlers.py:51`) | `cada_horas ≥ 6`, reintentos `(0,3,9)` (`topics.py:28`), espera entre subreddits; si cae, `ultimo_error` visible |
| Reddit: ToS sobre uso de contenido de usuarios | sin verificar; ver decisión abierta |
| X: API v2 de lectura es de pago; precio y límites | sin verificar; apagado por default, llaves por marca |
| X: scraping sin API | fuera de alcance; no se hace |
| Derechos de terceros: publicar texto ajeno en un post | el material se reescribe; campo `credito` determinista; `licencia='desconocida'` bloquea texto literal (decisión abierta) |
| IA inventa hechos | la fuente IA queda marcada `fuente='ia'` (columna TEXT sin CHECK, `schema.sql:439`); nunca genera URLs (misma regla que `plan_temas.py:9-10,106-126`) |
| Costo de LLM por corrida IA y por llenado con material | tope por marca (decisión abierta); sin cifra hoy |
| SSRF en RSS | ya cubierto por `topics.url_segura` (`topics.py:61`) |
| Inyección de prompt desde texto de Reddit/X | material va en bloque delimitado; salida pasa por `validar_campos` |

## 7. Pruebas

- Unit `fuentes.validar_config`: `ia_prompt` y `x` válidos/ inválidos.
- Unit `generar_campos` con `material` (LLM mockeado): el prompt contiene el
  bloque MATERIAL; sin `material`, prompt idéntico al actual (regresión).
- Unit `topics.guardar` con url sintética `ia://`: dedupe funciona.
- Unit `sourcing.x_fetch` sin llaves → `ultimo_error`, sin excepción.
- API: `POST /sources/{sid}/run` para reddit → 202 (hoy 422).
- API: aislamiento A/B en `/sources`, `/topics`, `/posts` con `topic_id` ajeno → 404.
- Migración: DB vieja + `db.init` → columnas nuevas, filas intactas.
- Frontend: vitest del diálogo con los 3 providers nuevos.
- Ninguna prueba llama Reddit, X ni LLM reales (fixtures).
- Verificación manual en staging de una marca, no en gdlscene prod.

## Fuera de alcance

- Mezcla por porcentaje entre fuentes (ya fuera de alcance en
  `2026-08-28-planes-contenido-masivo-design.md:181`).
- Reddit OAuth / Responsible Builder Policy.
- Lectura de X sin API oficial.
- Fuentes de imagen/video (ya existen: `fuentes.py:16-19`).
- Video a partir del material: subproyecto 3.

## Decisiones abiertas para Ricardo

1. **¿X entra en este subproyecto?** Default: sí en modelo/UI, apagado; el job solo corre con llaves por marca.
2. **Tier/costo de X API v2.** Sin verificar. Default: no contratar hasta tener una marca que lo pida.
3. **Tope de cuerpo que entra al prompt.** Default: reusar `_RESUMEN_MAX=500` (`topics.py:23`) en posts; cuerpo completo solo en video.
4. **Texto de terceros literal vs reescrito.** Default: siempre reescrito por LLM + campo `credito`; nunca literal.
5. **Atribución obligatoria.** Default: si el contrato tiene `credito`, se llena siempre; si no, va en el caption.
6. **Tope de corridas IA por marca/día.** Default: `n_por_corrida ≤ 10`, `cada_horas ≥ 6`; cifra final la pones tú.
7. **Valor de `plan_topics.fuente` para Reddit/X/IA.** Default: `noticia` + `topic_suggestion_id`, sin tocar el CHECK.
8. **Modelo LLM de la fuente IA.** Default: DeepSeek (el default actual), Claude opcional por fuente.
9. **Reddit ToS para uso comercial del contenido.** Sin verificar. Default: solo marcas propias hasta revisarlo.
