"""Fuente «Seguidos de IG» (plan 5 del editor v2). Sin red: IG se simula con fixtures."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from src import db, import_followees
from src.assets import ig_seguidos

FIX = Path(__file__).parent / "fixtures" / "assets" / "ig"


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


def _following() -> list[dict]:
    return json.loads((FIX / "following.json").read_text())


@pytest.fixture
def following_falso(monkeypatch):
    llamadas: list[tuple] = []

    def falso(cuenta, limite):
        llamadas.append((cuenta, limite))
        return _following()

    monkeypatch.setattr(import_followees, "_listar_con_pool", falso)
    return llamadas


def test_normalizar_handle() -> None:
    assert ig_seguidos.normalizar_handle("  @Cafe.Tacuba ") == "cafe.tacuba"
    for malo in ("", "@", "../x", "a b", "x" * 31, "café", "a..b"):
        with pytest.raises(ValueError):
            ig_seguidos.normalizar_handle(malo)


def test_importar_seguidos_crea_candidatas(cx, ids, following_falso) -> None:
    a, b = ids["a"], ids["b"]
    r = ig_seguidos.importar_seguidos(cx, a, "@PensionMas", limite=50)
    assert following_falso == [("pensionmas", 50)]
    assert r == {"nuevas": 3, "ya": 0, "total": 4}          # el handle con "../" se salta
    filas = {f["ig_handle"]: f for f in ig_seguidos.listar(cx, a)}
    assert set(filas) == {"cafe.tacuba", "la_privada", "mercado.roma"}
    cafe = filas["cafe.tacuba"]
    assert cafe["estado"] == "candidata"
    assert cafe["origen"] == "seguido_de:pensionmas"
    assert cafe["nombre"] == "Café Tacuba Bar"
    assert cafe["avatar_url"].startswith("https://")
    assert cafe["privada"] == 0
    assert filas["la_privada"]["privada"] == 1
    assert filas["la_privada"]["nombre"] == "la_privada"   # full_name vacío => handle
    assert filas["mercado.roma"]["avatar_url"] is None     # solo https://
    assert ig_seguidos.listar(cx, b) == []                 # otra marca no ve nada


def test_reimportar_respeta_curaduria(cx, ids, following_falso) -> None:
    a = ids["a"]
    ig_seguidos.importar_seguidos(cx, a, "pensionmas")
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, a, "la_privada", "descartada")
    r = ig_seguidos.importar_seguidos(cx, a, "otra.semilla")
    assert r == {"nuevas": 0, "ya": 3, "total": 4}
    estados = {f["ig_handle"]: (f["estado"], f["origen"]) for f in ig_seguidos.listar(cx, a)}
    assert estados == {
        "cafe.tacuba": ("activa", "seguido_de:pensionmas"),
        "la_privada": ("descartada", "seguido_de:pensionmas"),
        "mercado.roma": ("candidata", "seguido_de:pensionmas"),
    }


def test_fijar_estado_upsert_manual(cx, ids) -> None:
    a = ids["a"]
    fila = ig_seguidos.fijar_estado(cx, a, "@Nueva.Cuenta", "activa")
    assert (fila["ig_handle"], fila["estado"], fila["origen"]) == ("nueva.cuenta", "activa", "manual")
    fila = ig_seguidos.fijar_estado(cx, a, "nueva.cuenta", "descartada")
    assert fila["estado"] == "descartada"
    assert fila["origen"] == "manual"
    filas = ig_seguidos.listar(cx, a)
    assert [(f["ig_handle"], f["estado"]) for f in filas] == [("nueva.cuenta", "descartada")]
    with pytest.raises(ValueError):
        ig_seguidos.fijar_estado(cx, a, "nueva.cuenta", "aprobada")
    assert ig_seguidos.listar(cx, a)[0]["estado"] == "descartada"   # el rechazo no mutó nada


def test_fijar_estado_no_cruza_marcas(cx, ids) -> None:
    ig_seguidos.fijar_estado(cx, ids["a"], "comun", "activa")
    ig_seguidos.fijar_estado(cx, ids["b"], "comun", "descartada")
    assert ig_seguidos.listar(cx, ids["a"])[0]["estado"] == "activa"
    assert ig_seguidos.listar(cx, ids["b"])[0]["estado"] == "descartada"


def test_listar_filtra_por_estado(cx, ids) -> None:
    a = ids["a"]
    ig_seguidos.fijar_estado(cx, a, "a1", "activa")
    ig_seguidos.fijar_estado(cx, a, "c1", "candidata")
    ig_seguidos.fijar_estado(cx, a, "d1", "descartada")
    assert [f["ig_handle"] for f in ig_seguidos.listar(cx, a, estado="activa")] == ["a1"]
    assert [f["ig_handle"] for f in ig_seguidos.listar(cx, a)] == ["c1", "a1", "d1"]  # candidatas primero
    with pytest.raises(ValueError):
        ig_seguidos.listar(cx, a, estado="todas")


def test_importar_gdlscene_sigue_escribiendo_bands(cx, ids, tmp_path, following_falso, monkeypatch) -> None:
    """El flujo de gdlscene no cambia y no se cruza con brand_ig_cuentas."""
    real = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: real(tmp_path / "t.db"))
    r = import_followees.importar(cuenta="gdlscene", limite=10)
    assert following_falso == [("gdlscene", 10)]
    assert r == {"nuevas": 4, "ya": 0, "total": 4}   # importar no valida handles: el "../" entra a bands
    handles = {f["ig_handle"] for f in db.rows(cx, "SELECT ig_handle FROM bands", ())}
    assert "cafe.tacuba" in handles
    assert db.rows(cx, "SELECT id FROM brand_ig_cuentas", ()) == []


@pytest.mark.lento
@pytest.mark.ig_real
@pytest.mark.skipif(os.getenv("IG_REAL") != "1",
                    reason="usa una cookie real del pool; correr solo con aprobación de Ricardo")
def test_contrato_following_real() -> None:
    """Confirma las llaves que los fixtures inventaron. IG_REAL=1 pytest -m ig_real."""
    usuarios = import_followees._listar_con_pool("gdlscene", 5)
    assert usuarios, "following vacío"
    assert {"username", "full_name", "is_private", "profile_pic_url"} <= set(usuarios[0])
