"""Verifica el cimiento de H1 contra una DB real (o una copia).

Uso:
    .venv/bin/python scripts/verificar_h1.py data/copia-de-prod.db

Corre init_db (idempotente) y los dos seeds, y reporta si el conteo de
entidades cuadra con el de bandas y si no se perdieron fotos.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import db, entidades, plantillas  # noqa: E402
from src.seeds import entidades_gdlscene, plantillas_gdlscene  # noqa: E402


def main(ruta: str) -> int:
    cx = db.connect(ruta)
    fotos_antes = db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"]
    bandas = db.rows(cx, "SELECT count(*) c FROM bands WHERE account_id = 1")[0]["c"]

    db.init_db(cx)
    db.init_db(cx)  # idempotencia: la 2a corrida no debe truenar

    r_ent = entidades_gdlscene.sembrar(cx, 1)
    r_tpl = plantillas_gdlscene.sembrar(cx, 1)

    fotos_despues = db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"]
    ents = len(entidades.listar(cx, 1, solo_activas=False))
    tpls = len(plantillas.listar(cx, 1))
    huerfanas = db.rows(
        cx, "SELECT count(*) c FROM photos WHERE band_id IS NOT NULL "
            "AND entity_id IS NULL")[0]["c"]

    print(f"bandas de gdlscene ......... {bandas}")
    print(f"entidades tras el seed ..... {ents}  (nuevas {r_ent['creadas']})")
    print(f"plantillas tras el seed .... {tpls}  (nuevas {r_tpl['creadas']})")
    print(f"fotos antes / después ...... {fotos_antes} / {fotos_despues}")
    print(f"fotos con banda y sin entidad {huerfanas}")

    fallas = []
    if ents != bandas:
        fallas.append(f"entidades ({ents}) != bandas ({bandas})")
    if fotos_despues != fotos_antes:
        fallas.append(f"se perdieron fotos: {fotos_antes} -> {fotos_despues}")
    if huerfanas:
        fallas.append(f"{huerfanas} fotos con band_id quedaron sin entity_id")
    if tpls < 4:
        fallas.append(f"solo hay {tpls} plantillas, se esperaban al menos 4")

    if fallas:
        print("\n🔴 FALLAS:")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("\n🟢 H1 íntegro")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
