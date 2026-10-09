import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageChops

from src import db
from src.plantillas import contrato as contrato_mod
from src.plantillas import escena as escena_mod
from src.plantillas import extraer, fuentes_tipograficas, kinds
from src.plantillas import render as plantillas_render

TOK = {"fondo": "#FFFFFF", "tinta": "#1C1A23", "acento": "#7A4CFF",
       "panel": "rgba(255,255,255,0.14)"}


def _cs(**kw):
    base = {"fontFamily": "\"Poppins-Bold\", sans-serif", "fontSize": "72px", "fontWeight": "700",
            "lineHeight": "73.44px", "letterSpacing": "-1.44px", "color": "rgb(28, 26, 35)",
            "textAlign": "left", "textTransform": "none", "whiteSpace": "pre-line",
            "textWrapMode": "wrap", "textWrapStyle": "auto", "backgroundColor": "rgba(0, 0, 0, 0)",
            "backgroundSize": "cover", "backgroundPosition": "50% 50%",
            "borderTopLeftRadius": "0px", "borderTopWidth": "0px", "borderTopStyle": "none",
            "borderTopColor": "rgb(0, 0, 0)", "filter": "none", "mixBlendMode": "normal",
            "paddingTop": "0px", "paddingRight": "0px", "paddingBottom": "0px", "paddingLeft": "0px"}
    base.update(kw)
    return base


def _capa(**kw):
    base = {"tipo": "text", "id": "titulo", "nombre": "Título", "campo": None, "anclaje": None,
            "valign": "top", "x": 79.6, "y": 230.2, "w": 400.0, "h": 147.3, "rot": 0,
            "opacity": 1, "src": None, "srcUrl": None, "recorte": False, "fuenteAsset": None,
            "texto": "Tu ciclo\ntambién habla", "spans": [{"desde": 16, "hasta": 21, "color": "rgb(122, 76, 255)"}],
            "svg": None, "cs": _cs()}
    base.update(kw)
    return base


def test_colores_y_tokens():
    assert extraer.css_a_color("rgb(122, 76, 255)") == "#7a4cff"
    assert extraer.css_a_color("rgba(0, 0, 0, 0)") is None
    assert extraer.css_a_color("rgba(255, 255, 255, 0.14)") == "rgba(255,255,255,0.14)"
    assert extraer.tokenizar("#7a4cff", TOK) == "token:acento"
    assert extraer.tokenizar("rgba(255,255,255,0.14)", TOK) == "token:panel"
    assert extraer.tokenizar("#123456", TOK) == "#123456"


def test_texto_fijo_con_spans():
    datos = {"fondo": {"color": "rgb(255, 255, 255)", "aplanar": False}, "capas": [_capa()]}
    esc, muestras = extraer.a_escena(datos, slug="prueba", tokens=TOK, fuente="Poppins-SemiBold",
                                     fondo_png=None)
    c = esc["capas"][0]
    assert (c["x"], c["y"], c["w"], c["h"]) == (80, 230, 400, 148)
    assert c["texto"] == "Tu ciclo\ntambién habla"
    assert c["estilo"]["fontFamily"] == "Poppins-Bold"
    assert c["estilo"]["lineHeight"] == 1.02
    assert c["estilo"]["letterSpacing"] == "-0.020em"
    assert c["estilo"]["color"] == "token:tinta"
    assert c["estilo"]["spans"] == [{"desde": 16, "hasta": 21, "color": "token:acento"}]
    assert "campo" not in c
    assert esc["lienzo"] == {"w": 1080, "h": 1350, "formato": "4x5",
                             "fondo": {"tipo": "color", "valor": "token:fondo"}}
    assert muestras == {}


def test_campo_quita_spans_y_da_muestra():
    capa = _capa(id="bajada", campo="bajada", texto="hola", spans=[{"desde": 0, "hasta": 1, "color": "rgb(0, 0, 0)"}])
    esc, muestras = extraer.a_escena({"fondo": {"color": "rgb(255, 255, 255)", "aplanar": False},
                                      "capas": [capa]}, slug="prueba", tokens=TOK,
                                     fuente="Poppins-SemiBold", fondo_png=None)
    c = esc["capas"][0]
    assert c["campo"] == "bajada"
    assert "spans" not in c["estilo"]
    assert muestras == {"bajada": "hola"}


def test_caja_se_parte_en_fondo_y_texto():
    capa = _capa(tipo="caja", id="cta", texto="Agenda", spans=[], rot=-6, x=80, y=1110, w=400, h=84,
                 cs=_cs(backgroundColor="rgb(122, 76, 255)", borderTopLeftRadius="999px",
                        paddingTop="16px", paddingRight="16px", paddingBottom="16px",
                        paddingLeft="16px", color="rgb(255, 255, 255)", textAlign="center",
                        fontSize="30px", lineHeight="34.5px", letterSpacing="normal"))
    esc, _ = extraer.a_escena({"fondo": {"color": "rgb(255, 255, 255)", "aplanar": False},
                               "capas": [capa]}, slug="prueba", tokens=TOK,
                              fuente="Poppins-SemiBold", fondo_png=None)
    fondo, texto = esc["capas"]
    assert fondo["id"] == "cta_fondo" and fondo["tipo"] == "shape"
    assert fondo["estilo"]["fill"] == "token:acento"
    assert fondo["estilo"]["radius"] == 42      # recortado a h/2
    assert texto["id"] == "cta" and texto["tipo"] == "text"
    assert (texto["x"], texto["y"], texto["w"], texto["h"]) == (96, 1126, 368, 52)
    assert texto["z"] == fondo["z"] + 5
    assert fondo["rot"] == texto["rot"] == -6
    assert texto["estilo"]["verticalAlign"] == "center"
    assert "letterSpacing" not in texto["estilo"]


def test_imagen_con_mascara_y_fuente():
    capa = _capa(tipo="image", id="imagen", campo="imagen", texto=None, spans=None,
                 src="assets/a.png", srcUrl="file:///x/a.png",
                 fuenteAsset={"proveedor": "pexels", "autor": "Ana", "otra": "x"},
                 cs=_cs(borderTopLeftRadius="50%"), w=150, h=150)
    esc, muestras = extraer.a_escena({"fondo": {"color": "rgb(255, 255, 255)", "aplanar": False},
                                      "capas": [capa]}, slug="prueba", tokens=TOK,
                                     fuente="Poppins-SemiBold", fondo_png=None)
    c = esc["capas"][0]
    assert c["mascara"] == "circle"
    assert c["src"] == "assets/a.png"
    assert c["estilo"]["objectPosition"] == "center"
    assert c["recorte"] is False
    assert c["fuente_asset"] == {"proveedor": "pexels", "autor": "Ana", "licencia": None,
                                 "url": None, "ig_handle": None}
    assert muestras == {"imagen": "file:///x/a.png"}


def test_svg_y_fondo_aplanado_van_a_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(extraer.biblioteca, "ruta_de", lambda slug, archivo: tmp_path / archivo)
    capa = _capa(tipo="svg", id="flor", texto=None, spans=None,
                 svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle r="1"/></svg>')
    esc, _ = extraer.a_escena({"fondo": {"color": "rgb(255, 255, 255)", "aplanar": True},
                               "capas": [capa]}, slug="prueba", tokens=TOK,
                              fuente="Poppins-SemiBold", fondo_png=b"\x89PNG")
    c = esc["capas"][0]
    assert c["src"].startswith("assets/") and c["src"].endswith(".svg")
    assert (tmp_path / c["src"].removeprefix("assets/")).read_text().startswith("<svg")
    fondo = esc["lienzo"]["fondo"]
    assert fondo["tipo"] == "imagen"
    assert (tmp_path / fondo["valor"].removeprefix("assets/")).read_bytes() == b"\x89PNG"


def test_anclaje_por_tercios():
    assert extraer.anclaje_por_tercio(100, 50) == "top"
    assert extraer.anclaje_por_tercio(600, 100) == "center"
    assert extraer.anclaje_por_tercio(1200, 100) == "bottom"


@pytest.mark.parametrize("css,esperado", [
    ("50% 50%", "center"), ("0% 0%", "left top"), ("100% 100%", "right bottom"),
    ("50% 0%", "center top"), ("0% 50%", "left"), ("100% 50%", "right"),
    ("37% 12%", "center"), (None, "center"), ("", "center")])
def test_posicion_porcentaje_a_palabra(css, esperado):
    p = extraer._posicion(css)
    assert p == esperado and p in escena_mod.POSICIONES



FIX_KINDS = Path(__file__).parent / "fixtures" / "kinds"


def _foto(ruta: Path, color):
    img = Image.new("RGB", (800, 800), color)
    for y in range(0, 800, 40):
        for x in range(0, 800, 40):
            if (x + y) // 40 % 2:
                img.paste((255 - color[0], 200, 90), (x, y, x + 40, y + 40))
    img.save(ruta)


@pytest.mark.lento
@pytest.mark.parametrize("kind", sorted(p.stem for p in FIX_KINDS.glob("*.json")))
def test_round_trip_pixel(kind, tmp_path, monkeypatch):
    brands = tmp_path / "brands"
    monkeypatch.setattr(plantillas_render, "BRANDS_DIR", brands, raising=False)
    monkeypatch.setattr(extraer.biblioteca, "BRANDS_DIR", brands, raising=False)
    monkeypatch.setattr(extraer.biblioteca, "ruta_de",
                        lambda slug, archivo: brands / slug / "assets" / archivo)
    assets_dir = brands / "prueba" / "assets"
    assets_dir.mkdir(parents=True)
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    marca = SimpleNamespace(id=1, slug="prueba", nombre="Prueba", ig_handle="prueba",
                            color_marca="#7A4CFF", voz="", fuentes=[], formatos=["4x5"],
                            estilos={}, logo_path=None, activa=True, prompts={})
    catalogo = fuentes_tipograficas.catalogo(cx, 1)
    familias = {f["familia"] for f in catalogo}

    spec = kinds.validar_spec(kind, json.loads((FIX_KINDS / f"{kind}.json").read_text())["spec"])
    assets = {}
    for i, s in enumerate(kinds.slots(kind, spec)):
        archivo = f"{s['id']}.png"
        _foto(assets_dir / archivo, (40 + 30 * i, 120, 200))
        assets[s["id"]] = {"src": (assets_dir / archivo).as_uri(), "archivo": f"assets/{archivo}",
                           "fuente_asset": {"proveedor": "prueba", "autor": None,
                                            "licencia": None, "url": None, "ig_handle": None}}
    tokens = kinds.tokens_de(marca, spec["tema"])
    fuentes = kinds.fuentes_de(marca, familias, kind)
    html = kinds.render(kind, spec, tokens=tokens, fuentes=fuentes, assets=assets,
                        font_faces=kinds.css_fuentes(set(fuentes.values()), catalogo),
                        handle="@prueba")
    png, escena, muestras = extraer.extraer(html, slug="prueba", tokens=tokens,
                                            fuente=fuentes["texto"])

    contrato = {"aspecto": "4:5", "base": list(contrato_mod.CAMPOS_BASE),
                "extras": [{"id": "bajada", "tipo": "texto"}] if "bajada" in muestras else []}
    escena_mod.validar(escena, contrato, familias=familias)
    html_v2 = escena_mod.a_html(escena, contrato, fuentes=catalogo)
    plantilla = {"html": html_v2, "contrato_json": json.dumps(contrato), "aspecto": "4:5",
                 "layout_json": json.dumps(escena), "account_id": 1, "id": 0}
    campos = {"titular": "x", "imagen": "", "logo": "", "color_marca": "#7A4CFF", **muestras}
    salida = plantillas_render.render(cx, marca, plantilla, campos,
                                      out_path=tmp_path / f"{kind}_v2.png")

    a = Image.open(__import__("io").BytesIO(png)).convert("RGB")
    b = Image.open(salida).convert("RGB")
    assert a.size == b.size
    diff = ImageChops.difference(a, b)
    distintos = sum(1 for px in diff.getdata() if max(px) > 32)
    ratio = distintos / (a.size[0] * a.size[1])
    if ratio > 0.01:
        ImageChops.difference(a, b).save(tmp_path / f"{kind}_diff.png")
    assert ratio <= 0.01, f"{kind}: {ratio:.2%} de píxeles distintos (ver {tmp_path})"
