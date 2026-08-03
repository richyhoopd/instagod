"""Colapsa fotos near-duplicadas dentro de una banda.

El problema de variedad del banco no es que falten fotos: es que hay diez casi
idénticas de la misma sesión. Reusa el dHash de `src/imghash.py`, ya probado en
producción para deduplicar flyers de agenda.

`agrupar_duplicadas` es PURA: recibe hashes ya calculados, no toca disco.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def agrupar_duplicadas(fotos: list[dict[str, Any]], umbral: int) -> list[list[dict[str, Any]]]:
    """Agrupa por distancia de Hamming ≤ umbral; representante (más nítido) primero.

    Una foto con `hash` None (imagen ilegible) siempre queda sola: preferimos
    conservar de más a perder una buena por un hash que no se pudo calcular.
    """
    grupos: list[list[dict[str, Any]]] = []
    for foto in fotos:
        h = foto.get("hash")
        destino = None
        if h is not None:
            for grupo in grupos:
                cabeza = grupo[0].get("hash")
                if cabeza is not None and int(np.count_nonzero(h != cabeza)) <= umbral:
                    destino = grupo
                    break
        if destino is None:
            grupos.append([foto])
        else:
            destino.append(foto)
    return [sorted(g, key=lambda f: f.get("nitidez") or 0.0, reverse=True)
            for g in grupos]
