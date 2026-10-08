"""Pexels: fotos (/v1/search) y video (/videos/search). Auth: header Authorization con la key."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_LADO_MAX_VIDEO = 1920


def _mejor_archivo(archivos: list[dict]) -> dict | None:
    mp4 = [a for a in archivos if a.get("file_type") == "video/mp4" and a.get("link")]
    caben = [a for a in mp4 if max(a.get("width") or 0, a.get("height") or 0) <= _LADO_MAX_VIDEO]
    if caben:
        return max(caben, key=lambda a: (a.get("width") or 0) * (a.get("height") or 0))
    return min(mp4, key=lambda a: (a.get("width") or 0) * (a.get("height") or 0), default=None)


class Pexels(base.Proveedor):
    nombre = "pexels"
    tipos = ("imagen", "video")
    llave = "PEXELS_API_KEY"
    # ⚠️ sin verificar en vivo: hoy los videos salen de videos.pexels.com, pero hay
    # respuestas viejas con player.vimeo.com.
    hosts = ("images.pexels.com", "videos.pexels.com", "player.vimeo.com")

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        headers = {"Authorization": self.clave()}
        params = {"query": q, "per_page": max(1, min(n, 80))}
        if tipo == "video":
            datos = base.get_json("https://api.pexels.com/videos/search", params=params,
                                  headers=headers)
            out = []
            for v in datos.get("videos", []):
                arch = _mejor_archivo(v.get("video_files") or [])
                if arch is None:
                    continue
                out.append(Candidata(
                    proveedor=self.nombre, id_origen=str(v["id"]), tipo="video",
                    url=arch["link"], preview_url=v.get("image") or "",
                    ancho=arch.get("width"), alto=arch.get("height"),
                    autor=(v.get("user") or {}).get("name"), licencia="Pexels License",
                    url_origen=v.get("url")))
            return out
        datos = base.get_json("https://api.pexels.com/v1/search", params=params, headers=headers)
        out = []
        for f in datos.get("photos", []):
            src = f.get("src") or {}
            url = src.get("large2x") or src.get("original")
            if not url:
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(f["id"]), tipo="imagen", url=url,
                preview_url=src.get("medium") or url, ancho=f.get("width"),
                alto=f.get("height"), autor=f.get("photographer"), licencia="Pexels License",
                url_origen=f.get("url")))
        return out
