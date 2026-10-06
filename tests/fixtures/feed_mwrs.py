"""Item con la forma del feed de MWRS (contrato v1) para tests."""
from __future__ import annotations

import copy


def item(id_="lote-esquina-melaque", **cambios):
    base = {
        "id": id_, "type": "lot", "updated_at": "2026-10-06T18:00:00Z",
        "status": "active",
        "title": {"es": "Lote esquina en Melaque", "en": "Corner lot in Melaque"},
        "summary": "Lote esquina a dos cuadras de la playa.",
        "url": f"https://melaquecapital.com/es/propiedades/{id_}",
        "media": [{"url": f"https://melaquecapital.com/img/{id_}-1.jpg",
                   "alt": "frente", "kind": "image"},
                  {"url": f"https://melaquecapital.com/img/{id_}-2.jpg",
                   "alt": "calle", "kind": "image"}],
        "facts": {"precio": "$1,450,000 MXN", "m2": 300, "regimen": "ejidal"},
        "unverified": ["regimen"],
        "tags": ["lote", "melaque"],
        "locale": "es",
    }
    out = copy.deepcopy(base)
    out.update(cambios)
    return out


def sobre(items, cursor=None):
    return {"version": 1, "brand": "melaquecapital", "cursor": cursor, "items": items}
