# Motor de Slideshows v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Motor genérico de slideshows (cualquier tema/formato): brief → guion LLM → imágenes multi-fuente → N PNGs → aprobación Telegram → carrusel IG por el pipeline existente.

**Architecture:** Contrato de datos en dos capas (guion semántico del LLM + compilador determinista con presets de estilo → contrato `Slideshow` completo estilo reel.farm). Sourcing por providers enchufables (banco/covers/pexels/pinterest). Render con el motor Playwright existente (`compose.render_card`), encolado y publicación por `approval`/`publish.py` sin cambios.

**Tech Stack:** Python 3.14, SQLite (`src/db.py`), Jinja2+Playwright (`src/compose.py`), DeepSeek/Claude vía `config.LLM_PROVIDER`, Cloudinary (`src/host.py`), Telegram (`src/approval.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-08-09-motor-slideshows-design.md`

## Global Constraints

- Identidad git: `richyhoopd <theilluminatiduck@gmail.com>` — verificar `git config user.email` antes del primer commit. **NUNCA** agregar `Co-Authored-By: Claude` ni firmas de IA en commits.
- El LLM SIEMPRE debe devolver un **objeto** JSON (dict raíz) con `response_format={"type": "json_object"}` y `max_tokens` explícito — `re.search(r"\{.*\}")` con raíz-array devuelve `[]` en silencio (gotcha documentado de `parse_events`).
- Cloudinary sube SIEMPRE con `format="jpg"` (IG rechaza PNG, error 9004) — `host.upload` ya lo hace; no tocarlo.
- Ningún test hace llamadas reales a LLM/Pexels/Pinterest/Telegram/Cloudinary.
- Nada en este plan abre un poller de Telegram (`enviar_a_telegram` es HTTP directo); no tocar `bot.py` ni el daemon.
- Mensajes/docstrings en español, código estilo repo (módulos con núcleo puro + IO en los bordes).
- Correr `ruff check src tests` antes de cada commit (el repo se mantiene ruff-limpio).
- Correr los tests con `python -m pytest tests/<archivo> -v` desde la raíz del repo.
- Timezone: cualquier `datetime.now()` lleva `pytz.timezone(config.TIMEZONE)` (la máquina puede estar en otro huso).
- Antes de tocar `data/gdlscene.db` a mano (no aplica a migraciones idempotentes de `db.init_db`): `sqlite3 data/gdlscene.db "PRAGMA wal_checkpoint(TRUNCATE)"`.

---

### Task 1: Contrato de datos (`slideshow_model.py`)

**Files:**
- Create: `src/slideshow_model.py`
- Modify: `config.py` (agregar `SLIDESHOW_PALETA`, `SLIDESHOW_FUENTES` después del bloque `FORMATO_PESOS_COLDSTART`)
- Test: `tests/test_slideshow_model.py`

**Interfaces:**
- Consumes: `config.SLIDESHOW_PALETA`, `config.SLIDESHOW_FUENTES` (definidos aquí mismo).
- Produces (usado por Tasks 3, 7, 8):
  - `TextItem`, `Slide`, `Slideshow` (dataclasses, campos abajo)
  - `validar(s: Slideshow) -> list[str]` (lista de errores; `[]` = válido)
  - `a_json(s: Slideshow) -> str` / `desde_json(texto: str) -> Slideshow` (round-trip)
  - Constantes: `FONT_SIZES`, `TEXT_STYLES`, `IMAGE_LAYOUTS` (dict layout→`(cols, rows)`), `ASPECT_RATIOS` (dict aspect→`(w, h)`), `ALINEACIONES`, `ANCLAS_V`, `SOURCES`

- [ ] **Step 1: Agregar paleta y catálogo de fuentes a `config.py`**

Después del bloque `FORMATO_PESOS_COLDSTART` en `config.py`:

```python
# Motor de slideshows -------------------------------------------------------
# Paleta con nombre (contrato estilo reel.farm: text_color es un nombre, no un hex).
SLIDESHOW_PALETA = {
    "blanco": "#ffffff",
    "negro": "#111111",
    "verde": "#1b5e3f",
    "crema": "#f5efe0",
    "rojo": "#c0392b",
    "amarillo": "#f1c40f",
}
# Catálogo de fuentes disponibles → archivo en templates/assets/fonts/.
SLIDESHOW_FUENTES = {
    "Anton-Regular": "Anton-Regular.ttf",
    "Poppins-Bold": "Poppins-Bold.ttf",
    "Poppins-SemiBold": "Poppins-SemiBold.ttf",
    "Tinos-Bold": "Tinos-Bold.ttf",
    "Tinos-Regular": "Tinos-Regular.ttf",
}
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_slideshow_model.py`:

```python
"""Contrato de datos del motor de slideshows: validación y round-trip JSON."""
from __future__ import annotations

from src import slideshow_model as sm


def _slide_ok(**kw):
    base = dict(image_urls=["/tmp/foto.jpg"], image_layout="single",
                text_items=[sm.TextItem(text="Hola mundo")],
                is_cta=False, background_opacity=0.35, duration=3.0, source="manual")
    base.update(kw)
    return sm.Slide(**base)


def _show_ok(**kw):
    base = dict(title="Demo", aspect_ratio="4:5", slides=[_slide_ok()],
                caption="pie de foto", language="es", brief={}, formato="listicle",
                account_slug="gdlscene")
    base.update(kw)
    return sm.Slideshow(**base)


def test_show_valido_no_da_errores() -> None:
    assert sm.validar(_show_ok()) == []


def test_sin_slides_es_error() -> None:
    assert any("slides" in e for e in sm.validar(_show_ok(slides=[])))


def test_mas_de_20_slides_es_error() -> None:
    assert any("slides" in e for e in sm.validar(_show_ok(slides=[_slide_ok()] * 21)))


def test_aspect_invalido_es_error() -> None:
    assert sm.validar(_show_ok(aspect_ratio="3:2"))


def test_layout_invalido_es_error() -> None:
    assert sm.validar(_show_ok(slides=[_slide_ok(image_layout="5:5")]))


def test_mas_imagenes_que_celdas_del_layout_es_error() -> None:
    s = _slide_ok(image_layout="1:2", image_urls=["a.jpg", "b.jpg", "c.jpg"])
    assert sm.validar(_show_ok(slides=[s]))


def test_slide_sin_texto_es_error() -> None:
    assert sm.validar(_show_ok(slides=[_slide_ok(text_items=[])]))


def test_font_desconocida_es_error() -> None:
    item = sm.TextItem(text="x", font="ComicSans")
    assert sm.validar(_show_ok(slides=[_slide_ok(text_items=[item])]))


def test_color_fuera_de_paleta_es_error() -> None:
    item = sm.TextItem(text="x", text_color="fucsia")
    assert sm.validar(_show_ok(slides=[_slide_ok(text_items=[item])]))


def test_opacity_fuera_de_rango_es_error() -> None:
    assert sm.validar(_show_ok(slides=[_slide_ok(background_opacity=1.5)]))


def test_slide_sin_imagen_es_valido() -> None:
    """Fallback de fondo sólido: image_urls=[] NO es error."""
    assert sm.validar(_show_ok(slides=[_slide_ok(image_urls=[])])) == []


def test_round_trip_json() -> None:
    s = _show_ok()
    otra = sm.desde_json(sm.a_json(s))
    assert otra == s
    assert isinstance(otra.slides[0].text_items[0], sm.TextItem)
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `python -m pytest tests/test_slideshow_model.py -v`
Expected: FAIL / ERROR con `ModuleNotFoundError: No module named 'src.slideshow_model'`

- [ ] **Step 4: Implementar `src/slideshow_model.py`**

```python
"""Contrato de datos del motor de slideshows (clon en forma de reel.farm).

Dos capas (ver spec 2026-08-09): el LLM emite un guion semántico simple; el
compilador (slideshow_compile) lo convierte en ESTE contrato completo, que es
lo que se almacena (content_queue.slideshow_json), se rinde y —a mediano
plazo— se expone como API de producto. Claves en inglés a propósito.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import config

FONT_SIZES = ("extra_extra_small", "extra_small", "small", "medium", "large",
              "extra_large")
TEXT_STYLES = ("text", "outline", "background")
# layout → (columnas, filas) de la grilla de imágenes.
IMAGE_LAYOUTS = {"single": (1, 1), "1:2": (1, 2), "1:3": (1, 3),
                 "2:1": (2, 1), "2:2": (2, 2)}
# aspect → (ancho, alto) en px de render.
ASPECT_RATIOS = {"4:5": (1080, 1350), "9:16": (1080, 1920),
                 "1:1": (1080, 1080), "16:9": (1920, 1080)}
ALINEACIONES = ("left", "center", "right")
ANCLAS_V = ("top", "center", "bottom")
# Proveniencia de la imagen (auditoría/bajadas de copyright, ver spec).
SOURCES = ("banco", "covers", "pexels", "pinterest", "manual")


@dataclass
class TextItem:
    text: str
    font_size: str = "large"
    text_color: str = "blanco"
    text_style: str = "background"
    font: str = "Poppins-Bold"
    text_width: float = 0.86          # fracción del ancho de la tarjeta
    text_align: str = "center"
    text_anchor: str = "center"       # horizontal
    text_vertical_anchor: str = "center"


@dataclass
class Slide:
    image_urls: list[str] = field(default_factory=list)  # [] = fondo sólido
    image_layout: str = "single"
    text_items: list[TextItem] = field(default_factory=list)
    is_cta: bool = False
    background_opacity: float = 0.35  # overlay oscuro sobre la(s) imagen(es)
    duration: float = 3.0             # segundos (futuro export a video)
    source: str = "manual"


@dataclass
class Slideshow:
    title: str
    aspect_ratio: str = "4:5"
    slides: list[Slide] = field(default_factory=list)
    caption: str = ""
    language: str = "es"
    brief: dict = field(default_factory=dict)
    formato: str = ""
    account_slug: str = "gdlscene"


def validar(s: Slideshow) -> list[str]:
    """Lista de errores humanos; [] = contrato válido."""
    errores: list[str] = []
    if not 1 <= len(s.slides) <= 20:
        errores.append(f"slides: deben ser 1-20, hay {len(s.slides)}")
    if s.aspect_ratio not in ASPECT_RATIOS:
        errores.append(f"aspect_ratio desconocido: {s.aspect_ratio!r}")
    for i, sl in enumerate(s.slides):
        pre = f"slide {i}"
        if sl.image_layout not in IMAGE_LAYOUTS:
            errores.append(f"{pre}: image_layout desconocido {sl.image_layout!r}")
        else:
            cols, rows = IMAGE_LAYOUTS[sl.image_layout]
            if len(sl.image_urls) > cols * rows:
                errores.append(f"{pre}: {len(sl.image_urls)} imágenes no caben "
                               f"en layout {sl.image_layout}")
        if not 0.0 <= sl.background_opacity <= 1.0:
            errores.append(f"{pre}: background_opacity fuera de [0,1]")
        if sl.source not in SOURCES:
            errores.append(f"{pre}: source desconocido {sl.source!r}")
        if not sl.text_items:
            errores.append(f"{pre}: sin text_items")
        for j, t in enumerate(sl.text_items):
            pj = f"{pre} texto {j}"
            if not (t.text or "").strip():
                errores.append(f"{pj}: texto vacío")
            if t.font_size not in FONT_SIZES:
                errores.append(f"{pj}: font_size desconocido {t.font_size!r}")
            if t.text_style not in TEXT_STYLES:
                errores.append(f"{pj}: text_style desconocido {t.text_style!r}")
            if t.text_color not in config.SLIDESHOW_PALETA:
                errores.append(f"{pj}: color fuera de paleta {t.text_color!r}")
            if t.font not in config.SLIDESHOW_FUENTES:
                errores.append(f"{pj}: fuente fuera de catálogo {t.font!r}")
            if not 0.2 <= t.text_width <= 1.0:
                errores.append(f"{pj}: text_width fuera de [0.2,1]")
            if t.text_align not in ALINEACIONES:
                errores.append(f"{pj}: text_align desconocido {t.text_align!r}")
            if t.text_anchor not in ALINEACIONES:
                errores.append(f"{pj}: text_anchor desconocido {t.text_anchor!r}")
            if t.text_vertical_anchor not in ANCLAS_V:
                errores.append(f"{pj}: text_vertical_anchor desconocido "
                               f"{t.text_vertical_anchor!r}")
    return errores


def a_json(s: Slideshow) -> str:
    return json.dumps(asdict(s), ensure_ascii=False)


def desde_json(texto: str) -> Slideshow:
    data = json.loads(texto)
    slides = []
    for sl in data.pop("slides", []):
        items = [TextItem(**t) for t in sl.pop("text_items", [])]
        slides.append(Slide(text_items=items, **sl))
    return Slideshow(slides=slides, **data)
```

- [ ] **Step 5: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_slideshow_model.py -v && ruff check src/slideshow_model.py tests/test_slideshow_model.py config.py`
Expected: 13 PASS, ruff sin quejas

- [ ] **Step 6: Commit**

```bash
git add src/slideshow_model.py tests/test_slideshow_model.py config.py
git commit -m "feat(slideshows): contrato de datos Slideshow/Slide/TextItem + paleta y fuentes"
```

---

### Task 2: Guion semántico del LLM (`slideshow_script.py`)

**Files:**
- Create: `src/slideshow_script.py`
- Modify: `config.py` (agregar `SLIDESHOW_TEMPERATURE` y `SLIDESHOW_FORMATOS` junto al bloque de Task 1)
- Test: `tests/test_slideshow_script.py`

**Interfaces:**
- Consumes: `config.LLM_PROVIDER`, `config.DEEPSEEK_*`, `config.ANTHROPIC_*` (patrón de `caption.py`).
- Produces (usado por Task 8):
  - `generar_guion(tema: str, *, formato: str = "listicle", n_slides: int = 6, contexto: str | None = None, rechazados: list[str] | None = None, feedback: str | None = None) -> dict` — devuelve el guion validado; `RuntimeError` tras 3 intentos fallidos.
  - `extraer_guion(texto: str) -> dict | None` (puro)
  - `validar_guion(data: dict, *, n_slides: int) -> list[str]` (puro)
- Forma del guion (consumida por `slideshow_compile.compilar` en Task 3):

```json
{"tema": "...", "hook": "...", "caption": "...", "cta": "...",
 "slides": [{"text": "...", "rol": "hook|punto|cta", "image_hint": "búsqueda 2-5 palabras"}]}
```

- [ ] **Step 1: Agregar formatos y temperatura a `config.py`**

Debajo de `SLIDESHOW_FUENTES`:

```python
# Temperatura del guion de slides (más bajo que memes: estructura > locura).
SLIDESHOW_TEMPERATURE = float(_get("SLIDESHOW_TEMPERATURE", "1.0") or "1.0")
# Formatos editoriales del motor (presets de instrucciones; el motor es genérico).
SLIDESHOW_FORMATOS = {
    "listicle": (
        "LISTICLE: el hook promete N cosas ('5 señales de que…', '7 formas de…'). "
        "Cada slide intermedio es UNA idea numerada (1., 2., …), corta y rematada."
    ),
    "todo_lo_que_sabemos": (
        "TODO LO QUE SABEMOS: hook = 'Todo lo que sabemos de {tema}' (o variante). "
        "Cada slide intermedio es un 'dato' deadpan estilo nota seria; mezcla datos "
        "reales del contexto con absurdos evidentes si el tono lo pide."
    ),
    "perfil": (
        "PERFIL: el hook presenta al sujeto ('Conoce a X'). Cada slide intermedio "
        "revela un dato de su vida/carrera tratado con gravedad periodística."
    ),
    "libre": (
        "LIBRE: hook fuerte, UNA sola idea por slide, remate claro al final."
    ),
}
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_slideshow_script.py`:

```python
"""Guion semántico del LLM: extracción, validación y loop de reintentos."""
from __future__ import annotations

import json

import pytest

from src import slideshow_script as ss


def _guion_ok(n=3):
    slides = [{"text": "Gancho", "rol": "hook", "image_hint": "city night"}]
    for i in range(n - 2):
        slides.append({"text": f"Punto {i}", "rol": "punto", "image_hint": "coffee"})
    slides.append({"text": "Sígueme", "rol": "cta", "image_hint": "neon sign"})
    return {"tema": "café", "hook": "Gancho", "caption": "pie", "cta": "Sígueme",
            "slides": slides}


def test_extraer_guion_tolera_fences() -> None:
    texto = "```json\n" + json.dumps(_guion_ok()) + "\n```"
    assert ss.extraer_guion(texto) == _guion_ok()


def test_extraer_guion_rechaza_array_raiz() -> None:
    assert ss.extraer_guion(json.dumps([1, 2])) is None


def test_extraer_guion_rechaza_no_json() -> None:
    assert ss.extraer_guion("no hay json aquí") is None


def test_validar_guion_ok() -> None:
    assert ss.validar_guion(_guion_ok(), n_slides=3) == []


def test_validar_guion_sin_claves() -> None:
    assert ss.validar_guion({"tema": "x"}, n_slides=3)


def test_validar_guion_primer_slide_debe_ser_hook() -> None:
    g = _guion_ok()
    g["slides"][0]["rol"] = "punto"
    assert any("hook" in e for e in ss.validar_guion(g, n_slides=3))


def test_validar_guion_ultimo_slide_debe_ser_cta() -> None:
    g = _guion_ok()
    g["slides"][-1]["rol"] = "punto"
    assert any("cta" in e for e in ss.validar_guion(g, n_slides=3))


def test_validar_guion_rol_desconocido() -> None:
    g = _guion_ok()
    g["slides"][1]["rol"] = "outro"
    assert ss.validar_guion(g, n_slides=3)


def test_validar_guion_slide_sin_image_hint() -> None:
    g = _guion_ok()
    g["slides"][1]["image_hint"] = ""
    assert ss.validar_guion(g, n_slides=3)


def test_generar_guion_reintenta_y_devuelve(monkeypatch) -> None:
    """1er intento: basura; 2o: guion válido → lo devuelve sin agotar intentos."""
    respuestas = iter(["esto no es json", json.dumps(_guion_ok())])
    monkeypatch.setattr(ss, "_llamar_llm", lambda prompt: next(respuestas))
    g = ss.generar_guion("café", formato="listicle", n_slides=3)
    assert g["hook"] == "Gancho"


def test_generar_guion_agota_intentos(monkeypatch) -> None:
    monkeypatch.setattr(ss, "_llamar_llm", lambda prompt: "nunca es json")
    with pytest.raises(RuntimeError):
        ss.generar_guion("café", n_slides=3)


def test_generar_guion_formato_desconocido() -> None:
    with pytest.raises(ValueError):
        ss.generar_guion("café", formato="inexistente")
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `python -m pytest tests/test_slideshow_script.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.slideshow_script'`

- [ ] **Step 4: Implementar `src/slideshow_script.py`**

```python
"""Guion semántico de slideshows: el LLM emite estructura simple, sin estilos.

Clona el patrón de caption.py (proveedor agnóstico DeepSeek/Claude) pero pide
JSON ESTRICTO con objeto raíz dict (gotcha de parse_events: un array raíz se
pierde en silencio). El compilador (slideshow_compile) convierte este guion en
el contrato Slideshow completo.
"""
from __future__ import annotations

import json
import re
from typing import Any

import config

ROLES = ("hook", "punto", "cta")

SYSTEM_PROMPT = """\
Eres guionista de slideshows para redes sociales (carruseles de imágenes con \
texto grande encima, estilo TikTok/Instagram). Escribes guiones CORTOS y con \
gancho sobre CUALQUIER tema que te pidan: productos, nichos, humor, divulgación.

Devuelve ÚNICAMENTE un objeto JSON válido con este esquema EXACTO:
{"tema": str, "hook": str, "caption": str, "cta": str,
 "slides": [{"text": str, "rol": "hook"|"punto"|"cta", "image_hint": str}]}

Reglas:
- El PRIMER slide tiene rol "hook": el gancho, máximo 12 palabras, que obligue \
a pasar al siguiente slide.
- Los slides intermedios tienen rol "punto": UNA sola idea por slide, máximo \
20 palabras, rematada (nada de frases que continúan en el siguiente).
- El ÚLTIMO slide tiene rol "cta": llamada a la acción corta (seguir, comentar, \
guardar).
- "image_hint": búsqueda de imagen de fondo en 2-5 palabras EN INGLÉS \
(los bancos de imagen responden mejor en inglés). Concreta y visual: \
"vintage guitar closeup", no "music concept".
- "caption": pie del post, 1-2 frases + una pregunta que invite a comentar.
- Español de México, sin emojis en los slides (en el caption sí se permiten).
- El texto de cada slide debe funcionar SOLO, en pantalla, en letra grande."""


def extraer_guion(texto: str) -> dict[str, Any] | None:
    """Primer objeto JSON en la respuesta (tolera ```json ...```). PURO."""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def validar_guion(data: dict[str, Any], *, n_slides: int) -> list[str]:
    """Errores del guion contra el esquema; [] = válido. PURO."""
    errores: list[str] = []
    for clave in ("tema", "hook", "caption", "cta", "slides"):
        if clave not in data:
            errores.append(f"falta la clave {clave!r}")
    slides = data.get("slides") or []
    if not isinstance(slides, list) or not 1 <= len(slides) <= 20:
        errores.append(f"slides: deben ser 1-20, hay {len(slides)}")
        return errores
    for i, sl in enumerate(slides):
        if not isinstance(sl, dict):
            errores.append(f"slide {i}: no es objeto")
            continue
        if not (sl.get("text") or "").strip():
            errores.append(f"slide {i}: text vacío")
        if sl.get("rol") not in ROLES:
            errores.append(f"slide {i}: rol desconocido {sl.get('rol')!r}")
        if not (sl.get("image_hint") or "").strip():
            errores.append(f"slide {i}: image_hint vacío")
    if slides and slides[0].get("rol") != "hook":
        errores.append("el primer slide debe tener rol 'hook'")
    if len(slides) >= 2 and slides[-1].get("rol") != "cta":
        errores.append("el último slide debe tener rol 'cta'")
    return errores


def _build_user_prompt(tema: str, formato: str, n_slides: int,
                       contexto: str | None, rechazados: list[str] | None,
                       feedback: str | None, errores_previos: list[str]) -> str:
    partes = [
        f"TEMA: {tema}",
        f"FORMATO: {config.SLIDESHOW_FORMATOS[formato]}",
        f"NÚMERO DE SLIDES: exactamente {n_slides} (incluyendo hook y cta).",
    ]
    if contexto:
        partes.append(f"CONTEXTO/VOZ (síguelo): {contexto}")
    if rechazados:
        partes.append("Hooks ya RECHAZADOS (no los repitas ni te parezcas):\n"
                      + "\n".join(f"- {r}" for r in rechazados))
    if feedback:
        partes.append(f"RETROALIMENTACIÓN del editor (al pie de la letra): {feedback}")
    if errores_previos:
        partes.append("Tu respuesta anterior tuvo estos errores, corrígelos:\n"
                      + "\n".join(f"- {e}" for e in errores_previos))
    partes.append("Devuelve SOLO el objeto JSON.")
    return "\n\n".join(partes)


def _llamar_llm(user_prompt: str) -> str:
    """IO: una llamada al proveedor configurado. Monkeypatch-eable en tests."""
    if config.LLM_PROVIDER == "claude":
        return _via_anthropic(user_prompt)
    return _via_deepseek(user_prompt)


def _via_deepseek(user_prompt: str) -> str:
    from openai import OpenAI

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en el .env")
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": user_prompt}],
        temperature=config.SLIDESHOW_TEMPERATURE,
        max_tokens=2000,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


def _via_anthropic(user_prompt: str) -> str:
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en el .env (LLM_PROVIDER=claude)")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2000,
        temperature=min(config.SLIDESHOW_TEMPERATURE, 1.0),
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(b.text for b in resp.content if b.type == "text")


def generar_guion(tema: str, *, formato: str = "listicle", n_slides: int = 6,
                  contexto: str | None = None,
                  rechazados: list[str] | None = None,
                  feedback: str | None = None) -> dict[str, Any]:
    """Guion validado, o RuntimeError tras 3 intentos.

    En cada reintento se anexan los errores de validación al prompt para que
    el LLM se corrija (patrón del spec).
    """
    if formato not in config.SLIDESHOW_FORMATOS:
        raise ValueError(f"Formato desconocido: {formato!r}. "
                         f"Opciones: {list(config.SLIDESHOW_FORMATOS)}")
    errores: list[str] = []
    for _ in range(3):
        prompt = _build_user_prompt(tema, formato, n_slides, contexto,
                                    rechazados, feedback, errores)
        crudo = _llamar_llm(prompt)
        data = extraer_guion(crudo)
        if data is None:
            errores = ["la respuesta no contenía un objeto JSON válido"]
            continue
        errores = validar_guion(data, n_slides=n_slides)
        if not errores:
            return data
    raise RuntimeError(f"El LLM no produjo un guion válido en 3 intentos: {errores}")


if __name__ == "__main__":
    # Prueba aislada real: python -m src.slideshow_script
    print(json.dumps(generar_guion("cafeterías de especialidad en Guadalajara",
                                   n_slides=5), ensure_ascii=False, indent=2))
```

- [ ] **Step 5: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_slideshow_script.py -v && ruff check src/slideshow_script.py tests/test_slideshow_script.py config.py`
Expected: 12 PASS, ruff limpio

- [ ] **Step 6: Commit**

```bash
git add src/slideshow_script.py tests/test_slideshow_script.py config.py
git commit -m "feat(slideshows): guion semantico del LLM con validacion y reintentos"
```

---

### Task 3: Compilador guion→contrato (`slideshow_compile.py`)

**Files:**
- Create: `src/slideshow_compile.py`
- Modify: `config.py` (agregar `SLIDESHOW_ESTILOS` debajo de `SLIDESHOW_FORMATOS`)
- Test: `tests/test_slideshow_compile.py`

**Interfaces:**
- Consumes: `slideshow_model` (Task 1); guion dict (forma de Task 2); `ImagenCandidata` — para no depender de Task 4, el compilador acepta cualquier objeto con atributos `.ruta_o_url: str` y `.source: str`, o `None`.
- Produces (usado por Tasks 7 y 8):
  - `compilar(guion: dict, *, estilo: str, imagenes: list, aspect_ratio: str = "4:5", brief: dict | None = None, formato: str = "", account_slug: str = "gdlscene") -> Slideshow` — `imagenes[i]` corresponde a `guion["slides"][i]`; `None` → slide de fondo sólido.
  - `contexto_slide(s: Slideshow, idx: int) -> dict` — ctx listo para `compose.render_card("slide.html", ctx)`. Claves: `width`, `height`, `bg_color`, `image_srcs` (lista de URIs), `grid_cols`, `grid_rows`, `overlay_opacity`, `font_faces` (lista de `{"name", "url"}`), `items` (lista de `{"text", "font", "px", "color", "caja", "estilo", "width_pct", "align", "anchor", "v_anchor"}`).

- [ ] **Step 1: Agregar presets de estilo a `config.py`**

Debajo de `SLIDESHOW_FORMATOS`:

```python
# Presets de estilo del compilador: cosmética por ROL del slide. El LLM nunca
# decide estilos; re-estilar = recompilar el mismo guion con otro preset.
SLIDESHOW_ESTILOS = {
    "tiktok_bold": {
        "texto": "blanco", "fondo": "negro", "background_opacity": 0.35,
        "roles": {
            "hook": {"font": "Anton-Regular", "font_size": "extra_large",
                     "text_style": "background", "text_vertical_anchor": "center"},
            "punto": {"font": "Poppins-Bold", "font_size": "large",
                      "text_style": "background", "text_vertical_anchor": "center"},
            "cta": {"font": "Poppins-Bold", "font_size": "medium",
                    "text_style": "background", "text_vertical_anchor": "bottom"},
        },
    },
    "editorial": {
        "texto": "negro", "fondo": "crema", "background_opacity": 0.2,
        "roles": {
            "hook": {"font": "Tinos-Bold", "font_size": "extra_large",
                     "text_style": "background", "text_vertical_anchor": "top"},
            "punto": {"font": "Tinos-Bold", "font_size": "large",
                      "text_style": "background", "text_vertical_anchor": "center"},
            "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                    "text_style": "background", "text_vertical_anchor": "bottom"},
        },
    },
}
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_slideshow_compile.py`:

```python
"""Compilador determinista: guion + preset de estilo → contrato Slideshow."""
from __future__ import annotations

from dataclasses import dataclass

import config
from src import slideshow_compile as sc
from src import slideshow_model as sm


@dataclass
class _Img:
    ruta_o_url: str
    source: str = "pexels"


def _guion(n=3):
    slides = [{"text": "Gancho", "rol": "hook", "image_hint": "a"},
              {"text": "Punto uno", "rol": "punto", "image_hint": "b"},
              {"text": "Sígueme", "rol": "cta", "image_hint": "c"}][:n]
    return {"tema": "café", "hook": "Gancho", "caption": "pie", "cta": "Sígueme",
            "slides": slides}


def test_compilar_produce_contrato_valido() -> None:
    imgs = [_Img("/tmp/a.jpg"), _Img("/tmp/b.jpg"), _Img("/tmp/c.jpg")]
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=imgs)
    assert sm.validar(s) == []
    assert len(s.slides) == 3


def test_compilar_aplica_preset_por_rol() -> None:
    imgs = [_Img("/tmp/a.jpg")] * 3
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=imgs)
    preset = config.SLIDESHOW_ESTILOS["tiktok_bold"]
    assert s.slides[0].text_items[0].font == preset["roles"]["hook"]["font"]
    assert s.slides[1].text_items[0].font == preset["roles"]["punto"]["font"]
    assert s.slides[2].is_cta is True


def test_compilar_imagen_none_da_fondo_solido() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold",
                    imagenes=[_Img("/tmp/a.jpg"), None, _Img("/tmp/c.jpg")])
    assert s.slides[1].image_urls == []
    assert s.slides[1].background_opacity == 0.0
    assert sm.validar(s) == []


def test_compilar_registra_source_de_la_imagen() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold",
                    imagenes=[_Img("/tmp/a.jpg", source="banco")] * 3)
    assert s.slides[0].source == "banco"


def test_compilar_estilo_desconocido() -> None:
    import pytest
    with pytest.raises(KeyError):
        sc.compilar(_guion(), estilo="noexiste", imagenes=[None] * 3)


def test_mismo_guion_dos_estilos_distintos() -> None:
    imgs = [_Img("/tmp/a.jpg")] * 3
    a = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=imgs)
    b = sc.compilar(_guion(), estilo="editorial", imagenes=imgs)
    assert a.slides[0].text_items[0].font != b.slides[0].text_items[0].font
    assert a.slides[0].text_items[0].text == b.slides[0].text_items[0].text


def test_contexto_slide_tiene_llaves_para_la_plantilla() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold",
                    imagenes=[_Img("/tmp/a.jpg")] * 3, aspect_ratio="4:5")
    ctx = sc.contexto_slide(s, 0)
    assert ctx["width"] == 1080 and ctx["height"] == 1350
    assert ctx["grid_cols"] == 1 and ctx["grid_rows"] == 1
    assert ctx["image_srcs"][0].startswith("file://")
    assert ctx["items"][0]["px"] > 0
    assert ctx["items"][0]["color"].startswith("#")
    assert ctx["font_faces"][0]["url"].startswith("file://")


def test_contexto_slide_fondo_solido_sin_overlay() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    ctx = sc.contexto_slide(s, 0)
    assert ctx["image_srcs"] == []
    assert ctx["overlay_opacity"] == 0.0
    assert ctx["bg_color"] == config.SLIDESHOW_PALETA["negro"]
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `python -m pytest tests/test_slideshow_compile.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.slideshow_compile'`

- [ ] **Step 4: Implementar `src/slideshow_compile.py`**

```python
"""Compilador determinista: guion semántico + preset de estilo → Slideshow.

La cosmética (fuentes, colores, tamaños, anchors) vive en
config.SLIDESHOW_ESTILOS; re-estilar un set = recompilar el MISMO guion con
otro preset, sin volver a llamar al LLM.
"""
from __future__ import annotations

from typing import Any

import config
from src.compose import FONTS_DIR, _to_src
from src.slideshow_model import (ASPECT_RATIOS, IMAGE_LAYOUTS, Slide,
                                 Slideshow, TextItem)

# Tamaño con nombre → px sobre diseño de 1080 de ancho (se escala por aspect).
_FONT_PX = {"extra_extra_small": 36, "extra_small": 48, "small": 60,
            "medium": 76, "large": 96, "extra_large": 128}

# Color de la caja detrás del texto (text_style=background) según el color
# del texto: texto claro → caja oscura y viceversa.
_COLORES_CLAROS = {"blanco", "crema", "amarillo"}


def _caja_para(color_nombre: str) -> str:
    if color_nombre in _COLORES_CLAROS:
        return config.SLIDESHOW_PALETA["negro"]
    return config.SLIDESHOW_PALETA["blanco"]


def compilar(guion: dict[str, Any], *, estilo: str, imagenes: list,
             aspect_ratio: str = "4:5", brief: dict | None = None,
             formato: str = "", account_slug: str = "gdlscene") -> Slideshow:
    """guion + estilo + una imagen (o None) por slide → contrato completo.

    imagenes[i] corresponde a guion["slides"][i]; acepta cualquier objeto con
    .ruta_o_url y .source (ImagenCandidata de image_sources), o None →
    slide de fondo sólido sin overlay.
    """
    preset = config.SLIDESHOW_ESTILOS[estilo]  # KeyError si no existe: a propósito
    slides: list[Slide] = []
    for sl, img in zip(guion["slides"], imagenes):
        rol = sl.get("rol", "punto")
        r = preset["roles"].get(rol, preset["roles"]["punto"])
        item = TextItem(text=sl["text"], font=r["font"], font_size=r["font_size"],
                        text_color=preset["texto"], text_style=r["text_style"],
                        text_vertical_anchor=r["text_vertical_anchor"])
        slides.append(Slide(
            image_urls=[img.ruta_o_url] if img else [],
            image_layout="single",
            text_items=[item],
            is_cta=(rol == "cta"),
            background_opacity=preset["background_opacity"] if img else 0.0,
            source=img.source if img else "manual",
        ))
    return Slideshow(title=guion["hook"], aspect_ratio=aspect_ratio,
                     slides=slides, caption=guion.get("caption", ""),
                     brief=brief or {}, formato=formato,
                     account_slug=account_slug)


def contexto_slide(s: Slideshow, idx: int) -> dict[str, Any]:
    """Contexto Jinja2 de UN slide para templates/slide.html. PURO."""
    sl = s.slides[idx]
    width, height = ASPECT_RATIOS[s.aspect_ratio]
    cols, rows = IMAGE_LAYOUTS[sl.image_layout]
    escala = width / 1080
    items = []
    for t in sl.text_items:
        items.append({
            "text": t.text,
            "font": t.font,
            "px": round(_FONT_PX[t.font_size] * escala),
            "color": config.SLIDESHOW_PALETA[t.text_color],
            "caja": _caja_para(t.text_color),
            "estilo": t.text_style,
            "width_pct": round(t.text_width * 100),
            "align": t.text_align,
            "anchor": t.text_anchor,
            "v_anchor": t.text_vertical_anchor,
        })
    return {
        "width": width,
        "height": height,
        "bg_color": config.SLIDESHOW_PALETA["negro"],
        "image_srcs": [_to_src(u) for u in sl.image_urls],
        "grid_cols": cols,
        "grid_rows": rows,
        "overlay_opacity": sl.background_opacity,
        "font_faces": [{"name": nombre, "url": (FONTS_DIR / archivo).as_uri()}
                       for nombre, archivo in config.SLIDESHOW_FUENTES.items()],
        "items": items,
    }
```

- [ ] **Step 5: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_slideshow_compile.py tests/test_slideshow_model.py -v && ruff check src/slideshow_compile.py tests/test_slideshow_compile.py config.py`
Expected: PASS todo, ruff limpio

- [ ] **Step 6: Commit**

```bash
git add src/slideshow_compile.py tests/test_slideshow_compile.py config.py
git commit -m "feat(slideshows): compilador guion+estilo -> contrato, presets tiktok_bold/editorial"
```

---

### Task 4: Sourcing núcleo + providers locales (`image_sources.py`)

**Files:**
- Create: `src/image_sources.py`
- Test: `tests/test_image_sources.py`

**Interfaces:**
- Consumes: `src.db` (fotos/bandas/events), `covers.asegurar_cover(url) -> Path | None`.
- Produces (usado por Tasks 5, 6, 8):
  - `@dataclass ImagenCandidata: ruta_o_url: str; source: str; credito: str | None = None`
  - `resolver(hints: list[str], fuentes: list[str], *, cx=None, providers: dict | None = None) -> list[ImagenCandidata | None]` — una candidata (o None) por hint, en orden; nunca repite la misma imagen dentro del set.
  - `providers_default(cx=None) -> dict[str, Any]` — `{"banco": ..., "covers": ..., "pexels": ..., "pinterest": ...}` (pexels/pinterest se agregan en Tasks 5-6; aquí el dict solo trae banco y covers).
  - `_descargar_cache(url: str) -> Path | None` — cache en `data/sourcing/<sha1[:16]>.jpg`, escritura atómica, valida bytes mágicos (usada por Tasks 5-6).
- Contrato de provider: objeto con atributo `nombre: str` y método `buscar(hint: str, n: int = 3) -> list[ImagenCandidata]`. Un provider que falla devuelve `[]`, nunca propaga la excepción a `resolver`.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_image_sources.py`:

```python
"""Sourcing multi-fuente: cascada de providers, dedup y providers locales."""
from __future__ import annotations

from src import db
from src import image_sources as isrc


class _Fake:
    def __init__(self, nombre, resultados):
        self.nombre = nombre
        self.resultados = resultados  # hint → list[ImagenCandidata]
        self.llamadas = []

    def buscar(self, hint, n=3):
        self.llamadas.append(hint)
        return self.resultados.get(hint, [])


def _cand(ruta, source="pexels"):
    return isrc.ImagenCandidata(ruta_o_url=ruta, source=source)


def test_resolver_usa_primer_provider_con_resultado() -> None:
    p1 = _Fake("banco", {})
    p2 = _Fake("pexels", {"cafe": [_cand("/tmp/a.jpg")]})
    out = isrc.resolver(["cafe"], ["banco", "pexels"],
                        providers={"banco": p1, "pexels": p2})
    assert out[0].ruta_o_url == "/tmp/a.jpg"
    assert p1.llamadas == ["cafe"]  # se intentó primero


def test_resolver_none_si_nadie_tiene() -> None:
    out = isrc.resolver(["x"], ["pexels"], providers={"pexels": _Fake("pexels", {})})
    assert out == [None]


def test_resolver_no_repite_imagen_en_el_set() -> None:
    p = _Fake("pexels", {"a": [_cand("/tmp/1.jpg"), _cand("/tmp/2.jpg")],
                         "b": [_cand("/tmp/1.jpg"), _cand("/tmp/3.jpg")]})
    out = isrc.resolver(["a", "b"], ["pexels"], providers={"pexels": p})
    assert out[0].ruta_o_url == "/tmp/1.jpg"
    assert out[1].ruta_o_url == "/tmp/3.jpg"  # la 1 ya estaba usada


def test_resolver_fuente_desconocida_se_ignora() -> None:
    p = _Fake("pexels", {"a": [_cand("/tmp/1.jpg")]})
    out = isrc.resolver(["a"], ["noexiste", "pexels"], providers={"pexels": p})
    assert out[0].ruta_o_url == "/tmp/1.jpg"


def test_provider_que_lanza_no_tumba_resolver() -> None:
    class _Roto:
        nombre = "roto"

        def buscar(self, hint, n=3):
            raise RuntimeError("boom")

    p = _Fake("pexels", {"a": [_cand("/tmp/1.jpg")]})
    out = isrc.resolver(["a"], ["roto", "pexels"],
                        providers={"roto": _Roto(), "pexels": p})
    assert out[0].ruta_o_url == "/tmp/1.jpg"


def _db_con_fotos(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial",
                    activa=1)
    db.insert(cx, "photos", band_id=bid, path="/tmp/kabala1.jpg",
              source_post_id="p1", usable_meme=1, usada=0, descartada=0,
              nitidez=90.0)
    db.insert(cx, "photos", band_id=bid, path="/tmp/kabala2.jpg",
              source_post_id="p2", usable_meme=1, usada=1, descartada=0,
              nitidez=99.0)  # usada: no debe salir
    return cx, bid


def test_banco_provider_matchea_por_nombre(tmp_path) -> None:
    cx, _ = _db_con_fotos(tmp_path)
    out = isrc.BancoProvider(cx).buscar("kabala")
    assert [c.ruta_o_url for c in out] == ["/tmp/kabala1.jpg"]
    assert out[0].source == "banco"


def test_banco_provider_sin_match(tmp_path) -> None:
    cx, _ = _db_con_fotos(tmp_path)
    assert isrc.BancoProvider(cx).buscar("mountain sunset") == []


def test_covers_provider_matchea_titulo(tmp_path, monkeypatch) -> None:
    cx, bid = _db_con_fotos(tmp_path)
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-08-01",
              titulo="Disco Lunar (álbum)", cover_url="https://cdn/x.jpg")
    monkeypatch.setattr(isrc.covers, "asegurar_cover",
                        lambda url, **kw: tmp_path / "cover.jpg")
    out = isrc.CoversProvider(cx).buscar("lunar")
    assert out and out[0].source == "covers"


def test_descargar_cache_valida_magia(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200
        content = b"\xff\xd8\xff" + b"x" * 100  # JPEG mágico

        def raise_for_status(self):
            pass

    monkeypatch.setattr(isrc.requests, "get", lambda *a, **kw: _Resp())
    p = isrc._descargar_cache("https://img/x.jpg")
    assert p is not None and p.exists()
    # segunda llamada: cache hit, sin red
    monkeypatch.setattr(isrc.requests, "get",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("red")))
    assert isrc._descargar_cache("https://img/x.jpg") == p


def test_descargar_cache_rechaza_no_imagen(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200
        content = b"<html>not found</html>"

        def raise_for_status(self):
            pass

    monkeypatch.setattr(isrc.requests, "get", lambda *a, **kw: _Resp())
    assert isrc._descargar_cache("https://img/y.jpg") is None
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_image_sources.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.image_sources'`

- [ ] **Step 3: Implementar `src/image_sources.py`**

```python
"""Sourcing de imágenes multi-fuente para slideshows.

Protocolo: un provider tiene .nombre y .buscar(hint, n) -> [ImagenCandidata].
resolver() recorre las fuentes en el orden del brief con fallback en cascada
y nunca repite la misma imagen dentro de un set. Un provider que falla
devuelve [] (o su excepción se traga aquí): el set nunca truena por sourcing.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

import requests

import config
from src import covers, db

SOURCING_DIR = config.BASE_DIR / "data" / "sourcing"

# Bytes mágicos aceptados (JPEG, PNG, WEBP/RIFF).
_MAGIA = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF")


@dataclass
class ImagenCandidata:
    ruta_o_url: str            # path local o URL https
    source: str                # "banco"|"covers"|"pexels"|"pinterest"|"manual"
    credito: str | None = None


def _descargar_cache(url: str) -> Path | None:
    """Descarga con cache en data/sourcing/<sha1[:16]>.jpg. None si falla."""
    SOURCING_DIR.mkdir(parents=True, exist_ok=True)
    destino = SOURCING_DIR / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
    if destino.exists():
        return destino
    try:
        r = requests.get(url, timeout=20,
                         headers={"User-Agent": "Mozilla/5.0 (Macintosh)"})
        r.raise_for_status()
    except requests.RequestException:
        return None
    data = r.content
    if not data or not data.startswith(_MAGIA):
        return None
    fd, tmp = tempfile.mkstemp(dir=str(SOURCING_DIR), suffix=".part")
    os.close(fd)  # solo queremos el nombre único
    Path(tmp).write_bytes(data)
    Path(tmp).rename(destino)  # escritura atómica
    return destino


class BancoProvider:
    """Fotos reales del banco propio: match del hint contra nombre/handle."""

    nombre = "banco"

    def __init__(self, cx):
        self.cx = cx

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        like = f"%{hint.strip()}%"
        filas = db.rows(self.cx, """
            SELECT p.path FROM photos p
            JOIN bands b ON b.id = p.band_id
            WHERE (b.nombre LIKE ? COLLATE NOCASE
                   OR b.ig_handle LIKE ? COLLATE NOCASE)
              AND p.usable_meme = 1 AND p.usada = 0 AND p.descartada = 0
            ORDER BY p.nitidez DESC LIMIT ?
        """, (like, like, n))
        return [ImagenCandidata(f["path"], "banco") for f in filas]


class CoversProvider:
    """Portadas de releases (events.cover_url) vía el cache anti-DNS de covers."""

    nombre = "covers"

    def __init__(self, cx):
        self.cx = cx

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        like = f"%{hint.strip()}%"
        filas = db.rows(self.cx, """
            SELECT e.cover_url, e.titulo FROM events e
            JOIN bands b ON b.id = e.band_id
            WHERE e.cover_url IS NOT NULL
              AND (e.titulo LIKE ? COLLATE NOCASE
                   OR b.nombre LIKE ? COLLATE NOCASE)
            ORDER BY e.fecha_evento DESC LIMIT ?
        """, (like, like, n))
        out = []
        for f in filas:
            ruta = covers.asegurar_cover(f["cover_url"])
            if ruta:
                out.append(ImagenCandidata(str(ruta), "covers", credito=f["titulo"]))
        return out


def providers_default(cx=None) -> dict:
    """Providers disponibles. banco/covers requieren conexión a la DB."""
    out: dict = {}
    if cx is not None:
        out["banco"] = BancoProvider(cx)
        out["covers"] = CoversProvider(cx)
    return out


def resolver(hints: list[str], fuentes: list[str], *, cx=None,
             providers: dict | None = None) -> list[ImagenCandidata | None]:
    """Una candidata (o None) por hint, sin repetir imagen dentro del set."""
    provs = providers if providers is not None else providers_default(cx)
    usadas: set[str] = set()
    out: list[ImagenCandidata | None] = []
    for hint in hints:
        elegida = None
        for fuente in fuentes:
            prov = provs.get(fuente)
            if prov is None:
                continue
            try:
                candidatas = prov.buscar(hint, n=4)
            except Exception as e:  # noqa: BLE001 — el set no truena por sourcing
                print(f"[image_sources] provider {fuente} falló: {e}")
                continue
            for c in candidatas:
                if c.ruta_o_url not in usadas:
                    elegida = c
                    break
            if elegida:
                break
        if elegida:
            usadas.add(elegida.ruta_o_url)
        out.append(elegida)
    return out
```

- [ ] **Step 4: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_image_sources.py -v && ruff check src/image_sources.py tests/test_image_sources.py`
Expected: 10 PASS, ruff limpio

- [ ] **Step 5: Commit**

```bash
git add src/image_sources.py tests/test_image_sources.py
git commit -m "feat(slideshows): sourcing en cascada + providers banco y covers + cache de descargas"
```

---

### Task 5: Provider Pexels

**Files:**
- Modify: `src/image_sources.py` (agregar `PexelsProvider` y registrarlo en `providers_default`)
- Modify: `config.py` (agregar `PEXELS_API_KEY = _get("PEXELS_API_KEY")` en un bloque nuevo `# ---------- Sourcing externo ----------` después del bloque Cloudinary)
- Test: `tests/test_image_sources.py` (agregar tests)

**Interfaces:**
- Consumes: `config.PEXELS_API_KEY`, `_descargar_cache` (Task 4).
- Produces: `PexelsProvider` con `nombre = "pexels"` y `buscar(hint, n=3) -> list[ImagenCandidata]`; registrado en `providers_default()` (sin necesitar `cx`).

- [ ] **Step 1: Agregar tests que fallan**

Al final de `tests/test_image_sources.py`:

```python
def test_pexels_sin_api_key_devuelve_vacio(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", None)
    assert isrc.PexelsProvider().buscar("coffee") == []


def test_pexels_parsea_respuesta(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", "k123")
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"photos": [
                {"src": {"large2x": "https://img/1.jpg"},
                 "photographer": "Ana"},
                {"src": {"large2x": "https://img/2.jpg"},
                 "photographer": "Luis"},
            ]}

    llamadas = {}

    def _get(url, **kw):
        if "api.pexels.com" in url:
            llamadas["headers"] = kw.get("headers")
            return _Resp()
        # descarga de la imagen

        class _Img:
            status_code = 200
            content = b"\xff\xd8\xff" + b"x" * 50

            def raise_for_status(self):
                pass

        return _Img()

    monkeypatch.setattr(isrc.requests, "get", _get)
    out = isrc.PexelsProvider().buscar("coffee", n=2)
    assert len(out) == 2
    assert out[0].source == "pexels"
    assert out[0].credito == "Ana"
    assert out[0].ruta_o_url.endswith(".jpg")  # ruta local del cache
    assert llamadas["headers"]["Authorization"] == "k123"


def test_pexels_error_http_devuelve_vacio(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "PEXELS_API_KEY", "k123")

    def _get(url, **kw):
        raise isrc.requests.RequestException("timeout")

    monkeypatch.setattr(isrc.requests, "get", _get)
    assert isrc.PexelsProvider().buscar("coffee") == []
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_image_sources.py -v -k pexels`
Expected: FAIL con `AttributeError: ... no attribute 'PexelsProvider'`

- [ ] **Step 3: Implementar `PexelsProvider`**

En `src/image_sources.py`, después de `CoversProvider`:

```python
class PexelsProvider:
    """Búsqueda en Pexels (API oficial, licencia limpia para uso comercial)."""

    nombre = "pexels"

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        if not config.PEXELS_API_KEY:
            return []
        try:
            r = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": hint, "per_page": n, "orientation": "portrait"},
                headers={"Authorization": config.PEXELS_API_KEY},
                timeout=20,
            )
            r.raise_for_status()
            fotos = r.json().get("photos", [])
        except (requests.RequestException, ValueError) as e:
            print(f"[image_sources] pexels falló: {e}")
            return []
        out = []
        for f in fotos[:n]:
            url = (f.get("src") or {}).get("large2x") or (f.get("src") or {}).get("large")
            if not url:
                continue
            ruta = _descargar_cache(url)
            if ruta:
                out.append(ImagenCandidata(str(ruta), "pexels",
                                           credito=f.get("photographer")))
        return out
```

Y en `providers_default`, antes del `return`:

```python
    out["pexels"] = PexelsProvider()
```

En `config.py` (bloque nuevo tras Cloudinary):

```python
# ---------- Sourcing externo (motor de slideshows) ----------
PEXELS_API_KEY = _get("PEXELS_API_KEY")
```

- [ ] **Step 4: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_image_sources.py -v && ruff check src/image_sources.py config.py`
Expected: 13 PASS, ruff limpio

- [ ] **Step 5: Commit**

```bash
git add src/image_sources.py tests/test_image_sources.py config.py
git commit -m "feat(slideshows): provider Pexels (API oficial) con cache local"
```

---

### Task 6: Provider Pinterest (flag + circuit breaker)

**Files:**
- Modify: `src/image_sources.py` (agregar `PinterestProvider`, registrarlo)
- Modify: `config.py` (agregar `SOURCING_PINTEREST` junto a `PEXELS_API_KEY`)
- Test: `tests/test_image_sources.py` (agregar tests)

**Interfaces:**
- Consumes: `config.SOURCING_PINTEREST` (bool), `_descargar_cache`.
- Produces: `PinterestProvider` con `nombre = "pinterest"`, `buscar(hint, n=3)`, atributo interno `_muerto` (circuit breaker de la corrida); registrado en `providers_default()`.

- [ ] **Step 1: Agregar tests que fallan**

Al final de `tests/test_image_sources.py`:

```python
def test_pinterest_apagado_por_flag(monkeypatch) -> None:
    monkeypatch.setattr(isrc.config, "SOURCING_PINTEREST", False)
    assert isrc.PinterestProvider().buscar("coffee") == []


def test_pinterest_parsea_resultados(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(isrc.config, "SOURCING_PINTEREST", True)
    monkeypatch.setattr(isrc, "SOURCING_DIR", tmp_path)

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"resource_response": {"data": {"results": [
                {"images": {"orig": {"url": "https://i.pinimg.com/a.jpg"}}},
            ]}}}

    def _get(url, **kw):
        if "pinterest.com" in url:
            return _Resp()

        class _Img:
            status_code = 200
            content = b"\xff\xd8\xff" + b"x" * 50

            def raise_for_status(self):
                pass

        return _Img()

    monkeypatch.setattr(isrc.requests, "get", _get)
    out = isrc.PinterestProvider().buscar("coffee")
    assert out and out[0].source == "pinterest"


def test_pinterest_circuit_breaker(monkeypatch) -> None:
    """Tras un fallo, el provider queda muerto en la corrida: no reintenta."""
    monkeypatch.setattr(isrc.config, "SOURCING_PINTEREST", True)
    contador = {"n": 0}

    def _get(url, **kw):
        contador["n"] += 1
        raise isrc.requests.RequestException("403")

    monkeypatch.setattr(isrc.requests, "get", _get)
    p = isrc.PinterestProvider()
    assert p.buscar("a") == []
    assert p.buscar("b") == []  # segundo hint: NO vuelve a pegarle a la red
    assert contador["n"] == 1
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_image_sources.py -v -k pinterest`
Expected: FAIL con `AttributeError: ... no attribute 'PinterestProvider'`

- [ ] **Step 3: Implementar `PinterestProvider`**

En `src/image_sources.py`, después de `PexelsProvider`:

```python
class PinterestProvider:
    """Búsqueda en Pinterest vía su endpoint JSON interno (SIN API oficial).

    Best-effort detrás del flag SOURCING_PINTEREST: cualquier fallo apaga el
    provider por el resto de la corrida (circuit breaker) y la cascada cae al
    siguiente (pexels). Las imágenes pueden tener copyright de terceros: la
    proveniencia queda marcada (source="pinterest") para auditar/bajar.
    """

    nombre = "pinterest"

    def __init__(self):
        self._muerto = False

    def buscar(self, hint: str, n: int = 3) -> list[ImagenCandidata]:
        if not config.SOURCING_PINTEREST or self._muerto:
            return []
        import json as json_mod
        try:
            r = requests.get(
                "https://www.pinterest.com/resource/BaseSearchResource/get/",
                params={
                    "source_url": f"/search/pins/?q={hint}",
                    "data": json_mod.dumps(
                        {"options": {"query": hint, "scope": "pins"}, "context": {}}),
                },
                headers={
                    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/126.0 Safari/537.36"),
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=20,
            )
            r.raise_for_status()
            resultados = (r.json().get("resource_response", {})
                          .get("data", {}).get("results", []))
        except (requests.RequestException, ValueError) as e:
            print(f"[image_sources] pinterest falló, se apaga esta corrida: {e}")
            self._muerto = True
            return []
        out = []
        for res in resultados:
            url = ((res.get("images") or {}).get("orig") or {}).get("url")
            if not url:
                continue
            ruta = _descargar_cache(url)
            if ruta:
                out.append(ImagenCandidata(str(ruta), "pinterest"))
            if len(out) >= n:
                break
        return out
```

Y en `providers_default`:

```python
    out["pinterest"] = PinterestProvider()
```

En `config.py`, junto a `PEXELS_API_KEY`:

```python
# Pinterest es scraping best-effort (sin API oficial): apagado por default.
SOURCING_PINTEREST = (_get("SOURCING_PINTEREST", "0") or "0") == "1"
```

- [ ] **Step 4: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_image_sources.py -v && ruff check src/image_sources.py config.py`
Expected: 16 PASS, ruff limpio

- [ ] **Step 5: Commit**

```bash
git add src/image_sources.py tests/test_image_sources.py config.py
git commit -m "feat(slideshows): provider Pinterest tras flag con circuit breaker"
```

---

### Task 7: Plantilla de slide (`templates/slide.html`)

**Files:**
- Create: `templates/slide.html`
- Test: `tests/test_slide_render.py` (smoke con Playwright real)

**Interfaces:**
- Consumes: el ctx de `contexto_slide` (Task 3) vía `compose.render_card("slide.html", ctx)`.
- Produces: PNG del slide en `out/` (lo consume Task 8).

- [ ] **Step 1: Escribir el smoke test que falla**

`tests/test_slide_render.py`:

```python
"""Smoke de render de slide.html: rinde y auto-fitea, sin comparar píxeles.

Usa Playwright/Chromium REAL (ya es dependencia del repo, igual que compose).
"""
from __future__ import annotations

from dataclasses import dataclass

from src import compose
from src import slideshow_compile as sc


@dataclass
class _Img:
    ruta_o_url: str
    source: str = "manual"


def _guion():
    return {"tema": "café", "hook": "5 secretos del café", "caption": "pie",
            "cta": "Sígueme para más",
            "slides": [
                {"text": "5 secretos del café que nadie te cuenta",
                 "rol": "hook", "image_hint": "a"},
                {"text": "El agua importa más que el grano", "rol": "punto",
                 "image_hint": "b"},
                {"text": "Sígueme para más", "rol": "cta", "image_hint": "c"},
            ]}


def test_render_slide_con_fondo_solido(tmp_path) -> None:
    """Sin imagen (fallback sólido): debe producir un PNG no trivial."""
    show = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    ctx = sc.contexto_slide(show, 0)
    png = compose.render_card("slide.html", ctx, out_path=tmp_path / "s0.png")
    assert png.exists() and png.stat().st_size > 10_000


def test_render_slide_cta_estilo_editorial(tmp_path) -> None:
    show = sc.compilar(_guion(), estilo="editorial", imagenes=[None] * 3)
    ctx = sc.contexto_slide(show, 2)
    png = compose.render_card("slide.html", ctx, out_path=tmp_path / "s2.png")
    assert png.exists() and png.stat().st_size > 10_000
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_slide_render.py -v`
Expected: FAIL con `jinja2.exceptions.TemplateNotFound: slide.html`

- [ ] **Step 3: Implementar `templates/slide.html`**

Nota: `compose._screenshot_card` usa viewport fijo 1080×1350 pero el screenshot es del nodo `.card` — la tarjeta define su propio tamaño con `width`/`height` del ctx, así que aspects distintos funcionan sin tocar compose.

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  {% for f in font_faces %}
  @font-face { font-family:'{{ f.name }}'; src:url('{{ f.url }}') format('truetype'); }
  {% endfor %}

  * { margin:0; padding:0; box-sizing:border-box; }

  .card {
    width:{{ width }}px; height:{{ height }}px; position:relative;
    overflow:hidden; background:{{ bg_color }};
  }

  /* Grilla de imágenes de fondo (image_layout del contrato). */
  .bg {
    position:absolute; inset:0; display:grid; gap:6px;
    grid-template-columns:repeat({{ grid_cols }}, 1fr);
    grid-template-rows:repeat({{ grid_rows }}, 1fr);
  }
  .bg img { width:100%; height:100%; object-fit:cover; display:block; }

  .overlay { position:absolute; inset:0; background:#000; opacity:{{ overlay_opacity }}; }

  /* Tres zonas verticales apiladas; cada text_item cae en la suya. */
  .zonas {
    position:absolute; inset:0; display:flex; flex-direction:column;
    justify-content:space-between; padding:{{ (height * 0.06) | round | int }}px 0;
  }
  .zona { display:flex; flex-direction:column; width:100%; }
  .zona.top { justify-content:flex-start; }
  .zona.center { flex:1; justify-content:center; }
  .zona.bottom { justify-content:flex-end; }

  .txt { line-height:1.22; }
  .txt.a-left { align-self:flex-start; margin-left:4%; }
  .txt.a-center { align-self:center; }
  .txt.a-right { align-self:flex-end; margin-right:4%; }

  .txt.estilo-outline span.linea {
    -webkit-text-stroke:0.055em #000;
    paint-order:stroke fill;
    text-shadow:0 2px 12px rgba(0,0,0,.45);
  }
  .txt.estilo-background span.linea {
    box-decoration-break:clone; -webkit-box-decoration-break:clone;
    padding:0.08em 0.34em; border-radius:0.12em;
  }
  .txt.estilo-text span.linea { text-shadow:0 2px 14px rgba(0,0,0,.55); }
</style>
</head>
<body>
  <div class="card">
    {% if image_srcs %}
    <div class="bg">
      {% for src in image_srcs %}<img src="{{ src }}">{% endfor %}
    </div>
    <div class="overlay"></div>
    {% endif %}
    <div class="zonas">
      {% for zona in ["top", "center", "bottom"] %}
      <div class="zona {{ zona }}">
        {% for it in items if it.v_anchor == zona %}
        <div class="txt a-{{ it.anchor }} estilo-{{ it.estilo }}"
             style="font-family:'{{ it.font }}'; font-size:{{ it.px }}px;
                    color:{{ it.color }}; max-width:{{ it.width_pct }}%;
                    text-align:{{ it.align }};
                    {% if it.estilo == 'background' %}--caja:{{ it.caja }};{% endif %}">
          <span class="linea"
                {% if it.estilo == 'background' %}style="background:{{ it.caja }};"{% endif %}
          >{{ it.text }}</span>
        </div>
        {% endfor %}
      </div>
      {% endfor %}
    </div>
  </div>
  <script>
    // Auto-fit por text_item: encoge la fuente hasta caber en su zona,
    // mismo patrón que fitCaption de meme.html.
    function fitAll() {
      const card = document.querySelector('.card');
      document.querySelectorAll('.txt').forEach(el => {
        let size = parseFloat(getComputedStyle(el).fontSize);
        const minSize = 24;
        const maxH = card.clientHeight * 0.62;
        while ((el.scrollHeight > maxH || el.scrollWidth > el.clientWidth + 2)
               && size > minSize) {
          size -= 2; el.style.fontSize = size + 'px';
        }
      });
      window.__captionFitted = true;
    }
    document.fonts.ready.then(() =>
      requestAnimationFrame(() => requestAnimationFrame(fitAll)));
  </script>
</body>
</html>
```

- [ ] **Step 4: Correr tests, verificar verde e inspección visual**

Run: `python -m pytest tests/test_slide_render.py -v`
Expected: 2 PASS (tardan unos segundos: Chromium real)

Además, generar un PNG de muestra y ABRIRLO para revisar a ojo:

```bash
python - <<'EOF'
from src import compose, slideshow_compile as sc
g = {"tema": "café", "hook": "5 secretos del café", "caption": "", "cta": "Sígueme",
     "slides": [{"text": "5 secretos del café que nadie te cuenta", "rol": "hook",
                 "image_hint": "a"}]}
show = sc.compilar(g, estilo="tiktok_bold", imagenes=[None])
p = compose.render_card("slide.html", sc.contexto_slide(show, 0), prefix="demo_slide")
print(p)
EOF
open out/demo_slide*.png
```
Expected: tarjeta 1080×1350 fondo negro, hook en Anton blanco con caja negra… legible y centrado. Si se ve mal, iterar el CSS antes de commitear.

- [ ] **Step 5: Commit**

```bash
git add templates/slide.html tests/test_slide_render.py
git commit -m "feat(slideshows): plantilla slide.html (grilla, overlay, anchors, auto-fit)"
```

---

### Task 8: Migración + orquestador CLI (`generate_slideshow.py`)

**Files:**
- Modify: `src/db.py` (migración `content_queue.slideshow_json` + whitelist)
- Create: `src/generate_slideshow.py`
- Test: `tests/test_generate_slideshow.py`

**Interfaces:**
- Consumes: todo lo anterior + `approval.encolar_pendiente`, `approval.enviar_a_telegram`, `host.upload`, `compose.render_card`, `db`.
- Produces:
  - `generar(cx, tema, *, formato="listicle", estilo="tiktok_bold", fuentes=("pexels",), n_slides=6, aspect="4:5", contexto=None, dry_run=False) -> int | None` — queue_id o None en dry-run.
  - CLI: `python -m src.generate_slideshow --tema "..." [--formato listicle] [--estilo tiktok_bold] [--fuentes pexels,banco] [--n-slides 6] [--aspect 4:5] [--contexto "..."] [--dry-run]`
- Nota de flujo: `tipo="slideshow"` en `content_queue` → `approval.aprobar` NO lo trata como inmediato (solo `tipo == "anuncio"` lo es) → toma slot de la malla 2/día, como pide el spec. Sin cambios en `approval.py`.

- [ ] **Step 1: Migración en `src/db.py`**

En el dict `_MIGRATIONS`, dentro de la entrada `"content_queue"`, agregar:

```python
        # Motor de slideshows: contrato completo del set (JSON) para
        # regenerar/re-estilar y para el futuro export a video.
        "slideshow_json": "TEXT",
```

Y en el dict whitelist de columnas (el que usa `_check_cols`, entrada `"content_queue"`), agregar `"slideshow_json"` al set.

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_generate_slideshow.py`:

```python
"""Orquestador de slideshows: dry-run, encolado y envío a Telegram."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src import db
from src import generate_slideshow as gs


@dataclass
class _Img:
    ruta_o_url: str
    source: str = "pexels"


def _guion(n=3):
    return {"tema": "café", "hook": "Gancho", "caption": "pie del post",
            "cta": "Sígueme",
            "slides": [{"text": "Gancho", "rol": "hook", "image_hint": "a"},
                       {"text": "Punto", "rol": "punto", "image_hint": "b"},
                       {"text": "Sígueme", "rol": "cta", "image_hint": "c"}][:n]}


def _preparar(monkeypatch, tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: _guion())
    monkeypatch.setattr(gs.image_sources, "resolver",
                        lambda hints, fuentes, **kw: [_Img("/tmp/x.jpg")] * len(hints))
    pngs = iter([tmp_path / f"s{i}.png" for i in range(10)])

    def _render(template_file, ctx, **kw):
        p = next(pngs)
        p.write_bytes(b"png")
        return p

    monkeypatch.setattr(gs.compose, "render_card", _render)
    subidas = []

    def _upload(path, public_id=None):
        subidas.append(public_id)
        return f"https://cdn/{public_id}.jpg"

    monkeypatch.setattr(gs.host, "upload", _upload)
    enviados = []
    monkeypatch.setattr(gs.approval, "enviar_a_telegram",
                        lambda cap, url, qid, **kw: enviados.append((cap, url, qid)))
    return cx, subidas, enviados


def test_dry_run_no_sube_ni_encola(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    out = gs.generar(cx, "café", dry_run=True)
    assert out is None
    assert subidas == [] and enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []


def test_generar_encola_y_envia(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café")
    assert qid is not None
    fila = db.get(cx, "content_queue", qid)
    assert fila["tipo"] == "slideshow"
    assert fila["aprobacion"] == "pendiente"
    urls = json.loads(fila["imagen_url"])
    assert len(urls) == 3 and all(u.startswith("https://cdn/") for u in urls)
    contrato = json.loads(fila["slideshow_json"])
    assert len(contrato["slides"]) == 3
    assert enviados and enviados[0][2] == qid
    assert len(subidas) == 3


def test_generar_aborta_si_contrato_invalido(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    malo = _guion()
    malo["slides"][0]["text"] = "   "
    monkeypatch.setattr(gs.slideshow_script, "generar_guion",
                        lambda tema, **kw: malo)
    import pytest
    with pytest.raises(RuntimeError):
        gs.generar(cx, "café")
    assert enviados == []
    assert db.rows(cx, "SELECT * FROM content_queue") == []
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `python -m pytest tests/test_generate_slideshow.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.generate_slideshow'`

- [ ] **Step 4: Implementar `src/generate_slideshow.py`**

```python
"""Entrypoint del motor de slideshows (Proceso A, no-bloqueante).

CLI/GUI → guion (LLM) → imágenes (cascada de fuentes) → compilar → render →
Cloudinary → encolar + Telegram. El approval-daemon resuelve la aprobación;
publish.py publica el carrusel. NO abre poller de Telegram.

Uso:
  python -m src.generate_slideshow --tema "cafeterías de GDL" \
      --formato listicle --estilo tiktok_bold --fuentes pexels,banco --dry-run
"""
from __future__ import annotations

import argparse
import json
import time

import config
from src import (approval, compose, db, host, image_sources, slideshow_compile,
                 slideshow_model, slideshow_script)


def generar(cx, tema: str, *, formato: str = "listicle",
            estilo: str = "tiktok_bold", fuentes: tuple[str, ...] = ("pexels",),
            n_slides: int = 6, aspect: str = "4:5", contexto: str | None = None,
            dry_run: bool = False) -> int | None:
    """Genera el set completo; queue_id, o None en dry-run."""
    guion = slideshow_script.generar_guion(tema, formato=formato,
                                           n_slides=n_slides, contexto=contexto)
    hints = [sl["image_hint"] for sl in guion["slides"]]
    imagenes = image_sources.resolver(hints, list(fuentes), cx=cx)
    sin_imagen = sum(1 for i in imagenes if i is None)
    if sin_imagen:
        print(f"[slideshow] {sin_imagen}/{len(imagenes)} slides sin imagen "
              "(fondo sólido)")
    brief = {"tema": tema, "formato": formato, "estilo": estilo,
             "fuentes": list(fuentes), "n_slides": n_slides,
             "contexto": contexto, "aspect": aspect}
    show = slideshow_compile.compilar(guion, estilo=estilo, imagenes=imagenes,
                                      aspect_ratio=aspect, brief=brief,
                                      formato=formato)
    errores = slideshow_model.validar(show)
    if errores:
        raise RuntimeError(f"Contrato inválido, no se encola: {errores}")

    pngs = []
    for i in range(len(show.slides)):
        ctx = slideshow_compile.contexto_slide(show, i)
        pngs.append(compose.render_card("slide.html", ctx, prefix=f"slide{i}"))
    if dry_run:
        print("[slideshow] dry-run, PNGs en:")
        for p in pngs:
            print(f"  {p}")
        return None

    ts = int(time.time())
    urls = [host.upload(str(p), public_id=f"ss{ts}_{i}")
            for i, p in enumerate(pngs)]
    qid = approval.encolar_pendiente(
        cx, tipo="slideshow", caption=show.caption,
        imagen_url=json.dumps(urls), template=estilo,
        tema_semilla=f"slideshow {formato}: {tema}")
    db.update(cx, "content_queue", qid,
              slideshow_json=slideshow_model.a_json(show))
    approval.enviar_a_telegram(show.caption, json.dumps(urls), qid)
    print(f"[slideshow] q{qid} enviado a Telegram ({len(urls)} slides)")
    return qid


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera un slideshow y lo manda a aprobación")
    ap.add_argument("--tema", required=True)
    ap.add_argument("--formato", default="listicle",
                    choices=sorted(config.SLIDESHOW_FORMATOS))
    ap.add_argument("--estilo", default="tiktok_bold",
                    choices=sorted(config.SLIDESHOW_ESTILOS))
    ap.add_argument("--fuentes", default="pexels",
                    help="orden de fuentes separado por comas: banco,covers,pexels,pinterest")
    ap.add_argument("--n-slides", type=int, default=6)
    ap.add_argument("--aspect", default="4:5",
                    choices=sorted(slideshow_model.ASPECT_RATIOS))
    ap.add_argument("--contexto", default=None,
                    help="voz/instrucciones extra para el guion")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cx = db.connect()
    try:
        db.init_db(cx)
        generar(cx, args.tema, formato=args.formato, estilo=args.estilo,
                fuentes=tuple(f.strip() for f in args.fuentes.split(",") if f.strip()),
                n_slides=args.n_slides, aspect=args.aspect,
                contexto=args.contexto, dry_run=args.dry_run)
    finally:
        cx.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Correr tests y ruff, verificar verde (incluye suite completa)**

Run: `python -m pytest tests/ -x -q && ruff check src tests`
Expected: suite completa verde (los ~680 existentes + los nuevos), ruff limpio. Si fallan tests PREEXISTENTES conocidos (sensibles a fecha/pool scraper, ver memoria del repo), verificar que fallaban igual ANTES de este cambio (`git stash` + rerun) y anotarlo en el commit.

- [ ] **Step 6: Commit**

```bash
git add src/db.py src/generate_slideshow.py tests/test_generate_slideshow.py
git commit -m "feat(slideshows): orquestador CLI + migracion slideshow_json en content_queue"
```

---

### Task 9: Página GUI `/slideshows`

**Files:**
- Create: `web/templates/slideshows.html`
- Modify: `web/app.py` (rutas GET `/slideshows` y POST `/slideshows/generar`)
- Modify: `web/templates/base.html` (link "Slideshows" en la navegación, junto a los existentes)
- Test: `tests/test_slideshows_web.py`

**Interfaces:**
- Consumes: `_lanzar_sesion(modulo, *args)` existente en `web/app.py` (lanza `python -m <modulo>` detached; devuelve HTMLResponse de bloqueo si el bot interactivo está corriendo, None si lanzó).
- Produces: form GUI → `python -m src.generate_slideshow --tema ... --formato ... --estilo ... --fuentes ... --n-slides N` detached.

- [ ] **Step 1: Escribir el test que falla**

`tests/test_slideshows_web.py` (mismo patrón que los tests web existentes: `TestClient` de FastAPI con monkeypatch del launcher):

```python
"""GUI /slideshows: la página carga y el POST lanza el generador detached."""
from __future__ import annotations

from fastapi.testclient import TestClient

from web import app as web_app


def test_get_slideshows_carga() -> None:
    client = TestClient(web_app.app)
    r = client.get("/slideshows")
    assert r.status_code == 200
    assert "slideshow" in r.text.lower()


def test_post_generar_lanza_modulo(monkeypatch) -> None:
    lanzados = []

    def _fake_lanzar(modulo, *args):
        lanzados.append((modulo, args))
        return None

    monkeypatch.setattr(web_app, "_lanzar_sesion", _fake_lanzar)
    client = TestClient(web_app.app)
    r = client.post("/slideshows/generar", data={
        "tema": "cafeterías de GDL", "formato": "listicle",
        "estilo": "tiktok_bold", "fuentes": "pexels,banco", "n_slides": "5",
    })
    assert r.status_code == 200
    modulo, args = lanzados[0]
    assert modulo == "src.generate_slideshow"
    assert "--tema" in args and "cafeterías de GDL" in args
    assert "--n-slides" in args and "5" in args
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_slideshows_web.py -v`
Expected: FAIL — GET /slideshows devuelve 404

- [ ] **Step 3: Implementar rutas y plantilla**

En `web/app.py` (junto a las demás rutas; usa los objetos `templates`, `Request`, `Form` ya importados en el archivo):

```python
@app.get("/slideshows", response_class=HTMLResponse)
def slideshows_vista(request: Request) -> HTMLResponse:
    """Form para generar un slideshow (motor genérico, spec 2026-08-09)."""
    import config as cfg
    return templates.TemplateResponse(request, "slideshows.html", {
        "formatos": sorted(cfg.SLIDESHOW_FORMATOS),
        "estilos": sorted(cfg.SLIDESHOW_ESTILOS),
    })


@app.post("/slideshows/generar", response_class=HTMLResponse)
def slideshows_generar(tema: str = Form(...), formato: str = Form("listicle"),
                       estilo: str = Form("tiktok_bold"),
                       fuentes: str = Form("pexels"),
                       n_slides: int = Form(6),
                       contexto: str = Form("")) -> HTMLResponse:
    args = ["--tema", tema, "--formato", formato, "--estilo", estilo,
            "--fuentes", fuentes, "--n-slides", str(n_slides)]
    if contexto.strip():
        args += ["--contexto", contexto.strip()]
    bloqueo = _lanzar_sesion("src.generate_slideshow", *args)
    if bloqueo:
        return bloqueo
    return HTMLResponse("⏳ Generando slideshow… llegará a Telegram para aprobar.")
```

`web/templates/slideshows.html` (sigue el patrón de las páginas existentes — extiende `base.html`, form HTMX que postea a `/slideshows/generar` con target de resultado):

```html
{% extends "base.html" %}
{% block contenido %}
<h2>Slideshows</h2>
<form hx-post="/slideshows/generar" hx-target="#resultado" hx-swap="innerHTML">
  <label>Tema
    <input name="tema" required placeholder="p.ej. cafeterías de especialidad en GDL">
  </label>
  <label>Formato
    <select name="formato">
      {% for f in formatos %}<option value="{{ f }}">{{ f }}</option>{% endfor %}
    </select>
  </label>
  <label>Estilo
    <select name="estilo">
      {% for e in estilos %}<option value="{{ e }}">{{ e }}</option>{% endfor %}
    </select>
  </label>
  <label>Fuentes (orden, separadas por coma)
    <input name="fuentes" value="pexels" placeholder="banco,covers,pexels,pinterest">
  </label>
  <label>Slides <input name="n_slides" type="number" value="6" min="2" max="10"></label>
  <label>Contexto/voz (opcional)
    <input name="contexto" placeholder="tono, marca, reglas extra para el guion">
  </label>
  <button type="submit">▶ Generar y mandar a Telegram</button>
</form>
<div id="resultado"></div>
{% endblock %}
```

(Ajustar nombres de bloque/estructura al `base.html` real al implementar — el bloque puede llamarse distinto; copiar el de cualquier página existente como `deezer.html`.) Agregar en la navegación de `base.html` un link `<a href="/slideshows">Slideshows</a>` junto a los existentes.

- [ ] **Step 4: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_slideshows_web.py -v && ruff check web tests/test_slideshows_web.py`
Expected: 2 PASS, ruff limpio

- [ ] **Step 5: Commit y recordatorio operativo**

```bash
git add web/app.py web/templates/slideshows.html web/templates/base.html tests/test_slideshows_web.py
git commit -m "feat(slideshows): pagina /slideshows en la GUI (form -> generador detached)"
```

Recordar a Ricardo: la GUI corre uvicorn SIN --reload en 127.0.0.1:8742 — hay que reiniciarlo para ver las rutas nuevas.

---

### Task 10: Verificación E2E manual (con Ricardo)

**Files:** ninguno nuevo (solo fixes que salgan de la verificación).

Esta tarea es el criterio de éxito del spec; requiere `.env` real (DeepSeek, Cloudinary, Telegram) y, para el paso 4, aprobación humana. Ejecutar en orden y anotar/arreglar lo que falle:

- [ ] **Step 1: Dry-run genérico con Pexels** (requiere `PEXELS_API_KEY` en `.env` — Ricardo la crea gratis en pexels.com/api)

```bash
python -m src.generate_slideshow --tema "5 señales de que tu cafetería favorita es especial" --fuentes pexels --n-slides 5 --dry-run
open out/slide*.png
```
Expected: 5 PNGs con fotos reales de Pexels + texto legible. Revisar a ojo: contraste, tamaño, cortes de línea.

- [ ] **Step 2: Dry-run con el banco propio** ("todo lo que sabemos", pendiente editorial de junio)

```bash
python -m src.generate_slideshow --tema "todo lo que sabemos del proximo lanzamiento de Kabala" --formato todo_lo_que_sabemos --fuentes banco,covers,pexels --n-slides 5 --contexto "sátira estilo The Onion sobre la escena musical de Guadalajara, deadpan, español de México" --dry-run
```
Expected: slides con fotos del banco de Kabala; hints sin match caen a covers/pexels.

- [ ] **Step 3: Generación real → Telegram** (sin `--dry-run`, con el approval-daemon vivo)

Expected: álbum en Telegram con botones ✅/❌; la fila en `content_queue` con `tipo='slideshow'`, `slideshow_json` poblado.

- [ ] **Step 4: Aprobar en Telegram y verificar el agendado**

Expected: fila approved en el Sheet con `scheduled_datetime` en el siguiente hueco de la malla 2/día (NO inmediato); al vencer, `publish.py` (cron o local) publica el carrusel en IG.

- [ ] **Step 5: Commit de los fixes que hayan salido + push**

```bash
git push
```

---

## Self-review del plan (hecho al escribirlo)

- **Cobertura del spec:** contrato dos capas (T1-T3), sourcing 4 providers + cascada + cache + flag Pinterest + circuit breaker (T4-T6), plantilla contrato completo con grids/anchors/auto-fit (T7), migración `slideshow_json` + orquestador + dry-run + encolado por camino existente (T8), GUI (T9), criterio de éxito (T10). Regenerar-desde-Telegram: explícitamente posterior (spec lo marca como mejora futura).
- **Fuera de alcance respetado:** ni video, ni TikTok, ni perfiles en DB, ni automations.
- **Consistencia de firmas:** `ImagenCandidata.ruta_o_url/.source` usados igual en T3/T4/T8; `contexto_slide` produce exactamente las llaves que `slide.html` consume; `generar_guion(tema, *, formato, n_slides, contexto, rechazados, feedback)` consistente entre T2 y T8.
- **Nota `image_layout`:** el compilador v1 siempre emite `single` (una imagen por slide); el contrato, la validación y la plantilla ya soportan las grillas 1:2/1:3/2:1/2:2 para el modo manual/futuro — eso es lo que compra el Enfoque 3.
