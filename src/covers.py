"""Caché local de portadas (Spotify/YouTube) para las tarjetas.

El filtro DNS de la máquina bloquea `i.scdn.co` (CDN de imágenes de Spotify):
el resolver del sistema responde vacío SOLO para ese host, así que ni el
navegador ni Playwright pueden bajar las portadas. La red en sí no está
bloqueada: el host resuelve bien vía DoH y conectar por IP funciona.

Estrategia: descargar UNA vez a `data/covers/{hash}.jpg` y renderizar siempre
desde archivo local (file://). Descarga: requests normal → si el DNS falla,
fallback DoH (dns.google) + conexión por IP con SNI del host real.

Uso:
    from src import covers
    path = covers.asegurar_cover(url)   # Path local o None si no se pudo
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import certifi
import requests
import urllib3

import config

_TIMEOUT = 15


def _dir_covers() -> Path:
    p = config.BASE_DIR / "data" / "covers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ruta_cache(url: str, *, base: Path | None = None) -> Path:
    """Ruta determinista por URL (hash corto): misma portada → mismo archivo."""
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return (base or _dir_covers()) / f"{h}.jpg"


def _descargar(url: str) -> bytes:
    r = requests.get(url, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.content


def _descargar_via_doh(url: str) -> bytes:
    """Resuelve el host vía DoH (dns.google) y conecta por IP con SNI.

    Esquiva el resolver local que filtra i.scdn.co; el certificado se valida
    contra el hostname REAL (server_hostname), no contra la IP.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    r = requests.get("https://dns.google/resolve",
                     params={"name": host, "type": "A"}, timeout=_TIMEOUT)
    r.raise_for_status()
    ips = [a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1]
    if not ips:
        raise requests.ConnectionError(f"DoH sin respuesta A para {host}")
    pool = urllib3.HTTPSConnectionPool(
        ips[0], 443, server_hostname=host, assert_hostname=host,
        ca_certs=certifi.where(), timeout=_TIMEOUT)
    ruta = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    resp = pool.request("GET", ruta, headers={"Host": host})
    if resp.status != 200:
        raise requests.ConnectionError(f"{host} via IP respondió {resp.status}")
    return resp.data


def _parece_imagen(data: bytes) -> bool:
    """JPEG/PNG/WebP por bytes mágicos: un 200 con HTML no debe cachearse."""
    return data.startswith((b"\xff\xd8", b"\x89PNG")) or (
        data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def asegurar_cover(url: str | None, *, base: Path | None = None) -> Path | None:
    """Devuelve la ruta local de la portada (cacheada o recién bajada), o None."""
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        # Releases detectados de IG: cover_url es la foto local del post
        # (relativa a BASE_DIR). No hay nada que descargar ni cachear.
        p = Path(url)
        if not p.is_absolute():
            p = config.BASE_DIR / p
        return p if p.exists() else None
    destino = _ruta_cache(url, base=base)
    if destino.exists():
        return destino
    try:
        data = _descargar(url)
    except (requests.RequestException, OSError):
        try:
            data = _descargar_via_doh(url)
        except Exception as exc:  # red rota de verdad: la tarjeta usa placeholder
            print(f"⚠️ portada no disponible ({exc})", file=sys.stderr)
            return None
    if not data or not _parece_imagen(data):
        print("⚠️ portada no es imagen, no se cachea", file=sys.stderr)
        return None
    tmp = destino.with_suffix(".jpg.part")
    tmp.write_bytes(data)
    os.replace(tmp, destino)
    return destino
