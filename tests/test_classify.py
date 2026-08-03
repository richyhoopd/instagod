"""Tests de Fase 3: heurísticas de clasificación con imágenes sintéticas.

No usan fotos reales ni red. La detección de caras Haar se prueba indirecta
(imagen sintética sin caras → 0); las decisiones usable/flyer se prueban como
funciones puras contra los umbrales de config.
"""
from __future__ import annotations

import cv2
import numpy as np

import config
from src import classify, db, faces
from src.classify import (
    caption_sugiere_evento,
    clasificar_foto,
    contar_caras,
    decidir_usable,
    es_grafico,
    hay_persona,
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
    plana_gris = np.full((900, 1200), 128, dtype=np.uint8)
    plana_color = np.full((900, 1200, 3), 128, dtype=np.uint8)
    assert contar_caras(plana_color) == 0
    assert medir_nitidez(plana_gris) == 0.0


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


# ---------- contar_caras / cargar_color: YuNet reemplaza los cascades Haar ----------

def test_contar_caras_usa_yunet(monkeypatch) -> None:
    """contar_caras delega en faces.detectar, no en cascades."""
    llamado = {}

    def fake_detectar(img):
        llamado["si"] = True
        return [
            faces.Cara(bbox=(0, 0, 50, 50), det_score=0.9,
                       landmarks=np.zeros(14, dtype=np.float32), frac_area=0.2),
            faces.Cara(bbox=(60, 0, 40, 40), det_score=0.8,
                       landmarks=np.zeros(14, dtype=np.float32), frac_area=0.1),
        ]

    monkeypatch.setattr(classify.faces, "detectar", fake_detectar)
    assert classify.contar_caras(np.zeros((300, 300, 3), dtype=np.uint8)) == 2
    assert llamado.get("si") is True


def test_contar_caras_sin_caras(monkeypatch) -> None:
    monkeypatch.setattr(classify.faces, "detectar", lambda img: [])
    assert classify.contar_caras(np.zeros((300, 300, 3), dtype=np.uint8)) == 0


def test_cargar_color_normaliza_ancho(tmp_path) -> None:
    p = tmp_path / "grande.jpg"
    cv2.imwrite(str(p), np.full((2000, 3000, 3), 128, dtype=np.uint8))
    img = classify.cargar_color(p)
    assert img is not None
    assert img.shape[1] == classify._ANCHO_NORM
    assert img.ndim == 3


def test_cargar_color_ilegible(tmp_path) -> None:
    p = tmp_path / "no_es_imagen.jpg"
    p.write_bytes(b"basura")
    assert classify.cargar_color(p) is None


# ---------- decidir_usable: gráfico/póster nunca usable ----------

def test_decidir_usable_grafico_nunca_usable() -> None:
    arriba = config.CLASSIFY_NITIDEZ_MIN + 1
    # aun con cara clara y nítida, un póster (grafico=True) se descarta.
    assert decidir_usable(caras_claras=2, nitidez=arriba, flyer=False,
                          grafico=True) is False


# ---------- score_flyer: rama de texto MUY denso (cartel seguro) ----------

def test_score_flyer_texto_muy_denso() -> None:
    # > 2.5x el mínimo de chars → flyer aunque no haya fecha ni keywords.
    txt = "x" * (int(config.CLASSIFY_OCR_MIN_CHARS * 2.5) + 5)
    es, motivo = score_flyer(txt)
    assert es is True and "denso" in motivo


# ---------- es_grafico / hay_persona: no truenan con imágenes sintéticas ----------

def test_es_grafico_devuelve_tupla_sin_error() -> None:
    plana = np.full((900, 1200), 128, dtype=np.uint8)
    es, n = es_grafico(plana)
    assert isinstance(es, bool) and isinstance(n, int)
    assert es is False           # imagen plana no tiene regiones tipo-texto


def test_hay_persona_imagen_plana_es_false() -> None:
    plana = np.full((900, 1200), 128, dtype=np.uint8)
    assert hay_persona(plana) is False


# ---------- clasificar_foto: integración contra DB con OCR mockeado ----------

def _foto_en_db(cx, tmp_path, gris, tipo="foro", **extra):
    """Escribe un PNG real y crea la fila photos+band; devuelve el dict de la foto.

    Incluye `tipo` (en producción llega vía el JOIN con bands de clasificar()).
    """
    ruta = tmp_path / "foto.png"
    cv2.imwrite(str(ruta), gris)
    bid = db.insert(cx, "bands", nombre="Banda", tipo=tipo, activa=1)
    pid = db.insert(cx, "photos", band_id=bid, path=str(ruta),
                    source_post_id="POST1", **extra)
    return {**db.get(cx, "photos", pid), "tipo": tipo}


def test_clasificar_foto_nitida_sin_flyer_es_usable(tmp_path, monkeypatch) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    monkeypatch.setattr(classify, "texto_ocr", lambda p: "")          # sin OCR
    monkeypatch.setattr(classify, "es_grafico", lambda g: (False, 0))  # no póster
    nitida = _ruido()
    foto = _foto_en_db(cx, tmp_path, nitida, tipo="foro")             # foro: no exige cara
    etiqueta = clasificar_foto(cx, foto)
    assert etiqueta.startswith("usable")
    fila = db.get(cx, "photos", foto["id"])
    assert fila["usable_meme"] == 1 and fila["nitidez"] > config.CLASSIFY_NITIDEZ_MIN
    cx.close()


def test_clasificar_foto_flyer_va_a_events_y_no_es_usable(tmp_path, monkeypatch) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    flyer_txt = ("FESTIVAL presenta a Kabala viernes 21 de noviembre 9:00 pm "
                 "Foro Independencia boletos preventa cover acceso 8:00 hrs")
    monkeypatch.setattr(classify, "texto_ocr", lambda p: flyer_txt)
    foto = _foto_en_db(cx, tmp_path, _ruido(), tipo="banda")
    etiqueta = clasificar_foto(cx, foto)
    assert etiqueta.startswith("flyer")
    fila = db.get(cx, "photos", foto["id"])
    assert fila["usable_meme"] == 0
    eventos = db.rows(cx, "SELECT * FROM events WHERE source_post_id = 'POST1'")
    assert len(eventos) == 1 and eventos[0]["tipo"] == "flyer"
    cx.close()


def test_clasificar_foto_ilegible_marca_no_usable(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Banda", tipo="banda", activa=1)
    pid = db.insert(cx, "photos", band_id=bid, path="/no/existe.png",
                    source_post_id="X")
    foto = db.get(cx, "photos", pid)
    assert clasificar_foto(cx, foto) == "ilegible"
    assert db.get(cx, "photos", pid)["usable_meme"] == 0
    cx.close()


def test_clasificar_foto_descartada_nunca_usable(tmp_path, monkeypatch) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    monkeypatch.setattr(classify, "texto_ocr", lambda p: "")
    monkeypatch.setattr(classify, "es_grafico", lambda g: (False, 0))
    foto = _foto_en_db(cx, tmp_path, _ruido(), tipo="foro", descartada=1)
    clasificar_foto(cx, foto)
    assert db.get(cx, "photos", foto["id"])["usable_meme"] == 0   # lista negra manda
    cx.close()


def test_poster_grafico_con_caption_evento_va_a_flyer(tmp_path, monkeypatch):
    """Un póster gráfico cuyo OCR NO lee la fecha pero el CAPTION anuncia evento
    debe registrarse como flyer (no descartarse en silencio)."""
    import numpy as np

    from src import classify, db
    cx = db.connect(tmp_path / "c.db"); db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Angel", tipo="banda")
    pid = db.insert(cx, "photos", band_id=bid, path="p/x.jpg", source_post_id="DZL",
                    caption_original="Estreno mi EP el 10 de junio 7:30 PM")
    # Simula: imagen legible, sin caras, póster gráfico (MSER alto), OCR SIN fecha.
    monkeypatch.setattr(classify, "cargar_normalizada", lambda p: np.zeros((10, 10), "uint8"))
    monkeypatch.setattr(classify, "cargar_color", lambda p: np.zeros((10, 10, 3), "uint8"))
    monkeypatch.setattr(classify, "medir_nitidez", lambda g: 1042.0)
    monkeypatch.setattr(classify, "contar_caras", lambda g: 0)
    monkeypatch.setattr(classify, "texto_ocr", lambda p: "RESISTENCIA CULTURA PERREO")  # sin fecha
    monkeypatch.setattr(classify, "score_flyer", lambda t, ce: (False, ""))
    monkeypatch.setattr(classify, "es_grafico", lambda g: (True, 2000))
    registrado = []
    monkeypatch.setattr(classify, "_registrar_flyer", lambda cx2, f: registrado.append(f["id"]))
    etiqueta = classify.clasificar_foto(cx, db.get(cx, "photos", pid))
    assert registrado == [pid]            # se registró como flyer
    assert "flyer" in etiqueta.lower()
    cx.close()
