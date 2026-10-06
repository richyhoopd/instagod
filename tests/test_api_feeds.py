"""API mínima de feeds, entidades y recetas por marca."""
from __future__ import annotations

from src import db, feeds, recetas
from tests.fixtures.feed_mwrs import item


def _marca(api_cliente, rol="manager"):
    client, cx, H = api_cliente
    aid = db.insert(cx, "accounts", slug="melaquecapital", ig_handle="mc",
                    nombre="MWRS", ciudad="Melaque")
    recetas.sembrar(cx, aid, recetas.SEMILLA_MELAQUECAPITAL)
    H.login(H.usuario("mc@x.mx", marcas=[(aid, rol)]))
    return client, cx, aid


def test_alta_lista_y_sync_de_feed(api_cliente):
    client, cx, aid = _marca(api_cliente)
    url = "https://melaquecapital.com/api/instagod-feed"
    r = client.post("/brands/melaquecapital/feeds", json={"url": url})
    assert r.status_code == 201, r.text
    fid = r.json()["id"]
    assert client.post("/brands/melaquecapital/feeds", json={"url": url}).status_code == 409
    assert client.post("/brands/melaquecapital/feeds",
                       json={"url": "/relativa/feed"}).status_code == 422
    assert [f["id"] for f in client.get("/brands/melaquecapital/feeds").json()] == [fid]
    r = client.post(f"/brands/melaquecapital/feeds/{fid}/sync")
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert job["tipo"] == "feeds.sync" and job["account_id"] == aid
    assert client.post("/brands/melaquecapital/feeds/999/sync").status_code == 404


def test_editor_no_registra_feeds(api_cliente):
    client, _, _ = _marca(api_cliente, rol="editor")
    r = client.post("/brands/melaquecapital/feeds",
                    json={"url": "https://x.com/feed"})
    assert r.status_code == 403


def test_entidades_recetas_y_generar(api_cliente):
    client, cx, aid = _marca(api_cliente)
    eid, _ = feeds.upsert_item(cx, aid, 1, item())
    ents = client.get("/brands/melaquecapital/entidades").json()
    assert ents[0]["id"] == eid and ents[0]["unverified"] == ["regimen"]
    assert ents[0]["facts"]["m2"] == 300 and ents[0]["media"] == 2
    assert len(client.get("/brands/melaquecapital/recetas").json()) == 3
    r = client.post("/brands/melaquecapital/recetas/ficha-carrusel/generar",
                    json={"entidad_id": eid})
    assert r.status_code == 202
    assert db.get(cx, "jobs", r.json()["job_id"])["tipo"] == "receta.generar"
    assert client.post("/brands/melaquecapital/recetas/nope/generar",
                       json={"entidad_id": eid}).status_code == 404
    assert client.post("/brands/melaquecapital/recetas/ficha-carrusel/generar",
                       json={"entidad_id": 999}).status_code == 404
