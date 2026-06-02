"""Refresh del token de larga duración de Instagram (flujo Instagram Login).

El token de 60 días se refresca contra `graph.instagram.com/refresh_access_token`
con `grant_type=ig_refresh_token`. El Proceso C (GitHub Actions) lo corre cada
~50 días. Imprime el nuevo token para que lo guardes como secret.
"""
from __future__ import annotations

import json

import requests

import config


def refresh_long_lived_token() -> dict:
    """Refresca el IG_ACCESS_TOKEN y devuelve el JSON de respuesta de Meta."""
    url = f"{config.IG_GRAPH_BASE.rstrip('/')}/refresh_access_token"
    resp = requests.get(
        url,
        params={"grant_type": "ig_refresh_token", "access_token": config.IG_ACCESS_TOKEN},
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Refresh falló {resp.status_code}: {resp.text}")
    return resp.json()


if __name__ == "__main__":
    data = refresh_long_lived_token()
    print(json.dumps(data, indent=2))
    token = data.get("access_token")
    if token:
        # En GitHub Actions este valor se captura y se actualiza el secret IG_ACCESS_TOKEN.
        print(f"\n::add-mask::{token}")
        print("NUEVO IG_ACCESS_TOKEN obtenido (válido ~60 días). Actualiza tu .env y el secret.")
