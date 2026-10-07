# 2026-10-06 — Editor de diseños v2: escena JSON, editor tipo Figma, chat IA y fuentes de assets

Estado: borrador para revisión de Ricardo.
Subproyecto 1 de 3. Los otros dos tienen spec propio:
2. Fuentes de contenido por marca (Reddit por subreddit, IA con prompt, RSS, X).
3. Compositor de video sobre la misma escena.

## Problema

El editor de `Diseños` está a medio construir (auditoría 2026-10-06, rama `master` 38f30e9):

- `templates/[id]/page.tsx` solo usa `useDiseno`, `useFuentes`, `useStickers`. Nunca llama a `useGuardarDiseno`, `usePreviaDiseno`, `usePedirDiseno`, `useActivarDiseno`, `useVersiones` ni `useRevertir` (`hooks/use-disenos.ts`). Resultado: no guarda, no agrega capas, no hay panel de propiedades, no hay vista previa real, no hay chat de IA.
- El lienzo muestra placeholders fijos: «Foto» (`capa-vista.tsx:206`), `«campo»` (`:239`). El diseño de la captura es `layout.py:209 vacio()`.
- `GET /templates` solo lista diseños `activa` (`api/routers/plantillas.py:42`) y la UI no puede activar. El creador de posts no tiene diseños que ofrecer.
- Los posts de calidad que sí existen (Daisies, `~/Work/daisies/creativos/NUEVAS CAMPAÑAS/*/gen.py`, `gen-*.js`) salen de un proceso que instagod no replica: el LLM llena un spec por tipo de layout, un HTML/CSS fijo y probado lo dibuja y Playwright lo rasteriza.

## Objetivo

1. Editor dentro de instagod que se sienta como Figma: mover, redimensionar, rotar, guías, capas, propiedades, deshacer, guardar.
2. Un chat de IA que construye el diseño con el mismo proceso que los creativos de Daisies y lo deja editable con arrastrar y soltar.
3. Fuentes de fotos y video configurables por marca, todas gratuitas, incluyendo **fotos de las cuentas que sigue una cuenta de Instagram**, disponible para cualquier marca (para crear más cuentas tipo @gdlscene).

Criterio de éxito: desde el portal, para shit.book, melaquecapital y gdlscene, pedir en el chat «post de X» produce un diseño 4:5 con foto real, recortes y tipografía de marca. El diseño se ajusta a mano y queda guardado y activo. El creador de posts lo usa para renderizar el PNG final, y el PNG es idéntico al lienzo.

## Decisiones

| Decisión | Elección | Por qué |
|---|---|---|
| Librería de editor | Propia. Sin Polotno ni IMG.LY | Ricardo, 2026-10-06: «todo propio» |
| Motor de edición | DOM con posición absoluta + `react-moveable` / `react-selecto` | El render final es Chromium (Playwright). Un editor de DOM da paridad exacta de texto, tracking, `text-wrap`, blend y filtros. Konva/Fabric dibujan el texto distinto. ⚠️ Licencia y mantenimiento de moveable/selecto se verifican en el paso 0 del plan |
| Fuente de verdad | Escena JSON v2 en `brand_templates.layout_json` | Se edita por coordenadas y se compila a HTML para el render |
| Cómo diseña la IA | Biblioteca de *kinds* (layouts Jinja probados) + spec → render → extracción de capas | Replica el proceso de Daisies. El HTML libre del LLM no es editable ni consistente |
| Modelo del chat de diseño | Claude Sonnet 5.5 (`claude-sonnet-5-5`) con visión | Se revisa su propio render. DeepSeek, el proveedor por defecto, no tiene visión. El resto de instagod sigue en DeepSeek |
| Fuentes de assets | Solo gratuitas: Unsplash, Pexels, Pixabay, Openverse, Coverr, Giphy, biblioteca propia, seguidos de IG, IA (fal.ai) opcional | Ricardo, 2026-10-06. Pinterest se descarta: la API de búsqueda es solo para partners y los términos prohíben el scraping |
| Quitar fondo | `rembg` en el servidor (MIT) con modelo BiRefNet (MIT) | BRIA RMBG 2.0 es CC BY-NC e imgly es AGPL: descartados |
| Tipografías | `brand_fonts` + catálogo Fontsource descargado al servidor | Se mantiene la regla actual: nada desde CDN en el render (`src/plantillas/fuentes_tipograficas.py`) |

## 1. Escena JSON v2

```jsonc
{
  "v": 2,
  "lienzo": { "w": 1080, "h": 1350, "formato": "4x5", "fondo": { "tipo": "color|gradiente|imagen", "valor": "#FBFAF7" } },
  "tokens": { "colores": { "ink": "#1C1A23", "accent": "#F5C842" }, "fuente": "Hanken Grotesk" },
  "capas": [
    {
      "id": "c_titular", "nombre": "Titular", "tipo": "text",
      "x": 72, "y": 196, "w": 936, "h": 320, "rot": 0, "opacity": 1, "z": 10,
      "bloqueada": false, "oculta": false,
      "campo": "titular",              // opcional: se llena con datos del post al renderizar
      "texto": "Lo que le regalas\n+ lo que la cuida.",
      "estilo": { "fontFamily": "Hanken Grotesk", "fontWeight": 800, "fontSize": 96, "lineHeight": 1.02,
                  "letterSpacing": "-0.03em", "color": "token:ink", "textAlign": "left", "textWrap": "balance",
                  "spans": [{ "desde": 18, "hasta": 36, "color": "token:accent" }] },
      "anclaje": "top"                 // top|bottom|center: cómo se mueve al pasar de 4:5 a 9:16
    },
    {
      "id": "c_foto", "tipo": "image", "x": 540, "y": 600, "w": 480, "h": 600, "rot": -6, "z": 5,
      "campo": "foto",
      "src": "assets/<sha>.png", "recorte": true, "ajuste": "cover|contain", "mascara": "none|circle|rounded:48",
      "estilo": { "filter": "drop-shadow(0 24px 48px rgba(61,53,128,.35))", "mixBlendMode": "normal" },
      "fuente_asset": { "proveedor": "unsplash", "autor": "…", "licencia": "Unsplash", "url": "…", "ig_handle": null }
    }
  ]
}
```

- Tipos de capa: `text | image | video | shape | svg | group`. `video` existe en el esquema; su render se resuelve en el subproyecto 3. En este subproyecto el PNG muestra el primer cuadro.
- `campo` mantiene el contrato actual (`contrato_json`): el creador de posts sigue llenando campos por nombre.
- Migración: `layout.py` gana `v1_a_v2()`. Los `layout_json` v1 existentes se convierten al leerlos y se guardan como v2 la siguiente vez que se guardan. Sin migración destructiva.
- `a_html(escena)` reemplaza a `layout.py:359`. Cada capa se vuelve un `div` absoluto con su estilo. Los campos se sustituyen con Jinja. El mismo HTML sirve para la vista previa y el render final (`render.py:49` sin cambio de contrato).

## 2. Editor (frontend)

Ruta existente: `app/(portal)/[marca]/templates/[id]`. Se rehace `_components/` y se mantiene la ruta.

- **Lienzo**: HTML de la escena en un contenedor escalado (zoom 10–400 %, desplazamiento con espacio + arrastre o con trackpad). `react-moveable` para mover, redimensionar, rotar y guías magnéticas a bordes, centros y otras capas. `react-selecto` para selección múltiple con recuadro y shift.
- **Texto**: doble clic edita en el lienzo con `contentEditable`, con soporte de *spans* de color (acento en la última línea, el patrón de Daisies).
- **Panel de capas** (izquierda): árbol con dnd-kit, ya instalado. Reordenar, agrupar, ocultar, bloquear, renombrar.
- **Panel de propiedades** (derecha), según el tipo de capa:
  - texto: fuente, peso, tamaño, interlineado, tracking, alineación, color o token, sombra
  - imagen: reemplazar, recortar o quitar fondo, ajuste, máscara, radio, filtros, sombra
  - forma: relleno, borde, radio
  - comunes: posición, tamaño, rotación, opacidad, blend, vínculo a `campo`
- **Barra superior**: formato 4:5 / 1:1 / 9:16 (reacomoda capas según su `anclaje`, el mismo algoritmo `P.Y` de `hombres-regalale-daisies/gen.py`), deshacer y rehacer, alinear y distribuir, Guardar, Vista previa real, Activar, Versiones.
- **Estado**: store con zustand + historial de parches (immer); ambas son dependencias nuevas, hoy no están en `frontend/package.json`, para deshacer y rehacer. Se guarda solo (con *debounce* de 2 s) como borrador. «Guardar versión» crea una fila en `template_versions`.
- **Atajos**: ⌘Z / ⇧⌘Z, ⌘C / ⌘V / ⌘D, Supr, flechas (1 px; con shift, 10 px), ⌘G agrupar, ⌘] / ⌘[ para el orden z.
- **Conectar los hooks que ya existen** en `hooks/use-disenos.ts`: guardar, vista previa, activar, versiones, revertir, pedir diseño.
- **Panel de assets** (pestaña izquierda): búsqueda unificada en las fuentes activas de la marca, arrastrar al lienzo, subir archivo propio, «quitar fondo».

## 3. Chat de IA

Panel derecho, con pestaña junto a Propiedades. Cada mensaje produce una fila en `template_versions`, como ya documenta el esquema.

### Crear desde cero
1. **Brief**: mensaje del usuario + marca (`Marca`: voz, tokens, fuentes, logo) + formato.
2. **Elegir kind y llenar el spec**: el LLM recibe el catálogo de kinds con su esquema de spec y devuelve, por *tool use* con esquema validado:
   - el kind y el spec (textos, acentos, tema)
   - las búsquedas de assets (`{"slot": "foto", "query": "...", "recorte": true}`)
3. **Assets**: `assets.buscar()` contra las fuentes activas de la marca. Toma el primer resultado viable, quita el fondo si `recorte`, cachea y registra la atribución.
4. **Render**: el kind Jinja + tokens de marca + spec → HTML → Playwright PNG.
5. **Autocrítica** (una sola pasada): el LLM ve el PNG y puede devolver un spec corregido si encuentra texto desbordado, contraste pobre o una foto que no corresponde. Máximo 1 reintento, para acotar el costo.
6. **Extracción a capas**: en la misma página de Playwright, un script recorre los nodos marcados con `data-capa` y lee `getBoundingClientRect()` y `getComputedStyle()`. Con eso arma la escena v2. Los kinds se escriben para que cada elemento editable tenga `data-capa` y `data-campo`.
7. Se abre en el editor ya editable.

### Editar uno existente
- El LLM recibe la escena v2 (sin `src` largos) y la instrucción. Devuelve operaciones: `[{op:"set", capa, ruta, valor} | {op:"add", capa} | {op:"del", capa} | {op:"buscar_asset", capa, query}]`.
- Las operaciones se validan contra el esquema y se aplican como un paso del historial, así que se deshacen con ⌘Z.

### Biblioteca de kinds (`src/plantillas/kinds/`)
- Un archivo `.html.j2` + `.schema.json` por kind, parametrizados con los tokens de la marca. Nada de Daisies queda fijo en el código.
- Primer lote, portado de los creativos de Daisies y de lo que piden las marcas:

| Kind | Origen | Uso típico |
|---|---|---|
| `side` | Daisies | texto a un lado, foto o recorte al otro |
| `stat` | Daisies | número gigante + contexto |
| `vs` | Daisies | comparación de dos lados |
| `compare` | Daisies | recortes con etiquetas de precio contra la oferta |
| `list` | Daisies | 3–5 puntos |
| `cta` | Daisies | cierre con llamado a la acción |
| `meme` | gdlscene / shit.book | foto a sangre + texto superior/inferior, o captura tipo tweet |
| `historia` | shit.book | relato largo partido en slides (carrusel) |
| `cita` | general | testimonio o frase |
| `propiedad` | Melaque | foto de casa + precio + datos clave |

- Ingredientes visuales disponibles como parciales (macros Jinja):
  - `sticker` rotado
  - `recorte` con sombra
  - `telefono` (mockup)
  - `elemento_marca` que se sale del borde (logo o ícono de la marca)
  - `pill`, `coin`, grano y textura

## 4. Fuentes de assets por marca

Se reusa `brand_sources` (`kind='imagen'`) y se agrega `kind='video'`. Los proveedores implementan la interfaz actual de `src/image_sources.py` (`buscar(hint, n) -> list[ImagenCandidata]`). `ImagenCandidata` gana `tipo` (`imagen|video`), `autor`, `licencia`, `url_origen` y `ancho/alto`.

| Proveedor | Imagen | Video | Llave | Límite / regla | Estado |
|---|---|---|---|---|---|
| `carpeta` (biblioteca de la marca) | ✅ | ✅ | — | — | existe, se extiende a video |
| `unsplash` | ✅ | — | `UNSPLASH_ACCESS_KEY` (`brand_secrets`) | 50/h demo, 5000/h prod; atribución obligatoria | existe |
| `pexels` | ✅ | ✅ | `PEXELS_API_KEY` | 200/h, 20k/mes | existe (foto), se agrega video |
| `pixabay` | ✅ | ✅ | `PIXABAY_API_KEY` | 100/min; **descargar y cachear 24 h, no enlazar directo** | nuevo |
| `openverse` | ✅ | — | opcional (OAuth) | 100/día anónimo, 10k/día con llave; se filtra por licencia comercial | nuevo |
| `coverr` | — | ✅ | `COVERR_API_KEY` | 2000/h prod | nuevo |
| `giphy` | ✅ stickers | ✅ mp4 | `GIPHY_API_KEY` | 100/h beta; mostrar el logo «Powered by GIPHY» en el selector | nuevo |
| `ig_seguidos` | ✅ | ✅ (reels, primer cuadro en PNG) | pool de cookies existente (`ingest_ig.SesionRotatoria`) | ritmo del pool actual | **generaliza lo de gdlscene** |
| `ia_imagen` (fal.ai) | ✅ | — | `FAL_KEY` | de pago por imagen: **apagado por defecto**, solo si la marca lo activa | nuevo |
| `banco`, `covers` | ✅ | — | — | — | existen; siguen exclusivos de gdlscene |
| `pinterest` | — | — | — | — | 🔴 se desactiva en la UI (no cumple términos) |

### Fuente `ig_seguidos` (cualquier marca)
Hoy la cadena es exclusiva de gdlscene: `import_followees` → `bands` (`tipo` banda/solista/…) → `ingest_ig` → `photos`. Se generaliza sin tocar las tablas de gdlscene:

- Tabla nueva `brand_ig_cuentas`: `account_id, ig_handle, nombre, estado (candidata|activa|descartada), origen (seguido_de:<handle>|manual), scraped_at, notas`. UNIQUE `(account_id, ig_handle)`.
- Tabla nueva `brand_assets`, la biblioteca única de la marca: `account_id, tipo (imagen|video), path, sha, proveedor, autor, licencia, url_origen, ig_handle, source_post_id, ancho, alto, tags_json, recorte_path, usada, descartada, creado_en`. UNIQUE `(account_id, sha)`. Aquí caen todos los assets: los descargados de proveedores, los subidos y los ingeridos de IG.
- Flujo en **Ajustes → Fuentes → Instagram**:
  1. Escribes la cuenta semilla (por ejemplo, la cuenta de la marca).
  2. Se importa su lista de *following* como `candidata`, reusando `import_followees.listar_following`.
  3. Apruebas o descartas las cuentas en una lista con avatar y bio.
  4. Un job `ig.ingerir` baja los últimos N posts de las cuentas activas a `brand_assets`, reusando `ingest_ig.fetch_profile`.
- En el editor, el proveedor aparece como «Seguidos de IG», con búsqueda por handle y por texto del caption.
- La atribución `@handle` se guarda en la capa y el creador de posts la puede inyectar en el caption.
- ⚠️ Riesgo declarado: el contenido es de terceros y Meta puede bloquear las cookies del pool. Se mantiene el ritmo y la rotación actuales de `SesionRotatoria`; no se sube la concurrencia.

## 5. Backend: endpoints nuevos o cambiados

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/templates?estado=todas` | La UI de Diseños ve borradores; el creador de posts sigue pidiendo `activa` |
| `PUT` | `/templates/{id}` | Guarda la escena v2 (y compila el HTML) |
| `POST` | `/templates/{id}/activar` | Ya existe el hook; se verifica el endpoint |
| `POST` | `/templates/{id}/chat` | Mensaje → job `diseno.chat` → devuelve la escena nueva o las operaciones |
| `POST` | `/templates/{id}/previa` | PNG real con datos de ejemplo |
| `GET` | `/assets/buscar?q=&tipo=&proveedores=` | Búsqueda unificada en las fuentes activas de la marca |
| `POST` | `/assets/importar` | Descarga a `brand_assets` (cache + atribución) |
| `POST` | `/assets/{id}/recorte` | `rembg` → PNG transparente recortado al contenido |
| `GET/POST` | `/fuentes/ig/cuentas`, `/fuentes/ig/importar-seguidos`, `/fuentes/ig/ingerir` | Gestión de `ig_seguidos` |
| `GET` | `/tipografias/catalogo` | Catálogo de Fontsource; `POST` descarga una familia a `brand_fonts` |

- Los jobs largos (chat, ingesta IG, quitar fondo) van por la cola `jobs` y `src/jobs/worker.py`, como hoy.
- `rembg` y sus modelos aumentan el tamaño de la imagen Docker (⚠️ no medido). El modelo se baja al construir la imagen, no al primer uso.

## 6. Errores y límites

- **Proveedor caído o sin llave**: se salta con un registro en `brand_sources.ultimo_error` (ya existe) y se sigue con el siguiente (cascada actual de `resolver`).
- **LLM devuelve un spec inválido**: se valida contra el esquema del kind; 1 reintento con el error; si vuelve a fallar, se muestra el error en el chat y no se toca la escena.
- **Texto desbordado**: el kind usa `fit` (reducir la fuente hasta un mínimo); la autocrítica lo detecta en el PNG.
- **Extracción a capas imperfecta** (pseudo-elementos, fondos complejos): todo lo que no tenga `data-capa` se aplana en una capa `image` de fondo para no perderlo.
- **Costo del chat**: 1 llamada de diseño + 1 de autocrítica por mensaje. El costo real se mide en el plan y se registra en `jobs`.

## 7. Pruebas

- `pytest`:
  - esquema v2 (válido e inválido)
  - `v1_a_v2` con los `layout_json` existentes
  - `a_html` (snapshot)
  - cada proveedor con respuestas grabadas, sin red
  - aplicador de operaciones del chat
  - spec → HTML de cada kind
- **Ida y vuelta**: kind → render PNG A → extracción a escena → `a_html` → render PNG B; diferencia de píxeles ≤ 1 % por kind.
- **E2E Playwright** contra el portal local: abrir diseño, mover capa, editar texto, guardar, recargar, ver el cambio, activar, verlo en el creador de posts y renderizar.
- La prueba con LLM real (chat de punta a punta) se corre a mano con una marca de prueba (⚠️ hay que crearla; no verifiqué que exista) y se reporta como manual, no como automática.

## Fuera de alcance

- Fuentes de texto (Reddit, X, RSS, prompt por marca): subproyecto 2.
- Render de video y línea de tiempo: subproyecto 3.
- Colaboración en tiempo real, comentarios, multipágina estilo Figma.
- Generación de video con IA.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| `react-moveable` sin mantenimiento | Verificar en el paso 0; si está muerto, implementar las manijas a mano sobre DOM (el editor actual ya arrastra y redimensiona) |
| Diferencias de fuente entre el navegador y Playwright | Ambos cargan las mismas fuentes desde `/fonts` de la marca con `document.fonts.ready` antes de medir o capturar |
| Bloqueo de cookies de IG por ingestas de varias marcas | Cola única de ingesta compartida entre marcas, con el ritmo actual |
| Rama `feat/lote-bimestral-killswitch` con cambios sin commitear | Se trabaja en el worktree `feat/editor-v2` desde `master` 38f30e9 |
