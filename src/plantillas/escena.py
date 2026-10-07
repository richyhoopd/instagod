"""Escena v2: el diseño por coordenadas del editor tipo Figma.

Es lo que guarda `brand_templates.layout_json` a partir del editor v2 (spec
2026-10-06 §1). Este módulo es puro: valida, convierte desde el layout v1,
compila a HTML+CSS+Jinja y reacomoda entre formatos. No toca DB ni red.

Todo lo que acaba dentro de un `style="..."` o de un `url('...')` pasa antes
por una lista blanca: la escena la escriben el editor y el chat de IA, y
ninguno de los dos es de fiar.
"""
from __future__ import annotations

import copy
import html as _html
import re
from typing import Any

from . import layout as _layout
from .contrato import ContratoInvalido, variables_declaradas

FORMATOS: dict[str, tuple[int, int]] = {
    "4x5": (1080, 1350), "1x1": (1080, 1080), "9x16": (1080, 1920)}
# El valor es el de la columna brand_templates.aspecto y contrato["aspecto"].
ASPECTO_DE_FORMATO = {"4x5": "4:5", "1x1": "1:1", "9x16": "9:16"}
FORMATO_DE_ASPECTO = {a: f for f, a in ASPECTO_DE_FORMATO.items()}
TIPOS: tuple[str, ...] = ("text", "image", "video", "shape", "svg", "group")
ANCLAJES = ("top", "center", "bottom")
MAX_CAPAS = 80
MAX_TEXTO = 1000
MAX_SPANS = 50
MAX_TOKENS = 32

TEXT_ALIGN = ("left", "center", "right", "justify")
TEXT_WRAP = ("wrap", "balance", "pretty", "nowrap")
VERTICAL = ("top", "center", "bottom")
TRANSFORM = ("none", "uppercase")
AJUSTES = ("cover", "contain")
FORMAS = ("rect", "ellipse")
BLENDS = ("normal", "multiply", "screen", "overlay", "darken", "lighten",
          "color-dodge", "color-burn", "hard-light", "soft-light", "difference",
          "exclusion", "hue", "saturation", "color", "luminosity")
# Mismas posiciones que el `anclaje` de imagen v1: así la conversión no pierde nada.
POSICIONES = _layout.ANCLAJES
_FUENTE_ASSET = ("proveedor", "autor", "licencia", "url", "ig_handle")

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_RGBA = re.compile(
    r"^rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(,\s*(0|1|0?\.\d{1,3}|1\.0)\s*)?\)$")
_CAMPO = re.compile(r"[a-z_][a-z0-9_]*")        # lo único que entra a {{ ... }}
_TOKEN = re.compile(r"^token:([a-z][a-z0-9_-]{0,31})$")
_SRC = re.compile(r"^(assets|fotos)/[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_FUENTE = re.compile(r"^[A-Za-z0-9 ._-]{1,60}$")
_TRACKING = re.compile(r"^-?\d{1,3}(\.\d{1,3})?(em|px)$")
_MASCARA = re.compile(r"^(none|circle|rounded:\d{1,4})$")
# filter y gradientes: solo letras, números, espacios y . , % # ( ) -. Sin ; { } < > " '
# ni url(): no hay forma de cerrar la declaración ni de pedir un recurso externo.
_CSS_LIBRE = re.compile(r"^[a-zA-Z0-9 .,%#()\-]{1,300}$")
_GRADIENTE = re.compile(r"^(linear|radial)-gradient\([a-zA-Z0-9 .,%#()\-]{1,300}\)$")


class EscenaInvalida(ContratoInvalido):
    """Una escena v2 que no se puede compilar.

    Hereda de ContratoInvalido (y por tanto de ValueError): los `except
    ContratoInvalido` del servicio y del router la vuelven 422 sin cambios.
    """


# ---------------------------------------------------------------------------
# Validación
# ---------------------------------------------------------------------------

def _num(d: dict[str, Any], clave: str, minimo: float, maximo: float,
         defecto: Any, donde: str, *, entero: bool = False) -> float:
    valor = d.get(clave, defecto)
    tipo_ok = isinstance(valor, int) if entero else isinstance(valor, (int, float))
    if isinstance(valor, bool) or not tipo_ok:
        raise EscenaInvalida(
            f"{donde}: '{clave}' debe ser {'un entero' if entero else 'un número'}")
    if not minimo <= valor <= maximo:
        raise EscenaInvalida(f"{donde}: '{clave}' fuera de rango ({minimo:g} a {maximo:g})")
    return valor


def _uno_de(d: dict[str, Any], clave: str, opciones: tuple, defecto: Any,
            donde: str) -> Any:
    valor = d.get(clave, defecto)
    if valor not in opciones:
        raise EscenaInvalida(
            f"{donde}: '{clave}' debe ser uno de: {', '.join(map(str, opciones))}")
    return valor


def _booleano(d: dict[str, Any], clave: str, donde: str) -> None:
    if not isinstance(d.get(clave, False), bool):
        raise EscenaInvalida(f"{donde}: '{clave}' debe ser verdadero o falso")


def _color(valor: Any, colores: dict[str, str], donde: str) -> None:
    if isinstance(valor, str):
        if _HEX.fullmatch(valor) or _RGBA.fullmatch(valor):
            return
        m = _TOKEN.fullmatch(valor)
        if m:
            if m.group(1) == "marca" or m.group(1) in colores:
                return
            raise EscenaInvalida(f"{donde}: el token de color '{m.group(1)}' no existe")
    raise EscenaInvalida(
        f"{donde}: color inválido {valor!r} (usa #rrggbb, rgba(...) o token:<nombre>)")


def _css_libre(valor: Any, regex: re.Pattern, donde: str, clave: str) -> None:
    if (not isinstance(valor, str) or not regex.fullmatch(valor)
            or "url(" in valor.lower()):
        raise EscenaInvalida(f"{donde}: '{clave}' tiene un valor no permitido")


def _src(valor: Any, donde: str, clave: str = "src") -> None:
    if not isinstance(valor, str) or not _SRC.fullmatch(valor):
        raise EscenaInvalida(
            f"{donde}: '{clave}' debe ser assets/<archivo> o fotos/<archivo>")


def _familia(valor: Any, familias: set[str] | None, donde: str) -> None:
    if not isinstance(valor, str) or not _FUENTE.fullmatch(valor):
        raise EscenaInvalida(f"{donde}: falta la tipografía o tiene caracteres raros")
    if familias is not None and valor not in familias:
        raise EscenaInvalida(
            f"{donde}: la tipografía '{valor}' no está instalada para esta marca")


def _validar_fondo(fondo: Any, colores: dict[str, str]) -> None:
    donde = "lienzo.fondo"
    if not isinstance(fondo, dict):
        raise EscenaInvalida(f"{donde}: falta el fondo")
    tipo, valor = fondo.get("tipo"), fondo.get("valor")
    if tipo == "color":
        _color(valor, colores, donde)
    elif tipo == "gradiente":
        _css_libre(valor, _GRADIENTE, donde, "valor")
    elif tipo == "imagen":
        _src(valor, donde, "valor")
    else:
        raise EscenaInvalida(f"{donde}: el tipo de fondo debe ser color, gradiente o imagen")


def _validar_visual(estilo: dict[str, Any], donde: str) -> None:
    """filter y mixBlendMode: comunes a imagen, video, svg y forma."""
    if "filter" in estilo and estilo["filter"] not in (None, "", "none"):
        _css_libre(estilo["filter"], _CSS_LIBRE, donde, "filter")
    _uno_de(estilo, "mixBlendMode", BLENDS, "normal", donde)


def _validar_fuente_asset(capa: dict[str, Any], donde: str) -> None:
    fa = capa.get("fuente_asset")
    if fa is None:
        return
    if not isinstance(fa, dict) or any(
            k not in _FUENTE_ASSET or not (v is None or (isinstance(v, str) and len(v) <= 500))
            for k, v in fa.items()):
        raise EscenaInvalida(f"{donde}: 'fuente_asset' mal formada")


def _validar_text(capa, estilo, colores, familias, donde) -> None:
    texto = capa.get("texto", "")
    if not isinstance(texto, str) or len(texto) > MAX_TEXTO:
        raise EscenaInvalida(
            f"{donde}: el texto fijo debe ser texto de hasta {MAX_TEXTO} caracteres")
    if any(m in texto for m in ("{{", "{%", "{#")):
        raise EscenaInvalida(f"{donde}: el texto fijo no puede llevar llaves de plantilla")
    _familia(estilo.get("fontFamily"), familias, donde)
    _num(estilo, "fontSize", 8, 400, None, donde)
    if estilo.get("fontWeight", 400) not in _layout.PESOS:
        raise EscenaInvalida(f"{donde}: 'fontWeight' debe ser 100, 200, … 900")
    _num(estilo, "lineHeight", 0.8, 3.0, 1.2, donde)
    tracking = estilo.get("letterSpacing")
    if tracking is not None and (not isinstance(tracking, str) or not _TRACKING.fullmatch(tracking)):
        raise EscenaInvalida(f"{donde}: 'letterSpacing' debe ser como -0.03em o 2px")
    _color(estilo.get("color", "#000000"), colores, donde)
    _uno_de(estilo, "textAlign", TEXT_ALIGN, "left", donde)
    _uno_de(estilo, "textWrap", TEXT_WRAP, "wrap", donde)
    _uno_de(estilo, "verticalAlign", VERTICAL, "top", donde)
    _uno_de(estilo, "textTransform", TRANSFORM, "none", donde)
    _booleano(capa, "auto", donde)
    _booleano(capa, "resaltar", donde)
    if capa.get("resaltar") and not capa.get("campo"):
        raise EscenaInvalida(
            f"{donde}: el resaltado solo aplica a datos del diseño, no a un texto fijo")

    spans = estilo.get("spans", [])
    if not isinstance(spans, list) or len(spans) > MAX_SPANS:
        raise EscenaInvalida(f"{donde}: 'spans' debe ser una lista de hasta {MAX_SPANS}")
    if spans and capa.get("campo"):
        raise EscenaInvalida(f"{donde}: los span de color solo aplican a un texto fijo")
    for s in spans:
        if (not isinstance(s, dict)
                or any(isinstance(s.get(k), bool) or not isinstance(s.get(k), int)
                       for k in ("desde", "hasta"))
                or not 0 <= s["desde"] < s["hasta"] <= len(texto)):
            raise EscenaInvalida(f"{donde}: un span tiene desde/hasta fuera del texto")
        _color(s.get("color"), colores, donde)
    ordenados = sorted(spans, key=lambda s: s["desde"])
    for a, b in zip(ordenados, ordenados[1:]):
        if b["desde"] < a["hasta"]:
            raise EscenaInvalida(f"{donde}: dos span de color se enciman")


def _validar_image(capa, estilo, colores, familias, donde) -> None:
    if capa.get("src") is not None or not capa.get("campo"):
        _src(capa.get("src"), donde)
    _booleano(capa, "recorte", donde)
    _uno_de(capa, "ajuste", AJUSTES, "cover", donde)
    mascara = capa.get("mascara", "none")
    if not isinstance(mascara, str) or not _MASCARA.fullmatch(mascara):
        raise EscenaInvalida(f"{donde}: 'mascara' debe ser none, circle o rounded:N")
    _uno_de(estilo, "objectPosition", POSICIONES, "center", donde)
    _validar_visual(estilo, donde)
    _validar_fuente_asset(capa, donde)


def _validar_video(capa, estilo, colores, familias, donde) -> None:
    _validar_image(capa, estilo, colores, familias, donde)
    if capa.get("poster") is not None:
        _src(capa["poster"], donde, "poster")


def _validar_svg(capa, estilo, colores, familias, donde) -> None:
    _src(capa.get("src"), donde)
    if not capa["src"].lower().endswith(".svg"):
        raise EscenaInvalida(f"{donde}: una capa svg necesita un archivo .svg")
    _uno_de(capa, "ajuste", AJUSTES, "contain", donde)
    _validar_visual(estilo, donde)
    _validar_fuente_asset(capa, donde)


def _validar_shape(capa, estilo, colores, familias, donde) -> None:
    _uno_de(capa, "forma", FORMAS, "rect", donde)
    _color(estilo.get("fill", "#000000"), colores, donde)
    _num(estilo, "radius", 0, 2000, 0, donde)
    _num(estilo, "borderWidth", 0, 200, 0, donde)
    if estilo.get("borderColor") is not None:
        _color(estilo["borderColor"], colores, donde)
    _validar_visual(estilo, donde)


def _validar_group(capa, estilo, colores, familias, donde) -> None:
    hijos = capa.get("hijos")
    if (not isinstance(hijos, list) or not hijos
            or any(not isinstance(h, str) for h in hijos)
            or len(set(hijos)) != len(hijos)):
        raise EscenaInvalida(f"{donde}: 'hijos' debe ser una lista de ids sin repetir")


_VALIDADORES = {"text": _validar_text, "image": _validar_image, "video": _validar_video,
                "svg": _validar_svg, "shape": _validar_shape, "group": _validar_group}


def _validar_capa(capa: dict[str, Any], colores: dict[str, str], declaradas: set[str],
                  familias: set[str] | None, imagenes: frozenset[str] = frozenset()) -> None:
    donde = f"capa '{capa['id']}'"
    tipo = capa.get("tipo")
    if tipo not in TIPOS:
        raise EscenaInvalida(f"{donde}: tipo desconocido {tipo!r}")
    nombre = capa.get("nombre", capa["id"])
    if not isinstance(nombre, str) or not 0 < len(nombre) <= 80:
        raise EscenaInvalida(f"{donde}: 'nombre' debe ser texto de 1 a 80 caracteres")
    for clave, lo, hi in (("x", -2000, 4000), ("y", -2000, 4000),
                          ("w", 1, 4000), ("h", 1, 4000)):
        _num(capa, clave, lo, hi, None, donde)
    _num(capa, "rot", -180, 180, 0, donde)
    _num(capa, "opacity", 0, 1, 1, donde)
    _num(capa, "z", 0, 999, 0, donde, entero=True)
    _booleano(capa, "bloqueada", donde)
    _booleano(capa, "oculta", donde)
    _uno_de(capa, "anclaje", ANCLAJES, "top", donde)
    campo = capa.get("campo")
    if campo is not None:
        if tipo not in ("text", "image", "video"):
            raise EscenaInvalida(f"{donde}: solo texto, imagen y video se vinculan a un dato")
        if not isinstance(campo, str) or campo not in declaradas:
            raise EscenaInvalida(f"{donde}: el dato '{campo}' no está en el diseño")
        if not _CAMPO.fullmatch(campo):
            raise EscenaInvalida(f"{donde}: el nombre del dato no es un identificador válido")
        # Imagen y video emiten el dato dentro de url('...') / src="..." sin escape:
        # solo pueden ligarse a datos que son URL (los arma render con _to_src).
        if tipo in ("image", "video") and campo not in imagenes:
            raise EscenaInvalida(
                f"{donde}: una capa de {'imagen' if tipo == 'image' else 'video'} solo "
                "se liga a 'imagen', 'logo' o a un dato de tipo imagen")
    estilo = capa.get("estilo", {})
    if not isinstance(estilo, dict):
        raise EscenaInvalida(f"{donde}: 'estilo' debe ser un objeto")
    _VALIDADORES[tipo](capa, estilo, colores, familias, donde)


def validar(escena: dict[str, Any], contrato: dict[str, Any],
            *, familias: set[str] | None = None) -> None:
    """Que la escena se pueda compilar. Lanza EscenaInvalida con el porqué.

    `familias` es el catálogo tipográfico de la marca; con None no se revisa
    la tipografía (tests puros, igual que `layout.validar`).
    """
    if not isinstance(escena, dict) or escena.get("v") != 2:
        raise EscenaInvalida("la escena debe ser un objeto con v=2")

    lienzo = escena.get("lienzo")
    if not isinstance(lienzo, dict):
        raise EscenaInvalida("falta el lienzo")
    formato = lienzo.get("formato")
    if not isinstance(formato, str) or formato not in FORMATOS:
        raise EscenaInvalida(f"formato desconocido {formato!r} (4x5, 1x1 o 9x16)")
    if ASPECTO_DE_FORMATO[formato] != contrato.get("aspecto"):
        raise EscenaInvalida(
            f"el lienzo es {formato} pero el diseño es {contrato.get('aspecto')}")
    if (lienzo.get("w"), lienzo.get("h")) != FORMATOS[formato]:
        ancho, alto = FORMATOS[formato]
        raise EscenaInvalida(f"el lienzo {formato} mide {ancho}x{alto}")

    tokens = escena.get("tokens") or {}
    colores = tokens.get("colores") or {} if isinstance(tokens, dict) else None
    if not isinstance(colores, dict) or len(colores) > MAX_TOKENS:
        raise EscenaInvalida(f"tokens.colores debe ser un objeto de hasta {MAX_TOKENS}")
    for nombre, valor in colores.items():
        if not isinstance(nombre, str) or not _ID.fullmatch(nombre) or nombre == "marca":
            raise EscenaInvalida(f"token de color con nombre inválido: {nombre!r}")
        if not isinstance(valor, str) or not (_HEX.fullmatch(valor) or _RGBA.fullmatch(valor)):
            raise EscenaInvalida(f"el token de color '{nombre}' debe ser #rrggbb o rgba(...)")
    if tokens.get("fuente") is not None:
        _familia(tokens["fuente"], familias, "tokens")
    _validar_fondo(lienzo.get("fondo"), colores)

    guias = escena.get("guias")
    if guias is not None and (not isinstance(guias, dict) or any(
            isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 64
            for v in guias.values())):
        raise EscenaInvalida("la rejilla tiene un valor raro")

    capas = escena.get("capas")
    if not isinstance(capas, list):
        raise EscenaInvalida("'capas' debe ser una lista")
    if len(capas) > MAX_CAPAS:
        raise EscenaInvalida(f"el diseño tiene demasiadas capas ({len(capas)}, tope {MAX_CAPAS})")

    ids: set[str] = set()
    for capa in capas:
        if not isinstance(capa, dict):
            raise EscenaInvalida("cada capa debe ser un objeto")
        cid = capa.get("id")
        if not isinstance(cid, str) or not _ID.fullmatch(cid):
            raise EscenaInvalida(f"id de capa inválido: {cid!r}")
        if cid in ids:
            raise EscenaInvalida(f"id de capa repetido: '{cid}'")
        ids.add(cid)

    declaradas = variables_declaradas(contrato)
    imagenes = frozenset({"imagen", "logo"} | {
        e["id"] for e in contrato.get("extras") or []
        if isinstance(e, dict) and e.get("tipo") == "imagen" and "id" in e})
    padre_de: dict[str, str] = {}
    for capa in capas:
        _validar_capa(capa, colores, declaradas, familias, imagenes)
        if capa["tipo"] != "group":
            continue
        for hijo in capa["hijos"]:
            if hijo not in ids or hijo == capa["id"]:
                raise EscenaInvalida(
                    f"capa '{capa['id']}': 'hijos' apunta a una capa que no existe: '{hijo}'")
            if hijo in padre_de:
                raise EscenaInvalida(f"la capa '{hijo}' está en dos grupos")
            padre_de[hijo] = capa["id"]
    for inicio in padre_de:
        vistos, actual = set(), inicio
        while actual in padre_de:
            if actual in vistos:
                raise EscenaInvalida("los grupos forman un ciclo")
            vistos.add(actual)
            actual = padre_de[actual]


# ---------------------------------------------------------------------------
# v1 -> v2
# ---------------------------------------------------------------------------

_ALINEAR_V1 = {"izq": "left", "centro": "center", "der": "right"}
_VERTICAL_V1 = {"arriba": "top", "centro": "center", "abajo": "bottom"}


def _color_v1(valor: Any) -> Any:
    return "token:marca" if valor == "marca" else valor


def _anclaje_de(capa: dict[str, Any], ancho: int, alto: int) -> str:
    """Hacia dónde se mueve la capa al cambiar de formato.

    Lo que cubre el lienzo entero (la foto de fondo) se queda arriba: el
    reformateo lo estira. Lo demás, por el tercio en que cae su centro.
    """
    x, y, w, h = capa.get("x", 0), capa.get("y", 0), capa.get("w", 0), capa.get("h", 0)
    if x <= 0 and y <= 0 and x + w >= ancho and y + h >= alto:
        return "top"
    centro = y + h / 2
    if centro < alto / 3:
        return "top"
    if centro > alto * 2 / 3:
        return "bottom"
    return "center"


def _comunes_v1(capa: dict[str, Any], ancho: int, alto: int) -> dict[str, Any]:
    return {
        "id": capa["id"], "nombre": capa["id"],
        "x": capa.get("x", 0), "y": capa.get("y", 0),
        "w": capa.get("w", 1), "h": capa.get("h", 1),
        "rot": capa.get("rot", 0), "opacity": capa.get("opacidad", 1),
        "z": capa.get("z", 0), "bloqueada": False, "oculta": False,
        "anclaje": _anclaje_de(capa, ancho, alto),
    }


def _texto_v1(capa: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    nueva = {**base, "tipo": "text"}
    if capa.get("campo"):
        nueva["campo"] = capa["campo"]
        nueva["texto"] = ""
    else:
        nueva["texto"] = capa.get("texto", "")
    nueva["estilo"] = {
        "fontFamily": capa.get("fuente"),
        "fontWeight": capa.get("peso", 400),
        "fontSize": capa.get("tam"),
        "lineHeight": capa.get("interlinea", 1.2),
        "color": _color_v1(capa.get("color", "#000000")),
        "textAlign": _ALINEAR_V1.get(capa.get("alinear", "centro"), "center"),
        "verticalAlign": _VERTICAL_V1.get(capa.get("vertical", "centro"), "center"),
        "textTransform": "uppercase" if capa.get("mayusculas") else "none",
        "textWrap": "wrap",
        "spans": [],
    }
    nueva["auto"] = bool(capa.get("auto", False))
    nueva["resaltar"] = bool(capa.get("resaltar", False))
    return nueva


def _imagen_v1(capa: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    nueva = {**base, "tipo": "image"}
    if capa.get("campo"):
        nueva["campo"] = capa["campo"]
    else:
        nueva["src"] = f"fotos/{capa.get('archivo')}"
    radio = capa.get("radio", 0) or 0
    nueva.update(recorte=False, ajuste=capa.get("ajuste", "cover"),
                 mascara=f"rounded:{radio}" if radio else "none",
                 estilo={"objectPosition": capa.get("anclaje", "center")})
    return nueva


def _caja_v1(capa: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    return {**base, "tipo": "shape", "forma": "rect",
            "estilo": {"fill": _color_v1(capa.get("color", "#000000")),
                       "radius": capa.get("radio", 0) or 0}}


_DE_V1 = {"texto": _texto_v1, "imagen": _imagen_v1, "caja": _caja_v1}


def _guardar_v1(layout: Any) -> None:
    """Estructura mínima de un v1 para poder convertirlo; si no, EscenaInvalida."""
    if not isinstance(layout, dict):
        raise EscenaInvalida("el layout v1 debe ser un objeto")
    if layout.get("lienzo") is not None and not isinstance(layout["lienzo"], dict):
        raise EscenaInvalida("lienzo del layout v1 debe ser un objeto")
    capas = layout.get("capas")
    if capas is None:
        return
    if not isinstance(capas, list):
        raise EscenaInvalida("capas del layout v1 debe ser una lista")
    for i, capa in enumerate(capas):
        if not isinstance(capa, dict):
            raise EscenaInvalida(f"capa {i} del layout v1 debe ser un objeto")
        if not isinstance(capa.get("id"), str):
            raise EscenaInvalida(f"capa {i} del layout v1 sin id de texto")
        tipo = capa.get("tipo")
        if not isinstance(tipo, str):
            raise EscenaInvalida(f"capa {capa['id']!r}: falta el tipo de capa")
        if tipo not in _DE_V1:
            raise EscenaInvalida(f"tipo de capa desconocido en v1: {tipo!r} (capa {capa['id']!r})")
        if tipo == "imagen" and not capa.get("campo") and not capa.get("archivo"):
            raise EscenaInvalida(f"capa {capa['id']!r}: imagen v1 sin campo ni archivo")


def v1_a_v2(layout: dict[str, Any], aspecto: str) -> dict[str, Any]:
    """Convierte un layout v1 (`layout.py`) a escena v2 sin mutar la entrada.

    No valida: el v1 ya pasó por `layout.validar` al guardarse. Quien necesite
    la garantía llama a `validar` sobre el resultado. Lo que sí hace es no
    reventar con KeyError/TypeError si `layout_json` (que sale de la DB) viene
    malformado: eso es `EscenaInvalida`.
    """
    if not isinstance(aspecto, str) or aspecto not in FORMATO_DE_ASPECTO:
        raise EscenaInvalida(f"aspecto desconocido {aspecto!r}")
    _guardar_v1(layout)
    formato = FORMATO_DE_ASPECTO[aspecto]
    ancho, alto = FORMATOS[formato]
    lienzo_v1 = layout.get("lienzo") or {}
    escena = {
        "v": 2,
        "lienzo": {"w": ancho, "h": alto, "formato": formato,
                   "fondo": {"tipo": "color",
                             "valor": _color_v1(lienzo_v1.get("fondo", "#ffffff"))}},
        "tokens": {"colores": {}},
        "capas": [
            _DE_V1[c["tipo"]](c, _comunes_v1(c, ancho, alto))
            for c in layout.get("capas") or []
        ],
    }
    if layout.get("guias"):
        escena["guias"] = copy.deepcopy(layout["guias"])
    return escena


def normalizar(layout: dict[str, Any] | None, aspecto: str) -> dict[str, Any]:
    """Cualquier cosa guardada en layout_json -> escena v2 (copia nueva).

    None arranca el lienzo en blanco de siempre (`layout.vacio`) ya convertido.
    Con v2 solo copia: no valida, eso lo hace `validar`.
    """
    if layout is None:
        if not isinstance(aspecto, str) or aspecto not in _layout.LIENZO:
            raise EscenaInvalida(f"aspecto desconocido {aspecto!r}")
        return v1_a_v2(_layout.vacio(aspecto), aspecto)
    version = layout.get("v") if isinstance(layout, dict) else None
    if version == 1:
        return v1_a_v2(layout, aspecto)
    if version == 2:
        return copy.deepcopy(layout)
    raise EscenaInvalida(f"versión de diseño desconocida: {version!r}")


# ---------------------------------------------------------------------------
# Compilador: escena -> HTML+CSS+Jinja
#
# Seguridad: aquí solo se compila lo que `validar` ya aprobó con listas
# blancas (regex con fullmatch, enumeraciones, números acotados). Nada de la
# escena entra a `style="..."`, `url('...')` o Jinja por otra vía; el texto
# fijo se escapa con html.escape y `validar` le prohíbe `{{`, `{%` y `{#`.
# ---------------------------------------------------------------------------

_JUSTIFY = {"left": "flex-start", "center": "center", "right": "flex-end",
            "justify": "flex-start"}
_ALIGN = {"top": "flex-start", "center": "center", "bottom": "flex-end"}


def _resolver(color: str, colores: dict[str, str]) -> str:
    """token:marca se resuelve al renderizar; los demás tokens, aquí."""
    m = _TOKEN.fullmatch(color)
    if not m:
        return color
    return "{{ color_marca }}" if m.group(1) == "marca" else colores[m.group(1)]


def _url(src: str) -> str:
    """assets/x -> {{ assets_dir }}/x ; fotos/x -> {{ fotos_dir }}/x."""
    carpeta, archivo = src.split("/", 1)
    return "{{ %s_dir }}/%s" % (carpeta, archivo)


def _campo(capa: dict[str, Any]) -> str | None:
    """El nombre de dato listo para {{ }}; solo identificadores (defensa en profundidad)."""
    campo = capa.get("campo")
    if campo and not (isinstance(campo, str) and _CAMPO.fullmatch(campo)):
        raise EscenaInvalida(f"capa '{capa['id']}': el nombre del dato no es un identificador válido")
    return campo or None


def _origen(capa: dict[str, Any]) -> str:
    """El dato del post si viene; si viene vacío, el archivo fijo de la capa."""
    campo, src = _campo(capa), capa.get("src")
    if campo and src:
        carpeta, archivo = src.split("/", 1)
        return "{{ %s or (%s_dir ~ '/%s') }}" % (campo, carpeta, archivo)
    if campo:
        return "{{ %s }}" % campo
    return _url(src)


def _caja(capa: dict[str, Any]) -> list[str]:
    partes = ["position:absolute",
              f"left:{capa['x']:g}px", f"top:{capa['y']:g}px",
              f"width:{capa['w']:g}px", f"height:{capa['h']:g}px",
              f"z-index:{capa.get('z', 0)}"]
    if capa.get("rot"):
        partes.append(f"transform:rotate({capa['rot']:g}deg)")
    if capa.get("opacity", 1) != 1:
        partes.append(f"opacity:{capa['opacity']:g}")
    return partes


def _mascara(valor: str) -> list[str]:
    if valor == "circle":
        return ["border-radius:50%", "overflow:hidden"]
    if valor.startswith("rounded:") and int(valor.split(":")[1]):
        return [f"border-radius:{int(valor.split(':')[1])}px", "overflow:hidden"]
    return []


def _visual(estilo: dict[str, Any]) -> list[str]:
    partes = []
    if estilo.get("filter") not in (None, "", "none"):
        partes.append(f"filter:{estilo['filter']}")
    if estilo.get("mixBlendMode", "normal") != "normal":
        partes.append(f"mix-blend-mode:{estilo['mixBlendMode']}")
    return partes


def _div(capa: dict[str, Any], css: list[str], dentro: str = "") -> str:
    return f'<div id="capa-{capa["id"]}" class="capa" style="{";".join(css)}">{dentro}</div>'


# desde/hasta son puntos de código de Python (str slicing), no UTF-16: el frontend convierte.
def _texto_con_spans(texto: str, spans: list[dict[str, Any]], colores: dict[str, str]) -> str:
    piezas, cursor = [], 0
    for s in sorted(spans, key=lambda s: s["desde"]):
        piezas.append(_html.escape(texto[cursor:s["desde"]], quote=False))
        trozo = _html.escape(texto[s["desde"]:s["hasta"]], quote=False)
        piezas.append(f'<span style="color:{_resolver(s["color"], colores)}">{trozo}</span>')
        cursor = s["hasta"]
    piezas.append(_html.escape(texto[cursor:], quote=False))
    return "".join(piezas)


def _pintar_text(capa: dict[str, Any], colores: dict[str, str]) -> str:
    e = capa.get("estilo", {})
    if _campo(capa):
        contenido = ("{{ %s|resaltar }}" if capa.get("resaltar") else "{{ %s }}") % capa["campo"]
    else:
        contenido = _texto_con_spans(capa.get("texto", ""), e.get("spans", []), colores)
    alinear = e.get("textAlign", "left")
    caja = _caja(capa) + ["display:flex", f"justify-content:{_JUSTIFY[alinear]}",
                          f"align-items:{_ALIGN[e.get('verticalAlign', 'top')]}",
                          "overflow:hidden"]
    texto = [f"font-family:'{_html.escape(e['fontFamily'], quote=True)}',sans-serif",
             f"font-size:{e['fontSize']:g}px",
             f"font-weight:{e.get('fontWeight', 400)}",
             f"color:{_resolver(e.get('color', '#000000'), colores)}",
             f"line-height:{e.get('lineHeight', 1.2):g}",
             f"text-align:{alinear}",
             "width:100%"]
    if e.get("letterSpacing"):
        texto.append(f"letter-spacing:{e['letterSpacing']}")
    wrap = e.get("textWrap", "wrap")
    if not capa.get("campo"):
        # Los saltos de línea del texto fijo son intencionales; los del dato
        # del post no (paridad con v1, que no los respetaba).
        texto.append("white-space:pre" if wrap == "nowrap" else "white-space:pre-line")
    elif wrap == "nowrap":
        texto.append("white-space:nowrap")
    if wrap in ("balance", "pretty"):
        texto.append(f"text-wrap:{wrap}")
    if e.get("textTransform") == "uppercase":
        texto.append("text-transform:uppercase")
    fit = " data-fit" if capa.get("auto") else ""
    return _div(capa, caja, f'<div{fit} style="{";".join(texto)}">{contenido}</div>')


def _pintar_image(capa: dict[str, Any], colores: dict[str, str]) -> str:
    e = capa.get("estilo", {})
    css = (_caja(capa)
           + [f"background-image:url('{_origen(capa)}')",
              f"background-size:{capa.get('ajuste', 'cover')}",
              f"background-position:{e.get('objectPosition', 'center')}",
              "background-repeat:no-repeat"]
           + _mascara(capa.get("mascara", "none")) + _visual(e))
    return _div(capa, css)


def _pintar_video(capa: dict[str, Any], colores: dict[str, str]) -> str:
    """El PNG sale con el primer cuadro; la animación es del subproyecto de video."""
    e = capa.get("estilo", {})
    css = _caja(capa) + _mascara(capa.get("mascara", "none")) + _visual(e)
    poster = f' poster="{_url(capa["poster"])}"' if capa.get("poster") else ""
    video = (f'<video src="{_origen(capa)}"{poster} muted playsinline preload="auto" '
             f'style="width:100%;height:100%;display:block;'
             f'object-fit:{capa.get("ajuste", "cover")};'
             f'object-position:{e.get("objectPosition", "center")}"></video>')
    return _div(capa, css, video)


def _pintar_svg(capa: dict[str, Any], colores: dict[str, str]) -> str:
    # Como imagen de fondo y nunca en línea: un SVG en línea podría traer <script>.
    e = capa.get("estilo", {})
    css = (_caja(capa)
           + [f"background-image:url('{_url(capa['src'])}')",
              f"background-size:{capa.get('ajuste', 'contain')}",
              "background-position:center", "background-repeat:no-repeat"]
           + _visual(e))
    return _div(capa, css)


def _pintar_shape(capa: dict[str, Any], colores: dict[str, str]) -> str:
    e = capa.get("estilo", {})
    css = _caja(capa) + [f"background:{_resolver(e.get('fill', '#000000'), colores)}"]
    if capa.get("forma") == "ellipse":
        css.append("border-radius:50%")
    elif e.get("radius"):
        css.append(f"border-radius:{e['radius']:g}px")
    if e.get("borderWidth"):
        borde = _resolver(e.get("borderColor", "#000000"), colores)
        css.append(f"border:{e['borderWidth']:g}px solid {borde}")
    return _div(capa, css + _visual(e))


_PINTORES = {"text": _pintar_text, "image": _pintar_image, "video": _pintar_video,
             "svg": _pintar_svg, "shape": _pintar_shape}


def _ocultas(capas: list[dict[str, Any]]) -> set[str]:
    """Las capas ocultas y, si es un grupo, todo lo que cuelga de él."""
    hijos = {c["id"]: c.get("hijos", []) for c in capas if c["tipo"] == "group"}
    fuera: set[str] = set()
    pendientes = [c["id"] for c in capas if c.get("oculta")]
    while pendientes:
        cid = pendientes.pop()
        if cid not in fuera:
            fuera.add(cid)
            pendientes.extend(hijos.get(cid, []))
    return fuera


def _fondo_css(fondo: dict[str, Any], colores: dict[str, str]) -> str:
    if fondo["tipo"] == "color":
        return _resolver(fondo["valor"], colores)
    if fondo["tipo"] == "gradiente":
        return fondo["valor"]
    return f"url('{_url(fondo['valor'])}') center/cover no-repeat"


def _font_faces(capas: list[dict[str, Any]], fuentes: list[dict[str, Any]] | None) -> str:
    """Solo las tipografías que se pintan (mismo criterio que layout.py)."""
    if not fuentes:
        return ""
    usadas = {c["estilo"]["fontFamily"] for c in capas if c["tipo"] == "text"}
    piezas = []
    for f in sorted(fuentes, key=lambda x: x["familia"]):
        if f["familia"] not in usadas:
            continue
        familia = _html.escape(f["familia"], quote=True)
        archivo = _html.escape(f["archivo"], quote=True)
        ruta = archivo if f.get("propia") else "{{ fonts_dir }}/" + archivo
        piezas.append(f"@font-face{{font-family:'{familia}';src:url('{ruta}');"
                      "font-display:block;}")
    return "\n  ".join(piezas)


def a_html(escena: dict[str, Any], contrato: dict[str, Any],
           *, fuentes: list[dict[str, Any]] | None = None) -> str:
    """Compila una escena v2 a HTML+CSS+Jinja. Determinista.

    Cumple lo mismo que `layout.a_html`: un único `.card` (lo fotografía
    `compose._screenshot_card`), solo variables declaradas o de sistema (lo
    valida `contrato.validar_html`) y el literal `window.__captionFitted` cuando
    hay auto-ajuste (lo espera `compose._screenshot_card`).
    """
    familias = {f["familia"] for f in fuentes} if fuentes else None
    validar(escena, contrato, familias=familias)

    lienzo = escena["lienzo"]
    ancho, alto = lienzo["w"], lienzo["h"]
    colores = (escena.get("tokens") or {}).get("colores") or {}
    fuera = _ocultas(escena["capas"])
    capas = sorted((c for c in escena["capas"]
                    if c["id"] not in fuera and c["tipo"] != "group"),
                   key=lambda c: (c.get("z", 0), c["id"]))
    cuerpo = "\n    ".join(_PINTORES[c["tipo"]](c, colores) for c in capas)
    script = "\n  " + _layout._SCRIPT_AUTO if any(
        c["tipo"] == "text" and c.get("auto") for c in capas) else ""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  {_font_faces(capas, fuentes)}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:{ancho}px; height:{alto}px; }}
  .card {{ width:{ancho}px; height:{alto}px; background:{_fondo_css(lienzo["fondo"], colores)};
          position:relative; overflow:hidden; }}
  .capa {{ position:absolute; }}
</style>
</head>
<body>
  <div class="card">
    {cuerpo}
  </div>{script}
</body>
</html>"""
