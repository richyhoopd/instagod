"""Tests del cliente Deezer, el match banda→deezer y el registro de releases.

Sin red: el HTTP de Deezer se mockea. La DB vive en tmp_path.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src import db, deezer, deezer_match


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def json(self):
        return self._p


# ---------- migración ----------

def test_migracion_deezer(cx) -> None:
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(bands)")}
    assert {"deezer_id", "deezer_status"} <= cols
    assert {"deezer_id", "deezer_status"} <= db.TABLES["bands"]
    # backfill: con deezer_id → ok
    bid = db.insert(cx, "bands", nombre="X", deezer_id="999")
    db.init_db(cx)
    assert db.get(cx, "bands", bid)["deezer_status"] == "ok"


# ---------- cliente ----------

def test_buscar_artista(cx, monkeypatch) -> None:
    payload = {"data": [
        {"id": 111, "name": "Kabala", "nb_album": 3, "nb_fan": 1200,
         "link": "https://deezer.com/artist/111", "picture_xl": "u"},
    ]}
    monkeypatch.setattr(deezer, "_get", lambda url, params=None: _Resp(payload))
    cands = deezer.buscar_artista("Kabala")
    assert cands[0]["id"] == "111" and cands[0]["nombre"] == "Kabala"
    assert cands[0]["nb_album"] == 3


def test_albums_pagina_y_parsea(cx, monkeypatch) -> None:
    pag1 = {"data": [
        {"id": 1, "title": "Disco (sencillo)", "record_type": "single",
         "release_date": "2026-06-01", "cover_xl": "c1"}],
        "next": "https://api.deezer.com/artist/111/albums?index=1"}
    pag2 = {"data": [
        {"id": 2, "title": "Álbum Grande", "record_type": "album",
         "release_date": "2024-01-01", "cover_xl": "c2"}]}
    urls = []

    def fake_get(url, params=None):
        urls.append(url)
        return _Resp(pag1 if len(urls) == 1 else pag2)

    monkeypatch.setattr(deezer, "_get", fake_get)
    monkeypatch.setattr(deezer, "_throttle", lambda: None)
    albums = deezer.albums("111")
    assert [a["album_id"] for a in albums] == ["1", "2"]
    assert albums[0]["record_type"] == "single" and albums[0]["release_date"] == "2026-06-01"
    assert albums[0]["cover_url"] == "c1"
    assert len(urls) == 2  # siguió el `next`


def test_get_http_error(cx, monkeypatch) -> None:
    monkeypatch.setattr(deezer, "_get", lambda url, params=None: _Resp({}, status=500))
    with pytest.raises(deezer.DeezerError):
        deezer.buscar_artista("X")


# ---------- cross-check de discografía (precisión) ----------

def test_comparten_release_titulo_y_anio() -> None:
    spot = {("nuevo sencillo", 2026), ("primer disco", 2024)}
    # mismo título + mismo año → comparten
    assert deezer_match.comparten_release(spot, {("nuevo sencillo", 2026)})
    # mismo título, año ±1 (Deezer a veces difiere) → comparten
    assert deezer_match.comparten_release(spot, {("primer disco", 2025)})
    # mismo título pero año lejano → NO
    assert not deezer_match.comparten_release(spot, {("primer disco", 2020)})
    # títulos distintos (la Kabala falsa) → NO
    assert not deezer_match.comparten_release(spot, {("caminos de gloria", 2025)})


# ---------- match preciso ----------

class _FakeSp:
    def __init__(self, titulos_anios):
        self._d = titulos_anios

    def artist_albums(self, artist_id, **kw):
        items = [{"name": t, "release_date": f"{y}-01-01"} for t, y in self._d]
        return {"items": items}


def test_resolver_preciso_confirma_por_spotify(cx, monkeypatch) -> None:
    # banda con spotify_id; el candidato CORRECTO comparte discografía
    bid = db.insert(cx, "bands", nombre="Kabala", activa=1, spotify_id="SP1")
    cands = [
        {"id": "FALSA", "nombre": "Kabala", "nb_album": 22, "nb_fan": 9999, "link": ""},
        {"id": "REAL", "nombre": "Kabala", "nb_album": 2, "nb_fan": 30, "link": ""},
    ]
    disco = {"FALSA": [{"album_id": "x", "titulo": "Caminos De Gloria",
                        "release_date": "2025-07-15", "record_type": "album", "cover_url": ""}],
             "REAL": [{"album_id": "y", "titulo": "Nuestro Demo",
                       "release_date": "2026-02-01", "record_type": "ep", "cover_url": ""}]}
    monkeypatch.setattr(deezer_match.deezer, "buscar_artista", lambda n: cands)
    monkeypatch.setattr(deezer_match.deezer, "albums", lambda aid: disco[aid])
    monkeypatch.setattr(deezer_match.deezer, "registrar_releases", lambda *a, **k: [])
    # Spotify de la banda real lista "Nuestro Demo" 2026 → coincide con REAL, no FALSA
    sp = _FakeSp({("Nuestro Demo", 2026)})

    res = deezer_match.resolver_preciso(cx, sp=sp)
    b = db.get(cx, "bands", bid)
    assert b["deezer_id"] == "REAL"      # NO la falsa de 22 álbumes
    assert b["deezer_status"] == "ok"
    assert res["ok_spotify"] == 1


def test_resolver_preciso_rechaza_si_no_comparte(cx, monkeypatch) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala", activa=1, spotify_id="SP1")
    cands = [{"id": "FALSA", "nombre": "Kabala", "nb_album": 22, "nb_fan": 9999, "link": ""}]
    monkeypatch.setattr(deezer_match.deezer, "buscar_artista", lambda n: cands)
    monkeypatch.setattr(deezer_match.deezer, "albums",
                        lambda aid: [{"album_id": "x", "titulo": "Caminos De Gloria",
                                      "release_date": "2025-07-15", "record_type": "album",
                                      "cover_url": ""}])
    reg = []
    monkeypatch.setattr(deezer_match.deezer, "registrar_releases",
                        lambda *a, **k: reg.append(a) or [])
    sp = _FakeSp({("Otra Cosa", 2024)})  # no comparte nada con la Kabala falsa

    res = deezer_match.resolver_preciso(cx, sp=sp)
    b = db.get(cx, "bands", bid)
    assert b["deezer_id"] is None             # NO se adivinó
    assert b["deezer_status"] == "pendiente"  # queda para revisión manual
    assert res["sin_confirmar"] == 1
    assert reg == []                          # nunca registró releases


def test_resolver_preciso_confirma_por_link_bio(cx, monkeypatch) -> None:
    bid = db.insert(cx, "bands", nombre="Quien Sos", activa=1,
                    link_externo="https://beacons.ai/quiensos")
    monkeypatch.setattr(deezer_match, "deezer_id_de_link", lambda url: "777")
    monkeypatch.setattr(deezer_match.deezer, "registrar_releases", lambda *a, **k: [])
    res = deezer_match.resolver_preciso(cx, sp=None)
    b = db.get(cx, "bands", bid)
    assert b["deezer_id"] == "777" and b["deezer_status"] == "ok"
    assert res["ok_link"] == 1


def test_resolver_preciso_excluye_no_esta(cx, monkeypatch) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala", activa=1)
    db.update(cx, "bands", bid, deezer_status="no_esta")
    llamadas = []
    monkeypatch.setattr(deezer_match, "deezer_id_de_link", lambda url: None)
    monkeypatch.setattr(deezer_match.deezer, "buscar_artista",
                        lambda n: llamadas.append(n) or [])
    deezer_match.resolver_preciso(cx, sp=None)
    assert llamadas == []


# ---------- purga de matches falsos ----------

def test_purgar_limpia_ids_y_releases(cx) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala", activa=1, deezer_id="FALSA")
    db.update(cx, "bands", bid, deezer_status="ok")
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Ajeno",
              fecha_evento="2025-07-15", source_post_id="dz:x", status="nuevo")
    # un release de OTRA fuente NO se debe borrar
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Propio",
              fecha_evento="2026-01-01", source_post_id="sp:y", status="nuevo")

    res = deezer_match.purgar(cx)
    b = db.get(cx, "bands", bid)
    assert b["deezer_id"] is None and b["deezer_status"] == "pendiente"
    sources = {r["source_post_id"] for r in db.rows(cx, "SELECT source_post_id FROM events")}
    assert "dz:x" not in sources and "sp:y" in sources
    assert res["bandas"] == 1 and res["releases"] == 1


# ---------- registro de releases + dedup ----------

def test_registrar_releases_crea_y_dedup_album(cx, monkeypatch) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala", activa=1, deezer_id="111")
    hoy = datetime(2026, 6, 8)
    albums = [
        {"album_id": "A1", "titulo": "Nuevo Sencillo", "record_type": "single",
         "release_date": "2026-06-05", "cover_url": "cov"},
        {"album_id": "A2", "titulo": "Viejo", "record_type": "album",
         "release_date": "2020-01-01", "cover_url": "c2"},  # fuera de ventana
    ]
    monkeypatch.setattr(deezer, "albums", lambda aid: albums)
    nuevos = deezer.registrar_releases(cx, bid, "111", hoy=hoy)
    assert len(nuevos) == 1
    ev = db.rows(cx, "SELECT * FROM events WHERE band_id=? AND tipo='release'", (bid,))
    assert len(ev) == 1
    assert ev[0]["source_post_id"] == "dz:A1"
    assert ev[0]["titulo"] == "Nuevo Sencillo" and ev[0]["cover_url"] == "cov"
    # segunda corrida: mismo álbum no se duplica
    assert deezer.registrar_releases(cx, bid, "111", hoy=hoy) == []


def test_registrar_releases_dedup_vs_spotify(cx, monkeypatch) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala", activa=1, deezer_id="111")
    hoy = datetime(2026, 6, 8)
    # release de Spotify ya existente, título similar y fecha cercana
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Nuevo Sencillo (sencillo)",
              fecha_evento="2026-06-04", source_post_id="sp:XYZ", status="nuevo")
    albums = [{"album_id": "A1", "titulo": "Nuevo Sencillo", "record_type": "single",
               "release_date": "2026-06-05", "cover_url": "cov"}]
    monkeypatch.setattr(deezer, "albums", lambda aid: albums)
    nuevos = deezer.registrar_releases(cx, bid, "111", hoy=hoy)
    assert nuevos == []  # Spotify ya lo tiene → no duplica
    assert len(db.rows(cx, "SELECT 1 FROM events WHERE band_id=?", (bid,))) == 1


def test_registrar_releases_lejano_si_inserta(cx, monkeypatch) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala", activa=1, deezer_id="111")
    hoy = datetime(2026, 6, 8)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Nuevo Sencillo",
              fecha_evento="2023-01-01", source_post_id="sp:OLD", status="nuevo")  # >30d
    albums = [{"album_id": "A1", "titulo": "Nuevo Sencillo", "record_type": "single",
               "release_date": "2026-06-05", "cover_url": "cov"}]
    monkeypatch.setattr(deezer, "albums", lambda aid: albums)
    nuevos = deezer.registrar_releases(cx, bid, "111", hoy=hoy)
    assert len(nuevos) == 1  # mismo título pero fecha lejana = release distinto
