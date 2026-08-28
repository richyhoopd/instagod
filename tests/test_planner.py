"""Tests del planificador mensual: topes por prioridad, ranking y reparto."""
from __future__ import annotations

from datetime import date

import config
from src import db
from src.planner import (
    _cap,
    _slots_del_mes,
    pick_replacement,
    proximo_mes,
    seleccionar,
)


def _seed(cx, nombre, prioridad, followers, n_fotos, nitidez=100.0, usadas=0):
    bid = db.insert(cx, "bands", nombre=nombre, prioridad=prioridad,
                    followers_ig=followers, activa=1)
    for i in range(n_fotos):
        db.insert(cx, "photos", band_id=bid, path=f"{nombre}_{i}.jpg",
                  usable_meme=1, usada=1 if i < usadas else 0, nitidez=nitidez)
    return bid


def test_cap_por_prioridad() -> None:
    assert _cap(1) == 5 and _cap(2) == 2 and _cap(3) == 1
    assert _cap(4) == 1 and _cap(5) == 1 and _cap(None) == 1


def test_topes_se_respetan(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    p1 = _seed(cx, "P1band", 1, 1000, 10)   # tope 5
    p2 = _seed(cx, "P2band", 2, 1000, 10)   # tope 2
    p3 = _seed(cx, "P3band", 3, 1000, 10)   # tope 1
    sel = seleccionar(cx, max_posts=1000)   # sin límite de slots
    cuenta = {p1: 0, p2: 0, p3: 0}
    for f in sel:
        cuenta[f["band_id"]] += 1
    assert cuenta[p1] == 5 and cuenta[p2] == 2 and cuenta[p3] == 1
    cx.close()


def test_ranking_prioridad_luego_followers(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    # misma prioridad, distinto followers → primero el de más followers
    grande = _seed(cx, "Grande", 2, 5000, 1)
    chico = _seed(cx, "Chico", 2, 100, 1)
    # prioridad más alta (1) debe ir ANTES que cualquier P2
    top = _seed(cx, "Top", 1, 50, 1)
    sel = seleccionar(cx, max_posts=3)
    assert sel[0]["band_id"] == top            # P1 primero pese a menos followers
    assert sel[1]["band_id"] == grande         # entre P2, más followers
    assert sel[2]["band_id"] == chico
    cx.close()


def test_solo_usables_sin_usar(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = _seed(cx, "Banda", 1, 1000, 5, usadas=3)  # 3 ya usadas, 2 disponibles
    # foto no usable extra
    db.insert(cx, "photos", band_id=bid, path="mala.jpg", usable_meme=0, usada=0)
    sel = seleccionar(cx, max_posts=1000)
    assert len(sel) == 2  # solo las 2 usables sin usar (tope 5 no alcanza)
    cx.close()


def test_round_robin_reparte(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    a = _seed(cx, "A", 1, 1000, 5)
    b = _seed(cx, "B", 1, 900, 5)
    sel = seleccionar(cx, max_posts=4)
    # primeras 2 deben ser de bandas distintas (no AA seguido)
    assert sel[0]["band_id"] != sel[1]["band_id"]
    assert {sel[0]["band_id"], sel[1]["band_id"]} == {a, b}
    cx.close()


def test_proximo_mes() -> None:
    assert proximo_mes(date(2026, 6, 15)) == (2026, 7)
    assert proximo_mes(date(2026, 12, 1)) == (2027, 1)


def test_respeta_max_posts(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    for i in range(20):
        _seed(cx, f"B{i}", 1, 1000, 5)
    sel = seleccionar(cx, max_posts=30)
    assert len(sel) == 30  # corta en el límite de slots
    cx.close()


# ---------- _slots_del_mes ----------

def test_slots_del_mes_cuenta_y_orden() -> None:
    slots = _slots_del_mes(2026, 6)   # junio: 30 días
    por_dia = min(len(config.POSTING_SLOTS), config.POSTS_PER_DAY)
    assert len(slots) == 30 * por_dia
    assert slots == sorted(slots)              # ascendente global
    assert all(s.tzinfo is not None for s in slots)   # tz-aware (America/Mexico_City)


# ---------- pick_replacement: rellena con banda NUEVA, sin repetir ----------

def _foto_id(cx, band_id):
    return db.rows(cx, "SELECT id FROM photos WHERE band_id = ?", (band_id,))[0]["id"]


def _plan_row(cx, band_id, photo_id, mes="2026-07"):
    db.insert(cx, "content_queue", tipo="meme", band_id=band_id, photo_id=photo_id,
              status=db.QUEUE_BORRADOR, scheduled_datetime=f"{mes}-05T19:00:00")


def test_pick_replacement_prefiere_banda_nueva_por_impacto(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    a = _seed(cx, "A", 3, 1000, 1)          # ya en el plan (tocada)
    b = _seed(cx, "B", 1, 100, 1)           # nueva, prioridad alta
    _seed(cx, "C", 2, 9999, 1)              # nueva, más followers pero prioridad menor
    _plan_row(cx, a, _foto_id(cx, a))       # A ocupa un slot del mes

    repl = pick_replacement(cx, "2026-07")
    assert repl is not None
    assert repl["band_id"] == b             # P1 gana sobre P2 con más followers
    cx.close()


def test_pick_replacement_respeta_excluir_band(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    a = _seed(cx, "A", 3, 1000, 1)
    b = _seed(cx, "B", 1, 100, 1)
    c = _seed(cx, "C", 2, 9999, 1)
    _plan_row(cx, a, _foto_id(cx, a))

    repl = pick_replacement(cx, "2026-07", excluir_band=b)
    assert repl["band_id"] == c             # B excluida → la siguiente por impacto
    cx.close()


def test_pick_replacement_sin_candidatas_devuelve_none(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    db.insert(cx, "bands", nombre="Vacia", activa=1)   # sin fotos usables
    assert pick_replacement(cx, "2026-07") is None
    cx.close()


# ---------- FIX A: plan_month solo agenda slots FUTUROS ----------

def test_plan_month_salta_slots_pasados(tmp_path, monkeypatch) -> None:
    """Estando a 10-jul, plan_month(2026,7) NO crea posts de los días 1..10 pasados."""
    from datetime import datetime as _dt

    from src import planner
    db_path = tmp_path / "t.db"
    cx = db.connect(db_path)
    db.init_db(cx)
    for i in range(60):                 # pool amplio para llenar todos los slots
        _seed(cx, f"B{i}", 1, 1000, 5)
    cx.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    class _FakeDT(_dt):                  # ahora = 2026-07-10 15:00 CDMX
        @classmethod
        def now(cls, tz=None):
            base = _dt(2026, 7, 10, 15, 0)
            return tz.localize(base) if tz else base
    monkeypatch.setattr(planner, "datetime", _FakeDT)

    res = planner.plan_month(2026, 7, replan=True)
    assert res["posts"] > 0

    cx = orig(db_path)
    fechas = [f["scheduled_datetime"] for f in db.rows(
        cx, "SELECT scheduled_datetime FROM content_queue "
            "WHERE status='borrador' AND substr(scheduled_datetime,1,7)='2026-07'")]
    cx.close()
    assert fechas, "debió crear borradores del resto del mes"
    assert all(f[8:10] >= "10" for f in fechas)          # nada de los días 1..9
    assert min(fechas) >= "2026-07-10T15:00"             # nada antes de ahora
    dia10 = [f for f in fechas if f[8:10] == "10"]        # día de hoy: solo > 15:00
    assert dia10 and all(f[11:16] > "15:00" for f in dia10)


def test_plan_month_mes_futuro_sigue_completo(tmp_path, monkeypatch) -> None:
    """Un mes futuro (agosto) NO se filtra: mantiene el día 1."""
    from datetime import datetime as _dt

    from src import planner
    db_path = tmp_path / "t.db"
    cx = db.connect(db_path)
    db.init_db(cx)
    for i in range(60):
        _seed(cx, f"B{i}", 1, 1000, 5)
    cx.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    class _FakeDT(_dt):
        @classmethod
        def now(cls, tz=None):
            base = _dt(2026, 7, 10, 15, 0)
            return tz.localize(base) if tz else base
    monkeypatch.setattr(planner, "datetime", _FakeDT)

    planner.plan_month(2026, 8, replan=True)
    cx = orig(db_path)
    fechas = [f["scheduled_datetime"] for f in db.rows(
        cx, "SELECT scheduled_datetime FROM content_queue "
            "WHERE status='borrador' AND substr(scheduled_datetime,1,7)='2026-08'")]
    cx.close()
    assert any(f[8:10] == "01" for f in fechas)          # agosto arranca el día 1


# ---------- criterio="engagement": desempeño propio + tiempo sin publicar ----------

def _post_nuestro(cx, band_id, *, dias, media_id, likes, reach, shares=0):
    """Un post NUESTRO sobre esa banda, con el formato de fecha de la Graph API."""
    from datetime import datetime, timedelta, timezone
    ts = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%dT%H:%M:%S") + "+0000"
    return db.insert(cx, "ig_posts", media_id=media_id, band_id=band_id, timestamp=ts,
                     likes=likes, comments=0, saved=0, reach=reach, shares=shares)


def _cx_planner(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_criterio_engagement_cambia_el_orden_contra_impacto(tmp_path) -> None:
    """Misma DB, dos criterios, dos órdenes distintos.

    `quemada` es P1 con 100k followers pero la publicamos ayer y le fue mal.
    `probada` es P3 con 100 followers, la publicamos hace 90 días y le fue muy bien.
    Con "impacto" (prioridad+followers) gana `quemada`; con "engagement" gana `probada`.
    """
    cx = _cx_planner(tmp_path)
    quemada = _seed(cx, "Quemada", 1, 100_000, 3)
    probada = _seed(cx, "Probada", 3, 100, 3)
    _post_nuestro(cx, quemada, dias=1, media_id="q1", likes=5, reach=1000)
    _post_nuestro(cx, quemada, dias=2, media_id="q2", likes=5, reach=1000)
    _post_nuestro(cx, probada, dias=90, media_id="p1", likes=200, reach=800, shares=40)
    _post_nuestro(cx, probada, dias=91, media_id="p2", likes=200, reach=800, shares=40)

    por_impacto = seleccionar(cx, max_posts=2, criterio="impacto")
    por_engagement = seleccionar(cx, max_posts=2, criterio="engagement")

    assert por_impacto[0]["band_id"] == quemada
    assert por_engagement[0]["band_id"] == probada
    cx.close()


def test_criterio_por_defecto_sigue_siendo_impacto(tmp_path) -> None:
    """El criterio nuevo es opt-in: no cambia lo que ya hacían web/app.py ni el cron."""
    cx = _cx_planner(tmp_path)
    alta = _seed(cx, "Alta", 1, 10, 2)
    baja = _seed(cx, "Baja", 3, 999_999, 2)
    assert seleccionar(cx, max_posts=2)[0]["band_id"] == alta
    assert seleccionar(cx, max_posts=2)[0]["band_id"] == \
        seleccionar(cx, max_posts=2, criterio="impacto")[0]["band_id"]
    assert baja is not None
    cx.close()


def test_criterio_engagement_respeta_topes_y_round_robin(tmp_path) -> None:
    """El criterio solo cambia el ORDEN de las bandas: topes y reparto siguen igual."""
    cx = _cx_planner(tmp_path)
    p1 = _seed(cx, "P1band", 1, 1000, 10)
    p2 = _seed(cx, "P2band", 2, 1000, 10)
    p3 = _seed(cx, "P3band", 3, 1000, 10)
    sel = seleccionar(cx, max_posts=1000, criterio="engagement")
    cuenta = {p1: 0, p2: 0, p3: 0}
    for f in sel:
        cuenta[f["band_id"]] += 1
    assert cuenta[p1] == 5 and cuenta[p2] == 2 and cuenta[p3] == 1
    cx.close()
