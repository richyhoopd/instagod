# Carrusel "Música Nueva" v2: portadas locales + grid 2×2 + tags

**Fecha:** 2026-06-07 · **Estado:** aprobado por Ricardo

## Problema

1. **Portadas rotas**: el filtro DNS de la máquina (resolver 100.64.0.2) responde vacío para `i.scdn.co` (CDN de imágenes de Spotify). Playwright usa el mismo DNS → las tarjetas salen sin portadas. Las URLs en DB están bien. `api.spotify.com`, `open.spotify.com`, `i.ytimg.com` y `dns.google` SÍ resuelven; conectar a i.scdn.co por IP (resuelta vía DoH) funciona (verificado: 200, JPEG).
2. **Overflow**: la tarjeta única mete hasta 10 releases y se desborda.
3. Faltan tags de las bandas en el caption.

## Diseño

### 1. `src/covers.py` (nuevo)
`asegurar_cover(url) -> Path | None` con caché `data/covers/{sha1(url)[:16]}.jpg`:
- Si ya existe en caché → regresa la ruta (sin red).
- Descarga normal (requests, 15s) → si falla por DNS/conexión, **fallback DoH**: resolver A-record vía `https://dns.google/resolve`, conectar con `urllib3.HTTPSConnectionPool(ip, server_hostname=host, ca_certs=certifi.where())`.
- Falla total → None (la tarjeta pinta placeholder de marca, nunca img rota).

### 2. Carrusel releases en `generate_agenda.py` — `build_releases_carousel(periodo)`
- **Portada** `templates/release_cover.html`: fondo verde marca, "Música Nueva", rango, **collage de hasta 6 mini-portadas** (rotaciones leves, estilo pila de discos) + **lineup** de nombres de bandas en pequeño.
- **Slides** `templates/release_grid.html`: **grid 2×2** (máx 4 releases/slide), portada grande arriba, banda (Tinos bold), título (itálica), fecha + badge verde (SENCILLO/ÁLBUM/LIVE SESSION, parseado del sufijo del titulo). Con 1–3 releases el layout se adapta (sin celdas vacías). Paginación en kicker.
- **CTA** `templates/release_cta.html`: "¿Ya las escuchaste?" + Guarda/Comparte, lenguaje del agenda_cta.
- Tope IG 10 slides: portada + 8 grids + CTA = 32 releases; excedente → "+N más" en caption.
- `main()` modo releases usa el carrusel nuevo; `build_card`/modo shows intactos.

### 3. Caption
Head + "• {d} {mes} — {banda}: {titulo}" por release + bloque final de tags `@handle` únicos (patrón de la agenda de flyers).

## Fuera de alcance
- `web/` (tabla GUI): los thumbs se arreglan whitelisteando `i.scdn.co` en el filtro DNS de Ricardo, o sirviendo `data/covers/` (sesión del otro Claude).
- Releases de YouTube se insertan a mano (hecho: events 270/271, `source_post_id='yt:...'`, thumb de i.ytimg.com como cover).

## Coordinación
NO tocar `planner.py`/`web/`. NO `git commit`. Marca visual: paper `#faf8f3`, verde `#1b5e3f`, Tinos + Poppins, motor `compose.render_card` (file:// + networkidle).
