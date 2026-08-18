"""Correo transaccional del portal (Resend). Sin RESEND_API_KEY en dev, imprime la URL."""
from __future__ import annotations

import httpx

import config


def _post_resend(payload: dict) -> None:
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    r = httpx.post("https://api.resend.com/emails", json=payload, timeout=10,
                   headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"})
    r.raise_for_status()


def enviar_magic_link(email: str, url: str) -> None:
    if not config.RESEND_API_KEY:
        if config.ENV == "prod":
            raise RuntimeError("Falta RESEND_API_KEY para mandar magic links en prod")
        print(f"[mail] (dev) magic link para {email}: {url}")
        return
    _post_resend({
        "from": config.MAIL_FROM,
        "to": [email],
        "subject": "Tu acceso a instagod",
        "html": (f"<p>Entra a instagod con este link (vale 15 minutos):</p>"
                 f"<p><a href=\"{url}\">{url}</a></p>"
                 "<p>Si no lo pediste, ignora este correo.</p>"),
        "_url": url,   # solo para tests; _post_resend lo descarta
    })
