from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db, venues


@pytest.fixture()
def cliente(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import importlib

    import config
    importlib.reload(config)
    from web import app as app_mod
    importlib.reload(app_mod)
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield TestClient(app_mod.app), conn
    conn.close()


def test_vista_lista_foros_y_huerfanos(cliente) -> None:
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, vid, "Hake al Rey")
    venues.registrar_desconocido(cx, "REY")
    r = cli.get("/venues")
    assert r.status_code == 200
    assert "Hake Al Rey" in r.text
    assert "REY" in r.text


def test_asignar_alias_lo_saca_de_la_cola(cliente) -> None:
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    aid = venues.registrar_desconocido(cx, "REY")
    r = cli.post(f"/venues/alias/{aid}/asignar", data={"venue_id": str(vid)})
    assert r.status_code in (200, 204, 303)
    assert venues.resolver(cx, "REY") == vid
    assert venues.huerfanos(cx) == []


def test_no_es_lugar_saca_la_basura(cliente) -> None:
    cli, cx = cliente
    aid = venues.registrar_desconocido(cx, "siamesasperdidas")
    r = cli.post(f"/venues/alias/{aid}/no-es-lugar")
    assert r.status_code in (200, 204, 303)
    assert venues.huerfanos(cx) == []


def test_crear_foro_desde_un_huerfano(cliente) -> None:
    cli, cx = cliente
    aid = venues.registrar_desconocido(cx, "Foro Nuevo")
    r = cli.post("/venues/nuevo", data={"nombre": "Foro Nuevo", "alias_id": str(aid)})
    assert r.status_code in (200, 204, 303)
    assert venues.resolver(cx, "Foro Nuevo") is not None
    assert venues.huerfanos(cx) == []


def test_fusionar_dos_foros(cliente) -> None:
    cli, cx = cliente
    dst = db.insert(cx, "venues", nombre="Hake Al Rey")
    src = db.insert(cx, "venues", nombre="Hakealrey")
    venues.asignar_alias(cx, src, "Hakealrey")
    r = cli.post(f"/venues/{dst}/fusionar", data={"otro_id": str(src)})
    assert r.status_code in (200, 204, 303)
    assert db.get(cx, "venues", src) is None
    assert venues.resolver(cx, "Hakealrey") == dst


def test_fusionar_consigo_mismo_falla(cliente) -> None:
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Cuerda")
    r = cli.post(f"/venues/{vid}/fusionar", data={"otro_id": str(vid)})
    assert r.status_code == 400
    assert db.get(cx, "venues", vid) is not None


def test_asignar_a_foro_inexistente_falla(cliente) -> None:
    cli, cx = cliente
    aid = venues.registrar_desconocido(cx, "Foro X")
    r = cli.post(f"/venues/alias/{aid}/asignar", data={"venue_id": "9999"})
    assert r.status_code == 404
    assert len(venues.huerfanos(cx)) == 1
