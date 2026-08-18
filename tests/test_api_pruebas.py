"""Botones 'Probar' de conexiones: creds de la marca, cred faltante → 422, remoto → 502."""
from __future__ import annotations

from src import db


def _setup(api_cliente, monkeypatch, **env):
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    for k, v in env.items():
        monkeypatch.setenv(f"{k}__PENSIONMAS", v)
    return cli


def test_telegram_ok_y_faltante(api_cliente, monkeypatch) -> None:
    from api.routers import pruebas
    llamadas = []
    monkeypatch.setattr(pruebas, "_telegram_send",
                        lambda t, c, txt: llamadas.append((t, c, txt)) or {"ok": True})
    cli = _setup(api_cliente, monkeypatch, TELEGRAM_BOT_TOKEN="1:A", TELEGRAM_CHAT_ID="-9")
    r = cli.post("/brands/pensionmas/telegram/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert llamadas[0][:2] == ("1:A", "-9") and "P" in llamadas[0][2]
    monkeypatch.delenv("TELEGRAM_CHAT_ID__PENSIONMAS")
    r = cli.post("/brands/pensionmas/telegram/test")
    assert r.status_code == 422 and r.json()["campo"] == "TELEGRAM_CHAT_ID"


def test_instagram_502_si_falla(api_cliente, monkeypatch) -> None:
    from api.routers import pruebas

    def _boom(token):
        raise RuntimeError("token expirado")
    monkeypatch.setattr(pruebas, "_ig_me", _boom)
    cli = _setup(api_cliente, monkeypatch, IG_ACCESS_TOKEN="tok_abc123", IG_USER_ID="1")
    r = cli.post("/brands/pensionmas/instagram/test")
    assert r.status_code == 502 and "token expirado" in r.json()["detalle"]


def test_llm_usa_creds_de_marca_o_global(api_cliente, monkeypatch) -> None:
    import config
    from api.routers import pruebas
    monkeypatch.setattr(pruebas, "_llm_ping", lambda p, k, m: f"pong:{p}:{m}")
    cli = _setup(api_cliente, monkeypatch, LLM_PROVIDER="claude", LLM_API_KEY="sk",
                 LLM_MODEL="claude-sonnet-4-6")
    assert cli.post("/brands/pensionmas/llm/test").json()["respuesta"] == "pong:claude:claude-sonnet-4-6"
    for k in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(f"{k}__PENSIONMAS")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "global")
    r = cli.post("/brands/pensionmas/llm/test").json()
    assert r["provider"] == "deepseek" and r["ok"] is True
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", None)
    assert cli.post("/brands/pensionmas/llm/test").status_code == 422


def test_editor_403(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.post("/brands/pensionmas/telegram/test").status_code == 403


def test_502_no_filtra_token(api_cliente, monkeypatch) -> None:
    from api.routers import pruebas

    def _boom(token):
        raise RuntimeError(f"fallo con token={token}-secreto-123 en la url")
    monkeypatch.setattr(pruebas, "_ig_me", _boom)
    cli = _setup(api_cliente, monkeypatch, IG_ACCESS_TOKEN="t-secreto-123", IG_USER_ID="1")
    r = cli.post("/brands/pensionmas/instagram/test")
    assert r.status_code == 502
    assert "t-secreto-123" not in r.text
    assert "***" in r.json()["detalle"]


def test_502_http_error_solo_status(api_cliente, monkeypatch) -> None:
    import requests

    from api.routers import pruebas

    def _boom(token):
        resp = requests.Response()
        resp.status_code = 400
        resp.url = "https://graph.instagram.com/me?access_token=t-secreto-123"
        err = requests.HTTPError("400 Client Error", response=resp)
        raise err
    monkeypatch.setattr(pruebas, "_ig_me", _boom)
    cli = _setup(api_cliente, monkeypatch, IG_ACCESS_TOKEN="t-secreto-123", IG_USER_ID="1")
    r = cli.post("/brands/pensionmas/instagram/test")
    assert r.status_code == 502
    detalle = r.json()["detalle"]
    assert "El servicio respondió HTTP 400" in detalle
    assert "t-secreto-123" not in r.text
