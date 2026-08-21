"""Worker de jobs: loop que toma filas de `jobs` y las despacha por `tipo`.

Uso:
  .venv/bin/python -m src.jobs.worker          # loop continuo
  .venv/bin/python -m src.jobs.worker --once   # procesa a lo más un job y sale

`WORKER_MAX_JOBS` (env, default 2): tope de jobs corriendo a la vez en toda
la instancia (ver `jobs.tomar`). Sin job disponible, duerme 3s antes de
reintentar — `_dormir` está separado para que los tests lo monkeypatcheen y
no bloqueen de verdad.
"""
from __future__ import annotations

import argparse
import os
import time

from src import db, jobs
from src.jobs import handlers

_TRUNCA_ERROR = 400


def _dormir(seg: float) -> None:
    time.sleep(seg)


def _worker_id() -> str:
    return os.getenv("WORKER_ID") or f"worker-{os.getpid()}"


def _despachar(cx, job: dict) -> None:
    handler = handlers.HANDLERS.get(job["tipo"])
    try:
        if handler is None:
            raise ValueError(f"Tipo de job desconocido: {job['tipo']!r}")
        resultado = handler(cx, job)
        jobs.terminar(cx, job["id"], ok=True, resultado=resultado)
    except Exception as exc:  # noqa: BLE001 — cualquier falla del handler cierra el job
        jobs.terminar(cx, job["id"], ok=False, error=str(exc)[:_TRUNCA_ERROR])


def main(once: bool = False) -> None:
    max_global = int(os.getenv("WORKER_MAX_JOBS", "2"))
    worker_id = _worker_id()
    cx = db.connect()
    try:
        db.init_db(cx)
        while True:
            jobs.rescatar_huerfanos(cx)
            job = jobs.tomar(cx, worker_id, max_global=max_global)
            if job is None:
                if once:
                    return
                _dormir(3)
                continue
            _despachar(cx, job)
            if once:
                return
    finally:
        cx.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Worker de jobs asíncronos del portal")
    ap.add_argument("--once", action="store_true",
                    help="procesa a lo más un job y sale (para cron/debug)")
    args = ap.parse_args()
    main(once=args.once)
