# Portal de colaboradores — Fase 1: auth, usuarios, secretos en DB y esqueleto `api/`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que instagod tenga una API JSON con login por magic link, usuarios con roles por marca, y secretos por marca guardados cifrados en SQLite (con `config.account_creds` leyéndolos primero de DB), lista para que las fases siguientes cuelguen cola, jobs, fuentes y el front.

**Architecture:** Paquete nuevo `api/` (FastAPI, JSON) con routers delgados; la lógica en `src/users.py` y `src/secrets_store.py`. `config.account_creds(slug)` resuelve **DB → env con sufijo → env global (solo gdlscene)** sin cambiar de firma, así `approval`, `publish`, `approval_daemon` funcionan sin tocarlos. El daemon detecta cambios de secretos cada 60 s y recarga sus bots. La GUI HTMX (`web/`) no se toca: se protegerá vía `GET /auth/verify` (forward_auth de Caddy, Fase 5).

**Tech Stack:** Python 3.12+, FastAPI 0.136 / Pydantic v2, SQLite (`src/db.py`), `cryptography` (Fernet), `httpx` (Resend + TestClient), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-17-portal-colaboradores-design.md` (§1-§3, §8-§9). **Ajuste al spec (§1):** en vez de montar `web/` en `/legacy` dentro de la API (sus 76 rutas y plantillas usan paths absolutos), la GUI legacy se sirve como servicio aparte detrás de Caddy con `forward_auth` contra `GET /auth/verify` (200 solo con sesión admin). Esta fase entrega `/auth/verify`; el cableado de Caddy va en la Fase 5.

## Global Constraints

- Español en mensajes, docstrings, nombres de campos JSON y errores (regla del repo).
- Commits **sin firma de Claude**, identidad `richyhoopd <theilluminatiduck@gmail.com>` (verificar `git config user.email`). Mensajes estilo `feat(api): ...`, `feat(secretos): ...`.
- **Otra sesión de Claude trabaja en paralelo** en `config.py` (constantes de paleta/fuentes), `src/slideshow_compile.py`, `src/image_sources.py`, `src/marcas_seed.py`, `publish.yml`, `src/ig_token.py`. En este plan **solo** se toca de `config.py` la función `account_creds`, `_ACCOUNT_CRED_KEYS` y un bloque nuevo de constantes al final. Antes de cada commit: `git pull --rebase`. No tocar los otros archivos listados.
- Secretos: la API **nunca** devuelve el valor de un secreto; solo `configurada`, `ultimos4`, `updated_at`. Ningún log imprime valores.
- Cero llamadas reales a Telegram/IG/LLM/Resend en tests.
- Tests aislan la DB con `monkeypatch.setenv("DB_PATH", tmp)` + `importlib.reload(config)` (patrón de `tests/test_venues_web.py`) y `config.INSTAGOD_MASTER_KEY` se anula por default en un `conftest.py` autouse (Task 2) para que ningún test lea secretos de la DB real.
- Errores JSON uniformes: `{"error": "<codigo>", "detalle": "<texto>", "campo": "<opcional>"}`.
- ruff limpio (`ruff check .`), suite completa verde (`pytest -q`) antes de cada commit.

---

## Mapa de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/schema.sql` (modificar, al final) | DDL de `users`, `brand_members`, `magic_links`, `sessions`, `brand_secrets` |
| `src/db.py` (modificar `TABLES`) | whitelist de columnas de las tablas nuevas |
| `src/secrets_store.py` (crear) | cifrado Fernet, CRUD de `brand_secrets`, metadatos, `creds_de_slug`, `version_marcas` |
| `config.py` (modificar `account_creds`, `_ACCOUNT_CRED_KEYS`, + bloque `Portal`) | precedencia DB → env; constantes `INSTAGOD_MASTER_KEY`, `APP_URL`, `RESEND_API_KEY`, `MAIL_FROM`, `SESSION_DAYS`, `ENV`, `COOKIE_DOMAIN` |
| `src/users.py` (crear) | usuarios, membresías/roles, magic links, sesiones |
| `api/__init__.py`, `api/app.py` (crear) | factory `create_app()`, handlers de error, startup `init_db`, routers |
| `api/errors.py` (crear) | `ApiError` + helpers |
| `api/deps.py` (crear) | `get_cx`, `usuario_actual`, `requiere_admin`, `marca_para` |
| `api/ratelimit.py` (crear) | `Limitador` en memoria |
| `api/mail.py` (crear) | `enviar_magic_link` (Resend vía httpx; en dev imprime) |
| `api/routers/auth.py` (crear) | `/auth/magic-link`, `/auth/callback`, `/auth/logout`, `/auth/verify`, `/me` |
| `api/routers/users.py` (crear) | admin: invitar, listar, editar, cerrar sesiones |
| `api/routers/brands.py` (crear) | `GET /brands`, `POST /brands`, `GET/PATCH /brands/{slug}` (campos básicos) |
| `api/routers/secrets.py` (crear) | `GET/PUT/DELETE /brands/{slug}/secrets[/{clave}]` |
| `api/routers/pruebas.py` (crear) | `POST /brands/{slug}/telegram|instagram|llm/test` |
| `api/routers/system.py` (crear) | `GET /health` |
| `api/bootstrap.py` (crear) | CLI: `--admin`, `--importar-env`, `--nueva-master-key` |
| `src/approval_daemon.py` (modificar `correr`, `main`, + helpers) | recarga de bots al cambiar secretos |
| `tests/conftest.py` (crear) | autouse: `INSTAGOD_MASTER_KEY=None`; fixture `api_cliente` |
| `tests/test_secrets_store.py`, `tests/test_users.py`, `tests/test_account_creds_db.py`, `tests/test_api_auth.py`, `tests/test_api_users.py`, `tests/test_api_brands.py`, `tests/test_api_secrets.py`, `tests/test_api_pruebas.py`, `tests/test_daemon_recarga.py`, `tests/test_bootstrap.py` (crear) | tests por tarea |
| `requirements.txt` (modificar) | `cryptography`, `httpx` |
| `.env.example` (modificar) | vars nuevas del portal |

---

### Task 1: Tablas nuevas + whitelist + dependencias

**Files:**
- Modify: `src/schema.sql` (append al final)
- Modify: `src/db.py:23` (`TABLES`)
- Modify: `requirements.txt`
- Test: `tests/test_portal_schema.py`

**Interfaces:**
- Produces: tablas `users(id,email,nombre,is_admin,activo,created_at,last_login)`, `brand_members(user_id,account_id,rol)`, `magic_links(token_hash,user_id,expira,usado_at,created_at)`, `sessions(token_hash,user_id,expira,created_at,ua)`, `brand_secrets(account_id,clave,valor_cifrado,updated_by,updated_at)`; entradas en `db.TABLES` para `users`, `brand_members`, `brand_secrets`, `magic_links`, `sessions`.

- [ ] **Step 1: Test de esquema**

```python
# tests/test_portal_schema.py
"""Tablas del portal (users, membresías, magic links, sesiones, secretos)."""
from __future__ import annotations

import sqlite3

import pytest

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_tablas_existen_y_init_es_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # segunda vez: no truena
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "brand_members", "magic_links", "sessions",
            "brand_secrets"} <= tablas


def test_email_unico_y_rol_valido(tmp_path) -> None:
    cx = _cx(tmp_path)
    uid = db.insert(cx, "users", email="a@x.com", nombre="A")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "users", email="a@x.com", nombre="dup")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_members", user_id=uid, account_id=1, rol="dios")
    db.insert(cx, "brand_members", user_id=uid, account_id=1, rol="editor")


def test_secretos_pk_compuesta(tmp_path) -> None:
    cx = _cx(tmp_path)
    cx.execute("INSERT INTO brand_secrets(account_id, clave, valor_cifrado) "
               "VALUES (1, 'IG_USER_ID', 'x')")
    with pytest.raises(sqlite3.IntegrityError):
        cx.execute("INSERT INTO brand_secrets(account_id, clave, valor_cifrado) "
                   "VALUES (1, 'IG_USER_ID', 'y')")
```

- [ ] **Step 2: Correr y ver fallar**

Run: `.venv/bin/python -m pytest tests/test_portal_schema.py -v`
Expected: FAIL (`no such table: users` / `Tabla desconocida: users`).

- [ ] **Step 3: DDL en `src/schema.sql`** (append al final del archivo)

```sql
-- -----------------------------------------------------------------------------
-- Portal de colaboradores (spec 2026-08-17): usuarios, roles por marca,
-- magic links, sesiones y secretos cifrados por marca. Los tokens se guardan
-- SIEMPRE hasheados (sha256); el valor de un secreto SIEMPRE cifrado (Fernet).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL UNIQUE,
    nombre      TEXT,
    is_admin    INTEGER NOT NULL DEFAULT 0,
    activo      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    last_login  TEXT,
    CHECK (is_admin IN (0,1)), CHECK (activo IN (0,1))
);

CREATE TABLE IF NOT EXISTS brand_members (
    user_id     INTEGER NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    rol         TEXT NOT NULL,
    PRIMARY KEY (user_id, account_id),
    CHECK (rol IN ('manager', 'editor'))
);

CREATE TABLE IF NOT EXISTS magic_links (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expira      TEXT NOT NULL,
    usado_at    TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expira      TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    ua          TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS brand_secrets (
    account_id     INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    clave          TEXT NOT NULL,
    valor_cifrado  TEXT NOT NULL,
    updated_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (account_id, clave)
);
```

- [ ] **Step 4: Whitelist en `src/db.py`** — dentro del dict `TABLES` (línea ~23), agregar al final:

```python
    # Portal de colaboradores (spec 2026-08-17)
    "users": {"email", "nombre", "is_admin", "activo", "last_login"},
    "brand_members": {"user_id", "account_id", "rol"},
    "magic_links": {"token_hash", "user_id", "expira", "usado_at"},
    "sessions": {"token_hash", "user_id", "expira", "ua"},
    "brand_secrets": {"account_id", "clave", "valor_cifrado", "updated_by", "updated_at"},
```

- [ ] **Step 5: Dependencias** — en `requirements.txt` agregar:

```
cryptography     # secretos por marca cifrados en DB (Fernet) — portal
httpx            # cliente HTTP de la API (Resend) y TestClient
```

Run: `.venv/bin/pip install cryptography httpx`

- [ ] **Step 6: Correr y ver pasar**

Run: `.venv/bin/python -m pytest tests/test_portal_schema.py -v`
Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git pull --rebase
git add src/schema.sql src/db.py requirements.txt tests/test_portal_schema.py
git commit -m "feat(portal): tablas users/brand_members/magic_links/sessions/brand_secrets"
```

---

### Task 2: `src/secrets_store.py` (cifrado y CRUD) + `conftest.py`

**Files:**
- Create: `src/secrets_store.py`, `tests/conftest.py`
- Modify: `config.py` (bloque nuevo al final)
- Test: `tests/test_secrets_store.py`

**Interfaces:**
- Consumes: tabla `brand_secrets` (Task 1), `db.connect`, `db.rows`.
- Produces:
  - `config.INSTAGOD_MASTER_KEY: str | None`, `config.APP_URL: str`, `config.RESEND_API_KEY: str | None`, `config.MAIL_FROM: str`, `config.SESSION_DAYS: int`, `config.ENV: str`, `config.COOKIE_DOMAIN: str | None`.
  - `secrets_store.CLAVES: tuple[str, ...]`, `class SinMasterKey(RuntimeError)`, `habilitado() -> bool`, `cifrar(valor) -> str`, `descifrar(token) -> str`, `guardar(cx, account_id, clave, valor, *, user_id=None) -> None`, `borrar(cx, account_id, clave) -> bool`, `leer(cx, account_id, clave) -> str | None`, `leer_todos(cx, account_id) -> dict[str, str]`, `listar_meta(cx, account_id) -> list[dict]`, `creds_de_slug(slug) -> dict[str, str]`, `version_marcas(cx) -> dict[int, str]`.

- [ ] **Step 1: Bloque en `config.py`** (append al final del archivo; avisar a la otra sesión antes de editar `config.py`)

```python
# ---------- Portal de colaboradores (api/) ----------
# Llave maestra Fernet para brand_secrets. Sin ella, la API no acepta secretos
# y account_creds ignora la DB (solo env). Generar: python -m api.bootstrap --nueva-master-key
INSTAGOD_MASTER_KEY = _get("INSTAGOD_MASTER_KEY")
APP_URL = (_get("APP_URL", "http://localhost:3000") or "").rstrip("/")
RESEND_API_KEY = _get("RESEND_API_KEY")
MAIL_FROM = _get("MAIL_FROM", "instagod <no-reply@instagod.local>")
SESSION_DAYS = int(_get("SESSION_DAYS", "30") or 30)
ENV = (_get("ENV", "dev") or "dev").lower()          # dev | prod
COOKIE_DOMAIN = _get("COOKIE_DOMAIN")                 # p.ej. ".midominio.com" (opcional)
```

- [ ] **Step 2: `tests/conftest.py`**

```python
"""Fixtures globales: ningún test lee secretos de la DB real."""
from __future__ import annotations

import pytest

import config


@pytest.fixture(autouse=True)
def _sin_master_key_por_default(monkeypatch):
    # Los tests que necesiten cifrado setean su propia llave con
    # monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", <llave>).
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    yield
```

- [ ] **Step 3: Tests**

```python
# tests/test_secrets_store.py
"""Secretos por marca: cifrado, CRUD, metadatos sin valor, resolución por slug."""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

import config
from src import db, secrets_store as ss


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield c
    c.close()


def test_round_trip_cifrado(cx) -> None:
    tok = ss.cifrar("hola")
    assert tok != "hola" and ss.descifrar(tok) == "hola"


def test_guardar_leer_borrar(cx) -> None:
    ss.guardar(cx, 2, "IG_ACCESS_TOKEN", "abcd1234", user_id=None)
    assert ss.leer(cx, 2, "IG_ACCESS_TOKEN") == "abcd1234"
    crudo = cx.execute("SELECT valor_cifrado FROM brand_secrets").fetchone()[0]
    assert "abcd1234" not in crudo
    ss.guardar(cx, 2, "IG_ACCESS_TOKEN", "nuevo")          # upsert
    assert ss.leer(cx, 2, "IG_ACCESS_TOKEN") == "nuevo"
    assert ss.borrar(cx, 2, "IG_ACCESS_TOKEN") is True
    assert ss.borrar(cx, 2, "IG_ACCESS_TOKEN") is False
    assert ss.leer(cx, 2, "IG_ACCESS_TOKEN") is None


def test_clave_desconocida_y_valor_vacio(cx) -> None:
    with pytest.raises(KeyError):
        ss.guardar(cx, 2, "PASSWORD_ROOT", "x")
    with pytest.raises(ValueError):
        ss.guardar(cx, 2, "IG_USER_ID", "   ")


def test_listar_meta_no_expone_valor(cx) -> None:
    ss.guardar(cx, 2, "TELEGRAM_BOT_TOKEN", "123456:ABCDEF")
    meta = {m["clave"]: m for m in ss.listar_meta(cx, 2)}
    assert set(meta) == set(ss.CLAVES)
    assert meta["TELEGRAM_BOT_TOKEN"]["configurada"] is True
    assert meta["TELEGRAM_BOT_TOKEN"]["ultimos4"] == "CDEF"
    assert meta["TELEGRAM_BOT_TOKEN"]["updated_at"]
    assert meta["IG_USER_ID"] == {"clave": "IG_USER_ID", "configurada": False,
                                  "ultimos4": None, "updated_at": None}
    assert "123456" not in str(meta)


def test_leer_todos_y_creds_de_slug(cx) -> None:
    ss.guardar(cx, 2, "IG_USER_ID", "111")
    ss.guardar(cx, 2, "LLM_API_KEY", "sk-x")
    assert ss.leer_todos(cx, 2) == {"IG_USER_ID": "111", "LLM_API_KEY": "sk-x"}
    assert ss.creds_de_slug("pensionmas") == {"IG_USER_ID": "111", "LLM_API_KEY": "sk-x"}
    assert ss.creds_de_slug("no_existe") == {}


def test_sin_master_key_todo_apagado(cx, monkeypatch) -> None:
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    assert ss.habilitado() is False
    assert ss.creds_de_slug("pensionmas") == {}
    with pytest.raises(ss.SinMasterKey):
        ss.guardar(cx, 2, "IG_USER_ID", "1")


def test_version_marcas(cx) -> None:
    assert ss.version_marcas(cx) == {}
    ss.guardar(cx, 2, "IG_USER_ID", "1")
    v = ss.version_marcas(cx)
    assert list(v) == [2] and v[2]
```

- [ ] **Step 4: Correr y ver fallar**

Run: `.venv/bin/python -m pytest tests/test_secrets_store.py -v`
Expected: FAIL (`No module named src.secrets_store`).

- [ ] **Step 5: Implementación `src/secrets_store.py`**

```python
"""Secretos por marca cifrados en `brand_secrets` (Fernet con INSTAGOD_MASTER_KEY).

Reglas: el valor jamás se loguea ni se devuelve en metadatos (solo últimos 4);
sin master key el módulo está apagado (habilitado() False) y la resolución de
credenciales cae a env. Las claves permitidas son cerradas (CLAVES).
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken

import config
from src import db

CLAVES: tuple[str, ...] = (
    "IG_USER_ID", "IG_ACCESS_TOKEN",
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
    "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL",
    "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY",
    "SHEET_ID",
)


class SinMasterKey(RuntimeError):
    """INSTAGOD_MASTER_KEY no está configurada."""


def habilitado() -> bool:
    return bool(config.INSTAGOD_MASTER_KEY)


def _fernet() -> Fernet:
    if not config.INSTAGOD_MASTER_KEY:
        raise SinMasterKey("Falta INSTAGOD_MASTER_KEY: los secretos en DB están apagados")
    return Fernet(config.INSTAGOD_MASTER_KEY.encode())


def cifrar(valor: str) -> str:
    return _fernet().encrypt(valor.encode("utf-8")).decode("ascii")


def descifrar(token: str) -> str:
    return _fernet().decrypt(token.encode("ascii")).decode("utf-8")


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def guardar(cx: sqlite3.Connection, account_id: int, clave: str, valor: str,
            *, user_id: int | None = None) -> None:
    """Upsert cifrado. KeyError si la clave no es de CLAVES; ValueError si vacía."""
    if clave not in CLAVES:
        raise KeyError(f"Clave de secreto no permitida: {clave}")
    if not valor or not valor.strip():
        raise ValueError(f"El valor de {clave} no puede estar vacío")
    cx.execute(
        "INSERT INTO brand_secrets(account_id, clave, valor_cifrado, updated_by, updated_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(account_id, clave) DO UPDATE SET valor_cifrado=excluded.valor_cifrado, "
        "updated_by=excluded.updated_by, updated_at=excluded.updated_at",
        (account_id, clave, cifrar(valor.strip()), user_id, _ahora()))
    cx.commit()


def borrar(cx: sqlite3.Connection, account_id: int, clave: str) -> bool:
    cur = cx.execute("DELETE FROM brand_secrets WHERE account_id=? AND clave=?",
                     (account_id, clave))
    cx.commit()
    return cur.rowcount > 0


def leer(cx: sqlite3.Connection, account_id: int, clave: str) -> str | None:
    fila = cx.execute("SELECT valor_cifrado FROM brand_secrets WHERE account_id=? AND clave=?",
                      (account_id, clave)).fetchone()
    return descifrar(fila[0]) if fila else None


def leer_todos(cx: sqlite3.Connection, account_id: int) -> dict[str, str]:
    """{clave: valor} de la marca. Un token indescifrable (llave rotada) se salta con aviso."""
    out: dict[str, str] = {}
    for f in db.rows(cx, "SELECT clave, valor_cifrado FROM brand_secrets WHERE account_id=?",
                     (account_id,)):
        try:
            out[f["clave"]] = descifrar(f["valor_cifrado"])
        except InvalidToken:
            print(f"[secretos] {f['clave']} de account {account_id} no descifra "
                  "(¿cambió INSTAGOD_MASTER_KEY?)", file=sys.stderr)
    return out


def listar_meta(cx: sqlite3.Connection, account_id: int) -> list[dict]:
    """Metadatos de TODAS las claves posibles, sin valores."""
    filas = {f["clave"]: f for f in db.rows(
        cx, "SELECT clave, valor_cifrado, updated_at FROM brand_secrets WHERE account_id=?",
        (account_id,))}
    out = []
    for clave in CLAVES:
        f = filas.get(clave)
        if not f:
            out.append({"clave": clave, "configurada": False, "ultimos4": None,
                        "updated_at": None})
            continue
        try:
            val = descifrar(f["valor_cifrado"])
            ultimos4 = val[-4:] if len(val) >= 4 else "*" * len(val)
        except InvalidToken:
            ultimos4 = "????"
        out.append({"clave": clave, "configurada": True, "ultimos4": ultimos4,
                    "updated_at": f["updated_at"]})
    return out


def creds_de_slug(slug: str) -> dict[str, str]:
    """Secretos de la marca por slug, con conexión propia. {} si el módulo está
    apagado, la DB/tabla no existe (worker sin DB) o la marca no existe."""
    if not habilitado():
        return {}
    try:
        cx = db.connect()
    except sqlite3.Error:
        return {}
    try:
        fila = cx.execute("SELECT id FROM accounts WHERE slug=?", (slug,)).fetchone()
        if not fila:
            return {}
        return leer_todos(cx, int(fila[0]))
    except sqlite3.Error as e:  # tabla ausente en una DB vieja: no es fatal
        print(f"[secretos] no pude leer brand_secrets: {e}", file=sys.stderr)
        return {}
    finally:
        cx.close()


def version_marcas(cx: sqlite3.Connection) -> dict[int, str]:
    """{account_id: max(updated_at)} — huella barata para detectar cambios."""
    return {int(f["account_id"]): f["v"] for f in db.rows(
        cx, "SELECT account_id, MAX(updated_at) AS v FROM brand_secrets GROUP BY account_id")}
```

- [ ] **Step 6: Correr y ver pasar**

Run: `.venv/bin/python -m pytest tests/test_secrets_store.py -v`
Expected: 7 PASS.

- [ ] **Step 7: Commit**

```bash
git pull --rebase
git add src/secrets_store.py tests/conftest.py tests/test_secrets_store.py config.py
git commit -m "feat(secretos): brand_secrets cifrados con Fernet + constantes del portal en config"
```

---

### Task 3: `config.account_creds` con precedencia DB → env

**Files:**
- Modify: `config.py:370-404` (`_ACCOUNT_CRED_KEYS`, `account_creds`)
- Test: `tests/test_account_creds_db.py`

**Interfaces:**
- Consumes: `secrets_store.creds_de_slug(slug)`.
- Produces: `config.account_creds(slug) -> dict[str, str | None]` (misma firma) con claves de `_ACCOUNT_CRED_KEYS` extendida: `IG_USER_ID, IG_ACCESS_TOKEN, IG_SCRAPER_SESSIONID, IG_SCRAPER_UA, SHEET_ID, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, LLM_PROVIDER, LLM_API_KEY, LLM_MODEL, PEXELS_API_KEY, UNSPLASH_ACCESS_KEY, NEWSAPI_KEY`.

- [ ] **Step 1: Test**

```python
# tests/test_account_creds_db.py
"""account_creds: DB (brand_secrets) gana a env con sufijo; env global solo gdlscene."""
from __future__ import annotations

import importlib

import pytest
from cryptography.fernet import Fernet

import config
from src import db, secrets_store as ss


@pytest.fixture()
def entorno(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    importlib.reload(config)
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield cx, pid
    cx.close()


def test_db_gana_a_env_sufijo(entorno, monkeypatch) -> None:
    cx, pid = entorno
    monkeypatch.setenv("IG_ACCESS_TOKEN__PENSIONMAS", "de-env")
    ss.guardar(cx, pid, "IG_ACCESS_TOKEN", "de-db")
    assert config.account_creds("pensionmas")["IG_ACCESS_TOKEN"] == "de-db"


def test_env_sufijo_cuando_db_no_tiene(entorno, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_CHAT_ID__PENSIONMAS", "-100")
    assert config.account_creds("pensionmas")["TELEGRAM_CHAT_ID"] == "-100"


def test_marca_nueva_no_hereda_global_ni_con_db(entorno, monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-gdl")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN__PENSIONMAS", raising=False)
    assert config.account_creds("pensionmas")["TELEGRAM_BOT_TOKEN"] is None
    assert config.account_creds("gdlscene")["TELEGRAM_BOT_TOKEN"] == "token-gdl"


def test_gdlscene_db_gana_a_global(entorno, monkeypatch) -> None:
    cx, _ = entorno
    monkeypatch.setenv("SHEET_ID", "sheet-env")
    ss.guardar(cx, 1, "SHEET_ID", "sheet-db")
    assert config.account_creds("gdlscene")["SHEET_ID"] == "sheet-db"


def test_claves_llm_e_imagenes_presentes(entorno) -> None:
    creds = config.account_creds("pensionmas")
    for k in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL", "PEXELS_API_KEY",
              "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY"):
        assert k in creds


def test_sin_master_key_ignora_db(entorno, monkeypatch) -> None:
    cx, pid = entorno
    ss.guardar(cx, pid, "IG_USER_ID", "db")
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    monkeypatch.setenv("IG_USER_ID__PENSIONMAS", "env")
    assert config.account_creds("pensionmas")["IG_USER_ID"] == "env"
```

- [ ] **Step 2: Correr y ver fallar**

Run: `.venv/bin/python -m pytest tests/test_account_creds_db.py -v`
Expected: `test_db_gana_a_env_sufijo`, `test_gdlscene_db_gana_a_global`, `test_claves_llm_e_imagenes_presentes` FAIL.

- [ ] **Step 3: Implementación en `config.py`** — reemplazar `_ACCOUNT_CRED_KEYS` y `account_creds`:

```python
_ACCOUNT_CRED_KEYS = ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_SCRAPER_SESSIONID",
                      "IG_SCRAPER_UA", "SHEET_ID",
                      "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                      # Portal: LLM y APIs de imágenes/noticias por marca (opcionales)
                      "LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL",
                      "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY")


def _creds_db(slug: str) -> dict[str, str]:
    """Secretos de la marca en DB (brand_secrets). {} si el store está apagado
    o falla: la resolución cae a env sin tumbar al que llama."""
    if not INSTAGOD_MASTER_KEY:
        return {}
    try:
        from src import secrets_store  # import tardío: src importa config
        return secrets_store.creds_de_slug(slug)
    except Exception as e:  # noqa: BLE001 — nunca romper por secretos en DB
        import sys
        print(f"[config] secretos en DB no disponibles para {slug}: {e}", file=sys.stderr)
        return {}


def account_creds(slug: str) -> dict[str, str | None]:
    """Credenciales de una cuenta. Precedencia: DB (brand_secrets) → env con
    sufijo __SLUG → env global SOLO para gdlscene.

    Una cuenta nueva jamás hereda por accidente los tokens de gdlscene.
    """
    sufijo = f"__{slug.upper()}"
    en_db = _creds_db(slug)
    out: dict[str, str | None] = {}
    for k in _ACCOUNT_CRED_KEYS:
        val = en_db.get(k)
        if val is None:
            val = os.getenv(k + sufijo)
        if val is None and slug == "gdlscene":
            val = os.getenv(k)
        out[k] = val
    return out
```

Nota: `INSTAGOD_MASTER_KEY` se define en el bloque del final de `config.py` (Task 2); Python lo resuelve en tiempo de llamada, así que `_creds_db` puede vivir antes del bloque.

- [ ] **Step 4: Correr todo**

Run: `.venv/bin/python -m pytest tests/test_account_creds_db.py tests/test_marcas.py tests/test_multicuenta.py -v`
Expected: PASS (los tests viejos de no-herencia siguen verdes porque `conftest` apaga la master key).

- [ ] **Step 5: Commit**

```bash
git pull --rebase
git add config.py tests/test_account_creds_db.py
git commit -m "feat(secretos): account_creds resuelve DB → env sufijo → global (solo gdlscene)"
```

---

### Task 4: `src/users.py` — usuarios, roles, magic links, sesiones

**Files:**
- Create: `src/users.py`
- Test: `tests/test_users.py`

**Interfaces:**
- Produces: `ROLES = ("manager", "editor")`; `class LinkInvalido(ValueError)`; `crear_usuario(cx, email, nombre=None, *, is_admin=False) -> int`; `por_email(cx, email) -> dict | None`; `por_id(cx, uid) -> dict | None`; `listar(cx) -> list[dict]` (con `marcas`); `asignar_marca(cx, user_id, account_id, rol) -> None`; `quitar_marca(cx, user_id, account_id) -> None`; `marcas_de(cx, user_id) -> list[dict]` (`{account_id, slug, nombre, ig_handle, color_marca, activa, rol}`); `rol_en(cx, user, account_id) -> str | None` (`"admin"|"manager"|"editor"|None`); `crear_magic_link(cx, user_id, *, ttl_min=15, ahora=None) -> str`; `consumir_magic_link(cx, token, *, ahora=None) -> int`; `crear_sesion(cx, user_id, *, dias=30, ua=None, ahora=None) -> str`; `usuario_de_sesion(cx, token, *, ahora=None) -> dict | None`; `cerrar_sesion(cx, token) -> None`; `cerrar_sesiones_de(cx, user_id) -> int`; `hash_token(token) -> str`.

- [ ] **Step 1: Tests**

```python
# tests/test_users.py
"""Usuarios del portal: alta, roles por marca, magic links y sesiones."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src import db, users


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    yield c
    c.close()


T0 = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def test_crear_usuario_normaliza_email_y_rechaza_duplicado(cx) -> None:
    uid = users.crear_usuario(cx, "  Ana@X.com ", "Ana")
    assert users.por_email(cx, "ana@x.com")["id"] == uid
    with pytest.raises(ValueError):
        users.crear_usuario(cx, "ANA@x.com")
    with pytest.raises(ValueError):
        users.crear_usuario(cx, "no-es-email")


def test_roles_por_marca(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    admin = users.crear_usuario(cx, "r@x.com", is_admin=True)
    users.asignar_marca(cx, uid, 2, "editor")
    assert users.rol_en(cx, users.por_id(cx, uid), 2) == "editor"
    assert users.rol_en(cx, users.por_id(cx, uid), 1) is None
    users.asignar_marca(cx, uid, 2, "manager")          # upsert
    assert users.marcas_de(cx, uid) == [{
        "account_id": 2, "slug": "pensionmas", "nombre": "P", "ig_handle": "@p",
        "color_marca": "#1b5e3f", "activa": 1, "rol": "manager"}]
    assert users.rol_en(cx, users.por_id(cx, admin), 2) == "admin"
    with pytest.raises(ValueError):
        users.asignar_marca(cx, uid, 2, "dios")
    users.quitar_marca(cx, uid, 2)
    assert users.marcas_de(cx, uid) == []


def test_magic_link_un_uso_y_expira(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    tok = users.crear_magic_link(cx, uid, ahora=T0)
    assert len(tok) >= 32
    assert cx.execute("SELECT token_hash FROM magic_links").fetchone()[0] != tok
    assert users.consumir_magic_link(cx, tok, ahora=T0 + timedelta(minutes=5)) == uid
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, tok, ahora=T0 + timedelta(minutes=6))  # ya usado
    tok2 = users.crear_magic_link(cx, uid, ahora=T0)
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, tok2, ahora=T0 + timedelta(minutes=16))  # expiró
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, "inventado", ahora=T0)


def test_magic_link_usuario_inactivo(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    tok = users.crear_magic_link(cx, uid, ahora=T0)
    db.update(cx, "users", uid, activo=0)
    with pytest.raises(users.LinkInvalido):
        users.consumir_magic_link(cx, tok, ahora=T0)


def test_sesiones(cx) -> None:
    uid = users.crear_usuario(cx, "a@x.com")
    s = users.crear_sesion(cx, uid, dias=30, ua="pytest", ahora=T0)
    u = users.usuario_de_sesion(cx, s, ahora=T0 + timedelta(days=1))
    assert u["id"] == uid and u["email"] == "a@x.com"
    assert users.usuario_de_sesion(cx, s, ahora=T0 + timedelta(days=31)) is None
    assert users.usuario_de_sesion(cx, "otra", ahora=T0) is None
    s2 = users.crear_sesion(cx, uid, ahora=T0)
    users.cerrar_sesion(cx, s2)
    assert users.usuario_de_sesion(cx, s2, ahora=T0) is None
    assert users.cerrar_sesiones_de(cx, uid) == 1
    assert users.usuario_de_sesion(cx, s, ahora=T0) is None
    assert users.por_id(cx, uid)["last_login"] is not None
```

- [ ] **Step 2: Correr y ver fallar**

Run: `.venv/bin/python -m pytest tests/test_users.py -v`
Expected: FAIL (`No module named src.users`).

- [ ] **Step 3: Implementación `src/users.py`**

```python
"""Usuarios del portal: alta, membresías por marca, magic links y sesiones.

Tokens (magic link, sesión) se generan con `secrets.token_urlsafe(32)` y se
guardan hasheados (sha256): una fuga de la DB no regala sesiones vivas.
Fechas ISO en UTC ("YYYY-MM-DD HH:MM:SS"), comparables como texto.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from src import db

ROLES = ("manager", "editor")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LinkInvalido(ValueError):
    """Magic link inexistente, usado, expirado o de usuario inactivo."""


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _ahora(ahora: datetime | None) -> datetime:
    return ahora or datetime.now(timezone.utc)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if not _EMAIL_RE.match(e):
        raise ValueError(f"Email inválido: {email!r}")
    return e


# ---------- usuarios ----------

def crear_usuario(cx: sqlite3.Connection, email: str, nombre: str | None = None,
                  *, is_admin: bool = False) -> int:
    e = _norm_email(email)
    if por_email(cx, e):
        raise ValueError(f"Ya existe un usuario con email {e}")
    return db.insert(cx, "users", email=e, nombre=(nombre or "").strip() or None,
                     is_admin=1 if is_admin else 0)


def por_email(cx: sqlite3.Connection, email: str) -> dict | None:
    r = db.rows(cx, "SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))
    return r[0] if r else None


def por_id(cx: sqlite3.Connection, uid: int) -> dict | None:
    return db.get(cx, "users", uid)


def listar(cx: sqlite3.Connection) -> list[dict]:
    out = []
    for u in db.rows(cx, "SELECT * FROM users ORDER BY id"):
        u["marcas"] = marcas_de(cx, u["id"])
        out.append(u)
    return out


# ---------- membresías ----------

def asignar_marca(cx: sqlite3.Connection, user_id: int, account_id: int, rol: str) -> None:
    if rol not in ROLES:
        raise ValueError(f"Rol inválido: {rol!r} (válidos: {', '.join(ROLES)})")
    cx.execute("INSERT INTO brand_members(user_id, account_id, rol) VALUES (?, ?, ?) "
               "ON CONFLICT(user_id, account_id) DO UPDATE SET rol = excluded.rol",
               (user_id, account_id, rol))
    cx.commit()


def quitar_marca(cx: sqlite3.Connection, user_id: int, account_id: int) -> None:
    cx.execute("DELETE FROM brand_members WHERE user_id=? AND account_id=?",
               (user_id, account_id))
    cx.commit()


def marcas_de(cx: sqlite3.Connection, user_id: int) -> list[dict]:
    return db.rows(cx, """
        SELECT a.id AS account_id, a.slug, a.nombre, a.ig_handle, a.color_marca,
               a.activa, m.rol
          FROM brand_members m JOIN accounts a ON a.id = m.account_id
         WHERE m.user_id = ? ORDER BY a.id""", (user_id,))


def rol_en(cx: sqlite3.Connection, user: dict, account_id: int) -> str | None:
    """'admin' para admins globales; si no, el rol de la membresía o None."""
    if user.get("is_admin"):
        return "admin"
    r = cx.execute("SELECT rol FROM brand_members WHERE user_id=? AND account_id=?",
                   (user["id"], account_id)).fetchone()
    return r[0] if r else None


# ---------- magic links ----------

def crear_magic_link(cx: sqlite3.Connection, user_id: int, *, ttl_min: int = 15,
                     ahora: datetime | None = None) -> str:
    tok = secrets.token_urlsafe(32)
    db.insert(cx, "magic_links", token_hash=hash_token(tok), user_id=user_id,
              expira=_fmt(_ahora(ahora) + timedelta(minutes=ttl_min)))
    return tok


def consumir_magic_link(cx: sqlite3.Connection, token: str, *,
                        ahora: datetime | None = None) -> int:
    """Marca el link como usado y devuelve el user_id. LinkInvalido si no aplica."""
    now = _fmt(_ahora(ahora))
    fila = cx.execute("""
        SELECT l.token_hash, l.user_id, l.expira, l.usado_at, u.activo
          FROM magic_links l JOIN users u ON u.id = l.user_id
         WHERE l.token_hash = ?""", (hash_token(token),)).fetchone()
    if not fila or fila["usado_at"] or fila["expira"] < now or not fila["activo"]:
        raise LinkInvalido("Link inválido, usado o expirado")
    cx.execute("UPDATE magic_links SET usado_at=? WHERE token_hash=?", (now, fila["token_hash"]))
    cx.execute("UPDATE users SET last_login=? WHERE id=?", (now, fila["user_id"]))
    cx.commit()
    return int(fila["user_id"])


# ---------- sesiones ----------

def crear_sesion(cx: sqlite3.Connection, user_id: int, *, dias: int = 30,
                 ua: str | None = None, ahora: datetime | None = None) -> str:
    tok = secrets.token_urlsafe(32)
    db.insert(cx, "sessions", token_hash=hash_token(tok), user_id=user_id,
              expira=_fmt(_ahora(ahora) + timedelta(days=dias)), ua=(ua or "")[:200] or None)
    return tok


def usuario_de_sesion(cx: sqlite3.Connection, token: str, *,
                      ahora: datetime | None = None) -> dict | None:
    if not token:
        return None
    r = db.rows(cx, """
        SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
         WHERE s.token_hash = ? AND s.expira > ? AND u.activo = 1""",
                (hash_token(token), _fmt(_ahora(ahora))))
    return r[0] if r else None


def cerrar_sesion(cx: sqlite3.Connection, token: str) -> None:
    cx.execute("DELETE FROM sessions WHERE token_hash=?", (hash_token(token),))
    cx.commit()


def cerrar_sesiones_de(cx: sqlite3.Connection, user_id: int) -> int:
    cur = cx.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    cx.commit()
    return cur.rowcount
```

- [ ] **Step 4: Correr y ver pasar**

Run: `.venv/bin/python -m pytest tests/test_users.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git pull --rebase
git add src/users.py tests/test_users.py
git commit -m "feat(portal): usuarios, roles por marca, magic links y sesiones"
```

---

### Task 5: Esqueleto `api/` + auth (magic link, sesión, `/me`, `/auth/verify`)

**Files:**
- Create: `api/__init__.py`, `api/app.py`, `api/errors.py`, `api/deps.py`, `api/ratelimit.py`, `api/mail.py`, `api/routers/__init__.py`, `api/routers/auth.py`, `api/routers/system.py`
- Modify: `tests/conftest.py` (fixture `api_cliente`)
- Test: `tests/test_api_auth.py`

**Interfaces:**
- Consumes: `src.users.*` (Task 4), `config.APP_URL/SESSION_DAYS/ENV/COOKIE_DOMAIN/RESEND_API_KEY/MAIL_FROM`.
- Produces:
  - `api.app.create_app() -> FastAPI`, `api.app.app`.
  - `api.errors.ApiError(status: int, error: str, detalle: str, campo: str | None = None)`; helpers `no_autenticado()`, `sin_permiso()`, `no_encontrado(que)`, `cred_faltante(clave)`, `conflicto(detalle)`.
  - `api.deps.get_cx()` (yield conexión), `api.deps.usuario_actual(request, cx) -> dict`, `api.deps.requiere_admin(user) -> dict`, `api.deps.marca_para(slug, cx, user, minimo="editor") -> tuple[dict, str]` (fila de `accounts`, rol efectivo; 404 si no existe, 403 si sin permiso o rol insuficiente; orden `editor < manager < admin`).
  - `api.ratelimit.Limitador(max_eventos, ventana_seg).permitir(clave, ahora=None) -> bool`.
  - `api.mail.enviar_magic_link(email, url) -> None` (`_post_resend(payload)` monkeypatcheable).
  - Cookie `instagod_session` (`api.routers.auth.COOKIE`).
  - Rutas: `POST /auth/magic-link {email}` → 200 `{ok: true}` siempre (429 si excede 5/h por email o IP); `GET /auth/callback?token=` → 302 a `APP_URL/brands` con cookie, o 302 a `APP_URL/login?error=link_invalido`; `POST /auth/logout` → 200; `GET /auth/verify` → 200 `{ok:true}` si sesión admin, 401 si no; `GET /me` → `{id, email, nombre, is_admin, marcas:[...]}`; `GET /health` → `{ok: true, version}`.

- [ ] **Step 1: Fixture en `tests/conftest.py`** (append)

```python
@pytest.fixture()
def api_cliente(tmp_path, monkeypatch):
    """TestClient de la API con DB temporal. Devuelve (cliente, cx, helpers)."""
    import importlib

    from fastapi.testclient import TestClient

    from src import db, users

    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    importlib.reload(config)
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", None)
    monkeypatch.setattr(config, "APP_URL", "http://front.test")
    monkeypatch.setattr(config, "ENV", "dev")
    from api import app as app_mod
    importlib.reload(app_mod)
    cx = db.connect(tmp_path / "api.db")
    db.init_db(cx)
    cli = TestClient(app_mod.app, base_url="http://api.test")

    class H:
        """Atajos: crear usuarios y loguearlos (cookie de sesión)."""

        @staticmethod
        def usuario(email, *, admin=False, marcas=()):
            uid = users.crear_usuario(cx, email, is_admin=admin)
            for account_id, rol in marcas:
                users.asignar_marca(cx, uid, account_id, rol)
            return uid

        @staticmethod
        def login(uid):
            tok = users.crear_sesion(cx, uid)
            cli.cookies.set("instagod_session", tok)
            return tok

        @staticmethod
        def logout():
            cli.cookies.clear()

    yield cli, cx, H
    cx.close()
```

- [ ] **Step 2: Tests**

```python
# tests/test_api_auth.py
"""API: magic link, sesión por cookie, /me, /auth/verify, /health, errores JSON."""
from __future__ import annotations

from src import db, users


def test_health(api_cliente) -> None:
    cli, _, _ = api_cliente
    r = cli.get("/health")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_me_sin_sesion_401_json(api_cliente) -> None:
    cli, _, _ = api_cliente
    r = cli.get("/me")
    assert r.status_code == 401
    assert r.json() == {"error": "no_autenticado", "detalle": "Inicia sesión", "campo": None}


def test_magic_link_flujo_completo(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "_post_resend", lambda payload: enviados.append(payload))
    monkeypatch.setattr(mail.config, "RESEND_API_KEY", "re_test")
    uid = H.usuario("ana@x.com", marcas=[(1, "editor")])
    r = cli.post("/auth/magic-link", json={"email": "Ana@X.com"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(enviados) == 1 and enviados[0]["to"] == ["ana@x.com"]
    url = enviados[0]["_url"]
    assert url.startswith("http://api.test/auth/callback?token=")
    r = cli.get(url, follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == "http://front.test/brands"
    assert "instagod_session=" in r.headers["set-cookie"]
    assert "HttpOnly" in r.headers["set-cookie"]
    me = cli.get("/me").json()
    assert me["email"] == "ana@x.com" and me["is_admin"] is False
    assert me["marcas"][0]["slug"] == "gdlscene" and me["marcas"][0]["rol"] == "editor"
    r = cli.get(url, follow_redirects=False)              # segundo uso: inválido
    assert r.headers["location"] == "http://front.test/login?error=link_invalido"
    assert users.por_id(cx, uid)["last_login"]


def test_magic_link_email_desconocido_responde_igual_y_no_manda(api_cliente, monkeypatch) -> None:
    cli, _, _ = api_cliente
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "_post_resend", lambda payload: enviados.append(payload))
    r = cli.post("/auth/magic-link", json={"email": "nadie@x.com"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert enviados == []


def test_magic_link_rate_limit(api_cliente, monkeypatch) -> None:
    cli, _, H = api_cliente
    from api import mail
    monkeypatch.setattr(mail, "_post_resend", lambda payload: None)
    H.usuario("ana@x.com")
    for _ in range(5):
        assert cli.post("/auth/magic-link", json={"email": "ana@x.com"}).status_code == 200
    r = cli.post("/auth/magic-link", json={"email": "ana@x.com"})
    assert r.status_code == 429 and r.json()["error"] == "demasiados_intentos"


def test_magic_link_en_dev_sin_resend_imprime_url(api_cliente, capsys) -> None:
    cli, _, H = api_cliente
    H.usuario("ana@x.com")
    cli.post("/auth/magic-link", json={"email": "ana@x.com"})
    assert "/auth/callback?token=" in capsys.readouterr().out


def test_logout_y_verify(api_cliente) -> None:
    cli, _, H = api_cliente
    uid = H.usuario("r@x.com", admin=True)
    assert cli.get("/auth/verify").status_code == 401
    H.login(uid)
    assert cli.get("/auth/verify").status_code == 200
    assert cli.post("/auth/logout").status_code == 200
    assert cli.get("/me").status_code == 401


def test_verify_no_admin_401(api_cliente) -> None:
    cli, _, H = api_cliente
    H.login(H.usuario("e@x.com", marcas=[(1, "manager")]))
    assert cli.get("/auth/verify").status_code == 401


def test_usuario_inactivo_pierde_sesion(api_cliente) -> None:
    cli, cx, H = api_cliente
    uid = H.usuario("e@x.com")
    H.login(uid)
    db.update(cx, "users", uid, activo=0)
    assert cli.get("/me").status_code == 401
```

- [ ] **Step 3: Correr y ver fallar**

Run: `.venv/bin/python -m pytest tests/test_api_auth.py -v`
Expected: FAIL (`No module named api`).

- [ ] **Step 4: `api/errors.py`**

```python
"""Errores JSON uniformes de la API: {error, detalle, campo}."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, error: str, detalle: str, campo: str | None = None):
        super().__init__(detalle)
        self.status, self.error, self.detalle, self.campo = status, error, detalle, campo

    def cuerpo(self) -> dict:
        return {"error": self.error, "detalle": self.detalle, "campo": self.campo}


def no_autenticado() -> ApiError:
    return ApiError(401, "no_autenticado", "Inicia sesión")


def sin_permiso(detalle: str = "No tienes permiso sobre esta marca") -> ApiError:
    return ApiError(403, "sin_permiso", detalle)


def no_encontrado(que: str) -> ApiError:
    return ApiError(404, "no_encontrado", f"No existe {que}")


def conflicto(detalle: str, campo: str | None = None) -> ApiError:
    return ApiError(409, "conflicto", detalle, campo)


def cred_faltante(clave: str) -> ApiError:
    return ApiError(422, "cred_faltante", f"Falta configurar {clave} en la marca", clave)


async def manejar_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(exc.cuerpo(), status_code=exc.status)
```

- [ ] **Step 5: `api/ratelimit.py`**

```python
"""Límite de eventos por clave en memoria (suficiente para 1 proceso de API)."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class Limitador:
    def __init__(self, max_eventos: int, ventana_seg: int):
        self.max, self.ventana = max_eventos, ventana_seg
        self._eventos: dict[str, deque[float]] = defaultdict(deque)

    def permitir(self, clave: str, ahora: float | None = None) -> bool:
        t = time.monotonic() if ahora is None else ahora
        cola = self._eventos[clave]
        while cola and t - cola[0] > self.ventana:
            cola.popleft()
        if len(cola) >= self.max:
            return False
        cola.append(t)
        return True
```

- [ ] **Step 6: `api/mail.py`**

```python
"""Correo transaccional del portal (Resend). Sin RESEND_API_KEY en dev, imprime la URL."""
from __future__ import annotations

import httpx

import config


def _post_resend(payload: dict) -> None:
    payload = {k: v for k, v in payload.items() if not k.startswith("_")}
    r = httpx.post("https://api.resend.com/emails", json=payload, timeout=10,
                   headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"})
    r.raise_for_status()


def enviar_magic_link(email: str, url: str) -> None:
    if not config.RESEND_API_KEY:
        if config.ENV == "prod":
            raise RuntimeError("Falta RESEND_API_KEY para mandar magic links en prod")
        print(f"[mail] (dev) magic link para {email}: {url}")
        return
    _post_resend({
        "from": config.MAIL_FROM,
        "to": [email],
        "subject": "Tu acceso a instagod",
        "html": (f"<p>Entra a instagod con este link (vale 15 minutos):</p>"
                 f"<p><a href=\"{url}\">{url}</a></p>"
                 "<p>Si no lo pediste, ignora este correo.</p>"),
        "_url": url,   # solo para tests; _post_resend lo descarta
    })
```

- [ ] **Step 7: `api/deps.py`**

```python
"""Dependencias FastAPI: conexión, usuario de la cookie, permisos por marca."""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request

from api.errors import no_autenticado, no_encontrado, sin_permiso
from src import db, users

COOKIE = "instagod_session"
_ORDEN_ROL = {"editor": 1, "manager": 2, "admin": 3}


def get_cx() -> Iterator:
    cx = db.connect()
    try:
        yield cx
    finally:
        cx.close()


def usuario_actual(request: Request, cx=Depends(get_cx)) -> dict:
    u = users.usuario_de_sesion(cx, request.cookies.get(COOKIE, ""))
    if not u:
        raise no_autenticado()
    return u


def requiere_admin(user: dict = Depends(usuario_actual)) -> dict:
    if not user.get("is_admin"):
        raise sin_permiso("Solo administradores")
    return user


def marca_para(slug: str, cx, user: dict, minimo: str = "editor") -> tuple[dict, str]:
    """Fila de accounts + rol efectivo del usuario. 404 si no existe, 403 si no alcanza."""
    fila = db.get_account(cx, slug)
    if not fila:
        raise no_encontrado(f"la marca {slug!r}")
    rol = users.rol_en(cx, user, fila["id"])
    if not rol or _ORDEN_ROL[rol] < _ORDEN_ROL[minimo]:
        raise sin_permiso()
    return fila, rol
```

- [ ] **Step 8: `api/routers/system.py`**

```python
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["system"])
VERSION = "portal-fase1"


@router.get("/health")
def health() -> dict:
    return {"ok": True, "version": VERSION}
```

- [ ] **Step 9: `api/routers/auth.py`**

```python
"""Login por magic link, sesión en cookie httpOnly, /me y /auth/verify."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr

import config
from api import mail
from api.deps import COOKIE, get_cx, usuario_actual
from api.errors import ApiError, no_autenticado
from api.ratelimit import Limitador
from src import users

router = APIRouter(tags=["auth"])
_limite_email = Limitador(5, 3600)
_limite_ip = Limitador(5, 3600)


class PedirLink(BaseModel):
    email: EmailStr


def _poner_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(COOKIE, token, max_age=config.SESSION_DAYS * 86400, httponly=True,
                    secure=(config.ENV == "prod"), samesite="lax", path="/",
                    domain=config.COOKIE_DOMAIN or None)


@router.post("/auth/magic-link")
def pedir_magic_link(datos: PedirLink, request: Request, cx=Depends(get_cx)) -> dict:
    email = datos.email.lower()
    ip = request.client.host if request.client else "?"
    if not (_limite_email.permitir(email) and _limite_ip.permitir(ip)):
        raise ApiError(429, "demasiados_intentos", "Espera un rato antes de pedir otro link")
    u = users.por_email(cx, email)
    if u and u["activo"]:
        tok = users.crear_magic_link(cx, u["id"])
        url = str(request.url_for("auth_callback")) + f"?token={tok}"
        mail.enviar_magic_link(email, url)
    return {"ok": True}   # nunca revela si el email existe


@router.get("/auth/callback", name="auth_callback")
def auth_callback(token: str, request: Request, cx=Depends(get_cx)) -> RedirectResponse:
    try:
        uid = users.consumir_magic_link(cx, token)
    except users.LinkInvalido:
        return RedirectResponse(f"{config.APP_URL}/login?error=link_invalido", status_code=302)
    ses = users.crear_sesion(cx, uid, dias=config.SESSION_DAYS,
                             ua=request.headers.get("user-agent"))
    resp = RedirectResponse(f"{config.APP_URL}/brands", status_code=302)
    _poner_cookie(resp, ses)
    return resp


@router.post("/auth/logout")
def logout(request: Request, cx=Depends(get_cx)) -> Response:
    tok = request.cookies.get(COOKIE)
    if tok:
        users.cerrar_sesion(cx, tok)
    resp = Response(content='{"ok": true}', media_type="application/json")
    resp.delete_cookie(COOKIE, path="/", domain=config.COOKIE_DOMAIN or None)
    return resp


@router.get("/auth/verify")
def verify(user: dict = Depends(usuario_actual)) -> dict:
    """Para forward_auth de Caddy (GUI legacy): 200 solo si la sesión es admin."""
    if not user.get("is_admin"):
        raise no_autenticado()
    return {"ok": True}


@router.get("/me")
def me(user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    return {"id": user["id"], "email": user["email"], "nombre": user["nombre"],
            "is_admin": bool(user["is_admin"]), "marcas": users.marcas_de(cx, user["id"])}
```

`EmailStr` requiere `email-validator`: `.venv/bin/pip install "pydantic[email]"` y agregar `email-validator  # EmailStr en la API` a `requirements.txt`.

- [ ] **Step 10: `api/app.py` y `api/__init__.py`, `api/routers/__init__.py`** (los `__init__.py` vacíos con docstring de una línea)

```python
"""API JSON del portal de colaboradores. Uso: uvicorn api.app:app --port 8100"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.errors import ApiError, manejar_api_error
from api.routers import auth, system
from src import db


def create_app() -> FastAPI:
    app = FastAPI(title="instagod API", docs_url="/docs", redoc_url=None)
    app.add_exception_handler(ApiError, manejar_api_error)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_, exc: RequestValidationError):
        e = exc.errors()[0] if exc.errors() else {}
        campo = ".".join(str(p) for p in e.get("loc", [])[1:]) or None
        return JSONResponse({"error": "validacion", "detalle": e.get("msg", "Datos inválidos"),
                             "campo": campo}, status_code=422)

    @app.on_event("startup")
    def _startup() -> None:
        cx = db.connect()
        try:
            db.init_db(cx)
        finally:
            cx.close()

    app.include_router(system.router)
    app.include_router(auth.router)
    return app


app = create_app()
```

- [ ] **Step 11: Correr y ver pasar**

Run: `.venv/bin/python -m pytest tests/test_api_auth.py -v`
Expected: 9 PASS. Luego `ruff check api src tests`.

- [ ] **Step 12: Commit**

```bash
git pull --rebase
git add api tests/conftest.py tests/test_api_auth.py requirements.txt
git commit -m "feat(api): esqueleto FastAPI JSON con magic link, sesión por cookie, /me y /auth/verify"
```

---

### Task 6: Router admin de usuarios

**Files:**
- Create: `api/routers/users.py`
- Modify: `api/app.py` (include_router)
- Test: `tests/test_api_users.py`

**Interfaces:**
- Produces (admin-only): `GET /users` → lista con `marcas`; `POST /users/invite {email, nombre?, marcas:[{slug, rol}], is_admin?}` → 201 `{id, email, ...}` y manda magic link; `PATCH /users/{id} {nombre?, activo?, is_admin?, marcas?:[{slug, rol}]}` (marcas reemplaza el set completo); `POST /users/{id}/reinvitar` (nuevo magic link); `DELETE /users/{id}/sessions` → `{cerradas: n}`.

- [ ] **Step 1: Tests**

```python
# tests/test_api_users.py
"""Admin: invitar, listar, editar membresías, cerrar sesiones. No-admin → 403."""
from __future__ import annotations

from src import db, users


def _admin(H):
    uid = H.usuario("r@x.com", admin=True)
    H.login(uid)
    return uid


def test_no_admin_403(api_cliente) -> None:
    cli, _, H = api_cliente
    H.login(H.usuario("e@x.com", marcas=[(1, "manager")]))
    assert cli.get("/users").status_code == 403
    assert cli.post("/users/invite", json={"email": "z@x.com"}).status_code == 403


def test_invitar_crea_asigna_y_manda_link(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    _admin(H)
    db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "enviar_magic_link", lambda e, u: enviados.append((e, u)))
    r = cli.post("/users/invite", json={
        "email": "Colab@X.com", "nombre": "Colab",
        "marcas": [{"slug": "pensionmas", "rol": "manager"}]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "colab@x.com" and body["marcas"][0]["rol"] == "manager"
    assert enviados and enviados[0][0] == "colab@x.com"
    r = cli.post("/users/invite", json={"email": "colab@x.com"})
    assert r.status_code == 409 and r.json()["error"] == "conflicto"
    r = cli.post("/users/invite", json={"email": "z@x.com",
                                        "marcas": [{"slug": "nope", "rol": "editor"}]})
    assert r.status_code == 404
    r = cli.post("/users/invite", json={"email": "z@x.com",
                                        "marcas": [{"slug": "pensionmas", "rol": "dios"}]})
    assert r.status_code == 422


def test_listar_y_patch(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    _admin(H)
    from api import mail
    monkeypatch.setattr(mail, "enviar_magic_link", lambda e, u: None)
    uid = cli.post("/users/invite", json={"email": "c@x.com",
                                          "marcas": [{"slug": "gdlscene", "rol": "editor"}]}).json()["id"]
    lista = cli.get("/users").json()
    assert [u["email"] for u in lista] == ["r@x.com", "c@x.com"]
    r = cli.patch(f"/users/{uid}", json={"nombre": "Ceci", "marcas": []})
    assert r.status_code == 200 and r.json()["nombre"] == "Ceci" and r.json()["marcas"] == []
    r = cli.patch(f"/users/{uid}", json={"activo": False})
    assert r.json()["activo"] == 0
    assert cli.patch("/users/999", json={"nombre": "x"}).status_code == 404


def test_reinvitar_y_cerrar_sesiones(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    _admin(H)
    from api import mail
    enviados = []
    monkeypatch.setattr(mail, "enviar_magic_link", lambda e, u: enviados.append(e))
    uid = H.usuario("c@x.com")
    users.crear_sesion(cx, uid)
    assert cli.post(f"/users/{uid}/reinvitar").status_code == 200 and enviados == ["c@x.com"]
    assert cli.delete(f"/users/{uid}/sessions").json() == {"cerradas": 1}
```

- [ ] **Step 2: Correr y ver fallar**

Run: `.venv/bin/python -m pytest tests/test_api_users.py -v` → FAIL (404 en `/users`).

- [ ] **Step 3: Implementación `api/routers/users.py`**

```python
"""Administración de usuarios (solo admin)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field

from api import mail
from api.deps import get_cx, requiere_admin
from api.errors import ApiError, conflicto, no_encontrado
from src import db, users

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(requiere_admin)])


class MarcaRol(BaseModel):
    slug: str
    rol: str


class Invitar(BaseModel):
    email: EmailStr
    nombre: str | None = None
    is_admin: bool = False
    marcas: list[MarcaRol] = Field(default_factory=list)


class Editar(BaseModel):
    nombre: str | None = None
    activo: bool | None = None
    is_admin: bool | None = None
    marcas: list[MarcaRol] | None = None


def _resolver_marcas(cx, marcas: list[MarcaRol]) -> list[tuple[int, str]]:
    out = []
    for m in marcas:
        if m.rol not in users.ROLES:
            raise ApiError(422, "validacion", f"Rol inválido: {m.rol}", "rol")
        fila = db.get_account(cx, m.slug)
        if not fila:
            raise no_encontrado(f"la marca {m.slug!r}")
        out.append((fila["id"], m.rol))
    return out


def _vista(cx, uid: int) -> dict:
    u = users.por_id(cx, uid)
    u["marcas"] = users.marcas_de(cx, uid)
    return u


def _mandar_link(cx, request: Request, uid: int, email: str) -> None:
    tok = users.crear_magic_link(cx, uid)
    mail.enviar_magic_link(email, str(request.url_for("auth_callback")) + f"?token={tok}")


@router.get("")
def listar(cx=Depends(get_cx)) -> list[dict]:
    return users.listar(cx)


@router.post("/invite", status_code=201)
def invitar(datos: Invitar, request: Request, cx=Depends(get_cx)) -> dict:
    asignaciones = _resolver_marcas(cx, datos.marcas)
    try:
        uid = users.crear_usuario(cx, datos.email, datos.nombre, is_admin=datos.is_admin)
    except ValueError as e:
        raise conflicto(str(e), "email") from e
    for account_id, rol in asignaciones:
        users.asignar_marca(cx, uid, account_id, rol)
    _mandar_link(cx, request, uid, datos.email.lower())
    return _vista(cx, uid)


@router.patch("/{uid}")
def editar(uid: int, datos: Editar, cx=Depends(get_cx)) -> dict:
    if not users.por_id(cx, uid):
        raise no_encontrado(f"el usuario {uid}")
    campos = {}
    if datos.nombre is not None:
        campos["nombre"] = datos.nombre.strip() or None
    if datos.activo is not None:
        campos["activo"] = 1 if datos.activo else 0
    if datos.is_admin is not None:
        campos["is_admin"] = 1 if datos.is_admin else 0
    if campos:
        db.update(cx, "users", uid, **campos)
    if datos.marcas is not None:
        nuevas = _resolver_marcas(cx, datos.marcas)
        for m in users.marcas_de(cx, uid):
            users.quitar_marca(cx, uid, m["account_id"])
        for account_id, rol in nuevas:
            users.asignar_marca(cx, uid, account_id, rol)
    return _vista(cx, uid)


@router.post("/{uid}/reinvitar")
def reinvitar(uid: int, request: Request, cx=Depends(get_cx)) -> dict:
    u = users.por_id(cx, uid)
    if not u:
        raise no_encontrado(f"el usuario {uid}")
    _mandar_link(cx, request, uid, u["email"])
    return {"ok": True}


@router.delete("/{uid}/sessions")
def cerrar_sesiones(uid: int, cx=Depends(get_cx)) -> dict:
    if not users.por_id(cx, uid):
        raise no_encontrado(f"el usuario {uid}")
    return {"cerradas": users.cerrar_sesiones_de(cx, uid)}
```

En `api/app.py`: `from api.routers import auth, system, users` y `app.include_router(users.router)`.

- [ ] **Step 4: Correr y ver pasar**

Run: `.venv/bin/python -m pytest tests/test_api_users.py tests/test_api_auth.py -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git pull --rebase
git add api/routers/users.py api/app.py tests/test_api_users.py
git commit -m "feat(api): admin de usuarios (invitar, editar membresías, reinvitar, cerrar sesiones)"
```

---

### Task 7: Router de marcas (lista por rol, alta admin, detalle, patch básico)

**Files:**
- Create: `api/routers/brands.py`
- Modify: `api/app.py`
- Test: `tests/test_api_brands.py`

**Interfaces:**
- Consumes: `api.deps.marca_para`, `src.marcas.creds_faltantes(slug)`.
- Produces: `GET /brands` → `[{id, slug, nombre, ig_handle, ciudad, timezone, color_marca, activa, logo_path, rol, creds_faltantes:[...]}]` (admin: todas activas e inactivas; otros: sus membresías); `POST /brands {slug, nombre, ig_handle, ciudad?, timezone?, color_marca?}` (admin) → 201; `GET /brands/{slug}` (miembro) → fila completa de `accounts` (sin secretos: no hay) + `rol`; `PATCH /brands/{slug} {nombre?, ig_handle?, ciudad?, timezone?, color_marca?, activa?}` (manager; `activa` solo admin).
- `creds_faltantes` aquí se calcula con `marcas.creds_faltantes(slug)` pero devolviendo **claves sin sufijo** (`TELEGRAM_BOT_TOKEN`, ...): agregar en `src/marcas.py` la función `claves_faltantes(slug) -> list[str]` = `[v for v in CRED_VARS if not config.account_creds(slug).get(v)]` sin `SHEET_ID` (ya no es obligatorio): `CRED_OBLIGATORIAS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "IG_USER_ID", "IG_ACCESS_TOKEN")`. `creds_faltantes` existente no se toca.

- [ ] **Step 1: Tests**

```python
# tests/test_api_brands.py
"""Marcas: visibilidad por rol, alta admin, detalle y edición básica."""
from __future__ import annotations

from src import db


def test_lista_segun_rol(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    lista = cli.get("/brands").json()
    assert [b["slug"] for b in lista] == ["pensionmas"] and lista[0]["rol"] == "editor"
    assert "TELEGRAM_BOT_TOKEN" in lista[0]["creds_faltantes"]
    H.logout()
    H.login(H.usuario("r@x.com", admin=True))
    assert [b["slug"] for b in cli.get("/brands").json()] == ["gdlscene", "pensionmas"]


def test_alta_solo_admin_y_validaciones(api_cliente) -> None:
    cli, _, H = api_cliente
    H.login(H.usuario("m@x.com", marcas=[(1, "manager")]))
    assert cli.post("/brands", json={"slug": "x1", "nombre": "X", "ig_handle": "@x"}).status_code == 403
    H.logout()
    H.login(H.usuario("r@x.com", admin=True))
    r = cli.post("/brands", json={"slug": "Melaque Capital", "nombre": "M", "ig_handle": "@m"})
    assert r.status_code == 422 and r.json()["campo"] == "slug"
    r = cli.post("/brands", json={"slug": "melaque", "nombre": "Melaque", "ig_handle": "melaque"})
    assert r.status_code == 201 and r.json()["ig_handle"] == "@melaque"
    r = cli.post("/brands", json={"slug": "melaque", "nombre": "Otra", "ig_handle": "@o"})
    assert r.status_code == 409


def test_detalle_y_patch(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    eid = H.usuario("e@x.com", marcas=[(pid, "editor")])
    H.login(eid)
    assert cli.get("/brands/pensionmas").json()["nombre"] == "P"
    assert cli.get("/brands/gdlscene").status_code == 403
    assert cli.get("/brands/nope").status_code == 404
    assert cli.patch("/brands/pensionmas", json={"nombre": "PP"}).status_code == 403
    H.logout()
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.patch("/brands/pensionmas", json={"nombre": "Pensión+", "color_marca": "#112233"})
    assert r.status_code == 200 and r.json()["nombre"] == "Pensión+"
    assert cli.patch("/brands/pensionmas", json={"activa": False}).status_code == 403
    assert cli.patch("/brands/pensionmas", json={"color_marca": "rojo"}).status_code == 422
```

- [ ] **Step 2: Correr y ver fallar** → FAIL (404 en `/brands`).

- [ ] **Step 3: `src/marcas.py`** — agregar debajo de `creds_faltantes`:

```python
# Portal: obligatorias para operar (SHEET_ID ya no lo es: la cola vive en DB).
CRED_OBLIGATORIAS = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "IG_USER_ID", "IG_ACCESS_TOKEN")


def claves_faltantes(slug: str) -> list[str]:
    """Claves (sin sufijo) que la marca aún no tiene ni en DB ni en env."""
    creds = config.account_creds(slug)
    return [k for k in CRED_OBLIGATORIAS if not creds.get(k)]
```

- [ ] **Step 4: `api/routers/brands.py`**

```python
"""Marcas: lista por rol, alta (admin), detalle y edición básica (manager)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, field_validator

from api.deps import get_cx, marca_para, requiere_admin, usuario_actual
from api.errors import ApiError, conflicto, sin_permiso
from src import db, marcas, users

router = APIRouter(prefix="/brands", tags=["brands"])
_SLUG_RE = re.compile(r"^[a-z0-9_]{2,32}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _handle(v: str) -> str:
    v = (v or "").strip()
    return v if v.startswith("@") else f"@{v}"


class NuevaMarca(BaseModel):
    slug: str
    nombre: str
    ig_handle: str
    ciudad: str = "México"
    timezone: str = "America/Mexico_City"
    color_marca: str = "#1b5e3f"

    @field_validator("slug")
    @classmethod
    def _slug(cls, v):
        if not _SLUG_RE.match(v):
            raise ValueError("solo minúsculas, dígitos y guion bajo (2-32)")
        return v

    @field_validator("color_marca")
    @classmethod
    def _color(cls, v):
        if not _COLOR_RE.match(v):
            raise ValueError("color hex #RRGGBB")
        return v


class EditarMarca(BaseModel):
    nombre: str | None = None
    ig_handle: str | None = None
    ciudad: str | None = None
    timezone: str | None = None
    color_marca: str | None = None
    activa: bool | None = None

    @field_validator("color_marca")
    @classmethod
    def _color(cls, v):
        if v is not None and not _COLOR_RE.match(v):
            raise ValueError("color hex #RRGGBB")
        return v


def _resumen(fila: dict, rol: str) -> dict:
    return {"id": fila["id"], "slug": fila["slug"], "nombre": fila["nombre"],
            "ig_handle": fila["ig_handle"], "ciudad": fila["ciudad"],
            "timezone": fila["timezone"], "color_marca": fila["color_marca"],
            "activa": fila["activa"], "logo_path": fila.get("logo_path"), "rol": rol,
            "creds_faltantes": marcas.claves_faltantes(fila["slug"])}


@router.get("")
def listar(user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    if user["is_admin"]:
        return [_resumen(f, "admin") for f in db.list_accounts(cx, solo_activas=False)]
    return [_resumen(db.get_account(cx, m["slug"]), m["rol"]) for m in users.marcas_de(cx, user["id"])]


@router.post("", status_code=201, dependencies=[Depends(requiere_admin)])
def crear(datos: NuevaMarca, cx=Depends(get_cx)) -> dict:
    if db.get_account(cx, datos.slug):
        raise conflicto(f"Ya existe la marca {datos.slug}", "slug")
    db.insert(cx, "accounts", slug=datos.slug, nombre=datos.nombre.strip(),
              ig_handle=_handle(datos.ig_handle), ciudad=datos.ciudad,
              timezone=datos.timezone, color_marca=datos.color_marca)
    return _resumen(db.get_account(cx, datos.slug), "admin")


@router.get("/{slug}")
def detalle(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, rol = marca_para(slug, cx, user)
    return {**fila, "rol": rol}


@router.patch("/{slug}")
def editar(slug: str, datos: EditarMarca, user: dict = Depends(usuario_actual),
           cx=Depends(get_cx)) -> dict:
    fila, rol = marca_para(slug, cx, user, minimo="manager")
    campos = {k: v for k, v in datos.model_dump().items() if v is not None}
    if "activa" in campos:
        if rol != "admin":
            raise sin_permiso("Solo un admin activa/desactiva marcas")
        campos["activa"] = 1 if campos["activa"] else 0
    if "ig_handle" in campos:
        campos["ig_handle"] = _handle(campos["ig_handle"])
    if campos:
        db.update(cx, "accounts", fila["id"], **campos)
    fila, rol = marca_para(slug, cx, user)
    return {**fila, "rol": rol}
```

Registrar en `api/app.py`: `from api.routers import auth, brands, system, users` + `app.include_router(brands.router)`.

- [ ] **Step 5: Correr y ver pasar** → `pytest tests/test_api_brands.py -v` PASS. Si el 422 de `slug` no trae `campo == "slug"`, revisar que el handler de `RequestValidationError` (Task 5) tome `loc[1:]` (`["body","slug"]` → `"slug"`).

- [ ] **Step 6: Commit**

```bash
git pull --rebase
git add api/routers/brands.py api/app.py src/marcas.py tests/test_api_brands.py
git commit -m "feat(api): marcas por rol, alta admin, detalle y edición básica"
```

---

### Task 8: Router de secretos por marca

**Files:**
- Create: `api/routers/secrets.py`
- Modify: `api/app.py`
- Test: `tests/test_api_secrets.py`

**Interfaces:**
- Consumes: `secrets_store.listar_meta/guardar/borrar/CLAVES/habilitado`, `marca_para(minimo="manager")`.
- Produces: `GET /brands/{slug}/secrets` (manager) → `listar_meta`; `PUT /brands/{slug}/secrets/{clave} {valor}` → 200 metadato de esa clave; `DELETE /brands/{slug}/secrets/{clave}` → 204; 503 `{"error":"secretos_apagados"}` si no hay master key; 404 clave desconocida.

- [ ] **Step 1: Tests**

```python
# tests/test_api_secrets.py
"""Secretos por marca vía API: solo manager+, nunca se devuelve el valor."""
from __future__ import annotations

from cryptography.fernet import Fernet

import config
from src import db, secrets_store as ss


def _marca(cx):
    return db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")


def test_sin_master_key_503(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.put("/brands/pensionmas/secrets/IG_USER_ID", json={"valor": "1"})
    assert r.status_code == 503 and r.json()["error"] == "secretos_apagados"


def test_editor_403_manager_ok_valor_nunca_sale(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.get("/brands/pensionmas/secrets").status_code == 403
    H.logout()
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.put("/brands/pensionmas/secrets/TELEGRAM_BOT_TOKEN", json={"valor": "123456:ABCDEF"})
    assert r.status_code == 200
    assert r.json() == {"clave": "TELEGRAM_BOT_TOKEN", "configurada": True,
                        "ultimos4": "CDEF", "updated_at": r.json()["updated_at"]}
    lista = cli.get("/brands/pensionmas/secrets").json()
    assert "123456" not in str(lista) and len(lista) == len(ss.CLAVES)
    assert ss.leer(cx, pid, "TELEGRAM_BOT_TOKEN") == "123456:ABCDEF"
    assert cli.put("/brands/pensionmas/secrets/PASSWORD", json={"valor": "x"}).status_code == 404
    assert cli.put("/brands/pensionmas/secrets/IG_USER_ID", json={"valor": " "}).status_code == 422
    assert cli.delete("/brands/pensionmas/secrets/TELEGRAM_BOT_TOKEN").status_code == 204
    assert cli.delete("/brands/pensionmas/secrets/TELEGRAM_BOT_TOKEN").status_code == 404


def test_aislamiento_entre_marcas(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    assert cli.get("/brands/gdlscene/secrets").status_code == 403
    cli.put("/brands/pensionmas/secrets/IG_USER_ID", json={"valor": "777"})
    assert config.account_creds("gdlscene")["IG_USER_ID"] is None
    assert config.account_creds("pensionmas")["IG_USER_ID"] == "777"
```

- [ ] **Step 2: Correr y ver fallar** → FAIL (404).

- [ ] **Step 3: `api/routers/secrets.py`**

```python
"""Secretos por marca (manager+). La API jamás devuelve valores."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, no_encontrado
from src import secrets_store as ss

router = APIRouter(prefix="/brands/{slug}/secrets", tags=["secrets"])


class Valor(BaseModel):
    valor: str


def _requiere_store() -> None:
    if not ss.habilitado():
        raise ApiError(503, "secretos_apagados",
                       "Falta INSTAGOD_MASTER_KEY en el servidor: no se pueden guardar secretos")


def _clave_valida(clave: str) -> None:
    if clave not in ss.CLAVES:
        raise no_encontrado(f"la clave de secreto {clave!r}")


@router.get("")
def listar(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _requiere_store()
    return ss.listar_meta(cx, fila["id"])


@router.put("/{clave}")
def poner(slug: str, clave: str, datos: Valor, user: dict = Depends(usuario_actual),
          cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _clave_valida(clave)
    _requiere_store()
    try:
        ss.guardar(cx, fila["id"], clave, datos.valor, user_id=user["id"])
    except ValueError as e:
        raise ApiError(422, "validacion", str(e), "valor") from e
    return next(m for m in ss.listar_meta(cx, fila["id"]) if m["clave"] == clave)


@router.delete("/{clave}", status_code=204)
def quitar(slug: str, clave: str, user: dict = Depends(usuario_actual),
           cx=Depends(get_cx)) -> Response:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _clave_valida(clave)
    if not ss.borrar(cx, fila["id"], clave):
        raise no_encontrado(f"el secreto {clave} en {slug}")
    return Response(status_code=204)
```

Registrar en `api/app.py` (`from api.routers import auth, brands, secrets, system, users`; `app.include_router(secrets.router)`). Ojo: registrar `secrets.router` **antes** que cualquier ruta `/brands/{slug}/...` genérica futura no importa aquí, pero sí después de `brands.router` está bien (paths distintos).

- [ ] **Step 4: Correr y ver pasar** → PASS.

- [ ] **Step 5: Commit**

```bash
git pull --rebase
git add api/routers/secrets.py api/app.py tests/test_api_secrets.py
git commit -m "feat(api): secretos por marca (manager+), metadatos sin valor, aislamiento"
```

---

### Task 9: Endpoints de prueba (Telegram, Instagram, LLM)

**Files:**
- Create: `api/routers/pruebas.py`
- Modify: `api/app.py`
- Test: `tests/test_api_pruebas.py`

**Interfaces:**
- Consumes: `config.account_creds(slug)`, `errors.cred_faltante`.
- Produces: `POST /brands/{slug}/telegram/test` → `{ok, detalle}` (manda "✅ instagod conectado a <nombre>" al chat); `POST /brands/{slug}/instagram/test` → `{ok, username}`; `POST /brands/{slug}/llm/test` → `{ok, provider, model, respuesta}`. Funciones monkeypatcheables: `_telegram_send(token, chat_id, texto) -> dict`, `_ig_me(token) -> dict`, `_llm_ping(provider, key, model) -> str`. Fallo remoto → 502 `{"error":"prueba_fallida", "detalle": ...}`.

- [ ] **Step 1: Tests**

```python
# tests/test_api_pruebas.py
"""Botones 'Probar' de conexiones: creds de la marca, cred faltante → 422, remoto → 502."""
from __future__ import annotations

from src import db


def _setup(api_cliente, monkeypatch, **env):
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    for k, v in env.items():
        monkeypatch.setenv(f"{k}__PENSIONMAS", v)
    return cli


def test_telegram_ok_y_faltante(api_cliente, monkeypatch) -> None:
    from api.routers import pruebas
    llamadas = []
    monkeypatch.setattr(pruebas, "_telegram_send",
                        lambda t, c, txt: llamadas.append((t, c, txt)) or {"ok": True})
    cli = _setup(api_cliente, monkeypatch, TELEGRAM_BOT_TOKEN="1:A", TELEGRAM_CHAT_ID="-9")
    r = cli.post("/brands/pensionmas/telegram/test")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert llamadas[0][:2] == ("1:A", "-9") and "P" in llamadas[0][2]
    monkeypatch.delenv("TELEGRAM_CHAT_ID__PENSIONMAS")
    r = cli.post("/brands/pensionmas/telegram/test")
    assert r.status_code == 422 and r.json()["campo"] == "TELEGRAM_CHAT_ID"


def test_instagram_502_si_falla(api_cliente, monkeypatch) -> None:
    from api.routers import pruebas

    def _boom(token):
        raise RuntimeError("token expirado")
    monkeypatch.setattr(pruebas, "_ig_me", _boom)
    cli = _setup(api_cliente, monkeypatch, IG_ACCESS_TOKEN="t", IG_USER_ID="1")
    r = cli.post("/brands/pensionmas/instagram/test")
    assert r.status_code == 502 and "token expirado" in r.json()["detalle"]


def test_llm_usa_creds_de_marca_o_global(api_cliente, monkeypatch) -> None:
    from api.routers import pruebas
    import config
    monkeypatch.setattr(pruebas, "_llm_ping", lambda p, k, m: f"pong:{p}:{m}")
    cli = _setup(api_cliente, monkeypatch, LLM_PROVIDER="claude", LLM_API_KEY="sk",
                 LLM_MODEL="claude-sonnet-4-6")
    assert cli.post("/brands/pensionmas/llm/test").json()["respuesta"] == "pong:claude:claude-sonnet-4-6"
    for k in ("LLM_PROVIDER", "LLM_API_KEY", "LLM_MODEL"):
        monkeypatch.delenv(f"{k}__PENSIONMAS")
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", "global")
    r = cli.post("/brands/pensionmas/llm/test").json()
    assert r["provider"] == "deepseek" and r["ok"] is True
    monkeypatch.setattr(config, "DEEPSEEK_API_KEY", None)
    assert cli.post("/brands/pensionmas/llm/test").status_code == 422


def test_editor_403(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    assert cli.post("/brands/pensionmas/telegram/test").status_code == 403
```

- [ ] **Step 2: Correr y ver fallar** → FAIL (404).

- [ ] **Step 3: `api/routers/pruebas.py`**

```python
"""Botones "Probar" de la pestaña Conexiones. Manager+."""
from __future__ import annotations

import requests
from fastapi import APIRouter, Depends

import config
from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, cred_faltante

router = APIRouter(prefix="/brands/{slug}", tags=["pruebas"])


# --- adaptadores remotos (monkeypatcheables en tests) ---

def _telegram_send(token: str, chat_id: str, texto: str) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      json={"chat_id": chat_id, "text": texto}, timeout=15)
    r.raise_for_status()
    return r.json()


def _ig_me(token: str) -> dict:
    r = requests.get("https://graph.instagram.com/me",
                     params={"fields": "id,username", "access_token": token}, timeout=15)
    r.raise_for_status()
    return r.json()


def _llm_ping(provider: str, key: str, model: str) -> str:
    if provider == "claude":
        import anthropic
        msg = anthropic.Anthropic(api_key=key).messages.create(
            model=model, max_tokens=5, messages=[{"role": "user", "content": "Di 'ok'"}])
        return msg.content[0].text
    from openai import OpenAI
    out = OpenAI(api_key=key, base_url=config.DEEPSEEK_BASE_URL).chat.completions.create(
        model=model, max_tokens=5, messages=[{"role": "user", "content": "Di 'ok'"}])
    return out.choices[0].message.content or ""


def _fallo(e: Exception) -> ApiError:
    return ApiError(502, "prueba_fallida", f"El servicio respondió con error: {e}")


def _llm_de(creds: dict) -> tuple[str, str, str]:
    provider = (creds.get("LLM_PROVIDER") or config.LLM_PROVIDER or "deepseek").lower()
    if creds.get("LLM_API_KEY"):
        key = creds["LLM_API_KEY"]
    else:
        key = config.ANTHROPIC_API_KEY if provider == "claude" else config.DEEPSEEK_API_KEY
    if not key:
        raise cred_faltante("LLM_API_KEY")
    model = creds.get("LLM_MODEL") or (
        config.ANTHROPIC_MODEL if provider == "claude" else config.DEEPSEEK_MODEL)
    return provider, key, model


@router.post("/telegram/test")
def telegram_test(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    creds = config.account_creds(slug)
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        if not creds.get(k):
            raise cred_faltante(k)
    try:
        _telegram_send(creds["TELEGRAM_BOT_TOKEN"], creds["TELEGRAM_CHAT_ID"],
                       f"✅ instagod conectado a {fila['nombre']} ({fila['ig_handle']})")
    except Exception as e:  # noqa: BLE001
        raise _fallo(e) from e
    return {"ok": True, "detalle": "Mensaje enviado al chat configurado"}


@router.post("/instagram/test")
def instagram_test(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca_para(slug, cx, user, minimo="manager")
    creds = config.account_creds(slug)
    for k in ("IG_ACCESS_TOKEN", "IG_USER_ID"):
        if not creds.get(k):
            raise cred_faltante(k)
    try:
        me = _ig_me(creds["IG_ACCESS_TOKEN"])
    except Exception as e:  # noqa: BLE001
        raise _fallo(e) from e
    return {"ok": True, "username": me.get("username"), "id": me.get("id")}


@router.post("/llm/test")
def llm_test(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca_para(slug, cx, user, minimo="manager")
    provider, key, model = _llm_de(config.account_creds(slug))
    try:
        respuesta = _llm_ping(provider, key, model)
    except Exception as e:  # noqa: BLE001
        raise _fallo(e) from e
    return {"ok": True, "provider": provider, "model": model, "respuesta": respuesta[:80]}
```

Registrar en `api/app.py`.

- [ ] **Step 4: Correr y ver pasar** → PASS.

- [ ] **Step 5: Commit**

```bash
git pull --rebase
git add api/routers/pruebas.py api/app.py tests/test_api_pruebas.py
git commit -m "feat(api): botones probar Telegram/Instagram/LLM con creds de la marca"
```

---

### Task 10: Daemon recarga bots al cambiar secretos (sin reinicio)

**Files:**
- Modify: `src/approval_daemon.py:224-283` (`correr`, `main`, helpers nuevos)
- Test: `tests/test_daemon_recarga.py`

**Interfaces:**
- Consumes: `marcas_con_bot`, `config.account_creds` (ya con DB).
- Produces: `RECARGA_SEG = 60`; `_huella(pares) -> tuple`; `_pares_actuales() -> list`; `async _esperar_senal_o_cambio(huella, calcular, cada) -> str` (`"senal"|"recarga"`); `correr(apps, *, esperar=None) -> str` (compatible: sin `esperar` usa `_esperar_senal` y devuelve `"senal"`); `main()` en bucle: recarga cuando cambia la huella; sin marcas con bot → espera en vez de fallar.

- [ ] **Step 1: Tests**

```python
# tests/test_daemon_recarga.py
"""Daemon: recarga las Applications cuando cambian tokens/chat de marcas."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from src import approval_daemon as ad
from tests.test_daemon_multibot import _FakeApp


@dataclass
class _M:
    slug: str


def test_huella_estable_e_independiente_del_orden() -> None:
    a = [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"}),
         (_M("b"), {"TELEGRAM_BOT_TOKEN": "2", "TELEGRAM_CHAT_ID": "y"})]
    assert ad._huella(a) == ad._huella(list(reversed(a)))
    b = [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "z"})]
    assert ad._huella(a) != ad._huella(b)


def test_esperar_detecta_cambio() -> None:
    valores = iter([("v1",), ("v1",), ("v2",)])
    motivo = asyncio.run(ad._esperar_senal_o_cambio(("v1",), lambda: next(valores), cada=0.001))
    assert motivo == "recarga"


def test_correr_devuelve_motivo_y_apaga(monkeypatch) -> None:
    log: list = []
    apps = [_FakeApp("a", log)]

    async def _recarga():
        return "recarga"
    assert asyncio.run(ad.correr(apps, esperar=_recarga)) == "recarga"
    assert "shutdown:a" in log


def test_main_recarga_hasta_senal(monkeypatch) -> None:
    rondas = iter([
        [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"})],
        [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"}),
         (_M("b"), {"TELEGRAM_BOT_TOKEN": "2", "TELEGRAM_CHAT_ID": "y"})],
    ])
    construidas: list = []
    motivos = iter(["recarga", "senal"])
    monkeypatch.setattr(ad.poller_lock, "adquirir", lambda: None)
    monkeypatch.setattr(ad, "_pares_actuales", lambda: next(rondas))
    monkeypatch.setattr(ad, "construir_app",
                        lambda t, c, slug, interactivo=False: construidas.append(slug) or object())

    async def _correr(apps, *, esperar=None):
        return next(motivos)
    monkeypatch.setattr(ad, "correr", _correr)
    ad.main()
    assert construidas == ["a", "a", "b"]


def test_main_sin_bots_espera_en_vez_de_fallar(monkeypatch) -> None:
    rondas = iter([[], [(_M("a"), {"TELEGRAM_BOT_TOKEN": "1", "TELEGRAM_CHAT_ID": "x"})]])
    dormidas: list = []
    monkeypatch.setattr(ad.poller_lock, "adquirir", lambda: None)
    monkeypatch.setattr(ad, "_pares_actuales", lambda: next(rondas))
    monkeypatch.setattr(ad, "_dormir", lambda s: dormidas.append(s))
    monkeypatch.setattr(ad, "construir_app", lambda *a, **k: object())

    async def _correr(apps, *, esperar=None):
        return "senal"
    monkeypatch.setattr(ad, "correr", _correr)
    ad.main()
    assert dormidas == [ad.RECARGA_SEG]
```

- [ ] **Step 2: Correr y ver fallar** → FAIL (`_huella` no existe).

- [ ] **Step 3: Implementación** en `src/approval_daemon.py`. Agregar `import time` arriba y, antes de `correr`:

```python
RECARGA_SEG = 60   # cada cuánto revisa si cambiaron tokens/chats de marcas


def _huella(pares) -> tuple:
    """Huella de (slug, token, chat) de las marcas con bot: cambia → recargar."""
    return tuple(sorted((m.slug, c.get("TELEGRAM_BOT_TOKEN"), c.get("TELEGRAM_CHAT_ID"))
                        for m, c in pares))


def _pares_actuales() -> list:
    cx = db.connect()
    try:
        db.init_db(cx)
        lista = marcas_mod.listar(cx)
    finally:
        cx.close()
    return marcas_con_bot(lista)


def _dormir(seg: float) -> None:
    time.sleep(seg)


async def _esperar_senal_o_cambio(huella, calcular, cada: float = RECARGA_SEG) -> str:
    """Termina con 'senal' (SIGINT/SIGTERM) o 'recarga' (cambió la huella)."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    while not stop.is_set():
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=cada)
        if stop.is_set():
            break
        try:
            if await asyncio.to_thread(calcular) != huella:
                return "recarga"
        except Exception as e:  # noqa: BLE001 — un fallo de DB no tumba el daemon
            print(f"WARNING recarga: {e}", file=sys.stderr)
    return "senal"
```

Modificar `correr` para aceptar `esperar` y devolver motivo:

```python
async def correr(apps, *, esperar=None) -> str:
    """... (docstring existente) ...
    `esperar` (corutina sin args) decide cuándo terminar; por default espera
    señal. Devuelve el motivo ('senal' | 'recarga') para que main() decida si
    reconstruir los bots.
    """
    latido = None
    motivo = "senal"
    try:
        for app in apps:
            await app.initialize()
        for app in apps:
            await app.start()
        latido = asyncio.create_task(_latido_loop_multi(apps))
        for app in apps:
            await app.updater.start_polling(drop_pending_updates=True,
                                            bootstrap_retries=-1)
        motivo = await (esperar() if esperar else _esperar_senal()) or "senal"
    finally:
        # ... bloque finally existente sin cambios ...
    return motivo
```

(`_esperar_senal` devuelve None → `or "senal"`. Los tests viejos que monkeypatchean `_esperar_senal` siguen funcionando.)

Reemplazar `main`:

```python
def main() -> None:
    poller_lock.adquirir()
    while True:
        pares = _pares_actuales()
        if not pares:
            print("[daemon] ninguna marca tiene TELEGRAM_BOT_TOKEN/CHAT_ID; "
                  f"reviso de nuevo en {RECARGA_SEG}s")
            _dormir(RECARGA_SEG)
            continue
        huella = _huella(pares)
        apps = [construir_app(creds["TELEGRAM_BOT_TOKEN"], creds["TELEGRAM_CHAT_ID"],
                              m.slug, interactivo=(m.slug == "gdlscene"))
                for m, creds in pares]
        print(f"Daemon multi-bot: {len(apps)} marca(s) — "
              + ", ".join(m.slug for m, _ in pares))

        async def _esperar(h=huella):
            return await _esperar_senal_o_cambio(
                h, lambda: _huella(_pares_actuales()), cada=RECARGA_SEG)
        motivo = asyncio.run(correr(apps, esperar=_esperar))
        if motivo != "recarga":
            break
        print("[daemon] cambiaron credenciales de Telegram: recargando bots")
```

Nota: en `test_main_sin_bots_espera_en_vez_de_fallar` el segundo `_pares_actuales` devuelve una marca y `correr` fake devuelve `"senal"` → sale del bucle. Si algún test existente esperaba `RuntimeError` con cero bots (`grep -n "Ninguna marca" tests/`), actualizarlo a este comportamiento.

- [ ] **Step 4: Correr** → `pytest tests/test_daemon_recarga.py tests/test_daemon_multibot.py tests/test_daemon_health.py tests/test_daemon_watchdog.py -v` PASS.

- [ ] **Step 5: Commit**

```bash
git pull --rebase
git add src/approval_daemon.py tests/test_daemon_recarga.py
git commit -m "feat(daemon): recarga bots al cambiar secretos de Telegram; sin bots espera en vez de fallar"
```

---

### Task 11: `api.bootstrap` CLI + `.env.example` + smoke de arranque

**Files:**
- Create: `api/bootstrap.py`
- Modify: `.env.example` (append), `docs/bot_telegram_uso.md` no; crear `docs/api_portal.md` (uso mínimo: correr, crear admin, endpoints)
- Test: `tests/test_bootstrap.py`

**Interfaces:**
- Produces: `python -m api.bootstrap --nueva-master-key` (imprime llave Fernet); `--admin EMAIL [--nombre N]` (crea/asegura admin, imprime URL de magic link relativa a `API_URL_PUBLICA` o `http://localhost:8100`); `--importar-env` (por cada `accounts` activa, copia `KEY__SLUG` — y global para gdlscene — de `os.environ` a `brand_secrets` para `secrets_store.CLAVES`; imprime resumen; no pisa lo que ya está en DB salvo `--forzar`). Funciones: `nueva_master_key() -> str`, `asegurar_admin(cx, email, nombre=None) -> tuple[int, str]` (uid, token magic), `importar_env(cx, environ, *, forzar=False) -> dict[str, list[str]]` (slug → claves importadas).

- [ ] **Step 1: Tests**

```python
# tests/test_bootstrap.py
"""CLI de arranque: master key, admin inicial, importar secretos de env a DB."""
from __future__ import annotations

from cryptography.fernet import Fernet

import config
from api import bootstrap
from src import db, secrets_store as ss, users


def test_nueva_master_key_es_fernet() -> None:
    Fernet(bootstrap.nueva_master_key().encode())


def test_asegurar_admin_idempotente(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    uid, tok = bootstrap.asegurar_admin(cx, "R@x.com", "Ricardo")
    assert users.por_id(cx, uid)["is_admin"] == 1
    uid2, tok2 = bootstrap.asegurar_admin(cx, "r@x.com")
    assert uid2 == uid and tok2 != tok
    assert users.consumir_magic_link(cx, tok2) == uid


def test_importar_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "INSTAGOD_MASTER_KEY", Fernet.generate_key().decode())
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    pid = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    env = {"IG_USER_ID": "gdl-user", "TELEGRAM_BOT_TOKEN": "gdl-tok",
           "IG_USER_ID__PENSIONMAS": "p-user", "OTRA_COSA": "x"}
    res = bootstrap.importar_env(cx, env)
    assert res == {"gdlscene": ["IG_USER_ID", "TELEGRAM_BOT_TOKEN"], "pensionmas": ["IG_USER_ID"]}
    assert ss.leer(cx, 1, "IG_USER_ID") == "gdl-user"
    assert ss.leer(cx, pid, "IG_USER_ID") == "p-user"
    assert ss.leer(cx, pid, "TELEGRAM_BOT_TOKEN") is None      # no hereda global
    env["IG_USER_ID__PENSIONMAS"] = "cambiado"
    assert bootstrap.importar_env(cx, env) == {"gdlscene": [], "pensionmas": []}
    assert bootstrap.importar_env(cx, env, forzar=True)["pensionmas"] == ["IG_USER_ID"]
    assert ss.leer(cx, pid, "IG_USER_ID") == "cambiado"
```

- [ ] **Step 2: Correr y ver fallar** → FAIL.

- [ ] **Step 3: `api/bootstrap.py`**

```python
"""Arranque del portal desde CLI.

  python -m api.bootstrap --nueva-master-key
  python -m api.bootstrap --admin tu@email.com [--nombre "Ricardo"]
  python -m api.bootstrap --importar-env [--forzar]
"""
from __future__ import annotations

import argparse
import os
import sys

from cryptography.fernet import Fernet

import config
from src import db, secrets_store as ss, users


def nueva_master_key() -> str:
    return Fernet.generate_key().decode()


def asegurar_admin(cx, email: str, nombre: str | None = None) -> tuple[int, str]:
    """Crea (o promueve) al admin y devuelve (uid, token de magic link)."""
    u = users.por_email(cx, email)
    if u:
        uid = u["id"]
        db.update(cx, "users", uid, is_admin=1, activo=1)
    else:
        uid = users.crear_usuario(cx, email, nombre, is_admin=True)
    return uid, users.crear_magic_link(cx, uid, ttl_min=60)


def importar_env(cx, environ, *, forzar: bool = False) -> dict[str, list[str]]:
    """Copia secretos KEY__SLUG (y globales para gdlscene) del entorno a brand_secrets."""
    res: dict[str, list[str]] = {}
    for a in db.list_accounts(cx, solo_activas=True):
        slug, importadas = a["slug"], []
        ya = set(ss.leer_todos(cx, a["id"]))
        for clave in ss.CLAVES:
            val = environ.get(f"{clave}__{slug.upper()}")
            if val is None and slug == "gdlscene":
                val = environ.get(clave)
            if not val or (clave in ya and not forzar):
                continue
            ss.guardar(cx, a["id"], clave, val)
            importadas.append(clave)
        res[slug] = importadas
    return res


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--nueva-master-key", action="store_true")
    p.add_argument("--admin", metavar="EMAIL")
    p.add_argument("--nombre")
    p.add_argument("--importar-env", action="store_true")
    p.add_argument("--forzar", action="store_true")
    a = p.parse_args(argv)
    if a.nueva_master_key:
        print(nueva_master_key())
        return 0
    cx = db.connect()
    try:
        db.init_db(cx)
        if a.admin:
            uid, tok = asegurar_admin(cx, a.admin, a.nombre)
            base = os.getenv("API_URL_PUBLICA", "http://localhost:8100")
            print(f"Admin listo (id={uid}). Entra con:\n  {base}/auth/callback?token={tok}")
        if a.importar_env:
            if not ss.habilitado():
                print("Falta INSTAGOD_MASTER_KEY en .env", file=sys.stderr)
                return 2
            for slug, claves in importar_env(cx, os.environ, forzar=a.forzar).items():
                print(f"{slug}: {', '.join(claves) or '(nada nuevo)'}")
        if not (a.admin or a.importar_env):
            p.print_help()
    finally:
        cx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: `.env.example`** (append)

```
# ---------- Portal de colaboradores (api/) ----------
# Llave Fernet para cifrar secretos por marca en DB (python -m api.bootstrap --nueva-master-key)
INSTAGOD_MASTER_KEY=
# URL pública del front (redirect tras login) y de la API (para el CLI)
APP_URL=http://localhost:3000
API_URL_PUBLICA=http://localhost:8100
# Correo de magic links (Resend). Vacío en dev → la URL se imprime en el log.
RESEND_API_KEY=
MAIL_FROM=instagod <no-reply@tudominio.com>
SESSION_DAYS=30
ENV=dev
# COOKIE_DOMAIN=.tudominio.com
```

- [ ] **Step 5: `docs/api_portal.md`** (breve)

```markdown
# API del portal (Fase 1)

Correr: `.venv/bin/uvicorn api.app:app --port 8100 --reload` → docs en `/docs`.

Primer uso:
1. `python -m api.bootstrap --nueva-master-key` → pegar en `.env` como `INSTAGOD_MASTER_KEY`.
2. `python -m api.bootstrap --admin tu@email.com` → abre la URL impresa (crea la sesión).
3. `python -m api.bootstrap --importar-env` → copia `KEY__SLUG` del `.env` a `brand_secrets`.

Endpoints: `POST /auth/magic-link`, `GET /auth/callback`, `POST /auth/logout`, `GET /auth/verify`,
`GET /me`, `GET/POST /users...` (admin), `GET/POST /brands`, `GET/PATCH /brands/{slug}`,
`GET/PUT/DELETE /brands/{slug}/secrets[/{clave}]`, `POST /brands/{slug}/{telegram|instagram|llm}/test`,
`GET /health`. Errores: `{error, detalle, campo}`.

Precedencia de credenciales por marca: DB (`brand_secrets`) → `.env` con sufijo `__SLUG` →
`.env` global (solo gdlscene). El daemon detecta cambios de token/chat cada 60 s.
```

- [ ] **Step 6: Smoke manual de arranque**

Run: `.venv/bin/python -c "from api.app import app; print([r.path for r in app.routes][:30])"` → lista de rutas sin error.
Run: `.venv/bin/python -m pytest -q` (suite completa) y `.venv/bin/ruff check .` → verde.

- [ ] **Step 7: Commit**

```bash
git pull --rebase
git add api/bootstrap.py tests/test_bootstrap.py .env.example docs/api_portal.md
git commit -m "feat(api): bootstrap CLI (master key, admin, importar secretos de env) + docs"
```

---

## Auto-revisión del plan

- **Cobertura del spec (Fase 1 = §1 estructura mínima, §2, §3, §8, §9):** §2 usuarios/roles/magic link/sesión → Tasks 4-6; §3 secretos/Fernet/precedencia/pruebas/daemon recarga/importar env → Tasks 2, 3, 8, 9, 10, 11; §8 errores JSON/403 por marca/rate limit → Tasks 5, 7, 8; §9 tests de auth, secretos, aislamiento, daemon → en cada tarea. `/legacy` → sustituido por `/auth/verify` (ajuste declarado). Cola/jobs/publisher/fuentes/presets/front/deploy → Fases 2-5.
- **Placeholders:** ninguno; todo el código está escrito.
- **Consistencia de nombres:** `api.deps.COOKIE == "instagod_session"` usado por `auth.py` y el fixture; `marca_para(slug, cx, user, minimo)` mismo orden en brands/secrets/pruebas; `secrets_store.CLAVES/guardar/borrar/leer/leer_todos/listar_meta/creds_de_slug/habilitado/version_marcas` iguales en Tasks 2, 3, 8, 11; `users.crear_sesion/usuario_de_sesion/crear_magic_link/consumir_magic_link/marcas_de/rol_en/asignar_marca/quitar_marca/listar/por_id/por_email/cerrar_sesion/cerrar_sesiones_de` iguales en Tasks 4-6, 11; `correr(apps, *, esperar=None) -> str` en Task 10 y sus tests.
- **Riesgo conocido:** `_creds_db` abre una conexión SQLite por llamada a `account_creds`; suficiente para v1 (llamadas esporádicas). Si el publisher de la Fase 2 lo llama en loop apretado, cachear 30 s ahí.
