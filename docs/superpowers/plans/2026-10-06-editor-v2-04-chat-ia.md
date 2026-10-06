# Editor v2, plan 4: chat IA que crea y edita escenas

Spec: `docs/superpowers/specs/2026-10-06-editor-escena-v2-design.md` (commit e87942f), §5 «Chat IA» y §6 «Kinds».
Índice y contrato de interfaces: `docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md`.
Depende de: plan 1 (escena v2), plan 2 (`aplicarOps`, `useEditor`, `PanelLateral`), plan 3 (`buscar`, `biblioteca`, `recorte`).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** desde la pestaña «Chat» del editor, la persona escribe «hazme un post de 3 razones para…» y recibe una escena v2 editable, capa por capa. Después escribe «el título más grande y en amarillo» y recibe ops que se aplican como un paso de deshacer.

**Architecture:**
- **Crear:**
  - Claude elige un *kind* (10 plantillas Jinja hechas a mano) y llena su `spec` con una herramienta forzada.
  - El servidor resuelve las imágenes con el plan 3 y renderiza el HTML del kind en Chromium.
  - `extraer.py` mide cada elemento marcado con `data-tipo` y lo convierte en una capa v2.
  - Una pasada de crítica con visión puede corregir el `spec` una vez.
  - Claude no escribe coordenadas: las coordenadas salen del navegador.
- **Editar:**
  - Claude recibe la escena JSON y devuelve `ops` con la misma semántica que `aplicarOps` de TS.
  - Opcionalmente devuelve `buscar_asset`, que el servidor convierte en ops `set`.
  - El servidor aplica las ops y valida antes de responder.
- **Transporte:** job `diseno.chat`. Cada mensaje guarda una versión en `template_versions` (`mensaje_usuario`, `llm_meta`), y ese es el historial del chat.

**Tech Stack:**
- Python 3 y `anthropic` (ya está en `requirements.txt:6`).
- `jinja2` (`requirements.txt:8`).
- Playwright (Chromium, el mismo que `compose.py`) y Pillow para el diff.
- FastAPI.
- Next 16 y React 19.2 con zustand (plan 2) y vitest (plan 2).

## Global Constraints

- **Sin red en la suite normal.**
  - Toda prueba que llama a Claude reemplaza `llm_claude.pedir_herramienta` con monkeypatch.
  - Toda prueba que busca assets reemplaza `buscar.buscar`, `biblioteca.importar` y `recorte.quitar_fondo`.
  - Las pruebas con Chromium llevan `@pytest.mark.lento`.
- **Claude nunca produce coordenadas ni HTML.**
  - Al crear produce `kind + spec + consultas`.
  - Al editar produce `ops`.
  - Toda salida pasa por `kinds.validar_spec`, `ops.aplicar` y `escena.validar` antes de salir del job.
- **DSL de los kinds.** Lo que no cumpla esto no se extrae bien:
  - Toda capa es hija directa de `.card` y lleva `data-tipo`, `data-id` y `left`, `top` y `width` explícitos en px.
  - Las capas `image`, `shape`, `caja` y `svg` llevan además `height` explícito.
  - El texto no lleva saltos de línea ni espacios al inicio en la fuente: se usa `{%- -%}` y `<br>`.
  - Nada de `box-shadow` ni `text-shadow`: las sombras son `filter: drop-shadow(...)`.
  - El `padding` de `caja` es simétrico, para que el centro de rotación del fondo y del texto coincida.
- **Decoraciones.**
  - Las decoraciones sin capa propia (grano) llevan `data-aplanar` **sin** `data-tipo`.
  - Se hornean en `lienzo.fondo` como imagen.
- **Los kinds se diseñan en 4x5.**
  - 1:1 y 9:16 salen de `escena.reformatear` (plan 1).
- **Nombres del contrato del índice:**
  - `pedir_herramienta` gana dos kwargs opcionales, `uso` y `max_tokens`. El Task 0 los agrega al índice **antes** de escribir código.
- **Mantenimiento de lo existente:**
  - No se toca `src/plantillas/disenador.py` ni `POST /templates/design`. Siguen sirviendo a v1.
  - Se marcan como obsoletos en el Task 9 con un comentario y se borran después de que v2 esté en prod (fuera de este plan).
- **Comandos** (siempre desde la raíz del worktree `/Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2`):
  - `PY=/Users/ricardo/Work/personal/instagod/.venv/bin/python`
  - `PYTEST=/Users/ricardo/Work/personal/instagod/.venv/bin/pytest`
  - `RUFF=/Users/ricardo/Work/personal/instagod/.venv/bin/ruff`
- **Commits:** un commit por task, en la rama `feat/editor-v2`. Nada de push.

## Review Focus

- `ops.py` y `aplicarOps` (TS) **deben** dar el mismo resultado. Si la paridad falla, se corrige el lado que contradiga el índice; no se relaja la prueba.
- Aislamiento por marca en el handler y en el router: un `template_id` ajeno da 404 antes de encolar y `ValueError` dentro del job.
- `extraer.py`:
  - qué pasa con el texto que se desborda;
  - si un `rot` medido sin `transform` reproduce la misma caja;
  - si los colores se tokenizan solo cuando son exactos.
- El costo: el chat de crear hace como máximo 4 llamadas (diseñar, reintento, revisar, reintento implícito de revisar = 0). Ver `llm_meta.uso`.

## Desviaciones del spec (declaradas)

| # | Desviación | Por qué |
|---|---|---|
| 1 | `pedir_herramienta(..., uso=None, max_tokens=8192)` | Registrar tokens por mensaje en `llm_meta` sin otra API. Se amplía el índice en el Task 0 |
| 2 | Cada mensaje del chat guarda versión con `nueva_version` | El historial del chat vive en `template_versions` (lo pide el alcance). Contradice el «el chat propone, el editor dispone» de `template_disenar` (`handlers.py`) |
| 3 | Los kinds solo existen en 4x5; los demás formatos salen de `reformatear` | Diez plantillas por tres formatos son treinta diseños a mano |
| 4 | `historia` es una sola lámina | El carrusel queda para después de v2 |
| 5 | Validador de JSON Schema propio (`kinds/_esquema.py`) | Evita meter `jsonschema` por un subconjunto pequeño |
| 6 | Crear reemplaza la escena con `cargar()` y **pierde el historial de deshacer** | `useEditor` no expone «reemplazar como un paso». Editar sí es un paso (`aplicar`) |
| 7 | El título del kind es texto **fijo con spans**, sin `campo` | En plan 1 los `spans` solo existen sin `campo`, y el texto con `campo` no conserva saltos de línea. La persona puede ligarlo a `titular` en el editor |
| 8 | `caja` (texto con fondo) se separa en dos capas: shape `<id>_fondo` y text `<id>` | La capa de texto v2 no tiene `backgroundColor` ni padding |
| 9 | Los SVG de decoración y el fondo aplanado se escriben en `data/brands/<slug>/assets/` **sin fila en `brand_assets`** | No son assets de biblioteca. Quedan huérfanos si se descarta la versión |
| 10 | Si la crítica pide re-render, los archivos SVG y de fondo del primer intento quedan huérfanos | Lo mismo que el 9 |
| 11 | El plan 3 no expone un helper de recorte (solo el job `asset.recorte`). `_recortar` copia su convención: `<stem>-recorte.png` y `UPDATE brand_assets.recorte_archivo` filtrado por `account_id` | Verificado contra el plan 3 (handler `asset_recorte`) |

## No verificado (al escribir este plan)

- ⚠️ Que `claude-sonnet-5-5` acepte `tool_choice` forzado junto con imágenes en esta cuenta. El Task 7 trae una prueba `lento` real opcional.
- ⚠️ El costo por mensaje. Se mide con `llm_meta.uso` en la primera semana.
- ⚠️ Que el diff del round-trip sea ≤1% en los 10 kinds. Hay riesgos con el bold sintético, `fontSize` redondeado y el `nowrap` en compile v2. Si un kind no pasa, se ajusta el kind, no el umbral.
- ⚠️ Los detalles internos de los planes 1, 2 y 3 que todavía no están commiteados. El Task 0 los verifica con grep.

---

## Task 0: verificar el contrato contra el código real

**Files:**
- Modify: `docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md` (solo si algo difiere)

- [ ] **Step 1: comprobar que los planes 1, 2 y 3 ya están en la rama**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git log --oneline master..HEAD | head -40
grep -n "^def \(validar\|a_html\|reformatear\|normalizar\|_font_faces\)" src/plantillas/escena.py
grep -n "^def \(buscar\|importar\|ruta_de\|quitar_fondo\)" src/assets/buscar.py src/assets/biblioteca.py src/assets/recorte.py
grep -n "export function aplicarOps\|export type Op\b" frontend/lib/escena.ts
grep -n "cargar\|aplicar" frontend/stores/editor.ts | head
```

Esperado: las cinco funciones de `escena.py`, las cuatro de `src/assets/` y `aplicarOps` y `Op` en TS. Si falta algo, **se para**: este plan no arranca sin los planes 1 a 3.

- [ ] **Step 2: verificar los detalles de la escena v2 de los que depende `extraer.py`**

```bash
grep -n "TEXT_ALIGN\|TEXT_WRAP\|_LETTER\|letterSpacing\|_MASCARA\|rounded:\|fondo\[.tipo.\]\|\"imagen\"" src/plantillas/escena.py | head -40
grep -n "def _font_faces" -A20 src/plantillas/escena.py
grep -n "\"auto\"\|requerid\|obligatori" src/plantillas/escena.py | head
```

Checklist, con lo que asume este plan:

- [ ] `textAlign` acepta `left|center|right`.
- [ ] `letterSpacing` es un string `-0.020em`.
- [ ] `mascara` es `none|circle|rounded:N`.
- [ ] `lienzo.fondo` acepta `{"tipo":"imagen","valor":"assets/<f>"}` y se pinta con `background-size:cover`.
- [ ] Una capa puede quedar parcialmente fuera del lienzo (`x` negativo).
- [ ] `auto` es opcional en text.
- [ ] Los colores de `fondo.valor` aceptan `token:<n>`.
- [ ] `_font_faces(capas, fuentes)` acepta capas sintéticas `{"tipo":"text","estilo":{"fontFamily":...}}`.

Si algo difiere, se ajusta el código de los Tasks 6 y 7 de este plan (no el plan 1).

- [ ] **Step 3: verificar los nombres del plan 3 que usa el chat**

```bash
grep -n "proveedor\|autor\|licencia\|url_origen\|ig_handle\|archivo\|recorte_archivo" src/schema.sql | grep -i -A0 "" | head -20
grep -n "^def " src/assets/biblioteca.py src/assets/recorte.py
```

Esperado: las columnas `proveedor`, `autor`, `licencia`, `url_origen`, `ig_handle`, `archivo` y `recorte_archivo` en `brand_assets`. El plan 3 no expone helper de recorte; `_recortar` replica el nombre `<stem>-recorte.png` del job `asset.recorte` (desviación 11).

- [ ] **Step 4: verificar el frontend de pruebas y el editor**

```bash
cd frontend && grep -n "\"test\|vitest" package.json; ls tests 2>/dev/null; ls tests/unit 2>/dev/null | head; cd ..
grep -n "throw" frontend/lib/escena.ts | head
```

- Si las pruebas unitarias no viven en `frontend/tests/unit/`, se cambia la ruta del Task 2, Step 5 y del Task 10.
- Si `aplicarOps` **no** lanza ante una op inválida, los casos `error` del Task 2 fallan del lado TS. En ese caso se corrige `aplicarOps` (el índice dice «misma semántica»).

- [ ] **Step 5: verificar dependencias Python**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/python -c "import anthropic, jinja2, PIL, playwright; print(anthropic.__version__, jinja2.__version__)"
/Users/ricardo/Work/personal/instagod/.venv/bin/python -c "import config; print(sorted(config.SLIDESHOW_FUENTES)[:12])"
```

- Esperado: imprime las versiones y las familias, que incluyen `Anton-Regular`, `Poppins-Bold` y `Poppins-SemiBold`.
- Si `anthropic` no está instalado, se corre:
  ```bash
  /Users/ricardo/Work/personal/instagod/.venv/bin/pip install anthropic
  ```
  Ya está en `requirements.txt`, así que no hace falta editar el archivo.

- [ ] **Step 6: ampliar el índice con la firma real de `pedir_herramienta`**

En `docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md`, sección «Plan 4 (Python)», se reemplaza:

```python
def pedir_herramienta(*, system: str, mensajes: list[dict], herramienta: dict,
                      imagenes: list[Path] = (), modelo: str | None = None) -> dict
```

por:

```python
def pedir_herramienta(*, system: str, mensajes: list[dict], herramienta: dict,
                      imagenes: list[Path] = (), modelo: str | None = None,
                      uso: list[dict] | None = None, max_tokens: int = 8192) -> dict
# uso: si se pasa, se le agrega {"modelo","entrada","salida"} por llamada
```

y se agrega debajo de `ops.aplicar`:

```python
# src/plantillas/kinds/__init__.py
KINDS: tuple[str, ...]   # side, stat, vs, compare, list, cta, meme, historia, cita, propiedad
# src/plantillas/extraer.py
def extraer(html: str, *, slug: str, tokens: dict, fuente: str) -> tuple[bytes, dict, dict]   # png, escena, muestras
# src/plantillas/chat.py
def crear(cx, marca, mensaje, *, formato="4x5", uso=None) -> tuple[dict, dict, dict]      # escena, contrato, meta
def editar(cx, marca, escena, contrato, mensaje, *, uso=None) -> tuple[list, dict, dict]  # ops, escena, meta
```

- [ ] **Step 7: commit**

```bash
git add docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md
git commit -m "docs(plan4): amplía contrato del índice con uso/max_tokens, kinds, extraer y chat" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 1: `src/llm_claude.py`, una herramienta forzada con visión

**Files:**
- Create: `src/llm_claude.py`
- Modify: `config.py` (agregar `DISENO_MODELO` junto a `ANTHROPIC_API_KEY`, línea ~29)
- Test: `tests/test_llm_claude.py`

**Interfaces:**

```python
class LLMNoDisponible(RuntimeError): ...
class LLMSinHerramienta(RuntimeError): ...
def pedir_herramienta(*, system, mensajes, herramienta, imagenes=(), modelo=None, uso=None, max_tokens=8192) -> dict
```

- [ ] **Step 1: prueba que falla**

`tests/test_llm_claude.py`:

```python
import sys
import types

import pytest

import config
from src import llm_claude


class _Bloque:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Resp:
    def __init__(self, content, stop_reason="tool_use"):
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _Bloque(input_tokens=120, output_tokens=40)


@pytest.fixture
def anthropic_falso(monkeypatch):
    llamadas: list[dict] = []
    respuesta = {"r": _Resp([_Bloque(type="tool_use", name="disenar",
                                     input={"kind": "side"})])}

    class _Mensajes:
        def create(self, **kw):
            llamadas.append(kw)
            return respuesta["r"]

    class Anthropic:
        def __init__(self, api_key):
            assert api_key == "sk-prueba"
            self.messages = _Mensajes()

    mod = types.ModuleType("anthropic")
    mod.Anthropic = Anthropic
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-prueba")
    return llamadas, respuesta


HERR = {"name": "disenar", "description": "x",
        "input_schema": {"type": "object", "properties": {}}}


def test_fuerza_la_herramienta_y_devuelve_su_input(anthropic_falso):
    llamadas, _ = anthropic_falso
    uso: list[dict] = []
    out = llm_claude.pedir_herramienta(
        system="s", mensajes=[{"role": "user", "content": "hola"}],
        herramienta=HERR, uso=uso)
    assert out == {"kind": "side"}
    kw = llamadas[0]
    assert kw["tool_choice"] == {"type": "tool", "name": "disenar"}
    assert kw["tools"] == [HERR]
    assert kw["model"] == config.DISENO_MODELO
    assert uso == [{"modelo": config.DISENO_MODELO, "entrada": 120, "salida": 40}]


def test_adjunta_imagenes_al_ultimo_mensaje_de_usuario(anthropic_falso, tmp_path):
    llamadas, _ = anthropic_falso
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfalso")
    mensajes = [{"role": "user", "content": "uno"},
                {"role": "assistant", "content": "dos"},
                {"role": "user", "content": "tres"}]
    llm_claude.pedir_herramienta(system="s", mensajes=mensajes,
                                 herramienta=HERR, imagenes=[png])
    enviados = llamadas[0]["messages"]
    assert enviados[0]["content"] == "uno"
    ultimo = enviados[2]["content"]
    assert ultimo[0]["type"] == "image"
    assert ultimo[0]["source"]["media_type"] == "image/png"
    assert ultimo[1] == {"type": "text", "text": "tres"}
    assert mensajes[2]["content"] == "tres"   # no muta la entrada


def test_sin_tool_use_lanza(anthropic_falso):
    _, respuesta = anthropic_falso
    respuesta["r"] = _Resp([_Bloque(type="text", text="no")], stop_reason="max_tokens")
    with pytest.raises(llm_claude.LLMSinHerramienta, match="max_tokens"):
        llm_claude.pedir_herramienta(system="s", mensajes=[{"role": "user", "content": "x"}],
                                     herramienta=HERR)


def test_sin_api_key_lanza(monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    with pytest.raises(llm_claude.LLMNoDisponible):
        llm_claude.pedir_herramienta(system="s", mensajes=[{"role": "user", "content": "x"}],
                                     herramienta=HERR)


def test_extension_no_soportada(anthropic_falso, tmp_path):
    gif = tmp_path / "a.gif"
    gif.write_bytes(b"GIF89a")
    with pytest.raises(ValueError, match="gif"):
        llm_claude.pedir_herramienta(system="s", mensajes=[{"role": "user", "content": "x"}],
                                     herramienta=HERR, imagenes=[gif])
```

- [ ] **Step 2: correr y ver que falla**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_llm_claude.py -q
```

Esperado: `ModuleNotFoundError: No module named 'src.llm_claude'`.

- [ ] **Step 3: implementar**

`config.py`, justo debajo de la línea de `ANTHROPIC_API_KEY`:

```python
DISENO_MODELO = _get("DISENO_MODELO", "claude-sonnet-5-5")
```

`src/llm_claude.py`:

```python
"""Cliente mínimo de Claude para el diseñador v2.

Una sola forma de llamar: herramienta forzada (`tool_choice`), con imágenes
opcionales. Devuelve el `input` de la herramienta tal cual; validar es
trabajo de quien llama.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import config


class LLMNoDisponible(RuntimeError):
    """Falta la API key o el paquete `anthropic`."""


class LLMSinHerramienta(RuntimeError):
    """El modelo respondió sin llamar a la herramienta pedida."""


_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".webp": "image/webp"}


def _cliente():
    if not config.ANTHROPIC_API_KEY:
        raise LLMNoDisponible("falta ANTHROPIC_API_KEY")
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - depende del venv
        raise LLMNoDisponible("falta el paquete anthropic") from e
    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def _bloque_imagen(ruta: Path) -> dict[str, Any]:
    media = _MEDIA.get(ruta.suffix.lower())
    if media is None:
        raise ValueError(f"imagen no soportada: {ruta.suffix.lstrip('.')}")
    datos = base64.b64encode(ruta.read_bytes()).decode("ascii")
    return {"type": "image",
            "source": {"type": "base64", "media_type": media, "data": datos}}


def _con_imagenes(mensajes: list[dict], imagenes) -> list[dict]:
    mensajes = [dict(m) for m in mensajes]
    if not imagenes:
        return mensajes
    for i in range(len(mensajes) - 1, -1, -1):
        if mensajes[i].get("role") != "user":
            continue
        contenido = mensajes[i]["content"]
        if isinstance(contenido, str):
            contenido = [{"type": "text", "text": contenido}]
        mensajes[i]["content"] = [_bloque_imagen(Path(p)) for p in imagenes] + list(contenido)
        return mensajes
    raise ValueError("no hay mensaje de usuario al cual adjuntar imágenes")


def pedir_herramienta(*, system: str, mensajes: list[dict], herramienta: dict,
                      imagenes=(), modelo: str | None = None,
                      uso: list[dict] | None = None, max_tokens: int = 8192) -> dict:
    modelo = modelo or config.DISENO_MODELO
    enviados = _con_imagenes(mensajes, imagenes)
    cli = _cliente()
    resp = cli.messages.create(
        model=modelo, max_tokens=max_tokens, system=system, messages=enviados,
        tools=[herramienta], tool_choice={"type": "tool", "name": herramienta["name"]})
    if uso is not None:
        u = getattr(resp, "usage", None)
        uso.append({"modelo": modelo,
                    "entrada": int(getattr(u, "input_tokens", 0) or 0),
                    "salida": int(getattr(u, "output_tokens", 0) or 0)})
    for bloque in resp.content:
        if getattr(bloque, "type", None) == "tool_use" and bloque.name == herramienta["name"]:
            return dict(bloque.input)
    raise LLMSinHerramienta(f"sin llamada a {herramienta['name']} (stop_reason={resp.stop_reason})")
```

Nota: `_con_imagenes` corre antes que `_cliente()` para que `test_extension_no_soportada` falle por la extensión y no por la clave.

- [ ] **Step 4: verde y lint**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_llm_claude.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
```

Esperado: `5 passed`, ruff sin errores.

- [ ] **Step 5: commit**

```bash
git add config.py src/llm_claude.py tests/test_llm_claude.py
git commit -m "feat(llm): cliente Claude con herramienta forzada, visión y registro de uso" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: `src/plantillas/ops.py` con paridad Python/TS

**Files:**
- Create: `src/plantillas/ops.py`
- Create: `tests/fixtures/ops/casos.json`
- Test: `tests/test_ops.py`
- Test: `frontend/tests/unit/ops-paridad.test.ts` (ruta confirmada en el Task 0, Step 4)

**Semántica** (es la del índice, y esta prueba la fija para ambos lados):

- `set`:
  - `ruta` va con puntos y crea los dicts intermedios.
  - `valor: null` **borra** la clave.
  - Prohíbe los segmentos vacíos y los segmentos `id`, `__proto__`, `constructor` y `prototype`.
  - Si un intermedio no es dict, error.
- `add`:
  - `capa.id` debe cumplir `^[a-z][a-z0-9_-]{0,31}$` y no estar repetido.
  - `indice` se recorta a `[0, len]`; si no se da, la capa va al final.
- `del`:
  - Quita la capa y también su id de los `hijos` de cualquier grupo.
- Una op desconocida o una capa inexistente lanza error, y ninguna entrada se muta.

- [ ] **Step 1: fixture compartido**

`tests/fixtures/ops/casos.json`:

```json
[
  {"nombre": "set crea intermedios",
   "escena": {"v": 2, "capas": [{"id": "t", "tipo": "text"}]},
   "ops": [{"op": "set", "capa": "t", "ruta": "estilo.color", "valor": "#ff0000"}],
   "esperado": {"v": 2, "capas": [{"id": "t", "tipo": "text", "estilo": {"color": "#ff0000"}}]}},
  {"nombre": "set con null borra la clave",
   "escena": {"v": 2, "capas": [{"id": "t", "tipo": "text", "estilo": {"color": "#000000", "fontSize": 40}}]},
   "ops": [{"op": "set", "capa": "t", "ruta": "estilo.color", "valor": null}],
   "esperado": {"v": 2, "capas": [{"id": "t", "tipo": "text", "estilo": {"fontSize": 40}}]}},
  {"nombre": "set reemplaza un objeto entero",
   "escena": {"v": 2, "capas": [{"id": "f", "tipo": "image", "src": "assets/a.png"}]},
   "ops": [{"op": "set", "capa": "f", "ruta": "fuente_asset", "valor": {"proveedor": "pexels", "autor": "Ana"}}],
   "esperado": {"v": 2, "capas": [{"id": "f", "tipo": "image", "src": "assets/a.png", "fuente_asset": {"proveedor": "pexels", "autor": "Ana"}}]}},
  {"nombre": "add al final y con indice recortado",
   "escena": {"v": 2, "capas": [{"id": "a", "tipo": "shape"}]},
   "ops": [{"op": "add", "capa": {"id": "b", "tipo": "shape"}},
           {"op": "add", "capa": {"id": "c", "tipo": "shape"}, "indice": -5}],
   "esperado": {"v": 2, "capas": [{"id": "c", "tipo": "shape"}, {"id": "a", "tipo": "shape"}, {"id": "b", "tipo": "shape"}]}},
  {"nombre": "del quita de hijos",
   "escena": {"v": 2, "capas": [{"id": "g", "tipo": "group", "hijos": ["a", "b"]}, {"id": "a", "tipo": "shape"}, {"id": "b", "tipo": "shape"}]},
   "ops": [{"op": "del", "capa": "a"}],
   "esperado": {"v": 2, "capas": [{"id": "g", "tipo": "group", "hijos": ["b"]}, {"id": "b", "tipo": "shape"}]}},
  {"nombre": "set sobre id prohibido", "error": true,
   "escena": {"v": 2, "capas": [{"id": "t", "tipo": "text"}]},
   "ops": [{"op": "set", "capa": "t", "ruta": "id", "valor": "x"}]},
  {"nombre": "set con __proto__", "error": true,
   "escena": {"v": 2, "capas": [{"id": "t", "tipo": "text"}]},
   "ops": [{"op": "set", "capa": "t", "ruta": "estilo.__proto__.x", "valor": 1}]},
  {"nombre": "set con segmento vacío", "error": true,
   "escena": {"v": 2, "capas": [{"id": "t", "tipo": "text"}]},
   "ops": [{"op": "set", "capa": "t", "ruta": "estilo..color", "valor": 1}]},
  {"nombre": "set a través de un no-dict", "error": true,
   "escena": {"v": 2, "capas": [{"id": "t", "tipo": "text", "texto": "hola"}]},
   "ops": [{"op": "set", "capa": "t", "ruta": "texto.color", "valor": 1}]},
  {"nombre": "capa inexistente", "error": true,
   "escena": {"v": 2, "capas": []},
   "ops": [{"op": "del", "capa": "nada"}]},
  {"nombre": "add con id duplicado", "error": true,
   "escena": {"v": 2, "capas": [{"id": "a", "tipo": "shape"}]},
   "ops": [{"op": "add", "capa": {"id": "a", "tipo": "shape"}}]},
  {"nombre": "add con id inválido", "error": true,
   "escena": {"v": 2, "capas": []},
   "ops": [{"op": "add", "capa": {"id": "1mal", "tipo": "shape"}}]},
  {"nombre": "op desconocida", "error": true,
   "escena": {"v": 2, "capas": []},
   "ops": [{"op": "mover", "capa": "a"}]}
]
```

- [ ] **Step 2: prueba Python que falla**

`tests/test_ops.py`:

```python
import copy
import json
from pathlib import Path

import pytest

from src.plantillas import ops

CASOS = json.loads((Path(__file__).parent / "fixtures/ops/casos.json").read_text())


@pytest.mark.parametrize("caso", CASOS, ids=[c["nombre"] for c in CASOS])
def test_paridad(caso):
    original = copy.deepcopy(caso["escena"])
    if caso.get("error"):
        with pytest.raises(ops.OpInvalida):
            ops.aplicar(caso["escena"], caso["ops"])
    else:
        assert ops.aplicar(caso["escena"], caso["ops"]) == caso["esperado"]
    assert caso["escena"] == original


def test_valor_se_copia():
    valor = {"a": [1]}
    out = ops.aplicar({"v": 2, "capas": [{"id": "t"}]},
                      [{"op": "set", "capa": "t", "ruta": "x", "valor": valor}])
    valor["a"].append(2)
    assert out["capas"][0]["x"] == {"a": [1]}


def test_ops_no_lista():
    with pytest.raises(ops.OpInvalida):
        ops.aplicar({"v": 2, "capas": []}, {"op": "del"})
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ops.py -q
```

Esperado: `ImportError` en `src.plantillas.ops`.

- [ ] **Step 3: implementar**

`src/plantillas/ops.py`:

```python
"""Ops sobre escenas v2. Misma semántica que `aplicarOps` en frontend/lib/escena.ts.

La prueba de paridad (`tests/fixtures/ops/casos.json`) corre en pytest y en
vitest: si cambias algo aquí, cámbialo allá en el mismo commit.
"""
from __future__ import annotations

import copy
import re
from typing import Any

_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_PROHIBIDOS = {"id", "__proto__", "constructor", "prototype"}


class OpInvalida(ValueError):
    pass


def _capa(capas: list[dict], cid: Any) -> dict:
    for c in capas:
        if c.get("id") == cid:
            return c
    raise OpInvalida(f"no existe la capa {cid!r}")


def _set(capas: list[dict], op: dict) -> None:
    ruta = op.get("ruta")
    if not isinstance(ruta, str) or not ruta:
        raise OpInvalida("set necesita ruta")
    segmentos = ruta.split(".")
    if any(not s or s in _PROHIBIDOS for s in segmentos):
        raise OpInvalida(f"ruta no permitida: {ruta!r}")
    obj = _capa(capas, op.get("capa"))
    for s in segmentos[:-1]:
        sig = obj.get(s)
        if sig is None:
            sig = obj[s] = {}
        elif not isinstance(sig, dict):
            raise OpInvalida(f"{ruta!r}: {s!r} no es un objeto")
        obj = sig
    if op.get("valor") is None:
        obj.pop(segmentos[-1], None)
    else:
        obj[segmentos[-1]] = copy.deepcopy(op["valor"])


def _add(capas: list[dict], op: dict) -> None:
    capa = op.get("capa")
    if not isinstance(capa, dict) or not _ID.match(str(capa.get("id", ""))):
        raise OpInvalida("add necesita una capa con id válido")
    if any(c.get("id") == capa["id"] for c in capas):
        raise OpInvalida(f"id duplicado: {capa['id']!r}")
    indice = op.get("indice", len(capas))
    if not isinstance(indice, int) or isinstance(indice, bool):
        raise OpInvalida("indice debe ser entero")
    capas.insert(max(0, min(len(capas), indice)), copy.deepcopy(capa))


def _del(capas: list[dict], op: dict) -> None:
    cid = op.get("capa")
    capas.remove(_capa(capas, cid))
    for c in capas:
        hijos = c.get("hijos")
        if isinstance(hijos, list) and cid in hijos:
            c["hijos"] = [h for h in hijos if h != cid]


_OPS = {"set": _set, "add": _add, "del": _del}


def aplicar(escena: dict, ops: list[dict]) -> dict:
    if not isinstance(ops, list):
        raise OpInvalida("ops debe ser una lista")
    nueva = copy.deepcopy(escena)
    capas = nueva.setdefault("capas", [])
    for op in ops:
        if not isinstance(op, dict) or op.get("op") not in _OPS:
            raise OpInvalida(f"op desconocida: {op!r:.80}")
        _OPS[op["op"]](capas, op)
    return nueva
```

- [ ] **Step 4: verde**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ops.py -q
```

Esperado: `15 passed`.

- [ ] **Step 5: paridad del lado TS**

`frontend/tests/unit/ops-paridad.test.ts`:

```ts
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { aplicarOps, type Escena, type Op } from "../../lib/escena";

type Caso = { nombre: string; escena: Escena; ops: Op[]; esperado?: Escena; error?: boolean };

const casos: Caso[] = JSON.parse(
  readFileSync(resolve(__dirname, "../../../tests/fixtures/ops/casos.json"), "utf8"),
);

describe("paridad ops Python/TS", () => {
  for (const c of casos) {
    it(c.nombre, () => {
      const original = structuredClone(c.escena);
      if (c.error) {
        expect(() => aplicarOps(c.escena, c.ops)).toThrow();
      } else {
        expect(aplicarOps(c.escena, c.ops)).toEqual(c.esperado);
      }
      expect(c.escena).toEqual(original);
    });
  }
});
```

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend && pnpm vitest run tests/unit/ops-paridad.test.ts; cd ..
```

- Esperado: `13 passed`.
- Si falla algún caso (lo más probable: `null` que borra, recorte de `indice`, o `del` sobre `hijos`), se corrige `aplicarOps` en `frontend/lib/escena.ts` para cumplir la semántica de arriba y se vuelve a correr la suite de vitest completa:
  ```bash
  pnpm vitest run
  ```
  El cambio TS se anota en el mensaje de commit.

- [ ] **Step 6: lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/plantillas/ops.py tests/test_ops.py tests/fixtures/ops/casos.json frontend/tests/unit/ops-paridad.test.ts frontend/lib/escena.ts
git commit -m "feat(escena): ops.aplicar en Python con fixture de paridad compartido con aplicarOps" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: infraestructura de kinds

**Files:**
- Create: `src/plantillas/kinds/__init__.py`
- Create: `src/plantillas/kinds/_esquema.py`
- Create: `src/plantillas/kinds/_base.html.j2`
- Create: `src/plantillas/kinds/_parciales.html.j2`
- Test: `tests/test_kinds_infra.py`

**Interfaces:**

```python
KINDS = ("side", "stat", "vs", "compare", "list", "cta", "meme", "historia", "cita", "propiedad")
class SpecInvalido(ValueError): ...
def esquema(kind: str) -> dict                 # comunes + propio; "x-slots" incluido
def esquema_para_llm(kind: str) -> dict        # sin "x-*" ni "default"
def catalogo() -> list[dict]                   # [{"kind","descripcion","esquema"}]
def validar_spec(kind: str, spec: dict) -> dict   # con defaults
def slots(kind: str, spec: dict) -> list[dict]    # [{"id","recorte","requerido"}]
def tokens_de(marca, tema: str = "claro") -> dict[str, str]
def fuentes_de(marca, familias: set[str], kind: str) -> dict[str, str]   # {"titulo","texto"}
def css_fuentes(familias_usadas: set[str], catalogo: list[dict]) -> str
def render(kind, spec, *, tokens, fuentes, assets, font_faces="", handle="", logo="") -> str
```

**DSL de elementos** (lo lee `extraer.py` en el Task 6):

| `data-tipo` | Qué es | Atributos extra | Se convierte en |
|---|---|---|---|
| `text` | texto sin fondo; `<br>` = salto; `<span data-acento>` = span de color | `data-campo`, `data-valign` (`top|center|bottom`) | capa `text` |
| `caja` | texto con `background` + `padding` simétrico + `border-radius` | igual que `text` | shape `<id>_fondo` + text `<id>` (z+5) |
| `shape` | `div` con `background`, `border-radius`, `border`; `50%` = elipse | — | capa `shape` |
| `image` | `div` con `background-image` | `data-src="assets/…"`, `data-recorte`, `data-fuente-asset='{json}'`, `data-campo` | capa `image` |
| `svg` | `div` con un `<svg viewBox>` dentro | — | archivo `assets/<sha>.svg` + capa `svg` |
| *(sin data-tipo)* `data-aplanar` | decoración (grano) | — | se hornea en `lienzo.fondo` |

Todas: `data-id` (regex v1, ≤25 caracteres para que quepa `_fondo`), `data-nombre`, `data-anclaje` opcional.

- [ ] **Step 1: prueba que falla**

`tests/test_kinds_infra.py`:

```python
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
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_kinds_infra.py -q
```

Esperado: `ImportError`. (`side` y `compare` llegan en el Task 4; por eso este task crea ya `side.schema.json`, `side.html.j2` y `compare.schema.json`, y el Task 4 solo los completa y prueba. Ver Step 5.)

- [ ] **Step 2: validador mínimo**

`src/plantillas/kinds/_esquema.py`:

```python
"""Subconjunto de JSON Schema que usan los kinds. Nada más.

type, properties, required, additionalProperties(False), items, enum,
minLength/maxLength, pattern, minItems/maxItems, minimum/maximum.
"""
from __future__ import annotations

import re
from typing import Any

_TIPOS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
}


def errores(valor: Any, esquema: dict, ruta: str = "$") -> list[str]:
    tipo = esquema.get("type")
    if tipo and not _TIPOS[tipo](valor):
        return [f"{ruta}: se esperaba {tipo}"]
    out: list[str] = []
    if "enum" in esquema and valor not in esquema["enum"]:
        out.append(f"{ruta}: debe ser uno de {esquema['enum']}")
    if tipo == "string":
        if len(valor) < esquema.get("minLength", 0):
            out.append(f"{ruta}: mínimo {esquema['minLength']} caracteres")
        if "maxLength" in esquema and len(valor) > esquema["maxLength"]:
            out.append(f"{ruta}: máximo {esquema['maxLength']} caracteres")
        if "pattern" in esquema and not re.search(esquema["pattern"], valor):
            out.append(f"{ruta}: no cumple {esquema['pattern']}")
    if tipo in ("integer", "number"):
        if "minimum" in esquema and valor < esquema["minimum"]:
            out.append(f"{ruta}: mínimo {esquema['minimum']}")
        if "maximum" in esquema and valor > esquema["maximum"]:
            out.append(f"{ruta}: máximo {esquema['maximum']}")
    if tipo == "array":
        if len(valor) < esquema.get("minItems", 0):
            out.append(f"{ruta}: mínimo {esquema['minItems']} elementos")
        if "maxItems" in esquema and len(valor) > esquema["maxItems"]:
            out.append(f"{ruta}: máximo {esquema['maxItems']} elementos")
        if "items" in esquema:
            for i, v in enumerate(valor):
                out += errores(v, esquema["items"], f"{ruta}[{i}]")
    if tipo == "object":
        props = esquema.get("properties", {})
        for req in esquema.get("required", []):
            if req not in valor:
                out.append(f"{ruta}.{req}: obligatorio")
        if esquema.get("additionalProperties") is False:
            for k in valor:
                if k not in props:
                    out.append(f"{ruta}.{k}: propiedad no permitida")
        for k, v in valor.items():
            if k in props:
                out += errores(v, props[k], f"{ruta}.{k}")
    return out
```

- [ ] **Step 3: módulo de kinds**

`src/plantillas/kinds/__init__.py`:

```python
"""Kinds: diseños Jinja hechos a mano que el chat llena con un `spec`.

El modelo elige kind y spec; el navegador pone las coordenadas
(`plantillas/extraer.py`). Todos se diseñan en 4x5 (1080×1350).
"""
from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jinja2

from ... import compose
from .. import escena as escena_mod
from ._esquema import errores

KINDS = ("side", "stat", "vs", "compare", "list", "cta", "meme", "historia", "cita", "propiedad")
_DIR = Path(__file__).parent


class SpecInvalido(ValueError):
    pass


_STICKER = {"type": "object", "additionalProperties": False, "required": ["texto"],
            "properties": {"texto": {"type": "string", "minLength": 1, "maxLength": 24},
                           "color": {"type": "string", "enum": ["acento", "destacado", "profundo"]}}}

COMUNES: dict[str, dict] = {
    "tema": {"type": "string", "enum": ["claro", "oscuro", "marca"], "default": "claro",
             "description": "claro = fondo blanco; oscuro = fondo casi negro; marca = fondo del color de la marca"},
    "etiqueta": {"type": "string", "maxLength": 40, "description": "píldora corta arriba"},
    "titulo": {"type": "array", "minItems": 1, "maxItems": 4,
               "items": {"type": "string", "minLength": 1, "maxLength": 40},
               "description": "una línea por elemento; el salto lo decides tú"},
    "acento": {"type": "string", "maxLength": 40,
               "description": "fragmento literal del título que se pinta en color de acento"},
    "bajada": {"type": "string", "maxLength": 220},
    "cta": {"type": "string", "maxLength": 40},
    "stickers": {"type": "array", "maxItems": 3, "items": _STICKER, "default": []},
    "grano": {"type": "boolean", "default": False, "description": "textura de grano sobre el fondo"},
}


@lru_cache(maxsize=None)
def _propio(kind: str) -> dict:
    return json.loads((_DIR / f"{kind}.schema.json").read_text(encoding="utf-8"))


def esquema(kind: str) -> dict:
    if kind not in KINDS:
        raise SpecInvalido(f"kind desconocido: {kind!r}")
    propio = _propio(kind)
    props = {**COMUNES, **propio.get("properties", {})}
    return {"type": "object", "description": propio["description"], "properties": props,
            "required": sorted({"titulo", *propio.get("required", [])}),
            "additionalProperties": False, "x-slots": propio.get("x-slots", [])}


def _limpio(nodo: Any) -> Any:
    if isinstance(nodo, dict):
        return {k: _limpio(v) for k, v in nodo.items()
                if not k.startswith("x-") and k != "default"}
    if isinstance(nodo, list):
        return [_limpio(v) for v in nodo]
    return nodo


def esquema_para_llm(kind: str) -> dict:
    return _limpio(esquema(kind))


def catalogo() -> list[dict]:
    return [{"kind": k, "descripcion": _propio(k)["description"], "esquema": esquema_para_llm(k)}
            for k in KINDS]


def _con_defaults(spec: dict, props: dict) -> dict:
    out = copy.deepcopy(spec)
    for k, p in props.items():
        if k not in out and "default" in p:
            out[k] = copy.deepcopy(p["default"])
    return out


def validar_spec(kind: str, spec: dict) -> dict:
    e = esquema(kind)
    if not isinstance(spec, dict):
        raise SpecInvalido("spec debe ser un objeto")
    errs = errores(spec, e)
    if errs:
        raise SpecInvalido("; ".join(errs[:8]))
    return _con_defaults(spec, e["properties"])


def slots(kind: str, spec: dict) -> list[dict]:
    out = []
    for s in esquema(kind)["x-slots"]:
        if s.get("por"):
            for i, _ in enumerate(spec.get(s["por"]) or []):
                out.append({"id": f"{s['id']}_{i}", "recorte": bool(s.get("recorte")),
                            "requerido": bool(s.get("requerido"))})
            continue
        requerido = bool(s.get("requerido")) or bool(
            s.get("requerido_si") and spec.get(s["requerido_si"]))
        out.append({"id": s["id"], "recorte": bool(s.get("recorte")), "requerido": requerido})
    return out


def _sobre(hexa: str) -> str:
    h = hexa.lstrip("#")
    if len(h) != 6:
        return "#FFFFFF"
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#1C1A23" if lum > 0.6 else "#FFFFFF"


def tokens_de(marca, tema: str = "claro") -> dict[str, str]:
    acento = (marca.color_marca or "#7A4CFF").upper()
    base = {
        "claro": {"fondo": "#FFFFFF", "tinta": "#1C1A23", "suave": "#5B5866", "panel": "#F3F1F6"},
        "oscuro": {"fondo": "#1C1A23", "tinta": "#FFFFFF", "suave": "#C9C6D1", "panel": "#2A2733"},
        "marca": {"fondo": acento, "tinta": _sobre(acento), "suave": _sobre(acento),
                  "panel": "rgba(255,255,255,0.14)"},
    }[tema]
    t = {**base, "acento": acento, "sobre_acento": _sobre(acento),
         "destacado": "#F5C842", "sobre_destacado": "#3B2C00",
         "profundo": "#1C1A23", "sobre_profundo": "#FFFFFF"}
    if tema == "marca":
        # Sobre fondo de marca el acento sería invisible: se usa el destacado.
        t["acento"], t["sobre_acento"] = t["destacado"], t["sobre_destacado"]
    t.update((getattr(marca, "estilos", None) or {}).get("tokens", {}))
    t.pop("marca", None)   # nombre reservado por escena.validar
    return t


_TITULO_KIND = {"meme": "Anton-Regular"}


def fuentes_de(marca, familias: set[str], kind: str) -> dict[str, str]:
    propia = (marca.fuentes or [None])[0]
    titulo = _TITULO_KIND.get(kind) or (propia if propia in familias else "Poppins-Bold")
    if titulo not in familias:
        titulo = "Poppins-Bold"
    return {"titulo": titulo, "texto": "Poppins-SemiBold"}


def css_fuentes(familias_usadas: set[str], catalogo_fuentes: list[dict]) -> str:
    capas = [{"tipo": "text", "estilo": {"fontFamily": f}} for f in sorted(familias_usadas)]
    css = escena_mod._font_faces(capas, catalogo_fuentes)
    return css.replace("{{ fonts_dir }}", compose.FONTS_DIR.as_uri())


_ENV = jinja2.Environment(loader=jinja2.FileSystemLoader(str(_DIR)), autoescape=True,
                          undefined=jinja2.StrictUndefined, trim_blocks=True, lstrip_blocks=True)


def render(kind: str, spec: dict, *, tokens: dict, fuentes: dict, assets: dict,
           font_faces: str = "", handle: str = "", logo: str = "") -> str:
    e = esquema(kind)
    completo = {k: spec.get(k) for k in e["properties"]}
    completo["stickers"] = completo.get("stickers") or []
    a = {s["id"]: assets.get(s["id"]) for s in slots(kind, completo)}
    return _ENV.get_template(f"{kind}.html.j2").render(
        spec=completo, t=tokens, f=fuentes, a=a, font_faces=font_faces,
        handle=handle, logo=logo)
```

- [ ] **Step 4: base y parciales**

`src/plantillas/kinds/_base.html.j2`:

```jinja
{% import "_parciales.html.j2" as p %}
<!doctype html>
<html><head><meta charset="utf-8"><style>
{{ font_faces|safe }}
*{margin:0;padding:0;box-sizing:border-box}
html,body{width:1080px;height:1350px;background:transparent}
.card{position:relative;width:1080px;height:1350px;overflow:hidden;background:{{ t.fondo }};
  font-family:'{{ f.texto }}';color:{{ t.tinta }};-webkit-font-smoothing:antialiased;--acento:{{ t.acento }}}
.card>[data-tipo]{position:absolute}
.card>[data-tipo="text"],.card>[data-tipo="caja"]{white-space:pre-line}
.titulo{font-family:'{{ f.titulo }}';font-weight:700;line-height:1.02;letter-spacing:-0.02em;color:{{ t.tinta }}}
.bajada{font-size:36px;line-height:1.3;font-weight:600;color:{{ t.suave }}}
.pill{font-size:28px;font-weight:600;line-height:1.2;padding:14px 28px;border-radius:999px;white-space:nowrap;text-align:center}
{% block estilos %}{% endblock %}
</style></head>
<body><div class="card lienzo">
{% block capas %}{% endblock %}
{% set ps = posiciones_sticker if posiciones_sticker is defined else [(760, 96, 8), (90, 1120, -6), (700, 1140, 5)] %}
{% for s in spec.stickers %}{% set q = ps[loop.index0] %}{{ p.sticker("sticker_" ~ loop.index0, s, q[0], q[1], q[2], t) }}{% endfor %}
{{ p.pie(handle, logo, t) }}
{% if spec.grano %}{{ p.grano() }}{% endif %}
</div></body></html>
```

> Un kind define `{% set posiciones_sticker = [...] %}` **fuera** de bloques. En Jinja, las asignaciones de nivel superior de la plantilla hija se ejecutan antes que el padre y el padre las ve. ⚠️ Con `StrictUndefined`, `is defined` sigue funcionando; se confirma en `test_render_strict_y_escapa`.

`src/plantillas/kinds/_parciales.html.j2`:

```jinja
{% macro texto_con_acento(lineas, acento) -%}
{%- for l in lineas -%}
{%- if not loop.first %}<br>{% endif -%}
{%- if acento and acento in l -%}
{%- set i = l.find(acento) -%}
{{ l[:i] }}<span data-acento="acento" style="color:var(--acento)">{{ acento }}</span>{{ l[i + acento|length:] }}
{%- else -%}
{{ l }}
{%- endif -%}
{%- endfor -%}
{%- endmacro %}

{% macro texto(id, nombre, x, y, w, size, contenido, clase="", campo=None, anclaje=None, color=None, alinea="left", valign="top", extra="") -%}
<div data-tipo="text" data-id="{{ id }}" data-nombre="{{ nombre }}"{% if campo %} data-campo="{{ campo }}"{% endif %}{% if anclaje %} data-anclaje="{{ anclaje }}"{% endif %} data-valign="{{ valign }}" class="{{ clase }}" style="left:{{ x }}px;top:{{ y }}px;width:{{ w }}px;font-size:{{ size }}px;text-align:{{ alinea }};{% if color %}color:{{ color }};{% endif %}{{ extra }}">{{ contenido }}</div>
{%- endmacro %}

{% macro caja(id, nombre, x, y, w, h, contenido, bg, fg, size=28, radio="999px", rot=0, peso=600, padding=24) -%}
<div data-tipo="caja" data-id="{{ id }}" data-nombre="{{ nombre }}" data-valign="center" style="left:{{ x }}px;top:{{ y }}px;width:{{ w }}px;height:{{ h }}px;padding:{{ padding }}px;background:{{ bg }};color:{{ fg }};border-radius:{{ radio }};font-size:{{ size }}px;font-weight:{{ peso }};line-height:1.15;text-align:center;display:flex;align-items:center;justify-content:center;{% if rot %}transform:rotate({{ rot }}deg);{% endif %}">{{ contenido }}</div>
{%- endmacro %}

{% macro pill(id, texto, x, y, w, t, color="panel", fg=None) -%}
{{ caja(id, "Píldora", x, y, w, 64, texto, t[color], fg or t.tinta, size=26, padding=12) }}
{%- endmacro %}

{% macro sticker(id, s, x, y, rot, t) -%}
{%- set c = s.color or "destacado" -%}
{{ caja(id, "Sticker", x, y, 260, 76, s.texto, t[c], t["sobre_" ~ c], size=28, rot=rot, peso=700, padding=14) }}
{%- endmacro %}

{% macro coin(id, texto, x, y, d, bg, fg, size=40) -%}
{{ caja(id, "Moneda", x, y, d, d, texto, bg, fg, size=size, radio="50%", peso=700, padding=12) }}
{%- endmacro %}

{% macro shape(id, nombre, x, y, w, h, bg, radio="0px", extra="") -%}
<div data-tipo="shape" data-id="{{ id }}" data-nombre="{{ nombre }}" style="left:{{ x }}px;top:{{ y }}px;width:{{ w }}px;height:{{ h }}px;background:{{ bg }};border-radius:{{ radio }};{{ extra }}"></div>
{%- endmacro %}

{% macro foto(id, asset, x, y, w, h, nombre="Foto", campo=None, recorte=False, radio="0px", ajuste="cover", anclaje=None, sombra=False) -%}
{%- if asset -%}
<div data-tipo="image" data-id="{{ id }}" data-nombre="{{ nombre }}"{% if campo %} data-campo="{{ campo }}"{% endif %}{% if anclaje %} data-anclaje="{{ anclaje }}"{% endif %} data-src="{{ asset.archivo }}"{% if recorte %} data-recorte="1"{% endif %} data-fuente-asset='{{ asset.fuente_asset|tojson }}' style="left:{{ x }}px;top:{{ y }}px;width:{{ w }}px;height:{{ h }}px;background-image:url('{{ asset.src }}');background-size:{{ ajuste }};background-position:center;background-repeat:no-repeat;border-radius:{{ radio }};{% if sombra %}filter:drop-shadow(0px 18px 30px rgba(0,0,0,0.25));{% endif %}"></div>
{%- endif -%}
{%- endmacro %}

{% macro recorte(id, asset, x, y, w, h, nombre="Recorte") -%}
{{ foto(id, asset, x, y, w, h, nombre=nombre, recorte=True, ajuste="contain", sombra=True) }}
{%- endmacro %}

{% macro telefono(id, asset, x, y, w, h, t, campo=None) -%}
{%- if asset -%}
{{ shape(id ~ "_marco", "Teléfono", x, y, w, h, t.profundo, "96px", "filter:drop-shadow(0px 24px 40px rgba(0,0,0,0.30));") }}
{{ foto(id, asset, x + 12, y + 12, w - 24, h - 24, nombre="Pantalla", campo=campo, radio="84px") }}
{%- endif -%}
{%- endmacro %}

{% macro flor(id, x, y, d, color, centro) -%}
<div data-tipo="svg" data-id="{{ id }}" data-nombre="Flor" style="left:{{ x }}px;top:{{ y }}px;width:{{ d }}px;height:{{ d }}px">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100%" height="100%">
{%- for i in range(10) %}<ellipse cx="50" cy="24" rx="9" ry="22" fill="{{ color }}" transform="rotate({{ i * 36 }} 50 50)"/>{% endfor -%}
<circle cx="50" cy="50" r="12" fill="{{ centro }}"/></svg></div>
{%- endmacro %}

{% macro comillas(id, x, y, d, color) -%}
<div data-tipo="svg" data-id="{{ id }}" data-nombre="Comillas" style="left:{{ x }}px;top:{{ y }}px;width:{{ d }}px;height:{{ d }}px">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 80" width="100%" height="100%"><path fill="{{ color }}" d="M0 80V44C0 18 14 3 40 0l4 10C30 14 23 22 22 36h20v44H0zm56 0V44C56 18 70 3 96 0l4 10C86 14 79 22 78 36h20v44H56z"/></svg></div>
{%- endmacro %}

{% macro pie(handle, logo, t) -%}
{%- if handle -%}
{{ texto("handle", "Usuario", 80, 1258, 600, 28, handle, campo="handle", anclaje="bottom", color=t.suave, extra="font-weight:600;line-height:1.2;") }}
{%- endif -%}
{%- if logo -%}
<div data-tipo="image" data-id="logo" data-nombre="Logo" data-campo="logo" data-anclaje="bottom" style="left:920px;top:1230px;width:80px;height:80px;background-image:url('{{ logo }}');background-size:contain;background-position:center;background-repeat:no-repeat;border-radius:0px"></div>
{%- endif -%}
{%- endmacro %}

{% macro grano() -%}
<div data-aplanar style="position:absolute;inset:0;opacity:0.18;mix-blend-mode:multiply;background-image:url(&quot;data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>&quot;)"></div>
{%- endmacro %}
```

Los `span` de acento leen `var(--acento)`, que define la regla `.card` de `_base.html.j2`. `extraer.py` lee el color computado y lo tokeniza, así que la variable CSS no llega a la escena.

- [ ] **Step 5: kind mínimo `side` y esquema de `compare` para que pase esta prueba**

Se crean ahora los archivos del Task 4 para `side` y `compare` con el contenido **completo** que da el Task 4, Steps 2 y 3. El Task 4 solo agrega su prueba.

- [ ] **Step 6: verde, lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_kinds_infra.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/plantillas/kinds tests/test_kinds_infra.py
git commit -m "feat(kinds): esquemas, validador, tokens, fuentes, parciales y base Jinja" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Esperado: `7 passed`.

---

## Task 4: kinds lote A (side, stat, vs, compare, list, cta)

**Files:**
- Create: `src/plantillas/kinds/{side,stat,vs,compare,list,cta}.schema.json`
- Create: `src/plantillas/kinds/{side,stat,vs,compare,list,cta}.html.j2`
- Create: `tests/fixtures/kinds/{side,stat,vs,compare,list,cta}.json`
- Test: `tests/test_kinds.py`

- [ ] **Step 1: prueba que falla, compartida por los lotes A y B**

`tests/test_kinds.py`:

```python
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.plantillas import kinds

FIX = Path(__file__).parent / "fixtures" / "kinds"
DISPONIBLES = sorted(p.stem for p in FIX.glob("*.json"))
FUENTES = {"titulo": "Poppins-Bold", "texto": "Poppins-SemiBold"}


def _marca():
    return SimpleNamespace(id=1, slug="prueba", nombre="Prueba", ig_handle="prueba",
                           color_marca="#7A4CFF", voz="", fuentes=[], formatos=["4x5"],
                           estilos={}, logo_path=None, activa=True, prompts={})


def _asset(slot):
    return {"src": f"file:///tmp/{slot}.png", "archivo": f"assets/{slot}.png",
            "fuente_asset": {"proveedor": "prueba", "autor": None, "licencia": None,
                             "url": None, "ig_handle": None}}


def render_fixture(kind):
    spec = kinds.validar_spec(kind, json.loads((FIX / f"{kind}.json").read_text())["spec"])
    assets = {s["id"]: _asset(s["id"]) for s in kinds.slots(kind, spec)}
    return spec, kinds.render(kind, spec, tokens=kinds.tokens_de(_marca(), spec["tema"]),
                              fuentes=FUENTES, assets=assets, handle="@prueba")


@pytest.mark.parametrize("kind", DISPONIBLES)
def test_fixture_renderiza(kind):
    _, html = render_fixture(kind)
    ids = re.findall(r'data-id="([^"]+)"', html)
    assert "titulo" in ids or kind == "meme"
    assert len(ids) == len(set(ids)), f"ids repetidos en {kind}"
    for i in ids:
        assert re.fullmatch(r"[a-z][a-z0-9_-]{0,24}", i), i
    assert "{{" not in html
    assert "box-shadow" not in html and "text-shadow" not in html
    # El DSL exige coordenadas explícitas en cada capa.
    for estilo in re.findall(r'data-tipo="[a-z]+"[^>]*style="([^"]*)"', html):
        assert "left:" in estilo and "top:" in estilo and "width:" in estilo


@pytest.mark.parametrize("kind", DISPONIBLES)
def test_requeridos_propios(kind):
    req = set(kinds.esquema(kind)["required"]) - {"titulo"}
    spec = json.loads((FIX / f"{kind}.json").read_text())["spec"]
    for r in req:
        incompleto = {k: v for k, v in spec.items() if k != r}
        with pytest.raises(kinds.SpecInvalido, match=r):
            kinds.validar_spec(kind, incompleto)


def test_estan_todos_los_del_lote_a():
    assert {"side", "stat", "vs", "compare", "list", "cta"} <= set(DISPONIBLES)
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_kinds.py -q
```

Esperado: falla `test_estan_todos_los_del_lote_a`.

- [ ] **Step 2: `side`, foto a un lado y texto al otro**

`src/plantillas/kinds/side.schema.json`:

```json
{
  "description": "Foto a media página de un lado y texto del otro. Para presentar un tema, un servicio o una persona.",
  "properties": {
    "lado": {"type": "string", "enum": ["izq", "der"], "default": "der", "description": "lado de la foto"}
  },
  "x-slots": [{"id": "imagen", "requerido": true}]
}
```

`src/plantillas/kinds/side.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% set posiciones_sticker = [(560, 1000, -6), (70, 940, 5), (560, 80, 6)] %}
{% block capas %}
{% set izq = spec.lado == "izq" %}
{% set tx = 600 if izq else 80 %}
{{ p.foto("imagen", a.imagen, 0 if izq else 540, 0, 540, 1350, campo="imagen") }}
{% if spec.etiqueta %}{{ p.pill("etiqueta", spec.etiqueta, tx, 120, 400, t) }}{% endif %}
{{ p.texto("titulo", "Título", tx, 230, 400, 72, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo", anclaje="center") }}
{% if spec.bajada %}{{ p.texto("bajada", "Bajada", tx, 700, 400, 32, spec.bajada, clase="bajada", campo="bajada") }}{% endif %}
{% if spec.cta %}{{ p.caja("cta", "Botón", tx, 1110, 400, 84, spec.cta, t.acento, t.sobre_acento, size=30, padding=16) }}{% endif %}
{% endblock %}
```

`tests/fixtures/kinds/side.json`:

```json
{"spec": {"titulo": ["Tu ciclo", "también habla"], "acento": "habla", "etiqueta": "Salud hormonal",
          "bajada": "Escúchalo con una ginecóloga en línea, sin salir de casa.", "cta": "Agenda hoy",
          "stickers": [{"texto": "Nuevo"}]}}
```

- [ ] **Step 3: `compare`, varios productos contra una oferta**

`src/plantillas/kinds/compare.schema.json`:

```json
{
  "description": "Varios productos sueltos con su precio contra una oferta que los incluye. Para mostrar ahorro.",
  "properties": {
    "titulo": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 40}},
    "items": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "object", "additionalProperties": false, "required": ["nombre", "precio"],
              "properties": {"nombre": {"type": "string", "minLength": 1, "maxLength": 24}, "precio": {"type": "string", "minLength": 1, "maxLength": 12}}}},
    "oferta": {"type": "object", "additionalProperties": false, "required": ["nombre", "precio"],
               "properties": {"nombre": {"type": "string", "minLength": 1, "maxLength": 32}, "precio": {"type": "string", "minLength": 1, "maxLength": 12}}}
  },
  "required": ["items", "oferta"],
  "x-slots": [{"id": "item", "por": "items", "recorte": true, "requerido": true}]
}
```

`src/plantillas/kinds/compare.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% set posiciones_sticker = [(780, 70, 8), (60, 1110, -5), (760, 1110, 4)] %}
{% block capas %}
{% if spec.etiqueta %}{{ p.pill("etiqueta", spec.etiqueta, 80, 80, 400, t) }}{% endif %}
{{ p.texto("titulo", "Título", 80, 170, 920, 70, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo", anclaje="top") }}
{% set n = spec["items"]|length %}
{% set ancho = (920 - (n - 1) * 24) // n %}
{% for it in spec["items"] %}
{% set x = 80 + loop.index0 * (ancho + 24) %}
{{ p.shape("panel_" ~ loop.index0, "Panel", x, 360, ancho, 420, t.panel, "32px") }}
{{ p.recorte("item_" ~ loop.index0, a["item_" ~ loop.index0], x + 20, 380, ancho - 40, 250, nombre=it.nombre) }}
{{ p.texto("nombre_" ~ loop.index0, "Nombre", x + 16, 650, ancho - 32, 26, it.nombre, alinea="center", extra="font-weight:600;line-height:1.2;") }}
{{ p.coin("precio_" ~ loop.index0, it.precio, x + ancho // 2 - 60, 720, 120, t.destacado, t.sobre_destacado, size=30) }}
{% endfor %}
{{ p.shape("oferta_fondo", "Oferta", 80, 880, 920, 300, t.acento, "40px") }}
{{ p.texto("oferta_nombre", "Oferta", 130, 930, 560, 44, spec.oferta.nombre, clase="titulo", color=t.sobre_acento, valign="center") }}
{{ p.coin("oferta_precio", spec.oferta.precio, 760, 910, 200, t.destacado, t.sobre_destacado, size=48) }}
{% if spec.bajada %}{{ p.texto("bajada", "Bajada", 130, 1060, 600, 28, spec.bajada, clase="bajada", campo="bajada", color=t.sobre_acento) }}{% endif %}
{% endblock %}
```

> ⚠️ `spec["items"]` y no `spec.items`: en Jinja `spec.items` es el método `dict.items`.

`tests/fixtures/kinds/compare.json`:

```json
{"spec": {"titulo": ["Por separado", "te sale caro"], "acento": "caro",
          "items": [{"nombre": "Consulta", "precio": "$600"}, {"nombre": "Laboratorio", "precio": "$900"}, {"nombre": "Seguimiento", "precio": "$400"}],
          "oferta": {"nombre": "Todo en Daisies", "precio": "$399"},
          "bajada": "Consulta, estudios y seguimiento por chat."}}
```

- [ ] **Step 4: `stat`, una cifra grande**

`src/plantillas/kinds/stat.schema.json`:

```json
{
  "description": "Una cifra enorme con su contexto. Para datos duros: porcentajes, conteos, precios.",
  "properties": {
    "cifra": {"type": "string", "minLength": 1, "maxLength": 8, "description": "lo que va enorme: 7 de 10, 82%, $399"},
    "unidad": {"type": "string", "maxLength": 20},
    "fuente": {"type": "string", "maxLength": 80, "description": "de dónde sale la cifra"}
  },
  "required": ["cifra"],
  "x-slots": []
}
```

`src/plantillas/kinds/stat.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% block capas %}
{{ p.flor("flor", 760, -80, 380, t.panel, t.destacado) }}
{% if spec.etiqueta %}{{ p.pill("etiqueta", spec.etiqueta, 80, 100, 420, t) }}{% endif %}
{{ p.texto("cifra", "Cifra", 60, 220, 960, 300, spec.cifra, clase="titulo", color=t.acento, extra="line-height:1;white-space:nowrap;") }}
{% if spec.unidad %}{{ p.texto("unidad", "Unidad", 80, 540, 920, 48, spec.unidad, clase="titulo", color=t.suave) }}{% endif %}
{{ p.texto("titulo", "Título", 80, 640, 920, 64, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo", anclaje="center") }}
{% if spec.bajada %}{{ p.texto("bajada", "Bajada", 80, 960, 860, 32, spec.bajada, clase="bajada", campo="bajada") }}{% endif %}
{% if spec.fuente %}{{ p.texto("fuente", "Fuente", 80, 1190, 860, 22, "Fuente: " ~ spec.fuente, color=t.suave, anclaje="bottom", extra="line-height:1.3;") }}{% endif %}
{% endblock %}
```

`tests/fixtures/kinds/stat.json`:

```json
{"spec": {"cifra": "7 de 10", "unidad": "mujeres", "titulo": ["no saben qué es", "el SOP"], "acento": "SOP",
          "bajada": "Y es una de las causas más comunes de reglas irregulares.", "fuente": "OMS 2023", "tema": "oscuro"}}
```

- [ ] **Step 5: `vs`, ellos contra nosotros**

`src/plantillas/kinds/vs.schema.json`:

```json
{
  "description": "Dos columnas: la opción común (ellos) contra la de la marca (nosotros). Para diferenciarse.",
  "properties": {
    "titulo": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 40}},
    "ellos": {"type": "object", "additionalProperties": false, "required": ["nombre", "puntos"],
              "properties": {"nombre": {"type": "string", "minLength": 1, "maxLength": 20},
                             "puntos": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "minLength": 1, "maxLength": 36}}}},
    "nosotros": {"type": "object", "additionalProperties": false, "required": ["nombre", "puntos"],
                 "properties": {"nombre": {"type": "string", "minLength": 1, "maxLength": 20},
                                "puntos": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "minLength": 1, "maxLength": 36}}}}
  },
  "required": ["ellos", "nosotros"],
  "x-slots": []
}
```

`src/plantillas/kinds/vs.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% block capas %}
{{ p.texto("titulo", "Título", 80, 100, 920, 68, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo", alinea="center") }}
{{ p.shape("ellos_fondo", "Ellos", 60, 330, 470, 820, t.panel, "36px") }}
{{ p.shape("nosotros_fondo", "Nosotros", 550, 330, 470, 820, t.acento, "36px") }}
{{ p.texto("ellos_nombre", "Ellos", 100, 380, 390, 40, spec.ellos.nombre, clase="titulo", alinea="center", color=t.suave) }}
{{ p.texto("nosotros_nombre", "Nosotros", 590, 380, 390, 40, spec.nosotros.nombre, clase="titulo", alinea="center", color=t.sobre_acento) }}
{% for x in spec.ellos.puntos %}{{ p.texto("ellos_" ~ loop.index0, "Punto", 100, 500 + loop.index0 * 150, 390, 30, "– " ~ x, color=t.suave, extra="line-height:1.25;font-weight:600;") }}{% endfor %}
{% for x in spec.nosotros.puntos %}{{ p.texto("nosotros_" ~ loop.index0, "Punto", 590, 500 + loop.index0 * 150, 390, 30, "+ " ~ x, color=t.sobre_acento, extra="line-height:1.25;font-weight:600;") }}{% endfor %}
{{ p.coin("vs", "VS", 480, 300, 120, t.destacado, t.sobre_destacado, size=40) }}
{% endblock %}
```

`tests/fixtures/kinds/vs.json`:

```json
{"spec": {"titulo": ["Clínica vs", "Daisies"], "acento": "Daisies",
          "ellos": {"nombre": "Clínica", "puntos": ["Semanas para cita", "Sala de espera", "Pagas cada visita"]},
          "nosotros": {"nombre": "Daisies", "puntos": ["Cita hoy", "Desde tu cama", "Seguimiento incluido"]}}}
```

- [ ] **Step 6: `list`, lista numerada**

`src/plantillas/kinds/list.schema.json`:

```json
{
  "description": "Título y de 3 a 6 puntos numerados. Para tips, pasos, razones o señales.",
  "properties": {
    "titulo": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 40}},
    "items": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "string", "minLength": 1, "maxLength": 60}}
  },
  "required": ["items"],
  "x-slots": []
}
```

`src/plantillas/kinds/list.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% set posiciones_sticker = [(780, 80, 8), (760, 1150, -5), (60, 1150, 4)] %}
{% block capas %}
{% if spec.etiqueta %}{{ p.pill("etiqueta", spec.etiqueta, 80, 80, 400, t) }}{% endif %}
{{ p.texto("titulo", "Título", 80, 170, 920, 68, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo") }}
{% set n = spec["items"]|length %}
{% set paso = 760 // n %}
{% for it in spec["items"] %}
{% set y = 360 + loop.index0 * paso %}
{{ p.coin("num_" ~ loop.index0, loop.index|string, 80, y, 84, t.acento, t.sobre_acento, size=36) }}
{{ p.texto("item_" ~ loop.index0, "Punto", 196, y + 4, 800, 34, it, valign="center", extra="line-height:1.25;font-weight:600;") }}
{% endfor %}
{% endblock %}
```

`tests/fixtures/kinds/list.json`:

```json
{"spec": {"titulo": ["5 señales de que", "tu regla no es normal"], "acento": "no es normal",
          "items": ["Dura más de 7 días", "Cambias toalla cada hora", "Te duele hasta faltar", "Llega cada 2 semanas", "Coágulos grandes"]}}
```

- [ ] **Step 7: `cta`, llamado a la acción**

`src/plantillas/kinds/cta.schema.json`:

```json
{
  "description": "Cierre con llamado a la acción grande. Opcional: pantalla de la app en un teléfono.",
  "properties": {
    "cta": {"type": "string", "minLength": 1, "maxLength": 40},
    "con_telefono": {"type": "boolean", "default": false}
  },
  "required": ["cta"],
  "x-slots": [{"id": "pantalla", "requerido_si": "con_telefono"}]
}
```

`src/plantillas/kinds/cta.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% set posiciones_sticker = [(90, 90, -7), (740, 90, 6), (90, 1120, 4)] %}
{% block capas %}
{{ p.flor("flor_a", -90, 980, 360, t.panel, t.destacado) }}
{{ p.flor("flor_b", 820, 380, 300, t.panel, t.acento) }}
{% if spec.con_telefono and a.pantalla %}
{{ p.texto("titulo", "Título", 80, 200, 500, 72, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo", anclaje="center") }}
{% if spec.bajada %}{{ p.texto("bajada", "Bajada", 80, 640, 480, 32, spec.bajada, clase="bajada", campo="bajada") }}{% endif %}
{{ p.telefono("pantalla", a.pantalla, 620, 170, 380, 780, t) }}
{{ p.caja("cta", "Botón", 80, 1040, 920, 110, spec.cta, t.acento, t.sobre_acento, size=40, padding=20) }}
{% else %}
{{ p.texto("titulo", "Título", 80, 300, 920, 88, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo", alinea="center", anclaje="center") }}
{% if spec.bajada %}{{ p.texto("bajada", "Bajada", 140, 760, 800, 34, spec.bajada, clase="bajada", campo="bajada", alinea="center") }}{% endif %}
{{ p.caja("cta", "Botón", 190, 980, 700, 120, spec.cta, t.acento, t.sobre_acento, size=44, padding=20) }}
{% endif %}
{% endblock %}
```

`tests/fixtures/kinds/cta.json`:

```json
{"spec": {"titulo": ["Tu primera consulta", "por $350"], "acento": "$350", "cta": "Descarga Daisies",
          "bajada": "Ginecóloga en línea hoy mismo.", "tema": "marca", "grano": true}}
```

- [ ] **Step 8: verde, lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_kinds.py tests/test_kinds_infra.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/plantillas/kinds tests/fixtures/kinds tests/test_kinds.py
git commit -m "feat(kinds): lote A side, stat, vs, compare, list y cta" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Esperado: todo verde. `test_requeridos_propios` corre sobre los 6 kinds.

---

## Task 5: kinds lote B (meme, historia, cita, propiedad)

**Files:**
- Create: `src/plantillas/kinds/{meme,historia,cita,propiedad}.schema.json`
- Create: `src/plantillas/kinds/{meme,historia,cita,propiedad}.html.j2`
- Create: `tests/fixtures/kinds/{meme,historia,cita,propiedad}.json`
- Modify: `tests/test_kinds.py` (agregar la prueba del lote B)

- [ ] **Step 1: prueba que falla**

Se agrega a `tests/test_kinds.py`:

```python
def test_estan_todos():
    assert set(DISPONIBLES) == set(kinds.KINDS)


def test_meme_usa_anton():
    f = kinds.fuentes_de(_marca(), {"Anton-Regular", "Poppins-Bold", "Poppins-SemiBold"}, "meme")
    assert f["titulo"] == "Anton-Regular"
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_kinds.py -q -k "todos or anton"
```

Esperado: falla `test_estan_todos`.

- [ ] **Step 2: `meme`**

`src/plantillas/kinds/meme.schema.json`:

```json
{
  "description": "Meme. impact = foto a sangre con texto arriba y abajo en mayúsculas; tweet = captura tipo publicación con texto e imagen. El título es el texto de arriba (impact) o el texto del post (tweet).",
  "properties": {
    "estilo": {"type": "string", "enum": ["impact", "tweet"], "default": "impact"},
    "abajo": {"type": "string", "maxLength": 80, "description": "texto de abajo (solo impact)"}
  },
  "x-slots": [{"id": "imagen", "requerido": true}]
}
```

`src/plantillas/kinds/meme.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% block capas %}
{% if spec.estilo == "impact" %}
{{ p.foto("imagen", a.imagen, 0, 0, 1080, 1350, campo="imagen") }}
{{ p.shape("banda_arriba", "Banda", 0, 0, 1080, 330, "rgba(0,0,0,0.35)") }}
{{ p.texto("titulo", "Arriba", 60, 50, 960, 96, spec.titulo|join("<br>"|safe), clase="titulo", alinea="center", color="#FFFFFF", extra="text-transform:uppercase;line-height:1.05;letter-spacing:0em;") }}
{% if spec.abajo %}
{{ p.shape("banda_abajo", "Banda", 0, 1020, 1080, 330, "rgba(0,0,0,0.35)") }}
{{ p.texto("abajo", "Abajo", 60, 1060, 960, 96, spec.abajo, clase="titulo", alinea="center", color="#FFFFFF", anclaje="bottom", extra="text-transform:uppercase;line-height:1.05;letter-spacing:0em;") }}
{% endif %}
{% else %}
{{ p.shape("tarjeta", "Tarjeta", 60, 140, 960, 1060, t.panel, "40px") }}
{{ p.shape("avatar", "Avatar", 110, 190, 96, 96, t.acento, "50%") }}
{{ p.texto("autor", "Autor", 230, 200, 700, 34, handle or "@marca", extra="font-weight:700;line-height:1.2;") }}
{{ p.texto("titulo", "Post", 110, 330, 860, 44, spec.titulo|join("<br>"|safe), extra="font-weight:600;line-height:1.25;") }}
{{ p.foto("imagen", a.imagen, 110, 600, 860, 540, campo="imagen", radio="28px") }}
{% endif %}
{% endblock %}
```

> ⚠️ `join("<br>"|safe)` con autoescape: Jinja escapa cada línea y conserva el `<br>` crudo. La prueba `test_render_strict_y_escapa` cubre el escape del contenido.

`tests/fixtures/kinds/meme.json`:

```json
{"spec": {"titulo": ["Cuando dices", "\"seguro no es nada\""], "abajo": "y era SOP", "estilo": "impact"}}
```

- [ ] **Step 3: `historia`, una sola lámina**

`src/plantillas/kinds/historia.schema.json`:

```json
{
  "description": "Historia corta en una sola lámina: título y de 1 a 3 párrafos, con foto opcional arriba. Para testimonios o casos.",
  "properties": {
    "titulo": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 40}},
    "parrafos": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string", "minLength": 1, "maxLength": 280}},
    "con_foto": {"type": "boolean", "default": true}
  },
  "required": ["parrafos"],
  "x-slots": [{"id": "imagen", "requerido_si": "con_foto"}]
}
```

`src/plantillas/kinds/historia.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% set posiciones_sticker = [(760, 60, 6), (60, 60, -6), (760, 1150, 4)] %}
{% block capas %}
{% set y0 = 80 %}
{% if spec.con_foto and a.imagen %}
{{ p.foto("imagen", a.imagen, 80, 80, 920, 420, campo="imagen", radio="36px") }}
{% set y0 = 540 %}
{% endif %}
{{ p.texto("titulo", "Título", 80, y0, 920, 60, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo") }}
{% set alto = 220 if spec.con_foto and a.imagen else 300 %}
{% for par in spec.parrafos %}
{{ p.texto("parrafo_" ~ loop.index0, "Párrafo", 80, y0 + 160 + loop.index0 * alto, 920, 28 if spec.con_foto and a.imagen else 32, par, color=t.suave, extra="line-height:1.4;font-weight:600;") }}
{% endfor %}
{% endblock %}
```

`tests/fixtures/kinds/historia.json`:

```json
{"spec": {"titulo": ["Ana tardó 3 años", "en su diagnóstico"], "acento": "3 años",
          "parrafos": ["Fue a cuatro consultas. En todas le dijeron que era estrés.",
                       "En Daisies le pidieron un ultrasonido el primer día. Era endometriosis.",
                       "Hoy tiene tratamiento y seguimiento por chat."]}}
```

- [ ] **Step 4: `cita`**

`src/plantillas/kinds/cita.schema.json`:

```json
{
  "description": "Frase textual de una persona con su nombre y rol. El título ES la cita, partida en líneas.",
  "properties": {
    "autor": {"type": "string", "minLength": 1, "maxLength": 40},
    "rol": {"type": "string", "maxLength": 60},
    "con_retrato": {"type": "boolean", "default": false}
  },
  "required": ["autor"],
  "x-slots": [{"id": "retrato", "requerido_si": "con_retrato"}]
}
```

`src/plantillas/kinds/cita.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% block capas %}
{{ p.comillas("comillas", 80, 120, 160, t.acento) }}
{{ p.texto("titulo", "Cita", 80, 330, 920, 64, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo", anclaje="center") }}
{% set xa = 80 %}
{% if spec.con_retrato and a.retrato %}
{{ p.foto("retrato", a.retrato, 80, 960, 150, 150, nombre="Retrato", radio="50%") }}
{% set xa = 260 %}
{% endif %}
{{ p.texto("autor", "Autor", xa, 980, 700, 40, spec.autor, clase="titulo", anclaje="bottom") }}
{% if spec.rol %}{{ p.texto("rol", "Rol", xa, 1040, 700, 28, spec.rol, color=t.suave, anclaje="bottom", extra="line-height:1.3;font-weight:600;") }}{% endif %}
{% endblock %}
```

`tests/fixtures/kinds/cita.json`:

```json
{"spec": {"titulo": ["\"El dolor menstrual", "fuerte no es normal.", "Es una señal.\""], "acento": "Es una señal.",
          "autor": "Dra. Laura Méndez", "rol": "Ginecóloga, Daisies", "tema": "oscuro"}}
```

- [ ] **Step 5: `propiedad`, inmobiliaria**

`src/plantillas/kinds/propiedad.schema.json`:

```json
{
  "description": "Ficha de inmueble: foto grande, precio, ubicación (etiqueta) y hasta 4 datos cortos.",
  "properties": {
    "titulo": {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string", "minLength": 1, "maxLength": 40}},
    "precio": {"type": "string", "minLength": 1, "maxLength": 20},
    "datos": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string", "minLength": 1, "maxLength": 24}}
  },
  "required": ["precio", "datos"],
  "x-slots": [{"id": "imagen", "requerido": true}]
}
```

`src/plantillas/kinds/propiedad.html.j2`:

```jinja
{% extends "_base.html.j2" %}
{% import "_parciales.html.j2" as p %}
{% set posiciones_sticker = [(780, 60, 7), (60, 60, -6), (780, 640, 5)] %}
{% block capas %}
{{ p.foto("imagen", a.imagen, 0, 0, 1080, 760, campo="imagen") }}
{% if spec.etiqueta %}{{ p.pill("etiqueta", spec.etiqueta, 60, 680, 420, t, color="profundo", fg=t.sobre_profundo) }}{% endif %}
{{ p.texto("titulo", "Título", 60, 800, 640, 56, p.texto_con_acento(spec.titulo, spec.acento), clase="titulo") }}
{{ p.caja("precio", "Precio", 720, 800, 300, 110, spec.precio, t.acento, t.sobre_acento, size=40, radio="28px", peso=700, padding=16) }}
{% for d in spec.datos %}
{{ p.caja("dato_" ~ loop.index0, "Dato", 60 + (loop.index0 % 2) * 470, 980 + (loop.index0 // 2) * 100, 450, 80, d, t.panel, t.tinta, size=26, radio="20px", padding=12) }}
{% endfor %}
{% endblock %}
```

`tests/fixtures/kinds/propiedad.json`:

```json
{"spec": {"titulo": ["Depa con terraza", "en Providencia"], "acento": "terraza", "precio": "$4.2 M",
          "etiqueta": "Guadalajara, Jal.", "datos": ["2 recámaras", "2 baños", "98 m²", "1 cajón"]}}
```

- [ ] **Step 6: verde, lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_kinds.py tests/test_kinds_infra.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/plantillas/kinds tests/fixtures/kinds tests/test_kinds.py
git commit -m "feat(kinds): lote B meme, historia, cita y propiedad" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: `src/plantillas/extraer.py`, del HTML del kind a la escena v2

**Files:**
- Create: `src/plantillas/extraer.py`
- Test: `tests/test_extraer.py` (unitarias puras y round-trip `lento`)

**Interfaces:**

```python
def extraer(html: str, *, slug: str, tokens: dict[str, str], fuente: str) -> tuple[bytes, dict, dict]
# png del kind, escena v2 (formato 4x5), muestras {campo: texto | uri}
def a_escena(datos: dict, *, slug: str, tokens: dict, fuente: str, fondo_png: bytes | None) -> tuple[dict, dict]
```

- [ ] **Step 1: pruebas unitarias que fallan, sin navegador**

`tests/test_extraer.py`:

```python
import json
from pathlib import Path

import pytest

from src.plantillas import extraer

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
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_extraer.py -q
```

Esperado: `ImportError`.

- [ ] **Step 2: implementar**

`src/plantillas/extraer.py`:

```python
"""Del HTML de un kind a una escena v2: el navegador mide, Python traduce.

Ver el DSL en `plantillas/kinds/__init__.py` (data-tipo, data-id, ...).
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

from .. import compose
from ..assets import biblioteca

W, H = 1080, 1350
_RGB = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
_CLAVES_FUENTE = ("proveedor", "autor", "licencia", "url", "ig_handle")
_ALINEA = {"start": "left", "left": "left", "center": "center", "end": "right", "right": "right",
           "justify": "left"}

_JS = r"""
() => {
  const card = document.querySelector('.card');
  const base = card.getBoundingClientRect();
  const rotDe = (tf) => {
    if (!tf || tf === 'none') return 0;
    const m = new DOMMatrix(tf);
    return Math.round(Math.atan2(m.b, m.a) * 18000 / Math.PI) / 100;
  };
  const PROPS = ['fontFamily','fontSize','fontWeight','lineHeight','letterSpacing','color',
    'textAlign','textTransform','whiteSpace','backgroundColor','backgroundSize',
    'backgroundPosition','borderTopLeftRadius','borderTopWidth','borderTopStyle',
    'borderTopColor','filter','mixBlendMode','paddingTop','paddingRight','paddingBottom',
    'paddingLeft'];
  const textoDe = (el) => {
    let texto = '';
    const spans = [];
    const walk = (n) => {
      for (const c of n.childNodes) {
        if (c.nodeType === 3) texto += c.nodeValue.replace(/[ \t\r\n]+/g, ' ');
        else if (c.nodeName === 'BR') texto += '\n';
        else if (c.dataset && c.dataset.acento !== undefined) {
          const desde = texto.length;
          walk(c);
          spans.push({desde, hasta: texto.length, color: getComputedStyle(c).color});
        } else walk(c);
      }
    };
    walk(el);
    return {texto, spans};
  };
  const limpiarSvg = (svg) => {
    const copia = svg.cloneNode(true);
    for (const n of [copia, ...copia.querySelectorAll('*')]) {
      for (const a of [...n.attributes]) {
        if (a.name.startsWith('data-') || a.name === 'class' || a.name === 'style') n.removeAttribute(a.name);
      }
    }
    return copia.outerHTML;
  };
  const capas = [];
  for (const el of card.querySelectorAll(':scope > [data-tipo]')) {
    const cs = getComputedStyle(el);
    const rot = rotDe(cs.transform);
    const previo = el.style.transform;
    el.style.transform = 'none';
    const r = el.getBoundingClientRect();
    el.style.transform = previo;
    const d = el.dataset;
    const estilo = {};
    for (const p of PROPS) estilo[p] = cs[p];
    estilo.textWrapMode = cs.getPropertyValue('text-wrap-mode') || 'wrap';
    estilo.textWrapStyle = cs.getPropertyValue('text-wrap-style') || 'auto';
    const bg = cs.backgroundImage.match(/url\("?(.*?)"?\)/);
    const capa = {tipo: d.tipo, id: d.id, nombre: d.nombre || d.id, campo: d.campo || null,
      anclaje: d.anclaje || null, valign: d.valign || 'top',
      x: r.left - base.left, y: r.top - base.top, w: r.width, h: r.height, rot,
      opacity: parseFloat(cs.opacity), src: d.src || null, srcUrl: bg ? bg[1] : null,
      recorte: d.recorte !== undefined,
      fuenteAsset: d.fuenteAsset ? JSON.parse(d.fuenteAsset) : null,
      texto: null, spans: null, svg: null, cs: estilo};
    if (d.tipo === 'text' || d.tipo === 'caja') Object.assign(capa, textoDe(el));
    if (d.tipo === 'svg') capa.svg = limpiarSvg(el.querySelector('svg'));
    capas.push(capa);
  }
  return {fondo: {color: getComputedStyle(card).backgroundColor,
                  aplanar: !!card.querySelector('[data-aplanar]')}, capas};
}
"""

_OCULTAR = "() => { for (const el of document.querySelectorAll('.card > [data-tipo]')) el.style.visibility = 'hidden'; }"


# ---------- colores ----------

def css_a_color(css: str | None) -> str | None:
    m = _RGB.fullmatch((css or "").strip())
    if not m:
        return None
    r, g, b = (round(float(v)) for v in m.groups()[:3])
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    if a <= 0.001:
        return None
    if a >= 0.999:
        return f"#{r:02x}{g:02x}{b:02x}"
    return f"rgba({r},{g},{b},{round(a, 3):g})"


def _normal(valor: str) -> str:
    v = valor.strip().lower()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"#{h}"
    return css_a_color(v) or v


def tokenizar(color: str | None, tokens: dict[str, str]) -> str | None:
    if color is None:
        return None
    for nombre, valor in tokens.items():
        if _normal(valor) == color:
            return f"token:{nombre}"
    return color


# ---------- medidas ----------

def _px(v: str | None) -> float:
    try:
        return float(str(v).removesuffix("px"))
    except ValueError:
        return 0.0


def anclaje_por_tercio(y: float, h: float) -> str:
    centro = y + h / 2
    if centro < H / 3:
        return "top"
    if centro > 2 * H / 3:
        return "bottom"
    return "center"


def _comunes(c: dict, z: int, *, x=None, y=None, w=None, h=None, cid=None, nombre=None) -> dict:
    x = c["x"] if x is None else x
    y = c["y"] if y is None else y
    w = c["w"] if w is None else w
    h = c["h"] if h is None else h
    capa = {"id": cid or c["id"], "nombre": (nombre or c["nombre"] or c["id"])[:80],
            "x": round(x), "y": round(y),
            "w": max(1, math.ceil(w - 0.01)), "h": max(1, math.ceil(h - 0.01)),
            "rot": float(c["rot"] or 0), "opacity": round(float(c["opacity"]), 3), "z": z,
            "bloqueada": False, "oculta": False,
            "anclaje": c["anclaje"] or anclaje_por_tercio(y, h)}
    if c.get("campo"):
        capa["campo"] = c["campo"]
    return capa


def _estilo_texto(cs: dict, tokens: dict, valign: str) -> dict:
    fs = _px(cs["fontSize"]) or 16.0
    lh = cs["lineHeight"]
    lh = round(_px(lh) / fs, 3) if str(lh).endswith("px") else 1.2
    peso = min(900, max(100, int(round(int(float(cs["fontWeight"])) / 100) * 100)))
    estilo: dict[str, Any] = {
        "fontFamily": cs["fontFamily"].split(",")[0].strip().strip("'\""),
        "fontSize": round(fs), "fontWeight": peso, "lineHeight": min(3.0, max(0.8, lh)),
        "color": tokenizar(css_a_color(cs["color"]), tokens) or "#000000",
        "textAlign": _ALINEA.get(cs["textAlign"], "left"),
        "textTransform": "uppercase" if cs["textTransform"] == "uppercase" else "none",
        "verticalAlign": valign if valign in ("top", "center", "bottom") else "top",
    }
    if cs.get("whiteSpace") == "nowrap" or cs.get("textWrapMode") == "nowrap":
        estilo["textWrap"] = "nowrap"
    elif cs.get("textWrapStyle") in ("balance", "pretty"):
        estilo["textWrap"] = cs["textWrapStyle"]
    else:
        estilo["textWrap"] = "wrap"
    ls = cs.get("letterSpacing", "normal")
    if str(ls).endswith("px") and _px(ls) != 0:
        estilo["letterSpacing"] = f"{_px(ls) / fs:.3f}em"
    return estilo


def _texto(c: dict, z: int, tokens: dict, **geo) -> dict:
    capa = _comunes(c, z, **geo)
    capa["tipo"] = "text"
    capa["texto"] = (c["texto"] or "").replace("{{", "{ {")[:1000]
    estilo = _estilo_texto(c["cs"], tokens, "center" if c["tipo"] == "caja" else c["valign"])
    if c.get("spans") and not c.get("campo"):
        estilo["spans"] = [{"desde": s["desde"], "hasta": s["hasta"],
                            "color": tokenizar(css_a_color(s["color"]), tokens)}
                           for s in c["spans"] if s["hasta"] > s["desde"]]
    capa["estilo"] = estilo
    return capa


def _radio(cs: dict, w: float, h: float) -> int:
    r = cs.get("borderTopLeftRadius", "0px")
    if str(r).endswith("%"):
        return round(min(w, h) / 2)
    return round(min(_px(r), h / 2, w / 2))


def _shape(c: dict, z: int, tokens: dict, **geo) -> dict:
    capa = _comunes(c, z, **geo)
    cs = c["cs"]
    capa["tipo"] = "shape"
    capa["forma"] = "ellipse" if str(cs["borderTopLeftRadius"]).endswith("%") else "rect"
    estilo: dict[str, Any] = {"fill": tokenizar(css_a_color(cs["backgroundColor"]), tokens)
                              or "rgba(0,0,0,0)"}
    if capa["forma"] == "rect":
        estilo["radius"] = _radio(cs, capa["w"], capa["h"])
    if cs.get("borderTopStyle") not in (None, "none") and _px(cs["borderTopWidth"]) > 0:
        estilo["borderWidth"] = round(_px(cs["borderTopWidth"]))
        estilo["borderColor"] = tokenizar(css_a_color(cs["borderTopColor"]), tokens)
    if cs.get("filter") not in (None, "none"):
        estilo["filter"] = cs["filter"]
    if cs.get("mixBlendMode") not in (None, "normal"):
        estilo["mixBlendMode"] = cs["mixBlendMode"]
    capa["estilo"] = estilo
    return capa


def _imagen(c: dict, z: int) -> dict:
    capa = _comunes(c, z)
    cs = c["cs"]
    capa["tipo"] = "image"
    capa["ajuste"] = "contain" if cs["backgroundSize"] == "contain" else "cover"
    radio = cs["borderTopLeftRadius"]
    if str(radio).endswith("%"):
        capa["mascara"] = "circle"
    elif _px(radio) > 0:
        capa["mascara"] = f"rounded:{round(_px(radio))}"
    else:
        capa["mascara"] = "none"
    capa["recorte"] = bool(c.get("recorte"))
    if c.get("src"):
        capa["src"] = c["src"]
    if c.get("fuenteAsset"):
        capa["fuente_asset"] = {k: (str(c["fuenteAsset"][k])[:500]
                                    if c["fuenteAsset"].get(k) is not None else None)
                                for k in _CLAVES_FUENTE}
    estilo = {"objectPosition": cs.get("backgroundPosition") or "50% 50%"}
    if cs.get("filter") not in (None, "none"):
        estilo["filter"] = cs["filter"]
    capa["estilo"] = estilo
    return capa


def _svg(c: dict, z: int, slug: str) -> dict:
    datos = c["svg"].encode("utf-8")
    nombre = hashlib.sha1(datos).hexdigest()[:16] + ".svg"
    destino = biblioteca.ruta_de(slug, nombre)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    capa = _comunes(c, z)
    capa.update({"tipo": "svg", "src": f"assets/{nombre}", "ajuste": "contain"})
    return capa


def a_escena(datos: dict, *, slug: str, tokens: dict, fuente: str,
             fondo_png: bytes | None) -> tuple[dict, dict]:
    capas: list[dict] = []
    muestras: dict[str, str] = {}
    for i, c in enumerate(datos["capas"]):
        z = (i + 1) * 10
        tipo = c["tipo"]
        if tipo == "text":
            capas.append(_texto(c, z, tokens))
        elif tipo == "caja":
            cs = c["cs"]
            pt, pr, pb, pl = (_px(cs[k]) for k in ("paddingTop", "paddingRight",
                                                   "paddingBottom", "paddingLeft"))
            capas.append(_shape(c, z, tokens, cid=f"{c['id']}_fondo",
                                nombre=f"{c['nombre']} (fondo)"))
            capas.append(_texto(c, z + 5, tokens, x=c["x"] + pl, y=c["y"] + pt,
                                w=c["w"] - pl - pr, h=c["h"] - pt - pb))
        elif tipo == "shape":
            capas.append(_shape(c, z, tokens))
        elif tipo == "image":
            capas.append(_imagen(c, z))
        elif tipo == "svg":
            capas.append(_svg(c, z, slug))
        else:
            raise ValueError(f"data-tipo desconocido: {tipo!r}")
        if c.get("campo"):
            muestras[c["campo"]] = c["texto"] if tipo in ("text", "caja") else (c.get("srcUrl") or "")
    if datos["fondo"]["aplanar"] and fondo_png:
        nombre = f"fondo_{uuid.uuid4().hex[:12]}.png"
        destino = biblioteca.ruta_de(slug, nombre)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(fondo_png)
        fondo = {"tipo": "imagen", "valor": f"assets/{nombre}"}
    else:
        fondo = {"tipo": "color",
                 "valor": tokenizar(css_a_color(datos["fondo"]["color"]), tokens) or "#ffffff"}
    escena = {"v": 2, "lienzo": {"w": W, "h": H, "formato": "4x5", "fondo": fondo},
              "tokens": {"colores": dict(tokens), "fuente": fuente}, "capas": capas}
    return escena, muestras


def _medir(html: str) -> tuple[bytes, dict, bytes | None]:
    from playwright.sync_api import sync_playwright

    compose.OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".html", dir=compose.OUT_DIR,
                                     delete=False, encoding="utf-8") as f:
        f.write(html)
        ruta = Path(f.name)
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch()
            try:
                pag = nav.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
                pag.goto(ruta.as_uri(), wait_until="networkidle")
                pag.evaluate("() => document.fonts.ready")
                card = pag.locator(".card")
                png = card.screenshot(type="png")
                datos = pag.evaluate(_JS)
                fondo_png = None
                if datos["fondo"]["aplanar"]:
                    pag.evaluate(_OCULTAR)
                    fondo_png = card.screenshot(type="png")
                return png, datos, fondo_png
            finally:
                nav.close()
    finally:
        ruta.unlink(missing_ok=True)


def extraer(html: str, *, slug: str, tokens: dict[str, str], fuente: str) -> tuple[bytes, dict, dict]:
    png, datos, fondo_png = _medir(html)
    escena, muestras = a_escena(datos, slug=slug, tokens=tokens, fuente=fuente, fondo_png=fondo_png)
    return png, escena, muestras


__all__ = ["extraer", "a_escena", "css_a_color", "tokenizar", "anclaje_por_tercio", "json"]
```

> ⚠️ `compose.OUT_DIR` existe según el resumen de `_screenshot_card`. Si el nombre es otro, se usa el que use `_screenshot_card`, para que el ruteo de sandbox (`file:` y `data:`) sea el mismo.

- [ ] **Step 3: verde de las unitarias**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_extraer.py -q -m "not lento"
```

Esperado: `7 passed`.

- [ ] **Step 4: prueba round-trip `lento`, con ≤1% de píxeles distintos**

Se agrega a `tests/test_extraer.py`:

```python
from types import SimpleNamespace

from PIL import Image, ImageChops

from src import db
from src.plantillas import contrato as contrato_mod
from src.plantillas import escena as escena_mod
from src.plantillas import fuentes_tipograficas, kinds
from src.plantillas import render as plantillas_render

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
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_extraer.py -q -m lento
```

- Esperado: `10 passed`.
- ⚠️ Antes de correr, se confirma que `plantillas_render.render` lee de la plantilla `html` y `contrato_json` (`render.py:51` y `:60`). Si exige más claves (`aspecto` u otras), se agregan al dict `plantilla`.
- Si un kind supera el 1%, se abre `tmp_path/<kind>_diff.png` y se ataca la causa, **no el umbral**. Las causas esperadas son:
  1. Un tamaño de fuente no entero en el kind.
  2. `nowrap` que corta distinto: subir `w` 2 px en `_texto` cuando `textWrap == "nowrap"`.
  3. Un `background-position` que `a_html` no traduce.

- [ ] **Step 5: lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/plantillas/extraer.py tests/test_extraer.py
git commit -m "feat(escena): extraer mide el kind en Chromium y lo traduce a capas v2, con round-trip ≤1%" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: `chat.crear`

**Files:**
- Create: `src/plantillas/chat.py`
- Test: `tests/test_chat_crear.py`

**Interfaces:**

```python
class ChatError(RuntimeError): ...
HERRAMIENTA_DISENAR: dict
HERRAMIENTA_REVISAR: dict
def contrato_de(escena: dict, formato: str) -> dict
def crear(cx, marca, mensaje: str, *, formato: str = "4x5", uso: list | None = None) -> tuple[dict, dict, dict]
```

**Flujo:**

1. `pedir_herramienta(disenar)` → `_pedir_valido`. Si `validar_spec` falla, o faltan consultas para slots requeridos, hay **un** reintento con el error en texto.
2. `_resolver_assets`: `buscar(n=5)` → `importar(cands[0])` → `quitar_fondo` si el slot es `recorte`.
3. `kinds.render` → `extraer.extraer`.
4. `pedir_herramienta(revisar, imagenes=[png])`. Si `ok=false` y trae un `spec` válido, se re-renderiza **una** vez sin volver a revisar.
5. `reformatear` si el formato no es `4x5`. Luego `contrato_de` y `escena.validar(familias=)`.

- [ ] **Step 1: prueba que falla**

`tests/test_chat_crear.py`:

```python
import json
from types import SimpleNamespace

import pytest

from src import db
from src.assets import Candidata
from src.plantillas import chat, escena as escena_mod, kinds


def _marca():
    return SimpleNamespace(id=1, slug="prueba", nombre="Prueba", ig_handle="prueba",
                           color_marca="#7A4CFF", voz="Cercana, directa.", fuentes=[],
                           formatos=["4x5"], estilos={}, logo_path=None, activa=True, prompts={})


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    respuestas: list[dict] = []
    pedidos: list[dict] = []

    def falso(**kw):
        pedidos.append(kw)
        if kw.get("uso") is not None:
            kw["uso"].append({"modelo": "falso", "entrada": 1, "salida": 1})
        return respuestas.pop(0)

    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", falso)
    buscadas: list[str] = []

    def buscar(cx_, aid, slug, q, *, tipo="imagen", proveedores=None, n=20):
        buscadas.append(q)
        return [Candidata(proveedor="pexels", id_origen="1", tipo="imagen", url="u",
                          preview_url="p", ancho=10, alto=10, autor="Ana",
                          licencia="Pexels", url_origen="https://pexels.com/1")]

    monkeypatch.setattr(chat.buscar, "buscar", buscar)
    monkeypatch.setattr(chat.biblioteca, "importar", lambda cx_, aid, slug, cand: {
        "archivo": "foto.jpg", "proveedor": cand.proveedor, "autor": cand.autor,
        "licencia": cand.licencia, "url_origen": cand.url_origen, "ig_handle": None,
        "recorte_archivo": None})
    monkeypatch.setattr(chat.biblioteca, "ruta_de", lambda slug, a: tmp_path / a)
    recortes: list[str] = []
    monkeypatch.setattr(chat.recorte, "quitar_fondo",
                        lambda o, d: recortes.append(d.name) or d)
    compuestos: list[dict] = []

    def componer(cx_, marca, kind, spec, assets, catalogo):
        compuestos.append({"kind": kind, "spec": spec, "assets": assets})
        esc = {"v": 2, "lienzo": {"w": 1080, "h": 1350, "formato": "4x5",
                                  "fondo": {"tipo": "color", "valor": "#ffffff"}},
               "tokens": {"colores": {}, "fuente": "Poppins-SemiBold"},
               "capas": [{"id": "bajada", "tipo": "text", "campo": "bajada", "texto": "x"}]}
        return b"\x89PNG", esc, {"bajada": "x"}

    monkeypatch.setattr(chat, "_componer", componer)
    validadas: list[dict] = []
    monkeypatch.setattr(chat.escena_mod, "validar",
                        lambda e, c, familias=None: validadas.append(c))
    return SimpleNamespace(cx=cx, respuestas=respuestas, pedidos=pedidos, buscadas=buscadas,
                           recortes=recortes, compuestos=compuestos, validadas=validadas)


SIDE = {"kind": "side", "spec": {"titulo": ["Hola"], "bajada": "x"},
        "assets": {"imagen": "woman doctor smiling"}, "respuesta": "Listo"}


def test_crear_feliz(entorno):
    entorno.respuestas += [SIDE, {"ok": True}]
    uso: list = []
    escena, contrato, meta = chat.crear(entorno.cx, _marca(), "post de ginecología", uso=uso)
    assert entorno.buscadas == ["woman doctor smiling"]
    assert entorno.compuestos[0]["assets"]["imagen"]["archivo"] == "assets/foto.jpg"
    assert entorno.compuestos[0]["assets"]["imagen"]["fuente_asset"]["url"] == "https://pexels.com/1"
    assert contrato["extras"] == [{"id": "bajada", "tipo": "texto"}]
    assert contrato["aspecto"] == "4:5"
    assert meta["kind"] == "side" and meta["respuesta"] == "Listo"
    assert len(uso) == 2
    # la segunda llamada es la crítica, con la imagen
    assert entorno.pedidos[1]["herramienta"]["name"] == "revisar"
    assert len(entorno.pedidos[1]["imagenes"]) == 1


def test_spec_invalido_reintenta_una_vez(entorno):
    malo = {**SIDE, "spec": {"titulo": []}}
    entorno.respuestas += [malo, SIDE, {"ok": True}]
    chat.crear(entorno.cx, _marca(), "x")
    reintento = entorno.pedidos[1]["mensajes"]
    assert reintento[-1]["role"] == "user" and "titulo" in reintento[-1]["content"]


def test_dos_fallos_es_chat_error(entorno):
    malo = {**SIDE, "spec": {"titulo": []}}
    entorno.respuestas += [malo, malo]
    with pytest.raises(chat.ChatError):
        chat.crear(entorno.cx, _marca(), "x")


def test_falta_consulta_de_slot_requerido(entorno):
    sin = {**SIDE, "assets": {}}
    entorno.respuestas += [sin, sin]
    with pytest.raises(chat.ChatError, match="imagen"):
        chat.crear(entorno.cx, _marca(), "x")


def test_recorte_en_compare(entorno):
    comp = {"kind": "compare", "respuesta": "ok", "assets": {"item_0": "pill", "item_1": "flask"},
            "spec": {"titulo": ["A"], "oferta": {"nombre": "T", "precio": "$1"},
                     "items": [{"nombre": "a", "precio": "1"}, {"nombre": "b", "precio": "2"}]}}
    entorno.respuestas += [comp, {"ok": True}]
    chat.crear(entorno.cx, _marca(), "x")
    assert entorno.recortes == ["foto-recorte.png", "foto-recorte.png"]
    assert entorno.compuestos[0]["assets"]["item_0"]["archivo"] == "assets/foto-recorte.png"


def test_critica_corrige_una_vez(entorno):
    entorno.respuestas += [SIDE, {"ok": False, "problemas": ["título corto"],
                                  "spec": {"titulo": ["Hola", "mundo"]}}]
    chat.crear(entorno.cx, _marca(), "x")
    assert len(entorno.compuestos) == 2
    assert entorno.compuestos[1]["spec"]["titulo"] == ["Hola", "mundo"]
    assert len(entorno.pedidos) == 2


def test_critica_con_spec_invalido_se_ignora(entorno):
    entorno.respuestas += [SIDE, {"ok": False, "spec": {"titulo": []}}]
    chat.crear(entorno.cx, _marca(), "x")
    assert len(entorno.compuestos) == 1


def test_formato_1x1_reformatea(entorno, monkeypatch):
    llamado = {}
    monkeypatch.setattr(chat.escena_mod, "reformatear",
                        lambda e, f: llamado.setdefault("f", f) and e)
    entorno.respuestas += [SIDE, {"ok": True}]
    _, contrato, _ = chat.crear(entorno.cx, _marca(), "x", formato="1x1")
    assert llamado["f"] == "1x1"
    assert contrato["aspecto"] == "1:1"


def test_system_lista_los_kinds(entorno):
    entorno.respuestas += [SIDE, {"ok": True}]
    chat.crear(entorno.cx, _marca(), "x")
    system = entorno.pedidos[0]["system"]
    for k in kinds.KINDS:
        assert f'"{k}"' in system
    assert "Cercana, directa." in system
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_chat_crear.py -q
```

Esperado: `ImportError`.

- [ ] **Step 2: implementar**

`src/plantillas/chat.py`:

```python
"""Chat del diseñador v2: crear (kind + spec) y editar (ops).

El modelo nunca pone coordenadas ni HTML. Todo lo que devuelve pasa por
kinds.validar_spec / ops.aplicar / escena.validar antes de salir de aquí.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Callable

from .. import compose, llm_claude
from ..assets import biblioteca, buscar, recorte
from . import contrato as contrato_mod
from . import escena as escena_mod
from . import extraer, fuentes_tipograficas, kinds, ops

_CLAVES_FUENTE = ("proveedor", "autor", "licencia", "url", "ig_handle")


class ChatError(RuntimeError):
    """El modelo no produjo algo usable tras su reintento, o falta un asset."""


HERRAMIENTA_DISENAR = {
    "name": "disenar",
    "description": "Elige un kind del catálogo y llena su spec. Para cada slot de imagen, "
                   "da una búsqueda corta en inglés (2 a 4 palabras) en `assets`.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(kinds.KINDS)},
            "spec": {"type": "object", "description": "cumple el esquema del kind elegido"},
            "assets": {"type": "object", "additionalProperties": {"type": "string"},
                       "description": "slot -> búsqueda de foto en inglés"},
            "respuesta": {"type": "string", "description": "una frase para la persona, en español"},
        },
        "required": ["kind", "spec", "respuesta"],
    },
}

HERRAMIENTA_REVISAR = {
    "name": "revisar",
    "description": "Revisa el render. ok=true si se lee bien y nada se encima ni se corta. "
                   "Si no, da los problemas y un spec corregido del MISMO kind.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "problemas": {"type": "array", "items": {"type": "string"}},
            "spec": {"type": "object"},
        },
        "required": ["ok"],
    },
}


def _system_crear(marca, formato: str) -> str:
    catalogo = json.dumps(kinds.catalogo(), ensure_ascii=False)
    return (
        f"Diseñas posts de Instagram para la marca {marca.nombre}"
        f"{' (@' + marca.ig_handle + ')' if marca.ig_handle else ''}.\n"
        f"Voz de la marca: {marca.voz or 'sin definir'}\n"
        f"Formato final: {formato} (se diseña en 4x5 y se adapta).\n\n"
        "Reglas:\n"
        "- Elige el kind que mejor cuente el mensaje. No inventes kinds.\n"
        "- `titulo` es una lista de líneas cortas: tú decides dónde se parte.\n"
        "- `acento` es un fragmento LITERAL de una línea del título.\n"
        "- No inventes cifras ni datos médicos: si el mensaje no trae una cifra, no uses `stat`.\n"
        "- Español de México, sin emojis.\n\n"
        f"Catálogo de kinds (JSON): {catalogo}"
    )


def _pedir_valido(*, system: str, mensajes: list[dict], herramienta: dict,
                  validar: Callable[[dict], Any], uso: list, imagenes=()) -> tuple[dict, Any]:
    salida = llm_claude.pedir_herramienta(system=system, mensajes=mensajes,
                                          herramienta=herramienta, imagenes=imagenes, uso=uso)
    try:
        return salida, validar(salida)
    except (kinds.SpecInvalido, escena_mod.EscenaInvalida, ops.OpInvalida, ChatError) as e:
        error = e
    reintento = mensajes + [
        {"role": "assistant",
         "content": f"Propuesta anterior:\n{json.dumps(salida, ensure_ascii=False)[:6000]}"},
        {"role": "user",
         "content": f"La propuesta no es válida: {error}. Corrígela y vuelve a llamar a "
                    f"{herramienta['name']}."},
    ]
    salida = llm_claude.pedir_herramienta(system=system, mensajes=reintento,
                                          herramienta=herramienta, uso=uso)
    try:
        return salida, validar(salida)
    except (kinds.SpecInvalido, escena_mod.EscenaInvalida, ops.OpInvalida, ChatError) as e:
        raise ChatError(f"el modelo no corrigió su propuesta: {e}") from e


def _recortar(cx, marca, fila: dict) -> str:
    """Mismo nombre y misma columna que el job asset.recorte del plan 3."""
    nombre = fila["archivo"].rsplit(".", 1)[0] + "-recorte.png"
    recorte.quitar_fondo(biblioteca.ruta_de(marca.slug, fila["archivo"]),
                         biblioteca.ruta_de(marca.slug, nombre))
    cx.execute("UPDATE brand_assets SET recorte_archivo = ? WHERE id = ? AND account_id = ?",
               (nombre, fila.get("id"), marca.id))
    cx.commit()
    return nombre


def asset_para(cx, marca, consulta: str, *, recortar: bool) -> dict | None:
    candidatas = buscar.buscar(cx, marca.id, marca.slug, consulta, tipo="imagen", n=5)
    if not candidatas:
        return None
    fila = biblioteca.importar(cx, marca.id, marca.slug, candidatas[0])
    archivo = fila["archivo"]
    if recortar:
        archivo = fila.get("recorte_archivo") or _recortar(cx, marca, fila)
    fuente = {"proveedor": fila.get("proveedor"), "autor": fila.get("autor"),
              "licencia": fila.get("licencia"), "url": fila.get("url_origen"),
              "ig_handle": fila.get("ig_handle")}
    return {"src": biblioteca.ruta_de(marca.slug, archivo).as_uri(),
            "archivo": f"assets/{archivo}",
            "fuente_asset": {k: (str(v)[:500] if v is not None else None)
                             for k, v in fuente.items()}}


def _resolver_assets(cx, marca, kind: str, spec: dict, consultas: dict) -> dict:
    resueltos: dict[str, dict] = {}
    for slot in kinds.slots(kind, spec):
        consulta = str(consultas.get(slot["id"]) or "").strip()
        if not consulta:
            if slot["requerido"]:
                raise ChatError(f"falta búsqueda para el slot {slot['id']}")
            continue
        asset = asset_para(cx, marca, consulta, recortar=slot["recorte"])
        if asset is None:
            if slot["requerido"]:
                raise ChatError(f"sin resultados para {consulta!r} ({slot['id']})")
            continue
        resueltos[slot["id"]] = asset
    return resueltos


def _componer(cx, marca, kind: str, spec: dict, assets: dict,
              catalogo: list[dict]) -> tuple[bytes, dict, dict]:
    tokens = kinds.tokens_de(marca, spec["tema"])
    fuentes = kinds.fuentes_de(marca, {f["familia"] for f in catalogo}, kind)
    logo = compose._to_src(marca.logo_path) if marca.logo_path else ""
    html = kinds.render(kind, spec, tokens=tokens, fuentes=fuentes, assets=assets,
                        font_faces=kinds.css_fuentes(set(fuentes.values()), catalogo),
                        handle=f"@{marca.ig_handle}" if marca.ig_handle else "", logo=logo)
    return extraer.extraer(html, slug=marca.slug, tokens=tokens, fuente=fuentes["texto"])


def contrato_de(escena: dict, formato: str) -> dict:
    campos = {c["campo"] for c in escena["capas"] if c.get("campo")}
    extras = [{"id": c, "tipo": "texto"}
              for c in sorted(campos - set(contrato_mod.CAMPOS_BASE))]
    return {"aspecto": escena_mod.ASPECTO_DE_FORMATO[formato],
            "base": list(contrato_mod.CAMPOS_BASE), "extras": extras}


def _revisar(png: bytes, kind: str, spec: dict, uso: list) -> dict | None:
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(png)
        ruta = Path(f.name)
    try:
        salida = llm_claude.pedir_herramienta(
            system="Eres director de arte. Revisas un post de Instagram ya renderizado.",
            mensajes=[{"role": "user", "content":
                       f"Kind: {kind}\nSpec: {json.dumps(spec, ensure_ascii=False)}\n"
                       f"Esquema: {json.dumps(kinds.esquema_para_llm(kind), ensure_ascii=False)}"}],
            herramienta=HERRAMIENTA_REVISAR, imagenes=[ruta], uso=uso, max_tokens=2048)
    finally:
        ruta.unlink(missing_ok=True)
    if salida.get("ok") or not isinstance(salida.get("spec"), dict):
        return None
    try:
        return kinds.validar_spec(kind, salida["spec"])
    except kinds.SpecInvalido:
        return None


def crear(cx, marca, mensaje: str, *, formato: str = "4x5",
          uso: list | None = None) -> tuple[dict, dict, dict]:
    uso = [] if uso is None else uso
    if formato not in escena_mod.FORMATOS:
        raise ChatError(f"formato desconocido: {formato!r}")
    catalogo = fuentes_tipograficas.catalogo(cx, marca.id)

    def validar(salida: dict) -> tuple[str, dict]:
        kind = salida.get("kind")
        spec = kinds.validar_spec(kind, salida.get("spec") or {})
        consultas = salida.get("assets") or {}
        faltan = [s["id"] for s in kinds.slots(kind, spec)
                  if s["requerido"] and not str(consultas.get(s["id"]) or "").strip()]
        if faltan:
            raise ChatError(f"faltan búsquedas para los slots {faltan}")
        return kind, spec

    salida, (kind, spec) = _pedir_valido(
        system=_system_crear(marca, formato), mensajes=[{"role": "user", "content": mensaje}],
        herramienta=HERRAMIENTA_DISENAR, validar=validar, uso=uso)
    consultas = salida.get("assets") or {}
    assets = _resolver_assets(cx, marca, kind, spec, consultas)
    png, escena, muestras = _componer(cx, marca, kind, spec, assets, catalogo)

    corregido = _revisar(png, kind, spec, uso)
    if corregido is not None:
        faltantes = {s["id"] for s in kinds.slots(kind, corregido)} - set(assets)
        if faltantes:
            assets |= _resolver_assets(cx, marca, kind, corregido,
                                       {k: v for k, v in consultas.items() if k in faltantes})
        spec = corregido
        png, escena, muestras = _componer(cx, marca, kind, spec, assets, catalogo)

    if formato != "4x5":
        escena = escena_mod.reformatear(escena, formato)
    contrato = contrato_de(escena, formato)
    escena_mod.validar(escena, contrato, familias={f["familia"] for f in catalogo})
    return escena, contrato, {"kind": kind, "spec": spec, "respuesta": salida["respuesta"],
                              "muestras": muestras, "revisado": corregido is not None}
```

- [ ] **Step 3: verde, lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_chat_crear.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/plantillas/chat.py tests/test_chat_crear.py
git commit -m "feat(chat): crear elige kind, resuelve assets, extrae capas y pasa una crítica con visión" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Esperado: `9 passed`.

- [ ] **Step 4 (opcional, con red y costo real; solo si Ricardo lo aprueba en el momento): humo contra Claude**

```python
# tests/test_chat_real.py
import os

import pytest

from src import db, marcas
from src.plantillas import chat


@pytest.mark.lento
@pytest.mark.skipif(not os.getenv("CHAT_REAL_SLUG"), reason="CHAT_REAL_SLUG no definido")
def test_crear_real():
    cx = db.connect()
    m = marcas.cargar(cx, os.environ["CHAT_REAL_SLUG"])
    uso: list = []
    escena, contrato, meta = chat.crear(cx, m, "Post con 3 señales de que tu regla no es normal",
                                        uso=uso)
    assert escena["capas"]
    print(meta["kind"], uso)
```

```bash
CHAT_REAL_SLUG=gdlscene /Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_chat_real.py -q -s -m lento
```

- ⚠️ Este paso lee la base local y escribe assets en `data/brands/<slug>/assets/`.
- El slug real se elige con Ricardo; `gdlscene` es solo un ejemplo.
- Se registran en la nota de sesión el kind, los tokens de `uso` y el costo.

---

## Task 8: `chat.editar`

**Files:**
- Modify: `src/plantillas/chat.py`
- Test: `tests/test_chat_editar.py`

**Interfaces:**

```python
HERRAMIENTA_EDITAR: dict
def editar(cx, marca, escena: dict, contrato: dict, mensaje: str, *, uso: list | None = None) -> tuple[list, dict, dict]
```

- [ ] **Step 1: prueba que falla**

`tests/test_chat_editar.py`:

```python
from types import SimpleNamespace

import pytest

from src import db
from src.plantillas import chat

ESCENA = {"v": 2, "lienzo": {"w": 1080, "h": 1350, "formato": "4x5",
                             "fondo": {"tipo": "color", "valor": "#ffffff"}},
          "tokens": {"colores": {}, "fuente": "Poppins-SemiBold"},
          "capas": [{"id": "titulo", "tipo": "text", "texto": "Hola", "estilo": {"fontSize": 72}},
                    {"id": "imagen", "tipo": "image", "src": "assets/a.png", "recorte": False}]}
CONTRATO = {"aspecto": "4:5", "base": [], "extras": []}


@pytest.fixture
def entorno(tmp_path, monkeypatch):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    respuestas, pedidos, validadas = [], [], []

    def falso(**kw):
        pedidos.append(kw)
        return respuestas.pop(0)

    monkeypatch.setattr(chat.llm_claude, "pedir_herramienta", falso)

    def validar(e, c, familias=None):
        validadas.append(e)
        tam = next(x for x in e["capas"] if x["id"] == "titulo")["estilo"].get("fontSize", 0)
        if tam > 400:
            raise chat.escena_mod.EscenaInvalida("fontSize fuera de rango")

    monkeypatch.setattr(chat.escena_mod, "validar", validar)
    monkeypatch.setattr(chat, "asset_para", lambda cx_, m, q, recortar: {
        "src": "file:///x/b.jpg", "archivo": "assets/b.jpg",
        "fuente_asset": {"proveedor": "pexels", "autor": "Ana", "licencia": None,
                         "url": None, "ig_handle": None}})
    marca = SimpleNamespace(id=1, slug="prueba", nombre="Prueba", ig_handle=None, voz="",
                            fuentes=[], estilos={}, logo_path=None)
    return SimpleNamespace(cx=cx, marca=marca, respuestas=respuestas, pedidos=pedidos,
                           validadas=validadas)


def test_editar_aplica_ops(entorno):
    entorno.respuestas.append({"ops": [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize",
                                        "valor": 96}], "respuesta": "Más grande."})
    lista, nueva, meta = chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "más grande")
    assert nueva["capas"][0]["estilo"]["fontSize"] == 96
    assert ESCENA["capas"][0]["estilo"]["fontSize"] == 72
    assert lista == [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize", "valor": 96}]
    assert meta["respuesta"] == "Más grande."
    assert '"titulo"' in entorno.pedidos[0]["mensajes"][0]["content"]


def test_editar_reintenta_si_la_escena_no_valida(entorno):
    entorno.respuestas += [
        {"ops": [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize", "valor": 900}],
         "respuesta": "x"},
        {"ops": [{"op": "set", "capa": "titulo", "ruta": "estilo.fontSize", "valor": 300}],
         "respuesta": "y"}]
    lista, nueva, _ = chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "enorme")
    assert nueva["capas"][0]["estilo"]["fontSize"] == 300
    assert "fontSize fuera de rango" in entorno.pedidos[1]["mensajes"][-1]["content"]


def test_editar_op_invalida_dos_veces(entorno):
    mala = {"ops": [{"op": "del", "capa": "nada"}], "respuesta": "x"}
    entorno.respuestas += [mala, mala]
    with pytest.raises(chat.ChatError):
        chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "borra")


def test_buscar_asset_se_vuelve_ops(entorno):
    entorno.respuestas.append({"ops": [], "respuesta": "Cambié la foto.",
                               "buscar_asset": [{"capa": "imagen", "query": "beach sunset"}]})
    lista, nueva, _ = chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "otra foto")
    assert {"op": "set", "capa": "imagen", "ruta": "src", "valor": "assets/b.jpg"} in lista
    assert nueva["capas"][1]["fuente_asset"]["autor"] == "Ana"


def test_buscar_asset_sobre_capa_no_imagen(entorno):
    mala = {"ops": [], "respuesta": "x", "buscar_asset": [{"capa": "titulo", "query": "a"}]}
    entorno.respuestas += [mala, mala]
    with pytest.raises(chat.ChatError, match="titulo"):
        chat.editar(entorno.cx, entorno.marca, ESCENA, CONTRATO, "x")
```

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_chat_editar.py -q
```

Esperado: `AttributeError: module 'src.plantillas.chat' has no attribute 'editar'`.

- [ ] **Step 2: implementar**

Se agrega a `src/plantillas/chat.py`:

```python
HERRAMIENTA_EDITAR = {
    "name": "editar",
    "description": "Cambia la escena con ops. set: {op:'set', capa:id, ruta:'estilo.color', valor}; "
                   "valor null borra la clave. add: {op:'add', capa:{...capa v2 completa...}, indice?}. "
                   "del: {op:'del', capa:id}. Para cambiar una foto usa buscar_asset, no inventes src.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ops": {"type": "array", "items": {"type": "object"}},
            "buscar_asset": {"type": "array", "items": {
                "type": "object", "properties": {"capa": {"type": "string"},
                                                 "query": {"type": "string"}},
                "required": ["capa", "query"]}},
            "respuesta": {"type": "string", "description": "una frase para la persona, en español"},
        },
        "required": ["ops", "respuesta"],
    },
}

_SYSTEM_EDITAR = (
    "Editas una escena v2 de un post de Instagram. Responde SOLO con la herramienta `editar`.\n"
    "- Cambia lo mínimo que pide la persona; no reacomodes lo demás.\n"
    "- Colores: '#rrggbb', 'rgba(...)' o 'token:<nombre>' de escena.tokens.colores.\n"
    "- El lienzo mide lienzo.w × lienzo.h px; x/y/w/h van en px.\n"
    "- Ids nuevos: ^[a-z][a-z0-9_-]{0,31}$ y que no existan.\n"
    "- Nunca cambies `id` ni `campo`.\n"
    "- Español de México, sin emojis."
)


def _ops_de_asset(cx, marca, escena: dict, pedido: dict) -> list[dict]:
    capa = next((c for c in escena.get("capas", []) if c.get("id") == pedido.get("capa")), None)
    if capa is None or capa.get("tipo") != "image":
        raise ChatError(f"buscar_asset necesita una capa de imagen: {pedido.get('capa')!r}")
    asset = asset_para(cx, marca, str(pedido.get("query") or ""),
                       recortar=bool(capa.get("recorte")))
    if asset is None:
        raise ChatError(f"sin resultados para {pedido.get('query')!r}")
    return [{"op": "set", "capa": capa["id"], "ruta": "src", "valor": asset["archivo"]},
            {"op": "set", "capa": capa["id"], "ruta": "fuente_asset",
             "valor": asset["fuente_asset"]}]


def editar(cx, marca, escena: dict, contrato: dict, mensaje: str, *,
           uso: list | None = None) -> tuple[list, dict, dict]:
    uso = [] if uso is None else uso
    familias = {f["familia"] for f in fuentes_tipograficas.catalogo(cx, marca.id)}

    def validar(salida: dict) -> tuple[list, dict]:
        lista = list(salida.get("ops") or [])
        for pedido in salida.get("buscar_asset") or []:
            lista += _ops_de_asset(cx, marca, escena, pedido)
        nueva = ops.aplicar(escena, lista)
        escena_mod.validar(nueva, contrato, familias=familias)
        return lista, nueva

    contenido = (f"Escena actual:\n{json.dumps(escena, ensure_ascii=False)}\n\n"
                 f"Familias tipográficas disponibles: {sorted(familias)}\n\n"
                 f"Pedido: {mensaje}")
    salida, (lista, nueva) = _pedir_valido(
        system=_SYSTEM_EDITAR, mensajes=[{"role": "user", "content": contenido}],
        herramienta=HERRAMIENTA_EDITAR, validar=validar, uso=uso)
    return lista, nueva, {"respuesta": salida["respuesta"]}
```

- [ ] **Step 3: verde (con las de crear), lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_chat_editar.py tests/test_chat_crear.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/plantillas/chat.py tests/test_chat_editar.py
git commit -m "feat(chat): editar devuelve ops validadas y resuelve buscar_asset en el servidor" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Esperado: `14 passed`.

---

## Task 9: job `diseno.chat` y endpoints

**Files:**
- Modify: `src/jobs/handlers.py` (handler y registro en `HANDLERS`, ~línea 744)
- Modify: `api/routers/plantillas.py` (modelo `MensajeChat`, `POST` y `GET /templates/{tid}/chat`, comentario de obsoleto en `POST /templates/design`)
- Modify: `src/plantillas/disenador.py` (solo un comentario de obsoleto en el docstring del módulo)
- Test: `tests/test_diseno_chat.py`

- [ ] **Step 1: prueba que falla**

`tests/test_diseno_chat.py`:

```python
import json

import pytest

from src import db, jobs, plantillas
from src.jobs import handlers
from src.plantillas import chat

ESCENA = {"v": 2, "lienzo": {"w": 1080, "h": 1350, "formato": "4x5",
                             "fondo": {"tipo": "color", "valor": "#ffffff"}},
          "tokens": {"colores": {}, "fuente": "Poppins-SemiBold"}, "capas": []}
CONTRATO = {"aspecto": "4:5", "base": ["titular", "imagen", "handle", "logo", "color_marca"],
            "extras": []}


def _marca(cx, slug):
    """conftest no tiene helper de marcas: se insertan como en test_disenos_web.py."""
    filas = db.rows(cx, "SELECT id FROM accounts WHERE slug = ?", (slug,))
    if filas:
        return {"id": filas[0]["id"], "slug": slug}
    aid = db.insert(cx, "accounts", slug=slug, ig_handle=slug, nombre=slug.title(),
                    ciudad="CDMX")
    return {"id": aid, "slug": slug}


def _plantilla(cx, account_id):
    # Mismo patrón que las pruebas del plan 1: HTML vacío y la escena v2 como layout.
    return plantillas.crear(cx, account_id, "Prueba", "", CONTRATO, layout=ESCENA)


@pytest.fixture
def con_marca(api_cliente):
    cli, cx, H = api_cliente
    prueba = _marca(cx, "prueba")
    uid = H.usuario("dueno@x.com", marcas=((prueba["id"], "manager"),))
    H.login(uid)
    return cli, cx, H, uid


def test_post_encola_202(con_marca, monkeypatch):
    cli, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    r = cli.post(f"/brands/prueba/templates/{tid}/chat",
                 json={"mensaje": "hazlo amarillo", "modo": "editar", "escena": ESCENA})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert job["tipo"] == "diseno.chat"
    assert json.loads(job["payload_json"])["template_id"] == tid


def test_post_editor_403(con_marca):
    cli, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    otro = H.usuario("editor@x.com", marcas=((marca["id"], "editor"),))
    H.login(otro)
    r = cli.post(f"/brands/prueba/templates/{tid}/chat", json={"mensaje": "x"})
    assert r.status_code == 403


def test_post_plantilla_ajena_404(con_marca):
    cli, cx, H, uid = con_marca
    _marca(cx, "prueba")
    ajena = _marca(cx, "otra")
    tid = _plantilla(cx, ajena["id"])
    r = cli.post(f"/brands/prueba/templates/{tid}/chat", json={"mensaje": "x"})
    assert r.status_code == 404


def test_handler_crear_guarda_version(con_marca, monkeypatch):
    _, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    monkeypatch.setattr(chat, "crear", lambda cx_, m, msg, formato="4x5", uso=None: (
        uso.append({"modelo": "f", "entrada": 1, "salida": 1}) or ESCENA, CONTRATO,
        {"kind": "side", "respuesta": "Listo"}))
    jid = jobs.crear(cx, "diseno.chat", marca["id"],
                     {"template_id": tid, "mensaje": "post", "modo": "crear"}, creado_por=uid)
    res = handlers.diseno_chat(cx, db.get(cx, "jobs", jid))
    assert res["escena"] == ESCENA and res["respuesta"] == "Listo"
    ver = plantillas.versiones(cx, tid)[-1]
    assert ver["mensaje_usuario"] == "post"
    assert json.loads(ver["llm_meta"])["modo"] == "crear"


def test_handler_editar_devuelve_ops(con_marca, monkeypatch):
    _, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    lista = [{"op": "set", "capa": "t", "ruta": "x", "valor": 1}]
    monkeypatch.setattr(chat, "editar", lambda cx_, m, e, c, msg, uso=None: (
        lista, ESCENA, {"respuesta": "Hecho"}))
    jid = jobs.crear(cx, "diseno.chat", marca["id"],
                     {"template_id": tid, "mensaje": "x", "modo": "editar", "escena": ESCENA},
                     creado_por=uid)
    res = handlers.diseno_chat(cx, db.get(cx, "jobs", jid))
    assert res["ops"] == lista and "escena" not in res


def test_handler_plantilla_de_otra_cuenta(con_marca):
    _, cx, H, uid = con_marca
    m1 = _marca(cx, "prueba")
    m2 = _marca(cx, "otra")
    tid = _plantilla(cx, m2["id"])
    jid = jobs.crear(cx, "diseno.chat", m1["id"],
                     {"template_id": tid, "mensaje": "x", "modo": "crear"}, creado_por=uid)
    with pytest.raises(ValueError):
        handlers.diseno_chat(cx, db.get(cx, "jobs", jid))


def test_get_historial(con_marca, monkeypatch):
    cli, cx, H, uid = con_marca
    marca = _marca(cx, "prueba")
    tid = _plantilla(cx, marca["id"])
    plantillas.nueva_version(cx, tid, "", CONTRATO, mensaje_usuario="hola",
                             llm_meta={"modo": "crear", "respuesta": "Listo"}, layout=ESCENA)
    r = cli.get(f"/brands/prueba/templates/{tid}/chat")
    assert r.status_code == 200
    assert r.json()[-1]["mensaje"] == "hola"
    assert r.json()[-1]["respuesta"] == "Listo"
```

> Helpers verificados contra el repo (2026-10-06): `H.usuario(email, *, admin=False, marcas=((account_id, rol),))` con `rol ∈ ("manager","editor")` (`src/users.py:17`), `H.login(uid)`. No hay `H.marca` ni `jobs.obtener`: las marcas se insertan con `db.insert(cx, "accounts", ...)` y los jobs se leen con `db.get(cx, "jobs", id)`, como en `tests/test_api_cola.py:196`. `plantillas.crear(cx, account_id, nombre, html, contrato_dict, *, layout=...)` (`src/plantillas/__init__.py:66`).

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_diseno_chat.py -q
```

Esperado: 404 en el POST (ruta inexistente) y `AttributeError` en el handler.

- [ ] **Step 2: handler**

En `src/jobs/handlers.py`, junto a los demás imports de `src.plantillas`:

```python
from src.plantillas import chat as plantillas_chat
from src.plantillas import escena as escena_mod
```

Handler, antes de `HANDLERS`:

```python
_FORMATO_DE_ASPECTO = {v: k for k, v in escena_mod.ASPECTO_DE_FORMATO.items()}


def diseno_chat(cx, job) -> dict:
    """Un mensaje del chat del editor v2. Guarda versión: el historial del chat
    ES `template_versions` (mensaje_usuario + llm_meta)."""
    payload = json.loads(job["payload_json"] or "{}")
    tid = int(payload["template_id"])
    mensaje = str(payload.get("mensaje") or "").strip()
    fila = plantillas.obtener(cx, tid)
    if fila is None or fila["account_id"] != job["account_id"]:
        raise ValueError("plantilla de otra marca o inexistente")
    m = marcas.cargar_por_id(cx, job["account_id"])
    uso: list[dict] = []
    jobs.progresar(cx, job["id"], 10, "Pensando el diseño")
    if payload.get("modo") == "editar":
        actual = payload.get("escena") or escena_mod.normalizar(
            json.loads(fila.get("layout_json") or "null"), fila["aspecto"])
        contrato = json.loads(fila["contrato_json"])
        lista, nueva, meta = plantillas_chat.editar(cx, m, actual, contrato, mensaje, uso=uso)
        resultado: dict = {"ops": lista}
    else:
        formato = payload.get("formato") or _FORMATO_DE_ASPECTO.get(fila["aspecto"], "4x5")
        nueva, contrato, meta = plantillas_chat.crear(cx, m, mensaje, formato=formato, uso=uso)
        resultado = {"escena": nueva}
    jobs.progresar(cx, job["id"], 90, "Guardando versión")
    numero = plantillas.nueva_version(
        cx, tid, "", contrato, mensaje_usuario=mensaje, layout=nueva,
        llm_meta={"modelo": config.DISENO_MODELO, "uso": uso,
                  "modo": payload.get("modo") or "crear", "kind": meta.get("kind"),
                  "respuesta": meta.get("respuesta")})
    return {**resultado, "version": numero, "respuesta": meta.get("respuesta"), "uso": uso}
```

En el dict `HANDLERS`:

```python
    "diseno.chat": diseno_chat,
```

> ⚠️ Se verifica que `handlers.py` ya importe `config`, `plantillas`, `marcas` y `jobs`. Si no, se agregan con el mismo estilo de import que use el archivo.
>
> El layout guardado vive en `brand_templates.layout_json` o en la última fila de `template_versions`, según cómo lo dejó el plan 1. Se confirma con:
>
> ```bash
> grep -n "layout_json" src/plantillas/__init__.py
> ```
>
> El frontend siempre manda `escena`, así que el fallback solo corre cuando no hay escena en el payload.

- [ ] **Step 3: router**

En `api/routers/plantillas.py`, cerca de `PedirDiseno`:

```python
from typing import Literal


class MensajeChat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)
    modo: Literal["crear", "editar"] = "editar"
    escena: dict | None = None
    formato: Literal["4x5", "1x1", "9x16"] | None = None
```

Endpoints, debajo de `listar_versiones`:

```python
@router.post("/templates/{tid}/chat", status_code=202)
def chat_diseno(slug: str, tid: int, cuerpo: MensajeChat, user: dict = Depends(usuario_actual),
                cx=Depends(get_cx)) -> dict:
    """Un mensaje del chat del editor v2 (crear o editar). Aislamiento antes de encolar."""
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _plantilla_de_marca(cx, marca["id"], tid)
    job_id = jobs.crear(cx, "diseno.chat", marca["id"],
                        {"template_id": tid, **cuerpo.model_dump()}, creado_por=user["id"])
    return {"job_id": job_id}


@router.get("/templates/{tid}/chat")
def historial_chat(slug: str, tid: int, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> list[dict]:
    """Historial del chat: las versiones que nacieron de un mensaje, en orden."""
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _plantilla_de_marca(cx, marca["id"], tid)
    out = []
    for f in plantillas.versiones(cx, tid):
        meta = json.loads(f.get("llm_meta") or "{}")
        if not f.get("mensaje_usuario") or "modo" not in meta:
            continue
        out.append({"version": f["version"], "mensaje": f["mensaje_usuario"],
                    "respuesta": meta.get("respuesta"), "modo": meta["modo"],
                    "kind": meta.get("kind"), "creado_en": f.get("creado_en")})
    return out
```

(Se agrega `import json` arriba si no está.)

En el docstring de `pedir_diseno` (`POST /templates/design`) se agrega como primera línea:

```python
    """OBSOLETO desde editor v2: lo reemplaza POST /templates/{tid}/chat. Se borra cuando v2 esté en prod.
```

En `src/plantillas/disenador.py`, primera línea del docstring del módulo:

```python
"""OBSOLETO desde editor v2 (lo reemplaza plantillas/chat.py). Se borra cuando v2 esté en prod.
```

- [ ] **Step 4: verde, suite completa sin lentas, lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_diseno_chat.py -q
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/jobs/handlers.py api/routers/plantillas.py src/plantillas/disenador.py tests/test_diseno_chat.py
git commit -m "feat(chat): job diseno.chat y endpoints POST/GET /templates/{tid}/chat con historial en template_versions" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Esperado: `7 passed` y la suite completa verde.

---

## Task 10: frontend, pestaña «Chat»

**Files:**
- Create: `frontend/hooks/use-chat-diseno.ts`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/panel-chat.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx` (agregar la pestaña)
- Test: `frontend/tests/unit/use-chat-diseno.test.ts`

- [ ] **Step 1: prueba que falla (lógica pura del hook)**

`frontend/tests/unit/use-chat-diseno.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { interpretarResultado } from "../../hooks/use-chat-diseno";

describe("interpretarResultado", () => {
  it("crear devuelve escena", () => {
    const r = interpretarResultado({ escena: { v: 2, capas: [] }, respuesta: "Listo", version: 3 });
    expect(r).toEqual({ tipo: "escena", escena: { v: 2, capas: [] }, respuesta: "Listo", version: 3 });
  });
  it("editar devuelve ops", () => {
    const ops = [{ op: "del", capa: "a" }];
    const r = interpretarResultado({ ops, respuesta: "Hecho", version: 4 });
    expect(r).toEqual({ tipo: "ops", ops, respuesta: "Hecho", version: 4 });
  });
  it("basura es null", () => {
    expect(interpretarResultado(null)).toBeNull();
    expect(interpretarResultado({ respuesta: "x" })).toBeNull();
  });
});
```

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend && pnpm vitest run tests/unit/use-chat-diseno.test.ts; cd ..
```

Esperado: falla la resolución del módulo.

- [ ] **Step 2: hook**

`frontend/hooks/use-chat-diseno.ts`:

```ts
"use client";

import { useCallback, useEffect, useState } from "react";
import { get, post } from "@/lib/api";
import type { Escena, Formato, Op } from "@/lib/escena";
import { useJob } from "@/hooks/use-job";
import { resultadoDeJob } from "@/hooks/use-disenos";

export type MensajeHistorial = {
  version: number;
  mensaje: string;
  respuesta: string | null;
  modo: "crear" | "editar";
  kind: string | null;
  creado_en: string | null;
};

export type ResultadoChat =
  | { tipo: "escena"; escena: Escena; respuesta: string; version: number }
  | { tipo: "ops"; ops: Op[]; respuesta: string; version: number };

export function interpretarResultado(r: unknown): ResultadoChat | null {
  if (!r || typeof r !== "object") return null;
  const o = r as Record<string, unknown>;
  const respuesta = typeof o.respuesta === "string" ? o.respuesta : "";
  const version = typeof o.version === "number" ? o.version : 0;
  if (o.escena && typeof o.escena === "object") {
    return { tipo: "escena", escena: o.escena as Escena, respuesta, version };
  }
  if (Array.isArray(o.ops)) return { tipo: "ops", ops: o.ops as Op[], respuesta, version };
  return null;
}

export function useChatDiseno(slug: string, tid: number, alResultado: (r: ResultadoChat) => void) {
  const [historial, setHistorial] = useState<MensajeHistorial[]>([]);
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const job = useJob(slug, jobId);

  const recargar = useCallback(async () => {
    setHistorial(await get<MensajeHistorial[]>(`/brands/${slug}/templates/${tid}/chat`));
  }, [slug, tid]);

  useEffect(() => {
    void recargar();
  }, [recargar]);

  useEffect(() => {
    const j = job.data;
    if (!j || jobId === null) return;
    if (j.estado === "ok") {
      const r = interpretarResultado(resultadoDeJob(j));
      if (r) alResultado(r);
      else setError("El job terminó sin resultado.");
      setJobId(null);
      void recargar();
    } else if (j.estado === "error" || j.estado === "cancelado") {
      setError("No se pudo completar. Intenta de nuevo o reformula.");
      setJobId(null);
    }
  }, [job.data, jobId, alResultado, recargar]);

  const enviar = useCallback(
    async (mensaje: string, modo: "crear" | "editar", escena: Escena | null, formato?: Formato) => {
      setError(null);
      const r = await post<{ job_id: number }>(`/brands/${slug}/templates/${tid}/chat`, {
        mensaje,
        modo,
        escena: modo === "editar" ? escena : null,
        formato: formato ?? null,
      });
      setJobId(r.job_id);
    },
    [slug, tid],
  );

  return { historial, enviar, ocupado: jobId !== null, progreso: job.data, error };
}
```

> ⚠️ Las firmas de `get` y `post` (tipadas con genérico), la forma de `useJob` (`{ data }`) y el import de `resultadoDeJob` salen de `lib/api.ts`, `hooks/use-job.ts` y `hooks/use-disenos.ts`. Si `useJob` devuelve el `Job` directo y no `{ data }`, se cambia `job.data` por `job`. Se confirma con:
>
> ```bash
> grep -n "export function useJob" -A15 frontend/hooks/use-job.ts
> grep -n "export async function \(get\|post\)" frontend/lib/api.ts
> ```

- [ ] **Step 3: panel**

`frontend/app/b/[slug]/templates/[id]/_components/panel-chat.tsx`:

```tsx
"use client";

import { useCallback, useState } from "react";
import { useEditor } from "@/stores/editor";
import { useChatDiseno, type ResultadoChat } from "@/hooks/use-chat-diseno";

export function PanelChat({ slug, tid }: { slug: string; tid: number }) {
  const escena = useEditor((s) => s.escena);
  const cargar = useEditor((s) => s.cargar);
  const aplicar = useEditor((s) => s.aplicar);
  const [texto, setTexto] = useState("");
  const [modo, setModo] = useState<"crear" | "editar">(escena?.capas?.length ? "editar" : "crear");
  const [ultima, setUltima] = useState<string | null>(null);

  const alResultado = useCallback(
    (r: ResultadoChat) => {
      if (r.tipo === "escena") cargar(r.escena);
      else aplicar(r.ops, `IA: ${r.respuesta.slice(0, 40)}`);
      setUltima(r.respuesta);
      setModo("editar");
    },
    [cargar, aplicar],
  );

  const { historial, enviar, ocupado, progreso, error } = useChatDiseno(slug, tid, alResultado);

  const mandar = async () => {
    const m = texto.trim();
    if (!m || ocupado) return;
    if (modo === "crear" && escena?.capas?.length &&
        !window.confirm("Crear desde cero reemplaza el diseño y no se puede deshacer. ¿Seguir?")) {
      return;
    }
    await enviar(m, modo, escena ?? null);
    setTexto("");
  };

  return (
    <div className="flex h-full flex-col gap-3 p-3 text-sm">
      <div className="flex gap-1 rounded-md bg-muted p-1">
        {(["crear", "editar"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setModo(m)}
            className={`flex-1 rounded px-2 py-1 ${modo === m ? "bg-background shadow-sm" : ""}`}
          >
            {m === "crear" ? "Crear desde cero" : "Editar este"}
          </button>
        ))}
      </div>

      <ol className="flex-1 space-y-3 overflow-y-auto">
        {historial.map((h) => (
          <li key={h.version} className="space-y-1">
            <p className="rounded-md bg-muted px-2 py-1">{h.mensaje}</p>
            {h.respuesta && <p className="px-2 text-muted-foreground">{h.respuesta}</p>}
          </li>
        ))}
        {ocupado && (
          <li className="px-2 text-muted-foreground">
            {progreso?.mensaje ?? "Pensando…"} {progreso?.progreso ? `${progreso.progreso}%` : ""}
          </li>
        )}
        {ultima && !ocupado && historial.length === 0 && (
          <li className="px-2 text-muted-foreground">{ultima}</li>
        )}
      </ol>

      {error && <p className="text-destructive">{error}</p>}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          void mandar();
        }}
        className="flex flex-col gap-2"
      >
        <textarea
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void mandar();
          }}
          rows={3}
          maxLength={2000}
          placeholder={modo === "crear" ? "Post de 3 señales de que tu regla no es normal" : "El título más grande y en amarillo"}
          className="w-full resize-none rounded-md border bg-background p-2"
          disabled={ocupado}
        />
        <button
          type="submit"
          disabled={ocupado || !texto.trim()}
          className="rounded-md bg-primary px-3 py-2 text-primary-foreground disabled:opacity-50"
        >
          {ocupado ? "Trabajando…" : "Enviar"}
        </button>
      </form>
    </div>
  );
}
```

> ⚠️ Los nombres de los campos de progreso del `Job` (`mensaje` y `progreso`) se confirman en `hooks/use-job.ts`. Si son otros (p. ej. `progreso_msg`), se ajustan aquí.

- [ ] **Step 4: pestaña en `page.tsx`**

En `frontend/app/b/[slug]/templates/[id]/page.tsx`, se agrega el import:

```tsx
import { PanelChat } from "./_components/panel-chat";
```

y una entrada en el arreglo `pestanas` que se pasa a `PanelLateral`:

```tsx
{ id: "chat", etiqueta: "Chat", contenido: <PanelChat slug={slug} tid={Number(id)} /> },
```

(`slug` e `id` son los nombres que `page.tsx` ya use para los params; se usan esos.)

- [ ] **Step 5: verde, typecheck, lint y commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend
pnpm vitest run
pnpm tsc --noEmit
pnpm lint
cd ..
git add frontend/hooks/use-chat-diseno.ts "frontend/app/b/[slug]/templates/[id]/_components/panel-chat.tsx" "frontend/app/b/[slug]/templates/[id]/page.tsx" frontend/tests/unit/use-chat-diseno.test.ts
git commit -m "feat(editor): pestaña Chat que crea (cargar) y edita (aplicar ops como un paso de deshacer)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: humo manual en el navegador (sin red de LLM: se para antes de enviar)**

- Se levanta API y frontend como en el plan 2.
- Se abre `/b/<slug>/templates/<id>`.
- Checklist:
  - [ ] La pestaña «Chat» aparece.
  - [ ] El historial carga (vacío o con lo de pruebas).
  - [ ] El conmutador crear/editar funciona.
  - [ ] Enviar con texto vacío no hace nada.
- Mandar un mensaje real gasta API de Anthropic, así que **solo se hace con aprobación de Ricardo en el momento**.

---

## Cierre del plan

- [ ] Suite completa:
  ```bash
  /Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
  /Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m lento -k "round_trip"
  cd frontend && pnpm vitest run && pnpm tsc --noEmit; cd ..
  ```
- [ ] Nota de sesión en el vault: `instagod/Sessions/YYYY-MM-DD-editor-v2-plan4-chat-ia.md`, con:
  - el diff del round-trip por kind;
  - los tokens del humo real si se corrió.
- [ ] Sin push ni deploy a la VM.
