"""Unsplash: GET /search/photos. La guía de la API exige pegarle a
/photos/{id}/download cuando la foto se usa (registrar_descarga)."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_API = "https://api.unsplash.com"


class Unsplash(base.Proveedor):
    nombre = "unsplash"
    tipos = ("imagen",)
    llave = "UNSPLASH_ACCESS_KEY"
    hosts = ("images.unsplash.com",)

    def _headers(self) -> dict:
        return {"Authorization": f"Client-ID {self.clave()}", "Accept-Version": "v1"}

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo != "imagen":
            return []
        datos = base.get_json(f"{_API}/search/photos",
                              params={"query": q, "per_page": max(1, min(n, 30)),
                                      "content_filter": "high"},
                              headers=self._headers())
        out = []
        for r in datos.get("results", []):
            urls, user = r.get("urls") or {}, r.get("user") or {}
            if not urls.get("regular"):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(r["id"]), tipo="imagen",
                url=urls["regular"], preview_url=urls.get("small") or urls["regular"],
                ancho=r.get("width"), alto=r.get("height"), autor=user.get("name"),
                licencia="Unsplash License", url_origen=(r.get("links") or {}).get("html")))
        return out

    def registrar_descarga(self, cand: Candidata) -> None:
        # Ping sin cuerpo: `enviar` no parsea la respuesta (el endpoint devuelve {"url": ...}).
        base.enviar("GET", f"{_API}/photos/{cand.id_origen}/download", headers=self._headers())
