"""Aprobación asíncrona: encolar pendiente y resolver (aprobar/rechazar)."""
from __future__ import annotations

from datetime import datetime

from src import approval, db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_encolar_pendiente(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    qid = approval.encolar_pendiente(cx, tipo="meme", band_id=bid,
                                     caption="hola", imagen_url="http://x/y.jpg")
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "pendiente" and fila["status"] == "borrador"
    assert fila["caption"] == "hola" and fila["imagen_url"] == "http://x/y.jpg"


def test_aprobar_agenda_slot(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="x", imagen_url="u")
    slot = approval.aprobar(cx, qid, ahora=datetime(2026, 6, 8, 10, 0),
                            ventana_trafico="meme", audiencia=[],
                            _escribir_sheet=lambda **k: 99)  # doble: no toca Sheet real
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "aprobado" and fila["status"] == "en_sheet"
    assert fila["sheet_row_id"] == "99"
    assert slot.hour == 20  # default meme = miércoles 20h


def test_rechazar(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="x", imagen_url="u")
    approval.rechazar(cx, qid)
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "rechazado" and fila["status"] == "descartado"


def test_aprobar_marca_eventos_anunciado(tmp_path) -> None:
    """Al aprobar, los events de evento_ids quedan status='anunciado'."""
    import json
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="SilentNoir")
    e1 = db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-01")
    e2 = db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-02")
    qid = approval.encolar_pendiente(cx, tipo="anuncio", caption="x", imagen_url="u",
                                     evento_ids=json.dumps([e1, e2]))
    approval.aprobar(cx, qid, ahora=datetime(2026, 6, 8, 10, 0),
                     ventana_trafico="meme", audiencia=[],
                     _escribir_sheet=lambda **k: 99)
    assert db.get(cx, "events", e1)["status"] == "anunciado"
    assert db.get(cx, "events", e2)["status"] == "anunciado"


# --- Helpers PUROS del daemon (la cáscara que hace polling no se testea) ---

def test_construir_botones() -> None:
    teclado = approval.construir_botones(123)
    datas = [b["callback_data"] for fila in teclado for b in fila]
    assert datas == ["aprobar:123", "rechazar:123"]


def test_parsear_callback() -> None:
    assert approval.parsear_callback("aprobar:123") == ("aprobar", 123)
    assert approval.parsear_callback("rechazar:7") == ("rechazar", 7)


def test_parsear_callback_invalido() -> None:
    import pytest
    with pytest.raises(ValueError):
        approval.parsear_callback("borrar:1")


# --- Helper puro: parsear imagen_url (string vs JSON-lista) ---

def test_parse_imagen_url():
    from src import approval
    import json
    assert approval._urls_de_imagen(json.dumps(["a","b","c"])) == ["a","b","c"]
    assert approval._urls_de_imagen("http://x/y.jpg") == ["http://x/y.jpg"]
    assert approval._urls_de_imagen("") == []
