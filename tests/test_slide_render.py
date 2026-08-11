"""Smoke de render de slide.html: rinde y auto-fitea, sin comparar píxeles.

Usa Playwright/Chromium REAL (ya es dependencia del repo, igual que compose).
"""
from __future__ import annotations

from dataclasses import dataclass

from src import compose
from src import slideshow_compile as sc


@dataclass
class _Img:
    ruta_o_url: str
    source: str = "manual"


def _guion():
    return {"tema": "café", "hook": "5 secretos del café", "caption": "pie",
            "cta": "Sígueme para más",
            "slides": [
                {"text": "5 secretos del café que nadie te cuenta",
                 "rol": "hook", "image_hint": "a"},
                {"text": "El agua importa más que el grano", "rol": "punto",
                 "image_hint": "b"},
                {"text": "Sígueme para más", "rol": "cta", "image_hint": "c"},
            ]}


def test_render_slide_con_fondo_solido(tmp_path) -> None:
    """Sin imagen (fallback sólido): debe producir un PNG no trivial."""
    show = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    ctx = sc.contexto_slide(show, 0)
    png = compose.render_card("slide.html", ctx, out_path=tmp_path / "s0.png")
    assert png.exists() and png.stat().st_size > 10_000


def test_render_slide_cta_estilo_editorial(tmp_path) -> None:
    show = sc.compilar(_guion(), estilo="editorial", imagenes=[None] * 3)
    ctx = sc.contexto_slide(show, 2)
    png = compose.render_card("slide.html", ctx, out_path=tmp_path / "s2.png")
    assert png.exists() and png.stat().st_size > 10_000


def test_render_slide_con_chrome(tmp_path) -> None:
    """El pie de marca (handle) rinde sin romper el auto-fit."""
    estilos = {"pensionmas": {"texto": "blanco", "fondo": "navy",
                              "background_opacity": 0.3,
                              "chrome": {"handle": "@pensionmas", "logo": None},
                              "roles": {"hook": {"font": "Erode-Bold",
                                                 "font_size": "extra_large",
                                                 "text_style": "background",
                                                 "text_vertical_anchor": "center"},
                                        "punto": {"font": "Erode-Semibold",
                                                  "font_size": "large",
                                                  "text_style": "background",
                                                  "text_vertical_anchor": "center"},
                                        "cta": {"font": "Poppins-SemiBold",
                                                "font_size": "medium",
                                                "text_style": "background",
                                                "text_vertical_anchor": "bottom"}}}}
    show = sc.compilar(_guion(), estilo="pensionmas", imagenes=[None] * 3,
                       estilos=estilos)
    png = compose.render_card("slide.html", sc.contexto_slide(show, 0),
                              out_path=tmp_path / "chrome.png")
    assert png.exists() and png.stat().st_size > 10_000
