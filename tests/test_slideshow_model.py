"""Contrato de datos del motor de slideshows: validación y round-trip JSON."""
from __future__ import annotations

from src import slideshow_model as sm


def _slide_ok(**kw):
    base = dict(image_urls=["/tmp/foto.jpg"], image_layout="single",
                text_items=[sm.TextItem(text="Hola mundo")],
                is_cta=False, background_opacity=0.35, duration=3.0, source="manual")
    base.update(kw)
    return sm.Slide(**base)


def _show_ok(**kw):
    base = dict(title="Demo", aspect_ratio="4:5", slides=[_slide_ok()],
                caption="pie de foto", language="es", brief={}, formato="listicle",
                account_slug="gdlscene")
    base.update(kw)
    return sm.Slideshow(**base)


def test_show_valido_no_da_errores() -> None:
    assert sm.validar(_show_ok()) == []


def test_sin_slides_es_error() -> None:
    assert any("slides" in e for e in sm.validar(_show_ok(slides=[])))


def test_mas_de_20_slides_es_error() -> None:
    assert any("slides" in e for e in sm.validar(_show_ok(slides=[_slide_ok()] * 21)))


def test_aspect_invalido_es_error() -> None:
    assert sm.validar(_show_ok(aspect_ratio="3:2"))


def test_layout_invalido_es_error() -> None:
    assert sm.validar(_show_ok(slides=[_slide_ok(image_layout="5:5")]))


def test_mas_imagenes_que_celdas_del_layout_es_error() -> None:
    s = _slide_ok(image_layout="1:2", image_urls=["a.jpg", "b.jpg", "c.jpg"])
    assert sm.validar(_show_ok(slides=[s]))


def test_slide_sin_texto_es_error() -> None:
    assert sm.validar(_show_ok(slides=[_slide_ok(text_items=[])]))


def test_font_desconocida_es_error() -> None:
    item = sm.TextItem(text="x", font="ComicSans")
    assert sm.validar(_show_ok(slides=[_slide_ok(text_items=[item])]))


def test_color_fuera_de_paleta_es_error() -> None:
    item = sm.TextItem(text="x", text_color="fucsia")
    assert sm.validar(_show_ok(slides=[_slide_ok(text_items=[item])]))


def test_opacity_fuera_de_rango_es_error() -> None:
    assert sm.validar(_show_ok(slides=[_slide_ok(background_opacity=1.5)]))


def test_slide_sin_imagen_es_valido() -> None:
    """Fallback de fondo sólido: image_urls=[] NO es error."""
    assert sm.validar(_show_ok(slides=[_slide_ok(image_urls=[])])) == []


def test_round_trip_json() -> None:
    s = _show_ok()
    otra = sm.desde_json(sm.a_json(s))
    assert otra == s
    assert isinstance(otra.slides[0].text_items[0], sm.TextItem)


def test_source_carpeta_es_valido() -> None:
    """El banco propio por marca (image_sources.CarpetaProvider) es un source legal."""
    assert "carpeta" in sm.SOURCES
