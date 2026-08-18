"""Marcas: visibilidad por rol, alta admin, detalle y edición básica."""
from __future__ import annotations

from src import db


def test_lista_segun_rol(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    lista = cli.get("/brands").json()
    assert [b["slug"] for b in lista] == ["pensionmas"] and lista[0]["rol"] == "editor"
    assert "TELEGRAM_BOT_TOKEN" in lista[0]["creds_faltantes"]
    H.logout()
    H.login(H.usuario("r@x.com", admin=True))
    assert [b["slug"] for b in cli.get("/brands").json()] == ["gdlscene", "pensionmas"]


def test_alta_solo_admin_y_validaciones(api_cliente) -> None:
    cli, _, H = api_cliente
    H.login(H.usuario("m@x.com", marcas=[(1, "manager")]))
    assert cli.post("/brands", json={"slug": "x1", "nombre": "X", "ig_handle": "@x"}).status_code == 403
    H.logout()
    H.login(H.usuario("r@x.com", admin=True))
    r = cli.post("/brands", json={"slug": "Melaque Capital", "nombre": "M", "ig_handle": "@m"})
    assert r.status_code == 422 and r.json()["campo"] == "slug"
    r = cli.post("/brands", json={"slug": "melaque", "nombre": "Melaque", "ig_handle": "melaque"})
    assert r.status_code == 201 and r.json()["ig_handle"] == "@melaque"
    r = cli.post("/brands", json={"slug": "melaque", "nombre": "Otra", "ig_handle": "@o"})
    assert r.status_code == 409


def test_nombre_y_handle_no_vacios(api_cliente) -> None:
    cli, cx, H = api_cliente
    H.login(H.usuario("r@x.com", admin=True))
    r = cli.post("/brands", json={"slug": "n1", "nombre": "", "ig_handle": "@n"})
    assert r.status_code == 422 and r.json()["campo"] == "nombre"

    db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    r = cli.patch("/brands/pensionmas", json={"nombre": "   "})
    assert r.status_code == 422 and r.json()["campo"] == "nombre"
    r = cli.patch("/brands/pensionmas", json={"ig_handle": ""})
    assert r.status_code == 422 and r.json()["campo"] == "ig_handle"


def test_detalle_y_patch(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    eid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(eid)
    assert cli.get("/brands/pensionmas").json()["nombre"] == "P"
    assert cli.get("/brands/gdlscene").status_code == 403
    assert cli.get("/brands/nope").status_code == 404
    assert cli.patch("/brands/pensionmas", json={"nombre": "PP"}).status_code == 403
    H.logout()
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.patch("/brands/pensionmas", json={"nombre": "Pensión+", "color_marca": "#112233"})
    assert r.status_code == 200 and r.json()["nombre"] == "Pensión+"
    assert cli.patch("/brands/pensionmas", json={"activa": False}).status_code == 403
    assert cli.patch("/brands/pensionmas", json={"color_marca": "rojo"}).status_code == 422
