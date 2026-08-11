# Multi-marca (Fase B/C + bots por marca) — diseño

**Fecha:** 2026-08-10
**Estado:** aprobado por Ricardo (brainstorm 2026-08-10)
**Contexto:** sub-proyecto 2 del roadmap "instagod → producto" (Orden A, ver spec
2026-08-09-motor-slideshows). Feedback que lo detonó: el set E2E de Kabala
funcionó técnicamente pero no llevaba la identidad de la cuenta, y las
aprobaciones de todas las marcas no pueden llegar al mismo bot de Telegram.

## Objetivo

instagod pasa de "una cuenta con sufijos" a **plataforma multi-marca**: cada
marca registrada tiene su configuración interna (fuentes de imagen, paleta y
estilos de slideshow, voz LLM con reglas de compliance, cuenta IG destino,
Sheet propio, malla de horarios propia) y **su propio bot de Telegram** para
aprobaciones. El usuario (hoy Ricardo) da de alta marcas desde la GUI.

**Marca 2 real:** Pensión+ (`pensionmas.com.mx`) — asesoría de retiro parcial
por desempleo de AFORE, cambios/mejora de afore. Cuenta IG ya creada. Solo
produce **slideshows** (v1); memes/agenda/releases siguen exclusivos de
gdlscene. Identidad completa en `~/Work/personal/tulanaya/DESIGN.md` y
`PRODUCT.md`: paleta cobalto/navy/oro/teal/periwinkle (OKLCH), display Erode
(woff2 en `tulanaya/public/fonts/`), tono confiable/claro/cercano SIN urgencia,
reglas legales de copy (montos siempre "estimados", cero promesas absolutas),
imágenes de personas reales 40-60 mexicanas (nada corporativo gringo).

**Criterio de éxito:** onboarding completo de pensión+ — bot de BotFather +
fila de marca en `/marcas` + vars en `.env` + reinicio del daemon → set
generado con `--marca pensionmas`, aprobado en SU bot, publicado en SU IG en
SU slot. gdlscene sigue operando idéntico; aprobar/rechazar en un bot no toca
al otro.

## A. Entidad marca

`accounts` (Fase A: slug, ig_handle, nombre, ciudad, timezone, voz_extra,
color_marca, activa) se amplía vía `db._MIGRATIONS` (idempotente):

| Columna nueva | Tipo | Contenido |
|---|---|---|
| `fuentes_imagen` | TEXT JSON | Orden de sourcing: pensión+ `["pinterest","pexels"]`; gdlscene `["banco","covers","pexels"]` |
| `estilos_json` | TEXT JSON | Presets de slideshow de la marca (esquema de `config.SLIDESHOW_ESTILOS` + bloque `chrome`); NULL → presets globales |
| `voz` | TEXT | System-prompt de marca: tono, audiencia, compliance, guía de imágenes. Se inyecta como contexto base del guion |
| `formatos` | TEXT JSON | Formatos habilitados (pensión+: `["listicle","libre"]`) |
| `logo_path` | TEXT | Asset local en `data/brands/<slug>/` |
| `posting_slots` | TEXT | Malla propia "HH:MM,HH:MM" opcional; NULL → `config.POSTING_SLOTS` global |

**Secretos NUNCA en DB.** `config._ACCOUNT_CRED_KEYS` se extiende con
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`. Todo por sufijo:
`TELEGRAM_BOT_TOKEN__PENSIONMAS`, `IG_ACCESS_TOKEN__PENSIONMAS`,
`IG_USER_ID__PENSIONMAS`, `SHEET_ID__PENSIONMAS`. El fallback sin sufijo
sigue siendo EXCLUSIVO de gdlscene (`config.account_creds` ya lo implementa;
una marca nueva jamás hereda tokens por accidente).

**Fuentes tipográficas de marca:** los woff2 de Erode se copian a
`templates/assets/fonts/`, se registran en `config.SLIDESHOW_FUENTES`, y
`slide.html` declara `format('woff2'|'truetype')` según la extensión del
archivo.

## B. Daemon multi-bot y aprobación por marca

**Daemon (un solo proceso, N bots):** `approval_daemon.main()` lee marcas
activas; por cada una con token TG (gdlscene cae al global) construye una
**Application PTB propia** con los mismos handlers de hoy y
`bot_data["account_id"]`/`["slug"]` sellados. Todas corren en el mismo loop
asyncio: `initialize()` → `start()` → `updater.start_polling()` por app;
shutdown limpio en orden inverso. Se conservan sin cambios: heartbeat único,
watchdog, `poller_lock` global. Marca sin token → no levanta bot, log claro
al arrancar. El `filters.Chat(chat_id)` por bot mantiene "solo tú" por marca.

**Envío:** `approval.enviar_a_telegram(...)` gana `account_slug` (el caller lo
resuelve de la fila de `content_queue`); manda con token/chat de esa marca.

**Aprobación:** callbacks `aprobar:{qid}`/`rechazar:{qid}` sin cambios.
`approval.aprobar` lee `account_id` de la fila y con eso:
- escribe en el **Sheet de la marca** (`SHEET_ID__SLUG`; el módulo `sheets` se
  parametriza por marca),
- elige slot contra la **malla de la marca** (`posting_slots` propio o global,
  leyendo el Sheet de esa marca).

Los flujos de una marca jamás pisan el Sheet ni los slots de otra. `bot.py`
interactivo (fotos con descripción) sigue siendo gdlscene-only en v1.

## C. Generación brandeada

`python -m src.generate_slideshow --marca pensionmas --tema "..."`:

1. Carga el perfil → fuentes default, estilo default, formatos permitidos
   (formato no habilitado → error inmediato), y la `voz` de la marca como
   contexto base del guion (el `--contexto` CLI se concatena encima).
2. `estilos_json` de la marca se resuelve con prioridad sobre
   `config.SLIDESHOW_ESTILOS`. El esquema de preset gana el bloque
   **`chrome`**: `{"handle": "@pensionmas", "logo": bool, "posicion":
   "footer"}` → `slide.html` pinta un pie de marca discreto (wordmark/logo +
   handle) en cada slide. Es la identidad que le faltó al set de Kabala.
3. **Preset semilla `pensionmas`**: cobalto/navy/oro (hex convertidos de los
   OKLCH de tulanaya/DESIGN.md), display Erode 600/700, cuerpo Poppins, cajas
   limpias sin urgencia. **Preset propio `gdlscene`**: su verde/Tinos/handle,
   para que sus slideshows también queden alineados a su plantilla.
4. `content_queue.account_id` se llena con la marca (columna ya existente).
   GUI `/slideshows` gana selector de marca.

## D. Publicación multi-cuenta, GUI y onboarding

**Publicación:** `publish.py` itera marcas activas → abre SU Sheet → publica
lo vencido con SUS creds (`account_creds(slug)`). Una marca solo publica en
las redes cuyas credenciales tenga (pensión+ v1 = solo IG; FB/X siguen siendo
de gdlscene). Worker de Actions: los secretos con sufijo se cargan con
`gh secret set` (paso del onboarding); mientras falten, el respaldo horario no
ve esa marca y la publicación local la cubre.

**GUI `/marcas`:** lista + alta/edición del perfil (nombre, handle, colores/
estilos, voz, fuentes de imagen, formatos, slots). Secretos NO editables ahí:
la página muestra un **checklist de vars de `.env` faltantes** por marca
(`TELEGRAM_BOT_TOKEN__X ✅/❌`…) para guiar el alta.

**Onboarding pensión+ (E2E del spec):** BotFather → `/marcas` (perfil +
preset semilla) → `.env` (4-5 vars con sufijo) → reiniciar daemon → set de
prueba `--marca pensionmas` → aprobar en el bot de pensión+ → publicado en su
IG. Verificar en paralelo que gdlscene sigue intacto.

## Manejo de errores

- Marca sin token TG → sin bot, log al arrancar el daemon (no fatal).
- `aprobar` sin `SHEET_ID__SLUG` → error accionable con el nombre de la var
  faltante (nunca silencioso, nunca cae al Sheet de gdlscene).
- Formato no habilitado para la marca → error inmediato en `generar`.
- Sourcing/render/publicación: manejos del motor v1 sin cambios.

## Testing

- Unit puros: resolución de perfil (defaults, JSON malformado), merge de
  estilos marca→global, `account_creds` con sufijo (incluido: marca nueva
  jamás hereda tokens sin sufijo), malla por marca.
- Daemon multi-bot con Applications fake: arranque N bots, ruteo por
  `account_id`, marca sin token, shutdown limpio.
- `sheets`/`publish` parametrizados con fakes por marca (fila de pensión+
  publica con creds de pensión+, nunca con las de gdlscene).
- Render smoke del `chrome` de marca (footer con handle/logo) en Playwright.
- Cero llamadas reales a Telegram/IG/Sheets en tests.

## Fuera de alcance (explícito)

TikTok, video/Reels, automations por marca, memes/agenda/releases para marcas
nuevas, portal multi-usuario real (tenancy, auth, billing — sigue siendo la
instancia de Ricardo), edición de secretos desde la GUI, migrar `bot.py`
interactivo a multi-marca.

## Riesgos

- **PTB multi-Application en un loop** es menos trillado que una sola: se
  mitiga con arranque/shutdown explícitos, tests con fakes y el watchdog
  existente (un crash revive todos los bots).
- **Fuga entre marcas** (tokens/Sheets cruzados) es el riesgo de producto más
  caro: el fallback sin sufijo queda restringido a gdlscene y hay tests
  específicos de no-herencia.
- **Compliance de pensión+**: la `voz` fija las reglas legales del copy
  (estimados, sin promesas); la aprobación humana en su bot sigue siendo la
  compuerta final.
