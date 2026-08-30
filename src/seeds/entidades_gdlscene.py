"""Siembra las bandas de gdlscene como entidades genéricas.

No toca `bands` ni sus tablas colgadas (`photos`, `members`, `events`,
`personas`, `face_signatures`): crea el espejo en `brand_entities` con
`band_id` como puente, y liga `photos.entity_id`. Idempotente por `band_id`.
"""
from __future__ import annotations

from typing import Any

from .. import db, entidades

# Atributos del dominio musical que viajan al JSON de la entidad.
_ATRIBUTOS = (
    "ig_handle", "spotify_id", "deezer_id", "ciudad", "popularity",
    "followers_ig", "genero_principal", "category_ig",
)


def _atributos_de_banda(banda: dict[str, Any]) -> dict[str, Any]:
    return {k: banda[k] for k in _ATRIBUTOS if k in banda and banda[k] is not None}


def sembrar(cx, account_id: int = 1) -> dict[str, int]:
    creadas = existentes = 0
    bandas = db.rows(cx, "SELECT * FROM bands WHERE account_id = ?", (account_id,))
    for banda in bandas:
        if entidades.por_band_id(cx, banda["id"]) is not None:
            existentes += 1
            continue
        prioridad = banda.get("prioridad") or 3
        entidades.crear(
            cx, account_id, banda["nombre"], banda.get("tipo") or "banda",
            prioridad=max(1, min(5, int(prioridad))),
            atributos=_atributos_de_banda(banda),
            band_id=banda["id"],
            slug=entidades.slugificar(banda.get("ig_handle") or banda["nombre"]),
        )
        creadas += 1
        if not banda.get("activa", 1):
            ent = entidades.por_band_id(cx, banda["id"])
            entidades.archivar(cx, ent["id"])

    # Backfill de fotos: solo las que aún no tienen entidad.
    cx.execute(
        "UPDATE photos SET entity_id = ("
        "  SELECT e.id FROM brand_entities e WHERE e.band_id = photos.band_id"
        ") WHERE entity_id IS NULL AND band_id IS NOT NULL"
    )
    fotos = db.rows(cx, "SELECT count(*) c FROM photos WHERE entity_id IS NOT NULL")
    cx.commit()
    return {"creadas": creadas, "existentes": existentes,
            "fotos_ligadas": fotos[0]["c"]}


if __name__ == "__main__":  # pragma: no cover
    cx = db.connect()
    db.init_db(cx)
    print(sembrar(cx))
