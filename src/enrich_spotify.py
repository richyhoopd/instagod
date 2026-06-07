"""Enriquecimiento Spotify (Fase 4): popularity, followers, géneros y releases.

Por cada banda activa:
- Si ya tiene `spotify_id`, consulta el artista directo; si no, lo busca por
  nombre (mercado MX) y elige el mejor match (nombre exacto primero; si la bio
  de IG trae un link de open.spotify.com/artist se usa como confirmación dura).
- Guarda `popularity` (0-100), `followers_spotify`, `generos` (JSON) y el
  `spotify_id` para corridas futuras.
- Releases: álbumes/singles con menos de SPOTIFY_RELEASE_DAYS días se insertan
  en `events` (tipo='release', dedupe por id del álbum) → alimentan anuncios.

Límites conocidos: la API oficial no da reproducciones ni related-artists, y su
data no debe usarse para entrenar modelos (ToS). El match por nombre puede
fallar con nombres genéricos: revisa `spotify_id` en la GUI y corrígelo a mano
si hace falta (el botón ♻ re-enriquece esa banda).

Uso:
    python -m src.enrich_spotify                  # todas las bandas activas
    python -m src.enrich_spotify kabala_oficial   # solo esas (por ig_handle)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import spotipy
from spotipy import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials

import config
from src import db

_ARTIST_LINK = re.compile(r"open\.spotify\.com/(?:intl-[a-z]+/)?artist/([A-Za-z0-9]+)")


class SpotifyOcupado(RuntimeError):
    """Otro proceso está usando Spotify (lock tomado por un pid vivo)."""


class RateLimitado(RuntimeError):
    """Spotify regresó 429: cortar la corrida (lo guardado queda)."""

    def __init__(self, retry_after: int | None):
        self.retry_after = retry_after
        espera = f"~{retry_after // 60 + 1} min" if retry_after else "un rato"
        super().__init__(f"Rate limit de Spotify; reintenta en {espera}.")


def _checar_429(exc: SpotifyException) -> None:
    """Si el error es 429, lo convierte a RateLimitado (corte limpio)."""
    if exc.http_status == 429:
        try:
            retry = int((exc.headers or {}).get("Retry-After", ""))
        except ValueError:
            retry = None
        raise RateLimitado(retry) from exc


def _pid_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def spotify_lock(path: str | Path | None = None):
    """Exclusión entre procesos que llaman Spotify (pipeline, cron, GUI).

    Creación atómica (O_EXCL). Si el lock existe pero su pid ya murió
    (proceso matado a media corrida), se roba en vez de quedar trabado.
    """
    lock = Path(path) if path else config._resolve(config.SPOTIFY_LOCK_PATH)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            pid = int(lock.read_text().strip())
        except (ValueError, OSError):
            pid = None
        if pid and _pid_vivo(pid):
            raise SpotifyOcupado(f"Spotify en uso por pid {pid} ({lock})")
        lock.unlink(missing_ok=True)  # lock muerto → robar
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        lock.unlink(missing_ok=True)


def get_client() -> spotipy.Spotify:
    if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
        raise RuntimeError("Faltan SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET en el .env")
    # retries=0: el primer 429 agota `total` y urllib3 levanta MaxRetryError
    # ANTES de dormir el Retry-After (verificado contra urllib3 2.7) — sin esto,
    # spotipy respetaría el header y un Retry-After de horas colgaría el proceso.
    # Costo: el 429 llega como RetryError SIN headers (RateLimitado.retry_after
    # queda None); el valor real sí se ve en el log vía el warning de spotipy.
    return spotipy.Spotify(retries=0, status_retries=0, auth_manager=SpotifyClientCredentials(
        client_id=config.SPOTIFY_CLIENT_ID,
        client_secret=config.SPOTIFY_CLIENT_SECRET,
    ))


# ---------- Lógica de match (pura, testeable) ----------

def artist_id_de_link(link: str | None) -> str | None:
    """Extrae el id de artista si el link (bio de IG) apunta a Spotify."""
    if not link:
        return None
    m = _ARTIST_LINK.search(link)
    return m.group(1) if m else None


def elegir_match(nombre: str, candidatos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Mejor artista para `nombre`: match exacto (casefold) o el primero."""
    if not candidatos:
        return None
    objetivo = nombre.casefold().strip()
    for c in candidatos:
        if c.get("name", "").casefold().strip() == objetivo:
            return c
    return candidatos[0]


def es_release_reciente(release_date: str | None, *, hoy: datetime | None = None) -> bool:
    """True si la fecha (YYYY[-MM[-DD]]) cae dentro de la ventana configurada."""
    if not release_date:
        return False
    partes = release_date.split("-")
    try:
        fecha = datetime(int(partes[0]), int(partes[1]) if len(partes) > 1 else 1,
                         int(partes[2]) if len(partes) > 2 else 1)
    except ValueError:
        return False
    hoy = hoy or datetime.now()
    return (hoy - fecha) <= timedelta(days=config.SPOTIFY_RELEASE_DAYS)


# ---------- Enriquecimiento contra la DB ----------

def enrich_band(sp: spotipy.Spotify, cx, band: dict[str, Any]) -> str:
    """Enriquece una banda. Devuelve etiqueta para el log."""
    artista = None
    confirmado_por_link = False

    link_id = artist_id_de_link(band.get("link_externo"))
    spotify_id = band.get("spotify_id") or link_id
    if spotify_id:
        try:
            artista = sp.artist(spotify_id)
            confirmado_por_link = bool(link_id)
        except SpotifyException as exc:
            _checar_429(exc)
            artista = None  # id inválido → caemos a búsqueda

    if artista is None:
        res = sp.search(q=band["nombre"], type="artist", limit=5, market="MX")
        artista = elegir_match(band["nombre"], res.get("artists", {}).get("items", []))
    if artista is None:
        return "sin match en Spotify"

    exacto = artista["name"].casefold().strip() == band["nombre"].casefold().strip()
    # Solo confiamos en match exacto o confirmado por el link de la bio. Un match
    # aproximado suele ser un artista DISTINTO (la banda no está en Spotify) y
    # guardarlo contaminaría los anuncios de releases con lanzamientos ajenos.
    if not (exacto or confirmado_por_link):
        return f"match dudoso ('{artista['name']}') → NO guardado; pon el spotify_id a mano si aplica"

    db.update(cx, "bands", band["id"],
              spotify_id=artista["id"],
              popularity=artista.get("popularity"),
              followers_spotify=artista.get("followers", {}).get("total"),
              generos=json.dumps(artista.get("genres", []), ensure_ascii=False))

    nuevos = _registrar_releases(sp, cx, band["id"], artista["id"])
    confianza = "link" if confirmado_por_link else "exacto"
    extra = f" · {len(nuevos)} release(s) nuevos → events" if nuevos else ""
    pop = artista.get("popularity")
    pop_txt = f"pop={pop}" if pop is not None else "pop/géneros no disponibles (cap de Spotify)"
    return f"{artista['name']} (match {confianza}) {pop_txt}{extra}"


def _registrar_releases(sp: spotipy.Spotify, cx, band_id: int, artist_id: str) -> list[dict]:
    """Inserta releases recientes en events (dedupe por id de álbum).

    Devuelve los nuevos como [{"titulo", "fecha", "cover_url"}] para que el
    cron arme el aviso de Telegram; lista vacía = nada nuevo.
    """
    try:
        albums = sp.artist_albums(artist_id, include_groups="album,single", limit=10)
    except SpotifyException as exc:
        _checar_429(exc)
        return []
    nuevos: list[dict] = []
    for alb in albums.get("items", []):
        if not es_release_reciente(alb.get("release_date")):
            continue
        ya = db.rows(cx, "SELECT 1 FROM events WHERE band_id = ? AND source_post_id = ?",
                     (band_id, alb["id"]))
        if ya:
            continue
        # El tipo (álbum/single) enriquece el copy del anuncio de música nueva.
        clase = "álbum" if alb.get("album_type") == "album" else "sencillo"
        imgs = alb.get("images") or []
        titulo = f"{alb.get('name')} ({clase})" if alb.get("name") else None
        cover = imgs[0]["url"] if imgs else None
        db.insert(cx, "events", band_id=band_id, tipo="release",
                  fecha_evento=alb.get("release_date"), titulo=titulo,
                  cover_url=cover, source_post_id=alb["id"], status="nuevo")
        nuevos.append({"titulo": titulo, "fecha": alb.get("release_date"),
                       "cover_url": cover})
    return nuevos


def backfill_release_titles() -> int:
    """Rellena `titulo` de releases sin él, vía artist_albums (sp.albums está capado)."""
    cx = db.connect()
    try:
        pend = db.rows(cx, """
            SELECT e.id, e.source_post_id, b.spotify_id
              FROM events e JOIN bands b ON b.id = e.band_id
             WHERE e.tipo='release' AND (e.titulo IS NULL OR e.cover_url IS NULL)
               AND e.source_post_id IS NOT NULL AND b.spotify_id IS NOT NULL
        """)
        if not pend:
            print("No hay releases sin título/portada.")
            return 0
        # Cachea los álbumes por artista (una llamada artist_albums por banda).
        cache: dict[str, dict[str, dict]] = {}
        n = 0
        try:
            with spotify_lock():
                sp = get_client()
                for p in pend:
                    sid = p["spotify_id"]
                    if sid not in cache:
                        try:
                            items = sp.artist_albums(sid, include_groups="album,single", limit=20)["items"]
                            cache[sid] = {a["id"]: a for a in items}
                        except SpotifyException as exc:
                            _checar_429(exc)
                            cache[sid] = {}
                    alb = cache[sid].get(p["source_post_id"])
                    if not alb:
                        continue
                    clase = "álbum" if alb.get("album_type") == "album" else "sencillo"
                    imgs = alb.get("images") or []
                    db.update(cx, "events", p["id"], titulo=f"{alb['name']} ({clase})",
                              cover_url=imgs[0]["url"] if imgs else None)
                    n += 1
        except SpotifyOcupado as exc:
            print(f"⏭ {exc} — corre de nuevo cuando termine.")
            return 0
        except RateLimitado as exc:
            print(f"🛑 {exc}")
            return n
        print(f"✅ {n} release(s) con título + portada rellenados.")
        return n
    finally:
        cx.close()


def enrich(handles: list[str] | None = None, *, solo_faltantes: bool = False) -> None:
    """Enriquece bandas activas (o `handles`); `solo_faltantes` = sin spotify_id."""
    cx = db.connect()
    try:
        db.init_db(cx)
        bandas = db.list_bands(cx)
        if handles:
            quiero = {h.lstrip("@").lower() for h in handles}
            bandas = [b for b in bandas if (b.get("ig_handle") or "").lower() in quiero]
        # 'no_esta' = el usuario confirmó en /spotify que la banda no está en
        # Spotify; no la re-buscamos nunca (gastaría cuota y no daría match).
        bandas = [b for b in bandas if b.get("spotify_status") != "no_esta"]
        if solo_faltantes:
            bandas = [b for b in bandas if not b.get("spotify_id")]
        if not bandas:
            print("No hay bandas que enriquecer.")
            return
        try:
            with spotify_lock():
                sp = get_client()
                print(f"Enriqueciendo {len(bandas)} banda(s) con Spotify…")
                for band in bandas:
                    try:
                        print(f"▶ {band['nombre']}: {enrich_band(sp, cx, band)}")
                    except SpotifyException as exc:
                        _checar_429(exc)
                        print(f"▶ {band['nombre']}: ❌ Spotify respondió mal ({exc.http_status})")
                    time.sleep(config.SPOTIFY_THROTTLE_S)
        except SpotifyOcupado as exc:
            print(f"⏭ {exc} — corre de nuevo cuando termine.")
        except RateLimitado as exc:
            print(f"🛑 {exc} Lo ya procesado quedó guardado.")
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enriquecimiento Spotify (Fase 4)")
    parser.add_argument("handles", nargs="*", help="limitar a estos ig_handle")
    parser.add_argument("--faltantes", action="store_true",
                        help="solo bandas activas SIN spotify_id")
    args = parser.parse_args()
    try:
        enrich(args.handles or None, solo_faltantes=args.faltantes)
    except KeyboardInterrupt:
        sys.exit("\nEnriquecimiento interrumpido.")
