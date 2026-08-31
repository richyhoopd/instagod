# H3 — Diseñador de plantillas con DeepSeek — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que alguien del equipo cree un diseño nuevo para su marca escribiéndole en español lo que quiere, vea el resultado renderizado, lo siga corrigiendo por chat, y pueda volver a cualquier versión anterior.

**Architecture:** Un módulo puro arma el prompt y valida la respuesta; un job asíncrono la ejecuta; `template_versions` —que ya existe desde H1— hace de historial y de log del chat a la vez, sin tabla nueva. La UI es una galería más un panel de conversación. Todo el andamio (tablas, CRUD versionado, validación de contrato y de HTML, render, preview cacheado) quedó construido en H1 y H2: H3 solo agrega el prompt, el job y la pantalla.

**Tech Stack:** Python 3.12+, SQLite, Jinja2, Playwright, DeepSeek vía SDK de OpenAI, FastAPI, Next.js 16 + React 19 + TanStack Query + shadcn.

**Spec:** `docs/superpowers/specs/2026-08-29-plantillas-lotes-y-stats-design.md`

**Hitos previos:** `2026-08-30-h1-cimiento-entidades-y-plantillas.md` y `2026-08-31-h2-post-simple-end-to-end.md`, ambos completos.

## Global Constraints

- **El worktree necesita dos symlinks al repo principal**, ya puestos: `.venv` y `.env` del repo principal. Un worktree de git no hereda archivos no versionados, y sin `.env` cuatro tests fallan por entorno y se confunden con regresiones.
- **Baseline: `1402 tests, 1 failure`** — `tests/test_segmentos_web.py::test_segmentos_lista_catalogo_y_preview`, de otra área y anterior a esta rama. No se toca.
- El `pytest -q` de este repo **no imprime su línea final de resumen**. Conteos fiables con `--junit-xml=/tmp/x.xml` y parseando el XML.
- **Cero llamadas reales al LLM en los tests.** Se mockea una sola función. Un test que sale a la red está mal escrito. El único que llama de verdad es el script de verificación final.
- **Nada toca producción.** Ni la VM, ni `/opt/instagod/`, ni `data/gdlscene.db` directamente.
- Línea máxima 100 (`ruff`). Comentarios y docstrings en español.
- Lint: `ruff check src/ tests/ api/ web/ config.py` limpio. **No** lintear `scripts/` completo: `scripts/portal_magic_link.py` arrastra un `F401` ajeno.
- En el frontend, `pnpm lint` sin errores y `pnpm build` compilando. Hay un warning preexistente en `app/login/page.tsx` que no es nuestro.
- **Cero jerga técnica en pantalla** (`PRODUCT.md`): nunca aparecen "contrato", "JSON", "slug", "HTML", "template_id" ni códigos de error. La plantilla se llama **diseño**.
- Vocabulario canónico del contrato: `titular`, `imagen`, `handle`, `logo`, `color_marca`. Variable de sistema: `fonts_dir`.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `api/routers/plantillas.py` (crear) | Todos los endpoints de diseños. Recibe los tres que hoy viven en `posts.py` |
| `api/routers/posts.py` (modificar) | Se queda solo con `POST /posts` |
| `src/plantillas/disenador.py` (crear) | Arma el prompt, llama al LLM, valida y reintenta. Puro salvo la llamada |
| `src/plantillas/fuentes_tipograficas.py` (crear) | Catálogo de fuentes disponibles para una marca: globales + propias |
| `src/plantillas/contrato.py` (modificar) | `validar_fuentes` y un tope de tamaño del HTML |
| `src/compose.py` (modificar) | No esperar el auto-fit cuando el HTML no lo declara |
| `src/jobs/handlers.py` (modificar) | Handler `template.disenar` |
| `frontend/hooks/use-templates.ts` (modificar) | Mutaciones de diseñar, chatear, revertir, activar, borrar |
| `frontend/hooks/use-fonts.ts` (crear) | Fuentes de la marca |
| `frontend/app/b/[slug]/templates/page.tsx` (crear) | Galería de diseños |
| `frontend/app/b/[slug]/templates/_components/*.tsx` (crear) | Tarjeta, chat, historial de versiones, diálogo de creación |
| `frontend/app/b/[slug]/layout.tsx` (modificar) | Entrada "Diseños" en el sidebar |
| `scripts/verificar_h3.py` (crear) | Crea una plantilla hablándole, itera y revierte, contra una copia |

---

### Task 1: Router propio para diseños

**Files:**
- Create: `api/routers/plantillas.py`
- Modify: `api/routers/posts.py`, `api/app.py`
- Test: `tests/test_api_posts.py` debe seguir pasando **sin tocarlo**

**Interfaces:**
- Produces: los tres endpoints que hoy están en `posts.py` (`GET /templates`, `GET /templates/{tid}/preview.png` y el helper `_plantilla_de_marca`), movidos tal cual a `api/routers/plantillas.py`, con las mismas rutas y las mismas respuestas.

Es un refactor puro: mismo prefijo, mismas rutas, mismo comportamiento. H3 agrega ocho endpoints más de diseños, y dejarlos en el router de posts convertiría ese archivo en un cajón. `POST /posts` se queda donde está.

- [ ] **Step 1: Mover, sin cambiar nada**

Corta de `api/routers/posts.py` el helper `_plantilla_de_marca`, `GET /templates` y `GET /templates/{tid}/preview.png`, y pégalos en `api/routers/plantillas.py` con el mismo `APIRouter` (mismo `prefix` y `tags` que usa `posts.py`). `POST /posts` necesita `_plantilla_de_marca`: impórtalo desde el módulo nuevo, no lo dupliques.

- [ ] **Step 2: Montar el router en `api/app.py`**

Junto a los demás `include_router`.

- [ ] **Step 3: Verificar que nada cambió**

Run: `.venv/bin/python -m pytest tests/test_api_posts.py -v`
Expected: PASS, los 13, **sin haber tocado el archivo de test**. Si hay que tocarlo, el refactor cambió la API y está mal.

- [ ] **Step 4: Commit**

```bash
git add api/
git commit -m "refactor(h3): router propio para diseños, sin cambiar la API"
```

---

### Task 2: Catálogo de fuentes por marca

**Files:**
- Create: `src/plantillas/fuentes_tipograficas.py`
- Modify: `src/plantillas/contrato.py`
- Test: `tests/test_fuentes_tipograficas.py`

**Interfaces:**
- Produces:
  - `catalogo(cx, account_id: int) -> list[dict]` — `[{"familia": str, "archivo": str, "propia": bool}]`, las globales de `config.SLIDESHOW_FUENTES` más las de `brand_fonts` de esa marca. Las propias pisan a las globales con el mismo nombre.
  - `familias(cx, account_id: int) -> set[str]`
  - `css_font_faces(cx, account_id: int, fonts_dir: str) -> str` — los `@font-face` listos para inyectar
  - En `contrato.py`: `validar_fuentes(html: str, familias: set[str]) -> list[str]` y `MAX_HTML = 60_000`

**Por qué el tope de tamaño:** un LLM que se descarrila puede devolver cientos de kilobytes de HTML. Se guarda en la DB, se renderiza en Chromium y se manda al navegador. 60 KB es holgado para una plantilla real (las cuatro de gdlscene rondan los 3 KB) y ataja lo absurdo.

**Sobre `Tinos-Italic`:** el archivo `templates/assets/fonts/Tinos-Italic.ttf` existe en disco pero **no está en `config.SLIDESHOW_FUENTES`**. Las plantillas de gdlscene lo usan con un `@font-face` propio. Agrégalo al dict del config como `"Tinos-Italic": "Tinos-Italic.ttf"`: si el LLM solo puede pedir del catálogo, esa fuente le sería invisible sin razón.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_fuentes_tipograficas.py`:

```python
"""Catálogo tipográfico por marca: globales + propias."""
from __future__ import annotations

import config
from src import db, marcas
from src.plantillas import contrato as c
from src.plantillas import fuentes_tipograficas as ft


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_el_catalogo_trae_las_globales(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    fams = ft.familias(cx, m.id)
    assert "Anton-Regular" in fams and "Tinos-Regular" in fams


def test_tinos_italic_esta_en_el_catalogo() -> None:
    """Existe en disco y las plantillas de gdlscene la usan."""
    assert "Tinos-Italic" in config.SLIDESHOW_FUENTES


def test_las_propias_de_la_marca_se_suman(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    db.insert(cx, "brand_fonts", account_id=m.id, familia="MiFuente",
              archivo="fonts/mifuente.woff2")
    cat = ft.catalogo(cx, m.id)
    propia = next(f for f in cat if f["familia"] == "MiFuente")
    assert propia["propia"] is True
    assert any(f["familia"] == "Anton-Regular" and not f["propia"] for f in cat)


def test_una_propia_pisa_a_la_global_del_mismo_nombre(tmp_path) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    db.insert(cx, "brand_fonts", account_id=m.id, familia="Anton-Regular",
              archivo="fonts/anton-custom.woff2")
    cat = [f for f in ft.catalogo(cx, m.id) if f["familia"] == "Anton-Regular"]
    assert len(cat) == 1 and cat[0]["propia"] is True


def test_el_catalogo_aisla_marcas(tmp_path) -> None:
    cx = _cx(tmp_path)
    otra = db.insert(cx, "accounts", slug="otra", ig_handle="otra",
                     nombre="Otra", ciudad="CDMX")
    db.insert(cx, "brand_fonts", account_id=otra, familia="Ajena",
              archivo="fonts/ajena.woff2")
    m = marcas.cargar(cx, "gdlscene")
    assert "Ajena" not in ft.familias(cx, m.id)
    assert "Ajena" in ft.familias(cx, otra)


def test_validar_fuentes_acepta_las_del_catalogo() -> None:
    html = "<style>.card{font-family:'Anton-Regular',sans-serif}</style>"
    assert c.validar_fuentes(html, {"Anton-Regular"}) == []


def test_validar_fuentes_rechaza_una_inventada() -> None:
    html = "<style>.card{font-family:'Helvetica Neue Ultra',sans-serif}</style>"
    errs = c.validar_fuentes(html, {"Anton-Regular"})
    assert errs and "Helvetica Neue Ultra" in errs[0]


def test_validar_fuentes_tolera_genericas() -> None:
    """sans-serif, serif y monospace no son fuentes que haya que tener."""
    html = "<style>.card{font-family:sans-serif} .x{font-family:monospace}</style>"
    assert c.validar_fuentes(html, set()) == []


def test_html_demasiado_grande_se_rechaza() -> None:
    import pytest
    grande = "<div>" + "x" * (c.MAX_HTML + 1) + "</div>"
    ct = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}
    with pytest.raises(c.ContratoInvalido, match="grande"):
        c.validar_html(grande, ct)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_fuentes_tipograficas.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Agregar `Tinos-Italic` al catálogo de `config.py`**

En `SLIDESHOW_FUENTES`, junto a las otras Tinos:

```python
    "Tinos-Italic": "Tinos-Italic.ttf",
```

- [ ] **Step 4: Escribir `src/plantillas/fuentes_tipograficas.py`**

```python
"""Qué tipografías puede usar una marca: las globales más las suyas.

El diseñador con LLM recibe esta lista y solo puede pedir de aquí. Es lo que
hace el render determinista y offline: nada de webfonts externas que el día
que falle el DNS dejen un post publicado con la tipografía equivocada.
"""
from __future__ import annotations

from typing import Any

import config

from .. import db


def catalogo(cx, account_id: int) -> list[dict[str, Any]]:
    """Globales + propias de la marca. Las propias pisan por nombre."""
    fuentes: dict[str, dict[str, Any]] = {
        familia: {"familia": familia, "archivo": archivo, "propia": False}
        for familia, archivo in config.SLIDESHOW_FUENTES.items()
    }
    for fila in db.rows(cx, "SELECT familia, archivo FROM brand_fonts "
                            "WHERE account_id = ? ORDER BY familia", (account_id,)):
        fuentes[fila["familia"]] = {"familia": fila["familia"],
                                    "archivo": fila["archivo"], "propia": True}
    return sorted(fuentes.values(), key=lambda f: f["familia"])


def familias(cx, account_id: int) -> set[str]:
    return {f["familia"] for f in catalogo(cx, account_id)}


def css_font_faces(cx, account_id: int, fonts_dir: str) -> str:
    """Bloque de @font-face para inyectar en el HTML de una plantilla."""
    piezas = []
    for f in catalogo(cx, account_id):
        ruta = f["archivo"] if f["propia"] else f"{fonts_dir}/{f['archivo']}"
        piezas.append(
            f"@font-face{{font-family:'{f['familia']}';src:url('{ruta}');"
            "font-display:block;}"
        )
    return "\n".join(piezas)
```

- [ ] **Step 5: Agregar `validar_fuentes` y `MAX_HTML` a `contrato.py`**

```python
# Un LLM descarrilado puede devolver cientos de kilobytes. Las cuatro
# plantillas de gdlscene rondan los 3 KB, así que 60 KB es holgado y ataja
# lo absurdo antes de guardarlo en la DB y mandarlo a Chromium.
MAX_HTML = 60_000

# No son tipografías que haya que tener instaladas.
_GENERICAS = {"sans-serif", "serif", "monospace", "cursive", "fantasy",
              "system-ui", "inherit", "initial", "unset"}

_FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}\n]+)", re.I)


def validar_fuentes(html: str, familias: set[str]) -> list[str]:
    """Toda familia citada en el HTML debe estar en el catálogo de la marca."""
    errores: list[str] = []
    for declaracion in _FONT_FAMILY.findall(html or ""):
        for bruto in declaracion.split(","):
            nombre = bruto.strip().strip("'\"")
            if not nombre or nombre.lower() in _GENERICAS:
                continue
            if nombre not in familias:
                errores.append(
                    f"la tipografía '{nombre}' no está disponible para esta marca")
    return errores
```

Y al principio de `validar_html`, antes de parsear:

```python
    if len(html or "") > MAX_HTML:
        raise ContratoInvalido(
            f"el HTML es demasiado grande ({len(html)} caracteres, tope {MAX_HTML})")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fuentes_tipograficas.py tests/test_contrato_plantilla.py tests/test_equivalencia_plantillas.py -v`
Expected: PASS. Los de equivalencia siguen verdes: agregar una fuente al catálogo no cambia ningún PNG.

- [ ] **Step 7: Commit**

```bash
git add config.py src/plantillas/ tests/test_fuentes_tipograficas.py
git commit -m "feat(h3): catálogo tipográfico por marca y tope de tamaño del HTML"
```

---

### Task 3: No esperar el auto-fit cuando el HTML no lo declara

**Files:**
- Modify: `src/compose.py`
- Test: `tests/test_compose_desde_db.py`

**Interfaces:**
- Produces: `_screenshot_card` solo espera `window.__captionFitted` si la cadena `__captionFitted` aparece en el HTML.

**El problema:** las cuatro plantillas de gdlscene traen un script de auto-ajuste del titular que al terminar hace `window.__captionFitted = true`, y `_screenshot_card` lo espera con `wait_for_function(..., timeout=5000)` dentro de un `try/except`. Una plantilla diseñada por el LLM no tiene por qué traer ese script, así que **cada render se comería 5 segundos de espera inútil** antes de rendirse. Con una galería de previews eso es la diferencia entre una pantalla que carga y una que parece rota.

La solución es una línea y no cambia nada del camino viejo: si el HTML no menciona `__captionFitted`, no hay nada que esperar.

- [ ] **Step 1: Write the failing test**

Agregar a `tests/test_compose_desde_db.py`:

```python
def test_no_espera_el_autofit_si_el_html_no_lo_declara(tmp_path) -> None:
    """Sin este atajo, cada plantilla del LLM pagaría 5s de timeout."""
    import time

    html = """<!doctype html><html><head><style>
      .card { width:1080px; height:1350px; background:#222; }
    </style></head><body><div class="card"></div></body></html>"""
    t0 = time.monotonic()
    png = compose.render_html(html, aspecto="4:5", out_path=tmp_path / "sin.png")
    tardo = time.monotonic() - t0
    assert png.exists()
    assert tardo < 4.5, f"esperó el auto-fit sin necesidad: {tardo:.1f}s"


def test_sigue_esperando_el_autofit_cuando_si_lo_declara(tmp_path) -> None:
    """El camino viejo no cambia: si la plantilla lo declara, se espera."""
    html = """<!doctype html><html><head><style>
      .card { width:1080px; height:1350px; background:#222; }
    </style></head><body><div class="card"></div>
    <script>setTimeout(function(){ window.__captionFitted = true; }, 300);</script>
    </body></html>"""
    png = compose.render_html(html, aspecto="4:5", out_path=tmp_path / "con.png")
    assert png.exists() and png.stat().st_size > 5_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compose_desde_db.py -v`
Expected: FAIL — el primero tarda ~5s y revienta la aserción.

- [ ] **Step 3: Implementar el atajo**

En `_screenshot_card`, envolver la espera:

```python
            # El auto-fit es de las plantillas de gdlscene: un script que al
            # terminar pone window.__captionFitted = true. Una plantilla nueva
            # no tiene por qué traerlo, y esperarlo costaría 5s de timeout por
            # render. Si el HTML no lo menciona, no hay nada que esperar.
            if "__captionFitted" in html:
                try:
                    page.wait_for_function("window.__captionFitted === true",
                                           timeout=5000)
                except Exception:
                    pass  # si falla el fit, igual renderiza con el tamaño base
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_compose_desde_db.py tests/test_equivalencia_plantillas.py tests/test_compose.py tests/test_slide_render.py -v`
Expected: PASS. **Los de equivalencia son la prueba de que el camino viejo no cambió**: las cuatro plantillas de gdlscene sí declaran `__captionFitted`, así que siguen esperándolo y siguen produciendo el mismo PNG byte a byte.

- [ ] **Step 5: Commit**

```bash
git add src/compose.py tests/test_compose_desde_db.py
git commit -m "perf(h3): no esperar el auto-fit cuando la plantilla no lo declara"
```

---

### Task 4: El diseñador

**Files:**
- Create: `src/plantillas/disenador.py`
- Test: `tests/test_disenador.py`

**Interfaces:**
- Produces:
  - `construir_prompt(*, marca, mensaje, familias, anterior=None, errores=None) -> str`
  - `extraer_respuesta(texto: str) -> dict | None`
  - `disenar(cx, marca, mensaje: str, *, anterior: dict | None = None, intentos: int = 2) -> dict` — devuelve `{"nombre", "descripcion", "html", "contrato"}` ya validado
  - `_pedir_al_llm(prompt: str) -> str` — única superficie de red, es lo que se mockea
  - `DisenoInvalido(ValueError)`

**Lo que el prompt SÍ lleva:**
- La voz y el color de la marca, y si tiene logo.
- El catálogo de tipografías, enumerado. Solo puede usar esas.
- El contrato base obligatorio (`titular`, `imagen`, `handle`, `logo`, `color_marca`) y cómo declarar extras.
- Las dimensiones exactas del aspecto pedido, y que el nodo raíz debe ser `.card`.
- Los filtros disponibles (`resaltar`, `etiqueta`) y qué hacen.
- Una plantilla de ejemplo corta, como referencia de estructura.
- **Solo el HTML de la versión anterior** si es una iteración.

**Lo que el prompt NO lleva, y es deliberado:**
- El historial completo del chat. Iterar diez veces debe costar diez llamadas de tamaño constante, no diez llamadas cada vez más caras. El historial vive en `template_versions` para que el usuario vuelva a cualquier versión; el LLM solo ve la última.

**Validación, en este orden.** Si algo falla, se reintenta UNA vez con los errores como contexto; al segundo fallo se lanza `DisenoInvalido` con el HTML crudo adjunto para poder inspeccionarlo:
1. La respuesta es un objeto JSON con `nombre`, `html` y `contrato`.
2. `contrato.validar(contrato)` — aspecto conocido, núcleo base completo, extras bien formados.
3. `contrato.validar_html(html, contrato)` — tamaño, Jinja parsea **y compila** (esto atrapa filtros inventados), y toda variable está declarada.
4. `contrato.validar_fuentes(html, familias)` — nada de tipografías que la marca no tiene.
5. El HTML contiene un nodo con `class="card"`, o el screenshot no encuentra qué recortar.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_disenador.py`:

```python
"""El diseñador de plantillas. El LLM va mockeado: cero red."""
from __future__ import annotations

import json

import pytest

from src import db, marcas
from src.plantillas import contrato as c
from src.plantillas import disenador as d

_BUENO = {
    "nombre": "Ficha de propiedad",
    "descripcion": "Fondo oscuro, titular grande, precio abajo",
    "contrato": {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []},
    "html": ("<div class=\"card\" style=\"width:1080px;height:1350px;"
             "background:{{ color_marca }};font-family:'Anton-Regular',sans-serif\">"
             "<h1>{{ titular }}</h1><span>{{ handle }}</span></div>"),
}


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _responde(monkeypatch, *respuestas):
    vistos: list[str] = []

    def fake(prompt: str) -> str:
        vistos.append(prompt)
        return respuestas[min(len(vistos) - 1, len(respuestas) - 1)]

    monkeypatch.setattr(d, "_pedir_al_llm", fake)
    return vistos


def test_diseno_valido(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    _responde(monkeypatch, json.dumps(_BUENO))
    out = d.disenar(cx, m, "una ficha de propiedad")
    assert out["nombre"] == "Ficha de propiedad"
    assert "{{ titular }}" in out["html"]


def test_el_prompt_lleva_el_catalogo_de_fuentes(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    vistos = _responde(monkeypatch, json.dumps(_BUENO))
    d.disenar(cx, m, "algo")
    assert "Anton-Regular" in vistos[0] and "Tinos-Regular" in vistos[0]


def test_rechaza_una_tipografia_inventada(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    malo = dict(_BUENO, html=_BUENO["html"].replace("Anton-Regular", "Comic Papyrus"))
    _responde(monkeypatch, json.dumps(malo))
    with pytest.raises(d.DisenoInvalido, match="Comic Papyrus"):
        d.disenar(cx, m, "algo")


def test_rechaza_un_filtro_inventado(tmp_path, monkeypatch) -> None:
    """El validador compila, no solo parsea: los filtros falsos se atrapan."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    malo = dict(_BUENO, html=_BUENO["html"].replace("{{ titular }}",
                                                    "{{ titular | glitchear }}"))
    _responde(monkeypatch, json.dumps(malo))
    with pytest.raises(d.DisenoInvalido):
        d.disenar(cx, m, "algo")


def test_rechaza_html_sin_nodo_card(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    malo = dict(_BUENO, html=_BUENO["html"].replace('class="card"', 'class="caja"'))
    _responde(monkeypatch, json.dumps(malo))
    with pytest.raises(d.DisenoInvalido, match="card"):
        d.disenar(cx, m, "algo")


def test_reintenta_una_vez_con_el_error(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    malo = dict(_BUENO, html=_BUENO["html"].replace("Anton-Regular", "Comic Papyrus"))
    vistos = _responde(monkeypatch, json.dumps(malo), json.dumps(_BUENO))
    out = d.disenar(cx, m, "algo")
    assert out["nombre"] == "Ficha de propiedad"
    assert len(vistos) == 2
    assert "Comic Papyrus" in vistos[1], "el reintento debe llevar el error"


def test_se_rinde_al_segundo_fallo(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    malo = dict(_BUENO, html=_BUENO["html"].replace("Anton-Regular", "Comic Papyrus"))
    _responde(monkeypatch, json.dumps(malo))
    with pytest.raises(d.DisenoInvalido) as exc:
        d.disenar(cx, m, "algo")
    assert exc.value.html_crudo, "hay que conservar el HTML para inspeccionarlo"


def test_la_iteracion_manda_solo_la_version_anterior(tmp_path, monkeypatch) -> None:
    """Iterar diez veces no debe costar diez prompts cada vez más grandes."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    vistos = _responde(monkeypatch, json.dumps(_BUENO))
    anterior = {"html": "<div class='card'>VERSION ANTERIOR</div>",
                "contrato_json": json.dumps(_BUENO["contrato"])}
    d.disenar(cx, m, "hazla más oscura", anterior=anterior)
    assert "VERSION ANTERIOR" in vistos[0]
    assert vistos[0].count("VERSION ANTERIOR") == 1


def test_el_prompt_lleva_la_voz_de_la_marca(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    vistos = _responde(monkeypatch, json.dumps(_BUENO))
    d.disenar(cx, m, "algo")
    assert m.color_marca in vistos[0]


def test_extraer_respuesta_tolera_fences() -> None:
    assert d.extraer_respuesta('```json\n{"nombre":"X"}\n```') == {"nombre": "X"}
    assert d.extraer_respuesta("no puedo") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_disenador.py -v`
Expected: FAIL con `ModuleNotFoundError`.

- [ ] **Step 3: Escribir `src/plantillas/disenador.py`**

Sigue el molde de `src/plantillas/generador.py` (creado en H2): mismo `_pedir_al_llm` delegando en `slideshow_script._via_deepseek` / `_via_anthropic` con `system_prompt=""`, misma forma de extraer el JSON con regex tolerante a fences, mismo bucle de reintento anexando los errores previos.

`DisenoInvalido` debe llevar un atributo `html_crudo` con lo que devolvió el LLM en el último intento, para poder inspeccionarlo desde el log del job.

El prompt lleva las dimensiones concretas: `contrato.dimensiones(aspecto)` da `(1080, 1350)` o `(1080, 1920)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_disenador.py -v`
Expected: PASS (10 tests), sin una sola llamada de red.

- [ ] **Step 5: Commit**

```bash
git add src/plantillas/disenador.py tests/test_disenador.py
git commit -m "feat(h3): diseñador de plantillas con validación estricta"
```

---

### Task 5: Job `template.disenar` y endpoints del diseñador

**Files:**
- Modify: `src/jobs/handlers.py`
- Modify: `api/routers/plantillas.py`
- Test: `tests/test_api_disenador.py`

**Interfaces:**
- Job `template.disenar`. Payload: `{"mensaje": str, "template_id": int | None, "aspecto": "4:5"|"9:16"}`. Si `template_id` es `None` crea una plantilla nueva en `borrador`; si viene, agrega una versión a esa. Al terminar genera el preview de la versión nueva y deja `queue_id` sin tocar (esto no produce piezas).
- Endpoints nuevos en `api/routers/plantillas.py`, todos con rol mínimo **`manager`** salvo los de lectura, que son `editor`:

| Método | Ruta | Qué hace | Rol |
|---|---|---|---|
| POST | `/brands/{slug}/templates` | encola `template.disenar` sin `template_id` | manager |
| POST | `/brands/{slug}/templates/{tid}/chat` | encola `template.disenar` con `template_id` | manager |
| GET | `/brands/{slug}/templates/{tid}/versions` | historial, más nuevo primero | editor |
| POST | `/brands/{slug}/templates/{tid}/revert` | body `{version:int}`, copia esa versión al final | manager |
| PATCH | `/brands/{slug}/templates/{tid}` | `nombre`, `descripcion`, `estado` | manager |
| DELETE | `/brands/{slug}/templates/{tid}` | archiva; **no borra** | manager |
| GET | `/brands/{slug}/fonts` | catálogo tipográfico | editor |
| POST | `/brands/{slug}/fonts` | sube una fuente propia | manager |
| DELETE | `/brands/{slug}/fonts/{fid}` | quita una fuente propia | manager |

**Diseñar es acción de `manager`, no de `editor`.** Un editor genera contenido; cambiar el aspecto visual de la marca es otra cosa. Es la misma frontera que ya usa el repo para presets y fuentes.

**DELETE archiva, no borra.** Hay piezas publicadas que apuntan a esa plantilla por `content_queue.template_id`, y las estadísticas por plantilla de H5 las necesitan. Borrar de verdad dejaría huérfanas las filas y falsearía los números.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_api_disenador.py` reusando las fixtures de `tests/test_api_posts.py` (léelo antes). Cubre como mínimo:

```python
def test_crear_diseno_encola_job(cliente, cx) -> None:
    r = cliente.post("/brands/gdlscene/templates",
                     json={"mensaje": "una ficha de propiedad, fondo oscuro"})
    assert r.status_code == 202 and "job_id" in r.json()
    fila = db.rows(cx, "SELECT tipo FROM jobs ORDER BY id DESC LIMIT 1")[0]
    assert fila["tipo"] == "template.disenar"


def test_editor_no_puede_disenar(cliente_editor, plantilla) -> None:
    """Diseñar es de manager: cambia el aspecto visual de la marca."""
    r = cliente_editor.post("/brands/gdlscene/templates", json={"mensaje": "x"})
    assert r.status_code == 403


def test_chat_sobre_plantilla_ajena_no_pasa(cliente, plantilla_ajena) -> None:
    r = cliente.post(f"/brands/gdlscene/templates/{plantilla_ajena}/chat",
                     json={"mensaje": "más oscura"})
    assert r.status_code in (403, 404)


def test_versions_devuelve_el_historial(cliente, cx, plantilla) -> None:
    r = cliente.get(f"/brands/gdlscene/templates/{plantilla}/versions")
    assert r.status_code == 200
    vs = r.json()
    assert vs and vs[0]["version"] >= 1
    assert "html" not in vs[0], "el historial no expone el HTML crudo al listar"


def test_revert_agrega_version_no_borra(cliente, cx, plantilla) -> None:
    from src import plantillas
    plantillas.nueva_version(cx, plantilla, "<div class='card'>v2</div>",
                             plantillas.contrato_de(plantillas.obtener(cx, plantilla)))
    r = cliente.post(f"/brands/gdlscene/templates/{plantilla}/revert",
                     json={"version": 1})
    assert r.status_code == 200
    assert len(plantillas.versiones(cx, plantilla)) == 3


def test_delete_archiva_y_no_borra(cliente, cx, plantilla) -> None:
    from src import plantillas
    assert cliente.delete(f"/brands/gdlscene/templates/{plantilla}").status_code in (200, 204)
    assert plantillas.obtener(cx, plantilla)["estado"] == "archivada"


def test_fonts_lista_el_catalogo(cliente) -> None:
    r = cliente.get("/brands/gdlscene/fonts")
    assert r.status_code == 200
    assert any(f["familia"] == "Anton-Regular" for f in r.json())
```

Y un test del handler que NO mockea el diseñador entero, solo `_pedir_al_llm`, para ejercitar la costura completa job → diseñador → `plantillas.crear`:

```python
def test_el_handler_crea_la_plantilla_de_verdad(tmp_path, monkeypatch) -> None:
    """Costura completa: job -> diseñador -> plantillas.crear.

    Mockea SOLO `_pedir_al_llm`, que es lo único que sale de la máquina. Los
    tres bugs de H2 vivieron exactamente en costuras como esta, invisibles
    para los tests que mockean la función de en medio.
    """
    from src import db, jobs, marcas, plantillas
    from src.jobs import handlers
    from src.plantillas import disenador

    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    m = marcas.cargar(cx, "gdlscene")
    monkeypatch.setattr(disenador, "_pedir_al_llm", lambda prompt: json.dumps(_BUENO))

    jid = jobs.crear(cx, "template.disenar", m.id,
                     {"mensaje": "una ficha de propiedad", "aspecto": "4:5"})
    out = handlers.HANDLERS["template.disenar"](cx, db.get(cx, "jobs", jid))

    tpl = plantillas.obtener(cx, out["template_id"])
    assert tpl["account_id"] == m.id
    assert tpl["origen"] == "llm"
    assert tpl["estado"] == "borrador", "nace en borrador; la activa un humano"
    assert len(plantillas.versiones(cx, tpl["id"])) == 1
    assert plantillas.versiones(cx, tpl["id"])[0]["mensaje_usuario"] == "una ficha de propiedad"


def test_el_chat_agrega_version_a_la_misma_plantilla(tmp_path, monkeypatch) -> None:
    """Iterar no crea plantillas nuevas: agrega versiones a la existente."""
    from src import db, jobs, marcas, plantillas
    from src.jobs import handlers
    from src.plantillas import disenador

    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    m = marcas.cargar(cx, "gdlscene")
    monkeypatch.setattr(disenador, "_pedir_al_llm", lambda prompt: json.dumps(_BUENO))
    tid = plantillas.crear(cx, m.id, "Base", _BUENO["html"], _BUENO["contrato"])

    jid = jobs.crear(cx, "template.disenar", m.id,
                     {"mensaje": "más oscura", "template_id": tid, "aspecto": "4:5"})
    handlers.HANDLERS["template.disenar"](cx, db.get(cx, "jobs", jid))

    assert len(plantillas.listar(cx, m.id, estado=None)) == 1
    assert plantillas.obtener(cx, tid)["version_actual"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_api_disenador.py -v`
Expected: FAIL — 404 en las rutas nuevas.

- [ ] **Step 3: Escribir el handler y los endpoints**

El handler sigue el molde de los de H2: firma `(cx, job) -> dict`, `marcas.cargar(cx, _marca_de(cx, job["account_id"]))` (⚠️ `_marca_de` devuelve el **slug**, no el objeto), `jobs.progresar` en los puntos caros, errores que se propagan.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_api_disenador.py tests/test_api_posts.py -v`
Expected: PASS, y los 13 de posts sin tocarlos.

- [ ] **Step 5: Commit**

```bash
git add src/jobs/handlers.py api/routers/plantillas.py tests/test_api_disenador.py
git commit -m "feat(h3): job del diseñador y endpoints de diseños y fuentes"
```

---

### Task 6: La pantalla de diseños

**Files:**
- Create: `frontend/app/b/[slug]/templates/page.tsx` y `_components/`
- Create: `frontend/hooks/use-fonts.ts`
- Modify: `frontend/hooks/use-templates.ts`, `frontend/app/b/[slug]/layout.tsx`

**La pantalla:** galería de diseños de la marca a la izquierda, y al abrir uno, un panel con el preview grande, el chat y el historial de versiones.

**El chat.** Cada mensaje del usuario produce una versión. Mientras el job corre se muestra `ProgresoJob` (ya existe, es agnóstico al tipo de job). Al terminar, el preview se recarga con `?v={version_actual}` — ese cache-buster es lo único que hace que la imagen nueva aparezca.

**El historial.** Lista de versiones con su mensaje y su miniatura. "Volver a esta" llama a `revert`, que **agrega** una versión al final en vez de borrar. Hay que decirlo en la UI con esas palabras: nada se pierde.

**Reglas de producto** (`PRODUCT.md`): se llaman **diseños**, no plantillas ni templates. En pantalla no aparece la palabra HTML, ni JSON, ni contrato. El HTML crudo va detrás de un "ver código" plegado, para quien lo quiera. Los estados se dicen en lenguaje del equipo: "borrador", "en uso", "archivado".

- [ ] **Step 1: Los hooks**

`useDisenarTemplate(slug)`, `useChatTemplate(slug, tid)`, `useVersions(slug, tid)`, `useRevert(slug, tid)`, `usePatchTemplate(slug, tid)`, `useArchivarTemplate(slug, tid)`, `useFonts(slug)`. Molde: los que ya están en `use-templates.ts` y `use-job.ts`.

- [ ] **Step 2: Los componentes**

`galeria-disenos.tsx`, `panel-diseno.tsx`, `chat-diseno.tsx`, `historial-versiones.tsx`, `nuevo-diseno-dialog.tsx`. Molde de composición: `frontend/app/b/[slug]/plans/[pid]/page.tsx`, que ya hace lista + panel de detalle.

- [ ] **Step 3: La entrada del sidebar**

En `layout.tsx`, "Diseños" junto a las demás, visible solo para `manager` y `admin`.

- [ ] **Step 4: Verificar**

```bash
cd frontend && pnpm lint && pnpm build
```
Expected: sin errores. Hay un warning preexistente en `app/login/page.tsx` que no es nuestro.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(h3): pantalla de diseños con chat y versiones"
```

---

### Task 7: Verificación end-to-end

**Files:**
- Create: `scripts/verificar_h3.py`

Es el criterio de aceptación del hito, tal como lo fija el spec: **crear una plantilla de inmobiliaria hablándole, iterar tres veces y volver a la v2.**

El script, contra una copia de la DB y llamando a DeepSeek de verdad:
1. Toma `melaquecapital` (o la primera marca no musical que encuentre).
2. Crea un diseño con un mensaje en español: *"una ficha de propiedad, fondo oscuro, el precio grande abajo a la derecha"*.
3. Itera tres veces: *"súbele el contraste"*, *"pon el handle arriba en vez de abajo"*, *"hazla más sobria, menos decoración"*.
4. Vuelve a la versión 2 y comprueba que eso **agrega** una versión (queda con 5) en vez de borrar.
5. Renderiza el preview de cada versión y **guarda los 5 PNG** en una carpeta, imprimiendo sus rutas para poder mirarlos.
6. Verifica que ninguna versión perdió el núcleo base ni usó una tipografía fuera del catálogo.
7. Sale con 1 si algo falla.

- [ ] **Step 1: Escribir y correr**

```bash
cp ~/Work/personal/instagod/data/gdlscene.db /tmp/h3.db
.venv/bin/python scripts/verificar_h3.py /tmp/h3.db
```

**Mira los cinco PNG.** El criterio no es que el script diga 🟢: es que las tres iteraciones se parezcan a lo que se pidió. Si "súbele el contraste" no cambió nada visible, el prompt necesita trabajo, y eso es un hallazgo del hito, no un fallo del script.

- [ ] **Step 2: Suite completa y lint**

```bash
.venv/bin/python -m pytest -p no:cacheprovider --junit-xml=/tmp/h3.xml
.venv/bin/python -m ruff check src/ tests/ api/ web/ config.py scripts/verificar_h3.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/verificar_h3.py
git commit -m "chore(h3): verificación end-to-end del diseñador"
```

---

## Definición de terminado para H3

- [ ] Suite con una sola falla, la de `test_segmentos_web`, y con más tests que al empezar.
- [ ] `ruff` limpio; `pnpm lint` y `pnpm build` limpios.
- [ ] Los tests de equivalencia siguen verdes: **las cuatro plantillas de gdlscene siguen dibujando byte a byte igual**.
- [ ] Se creó un diseño de inmobiliaria hablándole, se iteró tres veces y se volvió a la v2, con los cinco PNG revisados a ojo.
- [ ] Un diseño con tipografía inventada o filtro inventado se rechaza antes de guardarse.
- [ ] `DELETE` archiva y no borra.
- [ ] Un `editor` no puede diseñar; un `manager` sí.

## Lo que H3 deliberadamente NO hace

- No genera lotes de variantes de golpe. Decisión 5 del spec: chat con versiones, un diseño a la vez.
- No arma lotes ni toca `content_plans`. Eso es H4.
- No muestra estadísticas por plantilla. Eso es H5.
- No enciende `TEMPLATE_RENDER_SANDBOX`. Sigue apagado por decisión explícita; este es el hito donde el HTML del LLM aparece de verdad, así que es el momento de recordar que la deuda está viva.
- No implementa cuotas de generación por marca. Sigue siendo lo primero a agregar antes de dar de alta un cliente externo.
