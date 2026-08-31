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
| `imagen` | `campos["imagen"]`, pasado por `compose._to_src` (local → `file://`, URL/data intactas) |
| `handle` | `marca.ig_handle`, con `@` al frente |
| `logo` | `marca.logo_path` por `_to_src`; `None` si la marca no tiene logo |
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
    m = marcas.por_slug(cx, "gdlscene")
    ctx = R.contexto(m, {"titular": "Hola"})
    assert ctx["titular"] == "Hola"
    assert ctx["handle"].startswith("@")
    assert "color_marca" in ctx and "logo" in ctx and "fonts_dir" in ctx


def test_contexto_no_deja_pasar_none_como_imagen(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.por_slug(cx, "gdlscene")
    ctx = R.contexto(m, {"titular": "Hola", "imagen": None})
    assert ctx["imagen"] is None  # la plantilla decide con {% if imagen %}


def test_render_produce_png(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.por_slug(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Prueba", _HTML.format(h=1350), _ct())
    p = plantillas.obtener(cx, tid)
    png = R.render(cx, m, p, {"titular": "HOLA"}, out_path=tmp_path / "a.png")
    assert png.exists() and png.stat().st_size > 10_000
    assert Image.open(png).size == (1080, 1350)


def test_render_respeta_el_aspecto_de_la_plantilla(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.por_slug(cx, "gdlscene")
    tid = plantillas.crear(cx, m.id, "Vertical", _HTML.format(h=1920),
                           _ct(aspecto="9:16"))
    p = plantillas.obtener(cx, tid)
    png = R.render(cx, m, p, {"titular": "HOLA"}, out_path=tmp_path / "b.png")
    assert Image.open(png).size == (1080, 1920)


def test_render_rechaza_campos_invalidos(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.por_slug(cx, "gdlscene")
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
    m = marcas.por_slug(cx, "gdlscene")
    plantillas_gdlscene.sembrar(cx, m.id)
    p = plantillas.por_slug(cx, m.id, "onion")
    png = R.render(cx, m, p, {"titular": "Banda local revienta el foro"},
                   out_path=tmp_path / "onion.png")
    assert png.exists() and png.stat().st_size > 10_000
```

Si `marcas` no expone `por_slug`, usar la función real del módulo (`marcas.listar` + filtro, o la que exista) y ajustar los seis usos. Verificar con `grep -n "^def " src/marcas.py` antes de escribir el test.

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
    imagen = campos.get("imagen")
    ctx["imagen"] = compose._to_src(imagen) if imagen else None
    handle = (marca.ig_handle or "").lstrip("@")
    ctx["handle"] = f"@{handle}" if handle else ""
    ctx["logo"] = compose._to_src(marca.logo_path) if marca.logo_path else None
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

Run: `.venv/bin/python -m pytest tests/test_plantillas_render.py -v`
Expected: PASS (6 tests). El último tarda: levanta Chromium de verdad.

- [ ] **Step 5: Commit**

```bash
git add src/plantillas/render.py src/plantillas/contrato.py tests/test_plantillas_render.py
git commit -m "feat(h2): contexto y render de plantillas de DB"
```
