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
