"""Tests de Frente B: resolvedor de links + vista de matcheo manual (sin red)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import config
from src import db, spotify_match


# ---------- Fixtures HTML (páginas externas simuladas) ----------

HTML_CON_SPOTIFY = """
<html><head><title>Kabala</title></head><body>
  <a href="https://music.apple.com/kabala">Apple Music</a>
  <a href="https://open.spotify.com/artist/4Z8W4fKeB5YxbusRsdQVPb?si=abc">Spotify</a>
</body></html>
"""

HTML_SIN_SPOTIFY = """
<html><body>
  <a href="https://www.youtube.com/@kabala">YouTube</a>
  <a href="https://www.instagram.com/kabala">IG</a>
</body></html>
"""


def test_extraer_artist_id_de_html() -> None:
    assert spotify_match.extraer_artist_id(HTML_CON_SPOTIFY) == "4Z8W4fKeB5YxbusRsdQVPb"
    assert spotify_match.extraer_artist_id(HTML_SIN_SPOTIFY) is None
    assert spotify_match.extraer_artist_id("") is None


def test_es_link_resolvible() -> None:
    assert spotify_match.es_link_resolvible("https://linktr.ee/kabala")
    assert spotify_match.es_link_resolvible("https://distrokid.com/hyperfollow/kabala")
    assert spotify_match.es_link_resolvible("https://kabala.lnk.to/single")
    assert spotify_match.es_link_resolvible("https://ffm.to/kabala")
    assert spotify_match.es_link_resolvible("https://songwhip.com/kabala")
    assert spotify_match.es_link_resolvible("https://lnk.fi/kabala")  # linkfire short
    # no resolvibles
    assert not spotify_match.es_link_resolvible("https://instagram.com/kabala")
    assert not spotify_match.es_link_resolvible(None)
    assert not spotify_match.es_link_resolvible("")


# ---------- Resolvedor de links contra la DB ----------

@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "match.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _banda(cx, nombre, link=None, **extra):
    return db.insert(cx, "bands", nombre=nombre, link_externo=link, **extra)


def test_resolver_links_guarda_id_y_marca_ok(cx, monkeypatch) -> None:
    bid = _banda(cx, "Kabala", "https://linktr.ee/kabala")

    monkeypatch.setattr(spotify_match, "_get_html", lambda url: HTML_CON_SPOTIFY)
    # _registrar_releases hace red → mockeado (no es lo que probamos aquí)
    monkeypatch.setattr(spotify_match, "get_client", lambda: object())
    monkeypatch.setattr(spotify_match, "_registrar_releases", lambda sp, cx, bid, aid: [])

    res = spotify_match.resolver_links(cx)

    banda = db.get(cx, "bands", bid)
    assert banda["spotify_id"] == "4Z8W4fKeB5YxbusRsdQVPb"
    assert banda["spotify_status"] == "ok"
    assert res["resueltas"] == 1


def test_resolver_links_pagina_sin_link_sigue_pendiente(cx, monkeypatch) -> None:
    bid = _banda(cx, "Otra", "https://linktr.ee/otra")
    monkeypatch.setattr(spotify_match, "_get_html", lambda url: HTML_SIN_SPOTIFY)

    spotify_match.resolver_links(cx)

    banda = db.get(cx, "bands", bid)
    assert banda["spotify_id"] is None
    assert banda["spotify_status"] == "pendiente"


def test_resolver_links_pagina_rota_no_tira_la_corrida(cx, monkeypatch) -> None:
    rota = _banda(cx, "Rota", "https://linktr.ee/rota")
    buena = _banda(cx, "Buena", "https://linktr.ee/buena")

    def get_html(url):
        if "rota" in url:
            raise TimeoutError("timeout simulado")
        return HTML_CON_SPOTIFY

    monkeypatch.setattr(spotify_match, "_get_html", get_html)
    monkeypatch.setattr(spotify_match, "get_client", lambda: object())
    monkeypatch.setattr(spotify_match, "_registrar_releases", lambda *a: [])

    res = spotify_match.resolver_links(cx)

    assert db.get(cx, "bands", rota)["spotify_status"] == "pendiente"
    assert db.get(cx, "bands", buena)["spotify_status"] == "ok"
    assert res["resueltas"] == 1


def test_resolver_links_ignora_no_pendientes_y_sin_link(cx, monkeypatch) -> None:
    # 'ok' ya resuelta, 'no_esta' descartada y una activa sin link resolvible
    _banda(cx, "YaOk", "https://linktr.ee/x", spotify_status="ok", spotify_id="zzz")
    _banda(cx, "NoEsta", "https://linktr.ee/y", spotify_status="no_esta")
    _banda(cx, "SinLink", "https://instagram.com/z")
    inactiva = _banda(cx, "Inactiva", "https://linktr.ee/w", activa=0)

    llamadas = []
    monkeypatch.setattr(spotify_match, "_get_html",
                        lambda url: llamadas.append(url) or HTML_SIN_SPOTIFY)

    res = spotify_match.resolver_links(cx)

    assert llamadas == []  # ninguna candidata válida → no se toca la red
    assert res["revisadas"] == 0
    assert db.get(cx, "bands", inactiva)["spotify_status"] == "pendiente"


# ---------- candidatos() (búsqueda en Spotify) ----------

class _SpFake:
    def __init__(self, items):
        self._items = items

    def search(self, q, type, limit, market):  # noqa: A002 — firma de spotipy
        return {"artists": {"items": self._items}}


def test_candidatos_top5() -> None:
    sp = _SpFake([
        {"id": "a1", "name": "Kabala"},
        {"id": "a2", "name": "Kabala Tribute"},
    ])
    cands = spotify_match.candidatos(sp, "Kabala")
    assert cands[0] == {"id": "a1", "nombre": "Kabala",
                        "url": "https://open.spotify.com/artist/a1"}
    assert len(cands) == 2


def test_candidatos_maneja_rate_limit() -> None:
    from spotipy import SpotifyException

    class _Sp429:
        def search(self, **kw):
            raise SpotifyException(429, -1, "rate", headers={"Retry-After": "1"})

    with pytest.raises(spotify_match.RateLimitado):
        spotify_match.candidatos(_Sp429(), "Kabala")


# ---------- enrich_spotify excluye no_esta ----------

def test_enrich_excluye_no_esta(tmp_path, monkeypatch) -> None:
    import contextlib

    from src import enrich_spotify

    db_path = tmp_path / "enrich.db"
    conn = db.connect(db_path)
    db.init_db(conn)
    db.insert(conn, "bands", nombre="Pendiente")
    db.insert(conn, "bands", nombre="Descartada", spotify_status="no_esta")
    conn.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    vistas = []
    monkeypatch.setattr(enrich_spotify, "get_client", lambda: object())
    monkeypatch.setattr(enrich_spotify, "spotify_lock", contextlib.nullcontext)
    monkeypatch.setattr(enrich_spotify, "enrich_band",
                        lambda sp, cx, band: vistas.append(band["nombre"]) or "ok")

    enrich_spotify.enrich()
    assert "Pendiente" in vistas
    assert "Descartada" not in vistas


# ---------- Vista /spotify ----------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "web.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)
    ids = {}
    ids["pend"] = db.insert(cx, "bands", nombre="BandaPendiente")
    ids["ok"] = db.insert(cx, "bands", nombre="BandaOk", spotify_status="ok",
                          spotify_id="zzz")
    cx.close()

    from web.app import app
    with TestClient(app) as c:
        c._ids = ids  # type: ignore[attr-defined]
        yield c


def test_vista_spotify_lista_pendientes_con_candidatos(client, monkeypatch) -> None:
    from web import app as webapp

    monkeypatch.setattr(webapp.spotify_match, "get_client", lambda: object())
    monkeypatch.setattr(webapp.spotify_match, "candidatos",
                        lambda sp, nombre: [{"id": "cand1", "nombre": nombre,
                                             "url": "https://open.spotify.com/artist/cand1"}])

    resp = client.get("/spotify")
    assert resp.status_code == 200
    assert "BandaPendiente" in resp.text
    assert "cand1" in resp.text
    # la banda ya 'ok' no debe aparecer en la lista de pendientes
    assert "BandaOk" not in resp.text


def test_vista_spotify_search_caido_carga_con_error(client, monkeypatch) -> None:
    from web import app as webapp

    def boom():
        raise RuntimeError("Spotify caído")

    monkeypatch.setattr(webapp.spotify_match, "get_client", boom)
    resp = client.get("/spotify")
    assert resp.status_code == 200
    assert "BandaPendiente" in resp.text  # la página carga igual


def test_elegir_marca_ok_y_registra_releases(client, monkeypatch) -> None:
    from web import app as webapp

    monkeypatch.setattr(webapp.spotify_match, "get_client", lambda: object())
    registrados = []
    monkeypatch.setattr(webapp.spotify_match, "_registrar_releases",
                        lambda sp, cx, bid, aid: registrados.append(aid) or [])

    bid = client._ids["pend"]
    resp = client.post(f"/spotify/{bid}/elegir", data={"spotify_id": "elegidoXYZ"})
    assert resp.status_code == 200

    cx = db.connect()
    banda = db.get(cx, "bands", bid)
    cx.close()
    assert banda["spotify_id"] == "elegidoXYZ"
    assert banda["spotify_status"] == "ok"
    assert registrados == ["elegidoXYZ"]


def test_no_esta_marca_estado(client) -> None:
    bid = client._ids["pend"]
    resp = client.post(f"/spotify/{bid}/no-esta")
    assert resp.status_code == 200
    cx = db.connect()
    banda = db.get(cx, "bands", bid)
    cx.close()
    assert banda["spotify_status"] == "no_esta"


def test_nav_tiene_link_spotify(client) -> None:
    resp = client.get("/spotify")
    assert 'href="/spotify"' in resp.text
