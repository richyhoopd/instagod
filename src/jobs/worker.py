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
import json
import os
import time
from datetime import datetime, timedelta, timezone

import config
from src import db, jobs
from src.jobs import handlers

_TRUNCA_ERROR = 400
_CADA_HORAS_DEFAULT = 24
_TIPO_POR_PROVIDER = {"rss": "sourcing.rss_fetch", "newsapi": "sourcing.newsapi_fetch"}


def _dormir(seg: float) -> None:
    time.sleep(seg)


def _worker_id() -> str:
    return os.getenv("WORKER_ID") or f"worker-{os.getpid()}"


def _error_seguro(exc: Exception, cx, job: dict) -> str:
    """Texto de error SIN secretos (mismo criterio que approval._error_seguro):
    requests.HTTPError → solo el status code; cualquier otra excepción se
    castea a texto y se redactan las credenciales de la cuenta del job
    (IG_ACCESS_TOKEN, TELEGRAM_BOT_TOKEN, LLM_API_KEY, etc. — lo que devuelva
    `config.account_creds`) si aparecen ahí. Truncado a 400 chars.
    """
    import requests
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    msg = str(exc)
    cuenta = db.get(cx, "accounts", job.get("account_id"))
    if cuenta:
        for val in config.account_creds(cuenta["slug"]).values():
            if val:
                msg = msg.replace(val, "***")
    return msg[:_TRUNCA_ERROR]


def encolar_fuentes_vencidas(cx) -> int:
    """Encola `sourcing.rss_fetch`/`sourcing.newsapi_fetch` para fuentes `info`
    activas cuyo `cada_horas` (config, default 24) ya venció. Dedup: si ya hay
    un job cola/corriendo para esa `source_id`, no encola otro. Devuelve
    cuántos jobs creó."""
    ahora = datetime.now(timezone.utc)
    fuentes_info = db.rows(
        cx, "SELECT * FROM brand_sources WHERE kind = 'info' AND activa = 1")
    creados = 0
    for f in fuentes_info:
        tipo = _TIPO_POR_PROVIDER.get(f["provider"])
        if tipo is None:
            continue
        try:
            cfg = json.loads(f["config_json"]) if f["config_json"] else {}
        except (TypeError, ValueError):
            cfg = {}
        cada_horas = cfg.get("cada_horas") or _CADA_HORAS_DEFAULT

        vencido = True
        if f["ultimo_run"]:
            try:
                ultimo = datetime.strptime(f["ultimo_run"], "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc)
                vencido = (ahora - ultimo) >= timedelta(hours=cada_horas)
            except ValueError:
                vencido = True
        if not vencido:
            continue

        ya_en_cola = db.rows(
            cx, "SELECT id FROM jobs WHERE tipo = ? AND estado IN ('cola', 'corriendo') "
                "AND payload_json LIKE ?",
            (tipo, f'%"source_id": {f["id"]}%'))
        if ya_en_cola:
            continue

        jobs.crear(cx, tipo, f["account_id"], {"source_id": f["id"]})
        creados += 1
    return creados


def _despachar(cx, job: dict) -> None:
    handler = handlers.HANDLERS.get(job["tipo"])
    try:
        if handler is None:
            raise ValueError(f"Tipo de job desconocido: {job['tipo']!r}")
        resultado = handler(cx, job)
        jobs.terminar(cx, job["id"], ok=True, resultado=resultado)
    except Exception as exc:  # noqa: BLE001 — cualquier falla del handler cierra el job
        jobs.terminar(cx, job["id"], ok=False, error=_error_seguro(exc, cx, job))


def main(once: bool = False) -> None:
    max_global = int(os.getenv("WORKER_MAX_JOBS", "2"))
    worker_id = _worker_id()
    cx = db.connect()
    try:
        db.init_db(cx)
        while True:
            jobs.rescatar_huerfanos(cx)
            encolar_fuentes_vencidas(cx)
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
