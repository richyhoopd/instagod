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
