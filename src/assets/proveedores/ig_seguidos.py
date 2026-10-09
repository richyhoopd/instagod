"""Proveedor «Seguidos de IG»: assets ya ingeridos por ig.ingerir (local, sin red)."""
from __future__ import annotations

import json
from typing import Any

from src import db
from src.assets import Candidata
from src.assets.proveedores import base

_LIMITE = 100


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class IgSeguidosProvider(base.Proveedor):
    """Sin llave ni hosts: lee brand_assets con el cx/account_id/slug que le pasa
    buscar_con_avisos (constructor del plan 3)."""
    nombre = "ig_seguidos"
    etiqueta = "Seguidos de IG"
    tipos = ("imagen", "video")

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo not in self.tipos:
            return []
        sql = """
            SELECT a.* FROM brand_assets a
             WHERE a.account_id = ? AND a.proveedor = 'ig_seguidos' AND a.tipo = ?
               AND COALESCE(a.descartada, 0) = 0
               AND NOT EXISTS (
                   SELECT 1 FROM brand_ig_cuentas c
                    WHERE c.account_id = a.account_id AND c.ig_handle = a.ig_handle
                      AND c.estado = 'descartada')
        """
        params: list[Any] = [self.account_id, tipo]
        texto = (q or "").strip().lstrip("@").lower()
        if texto:
            patron = f"%{_escapar_like(texto)}%"
            # Solo handle y caption: un LIKE sobre todo tags_json casaría con las claves.
            sql += (" AND (lower(COALESCE(a.ig_handle, '')) LIKE ? ESCAPE '\\'"
                    " OR lower(COALESCE(json_extract(a.tags_json, '$.caption'), ''))"
                    " LIKE ? ESCAPE '\\')")
            params += [patron, patron]
        sql += " ORDER BY a.id DESC LIMIT ?"
        params.append(max(1, min(int(n), _LIMITE)))
        return [self._candidata(dict(f)) for f in db.rows(self.cx, sql, tuple(params))]

    def _candidata(self, f: dict[str, Any]) -> Candidata:
        tags = json.loads(f["tags_json"] or "{}")
        vista = tags.get("poster") or f["archivo"]
        return Candidata(
            proveedor=self.nombre, id_origen=str(f["id"]), tipo=f["tipo"],
            url=f"local:assets/{f['archivo']}",          # lo resuelve biblioteca._importar_local
            preview_url=f"/brands/{self.slug}/files/assets/{vista}",
            ancho=f["ancho"], alto=f["alto"], autor=f["autor"], licencia=f["licencia"],
            url_origen=f["url_origen"], ig_handle=f["ig_handle"],
            source_post_id=f["source_post_id"])
