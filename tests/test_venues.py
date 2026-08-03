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


def test_normalizar_articulo_mas_generico_se_conserva() -> None:
    """Un artículo + genérico no debe colapsar a solo el artículo.
    Dos lugares 'El Bar' y 'El Salon' no deben fusionarse."""
    assert venues.normalizar("El Foro") == "el foro"
    assert venues.normalizar("El Bar") == "el bar"
    assert venues.normalizar("El Salon") == "el salon"
    assert venues.normalizar("El Pub") == "el pub"


def _venue(cx, nombre, *alias):
    vid = db.insert(cx, "venues", nombre=nombre)
    for a in alias:
        db.insert(cx, "venue_alias", venue_id=vid, alias_norm=venues.normalizar(a),
                  alias_visto=a, origen="semilla")
    return vid


def test_resolver_alias_conocido(cx) -> None:
    vid = _venue(cx, "Hake Al Rey", "Hake al Rey", "REY")
    assert venues.resolver(cx, "HAKE AL REY") == vid
    assert venues.resolver(cx, "@rey") == vid          # normaliza antes de buscar
    assert venues.resolver(cx, "Rey ") == vid


def test_resolver_desconocido_devuelve_none_y_no_escribe(cx) -> None:
    _venue(cx, "Cuerda", "Cuerda Cultura")
    assert venues.resolver(cx, "Foro Que No Existe") is None
    assert db.rows(cx, "SELECT * FROM venue_alias WHERE venue_id IS NULL") == []


def test_resolver_vacio(cx) -> None:
    assert venues.resolver(cx, None) is None
    assert venues.resolver(cx, "") is None


def test_registrar_desconocido_deja_huerfano(cx) -> None:
    aid = venues.registrar_desconocido(cx, "Foro Nuevo (sala 2)")
    fila = db.get(cx, "venue_alias", aid)
    assert fila["venue_id"] is None
    assert fila["alias_visto"] == "Foro Nuevo (sala 2)"   # texto CRUDO
    assert fila["alias_norm"] == "nuevo"


def test_registrar_desconocido_marca_origen_visto(cx) -> None:
    aid = venues.registrar_desconocido(cx, "Foro Nuevo")
    assert db.get(cx, "venue_alias", aid)["origen"] == "visto"


def test_registrar_desconocido_es_idempotente(cx) -> None:
    a1 = venues.registrar_desconocido(cx, "Foro Nuevo")
    a2 = venues.registrar_desconocido(cx, "FORO NUEVO")
    assert a1 == a2
    assert len(db.rows(cx, "SELECT * FROM venue_alias")) == 1


def test_registrar_desconocido_ignora_vacio(cx) -> None:
    assert venues.registrar_desconocido(cx, "  ") is None
    assert db.rows(cx, "SELECT * FROM venue_alias") == []


def test_asignar_alias_resuelve_el_huerfano(cx) -> None:
    vid = _venue(cx, "Hake Al Rey", "Hake al Rey")
    venues.registrar_desconocido(cx, "REY")
    venues.asignar_alias(cx, vid, "REY")
    assert venues.resolver(cx, "REY") == vid
    assert db.rows(cx, "SELECT * FROM venue_alias WHERE venue_id IS NULL") == []


def test_asignar_alias_marca_origen_manual(cx) -> None:
    vid = _venue(cx, "Cuerda")
    aid = venues.asignar_alias(cx, vid, "cuerdacultura")
    assert db.get(cx, "venue_alias", aid)["origen"] == "manual"


def test_marcar_no_es_lugar_lo_saca_de_la_cola(cx) -> None:
    aid = venues.registrar_desconocido(cx, "siamesasperdidas")
    venues.marcar_no_es_lugar(cx, aid)
    assert venues.huerfanos(cx) == []
    # Sigue en la tabla, para que no vuelva a entrar a la cola.
    assert db.get(cx, "venue_alias", aid)["origen"] == "no_es_lugar"


def test_registrar_no_revive_lo_marcado_como_basura(cx) -> None:
    aid = venues.registrar_desconocido(cx, "barragan_kun")
    venues.marcar_no_es_lugar(cx, aid)
    venues.registrar_desconocido(cx, "barragan_kun")
    assert venues.huerfanos(cx) == []


def test_fusionar_mueve_alias_y_eventos(cx) -> None:
    dst = _venue(cx, "Hake Al Rey", "Hake al Rey")
    src = _venue(cx, "Hakealrey", "Hakealrey")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    eid = db.insert(cx, "events", band_id=bid, tipo="flyer", venue_id=src)
    venues.fusionar(cx, dst, src)
    assert db.get(cx, "venues", src) is None
    assert db.get(cx, "events", eid)["venue_id"] == dst
    assert venues.resolver(cx, "Hakealrey") == dst


def test_fusionar_consigo_mismo_no_hace_nada(cx) -> None:
    vid = _venue(cx, "Cuerda", "Cuerda")
    venues.fusionar(cx, vid, vid)
    assert db.get(cx, "venues", vid) is not None
    assert venues.resolver(cx, "Cuerda") == vid


def test_huerfanos_lista_solo_los_pendientes(cx) -> None:
    vid = _venue(cx, "Cuerda", "Cuerda")
    venues.registrar_desconocido(cx, "Foro X")
    nombres = [h["alias_visto"] for h in venues.huerfanos(cx)]
    assert nombres == ["Foro X"]
