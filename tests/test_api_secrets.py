"""Secretos por marca vía API: solo manager+, nunca se devuelve el valor."""
from __future__ import annotations

from cryptography.fernet import Fernet

import config
from src import db
from src import secrets_store as ss


def _marca(cx):
    return db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")


def test_sin_master_key_503(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.put("/brands/pensionmas/secrets/IG_USER_ID", json={"valor": "1"})
    assert r.status_code == 503 and r.json()["error"] == "secretos_apagados"


def test_editor_403_manager_ok_valor_nunca_sale(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.get("/brands/pensionmas/secrets").status_code == 403
    H.logout()
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.put("/brands/pensionmas/secrets/TELEGRAM_BOT_TOKEN", json={"valor": "123456:ABCDEF"})
    assert r.status_code == 200
    assert r.json() == {"clave": "TELEGRAM_BOT_TOKEN", "configurada": True,
                        "ultimos4": "CDEF", "updated_at": r.json()["updated_at"]}
    lista = cli.get("/brands/pensionmas/secrets").json()
    assert "123456" not in str(lista) and len(lista) == len(ss.CLAVES)
    assert ss.leer(cx, pid, "TELEGRAM_BOT_TOKEN") == "123456:ABCDEF"
    assert cli.put("/brands/pensionmas/secrets/PASSWORD", json={"valor": "x"}).status_code == 404
    assert cli.put("/brands/pensionmas/secrets/IG_USER_ID", json={"valor": " "}).status_code == 422
    assert cli.delete("/brands/pensionmas/secrets/TELEGRAM_BOT_TOKEN").status_code == 204
    assert cli.delete("/brands/pensionmas/secrets/TELEGRAM_BOT_TOKEN").status_code == 404


def test_aislamiento_entre_marcas(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    assert cli.get("/brands/gdlscene/secrets").status_code == 403
    cli.put("/brands/pensionmas/secrets/IG_USER_ID", json={"valor": "777"})
    assert config.account_creds("gdlscene")["IG_USER_ID"] is None
    assert config.account_creds("pensionmas")["IG_USER_ID"] == "777"
