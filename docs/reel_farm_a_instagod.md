# Reel.farm → instagod: investigación a fondo y plan de integración nativa

> **Objetivo del documento.** Entender exactamente cómo funciona reel.farm, hacerle ingeniería inversa a su producto (usando su propia API pública como "plano"), y trazar el plan para replicar esa capacidad **de forma nativa dentro de instagod** — reutilizando lo que ya tienes — para empezar a generar reels, carruseles y mejor contenido en Instagram, video y TikTok.
>
> Entregable de esta sesión: **solo documento técnico + pasos de arranque**. No se escribió código todavía.

---

## 0. Conclusión de arriba (TL;DR)

1. **reel.farm no es magia: es exactamente tu misma arquitectura, un nivel más arriba.** Ellos generan *slideshows faceless* (carruseles de imágenes con texto grande encima) con un LLM, los rinden a imagen, opcionalmente los exportan a `.mp4`, y los publican/agendan a TikTok por cron. Tú ya haces el 80% de eso en instagod: guion con LLM (`caption.py`), render HTML/CSS→PNG con Playwright (`compose.py` / `render_card`), hosting público (Cloudinary `host.py`), aprobación humana (Telegram), cola + agenda (Sheet + `scheduler.py`) y publicación 2-pasos a Instagram — **incluido `publish_carousel()` que ya tienes funcionando**.

2. **La pista más reveladora del reverse engineering:** su plan Enterprise deja "traer tu propia Anthropic API key + Skill.md". Eso confirma que el cerebro creativo de reel.farm es **un agente Claude guiado por un skill** (un prompt/estructura fija) — precisamente el patrón que tú ya usas con DeepSeek/Claude en `caption.py`. No hay un modelo propietario de video; hay **buenos prompts + una plantilla de slides + plomería de publicación**.

3. **Lo que te falta para igualarlo es acotado y conocido:** (a) un generador de *guion de slides* (hook + N slides + CTA) análogo a `caption.py`; (b) una o dos plantillas HTML de "slide" estilo TikTok; (c) ensamblado a video con **ffmpeg** para los Reels de video; (d) publicación de **Reels** (`media_type=REELS`) extendiendo `instagram.py`; y (e) un módulo `tiktok.py` con la **Content Posting API** (foto-carrusel y video), análogo a tus `facebook.py` / `x_twitter.py`.

4. **Tu ventaja sobre reel.farm:** ellos sacan imágenes genéricas de Pinterest/stock ("faceless"). Tú ya tienes un **banco de fotos reales por banda/persona** (SQLite + reconocimiento facial + clasificación de nitidez/flyers). Tu contenido puede ser *no-faceless*, real y local — mucho más difícil de replicar y más valioso para tu nicho (escena musical de Guadalajara).

---

## 1. Qué es reel.farm y cómo funciona

### 1.1 El producto

reel.farm (dominio de marketing en `reelfarm.org`, app y API en `reel.farm`) es una plataforma de **automatización de contenido faceless para TikTok**, con el lema "videos automáticos que mandan tráfico a tu web/app/negocio". Su formato estrella **no es video tradicional, sino el *slideshow*: un carrusel de imágenes** con texto grande encima, estilo listicle ("5 hábitos…", "7 formas de…"). El pitch textual es "slideshows de TikTok con IA que no se sienten hechos con IA".

El flujo de usuario son tres pasos: (1) creas una *automatización* (defines formato, tema/hook y horario), (2) conectas tu cuenta de TikTok por OAuth, (3) "set & forget": el sistema genera y publica contenido original a diario, solo.

### 1.2 Qué genera, exactamente

- **Slideshows (lo central):** toma un tema en lenguaje natural, el LLM lo parte en *slides*, cada slide recibe una imagen de fondo + texto en negritas estilo meme/viral, con transiciones y música automáticas. La imagen de cada slide se **sourcea automáticamente desde Pinterest** (búsqueda por query).
- **Export a video:** el mismo slideshow se puede exportar como `.mp4` (parámetro `export_as_video`, con `duration` por slide). Es decir: el slideshow es la primitiva; el "reel de video" es el mismo slideshow renderizado a video.
- **Hooks / ganchos:** un *Hook Generator* que, dado el brief de marca (mín. 40 caracteres), devuelve varias líneas de apertura "conversacionales" en 4–7 segundos.
- **UGC / avatares (secundario):** 50+ avatares IA prehechos y avatares custom por descripción de texto (con topes de imágenes/videos por plan). Es un añadido; el core es el slideshow faceless.
- **Analítica:** vistas, likes, shares, comentarios, bookmarks por post.
- **Biblioteca de inspiración:** un catálogo consultable de perfiles/slideshows reales de TikTok por nicho (esto es scraping de TikTok que ellos exponen como "research").

### 1.3 Modelo de negocio (para dimensionar el "build vs buy")

Tres planes de suscripción por volumen de contenido: **Growth ~$49/mes** (100 slideshows, 150 créditos IA, 10 automatizaciones), **Scale ~$95/mes** (250 / 300 / 20) y **Enterprise ~$195/mes** (750 / 750 / 200 + **acceso a API** y **tu propia Anthropic API key para generaciones ilimitadas**). Prueba gratis: "haz 3 TikToks gratis". El acceso a API vive solo en los planes altos.

**Lectura estratégica:** el costo real que ellos te cobran es *plomería + prompt afinado + acceso a Pinterest + publicación a TikTok*, no cómputo caro. Como tú ya tienes casi toda esa plomería, construir nativo te sale básicamente al costo de tokens del LLM (que ya pagas con DeepSeek/Claude) + tu tiempo de ingeniería.

### 1.4 La arquitectura interna, deducida

Nadie publica sus internals, pero el founder es "ingeniero que escribió código en vez de contratar un equipo", y **su propia API pública revela el modelo de datos** (sección 2). De ahí se deduce una arquitectura casi idéntica a la tuya:

```
Prompt/tema ─► LLM (Claude, guiado por un "skill") ─► guion de slides (texto por slide)
                                     │
             Pinterest search ◄──────┘ (una query por slide) ─► URLs de imágenes
                                     │
        Render de cada slide (imagen + texto overlay) ─► imágenes de slideshow
                                     │
             (opcional) ensamblar .mp4 con música/transiciones
                                     │
     Automation = cron + hook rotation ─► publicar a TikTok (OAuth) ─► analítica
```

Esto es, literalmente, tu blueprint de `@gdlscene` con: (a) el "meme" convertido en "slide N de un set" y (b) TikTok como destino además de IG.

---

## 2. Reverse engineering: el mapa de su API (tu mejor "spec" para clonar)

reel.farm publica una **REST API documentada** en `https://reel.farm/api-docs`, base `https://reel.farm/api/v1`, auth `Authorization: Bearer rf_...`. **No necesitas usar esta API** (elegiste build nativo), pero su forma es el mejor plano de referencia de qué piezas construir. Estos son los grupos y lo que cada uno te enseña.

### 2.1 Slideshows — el corazón

| Endpoint | Qué hace | Lo que te enseña a construir |
|---|---|---|
| `POST /slideshows/generate` | Genera un slideshow desde un prompt en lenguaje natural (IA elige contenido e imágenes). `additional_context` (prompt), `images[]` (opcional, fondos). Devuelve `slideshow_id`, `status:"processing"`. | El modo "automático": prompt → guion + imágenes. Es tu `reel_script.py` + sourcing + render, encadenados. |
| `POST /slideshows/create` | Control total, slide por slide: `slides[]` (1–20), `title`, `aspect_ratio` (`4:5`,`9:16`,`1:1`,`16:9`), `text_position`, `export_as_video`, `duration`, overlays y opacidad de fondo. | El **contrato de datos del slideshow**. Cópialo como tu estructura interna (sección 8). |
| `GET /slideshows/{id}/status` | Poll de estado: `draft`/`generating`/`rendering`/`completed`/`failed`, con `video_id`/`video_status`. | Confirma que el render es **asíncrono con polling** — igual que tu espera de container FINISHED en IG. |

**Objeto `slide`:** `image_url`/`image_urls`, `image_layout` (`single`,`1:2`,`1:3`,`2:1`,`2:2` — grillas), `text_items[]`, `is_cta` (marca el slide de llamada a la acción).

**Objeto `text_item`:** `text`, `font_size` (`extra_extra_small`…`extra_large`), `text_color` (paleta con nombre), `text_style` (`text`,`outline`,`background`…), `font` (`TikTokDisplay-Bold`, `BebasNeue-Regular`…), `text_width`, `text_align`, `text_anchor`, `text_vertical_anchor`.

> **Insight de oro:** esto es exactamente lo que tú ya haces con Jinja2 + una plantilla HTML. Cada `text_item` es una variable de plantilla; cada `slide` es un `render_card()`. **La plantilla de slide es una versión parametrizada de tu `meme.html`.**

### 2.2 Automations — el "set & forget"

`POST /automations` crea un horario recurrente que genera y publica solo: `tiktok_account_id`, `schedule[]` (`{cron}` en hora del Pacífico), `slideshow_hooks[]` (plantillas de tema que la IA rota), `style` (prompt de estilo), `language`, `tiktok_post_settings` (caption modo `prompt`/`static`, `auto_post`, `visibility`, `auto_music`, `post_mode`, `allow_comments/duet/stitch`) e `image_settings` (primer slide vs todos, aspect ratio, overlays, grillas, CTA). Se listan, editan (`PATCH`, incluido `action:"pause"/"unpause"`), borran, y tienen `POST /automations/{id}/run` para un disparo único y `/schedule` para administrar los crons.

> **Traducción a instagod:** tu "automation" es **una fila de configuración** (en el Sheet o en SQLite) que combina: un conjunto de *hooks/temas*, un *estilo*, un *slot de publicación* (ya tienes `POSTING_SLOTS`/`scheduler.py`) y un *destino*. El cron de GitHub Actions que ya usas para publicar es tu motor de automatización.

### 2.3 Videos, TikTok, Pinterest, Library, Collections, Account

- `GET /videos`, `GET /videos/{id}`, `GET /videos/{id}/analytics`, `POST /videos/{id}/publish` — inventario de piezas renderizadas + métricas. Tipos: `slideshow`, `ugc`, `greenscreen`.
- `POST /tiktok/publish` (publica un video/slides con settings custom, sin automatización), `GET /tiktok/accounts`, `GET /tiktok/posts` (posts con métricas). **Nota clave suya:** TikTok permite **6 publicaciones directas por 24h**; sugieren `MEDIA_UPLOAD` (borrador en la app) para esquivar ese límite. Esto es un dato real de la Content Posting API de TikTok, no un invento suyo.
- `GET /pinterest/search?q=...` — devuelve URLs de imágenes en alta resolución (hasta 5 páginas). **Este es su motor de sourcing de imágenes faceless.**
- `GET /library`, `GET /library/niches`, `GET /library/profiles/{id}` — su base de research (slideshows reales de TikTok por nicho/región).
- `GET /collections`, `GET /account` — banco de imágenes del usuario y estado de créditos.
- **Límites:** 20 req/60s por usuario; máx **3 slideshows en render simultáneo**; errores estándar (`401/402/403/404/422/429`, con `CONCURRENT_LIMIT`).

> **Qué copiar de aquí, qué ignorar.** Copia: el contrato de `slideshow`/`slide`/`text_item`, la idea de `automation`, el sourcing por búsqueda de imágenes, y el patrón render-asíncrono-con-polling. Ignora (o pospón): `library` (research por scraping de TikTok) y `ugc/greenscreen` (avatares) — no son tu core y añaden complejidad legal/técnica.

---

## 3. Cómo se mapea sobre instagod (lo que YA tienes)

Este es el hallazgo central. Componente de reel.farm → tu equivalente actual:

| Pieza de reel.farm | Equivalente en instagod (hoy) | ¿Reutilizable? |
|---|---|---|
| LLM que escribe el guion del slideshow | `src/caption.py` (LLM agnóstico DeepSeek/Claude, few-shot, loop de rechazados) | **Sí**, clonar patrón a `reel_script.py` |
| Render de cada slide (imagen + texto) | `src/compose.py` → `render_card(template_file, ctx)` + Playwright + Jinja2 | **Sí**, casi directo |
| Plantillas de estilo (`meme.html`, `meme_verde.html`, `meme_onion.html`, `anuncio.html`) | `templates/` con auto-fit de titular (`window.__captionFitted`) | **Sí**, añadir `slide.html` |
| Sourcing de imágenes (Pinterest) | Tu **banco propio** de fotos por banda/persona (`data/photos`, `src/banco.py`, `faces.py`, `classify.py`) + `covers.py` (portadas) | **Mejor que el suyo** para tu nicho; Pinterest/Pexels solo como relleno |
| Hosting público de la imagen | `src/host.py` (Cloudinary) — IG exige `image_url`/`video_url` público | **Sí**, directo |
| Publicar carrusel a IG | `src/instagram.py` → **`publish_carousel(image_urls, caption)` ya existe** (containers hijo → CAROUSEL → publish) | **Sí, ya está** |
| Automation / cron | `scheduler.py` + `POSTING_SLOTS` + GitHub Actions (`publish.yml`) + cola en Sheet | **Sí**, directo |
| Aprobación humana | `telegram_bot.py` (`run_approval_batch`) con botones inline | **Sí** (ventaja tuya: reel.farm es full-auto) |
| Analítica de posts | `ig_insights.py`, `engagement.py`, `segments*.py` (motor de engagement por formato) | **Sí**, más avanzado que el suyo |
| Multi-cuenta | `config.account_creds(slug)` (sufijos `__SLUG`) + `ig_accounts.py` | **Sí** |
| Publicar a TikTok | — (no existe) | **Falta: nuevo `tiktok.py`** |
| Ensamblar `.mp4` (reel de video) | — (no existe; hoy solo PNG) | **Falta: nuevo `video.py` con ffmpeg** |
| Publicar **Reels** de video a IG | `instagram.py` solo hace imagen/carrusel | **Falta: extender a `media_type=REELS`** |
| Guion de slides (hook+slides+CTA) | `caption.py` hace 1 frase, no un set | **Falta: `reel_script.py`** |

**Resultado:** de ~13 piezas, **9 ya existen y se reutilizan**; solo **4 son trabajo nuevo real** (guion de slides, video ffmpeg, Reels IG, TikTok). Y de esas, dos (guion y Reels) son extensiones de módulos que ya tienes.

---

## 4. Arquitectura nativa propuesta

Manteniendo tu decisión arquitectónica central (Proceso A generación local con aprobación / Proceso B publicación desatendida por cron), se añade una **rama de "sets" (slideshows/reels)** en paralelo a la rama de "memes" actual.

```
┌───────────────── PROCESO A — GENERACIÓN (local, on-demand) ─────────────────┐
│                                                                             │
│  tema/hook ─► reel_script.py (LLM)  ──►  guion = {hook, slides[], cta}       │
│                     │                                                       │
│   banco.py / faces  └─► image_picker.py ─► 1 imagen por slide                │
│   (o pinterest.py/pexels.py de relleno)         │                           │
│                                                  ▼                           │
│                         compose.py::render_card(slide.html)  ─► PNG x N      │
│                                                  │                           │
│            (si formato=video) video.py (ffmpeg) ─► set.mp4  + audio          │
│                                                  │                           │
│                        telegram_bot.run_approval_batch  (apruebas el set)    │
│                                                  │                           │
│      host.py (Cloudinary) sube PNGs y/o el mp4  ─► URLs públicas             │
│                                                  │                           │
│   scheduler.assign_slot ─► fila approved en el Sheet con:                    │
│      formato ∈ {carrusel_ig, reel_ig, tiktok_slides, tiktok_video}          │
│      media_urls (JSON), caption, scheduled_datetime, destinos[]             │
└─────────────────────────────────────────────────────────────────────────────┘
                                   │
┌───────────────── PROCESO B — PUBLICACIÓN (GitHub Actions cron) ─────────────┐
│  publish.py lee filas due y despacha por formato:                           │
│     carrusel_ig   → instagram.publish_carousel(urls, caption)   [YA EXISTE] │
│     reel_ig       → instagram.publish_reel(video_url, caption)  [NUEVO]     │
│     tiktok_slides → tiktok.publish_photos(urls, caption)        [NUEVO]     │
│     tiktok_video  → tiktok.publish_video(video_url, caption)    [NUEVO]     │
│  (mismo patrón de columnas por-red y reintento parcial que ya tienes)       │
└─────────────────────────────────────────────────────────────────────────────┘
```

Módulos nuevos (todos siguen el estilo de los que ya tienes):

- `src/reel_script.py` — genera el guion de slides con el LLM. Clona la estructura de `caption.py` (cliente agnóstico, temperatura, few-shot, `rechazados`, `feedback`).
- `src/image_picker.py` — elige la imagen de cada slide desde tu banco (`db` + `banco.py`); fallback a `pinterest.py`/`pexels.py`.
- `templates/slide.html` — plantilla de un slide (imagen de fondo + overlay + texto grande auto-fit). Reusa el motor de `_screenshot_card`.
- `src/video.py` — ensambla los PNGs en `.mp4` con **ffmpeg** (Ken Burns opcional, transiciones, audio). Nuevo, pero autocontenido.
- `src/tiktok.py` — Content Posting API (OAuth + publish foto/video). Análogo a `facebook.py`.
- Extender `src/instagram.py` — `publish_reel()` (`media_type=REELS`).
- Extender el esquema del Sheet/DB — columna `formato` y `media_urls` (JSON) para soportar N imágenes o un mp4, y columnas de id por destino (`tt_post_id`, etc.).

---

## 5. Formato objetivo #1 — Carrusel de Instagram (slides)

Es el más cercano a lo que ya haces y el punto de arranque recomendado, porque **casi todo existe**.

- **Guion:** `reel_script.py` produce, p. ej., 5–8 slides (slide 1 = hook, slides intermedios = puntos, último = CTA con `@handle`).
- **Imagen por slide:** `image_picker.py` saca fotos reales de tu banco (por banda/persona/evento) — aquí ganas a reel.farm.
- **Render:** `render_card("slide.html", ctx)` por slide → PNG 1080×1350 (4:5) o 1080×1350/1080×1920 según diseño. Ya tienes auto-fit de titular.
- **Hosting:** `host.upload()` de cada PNG → lista de URLs.
- **Publicación:** **`instagram.publish_carousel(urls, caption)` ya está implementada** (containers hijo → `media_type=CAROUSEL` → `media_publish`, con espera de FINISHED y reintento). Tope 10 imágenes; tu código ya lo recorta.
- **Cola/agenda/aprobación:** sin cambios; solo marcar `formato=carrusel_ig` en la fila.

**Trabajo real aquí:** `reel_script.py` + `slide.html` + `image_picker.py`. Publicación y plomería: cero.

---

## 6. Formato objetivo #2 — Reel de video de Instagram

El "reel de video" = el mismo set de slides, ensamblado a `.mp4` y publicado como Reel.

### 6.1 Ensamblado del video (`video.py`, ffmpeg)

- Toma los N PNGs ya renderizados (misma fuente que el carrusel) y arma un `.mp4` **1080×1920 (9:16)** con:
  - `duration` por slide (p. ej. 2.5–3.5s), transiciones (fade/`xfade`), y opcional **Ken Burns** (zoom/pan lento) para que no se sienta estático.
  - **Audio:** pista de fondo. Ojo con derechos (sección 9).
- ffmpeg es CLI; el módulo solo compone el comando y verifica que exista (`which ffmpeg`; instalar si falta). Output a `out/` como tus PNGs.
- Alternativa sin ffmpeg: MoviePy (Python), más lento pero más simple de scriptear.

### 6.2 Publicación de Reels (`instagram.publish_reel`)

Extiende `instagram.py` con el mismo patrón de 2 pasos que ya usas, pero para video:

1. `POST /{ig-user-id}/media` con `media_type=REELS`, `video_url=<url pública del mp4>`, `caption`, opcional `cover_url`/`thumb_offset`, `share_to_feed=true`.
2. **Poll de estado** del container hasta `FINISHED` (los videos tardan más que las imágenes; reusa `_wait_until_ready` subiendo `attempts`/`delay`).
3. `POST /{ig-user-id}/media_publish` con `creation_id`.

Consideraciones: el `.mp4` debe estar en URL pública (Cloudinary ya te sirve; verifica cuota de video del free tier o usa R2/S3). Specs de Reels: MP4/MOV, 9:16, ~3s–15min, códecs H.264/AAC. Límite práctico de publicaciones por día de la cuenta (tu blueprint ya contempla 25/24h para imágenes; Reels comparte cuota de content publishing).

> Nota: reel.farm confirma que su "video" es literalmente `export_as_video` del slideshow. No hace falta generación de video con IA para igualar su producto; **imágenes + ffmpeg + audio** es suficiente.

---

## 7. Formato objetivo #3 — TikTok

Aquí sí es territorio nuevo, porque instagod hoy no toca TikTok. Es lo que reel.farm hace nativo.

### 7.1 La vía oficial: Content Posting API de TikTok

- **Dos modalidades** que te sirven directo:
  - **Photo post (slideshow):** subes N imágenes (por `PULL_FROM_URL` con tus URLs públicas de Cloudinary, o `FILE_UPLOAD`). Es el equivalente 1:1 del slideshow de reel.farm en TikTok.
  - **Video post:** subes el `.mp4` (mismo que el Reel).
- **Dos modos de posteo:**
  - `DIRECT_POST` — publica directo (requiere que tu app pase la **auditoría** de TikTok para poder postear público a cuentas que no son de prueba).
  - **`MEDIA_UPLOAD` (a.k.a. "upload to inbox")** — deja el contenido como **borrador** en la app de TikTok para que le des "publicar" a mano. **No requiere auditoría** y **esquiva el límite de 6 publicaciones directas/24h.** reel.farm recomienda justo esto; es el arranque más sano.
- **OAuth de TikTok:** registras una app en `developers.tiktok.com`, pides los scopes `video.publish` / `video.upload` (y los de foto), y guardas el `access_token`/`refresh_token` por cuenta (como ya haces con IG/FB en `config.account_creds`). El refresh de token es obligatorio (igual que tu Proceso C de IG).

### 7.2 `src/tiktok.py` (nuevo, análogo a `facebook.py`)

Funciones sugeridas: `publish_photos(image_urls, caption, *, post_mode="MEDIA_UPLOAD")` y `publish_video(video_url, caption, *, post_mode="MEDIA_UPLOAD")`, cada una con el flujo init→(poll)→status y el mismo manejo de errores/reintentos de tus otros módulos. En `publish.py` se agrega como una plataforma más en la lista `PLATFORMS`, con su columna `tt_post_id` y kill-switch `CROSSPOST_TT` en `config.py`.

### 7.3 Plan realista de auditoría

Empieza con `MEDIA_UPLOAD` (borradores) mientras tu app está en modo desarrollo — funcional para ti y tus cuentas de prueba desde el día 1. Solicita la auditoría para `DIRECT_POST` público solo cuando el pipeline esté probado y quieras full-auto. Presupuesta 1–3 semanas de ida y vuelta con TikTok para la auditoría.

---

## 8. El cerebro creativo: generación del guion de slides

Aquí está el 70% del valor (igual que anota tu blueprint para el caption). Diseño de `reel_script.py`:

### 8.1 Contrato de datos (cópialo del `slideshow` de reel.farm)

```python
# Estructura interna sugerida (dataclass o dict), inspirada en POST /slideshows/create
Slide     = {"texto": str, "rol_texto": "hook|punto|cta",
             "imagen_hint": str,           # query/tema para image_picker
             "font_size": "grande|mediano", "posicion": "top|center|bottom"}
GuionReel = {"tema": str, "hook": str, "slides": list[Slide],
             "cta": str, "aspect": "9:16|4:5", "formato_patron": str}
```

Esto te da algo enchufable a `render_card()` (cada `Slide` → un `ctx` de plantilla) y a `video.py` (orden + duración).

### 8.2 Firma y patrón (clona `caption.py`)

```python
def generar_guion(tema: str, *, banda: str | None = None,
                  n_slides: int = 6, formato: str = "listicle",
                  rechazados: list[str] | None = None,
                  feedback: str | None = None) -> GuionReel: ...
```

- **Agnóstico de proveedor** (DeepSeek/Claude) reusando `config.LLM_PROVIDER` — igual que hoy.
- **Salida estructurada:** pide al LLM **JSON estricto** con el esquema de arriba (más robusto que parsear texto). Valida y reintenta si no cumple.
- **Few-shot con tu voz editorial:** reusa tus patrones ganadores (`FORMATO_PATRONES`: `absurdo_domestico`, `declaracion_personaje`, `dato_falso`, `comunicado`). Un slideshow es varios de estos encadenados con un hook al frente.
- **Loop de mejora:** guarda guiones aprobados/rechazados y aliméntalos como ejemplos + negativos (tu blueprint ya tiene este mecanismo para captions y `engagement.py` para pesos por formato). Aquí lo extiendes a "qué hooks retienen".
- **El "Skill.md" de reel.farm = tu system prompt afinado.** No hay más secreto: una plantilla de instrucciones que fija tono, longitud por slide, estructura hook→desarrollo→CTA y reglas de marca. Escríbelo una vez, itéralo con datos.

### 8.3 Hooks

Un mini-modo `generar_hooks(brief) -> list[str]` (barato, temperatura alta) para producir 3–5 aperturas y elegir/AB-testear. Esto replica su Hook Generator y alimenta la rotación de `slideshow_hooks` de una automatización.

---

## 9. Fuentes de imagen y música (los dos detalles con trampa)

**Imágenes.** Orden de preferencia para tu caso:
1. **Tu banco propio** (`data/photos` + `banco.py` + `faces.py`): fotos reales de la banda/persona/foro del slide. Es tu foso defensivo; reel.farm no puede replicarlo.
2. **Portadas** (`covers.py`) para slides de releases/música nueva.
3. **Relleno stock** cuando el slide es genérico: Pinterest (como reel.farm) o, más limpio legalmente, **Pexels/Unsplash API** (licencia clara para uso comercial). Un `pinterest.py`/`pexels.py` de ~30 líneas.

> Cuidado con Pinterest: reel.farm scrapea resultados de Pinterest, cuyas imágenes suelen tener copyright de terceros. Para contenido tuyo real no lo necesitas; úsalo solo para fondos abstractos/genéricos, y prefiere Pexels/Unsplash para estar tranquilo.

**Música.** Los Reels/TikToks "sin audio propio" rinden peor, pero meter música con copyright vía API es riesgo. Opciones: (a) publicar el video **sin** pista y dejar que tú añadas audio nativo de la plataforma antes de publicar (fácil con `MEDIA_UPLOAD`/borrador en TikTok y con Reels que permiten audio trending en la app), o (b) usar **biblioteca libre de regalías** (p. ej. pistas con licencia CC0/comercial) embebida por ffmpeg. Empieza por (a): es lo que mejor rinde y evita el problema legal.

---

## 10. Pasos de arranque (roadmap por fases)

Orden pensado para tener valor publicable lo antes posible y dejar lo nuevo/riesgoso al final. Cada fase es entregable por sí sola.

**Fase 0 — Decisiones y specs (medio día).**
Congela el contrato de datos (`GuionReel`/`Slide`, sección 8.1) y añade al esquema del Sheet/DB la columna `formato` y `media_urls` (JSON). Define 1–2 diseños de `slide.html` en papel (hook grande, punto, CTA).

**Fase 1 — Carrusel IG nativo (el quick win).**
`reel_script.py` (JSON estructurado, few-shot con tus patrones) → `slide.html` (Jinja2, auto-fit) → `image_picker.py` (banco propio) → render con `render_card` → `host.upload` → **`publish_carousel` (ya existe)**. Apruébalo por Telegram como cualquier meme. **Al terminar esta fase ya estás publicando slideshows reales, sin tocar video ni TikTok.**

**Fase 2 — Reel de video IG.**
`video.py` (ffmpeg: PNGs→mp4 9:16, transiciones, Ken Burns, sin audio o audio libre) → subir mp4 a Cloudinary → `instagram.publish_reel()` (`media_type=REELS`, poll extendido). Verifica cuota de video del hosting.

**Fase 3 — TikTok.**
App en developers.tiktok.com + OAuth + refresh de token (reusa el patrón de `ig_token.py`). `tiktok.py` con `publish_photos`/`publish_video` en modo `MEDIA_UPLOAD` (borradores, sin auditoría). Enchúfalo a `publish.py` como plataforma nueva con su columna y kill-switch. Solicita auditoría para `DIRECT_POST` cuando esté sólido.

**Fase 4 — Automatización de "sets".**
Extiende `scheduler.py`/agenda para programar sets recurrentes por tema/hook (tu equivalente a las *automations*). Reusa el cron de GitHub Actions. Opcional: rotación de hooks y AB test de aperturas.

**Fase 5 — Loop de mejora.**
Conecta `ig_insights.py`/`engagement.py` para puntuar qué hooks/formatos retienen y realimentar el prompt de `reel_script.py`. Aquí instagod supera a reel.farm: aprendizaje editorial dirigido por tus propias métricas.

**Orden de construcción sugerido para Claude Code:** `slide.html` → `reel_script.py` (probar aislado con JSON dummy) → `image_picker.py` → integrar en un `generate_reel.py` (entrypoint análogo a `generate.py`) → publicar carrusel → `video.py` → `publish_reel` → `tiktok.py`.

---

## 11. Riesgos y consideraciones

- **Auditoría de TikTok:** `DIRECT_POST` público la exige. Mitigación: arranca con `MEDIA_UPLOAD` (borradores), que además evita el límite de 6/día.
- **Cuotas de publicación:** IG ~25 posts/24h por cuenta (content publishing, compartido entre imagen/carrusel/Reels); TikTok 6 directas/24h. Irrelevante a bajo volumen; relevante si automatizas varias cuentas.
- **Hosting de video:** el mp4 debe ser URL pública y pesa más que un PNG. Revisa la cuota de video de Cloudinary free tier; ten R2/S3 como plan B.
- **Derechos de imagen y música:** evita Pinterest para primeros planos con copyright; prefiere tu banco + Pexels/Unsplash. Para música, audio nativo de plataforma o pistas libres.
- **Riesgo editorial (el de tu blueprint, ahora amplificado):** los slideshows escalan tu sátira sobre personas reales a más formatos y plataformas. Mantén la marca de parodia visible, el absurdo evidentemente ficticio, y una vía rápida de bajar contenido. A escala, los errores también se automatizan.
- **Calidad "que no se sienta IA":** el diferenciador de reel.farm es cosmético (tipografías tipo TikTok, texto meme, imágenes reales). Con tus fotos reales y tu voz editorial ya afinada, tu piso de calidad es más alto — invierte en `slide.html` y en el prompt, no en más plomería.
- **Tokens/costo:** construir nativo mueve el costo de una suscripción fija (~$49–195/mes) a tokens variables del LLM (ya los pagas) + tu tiempo. A tu volumen, sale más barato y sin depender de su roadmap.

---

## 12. Apéndice — Resumen de "qué construir" en una tabla

| Nuevo/Extensión | Archivo | Análogo existente | Esfuerzo |
|---|---|---|---|
| Guion de slides (LLM, JSON) | `src/reel_script.py` | `caption.py` | Medio |
| Plantilla de slide | `templates/slide.html` | `meme.html` | Bajo-Medio |
| Selección de imagen por slide | `src/image_picker.py` | `banco.py`/`covers.py` | Bajo |
| Relleno stock | `src/pexels.py` (o `pinterest.py`) | `host.py` (patrón HTTP) | Bajo |
| Ensamblado a mp4 | `src/video.py` (ffmpeg) | — | Medio |
| Publicar Reel IG | `instagram.publish_reel()` | `instagram.publish_carousel()` | Bajo |
| Publicar TikTok | `src/tiktok.py` | `facebook.py` | Medio-Alto (OAuth/auditoría) |
| Refresh token TikTok | `src/tiktok_token.py` | `ig_token.py` | Bajo |
| Entrypoint de sets | `generate_reel.py` + rama en `publish.py` | `generate.py`/`publish.py` | Bajo |
| Esquema: `formato`, `media_urls` | Sheet/DB | tu esquema actual | Bajo |

---

### Fuentes

- [ReelFarm — sitio oficial (reel.farm)](https://reel.farm/)
- [ReelFarm — landing (reelfarm.org)](https://reelfarm.org/)
- [ReelFarm — API Reference (reel.farm/api-docs)](https://reel.farm/api-docs)
- [Reel Farm: Honest Review for AI UGC Ads (2026) — SendShort](https://sendshort.ai/guides/reelfarm-review/)
- [How One Developer Launched ReelFarm — Starter Story](https://www.starterstory.com/reel-farm-breakdown)
- [Publish Content using the Instagram Platform — Meta Developers](https://developers.facebook.com/docs/instagram-platform/content-publishing/)
- [Instagram Reels API: Complete Developer Guide (2026) — Phyllo](https://www.getphyllo.com/post/a-complete-guide-to-the-instagram-reels-api)
- [Guide to Using the Content Posting API for TikTok — TikTok Developers](https://developers.tiktok.com/doc/content-posting-api-get-started)
- [TikTok Content Posting API Reference: Photo Post — TikTok Developers](https://developers.tiktok.com/doc/content-posting-api-reference-photo-post)
