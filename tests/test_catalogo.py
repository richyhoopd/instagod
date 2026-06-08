"""Catálogo: los 4 segmentos vivos registrados con su cadencia/ventana."""
from src.catalogo import REGISTRO


def test_catalogo_tiene_los_cuatro() -> None:
    claves = {s.clave for s in REGISTRO}
    assert {"agenda_semanal", "agenda_mensual",
            "releases_semanal", "releases_mensual"} <= claves


def test_cadencias() -> None:
    por = {s.clave: s for s in REGISTRO}
    assert por["agenda_semanal"].cadencia["tipo"] == "semanal"
    assert por["releases_mensual"].cadencia["tipo"] == "mensual"
    assert por["agenda_semanal"].ventana_trafico == "agenda_semanal"
