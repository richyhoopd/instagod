"""Contrato híbrido de una plantilla: núcleo garantizado + extras declarados.

El mismo contrato sirve para dos cosas: es el schema con el que se renderiza
y es el schema que se le pide al LLM al generar el contenido. Una sola fuente
de verdad — si la plantilla declara tres bullets, el generador pide tres.
"""
from __future__ import annotations

import json
import re
from typing import Any

import jinja2
from jinja2 import meta as jinja_meta

from . import filtros

# Toda plantilla los recibe siempre: ninguna puede quedarse sin logo o handle.
CAMPOS_BASE: tuple[str, ...] = ("titular", "imagen", "handle", "logo", "color_marca")
# Los inyecta el motor de render, no el contrato ni el LLM.
# `fotos_dir` es la carpeta de fotos y stickers de la marca: los diseños
# visuales apuntan ahí por nombre de archivo, nunca por ruta absoluta, para
# que el mismo diseño renderice igual en la laptop y en la VM.
CAMPOS_SISTEMA: tuple[str, ...] = ("fonts_dir", "fotos_dir", "assets_dir")
TIPOS: tuple[str, ...] = ("texto", "texto_largo", "lista", "numero",
                          "imagen", "booleano")
ASPECTOS: dict[str, tuple[int, int]] = {"4:5": (1080, 1350), "9:16": (1080, 1920)}

# Un LLM descarrilado puede devolver cientos de kilobytes. Las cuatro
# plantillas de gdlscene rondan los 3 KB, así que 60 KB es holgado y ataja
# lo absurdo antes de guardarlo en la DB y mandarlo a Chromium.
MAX_HTML = 60_000

# No son tipografías que haya que tener instaladas.
_GENERICAS = {"sans-serif", "serif", "monospace", "cursive", "fantasy",
              "system-ui", "inherit", "initial", "unset"}

_FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}\n]+)", re.I)


_FONT_FACE = re.compile(r"@font-face\s*\{([^}]*)\}", re.I)
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
# `card` como palabra completa dentro del atributo class, sin importar qué
# otras clases lo acompañen: el motor usa `page.locator(".card")`
# (src/compose.py:191), que encuentra `class="foo card"` igual que
# `class="card"`. Exigir el valor exacto rechazaría de más un HTML legítimo
# con clases combinadas.
_ATRIBUTO_CLASS = re.compile(r"""class\s*=\s*["']([^"']*)["']""")


def _tiene_card(html: str) -> bool:
    """`card` como clase entera, no como prefijo: `class="card-top"` no vale
    porque `page.locator(".card")` tampoco lo encuentra."""
    return any("card" in v.split() for v in _ATRIBUTO_CLASS.findall(html))


def _sin_jinja(html: str) -> str:
    r"""Sustituye las expresiones Jinja por un token sin llaves.

    Sin esto, cualquier regex de bloque CSS (`\{[^}]*\}`) se corta en el
    `}}` de un `{{ fonts_dir }}` y parsea la plantilla a medias.
    """
    return _JINJA.sub("JINJAVAR", html or "")
_FF_FAMILY = re.compile(r"font-family\s*:\s*([^;}\n]+)", re.I)
_FF_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)", re.I)


def _familias_autodeclaradas(html: str) -> set[str]:
    """Familias que la propia plantilla define con @font-face."""
    nombres: set[str] = set()
    for bloque in _FONT_FACE.findall(_sin_jinja(html)):
        for decl in _FF_FAMILY.findall(bloque):
            nombres.add(decl.strip().strip("'\""))
    return nombres


def validar_fuentes(html: str, familias: set[str],
                    *, archivos: set[str] | None = None) -> list[str]:
    """Que el HTML no dependa de tipografías que la marca no tiene.

    OJO: hay DOS espacios de nombres distintos y confundirlos rechaza las
    plantillas que ya se publican. Las claves del catálogo son nombres de
    archivo (`Tinos-Regular`, `Poppins-SemiBold`), mientras que las plantillas
    de gdlscene declaran su propio `@font-face` con familias CSS cortas
    (`Tinos`, `Poppins`, `Anton`) apuntando a esos archivos. Una plantilla
    PUEDE declarar la familia que quiera; lo que no puede es apuntar a un
    archivo que no existe o, peor, a la red.

    Por eso se valida en dos ejes:
    - toda familia USADA está en el catálogo, autodeclarada, o es genérica;
    - todo `src:url()` de un `@font-face` apunta a un archivo del catálogo,
      nunca a http(s). Un webfont externo hace que el render dependa del DNS:
      el día que falle, se publica un post con la tipografía equivocada, y ya
      publicado no se arregla.
    """
    errores: list[str] = []
    limpio = _sin_jinja(html)
    autodeclaradas = _familias_autodeclaradas(html)
    permitidas = familias | autodeclaradas | _GENERICAS

    for bloque in _FONT_FACE.findall(limpio):
        for url in _FF_URL.findall(bloque):
            limpia = url.strip()
            if limpia.startswith(("http://", "https://", "//")):
                errores.append(
                    f"la tipografía se carga de la red ({limpia[:60]}): "
                    "solo se permiten las del catálogo de la marca")
                continue
            if archivos is not None:
                nombre = limpia.rsplit("/", 1)[-1].split("?")[0].replace("JINJAVAR", "")
                if nombre and nombre not in archivos:
                    errores.append(
                        f"el archivo de tipografía '{nombre}' no está en el "
                        "catálogo de la marca")

    sin_font_faces = _FONT_FACE.sub("", limpio)
    # Solo se exige la PRIMERA familia de cada pila. Así funcionan las pilas
    # CSS: la primera es la intención y las siguientes son degradación
    # elegante. Las plantillas de gdlscene escriben
    # `font-family:'Tinos','Times New Roman',serif` — pedir que 'Times New
    # Roman' esté en el catálogo rechazaría los diseños que ya se publican.
    for declaracion in _FONT_FAMILY.findall(sin_font_faces):
        piezas = [b.strip().strip("'\"") for b in declaracion.split(",")]
        piezas = [x for x in piezas if x]
        if not piezas:
            continue
        principal = piezas[0]
        if principal.lower() in _GENERICAS:
            continue
        if principal not in permitidas:
            errores.append(
                f"la tipografía '{principal}' no está disponible para esta marca")
    return errores



class ContratoInvalido(ValueError):
    """El contrato o el HTML no cumplen el formato esperado."""


def dimensiones(aspecto: str) -> tuple[int, int]:
    if aspecto not in ASPECTOS:
        raise ContratoInvalido(f"aspecto desconocido: {aspecto!r}")
    return ASPECTOS[aspecto]


def validar(contrato: dict[str, Any]) -> None:
    if not isinstance(contrato, dict):
        raise ContratoInvalido("el contrato debe ser un objeto")

    aspecto = contrato.get("aspecto")
    if aspecto not in ASPECTOS:
        raise ContratoInvalido(f"aspecto desconocido: {aspecto!r}")

    base = contrato.get("base")
    if not isinstance(base, list) or set(CAMPOS_BASE) - set(base):
        faltan = sorted(set(CAMPOS_BASE) - set(base or []))
        raise ContratoInvalido(f"faltan campos base: {faltan}")

    extras = contrato.get("extras", [])
    if not isinstance(extras, list):
        raise ContratoInvalido("extras debe ser una lista")

    vistos: set[str] = set()
    for extra in extras:
        if not isinstance(extra, dict):
            raise ContratoInvalido("cada extra debe ser un objeto")
        eid = extra.get("id")
        if not eid or not isinstance(eid, str):
            raise ContratoInvalido("cada extra necesita un id de texto")
        if eid in CAMPOS_BASE:
            raise ContratoInvalido(f"el extra {eid!r} pisa un campo base")
        if eid in CAMPOS_SISTEMA:
            raise ContratoInvalido(f"el extra {eid!r} pisa una variable de sistema")
        if eid in vistos:
            raise ContratoInvalido(f"extra duplicado: {eid!r}")
        vistos.add(eid)

        tipo = extra.get("tipo")
        if tipo not in TIPOS:
            raise ContratoInvalido(f"tipo desconocido en {eid!r}: {tipo!r}")

        if tipo == "lista":
            minimo, maximo = extra.get("min", 1), extra.get("max", 10)
            if not isinstance(minimo, int) or not isinstance(maximo, int):
                raise ContratoInvalido(f"min y max de {eid!r} deben ser enteros")
            if minimo < 1 or minimo > maximo:
                raise ContratoInvalido(
                    f"min inválido en {eid!r}: min={minimo} max={maximo}")


def variables_declaradas(contrato: dict[str, Any]) -> set[str]:
    extras = contrato.get("extras", []) or []
    return set(contrato.get("base", [])) | {e["id"] for e in extras if "id" in e}


def validar_html(html: str, contrato: dict[str, Any]) -> None:
    """Toda {{ variable }} del HTML debe estar declarada o ser de sistema."""
    if len(html or "") > MAX_HTML:
        raise ContratoInvalido(
            f"el HTML es demasiado grande ({len(html)} caracteres, tope {MAX_HTML})")

    # El motor fotografía el nodo `.card` (src/compose.py:191). Sin él, el
    # render no falla: devuelve un PNG vacío, que es mucho peor.
    if not _tiene_card(html or ""):
        raise ContratoInvalido("el diseño no tiene el marco de la imagen")

    env = filtros.entorno()
    try:
        ast = env.parse(html)
        # `Environment.parse()` no detecta filtros desconocidos (arma el AST
        # igual); solo se descubren al compilar. `compile()` los valida sin
        # necesitar contexto de render, y por eso vive en el mismo try: un
        # filtro inventado (por ejemplo por un LLM en H3) debe volverse
        # ContratoInvalido, no una TemplateAssertionError sin capturar.
        env.compile(html)
    except jinja2.TemplateSyntaxError as exc:
        raise ContratoInvalido(f"HTML inválido para Jinja: {exc.message}") from exc

    usadas = jinja_meta.find_undeclared_variables(ast)
    permitidas = variables_declaradas(contrato) | set(CAMPOS_SISTEMA)
    sobrantes = sorted(usadas - permitidas)
    if sobrantes:
        raise ContratoInvalido(
            f"el HTML usa variables no declaradas en el contrato: {sobrantes}")


# Los inyecta el motor de render desde la marca, no el generador de contenido.
_INYECTADOS: tuple[str, ...] = ("imagen", "handle", "logo", "color_marca")


def _error_tipo(eid: str, valor: Any, tipo: str, extra: dict[str, Any]) -> str | None:
    if tipo in ("texto", "texto_largo", "imagen"):
        if not isinstance(valor, str) or not valor.strip():
            return f"{eid}: se esperaba texto no vacío"
    elif tipo == "numero":
        # bool es subclase de int en Python: hay que excluirlo a mano.
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            return f"{eid}: se esperaba un número, no texto"
    elif tipo == "booleano":
        if not isinstance(valor, bool):
            return f"{eid}: se esperaba true o false"
    elif tipo == "lista":
        if not isinstance(valor, list):
            return f"{eid}: se esperaba una lista"
        if any(not isinstance(x, str) or not x.strip() for x in valor):
            return f"{eid}: todos los elementos deben ser texto no vacío"
        minimo, maximo = extra.get("min", 1), extra.get("max", 10)
        if not minimo <= len(valor) <= maximo:
            return f"{eid}: se esperaban entre {minimo} y {maximo} elementos, llegaron {len(valor)}"
    return None


def validar_campos(campos: dict[str, Any], contrato: dict[str, Any]) -> list[str]:
    """Valida VALORES contra el contrato. Devuelve errores; [] = válido.

    No lanza a propósito: la lista se le devuelve al LLM para que se
    autocorrija en el siguiente intento, igual que slideshow_script.
    """
    errores: list[str] = []
    extras = {e["id"]: e for e in contrato.get("extras", []) or [] if "id" in e}

    titular = campos.get("titular")
    if not isinstance(titular, str) or not titular.strip():
        errores.append("titular: es obligatorio y no puede ir vacío")

    for eid, extra in extras.items():
        if eid not in campos or campos[eid] is None:
            if not extra.get("opcional"):
                errores.append(f"{eid}: falta y no es opcional")
            continue
        err = _error_tipo(eid, campos[eid], extra.get("tipo", "texto"), extra)
        if err:
            errores.append(err)

    conocidos = set(extras) | {"titular"} | set(_INYECTADOS)
    for clave in campos:
        if clave not in conocidos:
            errores.append(f"{clave}: campo desconocido, no está en el contrato")

    return errores


def contrato_de_json(crudo: str | None) -> dict[str, Any]:
    """`json.loads` tolerante: `{}` si el string es None, está roto o no es un objeto.

    Gemelo de `plantillas.contrato_de` (que recibe una FILA de DB); este recibe
    directamente el string de `contrato_json`, para no repetir el try/except
    en cada módulo que necesita el contrato ya parseado (p. ej. `render.py`).
    """
    if not crudo:
        return {}
    try:
        valor = json.loads(crudo)
    except (json.JSONDecodeError, TypeError):
        return {}
    return valor if isinstance(valor, dict) else {}
