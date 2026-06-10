"""Estado + preview de los segmentos para la GUI (/segmentos).

Por cada Segment del catálogo arma: cadencia en humano, última corrida,
próxima fecha que toca, items pendientes de aprobación en la cola, y un
PREVIEW del contenido que el generador usaría HOY (mismos helpers de
generate_agenda: ventanas, agrupado, dedup de flyers, captions) — sin
renderizar PNGs ni tocar Telegram. Solo lectura.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytz

import config
from src import db, segments

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def cadencia_humana(seg: segments.Segment) -> str:
    c = seg.cadencia
    if c["tipo"] == "semanal":
        return f"cada {_DIAS[c['dow']]}"
    if c["tipo"] == "mensual":
        return f"el día {c.get('dia_mes', 1)} de cada mes"
    return "diario"


def proxima_corrida(seg: segments.Segment, ahora: datetime) -> datetime:
    """Próxima fecha (incluido hoy) en que la cadencia del segmento toca."""
    for i in range(0, 62):
        cand = ahora + timedelta(days=i)
        if segments.toca_hoy(seg, cand):
            return cand
    return ahora  # cadencia imposible; no debería pasar


def _modo_periodo(clave: str) -> tuple[str, str]:
    modo = "releases" if clave.startswith("releases") else "shows"
    periodo = "mensual" if clave.endswith("_mensual") else "semanal"
    return modo, periodo


def _pendientes(cx, modo: str, periodo: str, account_id: int) -> list[dict[str, Any]]:
    """Items del segmento encolados y esperando aprobación en Telegram."""
    from src.approval import _urls_de_imagen
    filas = db.rows(cx, """
        SELECT id, caption, imagen_url, created_at FROM content_queue
         WHERE aprobacion = 'pendiente' AND account_id = ?
           AND tema_semilla LIKE ?
         ORDER BY id DESC
    """, (account_id, f"{modo} {periodo}%"))
    return [{"queue_id": f["id"], "caption": f["caption"] or "",
             "urls": _urls_de_imagen(f["imagen_url"] or ""),
             "creado": f["created_at"]} for f in filas]


def _preview_shows(cx, periodo: str, ahora: datetime) -> dict[str, Any]:
    from src import generate_agenda as ga
    dias = ga._PERIODOS[periodo]
    grupos = ga.agrupar_por_evento(ga.eventos_ventana(cx, dias, hoy=ahora))
    unicos, omitidos = ga._unicos_flyers(grupos)
    en_carrusel = {e["id"] for e, _ in unicos}

    eventos = [{
        "id": g["id"], "fecha": (g.get("fecha_evento") or "")[:10],
        "banda": g["banda_nombre"], "lugar": g.get("lugar"),
        "tiene_flyer": bool(g.get("flyer_path")),
        "en_carrusel": g["id"] in en_carrusel,
    } for g in grupos]

    # Mismo reparto que build_agenda_partes: parte 1 = portada + ≤9, resto ≤10.
    n = len(unicos)
    partes = 0 if n == 0 else 1 + max(0, -(-(n - 9) // 10))
    rango = ga._rango_shows(ahora, dias)
    caption = ga._caption_agenda(unicos, periodo, rango) if unicos else None
    return {
        "rango": rango, "eventos": eventos, "flyers_usables": n,
        "omitidos_dedup": omitidos, "partes": partes, "caption": caption,
        "se_genera": n > 0,
        "motivo": (f"{n} flyer(s) en {partes} parte(s)" if n
                   else "sin flyers con imagen y fecha en la ventana"),
    }


def _preview_releases(cx, periodo: str, ahora: datetime) -> dict[str, Any]:
    from src import generate_agenda as ga
    dias = ga._PERIODOS[periodo]
    solo_frescos = periodo == "semanal"
    evs = ga.releases_ventana(cx, dias, hoy=ahora, solo_frescos=solo_frescos)
    min_req = (config.SEGMENT_MIN_RELEASES_SEMANAL if periodo == "semanal"
               else config.SEGMENT_MIN_RELEASES_MENSUAL)
    eventos = [{
        "id": e["id"], "fecha": (e.get("fecha_evento") or "")[:10],
        "banda": e["banda_nombre"], "titulo": e.get("titulo"),
        "cover_url": e.get("cover_url"),
    } for e in evs]
    se_genera = len(evs) >= min_req
    etiqueta = "fresco(s)" if solo_frescos else "release(s)"
    return {
        "rango": ga._rango_releases(ahora, dias), "eventos": eventos,
        "frescos": len(evs), "min": min_req,
        "caption": ga._caption_releases(evs, periodo) if evs else None,
        "se_genera": se_genera,
        "motivo": (f"{len(evs)} {etiqueta} (mínimo {min_req})" if se_genera
                   else f"solo {len(evs)} {etiqueta} (< {min_req}); se salta"),
    }


def vista_segmentos(cx, registro: list[segments.Segment], *,
                    ahora: datetime | None = None,
                    account_id: int = 1) -> list[dict[str, Any]]:
    """Estado completo de cada segmento del catálogo, para la plantilla."""
    ahora = ahora or datetime.now(pytz.timezone(config.TIMEZONE))
    out: list[dict[str, Any]] = []
    for seg in registro:
        modo, periodo = _modo_periodo(seg.clave)
        ventana = segments.ventana_actual(seg, ahora)
        ya = bool(db.rows(cx, """
            SELECT 1 FROM segment_runs WHERE segmento=? AND account_id=? AND ventana=?
        """, (seg.clave, account_id, ventana)))
        ult = db.rows(cx, """
            SELECT MAX(corrido_at) AS t FROM segment_runs
             WHERE segmento=? AND account_id=?
        """, (seg.clave, account_id))
        preview = (_preview_shows(cx, periodo, ahora) if modo == "shows"
                   else _preview_releases(cx, periodo, ahora))
        out.append({
            "clave": seg.clave, "nombre": seg.nombre, "activo": seg.activo,
            "modo": modo, "periodo": periodo,
            "cadencia": cadencia_humana(seg),
            "toca_hoy": segments.toca_hoy(seg, ahora),
            "ventana": ventana, "ya_corrio": ya,
            "ultima_corrida": ult[0]["t"] if ult else None,
            "proxima": proxima_corrida(seg, ahora).strftime("%Y-%m-%d"),
            "pendientes": _pendientes(cx, modo, periodo, account_id),
            "preview": preview,
        })
    return out
