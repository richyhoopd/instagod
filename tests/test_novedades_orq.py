"""Tests del orquestador diario de novedades (src/novedades.py).

Todos los pasos van mockeados: aquí solo se prueba la orquestación
(orden, tolerancia a fallos, aviso y exit codes).
"""
from __future__ import annotations

import pytest

from src import db, novedades


@pytest.fixture()
def pasos(tmp_path, monkeypatch):
    """Mockea los 4 pasos + Telegram y registra el orden de llamadas."""
    llamadas: list = []
    db_path = tmp_path / "test.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    res_ingest = {
        "bandas_revisadas": 3, "con_novedades": 2, "fotos_nuevas": 4,
        "fallidas": [],
        "posts_nuevos": [
            {"band_id": 1, "ig_handle": "kabala", "shortcode": "A1",
             "caption": "nuevo sencillo", "path": "p/a1.jpg", "fecha": "2026-06-07"},
            {"band_id": 1, "ig_handle": "kabala", "shortcode": "A2",
             "caption": "show", "path": "p/a2.jpg", "fecha": "2026-06-07"},
            {"band_id": 2, "ig_handle": "lefnes", "shortcode": "B1",
             "caption": None, "path": "p/b1.jpg", "fecha": "2026-06-06"},
        ],
    }
    monkeypatch.setattr(novedades, "_proceso_activo", lambda: False)
    monkeypatch.setattr(novedades.ingest_ig, "novedades",
                        lambda **kw: llamadas.append("ingest") or res_ingest)
    monkeypatch.setattr(novedades.classify, "clasificar",
                        lambda handles=None, **kw: llamadas.append(("clasificar", handles)) or {})
    monkeypatch.setattr(novedades.detect_releases_ig, "detectar",
                        lambda cx, posts: llamadas.append(("detectar", len(posts))) or
                        {"revisados": 2, "releases_nuevos": 1, "saltados_dedupe": 0, "fallidos": 0})
    monkeypatch.setattr(novedades.parse_events, "parse_all",
                        lambda *a, **kw: llamadas.append("parse"))
    monkeypatch.setattr(novedades, "avisar_telegram",
                        lambda texto: llamadas.append(("telegram", texto)) or True)
    return llamadas, res_ingest


def test_orden_y_handles(pasos) -> None:
    llamadas, _ = pasos
    assert novedades.main([]) == 0
    nombres = [c if isinstance(c, str) else c[0] for c in llamadas]
    assert nombres == ["ingest", "clasificar", "detectar", "parse", "telegram"]
    # handles únicos de los posts nuevos, ordenados
    assert dict(c for c in llamadas if isinstance(c, tuple))["clasificar"] == ["kabala", "lefnes"]
    # detectar recibe TODOS los posts nuevos (el dedupe interno es suyo)
    assert ("detectar", 3) in llamadas


def test_sin_novedades_no_avisa(pasos, monkeypatch) -> None:
    llamadas, res = pasos
    res.update(con_novedades=0, fotos_nuevas=0, posts_nuevos=[], fallidas=[])
    assert novedades.main([]) == 0
    nombres = [c if isinstance(c, str) else c[0] for c in llamadas]
    assert "clasificar" not in nombres   # nada que clasificar
    assert "telegram" not in nombres     # sin spam diario


def test_paso_caido_no_tumba(pasos, monkeypatch) -> None:
    llamadas, _ = pasos

    def boom(handles=None, **kw):
        raise RuntimeError("OpenCV explotó")

    monkeypatch.setattr(novedades.classify, "clasificar", boom)
    assert novedades.main([]) == 0  # los demás pasos corrieron
    nombres = [c if isinstance(c, str) else c[0] for c in llamadas]
    assert "detectar" in nombres and "parse" in nombres
    texto = dict(c for c in llamadas if isinstance(c, tuple))["telegram"]
    assert "clasificar" in texto.lower() or "error" in texto.lower()


def test_ingesta_caida_exit_1(pasos, monkeypatch) -> None:
    def boom(**kw):
        raise RuntimeError("sesión de IG caída")

    monkeypatch.setattr(novedades.ingest_ig, "novedades", boom)
    assert novedades.main([]) == 1


def test_no_corre_con_pipeline_activo(pasos, monkeypatch) -> None:
    llamadas, _ = pasos
    monkeypatch.setattr(novedades, "_proceso_activo", lambda: True)
    assert novedades.main([]) == 0  # salida limpia, no es error
    assert llamadas == []


def test_resumen_nombra_proximos_y_salidos() -> None:
    from src import novedades
    res = {"bandas_revisadas": 5, "con_novedades": 2, "fotos_nuevas": 3,
           "fallidas": [], "pendientes": 0, "cortado_por_bloqueo": False}
    rel = {"releases_nuevos": 2, "saltados_dedupe": 0, "fallidos": 0,
           "nuevos": [{"banda": "Duck Fizz", "titulo": "A Ciegas", "fecha": "2099-06-19"},
                      {"banda": "X", "titulo": "Viejo", "fecha": "2000-01-01"}]}
    texto = novedades._resumen_texto(res, rel, [])
    assert "🔜 Duck Fizz — A Ciegas (sale 2099-06-19)" in texto
    assert "🎵 X — Viejo (salió 2000-01-01)" in texto
