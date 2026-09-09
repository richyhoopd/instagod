"""El diseño visual de una plantilla: capas con posición absoluta.

`layout_json` es la fuente de verdad de un diseño; el `html` de la DB es un
artefacto derivado que sale de `a_html()`. Este módulo es puro —ni DB ni
disco— para poder validar en milisegundos lo que devuelva un LLM.

Las medidas son píxeles enteros sobre el lienzo REAL (1080x1350 o 1080x1920).
El editor del portal muestra el lienzo a escala, pero guarda píxeles reales:
si guardara los del navegador, cambiar el ancho de la pantalla movería los
diseños ya publicados.
"""
from __future__ import annotations

import re
from typing import Any

from .contrato import ASPECTOS, CAMPOS_BASE, ContratoInvalido, variables_declaradas

LIENZO = ASPECTOS
TIPOS_CAPA: tuple[str, ...] = ("texto", "imagen", "caja")
# 40 capas ya es un diseño barroco. El tope ataja un LLM en bucle antes de
# que Chromium tenga que pintar mil divs.
MAX_CAPAS = 40
MAX_LITERAL = 500

ALINEACIONES = ("izq", "centro", "der")
VERTICALES = ("arriba", "centro", "abajo")
AJUSTES = ("cover", "contain")
ANCLAJES = ("center", "center top", "center bottom", "left", "left top",
            "left bottom", "right", "right top", "right bottom")
PESOS = tuple(range(100, 1000, 100))

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_ARCHIVO = re.compile(r"^[A-Za-z0-9._-]{1,80}$")


def _color(valor: Any, donde: str) -> None:
    if valor == "marca":
        return
    if not isinstance(valor, str) or not _HEX.match(valor):
        raise ContratoInvalido(
            f"{donde}: el color debe ser #rrggbb o la palabra 'marca', llegó {valor!r}")


def _entero(capa: dict[str, Any], clave: str, minimo: int, maximo: int) -> int:
    valor = capa.get(clave)
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ContratoInvalido(
            f"capa '{capa.get('id')}': la medida '{clave}' debe ser un número entero")
    if not minimo <= valor <= maximo:
        raise ContratoInvalido(
            f"capa '{capa.get('id')}': la medida '{clave}' está fuera de rango "
            f"({valor}, se esperaba entre {minimo} y {maximo})")
    return valor


def _numero(capa: dict[str, Any], clave: str, minimo: float, maximo: float,
            defecto: float) -> float:
    valor = capa.get(clave, defecto)
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ContratoInvalido(f"capa '{capa.get('id')}': '{clave}' debe ser un número")
    if not minimo <= valor <= maximo:
        raise ContratoInvalido(
            f"capa '{capa.get('id')}': '{clave}' está fuera de rango ({valor})")
    return float(valor)


def _uno_de(capa: dict[str, Any], clave: str, opciones: tuple,
            defecto: Any) -> Any:
    valor = capa.get(clave, defecto)
    if valor not in opciones:
        raise ContratoInvalido(
            f"capa '{capa.get('id')}': '{clave}' debe ser uno de {list(opciones)}, "
            f"llegó {valor!r}")
    return valor


def _validar_texto(capa: dict[str, Any], declaradas: set[str],
                   familias: set[str] | None) -> None:
    tiene_campo = bool(capa.get("campo"))
    tiene_literal = capa.get("texto") is not None
    if tiene_campo == tiene_literal:
        raise ContratoInvalido(
            f"capa '{capa['id']}': hay que decir qué texto va aquí — o un dato del "
            "diseño o un texto fijo, pero no los dos ni ninguno")
    if tiene_campo and capa["campo"] not in declaradas:
        raise ContratoInvalido(
            f"capa '{capa['id']}': el dato '{capa['campo']}' no está en el diseño")
    if tiene_literal:
        literal = capa["texto"]
        if not isinstance(literal, str) or len(literal) > MAX_LITERAL:
            raise ContratoInvalido(
                f"capa '{capa['id']}': el texto fijo debe ser texto de hasta "
                f"{MAX_LITERAL} caracteres")
        if capa.get("resaltar"):
            raise ContratoInvalido(
                f"capa '{capa['id']}': el resaltado solo aplica a datos del diseño, "
                "no a un texto fijo")
    fuente = capa.get("fuente")
    if not isinstance(fuente, str) or not fuente.strip():
        raise ContratoInvalido(f"capa '{capa['id']}': falta la tipografía")
    if familias is not None and fuente not in familias:
        raise ContratoInvalido(
            f"capa '{capa['id']}': la tipografía '{fuente}' no está en el catálogo "
            "de la marca")
    _entero(capa, "tam", 8, 400)
    if capa.get("peso", 400) not in PESOS:
        raise ContratoInvalido(f"capa '{capa['id']}': el grosor debe ser 100..900")
    _uno_de(capa, "alinear", ALINEACIONES, "centro")
    _uno_de(capa, "vertical", VERTICALES, "centro")
    _numero(capa, "interlinea", 0.8, 3.0, 1.2)
    _color(capa.get("color", "#000000"), f"capa '{capa['id']}'")


def _validar_imagen(capa: dict[str, Any], declaradas: set[str]) -> None:
    tiene_campo = bool(capa.get("campo"))
    tiene_archivo = bool(capa.get("archivo"))
    if tiene_campo == tiene_archivo:
        raise ContratoInvalido(
            f"capa '{capa['id']}': hay que decir de dónde sale la imagen — o de un "
            "dato del diseño o de un archivo de la marca, pero no los dos ni ninguno")
    if tiene_campo and capa["campo"] not in declaradas:
        raise ContratoInvalido(
            f"capa '{capa['id']}': el dato '{capa['campo']}' no está en el diseño")
    if tiene_archivo and not _ARCHIVO.match(str(capa["archivo"])):
        raise ContratoInvalido(
            f"capa '{capa['id']}': el archivo {capa['archivo']!r} no es un nombre válido")
    _uno_de(capa, "ajuste", AJUSTES, "cover")
    _uno_de(capa, "anclaje", ANCLAJES, "center")
    _entero({**capa, "radio": capa.get("radio", 0)}, "radio", 0, 2000)


def validar(layout: dict[str, Any], contrato: dict[str, Any],
            *, familias: set[str] | None = None) -> None:
    """Que el diseño se pueda compilar. Lanza ContratoInvalido con el porqué.

    `familias` es el catálogo tipográfico de la marca. Si va en None no se
    valida la tipografía: sirve para los tests puros y para validar un diseño
    fuera del contexto de una marca.
    """
    if not isinstance(layout, dict):
        raise ContratoInvalido("el diseño debe ser un objeto")
    if layout.get("v") != 1:
        raise ContratoInvalido(f"versión de diseño desconocida: {layout.get('v')!r}")

    lienzo = layout.get("lienzo") or {}
    _color(lienzo.get("fondo", "#ffffff"), "el fondo del diseño")

    guias = layout.get("guias") or {}
    for clave, tope in (("cols", 48), ("filas", 64), ("iman", 64)):
        valor = guias.get(clave, 12)
        if (isinstance(valor, bool) or not isinstance(valor, int)
                or not 0 <= valor <= tope):
            raise ContratoInvalido(f"la rejilla tiene un valor raro en '{clave}'")

    capas = layout.get("capas")
    if not isinstance(capas, list) or not capas:
        raise ContratoInvalido(
            "el diseño está vacío: hay que poner al menos una capa")
    if len(capas) > MAX_CAPAS:
        raise ContratoInvalido(
            f"el diseño tiene demasiadas capas ({len(capas)}, tope {MAX_CAPAS})")

    declaradas = variables_declaradas(contrato) | set(CAMPOS_BASE)
    vistos: set[str] = set()
    for capa in capas:
        if not isinstance(capa, dict):
            raise ContratoInvalido("cada capa debe ser un objeto")
        cid = capa.get("id")
        if not isinstance(cid, str) or not _ID.match(cid):
            raise ContratoInvalido(
                f"el nombre de capa {cid!r} no sirve: minúsculas, números, guiones, "
                "empezando por letra")
        if cid in vistos:
            raise ContratoInvalido(f"el nombre de capa '{cid}' está repetido")
        vistos.add(cid)

        tipo = capa.get("tipo")
        if tipo not in TIPOS_CAPA:
            raise ContratoInvalido(
                f"capa '{cid}': tipo {tipo!r} desconocido, se esperaba uno de "
                f"{list(TIPOS_CAPA)}")

        _entero(capa, "x", -2000, 4000)
        _entero(capa, "y", -2000, 4000)
        _entero(capa, "w", 1, 4000)
        _entero(capa, "h", 1, 4000)
        _entero({**capa, "z": capa.get("z", 0)}, "z", 0, 999)
        _numero(capa, "rot", -180, 180, 0)
        _numero(capa, "opacidad", 0, 1, 1)

        if tipo == "texto":
            _validar_texto(capa, declaradas, familias)
        elif tipo == "imagen":
            _validar_imagen(capa, declaradas)
        else:
            _color(capa.get("color", "#000000"), f"capa '{cid}'")
            _entero({**capa, "radio": capa.get("radio", 0)}, "radio", 0, 2000)


def vacio(aspecto: str) -> dict[str, Any]:
    """Un diseño en blanco: fondo blanco, la foto de fondo y el titular encima."""
    ancho, alto = LIENZO[aspecto]
    return {
        "v": 1,
        "lienzo": {"fondo": "#ffffff"},
        "guias": {"cols": 12, "filas": 15, "iman": 8},
        "capas": [
            {"id": "fondo", "tipo": "imagen", "x": 0, "y": 0, "w": ancho, "h": alto,
             "z": 1, "campo": "imagen", "ajuste": "cover", "anclaje": "center",
             "radio": 0, "rot": 0, "opacidad": 1},
            {"id": "titular", "tipo": "texto",
             "x": 80, "y": int(alto * 0.6), "w": ancho - 160, "h": int(alto * 0.25),
             "z": 2, "campo": "titular", "fuente": "Poppins", "tam": 64, "peso": 700,
             "color": "#ffffff", "alinear": "centro", "vertical": "centro",
             "interlinea": 1.15, "mayusculas": False, "auto": True, "resaltar": False,
             "rot": 0, "opacidad": 1},
        ],
    }
