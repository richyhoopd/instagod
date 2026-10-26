"""Publicación en la Página de Facebook de CADA marca (Graph API, token de Página).

Las credenciales son explícitas: `FbCreds(page_id, token)` sale de
`config.account_creds(slug)` con `creds_de()`. No hay credenciales globales ni
fallback a gdlscene: una marca sin FB_PAGE_ID/FB_PAGE_ACCESS_TOKEN lanza
`SinCredencialesFB` antes de tocar la red.

- Foto: POST /{page}/photos (url o archivo local) con caption.
- Carrusel: cada foto con published=false + POST /{page}/feed con attached_media.
- Video: POST /{page}/videos con file_url (URL pública) o, para archivo local,
  `source` directo si es chico y subida reanudable start/transfer/finish si no.
- Reel (opcional): /{page}/video_reels start → upload → finish.

Reintentos con backoff SOLO para errores transitorios de Graph (códigos 1, 2, 4,
17, 341 y HTTP 5xx). Token inválido (190), permisos (200) o permiso de app (10)
fallan a la primera con un mensaje entendible.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests

GRAPH = "https://graph.facebook.com"
API_VERSION = "v25.0"
_TIMEOUT = 60
_TIMEOUT_VIDEO = 300
REINTENTOS = 3
# Archivos locales mayores a esto suben por sesión reanudable (/videos start…).
VIDEO_SIMPLE_MAX = 25 * 1024 * 1024

_CODIGOS_TRANSITORIOS = {1, 2, 4, 17, 341}
_MENSAJES = {
    190: "El token de Facebook es inválido o expiró. Genera uno nuevo de página "
         "(usuario del sistema) y reemplaza FB_PAGE_ACCESS_TOKEN.",
    200: "El token no tiene permiso para publicar en esta página: requiere "
         "pages_manage_posts y que la página esté asignada.",
    10: "La app no tiene el permiso necesario para esta acción en la página.",
}


@dataclass(frozen=True)
class FbCreds:
    page_id: str
    token: str


@dataclass(frozen=True)
class Resultado:
    id: str
    url: str


class SinCredencialesFB(RuntimeError):
    """La marca no tiene FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN configurados."""


class FbError(RuntimeError):
    def __init__(self, mensaje: str, *, codigo: int | None = None,
                 status: int | None = None, transitorio: bool = False):
        super().__init__(mensaje)
        self.codigo = codigo
        self.status = status
        self.transitorio = transitorio


def creds_de(creds: dict | FbCreds | None, slug: str = "") -> FbCreds:
    """`account_creds(slug)` → FbCreds, o SinCredencialesFB si falta algo."""
    if isinstance(creds, FbCreds):
        return creds
    creds = creds or {}
    page_id = (creds.get("FB_PAGE_ID") or "").strip()
    token = (creds.get("FB_PAGE_ACCESS_TOKEN") or "").strip()
    if not page_id or not token:
        de = f" de {slug}" if slug else ""
        raise SinCredencialesFB(
            f"La marca{de} no tiene Facebook configurado (FB_PAGE_ID y "
            "FB_PAGE_ACCESS_TOKEN en Ajustes → Credenciales).")
    return FbCreds(page_id, token)


def tiene_creds(creds: dict | None) -> bool:
    return bool((creds or {}).get("FB_PAGE_ID") and (creds or {}).get("FB_PAGE_ACCESS_TOKEN"))


def _base() -> str:
    return f"{GRAPH}/{API_VERSION}"


def adaptar_caption(caption: str) -> str:
    """FB no recorta, pero los @ de IG ahí tampoco etiquetan: fuera arrobas."""
    return re.sub(r"@(\w[\w.]*)", r"\1", caption or "").strip()


def url_post(post_id: str) -> str:
    return f"https://www.facebook.com/{post_id}"


def url_video(page_id: str, video_id: str) -> str:
    return f"https://www.facebook.com/{page_id}/videos/{video_id}"


def url_reel(video_id: str) -> str:
    return f"https://www.facebook.com/reel/{video_id}"


# ---------- transporte con política de reintentos ----------

def _dormir(segundos: float) -> None:
    time.sleep(segundos)


def _error_de(resp: requests.Response) -> FbError:
    try:
        err = resp.json().get("error") or {}
    except Exception:  # noqa: BLE001
        err = {}
    codigo = err.get("code") if isinstance(err, dict) else None
    detalle = (err.get("message") if isinstance(err, dict) else None) or resp.text[:200]
    if codigo in _MENSAJES:
        return FbError(f"Facebook ({codigo}): {_MENSAJES[codigo]}", codigo=codigo,
                       status=resp.status_code)
    transitorio = codigo in _CODIGOS_TRANSITORIOS or resp.status_code >= 500
    return FbError(f"Graph API FB {resp.status_code} (code {codigo}): {detalle}",
                   codigo=codigo, status=resp.status_code, transitorio=transitorio)


def _llamar(metodo: str, url: str, *, reintentos: int = REINTENTOS, **kw: Any) -> dict:
    """Una llamada a Graph con backoff 1s, 2s, 4s… solo en errores transitorios."""
    kw.setdefault("timeout", _TIMEOUT)
    ultimo: Exception | None = None
    for intento in range(reintentos):
        try:
            resp = requests.request(metodo, url, **kw)
        except (requests.ConnectionError, requests.Timeout) as exc:
            ultimo = FbError(f"Sin conexión con Facebook: {type(exc).__name__}",
                             transitorio=True)
        else:
            if resp.status_code < 400:
                return resp.json()
            ultimo = _error_de(resp)
            if not ultimo.transitorio:
                raise ultimo
        if intento < reintentos - 1:
            _dormir(2 ** intento)
    assert ultimo is not None
    raise ultimo


def _post(creds: FbCreds, ruta: str, data: dict, **kw: Any) -> dict:
    data = {**data, "access_token": creds.token}
    return _llamar("POST", f"{_base()}/{ruta}", data=data, **kw)


# ---------- foto y carrusel ----------

def _es_local(ruta: str) -> bool:
    return bool(ruta) and not ruta.startswith(("http://", "https://"))


def _subir_foto(creds: FbCreds, imagen: str, *, message: str | None,
                published: bool) -> dict:
    data: dict = {"published": "true" if published else "false"}
    if message:
        data["message"] = message
    if _es_local(imagen):
        with open(imagen, "rb") as fh:
            return _post(creds, f"{creds.page_id}/photos", data, files={"source": fh})
    data["url"] = imagen
    return _post(creds, f"{creds.page_id}/photos", data)


def publicar_foto(creds: FbCreds, imagen: str, caption: str) -> Resultado:
    """Foto con caption. `imagen`: URL pública o ruta local."""
    body = _subir_foto(creds, imagen, message=adaptar_caption(caption), published=True)
    # Con published=true regresa post_id (id de la publicación) además del de la foto.
    post_id = body.get("post_id") or body["id"]
    return Resultado(post_id, url_post(post_id))


def publicar_carrusel(creds: FbCreds, imagenes: list[str], caption: str) -> Resultado:
    """Post multi-foto: fotos sin publicar colgadas de un solo post del feed."""
    imagenes = [u for u in imagenes if u]
    if not imagenes:
        raise ValueError("Carrusel sin imágenes")
    if len(imagenes) == 1:
        return publicar_foto(creds, imagenes[0], caption)
    foto_ids = [_subir_foto(creds, u, message=None, published=False)["id"] for u in imagenes]
    data = {"message": adaptar_caption(caption)}
    for i, fid in enumerate(foto_ids):
        data[f"attached_media[{i}]"] = json.dumps({"media_fbid": fid})
    post_id = _post(creds, f"{creds.page_id}/feed", data)["id"]
    return Resultado(post_id, url_post(post_id))


# ---------- video y reel ----------

def publicar_video(creds: FbCreds, video: str, caption: str) -> Resultado:
    """Video del feed. URL pública → file_url; archivo local → source o reanudable."""
    descripcion = adaptar_caption(caption)
    ruta = f"{creds.page_id}/videos"
    if not _es_local(video):
        vid = _post(creds, ruta, {"file_url": video, "description": descripcion},
                    timeout=_TIMEOUT_VIDEO)["id"]
    elif os.path.getsize(video) <= VIDEO_SIMPLE_MAX:
        with open(video, "rb") as fh:
            vid = _post(creds, ruta, {"description": descripcion},
                        files={"source": fh}, timeout=_TIMEOUT_VIDEO)["id"]
    else:
        vid = _video_reanudable(creds, video, descripcion)
    return Resultado(vid, url_video(creds.page_id, vid))


def _video_reanudable(creds: FbCreds, video: str, descripcion: str) -> str:
    ruta = f"{creds.page_id}/videos"
    tam = os.path.getsize(video)
    ini = _post(creds, ruta, {"upload_phase": "start", "file_size": str(tam)})
    sesion, vid = ini["upload_session_id"], ini["video_id"]
    desde, hasta = int(ini["start_offset"]), int(ini["end_offset"])
    with open(video, "rb") as fh:
        while desde < hasta:
            fh.seek(desde)
            trozo = fh.read(hasta - desde)
            r = _post(creds, ruta, {"upload_phase": "transfer", "upload_session_id": sesion,
                                    "start_offset": str(desde)},
                      files={"video_file_chunk": ("chunk", trozo)}, timeout=_TIMEOUT_VIDEO)
            desde, hasta = int(r["start_offset"]), int(r["end_offset"])
    _post(creds, ruta, {"upload_phase": "finish", "upload_session_id": sesion,
                        "description": descripcion})
    return vid


def publicar_reel(creds: FbCreds, video: str, caption: str) -> Resultado:
    """Reel de la página: start → upload (rupload, URL pública o archivo) → finish."""
    ruta = f"{creds.page_id}/video_reels"
    ini = _post(creds, ruta, {"upload_phase": "start"})
    vid = ini["video_id"]
    upload_url = ini.get("upload_url") or f"https://rupload.facebook.com/video-upload/{API_VERSION}/{vid}"
    headers = {"Authorization": f"OAuth {creds.token}"}
    if _es_local(video):
        with open(video, "rb") as fh:
            contenido = fh.read()
        headers.update({"offset": "0", "file_size": str(len(contenido))})
        _llamar("POST", upload_url, headers=headers, data=contenido, timeout=_TIMEOUT_VIDEO)
    else:
        headers["file_url"] = video
        _llamar("POST", upload_url, headers=headers, timeout=_TIMEOUT_VIDEO)
    _post(creds, ruta, {"upload_phase": "finish", "video_id": vid,
                        "video_state": "PUBLISHED", "description": adaptar_caption(caption)})
    return Resultado(vid, url_reel(vid))


# ---------- interfaz de `publish.py` (Sheet/Actions): devuelve solo el id ----------

def publish(image_url: str, caption: str, *, creds: dict | FbCreds | None = None) -> str:
    return publicar_foto(creds_de(creds), image_url, caption).id


def publish_carousel(image_urls: list[str], caption: str, *,
                     creds: dict | FbCreds | None = None) -> str:
    return publicar_carrusel(creds_de(creds), image_urls, caption).id
