"""Tests del clasificador de géneros vía LLM (Frente A) y su pieza en la GUI.

El LLM se mockea en el límite `_llm_clasificar` (igual que parse_events mockea
`_llm_extraer`): sin red, respuestas controladas por test.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import config
from src import clasifica_generos as cg
from src import db


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)
    yield cx
    cx.close()


def _banda(cx, nombre, **fields):
    return db.insert(cx, "bands", nombre=nombre, ig_handle=nombre.lower(),
                     activa=1, **fields)


# ---------- clasificador (CLI / batch) ----------

def test_genero_valido_se_guarda(cx, monkeypatch):
    bid = _banda(cx, "PunkBand", bio="ruido rápido")
    monkeypatch.setattr(cg, "_llm_clasificar",
                        lambda ctx: {"genero_principal": "punk", "subtags": ["d-beat", "crust"]})
    res = cg.clasificar(cx=cx)
    assert res["clasificadas"] == 1
    fila = db.get(cx, "bands", bid)
    assert fila["genero_principal"] == "punk"
    assert fila["generos_fuente"] == "llm"
    assert db.generos_list(fila) == ["d-beat", "crust"]


def test_genero_inventado_se_mapea_por_substring(cx, monkeypatch):
    bid = _banda(cx, "Mapeable")
    # "indie rock" no está literal en la taxonomía pero contiene "indie".
    monkeypatch.setattr(cg, "_llm_clasificar",
                        lambda ctx: {"genero_principal": "Indie Rock", "subtags": []})
    res = cg.clasificar(cx=cx)
    assert res["clasificadas"] == 1
    assert db.get(cx, "bands", bid)["genero_principal"] == "indie"


def test_genero_fuera_de_taxonomia_no_toca_la_banda(cx, monkeypatch):
    bid = _banda(cx, "Rara")
    monkeypatch.setattr(cg, "_llm_clasificar",
                        lambda ctx: {"genero_principal": "reggaeton", "subtags": ["x"]})
    res = cg.clasificar(cx=cx)
    assert res["falladas"] == 1
    assert res["clasificadas"] == 0
    fila = db.get(cx, "bands", bid)
    assert fila["genero_principal"] is None
    assert fila["generos_fuente"] is None


def test_nunca_pisa_fuente_manual(cx, monkeypatch):
    bid = _banda(cx, "Curada", genero_principal="rock", generos_fuente="manual",
                 generos=json.dumps(["a mano"], ensure_ascii=False))
    monkeypatch.setattr(cg, "_llm_clasificar",
                        lambda ctx: {"genero_principal": "metal", "subtags": ["nope"]})
    res = cg.clasificar(cx=cx)
    assert res["saltadas"] == 1
    fila = db.get(cx, "bands", bid)
    assert fila["genero_principal"] == "rock"
    assert fila["generos_fuente"] == "manual"


def test_reclasifica_fuente_llm(cx, monkeypatch):
    bid = _banda(cx, "ReHacer", genero_principal="pop", generos_fuente="llm")
    monkeypatch.setattr(cg, "_llm_clasificar",
                        lambda ctx: {"genero_principal": "punk", "subtags": []})
    cg.clasificar(cx=cx)
    assert db.get(cx, "bands", bid)["genero_principal"] == "punk"


def test_json_malformado_deja_banda_intacta_y_sigue(cx, monkeypatch):
    b1 = _banda(cx, "Rompe")
    b2 = _banda(cx, "Sigue")

    def fake(ctx):
        if "Rompe" in ctx:
            return None  # respuesta no parseable
        return {"genero_principal": "garage", "subtags": []}

    monkeypatch.setattr(cg, "_llm_clasificar", fake)
    res = cg.clasificar(cx=cx)
    assert res["falladas"] == 1 and res["clasificadas"] == 1
    assert db.get(cx, "bands", b1)["genero_principal"] is None
    assert db.get(cx, "bands", b2)["genero_principal"] == "garage"


def test_excepcion_del_llm_no_tumba_la_corrida(cx, monkeypatch):
    b1 = _banda(cx, "Cae")
    b2 = _banda(cx, "Ok")

    def fake(ctx):
        if "Cae" in ctx:
            raise RuntimeError("LLM caído")
        return {"genero_principal": "metal", "subtags": []}

    monkeypatch.setattr(cg, "_llm_clasificar", fake)
    res = cg.clasificar(cx=cx)
    assert res["falladas"] == 1 and res["clasificadas"] == 1
    assert db.get(cx, "bands", b2)["genero_principal"] == "metal"


def test_solo_faltantes_filtra(cx, monkeypatch):
    con_genero = _banda(cx, "YaTiene", genero_principal="rock", generos_fuente="llm")
    sin_genero = _banda(cx, "LeFalta")
    llamadas = []

    def fake(ctx):
        llamadas.append(ctx)
        return {"genero_principal": "punk", "subtags": []}

    monkeypatch.setattr(cg, "_llm_clasificar", fake)
    res = cg.clasificar(cx=cx, solo_faltantes=True)
    assert res["clasificadas"] == 1
    assert len(llamadas) == 1
    assert db.get(cx, "bands", sin_genero)["genero_principal"] == "punk"
    assert db.get(cx, "bands", con_genero)["genero_principal"] == "rock"


def test_filtra_por_handles(cx, monkeypatch):
    a = _banda(cx, "Elegida")  # ig_handle = "elegida"
    b = _banda(cx, "Otra")
    monkeypatch.setattr(cg, "_llm_clasificar",
                        lambda ctx: {"genero_principal": "indie", "subtags": []})
    res = cg.clasificar(cx=cx, handles=["elegida"])
    assert res["clasificadas"] == 1
    assert db.get(cx, "bands", a)["genero_principal"] == "indie"
    assert db.get(cx, "bands", b)["genero_principal"] is None


def test_banda_inactiva_se_ignora(cx, monkeypatch):
    bid = db.insert(cx, "bands", nombre="Archivada", ig_handle="archivada", activa=0)
    monkeypatch.setattr(cg, "_llm_clasificar",
                        lambda ctx: {"genero_principal": "punk", "subtags": []})
    res = cg.clasificar(cx=cx)
    assert res["clasificadas"] == 0
    assert db.get(cx, "bands", bid)["genero_principal"] is None


def test_contexto_incluye_captions_mas_largos_primero(cx, monkeypatch):
    bid = _banda(cx, "ConFotos", bio="bio corta")
    db.insert(cx, "photos", band_id=bid, path="/tmp/a.jpg",
              caption_original="x" * 10)
    db.insert(cx, "photos", band_id=bid, path="/tmp/b.jpg",
              caption_original="CAPTION_LARGO " * 20)
    capturado = {}

    def fake(ctx):
        capturado["ctx"] = ctx
        return {"genero_principal": "rock", "subtags": []}

    monkeypatch.setattr(cg, "_llm_clasificar", fake)
    cg.clasificar(cx=cx)
    ctx = capturado["ctx"]
    assert "CAPTION_LARGO" in ctx
    # el largo aparece antes que el corto (orden por longitud desc)
    assert ctx.index("CAPTION_LARGO") < ctx.index("x" * 10)


# ---------- GUI ----------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "web.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)
    cx.close()
    from web.app import app
    with TestClient(app) as c:
        yield c


def test_gui_guardar_genero_setea_fuente_manual(client):
    cx = db.connect()
    bid = db.insert(cx, "bands", nombre="Editada", genero_principal="pop",
                    generos_fuente="llm", activa=1)
    cx.close()
    resp = client.post(f"/bandas/{bid}", data={
        "nombre": "Editada", "genero_principal": "punk", "prioridad": 3, "activa": 1,
    })
    assert resp.status_code == 200
    cx = db.connect()
    fila = db.get(cx, "bands", bid)
    cx.close()
    assert fila["genero_principal"] == "punk"
    assert fila["generos_fuente"] == "manual"


def test_gui_genero_fuera_de_taxonomia_queda_none(client):
    cx = db.connect()
    bid = db.insert(cx, "bands", nombre="Mala", activa=1)
    cx.close()
    client.post(f"/bandas/{bid}", data={
        "nombre": "Mala", "genero_principal": "reggaeton", "prioridad": 3, "activa": 1,
    })
    cx = db.connect()
    assert db.get(cx, "bands", bid)["genero_principal"] is None
    cx.close()


def test_gui_genero_vacio_no_setea_manual(client):
    """Guardar sin tocar el género (vacío y ya era None) no marca fuente manual."""
    cx = db.connect()
    bid = db.insert(cx, "bands", nombre="SinGenero", activa=1)
    cx.close()
    client.post(f"/bandas/{bid}", data={
        "nombre": "SinGenero", "genero_principal": "", "prioridad": 3, "activa": 1,
    })
    cx = db.connect()
    fila = db.get(cx, "bands", bid)
    cx.close()
    assert fila["genero_principal"] is None
    assert fila["generos_fuente"] is None


def test_gui_filtro_por_genero(client):
    cx = db.connect()
    db.insert(cx, "bands", nombre="PunkA", genero_principal="punk", activa=1)
    db.insert(cx, "bands", nombre="MetalB", genero_principal="metal", activa=1)
    cx.close()
    resp = client.get("/bandas?genero=punk")
    assert "PunkA" in resp.text
    assert "MetalB" not in resp.text


def test_gui_edit_tiene_select_de_generos(client):
    cx = db.connect()
    bid = db.insert(cx, "bands", nombre="Edit", activa=1)
    cx.close()
    resp = client.get(f"/bandas/{bid}/edit")
    assert 'name="genero_principal"' in resp.text
    for g in config.GENEROS:
        assert f'value="{g}"' in resp.text
