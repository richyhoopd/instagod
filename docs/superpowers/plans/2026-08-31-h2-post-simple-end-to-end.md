# H2 — Post simple end-to-end — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un colaborador genere, edite, apruebe y publique un post de una sola imagen desde el portal, usando una plantilla de la DB, en gdlscene **y** en una marca que no tiene nada que ver con música.

**Architecture:** Se parametriza el motor de render que ya existe (`src/compose.py`) para que acepte HTML que viene de la DB y dimensiones por aspecto, sin cambiar el comportamiento de ninguno de sus llamadores actuales. Encima se apilan cuatro piezas nuevas y pequeñas: el armado del contexto de render, el generador de campos por contrato con DeepSeek, la orquestación de la pieza, y dos handlers de job. La API y el wizard copian patrones que ya están en el repo (`PUT .../slides`, `POST /slideshows`, `PasoEstilo`, `ProgresoJob`).

**Tech Stack:** Python 3.12+, SQLite, Jinja2, Playwright (Chromium sync), DeepSeek vía SDK de OpenAI, FastAPI, Next.js 16 + React 19 + TanStack Query + shadcn.

**Spec:** `docs/superpowers/specs/2026-08-29-plantillas-lotes-y-stats-design.md`

**Hito previo:** `docs/superpowers/plans/2026-08-30-h1-cimiento-entidades-y-plantillas.md` (completo). H2 consume todo lo que H1 dejó: `brand_templates`, `template_versions`, `brand_entities`, `brand_fonts`, las columnas `template_id`/`template_version`/`entity_id`/`campos_json`/`aspecto` de `content_queue`, el tipo `'post'`, y los módulos `src/entidades.py`, `src/plantillas/{__init__,contrato,filtros}.py`.

## Global Constraints

- **El worktree necesita dos symlinks al repo principal antes de correr nada.** Un worktree de git no hereda archivos no versionados:
  ```bash
  ln -s ~/Work/personal/instagod/.venv .venv
  ln -s ~/Work/personal/instagod/.env  .env
  ```
  Sin `.env`, cuatro tests que dependen de credenciales fallan por entorno y se confunden con regresiones. Ambos ya están puestos en este worktree.
- **Baseline al arrancar H2: `1325 tests, 3 failures, 1322 passed`.** Las 3 son `test_planner::test_plan_month_salta_slots_pasados`, `test_replan::test_replan_no_repite_las_mismas_fotos` y `test_segmentos_web::test_segmentos_lista_catalogo_y_preview`, todas anteriores a esta rama. Si alguna ya fue arreglada cuando arranques, el baseline baja y **ese** es el número a mantener.
- El `pytest -q` de este repo **no imprime su línea final de resumen**. Para conteos fiables: `--junit-xml=/tmp/x.xml` y parsear el XML.
- **Ningún llamador actual de `src/compose.py` puede cambiar de comportamiento.** `compose()`, `render_card()` y el dict `TEMPLATES` siguen intactos y con las mismas firmas. Todo lo nuevo entra por parámetros con default. El dict `TEMPLATES` se retira hasta H5, no aquí.
- **Ninguna llamada real a DeepSeek, a Instagram, a Telegram ni a proveedores de imágenes en los tests.** Todo mockeado. Un test que sale a la red está mal escrito.
- Playwright sí corre de verdad en los tests de render, como ya hace `tests/test_slide_render.py`. Son smoke tests: el PNG existe y pesa más de 10 KB.
- Línea máxima 100 (`ruff`). Comentarios y docstrings en español.
- Lint: `ruff check src/ tests/ api/` limpio. **No** lintear `scripts/` completo: `scripts/portal_magic_link.py` arrastra un `F401` ajeno.
- **Nada toca producción.** Ni la VM, ni `/opt/instagod/`, ni `data/gdlscene.db` directamente. Copias en `/tmp` para verificación manual.
- Vocabulario canónico del contrato, idéntico en todos los hitos: `titular`, `imagen`, `handle`, `logo`, `color_marca`. Variable de sistema: `fonts_dir`.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `src/compose.py` (modificar) | Aceptar HTML string y dimensiones por parámetro. Cambios aditivos, con default = comportamiento actual |
| `src/plantillas/contrato.py` (modificar) | Agregar `validar_campos()`: valida un dict de valores contra el contrato. Sigue siendo puro |
| `src/plantillas/render.py` (crear) | Arma el contexto Jinja de una marca + campos, y renderiza una plantilla de DB a PNG |
| `src/plantillas/generador.py` (crear) | Le pide a DeepSeek los campos del contrato como JSON, con reintento sobre errores de validación |
| `src/plantillas/preview.py` (crear) | Preview cacheado de una plantilla con datos de muestra |
| `src/posts.py` (crear) | Orquesta la pieza: tema/entidad → campos → imagen → render → fila en `content_queue` |
| `src/jobs/handlers.py` (modificar) | Handlers `post.generar` y `post.rerender`, registrados en `HANDLERS` |
| `src/cola.py` (modificar) | `editar_campos()`, gemelo de `editar_slides()` |
| `api/routers/cola.py` (modificar) | `PUT /brands/{slug}/queue/{qid}/campos` |
| `api/routers/posts.py` (crear) | `POST /brands/{slug}/posts` y el preview de plantilla |
| `api/app.py` (modificar) | Montar el router nuevo |
| `frontend/hooks/use-templates.ts` (crear) | Listar plantillas de la marca |
| `frontend/hooks/use-job.ts` (modificar) | `useCrearPost` |
| `frontend/app/b/[slug]/create/_components/paso-plantilla.tsx` (crear) | Selector visual de plantilla, copia de `paso-estilo.tsx` |
| `frontend/app/b/[slug]/create/_components/paso-campos.tsx` (crear) | Formulario generado desde `contrato_json.extras` |
| `frontend/app/b/[slug]/create/page.tsx` (modificar) | Bifurcación carrusel / post simple |
| `scripts/verificar_h2.py` (crear) | Genera un post real de gdlscene y uno de melaquecapital, sin publicar |

`src/plantillas/` se mantiene como paquete: `contrato` y `generador` son puros (sin DB, sin Playwright), `render` y `preview` sí tocan disco y Chromium. Esa frontera es lo que permite validar la salida del LLM en milisegundos sin levantar un navegador.

---

### Task 1: Parametrizar dimensiones y HTML string en `compose`

**Files:**
- Modify: `src/compose.py:140-187`
- Test: `tests/test_compose_desde_db.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces:
  - `ASPECTOS: dict[str, tuple[int, int]]` = `{"4:5": (1080, 1350), "9:16": (1080, 1920)}`
  - `_screenshot_card(html, *, out_path=None, row_id=None, prefix="meme", ancho=WIDTH, alto=HEIGHT, sandbox=False) -> Path`
  - `render_html(html: str, *, aspecto: str = "4:5", out_path=None, row_id=None, prefix="post", sandbox: bool = False) -> Path`

**Restricción dura:** `compose()`, `render_card()` y `_render_html()` conservan firma y comportamiento. Los parámetros nuevos son keyword-only con default igual a lo de hoy. `tests/test_compose.py`, `tests/test_slide_render.py` y `tests/test_estilo_preview.py` deben seguir en verde sin tocarlos.

**Sobre `sandbox`:** cuando es `True`, el `BrowserContext` bloquea todo request cuyo esquema no sea `file:` o `data:`. Se controla con `config.TEMPLATE_RENDER_SANDBOX` (default `0`, apagado). Decisión 11 del spec: Ricardo eligió no restringir por ahora, con el riesgo explicado. El interruptor queda puesto para el día que entre una marca de un tercero.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_compose_desde_db.py`:

```python
"""Render de HTML que viene de la DB, con dimensiones por aspecto."""
from __future__ import annotations

import pytest
from PIL import Image

from src import compose

_HTML = """<!doctype html><html><head><style>
  .card {{ width: {w}px; height: {h}px; background:#111; color:#fff;
           display:flex; align-items:center; justify-content:center;
           font-size:80px; font-family:sans-serif; }}
</style></head><body><div class="card">HOLA</div>
<script>window.__captionFitted = true;</script></body></html>"""


def _html(aspecto: str) -> str:
    w, h = compose.ASPECTOS[aspecto]
    return _HTML.format(w=w, h=h)


def test_aspectos_declarados() -> None:
    assert compose.ASPECTOS["4:5"] == (1080, 1350)
    assert compose.ASPECTOS["9:16"] == (1080, 1920)


@pytest.mark.parametrize("aspecto", ["4:5", "9:16"])
def test_render_html_produce_png_del_tamano_pedido(aspecto, tmp_path) -> None:
    out = tmp_path / f"p_{aspecto.replace(':', 'x')}.png"
    png = compose.render_html(_html(aspecto), aspecto=aspecto, out_path=out)
    assert png.exists() and png.stat().st_size > 10_000
    assert Image.open(png).size == compose.ASPECTOS[aspecto]


def test_render_html_rechaza_aspecto_desconocido(tmp_path) -> None:
    with pytest.raises(ValueError, match="aspecto"):
        compose.render_html(_html("4:5"), aspecto="16:9",
                            out_path=tmp_path / "x.png")


def test_compose_clasico_sigue_intacto(tmp_path) -> None:
    """El camino viejo no cambia de tamaño ni de firma."""
    png = compose.compose(caption="Prueba de regresión",
                          foto_url=None, template="clasica",
                          out_path=tmp_path / "viejo.png")
    assert Image.open(png).size == (compose.WIDTH, compose.HEIGHT)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compose_desde_db.py -v`
Expected: FAIL con `AttributeError: module 'src.compose' has no attribute 'ASPECTOS'`.

- [ ] **Step 3: Agregar `ASPECTOS` y parametrizar `_screenshot_card`**

En `src/compose.py`, junto a `WIDTH, HEIGHT = 1080, 1350`:

```python
# H2: el post simple soporta 4:5 (feed) y 9:16 (stories). El default es el
# tamaño histórico, así que ningún llamador viejo cambia de comportamiento.
ASPECTOS: dict[str, tuple[int, int]] = {"4:5": (WIDTH, HEIGHT), "9:16": (1080, 1920)}
```

En la firma de `_screenshot_card`, agregar los tres keyword-only al final:

```python
def _screenshot_card(html: str, *, out_path=None, row_id=None, prefix="meme",
                     ancho: int = WIDTH, alto: int = HEIGHT,
                     sandbox: bool = False) -> Path:
```

Dentro, reemplazar el `viewport` fijo por `viewport={"width": ancho, "height": alto}`, y justo después de crear el contexto del navegador, agregar el bloqueo opcional de red:

```python
        contexto = browser.new_context(viewport={"width": ancho, "height": alto})
        if sandbox:
            # Solo file:// y data:. Impide que una plantilla generada por un LLM
            # saque datos del servidor. Apagado por default (config), ver
            # decisión 11 del spec.
            contexto.route(
                "**",
                lambda ruta: ruta.continue_()
                if ruta.request.url.startswith(("file:", "data:"))
                else ruta.abort(),
            )
        page = contexto.new_page()
```

Si el cuerpo actual usa `browser.new_page(viewport=...)` sin contexto explícito, introducir el contexto como arriba y dejar el resto igual.

- [ ] **Step 4: Agregar `render_html`**

Debajo de `render_card`:

```python
def render_html(html: str, *, aspecto: str = "4:5", out_path=None,
                row_id=None, prefix: str = "post",
                sandbox: bool | None = None) -> Path:
    """Renderiza HTML YA resuelto (viene de brand_templates, no de un archivo).

    El HTML entra tal cual: quien lo llama ya corrió Jinja sobre él. Comparte
    todo el pipeline con el camino viejo, incluido el wait de
    window.__captionFitted, para que una plantilla migrada a la DB produzca el
    mismo PNG que producía como archivo.
    """
    if aspecto not in ASPECTOS:
        raise ValueError(f"aspecto desconocido: {aspecto!r}")
    ancho, alto = ASPECTOS[aspecto]
    if sandbox is None:
        sandbox = config.TEMPLATE_RENDER_SANDBOX
    return _screenshot_card(html, out_path=out_path, row_id=row_id,
                            prefix=prefix, ancho=ancho, alto=alto,
                            sandbox=sandbox)
```

- [ ] **Step 5: Agregar el flag a `config.py`**

Junto a las demás lecturas de entorno:

```python
# H2: bloquea todo request saliente al renderizar una plantilla. Apagado por
# decisión explícita (spec, decisión 11). Se enciende el día que una marca de
# un tercero pueda escribir plantillas.
TEMPLATE_RENDER_SANDBOX = _get("TEMPLATE_RENDER_SANDBOX", "0") not in ("0", "", "false", "False")
```

Usa el mismo helper de lectura que ya usan las variables vecinas; si el nombre no es `_get`, adáptalo al que exista.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_compose_desde_db.py tests/test_compose.py tests/test_slide_render.py tests/test_estilo_preview.py -v`
Expected: PASS. Los tres archivos preexistentes deben pasar **sin haberlos modificado**.

- [ ] **Step 7: Commit**

```bash
git add src/compose.py config.py tests/test_compose_desde_db.py
git commit -m "feat(h2): compose acepta HTML de DB y dimensiones por aspecto"
```

---

### Task 2: `validar_campos` en el contrato

**Files:**
- Modify: `src/plantillas/contrato.py`
- Test: `tests/test_contrato_campos.py`

**Interfaces:**
- Consumes: `CAMPOS_BASE`, `TIPOS`, `ContratoInvalido` (H1).
- Produces: `validar_campos(campos: dict, contrato: dict) -> list[str]` — devuelve la lista de errores en español; `[]` significa válido. **No lanza**: la lista se le devuelve al LLM para que se autocorrija, igual que hace `slideshow_script.validar_guion`.

Reglas por tipo:
- `texto`, `texto_largo`: string no vacío tras `.strip()`.
- `numero`: `int` o `float` (un string numérico NO cuenta: el LLM debe mandar número).
- `booleano`: `bool`.
- `imagen`: string no vacío (la resolución de la ruta es de otra capa).
- `lista`: lista de strings no vacíos, con `min <= len <= max`.
- Un extra con `"opcional": true` puede faltar o venir `None`; si viene con valor, se valida igual.
- `titular` es obligatorio siempre. `imagen`, `handle`, `logo` y `color_marca` los inyecta el motor de render, así que **no** se exigen aquí.
- Claves que no están en el contrato: error de "campo desconocido".

- [ ] **Step 1: Write the failing test**

Crear `tests/test_contrato_campos.py`:

```python
"""Validación de los VALORES contra el contrato. Sin DB, sin red."""
from __future__ import annotations

from src.plantillas import contrato as c


def _ct(extras=None) -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}


def test_campos_minimos_validos() -> None:
    assert c.validar_campos({"titular": "Hola"}, _ct()) == []


def test_titular_vacio() -> None:
    errs = c.validar_campos({"titular": "   "}, _ct())
    assert errs and "titular" in errs[0]


def test_titular_ausente() -> None:
    errs = c.validar_campos({}, _ct())
    assert errs and "titular" in errs[0]


def test_lista_con_cantidad_incorrecta() -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    errs = c.validar_campos({"titular": "x", "pasos": ["a", "b"]}, ct)
    assert errs and "pasos" in errs[0]


def test_lista_correcta() -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    assert c.validar_campos({"titular": "x", "pasos": ["a", "b", "c"]}, ct) == []


def test_extra_opcional_puede_faltar() -> None:
    ct = _ct([{"id": "badge", "tipo": "texto", "opcional": True}])
    assert c.validar_campos({"titular": "x"}, ct) == []


def test_extra_obligatorio_no_puede_faltar() -> None:
    ct = _ct([{"id": "badge", "tipo": "texto"}])
    errs = c.validar_campos({"titular": "x"}, ct)
    assert errs and "badge" in errs[0]


def test_numero_como_texto_es_error() -> None:
    ct = _ct([{"id": "precio", "tipo": "numero"}])
    errs = c.validar_campos({"titular": "x", "precio": "1200"}, ct)
    assert errs and "precio" in errs[0]


def test_numero_correcto() -> None:
    ct = _ct([{"id": "precio", "tipo": "numero"}])
    assert c.validar_campos({"titular": "x", "precio": 1200}, ct) == []


def test_campo_desconocido() -> None:
    errs = c.validar_campos({"titular": "x", "inventado": "y"}, _ct())
    assert errs and "inventado" in errs[0]


def test_acumula_todos_los_errores() -> None:
    """El LLM se autocorrige con la lista completa, no de uno en uno."""
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3},
              {"id": "badge", "tipo": "texto"}])
    errs = c.validar_campos({"pasos": []}, ct)
    assert len(errs) == 3  # titular ausente, pasos corta, badge ausente
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_contrato_campos.py -v`
Expected: FAIL con `AttributeError: module 'src.plantillas.contrato' has no attribute 'validar_campos'`.

- [ ] **Step 3: Implementar `validar_campos`**

Al final de `src/plantillas/contrato.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_contrato_campos.py tests/test_contrato_plantilla.py -v`
Expected: PASS (11 nuevos + los 11 de H1).

- [ ] **Step 5: Commit**

```bash
git add src/plantillas/contrato.py tests/test_contrato_campos.py
git commit -m "feat(h2): validación de valores contra el contrato de plantilla"
```

---

### Task 3: Contexto de render y `src/plantillas/render.py`

**Files:**
- Create: `src/plantillas/render.py`
- Test: `tests/test_plantillas_render.py`

**Interfaces:**
- Consumes: `compose.render_html`, `compose._to_src`, `contrato.validar_campos`, `filtros.entorno`, `src/marcas.py`, tabla `brand_fonts`.
- Produces:
  - `contexto(marca, campos: dict, *, fonts_dir: str | None = None) -> dict`
  - `render(cx, marca, plantilla: dict, campos: dict, *, out_path=None, row_id=None) -> Path`
  - `CamposInvalidos(ValueError)`

`contexto()` inyecta el núcleo base desde la marca y deja pasar los extras:

| Campo | De dónde sale |
|---|---|
| `titular` y extras | `campos` |
| `imagen` | `campos["imagen"]` por `compose._to_src`. **Cuando no hay imagen va `""`, NUNCA `None`**: Jinja escribe el `None` de Python como el texto `"None"` dentro del CSS, y la plantilla queda con `background-image:url('None')` |
| `handle` | `marca.ig_handle`, con `@` al frente |
| `logo` | `marca.logo_path` por `_to_src`; `""` si la marca no tiene logo, por la misma razón |
| `color_marca` | `marca.color_marca` |
| `fonts_dir` | el global de `compose.FONTS_DIR`, como URI `file://` |

`render()` valida los campos contra el contrato de la plantilla y lanza `CamposInvalidos` con la lista si no pasan; después corre Jinja (con los filtros del proyecto, para que `resaltar` funcione) y delega en `compose.render_html` con el aspecto de la plantilla.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_plantillas_render.py`:

```python
"""Armado del contexto y render de una plantilla de DB."""
from __future__ import annotations

import pytest
from PIL import Image

from src import db, entidades, marcas, plantillas
from src.plantillas import contrato as c
from src.plantillas import render as R

_HTML = """<!doctype html><html><head><style>
 .card {{ width:1080px; height:{h}px; background:{{{{ color_marca }}}};
          color:#fff; font-family:sans-serif; font-size:64px;
          display:flex; align-items:center; justify-content:center; }}
</style></head><body>
 <div class="card">{{{{ titular }}}} — {{{{ handle }}}}</div>
 <script>window.__captionFitted = true;</script></body></html>"""


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct(aspecto="4:5", extras=None) -> dict:
    return {"aspecto": aspecto, "base": list(c.CAMPOS_BASE), "extras": extras or []}


def test_contexto_inyecta_el_nucleo(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    ctx = R.contexto(m, {"titular": "Hola"})
    assert ctx["titular"] == "Hola"
    assert ctx["handle"].startswith("@")
    assert "color_marca" in ctx and "logo" in ctx and "fonts_dir" in ctx


def test_contexto_convierte_lo_vacio_en_cadena_vacia(tmp_path) -> None:
    """NUNCA None: Jinja escribiría el None de Python como el texto "None"
    dentro del CSS, y la plantilla quedaría con background-image:url('None')."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    ctx = R.contexto(m, {"titular": "Hola", "imagen": None})
    assert ctx["imagen"] == ""
    assert ctx["logo"] == "" or ctx["logo"]


def test_render_produce_png(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Prueba", _HTML.format(h=1350), _ct())
    p = plantillas.obtener(cx, tid)
    png = R.render(cx, m, p, {"titular": "HOLA"}, out_path=tmp_path / "a.png")
    assert png.exists() and png.stat().st_size > 10_000
    assert Image.open(png).size == (1080, 1350)


def test_render_respeta_el_aspecto_de_la_plantilla(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Vertical", _HTML.format(h=1920),
                           _ct(aspecto="9:16"))
    p = plantillas.obtener(cx, tid)
    png = R.render(cx, m, p, {"titular": "HOLA"}, out_path=tmp_path / "b.png")
    assert Image.open(png).size == (1080, 1920)


def test_render_rechaza_campos_invalidos(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Prueba", _HTML.format(h=1350),
                           _ct(extras=[{"id": "pasos", "tipo": "lista",
                                        "min": 3, "max": 3}]))
    p = plantillas.obtener(cx, tid)
    with pytest.raises(R.CamposInvalidos) as exc:
        R.render(cx, m, p, {"titular": "x", "pasos": ["solo uno"]},
                 out_path=tmp_path / "c.png")
    assert "pasos" in str(exc.value)


def test_render_de_la_onion_sembrada_usa_el_filtro(tmp_path) -> None:
    """La plantilla real de gdlscene, con su filtro `resaltar`, renderiza."""
    from src.seeds import plantillas_gdlscene
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    plantillas_gdlscene.sembrar(cx, m.id)
    p = plantillas.por_slug(cx, m.id, "onion")
    png = R.render(cx, m, p, {"titular": "Banda local revienta el foro"},
                   out_path=tmp_path / "onion.png")
    assert png.exists() and png.stat().st_size > 10_000
```

La función real de `src/marcas.py` es `cargar(cx, slug) -> Marca`. No existe `por_slug`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_plantillas_render.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.plantillas.render'`.

- [ ] **Step 3: Escribir `src/plantillas/render.py`**

```python
"""Render de una plantilla de DB: arma el contexto y dispara Chromium.

Separado de `contrato` y `generador` a propósito: aquí sí hay disco y
navegador. Los otros dos son puros para poder validar la salida del LLM en
milisegundos sin levantar nada.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import compose, db
from . import contrato as _contrato
from . import filtros


class CamposInvalidos(ValueError):
    """Los valores no cumplen el contrato de la plantilla."""


def _fuentes_de_marca(cx, account_id: int) -> list[dict[str, Any]]:
    return db.rows(cx, "SELECT familia, archivo FROM brand_fonts WHERE account_id = ?",
                   (account_id,))


def contexto(marca, campos: dict[str, Any], *,
             fonts_dir: str | None = None) -> dict[str, Any]:
    """Campos del contrato + el núcleo base inyectado desde la marca."""
    ctx = dict(campos)
    # OJO: lo vacío va como "" y nunca como None. _to_src(None) devuelve "",
    # y Jinja escribiría el None de Python como el texto "None" dentro del CSS.
    # Verificado comparando el PNG contra el del camino viejo.
    ctx["imagen"] = compose._to_src(campos.get("imagen"))
    handle = (marca.ig_handle or "").lstrip("@")
    ctx["handle"] = f"@{handle}" if handle else ""
    ctx["logo"] = compose._to_src(marca.logo_path)
    ctx["color_marca"] = marca.color_marca
    ctx["fonts_dir"] = fonts_dir or compose.FONTS_DIR.as_uri()
    return ctx


def render(cx, marca, plantilla: dict[str, Any], campos: dict[str, Any], *,
           out_path: Path | None = None, row_id: str | None = None) -> Path:
    ct = _contrato.contrato_de_json(plantilla["contrato_json"])
    errores = _contrato.validar_campos(campos, ct)
    if errores:
        raise CamposInvalidos("; ".join(errores))

    fuentes = _fuentes_de_marca(cx, marca.id)
    ctx = contexto(marca, campos)
    ctx["brand_fonts"] = fuentes

    tpl = filtros.entorno().from_string(plantilla["html"])
    html = tpl.render(**ctx)
    return compose.render_html(html, aspecto=ct.get("aspecto", "4:5"),
                               out_path=out_path, row_id=row_id, prefix="post")
```

`contrato_de_json` es un helper nuevo de una línea en `contrato.py` que hace `json.loads` tolerante y devuelve `{}` si falla, para no repetir el `try/except` en tres módulos. Agrégalo ahí y reusa la lógica que ya tiene `plantillas.contrato_de`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_plantillas_render.py tests/test_equivalencia_plantillas.py -v`
Expected: PASS. Los de equivalencia son el criterio de aceptación de la migración: comparan el PNG **byte a byte** contra el que produce el archivo de `templates/`. Si alguno se pone rojo, las piezas de gdlscene cambiaron de aspecto sin que nadie lo pidiera.

⚠️ **El badge no es opcional en la práctica.** `compose()` hace `badge_text or _default_badge()`, así que toda pieza del camino viejo lleva un badge aunque nadie lo pase. Hoy `_default_badge()` devuelve `"Our Annual Year <año>"` — hardcodeado y en inglés. H2 no lo cambia, pero el generador de campos debe poder producir un `badge`, y la plantilla `clasica`/`verde`/`anuncio` lo declara como extra opcional. Si el equipo quiere otro texto, es una edición de plantilla o un campo con default por marca, y eso es H3.

- [ ] **Step 5: Commit**

```bash
git add src/plantillas/render.py src/plantillas/contrato.py tests/test_plantillas_render.py
git commit -m "feat(h2): contexto y render de plantillas de DB"
```

---

### Task 4: Generador de campos con DeepSeek

**Files:**
- Create: `src/plantillas/generador.py`
- Test: `tests/test_generador_campos.py`

**Interfaces:**
- Consumes: `contrato.validar_campos`, `config.LLM_PROVIDER`, el cliente que ya usa `src/slideshow_script.py`.
- Produces:
  - `describir_contrato(contrato: dict) -> str` — el contrato en prosa, para meterlo al prompt
  - `extraer_campos(texto: str) -> dict | None`
  - `generar_campos(contrato: dict, *, marca, tema: str, entidad: dict | None = None, rechazados: list[str] | None = None, intentos: int = 3) -> dict`

**Molde:** `src/slideshow_script.py:184-214` (`generar_guion`). Se copia su bucle: hasta 3 intentos, y en cada reintento se anexan al prompt los errores de validación del intento anterior para que el LLM se autocorrija. `response_format={"type": "json_object"}` con DeepSeek. `RuntimeError` al agotar los intentos.

**La diferencia con `caption.py`:** `src/caption.py` tiene el prompt de gdlscene hardcodeado en constantes (`SYSTEM_PROMPT:27-124` y `TIPO_GUIA:131-170`, ambos 100% escena musical de Guadalajara) y devuelve un string suelto. Este módulo no hereda nada de ahí: construye el prompt desde `marca.voz` + `marca.prompts_json` + el contrato, y pide un objeto JSON. `caption.py` no se toca en H2; sigue sirviendo al camino viejo.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_generador_campos.py`:

```python
"""Generación de campos por contrato. El LLM va mockeado: cero red."""
from __future__ import annotations

import json

import pytest

from src.plantillas import contrato as c
from src.plantillas import generador as g


class _MarcaFalsa:
    id = 1
    slug = "tips"
    nombre = "Cuenta de Tips"
    ig_handle = "tips"
    voz = "Tono cercano, directo, sin tecnicismos."
    prompts = {"caption_extra": "Nunca prometas resultados médicos.", "por_formato": {}}


def _ct(extras=None) -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}


def test_describir_contrato_menciona_cada_extra() -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3,
               "desc": "Tres pasos accionables"}])
    txt = g.describir_contrato(ct)
    assert "titular" in txt and "pasos" in txt
    assert "3" in txt and "Tres pasos accionables" in txt


def test_extraer_campos_tolera_fences() -> None:
    assert g.extraer_campos('```json\n{"titular": "Hola"}\n```') == {"titular": "Hola"}


def test_extraer_campos_devuelve_none_si_no_hay_json() -> None:
    assert g.extraer_campos("lo siento, no puedo") is None


def test_generar_campos_feliz(monkeypatch) -> None:
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: json.dumps({"titular": "Tres trucos"}))
    out = g.generar_campos(_ct(), marca=_MarcaFalsa(), tema="ahorro")
    assert out == {"titular": "Tres trucos"}


def test_generar_campos_reintenta_con_los_errores(monkeypatch) -> None:
    """El 1er intento devuelve una lista corta; el 2o corrige. El prompt del
    2o intento tiene que mencionar el error del 1o."""
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    prompts: list[str] = []
    respuestas = [json.dumps({"titular": "x", "pasos": ["a"]}),
                  json.dumps({"titular": "x", "pasos": ["a", "b", "c"]})]

    def fake(prompt, **kw):
        prompts.append(prompt)
        return respuestas[len(prompts) - 1]

    monkeypatch.setattr(g, "_pedir_al_llm", fake)
    out = g.generar_campos(ct, marca=_MarcaFalsa(), tema="ahorro")
    assert out["pasos"] == ["a", "b", "c"]
    assert len(prompts) == 2
    assert "pasos" in prompts[1]


def test_generar_campos_se_rinde_tras_los_intentos(monkeypatch) -> None:
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: json.dumps({"titular": "x", "pasos": []}))
    with pytest.raises(RuntimeError, match="pasos"):
        g.generar_campos(ct, marca=_MarcaFalsa(), tema="ahorro")


def test_el_prompt_lleva_la_voz_de_la_marca(monkeypatch) -> None:
    capturado: list[str] = []
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: capturado.append(prompt)
                        or json.dumps({"titular": "ok"}))
    g.generar_campos(_ct(), marca=_MarcaFalsa(), tema="ahorro")
    assert "Tono cercano" in capturado[0]
    assert "Nunca prometas" in capturado[0]


def test_no_hereda_el_prompt_de_gdlscene(monkeypatch) -> None:
    """Regresión: una marca de tips no debe recibir el prompt de la escena."""
    capturado: list[str] = []
    monkeypatch.setattr(g, "_pedir_al_llm",
                        lambda prompt, **kw: capturado.append(prompt)
                        or json.dumps({"titular": "ok"}))
    g.generar_campos(_ct(), marca=_MarcaFalsa(), tema="ahorro")
    bajo = capturado[0].lower()
    assert "gdlscene" not in bajo and "guadalajara" not in bajo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_generador_campos.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.plantillas.generador'`.

- [ ] **Step 3: Escribir `src/plantillas/generador.py`**

Lee `src/slideshow_script.py:140-214` y copia su forma de hablarle al proveedor (cliente, modelo, `response_format`, manejo de `LLM_PROVIDER`). No dupliques ese código si puedes importarlo; si está enredado con el dominio de slideshows, extrae solo lo mínimo y déjalo aislado en `_pedir_al_llm(prompt, *, temperature=None) -> str`, que es la única función que los tests mockean.

```python
"""Le pide a DeepSeek los campos que declara el contrato de una plantilla.

Es el gemelo genérico de src/caption.py, que tiene el prompt de gdlscene
hardcodeado y devuelve un string suelto. Aquí el prompt se arma desde la voz
de la marca y el contrato, y la respuesta es un objeto JSON con exactamente
las claves que la plantilla sabe dibujar.

Módulo puro salvo por la llamada al LLM: no toca DB ni Playwright.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import contrato as _contrato

_JSON = re.compile(r"\{.*\}", re.S)

_SISTEMA = (
    "Eres el redactor de una cuenta de Instagram. Escribes en español de México, "
    "directo y sin relleno. Devuelves SIEMPRE un único objeto JSON con exactamente "
    "las claves que se te piden, sin texto alrededor y sin claves de más."
)


def describir_contrato(contrato: dict[str, Any]) -> str:
    """El contrato en prosa, para que el LLM sepa qué debe devolver."""
    lineas = ["- titular (texto): el titular principal de la pieza."]
    for extra in contrato.get("extras", []) or []:
        eid, tipo = extra.get("id"), extra.get("tipo", "texto")
        desc = extra.get("desc") or ""
        opc = " OPCIONAL, puedes omitirlo" if extra.get("opcional") else ""
        if tipo == "lista":
            minimo, maximo = extra.get("min", 1), extra.get("max", 10)
            rango = (f"exactamente {minimo}" if minimo == maximo
                     else f"entre {minimo} y {maximo}")
            lineas.append(f"- {eid} (lista de textos, {rango} elementos){opc}. {desc}")
        else:
            lineas.append(f"- {eid} ({tipo}){opc}. {desc}")
    return "\n".join(lineas)


def extraer_campos(texto: str) -> dict[str, Any] | None:
    m = _JSON.search(texto or "")
    if not m:
        return None
    try:
        valor = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return valor if isinstance(valor, dict) else None


def _construir_prompt(contrato, *, marca, tema, entidad, rechazados,
                      errores_previos) -> str:
    partes = [_SISTEMA, "", f"MARCA: {marca.nombre} (@{(marca.ig_handle or '').lstrip('@')})"]
    if getattr(marca, "voz", None):
        partes += ["", "VOZ DE LA MARCA:", marca.voz]
    extra = (getattr(marca, "prompts", None) or {}).get("caption_extra")
    if extra:
        partes += ["", "REGLAS ADICIONALES:", extra]
    if entidad:
        partes += ["", f"SUJETO: {entidad.get('nombre')} ({entidad.get('tipo')})"]
    partes += ["", f"TEMA: {tema}", "", "DEVUELVE UN JSON CON ESTAS CLAVES:",
               describir_contrato(contrato)]
    if rechazados:
        partes += ["", "TITULARES YA RECHAZADOS, no los repitas:",
                   *(f"- {r}" for r in rechazados)]
    if errores_previos:
        partes += ["", "TU RESPUESTA ANTERIOR TUVO ESTOS ERRORES, corrígelos:",
                   *(f"- {e}" for e in errores_previos)]
    return "\n".join(partes)


def generar_campos(contrato: dict[str, Any], *, marca, tema: str,
                   entidad: dict[str, Any] | None = None,
                   rechazados: list[str] | None = None,
                   intentos: int = 3) -> dict[str, Any]:
    errores: list[str] = []
    for _ in range(intentos):
        prompt = _construir_prompt(contrato, marca=marca, tema=tema,
                                   entidad=entidad, rechazados=rechazados,
                                   errores_previos=errores)
        campos = extraer_campos(_pedir_al_llm(prompt))
        if campos is None:
            errores = ["no devolviste un objeto JSON válido"]
            continue
        errores = _contrato.validar_campos(campos, contrato)
        if not errores:
            return campos
    raise RuntimeError(
        f"el LLM no produjo campos válidos en {intentos} intentos: {'; '.join(errores)}")
```

`_pedir_al_llm` va al final del módulo y delega en `_via_deepseek`/`_via_anthropic` de `slideshow_script` en vez de duplicarlas. Es la única superficie que los tests mockean, así que su firma tiene que ser exactamente `_pedir_al_llm(prompt: str) -> str`.

⚠️ **Sin parámetro `temperature`.** La de `slideshow_script` se lee de `config`, así que ajustarla por llamada obliga a pisar `config.SLIDESHOW_TEMPERATURE` y restaurarla en un `finally`. El worker corre hasta `WORKER_MAX_JOBS` jobs a la vez: ese estado global mutable es una carrera esperando a ocurrir, y nadie estaba pidiendo una temperatura distinta. Si algún día hace falta, el parámetro se agrega en `slideshow_script`, no un swap global.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_generador_campos.py -v`
Expected: PASS (8 tests), sin una sola llamada de red.

- [ ] **Step 5: Commit**

```bash
git add src/plantillas/generador.py tests/test_generador_campos.py
git commit -m "feat(h2): generador de campos por contrato con DeepSeek"
```

---

### Task 5: Orquestación de la pieza — `src/posts.py`

**Files:**
- Create: `src/posts.py`
- Test: `tests/test_posts.py`

**Interfaces:**
- Consumes: `plantillas`, `plantillas.render`, `plantillas.generador`, `entidades`, `fuentes.orden_imagen`, `image_sources.resolver`, `db`, `marcas`.
- Produces:
  - `resolver_imagen(cx, marca, *, entidad_id=None, hint=None, manual=None) -> str | None`
  - `crear_post(cx, marca, *, template_id, tema, entidad_id=None, campos_manuales=None, imagen_manual=None, creado_por=None) -> int` — devuelve el `queue_id`
  - `rerender(cx, marca, queue_id: int) -> str` — devuelve la ruta/URL del PNG nuevo

**Orden de resolución de la imagen**, tal como manda el spec (sección "Flujo del post simple"):
1. `manual` (subida desde el portal) si viene.
2. Una foto de la entidad: `photos` con `entity_id` = la entidad, `usable_meme=1`, `descartada=0`, `usada=0`, la menos usada primero.
3. La cascada global: `image_sources.resolver([hint], fuentes.orden_imagen(cx, marca), ...)`.
4. `None`. La plantilla decide con `{% if imagen %}`; no es error que una marca de puro texto no tenga foto.

`crear_post` inserta en `content_queue` con `tipo='post'`, `template_id`, `template_version` (la `version_actual` de la plantilla al momento — congelada, para que editar la plantilla después no cambie piezas ya generadas), `entity_id`, `campos_json`, `aspecto`, `imagen_url`, `caption` y `aprobacion=NULL`. `status` queda en `'borrador'`.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_posts.py`:

```python
"""Orquestación del post simple. LLM e imágenes mockeados: cero red."""
from __future__ import annotations

import json

from src import db, entidades, marcas, plantillas, posts
from src.plantillas import contrato as c

_HTML = ("<div class='card'>{{ titular }} {{ handle }}"
         "{% if imagen %}<img src='{{ imagen }}'>{% endif %}</div>")


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


def _plantilla(cx, account_id) -> int:
    return plantillas.crear(cx, account_id, "Simple", _HTML, _ct())


def _sin_render(monkeypatch, tmp_path):
    """Evita levantar Chromium en los tests de orquestación."""
    png = tmp_path / "fake.png"
    png.write_bytes(b"\x89PNG" + b"0" * 20_000)
    monkeypatch.setattr(posts.render, "render", lambda *a, **k: png)
    monkeypatch.setattr(posts.host, "upload", lambda ruta, **k: "https://cdn/x.png")
    return png


def test_crear_post_inserta_fila_completa(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)
    monkeypatch.setattr(posts.generador, "generar_campos",
                        lambda ct, **kw: {"titular": "Hola mundo"})

    qid = posts.crear_post(cx, m, template_id=tid, tema="lo que sea")
    fila = db.get(cx, "content_queue", qid)
    assert fila["tipo"] == "post"
    assert fila["template_id"] == tid
    assert fila["template_version"] == 1
    assert fila["aspecto"] == "4:5"
    assert json.loads(fila["campos_json"])["titular"] == "Hola mundo"
    assert fila["status"] == "borrador"
    assert fila["aprobacion"] is None
    assert fila["account_id"] == m.id


def test_los_campos_manuales_ganan_al_llm(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)

    def no_debe_llamarse(*a, **k):
        raise AssertionError("no se debe llamar al LLM si vienen campos manuales")

    monkeypatch.setattr(posts.generador, "generar_campos", no_debe_llamarse)
    qid = posts.crear_post(cx, m, template_id=tid, tema="x",
                           campos_manuales={"titular": "Escrito a mano"})
    assert json.loads(db.get(cx, "content_queue", qid)["campos_json"])["titular"] == "Escrito a mano"


def test_congela_la_version_de_la_plantilla(tmp_path, monkeypatch) -> None:
    """Editar la plantilla después no debe cambiar piezas ya generadas."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)
    monkeypatch.setattr(posts.generador, "generar_campos",
                        lambda ct, **kw: {"titular": "v1"})
    qid = posts.crear_post(cx, m, template_id=tid, tema="x")
    plantillas.nueva_version(cx, tid, _HTML + "<b>v2</b>", _ct())
    assert db.get(cx, "content_queue", qid)["template_version"] == 1
    assert plantillas.obtener(cx, tid)["version_actual"] == 2


def test_imagen_manual_gana(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    monkeypatch.setattr(posts.image_sources, "resolver",
                        lambda *a, **k: [None])
    assert posts.resolver_imagen(cx, m, manual="/tmp/mia.jpg") == "/tmp/mia.jpg"


def test_usa_foto_de_la_entidad_antes_que_la_cascada(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", account_id=m.id)
    eid = entidades.crear(cx, m.id, "Los Ejemplo", "banda", band_id=bid)
    db.insert(cx, "photos", band_id=bid, entity_id=eid,
              path="/tmp/de-la-banda.jpg", usable_meme=1)

    def no_debe_llamarse(*a, **k):
        raise AssertionError("no debe caer a la cascada si la entidad tiene foto")

    monkeypatch.setattr(posts.image_sources, "resolver", no_debe_llamarse)
    assert posts.resolver_imagen(cx, m, entidad_id=eid) == "/tmp/de-la-banda.jpg"


def test_sin_imagen_no_es_error(tmp_path, monkeypatch) -> None:
    """Una marca de puro texto es válida: la plantilla decide con {% if %}."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    monkeypatch.setattr(posts.image_sources, "resolver", lambda *a, **k: [None])
    assert posts.resolver_imagen(cx, m, hint="lo que sea") is None


def test_rerender_usa_los_campos_guardados(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = _plantilla(cx, m.id)
    _sin_render(monkeypatch, tmp_path)
    monkeypatch.setattr(posts.generador, "generar_campos",
                        lambda ct, **kw: {"titular": "original"})
    qid = posts.crear_post(cx, m, template_id=tid, tema="x")

    db.update(cx, "content_queue", qid,
              campos_json=json.dumps({"titular": "editado a mano"}))

    def no_debe_llamarse(*a, **k):
        raise AssertionError("rerender NO debe llamar al LLM")

    monkeypatch.setattr(posts.generador, "generar_campos", no_debe_llamarse)
    posts.rerender(cx, m, qid)
    assert json.loads(db.get(cx, "content_queue", qid)["campos_json"])["titular"] == "editado a mano"
```

Antes de escribir, confirma con `grep -n "^def \|^class " src/host.py src/marcas.py src/image_sources.py` los nombres reales de `host.upload`, `marcas.por_slug` e `image_sources.resolver`, y ajusta los mocks a lo que exista.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_posts.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.posts'`.

- [ ] **Step 3: Escribir `src/posts.py`**

```python
"""Orquesta un post simple: campos, imagen, render y fila en la cola.

Es el equivalente de src/generate_slideshow.py para la pieza de una sola
imagen, pero sin nada del dominio musical: habla de entidades y plantillas,
no de bandas y memes.
"""
from __future__ import annotations

import json
from typing import Any

from . import db, fuentes as fuentes_mod, host, image_sources, plantillas
from .plantillas import generador, render


def resolver_imagen(cx, marca, *, entidad_id: int | None = None,
                    hint: str | None = None, manual: str | None = None) -> str | None:
    """Manual > foto de la entidad > cascada de la marca > nada."""
    if manual:
        return manual
    if entidad_id:
        filas = db.rows(
            cx,
            "SELECT path FROM photos WHERE entity_id = ? AND usable_meme = 1 "
            "  AND descartada = 0 AND usada = 0 ORDER BY id LIMIT 1",
            (entidad_id,),
        )
        if filas:
            return filas[0]["path"]
    if hint:
        cascada = list(fuentes_mod.orden_imagen(cx, marca))
        candidatas = image_sources.resolver([hint], cascada, cx=cx, slug=marca.slug)
        if candidatas and candidatas[0] is not None:
            return candidatas[0].ruta_o_url
    return None


def crear_post(cx, marca, *, template_id: int, tema: str,
               entidad_id: int | None = None,
               campos_manuales: dict[str, Any] | None = None,
               imagen_manual: str | None = None,
               creado_por: int | None = None) -> int:
    tpl = plantillas.obtener(cx, template_id)
    if tpl is None or tpl["account_id"] != marca.id:
        raise ValueError("plantilla")
    ct = plantillas.contrato_de(tpl)

    entidad = db.get(cx, "brand_entities", entidad_id) if entidad_id else None
    campos = campos_manuales or generador.generar_campos(
        ct, marca=marca, tema=tema, entidad=entidad)

    campos["imagen"] = resolver_imagen(
        cx, marca, entidad_id=entidad_id,
        hint=campos.get("titular") or tema, manual=imagen_manual)

    png = render.render(cx, marca, tpl, campos)
    url = host.upload(str(png))

    return db.insert(
        cx, "content_queue", tipo="post", account_id=marca.id,
        template_id=template_id, template_version=tpl["version_actual"],
        entity_id=entidad_id, campos_json=json.dumps(campos, ensure_ascii=False),
        aspecto=ct.get("aspecto", "4:5"), imagen_url=url,
        caption=campos.get("titular"), tema_semilla=tema,
        status="borrador", creado_por=creado_por, origen="portal",
    )


def rerender(cx, marca, queue_id: int) -> str:
    """Vuelve a dibujar con los campos que ya están guardados. Sin LLM."""
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None or fila["account_id"] != marca.id:
        raise ValueError("pieza")
    if fila["tipo"] != "post":
        raise ValueError("tipo")
    tpl = plantillas.obtener(cx, fila["template_id"])
    if tpl is None:
        raise ValueError("plantilla")

    campos = json.loads(fila["campos_json"] or "{}")
    png = render.render(cx, marca, tpl, campos, row_id=f"q{queue_id}")
    url = host.upload(str(png), public_id=f"post_{queue_id}")
    db.update(cx, "content_queue", queue_id, imagen_url=url,
              caption=campos.get("titular"))
    return url
```

`origen="portal"` solo si esa columna acepta ese valor; verifica el `CHECK` o los valores que ya usa `api/routers/`. Si no existe tal convención, omite el parámetro.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_posts.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/posts.py tests/test_posts.py
git commit -m "feat(h2): orquestación del post simple"
```

---

### Task 6: Handlers de job `post.generar` y `post.rerender`

**Files:**
- Modify: `src/jobs/handlers.py`
- Test: `tests/test_jobs_post.py`

**Interfaces:**
- Consumes: `posts.crear_post`, `posts.rerender`, `jobs.progresar`, `_marca_de`.
- Produces: `generar_post(cx, job) -> dict`, `rerender_post(cx, job) -> dict`, y sus entradas en `HANDLERS`.

**Molde:** `rerender_slideshow` (`src/jobs/handlers.py:127-152`). Firma fija `(cx, job) -> dict`. Resuelve la marca con `_marca_de(cx, job["account_id"])` — **nunca** un default. Reporta con `jobs.progresar` en los puntos caros (antes del LLM, antes del render, antes de subir). Enlaza el resultado con `db.update(cx, "jobs", job["id"], queue_id=qid)`. Deja propagar los errores: el worker los captura y marca el job en `'error'`.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_jobs_post.py`:

```python
"""Handlers de job del post simple."""
from __future__ import annotations

import json

import pytest

from src import db, jobs, marcas, plantillas
from src.jobs import handlers
from src.plantillas import contrato as c

_HTML = "<div class='card'>{{ titular }} {{ handle }}</div>"


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


def test_registrados_en_handlers() -> None:
    assert "post.generar" in handlers.HANDLERS
    assert "post.rerender" in handlers.HANDLERS


def test_generar_post_crea_la_pieza_y_reporta_progreso(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Simple", _HTML, _ct())
    monkeypatch.setattr(handlers.posts, "crear_post", lambda *a, **k: 4242)

    vistos: list[int] = []
    real = jobs.progresar
    monkeypatch.setattr(handlers.jobs, "progresar",
                        lambda cx_, jid, pct, msg: vistos.append(pct) or real(cx_, jid, pct, msg))

    jid = jobs.crear(cx, "post.generar", m.id,
                     {"template_id": tid, "tema": "lo que sea"})
    job = db.get(cx, "jobs", jid)
    out = handlers.HANDLERS["post.generar"](cx, job)

    assert out["queue_id"] == 4242
    assert db.get(cx, "jobs", jid)["queue_id"] == 4242
    assert vistos, "el handler debe reportar progreso"


def test_generar_post_rechaza_plantilla_de_otra_marca(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    otra_id = db.insert(cx, "accounts", slug="otra", ig_handle="otra",
                        nombre="Otra", ciudad="CDMX")
    tid_ajena = plantillas.crear(cx, otra_id, "Ajena", _HTML, _ct())

    def explota(*a, **k):
        raise ValueError("plantilla")

    monkeypatch.setattr(handlers.posts, "crear_post", explota)
    jid = jobs.crear(cx, "post.generar", m.id,
                     {"template_id": tid_ajena, "tema": "x"})
    with pytest.raises(ValueError, match="plantilla"):
        handlers.HANDLERS["post.generar"](cx, db.get(cx, "jobs", jid))


def test_rerender_post_no_llama_al_llm(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    qid = db.insert(cx, "content_queue", tipo="post", account_id=m.id,
                    campos_json=json.dumps({"titular": "x"}))
    monkeypatch.setattr(handlers.posts, "rerender", lambda *a, **k: "https://cdn/y.png")
    jid = jobs.crear(cx, "post.rerender", m.id, {"queue_id": qid})
    out = handlers.HANDLERS["post.rerender"](cx, db.get(cx, "jobs", jid))
    assert out["queue_id"] == qid
```

Confirma la firma real de `jobs.crear` antes de escribir (`grep -n "def crear" src/jobs/__init__.py`) y ajusta los cuatro usos.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_jobs_post.py -v`
Expected: FAIL con `KeyError: 'post.generar'`.

- [ ] **Step 3: Escribir los handlers**

En `src/jobs/handlers.py`, junto a los demás:

```python
def generar_post(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """Genera una pieza de una sola imagen desde una plantilla de la marca."""
    payload = json.loads(job["payload_json"] or "{}")
    marca = _marca_de(cx, job["account_id"])
    jobs.progresar(cx, job["id"], 15, "redactando")
    qid = posts.crear_post(
        cx, marca,
        template_id=payload["template_id"],
        tema=payload.get("tema") or "",
        entidad_id=payload.get("entidad_id"),
        campos_manuales=payload.get("campos"),
        imagen_manual=payload.get("imagen"),
        creado_por=job.get("creado_por"),
    )
    jobs.progresar(cx, job["id"], 90, "listo")
    db.update(cx, "jobs", job["id"], queue_id=qid)
    return {"queue_id": qid}


def rerender_post(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """Vuelve a dibujar una pieza con sus campos actuales. Sin LLM."""
    payload = json.loads(job["payload_json"] or "{}")
    marca = _marca_de(cx, job["account_id"])
    queue_id = payload["queue_id"]
    jobs.progresar(cx, job["id"], 30, "dibujando")
    posts.rerender(cx, marca, queue_id)
    jobs.progresar(cx, job["id"], 90, "listo")
    db.update(cx, "jobs", job["id"], queue_id=queue_id)
    return {"queue_id": queue_id}
```

Y en el dict `HANDLERS`:

```python
    "post.generar": generar_post,
    "post.rerender": rerender_post,
```

Agrega `from .. import posts` a los imports del módulo.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_jobs_post.py tests/test_jobs_handlers.py -v`
Expected: PASS. Los tests de handlers que ya existían deben seguir en verde sin tocarlos.

- [ ] **Step 5: Commit**

```bash
git add src/jobs/handlers.py tests/test_jobs_post.py
git commit -m "feat(h2): handlers post.generar y post.rerender"
```

---

### Task 7: `cola.editar_campos` y `PUT /queue/{qid}/campos`

**Files:**
- Modify: `src/cola.py`
- Modify: `api/routers/cola.py`
- Test: `tests/test_cola_campos.py`

**Interfaces:**
- Consumes: `contrato.validar_campos`, `plantillas.obtener`, `cola.estado_de`, `cola._resolver_image_url`.
- Produces: `cola.editar_campos(cx, queue_id: int, campos: dict) -> None`, y el endpoint que encola `post.rerender`.

**Molde exacto:** `cola.editar_slides` (`src/cola.py:200-230`) y su router (`api/routers/cola.py:93-104`). Se copian sus tres validaciones y su mapa de errores:

| `ValueError` | Mensaje al usuario |
|---|---|
| `"estado"` | La pieza ya no se puede editar |
| `"tipo"` | Esta pieza no es un post simple |
| `"campos"` | (el detalle de `validar_campos`, unido con `; `) |
| `"url"` | La imagen no es válida |

La imagen se resuelve con `_resolver_image_url`, que ya trae la defensa contra path traversal y la validación de URL con `topics.url_segura`. **No la reimplementes.**

- [ ] **Step 1: Write the failing test**

Crear `tests/test_cola_campos.py`:

```python
"""Edición manual de los campos de un post y re-render."""
from __future__ import annotations

import json

import pytest

from src import cola, db, marcas, plantillas
from src.plantillas import contrato as c

_HTML = "<div class='card'>{{ titular }} {{ handle }}</div>"


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _pieza(cx, m, extras=None) -> tuple[int, int]:
    ct = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}
    tid = plantillas.crear(cx, m.id, "Simple", _HTML, ct)
    qid = db.insert(cx, "content_queue", tipo="post", account_id=m.id,
                    template_id=tid, template_version=1, aspecto="4:5",
                    campos_json=json.dumps({"titular": "original"}),
                    status="borrador")
    return tid, qid


def test_editar_campos_guarda(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m)
    cola.editar_campos(cx, qid, {"titular": "corregido a mano"})
    guardado = json.loads(db.get(cx, "content_queue", qid)["campos_json"])
    assert guardado["titular"] == "corregido a mano"


def test_rechaza_campos_que_violan_el_contrato(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m, extras=[{"id": "pasos", "tipo": "lista",
                                    "min": 3, "max": 3}])
    with pytest.raises(ValueError, match="campos"):
        cola.editar_campos(cx, qid, {"titular": "x", "pasos": ["solo uno"]})


def test_rechaza_si_no_es_post(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=m.id)
    with pytest.raises(ValueError, match="tipo"):
        cola.editar_campos(cx, qid, {"titular": "x"})


def test_rechaza_si_ya_se_publico(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m)
    db.update(cx, "content_queue", qid, status="publicado")
    with pytest.raises(ValueError, match="estado"):
        cola.editar_campos(cx, qid, {"titular": "tarde"})


def test_no_toca_el_titular_si_solo_cambia_un_extra(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _, qid = _pieza(cx, m, extras=[{"id": "badge", "tipo": "texto",
                                    "opcional": True}])
    cola.editar_campos(cx, qid, {"titular": "original", "badge": "NUEVO"})
    guardado = json.loads(db.get(cx, "content_queue", qid)["campos_json"])
    assert guardado["titular"] == "original" and guardado["badge"] == "NUEVO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cola_campos.py -v`
Expected: FAIL con `AttributeError: module 'src.cola' has no attribute 'editar_campos'`.

- [ ] **Step 3: Escribir `cola.editar_campos`**

En `src/cola.py`, junto a `editar_slides`:

```python
def editar_campos(cx, queue_id: int, campos: dict[str, Any]) -> None:
    """Reemplaza los valores de un post y los valida contra su contrato.

    Gemelo de editar_slides. NO re-renderiza: eso lo encola el router como
    job post.rerender, igual que el camino de slideshows.
    """
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None:
        raise ValueError("estado")
    if estado_de(fila) not in _EDITABLES:
        raise ValueError("estado")
    if fila["tipo"] != "post":
        raise ValueError("tipo")

    tpl = plantillas.obtener(cx, fila["template_id"])
    if tpl is None:
        raise ValueError("tipo")
    ct = plantillas.contrato_de(tpl)

    limpios = dict(campos)
    if "imagen" in limpios and limpios["imagen"]:
        limpios["imagen"] = _resolver_image_url(cx, fila, limpios["imagen"])

    errores = contrato.validar_campos(limpios, ct)
    if errores:
        raise ValueError("campos: " + "; ".join(errores))

    db.update(cx, "content_queue", queue_id,
              campos_json=json.dumps(limpios, ensure_ascii=False),
              caption=limpios.get("titular"))
```

Si `_resolver_image_url` tiene otra firma, adáptala; su contrato es "valida y normaliza una URL o una ruta del banco de la marca".

- [ ] **Step 4: Escribir el endpoint**

En `api/routers/cola.py`, junto al de slides:

```python
class EditarCampos(BaseModel):
    campos: dict[str, Any]


_ERRORES_CAMPOS = {
    "estado": "Esta pieza ya no se puede editar",
    "tipo": "Esta pieza no es un post simple",
    "url": "La imagen no es válida",
}


@router.put("/queue/{qid}/campos", status_code=202)
def editar_campos(slug: str, qid: int, datos: EditarCampos,
                  user=Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    _item_de_marca(cx, fila["id"], qid)
    try:
        cola.editar_campos(cx, qid, datos.campos)
    except ValueError as e:
        clave = str(e).split(":")[0]
        detalle = _ERRORES_CAMPOS.get(clave, str(e).split(": ", 1)[-1])
        raise ApiError(422, "validacion", detalle, "campos") from None
    job_id = jobs.crear(cx, "post.rerender", fila["id"], {"queue_id": qid},
                        creado_por=user["id"])
    return {"job_id": job_id}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cola_campos.py tests/test_cola.py tests/test_api_cola.py -v`
Expected: PASS. Los tests de cola que ya existían siguen en verde sin tocarlos.

- [ ] **Step 6: Commit**

```bash
git add src/cola.py api/routers/cola.py tests/test_cola_campos.py
git commit -m "feat(h2): editar campos de un post y re-renderizar"
```

---

### Task 8: `POST /brands/{slug}/posts` y preview de plantilla

**Files:**
- Create: `api/routers/posts.py`
- Create: `src/plantillas/preview.py`
- Modify: `api/app.py`
- Test: `tests/test_api_posts.py`

**Interfaces:**
- Produces:
  - `POST /brands/{slug}/posts` → `{"job_id": n}`. Body: `template_id`, `tema`, `entidad_id?`, `campos?`, `imagen?`. Rol mínimo `editor`.
  - `GET /brands/{slug}/templates` → lista de plantillas activas de la marca. Rol mínimo `editor`.
  - `GET /brands/{slug}/templates/{tid}/preview.png` → PNG cacheado. Rol mínimo `editor`.
  - `src/plantillas/preview.py`: `png_de(cx, marca, template_id: int) -> Path`

**Molde del preview:** `src/estilo_preview.py:44-77`. Cachea en `data/previews/tpl_<slug>_<tid>_<hash12>.png`, donde el hash es `sha1` del HTML más el contrato, así que se invalida solo cuando la plantilla cambia. Usa datos de muestra y una foto del banco de la marca si hay. Borra los previews viejos del mismo `template_id`.

Datos de muestra: `{"titular": "Titular de ejemplo para ver cómo se acomoda el texto"}` más, por cada extra, un valor del tipo correcto (una lista de N cadenas `"Elemento N"` para las listas, `"Ejemplo"` para textos, `0` para números, `True` para booleanos). Escribe un helper `campos_de_muestra(contrato) -> dict` en `preview.py` y **pruébalo aparte**: es lo que evita que el preview reviente con una plantilla que declara extras raros.

**Autorización:** todos los endpoints pasan por `marca_para(slug, cx, user)` como el resto (`api/deps.py:35`). Crear un post es acción de contenido: `editor` basta.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_api_posts.py` siguiendo el patrón de `tests/test_api_cola.py` (mismo cliente de prueba, mismos helpers de sesión y de usuario). Cubre como mínimo:

```python
def test_crear_post_encola_job(cliente, cx, marca, plantilla) -> None:
    r = cliente.post(f"/brands/gdlscene/posts",
                     json={"template_id": plantilla, "tema": "lo que sea"})
    assert r.status_code == 202
    assert "job_id" in r.json()


def test_crear_post_con_plantilla_de_otra_marca_es_rechazado(
        cliente, cx, plantilla_ajena) -> None:
    """Aislamiento entre marcas: no puedes usar el diseño de otra cuenta."""
    r = cliente.post("/brands/gdlscene/posts",
                     json={"template_id": plantilla_ajena, "tema": "x"})
    assert r.status_code in (403, 404, 422)
    # Y no se encoló nada.
    assert db.rows(cx, "SELECT count(*) c FROM jobs WHERE tipo='post.generar'")[0]["c"] == 0


def test_editor_puede_crear_post(cliente_editor, plantilla) -> None:
    """Crear contenido es acción de editor, no de manager."""
    r = cliente_editor.post("/brands/gdlscene/posts",
                            json={"template_id": plantilla, "tema": "x"})
    assert r.status_code == 202


def test_usuario_sin_membresia_recibe_403(cliente_ajeno, plantilla) -> None:
    r = cliente_ajeno.post("/brands/gdlscene/posts",
                           json={"template_id": plantilla, "tema": "x"})
    assert r.status_code == 403


def test_listar_plantillas_solo_las_de_la_marca(
        cliente, cx, plantilla, plantilla_ajena) -> None:
    r = cliente.get("/brands/gdlscene/templates")
    assert r.status_code == 200
    ids = [t["id"] for t in r.json()]
    assert plantilla in ids and plantilla_ajena not in ids


def test_las_plantillas_traen_su_contrato(cliente, plantilla) -> None:
    """El wizard genera el formulario desde `contrato`: si no viaja, no hay UI."""
    fila = next(t for t in cliente.get("/brands/gdlscene/templates").json()
                if t["id"] == plantilla)
    assert "contrato" in fila and "extras" in fila["contrato"]
    assert fila["version_actual"] >= 1   # el ?v= del preview sale de aquí


def test_preview_devuelve_png(cliente, plantilla) -> None:
    r = cliente.get(f"/brands/gdlscene/templates/{plantilla}/preview.png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content.startswith(b"\x89PNG") and len(r.content) > 10_000


def test_preview_de_plantilla_ajena_no_se_sirve(cliente, plantilla_ajena) -> None:
    r = cliente.get(f"/brands/gdlscene/templates/{plantilla_ajena}/preview.png")
    assert r.status_code in (403, 404)


def test_campos_de_muestra_cubre_todos_los_tipos() -> None:
    """Unitario del helper, sin HTTP: una plantilla con un extra de cada
    tipo produce campos que pasan validar_campos."""
    from src.plantillas import contrato as c, preview
    ct = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": [
        {"id": "t", "tipo": "texto"},
        {"id": "tl", "tipo": "texto_largo"},
        {"id": "n", "tipo": "numero"},
        {"id": "b", "tipo": "booleano"},
        {"id": "l", "tipo": "lista", "min": 2, "max": 4},
        {"id": "i", "tipo": "imagen"},
    ]}
    assert c.validar_campos(preview.campos_de_muestra(ct), ct) == []
```

Lee `tests/test_api_cola.py` completo antes de escribir y reusa sus fixtures en vez de inventar otras. Las que este archivo necesita y que probablemente tengas que agregar:

| Fixture | Qué da |
|---|---|
| `cliente` | cliente de prueba autenticado como manager de gdlscene |
| `cliente_editor` | lo mismo, con rol `editor` |
| `cliente_ajeno` | usuario válido SIN membresía en gdlscene |
| `plantilla` | id de una plantilla activa de gdlscene |
| `plantilla_ajena` | id de una plantilla de otra cuenta, para probar el aislamiento |

`test_preview_devuelve_png` levanta Chromium de verdad y es el más lento del archivo. Los tres tests de aislamiento entre marcas son los que más valen: son la diferencia entre un portal multi-marca y uno que finge serlo.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_posts.py -v`
Expected: FAIL — 404 en las rutas nuevas.

- [ ] **Step 3: Escribir `src/plantillas/preview.py`, `api/routers/posts.py` y montar el router**

`preview.py` copia la estructura de `src/estilo_preview.py` (hash del contenido → nombre de archivo, cache dir, limpieza de versiones viejas), pero renderiza con `render.render(cx, marca, plantilla, campos_de_muestra(ct))`.

`api/routers/posts.py` sigue el estilo de `api/routers/trabajos.py` para el `POST` que encola, y el de `api/routers/perfil.py:242-270` para servir el PNG con `FileResponse`.

En `api/app.py`, montar el router junto a los demás `include_router`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_api_posts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/routers/posts.py api/app.py src/plantillas/preview.py tests/test_api_posts.py
git commit -m "feat(h2): endpoints de post simple y preview de plantilla"
```

---

### Task 9: Wizard de post simple en el portal

**Files:**
- Create: `frontend/hooks/use-templates.ts`
- Create: `frontend/app/b/[slug]/create/_components/paso-plantilla.tsx`
- Create: `frontend/app/b/[slug]/create/_components/paso-campos.tsx`
- Create: `frontend/app/b/[slug]/create/_components/paso-tipo.tsx`
- Modify: `frontend/hooks/use-job.ts`
- Modify: `frontend/app/b/[slug]/create/page.tsx`
- Modify: `frontend/app/b/[slug]/create/_components/wizard-steps.tsx`

**Interfaces:**
- Consumes: `GET /brands/{slug}/templates`, `POST /brands/{slug}/posts`, `useJob` (ya existe).
- Produces: `useTemplates(slug)`, `useCrearPost(slug)`, y tres componentes de paso.

**Moldes exactos, no inventes patrones nuevos:**
- `paso-estilo.tsx` para `paso-plantilla.tsx`: grid de tarjetas clicables con `<img src="/api/brands/{slug}/templates/{tid}/preview.png?v={version_actual}" />` y fallback si la imagen no carga. El `?v=` es lo que invalida el caché del navegador cuando la plantilla cambia de versión.
- `use-job.ts:62-67` (`useCrearSlideshow`) para `useCrearPost`.
- `ProgresoJob` y `useJob` se reusan **tal cual**: son agnósticos al tipo de job.

**`paso-campos.tsx`** genera el formulario desde `contrato_json.extras`:

| `tipo` | Control |
|---|---|
| `texto` | `<Input>` |
| `texto_largo` | `<Textarea>` |
| `numero` | `<Input type="number">`, y se manda **como número**, no como string |
| `booleano` | `<Switch>` |
| `lista` | `<ChipInput>` (ya existe en `frontend/components/chip-input.tsx`), con el mínimo y el máximo del contrato |
| `imagen` | reusa el selector del banco de fotos de `fotos-panel.tsx` |

`titular` siempre va primero y siempre visible. Los extras opcionales van bajo un "Opcionales" plegado — `PRODUCT.md` pide progressive disclosure: los defaults funcionan y la complejidad se revela cuando se necesita.

**`paso-tipo.tsx`** es el primer paso nuevo: "¿Carrusel o post simple?". Si elige carrusel, el wizard sigue exactamente como hoy (no se toca ese camino). Si elige post simple, va a plantilla → tema → campos.

**Reglas de UI que manda `PRODUCT.md`:** cero jerga técnica visible. En pantalla nunca aparecen las palabras "contrato", "JSON", "slug", "template_id" ni un código de error HTTP. La plantilla se llama "diseño", los campos se llaman por su `desc` del contrato, y si no tiene `desc`, por su `id` capitalizado.

- [ ] **Step 1: Escribir el hook de plantillas**

`frontend/hooks/use-templates.ts`, copiando la forma de `frontend/hooks/use-presets.ts`:

```ts
export type Plantilla = {
  id: number
  slug: string
  nombre: string
  descripcion: string | null
  aspecto: "4:5" | "9:16"
  version_actual: number
  contrato: { aspecto: string; base: string[]; extras: ExtraContrato[] }
}

export type ExtraContrato = {
  id: string
  tipo: "texto" | "texto_largo" | "numero" | "booleano" | "lista" | "imagen"
  desc?: string
  opcional?: boolean
  min?: number
  max?: number
}

export function useTemplates(slug: string) { /* useQuery a /brands/{slug}/templates */ }
```

- [ ] **Step 2: Escribir `useCrearPost`**

En `frontend/hooks/use-job.ts`, junto a `useCrearSlideshow`, con la misma forma: `useMutation` que hace `POST /brands/{slug}/posts` y devuelve `{ job_id }`.

- [ ] **Step 3: Escribir los tres componentes de paso**

Sigue literalmente el estilo de los `paso-*.tsx` que ya existen: props `{ valor, onChange }`, sin estado global, sin fetch propio salvo por su hook.

- [ ] **Step 4: Cablear el wizard**

En `page.tsx`, agregar el estado `tipoPieza: "carrusel" | "post"` y bifurcar la lista de pasos. `TOTAL_PASOS` deja de ser la constante `5` y pasa a derivarse del arreglo de pasos del tipo elegido. `WizardSteps` recibe la lista de títulos en vez de asumirla.

- [ ] **Step 5: Verificar que compila y que el lint pasa**

```bash
cd frontend && pnpm install --frozen-lockfile && pnpm lint && pnpm build
```
Expected: sin errores de TypeScript ni de ESLint.

- [ ] **Step 6: Commit**

```bash
git add frontend/
git commit -m "feat(h2): wizard de post simple con selector de plantilla"
```

---

### Task 10: Cierre — verificación end-to-end

**Files:**
- Create: `scripts/verificar_h2.py`

**Interfaces:**
- Produces: un script que genera un post real de gdlscene **y** uno de una marca no musical, contra una copia de la DB, sin publicar nada.

Este es el criterio de aceptación del hito, tal como lo fija el spec: *"se genera, edita, aprueba y publica un post de gdlscene y uno de melaquecapital desde el portal"*. El script cubre la parte automatizable; la aprobación y publicación se prueban a mano en el portal.

- [ ] **Step 1: Escribir el script**

```python
"""Genera un post simple real de dos marcas distintas, sin publicar.

Uso:
    cp ~/Work/personal/instagod/data/gdlscene.db /tmp/h2.db
    .venv/bin/python scripts/verificar_h2.py /tmp/h2.db

Llama al LLM de verdad y renderiza con Chromium de verdad. NO sube a
Instagram y NO toca la cola de publicación: las piezas quedan en borrador.
"""
```

Para cada una de las dos marcas: toma su primera plantilla activa, genera un post con un tema fijo, imprime la ruta del PNG y sus dimensiones, y verifica que la fila quedó con `tipo='post'`, `status='borrador'` y `aprobacion IS NULL`. Sale con 1 si algo falla.

Si `melaquecapital` no tiene plantillas (H1 solo sembró las de gdlscene), el script **crea una plantilla mínima genérica para esa marca** antes de generar, y lo dice en la salida. Eso es exactamente la prueba de que el sistema sirve para una marca que no es de música.

- [ ] **Step 2: Correrlo**

```bash
cp ~/Work/personal/instagod/data/gdlscene.db /tmp/h2.db
.venv/bin/python scripts/verificar_h2.py /tmp/h2.db
```
Expected: dos PNG generados, uno 1080×1350, e impresión de ambas rutas. Ábrelos y **míralos**: un test que dice "el archivo pesa más de 10 KB" no distingue un post bien compuesto de una mancha negra.

- [ ] **Step 3: Suite completa y lint**

```bash
.venv/bin/python -m pytest -p no:cacheprovider --junit-xml=/tmp/h2.xml
.venv/bin/python -m ruff check src/ tests/ api/ web/ scripts/verificar_h2.py
```
Expected: una sola falla (`test_segmentos_web::test_segmentos_lista_catalogo_y_preview`, de otra área) y lint limpio.

- [ ] **Step 4: Commit**

```bash
git add scripts/verificar_h2.py
git commit -m "chore(h2): verificación end-to-end del post simple"
```

---

## Definición de terminado para H2

- [ ] Suite con una sola falla, la de `test_segmentos_web`, y con más tests que al empezar.
- [ ] `ruff check src/ tests/ api/ web/` limpio.
- [ ] `pnpm lint` y `pnpm build` limpios en `frontend/`.
- [ ] `scripts/verificar_h2.py` genera dos PNG de dos marcas distintas, **y los PNG se vieron con los ojos**.
- [ ] Un post se genera, se edita campo por campo y se re-renderiza desde el portal corriendo en local.
- [ ] `src/compose.py` conserva `compose()`, `render_card()` y `TEMPLATES` con la misma firma y el mismo comportamiento.
- [ ] `src/caption.py` sin modificar.
- [ ] Ningún test preexistente modificado.

## Lo que H2 deliberadamente NO hace

- No diseña plantillas con el LLM. Eso es H3: aquí las plantillas se consumen, no se crean.
- No arma lotes ni toca `content_plans`. Eso es H4.
- No muestra estadísticas. Eso es H5.
- No retira el dict `TEMPLATES` de `src/compose.py` ni toca `templates/`. Eso es H5.
- No enciende el sandbox de render: el flag queda apagado, decisión 11 del spec.
- No implementa cuotas de LLM por marca. Es la deuda a saldar antes de dar de alta un cliente externo.
