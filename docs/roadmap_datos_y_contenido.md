# Roadmap @gdlscene — De Sheet plano a base de datos viva + nuevos formatos

> Cómo evolucionar el bot actual (DeepSeek → Playwright → Telegram → IG Graph) hacia
> un sistema que se alimenta solo: escrapea las bandas que sigues, clasifica fotos y
> data, y genera no solo memes sino anuncios y Reels. Pensado alrededor de 5 repos:
> `instaloader`, `FaustRen/instagram-posts-scraper`, `spotipy`, `gyoridavid/short-video-maker`,
> `mohammedelahmar/tiktok-agent`.

---

## 0. Diagnóstico: qué ya tienes y dónde está el cuello de botella

Tu pipeline (Proceso A) ya resuelve lo difícil: voz editorial, composición, aprobación humana,
hosting, publicación y calendarización. Todo se dispara desde filas `pending` del Sheet con
estos campos: `banda`, `integrante`, `rol`, `tema_semilla`, `foto_url`, `foto_inset_url`.

**El límite hoy es el INPUT, no el OUTPUT.** Cada meme depende de que alguien llene a mano:
quién es la banda, quién es el integrante, qué foto usar. El proyecto escala tanto como tu
capacidad de meter buenas filas. Todo este roadmap ataca esa capa: convertir "las bandas que
sigo en IG" en una base de datos rica que llene el Sheet sola.

---

## 1. La pieza central: una DB relacional (SQLite) detrás del Sheet

Hoy la "DB" es una hoja plana. Para clasificar bien y automatizar incluso sin estar
escrapeando, conviene una DB relacional local (SQLite, cero infraestructura). El Sheet
**sigue siendo tu UI de aprobación**, pero la fuente de verdad pasa a ser la DB; un job
sincroniza filas `pending` hacia el Sheet.

Esquema mínimo propuesto:

```
bands
  id, nombre, ig_handle, spotify_id, ciudad, activa(bool),
  popularity, followers_ig, followers_spotify, monthly_listeners,
  generos (json), n_integrantes, prioridad(1-5), notas

members
  id, band_id(fk), nombre, rol, ig_handle,
  foto_principal_id(fk photos), confiabilidad(0-1)   # qué tan seguro mapeaste nombre↔rol

photos
  id, band_id(fk), member_id(fk, nullable),
  path, source_post_id, fecha,
  faces_count, es_grupal(bool), nitidez(float),       # varianza Laplaciano
  usable_meme(bool), caption_original, usada(bool)

events
  id, band_id(fk), tipo(fecha|flyer|release),
  fecha_evento, lugar, ciudad, flyer_path,
  source_post_id, parseado_por_llm(bool), status(nuevo|anunciado|pasado)

content_queue   # equivale a tus filas pending, pero generado por la DB
  id, tipo(meme|anuncio|reel), band_id, member_id, photo_id, event_id,
  tema_semilla, status, scheduled_datetime
```

Por qué importa cada decisión:
- `prioridad` + `popularity` deciden a qué bandas dedicarles más contenido (más alcance).
- `usable_meme` y `nitidez` son el filtro que evita memes con fotos borrosas o sin caras.
- `usada` evita repetir la misma foto.
- `events` habilita los anuncios automáticos sin tocar el flujo de memes.

---

## 2. Pipeline de ingesta (Proceso C — corre cuando escrapeas)

Flujo end-to-end, por banda que sigues:

1. **Lista de objetivos.** `instaloader` con tu login obtiene a quién sigues
   (`Profile.get_followees()`). Filtras manualmente una vez cuáles son bandas/artistas y
   los marcas en `bands`. (Esto se hace una vez; luego solo agregas nuevos.)

2. **Perfil + posts.** Por cada `ig_handle`, `instaloader` baja: bio, follower count, link
   externo (casi siempre Linktree/Spotify → te sirve para el match de Spotify), y los últimos
   N posts con imagen, caption y fecha. `FaustRen/instagram-posts-scraper` es la alternativa
   en Python puro si quieres data estructurada de posts sin la CLI de instaloader.

3. **Routing de cada post** (aquí está la inteligencia):
   - ¿Es **foto de integrantes**? → candidata a meme. Va a `photos`.
   - ¿Es **flyer / anuncio de fecha**? → va a `events`.
   - ¿Es otra cosa (merch, repost, story random)? → se descarta.

   El clasificador combina dos señales baratas:
   - **Visual**: detección de caras (mediapipe o `face_recognition`/OpenCV) → cuenta caras,
     marca `es_grupal`; nitidez con varianza del Laplaciano (descarta borrosas). Imagen con
     mucho texto y pocas caras → probable flyer.
   - **Texto**: el caption + OCR del flyer (tesseract). Palabras como *toca, show, presale,
     boletos, sold out, fecha, gira, lanzamiento, nuevo single* → `events`.

4. **Enriquecimiento Spotify** (`spotipy`): matcheas la banda (search por nombre, confirmas con
   el link de la bio) y guardas `popularity`, `followers`, `generos`, top tracks. Esto NO da
   reproducciones ni "related artists" (Spotify lo restringió), pero popularity + géneros bastan
   para clasificar y priorizar.

5. **Parseo de eventos con LLM** (DeepSeek, que ya usas): le pasas caption + texto OCR y pides
   JSON estructurado `{fecha, lugar, ciudad, tipo}`. Llenas `events`.

Resultado: tras una sesión de scraping, tu DB tiene bandas clasificadas por género/popularidad,
fotos puntuadas y listas para meme, y eventos detectados — todo lo que tu Proceso A necesita,
generado solo.

---

## 3. Selección de fotos para meme (el mayor multiplicador de calidad)

Tus memes viven o mueren por la foto. Regla de selección automática para llenar `foto_url`:
- descarta `faces_count == 0` y nitidez baja;
- prefiere foto donde el integrante salga **claro** (cara grande, frontal);
- si quieres meme de integrante específico, usa *face clustering* (agrupar caras por persona)
  sembrando una foto etiquetada por banda; así mapeas `member_id` a futuras fotos solo.
- marca `usable_meme=true` solo a las que pasen el filtro; el Sheet jala de ahí.

Realidad útil: **nombre↔rol casi nunca está en IG.** Tres caminos, de menos a más esfuerzo:
(a) dejar `rol`/`integrante` vacíos → tu prompt ya maneja eso hablando de la banda como
colectivo; (b) sembrar el lineup a mano una vez por banda (tabla `members`); (c) que DeepSeek
+ búsqueda web rellene lineup. Recomiendo (b) para tus bandas top y (a) para la cola larga.

---

## 4. Nuevo formato: anuncios automáticos (fechas, flyers, releases)

Tu necesidad explícita. Reutiliza casi todo el Proceso A, cambiando solo plantilla y voz:

- Disparador: filas nuevas en `events`.
- Generación: una plantilla distinta (`templates/anuncio.html`) — informativa pero con el sello
  @gdlscene. Dos sabores: (1) **repost de flyer** limpio con tu marca de agua; (2) **tarjeta
  satírica-informativa**: el dato real (fecha/lugar) enmarcado con un titular deadpan.
- Calendarización **consciente de la fecha**: el scheduler debe publicar el anuncio *antes* del
  evento, no en el siguiente hueco genérico. Añade a `scheduler.py` un modo "urgente" que
  respete `fecha_evento`.
- Para releases nuevos: `spotipy` detecta single/álbum nuevo (compara contra última vez) →
  genera anuncio automático.

Cuidado editorial: en anuncios reales (fechas que la gente usa para ir al show) la info debe ser
**correcta**, no satírica. Mantén satírico el meme; mantén fiel el anuncio. Puedes mezclar tono
en el copy pero nunca falsear fecha/lugar.

---

## 5. Nuevo formato: Reels / TikTok (expandir la voz a video corto)

Mismo cerebro editorial, nuevo lienzo. Dos repos, dos casos:

- **`gyoridavid/short-video-maker`** (texto/imagen → video vertical con voz, subtítulos, música).
  Caso ideal: tomas un titular ya aprobado + la foto de la banda + un fondo musical, y generas un
  Reel donde el titular se "teclea" o se narra. Convierte tu catálogo de memes en Reels sin
  trabajo creativo extra. Expone MCP + REST, fácil de invocar como un Proceso A' paralelo.
  (Nota: el repo no se actualiza desde mediados de 2025; pruébalo antes de casarte con él.)

- **`mohammedelahmar/tiktok-agent`** (extrae clips "virales" de videos largos). Caso ideal: si
  consigues videos de shows en vivo, entrevistas o sesiones, el agente recorta los segmentos con
  más gancho y los deja en vertical, listos para que tú les pongas el titular @gdlscene encima.

Idea puente: "meme → reel" automático. Toda fila aprobada en `content_queue` con `tipo=meme`
puede clonarse a `tipo=reel` y mandarse a short-video-maker con el top track de Spotify de esa
banda como audio. Mismo chiste, doble formato, doble plataforma.

---

## 6. Banco de ideas de contenido (para el ask "dame más ideas así")

Ordenadas por relación esfuerzo/impacto, todas alimentadas por la DB:

1. **Loop de crecimiento por @menciones.** Cada meme/anuncio etiqueta a la banda (`ig_handle` ya
   está en la DB). Si la banda lo reshares, te crece la cuenta. Es probablemente tu palanca #1.
2. **Power rankings satíricos.** Usa `popularity` de Spotify para "el top 10 de la escena tapatía
   según un comité que nadie eligió". Tier-lists generan mucho engagement y debate.
3. **Contenido reactivo (timely).** Cuando una banda postea algo, generas en horas un titular
   deadpan "respondiendo". Lo reciente rinde más en el algoritmo.
4. **Series por género.** Agrupa bandas por `generos` de Spotify → "semana del punk tapatío", etc.
   Da estructura editorial y facilita programar.
5. **Generador de colabs falsas.** Empareja dos bandas random de la DB → titular de "colaboración"
   absurda. Material infinito y muy compartible entre las dos fanbases.
6. **Throwback / aniversarios.** Post más viejo de una banda → "hace X años…" satírico.
7. **Digest semanal en Reel.** Junta todos los `events` de la semana → un Reel "esta semana en la
   escena" (informativo + sello @gdlscene). Recurrente y programable.
8. **Alertas de release.** Single nuevo detectado por spotipy → anuncio automático.
9. **Stories de engagement.** Encuestas auto-generadas ("¿qué banda…?") con nombres de la DB.
10. **Quote-cards.** El mismo motor de titular, pero formato "cita" sobre foto del integrante.

---

## 7. Orden de construcción (fases, no big-bang)

- **Fase 1 — DB + sync (1 fin de semana).** Crea SQLite con el esquema, y un script que sincroniza
  filas `pending` DB → Sheet. No rompes nada del Proceso A; solo cambias de dónde salen las filas.
- **Fase 2 — Ingesta básica.** `instaloader` baja perfil + posts de tus bandas top. Llena `bands`
  y `photos` (sin clasificar todavía; solo guarda fotos + nitidez).
- **Fase 3 — Clasificación de fotos.** Caras + nitidez → marca `usable_meme`. Ya tu Sheet jala
  fotos buenas solo. Aquí ya sientes el salto de productividad.
- **Fase 4 — Spotify.** `spotipy` enriquece popularity/géneros → habilita priorización y series.
- **Fase 5 — Eventos/anuncios.** Routing flyer + OCR + parseo LLM → tabla `events` + plantilla de
  anuncio + scheduler consciente de fecha.
- **Fase 6 — Video.** short-video-maker clona memes a Reels; tiktok-agent para material de video.

Cada fase entrega valor solo y no bloquea a la anterior.

---

## 8. Riesgos y límites (leer antes de escalar)

- **ToS de Meta.** `instaloader` y cualquier scraping de IG van contra los términos. Riesgo real de
  bloqueo de cuenta/IP. Mitiga: usa una cuenta secundaria para escrapear (no la de @gdlscene),
  límites bajos, *delays* aleatorios, no corras a diario masivamente. Trátalo como ingesta puntual,
  no como un crawler 24/7.
- **Spotify.** popularity/followers/genres OK por API oficial; reproducciones y related-artists NO.
  No uses la data de Spotify para entrenar modelos (su ToS lo prohíbe).
- **Personas reales.** Estás satirizando músicos reales y descargando sus fotos. Tu prompt ya
  bloquea acusaciones creíbles de delitos (bien). Mantén ese guardarraíl, no toques temas
  sensibles (sexual, violencia real, menores), y recuerda que el loop de @menciones funciona por
  *goodwill*: si una banda pide bajar algo, bájalo. Eso protege la cuenta y la relación con la escena.
- **Calidad de datos.** El OCR de flyers y el match de Spotify fallan seguido; deja siempre el paso
  de aprobación humana por Telegram antes de publicar un anuncio con fecha.

---

## 9. Cómo encaja cada repo

| Repo | Rol en tu sistema | Fase |
|---|---|---|
| `instaloader` | Bajar perfil, posts, fotos y captions de las bandas que sigues | 2 |
| `FaustRen/instagram-posts-scraper` | Alternativa Python para data estructurada de posts | 2 |
| `spotipy` | Enriquecer bandas: popularity, followers, géneros, releases | 4 |
| `gyoridavid/short-video-maker` | Clonar memes/titulares a Reels verticales | 6 |
| `mohammedelahmar/tiktok-agent` | Extraer clips de videos largos de shows/entrevistas | 6 |

Tu stack actual (DeepSeek, Playwright, Telegram, Cloudinary, Sheets, IG Graph, scheduler) no se
toca: estos repos solo **alimentan y extienden** el pipeline que ya funciona.
