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
# (nombre, url, tamaño mínimo plausible en bytes). Los reales pesan 232 KB y
# 38.7 MB; el mínimo es holgado (la mitad) — sirve para atajar un cuerpo
# truncado o una página de error, no para verificar la versión exacta.
_YUNET = ("face_detection_yunet_2023mar.onnx",
          f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
          100_000)
_SFACE = ("face_recognition_sface_2021dec.onnx",
          f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
          19_000_000)
_TIMEOUT = 120
# Un .onnx es un protobuf `ModelProto` cuyo primer campo es `ir_version`
# (field 1, varint) → el archivo SIEMPRE empieza con el byte de tag 0x08.
# Un 200 con HTML ('<') o un redirect en texto jamás empiezan así.
_ONNX_MAGIC = b"\x08"

_detector = None
_reconocedor = None


@dataclass(frozen=True)
class Cara:
    bbox: tuple[int, int, int, int]      # x, y, w, h
    det_score: float
    landmarks: "np.ndarray"              # 5 puntos (10 valores) que pide SFace
    frac_area: float                     # área de la cara / área de la imagen


def _es_onnx(path: Path, minimo: int) -> bool:
    """¿El archivo en disco parece el ONNX esperado? (bytes mágicos + tamaño)."""
    try:
        if path.stat().st_size < minimo:
            return False
        with path.open("rb") as fh:
            return fh.read(len(_ONNX_MAGIC)) == _ONNX_MAGIC
    except OSError:
        return False


def _bajar(nombre: str, url: str, minimo: int) -> Path:
    """Descarga el modelo a data/models/ con escritura atómica. Falla ruidosa.

    Mismo patrón que `src.covers.asegurar_cover`: descarga → VALIDA → escritura
    atómica. Sin la validación, un 200 con HTML (portal cautivo, página de error
    de GitHub) o un cuerpo truncado se cacheaban para siempre: el early-return
    por `exists()` los reusaba en cada corrida y el síntoma era un error de cv2
    sin relación aparente, que solo se curaba borrando `data/models/` a mano.

    Por eso el archivo YA cacheado también se valida: un ONNX corrupto de una
    corrida vieja se re-baja solo, sin intervención manual.
    """
    destino = config.resolve_models_dir() / nombre
    if destino.exists() and _es_onnx(destino, minimo):
        return destino
    print(f"⬇️  bajando modelo {nombre}…", file=sys.stderr)
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    tmp = destino.with_suffix(destino.suffix + ".part")
    tmp.write_bytes(resp.content)
    if not _es_onnx(tmp, minimo):
        cabeza = resp.content[:16]
        tmp.unlink(missing_ok=True)
        raise RuntimeError(
            f"descarga inválida de {nombre} desde {url}: se esperaba un ONNX "
            f"(≥{minimo} bytes, empezando con {_ONNX_MAGIC!r}) y llegaron "
            f"{len(resp.content)} bytes que empiezan con {cabeza!r}. "
            f"No se cacheó nada en {destino.parent}.")
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
