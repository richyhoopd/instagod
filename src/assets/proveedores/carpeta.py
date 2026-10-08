"""Lo que la marca ya tiene: su biblioteca (brand_assets) y la carpeta fotos/ v1."""
from __future__ import annotations

import re

from src import assets, db
from src.assets import EXT_FOTO, NOMBRE_FOTO_RE, SLUG_RE, Candidata
from src.assets.proveedores.base import Proveedor


def _tokens(q: str) -> list[str]:
    return [t for t in re.findall(r"\w+", q.lower()) if len(t) > 1]


class Carpeta(Proveedor):
    nombre = "carpeta"
    tipos = ("imagen", "video")

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if not SLUG_RE.match(self.slug or ""):
            return []
        toks = _tokens(q)
        filas = db.rows(self.cx, "SELECT * FROM brand_assets WHERE account_id = ? AND tipo = ? "
                                 "AND descartada = 0 ORDER BY id DESC LIMIT 500",
                        (self.account_id, tipo))
        puntuadas = []
        for f in filas:
            texto = " ".join([f["archivo"], f["tags_json"] or "", f["autor"] or ""]).lower()
            puntos = sum(t in texto for t in toks)
            if puntos or not toks:
                puntuadas.append((puntos, f))
        puntuadas.sort(key=lambda p: -p[0])  # sort estable: empate conserva id DESC
        out = [Candidata(proveedor="carpeta", id_origen=str(f["id"]), tipo=tipo,
                         url=f"local:assets/{f['archivo']}",
                         preview_url=f"/brands/{self.slug}/files/assets/{f['archivo']}",
                         ancho=f["ancho"], alto=f["alto"], autor=f["autor"],
                         licencia=f["licencia"], url_origen=f["url_origen"],
                         ig_handle=f["ig_handle"], source_post_id=f["source_post_id"])
               for _, f in puntuadas]
        if tipo == "imagen":
            carpeta = assets.BRANDS_DIR / self.slug / "fotos"
            if carpeta.is_dir():
                for p in sorted(carpeta.iterdir()):
                    if (not p.is_file() or p.is_symlink() or p.suffix.lower() not in EXT_FOTO or not NOMBRE_FOTO_RE.match(p.name)
                            or (toks and not any(t in p.name.lower() for t in toks))):
                        continue
                    out.append(Candidata(
                        proveedor="carpeta", id_origen=p.name, tipo="imagen",
                        url=f"local:fotos/{p.name}",
                        preview_url=f"/brands/{self.slug}/files/fotos/{p.name}",
                        ancho=None, alto=None, autor=None, licencia="propia", url_origen=None))
        return out[:n]
