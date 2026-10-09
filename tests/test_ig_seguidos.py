"""Fuente «Seguidos de IG» (plan 5 del editor v2). Sin red: IG se simula con fixtures."""
from __future__ import annotations

import sqlite3

import pytest

from src import db


@pytest.fixture
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture
def ids(cx) -> dict[str, int]:
    """Ids reales devueltos por insert (init_db siembra gdlscene=1; no se asume nada)."""
    return {
        "a": db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p",
                       nombre="P", ciudad="CDMX"),
        "b": db.insert(cx, "accounts", slug="daisies", ig_handle="@d",
                       nombre="D", ciudad="CDMX"),
    }


def test_precondicion_plan3_brand_assets_existe(cx) -> None:
    cols = {r[1] for r in cx.execute("PRAGMA table_info(brand_assets)")}
    assert {"account_id", "tipo", "archivo", "sha", "proveedor", "ig_handle",
            "source_post_id", "tags_json"} <= cols


def test_tabla_ig_cuentas_defaults(cx, ids) -> None:
    cid = db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="cafe.tacuba")
    fila = db.get(cx, "brand_ig_cuentas", cid)
    assert fila["estado"] == "candidata"
    assert fila["origen"] == "manual"
    assert fila["privada"] == 0


def test_tabla_ig_cuentas_unica_por_marca(cx, ids) -> None:
    db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="cafe.tacuba")
    db.insert(cx, "brand_ig_cuentas", account_id=ids["b"], ig_handle="cafe.tacuba")  # otra marca: OK
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="cafe.tacuba")


def test_tabla_ig_cuentas_estado_invalido(cx, ids) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_ig_cuentas", account_id=ids["a"], ig_handle="x", estado="aprobada")
