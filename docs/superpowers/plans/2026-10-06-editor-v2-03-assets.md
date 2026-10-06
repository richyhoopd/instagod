# Editor v2 · Plan 3: assets (fotos, video, quitar fondo, tipografías)

> **Para agentes:** SUB-SKILL REQUERIDA: usa `superpowers:subagent-driven-development` (recomendado) o `superpowers:executing-plans` para ejecutar este plan task por task. Los pasos usan casillas (`- [ ]`) para el seguimiento.

**Goal:** que cada marca tenga su biblioteca de assets (`brand_assets`), busque foto y video en proveedores gratis que ella misma configura, importe al disco de la marca con su atribución, quite fondos con rembg y meta cualquier asset al lienzo v2 desde una pestaña del editor. Además puede instalar tipografías de Fontsource.

**Architecture:** el paquete nuevo `src/assets/` vive en paralelo a `src/image_sources.py`, que no se toca porque el slideshow v1 sigue usándolo. Hay un proveedor por archivo, todos con la misma clase base y un registro común (`PROVEEDORES`). `buscar.py` reparte la consulta entre las fuentes activas de la marca (`brand_sources`, kind `imagen` o `video`) y registra los errores en `ultimo_error` sin cortar la búsqueda. `biblioteca.py` es la única puerta al disco:
- descarga solo por https y a hosts públicos;
- valida magic bytes y aplica un tope de tamaño;
- deduplica por sha256.

El recorte es un job (`asset.recorte`) porque BiRefNet tarda segundos. El router `api/routers/assets.py` expone buscar, listar, importar, subir, descartar, recortar y Fontsource. El frontend agrega fuentes de video y tipografías en Ajustes, más la pestaña «Assets» en el editor.

**Tech Stack:** Python 3.12, FastAPI, SQLite, requests, Pillow, rembg (`birefnet-general`, CPU), Next 16 + React 19 + TanStack Query, vitest (lo instala el plan 2).

**Spec:** `docs/superpowers/specs/2026-10-06-editor-escena-v2-design.md` (§1 capa imagen, §4 assets, §6 riesgos). Contrato entre planes: `docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md`.

## Global Constraints

- **Sin red en las pruebas.** Los proveedores se prueban con respuestas grabadas en `tests/fixtures/assets/*.json`, monkeypatcheando `src.assets.proveedores.base.get_json` / `post_json`. Lo que toca red o el modelo real lleva `@pytest.mark.lento`.
- **Ninguna API key sale del servidor.** No se escribe en `brand_sources.ultimo_error`, ni en `avisos`, ni en logs, ni en respuestas HTTP.
- **`ia_imagen` cuesta dinero.** Solo corre si la llamada lo pide por nombre **y** la marca tiene una fila activa con ese proveedor. Nunca entra en la búsqueda por omisión.
- **No se toca** `src/image_sources.py`, `src/plantillas/layout.py` ni el endpoint `GET /brands/{slug}/files/assets/{archivo}` (es del plan 1).
- Toda columna o tabla nueva va en `src/schema.sql` **y** en la allowlist `TABLES` de `src/db.py`.
- Pinterest sigue en el backend, porque el slideshow v1 lo usa, pero la UI ya no lo ofrece.
- Un commit por task, solo local en `feat/editor-v2`. Nada de push ni de deploy a la VM.
- Comandos, siempre desde la raíz del worktree `/Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2`:
  - Pytest: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest`
  - Ruff: `/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/`
  - Frontend: `cd frontend && pnpm lint && pnpm tsc --noEmit`

## Review Focus

1. **Las llaves no se filtran.** `ultimo_error` y `avisos` nunca contienen una API key, ni en el texto de la excepción ni en una URL con `key=`. Prueba: `test_error_de_proveedor_no_filtra_llave` (Task 10).
2. **Descarga cerrada.** Solo https, solo hosts con IP global, redirects re-validados (sin rebote a 127.0.0.1 ni a 169.254.169.254), magic bytes obligatorios y tope por tipo. Pruebas: `test_descarga_*` (Task 11).
3. **`ia_imagen` nunca se gasta solo.** No entra por omisión aunque haya una fila activa, y pedirlo sin fila activa no llama a fal. Prueba: `test_ia_imagen_solo_explicito_y_activo` (Task 10).
4. **Aislamiento entre marcas.** Una marca no puede listar, importar, descartar ni recortar assets de otra. Pruebas: `test_recorte_rechaza_asset_de_otra_marca` (Task 12) y `test_api_assets_aislado_por_marca` (Task 14).
5. **La migración del CHECK de `brand_sources.kind`.** Conserva ids y filas, es idempotente y deja insertar `'video'`. Prueba: `test_migracion_kind_video_conserva_filas` (Task 1).

---

### Task 1: esquema `brand_assets` y `brand_sources.kind = 'video'`

**Files:**
- Modify: `src/schema.sql` (DDL de `brand_sources` + tabla nueva `brand_assets`)
- Modify: `src/db.py` (allowlist `TABLES`, `_migrar_check_kind_sources`, llamada en `init_db`)
- Test: `tests/test_assets_schema.py`

**Interfaces:**
```python
# src/db.py
_BRAND_SOURCES_REBUILD_COLS: tuple[str, ...]
_BRAND_SOURCES_REBUILD_DDL: str
def _migrar_check_kind_sources(cx: sqlite3.Connection) -> None   # idempotente
```

- [ ] **Paso 1: escribir la prueba que falla**

`tests/test_assets_schema.py`:
```python
"""brand_assets nueva y brand_sources.kind acepta 'video' (migración del CHECK)."""
from __future__ import annotations

import sqlite3

import pytest

from src import db

_DDL_VIEJO = """
CREATE TABLE brand_sources (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL,
    provider     TEXT    NOT NULL,
    config_json  TEXT    NOT NULL DEFAULT '{}',
    activa       INTEGER NOT NULL DEFAULT 1,
    orden        INTEGER NOT NULL DEFAULT 0,
    ultimo_run   TEXT,
    ultimo_error TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (kind IN ('imagen','info')),
    CHECK (activa IN (0,1))
)
"""


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx, slug="m1") -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}", nombre=slug, ciudad="GDL")


def test_brand_assets_existe_y_dedup_por_sha(cx) -> None:
    aid = _cuenta(cx)
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="a.jpg",
              sha="s1", proveedor="pexels")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="b.jpg",
                  sha="s1", proveedor="pexels")
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_assets", account_id=aid, tipo="audio", archivo="c.mp3",
                  sha="s2", proveedor="pexels")


def test_brand_sources_acepta_video_en_db_nueva(cx) -> None:
    aid = _cuenta(cx)
    sid = db.insert(cx, "brand_sources", account_id=aid, kind="video", provider="pexels")
    assert db.get(cx, "brand_sources", sid)["kind"] == "video"


def test_migracion_kind_video_conserva_filas(tmp_path) -> None:
    c = db.connect(tmp_path / "v.db")
    db.init_db(c)
    aid = _cuenta(c)
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("DROP TABLE brand_sources")
    c.execute(_DDL_VIEJO)
    c.execute("CREATE INDEX idx_sources_account ON brand_sources(account_id)")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("INSERT INTO brand_sources (id, account_id, kind, provider, orden, ultimo_error) "
              "VALUES (7, ?, 'imagen', 'pexels', 2, 'x'), (9, ?, 'info', 'rss', 0, NULL)",
              (aid, aid))
    c.commit()
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO brand_sources (account_id, kind, provider) VALUES (?, 'video', 'p')",
                  (aid,))
    c.rollback()

    db.init_db(c)
    db.init_db(c)  # idempotente: la segunda corrida es no-op

    filas = [dict(f) for f in c.execute(
        "SELECT id, kind, provider, orden, ultimo_error FROM brand_sources ORDER BY id")]
    assert filas == [
        {"id": 7, "kind": "imagen", "provider": "pexels", "orden": 2, "ultimo_error": "x"},
        {"id": 9, "kind": "info", "provider": "rss", "orden": 0, "ultimo_error": None},
    ]
    nuevo = db.insert(c, "brand_sources", account_id=aid, kind="video", provider="pixabay")
    assert nuevo == 10
    sql = c.execute("SELECT sql FROM sqlite_master WHERE name='brand_sources'").fetchone()[0]
    assert "'video'" in sql
    idx = c.execute("SELECT name FROM sqlite_master WHERE type='index' "
                    "AND tbl_name='brand_sources'").fetchall()
    assert ("idx_sources_account",) in [tuple(i) for i in idx]
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()
```

- [ ] **Paso 2: correrla y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_schema.py -q`
Expected: FAIL. Los 3 tests fallan: `brand_assets` no está en `TABLES` (ValueError del allowlist) y el CHECK rechaza `'video'`.

- [ ] **Paso 3: esquema**

En `src/schema.sql`, dentro del `CREATE TABLE IF NOT EXISTS brand_sources`, cambiar la línea del CHECK:
```sql
    CHECK (kind IN ('imagen','info','video')),
```
Al final de `src/schema.sql`, agregar:
```sql
-- Biblioteca de assets por marca (editor v2, plan 3). `archivo` es el nombre
-- dentro de data/brands/<slug>/assets/. Dedup por (account_id, sha).
CREATE TABLE IF NOT EXISTS brand_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    tipo            TEXT    NOT NULL,
    archivo         TEXT    NOT NULL,
    sha             TEXT    NOT NULL,
    proveedor       TEXT    NOT NULL,
    autor           TEXT,
    licencia        TEXT,
    url_origen      TEXT,
    ig_handle       TEXT,
    source_post_id  TEXT,
    ancho           INTEGER,
    alto            INTEGER,
    tags_json       TEXT,
    recorte_archivo TEXT,
    usada           INTEGER NOT NULL DEFAULT 0,
    descartada      INTEGER NOT NULL DEFAULT 0,
    creado_en       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, sha),
    CHECK (tipo IN ('imagen','video')),
    CHECK (usada IN (0,1)),
    CHECK (descartada IN (0,1))
);
CREATE INDEX IF NOT EXISTS idx_assets_account ON brand_assets(account_id, tipo);
```

- [ ] **Paso 4: allowlist y migración en `src/db.py`**

En `TABLES`, junto a `"brand_fonts"`:
```python
    "brand_assets": {"account_id", "tipo", "archivo", "sha", "proveedor", "autor", "licencia",
                     "url_origen", "ig_handle", "source_post_id", "ancho", "alto", "tags_json",
                     "recorte_archivo", "usada", "descartada"},
```
Debajo de `_migrar_check_tipo_queue`:
```python
_BRAND_SOURCES_REBUILD_COLS = ("id", "account_id", "kind", "provider", "config_json", "activa",
                               "orden", "ultimo_run", "ultimo_error", "created_at")

_BRAND_SOURCES_REBUILD_DDL = """
CREATE TABLE brand_sources_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    kind         TEXT    NOT NULL,
    provider     TEXT    NOT NULL,
    config_json  TEXT    NOT NULL DEFAULT '{}',
    activa       INTEGER NOT NULL DEFAULT 1,
    orden        INTEGER NOT NULL DEFAULT 0,
    ultimo_run   TEXT,
    ultimo_error TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (kind IN ('imagen','info','video')),
    CHECK (activa IN (0,1))
)
"""


def _migrar_check_kind_sources(cx: sqlite3.Connection) -> None:
    """Ensancha CHECK(kind) de brand_sources para aceptar 'video' (editor v2).

    Mismo procedimiento que `_migrar_check_tipo_queue`: reconstruir la tabla con
    foreign_keys=OFF, copiar, renombrar, recrear el índice y validar las FK antes
    del COMMIT. Idempotente: si el SQL ya trae 'video' es no-op.
    """
    row = cx.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='brand_sources'"
    ).fetchone()
    if row is None or "'video'" in row[0]:
        return
    viejas = {r[1] for r in cx.execute("PRAGMA table_info(brand_sources)")}
    huerfanas = viejas - set(_BRAND_SOURCES_REBUILD_COLS)
    if huerfanas:
        raise RuntimeError(f"brand_sources tiene columnas que el rebuild perdería: "
                           f"{sorted(huerfanas)}; agrégalas a _BRAND_SOURCES_REBUILD_COLS")
    col_list = ", ".join(c for c in _BRAND_SOURCES_REBUILD_COLS if c in viejas)

    cx.commit()  # PRAGMA foreign_keys no surte efecto dentro de una transacción
    cx.execute("PRAGMA foreign_keys=OFF")
    try:
        cx.execute("BEGIN")
        cx.execute(_BRAND_SOURCES_REBUILD_DDL)
        cx.execute(f"INSERT INTO brand_sources_new ({col_list}) "
                   f"SELECT {col_list} FROM brand_sources")
        cx.execute("DROP TABLE brand_sources")
        cx.execute("ALTER TABLE brand_sources_new RENAME TO brand_sources")
        cx.execute("CREATE INDEX IF NOT EXISTS idx_sources_account ON brand_sources(account_id)")
        violaciones = cx.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            raise RuntimeError(f"foreign_key_check falló tras el rebuild de "
                               f"brand_sources: {[tuple(v) for v in violaciones]}")
        cx.execute("COMMIT")
    except BaseException:
        try:
            cx.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise
    finally:
        cx.execute("PRAGMA foreign_keys=ON")
```
En `init_db`, justo después de `_migrar_check_tipo_queue(cx)`:
```python
    _migrar_check_kind_sources(cx)
```
⚠️ Hay que revisar si `_migrar_check_tipo_queue` hace `cx.commit()` antes del PRAGMA. Si no lo hace, igual se deja el `cx.commit()` aquí: `executescript` ya hizo commit y el `commit()` sin transacción abierta es un no-op.

- [ ] **Paso 5: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_schema.py tests/test_db.py -q`
Expected: PASS. Si `tests/test_db.py` no existe, correr solo el primero y `tests/ -q -x -k "db or fuentes or sources"`.

- [ ] **Paso 6: commit**
```bash
git add src/schema.sql src/db.py tests/test_assets_schema.py
git commit -m "assets: tabla brand_assets y kind 'video' en brand_sources

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: paquete `src/assets/`, clase base de proveedor, `carpeta` y credenciales nuevas

**Files:**
- Create: `src/assets/__init__.py`, `src/assets/proveedores/__init__.py`, `src/assets/proveedores/base.py`, `src/assets/proveedores/carpeta.py`
- Modify: `config.py` (`_ACCOUNT_CRED_KEYS`), `src/secrets_store.py` (`CLAVES`), `tests/conftest.py` (delenv de `api_cliente`)
- Test: `tests/test_assets_base.py`

**Interfaces:**
```python
# src/assets/__init__.py
TIPOS = ("imagen", "video")
BRANDS_DIR: Path     # config.BASE_DIR / "data" / "brands"  (monkeypatcheable)
CACHE_DIR: Path      # config.BASE_DIR / "data" / "cache" / "assets"
@dataclass
class Candidata: ...  # exactamente el contrato del índice + a_dict()

# src/assets/proveedores/base.py
TIMEOUT = 15
class SinLlave(Exception): ...           # args[0] = nombre de la variable que falta
def get_json(url, *, params=None, headers=None) -> dict
def post_json(url, *, json_body, headers=None) -> dict
def enviar(metodo, url, *, headers=None) -> None    # tracking (Unsplash, Coverr)
class Proveedor:
    nombre: str; tipos: tuple[str, ...]; llave: str | None
    hosts: tuple[str, ...] | None        # sufijos permitidos al descargar; None = cualquier host público
    de_pago: bool
    def __init__(self, *, cx=None, account_id=None, slug="", creds=None, config=None)
    def clave(self) -> str               # SinLlave si falta
    def buscar(self, q, *, tipo="imagen", n=20) -> list[Candidata]
    def registrar_descarga(self, cand) -> None

# src/assets/proveedores/__init__.py
PROVEEDORES: dict[str, type[Proveedor]]
```

- [ ] **Paso 1: escribir la prueba que falla**

`tests/test_assets_base.py`:
```python
"""Paquete src/assets: Candidata, registro de proveedores, carpeta y llaves nuevas."""
from __future__ import annotations

import pytest

import config
from src import assets, db, secrets_store
from src.assets import Candidata
from src.assets.proveedores import PROVEEDORES, base
from src.assets.proveedores.carpeta import Carpeta

NUEVAS = ("PIXABAY_API_KEY", "COVERR_API_KEY", "GIPHY_API_KEY", "FAL_KEY")


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def test_candidata_a_dict() -> None:
    c = Candidata(proveedor="pexels", id_origen="1", tipo="imagen", url="https://x/a.jpg",
                  preview_url="https://x/s.jpg", ancho=10, alto=20, autor="Ana",
                  licencia="Pexels License", url_origen="https://pexels.com/1")
    d = c.a_dict()
    assert d["ig_handle"] is None and d["source_post_id"] is None
    assert Candidata(**d) == c


def test_llaves_nuevas_registradas() -> None:
    for k in NUEVAS:
        assert k in config._ACCOUNT_CRED_KEYS
        assert k in secrets_store.CLAVES


def test_registro_tiene_carpeta_y_clave_falta() -> None:
    assert PROVEEDORES["carpeta"] is Carpeta
    p = base.Proveedor(creds={})
    assert p.clave() == ""          # llave None: no requiere
    p.llave = "PEXELS_API_KEY"
    with pytest.raises(base.SinLlave) as e:
        p.clave()
    assert e.value.args[0] == "PEXELS_API_KEY"


def test_carpeta_busca_en_biblioteca_y_fotos(cx, tmp_path) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="aa.jpg", sha="1",
              proveedor="pexels", tags_json='["playa","atardecer"]', ancho=10, alto=10)
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="bb.jpg", sha="2",
              proveedor="pexels", tags_json='["ciudad"]')
    db.insert(cx, "brand_assets", account_id=aid, tipo="imagen", archivo="cc.jpg", sha="3",
              proveedor="pexels", tags_json='["playa"]', descartada=1)
    fotos = tmp_path / "brands" / "m1" / "fotos"
    fotos.mkdir(parents=True)
    (fotos / "playa-gdl.jpg").write_bytes(b"\xff\xd8\xff")
    (fotos / "nota.txt").write_text("x")

    p = Carpeta(cx=cx, account_id=aid, slug="m1", creds={}, config={})
    res = p.buscar("playa", tipo="imagen", n=10)
    assert [c.url for c in res] == ["local:assets/aa.jpg", "local:fotos/playa-gdl.jpg"]
    assert res[0].preview_url == "/brands/m1/files/assets/aa.jpg"
    assert res[1].preview_url == "/brands/m1/files/fotos/playa-gdl.jpg"
    assert p.buscar("playa", tipo="video", n=10) == []
```

- [ ] **Paso 2: correrla y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_base.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.assets'`.

- [ ] **Paso 3: implementar**

`src/assets/__init__.py`:
```python
"""Biblioteca de assets por marca (editor v2): búsqueda en proveedores, import al
disco de la marca, recorte de fondo. Paralelo a src/image_sources.py (slideshow v1),
que no se toca."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import config

TIPOS = ("imagen", "video")
# Módulo-nivel para que las pruebas lo monkeypatcheen (mismo patrón que perfil.BRANDS_DIR).
# Los submódulos lo leen como `assets.BRANDS_DIR` en tiempo de llamada, nunca lo copian.
BRANDS_DIR = config.BASE_DIR / "data" / "brands"
CACHE_DIR = config.BASE_DIR / "data" / "cache" / "assets"


@dataclass
class Candidata:
    proveedor: str
    id_origen: str
    tipo: str          # "imagen" | "video"
    url: str
    preview_url: str
    ancho: int | None
    alto: int | None
    autor: str | None
    licencia: str | None
    url_origen: str | None
    ig_handle: str | None = None
    source_post_id: str | None = None

    def a_dict(self) -> dict[str, Any]:
        return asdict(self)
```

`src/assets/proveedores/base.py`:
```python
"""Clase base de proveedor y HTTP común. Los proveedores llaman `base.get_json`
(no `requests` directo) para que las pruebas lo sustituyan con respuestas grabadas."""
from __future__ import annotations

from typing import Any

import requests

from src.assets import Candidata

TIMEOUT = 15
UA = "instagod/2 (+editor de assets)"


class SinLlave(Exception):
    """Falta la API key del proveedor. args[0] = nombre de la variable."""


def get_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> Any:
    r = requests.get(url, params=params, headers={"User-Agent": UA, **(headers or {})},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def post_json(url: str, *, json_body: dict, headers: dict | None = None) -> Any:
    r = requests.post(url, json=json_body, headers={"User-Agent": UA, **(headers or {})},
                      timeout=TIMEOUT * 4)
    r.raise_for_status()
    return r.json()


def enviar(metodo: str, url: str, *, headers: dict | None = None) -> None:
    """Pings de tracking (descarga de Unsplash, stats de Coverr). Sin cuerpo."""
    r = requests.request(metodo, url, headers={"User-Agent": UA, **(headers or {})},
                         timeout=TIMEOUT)
    r.raise_for_status()


class Proveedor:
    nombre = ""
    tipos: tuple[str, ...] = ("imagen",)
    llave: str | None = None
    hosts: tuple[str, ...] | None = None
    de_pago = False

    def __init__(self, *, cx=None, account_id: int | None = None, slug: str = "",
                 creds: dict | None = None, config: dict | None = None) -> None:
        self.cx = cx
        self.account_id = account_id
        self.slug = slug
        self.creds = creds or {}
        self.config = config or {}

    def clave(self) -> str:
        if self.llave is None:
            return ""
        valor = self.creds.get(self.llave)
        if not valor:
            raise SinLlave(self.llave)
        return valor

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        raise NotImplementedError

    def registrar_descarga(self, cand: Candidata) -> None:
        return None
```

`src/assets/proveedores/carpeta.py`:
```python
"""Lo que la marca ya tiene: su biblioteca (brand_assets) y la carpeta fotos/ v1."""
from __future__ import annotations

import re

from src import assets, db
from src.assets import Candidata
from src.assets.proveedores.base import Proveedor

_EXT_FOTO = {".jpg", ".jpeg", ".png", ".webp"}
_NOMBRE_FOTO_RE = re.compile(r"^[a-z0-9_.-]+\Z")


def _tokens(q: str) -> list[str]:
    return [t for t in re.findall(r"\w+", q.lower()) if len(t) > 1]


class Carpeta(Proveedor):
    nombre = "carpeta"
    tipos = ("imagen", "video")

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        toks = _tokens(q)
        filas = db.rows(self.cx, "SELECT * FROM brand_assets WHERE account_id = ? AND tipo = ? "
                                 "AND descartada = 0 ORDER BY id DESC LIMIT 500",
                        (self.account_id, tipo))
        puntuadas = []
        for f in filas:
            texto = " ".join([f["archivo"], f["tags_json"] or "", f["autor"] or ""]).lower()
            puntos = sum(t in texto for t in toks)
            if puntos or not toks:
                puntuadas.append((puntos, f))
        puntuadas.sort(key=lambda p: -p[0])  # sort estable: empate conserva id DESC
        out = [Candidata(proveedor="carpeta", id_origen=str(f["id"]), tipo=tipo,
                         url=f"local:assets/{f['archivo']}",
                         preview_url=f"/brands/{self.slug}/files/assets/{f['archivo']}",
                         ancho=f["ancho"], alto=f["alto"], autor=f["autor"],
                         licencia=f["licencia"], url_origen=f["url_origen"],
                         ig_handle=f["ig_handle"], source_post_id=f["source_post_id"])
               for _, f in puntuadas]
        if tipo == "imagen":
            carpeta = assets.BRANDS_DIR / self.slug / "fotos"
            if carpeta.is_dir():
                for p in sorted(carpeta.iterdir()):
                    if (p.suffix.lower() not in _EXT_FOTO or not _NOMBRE_FOTO_RE.match(p.name)
                            or (toks and not any(t in p.name.lower() for t in toks))):
                        continue
                    out.append(Candidata(
                        proveedor="carpeta", id_origen=p.name, tipo="imagen",
                        url=f"local:fotos/{p.name}",
                        preview_url=f"/brands/{self.slug}/files/fotos/{p.name}",
                        ancho=None, alto=None, autor=None, licencia="propia", url_origen=None))
        return out[:n]
```

`src/assets/proveedores/__init__.py`:
```python
"""Registro de proveedores de assets. El plan 5 agrega `ig_seguidos` aquí."""
from __future__ import annotations

from src.assets.proveedores.base import Proveedor
from src.assets.proveedores.carpeta import Carpeta

PROVEEDORES: dict[str, type[Proveedor]] = {c.nombre: c for c in (Carpeta,)}
```

En `config.py`, la tupla `_ACCOUNT_CRED_KEYS` cierra así:
```python
                      "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY",
                      # Editor v2 (plan 3): assets. FAL_KEY es de pago (ia_imagen).
                      "PIXABAY_API_KEY", "COVERR_API_KEY", "GIPHY_API_KEY", "FAL_KEY")
```
En `src/secrets_store.py`, agregar al final de la tupla `CLAVES` (línea 18): `"PIXABAY_API_KEY", "COVERR_API_KEY", "GIPHY_API_KEY", "FAL_KEY"`.
En `tests/conftest.py`, línea 42, la tupla de `delenv` cierra así:
```python
                "PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "NEWSAPI_KEY",
                "PIXABAY_API_KEY", "COVERR_API_KEY", "GIPHY_API_KEY", "FAL_KEY"):
```

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_base.py tests/ -q -k "assets_base or secrets"`
Expected: PASS. `test_secrets*` compara `set(meta) == set(ss.CLAVES)`, así que sigue verde.

- [ ] **Paso 5: commit**
```bash
git add src/assets config.py src/secrets_store.py tests/conftest.py tests/test_assets_base.py
git commit -m "assets: paquete src/assets, proveedor carpeta y llaves Pixabay/Coverr/GIPHY/fal

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: proveedor Unsplash

**Files:**
- Create: `src/assets/proveedores/unsplash.py`, `tests/fixtures/assets/unsplash_search.json`
- Modify: `src/assets/proveedores/__init__.py`
- Test: `tests/test_assets_proveedores.py` (archivo compartido por los Tasks 3 a 9)

**Interfaces:** `class Unsplash(Proveedor)`: `nombre="unsplash"`, `tipos=("imagen",)`, `llave="UNSPLASH_ACCESS_KEY"`, `hosts=("images.unsplash.com",)`.

- [ ] **Paso 1: fixture y prueba que falla**

`tests/fixtures/assets/unsplash_search.json`, con la forma de `GET /search/photos` (campos de la doc oficial, recortado):
```json
{"total": 2, "total_pages": 1, "results": [
  {"id": "abc123", "width": 4000, "height": 6000,
   "urls": {"raw": "https://images.unsplash.com/photo-1?ixid=r", "regular": "https://images.unsplash.com/photo-1?w=1080", "small": "https://images.unsplash.com/photo-1?w=400"},
   "links": {"html": "https://unsplash.com/photos/abc123", "download_location": "https://api.unsplash.com/photos/abc123/download?ixid=r"},
   "user": {"name": "Ana Pérez", "username": "anap"}},
  {"id": "sinurl", "width": 1, "height": 1, "urls": {}, "links": {}, "user": {}}
]}
```
`tests/test_assets_proveedores.py`:
```python
"""Proveedores de assets contra respuestas grabadas (sin red)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.assets.proveedores import PROVEEDORES, base

FIX = Path(__file__).parent / "fixtures" / "assets"


def _grabado(nombre: str):
    return json.loads((FIX / nombre).read_text())


@pytest.fixture()
def llamadas(monkeypatch):
    """Sustituye get_json/post_json/enviar; cada test pone la respuesta en `llamadas.resp`."""
    class R:
        resp: object = None
        hechas: list = []
    R.hechas = []

    def fake_get(url, *, params=None, headers=None):
        R.hechas.append(("GET", url, params or {}, headers or {}))
        return R.resp(url) if callable(R.resp) else R.resp

    def fake_post(url, *, json_body, headers=None):
        R.hechas.append(("POST", url, json_body, headers or {}))
        return R.resp(url) if callable(R.resp) else R.resp

    def fake_enviar(metodo, url, *, headers=None):
        R.hechas.append((metodo, url, {}, headers or {}))

    monkeypatch.setattr(base, "get_json", fake_get)
    monkeypatch.setattr(base, "post_json", fake_post)
    monkeypatch.setattr(base, "enviar", fake_enviar)
    return R


def _prov(nombre, creds=None, config=None):
    return PROVEEDORES[nombre](cx=None, account_id=1, slug="m1", creds=creds or {},
                               config=config or {})


def test_unsplash_mapea_y_registra_descarga(llamadas) -> None:
    llamadas.resp = _grabado("unsplash_search.json")
    p = _prov("unsplash", {"UNSPLASH_ACCESS_KEY": "UK"})
    res = p.buscar("playa", tipo="imagen", n=5)
    assert len(res) == 1
    c = res[0]
    assert (c.proveedor, c.id_origen, c.tipo) == ("unsplash", "abc123", "imagen")
    assert c.url == "https://images.unsplash.com/photo-1?w=1080"
    assert c.preview_url.endswith("w=400")
    assert (c.autor, c.licencia) == ("Ana Pérez", "Unsplash License")
    assert c.url_origen == "https://unsplash.com/photos/abc123"
    metodo, url, params, headers = llamadas.hechas[0]
    assert url == "https://api.unsplash.com/search/photos" and params["query"] == "playa"
    assert headers["Authorization"] == "Client-ID UK"
    assert p.buscar("playa", tipo="video", n=5) == []
    p.registrar_descarga(c)
    assert llamadas.hechas[-1][1] == "https://api.unsplash.com/photos/abc123/download"


def test_unsplash_sin_llave(llamadas) -> None:
    with pytest.raises(base.SinLlave):
        _prov("unsplash").buscar("x", tipo="imagen", n=5)
```

- [ ] **Paso 2: correrla y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: FAIL con `KeyError: 'unsplash'`.

- [ ] **Paso 3: implementar** `src/assets/proveedores/unsplash.py`:
```python
"""Unsplash: GET /search/photos. La guía de la API exige pegarle a
/photos/{id}/download cuando la foto se usa (registrar_descarga)."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_API = "https://api.unsplash.com"


class Unsplash(base.Proveedor):
    nombre = "unsplash"
    tipos = ("imagen",)
    llave = "UNSPLASH_ACCESS_KEY"
    hosts = ("images.unsplash.com",)

    def _headers(self) -> dict:
        return {"Authorization": f"Client-ID {self.clave()}", "Accept-Version": "v1"}

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo != "imagen":
            return []
        datos = base.get_json(f"{_API}/search/photos",
                              params={"query": q, "per_page": max(1, min(n, 30)),
                                      "content_filter": "high"},
                              headers=self._headers())
        out = []
        for r in datos.get("results", []):
            urls, user = r.get("urls") or {}, r.get("user") or {}
            if not urls.get("regular"):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(r["id"]), tipo="imagen",
                url=urls["regular"], preview_url=urls.get("small") or urls["regular"],
                ancho=r.get("width"), alto=r.get("height"), autor=user.get("name"),
                licencia="Unsplash License", url_origen=(r.get("links") or {}).get("html")))
        return out

    def registrar_descarga(self, cand: Candidata) -> None:
        base.get_json(f"{_API}/photos/{cand.id_origen}/download", headers=self._headers())
```
En `src/assets/proveedores/__init__.py`:
```python
from src.assets.proveedores.unsplash import Unsplash

PROVEEDORES: dict[str, type[Proveedor]] = {c.nombre: c for c in (Carpeta, Unsplash)}
```

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/proveedores tests/fixtures/assets/unsplash_search.json tests/test_assets_proveedores.py
git commit -m "assets: proveedor Unsplash con registro de descarga

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: proveedor Pexels (foto y video)

**Files:**
- Create: `src/assets/proveedores/pexels.py`, `tests/fixtures/assets/pexels_fotos.json`, `tests/fixtures/assets/pexels_videos.json`
- Modify: `src/assets/proveedores/__init__.py`, `tests/test_assets_proveedores.py`

**Interfaces:** `class Pexels(Proveedor)`: `tipos=("imagen","video")`, `llave="PEXELS_API_KEY"`, `hosts=("images.pexels.com","videos.pexels.com","player.vimeo.com")` ⚠️. Hoy Pexels sirve los videos desde `videos.pexels.com`, pero hay respuestas viejas con `player.vimeo.com`. No se verificó en vivo.

- [ ] **Paso 1: fixtures y prueba que falla**

`tests/fixtures/assets/pexels_fotos.json`:
```json
{"page": 1, "per_page": 2, "photos": [
  {"id": 101, "width": 3000, "height": 4000, "url": "https://www.pexels.com/photo/101/",
   "photographer": "Luis", "src": {"original": "https://images.pexels.com/photos/101/a.jpeg",
   "large2x": "https://images.pexels.com/photos/101/a.jpeg?w=1880", "medium": "https://images.pexels.com/photos/101/a.jpeg?h=350"}}
]}
```
`tests/fixtures/assets/pexels_videos.json`:
```json
{"page": 1, "videos": [
  {"id": 202, "width": 3840, "height": 2160, "url": "https://www.pexels.com/video/202/",
   "image": "https://images.pexels.com/videos/202/thumb.jpeg", "user": {"name": "Marta"},
   "video_files": [
     {"quality": "uhd", "file_type": "video/mp4", "width": 3840, "height": 2160, "link": "https://videos.pexels.com/video-files/202/uhd.mp4"},
     {"quality": "hd", "file_type": "video/mp4", "width": 1920, "height": 1080, "link": "https://videos.pexels.com/video-files/202/hd.mp4"},
     {"quality": "sd", "file_type": "video/mp4", "width": 640, "height": 360, "link": "https://videos.pexels.com/video-files/202/sd.mp4"}
   ]}
]}
```
Agregar a `tests/test_assets_proveedores.py`:
```python
def test_pexels_fotos(llamadas) -> None:
    llamadas.resp = _grabado("pexels_fotos.json")
    [c] = _prov("pexels", {"PEXELS_API_KEY": "PK"}).buscar("café", tipo="imagen", n=3)
    assert c.url.endswith("w=1880") and c.preview_url.endswith("h=350")
    assert (c.autor, c.ancho, c.alto, c.licencia) == ("Luis", 3000, 4000, "Pexels License")
    _, url, params, headers = llamadas.hechas[0]
    assert url == "https://api.pexels.com/v1/search" and headers["Authorization"] == "PK"


def test_pexels_video_elige_mp4_hasta_1920(llamadas) -> None:
    llamadas.resp = _grabado("pexels_videos.json")
    [c] = _prov("pexels", {"PEXELS_API_KEY": "PK"}).buscar("ciudad", tipo="video", n=3)
    assert c.tipo == "video" and c.url.endswith("/hd.mp4")
    assert (c.ancho, c.alto) == (1920, 1080)
    assert c.preview_url.endswith("thumb.jpeg")
    assert llamadas.hechas[0][1] == "https://api.pexels.com/videos/search"
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q -k pexels`
Expected: FAIL con `KeyError: 'pexels'`.

- [ ] **Paso 3: implementar** `src/assets/proveedores/pexels.py`:
```python
"""Pexels: fotos (/v1/search) y video (/videos/search). Auth: header Authorization con la key."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_LADO_MAX_VIDEO = 1920


def _mejor_archivo(archivos: list[dict]) -> dict | None:
    mp4 = [a for a in archivos if a.get("file_type") == "video/mp4" and a.get("link")]
    caben = [a for a in mp4 if max(a.get("width") or 0, a.get("height") or 0) <= _LADO_MAX_VIDEO]
    if caben:
        return max(caben, key=lambda a: (a.get("width") or 0) * (a.get("height") or 0))
    return min(mp4, key=lambda a: (a.get("width") or 0) * (a.get("height") or 0), default=None)


class Pexels(base.Proveedor):
    nombre = "pexels"
    tipos = ("imagen", "video")
    llave = "PEXELS_API_KEY"
    hosts = ("images.pexels.com", "videos.pexels.com", "player.vimeo.com")

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        headers = {"Authorization": self.clave()}
        params = {"query": q, "per_page": max(1, min(n, 80))}
        if tipo == "video":
            datos = base.get_json("https://api.pexels.com/videos/search", params=params,
                                  headers=headers)
            out = []
            for v in datos.get("videos", []):
                arch = _mejor_archivo(v.get("video_files") or [])
                if arch is None:
                    continue
                out.append(Candidata(
                    proveedor=self.nombre, id_origen=str(v["id"]), tipo="video",
                    url=arch["link"], preview_url=v.get("image") or "",
                    ancho=arch.get("width"), alto=arch.get("height"),
                    autor=(v.get("user") or {}).get("name"), licencia="Pexels License",
                    url_origen=v.get("url")))
            return out
        datos = base.get_json("https://api.pexels.com/v1/search", params=params, headers=headers)
        out = []
        for f in datos.get("photos", []):
            src = f.get("src") or {}
            url = src.get("large2x") or src.get("original")
            if not url:
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(f["id"]), tipo="imagen", url=url,
                preview_url=src.get("medium") or url, ancho=f.get("width"),
                alto=f.get("height"), autor=f.get("photographer"), licencia="Pexels License",
                url_origen=f.get("url")))
        return out
```
Registrar `Pexels` en `PROVEEDORES` (agregar el import y meterlo en la tupla).

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/proveedores tests/fixtures/assets/pexels_*.json tests/test_assets_proveedores.py
git commit -m "assets: proveedor Pexels de foto y video

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: proveedor Pixabay (foto y video, caché de 24 h)

**Files:**
- Create: `src/assets/proveedores/pixabay.py`, `tests/fixtures/assets/pixabay_fotos.json`, `tests/fixtures/assets/pixabay_videos.json`
- Modify: `src/assets/proveedores/__init__.py`, `tests/test_assets_proveedores.py`

**Interfaces:** `class Pixabay(Proveedor)`: `tipos=("imagen","video")`, `llave="PIXABAY_API_KEY"`, `hosts=("pixabay.com",)`. El sufijo cubre `cdn.pixabay.com`. La caché vive en `assets.CACHE_DIR / "pixabay" / <sha1>.json`, y el hash **no** incluye la key. La caché de 24 h la exige la API de Pixabay.

- [ ] **Paso 1: fixtures y prueba que falla**

`tests/fixtures/assets/pixabay_fotos.json`:
```json
{"total": 1, "totalHits": 1, "hits": [
  {"id": 303, "pageURL": "https://pixabay.com/photos/x-303/", "user": "pepe",
   "webformatURL": "https://pixabay.com/get/303_640.jpg", "largeImageURL": "https://pixabay.com/get/303_1280.jpg",
   "imageWidth": 5000, "imageHeight": 3000}
]}
```
`tests/fixtures/assets/pixabay_videos.json`:
```json
{"total": 1, "totalHits": 1, "hits": [
  {"id": 404, "pageURL": "https://pixabay.com/videos/y-404/", "user": "lola",
   "videos": {"large": {"url": "https://cdn.pixabay.com/video/404_large.mp4", "width": 3840, "height": 2160, "thumbnail": "https://cdn.pixabay.com/video/404_large.jpg"},
              "medium": {"url": "https://cdn.pixabay.com/video/404_medium.mp4", "width": 1920, "height": 1080, "thumbnail": "https://cdn.pixabay.com/video/404_medium.jpg"},
              "small": {"url": "https://cdn.pixabay.com/video/404_small.mp4", "width": 1280, "height": 720, "thumbnail": "https://cdn.pixabay.com/video/404_small.jpg"}}}
]}
```
Agregar a `tests/test_assets_proveedores.py`:
```python
def test_pixabay_fotos_y_cache_sin_llave_en_hash(llamadas, tmp_path, monkeypatch) -> None:
    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    llamadas.resp = _grabado("pixabay_fotos.json")
    [c] = _prov("pixabay", {"PIXABAY_API_KEY": "K1"}).buscar("sol", tipo="imagen", n=5)
    assert c.url.endswith("303_1280.jpg") and c.preview_url.endswith("303_640.jpg")
    assert (c.autor, c.licencia) == ("pepe", "Pixabay Content License")
    params = llamadas.hechas[0][2]
    assert params["key"] == "K1" and params["per_page"] >= 3
    # misma consulta con otra key: sale de caché, no hay segunda llamada
    _prov("pixabay", {"PIXABAY_API_KEY": "K2"}).buscar("sol", tipo="imagen", n=5)
    assert len(llamadas.hechas) == 1
    cacheados = list((tmp_path / "cache" / "pixabay").glob("*.json"))
    assert len(cacheados) == 1 and "K1" not in cacheados[0].read_text()


def test_pixabay_video_usa_medium(llamadas, tmp_path, monkeypatch) -> None:
    from src import assets
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    llamadas.resp = _grabado("pixabay_videos.json")
    [c] = _prov("pixabay", {"PIXABAY_API_KEY": "K"}).buscar("mar", tipo="video", n=5)
    assert c.url.endswith("404_medium.mp4") and (c.ancho, c.alto) == (1920, 1080)
    assert c.preview_url.endswith("404_medium.jpg")
    assert llamadas.hechas[0][1] == "https://pixabay.com/api/videos/"
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q -k pixabay`
Expected: FAIL con `KeyError: 'pixabay'`.

- [ ] **Paso 3: implementar** `src/assets/proveedores/pixabay.py`:
```python
"""Pixabay: fotos (/api/) y video (/api/videos/). La API exige cachear 24 h;
la caché se indexa SIN la key para no escribir secretos a disco."""
from __future__ import annotations

import hashlib
import json
import os
import time

from src import assets
from src.assets import Candidata
from src.assets.proveedores import base

_TTL = 24 * 3600


def _cacheado(url: str, params: dict, llave: str) -> dict:
    sin_llave = {k: v for k, v in params.items() if k != "key"}
    h = hashlib.sha1(json.dumps([url, sin_llave], sort_keys=True).encode()).hexdigest()
    ruta = assets.CACHE_DIR / "pixabay" / f"{h}.json"
    if ruta.is_file() and time.time() - ruta.stat().st_mtime < _TTL:
        return json.loads(ruta.read_text())
    datos = base.get_json(url, params={**sin_llave, "key": llave})
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".part")
    tmp.write_text(json.dumps(datos))
    os.replace(tmp, ruta)
    return datos


class Pixabay(base.Proveedor):
    nombre = "pixabay"
    tipos = ("imagen", "video")
    llave = "PIXABAY_API_KEY"
    hosts = ("pixabay.com",)

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        llave = self.clave()
        params = {"q": q[:100], "per_page": max(3, min(n, 200)), "safesearch": "true"}
        if tipo == "video":
            datos = _cacheado("https://pixabay.com/api/videos/", params, llave)
            out = []
            for h in datos.get("hits", []):
                v = (h.get("videos") or {})
                arch = v.get("medium") or v.get("large") or v.get("small")
                if not arch or not arch.get("url"):
                    continue
                out.append(Candidata(
                    proveedor=self.nombre, id_origen=str(h["id"]), tipo="video",
                    url=arch["url"], preview_url=arch.get("thumbnail") or "",
                    ancho=arch.get("width"), alto=arch.get("height"), autor=h.get("user"),
                    licencia="Pixabay Content License", url_origen=h.get("pageURL")))
            return out
        datos = _cacheado("https://pixabay.com/api/", {**params, "image_type": "photo"}, llave)
        out = []
        for h in datos.get("hits", []):
            url = h.get("largeImageURL") or h.get("webformatURL")
            if not url:
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(h["id"]), tipo="imagen", url=url,
                preview_url=h.get("webformatURL") or url, ancho=h.get("imageWidth"),
                alto=h.get("imageHeight"), autor=h.get("user"),
                licencia="Pixabay Content License", url_origen=h.get("pageURL")))
        return out
```
Registrar `Pixabay` en `PROVEEDORES`.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/proveedores tests/fixtures/assets/pixabay_*.json tests/test_assets_proveedores.py
git commit -m "assets: proveedor Pixabay con caché de 24 h sin la key en disco

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: proveedor Openverse (anónimo)

**Files:**
- Create: `src/assets/proveedores/openverse.py`, `tests/fixtures/assets/openverse.json`
- Modify: `src/assets/proveedores/__init__.py`, `tests/test_assets_proveedores.py`

**Interfaces:** `class Openverse(Proveedor)`: `tipos=("imagen",)`, `llave=None`, `hosts=None`. Las imágenes vienen de muchos hosts (Flickr, Wikimedia…), así que aquí manda el filtro de IP pública del Task 11. Se descartan las licencias `nd` (el editor recorta y modifica) y los resultados `mature`.

- [ ] **Paso 1: fixture y prueba que falla**

`tests/fixtures/assets/openverse.json`:
```json
{"result_count": 3, "results": [
  {"id": "uuid-1", "url": "https://live.staticflickr.com/1/a.jpg", "thumbnail": "https://api.openverse.org/v1/images/uuid-1/thumb/",
   "width": 1024, "height": 768, "creator": "Juan", "license": "by", "license_version": "4.0",
   "foreign_landing_url": "https://www.flickr.com/photos/x/1", "mature": false},
  {"id": "uuid-2", "url": "https://upload.wikimedia.org/b.jpg", "thumbnail": "https://api.openverse.org/v1/images/uuid-2/thumb/",
   "width": 800, "height": 600, "creator": "Eva", "license": "by-nd", "license_version": "2.0",
   "foreign_landing_url": "https://commons.wikimedia.org/b", "mature": false},
  {"id": "uuid-3", "url": "https://upload.wikimedia.org/c.jpg", "thumbnail": "https://api.openverse.org/v1/images/uuid-3/thumb/",
   "width": 800, "height": 600, "creator": "Ivo", "license": "cc0", "license_version": "1.0",
   "foreign_landing_url": "https://commons.wikimedia.org/c", "mature": true}
]}
```
Agregar a `tests/test_assets_proveedores.py`:
```python
def test_openverse_filtra_nd_y_mature(llamadas) -> None:
    llamadas.resp = _grabado("openverse.json")
    res = _prov("openverse").buscar("tacos", tipo="imagen", n=10)
    assert [c.id_origen for c in res] == ["uuid-1"]
    c = res[0]
    assert c.licencia == "CC BY 4.0" and c.autor == "Juan"
    assert c.url_origen == "https://www.flickr.com/photos/x/1"
    _, url, params, headers = llamadas.hechas[0]
    assert url == "https://api.openverse.org/v1/images/"
    assert params["license_type"] == "commercial" and "Authorization" not in headers
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q -k openverse`
Expected: FAIL con `KeyError: 'openverse'`.

- [ ] **Paso 3: implementar** `src/assets/proveedores/openverse.py`:
```python
"""Openverse (CC y dominio público), anónimo. license_type=commercial deja fuera NC;
aquí además se descarta ND porque el editor recorta y modifica la imagen."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base


def _licencia(lic: str, version: str | None) -> str:
    if lic in ("cc0", "pdm"):
        return "CC0" if lic == "cc0" else "Dominio público"
    return f"CC {lic.upper()} {version or ''}".strip()


class Openverse(base.Proveedor):
    nombre = "openverse"
    tipos = ("imagen",)

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo != "imagen":
            return []
        datos = base.get_json("https://api.openverse.org/v1/images/",
                              params={"q": q[:200], "page_size": max(1, min(n, 20)),
                                      "license_type": "commercial", "mature": "false"})
        out = []
        for r in datos.get("results", []):
            lic = (r.get("license") or "").lower()
            if not r.get("url") or r.get("mature") or "nd" in lic.split("-"):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(r["id"]), tipo="imagen", url=r["url"],
                preview_url=r.get("thumbnail") or r["url"], ancho=r.get("width"),
                alto=r.get("height"), autor=r.get("creator"),
                licencia=_licencia(lic, r.get("license_version")),
                url_origen=r.get("foreign_landing_url")))
        return out
```
Registrar `Openverse` en `PROVEEDORES`.

⚠️ No se verificó el límite anónimo de Openverse ni si `page_size` está topado en 20 sin token.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/proveedores tests/fixtures/assets/openverse.json tests/test_assets_proveedores.py
git commit -m "assets: proveedor Openverse anónimo, sin ND ni mature

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: proveedor Coverr (solo video)

**Files:**
- Create: `src/assets/proveedores/coverr.py`, `tests/fixtures/assets/coverr.json`
- Modify: `src/assets/proveedores/__init__.py`, `tests/test_assets_proveedores.py`

**Interfaces:** `class Coverr(Proveedor)`: `tipos=("video",)`, `llave="COVERR_API_KEY"`, `hosts=None`. `registrar_descarga` hace `PATCH /videos/{id}/stats/downloads`.

⚠️ El host del CDN de Coverr no se verificó, por eso `hosts=None` (solo filtro de IP pública). Los campos `hits[].urls.mp4` / `thumbnail` / `max_width` salen de la doc y no de una llamada real. Antes de cerrar este task, ejecutar a mano una sola llamada:
```bash
curl -s "https://api.coverr.co/videos?query=city&page_size=1&urls=true" -H "Authorization: Bearer $COVERR_API_KEY" | python3 -m json.tool | head -40
```
Si los nombres difieren, ajustar el fixture y el mapeo.

- [ ] **Paso 1: fixture y prueba que falla**

`tests/fixtures/assets/coverr.json`:
```json
{"page": 0, "pages": 1, "total": 1, "hits": [
  {"id": "cvr1", "title": "Night city", "max_width": 1920, "max_height": 1080,
   "thumbnail": "https://cdn.coverr.co/videos/cvr1/thumbnail.jpg",
   "urls": {"mp4": "https://cdn.coverr.co/videos/cvr1/1080p.mp4", "mp4_preview": "https://cdn.coverr.co/videos/cvr1/preview.mp4"}}
]}
```
Agregar a `tests/test_assets_proveedores.py`:
```python
def test_coverr_video_y_tracking(llamadas) -> None:
    llamadas.resp = _grabado("coverr.json")
    p = _prov("coverr", {"COVERR_API_KEY": "CK"})
    assert p.buscar("noche", tipo="imagen", n=5) == []
    [c] = p.buscar("noche", tipo="video", n=5)
    assert c.url.endswith("1080p.mp4") and (c.ancho, c.alto) == (1920, 1080)
    assert c.licencia == "Coverr License"
    _, url, params, headers = llamadas.hechas[0]
    assert url == "https://api.coverr.co/videos" and params["urls"] == "true"
    assert headers["Authorization"] == "Bearer CK"
    p.registrar_descarga(c)
    assert llamadas.hechas[-1][:2] == ("PATCH", "https://api.coverr.co/videos/cvr1/stats/downloads")
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q -k coverr`
Expected: FAIL con `KeyError: 'coverr'`.

- [ ] **Paso 3: implementar** `src/assets/proveedores/coverr.py`:
```python
"""Coverr: stock de video gratis. Bearer auth; registrar la descarga con PATCH stats."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_API = "https://api.coverr.co"


class Coverr(base.Proveedor):
    nombre = "coverr"
    tipos = ("video",)
    llave = "COVERR_API_KEY"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.clave()}"}

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo != "video":
            return []
        datos = base.get_json(f"{_API}/videos",
                              params={"query": q[:100], "page_size": max(1, min(n, 50)),
                                      "urls": "true"},
                              headers=self._headers())
        out = []
        for h in datos.get("hits", []):
            urls = h.get("urls") or {}
            if not urls.get("mp4"):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(h["id"]), tipo="video", url=urls["mp4"],
                preview_url=h.get("thumbnail") or urls.get("mp4_preview") or "",
                ancho=h.get("max_width"), alto=h.get("max_height"), autor=None,
                licencia="Coverr License", url_origen=f"https://coverr.co/videos/{h['id']}"))
        return out

    def registrar_descarga(self, cand: Candidata) -> None:
        base.enviar("PATCH", f"{_API}/videos/{cand.id_origen}/stats/downloads",
                    headers=self._headers())
```
Registrar `Coverr` en `PROVEEDORES`.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/proveedores tests/fixtures/assets/coverr.json tests/test_assets_proveedores.py
git commit -m "assets: proveedor Coverr de video con tracking de descarga

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: proveedor GIPHY (GIF y stickers)

**Files:**
- Create: `src/assets/proveedores/giphy.py`, `tests/fixtures/assets/giphy.json`
- Modify: `src/assets/proveedores/__init__.py`, `tests/test_assets_proveedores.py`

**Interfaces:** `class Giphy(Proveedor)`: `tipos=("imagen","video")`, `llave="GIPHY_API_KEY"`, `hosts=("giphy.com",)`. Con `tipo="imagen"` devuelve el `.gif` original; con `tipo="video"`, el `.mp4`. `config["stickers"]` truthy usa `/v1/stickers/search`. La UI muestra «Powered by GIPHY» (Task 17).

⚠️ Hay tres cosas sin verificar en GIPHY: la doc no cargó (DNS), los nombres `images.original.{url,mp4,width,height}` son los conocidos de la API v1, y el límite de la beta key tampoco se confirmó.

- [ ] **Paso 1: fixture y prueba que falla**

`tests/fixtures/assets/giphy.json`:
```json
{"data": [
  {"id": "g1", "url": "https://giphy.com/gifs/g1", "username": "estudio",
   "images": {"original": {"url": "https://media2.giphy.com/media/g1/giphy.gif", "mp4": "https://media2.giphy.com/media/g1/giphy.mp4", "width": "480", "height": "270"},
              "fixed_width": {"url": "https://media2.giphy.com/media/g1/200w.gif"}}}
], "pagination": {"count": 1}}
```
Agregar a `tests/test_assets_proveedores.py`:
```python
def test_giphy_gif_mp4_y_stickers(llamadas) -> None:
    llamadas.resp = _grabado("giphy.json")
    [g] = _prov("giphy", {"GIPHY_API_KEY": "GK"}).buscar("wow", tipo="imagen", n=5)
    assert g.url.endswith("giphy.gif") and (g.ancho, g.alto) == (480, 270)
    assert g.preview_url.endswith("200w.gif") and g.licencia == "GIPHY"
    assert llamadas.hechas[0][1] == "https://api.giphy.com/v1/gifs/search"
    assert llamadas.hechas[0][2]["api_key"] == "GK" and llamadas.hechas[0][2]["rating"] == "g"
    [v] = _prov("giphy", {"GIPHY_API_KEY": "GK"}).buscar("wow", tipo="video", n=5)
    assert v.url.endswith("giphy.mp4") and v.tipo == "video"
    _prov("giphy", {"GIPHY_API_KEY": "GK"}, {"stickers": True}).buscar("wow", tipo="imagen", n=5)
    assert llamadas.hechas[-1][1] == "https://api.giphy.com/v1/stickers/search"
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q -k giphy`
Expected: FAIL con `KeyError: 'giphy'`.

- [ ] **Paso 3: implementar** `src/assets/proveedores/giphy.py`:
```python
"""GIPHY: GIF animado (tipo imagen) o su MP4 (tipo video). Rating g.
Atribución obligatoria «Powered by GIPHY» en la UI que muestra resultados."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


class Giphy(base.Proveedor):
    nombre = "giphy"
    tipos = ("imagen", "video")
    llave = "GIPHY_API_KEY"
    hosts = ("giphy.com",)

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        ruta = "stickers" if self.config.get("stickers") else "gifs"
        datos = base.get_json(f"https://api.giphy.com/v1/{ruta}/search",
                              params={"api_key": self.clave(), "q": q[:50],
                                      "limit": max(1, min(n, 50)), "rating": "g"})
        out = []
        for d in datos.get("data", []):
            imgs = d.get("images") or {}
            orig = imgs.get("original") or {}
            url = orig.get("mp4") if tipo == "video" else orig.get("url")
            if not url:
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=str(d["id"]), tipo=tipo, url=url,
                preview_url=(imgs.get("fixed_width") or {}).get("url") or orig.get("url") or "",
                ancho=_int(orig.get("width")), alto=_int(orig.get("height")),
                autor=d.get("username") or None, licencia="GIPHY", url_origen=d.get("url")))
        return out
```
Registrar `Giphy` en `PROVEEDORES`.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/proveedores tests/fixtures/assets/giphy.json tests/test_assets_proveedores.py
git commit -m "assets: proveedor GIPHY (gif, mp4 y stickers)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: proveedor `ia_imagen` (fal.ai FLUX schnell, de pago)

**Files:**
- Create: `src/assets/proveedores/ia_imagen.py`, `tests/fixtures/assets/fal_flux.json`
- Modify: `src/assets/proveedores/__init__.py`, `tests/test_assets_proveedores.py`

**Interfaces:** `class IaImagen(Proveedor)`: `nombre="ia_imagen"`, `tipos=("imagen",)`, `llave="FAL_KEY"`, `de_pago=True`, `hosts=("fal.media",)` ⚠️. `num_images` va entre 1 y 4. Este proveedor no decide si debe correr; eso lo controla `buscar.py` (Task 10).

⚠️ Tres cosas sin verificar:
- el header `Authorization: Key <FAL_KEY>`;
- el host de las imágenes devueltas (`fal.media` / `v3.fal.media`);
- el precio por imagen.

Antes de activarlo en una marca real, Ricardo confirma el precio en `https://fal.ai/models/fal-ai/flux/schnell` y prueba una llamada a mano.

- [ ] **Paso 1: fixture y prueba que falla**

`tests/fixtures/assets/fal_flux.json`:
```json
{"images": [{"url": "https://v3.fal.media/files/x/a.jpeg", "width": 1024, "height": 768, "content_type": "image/jpeg"},
            {"url": "https://v3.fal.media/files/x/b.jpeg", "width": 1024, "height": 768, "content_type": "image/jpeg"}],
 "seed": 42, "has_nsfw_concepts": [false, true], "prompt": "taco"}
```
Agregar a `tests/test_assets_proveedores.py`:
```python
def test_ia_imagen_genera_y_tope_4(llamadas) -> None:
    llamadas.resp = _grabado("fal_flux.json")
    p = _prov("ia_imagen", {"FAL_KEY": "FK"})
    assert PROVEEDORES["ia_imagen"].de_pago is True
    res = p.buscar("taco al pastor", tipo="imagen", n=20)
    assert [c.id_origen for c in res] == ["42-0"]      # el nsfw se descarta
    assert res[0].licencia == "Generada (fal.ai)"
    metodo, url, body, headers = llamadas.hechas[0]
    assert (metodo, url) == ("POST", "https://fal.run/fal-ai/flux/schnell")
    assert body["num_images"] == 4 and body["prompt"] == "taco al pastor"
    assert headers["Authorization"] == "Key FK"
    assert p.buscar("x", tipo="video", n=2) == []
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q -k ia_imagen`
Expected: FAIL con `KeyError: 'ia_imagen'`.

- [ ] **Paso 3: implementar** `src/assets/proveedores/ia_imagen.py`:
```python
"""Generación con fal.ai FLUX schnell. DE PAGO: buscar.py solo lo corre si la
llamada lo pide por nombre y la marca tiene la fuente activa (spec §4)."""
from __future__ import annotations

from src.assets import Candidata
from src.assets.proveedores import base

_MAX = 4


class IaImagen(base.Proveedor):
    nombre = "ia_imagen"
    tipos = ("imagen",)
    llave = "FAL_KEY"
    hosts = ("fal.media",)
    de_pago = True

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo != "imagen":
            return []
        datos = base.post_json("https://fal.run/fal-ai/flux/schnell",
                               json_body={"prompt": q[:500], "image_size": "portrait_4_3",
                                          "num_images": max(1, min(n, _MAX))},
                               headers={"Authorization": f"Key {self.clave()}"})
        nsfw = datos.get("has_nsfw_concepts") or []
        seed = datos.get("seed", "x")
        out = []
        for i, img in enumerate(datos.get("images", [])):
            if not img.get("url") or (i < len(nsfw) and nsfw[i]):
                continue
            out.append(Candidata(
                proveedor=self.nombre, id_origen=f"{seed}-{i}", tipo="imagen", url=img["url"],
                preview_url=img["url"], ancho=img.get("width"), alto=img.get("height"),
                autor=None, licencia="Generada (fal.ai)", url_origen=None))
        return out
```
Registrar `IaImagen` en `PROVEEDORES`. La tupla final queda `(Carpeta, Unsplash, Pexels, Pixabay, Openverse, Coverr, Giphy, IaImagen)`.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/proveedores tests/fixtures/assets/fal_flux.json tests/test_assets_proveedores.py
git commit -m "assets: proveedor ia_imagen (fal FLUX schnell, de pago)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `buscar.py`, la búsqueda repartida entre las fuentes de la marca

**Files:**
- Create: `src/assets/buscar.py`
- Test: `tests/test_assets_buscar.py`

**Interfaces:**
```python
def buscar(cx, account_id: int, slug: str, q: str, *, tipo: str = "imagen",
           proveedores: list[str] | None = None, n: int = 20) -> list[Candidata]   # contrato
def buscar_con_avisos(cx, account_id, slug, q, *, tipo="imagen", proveedores=None, n=20
                      ) -> tuple[list[Candidata], list[str]]                      # lo usa la API
```
Reglas:
- **Sin `proveedores`:** usa las filas activas de `brand_sources` con `kind == tipo`, sin las de pago. Si la marca no tiene ninguna, cae a `carpeta` y, si hay key, a `pexels`.
- **Con `proveedores`:** usa esos nombres. Uno `de_pago` solo corre si existe una fila activa de la marca con ese provider; si no, se avisa y se omite.
- **Errores:** un proveedor que falla se salta, su error va a `ultimo_error` de su fila (si la hay) y a `avisos`. El texto sale limpio de llaves y truncado a 300.
- **Resultados:** se intercalan en round-robin, se deduplican por `url` y se cortan a `n`.

- [ ] **Paso 1: escribir la prueba que falla**

`tests/test_assets_buscar.py`:
```python
"""buscar.py: orden, fallback, de pago explícito y errores sin llaves."""
from __future__ import annotations

import pytest

import config
from src import assets, db
from src.assets import Candidata, buscar
from src.assets.proveedores import PROVEEDORES, base

SECRETO = "sk-SUPERSECRETA-123"


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx) -> int:
    return db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")


def _c(prov, i) -> Candidata:
    return Candidata(proveedor=prov, id_origen=str(i), tipo="imagen", url=f"https://h/{prov}/{i}",
                     preview_url="", ancho=None, alto=None, autor=None, licencia=None,
                     url_origen=None)


class _Falso(base.Proveedor):
    tipos = ("imagen", "video")
    llamadas: list = []

    def buscar(self, q, *, tipo="imagen", n=20):
        _Falso.llamadas.append(self.nombre)
        return [_c(self.nombre, i) for i in range(3)]


def _registrar(monkeypatch, nombre, cls=_Falso, **attrs):
    sub = type(f"P_{nombre}", (cls,), {"nombre": nombre, **attrs})
    monkeypatch.setitem(PROVEEDORES, nombre, sub)
    return sub


@pytest.fixture(autouse=True)
def _sin_creds(monkeypatch):
    monkeypatch.setattr(config, "account_creds", lambda slug: {"PEXELS_API_KEY": SECRETO})
    _Falso.llamadas = []


def test_intercala_dedup_y_corta(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "pa")
    _registrar(monkeypatch, "pb")
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pa", orden=0)
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pb", orden=1)
    db.insert(cx, "brand_sources", account_id=aid, kind="video", provider="pa", orden=0)
    res = buscar.buscar(cx, aid, "m1", "x", tipo="imagen", n=4)
    assert [c.url for c in res] == ["https://h/pa/0", "https://h/pb/0",
                                    "https://h/pa/1", "https://h/pb/1"]


def test_sin_fuentes_cae_a_carpeta_y_pexels(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "carpeta")
    _registrar(monkeypatch, "pexels")
    buscar.buscar(cx, aid, "m1", "x")
    assert _Falso.llamadas == ["carpeta", "pexels"]


def test_ia_imagen_solo_explicito_y_activo(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "pa")
    _registrar(monkeypatch, "ia_imagen", de_pago=True)
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pa")
    sid = db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="ia_imagen")
    # 1) por omisión NO corre aunque la fila esté activa
    buscar.buscar(cx, aid, "m1", "x")
    assert "ia_imagen" not in _Falso.llamadas
    # 2) pedido por nombre con fila activa: corre
    buscar.buscar(cx, aid, "m1", "x", proveedores=["ia_imagen"])
    assert _Falso.llamadas[-1] == "ia_imagen"
    # 3) pedido por nombre con la fila apagada: no corre y avisa
    db.update(cx, "brand_sources", sid, activa=0)
    _Falso.llamadas = []
    res, avisos = buscar.buscar_con_avisos(cx, aid, "m1", "x", proveedores=["ia_imagen"])
    assert _Falso.llamadas == [] and res == []
    assert avisos and avisos[0].startswith("ia_imagen:")


def test_error_de_proveedor_no_filtra_llave(cx, monkeypatch) -> None:
    aid = _cuenta(cx)

    class Roto(base.Proveedor):
        tipos = ("imagen",)

        def buscar(self, q, *, tipo="imagen", n=20):
            raise RuntimeError(f"401 for url: https://api.x/?key={SECRETO}&q=x "
                               f"Authorization: {SECRETO}")

    _registrar(monkeypatch, "roto", cls=Roto)
    _registrar(monkeypatch, "pa")
    sid = db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="roto")
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="pa")
    res, avisos = buscar.buscar_con_avisos(cx, aid, "m1", "x")
    assert len(res) == 3                              # el roto no tumba la búsqueda
    fila = db.get(cx, "brand_sources", sid)
    assert fila["ultimo_run"] and fila["ultimo_error"]
    for texto in [fila["ultimo_error"], *avisos]:
        assert SECRETO not in texto
        assert "SUPERSECRETA" not in texto
        assert len(texto) <= 320


def test_sin_llave_se_reporta_por_nombre(cx, monkeypatch) -> None:
    aid = _cuenta(cx)
    _registrar(monkeypatch, "conllave", cls=base.Proveedor, llave="GIPHY_API_KEY",
               buscar=lambda self, q, *, tipo="imagen", n=20: [self.clave()])
    db.insert(cx, "brand_sources", account_id=aid, kind="imagen", provider="conllave")
    _, avisos = buscar.buscar_con_avisos(cx, aid, "m1", "x")
    assert avisos == ["conllave: falta GIPHY_API_KEY"]


def test_tipo_invalido(cx) -> None:
    with pytest.raises(ValueError):
        buscar.buscar(cx, _cuenta(cx), "m1", "x", tipo="audio")
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_buscar.py -q`
Expected: FAIL con `ImportError: cannot import name 'buscar' from 'src.assets'`.

- [ ] **Paso 3: implementar** `src/assets/buscar.py`:
```python
"""Búsqueda de assets repartida entre las fuentes de la marca.

Un proveedor que falla (sin key, 4xx, timeout) se salta: el error queda en
brand_sources.ultimo_error y en `avisos`, y la búsqueda sigue (spec §4). Los
proveedores de pago (`de_pago=True`) nunca corren por omisión.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from itertools import zip_longest

import config
from src import db
from src.assets import TIPOS, Candidata
from src.assets.proveedores import PROVEEDORES
from src.assets.proveedores.base import SinLlave

_MAX_ERROR = 300
_PARAM_SECRETO = re.compile(r"(?i)\b(key|api_key|apikey|client_id|access_key|token)=[^&\s'\"]+")
_HEADER_SECRETO = re.compile(r"(?i)\b(authorization|client-id|bearer|key)\s*[:=]?\s+\S+")


def _limpiar(msg: str, creds: dict) -> str:
    for valor in creds.values():
        if valor and len(valor) >= 4:
            msg = msg.replace(valor, "***")
    msg = _PARAM_SECRETO.sub(r"\1=***", msg)
    msg = _HEADER_SECRETO.sub(r"\1 ***", msg)
    return msg[:_MAX_ERROR]


def _ahora() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def buscar_con_avisos(cx, account_id: int, slug: str, q: str, *, tipo: str = "imagen",
                      proveedores: list[str] | None = None, n: int = 20
                      ) -> tuple[list[Candidata], list[str]]:
    if tipo not in TIPOS:
        raise ValueError("tipo")
    q = (q or "").strip()[:200]
    n = max(1, min(n, 60))
    creds = config.account_creds(slug)
    filas = db.rows(cx, "SELECT * FROM brand_sources WHERE account_id = ? AND kind = ? "
                        "AND activa = 1 ORDER BY orden, id", (account_id, tipo))
    fila_de: dict[str, dict] = {}
    for f in filas:
        fila_de.setdefault(f["provider"], f)

    avisos: list[str] = []
    if proveedores is None:
        nombres = [p for p in fila_de if p in PROVEEDORES and not PROVEEDORES[p].de_pago]
        if not nombres:
            nombres = ["carpeta"] + (["pexels"] if creds.get("PEXELS_API_KEY") else [])
    else:
        nombres = []
        for p in proveedores:
            cls = PROVEEDORES.get(p)
            if cls is None:
                avisos.append(f"{p}: proveedor desconocido")
            elif cls.de_pago and p not in fila_de:
                avisos.append(f"{p}: es de pago; actívalo en Ajustes → Fuentes")
            else:
                nombres.append(p)

    listas: list[list[Candidata]] = []
    for nombre in dict.fromkeys(nombres):
        cls = PROVEEDORES.get(nombre)
        if cls is None or tipo not in cls.tipos:
            continue
        fila = fila_de.get(nombre)
        conf = json.loads(fila["config_json"] or "{}") if fila else {}
        prov = cls(cx=cx, account_id=account_id, slug=slug, creds=creds, config=conf)
        error = None
        try:
            res = list(prov.buscar(q, tipo=tipo, n=n))
        except SinLlave as e:
            res, error = [], f"falta {e.args[0]}"
        except Exception as e:  # noqa: BLE001 — un proveedor no tumba la búsqueda
            res, error = [], _limpiar(f"{type(e).__name__}: {e}", creds)
        if error:
            avisos.append(f"{nombre}: {error}")
        if fila is not None:
            db.update(cx, "brand_sources", fila["id"], ultimo_run=_ahora(), ultimo_error=error)
        listas.append(res)
    cx.commit()

    out: list[Candidata] = []
    vistos: set[str] = set()
    for grupo in zip_longest(*listas):
        for c in grupo:
            if c is None or c.url in vistos:
                continue
            vistos.add(c.url)
            out.append(c)
    return out[:n], avisos


def buscar(cx, account_id: int, slug: str, q: str, *, tipo: str = "imagen",
           proveedores: list[str] | None = None, n: int = 20) -> list[Candidata]:
    return buscar_con_avisos(cx, account_id, slug, q, tipo=tipo, proveedores=proveedores,
                             n=n)[0]
```

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_buscar.py -q`
Expected: PASS. Si `db.update` rechaza `ultimo_error=None`, es porque la allowlist ya trae `ultimo_error` en `brand_sources`, así que no debería pasar.

- [ ] **Paso 5: commit**
```bash
git add src/assets/buscar.py tests/test_assets_buscar.py
git commit -m "assets: búsqueda repartida, de pago solo explícito, errores sin llaves

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: `biblioteca.py`, la única puerta al disco

**Files:**
- Create: `src/assets/biblioteca.py`
- Test: `tests/test_assets_biblioteca.py`

**Interfaces:**
```python
class AssetInvalido(ValueError): ...
TOPES = {"imagen": 15 * 1024 * 1024, "video": 100 * 1024 * 1024}
def ruta_de(slug: str, archivo: str) -> Path                 # contrato; ValueError si no valida
def tipo_de_bytes(cabeza: bytes) -> tuple[str, str] | None   # (tipo, ext)
def descargar(url: str, *, hosts: tuple[str, ...] | None, tope: int) -> bytes
def guardar_bytes(cx, account_id, slug, datos: bytes, *, proveedor: str, meta: dict | None = None,
                  tags: list[str] | None = None) -> tuple[dict, bool]   # (fila, nueva)
def importar(cx, account_id: int, slug: str, cand: Candidata, *, tags=None) -> dict   # contrato
```

- [ ] **Paso 1: escribir la prueba que falla**

`tests/test_assets_biblioteca.py`:
```python
"""biblioteca: rutas, magic bytes, descarga cerrada (https, IP pública, redirects), dedup."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src import assets, db
from src.assets import Candidata, biblioteca
from src.assets.biblioteca import AssetInvalido


def _png(w=4, h=3) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), "red").save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx, slug="m1") -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}", nombre=slug, ciudad="GDL")


class _Resp:
    def __init__(self, status=200, body=b"", headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}
        self.is_redirect = status in (301, 302, 303, 307, 308)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i:i + n]


@pytest.fixture()
def red(monkeypatch):
    """DNS y HTTP falsos: `red.dns[host] = [ip]`, `red.resp[url] = _Resp`."""
    class R:
        dns: dict = {}
        resp: dict = {}
        pedidas: list = []
    R.dns, R.resp, R.pedidas = {}, {}, []
    monkeypatch.setattr(biblioteca, "_ips_de", lambda host: R.dns.get(host, []))

    def fake_get(url, **kw):
        assert kw.get("allow_redirects") is False and kw.get("stream") is True
        R.pedidas.append(url)
        return R.resp[url]
    monkeypatch.setattr(biblioteca.requests, "get", fake_get)
    return R


def test_ruta_de_valida() -> None:
    assert biblioteca.ruta_de("m1", "ab12.jpg").parts[-3:] == ("m1", "assets", "ab12.jpg")
    for slug, archivo in [("../x", "a.jpg"), ("m1", "../a.jpg"), ("m1", "a/b.jpg"),
                          ("m1", ".oculto"), ("M1", "a.jpg"), ("m1", "")]:
        with pytest.raises(ValueError):
            biblioteca.ruta_de(slug, archivo)


def test_tipo_de_bytes() -> None:
    assert biblioteca.tipo_de_bytes(_png()[:16]) == ("imagen", "png")
    assert biblioteca.tipo_de_bytes(b"\xff\xd8\xff\xe0" + b"0" * 12) == ("imagen", "jpg")
    assert biblioteca.tipo_de_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == ("imagen", "webp")
    assert biblioteca.tipo_de_bytes(b"GIF89a" + b"0" * 10) == ("imagen", "gif")
    assert biblioteca.tipo_de_bytes(b"\x00\x00\x00\x18ftypisom0000") == ("video", "mp4")
    assert biblioteca.tipo_de_bytes(b"\x1a\x45\xdf\xa3" + b"0" * 12) == ("video", "webm")
    assert biblioteca.tipo_de_bytes(b"\x00\x00\x00\x18ftypheic0000") is None
    assert biblioteca.tipo_de_bytes(b"<svg xmlns=") is None


def test_descarga_solo_https(red) -> None:
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("http://a.com/x.png", hosts=None, tope=100)
    assert red.pedidas == []


def test_descarga_rechaza_ip_privada_y_host_fuera_de_lista(red) -> None:
    red.dns["interno.com"] = ["10.0.0.5"]
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://interno.com/x.png", hosts=None, tope=100)
    red.dns["evil.com"] = ["93.184.216.34"]
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://evil.com/x.png", hosts=("pexels.com",), tope=100)
    red.dns["images.pexels.com"] = ["93.184.216.34"]
    red.resp["https://images.pexels.com/x.png"] = _Resp(body=b"ok")
    assert biblioteca.descargar("https://images.pexels.com/x.png", hosts=("pexels.com",),
                                tope=100) == b"ok"
    assert red.pedidas == ["https://images.pexels.com/x.png"]


def test_descarga_redirect_a_metadata_se_bloquea(red) -> None:
    red.dns["cdn.com"] = ["93.184.216.34"]
    red.dns["169.254.169.254"] = ["169.254.169.254"]
    red.resp["https://cdn.com/a"] = _Resp(302, headers={"Location": "https://169.254.169.254/x"})
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://cdn.com/a", hosts=None, tope=100)
    assert red.pedidas == ["https://cdn.com/a"]


def test_descarga_tope_y_demasiados_redirects(red) -> None:
    red.dns["cdn.com"] = ["93.184.216.34"]
    red.resp["https://cdn.com/grande"] = _Resp(body=b"x" * 200_000)
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://cdn.com/grande", hosts=None, tope=100_000)
    red.resp["https://cdn.com/r"] = _Resp(302, headers={"Location": "/r"})
    with pytest.raises(AssetInvalido):
        biblioteca.descargar("https://cdn.com/r", hosts=None, tope=100)


def test_guardar_bytes_dedup_y_dims(cx) -> None:
    aid = _cuenta(cx)
    fila, nueva = biblioteca.guardar_bytes(cx, aid, "m1", _png(8, 5), proveedor="subida")
    assert nueva and (fila["ancho"], fila["alto"], fila["tipo"]) == (8, 5, "imagen")
    assert fila["archivo"].endswith(".png")
    assert biblioteca.ruta_de("m1", fila["archivo"]).read_bytes() == _png(8, 5)
    otra, nueva2 = biblioteca.guardar_bytes(cx, aid, "m1", _png(8, 5), proveedor="subida")
    assert not nueva2 and otra["id"] == fila["id"]
    with pytest.raises(AssetInvalido):
        biblioteca.guardar_bytes(cx, aid, "m1", b"<html>", proveedor="subida")
    with pytest.raises(AssetInvalido):   # magic de PNG pero cuerpo corrupto
        biblioteca.guardar_bytes(cx, aid, "m1", _png()[:20] + b"basura", proveedor="subida")
    assert not list((assets.BRANDS_DIR / "m1" / "assets").glob("*.part"))


def test_importar_remoto_registra_descarga_solo_si_es_nueva(cx, red, monkeypatch) -> None:
    from src.assets.proveedores import PROVEEDORES
    aid = _cuenta(cx)
    registradas = []
    monkeypatch.setattr(PROVEEDORES["unsplash"], "registrar_descarga",
                        lambda self, cand: registradas.append(cand.id_origen))
    red.dns["images.unsplash.com"] = ["93.184.216.34"]
    red.resp["https://images.unsplash.com/p1"] = _Resp(body=_png())
    cand = Candidata(proveedor="unsplash", id_origen="p1", tipo="imagen",
                     url="https://images.unsplash.com/p1", preview_url="", ancho=None,
                     alto=None, autor="Ana", licencia="Unsplash License",
                     url_origen="https://unsplash.com/p1")
    fila = biblioteca.importar(cx, aid, "m1", cand, tags=["playa"])
    assert (fila["proveedor"], fila["autor"], fila["tags_json"]) == ("unsplash", "Ana", '["playa"]')
    biblioteca.importar(cx, aid, "m1", cand)
    assert registradas == ["p1"]


def test_importar_tipo_no_coincide(cx, red) -> None:
    aid = _cuenta(cx)
    red.dns["media.giphy.com"] = ["93.184.216.34"]
    red.resp["https://media.giphy.com/a.mp4"] = _Resp(body=_png())
    cand = Candidata(proveedor="giphy", id_origen="g", tipo="video",
                     url="https://media.giphy.com/a.mp4", preview_url="", ancho=None,
                     alto=None, autor=None, licencia="GIPHY", url_origen=None)
    with pytest.raises(AssetInvalido):
        biblioteca.importar(cx, aid, "m1", cand)


def test_importar_local_fotos_y_assets(cx) -> None:
    aid = _cuenta(cx)
    otra = _cuenta(cx, "m2")
    fotos = assets.BRANDS_DIR / "m1" / "fotos"
    fotos.mkdir(parents=True)
    (fotos / "a.png").write_bytes(_png())
    cand = Candidata(proveedor="carpeta", id_origen="a.png", tipo="imagen",
                     url="local:fotos/a.png", preview_url="", ancho=None, alto=None,
                     autor=None, licencia="propia", url_origen=None)
    fila = biblioteca.importar(cx, aid, "m1", cand)
    assert fila["proveedor"] == "carpeta"
    ya = Candidata(**{**cand.a_dict(), "url": f"local:assets/{fila['archivo']}"})
    assert biblioteca.importar(cx, aid, "m1", ya)["id"] == fila["id"]
    with pytest.raises(AssetInvalido):          # el archivo es de m1, no de m2
        biblioteca.importar(cx, otra, "m2", ya)
    for mala in ("local:fotos/../../x.png", "local:otra/a.png", "local:fotos/A B.png"):
        with pytest.raises((AssetInvalido, ValueError)):
            biblioteca.importar(cx, aid, "m1", Candidata(**{**cand.a_dict(), "url": mala}))
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_biblioteca.py -q`
Expected: FAIL con `ImportError: cannot import name 'biblioteca'`.

- [ ] **Paso 3: implementar** `src/assets/biblioteca.py`:
```python
"""Única puerta al disco de assets de una marca.

Descarga cerrada: solo https, solo hosts cuyas IP resueltas son globales
(nada de 10/8, 127/8, 169.254/16, ::1…), redirects manuales re-validados en
cada salto, allowlist de hosts por proveedor, tope de bytes leído por chunks.
Lo que se guarda pasa por magic bytes; nada se escribe con el nombre que da
el origen: el archivo es <sha[:16]>.<ext>.
⚠️ Queda un TOCTOU de DNS rebinding entre _ips_de y la conexión de requests;
se acepta para este alcance (spec §6).
"""
from __future__ import annotations

import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import socket
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from PIL import Image

import config
from src import assets, db
from src.assets import Candidata
from src.assets.proveedores import PROVEEDORES, base

log = logging.getLogger(__name__)

TOPES = {"imagen": 15 * 1024 * 1024, "video": 100 * 1024 * 1024}
_MAX_REDIRECTS = 3
_CHUNK = 64 * 1024
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")
_ARCHIVO_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,120}\Z")
_NOMBRE_FOTO_RE = re.compile(r"^[a-z0-9_.-]+\Z")
_FTYP_NO_VIDEO = {b"heic", b"heix", b"hevc", b"mif1", b"msf1", b"avif", b"avis"}


class AssetInvalido(ValueError):
    pass


def ruta_de(slug: str, archivo: str) -> Path:
    if not _SLUG_RE.match(slug or "") or not _ARCHIVO_RE.match(archivo or "") or ".." in archivo:
        raise ValueError("ruta de asset inválida")
    return assets.BRANDS_DIR / slug / "assets" / archivo


def tipo_de_bytes(cabeza: bytes) -> tuple[str, str] | None:
    if cabeza.startswith(b"\xff\xd8\xff"):
        return "imagen", "jpg"
    if cabeza.startswith(b"\x89PNG\r\n\x1a\n"):
        return "imagen", "png"
    if cabeza[:4] == b"RIFF" and cabeza[8:12] == b"WEBP":
        return "imagen", "webp"
    if cabeza[:6] in (b"GIF87a", b"GIF89a"):
        return "imagen", "gif"
    if cabeza[4:8] == b"ftyp" and cabeza[8:12] not in _FTYP_NO_VIDEO:
        return "video", "mp4"
    if cabeza.startswith(b"\x1a\x45\xdf\xa3"):
        return "video", "webm"
    return None


def _ips_de(host: str) -> list[str]:
    return [ai[4][0] for ai in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)]


def _validar_url(url: str, hosts: tuple[str, ...] | None) -> None:
    partes = urlsplit(url)
    host = (partes.hostname or "").lower()
    if partes.scheme != "https" or not host:
        raise AssetInvalido("solo se descargan URLs https")
    if hosts is not None and not any(host == h or host.endswith("." + h) for h in hosts):
        raise AssetInvalido(f"host no permitido para este proveedor: {host}")
    try:
        ips = _ips_de(host)
    except (socket.gaierror, UnicodeError) as e:
        raise AssetInvalido(f"el host no resuelve: {host}") from e
    try:
        if not ips or not all(ipaddress.ip_address(ip.split("%")[0]).is_global for ip in ips):
            raise AssetInvalido(f"host no público: {host}")
    except ValueError as e:
        if isinstance(e, AssetInvalido):
            raise
        raise AssetInvalido(f"IP inválida para {host}") from e


def descargar(url: str, *, hosts: tuple[str, ...] | None, tope: int) -> bytes:
    for _ in range(_MAX_REDIRECTS + 1):
        _validar_url(url, hosts)
        with requests.get(url, stream=True, allow_redirects=False, timeout=base.TIMEOUT,
                          headers={"User-Agent": base.UA}) as r:
            if r.is_redirect:
                destino = r.headers.get("Location")
                if not destino:
                    raise AssetInvalido("redirect sin destino")
                url = urljoin(url, destino)
                continue
            r.raise_for_status()
            largo = r.headers.get("Content-Length", "")
            if largo.isdigit() and int(largo) > tope:
                raise AssetInvalido("el archivo excede el tope")
            piezas, total = [], 0
            for chunk in r.iter_content(_CHUNK):
                total += len(chunk)
                if total > tope:
                    raise AssetInvalido("el archivo excede el tope")
                piezas.append(chunk)
            return b"".join(piezas)
    raise AssetInvalido("demasiados redirects")


def _dims_imagen(datos: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(datos)) as im:
            im.verify()
        with Image.open(io.BytesIO(datos)) as im:
            return im.size
    except Exception as e:  # noqa: BLE001 — cualquier fallo de Pillow = archivo corrupto
        raise AssetInvalido("la imagen está dañada") from e


def guardar_bytes(cx, account_id: int, slug: str, datos: bytes, *, proveedor: str,
                  meta: dict | None = None, tags: list[str] | None = None
                  ) -> tuple[dict, bool]:
    detectado = tipo_de_bytes(datos[:16])
    if detectado is None:
        raise AssetInvalido("formato no soportado (jpg, png, webp, gif, mp4, webm)")
    tipo, ext = detectado
    if len(datos) > TOPES[tipo]:
        raise AssetInvalido("el archivo excede el tope")
    sha = hashlib.sha256(datos).hexdigest()
    previas = db.rows(cx, "SELECT * FROM brand_assets WHERE account_id = ? AND sha = ?",
                      (account_id, sha))
    if previas:
        return dict(previas[0]), False
    meta = meta or {}
    ancho, alto = _dims_imagen(datos) if tipo == "imagen" else (meta.get("ancho"), meta.get("alto"))
    archivo = f"{sha[:16]}.{ext}"
    destino = ruta_de(slug, archivo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    tmp.write_bytes(datos)
    os.replace(tmp, destino)
    aid = db.insert(cx, "brand_assets", account_id=account_id, tipo=tipo, archivo=archivo,
                    sha=sha, proveedor=proveedor, autor=meta.get("autor"),
                    licencia=meta.get("licencia"), url_origen=meta.get("url_origen"),
                    ig_handle=meta.get("ig_handle"), source_post_id=meta.get("source_post_id"),
                    ancho=ancho, alto=alto,
                    tags_json=json.dumps(tags, ensure_ascii=False) if tags else None)
    cx.commit()
    return dict(db.get(cx, "brand_assets", aid)), True


def _importar_local(cx, account_id: int, slug: str, cand: Candidata, tags) -> dict:
    carpeta, _, nombre = cand.url[len("local:"):].partition("/")
    if carpeta == "assets":
        ruta_de(slug, nombre)  # valida el nombre
        filas = db.rows(cx, "SELECT * FROM brand_assets WHERE account_id = ? AND archivo = ?",
                        (account_id, nombre))
        if not filas:
            raise AssetInvalido("ese asset no existe en esta marca")
        return dict(filas[0])
    if carpeta == "fotos" and _NOMBRE_FOTO_RE.match(nombre) and ".." not in nombre:
        if not _SLUG_RE.match(slug):
            raise AssetInvalido("marca inválida")
        origen = assets.BRANDS_DIR / slug / "fotos" / nombre
        if not origen.is_file():
            raise AssetInvalido("esa foto no existe")
        meta = {"licencia": "propia"}
        return guardar_bytes(cx, account_id, slug, origen.read_bytes(), proveedor="carpeta",
                             meta=meta, tags=tags)[0]
    raise AssetInvalido("ruta local inválida")


def importar(cx, account_id: int, slug: str, cand: Candidata, *,
             tags: list[str] | None = None) -> dict:
    if cand.url.startswith("local:"):
        return _importar_local(cx, account_id, slug, cand, tags)
    cls = PROVEEDORES.get(cand.proveedor)
    if cls is None or cand.tipo not in cls.tipos:
        raise AssetInvalido("proveedor inválido")
    datos = descargar(cand.url, hosts=cls.hosts, tope=TOPES[cand.tipo])
    detectado = tipo_de_bytes(datos[:16])
    if detectado is None or detectado[0] != cand.tipo:
        raise AssetInvalido("el archivo no es del tipo esperado")
    fila, nueva = guardar_bytes(cx, account_id, slug, datos, proveedor=cand.proveedor,
                                meta=cand.a_dict(), tags=tags)
    if nueva:
        try:
            cls(cx=cx, account_id=account_id, slug=slug, creds=config.account_creds(slug),
                config={}).registrar_descarga(cand)
        except Exception as e:  # noqa: BLE001 — el tracking nunca rompe un import
            log.warning("registrar_descarga %s falló: %s", cand.proveedor, type(e).__name__)
    return fila
```
Nota: en `_importar_local`, `"A B.png"` no pasa `_NOMBRE_FOTO_RE`, así que lanza AssetInvalido. `"../../x.png"` tiene `/`, así que el `partition` deja `"../../x.png"` como `nombre`, y el `".."` lo rechaza.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_biblioteca.py tests/test_assets_proveedores.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/assets/biblioteca.py tests/test_assets_biblioteca.py
git commit -m "assets: biblioteca con descarga cerrada, magic bytes y dedup por sha

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: recorte con rembg (BiRefNet) y job `asset.recorte`

**Files:**
- Create: `src/assets/recorte.py`
- Modify: `src/jobs/handlers.py` (handler + `HANDLERS`), `requirements.txt`, `Dockerfile`
- Test: `tests/test_assets_recorte.py`

**Interfaces:**
```python
# src/assets/recorte.py
MODELO = "birefnet-general"
def quitar_fondo(origen: Path, destino: Path) -> Path          # contrato; recorta al bbox del alfa
# src/jobs/handlers.py
def asset_recorte(cx, job) -> dict   # payload {"asset_id": int} -> {"asset_id", "recorte_archivo", "src"}
HANDLERS["asset.recorte"] = asset_recorte
```

- [ ] **Paso 1: escribir la prueba que falla**

`tests/test_assets_recorte.py`:
```python
"""quitar_fondo y job asset.recorte. El modelo real solo corre con -m lento."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src import assets, db, jobs
from src.assets import biblioteca, recorte
from src.jobs import handlers


def _png_con_alfa() -> bytes:
    im = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
    for x in range(10, 20):
        for y in range(5, 25):
            im.putpixel((x, y), (255, 0, 0, 255))
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _png(w=40, h=30) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), "blue").save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(recorte, "_remover", lambda datos: _png_con_alfa())
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def _cuenta(cx, slug) -> int:
    return db.insert(cx, "accounts", slug=slug, ig_handle=f"@{slug}", nombre=slug, ciudad="GDL")


def test_quitar_fondo_recorta_al_contenido(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(recorte, "_remover", lambda datos: _png_con_alfa())
    origen = tmp_path / "o.png"
    origen.write_bytes(_png())
    destino = recorte.quitar_fondo(origen, tmp_path / "d" / "o-recorte.png")
    with Image.open(destino) as im:
        assert im.mode == "RGBA" and im.size == (10, 20)
    assert not list((tmp_path / "d").glob("*.part"))


def test_quitar_fondo_vacio(tmp_path, monkeypatch) -> None:
    vacio = io.BytesIO()
    Image.new("RGBA", (5, 5), (0, 0, 0, 0)).save(vacio, "PNG")
    monkeypatch.setattr(recorte, "_remover", lambda datos: vacio.getvalue())
    origen = tmp_path / "o.png"
    origen.write_bytes(_png())
    with pytest.raises(ValueError):
        recorte.quitar_fondo(origen, tmp_path / "x.png")


def test_job_recorte_guarda_y_actualiza_fila(cx) -> None:
    aid = _cuenta(cx, "m1")
    fila, _ = biblioteca.guardar_bytes(cx, aid, "m1", _png(), proveedor="subida")
    jid = jobs.crear(cx, "asset.recorte", aid, {"asset_id": fila["id"]}, creado_por=None)
    res = handlers.HANDLERS["asset.recorte"](cx, db.get(cx, "jobs", jid))
    esperado = fila["archivo"].rsplit(".", 1)[0] + "-recorte.png"
    assert res == {"asset_id": fila["id"], "recorte_archivo": esperado,
                   "src": f"assets/{esperado}"}
    assert db.get(cx, "brand_assets", fila["id"])["recorte_archivo"] == esperado
    assert biblioteca.ruta_de("m1", esperado).is_file()


def test_recorte_rechaza_asset_de_otra_marca(cx) -> None:
    a1, a2 = _cuenta(cx, "m1"), _cuenta(cx, "m2")
    ajeno, _ = biblioteca.guardar_bytes(cx, a2, "m2", _png(), proveedor="subida")
    jid = jobs.crear(cx, "asset.recorte", a1, {"asset_id": ajeno["id"]}, creado_por=None)
    with pytest.raises(ValueError):
        handlers.asset_recorte(cx, db.get(cx, "jobs", jid))
    assert db.get(cx, "brand_assets", ajeno["id"])["recorte_archivo"] is None
    assert not list((assets.BRANDS_DIR / "m1").glob("**/*-recorte.png"))


def test_opencv_sigue_cargando_haar() -> None:
    """rembg trae opencv-python-headless: el clasificador de caras v1 debe seguir vivo."""
    import cv2
    ruta = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    assert not cv2.CascadeClassifier(ruta).empty()


@pytest.mark.lento
def test_modelo_real_birefnet(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(recorte, "_remover", recorte._remover_real)
    origen = tmp_path / "o.png"
    im = Image.new("RGB", (256, 256), "white")
    for x in range(80, 176):
        for y in range(80, 176):
            im.putpixel((x, y), (200, 30, 30))
    im.save(origen)
    destino = recorte.quitar_fondo(origen, tmp_path / "r.png")
    with Image.open(destino) as r:
        assert r.mode == "RGBA" and r.size[0] < 256
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_recorte.py -q -m "not lento"`
Expected: FAIL con `ImportError: cannot import name 'recorte'`. `test_opencv_sigue_cargando_haar` pasa desde ya; es la línea base.

- [ ] **Paso 3: implementar**

`src/assets/recorte.py`:
```python
"""Quitar fondo con rembg + BiRefNet (CPU). La sesión se carga una vez por proceso
(perezosa: importar este módulo no carga onnxruntime). El modelo se descarga en el
build de la imagen (Dockerfile: `rembg d birefnet-general`, REMBG_HOME=/opt/rembg)."""
from __future__ import annotations

import io
import os
from pathlib import Path

from PIL import Image

MODELO = "birefnet-general"
_sesion = None


def _remover_real(datos: bytes) -> bytes:
    global _sesion
    from rembg import new_session, remove
    if _sesion is None:
        _sesion = new_session(MODELO)
    return remove(datos, session=_sesion)


# Punto de sustitución en pruebas.
_remover = _remover_real


def quitar_fondo(origen: Path, destino: Path) -> Path:
    salida = _remover(Path(origen).read_bytes())
    with Image.open(io.BytesIO(salida)) as im:
        rgba = im.convert("RGBA")
    caja = rgba.getchannel("A").getbbox()
    if caja is None:
        raise ValueError("el recorte quedó vacío")
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    rgba.crop(caja).save(tmp, "PNG")
    os.replace(tmp, destino)
    return destino
```
⚠️ `_remover` se llama por nombre de módulo dentro de `quitar_fondo`, así que el monkeypatch de `recorte._remover` funciona. No hay que importarlo con `from`.

En `src/jobs/handlers.py`, agregar el import `from src.assets import biblioteca as assets_biblioteca, recorte as assets_recorte` en el bloque de imports `src`, respetando el orden de ruff (isort). Antes de `HANDLERS = {`, agregar:
```python
def asset_recorte(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """Quita el fondo de un asset de imagen de la marca del job.

    payload: {asset_id}. El asset DEBE ser de job['account_id']: el router ya lo
    valida, pero aquí se repite porque el job es la frontera que escribe a disco.
    """
    payload = json.loads(job["payload_json"] or "{}")
    slug = _marca_de(cx, job["account_id"])
    asset = db.get(cx, "brand_assets", int(payload["asset_id"]))
    if asset is None or asset["account_id"] != job["account_id"]:
        raise ValueError("el asset no existe en esta marca")
    if asset["tipo"] != "imagen":
        raise ValueError("solo se recortan imágenes")
    jobs.progresar(cx, job["id"], 10, "Quitando el fondo")
    nombre = asset["archivo"].rsplit(".", 1)[0] + "-recorte.png"
    assets_recorte.quitar_fondo(assets_biblioteca.ruta_de(slug, asset["archivo"]),
                                assets_biblioteca.ruta_de(slug, nombre))
    db.update(cx, "brand_assets", asset["id"], recorte_archivo=nombre)
    cx.commit()
    jobs.progresar(cx, job["id"], 100, "listo")
    return {"asset_id": asset["id"], "recorte_archivo": nombre, "src": f"assets/{nombre}"}
```
En `HANDLERS`: `"asset.recorte": asset_recorte,`.

`requirements.txt`, debajo de `rapidocr_onnxruntime`:
```
rembg[cpu,cli]>=2.0.60   # editor v2: quitar fondo (BiRefNet). Trae opencv-python-headless
```
`Dockerfile`: agregar `REMBG_HOME=/opt/rembg` al bloque `ENV` y cambiar el `RUN pip install` así:
```dockerfile
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium \
    && rembg d birefnet-general \
    && rm -rf /var/lib/apt/lists/*
```
y el `chown` final así: `&& chown -R instagod:instagod /app /ms-playwright /opt/rembg`.

Instalar local:
```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pip install "rembg[cpu,cli]>=2.0.60"
```
⚠️ Hay dos cosas sin verificar:
- **Conflicto de OpenCV.** `rembg` depende de `opencv-python-headless` y el repo usa `opencv-python<5`. Los dos paquetes escriben el mismo módulo `cv2`. Si `test_opencv_sigue_cargando_haar` falla después del `pip install`, hay que reinstalar con `pip install --force-reinstall "opencv-python<5"`, dejar en `requirements.txt` solo `opencv-python-headless<5` (la VM no tiene GUI) y volver a correr la suite completa.
- **Tamaño de la imagen.** El modelo birefnet-general pesa del orden de cientos de MB, a sumar a la imagen Docker. Medirlo con `docker images` en el build y no darlo por bueno antes. Nada de deploy a la VM sin aprobación de Ricardo.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_recorte.py tests/test_jobs_handlers.py -q -m "not lento"`
Expected: PASS.
Opcional, porque baja el modelo a `~/.u2net`: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_recorte.py -q -m lento`.

- [ ] **Paso 5: commit**
```bash
git add src/assets/recorte.py src/jobs/handlers.py requirements.txt Dockerfile tests/test_assets_recorte.py
git commit -m "assets: quitar fondo con rembg BiRefNet como job asset.recorte

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: catálogo de fuentes en el backend (kind `video` y providers nuevos)

**Files:**
- Modify: `src/fuentes.py` (líneas 16 y 22), `api/routers/fuentes_api.py` (`_MOTIVO_KEY` y la tupla de `estado_fuentes`)
- Test: `tests/test_assets_catalogo_fuentes.py`

**Interfaces:**
```python
PROVIDERS_IMAGEN = ("carpeta", "ig_accounts", "pinterest", "pexels", "unsplash", "banco", "covers",
                    "pixabay", "openverse", "giphy", "ia_imagen")
PROVIDERS_VIDEO = ("carpeta", "pexels", "pixabay", "coverr", "giphy")
_CATALOGO = {"imagen": ..., "info": ..., "video": PROVIDERS_VIDEO}
```
`src/image_sources.resolver` salta los providers que no conoce (`prov is None: continue`, `image_sources.py:343`). Por eso, agregar providers al kind `imagen` no rompe el slideshow v1.

- [ ] **Paso 1: escribir la prueba que falla**

`tests/test_assets_catalogo_fuentes.py`:
```python
"""brand_sources acepta kind 'video' y los providers nuevos; estado_fuentes los reporta."""
from __future__ import annotations

import pytest

import config
from api.routers import fuentes_api
from src import db, fuentes


@pytest.fixture()
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


def test_crear_fuentes_video_y_nuevas(cx) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    for kind, prov in [("video", "pexels"), ("video", "coverr"), ("imagen", "openverse"),
                       ("imagen", "ia_imagen"), ("imagen", "giphy")]:
        fuentes.crear(cx, aid, kind, prov, {})
    with pytest.raises(ValueError):
        fuentes.crear(cx, aid, "video", "unsplash", {})
    assert {f["provider"] for f in fuentes.listar(cx, aid, kind="video")} == {"pexels", "coverr"}


def test_estado_fuentes_nuevos(monkeypatch) -> None:
    monkeypatch.setattr(config, "account_creds", lambda slug: {"PIXABAY_API_KEY": "k"})
    estado = fuentes_api.estado_fuentes("m1")
    assert estado["pixabay"]["ok"] is True
    assert estado["openverse"]["ok"] is True
    for prov in ("coverr", "giphy", "ia_imagen"):
        assert estado[prov] == {"ok": False, "motivo": "sin API key"}
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_catalogo_fuentes.py -q`
Expected: FAIL. `ValueError` en `fuentes.crear(..., "video", ...)` y `KeyError: 'pixabay'`.

- [ ] **Paso 3: implementar**

`src/fuentes.py`:
```python
PROVIDERS_IMAGEN = ("carpeta", "ig_accounts", "pinterest", "pexels", "unsplash", "banco", "covers",
                    "pixabay", "openverse", "giphy", "ia_imagen")
# Editor v2 (plan 3): fuentes de video del panel de assets. 'ig_seguidos' lo agrega el plan 5.
PROVIDERS_VIDEO = ("carpeta", "pexels", "pixabay", "coverr", "giphy")
```
y
```python
_CATALOGO = {"imagen": PROVIDERS_IMAGEN, "info": PROVIDERS_INFO, "video": PROVIDERS_VIDEO}
```
⚠️ Revisar si `fuentes.listar(..., kind=...)` o el router validan `kind in ("imagen","info")` por separado. Buscarlo con `grep -n "\"info\"" src/fuentes.py api/routers/fuentes_api.py`, y en cada validación de esos dos literales agregar `"video"`.

`api/routers/fuentes_api.py`:
```python
_MOTIVO_KEY = {"pexels": "PEXELS_API_KEY", "unsplash": "UNSPLASH_ACCESS_KEY",
               "newsapi": "NEWSAPI_KEY", "pixabay": "PIXABAY_API_KEY",
               "coverr": "COVERR_API_KEY", "giphy": "GIPHY_API_KEY", "ia_imagen": "FAL_KEY"}
```
y la tupla de `estado_fuentes`:
```python
    for prov in ("pexels", "unsplash", "pinterest", "newsapi", "rss", "banco",
                 "covers", "carpeta", "ig_accounts", "manual",
                 "pixabay", "openverse", "coverr", "giphy", "ia_imagen"):
```

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_assets_catalogo_fuentes.py tests/ -q -k "fuentes or sources"`
Expected: PASS. Si una prueba existente compara `estado_fuentes` contra un dict exacto de 10 claves, se actualiza su expected con las 5 nuevas y se dice en el commit.

- [ ] **Paso 5: commit**
```bash
git add src/fuentes.py api/routers/fuentes_api.py tests/test_assets_catalogo_fuentes.py
git commit -m "fuentes: kind video y providers Pixabay, Openverse, Coverr, GIPHY, IA

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: router `api/routers/assets.py`

**Files:**
- Create: `api/routers/assets.py`
- Modify: `api/app.py` (`app.include_router(assets.router)` junto a `fuentes_api.router`)
- Test: `tests/test_api_assets.py`

**Interfaces (todas bajo `/brands/{slug}`):**

| Método | Ruta | Rol | Respuesta |
|---|---|---|---|
| GET | `/assets/buscar?q=&tipo=imagen&proveedores=a,b&n=20` | editor | `{"resultados": [Candidata], "avisos": [str]}` |
| GET | `/assets?tipo=` | editor | `[fila brand_assets + "src"]` (sin descartadas) |
| POST | `/assets/importar` | editor | 201, fila + `src` |
| POST | `/assets/subir` (multipart `archivo`) | editor | 201, fila + `src` |
| PATCH | `/assets/{aid}` `{descartada: bool}` | editor | fila + `src` |
| POST | `/assets/{aid}/recorte` | editor | 202, `{"job_id": int}` |

El endpoint `GET /brands/{slug}/files/assets/{archivo}` es del plan 1 y aquí **no** se define.

- [ ] **Paso 1: escribir la prueba que falla**

`tests/test_api_assets.py`:
```python
"""API de assets: buscar, listar, importar, subir, descartar, recortar; aislamiento."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from src import assets, db
from src.assets import Candidata, biblioteca, buscar


def _png(w=6, h=4) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), "green").save(b, "PNG")
    return b.getvalue()


@pytest.fixture()
def entorno(api_cliente, tmp_path, monkeypatch):
    cli, cx, H = api_cliente
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    a1 = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    a2 = db.insert(cx, "accounts", slug="m2", ig_handle="@m2", nombre="M2", ciudad="GDL")
    uid = H.usuario("ed@x.com", marcas=[(a1, "editor")])
    H.login(uid)
    return cli, cx, a1, a2


def test_buscar_devuelve_resultados_y_avisos(entorno, monkeypatch) -> None:
    cli, cx, a1, _ = entorno
    vistos = {}

    def fake(cx_, aid, slug, q, *, tipo, proveedores, n):
        vistos.update(aid=aid, slug=slug, q=q, tipo=tipo, proveedores=proveedores, n=n)
        return [Candidata("pexels", "1", tipo, "https://images.pexels.com/1.jpg", "p", 1, 1,
                          "A", "Pexels License", None)], ["unsplash: falta UNSPLASH_ACCESS_KEY"]
    monkeypatch.setattr(buscar, "buscar_con_avisos", fake)
    r = cli.get("/brands/m1/assets/buscar", params={"q": "playa", "tipo": "video",
                                                     "proveedores": "pexels,unsplash", "n": 5})
    assert r.status_code == 200
    assert r.json()["resultados"][0]["url"] == "https://images.pexels.com/1.jpg"
    assert r.json()["avisos"] == ["unsplash: falta UNSPLASH_ACCESS_KEY"]
    assert vistos == {"aid": a1, "slug": "m1", "q": "playa", "tipo": "video",
                      "proveedores": ["pexels", "unsplash"], "n": 5}
    assert cli.get("/brands/m1/assets/buscar", params={"q": "x", "n": 999}).status_code == 422
    assert cli.get("/brands/m1/assets/buscar", params={"q": "x", "tipo": "audio"}).status_code == 422


def test_subir_listar_descartar(entorno) -> None:
    cli, cx, a1, _ = entorno
    r = cli.post("/brands/m1/assets/subir", files={"archivo": ("x.png", _png(), "image/png")})
    assert r.status_code == 201
    fila = r.json()
    assert fila["proveedor"] == "subida" and fila["src"] == f"assets/{fila['archivo']}"
    malo = cli.post("/brands/m1/assets/subir",
                    files={"archivo": ("x.png", b"<script>", "image/png")})
    assert malo.status_code == 422
    assert [f["id"] for f in cli.get("/brands/m1/assets").json()] == [fila["id"]]
    assert cli.patch(f"/brands/m1/assets/{fila['id']}", json={"descartada": True}).status_code == 200
    assert cli.get("/brands/m1/assets").json() == []


def test_importar_valida_proveedor_y_url(entorno, monkeypatch) -> None:
    cli, cx, a1, _ = entorno
    base = {"proveedor": "pexels", "id_origen": "1", "tipo": "imagen",
            "url": "https://images.pexels.com/1.jpg", "preview_url": "", "ancho": None,
            "alto": None, "autor": None, "licencia": None, "url_origen": None}
    assert cli.post("/brands/m1/assets/importar",
                    json={**base, "proveedor": "nope"}).status_code == 422
    assert cli.post("/brands/m1/assets/importar",
                    json={**base, "url": "local:fotos/a.png"}).status_code == 422
    assert cli.post("/brands/m1/assets/importar",
                    json={**base, "url": "file:///etc/passwd"}).status_code == 422

    def fake_importar(cx_, aid, slug, cand, *, tags=None):
        assert (aid, slug, cand.proveedor, tags) == (a1, "m1", "pexels", ["playa"])
        fila, _ = biblioteca.guardar_bytes(cx_, aid, slug, _png(), proveedor="pexels")
        return fila
    monkeypatch.setattr(biblioteca, "importar", fake_importar)
    r = cli.post("/brands/m1/assets/importar", json={**base, "tags": ["playa"]})
    assert r.status_code == 201 and r.json()["src"].startswith("assets/")

    def invalido(*a, **k):
        raise biblioteca.AssetInvalido("host no público: x")
    monkeypatch.setattr(biblioteca, "importar", invalido)
    r = cli.post("/brands/m1/assets/importar", json=base)
    assert r.status_code == 422 and "host no público" in r.text


def test_recorte_encola_job(entorno) -> None:
    cli, cx, a1, _ = entorno
    fila, _ = biblioteca.guardar_bytes(cx, a1, "m1", _png(), proveedor="subida")
    r = cli.post(f"/brands/m1/assets/{fila['id']}/recorte")
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert (job["tipo"], job["account_id"]) == ("asset.recorte", a1)


def test_api_assets_aislado_por_marca(entorno) -> None:
    cli, cx, a1, a2 = entorno
    ajeno, _ = biblioteca.guardar_bytes(cx, a2, "m2", _png(), proveedor="subida")
    # por la marca propia con id ajeno: 404
    assert cli.post(f"/brands/m1/assets/{ajeno['id']}/recorte").status_code == 404
    assert cli.patch(f"/brands/m1/assets/{ajeno['id']}",
                     json={"descartada": True}).status_code == 404
    assert cli.get("/brands/m1/assets").json() == []
    local = {"proveedor": "carpeta", "id_origen": "x", "tipo": "imagen",
             "url": f"local:assets/{ajeno['archivo']}", "preview_url": "", "ancho": None,
             "alto": None, "autor": None, "licencia": None, "url_origen": None}
    assert cli.post("/brands/m1/assets/importar", json=local).status_code == 422
    # por la marca ajena: sin rol
    assert cli.get("/brands/m2/assets").status_code in (403, 404)
    assert cli.post(f"/brands/m2/assets/{ajeno['id']}/recorte").status_code in (403, 404)
    assert db.rows(cx, "SELECT id FROM jobs WHERE tipo = 'asset.recorte'") == []
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_api_assets.py -q`
Expected: FAIL con 404 en todas las rutas.

- [ ] **Paso 3: implementar** `api/routers/assets.py`:
```python
"""Assets de la marca para el editor v2: buscar en proveedores, importar a la
biblioteca, subir, descartar y quitar fondo (job). Los bytes se sirven en
GET /brands/{slug}/files/assets/{archivo} (plan 1), no aquí."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, no_encontrado
from src import db, jobs
from src.assets import Candidata, biblioteca, buscar
from src.assets.proveedores import PROVEEDORES

router = APIRouter(prefix="/brands/{slug}", tags=["assets"])

_CHUNK = 64 * 1024


def _con_src(fila: dict) -> dict:
    return {**dict(fila), "src": f"assets/{fila['archivo']}"}


def _asset_de_marca(cx, account_id: int, aid: int) -> dict:
    fila = db.get(cx, "brand_assets", aid)
    if fila is None or fila["account_id"] != account_id:
        raise no_encontrado("ese asset")
    return dict(fila)


class CandidataIn(BaseModel):
    proveedor: str
    id_origen: str = Field(max_length=200)
    tipo: Literal["imagen", "video"]
    url: str = Field(max_length=2000)
    preview_url: str = Field("", max_length=2000)
    ancho: int | None = None
    alto: int | None = None
    autor: str | None = Field(None, max_length=200)
    licencia: str | None = Field(None, max_length=100)
    url_origen: str | None = Field(None, max_length=2000)
    ig_handle: str | None = Field(None, max_length=60)
    source_post_id: str | None = Field(None, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)


class AssetPatch(BaseModel):
    descartada: bool


@router.get("/assets/buscar")
def buscar_assets(slug: str, q: str = Query(..., min_length=1, max_length=200),
                  tipo: Literal["imagen", "video"] = "imagen",
                  proveedores: str | None = Query(None, max_length=200),
                  n: int = Query(20, ge=1, le=60),
                  user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user)
    lista = [p.strip() for p in proveedores.split(",") if p.strip()] if proveedores else None
    resultados, avisos = buscar.buscar_con_avisos(cx, marca["id"], marca["slug"], q, tipo=tipo,
                                                  proveedores=lista, n=n)
    return {"resultados": [c.a_dict() for c in resultados], "avisos": avisos}


@router.get("/assets")
def listar_assets(slug: str, tipo: Literal["imagen", "video"] | None = None,
                  user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    marca, _ = marca_para(slug, cx, user)
    sql = "SELECT * FROM brand_assets WHERE account_id = ? AND descartada = 0"
    params: list = [marca["id"]]
    if tipo:
        sql += " AND tipo = ?"
        params.append(tipo)
    return [_con_src(f) for f in db.rows(cx, sql + " ORDER BY id DESC LIMIT 500", tuple(params))]


@router.post("/assets/importar", status_code=201)
def importar_asset(slug: str, datos: CandidataIn, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user)
    if datos.proveedor not in PROVEEDORES:
        raise ApiError(422, "validacion", "Proveedor desconocido", "proveedor")
    es_local = datos.url.startswith("local:")
    if es_local != (datos.proveedor == "carpeta") or (
            not es_local and not datos.url.startswith("https://")):
        raise ApiError(422, "validacion", "URL inválida para ese proveedor", "url")
    cand = Candidata(**datos.model_dump(exclude={"tags"}))
    tags = [t.strip()[:40] for t in datos.tags if t.strip()] or None
    try:
        fila = biblioteca.importar(cx, marca["id"], marca["slug"], cand, tags=tags)
    except (biblioteca.AssetInvalido, ValueError) as e:
        raise ApiError(422, "validacion", str(e)[:200], "url") from e
    except Exception as e:  # noqa: BLE001 — red del origen caída o 4xx/5xx
        raise ApiError(502, "origen", "No se pudo descargar del proveedor") from e
    return _con_src(fila)


@router.post("/assets/subir", status_code=201)
def subir_asset(slug: str, archivo: UploadFile = File(...),
                user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user)
    tope = max(biblioteca.TOPES.values())
    piezas, total = [], 0
    while chunk := archivo.file.read(_CHUNK):
        total += len(chunk)
        if total > tope:
            raise ApiError(422, "validacion", "archivo demasiado grande", "archivo")
        piezas.append(chunk)
    try:
        fila, _ = biblioteca.guardar_bytes(cx, marca["id"], marca["slug"], b"".join(piezas),
                                           proveedor="subida", meta={"licencia": "propia"})
    except (biblioteca.AssetInvalido, ValueError) as e:
        raise ApiError(422, "validacion", str(e)[:200], "archivo") from e
    return _con_src(fila)


@router.patch("/assets/{aid}")
def editar_asset(slug: str, aid: int, datos: AssetPatch, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user)
    _asset_de_marca(cx, marca["id"], aid)
    db.update(cx, "brand_assets", aid, descartada=int(datos.descartada))
    cx.commit()
    return _con_src(db.get(cx, "brand_assets", aid))


@router.post("/assets/{aid}/recorte", status_code=202)
def recortar_asset(slug: str, aid: int, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user)
    asset = _asset_de_marca(cx, marca["id"], aid)
    if asset["tipo"] != "imagen":
        raise ApiError(422, "validacion", "Solo se puede quitar el fondo a imágenes", "tipo")
    jid = jobs.crear(cx, "asset.recorte", marca["id"], {"asset_id": aid},
                     creado_por=user["id"])
    return {"job_id": jid}
```
⚠️ Hay que confirmar tres cosas contra el código:
- que `user["id"]` es la clave del usuario en `usuario_actual` (en otros routers se pasa `creado_por=user["id"]`; verificar con `grep -n "creado_por=" api/routers/*.py`);
- que `marca_para` devuelve la fila con `"id"` y `"slug"`;
- que `ApiError` acepta 3 argumentos (sin `campo`) para el 502.

En `api/app.py`, importar `assets` en el bloque de routers y registrar `app.include_router(assets.router)` junto a `fuentes_api.router`.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_api_assets.py -q`
Expected: PASS.

- [ ] **Paso 5: revisar el endpoint de archivos del plan 1**

Run: `grep -n "files/assets" -A25 api/routers/*.py`
Revisar que el `FileResponse` de `files/assets/{archivo}` acepte `.gif`, `.mp4` y `.webm` además de `.png`/`.jpg`/`.webp`, y que lea de `data/brands/<slug>/assets/`, que es la misma raíz que `assets.BRANDS_DIR`.

- Si su whitelist de extensiones no incluye esas tres, **no** se edita aquí. Se anota en `## Desviaciones` del plan 1 y se avisa a Ricardo, porque ese endpoint es del plan 1 según el contrato.
- Si el plan 1 todavía no está mergeado en la rama, se deja marcado ⚠️ en el commit.

- [ ] **Paso 6: commit**
```bash
git add api/routers/assets.py api/app.py tests/test_api_assets.py
git commit -m "api: router de assets (buscar, importar, subir, descartar, recorte)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: tipografías de Fontsource

**Files:**
- Create: `src/plantillas/fontsource.py`, `tests/fixtures/assets/fontsource_lista.json`, `tests/fixtures/assets/fontsource_bebas.json`
- Modify: `api/routers/assets.py` (dos rutas)
- Test: `tests/test_fontsource.py`

**Interfaces:**
```python
# src/plantillas/fontsource.py
def catalogo(q: str = "", *, limite: int = 50) -> list[dict]       # [{id, familia, categoria, pesos}]
def detalle(fid: str) -> dict
def instalar(cx, account_id: int, slug: str, fid: str, peso: int = 400) -> dict  # fila de brand_fonts
# api/routers/assets.py
# GET  /brands/{slug}/tipografias/catalogo?q=   (editor)
# POST /brands/{slug}/tipografias {id, peso}     (manager) -> 201 {familia, archivo, propia: true}
```
Hay tres decisiones de diseño:
- Se baja **un solo** archivo TTF por familia, el peso pedido en estilo normal y subset latin. TTF porque Chromium lo renderiza y `_TIPO_FUENTE` ya lo acepta.
- El archivo va a `assets.BRANDS_DIR/<slug>/fonts/<id>-<peso>-normal.ttf`, y `brand_fonts.archivo` guarda la ruta **absoluta**, como el resto de fuentes propias que lee `css_font_faces`.
- Reinstalar la misma familia hace upsert (`ON CONFLICT(account_id, familia)`).

- [ ] **Paso 1: fixtures y prueba que falla**

`tests/fixtures/assets/fontsource_lista.json`, con la forma de `GET https://api.fontsource.org/v1/fonts?subsets=latin&type=google` (recortado):
```json
[
  {"id": "bebas-neue", "family": "Bebas Neue", "subsets": ["latin"], "weights": [400], "styles": ["normal"], "category": "display", "license": "OFL-1.1", "type": "google"},
  {"id": "inter", "family": "Inter", "subsets": ["latin"], "weights": [100, 400, 700, 900], "styles": ["normal", "italic"], "category": "sans-serif", "license": "OFL-1.1", "type": "google"}
]
```
`tests/fixtures/assets/fontsource_bebas.json`, con la forma de `GET https://api.fontsource.org/v1/fonts/bebas-neue` (recortado):
```json
{"id": "bebas-neue", "family": "Bebas Neue", "weights": [400], "styles": ["normal"], "license": "OFL-1.1",
 "variants": {"400": {"normal": {"latin": {"url": {
   "woff2": "https://cdn.jsdelivr.net/fontsource/fonts/bebas-neue@latest/latin-400-normal.woff2",
   "ttf": "https://cdn.jsdelivr.net/fontsource/fonts/bebas-neue@latest/latin-400-normal.ttf"}}}}}}
```
`tests/test_fontsource.py`:
```python
"""Fontsource: catálogo con caché, instalación validada a brand_fonts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import assets, db
from src.assets import biblioteca
from src.assets.proveedores import base
from src.plantillas import fontsource, fuentes_tipograficas

FIX = Path(__file__).parent / "fixtures" / "assets"
TTF = b"\x00\x01\x00\x00" + b"\x00" * 200


@pytest.fixture()
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    yield c
    c.close()


@pytest.fixture()
def api(monkeypatch):
    llamadas = []

    def fake_get(url, *, params=None, headers=None):
        llamadas.append(url)
        if url.endswith("/v1/fonts"):
            return json.loads((FIX / "fontsource_lista.json").read_text())
        return json.loads((FIX / "fontsource_bebas.json").read_text())
    monkeypatch.setattr(base, "get_json", fake_get)
    return llamadas


def test_catalogo_filtra_y_cachea(cx, api) -> None:
    res = fontsource.catalogo("bebas")
    assert res == [{"id": "bebas-neue", "familia": "Bebas Neue", "categoria": "display",
                    "pesos": [400]}]
    assert len(fontsource.catalogo("")) == 2
    assert api == ["https://api.fontsource.org/v1/fonts"]   # segunda vez sale de caché


def test_instalar_baja_ttf_y_registra(cx, api, monkeypatch) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    pedidas = []

    def fake_descargar(url, *, hosts, tope):
        pedidas.append((url, hosts, tope))
        return TTF
    monkeypatch.setattr(biblioteca, "descargar", fake_descargar)
    fila = fontsource.instalar(cx, aid, "m1", "bebas-neue", 400)
    assert fila["familia"] == "Bebas Neue"
    ruta = Path(fila["archivo"])
    assert ruta.is_absolute() and ruta.name == "bebas-neue-400-normal.ttf"
    assert ruta.read_bytes() == TTF
    assert pedidas[0][1] == ("cdn.jsdelivr.net",) and pedidas[0][0].endswith(".ttf")
    cat = {f["familia"]: f for f in fuentes_tipograficas.catalogo(cx, aid)}
    assert cat["Bebas Neue"]["propia"] is True
    fontsource.instalar(cx, aid, "m1", "bebas-neue", 400)       # upsert, sin duplicar
    assert len(db.rows(cx, "SELECT id FROM brand_fonts WHERE account_id = ?", (aid,))) == 1


def test_instalar_rechaza(cx, api, monkeypatch) -> None:
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    monkeypatch.setattr(biblioteca, "descargar", lambda url, **k: b"<html>")
    with pytest.raises(ValueError):
        fontsource.instalar(cx, aid, "m1", "bebas-neue", 400)      # no es TTF
    with pytest.raises(ValueError):
        fontsource.instalar(cx, aid, "m1", "../etc", 400)          # id inválido
    monkeypatch.setattr(biblioteca, "descargar", lambda url, **k: TTF)
    with pytest.raises(ValueError):
        fontsource.instalar(cx, aid, "m1", "bebas-neue", 700)      # peso inexistente


def test_api_tipografias(api_cliente, tmp_path, monkeypatch) -> None:
    cli, cx, H = api_cliente
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(assets, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(base, "get_json", lambda url, **k: json.loads(
        (FIX / ("fontsource_lista.json" if url.endswith("/fonts") else "fontsource_bebas.json"))
        .read_text()))
    monkeypatch.setattr(biblioteca, "descargar", lambda url, **k: TTF)
    aid = db.insert(cx, "accounts", slug="m1", ig_handle="@m1", nombre="M1", ciudad="GDL")
    H.login(H.usuario("ed@x.com", marcas=[(aid, "editor")]))
    assert cli.get("/brands/m1/tipografias/catalogo", params={"q": "inter"}).json()[0]["id"] == "inter"
    assert cli.post("/brands/m1/tipografias", json={"id": "bebas-neue"}).status_code == 403
    H.login(H.usuario("man@x.com", marcas=[(aid, "manager")]))
    r = cli.post("/brands/m1/tipografias", json={"id": "bebas-neue", "peso": 400})
    assert r.status_code == 201 and r.json()["familia"] == "Bebas Neue"
```

- [ ] **Paso 2: correr y ver que falla**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_fontsource.py -q`
Expected: FAIL con `ImportError: cannot import name 'fontsource'`.

- [ ] **Paso 3: implementar** `src/plantillas/fontsource.py`:
```python
"""Tipografías de Fontsource (Google Fonts y más, OFL) instaladas como fuente
propia de la marca. Se baja UN archivo TTF (peso pedido, normal, latin) del CDN
de jsDelivr con la misma descarga cerrada de assets."""
from __future__ import annotations

import json
import os
import re
import time

from src import assets, db
from src.assets import biblioteca
from src.assets.proveedores import base

_API = "https://api.fontsource.org/v1/fonts"
_TTL = 24 * 3600
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,80}\Z")
_TOPE = 5 * 1024 * 1024
_MAGIC_TTF = (b"\x00\x01\x00\x00", b"OTTO", b"true")


def _lista() -> list[dict]:
    ruta = assets.CACHE_DIR / "fontsource" / "catalogo.json"
    if ruta.is_file() and time.time() - ruta.stat().st_mtime < _TTL:
        return json.loads(ruta.read_text())
    datos = base.get_json(_API, params={"subsets": "latin", "type": "google"})
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".part")
    tmp.write_text(json.dumps(datos))
    os.replace(tmp, ruta)
    return datos


def catalogo(q: str = "", *, limite: int = 50) -> list[dict]:
    q = (q or "").strip().lower()
    out = []
    for f in _lista():
        if q and q not in f.get("family", "").lower() and q not in f.get("id", ""):
            continue
        out.append({"id": f["id"], "familia": f["family"], "categoria": f.get("category"),
                    "pesos": f.get("weights", [])})
        if len(out) >= limite:
            break
    return out


def detalle(fid: str) -> dict:
    if not _ID_RE.match(fid or ""):
        raise ValueError("id de tipografía inválido")
    return base.get_json(f"{_API}/{fid}")


def instalar(cx, account_id: int, slug: str, fid: str, peso: int = 400) -> dict:
    info = detalle(fid)
    try:
        url = info["variants"][str(peso)]["normal"]["latin"]["url"]["ttf"]
    except (KeyError, TypeError) as e:
        raise ValueError("esa tipografía no tiene ese peso en latin normal") from e
    datos = biblioteca.descargar(url, hosts=("cdn.jsdelivr.net",), tope=_TOPE)
    if not datos.startswith(_MAGIC_TTF):
        raise ValueError("el archivo descargado no es una tipografía TTF/OTF")
    biblioteca.ruta_de(slug, "x.ttf")  # valida el slug con la misma regla
    destino = assets.BRANDS_DIR / slug / "fonts" / f"{fid}-{int(peso)}-normal.ttf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".part")
    tmp.write_bytes(datos)
    os.replace(tmp, destino)
    familia = str(info.get("family") or fid)[:80]
    cx.execute("INSERT INTO brand_fonts (account_id, familia, archivo) VALUES (?, ?, ?) "
               "ON CONFLICT(account_id, familia) DO UPDATE SET archivo = excluded.archivo",
               (account_id, familia, str(destino.resolve())))
    cx.commit()
    return {"familia": familia, "archivo": str(destino.resolve()), "propia": True}
```
Agregar a `api/routers/assets.py`:
```python
from src.plantillas import fontsource


class TipografiaIn(BaseModel):
    id: str = Field(max_length=80)
    peso: int = Field(400, ge=100, le=900)


@router.get("/tipografias/catalogo")
def catalogo_tipografias(slug: str, q: str = Query("", max_length=60),
                         user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    marca_para(slug, cx, user)
    try:
        return fontsource.catalogo(q)
    except Exception as e:  # noqa: BLE001
        raise ApiError(502, "origen", "Fontsource no respondió") from e


@router.post("/tipografias", status_code=201)
def instalar_tipografia(slug: str, datos: TipografiaIn, user: dict = Depends(usuario_actual),
                        cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    try:
        return fontsource.instalar(cx, marca["id"], marca["slug"], datos.id, datos.peso)
    except (ValueError, biblioteca.AssetInvalido) as e:
        raise ApiError(422, "validacion", str(e)[:200], "id") from e
    except Exception as e:  # noqa: BLE001
        raise ApiError(502, "origen", "No se pudo bajar la tipografía") from e
```
El import de `fontsource` va arriba con los demás `src` (orden de isort).

⚠️ Faltan dos verificaciones:
- Que Fontsource siga sirviendo `url.ttf` en `variants`. La forma viene de la doc de su API v1 y no se probó en vivo. Probarlo con:
  ```bash
  curl -s https://api.fontsource.org/v1/fonts/bebas-neue | python3 -m json.tool | head -30
  ```
- El `marca_para` de una marca sin acceso para el rol editor: confirmar que devuelve 403. La prueba lo asume.

- [ ] **Paso 4: correr y ver que pasa**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_fontsource.py tests/test_api_assets.py -q`
Expected: PASS.

- [ ] **Paso 5: commit**
```bash
git add src/plantillas/fontsource.py api/routers/assets.py tests/fixtures/assets/fontsource_*.json tests/test_fontsource.py
git commit -m "tipografías: instalar fuentes de Fontsource como propias de la marca

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Ajustes, fuentes de video, providers nuevos y tipografías (frontend)

**Files:**
- Modify:
  - `frontend/hooks/use-sources.ts`
  - `frontend/app/b/[slug]/settings/_components/fuente-dialog.tsx`
  - `frontend/app/b/[slug]/settings/_components/fuentes-lista.tsx`
  - `frontend/app/b/[slug]/settings/_components/tab-fuentes.tsx`
  - `frontend/app/b/[slug]/settings/_components/tab-estilos.tsx`
  - `frontend/lib/fuentes.ts`
  - `frontend/lib/secretos.ts`
- Create: `frontend/hooks/use-tipografias.ts`, `frontend/app/b/[slug]/settings/_components/tipografias-panel.tsx`

**Interfaces:**
```ts
export type SourceKind = "imagen" | "info" | "video";
export function useTodasSources(slug: string): UseQueryResult<Source[], ApiError>;
export function useCatalogoTipografias(slug: string, q: string);
export function useInstalarTipografia(slug: string);   // invalida ["fuentes", slug]
```
Este task es solo UI de configuración y no tiene una prueba unitaria propia. La verificación es `tsc` + `lint`, más la prueba manual del paso 4.

- [ ] **Paso 1: tipos y hooks**

`frontend/hooks/use-sources.ts`:
- `export type SourceKind = "imagen" | "info" | "video";`
- En `useCrearSource`, `useEditarSource` y `useOrdenarSources`, cada `invalidateQueries` pasa a ser `qc.invalidateQueries({ queryKey: ["sources", slug] })`. Es un prefijo, así que invalida los tres kinds y también `"todas"`. Con eso se borran las dos invalidaciones fijas de `imagen`/`info` en las líneas 80–83.
- Agregar:
```ts
// Todas las fuentes de la marca (los tres kinds). El reordenamiento manda la
// lista COMPLETA de ids al backend, así que la lista de un kind necesita los demás.
export function useTodasSources(slug: string) {
  return useQuery<Source[], ApiError>({
    queryKey: ["sources", slug, "todas"],
    queryFn: () => get<Source[]>(`/brands/${slug}/sources`),
    enabled: !!slug,
    retry: false,
  });
}
```

`frontend/hooks/use-tipografias.ts`:
```ts
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post } from "@/lib/api";

export interface TipografiaCatalogo {
  id: string;
  familia: string;
  categoria: string | null;
  pesos: number[];
}

export function useCatalogoTipografias(slug: string, q: string) {
  return useQuery<TipografiaCatalogo[], ApiError>({
    queryKey: ["tipografias-catalogo", slug, q],
    queryFn: () =>
      get<TipografiaCatalogo[]>(
        `/brands/${slug}/tipografias/catalogo?q=${encodeURIComponent(q)}`,
      ),
    enabled: !!slug,
    staleTime: 60 * 60_000,
    retry: false,
  });
}

export function useInstalarTipografia(slug: string) {
  const qc = useQueryClient();
  return useMutation<{ familia: string }, ApiError, { id: string; peso: number }>({
    mutationFn: (vars) => post(`/brands/${slug}/tipografias`, vars),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["fuentes", slug] }),
  });
}
```

- [ ] **Paso 2: diálogo, lista y pestaña de fuentes**

`fuente-dialog.tsx`, línea 33:
```ts
// Pinterest sigue en el backend (slideshow v1) pero ya no se ofrece: su scraping
// no es estable. ig_seguidos lo agrega el plan 5.
const PROVIDERS: Record<SourceKind, string[]> = {
  imagen: ["carpeta", "pexels", "unsplash", "pixabay", "openverse", "giphy",
           "ig_accounts", "banco", "covers", "ia_imagen"],
  info: ["rss", "newsapi"],
  video: ["carpeta", "pexels", "pixabay", "coverr", "giphy"],
};
```
Línea 42:
```ts
const SIN_CONFIG_ESTRICTA = new Set(["carpeta", "pinterest", "pexels", "unsplash", "banco",
  "covers", "pixabay", "openverse", "coverr", "giphy", "ia_imagen"]);
```
Si el diálogo pinta un aviso por proveedor, agregar el de `ia_imagen`. Se pone debajo del select cuando `provider === "ia_imagen"`:
```tsx
{provider === "ia_imagen" && (
  <p className="text-xs text-amber-600">
    De pago: cada búsqueda genera hasta 4 imágenes con fal.ai y cobra a la llave FAL_KEY de
    la marca. Solo corre cuando se pide «Generar con IA» en el editor.
  </p>
)}
```
⚠️ Hay que leer cómo se llama la variable del provider elegido en ese componente y usar ese nombre.

`fuentes-lista.tsx`: reemplazar
```ts
const otroKind: SourceKind = kind === "imagen" ? "info" : "imagen";
const otroQuery = useSources(slug, otroKind);
```
por
```ts
const todasQuery = useTodasSources(slug);
```
y dentro de `handleDragEnd`:
```ts
if (!todasQuery.data) {
  toast.error("No se pudo reordenar: faltan cargar las demás fuentes");
  return;
}
const idsCompletos = [
  ...nuevo.map((s) => s.id),
  ...todasQuery.data.filter((s) => s.kind !== kind).map((s) => s.id),
];
```
Además, ajustar el import (`useTodasSources` sí, `SourceKind` solo si todavía se usa). ⚠️ Confirmar que `Source` trae el campo `kind`; el backend lo devuelve en `_resumen_fuente`.

`tab-fuentes.tsx`: después del bloque `FuentesLista kind="imagen"` y su `Separator`, agregar
```tsx
<FuentesLista slug={slug} kind="video" titulo="Fuentes de video" puedeEditar={puedeEditar} />
<Separator />
```
Usar las mismas props que recibe la de imagen; si se llaman distinto, copiarlas tal cual.

`frontend/lib/fuentes.ts`, en `FUENTE_LABELS`:
```ts
  pixabay: "Pixabay",
  openverse: "Openverse",
  coverr: "Coverr",
  giphy: "GIPHY",
  ia_imagen: "IA (fal.ai, de pago)",
```
`frontend/lib/secretos.ts`, en `SECRETO_INFO`:
```ts
  PIXABAY_API_KEY: { label: "Fotos y video de Pixabay", ayuda: "Gratis en pixabay.com/api/docs", grupo: "imagenes" },
  COVERR_API_KEY: { label: "Video de Coverr", ayuda: "Gratis en coverr.co/developers", grupo: "imagenes" },
  GIPHY_API_KEY: { label: "GIFs de GIPHY", ayuda: "Gratis en developers.giphy.com", grupo: "imagenes" },
  FAL_KEY: { label: "IA de imágenes (fal.ai)", ayuda: "De pago, se cobra por imagen generada. fal.ai/dashboard/keys", grupo: "imagenes" },
```

- [ ] **Paso 3: panel de tipografías**

`frontend/app/b/[slug]/settings/_components/tipografias-panel.tsx`:
```tsx
"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { useCatalogoTipografias, useInstalarTipografia } from "@/hooks/use-tipografias";

export function TipografiasPanel({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const [q, setQ] = useState("");
  const [buscado, setBuscado] = useState("");
  const catalogo = useCatalogoTipografias(slug, buscado);
  const instalar = useInstalarTipografia(slug);

  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-medium">Tipografías de Fontsource</h3>
        <p className="text-xs text-muted-foreground">
          Se instalan como fuentes propias de la marca y aparecen en el editor.
        </p>
      </div>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setBuscado(q.trim());
        }}
      >
        <Label htmlFor="tipo-q" className="sr-only">Buscar tipografía</Label>
        <Input id="tipo-q" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Bebas, Inter, Playfair…" maxLength={60} />
        <Button type="submit" variant="secondary">Buscar</Button>
      </form>
      {catalogo.isLoading && <Skeleton className="h-24 w-full" />}
      {catalogo.error && (
        <p className="text-xs text-destructive">No se pudo cargar el catálogo.</p>
      )}
      <ul className="max-h-72 divide-y overflow-y-auto rounded-md border">
        {(catalogo.data ?? []).map((t) => (
          <li key={t.id} className="flex items-center justify-between gap-2 px-3 py-2">
            <div className="min-w-0">
              <p className="truncate text-sm">{t.familia}</p>
              <p className="text-xs text-muted-foreground">
                {t.categoria ?? "—"} · {t.pesos.join(", ")}
              </p>
            </div>
            {puedeEditar && (
              <Button
                size="sm"
                variant="outline"
                disabled={instalar.isPending}
                onClick={() =>
                  instalar.mutate(
                    { id: t.id, peso: t.pesos.includes(400) ? 400 : t.pesos[0] },
                    {
                      onSuccess: (r) => toast.success(`${r.familia} instalada`),
                      onError: (e) => toast.error(e.message),
                    },
                  )
                }
              >
                Instalar
              </Button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
```
En `tab-estilos.tsx`, antes del `</div>` de cierre de `TabEstilos`:
```tsx
      <Separator />
      <TipografiasPanel slug={slug} puedeEditar={puedeEditar} />
```
con los imports de `Separator` (si no estaba) y de `TipografiasPanel`.

- [ ] **Paso 4: verificar**

Run: `cd frontend && pnpm lint && pnpm tsc --noEmit`
Expected: 0 errores.

Prueba manual: levantar el api y el frontend con los comandos de dev del README del repo y entrar a `http://localhost:3000/b/<slug>/settings`. Revisar:
- la pestaña Fuentes muestra «Fuentes de video»;
- agregar Pexels video funciona;
- arrastrar una fuente de imagen no rompe el orden de las de info y video;
- Pinterest ya no aparece;
- en Estilos, buscar «bebas» e instalar la deja en el selector de fuentes del editor.

⚠️ Esto **no** lo cubre ninguna prueba automática, y así se reporta.

- [ ] **Paso 5: commit**
```bash
git add frontend/hooks/use-sources.ts frontend/hooks/use-tipografias.ts frontend/lib/fuentes.ts frontend/lib/secretos.ts "frontend/app/b/[slug]/settings/_components"
git commit -m "ajustes: fuentes de video, proveedores nuevos y tipografías de Fontsource

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: pestaña «Assets» del editor

**Files:**
- Create:
  - `frontend/lib/assets.ts` y `frontend/lib/assets.test.ts`
  - `frontend/hooks/use-assets.ts`
  - `frontend/app/b/[slug]/templates/[id]/_components/panel-assets.tsx`
- Modify: `frontend/app/b/[slug]/templates/[id]/page.tsx` (una pestaña más en `PanelLateral`)

**Interfaces:**
```ts
// frontend/lib/assets.ts
export interface Candidata { proveedor; id_origen; tipo: "imagen" | "video"; url; preview_url;
  ancho: number | null; alto: number | null; autor: string | null; licencia: string | null;
  url_origen: string | null; ig_handle?: string | null; source_post_id?: string | null }
export interface Asset { id; tipo; archivo; recorte_archivo: string | null; proveedor; autor;
  licencia; url_origen; ig_handle; ancho; alto; src: string }
export function urlVisible(slug: string, url: string): string
export function idLibre(escena: Escena, base: string): string          // regex ^[a-z][a-z0-9_-]{0,31}$
export function capaDesdeAsset(asset: Asset, escena: Escena, opts?: { recorte?: boolean }): Capa
```
Dependencias del plan 2:
- `Escena`, `Capa` y `CapaImagen` de `@/lib/escena`;
- `useEditor().agregarCapa` de `@/stores/editor`;
- vitest (`pnpm vitest run`).

⚠️ La forma exacta de `CapaImagen` es la del spec §1. Si el plan 2 la nombró distinto, se ajusta `capaDesdeAsset` y su prueba, no el contrato.

- [ ] **Paso 1: escribir la prueba que falla**

`frontend/lib/assets.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import type { Escena } from "@/lib/escena";
import { capaDesdeAsset, idLibre, urlVisible, type Asset } from "@/lib/assets";

const escena = {
  v: 2,
  lienzo: { w: 1080, h: 1350, formato: "4x5", fondo: "#ffffff" },
  tokens: {},
  capas: [
    { id: "foto", nombre: "foto", tipo: "image", x: 0, y: 0, w: 10, h: 10, rot: 0,
      opacity: 1, z: 3, bloqueada: false, oculta: false, src: "assets/a.jpg",
      ajuste: "cover", mascara: "none", estilo: {} },
  ],
} as unknown as Escena;

const asset: Asset = {
  id: 9, tipo: "imagen", archivo: "ab12.jpg", recorte_archivo: "ab12-recorte.png",
  proveedor: "unsplash", autor: "Ana", licencia: "Unsplash License",
  url_origen: "https://unsplash.com/p", ig_handle: null, ancho: 2000, alto: 1000,
  src: "assets/ab12.jpg",
};

describe("assets", () => {
  it("urlVisible antepone /api a rutas del backend y deja pasar URLs externas", () => {
    expect(urlVisible("m1", "/brands/m1/files/assets/a.jpg")).toBe("/api/brands/m1/files/assets/a.jpg");
    expect(urlVisible("m1", "https://images.pexels.com/x.jpg")).toBe("https://images.pexels.com/x.jpg");
    expect(urlVisible("m1", "assets/a.jpg")).toBe("/api/brands/m1/files/assets/a.jpg");
  });

  it("idLibre no choca y respeta el regex", () => {
    expect(idLibre(escena, "foto")).toBe("foto_2");
    expect(idLibre(escena, "Foto De Ana!")).toBe("foto_de_ana");
    expect(idLibre(escena, "123")).toMatch(/^[a-z][a-z0-9_-]{0,31}$/);
  });

  it("capaDesdeAsset escala a 60% del lienzo, centra y queda arriba", () => {
    const c = capaDesdeAsset(asset, escena) as Record<string, unknown>;
    expect(c.tipo).toBe("image");
    expect(c.src).toBe("assets/ab12.jpg");
    expect(c.w).toBe(648);
    expect(c.h).toBe(324);
    expect(c.x).toBe(216);
    expect(c.y).toBe(513);
    expect(c.z).toBe(4);
    expect(c.fuente_asset).toEqual({ proveedor: "unsplash", autor: "Ana",
      licencia: "Unsplash License", url: "https://unsplash.com/p", ig_handle: null });
    const r = capaDesdeAsset(asset, escena, { recorte: true }) as Record<string, unknown>;
    expect(r.src).toBe("assets/ab12-recorte.png");
    expect(r.ajuste).toBe("contain");
  });
});
```
Las cuentas: lienzo 1080×1350 y asset 2000×1000, así que la escala es min(0.6·1080/2000, 0.6·1350/1000) = min(0.324, 0.81) = 0.324. Eso da w = 648 y h = 324, x = (1080−648)/2 = 216 e y = (1350−324)/2 = 513.

- [ ] **Paso 2: correr y ver que falla**

Run: `cd frontend && pnpm vitest run lib/assets.test.ts`
Expected: FAIL con `Failed to resolve import "@/lib/assets"`.

- [ ] **Paso 3: implementar `frontend/lib/assets.ts`**
```ts
import type { Capa, Escena } from "@/lib/escena";

export interface Candidata {
  proveedor: string;
  id_origen: string;
  tipo: "imagen" | "video";
  url: string;
  preview_url: string;
  ancho: number | null;
  alto: number | null;
  autor: string | null;
  licencia: string | null;
  url_origen: string | null;
  ig_handle?: string | null;
  source_post_id?: string | null;
}

export interface Asset {
  id: number;
  tipo: "imagen" | "video";
  archivo: string;
  recorte_archivo: string | null;
  proveedor: string;
  autor: string | null;
  licencia: string | null;
  url_origen: string | null;
  ig_handle: string | null;
  ancho: number | null;
  alto: number | null;
  src: string;
}

const ID_RE = /^[a-z][a-z0-9_-]{0,31}$/;

/** URL que el navegador puede pedir: el backend vive bajo /api. */
export function urlVisible(slug: string, url: string): string {
  if (url.startsWith("assets/")) return `/api/brands/${slug}/files/${url}`;
  if (url.startsWith("/")) return `/api${url}`;
  return url;
}

export function idLibre(escena: Escena, base: string): string {
  let limpio = base
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 28);
  if (!/^[a-z]/.test(limpio)) limpio = `img_${limpio}`.slice(0, 28);
  const usados = new Set(escena.capas.map((c) => c.id));
  if (!usados.has(limpio) && ID_RE.test(limpio)) return limpio;
  for (let i = 2; i < 1000; i++) {
    const cand = `${limpio}_${i}`;
    if (!usados.has(cand)) return cand;
  }
  return `img_${Date.now().toString(36)}`.slice(0, 32);
}

export function capaDesdeAsset(
  asset: Asset,
  escena: Escena,
  opts: { recorte?: boolean } = {},
): Capa {
  const { w: W, h: H } = escena.lienzo;
  const aw = asset.ancho ?? W;
  const ah = asset.alto ?? H;
  const escala = Math.min((0.6 * W) / aw, (0.6 * H) / ah);
  const w = Math.round(aw * escala);
  const h = Math.round(ah * escala);
  const zMax = escena.capas.reduce((m, c) => Math.max(m, c.z ?? 0), 0);
  const recorte = !!opts.recorte && !!asset.recorte_archivo;
  const archivo = recorte ? asset.recorte_archivo! : asset.archivo;
  const nombre = asset.autor ? `foto ${asset.autor}` : "foto";
  const capa = {
    id: idLibre(escena, nombre),
    nombre,
    tipo: asset.tipo === "video" ? "video" : "image",
    x: Math.round((W - w) / 2),
    y: Math.round((H - h) / 2),
    w,
    h,
    rot: 0,
    opacity: 1,
    z: zMax + 1,
    bloqueada: false,
    oculta: false,
    src: `assets/${archivo}`,
    recorte: null,
    ajuste: recorte ? "contain" : "cover",
    mascara: "none",
    estilo: {},
    fuente_asset: {
      proveedor: asset.proveedor,
      autor: asset.autor,
      licencia: asset.licencia,
      url: asset.url_origen,
      ig_handle: asset.ig_handle,
    },
  };
  return capa as unknown as Capa;
}
```
⚠️ Hay tres puntos pendientes de confirmar con el plan 2:
- **`id` de la prueba.** Con `nombre = "foto Ana"` el id sale `foto_ana`. La prueba solo verifica `idLibre` por separado.
- **Capas de video.** Si el plan 2 exige campos propios para video (`loop`, `muted`…), se agregan aquí cuando `asset.tipo === "video"`.
- **`recorte`.** Se manda `null`; si el validador del plan 1 lo exige como objeto, se ajusta.

- [ ] **Paso 4: correr y ver que pasa**

Run: `cd frontend && pnpm vitest run lib/assets.test.ts`
Expected: PASS (3 tests).

- [ ] **Paso 5: hooks** `frontend/hooks/use-assets.ts`:
```ts
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, patch, post, postForm } from "@/lib/api";
import type { Asset, Candidata } from "@/lib/assets";

export type TipoAsset = "imagen" | "video";

export function useBuscarAssets(slug: string, q: string, tipo: TipoAsset,
                                proveedores?: string[]) {
  const params = new URLSearchParams({ q, tipo, n: "30" });
  if (proveedores?.length) params.set("proveedores", proveedores.join(","));
  return useQuery<{ resultados: Candidata[]; avisos: string[] }, ApiError>({
    queryKey: ["assets-buscar", slug, tipo, q, proveedores?.join(",") ?? ""],
    queryFn: () => get(`/brands/${slug}/assets/buscar?${params.toString()}`),
    enabled: !!slug && q.trim().length >= 2,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

export function useAssets(slug: string, tipo?: TipoAsset) {
  return useQuery<Asset[], ApiError>({
    queryKey: ["assets", slug, tipo ?? "todos"],
    queryFn: () => get<Asset[]>(`/brands/${slug}/assets${tipo ? `?tipo=${tipo}` : ""}`),
    enabled: !!slug,
  });
}

export function useImportarAsset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Asset, ApiError, Candidata & { tags?: string[] }>({
    mutationFn: (cand) => post<Asset>(`/brands/${slug}/assets/importar`, cand),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", slug] }),
  });
}

export function useSubirAsset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Asset, ApiError, File>({
    mutationFn: (archivo) => {
      const form = new FormData();
      form.append("archivo", archivo);
      return postForm<Asset>(`/brands/${slug}/assets/subir`, form);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", slug] }),
  });
}

export function useDescartarAsset(slug: string) {
  const qc = useQueryClient();
  return useMutation<Asset, ApiError, number>({
    mutationFn: (id) => patch<Asset>(`/brands/${slug}/assets/${id}`, { descartada: true }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", slug] }),
  });
}

export function useRecorteAsset(slug: string) {
  return useMutation<{ job_id: number }, ApiError, number>({
    mutationFn: (id) => post<{ job_id: number }>(`/brands/${slug}/assets/${id}/recorte`, {}),
  });
}
```
⚠️ Revisar que `get`/`post`/`patch`/`postForm` de `lib/api.ts` aceptan el genérico `<T>`. Si no lo aceptan, quitar los genéricos y tipar con `as`.

- [ ] **Paso 6: panel** `frontend/app/b/[slug]/templates/[id]/_components/panel-assets.tsx`:
```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { resultadoDeJob } from "@/hooks/use-disenos";
import { useJob } from "@/hooks/use-job";
import {
  type TipoAsset,
  useAssets,
  useBuscarAssets,
  useDescartarAsset,
  useImportarAsset,
  useRecorteAsset,
  useSubirAsset,
} from "@/hooks/use-assets";
import { type Asset, type Candidata, capaDesdeAsset, urlVisible } from "@/lib/assets";
import { useEditor } from "@/stores/editor";

function Miniatura({ src, tipo, alt }: { src: string; tipo: TipoAsset; alt: string }) {
  return tipo === "video" && src.endsWith(".mp4") ? (
    <video src={src} muted loop playsInline className="h-full w-full object-cover" />
  ) : (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={src} alt={alt} loading="lazy" className="h-full w-full object-cover" />
  );
}

export function PanelAssets({ slug }: { slug: string }) {
  const escena = useEditor((s) => s.escena);
  const agregarCapa = useEditor((s) => s.agregarCapa);
  const [tipo, setTipo] = useState<TipoAsset>("imagen");
  const [q, setQ] = useState("");
  const [buscado, setBuscado] = useState("");
  const [conIa, setConIa] = useState(false);
  const [recorteJob, setRecorteJob] = useState<{ jid: number; asset: Asset } | null>(null);
  const archivoRef = useRef<HTMLInputElement>(null);

  const busqueda = useBuscarAssets(slug, buscado, tipo, conIa ? ["ia_imagen"] : undefined);
  const biblioteca = useAssets(slug, tipo);
  const importar = useImportarAsset(slug);
  const subir = useSubirAsset(slug);
  const descartar = useDescartarAsset(slug);
  const recortar = useRecorteAsset(slug);
  const job = useJob(slug, recorteJob?.jid ?? null);

  useEffect(() => {
    if (!recorteJob || !job.data) return;
    if (job.data.estado === "ok") {
      const r = resultadoDeJob<{ recorte_archivo: string }>(job.data);
      if (r && escena) {
        agregarCapa(capaDesdeAsset({ ...recorteJob.asset, recorte_archivo: r.recorte_archivo },
                                   escena, { recorte: true }));
        toast.success("Fondo quitado");
      }
      setRecorteJob(null);
    } else if (job.data.estado === "error" || job.data.estado === "cancelado") {
      toast.error("No se pudo quitar el fondo");
      setRecorteJob(null);
    }
  }, [job.data, recorteJob, escena, agregarCapa]);

  function usar(asset: Asset) {
    if (!escena) return;
    agregarCapa(capaDesdeAsset(asset, escena));
  }

  function usarCandidata(c: Candidata) {
    importar.mutate(
      { ...c, tags: buscado ? [buscado] : [] },
      { onSuccess: usar, onError: (e) => toast.error(e.message) },
    );
  }

  const avisos = busqueda.data?.avisos ?? [];
  const hayGiphy = (busqueda.data?.resultados ?? []).some((c) => c.proveedor === "giphy");

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <Tabs value={tipo} onValueChange={(v) => setTipo(v as TipoAsset)}>
        <TabsList className="w-full">
          <TabsTrigger value="imagen" className="flex-1">Fotos</TabsTrigger>
          <TabsTrigger value="video" className="flex-1">Video</TabsTrigger>
        </TabsList>
        <TabsContent value={tipo} className="mt-3 space-y-3">
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              setConIa(false);
              setBuscado(q.trim());
            }}
          >
            <Input value={q} onChange={(e) => setQ(e.target.value)} maxLength={200}
                   placeholder={tipo === "imagen" ? "Buscar fotos…" : "Buscar video…"} />
            <Button type="submit" size="sm">Buscar</Button>
          </form>
          <div className="flex flex-wrap gap-2">
            {tipo === "imagen" && (
              <Button size="sm" variant="outline" disabled={q.trim().length < 2}
                      title="De pago: solo si la marca activó la fuente IA"
                      onClick={() => { setConIa(true); setBuscado(q.trim()); }}>
                Generar con IA
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => archivoRef.current?.click()}
                    disabled={subir.isPending}>
              Subir archivo
            </Button>
            <input ref={archivoRef} type="file" hidden
                   accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/webm"
                   onChange={(e) => {
                     const f = e.target.files?.[0];
                     if (f) subir.mutate(f, { onSuccess: usar,
                                              onError: (err) => toast.error(err.message) });
                     e.target.value = "";
                   }} />
          </div>
          {avisos.length > 0 && (
            <ul className="space-y-1 text-xs text-amber-600">
              {avisos.map((a) => <li key={a}>{a}</li>)}
            </ul>
          )}
        </TabsContent>
      </Tabs>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        {buscado && (
          <section>
            <h4 className="mb-2 text-xs font-medium text-muted-foreground">Resultados</h4>
            {busqueda.isLoading && <Skeleton className="h-32 w-full" />}
            <div className="grid grid-cols-2 gap-2">
              {(busqueda.data?.resultados ?? []).map((c) => (
                <button key={`${c.proveedor}-${c.id_origen}`} type="button"
                        className="group relative aspect-square overflow-hidden rounded border"
                        disabled={importar.isPending} onClick={() => usarCandidata(c)}
                        title={[c.autor, c.licencia].filter(Boolean).join(" · ")}>
                  <Miniatura src={urlVisible(slug, c.preview_url || c.url)} tipo={c.tipo}
                             alt={c.autor ?? c.proveedor} />
                  <span className="absolute bottom-0 left-0 right-0 truncate bg-black/60 px-1
                                   text-[10px] text-white">
                    {c.proveedor}{c.autor ? ` · ${c.autor}` : ""}
                  </span>
                </button>
              ))}
            </div>
            {hayGiphy && (
              <p className="mt-2 text-right text-[10px] text-muted-foreground">Powered by GIPHY</p>
            )}
          </section>
        )}

        <section>
          <h4 className="mb-2 text-xs font-medium text-muted-foreground">Biblioteca de la marca</h4>
          {biblioteca.isLoading && <Skeleton className="h-32 w-full" />}
          <div className="grid grid-cols-2 gap-2">
            {(biblioteca.data ?? []).map((a) => (
              <div key={a.id} className="group relative aspect-square overflow-hidden rounded border">
                <button type="button" className="h-full w-full" onClick={() => usar(a)}>
                  <Miniatura src={urlVisible(slug, a.src)} tipo={a.tipo} alt={a.archivo} />
                </button>
                <div className="absolute right-1 top-1 hidden gap-1 group-hover:flex">
                  {a.tipo === "imagen" && (
                    <Button size="sm" variant="secondary" className="h-6 px-2 text-[10px]"
                            disabled={!!recorteJob || recortar.isPending}
                            onClick={() => recortar.mutate(a.id, {
                              onSuccess: (r) => setRecorteJob({ jid: r.job_id, asset: a }),
                              onError: (e) => toast.error(e.message),
                            })}>
                      Sin fondo
                    </Button>
                  )}
                  <Button size="sm" variant="secondary" className="h-6 px-2 text-[10px]"
                          onClick={() => descartar.mutate(a.id)}>
                    Quitar
                  </Button>
                </div>
              </div>
            ))}
          </div>
          {recorteJob && (
            <p className="mt-2 text-xs text-muted-foreground">Quitando el fondo…</p>
          )}
        </section>
      </div>
    </div>
  );
}
```
⚠️ Hay tres supuestos:
- El selector `useEditor((s) => s.escena)` supone que el store de zustand admite selectores, que es lo normal en zustand 5.
- `escena` puede ser `null` antes de `cargar`, y por eso hay guardas.
- `resultadoDeJob` sigue exportado desde `hooks/use-disenos.ts:57`.

- [ ] **Paso 7: pestaña en `page.tsx`**

En el arreglo `pestanas` que el plan 2 pasa a `PanelLateral`, agregar después de la pestaña de capas:
```tsx
{ id: "assets", etiqueta: "Assets", contenido: <PanelAssets slug={slug} /> },
```
con `import { PanelAssets } from "./_components/panel-assets";`. `slug` es la variable que `page.tsx` ya saca de `params`.

- [ ] **Paso 8: verificar**

Run: `cd frontend && pnpm vitest run lib/assets.test.ts && pnpm lint && pnpm tsc --noEmit`
Expected: PASS y 0 errores.

Prueba manual, con api, worker y frontend locales:
- abrir un diseño en `http://localhost:3000/b/<slug>/templates/<id>`;
- en la pestaña Assets, buscar «playa» y hacer clic en un resultado: la capa aparece centrada y queda seleccionable;
- guardar y recargar: la imagen sigue;
- en la biblioteca, «Sin fondo» crea una segunda capa con el PNG recortado (requiere worker corriendo y el modelo descargado);
- subir un `.txt` renombrado a `.png` da error;
- «Generar con IA» sin la fuente IA activa muestra el aviso y no llama a fal.

⚠️ La prueba manual no está automatizada; se reporta como tal.

- [ ] **Paso 9: suite completa y lint**

Run:
```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m "not lento"
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
```
Expected: todo verde. Cualquier rojo preexistente se anota con su nombre y no se "arregla" fuera de alcance.

- [ ] **Paso 10: commit**
```bash
git add frontend/lib/assets.ts frontend/lib/assets.test.ts frontend/hooks/use-assets.ts "frontend/app/b/[slug]/templates/[id]"
git commit -m "editor: pestaña Assets con búsqueda, biblioteca, subida y quitar fondo

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Desviaciones respecto al spec y al índice

- **`src/assets/` en paralelo a `image_sources.py`.** El slideshow v1 no migra.
- **Nombres de columna.** El spec habla de `path`; aquí son `archivo` y `recorte_archivo`, como fija el contrato del índice.
- **Constructor de proveedor.** Lleva kwargs `cx, account_id, slug, creds, config` y los atributos `llave`, `hosts` y `de_pago`. El índice solo fija `.nombre`, `.tipos` y `.buscar`. El plan 5 debe usar este mismo constructor para `ig_seguidos`.
- **Extras fuera del contrato.** `buscar_con_avisos`, `guardar_bytes` y `descargar` son públicos porque los usan la API y Fontsource.
- **`ia_imagen` más restrictivo que el spec.** Exige pedido explícito además de la fila activa.
- **Pinterest.** Sigue en el backend y se oculta en la UI.
- **Fontsource.** Instala un solo TTF por familia (un peso, normal, latin).
- **Las rutas de Fontsource viven en `assets.py`**, no en `plantillas.py`, para no chocar con los planes 1 y 2.
- **Número de tasks.** Son 17 y no 16: Fontsource quedó como task propio.

## Sin verificar (⚠️)

**APIs externas:**
- **GIPHY:** campos de respuesta y límites de la beta key.
- **fal.ai:** header de auth, host de las imágenes y precio.
- **Openverse:** límites anónimos y tope de `page_size`.
- **Coverr:** forma exacta de `hits`, host del CDN y si exige atribución.
- **Pexels video:** host de descarga (`videos.pexels.com` vs `player.vimeo.com`).
- **Fontsource:** que `variants[...].url.ttf` siga vigente.

**Infraestructura:**
- **rembg:** conflicto de `opencv-python-headless` con `opencv-python`, y tamaño final de la imagen Docker con BiRefNet.
- **Descarga:** el TOCTOU de DNS rebinding en `biblioteca.descargar` queda abierto.

**Dependencias de otros planes:**
- **Plan 2:** nombres de los tipos TS y del store, y que vitest esté instalado.
- **Plan 1:** las extensiones (`.gif`/`.mp4`/`.webm`) que acepta `GET files/assets/{archivo}`.
