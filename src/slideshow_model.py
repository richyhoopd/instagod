"""Contrato de datos del motor de slideshows (clon en forma de reel.farm).

Dos capas (ver spec 2026-08-09): el LLM emite un guion semántico simple; el
compilador (slideshow_compile) lo convierte en ESTE contrato completo, que es
lo que se almacena (content_queue.slideshow_json), se rinde y —a mediano
plazo— se expone como API de producto. Claves en inglés a propósito.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import config

FONT_SIZES = ("extra_extra_small", "extra_small", "small", "medium", "large",
              "extra_large")
TEXT_STYLES = ("text", "outline", "background")
# layout → (columnas, filas) de la grilla de imágenes.
IMAGE_LAYOUTS = {"single": (1, 1), "1:2": (1, 2), "1:3": (1, 3),
                 "2:1": (2, 1), "2:2": (2, 2)}
# aspect → (ancho, alto) en px de render.
ASPECT_RATIOS = {"4:5": (1080, 1350), "9:16": (1080, 1920),
                 "1:1": (1080, 1080), "16:9": (1920, 1080)}
ALINEACIONES = ("left", "center", "right")
ANCLAS_V = ("top", "center", "bottom")
# Proveniencia de la imagen (auditoría/bajadas de copyright, ver spec).
SOURCES = ("banco", "covers", "pexels", "pinterest", "manual")


@dataclass
class TextItem:
    text: str
    font_size: str = "large"
    text_color: str = "blanco"
    text_style: str = "background"
    font: str = "Poppins-Bold"
    text_width: float = 0.86          # fracción del ancho de la tarjeta
    text_align: str = "center"
    text_anchor: str = "center"       # horizontal
    text_vertical_anchor: str = "center"


@dataclass
class Slide:
    image_urls: list[str] = field(default_factory=list)  # [] = fondo sólido
    image_layout: str = "single"
    text_items: list[TextItem] = field(default_factory=list)
    is_cta: bool = False
    background_opacity: float = 0.35  # overlay oscuro sobre la(s) imagen(es)
    duration: float = 3.0             # segundos (futuro export a video)
    source: str = "manual"


@dataclass
class Slideshow:
    title: str
    aspect_ratio: str = "4:5"
    slides: list[Slide] = field(default_factory=list)
    caption: str = ""
    language: str = "es"
    brief: dict = field(default_factory=dict)
    formato: str = ""
    account_slug: str = "gdlscene"


def validar(s: Slideshow) -> list[str]:
    """Lista de errores humanos; [] = contrato válido."""
    errores: list[str] = []
    if not 1 <= len(s.slides) <= 20:
        errores.append(f"slides: deben ser 1-20, hay {len(s.slides)}")
    if s.aspect_ratio not in ASPECT_RATIOS:
        errores.append(f"aspect_ratio desconocido: {s.aspect_ratio!r}")
    for i, sl in enumerate(s.slides):
        pre = f"slide {i}"
        if sl.image_layout not in IMAGE_LAYOUTS:
            errores.append(f"{pre}: image_layout desconocido {sl.image_layout!r}")
        else:
            cols, rows = IMAGE_LAYOUTS[sl.image_layout]
            if len(sl.image_urls) > cols * rows:
                errores.append(f"{pre}: {len(sl.image_urls)} imágenes no caben "
                               f"en layout {sl.image_layout}")
        if not 0.0 <= sl.background_opacity <= 1.0:
            errores.append(f"{pre}: background_opacity fuera de [0,1]")
        if sl.source not in SOURCES:
            errores.append(f"{pre}: source desconocido {sl.source!r}")
        if not sl.text_items:
            errores.append(f"{pre}: sin text_items")
        for j, t in enumerate(sl.text_items):
            pj = f"{pre} texto {j}"
            if not (t.text or "").strip():
                errores.append(f"{pj}: texto vacío")
            if t.font_size not in FONT_SIZES:
                errores.append(f"{pj}: font_size desconocido {t.font_size!r}")
            if t.text_style not in TEXT_STYLES:
                errores.append(f"{pj}: text_style desconocido {t.text_style!r}")
            if t.text_color not in config.SLIDESHOW_PALETA:
                errores.append(f"{pj}: color fuera de paleta {t.text_color!r}")
            if t.font not in config.SLIDESHOW_FUENTES:
                errores.append(f"{pj}: fuente fuera de catálogo {t.font!r}")
            if not 0.2 <= t.text_width <= 1.0:
                errores.append(f"{pj}: text_width fuera de [0.2,1]")
            if t.text_align not in ALINEACIONES:
                errores.append(f"{pj}: text_align desconocido {t.text_align!r}")
            if t.text_anchor not in ALINEACIONES:
                errores.append(f"{pj}: text_anchor desconocido {t.text_anchor!r}")
            if t.text_vertical_anchor not in ANCLAS_V:
                errores.append(f"{pj}: text_vertical_anchor desconocido "
                               f"{t.text_vertical_anchor!r}")
    return errores


def a_json(s: Slideshow) -> str:
    return json.dumps(asdict(s), ensure_ascii=False)


def desde_json(texto: str) -> Slideshow:
    data = json.loads(texto)
    slides = []
    for sl in data.pop("slides", []):
        items = [TextItem(**t) for t in sl.pop("text_items", [])]
        slides.append(Slide(text_items=items, **sl))
    return Slideshow(slides=slides, **data)
