"""Daemon: recarga las Applications cuando cambian tokens/chat de marcas."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src import approval_daemon as ad
from tests.test_daemon_multibot import _FakeApp


@dataclass
class _M:
    slug: str


def test_huella_estable_e_independiente_del_orden() -> None:
    a = [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"}),
         (_M("b"), {"TELEGRAM_BOT_TOKEN": "2", "TELEGRAM_CHAT_ID": "y"})]
    assert ad._huella(a) == ad._huella(list(reversed(a)))
    b = [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "z"})]
    assert ad._huella(a) != ad._huella(b)


def test_esperar_detecta_cambio() -> None:
    valores = iter([("v1",), ("v1",), ("v2",)])
    motivo = asyncio.run(ad._esperar_senal_o_cambio(("v1",), lambda: next(valores), cada=0.001))
    assert motivo == "recarga"


def test_correr_devuelve_motivo_y_apaga(monkeypatch) -> None:
    log: list = []
    apps = [_FakeApp("a", log)]

    async def _recarga():
        return "recarga"
    assert asyncio.run(ad.correr(apps, esperar=_recarga)) == "recarga"
    assert "shutdown:a" in log


def test_main_recarga_hasta_senal(tmp_path, monkeypatch) -> None:
    from src import db as db_mod

    conectar_real = db_mod.connect  # capturado ANTES de monkeypatchear: ad.db es db_mod
    rondas = iter([
        [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"})],
        [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"}),
         (_M("b"), {"TELEGRAM_BOT_TOKEN": "2", "TELEGRAM_CHAT_ID": "y"})],
    ])
    construidas: list = []
    motivos = iter(["recarga", "senal"])
    monkeypatch.setattr(ad.poller_lock, "adquirir", lambda: None)
    monkeypatch.setattr(ad.db, "connect", lambda *a, **k: conectar_real(tmp_path / "t.db"))
    monkeypatch.setattr(ad.db, "init_db", lambda cx: None)
    monkeypatch.setattr(ad, "_pares_actuales", lambda: next(rondas))
    monkeypatch.setattr(ad, "construir_app",
                        lambda t, c, slug, interactivo=False: construidas.append(slug) or object())

    async def _correr(apps, *, esperar=None):
        return next(motivos)
    monkeypatch.setattr(ad, "correr", _correr)
    ad.main()
    assert construidas == ["a", "a", "b"]


def test_pares_actuales_no_migra(tmp_path, monkeypatch) -> None:
    from src import db as db_mod

    conectar_real = db_mod.connect  # capturado ANTES de monkeypatchear: ad.db es db_mod
    cx = conectar_real(tmp_path / "t.db")
    db_mod.init_db(cx)
    cx.close()

    llamadas: list = []
    monkeypatch.setattr(ad.db, "init_db", lambda cx: llamadas.append(cx))
    monkeypatch.setattr(ad.db, "connect", lambda: conectar_real(tmp_path / "t.db"))
    monkeypatch.setattr(ad.marcas_mod, "listar", lambda cx: [])
    ad._pares_actuales()
    assert llamadas == []


def test_main_sin_bots_espera_en_vez_de_fallar(tmp_path, monkeypatch) -> None:
    from src import db as db_mod

    conectar_real = db_mod.connect  # capturado ANTES de monkeypatchear: ad.db es db_mod
    rondas = iter([[], [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"})]])
    dormidas: list = []
    monkeypatch.setattr(ad.poller_lock, "adquirir", lambda: None)
    monkeypatch.setattr(ad.db, "connect", lambda *a, **k: conectar_real(tmp_path / "t.db"))
    monkeypatch.setattr(ad.db, "init_db", lambda cx: None)
    monkeypatch.setattr(ad, "_pares_actuales", lambda: next(rondas))
    monkeypatch.setattr(ad, "_dormir", lambda s: dormidas.append(s))
    monkeypatch.setattr(ad, "construir_app", lambda *a, **k: object())

    async def _correr(apps, *, esperar=None):
        return "senal"
    monkeypatch.setattr(ad, "correr", _correr)
    ad.main()
    assert dormidas == [ad.RECARGA_SEG]
