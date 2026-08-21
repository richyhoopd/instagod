"""Motor de jobs asíncronos del portal: cola, toma atómica y ciclo de vida.

Un worker (`src.jobs.worker`) toma filas en estado 'cola' con `tomar`, reporta
avance con `progresar` (progreso + heartbeat) y cierra con `terminar`. La tabla
`jobs` vive en `src/schema.sql` (Fase 2, spec 2026-08-20); columnas editables
en `db.TABLES["jobs"]`.

Aislamiento por cuenta: `tomar` nunca saca dos jobs de la MISMA cuenta a
correr en paralelo (una marca no compite consigo misma por recursos de LLM/IG),
aunque sí deja correr cuentas distintas en simultáneo (hasta `max_global`).

Timestamps: mismo estilo que `src/users.py` — texto UTC "YYYY-MM-DD HH:MM:SS",
comparable como texto. `_ahora()` es el único punto que lee el reloj: los
tests de rescate de huérfanos lo monkeypatchean para fijar el "ahora".
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from src import db

_FMT = "%Y-%m-%d %H:%M:%S"


def _ahora() -> datetime:
    """Hora actual UTC. Monkeypatchable en tests (rescate de huérfanos)."""
    return datetime.now(timezone.utc)


def _ts() -> str:
    return _ahora().strftime(_FMT)


def crear(cx: sqlite3.Connection, tipo: str, account_id: int, payload: dict,
          *, creado_por: int | None = None) -> int:
    """Encola un job nuevo (estado='cola' por default de columna). Devuelve su id."""
    return db.insert(cx, "jobs", tipo=tipo, account_id=account_id,
                     payload_json=json.dumps(payload, ensure_ascii=False),
                     creado_por=creado_por)


def tomar(cx: sqlite3.Connection, worker_id: str,
          *, max_global: int | None = None) -> dict[str, Any] | None:
    """Toma atómicamente el job más viejo en cola de una cuenta sin nada corriendo.

    `max_global`: tope de jobs corriendo a la vez en toda la instancia; si ya
    se alcanzó, no toma nada (deja que otras cuentas/worker lo intenten luego).
    """
    if max_global is not None:
        corriendo = cx.execute(
            "SELECT COUNT(*) FROM jobs WHERE estado = 'corriendo'"
        ).fetchone()[0]
        if corriendo >= max_global:
            return None

    ahora = _ts()
    fila = cx.execute(
        """
        UPDATE jobs
           SET estado = 'corriendo', worker_id = ?, heartbeat = ?, started_at = ?
         WHERE id = (
             SELECT id FROM jobs
              WHERE estado = 'cola'
                AND account_id NOT IN (
                    SELECT account_id FROM jobs WHERE estado = 'corriendo'
                )
              ORDER BY id LIMIT 1
         )
        RETURNING *
        """,
        (worker_id, ahora, ahora),
    ).fetchone()
    cx.commit()
    return dict(fila) if fila else None


def _append_log(log_previo: str | None, linea: str) -> str:
    return f"{log_previo}\n{linea}" if log_previo else linea


def progresar(cx: sqlite3.Connection, job_id: int, pct: int, msg: str) -> None:
    """Actualiza progreso + heartbeat y agrega `[pct%] msg` al log."""
    fila = db.get(cx, "jobs", job_id)
    if fila is None:
        raise ValueError(f"No existe jobs.id={job_id}")
    nuevo_log = _append_log(fila.get("log"), f"[{pct}%] {msg}")
    db.update(cx, "jobs", job_id, progreso=pct, log=nuevo_log, heartbeat=_ts())


def terminar(cx: sqlite3.Connection, job_id: int, *, ok: bool,
             resultado: dict | None = None, error: str | None = None) -> None:
    """Cierra el job: 'ok' con `resultado_json`, o 'error' con el motivo."""
    campos: dict[str, Any] = {"finished_at": _ts()}
    if ok:
        campos["estado"] = "ok"
        if resultado is not None:
            campos["resultado_json"] = json.dumps(resultado, ensure_ascii=False)
    else:
        campos["estado"] = "error"
        if error is not None:
            campos["resultado_json"] = json.dumps({"error": error}, ensure_ascii=False)
            fila = db.get(cx, "jobs", job_id)
            campos["log"] = _append_log((fila or {}).get("log"), f"[error] {error}")
    db.update(cx, "jobs", job_id, **campos)


def cancelar(cx: sqlite3.Connection, job_id: int) -> bool:
    """Cancela solo si sigue en 'cola'. Devuelve si canceló algo."""
    cur = cx.execute(
        "UPDATE jobs SET estado = 'cancelado' WHERE id = ? AND estado = 'cola'",
        (job_id,),
    )
    cx.commit()
    return cur.rowcount > 0


def rescatar_huerfanos(cx: sqlite3.Connection, *, max_min: int = 30) -> int:
    """Recupera jobs 'corriendo' sin heartbeat reciente (worker caído a medias).

    1ª vez que se detecta huérfano: vuelve a 'cola' (queda anotado en el log
    con '[rescate]'). Si ya se había rescatado antes (el log ya trae esa
    marca) y volvió a quedar huérfano, se da por no recuperable → 'error'.
    Devuelve cuántos jobs tocó.
    """
    corte = (_ahora() - timedelta(minutes=max_min)).strftime(_FMT)
    huerfanos = db.rows(
        cx,
        "SELECT * FROM jobs WHERE estado = 'corriendo' AND heartbeat IS NOT NULL "
        "AND heartbeat < ?",
        (corte,),
    )
    for job in huerfanos:
        log_previo = job.get("log") or ""
        if "[rescate]" in log_previo:
            db.update(
                cx, "jobs", job["id"], estado="error",
                resultado_json=json.dumps(
                    {"error": "job huérfano no recuperable (rescatado dos veces)"},
                    ensure_ascii=False),
                finished_at=_ts(),
            )
        else:
            db.update(
                cx, "jobs", job["id"], estado="cola", worker_id=None, heartbeat=None,
                log=_append_log(log_previo, "[rescate] heartbeat perdido, devuelto a cola"),
            )
    return len(huerfanos)
