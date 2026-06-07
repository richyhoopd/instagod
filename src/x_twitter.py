"""Publicación en X/Twitter (OAuth 1.0 vía tweepy).

Misma interfaz que `instagram.py`: publish() / publish_carousel(). El caption
se adapta: fuera @handles de IG (en X no etiquetan a nadie) y recorte limpio a
280. Los carruseles van como HILO (X topa 4 imágenes por tweet).
"""
from __future__ import annotations

import io
import re
import time

import requests

import config

_TIMEOUT = 60
_MAX_CHARS = 280
_MAX_MEDIA = 4  # imágenes por tweet


def _clients():
    """(Client v2, API v1.1) — la v1.1 solo para subir media."""
    import tweepy

    auth_kwargs = dict(
        consumer_key=config.X_API_KEY,
        consumer_secret=config.X_API_SECRET,
        access_token=config.X_ACCESS_TOKEN,
        access_token_secret=config.X_ACCESS_SECRET,
    )
    client = tweepy.Client(**auth_kwargs)
    api_v1 = tweepy.API(tweepy.OAuth1UserHandler(**auth_kwargs))
    return client, api_v1


def adaptar_caption(caption: str, *, limite: int = _MAX_CHARS) -> str:
    """Quita los @ de IG (deja el nombre) y recorta a `limite` sin partir palabras."""
    texto = re.sub(r"@(\w[\w.]*)", r"\1", caption or "").strip()
    texto = re.sub(r"[ \t]+", " ", texto)
    if len(texto) <= limite:
        return texto
    corte = texto[: limite - 1]
    if " " in corte:
        corte = corte.rsplit(" ", 1)[0]
    return corte + "…"


def _upload_media(api_v1, image_url: str) -> int:
    """Descarga la imagen (Cloudinary) y la sube a X; devuelve media_id."""
    resp = requests.get(image_url, timeout=_TIMEOUT)
    resp.raise_for_status()
    media = api_v1.media_upload(filename="meme.png", file=io.BytesIO(resp.content))
    return media.media_id


def publish(image_url: str, caption: str, *, retries: int = 3) -> str:
    """Publica una imagen con caption adaptado y devuelve el tweet_id."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            client, api_v1 = _clients()
            media_id = _upload_media(api_v1, image_url)
            tweet = client.create_tweet(text=adaptar_caption(caption), media_ids=[media_id])
            return str(tweet.data["id"])
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Falló el tweet tras {retries} intentos: {last_err}")


def publish_carousel(image_urls: list[str], caption: str, *, retries: int = 3) -> str:
    """Publica un carrusel como HILO: tweet con 4 imágenes + replies con el resto.

    Devuelve el id del PRIMER tweet. Si un reply falla a la mitad, el hilo queda
    parcial pero el id raíz ya es válido (no se reintenta el hilo completo).
    """
    urls = [u for u in image_urls if u]
    if len(urls) <= 1:
        return publish(urls[0], caption) if urls else ""

    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            client, api_v1 = _clients()
            bloques = [urls[i:i + _MAX_MEDIA] for i in range(0, len(urls), _MAX_MEDIA)]
            media_ids = [_upload_media(api_v1, u) for u in bloques[0]]
            raiz = client.create_tweet(text=adaptar_caption(caption), media_ids=media_ids)
            raiz_id = str(raiz.data["id"])
            anterior = raiz_id
            for n, bloque in enumerate(bloques[1:], start=2):
                media_ids = [_upload_media(api_v1, u) for u in bloque]
                reply = client.create_tweet(
                    text=f"({n}/{len(bloques)})", media_ids=media_ids,
                    in_reply_to_tweet_id=anterior,
                )
                anterior = str(reply.data["id"])
            return raiz_id
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Falló el hilo tras {retries} intentos: {last_err}")
