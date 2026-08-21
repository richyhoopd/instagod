"""Task 3 (Fase 2): aprobar sin Sheet (slot desde DB), espejo opcional y
rastro de Telegram.

Spec: sin SHEET_ID ya no truena (comportamiento removido) — usa
scheduler.next_free_slot_db y deja status='programado'. Con SHEET_ID sigue
el camino legacy (escribe el Sheet, status='en_sheet'). Si el espejo al
Sheet falla, la aprobación NO se revierte: cae a 'programado' + columna
`error` accionable.
"""
from __future__ import annotations

from datetime import datetime

import pytz

import config
from src import approval, db, scheduler


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ahora():
    return datetime.now(pytz.timezone(config.TIMEZONE))


def test_aprobar_sin_sheet_id_usa_slot_db_y_queda_programado(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SHEET_ID", raising=False)
    monkeypatch.delenv("SHEET_ID__GDLSCENE", raising=False)
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")

    hueco = datetime(2026, 6, 11, 19, 0)
    llamado = {}

    def _fake_next_free_slot_db(cx_, account_id, *, now=None, slots=None):
        llamado["account_id"] = account_id
        return hueco

    monkeypatch.setattr(scheduler, "next_free_slot_db", _fake_next_free_slot_db)

    slot = approval.aprobar(cx, qid, ahora=datetime(2026, 6, 10, 10, 0), user_id=7)

    fila = db.get(cx, "content_queue", qid)
    assert slot == hueco
    assert fila["status"] == "programado"
    assert fila["aprobacion"] == "aprobado"
    assert fila["aprobado_por"] == 7
    assert fila["scheduled_datetime"] == hueco.isoformat()
    assert fila["sheet_row_id"] is None
    assert llamado["account_id"] == 1


def test_aprobar_con_sheet_id_conserva_en_sheet(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SHEET_ID", "SHEET-TEST")
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")

    hueco = datetime(2026, 6, 11, 19, 0)
    slot = approval.aprobar(cx, qid, ahora=datetime(2026, 6, 10, 10, 0), user_id=3,
                            _escribir_sheet=lambda **k: 99,
                            _slot_meme=lambda ahora, sheet_id, slots: hueco)

    fila = db.get(cx, "content_queue", qid)
    assert slot == hueco
    assert fila["status"] == "en_sheet"
    assert fila["sheet_row_id"] == "99"
    assert fila["aprobado_por"] == 3
    assert fila["scheduled_datetime"] == hueco.isoformat()
    assert fila["error"] is None


def test_aprobar_espejo_sheet_falla_deja_programado_con_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SHEET_ID", "SHEET-TEST")
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")

    hueco = datetime(2026, 6, 11, 19, 0)

    def _sheet_roto(**kw):
        raise RuntimeError("Sheet API caída y con un mensaje bien largo " * 10)

    slot = approval.aprobar(cx, qid, ahora=datetime(2026, 6, 10, 10, 0), user_id=3,
                            _escribir_sheet=_sheet_roto,
                            _slot_meme=lambda ahora, sheet_id, slots: hueco)

    fila = db.get(cx, "content_queue", qid)
    assert slot == hueco
    # la aprobación NO se revierte
    assert fila["aprobacion"] == "aprobado"
    assert fila["aprobado_por"] == 3
    assert fila["status"] == "programado"
    assert fila["scheduled_datetime"] == hueco.isoformat()
    assert fila["error"].startswith("espejo sheet:")
    assert len(fila["error"]) <= len("espejo sheet: ") + 200


def test_rechazar_guarda_aprobado_por_y_descartado(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")
    approval.rechazar(cx, qid, user_id=11)
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "rechazado"
    assert fila["status"] == "descartado"
    assert fila["aprobado_por"] == 11


def test_enviar_a_telegram_con_cx_persiste_tg_ids(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-gdl")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {"message_id": 42, "chat": {"id": -100}}}

    def _post(url, data=None, timeout=None):
        return _Resp()

    import requests
    monkeypatch.setattr(requests, "post", _post)

    approval.enviar_a_telegram("hola", "http://x/1.jpg", qid, cx=cx)

    fila = db.get(cx, "content_queue", qid)
    assert fila["tg_message_id"] == "42"
    assert fila["tg_chat_id"] == "-100"


def test_enviar_a_telegram_sin_cx_no_toca_db(monkeypatch) -> None:
    """Llamadas legacy (sin cx) mantienen el comportamiento actual: no truena
    por no poder persistir tg ids."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-gdl")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": {"message_id": 1, "chat": {"id": -1}}}

    def _post(url, data=None, timeout=None):
        return _Resp()

    import requests
    monkeypatch.setattr(requests, "post", _post)

    approval.enviar_a_telegram("hola", "http://x/1.jpg", 999)  # no revienta


def test_notificar_resolucion_sin_token_devuelve_false_sin_excepcion(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__GDLSCENE", raising=False)
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")
    db.update(cx, "content_queue", qid, tg_chat_id="-100", tg_message_id="42")

    assert approval.notificar_resolucion(cx, qid, "✅ Aprobado") is False


def test_notificar_resolucion_edita_botones_y_manda_reply(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-gdl")
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")
    db.update(cx, "content_queue", qid, tg_chat_id="-100", tg_message_id="42")

    llamadas = []

    class _Resp:
        def raise_for_status(self):
            pass

    def _post(url, data=None, timeout=None):
        llamadas.append((url, data))
        return _Resp()

    import requests
    monkeypatch.setattr(requests, "post", _post)

    assert approval.notificar_resolucion(cx, qid, "✅ Aprobado") is True
    assert any("editMessageReplyMarkup" in u for u, _ in llamadas)
    assert any("sendMessage" in u for u, _ in llamadas)
    envio = next(d for u, d in llamadas if "sendMessage" in u)
    assert envio["reply_to_message_id"] == "42"
    assert envio["text"] == "✅ Aprobado"


def test_notificar_resolucion_falla_no_revienta(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-gdl")
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")
    db.update(cx, "content_queue", qid, tg_chat_id="-100", tg_message_id="42")

    def _post(url, data=None, timeout=None):
        raise ConnectionError("red caída")

    import requests
    monkeypatch.setattr(requests, "post", _post)

    assert approval.notificar_resolucion(cx, qid, "x") is False


def test_notificar_resolucion_sin_tg_ids_devuelve_false(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-gdl")
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")
    assert approval.notificar_resolucion(cx, qid, "x") is False


def test_notificar_resolucion_no_filtra_token(tmp_path, monkeypatch, capsys) -> None:
    """requests.HTTPError trae la URL completa (con el bot token) en su texto
    y en resp.url — el log a stderr NUNCA debe filtrar ese token."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok_tg_999")
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c", imagen_url="u")
    db.update(cx, "content_queue", qid, tg_chat_id="-100", tg_message_id="42")

    import requests

    def _post(url, data=None, timeout=None):
        resp = requests.Response()
        resp.status_code = 401
        resp.url = "https://api.telegram.org/bottok_tg_999/editMessageReplyMarkup"
        raise requests.HTTPError("401 Client Error: Unauthorized for url: "
                                 f"{resp.url}", response=resp)

    monkeypatch.setattr(requests, "post", _post)

    assert approval.notificar_resolucion(cx, qid, "x") is False
    captured = capsys.readouterr()
    assert "tok_tg_999" not in captured.err
