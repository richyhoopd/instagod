"""Conversión de layouts v1 (layout.py) a escena v2."""
from __future__ import annotations

import copy

import pytest

from src.plantillas import contrato, layout
from src.plantillas import escena as E

FAMILIAS = {"Poppins-Bold", "Tinos"}


def _ct(aspecto: str) -> dict:
    return {"aspecto": aspecto, "base": list(contrato.CAMPOS_BASE),
            "extras": [{"id": "badge", "tipo": "texto", "etiqueta": "Etiqueta"}]}


def _v1_completo() -> dict:
    """Un v1 con los tres tipos de capa y todos los campos opcionales."""
    v1 = layout.vacio("4:5")
    v1["lienzo"]["fondo"] = "marca"
    v1["capas"] += [
        {"id": "badge", "tipo": "texto", "x": 60, "y": 60, "w": 400, "h": 80, "z": 3,
         "texto": "NUEVO", "fuente": "Tinos", "tam": 40, "peso": 400, "color": "marca",
         "alinear": "izq", "vertical": "arriba", "interlinea": 1.0, "mayusculas": True,
         "auto": False, "resaltar": False, "rot": 0, "opacidad": 0.8},
        {"id": "caja", "tipo": "caja", "x": 0, "y": 1200, "w": 1080, "h": 150, "z": 0,
         "color": "#112233", "radio": 24, "rot": 0, "opacidad": 1},
        {"id": "sello", "tipo": "imagen", "x": 800, "y": 1100, "w": 200, "h": 200, "z": 4,
         "archivo": "sello.png", "ajuste": "contain", "anclaje": "center bottom",
         "radio": 0, "rot": 12, "opacidad": 1},
    ]
    layout.validar(v1, _ct("4:5"), familias=FAMILIAS)   # el insumo es un v1 válido
    return v1


@pytest.mark.parametrize("aspecto", ["4:5", "9:16", "1:1"])
def test_el_vacio_v1_convertido_es_v2_valido(aspecto):
    if aspecto not in contrato.ASPECTOS:
        pytest.skip("1:1 llega en el Task 6")
    v2 = E.v1_a_v2(layout.vacio(aspecto), aspecto)
    E.validar(v2, _ct(aspecto), familias=FAMILIAS)
    assert v2["lienzo"]["formato"] == E.FORMATO_DE_ASPECTO[aspecto]
    assert [c["id"] for c in v2["capas"]] == ["fondo", "titular"]


def test_mapeo_campo_por_campo():
    v1 = _v1_completo()
    original = copy.deepcopy(v1)
    v2 = E.v1_a_v2(v1, "4:5")
    assert v1 == original                       # no muta la entrada
    E.validar(v2, _ct("4:5"), familias=FAMILIAS)

    assert v2["v"] == 2
    assert v2["lienzo"] == {"w": 1080, "h": 1350, "formato": "4x5",
                            "fondo": {"tipo": "color", "valor": "token:marca"}}
    assert v2["guias"] == {"cols": 12, "filas": 15, "iman": 8}
    capas = {c["id"]: c for c in v2["capas"]}

    fondo = capas["fondo"]
    assert fondo["tipo"] == "image" and fondo["campo"] == "imagen"
    assert fondo["ajuste"] == "cover" and fondo["mascara"] == "none"
    assert fondo["estilo"]["objectPosition"] == "center"
    assert "src" not in fondo

    tit = capas["titular"]
    assert tit["tipo"] == "text" and tit["campo"] == "titular" and tit["texto"] == ""
    assert tit["estilo"] == {"fontFamily": "Poppins-Bold", "fontWeight": 700, "fontSize": 64,
                             "lineHeight": 1.15, "color": "#ffffff", "textAlign": "center",
                             "verticalAlign": "center", "textTransform": "none",
                             "textWrap": "wrap", "spans": []}
    assert tit["auto"] is True and tit["resaltar"] is False

    badge = capas["badge"]
    assert badge["texto"] == "NUEVO" and "campo" not in badge
    assert badge["estilo"]["color"] == "token:marca"
    assert badge["estilo"]["textAlign"] == "left"
    assert badge["estilo"]["verticalAlign"] == "top"
    assert badge["estilo"]["textTransform"] == "uppercase"
    assert badge["opacity"] == 0.8

    caja = capas["caja"]
    assert caja["tipo"] == "shape" and caja["forma"] == "rect"
    assert caja["estilo"] == {"fill": "#112233", "radius": 24}

    sello = capas["sello"]
    assert sello["src"] == "fotos/sello.png"
    assert sello["estilo"]["objectPosition"] == "center bottom"
    assert sello["rot"] == 12

    for c in v2["capas"]:
        assert c["nombre"] == c["id"]
        assert c["bloqueada"] is False and c["oculta"] is False


def test_radio_de_imagen_se_vuelve_mascara():
    v1 = layout.vacio("4:5")
    v1["capas"][0]["radio"] = 32
    v2 = E.v1_a_v2(v1, "4:5")
    assert v2["capas"][0]["mascara"] == "rounded:32"


@pytest.mark.parametrize("y,h,esperado", [(0, 100, "top"), (600, 150, "center"),
                                          (1200, 100, "bottom")])
def test_anclaje_por_tercio_del_lienzo(y, h, esperado):
    v1 = layout.vacio("4:5")
    v1["capas"][1].update(y=y, h=h)
    assert E.v1_a_v2(v1, "4:5")["capas"][1]["anclaje"] == esperado


def test_una_capa_a_sangre_queda_anclada_arriba():
    assert E.v1_a_v2(layout.vacio("4:5"), "4:5")["capas"][0]["anclaje"] == "top"


def test_normalizar():
    vacio_v2 = E.normalizar(None, "4:5")
    assert vacio_v2 == E.v1_a_v2(layout.vacio("4:5"), "4:5")
    assert E.normalizar(layout.vacio("9:16"), "9:16")["lienzo"]["formato"] == "9x16"
    ya_v2 = E.normalizar(None, "4:5")
    copia = E.normalizar(ya_v2, "4:5")
    assert copia == ya_v2 and copia is not ya_v2
    with pytest.raises(E.EscenaInvalida):
        E.normalizar({"v": 7}, "4:5")
    with pytest.raises(E.EscenaInvalida):
        E.normalizar(layout.vacio("4:5"), "16:9")


@pytest.mark.parametrize("v1,fragmento", [
    ([], "layout"),
    ({"v": 1, "lienzo": "x", "capas": []}, "lienzo"),
    ({"v": 1, "capas": "x"}, "capas"),
    ({"v": 1, "capas": ["x"]}, "capa 0"),
    ({"v": 1, "capas": [{"tipo": "caja"}]}, "id"),
    ({"v": 1, "capas": [{"id": "a"}]}, "tipo"),
    ({"v": 1, "capas": [{"id": "a", "tipo": "video"}]}, "tipo de capa desconocido en v1"),
    ({"v": 1, "capas": [{"id": "a", "tipo": ["x"]}]}, "tipo"),
    ({"v": 1, "capas": [{"id": "a", "tipo": "imagen", "x": 0, "y": 0}]}, "campo"),
])
def test_v1_malformado_da_escena_invalida(v1, fragmento):
    with pytest.raises(E.EscenaInvalida, match=fragmento):
        E.v1_a_v2(v1, "4:5")
    if isinstance(v1, dict):
        with pytest.raises(E.EscenaInvalida):
            E.normalizar(v1, "4:5")


def test_normalizar_none_en_1x1():
    if "1:1" in contrato.ASPECTOS:
        assert E.normalizar(None, "1:1")["lienzo"]["formato"] == "1x1"
    else:
        with pytest.raises(E.EscenaInvalida):
            E.normalizar(None, "1:1")
