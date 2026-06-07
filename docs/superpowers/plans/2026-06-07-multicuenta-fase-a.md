# Multi-cuenta Fase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dimensión "cuenta" en el schema (tabla `accounts` + `account_id` en bands/content_queue/ig_posts, default gdlscene) + helpers de creds por cuenta. Cero cambio de comportamiento.

**Architecture:** Spec: `docs/superpowers/specs/2026-06-07-multicuenta-schema-design.md`. Se monta en el patrón existente: `schema.sql` (CREATE IF NOT EXISTS, append) + `db._MIGRATIONS` (ALTER idempotente) + seed/índices en `init_db`. Creds por env con sufijo `__SLUG`, fallback sin sufijo para gdlscene.

**Tech Stack:** Python, SQLite, pytest. `.venv/bin/python`.

**⚠️ Reglas de sesión:** NO `git commit`/`git add` (otros agentes mergean a master; Ricardo decide commits). NO tocar `web/` ni `src/planner.py`. Cambios a `db.py`/`schema.sql` SOLO aditivos en los puntos indicados. Comentarios en español.

---

### Task A1: Tabla accounts + migraciones + seed + índices

**Files:**
- Modify: `src/schema.sql` (append al final, antes de los triggers o después — bloque nuevo completo)
- Modify: `src/db.py` (`_MIGRATIONS`, `init_db`, `TABLES`)
- Test: `tests/test_multicuenta.py` (nuevo)

- [ ] **Step 1: Test failing primero**

`tests/test_multicuenta.py`:

```python
"""Fase A multi-cuenta: tabla accounts, seed gdlscene, FKs con default 1."""
from __future__ import annotations

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_seed_gdlscene_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # segunda corrida: no duplica
    cuentas = db.rows(cx, "SELECT * FROM accounts")
    assert len(cuentas) == 1
    assert cuentas[0]["id"] == 1 and cuentas[0]["slug"] == "gdlscene"
    assert cuentas[0]["ciudad"] == "Guadalajara"


def test_bands_caen_en_gdlscene(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    fila = db.rows(cx, "SELECT account_id FROM bands WHERE id = ?", (bid,))[0]
    assert fila["account_id"] == 1


def test_queue_e_igposts_tienen_account_id(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="meme")
    assert db.rows(cx, "SELECT account_id FROM content_queue WHERE id=?", (qid,))[0]["account_id"] == 1
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(ig_posts)")}
    assert "account_id" in cols


def test_helpers_accounts(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "accounts", slug="cdmxscene", ig_handle="cdmxscene",
              nombre="La Escena CDMX", ciudad="CDMX", activa=0)
    assert [a["slug"] for a in db.list_accounts(cx)] == ["gdlscene"]
    assert [a["slug"] for a in db.list_accounts(cx, solo_activas=False)] == ["gdlscene", "cdmxscene"]
    assert db.get_account(cx, "cdmxscene")["nombre"] == "La Escena CDMX"
    assert db.get_account(cx, "noexiste") is None
```

- [ ] **Step 2: Correr y ver que falla**

Run: `.venv/bin/python -m pytest tests/test_multicuenta.py -v`
Expected: FAIL (`no such table: accounts` / AttributeError list_accounts)

- [ ] **Step 3: schema.sql — append del bloque accounts**

Al FINAL de `src/schema.sql` (después del último trigger), agregar:

```sql
-- -----------------------------------------------------------------------------
-- accounts — cuentas de escena (@gdlscene, @cdmxscene, @mtyscene). Multi-cuenta
-- Fase A: bands/content_queue/ig_posts cargan account_id (DEFAULT 1 = gdlscene);
-- photos/events/members heredan la cuenta vía band_id. Las CREDENCIALES nunca
-- viven aquí: van en env con sufijo (IG_ACCESS_TOKEN__CDMXSCENE...), ver config.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    slug         TEXT NOT NULL UNIQUE,
    ig_handle    TEXT NOT NULL,
    nombre       TEXT NOT NULL,
    ciudad       TEXT NOT NULL,
    timezone     TEXT NOT NULL DEFAULT 'America/Mexico_City',
    voz_extra    TEXT,                                    -- textura local del caption
    color_marca  TEXT NOT NULL DEFAULT '#1b5e3f',
    activa       INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (activa IN (0,1))
);

CREATE TRIGGER IF NOT EXISTS trg_accounts_updated
    AFTER UPDATE ON accounts FOR EACH ROW
    BEGIN UPDATE accounts SET updated_at = datetime('now') WHERE id = OLD.id; END;
```

- [ ] **Step 4: db.py — migraciones, seed, índices, whitelist, helpers**

(a) En `_MIGRATIONS`, agregar la columna a las tres tablas (clave nueva por tabla; bands/events/content_queue ya existen en el dict — agregar la entrada; para `ig_posts` crear la sub-dict si no existe):

```python
        # Multi-cuenta Fase A: todo lo existente cae a la cuenta 1 (gdlscene).
        # SIN cláusula REFERENCES: SQLite prohíbe ADD COLUMN con FK y default
        # no-NULL bajo foreign_keys=ON; la integridad la cuida la app (igual
        # que el resto de columnas migradas). FK dura llegará con Postgres.
        "account_id": "INTEGER NOT NULL DEFAULT 1",
```
en `"bands"`, `"content_queue"` y `"ig_posts"`.

(b) En `init_db`, DESPUÉS del loop de migraciones y antes del backfill existente, agregar:

```python
    # Multi-cuenta Fase A: seed de la cuenta original e índices post-migración
    # (los índices van aquí y no en schema.sql: en DBs viejas la columna
    # account_id no existe todavía cuando corre executescript).
    cx.execute("""INSERT OR IGNORE INTO accounts (id, slug, ig_handle, nombre, ciudad)
                  VALUES (1, 'gdlscene', 'gdlscene', 'La Escena GDL', 'Guadalajara')""")
    for idx in ("CREATE INDEX IF NOT EXISTS idx_bands_account ON bands(account_id)",
                "CREATE INDEX IF NOT EXISTS idx_queue_account ON content_queue(account_id)",
                "CREATE INDEX IF NOT EXISTS idx_igposts_account ON ig_posts(account_id)"):
        cx.execute(idx)
```

(c) Agregar `"accounts"` a la whitelist `TABLES` (buscar la constante; es un dict/set de tablas permitidas para el CRUD — seguir su formato exacto). Si `TABLES` enumera columnas permitidas por tabla, incluir también `account_id` en las de `bands`, `content_queue` e `ig_posts` (Fase B lo va a escribir).

(d) Helpers, junto a los demás helpers de consulta de db.py:

```python
def list_accounts(cx: sqlite3.Connection, solo_activas: bool = True) -> list[dict[str, Any]]:
    """Cuentas de escena, en orden de id (gdlscene primero)."""
    q = "SELECT * FROM accounts"
    if solo_activas:
        q += " WHERE activa = 1"
    return rows(cx, q + " ORDER BY id")


def get_account(cx: sqlite3.Connection, slug: str) -> dict[str, Any] | None:
    """Cuenta por slug, o None si no existe."""
    r = rows(cx, "SELECT * FROM accounts WHERE slug = ?", (slug,))
    return r[0] if r else None
```

- [ ] **Step 5: Tests pasan + suite completa**

Run: `.venv/bin/python -m pytest tests/test_multicuenta.py -v` → 4 PASS
Run: `.venv/bin/python -m pytest tests/ -q` → sin fallas nuevas

---

### Task A2: `config.account_creds(slug)` — creds por env con fallback

**Files:**
- Modify: `config.py` (función nueva al final, junto a los `resolve_*`)
- Modify: `.env.example` (documentar el patrón de sufijos)
- Test: `tests/test_multicuenta.py` (ampliar)

- [ ] **Step 1: Test failing**

Agregar a `tests/test_multicuenta.py`:

```python
def test_account_creds_fallback_y_sufijo(monkeypatch) -> None:
    import config
    monkeypatch.setenv("IG_USER_ID", "base-user")
    monkeypatch.setenv("IG_ACCESS_TOKEN", "base-token")
    monkeypatch.setenv("IG_ACCESS_TOKEN__CDMXSCENE", "cdmx-token")
    # gdlscene sin sufijo → cae a las vars base (compat con el .env actual)
    g = config.account_creds("gdlscene")
    assert g["IG_USER_ID"] == "base-user" and g["IG_ACCESS_TOKEN"] == "base-token"
    # otra cuenta: SOLO sufijo; lo que falte queda None (nunca hereda la base)
    c = config.account_creds("cdmxscene")
    assert c["IG_ACCESS_TOKEN"] == "cdmx-token"
    assert c["IG_USER_ID"] is None
```

- [ ] **Step 2: Ver que falla** → AttributeError.

- [ ] **Step 3: Implementar en `config.py`** (al final, después de los `resolve_*`):

```python
# Claves de credenciales que existen POR CUENTA de escena (multi-cuenta Fase A).
_ACCOUNT_CRED_KEYS = ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_SCRAPER_SESSIONID",
                      "IG_SCRAPER_UA", "SHEET_ID")


def account_creds(slug: str) -> dict[str, str | None]:
    """Credenciales de una cuenta: env con sufijo __SLUG (en mayúsculas).

    gdlscene (la cuenta original) cae a las vars SIN sufijo para no tocar el
    .env ni los secrets actuales. Las demás cuentas usan SOLO su sufijo: que
    una cuenta nueva jamás herede por accidente los tokens de gdlscene.
    """
    sufijo = f"__{slug.upper()}"
    out: dict[str, str | None] = {}
    for k in _ACCOUNT_CRED_KEYS:
        val = os.getenv(k + sufijo)
        if val is None and slug == "gdlscene":
            val = os.getenv(k)
        out[k] = val
    return out
```

- [ ] **Step 4: `.env.example`** — agregar al final:

```
# ---------- Multi-cuenta (Fase A) ----------
# Credenciales por cuenta de escena: misma clave + __SLUG en mayúsculas.
# gdlscene usa las variables base de arriba (sin sufijo).
# IG_USER_ID__CDMXSCENE=
# IG_ACCESS_TOKEN__CDMXSCENE=
# IG_USER_ID__MTYSCENE=
# IG_ACCESS_TOKEN__MTYSCENE=
```

- [ ] **Step 5: Tests + suite** → todo PASS.

---

### Task A3: Migrar la DB viva + verificación (inline, la hace el controlador)

- [ ] Corre `init_db` contra `data/gdlscene.db` (cualquier flujo lo hace, pero explícito: `.venv/bin/python -c "from src import db; cx = db.connect(); db.init_db(cx); cx.close()"`)
- [ ] Verificar: `accounts` tiene gdlscene id=1; `SELECT count(*) FROM bands WHERE account_id != 1` = 0; ídem content_queue/ig_posts.
- [ ] Suite completa verde.
- [ ] Smoke de GUI: `TestClient(app).get("/calendario")` y `/bandas` → 200 (nada se rompió).
- [ ] Entregar resumen a Ricardo (sin commit).
