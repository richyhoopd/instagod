"""Composición de la imagen-meme: HTML/CSS → PNG con Playwright (Chromium headless).

Carga `templates/meme.html`, inyecta variables con Jinja2 y renderiza a
1080×1350 px (formato vertical 4:5 de Instagram). Devuelve la ruta del PNG.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

import config

TEMPLATES_DIR = config.BASE_DIR / "templates"
FONTS_DIR = TEMPLATES_DIR / "assets" / "fonts"
OUT_DIR = config.BASE_DIR / "out"

WIDTH, HEIGHT = 1080, 1350
DEFAULT_BADGE = "Our Annual Year 2025"
DEFAULT_HANDLE = "@gdlscene"

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _render_html(
    caption: str,
    foto_url: str,
    foto_inset_url: str | None,
    badge_text: str,
    handle: str,
) -> str:
    template = _env.get_template("meme.html")
    return template.render(
        fonts_dir=FONTS_DIR.as_uri(),
        foto_url=foto_url,
        foto_inset_url=foto_inset_url or "",
        caption=caption,
        badge_text=badge_text,
        handle=handle,
    )


def compose(
    caption: str,
    foto_url: str,
    foto_inset_url: str | None = None,
    *,
    badge_text: str = DEFAULT_BADGE,
    handle: str = DEFAULT_HANDLE,
    out_path: str | Path | None = None,
    row_id: Any = None,
) -> Path:
    """Renderiza el meme y devuelve la ruta del PNG generado."""
    html = _render_html(caption, foto_url, foto_inset_url, badge_text, handle)

    if out_path is None:
        OUT_DIR.mkdir(exist_ok=True)
        suffix = f"_{row_id}" if row_id is not None else ""
        fd, tmp = tempfile.mkstemp(prefix=f"meme{suffix}_", suffix=".png", dir=str(OUT_DIR))
        Path(tmp).unlink(missing_ok=True)  # solo queremos el nombre único
        out_path = tmp
    out_path = Path(out_path)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        page.set_content(html, wait_until="networkidle")
        # Espera a que el script de auto-ajuste del titular termine.
        try:
            page.wait_for_function("window.__captionFitted === true", timeout=5000)
        except Exception:
            pass  # si falla el fit, igual renderiza con el tamaño base
        card = page.locator(".card")
        card.screenshot(path=str(out_path))
        browser.close()

    return out_path


if __name__ == "__main__":
    # Prueba aislada con datos dummy: python -m src.compose
    demo = compose(
        caption="El guitarrista de Noisy Room, Carlos Virgen, asegura que preferiría "
        "fumar crack antes que ver Stranger Things.",
        foto_url="https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=1080&q=80",
        foto_inset_url="https://images.unsplash.com/photo-1514228742587-6b1558fcca3d?w=400&q=80",
    )
    print(f"PNG generado en: {demo}")
