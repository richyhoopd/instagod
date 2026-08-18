"""CLI de arranque: master key, admin inicial, importar secretos de env a DB."""
from __future__ import annotations

from cryptography.fernet import Fernet

import config
from api.bootstrap import asegurar_admin, importar_env, nueva_master_key
from src import db, users
from src import secrets_store as ss


def test_nueva_master_key_es_fernet() -> None:
    Fernet(nueva_master_key().encode())


def test_asegurar_admin_idempotente(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    uid, tok = asegurar_admin(cx, "R@x.com", "Ricardo")
    assert users.por_id(cx, uid)["is_admin"] == 1
    uid2, tok2 = asegurar_admin(cx, "r@x.com")
    assert uid2 == uid and tok2 != tok
    assert users.consumir_magic_link(cx, tok2) == uid


def test_importar_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    env = {"IG_USER_ID": "gdl-user", "TELEGRAM_BOT_TOKEN": "gdl-tok",
           "IG_USER_ID__PENSIONMAS": "p-user", "OTRA_COSA": "x"}
    res = importar_env(cx, env)
    assert res == {"gdlscene": ["IG_USER_ID", "TELEGRAM_BOT_TOKEN"], "pensionmas": ["IG_USER_ID"]}
    assert ss.leer(cx, 1, "IG_USER_ID") == "gdl-user"
    assert ss.leer(cx, pid, "IG_USER_ID") == "p-user"
    assert ss.leer(cx, pid, "TELEGRAM_BOT_TOKEN") is None      # no hereda global
    env["IG_USER_ID__PENSIONMAS"] = "cambiado"
    assert importar_env(cx, env) == {"gdlscene": [], "pensionmas": []}
    assert importar_env(cx, env, forzar=True)["pensionmas"] == ["IG_USER_ID"]
    assert ss.leer(cx, pid, "IG_USER_ID") == "cambiado"
