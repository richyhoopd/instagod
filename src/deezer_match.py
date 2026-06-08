"""Match banda→artista de Deezer con CONFIRMACIÓN dura (no adivina por nombre).

Muchos artistas independientes comparten nombre, así que un match por nombre
exacto produce falsos positivos (p.ej. ligar la Kabala de GDL a otra Kabala con
22 álbumes). Aquí solo se liga cuando hay una señal dura:

  1. **Link de Deezer en la bio** (resuelto desde beacons.ai/linktr.ee/etc.) →
     confirmación definitiva.
  2. **Cross-check con Spotify**: si la banda ya tiene `spotify_id` confirmado, el
     candidato de Deezer debe COMPARTIR ≥1 release (título normalizado + mismo
     año ±1) con la discografía de Spotify de la banda. Si ninguno comparte → NO
     se liga (queda pendiente para revisión manual en /deezer).

Solo tras confirmar se registran los releases. `purgar()` revierte los matches
viejos hechos por el algoritmo débil.

Spec: docs/superpowers/specs/2026-06-08-deezer-releases-design.md
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import requests

from src import db, deezer

# Link de artista de Deezer dentro del HTML de un agregador de bio.
_DEEZER_ARTIST = re.compile(r"deezer\.com/(?:[a-z]{2}/)?artist/(\d+)")
_AGREGADORES = ("linktr.ee", "beacons.ai", "lnk.to", "ffm.to", "songwhip.com",
                "linkfire", "distrokid.com", "bio.link", "hoo.be", "tap.bio")
_ANIO_TOL = 1  # Deezer usa la fecha de disponibilidad digital; tolera ±1 año
_TIMEOUT = 15


def _pendientes(cx) -> list[dict[str, Any]]:
    return db.rows(cx, """
        SELECT * FROM bands
         WHERE activa = 1 AND deezer_status = 'pendiente'
         ORDER BY prioridad, nombre
    """)


# ---------- normalización y comparación de discografía ----------

def _norm(titulo: str | None) -> str:
    """Título comparable: sin acentos, sin sufijo de tipo, solo alfanum y espacios."""
    if not titulo:
        return ""
    s = re.sub(r"\((?:sencillo|álbum|album|ep|single|live.*?)\)", "", titulo, flags=re.I)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def _titulos_anios(albums: list[dict[str, Any]], *, key_titulo: str,
                   key_fecha: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for a in albums:
        t = _norm(a.get(key_titulo))
        fecha = str(a.get(key_fecha) or "")[:4]
        if t and fecha.isdigit():
            out.add((t, int(fecha)))
    return out


def comparten_release(a: set[tuple[str, int]], b: set[tuple[str, int]]) -> bool:
    """True si comparten ≥1 (título normalizado igual, año dentro de ±_ANIO_TOL)."""
    for ta, ya in a:
        for tb, yb in b:
            if ta == tb and abs(ya - yb) <= _ANIO_TOL:
                return True
    return False


def discografia_deezer(deezer_id: str) -> set[tuple[str, int]]:
    return _titulos_anios(deezer.albums(deezer_id),
                          key_titulo="titulo", key_fecha="release_date")


def discografia_spotify(sp, spotify_id: str) -> set[tuple[str, int]]:
    """Títulos+años de la discografía de Spotify (1 llamada; tolera fallos arriba)."""
    res = sp.artist_albums(spotify_id, album_type="album,single", limit=50)
    return _titulos_anios(res.get("items", []), key_titulo="name", key_fecha="release_date")


# ---------- confirmación por link de bio ----------

def deezer_id_de_link(link_externo: str | None) -> str | None:
    """Resuelve el agregador de la bio y extrae el id de artista de Deezer si está."""
    if not link_externo or not any(a in link_externo for a in _AGREGADORES):
        return None
    try:
        resp = requests.get(link_externo, timeout=_TIMEOUT,
                            headers={"User-Agent": "Mozilla/5.0"})
    except Exception:  # noqa: BLE001 — link caído: sin confirmación, sigue
        return None
    m = _DEEZER_ARTIST.search(resp.text or "")
    return m.group(1) if m else None


# ---------- orquestador preciso ----------

def resolver_preciso(cx, sp=None) -> dict[str, int]:
    """Liga las bandas pendientes SOLO con confirmación dura; registra releases.

    `sp`: cliente de Spotify (inyectable). Si es None se intenta crear perezosamente
    para el cross-check; si no hay/falla, esas bandas quedan pendientes (no se adivina).
    """
    res = {"revisadas": 0, "ok_link": 0, "ok_spotify": 0, "sin_confirmar": 0}
    sp_intentado = sp is not None
    for band in _pendientes(cx):
        res["revisadas"] += 1
        # 1) Link de Deezer en la bio → confirmación dura.
        did = deezer_id_de_link(band.get("link_externo"))
        if did:
            _confirmar(cx, band["id"], did)
            res["ok_link"] += 1
            continue
        # 2) Cross-check con Spotify (solo si la banda tiene id confirmado).
        if not band.get("spotify_id"):
            res["sin_confirmar"] += 1
            continue
        if sp is None and not sp_intentado:
            sp = _intentar_spotify()
            sp_intentado = True
        if sp is None:
            res["sin_confirmar"] += 1
            continue
        did = _match_por_spotify(sp, band)
        if did:
            _confirmar(cx, band["id"], did)
            res["ok_spotify"] += 1
        else:
            res["sin_confirmar"] += 1
    return res


def _match_por_spotify(sp, band: dict[str, Any]) -> str | None:
    """Candidato de Deezer cuya discografía comparte ≥1 release con la de Spotify."""
    try:
        spot = discografia_spotify(sp, band["spotify_id"])
    except Exception:  # noqa: BLE001 — Spotify caído/429: sin cross-check, no adivina
        return None
    if not spot:
        return None
    for cand in deezer.buscar_artista(band["nombre"])[:5]:
        try:
            if comparten_release(spot, discografia_deezer(cand["id"])):
                return cand["id"]
        except deezer.DeezerError:
            continue
    return None


def _intentar_spotify():
    try:
        from src.enrich_spotify import get_client
        return get_client()
    except Exception:  # noqa: BLE001
        return None


def _confirmar(cx, band_id: int, deezer_id: str) -> None:
    db.update(cx, "bands", band_id, deezer_id=deezer_id, deezer_status="ok")
    deezer.registrar_releases(cx, band_id, deezer_id)


# ---------- acciones manuales (vista /deezer) ----------

def elegir(cx, band_id: int, deezer_id: str) -> None:
    """Confirma un candidato a mano: guarda id y registra releases."""
    _confirmar(cx, band_id, deezer_id)


def marcar_no_esta(cx, band_id: int) -> None:
    db.update(cx, "bands", band_id, deezer_status="no_esta")


def candidatos(cx, band_id: int) -> list[dict[str, Any]]:
    """Candidatos de Deezer (con su discografía corta) para el matcheo manual."""
    band = db.get(cx, "bands", band_id)
    if not band:
        return []
    cands = deezer.buscar_artista(band["nombre"])
    for c in cands:
        try:
            c["albumes_muestra"] = [a["titulo"] for a in deezer.albums(c["id"])[:4]]
        except deezer.DeezerError:
            c["albumes_muestra"] = []
    return cands


# ---------- depuración de matches falsos ----------

def purgar(cx) -> dict[str, int]:
    """Revierte TODOS los matches de Deezer y borra sus releases (`dz:`).

    Para limpiar lo que ligó el algoritmo débil antes de re-correr el preciso.
    No toca releases de otras fuentes (sp:/ig:).
    """
    bandas = cx.execute("SELECT COUNT(*) FROM bands WHERE deezer_id IS NOT NULL").fetchone()[0]
    rel = cx.execute("DELETE FROM events WHERE source_post_id LIKE 'dz:%'").rowcount
    cx.execute("UPDATE bands SET deezer_id = NULL, deezer_status = 'pendiente' "
               "WHERE deezer_id IS NOT NULL")
    cx.commit()
    return {"bandas": bandas, "releases": rel}
