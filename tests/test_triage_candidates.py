"""Triage de candidatas: clasificar() decide qué cuenta se activa/borra/queda dudosa.

Función PURA (categoría IG + bio → tipo de actor) sin red ni DB. Es la compuerta
que define qué cuentas entran al sistema, así que cada rama importa.
"""
from __future__ import annotations

import pytest

from src.triage_candidates import clasificar

# ---------- Activar por categoría IG (primer match gana, orden importa) ----------

@pytest.mark.parametrize("categoria,tipo", [
    ("Musician/Band", "banda"),
    ("Artist", "banda"),
    ("Rapper", "banda"),
    ("Record Label", "colectivo"),
    ("Music Production", "colectivo"),
    ("Bar", "foro"),
    ("Live Music Venue", "foro"),
    ("Cultural Center", "foro"),
    ("Art Gallery", "foro"),          # "art" cae en el grupo foro
    ("Event Planner", "evento"),
    ("Festival", "evento"),
    ("Magazine", "colectivo"),
    ("Community", "colectivo"),
])
def test_categoria_activa_con_tipo(categoria, tipo) -> None:
    t, decision, motivo = clasificar(categoria, bio=None)
    assert decision == "activar"
    assert t == tipo
    assert categoria in motivo


def test_record_label_gana_sobre_producer_antes_que_musician() -> None:
    # "music production" debe resolver a colectivo, NO a banda (orden de _CAT_A_TIPO).
    t, decision, _ = clasificar("Music Production House", bio="banda de rock")
    assert (t, decision) == ("colectivo", "activar")


# ---------- Borrar: no es un actor de la escena ----------

@pytest.mark.parametrize("categoria,etiqueta", [
    ("Photographer", "fotografía"),
    ("Photography", "fotografía"),
    ("Clothing (Brand)", "tienda"),
    ("Shopping & Retail", "tienda"),
    ("Restaurant", "restaurante"),
    ("Product/Service", "marca"),
    ("Digital Creator", "creador"),
    ("Writer", "persona"),
])
def test_categoria_recomienda_borrar(categoria, etiqueta) -> None:
    t, decision, motivo = clasificar(categoria, bio="lo que sea")
    assert decision == "borrar"
    assert t is None
    assert etiqueta in motivo


@pytest.mark.parametrize("categoria,decision_esperada", [
    ("Public Figure", "borrar"),    # antes activaba foro por "pub" en "PUBlic"
    ("Bartender", "dudosa"),        # antes activaba foro por "bar" en "BARtender"
    ("Personal Blog", "borrar"),    # antes activaba colectivo por "blog"
])
def test_no_activa_por_substring_goloso(categoria, decision_esperada) -> None:
    """REGRESIÓN del bug de substring: el match es por PALABRA completa y _CAT_BORRAR
    se evalúa antes, así que estas cuentas ya NO se activan por error (pub/bar/blog).
    """
    _, decision, _ = clasificar(categoria, bio=None)
    assert decision == decision_esperada
    assert decision != "activar"


def test_match_por_palabra_no_rompe_categorias_compuestas() -> None:
    # Las claves multipalabra y de una palabra siguen activando lo correcto.
    assert clasificar("Live Music Venue", None)[:2] == ("foro", "activar")
    assert clasificar("Nightclub", None)[:2] == ("foro", "activar")
    assert clasificar("Record Label", None)[:2] == ("colectivo", "activar")


# ---------- Sin categoría útil: heurística de bio (queda dudosa) ----------

def test_bio_foro_queda_dudosa() -> None:
    t, decision, _ = clasificar(None, bio="Espacio cultural y sala de ensayo en el centro")
    assert (t, decision) == ("foro", "dudosa")


def test_bio_solista_queda_dudosa() -> None:
    t, decision, _ = clasificar(None, bio="Cantautor tapatío, beatmaker independiente")
    assert (t, decision) == ("solista", "dudosa")


def test_bio_colectivo_queda_dudosa() -> None:
    t, decision, _ = clasificar(None, bio="Sello y promotora de gestión cultural")
    assert (t, decision) == ("colectivo", "dudosa")


def test_bio_musical_sin_pista_explicita_cae_a_banda_dudosa() -> None:
    # No dice "banda" pero suena musical (single/spotify/rock) → banda tentativa.
    t, decision, motivo = clasificar(None, bio="Nuevo single ya disponible en Spotify, puro rock")
    assert (t, decision) == ("banda", "dudosa")
    assert "musical" in motivo


# ---------- Fallbacks ----------

def test_categoria_irreconocible_sin_bio_queda_dudosa_con_categoria() -> None:
    t, decision, motivo = clasificar("Tattoo Studio", bio=None)
    # No matchea activar ni borrar ni bio → dudosa, conserva la categoría como pista.
    assert (t, decision) == (None, "dudosa")
    assert "Tattoo" in motivo


def test_sin_categoria_ni_bio_queda_dudosa() -> None:
    t, decision, motivo = clasificar(None, bio=None)
    assert (t, decision) == (None, "dudosa")
    assert "sin categoría" in motivo


def test_vacios_se_tratan_como_ausentes() -> None:
    assert clasificar("", "") == (None, "dudosa", "sin categoría ni pistas en bio")
