"""Edición manual de los campos de un post y re-render."""
from __future__ import annotations

import json

import pytest

from src import cola, db, marcas, plantillas
from src.plantillas import contrato as c

_HTML = "<div class='card'>{{ titular }} {{ handle }}</div>"


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _pieza(cx, m, extras=None) -> tuple[int, int]:
    ct = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}
    tid = plantillas.crear(cx, m.id, "Simple", _HTML, ct)
    qid = db.insert(cx, "content_queue", tipo="post", account_id=m.id,
                    template_id=tid, template_version=1, aspecto="4:5",
                    campos_json=json.dumps({"titular": "original"}),
                    status="borrador")
    return tid, qid


def test_editar_campos_guarda(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m)
    cola.editar_campos(cx, qid, {"titular": "corregido a mano"})
    guardado = json.loads(db.get(cx, "content_queue", qid)["campos_json"])
    assert guardado["titular"] == "corregido a mano"


def test_rechaza_campos_que_violan_el_contrato(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m, extras=[{"id": "pasos", "tipo": "lista",
                                    "min": 3, "max": 3}])
    with pytest.raises(ValueError, match="campos"):
        cola.editar_campos(cx, qid, {"titular": "x", "pasos": ["solo uno"]})


def test_rechaza_si_no_es_post(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=m.id)
    with pytest.raises(ValueError, match="tipo"):
        cola.editar_campos(cx, qid, {"titular": "x"})


def test_rechaza_si_ya_se_publico(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m)
    db.update(cx, "content_queue", qid, status="publicado")
    with pytest.raises(ValueError, match="estado"):
        cola.editar_campos(cx, qid, {"titular": "tarde"})


def test_no_toca_el_titular_si_solo_cambia_un_extra(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m, extras=[{"id": "badge", "tipo": "texto",
                                    "opcional": True}])
    cola.editar_campos(cx, qid, {"titular": "original", "badge": "NUEVO"})
    guardado = json.loads(db.get(cx, "content_queue", qid)["campos_json"])
    assert guardado["titular"] == "original" and guardado["badge"] == "NUEVO"
