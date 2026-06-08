"""Match banda→artista de Deezer (espejo de spotify_match, sin auth ni cap).

Auto-match exacto por nombre en la primera corrida (Deezer no tiene rate cap, así
que buscar todas las bandas es barato); los dudosos quedan `deezer_status='pendiente'`
para confirmarlos a mano en la vista /deezer. Al confirmar se registran releases.

Spec: docs/superpowers/specs/2026-06-08-deezer-releases-design.md
"""
from __future__ import annotations

from typing import Any

from src import db, deezer


def _pendientes(cx) -> list[dict[str, Any]]:
    return db.rows(cx, """
        SELECT * FROM bands
         WHERE activa = 1 AND deezer_status = 'pendiente'
         ORDER BY prioridad, nombre
    """)


def resolver_auto(cx) -> dict[str, int]:
    """Asocia por nombre EXACTO las bandas pendientes; registra sus releases.

    Devuelve {revisadas, ok, dudosas}. Las `no_esta` nunca se tocan.
    """
    res = {"revisadas": 0, "ok": 0, "dudosas": 0}
    for band in _pendientes(cx):
        res["revisadas"] += 1
        try:
            cands = deezer.buscar_artista(band["nombre"])
        except deezer.DeezerError:
            continue  # Deezer caído: lo dejamos pendiente, sigue
        objetivo = band["nombre"].casefold().strip()
        match = next((c for c in cands if c["nombre"].casefold().strip() == objetivo), None)
        if not match:
            res["dudosas"] += 1
            continue
        db.update(cx, "bands", band["id"], deezer_id=match["id"], deezer_status="ok")
        deezer.registrar_releases(cx, band["id"], match["id"])
        res["ok"] += 1
    return res


def elegir(cx, band_id: int, deezer_id: str) -> None:
    """Confirma un candidato a mano (vista /deezer): guarda id y registra releases."""
    db.update(cx, "bands", band_id, deezer_id=deezer_id, deezer_status="ok")
    deezer.registrar_releases(cx, band_id, deezer_id)


def marcar_no_esta(cx, band_id: int) -> None:
    db.update(cx, "bands", band_id, deezer_status="no_esta")


def candidatos(cx, band_id: int) -> list[dict[str, Any]]:
    """Candidatos de Deezer para mostrar en la vista de matcheo."""
    band = db.get(cx, "bands", band_id)
    return deezer.buscar_artista(band["nombre"]) if band else []
