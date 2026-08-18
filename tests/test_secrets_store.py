"""Secretos por marca: cifrado, CRUD, metadatos sin valor, resolución por slug."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

import config
from src import db
from src import secrets_store as ss


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield c
    c.close()


def test_round_trip_cifrado(cx) -> None:
    tok = ss.cifrar("hola")
    assert tok != "hola" and ss.descifrar(tok) == "hola"


def test_guardar_leer_borrar(cx) -> None:
    ss.guardar(cx, 2, "IG_ACCESS_TOKEN", "abcd1234", user_id=None)
    assert ss.leer(cx, 2, "IG_ACCESS_TOKEN") == "abcd1234"
    crudo = cx.execute("SELECT valor_cifrado FROM brand_secrets").fetchone()[0]
    assert "abcd1234" not in crudo
    ss.guardar(cx, 2, "IG_ACCESS_TOKEN", "nuevo")          # upsert
    assert ss.leer(cx, 2, "IG_ACCESS_TOKEN") == "nuevo"
    assert ss.borrar(cx, 2, "IG_ACCESS_TOKEN") is True
    assert ss.borrar(cx, 2, "IG_ACCESS_TOKEN") is False
    assert ss.leer(cx, 2, "IG_ACCESS_TOKEN") is None


def test_clave_desconocida_y_valor_vacio(cx) -> None:
    with pytest.raises(KeyError):
        ss.guardar(cx, 2, "PASSWORD_ROOT", "x")
    with pytest.raises(ValueError):
        ss.guardar(cx, 2, "IG_USER_ID", "   ")


def test_listar_meta_no_expone_valor(cx) -> None:
    ss.guardar(cx, 2, "TELEGRAM_BOT_TOKEN", "123456:ABCDEF")
    meta = {m["clave"]: m for m in ss.listar_meta(cx, 2)}
    assert set(meta) == set(ss.CLAVES)
    assert meta["TELEGRAM_BOT_TOKEN"]["configurada"] is True
    assert meta["TELEGRAM_BOT_TOKEN"]["ultimos4"] == "CDEF"
    assert meta["TELEGRAM_BOT_TOKEN"]["updated_at"]
    assert meta["IG_USER_ID"] == {"clave": "IG_USER_ID", "configurada": False,
                                  "ultimos4": None, "updated_at": None}
    assert "123456" not in str(meta)


def test_leer_todos_y_creds_de_slug(cx) -> None:
    ss.guardar(cx, 2, "IG_USER_ID", "111")
    ss.guardar(cx, 2, "LLM_API_KEY", "sk-x")
    assert ss.leer_todos(cx, 2) == {"IG_USER_ID": "111", "LLM_API_KEY": "sk-x"}
    assert ss.creds_de_slug("pensionmas") == {"IG_USER_ID": "111", "LLM_API_KEY": "sk-x"}
    assert ss.creds_de_slug("no_existe") == {}


def test_sin_master_key_todo_apagado(cx, monkeypatch) -> None:
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    assert ss.habilitado() is False
    assert ss.creds_de_slug("pensionmas") == {}
    with pytest.raises(ss.SinMasterKey):
        ss.guardar(cx, 2, "IG_USER_ID", "1")


def test_version_marcas(cx) -> None:
    assert ss.version_marcas(cx) == {}
    ss.guardar(cx, 2, "IG_USER_ID", "1")
    v = ss.version_marcas(cx)
    assert list(v) == [2] and v[2]
