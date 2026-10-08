"""Pixabay: fotos (/api/) y video (/api/videos/). La API exige cachear 24 h;
la caché se indexa SIN la key para no escribir secretos a disco."""
from __future__ import annotations

import hashlib
import json
import os
import time

from src import assets
from src.assets import Candidata
from src.assets.proveedores import base

_TTL = 24 * 3600


def _cacheado(url: str, params: dict, llave: str) -> dict:
    sin_llave = {k: v for k, v in params.items() if k != "key"}
    h = hashlib.sha1(json.dumps([url, sin_llave], sort_keys=True).encode()).hexdigest()
    ruta = assets.CACHE_DIR / "pixabay" / f"{h}.json"
    if ruta.is_file() and time.time() - ruta.stat().st_mtime < _TTL:
        try:
            return json.loads(ruta.read_text())
        except ValueError:
            pass  # caché corrupta: se vuelve a pedir y se reescribe
    datos = base.get_json(url, params={**sin_llave, "key": llave})
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = ruta.with_name(ruta.name + ".part")
        tmp.write_text(json.dumps(datos))
        os.replace(tmp, ruta)
    except OSError:
        pass  # sin caché la consulta se repite después; el dato ya vino y se devuelve
    return datos


def _hits(datos) -> list[dict]:
    hits = datos.get("hits") if isinstance(datos, dict) else None
    return [h for h in (hits or []) if isinstance(h, dict) and h.get("id") is not None]


class Pixabay(base.Proveedor):
    nombre = "pixabay"
    tipos = ("imagen", "video")
    llave = "PIXABAY_API_KEY"
    hosts = ("pixabay.com",)

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo not in self.tipos:
            return []
        llave = self.clave()
        params = {"q": q[:100], "per_page": max(3, min(n, 200)), "safesearch": "true"}
        out = []
        if tipo == "video":
            datos = _cacheado("https://pixabay.com/api/videos/", params, llave)
            for h in _hits(datos):
                v = h.get("videos") if isinstance(h.get("videos"), dict) else {}
                arch = v.get("medium") or v.get("large") or v.get("small")
                if not isinstance(arch, dict) or not arch.get("url"):
                    continue
                out.append(Candidata(
                    proveedor=self.nombre, id_origen=str(h["id"]), tipo="video",
                    url=arch["url"], preview_url=arch.get("thumbnail") or "",
                    ancho=arch.get("width"), alto=arch.get("height"), autor=h.get("user"),
                    licencia="Pixabay Content License", url_origen=h.get("pageURL")))
            return out
        datos = _cacheado("https://pixabay.com/api/", {**params, "image_type": "photo"}, llave)
        for h in _hits(datos):
            url = h.get("largeImageURL") or h.get("webformatURL")
            if not url:
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(h["id"]), tipo="imagen", url=url,
                preview_url=h.get("webformatURL") or url, ancho=h.get("imageWidth"),
                alto=h.get("imageHeight"), autor=h.get("user"),
                licencia="Pixabay Content License", url_origen=h.get("pageURL")))
        return out
