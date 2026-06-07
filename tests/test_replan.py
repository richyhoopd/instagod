"""Tests del auto-relleno del plan: quitar un post mete otra banda en su lugar."""
from __future__ import annotations

from src import db
from src.planner import pick_replacement, reemplazar


def _band_con_foto(cx, nombre, prioridad=3, followers=100, n=1):
    bid = db.insert(cx, "bands", nombre=nombre, prioridad=prioridad,
                    followers_ig=followers, activa=1)
    pids = [db.insert(cx, "photos", band_id=bid, path=f"{nombre}_{i}.jpg",
                      usable_meme=1, usada=0, nitidez=100) for i in range(n)]
    return bid, pids


def _en_plan(cx, bid, pid, slot):
    return db.insert(cx, "content_queue", tipo="meme", band_id=bid, photo_id=pid,
                     status=db.QUEUE_BORRADOR, scheduled_datetime=slot)


def test_pick_prefiere_banda_nueva_al_plan(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MONTHLY_CAP", {1: 5, 2: 2, 3: 1, 4: 1, 5: 1})
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    a, pa = _band_con_foto(cx, "EnPlan", prioridad=1, followers=9999, n=3)
    b, pb = _band_con_foto(cx, "Fuera", prioridad=3, followers=10, n=1)
    _en_plan(cx, a, pa[0], "2026-07-01T12:00")  # A ya está en el plan
    # aunque A es P1 con cupo, el reemplazo prefiere B (banda nueva al plan)
    repl = pick_replacement(cx, "2026-07", excluir_band=None)
    assert repl["band_id"] == b
    cx.close()


def test_pick_respeta_tope(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MONTHLY_CAP", {1: 5, 2: 2, 3: 1, 4: 1, 5: 1})
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    # única banda, P3 (tope 1), ya en el plan → no hay reemplazo posible
    a, pa = _band_con_foto(cx, "Sola", prioridad=3, n=3)
    _en_plan(cx, a, pa[0], "2026-07-01T12:00")
    assert pick_replacement(cx, "2026-07", excluir_band=None) is None
    cx.close()


def test_reemplazar_mantiene_el_slot(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "MONTHLY_CAP", {1: 5, 2: 2, 3: 1, 4: 1, 5: 1})
    db_path = tmp_path / "t.db"
    cx = db.connect(db_path)
    db.init_db(cx)
    a, pa = _band_con_foto(cx, "Quitada", n=1)
    b, pb = _band_con_foto(cx, "Nueva", followers=500, n=1)
    qid = _en_plan(cx, a, pa[0], "2026-07-05T19:00")
    cx.close()

    # reemplazar() abre su propia conexión → la apuntamos a la DB de prueba.
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    repl = reemplazar(qid)
    assert repl is not None
    assert repl["banda_nombre"] == "Nueva"                    # entró otra banda
    assert repl["scheduled_datetime"] == "2026-07-05T19:00"   # mismo slot

    cx = orig(db_path)
    # el plan sigue con 1 borrador (se mantuvo el número); el viejo quedó descartado
    assert db.rows(cx, "SELECT COUNT(*) c FROM content_queue WHERE status='borrador'")[0]["c"] == 1
    assert db.get(cx, "content_queue", qid)["status"] == "descartado"
    cx.close()


def test_eliminar_lista_negra(tmp_path, monkeypatch):
    """Eliminar marca la foto descartada=1 → nunca vuelve a seleccionarse."""
    import config
    from src.planner import eliminar, seleccionar
    monkeypatch.setattr(config, "MONTHLY_CAP", {1: 5, 2: 2, 3: 1, 4: 1, 5: 1})
    db_path = tmp_path / "t.db"
    cx = db.connect(db_path)
    db.init_db(cx)
    a, pa = _band_con_foto(cx, "A", n=1)
    b, pb = _band_con_foto(cx, "B", followers=500, n=1)
    qid = _en_plan(cx, a, pa[0], "2026-07-05T19:00")
    cx.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    repl = eliminar(qid)                      # elimina A → entra B
    assert repl["banda_nombre"] == "B"

    cx = orig(db_path)
    assert db.get(cx, "photos", pa[0])["descartada"] == 1   # A en lista negra
    # ya no aparece en una nueva selección, ni con cupo libre
    sel = seleccionar(cx, max_posts=100)
    assert pa[0] not in [f["photo_id"] for f in sel]
    cx.close()


def test_sugeridas_no_se_repiten(tmp_path, monkeypatch):
    """Una foto que ya estuvo en la cola (cualquier status) no se vuelve a sugerir."""
    import config
    from src.planner import seleccionar
    monkeypatch.setattr(config, "MONTHLY_CAP", {1: 5, 2: 2, 3: 1, 4: 1, 5: 1})
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    a, pa = _band_con_foto(cx, "A", n=2)   # 2 fotos
    # una foto ya estuvo en la cola y fue RECHAZADA (descartado) → no re-sugerir
    db.insert(cx, "content_queue", tipo="meme", band_id=a, photo_id=pa[0],
              status=db.QUEUE_DESCARTADO, scheduled_datetime="2026-06-01T11:00")
    sel = seleccionar(cx, max_posts=100)
    ids = [f["photo_id"] for f in sel]
    assert pa[0] not in ids          # la rechazada NO vuelve
    assert pa[1] in ids              # la otra (nunca usada) sí
    cx.close()


def test_lo_quitado_no_regresa(tmp_path, monkeypatch):
    """El bug del ping-pong: quitar A→B, luego quitar B NO debe traer A de vuelta."""
    import config
    monkeypatch.setattr(config, "MONTHLY_CAP", {1: 5, 2: 2, 3: 1, 4: 1, 5: 1})
    db_path = tmp_path / "t.db"
    cx = db.connect(db_path)
    db.init_db(cx)
    a, pa = _band_con_foto(cx, "A", followers=100, n=1)
    b, pb = _band_con_foto(cx, "B", followers=200, n=1)
    c, pc = _band_con_foto(cx, "C", followers=300, n=1)
    qid = _en_plan(cx, a, pa[0], "2026-07-05T19:00")   # plan: solo A
    cx.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    r1 = reemplazar(qid)            # quito A → entra la de más impacto no usada (C)
    assert r1["banda_nombre"] == "C"
    r2 = reemplazar(r1["id"])      # quito C → debe entrar B, NUNCA A ni C otra vez
    assert r2["banda_nombre"] == "B"
    r3 = reemplazar(r2["id"])      # quito B → ya no hay nuevas → None (no revive A/C)
    assert r3 is None
