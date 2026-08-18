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


@pytest.fixture()
def api_cliente(tmp_path, monkeypatch):
    """TestClient de la API con DB temporal. Devuelve (cliente, cx, helpers)."""
    import importlib

    from fastapi.testclient import TestClient

    from src import db, users

    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    importlib.reload(config)
    # Limpiar env vars de marcas DESPUÉS del reload (que carga .env)
    for key in ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_SCRAPER_SESSIONID",
                "IG_SCRAPER_UA", "SHEET_ID",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL",
                "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    monkeypatch.setattr(config, "APP_URL", "http://front.test")
    monkeypatch.setattr(config, "ENV", "dev")
    from api import app as app_mod
    importlib.reload(app_mod)
    cx = db.connect(tmp_path / "api.db")
    db.init_db(cx)
    cli = TestClient(app_mod.app, base_url="http://api.test")

    class H:
        """Atajos: crear usuarios y loguearlos (cookie de sesión)."""

        @staticmethod
        def usuario(email, *, admin=False, marcas=()):
            uid = users.crear_usuario(cx, email, is_admin=admin)
            for account_id, rol in marcas:
                users.asignar_marca(cx, uid, account_id, rol)
            return uid

        @staticmethod
        def login(uid):
            tok = users.crear_sesion(cx, uid)
            cli.cookies.set("instagod_session", tok)
            return tok

        @staticmethod
        def logout():
            cli.cookies.clear()

    yield cli, cx, H
    cx.close()
