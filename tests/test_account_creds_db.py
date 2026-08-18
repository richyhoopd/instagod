"""account_creds: DB (brand_secrets) gana a env con sufijo; env global solo gdlscene."""
from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet

import config
from src import db
from src import secrets_store as ss


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    importlib.reload(config)
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield cx, pid
    cx.close()


def test_db_gana_a_env_sufijo(entorno, monkeypatch) -> None:
    cx, pid = entorno
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "de-env")
    ss.guardar(cx, pid, "IG_ACCESS_TOKEN", "de-db")
    assert config.account_creds("pensionmas")["IG_ACCESS_TOKEN"] == "de-db"


def test_env_sufijo_cuando_db_no_tiene(entorno, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID__PENSIONMAS", "-100")
    assert config.account_creds("pensionmas")["TELEGRAM_CHAT_ID"] == "-100"


def test_marca_nueva_no_hereda_global_ni_con_db(entorno, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-gdl")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    assert config.account_creds("pensionmas")["TELEGRAM_BOT_TOKEN"] is None
    assert config.account_creds("gdlscene")["TELEGRAM_BOT_TOKEN"] == "token-gdl"


def test_gdlscene_db_gana_a_global(entorno, monkeypatch) -> None:
    cx, _ = entorno
    monkeypatch.setenv("SHEET_ID", "sheet-env")
    ss.guardar(cx, 1, "SHEET_ID", "sheet-db")
    assert config.account_creds("gdlscene")["SHEET_ID"] == "sheet-db"


def test_claves_llm_e_imagenes_presentes(entorno) -> None:
    creds = config.account_creds("pensionmas")
    for k in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "PEXELS_API_KEY",
              "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY"):
        assert k in creds


def test_sin_master_key_ignora_db(entorno, monkeypatch) -> None:
    cx, pid = entorno
    ss.guardar(cx, pid, "IG_USER_ID", "db")
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "env")
    assert config.account_creds("pensionmas")["IG_USER_ID"] == "env"
