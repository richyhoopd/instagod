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

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import requests

import config

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
_YUNET = ("face_detection_yunet_2023mar.onnx",
          f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx")
_SFACE = ("face_recognition_sface_2021dec.onnx",
          f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx")
_TIMEOUT = 120

_detector = None
_reconocedor = None


@dataclass(frozen=True)
class Cara:
    bbox: tuple[int, int, int, int]      # x, y, w, h
    det_score: float
    landmarks: "np.ndarray"              # 5 puntos (10 valores) que pide SFace
    frac_area: float                     # área de la cara / área de la imagen


def _bajar(nombre: str, url: str) -> Path:
    """Descarga el modelo a data/models/ con escritura atómica. Falla ruidosa."""
    destino = config.resolve_models_dir() / nombre
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    print(f"⬇️  bajando modelo {nombre}…", file=sys.stderr)
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    tmp = destino.with_suffix(destino.suffix + ".part")
    tmp.write_bytes(resp.content)
    tmp.replace(destino)
    return destino


def asegurar_modelos() -> tuple[Path, Path]:
    """Rutas locales de (YuNet, SFace), bajándolos la primera vez."""
    return _bajar(*_YUNET), _bajar(*_SFACE)


def _motores():
    """Detector y reconocedor, creados una vez por proceso."""
    global _detector, _reconocedor
    if _detector is None or _reconocedor is None:
        import cv2
        yunet, sface = asegurar_modelos()
        _detector = cv2.FaceDetectorYN_create(
            str(yunet), "", (320, 320), config.FACE_DET_SCORE_MIN)
        _reconocedor = cv2.FaceRecognizerSF_create(str(sface), "")
    return _detector, _reconocedor


def detectar(img: "np.ndarray") -> list[Cara]:
    """Caras de la imagen que superan score y tamaño mínimos."""
    det, _ = _motores()
    alto, ancho = img.shape[:2]
    det.setInputSize((ancho, alto))
    _, crudas = det.detect(img)
    if crudas is None:
        return []
    area_img = float(alto * ancho)
    salida: list[Cara] = []
    for fila in crudas:
        x, y, w, h = (int(v) for v in fila[:4])
        score = float(fila[-1])
        frac = (w * h) / area_img
        if score < config.FACE_DET_SCORE_MIN or frac < config.FACE_CARA_MIN_FRAC:
            continue
        salida.append(Cara(bbox=(x, y, w, h), det_score=score,
                           landmarks=fila[:-1].astype(np.float32), frac_area=frac))
    return salida


def firma(img: "np.ndarray", cara: Cara) -> "np.ndarray":
    """Vector de 128 float32 L2-normalizado que identifica a la persona."""
    _, rec = _motores()
    alineada = rec.alignCrop(img, cara.landmarks.reshape(1, -1))
    vec = rec.feature(alineada).flatten().astype(np.float32)
    norma = float(np.linalg.norm(vec))
    return vec / norma if norma else vec


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
