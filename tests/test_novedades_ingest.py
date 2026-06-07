"""Tests del modo novedades de la ingesta IG (Frente A).

Red 100% mockeada: fetch_posts, el fetch de perfil y la descarga de imagen se
monkeypatchean; la DB vive en tmp_path. Spec en
docs/superpowers/specs/2026-06-07-fetch-incremental-design.md (Frente A).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import db, ingest_ig


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _band(cx, handle, *, scraped=True, ig_user_id=None, activa=1):
    bid = db.insert(cx, "bands", nombre=handle, ig_handle=handle, activa=activa)
    fields = {}
    if scraped:
        fields["scraped_at"] = "2026-06-01T10:00:00"
    if ig_user_id:
        fields["ig_user_id"] = ig_user_id
    if fields:
        db.update(cx, "bands", bid, **fields)
    return bid


def _post(shortcode: str, *, taken_at: int = 1_700_000_000, caption: str = "hola") -> dict:
    """Item de feed mínimo (foto sencilla) como lo devuelve fetch_posts."""
    return {
        "code": shortcode,
        "media_type": ingest_ig._MEDIA_FOTO,
        "taken_at": taken_at,
        "caption": {"text": caption},
        "image_versions2": {"candidates": [{"url": f"https://cdn/{shortcode}.jpg"}]},
    }


@pytest.fixture()
def mock_red(monkeypatch, tmp_path):
    """Mockea descarga de imagen, delays y PHOTOS_DIR. Devuelve el contador de fetch_profile."""
    monkeypatch.setattr(ingest_ig, "_download", lambda session, url, dest: dest.write_bytes(b"x") or True)
    monkeypatch.setattr(ingest_ig, "_sleep", lambda: None)
    # photos_dir bajo BASE_DIR para que path.relative_to(BASE_DIR) funcione
    monkeypatch.setattr(ingest_ig.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ingest_ig.config, "resolve_photos_dir", lambda: tmp_path / "photos")
    return monkeypatch


# ---------- migración ----------

def test_migracion_ig_user_id(cx) -> None:
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(bands)")}
    assert "ig_user_id" in cols
    assert "ig_user_id" in db.TABLES["bands"]


# ---------- corte por post conocido ----------

def test_corte_en_post_conocido(cx, mock_red, monkeypatch) -> None:
    bid = _band(cx, "banda", ig_user_id="111")
    # el post más reciente ya está en photos → no debe bajar nada
    db.insert(cx, "photos", band_id=bid, path="x.jpg", source_post_id="SC1")

    fetch_calls = []
    monkeypatch.setattr(ingest_ig, "fetch_posts",
                        lambda s, uid, count: fetch_calls.append(uid) or [_post("SC1")])
    perfil_calls = []
    monkeypatch.setattr(ingest_ig, "fetch_profile",
                        lambda s, h: perfil_calls.append(h) or {"id": "111"})
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    res = ingest_ig.novedades(_cx=cx)
    assert res["bandas_revisadas"] == 1
    assert res["con_novedades"] == 0
    assert res["fotos_nuevas"] == 0
    assert res["posts_nuevos"] == []
    assert fetch_calls == ["111"]
    assert perfil_calls == []  # ig_user_id cacheado


# ---------- posts nuevos antes de uno conocido ----------

def test_solo_nuevos_se_insertan(cx, mock_red, monkeypatch) -> None:
    bid = _band(cx, "banda", ig_user_id="111")
    db.insert(cx, "photos", band_id=bid, path="x.jpg", source_post_id="VIEJO")

    # feed del más nuevo al más viejo: dos nuevos y luego el conocido
    feed = [_post("NEW2", taken_at=1_700_000_200, caption="cap2"),
            _post("NEW1", taken_at=1_700_000_100, caption="cap1"),
            _post("VIEJO", taken_at=1_700_000_000)]
    monkeypatch.setattr(ingest_ig, "fetch_posts", lambda s, uid, count: feed)
    monkeypatch.setattr(ingest_ig, "fetch_profile", lambda s, h: {"id": "111"})
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    res = ingest_ig.novedades(_cx=cx)
    assert res["fotos_nuevas"] == 2
    assert res["con_novedades"] == 1
    shortcodes = {p["shortcode"] for p in res["posts_nuevos"]}
    assert shortcodes == {"NEW1", "NEW2"}
    # VIEJO no se vuelve a bajar
    filas = db.rows(cx, "SELECT source_post_id, caption_original, fecha FROM photos "
                        "WHERE band_id = ? ORDER BY source_post_id", (bid,))
    nuevos = {f["source_post_id"]: f for f in filas if f["source_post_id"] != "VIEJO"}
    assert set(nuevos) == {"NEW1", "NEW2"}
    assert nuevos["NEW1"]["caption_original"] == "cap1"
    assert nuevos["NEW1"]["fecha"] is not None
    # el dict de salida trae caption/fecha/path
    p = next(p for p in res["posts_nuevos"] if p["shortcode"] == "NEW1")
    assert p["caption"] == "cap1" and p["fecha"] and p["path"]
    assert p["band_id"] == bid and p["ig_handle"] == "banda"


# ---------- caché de ig_user_id ----------

def test_sin_cache_llama_perfil_y_persiste(cx, mock_red, monkeypatch) -> None:
    bid = _band(cx, "banda", ig_user_id=None)  # sin caché

    perfil_calls = []
    monkeypatch.setattr(ingest_ig, "fetch_profile",
                        lambda s, h: perfil_calls.append(h) or {"id": "999"})
    fetch_calls = []
    monkeypatch.setattr(ingest_ig, "fetch_posts",
                        lambda s, uid, count: fetch_calls.append(uid) or [])
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    ingest_ig.novedades(_cx=cx)
    assert perfil_calls == ["banda"]
    assert fetch_calls == ["999"]
    assert db.get(cx, "bands", bid)["ig_user_id"] == "999"


def test_con_cache_no_llama_perfil(cx, mock_red, monkeypatch) -> None:
    _band(cx, "banda", ig_user_id="111")
    perfil_calls = []
    monkeypatch.setattr(ingest_ig, "fetch_profile",
                        lambda s, h: perfil_calls.append(h) or {"id": "x"})
    monkeypatch.setattr(ingest_ig, "fetch_posts", lambda s, uid, count: [])
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    ingest_ig.novedades(_cx=cx)
    assert perfil_calls == []


# ---------- banda que falla no tumba la corrida ----------

def test_banda_fallida_continua(cx, mock_red, monkeypatch) -> None:
    _band(cx, "rota", ig_user_id="111")
    bid_ok = _band(cx, "buena", ig_user_id="222")

    def fake_posts(s, uid, count):
        if uid == "111":
            raise ingest_ig.IngestRateLimited("HTTP 429")
        return [_post("OK1")]

    monkeypatch.setattr(ingest_ig, "fetch_posts", fake_posts)
    monkeypatch.setattr(ingest_ig, "fetch_profile", lambda s, h: {"id": "?"})
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    res = ingest_ig.novedades(_cx=cx)
    assert "rota" in res["fallidas"]
    assert res["bandas_revisadas"] == 2
    # la buena sí se procesó
    assert res["fotos_nuevas"] == 1
    assert db.rows(cx, "SELECT 1 FROM photos WHERE band_id = ?", (bid_ok,))


# ---------- bandas sin scrapear NO entran ----------

def test_sin_scrapear_no_entra(cx, mock_red, monkeypatch) -> None:
    _band(cx, "nueva", scraped=False, ig_user_id="111")
    revisadas = []
    monkeypatch.setattr(ingest_ig, "fetch_posts",
                        lambda s, uid, count: revisadas.append(uid) or [])
    monkeypatch.setattr(ingest_ig, "fetch_profile", lambda s, h: {"id": "111"})
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    res = ingest_ig.novedades(_cx=cx)
    assert res["bandas_revisadas"] == 0
    assert revisadas == []


def test_handles_explicitos_solo_scrapeadas(cx, mock_red, monkeypatch) -> None:
    _band(cx, "scrapeada", scraped=True, ig_user_id="111")
    _band(cx, "nueva", scraped=False, ig_user_id="222")
    revisadas = []
    monkeypatch.setattr(ingest_ig, "fetch_posts",
                        lambda s, uid, count: revisadas.append(uid) or [])
    monkeypatch.setattr(ingest_ig, "fetch_profile", lambda s, h: {"id": "?"})
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    res = ingest_ig.novedades(handles=["scrapeada", "nueva"], _cx=cx)
    assert revisadas == ["111"]  # nueva no entra aunque se pida explícita
    assert res["bandas_revisadas"] == 1


# ---------- scraped_at se actualiza ----------

def test_actualiza_scraped_at(cx, mock_red, monkeypatch) -> None:
    bid = _band(cx, "banda", ig_user_id="111")
    monkeypatch.setattr(ingest_ig, "fetch_posts", lambda s, uid, count: [_post("N1")])
    monkeypatch.setattr(ingest_ig, "fetch_profile", lambda s, h: {"id": "111"})
    monkeypatch.setattr(ingest_ig, "get_session", lambda: object())

    ingest_ig.novedades(_cx=cx)
    assert db.get(cx, "bands", bid)["scraped_at"] != "2026-06-01T10:00:00"
