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


def test_pexels_fotos(llamadas) -> None:
    """Fixture pexels_fotos.json: forma del plan, sin verificar contra la API real (R8)."""
    llamadas.resp = _grabado("pexels_fotos.json")
    [c] = _prov("pexels", {"PEXELS_API_KEY": "PK"}).buscar("café", tipo="imagen", n=3)
    assert c.url.endswith("w=1880") and c.preview_url.endswith("h=350")
    assert (c.autor, c.ancho, c.alto, c.licencia) == ("Luis", 3000, 4000, "Pexels License")
    metodo, url, params, headers = llamadas.hechas[0]
    assert (metodo, url) == ("GET", "https://api.pexels.com/v1/search")
    assert headers == {"Authorization": "PK"}
    assert params == {"query": "café", "per_page": 3}


def test_pexels_video_elige_mp4_hasta_1920(llamadas) -> None:
    """Fixture pexels_videos.json: forma del plan, sin verificar contra la API real (R8)."""
    llamadas.resp = _grabado("pexels_videos.json")
    [c] = _prov("pexels", {"PEXELS_API_KEY": "PK"}).buscar("ciudad", tipo="video", n=3)
    assert c.tipo == "video" and c.url.endswith("/hd.mp4")
    assert (c.ancho, c.alto) == (1920, 1080)
    assert c.preview_url.endswith("thumb.jpeg")
    metodo, url, _, headers = llamadas.hechas[0]
    assert (metodo, url) == ("GET", "https://api.pexels.com/videos/search")
    assert headers == {"Authorization": "PK"}


def test_pexels_video_solo_archivos_grandes_toma_el_menor(llamadas) -> None:
    """Dato sintético armado en el test (no es respuesta real)."""
    arch = lambda w, h, n: {"file_type": "video/mp4", "width": w, "height": h,  # noqa: E731
                            "link": f"https://videos.pexels.com/{n}.mp4"}
    llamadas.resp = {"videos": [
        {"id": 1, "video_files": [arch(3840, 2160, "uhd"), arch(2560, 1440, "qhd")]},
        {"id": 2, "video_files": [{"file_type": "video/webm", "link": "x"}]},
    ]}
    [c] = _prov("pexels", {"PEXELS_API_KEY": "PK"}).buscar("x", tipo="video", n=3)
    assert c.url.endswith("/qhd.mp4")


def test_pexels_sin_llave(llamadas) -> None:
    with pytest.raises(base.SinLlave):
        _prov("pexels").buscar("x", tipo="imagen", n=5)
    assert llamadas.hechas == []


def test_pixabay_fotos_y_cache_sin_llave_en_hash(llamadas, tmp_path, monkeypatch) -> None:
    """Fixture pixabay_fotos.json: forma del plan, sin verificar contra la API real (R8)."""
    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    llamadas.resp = _grabado("pixabay_fotos.json")
    [c] = _prov("pixabay", {"PIXABAY_API_KEY": "K1"}).buscar("sol", tipo="imagen", n=5)
    assert c.url.endswith("303_1280.jpg") and c.preview_url.endswith("303_640.jpg")
    assert (c.autor, c.licencia) == ("pepe", "Pixabay Content License")
    metodo, url, params, _ = llamadas.hechas[0]
    assert (metodo, url) == ("GET", "https://pixabay.com/api/")
    assert params["key"] == "K1" and params["per_page"] >= 3
    assert params["image_type"] == "photo" and params["q"] == "sol"
    # misma consulta con otra key: sale de caché, no hay segunda llamada
    _prov("pixabay", {"PIXABAY_API_KEY": "K2"}).buscar("sol", tipo="imagen", n=5)
    assert len(llamadas.hechas) == 1
    cacheados = list((tmp_path / "cache" / "pixabay").glob("*.json"))
    assert len(cacheados) == 1 and "K1" not in cacheados[0].read_text()


def test_pixabay_cache_vencida_o_corrupta_vuelve_a_pedir(llamadas, tmp_path, monkeypatch) -> None:
    import os
    import time

    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    llamadas.resp = _grabado("pixabay_fotos.json")
    p = _prov("pixabay", {"PIXABAY_API_KEY": "K"})
    p.buscar("sol", tipo="imagen", n=5)
    [arch] = (tmp_path / "cache" / "pixabay").glob("*.json")
    viejo = time.time() - 25 * 3600
    os.utime(arch, (viejo, viejo))
    p.buscar("sol", tipo="imagen", n=5)
    assert len(llamadas.hechas) == 2  # venció a las 24 h
    arch.write_text("{no es json")
    [c] = p.buscar("sol", tipo="imagen", n=5)
    assert len(llamadas.hechas) == 3 and c.id_origen == "303"


def test_pixabay_video_usa_medium(llamadas, tmp_path, monkeypatch) -> None:
    """Fixture pixabay_videos.json: forma del plan, sin verificar contra la API real (R8)."""
    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    llamadas.resp = _grabado("pixabay_videos.json")
    [c] = _prov("pixabay", {"PIXABAY_API_KEY": "K"}).buscar("mar", tipo="video", n=5)
    assert c.url.endswith("404_medium.mp4") and (c.ancho, c.alto) == (1920, 1080)
    assert c.preview_url.endswith("404_medium.jpg") and c.tipo == "video"
    metodo, url, params, _ = llamadas.hechas[0]
    assert (metodo, url) == ("GET", "https://pixabay.com/api/videos/")
    assert params["key"] == "K"


def test_pixabay_item_malformado_se_salta(llamadas, tmp_path, monkeypatch) -> None:
    """Dato sintético armado en el test (no es respuesta real)."""
    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    bueno = _grabado("pixabay_fotos.json")["hits"][0]
    llamadas.resp = {"hits": [None, "x", {"largeImageURL": "https://pixabay.com/a.jpg"}, bueno]}
    res = _prov("pixabay", {"PIXABAY_API_KEY": "K"}).buscar("sol", tipo="imagen", n=5)
    assert [c.id_origen for c in res] == ["303"]
    llamadas.resp = {"hits": [{"videos": {}}, {"id": 1, "videos": None}, "x"]}
    assert _prov("pixabay", {"PIXABAY_API_KEY": "K"}).buscar("otra", tipo="video", n=5) == []


def test_pixabay_tipo_no_soportado_y_sin_llave(llamadas, tmp_path, monkeypatch) -> None:
    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    assert _prov("pixabay", {"PIXABAY_API_KEY": "K"}).buscar("x", tipo="audio", n=5) == []
    with pytest.raises(base.SinLlave):
        _prov("pixabay").buscar("x", tipo="imagen", n=5)
    assert llamadas.hechas == []


def test_pixabay_error_http_no_filtra_la_llave(tmp_path, monkeypatch) -> None:
    """La key va en la query; el error que sale pasa por el saneo de base (estado + host)."""
    import requests

    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")

    def get_roto(url, params=None, headers=None, timeout=None):
        raise requests.HTTPError(f"500 Server Error for url: {url}?key=SECRETO123&q=sol")
    monkeypatch.setattr(base.requests, "get", get_roto)
    with pytest.raises(base.ErrorHttp) as e:
        _prov("pixabay", {"PIXABAY_API_KEY": "SECRETO123"}).buscar("sol", tipo="imagen", n=5)
    assert "SECRETO123" not in str(e.value) and "pixabay.com" in str(e.value)
    assert not (tmp_path / "cache" / "pixabay").exists()


def test_openverse_filtra_nd_y_mature(llamadas) -> None:
    """Fixture openverse.json: forma del plan, sin verificar contra la API real (R8)."""
    llamadas.resp = _grabado("openverse.json")
    res = _prov("openverse").buscar("tacos", tipo="imagen", n=10)
    assert [c.id_origen for c in res] == ["uuid-1"]
    c = res[0]
    assert c.licencia == "CC BY 4.0" and c.autor == "Juan"
    assert c.url_origen == "https://www.flickr.com/photos/x/1"
    metodo, url, params, headers = llamadas.hechas[0]
    assert (metodo, url) == ("GET", "https://api.openverse.org/v1/images/")
    assert params["license_type"] == "commercial" and "Authorization" not in headers
    assert params["q"] == "tacos" and params["page_size"] == 10


def test_openverse_licencias_libres_item_malformado_y_tipo(llamadas) -> None:
    """Dato sintético armado en el test (no es respuesta real)."""
    def r(i, lic, ver="1.0"):
        return {"id": i, "url": f"https://x.org/{i}.jpg", "license": lic, "license_version": ver,
                "mature": False}
    llamadas.resp = {"results": [
        None, {"url": "https://x.org/sin-id.jpg", "license": "by"}, {"id": "s", "license": "by"},
        r("a", "cc0"), r("b", "pdm"), r("c", "by-sa", "3.0"), r("d", "by-nc-nd", "2.0"),
        {"id": "e", "url": "https://x.org/e.jpg", "license": None}]}
    p = _prov("openverse")
    res = {c.id_origen: c.licencia for c in p.buscar("x", tipo="imagen", n=50)}
    assert res == {"a": "CC0", "b": "Dominio público", "c": "CC BY-SA 3.0"}  # "e" sin licencia se descarta
    assert llamadas.hechas[0][2]["page_size"] == 20  # tope de page_size
    assert p.buscar("x", tipo="video", n=5) == []
    assert len(llamadas.hechas) == 1


def test_coverr_video_y_tracking(llamadas) -> None:
    """Fixture coverr.json: forma de la doc/plan, sin verificar contra la API real (R8)."""
    llamadas.resp = _grabado("coverr.json")
    p = _prov("coverr", {"COVERR_API_KEY": "CK"})
    assert p.buscar("noche", tipo="imagen", n=5) == []
    assert llamadas.hechas == []
    [c] = p.buscar("noche", tipo="video", n=5)
    assert c.url.endswith("1080p.mp4") and (c.ancho, c.alto) == (1920, 1080)
    assert c.licencia == "Coverr License" and c.preview_url.endswith("thumbnail.jpg")
    metodo, url, params, headers = llamadas.hechas[0]
    assert (metodo, url) == ("GET", "https://api.coverr.co/videos")
    assert params["urls"] == "true" and params["query"] == "noche"
    assert headers["Authorization"] == "Bearer CK"
    p.registrar_descarga(c)
    metodo, url, _, headers = llamadas.hechas[-1]
    assert (metodo, url) == ("PATCH", "https://api.coverr.co/videos/cvr1/stats/downloads")
    assert headers["Authorization"] == "Bearer CK"


def test_coverr_item_malformado_y_sin_llave(llamadas) -> None:
    """Dato sintético armado en el test (no es respuesta real)."""
    llamadas.resp = {"hits": [None, {"urls": {"mp4": "https://c.co/sin-id.mp4"}},
                              {"id": "x"}, {"id": "y", "urls": None},
                              {"id": "ok", "urls": {"mp4": "https://c.co/ok.mp4",
                                                    "mp4_preview": "https://c.co/p.mp4"}}]}
    [c] = _prov("coverr", {"COVERR_API_KEY": "CK"}).buscar("x", tipo="video", n=5)
    assert c.id_origen == "ok" and c.preview_url == "https://c.co/p.mp4"
    with pytest.raises(base.SinLlave):
        _prov("coverr").buscar("x", tipo="video", n=5)


def test_coverr_error_de_tracking_no_filtra_el_bearer(monkeypatch) -> None:
    """El Bearer va en header; un fallo de red sale solo con estado + host."""
    import requests

    from src.assets import Candidata

    def roto(metodo, url, headers=None, timeout=None):
        raise requests.HTTPError(f"500 {headers['Authorization']} {url}")
    monkeypatch.setattr(base.requests, "request", roto)
    c = Candidata("coverr", "cvr1", "video", "https://c.co/a.mp4", "", None, None, None, None, None)
    with pytest.raises(base.ErrorHttp) as e:
        _prov("coverr", {"COVERR_API_KEY": "SECRETO123"}).registrar_descarga(c)
    assert "SECRETO123" not in str(e.value) and "api.coverr.co" in str(e.value)


def test_giphy_gif_mp4_y_stickers(llamadas) -> None:
    """Fixture giphy.json: forma conocida de la API v1, sin verificar contra la real (R8)."""
    llamadas.resp = _grabado("giphy.json")
    [g] = _prov("giphy", {"GIPHY_API_KEY": "GK"}).buscar("wow", tipo="imagen", n=5)
    assert g.url.endswith("giphy.gif") and (g.ancho, g.alto) == (480, 270)
    assert g.preview_url.endswith("200w.gif") and g.licencia == "GIPHY"
    assert (g.tipo, g.autor) == ("imagen", "estudio")
    metodo, url, params, _ = llamadas.hechas[0]
    assert (metodo, url) == ("GET", "https://api.giphy.com/v1/gifs/search")
    assert params["api_key"] == "GK" and params["rating"] == "g" and params["q"] == "wow"
    [v] = _prov("giphy", {"GIPHY_API_KEY": "GK"}).buscar("wow", tipo="video", n=5)
    assert v.url.endswith("giphy.mp4") and v.tipo == "video"
    _prov("giphy", {"GIPHY_API_KEY": "GK"}, {"stickers": True}).buscar("wow", tipo="imagen", n=5)
    assert llamadas.hechas[-1][:2] == ("GET", "https://api.giphy.com/v1/stickers/search")


def test_giphy_item_malformado_tipo_y_sin_llave(llamadas) -> None:
    """Dato sintético armado en el test (no es respuesta real)."""
    llamadas.resp = {"data": [None, {"images": {"original": {"url": "https://g.com/sin-id.gif"}}},
                              {"id": "a"}, {"id": "b", "images": None},
                              {"id": "c", "images": {"original": {"url": "https://g.com/c.gif",
                                                                  "width": "x"}}}]}
    p = _prov("giphy", {"GIPHY_API_KEY": "GK"})
    [c] = p.buscar("x", tipo="imagen", n=5)
    assert c.id_origen == "c" and c.ancho is None and c.preview_url == "https://g.com/c.gif"
    assert p.buscar("x", tipo="video", n=5) == []  # ninguno trae mp4
    n_llamadas = len(llamadas.hechas)
    assert p.buscar("x", tipo="audio", n=5) == [] and len(llamadas.hechas) == n_llamadas
    with pytest.raises(base.SinLlave):
        _prov("giphy").buscar("x", tipo="imagen", n=5)


def test_giphy_error_http_no_filtra_la_llave(monkeypatch) -> None:
    """api_key va en la query; el error que sale pasa por el saneo de base (estado + host)."""
    import requests

    def get_roto(url, params=None, headers=None, timeout=None):
        raise requests.HTTPError(f"429 for url: {url}?api_key=SECRETO123&q=wow")
    monkeypatch.setattr(base.requests, "get", get_roto)
    with pytest.raises(base.ErrorHttp) as e:
        _prov("giphy", {"GIPHY_API_KEY": "SECRETO123"}).buscar("wow", tipo="imagen", n=5)
    assert "SECRETO123" not in str(e.value) and "api.giphy.com" in str(e.value)


def test_coverr_id_origen_se_escapa_en_el_path(llamadas) -> None:
    """Un id con '../' no debe escapar del path /videos/{id}/stats/downloads."""
    from src.assets import Candidata
    c = Candidata("coverr", "../x", "video", "https://c.co/a.mp4", "", None, None, None, None, None)
    _prov("coverr", {"COVERR_API_KEY": "CK"}).registrar_descarga(c)
    metodo, url, _, _ = llamadas.hechas[-1]
    assert metodo == "PATCH"
    assert "/../" not in url and url == "https://api.coverr.co/videos/..%2Fx/stats/downloads"


def test_openverse_licencia_no_str_descarta_solo_ese_item(llamadas) -> None:
    """Dato sintético armado en el test (no es respuesta real)."""
    llamadas.resp = {"results": [
        {"id": "mala", "url": "https://x.org/m.jpg", "license": 123, "mature": False},
        {"id": "ok", "url": "https://x.org/ok.jpg", "license": "by", "license_version": "4.0",
         "mature": False},
    ]}
    res = _prov("openverse").buscar("x", tipo="imagen", n=5)
    assert [c.id_origen for c in res] == ["ok"] and res[0].licencia == "CC BY 4.0"


def test_pixabay_error_al_escribir_cache_no_pierde_resultados(llamadas, tmp_path,
                                                              monkeypatch) -> None:
    """Fixture pixabay_fotos.json: forma del plan, sin verificar contra la API real (R8)."""
    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")

    def escribir_roto(self, *a, **k):
        raise OSError("disco lleno")
    monkeypatch.setattr(Path, "write_text", escribir_roto)
    llamadas.resp = _grabado("pixabay_fotos.json")
    [c] = _prov("pixabay", {"PIXABAY_API_KEY": "K"}).buscar("sol", tipo="imagen", n=5)
    assert c.id_origen == "303" and c.url.endswith("303_1280.jpg")
    assert not list((tmp_path / "cache" / "pixabay").glob("*.json"))
