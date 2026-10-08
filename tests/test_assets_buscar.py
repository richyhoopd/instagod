"""buscar.py: orden, fallback, de pago explícito y errores sin llaves."""
from __future__ import annotations

import pytest

import config
from src import assets, db
from src.assets import Candidata, buscar
from src.assets.proveedores import PROVEEDORES, base

SECRETO = "sk-SUPERSECRETA-123"


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx) -> int:
    return db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")


def _c(prov, i) -> Candidata:
    return Candidata(proveedor=prov, id_origen=str(i), tipo="imagen", url=f"https://h/{prov}/{i}",
                     preview_url="", ancho=None, alto=None, autor=None, licencia=None,
                     url_origen=None)


class _Falso(base.Proveedor):
    tipos = ("imagen", "video")
    llamadas: list = []

    def buscar(self, q, *, tipo="imagen", n=20):
        _Falso.llamadas.append(self.nombre)
        return [_c(self.nombre, i) for i in range(3)]


def _registrar(monkeypatch, nombre, cls=_Falso, **attrs):
    sub = type(f"P_{nombre}", (cls,), {"nombre": nombre, **attrs})
    monkeypatch.setitem(PROVEEDORES, nombre, sub)
    return sub


@pytest.fixture(autouse=True)
def _sin_creds(monkeypatch):
    monkeypatch.setattr(config, "account_creds", lambda slug: {"PEXELS_API_KEY": SECRETO})
    _Falso.llamadas = []


def test_intercala_dedup_y_corta(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "pa")
    _registrar(monkeypatch, "pb")
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pa", orden=0)
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pb", orden=1)
    db.insert(cx, "brand_sources", account_id=aid, kind="video", provider="pa", orden=0)
    res = buscar.buscar(cx, aid, "m1", "x", tipo="imagen", n=4)
    assert [c.url for c in res] == ["https://h/pa/0", "https://h/pb/0",
                                    "https://h/pa/1", "https://h/pb/1"]


def test_sin_fuentes_cae_a_carpeta_y_pexels(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "carpeta")
    _registrar(monkeypatch, "pexels")
    buscar.buscar(cx, aid, "m1", "x")
    assert _Falso.llamadas == ["carpeta", "pexels"]


def test_ia_imagen_solo_explicito_y_activo(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "pa")
    _registrar(monkeypatch, "ia_imagen", de_pago=True)
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pa")
    sid = db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="ia_imagen")
    # 1) por omisión NO corre aunque la fila esté activa
    buscar.buscar(cx, aid, "m1", "x")
    assert "ia_imagen" not in _Falso.llamadas
    # 2) pedido por nombre con fila activa: corre
    buscar.buscar(cx, aid, "m1", "x", proveedores=["ia_imagen"])
    assert _Falso.llamadas[-1] == "ia_imagen"
    # 3) pedido por nombre con la fila apagada: no corre y avisa
    db.update(cx, "brand_sources", sid, activa=0)
    _Falso.llamadas = []
    res, avisos = buscar.buscar_con_avisos(cx, aid, "m1", "x", proveedores=["ia_imagen"])
    assert _Falso.llamadas == [] and res == []
    assert avisos and avisos[0].startswith("ia_imagen:")


def test_error_de_proveedor_no_filtra_llave(cx, monkeypatch) -> None:
    aid = _cuenta(cx)

    class Roto(base.Proveedor):
        tipos = ("imagen",)

        def buscar(self, q, *, tipo="imagen", n=20):
            raise RuntimeError(f"401 for url: https://api.x/?key={SECRETO}&q=x "
                               f"Authorization: {SECRETO}")

    _registrar(monkeypatch, "roto", cls=Roto)
    _registrar(monkeypatch, "pa")
    sid = db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="roto")
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pa")
    res, avisos = buscar.buscar_con_avisos(cx, aid, "m1", "x")
    assert len(res) == 3                              # el roto no tumba la búsqueda
    fila = db.get(cx, "brand_sources", sid)
    assert fila["ultimo_run"] and fila["ultimo_error"]
    for texto in [fila["ultimo_error"], *avisos]:
        assert SECRETO not in texto
        assert "SUPERSECRETA" not in texto
        assert len(texto) <= 320


def test_sin_llave_se_reporta_por_nombre(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "conllave", cls=base.Proveedor, llave="GIPHY_API_KEY",
               buscar=lambda self, q, *, tipo="imagen", n=20: [self.clave()])
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="conllave")
    _, avisos = buscar.buscar_con_avisos(cx, aid, "m1", "x")
    assert avisos == ["conllave: falta GIPHY_API_KEY"]


def test_tipo_invalido(cx) -> None:
    with pytest.raises(ValueError):
        buscar.buscar(cx, _cuenta(cx), "m1", "x", tipo="audio")
