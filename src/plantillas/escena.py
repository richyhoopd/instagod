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
                  familias: set[str] | None) -> None:
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
    padre_de: dict[str, str] = {}
    for capa in capas:
        _validar_capa(capa, colores, declaradas, familias)
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
