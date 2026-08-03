"""Colapsa fotos near-duplicadas dentro de una banda.

El problema de variedad del banco no es que falten fotos: es que hay diez casi
idénticas de la misma sesión. Reusa el dHash de `src/imghash.py`, ya probado en
producción para deduplicar flyers de agenda.

`agrupar_duplicadas` es PURA: recibe hashes ya calculados, no toca disco.
"""
from __future__ import annotations

from typing import Any

from src import imghash


def agrupar_duplicadas(fotos: list[dict[str, Any]], umbral: int) -> list[list[dict[str, Any]]]:
    """Agrupa por distancia de Hamming ≤ umbral; representante (más nítido) primero.

    Una foto con `hash` None (imagen ilegible) siempre queda sola: preferimos
    conservar de más a perder una buena por un hash que no se pudo calcular.

    NOTA SOBRE NO-TRANSITIVIDAD: La comparación es greedy contra la cabeza (fundadora)
    de cada grupo, no entre todos los miembros. Eso hace el resultado dependiente del
    orden de entrada: en una ráfaga con deriva gradual (A~B, B~C, …), es posible que
    Z acabe solo aunque sea casi idéntico a su vecina Y. Esto se eligió a propósito
    porque el modo de falla es conservador: deduplica de menos (más grupos de lo
    óptimo), nunca fusiona indebidamente ni pierde una foto. Contrasta con
    `faces.agrupar`, que sí es transitiva porque ahí el costo de partir a una persona
    en dos grupos distintos es mucho mayor.
    """
    grupos: list[list[dict[str, Any]]] = []
    for foto in fotos:
        h = foto.get("hash")
        destino = None
        if h is not None:
            for grupo in grupos:
                cabeza = grupo[0].get("hash")
                if cabeza is not None and imghash.es_duplicado(h, [cabeza], umbral):
                    destino = grupo
                    break
        if destino is None:
            grupos.append([foto])
        else:
            destino.append(foto)
    return [sorted(g, key=lambda f: f.get("nitidez") or 0.0, reverse=True)
            for g in grupos]
