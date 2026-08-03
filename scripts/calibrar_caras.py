"""Barre FACE_COS_MISMA_PERSONA sobre las firmas YA guardadas.

No reprocesa imágenes: lee `face_signatures` y reagrupa en memoria con
`faces.agrupar`. Sirve para elegir el umbral con datos de bandas reales en
vez de con el valor de arranque calibrado sobre pares sintéticos (Task 3).

Uso:
    .venv/bin/python scripts/calibrar_caras.py [handle ...]

Sin argumentos, barre todas las bandas que ya tengan `face_signatures`
(es decir, las que ya pasaron por `python -m src.banco`).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from src import db, faces

UMBRALES = (0.25, 0.30, 0.35, 0.363, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65)


def main() -> None:
    cx = db.connect()
    handles = sys.argv[1:]
    if not handles:
        handles = [f["ig_handle"] for f in db.rows(cx, """
            SELECT DISTINCT b.ig_handle FROM bands b
              JOIN photos p ON p.band_id = b.id
              JOIN face_signatures f ON f.photo_id = p.id
             ORDER BY b.ig_handle
        """)]
        if not handles:
            print("No hay face_signatures en la DB todavía — corre antes "
                  "`python -m src.banco <handles> --limite N`.")
            cx.close()
            return

    for handle in handles:
        handle = handle.lstrip("@")
        fila = db.rows(cx, "SELECT id, nombre, tipo FROM bands WHERE ig_handle = ?", (handle,))
        if not fila:
            print(f"@{handle}: no está en bands")
            continue
        banda = fila[0]
        firmas = db.rows(cx, """
            SELECT f.embedding FROM face_signatures f
              JOIN photos p ON p.id = f.photo_id
             WHERE p.band_id = ?
        """, (banda["id"],))
        vecs = [np.frombuffer(f["embedding"], dtype=np.float32) for f in firmas]
        print(f"\n@{handle} ({banda['tipo'] or '?'}) — {len(vecs)} cara(s)")
        if not vecs:
            print("  sin firmas guardadas (corre `python -m src.banco` primero)")
            continue
        for u in UMBRALES:
            grupos = faces.agrupar(vecs, u)
            tam = sorted((len(g) for g in grupos), reverse=True)[:6]
            print(f"  umbral {u:.3f} → {len(grupos):2d} persona(s), tamaños {tam}")
    cx.close()


if __name__ == "__main__":
    main()
