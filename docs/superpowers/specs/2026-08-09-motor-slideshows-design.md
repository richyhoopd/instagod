# Motor de slideshows v1 — diseño

**Fecha:** 2026-08-09
**Estado:** aprobado por Ricardo (brainstorm 2026-08-09)
**Contexto:** primer sub-proyecto de la ruta "instagod → producto tipo reel.farm"
(ver `docs/reel_farm_a_instagod.md`).

## Secuencia congelada del roadmap (Orden A)

1. **Motor de slideshows** (este spec) — incluye sourcing externo desde v1
2. Multi-cuenta Fase B/C — páginas temáticas (perfiles de contenido en DB)
3. TikTok photo posts (`MEDIA_UPLOAD`; registrar la app en developers.tiktok.com
   en paralelo desde ya, la auditoría tarda semanas)
4. Video + Reels IG (ffmpeg + `publish_reel`)
5. Automations por cuenta + loop de mejora
6. (Mediano plazo) Productización SaaS para terceros — proyecto aparte

## Objetivo v1

Motor **genérico** de slideshows (cualquier tema, cualquier producto, cualquier
formato — no solo bandas): un brief produce un set de N slides (imagen de fondo +
texto grande estilo TikTok), que se aprueba por Telegram y se publica como
**carrusel de Instagram** en @gdlscene por el pipeline existente.

Los formatos de @gdlscene ("todo lo que sabemos de X", listicle satírico, perfil
de banda/persona) son *presets* del motor, no su núcleo.

**Criterio de éxito:**

- `python -m src.generate_slideshow --tema "..." --formato listicle --estilo
  tiktok_bold --fuentes pexels` → set aprobado en Telegram → carrusel publicado
  en IG por `publish.py` sin cambios.
- El mismo motor con `--fuentes banco` produce el "Todo lo que sabemos de X" de
  una banda (pendiente editorial de junio).

## Contrato de datos (dos capas)

### Capa 1 — Contrato `Slideshow` (completo, claves en inglés)

Clon en forma de `POST /slideshows/create` de reel.farm. Es lo que se almacena,
se rinde, y a mediano plazo se expone como API de producto.

```python
TextItem:  text, font_size ("extra_extra_small"…"extra_large"),
           text_color (nombre de paleta), text_style ("text"|"outline"|"background"),
           font (catálogo propio), text_width (0–1), text_align,
           text_anchor ("left"|"center"|"right"),
           text_vertical_anchor ("top"|"center"|"bottom")

Slide:     image_url | image_urls[], image_layout ("single"|"1:2"|"1:3"|"2:1"|"2:2"),
           text_items[], is_cta (bool), background_opacity (0–1),
           duration (float, para el futuro export a video),
           source (proveniencia de la imagen: "banco"|"covers"|"pexels"|"pinterest"|"manual")

Slideshow: title, aspect_ratio ("4:5"|"9:16"|"1:1"|"16:9"), slides[1–20],
           caption, language,
           # metadatos instagod:
           brief (dict), formato (str), account_slug (str)
```

Implementación: dataclasses ligeras en `src/slideshow_model.py` + `validar()`
(enums, rangos, 1–20 slides). Sin pydantic (consistente con el repo).

### Capa 2 — Guion semántico (lo que emite el LLM)

El LLM **no** decide estilos ni posiciones. Emite JSON estricto:

```json
{"tema": "...", "hook": "...", "caption": "...",
 "slides": [{"text": "...", "rol": "hook|punto|cta", "image_hint": "query"}],
 "cta": "..."}
```

Reglas obligadas (gotcha documentado de `parse_events.extraer_json`): objeto
raíz **dict**, `response_format={"type": "json_object"}`, `max_tokens` explícito.

### Compilador determinista

`compilar(guion, estilo) → Slideshow`. El preset de estilo
(`config.SLIDESHOW_ESTILOS`) aporta fuentes, colores, tamaños, anchors,
`background_opacity` y layout por rol (hook/punto/cta). Beneficios:

- Un mismo guion se **re-estila sin regenerar** (análogo al botón 🎨 de memes).
- El LLM valida contra un esquema chico → menos reintentos.
- El contrato completo existe desde el día 1 para llenado manual (modo
  "create" de reel.farm).

### Persistencia

Columna nueva `content_queue.slideshow_json` (TEXT, JSON del contrato completo)
vía migración idempotente en `db._MIGRATIONS`. Necesaria para
regenerar/re-estilar y para el futuro export a video. El resto de la fila usa el
mecanismo existente de carrusel (lista JSON de URLs en la columna de imagen).

## Módulos

| Módulo | Responsabilidad |
|---|---|
| `src/slideshow_model.py` | Dataclasses del contrato + `validar()` |
| `src/slideshow_script.py` | `generar_guion(brief, *, rechazados=None, feedback=None) → guion`. Clona el patrón de `caption.py`: cliente LLM agnóstico (`config.LLM_PROVIDER`), few-shot por formato, reintento con el error de validación en el prompt |
| `src/slideshow_compile.py` | `compilar(guion, estilo) → Slideshow`, determinista, presets en `config.SLIDESHOW_ESTILOS` |
| `src/image_sources.py` | Protocolo provider `buscar(hint, n) → [ImagenCandidata]`. Providers v1: `banco`, `covers`, `pexels`, `pinterest`. Orden de preferencia por brief, fallback en cascada, cache de descargas en `data/sourcing/` |
| `templates/slide.html` | Rinde el contrato completo: aspect variable, grids de `image_layout`, N `text_items` posicionados, overlay, auto-fit reutilizando el patrón `__captionFitted` de `compose._screenshot_card` |
| `src/generate_slideshow.py` | CLI orquestador (flujo abajo), con `--dry-run` |

Piezas existentes que se reusan sin cambios: `compose.render_card`,
`host.upload` (jpg — IG rechaza PNG), `approval.enviar_a_telegram` (álbum +
botones ya soporta carrusel), `approval.aprobar`, `sheets`, `publish.py`,
`instagram.publish_carousel`.

## Flujo v1

```
CLI (o botón GUI) → generar_guion → image_sources (1 imagen/slide) → compilar
  → render_card("slide.html", ctx) × N  → PNGs en out/
  → host.upload(format="jpg") × N
  → encolar content_queue (status='borrador', aprobacion='pendiente',
    slideshow_json, imagen = JSON-list de URLs)
  → approval.enviar_a_telegram   (no-bloqueante; el approval-daemon es el poller)
  → Ricardo aprueba → fila approved en el Sheet → publish.py → publish_carousel
```

Carruseles conservan la botonera actual de carrusel (✅/❌); regenerar/re-estilar
un set desde Telegram queda como mejora posterior (el `slideshow_json`
persistido ya lo deja listo).

**Agendado al aprobar:** los slideshows son contenido *evergreen* → al aprobar
toman el siguiente hueco libre de la malla de slots (`scheduler.next_free_slot`),
igual que los memes. NO publican de inmediato (ese camino es exclusivo de
anuncios/agendas).

**GUI:** página `/slideshows` mínima: form (tema, formato, estilo, fuentes,
n_slides) → `_lanzar_sesion` detached (patrón de novedades). Sin CRUD de
perfiles (eso llega con multi-cuenta). Recordatorio operativo: rutas nuevas en
`web/app.py` requieren reiniciar uvicorn.

## Sourcing

- **`banco`**: fotos usables por banda/persona (`db` + criterios de
  `banco.py`/`planner`); respeta `usada` y anti-repetición.
- **`covers`**: portadas de releases vía `covers.asegurar_cover` (ya resuelve el
  DNS roto de i.scdn.co).
- **`pexels`**: API oficial (`PEXELS_API_KEY` en `.env`), licencia limpia para
  uso comercial. Fallback por defecto de temas genéricos.
- **`pinterest`**: sin API pública de búsqueda → endpoint JSON interno de
  búsqueda con headers de navegador, sin login, rate bajo, cache agresivo.
  Detrás de feature-flag `SOURCING_PINTEREST=1`. Si devuelve 403 o cambia el
  formato: el provider se apaga en la corrida (circuit breaker simple, sin
  reintentos en loop) y cae la cascada a `pexels`. Las imágenes quedan marcadas
  `source="pinterest"` en el contrato para auditar/bajar contenido con
  copyright reclamado. Riesgo asumido y aislado.
- Puerta abierta a providers futuros (Unsplash, Wikimedia) por el mismo
  protocolo.

## Manejo de errores

- **LLM**: JSON inválido o guion que no valida → hasta 3 reintentos con el error
  en el prompt; si agota, aborta con mensaje claro. Nunca se encola un set roto.
- **Sourcing**: provider caído/sin resultados → siguiente en cascada; ningún
  provider da imagen → slide de **fondo sólido** con el color del preset (el set
  no truena; se ve en la aprobación).
- **Render / hosting / publicación**: manejos existentes de
  `compose`/`host`/`publish.py` (reintentos, filas parciales). Sin código nuevo.

## Testing

- Unit puros: validador del contrato; compilador (casos por layout/rol/anchor);
  parseo de respuesta LLM con fixtures; cascada de `image_sources` con
  providers fake; slide de fallback.
- Render smoke con Playwright: `slide.html` para 2–3 contratos representativos
  (grid, outline, CTA) — rinde y auto-fitea; sin comparación de píxeles.
- CLI `--dry-run`: guion + contrato + PNGs locales, sin subir/encolar/enviar.
- Cero llamadas reales a LLM/Pexels/Pinterest/Telegram en tests (patrón del
  repo).

## Fuera de alcance v1 (explícito)

Export a video/ffmpeg, Reels IG, TikTok, automations recurrentes, perfiles de
contenido en DB, música/audio, multi-cuenta Fase B/C, UGC/avatares, library de
research. Cada uno tiene su lugar en la secuencia congelada.

## Riesgos

- **Pinterest**: scraping frágil y con imágenes de terceros — flag + cascada +
  marcado de proveniencia (arriba).
- **Editorial**: la sátira sobre personas reales escala a más formatos; la
  aprobación humana por Telegram se mantiene como compuerta obligatoria.
- **Cuota IG**: los carruseles comparten la cuota de content publishing
  (~25/24h); irrelevante al volumen actual.
