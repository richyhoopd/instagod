"""Tests del envío ASÍNCRONO del plan (src.send_plan): encola 'pendiente' y manda
a Telegram sin abrir poller (compatible con el approval-daemon)."""
from __future__ import annotations

from src import db


def _seed_borrador(cx, *, nombre="Kabala", handle=None, mes="2026-07",
                   status=None, aprobacion=None, tipo="meme"):
    bid = db.insert(cx, "bands", nombre=nombre, ig_handle=handle or nombre.lower(),
                    activa=1, prioridad=1)
    pid = db.insert(cx, "photos", band_id=bid, path="/tmp/x.jpg", usable_meme=1, usada=0)
    qid = db.insert(cx, "content_queue", tipo=tipo, band_id=bid, photo_id=pid,
                    status=status or db.QUEUE_BORRADOR, aprobacion=aprobacion,
                    scheduled_datetime=f"{mes}-15T19:00:00")
    return bid, pid, qid


def _mock_pipeline(monkeypatch):
    """Mockea LLM/compose/host/Telegram; devuelve la lista de envíos capturados."""
    from src import send_plan
    enviados: list = []
    monkeypatch.setattr(send_plan, "_PAUSA_ENVIO_S", 0)
    monkeypatch.setattr(send_plan.caption_mod, "generate_caption", lambda **k: "TITULAR")
    monkeypatch.setattr(send_plan.compose_mod, "random_template", lambda: "clasica")
    monkeypatch.setattr(send_plan.compose_mod, "compose", lambda **k: "/tmp/out.png")
    monkeypatch.setattr(send_plan.host, "upload", lambda p, public_id=None: "http://img/x.png")
    monkeypatch.setattr(send_plan.approval, "enviar_a_telegram",
                        lambda cap, url, q, **kw: enviados.append((cap, url, q, kw)))
    return send_plan, enviados


def test_send_plan_encola_pendiente_y_envia(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "t.db"
    cx = db.connect(db_path)
    db.init_db(cx)
    _, _, qid = _seed_borrador(cx)
    cx.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    send_plan, enviados = _mock_pipeline(monkeypatch)

    rc = send_plan.main("2026-07")
    assert rc == 0

    # Se mandó exactamente 1, con botón regenerable y la imagen subida.
    assert len(enviados) == 1
    cap, url, q, kw = enviados[0]
    assert q == qid and url == "http://img/x.png"
    assert kw.get("regenerable") is True
    assert cap.endswith("@kabala")           # caption con @handle

    # La fila del plan quedó 'pendiente' (no una fila nueva) con caption/imagen.
    cx = orig(db_path)
    fila = db.get(cx, "content_queue", qid)
    total = db.rows(cx, "SELECT COUNT(*) c FROM content_queue")[0]["c"]
    cx.close()
    assert total == 1                        # ACTUALIZA, no inserta duplicado
    assert fila["aprobacion"] == "pendiente"
    assert fila["caption"] == "TITULAR\n\n@kabala"
    assert fila["imagen_url"] == "http://img/x.png"
    assert fila["template"] == "clasica"
    assert fila["status"] == db.QUEUE_BORRADOR   # el daemon lo mueve a en_sheet al aprobar


def test_send_plan_no_reenvia_lo_ya_pendiente(tmp_path, monkeypatch) -> None:
    """Segunda corrida: lo ya enviado (aprobacion='pendiente') NO se re-manda."""
    db_path = tmp_path / "t.db"
    cx = db.connect(db_path)
    db.init_db(cx)
    _seed_borrador(cx, aprobacion="pendiente")   # ya enviado antes
    cx.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    send_plan, enviados = _mock_pipeline(monkeypatch)

    rc = send_plan.main("2026-07")
    assert rc == 0
    assert enviados == []                       # nada que reenviar


def test_borradores_del_mes_filtra_tipo_y_mes(tmp_path) -> None:
    from src import send_plan
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    _, _, qid_meme = _seed_borrador(cx, nombre="Meme", mes="2026-07")
    _seed_borrador(cx, nombre="Anuncio", tipo="anuncio", mes="2026-07")  # no es meme
    _seed_borrador(cx, nombre="OtroMes", mes="2026-08")                  # otro mes
    filas = send_plan.borradores_del_mes(cx, "2026-07")
    cx.close()
    assert [f["qid"] for f in filas] == [qid_meme]
