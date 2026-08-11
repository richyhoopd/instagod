"""Daemon multi-bot: filtrado de marcas, ciclo de vida y latido multi-app."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from src import approval_daemon as ad


@dataclass
class _M:
    slug: str


def _creds(mapa):
    return lambda slug: mapa.get(slug, {"TELEGRAM_BOT_TOKEN": None,
                                        "TELEGRAM_CHAT_ID": None})


def test_marcas_con_bot_filtra_y_avisa(capsys) -> None:
    mapa = {"gdlscene": {"TELEGRAM_BOT_TOKEN": "t1", "TELEGRAM_CHAT_ID": "1"},
            "pensionmas": {"TELEGRAM_BOT_TOKEN": None, "TELEGRAM_CHAT_ID": None}}
    pares = ad.marcas_con_bot([_M("gdlscene"), _M("pensionmas")],
                              creds_de=_creds(mapa))
    assert [m.slug for m, _ in pares] == ["gdlscene"]
    assert "TELEGRAM_BOT_TOKEN__PENSIONMAS" in capsys.readouterr().out


@dataclass
class _FakeUpdater:
    running: bool = False
    llamadas: list = field(default_factory=list)

    async def start_polling(self, **kw):
        self.running = True
        self.llamadas.append(("poll", kw))

    async def stop(self):
        self.running = False
        self.llamadas.append(("stop_poll", None))


@dataclass
class _FakeApp:
    nombre: str
    log: list
    updater: _FakeUpdater = field(default_factory=_FakeUpdater)

    async def initialize(self):
        self.log.append(f"init:{self.nombre}")

    async def start(self):
        self.log.append(f"start:{self.nombre}")

    async def stop(self):
        self.log.append(f"stop:{self.nombre}")

    async def shutdown(self):
        self.log.append(f"shutdown:{self.nombre}")


def test_correr_arranca_todas_y_apaga_en_orden_inverso(monkeypatch) -> None:
    log: list = []
    apps = [_FakeApp("a", log), _FakeApp("b", log)]

    async def _sin_espera():
        return None

    monkeypatch.setattr(ad, "_esperar_senal", _sin_espera)
    asyncio.run(ad.correr(apps))
    assert log[:4] == ["init:a", "init:b", "start:a", "start:b"]
    assert all(u.llamadas[0][0] == "poll" for u in (apps[0].updater, apps[1].updater))
    # apagado inverso: b antes que a
    assert log.index("stop:b") < log.index("stop:a")
    assert log.index("shutdown:b") < log.index("shutdown:a")


def test_correr_shutdown_tolera_fallos(monkeypatch) -> None:
    log: list = []
    apps = [_FakeApp("a", log), _FakeApp("b", log)]

    async def _boom():
        raise RuntimeError("stop roto")

    apps[1].stop = _boom  # el fallo de b NO debe impedir apagar a

    async def _sin_espera():
        return None

    monkeypatch.setattr(ad, "_esperar_senal", _sin_espera)
    asyncio.run(ad.correr(apps))
    assert "stop:a" in log and "shutdown:a" in log


def test_latido_solo_si_todos_los_updaters_corren(monkeypatch) -> None:
    latidos = []
    monkeypatch.setattr(ad.daemon_health, "escribir_latido",
                        lambda: latidos.append(1))
    log: list = []
    a, b = _FakeApp("a", log), _FakeApp("b", log)
    a.updater.running = True
    b.updater.running = False
    assert ad._todos_corriendo([a, b]) is False
    b.updater.running = True
    assert ad._todos_corriendo([a, b]) is True
