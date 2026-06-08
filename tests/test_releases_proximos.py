"""Tests de la vista de próximos lanzamientos (releases con fecha futura)."""
from __future__ import annotations

from datetime import datetime

import pytest

from src import db
from src.generate_agenda import releases_proximos


@pytest.fixture()
def cx(tmp_path):
    cx = db.connect(tmp_path / "test.db")
    db.init_db(cx)
    yield cx
    cx.close()


def test_releases_proximos_futuro_si_pasado_no(cx):
    bid = db.insert(cx, "bands", nombre="Duck Fizz")
    hoy = datetime(2026, 6, 9)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="A Ciegas",
              fecha_evento="2026-06-19", source_post_id="a", status="nuevo")   # futuro
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Viejo",
              fecha_evento="2026-05-20", source_post_id="b", status="nuevo")   # pasado
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Lejano",
              fecha_evento="2026-12-01", source_post_id="c", status="nuevo")   # fuera de ventana
    titulos = [e["titulo"] for e in releases_proximos(cx, dias=60, hoy=hoy)]
    assert titulos == ["A Ciegas"]


def test_releases_proximos_excluye_irrelevante(cx):
    bid = db.insert(cx, "bands", nombre="X")
    hoy = datetime(2026, 6, 9)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Irrel",
              fecha_evento="2026-06-15", source_post_id="a", status="nuevo", irrelevante=1)
    assert releases_proximos(cx, dias=60, hoy=hoy) == []
