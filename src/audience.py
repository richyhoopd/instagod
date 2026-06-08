"""Fetcher de online_followers de IG → tabla audience_activity.

Lee el endpoint /{uid}/insights?metric=online_followers&period=lifetime
(solo lectura; no publica nada). Parsea los valores hora→count por día,
agrega por (dow, hora) y hace upsert en audience_activity.

Pre-vuelo: este endpoint devuelve value:{} vacío mientras @gdlscene tenga
<100 seguidores; fetch_online_followers lo maneja sin error (log + no escribe).
En cuanto haya datos, timing.elegir_slot los consumirá vía cargar().
"""
from __future__ import annotations

import logging
from typing import Any

import requests

import config
from src import db

_LOG = logging.getLogger(__name__)
_TIMEOUT = 60


def _base() -> str:
    """URL base de la Graph API (igual que ig_insights._base)."""
    return f"{config.IG_GRAPH_BASE.rstrip('/')}/{config.IG_API_VERSION}"


def _parsear_online_followers(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Convierte la respuesta de online_followers en filas {dow, hora, valor}.

    IG devuelve una lista de objetos values[] donde cada uno tiene:
      end_time: timestamp del día  (ISO 8601 UTC)
      value:    dict str(hora) → int(conteo)   — hora en zona local de la cuenta

    Agrega SUMANDO por (dow, hora) ya que el endpoint da snapshots diarios:
    al acumular varias semanas la suma refleja el tráfico histórico relativo
    (lo que importa es el peso relativo, no el valor absoluto).
    """
    acum: dict[tuple[int, int], int] = {}
    for bloque in payload.get("data", []):
        for entrada in bloque.get("values", []):
            valor_dia: dict[str, int] = entrada.get("value") or {}
            if not valor_dia:
                continue
            # end_time: "2026-06-01T23:00:00+0000" → día; weekday = dow (0=lunes).
            end_time = entrada.get("end_time", "")
            try:
                # Parsear solo la fecha (primeros 10 chars "YYYY-MM-DD").
                from datetime import datetime
                fecha = datetime.strptime(end_time[:10], "%Y-%m-%d")
                dow = fecha.weekday()   # 0=lunes … 6=domingo
            except (ValueError, TypeError):
                # Si end_time es inválido, no se puede asignar dow: saltar.
                continue
            for hora_str, conteo in valor_dia.items():
                try:
                    hora = int(hora_str)
                    if not (0 <= hora <= 23):
                        continue
                    acum[(dow, hora)] = acum.get((dow, hora), 0) + int(conteo)
                except (ValueError, TypeError):
                    continue

    return [{"dow": dow, "hora": hora, "valor": val}
            for (dow, hora), val in sorted(acum.items())]


def fetch_online_followers(account_id: int = 1) -> list[dict[str, Any]]:
    """GET /{uid}/insights?metric=online_followers&period=lifetime.

    Usa creds de account_creds('gdlscene') para account_id=1; cuando haya
    multi-cuenta habrá que mapear account_id → slug.
    Devuelve las filas parseadas (vacío si IG no tiene datos todavía).
    """
    # Por ahora: account_id=1 = gdlscene (default); usa los tokens globales.
    creds = config.account_creds("gdlscene")
    uid = creds.get("IG_USER_ID") or config.IG_USER_ID
    token = creds.get("IG_ACCESS_TOKEN") or config.IG_ACCESS_TOKEN

    if not uid or not token:
        _LOG.warning("audience: sin credenciales de IG, salteando fetch")
        return []

    url = f"{_base()}/{uid}/insights"
    params = {
        "metric": "online_followers",
        "period": "lifetime",
        "access_token": token,
    }
    try:
        resp = requests.get(url, params=params, timeout=_TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("audience: error al llamar a IG (%s), salteando", exc)
        return []

    filas = _parsear_online_followers(payload)
    if not filas:
        _LOG.info("audience: online_followers vacío (cuenta pequeña), nada que escribir")
    return filas


def upsert_audience(cx, account_id: int, filas: list[dict[str, Any]]) -> int:
    """Upsert de filas {dow, hora, valor} en audience_activity. Devuelve n escritas."""
    if not filas:
        return 0
    n = 0
    for f in filas:
        cx.execute(
            """INSERT INTO audience_activity (account_id, dow, hora, valor)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (account_id, dow, hora)
               DO UPDATE SET valor = excluded.valor,
                             updated_at = datetime('now')""",
            (account_id, f["dow"], f["hora"], f["valor"]),
        )
        n += 1
    cx.commit()
    return n


def sync(cx, account_id: int = 1) -> int:
    """Fetch + upsert completo. Devuelve filas escritas (0 si vacío)."""
    filas = fetch_online_followers(account_id)
    return upsert_audience(cx, account_id, filas)


def cargar(cx, account_id: int = 1) -> list[dict[str, Any]]:
    """Lee audience_activity para la cuenta → lista de {dow, hora, valor}.

    Se pasa directamente a timing.elegir_slot(audiencia=...).
    """
    return db.rows(cx,
        "SELECT dow, hora, valor FROM audience_activity WHERE account_id = ? ORDER BY dow, hora",
        (account_id,),
    )
