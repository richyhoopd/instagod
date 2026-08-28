# Planes de contenido masivo — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Planes de contenido semanales/mensuales por marca: objetivo → temas curables (1 llamada LLM) → generación masiva en un job → curación de lote en el portal → aprobación en bloque server-side → publisher existente.

**Architecture:** Dos tablas nuevas (`content_plans`, `plan_topics`) + columna `plan_id` en `content_queue`. Dos jobs nuevos (`plan.proponer_temas`, `plan.generar` — un solo job que itera piezas con progreso agregado, respetando el aislamiento un-job-por-cuenta del worker). Router FastAPI nuevo `api/routers/planes.py`. Front Next.js: ruta `/b/[slug]/plans` reutilizando `slide-editor`/`queue-drawer` existentes para la curación.

**Tech Stack:** Python 3.12 + FastAPI + SQLite (WAL) + queue propia (`src/jobs/`) + pytest. Front: Next.js 16 App Router + TanStack Query v5 + shadcn/ui.

**Spec:** `docs/superpowers/specs/2026-08-28-planes-contenido-masivo-design.md`

## Global Constraints

- Todo el código, docstrings, mensajes y textos de UI en **español** (el contrato `Slideshow` mantiene claves en inglés).
- Toda columna escribible debe estar en `db.TABLES` (whitelist); toda columna nueva de `content_queue` va en `_MIGRATIONS` **y además** en `_CONTENT_QUEUE_REBUILD_DDL` + `_CONTENT_QUEUE_REBUILD_COLS` (si no, `RuntimeError` a propósito en `db.py:346`).
- Nunca filtrar secretos en errores: redactar con los valores de `config.account_creds(slug)` y truncar (patrón `_error_seguro`).
- Fechas con timezone: `datetime.now(pytz.timezone(config.TIMEZONE))`, jamás `datetime.now()` naive.
- `n_slides` 1–10 (tope carrusel IG), `n_piezas` 1–30 por plan.
- Todo endpoint por marca empieza con `marca_para(slug, cx, user)` (`api/deps.py`); errores con `ApiError` (`api/errors.py`).
- Tests unitarios sin red, DB en `tmp_path`, IO monkeypatcheado; correr `pytest -q` y `ruff check src/ tests/ api/` antes de cada commit.
- Commits con mensaje `feat(planes): ...` / `fix(...)` / `test(...)`, en español.
- El worker de la VM tiene `mem_limit: 2g` y un render consume ~550 MB: `plan.generar` es UN job secuencial, nunca N jobs paralelos por marca.

---

### Task 1: Esquema y migraciones (content_plans, plan_topics, content_queue.plan_id)

**Files:**
- Modify: `src/schema.sql` (agregar al final)
- Modify: `src/db.py` (TABLES ~línea 110, _MIGRATIONS content_queue ~línea 219, _CONTENT_QUEUE_REBUILD_DDL ~línea 302, _CONTENT_QUEUE_REBUILD_COLS ~línea 314)
- Test: `tests/test_planes_schema.py`

**Interfaces:**
- Produces: tablas `content_plans` y `plan_topics` (columnas exactas abajo), columna `content_queue.plan_id INTEGER` (NULL default). `db.insert/update/get` funcionan sobre ambas tablas nuevas.

- [ ] **Step 1: Write the failing test**

```python
"""Esquema de planes de contenido masivo (spec 2026-08-28)."""
import pytest

from src import db


@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_tablas_de_planes_existen(cx):
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "content_plans" in tablas
    assert "plan_topics" in tablas


def test_content_queue_tiene_plan_id(cx):
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert "plan_id" in cols


def test_plan_id_esta_en_rebuild_de_content_queue():
    # Si content_queue gana una columna sin actualizar el DDL de rebuild,
    # _migrar_check_tipo_queue revienta a propósito. Se valida aquí en frío.
    assert "plan_id" in db._CONTENT_QUEUE_REBUILD_COLS
    assert "plan_id" in db._CONTENT_QUEUE_REBUILD_DDL


def test_crud_content_plans(cx):
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="semana",
                    periodo="2026-W36", objetivo="crecer en awareness local",
                    config_json="{}", creado_por=None)
    fila = db.get(cx, "content_plans", pid)
    assert fila["estado"] == "proponiendo"
    db.update(cx, "content_plans", pid, estado="temas")
    assert db.get(cx, "content_plans", pid)["estado"] == "temas"


def test_check_estado_content_plans(cx):
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        cx.execute("INSERT INTO content_plans (account_id, tipo_periodo, periodo, "
                   "objetivo, estado) VALUES (1, 'semana', '2026-W36', 'x', 'inventado')")


def test_crud_plan_topics(cx):
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="mes",
                    periodo="2026-09", objetivo="lanzar membresía")
    tid = db.insert(cx, "plan_topics", plan_id=pid, orden=0,
                    titulo="5 razones para ir a shows locales",
                    formato="listicle", hook="nadie habla de la 4",
                    fuente="prompt")
    fila = db.get(cx, "plan_topics", tid)
    assert fila["estado"] == "propuesto"
    db.update(cx, "plan_topics", tid, estado="aprobado")
    # ON DELETE CASCADE del plan
    cx.execute("DELETE FROM content_plans WHERE id = ?", (pid,))
    cx.commit()
    assert db.get(cx, "plan_topics", tid) is None


def test_queue_acepta_plan_id(cx):
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="semana",
                    periodo="2026-W36", objetivo="x")
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
                    caption="c", imagen_url="[]", plan_id=pid)
    assert db.get(cx, "content_queue", qid)["plan_id"] == pid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_planes_schema.py -v`
Expected: FAIL (`no such table: content_plans`, `plan_id` desconocida en whitelist)

- [ ] **Step 3: Write minimal implementation**

Al final de `src/schema.sql`:

```sql
-- -----------------------------------------------------------------------------
-- Planes de contenido masivo (spec 2026-08-28): un plan agrupa N temas curables
-- y las piezas de content_queue generadas a partir de ellos. Estados del plan
-- movidos SOLO por jobs/endpoints (src/planes.py documenta las transiciones).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS content_plans (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    tipo_periodo TEXT NOT NULL,
    periodo      TEXT NOT NULL,           -- '2026-W36' | '2026-09'
    objetivo     TEXT NOT NULL,
    config_json  TEXT,                    -- {n_piezas, n_slides, aspect, estilo, formatos, fuentes_imagen, fuentes_info}
    estado       TEXT NOT NULL DEFAULT 'proponiendo',
    error        TEXT,
    creado_por   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (tipo_periodo IN ('semana','mes')),
    CHECK (estado IN ('proponiendo','temas','generando','curacion','aprobado','error'))
);
CREATE INDEX IF NOT EXISTS idx_plans_account ON content_plans(account_id);

CREATE TABLE IF NOT EXISTS plan_topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES content_plans(id) ON DELETE CASCADE,
    orden       INTEGER NOT NULL DEFAULT 0,
    titulo      TEXT NOT NULL,
    formato     TEXT,                     -- clave de config.SLIDESHOW_FORMATOS
    hook        TEXT,                     -- ángulo/gancho sugerido, editable
    fuente      TEXT NOT NULL DEFAULT 'prompt',
    url         TEXT,
    topic_suggestion_id INTEGER,          -- FK suave a topic_suggestions
    estado      TEXT NOT NULL DEFAULT 'propuesto',
    error       TEXT,
    queue_id    INTEGER,                  -- content_queue.id una vez generado
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (fuente IN ('prompt','noticia','manual')),
    CHECK (estado IN ('propuesto','aprobado','descartado','generado','error'))
);
CREATE INDEX IF NOT EXISTS idx_plan_topics_plan ON plan_topics(plan_id);
```

En `src/db.py`:

1. `TABLES` — agregar a `"content_queue"` la entrada `"plan_id",` (junto a `"intentos"`), y las dos tablas nuevas al dict:

```python
    # Planes de contenido masivo (spec 2026-08-28)
    "content_plans": {
        "account_id", "tipo_periodo", "periodo", "objetivo", "config_json",
        "estado", "error", "creado_por",
    },
    "plan_topics": {
        "plan_id", "orden", "titulo", "formato", "hook", "fuente", "url",
        "topic_suggestion_id", "estado", "error", "queue_id",
    },
```

2. `_MIGRATIONS["content_queue"]` — agregar al final:

```python
        # Planes de contenido masivo (spec 2026-08-28): agrupación de piezas.
        "plan_id": "INTEGER",
```

3. `_CONTENT_QUEUE_REBUILD_DDL` — agregar `plan_id INTEGER,` después de la línea `intentos INTEGER NOT NULL DEFAULT 0,` (antes de los CHECK).

4. `_CONTENT_QUEUE_REBUILD_COLS` — agregar `"plan_id",` al final de la tupla.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_planes_schema.py tests/test_motor_migraciones.py tests/test_db_migracion_tipo_queue.py -v`
Expected: PASS (incluidos los tests existentes de migración, que verifican el rebuild)

- [ ] **Step 5: Commit**

```bash
git add src/schema.sql src/db.py tests/test_planes_schema.py
git commit -m "feat(planes): esquema content_plans + plan_topics + content_queue.plan_id"
```

---

### Task 2: Tolerancia n±1 slides en el guion (fix del bug de prod 2026-08-28)

**Files:**
- Modify: `src/slideshow_script.py:57-83` (`validar_guion`) y `:148-177` (`generar_guion`)
- Test: `tests/test_slideshow_script.py` (agregar casos; NO tocar los existentes)

**Interfaces:**
- Consumes: `validar_guion(data, *, n_slides) -> list[str]`, `generar_guion(...) -> dict` (existentes).
- Produces: `recortar_slide_extra(slides: list[dict]) -> list[dict]` (PURO, exportado para tests). `generar_guion` acepta n±1 del LLM: con n+1 recorta un slide 'punto'; con n−1 acepta tal cual.

- [ ] **Step 1: Write the failing tests** (agregar al final de `tests/test_slideshow_script.py`)

```python
def _slides(n):
    """n slides válidos: hook + puntos + cta."""
    mids = [{"text": f"punto {i}", "rol": "punto", "image_hint": "gig photo"}
            for i in range(n - 2)]
    return ([{"text": "el hook", "rol": "hook", "image_hint": "band stage"}]
            + mids
            + [{"text": "sígueme", "rol": "cta", "image_hint": "crowd"}])


def _guion(n):
    return {"tema": "t", "hook": "h", "caption": "c", "cta": "x", "slides": _slides(n)}


def test_validar_tolera_un_slide_de_mas():
    assert slideshow_script.validar_guion(_guion(7), n_slides=6) == []


def test_validar_tolera_un_slide_de_menos():
    assert slideshow_script.validar_guion(_guion(5), n_slides=6) == []


def test_validar_rechaza_dos_de_mas():
    errores = slideshow_script.validar_guion(_guion(8), n_slides=6)
    assert any("±1" in e for e in errores)


def test_recortar_slide_extra_quita_un_punto_no_el_cta():
    slides = _slides(7)
    recortados = slideshow_script.recortar_slide_extra(slides)
    assert len(recortados) == 6
    assert recortados[0]["rol"] == "hook"
    assert recortados[-1]["rol"] == "cta"


def test_recortar_sin_puntos_no_rompe():
    slides = [{"text": "h", "rol": "hook", "image_hint": "x"},
              {"text": "c", "rol": "cta", "image_hint": "x"}]
    assert slideshow_script.recortar_slide_extra(slides) == slides


def test_generar_guion_recorta_cuando_llegan_de_mas(monkeypatch):
    import json as json_mod
    monkeypatch.setattr(slideshow_script, "_llamar_llm",
                        lambda *a, **k: json_mod.dumps(_guion(7)))
    guion = slideshow_script.generar_guion("tema", n_slides=6)
    assert len(guion["slides"]) == 6
    assert guion["slides"][-1]["rol"] == "cta"


def test_generar_guion_acepta_uno_de_menos(monkeypatch):
    import json as json_mod
    monkeypatch.setattr(slideshow_script, "_llamar_llm",
                        lambda *a, **k: json_mod.dumps(_guion(5)))
    guion = slideshow_script.generar_guion("tema", n_slides=6)
    assert len(guion["slides"]) == 5
```

(Si el archivo de tests no importa ya `slideshow_script`, usar el import existente del archivo: `from src import slideshow_script`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_slideshow_script.py -v -k "tolera or recortar or de_mas or de_menos"`
Expected: FAIL (`validar_guion` exige conteo exacto; `recortar_slide_extra` no existe)

- [ ] **Step 3: Write the implementation**

En `validar_guion`, reemplazar:

```python
    if len(slides) != n_slides:
        errores.append(f"slides: se pidieron {n_slides}, llegaron {len(slides)}")
```

por:

```python
    # Tolerancia ±1 (bug de prod 2026-08-28: el LLM insiste en n+1 y quemaba
    # los 3 intentos). Con n+1 el caller recorta un 'punto'; con n−1 se acepta.
    if abs(len(slides) - n_slides) > 1:
        errores.append(f"slides: se pidieron {n_slides} (±1), llegaron {len(slides)}")
```

Agregar después de `validar_guion`:

```python
def recortar_slide_extra(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita el ÚLTIMO slide con rol 'punto' (jamás el hook ni el cta). PURO.

    Si no hay ningún 'punto' que quitar (guion degenerado hook+cta+extra),
    devuelve la lista intacta: validar_guion ya aceptó n±1 y el tope duro de
    10 lo siguen imponiendo approval/instagram al truncar.
    """
    for i in range(len(slides) - 1, -1, -1):
        if slides[i].get("rol") == "punto":
            return slides[:i] + slides[i + 1:]
    return slides
```

En `generar_guion`, reemplazar el cierre del loop:

```python
        errores = validar_guion(data, n_slides=n_slides)
        if not errores:
            return data
```

por:

```python
        errores = validar_guion(data, n_slides=n_slides)
        if not errores:
            if len(data["slides"]) == n_slides + 1:
                data["slides"] = recortar_slide_extra(data["slides"])
            return data
```

- [ ] **Step 4: Run the full test file**

Run: `pytest tests/test_slideshow_script.py -v`
Expected: PASS completo (los tests viejos de conteo exacto ya no existen como tales; si alguno falla porque esperaba el error con conteo exacto n±1, actualizar SOLO ese assert al mensaje nuevo con `±1`)

- [ ] **Step 5: Commit**

```bash
git add src/slideshow_script.py tests/test_slideshow_script.py
git commit -m "fix(slideshows): tolerar n±1 slides del LLM y recortar el punto extra"
```

---

### Task 3: Flag `notificar_telegram` en el motor de slideshows

**Files:**
- Modify: `src/generate_slideshow.py:31-129` (`generar`)
- Modify: `src/jobs/handlers.py:90-114` (`regenerar_slideshow` — propagar el flag desde el brief)
- Test: `tests/test_generate_slideshow.py` (agregar caso)

**Interfaces:**
- Consumes: `generar(cx, tema, *, marca, formato, estilo, fuentes, n_slides, aspect, contexto, dry_run, progreso, creado_por, topic_id) -> int | None`.
- Produces: mismo `generar` con parámetro nuevo keyword-only `notificar_telegram: bool = True`; el brief guardado gana la clave `"notificar_telegram"`; `regenerar_slideshow` la respeta.

- [ ] **Step 1: Write the failing test** (agregar a `tests/test_generate_slideshow.py`, siguiendo el estilo de mocks que ya usa ese archivo para `slideshow_script.generar_guion`, `image_sources.resolver`, `compose.render_card`, `host.upload` y `approval`)

```python
def test_notificar_telegram_false_no_envia(cx_con_marca, monkeypatch, mocks_generacion):
    """Con notificar_telegram=False la pieza se encola pero NO va a Telegram,
    y el brief persiste el flag para que regenerar lo respete."""
    import json
    from src import approval, db, generate_slideshow

    llamadas = []
    monkeypatch.setattr(approval, "enviar_a_telegram",
                        lambda *a, **k: llamadas.append(1))
    qid = generate_slideshow.generar(cx_con_marca, "tema x", marca="gdlscene",
                                     notificar_telegram=False, creado_por=1)
    assert llamadas == []
    brief = json.loads(db.get(cx_con_marca, "content_queue", qid)["slideshow_json"])["brief"]
    assert brief["notificar_telegram"] is False
```

Nota para el ejecutor: `cx_con_marca` y `mocks_generacion` son los nombres ilustrativos de las fixtures que ese archivo YA tiene para montar DB temporal y mockear LLM/render/upload — leer `tests/test_generate_slideshow.py` y usar las fixtures/helpers reales del archivo (existen: el archivo ya prueba `generar` de punta a punta sin red). No inventar fixtures nuevas si ya hay equivalentes.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_slideshow.py -v -k notificar`
Expected: FAIL (`generar() got an unexpected keyword argument 'notificar_telegram'`)

- [ ] **Step 3: Write the implementation**

En `generate_slideshow.generar`:

1. Firma: agregar `notificar_telegram: bool = True` al final (después de `topic_id`).
2. En el dict `brief` (línea ~79) agregar la clave: `"notificar_telegram": notificar_telegram`.
3. Envolver el envío (líneas ~125-127):

```python
    if notificar_telegram:
        approval.enviar_a_telegram(show.caption, json.dumps(urls), qid,
                                   account_slug=m.slug, cx=cx)
        print(f"[slideshow] q{qid} ({m.slug}) enviado a Telegram ({len(urls)} slides)")
    else:
        print(f"[slideshow] q{qid} ({m.slug}) encolado sin Telegram ({len(urls)} slides)")
```

En `handlers.regenerar_slideshow`, en la llamada a `generate_slideshow.generar` agregar:

```python
        notificar_telegram=brief.get("notificar_telegram", True),
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_generate_slideshow.py tests/test_jobs_handlers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/generate_slideshow.py src/jobs/handlers.py tests/test_generate_slideshow.py
git commit -m "feat(slideshows): flag notificar_telegram persistido en el brief"
```

---

### Task 4: `src/plan_temas.py` — propuesta de temas con una llamada LLM

**Files:**
- Modify: `src/slideshow_script.py:108-145` (`_llamar_llm`, `_via_deepseek`, `_via_anthropic` — parámetro `system_prompt`)
- Create: `src/plan_temas.py`
- Test: `tests/test_plan_temas.py`

**Interfaces:**
- Consumes: `slideshow_script._llamar_llm(user_prompt, *, system_prompt=...) -> str` (generalizado aquí).
- Produces: `plan_temas.proponer(objetivo, *, n, formatos, contexto=None, noticias=None) -> list[dict]` donde cada dict es `{"titulo": str, "formato": str, "hook": str, "fuente": "prompt"|"noticia", "url": str|None}`. Puros: `extraer_temas(texto) -> dict|None`, `validar_temas(data, *, formatos) -> list[str]`.

- [ ] **Step 1: Generalizar `_llamar_llm` (cambio previo, sin test propio — lo cubren los tests de este task y los existentes)**

En `src/slideshow_script.py`:

```python
def _llamar_llm(user_prompt: str, *, system_prompt: str = SYSTEM_PROMPT) -> str:
    """IO: una llamada al proveedor configurado. Monkeypatch-eable en tests.

    `system_prompt` permite reusar el mismo cliente para otros guiones
    (p. ej. src/plan_temas.py) sin duplicar el manejo de proveedores.
    """
    if config.LLM_PROVIDER == "claude":
        return _via_anthropic(user_prompt, system_prompt)
    return _via_deepseek(user_prompt, system_prompt)


def _via_deepseek(user_prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    ...  # igual que hoy, pero messages=[{"role": "system", "content": system_prompt}, ...]


def _via_anthropic(user_prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str:
    ...  # igual que hoy, pero system=system_prompt
```

(Solo cambian la firma y el uso del parámetro; el resto del cuerpo queda intacto.)

Run: `pytest tests/test_slideshow_script.py -q` → PASS (nada más cambia).

- [ ] **Step 2: Write the failing tests**

```python
"""Propuesta de temas de un plan (src/plan_temas.py)."""
import json

import pytest

from src import plan_temas, slideshow_script


def _respuesta(n, formato="listicle"):
    return json.dumps({"temas": [
        {"titulo": f"tema {i}", "formato": formato, "hook": f"gancho {i}",
         "fuente": "prompt", "url": None}
        for i in range(n)
    ]})


def test_extraer_temas_tolera_fences():
    data = plan_temas.extraer_temas("```json\n" + _respuesta(2) + "\n```")
    assert data is not None and len(data["temas"]) == 2


def test_extraer_temas_none_si_no_hay_json():
    assert plan_temas.extraer_temas("no hay nada") is None


def test_validar_temas_detecta_titulo_vacio():
    data = {"temas": [{"titulo": " ", "formato": "listicle", "hook": "h"}]}
    errores = plan_temas.validar_temas(data, formatos=["listicle"])
    assert any("titulo" in e for e in errores)


def test_validar_temas_lista_vacia_es_error():
    assert plan_temas.validar_temas({"temas": []}, formatos=["listicle"])


def test_proponer_normaliza_formato_desconocido(monkeypatch):
    crudo = json.dumps({"temas": [{"titulo": "t", "formato": "inventado",
                                   "hook": "h", "fuente": "prompt", "url": None}]})
    monkeypatch.setattr(slideshow_script, "_llamar_llm", lambda *a, **k: crudo)
    temas = plan_temas.proponer("objetivo largo del plan", n=1, formatos=["listicle", "libre"])
    assert temas[0]["formato"] == "listicle"


def test_proponer_trunca_a_n(monkeypatch):
    monkeypatch.setattr(slideshow_script, "_llamar_llm",
                        lambda *a, **k: _respuesta(8))
    temas = plan_temas.proponer("objetivo del plan", n=5, formatos=["listicle"])
    assert len(temas) == 5


def test_proponer_fuente_noticia_solo_con_url_del_banco(monkeypatch):
    crudo = json.dumps({"temas": [
        {"titulo": "t1", "formato": "listicle", "hook": "h",
         "fuente": "noticia", "url": "https://ejemplo.mx/nota"},
        {"titulo": "t2", "formato": "listicle", "hook": "h",
         "fuente": "noticia", "url": "https://otro.mx/inventada"},
    ]})
    monkeypatch.setattr(slideshow_script, "_llamar_llm", lambda *a, **k: crudo)
    noticias = [{"titulo": "nota", "url": "https://ejemplo.mx/nota", "resumen": "r", "id": 7}]
    temas = plan_temas.proponer("objetivo", n=2, formatos=["listicle"], noticias=noticias)
    assert temas[0]["fuente"] == "noticia" and temas[0]["url"] == "https://ejemplo.mx/nota"
    # URL que no está en el banco de noticias → cae a 'prompt' sin URL (anti-alucinación)
    assert temas[1]["fuente"] == "prompt" and temas[1]["url"] is None


def test_proponer_reintenta_con_errores(monkeypatch):
    respuestas = iter(["esto no es json", _respuesta(3)])
    monkeypatch.setattr(slideshow_script, "_llamar_llm",
                        lambda *a, **k: next(respuestas))
    temas = plan_temas.proponer("objetivo", n=3, formatos=["listicle"])
    assert len(temas) == 3


def test_proponer_revienta_tras_3_intentos(monkeypatch):
    monkeypatch.setattr(slideshow_script, "_llamar_llm", lambda *a, **k: "basura")
    with pytest.raises(RuntimeError):
        plan_temas.proponer("objetivo", n=3, formatos=["listicle"])
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_plan_temas.py -v`
Expected: FAIL (`ModuleNotFoundError: src.plan_temas`)

- [ ] **Step 4: Write the implementation** — `src/plan_temas.py`:

```python
"""Propuesta de temas de un plan de contenido: UNA llamada LLM → N temas curables.

Fase barata del plan masivo (spec 2026-08-28): antes de gastar imágenes y
renders, el LLM propone titulares + ganchos que el usuario cura en el portal.
Clona el patrón de slideshow_script (JSON estricto, extraer/validar puros,
3 intentos reinyectando errores) y reusa su `_llamar_llm` con system prompt
propio.

Anti-alucinación de noticias: un tema solo puede citar una URL que venga del
banco de noticias entregado; cualquier otra URL se degrada a fuente 'prompt'.
"""
from __future__ import annotations

import json
import re
from typing import Any

from src import slideshow_script

SYSTEM_PROMPT_TEMAS = """\
Eres estratega de contenido para redes sociales. Te dan el OBJETIVO de un plan
(semanal o mensual) de una marca y, a veces, un banco de NOTICIAS recientes.
Propones una lista de temas DIVERSOS para carruseles de imágenes.

Devuelve ÚNICAMENTE un objeto JSON válido con este esquema EXACTO:
{"temas": [{"titulo": str, "formato": str, "hook": str,
            "fuente": "prompt"|"noticia", "url": str|null}]}

Reglas:
- "titulo": el tema del carrusel, concreto y con gancho, máximo 15 palabras.
- "formato": UNO de los formatos permitidos que te listan.
- "hook": el ángulo/gancho sugerido para el primer slide, máximo 12 palabras.
- "fuente": "noticia" SOLO si el tema sale de una noticia del banco (y entonces
  "url" es la URL EXACTA de esa noticia, copiada tal cual); si no, "prompt" y
  "url" null.
- Temas variados entre sí: nada de 5 variaciones del mismo ángulo.
- Español de México."""


def extraer_temas(texto: str) -> dict[str, Any] | None:
    """Primer objeto JSON en la respuesta (tolera ```json ...```). PURO."""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def validar_temas(data: dict[str, Any], *, formatos: list[str]) -> list[str]:
    """Errores del lote de temas; [] = válido. PURO.

    El conteo NO se valida aquí (el caller trunca a n; pedir el número exacto
    al LLM quema reintentos — lección del bug de slides 2026-08-28). El formato
    desconocido tampoco es error: se normaliza en `proponer`.
    """
    errores: list[str] = []
    temas = data.get("temas")
    if not isinstance(temas, list) or not temas:
        return ["temas: debe ser una lista con al menos 1 tema"]
    for i, t in enumerate(temas):
        if not isinstance(t, dict):
            errores.append(f"tema {i}: no es objeto")
            continue
        if not (t.get("titulo") or "").strip():
            errores.append(f"tema {i}: titulo vacío")
        if not (t.get("hook") or "").strip():
            errores.append(f"tema {i}: hook vacío")
    return errores


def _build_user_prompt(objetivo: str, n: int, formatos: list[str],
                       contexto: str | None, noticias: list[dict[str, Any]],
                       errores_previos: list[str]) -> str:
    partes = [
        f"OBJETIVO DEL PLAN: {objetivo}",
        f"NÚMERO DE TEMAS: {n}",
        f"FORMATOS PERMITIDOS: {', '.join(formatos)}",
    ]
    if contexto:
        partes.append(f"VOZ DE LA MARCA (síguela): {contexto}")
    if noticias:
        lineas = [f"- {t['titulo']} | {t.get('url')}" + (f" | {t['resumen']}" if t.get("resumen") else "")
                  for t in noticias]
        partes.append("BANCO DE NOTICIAS (las únicas URLs citables):\n" + "\n".join(lineas))
    if errores_previos:
        partes.append("Tu respuesta anterior tuvo estos errores, corrígelos:\n"
                      + "\n".join(f"- {e}" for e in errores_previos))
    partes.append("Devuelve SOLO el objeto JSON.")
    return "\n\n".join(partes)


def proponer(objetivo: str, *, n: int, formatos: list[str],
             contexto: str | None = None,
             noticias: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """N temas normalizados, o RuntimeError tras 3 intentos.

    Normalizaciones (no queman reintentos): trunca a n, formato desconocido →
    primer formato permitido, fuente 'noticia' sin URL del banco → 'prompt'.
    """
    if not formatos:
        raise ValueError("formatos no puede estar vacío")
    noticias = noticias or []
    urls_banco = {t.get("url") for t in noticias if t.get("url")}
    errores: list[str] = []
    for _ in range(3):
        prompt = _build_user_prompt(objetivo, n, formatos, contexto, noticias, errores)
        crudo = slideshow_script._llamar_llm(prompt, system_prompt=SYSTEM_PROMPT_TEMAS)
        data = extraer_temas(crudo)
        if data is None:
            errores = ["la respuesta no contenía un objeto JSON válido"]
            continue
        errores = validar_temas(data, formatos=formatos)
        if errores:
            continue
        limpios: list[dict[str, Any]] = []
        for t in data["temas"][:n]:
            formato = t.get("formato") if t.get("formato") in formatos else formatos[0]
            url = t.get("url")
            if t.get("fuente") == "noticia" and url in urls_banco:
                fuente = "noticia"
            else:
                fuente, url = "prompt", None
            limpios.append({"titulo": t["titulo"].strip(), "formato": formato,
                            "hook": (t.get("hook") or "").strip(),
                            "fuente": fuente, "url": url})
        return limpios
    raise RuntimeError(f"El LLM no produjo temas válidos en 3 intentos: {errores}")
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_plan_temas.py tests/test_slideshow_script.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/plan_temas.py src/slideshow_script.py tests/test_plan_temas.py
git commit -m "feat(planes): propuesta de temas con una llamada LLM (src/plan_temas.py)"
```

---

### Task 5: `src/planes.py` — dominio del plan (CRUD, gates, transiciones)

**Files:**
- Create: `src/planes.py`
- Test: `tests/test_planes.py`

**Interfaces:**
- Consumes: `db.insert/update/get/rows`, tablas del Task 1.
- Produces:
  - `validar_periodo(tipo_periodo: str, periodo: str) -> bool` (PURO)
  - `crear(cx, account_id, *, tipo_periodo, periodo, objetivo, config: dict, creado_por) -> int`
  - `listar(cx, account_id) -> list[dict]` (con conteos `topics_total`, `topics_aprobados`, `piezas`, `piezas_pendientes`)
  - `detalle(cx, plan_id) -> dict | None` (plan + `topics` + `piezas` resumen)
  - `agregar_topic(cx, plan_id, *, titulo, formato=None, hook=None) -> int`
  - `editar_topic(cx, topic_id, **campos) -> None` (ValueError `"estado"` si ya generó)
  - `config_de(fila: dict) -> dict` (PURO, json tolerante)

- [ ] **Step 1: Write the failing tests**

```python
"""Dominio de planes de contenido (src/planes.py)."""
import pytest

from src import db, planes


@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _plan(cx, **extra):
    base = dict(tipo_periodo="semana", periodo="2026-W36",
                objetivo="crecer awareness", config={"n_piezas": 3}, creado_por=None)
    base.update(extra)
    return planes.crear(cx, 1, **base)


def test_validar_periodo():
    assert planes.validar_periodo("semana", "2026-W36")
    assert planes.validar_periodo("mes", "2026-09")
    assert not planes.validar_periodo("semana", "2026-09")
    assert not planes.validar_periodo("mes", "2026-W36")
    assert not planes.validar_periodo("mes", "septiembre")


def test_crear_y_detalle(cx):
    pid = _plan(cx)
    d = planes.detalle(cx, pid)
    assert d["estado"] == "proponiendo"
    assert d["topics"] == [] and d["piezas"] == []
    assert planes.config_de(d)["n_piezas"] == 3


def test_listar_con_conteos(cx):
    pid = _plan(cx)
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="a", estado="aprobado")
    db.insert(cx, "plan_topics", plan_id=pid, orden=1, titulo="b")
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
                    caption="c", imagen_url="[]", plan_id=pid, aprobacion="pendiente")
    db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
              caption="d", imagen_url="[]", plan_id=pid, status="descartado")
    fila = planes.listar(cx, 1)[0]
    assert fila["id"] == pid
    assert fila["topics_total"] == 2 and fila["topics_aprobados"] == 1
    assert fila["piezas"] == 1 and fila["piezas_pendientes"] == 1
    assert qid  # la descartada no cuenta


def test_agregar_topic_manual_nace_aprobado(cx):
    pid = _plan(cx)
    tid = planes.agregar_topic(cx, pid, titulo="tema manual", hook="gancho")
    t = db.get(cx, "plan_topics", tid)
    assert t["estado"] == "aprobado" and t["fuente"] == "manual" and t["orden"] == 0
    tid2 = planes.agregar_topic(cx, pid, titulo="otro")
    assert db.get(cx, "plan_topics", tid2)["orden"] == 1


def test_editar_topic_bloquea_generados(cx):
    pid = _plan(cx)
    tid = planes.agregar_topic(cx, pid, titulo="t")
    planes.editar_topic(cx, tid, titulo="t2", estado="descartado")
    assert db.get(cx, "plan_topics", tid)["titulo"] == "t2"
    db.update(cx, "plan_topics", tid, estado="generado", queue_id=99)
    with pytest.raises(ValueError, match="estado"):
        planes.editar_topic(cx, tid, titulo="t3")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_planes.py -v`
Expected: FAIL (`ModuleNotFoundError: src.planes`)

- [ ] **Step 3: Write the implementation** — `src/planes.py`:

```python
"""Dominio de planes de contenido masivo (spec 2026-08-28).

Transiciones de content_plans.estado (nadie más las mueve):
  'proponiendo' → job plan.proponer_temas → 'temas' | 'error'
  'temas'       → POST /plans/{id}/generar → job plan.generar → 'generando'
  'generando'   → fin del job → 'curacion' (≥1 pieza) | 'error' (0 piezas)
  'curacion'    → POST /plans/{id}/aprobar con 0 pendientes restantes → 'aprobado'

plan_topics.estado: 'propuesto' → 'aprobado'|'descartado' (curación de temas),
'aprobado' → 'generado'|'error' (job plan.generar). Un topic con queue_id ya
no se edita: su pieza vive en content_queue y se cura allá.
"""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from src import db

_RE_SEMANA = re.compile(r"^\d{4}-W\d{2}$")
_RE_MES = re.compile(r"^\d{4}-\d{2}$")


def validar_periodo(tipo_periodo: str, periodo: str) -> bool:
    """'semana' ↔ '2026-W36', 'mes' ↔ '2026-09' (formato de segments.ventana_de). PURO."""
    if tipo_periodo == "semana":
        return bool(_RE_SEMANA.match(periodo))
    if tipo_periodo == "mes":
        return bool(_RE_MES.match(periodo))
    return False


def config_de(fila: dict[str, Any]) -> dict[str, Any]:
    """config_json → dict, tolerante a NULL/basura. PURO."""
    try:
        val = json.loads(fila.get("config_json") or "{}")
        return val if isinstance(val, dict) else {}
    except ValueError:
        return {}


def crear(cx: sqlite3.Connection, account_id: int, *, tipo_periodo: str,
          periodo: str, objetivo: str, config: dict[str, Any],
          creado_por: int | None) -> int:
    if not validar_periodo(tipo_periodo, periodo):
        raise ValueError("periodo")
    return db.insert(cx, "content_plans", account_id=account_id,
                     tipo_periodo=tipo_periodo, periodo=periodo,
                     objetivo=objetivo.strip(),
                     config_json=json.dumps(config, ensure_ascii=False),
                     creado_por=creado_por)


_SQL_CONTEOS = """
    SELECT p.*,
           (SELECT COUNT(*) FROM plan_topics t WHERE t.plan_id = p.id)
               AS topics_total,
           (SELECT COUNT(*) FROM plan_topics t WHERE t.plan_id = p.id
               AND t.estado = 'aprobado') AS topics_aprobados,
           (SELECT COUNT(*) FROM content_queue q WHERE q.plan_id = p.id
               AND q.status != 'descartado') AS piezas,
           (SELECT COUNT(*) FROM content_queue q WHERE q.plan_id = p.id
               AND q.status != 'descartado' AND q.aprobacion = 'pendiente')
               AS piezas_pendientes
      FROM content_plans p
"""


def listar(cx: sqlite3.Connection, account_id: int) -> list[dict[str, Any]]:
    return db.rows(cx, _SQL_CONTEOS + " WHERE p.account_id = ? ORDER BY p.id DESC",
                   (account_id,))


def detalle(cx: sqlite3.Connection, plan_id: int) -> dict[str, Any] | None:
    filas = db.rows(cx, _SQL_CONTEOS + " WHERE p.id = ?", (plan_id,))
    if not filas:
        return None
    plan = filas[0]
    plan["topics"] = db.rows(
        cx, "SELECT * FROM plan_topics WHERE plan_id = ? ORDER BY orden, id",
        (plan_id,))
    plan["piezas"] = db.rows(
        cx, "SELECT id, tipo, status, aprobacion, caption, imagen_url, "
            "scheduled_datetime, error FROM content_queue "
            "WHERE plan_id = ? AND status != 'descartado' ORDER BY id",
        (plan_id,))
    return plan


def agregar_topic(cx: sqlite3.Connection, plan_id: int, *, titulo: str,
                  formato: str | None = None, hook: str | None = None) -> int:
    """Tema manual: nace 'aprobado' (quien lo escribe a mano ya lo quiere)."""
    siguiente = cx.execute(
        "SELECT COALESCE(MAX(orden) + 1, 0) FROM plan_topics WHERE plan_id = ?",
        (plan_id,)).fetchone()[0]
    return db.insert(cx, "plan_topics", plan_id=plan_id, orden=siguiente,
                     titulo=titulo.strip(), formato=formato, hook=hook,
                     fuente="manual", estado="aprobado")


_TOPIC_EDITABLE = {"titulo", "formato", "hook", "estado"}


def editar_topic(cx: sqlite3.Connection, topic_id: int, **campos: Any) -> None:
    """Edita un topic aún no generado. ValueError('estado') si ya tiene pieza."""
    fila = db.get(cx, "plan_topics", topic_id)
    if fila is None:
        raise ValueError("no_existe")
    if fila.get("queue_id") or fila["estado"] in ("generado",):
        raise ValueError("estado")
    bad = set(campos) - _TOPIC_EDITABLE
    if bad:
        raise ValueError(f"campos no editables: {sorted(bad)}")
    if "estado" in campos and campos["estado"] not in ("aprobado", "descartado"):
        raise ValueError("estado_valor")
    db.update(cx, "plan_topics", topic_id, **campos)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_planes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/planes.py tests/test_planes.py
git commit -m "feat(planes): dominio del plan (crear, listar, detalle, gates de topics)"
```

---

### Task 6: Handlers `plan.proponer_temas` y `plan.generar` (+ fix de `regenerar_slideshow` para piezas de plan)

**Files:**
- Modify: `src/jobs/handlers.py` (dos handlers nuevos + registro en `HANDLERS` + fix en `regenerar_slideshow`)
- Test: `tests/test_jobs_plan.py`

**Interfaces:**
- Consumes: `plan_temas.proponer`, `planes.config_de`, `generate_slideshow.generar(..., notificar_telegram=False)`, `topics.listar/fetch_rss/fetch_newsapi/guardar`, `fuentes_mod.listar`, `jobs.progresar`, `_marca_de`, `_sellar_ultimo_run`.
- Produces: handlers `plan_proponer_temas(cx, job) -> dict` y `plan_generar(cx, job) -> dict`, registrados como `"plan.proponer_temas"` y `"plan.generar"`. Payload de ambos: `{"plan_id": int}`.

- [ ] **Step 1: Write the failing tests**

```python
"""Handlers de jobs de planes (plan.proponer_temas, plan.generar)."""
import json

import pytest

from src import db, jobs, planes
from src.jobs import handlers


@pytest.fixture()
def cx(tmp_path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _job(cx, tipo, plan_id, account_id=1):
    jid = jobs.crear(cx, tipo, account_id, {"plan_id": plan_id})
    fila = jobs.tomar(cx, "w-test")
    assert fila and fila["id"] == jid
    return fila


def _plan(cx, **cfg):
    config = {"n_piezas": 2, "n_slides": 6, "aspect": "4:5",
              "formatos": ["listicle"], "fuentes_info": ["prompt"]}
    config.update(cfg)
    return planes.crear(cx, 1, tipo_periodo="semana", periodo="2026-W36",
                        objetivo="objetivo de prueba", config=config, creado_por=5)


def test_proponer_temas_ok(cx, monkeypatch):
    pid = _plan(cx)
    monkeypatch.setattr(handlers.plan_temas, "proponer",
                        lambda *a, **k: [
                            {"titulo": "t1", "formato": "listicle", "hook": "h1",
                             "fuente": "prompt", "url": None},
                            {"titulo": "t2", "formato": "listicle", "hook": "h2",
                             "fuente": "prompt", "url": None}])
    res = handlers.plan_proponer_temas(cx, _job(cx, "plan.proponer_temas", pid))
    assert res["temas"] == 2
    plan = db.get(cx, "content_plans", pid)
    assert plan["estado"] == "temas"
    topics = db.rows(cx, "SELECT * FROM plan_topics WHERE plan_id = ? ORDER BY orden", (pid,))
    assert [t["titulo"] for t in topics] == ["t1", "t2"]
    assert all(t["estado"] == "propuesto" for t in topics)


def test_proponer_temas_error_marca_plan(cx, monkeypatch):
    pid = _plan(cx)
    def _revienta(*a, **k):
        raise RuntimeError("LLM caído")
    monkeypatch.setattr(handlers.plan_temas, "proponer", _revienta)
    with pytest.raises(RuntimeError):
        handlers.plan_proponer_temas(cx, _job(cx, "plan.proponer_temas", pid))
    assert db.get(cx, "content_plans", pid)["estado"] == "error"


def test_plan_generar_tolerante_a_fallos(cx, monkeypatch):
    pid = _plan(cx)
    db.update(cx, "content_plans", pid, estado="temas")
    t1 = db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="ok",
                   formato="listicle", estado="aprobado")
    t2 = db.insert(cx, "plan_topics", plan_id=pid, orden=1, titulo="falla",
                   formato="listicle", estado="aprobado")
    db.insert(cx, "plan_topics", plan_id=pid, orden=2, titulo="descartado",
              estado="descartado")

    def _generar_fake(cx_, tema, **kwargs):
        assert kwargs["notificar_telegram"] is False
        assert kwargs["creado_por"] == 5
        if tema == "falla":
            raise RuntimeError("pexels caído con key sk-secreta")
        return db.insert(cx_, "content_queue", tipo="slideshow", account_id=1,
                         caption="c", imagen_url="[]", aprobacion="pendiente",
                         origen="api")

    monkeypatch.setattr(handlers.generate_slideshow, "generar", _generar_fake)
    res = handlers.plan_generar(cx, _job(cx, "plan.generar", pid))
    assert res == {"generadas": 1, "fallidas": 1}
    plan = db.get(cx, "content_plans", pid)
    assert plan["estado"] == "curacion"
    f1, f2 = db.get(cx, "plan_topics", t1), db.get(cx, "plan_topics", t2)
    assert f1["estado"] == "generado" and f1["queue_id"]
    assert db.get(cx, "content_queue", f1["queue_id"])["plan_id"] == pid
    assert f2["estado"] == "error" and "falla" not in (f2["error"] or "")  # mensaje, no tema
    assert "sk-secreta" not in (f2["error"] or "")  # jamás filtrar secretos


def test_plan_generar_todo_falla_es_error(cx, monkeypatch):
    pid = _plan(cx)
    db.update(cx, "content_plans", pid, estado="temas")
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="x",
              formato="listicle", estado="aprobado")

    def _revienta(*a, **k):
        raise RuntimeError("todo mal")
    monkeypatch.setattr(handlers.generate_slideshow, "generar", _revienta)
    with pytest.raises(RuntimeError):
        handlers.plan_generar(cx, _job(cx, "plan.generar", pid))
    assert db.get(cx, "content_plans", pid)["estado"] == "error"


def test_plan_generar_exige_estado_temas(cx):
    pid = _plan(cx)  # sigue en 'proponiendo'
    with pytest.raises(ValueError):
        handlers.plan_generar(cx, _job(cx, "plan.generar", pid))


def test_regenerar_preserva_plan_id(cx, monkeypatch):
    pid = _plan(cx)
    qid = db.insert(cx, "content_queue", tipo="slideshow", account_id=1,
                    caption="c", imagen_url="[]", plan_id=pid,
                    slideshow_json=json.dumps({"brief": {"tema": "t", "n_slides": 6}}))
    tid = db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="t",
                    estado="generado", queue_id=qid)
    nuevo = {"valor": None}

    def _generar_fake(cx_, tema, **kwargs):
        nuevo["valor"] = db.insert(cx_, "content_queue", tipo="slideshow",
                                   account_id=1, caption="c2", imagen_url="[]")
        return nuevo["valor"]

    monkeypatch.setattr(handlers.generate_slideshow, "generar", _generar_fake)
    jid = jobs.crear(cx, "slideshow.regenerar", 1, {"queue_id": qid})
    fila = jobs.tomar(cx, "w-test")
    handlers.regenerar_slideshow(cx, fila)
    assert db.get(cx, "content_queue", nuevo["valor"])["plan_id"] == pid
    assert db.get(cx, "plan_topics", tid)["queue_id"] == nuevo["valor"]
    assert jid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_jobs_plan.py -v`
Expected: FAIL (`handlers` no tiene `plan_proponer_temas` ni `plan_temas`)

- [ ] **Step 3: Write the implementation** — en `src/jobs/handlers.py`:

Imports: agregar `plan_temas` y `planes` al bloque `from src import (...)`.

```python
def _redactar(slug: str, msg: str, tope: int = 300) -> str:
    """Mensaje de error sin secretos de la marca, truncado (patrón _error_seguro)."""
    for val in config.account_creds(slug).values():
        if val:
            msg = msg.replace(str(val), "***")
    return msg[:tope]


def _refrescar_fuentes_info(cx: sqlite3.Connection, account_id: int, slug: str) -> None:
    """Fetch inline y best-effort de las fuentes de info de la marca.

    Corre DENTRO de plan.proponer_temas (encolar jobs sourcing.* aquí sería un
    deadlock suave: el aislamiento por cuenta no los correría hasta terminar
    este job). Una fuente rota jamás tumba la propuesta: se sella su error y
    se sigue — el plan puede proponer con lo que ya haya en topic_suggestions.
    """
    for fuente in fuentes_mod.listar(cx, account_id, kind="info"):
        if not fuente.get("activa"):
            continue
        cfg = fuente["config"]
        error: str | None = None
        try:
            if fuente["provider"] == "rss":
                for url in cfg.get("urls", []):
                    try:
                        topics.guardar(cx, account_id, topics.fetch_rss(url), "rss")
                    except Exception as exc:  # noqa: BLE001 — una URL rota no tumba las demás
                        error = _redactar(slug, str(exc))
            elif fuente["provider"] == "newsapi":
                key = config.account_creds(slug).get("NEWSAPI_KEY")
                if not key:
                    error = "Falta NEWSAPI_KEY"
                else:
                    items = topics.fetch_newsapi(cfg["query"], key,
                                                 idioma=cfg.get("idioma", "es"),
                                                 pais=cfg.get("pais"), estricto=True)
                    topics.guardar(cx, account_id, items, "newsapi")
        except Exception as exc:  # noqa: BLE001 — best-effort total
            error = _redactar(slug, str(exc))
        _sellar_ultimo_run(cx, fuente["id"], error)


def _plan_de(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """Plan del payload, validando que pertenece a la cuenta del job."""
    payload = json.loads(job["payload_json"] or "{}")
    plan = db.get(cx, "content_plans", payload["plan_id"])
    if plan is None or plan["account_id"] != job["account_id"]:
        raise ValueError(f"No existe el plan {payload.get('plan_id')} en la cuenta del job")
    return plan


def plan_proponer_temas(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {plan_id}. Objetivo (+noticias) → N temas curables en plan_topics."""
    plan = _plan_de(cx, job)
    slug = _marca_de(cx, job["account_id"])
    m = marcas.cargar_por_id(cx, job["account_id"])
    cfg = planes.config_de(plan)
    try:
        noticias: list[dict[str, Any]] = []
        if "noticias" in (cfg.get("fuentes_info") or []):
            jobs.progresar(cx, job["id"], 15, "refrescando fuentes de noticias")
            _refrescar_fuentes_info(cx, job["account_id"], slug)
            noticias = topics.listar(cx, job["account_id"])[:20]
        jobs.progresar(cx, job["id"], 40, "proponiendo temas")
        temas = plan_temas.proponer(
            plan["objetivo"], n=cfg.get("n_piezas", 10),
            formatos=cfg.get("formatos") or m.formatos or ["listicle"],
            contexto=m.voz or None, noticias=noticias)
    except Exception as exc:
        db.update(cx, "content_plans", plan["id"], estado="error",
                  error=_redactar(slug, str(exc)))
        raise
    por_url = {t["url"]: t["id"] for t in noticias if t.get("url")}
    for i, t in enumerate(temas):
        db.insert(cx, "plan_topics", plan_id=plan["id"], orden=i,
                  titulo=t["titulo"], formato=t["formato"], hook=t["hook"],
                  fuente=t["fuente"], url=t["url"],
                  topic_suggestion_id=por_url.get(t["url"]))
    db.update(cx, "content_plans", plan["id"], estado="temas", error=None)
    jobs.progresar(cx, job["id"], 100, f"{len(temas)} temas propuestos")
    return {"temas": len(temas)}


def plan_generar(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {plan_id}. UN job secuencial: genera una pieza por topic aprobado.

    Tolerante a fallos por pieza (un tema caído no tumba el lote); revienta
    solo si NINGUNA pieza salió. `progresar` por pieza mantiene el heartbeat
    fresco (< 30 min entre latidos → rescatar_huerfanos no lo toca).
    """
    plan = _plan_de(cx, job)
    if plan["estado"] != "temas":
        raise ValueError(f"El plan {plan['id']} no está en 'temas' (está {plan['estado']!r})")
    slug = _marca_de(cx, job["account_id"])
    cfg = planes.config_de(plan)
    aprobados = db.rows(
        cx, "SELECT * FROM plan_topics WHERE plan_id = ? AND estado = 'aprobado' "
            "ORDER BY orden, id", (plan["id"],))
    if not aprobados:
        raise ValueError(f"El plan {plan['id']} no tiene temas aprobados")
    db.update(cx, "content_plans", plan["id"], estado="generando", error=None)

    generadas = 0
    for i, t in enumerate(aprobados):
        jobs.progresar(cx, job["id"], int(5 + 90 * i / len(aprobados)),
                       f"pieza {i + 1}/{len(aprobados)}: {t['titulo'][:40]}")
        contexto = f"Objetivo del plan: {plan['objetivo']}"
        if t.get("hook"):
            contexto += f"\nÁngulo/gancho sugerido para el hook: {t['hook']}"
        fuentes_img = cfg.get("fuentes_imagen")
        try:
            qid = generate_slideshow.generar(
                cx, t["titulo"], marca=slug, formato=t.get("formato") or None,
                estilo=cfg.get("estilo"),
                fuentes=tuple(fuentes_img) if fuentes_img else None,
                n_slides=cfg.get("n_slides", 6), aspect=cfg.get("aspect", "4:5"),
                contexto=contexto, creado_por=plan.get("creado_por"),
                topic_id=t.get("topic_suggestion_id"), notificar_telegram=False)
            db.update(cx, "content_queue", qid, plan_id=plan["id"])
            db.update(cx, "plan_topics", t["id"], estado="generado",
                      queue_id=qid, error=None)
            generadas += 1
        except Exception as exc:  # noqa: BLE001 — una pieza caída no tumba el lote
            db.update(cx, "plan_topics", t["id"], estado="error",
                      error=_redactar(slug, str(exc)))

    fallidas = len(aprobados) - generadas
    if generadas == 0:
        db.update(cx, "content_plans", plan["id"], estado="error",
                  error="ninguna pieza se generó")
        raise RuntimeError(f"plan {plan['id']}: las {fallidas} piezas fallaron")
    db.update(cx, "content_plans", plan["id"], estado="curacion")
    jobs.progresar(cx, job["id"], 100, f"{generadas} piezas generadas, {fallidas} fallidas")
    return {"generadas": generadas, "fallidas": fallidas}
```

En `regenerar_slideshow`, después de `db.update(cx, "jobs", job["id"], queue_id=nuevo_qid)` agregar:

```python
    # Piezas de un plan: la fila nueva hereda el plan y el topic apunta a ella
    # (si no, el plan "pierde" la pieza al regenerarla desde el portal).
    if fila.get("plan_id"):
        db.update(cx, "content_queue", nuevo_qid, plan_id=fila["plan_id"])
        for t in db.rows(cx, "SELECT id FROM plan_topics WHERE queue_id = ?",
                         (queue_id,)):
            db.update(cx, "plan_topics", t["id"], queue_id=nuevo_qid)
```

Registrar en `HANDLERS`:

```python
    "plan.proponer_temas": plan_proponer_temas,
    "plan.generar": plan_generar,
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_jobs_plan.py tests/test_jobs_handlers.py tests/test_jobs.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/jobs/handlers.py tests/test_jobs_plan.py
git commit -m "feat(planes): jobs plan.proponer_temas y plan.generar (lote tolerante a fallos)"
```

---

### Task 7: API — `api/routers/planes.py` + registro + docs

**Files:**
- Create: `api/routers/planes.py`
- Modify: `api/app.py:56-65` (import + `include_router`)
- Modify: `docs/api_portal.md` (sección nueva "Planes" — describir los 7 endpoints con una línea cada uno, siguiendo el formato de las secciones existentes)
- Test: `tests/test_api_planes.py`

**Interfaces:**
- Consumes: `planes.*` (Task 5), `jobs.crear`, `approval.aprobar(cx, qid, user_id=...) -> datetime`, `marca_para`, `ApiError/no_encontrado/conflicto`, `marcas.cargar_por_id`, `slideshow_model.ASPECT_RATIOS`, `config.SLIDESHOW_FORMATOS`.
- Produces: endpoints bajo `/brands/{slug}`: `POST /plans`, `GET /plans`, `GET /plans/{pid}`, `POST /plans/{pid}/topics`, `PATCH /plans/{pid}/topics/{tid}`, `POST /plans/{pid}/generar`, `POST /plans/{pid}/aprobar`. Respuestas exactas en el código de abajo.

- [ ] **Step 1: Write the failing tests** (usar la fixture existente `api_cliente` de `tests/conftest.py`, que devuelve `(TestClient, cx, H)` con `H.usuario(email, admin=..., marcas=[...])` y `H.login(uid)`)

```python
"""API de planes de contenido masivo."""
import json

from src import db, planes


def _login_editor(api_cliente):
    client, cx, H = api_cliente
    uid = H.usuario("editor@x.mx", marcas=[(1, "editor")])
    H.login(uid)
    return client, cx, uid


def _payload():
    return {"tipo_periodo": "semana", "periodo": "2026-W36",
            "objetivo": "crecer awareness con contenido local",
            "n_piezas": 3, "fuentes_info": ["prompt"]}


def test_crear_plan_encola_job(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    r = client.post("/brands/gdlscene/plans", json=_payload())
    assert r.status_code == 202, r.text
    body = r.json()
    plan = db.get(cx, "content_plans", body["plan_id"])
    assert plan["estado"] == "proponiendo" and plan["creado_por"] == uid
    job = db.get(cx, "jobs", body["job_id"])
    assert job["tipo"] == "plan.proponer_temas"
    assert json.loads(job["payload_json"])["plan_id"] == body["plan_id"]


def test_crear_plan_valida_periodo_y_topes(api_cliente):
    client, cx, _ = _login_editor(api_cliente)
    malo = dict(_payload(), periodo="2026-09")     # semana con formato de mes
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422
    malo = dict(_payload(), n_piezas=31)
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422
    malo = dict(_payload(), aspect="3:2")
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422
    malo = dict(_payload(), formatos=["inexistente"])
    assert client.post("/brands/gdlscene/plans", json=malo).status_code == 422


def test_marca_ajena_404(api_cliente):
    client, cx, H = api_cliente
    uid = H.usuario("ajeno@x.mx", marcas=[])
    H.login(uid)
    assert client.get("/brands/gdlscene/plans").status_code in (403, 404)


def test_listar_y_detalle(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="t")
    lista = client.get("/brands/gdlscene/plans").json()
    assert lista[0]["id"] == pid and lista[0]["topics_total"] == 1
    det = client.get(f"/brands/gdlscene/plans/{pid}").json()
    assert len(det["topics"]) == 1 and det["piezas"] == []


def test_curar_topics(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.update(cx, "content_plans", pid, estado="temas")
    tid = db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="t")
    r = client.patch(f"/brands/gdlscene/plans/{pid}/topics/{tid}",
                     json={"estado": "aprobado", "titulo": "t mejorado"})
    assert r.status_code == 200
    assert db.get(cx, "plan_topics", tid)["estado"] == "aprobado"
    r = client.post(f"/brands/gdlscene/plans/{pid}/topics",
                    json={"titulo": "manual nuevo"})
    assert r.status_code == 201
    # topic ya generado no se edita
    db.update(cx, "plan_topics", tid, estado="generado", queue_id=1)
    r = client.patch(f"/brands/gdlscene/plans/{pid}/topics/{tid}",
                     json={"titulo": "no"})
    assert r.status_code == 422


def test_generar_gates(api_cliente):
    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    # aún 'proponiendo' → 422
    assert client.post(f"/brands/gdlscene/plans/{pid}/generar").status_code == 422
    db.update(cx, "content_plans", pid, estado="temas")
    # sin temas aprobados → 422
    assert client.post(f"/brands/gdlscene/plans/{pid}/generar").status_code == 422
    db.insert(cx, "plan_topics", plan_id=pid, orden=0, titulo="t", estado="aprobado")
    r = client.post(f"/brands/gdlscene/plans/{pid}/generar")
    assert r.status_code == 202 and "job_id" in r.json()
    # job vivo → 409
    assert client.post(f"/brands/gdlscene/plans/{pid}/generar").status_code == 409


def test_aprobar_lote(api_cliente, monkeypatch):
    from datetime import datetime

    from src import approval

    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.update(cx, "content_plans", pid, estado="curacion")
    q1 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="a",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")
    q2 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="b",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")

    aprobadas = []

    def _aprobar_fake(cx_, qid, **kwargs):
        if qid == q2:
            raise ValueError("sin slots")
        aprobadas.append(qid)
        db.update(cx_, "content_queue", qid, aprobacion="aprobado", status="programado")
        return datetime(2026, 9, 1, 11, 0)

    monkeypatch.setattr(approval, "aprobar", _aprobar_fake)
    r = client.post(f"/brands/gdlscene/plans/{pid}/aprobar", json={})
    assert r.status_code == 200
    body = r.json()
    assert [a["queue_id"] for a in body["aprobadas"]] == [q1]
    assert body["fallidas"] == [q2]
    assert body["plan_estado"] == "curacion"  # queda 1 pendiente (la fallida)
    # segunda pasada: la fallida ahora sí
    def _aprobar_ok(cx_, qid, **kwargs):
        db.update(cx_, "content_queue", qid, aprobacion="aprobado", status="programado")
        return datetime(2026, 9, 1, 15, 0)
    monkeypatch.setattr(approval, "aprobar", _aprobar_ok)
    body = client.post(f"/brands/gdlscene/plans/{pid}/aprobar", json={}).json()
    assert body["plan_estado"] == "aprobado"
    assert db.get(cx, "content_plans", pid)["estado"] == "aprobado"


def test_aprobar_subset(api_cliente, monkeypatch):
    from datetime import datetime

    from src import approval

    client, cx, uid = _login_editor(api_cliente)
    pid = planes.crear(cx, 1, tipo_periodo="mes", periodo="2026-09",
                       objetivo="obj", config={}, creado_por=uid)
    db.update(cx, "content_plans", pid, estado="curacion")
    q1 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="a",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")
    q2 = db.insert(cx, "content_queue", tipo="slideshow", account_id=1, caption="b",
                   imagen_url="[]", plan_id=pid, aprobacion="pendiente", origen="api")
    monkeypatch.setattr(approval, "aprobar",
                        lambda cx_, qid, **k: datetime(2026, 9, 1, 11, 0))
    body = client.post(f"/brands/gdlscene/plans/{pid}/aprobar",
                       json={"queue_ids": [q1]}).json()
    assert [a["queue_id"] for a in body["aprobadas"]] == [q1]
    assert q2 not in [a["queue_id"] for a in body["aprobadas"]]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_planes.py -v`
Expected: FAIL (404 en todas las rutas — el router no existe)

- [ ] **Step 3: Write the implementation** — `api/routers/planes.py`:

```python
"""Planes de contenido masivo del portal (spec 2026-08-28).

Ciclo: crear (objetivo → job de temas) → curar temas → generar (job de lote)
→ curar piezas con los endpoints de cola existentes → aprobar en bloque aquí
(server-side: el bucle de N requests del cliente era el cuello de la biblioteca).
"""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import config
from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, conflicto, no_encontrado
from src import approval, db, jobs, marcas, planes, slideshow_model

router = APIRouter(prefix="/brands/{slug}", tags=["planes"])

# Fuentes de imagen que el motor conoce (src/image_sources.py); la validación
# fina (keys presentes, flags) la hace el propio motor al generar.
_FUENTES_IMAGEN = {"banco", "covers", "carpeta", "pexels", "unsplash", "pinterest"}


class NuevoPlan(BaseModel):
    tipo_periodo: Literal["semana", "mes"]
    periodo: str = Field(min_length=6, max_length=8)
    objetivo: str = Field(min_length=10, max_length=2000)
    n_piezas: int = Field(10, ge=1, le=30)
    n_slides: int = Field(6, ge=1, le=10)
    aspect: str = "4:5"
    estilo: str | None = None
    formatos: list[str] | None = None
    fuentes_imagen: list[str] | None = None
    fuentes_info: list[Literal["prompt", "noticias"]] = ["prompt"]


class NuevoTopic(BaseModel):
    titulo: str = Field(min_length=3, max_length=200)
    formato: str | None = None
    hook: str | None = Field(None, max_length=300)


class EditarTopic(BaseModel):
    titulo: str | None = Field(None, min_length=3, max_length=200)
    formato: str | None = None
    hook: str | None = Field(None, max_length=300)
    estado: Literal["aprobado", "descartado"] | None = None


class AprobarPlan(BaseModel):
    queue_ids: list[int] | None = None


def _plan_de_marca(cx, account_id: int, pid: int) -> dict:
    plan = planes.detalle(cx, pid)
    if plan is None or plan["account_id"] != account_id:
        raise no_encontrado("ese plan")
    return plan


def _job_vivo_de(cx, pid: int) -> int | None:
    fila = cx.execute(
        "SELECT id FROM jobs WHERE tipo IN ('plan.proponer_temas', 'plan.generar') "
        "AND estado IN ('cola', 'corriendo') "
        "AND json_extract(payload_json, '$.plan_id') = ? LIMIT 1", (pid,)).fetchone()
    return fila["id"] if fila else None


@router.post("/plans", status_code=202)
def crear_plan(slug: str, datos: NuevoPlan, user: dict = Depends(usuario_actual),
               cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    if not planes.validar_periodo(datos.tipo_periodo, datos.periodo):
        raise ApiError(422, "validacion",
                       "El periodo no coincide con el tipo (semana: 2026-W36, mes: 2026-09)",
                       "periodo")
    if datos.aspect not in slideshow_model.ASPECT_RATIOS:
        raise ApiError(422, "validacion", "Aspecto desconocido", "aspect")
    m = marcas.cargar_por_id(cx, fila["id"])
    permitidos = m.formatos or list(config.SLIDESHOW_FORMATOS)
    if datos.formatos:
        malos = set(datos.formatos) - set(permitidos)
        if malos:
            raise ApiError(422, "validacion",
                           f"Formatos no habilitados para la marca: {sorted(malos)}",
                           "formatos")
    if datos.fuentes_imagen:
        malas = set(datos.fuentes_imagen) - _FUENTES_IMAGEN
        if malas:
            raise ApiError(422, "validacion",
                           f"Fuentes de imagen desconocidas: {sorted(malas)}",
                           "fuentes_imagen")
    if datos.estilo and datos.estilo not in marcas.estilos_de(m):
        raise ApiError(422, "validacion", "Ese estilo no existe para la marca", "estilo")

    cfg = {"n_piezas": datos.n_piezas, "n_slides": datos.n_slides,
           "aspect": datos.aspect, "estilo": datos.estilo,
           "formatos": datos.formatos or permitidos,
           "fuentes_imagen": datos.fuentes_imagen,
           "fuentes_info": datos.fuentes_info}
    pid = planes.crear(cx, fila["id"], tipo_periodo=datos.tipo_periodo,
                       periodo=datos.periodo, objetivo=datos.objetivo,
                       config=cfg, creado_por=user["id"])
    job_id = jobs.crear(cx, "plan.proponer_temas", fila["id"], {"plan_id": pid},
                        creado_por=user["id"])
    return {"plan_id": pid, "job_id": job_id}


@router.get("/plans")
def listar_planes(slug: str, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    return planes.listar(cx, fila["id"])


@router.get("/plans/{pid}")
def detalle_plan(slug: str, pid: int, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    plan["job_id"] = _job_vivo_de(cx, pid)
    return plan


@router.post("/plans/{pid}/topics", status_code=201)
def agregar_topic(slug: str, pid: int, datos: NuevoTopic,
                  user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    if plan["estado"] not in ("temas", "curacion"):
        raise ApiError(422, "validacion",
                       "Solo se pueden agregar temas con el plan en curación de temas",
                       "estado")
    tid = planes.agregar_topic(cx, pid, titulo=datos.titulo,
                               formato=datos.formato, hook=datos.hook)
    return db.get(cx, "plan_topics", tid)


@router.patch("/plans/{pid}/topics/{tid}")
def editar_topic(slug: str, pid: int, tid: int, datos: EditarTopic,
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    _plan_de_marca(cx, fila["id"], pid)
    topic = db.get(cx, "plan_topics", tid)
    if topic is None or topic["plan_id"] != pid:
        raise no_encontrado("ese tema")
    campos = {k: v for k, v in datos.model_dump().items() if v is not None}
    if not campos:
        return topic
    try:
        planes.editar_topic(cx, tid, **campos)
    except ValueError:
        raise ApiError(422, "validacion",
                       "Ese tema ya generó su pieza y no se puede editar") from None
    return db.get(cx, "plan_topics", tid)


@router.post("/plans/{pid}/generar", status_code=202)
def generar_plan(slug: str, pid: int, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    if plan["estado"] != "temas":
        raise ApiError(422, "validacion",
                       "El plan no está en curación de temas", "estado")
    if plan["topics_aprobados"] == 0:
        raise ApiError(422, "validacion", "No hay temas aprobados que generar")
    if _job_vivo_de(cx, pid):
        raise conflicto("Este plan ya tiene un trabajo en curso")
    job_id = jobs.crear(cx, "plan.generar", fila["id"], {"plan_id": pid},
                        creado_por=user["id"])
    return {"job_id": job_id}


@router.post("/plans/{pid}/aprobar")
def aprobar_plan(slug: str, pid: int, datos: AprobarPlan,
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    """Aprobación en lote server-side: cada pieza toma su siguiente slot libre."""
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    if plan["estado"] not in ("curacion", "aprobado"):
        raise ApiError(422, "validacion", "El plan no está en curación", "estado")
    pendientes = [p["id"] for p in plan["piezas"] if p["aprobacion"] == "pendiente"]
    if datos.queue_ids is not None:
        elegidas = set(datos.queue_ids)
        pendientes = [qid for qid in pendientes if qid in elegidas]

    aprobadas, fallidas = [], []
    for qid in pendientes:
        try:
            slot = approval.aprobar(cx, qid, user_id=user["id"])
            aprobadas.append({"queue_id": qid, "slot": slot.isoformat()})
        except (ValueError, RuntimeError):
            fallidas.append(qid)

    restantes = cx.execute(
        "SELECT COUNT(*) FROM content_queue WHERE plan_id = ? "
        "AND status != 'descartado' AND aprobacion = 'pendiente'", (pid,)).fetchone()[0]
    estado = plan["estado"]
    if restantes == 0 and aprobadas:
        db.update(cx, "content_plans", pid, estado="aprobado")
        estado = "aprobado"
    return {"aprobadas": aprobadas, "fallidas": fallidas, "plan_estado": estado}
```

En `api/app.py`: agregar `planes` al import de routers y `app.include_router(planes.router)` junto a los demás.

En `docs/api_portal.md`: sección `## Planes` con una línea por endpoint (mismo formato de las secciones existentes del archivo).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_api_planes.py tests/test_api_cola.py tests/test_api_trabajos.py -v && ruff check src/ tests/ api/`
Expected: PASS y ruff limpio

- [ ] **Step 5: Commit**

```bash
git add api/routers/planes.py api/app.py docs/api_portal.md tests/test_api_planes.py
git commit -m "feat(planes): API del portal (crear, curar temas, generar, aprobar lote server-side)"
```

---

### Task 8: Front — hook `use-plans.ts`

**Files:**
- Create: `frontend/hooks/use-plans.ts`
- Reference (leer antes, para copiar el patrón exacto de imports/QueryClient): `frontend/hooks/use-queue.ts`, `frontend/lib/api.ts`

**Interfaces:**
- Consumes: `get/post/patch` de `frontend/lib/api.ts`.
- Produces: tipos `Plan`, `PlanDetail`, `PlanTopic`, `PiezaPlan` y hooks `usePlans(slug)`, `usePlan(slug, pid)`, `useCrearPlan(slug)`, `useAgregarTopic(slug, pid)`, `useEditarTopic(slug, pid)`, `useGenerarPlan(slug, pid)`, `useAprobarPlan(slug, pid)`.

- [ ] **Step 1: Write the implementation** (no hay framework de tests en el front; la verificación es `pnpm lint` + `pnpm build` + uso en Tasks 9-10)

```typescript
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { get, patch, post } from "@/lib/api";

export interface PlanTopic {
  id: number;
  orden: number;
  titulo: string;
  formato: string | null;
  hook: string | null;
  fuente: "prompt" | "noticia" | "manual";
  url: string | null;
  estado: "propuesto" | "aprobado" | "descartado" | "generado" | "error";
  error: string | null;
  queue_id: number | null;
}

export interface PiezaPlan {
  id: number;
  tipo: string;
  status: string;
  aprobacion: string | null;
  caption: string | null;
  imagen_url: string | null;
  scheduled_datetime: string | null;
  error: string | null;
}

export interface Plan {
  id: number;
  tipo_periodo: "semana" | "mes";
  periodo: string;
  objetivo: string;
  estado: "proponiendo" | "temas" | "generando" | "curacion" | "aprobado" | "error";
  error: string | null;
  config_json: string | null;
  created_at: string;
  topics_total: number;
  topics_aprobados: number;
  piezas: number;
  piezas_pendientes: number;
}

export interface PlanDetail extends Omit<Plan, "piezas"> {
  topics: PlanTopic[];
  piezas: PiezaPlan[];
  job_id: number | null;
}

export interface NuevoPlan {
  tipo_periodo: "semana" | "mes";
  periodo: string;
  objetivo: string;
  n_piezas: number;
  n_slides?: number;
  aspect?: string;
  estilo?: string | null;
  formatos?: string[] | null;
  fuentes_imagen?: string[] | null;
  fuentes_info?: ("prompt" | "noticias")[];
}

export function usePlans(slug: string) {
  return useQuery<Plan[]>({
    queryKey: ["plans", slug],
    queryFn: () => get(`/brands/${slug}/plans`),
  });
}

export function usePlan(slug: string, pid: number, opts?: { refetchInterval?: number | false }) {
  return useQuery<PlanDetail>({
    queryKey: ["plans", slug, pid],
    queryFn: () => get(`/brands/${slug}/plans/${pid}`),
    refetchInterval: opts?.refetchInterval ?? false,
  });
}

function useInvalidarPlanes(slug: string, pid?: number) {
  const qc = useQueryClient();
  return () => {
    qc.invalidateQueries({ queryKey: ["plans", slug] });
    if (pid) qc.invalidateQueries({ queryKey: ["plans", slug, pid] });
    qc.invalidateQueries({ queryKey: ["queue", slug] });
  };
}

export function useCrearPlan(slug: string) {
  const invalidar = useInvalidarPlanes(slug);
  return useMutation({
    mutationFn: (datos: NuevoPlan) =>
      post<{ plan_id: number; job_id: number }>(`/brands/${slug}/plans`, datos),
    onSuccess: invalidar,
  });
}

export function useAgregarTopic(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: (datos: { titulo: string; formato?: string | null; hook?: string | null }) =>
      post(`/brands/${slug}/plans/${pid}/topics`, datos),
    onSuccess: invalidar,
  });
}

export function useEditarTopic(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: ({ tid, ...datos }: { tid: number; titulo?: string; hook?: string;
                                      formato?: string; estado?: "aprobado" | "descartado" }) =>
      patch(`/brands/${slug}/plans/${pid}/topics/${tid}`, datos),
    onSuccess: invalidar,
  });
}

export function useGenerarPlan(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: () => post<{ job_id: number }>(`/brands/${slug}/plans/${pid}/generar`, {}),
    onSuccess: invalidar,
  });
}

export function useAprobarPlan(slug: string, pid: number) {
  const invalidar = useInvalidarPlanes(slug, pid);
  return useMutation({
    mutationFn: (datos: { queue_ids?: number[] }) =>
      post<{ aprobadas: { queue_id: number; slot: string }[]; fallidas: number[];
             plan_estado: string }>(`/brands/${slug}/plans/${pid}/aprobar`, datos),
    onSuccess: invalidar,
  });
}
```

Nota para el ejecutor: ANTES de guardar, leer `frontend/hooks/use-queue.ts` y ajustar los nombres de los helpers HTTP (`get/post/patch`) y sus genéricos al patrón EXACTO de ese archivo (si `lib/api.ts` exporta `api.get` en vez de `get`, seguir al archivo real, no a este plan).

- [ ] **Step 2: Verify**

Run: `cd frontend && pnpm lint`
Expected: sin errores nuevos

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/use-plans.ts
git commit -m "feat(portal): hook use-plans (planes de contenido masivo)"
```

---

### Task 9: Front — lista de planes y diálogo de creación (`/b/[slug]/plans`)

**Files:**
- Create: `frontend/app/b/[slug]/plans/page.tsx`
- Create: `frontend/app/b/[slug]/plans/_components/nuevo-plan-dialog.tsx`
- Modify: `frontend/app/b/[slug]/layout.tsx` (entrada `Planes` en el arreglo `NAV`, entre Calendario y Crear, con el mismo shape que las entradas existentes)
- Reference: `frontend/app/brands/page.tsx` y `frontend/app/b/[slug]/library/page.tsx` (patrones de página), `frontend/components/ui/*` (shadcn disponibles)

**Interfaces:**
- Consumes: `usePlans`, `useCrearPlan` (Task 8); `useBrand` para formatos/estilos de la marca.
- Produces: página con lista de planes (periodo, objetivo, estado con badge, conteos) que navega a `/b/[slug]/plans/[pid]`, y diálogo de creación.

- [ ] **Step 1: Write `nuevo-plan-dialog.tsx`**

```tsx
"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useCrearPlan } from "@/hooks/use-plans";

/** Periodo por default: la semana ISO siguiente o el mes siguiente. */
function periodoDefault(tipo: "semana" | "mes"): string {
  const hoy = new Date();
  if (tipo === "mes") {
    const m = new Date(hoy.getFullYear(), hoy.getMonth() + 1, 1);
    return `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`;
  }
  const d = new Date(hoy);
  d.setDate(d.getDate() + 7);
  // Semana ISO: jueves de la semana define el año.
  const jueves = new Date(d);
  jueves.setDate(d.getDate() + 3 - ((d.getDay() + 6) % 7));
  const inicioAno = new Date(jueves.getFullYear(), 0, 1);
  const semana = Math.ceil(((+jueves - +inicioAno) / 86400000 + 1) / 7);
  return `${jueves.getFullYear()}-W${String(semana).padStart(2, "0")}`;
}

export function NuevoPlanDialog({ slug }: { slug: string }) {
  const router = useRouter();
  const crear = useCrearPlan(slug);
  const [abierto, setAbierto] = useState(false);
  const [tipo, setTipo] = useState<"semana" | "mes">("semana");
  const [periodo, setPeriodo] = useState(periodoDefault("semana"));
  const [objetivo, setObjetivo] = useState("");
  const [nPiezas, setNPiezas] = useState(8);
  const [conNoticias, setConNoticias] = useState(false);

  const enviar = () => {
    crear.mutate(
      {
        tipo_periodo: tipo,
        periodo,
        objetivo,
        n_piezas: nPiezas,
        fuentes_info: conNoticias ? ["prompt", "noticias"] : ["prompt"],
      },
      {
        onSuccess: ({ plan_id }) => {
          setAbierto(false);
          router.push(`/b/${slug}/plans/${plan_id}`);
        },
        onError: (e) => toast.error(e instanceof Error ? e.message : "No se pudo crear el plan"),
      },
    );
  };

  const cambiarTipo = (t: "semana" | "mes") => {
    setTipo(t);
    setPeriodo(periodoDefault(t));
  };

  return (
    <Dialog open={abierto} onOpenChange={setAbierto}>
      <DialogTrigger asChild>
        <Button>Nuevo plan</Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Nuevo plan de contenido</DialogTitle>
        </DialogHeader>
        <div className="grid gap-4">
          <div className="flex gap-2">
            <Button variant={tipo === "semana" ? "default" : "outline"} size="sm"
                    onClick={() => cambiarTipo("semana")}>Semanal</Button>
            <Button variant={tipo === "mes" ? "default" : "outline"} size="sm"
                    onClick={() => cambiarTipo("mes")}>Mensual</Button>
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="periodo">Periodo</Label>
            <Input id="periodo" value={periodo}
                   onChange={(e) => setPeriodo(e.target.value)}
                   placeholder={tipo === "semana" ? "2026-W36" : "2026-09"} />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="objetivo">Objetivo del periodo</Label>
            <Textarea id="objetivo" value={objetivo} rows={3}
                      onChange={(e) => setObjetivo(e.target.value)}
                      placeholder="Ej. dar a conocer los venues chicos y llevar gente a los shows de octubre" />
          </div>
          <div className="grid gap-1.5">
            <Label htmlFor="npiezas">Número de publicaciones</Label>
            <Input id="npiezas" type="number" min={1} max={30} value={nPiezas}
                   onChange={(e) => setNPiezas(Number(e.target.value))} />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={conNoticias}
                   onChange={(e) => setConNoticias(e.target.checked)} />
            Usar noticias de mis fuentes como inspiración
          </label>
          <Button onClick={enviar}
                  disabled={crear.isPending || objetivo.trim().length < 10}>
            {crear.isPending ? "Creando…" : "Proponer temas"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2: Write `plans/page.tsx`**

```tsx
"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { usePlans } from "@/hooks/use-plans";

import { NuevoPlanDialog } from "./_components/nuevo-plan-dialog";

const ESTADOS: Record<string, { label: string; clase: string }> = {
  proponiendo: { label: "Proponiendo temas", clase: "bg-blue-100 text-blue-800" },
  temas: { label: "Temas por curar", clase: "bg-amber-100 text-amber-800" },
  generando: { label: "Generando", clase: "bg-blue-100 text-blue-800" },
  curacion: { label: "Curación", clase: "bg-purple-100 text-purple-800" },
  aprobado: { label: "Aprobado", clase: "bg-green-100 text-green-800" },
  error: { label: "Error", clase: "bg-red-100 text-red-800" },
};

export default function PlanesPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data: planes, isLoading } = usePlans(slug);

  return (
    <div className="space-y-4 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Planes de contenido</h1>
        <NuevoPlanDialog slug={slug} />
      </div>
      {isLoading && <p className="text-sm text-muted-foreground">Cargando…</p>}
      {planes?.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Sin planes todavía. Crea el primero: escribes el objetivo del periodo y te
          proponemos los temas.
        </p>
      )}
      <div className="grid gap-3">
        {planes?.map((p) => {
          const estado = ESTADOS[p.estado] ?? { label: p.estado, clase: "" };
          return (
            <Link key={p.id} href={`/b/${slug}/plans/${p.id}`}>
              <Card className="transition-colors hover:bg-accent/50">
                <CardContent className="flex items-center justify-between gap-4 p-4">
                  <div className="min-w-0">
                    <p className="font-medium">
                      {p.tipo_periodo === "semana" ? "Semana" : "Mes"} {p.periodo}
                    </p>
                    <p className="truncate text-sm text-muted-foreground">{p.objetivo}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-3 text-sm">
                    <span className="text-muted-foreground">
                      {p.topics_aprobados}/{p.topics_total} temas · {p.piezas} piezas
                      {p.piezas_pendientes > 0 && ` (${p.piezas_pendientes} por curar)`}
                    </span>
                    <Badge className={estado.clase} variant="secondary">{estado.label}</Badge>
                  </div>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 3: NAV** — en `frontend/app/b/[slug]/layout.tsx`, leer el arreglo `NAV` existente y agregar la entrada de Planes entre Calendario y Crear copiando el shape exacto de las entradas vecinas (href relativo `plans`, label `Planes`; si las entradas llevan icono de `lucide-react`, usar `ClipboardList`).

- [ ] **Step 4: Verify**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: build verde (las rutas nuevas compilan)

- [ ] **Step 5: Commit**

```bash
git add frontend/app/b/[slug]/plans frontend/app/b/[slug]/layout.tsx
git commit -m "feat(portal): lista de planes + creación (objetivo → temas)"
```

---

### Task 10: Front — detalle del plan en 3 fases (`/b/[slug]/plans/[pid]`)

**Files:**
- Create: `frontend/app/b/[slug]/plans/[pid]/page.tsx`
- Create: `frontend/app/b/[slug]/plans/[pid]/_components/curador-temas.tsx`
- Create: `frontend/app/b/[slug]/plans/[pid]/_components/curador-piezas.tsx`
- Reference (leer antes): `frontend/app/b/[slug]/calendar/_components/queue-drawer.tsx` (drawer existente con `ImageCarousel` + `slide-editor` — se REUTILIZA, no se duplica), `frontend/hooks/use-queue.ts` (`useQueueDetail`, `useAprobar`, `useRechazar`, `useRegenerar`), `frontend/components/progreso-job.tsx` o equivalente que use `useJob`.

**Interfaces:**
- Consumes: `usePlan(slug, pid, {refetchInterval})`, `useEditarTopic`, `useAgregarTopic`, `useGenerarPlan`, `useAprobarPlan`; `queue-drawer` existente para abrir una pieza.
- Produces: pantalla única que rota por `plan.estado`.

- [ ] **Step 1: Write `page.tsx`** (orquestador de fases)

```tsx
"use client";

import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { usePlan } from "@/hooks/use-plans";

import { CuradorPiezas } from "./_components/curador-piezas";
import { CuradorTemas } from "./_components/curador-temas";

export default function PlanPage() {
  const { slug, pid } = useParams<{ slug: string; pid: string }>();
  const planId = Number(pid);
  // Mientras un job corre (proponiendo/generando) la pantalla se refresca sola.
  const { data: plan, isLoading } = usePlan(slug, planId, {
    refetchInterval: (q) =>
      q.state.data && ["proponiendo", "generando"].includes(q.state.data.estado)
        ? 3000
        : false,
  });

  if (isLoading || !plan) {
    return <p className="p-6 text-sm text-muted-foreground">Cargando…</p>;
  }

  return (
    <div className="space-y-4 p-6">
      <div>
        <h1 className="text-xl font-semibold">
          Plan {plan.tipo_periodo === "semana" ? "semanal" : "mensual"} {plan.periodo}
        </h1>
        <p className="text-sm text-muted-foreground">{plan.objetivo}</p>
      </div>

      {plan.estado === "error" && (
        <div className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
          El plan falló: {plan.error ?? "error desconocido"}. Puedes crear uno nuevo o
          reintentar la generación si ya hay temas.
        </div>
      )}

      {["proponiendo", "generando"].includes(plan.estado) && (
        <div className="rounded-md border p-4 text-sm">
          <Badge variant="secondary" className="mb-2">
            {plan.estado === "proponiendo" ? "Proponiendo temas…" : "Generando piezas…"}
          </Badge>
          <p className="text-muted-foreground">
            Esto corre en segundo plano; la pantalla se actualiza sola.
          </p>
        </div>
      )}

      {plan.estado === "temas" && <CuradorTemas slug={slug} plan={plan} />}

      {["curacion", "aprobado"].includes(plan.estado) && (
        <CuradorPiezas slug={slug} plan={plan} />
      )}
    </div>
  );
}
```

Nota para el ejecutor: `refetchInterval` con callback recibe el query en TanStack v5 — verificar contra el uso real en `frontend/hooks/use-job.ts` y copiar su forma exacta de polling si difiere.

- [ ] **Step 2: Write `curador-temas.tsx`**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";
import {
  useAgregarTopic, useEditarTopic, useGenerarPlan, type PlanDetail, type PlanTopic,
} from "@/hooks/use-plans";

function FilaTema({ slug, pid, tema }: { slug: string; pid: number; tema: PlanTopic }) {
  const editar = useEditarTopic(slug, pid);
  const [titulo, setTitulo] = useState(tema.titulo);
  const descartado = tema.estado === "descartado";
  const aprobado = tema.estado === "aprobado";

  return (
    <div className={`flex items-center gap-2 rounded-md border p-2 ${descartado ? "opacity-50" : ""}`}>
      <Input value={titulo} className="flex-1"
             onChange={(e) => setTitulo(e.target.value)}
             onBlur={() => titulo.trim() !== tema.titulo &&
               editar.mutate({ tid: tema.id, titulo: titulo.trim() })} />
      {tema.fuente === "noticia" && tema.url && (
        <a href={tema.url} target="_blank" rel="noreferrer"
           className="text-xs text-muted-foreground underline">fuente</a>
      )}
      {tema.formato && <Badge variant="outline">{tema.formato}</Badge>}
      <Button size="sm" variant={aprobado ? "default" : "outline"}
              onClick={() => editar.mutate({ tid: tema.id, estado: "aprobado" })}>
        ✓
      </Button>
      <Button size="sm" variant={descartado ? "destructive" : "outline"}
              onClick={() => editar.mutate({ tid: tema.id, estado: "descartado" })}>
        ✕
      </Button>
    </div>
  );
}

export function CuradorTemas({ slug, plan }: { slug: string; plan: PlanDetail }) {
  const agregar = useAgregarTopic(slug, plan.id);
  const generar = useGenerarPlan(slug, plan.id);
  const [nuevo, setNuevo] = useState("");
  const aprobados = plan.topics.filter((t) => t.estado === "aprobado").length;

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Cura los temas: aprueba (✓), descarta (✕) o edita el título. Solo se generan
        los aprobados.
      </p>
      <div className="space-y-2">
        {plan.topics.map((t) => (
          <FilaTema key={t.id} slug={slug} pid={plan.id} tema={t} />
        ))}
      </div>
      <div className="flex gap-2">
        <Input value={nuevo} placeholder="Agregar tema propio…"
               onChange={(e) => setNuevo(e.target.value)} />
        <Button variant="outline" disabled={nuevo.trim().length < 3}
                onClick={() => {
                  agregar.mutate({ titulo: nuevo.trim() });
                  setNuevo("");
                }}>
          Agregar
        </Button>
      </div>
      <AlertDialog>
        <AlertDialogTrigger asChild>
          <Button disabled={aprobados === 0 || generar.isPending}>
            Generar {aprobados} {aprobados === 1 ? "pieza" : "piezas"}
          </Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>¿Generar el contenido?</AlertDialogTitle>
            <AlertDialogDescription>
              Se generarán {aprobados} publicaciones con imágenes. Toma varios minutos
              y corre en segundo plano; después las curas una por una.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            <AlertDialogAction
              onClick={() =>
                generar.mutate(undefined, {
                  onError: (e) =>
                    toast.error(e instanceof Error ? e.message : "No se pudo generar"),
                })
              }>
              Generar
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
```

- [ ] **Step 3: Write `curador-piezas.tsx`**

```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Card, CardContent } from "@/components/ui/card";
import { primeraImagen } from "@/lib/imagenes";
import { useAprobarPlan, type PlanDetail } from "@/hooks/use-plans";

// El drawer de detalle/edición de una pieza ya existe (calendario): se reutiliza
// tal cual — edición de caption, slide por slide, regenerar, rechazar.
import { QueueDrawer } from "../../../calendar/_components/queue-drawer";

export function CuradorPiezas({ slug, plan }: { slug: string; plan: PlanDetail }) {
  const aprobar = useAprobarPlan(slug, plan.id);
  const [abierta, setAbierta] = useState<number | null>(null);
  const pendientes = plan.piezas.filter((p) => p.aprobacion === "pendiente");

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          {pendientes.length} de {plan.piezas.length} piezas por curar. Abre cada una
          para editar slides, regenerar o descartar.
        </p>
        {pendientes.length > 0 && (
          <AlertDialog>
            <AlertDialogTrigger asChild>
              <Button disabled={aprobar.isPending}>
                Aprobar {pendientes.length} pendientes
              </Button>
            </AlertDialogTrigger>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>¿Aprobar todo lo pendiente?</AlertDialogTitle>
                <AlertDialogDescription>
                  Cada pieza tomará el siguiente horario libre de la marca y se
                  publicará sola. Las que descartaste no entran.
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>Cancelar</AlertDialogCancel>
                <AlertDialogAction
                  onClick={() =>
                    aprobar.mutate({}, {
                      onSuccess: ({ aprobadas, fallidas }) => {
                        toast.success(`${aprobadas.length} piezas programadas`);
                        if (fallidas.length > 0)
                          toast.error(`${fallidas.length} no se pudieron aprobar`);
                      },
                      onError: (e) =>
                        toast.error(e instanceof Error ? e.message : "No se pudo aprobar"),
                    })
                  }>
                  Aprobar todas
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
        {plan.piezas.map((p) => (
          <Card key={p.id} className="cursor-pointer overflow-hidden hover:ring-2"
                onClick={() => setAbierta(p.id)}>
            <CardContent className="p-0">
              {primeraImagen(p.imagen_url) ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={primeraImagen(p.imagen_url)!} alt=""
                     className="aspect-[4/5] w-full object-cover" />
              ) : (
                <div className="aspect-[4/5] w-full bg-muted" />
              )}
              <div className="flex items-center justify-between p-2">
                <p className="truncate text-xs">{p.caption ?? "(sin caption)"}</p>
                <Badge variant="secondary" className="shrink-0 text-xs">
                  {p.aprobacion === "pendiente" ? "pendiente"
                    : p.scheduled_datetime ? "programada" : p.status}
                </Badge>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      {abierta !== null && (
        <QueueDrawer slug={slug} qid={abierta} onClose={() => setAbierta(null)} />
      )}
    </div>
  );
}
```

Nota para el ejecutor (obligatoria): las props reales de `QueueDrawer` pueden diferir (`open`, `queueId`, `onOpenChange`…). Leer `frontend/app/b/[slug]/calendar/_components/queue-drawer.tsx` y (a) usar sus props reales, (b) si el componente no es importable desde fuera de `calendar/_components` sin acoplarse feo, MOVERLO a `frontend/components/queue-drawer.tsx` actualizando los imports del calendario en el mismo commit (es el mismo componente, no una copia). `primeraImagen` vive en `frontend/lib/imagenes.ts` — verificar el nombre exacto exportado.

- [ ] **Step 4: Verify**

Run: `cd frontend && pnpm lint && pnpm build`
Expected: build verde

- [ ] **Step 5: Commit**

```bash
git add frontend/app/b/[slug]/plans frontend/components
git commit -m "feat(portal): detalle de plan en 3 fases (temas, progreso, curación de lote)"
```

---

### Task 11: Sync del front al repo de Vercel + suite completa

**Files:**
- Sync: `frontend/` → `/Users/ricardo/Work/personal/instagod-web-app-front/`

- [ ] **Step 1: Suite completa del backend**

Run: `pytest -q && ruff check src/ tests/ api/`
Expected: PASS completo (los 2 fallos ambientales conocidos de la suite no cuentan)

- [ ] **Step 2: Sync al repo del front**

```bash
rsync -a --delete \
  --exclude node_modules --exclude .git --exclude .next \
  /Users/ricardo/Work/personal/instagod/frontend/ \
  /Users/ricardo/Work/personal/instagod-web-app-front/
cd /Users/ricardo/Work/personal/instagod-web-app-front
pnpm install && pnpm build
git add -A
git commit -m "sync: planes de contenido masivo desde instagod master"
```

(NO hacer `git push` todavía: el push despliega a Vercel — va en el Task 12, con aprobación.)

- [ ] **Step 3: Commit final del backend si quedó algo suelto**

```bash
cd /Users/ricardo/Work/personal/instagod && git status --short
```

Expected: árbol limpio (todo commiteado en tasks previos).

---

### Task 12: Deploy a la VM + prueba real con gdlscene — ⚠️ GATED

**⚠️ Este task NO se ejecuta sin aprobación explícita de Ricardo en el momento: toca producción (VM + Vercel).**

- [ ] **Step 1: Pedir aprobación** mostrando: commits a desplegar (`git log --oneline` desde el último deploy), y que las migraciones (`content_plans`, `plan_topics`, `plan_id`) corren solas en el lifespan.

- [ ] **Step 2: Deploy backend**

```bash
cd /Users/ricardo/Work/personal/instagod
git archive master | ssh instagod-vm 'tar -x -C /opt/instagod'
ssh instagod-vm 'cd /opt/instagod && docker compose build && docker compose up -d && docker compose ps'
```

Expected: 5 contenedores `Up`, `instagod-api` healthy.

- [ ] **Step 3: Verificar migración en la VM**

```bash
ssh instagod-vm 'cd /opt/instagod && docker compose exec -T api python -c "
from src import db
cx = db.connect()
tablas = {r[0] for r in cx.execute(\"SELECT name FROM sqlite_master WHERE type=\x27table\x27\")}
cols = {r[1] for r in cx.execute(\"PRAGMA table_info(content_queue)\")}
print(\"content_plans\" in tablas, \"plan_topics\" in tablas, \"plan_id\" in cols)
"'
```

Expected: `True True True`

- [ ] **Step 4: Deploy front** — `cd /Users/ricardo/Work/personal/instagod-web-app-front && git push` (Vercel auto-deploy); verificar que la URL de prod sirve `/b/gdlscene/plans`.

- [ ] **Step 5: Prueba real** — crear un plan semanal de gdlscene desde el portal (objetivo real de Ricardo), curar temas, generar, curar piezas, aprobar. Verificar con `docker compose logs publisher` que las piezas quedan programadas y se publican en su slot.

- [ ] **Step 6: Nota de sesión en el vault** (`vault-scribe`): `Sessions/2026-08-28-instagod-planes-contenido-masivo.md` con commits, decisiones y pendientes.

---

## Self-Review (hecho al escribir el plan)

1. **Cobertura del spec:** tablas+migración (T1), tolerancia ±1 (T2), flag Telegram (T3), plan_temas (T4), dominio (T5), jobs + fix regenerar (T6), API + docs (T7), front (T8-T10), sync (T11), deploy+prueba real (T12). El spec no exige planes recurrentes ni % de mezcla (fuera de alcance).
2. **Placeholders:** los "Nota para el ejecutor" de T3/T8/T10 no son TBD — son instrucciones de verificación contra archivos reales cuyo shape exacto vive en el repo (fixtures y props de componentes), con acción concreta y fallback definido.
3. **Consistencia de tipos:** `plan.proponer_temas`/`plan.generar` payload `{plan_id}` en T6 y T7; `notificar_telegram` T3→T6; `recortar_slide_extra` T2 exportado y testeado; estados de plan idénticos en T1 (CHECK), T5 (docstring), T6 (transiciones) y T9/T10 (UI).
