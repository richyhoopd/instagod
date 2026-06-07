"""Publicación en Instagram (Content Publishing).

Tu .env usa el flujo *Instagram Login* (`graph.instagram.com`), así que tanto el
container como el publish y la consulta de estado van contra esa base. Flujo de
2 pasos: crear container → publicar.
"""
from __future__ import annotations

import time

import requests

import config

_TIMEOUT = 60


def _base() -> str:
    return f"{config.IG_GRAPH_BASE.rstrip('/')}/{config.IG_API_VERSION}"


def _create_container(image_url: str, caption: str) -> str:
    url = f"{_base()}/{config.IG_USER_ID}/media"
    resp = requests.post(
        url,
        data={"image_url": image_url, "caption": caption, "access_token": config.IG_ACCESS_TOKEN},
        timeout=_TIMEOUT,
    )
    _raise_for_graph(resp)
    return resp.json()["id"]


def _create_carousel_item(image_url: str) -> str:
    """Container hijo de un carrusel (sin caption, con is_carousel_item)."""
    url = f"{_base()}/{config.IG_USER_ID}/media"
    resp = requests.post(
        url,
        data={"image_url": image_url, "is_carousel_item": "true",
              "access_token": config.IG_ACCESS_TOKEN},
        timeout=_TIMEOUT,
    )
    _raise_for_graph(resp)
    return resp.json()["id"]


def _create_carousel_container(children: list[str], caption: str) -> str:
    url = f"{_base()}/{config.IG_USER_ID}/media"
    resp = requests.post(
        url,
        data={"media_type": "CAROUSEL", "children": ",".join(children),
              "caption": caption, "access_token": config.IG_ACCESS_TOKEN},
        timeout=_TIMEOUT,
    )
    _raise_for_graph(resp)
    return resp.json()["id"]


def _wait_until_ready(creation_id: str, *, attempts: int = 10, delay: float = 3.0) -> None:
    """Espera a que el container esté FINISHED antes de publicar."""
    url = f"{_base()}/{creation_id}"
    for _ in range(attempts):
        resp = requests.get(
            url,
            params={"fields": "status_code,status", "access_token": config.IG_ACCESS_TOKEN},
            timeout=_TIMEOUT,
        )
        _raise_for_graph(resp)
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"Container {creation_id} en ERROR: {resp.json()}")
        time.sleep(delay)
    # Algunos containers de imagen nunca reportan status; intentamos publicar igual.


def _publish(creation_id: str) -> str:
    url = f"{_base()}/{config.IG_USER_ID}/media_publish"
    resp = requests.post(
        url,
        data={"creation_id": creation_id, "access_token": config.IG_ACCESS_TOKEN},
        timeout=_TIMEOUT,
    )
    _raise_for_graph(resp)
    return resp.json()["id"]


def publish(image_url: str, caption: str, *, retries: int = 3) -> str:
    """Publica una imagen y devuelve el `ig_post_id`. Reintenta con backoff."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            creation_id = _create_container(image_url, caption)
            _wait_until_ready(creation_id)
            return _publish(creation_id)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Falló la publicación tras {retries} intentos: {last_err}")


def publish_carousel(image_urls: list[str], caption: str, *, retries: int = 3) -> str:
    """Publica un carrusel (2-10 imágenes) y devuelve el `ig_post_id`.

    Flujo IG: un container hijo por imagen → un container CAROUSEL con los hijos →
    publicar. Si solo hay 1 url, cae a `publish` normal.
    """
    urls = [u for u in image_urls if u]
    if len(urls) <= 1:
        return publish(urls[0], caption) if urls else ""
    urls = urls[:10]  # IG topa el carrusel en 10
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            children = [_create_carousel_item(u) for u in urls]
            for c in children:
                _wait_until_ready(c)
            parent = _create_carousel_container(children, caption)
            _wait_until_ready(parent)
            return _publish(parent)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Falló el carrusel tras {retries} intentos: {last_err}")


def _raise_for_graph(resp: requests.Response) -> None:
    if resp.status_code >= 400:
        try:
            err = resp.json().get("error", resp.text)
        except Exception:  # noqa: BLE001
            err = resp.text
        raise RuntimeError(f"Graph API {resp.status_code}: {err}")
