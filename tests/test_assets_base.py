"""Paquete src/assets: Candidata, registro de proveedores, carpeta y llaves nuevas."""
from __future__ import annotations

import pytest

import config
from src import assets, db, secrets_store
from src.assets import Candidata
from src.assets.proveedores import PROVEEDORES, base
from src.assets.proveedores.carpeta import Carpeta

NUEVAS = ("PIXABAY_API_KEY", "COVERR_API_KEY", "GIPHY_API_KEY", "FAL_KEY")


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def test_candidata_a_dict() -> None:
    c = Candidata(proveedor="pexels", id_origen="1", tipo="imagen", url="https://x/a.jpg",
                  preview_url="https://x/s.jpg", ancho=10, alto=20, autor="Ana",
                  licencia="Pexels License", url_origen="https://pexels.com/1")
    d = c.a_dict()
    assert d["ig_handle"] is None and d["source_post_id"] is None
    assert Candidata(**d) == c


def test_llaves_nuevas_registradas() -> None:
    for k in NUEVAS:
        assert k in config._ACCOUNT_CRED_KEYS
        assert k in secrets_store.CLAVES


def test_registro_tiene_carpeta_y_clave_falta() -> None:
    assert PROVEEDORES["carpeta"] is Carpeta
    p = base.Proveedor(creds={})
    assert p.clave() == ""          # llave None: no requiere
    p.llave = "PEXELS_API_KEY"
    with pytest.raises(base.SinLlave) as e:
        p.clave()
    assert e.value.args[0] == "PEXELS_API_KEY"


def test_carpeta_busca_en_biblioteca_y_fotos(cx, tmp_path) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="aa.jpg", sha="1",
              proveedor="pexels", tags_json='["playa","atardecer"]', ancho=10, alto=10)
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="bb.jpg", sha="2",
              proveedor="pexels", tags_json='["ciudad"]')
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="cc.jpg", sha="3",
              proveedor="pexels", tags_json='["playa"]', descartada=1)
    fotos = tmp_path / "brands" / "m1" / "fotos"
    fotos.mkdir(parents=True)
    (fotos / "playa-gdl.jpg").write_bytes(b"\xff\xd8\xff")
    (fotos / "nota.txt").write_text("x")

    p = Carpeta(cx=cx, account_id=aid, slug="m1", creds={}, config={})
    res = p.buscar("playa", tipo="imagen", n=10)
    assert [c.url for c in res] == ["local:assets/aa.jpg", "local:fotos/playa-gdl.jpg"]
    assert res[0].preview_url == "/brands/m1/files/assets/aa.jpg"
    assert res[1].preview_url == "/brands/m1/files/fotos/playa-gdl.jpg"
    assert p.buscar("playa", tipo="video", n=10) == []


def test_brands_dir_coincide_con_image_sources() -> None:
    from src import image_sources
    assert assets.BRANDS_DIR == image_sources.BRANDS_DIR
