# Editor v2 · Plan 1: escena v2 en el backend

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-10-06-editor-escena-v2-design.md` (commit e87942f), §1 y §7.
**Índice y contrato entre planes:** `docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md`.

**Goal:** que el backend entienda la escena JSON v2: la valida, convierte los diseños v1 al leerlos, la compila a HTML para la vista previa y el render, la reacomoda entre 4:5, 1:1 y 9:16, y la API la acepta y la devuelve. Además: formato 1:1 de punta a punta, `GET /templates?estado=todas` y el endpoint que sirve `assets/`.

**Architecture:** un módulo nuevo, `src/plantillas/escena.py`, puro (sin DB ni red), con el contrato del índice. `layout.py` v1 no se toca. El servicio `src/plantillas/__init__.py` gana tres funciones que despachan por versión (`compilar`, `validar_diseno`, `escena_de`); el router, el handler `template.preview` y `_validado` pasan por ellas. `layout_de` sigue devolviendo el JSON crudo porque `template.disenar` (plan 4 lo reemplaza) todavía espera v1. El CHECK de `brand_templates.aspecto` se ensancha con el rebuild de tabla de siempre.

**Tech Stack:** Python 3 (`.venv`), Jinja2, FastAPI, SQLite, Playwright/Chromium (render), pytest, Pillow 12.2 (solo en la prueba lenta).

---

## Global Constraints

- Rama `feat/editor-v2`, worktree `/Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2`. Todos los comandos se corren desde esa raíz.
- Pytest: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest`. Lint: `/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/`.
- TDD estricto: prueba que falla → código mínimo → verde → commit. Un commit por task. **Nada de push ni deploy a la VM.**
- No se toca `src/plantillas/layout.py`, `src/plantillas/disenador.py` ni `src/image_sources.py`. Los diseños v1 y el slideshow siguen funcionando igual.
- No se leen `*.local.md` ni valores de `.env`.
- Comentarios y mensajes de error en español, en el tono de `layout.py`: dicen qué está mal y en qué capa.
- Nombres del contrato (índice §«Plan 1 → todos») exactos: `FORMATOS`, `ASPECTO_DE_FORMATO`, `TIPOS`, `EscenaInvalida`, `validar`, `v1_a_v2`, `normalizar`, `a_html`, `reformatear`.
- Antes de cada commit: la suite completa en verde (`pytest -q -m "not lento"`) y ruff limpio. Si algo ajeno ya estaba rojo antes de empezar, se anota en el mensaje del commit; no se arregla aquí.

## Review Focus

1. **Seguridad del compilador** (`escena.a_html`): todo lo que entra a un atributo `style="..."` o a `url('...')` pasa por regex de lista blanca. Revisar `_GRADIENTE`, `_CSS_LIBRE` (filter), `_SRC`, colores y que el texto fijo no pueda colar `{{`/`{%`.
2. **Compatibilidad v1**: `layout_de` sigue crudo; `template.disenar` y `disenador.py` siguen recibiendo v1; los tests existentes de `test_disenos_web.py`, `test_plantillas.py`, `test_layout_*.py` siguen verdes (solo cambia la aserción de `revert` por la forma v2).
3. **Rebuild de `brand_templates`**: no pierde filas ni versiones, la FK de `template_versions` sobrevive, el índice se recrea, `foreign_key_check` antes del COMMIT.
4. **Endpoint `files/assets`**: no lee fuera de `data/brands/<slug>/assets/` (ni con `..` ni con symlink), lista blanca de extensiones, SVG con CSP `sandbox`.
5. **Paridad v1 ↔ v2**: el mismo diseño v1 y su conversión producen el mismo PNG (prueba lenta, Task 4).

## Decisiones de este plan que extienden el spec (revisar)

| # | Decisión | Por qué |
|---|---|---|
| D1 | `EscenaInvalida` hereda de `contrato.ContratoInvalido` (que es `ValueError`) | Los `except ContratoInvalido` del router y del servicio la convierten en 422 sin cambios. Cumple el contrato (`ValueError`) |
| D2 | `src` acepta `assets/<archivo>` **y** `fotos/<archivo>` | `fotos/` conserva el `archivo` de las imágenes v1 al convertir. `assets/` → `{{ assets_dir }}`, `fotos/` → `{{ fotos_dir }}` |
| D3 | Variable de sistema nueva `assets_dir` (`contrato.CAMPOS_SISTEMA`, `render.contexto`) | El HTML no puede llevar rutas absolutas del servidor |
| D4 | Claves extra en `estilo` de texto: `verticalAlign` (top/center/bottom), `textTransform` (none/uppercase). En la capa: `auto` (auto-ajuste) y `resaltar` | Sin ellas, `v1_a_v2` pierde información y el PNG cambia |
| D5 | Imagen: `estilo.objectPosition` (los valores de `layout.ANCLAJES`) | Equivale al `anclaje` v1 de imagen; el `anclaje` v2 ya es top/center/bottom |
| D6 | `shape`: `forma` (rect/ellipse) + `estilo{fill, radius, borderColor, borderWidth}`. `svg`: `src` a un `.svg`, se pinta como `background-image` (nunca SVG en línea). `video`: `<video muted playsinline preload="auto">` + `poster` opcional | El spec no define sus campos |
| D7 | `group` es lógico: no pinta nada; lleva `hijos` (ids); un grupo `oculta` oculta a sus hijos; se permiten grupos anidados sin ciclos; cada capa en a lo más un grupo. `bloqueada` solo importa al editor | El spec no define su semántica |
| D8 | `MAX_CAPAS = 80` (v1: 40), texto fijo hasta 1000 caracteres (v1: 500), se permite una escena sin capas | Diseños tipo Daisies pasan de 40 capas; el editor puede quedar vacío a mitad de trabajo |
| D9 | Con `campo`, el `texto` de la capa no se pinta (el editor lo usa de muestra). `spans` solo en texto fijo | Los offsets de `spans` no aplican a un dato que cambia en cada post |
| D10 | `escena_de(fila)` nuevo (normaliza a v2); `layout_de(fila)` queda crudo | `src/jobs/handlers.py:466` (`template.disenar`) espera v1 |
| D11 | El spec dice «`layout.py` gana `v1_a_v2()`»; el índice lo pone en `escena.py` | Manda el índice. `layout.py` no se toca |
| D12 | Al guardar (PATCH) una escena v2 sin `contrato`, el `aspecto` del contrato se toma de `lienzo.formato` | Así el cambio de formato del editor (plan 2) se guarda sin mandar el contrato completo |

---

### Task 1: `escena.py` — constantes y `validar`

**Files:**
- Create: `src/plantillas/escena.py`
- Test: `tests/test_escena_esquema.py` (nuevo)

**Interfaces:**
```python
FORMATOS: dict[str, tuple[int, int]]
ASPECTO_DE_FORMATO: dict[str, str]
FORMATO_DE_ASPECTO: dict[str, str]          # inverso, uso interno y del router
TIPOS: tuple[str, ...]
ANCLAJES = ("top", "center", "bottom")
MAX_CAPAS = 80
MAX_TEXTO = 1000
class EscenaInvalida(ContratoInvalido)
def validar(escena: dict, contrato: dict, *, familias: set[str] | None = None) -> None
```

- [ ] **Step 1: Escribir la prueba que falla**

`tests/test_escena_esquema.py`:

```python
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
```

- [ ] **Step 2: Correrla y ver que falla**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_esquema.py -q
```
Esperado: `ModuleNotFoundError: No module named 'src.plantillas.escena'`.

- [ ] **Step 3: Implementar**

`src/plantillas/escena.py`:

```python
"""Escena v2: el diseño por coordenadas del editor tipo Figma.

Es lo que guarda `brand_templates.layout_json` a partir del editor v2 (spec
2026-10-06 §1). Este módulo es puro: valida, convierte desde el layout v1,
compila a HTML+CSS+Jinja y reacomoda entre formatos. No toca DB ni red.

Todo lo que acaba dentro de un `style="..."` o de un `url('...')` pasa antes
por una lista blanca: la escena la escriben el editor y el chat de IA, y
ninguno de los dos es de fiar.
"""
from __future__ import annotations

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
        if _HEX.match(valor) or _RGBA.match(valor):
            return
        m = _TOKEN.match(valor)
        if m:
            if m.group(1) == "marca" or m.group(1) in colores:
                return
            raise EscenaInvalida(f"{donde}: el token de color '{m.group(1)}' no existe")
    raise EscenaInvalida(
        f"{donde}: color inválido {valor!r} (usa #rrggbb, rgba(...) o token:<nombre>)")


def _css_libre(valor: Any, regex: re.Pattern, donde: str, clave: str) -> None:
    if (not isinstance(valor, str) or not regex.match(valor)
            or "url(" in valor.lower()):
        raise EscenaInvalida(f"{donde}: '{clave}' tiene un valor no permitido")


def _src(valor: Any, donde: str, clave: str = "src") -> None:
    if not isinstance(valor, str) or not _SRC.match(valor):
        raise EscenaInvalida(
            f"{donde}: '{clave}' debe ser assets/<archivo> o fotos/<archivo>")


def _familia(valor: Any, familias: set[str] | None, donde: str) -> None:
    if not isinstance(valor, str) or not _FUENTE.match(valor):
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
    if tracking is not None and (not isinstance(tracking, str) or not _TRACKING.match(tracking)):
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
    if not isinstance(mascara, str) or not _MASCARA.match(mascara):
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
        if campo not in declaradas:
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
    if formato not in FORMATOS:
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
        if not isinstance(nombre, str) or not _ID.match(nombre) or nombre == "marca":
            raise EscenaInvalida(f"token de color con nombre inválido: {nombre!r}")
        if not isinstance(valor, str) or not (_HEX.match(valor) or _RGBA.match(valor)):
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
        if not isinstance(cid, str) or not _ID.match(cid):
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
```

Nota: el caso `hijos=["g_marca"]` de la prueba (un grupo que se contiene a sí mismo) cae en `hijo == capa["id"]` con el mensaje «'hijos' apunta…».

- [ ] **Step 4: Correr y ver verde**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_esquema.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
```
Esperado: todo pasa. Si algún `match=` no coincide, se ajusta el **mensaje** del código para que diga lo que la prueba pide; no se afloja la prueba.

- [ ] **Step 5: Suite completa y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
git add src/plantillas/escena.py tests/test_escena_esquema.py
git commit -m "$(cat <<'EOF'
escena v2: esquema y validación

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `v1_a_v2` y `normalizar`

**Files:**
- Modify: `src/plantillas/escena.py`
- Test: `tests/test_escena_v1_a_v2.py` (nuevo)

**Interfaces:**
```python
def v1_a_v2(layout: dict, aspecto: str) -> dict
def normalizar(layout: dict | None, aspecto: str) -> dict   # siempre v2; copia, nunca muta
```

- [ ] **Step 1: Prueba que falla**

`tests/test_escena_v1_a_v2.py`:

```python
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
```

- [ ] **Step 2: Correr y ver que falla**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_v1_a_v2.py -q
```
Esperado: `AttributeError: module 'src.plantillas.escena' has no attribute 'v1_a_v2'`.

- [ ] **Step 3: Implementar** (agregar a `src/plantillas/escena.py`, después de `validar`; agregar `import copy` arriba)

```python
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


def v1_a_v2(layout: dict[str, Any], aspecto: str) -> dict[str, Any]:
    """Convierte un layout v1 (`layout.py`) a escena v2 sin mutar la entrada.

    No valida: el v1 ya pasó por `layout.validar` al guardarse. Quien necesite
    la garantía llama a `validar` sobre el resultado.
    """
    if aspecto not in FORMATO_DE_ASPECTO:
        raise EscenaInvalida(f"aspecto desconocido {aspecto!r}")
    formato = FORMATO_DE_ASPECTO[aspecto]
    ancho, alto = FORMATOS[formato]
    lienzo_v1 = layout.get("lienzo") or {}
    escena = {
        "v": 2,
        "lienzo": {"w": ancho, "h": alto, "formato": formato,
                   "fondo": {"tipo": "color",
                             "valor": _color_v1(lienzo_v1.get("fondo", "#ffffff"))}},
        "tokens": {"colores": {}},
        "capas": [_DE_V1[c["tipo"]](c, _comunes_v1(c, ancho, alto))
                  for c in layout.get("capas") or [] if c.get("tipo") in _DE_V1],
    }
    if layout.get("guias"):
        escena["guias"] = copy.deepcopy(layout["guias"])
    return escena


def normalizar(layout: dict[str, Any] | None, aspecto: str) -> dict[str, Any]:
    """Cualquier cosa guardada en layout_json -> escena v2 (copia nueva).

    None arranca el lienzo en blanco de siempre (`layout.vacio`) ya convertido.
    """
    if layout is None:
        if aspecto not in _layout.LIENZO:
            raise EscenaInvalida(f"aspecto desconocido {aspecto!r}")
        return v1_a_v2(_layout.vacio(aspecto), aspecto)
    version = layout.get("v") if isinstance(layout, dict) else None
    if version == 1:
        return v1_a_v2(layout, aspecto)
    if version == 2:
        return copy.deepcopy(layout)
    raise EscenaInvalida(f"versión de diseño desconocida: {version!r}")
```

Nota: el `fondo` del lienzo v1 en `vacio` es `"#ffffff"`; en v2 queda `{"tipo": "color", "valor": "#ffffff"}`. La prueba `test_mapeo_campo_por_campo` lo pone en `"marca"` a propósito.

- [ ] **Step 4: Verde**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_v1_a_v2.py tests/test_escena_esquema.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
```
Esperado: pasan; el caso `1:1` sale `skipped` hasta el Task 6.

- [ ] **Step 5: Commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
git add src/plantillas/escena.py tests/test_escena_v1_a_v2.py
git commit -m "$(cat <<'EOF'
escena v2: v1_a_v2 y normalizar

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: variable de sistema `assets_dir`

**Files:**
- Modify: `src/plantillas/contrato.py` (`CAMPOS_SISTEMA`)
- Modify: `src/plantillas/render.py` (`contexto`)
- Test: `tests/test_plantillas_render.py` (agregar una prueba), `tests/test_contrato_plantilla.py` (agregar una prueba)

**Interfaces:**
```python
CAMPOS_SISTEMA = ("fonts_dir", "fotos_dir", "assets_dir")
def contexto(marca, campos, *, fonts_dir=None, fotos_dir=None, assets_dir=None) -> dict
```

- [ ] **Step 1: Pruebas que fallan**

Al final de `tests/test_contrato_plantilla.py`:

```python
def test_assets_dir_es_variable_de_sistema():
    from src.plantillas import contrato as _c
    ct = {"aspecto": "4:5", "base": list(_c.CAMPOS_BASE), "extras": []}
    _c.validar_html(
        "<html><body><div class='card' "
        "style=\"background:url('{{ assets_dir }}/a.png')\"></div></body></html>", ct)
```

Al final de `tests/test_plantillas_render.py`:

```python
def test_contexto_trae_assets_dir():
    from src import marcas as _marcas
    from src.image_sources import BRANDS_DIR
    from src.plantillas import render as _render
    m = _marcas.cargar("gdlscene")
    ctx = _render.contexto(m, {"titular": "x"})
    assert ctx["assets_dir"] == (BRANDS_DIR / m.slug / "assets").as_uri()
    assert _render.contexto(m, {}, assets_dir="file:///tmp/a")["assets_dir"] == "file:///tmp/a"
```

Antes de escribirla, confirmar en `tests/test_plantillas_render.py` cómo obtienen la marca las otras pruebas (fixture o `marcas.cargar`) y usar exactamente lo mismo; si `marcas.cargar` no existe con ese nombre, se usa la fixture del archivo.

- [ ] **Step 2: Ver que fallan**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_contrato_plantilla.py tests/test_plantillas_render.py -q -k "assets_dir"
```
Esperado: `ContratoInvalido` por variable no declarada `assets_dir` y `KeyError: 'assets_dir'`.

- [ ] **Step 3: Implementar**

`src/plantillas/contrato.py`:

```python
CAMPOS_SISTEMA = ("fonts_dir", "fotos_dir", "assets_dir")
```

`src/plantillas/render.py`, en `contexto` (firma y una línea nueva después de `fotos_dir`):

```python
def contexto(marca, campos: dict[str, Any], *,
             fonts_dir: str | None = None, fotos_dir: str | None = None,
             assets_dir: str | None = None) -> dict[str, Any]:
    ...
    ctx["fotos_dir"] = fotos_dir or (BRANDS_DIR / marca.slug / "fotos").as_uri()
    # Biblioteca de la marca (plan 3): la escena v2 pide sus imágenes como assets/<archivo>.
    ctx["assets_dir"] = assets_dir or (BRANDS_DIR / marca.slug / "assets").as_uri()
    return ctx
```
(Respetar el resto del cuerpo tal cual; solo cambia la firma y se agrega la línea.)

- [ ] **Step 4: Verde y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add src/plantillas/contrato.py src/plantillas/render.py tests/test_contrato_plantilla.py tests/test_plantillas_render.py
git commit -m "$(cat <<'EOF'
plantillas: variable de sistema assets_dir

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `a_html` v2

**Files:**
- Modify: `src/plantillas/escena.py`
- Create: `tests/test_escena_html.py`, `tests/fixtures/escena/basica.html` (snapshot generado en el Step 4)

**Interfaces:**
```python
def a_html(escena: dict, contrato: dict, *, fuentes: list[dict] | None = None) -> str
```
Garantías (mismas que `layout.a_html`): un solo `.card`; solo variables declaradas o de sistema; el literal `window.__captionFitted` si hay texto con `auto`; determinista.

- [ ] **Step 1: Prueba que falla**

`tests/test_escena_html.py`:

```python
"""Compilador de escena v2 a HTML+CSS+Jinja."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from src.plantillas import contrato, layout
from src.plantillas import escena as E
from src.plantillas.filtros import entorno

from tests.test_escena_esquema import CONTRATO, _escena

FUENTES = [{"familia": "Poppins-Bold", "archivo": "Poppins-Bold.ttf", "propia": False},
           {"familia": "Tinos", "archivo": "Tinos-Bold.ttf", "propia": False}]
SNAPSHOT = Path(__file__).parent / "fixtures" / "escena" / "basica.html"


def test_cumple_lo_que_exigen_contrato_y_compose():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    contrato.validar_html(html, CONTRATO)
    assert contrato.validar_fuentes(html, {"Poppins-Bold", "Tinos"},
                                    archivos={"Poppins-Bold.ttf", "Tinos-Bold.ttf"}) == []
    assert html.count('class="card"') == 1
    assert html == E.a_html(_escena(), CONTRATO, fuentes=FUENTES)       # determinista


def test_snapshot():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert html == SNAPSHOT.read_text(encoding="utf-8")


def test_tokens_spans_y_texto_fijo():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "color:#1C1A23" in html                                  # token:ink
    assert '<span style="color:#F5C842">' in html                    # span token:accent
    assert "white-space:pre-line" in html                            # \n del texto fijo
    assert "text-wrap:balance" in html
    assert "letter-spacing:-0.03em" in html


def test_imagen_con_campo_y_src_de_respaldo():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "{{ imagen or (assets_dir ~ '/abc123.png') }}" in html
    assert "border-radius:48px" in html
    assert "drop-shadow(0 24px 48px rgba(61,53,128,.35))" in html


def test_marca_shape_svg():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "background:{{ color_marca }}" in html                    # fill token:marca
    assert "url('{{ assets_dir }}/logo.svg')" in html
    assert "<svg" not in html


def test_ocultas_y_grupos_no_se_pintan():
    esc = _escena()
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert "capa-c_clip" not in html                                 # oculta
    assert "capa-g_marca" not in html                                # group no pinta
    esc["capas"][5]["oculta"] = True
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert "capa-c_logo" not in html and "capa-c_caja" not in html   # hijos del grupo oculto


def test_video_visible():
    esc = _escena()
    esc["capas"][4]["oculta"] = False
    esc["capas"][4]["poster"] = "assets/clip.jpg"
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    assert ('<video src="{{ assets_dir }}/clip.mp4" poster="{{ assets_dir }}/clip.jpg" '
            'muted playsinline preload="auto"') in html
    assert "border-radius:50%" in html


def test_fondos():
    esc = _escena()
    esc["lienzo"]["fondo"] = {"tipo": "imagen", "valor": "fotos/f.jpg"}
    assert "url('{{ fotos_dir }}/f.jpg')" in E.a_html(esc, CONTRATO)
    esc["lienzo"]["fondo"] = {"tipo": "gradiente", "valor": "linear-gradient(#000000, #ffffff)"}
    assert "background:linear-gradient(#000000, #ffffff)" in E.a_html(esc, CONTRATO)


def test_auto_ajuste_y_resaltar():
    v2 = E.v1_a_v2(layout.vacio("4:5"), "4:5")
    ct = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
    html = E.a_html(v2, ct, fuentes=FUENTES)
    assert "window.__captionFitted" in html and "data-fit" in html
    v2["capas"][1]["auto"] = False
    v2["capas"][1]["resaltar"] = True
    html = E.a_html(v2, ct, fuentes=FUENTES)
    assert "window.__captionFitted" not in html
    assert "{{ titular|resaltar }}" in html


def test_solo_las_fuentes_usadas():
    html = E.a_html(_escena(), CONTRATO, fuentes=FUENTES)
    assert "Poppins-Bold.ttf" in html and "Tinos-Bold.ttf" not in html


def test_valida_antes_de_compilar():
    esc = _escena()
    esc["capas"][0]["estilo"]["fontFamily"] = "Papyrus"
    with pytest.raises(E.EscenaInvalida, match="tipografía"):
        E.a_html(esc, CONTRATO, fuentes=FUENTES)


def test_el_html_renderiza_con_jinja():
    esc = copy.deepcopy(_escena())
    html = E.a_html(esc, CONTRATO, fuentes=FUENTES)
    salida = entorno().from_string(html).render(
        titular="Hola", imagen="", handle="@x", logo="", color_marca="#ff0000",
        badge="", fonts_dir="file:///f", fotos_dir="file:///p", assets_dir="file:///a")
    assert "file:///a/abc123.png" in salida                           # imagen vacía -> respaldo
    assert "background:#ff0000" in salida
```

Crear `tests/fixtures/escena/` (vacío por ahora). `tests/` no es paquete (no hay `__init__.py`); los imports entre pruebas siguen la convención del repo, `from tests.<modulo> import …` (como `tests/test_daemon_recarga.py:8`).

- [ ] **Step 2: Ver que falla**

```bash
mkdir -p tests/fixtures/escena
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_html.py -q
```
Esperado: `AttributeError: ... has no attribute 'a_html'`.

- [ ] **Step 3: Implementar** (agregar a `src/plantillas/escena.py`; agregar `import html as _html` arriba)

```python
# ---------------------------------------------------------------------------
# Compilador: escena -> HTML+CSS+Jinja
# ---------------------------------------------------------------------------

_JUSTIFY = {"left": "flex-start", "center": "center", "right": "flex-end",
            "justify": "flex-start"}
_ALIGN = {"top": "flex-start", "center": "center", "bottom": "flex-end"}


def _resolver(color: str, colores: dict[str, str]) -> str:
    """token:marca se resuelve al renderizar; los demás tokens, aquí."""
    m = _TOKEN.match(color)
    if not m:
        return color
    return "{{ color_marca }}" if m.group(1) == "marca" else colores[m.group(1)]


def _url(src: str) -> str:
    """assets/x -> {{ assets_dir }}/x ; fotos/x -> {{ fotos_dir }}/x."""
    carpeta, archivo = src.split("/", 1)
    return "{{ %s_dir }}/%s" % (carpeta, archivo)


def _origen(capa: dict[str, Any]) -> str:
    """El dato del post si viene; si viene vacío, el archivo fijo de la capa."""
    campo, src = capa.get("campo"), capa.get("src")
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
    if capa.get("campo"):
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
```

- [ ] **Step 4: Generar el snapshot, revisarlo a mano y ver verde**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from pathlib import Path
from src.plantillas import escena as E
from tests.test_escena_esquema import CONTRATO, _escena
from tests.test_escena_html import FUENTES
Path('tests/fixtures/escena/basica.html').write_text(E.a_html(_escena(), CONTRATO, fuentes=FUENTES), encoding='utf-8')
"
cat tests/fixtures/escena/basica.html
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_html.py -q
```
Revisar el `cat`: un `@font-face` (Poppins-Bold), cuatro `div.capa` en orden z (`c_caja` 2, `c_foto` 5, `c_titular` 10, `c_logo` 20; `c_clip` oculta y `g_marca` no generan div), sin `<svg`, sin `;` sueltos dentro de valores. Si algo se ve mal, se corrige el código y se regenera; el snapshot no se edita a mano.

- [ ] **Step 5: Prueba lenta de paridad v1 ↔ v2** (agregar al final de `tests/test_escena_html.py`)

```python
@pytest.mark.lento
def test_paridad_de_pixeles_v1_y_v2(tmp_path):
    """El mismo diseño v1 y su conversión salen iguales de Chromium (<=1 % de píxeles)."""
    from PIL import Image, ImageChops

    from src import compose

    foto = tmp_path / "foto.png"
    Image.new("RGB", (1080, 1350), (40, 90, 160)).save(foto)
    ct = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
    v1 = layout.vacio("4:5")
    v1["capas"].append({"id": "caja", "tipo": "caja", "x": 0, "y": 1200, "w": 1080,
                        "h": 150, "z": 0, "color": "marca", "radio": 24, "rot": 0,
                        "opacidad": 1})
    ctx = dict(titular="Hola Guadalajara, esto es una prueba", imagen=foto.as_uri(),
               handle="@x", logo="", color_marca="#ff3366",
               fonts_dir=compose.FONTS_DIR.as_uri(), fotos_dir=tmp_path.as_uri(),
               assets_dir=tmp_path.as_uri())
    salidas = []
    for nombre, html in (("v1", layout.a_html(v1, ct, fuentes=FUENTES)),
                         ("v2", E.a_html(E.v1_a_v2(v1, "4:5"), ct, fuentes=FUENTES))):
        destino = tmp_path / f"{nombre}.png"
        compose.render_html(entorno().from_string(html).render(**ctx), aspecto="4:5",
                            out_path=destino)
        salidas.append(Image.open(destino).convert("RGB"))
    diff = ImageChops.difference(*salidas)
    distintos = sum(1 for p in diff.getdata() if max(p) > 8)
    assert distintos / (1080 * 1350) <= 0.01
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_html.py -q -m lento
```
Esperado: pasa. Si no hay Chromium de Playwright instalado en la Mac, la prueba falla al lanzar el navegador: anotarlo en el commit como «paridad no verificada» y seguir; no se marca `skip` en el código.

- [ ] **Step 6: Commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add src/plantillas/escena.py tests/test_escena_html.py tests/fixtures/escena/basica.html
git commit -m "$(cat <<'EOF'
escena v2: compilador a_html

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `reformatear`

**Files:**
- Modify: `src/plantillas/escena.py`
- Test: `tests/test_escena_reformatear.py` (nuevo)

**Interfaces:**
```python
def reformatear(escena: dict, formato: str) -> dict   # copia; no valida contra contrato
```
Regla (spec §2, algoritmo `P.Y` de `hombres-regalale-daisies/gen.py`): `dy = alto_nuevo − alto_viejo`; `top` conserva `y`, `bottom` suma `dy`, `center` suma `round(dy/2)`. Lo que cubre el lienzo entero se estira al lienzo nuevo. Los grupos recalculan su caja con la de sus hijos.

- [ ] **Step 1: Prueba que falla**

`tests/test_escena_reformatear.py`:

```python
"""Reacomodo de capas entre 4:5, 1:1 y 9:16 por su anclaje."""
from __future__ import annotations

import copy

import pytest

from src.plantillas import escena as E

from tests.test_escena_esquema import _escena


def _por_id(esc: dict) -> dict:
    return {c["id"]: c for c in esc["capas"]}


def test_4x5_a_9x16():
    esc = _escena()
    original = copy.deepcopy(esc)
    nueva = E.reformatear(esc, "9x16")
    assert esc == original                                  # no muta
    assert nueva["lienzo"]["w"] == 1080 and nueva["lienzo"]["h"] == 1920
    assert nueva["lienzo"]["formato"] == "9x16"
    c = _por_id(nueva)
    assert c["c_titular"]["y"] == 196                       # top
    assert c["c_foto"]["y"] == 600 + 570                    # bottom: dy = 570
    assert c["c_clip"]["y"] == 0 + 285                      # center: dy/2
    assert c["c_caja"]["y"] == 1200 + 570


def test_a_sangre_se_estira():
    esc = _escena()
    esc["capas"][1].update(x=0, y=0, w=1080, h=1350, anclaje="center")
    c = _por_id(E.reformatear(esc, "1x1"))
    assert (c["c_foto"]["x"], c["c_foto"]["y"], c["c_foto"]["w"], c["c_foto"]["h"]) == (
        0, 0, 1080, 1080)


def test_el_grupo_recalcula_su_caja():
    c = _por_id(E.reformatear(_escena(), "9x16"))
    logo, caja, grupo = c["c_logo"], c["c_caja"], c["g_marca"]
    assert grupo["x"] == min(logo["x"], caja["x"])
    assert grupo["y"] == min(logo["y"], caja["y"])
    assert grupo["y"] + grupo["h"] == max(logo["y"] + logo["h"], caja["y"] + caja["h"])


def test_ida_y_vuelta_conserva_posiciones():
    esc = _escena()
    vuelta = E.reformatear(E.reformatear(esc, "9x16"), "4x5")
    assert [(c["x"], c["y"]) for c in vuelta["capas"] if c["tipo"] != "group"] == [
        (c["x"], c["y"]) for c in esc["capas"] if c["tipo"] != "group"]


def test_el_resultado_es_valido_para_su_aspecto():
    from tests.test_escena_esquema import CONTRATO
    E.validar(E.reformatear(_escena(), "9x16"), {**CONTRATO, "aspecto": "9:16"})


def test_formato_desconocido():
    with pytest.raises(E.EscenaInvalida):
        E.reformatear(_escena(), "16x9")
```

- [ ] **Step 2: Ver que falla**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_escena_reformatear.py -q
```
Esperado: `AttributeError: ... 'reformatear'`.

- [ ] **Step 3: Implementar** (agregar a `src/plantillas/escena.py`)

```python
# ---------------------------------------------------------------------------
# Reacomodo entre formatos
# ---------------------------------------------------------------------------

def _a_sangre(capa: dict[str, Any], ancho: int, alto: int) -> bool:
    return (capa["x"] <= 0 and capa["y"] <= 0
            and capa["x"] + capa["w"] >= ancho and capa["y"] + capa["h"] >= alto)


def _caja_de_grupo(gid: str, por_id: dict[str, dict[str, Any]], hechos: set[str]) -> None:
    """La caja de un grupo es la que envuelve a sus hijos (primero los grupos hijos)."""
    if gid in hechos:
        return
    grupo = por_id[gid]
    for h in grupo["hijos"]:
        if por_id[h]["tipo"] == "group":
            _caja_de_grupo(h, por_id, hechos)
    hijos = [por_id[h] for h in grupo["hijos"]]
    x0 = min(h["x"] for h in hijos)
    y0 = min(h["y"] for h in hijos)
    x1 = max(h["x"] + h["w"] for h in hijos)
    y1 = max(h["y"] + h["h"] for h in hijos)
    grupo.update(x=x0, y=y0, w=x1 - x0, h=y1 - y0)
    hechos.add(gid)


def reformatear(escena: dict[str, Any], formato: str) -> dict[str, Any]:
    """La misma escena en otro formato, moviendo cada capa según su `anclaje`."""
    if formato not in FORMATOS:
        raise EscenaInvalida(f"formato desconocido {formato!r} (4x5, 1x1 o 9x16)")
    nueva = copy.deepcopy(escena)
    viejo_w, viejo_h = nueva["lienzo"]["w"], nueva["lienzo"]["h"]
    ancho, alto = FORMATOS[formato]
    dy = alto - viejo_h
    for capa in nueva["capas"]:
        if capa["tipo"] == "group":
            continue
        if _a_sangre(capa, viejo_w, viejo_h):
            capa.update(x=0, y=0, w=ancho, h=alto)
            continue
        anclaje = capa.get("anclaje", "top")
        if anclaje == "bottom":
            capa["y"] = capa["y"] + dy
        elif anclaje == "center":
            capa["y"] = capa["y"] + round(dy / 2)
    por_id = {c["id"]: c for c in nueva["capas"]}
    hechos: set[str] = set()
    for capa in nueva["capas"]:
        if capa["tipo"] == "group":
            _caja_de_grupo(capa["id"], por_id, hechos)
    nueva["lienzo"].update(w=ancho, h=alto, formato=formato)
    return nueva
```

Nota: la ida y vuelta es exacta salvo en `center` con `dy` impar (todos los `dy` posibles entre 1350, 1080 y 1920 son pares: 270, 570, 840) y en capas a sangre, que vuelven estiradas al lienzo (la prueba no las incluye).

- [ ] **Step 4: Verde y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add src/plantillas/escena.py tests/test_escena_reformatear.py
git commit -m "$(cat <<'EOF'
escena v2: reformatear por anclaje

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: formato 1:1 de punta a punta

**Files:**
- Modify: `src/plantillas/contrato.py:27` (`ASPECTOS`)
- Modify: `src/compose.py:29` (`ASPECTOS`)
- Modify: `src/schema.sql:534` (CHECK de `brand_templates.aspecto`)
- Modify: `src/db.py` (nueva `_migrar_check_aspecto_templates`, llamada en `init_db` después de `_migrar_check_tipo_queue(cx)`)
- Modify: `api/routers/plantillas.py` (patrones `aspecto` de `DisenoNuevo`, `VistaPrevia`, `PedirDiseno`)
- Modify: `tests/test_disenador_llm.py:175` (usaba `"1:1"` como aspecto inválido)
- Test: `tests/test_db_migracion_aspecto_templates.py` (nuevo), `tests/test_compose_desde_db.py` (agregar)

**Interfaces:**
```python
contrato.ASPECTOS == {"4:5": (1080, 1350), "9:16": (1080, 1920), "1:1": (1080, 1080)}
compose.ASPECTOS   # mismo contenido
def _migrar_check_aspecto_templates(cx: sqlite3.Connection) -> None
```
Efecto colateral buscado: `layout.LIENZO` es el mismo objeto que `contrato.ASPECTOS`, así que el v1 y `layout.vacio("1:1")` también aceptan 1:1.

- [ ] **Step 1: Pruebas que fallan**

`tests/test_db_migracion_aspecto_templates.py`:

```python
"""Ensanchar CHECK(aspecto) de brand_templates a '1:1' sin perder diseños ni versiones."""
from __future__ import annotations

import sqlite3

import pytest

from src import db

_NUEVO = "CHECK (aspecto IN ('4:5','9:16','1:1')),"
_VIEJO = "CHECK (aspecto IN ('4:5','9:16')),"
_SCHEMA_REAL = db.SCHEMA_PATH.read_text(encoding="utf-8")
assert _NUEVO in _SCHEMA_REAL, "cambió el CHECK de brand_templates en schema.sql"
_OLD_SCHEMA = _SCHEMA_REAL.replace(_NUEVO, _VIEJO)


def _db_vieja(path) -> None:
    cx = sqlite3.connect(path)
    cx.execute("PRAGMA foreign_keys = ON")
    cx.executescript(_OLD_SCHEMA)
    cx.execute("INSERT OR IGNORE INTO accounts (id, slug, ig_handle, nombre, ciudad) "
               "VALUES (1,'gdlscene','gdlscene','La Escena GDL','Guadalajara')")
    cx.execute("INSERT INTO brand_templates (id, account_id, slug, nombre, aspecto, "
               "contrato_json, html, layout_json, estado) VALUES "
               "(7, 1, 'onion', 'Onion', '9:16', '{}', '<div class=\"card\"></div>', "
               "'{\"v\": 1}', 'activa')")
    cx.execute("INSERT INTO template_versions (template_id, version, html, contrato_json) "
               "VALUES (7, 1, '<div class=\"card\"></div>', '{}')")
    with pytest.raises(sqlite3.IntegrityError):
        cx.execute("INSERT INTO brand_templates (account_id, slug, nombre, aspecto, "
                   "contrato_json, html) VALUES (1, 'q', 'Q', '1:1', '{}', 'x')")
    cx.commit()
    cx.close()


def test_migra_el_check_sin_perder_nada(tmp_path):
    path = tmp_path / "vieja.db"
    _db_vieja(path)
    cx = db.connect(path)
    db.init_db(cx)

    fila = db.rows(cx, "SELECT id, slug, aspecto, layout_json, estado FROM brand_templates")
    assert fila == [{"id": 7, "slug": "onion", "aspecto": "9:16",
                     "layout_json": '{"v": 1}', "estado": "activa"}]
    assert db.rows(cx, "SELECT template_id, version FROM template_versions") == [
        {"template_id": 7, "version": 1}]

    nuevo = db.insert(cx, "brand_templates", account_id=1, slug="cuadrado", nombre="C",
                      aspecto="1:1", contrato_json="{}", html="x")
    assert db.get(cx, "brand_templates", nuevo)["aspecto"] == "1:1"
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_templates", account_id=1, slug="ancho", nombre="A",
                  aspecto="16:9", contrato_json="{}", html="x")

    # El índice volvió y la cascada de versiones sigue viva.
    indices = {r["name"] for r in cx.execute("PRAGMA index_list(brand_templates)")}
    assert "idx_templates_cuenta" in indices
    cx.execute("DELETE FROM brand_templates WHERE id = 7")
    assert db.rows(cx, "SELECT * FROM template_versions") == []


def test_es_idempotente(tmp_path):
    path = tmp_path / "vieja.db"
    _db_vieja(path)
    cx = db.connect(path)
    db.init_db(cx)
    db.init_db(cx)
    assert db.rows(cx, "SELECT count(*) AS n FROM brand_templates") == [{"n": 1}]
```

Al final de `tests/test_compose_desde_db.py`:

```python
def test_render_html_acepta_1_1(monkeypatch, tmp_path):
    capturado = {}

    def falso(html, **kw):
        capturado.update(kw)
        return kw.get("out_path")

    monkeypatch.setattr(compose, "_screenshot_card", falso)
    compose.render_html("<div class='card'></div>", aspecto="1:1", out_path=tmp_path / "x.png")
    assert (capturado["ancho"], capturado["alto"]) == (1080, 1080)
```

Al final de `tests/test_contrato_plantilla.py`:

```python
def test_contrato_acepta_1_1():
    from src.plantillas import contrato as _c
    _c.validar({"aspecto": "1:1", "base": list(_c.CAMPOS_BASE), "extras": []})
    assert _c.dimensiones("1:1") == (1080, 1080)
```

En `tests/test_disenador_llm.py:175` cambiar `"aspecto": "1:1"` por `"aspecto": "16:9"` y, en el docstring de esa prueba, «no es uno de los dos que existen» por «no es uno de los que existen».

Antes de agregar, confirmar con `sed -n 1,35p tests/test_compose_desde_db.py` que `compose` ya está importado ahí y que `_screenshot_card` se llama con argumentos por nombre (`compose.py:213` en adelante). Si se llama posicional, el falso se escribe con la misma firma que el real.

- [ ] **Step 2: Ver que fallan**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_db_migracion_aspecto_templates.py tests/test_compose_desde_db.py tests/test_contrato_plantilla.py -q
```
Esperado: el `assert _NUEVO in _SCHEMA_REAL` revienta en colección; `ValueError` de aspecto en compose; `ContratoInvalido` en contrato.

- [ ] **Step 3: Implementar**

`src/plantillas/contrato.py:27`:
```python
ASPECTOS = {"4:5": (1080, 1350), "9:16": (1080, 1920), "1:1": (1080, 1080)}
```
(conservar el tipo anotado si la línea lo trae).

`src/compose.py:29`:
```python
ASPECTOS: dict[str, tuple[int, int]] = {"4:5": (WIDTH, HEIGHT), "9:16": (1080, 1920),
                                        "1:1": (1080, 1080)}
```

`src/schema.sql:534`:
```sql
    CHECK (aspecto IN ('4:5','9:16','1:1')),
```

`src/db.py`, después de `_migrar_check_tipo_queue`:

```python
# DDL de destino de brand_templates. Copia literal de src/schema.sql con el
# nombre _new: si cambia una columna allá, se cambia aquí también.
_BRAND_TEMPLATES_REBUILD_DDL = """
CREATE TABLE brand_templates_new (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    slug           TEXT    NOT NULL,
    nombre         TEXT    NOT NULL,
    descripcion    TEXT,
    aspecto        TEXT    NOT NULL DEFAULT '4:5',
    contrato_json  TEXT    NOT NULL,
    html           TEXT    NOT NULL,
    layout_json    TEXT,
    estado         TEXT    NOT NULL DEFAULT 'borrador',
    version_actual INTEGER NOT NULL DEFAULT 1,
    origen         TEXT    NOT NULL DEFAULT 'manual',
    creado_por     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now')),
    actualizado_en TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, slug),
    CHECK (aspecto IN ('4:5','9:16','1:1')),
    CHECK (estado  IN ('borrador','activa','archivada')),
    CHECK (origen  IN ('seed','llm','manual'))
)
"""
_BRAND_TEMPLATES_REBUILD_COLS = (
    "id", "account_id", "slug", "nombre", "descripcion", "aspecto", "contrato_json",
    "html", "layout_json", "estado", "version_actual", "origen", "creado_por",
    "creado_en", "actualizado_en",
)


def _migrar_check_aspecto_templates(cx: sqlite3.Connection) -> None:
    """Ensancha CHECK(aspecto) de brand_templates para aceptar '1:1'.

    Mismo procedimiento que `_migrar_check_tipo_queue` (sqlite.org, «Making
    Other Kinds Of Table Schema Changes»). Idempotente: si el DDL guardado ya
    trae '1:1' no hace nada. template_versions apunta a brand_templates por
    nombre, así que su FK sobrevive al DROP + RENAME.
    """
    row = cx.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='brand_templates'"
    ).fetchone()
    if row is None or "'1:1'" in row[0]:
        return

    viejas = {r["name"] for r in cx.execute("PRAGMA table_info(brand_templates)")}
    huerfanas = viejas - set(_BRAND_TEMPLATES_REBUILD_COLS)
    if huerfanas:
        raise RuntimeError(
            "_migrar_check_aspecto_templates no conoce estas columnas de "
            f"brand_templates: {sorted(huerfanas)}. Actualiza "
            "_BRAND_TEMPLATES_REBUILD_DDL y _BRAND_TEMPLATES_REBUILD_COLS antes de "
            "correr esta migración: el rebuild las tiraría en silencio.")
    col_list = ", ".join(c for c in _BRAND_TEMPLATES_REBUILD_COLS if c in viejas)

    cx.execute("PRAGMA foreign_keys=OFF")
    try:
        cx.execute("BEGIN")
        cx.execute(_BRAND_TEMPLATES_REBUILD_DDL)
        cx.execute(f"INSERT INTO brand_templates_new ({col_list}) "
                   f"SELECT {col_list} FROM brand_templates")
        cx.execute("DROP TABLE brand_templates")
        cx.execute("ALTER TABLE brand_templates_new RENAME TO brand_templates")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_templates_cuenta "
                   "ON brand_templates(account_id, estado)")
        violaciones = cx.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            raise RuntimeError(f"foreign_key_check falló tras el rebuild de "
                               f"brand_templates: {[tuple(v) for v in violaciones]}")
        cx.execute("COMMIT")
    except BaseException:
        try:
            cx.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise
    finally:
        cx.execute("PRAGMA foreign_keys=ON")
```

En `init_db`, justo después de `_migrar_check_tipo_queue(cx)`:
```python
    _migrar_check_aspecto_templates(cx)
```

`api/routers/plantillas.py`: en `DisenoNuevo`, `VistaPrevia` y `PedirDiseno`, `pattern="^(4:5|9:16)$"` → `pattern="^(4:5|1:1|9:16)$"`.

Antes de cerrar: `grep -rn "brand_templates" src/schema.sql` confirma que no hay triggers sobre `brand_templates` (a la fecha no hay); si aparecieran, se recrean dentro de la transacción igual que el índice.

- [ ] **Step 4: Verde**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_db_migracion_aspecto_templates.py tests/test_db_migracion_tipo_queue.py tests/test_compose_desde_db.py tests/test_contrato_plantilla.py tests/test_disenador_llm.py tests/test_escena_v1_a_v2.py -q
```
Esperado: pasan; el caso `1:1` de `test_el_vacio_v1_convertido_es_v2_valido` ya no sale `skipped`.

- [ ] **Step 5: Commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add src/plantillas/contrato.py src/compose.py src/schema.sql src/db.py api/routers/plantillas.py tests/test_db_migracion_aspecto_templates.py tests/test_compose_desde_db.py tests/test_contrato_plantilla.py tests/test_disenador_llm.py
git commit -m "$(cat <<'EOF'
plantillas: formato 1:1 (contrato, compose, CHECK de brand_templates)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: despacho por versión en el servicio y en `template.preview`

**Files:**
- Modify: `src/plantillas/__init__.py` (`compilar`, `validar_diseno`, `escena_de`; `_validado` usa `compilar`)
- Modify: `src/jobs/handlers.py:413` (`template_preview` usa `plantillas.compilar`)
- Test: `tests/test_plantillas.py` (agregar), `tests/test_plantillas_render.py` o el archivo donde vivan las pruebas de `template_preview` (agregar)

**Interfaces:**
```python
# src/plantillas/__init__.py
def compilar(layout: dict, contrato: dict, *, fuentes: list[dict] | None = None) -> str
def validar_diseno(layout: dict, contrato: dict, *, familias: set[str] | None = None) -> None
def escena_de(fila) -> dict | None     # None si es legacy (sin layout)
# layout_de(fila) NO cambia: sigue devolviendo el JSON crudo (v1 o v2).
```

- [ ] **Step 1: Pruebas que fallan**

Al final de `tests/test_plantillas.py`:

```python
def _ct_escena() -> dict:
    from src.plantillas import contrato as _c
    return {"aspecto": "4:5", "base": list(_c.CAMPOS_BASE), "extras": []}


def test_crear_y_versionar_con_escena_v2(cx):
    from src.plantillas import escena
    esc = escena.normalizar(None, "4:5")
    tid = plantillas.crear(cx, 1, "V2", "", _ct_escena(), layout=esc)
    fila = plantillas.obtener(cx, tid)
    assert plantillas.layout_de(fila)["v"] == 2
    assert 'class="card"' in fila["html"] and "capa-titular" in fila["html"]
    esc["capas"][1]["estilo"]["fontSize"] = 90
    plantillas.nueva_version(cx, tid, "", _ct_escena(), layout=esc)
    assert "font-size:90px" in plantillas.obtener(cx, tid)["html"]


def test_escena_v2_invalida_es_contrato_invalido(cx):
    from src.plantillas import escena
    esc = escena.normalizar(None, "4:5")
    esc["capas"][1]["estilo"]["fontFamily"] = "Papyrus"
    with pytest.raises(plantillas.ContratoInvalido, match="tipograf"):
        plantillas.crear(cx, 1, "Mala", "", _ct_escena(), layout=esc)


def test_escena_de_normaliza_y_layout_de_no(cx):
    from src.plantillas import layout as v1
    tid = plantillas.crear(cx, 1, "V1", "", _ct_escena(), layout=v1.vacio("4:5"))
    fila = plantillas.obtener(cx, tid)
    assert plantillas.layout_de(fila)["v"] == 1
    assert plantillas.escena_de(fila)["v"] == 2
    assert plantillas.escena_de(fila)["lienzo"]["formato"] == "4x5"


def test_escena_de_un_legacy_es_none(cx):
    tid = plantillas.crear(cx, 1, "Legacy", _HTML_MANUAL, _ct_escena())
    assert plantillas.escena_de(plantillas.obtener(cx, tid)) is None


def test_compilar_despacha_por_version():
    from src.plantillas import escena
    from src.plantillas import layout as v1
    ct = _ct_escena()
    assert plantillas.compilar(v1.vacio("4:5"), ct) == v1.a_html(v1.vacio("4:5"), ct)
    esc = escena.normalizar(None, "4:5")
    assert plantillas.compilar(esc, ct) == escena.a_html(esc, ct)
    with pytest.raises(plantillas.ContratoInvalido):
        plantillas.validar_diseno({"v": 3}, ct)
```

Antes de escribirlas, revisar en `tests/test_plantillas.py`: el nombre de la fixture de conexión (`cx`), si ya importa `pytest`, y cómo se llama la constante del HTML legacy escrito a mano. `_HTML_MANUAL` arriba es un nombre de ejemplo: se usa el que el archivo ya tenga; si no hay ninguna, se copia `_HTML_LEGACY` de `tests/test_disenos_web.py`.

Prueba del handler (en el archivo que ya prueba `template_preview`; ubicarlo con `grep -rln "template_preview" tests/`):

```python
def test_template_preview_acepta_escena_v2(cx, monkeypatch, tmp_path):
    from src.jobs import handlers
    from src.plantillas import escena
    capturado = {}

    def falso_render(cx_, marca, plantilla, campos, *, out_path):
        capturado["html"] = plantilla["html"]
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"png")
        return out_path

    monkeypatch.setattr(handlers.plantillas_render, "render", falso_render)
    ct = {"aspecto": "4:5", "base": list(contrato_mod.CAMPOS_BASE), "extras": []}
    job = _job(cx, "template.preview", 1,
               {"layout": escena.normalizar(None, "4:5"), "contrato": ct, "aspecto": "4:5"})
    resultado = handlers.template_preview(cx, job)
    assert resultado["url"].endswith(".png")
    assert "capa-titular" in capturado["html"]
```
Adaptar a lo que ya exista en ese archivo: el helper para crear el job (`_job` en `tests/test_disenador_llm.py`), el alias del módulo de contrato, cómo se redirige la carpeta de previews a `tmp_path` y la firma real de `plantillas_render.render` (verla en `src/plantillas/render.py`). Si no hay prueba previa de `template_preview`, esta va en `tests/test_disenador_llm.py`, que ya tiene `_job`.

- [ ] **Step 2: Ver que fallan**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_plantillas.py -q -k "escena or compilar"
```
Esperado: `ContratoInvalido: versión de diseño desconocida: 2` (de `layout.validar`) y `AttributeError` por `escena_de`/`compilar`.

- [ ] **Step 3: Implementar**

`src/plantillas/__init__.py`:

```python
from . import escena as _escena
```
(junto a los otros imports relativos)

```python
def _es_v2(layout_dict: Any) -> bool:
    return isinstance(layout_dict, dict) and layout_dict.get("v") == 2


def compilar(layout_dict: dict[str, Any], contrato_dict: dict[str, Any],
             *, fuentes: list[dict[str, Any]] | None = None) -> str:
    """HTML de un diseño con capas, sea v1 (layout.py) o v2 (escena.py)."""
    if _es_v2(layout_dict):
        return _escena.a_html(layout_dict, contrato_dict, fuentes=fuentes)
    return _layout.a_html(layout_dict, contrato_dict, fuentes=fuentes)


def validar_diseno(layout_dict: dict[str, Any], contrato_dict: dict[str, Any],
                   *, familias: set[str] | None = None) -> None:
    """Valida sin compilar, despachando por versión."""
    if _es_v2(layout_dict):
        _escena.validar(layout_dict, contrato_dict, familias=familias)
    else:
        _layout.validar(layout_dict, contrato_dict, familias=familias)
```

En `_validado`, la línea del layout:
```python
    if layout_dict is not None:
        html = compilar(layout_dict, contrato_dict, fuentes=fuentes)
```

Después de `layout_de`:
```python
def escena_de(fila: dict[str, Any]) -> dict[str, Any] | None:
    """El diseño de la fila como escena v2, o None si es legacy.

    `layout_de` sigue crudo a propósito: `template.disenar` (jobs/handlers.py)
    todavía trabaja en v1 hasta que el plan 4 lo reemplace.
    """
    crudo = layout_de(fila)
    if crudo is None:
        return None
    return _escena.normalizar(crudo, fila["aspecto"])
```

`src/jobs/handlers.py:413`:
```python
    html = plantillas.compilar(payload["layout"], contrato_dict, fuentes=fuentes)
```
Después correr ruff: si `layout` (import de la línea 41) queda sin uso en `handlers.py`, quitarlo de esa línea de import; si se usa en otro lado, se deja.

- [ ] **Step 4: Verde y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add src/plantillas/__init__.py src/jobs/handlers.py tests/
git commit -m "$(cat <<'EOF'
plantillas: despacho v1/v2 (compilar, validar_diseno, escena_de)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: la API acepta y devuelve v2; `estado=todas`

**Files:**
- Modify: `api/routers/plantillas.py`
- Modify: `tests/test_disenos_web.py` (una aserción cambia de forma; pruebas nuevas)

**Interfaces (HTTP):**
- `GET /brands/{slug}/templates?estado=todas` → todas las plantillas de la marca (sin parámetro sigue siendo solo `activa`).
- `GET|POST|PATCH /templates…` y `POST /templates/{tid}/revert/{n}`, `POST /templates/{tid}/duplicate`: el campo `layout` de la respuesta es **siempre escena v2** (o `null` en legacy).
- `POST /templates` sin `layout` crea con `escena.normalizar(None, aspecto)` (v2).
- `PATCH /templates/{tid}` y `POST /templates/preview` aceptan v1 y v2. En PATCH con v2 y sin `contrato`, el `aspecto` sale de `lienzo.formato` (D12).

- [ ] **Step 1: Pruebas**

En `tests/test_disenos_web.py`, la prueba `test_revertir_recupera_la_version_anterior` cambia su última línea (la respuesta ahora es v2):

```python
    assert r.json()["layout"]["capas"][1]["estilo"]["fontSize"] == 64
```

Pruebas nuevas al final del archivo:

```python
from src.plantillas import escena  # noqa: E402  (subirlo junto a los otros imports)


def test_crear_devuelve_escena_v2(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates",
                             json={"nombre": "N", "aspecto": "4:5"})
    assert r.status_code == 201
    assert r.json()["layout"]["v"] == 2
    assert r.json()["layout"]["lienzo"]["formato"] == "4x5"


def test_un_v1_guardado_se_devuelve_como_v2(cliente_manager, marca, cx):
    tid = plantillas.crear(cx, 1, "Viejo", "", _ct(), layout=layout.vacio("4:5"))
    r = cliente_manager.get(f"/brands/{marca}/templates/{tid}")
    assert r.json()["layout"]["v"] == 2
    assert plantillas.layout_de(plantillas.obtener(cx, tid))["v"] == 1   # BD intacta


def test_guardar_v2_y_cambiar_de_formato(cliente_manager, marca, cx):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "F", "aspecto": "4:5"}).json()["id"]
    esc = cliente_manager.get(f"/brands/{marca}/templates/{tid}").json()["layout"]
    esc = escena.reformatear(esc, "9x16")
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": esc})
    assert r.status_code == 200, r.text
    assert r.json()["aspecto"] == "9:16"
    assert r.json()["layout"]["lienzo"]["h"] == 1920
    assert plantillas.layout_de(plantillas.obtener(cx, tid))["v"] == 2


def test_guardar_v2_invalida_da_422(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "M", "aspecto": "4:5"}).json()["id"]
    esc = escena.normalizar(None, "4:5")
    esc["capas"][1]["estilo"]["fontFamily"] = "Papyrus"
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": esc})
    assert r.status_code == 422
    assert "tipograf" in r.json()["detail"].lower()


def test_crear_en_1_1(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates",
                             json={"nombre": "Cuadro", "aspecto": "1:1"})
    assert r.status_code == 201
    assert r.json()["aspecto"] == "1:1"
    assert r.json()["layout"]["lienzo"]["h"] == 1080


def test_vista_previa_acepta_v2(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": escena.normalizar(None, "4:5"), "aspecto": "4:5"})
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_vista_previa_v2_invalida_da_422(cliente_manager, marca):
    esc = escena.normalizar(None, "4:5")
    esc["capas"][1]["x"] = "a"
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": esc, "aspecto": "4:5"})
    assert r.status_code == 422


def test_listar_todas(cliente_manager, marca, cx, plantilla_legacy):
    borrador = plantillas.crear(cx, 1, "Borrador", "", _ct(), layout=layout.vacio("4:5"))
    ids_activas = {t["id"] for t in cliente_manager.get(f"/brands/{marca}/templates").json()}
    ids_todas = {t["id"] for t in
                 cliente_manager.get(f"/brands/{marca}/templates?estado=todas").json()}
    assert plantilla_legacy in ids_activas and borrador not in ids_activas
    assert {plantilla_legacy, borrador} <= ids_todas


def test_duplicar_guarda_v2(cliente_manager, marca, cx, plantilla_legacy):
    r = cliente_manager.post(f"/brands/{marca}/templates/{plantilla_legacy}/duplicate")
    nuevo = r.json()["id"]
    assert plantillas.layout_de(plantillas.obtener(cx, nuevo))["v"] == 2
```

Confirmar que `plantillas.crear` deja la fila en `borrador` por defecto (el DEFAULT de la tabla lo es) y que la respuesta de `_vista` trae `id`; si el nombre de la clave difiere, ajustar la prueba a lo que devuelve `_vista`.

- [ ] **Step 2: Ver que fallan**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_disenos_web.py -q
```
Esperado: fallan las nuevas y la de `revert` (el router todavía devuelve v1 y valida con `layout_mod`).

- [ ] **Step 3: Implementar en `api/routers/plantillas.py`**

Imports: quitar `from src.plantillas import layout as layout_mod` y agregar `from src.plantillas import escena as escena_mod`.

`listar_templates`:
```python
@router.get("/templates")
def listar_templates(slug: str,
                     estado: str | None = Query(
                         None, pattern="^(activa|borrador|archivada|todas)$"),
                     user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    # Sin parámetro sigue siendo «activas» (lo usa el creador de posts);
    # el editor pide `todas` para su lista.
    filtro = None if estado == "todas" else (estado or "activa")
    activas = plantillas.listar(cx, fila["id"], estado=filtro)
```
(el resto del cuerpo igual)

`_vista`:
```python
        "layout": plantillas.escena_de(fila),
```

`crear_diseno`:
```python
    layout_dict = cuerpo.layout or escena_mod.normalizar(None, cuerpo.aspecto)
```

`guardar_diseno`:
```python
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    fila = _plantilla_de_marca(cx, marca["id"], tid)
    contrato_dict = cuerpo.contrato or plantillas.contrato_de(fila)
    formato = (cuerpo.layout.get("lienzo") or {}).get("formato") \
        if cuerpo.layout.get("v") == 2 else None
    if cuerpo.contrato is None and formato in escena_mod.ASPECTO_DE_FORMATO:
        # El editor cambia de formato sin mandar el contrato: el aspecto lo
        # dicta el lienzo, y `nueva_version` lo copia a brand_templates.aspecto.
        contrato_dict = {**contrato_dict, "aspecto": escena_mod.ASPECTO_DE_FORMATO[formato]}
```
(el `try: plantillas.nueva_version(...)` sigue igual)

`vista_previa`, dentro del `try`:
```python
        contrato_mod.validar(contrato_dict)
        plantillas.validar_diseno(
            cuerpo.layout, contrato_dict,
            familias=fuentes_tipograficas.familias(cx, marca["id"]))
```
y actualizar el comentario de encima para que diga «`plantillas.validar_diseno` (v1 o v2)» en lugar de `layout.validar`.

`duplicar_diseno`:
```python
    layout_existente = plantillas.escena_de(fila)
    if layout_existente is None:
        # Legacy sin capas: la copia arranca un lienzo en blanco, editable.
        layout_nuevo = escena_mod.normalizar(None, fila["aspecto"])
        nombre_nuevo = f"{fila['nombre']} (editable)"
    else:
        layout_nuevo = layout_existente
        nombre_nuevo = f"{fila['nombre']} (copia)"
```

`revertir_diseno` no cambia: la versión vieja se restaura tal cual (v1 o v2) y `_vista` la normaliza al responder.

- [ ] **Step 4: Verde y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add api/routers/plantillas.py tests/test_disenos_web.py
git commit -m "$(cat <<'EOF'
api plantillas: escena v2 en lectura y escritura, estado=todas

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: `GET /brands/{slug}/files/assets/{archivo}`

**Files:**
- Modify: `api/routers/plantillas.py`
- Test: `tests/test_api_assets_archivos.py` (nuevo)

**Interfaces (HTTP):** `GET /brands/{slug}/files/assets/{archivo}` → bytes de `data/brands/<slug>/assets/<archivo>`. Rol mínimo `manager`. 404 si el nombre no cumple `^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$`, si la extensión no está en la lista blanca, si la ruta resuelta sale de la carpeta o si no existe. Cabeceras: `X-Content-Type-Options: nosniff`, `Cache-Control: private, max-age=86400`; los `.svg` llevan además `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`. El plan 3 llena la carpeta; este endpoint solo la sirve.

- [ ] **Step 1: Prueba que falla**

`tests/test_api_assets_archivos.py`:

```python
"""El lienzo del editor pide las imágenes de la escena a este endpoint."""
from __future__ import annotations

import pytest

import api.routers.plantillas as plantillas_api


@pytest.fixture()
def brands(tmp_path, monkeypatch):
    raiz = tmp_path / "brands"
    (raiz / "gdlscene" / "assets").mkdir(parents=True)
    (raiz / "otra" / "assets").mkdir(parents=True)
    monkeypatch.setattr(plantillas_api, "BRANDS_DIR", raiz)
    return raiz


@pytest.fixture()
def manager(api_cliente):
    cli, cx, H = api_cliente
    H.login(H.usuario("manager@x.com", marcas=[(1, "manager")]))
    return cli


def test_sirve_un_asset(manager, brands):
    (brands / "gdlscene" / "assets" / "abc.png").write_bytes(b"\x89PNG")
    r = manager.get("/brands/gdlscene/files/assets/abc.png")
    assert r.status_code == 200
    assert r.content == b"\x89PNG"
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_svg_va_en_sandbox(manager, brands):
    (brands / "gdlscene" / "assets" / "logo.svg").write_text("<svg/>")
    r = manager.get("/brands/gdlscene/files/assets/logo.svg")
    assert r.status_code == 200
    assert "sandbox" in r.headers["content-security-policy"]


@pytest.mark.parametrize("archivo", ["nada.png", "..%2Fsecreto.png", ".oculto.png",
                                     "script.html", "datos.json"])
def test_404(manager, brands, archivo):
    (brands / "gdlscene" / "secreto.png").write_bytes(b"x")
    (brands / "gdlscene" / "assets" / "script.html").write_text("<script>")
    (brands / "gdlscene" / "assets" / "datos.json").write_text("{}")
    assert manager.get(f"/brands/gdlscene/files/assets/{archivo}").status_code == 404


def test_symlink_que_sale_de_la_carpeta(manager, brands, tmp_path):
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(b"x")
    (brands / "gdlscene" / "assets" / "trampa.png").symlink_to(fuera)
    assert manager.get("/brands/gdlscene/files/assets/trampa.png").status_code == 404


def test_otra_marca_no(manager, brands, cx_otra):
    (brands / "otra" / "assets" / "suyo.png").write_bytes(b"x")
    assert manager.get("/brands/otra/files/assets/suyo.png").status_code in (403, 404)


def test_editor_no_pasa(api_cliente, brands):
    cli, cx, H = api_cliente
    H.login(H.usuario("editor@x.com", marcas=[(1, "editor")]))
    (brands / "gdlscene" / "assets" / "abc.png").write_bytes(b"x")
    assert cli.get("/brands/gdlscene/files/assets/abc.png").status_code == 403


@pytest.fixture()
def cx_otra(api_cliente):
    from src import db
    cx = api_cliente[1]
    db.insert(cx, "accounts", slug="otra", ig_handle="otra", nombre="Otra", ciudad="CDMX")
    return cx
```

Antes de fijar `test_otra_marca_no` y `test_editor_no_pasa`, confirmar en `tests/test_api_fuentes.py` qué código devuelve `marca_para` para una marca ajena (403 o 404) y para un rol insuficiente, y dejar la aserción exacta en lugar de `in (403, 404)`.

- [ ] **Step 2: Ver que falla**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_api_assets_archivos.py -q
```
Esperado: 404 en `test_sirve_un_asset` (la ruta no existe) y `KeyError` en el de SVG.

- [ ] **Step 3: Implementar** (en `api/routers/plantillas.py`, después de `archivo_fuente`; agregar `import re` arriba)

```python
_TIPO_ASSET = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
               ".mp4": "video/mp4", ".webm": "video/webm"}
_ARCHIVO_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


@router.get("/files/assets/{archivo}")
def archivo_asset(slug: str, archivo: str, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> FileResponse:
    """Los bytes de una imagen o video de la biblioteca de la marca.

    Es lo que pinta el lienzo del editor para una capa con `src: assets/<archivo>`.
    Mismo blindaje que `archivo_fuente`: nombre por regex, ruta resuelta dentro
    de la carpeta de ESTA marca (un symlink que apunte fuera no pasa) y lista
    blanca de extensiones. El SVG va con CSP sandbox: abierto directo en el
    navegador no puede correr scripts.
    """
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    if not _ARCHIVO_ASSET.match(archivo):
        raise no_encontrado("ese archivo")
    carpeta = (BRANDS_DIR / marca["slug"] / "assets").resolve()
    ruta = (carpeta / archivo).resolve()
    tipo = _TIPO_ASSET.get(ruta.suffix.lower())
    if tipo is None or not ruta.is_relative_to(carpeta) or not ruta.is_file():
        raise no_encontrado("ese archivo")
    headers = {"X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=86400"}
    if tipo == "image/svg+xml":
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; sandbox")
    return FileResponse(ruta, media_type=tipo, headers=headers)
```

- [ ] **Step 4: Verde y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add api/routers/plantillas.py tests/test_api_assets_archivos.py
git commit -m "$(cat <<'EOF'
api plantillas: servir assets/ de la marca

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Cierre del plan

- [ ] `pytest -q` completo (incluye `lento`) y anotar el resultado real en la nota de sesión: cuántas pasan, cuáles se saltaron y por qué.
- [ ] `git log --oneline master..feat/editor-v2` muestra 9 commits de este plan.
- [ ] Nada de push. El plan 2 arranca sobre esta rama.

## Qué queda sin verificar al escribir este plan

| Hueco | Dónde se resuelve |
|---|---|
| Que Chromium pinte el primer cuadro del `<video>` antes del screenshot (`compose._screenshot_card` no espera a `loadeddata`) | Subproyecto de video. Hoy el PNG puede salir con la capa de video vacía |
| Paridad de píxeles v1 ↔ v2 | Task 4, Step 5 (prueba `lento`) |
| Que todos los `layout_json` v1 de la VM conviertan a v2 válido | Solo se probó con `layout.vacio` y un v1 sintético. Antes del deploy: correr `escena.normalizar` + `escena.validar` sobre una copia de la BD de la VM (con aprobación de Ricardo) |
| `template.disenar` (`handlers.py:466`) sigue produciendo v1 | Plan 4 lo reemplaza. Mientras, el editor recibe ese v1 normalizado por `_vista` |
| Nombres exactos en pruebas existentes (`_HTML_MANUAL`, `marcas.cargar`, helper de jobs, códigos 403/404 de `marca_para`) | Cada task dice qué revisar antes de escribir la prueba |
