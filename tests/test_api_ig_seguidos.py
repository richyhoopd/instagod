"""API de la fuente «Seguidos de IG». Sin red: solo encola jobs y cura cuentas."""
from __future__ import annotations

import json

import pytest

from src import db
from src.assets import ig_seguidos


@pytest.fixture
def marcas(api_cliente):
    cli, cx, H = api_cliente
    a = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    b = db.insert(cx, "accounts", slug="daisies", ig_handle="@d", nombre="D", ciudad="CDMX")
    return cli, cx, H, a, b


def test_listar_y_curar(marcas) -> None:
    cli, cx, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    r = cli.post("/brands/pensionmas/fuentes/ig/cuentas",
                 json={"ig_handle": "@Cafe.Tacuba", "estado": "activa"})
    assert r.status_code == 200
    assert r.json()["ig_handle"] == "cafe.tacuba" and r.json()["origen"] == "manual"
    r = cli.get("/brands/pensionmas/fuentes/ig/cuentas", params={"estado": "activa"})
    assert [c["ig_handle"] for c in r.json()] == ["cafe.tacuba"]


def test_handle_invalido_422(marcas) -> None:
    cli, _, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    r = cli.post("/brands/pensionmas/fuentes/ig/cuentas",
                 json={"ig_handle": "../etc", "estado": "activa"})
    assert r.status_code == 422 and r.json()["campo"] == "ig_handle"
    r = cli.post("/brands/pensionmas/fuentes/ig/importar-seguidos", json={"semilla": "a b"})
    assert r.status_code == 422 and r.json()["campo"] == "semilla"


def test_estado_invalido_422(marcas) -> None:
    cli, _, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    r = cli.get("/brands/pensionmas/fuentes/ig/cuentas", params={"estado": "todas"})
    assert r.status_code == 422


def test_encola_jobs(marcas) -> None:
    cli, cx, H, a, _ = marcas
    uid = H.usuario("m@x.com", marcas=((a, "manager"),))
    H.login(uid)
    r = cli.post("/brands/pensionmas/fuentes/ig/importar-seguidos",
                 json={"semilla": "@PensionMas", "limite": 100})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert (job["tipo"], job["account_id"], job["creado_por"]) == ("ig.importar_seguidos", a, uid)
    assert json.loads(job["payload_json"]) == {"semilla": "pensionmas", "limite": 100}
    r = cli.post("/brands/pensionmas/fuentes/ig/ingerir", json={"por_cuenta": 8})
    assert r.status_code == 202
    assert json.loads(db.get(cx, "jobs", r.json()["job_id"])["payload_json"]) == {"por_cuenta": 8}


def test_limites_de_payload(marcas) -> None:
    cli, _, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    assert cli.post("/brands/pensionmas/fuentes/ig/ingerir",
                    json={"por_cuenta": 500}).status_code == 422
    assert cli.post("/brands/pensionmas/fuentes/ig/importar-seguidos",
                    json={"semilla": "x", "limite": 100000}).status_code == 422


def test_editor_lee_pero_no_encola(marcas) -> None:
    cli, cx, H, a, _ = marcas
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "candidata")
    H.login(H.usuario("e@x.com", marcas=((a, "editor"),)))
    assert cli.get("/brands/pensionmas/fuentes/ig/cuentas").status_code == 200
    assert cli.post("/brands/pensionmas/fuentes/ig/ingerir", json={}).status_code == 403
    assert cli.post("/brands/pensionmas/fuentes/ig/cuentas",
                    json={"ig_handle": "x", "estado": "activa"}).status_code == 403


def test_router_otra_marca_403(marcas) -> None:
    """Review Focus 4."""
    cli, cx, H, a, b = marcas
    ig_seguidos.fijar_estado(cx, b, "secreta.de.daisies", "activa")
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    assert cli.get("/brands/daisies/fuentes/ig/cuentas").status_code == 403
    assert cli.post("/brands/daisies/fuentes/ig/ingerir", json={}).status_code == 403
    assert cli.post("/brands/daisies/fuentes/ig/cuentas",
                    json={"ig_handle": "x", "estado": "activa"}).status_code == 403
