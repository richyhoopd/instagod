# Dedupe de releases entre bandas por flyer

**Fecha:** 2026-06-13 · **Estado:** aprobado

## Problema

Un release publicado por varias cuentas (post colaborativo de IG, o re-subida del
mismo flyer) genera N events `tipo='release'` — uno por banda — y el carrusel de
Música Nueva muestra N tarjetas del mismo lanzamiento (caso real: "La 4T Del
Perreo" salió 3 veces en el carrusel del 12 jun: CCÑA, Lxs cabronxxxit0s y
STADITCHE, todos del mismo post `DZLcf0Rkans`). El dedupe actual
(`detect_releases_ig._es_dupe`) está scoped por `band_id` y nunca compara entre
bandas.

## Decisiones

- **Atribución:** la tarjeta queda a nombre de la primera cuenta que publicó; las
  demás aparecen como créditos en el caption: `(con @handle1 @handle2)`.
  (Decidido por Ricardo 2026-06-13.)
- **Umbral visual:** el mismo que ya usa la agenda de shows — dHash 8×8,
  distancia ≤ 8 bits (`_es_duplicado`).

## Señales de duplicado (cross-banda, fecha ±`_VENTANA_DIAS`)

1. **Shortcode compartido** — mismo `source_post_id` en un release de otra banda
   = post colaborativo = mismo evento. Exacto, costo cero.
2. **Match visual** — pHash del flyer del post nuevo vs flyer/cover local de
   releases existentes de otras bandas. Atrapa re-subidas con shortcode distinto.

## Componentes

- **`src/imghash.py` (nuevo):** `phash(path)` y `es_duplicado(h, vistos, umbral=8)`
  movidos desde `generate_agenda` (evita import circular
  `detect_releases_ig → generate_agenda`). `generate_agenda` importa de ahí con
  alias `_phash`/`_es_duplicado` para no romper monkeypatches de tests.
- **Migración:** columna `events.creditos` (TEXT, JSON de band_ids) vía el patrón
  idempotente de `db.init_db` (TABLES + ALTER TABLE).
- **Detección (`detect_releases_ig.detectar`):** antes de insertar un release, se
  busca dupe cross-banda (señales 1 y 2). Si hay: `db.update` del event existente
  agregando el band_id nuevo a `creditos` (sin duplicar), NO se inserta fila, se
  cuenta como `fusionados` en el resumen.
- **Caption (`generate_agenda`):** los band_ids de `creditos` se resuelven a
  ig_handles (una query) y la línea del release agrega `(con @h1 @h2)`.
- **Red de seguridad en render (`build_releases_carousel`):** antes de armar
  slides, fusiona visibles duplicados (mismo shortcode o pHash ≤ 8 de covers
  locales): conserva el primero, une créditos. Cubre dupes ya existentes en BD.
- **Limpieza one-shot:** fusionar los dupes actuales (384 ← 406, 456): créditos
  al más antiguo, `irrelevante=1` a los demás (`releases_ventana` ya filtra
  `irrelevante=0`).
- **Artwork oficial del caso reportado:** resolver `deezer_id` de CCÑA
  (cross-check de discografía) para que `mejorar_covers_ig` reemplace el flyer
  de la fiesta por la portada real del EP.

## Fuera de alcance

- Atribución por artista principal vía Deezer (fallback descartado por ahora).
- Dedupe visual para shows (ya existe en render vía `_unicos_flyers`).

## Pruebas

TDD por componente: migración, merge de créditos en detección (shortcode y
pHash), caption con créditos, red de render, y limpieza. Sin red: pHash con
imágenes sintéticas en tmp_path; Deezer mockeado.
