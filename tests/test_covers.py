"""Caché de portadas: ruta estable, hit sin red, descarga con fallback."""
from __future__ import annotations

import requests

from src import covers


def test_ruta_cache_estable(tmp_path) -> None:
    a = covers._ruta_cache("https://i.scdn.co/image/abc", base=tmp_path)
    b = covers._ruta_cache("https://i.scdn.co/image/abc", base=tmp_path)
    c = covers._ruta_cache("https://i.scdn.co/image/OTRA", base=tmp_path)
    assert a == b and a != c and a.suffix == ".jpg" and a.parent == tmp_path


def test_cache_hit_no_descarga(tmp_path, monkeypatch) -> None:
    url = "https://i.scdn.co/image/abc"
    p = covers._ruta_cache(url, base=tmp_path)
    p.write_bytes(b"JPEGFAKE")

    def boom(*a, **k):
        raise AssertionError("no debió tocar la red")
    monkeypatch.setattr(covers, "_descargar", boom)
    assert covers.asegurar_cover(url, base=tmp_path) == p


def test_descarga_normal_y_escribe(tmp_path, monkeypatch) -> None:
    url = "https://i.scdn.co/image/abc"
    monkeypatch.setattr(covers, "_descargar", lambda u: b"\xff\xd8BYTESIMG")
    p = covers.asegurar_cover(url, base=tmp_path)
    assert p is not None and p.read_bytes() == b"\xff\xd8BYTESIMG"


def test_fallback_doh_si_dns_falla(tmp_path, monkeypatch) -> None:
    url = "https://i.scdn.co/image/abc"

    def dns_roto(u):
        raise requests.ConnectionError("NameResolutionError")
    monkeypatch.setattr(covers, "_descargar", dns_roto)
    monkeypatch.setattr(covers, "_descargar_via_doh", lambda u: b"\xff\xd8VIADOH")
    p = covers.asegurar_cover(url, base=tmp_path)
    assert p is not None and p.read_bytes() == b"\xff\xd8VIADOH"


def test_falla_total_regresa_none(tmp_path, monkeypatch) -> None:
    def roto(u):
        raise requests.ConnectionError("x")
    monkeypatch.setattr(covers, "_descargar", roto)
    monkeypatch.setattr(covers, "_descargar_via_doh", roto)
    assert covers.asegurar_cover("https://x/y", base=tmp_path) is None


def test_no_cachea_html(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(covers, "_descargar", lambda u: b"<html>error</html>")
    url = "https://i.scdn.co/image/abc"
    assert covers.asegurar_cover(url, base=tmp_path) is None
    assert not covers._ruta_cache(url, base=tmp_path).exists()


def test_falla_no_deja_archivo(tmp_path, monkeypatch) -> None:
    def roto(u):
        raise requests.ConnectionError("x")
    monkeypatch.setattr(covers, "_descargar", roto)
    monkeypatch.setattr(covers, "_descargar_via_doh", roto)
    url = "https://i.scdn.co/image/abc"
    assert covers.asegurar_cover(url, base=tmp_path) is None
    assert not covers._ruta_cache(url, base=tmp_path).exists()


# ---------- rutas locales (releases detectados de IG: cover_url = foto del post) ----------

def test_ruta_local_absoluta_se_usa_directo(tmp_path, monkeypatch) -> None:
    foto = tmp_path / "post.jpg"
    foto.write_bytes(b"\xff\xd8FOTOIG")

    def boom(*a, **k):
        raise AssertionError("ruta local no debe tocar la red")
    monkeypatch.setattr(covers, "_descargar", boom)
    assert covers.asegurar_cover(str(foto), base=tmp_path) == foto


def test_ruta_local_relativa_resuelve_contra_base_dir(tmp_path, monkeypatch) -> None:
    import config
    (tmp_path / "data" / "photos" / "banda").mkdir(parents=True)
    foto = tmp_path / "data" / "photos" / "banda" / "abc_0.jpg"
    foto.write_bytes(b"\xff\xd8FOTOIG")
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    p = covers.asegurar_cover("data/photos/banda/abc_0.jpg", base=tmp_path)
    assert p == foto


def test_ruta_local_inexistente_regresa_none(tmp_path, monkeypatch) -> None:
    import config
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    assert covers.asegurar_cover("data/photos/banda/no_existe.jpg", base=tmp_path) is None
