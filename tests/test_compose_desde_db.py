"""Render de HTML que viene de la DB, con dimensiones por aspecto."""
from __future__ import annotations

import pytest
from PIL import Image

from src import compose

_HTML = """<!doctype html><html><head><style>
  .card {{ width: {w}px; height: {h}px; background:#111; color:#fff;
           display:flex; align-items:center; justify-content:center;
           font-size:80px; font-family:sans-serif; }}
</style></head><body><div class="card">HOLA</div>
<script>window.__captionFitted = true;</script></body></html>"""


def _html(aspecto: str) -> str:
    w, h = compose.ASPECTOS[aspecto]
    return _HTML.format(w=w, h=h)


def test_aspectos_declarados() -> None:
    assert compose.ASPECTOS["4:5"] == (1080, 1350)
    assert compose.ASPECTOS["9:16"] == (1080, 1920)


@pytest.mark.parametrize("aspecto", ["4:5", "9:16"])
def test_render_html_produce_png_del_tamano_pedido(aspecto, tmp_path) -> None:
    out = tmp_path / f"p_{aspecto.replace(':', 'x')}.png"
    png = compose.render_html(_html(aspecto), aspecto=aspecto, out_path=out)
    assert png.exists() and png.stat().st_size > 10_000
    assert Image.open(png).size == compose.ASPECTOS[aspecto]


def test_render_html_rechaza_aspecto_desconocido(tmp_path) -> None:
    with pytest.raises(ValueError, match="aspecto"):
        compose.render_html(_html("4:5"), aspecto="16:9",
                            out_path=tmp_path / "x.png")


def test_compose_clasico_sigue_intacto(tmp_path) -> None:
    """El camino viejo no cambia de tamaño ni de firma."""
    png = compose.compose(caption="Prueba de regresión",
                          foto_url=None, template="clasica",
                          out_path=tmp_path / "viejo.png")
    assert Image.open(png).size == (compose.WIDTH, compose.HEIGHT)
