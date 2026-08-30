"""CRUD de brand_entities: el sujeto genérico del contenido."""
from __future__ import annotations

from src import db, entidades


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_slugificar_normaliza_acentos_y_espacios() -> None:
    assert entidades.slugificar("Los Ácidos del Norte") == "los-acidos-del-norte"
    assert entidades.slugificar("  Café   Tacvba  ") == "cafe-tacvba"
    assert entidades.slugificar("¿Qué Pex?") == "que-pex"


def test_crear_y_obtener(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = entidades.crear(cx, 1, "Los Ejemplo", "banda",
                          atributos={"followers_ig": 1200})
    fila = entidades.obtener(cx, eid)
    assert fila["slug"] == "los-ejemplo"
    assert entidades.atributos_de(fila) == {"followers_ig": 1200}


def test_slug_colisionado_recibe_sufijo(tmp_path) -> None:
    cx = _cx(tmp_path)
    entidades.crear(cx, 1, "Los Ejemplo", "banda")
    eid2 = entidades.crear(cx, 1, "Los Ejemplo", "banda")
    assert entidades.obtener(cx, eid2)["slug"] == "los-ejemplo-2"


def test_listar_aisla_por_cuenta(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="otra", ig_handle="otra",
              nombre="Otra", ciudad="CDMX")
    otra = db.rows(cx, "SELECT id FROM accounts WHERE slug='otra'")[0]["id"]
    entidades.crear(cx, 1, "De la uno", "banda")
    entidades.crear(cx, otra, "De la otra", "propiedad")
    assert [e["nombre"] for e in entidades.listar(cx, 1)] == ["De la uno"]
    assert [e["nombre"] for e in entidades.listar(cx, otra)] == ["De la otra"]


def test_archivar_la_saca_del_listado(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = entidades.crear(cx, 1, "Temporal", "banda")
    entidades.archivar(cx, eid)
    assert entidades.listar(cx, 1) == []
    assert len(entidades.listar(cx, 1, solo_activas=False)) == 1


def test_atributos_malformados_no_revientan(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = entidades.crear(cx, 1, "Rota", "banda")
    db.update(cx, "brand_entities", eid, atributos_json="{esto no es json")
    assert entidades.atributos_de(entidades.obtener(cx, eid)) == {}
