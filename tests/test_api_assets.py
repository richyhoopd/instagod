"""API de assets: buscar, listar, importar, subir, descartar, recortar; aislamiento."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src import assets, db
from src.assets import Candidata, biblioteca, buscar


def _png(w=6, h=4) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), "green").save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def entorno(api_cliente, tmp_path, monkeypatch):
    cli, cx, H = api_cliente
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    a1 = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    a2 = db.insert(cx, "accounts", slug="m2", ig_handle="@m2", nombre="M2", ciudad="GDL")
    uid = H.usuario("mg@x.com", marcas=[(a1, "manager")])
    H.login(uid)
    return cli, cx, a1, a2


def test_buscar_devuelve_resultados_y_avisos(entorno, monkeypatch) -> None:
    cli, cx, a1, _ = entorno
    vistos = {}

    def fake(cx_, aid, slug, q, *, tipo, proveedores, n):
        vistos.update(aid=aid, slug=slug, q=q, tipo=tipo, proveedores=proveedores, n=n)
        return [Candidata("pexels", "1", tipo, "https://images.pexels.com/1.jpg", "p", 1, 1,
                          "A", "Pexels License", None)], ["unsplash: falta UNSPLASH_ACCESS_KEY"]
    monkeypatch.setattr(buscar, "buscar_con_avisos", fake)
    r = cli.get("/brands/m1/assets/buscar", params={"q": "playa", "tipo": "video",
                                                     "proveedores": "pexels,unsplash", "n": 5})
    assert r.status_code == 200
    assert r.json()["resultados"][0]["url"] == "https://images.pexels.com/1.jpg"
    assert r.json()["avisos"] == ["unsplash: falta UNSPLASH_ACCESS_KEY"]
    assert vistos == {"aid": a1, "slug": "m1", "q": "playa", "tipo": "video",
                      "proveedores": ["pexels", "unsplash"], "n": 5}
    assert cli.get("/brands/m1/assets/buscar", params={"q": "x", "n": 999}).status_code == 422
    assert cli.get("/brands/m1/assets/buscar", params={"q": "x", "tipo": "audio"}).status_code == 422


def test_subir_listar_descartar(entorno) -> None:
    cli, cx, a1, _ = entorno
    r = cli.post("/brands/m1/assets/subir", files={"archivo": ("x.png", _png(), "image/png")})
    assert r.status_code == 201
    fila = r.json()
    assert fila["proveedor"] == "subida" and fila["src"] == f"assets/{fila['archivo']}"
    malo = cli.post("/brands/m1/assets/subir",
                    files={"archivo": ("x.png", b"<script>", "image/png")})
    assert malo.status_code == 422
    assert [f["id"] for f in cli.get("/brands/m1/assets").json()] == [fila["id"]]
    assert cli.patch(f"/brands/m1/assets/{fila['id']}", json={"descartada": True}).status_code == 200
    assert cli.get("/brands/m1/assets").json() == []


def test_importar_valida_proveedor_y_url(entorno, monkeypatch) -> None:
    cli, cx, a1, _ = entorno
    base = {"proveedor": "pexels", "id_origen": "1", "tipo": "imagen",
            "url": "https://images.pexels.com/1.jpg", "preview_url": "", "ancho": None,
            "alto": None, "autor": None, "licencia": None, "url_origen": None}
    assert cli.post("/brands/m1/assets/importar",
                    json={**base, "proveedor": "nope"}).status_code == 422
    assert cli.post("/brands/m1/assets/importar",
                    json={**base, "url": "local:fotos/a.png"}).status_code == 422
    assert cli.post("/brands/m1/assets/importar",
                    json={**base, "url": "file:///etc/passwd"}).status_code == 422

    def fake_importar(cx_, aid, slug, cand, *, tags=None):
        assert (aid, slug, cand.proveedor, tags) == (a1, "m1", "pexels", ["playa"])
        fila, _ = biblioteca.guardar_bytes(cx_, aid, slug, _png(), proveedor="pexels")
        return fila
    monkeypatch.setattr(biblioteca, "importar", fake_importar)
    r = cli.post("/brands/m1/assets/importar", json={**base, "tags": ["playa"]})
    assert r.status_code == 201 and r.json()["src"].startswith("assets/")

    def invalido(*a, **k):
        raise biblioteca.AssetInvalido("host no público: x")
    monkeypatch.setattr(biblioteca, "importar", invalido)
    r = cli.post("/brands/m1/assets/importar", json=base)
    assert r.status_code == 422 and "host no público" in r.text


def test_recorte_encola_job(entorno) -> None:
    cli, cx, a1, _ = entorno
    fila, _ = biblioteca.guardar_bytes(cx, a1, "m1", _png(), proveedor="subida")
    r = cli.post(f"/brands/m1/assets/{fila['id']}/recorte")
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert (job["tipo"], job["account_id"]) == ("asset.recorte", a1)


def test_api_assets_aislado_por_marca(entorno) -> None:
    cli, cx, a1, a2 = entorno
    ajeno, _ = biblioteca.guardar_bytes(cx, a2, "m2", _png(), proveedor="subida")
    # por la marca propia con id ajeno: 404
    assert cli.post(f"/brands/m1/assets/{ajeno['id']}/recorte").status_code == 404
    assert cli.patch(f"/brands/m1/assets/{ajeno['id']}",
                     json={"descartada": True}).status_code == 404
    assert cli.get("/brands/m1/assets").json() == []
    local = {"proveedor": "carpeta", "id_origen": "x", "tipo": "imagen",
             "url": f"local:assets/{ajeno['archivo']}", "preview_url": "", "ancho": None,
             "alto": None, "autor": None, "licencia": None, "url_origen": None}
    assert cli.post("/brands/m1/assets/importar", json=local).status_code == 422
    # por la marca ajena: sin rol
    assert cli.get("/brands/m2/assets").status_code in (403, 404)
    assert cli.post(f"/brands/m2/assets/{ajeno['id']}/recorte").status_code in (403, 404)
    assert db.rows(cx, "SELECT id FROM jobs WHERE tipo = 'asset.recorte'") == []


def test_editor_no_alcanza_manager(api_cliente, tmp_path, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    a1 = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    H.login(H.usuario("ed@x.com", marcas=[(a1, "editor")]))
    assert cli.get("/brands/m1/assets").status_code == 403
    assert cli.get("/brands/m1/assets/buscar", params={"q": "x"}).status_code == 403
    assert cli.post("/brands/m1/assets/1/recorte").status_code == 403


def test_importar_descarga_fallida_es_502(entorno, monkeypatch) -> None:
    cli, cx, a1, _ = entorno

    def cae(*a, **k):
        raise biblioteca.AssetInvalido("descarga falló: HTTP 500")
    monkeypatch.setattr(biblioteca, "importar", cae)
    base = {"proveedor": "pexels", "id_origen": "1", "tipo": "imagen",
            "url": "https://images.pexels.com/1.jpg"}
    r = cli.post("/brands/m1/assets/importar", json=base)
    assert r.status_code == 502 and "/" not in r.json()["detalle"].replace("HTTP 500", "")


def test_manager_de_a_no_toca_assets_de_b(entorno) -> None:
    cli, cx, a1, a2 = entorno
    ajeno, _ = biblioteca.guardar_bytes(cx, a2, "m2", _png(), proveedor="subida")
    for ruta in ("/brands/m2/assets", "/brands/m2/assets/buscar?q=x"):
        assert cli.get(ruta).status_code == 403
    assert cli.post("/brands/m2/assets/subir",
                    files={"archivo": ("x.png", _png(), "image/png")}).status_code == 403
    assert cli.patch(f"/brands/m2/assets/{ajeno['id']}",
                     json={"descartada": True}).status_code == 403
    assert db.get(cx, "brand_assets", ajeno["id"])["descartada"] == 0
