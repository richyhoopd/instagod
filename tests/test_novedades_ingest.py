"""Tests del modo novedades de la ingesta IG (Frente A).

Red 100% mockeada: fetch_posts, el fetch de perfil y la descarga de imagen se
monkeypatchean; la DB vive en tmp_path. Spec en
docs/superpowers/specs/2026-06-07-fetch-incremental-design.md (Frente A).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import db, ingest_ig


def _pool(tmp_path: Path, *cuentas: dict) -> Path:
    """Escribe un pool de cuentas scraper en tmp y devuelve la ruta."""
    p = tmp_path / "ig_accounts.json"
    if not cuentas:
        cuentas = ({"label": "t", "sessionid": "s", "ua": "u", "quemada_hasta": None},)
    p.write_text(json.dumps(list(cuentas)), encoding="utf-8")
    return p


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
    """Mockea descarga, delays, PHOTOS_DIR, un pool de 1 cuenta sana y la sesión."""
    monkeypatch.setattr(ingest_ig, "_download", lambda session, url, dest: dest.write_bytes(b"x") or True)
    monkeypatch.setattr(ingest_ig, "_sleep", lambda: None)
    # photos_dir bajo BASE_DIR para que path.relative_to(BASE_DIR) funcione
    monkeypatch.setattr(ingest_ig.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(ingest_ig.config, "resolve_photos_dir", lambda: tmp_path / "photos")
    # Pool por defecto: 1 cuenta sana en JSON real; sesión dummy (sin red).
    pool = _pool(tmp_path)
    monkeypatch.setattr(ingest_ig.config, "resolve_ig_accounts_path", lambda: pool)
    monkeypatch.setattr(ingest_ig, "get_session", lambda cuenta=None: object())
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

    ingest_ig.novedades(_cx=cx)
    assert perfil_calls == []


# ---------- banda que falla (NO rate-limit) no tumba la corrida ----------

def test_banda_fallida_continua(cx, mock_red, monkeypatch) -> None:
    _band(cx, "rota", ig_user_id="111")
    bid_ok = _band(cx, "buena", ig_user_id="222")

    def fake_posts(s, uid, count):
        if uid == "111":
            raise LookupError("IG no devolvió datos")  # fallo aislado, no 401/429
        return [_post("OK1")]

    monkeypatch.setattr(ingest_ig, "fetch_posts", fake_posts)
    monkeypatch.setattr(ingest_ig, "fetch_profile", lambda s, h: {"id": "?"})

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

    res = ingest_ig.novedades(handles=["scrapeada", "nueva"], _cx=cx)
    assert revisadas == ["111"]  # nueva no entra aunque se pida explícita
    assert res["bandas_revisadas"] == 1


# ---------- scraped_at se actualiza ----------

def test_actualiza_scraped_at(cx, mock_red, monkeypatch) -> None:
    bid = _band(cx, "banda", ig_user_id="111")
    monkeypatch.setattr(ingest_ig, "fetch_posts", lambda s, uid, count: [_post("N1")])
    monkeypatch.setattr(ingest_ig, "fetch_profile", lambda s, h: {"id": "111"})

    ingest_ig.novedades(_cx=cx)
    assert db.get(cx, "bands", bid)["scraped_at"] != "2026-06-01T10:00:00"


# ---------- rotación por antigüedad (tope por corrida) ----------

def test_tope_revisa_las_mas_viejas(cx, mock_red, monkeypatch) -> None:
    # 4 bandas con scraped_at distinto; tope 2 → solo las 2 MÁS VIEJAS
    for h, fecha, uid in [("vieja", "2026-06-01", "1"), ("media", "2026-06-03", "2"),
                          ("fresca", "2026-06-05", "3"), ("muy_vieja", "2026-05-20", "4")]:
        bid = db.insert(cx, "bands", nombre=h, ig_handle=h, activa=1)
        db.update(cx, "bands", bid, scraped_at=fecha, ig_user_id=uid)
    revisadas = []
    monkeypatch.setattr(ingest_ig, "fetch_posts",
                        lambda s, uid, count: revisadas.append(uid) or [])

    res = ingest_ig.novedades(limite=2, _cx=cx)
    assert res["bandas_revisadas"] == 2
    assert revisadas == ["4", "1"]  # muy_vieja (may-20) y vieja (jun-01)
    assert res["pendientes"] == 2


def test_handles_explicitos_ignoran_el_tope(cx, mock_red, monkeypatch) -> None:
    for h, uid in [("a", "1"), ("b", "2"), ("c", "3")]:
        bid = db.insert(cx, "bands", nombre=h, ig_handle=h, activa=1)
        db.update(cx, "bands", bid, scraped_at="2026-06-01", ig_user_id=uid)
    revisadas = []
    monkeypatch.setattr(ingest_ig, "fetch_posts",
                        lambda s, uid, count: revisadas.append(uid) or [])

    res = ingest_ig.novedades(handles=["a", "b", "c"], limite=1, _cx=cx)
    assert res["bandas_revisadas"] == 3  # explícito = intención, sin tope


# ---------- pool agotado corta la corrida ----------

def test_pool_agotado_corta(cx, mock_red, monkeypatch) -> None:
    # 1 sola cuenta (la default de mock_red); el feed siempre da 401
    for i in range(4):
        bid = db.insert(cx, "bands", nombre=f"b{i}", ig_handle=f"b{i}", activa=1)
        db.update(cx, "bands", bid, scraped_at=f"2026-06-0{i+1}", ig_user_id=str(i))
    monkeypatch.setattr(ingest_ig, "fetch_posts",
                        lambda s, uid, count: (_ for _ in ()).throw(
                            ingest_ig.IngestRateLimited("HTTP 401")))

    res = ingest_ig.novedades(limite=4, _cx=cx)
    assert res["cortado_por_bloqueo"] is True
    assert res["bandas_revisadas"] == 1   # la 1ª quema la única cuenta → pool agotado
    assert res["pendientes"] == 4         # ninguna se revisó


# ---------- rotación a media corrida: una cuenta se quema, sigue con la otra ----------

def test_rotacion_quema_una_sigue_con_otra(cx, mock_red, monkeypatch, tmp_path) -> None:
    # pool de 2 cuentas sanas
    pool = _pool(tmp_path,
                 {"label": "a", "sessionid": "sa", "ua": "ua", "quemada_hasta": None},
                 {"label": "b", "sessionid": "sb", "ua": "ub", "quemada_hasta": None})
    monkeypatch.setattr(ingest_ig.config, "resolve_ig_accounts_path", lambda: pool)
    # get_session devuelve un objeto que identifica la cuenta activa
    monkeypatch.setattr(ingest_ig, "get_session", lambda cuenta=None: cuenta["label"])

    for i in range(2):
        bid = db.insert(cx, "bands", nombre=f"b{i}", ig_handle=f"b{i}", activa=1)
        db.update(cx, "bands", bid, scraped_at=f"2026-06-0{i+1}", ig_user_id=str(i))

    # con la cuenta "a" el feed da 401; con "b" funciona
    def fake(sess, uid, count):
        if sess == "a":
            raise ingest_ig.IngestRateLimited("HTTP 401")
        return [_post(f"P{uid}")]

    monkeypatch.setattr(ingest_ig, "fetch_posts", fake)

    res = ingest_ig.novedades(limite=2, _cx=cx)
    assert res["cortado_por_bloqueo"] is False
    assert res["bandas_revisadas"] == 2
    assert res["fotos_nuevas"] == 2  # ambas bandas procesadas con la cuenta "b"
    # "a" quedó marcada en reposo en el JSON, "b" sigue sana
    from src import ig_accounts
    cuentas = {c["label"]: c for c in ig_accounts.cargar(pool)}
    assert cuentas["a"]["quemada_hasta"] is not None
    assert cuentas["b"]["quemada_hasta"] is None


