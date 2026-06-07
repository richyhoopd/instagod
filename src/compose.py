"""Composición de la imagen-meme: HTML/CSS → PNG con Playwright (Chromium headless).

Carga `templates/meme.html`, inyecta variables con Jinja2 y renderiza a
1080×1350 px (formato vertical 4:5 de Instagram). Devuelve la ruta del PNG.
"""
from __future__ import annotations

import html as html_mod
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

import config

TEMPLATES_DIR = config.BASE_DIR / "templates"
FONTS_DIR = TEMPLATES_DIR / "assets" / "fonts"
OUT_DIR = config.BASE_DIR / "out"

WIDTH, HEIGHT = 1080, 1350
DEFAULT_HANDLE = "@gdlscene"

# Plantillas disponibles → archivo HTML. La key es la que se elige desde el bot.
TEMPLATES = {
    "clasica": "meme.html",      # foto arriba, titular serif negro sobre blanco
    "verde": "meme_verde.html",  # invertida: fondo verde, texto blanco
    "onion": "meme_onion.html",  # foto completa oscurecida, titular condensado abajo
    "anuncio": "anuncio.html",   # flyer completo + línea informativa (Fase 5; dato fiel)
}

# Plantillas de MEME y sus pesos: la clásica domina, verde/onion con moderación.
MEME_TEMPLATES = ["clasica", "verde", "onion"]
_TEMPLATE_WEIGHTS = [70, 15, 15]


def random_template() -> str:
    """Elige plantilla de meme con pesos (mayormente clásica, verde/onion ocasional)."""
    import random
    return random.choices(MEME_TEMPLATES, weights=_TEMPLATE_WEIGHTS, k=1)[0]


def siguiente_template(actual: str) -> str:
    """Cicla a la siguiente plantilla de meme (clasica→verde→onion→clasica)."""
    try:
        i = MEME_TEMPLATES.index(actual)
    except ValueError:
        return MEME_TEMPLATES[0]
    return MEME_TEMPLATES[(i + 1) % len(MEME_TEMPLATES)]

# Palabras función que NO se colorean en la plantilla onion (el resto va en verde).
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del", "al", "a",
    "y", "o", "u", "e", "que", "en", "con", "por", "para", "su", "sus", "se", "lo",
    "le", "les", "es", "son", "fue", "ha", "han", "como", "más", "pero", "tras",
}

_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
)


def _current_year() -> int:
    return datetime.now(pytz.timezone(config.TIMEZONE)).year


def _default_badge() -> str:
    return f"Our Annual Year {_current_year()}"


def _to_src(value: str | None) -> str:
    """URL remota → tal cual; ruta local → file:// URI (para Playwright)."""
    if not value:
        return ""
    if value.startswith(("http://", "https://", "data:", "file://")):
        return value
    return Path(value).resolve().as_uri()


def _onion_html(caption: str) -> str:
    """Envuelve cada palabra de contenido en <span class='hl'> (verde); las de función en blanco."""
    out = []
    for word in caption.split():
        core = word.strip(".,;:¡!¿?\"'()—–-").lower()
        cls = "" if core in _STOPWORDS else "hl"
        safe = html_mod.escape(word)
        out.append(f'<span class="{cls}">{safe}</span>' if cls else f"<span>{safe}</span>")
    return " ".join(out)


def _render_html(
    caption: str,
    foto_url: str,
    foto_inset_url: str | None,
    badge_text: str,
    handle: str,
    template: str,
) -> str:
    tpl = _env.get_template(TEMPLATES[template])
    return tpl.render(
        fonts_dir=FONTS_DIR.as_uri(),
        foto_url=_to_src(foto_url),
        foto_inset_url=_to_src(foto_inset_url),
        caption=caption,
        caption_html=_onion_html(caption),
        badge_text=badge_text,
        tag_text=handle.lstrip("@").upper(),
        handle=handle,
    )


def compose(
    caption: str,
    foto_url: str,
    foto_inset_url: str | None = None,
    *,
    template: str = "clasica",
    badge_text: str | None = None,
    handle: str = DEFAULT_HANDLE,
    out_path: str | Path | None = None,
    row_id: Any = None,
) -> Path:
    """Renderiza el meme y devuelve la ruta del PNG generado.

    template: "clasica" | "verde" | "onion".
    """
    if template not in TEMPLATES:
        raise ValueError(f"Plantilla desconocida: {template}. Opciones: {list(TEMPLATES)}")
    html = _render_html(
        caption, foto_url, foto_inset_url, badge_text or _default_badge(), handle, template
    )

    return _screenshot_card(html, out_path=out_path, row_id=row_id)


def _screenshot_card(html: str, *, out_path: str | Path | None = None,
                     row_id: Any = None, prefix: str = "meme") -> Path:
    """HTML (con un nodo .card) → PNG vía Chromium headless. Motor compartido."""
    if out_path is None:
        OUT_DIR.mkdir(exist_ok=True)
        suffix = f"_{row_id}" if row_id is not None else ""
        fd, tmp = tempfile.mkstemp(prefix=f"{prefix}{suffix}_", suffix=".png", dir=str(OUT_DIR))
        Path(tmp).unlink(missing_ok=True)  # solo queremos el nombre único
        out_path = tmp
    out_path = Path(out_path)

    # La HTML se escribe a un archivo real y se carga con goto(file://): así el
    # documento tiene origen file:// y Chromium SÍ carga recursos file:// (foto
    # local + fuentes). Con set_content el origen es nulo y los bloquea.
    OUT_DIR.mkdir(exist_ok=True)
    fd, html_tmp = tempfile.mkstemp(prefix=".render_", suffix=".html", dir=str(OUT_DIR))
    Path(html_tmp).write_text(html, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
            page.goto(Path(html_tmp).as_uri(), wait_until="networkidle")
            # Espera a que el script de auto-ajuste del titular termine.
            try:
                page.wait_for_function("window.__captionFitted === true", timeout=5000)
            except Exception:
                pass  # si falla el fit, igual renderiza con el tamaño base
            card = page.locator(".card")
            card.screenshot(path=str(out_path))
            browser.close()
    finally:
        Path(html_tmp).unlink(missing_ok=True)

    return out_path


def render_card(template_file: str, ctx: dict[str, Any], *,
                out_path: str | Path | None = None, row_id: Any = None,
                prefix: str = "card") -> Path:
    """Renderiza CUALQUIER plantilla de templates/ a PNG con el motor del meme.

    Para formatos con estructura propia (p. ej. la agenda de eventos), donde
    las variables fijas de `compose()` no alcanzan. `fonts_dir` va siempre.
    """
    tpl = _env.get_template(template_file)
    html = tpl.render(fonts_dir=FONTS_DIR.as_uri(), **ctx)
    return _screenshot_card(html, out_path=out_path, row_id=row_id, prefix=prefix)


if __name__ == "__main__":
    # Prueba aislada con datos dummy: python -m src.compose
    demo = compose(
        caption="El guitarrista de Noisy Room, Carlos Virgen, asegura que preferiría "
        "fumar crack antes que ver Stranger Things.",
        foto_url="https://images.unsplash.com/photo-1511671782779-c97d3d27a1d4?w=1080&q=80",
        foto_inset_url="https://images.unsplash.com/photo-1514228742587-6b1558fcca3d?w=400&q=80",
    )
    print(f"PNG generado en: {demo}")
