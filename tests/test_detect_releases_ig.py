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
    assert ev["source_post_id"] == "ABC123"  # llave unificada (sin prefijo ig:)
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


def test_mismo_post_actualiza_no_duplica(cx, monkeypatch):
    # evento previo del MISMO post (con la llave vieja 'ig:') → se actualiza, no duplica
    bid = _banda(cx)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Algo",
              fecha_evento="2026-06-01", source_post_id="ig:ABC123")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "Otro Titulo", "tipo": "album", "fecha": "2026-06-05"})
    res = dr.detectar(cx, [_post(bid, shortcode="ABC123")])
    assert len(_eventos(cx)) == 1                 # una sola fila (merge sobre la vieja)
    assert _eventos(cx)[0]["titulo"] == "Otro Titulo"
    assert res["releases_nuevos"] == 1


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


# ---------- merge: post flyer + caption de release = UNA sola fila ----------

def test_merge_no_duplica_evento_del_post(cx, monkeypatch):
    bid = _banda(cx, "Duck Fizz")
    # classify ya creó un evento flyer de ESE post (source_post_id = shortcode bare)
    db.insert(cx, "events", band_id=bid, tipo="flyer",
              source_post_id="DZVaOLPFob5", status="nuevo")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "A Ciegas", "tipo": "sencillo",
        "fecha": "2026-06-19"})
    res = dr.detectar(cx, [_post(bid, shortcode="DZVaOLPFob5",
                                 caption="A Ciegas próximo sencillo", fecha="2026-06-08")])
    rel = db.rows(cx, "SELECT * FROM events WHERE band_id=? AND tipo='release'", (bid,))
    assert len(rel) == 1                       # NO se crea una fila paralela
    assert rel[0]["titulo"] == "A Ciegas"      # se actualizó el flyer existente
    assert rel[0]["fecha_evento"] == "2026-06-19"
    assert rel[0]["source_post_id"] == "DZVaOLPFob5"   # llave unificada (sin ig:)
    assert res["releases_nuevos"] == 1


def test_segunda_corrida_no_duplica(cx, monkeypatch):
    bid = _banda(cx, "Duck Fizz")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "A Ciegas", "tipo": "sencillo", "fecha": "2026-06-19"})
    post = _post(bid, shortcode="DZVaOLPFob5", caption="A Ciegas")
    dr.detectar(cx, [post])
    dr.detectar(cx, [post])  # otra vez
    rel = db.rows(cx, "SELECT * FROM events WHERE band_id=? AND tipo='release'", (bid,))
    assert len(rel) == 1


def test_detectar_devuelve_lista_de_nuevos(cx, monkeypatch):
    bid = _banda(cx, "Duck Fizz")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "A Ciegas", "tipo": "sencillo", "fecha": "2026-06-19"})
    res = dr.detectar(cx, [_post(bid, shortcode="X1", caption="A Ciegas")])
    assert res["nuevos"] == [{"banda": "Duck Fizz", "titulo": "A Ciegas",
                              "fecha": "2026-06-19"}]


# ---------- limpieza de duplicados existentes ----------

def test_purgar_releases_dup_colapsa(cx):
    bid = _banda(cx, "Duck Fizz")
    # dos releases del mismo post/fecha: uno con título (ig:) y uno sin (bare)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="A Ciegas",
              fecha_evento="2026-06-19", source_post_id="ig:DZVaOLPFob5", status="nuevo")
    db.insert(cx, "events", band_id=bid, tipo="release", titulo=None,
              fecha_evento="2026-06-19", source_post_id="DZVaOLPFob5", status="nuevo")
    n = dr.purgar_releases_dup(cx)
    rel = db.rows(cx, "SELECT * FROM events WHERE band_id=? AND tipo='release'", (bid,))
    assert len(rel) == 1 and rel[0]["titulo"] == "A Ciegas"  # conserva el que tiene título
    assert n == 1


def test_release_guarda_flyer_path_servible(cx, monkeypatch):
    """El cover queda como flyer_path local → la GUI lo sirve por /flyer/{id}."""
    bid = _banda(cx, "Duck Fizz")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "A Ciegas", "tipo": "sencillo", "fecha": "2099-06-19"})
    dr.detectar(cx, [_post(bid, shortcode="Z1", caption="A Ciegas",
                           path="data/photos/duckfizz/Z1_0.jpg")])
    ev = db.rows(cx, "SELECT * FROM events WHERE band_id=? AND tipo='release'", (bid,))[0]
    assert ev["flyer_path"] == "data/photos/duckfizz/Z1_0.jpg"  # servible por /flyer/{id}


# ---------- shows por caption (independiente de la imagen) ----------

def test_show_por_caption_crea_evento_fecha(cx, monkeypatch):
    bid = _banda(cx, "Angel")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": False, "es_show": True, "titulo": "La 4T Del Perreo",
        "fecha": "2026-06-10", "lugar": "Foro X", "ciudad": "Guadalajara"})
    res = dr.detectar(cx, [_post(bid, shortcode="DZLcf0Rkans",
                                 caption="Miércoles 10 de junio 7:30pm", path="p/x.jpg")])
    ev = db.rows(cx, "SELECT * FROM events WHERE band_id=?", (bid,))
    assert len(ev) == 1
    assert ev[0]["tipo"] == "fecha"
    assert ev[0]["fecha_evento"] == "2026-06-10"
    assert ev[0]["lugar"] == "Foro X" and ev[0]["ciudad"] == "Guadalajara"
    assert ev[0]["source_post_id"] == "DZLcf0Rkans"
    assert ev[0]["flyer_path"] == "p/x.jpg"  # servible por /flyer/{id}
    assert res["releases_nuevos"] == 1  # cuenta como evento detectado


def test_show_no_pisa_evento_flyer_existente(cx, monkeypatch):
    bid = _banda(cx, "Angel")
    # classify ya hizo el evento flyer de ese post → parse_events lo maneja
    db.insert(cx, "events", band_id=bid, tipo="flyer", source_post_id="ABC", status="nuevo")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": False, "es_show": True, "fecha": "2026-06-10", "lugar": "X"})
    dr.detectar(cx, [_post(bid, shortcode="ABC")])
    ev = db.rows(cx, "SELECT * FROM events WHERE band_id=?", (bid,))
    assert len(ev) == 1 and ev[0]["tipo"] == "flyer"  # no lo tocó


def test_caption_normal_ni_show_ni_release(cx, monkeypatch):
    bid = _banda(cx)
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": False, "es_show": False})
    dr.detectar(cx, [_post(bid)])
    assert _eventos(cx) == []


# ---------- backfill: re-analiza posts con fotos pero sin evento ----------

def test_backfill_recupera_post_sin_evento(cx, monkeypatch):
    from datetime import datetime
    bid = _banda(cx, "Angel")
    hoy = datetime(2026, 6, 9)
    # post ingerido (foto) pero SIN evento
    db.insert(cx, "photos", band_id=bid, path="data/photos/angel/DZL_0.jpg",
              source_post_id="DZLcf0Rkans", caption_original="Estreno EP 10 junio",
              fecha="2026-06-08")
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: {
        "es_release": True, "titulo": "La 4T", "tipo": "album", "fecha": "2026-06-10"})
    n = dr.backfill_eventos(cx, dias=30, hoy=hoy)
    rel = db.rows(cx, "SELECT * FROM events WHERE band_id=? AND tipo='release'", (bid,))
    assert len(rel) == 1 and rel[0]["titulo"] == "La 4T"
    assert n["releases_nuevos"] >= 1


def test_backfill_ignora_posts_con_evento(cx, monkeypatch):
    from datetime import datetime
    bid = _banda(cx, "Angel")
    hoy = datetime(2026, 6, 9)
    db.insert(cx, "photos", band_id=bid, path="p/Y_0.jpg", source_post_id="YA",
              caption_original="algo", fecha="2026-06-08")
    db.insert(cx, "events", band_id=bid, tipo="flyer", source_post_id="YA", status="nuevo")
    llamado = []
    monkeypatch.setattr(dr, "_llm_release", lambda cap, f: llamado.append(1) or {"es_release": False})
    dr.backfill_eventos(cx, dias=30, hoy=hoy)
    assert llamado == []  # no re-analiza el que ya tiene evento
