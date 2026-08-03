from __future__ import annotations

from pathlib import Path

import pytest

from src import db, venues


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_migracion_crea_venues_y_alias(cx) -> None:
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"venues", "venue_alias"} <= tablas
    assert "venue_id" in {r["name"] for r in cx.execute("PRAGMA table_info(events)")}
    assert "venues" in db.TABLES and "venue_alias" in db.TABLES
    assert "venue_id" in db.TABLES["events"]


def test_alias_norm_es_unico(cx) -> None:
    import sqlite3
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    db.insert(cx, "venue_alias", venue_id=vid, alias_norm="hake al rey",
              alias_visto="Hake al Rey", origen="semilla")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "venue_alias", venue_id=vid, alias_norm="hake al rey",
                  alias_visto="HAKE AL REY", origen="llm")


def test_migracion_es_idempotente(cx) -> None:
    db.init_db(cx)
    db.init_db(cx)
    vid = db.insert(cx, "venues", nombre="Cuerda", ciudad="Guadalajara")
    assert db.get(cx, "venues", vid)["nombre"] == "Cuerda"


@pytest.mark.parametrize("crudo,esperado", [
    # Los casos REALES de la DB de producción (3-ago-2026).
    ("Staditche", "staditche"),
    ("staditche", "staditche"),
    ("@staditche", "staditche"),
    ("Staditche (Espacio Cultural)", "staditche"),
    ("Staditche (Centro Cultural)", "staditche"),
    ("HAKE AL REY", "hake al rey"),
    ("Hake al Rey", "hake al rey"),
    ("Anexo Independencia", "anexo independencia"),
    ("Foro Anexo Independencia", "anexo independencia"),
    # Prefijo genérico
    ("Centro Cultural Calzada", "calzada"),
    ("El Foro Diez", "diez"),
    # Sufijo genérico
    ("Hake Al Rey - Concert Room", "hake al rey"),
    # Acentos y puntuación
    ("Foro Lázaro", "lazaro"),
    ("C3 Stage & C3 Rooftop", "c3 stage c3 rooftop"),
    # Vacíos
    (None, ""),
    ("", ""),
    ("   ", ""),
])
def test_normalizar(crudo, esperado) -> None:
    assert venues.normalizar(crudo) == esperado


def test_normalizar_quita_un_prefijo_y_un_sufijo_como_maximo() -> None:
    """'foro sala X' pierde solo 'foro'; el segundo genérico se conserva."""
    assert venues.normalizar("Foro Sala Diana") == "sala diana"


def test_normalizar_no_deja_cadena_vacia_si_solo_hay_generico() -> None:
    """Un lugar que es SOLO una palabra genérica conserva su texto: quitarla
    dejaría "" y "" es la clave de 'no hay lugar', que significa otra cosa."""
    assert venues.normalizar("Foro") == "foro"


def test_sugerencias_ordena_por_parecido() -> None:
    candidatos = [(1, "Hake Al Rey"), (2, "Staditche"), (3, "Cuerda")]
    out = venues.sugerencias("hake al rey concert", candidatos)
    assert out[0][0] == 1
    assert out[0][2] > out[-1][2]


def test_sugerencias_respeta_el_tope() -> None:
    candidatos = [(i, f"Foro {i}") for i in range(10)]
    assert len(venues.sugerencias("foro 3", candidatos, tope=2)) == 2


def test_sugerencias_sin_candidatos() -> None:
    assert venues.sugerencias("lo que sea", []) == []
