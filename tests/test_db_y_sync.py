"""Tests mínimos de Fase 1: esquema/CRUD de src/db.py y mapeo queue→Sheet.

No tocan red ni el Sheet real: el sync se prueba solo en su función pura
`to_sheet_fields`. Correr con:  pytest tests/ -q
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src import db
from src.sync_sheet import to_sheet_fields


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_init_es_idempotente(cx) -> None:
    db.init_db(cx)  # segunda corrida no debe tronar ni borrar datos
    bid = db.insert(cx, "bands", nombre="Lefnes")
    db.init_db(cx)
    assert db.get(cx, "bands", bid)["nombre"] == "Lefnes"


def test_upsert_band_no_duplica(cx) -> None:
    a = db.upsert_band(cx, "Kabala", "kabala.gdl", prioridad=5)
    b = db.upsert_band(cx, "Kabala", "kabala.gdl", prioridad=2)
    assert a == b
    assert db.get(cx, "bands", a)["prioridad"] == 2
    assert len(db.list_bands(cx)) == 1


def test_columnas_desconocidas_truenan(cx) -> None:
    with pytest.raises(KeyError):
        db.insert(cx, "bands", nombre="X", columna_falsa=1)
    with pytest.raises(KeyError):
        db.insert(cx, "tabla_falsa", nombre="X")


def test_fk_y_cascade(cx) -> None:
    bid = db.insert(cx, "bands", nombre="Noisy Room")
    pid = db.insert(cx, "photos", band_id=bid, path="/tmp/x.jpg")
    cx.execute("DELETE FROM bands WHERE id = ?", (bid,))
    cx.commit()
    assert db.get(cx, "photos", pid) is None  # ON DELETE CASCADE


def test_queue_listos_y_mapeo_sheet(cx) -> None:
    bid = db.insert(cx, "bands", nombre="Noisy Room")
    mid = db.insert(cx, "members", band_id=bid, nombre="Carlos Virgen", rol="guitarrista")
    pid = db.insert(cx, "photos", band_id=bid, member_id=mid, path="data/photos/nr.jpg",
                    usable_meme=1)
    db.insert(cx, "content_queue", band_id=bid, member_id=mid, photo_id=pid,
              tema_semilla="cocinas modernas", status=db.QUEUE_LISTO)
    db.insert(cx, "content_queue", band_id=bid, status=db.QUEUE_BORRADOR)  # no debe salir

    listos = db.queue_listos(cx)
    assert len(listos) == 1

    fields = to_sheet_fields(listos[0], now=datetime(2026, 6, 4, 12, 0))
    assert fields["banda"] == "Noisy Room"
    assert fields["integrante"] == "Carlos Virgen"
    assert fields["rol"] == "guitarrista"
    assert fields["tema_semilla"] == "cocinas modernas"
    assert fields["status"] == "pending"
    assert fields["fecha_captura"] == "2026-06-04"
    assert Path(fields["foto_url"]).is_absolute()  # compose._to_src la convierte a file://


def test_mapeo_sheet_sin_member(cx) -> None:
    """Sin integrante: el caption habla de la banda como colectivo (campos vacíos)."""
    bid = db.insert(cx, "bands", nombre="Los Flakos")
    pid = db.insert(cx, "photos", band_id=bid, path="/abs/foto.jpg")
    db.insert(cx, "content_queue", band_id=bid, photo_id=pid, status=db.QUEUE_LISTO)
    fields = to_sheet_fields(db.queue_listos(cx)[0])
    assert fields["integrante"] == "" and fields["rol"] == ""
    assert fields["foto_url"] == "/abs/foto.jpg"


def test_generos_list_tolerante() -> None:
    assert db.generos_list({"generos": '["punk","garage"]'}) == ["punk", "garage"]
    assert db.generos_list({"generos": None}) == []
    assert db.generos_list({"generos": "no es json"}) == []
