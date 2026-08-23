"""Miniaturas de estilos: cache por hash del preset, regeneración al editar."""
from __future__ import annotations

from PIL import Image

from src import db, estilo_preview, marcas_seed


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    marcas_seed.sembrar(cx)
    return cx


def _fake_render(monkeypatch, contador):
    def _render(template_file, ctx, **kw):
        contador.append(ctx)
        p = kw["out_path"]
        Image.new("RGB", (1080, 1350), "#223124").save(p)
        return p
    monkeypatch.setattr(estilo_preview.compose, "render_card", _render)


def test_png_de_renderiza_y_cachea(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(estilo_preview, "PREVIEWS_DIR", tmp_path / "previews")
    cx = _cx(tmp_path)
    llamadas = []
    _fake_render(monkeypatch, llamadas)
    p1 = estilo_preview.png_de(cx, "melaquecapital", "melaque_solido")
    p2 = estilo_preview.png_de(cx, "melaquecapital", "melaque_solido")
    assert p1 == p2 and p1.exists()
    assert len(llamadas) == 1                      # segunda vez sale del cache
    assert Image.open(p1).width <= 400             # miniatura, no el PNG de 1080


def test_png_de_cambia_al_editar_el_preset(tmp_path, monkeypatch) -> None:
    import json
    monkeypatch.setattr(estilo_preview, "PREVIEWS_DIR", tmp_path / "previews")
    cx = _cx(tmp_path)
    llamadas = []
    _fake_render(monkeypatch, llamadas)
    from src import marcas
    p1 = estilo_preview.png_de(cx, "melaquecapital", "melaquecapital")
    m = marcas.cargar(cx, "melaquecapital")
    editado = dict(m.estilos)
    editado["melaquecapital"] = dict(editado["melaquecapital"], background_opacity=0.9)
    db.update(cx, "accounts", m.id, estilos_json=json.dumps(editado))
    p2 = estilo_preview.png_de(cx, "melaquecapital", "melaquecapital")
    assert p1 != p2 and len(llamadas) == 2
    assert not p1.exists()                         # la miniatura vieja se limpia


def test_png_de_estilo_global_y_marca_sin_fotos(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(estilo_preview, "PREVIEWS_DIR", tmp_path / "previews")
    cx = _cx(tmp_path)
    llamadas = []
    _fake_render(monkeypatch, llamadas)
    p = estilo_preview.png_de(cx, "gdlscene", "tiktok_bold")
    assert p.exists()
    assert llamadas[0]["image_srcs"] in ([], None) or llamadas[0]["image_srcs"] == []


def test_png_de_estilo_desconocido_lanza(tmp_path, monkeypatch) -> None:
    import pytest
    monkeypatch.setattr(estilo_preview, "PREVIEWS_DIR", tmp_path / "previews")
    cx = _cx(tmp_path)
    with pytest.raises(KeyError):
        estilo_preview.png_de(cx, "gdlscene", "noexiste")
