"""brand_sources acepta kind 'video' y los providers nuevos; estado_fuentes los reporta."""
from __future__ import annotations

import pytest

import config
from api.routers import fuentes_api
from src import db, fuentes
from src.assets.proveedores import PROVEEDORES


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def test_crear_fuentes_video_y_nuevas(cx) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    for kind, prov in [("video", "pexels"), ("video", "coverr"), ("imagen", "openverse"),
                       ("imagen", "ia_imagen"), ("imagen", "giphy")]:
        fuentes.crear(cx, aid, kind, prov, {})
    with pytest.raises(ValueError):
        fuentes.crear(cx, aid, "video", "unsplash", {})
    assert {f["provider"] for f in fuentes.listar(cx, aid, kind="video")} == {"pexels", "coverr"}


def test_estado_fuentes_nuevos(monkeypatch) -> None:
    monkeypatch.setattr(config, "account_creds", lambda slug: {"PIXABAY_API_KEY": "k"})
    estado = fuentes_api.estado_fuentes("m1")
    assert estado["pixabay"]["ok"] is True
    assert estado["openverse"]["ok"] is True
    for prov in ("coverr", "giphy", "ia_imagen"):
        assert estado[prov] == {"ok": False, "motivo": "sin API key"}


def test_catalogo_coincide_con_registro_de_proveedores() -> None:
    """Los catálogos por kind no se desalinean del registro de proveedores de assets."""
    for kind, catalogo in (("imagen", fuentes.PROVIDERS_IMAGEN), ("video", fuentes.PROVIDERS_VIDEO)):
        esperado = {n for n, cls in PROVEEDORES.items() if kind in cls.tipos}
        assert esperado <= set(catalogo), (kind, esperado - set(catalogo))
    assert set(PROVEEDORES) <= set(fuentes_api.estado_fuentes("m1"))
