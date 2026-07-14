"""Watchdog del approval-daemon: reinicia si el latido envejece (poller zombie).

Corre bajo launchd cada pocos minutos (com.gdlscene.daemon-watchdog). Si el
daemon dejó de latir (loop congelado o updater muerto sin que el proceso salga),
launchd/KeepAlive NO lo recupera porque el proceso sigue vivo; este watchdog sí:
hace `launchctl kickstart -k` y avisa por Telegram.

Uso:
    python -m src.daemon_watchdog            # revisa y actúa
    python -m src.daemon_watchdog --dry-run  # sólo reporta
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

import pytz

import config
from src import daemon_health

LABEL = "com.gdlscene.approval-daemon"


def _kickstart() -> tuple[bool, str]:
    """Reinicia el daemon vía launchctl. Devuelve (ok, salida)."""
    target = f"gui/{os.getuid()}/{LABEL}"
    try:
        r = subprocess.run(
            ["launchctl", "kickstart", "-k", target],
            capture_output=True, text=True, timeout=30,
        )
        ok = r.returncode == 0
        return ok, (r.stderr or r.stdout).strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def _avisar(texto: str) -> None:
    """Aviso por Telegram directo (sin poller). Reusa el helper de check_releases."""
    try:
        from src.check_releases import avisar_telegram
        avisar_telegram(texto)
    except Exception as e:  # noqa: BLE001 — el aviso nunca debe tumbar el watchdog
        print(f"WARNING aviso TG: {e}", file=sys.stderr)


def revisar(*, dry_run: bool = False, ahora: datetime | None = None) -> bool:
    """Revisa el latido. Si está viejo/ausente, reinicia el daemon. True si actuó."""
    ahora = ahora or datetime.now(pytz.timezone(config.TIMEZONE))
    hb = daemon_health.leer_latido()
    if not daemon_health.necesita_reinicio(hb, ahora):
        print(f"OK: daemon latiendo (último latido: {hb}).")
        return False

    edad = "ausente" if not hb else hb
    print(f"ALERTA: latido {edad} > umbral {daemon_health.UMBRAL_REINICIO_SEG}s.")
    if dry_run:
        print("[dry-run] no reinicio.")
        return True

    ok, salida = _kickstart()
    msg = (f"🔁 Watchdog reinició el approval-daemon (poller sin latir). "
           f"launchctl: {'ok' if ok else 'FALLÓ — ' + salida}. Último latido: {edad}.")
    print(msg)
    _avisar(msg)
    return True


def main() -> int:
    dry = "--dry-run" in sys.argv
    revisar(dry_run=dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
