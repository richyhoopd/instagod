"""biblioteca: rutas, magic bytes, descarga cerrada (https, IP pública, redirects), dedup."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src import assets, db
from src.assets import Candidata, biblioteca
from src.assets.biblioteca import AssetInvalido


def _png(w=4, h=3) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), "red").save(b, "PNG")
    return b.getvalue()


@pytest.fixture(autouse=True)
def _brands_tmp(tmp_path, monkeypatch):
    """Ninguna prueba toca el data/brands real."""
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx, slug="m1") -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}", nombre=slug, ciudad="GDL")


class _Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.is_redirect = status in (301, 302, 303, 307, 308)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]


@pytest.fixture()
def red(monkeypatch):
    """DNS y HTTP falsos: `red.dns[host] = [ip]`, `red.resp[url] = _Resp`."""
    class R:
        dns: dict = {}
        resp: dict = {}
        pedidas: list = []
    R.dns, R.resp, R.pedidas = {}, {}, []
    monkeypatch.setattr(biblioteca, "_ips_de", lambda host: R.dns.get(host, []))

    def fake_get(url, **kw):
        assert kw.get("allow_redirects") is False and kw.get("stream") is True
        R.pedidas.append(url)
        return R.resp[url]
    monkeypatch.setattr(biblioteca.requests, "get", fake_get)
    return R


def test_ruta_de_valida() -> None:
    assert biblioteca.ruta_de("m1", "ab12.jpg").parts[-3:] == ("m1", "assets", "ab12.jpg")
    for slug, archivo in [("../x", "a.jpg"), ("m1", "../a.jpg"), ("m1", "a/b.jpg"),
                          ("m1", ".oculto"), ("M1", "a.jpg"), ("m1", "")]:
        with pytest.raises(ValueError):
            biblioteca.ruta_de(slug, archivo)


def test_tipo_de_bytes() -> None:
    assert biblioteca.tipo_de_bytes(_png()[:16]) == ("imagen", "png")
    assert biblioteca.tipo_de_bytes(b"\xff\xd8\xff\xe0" + b"0" * 12) == ("imagen", "jpg")
    assert biblioteca.tipo_de_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("imagen", "webp")
    assert biblioteca.tipo_de_bytes(b"GIF89a" + b"0" * 10) == ("imagen", "gif")
    assert biblioteca.tipo_de_bytes(b"\x00\x00\x00\x18ftypisom0000") == ("video", "mp4")
    assert biblioteca.tipo_de_bytes(b"\x1a\x45\xdf\xa3" + b"0" * 12) == ("video", "webm")
    assert biblioteca.tipo_de_bytes(b"\x00\x00\x00\x18ftypheic0000") is None
    assert biblioteca.tipo_de_bytes(b"<svg xmlns=") is None


def test_descarga_solo_https(red) -> None:
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("http://a.com/x.png", hosts=None, tope=100)
    assert red.pedidas == []


def test_descarga_rechaza_ip_privada_y_host_fuera_de_lista(red) -> None:
    red.dns["interno.com"] = ["10.0.0.5"]
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://interno.com/x.png", hosts=None, tope=100)
    red.dns["evil.com"] = ["93.184.216.34"]
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://evil.com/x.png", hosts=("pexels.com",), tope=100)
    red.dns["images.pexels.com"] = ["93.184.216.34"]
    red.resp["https://images.pexels.com/x.png"] = _Resp(body=b"ok")
    assert biblioteca.descargar("https://images.pexels.com/x.png", hosts=("pexels.com",),
                                tope=100) == b"ok"
    assert red.pedidas == ["https://images.pexels.com/x.png"]


def test_descarga_redirect_a_metadata_se_bloquea(red) -> None:
    red.dns["cdn.com"] = ["93.184.216.34"]
    red.dns["169.254.169.254"] = ["169.254.169.254"]
    red.resp["https://cdn.com/a"] = _Resp(302, headers={"Location": "https://169.254.169.254/x"})
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://cdn.com/a", hosts=None, tope=100)
    assert red.pedidas == ["https://cdn.com/a"]


def test_descarga_tope_y_demasiados_redirects(red) -> None:
    red.dns["cdn.com"] = ["93.184.216.34"]
    red.resp["https://cdn.com/grande"] = _Resp(body=b"x" * 200_000)
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://cdn.com/grande", hosts=None, tope=100_000)
    red.resp["https://cdn.com/r"] = _Resp(302, headers={"Location": "/r"})
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://cdn.com/r", hosts=None, tope=100)


def test_guardar_bytes_dedup_y_dims(cx) -> None:
    aid = _cuenta(cx)
    fila, nueva = biblioteca.guardar_bytes(cx, aid, "m1", _png(8, 5), proveedor="subida")
    assert nueva and (fila["ancho"], fila["alto"], fila["tipo"]) == (8, 5, "imagen")
    assert fila["archivo"].endswith(".png")
    assert biblioteca.ruta_de("m1", fila["archivo"]).read_bytes() == _png(8, 5)
    otra, nueva2 = biblioteca.guardar_bytes(cx, aid, "m1", _png(8, 5), proveedor="subida")
    assert not nueva2 and otra["id"] == fila["id"]
    with pytest.raises(AssetInvalido):
        biblioteca.guardar_bytes(cx, aid, "m1", b"<html>", proveedor="subida")
    with pytest.raises(AssetInvalido):   # magic de PNG pero cuerpo corrupto
        biblioteca.guardar_bytes(cx, aid, "m1", _png()[:20] + b"basura", proveedor="subida")
    carpeta = assets.BRANDS_DIR / "m1" / "assets"
    assert [p.name for p in carpeta.iterdir()] == [fila["archivo"]]   # ni .part ni huérfanos


def test_importar_remoto_registra_descarga_solo_si_es_nueva(cx, red, monkeypatch) -> None:
    from src.assets.proveedores import PROVEEDORES
    aid = _cuenta(cx)
    registradas = []
    monkeypatch.setattr(PROVEEDORES["unsplash"], "registrar_descarga",
                        lambda self, cand: registradas.append(cand.id_origen))
    red.dns["images.unsplash.com"] = ["93.184.216.34"]
    red.resp["https://images.unsplash.com/p1"] = _Resp(body=_png())
    cand = Candidata(proveedor="unsplash", id_origen="p1", tipo="imagen",
                     url="https://images.unsplash.com/p1", preview_url="", ancho=None,
                     alto=None, autor="Ana", licencia="Unsplash License",
                     url_origen="https://unsplash.com/p1")
    fila = biblioteca.importar(cx, aid, "m1", cand, tags=["playa"])
    assert (fila["proveedor"], fila["autor"], fila["tags_json"]) == ("unsplash", "Ana", '["playa"]')
    biblioteca.importar(cx, aid, "m1", cand)
    assert registradas == ["p1"]


def test_importar_tipo_no_coincide(cx, red) -> None:
    aid = _cuenta(cx)
    red.dns["media.giphy.com"] = ["93.184.216.34"]
    red.resp["https://media.giphy.com/a.mp4"] = _Resp(body=_png())
    cand = Candidata(proveedor="giphy", id_origen="g", tipo="video",
                     url="https://media.giphy.com/a.mp4", preview_url="", ancho=None,
                     alto=None, autor=None, licencia="GIPHY", url_origen=None)
    with pytest.raises(AssetInvalido):
        biblioteca.importar(cx, aid, "m1", cand)


def test_importar_local_fotos_y_assets(cx) -> None:
    aid = _cuenta(cx)
    otra = _cuenta(cx, "m2")
    fotos = assets.BRANDS_DIR / "m1" / "fotos"
    fotos.mkdir(parents=True)
    (fotos / "a.png").write_bytes(_png())
    cand = Candidata(proveedor="carpeta", id_origen="a.png", tipo="imagen",
                     url="local:fotos/a.png", preview_url="", ancho=None, alto=None,
                     autor=None, licencia="propia", url_origen=None)
    fila = biblioteca.importar(cx, aid, "m1", cand)
    assert fila["proveedor"] == "carpeta"
    ya = Candidata(**{**cand.a_dict(), "url": f"local:assets/{fila['archivo']}"})
    assert biblioteca.importar(cx, aid, "m1", ya)["id"] == fila["id"]
    with pytest.raises(AssetInvalido):          # el archivo es de m1, no de m2
        biblioteca.importar(cx, otra, "m2", ya)
    for mala in ("local:fotos/../../x.png", "local:otra/a.png", "local:fotos/A B.png"):
        with pytest.raises(AssetInvalido):
            biblioteca.importar(cx, aid, "m1", Candidata(**{**cand.a_dict(), "url": mala}))


def test_guardar_bytes_insert_fallido_no_deja_huerfano(cx, monkeypatch) -> None:
    aid = _cuenta(cx)

    def boom(*a, **k):
        raise RuntimeError("db caída")
    monkeypatch.setattr(biblioteca.db, "insert", boom)
    with pytest.raises(RuntimeError):
        biblioteca.guardar_bytes(cx, aid, "m1", _png(6, 6), proveedor="subida")
    carpeta = assets.BRANDS_DIR / "m1" / "assets"
    assert list(carpeta.iterdir()) == []


def test_guardar_bytes_insert_fallido_conserva_archivo_preexistente(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    fila, _ = biblioteca.guardar_bytes(cx, aid, "m1", _png(7, 7), proveedor="subida")
    destino = biblioteca.ruta_de("m1", fila["archivo"])
    cx.execute("DELETE FROM brand_assets WHERE id = ?", (fila["id"],))
    cx.commit()
    monkeypatch.setattr(biblioteca.db, "insert", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    with pytest.raises(RuntimeError):
        biblioteca.guardar_bytes(cx, aid, "m1", _png(7, 7), proveedor="subida")
    assert destino.exists()   # el archivo ya existía: no es de esta llamada


def test_guardar_bytes_slug_invalido_no_toca_disco(cx, tmp_path) -> None:
    aid = _cuenta(cx)
    for slug in ("../x", "/abs", "M1", "a/b", ""):
        with pytest.raises(AssetInvalido):
            biblioteca.guardar_bytes(cx, aid, slug, _png(), proveedor="subida")
    assert not (tmp_path / "x").exists() and not (tmp_path / "brands").exists()


def test_ruta_de_rechaza_absolutas_y_symlink_fuera(tmp_path) -> None:
    for archivo in ("/etc/passwd", "..", "a\\b.jpg", "a\x00.jpg"):
        with pytest.raises(ValueError):
            biblioteca.ruta_de("m1", archivo)
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    marca = assets.BRANDS_DIR / "m1"
    marca.mkdir(parents=True)
    (marca / "assets").symlink_to(fuera, target_is_directory=True)
    with pytest.raises(ValueError):
        biblioteca.ruta_de("m1", "ab12.jpg")


def test_guardar_bytes_symlink_de_assets_no_escapa(cx, tmp_path) -> None:
    aid = _cuenta(cx)
    fuera = tmp_path / "fuera"
    fuera.mkdir()
    marca = assets.BRANDS_DIR / "m1"
    marca.mkdir(parents=True)
    (marca / "assets").symlink_to(fuera, target_is_directory=True)
    with pytest.raises(AssetInvalido):
        biblioteca.guardar_bytes(cx, aid, "m1", _png(), proveedor="subida")
    assert list(fuera.iterdir()) == []


def test_importar_foto_symlink_se_rechaza(cx, tmp_path) -> None:
    aid = _cuenta(cx)
    secreto = tmp_path / "secreto.png"
    secreto.write_bytes(_png())
    fotos = assets.BRANDS_DIR / "m1" / "fotos"
    fotos.mkdir(parents=True)
    (fotos / "s.png").symlink_to(secreto)
    cand = Candidata(proveedor="carpeta", id_origen="s.png", tipo="imagen",
                     url="local:fotos/s.png", preview_url="", ancho=None, alto=None,
                     autor=None, licencia="propia", url_origen=None)
    with pytest.raises(AssetInvalido):
        biblioteca.importar(cx, aid, "m1", cand)
