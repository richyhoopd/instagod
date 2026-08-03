"""Detección y firma facial con los modelos que ya trae OpenCV.

YuNet (detector) y SFace (reconocedor) vienen incluidos en OpenCV ≥4.5.4 como
`FaceDetectorYN` y `FaceRecognizerSF`; los pesos son dos ONNX que se cachean en
`data/models/`. Se eligieron sobre InsightFace/dlib porque no agregan ninguna
dependencia de Python ni compilan extensiones de C — la misma razón por la que
el OCR vive en RapidOCR.

`similitud` y `agrupar` son PURAS y no tocan disco ni modelos: toda la política
de agrupamiento se puede probar con vectores sintéticos.
"""
from __future__ import annotations

import numpy as np


def similitud(a: "np.ndarray", b: "np.ndarray") -> float:
    """Coseno entre dos firmas. Asume vectores L2-normalizados (los da `firma`)."""
    return float(np.dot(a, b))


def agrupar(firmas: list["np.ndarray"], umbral: float) -> list[list[int]]:
    """Agrupa índices de firmas por similitud ≥ umbral (enlace simple).

    Enlace simple = transitivo: si a se parece a b y b a c, los tres caen en el
    mismo grupo aunque a y c no se parezcan directamente. Es lo correcto aquí:
    las caras de una misma persona forman una cadena a través de poses
    intermedias (frontal → tres cuartos → perfil).

    Devuelve los grupos ordenados de mayor a menor tamaño.
    """
    n = len(firmas)
    padre = list(range(n))

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if similitud(firmas[i], firmas[j]) >= umbral:
                ri, rj = raiz(i), raiz(j)
                if ri != rj:
                    padre[ri] = rj

    grupos: dict[int, list[int]] = {}
    for i in range(n):
        grupos.setdefault(raiz(i), []).append(i)
    return sorted(grupos.values(), key=len, reverse=True)
