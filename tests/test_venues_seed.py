from __future__ import annotations

from pathlib import Path

import pytest

from src import db, venues, venues_seed


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _evento(cx, band_id, lugar):
    return db.insert(cx, "events", band_id=band_id, tipo="flyer",
                     fecha_evento="2026-08-23", lugar=lugar)


def test_siembra_desde_bands_usa_los_foros_que_ya_sigue(cx) -> None:
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1, ciudad="Guadalajara")
    db.insert(cx, "bands", nombre="Pool Sessions", ig_handle="poolsessions_",
              tipo="evento", activa=1)
    db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial",
              tipo="banda", activa=1)
    assert venues_seed.sembrar_desde_bands(cx) == 2      # la banda NO entra
    nombres = {v["nombre"] for v in db.rows(cx, "SELECT nombre FROM venues")}
    assert nombres == {"STADITCHE", "Pool Sessions"}
    # El nombre y el handle quedan como alias, así ambos resuelven.
    assert venues.resolver(cx, "@staditche") is not None
    assert venues.resolver(cx, "STADITCHE") is not None


def test_siembra_desde_bands_marca_origen_semilla(cx) -> None:
    """Los alias sembrados desde bands son 'semilla', no 'manual': nadie los
    curó a mano, salieron de una cuenta que Ricardo ya sigue."""
    db.insert(cx, "bands", nombre="Pool Sessions", ig_handle="poolsessions_",
              tipo="evento", activa=1)
    venues_seed.sembrar_desde_bands(cx)
    origenes = {r["origen"] for r in db.rows(cx, "SELECT origen FROM venue_alias")}
    assert origenes == {"semilla"}


def test_siembra_desde_bands_es_idempotente(cx) -> None:
    db.insert(cx, "bands", nombre="Cuerda", ig_handle="cuerdacultura",
              tipo="foro", activa=1)
    venues_seed.sembrar_desde_bands(cx)
    assert venues_seed.sembrar_desde_bands(cx) == 0
    assert len(db.rows(cx, "SELECT * FROM venues")) == 1


def test_agrupar_mecanico_colapsa_las_escrituras_obvias() -> None:
    grupos = venues_seed.agrupar_mecanico([
        "Staditche", "staditche", "@staditche", "Staditche (Espacio Cultural)",
        "Cuerda Cultura",
    ])
    assert set(grupos) == {"staditche", "cuerda cultura"}
    assert len(grupos["staditche"]) == 4


def test_sembrar_resuelve_lo_mecanico_sin_llm(cx) -> None:
    """Lo que la normalización ya colapsa no debe llegar al LLM."""
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1)
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    for l in ("@staditche", "Staditche (Espacio Cultural)", "STADITCHE"):
        _evento(cx, bid, l)
    vistos = {}

    def _llm(pendientes):
        vistos["pendientes"] = list(pendientes)
        return []

    venues_seed.sembrar(cx, _llm=_llm)
    assert vistos["pendientes"] == []     # nada ambiguo que consultar


def test_sembrar_aplica_lo_que_propone_el_llm(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")
    _evento(cx, bid, "Hake al Rey")

    def _llm(pendientes):
        return [{"canonico": "Hake Al Rey", "alias": ["REY", "Hake al Rey"]}]

    res = venues_seed.sembrar(cx, _llm=_llm)
    assert res["venues"] >= 1
    assert venues.resolver(cx, "REY") == venues.resolver(cx, "Hake al Rey")


def test_sembrar_no_pisa_lo_curado(cx) -> None:
    """Un alias asignado a mano sobrevive aunque el LLM proponga otra cosa."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")
    mio = db.insert(cx, "venues", nombre="Mi Foro")
    venues.asignar_alias(cx, mio, "REY")

    def _llm(pendientes):
        return [{"canonico": "Otro Foro", "alias": ["REY"]}]

    venues_seed.sembrar(cx, _llm=_llm)
    assert venues.resolver(cx, "REY") == mio


def test_sembrar_no_pisa_lo_sembrado_desde_bands(cx) -> None:
    """Un alias con origen='semilla' tampoco lo pisa una propuesta del LLM.

    Debe fallar si el chequeo de protección se reduce a solo 'manual'.
    """
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1)

    def _llm(pendientes):
        return [{"canonico": "Otro Foro", "alias": ["staditche"]}]

    venues_seed.sembrar(cx, _llm=_llm)
    foro = db.rows(cx, "SELECT id FROM venues WHERE nombre = 'STADITCHE'")[0]["id"]
    assert venues.resolver(cx, "staditche") == foro


def test_sembrar_deja_huerfano_lo_que_el_llm_no_agrupa(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "GRAL.MANUEL pm COVER M.DIEGUEZ #71")

    res = venues_seed.sembrar(cx, _llm=lambda pendientes: [])
    assert res["huerfanos"] == 1
    assert len(venues.huerfanos(cx)) == 1


def test_sembrar_ignora_eventos_sin_lugar(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, None)
    _evento(cx, bid, "")
    res = venues_seed.sembrar(cx, _llm=lambda pendientes: [])
    assert res["huerfanos"] == 0
