"""Aprobación multi-marca: Sheet, malla y bot de la marca correcta, siempre."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
import pytz

import config
from src import approval, db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    mid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
                    nombre="Pensión+", ciudad="CDMX", posting_slots="10:00,18:00")
    return cx, mid


def _ahora():
    return datetime.now(pytz.timezone(config.TIMEZONE))


def test_aprobar_usa_sheet_y_malla_de_la_marca(tmp_path, monkeypatch) -> None:
    cx, mid = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="slideshow", caption="c",
                                     imagen_url=json.dumps(["https://x/1.jpg"]),
                                     account_id=mid)
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "SHEET-P")
    llamadas = {}

    def _slot(ahora, sheet_id, slots):
        llamadas["slot"] = (sheet_id, tuple(slots))
        return _ahora()

    def _sheet(**kw):
        llamadas["sheet"] = kw
        return 42

    approval.aprobar(cx, qid, _escribir_sheet=_sheet, _slot_meme=_slot)
    assert llamadas["slot"] == ("SHEET-P", ("10:00", "18:00"))
    assert llamadas["sheet"]["sheet_id"] == "SHEET-P"
    assert llamadas["sheet"]["banda"] == "@pensionmas"
    assert db.get(cx, "content_queue", qid)["sheet_row_id"] == "42"


def test_aprobar_gdlscene_sigue_igual(tmp_path, monkeypatch) -> None:
    cx, _ = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c",
                                     imagen_url="https://x/1.jpg")  # account_id=1
    # account_creds() resuelve el fallback de gdlscene leyendo os.environ en
    # el momento (no el atributo config.SHEET_ID cacheado al importar), igual
    # que test_marcas.test_marca_nueva_no_hereda_creds_de_gdlscene.
    monkeypatch.setenv("SHEET_ID", "SHEET-GDL")
    monkeypatch.delenv("SHEET_ID__GDLSCENE", raising=False)
    llamadas = {}

    def _slot(ahora, sheet_id, slots):
        llamadas["slot"] = (sheet_id, slots)
        return _ahora()

    approval.aprobar(cx, qid, _escribir_sheet=lambda **kw: 1, _slot_meme=_slot)
    sheet_id, slots = llamadas["slot"]
    assert sheet_id == "SHEET-GDL"
    assert slots is None            # malla global (POSTS_PER_DAY aplica)


def test_aprobar_sin_sheet_de_marca_revienta_accionable(tmp_path, monkeypatch) -> None:
    cx, mid = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="slideshow", caption="c",
                                     imagen_url="u", account_id=mid)
    monkeypatch.delenv("SHEET_ID__PENSIONMAS", raising=False)
    with pytest.raises(RuntimeError, match="SHEET_ID__PENSIONMAS"):
        approval.aprobar(cx, qid, _escribir_sheet=lambda **kw: 1,
                         _slot_meme=lambda a, s, sl: _ahora())
    # la fila NO quedó aprobada
    assert db.get(cx, "content_queue", qid)["aprobacion"] == "pendiente"


def test_enviar_a_telegram_usa_bot_de_la_marca(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", "tok-p")
    monkeypatch.setenv("TELEGRAM_CHAT_ID__PENSIONMAS", "777")
    urls = []

    class _Resp:
        def raise_for_status(self):
            pass

    def _post(url, data=None, timeout=None):
        urls.append(url)
        return _Resp()

    import requests
    monkeypatch.setattr(requests, "post", _post)
    approval.enviar_a_telegram("hola", "https://x/1.jpg", 5,
                               account_slug="pensionmas")
    assert all("bottok-p/" in u for u in urls)


def test_enviar_sin_token_de_marca_revienta_accionable(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-gdl")  # NO debe usarse
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN__PENSIONMAS"):
        approval.enviar_a_telegram("hola", "u", 5, account_slug="pensionmas")
