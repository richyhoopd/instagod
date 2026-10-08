from types import SimpleNamespace

import pytest

from src.plantillas import kinds
from src.plantillas.kinds import _esquema


def _marca(**kw):
    base = dict(id=1, slug="prueba", nombre="Prueba", ig_handle="prueba",
                color_marca="#7A4CFF", voz="", fuentes=["Erode-Bold"], formatos=["4x5"],
                estilos={}, logo_path=None, activa=True, prompts={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_esquema_minimo():
    e = {"type": "object", "properties": {"a": {"type": "string", "maxLength": 3},
                                           "b": {"type": "array", "minItems": 1,
                                                 "items": {"type": "integer", "minimum": 0}}},
         "required": ["a"], "additionalProperties": False}
    assert _esquema.errores({"a": "hey", "b": [1]}, e) == []
    errs = _esquema.errores({"a": "hola", "b": [-1], "c": 1}, e)
    assert any("$.a" in x for x in errs)
    assert any("$.b[0]" in x for x in errs)
    assert any("c" in x for x in errs)
    assert _esquema.errores({"b": [True]}, e)   # bool no es integer y falta a


def test_esquema_de_kind_mezcla_comunes():
    e = kinds.esquema("side")
    assert "titulo" in e["properties"] and "tema" in e["properties"]
    assert "titulo" in e["required"]
    llm = kinds.esquema_para_llm("side")
    assert "x-slots" not in llm
    assert "default" not in str(llm)


def test_validar_spec_rellena_defaults_y_rechaza():
    spec = kinds.validar_spec("side", {"titulo": ["Hola"]})
    assert spec["tema"] == "claro"
    assert spec["grano"] is False
    with pytest.raises(kinds.SpecInvalido, match="titulo"):
        kinds.validar_spec("side", {"titulo": []})
    with pytest.raises(kinds.SpecInvalido, match="kind"):
        kinds.validar_spec("nada", {})


def test_slots_expande_por_items():
    spec = kinds.validar_spec("compare", {
        "titulo": ["Precios"], "oferta": {"nombre": "Todo", "precio": "$399"},
        "items": [{"nombre": "A", "precio": "$1"}, {"nombre": "B", "precio": "$2"}]})
    ids = [s["id"] for s in kinds.slots("compare", spec)]
    assert ids[:2] == ["item_0", "item_1"]


def test_tokens_de_marca_y_override():
    t = kinds.tokens_de(_marca(), "claro")
    assert t["acento"] == "#7A4CFF"
    assert t["sobre_acento"] == "#FFFFFF"
    assert t["destacado"] == "#F5C842"
    t2 = kinds.tokens_de(_marca(estilos={"tokens": {"destacado": "#00FF00"}}), "oscuro")
    assert t2["destacado"] == "#00FF00"
    assert t2["fondo"] == "#1C1A23"
    assert "marca" not in t2


def test_fuentes_de_cae_a_poppins():
    f = kinds.fuentes_de(_marca(fuentes=["NoExiste"]), {"Poppins-Bold", "Poppins-SemiBold"}, "side")
    assert f == {"titulo": "Poppins-Bold", "texto": "Poppins-SemiBold"}
    f2 = kinds.fuentes_de(_marca(), {"Erode-Bold", "Poppins-Bold", "Poppins-SemiBold"}, "side")
    assert f2["titulo"] == "Erode-Bold"


def test_render_strict_y_escapa():
    spec = kinds.validar_spec("side", {"titulo": ["<b>Hola</b>"], "acento": "Hola"})
    asset = {"src": "file:///tmp/a.png", "archivo": "assets/a.png",
             "fuente_asset": {"proveedor": "pexels", "autor": "O'Neil", "licencia": None,
                              "url": None, "ig_handle": None}}
    html = kinds.render("side", spec, tokens=kinds.tokens_de(_marca()),
                        fuentes={"titulo": "Poppins-Bold", "texto": "Poppins-SemiBold"},
                        assets={"imagen": asset}, handle="@prueba")
    assert "&lt;b&gt;" in html
    assert 'data-tipo="text" data-id="titulo"' in html
    assert "O\\u0027Neil" in html or "O&#39;Neil" in html
    assert 'class="card' in html


def test_render_sticker_sin_color_usa_destacado():
    # Bajo StrictUndefined, un sticker sin "color" no debe romper el render.
    spec = kinds.validar_spec("side", {
        "titulo": ["Hola"],
        "stickers": [{"texto": "Nuevo"}, {"texto": "Oferta", "color": "profundo"}]})
    assert "color" not in spec["stickers"][0]
    tokens = kinds.tokens_de(_marca())
    html = kinds.render("side", spec, tokens=tokens,
                        fuentes={"titulo": "Poppins-Bold", "texto": "Poppins-SemiBold"},
                        assets={}, handle="@prueba")
    assert 'data-id="sticker_0"' in html and 'data-id="sticker_1"' in html
    assert f"background:{tokens['destacado']}" in html
    assert f"background:{tokens['profundo']}" in html
