# Carrusel de colab "Todo lo que sabemos" — blueprint

Fecha: 2026-07-14
Estado: diseño aprobado (pendiente review escrito de Ricardo)

## Problema

Para colaboraciones con eventos (p. ej. Moshpit Summer Fest, 1-ago en Staditche)
hace falta un post que sea **promo real del evento** y a la vez **contenido
divertido estilo The Onion**, que etiquete a TODOS los involucrados. Debe quedar
como **molde reutilizable** para futuras colabs, no un one-off.

## Decisiones tomadas (brainstorming)

- **Formato**: carrusel de IG "Todo lo que sabemos de <evento>".
- **Look**: portada = el cartel real del evento; slides internos estilo Onion
  limpio (fondo sólido, titular deadpan grande) reusando el motor de `meme.html`.
- **Copy**: DeepSeek escribe los titulares desde un *brief* corto; Ricardo
  aprueba/rechaza el carrusel armado en Telegram (flujo async del daemon).
- **Etiquetado**: TODOS etiquetados en el caption — los participantes de la
  colab + el lineup completo del cartel + sede + DJ. Etiquetar ≠ tener slide.
- **Slide fijo**: la vaca + el delfín de la playa es slide garantizado (gag
  insignia del cartel). *(default asumido — vetable en review)*
- **Publicación**: inmediata al aprobar (`tipo='anuncio'`, regla editorial "un
  anuncio que espera no sirve"). *(default asumido — vetable en review)*
- **No es segmento de cadencia** (no recurrente): generador on-demand.

## Arquitectura

### A. Entrada — brief por evento (`data/colabs/<slug>.json`)

```json
{
  "slug": "moshpit-summer-fest",
  "evento": "Moshpit Summer Fest",
  "fecha": "2026-08-01",
  "fecha_texto": "1 de agosto",
  "sede": "Staditche",
  "cta_handle": "@moshpit.mx",
  "cartel": "data/colabs/moshpit-summer-fest.jpg",
  "boletos": "opcional (texto o link)",
  "angulos_fijos": ["la vaca y el delfín retozando en la playa"],
  "angulos": ["estética de protector de pantalla 2003"],
  "participantes": [
    {"handle": "@moshpit.mx", "rol": "organiza", "tipo": "colectivo", "slide": false},
    {"handle": "@staditche", "rol": "sede", "tipo": "foro", "slide": false},
    {"handle": "@cabronxxit0s", "dato": "va en el feat de CCÑA", "slide": true},
    {"handle": "@cinemamanglar_band", "slide": true},
    {"handle": "@quiensosvozmusic", "slide": true},
    {"handle": "@angelxcecena", "slide": true}
  ],
  "tags_extra": ["@levin", "@palomaromo", "@chispy", "@wes", "@melloncollie",
                 "@sanimpala", "@axelitoo", "@diegofinn", "@olper"]
}
```

- `angulos_fijos` = semillas que SIEMPRE se vuelven slide (la vaca+delfín).
- `angulos` = semillas que el LLM usa si hay cupo.
- `participantes[].slide` = si obtiene slide-roast propio. `dato` opcional =
  hecho real para clavar el chiste. `tipo` alimenta `caption.TIPO_GUIA`.
- `tags_extra` = handles del lineup que van al caption pero NO tienen slide.
- **Fuente de verdad de handles = el brief.** Helper opcional
  `resolver_handle(nombre)` intenta completar desde la DB (`bands.ig_handle` por
  nombre) los que Ricardo deje en blanco; si no encuentra, se omite ese tag (no
  se inventa @).

### B. Generación — `src/generate_colab.py`

Molde: `generate_anuncios.py` / `generate_relleno.py` (no-bloqueante, encola +
`approval.enviar_a_telegram`, requiere daemon vivo).

1. **Portada (S1)** = el cartel real (`brief.cartel`), subido a Cloudinary como
   jpg (IG solo acepta JPEG) — primer hijo del carrusel, sin plantilla.
2. **Slides internos** — DeepSeek (voz Onion, `CAPTION_TEMPERATURE≈1.05`,
   inyectando `TIPO_GUIA` por `tipo` del participante) genera:
   - los `angulos_fijos` como titulares (slide garantizado),
   - 0-N `angulos` generales según cupo,
   - un titular-roast por participante con `slide: true` (usa `dato`/`tipo`),
     etiquetando su `@handle` al pie del slide.
3. **Render** con `compose.render_card(template_file, ctx)` y 2 plantillas
   nuevas mínimas:
   - `templates/colab_slide.html` — text-only: titular Tinos grande centrado +
     `@handle` al pie + kicker "N/M" (derivado de `meme.html` quitando `.photo`).
   - `templates/colab_cta.html` — fecha + sede + boletos + "etiqueta y comparte"
     (molde `agenda_cta.html`).
4. **Presupuesto de slides = tope 10** (límite de carrusel IG):
   `portada(1) + internos(≤8) + CTA(1)`. Orden de prioridad al llenar los ≤8:
   (a) `angulos_fijos`, (b) participantes con `slide:true`, (c) `angulos`
   generales. Si (a)+(b) > 8, se recortan primero los `angulos` y luego, si aún
   sobra, los participantes de menor prioridad (organiza/sede se asumen
   `slide:false`, no compiten). Indicador "N/M" en el kicker de cada slide.
5. **Caption** — intro Onion breve + info real (fecha, sede, CTA) + bloque final
   con **todos los @handles únicos**: participantes ∪ tags_extra ∪ cta_handle.

### C. Aprobación + publicación

- `approval.enviar_a_telegram(...)` detecta carrusel (lista de URLs) → manda
  `sendMediaGroup` (álbum) + `sendMessage` con botones ✅/❌ (los media groups no
  admiten botones inline). Encola en `content_queue` (status='borrador',
  aprobacion='pendiente', tipo='anuncio', evento_ids/`notas` con el slug).
- El **daemon** (único poller) resuelve la aprobación: `approval.aprobar` con
  `tipo='anuncio'` → `scheduled=ahora(TIMEZONE)` → escribe el Sheet approved →
  `_publicar_ahora()` (publish.py detached). Publica con
  `instagram.publish_carousel`. Crosspost según config (`CROSSPOST_FB=1`,
  `CROSSPOST_X=0`).

### D. Blueprint / reuso

- Cada colab futura = nuevo `data/colabs/<slug>.json` + su cartel jpg +
  `python -m src.generate_colab <slug>`.
- Botón en la GUI = fuera de alcance de esta pieza (futuro).

## Componentes y responsabilidades

| Unidad | Qué hace | Depende de |
|---|---|---|
| `data/colabs/<slug>.json` | Brief declarativo del evento | — |
| `src/generate_colab.py` | Carga brief → arma slides (LLM) → encola+manda a TG | caption, compose, approval, host, db |
| `templates/colab_slide.html` | Slide text-only deadpan + @handle + kicker | compose.render_card |
| `templates/colab_cta.html` | Slide de cierre con info+CTA | compose.render_card |
| `generar_titulares_colab()` (en generate_colab) | LLM→titulares (inyectable p/ tests) | caption/DeepSeek |
| `construir_slides()` (puro) | Aplica presupuesto/orden/tope 10 | — |
| `caption_colab()` (puro) | Arma caption + tags únicos | — |

Las funciones puras (`construir_slides`, `caption_colab`) se testean sin IO; el
LLM se inyecta.

## Tests — `tests/test_generate_colab.py`

- **Presupuesto**: ≤10 slides; portada primera, CTA última; `angulos_fijos`
  siempre presentes; recorte correcto cuando participantes+angulos > 8.
- **Tags**: el caption incluye TODOS los handles (participantes ∪ tags_extra ∪
  cta), únicos y sin duplicar; handle vacío se omite sin romper.
- **Estructura del carrusel**: `construir_slides` devuelve la lista esperada con
  el kicker "N/M" correcto.
- **LLM inyectable**: `generar_titulares_colab` mockeado → sin red.
- **Brief inválido**: falta `cartel`/`fecha` → error claro.

## Fuera de alcance (YAGNI)

- Botón GUI para colabs.
- Segmento de cadencia / automatización recurrente.
- Plantilla frutiger-aero a medida (se decidió portada=cartel + interior limpio).
- Edición slide-por-slide en Telegram (aprobar/rechazar el carrusel completo;
  para cambios, ajustar el brief y regenerar).

## Riesgos / notas

- **Handles del lineup**: Ricardo debe completar los @ reales en `tags_extra`
  (varios acts del cartel quizá no estén en la DB). Los que falten se omiten.
- **Requiere el daemon vivo** (poller único); el generador aborta limpio si no.
- **IG solo JPEG**: portada y slides suben como jpg (ya resuelto en `host.upload`).
