"""Publicación en la Página de Facebook (Graph API, token permanente de Página).

Misma interfaz que `instagram.py`. Una foto = POST /{page}/photos con la URL
(Cloudinary) directa, sin descargar. Carrusel = fotos sin publicar + post con
attached_media (sin tope de 4, a diferencia de X).
"""
from __future__ import annotations

import json
import re
import time

import requests

import config

_TIMEOUT = 60


def _base() -> str:
    return f"{config.FB_GRAPH_BASE.rstrip('/')}/{config.FB_API_VERSION}"


def adaptar_caption(caption: str) -> str:
    """FB no recorta, pero los @ de IG ahí tampoco etiquetan: fuera arrobas."""
    return re.sub(r"@(\w[\w.]*)", r"\1", caption or "").strip()


def _upload_photo(image_url: str, *, message: str | None = None,
                  published: bool = True) -> str:
    data = {"url": image_url, "published": "true" if published else "false",
            "access_token": config.FB_PAGE_ACCESS_TOKEN}
    if message:
        data["message"] = message
    resp = requests.post(f"{_base()}/{config.FB_PAGE_ID}/photos", data=data, timeout=_TIMEOUT)
    _raise_for_graph(resp)
    body = resp.json()
    # Con published=true regresa post_id (id de la publicación); sin él, id de la foto.
    return body.get("post_id") or body["id"]


def publish(image_url: str, caption: str, *, retries: int = 3) -> str:
    """Publica una foto con caption y devuelve el fb_post_id."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            return _upload_photo(image_url, message=adaptar_caption(caption))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Falló la publicación en FB tras {retries} intentos: {last_err}")


def publish_carousel(image_urls: list[str], caption: str, *, retries: int = 3) -> str:
    """Post multi-foto: sube cada imagen sin publicar y las cuelga de un solo post."""
    urls = [u for u in image_urls if u]
    if len(urls) <= 1:
        return publish(urls[0], caption) if urls else ""

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            foto_ids = [_upload_photo(u, published=False) for u in urls]
            data = {"message": adaptar_caption(caption),
                    "access_token": config.FB_PAGE_ACCESS_TOKEN}
            for i, fid in enumerate(foto_ids):
                data[f"attached_media[{i}]"] = json.dumps({"media_fbid": fid})
            resp = requests.post(f"{_base()}/{config.FB_PAGE_ID}/feed", data=data,
                                 timeout=_TIMEOUT)
            _raise_for_graph(resp)
            return resp.json()["id"]
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Falló el multi-foto en FB tras {retries} intentos: {last_err}")


def _raise_for_graph(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:  # noqa: BLE001
            err = resp.text
        raise RuntimeError(f"Graph API FB {resp.status_code}: {err}")
