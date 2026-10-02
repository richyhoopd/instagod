# Editor visual de diseños (layout_json) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un manager pueda armar un diseño de post arrastrando capas (fotos, stickers, cajas y textos) sobre un lienzo con rejilla, elegir tipografías del catálogo de la marca, guardarlo, y que el motor que ya existe genere contenido automático sobre ese diseño.

**Architecture:** El diseño deja de ser HTML escrito a mano y pasa a ser un `layout_json` versionado —una lista de capas con posición absoluta en píxeles sobre el lienzo real (1080×1350 o 1080×1920)— más un compilador determinista `layout.a_html()` que lo traduce a HTML+CSS+Jinja. El HTML sigue existiendo en la DB, pero como **artefacto derivado**: se compila al escribir, no al renderizar, así el camino caliente (`render.py`, `preview.py`, Playwright) no cambia ni una línea. Los diseños viejos que solo tienen `html` siguen renderizando igual (modo legacy) y el editor los abre en solo lectura con un botón de duplicar. DeepSeek deja de emitir HTML libre y pasa a emitir `layout_json` validable, lo que de paso cierra el riesgo de HTML sin sandbox.

**Tech Stack:** Python 3.11 · FastAPI · SQLite · Jinja2 · Playwright/Chromium · Next.js 16.3.1 · React 19.2.8 · TanStack Query 5 · Tailwind v4 · shadcn · pytest.

**Spec:** `docs/superpowers/specs/2026-08-29-plantillas-lotes-y-stats-design.md`

**Plan que extiende:** `docs/superpowers/plans/2026-08-31-h3-disenador-de-plantillas.md`. Las tareas 1-3 de ese plan están hechas (`5ef4f5d`). **Este plan reemplaza sus tareas 4-7**: el diseñador ya no es solo un chat que escupe HTML, es un lienzo directo más un chat que escupe `layout_json`.

## Decisiones que gobiernan este hito

Las tomó Ricardo el 2026-09-09, no se re-litigan durante la ejecución:

1. **Formato:** `layout_json` es la fuente de verdad; el `html` de la DB es un artefacto derivado que se compila al guardar.
2. **Migración:** las 4 plantillas publicadas de gdlscene (`clasica`, `onion`, `verde`, `slide`) **se quedan como están**. Modo legacy: si una plantilla tiene `html` y no tiene `layout_json`, renderiza como hoy y el editor la abre en solo lectura con un botón "Duplicar como editable". Los tests de equivalencia byte a byte siguen verdes sin tocarlos.
3. **Alcance:** los dos en este hito. El lienzo visual **y** el chat con DeepSeek, con el chat generando `layout_json`.

## Global Constraints

- **Baseline medido el 2026-09-09 en este worktree: 1421 tests, 1 falla conocida** (`tests/test_segmentos_web.py::test_segmentos_lista_catalogo_y_preview`, 92.87s). Ese número es el que hay que respetar, no el 1402/1 que dice el plan de H3. Cualquier tarea que agregue una falla distinta se revierte.
- `pytest -q` **no imprime su línea de resumen final** en este repo. Para contar tests hay que usar `--junit-xml` y parsear el XML **con el intérprete del venv**: `/Users/ricardo/Work/personal/instagod/.venv/bin/python`. El `python3` del sistema (3.14) revienta con `ImportError: ... pyexpat ... _XML_SetAllocTrackerActivationThreshold`.
- **Cero llamadas reales al LLM en los tests.** El punto de monkeypatch es `src/plantillas/generador.py::_pedir_al_llm`. Para el diseñador es `src/plantillas/disenador.py::_pedir_al_llm`, con la misma forma.
- **Nada toca producción.** Ni la VM, ni `/opt/instagod/`, ni `data/gdlscene.db`. Los tests usan DBs temporales.
- Ruff: línea máxima 100. Comentarios y docstrings en español. Comando exacto: `ruff check src/ tests/ api/ web/ config.py` — **NO** incluir todo `scripts/`, `scripts/portal_magic_link.py` tiene un F401 ajeno.
- Frontend: `pnpm lint` y `pnpm build` limpios. Hay **un** warning preexistente en `app/login/page.tsx`; ese se queda.
- **Cero jerga técnica en pantalla** (`PRODUCT.md:23,27`). En la UI se dice **"diseño"**. Nunca "plantilla", "contrato", "JSON", "slug", "HTML", "template_id", "layout", "capa z-index". Los nombres visibles de las capas son **"foto"**, **"sticker"**, **"texto"**, **"caja de color"**.
- Español mexicano, tono humano directo (`PRODUCT.md:17`). Estado visible en 5 segundos (`:28`). Acciones irreversibles protegidas y explicadas (`:29`). WCAG AA, contraste 4.5:1, teclado, `prefers-reduced-motion` (`:35`).
- Worktree: `/Users/ricardo/Work/personal/instagod/.claude/worktrees/plantillas-y-lotes`, rama `plantillas-y-lotes`. `.venv` y `.env` son symlinks al repo principal; **no los reemplaces por copias** o 4 tests fallan por entorno.
- **Sin dependencias nuevas en el frontend.** El lienzo se hace con eventos de puntero nativos (`pointerdown`/`pointermove` + `setPointerCapture`) y `transform`. `@dnd-kit` está instalado pero es para listas ordenables, no para posicionamiento libre con resize y rotación; no sirve aquí y meterlo a fuerza cuesta más de lo que ahorra.

---

## Esquema de `layout_json` (contrato central, memorízalo)

Todas las tareas dependen de esto. Las medidas son **píxeles enteros sobre el lienzo real**: 1080×1350 para `4:5`, 1080×1920 para `9:16`. El navegador nunca escala: el editor muestra el lienzo a escala reducida pero guarda píxeles reales.

```json
{
  "v": 1,
  "lienzo": { "fondo": "#ffffff" },
  "guias": { "cols": 12, "filas": 15, "iman": 8 },
  "capas": [
    {
      "id": "foto",
      "tipo": "imagen",
      "x": 0, "y": 0, "w": 1080, "h": 880, "z": 1,
      "rot": 0, "opacidad": 1,
      "campo": "imagen",
      "ajuste": "cover",
      "anclaje": "center top",
      "radio": 0
    },
    {
      "id": "titular",
      "tipo": "texto",
      "x": 70, "y": 940, "w": 940, "h": 280, "z": 3,
      "rot": 0, "opacidad": 1,
      "campo": "titular",
      "fuente": "Tinos", "tam": 58, "peso": 700,
      "color": "#0a0a0a",
      "alinear": "centro", "vertical": "centro",
      "interlinea": 1.18, "mayusculas": false,
      "auto": true, "resaltar": false
    },
    {
      "id": "franja",
      "tipo": "caja",
      "x": 0, "y": 876, "w": 1080, "h": 4, "z": 2,
      "rot": 0, "opacidad": 1,
      "color": "marca", "radio": 0
    },
    {
      "id": "sticker1",
      "tipo": "imagen",
      "x": 820, "y": 60, "w": 200, "h": 200, "z": 5,
      "rot": -8, "opacidad": 1,
      "archivo": "corazon.png",
      "ajuste": "contain",
      "anclaje": "center",
      "radio": 0
    }
  ]
}
```

**Reglas duras del esquema:**

| Campo | Regla |
|---|---|
| `v` | Entero, hoy siempre `1`. Otro valor → error. |
| `lienzo.fondo` | `#rrggbb` o el token `"marca"` (compila a `{{ color_marca }}`). |
| `guias` | Solo ayuda de edición, no afecta el render. `cols` 1..48, `filas` 1..64, `iman` 0..64. |
| `capas` | Lista, entre 1 y 40 elementos. |
| `id` | `^[a-z][a-z0-9_-]{0,31}$`, único dentro del diseño. |
| `tipo` | `"texto"`, `"imagen"` o `"caja"`. |
| `x`, `y` | Enteros entre -2000 y 4000 (se permite sangrado; `.card` recorta). |
| `w`, `h` | Enteros entre 1 y 4000. |
| `z` | Entero 0..999. |
| `rot` | Número -180..180. |
| `opacidad` | Número 0..1. |
| color (`color`, `fondo`) | `^#[0-9a-fA-F]{6}$` o `"marca"`. |
| texto: origen | **Exactamente uno** de `campo` (debe estar en `contrato.variables_declaradas`) o `texto` (literal, ≤ 500 caracteres). |
| texto: `fuente` | Debe estar en el catálogo tipográfico de la marca. |
| texto: `tam` | Entero 8..400. `peso` uno de 100..900 en pasos de 100. |
| texto: `alinear` | `izq` \| `centro` \| `der`. `vertical`: `arriba` \| `centro` \| `abajo`. |
| texto: `interlinea` | Número 0.8..3.0. |
| texto: `resaltar` | Si es `true`, la variable se emite con el filtro `resaltar`. Solo válido con `campo`. |
| texto: `auto` | Si es `true`, la capa se achica sola para caber. Enciende el script de auto-ajuste. |
| imagen: origen | **Exactamente uno** de `campo` (declarado en el contrato) o `archivo` (nombre de foto de la marca, `^[A-Za-z0-9._-]{1,80}$`, sin `/` ni `..`). |
| imagen: `ajuste` | `cover` \| `contain`. `anclaje`: uno de los 9 valores CSS (`center`, `center top`, …). |
| `radio` | Entero 0..2000. |

**Lo que el compilador garantiza en la salida** (esto lo exigen dos consumidores río abajo):
1. Existe exactamente un nodo `.card` de 1080×alto con `overflow:hidden` — `src/compose.py:191` fotografía ese nodo, y si no está el render revienta.
2. Toda `{{ variable }}` emitida está en `contrato.variables_declaradas(contrato) | CAMPOS_SISTEMA` y los únicos filtros son `resaltar` y `etiqueta` — `src/plantillas/contrato.py:182` lo valida.
3. Si alguna capa tiene `auto: true`, el HTML contiene el literal `window.__captionFitted` — `src/compose.py:185` lo detecta por substring y espera a que sea `true`.
4. El texto literal va escapado con `html.escape()`. Las variables NO (el filtro `resaltar` emite markup a propósito; `filtros.entorno()` no tiene autoescape y eso no cambia en este hito).

---

## File Structure

**Backend (crear):**
- `src/plantillas/layout.py` — esquema, validación y compilador `layout → HTML`. Puro, sin I/O, sin DB. Es el corazón del hito.
- `src/plantillas/disenador.py` — el puente con DeepSeek: prompt, parseo y reparación de `layout_json`. Espejo de `generador.py`.
- `tests/test_layout_esquema.py` — validación del esquema.
- `tests/test_layout_compilador.py` — compilación a HTML.
- `tests/test_disenos_web.py` — los endpoints nuevos.
- `tests/test_disenador_llm.py` — el chat, con `_pedir_al_llm` monkeypatcheado.

**Backend (modificar):**
- `src/schema.sql:516-560` — `layout_json TEXT` en `brand_templates` y en `template_versions`.
- `src/db.py:128-136` — whitelist de columnas; `src/db.py:~177+` — `_MIGRATIONS` para DBs viejas.
- `src/plantillas/__init__.py:27` — `_validado` compila el layout y valida tipografías; `crear`/`nueva_version` aceptan `layout`.
- `src/plantillas/contrato.py` — `fotos_dir` en `CAMPOS_SISTEMA`; `.card` obligatorio en `validar_html`.
- `src/plantillas/render.py:26` — `contexto()` inyecta `fotos_dir`.
- `src/plantillas/preview.py:75-76` — clave de caché incluye `layout_json`.
- `api/routers/plantillas.py` — de 2 endpoints a 12.
- `src/jobs/handlers.py` — handlers `template_preview` y `template_disenar` + registro en `HANDLERS`.

**Frontend (crear):**
- `frontend/hooks/use-disenos.ts` — queries y mutaciones de diseños, tipografías y stickers.
- `frontend/app/b/[slug]/templates/page.tsx` — la lista de diseños.
- `frontend/app/b/[slug]/templates/[id]/page.tsx` — el editor.
- `frontend/app/b/[slug]/templates/_components/lienzo.tsx` — el lienzo con rejilla y capas arrastrables.
- `frontend/app/b/[slug]/templates/_components/capa-vista.tsx` — cómo se pinta una capa en el lienzo.
- `frontend/app/b/[slug]/templates/_components/panel-capa.tsx` — el inspector de la capa seleccionada.
- `frontend/app/b/[slug]/templates/_components/lista-capas.tsx` — el orden de apilado.
- `frontend/app/b/[slug]/templates/_components/barra-agregar.tsx` — agregar foto, sticker, texto, caja.
- `frontend/app/b/[slug]/templates/_components/chat-diseno.tsx` — el chat con DeepSeek.
- `frontend/lib/layout.ts` — tipos y geometría pura (imán a rejilla, clamp, reordenar z).

**Frontend (modificar):**
- `frontend/app/b/[slug]/layout.tsx:19-26` — entrada "Diseños" en la navegación, `soloManager: true`.

---

### Task 1: La columna `layout_json`

Persistir el layout junto al HTML, sin romper nada de lo que ya existe. Al terminar esta tarea, un diseño puede guardar layout y leerlo de vuelta; el HTML sigue siendo el que le pasen.

**Files:**
- Modify: `src/schema.sql:516-560`
- Modify: `src/db.py:128-136`, `src/db.py:~177+` (`_MIGRATIONS`)
- Modify: `src/plantillas/__init__.py:27,34,52,111`
- Test: `tests/test_plantillas.py` (agregar al final)

**Interfaces:**
- Consumes: nada.
- Produces:
  - `plantillas.crear(cx, account_id, nombre, html, contrato_dict, *, descripcion=None, origen="manual", creado_por=None, mensaje_usuario=None, layout=None) -> int`
  - `plantillas.nueva_version(cx, template_id, html, contrato_dict, *, mensaje_usuario=None, llm_meta=None, layout=None) -> int`
  - `plantillas.layout_de(fila: dict) -> dict | None` — deserializa `layout_json`; devuelve `None` si la fila es legacy.
  - `plantillas.es_editable(fila: dict) -> bool` — `layout_de(fila) is not None`.

- [ ] **Step 1: Escribe los tests que fallan**

Al final de `tests/test_plantillas.py`:

```python
def test_crear_guarda_layout_y_lo_devuelve(cx_tmp):
    layout = {"v": 1, "lienzo": {"fondo": "#ffffff"}, "guias": {"cols": 12, "filas": 15, "iman": 8},
              "capas": [{"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 200,
                         "z": 1, "campo": "titular", "fuente": "Poppins", "tam": 48}]}
    tid = plantillas.crear(cx_tmp, 1, "Con layout", HTML_MINIMO, CONTRATO_MINIMO, layout=layout)
    fila = plantillas.obtener(cx_tmp, tid)
    assert plantillas.layout_de(fila) == layout
    assert plantillas.es_editable(fila) is True


def test_plantilla_sin_layout_es_legacy(cx_tmp):
    tid = plantillas.crear(cx_tmp, 1, "Sin layout", HTML_MINIMO, CONTRATO_MINIMO)
    fila = plantillas.obtener(cx_tmp, tid)
    assert plantillas.layout_de(fila) is None
    assert plantillas.es_editable(fila) is False


def test_nueva_version_guarda_el_layout_en_la_version(cx_tmp):
    layout = {"v": 1, "lienzo": {"fondo": "#ffffff"}, "guias": {"cols": 12, "filas": 15, "iman": 8},
              "capas": [{"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 200,
                         "z": 1, "campo": "titular", "fuente": "Poppins", "tam": 48}]}
    tid = plantillas.crear(cx_tmp, 1, "Versionada", HTML_MINIMO, CONTRATO_MINIMO, layout=layout)
    otro = {**layout, "lienzo": {"fondo": "#000000"}}
    plantillas.nueva_version(cx_tmp, tid, HTML_MINIMO, CONTRATO_MINIMO, layout=otro)
    v2 = plantillas.version(cx_tmp, tid, 2)
    assert json.loads(v2["layout_json"])["lienzo"]["fondo"] == "#000000"
    assert plantillas.layout_de(plantillas.obtener(cx_tmp, tid))["lienzo"]["fondo"] == "#000000"


def test_revertir_recupera_el_layout_viejo(cx_tmp):
    layout = {"v": 1, "lienzo": {"fondo": "#ffffff"}, "guias": {"cols": 12, "filas": 15, "iman": 8},
              "capas": [{"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 200,
                         "z": 1, "campo": "titular", "fuente": "Poppins", "tam": 48}]}
    tid = plantillas.crear(cx_tmp, 1, "Reversible", HTML_MINIMO, CONTRATO_MINIMO, layout=layout)
    plantillas.nueva_version(cx_tmp, tid, HTML_MINIMO, CONTRATO_MINIMO,
                             layout={**layout, "lienzo": {"fondo": "#000000"}})
    plantillas.revertir(cx_tmp, tid, 1)
    assert plantillas.layout_de(plantillas.obtener(cx_tmp, tid))["lienzo"]["fondo"] == "#ffffff"
```

Si `cx_tmp`, `HTML_MINIMO` o `CONTRATO_MINIMO` no se llaman así en ese archivo, usa los nombres que ya existan ahí; **no inventes fixtures nuevas**. Y agrega `import json` arriba si no está.

- [ ] **Step 2: Córrelos y confirma que fallan**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/plantillas-y-lotes
.venv/bin/python -m pytest tests/test_plantillas.py -k layout -x -q
```

Esperado: `AttributeError: module 'src.plantillas' has no attribute 'layout_de'`.

- [ ] **Step 3: Agrega la columna al esquema**

En `src/schema.sql`, dentro de `brand_templates`, justo después de `html TEXT NOT NULL,`:

```sql
    layout_json TEXT,
```

Y en `template_versions`, después de `contrato_json TEXT NOT NULL,`:

```sql
    layout_json TEXT,
```

Nullable a propósito: `NULL` es exactamente lo que significa "diseño legacy".

- [ ] **Step 4: Agrega la columna a la whitelist y a las migraciones**

En `src/db.py`, dentro del dict de tablas:

```python
    "brand_templates": {
        "account_id", "slug", "nombre", "descripcion", "aspecto",
        "contrato_json", "html", "layout_json", "estado", "version_actual",
        "origen", "creado_por", "actualizado_en",
    },
    "template_versions": {
        "template_id", "version", "mensaje_usuario", "html",
        "contrato_json", "layout_json", "preview_path", "llm_meta",
    },
```

Y en `_MIGRATIONS`, agrega dos entradas nuevas (mismo estilo que las que ya están):

```python
    # El diseño visual: lista de capas con posición absoluta. NULL = diseño
    # legacy escrito a mano, que sigue renderizando por su `html`.
    "brand_templates": {"layout_json": "TEXT"},
    "template_versions": {"layout_json": "TEXT"},
```

- [ ] **Step 5: Persiste el layout en el CRUD**

En `src/plantillas/__init__.py`:

```python
def layout_de(fila: dict[str, Any]) -> dict[str, Any] | None:
    """El diseño visual de una fila, o None si es legacy (HTML a mano)."""
    crudo = fila.get("layout_json") if hasattr(fila, "get") else fila["layout_json"]
    if not crudo:
        return None
    return json.loads(crudo)


def es_editable(fila: dict[str, Any]) -> bool:
    """Un diseño se abre en el editor solo si tiene capas. Los de antes, no."""
    return layout_de(fila) is not None
```

En `crear`, agrega el parámetro `layout: dict[str, Any] | None = None` al final de los keyword-only, y antes del `db.insert`:

```python
    layout_json = json.dumps(layout, ensure_ascii=False) if layout else None
```

Pásalo como `layout_json=layout_json` en los **dos** `db.insert` (el de `brand_templates` y el de `template_versions`).

En `nueva_version`, lo mismo: parámetro `layout` al final, `layout_json` calculado, y agregado al `db.insert` de `template_versions` y al `db.update` de `brand_templates`.

En `revertir` (`:72`), la copia hacia adelante tiene que arrastrar `layout_json` igual que arrastra `html` y `contrato_json`. Lee el cuerpo actual y agrega la columna en los mismos lugares donde ya aparecen esas dos.

- [ ] **Step 6: Corre los tests nuevos y luego los de plantillas completos**

```bash
.venv/bin/python -m pytest tests/test_plantillas.py -q
.venv/bin/python -m pytest tests/test_equivalencia_plantillas.py tests/test_plantillas_render.py tests/test_templates.py -q
```

Esperado: todo pasa. Los de equivalencia son el canario del modo legacy: si se ponen rojos, algo del CRUD cambió el HTML guardado y hay que volver atrás.

- [ ] **Step 7: Commit**

```bash
ruff check src/ tests/ api/ web/ config.py
git add src/schema.sql src/db.py src/plantillas/__init__.py tests/test_plantillas.py
git commit -m "feat(disenos): columna layout_json en brand_templates y template_versions"
```

---

### Task 2: El esquema del layout se valida solo

Un layout mal formado no debe llegar nunca al compilador. Esta tarea es puro Python sin I/O, así que corre en milisegundos y es la red que atrapa lo que devuelva DeepSeek.

**Files:**
- Create: `src/plantillas/layout.py`
- Create: `tests/test_layout_esquema.py`

**Interfaces:**
- Consumes: `plantillas.contrato.ContratoInvalido`, `contrato.variables_declaradas`, `contrato.ASPECTOS`.
- Produces:
  - `layout.LIENZO: dict[str, tuple[int, int]]` — alias de `contrato.ASPECTOS`, no lo dupliques.
  - `layout.TIPOS_CAPA: tuple[str, ...] = ("texto", "imagen", "caja")`
  - `layout.MAX_CAPAS: int = 40`
  - `layout.validar(layout: dict, contrato: dict, *, familias: set[str] | None = None) -> None` — lanza `contrato.ContratoInvalido` con mensaje en español; no devuelve nada.
  - `layout.vacio(aspecto: str) -> dict` — un layout mínimo válido (fondo blanco, una capa de texto ligada a `titular` centrada). Lo usa el botón "Diseño nuevo".

- [ ] **Step 1: Escribe los tests que fallan**

`tests/test_layout_esquema.py`:

```python
"""El esquema de un diseño visual: qué se acepta y qué se rechaza."""
import pytest

from src.plantillas import contrato, layout

CONTRATO = {
    "aspecto": "4:5",
    "base": list(contrato.CAMPOS_BASE),
    "extras": [{"id": "badge", "tipo": "texto", "etiqueta": "Etiqueta"}],
}
FAMILIAS = {"Poppins", "Tinos", "Anton"}


def _capa_texto(**extra):
    base = {"id": "titular", "tipo": "texto", "x": 70, "y": 940, "w": 940, "h": 280,
            "z": 3, "campo": "titular", "fuente": "Tinos", "tam": 58}
    base.update(extra)
    return base


def _layout(*capas):
    return {"v": 1, "lienzo": {"fondo": "#ffffff"},
            "guias": {"cols": 12, "filas": 15, "iman": 8},
            "capas": list(capas) or [_capa_texto()]}


def test_layout_minimo_es_valido():
    layout.validar(_layout(), CONTRATO, familias=FAMILIAS)


def test_vacio_es_valido_en_los_dos_aspectos():
    for aspecto in ("4:5", "9:16"):
        c = {**CONTRATO, "aspecto": aspecto}
        layout.validar(layout.vacio(aspecto), c, familias=FAMILIAS)


def test_version_desconocida_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="versión"):
        layout.validar({**_layout(), "v": 7}, CONTRATO, familias=FAMILIAS)


def test_ids_repetidos_se_rechazan():
    with pytest.raises(contrato.ContratoInvalido, match="repetido"):
        layout.validar(_layout(_capa_texto(), _capa_texto(z=4)), CONTRATO, familias=FAMILIAS)


def test_id_con_forma_rara_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="nombre"):
        layout.validar(_layout(_capa_texto(id="Titular Grande")), CONTRATO, familias=FAMILIAS)


def test_capa_de_texto_ligada_a_campo_no_declarado_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="no está en el diseño"):
        layout.validar(_layout(_capa_texto(campo="inventado")), CONTRATO, familias=FAMILIAS)


def test_capa_de_texto_sin_campo_ni_literal_se_rechaza():
    capa = _capa_texto()
    del capa["campo"]
    with pytest.raises(contrato.ContratoInvalido, match="qué texto"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_capa_de_texto_con_campo_y_literal_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="qué texto"):
        layout.validar(_layout(_capa_texto(texto="Hola")), CONTRATO, familias=FAMILIAS)


def test_texto_literal_si_es_valido():
    capa = _capa_texto(texto="GDL SCENE")
    del capa["campo"]
    layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_tipografia_fuera_del_catalogo_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="tipografía"):
        layout.validar(_layout(_capa_texto(fuente="Comic Sans")), CONTRATO, familias=FAMILIAS)


def test_sin_catalogo_no_se_valida_la_tipografia():
    layout.validar(_layout(_capa_texto(fuente="Comic Sans")), CONTRATO)


def test_resaltar_sobre_literal_se_rechaza():
    capa = _capa_texto(texto="Hola", resaltar=True)
    del capa["campo"]
    with pytest.raises(contrato.ContratoInvalido, match="resaltado"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_imagen_con_archivo_inseguro_se_rechaza():
    capa = {"id": "sticker", "tipo": "imagen", "x": 0, "y": 0, "w": 100, "h": 100,
            "z": 2, "archivo": "../../etc/passwd"}
    with pytest.raises(contrato.ContratoInvalido, match="archivo"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_imagen_con_campo_y_archivo_se_rechaza():
    capa = {"id": "foto", "tipo": "imagen", "x": 0, "y": 0, "w": 1080, "h": 880,
            "z": 1, "campo": "imagen", "archivo": "sticker.png"}
    with pytest.raises(contrato.ContratoInvalido, match="de dónde"):
        layout.validar(_layout(capa), CONTRATO, familias=FAMILIAS)


def test_color_invalido_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="color"):
        layout.validar(_layout(_capa_texto(color="rojo")), CONTRATO, familias=FAMILIAS)


def test_color_marca_es_valido():
    layout.validar(_layout(_capa_texto(color="marca")), CONTRATO, familias=FAMILIAS)


def test_medidas_fuera_de_rango_se_rechazan():
    with pytest.raises(contrato.ContratoInvalido, match="medida"):
        layout.validar(_layout(_capa_texto(w=99999)), CONTRATO, familias=FAMILIAS)


def test_demasiadas_capas_se_rechazan():
    capas = [_capa_texto(id=f"t{i}", z=i) for i in range(layout.MAX_CAPAS + 1)]
    with pytest.raises(contrato.ContratoInvalido, match="capas"):
        layout.validar(_layout(*capas), CONTRATO, familias=FAMILIAS)


def test_sin_capas_se_rechaza():
    with pytest.raises(contrato.ContratoInvalido, match="vacío"):
        layout.validar({**_layout(), "capas": []}, CONTRATO, familias=FAMILIAS)
```

- [ ] **Step 2: Córrelos y confirma que fallan**

```bash
.venv/bin/python -m pytest tests/test_layout_esquema.py -q
```

Esperado: `ImportError: cannot import name 'layout'`.

- [ ] **Step 3: Escribe el validador**

`src/plantillas/layout.py` (la parte de validación; el compilador llega en la Task 3):

```python
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

from .contrato import (ASPECTOS, CAMPOS_BASE, ContratoInvalido,
                       variables_declaradas)

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


def _uno_de(capa: dict[str, Any], clave: str, opciones: tuple, defecto: Any) -> Any:
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
        if isinstance(valor, bool) or not isinstance(valor, int) or not 0 <= valor <= tope:
            raise ContratoInvalido(f"la rejilla tiene un valor raro en '{clave}'")

    capas = layout.get("capas")
    if not isinstance(capas, list) or not capas:
        raise ContratoInvalido("el diseño está vacío: hay que poner al menos una capa")
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
```

**Ojo con `vacio()`:** usa la familia `"Poppins"`, que está en `config.SLIDESHOW_FUENTES` (catálogo global). Si al correr los tests resulta que no está, cambia el default por la primera familia que devuelva `fuentes_tipograficas.catalogo` en un catálogo vacío de marca — pero **no** metas `cx` en este módulo, sigue siendo puro.

- [ ] **Step 4: Corre los tests y verifica que pasan**

```bash
.venv/bin/python -m pytest tests/test_layout_esquema.py -q
ruff check src/plantillas/layout.py tests/test_layout_esquema.py
```

- [ ] **Step 5: Commit**

```bash
git add src/plantillas/layout.py tests/test_layout_esquema.py
git commit -m "feat(disenos): esquema y validación del diseño visual por capas"
```

---

### Task 3: El compilador de capas a HTML

La pieza que hace que todo lo demás valga. Determinista: el mismo layout produce siempre el mismo HTML, byte por byte.

**Files:**
- Modify: `src/plantillas/layout.py`
- Create: `tests/test_layout_compilador.py`
- Modify: `src/plantillas/contrato.py` (agregar `fotos_dir` a `CAMPOS_SISTEMA`)
- Modify: `src/plantillas/render.py:26` (inyectar `fotos_dir`)

**Interfaces:**
- Consumes: `layout.validar`, `contrato.CAMPOS_SISTEMA`, `contrato.ASPECTOS`.
- Produces:
  - `layout.a_html(layout: dict, contrato: dict, *, fuentes: list[dict] | None = None) -> str`
    donde `fuentes` es lo que devuelve `fuentes_tipograficas.catalogo(cx, account_id)`: `[{"familia": str, "archivo": str, "propia": bool}, ...]`. Si va en `None` no se emite ningún `@font-face` (útil en tests puros).
  - `contrato.CAMPOS_SISTEMA == ("fonts_dir", "fotos_dir")`

- [ ] **Step 1: Escribe los tests que fallan**

`tests/test_layout_compilador.py`:

```python
"""El diseño visual compila a HTML determinista y renderizable."""
import re

from src.plantillas import contrato, layout

CONTRATO = {
    "aspecto": "4:5",
    "base": list(contrato.CAMPOS_BASE),
    "extras": [{"id": "badge", "tipo": "texto", "etiqueta": "Etiqueta"}],
}
FUENTES = [
    {"familia": "Poppins", "archivo": "Poppins-SemiBold.ttf", "propia": False},
    {"familia": "Tinos", "archivo": "Tinos-Bold.ttf", "propia": False},
]


def _layout(*capas, aspecto="4:5"):
    base = layout.vacio(aspecto)
    if capas:
        base["capas"] = list(capas)
    return base


def test_hay_exactamente_un_nodo_card():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert html.count('class="card"') == 1


def test_el_card_mide_el_lienzo_completo():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "1080px" in html and "1350px" in html
    html916 = layout.a_html(_layout(aspecto="9:16"), {**CONTRATO, "aspecto": "9:16"},
                            fuentes=FUENTES)
    assert "1920px" in html916


def test_el_html_generado_pasa_la_validacion_del_contrato():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    contrato.validar_html(html, CONTRATO)  # no lanza


def test_es_determinista():
    l = _layout()
    assert layout.a_html(l, CONTRATO, fuentes=FUENTES) == layout.a_html(l, CONTRATO, fuentes=FUENTES)


def test_capa_de_texto_ligada_emite_la_variable():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "{{ titular }}" in html


def test_capa_con_resaltar_emite_el_filtro():
    capa = {"id": "titular", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 300,
            "z": 1, "campo": "titular", "fuente": "Tinos", "tam": 48, "resaltar": True}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "{{ titular|resaltar }}" in html
    contrato.validar_html(html, CONTRATO)


def test_texto_literal_va_escapado_y_sin_jinja():
    capa = {"id": "fijo", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 200,
            "z": 1, "texto": "<script>alert(1)</script> & \"comillas\"",
            "fuente": "Tinos", "tam": 40}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    contrato.validar_html(html, CONTRATO)


def test_capa_de_imagen_por_archivo_usa_fotos_dir():
    capa = {"id": "sticker", "tipo": "imagen", "x": 800, "y": 40, "w": 200, "h": 200,
            "z": 5, "archivo": "corazon.png", "ajuste": "contain"}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "{{ fotos_dir }}/corazon.png" in html
    contrato.validar_html(html, CONTRATO)


def test_capa_de_imagen_por_campo_usa_la_variable():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "{{ imagen }}" in html


def test_color_marca_compila_a_la_variable():
    capa = {"id": "franja", "tipo": "caja", "x": 0, "y": 800, "w": 1080, "h": 8,
            "z": 2, "color": "marca"}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "{{ color_marca }}" in html
    contrato.validar_html(html, CONTRATO)


def test_el_orden_de_apilado_sale_como_z_index():
    a = {"id": "abajo", "tipo": "caja", "x": 0, "y": 0, "w": 10, "h": 10, "z": 1,
         "color": "#000000"}
    b = {"id": "arriba", "tipo": "caja", "x": 0, "y": 0, "w": 10, "h": 10, "z": 9,
         "color": "#ffffff"}
    html = layout.a_html(_layout(b, a), CONTRATO, fuentes=FUENTES)
    # Se emiten ordenadas por z, no por el orden de la lista.
    assert html.index('id="capa-abajo"') < html.index('id="capa-arriba"')
    assert "z-index:1" in html and "z-index:9" in html


def test_auto_ajuste_solo_si_alguna_capa_lo_pide():
    con_auto = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "window.__captionFitted" in con_auto

    capa = {"id": "fijo", "tipo": "texto", "x": 0, "y": 0, "w": 1080, "h": 200,
            "z": 1, "texto": "Fijo", "fuente": "Tinos", "tam": 40, "auto": False}
    sin_auto = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "__captionFitted" not in sin_auto
    assert "<script" not in sin_auto


def test_las_font_faces_apuntan_a_fonts_dir_y_nunca_a_la_red():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "@font-face" in html
    assert "{{ fonts_dir }}" in html
    assert "http://" not in html and "https://" not in html


def test_solo_se_emiten_las_fuentes_que_el_diseno_usa():
    html = layout.a_html(_layout(), CONTRATO, fuentes=FUENTES)
    assert "Poppins" in html
    assert "Tinos-Bold" not in html


def test_rotacion_y_opacidad_salen_al_css():
    capa = {"id": "sticker", "tipo": "imagen", "x": 0, "y": 0, "w": 100, "h": 100,
            "z": 1, "archivo": "s.png", "rot": -8, "opacidad": 0.5}
    html = layout.a_html(_layout(capa), CONTRATO, fuentes=FUENTES)
    assert "rotate(-8deg)" in html
    assert "opacity:0.5" in html


def test_no_excede_el_tope_de_html():
    capas = [{"id": f"c{i}", "tipo": "caja", "x": i, "y": i, "w": 10, "h": 10,
              "z": i, "color": "#010101"} for i in range(layout.MAX_CAPAS)]
    html = layout.a_html(_layout(*capas), CONTRATO, fuentes=FUENTES)
    assert len(html) < contrato.MAX_HTML


def test_valida_antes_de_compilar():
    import pytest
    with pytest.raises(contrato.ContratoInvalido):
        layout.a_html({"v": 1, "capas": []}, CONTRATO, fuentes=FUENTES)


def test_fotos_dir_es_campo_de_sistema():
    assert "fotos_dir" in contrato.CAMPOS_SISTEMA
    assert re.search(r"fotos_dir", str(contrato.CAMPOS_SISTEMA))
```

- [ ] **Step 2: Córrelos y confirma que fallan**

```bash
.venv/bin/python -m pytest tests/test_layout_compilador.py -q
```

Esperado: `AttributeError: module 'src.plantillas.layout' has no attribute 'a_html'`.

- [ ] **Step 3: Agrega `fotos_dir` como campo de sistema**

En `src/plantillas/contrato.py:21`:

```python
# Los inyecta el motor de render, no el contrato ni el LLM.
# `fotos_dir` es la carpeta de fotos y stickers de la marca: los diseños
# visuales apuntan ahí por nombre de archivo, nunca por ruta absoluta, para
# que el mismo diseño renderice igual en la laptop y en la VM.
CAMPOS_SISTEMA: tuple[str, ...] = ("fonts_dir", "fotos_dir")
```

En `src/plantillas/render.py`, dentro de `contexto()`, junto a donde ya se inyecta `fonts_dir`, agrega `fotos_dir`. La carpeta es la misma que usa `api/routers/fuentes_api.py:200 _ruta_foto`: `config.PHOTOS_DIR / <slug de la marca>`. Emítela como URI de archivo con el mismo helper que ya se usa para las fuentes (mira cómo se arma `fonts_dir` unas líneas antes y cópialo; si `fonts_dir` sale como ruta simple, `fotos_dir` sale igual).

- [ ] **Step 4: Escribe el compilador**

Al final de `src/plantillas/layout.py`:

```python
import html as _html

_JUSTIFY = {"izq": "flex-start", "centro": "center", "der": "flex-end"}
_ALIGN = {"arriba": "flex-start", "centro": "center", "abajo": "flex-end"}

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


def _font_faces(layout: dict[str, Any], fuentes: list[dict[str, Any]] | None) -> str:
    """Solo las tipografías que el diseño usa de verdad.

    Emitir el catálogo entero engorda el HTML y hace que Chromium cargue
    archivos que nadie pide. `fonts_dir` lo inyecta el render, así que la ruta
    sale como variable Jinja y el diseño no depende de dónde esté instalado.
    """
    if not fuentes:
        return ""
    usadas = {_fuente_de(c) for c in layout["capas"] if c.get("tipo") == "texto"}
    piezas = []
    for f in sorted(fuentes, key=lambda x: x["familia"]):
        if f["familia"] not in usadas:
            continue
        ruta = f["archivo"] if f.get("propia") else "{{ fonts_dir }}/" + f["archivo"]
        piezas.append(
            f"@font-face{{font-family:'{f['familia']}';src:url('{ruta}');"
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
        f"font-family:'{capa['fuente']}',sans-serif",
        f"font-size:{capa['tam']}px",
        f"font-weight:{capa.get('peso', 400)}",
        f"color:{_css_color(capa.get('color', '#000000'))}",
        f"line-height:{capa.get('interlinea', 1.2):g}",
        f"text-align:{ {'izq': 'left', 'centro': 'center', 'der': 'right'}[capa.get('alinear', 'centro')] }",
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
```

- [ ] **Step 5: Corre los tests y verifica que pasan**

```bash
.venv/bin/python -m pytest tests/test_layout_compilador.py -q
.venv/bin/python -m pytest tests/test_contrato_plantilla.py tests/test_plantillas_render.py tests/test_equivalencia_plantillas.py -q
ruff check src/ tests/ api/ web/ config.py
```

Los tres archivos del segundo comando son la red: `fotos_dir` cambió `CAMPOS_SISTEMA` y eso toca validación y render. Si `test_equivalencia_plantillas.py` se pone rojo, `contexto()` está inyectando algo que antes no inyectaba y hay que revisar el paso 3.

- [ ] **Step 6: Renderiza uno de verdad y míralo**

No basta con que los tests pasen: hay que ver el PNG. Desde el worktree:

```bash
.venv/bin/python - <<'PY'
from src.plantillas import layout, contrato
from src import compose
c = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
html = layout.a_html(layout.vacio("4:5"), c)
html = html.replace("{{ imagen }}", "").replace("{{ titular }}", "Prueba de compilador")
html = html.replace("{{ color_marca }}", "#1b5e3f").replace("{{ fonts_dir }}", "templates/assets/fonts")
print(compose.render_html(html, aspecto="4:5", prefix="layout_smoke"))
PY
```

Abre el PNG que imprime. Tiene que medir 1080×1350 y verse el titular centrado. Si sale en blanco, el `.card` no está midiendo bien.

- [ ] **Step 7: Commit**

```bash
git add src/plantillas/layout.py src/plantillas/contrato.py src/plantillas/render.py tests/test_layout_compilador.py
git commit -m "feat(disenos): compilador determinista de capas a HTML"
```

---

### Task 4: El layout es la fuente de verdad al guardar

Hasta ahora el layout se guardaba pero nadie lo compilaba. Aquí se cierra el circuito: si un diseño trae layout, el HTML se **deriva** de él y lo que mande el llamador se ignora. De paso se conectan dos validaciones que están escritas y nadie llama.

**Files:**
- Modify: `src/plantillas/__init__.py:27` (`_validado`), `:34` (`crear`), `:52` (`nueva_version`)
- Modify: `src/plantillas/contrato.py:182` (`validar_html` exige `.card`)
- Modify: `src/plantillas/preview.py:75-76` (clave de caché)
- Test: `tests/test_plantillas.py`, `tests/test_contrato_plantilla.py`

**Interfaces:**
- Consumes: `layout.a_html`, `layout.validar`, `fuentes_tipograficas.catalogo`, `contrato.validar_fuentes`.
- Produces: `crear` y `nueva_version` con `layout=` compilan y guardan el HTML derivado. `contrato.validar_html` rechaza HTML sin `.card`.

- [ ] **Step 1: Escribe los tests que fallan**

En `tests/test_contrato_plantilla.py`:

```python
def test_html_sin_card_se_rechaza():
    html = "<html><body><div class='otra'>{{ titular }}</div></body></html>"
    with pytest.raises(contrato.ContratoInvalido, match="card"):
        contrato.validar_html(html, CONTRATO_BASE)
```

Usa el nombre de contrato que ya exista en ese archivo. En `tests/test_plantillas.py`:

```python
def test_con_layout_el_html_se_deriva_y_se_ignora_el_que_mandan(cx_tmp):
    layout_ = layout.vacio("4:5")
    tid = plantillas.crear(cx_tmp, 1, "Derivado", "<p>basura que se ignora</p>",
                           CONTRATO_MINIMO, layout=layout_)
    fila = plantillas.obtener(cx_tmp, tid)
    assert "basura" not in fila["html"]
    assert 'class="card"' in fila["html"]
    assert "{{ titular }}" in fila["html"]


def test_sin_layout_el_html_se_guarda_tal_cual(cx_tmp):
    tid = plantillas.crear(cx_tmp, 1, "Legacy", HTML_MINIMO, CONTRATO_MINIMO)
    assert plantillas.obtener(cx_tmp, tid)["html"] == HTML_MINIMO


def test_layout_invalido_no_se_guarda(cx_tmp):
    malo = {**layout.vacio("4:5"), "capas": []}
    with pytest.raises(contrato.ContratoInvalido):
        plantillas.crear(cx_tmp, 1, "Malo", "", CONTRATO_MINIMO, layout=malo)
    assert plantillas.listar(cx_tmp, 1) == []


def test_tipografia_fuera_del_catalogo_de_la_marca_no_se_guarda(cx_tmp):
    l = layout.vacio("4:5")
    l["capas"][1]["fuente"] = "Papyrus"
    with pytest.raises(contrato.ContratoInvalido, match="tipografía"):
        plantillas.crear(cx_tmp, 1, "Papyrus", "", CONTRATO_MINIMO, layout=l)


def test_fuente_propia_de_la_marca_si_se_acepta(cx_tmp):
    db.insert(cx_tmp, "brand_fonts", account_id=1, familia="Papyrus",
              archivo="papyrus.woff2")
    cx_tmp.commit()
    l = layout.vacio("4:5")
    l["capas"][1]["fuente"] = "Papyrus"
    tid = plantillas.crear(cx_tmp, 1, "Papyrus", "", CONTRATO_MINIMO, layout=l)
    assert "Papyrus" in plantillas.obtener(cx_tmp, tid)["html"]
```

Y en el mismo archivo, para la caché de preview:

```python
def test_el_preview_se_recalcula_si_cambia_solo_el_layout(cx_tmp, monkeypatch):
    """Dos layouts distintos que compilan a HTMLs distintos no comparten PNG."""
    from src.plantillas import preview
    l1 = layout.vacio("4:5")
    l2 = {**l1, "lienzo": {"fondo": "#123456"}}
    tid = plantillas.crear(cx_tmp, 1, "Cacheada", "", CONTRATO_MINIMO, layout=l1)
    c1 = preview.clave_de(plantillas.obtener(cx_tmp, tid))
    plantillas.nueva_version(cx_tmp, tid, "", CONTRATO_MINIMO, layout=l2)
    c2 = preview.clave_de(plantillas.obtener(cx_tmp, tid))
    assert c1 != c2
```

- [ ] **Step 2: Córrelos y confirma que fallan**

```bash
.venv/bin/python -m pytest tests/test_plantillas.py tests/test_contrato_plantilla.py -q
```

- [ ] **Step 3: `validar_html` exige el nodo `.card`**

En `src/plantillas/contrato.py`, dentro de `validar_html`, justo después del chequeo de `MAX_HTML`:

```python
    # El motor fotografía el nodo `.card` (src/compose.py:191). Sin él, el
    # render no falla: devuelve un PNG vacío, que es mucho peor.
    if 'class="card"' not in (html or "") and "class='card'" not in (html or ""):
        raise ContratoInvalido(
            "el diseño no tiene el marco de la imagen (falta el bloque card)")
```

- [ ] **Step 4: `_validado` compila y valida tipografías**

En `src/plantillas/__init__.py`:

```python
def _validado(cx, account_id: int, html: str, contrato_dict: dict[str, Any],
              layout_dict: dict[str, Any] | None) -> tuple[str, str]:
    """Valida todo y devuelve (html definitivo, contrato serializado).

    Con layout, el HTML es un artefacto derivado: se compila aquí y se ignora
    el que haya mandado el llamador. Sin layout es un diseño legacy escrito a
    mano y el HTML pasa tal cual.
    """
    _contrato.validar(contrato_dict)
    fuentes = fuentes_tipograficas.catalogo(cx, account_id)
    if layout_dict is not None:
        html = _layout.a_html(layout_dict, contrato_dict, fuentes=fuentes)
    _contrato.validar_html(html, contrato_dict)
    _contrato.validar_fuentes(
        html, {f["familia"] for f in fuentes},
        archivos={f["archivo"] for f in fuentes})
    return html, json.dumps(contrato_dict, ensure_ascii=False)
```

Importa arriba: `from . import contrato as _contrato, layout as _layout, fuentes_tipograficas`.

**Cuidado con la firma:** `_validado` cambió de `(html, contrato)` a `(cx, account_id, html, contrato, layout)`. Busca todos sus llamadores (`grep -rn "_validado" src/ tests/`) y ajústalos. `nueva_version` no recibe `account_id`; sácalo con `obtener(cx, template_id)["account_id"]`.

**Cuidado con `validar_fuentes` en modo legacy:** las 4 plantillas de gdlscene declaran familias en su `@font-face` que sí están en el catálogo global, así que deberían pasar. Si alguna no pasa, **no relajes el validador**: llámalo solo cuando hay layout (`if layout_dict is not None:` envolviendo la línea de `validar_fuentes`) y anota el porqué en un comentario. El objetivo del hito es blindar lo nuevo, no romper lo viejo.

- [ ] **Step 5: Extrae la clave de caché del preview**

En `src/plantillas/preview.py`, saca la clave a una función pública para poder testearla sin renderizar:

```python
def clave_de(fila: dict[str, Any]) -> str:
    """Huella del contenido de un diseño. Si cambia, el PNG se rehace.

    Incluye el layout aunque el HTML se derive de él: así un cambio que no
    altere el HTML (por ejemplo la rejilla) tampoco resucita un PNG viejo por
    accidente.
    """
    crudo = f"{fila['html']}{fila['contrato_json']}{fila.get('layout_json') or ''}"
    return hashlib.sha1(crudo.encode()).hexdigest()[:12]
```

Y en `png_de`, reemplaza el cálculo inline de las líneas 75-76 por `clave = clave_de(fila)`.

- [ ] **Step 6: Corre la suite de plantillas completa**

```bash
.venv/bin/python -m pytest tests/test_plantillas.py tests/test_contrato_plantilla.py \
  tests/test_contrato_campos.py tests/test_equivalencia_plantillas.py \
  tests/test_plantillas_render.py tests/test_templates.py \
  tests/test_layout_esquema.py tests/test_layout_compilador.py -q
ruff check src/ tests/ api/ web/ config.py
```

`test_equivalencia_plantillas.py` es el que importa: si se pone rojo, el requisito de `.card` o `validar_fuentes` está rechazando una plantilla publicada y hay que arreglar el validador, no la plantilla.

- [ ] **Step 7: Commit**

```bash
git add src/plantillas/ tests/test_plantillas.py tests/test_contrato_plantilla.py
git commit -m "feat(disenos): el layout manda — el HTML se deriva al guardar"
```

---

### Task 5: Los endpoints de diseños

De 2 endpoints a 12. Todo con `minimo="manager"` salvo los dos que ya existen, y todo pasando por `_plantilla_de_marca` para que una marca no pueda tocar el diseño de otra.

**Files:**
- Modify: `api/routers/plantillas.py`
- Create: `tests/test_disenos_web.py`

**Interfaces:**
- Consumes: `plantillas.*`, `layout.vacio`, `fuentes_tipograficas.catalogo`, `deps.marca_para`.
- Produces (todos bajo `/brands/{slug}`):

| Método | Ruta | Rol | Qué hace |
|---|---|---|---|
| GET | `/templates` | editor | Lista. Acepta `?estado=activa\|borrador\|archivada`. Sin `estado`, solo activas (comportamiento de hoy, no lo cambies). |
| GET | `/templates/{tid}` | manager | Un diseño con `layout`, `contrato` y `editable`. |
| POST | `/templates` | manager | Crea. Body `{nombre, aspecto, layout?, contrato?}`. Sin `layout` usa `layout.vacio(aspecto)`. |
| PATCH | `/templates/{tid}` | manager | Guarda una versión nueva. Body `{layout, contrato?, mensaje?}`. |
| POST | `/templates/{tid}/duplicate` | manager | Copia. Para los legacy: `layout=None` → `layout.vacio(aspecto)` y nombre `"<nombre> (editable)"`. |
| GET | `/templates/{tid}/versions` | manager | Historial. |
| POST | `/templates/{tid}/revert/{n}` | manager | Revierte. |
| POST | `/templates/{tid}/activate` | manager | Publica. |
| POST | `/templates/{tid}/archive` | manager | Archiva. |
| GET | `/templates/{tid}/preview.png` | editor | El de hoy, sin cambios. |
| GET | `/fonts` | manager | `[{familia, propia}]` para el selector de tipografía. |
| GET | `/stickers` | manager | `[{nombre, url}]` — las fotos de la marca, reutilizando `GET /photos`. |

- [ ] **Step 1: Escribe los tests que fallan**

`tests/test_disenos_web.py`. Copia el arranque (fixtures de cliente y de marca, cómo se autentica) de `tests/test_templates.py` — **no inventes un esquema de auth nuevo**.

```python
"""Los endpoints del editor de diseños."""
from src.plantillas import layout


def test_crear_diseno_arranca_con_un_lienzo_vacio(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates",
                             json={"nombre": "Nuevo", "aspecto": "4:5"})
    assert r.status_code == 201
    datos = r.json()
    assert datos["editable"] is True
    assert len(datos["layout"]["capas"]) == 2


def test_un_editor_no_puede_crear_disenos(cliente_editor, marca):
    r = cliente_editor.post(f"/brands/{marca}/templates",
                            json={"nombre": "Nuevo", "aspecto": "4:5"})
    assert r.status_code == 403


def test_guardar_crea_una_version_nueva(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    l = layout.vacio("4:5")
    l["capas"][1]["tam"] = 90
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}",
                              json={"layout": l, "mensaje": "Titular más grande"})
    assert r.status_code == 200
    assert r.json()["version_actual"] == 2
    versiones = cliente_manager.get(f"/brands/{marca}/templates/{tid}/versions").json()
    assert len(versiones) == 2
    assert versiones[0]["mensaje"] == "Titular más grande"


def test_guardar_un_diseno_invalido_explica_el_problema(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    l = layout.vacio("4:5")
    l["capas"][1]["fuente"] = "Papyrus"
    r = cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": l})
    assert r.status_code == 422
    assert "tipograf" in r.json()["detail"].lower()


def test_revertir_recupera_la_version_anterior(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    l = layout.vacio("4:5")
    l["capas"][1]["tam"] = 90
    cliente_manager.patch(f"/brands/{marca}/templates/{tid}", json={"layout": l})
    r = cliente_manager.post(f"/brands/{marca}/templates/{tid}/revert/1")
    assert r.status_code == 200
    assert r.json()["layout"]["capas"][1]["tam"] == 64


def test_un_diseno_legacy_se_ve_pero_no_se_edita(cliente_manager, marca, plantilla_legacy):
    r = cliente_manager.get(f"/brands/{marca}/templates/{plantilla_legacy}")
    assert r.status_code == 200
    assert r.json()["editable"] is False
    assert r.json()["layout"] is None


def test_duplicar_un_legacy_lo_vuelve_editable(cliente_manager, marca, plantilla_legacy):
    r = cliente_manager.post(f"/brands/{marca}/templates/{plantilla_legacy}/duplicate")
    assert r.status_code == 201
    assert r.json()["editable"] is True
    assert "editable" in r.json()["nombre"]


def test_no_se_puede_tocar_el_diseno_de_otra_marca(cliente_manager, marca, diseno_ajeno):
    r = cliente_manager.get(f"/brands/{marca}/templates/{diseno_ajeno}")
    assert r.status_code == 404


def test_activar_y_archivar(cliente_manager, marca):
    tid = cliente_manager.post(f"/brands/{marca}/templates",
                               json={"nombre": "V", "aspecto": "4:5"}).json()["id"]
    assert cliente_manager.post(
        f"/brands/{marca}/templates/{tid}/activate").json()["estado"] == "activa"
    assert cliente_manager.post(
        f"/brands/{marca}/templates/{tid}/archive").json()["estado"] == "archivada"


def test_la_lista_por_defecto_solo_trae_activas(cliente_editor, cliente_manager, marca):
    cliente_manager.post(f"/brands/{marca}/templates",
                         json={"nombre": "Borrador", "aspecto": "4:5"})
    nombres = [p["nombre"] for p in
               cliente_editor.get(f"/brands/{marca}/templates").json()]
    assert "Borrador" not in nombres
    nombres = [p["nombre"] for p in cliente_manager.get(
        f"/brands/{marca}/templates?estado=borrador").json()]
    assert "Borrador" in nombres


def test_el_catalogo_de_tipografias(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/fonts")
    assert r.status_code == 200
    assert all({"familia", "propia"} <= set(f) for f in r.json())
    assert len(r.json()) > 0


def test_los_stickers_son_las_fotos_de_la_marca(cliente_manager, marca):
    r = cliente_manager.get(f"/brands/{marca}/stickers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

Las fixtures `cliente_manager`, `cliente_editor`, `marca`, `plantilla_legacy` y `diseno_ajeno` las defines tú al inicio del archivo, basándote en cómo lo hace `tests/test_templates.py`. `plantilla_legacy` = `plantillas.crear(...)` sin `layout`. `diseno_ajeno` = un diseño de otro `account_id`.

- [ ] **Step 2: Córrelos y confirma que fallan**

```bash
.venv/bin/python -m pytest tests/test_disenos_web.py -q
```

- [ ] **Step 3: Escribe los endpoints**

En `api/routers/plantillas.py`, sobre lo que ya está. Los cuerpos de request van con Pydantic, siguiendo el estilo de los otros routers:

```python
class DisenoNuevo(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    aspecto: str = Field(pattern="^(4:5|9:16)$")
    layout: dict[str, Any] | None = None
    contrato: dict[str, Any] | None = None


class DisenoGuardado(BaseModel):
    layout: dict[str, Any]
    contrato: dict[str, Any] | None = None
    mensaje: str | None = Field(default=None, max_length=200)
```

Serializador único, para que la forma que ve el frontend sea siempre la misma:

```python
def _vista(fila) -> dict[str, Any]:
    """Cómo ve el portal un diseño. Nunca expone el HTML: es derivado."""
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "descripcion": fila["descripcion"],
        "aspecto": fila["aspecto"],
        "estado": fila["estado"],
        "version_actual": fila["version_actual"],
        "contrato": plantillas.contrato_de(fila),
        "layout": plantillas.layout_de(fila),
        "editable": plantillas.es_editable(fila),
    }
```

El contrato por defecto al crear (cuando el body no trae `contrato`):

```python
    contrato_dict = cuerpo.contrato or {
        "aspecto": cuerpo.aspecto,
        "base": list(contrato_mod.CAMPOS_BASE),
        "extras": [],
    }
```

Traduce `ContratoInvalido` a un 422 con el mensaje tal cual, que ya está escrito en español para humanos:

```python
    try:
        tid = plantillas.crear(cx, marca["account_id"], cuerpo.nombre, "",
                               contrato_dict, layout=layout_dict,
                               creado_por=user["id"])
    except contrato_mod.ContratoInvalido as exc:
        raise HTTPException(422, str(exc)) from exc
```

`GET /stickers` reusa la carpeta de fotos que ya sirve `fuentes_api`: lista `config.PHOTOS_DIR / marca["slug"]` y devuelve `{"nombre": n, "url": f"/api/brands/{slug}/files/fotos/{n}"}`. No dupliques la lógica de listado: si `fuentes_api` tiene un helper para eso, impórtalo.

El historial se serializa con el nombre que entiende una persona: la columna es
`mensaje_usuario` y hacia afuera se llama `mensaje`. El `PATCH` hace el camino inverso:
`plantillas.nueva_version(..., mensaje_usuario=cuerpo.mensaje)`.

```python
def _version_vista(fila) -> dict[str, Any]:
    return {"version": fila["version"], "mensaje": fila["mensaje_usuario"],
            "creado_en": fila["creado_en"], "creado_por": fila["creado_por"]}
```

Ajusta los nombres de columna a los que realmente tenga `template_versions` (`src/schema.sql:516-560`).

Todos los endpoints nuevos: `marca = Depends(...)` con `minimo="manager"`, y el `tid` resuelto con `_plantilla_de_marca(cx, marca["account_id"], tid)` que ya existe en `:15` y lanza 404 si no es de la marca.

- [ ] **Step 4: Corre los tests**

```bash
.venv/bin/python -m pytest tests/test_disenos_web.py tests/test_templates.py -q
ruff check src/ tests/ api/ web/ config.py
```

- [ ] **Step 5: Commit**

```bash
git add api/routers/plantillas.py tests/test_disenos_web.py
git commit -m "feat(disenos): endpoints de edición, versiones, tipografías y stickers"
```

---

### Task 6: Vista previa de un diseño sin guardar

El editor necesita enseñar cómo queda de verdad —con Chromium, con las tipografías cargadas— antes de guardar. Como Playwright tarda segundos, va por la maquinaria de trabajos que ya existe.

**Files:**
- Modify: `src/jobs/handlers.py` (nuevo handler + registro en `HANDLERS:490`)
- Modify: `api/routers/plantillas.py`
- Modify: `tests/test_disenos_web.py`

**Interfaces:**
- Consumes: `jobs.crear`, `jobs.progresar`, `layout.a_html`, `compose.render_html`, `preview.campos_de_muestra`.
- Produces:
  - `handlers.template_preview(cx, job) -> dict` — payload `{"template_id": int|None, "layout": dict, "contrato": dict, "aspecto": str}`; devuelve `{"url": "/api/brands/<slug>/files/previews/<nombre>.png"}`.
  - `HANDLERS["template.preview"] = template_preview`
  - `POST /brands/{slug}/templates/preview` (manager) → `{"job_id": int}`.

- [ ] **Step 1: Escribe los tests que fallan**

En `tests/test_disenos_web.py`:

```python
def test_pedir_vista_previa_encola_un_trabajo(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": layout.vacio("4:5"), "aspecto": "4:5"})
    assert r.status_code == 202
    assert isinstance(r.json()["job_id"], int)


def test_una_vista_previa_invalida_se_rechaza_al_encolar(cliente_manager, marca):
    """No se encola trabajo para un diseño que ya sabemos que no compila."""
    malo = {**layout.vacio("4:5"), "capas": []}
    r = cliente_manager.post(f"/brands/{marca}/templates/preview",
                             json={"layout": malo, "aspecto": "4:5"})
    assert r.status_code == 422
```

Y en el archivo de handlers de trabajos que ya exista (`tests/test_jobs*.py` — usa el que tenga los tests de `preset_preview`):

```python
def test_template_preview_genera_un_png(cx_tmp, marca_seed):
    from src.jobs import handlers
    from src.plantillas import contrato, layout
    payload = {
        "layout": layout.vacio("4:5"),
        "contrato": {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE),
                     "extras": []},
        "aspecto": "4:5",
    }
    job = _job_falso(cx_tmp, "template.preview", payload, account_id=1)
    salida = handlers.template_preview(cx_tmp, job)
    assert salida["url"].endswith(".png")
    ruta = config.BASE_DIR / "data" / "previews" / marca_seed / salida["url"].split("/")[-1]
    assert ruta.exists() and ruta.stat().st_size > 1000
```

`_job_falso` es el helper que ya usan los tests de `preset_preview`; si no existe con ese nombre, usa el que sí.

- [ ] **Step 2: Córrelos y confirma que fallan**

- [ ] **Step 3: Escribe el handler**

En `src/jobs/handlers.py`, calcado de `preset_preview:317`:

```python
def template_preview(cx, job) -> dict[str, Any]:
    """Foto de cómo queda un diseño con datos de muestra, sin guardarlo.

    El editor lo usa para el botón de vista previa: compila el layout que
    tiene en pantalla, lo renderiza con Chromium y devuelve el PNG. Nada de
    esto toca la plantilla guardada.
    """
    payload = json.loads(job["payload_json"] or "{}")
    slug = _marca_de(cx, job["account_id"])
    contrato_dict = payload["contrato"]
    jobs.progresar(cx, job["id"], 20, "Armando el diseño")

    fuentes = fuentes_tipograficas.catalogo(cx, job["account_id"])
    html = layout.a_html(payload["layout"], contrato_dict, fuentes=fuentes)
    campos = preview.campos_de_muestra(contrato_dict)
    jobs.progresar(cx, job["id"], 50, "Tomando la foto")

    marca = db.get(cx, "accounts", job["account_id"])
    png = render.render(cx, marca, {"html": html, "contrato_json": json.dumps(contrato_dict)},
                        campos, prefix="tpl_edit")

    nombre = f"edit_{job['id']}.png"
    destino = config.BASE_DIR / "data" / "previews" / slug / nombre
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(png, destino)
    jobs.progresar(cx, job["id"], 100, "Listo")
    return {"url": f"/api/brands/{slug}/files/previews/{nombre}"}
```

**Ajusta la llamada a `render.render`** a su firma real (`render(cx, marca, plantilla, campos, *, out_path=None, row_id=None)` — `plantilla` es la fila de la plantilla, así que quizá te convenga llamar directo a `compose.render_html(html, aspecto=...)` después de renderizar el Jinja con `render.contexto(marca, campos, fonts_dir=...)`). Léela antes de escribir y usa el camino más corto que **no** duplique la construcción del contexto.

Regístralo en `HANDLERS`:

```python
    "template.preview": template_preview,
```

- [ ] **Step 4: El endpoint que encola**

En `api/routers/plantillas.py`:

```python
@router.post("/brands/{slug}/templates/preview", status_code=202)
def vista_previa(slug: str, cuerpo: VistaPrevia, cx=Depends(get_cx),
                 marca=Depends(...)):  # minimo="manager"
    contrato_dict = cuerpo.contrato or {
        "aspecto": cuerpo.aspecto, "base": list(contrato_mod.CAMPOS_BASE),
        "extras": [],
    }
    # Se valida aquí, no en el worker: un diseño roto debe dar error en
    # pantalla al instante, no un trabajo que falla treinta segundos después.
    try:
        layout_mod.validar(
            cuerpo.layout, contrato_dict,
            familias=fuentes_tipograficas.familias(cx, marca["account_id"]))
    except contrato_mod.ContratoInvalido as exc:
        raise HTTPException(422, str(exc)) from exc
    job_id = jobs.crear(cx, marca["account_id"], "template.preview",
                        {"layout": cuerpo.layout, "contrato": contrato_dict,
                         "aspecto": cuerpo.aspecto})
    cx.commit()
    return {"job_id": job_id}
```

Ajusta la firma de `jobs.crear` a la real (`src/jobs/__init__.py:37`).

- [ ] **Step 5: Corre los tests**

```bash
.venv/bin/python -m pytest tests/test_disenos_web.py -q
.venv/bin/python -m pytest tests/ -k "job or worker" -q
ruff check src/ tests/ api/ web/ config.py
```

- [ ] **Step 6: Commit**

```bash
git add src/jobs/handlers.py api/routers/plantillas.py tests/
git commit -m "feat(disenos): vista previa real de un diseño sin guardar"
```

---

### Task 7: El diseñador con DeepSeek escupe capas, no HTML

Reemplaza las tareas 4-5 del plan de H3. El LLM ya no escribe HTML libre: devuelve `layout_json`, que se valida antes de tocar nada. Si devuelve basura, se reintenta con el error como contexto; si sigue fallando, se rinde con un mensaje entendible.

**Files:**
- Create: `src/plantillas/disenador.py`
- Create: `tests/test_disenador_llm.py`
- Modify: `src/jobs/handlers.py`

**Interfaces:**
- Consumes: `layout.validar`, `layout.vacio`, `slideshow_script._via_anthropic/_via_deepseek` (vía `_pedir_al_llm`).
- Produces:
  - `disenador._pedir_al_llm(prompt: str) -> str` — **el punto de monkeypatch de los tests. Cero llamadas reales al LLM en la suite.**
  - `disenador.disenar(*, marca, contrato, instruccion, base=None, familias=None, stickers=None, intentos=3) -> dict` — devuelve un layout válido o lanza `ContratoInvalido`.
  - `handlers.template_disenar(cx, job) -> dict` — payload `{"template_id": int|None, "instruccion": str, "aspecto": str}`; devuelve `{"layout": {...}, "mensaje": str}`.
  - `HANDLERS["template.disenar"] = template_disenar`
  - `POST /brands/{slug}/templates/design` (manager) → `{"job_id": int}`.

- [ ] **Step 1: Escribe los tests que fallan**

`tests/test_disenador_llm.py`:

```python
"""El diseñador con LLM. Cero llamadas reales: siempre monkeypatch."""
import json

import pytest

from src.plantillas import contrato, disenador, layout

CONTRATO = {"aspecto": "4:5", "base": list(contrato.CAMPOS_BASE), "extras": []}
MARCA = {"nombre": "GDL Scene", "color_marca": "#1b5e3f", "handle": "gdlscene"}
FAMILIAS = {"Poppins", "Tinos"}


def _respuesta(l):
    return json.dumps(l, ensure_ascii=False)


def test_devuelve_el_layout_que_manda_el_llm(monkeypatch):
    bueno = layout.vacio("4:5")
    monkeypatch.setattr(disenador, "_pedir_al_llm", lambda p: _respuesta(bueno))
    assert disenador.disenar(marca=MARCA, contrato=CONTRATO,
                             instruccion="algo minimalista",
                             familias=FAMILIAS) == bueno


def test_tolera_el_json_envuelto_en_bloque_de_codigo(monkeypatch):
    bueno = layout.vacio("4:5")
    monkeypatch.setattr(disenador, "_pedir_al_llm",
                        lambda p: "```json\n" + _respuesta(bueno) + "\n```")
    assert disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="x",
                             familias=FAMILIAS) == bueno


def test_reintenta_cuando_el_layout_no_valida(monkeypatch):
    malo = {**layout.vacio("4:5"), "capas": []}
    bueno = layout.vacio("4:5")
    respuestas = [_respuesta(malo), _respuesta(bueno)]
    vistos = []

    def falso(prompt):
        vistos.append(prompt)
        return respuestas.pop(0)

    monkeypatch.setattr(disenador, "_pedir_al_llm", falso)
    assert disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="x",
                             familias=FAMILIAS) == bueno
    assert len(vistos) == 2
    # El segundo intento le dice qué salió mal.
    assert "vacío" in vistos[1]


def test_se_rinde_despues_de_los_intentos(monkeypatch):
    monkeypatch.setattr(disenador, "_pedir_al_llm", lambda p: "no soy json")
    with pytest.raises(contrato.ContratoInvalido):
        disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="x",
                          familias=FAMILIAS, intentos=2)


def test_el_prompt_lleva_las_tipografias_y_los_datos_disponibles(monkeypatch):
    visto = {}

    def falso(prompt):
        visto["p"] = prompt
        return _respuesta(layout.vacio("4:5"))

    monkeypatch.setattr(disenador, "_pedir_al_llm", falso)
    disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="algo verde",
                      familias=FAMILIAS, stickers=["corazon.png"])
    p = visto["p"]
    assert "Poppins" in p and "Tinos" in p
    assert "titular" in p and "imagen" in p
    assert "corazon.png" in p
    assert "1080" in p and "1350" in p
    assert "algo verde" in p


def test_partir_de_un_diseno_existente_lo_manda_como_base(monkeypatch):
    visto = {}
    base = layout.vacio("4:5")
    base["capas"][1]["id"] = "mi_titular_raro"

    def falso(prompt):
        visto["p"] = prompt
        return _respuesta(layout.vacio("4:5"))

    monkeypatch.setattr(disenador, "_pedir_al_llm", falso)
    disenador.disenar(marca=MARCA, contrato=CONTRATO, instruccion="hazlo más grande",
                      base=base, familias=FAMILIAS)
    assert "mi_titular_raro" in visto["p"]
```

- [ ] **Step 2: Córrelos y confirma que fallan**

- [ ] **Step 3: Escribe el diseñador**

`src/plantillas/disenador.py`:

```python
"""El diseñador con LLM: convierte una instrucción en capas.

Antes el LLM escribía HTML libre y el motor lo renderizaba sin sandbox. Ahora
devuelve `layout_json`, que se valida contra un esquema cerrado antes de tocar
nada: lo peor que puede pasar es que el diseño se vea feo, no que ejecute algo.

`_pedir_al_llm` es el único punto que habla con el proveedor. Los tests lo
monkeypatchean; **la suite nunca llama al LLM de verdad**.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import layout as _layout
from .contrato import ASPECTOS, ContratoInvalido, variables_declaradas

_BLOQUE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)


def _pedir_al_llm(prompt: str) -> str:
    """Único punto de contacto con el proveedor. Espejo de generador._pedir_al_llm."""
    import config
    from src import slideshow_script

    if config.LLM_PROVIDER == "anthropic":
        return slideshow_script._via_anthropic(prompt)
    return slideshow_script._via_deepseek(prompt)


def _json_de(crudo: str) -> dict[str, Any]:
    """El LLM a veces envuelve el JSON en un bloque de código o lo rodea de prosa."""
    texto = (crudo or "").strip()
    bloque = _BLOQUE.search(texto)
    if bloque:
        texto = bloque.group(1)
    inicio, fin = texto.find("{"), texto.rfind("}")
    if inicio == -1 or fin <= inicio:
        raise ContratoInvalido("la respuesta no trae un diseño")
    return json.loads(texto[inicio:fin + 1])


def _prompt(*, marca, contrato, instruccion, base, familias, stickers, error) -> str:
    ancho, alto = ASPECTOS[contrato["aspecto"]]
    datos = ", ".join(sorted(variables_declaradas(contrato)))
    tipos = ", ".join(sorted(familias or []))
    stk = ", ".join(stickers or []) or "(ninguno)"
    partes = [
        f"Eres director de arte de la marca {marca.get('nombre')}. "
        f"Su color es {marca.get('color_marca')}.",
        f"Diseña una publicación de {ancho}x{alto} píxeles.",
        "Responde SOLO con un objeto JSON, sin explicaciones ni bloques de código.",
        "",
        "Formato exacto del JSON:",
        json.dumps(_layout.vacio(contrato["aspecto"]), ensure_ascii=False, indent=1),
        "",
        f"Tipos de capa: {list(_layout.TIPOS_CAPA)}.",
        "Una capa de texto lleva 'campo' (un dato del diseño) o 'texto' (fijo), "
        "nunca los dos. Una capa de imagen lleva 'campo' o 'archivo', nunca los dos.",
        f"Datos disponibles para 'campo': {datos}.",
        f"Tipografías permitidas: {tipos}. No inventes otras.",
        f"Stickers disponibles para 'archivo': {stk}.",
        "Los colores son #rrggbb o la palabra 'marca'.",
        f"Todo debe caber en {ancho}x{alto}. Máximo {_layout.MAX_CAPAS} capas.",
        "",
        f"Lo que se pide: {instruccion}",
    ]
    if base:
        partes += ["", "Parte de este diseño y modifícalo:",
                   json.dumps(base, ensure_ascii=False)]
    if error:
        partes += ["", f"Tu respuesta anterior no sirvió: {error}. Corrígelo."]
    return "\n".join(partes)


def disenar(*, marca: dict[str, Any], contrato: dict[str, Any], instruccion: str,
            base: dict[str, Any] | None = None, familias: set[str] | None = None,
            stickers: list[str] | None = None, intentos: int = 3) -> dict[str, Any]:
    """Una instrucción en español entra, un diseño válido sale.

    Reintenta pasándole al modelo el error exacto: en la práctica corrige a la
    segunda. Si no, lanza ContratoInvalido con el último problema, que ya está
    redactado para que lo lea una persona.
    """
    error: str | None = None
    for _ in range(max(1, intentos)):
        crudo = _pedir_al_llm(_prompt(
            marca=marca, contrato=contrato, instruccion=instruccion, base=base,
            familias=familias, stickers=stickers, error=error))
        try:
            propuesta = _json_de(crudo)
            _layout.validar(propuesta, contrato, familias=familias)
            return propuesta
        except (ContratoInvalido, json.JSONDecodeError, TypeError, KeyError) as exc:
            error = str(exc)
    raise ContratoInvalido(f"no se pudo armar el diseño: {error}")
```

- [ ] **Step 4: El trabajo y el endpoint**

En `src/jobs/handlers.py`:

```python
def template_disenar(cx, job) -> dict[str, Any]:
    """Le pide un diseño al modelo y devuelve las capas, sin guardarlas.

    Guardar es decisión de la persona: el chat propone, el editor dispone.
    """
    payload = json.loads(job["payload_json"] or "{}")
    marca = db.get(cx, "accounts", job["account_id"])
    jobs.progresar(cx, job["id"], 20, "Pensando el diseño")

    base = None
    contrato_dict = payload.get("contrato")
    if payload.get("template_id"):
        fila = plantillas.obtener(cx, payload["template_id"])
        base = plantillas.layout_de(fila)
        contrato_dict = contrato_dict or plantillas.contrato_de(fila)
    if not contrato_dict:
        contrato_dict = {"aspecto": payload["aspecto"],
                         "base": list(contrato_mod.CAMPOS_BASE), "extras": []}

    propuesta = disenador.disenar(
        marca=marca, contrato=contrato_dict, instruccion=payload["instruccion"],
        base=base, familias=fuentes_tipograficas.familias(cx, job["account_id"]),
        stickers=_stickers_de(cx, job["account_id"]))
    jobs.progresar(cx, job["id"], 100, "Listo")
    return {"layout": propuesta, "mensaje": "Diseño propuesto"}
```

`_stickers_de` lista la carpeta de fotos de la marca (la misma que usa `GET /stickers` de la Task 5) y devuelve los nombres. Si ya escribiste ese helper en el router, muévelo a un lugar compartido en vez de duplicarlo — `src/plantillas/__init__.py` o `src/marcas.py`, donde encaje mejor con lo que ya existe.

Registro: `"template.disenar": template_disenar,`.

Endpoint `POST /brands/{slug}/templates/design`, mismo patrón que `preview`: valida que `instruccion` no venga vacía, encola, devuelve `{"job_id": ...}` con 202.

Test del endpoint, en `tests/test_disenos_web.py`:

```python
def test_pedirle_un_diseno_al_asistente_encola_un_trabajo(cliente_manager, marca):
    r = cliente_manager.post(f"/brands/{marca}/templates/design",
                             json={"instruccion": "algo minimalista", "aspecto": "4:5"})
    assert r.status_code == 202
    assert isinstance(r.json()["job_id"], int)
```

- [ ] **Step 5: Corre los tests**

```bash
.venv/bin/python -m pytest tests/test_disenador_llm.py tests/test_disenos_web.py -q
ruff check src/ tests/ api/ web/ config.py
```

- [ ] **Step 6: Verifica que ningún test llama al LLM de verdad**

```bash
grep -rn "_via_deepseek\|_via_anthropic\|DEEPSEEK_API_KEY" tests/ | grep -v monkeypatch
```

Esperado: nada, o solo líneas que sean claramente de monkeypatch. Si sale algo que llame de verdad, se arregla aquí.

- [ ] **Step 7: Commit**

```bash
git add src/plantillas/disenador.py src/jobs/handlers.py api/routers/plantillas.py tests/
git commit -m "feat(disenos): el asistente propone capas validadas, no HTML libre"
```

---

### Task 8: Corte de control del backend

Antes de tocar el frontend, verifica que el backend entero sigue en pie. Esta tarea no escribe código nuevo: mide.

**Files:** ninguno (salvo lo que haya que arreglar).

- [ ] **Step 1: Corre la suite completa con conteo**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/plantillas-y-lotes
.venv/bin/python -m pytest -q --junit-xml=/tmp/instagod-disenos.xml
.venv/bin/python -c "
import xml.etree.ElementTree as ET
s = ET.parse('/tmp/instagod-disenos.xml').getroot()
if s.tag == 'testsuites': s = s[0]
print(dict(s.attrib))
for c in s.iter('testcase'):
    for hijo in c:
        if hijo.tag in ('failure', 'error'):
            print('ROJO:', c.get('classname'), c.get('name'))
"
```

- [ ] **Step 2: Compara contra el baseline**

- Antes: **1421 tests, 1 falla** (`tests/test_segmentos_web.py::test_segmentos_lista_catalogo_y_preview`).
- Ahora: más tests, **la misma única falla y ninguna otra**.

Si aparece una falla nueva, arréglala aquí. No sigas al frontend con la suite roja: depurar backend desde el editor visual es tres veces más caro.

- [ ] **Step 3: Ruff limpio**

```bash
ruff check src/ tests/ api/ web/ config.py
```

- [ ] **Step 4: Commit del corte (solo si hubo arreglos)**

```bash
git commit -am "fix(disenos): arreglos del corte de control del backend"
```

---

### Task 9: Tipos y hooks del frontend

El puente entre el portal y los endpoints de la Task 5. Sin pantalla todavía: solo tipos y datos, para que el editor se escriba contra algo que ya existe.

**Files:**
- Create: `frontend/lib/layout.ts`
- Create: `frontend/hooks/use-disenos.ts`
- Modify: `frontend/hooks/use-templates.ts` (reexporta lo que ya define, no dupliques `Plantilla`)

**Interfaces:**
- Consumes: `frontend/lib/api.ts` (`get/post/patch`), `@tanstack/react-query`.
- Produces:

```ts
// frontend/lib/layout.ts
export type TipoCapa = "texto" | "imagen" | "caja";
export type Capa = { id: string; tipo: TipoCapa; x: number; y: number; w: number; h: number;
  z: number; rot: number; opacidad: number;
  campo?: string; texto?: string; archivo?: string;
  fuente?: string; tam?: number; peso?: number; color?: string;
  alinear?: "izq" | "centro" | "der"; vertical?: "arriba" | "centro" | "abajo";
  interlinea?: number; mayusculas?: boolean; auto?: boolean; resaltar?: boolean;
  ajuste?: "cover" | "contain"; anclaje?: string; radio?: number };
export type Layout = { v: 1; lienzo: { fondo: string };
  guias: { cols: number; filas: number; iman: number }; capas: Capa[] };
export const LIENZO: Record<string, { ancho: number; alto: number }>;
export function capaNueva(tipo: TipoCapa, layout: Layout): Capa;
export function conCapa(layout: Layout, capa: Capa): Layout;
export function sinCapa(layout: Layout, id: string): Layout;
export function imantar(v: number, paso: number, iman: number): number;
export function dentro(capa: Capa, ancho: number, alto: number): Capa;

// frontend/hooks/use-disenos.ts
export type Diseno = { id: number; nombre: string; descripcion: string | null;
  aspecto: string; estado: string; version_actual: number;
  contrato: ContratoPlantilla; layout: Layout | null; editable: boolean };
export function useDisenos(slug: string, estado?: string);
export function useDiseno(slug: string, id: number);
export function useCrearDiseno(slug: string);
export function useGuardarDiseno(slug: string, id: number);
export function useDuplicarDiseno(slug: string);
export function useVersiones(slug: string, id: number);
export function useRevertir(slug: string, id: number);
export function useActivarDiseno(slug: string, id: number);
export function useArchivarDiseno(slug: string, id: number);
export function useFuentes(slug: string);
export function useStickers(slug: string);
export function usePreviaDiseno(slug: string);   // devuelve job_id, se sigue con useJob
export function usePedirDiseno(slug: string);    // el asistente, devuelve job_id
```

- [ ] **Step 1: Escribe `frontend/lib/layout.ts`**

Sin dependencias de React: son funciones puras que el lienzo y los tests manuales usan igual.

```ts
export const LIENZO: Record<string, { ancho: number; alto: number }> = {
  "4:5": { ancho: 1080, alto: 1350 },
  "9:16": { ancho: 1080, alto: 1920 },
};

/** Pega el valor a la rejilla cuando pasa cerca. Fuera del imán, movimiento libre. */
export function imantar(v: number, paso: number, iman: number): number {
  const pegado = Math.round(v / paso) * paso;
  return Math.abs(pegado - v) <= iman ? pegado : Math.round(v);
}

/** Ninguna capa puede salirse del lienzo: lo de afuera no sale en la foto. */
export function dentro(capa: Capa, ancho: number, alto: number): Capa {
  const w = Math.min(Math.max(1, Math.round(capa.w)), ancho);
  const h = Math.min(Math.max(1, Math.round(capa.h)), alto);
  return {
    ...capa, w, h,
    x: Math.min(Math.max(0, Math.round(capa.x)), ancho - w),
    y: Math.min(Math.max(0, Math.round(capa.y)), alto - h),
  };
}

/** Un id legible y único; el backend exige ^[a-z][a-z0-9_-]{0,31}$ */
function idLibre(base: string, layout: Layout): string {
  const usados = new Set(layout.capas.map((c) => c.id));
  let n = 1;
  while (usados.has(`${base}${n}`)) n += 1;
  return `${base}${n}`;
}

export function capaNueva(tipo: TipoCapa, layout: Layout): Capa {
  const z = Math.min(999, Math.max(0, ...layout.capas.map((c) => c.z)) + 1);
  const comun = { x: 120, y: 120, z, rot: 0, opacidad: 1, radio: 0 };
  if (tipo === "texto")
    return { ...comun, id: idLibre("texto", layout), tipo, w: 700, h: 180,
      texto: "Escribe aquí", fuente: layout.capas.find((c) => c.fuente)?.fuente ?? "Poppins",
      tam: 48, peso: 700, color: "#111111", alinear: "centro", vertical: "centro",
      interlinea: 1.2, mayusculas: false, auto: false };
  if (tipo === "imagen")
    return { ...comun, id: idLibre("imagen", layout), tipo, w: 400, h: 400,
      ajuste: "cover", anclaje: "center" };
  return { ...comun, id: idLibre("caja", layout), tipo, w: 400, h: 8, color: "marca" };
}

export const conCapa = (layout: Layout, capa: Capa): Layout => ({
  ...layout,
  capas: layout.capas.some((c) => c.id === capa.id)
    ? layout.capas.map((c) => (c.id === capa.id ? capa : c))
    : [...layout.capas, capa],
});

export const sinCapa = (layout: Layout, id: string): Layout => ({
  ...layout, capas: layout.capas.filter((c) => c.id !== id),
});
```

**Cuidado con la tipografía por defecto:** `"Poppins"` tiene que coincidir con la que usa `layout.vacio()` en el backend (Task 2). Si allá quedó otra, cámbiala aquí también.

- [ ] **Step 2: Escribe `frontend/hooks/use-disenos.ts`**

Copia el estilo exacto de `frontend/hooks/use-templates.ts` (claves de query, `enabled`, manejo de `ApiError`). Las mutaciones invalidan `["disenos", slug]` y `["diseno", slug, id]`:

```ts
export function useGuardarDiseno(slug: string, id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (b: { layout: Layout; contrato?: ContratoPlantilla; mensaje?: string }) =>
      patch<Diseno>(`/brands/${slug}/templates/${id}`, b),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["diseno", slug, id] });
      qc.invalidateQueries({ queryKey: ["versiones", slug, id] });
      qc.invalidateQueries({ queryKey: ["disenos", slug] });
    },
  });
}
```

`usePreviaDiseno` y `usePedirDiseno` devuelven `{job_id}` y se encadenan con el `useJob` que ya existe en `frontend/hooks/use-job.ts` — **no escribas otro poller**.

- [ ] **Step 3: Verifica**

```bash
cd frontend && pnpm lint && pnpm build
```

No hay corredor de tests en el frontend (`package.json` solo trae `dev/build/start/lint`). La verificación es que compile y que el linter esté limpio; el comportamiento se prueba en pantalla en la Task 14.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/layout.ts frontend/hooks/use-disenos.ts frontend/hooks/use-templates.ts
git commit -m "feat(disenos): tipos y hooks del editor en el portal"
```

---

### Task 10: La pantalla de Diseños

La lista. Entrada en el menú, tarjetas con la vista previa, botón de crear, y los legacy marcados como "no editable" con su botón de duplicar.

**Files:**
- Create: `frontend/app/b/[slug]/templates/page.tsx`
- Modify: `frontend/app/b/[slug]/layout.tsx:19-26` (el arreglo `NAV`)

**Interfaces:**
- Consumes: `useDisenos`, `useCrearDiseno`, `useDuplicarDiseno`.
- Produces: la ruta `/b/[slug]/templates`, desde la que la Task 11 abre `/b/[slug]/templates/[id]`.

- [ ] **Step 1: Entrada en el menú**

En `frontend/app/b/[slug]/layout.tsx`, dentro de `NAV`:

```tsx
  { href: "templates", label: "Diseños", soloManager: true },
```

Respeta la forma exacta de los objetos que ya están ahí (si la propiedad se llama distinto, usa la de ellos).

- [ ] **Step 2: La pantalla**

`frontend/app/b/[slug]/templates/page.tsx`, `"use client"`. Estructura:

- Encabezado: "Diseños" + botón primario **"Nuevo diseño"**.
- Filtro de estado: tres pastillas — Publicados / Borradores / Archivados. Por defecto Publicados.
- Rejilla de tarjetas. Cada tarjeta:
  - `<img src={`/api/brands/${slug}/templates/${d.id}/preview.png`} />` en proporción `aspect-[4/5]`, con `loading="lazy"`.
  - Nombre y una etiqueta de estado.
  - Si `d.editable`: la tarjeta entera es un link a `templates/${d.id}`.
  - Si no: etiqueta **"No editable"** y botón **"Duplicar como editable"** que llama a `useDuplicarDiseno` y navega al id nuevo.
- Vacío: "Todavía no hay diseños. Crea el primero." con el botón.
- Carga: esqueletos, no spinner (copia el patrón de `library/page.tsx`).

"Nuevo diseño" abre un diálogo mínimo: nombre + proporción (**Cuadrada alta 4:5** / **Vertical 9:16** — en pantalla nunca aparece "4:5", aparece el nombre). Al crear, navega al editor.

**Cero jerga en pantalla:** nada de "template", "layout", "JSON", "contrato", "aspecto", "capa" (en pantalla se dice **elemento**). Usa los componentes de `frontend/components/ui/` que ya existen; no metas dependencias nuevas.

- [ ] **Step 3: Verifica**

```bash
cd frontend && pnpm lint && pnpm build
```

- [ ] **Step 4: Míralo en el navegador**

Levanta el backend y el front (como se levanta en este repo — mira el README o los scripts) y entra a `/b/gdlscene/templates`. Debes ver las 4 plantillas de gdlscene, las cuatro marcadas **No editable**, cada una con su vista previa.

- [ ] **Step 5: Commit**

```bash
git add frontend/app/b/\[slug\]/templates/page.tsx frontend/app/b/\[slug\]/layout.tsx
git commit -m "feat(disenos): pantalla de diseños en el portal"
```

---

### Task 11: El lienzo

El corazón del hito: arrastrar, redimensionar y acomodar elementos sobre la rejilla. **Con eventos de puntero nativos y transformaciones CSS. Sin librería nueva** — `@dnd-kit` está instalado pero es para listas ordenables, no para posicionamiento libre con redimensión y giro.

**Files:**
- Create: `frontend/app/b/[slug]/templates/[id]/page.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/lienzo.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/capa-vista.tsx`

**Interfaces:**
- Consumes: `useDiseno`, `useFuentes`, `useStickers`, `lib/layout.ts`.
- Produces:

```ts
// lienzo.tsx
export function Lienzo(props: {
  layout: Layout; aspecto: string; seleccion: string | null;
  fuentes: { familia: string; propia: boolean }[];
  stickers: { nombre: string; url: string }[];
  onSeleccionar: (id: string | null) => void;
  onCambiar: (capa: Capa) => void;
  rejilla: boolean;
}): JSX.Element;

// capa-vista.tsx
export function CapaVista(props: {
  capa: Capa; escala: number; seleccionada: boolean;
  stickers: { nombre: string; url: string }[];
  onSeleccionar: () => void;
  onArrastrar: (dx: number, dy: number) => void;         // en px del lienzo
  onRedimensionar: (asa: Asa, dx: number, dy: number) => void;
  onSoltar: () => void;
}): JSX.Element;
export type Asa = "nw" | "ne" | "sw" | "se";
```

- [ ] **Step 1: El marco escalado**

El lienzo real mide 1080 px de ancho; en pantalla cabe en ~520. Todo se dibuja en coordenadas reales dentro de un contenedor con `transform: scale(escala)` y `transformOrigin: "top left"`:

```tsx
const { ancho, alto } = LIENZO[aspecto];
const ref = useRef<HTMLDivElement>(null);
const [escala, setEscala] = useState(0.4);

useEffect(() => {
  const el = ref.current;
  if (!el) return;
  const ro = new ResizeObserver(([e]) => setEscala(e.contentRect.width / ancho));
  ro.observe(el);
  return () => ro.disconnect();
}, [ancho]);
```

El contenedor exterior lleva `style={{ height: alto * escala }}` para que el layout de la página no salte.

**Guarda siempre coordenadas reales.** Divide entre `escala` al leer el movimiento del ratón; nunca guardes píxeles de pantalla, o el diseño se ve distinto en cada monitor.

- [ ] **Step 2: Arrastrar con eventos de puntero**

En `capa-vista.tsx`, sobre el `div` de la capa:

```tsx
function onPointerDown(e: React.PointerEvent) {
  e.stopPropagation();
  onSeleccionar();
  (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  const inicio = { x: e.clientX, y: e.clientY };
  const mover = (ev: PointerEvent) =>
    onArrastrar((ev.clientX - inicio.x) / escala, (ev.clientY - inicio.y) / escala);
  const soltar = () => {
    window.removeEventListener("pointermove", mover);
    window.removeEventListener("pointerup", soltar);
    onSoltar();
  };
  window.addEventListener("pointermove", mover);
  window.addEventListener("pointerup", soltar);
}
```

`setPointerCapture` es lo que hace que el arrastre siga funcionando cuando el cursor sale del elemento — sin eso se siente roto.

`onArrastrar` recibe el delta **acumulado desde el inicio**, no incremental: el padre guarda la posición de partida al empezar el gesto y calcula `x = partida.x + dx`. Así un `pointermove` perdido no descuadra nada.

- [ ] **Step 3: El imán a la rejilla**

En el padre, al mover:

```tsx
const paso = { x: ancho / layout.guias.cols, y: alto / layout.guias.filas };
const movida = dentro({
  ...partida.current,
  x: imantar(partida.current.x + dx, paso.x, layout.guias.iman),
  y: imantar(partida.current.y + dy, paso.y, layout.guias.iman),
}, ancho, alto);
onCambiar(movida);
```

Con la tecla `Alt` presionada durante el gesto, sáltate `imantar` (movimiento fino). Es la convención de todos los editores y no cuesta nada.

- [ ] **Step 4: Las asas de redimensión**

Cuatro asas en las esquinas, visibles solo en la capa seleccionada, de 12×12 px **de pantalla** (`width: 12 / escala` para que no crezcan al acercar). Cada una arrastra con la misma mecánica; el asa determina qué bordes se mueven:

```tsx
const REDIM: Record<Asa, (c: Capa, dx: number, dy: number) => Partial<Capa>> = {
  se: (c, dx, dy) => ({ w: c.w + dx, h: c.h + dy }),
  sw: (c, dx, dy) => ({ x: c.x + dx, w: c.w - dx, h: c.h + dy }),
  ne: (c, dx, dy) => ({ y: c.y + dy, w: c.w + dx, h: c.h - dy }),
  nw: (c, dx, dy) => ({ x: c.x + dx, y: c.y + dy, w: c.w - dx, h: c.h - dy }),
};
```

Ancho y alto mínimos de 8 px; `dentro()` se encarga del resto.

- [ ] **Step 5: Dibujar cada tipo de capa**

`CapaVista` posiciona con `position: absolute` y `transform: rotate(${capa.rot}deg)`:

- **texto**: el `texto` literal, o `«titular»` en gris cuando la capa está atada a un dato (es una vista previa de estructura, no de contenido). Aplica `fontFamily`, `fontSize`, `fontWeight`, `color`, alineación e interlínea reales. El color `"marca"` se dibuja con el color de la marca.
- **imagen** con `archivo`: el sticker desde `stickers.find(s => s.nombre === capa.archivo)?.url`, con `objectFit: capa.ajuste`.
- **imagen** con `campo`: un marco punteado con un ícono y la palabra "Foto".
- **caja**: un `div` con `background` y `borderRadius: capa.radio`.

Las tipografías propias de la marca hay que cargarlas para que se vean bien en pantalla; inyecta un `<style>` con las `@font-face` apuntando a `/api/brands/${slug}/files/fonts/${archivo}`.

- [ ] **Step 6: La rejilla y el teclado**

Fondo de rejilla con un `linear-gradient` repetido cada `paso.x` / `paso.y`, activable con un botón. Y atajos sobre la capa seleccionada (`onKeyDown` en el contenedor con `tabIndex={0}`):

| Tecla | Qué hace |
|---|---|
| Flechas | Mueve 1 px |
| Shift + flechas | Mueve 10 px |
| Supr / Backspace | Borra el elemento |
| Escape | Deselecciona |

- [ ] **Step 7: Verifica**

```bash
cd frontend && pnpm lint && pnpm build
```

- [ ] **Step 8: Pruébalo con las manos**

Abre un diseño nuevo en el navegador. Arrastra el titular: se pega a la rejilla. Con Alt, se mueve fino. Redimensiona desde las cuatro esquinas. Ninguna capa logra salirse del lienzo. Las flechas mueven de a uno.

- [ ] **Step 9: Commit**

```bash
git add frontend/app/b/\[slug\]/templates/
git commit -m "feat(disenos): lienzo con arrastre, redimensión y rejilla imantada"
```

---

### Task 12: El panel de propiedades

Lo que la Task 11 no cubre: qué dice cada elemento, con qué tipografía, de qué color, en qué orden.

**Files:**
- Create: `frontend/app/b/[slug]/templates/[id]/_components/panel-capa.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/lista-capas.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/barra-agregar.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx`

**Interfaces:**
- Consumes: `Capa`, `Layout`, `capaNueva`, `conCapa`, `sinCapa`, `useFuentes`, `useStickers`.
- Produces:

```ts
export function PanelCapa(props: { capa: Capa; contrato: ContratoPlantilla;
  fuentes: { familia: string; propia: boolean }[];
  stickers: { nombre: string; url: string }[];
  onCambiar: (capa: Capa) => void; onBorrar: () => void }): JSX.Element;

export function ListaCapas(props: { layout: Layout; seleccion: string | null;
  onSeleccionar: (id: string) => void;
  onSubir: (id: string) => void; onBajar: (id: string) => void }): JSX.Element;

export function BarraAgregar(props: { onAgregar: (tipo: TipoCapa) => void }): JSX.Element;
```

- [ ] **Step 1: `BarraAgregar`**

Tres botones con ícono y palabra: **Texto**, **Foto**, **Franja**. Eso es todo. (`caja` en pantalla se llama "franja" porque es para lo que se usa.)

- [ ] **Step 2: `ListaCapas`**

Los elementos ordenados por `z` descendente — arriba en la lista es arriba en la imagen. Cada renglón: ícono del tipo, un nombre legible (el `texto` recortado a 24 caracteres, o el nombre del dato, o el archivo del sticker), y dos flechas para subir/bajar. Subir intercambia el `z` con el vecino de arriba, no lo incrementa: así nunca se rompe el rango 0..999 ni se generan empates.

- [ ] **Step 3: `PanelCapa`**

Los controles cambian según el tipo. Comunes a todos: posición (x, y), tamaño (ancho, alto), giro, opacidad.

**Texto:**
- Interruptor **"Texto fijo" / "Un dato del diseño"**. En modo dato, un desplegable con las opciones del contrato (`base` + `extras`); en modo fijo, un área de texto (máx. 500).
- Tipografía: desplegable de `useFuentes`, **cada opción escrita en su propia tipografía**. Las propias de la marca van agrupadas arriba.
- Tamaño (8-400), grosor (100-900 de cien en cien), color (selector + campo hex + botón **"Color de la marca"** que pone el token `"marca"`).
- Alineación horizontal y vertical, interlínea, **MAYÚSCULAS**, **Resaltar** (solo con dato).
- **"Achicar si no cabe"** (`auto`) con la ayuda: *"si el texto es largo, se reduce solo hasta que quepa"*.

**Foto:**
- Interruptor **"La foto de la publicación" / "Un sticker"**. En modo sticker, una rejilla con las miniaturas de `useStickers` y un enlace a la biblioteca para subir más.
- Ajuste: **Rellenar** (`cover`) / **Caber completa** (`contain`).
- Esquinas redondeadas (0-2000, con un atajo "Círculo" que pone `radio = min(w,h)/2`).

**Franja:** color y esquinas.

Al final, un botón destructivo **"Quitar elemento"** con confirmación (PRODUCT.md: lo irreversible se protege).

Cada control llama a `onCambiar({...capa, campo: valor})`. Nada de estado local duplicado en el panel: la única fuente de verdad es el `layout` de la página, o los valores se desincronizan del lienzo.

- [ ] **Step 4: Arma la pantalla del editor**

`page.tsx` en tres columnas: `ListaCapas` (izquierda, angosta) · `Lienzo` + `BarraAgregar` (centro) · `PanelCapa` (derecha). En móvil se apila: lienzo arriba, panel abajo, lista en un desplegable. El `layout` vive en un `useState` de esta página y baja a todos.

- [ ] **Step 5: Verifica**

```bash
cd frontend && pnpm lint && pnpm build
```

- [ ] **Step 6: Commit**

```bash
git add frontend/app/b/\[slug\]/templates/
git commit -m "feat(disenos): panel de propiedades, lista de elementos y barra de agregar"
```

---

### Task 13: Guardar, versiones, vista previa y publicar

El editor ya deja armar un diseño. Falta que sirva de algo: guardarlo, verlo renderizado de verdad, publicarlo y poder volver atrás.

**Files:**
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx`
- Create: `frontend/app/b/[slug]/templates/[id]/_components/barra-guardar.tsx`

**Interfaces:**
- Consumes: `useGuardarDiseno`, `useVersiones`, `useRevertir`, `useActivarDiseno`, `useArchivarDiseno`, `usePreviaDiseno`, `useJob`.

- [ ] **Step 1: La barra superior**

De izquierda a derecha: nombre del diseño (editable en el sitio), estado, y los botones **Vista previa** · **Guardar** · **Publicar**.

- **Guardar** manda el `layout` completo con `useGuardarDiseno`. Si el backend responde 422, el mensaje se muestra tal cual: ya viene escrito en español para una persona (`"la tipografía «Papyrus» no está disponible para esta marca"`). No lo reescribas ni lo envuelvas en "Error:".
- **Vista previa** encola el trabajo con `usePreviaDiseno`, sigue el progreso con `useJob` y abre el PNG en un panel lateral. Mientras corre, el botón muestra el texto de progreso que devuelve el trabajo.
- **Publicar** llama a `useActivarDiseno` y avisa: *"Este diseño ya se puede usar para publicaciones."*

- [ ] **Step 2: Cambios sin guardar**

Marca sucio comparando `JSON.stringify(layout)` contra el último guardado. Con cambios pendientes:
- El botón Guardar se ve primario y dice **"Guardar cambios"**.
- Un `beforeunload` avisa antes de cerrar la pestaña.
- Al navegar dentro del portal, un diálogo de confirmación.

- [ ] **Step 3: El historial**

Un panel lateral con `useVersiones`: número, fecha, mensaje y quién. Cada renglón, un botón **"Volver a esta"** con confirmación que llama a `useRevertir` y recarga el layout en pantalla.

- [ ] **Step 4: El camino de los legacy**

Si `diseno.editable === false`, no se monta el editor. En su lugar: la vista previa grande, el aviso *"Este diseño se hizo antes del editor. Para modificarlo, haz una copia editable."* y el botón **"Duplicar como editable"**. Nada de habilitar el lienzo en modo lectura a medias: o se edita o no.

- [ ] **Step 5: Verifica**

```bash
cd frontend && pnpm lint && pnpm build
```

- [ ] **Step 6: La prueba de fuego**

Con el worker corriendo: crea un diseño, muévele el titular, dale Vista previa y **mira el PNG**. Debe verse igual que en el lienzo. Guarda, publica, y confirma que aparece en el desplegable de diseños al crear una publicación en `/b/gdlscene/create`.

Si el PNG y el lienzo no coinciden, es el compilador (Task 3) o el dibujado (Task 11) el que está mal. **Arréglalo aquí, no lo dejes pasar:** el valor entero del hito es que lo que ves sea lo que sale.

- [ ] **Step 7: Commit**

```bash
git add frontend/app/b/\[slug\]/templates/
git commit -m "feat(disenos): guardar, versiones, vista previa real y publicación"
```

---

### Task 14: El asistente de diseño

El chat de DeepSeek metido en la pantalla del editor. Propone, la persona decide.

**Files:**
- Create: `frontend/app/b/[slug]/templates/[id]/_components/chat-diseno.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx`

**Interfaces:**
- Consumes: `usePedirDiseno`, `useJob`.
- Produces: `export function ChatDiseno(props: { slug: string; templateId: number; layout: Layout; onPropuesta: (l: Layout) => void }): JSX.Element;`

- [ ] **Step 1: El panel**

Un panel lateral que se abre con un botón **"Pedirle un diseño al asistente"**. Dentro:

- Un campo de texto con marcador de posición: *"Describe cómo lo quieres. Por ejemplo: el titular más grande, abajo, sobre una franja verde."*
- Tres sugerencias de un clic: **"Más minimalista"** · **"Titular más grande"** · **"Con más color de la marca"**.
- Historial de la conversación de esta sesión (no se persiste; el historial que importa es el de versiones).

- [ ] **Step 2: El ciclo**

Enviar → `usePedirDiseno` → `job_id` → `useJob` muestra el progreso (*"Pensando el diseño…"*) → al terminar, el layout propuesto **se dibuja en el lienzo directamente**, y aparecen dos botones: **"Me gusta, lo dejo"** y **"Deshacer"**.

Guarda el layout previo antes de aplicar la propuesta para que Deshacer sea instantáneo. **La propuesta no se guarda sola nunca**: aplicarla al lienzo deja la pantalla sucia y la persona decide si le da Guardar.

- [ ] **Step 3: Cuando falla**

Si el trabajo termina en `error`, muestra el mensaje del backend tal cual (`"no se pudo armar el diseño: ..."`) y deja el texto escrito en el campo para reintentar sin volver a teclearlo.

- [ ] **Step 4: Verifica**

```bash
cd frontend && pnpm lint && pnpm build
```

- [ ] **Step 5: Pruébalo de verdad**

Esta es la única prueba del hito que sí llama a DeepSeek. Pídele *"que el titular vaya abajo, grande, sobre una franja del color de la marca"* y mira qué devuelve. Si la propuesta es válida pero fea, es prompt: ajústalo en `disenador._prompt`. Si es inválida y reintenta, mira en el log qué error le devolvió y si el mensaje era suficientemente claro para que el modelo lo corrigiera.

- [ ] **Step 6: Commit**

```bash
git add frontend/app/b/\[slug\]/templates/
git commit -m "feat(disenos): el asistente propone diseños dentro del editor"
```

---

### Task 15: Cierre

**Files:** los que haya que arreglar, más la nota de sesión.

- [ ] **Step 1: Suite completa con conteo**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/plantillas-y-lotes
.venv/bin/python -m pytest -q --junit-xml=/tmp/instagod-cierre.xml
.venv/bin/python -c "
import xml.etree.ElementTree as ET
s = ET.parse('/tmp/instagod-cierre.xml').getroot()
if s.tag == 'testsuites': s = s[0]
print(dict(s.attrib))
for c in s.iter('testcase'):
    for hijo in c:
        if hijo.tag in ('failure', 'error'):
            print('ROJO:', c.get('classname'), c.get('name'))
"
```

Criterio: **la única falla permitida es `tests/test_segmentos_web.py::test_segmentos_lista_catalogo_y_preview`**, que ya estaba rota antes de este hito. Cualquier otra se arregla antes de cerrar.

- [ ] **Step 2: Las 4 plantillas publicadas siguen intactas**

```bash
.venv/bin/python -m pytest tests/test_equivalencia_plantillas.py -v
```

Las cuatro (`clasica`, `onion`, `verde`, `slide`) deben renderizar byte por byte como antes. Es la promesa de la decisión de migración y no se negocia.

- [ ] **Step 3: Linters**

```bash
ruff check src/ tests/ api/ web/ config.py
cd frontend && pnpm lint && pnpm build
```

- [ ] **Step 4: Cero jerga en pantalla**

```bash
cd frontend && grep -rniE ">[^<]*(template|layout|JSON|contrato|aspecto|capa|render|slug)[^<]*<" app/b/\[slug\]/templates/ | grep -v "className"
```

Revisa a mano lo que salga: los nombres de variables están bien, el texto visible no. En pantalla se dice **diseño**, **elemento**, **dato**, **tipografía**, **proporción**.

- [ ] **Step 5: Cero llamadas al LLM en la suite**

```bash
grep -rn "DEEPSEEK_API_KEY\|ANTHROPIC_API_KEY" tests/ ; echo "---" ; \
grep -c "monkeypatch.setattr(disenador" tests/test_disenador_llm.py
```

- [ ] **Step 6: Nada tocó producción**

```bash
git -C /Users/ricardo/Work/personal/instagod status --short
ls -la data/*.db 2>/dev/null
```

Confirma que no se escribió en `data/gdlscene.db` ni se tocó nada fuera del worktree. Ni la VM, ni `/opt/instagod/`.

- [ ] **Step 7: Un PNG de verdad, mirado con los ojos**

Genera la vista previa de un diseño hecho en el editor y ábrelo. 1080×1350, el titular donde lo pusiste, la tipografía correcta, el color de la marca donde corresponde. **Esto no se declara terminado sin mirar la imagen.**

- [ ] **Step 8: Bitácora**

Escribe `~/Work/_vault/instagod/Sessions/2026-09-09-editor-visual-de-disenos.md` con las convenciones del vault: primera línea `Continúa [[Sessions/2026-08-31-instagod-h2-post-simple|H2, post simple end-to-end]].`, y las secciones `## Qué se hizo`, `## Decisiones tomadas`, `## Próximos pasos`, `## Addendum`. Commits citados con repo y hash corto.

Y **propón** (no apliques) la entrada nueva del `Decisions-Log`, arriba de todo, con el formato `## 2026-09-09 — título` + **Decisión:** / **Contexto:** / **Consecuencias:** + `Detalle: [[...]]`. El Decisions-Log solo se agrega arriba y nunca se reescribe.

- [ ] **Step 9: Commit final**

```bash
git add -A
git commit -m "chore(disenos): cierre del hito de editor visual"
```

---

## Lo que este hito NO hace

Anotado para que nadie lo confunda con un olvido:

- **No se mergea ni se despliega.** La rama `plantillas-y-lotes` se queda en el worktree, como está desde H1.
- **No se migran las 4 plantillas de gdlscene.** Es la decisión de migración: siguen legacy hasta que alguien las duplique a mano.
- **No hay plantillas prehechas** para arrancar un diseño desde algo bonito. `layout.vacio()` es un lienzo con foto y titular, nada más.
- **No hay deshacer/rehacer** con historial de teclado en el editor. El historial de versiones cubre el caso grave.
- **No hay guías de alineación entre elementos** (esas líneas que aparecen cuando dos cosas se alinean). Solo la rejilla.
- **No hay cuotas de generación por marca.** Sigue siendo la deuda que quedó desde H1 y sigue siendo bloqueante para clientes externos.
- **No se sandboxea el HTML legacy.** Los diseños con layout ya no pueden inyectar nada porque el esquema es cerrado; los cuatro legacy se renderizan como siempre.
