"""Fixtures globales: ningún test lee secretos de la DB real."""
from __future__ import annotations

import pytest

import config


@pytest.fixture(autouse=True)
def _sin_master_key_por_default(monkeypatch):
    # Los tests que necesiten cifrado setean su propia llave con
    # monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", <llave>).
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    yield
