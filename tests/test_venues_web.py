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


def _evento(cx, lugar, venue_id=None):
    n = len(db.rows(cx, "SELECT id FROM bands"))
    bid = db.insert(cx, "bands", nombre=f"B{n}", ig_handle=f"b{n}")
    return db.insert(cx, "events", band_id=bid, tipo="flyer",
                     fecha_evento="2026-08-23", lugar=lugar, venue_id=venue_id)


def test_asignar_reapunta_los_eventos_de_ese_lugar(cliente) -> None:
    """Curar en la GUI cambia la agenda YA, sin pasar por --solo-backfill."""
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    eid = _evento(cx, "REY")
    otro = _evento(cx, "Staditche")
    aid = venues.registrar_desconocido(cx, "REY")
    r = cli.post(f"/venues/alias/{aid}/asignar", data={"venue_id": str(vid)})
    assert r.status_code == 200
    assert db.get(cx, "events", eid)["venue_id"] == vid
    assert db.get(cx, "events", otro)["venue_id"] is None
    assert db.get(cx, "events", eid)["lugar"] == "REY"      # el texto NO se toca


def test_crear_foro_reapunta_los_eventos_de_ese_lugar(cliente) -> None:
    cli, cx = cliente
    eid = _evento(cx, "Foro Nuevo")
    aid = venues.registrar_desconocido(cx, "Foro Nuevo")
    cli.post("/venues/nuevo", data={"nombre": "Foro Nuevo", "alias_id": str(aid)})
    assert db.get(cx, "events", eid)["venue_id"] == venues.resolver(cx, "Foro Nuevo")


def test_no_es_lugar_suelta_los_eventos_que_lo_usaban(cliente) -> None:
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    aid = venues.asignar_alias(cx, vid, "siamesasperdidas")
    eid = _evento(cx, "siamesasperdidas", venue_id=vid)
    cli.post(f"/venues/alias/{aid}/no-es-lugar")
    assert db.get(cx, "events", eid)["venue_id"] is None


def _guardar(cli, eid, **campos):
    datos = {"tipo": "fecha", "fecha_evento": "2026-08-23", "lugar": "",
             "ciudad": "", "status": "nuevo", **campos}
    return cli.post(f"/eventos/{eid}", data=datos)


def test_editar_el_lugar_a_mano_re_resuelve_el_venue_id(cliente) -> None:
    """Tercer camino que escribe events.lugar: no puede dejar el venue viejo."""
    cli, cx = cliente
    rey = db.insert(cx, "venues", nombre="Hake Al Rey")
    stad = db.insert(cx, "venues", nombre="Staditche")
    venues.asignar_alias(cx, rey, "Hake Al Rey")
    venues.asignar_alias(cx, stad, "Staditche")
    eid = _evento(cx, "Hake Al Rey", venue_id=rey)
    r = _guardar(cli, eid, lugar="Staditche")
    assert r.status_code == 200
    assert db.get(cx, "events", eid)["venue_id"] == stad


def test_editar_a_un_lugar_desconocido_deja_venue_id_en_null(cliente) -> None:
    cli, cx = cliente
    rey = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, rey, "Hake Al Rey")
    eid = _evento(cx, "Hake Al Rey", venue_id=rey)
    _guardar(cli, eid, lugar="Foro Jamás Visto")
    assert db.get(cx, "events", eid)["venue_id"] is None
    assert [h["alias_visto"] for h in venues.huerfanos(cx)] == ["Foro Jamás Visto"]


def test_borrar_el_lugar_a_mano_suelta_el_venue_id(cliente) -> None:
    cli, cx = cliente
    rey = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, rey, "Hake Al Rey")
    eid = _evento(cx, "Hake Al Rey", venue_id=rey)
    _guardar(cli, eid, lugar="")
    assert db.get(cx, "events", eid)["venue_id"] is None


def test_guardar_sin_cambiar_el_lugar_conserva_el_venue_id(cliente) -> None:
    """Editar la fecha no debe recalcular nada del foro."""
    cli, cx = cliente
    rey = db.insert(cx, "venues", nombre="Hake Al Rey")
    eid = _evento(cx, "Hake Al Rey", venue_id=rey)   # sin alias: no resolvería
    _guardar(cli, eid, lugar="Hake Al Rey", fecha_evento="2026-09-01")
    assert db.get(cx, "events", eid)["venue_id"] == rey


def test_asignar_a_foro_inexistente_falla(cliente) -> None:
    cli, cx = cliente
    aid = venues.registrar_desconocido(cx, "Foro X")
    r = cli.post(f"/venues/alias/{aid}/asignar", data={"venue_id": "9999"})
    assert r.status_code == 404
    assert len(venues.huerfanos(cx)) == 1
