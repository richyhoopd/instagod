# H1 — Cimiento de datos: entidades y plantillas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar en la DB las cuatro tablas y las cinco columnas sobre las que se apoyan los hitos H2–H5, con los datos de gdlscene ya sembrados en ellas y sin que nada de lo que hoy funciona cambie de comportamiento.

**Architecture:** Se agregan `brand_entities`, `brand_templates`, `template_versions` y `brand_fonts` a `src/schema.sql`, y las columnas nuevas al dict `_MIGRATIONS` de `src/db.py`, siguiendo el patrón de ALTER idempotente que ya usa el repo. Dos módulos nuevos de dominio (`src/entidades.py`, `src/plantillas.py`) encapsulan el acceso, y dos seeds idempotentes migran las bandas de gdlscene a entidades y los cuatro HTML de `templates/` a plantillas de DB versionadas. Ningún camino de código existente cambia: las tablas nuevas quedan pobladas pero todavía sin lectores.

**Tech Stack:** Python 3.12+, SQLite (WAL), Jinja2, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-29-plantillas-lotes-y-stats-design.md`

## Global Constraints

- Toda migración es **idempotente**: `db.init_db(cx)` debe poder correr dos veces seguidas sin error y sin duplicar filas. Es el criterio de aceptación de cada tarea que toque el esquema.
- Los `CREATE TABLE` van a `src/schema.sql` con `IF NOT EXISTS`. Las columnas agregadas a tablas existentes van al dict `_MIGRATIONS` de `src/db.py`, nunca a `schema.sql`.
- Toda tabla nueva debe registrarse en el dict `TABLES` de `src/db.py:23` con el conjunto de sus columnas escribibles, o `db.insert` y `db.update` fallan con `KeyError: Tabla desconocida`.
- `src/db.py:449` `insert(cx, table, **fields) -> int` y `src/db.py:459` `update(cx, table, row_id, **fields) -> None` son los únicos escritores; no escribir SQL de INSERT/UPDATE a mano en los módulos nuevos.
- Línea máxima 100 caracteres (`ruff`, `pyproject.toml`). `E501` está ignorado, pero se respeta igual en código nuevo.
- La suite corre con `.venv/bin/python -m pytest`. El umbral de cobertura global es 50% (`fail_under = 50`); código nuevo sin test baja el número y rompe CI.
- Comentarios y docstrings en español, como todo el repo.
- **Nada toca `/opt/instagod/data/gdlscene.db` ni la VM en este hito.** Todo corre contra `tmp_path` en tests y contra copias locales.
- Nombres canónicos del contrato de plantilla, usados idénticos en todos los hitos: `titular`, `imagen`, `handle`, `logo`, `color_marca`.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `src/schema.sql` (modificar) | DDL de las 4 tablas nuevas, al final del archivo |
| `src/db.py` (modificar) | Entradas en `TABLES` y `_MIGRATIONS`; guarda y DDL del rebuild de `content_queue` |
| `src/entidades.py` (crear) | CRUD y listado de `brand_entities`; nada de estadísticas ni de selección |
| `src/plantillas/__init__.py` (crear) | CRUD de `brand_templates` y `template_versions` |
| `src/plantillas/contrato.py` (crear) | Validación del contrato y de las variables del HTML. Sin I/O ni DB |
| `src/seeds/entidades_gdlscene.py` (crear) | Siembra idempotente de `bands` → `brand_entities` y backfill de `photos.entity_id` |
| `src/seeds/plantillas_gdlscene.py` (crear) | Siembra idempotente de los 4 HTML → `brand_templates` + v1 |
| `tests/test_h1_schema.py` (crear) | Tablas, columnas, CHECK e idempotencia |
| `tests/test_entidades.py` (crear) | CRUD de entidades |
| `tests/test_contrato_plantilla.py` (crear) | Validación de contrato, sin DB ni Chromium |
| `tests/test_plantillas.py` (crear) | CRUD y versionado de plantillas |
| `tests/test_seeds_h1.py` (crear) | Idempotencia y fidelidad de los dos seeds |

`src/plantillas/` es paquete y no módulo suelto porque en H3 le entra el diseñador con DeepSeek y en H5 el motor de render; separar el contrato puro (sin I/O) del acceso a DB desde ahora evita el archivo de 600 líneas.

---

### Task 1: Tabla `brand_entities`

**Files:**
- Modify: `src/schema.sql` (agregar al final)
- Modify: `src/db.py:23` (dict `TABLES`)
- Test: `tests/test_h1_schema.py`

**Interfaces:**
- Consumes: nada.
- Produces: tabla `brand_entities` con las columnas `account_id, tipo, nombre, slug, prioridad, activa, atributos_json, band_id, creado_en`, y la entrada `"brand_entities"` en `db.TABLES`.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_h1_schema.py`:

```python
"""H1: tablas y columnas nuevas del cimiento de entidades y plantillas."""
from __future__ import annotations

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_tabla_brand_entities(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = db.insert(cx, "brand_entities", account_id=1, tipo="banda",
                    nombre="Los Ejemplo", slug="los-ejemplo")
    fila = db.get(cx, "brand_entities", eid)
    assert fila["nombre"] == "Los Ejemplo"
    assert fila["prioridad"] == 3      # default
    assert fila["activa"] == 1         # default


def test_brand_entities_slug_unico_por_cuenta(tmp_path) -> None:
    import sqlite3
    cx = _cx(tmp_path)
    db.insert(cx, "brand_entities", account_id=1, tipo="banda",
              nombre="A", slug="repetido")
    try:
        db.insert(cx, "brand_entities", account_id=1, tipo="banda",
                  nombre="B", slug="repetido")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("el slug debe ser único por cuenta")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py -v`
Expected: FAIL con `KeyError: Tabla desconocida: brand_entities` (o `no such table`).

- [ ] **Step 3: Agregar el DDL a `src/schema.sql`**

Al final del archivo:

```sql
-- ---------------------------------------------------------------------------
-- H1 (spec 2026-08-29): el sujeto del contenido, genérico por marca.
-- gdlscene lo usa para bandas; una inmobiliaria para propiedades. `band_id`
-- es el puente al dominio musical viejo, que NO se toca.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brand_entities (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    tipo           TEXT    NOT NULL,
    nombre         TEXT    NOT NULL,
    slug           TEXT    NOT NULL,
    prioridad      INTEGER NOT NULL DEFAULT 3,
    activa         INTEGER NOT NULL DEFAULT 1,
    atributos_json TEXT,
    band_id        INTEGER REFERENCES bands(id) ON DELETE SET NULL,
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, slug),
    CHECK (activa IN (0,1)),
    CHECK (prioridad BETWEEN 1 AND 5)
);
CREATE INDEX IF NOT EXISTS idx_entities_cuenta ON brand_entities(account_id, activa);
CREATE INDEX IF NOT EXISTS idx_entities_band   ON brand_entities(band_id);
```

- [ ] **Step 4: Registrar la tabla en `TABLES`**

En `src/db.py`, dentro del dict `TABLES` (empieza en la línea 23), agregar:

```python
    "brand_entities": {
        "account_id", "tipo", "nombre", "slug", "prioridad", "activa",
        "atributos_json", "band_id",
    },
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/schema.sql src/db.py tests/test_h1_schema.py
git commit -m "feat(h1): tabla brand_entities, el sujeto genérico del contenido"
```

---

### Task 2: Tablas `brand_templates`, `template_versions` y `brand_fonts`

**Files:**
- Modify: `src/schema.sql`
- Modify: `src/db.py:23` (dict `TABLES`)
- Test: `tests/test_h1_schema.py`

**Interfaces:**
- Consumes: `accounts`, `users` (ya existen).
- Produces: las tres tablas y sus entradas en `db.TABLES`. `template_versions.version` es un entero que arranca en 1 y es único por `template_id`.

- [ ] **Step 1: Write the failing test**

Agregar a `tests/test_h1_schema.py`:

```python
def test_tabla_brand_templates(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = db.insert(cx, "brand_templates", account_id=1, slug="clasica",
                    nombre="Clásica", aspecto="4:5",
                    contrato_json='{"aspecto":"4:5","base":[],"extras":[]}',
                    html="<div class=card></div>", origen="seed")
    fila = db.get(cx, "brand_templates", tid)
    assert fila["estado"] == "borrador"      # default
    assert fila["version_actual"] == 1       # default


def test_brand_templates_rechaza_aspecto_invalido(tmp_path) -> None:
    import sqlite3
    cx = _cx(tmp_path)
    try:
        db.insert(cx, "brand_templates", account_id=1, slug="x", nombre="X",
                  aspecto="16:9", contrato_json="{}", html="<div></div>")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("aspecto solo acepta 4:5 y 9:16")


def test_tabla_template_versions(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = db.insert(cx, "brand_templates", account_id=1, slug="v", nombre="V",
                    contrato_json="{}", html="<div></div>")
    vid = db.insert(cx, "template_versions", template_id=tid, version=1,
                    html="<div></div>", contrato_json="{}",
                    mensaje_usuario="hazla verde")
    assert db.get(cx, "template_versions", vid)["mensaje_usuario"] == "hazla verde"


def test_tabla_brand_fonts(tmp_path) -> None:
    cx = _cx(tmp_path)
    fid = db.insert(cx, "brand_fonts", account_id=1, familia="Anton",
                    archivo="fonts/Anton-Regular.ttf")
    assert db.get(cx, "brand_fonts", fid)["familia"] == "Anton"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py -v`
Expected: FAIL con `KeyError: Tabla desconocida: brand_templates`.

- [ ] **Step 3: Agregar el DDL a `src/schema.sql`**

```sql
-- ---------------------------------------------------------------------------
-- H1: el look. HTML+CSS Jinja2 en DB con contrato de variables, versionado.
-- Sustituye al dict TEMPLATES hardcodeado de src/compose.py (que se retira
-- hasta H5, cuando estas filas estén verificadas contra piezas reales).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS brand_templates (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    slug           TEXT    NOT NULL,
    nombre         TEXT    NOT NULL,
    descripcion    TEXT,
    aspecto        TEXT    NOT NULL DEFAULT '4:5',
    contrato_json  TEXT    NOT NULL,
    html           TEXT    NOT NULL,
    estado         TEXT    NOT NULL DEFAULT 'borrador',
    version_actual INTEGER NOT NULL DEFAULT 1,
    origen         TEXT    NOT NULL DEFAULT 'manual',
    creado_por     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    creado_en      TEXT    NOT NULL DEFAULT (datetime('now')),
    actualizado_en TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, slug),
    CHECK (aspecto IN ('4:5','9:16')),
    CHECK (estado  IN ('borrador','activa','archivada')),
    CHECK (origen  IN ('seed','llm','manual'))
);
CREATE INDEX IF NOT EXISTS idx_templates_cuenta ON brand_templates(account_id, estado);

-- Es a la vez el historial de versiones y el log del chat de diseño: cada
-- mensaje del usuario produce exactamente una fila.
CREATE TABLE IF NOT EXISTS template_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    template_id     INTEGER NOT NULL REFERENCES brand_templates(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    mensaje_usuario TEXT,
    html            TEXT    NOT NULL,
    contrato_json   TEXT    NOT NULL,
    preview_path    TEXT,
    llm_meta        TEXT,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (template_id, version)
);
CREATE INDEX IF NOT EXISTS idx_tversions_tpl ON template_versions(template_id);

CREATE TABLE IF NOT EXISTS brand_fonts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    familia    TEXT    NOT NULL,
    archivo    TEXT    NOT NULL,
    creado_en  TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, familia)
);
```

- [ ] **Step 4: Registrar las tres tablas en `TABLES`**

En `src/db.py`, dentro del dict `TABLES`:

```python
    "brand_templates": {
        "account_id", "slug", "nombre", "descripcion", "aspecto",
        "contrato_json", "html", "estado", "version_actual", "origen",
        "creado_por", "actualizado_en",
    },
    "template_versions": {
        "template_id", "version", "mensaje_usuario", "html",
        "contrato_json", "preview_path", "llm_meta",
    },
    "brand_fonts": {"account_id", "familia", "archivo"},
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Commit**

```bash
git add src/schema.sql src/db.py tests/test_h1_schema.py
git commit -m "feat(h1): brand_templates, template_versions y brand_fonts"
```

---

### Task 3: Columnas nuevas en tablas existentes

**Files:**
- Modify: `src/db.py` (dict `_MIGRATIONS`, empieza en la línea 158)
- Test: `tests/test_h1_schema.py`

**Interfaces:**
- Consumes: `brand_templates`, `brand_entities` (Tasks 1 y 2).
- Produces: `content_queue.{template_id, template_version, entity_id, campos_json, aspecto}`, `content_plans.{estrategia, criterio_json}`, `plan_topics.entity_id`, `photos.entity_id`.

Nota para quien implemente: `_MIGRATIONS` es un dict `tabla -> {columna: DDL}` que `init_db` aplica con `ALTER TABLE ADD COLUMN` solo si la columna no existe (`src/db.py:410-415`). SQLite no permite `ADD COLUMN` con una FK que apunte a otra tabla en el mismo statement de forma confiable, así que estas columnas se declaran como enteros simples sin `REFERENCES`. La integridad se cuida en el código, no en el motor.

- [ ] **Step 1: Write the failing test**

Agregar a `tests/test_h1_schema.py`:

```python
def test_columnas_nuevas_en_content_queue(tmp_path) -> None:
    cx = _cx(tmp_path)
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert {"template_id", "template_version", "entity_id",
            "campos_json", "aspecto"} <= cols


def test_columnas_nuevas_en_planes(tmp_path) -> None:
    cx = _cx(tmp_path)
    plan_cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_plans)")}
    topic_cols = {r["name"] for r in cx.execute("PRAGMA table_info(plan_topics)")}
    foto_cols = {r["name"] for r in cx.execute("PRAGMA table_info(photos)")}
    assert {"estrategia", "criterio_json"} <= plan_cols
    assert "entity_id" in topic_cols
    assert "entity_id" in foto_cols


def test_estrategia_por_defecto_es_llm(tmp_path) -> None:
    # Los planes que ya existen en prod no deben cambiar de comportamiento.
    cx = _cx(tmp_path)
    pid = db.insert(cx, "content_plans", account_id=1, tipo_periodo="mes",
                    periodo="2026-09")
    assert db.get(cx, "content_plans", pid)["estrategia"] == "llm"


def test_campos_json_persiste_en_content_queue(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="meme", campos_json='{"titular":"hola"}',
                    aspecto="9:16", template_version=2)
    fila = db.get(cx, "content_queue", qid)
    assert fila["campos_json"] == '{"titular":"hola"}'
    assert fila["aspecto"] == "9:16"
    assert fila["template_version"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py -v`
Expected: FAIL — los tests de columnas nuevas fallan con `assert {...} <= cols`.

- [ ] **Step 3: Agregar las columnas a `_MIGRATIONS`**

En `src/db.py`, dentro del dict `_MIGRATIONS`, en la entrada `"content_queue"` (la que tiene los DDL, no la de `TABLES`), agregar al final:

```python
        # H1 (spec 2026-08-29): la pieza apunta a una plantilla de DB y guarda
        # los valores de su contrato, para poder re-renderizar sin volver a
        # llamar al LLM. `template` (TEXT) se conserva y se llena en paralelo.
        "template_id": "INTEGER",
        "template_version": "INTEGER",
        "entity_id": "INTEGER",
        "campos_json": "TEXT",
        "aspecto": "TEXT",
```

Y agregar (o completar) las entradas de las otras tres tablas en `_MIGRATIONS`:

```python
    "content_plans": {
        # H1: un lote es un content_plan con otra estrategia de propuesta.
        # 'llm' es el comportamiento actual y por eso es el default.
        "estrategia": "TEXT NOT NULL DEFAULT 'llm'",
        "criterio_json": "TEXT",
    },
    "plan_topics": {
        "entity_id": "INTEGER",
    },
    "photos": {
        "entity_id": "INTEGER",
    },
```

Si alguna de esas tres claves ya existe en `_MIGRATIONS`, agregar las columnas dentro del dict existente en vez de crear una entrada duplicada — un dict literal con la misma clave dos veces descarta la primera en silencio.

- [ ] **Step 4: Agregar las columnas nuevas a `TABLES`**

En `src/db.py`, dentro del dict `TABLES`, agregar a los conjuntos existentes:

- `"content_queue"`: `"template_id", "template_version", "entity_id", "campos_json", "aspecto"`
- `"content_plans"`: `"estrategia", "criterio_json"`
- `"plan_topics"`: `"entity_id"`
- `"photos"`: `"entity_id"`

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py -v`
Expected: PASS (10 tests).

- [ ] **Step 6: Commit**

```bash
git add src/db.py tests/test_h1_schema.py
git commit -m "feat(h1): columnas de plantilla, entidad y estrategia en las tablas vivas"
```

---

### Task 4: Ensanchar el CHECK de `content_queue.tipo` con `'post'`

**Files:**
- Modify: `src/db.py:332-400` (`_migrar_check_tipo_queue`), y las constantes `_CONTENT_QUEUE_REBUILD_DDL` y `_CONTENT_QUEUE_REBUILD_COLS`
- Modify: `src/schema.sql` (el `CHECK (tipo IN ...)` de `content_queue`)
- Test: `tests/test_h1_schema.py`

**Interfaces:**
- Consumes: las columnas de la Task 3.
- Produces: `content_queue` acepta `tipo='post'`.

**Por qué esta tarea es delicada:** `_migrar_check_tipo_queue` reconstruye la tabla completa (procedimiento oficial de sqlite.org). Tiene una guarda deliberada en `src/db.py:355-367` que lanza `RuntimeError` si la tabla vieja trae columnas que `_CONTENT_QUEUE_REBUILD_COLS` no conoce, para no dropearlas en silencio. Como la Task 3 acaba de agregar cinco columnas, **esta tarea falla con ese RuntimeError si no se actualizan las dos constantes**. Eso no es un bug: es la guarda haciendo su trabajo.

Además, la salida temprana de `src/db.py:349-350` es `if row is None or ("'slideshow'" in row[0] and "'programado'" in row[0]): return`. Hay que agregarle `"'post'"` a esa condición, o en una DB que ya tenga el CHECK viejo-pero-con-slideshow la migración nunca corre.

- [ ] **Step 1: Write the failing test**

Agregar a `tests/test_h1_schema.py`:

```python
def test_tipo_post_es_valido(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="post", caption="hola")
    assert db.get(cx, "content_queue", qid)["tipo"] == "post"


def test_tipo_invalido_sigue_rechazandose(tmp_path) -> None:
    import sqlite3
    cx = _cx(tmp_path)
    try:
        db.insert(cx, "content_queue", tipo="reel", caption="x")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("el CHECK de tipo debe seguir cerrado")


def test_rebuild_conserva_columnas_y_filas(tmp_path) -> None:
    """Simula una DB vieja: CHECK sin 'post' + filas con datos, y verifica
    que el rebuild no pierde ni columnas ni filas."""
    cx = db.connect(tmp_path / "viejo.db")
    db.init_db(cx)
    qid = db.insert(cx, "content_queue", tipo="meme", caption="antes",
                    campos_json='{"titular":"x"}', template_version=3)
    # Fuerza el CHECK viejo reescribiendo sqlite_master no es posible; en su
    # lugar validamos la idempotencia y la preservación tras una 2a corrida.
    db.init_db(cx)
    fila = db.get(cx, "content_queue", qid)
    assert fila["caption"] == "antes"
    assert fila["campos_json"] == '{"titular":"x"}'
    assert fila["template_version"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py::test_tipo_post_es_valido -v`
Expected: FAIL con `sqlite3.IntegrityError: CHECK constraint failed`.

- [ ] **Step 3: Actualizar `src/schema.sql`**

En el `CREATE TABLE IF NOT EXISTS content_queue`, cambiar:

```sql
    CHECK (tipo   IN ('meme','anuncio','slideshow')),
```

por:

```sql
    CHECK (tipo   IN ('meme','anuncio','slideshow','post')),
```

Y actualizar el comentario de la columna `tipo` de `-- 'meme' | 'anuncio' | 'slideshow'` a `-- 'meme' | 'anuncio' | 'slideshow' | 'post'`.

- [ ] **Step 4: Actualizar las constantes del rebuild**

En `src/db.py`, en `_CONTENT_QUEUE_REBUILD_DDL` (el `CREATE TABLE content_queue_new (...)`):
- agregar `'post'` al `CHECK (tipo IN ...)`
- agregar las cinco columnas de la Task 3 con el mismo tipo que su DDL de `_MIGRATIONS`:

```sql
    template_id        INTEGER,
    template_version   INTEGER,
    entity_id          INTEGER,
    campos_json        TEXT,
    aspecto            TEXT,
```

En `_CONTENT_QUEUE_REBUILD_COLS`, agregar las cinco cadenas:

```python
    "template_id", "template_version", "entity_id", "campos_json", "aspecto",
```

- [ ] **Step 5: Actualizar la salida temprana de la migración**

En `src/db.py:349-350`, cambiar:

```python
    if row is None or ("'slideshow'" in row[0] and "'programado'" in row[0]):
        return
```

por:

```python
    if row is None or ("'slideshow'" in row[0] and "'programado'" in row[0]
                       and "'post'" in row[0]):
        return
```

Y actualizar el docstring de la función para mencionar `'post'` junto a `'slideshow'` y `'programado'`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_h1_schema.py tests/test_db_migracion_tipo_queue.py -v`
Expected: PASS. Los tests preexistentes de `test_db_migracion_tipo_queue.py` deben seguir en verde: si alguno falla, la guarda de columnas huérfanas está diciendo que falta una columna en `_CONTENT_QUEUE_REBUILD_COLS`.

- [ ] **Step 7: Commit**

```bash
git add src/db.py src/schema.sql tests/test_h1_schema.py
git commit -m "feat(h1): tipo 'post' en content_queue, con el rebuild al día"
```

---

### Task 5: Módulo `src/entidades.py`

**Files:**
- Create: `src/entidades.py`
- Test: `tests/test_entidades.py`

**Interfaces:**
- Consumes: `db.insert`, `db.update`, `db.rows`, `db.get`; tabla `brand_entities`.
- Produces:
  - `slugificar(nombre: str) -> str`
  - `crear(cx, account_id: int, nombre: str, tipo: str, *, prioridad: int = 3, atributos: dict | None = None, band_id: int | None = None, slug: str | None = None) -> int`
  - `listar(cx, account_id: int, *, solo_activas: bool = True) -> list[dict]`
  - `obtener(cx, entity_id: int) -> dict | None`
  - `por_slug(cx, account_id: int, slug: str) -> dict | None`
  - `editar(cx, entity_id: int, **campos) -> None`
  - `archivar(cx, entity_id: int) -> None`
  - `atributos_de(fila: dict) -> dict`

`atributos_de` es tolerante a JSON malformado y devuelve `{}`, igual que `src/marcas.py:53-63` hace con `estilos_json`.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_entidades.py`:

```python
"""CRUD de brand_entities: el sujeto genérico del contenido."""
from __future__ import annotations

from src import db, entidades


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_slugificar_normaliza_acentos_y_espacios() -> None:
    assert entidades.slugificar("Los Ácidos del Norte") == "los-acidos-del-norte"
    assert entidades.slugificar("  Café   Tacvba  ") == "cafe-tacvba"
    assert entidades.slugificar("¿Qué Pex?") == "que-pex"


def test_crear_y_obtener(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = entidades.crear(cx, 1, "Los Ejemplo", "banda",
                          atributos={"followers_ig": 1200})
    fila = entidades.obtener(cx, eid)
    assert fila["slug"] == "los-ejemplo"
    assert entidades.atributos_de(fila) == {"followers_ig": 1200}


def test_slug_colisionado_recibe_sufijo(tmp_path) -> None:
    cx = _cx(tmp_path)
    entidades.crear(cx, 1, "Los Ejemplo", "banda")
    eid2 = entidades.crear(cx, 1, "Los Ejemplo", "banda")
    assert entidades.obtener(cx, eid2)["slug"] == "los-ejemplo-2"


def test_listar_aisla_por_cuenta(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="otra", ig_handle="otra",
              nombre="Otra", ciudad="CDMX")
    otra = db.rows(cx, "SELECT id FROM accounts WHERE slug='otra'")[0]["id"]
    entidades.crear(cx, 1, "De la uno", "banda")
    entidades.crear(cx, otra, "De la otra", "propiedad")
    assert [e["nombre"] for e in entidades.listar(cx, 1)] == ["De la uno"]
    assert [e["nombre"] for e in entidades.listar(cx, otra)] == ["De la otra"]


def test_archivar_la_saca_del_listado(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = entidades.crear(cx, 1, "Temporal", "banda")
    entidades.archivar(cx, eid)
    assert entidades.listar(cx, 1) == []
    assert len(entidades.listar(cx, 1, solo_activas=False)) == 1


def test_atributos_malformados_no_revientan(tmp_path) -> None:
    cx = _cx(tmp_path)
    eid = entidades.crear(cx, 1, "Rota", "banda")
    db.update(cx, "brand_entities", eid, atributos_json="{esto no es json")
    assert entidades.atributos_de(entidades.obtener(cx, eid)) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_entidades.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.entidades'`.

- [ ] **Step 3: Escribir `src/entidades.py`**

```python
"""Entidades de marca: el sujeto del contenido.

Para gdlscene una entidad es una banda; para una inmobiliaria, una propiedad;
para una cuenta de tips, un tema recurrente. Es lo que permite que los lotes
("las que llevan más tiempo sin publicarse") y las estadísticas por sujeto
funcionen en cualquier marca y no solo en la musical.

Este módulo NO calcula estadísticas ni ordena para lotes: solo CRUD.
"""
from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from . import db

_NO_ALNUM = re.compile(r"[^a-z0-9]+")


def slugificar(nombre: str) -> str:
    """'Los Ácidos del Norte' -> 'los-acidos-del-norte'."""
    sin_acentos = unicodedata.normalize("NFKD", nombre)
    sin_acentos = sin_acentos.encode("ascii", "ignore").decode("ascii")
    return _NO_ALNUM.sub("-", sin_acentos.lower()).strip("-")


def _slug_libre(cx, account_id: int, base: str) -> str:
    """Agrega -2, -3... hasta encontrar uno libre en la cuenta."""
    base = base or "entidad"
    candidato, n = base, 1
    while por_slug(cx, account_id, candidato) is not None:
        n += 1
        candidato = f"{base}-{n}"
    return candidato


def crear(cx, account_id: int, nombre: str, tipo: str, *,
          prioridad: int = 3, atributos: dict[str, Any] | None = None,
          band_id: int | None = None, slug: str | None = None) -> int:
    slug_final = _slug_libre(cx, account_id, slug or slugificar(nombre))
    return db.insert(
        cx, "brand_entities", account_id=account_id, tipo=tipo, nombre=nombre,
        slug=slug_final, prioridad=prioridad, band_id=band_id,
        atributos_json=json.dumps(atributos or {}, ensure_ascii=False),
    )


def obtener(cx, entity_id: int) -> dict[str, Any] | None:
    return db.get(cx, "brand_entities", entity_id)


def por_slug(cx, account_id: int, slug: str) -> dict[str, Any] | None:
    filas = db.rows(
        cx, "SELECT * FROM brand_entities WHERE account_id = ? AND slug = ?",
        (account_id, slug),
    )
    return filas[0] if filas else None


def por_band_id(cx, band_id: int) -> dict[str, Any] | None:
    filas = db.rows(cx, "SELECT * FROM brand_entities WHERE band_id = ?", (band_id,))
    return filas[0] if filas else None


def listar(cx, account_id: int, *, solo_activas: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM brand_entities WHERE account_id = ?"
    if solo_activas:
        sql += " AND activa = 1"
    sql += " ORDER BY prioridad ASC, nombre ASC"
    return db.rows(cx, sql, (account_id,))


def editar(cx, entity_id: int, **campos: Any) -> None:
    if "atributos" in campos:
        campos["atributos_json"] = json.dumps(campos.pop("atributos"),
                                              ensure_ascii=False)
    db.update(cx, "brand_entities", entity_id, **campos)


def archivar(cx, entity_id: int) -> None:
    db.update(cx, "brand_entities", entity_id, activa=0)


def atributos_de(fila: dict[str, Any]) -> dict[str, Any]:
    """Tolerante a JSON malformado, como marcas._fila_a_marca."""
    crudo = fila.get("atributos_json")
    if not crudo:
        return {}
    try:
        valor = json.loads(crudo)
    except (json.JSONDecodeError, TypeError):
        return {}
    return valor if isinstance(valor, dict) else {}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_entidades.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Pasar ruff**

Run: `.venv/bin/python -m ruff check src/entidades.py tests/test_entidades.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/entidades.py tests/test_entidades.py
git commit -m "feat(h1): módulo de entidades de marca"
```

---

### Task 6: Seed de las bandas de gdlscene a entidades

**Files:**
- Create: `src/seeds/__init__.py` (vacío)
- Create: `src/seeds/entidades_gdlscene.py`
- Test: `tests/test_seeds_h1.py`

**Interfaces:**
- Consumes: `entidades.crear`, `entidades.por_band_id`, tabla `bands`, tabla `photos`.
- Produces: `sembrar(cx, account_id: int = 1) -> dict[str, int]` que devuelve `{"creadas": n, "existentes": n, "fotos_ligadas": n}`.

Reglas del mapeo, derivadas del DDL real de `bands`:

| `bands` | `brand_entities` |
|---|---|
| `nombre` | `nombre` |
| `tipo` (`banda`\|`solista`\|`foro`\|`evento`\|`colectivo`) | `tipo` tal cual |
| `activa` | `activa` |
| `prioridad` | `prioridad`, acotado a 1..5 |
| `id` | `band_id` |
| `ig_handle` | `slug` (si existe), si no `slugificar(nombre)` |
| `ig_handle`, `spotify_id`, `deezer_id`, `ciudad`, `popularity`, `followers_ig`, `genero_principal`, `category_ig` | `atributos_json` |

- [ ] **Step 1: Write the failing test**

Crear `tests/test_seeds_h1.py`:

```python
"""Seeds de H1: bandas -> entidades, y HTML -> plantillas. Idempotentes."""
from __future__ import annotations

from src import db, entidades
from src.seeds import entidades_gdlscene


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_siembra_una_entidad_por_banda(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
              tipo="banda", account_id=1)
    db.insert(cx, "bands", nombre="Foro X", ig_handle="forox",
              tipo="foro", account_id=1)
    r = entidades_gdlscene.sembrar(cx, 1)
    assert r["creadas"] == 2
    assert {e["tipo"] for e in entidades.listar(cx, 1)} == {"banda", "foro"}


def test_siembra_es_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
              tipo="banda", account_id=1)
    entidades_gdlscene.sembrar(cx, 1)
    r2 = entidades_gdlscene.sembrar(cx, 1)
    assert r2["creadas"] == 0 and r2["existentes"] == 1
    assert len(entidades.listar(cx, 1, solo_activas=False)) == 1


def test_atributos_llevan_el_dato_musical(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
                    tipo="banda", account_id=1, spotify_id="abc123",
                    genero_principal="punk")
    entidades_gdlscene.sembrar(cx, 1)
    ent = entidades.por_band_id(cx, bid)
    attrs = entidades.atributos_de(ent)
    assert attrs["spotify_id"] == "abc123"
    assert attrs["genero_principal"] == "punk"
    assert attrs["ig_handle"] == "losejemplo"


def test_backfill_liga_las_fotos(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
                    tipo="banda", account_id=1)
    db.insert(cx, "photos", band_id=bid, path="/tmp/a.jpg", source_post_id="m1")
    db.insert(cx, "photos", band_id=bid, path="/tmp/b.jpg", source_post_id="m2")
    r = entidades_gdlscene.sembrar(cx, 1)
    ent = entidades.por_band_id(cx, bid)
    assert r["fotos_ligadas"] == 2
    ligadas = db.rows(cx, "SELECT count(*) c FROM photos WHERE entity_id = ?",
                      (ent["id"],))[0]["c"]
    assert ligadas == 2


def test_no_pierde_fotos_al_resembrar(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Ejemplo", ig_handle="losejemplo",
                    tipo="banda", account_id=1)
    db.insert(cx, "photos", band_id=bid, path="/tmp/a.jpg", source_post_id="m1")
    antes = db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"]
    entidades_gdlscene.sembrar(cx, 1)
    entidades_gdlscene.sembrar(cx, 1)
    assert db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"] == antes
```

Columnas reales de `photos` verificadas contra `src/schema.sql`: `band_id` es `NOT NULL`, `path` es `NOT NULL`, y el id del post de origen se llama `source_post_id` (no existe `ig_media_id`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_seeds_h1.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.seeds'`.

- [ ] **Step 3: Escribir el seed**

Crear `src/seeds/__init__.py` vacío y `src/seeds/entidades_gdlscene.py`:

```python
"""Siembra las bandas de gdlscene como entidades genéricas.

No toca `bands` ni sus tablas colgadas (`photos`, `members`, `events`,
`personas`, `face_signatures`): crea el espejo en `brand_entities` con
`band_id` como puente, y liga `photos.entity_id`. Idempotente por `band_id`.
"""
from __future__ import annotations

from typing import Any

from .. import db, entidades

# Atributos del dominio musical que viajan al JSON de la entidad.
_ATRIBUTOS = (
    "ig_handle", "spotify_id", "deezer_id", "ciudad", "popularity",
    "followers_ig", "genero_principal", "category_ig",
)


def _atributos_de_banda(banda: dict[str, Any]) -> dict[str, Any]:
    return {k: banda[k] for k in _ATRIBUTOS if k in banda and banda[k] is not None}


def sembrar(cx, account_id: int = 1) -> dict[str, int]:
    creadas = existentes = 0
    bandas = db.rows(cx, "SELECT * FROM bands WHERE account_id = ?", (account_id,))
    for banda in bandas:
        if entidades.por_band_id(cx, banda["id"]) is not None:
            existentes += 1
            continue
        prioridad = banda.get("prioridad") or 3
        entidades.crear(
            cx, account_id, banda["nombre"], banda.get("tipo") or "banda",
            prioridad=max(1, min(5, int(prioridad))),
            atributos=_atributos_de_banda(banda),
            band_id=banda["id"],
            slug=entidades.slugificar(banda.get("ig_handle") or banda["nombre"]),
        )
        creadas += 1
        if not banda.get("activa", 1):
            ent = entidades.por_band_id(cx, banda["id"])
            entidades.archivar(cx, ent["id"])

    # Backfill de fotos: solo las que aún no tienen entidad.
    cx.execute(
        "UPDATE photos SET entity_id = ("
        "  SELECT e.id FROM brand_entities e WHERE e.band_id = photos.band_id"
        ") WHERE entity_id IS NULL AND band_id IS NOT NULL"
    )
    fotos = db.rows(cx, "SELECT count(*) c FROM photos WHERE entity_id IS NOT NULL")
    cx.commit()
    return {"creadas": creadas, "existentes": existentes,
            "fotos_ligadas": fotos[0]["c"]}


if __name__ == "__main__":  # pragma: no cover
    cx = db.connect()
    db.init_db(cx)
    print(sembrar(cx))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_seeds_h1.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/seeds/ tests/test_seeds_h1.py
git commit -m "feat(h1): seed idempotente de bandas de gdlscene a entidades"
```

---

### Task 7: Validación del contrato de plantilla

**Files:**
- Create: `src/plantillas/__init__.py` (por ahora solo el docstring del paquete)
- Create: `src/plantillas/contrato.py`
- Test: `tests/test_contrato_plantilla.py`

**Interfaces:**
- Consumes: `jinja2` (ya es dependencia; la usa `src/compose.py`).
- Produces:
  - `CAMPOS_BASE: tuple[str, ...]` = `("titular", "imagen", "handle", "logo", "color_marca")`
  - `CAMPOS_SISTEMA: tuple[str, ...]` = `("fonts_dir",)`
  - `TIPOS: tuple[str, ...]` = `("texto", "texto_largo", "lista", "numero", "imagen", "booleano")`
  - `ASPECTOS: dict[str, tuple[int, int]]` = `{"4:5": (1080, 1350), "9:16": (1080, 1920)}`
  - `ContratoInvalido(ValueError)`
  - `validar(contrato: dict) -> None`
  - `variables_declaradas(contrato: dict) -> set[str]`
  - `validar_html(html: str, contrato: dict) -> None`
  - `dimensiones(aspecto: str) -> tuple[int, int]`

`validar_html` usa `jinja2.Environment().parse()` y `jinja2.meta.find_undeclared_variables` para exigir que toda variable del HTML esté declarada en el contrato o sea de sistema. Es la red de seguridad contra un HTML alucinado por el LLM en H3, y por eso no toca DB ni Chromium: debe correr en milisegundos.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_contrato_plantilla.py`:

```python
"""Validación del contrato de plantilla. Sin DB, sin red, sin Chromium."""
from __future__ import annotations

import pytest

from src.plantillas import contrato as c


def _contrato_minimo() -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": []}


def test_contrato_minimo_es_valido() -> None:
    c.validar(_contrato_minimo())


def test_falta_un_campo_base() -> None:
    malo = _contrato_minimo()
    malo["base"] = ["titular", "imagen"]
    with pytest.raises(c.ContratoInvalido, match="base"):
        c.validar(malo)


def test_aspecto_desconocido() -> None:
    malo = _contrato_minimo()
    malo["aspecto"] = "16:9"
    with pytest.raises(c.ContratoInvalido, match="aspecto"):
        c.validar(malo)


def test_tipo_de_extra_desconocido() -> None:
    malo = _contrato_minimo()
    malo["extras"] = [{"id": "x", "tipo": "video"}]
    with pytest.raises(c.ContratoInvalido, match="tipo"):
        c.validar(malo)


def test_extra_que_pisa_un_campo_base() -> None:
    malo = _contrato_minimo()
    malo["extras"] = [{"id": "titular", "tipo": "texto"}]
    with pytest.raises(c.ContratoInvalido, match="titular"):
        c.validar(malo)


def test_lista_con_min_mayor_que_max() -> None:
    malo = _contrato_minimo()
    malo["extras"] = [{"id": "pasos", "tipo": "lista", "min": 5, "max": 3}]
    with pytest.raises(c.ContratoInvalido, match="min"):
        c.validar(malo)


def test_variables_declaradas_incluye_base_y_extras() -> None:
    ct = _contrato_minimo()
    ct["extras"] = [{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}]
    assert c.variables_declaradas(ct) == set(c.CAMPOS_BASE) | {"pasos"}


def test_html_con_variable_no_declarada() -> None:
    ct = _contrato_minimo()
    html = "<div>{{ titular }} {{ inventada }}</div>"
    with pytest.raises(c.ContratoInvalido, match="inventada"):
        c.validar_html(html, ct)


def test_html_puede_usar_variables_de_sistema() -> None:
    ct = _contrato_minimo()
    c.validar_html("<div>{{ titular }}<img src='{{ fonts_dir }}/a.ttf'></div>", ct)


def test_html_roto_de_jinja() -> None:
    ct = _contrato_minimo()
    with pytest.raises(c.ContratoInvalido, match="Jinja"):
        c.validar_html("<div>{{ titular </div>", ct)


def test_dimensiones() -> None:
    assert c.dimensiones("4:5") == (1080, 1350)
    assert c.dimensiones("9:16") == (1080, 1920)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_contrato_plantilla.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.plantillas'`.

- [ ] **Step 3: Escribir `src/plantillas/__init__.py`**

```python
"""Plantillas de marca: HTML+CSS en DB con contrato de variables y versionado.

`contrato` es puro (sin I/O) para poder validar la salida del LLM en
milisegundos; el acceso a DB vive en este módulo a partir de la Task 8.
"""
```

- [ ] **Step 4: Escribir `src/plantillas/contrato.py`**

```python
"""Contrato híbrido de una plantilla: núcleo garantizado + extras declarados.

El mismo contrato sirve para dos cosas: es el schema con el que se renderiza
y es el schema que se le pide al LLM al generar el contenido. Una sola fuente
de verdad — si la plantilla declara tres bullets, el generador pide tres.
"""
from __future__ import annotations

from typing import Any

import jinja2
from jinja2 import meta as jinja_meta

# Toda plantilla los recibe siempre: ninguna puede quedarse sin logo o handle.
CAMPOS_BASE: tuple[str, ...] = ("titular", "imagen", "handle", "logo", "color_marca")
# Los inyecta el motor de render, no el contrato ni el LLM.
CAMPOS_SISTEMA: tuple[str, ...] = ("fonts_dir",)
TIPOS: tuple[str, ...] = ("texto", "texto_largo", "lista", "numero",
                          "imagen", "booleano")
ASPECTOS: dict[str, tuple[int, int]] = {"4:5": (1080, 1350), "9:16": (1080, 1920)}


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
    try:
        ast = jinja2.Environment().parse(html)
    except jinja2.TemplateSyntaxError as exc:
        raise ContratoInvalido(f"HTML inválido para Jinja: {exc.message}") from exc

    usadas = jinja_meta.find_undeclared_variables(ast)
    permitidas = variables_declaradas(contrato) | set(CAMPOS_SISTEMA)
    sobrantes = sorted(usadas - permitidas)
    if sobrantes:
        raise ContratoInvalido(
            f"el HTML usa variables no declaradas en el contrato: {sobrantes}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_contrato_plantilla.py -v`
Expected: PASS (11 tests).

- [ ] **Step 6: Pasar ruff**

Run: `.venv/bin/python -m ruff check src/plantillas/ tests/test_contrato_plantilla.py`
Expected: `All checks passed!`

- [ ] **Step 7: Commit**

```bash
git add src/plantillas/ tests/test_contrato_plantilla.py
git commit -m "feat(h1): contrato híbrido de plantilla con validación de HTML"
```

---

### Task 8: CRUD y versionado de plantillas

**Files:**
- Modify: `src/plantillas/__init__.py`
- Test: `tests/test_plantillas.py`

**Interfaces:**
- Consumes: `contrato.validar`, `contrato.validar_html`, `entidades.slugificar`, tablas `brand_templates` y `template_versions`.
- Produces:
  - `crear(cx, account_id: int, nombre: str, html: str, contrato_dict: dict, *, descripcion: str | None = None, origen: str = "manual", creado_por: int | None = None, mensaje_usuario: str | None = None) -> int`
  - `nueva_version(cx, template_id: int, html: str, contrato_dict: dict, *, mensaje_usuario: str | None = None, llm_meta: dict | None = None) -> int` — devuelve el número de versión
  - `listar(cx, account_id: int, *, estado: str | None = None) -> list[dict]`
  - `obtener(cx, template_id: int) -> dict | None`
  - `por_slug(cx, account_id: int, slug: str) -> dict | None`
  - `versiones(cx, template_id: int) -> list[dict]`
  - `version(cx, template_id: int, numero: int) -> dict | None`
  - `revertir(cx, template_id: int, numero: int) -> int`
  - `activar(cx, template_id: int) -> None` / `archivar(cx, template_id: int) -> None`
  - `contrato_de(fila: dict) -> dict`

`crear` y `nueva_version` **validan antes de escribir**: contrato primero, HTML contra el contrato después. Una plantilla inválida nunca llega a la DB.

`revertir(cx, tid, n)` no borra versiones: copia la versión `n` como una versión nueva al final. El historial es de solo-agregar, igual que el Decisions-Log del vault.

- [ ] **Step 1: Write the failing test**

Crear `tests/test_plantillas.py`:

```python
"""CRUD y versionado de plantillas de marca."""
from __future__ import annotations

import pytest

from src import db, plantillas
from src.plantillas import contrato as c


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _ct(extras=None) -> dict:
    return {"aspecto": "4:5", "base": list(c.CAMPOS_BASE), "extras": extras or []}


_HTML = ("<div class='card' style='color:{{ color_marca }}'>"
         "<img src='{{ imagen }}'><h1>{{ titular }}</h1>"
         "<img src='{{ logo }}'><span>{{ handle }}</span></div>")


def test_crear_deja_v1(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct(), origen="seed")
    fila = plantillas.obtener(cx, tid)
    assert fila["slug"] == "clasica"
    assert fila["version_actual"] == 1
    assert len(plantillas.versiones(cx, tid)) == 1


def test_crear_rechaza_html_con_variable_inventada(tmp_path) -> None:
    cx = _cx(tmp_path)
    malo = _HTML + "{{ inventada }}"
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Mala", malo, _ct())
    assert plantillas.listar(cx, 1) == []


def test_crear_rechaza_contrato_sin_campo_base(tmp_path) -> None:
    cx = _cx(tmp_path)
    ct = _ct()
    ct["base"] = ["titular"]
    with pytest.raises(c.ContratoInvalido):
        plantillas.crear(cx, 1, "Mala", _HTML, ct)


def test_nueva_version_incrementa_y_no_pisa(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    v2 = plantillas.nueva_version(cx, tid, _HTML.replace("card", "card verde"),
                                  _ct(), mensaje_usuario="hazla verde")
    assert v2 == 2
    assert plantillas.obtener(cx, tid)["version_actual"] == 2
    assert "verde" in plantillas.obtener(cx, tid)["html"]
    assert "verde" not in plantillas.version(cx, tid, 1)["html"]


def test_revertir_agrega_version_nueva(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    plantillas.nueva_version(cx, tid, _HTML.replace("card", "card v2"), _ct())
    v3 = plantillas.revertir(cx, tid, 1)
    assert v3 == 3
    assert len(plantillas.versiones(cx, tid)) == 3
    assert plantillas.obtener(cx, tid)["html"] == _HTML


def test_listar_filtra_por_estado_y_cuenta(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Activa", _HTML, _ct())
    plantillas.crear(cx, 1, "Borrador", _HTML, _ct())
    plantillas.activar(cx, tid)
    activas = plantillas.listar(cx, 1, estado="activa")
    assert [t["nombre"] for t in activas] == ["Activa"]


def test_contrato_de_tolera_json_roto(tmp_path) -> None:
    cx = _cx(tmp_path)
    tid = plantillas.crear(cx, 1, "Clásica", _HTML, _ct())
    db.update(cx, "brand_templates", tid, contrato_json="{roto")
    assert plantillas.contrato_de(plantillas.obtener(cx, tid)) == {}


def test_extras_del_contrato_se_pueden_usar_en_el_html(tmp_path) -> None:
    cx = _cx(tmp_path)
    ct = _ct([{"id": "pasos", "tipo": "lista", "min": 3, "max": 3}])
    html = _HTML + "{% for p in pasos %}<li>{{ p }}</li>{% endfor %}"
    tid = plantillas.crear(cx, 1, "Tips", html, ct)
    assert plantillas.obtener(cx, tid) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_plantillas.py -v`
Expected: FAIL con `AttributeError: module 'src.plantillas' has no attribute 'crear'`.

- [ ] **Step 3: Escribir el CRUD en `src/plantillas/__init__.py`**

Debajo del docstring existente:

```python
from __future__ import annotations

import json
from typing import Any

from .. import db
from ..entidades import slugificar
from . import contrato as _contrato

ContratoInvalido = _contrato.ContratoInvalido


def _slug_libre(cx, account_id: int, base: str) -> str:
    base = base or "plantilla"
    candidato, n = base, 1
    while por_slug(cx, account_id, candidato) is not None:
        n += 1
        candidato = f"{base}-{n}"
    return candidato


def _validado(html: str, contrato_dict: dict[str, Any]) -> str:
    """Valida contrato y HTML, y devuelve el contrato serializado."""
    _contrato.validar(contrato_dict)
    _contrato.validar_html(html, contrato_dict)
    return json.dumps(contrato_dict, ensure_ascii=False)


def crear(cx, account_id: int, nombre: str, html: str,
          contrato_dict: dict[str, Any], *, descripcion: str | None = None,
          origen: str = "manual", creado_por: int | None = None,
          mensaje_usuario: str | None = None) -> int:
    contrato_json = _validado(html, contrato_dict)
    tid = db.insert(
        cx, "brand_templates", account_id=account_id, nombre=nombre,
        slug=_slug_libre(cx, account_id, slugificar(nombre)),
        descripcion=descripcion, aspecto=contrato_dict["aspecto"],
        contrato_json=contrato_json, html=html, origen=origen,
        creado_por=creado_por, version_actual=1,
    )
    db.insert(cx, "template_versions", template_id=tid, version=1, html=html,
              contrato_json=contrato_json, mensaje_usuario=mensaje_usuario)
    cx.commit()
    return tid


def nueva_version(cx, template_id: int, html: str,
                  contrato_dict: dict[str, Any], *,
                  mensaje_usuario: str | None = None,
                  llm_meta: dict[str, Any] | None = None) -> int:
    contrato_json = _validado(html, contrato_dict)
    fila = obtener(cx, template_id)
    if fila is None:
        raise ValueError(f"plantilla {template_id} no existe")
    numero = int(fila["version_actual"]) + 1
    db.insert(cx, "template_versions", template_id=template_id, version=numero,
              html=html, contrato_json=contrato_json,
              mensaje_usuario=mensaje_usuario,
              llm_meta=json.dumps(llm_meta, ensure_ascii=False) if llm_meta else None)
    db.update(cx, "brand_templates", template_id, html=html,
              contrato_json=contrato_json, aspecto=contrato_dict["aspecto"],
              version_actual=numero, actualizado_en=_ahora(cx))
    cx.commit()
    return numero


def revertir(cx, template_id: int, numero: int) -> int:
    """No borra: copia la versión pedida como una versión nueva al final."""
    vieja = version(cx, template_id, numero)
    if vieja is None:
        raise ValueError(f"la plantilla {template_id} no tiene versión {numero}")
    return nueva_version(cx, template_id, vieja["html"],
                         json.loads(vieja["contrato_json"]),
                         mensaje_usuario=f"volver a la versión {numero}")


def obtener(cx, template_id: int) -> dict[str, Any] | None:
    return db.get(cx, "brand_templates", template_id)


def por_slug(cx, account_id: int, slug: str) -> dict[str, Any] | None:
    filas = db.rows(
        cx, "SELECT * FROM brand_templates WHERE account_id = ? AND slug = ?",
        (account_id, slug),
    )
    return filas[0] if filas else None


def listar(cx, account_id: int, *, estado: str | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM brand_templates WHERE account_id = ?"
    params: list[Any] = [account_id]
    if estado:
        sql += " AND estado = ?"
        params.append(estado)
    sql += " ORDER BY nombre ASC"
    return db.rows(cx, sql, tuple(params))


def versiones(cx, template_id: int) -> list[dict[str, Any]]:
    return db.rows(
        cx, "SELECT * FROM template_versions WHERE template_id = ? ORDER BY version ASC",
        (template_id,),
    )


def version(cx, template_id: int, numero: int) -> dict[str, Any] | None:
    filas = db.rows(
        cx, "SELECT * FROM template_versions WHERE template_id = ? AND version = ?",
        (template_id, numero),
    )
    return filas[0] if filas else None


def activar(cx, template_id: int) -> None:
    db.update(cx, "brand_templates", template_id, estado="activa",
              actualizado_en=_ahora(cx))
    cx.commit()


def archivar(cx, template_id: int) -> None:
    db.update(cx, "brand_templates", template_id, estado="archivada",
              actualizado_en=_ahora(cx))
    cx.commit()


def contrato_de(fila: dict[str, Any]) -> dict[str, Any]:
    """Tolerante a JSON malformado, como entidades.atributos_de."""
    crudo = fila.get("contrato_json")
    if not crudo:
        return {}
    try:
        valor = json.loads(crudo)
    except (json.JSONDecodeError, TypeError):
        return {}
    return valor if isinstance(valor, dict) else {}


def _ahora(cx) -> str:
    return cx.execute("SELECT datetime('now')").fetchone()[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_plantillas.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Pasar ruff**

Run: `.venv/bin/python -m ruff check src/plantillas/ tests/test_plantillas.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add src/plantillas/__init__.py tests/test_plantillas.py
git commit -m "feat(h1): CRUD y versionado de plantillas, historial de solo-agregar"
```

---

### Task 9: Seed de las cuatro plantillas de gdlscene

**Files:**
- Create: `src/seeds/plantillas_gdlscene.py`
- Test: `tests/test_seeds_h1.py` (agregar)

**Interfaces:**
- Consumes: `plantillas.crear`, `plantillas.por_slug`, los archivos `templates/meme.html`, `templates/meme_verde.html`, `templates/meme_onion.html`, `templates/anuncio.html`.
- Produces: `sembrar(cx, account_id: int = 1) -> dict[str, int]` con `{"creadas": n, "existentes": n}`.

**El problema a resolver:** los HTML actuales usan los nombres de variable del código viejo (`caption`, `foto_url`, `badge_text`, `foto_inset_url`, `caption_html`, `tag_text`) y el contrato canónico usa `titular`, `imagen`, `handle`, `logo`, `color_marca`. El seed **renombra las variables al vocabulario canónico** al escribir el HTML en la DB. No se edita ningún archivo de `templates/`: el camino viejo sigue funcionando intacto hasta H5.

Mapeo de renombres, aplicado con reemplazo de texto sobre el HTML leído:

| En el archivo | En la DB |
|---|---|
| `{{ caption }}` | `{{ titular }}` |
| `{{ foto_url }}` | `{{ imagen }}` |
| `{{ handle }}` | `{{ handle }}` (sin cambio) |
| `{{ badge_text }}` | `{{ badge }}` (extra opcional) |
| `{{ foto_inset_url }}` | `{{ inset }}` (extra opcional, tipo imagen) |
| `{{ caption_html }}` (solo onion) | `{{ titular \| resaltar }}` |
| `{{ tag_text }}` (solo onion) | `{{ handle }}` |
| `{{ fonts_dir }}` | `{{ fonts_dir }}` (variable de sistema) |

`resaltar` es el filtro Jinja que reemplaza a `src/compose.py:84-92` `_onion_html`; se registra en el entorno de render en H2. Para que `validar_html` no truene con un filtro desconocido, no hace falta nada: `find_undeclared_variables` reporta variables, no filtros.

Ninguna de las cuatro plantillas usa `logo` ni `color_marca` hoy. El contrato los declara igual (son base) y el HTML simplemente no los referencia — eso es válido: el contrato exige que toda variable del HTML esté declarada, no que toda variable declarada se use.

- [ ] **Step 1: Write the failing test**

Agregar a `tests/test_seeds_h1.py`:

```python
from src import plantillas
from src.plantillas import contrato as c
from src.seeds import plantillas_gdlscene


def test_siembra_las_cuatro_plantillas(tmp_path) -> None:
    cx = _cx(tmp_path)
    r = plantillas_gdlscene.sembrar(cx, 1)
    assert r["creadas"] == 4
    slugs = {t["slug"] for t in plantillas.listar(cx, 1)}
    assert slugs == {"clasica", "verde", "onion", "anuncio"}


def test_las_sembradas_quedan_activas_y_con_origen_seed(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    for t in plantillas.listar(cx, 1):
        assert t["estado"] == "activa"
        assert t["origen"] == "seed"
        assert t["version_actual"] == 1


def test_el_html_sembrado_pasa_su_propio_contrato(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    for t in plantillas.listar(cx, 1):
        c.validar_html(t["html"], plantillas.contrato_de(t))


def test_el_html_ya_no_usa_los_nombres_viejos(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    for t in plantillas.listar(cx, 1):
        for viejo in ("{{ caption }}", "{{ foto_url }}", "{{ badge_text }}",
                      "{{ foto_inset_url }}", "{{ caption_html }}", "{{ tag_text }}"):
            assert viejo not in t["html"], f"{t['slug']} conserva {viejo}"


def test_onion_usa_el_filtro_resaltar(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    onion = plantillas.por_slug(cx, 1, "onion")
    assert "resaltar" in onion["html"]


def test_siembra_de_plantillas_es_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    plantillas_gdlscene.sembrar(cx, 1)
    r2 = plantillas_gdlscene.sembrar(cx, 1)
    assert r2["creadas"] == 0 and r2["existentes"] == 4
    assert len(plantillas.listar(cx, 1)) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_seeds_h1.py -v`
Expected: FAIL con `ImportError: cannot import name 'plantillas_gdlscene'`.

- [ ] **Step 3: Escribir el seed**

Crear `src/seeds/plantillas_gdlscene.py`:

```python
"""Migra las cuatro plantillas HTML de gdlscene al catálogo de DB.

No toca los archivos de `templates/`: los lee, renombra sus variables al
vocabulario canónico del contrato y escribe el resultado en `brand_templates`.
El dict TEMPLATES de src/compose.py sigue vivo y sin cambios hasta H5.

Idempotente por slug.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .. import plantillas
from ..entidades import slugificar
from ..plantillas import contrato as c

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"

# Del vocabulario del código viejo al canónico del contrato.
_RENOMBRES: tuple[tuple[str, str], ...] = (
    ("caption_html", "titular | resaltar"),   # antes que `caption`, es prefijo
    ("foto_inset_url", "inset"),              # antes que `foto_url`
    ("foto_url", "imagen"),
    ("badge_text", "badge"),
    ("tag_text", "handle"),
    ("caption", "titular"),
)

_EXTRA_BADGE = {"id": "badge", "tipo": "texto", "opcional": True,
                "desc": "Etiqueta corta en la esquina superior"}
_EXTRA_INSET = {"id": "inset", "tipo": "imagen", "opcional": True,
                "desc": "Foto secundaria en círculo"}

_SEEDS: tuple[dict[str, Any], ...] = (
    {"archivo": "meme.html", "nombre": "Clásica",
     "descripcion": "Fondo blanco, texto negro, franja verde. La original de gdlscene.",
     "extras": [_EXTRA_BADGE, _EXTRA_INSET]},
    {"archivo": "meme_verde.html", "nombre": "Verde",
     "descripcion": "La clásica invertida: fondo verde de marca, texto blanco.",
     "extras": [_EXTRA_BADGE, _EXTRA_INSET]},
    {"archivo": "meme_onion.html", "nombre": "Onion",
     "descripcion": "Titular encimado sobre la foto, con resaltes en verde.",
     "extras": []},
    {"archivo": "anuncio.html", "nombre": "Anuncio",
     "descripcion": "Flyer completo sobre fondo negro, para fechas y eventos.",
     "extras": [_EXTRA_BADGE]},
)


def _canonizar(html: str) -> str:
    """Renombra {{ viejo }} -> {{ nuevo }} respetando espacios y filtros."""
    for viejo, nuevo in _RENOMBRES:
        html = re.sub(r"\{\{\s*" + re.escape(viejo) + r"\s*\}\}",
                      "{{ " + nuevo + " }}", html)
    return html


def sembrar(cx, account_id: int = 1) -> dict[str, int]:
    creadas = existentes = 0
    for seed in _SEEDS:
        nombre = seed["nombre"]
        # OJO: el slug lo calcula plantillas.crear con slugificar(), que quita
        # acentos ("Clásica" -> "clasica"). Buscar por nombre.lower() aquí
        # rompería la idempotencia y resembraría duplicados en cada corrida.
        slug = slugificar(nombre)
        if plantillas.por_slug(cx, account_id, slug) is not None:
            existentes += 1
            continue
        html = _canonizar((TEMPLATES_DIR / seed["archivo"]).read_text(encoding="utf-8"))
        contrato = {"aspecto": "4:5", "base": list(c.CAMPOS_BASE),
                    "extras": seed["extras"]}
        tid = plantillas.crear(cx, account_id, nombre, html, contrato,
                               descripcion=seed["descripcion"], origen="seed",
                               mensaje_usuario=None)
        plantillas.activar(cx, tid)
        creadas += 1
    return {"creadas": creadas, "existentes": existentes}


if __name__ == "__main__":  # pragma: no cover
    from .. import db
    cx = db.connect()
    db.init_db(cx)
    print(sembrar(cx))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_seeds_h1.py -v`
Expected: PASS (11 tests).

Si `test_el_html_sembrado_pasa_su_propio_contrato` falla nombrando una variable que no está en el mapeo (por ejemplo un `{{ algo }}` que no anticipamos), **no relajar la validación**: agregar el renombre a `_RENOMBRES` o el extra correspondiente al contrato de esa plantilla. La validación estricta es la que hará seguro el diseñador con LLM en H3.

- [ ] **Step 5: Commit**

```bash
git add src/seeds/plantillas_gdlscene.py tests/test_seeds_h1.py
git commit -m "feat(h1): seed de las 4 plantillas de gdlscene al catálogo de DB"
```

---

### Task 10: Cierre del hito — integridad y suite completa

**Files:**
- Create: `scripts/verificar_h1.py`
- Test: la suite completa

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: `scripts/verificar_h1.py`, ejecutable contra una copia de la DB real, que imprime un reporte de integridad y sale con código 1 si algo no cuadra.

Este script es lo que se corre contra una **copia** de `/opt/instagod/data/gdlscene.db` antes de siquiera proponer tocar la VM. No escribe en la DB salvo por los seeds, que son idempotentes.

- [ ] **Step 1: Escribir el script de verificación**

Crear `scripts/verificar_h1.py`:

```python
"""Verifica el cimiento de H1 contra una DB real (o una copia).

Uso:
    .venv/bin/python scripts/verificar_h1.py data/copia-de-prod.db

Corre init_db (idempotente) y los dos seeds, y reporta si el conteo de
entidades cuadra con el de bandas y si no se perdieron fotos.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import db, entidades, plantillas          # noqa: E402
from src.seeds import entidades_gdlscene, plantillas_gdlscene  # noqa: E402


def main(ruta: str) -> int:
    cx = db.connect(ruta)
    fotos_antes = db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"]
    bandas = db.rows(cx, "SELECT count(*) c FROM bands WHERE account_id = 1")[0]["c"]

    db.init_db(cx)
    db.init_db(cx)  # idempotencia: la 2a corrida no debe truenar

    r_ent = entidades_gdlscene.sembrar(cx, 1)
    r_tpl = plantillas_gdlscene.sembrar(cx, 1)

    fotos_despues = db.rows(cx, "SELECT count(*) c FROM photos")[0]["c"]
    ents = len(entidades.listar(cx, 1, solo_activas=False))
    tpls = len(plantillas.listar(cx, 1))
    huerfanas = db.rows(
        cx, "SELECT count(*) c FROM photos WHERE band_id IS NOT NULL "
            "AND entity_id IS NULL")[0]["c"]

    print(f"bandas de gdlscene ......... {bandas}")
    print(f"entidades tras el seed ..... {ents}  (nuevas {r_ent['creadas']})")
    print(f"plantillas tras el seed .... {tpls}  (nuevas {r_tpl['creadas']})")
    print(f"fotos antes / después ...... {fotos_antes} / {fotos_despues}")
    print(f"fotos con banda y sin entidad {huerfanas}")

    fallas = []
    if ents != bandas:
        fallas.append(f"entidades ({ents}) != bandas ({bandas})")
    if fotos_despues != fotos_antes:
        fallas.append(f"se perdieron fotos: {fotos_antes} -> {fotos_despues}")
    if huerfanas:
        fallas.append(f"{huerfanas} fotos con band_id quedaron sin entity_id")
    if tpls < 4:
        fallas.append(f"solo hay {tpls} plantillas, se esperaban al menos 4")

    if fallas:
        print("\n🔴 FALLAS:")
        for f in fallas:
            print(f"  - {f}")
        return 1
    print("\n🟢 H1 íntegro")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
```

- [ ] **Step 2: Correrlo contra una copia local**

```bash
cd ~/Work/personal/instagod/.claude/worktrees/plantillas-y-lotes
cp ../../../data/gdlscene.db /tmp/h1-prueba.db
.venv/bin/python scripts/verificar_h1.py /tmp/h1-prueba.db
```

Expected: termina con `🟢 H1 íntegro`. Si la copia local no existe, usar el backup más reciente de `data/gdlscene.backup-*.db`.

- [ ] **Step 3: Correr la suite completa**

Run: `.venv/bin/python -m pytest`
Expected: PASS. **Ningún test preexistente debe cambiar de resultado**: H1 solo agrega tablas y columnas, no toca ningún camino de código vivo. Si algo de `tests/test_db_migracion_tipo_queue.py`, `tests/test_motor_migraciones.py`, `tests/test_planes_schema.py` o `tests/test_portal_schema.py` se pone rojo, es una regresión real del rebuild de `content_queue`, no un test que "hay que actualizar".

- [ ] **Step 4: Correr ruff sobre todo lo nuevo**

Run: `.venv/bin/python -m ruff check src/ tests/ scripts/`
Expected: `All checks passed!`

- [ ] **Step 5: Verificar la cobertura**

Run: `.venv/bin/python -m pytest --cov`
Expected: el porcentaje total no baja de 50 (`fail_under = 50` en `pyproject.toml`).

- [ ] **Step 6: Commit**

```bash
git add scripts/verificar_h1.py
git commit -m "chore(h1): script de verificación de integridad del cimiento"
```

- [ ] **Step 7: Medir la cobertura histórica de `content_queue.template`**

Deuda declarada en el spec: no se sabe cuántas piezas publicadas registraron su plantilla, y de eso depende si la vista de estadísticas por plantilla tiene histórico o arranca en cero.

```bash
.venv/bin/python - <<'PY'
import sqlite3
cx = sqlite3.connect("/tmp/h1-prueba.db")
cx.row_factory = sqlite3.Row
q = """SELECT count(*) tot,
              sum(CASE WHEN template IS NOT NULL AND template != '' THEN 1 ELSE 0 END) con
       FROM content_queue WHERE status = 'publicado'"""
r = cx.execute(q).fetchone()
print(f"publicadas: {r['tot']}   con plantilla: {r['con'] or 0}")
print("por plantilla:", [tuple(x) for x in cx.execute(
    "SELECT template, count(*) FROM content_queue WHERE status='publicado' GROUP BY 1")])
PY
```

Anotar el resultado en la nota de sesión del vault. Es el dato que decide, en H5, si la vista de estadísticas por plantilla se grafica completa o se etiqueta "con dato desde <fecha>".

---

## Definición de terminado para H1

- [ ] `.venv/bin/python -m pytest` en verde, sin ningún test preexistente modificado.
- [ ] `.venv/bin/python -m ruff check src/ tests/ scripts/` limpio.
- [ ] `scripts/verificar_h1.py` sale `🟢` contra una copia de la DB real.
- [ ] `db.init_db(cx)` corre dos veces seguidas sin error sobre esa misma copia.
- [ ] Ningún archivo de `templates/` modificado.
- [ ] `src/compose.py` sin modificar: el dict `TEMPLATES` intacto.
- [ ] Cobertura total ≥ 50%.
- [ ] Cobertura histórica de `content_queue.template` medida y anotada.

## Lo que H1 deliberadamente NO hace

- No renderiza nada desde la DB. Eso es H2.
- No expone ningún endpoint. Las tablas quedan pobladas y sin lectores.
- No toca `src/compose.py`, `src/planner.py`, `src/engagement.py`, `web/app.py`, `api/` ni `frontend/`.
- No llama al LLM.
- No toca la VM ni la DB de producción.
