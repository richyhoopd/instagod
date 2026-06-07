"""Tests del filtro de eventos incompletos (sin fecha o sin lugar detectados)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)

    ids: dict[str, int] = {}

    # una banda por evento: la fila de la tabla muestra la banda, no el título
    def evento(banda: str, **fields):
        bid = db.insert(cx, "bands", nombre=banda)
        ids[banda] = db.insert(cx, "events", band_id=bid, **fields)

    # completo: NO debe salir en el filtro
    evento("CompletoShow", tipo="fecha", fecha_evento="2026-06-20", lugar="Staditche")
    # sin fecha: SÍ debe salir
    evento("SinFechaFlyer", tipo="flyer", lugar="casa cobra")
    # con fecha pero sin lugar: SÍ debe salir
    evento("SinLugarShow", tipo="fecha", fecha_evento="2026-06-21")
    # release con fecha y sin lugar: NO debe salir (los releases no llevan lugar)
    evento("ReleaseOk", tipo="release", fecha_evento="2026-06-05")
    cx.close()

    from web.app import app
    with TestClient(app) as c:
        c._ids = ids  # type: ignore[attr-defined]
        yield c


def test_eventos_sin_filtro_muestra_todos(client) -> None:
    resp = client.get("/eventos")
    assert resp.status_code == 200
    for titulo in ("CompletoShow", "SinFechaFlyer", "SinLugarShow", "ReleaseOk"):
        assert titulo in resp.text


def test_eventos_filtro_incompletos(client) -> None:
    resp = client.get("/eventos?solo=incompletos")
    assert resp.status_code == 200
    assert "SinFechaFlyer" in resp.text
    assert "SinLugarShow" in resp.text
    assert "CompletoShow" not in resp.text
    assert "ReleaseOk" not in resp.text


def test_calendario_linkea_al_filtro(client) -> None:
    resp = client.get("/calendario")
    assert resp.status_code == 200
    assert "/eventos?solo=incompletos" in resp.text


def test_marcar_irrelevante_y_restaurar(client) -> None:
    eid = client._ids["SinFechaFlyer"]
    resp = client.post(f"/eventos/{eid}/irrelevante")
    assert resp.status_code == 200
    cx = db.connect()
    assert cx.execute("SELECT irrelevante FROM events WHERE id=?",
                      (eid,)).fetchone()["irrelevante"] == 1
    cx.close()
    # segundo toggle → restaurado
    client.post(f"/eventos/{eid}/irrelevante")
    cx = db.connect()
    assert cx.execute("SELECT irrelevante FROM events WHERE id=?",
                      (eid,)).fetchone()["irrelevante"] == 0
    cx.close()


def test_irrelevantes_fuera_de_listas_y_con_su_filtro(client) -> None:
    eid = client._ids["SinFechaFlyer"]
    client.post(f"/eventos/{eid}/irrelevante")
    assert "SinFechaFlyer" not in client.get("/eventos").text
    assert "SinFechaFlyer" not in client.get("/eventos?solo=incompletos").text
    assert "SinFechaFlyer" in client.get("/eventos?solo=irrelevantes").text


def test_calendario_excluye_irrelevantes(client) -> None:
    cx = db.connect()
    # flyer sin fecha → aparece en la franja "SIN fecha" del calendario
    db.update(cx, "events", client._ids["SinFechaFlyer"], flyer_path="/tmp/f.jpg")
    cx.close()
    assert "SinFechaFlyer" in client.get("/calendario").text
    client.post(f"/eventos/{client._ids['SinFechaFlyer']}/irrelevante")
    assert "SinFechaFlyer" not in client.get("/calendario").text


def test_agenda_excluye_irrelevantes(tmp_path, monkeypatch) -> None:
    from datetime import datetime, timedelta

    from src.generate_agenda import eventos_ventana, releases_ventana

    cx = db.connect(tmp_path / "agenda.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala")
    manana = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    ayer = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    show = db.insert(cx, "events", band_id=bid, tipo="fecha", fecha_evento=manana,
                     lugar="Staditche")
    rel = db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento=ayer)
    assert len(eventos_ventana(cx, 7)) == 1
    assert len(releases_ventana(cx, 7)) == 1
    db.update(cx, "events", show, irrelevante=1)
    db.update(cx, "events", rel, irrelevante=1)
    assert eventos_ventana(cx, 7) == []
    assert releases_ventana(cx, 7) == []
    cx.close()
