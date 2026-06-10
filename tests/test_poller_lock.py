"""Blindaje anti-doble-poller: el lock compartido del ÚNICO getUpdates.

Telegram solo permite un getUpdates por bot; dos pollers vivos chocan con
`telegram.error.Conflict`. Estos tests fijan el contrato del lock que el daemon
adquiere y que todo otro entrypoint exige libre antes de abrir su poller.
"""
from __future__ import annotations

import os

import pytest

from src import poller_lock


def _lock_en(monkeypatch, tmp_path):
    p = tmp_path / "poller.lock"
    monkeypatch.setattr(poller_lock, "LOCK_PATH", p)
    return p


def test_daemon_pid_none_sin_lock(monkeypatch, tmp_path) -> None:
    _lock_en(monkeypatch, tmp_path)
    assert poller_lock.daemon_pid() is None


def test_daemon_pid_none_si_lock_huerfano(monkeypatch, tmp_path) -> None:
    p = _lock_en(monkeypatch, tmp_path)
    p.write_text("2147483647")  # PID que no corre → lock huérfano
    assert poller_lock.daemon_pid() is None


def test_daemon_pid_devuelve_pid_vivo(monkeypatch, tmp_path) -> None:
    p = _lock_en(monkeypatch, tmp_path)
    p.write_text(str(os.getpid()))  # nosotros estamos vivos
    assert poller_lock.daemon_pid() == os.getpid()


def test_exigir_daemon_libre_no_aborta_sin_daemon(monkeypatch, tmp_path) -> None:
    _lock_en(monkeypatch, tmp_path)
    poller_lock.exigir_daemon_libre("test")  # no debe lanzar


def test_exigir_daemon_libre_aborta_con_daemon_vivo(monkeypatch, tmp_path) -> None:
    p = _lock_en(monkeypatch, tmp_path)
    p.write_text(str(os.getpid()))
    with pytest.raises(SystemExit):
        poller_lock.exigir_daemon_libre("test")


def test_adquirir_toma_lock_si_libre(monkeypatch, tmp_path) -> None:
    p = _lock_en(monkeypatch, tmp_path)
    poller_lock.adquirir()
    assert p.read_text().strip() == str(os.getpid())


def test_adquirir_pisa_lock_huerfano(monkeypatch, tmp_path) -> None:
    p = _lock_en(monkeypatch, tmp_path)
    p.write_text("2147483647")  # huérfano
    poller_lock.adquirir()
    assert p.read_text().strip() == str(os.getpid())


def test_adquirir_aborta_si_daemon_vivo(monkeypatch, tmp_path) -> None:
    p = _lock_en(monkeypatch, tmp_path)
    # Otro PID vivo distinto del nuestro: el PID de init (1) siempre corre.
    p.write_text("1")
    with pytest.raises(SystemExit):
        poller_lock.adquirir()
