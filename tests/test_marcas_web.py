"""GUI /marcas: listado con checklist de creds y upsert de perfil sin secretos."""
from __future__ import annotations

from fastapi.testclient import TestClient

from web import app as web_app


def test_get_marcas_lista_y_checklist(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    client = TestClient(web_app.app)
    r = client.get("/marcas")
    assert r.status_code == 200
    assert "gdlscene" in r.text


def test_post_guardar_upsert_y_json_invalido(monkeypatch) -> None:
    client = TestClient(web_app.app)
    r = client.post("/marcas/guardar", data={
        "slug": "prueba_web", "nombre": "Prueba", "ig_handle": "@prueba",
        "voz": "tono x", "fuentes_imagen": "pexels,pinterest",
        "formatos": "libre", "posting_slots": "09:00",
        "estilos_json": "", "color_marca": "#123456", "activa": "1",
    })
    assert r.status_code == 200
    r2 = client.get("/marcas")
    assert "prueba_web" in r2.text
    # JSON de estilos inválido → error legible, sin stacktrace
    r3 = client.post("/marcas/guardar", data={
        "slug": "prueba_web", "nombre": "Prueba", "ig_handle": "@prueba",
        "voz": "", "fuentes_imagen": "", "formatos": "",
        "posting_slots": "", "estilos_json": "{no json", "color_marca": "",
        "activa": "1",
    })
    assert r3.status_code == 200
    assert "estilos_json" in r3.text and "inválido" in r3.text.lower()


def test_slideshows_generar_pasa_marca(monkeypatch) -> None:
    lanzados = []
    monkeypatch.setattr(web_app, "_lanzar_sesion",
                        lambda mod, *args: lanzados.append((mod, args)) or None)
    client = TestClient(web_app.app)
    r = client.post("/slideshows/generar", data={
        "tema": "afore", "marca": "pensionmas", "formato": "libre",
        "estilo": "", "fuentes": "", "n_slides": "5",
    })
    assert r.status_code == 200
    _, args = lanzados[0]
    assert "--marca" in args and "pensionmas" in args
