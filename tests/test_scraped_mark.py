"""Tests de la marca de scrapeo: ingest solo baja bandas nuevas por default."""
from __future__ import annotations

from unittest.mock import patch

from src import db, ingest_ig


def _band(cx, handle, scraped=False):
    bid = db.insert(cx, "bands", nombre=handle, ig_handle=handle, activa=1)
    if scraped:
        db.update(cx, "bands", bid, scraped_at="2026-06-01T10:00:00")
    return bid


def test_default_solo_nuevas(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    _band(cx, "vieja", scraped=True)
    _band(cx, "nueva", scraped=False)
    cx.close()

    procesadas = []

    def fake_ingest_band(session, cx, band, max_posts):
        procesadas.append(band["ig_handle"])
        return 0

    with patch.object(ingest_ig, "get_session", return_value=type("S", (), {})()), \
         patch.object(ingest_ig, "ingest_band", side_effect=fake_ingest_band), \
         patch.object(ingest_ig, "_sleep"), \
         patch.object(db, "connect", return_value=db.connect(tmp_path / "t.db")):
        ingest_ig.ingest()  # sin handles, rescan=False
    assert procesadas == ["nueva"]  # la vieja se saltó


def test_rescan_incluye_scrapeadas(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    _band(cx, "vieja", scraped=True)
    _band(cx, "nueva", scraped=False)
    cx.close()

    procesadas = []
    with patch.object(ingest_ig, "get_session", return_value=type("S", (), {})()), \
         patch.object(ingest_ig, "ingest_band",
                      side_effect=lambda s, c, b, m: procesadas.append(b["ig_handle"]) or 0), \
         patch.object(ingest_ig, "_sleep"), \
         patch.object(db, "connect", return_value=db.connect(tmp_path / "t.db")):
        ingest_ig.ingest(rescan=True)
    assert set(procesadas) == {"vieja", "nueva"}


def test_handles_explicitos_ignoran_marca(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    _band(cx, "vieja", scraped=True)
    cx.close()

    procesadas = []
    with patch.object(ingest_ig, "get_session", return_value=type("S", (), {})()), \
         patch.object(ingest_ig, "ingest_band",
                      side_effect=lambda s, c, b, m: procesadas.append(b["ig_handle"]) or 0), \
         patch.object(ingest_ig, "_sleep"), \
         patch.object(db, "connect", return_value=db.connect(tmp_path / "t.db")):
        ingest_ig.ingest(handles=["vieja"])  # explícito → se scrapea aunque ya esté
    assert procesadas == ["vieja"]
