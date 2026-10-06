"""Mensajes sueltos al Telegram de UNA marca (alertas de feed, ZIP de 9:16).

`approval.enviar_a_telegram` es la tarjeta de aprobación (fotos + botones);
esto es lo mínimo para texto y documentos con las mismas credenciales por
marca (`approval._creds_de` → config.account_creds) y el mismo redactado de
secretos (`approval._error_seguro`). Nunca levanta: devuelve bool y loguea.
"""
from __future__ import annotations

import sys
from pathlib import Path

from src import approval


def _destino(slug: str) -> tuple[str, str] | None:
    creds = approval._creds_de(slug)
    token, chat_id = creds.get("TELEGRAM_BOT_TOKEN"), creds.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print(f"[avisos] {slug}: sin TELEGRAM_BOT_TOKEN/CHAT_ID, no se avisa",
              file=sys.stderr)
        return None
    return token, chat_id


def enviar_texto(slug: str, texto: str) -> bool:
    import requests
    dest = _destino(slug)
    if dest is None:
        return False
    token, chat_id = dest
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat_id, "text": texto[:4000]},
                          timeout=30)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[avisos] {slug}: sendMessage falló: "
              f"{approval._error_seguro(e, token=token, chat_id=chat_id)}",
              file=sys.stderr)
        return False


def enviar_documento(slug: str, ruta: str | Path, caption: str = "") -> bool:
    import requests
    dest = _destino(slug)
    if dest is None:
        return False
    token, chat_id = dest
    ruta = Path(ruta)
    try:
        with ruta.open("rb") as fh:
            r = requests.post(f"https://api.telegram.org/bot{token}/sendDocument",
                              data={"chat_id": chat_id, "caption": caption[:1000]},
                              files={"document": (ruta.name, fh, "application/zip")},
                              timeout=120)
        r.raise_for_status()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[avisos] {slug}: sendDocument falló: "
              f"{approval._error_seguro(e, token=token, chat_id=chat_id)}",
              file=sys.stderr)
        return False
