"""Clasificación de fotos (Fase 3): caras + nitidez + detección de flyers.

Por cada foto sin clasificar calcula:
- `faces_count` / `es_grupal`: caras Haar de OpenCV (frontales; suficiente para
  decidir "hay alguien claro en la foto" sin modelos pesados).
- `nitidez`: varianza del Laplaciano sobre la imagen normalizada a 1200px de
  ancho (mismo denominador para todas → el umbral del .env es comparable).
- `usable_meme`: ≥1 cara clara (tamaño mínimo relativo) + nitidez sobre umbral
  y que no sea flyer.
- Flyer: mucho texto por OCR (tesseract spa+eng) y pocas caras → fila en
  `events` (tipo='flyer'; la Fase 5 la parsea con el LLM) y la foto queda
  no-usable.

El OCR solo corre cuando faces_count <= 1 (los flyers casi nunca tienen caras
detectables); eso evita pagar tesseract en cada foto de banda.

Uso:
    python -m src.classify                 # todas las fotos sin clasificar
    python -m src.classify kabala_oficial  # solo esa banda
    python -m src.classify --redo          # reclasifica también las ya hechas
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import config
from src import db

import re

_ANCHO_NORM = 1200  # las métricas se calculan a este ancho

# Palabras de caption que delatan anuncio/fecha (refuerzan la señal del OCR).
_KEYWORDS_EVENTO = {
    "toca", "show", "presale", "preventa", "boletos", "tickets", "fecha",
    "gira", "tour", "lanzamiento", "estreno", "single", "sencillo", "álbum",
    "album", "out now", "ya disponible", "sold out", "cover", "entrada",
}

# Cascadas para caras: frontal (2 variantes) + perfil. El perfil se corre también
# sobre la imagen espejeada para cubrir el otro lado. Así se detectan caras de
# perfil y en ángulo, no solo de frente.
_HAAR = cv2.data.haarcascades
_FRONTAL = [cv2.CascadeClassifier(_HAAR + n) for n in
            ("haarcascade_frontalface_default.xml", "haarcascade_frontalface_alt2.xml")]
_PERFIL = cv2.CascadeClassifier(_HAAR + "haarcascade_profileface.xml")
# Cuerpos: para fotos de espaldas / sin cara visible (siguen siendo de la banda).
_UPPER = cv2.CascadeClassifier(_HAAR + "haarcascade_upperbody.xml")
_hog = cv2.HOGDescriptor()
_hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

# Señales de FLYER en el texto OCR (independientes de cuántas caras haya).
_FLYER_KEYWORDS = (
    "presenta", "presentan", "vol.", "vol ", "fest", "festival", "tour", "gira",
    "boletos", "preventa", "presale", "cover", "entrada", "en vivo", "live",
    "line up", "lineup", "feat", " ft ", "sold out", "8:00", "9:00", "10:00",
    "pm", "hrs", "horas", "puerta", "acceso", "foro", "venue", "escenario",
    "early bird", "after", "tocada", "concierto",
)
# Fechas/horas: fuerte señal de cartel. Días, meses, dd/mm, año, hora.
_DIAS = "lunes|martes|miércoles|miercoles|jueves|viernes|sábado|sabado|domingo"
_MESES = ("ene|feb|mar|abr|may|jun|jul|ago|sep|oct|nov|dic|"
          "enero|febrero|marzo|abril|mayo|junio|julio|agosto|"
          "septiembre|octubre|noviembre|diciembre")
_RE_FECHA = re.compile(
    rf"\b(\d{{1,2}}\s*(de\s*)?({_MESES}))\b|"      # "21 nov", "05 JUNIO", "5 de junio"
    rf"\b(\d{{1,2}}[/.\-]\d{{1,2}}([/.\-]\d{{2,4}})?)\b|"  # 21/11, 30.05.2026, 5-6-26
    rf"\b(20\d\d)\b|\b(\d{{1,2}}:\d{{2}})\b|\b({_DIAS})\b",  # año, hora, día semana
    re.IGNORECASE,
)


# ---------- Métricas puras (testeables sin DB) ----------

def cargar_normalizada(path: Path) -> "np.ndarray | None":
    """Imagen en gris a ancho fijo; None si el archivo no se puede leer."""
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0:
        return None
    h, w = img.shape
    if w != _ANCHO_NORM:
        escala = _ANCHO_NORM / w
        img = cv2.resize(img, (_ANCHO_NORM, max(1, int(h * escala))))
    return img


def medir_nitidez(gris: "np.ndarray") -> float:
    """Varianza del Laplaciano: bajo = borrosa, alto = nítida."""
    return float(cv2.Laplacian(gris, cv2.CV_64F).var())


def _solapan(a, b, umbral: float = 0.4) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / min(aw * ah, bw * bh) > umbral if inter else False


def contar_caras(gris: "np.ndarray") -> tuple[int, int]:
    """(caras_total, caras_claras) usando frontal + perfil + perfil espejeado.

    Detecta caras de frente, de perfil y en ángulo (no solo frontales). Deduplica
    detecciones solapadas. "Clara" = lado ≥ fracción del lado menor de la imagen.
    """
    cajas: list[tuple] = []
    espejo = cv2.flip(gris, 1)
    ancho = gris.shape[1]
    detectores = [(c, False) for c in _FRONTAL] + [(_PERFIL, False), (_PERFIL, True)]
    for det, en_espejo in detectores:
        img = espejo if en_espejo else gris
        for (x, y, w, h) in det.detectMultiScale(img, scaleFactor=1.1,
                                                  minNeighbors=5, minSize=(36, 36)):
            if en_espejo:
                x = ancho - x - w  # coordenada de vuelta a la imagen original
            caja = (int(x), int(y), int(w), int(h))
            if not any(_solapan(caja, c) for c in cajas):
                cajas.append(caja)
    min_lado = min(gris.shape) * config.CLASSIFY_CARA_MIN_FRAC
    claras = sum(1 for (_, _, w, h) in cajas if min(w, h) >= min_lado)
    return len(cajas), claras


_mser = cv2.MSER_create()


def es_grafico(gris: "np.ndarray") -> tuple[bool, int]:
    """¿Es un PÓSTER/FLYER/dibujo (no una foto)? Detecta tipografía artística que
    el OCR no lee, contando regiones tipo-texto (MSER).

    Los flyers dibujados/diseñados tienen MUCHÍSIMAS regiones de texto (miles);
    las fotos reales muy pocas (<800). Devuelve (es_grafico, n_regiones).
    """
    h, w = gris.shape
    g = cv2.resize(gris, (800, max(1, int(800 * h / w)))) if w != 800 else gris
    try:
        regiones, _ = _mser.detectRegions(g)
        n = len(regiones)
    except cv2.error:
        return False, 0
    return n >= config.CLASSIFY_MSER_FLYER, n


def hay_persona(gris: "np.ndarray") -> bool:
    """True si hay al menos una persona (aunque sea de espaldas/sin cara visible).

    HOG de cuerpo completo + cascada de torso. Cubre las fotos de banda en
    escenario donde no se ve cara de frente.
    """
    try:
        rects, _ = _hog.detectMultiScale(gris, winStride=(8, 8), padding=(8, 8),
                                         scale=1.05)
        if len(rects) > 0:
            return True
    except cv2.error:
        pass
    torsos = _UPPER.detectMultiScale(gris, scaleFactor=1.1, minNeighbors=4,
                                     minSize=(60, 60))
    return len(torsos) > 0


def texto_ocr(path: Path) -> str:
    """Texto detectado por tesseract (es+en) sobre el archivo original.

    Se llama al binario directo (no pytesseract: su parser de stderr truena
    con bytes no-UTF8 que tesseract emite a veces). Vacío si falla. Rápido pero
    flojo con tipografía artística → para flyers usa `texto_ocr_fuerte`.
    """
    import subprocess
    try:
        proc = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", "spa+eng"],
            capture_output=True, timeout=30,
        )
        return proc.stdout.decode("utf-8", errors="replace").strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"   ⚠️  OCR falló: {exc}")
        return ""


_rapid_engine = None  # RapidOCR es pesado de inicializar: carga perezosa, una vez.


def texto_ocr_fuerte(path: Path) -> str:
    """OCR potente (RapidOCR/ONNX, modelos PaddleOCR) que SÍ lee tipografía
    estilizada/dibujada de flyers. Más lento que tesseract; para extraer fechas.
    Cae a tesseract si RapidOCR falla.
    """
    global _rapid_engine
    try:
        if _rapid_engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _rapid_engine = RapidOCR()
        res, _ = _rapid_engine(str(path))
        return " ".join(x[1] for x in res) if res else ""
    except Exception as exc:  # noqa: BLE001 — sin OCR fuerte, usamos tesseract
        print(f"   ⚠️  RapidOCR falló ({str(exc)[:60]}); uso tesseract")
        return texto_ocr(path)


def caption_sugiere_evento(caption: str | None) -> bool:
    low = (caption or "").lower()
    return any(k in low for k in _KEYWORDS_EVENTO)


def score_flyer(ocr_text: str, caption_evento: bool = False) -> tuple[bool, str]:
    """¿Es flyer? Por DENSIDAD de texto + fechas + keywords, SIN importar las caras.

    Un flyer tiene mucho texto, casi siempre una fecha/hora y palabras de cartel.
    Una foto real puede traer texto incidental (un banner, una marca) pero poco.
    Devuelve (es_flyer, motivo).
    """
    low = ocr_text.lower()
    chars = len(re.sub(r"\s+", "", ocr_text))   # caracteres sin espacios
    fechas = len(_RE_FECHA.findall(ocr_text))
    kws = sum(1 for k in _FLYER_KEYWORDS if k in low)

    base = config.CLASSIFY_OCR_MIN_CHARS  # 80 por default

    # 1) Texto MUY denso → flyer seguro (cartel cargado, aunque tenga caras).
    if chars >= base * 2.5:
        return True, f"texto denso ({chars} chars)"
    # 2) Texto moderado + fecha o varias keywords → flyer.
    if chars >= base and (fechas >= 1 or kws >= 2):
        return True, f"texto+señales ({chars} chars, {fechas} fecha/s, {kws} kw)"
    # 3) Texto corto-medio CON fecha Y keyword → la combinación delata el cartel.
    if chars >= base // 2 and fechas >= 1 and kws >= 1:
        return True, f"fecha+keyword ({chars} chars)"
    # 4) Contexto: si el caption del post ya habla de evento, una fecha en poco
    #    texto basta (el OCR rara vez inventa una fecha coherente).
    if caption_evento and fechas >= 1 and chars >= 20:
        return True, f"caption-evento + fecha ({chars} chars)"
    return False, ""


# Tipos cuyo contenido NO depende de una persona: el lugar o el cartel sirven igual.
_TIPOS_SIN_CARA = {"foro", "evento", "colectivo"}


def decidir_usable(caras_claras: int, nitidez: float, flyer: bool,
                   tipo: str = "banda", hay_gente: bool = False,
                   grafico: bool = False) -> bool:
    """Una foto sirve para meme si está nítida, NO es flyer/gráfico y tiene gente.

    `grafico` = póster/flyer/dibujo detectado visualmente (MSER). Ya no exige cara
    FRONTAL: basta una persona detectada. foro/evento/colectivo no exigen persona
    (vale el lugar), pero un gráfico/póster nunca es usable.
    """
    if flyer or grafico or nitidez < config.CLASSIFY_NITIDEZ_MIN:
        return False
    if tipo in _TIPOS_SIN_CARA:
        return True
    return caras_claras >= 1 or hay_gente


# ---------- Clasificación contra la DB ----------

def clasificar_foto(cx, foto: dict[str, Any]) -> str:
    """Clasifica una foto y persiste. Devuelve etiqueta para el log."""
    path = Path(foto["path"])
    if not path.is_absolute():
        path = config.BASE_DIR / path
    gris = cargar_normalizada(path)
    if gris is None:
        db.update(cx, "photos", foto["id"], usable_meme=0, faces_count=0, nitidez=0.0)
        return "ilegible"

    nitidez = medir_nitidez(gris)
    total, claras = contar_caras(gris)

    # OCR SIEMPRE: los flyers también traen caras, así que el texto manda.
    texto = texto_ocr(path)
    flyer, motivo_flyer = score_flyer(
        texto, caption_sugiere_evento(foto.get("caption_original")))

    # Detección VISUAL de póster/flyer dibujado (tipografía que el OCR no lee).
    grafico, n_mser = (False, 0) if flyer else es_grafico(gris)

    # Solo gastamos el detector de personas si hace falta para decidir usable.
    tipo = foto.get("tipo", "banda")
    gente = False
    if not flyer and not grafico and tipo not in _TIPOS_SIN_CARA and claras == 0:
        gente = hay_persona(gris)

    usable = decidir_usable(claras, nitidez, flyer, tipo, gente, grafico)
    if foto.get("descartada"):
        usable = False  # lista negra manual: jamás usable, pase lo que pase
    db.update(cx, "photos", foto["id"],
              faces_count=total,
              es_grupal=1 if claras >= 2 else 0,
              nitidez=round(nitidez, 1),
              usable_meme=1 if usable else 0)

    if flyer:
        _registrar_flyer(cx, foto)
        return f"flyer→events ({motivo_flyer})"
    if grafico:
        # Si además trae fecha/keywords, lo mandamos a eventos como flyer.
        if _RE_FECHA.search(texto):
            _registrar_flyer(cx, foto)
            return f"flyer dibujado→events (mser {n_mser})"
        return f"gráfico/póster descartado (mser {n_mser})"
    if usable:
        quien = f"{claras} cara(s)" if claras else ("persona" if gente else "lugar")
        return f"usable ({quien}, nitidez {nitidez:.0f})"
    if nitidez < config.CLASSIFY_NITIDEZ_MIN:
        return f"borrosa (nitidez {nitidez:.0f})"
    return "sin gente detectable"


def _registrar_flyer(cx, foto: dict[str, Any]) -> None:
    """Crea el evento del flyer si no existe ya (idempotente por post de origen)."""
    ya = db.rows(cx, "SELECT 1 FROM events WHERE band_id = ? AND source_post_id = ?",
                 (foto["band_id"], foto["source_post_id"]))
    if not ya:
        db.insert(cx, "events", band_id=foto["band_id"], tipo="flyer",
                  flyer_path=foto["path"], source_post_id=foto["source_post_id"],
                  status="nuevo")


def clasificar(handles: list[str] | None = None, redo: bool = False) -> dict[str, int]:
    """Clasifica las fotos pendientes (o todas con --redo). Devuelve conteos."""
    cx = db.connect()
    try:
        db.init_db(cx)
        where = "" if redo else "AND p.faces_count IS NULL"
        params: list[Any] = []
        if handles:
            marks = ",".join("?" * len(handles))
            where += f" AND b.ig_handle IN ({marks})"
            params = [h.lstrip("@").lower() for h in handles]
        fotos = db.rows(cx, f"""
            SELECT p.*, b.ig_handle, b.tipo FROM photos p
              JOIN bands b ON b.id = p.band_id
             WHERE 1=1 {where} ORDER BY p.band_id, p.id
        """, params)
        if not fotos:
            print("No hay fotos por clasificar.")
            return {}

        print(f"Clasificando {len(fotos)} foto(s)…")
        conteo: dict[str, int] = {"usable": 0, "flyer": 0, "descartada": 0}
        for foto in fotos:
            etiqueta = clasificar_foto(cx, foto)
            if etiqueta.startswith("usable"):
                conteo["usable"] += 1
            elif etiqueta.startswith("flyer"):
                conteo["flyer"] += 1
            else:
                conteo["descartada"] += 1
            print(f"  [{foto['ig_handle']}] {Path(foto['path']).name}: {etiqueta}")
        print(f"\nResumen: {conteo['usable']} usables · {conteo['flyer']} flyers "
              f"→ events · {conteo['descartada']} descartadas")
        return conteo
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clasificación de fotos (Fase 3)")
    parser.add_argument("handles", nargs="*", help="limitar a estos ig_handle")
    parser.add_argument("--redo", action="store_true",
                        help="reclasificar también las fotos ya clasificadas")
    args = parser.parse_args()
    try:
        clasificar(args.handles or None, redo=args.redo)
    except KeyboardInterrupt:
        sys.exit("\nClasificación interrumpida.")
