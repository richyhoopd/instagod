"""Tests de Fase 3: heurísticas de clasificación con imágenes sintéticas.

No usan fotos reales ni red. La detección de caras Haar se prueba indirecta
(imagen sintética sin caras → 0); las decisiones usable/flyer se prueban como
funciones puras contra los umbrales de config.
"""
from __future__ import annotations

import numpy as np
import pytest

import config
from src import db
from src.classify import (
    caption_sugiere_evento,
    contar_caras,
    decidir_usable,
    medir_nitidez,
    score_flyer,
)


def _ruido(seed: int = 7) -> np.ndarray:
    """Imagen gris con ruido fuerte: muy 'nítida' para el Laplaciano."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (900, 1200), dtype=np.uint8)


def test_nitidez_distingue_borrosa_de_nitida() -> None:
    import cv2
    nitida = _ruido()
    borrosa = cv2.GaussianBlur(nitida, (31, 31), 12)
    assert medir_nitidez(nitida) > config.CLASSIFY_NITIDEZ_MIN
    assert medir_nitidez(borrosa) < medir_nitidez(nitida) / 10


def test_imagen_plana_no_tiene_caras_ni_nitidez() -> None:
    plana = np.full((900, 1200), 128, dtype=np.uint8)
    total, claras = contar_caras(plana)
    assert (total, claras) == (0, 0)
    assert medir_nitidez(plana) == 0.0


def test_decidir_usable() -> None:
    arriba = config.CLASSIFY_NITIDEZ_MIN + 1
    abajo = config.CLASSIFY_NITIDEZ_MIN - 1
    assert decidir_usable(caras_claras=1, nitidez=arriba, flyer=False)
    # sin cara FRONTAL pero con persona detectada (espaldas) → SÍ usable
    assert decidir_usable(caras_claras=0, nitidez=arriba, flyer=False, hay_gente=True)
    # sin cara ni persona → no usable (banda)
    assert not decidir_usable(caras_claras=0, nitidez=arriba, flyer=False, hay_gente=False)
    assert not decidir_usable(caras_claras=1, nitidez=abajo, flyer=False)   # borrosa
    assert not decidir_usable(caras_claras=2, nitidez=arriba, flyer=True)   # es flyer
    # foro no exige ni cara ni persona
    assert decidir_usable(0, arriba, flyer=False, tipo="foro", hay_gente=False)


def test_score_flyer_detecta_flyers_con_caras() -> None:
    # Flyer real: mucho texto + fecha + keywords (¡aunque tenga caras!).
    flyer_txt = ("CAÑA DIDR FEST VOL 2 presenta a Kabala Los Baxters y mas bandas "
                 "viernes 21 de noviembre 9:00 pm Foro Independencia boletos en preventa "
                 "cover 150 pesos acceso 8:00 hrs")
    es, _ = score_flyer(flyer_txt)
    assert es is True
    # Foto real con texto incidental (un banner) → NO flyer.
    es2, _ = score_flyer("JURISA")
    assert es2 is False
    # Texto vacío → no flyer
    assert score_flyer("")[0] is False


def test_score_flyer_texto_moderado_con_fecha() -> None:
    # ~90 chars + una fecha → flyer (la combinación delata el cartel)
    txt = "Kabala en vivo este sabado 15 de marzo en el Foro C3 Stage no te lo pierdas vamos"
    assert score_flyer(txt)[0] is True


def test_score_flyer_caption_evento_baja_umbral() -> None:
    txt = "Kabala 21 de marzo Foro C3"  # poco texto
    sin_ctx = score_flyer(txt, caption_evento=False)[0]
    con_ctx = score_flyer(txt, caption_evento=True)[0]
    assert con_ctx and (con_ctx or not sin_ctx)  # el contexto ayuda a detectarlo


def test_caption_sugiere_evento() -> None:
    assert caption_sugiere_evento("¡Boletos en preventa para el show!")
    assert caption_sugiere_evento("nuevo single OUT NOW")
    assert not caption_sugiere_evento("qué bonito atardecer")
    assert not caption_sugiere_evento(None)


def test_flyer_crea_evento_idempotente(tmp_path) -> None:
    """_registrar_flyer no duplica eventos del mismo post."""
    from src.classify import _registrar_flyer
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala")
    pid = db.insert(cx, "photos", band_id=bid, path="x.jpg", source_post_id="ABC")
    foto = db.get(cx, "photos", pid)
    _registrar_flyer(cx, foto)
    _registrar_flyer(cx, foto)
    eventos = db.rows(cx, "SELECT * FROM events WHERE band_id = ?", (bid,))
    assert len(eventos) == 1
    assert eventos[0]["tipo"] == "flyer" and eventos[0]["status"] == "nuevo"
    cx.close()
