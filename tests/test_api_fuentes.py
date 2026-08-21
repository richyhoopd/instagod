"""Router de fuentes (imagen/info), banco de fotos y temas sugeridos."""
from __future__ import annotations

import io

from src import db

_RSS_CFG = {"urls": ["http://feed.example.com/rss"]}
_NEWSAPI_CFG = {"query": "pensiones"}
_IG_CFG = {"cuentas": ["@marca"]}


def _marca(cx, slug="pensionmas"):
    return db.insert(cx, "accounts", slug=slug, ig_handle="@p", nombre="P", ciudad="CDMX")


# ---------- sources: CRUD ----------

def test_sources_lectura_editor_escritura_manager(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.get("/brands/pensionmas/sources")
    assert r.status_code == 200 and r.json() == []

    r = cli.post("/brands/pensionmas/sources",
                json={"kind": "info", "provider": "rss", "config": _RSS_CFG})
    assert r.status_code == 403
    H.logout()

    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.post("/brands/pensionmas/sources",
                json={"kind": "info", "provider": "rss", "config": _RSS_CFG})
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "rss" and body["config"] == _RSS_CFG and body["activa"] == 1

    r = cli.get("/brands/pensionmas/sources?kind=info")
    assert r.status_code == 200 and len(r.json()) == 1


def test_sources_crear_valida_provider_y_config(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    r = cli.post("/brands/pensionmas/sources", json={"kind": "info", "provider": "youtube"})
    assert r.status_code == 422 and r.json()["campo"] == "provider"

    r = cli.post("/brands/pensionmas/sources", json={"kind": "info", "provider": "rss"})
    assert r.status_code == 422 and r.json()["campo"] == "config"


def test_sources_patch_delete_y_ownership(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    otra_id = _marca(cx, "otramarca")
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager"), (otra_id, "manager")]))

    r = cli.post("/brands/pensionmas/sources",
                json={"kind": "info", "provider": "rss", "config": _RSS_CFG})
    sid = r.json()["id"]

    r = cli.patch(f"/brands/pensionmas/sources/{sid}", json={"activa": False})
    assert r.status_code == 200 and r.json()["activa"] == 0

    r = cli.patch(f"/brands/pensionmas/sources/{sid}", json={"config": {"urls": []}})
    assert r.status_code == 422 and r.json()["campo"] == "config"

    # ownership: fuente de otra marca -> 404 (aunque el usuario tenga acceso ahí)
    r = cli.patch(f"/brands/otramarca/sources/{sid}", json={"activa": True})
    assert r.status_code == 404
    r = cli.delete(f"/brands/otramarca/sources/{sid}")
    assert r.status_code == 404

    r = cli.delete(f"/brands/pensionmas/sources/{sid}")
    assert r.status_code == 204
    r = cli.get("/brands/pensionmas/sources")
    assert r.json() == []

    r = cli.delete(f"/brands/pensionmas/sources/{sid}")
    assert r.status_code == 404


def test_sources_orden(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    ids = []
    for cuenta in ("@a", "@b", "@c"):
        r = cli.post("/brands/pensionmas/sources",
                     json={"kind": "imagen", "provider": "ig_accounts",
                           "config": {"cuentas": [cuenta]}})
        ids.append(r.json()["id"])

    nuevo_orden = list(reversed(ids))
    r = cli.put("/brands/pensionmas/sources/orden", json={"ids": nuevo_orden})
    assert r.status_code == 200

    r = cli.get("/brands/pensionmas/sources?kind=imagen")
    assert [f["id"] for f in r.json()] == nuevo_orden

    r = cli.put("/brands/pensionmas/sources/orden", json={"ids": [ids[0]]})
    assert r.status_code == 422 and r.json()["campo"] == "ids"


# ---------- sources: run ----------

def test_sources_run_job_correcto_por_provider(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    casos = [
        ("info", "rss", _RSS_CFG, "sourcing.rss_fetch"),
        ("info", "newsapi", _NEWSAPI_CFG, "sourcing.newsapi_fetch"),
        ("imagen", "ig_accounts", _IG_CFG, "sourcing.ig_scrape"),
    ]
    for kind, provider, cfg, tipo_esperado in casos:
        r = cli.post("/brands/pensionmas/sources", json={"kind": kind, "provider": provider, "config": cfg})
        sid = r.json()["id"]
        r = cli.post(f"/brands/pensionmas/sources/{sid}/run")
        assert r.status_code == 202
        job_id = r.json()["job_id"]
        job = db.get(cx, "jobs", job_id)
        assert job["tipo"] == tipo_esperado and job["account_id"] == pid
        import json as _json
        assert _json.loads(job["payload_json"]) == {"source_id": sid}


def test_sources_run_provider_estatico_422_y_ownership(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    otra_id = _marca(cx, "otramarca")
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager"), (otra_id, "manager")]))

    r = cli.post("/brands/pensionmas/sources", json={"kind": "imagen", "provider": "pexels"})
    sid = r.json()["id"]
    r = cli.post(f"/brands/pensionmas/sources/{sid}/run")
    assert r.status_code == 422

    r = cli.post(f"/brands/otramarca/sources/{sid}/run")
    assert r.status_code == 404

    r = cli.post("/brands/pensionmas/sources/999999/run")
    assert r.status_code == 404

    H.logout()
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post(f"/brands/pensionmas/sources/{sid}/run")
    assert r.status_code == 403


# ---------- fotos ----------

def _png(n=100):
    return b"\x89PNG" + b"0" * n


def test_fotos_upload_list_delete(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    from api.routers import fuentes_api
    monkeypatch.setattr(fuentes_api, "BRANDS_DIR", tmp_path / "brands")

    r = cli.get("/brands/pensionmas/photos")
    assert r.status_code == 200 and r.json() == []

    r = cli.post("/brands/pensionmas/photos",
                files=[("archivos", ("foto.png", io.BytesIO(_png()), "image/png"))])
    assert r.status_code == 200
    guardadas = r.json()["guardadas"]
    assert len(guardadas) == 1
    nombre = guardadas[0]
    assert nombre != "foto.png"  # nombre regenerado server-side

    r = cli.get("/brands/pensionmas/photos")
    assert r.status_code == 200
    fotos = r.json()
    assert len(fotos) == 1
    assert fotos[0]["nombre"] == nombre
    assert fotos[0]["tamano"] == len(_png())
    assert "mtime" in fotos[0] and "url" in fotos[0]

    r = cli.get(f"/brands/pensionmas/files/fotos/{nombre}")
    assert r.status_code == 200 and r.content == _png()
    assert r.headers["x-content-type-options"] == "nosniff"

    r = cli.delete(f"/brands/pensionmas/photos/{nombre}")
    assert r.status_code == 204
    r = cli.get("/brands/pensionmas/photos")
    assert r.json() == []

    r = cli.delete(f"/brands/pensionmas/photos/{nombre}")
    assert r.status_code == 404


def test_fotos_valida_extension_tamano_y_cantidad(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    from api.routers import fuentes_api
    monkeypatch.setattr(fuentes_api, "BRANDS_DIR", tmp_path / "brands")

    r = cli.post("/brands/pensionmas/photos",
                files=[("archivos", ("virus.exe", io.BytesIO(b"MZ.."), "application/octet-stream"))])
    assert r.status_code == 422

    grande = b"0" * (8 * 1024 * 1024 + 1)
    r = cli.post("/brands/pensionmas/photos",
                files=[("archivos", ("grande.jpg", io.BytesIO(grande), "image/jpeg"))])
    assert r.status_code == 422

    muchas = [("archivos", (f"f{i}.jpg", io.BytesIO(_png()), "image/jpeg")) for i in range(11)]
    r = cli.post("/brands/pensionmas/photos", files=muchas)
    assert r.status_code == 422

    r = cli.get("/brands/pensionmas/photos")
    assert r.json() == []  # nada se guardó de los intentos fallidos


def test_fotos_editor_no_puede_mutar(api_cliente, tmp_path, monkeypatch) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    from api.routers import fuentes_api
    monkeypatch.setattr(fuentes_api, "BRANDS_DIR", tmp_path / "brands")

    r = cli.post("/brands/pensionmas/photos",
                files=[("archivos", ("foto.png", io.BytesIO(_png()), "image/png"))])
    assert r.status_code == 403

    r = cli.get("/brands/pensionmas/photos")
    assert r.status_code == 200


def test_fotos_traversal_y_aislamiento_por_marca(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    otra_id = _marca(cx, "otramarca")
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager"), (otra_id, "manager")]))
    from api.routers import fuentes_api
    monkeypatch.setattr(fuentes_api, "BRANDS_DIR", tmp_path / "brands")

    r = cli.post("/brands/pensionmas/photos",
                files=[("archivos", ("foto.png", io.BytesIO(_png()), "image/png"))])
    nombre = r.json()["guardadas"][0]

    r = cli.delete("/brands/pensionmas/photos/%2E%2E")
    assert r.status_code in (422, 404)

    r = cli.get("/brands/pensionmas/files/fotos/%2E%2E")
    assert r.status_code in (422, 404)

    # foto de otra marca no accesible aunque el usuario tenga acceso a ambas
    r = cli.get(f"/brands/otramarca/files/fotos/{nombre}")
    assert r.status_code == 404
    r = cli.delete(f"/brands/otramarca/photos/{nombre}")
    assert r.status_code == 404


# ---------- topics ----------

def _topic(cx, account_id, **campos):
    base = dict(account_id=account_id, titulo="Tema x", resumen="r", url=f"http://x/{campos.get('titulo','t')}",
               fuente="rss", publicado_en=None, usado_en_queue_id=None, descartado=0)
    base.update(campos)
    return db.insert(cx, "topic_suggestions", **base)


def test_topics_listar_y_descartar(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    tid = _topic(cx, pid, titulo="Uno", url="http://x/1")
    _topic(cx, pid, titulo="Usado", url="http://x/2", usado_en_queue_id=99)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))

    r = cli.get("/brands/pensionmas/topics")
    assert r.status_code == 200
    titulos = {t["titulo"] for t in r.json()}
    assert titulos == {"Uno"}  # el usado no sale por default

    r = cli.get("/brands/pensionmas/topics?usados=1")
    assert {t["titulo"] for t in r.json()} == {"Uno", "Usado"}

    r = cli.post(f"/brands/pensionmas/topics/{tid}/descartar")
    assert r.status_code == 403
    H.logout()

    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.post(f"/brands/pensionmas/topics/{tid}/descartar")
    assert r.status_code == 200

    r = cli.get("/brands/pensionmas/topics")
    assert "Uno" not in {t["titulo"] for t in r.json()}


def test_topics_ownership(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    otra_id = _marca(cx, "otramarca")
    tid_otra = _topic(cx, otra_id, titulo="Ajeno", url="http://x/ajeno")
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    r = cli.post(f"/brands/pensionmas/topics/{tid_otra}/descartar")
    assert r.status_code == 404
