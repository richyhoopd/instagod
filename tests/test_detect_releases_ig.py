"""Tests de detección de releases en captions de IG (Frente B).

El LLM se mockea en el límite `_llm_release` (igual que parse_events mockea
`_llm_extraer`): sin red, respuestas controladas por test. La DB vive en
tmp_path con db.connect/init_db.
"""
from __future__ import annotations

import pytest

from src import db
from src import detect_releases_ig as dr


@pytest.fixture()
def cx(tmp_path):
    cx = db.connect(tmp_path / "test.db")
    db.init_db(cx)
    yield cx
    cx.close()


def _banda(cx, nombre="Banda X"):
    return db.insert(cx, "bands", nombre=nombre, ig_handle=nombre.lower().replace(" ", ""))


def _post(band_id, shortcode="ABC123", caption="ya disponible nuestro disco",
          path="/fotos/banda/ABC123.jpg", fecha="2026-06-01"):
    return {"band_id": band_id, "shortcode": shortcode, "caption": caption,
            "path": path, "fecha": fecha}


def _eventos(cx):
    return db.rows(cx, "SELECT * FROM events ORDER BY id")


def test_release_crea_evento(cx, monkeypatch):
    bid = _banda(cx)
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "Noche Eterna", "tipo": "album",
        "fecha": "2026-06-05"})
    res = dr.detectar(cx, [_post(bid)])

    evs = _eventos(cx)
    assert len(evs) == 1
    ev = evs[0]
    assert ev["tipo"] == "release"
    assert ev["band_id"] == bid
    assert ev["titulo"] == "Noche Eterna"
    assert ev["fecha_evento"] == "2026-06-05"
    assert ev["cover_url"] == "/fotos/banda/ABC123.jpg"
    assert ev["source_post_id"] == "ig:ABC123"
    assert ev["status"] == "nuevo"
    assert ev["parseado_por_llm"] == 1
    assert res["revisados"] == 1
    assert res["releases_nuevos"] == 1
    assert res["saltados_dedupe"] == 0
    assert res["fallidos"] == 0


def test_fecha_del_post_si_llm_no_da_fecha(cx, monkeypatch):
    bid = _banda(cx)
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "Single Nuevo", "tipo": "sencillo", "fecha": None})
    dr.detectar(cx, [_post(bid, fecha="2026-06-02")])
    assert _eventos(cx)[0]["fecha_evento"] == "2026-06-02"


def test_titulo_null_no_inserta(cx, monkeypatch):
    bid = _banda(cx)
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": None, "tipo": "album", "fecha": "2026-06-05"})
    res = dr.detectar(cx, [_post(bid)])
    assert _eventos(cx) == []
    assert res["releases_nuevos"] == 0


def test_caption_normal_no_crea_nada(cx, monkeypatch):
    bid = _banda(cx)
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": False, "titulo": None, "tipo": None, "fecha": None})
    res = dr.detectar(cx, [_post(bid, caption="esta noche en el foro!")])
    assert _eventos(cx) == []
    assert res["releases_nuevos"] == 0
    assert res["revisados"] == 1


def test_dedupe_vs_spotify_existente(cx, monkeypatch):
    bid = _banda(cx)
    # Release de Spotify ya en la DB: mismo título con sufijo distinto, fecha cercana.
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Noche Eterna (álbum)",
              fecha_evento="2026-06-01", cover_url="https://spotify/cover.jpg",
              source_post_id="spotify:abc")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "Noche Eterna (sencillo)", "tipo": "sencillo",
        "fecha": "2026-06-10"})
    res = dr.detectar(cx, [_post(bid)])
    assert len(_eventos(cx)) == 1  # solo el de Spotify
    assert res["saltados_dedupe"] == 1
    assert res["releases_nuevos"] == 0


def test_dedupe_por_shortcode_repetido(cx, monkeypatch):
    bid = _banda(cx)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Algo",
              fecha_evento="2026-06-01", source_post_id="ig:ABC123")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "Otro Titulo", "tipo": "album", "fecha": "2026-06-05"})
    res = dr.detectar(cx, [_post(bid, shortcode="ABC123")])
    assert len(_eventos(cx)) == 1
    assert res["saltados_dedupe"] == 1


def test_fecha_lejana_si_inserta(cx, monkeypatch):
    bid = _banda(cx)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Noche Eterna",
              fecha_evento="2026-01-01")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "Noche Eterna", "tipo": "album", "fecha": "2026-06-05"})
    res = dr.detectar(cx, [_post(bid)])
    assert len(_eventos(cx)) == 2  # >30 días: no es el mismo
    assert res["releases_nuevos"] == 1
    assert res["saltados_dedupe"] == 0


def test_json_malformado_tolerado(cx, monkeypatch):
    bid = _banda(cx)

    def _boom(cap, f):
        return None  # el LLM no devolvió JSON parseable

    monkeypatch.setattr(dr, "_llm_release", _boom)
    res = dr.detectar(cx, [_post(bid)])
    assert _eventos(cx) == []
    assert res["fallidos"] == 1
    assert res["revisados"] == 1


def test_llm_caido_no_tumba_corrida(cx, monkeypatch):
    bid = _banda(cx)

    def _boom(cap, f):
        raise RuntimeError("LLM caído")

    monkeypatch.setattr(dr, "_llm_release", _boom)
    # Dos posts que truenan: la corrida sigue y los cuenta como fallidos.
    res = dr.detectar(cx, [_post(bid, shortcode="P1"), _post(bid, shortcode="P2")])
    assert res["fallidos"] == 2
    assert res["revisados"] == 2


def test_caption_vacio_no_llama_llm(cx, monkeypatch):
    bid = _banda(cx)

    def _no_llamar(cap, f):
        raise AssertionError("no debe llamarse el LLM con caption vacío")

    monkeypatch.setattr(dr, "_llm_release", _no_llamar)
    res = dr.detectar(cx, [_post(bid, caption="   "), _post(bid, shortcode="P2", caption=None)])
    assert _eventos(cx) == []
    assert res["revisados"] == 2
    assert res["releases_nuevos"] == 0
    assert res["fallidos"] == 0
