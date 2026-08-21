"""Handlers de jobs: despachados por `tipo` desde `src.jobs.worker`.

Cada handler recibe `(cx, job)` (la fila de `jobs`, ya en estado 'corriendo')
y devuelve el dict que se guarda en `resultado_json` al terminar. Reportan
avance vía `jobs.progresar` (el worker no sabe nada del payload interno).
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from src import db, generate_slideshow, jobs


def _marca_de(cx: sqlite3.Connection, account_id: int) -> str:
    """Slug de la cuenta del job. NUNCA cae a un default: un account_id viejo
    o borrado no debe terminar generando contenido bajo la marca equivocada
    (p. ej. 'gdlscene' por default) — mejor que el job truene y quede en
    estado='error' (el worker ya sabe manejar esa excepción)."""
    cuenta = db.get(cx, "accounts", account_id)
    if cuenta is None:
        raise ValueError(f"No existe la cuenta {account_id} del job")
    return cuenta["slug"]


def generar_slideshow(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {tema, formato, estilo, fuentes, n_slides, aspect, contexto}."""
    payload = json.loads(job["payload_json"] or "{}")
    fuentes = payload.get("fuentes")
    qid = generate_slideshow.generar(
        cx, payload["tema"],
        marca=_marca_de(cx, job["account_id"]),
        formato=payload.get("formato"),
        estilo=payload.get("estilo"),
        fuentes=tuple(fuentes) if fuentes else None,
        n_slides=payload.get("n_slides", 6),
        aspect=payload.get("aspect", "4:5"),
        contexto=payload.get("contexto"),
        progreso=lambda pct, msg: jobs.progresar(cx, job["id"], pct, msg),
        creado_por=job.get("creado_por"),
    )
    db.update(cx, "jobs", job["id"], queue_id=qid)
    return {"queue_id": qid}


def regenerar_slideshow(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {queue_id}. Descarta la fila vieja y regenera con el mismo brief."""
    payload = json.loads(job["payload_json"] or "{}")
    queue_id = payload["queue_id"]
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None:
        raise ValueError(f"No existe content_queue.id={queue_id}")
    brief = json.loads(fila["slideshow_json"])["brief"]
    db.update(cx, "content_queue", queue_id, status="descartado")

    fuentes = brief.get("fuentes")
    nuevo_qid = generate_slideshow.generar(
        cx, brief["tema"],
        marca=brief.get("marca", "gdlscene"),
        formato=brief.get("formato"),
        estilo=brief.get("estilo"),
        fuentes=tuple(fuentes) if fuentes else None,
        n_slides=brief.get("n_slides", 6),
        aspect=brief.get("aspect", "4:5"),
        contexto=brief.get("contexto"),
        progreso=lambda pct, msg: jobs.progresar(cx, job["id"], pct, msg),
        creado_por=job.get("creado_por"),
    )
    db.update(cx, "jobs", job["id"], queue_id=nuevo_qid)
    return {"queue_id": nuevo_qid}


HANDLERS = {
    "slideshow.generar": generar_slideshow,
    "slideshow.regenerar": regenerar_slideshow,
}
