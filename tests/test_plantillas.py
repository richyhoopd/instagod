"""CRUD y versionado de plantillas de marca."""
from __future__ import annotations

import pytest

from src import db, plantillas
from src.plantillas import contrato as c


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct(extras=None) -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}


_HTML = ("<div class='card' style='color:{{ color_marca }}'>"
         "<img src='{{ imagen }}'><h1>{{ titular }}</h1>"
         "<img src='{{ logo }}'><span>{{ handle }}</span></div>")


def test_crear_deja_v1(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct(), origen="seed")
    fila = plantillas.obtener(cx, tid)
    assert fila["slug"] == "clasica"
    assert fila["version_actual"] == 1
    assert len(plantillas.versiones(cx, tid)) == 1


def test_crear_rechaza_html_con_variable_inventada(tmp_path) -> None:
    cx = _cx(tmp_path)
    malo = _HTML + "{{ inventada }}"
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Mala", malo, _ct())
    assert plantillas.listar(cx, 1) == []


def test_crear_rechaza_contrato_sin_campo_base(tmp_path) -> None:
    cx = _cx(tmp_path)
    ct = _ct()
    ct["base"] = ["titular"]
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Mala", _HTML, ct)


def test_nueva_version_incrementa_y_no_pisa(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    v2 = plantillas.nueva_version(cx, tid, _HTML.replace("card", "card verde"),
                                  _ct(), mensaje_usuario="hazla verde")
    assert v2 == 2
    assert plantillas.obtener(cx, tid)["version_actual"] == 2
    assert "verde" in plantillas.obtener(cx, tid)["html"]
    assert "verde" not in plantillas.version(cx, tid, 1)["html"]


def test_revertir_agrega_version_nueva(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    plantillas.nueva_version(cx, tid, _HTML.replace("card", "card v2"), _ct())
    v3 = plantillas.revertir(cx, tid, 1)
    assert v3 == 3
    assert len(plantillas.versiones(cx, tid)) == 3
    assert plantillas.obtener(cx, tid)["html"] == _HTML


def test_listar_filtra_por_estado_y_cuenta(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Activa", _HTML, _ct())
    plantillas.crear(cx, 1, "Borrador", _HTML, _ct())
    plantillas.activar(cx, tid)
    activas = plantillas.listar(cx, 1, estado="activa")
    assert [t["nombre"] for t in activas] == ["Activa"]


def test_contrato_de_tolera_json_roto(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    db.update(cx, "brand_templates", tid, contrato_json="{roto")
    assert plantillas.contrato_de(plantillas.obtener(cx, tid)) == {}


def test_extras_del_contrato_se_pueden_usar_en_el_html(tmp_path) -> None:
    cx = _cx(tmp_path)
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    html = _HTML + "{% for p in pasos %}<li>{{ p }}</li>{% endfor %}"
    tid = plantillas.crear(cx, 1, "Tips", html, ct)
    assert plantillas.obtener(cx, tid) is not None
