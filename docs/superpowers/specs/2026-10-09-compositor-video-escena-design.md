# 2026-10-09 — Compositor de video sobre la escena v2

Estado: borrador para revisión de Ricardo.
Subproyecto 3 de 3. Los otros: 1) editor escena v2
(`2026-10-06-editor-escena-v2-design.md`), 2) fuentes de contenido por marca
(`2026-10-09-fuentes-contenido-por-marca-design.md`).

## Problema

- La escena v2 ya acepta capas `video` (`src/plantillas/escena.py:26`), pero solo
  como foto:
  - `_pintar_video` emite `<video muted playsinline preload="auto">` sin autoplay;
    docstring: "El PNG sale con el primer cuadro; la animación es del subproyecto
    de video" (`escena.py:720-729`).
  - `render.render` termina en `compose.render_html` → PNG (`src/plantillas/render.py:52-66`).
  - `compose._screenshot_card` hace `card.screenshot` con Playwright (`src/compose.py:148-200`).
- El spec 1 difiere el render de `video` y la línea de tiempo aquí
  (`2026-10-06-editor-escena-v2-design.md:68`, `:205-210`).
- Hoy hay un solo motor de video y no sabe de escenas:
  - `video_render.render(video, out, personaje, bg_video, progreso)` arma un reel
    narrado: TTS edge-tts + tarjetas Pillow + ffmpeg (`src/video_render.py:1-13`, `:374-485`).
  - Lienzo fijo 1080×1920 a 30 fps (`src/video_model.py:25`).
  - Sin libass ni drawtext: "todo el texto entra como secuencia de PNG" (`video_render.py:4-6`).
- El editor muestra el `<video>` sin reproducir ni línea de tiempo
  (`frontend/app/b/[slug]/templates/[id]/_components/capa-vista.tsx:176-187`).

## Objetivo

- Una plantilla escena v2 con capas `video` produce un **mp4** además del PNG.
- Línea de tiempo mínima: cada capa tiene ventana de aparición; las capas `video`
  tienen recorte de entrada.
- El mp4 entra a la cola como `tipo='video'` y se publica por el camino de Reels
  que ya existe (`src/publisher.py:113-116`, `src/instagram.py:160`).

## Decisiones

| Decisión | Elección propuesta | Por qué |
|---|---|---|
| Cómo se compone | Híbrido: Playwright pinta las capas no-video como PNG transparentes por tramo; ffmpeg compone los videos + overlays | Reusa `compose` y el patrón ffmpeg de `video_render.py:446-485`; evita capturar cuadro por cuadro |
| Texto en el video | Siempre PNG (de `a_html`) | El ffmpeg de Homebrew no trae drawtext/libass (`video_render.py:4-6`) |
| Dónde vive el tiempo | Bloque opcional `tiempo` dentro de `layout_json` (escena) | Sin columna nueva; escena sin `tiempo` = estática, comportamiento actual |
| Animaciones | Solo aparición/desaparición por ventana; sin keyframes | Mínimo útil; keyframes multiplican tramos de PNG |
| Audio | Del primer video con `audio=true`; si no hay, silencio | TTS/voz queda fuera (lo hace `video_render`) |
| Cola | `content_queue` `tipo='video'` (`schema.sql:151`), URL del mp4 en `imagen_url` | Así lo lee `publisher.py:113-116` hoy |
| Motor narrado existente | No se toca | `generate_video`/`rerender_video` siguen igual (`handlers.py:687-748`) |

## 1. Modelo de datos (migración no destructiva)

### En la escena (JSON, sin DDL)

```
"tiempo": {
  "duracion_s": <número>,
  "capas": {
    "<id>": {"inicio_s": n, "fin_s": n,
             "recorte_s": n,     // solo video: segundo del clip donde empieza
             "bucle": bool,      // solo video
             "audio": bool}      // solo video; a lo más uno en true
  }
}
```

- Capa sin entrada en `tiempo.capas` = visible toda la duración.
- Validación en `escena.validar` (`escena.py:323`): ids existentes, `0 ≤ inicio < fin ≤ duracion_s`,
  ≤1 capa con `audio`. Topes de `duracion_s` y de nº de tramos: decisión abierta.
- `a_html` (`escena.py:798-842`) gana un parámetro opcional `en_t: float | None`
  y `ocultar_video: bool`: pinta solo capas visibles en `t` y deja hueco transparente
  donde va un video. Sin parámetros = salida idéntica a hoy (regresión).
- `reformatear` (`escena.py:873`) conserva `tiempo` sin cambios.

### En la DB

- `content_queue`: ya tiene `template_id`, `campos_json`, `aspecto`, `video_json`
  (agregadas en `src/db.py`, `:266-273`, `:377-395`).
  - `video_json` hoy es el `Video` narrado (`video_model.py:80-92`); **no** se reusa.
  - Columna nueva nullable `escena_render_json`: `{duracion_s, tramos, fuente_videos[], ffmpeg_args_hash}` para re-render y auditoría.
- `brand_templates`: sin cambios; el `tiempo` viaja en `layout_json` y queda en `template_versions`.

### Campo de video en el contrato

- Hoy una capa `video` solo se liga a un dato de tipo `imagen` (`escena.py:285-291`);
  `contrato.TIPOS` no tiene `video` (`src/plantillas/contrato.py:25-26`).
- Propuesta: agregar `video` a `TIPOS` (aditivo); `validar_campos` (`contrato.py:255`)
  exige URL/ruta de asset `tipo='video'` de la misma marca (`schema.sql:568-591`).

## 2. Composición (algoritmo)

1. Cortes de tiempo = unión de todos los `inicio_s`/`fin_s` + 0 + `duracion_s`.
2. Por cada tramo `[a,b)`: `a_html(escena, en_t=a, ocultar_video=True)` → Jinja con
   campos (`render.contexto`, `render.py:32`) → PNG transparente del `.card`.
   - Requiere opción `omit_background` en `_screenshot_card`; hoy no existe (`compose.py:148-200`).
3. Por cada capa video: `-ss recorte_s` (+ `-stream_loop -1` si `bucle`),
   `scale` + `crop` al `w×h` de la capa según `ajuste` cover/contain, `overlay=x:y`
   con `enable='between(t,inicio,fin)'`.
4. Fondo del lienzo: color/gradiente del primer PNG; los PNG por tramo encima con `enable`.
5. Orden z: el de `a_html` (`z`, luego `id`, `escena.py:814-816`). Un video entre dos
   capas estáticas obliga a partir el PNG en "debajo" y "encima" del video.
6. Codificación: mismos parámetros que el reel (`libx264`, `crf 20`, `maxrate 4500k`,
   `yuv420p`, `+faststart`, `video_render.py:41`, `:480-482`).
7. Subida: `host.upload_video` (`src/host.py:61`).

Lo que ffmpeg no replica de la capa `video` (máscara, filtros CSS, `mixBlendMode`,
`_visual`, `escena.py:650`): ver decisión abierta (rechazar vs aproximar).

## 3. API

Bajo `/brands/{slug}`, `marca_para(..., minimo=...)` (`api/deps.py:36-44`).

| Endpoint | Rol | Qué hace |
|---|---|---|
| `PUT /templates/{id}` (existente) | manager | acepta `layout_json.tiempo`; valida con `escena.validar` |
| `POST /templates/{id}/preview-video` (nuevo) | editor | job de preview a baja resolución; devuelve `job_id` |
| `POST /posts` (`api/routers/posts.py:15-37`) | editor | si la plantilla tiene `tiempo`, encola `post.video` en vez de `post.generar` |
| `POST /cola/{qid}/rerender` | editor | reusa `escena_render_json`; sin LLM |

## 4. Jobs

| Job | Qué hace |
|---|---|
| `post.video` (nuevo) | `generar_campos` (igual que post) → composición → upload → `content_queue tipo='video'` |
| `post.video_preview` (nuevo) | igual, sin cola; mp4 temporal; resolución/duración reducidas |
| `post.video_rerender` (nuevo) | gemelo de `rerender_video` (`handlers.py:706-748`) sobre `escena_render_json` |

- Registro en `HANDLERS` (`handlers.py:833-855`); progreso con `jobs.progresar`
  como `video_render.render` (`video_render.py:384-386`).
- Aislamiento: una corrida por cuenta (`src/jobs/__init__.py:52-97`). No entra a `TIPOS_IG` (`:48`).
- `rescatar_huerfanos(max_min=30)` (`jobs/__init__.py:139`) marcaría huérfano un render
  largo; duración máxima de render: decisión abierta.
- Archivos temporales en `tempfile.mkdtemp` como `video_render.py:389`; limpieza al final (hoy `video_render` no limpia: sin verificar si es intencional).

## 5. Frontend

Base: `frontend/app/b/[slug]/templates/[id]/_components/`.

- `panel-tiempo.tsx` (nuevo): barra por capa (inicio/fin arrastrables), duración total, cabezal.
- `capa-vista.tsx:176-187`: el `<video>` sigue el cabezal (`currentTime = t - inicio + recorte`);
  capas fuera de ventana se atenúan.
- `panel-propiedades.tsx:477-500`: sección Video gana `recorte_s`, `bucle`, `audio`.
- `barra-superior.tsx`: botón "Vista previa video" → job preview → reproduce mp4.
- `panel-assets.tsx` ya sube mp4/webm hasta 100 MB (`panel-assets.tsx:32`, `:177`;
  `src/assets/biblioteca.py:36`).
- La vista en navegador es aproximada; la verdad es el mp4 del servidor (se dice en la UI).

## 6. Aislamiento por marca

- `_SRC` solo admite `assets/…` o `fotos/…` (`escena.py:53`); el compositor resuelve
  esas rutas solo dentro del directorio de la marca dueña de la plantilla.
- Un `campo` de tipo video con asset de otra marca → `CamposInvalidos`.
- `sandbox` de `_screenshot_card` (solo `file:`/`data:`, `compose.py:173-181`) se fuerza
  en los PNG de tramo, independiente de `config.TEMPLATE_RENDER_SANDBOX`.
- ffmpeg recibe solo rutas locales ya resueltas; nunca URLs de la escena.

## 7. Riesgos

| Riesgo | Mitigación |
|---|---|
| Derechos de clips de terceros (pexels, pixabay, coverr, giphy, ig_seguidos; `src/fuentes.py:19`) | `ig_seguidos` = reels ajenos: bloquear en video publicado salvo decisión contraria; licencia de los bancos sin verificar por proveedor |
| Música/audio con derechos dentro del clip | `audio=false` por default |
| Chromium de Playwright quizá no decodifica H.264 → primer cuadro negro en PNG | sin verificar; probar en la VM; fallback: `poster` obligatorio |
| Costo CPU/tiempo de render en la VM compartida | 1 por cuenta + tope global (`tomar`, `max_global`); tope de duración (decisión) |
| Fidelidad CSS ≠ ffmpeg en capas video (máscara, blend, filtros) | validar y rechazar en `tiempo` (default) |
| Especificaciones de Reels de IG (duración, peso, codec) | sin verificar; hoy `max_duracion_s` del preset llega hasta 180 (`api/routers/perfil.py:313`) |
| Costo IA | igual que un post: un `generar_campos`; el render no llama LLM |
| Muchos tramos → muchos screenshots | tope de tramos (decisión) |

## 8. Pruebas

- Unit `escena.validar` con `tiempo`: ventanas inválidas, id inexistente, dos `audio`.
- Unit `a_html(en_t=…, ocultar_video=True)`: oculta fuera de ventana; sin args, salida byte a byte igual a la actual.
- Unit cortes de tiempo y orden z (función pura, sin ffmpeg).
- Unit argumentos ffmpeg generados (string), incluido `enable='between(...)'`.
- Integración con clip de fixture de 2 s: mp4 sale, `ffprobe` da la duración pedida ± 1 cuadro.
- API: aislamiento A/B en preview y `POST /posts` con asset ajeno → 404/422.
- Migración: DB vieja + `db.init` → `escena_render_json` nula; filas intactas.
- Regresión: `generate_video` y `rerender_video` sin cambios (tests existentes, p. ej. `tests/test_video_importar.py`).
- Frontend: vitest de `panel-tiempo` (arrastre, límites).
- Sin publicar a IG en pruebas; verificación manual en una marca de staging.

## Fuera de alcance

- Keyframes (posición/escala/opacidad animadas), transiciones entre tramos.
- TTS y subtítulos por palabra (siguen en `video_render`).
- Fusionar el motor narrado con este compositor.
- Videos de material de fuentes de texto (subproyecto 2 entrega texto, no clips).
- TikTok.

## Decisiones abiertas para Ricardo

1. **Motor de composición.** Default: híbrido PNG por tramo + ffmpeg (vs captura cuadro a cuadro con Playwright).
2. **Duración máxima del video de plantilla.** Sin cifra. Default: la de `preset.max_duracion_s` de la marca.
3. **Tope de tramos/capas con tiempo.** Sin cifra. Default: lo fijas tras medir render en la VM.
4. **Efectos CSS en capa video que ffmpeg no replica.** Default: rechazarlos al validar `tiempo`.
5. **Audio.** Default: solo el de un clip con `audio=true`; sin música ni TTS.
6. **Clips de `ig_seguidos` en video publicado.** Default: bloqueados.
7. **Agregar `video` a `contrato.TIPOS`.** Default: sí, aditivo.
8. **Aspectos permitidos para video.** Default: solo 9:16 (`escena.py:21-22`), como el reel actual.
9. **Tiempo máximo de un job de render vs `rescatar_huerfanos(30 min)`.** Default: tope de render menor a 30 min; si no alcanza, subir el umbral solo para `post.video`.
10. **Columna `escena_render_json` vs reusar `video_json`.** Default: columna nueva; `video_json` sigue siendo del motor narrado.
