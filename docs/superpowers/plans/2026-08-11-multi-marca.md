# Multi-marca Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** instagod multi-marca: cada marca con perfil propio (fuentes, estilos+chrome, voz, formatos, malla), su bot de Telegram, su Sheet y su cuenta IG; onboarding de Pensión+ hasta publicar en su IG con gdlscene intacto.

**Architecture:** El perfil vive en `accounts` (ampliada) resuelto por un módulo nuevo `src/marcas.py`; secretos SOLO en `.env` por sufijo (`config.account_creds`). Un solo daemon levanta una Application PTB por marca en el mismo loop asyncio. `sheets`/`scheduler`/`instagram`/`publish` se parametrizan por marca. El compilador de slideshows acepta presets por marca y sella `fondo`/`chrome` en el contrato para que el render sea autocontenido.

**Tech Stack:** Python 3.14, SQLite (`src/db.py`), python-telegram-bot v20+ (asyncio), gspread, Jinja2+Playwright, pytest.

**Spec:** `docs/superpowers/specs/2026-08-10-multi-marca-design.md`

## Global Constraints

- Identidad git `richyhoopd <theilluminatiduck@gmail.com>`; NUNCA firmas de Claude/IA en commits.
- Secretos NUNCA en DB ni en la GUI: solo `.env` por sufijo `__SLUG` (mayúsculas). El fallback sin sufijo es EXCLUSIVO de gdlscene (ya implementado en `config.account_creds`) — una marca nueva jamás hereda tokens; hay tests de no-herencia.
- El worker de GitHub Actions NO tiene la SQLite (data/ gitignored): `publish.py` deriva las marcas del ENTORNO (sufijos `SHEET_ID__*`), nunca de la DB.
- Errores accionables: var de entorno faltante → mensaje con el NOMBRE exacto de la var (`Falta SHEET_ID__PENSIONMAS en el .env`); jamás caer en silencio al recurso de gdlscene.
- Ningún test llama Telegram/IG/Sheets/LLM reales; DB temporal real via `db.connect(tmp)/init_db`.
- Mensajes/docstrings en español; `ruff check` limpio antes de cada commit; tests con `/Users/ricardo/Work/personal/instagod/.venv/bin/python -m pytest`.
- `datetime.now()` siempre con `pytz.timezone(config.TIMEZONE)`.
- El daemon sigue siendo el ÚNICO poller (poller_lock global sin cambios); `bot.py` interactivo queda gdlscene-only.
- Fallas preexistentes conocidas de la suite en el checkout principal (no tocar): test_planner (con .env real), test_scraped_mark ×3, test_segmentos_web.

---

### Task 1: Perfil de marca (`src/marcas.py` + migraciones)

**Files:**
- Modify: `src/db.py` (dict `_MIGRATIONS` entrada `"accounts"`; whitelist `TABLES["accounts"]`)
- Modify: `config.py` (línea `_ACCOUNT_CRED_KEYS`)
- Create: `src/marcas.py`
- Test: `tests/test_marcas.py`

**Interfaces:**
- Consumes: `db.connect/init_db/rows/get/insert/update`, `config.account_creds(slug)`, `config.SLIDESHOW_ESTILOS`, `config.SLIDESHOW_FORMATOS`, `config.POSTING_SLOTS`.
- Produces (para Tasks 3-9):
  - `@dataclass Marca: id:int, slug:str, nombre:str, ig_handle:str, color_marca:str, voz:str, fuentes:list[str], formatos:list[str], estilos:dict, logo_path:str|None, posting_slots:list[str]|None, activa:bool`
  - `cargar(cx, slug) -> Marca` (ValueError si no existe), `cargar_por_id(cx, account_id) -> Marca`, `listar(cx, solo_activas=True) -> list[Marca]`
  - `estilos_de(marca) -> dict` (merge marca sobre `config.SLIDESHOW_ESTILOS`)
  - `slots_de(marca) -> list[str]` (propios o `config.POSTING_SLOTS`)
  - `CRED_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "IG_USER_ID", "IG_ACCESS_TOKEN", "SHEET_ID")`
  - `creds_faltantes(slug) -> list[str]` (nombres EXACTOS de vars faltantes, con sufijo; para gdlscene considera el fallback)

- [ ] **Step 1: Migraciones y cred keys**

En `src/db.py`, dentro de `_MIGRATIONS`, agregar la entrada (o ampliar si existiera) para `accounts`:

```python
    "accounts": {
        # Multi-marca (spec 2026-08-10): perfil completo de la marca.
        "fuentes_imagen": "TEXT",   # JSON: orden de sourcing ["pinterest","pexels"]
        "estilos_json": "TEXT",     # JSON: presets de slideshow propios (+chrome)
        "voz": "TEXT",              # system-prompt de marca (tono/compliance/imágenes)
        "formatos": "TEXT",         # JSON: formatos habilitados
        "logo_path": "TEXT",        # asset local en data/brands/<slug>/
        "posting_slots": "TEXT",    # "HH:MM,HH:MM" propio; NULL → global
    },
```

Y en el whitelist `TABLES["accounts"]` agregar esos 6 nombres al set.

En `config.py` reemplazar la línea de `_ACCOUNT_CRED_KEYS`:

```python
_ACCOUNT_CRED_KEYS = ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_SCRAPER_SESSIONID",
                      "IG_SCRAPER_UA", "SHEET_ID",
                      "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
```

- [ ] **Step 2: Escribir los tests que fallan**

`tests/test_marcas.py`:

```python
"""Perfil de marca: carga, defaults, merges y checklist de credenciales."""
from __future__ import annotations

import json

import pytest

import config
from src import db, marcas


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def _alta_pensionmas(cx, **extra):
    campos = dict(slug="pensionmas", ig_handle="@pensionmas", nombre="Pensión+",
                  ciudad="CDMX", voz="Reglas: montos estimados.",
                  fuentes_imagen=json.dumps(["pinterest", "pexels"]),
                  formatos=json.dumps(["listicle", "libre"]),
                  estilos_json=json.dumps({"pensionmas": {"texto": "blanco"}}),
                  posting_slots="10:00,18:00")
    campos.update(extra)
    return db.insert(cx, "accounts", **campos)


def test_cargar_marca_completa(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx)
    m = marcas.cargar(cx, "pensionmas")
    assert m.slug == "pensionmas"
    assert m.fuentes == ["pinterest", "pexels"]
    assert m.formatos == ["listicle", "libre"]
    assert m.estilos == {"pensionmas": {"texto": "blanco"}}
    assert m.posting_slots == ["10:00", "18:00"]
    assert m.voz == "Reglas: montos estimados."


def test_cargar_defaults_sin_json(tmp_path) -> None:
    """gdlscene (seed de Fase A) no tiene columnas nuevas pobladas → defaults."""
    cx = _cx(tmp_path)
    m = marcas.cargar(cx, "gdlscene")
    assert m.fuentes == ["pexels"]
    assert m.formatos == sorted(config.SLIDESHOW_FORMATOS)
    assert m.estilos == {}
    assert m.posting_slots is None
    assert m.voz == ""


def test_cargar_inexistente_lanza(tmp_path) -> None:
    cx = _cx(tmp_path)
    with pytest.raises(ValueError):
        marcas.cargar(cx, "noexiste")


def test_json_malformado_cae_a_default(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx, fuentes_imagen="esto no es json", formatos="[1,")
    m = marcas.cargar(cx, "pensionmas")
    assert m.fuentes == ["pexels"]
    assert m.formatos == sorted(config.SLIDESHOW_FORMATOS)


def test_cargar_por_id_y_listar(tmp_path) -> None:
    cx = _cx(tmp_path)
    mid = _alta_pensionmas(cx)
    assert marcas.cargar_por_id(cx, mid).slug == "pensionmas"
    slugs = [m.slug for m in marcas.listar(cx)]
    assert "gdlscene" in slugs and "pensionmas" in slugs


def test_listar_excluye_inactivas(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx, activa=0)
    assert "pensionmas" not in [m.slug for m in marcas.listar(cx)]
    assert "pensionmas" in [m.slug for m in marcas.listar(cx, solo_activas=False)]


def test_estilos_de_hace_merge_con_prioridad_marca(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx, estilos_json=json.dumps(
        {"tiktok_bold": {"texto": "negro"}, "pensionmas": {"texto": "blanco"}}))
    m = marcas.cargar(cx, "pensionmas")
    fusion = marcas.estilos_de(m)
    assert fusion["tiktok_bold"] == {"texto": "negro"}       # marca pisa global
    assert fusion["pensionmas"] == {"texto": "blanco"}       # propio presente
    assert "editorial" in fusion                             # global sobrevive


def test_slots_de(tmp_path) -> None:
    cx = _cx(tmp_path)
    _alta_pensionmas(cx)
    assert marcas.slots_de(marcas.cargar(cx, "pensionmas")) == ["10:00", "18:00"]
    assert marcas.slots_de(marcas.cargar(cx, "gdlscene")) == config.POSTING_SLOTS


def test_marca_nueva_no_hereda_creds_de_gdlscene(monkeypatch) -> None:
    """REGLA DE ORO: sin sufijo __PENSIONMAS, las creds son None (no fallback)."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-gdl")
    monkeypatch.setenv("SHEET_ID", "sheet-gdl")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    creds = config.account_creds("pensionmas")
    assert creds["TELEGRAM_BOT_TOKEN"] is None
    assert creds["SHEET_ID"] is None
    # gdlscene SÍ cae al global:
    assert config.account_creds("gdlscene")["TELEGRAM_BOT_TOKEN"] == "token-gdl"


def test_creds_faltantes(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", "t")
    for var in ("TELEGRAM_CHAT_ID__PENSIONMAS", "IG_USER_ID__PENSIONMAS",
                "IG_ACCESS_TOKEN__PENSIONMAS", "SHEET_ID__PENSIONMAS"):
        monkeypatch.delenv(var, raising=False)
    faltan = marcas.creds_faltantes("pensionmas")
    assert "TELEGRAM_BOT_TOKEN__PENSIONMAS" not in faltan
    assert "SHEET_ID__PENSIONMAS" in faltan and "IG_ACCESS_TOKEN__PENSIONMAS" in faltan
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `python -m pytest tests/test_marcas.py -v` (con el python del venv)
Expected: FAIL con `ModuleNotFoundError: No module named 'src.marcas'`

- [ ] **Step 4: Implementar `src/marcas.py`**

```python
"""Perfil de marca: resolución de la fila `accounts` a un objeto usable.

Los SECRETOS jamás viven aquí: van en .env por sufijo (config.account_creds).
JSON malformado en el perfil cae a defaults con warning — la generación nunca
truena por un perfil a medias.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass

import config
from src import db

# Vars de entorno que una marca necesita para operar completa (con sufijo).
CRED_VARS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "IG_USER_ID",
             "IG_ACCESS_TOKEN", "SHEET_ID")


@dataclass
class Marca:
    id: int
    slug: str
    nombre: str
    ig_handle: str
    color_marca: str
    voz: str
    fuentes: list[str]
    formatos: list[str]
    estilos: dict
    logo_path: str | None
    posting_slots: list[str] | None
    activa: bool


def _json_o(default, crudo, *, slug: str, campo: str):
    """Parsea JSON tolerante: vacío/malformado/tipo equivocado → default."""
    if not crudo:
        return default
    try:
        val = json.loads(crudo)
    except ValueError:
        print(f"[marcas] {slug}.{campo}: JSON malformado, uso default",
              file=sys.stderr)
        return default
    return val if isinstance(val, type(default)) else default


def _fila_a_marca(fila: dict) -> Marca:
    slug = fila["slug"]
    slots_raw = (fila.get("posting_slots") or "").strip()
    return Marca(
        id=fila["id"],
        slug=slug,
        nombre=fila.get("nombre") or slug,
        ig_handle=fila.get("ig_handle") or "",
        color_marca=fila.get("color_marca") or "#1b5e3f",
        voz=(fila.get("voz") or "").strip(),
        fuentes=_json_o(["pexels"], fila.get("fuentes_imagen"),
                        slug=slug, campo="fuentes_imagen"),
        formatos=_json_o(sorted(config.SLIDESHOW_FORMATOS), fila.get("formatos"),
                         slug=slug, campo="formatos"),
        estilos=_json_o({}, fila.get("estilos_json"),
                        slug=slug, campo="estilos_json"),
        logo_path=fila.get("logo_path") or None,
        posting_slots=[s.strip() for s in slots_raw.split(",") if s.strip()] or None
                      if slots_raw else None,
        activa=bool(fila.get("activa", 1)),
    )


def cargar(cx, slug: str) -> Marca:
    filas = db.rows(cx, "SELECT * FROM accounts WHERE slug = ?", (slug,))
    if not filas:
        raise ValueError(f"No existe la marca {slug!r} en accounts")
    return _fila_a_marca(filas[0])


def cargar_por_id(cx, account_id: int) -> Marca:
    filas = db.rows(cx, "SELECT * FROM accounts WHERE id = ?", (account_id,))
    if not filas:
        raise ValueError(f"No existe la marca con id={account_id}")
    return _fila_a_marca(filas[0])


def listar(cx, solo_activas: bool = True) -> list[Marca]:
    sql = "SELECT * FROM accounts"
    if solo_activas:
        sql += " WHERE activa = 1"
    return [_fila_a_marca(f) for f in db.rows(cx, sql + " ORDER BY id")]


def estilos_de(marca: Marca) -> dict:
    """Presets disponibles para la marca: los suyos PISAN a los globales."""
    return {**config.SLIDESHOW_ESTILOS, **marca.estilos}


def slots_de(marca: Marca) -> list[str]:
    return marca.posting_slots or config.POSTING_SLOTS


def creds_faltantes(slug: str) -> list[str]:
    """Nombres EXACTOS (con sufijo) de las vars de .env que le faltan a la marca.

    Para gdlscene el fallback sin sufijo cuenta como presente (account_creds
    ya lo resuelve).
    """
    creds = config.account_creds(slug)
    sufijo = f"__{slug.upper()}"
    return [v + sufijo for v in CRED_VARS if not creds.get(v)]
```

Nota: `config.POSTING_SLOTS` ya existe como lista de strings "HH:MM" (revisar
su forma exacta en config.py al implementar; si fuera string CSV, ajustar
`slots_de` para normalizar a lista — el test `test_slots_de` fija el contrato).

- [ ] **Step 5: Correr tests y ruff, verificar verde**

Run: `python -m pytest tests/test_marcas.py -v && ruff check src/marcas.py tests/test_marcas.py src/db.py config.py`
Expected: 10 PASS, ruff limpio

- [ ] **Step 6: Commit**

```bash
git add src/marcas.py tests/test_marcas.py src/db.py config.py
git commit -m "feat(marcas): perfil de marca en accounts + resolucion con defaults y checklist de creds"
```

---

### Task 2: `sheets` y `scheduler` parametrizados por marca

**Files:**
- Modify: `src/sheets.py` (funciones `_worksheet`, `_records`, `get_pending_rows`, `get_due_rows`, `append_row`, `update_row`, `ensure_headers`)
- Modify: `src/scheduler.py` (funciones `_slot_times`, `_taken_slots`, `next_free_slot`)
- Test: `tests/test_sheets_multimarca.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces (para Tasks 3-4):
  - `sheets._worksheet(sheet_id: str)` con `@lru_cache(maxsize=8)` (la key ES el sheet_id)
  - Todas las públicas ganan kwarg `sheet_id: str | None = None` (None → `config.SHEET_ID`): `_records(sheet_id=None)`, `get_pending_rows(sheet_id=None)`, `get_due_rows(now=None, *, sheet_id=None)`, `append_row(*, sheet_id=None, **fields)`, `update_row(row_id, *, sheet_id=None, **fields)`, `ensure_headers(sheet_id=None)`
  - `scheduler._slot_times(slots: list[str] | None = None)` (None → `config.POSTING_SLOTS`)
  - `scheduler._taken_slots(sheet_id: str | None = None)`
  - `scheduler.next_free_slot(now=None, *, sheet_id=None, slots=None)` — con `slots` propio, usa `len(slots)` como tope diario (no `config.POSTS_PER_DAY`)
- Compatibilidad: TODOS los callers existentes siguen funcionando sin cambios (defaults = comportamiento actual).

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_sheets_multimarca.py`:

```python
"""Parametrización por marca de sheets y scheduler (sin red: _worksheet fake)."""
from __future__ import annotations

from datetime import datetime

import pytz

import config
from src import scheduler, sheets


class _FakeWS:
    def __init__(self):
        self.rows = []
        self.appended = []

    def get_all_records(self, expected_headers=None):
        return [dict(r) for r in self.rows]

    def append_row(self, row, value_input_option=None):
        self.appended.append(row)

    def row_values(self, i):
        return sheets.COLUMNS

    def batch_update(self, updates):
        self.updates = updates


def _con_fakes(monkeypatch):
    hojas = {}

    def _fake_ws(sheet_id):
        hojas.setdefault(sheet_id, _FakeWS())
        return hojas[sheet_id]

    monkeypatch.setattr(sheets, "_worksheet", _fake_ws)
    return hojas


def test_records_usa_el_sheet_pedido(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    hojas["S2"] = _FakeWS()
    hojas["S2"].rows = [{"id": 1, "status": "approved", "foto_url": ""}]
    assert sheets._records(sheet_id="S2")[0]["id"] == 1
    assert sheets._records(sheet_id="S1") == []          # otra hoja, vacía


def test_records_default_cae_a_config(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    monkeypatch.setattr(config, "SHEET_ID", "S-GLOBAL")
    sheets._records()
    assert "S-GLOBAL" in hojas


def test_append_row_va_al_sheet_de_la_marca(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    rid = sheets.append_row(banda="@pensionmas", status="approved", sheet_id="S2")
    assert rid == 1
    assert hojas["S2"].appended and not hojas.get("S1", _FakeWS()).appended


def test_get_due_rows_por_sheet(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    tz = pytz.timezone(config.TIMEZONE)
    ayer = "2026-08-10T10:00:00"
    hojas["S2"] = _FakeWS()
    hojas["S2"].rows = [{"id": 7, "status": "approved",
                         "scheduled_datetime": ayer, "foto_url": "x"}]
    now = tz.localize(datetime(2026, 8, 11, 12, 0))
    assert [r["id"] for r in sheets.get_due_rows(now, sheet_id="S2")] == [7]
    assert sheets.get_due_rows(now, sheet_id="S1") == []


def test_next_free_slot_con_malla_propia(monkeypatch) -> None:
    _con_fakes(monkeypatch)  # sheets vacíos → nada tomado
    tz = pytz.timezone(config.TIMEZONE)
    now = tz.localize(datetime(2026, 8, 11, 12, 0))
    slot = scheduler.next_free_slot(now, sheet_id="S2", slots=["10:00", "18:00"])
    assert slot.strftime("%H:%M") in ("10:00", "18:00")
    assert slot.date().isoformat() == "2026-08-12"       # empieza mañana


def test_taken_slots_lee_el_sheet_pedido(monkeypatch) -> None:
    hojas = _con_fakes(monkeypatch)
    hojas["S2"] = _FakeWS()
    hojas["S2"].rows = [{"id": 1, "status": "approved",
                         "scheduled_datetime": "2026-08-12T10:00:00"}]
    assert "2026-08-12T10:00" in scheduler._taken_slots(sheet_id="S2")
    assert scheduler._taken_slots(sheet_id="S1") == set()
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_sheets_multimarca.py -v`
Expected: FAIL — `_worksheet()` no acepta argumento / `_records()` no acepta `sheet_id`

- [ ] **Step 3: Implementar la parametrización**

En `src/sheets.py`:

```python
@lru_cache(maxsize=8)
def _worksheet(sheet_id: str) -> gspread.Worksheet:
    client = gspread.authorize(_credentials())
    return client.open_by_key(sheet_id).sheet1


def _sheet(sheet_id: str | None) -> str:
    sid = sheet_id or config.SHEET_ID
    if not sid:
        raise RuntimeError("Falta SHEET_ID en el .env (o el sufijo de la marca)")
    return sid
```

Y cada pública resuelve la hoja al inicio, p. ej.:

```python
def _records(sheet_id: str | None = None) -> list[dict[str, Any]]:
    ws = _worksheet(_sheet(sheet_id))
    records = ws.get_all_records(expected_headers=COLUMNS)
    for i, rec in enumerate(records, start=2):
        rec["_row"] = i
    return records
```

Mismo patrón en `get_pending_rows(sheet_id=None)`, `get_due_rows(now=None, *,
sheet_id=None)`, `ensure_headers(sheet_id=None)`, `append_row(*, sheet_id=None,
**fields)` y `update_row(row_id, *, sheet_id=None, **fields)` — todas pasan
`sheet_id` a `_records`/`_worksheet` internamente. OJO en `append_row`/`update_row`:
`sheet_id` se extrae ANTES de validar columnas (no es columna del Sheet).

En `src/scheduler.py`:

```python
def _slot_times(slots: list[str] | None = None) -> list[time]:
    out = []
    for s in (slots or config.POSTING_SLOTS):
        hh, mm = s.split(":")
        out.append(time(int(hh), int(mm)))
    return sorted(out) or [time(19, 0)]


def _taken_slots(sheet_id: str | None = None) -> set[str]:
    taken: set[str] = set()
    for r in sheets._records(sheet_id=sheet_id):
        ...  # cuerpo actual sin cambios


def next_free_slot(now: datetime | None = None, *, sheet_id: str | None = None,
                   slots: list[str] | None = None) -> datetime:
    ...
    horarios = _slot_times(slots)
    # con malla propia el tope diario ES la malla; sin ella, POSTS_PER_DAY:
    if slots is None:
        horarios = horarios[: max(1, config.POSTS_PER_DAY)]
    taken = _taken_slots(sheet_id=sheet_id)
    ...  # resto del cuerpo actual usando `horarios`
```

(`assign_slot` y `next_free_slot_before` quedan sin cambios: son
gdlscene-only.)

- [ ] **Step 4: Correr tests y ruff (incluye regresión de los existentes)**

Run: `python -m pytest tests/test_sheets_multimarca.py tests/ -q 2>&1 | tail -3 && ruff check src/sheets.py src/scheduler.py tests/test_sheets_multimarca.py`
Expected: nuevos PASS y cero regresiones nuevas (solo las preexistentes documentadas)

- [ ] **Step 5: Commit**

```bash
git add src/sheets.py src/scheduler.py tests/test_sheets_multimarca.py
git commit -m "feat(marcas): sheets y scheduler parametrizados por sheet_id y malla propia"
```

---

### Task 3: `approval` multi-marca

**Files:**
- Modify: `src/approval.py` (funciones `aprobar`, `_siguiente_hueco`, `_sheet_real`, `enviar_a_telegram`)
- Test: `tests/test_approval_multimarca.py`

**Interfaces:**
- Consumes: `marcas.cargar_por_id/slots_de` (Task 1), `sheets.append_row(sheet_id=)`, `scheduler.next_free_slot(sheet_id=, slots=)` (Task 2), `config.account_creds`.
- Produces (para Tasks 5, 8):
  - `enviar_a_telegram(caption, imagen_url, queue_id, *, regenerable=False, account_slug="gdlscene")` — usa token/chat de la marca; RuntimeError con el nombre de la var si falta.
  - `aprobar(...)` (firma pública sin cambios): resuelve la marca desde `content_queue.account_id`; escribe al Sheet de la marca y agenda contra SU malla. `_sheet_real(*, caption, imagen, scheduled, sheet_id=None, banda="@gdlscene")`; `_siguiente_hueco(ahora, sheet_id=None, slots=None)`.
  - El seam de test `_slot_meme` ahora se llama `_slot_meme(ahora, sheet_id, slots)`.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_approval_multimarca.py`:

```python
"""Aprobación multi-marca: Sheet, malla y bot de la marca correcta, siempre."""
from __future__ import annotations

import json
from datetime import datetime

import pytest
import pytz

import config
from src import approval, db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    mid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
                    nombre="Pensión+", ciudad="CDMX", posting_slots="10:00,18:00")
    return cx, mid


def _ahora():
    return datetime.now(pytz.timezone(config.TIMEZONE))


def test_aprobar_usa_sheet_y_malla_de_la_marca(tmp_path, monkeypatch) -> None:
    cx, mid = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="slideshow", caption="c",
                                     imagen_url=json.dumps(["https://x/1.jpg"]),
                                     account_id=mid)
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "SHEET-P")
    llamadas = {}

    def _slot(ahora, sheet_id, slots):
        llamadas["slot"] = (sheet_id, tuple(slots))
        return _ahora()

    def _sheet(**kw):
        llamadas["sheet"] = kw
        return 42

    approval.aprobar(cx, qid, _escribir_sheet=_sheet, _slot_meme=_slot)
    assert llamadas["slot"] == ("SHEET-P", ("10:00", "18:00"))
    assert llamadas["sheet"]["sheet_id"] == "SHEET-P"
    assert llamadas["sheet"]["banda"] == "@pensionmas"
    assert db.get(cx, "content_queue", qid)["sheet_row_id"] == "42"


def test_aprobar_gdlscene_sigue_igual(tmp_path, monkeypatch) -> None:
    cx, _ = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="c",
                                     imagen_url="https://x/1.jpg")  # account_id=1
    monkeypatch.setattr(config, "SHEET_ID", "SHEET-GDL")
    monkeypatch.delenv("SHEET_ID__GDLSCENE", raising=False)
    llamadas = {}

    def _slot(ahora, sheet_id, slots):
        llamadas["slot"] = (sheet_id, slots)
        return _ahora()

    approval.aprobar(cx, qid, _escribir_sheet=lambda **kw: 1, _slot_meme=_slot)
    sheet_id, slots = llamadas["slot"]
    assert sheet_id == "SHEET-GDL"
    assert slots is None            # malla global (POSTS_PER_DAY aplica)


def test_aprobar_sin_sheet_de_marca_revienta_accionable(tmp_path, monkeypatch) -> None:
    cx, mid = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="slideshow", caption="c",
                                     imagen_url="u", account_id=mid)
    monkeypatch.delenv("SHEET_ID__PENSIONMAS", raising=False)
    with pytest.raises(RuntimeError, match="SHEET_ID__PENSIONMAS"):
        approval.aprobar(cx, qid, _escribir_sheet=lambda **kw: 1,
                         _slot_meme=lambda a, s, sl: _ahora())
    # la fila NO quedó aprobada
    assert db.get(cx, "content_queue", qid)["aprobacion"] == "pendiente"


def test_enviar_a_telegram_usa_bot_de_la_marca(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", "tok-p")
    monkeypatch.setenv("TELEGRAM_CHAT_ID__PENSIONMAS", "777")
    urls = []

    class _Resp:
        def raise_for_status(self):
            pass

    def _post(url, data=None, timeout=None):
        urls.append(url)
        return _Resp()

    import requests
    monkeypatch.setattr(requests, "post", _post)
    approval.enviar_a_telegram("hola", "https://x/1.jpg", 5,
                               account_slug="pensionmas")
    assert all("bottok-p/" in u for u in urls)


def test_enviar_sin_token_de_marca_revienta_accionable(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-gdl")  # NO debe usarse
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN__PENSIONMAS"):
        approval.enviar_a_telegram("hola", "u", 5, account_slug="pensionmas")
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_approval_multimarca.py -v`
Expected: FAIL — `_slot_meme` recibe 1 arg / `enviar_a_telegram` no acepta `account_slug`

- [ ] **Step 3: Implementar**

En `src/approval.py`:

`aprobar` — tras leer `fila`, resolver la marca y pasar sheet/malla:

```python
    from src import marcas as marcas_mod
    marca = marcas_mod.cargar_por_id(cx, fila.get("account_id") or 1)
    creds = _creds_de(marca.slug)
    sheet_id = creds.get("SHEET_ID")
    if not sheet_id:
        raise RuntimeError(f"Falta SHEET_ID__{marca.slug.upper()} en el .env")
    # malla propia solo si la marca la define; None = malla global de gdlscene
    slots = marca.posting_slots
    inmediato = fila.get("tipo") == "anuncio"
    if inmediato:
        slot = ahora
    else:
        slot = (_slot_meme or _siguiente_hueco)(ahora, sheet_id, slots)
    escribir = _escribir_sheet or _sheet_real
    sheet_row = escribir(caption=fila.get("caption"),
                         imagen=fila.get("imagen_url"),
                         scheduled=slot.isoformat(),
                         sheet_id=sheet_id,
                         banda=marca.ig_handle or f"@{marca.slug}")
```

(el resto del cuerpo — update de la fila, foto usada, evento_ids, publicar
inmediato — queda idéntico). Helper nuevo:

```python
def _creds_de(slug: str) -> dict:
    import config as cfg
    return cfg.account_creds(slug)
```

```python
def _siguiente_hueco(ahora: datetime, sheet_id: str | None = None,
                     slots: list[str] | None = None) -> datetime:
    from src import scheduler
    return scheduler.next_free_slot(ahora, sheet_id=sheet_id, slots=slots)


def _sheet_real(*, caption, imagen, scheduled, sheet_id=None,
                banda="@gdlscene") -> int:
    from src import sheets
    return sheets.append_row(banda=banda, caption_generado=caption,
                             caption_final=caption, imagen_compuesta_url=imagen,
                             status=sheets.STATUS_APPROVED,
                             scheduled_datetime=scheduled, sheet_id=sheet_id)
```

`enviar_a_telegram` — resolver por marca al inicio (reemplaza las 2 líneas de
`base_url`/`chat_id`):

```python
def enviar_a_telegram(caption: str, imagen_url: str, queue_id: int,
                      *, regenerable: bool = False,
                      account_slug: str = "gdlscene") -> None:
    ...
    creds = _creds_de(account_slug)
    token = creds.get("TELEGRAM_BOT_TOKEN")
    chat_id = creds.get("TELEGRAM_CHAT_ID")
    if not token:
        raise RuntimeError(
            f"Falta TELEGRAM_BOT_TOKEN__{account_slug.upper()} en el .env")
    if not chat_id:
        raise RuntimeError(
            f"Falta TELEGRAM_CHAT_ID__{account_slug.upper()} en el .env")
    base_url = f"https://api.telegram.org/bot{token}"
```

(el resto del cuerpo idéntico).

- [ ] **Step 4: Correr tests y ruff (incluye tests existentes de approval)**

Run: `python -m pytest tests/test_approval_multimarca.py tests/test_approval.py tests/test_send_plan.py -v 2>&1 | tail -3 && ruff check src/approval.py tests/test_approval_multimarca.py`
Expected: PASS todo. Si `tests/test_approval.py` inyectaba `_slot_meme` con 1 argumento, actualizar esos tests a la firma nueva `(ahora, sheet_id, slots)` — es el único cambio de contrato permitido.

- [ ] **Step 5: Commit**

```bash
git add src/approval.py tests/test_approval_multimarca.py tests/test_approval.py
git commit -m "feat(marcas): aprobacion resuelve sheet, malla y bot por marca con errores accionables"
```

---

### Task 4: `instagram` con creds inyectables + `publish.py` por marcas

**Files:**
- Modify: `src/instagram.py` (todas las funciones: threading de `creds`)
- Modify: `publish.py` (`main`, `publish_row`)
- Modify: `config.py` (helper `marcas_en_env`)
- Test: `tests/test_publish_multimarca.py`

**Interfaces:**
- Consumes: `sheets.get_due_rows(sheet_id=)`, `sheets.update_row(row_id, sheet_id=)`, `config.account_creds`.
- Produces:
  - `instagram.publish(image_url, caption, *, retries=3, creds=None)` y `instagram.publish_carousel(image_urls, caption, *, retries=3, creds=None)` donde `creds = {"user_id": ..., "token": ...}`; `None` → globals de config (compatibilidad total).
  - `config.marcas_en_env() -> list[str]` — `["gdlscene"] + [slug.lower() por cada SHEET_ID__<SLUG> en os.environ]`, sin duplicados, orden estable.
  - `publish.publicar_marca(slug) -> None` — procesa las filas due del Sheet de esa marca con sus creds; `publish.main()` itera `config.marcas_en_env()`.
  - Crosspost FB/X SOLO corre para gdlscene (las demás marcas publican únicamente IG).

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_publish_multimarca.py`:

```python
"""publish.py multi-marca: cada Sheet con sus creds; marcas desde el ENV."""
from __future__ import annotations

import config
import publish
from src import instagram, sheets


def test_marcas_en_env(monkeypatch) -> None:
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "S2")
    monkeypatch.setenv("SHEET_ID__TELCO", "S3")
    ms = config.marcas_en_env()
    assert ms[0] == "gdlscene"
    assert set(ms) == {"gdlscene", "pensionmas", "telco"}
    assert len(ms) == len(set(ms))


def test_instagram_publish_usa_creds_inyectadas(monkeypatch) -> None:
    posts = []

    class _Resp:
        status_code = 200

        def json(self):
            return {"id": "post1", "status_code": "FINISHED"}

    def _post(url, data=None, timeout=None):
        posts.append((url, data))
        return _Resp()

    monkeypatch.setattr(instagram.requests, "post", _post)
    monkeypatch.setattr(instagram.requests, "get", lambda *a, **kw: _Resp())
    out = instagram.publish("https://cdn/x.jpg", "hola",
                            creds={"user_id": "UP", "token": "TP"})
    assert out == "post1"
    assert all("/UP/" in url for url, _ in posts)
    assert all(d["access_token"] == "TP" for _, d in posts)


def test_publicar_marca_pasa_sheet_y_creds(monkeypatch) -> None:
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "S2")
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "UP")
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "TP")
    filas = [{"id": 9, "imagen_compuesta_url": "https://cdn/a.jpg",
              "caption_final": "c", "status": "approved",
              "ig_post_id": "", "tw_post_id": "", "fb_post_id": ""}]
    vistos = {}
    monkeypatch.setattr(sheets, "get_due_rows",
                        lambda now=None, sheet_id=None:
                        filas if sheet_id == "S2" else [])
    monkeypatch.setattr(sheets, "update_row",
                        lambda rid, sheet_id=None, **kw:
                        vistos.setdefault("update", (rid, sheet_id, kw)))
    monkeypatch.setattr(instagram, "publish",
                        lambda url, cap, creds=None:
                        vistos.setdefault("creds", creds) or "ig9")
    publish.publicar_marca("pensionmas")
    assert vistos["creds"] == {"user_id": "UP", "token": "TP"}
    assert vistos["update"][1] == "S2"


def test_marca_sin_ig_no_publica_y_avisa(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SHEET_ID__PENSIONMAS", "S2")
    monkeypatch.delenv("IG_ACCESS_TOKEN__PENSIONMAS", raising=False)
    publish.publicar_marca("pensionmas")
    assert "IG_ACCESS_TOKEN__PENSIONMAS" in capsys.readouterr().out


def test_crosspost_solo_gdlscene(monkeypatch) -> None:
    plat = publish._plataformas_de("pensionmas")
    assert [p[1] for p in plat] == ["ig"]
    etiquetas = [p[1] for p in publish._plataformas_de("gdlscene")]
    assert "ig" in etiquetas          # fb/x según flags, ig siempre
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_publish_multimarca.py -v`
Expected: FAIL — `marcas_en_env` no existe / `publish` no acepta `creds` / `publicar_marca` no existe

- [ ] **Step 3: Implementar**

`config.py` (junto a `account_creds`):

```python
def marcas_en_env() -> list[str]:
    """Slugs de marcas visibles para el worker: gdlscene + sufijos SHEET_ID__*.

    El worker de Actions NO tiene la SQLite (data/ gitignored): el entorno es
    la fuente de verdad de qué marcas publica.
    """
    out = ["gdlscene"]
    for k in sorted(os.environ):
        if k.startswith("SHEET_ID__"):
            slug = k.removeprefix("SHEET_ID__").lower()
            if slug and slug not in out:
                out.append(slug)
    return out
```

`src/instagram.py` — threading de creds (patrón, aplicar a TODAS las helpers):

```python
def _c(creds: dict | None) -> tuple[str, str]:
    """(user_id, token) de las creds inyectadas o de config (gdlscene)."""
    if creds:
        return creds["user_id"], creds["token"]
    return config.IG_USER_ID, config.IG_ACCESS_TOKEN


def _create_container(image_url: str, caption: str, creds: dict | None = None) -> str:
    user_id, token = _c(creds)
    url = f"{_base()}/{user_id}/media"
    resp = requests.post(url, data={"image_url": image_url, "caption": caption,
                                    "access_token": token}, timeout=_TIMEOUT)
    _raise_for_graph(resp)
    return resp.json()["id"]
```

Igual en `_create_carousel_item`, `_create_carousel_container`,
`_wait_until_ready`, `_publish`; y las públicas propagan:
`publish(image_url, caption, *, retries=3, creds=None)` /
`publish_carousel(image_urls, caption, *, retries=3, creds=None)` pasando
`creds` a cada helper interno.

`publish.py`:

```python
def _plataformas_de(slug: str) -> list[tuple]:
    """Redes que aplican a la marca: IG siempre; FB/X solo gdlscene (flags)."""
    if slug == "gdlscene":
        return PLATFORMS
    return [p for p in PLATFORMS if p[1] == "ig"]


def publish_row(row: dict, *, slug: str = "gdlscene",
                sheet_id: str | None = None, ig_creds: dict | None = None
                ) -> tuple[bool, list[str]]:
    ...  # cuerpo actual, con dos cambios:
    for col, tag, mod, enabled in _plataformas_de(slug):
        ...
        kwargs = {"creds": ig_creds} if tag == "ig" else {}
        post_id = (mod.publish_carousel(urls, caption, **kwargs) if urls
                   else mod.publish(image_url, caption, **kwargs))
        sheets.update_row(row_id, sheet_id=sheet_id, **{col: post_id})


def publicar_marca(slug: str) -> None:
    creds = config.account_creds(slug)
    sheet_id = creds.get("SHEET_ID")
    if not sheet_id:
        print(f"⏭ {slug}: falta SHEET_ID__{slug.upper()} en el entorno")
        return
    if not (creds.get("IG_USER_ID") and creds.get("IG_ACCESS_TOKEN")):
        print(f"⏭ {slug}: falta IG_USER_ID__{slug.upper()} o "
              f"IG_ACCESS_TOKEN__{slug.upper()} en el entorno")
        return
    ig_creds = ({"user_id": creds["IG_USER_ID"], "token": creds["IG_ACCESS_TOKEN"]}
                if slug != "gdlscene" else None)  # gdlscene usa globals (igual que hoy)
    due = sheets.get_due_rows(sheet_id=None if slug == "gdlscene" else sheet_id)
    ...  # mismo cuerpo del main() actual (sort agendas, loop, published/parcial)
        # pero pasando slug=slug, sheet_id=(None si gdlscene) e ig_creds a
        # publish_row y sheet_id a cada sheets.update_row.


def main() -> None:
    for slug in config.marcas_en_env():
        print(f"— marca: {slug}")
        publicar_marca(slug)
```

(gdlscene con `sheet_id=None` conserva el comportamiento exacto actual,
incluida la ausencia de `SHEET_ID__GDLSCENE` en el repo de Actions.)

- [ ] **Step 4: Correr tests y ruff**

Run: `python -m pytest tests/test_publish_multimarca.py tests/ -q 2>&1 | tail -3 && ruff check publish.py src/instagram.py config.py tests/test_publish_multimarca.py`
Expected: nuevos PASS, cero regresiones nuevas

- [ ] **Step 5: Commit**

```bash
git add publish.py src/instagram.py config.py tests/test_publish_multimarca.py
git commit -m "feat(marcas): publish itera marcas del entorno con creds IG y Sheet propios"
```

---

### Task 5: Daemon multi-bot

**Files:**
- Modify: `src/approval_daemon.py` (reemplaza `main`; agrega `marcas_con_bot`, `construir_app`, `correr`, `_latido_loop_multi`; elimina `_post_init`/`_latido_loop` de una sola app)
- Test: `tests/test_daemon_multibot.py`

**Interfaces:**
- Consumes: `marcas.listar` (Task 1), `config.account_creds`, `poller_lock.adquirir`, `daemon_health.escribir_latido`, handlers existentes (`on_aprobacion`, `on_recomponer`, `bot.on_photo/on_reply/on_callback/on_error`).
- Produces:
  - `marcas_con_bot(lista_marcas, creds_de=config.account_creds) -> list[tuple[Marca, dict]]` — PURO: solo marcas con token+chat; imprime cuáles se saltan y por qué var.
  - `construir_app(token, chat_id, slug, *, interactivo=False) -> Application` — handlers de aprobación en todas; los interactivos de `bot.py` SOLO cuando `interactivo=True` (gdlscene).
  - `correr(apps) -> None` (corrutina): initialize→start→start_polling de todas, latido multi-app, espera señal, shutdown en orden inverso tolerante a fallos.
  - `main()`: lock → carga marcas de la DB → construye apps (gdlscene `interactivo=True`) → `asyncio.run(correr(apps))`. RuntimeError si NINGUNA marca tiene bot.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_daemon_multibot.py`:

```python
"""Daemon multi-bot: filtrado de marcas, ciclo de vida y latido multi-app."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from src import approval_daemon as ad


@dataclass
class _M:
    slug: str


def _creds(mapa):
    return lambda slug: mapa.get(slug, {"TELEGRAM_BOT_TOKEN": None,
                                        "TELEGRAM_CHAT_ID": None})


def test_marcas_con_bot_filtra_y_avisa(capsys) -> None:
    mapa = {"gdlscene": {"TELEGRAM_BOT_TOKEN": "t1", "TELEGRAM_CHAT_ID": "1"},
            "pensionmas": {"TELEGRAM_BOT_TOKEN": None, "TELEGRAM_CHAT_ID": None}}
    pares = ad.marcas_con_bot([_M("gdlscene"), _M("pensionmas")],
                              creds_de=_creds(mapa))
    assert [m.slug for m, _ in pares] == ["gdlscene"]
    assert "TELEGRAM_BOT_TOKEN__PENSIONMAS" in capsys.readouterr().out


@dataclass
class _FakeUpdater:
    running: bool = False
    llamadas: list = field(default_factory=list)

    async def start_polling(self, **kw):
        self.running = True
        self.llamadas.append(("poll", kw))

    async def stop(self):
        self.running = False
        self.llamadas.append(("stop_poll", None))


@dataclass
class _FakeApp:
    nombre: str
    log: list
    updater: _FakeUpdater = field(default_factory=_FakeUpdater)

    async def initialize(self):
        self.log.append(f"init:{self.nombre}")

    async def start(self):
        self.log.append(f"start:{self.nombre}")

    async def stop(self):
        self.log.append(f"stop:{self.nombre}")

    async def shutdown(self):
        self.log.append(f"shutdown:{self.nombre}")


def test_correr_arranca_todas_y_apaga_en_orden_inverso(monkeypatch) -> None:
    log: list = []
    apps = [_FakeApp("a", log), _FakeApp("b", log)]

    async def _sin_espera():
        return None

    monkeypatch.setattr(ad, "_esperar_senal", _sin_espera)
    asyncio.run(ad.correr(apps))
    assert log[:4] == ["init:a", "init:b", "start:a", "start:b"]
    assert all(u.llamadas[0][0] == "poll" for u in (apps[0].updater, apps[1].updater))
    # apagado inverso: b antes que a
    assert log.index("stop:b") < log.index("stop:a")
    assert log.index("shutdown:b") < log.index("shutdown:a")


def test_correr_shutdown_tolera_fallos(monkeypatch) -> None:
    log: list = []
    apps = [_FakeApp("a", log), _FakeApp("b", log)]

    async def _boom():
        raise RuntimeError("stop roto")

    apps[1].stop = _boom  # el fallo de b NO debe impedir apagar a

    async def _sin_espera():
        return None

    monkeypatch.setattr(ad, "_esperar_senal", _sin_espera)
    asyncio.run(ad.correr(apps))
    assert "stop:a" in log and "shutdown:a" in log


def test_latido_solo_si_todos_los_updaters_corren(monkeypatch) -> None:
    latidos = []
    monkeypatch.setattr(ad.daemon_health, "escribir_latido",
                        lambda: latidos.append(1))
    log: list = []
    a, b = _FakeApp("a", log), _FakeApp("b", log)
    a.updater.running = True
    b.updater.running = False
    assert ad._todos_corriendo([a, b]) is False
    b.updater.running = True
    assert ad._todos_corriendo([a, b]) is True
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_daemon_multibot.py -v`
Expected: FAIL — `marcas_con_bot` no existe

- [ ] **Step 3: Implementar**

En `src/approval_daemon.py` (los handlers `on_aprobacion`/`on_recomponer`,
`_aprobar_sync`, `_rechazar_sync`, `_recomponer_sync`, `_resolver_msg` y
`_pretty` quedan EXACTAMENTE como están; se reemplaza el bloque
`_latido_loop`/`_post_init`/`main` completo):

```python
import contextlib
import signal

from src import marcas as marcas_mod


def marcas_con_bot(lista, creds_de=None):
    """PURO: (marca, creds) de las que tienen bot completo; avisa las que no."""
    creds_de = creds_de or config.account_creds
    pares = []
    for m in lista:
        creds = creds_de(m.slug)
        if creds.get("TELEGRAM_BOT_TOKEN") and creds.get("TELEGRAM_CHAT_ID"):
            pares.append((m, creds))
        else:
            faltan = [f"TELEGRAM_BOT_TOKEN__{m.slug.upper()}"
                      if not creds.get("TELEGRAM_BOT_TOKEN") else None,
                      f"TELEGRAM_CHAT_ID__{m.slug.upper()}"
                      if not creds.get("TELEGRAM_CHAT_ID") else None]
            print(f"[daemon] marca {m.slug} sin bot: faltan "
                  + ", ".join(v for v in faltan if v))
    return pares


def construir_app(token: str, chat_id: str, slug: str,
                  *, interactivo: bool = False) -> Application:
    """Una Application PTB por marca, con los mismos handlers de aprobación.

    Los handlers interactivos de bot.py (foto→meme, replies) son gdlscene-only.
    """
    app = Application.builder().token(token).build()
    app.bot_data["slug"] = slug
    solo_tu = filters.Chat(int(chat_id))
    app.add_handler(CallbackQueryHandler(on_aprobacion, pattern=r"^(aprobar|rechazar):"))
    app.add_handler(CallbackQueryHandler(on_recomponer, pattern=r"^(regenerar|plantilla):"))
    if interactivo:
        app.add_handler(MessageHandler(filters.PHOTO & solo_tu, bot.on_photo))
        app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & solo_tu, bot.on_reply))
        app.add_handler(CallbackQueryHandler(bot.on_callback,
                                             pattern=r"^(approve|reject|regen|tpl):"))
    app.add_error_handler(bot.on_error)
    return app


def _todos_corriendo(apps) -> bool:
    return all(getattr(a.updater, "running", False) for a in apps)


async def _latido_loop_multi(apps) -> None:
    """Latido SOLO si TODOS los updaters corren: un bot caído = latido viejo →
    el watchdog reinicia el daemon completo (todas las marcas)."""
    daemon_health.escribir_latido()  # latido inicial: cubre el arranque
    while True:
        try:
            if _todos_corriendo(apps):
                daemon_health.escribir_latido()
        except Exception as e:  # el latido jamás tumba el daemon
            print(f"WARNING latido: {e}", file=sys.stderr)
        await asyncio.sleep(daemon_health.LATIDO_INTERVALO_SEG)


async def _esperar_senal() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()


async def correr(apps) -> None:
    """Ciclo de vida de N Applications en un solo loop."""
    for app in apps:
        await app.initialize()
    for app in apps:
        await app.start()
    for app in apps:
        # bootstrap_retries=-1: parpadeo de red al arrancar reintenta indefinido
        await app.updater.start_polling(drop_pending_updates=True,
                                        bootstrap_retries=-1)
    latido = asyncio.create_task(_latido_loop_multi(apps))
    try:
        await _esperar_senal()
    finally:
        latido.cancel()
        for app in reversed(apps):
            with contextlib.suppress(Exception):
                await app.updater.stop()
        for app in reversed(apps):
            with contextlib.suppress(Exception):
                await app.stop()
        for app in reversed(apps):
            with contextlib.suppress(Exception):
                await app.shutdown()


def main() -> None:
    poller_lock.adquirir()
    cx = db.connect()
    try:
        db.init_db(cx)
        lista = marcas_mod.listar(cx)
    finally:
        cx.close()
    pares = marcas_con_bot(lista)
    if not pares:
        raise RuntimeError("Ninguna marca tiene TELEGRAM_BOT_TOKEN/CHAT_ID: "
                           "no hay bots que polear")
    apps = [construir_app(creds["TELEGRAM_BOT_TOKEN"], creds["TELEGRAM_CHAT_ID"],
                          m.slug, interactivo=(m.slug == "gdlscene"))
            for m, creds in pares]
    print(f"Daemon multi-bot: {len(apps)} marca(s) — "
          + ", ".join(m.slug for m, _ in pares))
    asyncio.run(correr(apps))
```

- [ ] **Step 4: Correr tests y ruff**

Run: `python -m pytest tests/test_daemon_multibot.py tests/test_daemon_health.py tests/test_poller_lock.py -v 2>&1 | tail -3 && ruff check src/approval_daemon.py tests/test_daemon_multibot.py`
Expected: PASS todo

- [ ] **Step 5: Commit**

```bash
git add src/approval_daemon.py tests/test_daemon_multibot.py
git commit -m "feat(marcas): daemon multi-bot, una Application PTB por marca en un solo loop"
```

---

### Task 6: Branding en el compilador y la plantilla (chrome + woff2 + paleta)

**Files:**
- Modify: `config.py` (`SLIDESHOW_PALETA` += 4 colores; `SLIDESHOW_FUENTES` += 2 Erode)
- Create: `templates/assets/fonts/erode-600.woff2`, `templates/assets/fonts/erode-700.woff2` (copiar de `/Users/ricardo/Work/personal/tulanaya/public/fonts/`)
- Modify: `src/slideshow_compile.py` (`compilar` gana `estilos=`; sella `fondo`/`chrome` en el brief; `contexto_slide` emite `chrome` y `fmt` por fuente; `_COLORES_CLAROS` += "oro")
- Modify: `templates/slide.html` (font-face con formato dinámico; bloque `.chrome`)
- Test: `tests/test_slideshow_compile.py` (ampliar), `tests/test_slide_render.py` (ampliar)

**Interfaces:**
- Consumes: contrato Task 1 del motor v1 (sin cambios de dataclasses).
- Produces (para Tasks 7-8):
  - `compilar(guion, *, estilo, imagenes, aspect_ratio="4:5", brief=None, formato="", account_slug="gdlscene", estilos=None) -> Slideshow` — `estilos` es el dict de presets resuelto (marca+global); `None` → `config.SLIDESHOW_ESTILOS`. Sella `brief["estilo"]`, `brief["fondo"]` (nombre de paleta) y `brief["chrome"]` (dict o None) → el contrato es AUTOCONTENIDO para re-render.
  - Esquema de preset ampliado: clave opcional `"chrome": {"handle": "@marca", "logo": "ruta/o/None"}`.
  - `contexto_slide(s, idx)` — sin cambio de firma; agrega al ctx: `"chrome": {"handle": str, "logo_src": str|None} | None`, y cada entrada de `font_faces` gana `"fmt": "woff2"|"truetype"` según extensión. `bg_color` sale de `brief["fondo"]` (fallback: lookup en config como hoy, para filas viejas).
  - Paleta nueva: `"cobalto": "#2F52D9"`, `"navy": "#1A2142"`, `"oro": "#EAC366"`, `"oro_profundo": "#A57D2A"` (conversión aproximada de los OKLCH de tulanaya/DESIGN.md). Fuentes nuevas: `"Erode-Semibold": "erode-600.woff2"`, `"Erode-Bold": "erode-700.woff2"`.

- [ ] **Step 1: Copiar fuentes y ampliar config**

```bash
cp /Users/ricardo/Work/personal/tulanaya/public/fonts/erode-600.woff2 templates/assets/fonts/
cp /Users/ricardo/Work/personal/tulanaya/public/fonts/erode-700.woff2 templates/assets/fonts/
```

En `config.py`, dentro de `SLIDESHOW_PALETA` agregar:

```python
    # Pensión+ (conversión aproximada de los OKLCH de tulanaya/DESIGN.md):
    "cobalto": "#2F52D9",
    "navy": "#1A2142",
    "oro": "#EAC366",
    "oro_profundo": "#A57D2A",
```

Y en `SLIDESHOW_FUENTES`:

```python
    "Erode-Semibold": "erode-600.woff2",
    "Erode-Bold": "erode-700.woff2",
```

- [ ] **Step 2: Escribir los tests que fallan**

Agregar al final de `tests/test_slideshow_compile.py`:

```python
def test_compilar_acepta_estilos_de_marca() -> None:
    estilos = {"pensionmas": {"texto": "blanco", "fondo": "navy",
                              "background_opacity": 0.3,
                              "chrome": {"handle": "@pensionmas", "logo": None},
                              "roles": {"hook": {"font": "Erode-Bold",
                                                 "font_size": "extra_large",
                                                 "text_style": "background",
                                                 "text_vertical_anchor": "center"},
                                        "punto": {"font": "Erode-Semibold",
                                                  "font_size": "large",
                                                  "text_style": "background",
                                                  "text_vertical_anchor": "center"},
                                        "cta": {"font": "Poppins-SemiBold",
                                                "font_size": "medium",
                                                "text_style": "background",
                                                "text_vertical_anchor": "bottom"}}}}
    s = sc.compilar(_guion(), estilo="pensionmas", imagenes=[None] * 3,
                    estilos=estilos, account_slug="pensionmas")
    assert s.brief["fondo"] == "navy"
    assert s.brief["chrome"]["handle"] == "@pensionmas"
    assert s.slides[0].text_items[0].font == "Erode-Bold"
    import config as cfg
    ctx = sc.contexto_slide(s, 0)
    assert ctx["bg_color"] == cfg.SLIDESHOW_PALETA["navy"]
    assert ctx["chrome"] == {"handle": "@pensionmas", "logo_src": None}


def test_contexto_slide_sin_chrome_es_none() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    assert sc.contexto_slide(s, 0)["chrome"] is None


def test_font_faces_declaran_formato() -> None:
    s = sc.compilar(_guion(), estilo="tiktok_bold", imagenes=[None] * 3)
    faces = {f["name"]: f["fmt"] for f in sc.contexto_slide(s, 0)["font_faces"]}
    assert faces["Erode-Bold"] == "woff2"
    assert faces["Anton-Regular"] == "truetype"
```

Agregar al final de `tests/test_slide_render.py`:

```python
def test_render_slide_con_chrome(tmp_path) -> None:
    """El pie de marca (handle) rinde sin romper el auto-fit."""
    estilos = {"pensionmas": {"texto": "blanco", "fondo": "navy",
                              "background_opacity": 0.3,
                              "chrome": {"handle": "@pensionmas", "logo": None},
                              "roles": {"hook": {"font": "Erode-Bold",
                                                 "font_size": "extra_large",
                                                 "text_style": "background",
                                                 "text_vertical_anchor": "center"},
                                        "punto": {"font": "Erode-Semibold",
                                                  "font_size": "large",
                                                  "text_style": "background",
                                                  "text_vertical_anchor": "center"},
                                        "cta": {"font": "Poppins-SemiBold",
                                                "font_size": "medium",
                                                "text_style": "background",
                                                "text_vertical_anchor": "bottom"}}}}
    show = sc.compilar(_guion(), estilo="pensionmas", imagenes=[None] * 3,
                       estilos=estilos)
    png = compose.render_card("slide.html", sc.contexto_slide(show, 0),
                              out_path=tmp_path / "chrome.png")
    assert png.exists() and png.stat().st_size > 10_000
```

- [ ] **Step 3: Correr y verificar que fallan**

Run: `python -m pytest tests/test_slideshow_compile.py tests/test_slide_render.py -v 2>&1 | tail -4`
Expected: FAIL — `compilar` no acepta `estilos` / ctx sin `chrome`/`fmt`

- [ ] **Step 4: Implementar**

`src/slideshow_compile.py`:

```python
_COLORES_CLAROS = {"blanco", "crema", "amarillo", "oro"}


def compilar(guion, *, estilo, imagenes, aspect_ratio="4:5", brief=None,
             formato="", account_slug="gdlscene", estilos=None) -> Slideshow:
    catalogo = estilos if estilos is not None else config.SLIDESHOW_ESTILOS
    preset = catalogo[estilo]  # KeyError si no existe: a propósito
    brief_final = dict(brief or {})
    brief_final.setdefault("estilo", estilo)
    # El contrato es autocontenido: fondo y chrome viajan con él (los presets
    # de marca NO viven en config, así que el render no puede re-buscarlos).
    brief_final.setdefault("fondo", preset.get("fondo", "negro"))
    brief_final.setdefault("chrome", preset.get("chrome"))
    ...  # resto idéntico, usando `preset` (ya no config.SLIDESHOW_ESTILOS[...])
    #     y pasando brief_final al Slideshow.
```

`contexto_slide` — reemplazar la resolución de fondo y agregar chrome/fmt:

```python
    fondo = s.brief.get("fondo")
    if not fondo:  # filas viejas (pre-multi-marca): lookup como antes
        preset_cfg = config.SLIDESHOW_ESTILOS.get(s.brief.get("estilo", ""), {})
        fondo = preset_cfg.get("fondo", "negro")
    chrome_brief = s.brief.get("chrome") or None
    chrome = None
    if chrome_brief:
        logo = chrome_brief.get("logo")
        chrome = {"handle": chrome_brief.get("handle", ""),
                  "logo_src": _to_src(logo) if logo else None}
    ...
    return {
        ...,
        "bg_color": config.SLIDESHOW_PALETA[fondo],
        "chrome": chrome,
        "font_faces": [{"name": nombre,
                        "url": (FONTS_DIR / archivo).as_uri(),
                        "fmt": "woff2" if archivo.endswith(".woff2") else "truetype"}
                       for nombre, archivo in config.SLIDESHOW_FUENTES.items()],
    }
```

`templates/slide.html` — font-face con formato dinámico:

```html
  {% for f in font_faces %}
  @font-face { font-family:'{{ f.name }}'; src:url('{{ f.url }}') format('{{ f.fmt }}'); }
  {% endfor %}
```

CSS del chrome (junto a las reglas de `.txt`):

```css
  .chrome {
    position:absolute; left:0; right:0; bottom:{{ (height * 0.025) | round | int }}px;
    display:flex; align-items:center; justify-content:center; gap:14px;
    font-family:'Poppins-SemiBold',sans-serif;
    font-size:{{ (width * 0.028) | round | int }}px;
    color:rgba(255,255,255,.92); letter-spacing:.04em; z-index:10;
    text-shadow:0 1px 8px rgba(0,0,0,.5);
  }
  .chrome img { height:{{ (width * 0.04) | round | int }}px; display:block; }
```

Y el bloque en el body, dentro de `.card`, DESPUÉS de `.zonas`:

```html
    {% if chrome %}
    <div class="chrome">
      {% if chrome.logo_src %}<img src="{{ chrome.logo_src }}">{% endif %}
      <span>{{ chrome.handle }}</span>
    </div>
    {% endif %}
```

Ajuste para que la zona bottom no choque con el chrome: en `.zonas`, el
`padding` inferior sube cuando hay chrome —

```css
  .zonas { ... padding:{{ (height * 0.06) | round | int }}px 0
           {{ (height * (0.10 if chrome else 0.06)) | round | int }}px 0; }
```

(padding shorthand: arriba derecha abajo izquierda — verificar el shorthand
actual de la plantilla y ajustar SOLO el componente inferior.)

- [ ] **Step 5: Correr tests, inspección visual y ruff**

Run: `python -m pytest tests/test_slideshow_compile.py tests/test_slide_render.py -v && ruff check src/slideshow_compile.py config.py`
Expected: PASS todo.

Además, renderizar el demo del chrome e INSPECCIONARLO a ojo (leer el PNG):
navy de fondo, hook en Erode, "@pensionmas" legible al pie sin encimarse con
el CTA. Iterar CSS si algo se ve mal ANTES de commitear.

- [ ] **Step 6: Commit**

```bash
git add config.py src/slideshow_compile.py templates/slide.html templates/assets/fonts/erode-600.woff2 templates/assets/fonts/erode-700.woff2 tests/test_slideshow_compile.py tests/test_slide_render.py
git commit -m "feat(marcas): presets por marca con chrome de identidad, paleta pension+ y fuentes Erode"
```

---

### Task 7: Seeds de marca (`src/marcas_seed.py`)

**Files:**
- Create: `src/marcas_seed.py`
- Test: `tests/test_marcas_seed.py`

**Interfaces:**
- Consumes: `db`, `marcas.cargar` (Task 1); esquema de preset con `chrome` (Task 6).
- Produces:
  - `ESTILOS_GDLSCENE: dict`, `ESTILOS_PENSIONMAS: dict`, `VOZ_PENSIONMAS: str` (constantes públicas, reutilizables por la GUI como plantillas).
  - `sembrar(cx) -> None` — idempotente: actualiza el perfil de gdlscene (solo campos de perfil NULL — nunca pisa lo editado a mano) e inserta/actualiza pensionmas.
  - CLI: `python -m src.marcas_seed`

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_marcas_seed.py`:

```python
"""Seeds de marca: gdlscene brandeado + pensión+ completo, idempotente."""
from __future__ import annotations

from src import db, marcas, marcas_seed


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_sembrar_crea_pensionmas_completo(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "pensionmas")
    assert m.fuentes == ["pinterest", "pexels"]
    assert m.formatos == ["libre", "listicle"]
    assert "pensionmas" in m.estilos
    assert m.estilos["pensionmas"]["chrome"]["handle"] == "@pensionmas"
    assert "estimad" in m.voz.lower()          # regla legal presente
    assert m.posting_slots == ["10:00", "18:00"]


def test_sembrar_brandea_gdlscene(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    m = marcas.cargar(cx, "gdlscene")
    assert "gdlscene_clasico" in m.estilos
    assert m.estilos["gdlscene_clasico"]["chrome"]["handle"] == "@gdlscene"
    assert m.fuentes == ["banco", "covers", "pexels"]


def test_sembrar_es_idempotente_y_no_pisa_manual(tmp_path) -> None:
    cx = _cx(tmp_path)
    marcas_seed.sembrar(cx)
    db.update(cx, "accounts", marcas.cargar(cx, "pensionmas").id,
              voz="VOZ EDITADA A MANO")
    marcas_seed.sembrar(cx)
    assert marcas.cargar(cx, "pensionmas").voz == "VOZ EDITADA A MANO"
    assert len([m for m in marcas.listar(cx, solo_activas=False)
                if m.slug == "pensionmas"]) == 1
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_marcas_seed.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.marcas_seed'`

- [ ] **Step 3: Implementar `src/marcas_seed.py`**

```python
"""Seeds de perfil de marca: gdlscene brandeado + Pensión+ (tulanaya).

Idempotente y respetuoso: solo escribe campos de perfil que estén vacíos —
lo editado a mano (GUI) nunca se pisa. CLI: python -m src.marcas_seed
"""
from __future__ import annotations

import json

from src import db

ESTILOS_GDLSCENE = {
    "gdlscene_clasico": {
        "texto": "blanco", "fondo": "verde", "background_opacity": 0.35,
        "chrome": {"handle": "@gdlscene", "logo": None},
        "roles": {
            "hook": {"font": "Anton-Regular", "font_size": "extra_large",
                     "text_style": "background", "text_vertical_anchor": "center"},
            "punto": {"font": "Tinos-Bold", "font_size": "large",
                      "text_style": "background", "text_vertical_anchor": "center"},
            "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                    "text_style": "background", "text_vertical_anchor": "bottom"},
        },
    },
}

ESTILOS_PENSIONMAS = {
    "pensionmas": {
        "texto": "blanco", "fondo": "navy", "background_opacity": 0.3,
        "chrome": {"handle": "@pensionmas", "logo": None},
        "roles": {
            "hook": {"font": "Erode-Bold", "font_size": "extra_large",
                     "text_style": "background", "text_vertical_anchor": "center"},
            "punto": {"font": "Erode-Semibold", "font_size": "large",
                      "text_style": "background", "text_vertical_anchor": "center"},
            "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                    "text_style": "background", "text_vertical_anchor": "bottom"},
        },
    },
}

VOZ_PENSIONMAS = (
    "Marca: Pensión+ (pensionmas.com.mx) — asesoría y acompañamiento para el "
    "retiro parcial por desempleo de AFORE, cambios y mejora de afore. "
    "Audiencia: personas en México de 40 a 60 años, de ciudad, sin empleo, que "
    "necesitan liquidez; no son expertos financieros y desconfían de gestores. "
    "TONO: confiable, claro, cercano — un asesor serio que habla de frente. "
    "Español mexicano llano ('tu dinero', 'tu trámite'), SIN urgencia "
    "artificial, SIN letras chiquitas. "
    "REGLAS LEGALES OBLIGATORIAS: los montos SIEMPRE se llaman 'estimados'; "
    "NUNCA prometer resultados ni cantidades; el trámite ante la AFORE es "
    "personal y gratuito (nosotros asesoramos y acompañamos); honorarios "
    "visibles, nunca cobros por adelantado. Nada de 'dinero YA', contadores "
    "ni presión. "
    "IMÁGENES: personas reales de 40-60 años de ciudad mexicana, situaciones "
    "cotidianas (hogar, celular, papeles), luz cálida; NUNCA stock corporativo "
    "gringo ni oficinas genéricas."
)

# (campo de accounts, valor a sembrar) — solo se escribe si el campo está vacío.
_PERFIL_PENSIONMAS = {
    "voz": VOZ_PENSIONMAS,
    "fuentes_imagen": json.dumps(["pinterest", "pexels"]),
    "formatos": json.dumps(["libre", "listicle"]),
    "estilos_json": json.dumps(ESTILOS_PENSIONMAS, ensure_ascii=False),
    "posting_slots": "10:00,18:00",
}

_PERFIL_GDLSCENE = {
    "fuentes_imagen": json.dumps(["banco", "covers", "pexels"]),
    "estilos_json": json.dumps(ESTILOS_GDLSCENE, ensure_ascii=False),
}


def _completar(cx, account_id: int, perfil: dict) -> None:
    fila = db.get(cx, "accounts", account_id)
    faltantes = {k: v for k, v in perfil.items() if not (fila.get(k) or "").strip()}
    if faltantes:
        db.update(cx, "accounts", account_id, **faltantes)


def sembrar(cx) -> None:
    filas = db.rows(cx, "SELECT id, slug FROM accounts")
    por_slug = {f["slug"]: f["id"] for f in filas}
    if "gdlscene" in por_slug:
        _completar(cx, por_slug["gdlscene"], _PERFIL_GDLSCENE)
    if "pensionmas" not in por_slug:
        por_slug["pensionmas"] = db.insert(
            cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
            nombre="Pensión+", ciudad="CDMX", color_marca="#2F52D9", activa=1)
    _completar(cx, por_slug["pensionmas"], _PERFIL_PENSIONMAS)
    print("Seeds de marca aplicados (gdlscene + pensionmas).")


if __name__ == "__main__":
    cx = db.connect()
    try:
        db.init_db(cx)
        sembrar(cx)
    finally:
        cx.close()
```

Nota: `ig_handle="@pensionmas"` es placeholder — Ricardo pone el handle real
desde la GUI (Task 9) o al hacer el onboarding (Task 10).

- [ ] **Step 4: Correr tests y ruff**

Run: `python -m pytest tests/test_marcas_seed.py -v && ruff check src/marcas_seed.py tests/test_marcas_seed.py`
Expected: 3 PASS, ruff limpio

- [ ] **Step 5: Commit**

```bash
git add src/marcas_seed.py tests/test_marcas_seed.py
git commit -m "feat(marcas): seeds de perfil gdlscene y pension+ (estilos, voz con compliance)"
```

---

### Task 8: `generate_slideshow --marca`

**Files:**
- Modify: `src/generate_slideshow.py`
- Test: `tests/test_generate_slideshow.py` (ampliar)

**Interfaces:**
- Consumes: `marcas.cargar/estilos_de` (Task 1), `compilar(estilos=)` (Task 6), `approval.enviar_a_telegram(account_slug=)` (Task 3).
- Produces:
  - `generar(cx, tema, *, marca="gdlscene", formato=None, estilo=None, fuentes=None, n_slides=6, aspect="4:5", contexto=None, dry_run=False) -> int | None`
  - Defaults por marca: `formato=None` → primer formato del perfil; `estilo=None` → primer preset propio de la marca (o "tiktok_bold" si no tiene); `fuentes=None` → las del perfil. `ValueError` si el formato pedido no está habilitado o el estilo no existe en el catálogo fusionado.
  - La `voz` de la marca se antepone al `contexto` (separados por línea en blanco).
  - Encola con `account_id=marca.id` y envía con `account_slug=marca.slug`; `compilar(..., account_slug=marca.slug, estilos=fusionados)`.
  - CLI: gana `--marca` (default `gdlscene`); `--formato` y `--estilo` pierden `choices` estáticos (la validación es por marca, dentro de `generar`).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_generate_slideshow.py` (reusa `_preparar` y `_guion`
existentes; `_preparar` debe además monkeypatchear
`gs.approval.enviar_a_telegram` capturando kwargs — ajustar el helper para
guardar `(cap, url, qid, kwargs)`):

```python
import json as json_mod

from src import db as db_mod


def _alta_marca(cx):
    return db_mod.insert(
        cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
        nombre="Pensión+", ciudad="CDMX",
        voz="REGLAS: montos estimados.",
        fuentes_imagen=json_mod.dumps(["pinterest", "pexels"]),
        formatos=json_mod.dumps(["libre"]),
        estilos_json=json_mod.dumps({"pensionmas": {
            "texto": "blanco", "fondo": "navy", "background_opacity": 0.3,
            "chrome": {"handle": "@pensionmas", "logo": None},
            "roles": {"hook": {"font": "Erode-Bold", "font_size": "extra_large",
                               "text_style": "background",
                               "text_vertical_anchor": "center"},
                      "punto": {"font": "Erode-Semibold", "font_size": "large",
                                "text_style": "background",
                                "text_vertical_anchor": "center"},
                      "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                              "text_style": "background",
                              "text_vertical_anchor": "bottom"}}}}))


def test_generar_con_marca_usa_su_perfil(monkeypatch, tmp_path) -> None:
    cx, subidas, enviados = _preparar(monkeypatch, tmp_path)
    mid = _alta_marca(cx)
    capturado = {}

    def _guion_spy(tema, **kw):
        capturado.update(kw)
        return _guion()

    monkeypatch.setattr(gs.slideshow_script, "generar_guion", _guion_spy)
    fuentes_vistas = {}
    monkeypatch.setattr(gs.image_sources, "resolver",
                        lambda hints, fuentes, **kw:
                        fuentes_vistas.setdefault("f", fuentes)
                        or [None] * len(hints))
    qid = gs.generar(cx, "afore", marca="pensionmas")
    fila = db_mod.get(cx, "content_queue", qid)
    assert fila["account_id"] == mid
    assert capturado["formato"] == "libre"                 # default del perfil
    assert "montos estimados" in capturado["contexto"]     # voz inyectada
    assert fuentes_vistas["f"] == ["pinterest", "pexels"]
    assert enviados[-1][3].get("account_slug") == "pensionmas"
    contrato = json_mod.loads(fila["slideshow_json"])
    assert contrato["brief"]["fondo"] == "navy"            # estilo de marca


def test_generar_formato_no_habilitado(monkeypatch, tmp_path) -> None:
    cx, _, _ = _preparar(monkeypatch, tmp_path)
    _alta_marca(cx)
    import pytest
    with pytest.raises(ValueError, match="formato"):
        gs.generar(cx, "afore", marca="pensionmas", formato="perfil")


def test_generar_sin_marca_sigue_siendo_gdlscene(monkeypatch, tmp_path) -> None:
    cx, _, enviados = _preparar(monkeypatch, tmp_path)
    qid = gs.generar(cx, "café")
    assert db_mod.get(cx, "content_queue", qid)["account_id"] == 1
    assert enviados[-1][3].get("account_slug", "gdlscene") == "gdlscene"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_generate_slideshow.py -v`
Expected: FAIL — `generar` no acepta `marca`

- [ ] **Step 3: Implementar**

`src/generate_slideshow.py` — `generar` reescrito al frente (resto igual):

```python
def generar(cx, tema: str, *, marca: str = "gdlscene", formato: str | None = None,
            estilo: str | None = None, fuentes: tuple[str, ...] | None = None,
            n_slides: int = 6, aspect: str = "4:5", contexto: str | None = None,
            dry_run: bool = False) -> int | None:
    """Genera el set con el PERFIL de la marca; queue_id o None en dry-run."""
    from src import marcas as marcas_mod
    m = marcas_mod.cargar(cx, marca)
    formato = formato or (m.formatos[0] if m.formatos else "listicle")
    if formato not in m.formatos:
        raise ValueError(f"La marca {m.slug} no tiene habilitado el formato "
                         f"{formato!r} (permitidos: {m.formatos})")
    catalogo = marcas_mod.estilos_de(m)
    estilo = estilo or (next(iter(m.estilos)) if m.estilos else "tiktok_bold")
    if estilo not in catalogo:
        raise ValueError(f"Estilo {estilo!r} no existe para {m.slug} "
                         f"(disponibles: {sorted(catalogo)})")
    fuentes = tuple(fuentes) if fuentes else tuple(m.fuentes)
    contexto_full = "\n\n".join(x for x in (m.voz, contexto) if x) or None

    guion = slideshow_script.generar_guion(tema, formato=formato,
                                           n_slides=n_slides,
                                           contexto=contexto_full)
    hints = [sl["image_hint"] for sl in guion["slides"]]
    imagenes = image_sources.resolver(hints, list(fuentes), cx=cx)
    sin_imagen = sum(1 for i in imagenes if i is None)
    if sin_imagen:
        print(f"[slideshow] {sin_imagen}/{len(imagenes)} slides sin imagen "
              "(fondo sólido)")
    brief = {"tema": tema, "formato": formato, "estilo": estilo,
             "fuentes": list(fuentes), "n_slides": n_slides,
             "contexto": contexto, "aspect": aspect, "marca": m.slug}
    show = slideshow_compile.compilar(guion, estilo=estilo, imagenes=imagenes,
                                      aspect_ratio=aspect, brief=brief,
                                      formato=formato, account_slug=m.slug,
                                      estilos=catalogo)
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
        tema_semilla=f"slideshow {formato}: {tema}", account_id=m.id)
    db.update(cx, "content_queue", qid,
              slideshow_json=slideshow_model.a_json(show))
    approval.enviar_a_telegram(show.caption, json.dumps(urls), qid,
                               account_slug=m.slug)
    print(f"[slideshow] q{qid} ({m.slug}) enviado a Telegram ({len(urls)} slides)")
    return qid
```

CLI en `main()`: agregar `ap.add_argument("--marca", default="gdlscene")`;
`--formato` y `--estilo` cambian a `default=None` SIN `choices`; `--fuentes`
cambia a `default=None` (None → perfil de la marca; si viene string, se parsea
igual que hoy). Pasar `marca=args.marca` a `generar`.

- [ ] **Step 4: Correr tests y ruff**

Run: `python -m pytest tests/test_generate_slideshow.py -v && ruff check src/generate_slideshow.py tests/test_generate_slideshow.py`
Expected: PASS todo (los 3 tests viejos + 3 nuevos)

- [ ] **Step 5: Commit**

```bash
git add src/generate_slideshow.py tests/test_generate_slideshow.py
git commit -m "feat(marcas): generate_slideshow --marca carga perfil, voz y estilos de la marca"
```

---

### Task 9: GUI `/marcas` + selector de marca en `/slideshows`

**Files:**
- Create: `web/templates/marcas.html`
- Modify: `web/app.py` (rutas `GET /marcas`, `POST /marcas/guardar`; ruta `/slideshows` gana lista de marcas; `POST /slideshows/generar` gana campo `marca`)
- Modify: `web/templates/slideshows.html` (select de marca)
- Modify: `web/templates/base.html` (link "Marcas")
- Test: `tests/test_marcas_web.py`

**Interfaces:**
- Consumes: `marcas.listar/cargar/creds_faltantes` (Task 1), `db.insert/update`, `_lanzar_sesion`.
- Produces:
  - `GET /marcas`: tabla de marcas (nombre, slug, handle, activa) + por marca el checklist de vars de `.env` faltantes (`creds_faltantes`) + form de alta/edición.
  - `POST /marcas/guardar`: upsert por slug de los campos de PERFIL (nombre, ig_handle, color_marca, voz, fuentes_imagen CSV→JSON, formatos CSV→JSON, posting_slots, estilos_json validado con `json.loads` — error legible si inválido, logo_path, activa). NUNCA campos de secretos.
  - `POST /slideshows/generar` acepta `marca` (default `gdlscene`) y lo pasa como `--marca` al CLI.

- [ ] **Step 1: Escribir los tests que fallan**

`tests/test_marcas_web.py`:

```python
"""GUI /marcas: listado con checklist de creds y upsert de perfil sin secretos."""
from __future__ import annotations

from fastapi.testclient import TestClient

from web import app as web_app


def test_get_marcas_lista_y_checklist(monkeypatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    client = TestClient(web_app.app)
    r = client.get("/marcas")
    assert r.status_code == 200
    assert "gdlscene" in r.text


def test_post_guardar_upsert_y_json_invalido(monkeypatch) -> None:
    client = TestClient(web_app.app)
    r = client.post("/marcas/guardar", data={
        "slug": "prueba_web", "nombre": "Prueba", "ig_handle": "@prueba",
        "voz": "tono x", "fuentes_imagen": "pexels,pinterest",
        "formatos": "libre", "posting_slots": "09:00",
        "estilos_json": "", "color_marca": "#123456", "activa": "1",
    })
    assert r.status_code == 200
    r2 = client.get("/marcas")
    assert "prueba_web" in r2.text
    # JSON de estilos inválido → error legible, sin stacktrace
    r3 = client.post("/marcas/guardar", data={
        "slug": "prueba_web", "nombre": "Prueba", "ig_handle": "@prueba",
        "voz": "", "fuentes_imagen": "", "formatos": "",
        "posting_slots": "", "estilos_json": "{no json", "color_marca": "",
        "activa": "1",
    })
    assert r3.status_code == 200
    assert "estilos_json" in r3.text and "inválido" in r3.text.lower()


def test_slideshows_generar_pasa_marca(monkeypatch) -> None:
    lanzados = []
    monkeypatch.setattr(web_app, "_lanzar_sesion",
                        lambda mod, *args: lanzados.append((mod, args)) or None)
    client = TestClient(web_app.app)
    r = client.post("/slideshows/generar", data={
        "tema": "afore", "marca": "pensionmas", "formato": "libre",
        "estilo": "", "fuentes": "", "n_slides": "5",
    })
    assert r.status_code == 200
    _, args = lanzados[0]
    assert "--marca" in args and "pensionmas" in args
```

OJO: estos tests pegan a la DB real del checkout vía `web.app` (patrón de los
tests web existentes) — el upsert usa el slug `prueba_web` para no ensuciar
marcas reales; el POST re-ejecutado es idempotente.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_marcas_web.py -v`
Expected: FAIL — GET /marcas devuelve 404

- [ ] **Step 3: Implementar**

En `web/app.py` (siguiendo el patrón de rutas existente; `marcas` importado
junto a los demás módulos de src):

```python
@app.get("/marcas", response_class=HTMLResponse)
def marcas_vista(request: Request) -> HTMLResponse:
    """Marcas registradas + checklist de credenciales de .env por marca."""
    from src import marcas as marcas_mod
    cx = db.connect()
    try:
        db.init_db(cx)
        lista = marcas_mod.listar(cx, solo_activas=False)
    finally:
        cx.close()
    filas = [{"m": m, "faltan": marcas_mod.creds_faltantes(m.slug)}
             for m in lista]
    return templates.TemplateResponse(request, "marcas.html", {
        "filas": filas, "mensaje": request.query_params.get("msg", ""),
    })


@app.post("/marcas/guardar", response_class=HTMLResponse)
def marcas_guardar(slug: str = Form(...), nombre: str = Form(""),
                   ig_handle: str = Form(""), color_marca: str = Form(""),
                   voz: str = Form(""), fuentes_imagen: str = Form(""),
                   formatos: str = Form(""), posting_slots: str = Form(""),
                   estilos_json: str = Form(""), logo_path: str = Form(""),
                   activa: str = Form("1")) -> HTMLResponse:
    """Upsert del PERFIL de la marca. Los secretos van en .env, nunca aquí."""
    import json as json_mod
    slug = slug.strip().lower()
    if estilos_json.strip():
        try:
            json_mod.loads(estilos_json)
        except ValueError as e:
            return HTMLResponse(f"⚠️ estilos_json inválido: {e}")
    campos = {
        "nombre": nombre.strip() or slug,
        "ig_handle": ig_handle.strip(),
        "color_marca": color_marca.strip() or "#1b5e3f",
        "voz": voz.strip(),
        "fuentes_imagen": json_mod.dumps(
            [f.strip() for f in fuentes_imagen.split(",") if f.strip()])
            if fuentes_imagen.strip() else None,
        "formatos": json_mod.dumps(
            [f.strip() for f in formatos.split(",") if f.strip()])
            if formatos.strip() else None,
        "posting_slots": posting_slots.strip() or None,
        "estilos_json": estilos_json.strip() or None,
        "logo_path": logo_path.strip() or None,
        "activa": 1 if activa == "1" else 0,
    }
    cx = db.connect()
    try:
        db.init_db(cx)
        fila = db.rows(cx, "SELECT id FROM accounts WHERE slug = ?", (slug,))
        if fila:
            db.update(cx, "accounts", fila[0]["id"], **campos)
        else:
            db.insert(cx, "accounts", slug=slug, ciudad="", **campos)
    finally:
        cx.close()
    return HTMLResponse(f"✅ Marca {slug} guardada. "
                        '<a href="/marcas">volver</a>')
```

`web/templates/marcas.html` (extiende `base.html` con el bloque real del
repo, patrón de `slideshows.html`): tabla con nombre/slug/handle/activa +
lista `faltan` por marca (o "✅ credenciales completas"), y un form con los
campos del POST (voz y estilos_json como `<textarea>`; nota junto al form:
"Los tokens van en .env con sufijo __SLUG — esta pantalla nunca los guarda").
Botón por fila "editar" que rellena el form (values pre-cargados server-side
vía `?slug=` opcional o edición manual — mantenerlo simple, sin JS extra).

`/slideshows` (GET): agregar `marcas_activas` al contexto (lista de slugs vía
`marcas_mod.listar`) y en `slideshows.html` un `<select name="marca">` con
ellas. `POST /slideshows/generar`: agregar `marca: str = Form("gdlscene")` y
`args += ["--marca", marca]`; los campos `formato`/`estilo`/`fuentes` vacíos
ya NO se mandan como flags (solo si vienen no-vacíos) — así los defaults del
perfil aplican.

Link "Marcas" en la navegación de `base.html`.

- [ ] **Step 4: Correr tests y ruff**

Run: `python -m pytest tests/test_marcas_web.py tests/test_slideshows_web.py -v && ruff check web tests/test_marcas_web.py`
Expected: PASS todo (ajustar `test_slideshows_web.py` si el form cambió campos obligatorios)

- [ ] **Step 5: Commit y recordatorio**

```bash
git add web/app.py web/templates/marcas.html web/templates/slideshows.html web/templates/base.html tests/test_marcas_web.py tests/test_slideshows_web.py
git commit -m "feat(marcas): GUI /marcas con checklist de creds + selector de marca en /slideshows"
```

Recordar: reiniciar uvicorn para ver las rutas nuevas.

---

### Task 10: Onboarding E2E de Pensión+ (manual, con Ricardo)

**Files:** ninguno nuevo (solo fixes que salgan).

Pasos en orden; los marcados 🧑 requieren a Ricardo:

- [ ] **Step 1: Sembrar perfiles y verificar**

```bash
.venv/bin/python -m src.marcas_seed
.venv/bin/python -c "from src import db, marcas; cx=db.connect(); print([m.slug for m in marcas.listar(cx)])"
```
Expected: `['gdlscene', 'pensionmas']`

- [ ] **Step 2: 🧑 Credenciales de pensión+ en `.env`**

Ricardo: crear el bot en BotFather (`/newbot`) y agregar a `.env`:
`TELEGRAM_BOT_TOKEN__PENSIONMAS`, `TELEGRAM_CHAT_ID__PENSIONMAS` (su mismo
chat id sirve), `IG_USER_ID__PENSIONMAS`, `IG_ACCESS_TOKEN__PENSIONMAS`
(token del IG de pensión+, mismo trámite que gdlscene), y
`SHEET_ID__PENSIONMAS` (Sheet nuevo con los encabezados:
`.venv/bin/python -c "from src import sheets; sheets.ensure_headers(sheet_id='<ID>')"`).
También corregir `ig_handle` real de pensión+ en `/marcas` si no es
`@pensionmas`.

- [ ] **Step 3: Reiniciar daemon y verificar multi-bot**

```bash
launchctl kickstart -k gui/$(id -u)/com.gdlscene.approval-daemon
tail -5 <log del daemon>   # debe listar: 2 marca(s) — gdlscene, pensionmas
```
(Con solo el bot de gdlscene configurado, el daemon debe seguir operando
igual que siempre — verificarlo ANTES de poner las vars de pensión+.)

- [ ] **Step 4: Dry-run brandeado**

```bash
.venv/bin/python -m src.generate_slideshow --marca pensionmas --tema "3 cosas que nadie te dice del retiro por desempleo de tu afore" --dry-run
open out/slide*.png
```
Expected: slides navy/cobalto con Erode, pie "@pensionmas", copy con "estimado"
y sin promesas. Iterar preset/voz si el tono no convence.

- [ ] **Step 5: 🧑 Set real → aprobar en el bot de pensión+**

Sin `--dry-run`. El set llega SOLO al bot de pensión+; aprobar → fila en el
Sheet de pensión+ con slot de SU malla (10:00/18:00). Verificar que el bot de
gdlscene NO recibió nada.

- [ ] **Step 6: Publicación en el IG de pensión+**

`.venv/bin/python publish.py` local tras vencer el slot (o ajustar el slot a
mano en su Sheet para probar): debe publicar el carrusel en el IG de pensión+
con las creds del sufijo. Verificar el post publicado.

- [ ] **Step 7: 🧑 Secrets del worker (opcional en este paso)**

`gh secret set` de las vars `__PENSIONMAS` (IG + SHEET) para que el cron de
Actions también publique pensión+; mientras, la publicación local cubre.

- [ ] **Step 8: Commit de fixes + push**

```bash
git push
```

---

## Self-review del plan (hecho al escribirlo)

- **Cobertura del spec:** entidad marca (T1), sheets/scheduler por marca (T2), aprobación por marca con errores accionables (T3), publicación multi-cuenta con marcas desde ENV — restricción del worker sin SQLite (T4), daemon multi-bot un-proceso (T5), chrome/paleta/fuentes y contrato autocontenido (T6), seeds gdlscene+pensionmas con voz de compliance (T7), generación con perfil (T8), GUI /marcas + selector (T9), onboarding E2E (T10). Tests de no-herencia de creds: T1 y T3.
- **Placeholders:** ninguno; todo paso de código trae el código.
- **Consistencia de firmas:** `next_free_slot(now, *, sheet_id, slots)` igual en T2/T3; `_slot_meme(ahora, sheet_id, slots)` T3; `compilar(..., estilos=)` igual en T6/T8; `enviar_a_telegram(..., account_slug=)` igual en T3/T8; `creds={"user_id","token"}` igual en T4; `Marca` (T1) consumida en T3/T5/T8/T9.
- **Nota para el ejecutor:** los tests existentes que fijaban firmas viejas (`test_approval.py` `_slot_meme`, `test_slideshows_web.py` form) se actualizan en la task que cambia el contrato — está anotado en sus steps.
