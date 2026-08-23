"""GUI /slideshows: la página carga y el POST lanza el generador detached."""
from __future__ import annotations

from fastapi.testclient import TestClient

from web import app as web_app


def test_get_slideshows_carga() -> None:
    client = TestClient(web_app.app)
    r = client.get("/slideshows")
    assert r.status_code == 200
    assert "slideshow" in r.text.lower()


def test_post_generar_lanza_modulo(monkeypatch) -> None:
    lanzados = []

    def _fake_lanzar(modulo, *args):
        lanzados.append((modulo, args))
        return None

    monkeypatch.setattr(web_app, "_lanzar_sesion", _fake_lanzar)
    client = TestClient(web_app.app)
    r = client.post("/slideshows/generar", data={
        "tema": "cafeterías de GDL", "formato": "listicle",
        "estilo": "tiktok_bold", "fuentes": "pexels,banco", "n_slides": "5",
    })
    assert r.status_code == 200
    modulo, args = lanzados[0]
    assert modulo == "src.generate_slideshow"
    assert "--tema" in args and "cafeterías de GDL" in args
    assert "--n-slides" in args and "5" in args


def test_get_estilos_fragmento_lista_los_de_la_marca(tmp_path, monkeypatch) -> None:
    # DB temporal propia: otros tests reload(config) con DB_PATH temporal y
    # no siempre restauran el módulo — no dependemos del contenido de la real.
    import config
    from src import db, marcas_seed
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    cx = db.connect()
    db.init_db(cx)
    marcas_seed.sembrar(cx)
    cx.close()
    client = TestClient(web_app.app)
    r = client.get("/slideshows/estilos", params={"marca": "gdlscene"})
    assert r.status_code == 200
    assert "gdlscene_clasico" in r.text and "tiktok_bold" in r.text
    assert 'name="estilo"' in r.text
    assert "/slideshows/preview/gdlscene/tiktok_bold.png" in r.text


def test_get_preview_png(monkeypatch, tmp_path) -> None:
    from PIL import Image
    p = tmp_path / "x.png"
    Image.new("RGB", (10, 10)).save(p)
    from src import estilo_preview
    monkeypatch.setattr(estilo_preview, "png_de", lambda cx, m, e: p)
    client = TestClient(web_app.app)
    r = client.get("/slideshows/preview/gdlscene/tiktok_bold.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"


def test_get_preview_estilo_desconocido_404() -> None:
    client = TestClient(web_app.app)
    r = client.get("/slideshows/preview/gdlscene/noexiste.png")
    assert r.status_code == 404
