"""Coverr: stock de video gratis. Bearer auth; registrar la descarga con PATCH stats."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_API = "https://api.coverr.co"


class Coverr(base.Proveedor):
    nombre = "coverr"
    tipos = ("video",)
    llave = "COVERR_API_KEY"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.clave()}"}

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo != "video":
            return []
        datos = base.get_json(f"{_API}/videos",
                              params={"query": q[:100], "page_size": max(1, min(n, 50)),
                                      "urls": "true"},
                              headers=self._headers())
        hits = datos.get("hits") if isinstance(datos, dict) else None
        out = []
        for h in hits or []:
            if not isinstance(h, dict) or h.get("id") is None:
                continue
            urls = h.get("urls") if isinstance(h.get("urls"), dict) else {}
            if not urls.get("mp4"):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(h["id"]), tipo="video", url=urls["mp4"],
                preview_url=h.get("thumbnail") or urls.get("mp4_preview") or "",
                ancho=h.get("max_width"), alto=h.get("max_height"), autor=None,
                licencia="Coverr License", url_origen=f"https://coverr.co/videos/{h['id']}"))
        return out

    def registrar_descarga(self, cand: Candidata) -> None:
        base.enviar("PATCH", f"{_API}/videos/{cand.id_origen}/stats/downloads",
                    headers=self._headers())
