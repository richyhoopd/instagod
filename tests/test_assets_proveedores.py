"""Proveedores de assets contra respuestas grabadas (sin red).

Fixtures: las de tests/fixtures/assets/ salen de la forma documentada de cada API / del plan,
no de respuestas reales (sin verificar, ruling R8) salvo que el archivo diga lo contrario.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.assets.proveedores import PROVEEDORES, base

FIX = Path(__file__).parent / "fixtures" / "assets"


def _grabado(nombre: str):
    return json.loads((FIX / nombre).read_text())


@pytest.fixture()
def llamadas(monkeypatch):
    """Sustituye get_json/post_json/enviar; cada test pone la respuesta en `llamadas.resp`."""
    class R:
        resp: object = None
        hechas: list = []
    R.hechas = []

    def fake_get(url, *, params=None, headers=None):
        R.hechas.append(("GET", url, params or {}, headers or {}))
        return R.resp(url) if callable(R.resp) else R.resp

    def fake_post(url, *, json_body, headers=None):
        R.hechas.append(("POST", url, json_body, headers or {}))
        return R.resp(url) if callable(R.resp) else R.resp

    def fake_enviar(metodo, url, *, headers=None):
        R.hechas.append((metodo, url, {}, headers or {}))

    monkeypatch.setattr(base, "get_json", fake_get)
    monkeypatch.setattr(base, "post_json", fake_post)
    monkeypatch.setattr(base, "enviar", fake_enviar)
    return R


def _prov(nombre, creds=None, config=None):
    return PROVEEDORES[nombre](cx=None, account_id=1, slug="m1", creds=creds or {},
                               config=config or {})


def test_unsplash_mapea_y_registra_descarga(llamadas) -> None:
    llamadas.resp = _grabado("unsplash_search.json")  # sin verificar: forma del plan/doc
    p = _prov("unsplash", {"UNSPLASH_ACCESS_KEY": "UK"})
    res = p.buscar("playa", tipo="imagen", n=5)
    assert len(res) == 1
    c = res[0]
    assert (c.proveedor, c.id_origen, c.tipo) == ("unsplash", "abc123", "imagen")
    assert c.url == "https://images.unsplash.com/photo-1?w=1080"
    assert c.preview_url.endswith("w=400")
    assert (c.autor, c.licencia) == ("Ana Pérez", "Unsplash License")
    assert c.url_origen == "https://unsplash.com/photos/abc123"
    metodo, url, params, headers = llamadas.hechas[0]
    assert url == "https://api.unsplash.com/search/photos" and params["query"] == "playa"
    assert headers["Authorization"] == "Client-ID UK"
    assert p.buscar("playa", tipo="video", n=5) == []
    p.registrar_descarga(c)
    assert llamadas.hechas[-1][1] == "https://api.unsplash.com/photos/abc123/download"


def test_unsplash_sin_llave(llamadas) -> None:
    with pytest.raises(base.SinLlave):
        _prov("unsplash").buscar("x", tipo="imagen", n=5)
