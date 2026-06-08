"""Frente B — completar `spotify_id` faltantes (sin perseguir popularity/genres).

Dos caminos:

1. **Resolvedor de links** (confianza dura, sin LLM): muchas bandas tienen en su
   bio un Linktree/DistroKid/lnk.to que adentro lleva el link de Spotify. Bajamos
   esa página y, si trae `open.spotify.com/artist/<id>`, lo damos por bueno y
   registramos sus releases. Página caída/sin link → la banda sigue 'pendiente'.

2. **Matcheo manual** (GUI): para las que no se resolvieron por link, mostramos el
   top-5 de la búsqueda de Spotify y el usuario elige cuál es (o marca que no
   está). `candidatos()` es la pieza que alimenta esa vista.

La API de Spotify le responde a esta app con popularity/followers/genres en NULL
(cap de dev-mode); por eso aquí solo nos importa el id y los releases.

Uso:  python -m src.spotify_match     # corre el resolvedor de links e imprime resumen
"""
from __future__ import annotations

import sys

import requests
from spotipy import SpotifyException

from src import db
from src.enrich_spotify import (
    _ARTIST_LINK,
    RateLimitado,
    _checar_429,
    _registrar_releases,
    get_client,
)

# User-Agent de navegador normal: algunos agregadores (Linktree) devuelven HTML
# distinto o un 403 a clientes que parecen bots.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# Hosts que NUNCA embeben el link de Spotify (redes/plataformas o el propio
# Spotify/Deezer): no vale la pena bajar su HTML. Cualquier OTRO http(s) sí se
# intenta — la extracción de `open.spotify.com/artist/<id>` es la confirmación
# dura, así que probar agregadores desconocidos (amuse, hypeddit, beacons,
# boletomovil…) es seguro y reduce el matcheo manual.
_HOSTS_BLOQUEADOS = ("instagram.com", "facebook.com", "fb.com", "youtube.com",
                     "youtu.be", "twitter.com", "x.com", "tiktok.com",
                     "open.spotify.com", "deezer.com", "wa.me", "t.me")


def es_link_resolvible(link: str | None) -> bool:
    """¿Vale la pena bajar el HTML para buscar el link de Spotify embebido?

    Sí para cualquier http(s) que no esté en la blocklist (la extracción del
    artist id es la confirmación; un agregador desconocido no hace daño probarlo).
    """
    if not link:
        return False
    bajo = link.strip().lower()
    if not bajo.startswith(("http://", "https://")):
        return False
    return not any(h in bajo for h in _HOSTS_BLOQUEADOS)


def extraer_artist_id(html: str | None) -> str | None:
    """Primer `open.spotify.com/artist/<id>` que aparezca en el HTML."""
    if not html:
        return None
    m = _ARTIST_LINK.search(html)
    return m.group(1) if m else None


def candidatos(sp, nombre: str) -> list[dict[str, str]]:
    """Top-5 artistas de Spotify para `nombre` (mercado MX), como dicts simples.

    Devuelve [{id, nombre, url}]; la `url` abre el perfil para que el usuario lo
    oiga y confirme en la GUI. Un 429 se propaga como RateLimitado (corte limpio).
    """
    try:
        res = sp.search(q=nombre, type="artist", limit=5, market="MX")
    except SpotifyException as exc:
        _checar_429(exc)
        raise
    items = res.get("artists", {}).get("items", [])
    return [{"id": a["id"], "nombre": a["name"],
             "url": f"https://open.spotify.com/artist/{a['id']}"}
            for a in items]


def _get_html(url: str) -> str:
    """Baja la página externa (timeout corto, UA de navegador)."""
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
    resp.raise_for_status()
    return resp.text


def bandas_pendientes_con_link(cx) -> list[dict]:
    """Activas en 'pendiente' cuyo link_externo es de un agregador resolvible."""
    filas = db.rows(cx, """
        SELECT * FROM bands
         WHERE activa = 1 AND spotify_status = 'pendiente'
           AND tipo IN ('banda','solista')
           AND link_externo IS NOT NULL AND link_externo != ''
    """)
    return [b for b in filas if es_link_resolvible(b["link_externo"])]


def resolver_links(cx) -> dict[str, int]:
    """Resuelve por link las bandas 'pendiente' con agregador. Devuelve resumen.

    Una página caída/sin link no aborta la corrida: esa banda queda 'pendiente'
    para el matcheo manual. El cliente de Spotify se crea perezosamente (solo si
    hay algo que resolver) para registrar releases del id encontrado.
    """
    candidatas = bandas_pendientes_con_link(cx)
    res = {"revisadas": len(candidatas), "resueltas": 0, "sin_link": 0, "fallidas": 0}
    if not candidatas:
        return res

    sp = None
    for band in candidatas:
        try:
            html = _get_html(band["link_externo"])
        except Exception as exc:  # noqa: BLE001 — red inestable; seguimos con la siguiente
            res["fallidas"] += 1
            print(f"  ✗ {band['nombre']}: no se pudo bajar la página ({exc})")
            continue

        artist_id = extraer_artist_id(html)
        if not artist_id:
            res["sin_link"] += 1
            continue

        if sp is None:
            sp = get_client()
        db.update(cx, "bands", band["id"], spotify_id=artist_id, spotify_status="ok")
        nuevos = _registrar_releases(sp, cx, band["id"], artist_id)
        res["resueltas"] += 1
        extra = f" · {len(nuevos)} release(s) → events" if nuevos else ""
        print(f"  ✓ {band['nombre']}: {artist_id}{extra}")
    return res


def main() -> None:
    cx = db.connect()
    try:
        db.init_db(cx)
        print("Resolviendo spotify_id por links de agregadores…")
        try:
            res = resolver_links(cx)
        except RateLimitado as exc:
            print(f"🛑 {exc} Lo ya resuelto quedó guardado.")
            return
        print(f"\nResumen: {res['revisadas']} revisadas · {res['resueltas']} resueltas "
              f"· {res['sin_link']} sin link de Spotify · {res['fallidas']} páginas caídas.\n"
              "Las que quedaron 'pendiente' se matchean a mano en /spotify.")
    finally:
        cx.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nResolvedor interrumpido.")
