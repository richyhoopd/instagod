"""Helpers puros de composición del meme (sin Playwright/Chromium).

Lo visual (screenshot) necesita navegador y no se prueba aquí; sí se blindan las
funciones puras que deciden plantilla, resuelven rutas de imagen y resaltan el
titular (estilo onion), porque alimentan directamente lo que se renderiza.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import compose
from src.compose import (
    MEME_TEMPLATES,
    _onion_html,
    _to_src,
    random_template,
    siguiente_template,
)

# ---------- siguiente_template: ciclo determinista ----------

def test_siguiente_template_cicla() -> None:
    assert siguiente_template("clasica") == "verde"
    assert siguiente_template("verde") == "onion"
    assert siguiente_template("onion") == "clasica"   # vuelve al inicio


def test_siguiente_template_desconocida_cae_a_primera() -> None:
    assert siguiente_template("inexistente") == MEME_TEMPLATES[0]


# ---------- random_template: siempre una plantilla válida ----------

def test_random_template_siempre_valida() -> None:
    for _ in range(50):
        assert random_template() in MEME_TEMPLATES


# ---------- _to_src: URL remota vs ruta local ----------

def test_to_src_vacio() -> None:
    assert _to_src(None) == ""
    assert _to_src("") == ""


@pytest.mark.parametrize("url", [
    "https://cdn.example.com/a.jpg",
    "http://x/y.png",
    "data:image/png;base64,AAAA",
    "file:///ya/es/uri.png",
])
def test_to_src_remota_se_respeta(url) -> None:
    assert _to_src(url) == url


def test_to_src_ruta_local_a_file_uri() -> None:
    src = _to_src("fotos/banda.jpg")
    assert src.startswith("file://")
    assert src.endswith("banda.jpg")
    assert Path("fotos/banda.jpg").resolve().as_uri() == src   # absoluta + file://


# ---------- _onion_html: resalta contenido, deja stopwords planas, escapa HTML ----------

def test_onion_html_resalta_contenido_y_no_stopwords() -> None:
    out = _onion_html("El guitarrista de Kabala")
    # "guitarrista" y "Kabala" son contenido → clase hl; "el"/"de" son stopwords.
    assert '<span class="hl">guitarrista</span>' in out
    assert '<span class="hl">Kabala</span>' in out
    assert "<span>El</span>" in out and "<span>de</span>" in out


def test_onion_html_escapa_caracteres_html() -> None:
    out = _onion_html("Bandas & ruido <test>")
    assert "&amp;" in out
    assert "&lt;test&gt;" in out
    assert "<test>" not in out           # nunca HTML crudo del caption


def test_onion_html_stopword_con_puntuacion_sigue_siendo_stopword() -> None:
    # "de," (con coma) debe limpiarse y reconocerse como stopword (sin hl).
    out = _onion_html("Kabala, de, Guadalajara")
    assert "<span>de,</span>" in out


# ---------- compose(): valida la plantilla antes de tocar el navegador ----------

def test_compose_plantilla_desconocida_revienta() -> None:
    with pytest.raises(ValueError):
        compose.compose("titular", "foto.jpg", template="no_existe")
