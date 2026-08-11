"""Compilador determinista: guion semántico + preset de estilo → Slideshow.

La cosmética (fuentes, colores, tamaños, anchors) vive en
config.SLIDESHOW_ESTILOS; re-estilar un set = recompilar el MISMO guion con
otro preset, sin volver a llamar al LLM.
"""
from __future__ import annotations

from typing import Any

import config
from src.compose import FONTS_DIR, _to_src
from src.slideshow_model import ASPECT_RATIOS, IMAGE_LAYOUTS, Slide, Slideshow, TextItem

# Tamaño con nombre → px sobre diseño de 1080 de ancho (se escala por aspect).
_FONT_PX = {"extra_extra_small": 36, "extra_small": 48, "small": 60,
            "medium": 76, "large": 96, "extra_large": 128}

# Color de la caja detrás del texto (text_style=background) según el color
# del texto: texto claro → caja oscura y viceversa.
_COLORES_CLAROS = {"blanco", "crema", "amarillo", "oro"}


def _caja_para(color_nombre: str) -> str:
    if color_nombre in _COLORES_CLAROS:
        return config.SLIDESHOW_PALETA["negro"]
    return config.SLIDESHOW_PALETA["blanco"]


def compilar(guion: dict[str, Any], *, estilo: str, imagenes: list,
             aspect_ratio: str = "4:5", brief: dict | None = None,
             formato: str = "", account_slug: str = "gdlscene",
             estilos: dict | None = None) -> Slideshow:
    """guion + estilo + una imagen (o None) por slide → contrato completo.

    imagenes[i] corresponde a guion["slides"][i]; acepta cualquier objeto con
    .ruta_o_url y .source (ImagenCandidata de image_sources), o None →
    slide de fondo sólido sin overlay.

    estilos: catálogo de presets a usar (marca+global); None → config
    .SLIDESHOW_ESTILOS. Permite compilar con presets de marca que no viven
    en config (p.ej. resueltos dinámicamente por cuenta).

    Registra el estilo usado en brief para que contexto_slide pueda recuperar
    el fondo correcto del preset; sella también "fondo" y "chrome" para que
    el contrato sea AUTOCONTENIDO (el render no necesita volver a buscar el
    preset de marca, que puede no vivir en config).
    """
    catalogo = estilos if estilos is not None else config.SLIDESHOW_ESTILOS
    preset = catalogo[estilo]  # KeyError si no existe: a propósito
    slides: list[Slide] = []
    for sl, img in zip(guion["slides"], imagenes):
        rol = sl.get("rol", "punto")
        r = preset["roles"].get(rol, preset["roles"]["punto"])
        item = TextItem(text=sl["text"], font=r["font"], font_size=r["font_size"],
                        text_color=preset["texto"], text_style=r["text_style"],
                        text_vertical_anchor=r["text_vertical_anchor"])
        slides.append(Slide(
            image_urls=[img.ruta_o_url] if img else [],
            image_layout="single",
            text_items=[item],
            is_cta=(rol == "cta"),
            background_opacity=preset["background_opacity"] if img else 0.0,
            source=img.source if img else "manual",
        ))
    # Registra estilo en brief para que contexto_slide lo recupere
    brief_final = dict(brief or {})
    brief_final.setdefault("estilo", estilo)
    brief_final.setdefault("fondo", preset.get("fondo", "negro"))
    brief_final.setdefault("chrome", preset.get("chrome"))
    return Slideshow(title=guion["hook"], aspect_ratio=aspect_ratio,
                     slides=slides, caption=guion.get("caption", ""),
                     brief=brief_final, formato=formato,
                     account_slug=account_slug)


def contexto_slide(s: Slideshow, idx: int) -> dict[str, Any]:
    """Contexto Jinja2 de UN slide para templates/slide.html. PURO."""
    sl = s.slides[idx]
    width, height = ASPECT_RATIOS[s.aspect_ratio]
    cols, rows = IMAGE_LAYOUTS[sl.image_layout]
    escala = width / 1080
    items = []
    for t in sl.text_items:
        items.append({
            "text": t.text,
            "font": t.font,
            "px": round(_FONT_PX[t.font_size] * escala),
            "color": config.SLIDESHOW_PALETA[t.text_color],
            "caja": _caja_para(t.text_color),
            "estilo": t.text_style,
            "width_pct": round(t.text_width * 100),
            "align": t.text_align,
            "anchor": t.text_anchor,
            "v_anchor": t.text_vertical_anchor,
        })
    # Fondo: sale del brief (contrato autocontenido); filas viejas
    # (pre-multi-marca) no lo tienen → lookup en config como antes.
    fondo = s.brief.get("fondo")
    if not fondo:
        preset_cfg = config.SLIDESHOW_ESTILOS.get(s.brief.get("estilo", ""), {})
        fondo = preset_cfg.get("fondo", "negro")
    chrome_brief = s.brief.get("chrome") or None
    chrome = None
    if chrome_brief:
        logo = chrome_brief.get("logo")
        chrome = {"handle": chrome_brief.get("handle", ""),
                  "logo_src": _to_src(logo) if logo else None}
    return {
        "width": width,
        "height": height,
        "bg_color": config.SLIDESHOW_PALETA[fondo],
        "image_srcs": [_to_src(u) for u in sl.image_urls],
        "grid_cols": cols,
        "grid_rows": rows,
        "overlay_opacity": sl.background_opacity,
        "chrome": chrome,
        "font_faces": [{"name": nombre,
                        "url": (FONTS_DIR / archivo).as_uri(),
                        "fmt": "woff2" if archivo.endswith(".woff2") else "truetype"}
                       for nombre, archivo in config.SLIDESHOW_FUENTES.items()],
        "items": items,
    }
