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
