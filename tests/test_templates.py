"""Tests de variedad de plantillas: pesos + ciclo del botón de Telegram."""
from __future__ import annotations

from collections import Counter

from src.compose import MEME_TEMPLATES, random_template, siguiente_template


def test_random_template_respeta_pesos() -> None:
    c = Counter(random_template() for _ in range(3000))
    # la clásica domina (~70%); verde/onion aparecen pero con moderación
    assert c["clasica"] > c["verde"] and c["clasica"] > c["onion"]
    assert c["clasica"] / 3000 > 0.55          # mayoría clara
    assert c["verde"] > 0 and c["onion"] > 0   # pero las otras SÍ se usan
    assert set(c) <= set(MEME_TEMPLATES)       # nunca elige 'anuncio'


def test_siguiente_template_cicla() -> None:
    assert siguiente_template("clasica") == "verde"
    assert siguiente_template("verde") == "onion"
    assert siguiente_template("onion") == "clasica"
    # plantilla desconocida → vuelve a la primera
    assert siguiente_template("anuncio") == "clasica"
    assert siguiente_template("xyz") == "clasica"
