"""Tests de la lógica pura del carrusel de colab."""
import pytest

from src import generate_colab as gc


def _brief(**over):
    b = {
        "slug": "x", "evento": "Fest X", "fecha_texto": "1 de agosto",
        "sede": "Foro", "cta_handle": "@org", "cartel": "x.jpg",
        "caption_intro": "Intro.", "cta_texto": "Boletos.",
        "slides": [{"texto": f"hecho {i}"} for i in range(3)],
        "tags": ["@a", "@b"],
    }
    b.update(over)
    return b


def test_caption_incluye_intro_info_y_tags():
    cap = gc.caption_colab(_brief())
    assert "Intro." in cap
    assert "Fest X · 1 de agosto · Foro" in cap
    assert "🎟️ @org" in cap
    assert "@a @b" in cap


def test_caption_tags_unicos_sin_importar_caso_ni_orden():
    cap = gc.caption_colab(_brief(tags=["@Banda", "@banda", "@Otra", "  ", "@Otra"]))
    # @banda aparece una sola vez; vacío se omite
    assert cap.count("@Banda") == 1
    assert "@Otra @" not in cap  # no duplica @Otra
    assert cap.rstrip().endswith("@Otra") or "@Banda @Otra" in cap


def test_caption_agrega_sede_extra():
    cap = gc.caption_colab(_brief(sede_extra="Centro Cultural"))
    assert "(Centro Cultural)" in cap


def test_slides_interiores_topan_en_8():
    b = _brief(slides=[{"texto": f"h{i}"} for i in range(20)])
    assert len(gc.slides_interiores(b)) == gc.MAX_INTERIOR == 8


def test_slides_interiores_respeta_menos_de_8():
    assert len(gc.slides_interiores(_brief())) == 3


def test_cargar_brief_valida_campos(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(gc, "COLABS_DIR", tmp_path)
    (tmp_path / "malo.json").write_text(json.dumps({"evento": "X"}), encoding="utf-8")
    with pytest.raises(ValueError):
        gc.cargar_brief("malo")
