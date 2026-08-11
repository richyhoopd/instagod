"""Daemon multi-bot: filtrado de marcas, ciclo de vida y latido multi-app."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

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


def test_construir_app_no_interactivo_chat_id_no_numerico_no_truena() -> None:
    # pensionmas u otra marca no-interactiva no necesita chat_id numérico:
    # int(chat_id) solo se evalúa si interactivo=True (único uso real).
    app = ad.construir_app("123:AAA", "@canal", "pensionmas", interactivo=False)
    assert app.bot_data["slug"] == "pensionmas"


def test_construir_app_interactivo_chat_id_no_numerico_lanza() -> None:
    with pytest.raises(ValueError):
        ad.construir_app("123:AAA", "@canal", "gdlscene", interactivo=True)


@dataclass
class _FakeUpdater:
    running: bool = False
    llamadas: list = field(default_factory=list)
    # nombre/log opcionales: solo los usa el test de orden latido-vs-polling,
    # que necesita anotar "poll:<nombre>" en el MISMO log que init/start/stop.
    nombre: str = ""
    log: list | None = None

    async def start_polling(self, **kw):
        # simula la suspensión real de red de PTB: sin este await, el fake
        # correría sin ceder el loop y el test de orden sería no determinista.
        await asyncio.sleep(0)
        self.running = True
        self.llamadas.append(("poll", kw))
        if self.log is not None:
            self.log.append(f"poll:{self.nombre}")

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


def test_correr_latido_arranca_antes_del_polling(monkeypatch) -> None:
    log: list = []
    a = _FakeApp("a", log, updater=_FakeUpdater(nombre="a", log=log))
    b = _FakeApp("b", log, updater=_FakeUpdater(nombre="b", log=log))

    async def _latido_fake(apps):
        log.append("latido")
        await asyncio.sleep(3600)

    monkeypatch.setattr(ad, "_latido_loop_multi", _latido_fake)

    async def _sin_espera():
        return None

    monkeypatch.setattr(ad, "_esperar_senal", _sin_espera)
    asyncio.run(ad.correr([a, b]))
    idx_latido = log.index("latido")
    idx_primer_poll = min(i for i, ev in enumerate(log) if ev.startswith("poll:"))
    assert idx_latido < idx_primer_poll


def test_correr_fallo_de_arranque_apaga_lo_ya_arrancado(monkeypatch) -> None:
    log: list = []
    a = _FakeApp("a", log)
    b = _FakeApp("b", log)

    async def _boom_init():
        raise RuntimeError("token revocado")

    b.initialize = _boom_init

    async def _sin_espera():
        return None

    monkeypatch.setattr(ad, "_esperar_senal", _sin_espera)
    with pytest.raises(RuntimeError, match="token revocado"):
        asyncio.run(ad.correr([a, b]))
    assert "stop:a" in log and "shutdown:a" in log
