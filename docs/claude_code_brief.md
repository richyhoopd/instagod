# Brief de desarrollo para Claude Code — @gdlscene: DB de bandas + ingesta + GUI de curación

> Pega esto como primer mensaje en Claude Code (o déjalo en el repo como referencia).
> Está escrito para que Claude Code, abriendo este repositorio, entienda el contexto,
> respete lo que ya funciona y construya por fases. **Fuera de alcance por ahora: Reels y
> TikTok / video.** Solo trabajamos data, clasificación, anuncios y la GUI de curación.

---

## 1. Rol y contexto

Eres un ingeniero senior de Python trabajando en `instagod`, el bot de la cuenta de Instagram
**@gdlscene**: sátira estilo *The Onion* sobre la escena musical underground de Guadalajara.

El pipeline actual (NO lo rompas, ver §3) ya funciona así:
- **Fuente de trabajo:** un Google Sheet con filas `pending` (`banda`, `integrante`, `rol`,
  `tema_semilla`, `foto_url`, `foto_inset_url`, `status`, `scheduled_datetime`).
- **`generate.py`** (Proceso A): lee filas pending → genera caption + imagen → aprueba por
  Telegram → sube a Cloudinary → asigna horario → marca el Sheet.
- **`src/caption.py`**: genera el titular con DeepSeek (o Claude). Aquí vive el 70% del valor;
  el prompt y los few-shots son sagrados, no los toques sin pedir permiso.
- **`src/compose.py`**: Playwright + Jinja2 (`templates/*.html`) compone el PNG.
- **`src/telegram_bot.py`**, **`src/host.py`** (Cloudinary), **`src/instagram.py`** (IG Graph),
  **`src/scheduler.py`** (slots), **`src/sheets.py`** (Google Sheets), **`config.py`** (único
  punto de acceso a variables de entorno).

Lee `docs/roadmap_datos_y_contenido.md` para el diseño completo y el esquema de DB. Este brief
es la versión accionable de ese roadmap, sin las fases de video.

---

## 2. Objetivo

Convertir "las bandas/artistas que sigo en Instagram" en una **base de datos relacional curada**
que alimente sola al Proceso A, y darme una **interfaz web mínima local** para revisar y corregir
esa base a mano (nombres, roles, qué foto sirve, eventos).

Resultado esperado al terminar: escrapeo una sesión → la DB se llena y clasifica → abro la GUI,
corrijo lo que haga falta y marco fotos buenas → las filas `pending` aparecen en el Sheet → el
Proceso A sigue igual que hoy.

---

## 3. Principios de trabajo (innegociables)

1. **No rompas el Proceso A.** `generate.py` y los módulos de publicación deben seguir corriendo
   igual. Lo nuevo *alimenta* el Sheet, no lo reemplaza.
2. **Incremental y por fases (§5).** Una fase a la vez, cada una con su criterio de aceptación.
   No empieces la siguiente sin que la anterior corra y yo la apruebe.
3. **`config.py` es el único acceso a env.** Cualquier variable nueva se agrega ahí y a
   `.env.example`, nunca `os.environ` suelto en módulos.
4. **Convenciones del repo:** Python con docstrings y comentarios **en español**, type hints,
   `from __future__ import annotations`. Imita el estilo de los módulos existentes en `src/`.
5. **Sin dependencias pesadas innecesarias.** Reusa lo que ya está (jinja2, requests,
   python-dotenv). Para la DB usa **SQLite con la stdlib `sqlite3`** (o SQLModel/sqlite si lo
   justificas). Agrega dependencias nuevas a `requirements.txt` con comentario de para qué.
6. **Pide antes de cualquier cosa destructiva** (borrar datos, migraciones que tiren tablas,
   tocar `caption.py`/prompts). Antes de un cambio grande, propón un plan corto y espera mi OK.
7. **Cada módulo nuevo trae:** un `if __name__ == "__main__"` de prueba aislada y, donde aplique,
   un test mínimo. Datos reales nunca en el repo (fotos, tokens → fuera de git, ver `.gitignore`).

---

## 4. Arquitectura objetivo (sin video)

```
[instaloader / instagram-posts-scraper]  →  descarga perfil, posts, fotos, captions
                 │
                 ▼
        [clasificador de posts]  →  foto de integrantes | flyer/fecha | descarte
          (caras + nitidez + OCR + keywords del caption)
                 │
        ┌────────┴─────────┐
        ▼                  ▼
   tabla photos        tabla events  ←─ DeepSeek parsea {fecha, lugar, ciudad}
        │                  │
        │            [plantilla anuncio]
        ▼                  │
   tabla bands  ←── [spotipy: popularity, followers, géneros, releases]
        │
        ▼
   [GUI web de curación]  ←── YO corrijo nombres/roles, marco fotos usables, edito eventos
        │
        ▼
   tabla content_queue  →  [sync DB → Google Sheet]  →  Proceso A (sin cambios)
```

Esquema SQLite (detallado en el roadmap, §1): tablas `bands`, `members`, `photos`, `events`,
`content_queue`. La fuente de verdad pasa a ser la DB; el Sheet queda como UI de aprobación final
del caption + cola de publicación.

---

## 5. Plan por fases (con criterios de aceptación)

**Fase 1 — DB + sync DB→Sheet.**
Crea `src/db.py`: esquema SQLite (migración idempotente, función de init), y CRUD básico.
Crea `src/sync_sheet.py`: toma filas de `content_queue` con status `listo` y las escribe como
`pending` en el Sheet (reusando `src/sheets.py`).
*Aceptación:* puedo insertar una banda + foto a mano en la DB, correr el sync, y la fila aparece
en el Sheet lista para que `generate.py` la tome. Proceso A intacto.

**Fase 2 — Ingesta de Instagram.**
Crea `src/ingest_ig.py` usando `instaloader` (login con cuenta secundaria desde `config.py`,
con delays y límite de posts configurable). Baja perfil (bio, followers, link externo) y los
últimos N posts (imagen, caption, fecha) de cada `ig_handle` marcado en `bands`. Guarda imágenes
fuera de git y registra en `photos` (sin clasificar aún: solo path, fecha, caption_original).
*Aceptación:* corro `python -m src.ingest_ig` sobre 2-3 bandas y veo perfiles + fotos en la DB.

**Fase 3 — Clasificación de fotos.**
Crea `src/classify.py`: por cada foto calcula `faces_count` (mediapipe o face_recognition/OpenCV),
`nitidez` (varianza del Laplaciano), `es_grupal`, y decide `usable_meme` (heurística: ≥1 cara
clara y nitidez sobre umbral). Distingue flyers (mucho texto / OCR con tesseract + pocas caras) y
los manda a `events`.
*Aceptación:* tras clasificar, las fotos buenas quedan `usable_meme=true` y los flyers caen en
`events`; el sync solo manda fotos usables al Sheet.

**Fase 4 — Enriquecimiento Spotify.**
Crea `src/enrich_spotify.py` con `spotipy`: matchea banda por nombre (confirma con link de bio si
existe), guarda `popularity`, `followers_spotify`, `generos`, top tracks, y detecta releases nuevos.
*Aceptación:* las bandas tienen popularity y géneros; puedo ordenar por popularity en la GUI.

**Fase 5 — Eventos / anuncios.**
Crea `src/parse_events.py`: pasa caption + OCR del flyer a DeepSeek y obtiene JSON estructurado
del evento. Crea `templates/anuncio.html` y la rama de generación de anuncios (informativo, con
sello @gdlscene, **fecha/lugar fieles, nunca satirizados**). Extiende `scheduler.py` con un modo
"urgente" que publique antes de `fecha_evento`.
*Aceptación:* un flyer scrapeado se convierte en un anuncio bien fechado, aprobable por Telegram.

> La GUI (§6) se construye en paralelo a partir de la Fase 1, porque la necesito para curar desde
> que hay datos. Constrúyela apenas exista la DB y ve agregándole vistas conforme avanzan las fases.

---

## 6. Interfaz web de curación (entregable clave)

App **local** (corre en mi máquina, sin auth, solo `localhost`), mínima pero usable. Stack
sugerido: **FastAPI + Jinja2 + HTMX** (o Flask si lo prefieres) para edición inline sin SPA.
Carpeta `web/` con `app.py` y `templates/`. Sirve thumbnails de las fotos desde disco.

Vistas y acciones mínimas:
- **Bandas:** tabla editable inline — `nombre`, `ig_handle`, `spotify_id`, `generos`, `popularity`,
  `prioridad`, `activa`. Ordenable por popularity/prioridad. Botón "re-enriquecer Spotify" por fila.
- **Banda → detalle:** miembros (agregar/editar `nombre`, `rol`, `ig_handle`, foto principal) y
  **galería de fotos** con thumbnail, `faces_count`, `nitidez`, toggle `usable_meme`, selector de
  `member`, y marca `usada`. Esta es la pantalla más importante: curar fotos visualmente.
- **Eventos:** lista editable — `fecha_evento`, `lugar`, `ciudad`, `status`; ver el flyer.
- **Cola (`content_queue`):** ver qué está por sincronizar al Sheet; botón "enviar al Sheet".

Objetivo de la GUI: que en 5 minutos pueda corregir nombres mal escritos, descartar fotos malas,
arreglar un rol y aprobar eventos, sin tocar SQL ni el Sheet a mano.
*Aceptación:* abro `uvicorn web.app:app`, navego, edito un nombre y una foto, recargo y el cambio
persiste en SQLite.

---

## 7. Restricciones y cuidado

- **ToS de Meta:** el scraping va contra los términos. Usa cuenta secundaria (desde `config.py`),
  delays aleatorios y límites bajos; ingesta puntual, no crawler 24/7. No publiques credenciales.
- **Spotify:** popularity/followers/géneros OK; reproducciones y related-artists NO existen por API
  oficial; no uses su data para entrenar modelos.
- **Personas reales:** mantén el guardarraíl actual de `caption.py` (nada de acusaciones creíbles
  de delitos, ni temas sensibles). Los anuncios con fecha deben ser **fieles**, no satíricos.
- **Aprobación humana:** todo lo que se publique (memes y anuncios) pasa por Telegram antes de IG.

---

## 8. Cómo empezar

1. Recorre el repo y confirma que entiendes el Proceso A y `config.py`. Resume en 5 líneas qué hace
   cada módulo de `src/` para verificar tu comprensión.
2. Propón el DDL exacto de SQLite (las 5 tablas) y espera mi OK.
3. Implementa **solo la Fase 1** + el esqueleto de la GUI (vista de Bandas). Muéstrame cómo correrlo.
4. No avances a la Fase 2 hasta que yo apruebe.

Cuando tengas dudas de producto (qué umbral de nitidez, cuántos posts por banda, etc.), pregunta
con opciones concretas en lugar de asumir.
