"""Política del banco: qué fotos se conservan por banda.

PURO y sin IO — recibe fotos con sus caras ya agrupadas y devuelve qué ids
entran. Vive aparte porque es la pieza que se va a ajustar con el tiempo y debe
poder probarse sin imágenes ni base de datos.

El cupo es POR PERSONA, no por banda: un tope por banda puede llenarse con
diez fotos del vocalista y dejar al baterista fuera, que es exactamente el
problema que este banco resuelve.
"""
from __future__ import annotations

from typing import Any


def puntuar(foto: dict[str, Any]) -> float:
    """Qué tan buena es como retrato: nitidez × confianza × tamaño de la cara.

    Sin caras cae a la nitidez sola. El factor de tamaño evita que gane una
    foto nitidísima donde la persona sale de 20 píxeles al fondo.
    """
    nitidez = float(foto.get("nitidez") or 0.0)
    caras = foto.get("caras") or []
    if not caras:
        return nitidez
    mejor = max(caras, key=lambda c: c.get("frac_area", 0.0))
    return nitidez * float(mejor.get("det_score", 0.0)) * float(mejor.get("frac_area", 0.0))


def aplicar_cupo(fotos: list[dict[str, Any]], por_persona: int, grupales: int,
                 minimo_sin_caras: int) -> set[int]:
    """Ids que entran al banco.

    Tres cubetas independientes: una por persona (fotos de una sola cara), una
    de grupales (2+ caras), y la degradación sin caras para foros y paisajes.
    """
    ordenadas = sorted(fotos, key=puntuar, reverse=True)
    individuales = [f for f in ordenadas if len(f.get("caras") or []) == 1]
    de_grupo = [f for f in ordenadas if len(f.get("caras") or []) >= 2]
    sin_caras = [f for f in ordenadas if not (f.get("caras") or [])]

    dentro: set[int] = set()
    usado: dict[int, int] = {}
    for f in individuales:
        idx = f["caras"][0]["persona_idx"]
        if usado.get(idx, 0) < por_persona:
            usado[idx] = usado.get(idx, 0) + 1
            dentro.add(f["id"])

    dentro.update(f["id"] for f in de_grupo[:grupales])

    # Degradación: solo si la banda no dio material con caras.
    if not dentro:
        dentro.update(f["id"] for f in sin_caras[:minimo_sin_caras])
    return dentro
