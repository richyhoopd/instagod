"""Cron de releases: registro con detalle y formato del aviso de Telegram."""
from __future__ import annotations

from src import db
from src.enrich_spotify import _registrar_releases


class _FakeSpotify:
    """Devuelve un catálogo fijo; suficiente para probar inserción + dedupe."""

    def __init__(self, albums):
        self._albums = albums

    def artist_albums(self, artist_id, include_groups="", limit=10):
        return {"items": self._albums}


def _album(aid: str, nombre: str, fecha: str, tipo: str = "single"):
    return {"id": aid, "name": nombre, "release_date": fecha,
            "album_type": tipo, "images": [{"url": f"http://img/{aid}.jpg"}]}


def test_registrar_releases_devuelve_detalle_y_dedupea(tmp_path) -> None:
    from datetime import datetime
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala")
    hoy = datetime.now().strftime("%Y-%m-%d")
    sp = _FakeSpotify([_album("a1", "Nuevo Sencillo", hoy),
                       _album("a2", "Disco Viejo", "2019-01-01")])

    nuevos = _registrar_releases(sp, cx, bid, "spotify-id-x")
    assert nuevos == [{"titulo": "Nuevo Sencillo (sencillo)", "fecha": hoy,
                       "cover_url": "http://img/a1.jpg"}]
    # segunda corrida: dedupe por id de álbum
    assert _registrar_releases(sp, cx, bid, "spotify-id-x") == []


def test_check_mejora_covers_ig(tmp_path, monkeypatch) -> None:
    """El cron diario sube las portadas IG a artwork oficial vía Deezer."""
    from src import check_releases, deezer
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="CCÑA", activa=1, deezer_id="111")
    eid = db.insert(cx, "events", band_id=bid, tipo="release",
                    titulo="La 4T Del Perreo", fecha_evento="2026-06-10",
                    cover_url="data/photos/b/a_0.jpg", flyer_path="data/photos/b/a_0.jpg",
                    source_post_id="ABC", status="nuevo")
    monkeypatch.setattr(deezer, "albums", lambda aid: [
        {"album_id": "A1", "titulo": "La 4T Del Perreo", "record_type": "single",
         "release_date": "2026-06-10", "cover_url": "https://cdn/c.jpg"}])
    conectar = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: conectar(tmp_path / "t.db"))

    check_releases.check(dry_run=True)
    assert db.get(cx, "events", eid)["cover_url"] == "https://cdn/c.jpg"
    cx.close()


def test_formato_mensaje() -> None:
    from src.check_releases import formato_mensaje
    nuevos = [
        {"banda": "Kabala", "titulo": "Nuevo Sencillo (sencillo)", "fecha": "2026-06-05"},
        {"banda": "Los Baxters", "titulo": "Disco (álbum)", "fecha": "2026-06-01"},
    ]
    msg = formato_mensaje(nuevos)
    assert "🎵" in msg and "Kabala" in msg and "Disco (álbum)" in msg
    assert formato_mensaje([]) == ""


def test_formato_mensaje_trunca() -> None:
    from src.check_releases import formato_mensaje
    nuevos = [{"banda": f"Banda{i}", "titulo": f"Disco {i} (álbum)", "fecha": "2026-06-01"}
              for i in range(50)]
    msg = formato_mensaje(nuevos)
    assert len(msg) < 4096
    assert "y 20 más" in msg
