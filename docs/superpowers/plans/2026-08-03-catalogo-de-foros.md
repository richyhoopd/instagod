# Catálogo de foros canónicos — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que dos flyers del mismo evento se fusionen en un solo slide de la agenda aunque el foro venga escrito distinto (`REY` vs `Hake al Rey`), resolviendo el texto libre de `events.lugar` contra un catálogo de foros canónicos.

**Architecture:** Dos tablas nuevas (`venues` y `venue_alias`) y un módulo `src/venues.py` cuyo corazón es una función pura de normalización. La resolución en caliente es una búsqueda exacta de alias — sin LLM, sin fuzzy, determinista y auditable. El LLM trabaja una sola vez, en la siembra; lo que no reconoce queda como alias huérfano en una cola de curación en la GUI.

**Tech Stack:** Python 3.14, SQLite, FastAPI + HTMX, `difflib` de la librería estándar, DeepSeek vía el SDK de `openai` (solo en la siembra).

## Global Constraints

- **Sin dependencias nuevas de Python.** `difflib` es estándar; `openai` ya está instalado.
- Python 3.14; nada que compile extensiones de C.
- **`events.lugar` NUNCA se modifica.** Se conserva como texto crudo, rastro de auditoría y fallback. `venue_id` es una capa nueva encima.
- **El batch nunca pisa lo curado**: un alias con `origen='manual'` no lo reescribe la siembra. Misma regla que `bands.generos_fuente`.
- **Salas distintas son foros distintos** (decisión de Ricardo): `C3 Stage` y `C3 Rooftop` son dos entradas del catálogo, nunca se fusionan.
- Migraciones idempotentes: tablas nuevas en `src/schema.sql` con `CREATE TABLE IF NOT EXISTS`; columnas nuevas en `db._MIGRATIONS`, **sin cláusula `REFERENCES`** en `ADD COLUMN` (SQLite lo prohíbe con `foreign_keys=ON`).
- **Toda tabla nueva se registra en `db.TABLES`**, o `db.insert`/`db.update` la rechazan.
- Suite: `.venv/bin/python -m pytest` (nunca `python` a secas). **Dos fallos son PREEXISTENTES** y no cuentan como regresión: `tests/test_planner.py::test_plan_month_salta_slots_pasados` y `tests/test_segmentos_web.py::test_segmentos_lista_catalogo_y_preview`.
- Commits sin firma de Claude ni `Co-Authored-By`. Identidad: `richyhoopd <theilluminatiduck@gmail.com>`.
- **Ningún test llama al LLM ni a la red.** La siembra se prueba inyectando el cliente.

---

### Task 1: Esquema de venues y alias

**Files:**
- Modify: `src/schema.sql` (agregar al final)
- Modify: `src/db.py` (`TABLES`, `_MIGRATIONS`, índices en `init_db`)
- Test: `tests/test_venues.py`

**Interfaces:**
- Consumes: nada.
- Produces: tablas `venues` (id, nombre, ciudad, ig_handle, activa, created_at, updated_at) y `venue_alias` (id, venue_id, alias_norm UNIQUE, alias_visto, origen, created_at); columna `events.venue_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_venues.py
from __future__ import annotations

from pathlib import Path

import pytest

from src import db


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_migracion_crea_venues_y_alias(cx) -> None:
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"venues", "venue_alias"} <= tablas
    assert "venue_id" in {r["name"] for r in cx.execute("PRAGMA table_info(events)")}
    assert "venues" in db.TABLES and "venue_alias" in db.TABLES
    assert "venue_id" in db.TABLES["events"]


def test_alias_norm_es_unico(cx) -> None:
    import sqlite3
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    db.insert(cx, "venue_alias", venue_id=vid, alias_norm="hake al rey",
              alias_visto="Hake al Rey", origen="semilla")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "venue_alias", venue_id=vid, alias_norm="hake al rey",
                  alias_visto="HAKE AL REY", origen="llm")


def test_migracion_es_idempotente(cx) -> None:
    db.init_db(cx)
    db.init_db(cx)
    vid = db.insert(cx, "venues", nombre="Cuerda", ciudad="Guadalajara")
    assert db.get(cx, "venues", vid)["nombre"] == "Cuerda"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_venues.py -v`
Expected: FAIL — las tablas no existen.

- [ ] **Step 3: Write minimal implementation**

Al final de `src/schema.sql`:

```sql
-- -----------------------------------------------------------------------------
-- venues — foros canónicos. `events.lugar` es texto libre que un LLM saca del
-- OCR y trae el mismo foro con media docena de escrituras; esta tabla es la
-- identidad estable contra la que se resuelven. `ig_handle` liga al foro que ya
-- se sigue en `bands`, cuando existe.
-- Salas distintas = venues distintos (C3 Stage y C3 Rooftop son dos filas).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS venues (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    ciudad     TEXT,
    ig_handle  TEXT,
    activa     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- venue_alias — cada escritura vista de un foro, normalizada. venue_id NULL =
-- alias HUÉRFANO: texto visto en un flyer que nadie ha asignado todavía; es la
-- cola de curación de la GUI. `alias_visto` guarda el texto crudo porque al
-- curar hace falta ver qué decía el flyer, no la versión normalizada.
-- origen: 'semilla' | 'llm' | 'manual' | 'no_es_lugar'
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS venue_alias (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    venue_id    INTEGER,
    alias_norm  TEXT NOT NULL UNIQUE,
    alias_visto TEXT NOT NULL,
    origen      TEXT NOT NULL DEFAULT 'llm',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

En `src/db.py`, dentro de `TABLES`:

```python
    "venues": {"nombre", "ciudad", "ig_handle", "activa"},
    "venue_alias": {"venue_id", "alias_norm", "alias_visto", "origen"},
```

Y agregar `"venue_id"` al set de `TABLES["events"]`.

En `_MIGRATIONS`, dentro de `"events"`:

```python
        # Catálogo de foros: identidad estable del venue (NULL = sin resolver).
        "venue_id": "INTEGER",
```

En `init_db`, junto a los otros índices:

```python
                "CREATE INDEX IF NOT EXISTS idx_alias_venue ON venue_alias(venue_id)",
                "CREATE INDEX IF NOT EXISTS idx_events_venue ON events(venue_id)",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_venues.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/schema.sql src/db.py tests/test_venues.py
git commit -m "feat(venues): esquema de foros canonicos y alias"
```

---

### Task 2: Normalización y sugerencias (funciones puras)

**Files:**
- Create: `src/venues.py`
- Test: `tests/test_venues.py`

**Interfaces:**
- Consumes: nada.
- Produces: `venues.normalizar(s: str | None) -> str`; `venues.sugerencias(texto: str, candidatos: list[tuple[int, str]], tope: int = 3) -> list[tuple[int, str, float]]` — (venue_id, nombre, score 0-1) ordenadas por score descendente.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_venues.py — agregar
from src import venues


@pytest.mark.parametrize("crudo,esperado", [
    # Los casos REALES de la DB de producción (3-ago-2026).
    ("Staditche", "staditche"),
    ("staditche", "staditche"),
    ("@staditche", "staditche"),
    ("Staditche (Espacio Cultural)", "staditche"),
    ("Staditche (Centro Cultural)", "staditche"),
    ("HAKE AL REY", "hake al rey"),
    ("Hake al Rey", "hake al rey"),
    ("Anexo Independencia", "anexo independencia"),
    ("Foro Anexo Independencia", "anexo independencia"),
    # Prefijo genérico
    ("Centro Cultural Calzada", "calzada"),
    ("El Foro Diez", "diez"),
    # Sufijo genérico
    ("Hake Al Rey - Concert Room", "hake al rey"),
    # Acentos y puntuación
    ("Foro Lázaro", "lazaro"),
    ("C3 Stage & C3 Rooftop", "c3 stage c3 rooftop"),
    # Vacíos
    (None, ""),
    ("", ""),
    ("   ", ""),
])
def test_normalizar(crudo, esperado) -> None:
    assert venues.normalizar(crudo) == esperado


def test_normalizar_quita_un_prefijo_y_un_sufijo_como_maximo() -> None:
    """'foro sala X' pierde solo 'foro'; el segundo genérico se conserva."""
    assert venues.normalizar("Foro Sala Diana") == "sala diana"


def test_normalizar_no_deja_cadena_vacia_si_solo_hay_generico() -> None:
    """Un lugar que es SOLO una palabra genérica conserva su texto: quitarla
    dejaría "" y "" es la clave de 'no hay lugar', que significa otra cosa."""
    assert venues.normalizar("Foro") == "foro"


def test_sugerencias_ordena_por_parecido() -> None:
    candidatos = [(1, "Hake Al Rey"), (2, "Staditche"), (3, "Cuerda")]
    out = venues.sugerencias("hake al rey concert", candidatos)
    assert out[0][0] == 1
    assert out[0][2] > out[-1][2]


def test_sugerencias_respeta_el_tope() -> None:
    candidatos = [(i, f"Foro {i}") for i in range(10)]
    assert len(venues.sugerencias("foro 3", candidatos, tope=2)) == 2


def test_sugerencias_sin_candidatos() -> None:
    assert venues.sugerencias("lo que sea", []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_venues.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.venues'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/venues.py
"""Catálogo de foros canónicos: resuelve el texto libre de `events.lugar`.

`events.lugar` lo extrae un LLM del OCR y del caption, así que el mismo foro
llega escrito de media docena de formas: "Staditche", "@staditche",
"Staditche (Espacio Cultural)", "HAKE AL REY", "REY". Sin una identidad estable,
dos flyers del mismo evento salen como dos slides distintos en la agenda.

El diseño separa dos cosas a propósito:

- `normalizar()` barre lo MECÁNICO (mayúsculas, arrobas, paréntesis, acentos,
  prefijos y sufijos de tipo de local). Es pura y determinista.
- La tabla `venue_alias` captura lo que la normalización NO puede: "REY" es un
  OCR truncado de "Hake Al Rey" y ninguna regla de texto razonable las une sin
  unir también cosas que no debe. Eso se resuelve UNA vez por alias, a mano o
  con el LLM de la siembra, y queda resuelto para siempre.

La resolución en caliente es una búsqueda exacta: sin LLM, sin fuzzy, mismo
resultado siempre y auditable.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

# Palabras de "tipo de local" que no distinguen un foro de otro. Se quita como
# máximo UNA al inicio y UNA al final: "Foro Sala Diana" es "sala diana", no
# "diana" — encadenar borrados fusionaría lugares distintos.
_GENERICOS = (
    "centro cultural", "espacio cultural", "concert room", "concert hall",
    "el foro", "foro", "salon", "sala", "bar", "pub",
)


def normalizar(s: str | None) -> str:
    """Clave de comparación de un lugar. PURA.

    Cadena vacía significa "no hay lugar" — nunca "lugar irreconocible".
    """
    if not s:
        return ""
    # Paréntesis y su contenido: "Staditche (Espacio Cultural)" → "Staditche".
    s = re.sub(r"\([^)]*\)", " ", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = s.replace("@", " ")
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return ""

    completo = s  # antes de podar genéricos, por si el lugar ES un genérico
    for pref in _GENERICOS:  # como máximo UN prefijo
        if s.startswith(pref + " "):
            s = s[len(pref) + 1:].strip()
            break
    for suf in _GENERICOS:  # como máximo UN sufijo
        if s.endswith(" " + suf):
            s = s[: -(len(suf) + 1)].strip()
            break
    # Si el lugar era SOLO una palabra genérica ("Foro"), conservamos el texto:
    # "" está reservado para "no hay lugar" y confundir ambos casos haría que
    # todos los eventos sin lugar se fusionaran entre sí.
    return s or completo


def sugerencias(texto: str, candidatos: list[tuple[int, str]],
                tope: int = 3) -> list[tuple[int, str, float]]:
    """(venue_id, nombre, score) de los foros más parecidos. PURA.

    Para la cola de curación de la GUI. `difflib` en vez de LLM: es instantáneo,
    gratis y determinista, y aquí solo necesitamos ORDENAR candidatos para que
    Ricardo elija — no acertar solo.
    """
    clave = normalizar(texto)
    puntuadas = [
        (vid, nombre, difflib.SequenceMatcher(None, clave, normalizar(nombre)).ratio())
        for vid, nombre in candidatos
    ]
    puntuadas.sort(key=lambda t: (-t[2], t[0]))
    return puntuadas[:tope]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_venues.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add src/venues.py tests/test_venues.py
git commit -m "feat(venues): normalizacion de lugares y sugerencias por similitud"
```

---

### Task 3: Resolver, registrar y curar

**Files:**
- Modify: `src/venues.py`
- Test: `tests/test_venues.py`

**Interfaces:**
- Consumes: `venues.normalizar` (Task 2), esquema (Task 1).
- Produces:
  - `venues.resolver(cx, lugar: str | None) -> int | None` — solo lectura
  - `venues.registrar_desconocido(cx, lugar: str) -> int | None` — devuelve el id del alias huérfano, o None si `normalizar` da vacío
  - `venues.asignar_alias(cx, venue_id: int, texto: str) -> int`
  - `venues.marcar_no_es_lugar(cx, alias_id: int) -> None`
  - `venues.fusionar(cx, dst_id: int, src_id: int) -> None`
  - `venues.huerfanos(cx) -> list[dict]` — alias sin venue y sin marcar como basura

- [ ] **Step 1: Write the failing test**

```python
# tests/test_venues.py — agregar

def _venue(cx, nombre, *alias):
    vid = db.insert(cx, "venues", nombre=nombre)
    for a in alias:
        db.insert(cx, "venue_alias", venue_id=vid, alias_norm=venues.normalizar(a),
                  alias_visto=a, origen="semilla")
    return vid


def test_resolver_alias_conocido(cx) -> None:
    vid = _venue(cx, "Hake Al Rey", "Hake al Rey", "REY")
    assert venues.resolver(cx, "HAKE AL REY") == vid
    assert venues.resolver(cx, "@rey") == vid          # normaliza antes de buscar
    assert venues.resolver(cx, "Rey ") == vid


def test_resolver_desconocido_devuelve_none_y_no_escribe(cx) -> None:
    _venue(cx, "Cuerda", "Cuerda Cultura")
    assert venues.resolver(cx, "Foro Que No Existe") is None
    assert db.rows(cx, "SELECT * FROM venue_alias WHERE venue_id IS NULL") == []


def test_resolver_vacio(cx) -> None:
    assert venues.resolver(cx, None) is None
    assert venues.resolver(cx, "") is None


def test_registrar_desconocido_deja_huerfano(cx) -> None:
    aid = venues.registrar_desconocido(cx, "Foro Nuevo (sala 2)")
    fila = db.get(cx, "venue_alias", aid)
    assert fila["venue_id"] is None
    assert fila["alias_visto"] == "Foro Nuevo (sala 2)"   # texto CRUDO
    assert fila["alias_norm"] == "nuevo"


def test_registrar_desconocido_es_idempotente(cx) -> None:
    a1 = venues.registrar_desconocido(cx, "Foro Nuevo")
    a2 = venues.registrar_desconocido(cx, "FORO NUEVO")
    assert a1 == a2
    assert len(db.rows(cx, "SELECT * FROM venue_alias")) == 1


def test_registrar_desconocido_ignora_vacio(cx) -> None:
    assert venues.registrar_desconocido(cx, "  ") is None
    assert db.rows(cx, "SELECT * FROM venue_alias") == []


def test_asignar_alias_resuelve_el_huerfano(cx) -> None:
    vid = _venue(cx, "Hake Al Rey", "Hake al Rey")
    venues.registrar_desconocido(cx, "REY")
    venues.asignar_alias(cx, vid, "REY")
    assert venues.resolver(cx, "REY") == vid
    assert db.rows(cx, "SELECT * FROM venue_alias WHERE venue_id IS NULL") == []


def test_asignar_alias_marca_origen_manual(cx) -> None:
    vid = _venue(cx, "Cuerda")
    aid = venues.asignar_alias(cx, vid, "cuerdacultura")
    assert db.get(cx, "venue_alias", aid)["origen"] == "manual"


def test_marcar_no_es_lugar_lo_saca_de_la_cola(cx) -> None:
    aid = venues.registrar_desconocido(cx, "siamesasperdidas")
    venues.marcar_no_es_lugar(cx, aid)
    assert venues.huerfanos(cx) == []
    # Sigue en la tabla, para que no vuelva a entrar a la cola.
    assert db.get(cx, "venue_alias", aid)["origen"] == "no_es_lugar"


def test_registrar_no_revive_lo_marcado_como_basura(cx) -> None:
    aid = venues.registrar_desconocido(cx, "barragan_kun")
    venues.marcar_no_es_lugar(cx, aid)
    venues.registrar_desconocido(cx, "barragan_kun")
    assert venues.huerfanos(cx) == []


def test_fusionar_mueve_alias_y_eventos(cx) -> None:
    dst = _venue(cx, "Hake Al Rey", "Hake al Rey")
    src = _venue(cx, "Hakealrey", "Hakealrey")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    eid = db.insert(cx, "events", band_id=bid, tipo="flyer", venue_id=src)
    venues.fusionar(cx, dst, src)
    assert db.get(cx, "venues", src) is None
    assert db.get(cx, "events", eid)["venue_id"] == dst
    assert venues.resolver(cx, "Hakealrey") == dst


def test_fusionar_consigo_mismo_no_hace_nada(cx) -> None:
    vid = _venue(cx, "Cuerda", "Cuerda")
    venues.fusionar(cx, vid, vid)
    assert db.get(cx, "venues", vid) is not None
    assert venues.resolver(cx, "Cuerda") == vid


def test_huerfanos_lista_solo_los_pendientes(cx) -> None:
    vid = _venue(cx, "Cuerda", "Cuerda")
    venues.registrar_desconocido(cx, "Foro X")
    nombres = [h["alias_visto"] for h in venues.huerfanos(cx)]
    assert nombres == ["Foro X"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_venues.py -v`
Expected: FAIL — `AttributeError: module 'src.venues' has no attribute 'resolver'`.

- [ ] **Step 3: Write minimal implementation**

Agregar a `src/venues.py` (con `from src import db` en los imports):

```python
def resolver(cx, lugar: str | None) -> int | None:
    """venue_id del lugar, o None si no hay alias registrado. SOLO LECTURA.

    Separada de `registrar_desconocido` a propósito: una función que consulta
    no debe escribir, y quien llama decide si quiere dejar rastro del fallo.
    """
    clave = normalizar(lugar)
    if not clave:
        return None
    filas = db.rows(cx, "SELECT venue_id FROM venue_alias WHERE alias_norm = ?", (clave,))
    return filas[0]["venue_id"] if filas else None


def registrar_desconocido(cx, lugar: str) -> int | None:
    """Deja el alias en la cola de curación. Devuelve su id (None si vacío).

    Idempotente: si el alias ya existe —resuelto, huérfano o marcado basura—
    devuelve el id existente sin tocarlo. Eso evita que un lugar descartado
    como 'no es un lugar' reaparezca en la cola cada vez que pasa un flyer.
    """
    clave = normalizar(lugar)
    if not clave:
        return None
    filas = db.rows(cx, "SELECT id FROM venue_alias WHERE alias_norm = ?", (clave,))
    if filas:
        return int(filas[0]["id"])
    return db.insert(cx, "venue_alias", venue_id=None, alias_norm=clave,
                     alias_visto=lugar, origen="llm")


def asignar_alias(cx, venue_id: int, texto: str) -> int:
    """Liga un texto a un foro. Curación manual: gana sobre lo que hubiera."""
    clave = normalizar(texto)
    filas = db.rows(cx, "SELECT id FROM venue_alias WHERE alias_norm = ?", (clave,))
    if filas:
        aid = int(filas[0]["id"])
        db.update(cx, "venue_alias", aid, venue_id=venue_id, origen="manual")
        return aid
    return db.insert(cx, "venue_alias", venue_id=venue_id, alias_norm=clave,
                     alias_visto=texto, origen="manual")


def marcar_no_es_lugar(cx, alias_id: int) -> None:
    """Basura (nombre de banda, dirección): sale de la cola pero NO se borra,
    para que el mismo texto no vuelva a entrar en la próxima corrida."""
    db.update(cx, "venue_alias", alias_id, venue_id=None, origen="no_es_lugar")


def fusionar(cx, dst_id: int, src_id: int) -> None:
    """Absorbe src en dst: mueve alias y reapunta events antes de borrar.

    Nunca deja `events.venue_id` colgando (no hay FK que lo cuide).
    """
    if dst_id == src_id:
        return
    cx.execute("UPDATE venue_alias SET venue_id = ? WHERE venue_id = ?", (dst_id, src_id))
    cx.execute("UPDATE events SET venue_id = ? WHERE venue_id = ?", (dst_id, src_id))
    cx.execute("DELETE FROM venues WHERE id = ?", (src_id,))
    cx.commit()


def huerfanos(cx) -> list[dict]:
    """Alias pendientes de curar: sin foro y sin marcar como basura."""
    return db.rows(cx, """
        SELECT * FROM venue_alias
         WHERE venue_id IS NULL AND origen != 'no_es_lugar'
         ORDER BY created_at, id
    """)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_venues.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/venues.py tests/test_venues.py
git commit -m "feat(venues): resolver, cola de huerfanos y operaciones de curacion"
```

---

### Task 4: Siembra del catálogo

**Files:**
- Create: `src/venues_seed.py`
- Test: `tests/test_venues_seed.py`

**Interfaces:**
- Consumes: todo `src/venues.py`.
- Produces:
  - `venues_seed.sembrar_desde_bands(cx) -> int` — crea venues desde `bands` tipo foro/evento; devuelve cuántos creó
  - `venues_seed.lugares_distintos(cx) -> list[str]` — textos crudos de `events.lugar`
  - `venues_seed.agrupar_mecanico(lugares: list[str]) -> dict[str, list[str]]` — PURA, clave normalizada → textos crudos
  - `venues_seed.sembrar(cx, *, _llm=None) -> dict` — orquesta; `_llm` inyectable devuelve `list[dict]` con `{"canonico": str, "alias": [str, ...]}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_venues_seed.py
from __future__ import annotations

from pathlib import Path

import pytest

from src import db, venues, venues_seed


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _evento(cx, band_id, lugar):
    return db.insert(cx, "events", band_id=band_id, tipo="flyer",
                     fecha_evento="2026-08-23", lugar=lugar)


def test_siembra_desde_bands_usa_los_foros_que_ya_sigue(cx) -> None:
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1, ciudad="Guadalajara")
    db.insert(cx, "bands", nombre="Pool Sessions", ig_handle="poolsessions_",
              tipo="evento", activa=1)
    db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial",
              tipo="banda", activa=1)
    assert venues_seed.sembrar_desde_bands(cx) == 2      # la banda NO entra
    nombres = {v["nombre"] for v in db.rows(cx, "SELECT nombre FROM venues")}
    assert nombres == {"STADITCHE", "Pool Sessions"}
    # El nombre y el handle quedan como alias, así ambos resuelven.
    assert venues.resolver(cx, "@staditche") is not None
    assert venues.resolver(cx, "STADITCHE") is not None


def test_siembra_desde_bands_es_idempotente(cx) -> None:
    db.insert(cx, "bands", nombre="Cuerda", ig_handle="cuerdacultura",
              tipo="foro", activa=1)
    venues_seed.sembrar_desde_bands(cx)
    assert venues_seed.sembrar_desde_bands(cx) == 0
    assert len(db.rows(cx, "SELECT * FROM venues")) == 1


def test_agrupar_mecanico_colapsa_las_escrituras_obvias() -> None:
    grupos = venues_seed.agrupar_mecanico([
        "Staditche", "staditche", "@staditche", "Staditche (Espacio Cultural)",
        "Cuerda Cultura",
    ])
    assert set(grupos) == {"staditche", "cuerda cultura"}
    assert len(grupos["staditche"]) == 4


def test_sembrar_resuelve_lo_mecanico_sin_llm(cx) -> None:
    """Lo que la normalización ya colapsa no debe llegar al LLM."""
    db.insert(cx, "bands", nombre="STADITCHE", ig_handle="staditche",
              tipo="foro", activa=1)
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    for l in ("@staditche", "Staditche (Espacio Cultural)", "STADITCHE"):
        _evento(cx, bid, l)
    vistos = {}

    def _llm(pendientes):
        vistos["pendientes"] = list(pendientes)
        return []

    venues_seed.sembrar(cx, _llm=_llm)
    assert vistos["pendientes"] == []     # nada ambiguo que consultar


def test_sembrar_aplica_lo_que_propone_el_llm(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")
    _evento(cx, bid, "Hake al Rey")

    def _llm(pendientes):
        return [{"canonico": "Hake Al Rey", "alias": ["REY", "Hake al Rey"]}]

    res = venues_seed.sembrar(cx, _llm=_llm)
    assert res["venues"] >= 1
    assert venues.resolver(cx, "REY") == venues.resolver(cx, "Hake al Rey")


def test_sembrar_no_pisa_lo_curado(cx) -> None:
    """Un alias asignado a mano sobrevive aunque el LLM proponga otra cosa."""
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "REY")
    mio = db.insert(cx, "venues", nombre="Mi Foro")
    venues.asignar_alias(cx, mio, "REY")

    def _llm(pendientes):
        return [{"canonico": "Otro Foro", "alias": ["REY"]}]

    venues_seed.sembrar(cx, _llm=_llm)
    assert venues.resolver(cx, "REY") == mio


def test_sembrar_deja_huerfano_lo_que_el_llm_no_agrupa(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "GRAL.MANUEL pm COVER M.DIEGUEZ #71")

    res = venues_seed.sembrar(cx, _llm=lambda pendientes: [])
    assert res["huerfanos"] == 1
    assert len(venues.huerfanos(cx)) == 1


def test_sembrar_ignora_eventos_sin_lugar(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, None)
    _evento(cx, bid, "")
    res = venues_seed.sembrar(cx, _llm=lambda pendientes: [])
    assert res["huerfanos"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_venues_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.venues_seed'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/venues_seed.py
"""Siembra única del catálogo de foros.

Orden deliberado, de lo barato y seguro a lo caro e incierto:

1. Los foros y eventos que Ricardo YA sigue (`bands` tipo foro/evento) entran
   como venues con su nombre y su handle de alias. Es el catálogo gratis.
2. Los `events.lugar` distintos se agrupan con `venues.normalizar`, que colapsa
   mayúsculas, arrobas, paréntesis y prefijos sin ayuda de nadie.
3. Solo lo que sigue ambiguo va al LLM, en UNA llamada.
4. Lo que el LLM no agrupa queda huérfano para curación en la GUI.

Idempotente y respetuoso de lo manual: un alias con origen='manual' no se toca.
"""
from __future__ import annotations

import json
from typing import Any, Callable

import config
from src import db, venues

_TIPOS_VENUE = ("foro", "evento")

_PROMPT = """Eres un asistente que ordena nombres de foros y venues de la escena
musical de Guadalajara. Te doy una lista de textos crudos extraídos por OCR de
carteles de conciertos. Agrupa los que se refieran al MISMO lugar y dale a cada
grupo un nombre canónico limpio.

Reglas:
- Salas distintas del mismo edificio son lugares DISTINTOS (C3 Stage y C3
  Rooftop van separados).
- Si un texto no es un lugar (nombre de banda, dirección suelta, basura de OCR),
  NO lo incluyas en ningún grupo.
- Un texto que no puedas asignar con confianza, déjalo fuera.

Devuelve SOLO un JSON: [{"canonico": "Nombre Limpio", "alias": ["texto1", ...]}]

Textos:
"""


def sembrar_desde_bands(cx) -> int:
    """Crea venues desde las cuentas de tipo foro/evento. Devuelve cuántos creó."""
    creados = 0
    marcas = ",".join("?" * len(_TIPOS_VENUE))
    for b in db.rows(cx, f"""
        SELECT nombre, ig_handle, ciudad FROM bands
         WHERE tipo IN ({marcas}) AND activa = 1 ORDER BY id
    """, _TIPOS_VENUE):
        if venues.resolver(cx, b["nombre"]) is not None:
            continue
        vid = db.insert(cx, "venues", nombre=b["nombre"], ciudad=b["ciudad"],
                        ig_handle=b["ig_handle"])
        creados += 1
        for texto in (b["nombre"], b["ig_handle"]):
            if texto and venues.normalizar(texto):
                venues.asignar_alias(cx, vid, texto)
    return creados


def lugares_distintos(cx) -> list[str]:
    """Textos crudos distintos de `events.lugar`, en orden estable."""
    return [r["lugar"] for r in db.rows(cx, """
        SELECT DISTINCT lugar FROM events
         WHERE lugar IS NOT NULL AND trim(lugar) != ''
         ORDER BY lugar
    """)]


def agrupar_mecanico(lugares: list[str]) -> dict[str, list[str]]:
    """Clave normalizada → textos crudos que caen en ella. PURA."""
    grupos: dict[str, list[str]] = {}
    for l in lugares:
        clave = venues.normalizar(l)
        if clave:
            grupos.setdefault(clave, []).append(l)
    return grupos


def _llm_agrupar(pendientes: list[str]) -> list[dict[str, Any]]:
    """UNA llamada a DeepSeek con todos los textos ambiguos."""
    if not pendientes:
        return []
    from openai import OpenAI
    from src.parse_events import extraer_json
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": _PROMPT + "\n".join(pendientes)}],
        temperature=0,
    )
    data = extraer_json(resp.choices[0].message.content or "")
    if isinstance(data, dict):
        data = data.get("grupos") or []
    return data if isinstance(data, list) else []


def sembrar(cx, *, _llm: Callable[[list[str]], list[dict]] | None = None) -> dict:
    """Siembra completa. Devuelve {venues, alias, huerfanos, pendientes_llm}."""
    llm = _llm or _llm_agrupar
    db.init_db(cx)
    creados = sembrar_desde_bands(cx)

    grupos = agrupar_mecanico(lugares_distintos(cx))
    # Lo que ya resuelve contra el catálogo no se toca; el resto es "pendiente".
    pendientes = [textos[0] for clave, textos in grupos.items()
                  if venues.resolver(cx, textos[0]) is None]

    alias_nuevos = 0
    for grupo in llm(pendientes):
        canonico = (grupo.get("canonico") or "").strip()
        alias = [a for a in (grupo.get("alias") or []) if a and a.strip()]
        if not canonico or not alias:
            continue
        vid = venues.resolver(cx, canonico)
        if vid is None:
            vid = db.insert(cx, "venues", nombre=canonico)
            creados += 1
        for texto in [canonico, *alias]:
            clave = venues.normalizar(texto)
            if not clave:
                continue
            filas = db.rows(cx, "SELECT id, origen FROM venue_alias WHERE alias_norm = ?",
                            (clave,))
            if filas and filas[0]["origen"] == "manual":
                continue          # el batch NUNCA pisa lo curado a mano
            if filas:
                db.update(cx, "venue_alias", filas[0]["id"], venue_id=vid, origen="llm")
            else:
                db.insert(cx, "venue_alias", venue_id=vid, alias_norm=clave,
                          alias_visto=texto, origen="llm")
            alias_nuevos += 1

    # Lo que sigue sin resolver entra a la cola de curación.
    for clave, textos in grupos.items():
        if venues.resolver(cx, textos[0]) is None:
            venues.registrar_desconocido(cx, textos[0])
    cx.commit()
    return {"venues": creados, "alias": alias_nuevos,
            "huerfanos": len(venues.huerfanos(cx)),
            "pendientes_llm": len(pendientes)}
```

`config.DEEPSEEK_MODEL` existe (`config.py:28`, default `deepseek-chat`), igual que `DEEPSEEK_API_KEY` y `DEEPSEEK_BASE_URL`. `extraer_json` vive en `src/parse_events.py` y ya lo reusa `src/clasifica_generos.py` — es el mismo patrón, no inventes uno nuevo.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_venues_seed.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/venues_seed.py tests/test_venues_seed.py
git commit -m "feat(venues): siembra del catalogo desde bands, normalizacion y LLM"
```

---

### Task 5: Backfill y resolución al escribir

**Files:**
- Modify: `src/venues_seed.py` (agregar `backfill_eventos` y CLI)
- Modify: `src/parse_events.py:105-111`
- Modify: `src/detect_releases_ig.py:321`
- Test: `tests/test_venues_seed.py`

**Interfaces:**
- Consumes: `venues.resolver`, `venues.registrar_desconocido`.
- Produces: `venues_seed.backfill_eventos(cx) -> int` — cuántos eventos quedaron con `venue_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_venues_seed.py — agregar

def test_backfill_llena_venue_id(cx) -> None:
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, vid, "Hake al Rey")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    con = _evento(cx, bid, "HAKE AL REY")
    sin = _evento(cx, bid, "Foro Desconocido")
    assert venues_seed.backfill_eventos(cx) == 1
    assert db.get(cx, "events", con)["venue_id"] == vid
    assert db.get(cx, "events", sin)["venue_id"] is None


def test_backfill_es_idempotente(cx) -> None:
    vid = db.insert(cx, "venues", nombre="Cuerda")
    venues.asignar_alias(cx, vid, "Cuerda Cultura")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "cuerda cultura")
    venues_seed.backfill_eventos(cx)
    assert venues_seed.backfill_eventos(cx) == 1


def test_backfill_deja_huerfano_lo_no_resuelto(cx) -> None:
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    _evento(cx, bid, "Foro Nunca Visto")
    venues_seed.backfill_eventos(cx)
    assert [h["alias_visto"] for h in venues.huerfanos(cx)] == ["Foro Nunca Visto"]
```

Y el test del hook de `parse_events`, **en `tests/test_venues_seed.py`** para reusar el fixture `cx` que ya está ahí:

```python
def test_parse_event_resuelve_venue_id(cx, monkeypatch) -> None:
    """Al guardar el lugar, el evento queda ligado al foro si ya se conoce."""
    from src import parse_events
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, vid, "Hake al Rey")
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    eid = db.insert(cx, "events", band_id=bid, tipo="flyer", source_post_id="X")
    # `parse_event` arma el prompt de OCR + caption; sin flyer en disco y sin
    # foto en `photos` no habría texto, así que sembramos el caption.
    db.insert(cx, "photos", band_id=bid, path="p.jpg", source_post_id="X",
              caption_original="tocada el sabado")
    monkeypatch.setattr(parse_events, "_llm_extraer",
                        lambda prompt: {"tipo": "fecha", "fecha": "2026-08-23",
                                        "lugar": "HAKE AL REY", "ciudad": None})
    parse_events.parse_event(cx, db.get(cx, "events", eid))
    assert db.get(cx, "events", eid)["venue_id"] == vid


def test_parse_event_deja_huerfano_lo_no_resuelto(cx, monkeypatch) -> None:
    from src import parse_events
    bid = db.insert(cx, "bands", nombre="B", ig_handle="b")
    eid = db.insert(cx, "events", band_id=bid, tipo="flyer", source_post_id="Y")
    db.insert(cx, "photos", band_id=bid, path="p.jpg", source_post_id="Y",
              caption_original="tocada el sabado")
    monkeypatch.setattr(parse_events, "_llm_extraer",
                        lambda prompt: {"tipo": "fecha", "fecha": "2026-08-23",
                                        "lugar": "Foro Jamás Visto", "ciudad": None})
    parse_events.parse_event(cx, db.get(cx, "events", eid))
    assert db.get(cx, "events", eid)["venue_id"] is None
    assert [h["alias_visto"] for h in venues.huerfanos(cx)] == ["Foro Jamás Visto"]
```

`parse_event` solo llama al LLM si logra armar texto (OCR del flyer o caption de `photos`); por eso el test siembra la fila de `photos`. Verificado contra `src/parse_events.py:74-105`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_venues_seed.py tests/test_fase5.py -v`
Expected: FAIL — `AttributeError: ... has no attribute 'backfill_eventos'` y `venue_id` en None.

- [ ] **Step 3: Write minimal implementation**

En `src/venues_seed.py`:

```python
def backfill_eventos(cx) -> int:
    """Resuelve `venue_id` de todos los eventos con lugar. Devuelve cuántos.

    Lo que no resuelve entra a la cola de curación: así el catálogo crece con
    lo que de verdad aparece en los carteles, no con lo que alguien imagine.
    """
    resueltos = 0
    for e in db.rows(cx, """
        SELECT id, lugar FROM events
         WHERE lugar IS NOT NULL AND trim(lugar) != ''
    """):
        vid = venues.resolver(cx, e["lugar"])
        if vid is None:
            venues.registrar_desconocido(cx, e["lugar"])
            continue
        db.update(cx, "events", e["id"], venue_id=vid)
        resueltos += 1
    cx.commit()
    return resueltos


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Siembra del catálogo de foros")
    parser.add_argument("--solo-backfill", action="store_true",
                        help="no siembra: solo resuelve venue_id de los eventos")
    args = parser.parse_args()
    cx = db.connect()
    try:
        db.init_db(cx)
        if not args.solo_backfill:
            res = sembrar(cx)
            print(f"Siembra: {res['venues']} foro(s), {res['alias']} alias, "
                  f"{res['pendientes_llm']} al LLM")
        n = backfill_eventos(cx)
        print(f"Backfill: {n} evento(s) con foro resuelto · "
              f"{len(venues.huerfanos(cx))} alias por curar en /venues")
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido.")
    finally:
        cx.close()
```

En `src/parse_events.py`, después de `db.update(cx, "events", evento["id"], **cambios)` (línea ~111):

```python
    if cambios.get("lugar"):
        from src import venues
        vid = venues.resolver(cx, cambios["lugar"])
        if vid is not None:
            db.update(cx, "events", evento["id"], venue_id=vid)
        else:
            venues.registrar_desconocido(cx, cambios["lugar"])
```

En `src/detect_releases_ig.py`, dentro de `_registrar_show`, el `db.insert` de la línea ~320 hoy descarta el id que devuelve. Captúralo y resuelve:

```python
    lugar = (data.get("lugar") or None)
    eid = db.insert(cx, "events", band_id=post["band_id"], tipo="fecha",
                    titulo=(data.get("titulo") or None), fecha_evento=fecha,
                    lugar=lugar, ciudad=(data.get("ciudad") or None),
                    flyer_path=post.get("path"), cover_url=post.get("path"),
                    source_post_id=llave, status="nuevo", parseado_por_llm=1)
    if lugar:
        from src import venues
        vid = venues.resolver(cx, lugar)
        if vid is not None:
            db.update(cx, "events", eid, venue_id=vid)
        else:
            venues.registrar_desconocido(cx, lugar)
```

El resto de la función (el `print` y el `return True`) no cambia.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_venues_seed.py tests/test_fase5.py tests/test_detect_releases_ig.py -v`
Expected: PASS.

Luego la suite completa: `.venv/bin/python -m pytest`
Expected: solo los 2 fallos preexistentes.

- [ ] **Step 5: Commit**

```bash
git add src/venues_seed.py src/parse_events.py src/detect_releases_ig.py tests/
git commit -m "feat(venues): backfill de eventos y resolucion al parsear"
```

---

### Task 6: La agenda agrupa por venue_id

**Files:**
- Modify: `src/generate_agenda.py:40-60` (borrar `_norm_venue` y `_PREFIJOS_VENUE`), `:63-93` (`agrupar_por_evento`), `:95-103` (constantes duplicadas)
- Test: `tests/test_dedup_eventos.py`, `tests/test_agenda.py`

**Interfaces:**
- Consumes: `events.venue_id` (Task 5).
- Produces: `agrupar_por_evento` agrupa por `(fecha, venue_id)`; `_norm_venue` deja de existir.

**Limpieza incluida:** `generate_agenda.py` declara `_PERIODOS`, `_MES_ABREV` y `_MAX_EN_TARJETA` **dos veces** (líneas 95-98 y 100-103), con los mismos valores. Es duplicación muerta en el bloque que vas a tocar: borra la segunda copia.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedup_eventos.py — agregar
from src.generate_agenda import agrupar_por_evento


def _ev(eid, fecha, venue_id, banda, handle):
    return {"id": eid, "fecha_evento": fecha, "venue_id": venue_id,
            "lugar": "lo que sea", "banda_nombre": banda, "banda_handle": handle}


def test_agrupa_por_venue_id_aunque_el_texto_difiera() -> None:
    """El caso real del 23-ago: 'REY' y 'Hake al Rey' resuelven al mismo foro."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "SilentNoir", "silentnoirofficial"),
        _ev(2, "2026-08-23", 7, "Hake Al Rey", "hakealrey"),
    ])
    assert len(grupos) == 1
    assert set(grupos[0]["handles"]) == {"silentnoirofficial", "hakealrey"}
    assert grupos[0]["ids"] == [1, 2]


def test_no_agrupa_venues_distintos() -> None:
    """Salas distintas son foros distintos: C3 Stage y C3 Rooftop no se funden."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a"),
        _ev(2, "2026-08-23", 8, "B", "b"),
    ])
    assert len(grupos) == 2


def test_no_agrupa_sin_venue_id() -> None:
    """Sin foro resuelto no se fusiona: adivinar es peor que duplicar."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", None, "A", "a"),
        _ev(2, "2026-08-23", None, "B", "b"),
    ])
    assert len(grupos) == 2


def test_no_agrupa_fechas_distintas() -> None:
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a"),
        _ev(2, "2026-08-24", 7, "B", "b"),
    ])
    assert len(grupos) == 2


def test_no_repite_la_misma_banda() -> None:
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a"),
        _ev(2, "2026-08-23", 7, "A", "a"),
    ])
    assert grupos[0]["bandas"] == ["A"]
    assert grupos[0]["ids"] == [1, 2]
```

Revisa además los tests que ya existan en `tests/test_dedup_eventos.py` y `tests/test_agenda.py` que construyan eventos con `lugar`: ahora deben pasar `venue_id`. **Adáptalos, no los borres**, y si alguno probaba específicamente la normalización de texto de `_norm_venue`, muévelo a `tests/test_venues.py` como test de `venues.normalizar`.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dedup_eventos.py -v`
Expected: FAIL — agrupa por texto, así que `test_agrupa_por_venue_id_aunque_el_texto_difiera` da 1 grupo por accidente pero `test_no_agrupa_venues_distintos` falla (ambos tienen `lugar` igual).

- [ ] **Step 3: Write minimal implementation**

Borra de `src/generate_agenda.py`: `_PREFIJOS_VENUE`, la función `_norm_venue` completa, y la **segunda** copia de `_PERIODOS`/`_MES_ABREV`/`_MAX_EN_TARJETA`. Quita el `import unicodedata` si ya no se usa en el archivo (compruébalo con grep).

Reemplaza el cuerpo de `agrupar_por_evento`:

```python
def agrupar_por_evento(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusiona eventos con MISMA fecha + MISMO foro en uno solo con TODAS las bandas.

    La identidad del foro es `events.venue_id`, del catálogo de `src/venues.py`,
    no el texto de `lugar` — el mismo foro llega escrito de media docena de
    formas ("REY" y "Hake al Rey" son el mismo lugar) y comparar texto dejaba
    pasar duplicados a la agenda.

    Sin `venue_id` no se fusiona: adivinar que dos flyers son el mismo evento
    desaparecería uno de la agenda, y eso es peor que mostrarlo dos veces.
    """
    grupos: dict[tuple, dict] = {}
    orden: list[tuple] = []
    for e in eventos:
        fecha = (e.get("fecha_evento") or "")[:10]
        vid = e.get("venue_id")
        clave = (fecha, vid) if vid else (fecha, f"__solo{e['id']}")
        g = grupos.get(clave)
        if g is None:
            g = {**e, "bandas": [], "handles": [], "ids": []}
            grupos[clave] = g
            orden.append(clave)
        g["ids"].append(e["id"])
        if e["banda_nombre"] not in g["bandas"]:
            g["bandas"].append(e["banda_nombre"])
            if e.get("banda_handle"):
                g["handles"].append(e["banda_handle"])
        if not g.get("lugar") and e.get("lugar"):
            g["lugar"] = e["lugar"]
    out = []
    for clave in orden:
        g = grupos[clave]
        g["banda_nombre"] = " · ".join(g["bandas"])
        out.append(g)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dedup_eventos.py tests/test_agenda.py -v`
Expected: PASS.

Suite completa: `.venv/bin/python -m pytest` → solo los 2 fallos preexistentes.

- [ ] **Step 5: Commit**

```bash
git add src/generate_agenda.py tests/
git commit -m "feat(venues): la agenda agrupa por venue_id, no por texto del lugar"
```

---

### Task 7: GUI de curación del catálogo

**Files:**
- Modify: `web/app.py`
- Create: `web/templates/venues.html`
- Test: `tests/test_venues_web.py`

**Interfaces:**
- Consumes: todo `src/venues.py`.
- Produces: `GET /venues`, `POST /venues/alias/{alias_id}/asignar`, `POST /venues/alias/{alias_id}/no-es-lugar`, `POST /venues/nuevo`, `POST /venues/{venue_id}/fusionar`.

**Hechos verificados por el controlador:** `web/app.py:16` importa `FastAPI, Form, HTTPException, Request` — agrega `Response` si hace falta. La plantilla base es `base.html`; mira `web/templates/bandas.html` para el bloque y el estilo. **Las rutas nuevas exigen reiniciar uvicorn** (corre en 127.0.0.1:8742 sin `--reload`); no lo arranques tú, los tests van con `TestClient`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_venues_web.py
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db, venues


@pytest.fixture()
def cliente(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    import importlib

    import config
    importlib.reload(config)
    from web import app as app_mod
    importlib.reload(app_mod)
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield TestClient(app_mod.app), conn
    conn.close()


def test_vista_lista_foros_y_huerfanos(cliente) -> None:
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    venues.asignar_alias(cx, vid, "Hake al Rey")
    venues.registrar_desconocido(cx, "REY")
    r = cli.get("/venues")
    assert r.status_code == 200
    assert "Hake Al Rey" in r.text
    assert "REY" in r.text


def test_asignar_alias_lo_saca_de_la_cola(cliente) -> None:
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Hake Al Rey")
    aid = venues.registrar_desconocido(cx, "REY")
    r = cli.post(f"/venues/alias/{aid}/asignar", data={"venue_id": str(vid)})
    assert r.status_code in (200, 204, 303)
    assert venues.resolver(cx, "REY") == vid
    assert venues.huerfanos(cx) == []


def test_no_es_lugar_saca_la_basura(cliente) -> None:
    cli, cx = cliente
    aid = venues.registrar_desconocido(cx, "siamesasperdidas")
    r = cli.post(f"/venues/alias/{aid}/no-es-lugar")
    assert r.status_code in (200, 204, 303)
    assert venues.huerfanos(cx) == []


def test_crear_foro_desde_un_huerfano(cliente) -> None:
    cli, cx = cliente
    aid = venues.registrar_desconocido(cx, "Foro Nuevo")
    r = cli.post("/venues/nuevo", data={"nombre": "Foro Nuevo", "alias_id": str(aid)})
    assert r.status_code in (200, 204, 303)
    assert venues.resolver(cx, "Foro Nuevo") is not None
    assert venues.huerfanos(cx) == []


def test_fusionar_dos_foros(cliente) -> None:
    cli, cx = cliente
    dst = db.insert(cx, "venues", nombre="Hake Al Rey")
    src = db.insert(cx, "venues", nombre="Hakealrey")
    venues.asignar_alias(cx, src, "Hakealrey")
    r = cli.post(f"/venues/{dst}/fusionar", data={"otro_id": str(src)})
    assert r.status_code in (200, 204, 303)
    assert db.get(cx, "venues", src) is None
    assert venues.resolver(cx, "Hakealrey") == dst


def test_fusionar_consigo_mismo_falla(cliente) -> None:
    cli, cx = cliente
    vid = db.insert(cx, "venues", nombre="Cuerda")
    r = cli.post(f"/venues/{vid}/fusionar", data={"otro_id": str(vid)})
    assert r.status_code == 400
    assert db.get(cx, "venues", vid) is not None


def test_asignar_a_foro_inexistente_falla(cliente) -> None:
    cli, cx = cliente
    aid = venues.registrar_desconocido(cx, "Foro X")
    r = cli.post(f"/venues/alias/{aid}/asignar", data={"venue_id": "9999"})
    assert r.status_code == 404
    assert len(venues.huerfanos(cx)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_venues_web.py -v`
Expected: FAIL — 404 en `/venues`.

- [ ] **Step 3: Write minimal implementation**

`web/templates/venues.html` (ajusta el nombre del bloque al que use `base.html`):

```html
{% extends "base.html" %}
{% block contenido %}
<h1>Foros</h1>

{% if huerfanos %}
<section>
  <h2>Por curar ({{ huerfanos|length }})</h2>
  {% for h in huerfanos %}
  <div class="huerfano">
    <strong>{{ h.alias_visto }}</strong>
    <form hx-post="/venues/alias/{{ h.id }}/asignar" hx-swap="none">
      <select name="venue_id">
        {% for v in foros %}
          <option value="{{ v.id }}"
            {% if h.sugerencia and h.sugerencia == v.id %}selected{% endif %}>
            {{ v.nombre }}{% if h.sugerencia == v.id %} (sugerido){% endif %}
          </option>
        {% endfor %}
      </select>
      <button type="submit">Asignar</button>
    </form>
    <form hx-post="/venues/nuevo" hx-swap="none">
      <input type="hidden" name="alias_id" value="{{ h.id }}">
      <input name="nombre" value="{{ h.alias_visto }}">
      <button type="submit">Crear foro</button>
    </form>
    <button hx-post="/venues/alias/{{ h.id }}/no-es-lugar" hx-swap="none">No es un lugar</button>
  </div>
  {% endfor %}
</section>
{% endif %}

<section>
  <h2>Catálogo ({{ foros|length }})</h2>
  {% for v in foros %}
  <div class="foro">
    <strong>{{ v.nombre }}</strong>
    {% if v.ig_handle %}<span>@{{ v.ig_handle }}</span>{% endif %}
    <span>{{ v.alias|join(" · ") }}</span>
    {% if foros|length > 1 %}
    <form hx-post="/venues/{{ v.id }}/fusionar" hx-swap="none">
      <select name="otro_id">
        {% for o in foros if o.id != v.id %}
          <option value="{{ o.id }}">{{ o.nombre }}</option>
        {% endfor %}
      </select>
      <button type="submit">Absorber</button>
    </form>
    {% endif %}
  </div>
  {% endfor %}
</section>
{% endblock %}
```

En `web/app.py`:

```python
@app.get("/venues", response_class=HTMLResponse)
def venues_vista(request: Request):
    from src import venues as venues_mod
    cx = db.connect()
    try:
        foros = db.rows(cx, "SELECT * FROM venues ORDER BY nombre")
        for v in foros:
            v["alias"] = [a["alias_visto"] for a in db.rows(
                cx, "SELECT alias_visto FROM venue_alias WHERE venue_id = ? ORDER BY id",
                (v["id"],))]
        candidatos = [(v["id"], v["nombre"]) for v in foros]
        huerfanos = venues_mod.huerfanos(cx)
        for h in huerfanos:
            sug = venues_mod.sugerencias(h["alias_visto"], candidatos, tope=1)
            h["sugerencia"] = sug[0][0] if sug else None
        return templates.TemplateResponse(
            "venues.html", {"request": request, "foros": foros, "huerfanos": huerfanos})
    finally:
        cx.close()


@app.post("/venues/alias/{alias_id}/asignar")
def venue_alias_asignar(alias_id: int, venue_id: int = Form(...)):
    from src import venues as venues_mod
    cx = db.connect()
    try:
        alias = db.get(cx, "venue_alias", alias_id)
        if not alias:
            raise HTTPException(status_code=404, detail="alias no encontrado")
        if not db.get(cx, "venues", venue_id):
            raise HTTPException(status_code=404, detail="foro no encontrado")
        venues_mod.asignar_alias(cx, venue_id, alias["alias_visto"])
        return Response(status_code=204)
    finally:
        cx.close()


@app.post("/venues/alias/{alias_id}/no-es-lugar")
def venue_alias_basura(alias_id: int):
    from src import venues as venues_mod
    cx = db.connect()
    try:
        if not db.get(cx, "venue_alias", alias_id):
            raise HTTPException(status_code=404, detail="alias no encontrado")
        venues_mod.marcar_no_es_lugar(cx, alias_id)
        return Response(status_code=204)
    finally:
        cx.close()


@app.post("/venues/nuevo")
def venue_nuevo(nombre: str = Form(...), alias_id: int | None = Form(None)):
    from src import venues as venues_mod
    cx = db.connect()
    try:
        vid = db.insert(cx, "venues", nombre=nombre.strip())
        venues_mod.asignar_alias(cx, vid, nombre.strip())
        if alias_id:
            alias = db.get(cx, "venue_alias", alias_id)
            if alias:
                venues_mod.asignar_alias(cx, vid, alias["alias_visto"])
        return Response(status_code=204)
    finally:
        cx.close()


@app.post("/venues/{venue_id}/fusionar")
def venue_fusionar(venue_id: int, otro_id: int = Form(...)):
    """Absorbe `otro_id` en `venue_id`: mismo foro registrado dos veces."""
    from src import venues as venues_mod
    cx = db.connect()
    try:
        if venue_id == otro_id:
            raise HTTPException(status_code=400,
                                detail="un foro no se fusiona consigo mismo")
        if not db.get(cx, "venues", venue_id) or not db.get(cx, "venues", otro_id):
            raise HTTPException(status_code=404, detail="foro no encontrado")
        venues_mod.fusionar(cx, venue_id, otro_id)
        return Response(status_code=204)
    finally:
        cx.close()
```

Agrega un link a `/venues` desde la navegación que ya exista en `base.html`, siguiendo el patrón de los demás.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_venues_web.py -v`
Expected: PASS (7 tests).

Suite completa: `.venv/bin/python -m pytest` → solo los 2 fallos preexistentes.

- [ ] **Step 5: Commit**

```bash
git add web/app.py web/templates/venues.html tests/test_venues_web.py
git commit -m "feat(venues): GUI de curacion del catalogo de foros"
```

---

## Notas de ejecución

**Orden:** 1 → 2 → 3 → 4 → 5 son secuenciales. La 6 depende de la 5 (necesita `venue_id` poblado). La 7 depende de la 3.

**Después de implementar, antes de correr la siembra en producción:** respaldar la DB con checkpoint del WAL, que es regla del proyecto —
`sqlite3 data/gdlscene.db "PRAGMA wal_checkpoint(TRUNCATE)"` y luego copiar el archivo. La siembra escribe en `venues`, `venue_alias` y `events.venue_id`.

**La siembra cuesta una llamada al LLM.** Correrla en producción gasta saldo de DeepSeek (poco: un solo prompt con ~237 líneas). Es decisión operativa de Ricardo cuándo dispararla.

**Qué esperar de la primera corrida:** unos 40-60 foros en el catálogo, la mayoría de los 612 eventos con `venue_id` resuelto, y una cola de huérfanos con la basura real (nombres de banda, direcciones, OCR ilegible) más los foros que el LLM no supo agrupar. Esa cola es trabajo manual de una sola vez.
