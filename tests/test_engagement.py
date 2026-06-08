"""Cerebro de engagement: scoring puro de banda y formato + cold-start."""
from __future__ import annotations

from src import engagement


def test_score_formatos_cold_start_usa_reglas() -> None:
    # Sin datos suficientes → pesos de Ricardo (absurdo_domestico manda).
    pesos = engagement.score_formatos([], min_posts=2)
    assert pesos["absurdo_domestico"] > pesos["comunicado"]


def test_score_formatos_aprende_de_datos() -> None:
    # absurdo_domestico con reach/shares altos sube por encima de su peso base.
    posts = [
        {"patron": "absurdo_domestico", "reach": 1368, "shares": 30, "saved": 5},
        {"patron": "absurdo_domestico", "reach": 1140, "shares": 10, "saved": 2},
        {"patron": "comunicado", "reach": 200, "shares": 0, "saved": 0},
        {"patron": "comunicado", "reach": 180, "shares": 1, "saved": 0},
    ]
    pesos = engagement.score_formatos(posts, min_posts=2)
    assert pesos["absurdo_domestico"] > pesos["comunicado"] * 2


def test_score_bandas_anti_repeticion() -> None:
    # Misma señal base, pero una publicó ayer → debe quedar debajo.
    bandas = [
        {"band_id": 1, "er": 0.1, "shares": 5, "prioridad": 3, "followers_ig": 1000,
         "n_posts": 3, "dias_desde_ultimo": 1},
        {"band_id": 2, "er": 0.1, "shares": 5, "prioridad": 3, "followers_ig": 1000,
         "n_posts": 3, "dias_desde_ultimo": 60},
    ]
    orden = [b["band_id"] for b in engagement.score_bandas(bandas, min_posts=2)]
    assert orden == [2, 1]


def test_score_bandas_cold_start_por_followers() -> None:
    bandas = [
        {"band_id": 1, "er": None, "shares": 0, "prioridad": 3, "followers_ig": 500,
         "n_posts": 0, "dias_desde_ultimo": None},
        {"band_id": 2, "er": None, "shares": 0, "prioridad": 3, "followers_ig": 5000,
         "n_posts": 0, "dias_desde_ultimo": None},
    ]
    orden = [b["band_id"] for b in engagement.score_bandas(bandas, min_posts=2)]
    assert orden == [2, 1]  # sin datos → más followers primero
