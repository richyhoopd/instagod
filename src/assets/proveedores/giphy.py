"""GIPHY: GIF animado (tipo imagen) o su MP4 (tipo video). Rating g.
Atribución obligatoria «Powered by GIPHY» en la UI que muestra resultados."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class Giphy(base.Proveedor):
    nombre = "giphy"
    tipos = ("imagen", "video")
    llave = "GIPHY_API_KEY"
    hosts = ("giphy.com",)

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo not in self.tipos:
            return []
        ruta = "stickers" if self.config.get("stickers") else "gifs"
        datos = base.get_json(f"https://api.giphy.com/v1/{ruta}/search",
                              params={"api_key": self.clave(), "q": q[:50],
                                      "limit": max(1, min(n, 50)), "rating": "g"})
        items = datos.get("data") if isinstance(datos, dict) else None
        out = []
        for d in items or []:
            if not isinstance(d, dict) or d.get("id") is None:
                continue
            imgs = d.get("images") if isinstance(d.get("images"), dict) else {}
            orig = imgs.get("original") if isinstance(imgs.get("original"), dict) else {}
            fijo = imgs.get("fixed_width") if isinstance(imgs.get("fixed_width"), dict) else {}
            url = orig.get("mp4") if tipo == "video" else orig.get("url")
            if not url:
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(d["id"]), tipo=tipo, url=url,
                preview_url=fijo.get("url") or orig.get("url") or "",
                ancho=_int(orig.get("width")), alto=_int(orig.get("height")),
                autor=d.get("username") or None, licencia="GIPHY", url_origen=d.get("url")))
        return out
