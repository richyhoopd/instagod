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

import html as _html
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
# La tipografía la puede escribir un LLM (Tarea 7): sin esta forma, `fuente`
# se cuela sin escapar dentro de un atributo `style="..."` en `a_html`.
_FUENTE = re.compile(r"^[A-Za-z0-9 ._-]{1,60}$")


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
    if not _FUENTE.match(fuente):
        raise ContratoInvalido(
            f"capa '{capa['id']}': la tipografía {fuente!r} tiene caracteres no permitidos")
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
             "z": 2, "campo": "titular", "fuente": "Poppins-Bold", "tam": 64, "peso": 700,
             "color": "#ffffff", "alinear": "centro", "vertical": "centro",
             "interlinea": 1.15, "mayusculas": False, "auto": True, "resaltar": False,
             "rot": 0, "opacidad": 1},
        ],
    }


# ---------------------------------------------------------------------------
# Compilador: capas -> HTML+CSS+Jinja
# ---------------------------------------------------------------------------

_JUSTIFY = {"izq": "flex-start", "centro": "center", "der": "flex-end"}
_ALIGN = {"arriba": "flex-start", "centro": "center", "abajo": "flex-end"}
_TEXTALIGN = {"izq": "left", "centro": "center", "der": "right"}

# El auto-ajuste achica el texto hasta que cabe. `window.__captionFitted` NO es
# decorativo: `src/compose.py:185` busca ese literal en el HTML para decidir si
# espera al ajuste antes de la foto. Si cambias el nombre, Chromium dispara el
# screenshot a media letra.
_SCRIPT_AUTO = """<script>
function ajustarTextos(){
  for (const el of document.querySelectorAll('[data-fit]')) {
    const caja = el.parentElement;
    let tam = parseFloat(getComputedStyle(el).fontSize);
    const minimo = Math.max(12, Math.round(tam * 0.4));
    while ((el.scrollHeight > caja.clientHeight || el.scrollWidth > caja.clientWidth)
           && tam > minimo) {
      tam -= 1; el.style.fontSize = tam + 'px';
    }
  }
  window.__captionFitted = true;
}
document.fonts.ready.then(() => requestAnimationFrame(
  () => requestAnimationFrame(ajustarTextos)));
</script>"""


def _css_color(valor: Any) -> str:
    """'marca' se resuelve en tiempo de render; el hex se queda literal."""
    return "{{ color_marca }}" if valor == "marca" else str(valor)


def _fuente_de(capa: dict[str, Any]) -> str:
    return str(capa.get("fuente") or "")


def _font_faces(diseno: dict[str, Any], fuentes: list[dict[str, Any]] | None) -> str:
    """Solo las tipografías que el diseño usa de verdad.

    Emitir el catálogo entero engorda el HTML y hace que Chromium cargue
    archivos que nadie pide. `fonts_dir` lo inyecta el render, así que la ruta
    sale como variable Jinja y el diseño no depende de dónde esté instalado.
    """
    if not fuentes:
        return ""
    usadas = {_fuente_de(c) for c in diseno["capas"] if c.get("tipo") == "texto"}
    piezas = []
    for f in sorted(fuentes, key=lambda x: x["familia"]):
        if f["familia"] not in usadas:
            continue
        familia = _html.escape(f["familia"], quote=True)
        archivo = _html.escape(f["archivo"], quote=True)
        ruta = archivo if f.get("propia") else "{{ fonts_dir }}/" + archivo
        piezas.append(
            f"@font-face{{font-family:'{familia}';src:url('{ruta}');"
            "font-display:block;}")
    return "\n  ".join(piezas)


def _caja_css(capa: dict[str, Any]) -> str:
    """El posicionamiento común a las tres clases de capa."""
    partes = [
        "position:absolute",
        f"left:{capa['x']}px", f"top:{capa['y']}px",
        f"width:{capa['w']}px", f"height:{capa['h']}px",
        f"z-index:{capa.get('z', 0)}",
    ]
    rot = capa.get("rot", 0) or 0
    if rot:
        partes.append(f"transform:rotate({rot:g}deg)")
    opac = capa.get("opacidad", 1)
    if opac != 1:
        partes.append(f"opacity:{opac:g}")
    radio = capa.get("radio", 0) or 0
    if radio:
        partes.append(f"border-radius:{radio}px;overflow:hidden")
    return ";".join(partes)


def _capa_texto(capa: dict[str, Any]) -> str:
    if capa.get("campo"):
        contenido = ("{{ %s|resaltar }}" if capa.get("resaltar") else "{{ %s }}") % capa["campo"]
    else:
        contenido = _html.escape(capa["texto"], quote=False)

    caja = [_caja_css(capa), "display:flex",
            f"justify-content:{_JUSTIFY[capa.get('alinear', 'centro')]}",
            f"align-items:{_ALIGN[capa.get('vertical', 'centro')]}",
            "overflow:hidden"]
    texto = [
        f"font-family:'{_html.escape(capa['fuente'], quote=True)}',sans-serif",
        f"font-size:{capa['tam']}px",
        f"font-weight:{capa.get('peso', 400)}",
        f"color:{_css_color(capa.get('color', '#000000'))}",
        f"line-height:{capa.get('interlinea', 1.2):g}",
        f"text-align:{_TEXTALIGN[capa.get('alinear', 'centro')]}",
        "width:100%",
    ]
    if capa.get("mayusculas"):
        texto.append("text-transform:uppercase")
    fit = " data-fit" if capa.get("auto") else ""
    return (f'<div id="capa-{capa["id"]}" class="capa" style="{";".join(caja)}">'
            f'<div{fit} style="{";".join(texto)}">{contenido}</div></div>')


def _capa_imagen(capa: dict[str, Any]) -> str:
    if capa.get("campo"):
        src = "{{ %s }}" % capa["campo"]
    else:
        src = "{{ fotos_dir }}/" + str(capa["archivo"])
    css = [_caja_css(capa),
           f"background-image:url('{src}')",
           f"background-size:{capa.get('ajuste', 'cover')}",
           f"background-position:{capa.get('anclaje', 'center')}",
           "background-repeat:no-repeat"]
    return f'<div id="capa-{capa["id"]}" class="capa" style="{";".join(css)}"></div>'


def _capa_caja(capa: dict[str, Any]) -> str:
    css = [_caja_css(capa), f"background:{_css_color(capa.get('color', '#000000'))}"]
    return f'<div id="capa-{capa["id"]}" class="capa" style="{";".join(css)}"></div>'


_PINTORES = {"texto": _capa_texto, "imagen": _capa_imagen, "caja": _capa_caja}


def a_html(layout: dict[str, Any], contrato: dict[str, Any],
           *, fuentes: list[dict[str, Any]] | None = None) -> str:
    """Compila un diseño visual a HTML+CSS+Jinja. Determinista.

    El resultado tiene que cumplir tres cosas que exigen otros módulos:
    un único nodo `.card` (lo fotografía `compose._screenshot_card`), solo
    variables declaradas en el contrato (lo valida `contrato.validar_html`) y
    el literal `window.__captionFitted` cuando hay auto-ajuste (lo espera
    `compose._screenshot_card`).
    """
    familias = {f["familia"] for f in fuentes} if fuentes else None
    validar(layout, contrato, familias=familias)

    ancho, alto = LIENZO[contrato["aspecto"]]
    capas = sorted(layout["capas"], key=lambda c: (c.get("z", 0), c["id"]))
    cuerpo = "\n    ".join(_PINTORES[c["tipo"]](c) for c in capas)
    fondo = _css_color((layout.get("lienzo") or {}).get("fondo", "#ffffff"))
    script = "\n  " + _SCRIPT_AUTO if any(
        c.get("tipo") == "texto" and c.get("auto") for c in capas) else ""

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  {_font_faces(layout, fuentes)}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:{ancho}px; height:{alto}px; }}
  .card {{ width:{ancho}px; height:{alto}px; background:{fondo};
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
