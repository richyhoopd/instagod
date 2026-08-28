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


# ---------- dedupe cross-banda al render + créditos en caption ----------

def test_fusionar_duplicados_por_shortcode() -> None:
    import json

    from src.generate_agenda import _fusionar_duplicados
    evs = [
        {"id": 1, "band_id": 10, "source_post_id": "S1", "creditos": None,
         "cover_url": "http://x", "flyer_path": None},
        {"id": 2, "band_id": 20, "source_post_id": "S1", "creditos": None,
         "cover_url": "http://x", "flyer_path": None},
        {"id": 3, "band_id": 30, "source_post_id": "S2", "creditos": json.dumps([40]),
         "cover_url": "http://y", "flyer_path": None},
    ]
    unicos = _fusionar_duplicados(evs)
    assert [e["id"] for e in unicos] == [1, 3]
    assert json.loads(unicos[0]["creditos"]) == [20]


def test_fusionar_duplicados_por_phash(tmp_path, monkeypatch) -> None:
    import json

    import cv2
    import numpy as np

    import config
    from src.generate_agenda import _fusionar_duplicados
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    img = np.random.default_rng(3).integers(0, 255, (64, 64, 3), dtype=np.uint8)
    (tmp_path / "data").mkdir()
    cv2.imwrite(str(tmp_path / "data" / "f1.jpg"), img)
    cv2.imwrite(str(tmp_path / "data" / "f2.jpg"), img)
    evs = [
        {"id": 1, "band_id": 10, "source_post_id": "P1", "creditos": None,
         "cover_url": "data/f1.jpg", "flyer_path": "data/f1.jpg"},
        {"id": 2, "band_id": 20, "source_post_id": "P2", "creditos": json.dumps([50]),
         "cover_url": "data/f2.jpg", "flyer_path": "data/f2.jpg"},
    ]
    unicos = _fusionar_duplicados(evs)
    assert [e["id"] for e in unicos] == [1]
    assert json.loads(unicos[0]["creditos"]) == [20, 50]  # banda + sus créditos


def test_caption_releases_con_creditos() -> None:
    ev = {"fecha_evento": "2026-06-10", "banda_nombre": "CCÑA",
          "banda_handle": "angelxcecena", "titulo": "La 4T Del Perreo",
          "creditos_handles": ["cabronxxit0s", "staditche"]}
    cap = _caption_releases([ev], "semanal")
    assert "CCÑA: La 4T Del Perreo (con @cabronxxit0s @staditche)" in cap
    # los acreditados también van al bloque de tags del final
    assert cap.count("@staditche") == 2


def test_handles_creditos_resuelve_band_ids(tmp_path) -> None:
    import json

    from src import db
    from src.generate_agenda import _handles_creditos
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    b1 = db.insert(cx, "bands", nombre="A", ig_handle="a_oficial")
    b2 = db.insert(cx, "bands", nombre="B", ig_handle=None)  # sin handle → se omite
    evs = [{"id": 1, "creditos": json.dumps([b1, b2])}, {"id": 2, "creditos": None}]
    _handles_creditos(cx, evs)
    assert evs[0]["creditos_handles"] == ["a_oficial"]
    assert evs[1]["creditos_handles"] == []
    cx.close()
