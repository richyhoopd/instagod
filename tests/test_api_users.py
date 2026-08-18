"""Admin: invitar, listar, editar membresías, cerrar sesiones. No-admin → 403."""
from __future__ import annotations

from src import db, users


def _admin(H):
    uid = H.usuario("r@x.com", admin=True)
    H.login(uid)
    return uid


def test_no_admin_403(api_cliente) -> None:
    cli, _, H = api_cliente
    H.login(H.usuario("e@x.com", marcas=[(1, "manager")]))
    assert cli.get("/users").status_code == 403
    assert cli.post("/users/invite", json={"email": "z@x.com"}).status_code == 403


def test_invitar_crea_asigna_y_manda_link(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    _admin(H)
    db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "enviar_magic_link", lambda e, u: enviados.append((e, u)))
    r = cli.post("/users/invite", json={
        "email": "Colab@X.com", "nombre": "Colab",
        "marcas": [{"slug": "pensionmas", "rol": "manager"}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "colab@x.com" and body["marcas"][0]["rol"] == "manager"
    assert enviados and enviados[0][0] == "colab@x.com"
    r = cli.post("/users/invite", json={"email": "colab@x.com"})
    assert r.status_code == 409 and r.json()["error"] == "conflicto"
    r = cli.post("/users/invite", json={"email": "z@x.com",
                                        "marcas": [{"slug": "nope", "rol": "editor"}]})
    assert r.status_code == 404
    r = cli.post("/users/invite", json={"email": "z@x.com",
                                        "marcas": [{"slug": "pensionmas", "rol": "dios"}]})
    assert r.status_code == 422


def test_listar_y_patch(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    _admin(H)
    from api import mail
    monkeypatch.setattr(mail, "enviar_magic_link", lambda e, u: None)
    uid = cli.post("/users/invite", json={"email": "c@x.com",
                                          "marcas": [{"slug": "gdlscene", "rol": "editor"}]}).json()["id"]
    lista = cli.get("/users").json()
    assert [u["email"] for u in lista] == ["r@x.com", "c@x.com"]
    r = cli.patch(f"/users/{uid}", json={"nombre": "Ceci", "marcas": []})
    assert r.status_code == 200 and r.json()["nombre"] == "Ceci" and r.json()["marcas"] == []
    r = cli.patch(f"/users/{uid}", json={"activo": False})
    assert r.json()["activo"] == 0
    assert cli.patch("/users/999", json={"nombre": "x"}).status_code == 404


def test_reinvitar_y_cerrar_sesiones(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    _admin(H)
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "enviar_magic_link", lambda e, u: enviados.append(e))
    uid = H.usuario("c@x.com")
    users.crear_sesion(cx, uid)
    assert cli.post(f"/users/{uid}/reinvitar").status_code == 200 and enviados == ["c@x.com"]
    assert cli.delete(f"/users/{uid}/sessions").json() == {"cerradas": 1}
