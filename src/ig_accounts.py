"""Pool de cuentas scraper de IG con reposo (cooldown) tras quemarse.

Cada cuenta es una identidad de sesión de lectura: cookie `sessionid` del
navegador + su `user-agent` EXACTO (IG amarra una a otra). Cuando IG
soft-bloquea una (401/429 en el feed), `ingest_ig` la marca quemada por
`SCRAPER_COOLDOWN_HORAS` y rota a la siguiente sana; el reposo persiste entre
corridas (el cron de mañana sabe cuáles siguen frías).

Las cuentas viven en `data/ig_accounts.json` (gitignored: son secretos). Si el
archivo no existe se cae a la cookie única del `.env` → compatibilidad total con
el setup anterior. NUNCA se loguea por script (eso quema cuentas; ver memoria).

Formato del JSON:
    [{"label": "tulana", "sessionid": "...", "ua": "Mozilla/5.0 ...",
      "quemada_hasta": null}, ...]
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import config


def _path(path: str | Path | None) -> Path:
    return Path(path) if path else config.resolve_ig_accounts_path()


def cargar(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Pool de cuentas. Fallback al `.env` si no hay JSON; vacío si tampoco hay."""
    p = _path(path)
    if p.exists():
        datos = json.loads(p.read_text(encoding="utf-8"))
        return datos if isinstance(datos, list) else []
    if config.IG_SCRAPER_SESSIONID and config.IG_SCRAPER_UA:
        return [{"label": "env", "sessionid": config.IG_SCRAPER_SESSIONID,
                 "ua": config.IG_SCRAPER_UA, "quemada_hasta": None}]
    return []


def _sana(cuenta: dict[str, Any], ahora: datetime) -> bool:
    hasta = cuenta.get("quemada_hasta")
    if not hasta:
        return True
    try:
        return datetime.fromisoformat(hasta) <= ahora
    except ValueError:
        return True  # valor corrupto → trátala como sana, no la pierdas


def siguiente_sana(cuentas: list[dict[str, Any]],
                   ahora: datetime | None = None) -> dict[str, Any] | None:
    """Primera cuenta con cooldown vencido/nulo; None si todas en reposo."""
    ahora = ahora or datetime.now()
    return next((c for c in cuentas if _sana(c, ahora)), None)


def marcar_quemada(label: str, horas: int | None = None,
                   path: str | Path | None = None,
                   ahora: datetime | None = None) -> None:
    """Pone `quemada_hasta = ahora + horas` para `label` y reescribe el JSON (atómico).

    Si el pool venía del `.env` (sin archivo), lo materializa al JSON para poder
    recordar el reposo entre corridas.
    """
    horas = horas if horas is not None else config.SCRAPER_COOLDOWN_HORAS
    ahora = ahora or datetime.now()
    p = _path(path)
    cuentas = cargar(p)
    hasta = (ahora + timedelta(hours=horas)).isoformat(timespec="seconds")
    for c in cuentas:
        if c.get("label") == label:
            c["quemada_hasta"] = hasta
    _guardar(cuentas, p)


def _guardar(cuentas: list[dict[str, Any]], path: Path) -> None:
    """Escritura atómica: tmp + replace (no deja el JSON a medias si truena)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cuentas, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
