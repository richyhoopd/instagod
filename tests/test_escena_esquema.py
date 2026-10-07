"""Validación de la escena v2 (src/plantillas/escena.py)."""
from __future__ import annotations

import copy

import pytest

from src.plantillas import contrato
from src.plantillas import escena as E

CONTRATO = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE),
            "extras": [{"id": "badge", "tipo": "texto", "etiqueta": "Etiqueta"}]}


def _escena() -> dict:
    """Una escena v2 válida con una capa de cada tipo."""
    return {
        "v": 2,
        "lienzo": {"w": 1080, "h": 1350, "formato": "4x5",
                   "fondo": {"tipo": "color", "valor": "#FBFAF7"}},
        "tokens": {"colores": {"ink": "#1C1A23", "accent": "#F5C842"},
                   "fuente": "Poppins-Bold"},
        "capas": [
            {"id": "c_titular", "nombre": "Titular", "tipo": "text",
             "x": 72, "y": 196, "w": 936, "h": 320, "rot": 0, "opacity": 1, "z": 10,
             "bloqueada": False, "oculta": False, "anclaje": "top",
             "texto": "Lo que le regalas\n+ lo que la cuida.",
             "estilo": {"fontFamily": "Poppins-Bold", "fontWeight": 800, "fontSize": 96,
                        "lineHeight": 1.02, "letterSpacing": "-0.03em",
                        "color": "token:ink", "textAlign": "left", "textWrap": "balance",
                        "spans": [{"desde": 18, "hasta": 36, "color": "token:accent"}]}},
            {"id": "c_foto", "nombre": "Foto", "tipo": "image",
             "x": 540, "y": 600, "w": 480, "h": 600, "rot": -6, "opacity": 1, "z": 5,
             "bloqueada": False, "oculta": False, "anclaje": "bottom",
             "campo": "imagen", "src": "assets/abc123.png", "recorte": True,
             "ajuste": "cover", "mascara": "rounded:48",
             "estilo": {"filter": "drop-shadow(0 24px 48px rgba(61,53,128,.35))",
                        "mixBlendMode": "normal"},
             "fuente_asset": {"proveedor": "unsplash", "autor": "Ana", "licencia": "Unsplash",
                              "url": "https://unsplash.com/photos/x", "ig_handle": None}},
            {"id": "c_caja", "nombre": "Caja", "tipo": "shape",
             "x": 0, "y": 1200, "w": 1080, "h": 150, "rot": 0, "opacity": 0.9, "z": 2,
             "bloqueada": True, "oculta": False, "anclaje": "bottom",
             "forma": "rect", "estilo": {"fill": "token:marca", "radius": 0}},
            {"id": "c_logo", "nombre": "Logo", "tipo": "svg",
             "x": 900, "y": 40, "w": 120, "h": 120, "rot": 0, "opacity": 1, "z": 20,
             "bloqueada": False, "oculta": False, "anclaje": "top",
             "src": "assets/logo.svg", "ajuste": "contain", "estilo": {}},
            {"id": "c_clip", "nombre": "Clip", "tipo": "video",
             "x": 0, "y": 0, "w": 540, "h": 540, "rot": 0, "opacity": 1, "z": 1,
             "bloqueada": False, "oculta": True, "anclaje": "center",
             "src": "assets/clip.mp4", "ajuste": "cover", "mascara": "circle", "estilo": {}},
            {"id": "g_marca", "nombre": "Marca", "tipo": "group",
             "x": 0, "y": 40, "w": 1080, "h": 1310, "rot": 0, "opacity": 1, "z": 0,
             "bloqueada": False, "oculta": False, "anclaje": "top",
             "hijos": ["c_logo", "c_caja"]},
        ],
    }


def test_una_escena_completa_es_valida():
    E.validar(_escena(), CONTRATO, familias={"Poppins-Bold"})


def test_constantes_del_contrato():
    assert E.FORMATOS == {"4x5": (1080, 1350), "1x1": (1080, 1080), "9x16": (1080, 1920)}
    assert E.ASPECTO_DE_FORMATO == {"4x5": "4:5", "1x1": "1:1", "9x16": "9:16"}
    assert E.TIPOS == ("text", "image", "video", "shape", "svg", "group")
    assert issubclass(E.EscenaInvalida, ValueError)
    assert issubclass(E.EscenaInvalida, contrato.ContratoInvalido)


def test_una_escena_sin_capas_es_valida():
    esc = _escena()
    esc["capas"] = []
    E.validar(esc, CONTRATO)


def _rompe(mutar, mensaje: str) -> None:
    esc = _escena()
    mutar(esc)
    with pytest.raises(E.EscenaInvalida, match=mensaje):
        E.validar(esc, CONTRATO, familias={"Poppins-Bold"})


@pytest.mark.parametrize("mutar,mensaje", [
    (lambda e: e.update(v=1), "v=2"),
    (lambda e: e["lienzo"].update(formato="16x9"), "formato"),
    (lambda e: e["lienzo"].update(formato="9x16"), "el diseño es 4:5"),
    (lambda e: e["lienzo"].update(h=1300), "mide"),
    (lambda e: e["lienzo"]["fondo"].update(tipo="patron"), "fondo"),
    (lambda e: e["lienzo"].update(fondo={"tipo": "gradiente",
                                         "valor": "linear-gradient(red, blue);x:y"}), "fondo"),
    (lambda e: e["lienzo"].update(fondo={"tipo": "gradiente",
                                         "valor": "linear-gradient(url(x), blue)"}), "fondo"),
    (lambda e: e["tokens"]["colores"].update(marca="#000000"), "token"),
    (lambda e: e["capas"].append(copy.deepcopy(e["capas"][0])), "repetido"),
    (lambda e: e["capas"][0].update(id="Titular"), "id de capa"),
    (lambda e: e["capas"][0].update(tipo="texto"), "tipo"),
    (lambda e: e["capas"][0].update(x="72"), "'x'"),
    (lambda e: e["capas"][0].update(w=0), "'w'"),
    (lambda e: e["capas"][0].update(rot=200), "'rot'"),
    (lambda e: e["capas"][0].update(opacity=1.5), "'opacity'"),
    (lambda e: e["capas"][0].update(anclaje="arriba"), "anclaje"),
    (lambda e: e["capas"][0].update(oculta="no"), "oculta"),
    (lambda e: e["capas"][0]["estilo"].update(color="red"), "color"),
    (lambda e: e["capas"][0]["estilo"].update(color="token:nada"), "token de color 'nada'"),
    (lambda e: e["capas"][0]["estilo"].update(fontFamily="Papyrus"), "tipografía"),
    (lambda e: e["capas"][0]["estilo"].update(fontFamily="X';}</style>"), "tipografía"),
    (lambda e: e["capas"][0]["estilo"].update(fontWeight=850), "fontWeight"),
    (lambda e: e["capas"][0]["estilo"].update(fontSize=4), "fontSize"),
    (lambda e: e["capas"][0]["estilo"].update(letterSpacing="1rem"), "letterSpacing"),
    (lambda e: e["capas"][0]["estilo"].update(textWrap="auto"), "textWrap"),
    (lambda e: e["capas"][0]["estilo"].update(spans=[{"desde": 5, "hasta": 3,
                                                       "color": "#000000"}]), "span"),
    (lambda e: e["capas"][0]["estilo"].update(spans=[{"desde": 0, "hasta": 10, "color": "#000000"},
                                                      {"desde": 5, "hasta": 12,
                                                       "color": "#000000"}]), "enciman"),
    (lambda e: e["capas"][0].update(texto="{{ secreto }}"), "llaves"),
    (lambda e: e["capas"][0].update(texto="x" * 1001), "1000"),
    (lambda e: e["capas"][0].update(resaltar=True), "resaltado"),
    (lambda e: e["capas"][0].update(campo="no_existe"), "no está en el diseño"),
    (lambda e: e["capas"][2].update(campo="titular"), "se vinculan"),
    (lambda e: e["capas"][1].update(src="../etc/passwd"), "src"),
    (lambda e: e["capas"][1].update(src="https://x.com/a.png"), "src"),
    (lambda e: e["capas"][1].update(mascara="rounded:abc"), "mascara"),
    (lambda e: e["capas"][1].update(ajuste="fill"), "ajuste"),
    (lambda e: e["capas"][1]["estilo"].update(filter="url(#x)"), "filter"),
    (lambda e: e["capas"][1]["estilo"].update(filter="blur(2px);background:red"), "filter"),
    (lambda e: e["capas"][1]["estilo"].update(mixBlendMode="plus"), "mixBlendMode"),
    (lambda e: e["capas"][1]["estilo"].update(objectPosition="50% 50%"), "objectPosition"),
    (lambda e: e["capas"][3].update(src="assets/logo.png"), "svg"),
    (lambda e: e["capas"][2].update(forma="star"), "forma"),
    (lambda e: e["capas"][2]["estilo"].update(borderWidth=500), "borderWidth"),
    (lambda e: e["capas"][5].update(hijos=["c_nada"]), "hijos"),
    (lambda e: e["capas"][5].update(hijos=["g_marca"]), "hijos"),
    (lambda e: e["capas"].append({**copy.deepcopy(e["capas"][5]), "id": "g_otro",
                                  "hijos": ["c_logo"]}), "dos grupos"),
    (lambda e: e["capas"][1].update(fuente_asset={"autor": 3}), "fuente_asset"),
])
def test_escenas_invalidas(mutar, mensaje):
    _rompe(mutar, mensaje)


def test_grupos_en_ciclo():
    esc = _escena()
    esc["capas"][5]["hijos"] = ["c_logo", "g_dos"]
    esc["capas"].append({**copy.deepcopy(esc["capas"][5]), "id": "g_dos",
                         "hijos": ["g_marca"]})
    with pytest.raises(E.EscenaInvalida, match="ciclo"):
        E.validar(esc, CONTRATO)


def test_demasiadas_capas():
    esc = _escena()
    base = esc["capas"][2]
    esc["capas"] = [{**copy.deepcopy(base), "id": f"c{i}"} for i in range(E.MAX_CAPAS + 1)]
    with pytest.raises(E.EscenaInvalida, match="demasiadas capas"):
        E.validar(esc, CONTRATO)


def test_sin_familias_no_se_valida_la_tipografia():
    esc = _escena()
    esc["capas"][0]["estilo"]["fontFamily"] = "Papyrus"
    E.validar(esc, CONTRATO)            # familias=None: modo puro


def test_colores_aceptados():
    esc = _escena()
    for color in ("#000000", "rgba(0, 0, 0, .5)", "rgb(10,20,30)", "token:marca", "token:ink"):
        esc["capas"][0]["estilo"]["color"] = color
        E.validar(esc, CONTRATO)


def test_fondo_gradiente_e_imagen():
    esc = _escena()
    esc["lienzo"]["fondo"] = {"tipo": "gradiente",
                              "valor": "linear-gradient(180deg, #ffffff 0%, rgba(0,0,0,.4) 100%)"}
    E.validar(esc, CONTRATO)
    esc["lienzo"]["fondo"] = {"tipo": "imagen", "valor": "assets/fondo.jpg"}
    E.validar(esc, CONTRATO)
