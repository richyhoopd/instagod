# Próximos lanzamientos (releases con fecha futura) + dedup de post

**Fecha:** 2026-06-09
**Estado:** Aprobado

## Problema

Los anuncios de lanzamientos FUTUROS (ej. duckfizz "A Ciegas" sale 19 jun) sí se
detectan (`detect_releases_ig` los registra como `events` tipo=release con
`fecha_evento` futura), pero **no se ven en ningún lado**: "Música Nueva"
(`releases_ventana`) solo muestra releases de los últimos 30 días (pasado).
Además, un post que es imagen-flyer Y anuncia release se **duplica**: `classify`
crea un evento flyer con `source_post_id=<shortcode>` y `detect_releases_ig`
inserta otro con `ig:<shortcode>`; `parse_events` luego convierte el flyer en
release → dos filas release del mismo post (visto en duckfizz "A Ciegas").

Decisión del usuario: **verlos + avisar, yo decido** (sin auto-publicar).

## 1. Vista "Próximos lanzamientos" — `src/generate_agenda.py` + `/calendario`

- `releases_proximos(cx, dias=60, *, hoy=None)`: `tipo='release'`,
  `fecha_evento > hoy` y `<= hoy+dias`, `irrelevante=0`, orden por fecha asc.
- `/calendario` (web/app.py + calendario.html): sección nueva **"🔜 Próximos
  lanzamientos"** ARRIBA de "Música Nueva". Cada fila: banda, título, fecha de
  salida, portada (`cover_url`) y/o permalink del post. Reusa el patrón de la
  sección de releases existente.
- `releases_ventana` (Música Nueva, pasado últimos `dias`) NO cambia.

## 2. Aviso por Telegram más informativo

- `src/novedades.py` y/o `src/check_releases.py`: cuando hay releases nuevos,
  el aviso NOMBRA cada uno distinguiendo futuro vs pasado:
  - futuro: `🔜 {banda} — {titulo} (sale {fecha})`
  - pasado: `🎵 {banda} — {titulo} ({fecha})`
- `detect_releases_ig.detectar` ya devuelve conteos; se extiende para devolver
  también la lista de releases nuevos (banda, titulo, fecha) para el aviso.
  Sin auto-publicación.

## 3. Dedup del mismo post

- **Unificar la llave**: los eventos de origen IG usan `source_post_id =
  <shortcode>` (SIN prefijo `ig:`). `detect_releases_ig` deja de anteponer `ig:`.
- **Merge en vez de insert**: antes de insertar un release, `detect_releases_ig`
  busca un evento existente de ESE post (por `source_post_id = <shortcode>`,
  cualquier tipo) de la misma banda:
  - si existe (p. ej. el flyer que creó `classify`) → lo **actualiza**
    in-place a `tipo='release'`, set `titulo`, `fecha_evento`, `cover_url`,
    `parseado_por_llm=1` (no inserta otra fila).
  - si no existe → inserta con `source_post_id=<shortcode>`.
- El dedup vs Spotify/Deezer (`_es_dupe` por título+fecha ±30 días) se mantiene.
- **Compatibilidad**: el dedup también reconoce `ig:<shortcode>` viejo para no
  re-insertar sobre datos previos.

## 4. Limpieza única — `purgar_releases_dup(cx)` (o script)

- Colapsa releases duplicados existentes: por (band_id, fecha_evento) con >1
  fila tipo=release, conserva la que tenga `titulo` (y si empatan, la de
  `source_post_id` con prefijo `ig:`/más informativa), borra las demás.
- Se corre una vez sobre la DB viva (resuelve el doble "A Ciegas" de duckfizz).

## 5. Errores y tests

- Tolerante: vista vacía si no hay próximos; aviso no truena sin releases.
- Tests (sin red):
  - `releases_proximos`: incluye futuro en ventana, excluye pasado, excluye
    `irrelevante=1` y fuera de ventana.
  - dedup: post con evento flyer previo + caption de release → 1 sola fila
    release con título (merge, no insert); segunda corrida no duplica; post sin
    evento previo → inserta 1.
  - aviso: nombra próximos (`sale {fecha}`) vs salidos.
  - limpieza: 2 releases del mismo post/fecha → queda 1 (con título).
  - `/calendario` muestra la sección "Próximos lanzamientos" con un release futuro.

## Fuera de alcance

- Auto-anuncio "ya viene" y re-post el día de salida (el usuario lo quiere manual).
- Cambios a "Música Nueva" (pasado).
