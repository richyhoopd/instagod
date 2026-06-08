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
