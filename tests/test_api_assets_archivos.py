"""El lienzo del editor pide las imágenes de la escena a este endpoint."""
from __future__ import annotations

import pytest

import api.routers.plantillas as plantillas_api


@pytest.fixture()
def brands(tmp_path, monkeypatch):
    raiz = tmp_path / "brands"
    (raiz / "gdlscene" / "assets").mkdir(parents=True)
    (raiz / "otra" / "assets").mkdir(parents=True)
    monkeypatch.setattr(plantillas_api, "BRANDS_DIR", raiz)
    return raiz


@pytest.fixture()
def manager(api_cliente):
    cli, cx, H = api_cliente
    H.login(H.usuario("manager@x.com", marcas=[(1, "manager")]))
    return cli


@pytest.fixture()
def cx_otra(api_cliente):
    from src import db
    cx = api_cliente[1]
    db.insert(cx, "accounts", slug="otra", ig_handle="otra", nombre="Otra", ciudad="CDMX")
    return cx


def test_sirve_un_asset(manager, brands):
    (brands / "gdlscene" / "assets" / "abc.png").write_bytes(b"\x89PNG")
    r = manager.get("/brands/gdlscene/files/assets/abc.png")
    assert r.status_code == 200
    assert r.content == b"\x89PNG"
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "private, max-age=86400"


def test_svg_va_en_sandbox(manager, brands):
    (brands / "gdlscene" / "assets" / "logo.svg").write_text("<svg/>")
    r = manager.get("/brands/gdlscene/files/assets/logo.svg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert r.headers["content-security-policy"] == (
        "default-src 'none'; style-src 'unsafe-inline'; sandbox")


@pytest.mark.parametrize("archivo", [
    "nada.png", "..%2Fsecreto.png", "%2e%2e%2Fsecreto.png", "..%5Csecreto.png",
    "..", "%2e%2e", ".oculto.png", "%2Fetc%2Fpasswd", "%2Fetc%2Fpasswd.png",
    "a%00.png", "abc.png%00.html", "abc.png%0A", "abc.png%20", "script.html",
    "datos.json", "sin_extension", "SCRIPT.HTML", "a" * 90 + ".png",
])
def test_404(manager, brands, archivo):
    (brands / "gdlscene" / "secreto.png").write_bytes(b"x")
    (brands / "gdlscene" / "assets" / "abc.png").write_bytes(b"x")
    (brands / "gdlscene" / "assets" / "script.html").write_text("<script>")
    (brands / "gdlscene" / "assets" / "SCRIPT.HTML").write_text("<script>")
    (brands / "gdlscene" / "assets" / "datos.json").write_text("{}")
    (brands / "gdlscene" / "assets" / "sin_extension").write_text("x")
    r = manager.get(f"/brands/gdlscene/files/assets/{archivo}")
    assert r.status_code in (404, 422)
    assert r.content != b"x"


def test_slug_con_traversal(manager, brands):
    (brands / "secreto").mkdir()
    (brands / "secreto" / "assets").mkdir()
    (brands / "secreto" / "assets" / "a.png").write_bytes(b"x")
    for slug in ("..", "%2e%2e", "gdlscene%2F..%2Fsecreto"):
        r = manager.get(f"/brands/{slug}/files/assets/a.png")
        assert r.status_code in (404, 422)


def test_symlink_que_sale_de_la_carpeta(manager, brands, tmp_path):
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"x")
    (brands / "gdlscene" / "assets" / "trampa.png").symlink_to(fuera)
    assert manager.get("/brands/gdlscene/files/assets/trampa.png").status_code == 404


def test_symlink_a_la_carpeta_de_otra_marca(manager, brands):
    (brands / "otra" / "assets" / "suyo.png").write_bytes(b"x")
    (brands / "gdlscene" / "assets" / "ajeno.png").symlink_to(
        brands / "otra" / "assets" / "suyo.png")
    assert manager.get("/brands/gdlscene/files/assets/ajeno.png").status_code == 404


def test_carpeta_assets_symlink_fuera(manager, brands, tmp_path):
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    (fuera / "a.png").write_bytes(b"x")
    (brands / "gdlscene" / "assets").rmdir()
    (brands / "gdlscene" / "assets").symlink_to(fuera, target_is_directory=True)
    # La carpeta misma es un symlink: se resuelve a `fuera` y el archivo cae
    # dentro de lo resuelto. Es decisión de quien monta el disco, no del cliente;
    # lo que no debe pasar es salir de ahí.
    r = manager.get("/brands/gdlscene/files/assets/a.png")
    assert r.status_code in (200, 404)


def test_directorio_no_es_archivo(manager, brands):
    (brands / "gdlscene" / "assets" / "carpeta.png").mkdir()
    assert manager.get("/brands/gdlscene/files/assets/carpeta.png").status_code == 404


def test_otra_marca_no(manager, brands, cx_otra):
    (brands / "otra" / "assets" / "suyo.png").write_bytes(b"x")
    assert manager.get("/brands/otra/files/assets/suyo.png").status_code == 403


def test_sin_sesion(api_cliente, brands):
    cli = api_cliente[0]
    (brands / "gdlscene" / "assets" / "abc.png").write_bytes(b"x")
    assert cli.get("/brands/gdlscene/files/assets/abc.png").status_code in (401, 403)


def test_editor_no_pasa(api_cliente, brands):
    cli, cx, H = api_cliente
    H.login(H.usuario("editor@x.com", marcas=[(1, "editor")]))
    (brands / "gdlscene" / "assets" / "abc.png").write_bytes(b"x")
    assert cli.get("/brands/gdlscene/files/assets/abc.png").status_code == 403
