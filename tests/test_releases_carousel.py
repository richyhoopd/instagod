"""Carrusel de música nueva: parse de badge, chunks de 4, caption con tags."""
from __future__ import annotations

from src.generate_agenda import _caption_releases, _chunks, _parse_titulo


def test_parse_titulo_badge() -> None:
    assert _parse_titulo("Nuevo Sencillo (sencillo)") == ("Nuevo Sencillo", "Sencillo")
    assert _parse_titulo("Gran Disco (álbum)") == ("Gran Disco", "Álbum")
    assert _parse_titulo("Yorke | Parsons (Sesiones Bilbao) (live session)") \
        == ("Yorke | Parsons (Sesiones Bilbao)", "Live session")
    assert _parse_titulo("Sin Sufijo") == ("Sin Sufijo", "Estreno")
    assert _parse_titulo(None) == ("", "Estreno")


def test_chunks_de_cuatro() -> None:
    assert [len(c) for c in _chunks(list(range(9)), 4)] == [4, 4, 1]


def test_caption_releases_etiqueta_a_todos() -> None:
    evs = [
        {"fecha_evento": "2026-06-04", "banda_nombre": "a l a m e d a",
         "banda_handle": "alammedda", "titulo": "Yorke | Parsons (live session)"},
        {"fecha_evento": "2026-06-05", "banda_nombre": "kabala",
         "banda_handle": "kabala_oficial", "titulo": "X (sencillo)"},
        {"fecha_evento": "2026-06-05", "banda_nombre": "kabala",  # repetida → 1 tag
         "banda_handle": "kabala_oficial", "titulo": "Y (sencillo)"},
    ]
    cap = _caption_releases(evs, "semanal", omitidos=2)
    assert "@alammedda" in cap and "@kabala_oficial" in cap
    assert cap.count("@kabala_oficial") == 1   # tags únicos, en bloque final
    assert "• 4 jun — a l a m e d a" in cap
    assert "+2 lanzamientos más" in cap


def test_marcar_anunciados(tmp_path) -> None:
    from src import db
    from src.generate_agenda import _marcar_anunciados
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala")
    e1 = db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-01", status="nuevo")
    e2 = db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-06-02", status="anunciado")
    n = _marcar_anunciados(cx, [{"id": e1, "status": "nuevo"}, {"id": e2, "status": "anunciado"}])
    assert n == 1  # el ya-anunciado no se vuelve a tocar
    rows = db.rows(cx, "SELECT status FROM events ORDER BY id")
    assert [r["status"] for r in rows] == ["anunciado", "anunciado"]
