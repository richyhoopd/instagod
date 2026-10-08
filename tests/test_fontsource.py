"""Fontsource: catálogo con caché, instalación validada a brand_fonts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import assets, db
from src.assets import biblioteca
from src.assets.proveedores import base
from src.plantillas import fontsource, fuentes_tipograficas

FIX = Path(__file__).parent / "fixtures" / "assets"
TTF = b"\x00\x01\x00\x00" + b"\x00" * 200


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def api(monkeypatch):
    llamadas = []

    def fake_get(url, *, params=None, headers=None):
        llamadas.append(url)
        if url.endswith("/v1/fonts"):
            return json.loads((FIX / "fontsource_lista.json").read_text())
        return json.loads((FIX / "fontsource_bebas.json").read_text())
    monkeypatch.setattr(base, "get_json", fake_get)
    return llamadas


def test_catalogo_filtra_y_cachea(cx, api) -> None:
    res = fontsource.catalogo("bebas")
    assert res == [{"id": "bebas-neue", "familia": "Bebas Neue", "categoria": "display",
                    "pesos": [400]}]
    assert len(fontsource.catalogo("")) == 2
    assert api == ["https://api.fontsource.org/v1/fonts"]   # segunda vez sale de caché


def test_catalogo_cache_corrupta_se_regenera(cx, api) -> None:
    ruta = assets.CACHE_DIR / "fontsource" / "catalogo.json"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{no es json")
    assert len(fontsource.catalogo("")) == 2


def test_instalar_baja_ttf_y_registra(cx, api, monkeypatch) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    pedidas = []

    def fake_descargar(url, *, hosts, tope):
        pedidas.append((url, hosts, tope))
        return TTF
    monkeypatch.setattr(biblioteca, "descargar", fake_descargar)
    fila = fontsource.instalar(cx, aid, "m1", "bebas-neue", 400)
    assert fila["familia"] == "Bebas Neue"
    ruta = Path(fila["archivo"])
    assert ruta.is_absolute() and ruta.name == "bebas-neue-400-normal.ttf"
    assert ruta.read_bytes() == TTF
    assert pedidas[0][1] == ("cdn.jsdelivr.net",) and pedidas[0][0].endswith(".ttf")
    cat = {f["familia"]: f for f in fuentes_tipograficas.catalogo(cx, aid)}
    assert cat["Bebas Neue"]["propia"] is True
    fontsource.instalar(cx, aid, "m1", "bebas-neue", 400)       # upsert, sin duplicar
    assert len(db.rows(cx, "SELECT id FROM brand_fonts WHERE account_id = ?", (aid,))) == 1


def test_instalar_rechaza(cx, api, monkeypatch) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    monkeypatch.setattr(biblioteca, "descargar", lambda url, **k: b"<html>")
    with pytest.raises(ValueError):
        fontsource.instalar(cx, aid, "m1", "bebas-neue", 400)      # no es TTF
    with pytest.raises(ValueError):
        fontsource.instalar(cx, aid, "m1", "../etc", 400)          # id inválido
    monkeypatch.setattr(biblioteca, "descargar", lambda url, **k: TTF)
    with pytest.raises(ValueError):
        fontsource.instalar(cx, aid, "m1", "bebas-neue", 700)      # peso inexistente
    with pytest.raises(biblioteca.AssetInvalido):
        fontsource.instalar(cx, aid, "otra", "bebas-neue", 400)    # slug ajeno a la cuenta
    assert db.rows(cx, "SELECT id FROM brand_fonts") == []


def test_instalar_rechaza_familia_peligrosa(cx, monkeypatch) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    info = json.loads((FIX / "fontsource_bebas.json").read_text())
    info["family"] = "x');}body{display:none"
    monkeypatch.setattr(base, "get_json", lambda url, **k: info)
    monkeypatch.setattr(biblioteca, "descargar", lambda url, **k: TTF)
    with pytest.raises(ValueError):
        fontsource.instalar(cx, aid, "m1", "bebas-neue", 400)


def test_api_tipografias(api_cliente, tmp_path, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(base, "get_json", lambda url, **k: json.loads(
        (FIX / ("fontsource_lista.json" if url.endswith("/fonts") else "fontsource_bebas.json"))
        .read_text()))
    monkeypatch.setattr(biblioteca, "descargar", lambda url, **k: TTF)
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    H.login(H.usuario("ed@x.com", marcas=[(aid, "editor")]))
    # R2: ambos endpoints exigen manager (el editor de plantillas ya es solo manager)
    assert cli.get("/brands/m1/tipografias/catalogo", params={"q": "inter"}).status_code == 403
    assert cli.post("/brands/m1/tipografias", json={"id": "bebas-neue"}).status_code == 403
    H.login(H.usuario("man@x.com", marcas=[(aid, "manager")]))
    assert cli.get("/brands/m1/tipografias/catalogo", params={"q": "inter"}).json()[0]["id"] == "inter"
    r = cli.post("/brands/m1/tipografias", json={"id": "bebas-neue", "peso": 400})
    assert r.status_code == 201 and r.json()["familia"] == "Bebas Neue"
    assert r.json()["propia"] is True and "/" not in r.json()["archivo"]
    assert cli.post("/brands/m1/tipografias", json={"id": "../etc"}).status_code == 422
    assert cli.post("/brands/m1/tipografias", json={"id": "bebas-neue", "peso": 700}).status_code == 422


def test_api_tipografias_errores_de_origen(api_cliente, tmp_path, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    H.login(H.usuario("man@x.com", marcas=[(aid, "manager")]))

    def caido(url, **k):
        raise base.ErrorHttp("HTTP 500 en api.fontsource.org")
    monkeypatch.setattr(base, "get_json", caido)
    assert cli.get("/brands/m1/tipografias/catalogo").status_code == 502
    assert cli.post("/brands/m1/tipografias", json={"id": "bebas-neue"}).status_code == 502
    monkeypatch.setattr(base, "get_json", lambda url, **k: json.loads(
        (FIX / "fontsource_bebas.json").read_text()))

    def cdn_caido(url, **k):
        raise biblioteca.AssetInvalido("descarga falló: HTTP 503 en cdn.jsdelivr.net")
    monkeypatch.setattr(biblioteca, "descargar", cdn_caido)
    r = cli.post("/brands/m1/tipografias", json={"id": "bebas-neue"})
    assert r.status_code == 502 and r.json()["detalle"].startswith("descarga falló")
