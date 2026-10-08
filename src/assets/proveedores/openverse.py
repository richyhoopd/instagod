"""Openverse (CC y dominio público), anónimo. license_type=commercial deja fuera NC;
aquí además se descarta ND porque el editor recorta y modifica la imagen."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base


def _licencia(lic: str, version: str | None) -> str:
    if lic in ("cc0", "pdm"):
        return "CC0" if lic == "cc0" else "Dominio público"
    return f"CC {lic.upper()} {version or ''}".strip()


class Openverse(base.Proveedor):
    nombre = "openverse"
    tipos = ("imagen",)

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo != "imagen":
            return []
        datos = base.get_json("https://api.openverse.org/v1/images/",
                              params={"q": q[:200], "page_size": max(1, min(n, 20)),
                                      "license_type": "commercial", "mature": "false"})
        resultados = datos.get("results") if isinstance(datos, dict) else None
        out = []
        for r in resultados or []:
            if not isinstance(r, dict) or r.get("id") is None or not r.get("url"):
                continue
            lic = r.get("license")
            if not isinstance(lic, str):
                continue  # licencia no textual: se descarta el item, no el lote
            lic = lic.lower()
            # sin licencia declarada no se puede usar; ND no, porque el editor modifica la imagen
            if not lic or r.get("mature") or "nd" in lic.split("-"):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(r["id"]), tipo="imagen", url=r["url"],
                preview_url=r.get("thumbnail") or r["url"], ancho=r.get("width"),
                alto=r.get("height"), autor=r.get("creator"),
                licencia=_licencia(lic, r.get("license_version")),
                url_origen=r.get("foreign_landing_url")))
        return out
