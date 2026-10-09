"""Proveedor local «Seguidos de IG»: busca en brand_assets, nunca en la red."""
from __future__ import annotations

import json

import pytest

import config
from src import assets, db
from src.assets import biblioteca, buscar
from src.assets.proveedores import PROVEEDORES
from src.assets.proveedores.ig_seguidos import IgSeguidosProvider

_IDS: dict[str, int] = {}


@pytest.fixture
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "data" / "brands")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)  # siembra gdlscene como cuenta 1
    _IDS.clear()
    _IDS.update({  # F1: ids reales de las cuentas creadas, nunca hard-codeados
        "pensionmas": db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P",
                                ciudad="CDMX"),
        "daisies": db.insert(c, "accounts", slug="daisies", ig_handle="@d", nombre="D",
                             ciudad="CDMX"),
    })
    yield c
    c.close()


def _pm(cx) -> int:
    return _IDS["pensionmas"]


def _da(cx) -> int:
    return _IDS["daisies"]


def _asset(cx, account_id, handle, caption, *, tipo="imagen", sha, extra=None) -> int:
    archivo = f"ig_{sha[:20]}.{'mp4' if tipo == 'video' else 'png'}"
    return db.insert(cx, "brand_assets", account_id=account_id, tipo=tipo, archivo=archivo,
                     sha=sha, proveedor="ig_seguidos", autor=f"@{handle}",
                     licencia="Instagram (terceros)", url_origen="https://www.instagram.com/p/X/",
                     ig_handle=handle, source_post_id="1", ancho=40, alto=50,
                     tags_json=json.dumps({"fuente": "ig_seguidos", "caption": caption, **(extra or {})}))


def test_registrado() -> None:
    assert PROVEEDORES["ig_seguidos"] is IgSeguidosProvider


def test_busca_por_handle_y_caption(cx) -> None:
    _asset(cx, _pm(cx), "cafe.tacuba", "Noche de vinilos", sha="a" * 64)
    _asset(cx, _pm(cx), "mercado.roma", "Playa y mezcal", sha="b" * 64)
    p = IgSeguidosProvider(cx=cx, account_id=_pm(cx), slug="pensionmas")
    assert [c.ig_handle for c in p.buscar("@cafe")] == ["cafe.tacuba"]
    assert [c.ig_handle for c in p.buscar("PLAYA")] == ["mercado.roma"]
    assert len(p.buscar("")) == 2
    c = p.buscar("vinilos")[0]
    assert c.proveedor == "ig_seguidos" and c.tipo == "imagen"
    assert c.url == f"local:assets/ig_{'a' * 20}.png"
    assert c.preview_url == f"/brands/pensionmas/files/assets/ig_{'a' * 20}.png"
    assert c.autor == "@cafe.tacuba" and c.licencia == "Instagram (terceros)"


def test_comodines_like_no_se_cuelan(cx) -> None:
    _asset(cx, _pm(cx), "cafe.tacuba", "100% vinilo", sha="a" * 64)
    _asset(cx, _pm(cx), "otra", "nada", sha="b" * 64)
    p = IgSeguidosProvider(cx=cx, account_id=_pm(cx), slug="pensionmas")
    assert [c.ig_handle for c in p.buscar("%")] == ["cafe.tacuba"]
    assert p.buscar("e_t") == []                            # "_" literal, no comodín ("cafe.tacuba" tiene "e.t")


def test_video_usa_poster_como_preview(cx) -> None:
    _asset(cx, _pm(cx), "cafe.tacuba", "reel", tipo="video", sha="c" * 64,
           extra={"poster": f"ig_{'d' * 20}.png"})
    p = IgSeguidosProvider(cx=cx, account_id=_pm(cx), slug="pensionmas")
    v = p.buscar("", tipo="video")[0]
    assert v.url.endswith(".mp4")
    assert v.preview_url == f"/brands/pensionmas/files/assets/ig_{'d' * 20}.png"


def test_excluye_cuentas_descartadas_y_assets_descartados(cx) -> None:
    _asset(cx, _pm(cx), "cafe.tacuba", "uno", sha="a" * 64)
    aid = _asset(cx, _pm(cx), "mercado.roma", "dos", sha="b" * 64)
    db.insert(cx, "brand_ig_cuentas", account_id=_pm(cx), ig_handle="cafe.tacuba", estado="descartada")
    db.update(cx, "brand_assets", aid, descartada=1)
    assert IgSeguidosProvider(cx=cx, account_id=_pm(cx), slug="pensionmas").buscar("") == []


def test_proveedor_aisla_marcas(cx) -> None:
    """Review Focus 4."""
    _asset(cx, _pm(cx), "cafe.tacuba", "uno", sha="a" * 64)
    assert IgSeguidosProvider(cx=cx, account_id=_da(cx), slug="daisies").buscar("") == []
    assert buscar.buscar(cx, _da(cx), "daisies", "uno", proveedores=["ig_seguidos"]) == []


def test_buscar_unificado_incluye_ig_si_hay_assets(cx) -> None:
    _asset(cx, _pm(cx), "cafe.tacuba", "vinilos", sha="a" * 64)
    res = buscar.buscar(cx, _pm(cx), "pensionmas", "vinilos", proveedores=["ig_seguidos"])
    assert [c.proveedor for c in res] == ["ig_seguidos"]
    assert "ig_seguidos" in buscar._proveedores_extra(cx, _pm(cx))
    assert buscar._proveedores_extra(cx, _da(cx)) == []


def test_importar_devuelve_la_fila_sin_descargar(cx, monkeypatch) -> None:
    aid = _asset(cx, _pm(cx), "cafe.tacuba", "vinilos", sha="a" * 64)
    cand = IgSeguidosProvider(cx=cx, account_id=_pm(cx), slug="pensionmas").buscar("")[0]
    monkeypatch.setattr(biblioteca, "descargar", lambda *a, **k: pytest.fail("no debe bajar"))
    fila = biblioteca.importar(cx, _pm(cx), "pensionmas", cand)
    assert fila["id"] == aid


def test_importar_rechaza_asset_de_otra_marca(cx) -> None:
    """Review Focus 4: un id_origen de la marca 1 no se importa en la 2."""
    _asset(cx, _pm(cx), "cafe.tacuba", "vinilos", sha="a" * 64)
    cand = IgSeguidosProvider(cx=cx, account_id=_pm(cx), slug="pensionmas").buscar("")[0]
    with pytest.raises(biblioteca.AssetInvalido):
        biblioteca.importar(cx, _da(cx), "daisies", cand)


def test_busqueda_solo_en_caption_no_en_otras_claves(cx) -> None:
    """F3: 'poster' y 'caption' son claves de tags_json, no texto buscable."""
    _asset(cx, _pm(cx), "cafe.tacuba", "vinilos", sha="a" * 64, extra={"permalink": "zzz-unico"})
    _asset(cx, _pm(cx), "otra", "nada", sha="b" * 64, tipo="video",
           extra={"poster": f"ig_{'d' * 20}.png"})
    p = IgSeguidosProvider(cx=cx, account_id=_pm(cx), slug="pensionmas")
    assert p.buscar("caption") == [] and p.buscar("fuente") == [] and p.buscar("zzz-unico") == []
    assert p.buscar("poster", tipo="video") == []
    assert len(p.buscar("vinilos")) == 1


def test_no_filtra_assets_de_otra_cuenta_con_mismo_texto(cx) -> None:
    _asset(cx, _pm(cx), "cafe.tacuba", "vinilos", sha="a" * 64)
    _asset(cx, _da(cx), "otra", "vinilos", sha="b" * 64)
    res = IgSeguidosProvider(cx=cx, account_id=_da(cx), slug="daisies").buscar("vinilos")
    assert [c.ig_handle for c in res] == ["otra"]
    res = buscar.buscar(cx, _da(cx), "daisies", "vinilos")
    assert [c.ig_handle for c in res] == ["otra"]


def test_buscar_sin_proveedores_muestra_ig_seguidos(cx) -> None:
    """F2: con proveedores=None carpeta no debe tragarse los resultados por dedup de url."""
    _asset(cx, _pm(cx), "cafe.tacuba", "vinilos", sha="a" * 64)
    res = buscar.buscar(cx, _pm(cx), "pensionmas", "vinilos", proveedores=None)
    assert [(c.proveedor, c.ig_handle) for c in res] == [("ig_seguidos", "cafe.tacuba")]
    assert not any(c.proveedor == "carpeta" and c.url.endswith(".png") for c in res)
