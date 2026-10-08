"""Clase base de proveedor y HTTP común. Los proveedores llaman `base.get_json`
(no `requests` directo) para que las pruebas lo sustituyan con respuestas grabadas."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

import requests

from src.assets import Candidata

TIMEOUT = 15
UA = "instagod/2 (+editor de assets)"


class SinLlave(Exception):
    """Falta la API key del proveedor. args[0] = nombre de la variable."""


class ErrorHttp(requests.RequestException):
    """Error HTTP/red ya saneado: solo estado y host, nunca la query (lleva API keys)."""


def _sanear(exc: requests.RequestException, url: str) -> ErrorHttp:
    host = urlsplit(url).hostname or "?"
    resp = getattr(exc, "response", None)
    estado = getattr(resp, "status_code", None)
    detalle = f"HTTP {estado}" if estado is not None else type(exc).__name__
    return ErrorHttp(f"{detalle} en {host}")


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> Any:
    try:
        r = requests.get(url, params=params, headers={"User-Agent": UA, **(headers or {})},
                         timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise _sanear(e, url) from None


def post_json(url: str, *, json_body: dict, headers: dict | None = None) -> Any:
    try:
        r = requests.post(url, json=json_body, headers={"User-Agent": UA, **(headers or {})},
                          timeout=TIMEOUT * 4)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise _sanear(e, url) from None


def enviar(metodo: str, url: str, *, headers: dict | None = None) -> None:
    """Pings de tracking (descarga de Unsplash, stats de Coverr). Sin cuerpo."""
    try:
        r = requests.request(metodo, url, headers={"User-Agent": UA, **(headers or {})},
                             timeout=TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        raise _sanear(e, url) from None


class Proveedor:
    nombre = ""
    tipos: tuple[str, ...] = ("imagen",)
    llave: str | None = None
    hosts: tuple[str, ...] | None = None
    de_pago = False

    def __init__(self, *, cx=None, account_id: int | None = None, slug: str = "",
                 creds: dict | None = None, config: dict | None = None) -> None:
        self.cx = cx
        self.account_id = account_id
        self.slug = slug
        self.creds = creds or {}
        self.config = config or {}

    def clave(self) -> str:
        if self.llave is None:
            return ""
        valor = self.creds.get(self.llave)
        if not valor:
            raise SinLlave(self.llave)
        return valor

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        raise NotImplementedError

    def registrar_descarga(self, cand: Candidata) -> None:
        return None
