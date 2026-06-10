"""Tests de la página Publicado: ig_posts, snapshots, vinculación y sugerencias.

No tocan red: la Graph API y el Sheet se inyectan/mockean. El spec vive en
docs/superpowers/specs/2026-06-07-pagina-publicado-design.md.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src import db, ig_insights


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _media_item(media_id: str = "M1", **extra) -> dict:
    """Nodo de /me/media como lo regresa la Graph API."""
    base = {
        "id": media_id,
        "media_type": "IMAGE",
        "media_url": "https://cdn.example/m1.jpg",
        "permalink": f"https://instagram.com/p/{media_id}/",
        "caption": "un caption",
        "timestamp": "2026-06-01T19:00:00+0000",
        "like_count": 10,
        "comments_count": 2,
    }
    base.update(extra)
    return base


# ---------- upsert de posts ----------

def test_upsert_post_idempotente(cx) -> None:
    pid = ig_insights.upsert_post(cx, _media_item())
    pid2 = ig_insights.upsert_post(cx, _media_item(like_count=25, comments_count=4))
    assert pid == pid2
    posts = db.rows(cx, "SELECT * FROM ig_posts")
    assert len(posts) == 1
    assert posts[0]["likes"] == 25 and posts[0]["comments"] == 4
    assert posts[0]["media_id"] == "M1"
    assert posts[0]["permalink"].endswith("/p/M1/")


def test_upsert_no_pisa_band_id(cx) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala")
    pid = ig_insights.upsert_post(cx, _media_item())
    db.update(cx, "ig_posts", pid, band_id=bid)  # asignación manual
    ig_insights.upsert_post(cx, _media_item(like_count=99))
    row = db.get(cx, "ig_posts", pid)
    assert row["band_id"] == bid and row["likes"] == 99


def test_upsert_video_usa_thumbnail(cx) -> None:
    pid = ig_insights.upsert_post(cx, _media_item(
        media_type="VIDEO", thumbnail_url="https://cdn.example/thumb.jpg"))
    assert db.get(cx, "ig_posts", pid)["thumbnail_url"] == "https://cdn.example/thumb.jpg"


# ---------- insights + snapshots ----------

def test_save_insights_y_snapshot_mismo_dia_actualiza(cx) -> None:
    pid = ig_insights.upsert_post(cx, _media_item())
    ig_insights.save_insights(cx, pid, {"reach": 100, "saved": 3, "shares": 1, "views": 200})
    ig_insights.snapshot(cx, pid, fecha="2026-06-07")
    ig_insights.save_insights(cx, pid, {"reach": 150, "saved": 5, "shares": 2, "views": 300})
    ig_insights.snapshot(cx, pid, fecha="2026-06-07")  # mismo día → actualiza
    snaps = db.rows(cx, "SELECT * FROM ig_metrics_snapshots ORDER BY fecha")
    assert len(snaps) == 1
    assert snaps[0]["reach"] == 150 and snaps[0]["views"] == 300

    ig_insights.snapshot(cx, pid, fecha="2026-06-08")  # otro día → fila nueva
    snaps = db.rows(cx, "SELECT * FROM ig_metrics_snapshots ORDER BY fecha")
    assert len(snaps) == 2

    post = db.get(cx, "ig_posts", pid)
    assert post["reach"] == 150 and post["saved"] == 5


# ---------- vinculación Sheet ↔ content_queue ↔ banda ----------

def test_link_bands_desde_sheet(cx) -> None:
    bid = db.insert(cx, "bands", nombre="Noisy Room")
    qid = db.insert(cx, "content_queue", band_id=bid, status=db.QUEUE_PUBLICADO,
                    sheet_row_id="7")
    pid = ig_insights.upsert_post(cx, _media_item("M1"))
    n = ig_insights.link_bands(cx, [{"id": 7, "ig_post_id": "M1"},
                                    {"id": 8, "ig_post_id": ""}])
    assert n == 1
    row = db.get(cx, "ig_posts", pid)
    assert row["band_id"] == bid and row["queue_id"] == qid


def test_link_bands_no_pisa_asignacion_manual(cx) -> None:
    b1 = db.insert(cx, "bands", nombre="Lefnes")
    b2 = db.insert(cx, "bands", nombre="Kabala")
    db.insert(cx, "content_queue", band_id=b1, status=db.QUEUE_PUBLICADO, sheet_row_id="7")
    pid = ig_insights.upsert_post(cx, _media_item("M1"))
    db.update(cx, "ig_posts", pid, band_id=b2)  # el usuario la asignó a mano
    n = ig_insights.link_bands(cx, [{"id": 7, "ig_post_id": "M1"}])
    assert n == 0
    assert db.get(cx, "ig_posts", pid)["band_id"] == b2


# ---------- resumen por banda + sugerencia de prioridad ----------

def _post_con_metricas(cx, band_id: int, media_id: str, *, likes: int, comments: int = 0,
                       saved: int = 0, reach: int | None = None,
                       dias_atras: int = 5) -> int:
    ts = (datetime.now() - timedelta(days=dias_atras)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    pid = ig_insights.upsert_post(cx, _media_item(
        media_id, like_count=likes, comments_count=comments, timestamp=ts))
    db.update(cx, "ig_posts", pid, band_id=band_id)
    if reach is not None or saved:
        ig_insights.save_insights(cx, pid, {"reach": reach, "saved": saved,
                                            "shares": 0, "views": 0})
    return pid


def test_band_stats_sugerencias(cx) -> None:
    # ER = (likes + 2*comments + 3*saved) / reach
    alta = db.insert(cx, "bands", nombre="Alta", prioridad=3)
    media = db.insert(cx, "bands", nombre="Media", prioridad=3)
    baja = db.insert(cx, "bands", nombre="Baja", prioridad=3)
    for i in range(2):
        _post_con_metricas(cx, alta, f"A{i}", likes=20, comments=5, reach=100)   # ER 0.30
        _post_con_metricas(cx, media, f"M{i}", likes=10, reach=100)              # ER 0.10
        _post_con_metricas(cx, baja, f"B{i}", likes=2, reach=100)                # ER 0.02
    stats = {s["nombre"]: s for s in ig_insights.band_stats(cx)}
    # mediana = 0.10 → Alta >40% arriba sube (3→2); Baja >40% abajo baja (3→4)
    assert stats["Alta"]["sugerida"] == 2
    assert stats["Baja"]["sugerida"] == 4
    assert stats["Media"]["sugerida"] is None
    assert stats["Alta"]["n_posts"] == 2
    assert stats["Alta"]["avg_likes"] == 20


def test_band_stats_pocos_posts_sin_sugerencia(cx) -> None:
    b1 = db.insert(cx, "bands", nombre="Solo1", prioridad=3)
    b2 = db.insert(cx, "bands", nombre="Par", prioridad=3)
    _post_con_metricas(cx, b1, "S1", likes=50, reach=100)  # 1 post → sin sugerencia
    for i in range(2):
        _post_con_metricas(cx, b2, f"P{i}", likes=10, reach=100)
    stats = {s["nombre"]: s for s in ig_insights.band_stats(cx)}
    assert stats["Solo1"]["sugerida"] is None
    assert stats["Solo1"]["n_posts"] == 1


def test_band_stats_respeta_topes(cx) -> None:
    top = db.insert(cx, "bands", nombre="Top", prioridad=1)
    piso = db.insert(cx, "bands", nombre="Piso", prioridad=5)
    ref = db.insert(cx, "bands", nombre="Ref", prioridad=3)
    for i in range(2):
        _post_con_metricas(cx, top, f"T{i}", likes=30, reach=100)   # ER 0.30, ya en 1
        _post_con_metricas(cx, piso, f"F{i}", likes=1, reach=100)   # ER 0.01, ya en 5
        _post_con_metricas(cx, ref, f"R{i}", likes=10, reach=100)   # ER 0.10 (mediana)
    stats = {s["nombre"]: s for s in ig_insights.band_stats(cx)}
    assert stats["Top"]["sugerida"] is None    # no puede subir más
    assert stats["Piso"]["sugerida"] is None   # no puede bajar más


def test_band_stats_fallback_sin_reach(cx) -> None:
    """Sin reach: ER = likes / followers_ig de la banda."""
    sin = db.insert(cx, "bands", nombre="SinReach", prioridad=3, followers_ig=1000)
    ref = db.insert(cx, "bands", nombre="Ref", prioridad=3)
    for i in range(2):
        _post_con_metricas(cx, sin, f"X{i}", likes=30)              # 30/1000 = 0.03
        _post_con_metricas(cx, ref, f"R{i}", likes=10, reach=100)   # 0.10
    stats = {s["nombre"]: s for s in ig_insights.band_stats(cx)}
    assert stats["SinReach"]["er"] == pytest.approx(0.03)
    # mediana [0.03, 0.10] = 0.065 → 0.03 < 0.065*0.6 = 0.039 → baja (3→4)
    assert stats["SinReach"]["sugerida"] == 4


def test_band_stats_ignora_posts_viejos(cx) -> None:
    b = db.insert(cx, "bands", nombre="Vieja", prioridad=3)
    _post_con_metricas(cx, b, "V1", likes=10, reach=100, dias_atras=200)
    _post_con_metricas(cx, b, "V2", likes=10, reach=100, dias_atras=5)
    stats = {s["nombre"]: s for s in ig_insights.band_stats(cx)}
    assert stats["Vieja"]["n_posts"] == 1


# ---------- sync_posts orquestador (red mockeada) ----------

def test_sync_posts_tolerante_a_fallos(cx, monkeypatch) -> None:
    items = [_media_item("M1"), _media_item("M2", like_count=7)]
    monkeypatch.setattr(ig_insights, "_fetch_media", lambda: items)

    def fake_insights(media_id: str) -> dict:
        if media_id == "M2":
            raise RuntimeError("Graph API 400: insights no disponibles")
        return {"reach": 100, "saved": 3, "shares": 1, "views": 200}

    monkeypatch.setattr(ig_insights, "_fetch_insights", fake_insights)
    monkeypatch.setattr(ig_insights, "_sheet_rows", lambda: [])

    res = ig_insights.sync_posts(cx)
    assert res["posts"] == 2
    assert res["insights_fallidos"] == 1
    posts = {p["media_id"]: p for p in db.rows(cx, "SELECT * FROM ig_posts")}
    assert posts["M1"]["reach"] == 100
    assert posts["M2"]["reach"] is None and posts["M2"]["likes"] == 7  # conserva el feed
    assert posts["M1"]["last_sync"] is not None
    # snapshot del día para ambos
    assert len(db.rows(cx, "SELECT * FROM ig_metrics_snapshots")) == 2


def test_sync_posts_etiqueta_formatos_tras_vincular(cx, monkeypatch) -> None:
    # El sync diario debe correr el backfill de formato_patron (eje formato
    # del cerebro de engagement) para que score_formatos tenga datos frescos.
    from src import format_tags
    monkeypatch.setattr(ig_insights, "_fetch_media", lambda: [])
    monkeypatch.setattr(ig_insights, "_sheet_rows", lambda: [])
    monkeypatch.setattr(format_tags, "etiquetar_publicados",
                        lambda cx: {"etiquetados": 2, "fallados": 0})
    res = ig_insights.sync_posts(cx)
    assert res["etiquetados"] == 2


def test_sync_posts_llm_caido_no_es_fatal(cx, monkeypatch) -> None:
    from src import format_tags
    monkeypatch.setattr(ig_insights, "_fetch_media", lambda: [])
    monkeypatch.setattr(ig_insights, "_sheet_rows", lambda: [])

    def boom(cx):
        raise RuntimeError("DeepSeek caído")

    monkeypatch.setattr(format_tags, "etiquetar_publicados", boom)
    res = ig_insights.sync_posts(cx)
    assert res["etiquetados"] == 0
    assert "etiquetado" in (res.get("warning") or "").lower()


def test_sync_posts_sheet_caido_no_es_fatal(cx, monkeypatch) -> None:
    monkeypatch.setattr(ig_insights, "_fetch_media", lambda: [_media_item("M1")])
    monkeypatch.setattr(ig_insights, "_fetch_insights",
                        lambda mid: {"reach": 1, "saved": 0, "shares": 0, "views": 0})

    def boom():
        raise RuntimeError("sin credenciales de Google")

    monkeypatch.setattr(ig_insights, "_sheet_rows", boom)
    res = ig_insights.sync_posts(cx)
    assert res["posts"] == 1
    assert "sheet" in (res.get("warning") or "").lower() or res.get("warning")
