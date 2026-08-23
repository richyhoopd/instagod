"""API: magic link, sesión por cookie, /me, /auth/verify, /health, errores JSON."""
from __future__ import annotations

from src import db, users


def test_health(api_cliente) -> None:
    cli, _, _ = api_cliente
    r = cli.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_me_sin_sesion_401_json(api_cliente) -> None:
    cli, _, _ = api_cliente
    r = cli.get("/me")
    assert r.status_code == 401
    assert r.json() == {"error": "no_autenticado", "detalle": "Inicia sesión", "campo": None}


def test_magic_link_flujo_completo(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "_post_resend", lambda payload: enviados.append(payload))
    monkeypatch.setattr(mail.config, "RESEND_API_KEY", "re_test")
    uid = H.usuario("ana@x.com", marcas=[(1, "editor")])
    r = cli.post("/auth/magic-link", json={"email": "Ana@X.com"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(enviados) == 1 and enviados[0]["to"] == ["ana@x.com"]
    url = enviados[0]["_url"]
    assert url.startswith("http://api.test/auth/callback?token=")
    # GET no consume el token (vistas previas de chats/correo): devuelve la página que
    # hace el POST; el link sigue válido después.
    r = cli.get(url, follow_redirects=False)
    assert r.status_code == 200 and 'method="post"' in r.text
    assert "set-cookie" not in r.headers
    token = url.split("token=", 1)[1]
    r = cli.post(url, data={"token": token}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "http://front.test/brands"
    assert "instagod_session=" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"]
    me = cli.get("/me").json()
    assert me["email"] == "ana@x.com" and me["is_admin"] is False
    assert me["marcas"][0]["slug"] == "gdlscene" and me["marcas"][0]["rol"] == "editor"
    r = cli.post(url, data={"token": token}, follow_redirects=False)   # segundo uso: inválido
    assert r.headers["location"] == "http://front.test/login?error=link_invalido"
    assert users.por_id(cx, uid)["last_login"]


def test_magic_link_email_desconocido_responde_igual_y_no_manda(api_cliente, monkeypatch) -> None:
    cli, _, _ = api_cliente
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "_post_resend", lambda payload: enviados.append(payload))
    r = cli.post("/auth/magic-link", json={"email": "nadie@x.com"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert enviados == []


def test_magic_link_rate_limit(api_cliente, monkeypatch) -> None:
    cli, _, H = api_cliente
    from api import mail
    monkeypatch.setattr(mail, "_post_resend", lambda payload: None)
    H.usuario("ana@x.com")
    H.usuario("bea@x.com")
    for _ in range(5):
        assert cli.post("/auth/magic-link", json={"email": "ana@x.com"}).status_code == 200
    r = cli.post("/auth/magic-link", json={"email": "ana@x.com"})
    assert r.status_code == 429 and r.json()["error"] == "demasiados_intentos"
    # el límite por IP (ya agotado) también bloquea a otro email desde el mismo cliente
    r2 = cli.post("/auth/magic-link", json={"email": "bea@x.com"})
    assert r2.status_code == 429 and r2.json()["error"] == "demasiados_intentos"


def test_magic_link_rate_limit_por_email(api_cliente, monkeypatch) -> None:
    cli, _, H = api_cliente
    from api import mail
    monkeypatch.setattr(mail, "_post_resend", lambda payload: None)
    H.usuario("ana@x.com")
    H.usuario("bea@x.com")
    # 3 para ana, 2 para bea: ningún email individual toca su tope de 5
    emails = ["ana@x.com", "bea@x.com", "ana@x.com", "bea@x.com", "ana@x.com"]
    for email in emails:
        assert cli.post("/auth/magic-link", json={"email": email}).status_code == 200
    # pero el límite por IP (5 en total desde el mismo cliente) ya se agotó
    r = cli.post("/auth/magic-link", json={"email": "bea@x.com"})
    assert r.status_code == 429 and r.json()["error"] == "demasiados_intentos"


def test_magic_link_en_dev_sin_resend_imprime_url(api_cliente, capsys) -> None:
    cli, _, H = api_cliente
    H.usuario("ana@x.com")
    cli.post("/auth/magic-link", json={"email": "ana@x.com"})
    assert "/auth/callback?token=" in capsys.readouterr().out


def test_logout_y_verify(api_cliente) -> None:
    cli, _, H = api_cliente
    uid = H.usuario("r@x.com", admin=True)
    assert cli.get("/auth/verify").status_code == 401
    H.login(uid)
    assert cli.get("/auth/verify").status_code == 200
    assert cli.post("/auth/logout").status_code == 200
    assert cli.get("/me").status_code == 401


def test_verify_no_admin_401(api_cliente) -> None:
    cli, _, H = api_cliente
    H.login(H.usuario("e@x.com", marcas=[(1, "manager")]))
    assert cli.get("/auth/verify").status_code == 401


def test_usuario_inactivo_pierde_sesion(api_cliente) -> None:
    cli, cx, H = api_cliente
    uid = H.usuario("e@x.com")
    H.login(uid)
    db.update(cx, "users", uid, activo=0)
    assert cli.get("/me").status_code == 401


def test_cors_solo_app_url(api_cliente) -> None:
    cli, _, _ = api_cliente
    r = cli.options("/health", headers={"Origin": "http://front.test",
                                        "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") == "http://front.test"
    r2 = cli.options("/health", headers={"Origin": "http://otro.test",
                                         "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r2.headers


def test_magic_link_ignora_header_host(api_cliente, monkeypatch) -> None:
    cli, _, H = api_cliente
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "_post_resend", lambda payload: enviados.append(payload))
    monkeypatch.setattr(mail.config, "RESEND_API_KEY", "re_test")
    H.usuario("ana@x.com")
    r = cli.post("/auth/magic-link", json={"email": "ana@x.com"},
                headers={"Host": "evil.example.com"})
    assert r.status_code == 200
    url = enviados[0]["_url"]
    assert url.startswith("http://api.test/auth/callback?token=")
    assert "evil.example.com" not in url
