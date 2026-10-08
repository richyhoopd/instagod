"""Generación con fal.ai FLUX schnell. DE PAGO: buscar.py solo lo corre si la
llamada lo pide por nombre y la marca tiene la fuente activa (spec §4).
Sin verificar: header `Authorization: Key ...`, host de las imágenes y precio."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_MAX = 4


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class IaImagen(base.Proveedor):
    nombre = "ia_imagen"
    tipos = ("imagen",)
    llave = "FAL_KEY"
    hosts = ("fal.media",)
    de_pago = True

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        # Guardas anti-gasto: cada llamada a fal.ai cuesta dinero.
        if tipo != "imagen" or not (q or "").strip() or n < 1:
            return []
        datos = base.post_json("https://fal.run/fal-ai/flux/schnell",
                               json_body={"prompt": q[:500], "image_size": "portrait_4_3",
                                          "num_images": max(1, min(n, _MAX))},
                               headers={"Authorization": f"Key {self.clave()}"})
        if not isinstance(datos, dict):
            return []
        nsfw = datos.get("has_nsfw_concepts")
        nsfw = nsfw if isinstance(nsfw, list) else []
        imagenes = datos.get("images")
        seed = datos.get("seed", "x")
        out = []
        for i, img in enumerate(imagenes if isinstance(imagenes, list) else []):
            if not isinstance(img, dict) or not img.get("url") or (i < len(nsfw) and nsfw[i]):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=f"{seed}-{i}", tipo="imagen", url=img["url"],
                preview_url=img["url"], ancho=_int(img.get("width")), alto=_int(img.get("height")),
                autor=None, licencia="Generada (fal.ai)", url_origen=None))
        return out
