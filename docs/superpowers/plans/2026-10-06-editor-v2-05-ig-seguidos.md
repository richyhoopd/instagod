# Editor v2 · Plan 5: fuente «Seguidos de IG» para cualquier marca

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cualquier marca (no solo gdlscene) puede importar el *following* de una cuenta semilla, curar esas cuentas (aprobar o descartar, con avatar y bio) y bajar sus fotos y reels a `brand_assets`, donde el editor los busca como el proveedor «Seguidos de IG».

**Architecture:** Una tabla nueva, `brand_ig_cuentas`, guarda la curaduría por marca. Un módulo nuevo, `src/assets/ig_seguidos.py`, reusa el pool de cookies (`ingest_ig.SesionRotatoria`), `import_followees._listar_con_pool`, `ingest_ig.fetch_profile` y `ingest_ig.fetch_posts`, sin tocar `bands` ni el flujo de gdlscene. Las dos operaciones largas son jobs (`ig.importar_seguidos`, `ig.ingerir`), y la cola gana un «carril IG» global: un solo job de IG corre a la vez en toda la instancia, sin importar la marca, para no subir la concurrencia contra Meta. El proveedor `ig_seguidos` es local: busca en `brand_assets` y nunca toca la red.

**Tech Stack:** Python 3.14, SQLite, FastAPI, pytest, curl_cffi (ya instalado), Pillow 12.2, ffmpeg (`/opt/homebrew/bin/ffmpeg` en la Mac, ya en la imagen Docker porque lo usa `src/video_render.py`), Next 16.3.1, React 19.2 y TanStack Query.

**Spec:** `docs/superpowers/specs/2026-10-06-editor-escena-v2-design.md` (commit e87942f), §4 «Fuente `ig_seguidos`» y §5. Índice y contrato: `docs/superpowers/plans/2026-10-06-editor-v2-00-indice.md`.

---

## Global Constraints

- **Depende del plan 3.** Antes del Task 1, el plan 3 tiene que estar mergeado en `feat/editor-v2`: `brand_assets`, `src/assets/biblioteca.py` (`importar`, `ruta_de`), `src/assets/buscar.py` y `src/assets/proveedores/__init__.py` (`PROVEEDORES`). El Task 1 lo comprueba con una prueba.
- **gdlscene no se toca.** `src/import_followees.py`, `src/ingest_ig.py`, `src/ig_accounts.py` y la tabla `bands` quedan sin cambios. Este plan solo los importa.
- **Nada de red en las pruebas.** Todo IG se simula con `tests/fixtures/assets/ig/*.json`. Las pruebas con ffmpeg llevan `@pytest.mark.lento`.
- **Ritmo de IG.** Ni un request más rápido que hoy: `ingest_ig._sleep()` entre perfil y feed y entre posts con descarga, y un solo job de IG a la vez en toda la instancia (Task 2). La concurrencia no sube (spec §4, riesgo declarado).
- **Nombres de archivo sin datos del usuario.** Lo que se escribe en disco es `ig_<sha256[:20]>.<ext>`, con `<ext>` de una lista cerrada (`jpg`, `png`, `webp`, `mp4`). El handle, el caption y la URL nunca forman parte de una ruta.
- **Aislamiento por marca.** Cada consulta a `brand_ig_cuentas` y `brand_assets` filtra por `account_id`. El router resuelve la marca con `marca_para`.
- **Curaduría.** Reimportar el following nunca cambia el `estado` de una cuenta que ya existe. Una cuenta `descartada` sigue descartada.
- Pytest: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest`. Ruff: `/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/`. Ambos desde la raíz del worktree (`/Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2`).
- Commits locales en `feat/editor-v2`, uno por task. Nada de push. Nada de deploy a la VM.
- No hay que leer `.env` ni `*.local.md`. El pool de cookies (`config.resolve_ig_accounts_path()`) solo lo toca la prueba, que lo redirige a un JSON temporal.

## Review Focus

1. **gdlscene intacto:** `import_followees.importar` sigue escribiendo en `bands` y no escribe en `brand_ig_cuentas`. Prueba: `test_importar_gdlscene_sigue_escribiendo_bands` (Task 3).
2. **Dos marcas nunca ingieren a la vez:** con un job de IG corriendo, `jobs.tomar` no entrega otro de IG de otra marca, pero sí entrega uno que no es de IG. Pruebas: `test_carril_ig_un_solo_job_global` y `test_carril_ig_no_bloquea_otros_tipos` (Task 2).
3. **Curaduría respetada:** reimportar no reactiva una cuenta descartada ni pisa una activa. Prueba: `test_reimportar_respeta_curaduria` (Task 3).
4. **Aislamiento por marca:** el proveedor no devuelve assets de otra marca, `importar` no acepta un id de otra marca, y el router responde 403 con otra marca. Pruebas: `test_proveedor_aisla_marcas` y `test_importar_rechaza_asset_de_otra_marca` (Task 8), y `test_router_otra_marca_403` (Task 9).
5. **Archivos seguros:** el nombre en disco no contiene datos de IG y la ruta cae dentro de `data/brands/<slug>/assets/`. Prueba: `test_nombre_de_archivo_sin_datos_de_ig` (Task 4).

## Desviaciones respecto del spec y del índice

- ⚠️ `brand_ig_cuentas` lleva 4 columnas que el spec no lista: `avatar_url`, `bio`, `ig_user_id` y `privada`. Hacen falta para el paso 3 del spec («lista con avatar y bio») y para no volver a pedir el perfil.
- ⚠️ `sourcing.ig_scrape`, que ya existe, entra al carril IG global. Hoy dos marcas pueden scrapear a la vez con la misma cookie. Un job colgado en `corriendo` bloquea el carril hasta que el rescate de huérfanos existente lo libere.
- ⚠️ `HTTPError` quema la cuenta del pool y rota, igual que `_listar_con_pool` hace hoy (p. ej. `checkpoint_required`).
- El plan 3 se toca en un punto (Task 8): `buscar_con_avisos` suma `_proveedores_extra` cuando `proveedores is None`. La instanciación con `cx` y el `importar` sin redescarga (`local:assets/...`) ya los resuelve el plan 3.
- ⚠️ El índice nombra `archivo` y el spec nombra `path` para la columna de `brand_assets`. Este plan sigue el índice (`archivo`). El Task 4 empieza leyendo el esquema real del plan 3.

## No verificado

- ⚠️ La forma de las respuestas de IG en los fixtures se escribió a mano con base en lo que el código actual lee (`data.user`, `items`, `image_versions2.candidates`, `carousel_media`, `media_type`, `users`). Tres campos no los lee hoy ningún código del repo y no hay respuesta grabada: `profile_pic_url`, `video_versions` e `is_private` en `following`. El Task 3 incluye una prueba de contrato `lento` que **no se corre sin aprobación de Ricardo en el momento**, porque consume una cookie del pool.
- ⚠️ No está verificado que el CDN de IG sirva el avatar como `<img>` desde otro dominio, ni cuánto tarda en expirar la URL firmada (`oe=`). La UI cae a las iniciales si la imagen falla.
- Internos del plan 3 verificados contra su plan (no contra código): `Proveedor(*, cx, account_id, slug, creds, config)`, `url="local:assets/<archivo>"`, `preview_url="/brands/<slug>/files/assets/<archivo>"`, `ruta_de` lee `assets.BRANDS_DIR` (las pruebas lo monkeypatchean).
- ⚠️ El `lower()` de SQLite solo pliega ASCII: buscar «cafe» no encuentra «CAFÉ». Es un límite declarado, no se corrige aquí.

---

## Task 1: tabla `brand_ig_cuentas`

**Files:**
- Modify: `src/schema.sql` (al final)
- Modify: `src/db.py` (`TABLES`, después de la entrada de `brand_assets` que agrega el plan 3)
- Create: `tests/test_ig_seguidos.py`

**Interfaces:**
```sql
brand_ig_cuentas(id, account_id → accounts ON DELETE CASCADE, ig_handle, nombre,
                 estado ∈ {candidata, activa, descartada} DEFAULT candidata,
                 origen DEFAULT 'manual', avatar_url, bio, ig_user_id, privada DEFAULT 0,
                 scraped_at, notas, created_at)  UNIQUE(account_id, ig_handle)
```

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_ig_seguidos.py`:
```python
"""Fuente «Seguidos de IG» (plan 5 del editor v2). Sin red: IG se simula con fixtures."""
from __future__ import annotations

import sqlite3

import pytest

from src import db


@pytest.fixture
def cx(tmp_path):
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    db.insert(c, "accounts", slug="daisies", ig_handle="@d", nombre="D", ciudad="CDMX")
    yield c
    c.close()


def test_precondicion_plan3_brand_assets_existe(cx) -> None:
    cols = {r[1] for r in cx.execute("PRAGMA table_info(brand_assets)")}
    assert {"account_id", "tipo", "archivo", "sha", "proveedor", "ig_handle",
            "source_post_id", "tags_json"} <= cols


def test_tabla_ig_cuentas_defaults(cx) -> None:
    cid = db.insert(cx, "brand_ig_cuentas", account_id=1, ig_handle="cafe.tacuba")
    fila = db.get(cx, "brand_ig_cuentas", cid)
    assert fila["estado"] == "candidata"
    assert fila["origen"] == "manual"
    assert fila["privada"] == 0


def test_tabla_ig_cuentas_unica_por_marca(cx) -> None:
    db.insert(cx, "brand_ig_cuentas", account_id=1, ig_handle="cafe.tacuba")
    db.insert(cx, "brand_ig_cuentas", account_id=2, ig_handle="cafe.tacuba")  # otra marca: OK
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_ig_cuentas", account_id=1, ig_handle="cafe.tacuba")


def test_tabla_ig_cuentas_estado_invalido(cx) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.insert(cx, "brand_ig_cuentas", account_id=1, ig_handle="x", estado="aprobada")
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -v`
Expected: si el plan 3 no está mergeado, `test_precondicion_plan3_brand_assets_existe` falla, y en ese caso hay que **detenerse**. Si está mergeado, esa pasa y las otras 3 fallan con `KeyError` (`brand_ig_cuentas` no está en `TABLES`).

- [ ] **Step 3: Agregar la tabla**

Al final de `src/schema.sql`:
```sql
-- Plan 5 editor v2: cuentas de IG curadas por marca (fuente «Seguidos de IG»).
-- Generaliza la lista de candidatas de gdlscene (bands) sin tocarla.
CREATE TABLE IF NOT EXISTS brand_ig_cuentas (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  ig_handle   TEXT NOT NULL,
  nombre      TEXT,
  estado      TEXT NOT NULL DEFAULT 'candidata'
              CHECK (estado IN ('candidata', 'activa', 'descartada')),
  origen      TEXT NOT NULL DEFAULT 'manual',   -- 'manual' | 'seguido_de:<handle>'
  avatar_url  TEXT,
  bio         TEXT,
  ig_user_id  TEXT,
  privada     INTEGER NOT NULL DEFAULT 0,
  scraped_at  TEXT,
  notas       TEXT,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (account_id, ig_handle)
);
CREATE INDEX IF NOT EXISTS idx_ig_cuentas_account ON brand_ig_cuentas(account_id, estado);
```

En `src/db.py`, dentro de `TABLES`:
```python
    # Plan 5 editor v2: fuente «Seguidos de IG».
    "brand_ig_cuentas": {
        "account_id", "ig_handle", "nombre", "estado", "origen", "avatar_url",
        "bio", "ig_user_id", "privada", "scraped_at", "notas",
    },
```

- [ ] **Step 4: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py tests/test_db.py -v`
Expected: PASS. (Si `tests/test_db.py` no existe, se corre solo el primero.)

- [ ] **Step 5: Commit**

```bash
git add src/schema.sql src/db.py tests/test_ig_seguidos.py
git commit -m "feat(ig-seguidos): tabla brand_ig_cuentas por marca" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: carril IG global en `jobs.tomar`

**Files:**
- Modify: `src/jobs/__init__.py` (constante nueva y el `UPDATE` de `tomar`, ~65-80)
- Modify: `tests/test_jobs.py` (2 pruebas al final)

**Interfaces:**
```python
TIPOS_IG: tuple[str, ...] = ("ig.importar_seguidos", "ig.ingerir", "sourcing.ig_scrape")
# tomar(): además del aislamiento por cuenta, un job de TIPOS_IG no se toma si ya
# hay otro de TIPOS_IG corriendo en cualquier cuenta.
```

- [ ] **Step 1: Escribir las pruebas que fallan**

Al final de `tests/test_jobs.py`:
```python
def test_carril_ig_un_solo_job_global(cx) -> None:
    otra = db.insert(cx, "accounts", slug="daisies", ig_handle="@d", nombre="D", ciudad="CDMX")
    a = jobs.crear(cx, "ig.ingerir", 1, {})
    jobs.crear(cx, "ig.ingerir", otra, {})
    primero = jobs.tomar(cx, "w1")
    assert primero["id"] == a
    # Otra marca, pero el carril IG está ocupado: no se toma.
    assert jobs.tomar(cx, "w2") is None


def test_carril_ig_no_bloquea_otros_tipos(cx) -> None:
    otra = db.insert(cx, "accounts", slug="daisies", ig_handle="@d", nombre="D", ciudad="CDMX")
    jobs.crear(cx, "sourcing.ig_scrape", 1, {})
    jobs.crear(cx, "ig.importar_seguidos", otra, {})
    libre = jobs.crear(cx, "template.preview", otra, {})
    assert jobs.tomar(cx, "w1")["tipo"] == "sourcing.ig_scrape"
    # El de IG de la otra marca espera; el que no es de IG pasa delante.
    assert jobs.tomar(cx, "w2")["id"] == libre
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_jobs.py -k carril_ig -v`
Expected: FAIL. En la primera, `tomar(cx, "w2")` devuelve el `ig.ingerir` de la otra marca. En la segunda, devuelve el `ig.importar_seguidos`.

- [ ] **Step 3: Implementar**

En `src/jobs/__init__.py`, arriba de `def tomar`:
```python
# Tipos que pegan a Instagram con el pool de cookies compartido. Corren de uno
# en uno en TODA la instancia (no por cuenta): dos marcas scrapeando a la vez
# duplican el ritmo contra Meta y queman cookies (spec editor v2 §4).
TIPOS_IG: tuple[str, ...] = ("ig.importar_seguidos", "ig.ingerir", "sourcing.ig_scrape")
_PH_IG = ", ".join("?" * len(TIPOS_IG))
```

En `tomar`, el `UPDATE` queda así (solo cambian el subselect y los parámetros):
```python
    fila = cx.execute(
        f"""
        UPDATE jobs
           SET estado = 'corriendo', worker_id = ?, heartbeat = ?, started_at = ?
         WHERE id = (
             SELECT id FROM jobs
              WHERE estado = 'cola'
                AND account_id NOT IN (
                    SELECT account_id FROM jobs WHERE estado = 'corriendo'
                )
                AND NOT (
                    tipo IN ({_PH_IG})
                    AND EXISTS (SELECT 1 FROM jobs
                                 WHERE estado = 'corriendo' AND tipo IN ({_PH_IG}))
                )
              ORDER BY id LIMIT 1
         )
        RETURNING *
        """,
        (worker_id, ahora, ahora, *TIPOS_IG, *TIPOS_IG),
    ).fetchone()
```

Agregar una línea al docstring de `tomar`: «Además, los tipos de `TIPOS_IG` corren de uno en uno en toda la instancia (carril IG).»

- [ ] **Step 4: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_jobs.py -v`
Expected: PASS, incluidas las pruebas existentes de `tomar`, `max_global` y el worker.

- [ ] **Step 5: Commit**

```bash
git add src/jobs/__init__.py tests/test_jobs.py
git commit -m "feat(jobs): carril IG global, un job de Instagram a la vez en la instancia" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: fixtures de IG e importación del following

**Files:**
- Create: `tests/fixtures/assets/ig/following.json`
- Create: `tests/fixtures/assets/ig/web_profile_info.json`
- Create: `tests/fixtures/assets/ig/feed_user.json`
- Create: `src/assets/ig_seguidos.py`
- Modify: `tests/test_ig_seguidos.py`

**Interfaces:**
```python
# src/assets/ig_seguidos.py
PROVEEDOR = "ig_seguidos"
ESTADOS = ("candidata", "activa", "descartada")
def normalizar_handle(texto: str) -> str                      # ValueError si no es un handle de IG
def listar(cx, account_id: int, *, estado: str | None = None) -> list[dict]
def fijar_estado(cx, account_id: int, handle: str, estado: str) -> dict   # upsert; nueva => origen 'manual'
def importar_seguidos(cx, account_id: int, semilla: str, limite: int | None = None) -> dict
    # -> {"nuevas": int, "ya": int, "total": int}; propaga IngestRateLimited si el pool se agota
```

- [ ] **Step 1: Crear los fixtures**

⚠️ Se escribieron a mano con la forma que el código actual lee; los campos `profile_pic_url`, `is_private` (en `users`) y `video_versions` no se han visto en una respuesta real (ver «No verificado»).

`tests/fixtures/assets/ig/following.json` (lo que devuelve `import_followees._listar_con_pool`: la lista `users` ya aplanada):
```json
[
  {"pk": "111", "username": "cafe.tacuba", "full_name": "Café Tacuba Bar",
   "is_private": false, "profile_pic_url": "https://scontent.cdninstagram.com/v/t51/avatar_111.jpg?oe=AAAA"},
  {"pk": "222", "username": "la_privada", "full_name": "",
   "is_private": true, "profile_pic_url": "https://scontent.cdninstagram.com/v/t51/avatar_222.jpg?oe=BBBB"},
  {"pk": "333", "username": "Mercado.Roma", "full_name": "Mercado Roma",
   "is_private": false, "profile_pic_url": "javascript:alert(1)"},
  {"pk": "444", "username": "../../etc/passwd", "full_name": "malo"}
]
```

`tests/fixtures/assets/ig/web_profile_info.json` (cuerpo crudo de `/users/web_profile_info/`; `fetch_profile` devuelve `data.user`):
```json
{"data": {"user": {
  "id": "111", "username": "cafe.tacuba", "full_name": "Café Tacuba Bar",
  "biography": "Mezcal y vinilos · CDMX", "is_private": false,
  "edge_follow": {"count": 180}
}}, "status": "ok"}
```

`tests/fixtures/assets/ig/feed_user.json` (cuerpo crudo de `/feed/user/{id}/`; `fetch_posts` devuelve `items`): una foto, un carrusel con foto y video, y un reel.
```json
{"items": [
  {"pk": "9001", "code": "CfOtO1", "media_type": 1,
   "caption": {"text": "Noche de vinilos en la terraza"},
   "image_versions2": {"candidates": [
     {"url": "https://scontent.cdninstagram.com/v/t51/foto_9001_1080.jpg?stp=x", "width": 1080, "height": 1350},
     {"url": "https://scontent.cdninstagram.com/v/t51/foto_9001_640.jpg?stp=x", "width": 640, "height": 800}]}},
  {"pk": "9002", "code": "CaRr-2_x", "media_type": 8,
   "caption": {"text": "Playa y mezcal"},
   "carousel_media": [
     {"pk": "9002a", "media_type": 1,
      "image_versions2": {"candidates": [
        {"url": "https://scontent.cdninstagram.com/v/t51/carr_9002a.jpg?stp=x", "width": 1080, "height": 1080}]}},
     {"pk": "9002b", "media_type": 2,
      "image_versions2": {"candidates": [
        {"url": "https://scontent.cdninstagram.com/v/t51/carr_9002b_cover.jpg?stp=x", "width": 1080, "height": 1920}]},
      "video_versions": [
        {"url": "https://scontent.cdninstagram.com/o1/v/t16/carr_9002b.mp4?efg=x", "width": 720, "height": 1280}]}
   ]},
  {"pk": "9003", "code": "ReEl3", "media_type": 2, "caption": null,
   "image_versions2": {"candidates": [
     {"url": "https://scontent.cdninstagram.com/v/t51/reel_9003_cover.jpg?stp=x", "width": 1080, "height": 1920}]},
   "video_versions": [
     {"url": "https://scontent.cdninstagram.com/o1/v/t16/reel_9003.mp4?efg=x", "width": 720, "height": 1280}]}
]}
```

- [ ] **Step 2: Escribir las pruebas que fallan**

Agregar a `tests/test_ig_seguidos.py` (imports arriba, el resto al final):
```python
import json
from pathlib import Path

from src import import_followees
from src.assets import ig_seguidos

FIX = Path(__file__).parent / "fixtures" / "assets" / "ig"


def _following() -> list[dict]:
    return json.loads((FIX / "following.json").read_text())


@pytest.fixture
def following_falso(monkeypatch):
    llamadas: list[tuple] = []

    def falso(cuenta, limite):
        llamadas.append((cuenta, limite))
        return _following()

    monkeypatch.setattr(import_followees, "_listar_con_pool", falso)
    return llamadas


def test_normalizar_handle() -> None:
    assert ig_seguidos.normalizar_handle("  @Cafe.Tacuba ") == "cafe.tacuba"
    for malo in ("", "@", "../x", "a b", "x" * 31, "café"):
        with pytest.raises(ValueError):
            ig_seguidos.normalizar_handle(malo)


def test_importar_seguidos_crea_candidatas(cx, following_falso) -> None:
    r = ig_seguidos.importar_seguidos(cx, 1, "@PensionMas", limite=50)
    assert following_falso == [("pensionmas", 50)]
    assert r == {"nuevas": 3, "ya": 0, "total": 4}          # el handle con "../" se salta
    filas = {f["ig_handle"]: f for f in ig_seguidos.listar(cx, 1)}
    assert set(filas) == {"cafe.tacuba", "la_privada", "mercado.roma"}
    cafe = filas["cafe.tacuba"]
    assert cafe["estado"] == "candidata"
    assert cafe["origen"] == "seguido_de:pensionmas"
    assert cafe["nombre"] == "Café Tacuba Bar"
    assert cafe["avatar_url"].startswith("https://")
    assert filas["la_privada"]["privada"] == 1
    assert filas["la_privada"]["nombre"] == "la_privada"   # full_name vacío => handle
    assert filas["mercado.roma"]["avatar_url"] is None     # solo https://
    assert ig_seguidos.listar(cx, 2) == []                 # otra marca no ve nada


def test_reimportar_respeta_curaduria(cx, following_falso) -> None:
    ig_seguidos.importar_seguidos(cx, 1, "pensionmas")
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, 1, "la_privada", "descartada")
    r = ig_seguidos.importar_seguidos(cx, 1, "otra.semilla")
    assert r == {"nuevas": 0, "ya": 3, "total": 4}
    estados = {f["ig_handle"]: (f["estado"], f["origen"]) for f in ig_seguidos.listar(cx, 1)}
    assert estados["cafe.tacuba"] == ("activa", "seguido_de:pensionmas")
    assert estados["la_privada"] == ("descartada", "seguido_de:pensionmas")


def test_fijar_estado_upsert_manual(cx) -> None:
    fila = ig_seguidos.fijar_estado(cx, 1, "@Nueva.Cuenta", "activa")
    assert (fila["ig_handle"], fila["estado"], fila["origen"]) == ("nueva.cuenta", "activa", "manual")
    fila = ig_seguidos.fijar_estado(cx, 1, "nueva.cuenta", "descartada")
    assert fila["estado"] == "descartada"
    assert len(ig_seguidos.listar(cx, 1)) == 1
    with pytest.raises(ValueError):
        ig_seguidos.fijar_estado(cx, 1, "nueva.cuenta", "aprobada")


def test_listar_filtra_por_estado(cx) -> None:
    ig_seguidos.fijar_estado(cx, 1, "a1", "activa")
    ig_seguidos.fijar_estado(cx, 1, "c1", "candidata")
    assert [f["ig_handle"] for f in ig_seguidos.listar(cx, 1, estado="activa")] == ["a1"]
    with pytest.raises(ValueError):
        ig_seguidos.listar(cx, 1, estado="todas")


def test_importar_gdlscene_sigue_escribiendo_bands(cx, tmp_path, following_falso, monkeypatch) -> None:
    """Review Focus 1: el flujo de gdlscene no cambia y no se cruza con brand_ig_cuentas."""
    real = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: real(tmp_path / "t.db"))
    r = import_followees.importar(cuenta="gdlscene", limite=10)
    assert r["nuevas"] >= 3                                  # importar no valida handles; el "../" puede entrar a bands
    handles = {f["ig_handle"] for f in db.rows(cx, "SELECT ig_handle FROM bands", ())}
    assert "cafe.tacuba" in handles
    assert db.rows(cx, "SELECT id FROM brand_ig_cuentas", ()) == []
```

- [ ] **Step 3: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -v`
Expected: ERROR en la colección, `ModuleNotFoundError: No module named 'src.assets.ig_seguidos'`.

- [ ] **Step 4: Implementar**

`src/assets/ig_seguidos.py`:
```python
"""Fuente «Seguidos de IG»: el following de una cuenta semilla, curado por marca,
como banco de fotos y reels en brand_assets.

Generaliza lo de gdlscene (import_followees + ingest_ig) a cualquier marca SIN
tocar `bands`: las cuentas viven en brand_ig_cuentas y los medios en brand_assets.
Reusa el pool de cookies (SesionRotatoria) y su ritmo; no sube la concurrencia.
"""
from __future__ import annotations

import re
from typing import Any

from src import db, import_followees

PROVEEDOR = "ig_seguidos"
ESTADOS = ("candidata", "activa", "descartada")
_HANDLE_RE = re.compile(r"^[a-z0-9._]{1,30}\Z")


def normalizar_handle(texto: str) -> str:
    """'  @Cafe.Tacuba ' -> 'cafe.tacuba'. ValueError si no es un handle de IG válido."""
    h = (texto or "").strip().lstrip("@").lower()
    if not _HANDLE_RE.match(h) or ".." in h:
        raise ValueError(f"handle de Instagram inválido: {texto!r}")
    return h


def _fila(cx, account_id: int, handle: str) -> dict[str, Any] | None:
    filas = db.rows(cx, "SELECT * FROM brand_ig_cuentas WHERE account_id = ? AND ig_handle = ?",
                    (account_id, handle))
    return dict(filas[0]) if filas else None


def listar(cx, account_id: int, *, estado: str | None = None) -> list[dict[str, Any]]:
    """Cuentas de la marca: primero candidatas (lo que falta curar), luego activas."""
    sql = "SELECT * FROM brand_ig_cuentas WHERE account_id = ?"
    params: list[Any] = [account_id]
    if estado is not None:
        if estado not in ESTADOS:
            raise ValueError(f"estado inválido: {estado!r}")
        sql += " AND estado = ?"
        params.append(estado)
    sql += (" ORDER BY CASE estado WHEN 'candidata' THEN 0 WHEN 'activa' THEN 1 ELSE 2 END,"
            " ig_handle")
    return [dict(r) for r in db.rows(cx, sql, tuple(params))]


def fijar_estado(cx, account_id: int, handle: str, estado: str) -> dict[str, Any]:
    """Aprueba, descarta o agrega a mano. Si la cuenta no existía, nace con origen 'manual'."""
    if estado not in ESTADOS:
        raise ValueError(f"estado inválido: {estado!r}")
    h = normalizar_handle(handle)
    fila = _fila(cx, account_id, h)
    if fila:
        db.update(cx, "brand_ig_cuentas", fila["id"], estado=estado)
    else:
        db.insert(cx, "brand_ig_cuentas", account_id=account_id, ig_handle=h,
                  nombre=h, estado=estado, origen="manual")
    return _fila(cx, account_id, h)


def importar_seguidos(cx, account_id: int, semilla: str,
                      limite: int | None = None) -> dict[str, int]:
    """Importa el following de `semilla` como candidatas de la marca.

    Nunca toca filas existentes: la curaduría (activa/descartada) manda sobre
    cualquier reimportación. Propaga IngestRateLimited si el pool se agota.
    """
    s = normalizar_handle(semilla)
    usuarios = import_followees._listar_con_pool(s, limite)
    nuevas = ya = 0
    for u in usuarios:
        try:
            h = normalizar_handle(str(u.get("username") or ""))
        except ValueError:
            continue
        if _fila(cx, account_id, h):
            ya += 1
            continue
        avatar = u.get("profile_pic_url") or ""
        db.insert(cx, "brand_ig_cuentas", account_id=account_id, ig_handle=h,
                  nombre=(u.get("full_name") or "").strip() or h,
                  origen=f"seguido_de:{s}",
                  avatar_url=avatar if avatar.startswith("https://") else None,
                  privada=1 if u.get("is_private") else 0)
        nuevas += 1
    return {"nuevas": nuevas, "ya": ya, "total": len(usuarios)}
```

- [ ] **Step 5: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py tests/test_followees_web.py -v`
Expected: PASS. Si `test_importar_gdlscene_sigue_escribiendo_bands` falla porque `bands` exige columnas que el fixture no da, se corrige la prueba, no `import_followees`.

- [ ] **Step 6: Prueba de contrato contra IG real (opcional, NO correr sin aprobación)**

Agregar a `tests/test_ig_seguidos.py`:
```python
@pytest.mark.lento
@pytest.mark.ig_real
@pytest.mark.skipif(os.getenv("IG_REAL") != "1",
                    reason="usa una cookie real del pool; correr solo con aprobación de Ricardo")
def test_contrato_following_real() -> None:
    """Confirma las llaves que los fixtures inventaron. IG_REAL=1 pytest -m ig_real."""
    usuarios = import_followees._listar_con_pool("gdlscene", 5)
    assert usuarios, "following vacío"
    assert {"username", "full_name", "is_private", "profile_pic_url"} <= set(usuarios[0])
```
Agregar `import os` a los imports del archivo. (No se usa una condición en texto en `skipif`: el `import config` del Task 4 taparía el `config` de pytest.) Registrar el marcador en `pyproject.toml`, junto a `lento`: `"ig_real: pega a Instagram con una cookie real del pool (requiere aprobación)"`.
Run (para confirmar que se salta): `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -k contrato -v`
Expected: `SKIPPED`.

- [ ] **Step 7: Lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/assets/ig_seguidos.py tests/test_ig_seguidos.py tests/fixtures/assets/ig/ pyproject.toml
git commit -m "feat(ig-seguidos): importar following como candidatas por marca" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: ingesta de fotos a `brand_assets`

**Files:**
- Modify: `src/assets/ig_seguidos.py`
- Modify: `tests/test_ig_seguidos.py`

**Interfaces:**
```python
def ingerir(cx, account_id: int, *, por_cuenta: int = 12,
            progreso: Callable[[int, str], None] | None = None) -> dict
    # -> {"cuentas": int, "assets": int, "errores": list[str], "cortado": bool}
# brand_assets que escribe: proveedor='ig_seguidos', autor='@<handle>',
# licencia='Instagram (terceros)', url_origen='https://www.instagram.com/p/<code>/',
# ig_handle, source_post_id=<pk del post>, archivo='ig_<sha[:20]>.<ext>',
# tags_json={"fuente": "ig_seguidos", "caption": str, ...}
```

- [ ] **Step 0: Leer el esquema real del plan 3**

Run: `grep -n "brand_assets" -A25 src/schema.sql` y `grep -n "def ruta_de" -A8 src/assets/biblioteca.py`
Hay que confirmar tres cosas: que las columnas se llaman como en el contrato (`archivo`, `ancho`, `alto`, `descartada`), que `ruta_de` arma la ruta desde `assets.BRANDS_DIR` **en cada llamada** (la prueba lo monkeypatchea), y si `brand_assets` tiene columnas NOT NULL que este plan no llena. Si algo difiere, se ajusta `_registrar` y la prueba, y se anota en el commit.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_ig_seguidos.py`:
```python
import hashlib
import io

from PIL import Image

import config
from src import assets, ingest_ig


def _png(semilla: str) -> bytes:
    """PNG chico y distinto por URL: sha distinto por medio."""
    h = hashlib.sha256(semilla.encode()).digest()
    buf = io.BytesIO()
    Image.new("RGB", (40, 50), (h[0], h[1], h[2])).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def ig_falso(monkeypatch, tmp_path):
    """IG simulado de punta a punta, sin red: pool temporal, sesión falsa,
    _get_json responde con los fixtures, _download escribe un PNG/MP4 local."""
    pool = tmp_path / "ig_accounts.json"
    pool.write_text(json.dumps([
        {"label": "t1", "sessionid": "s1", "ua": "u", "quemada_hasta": None},
        {"label": "t2", "sessionid": "s2", "ua": "u", "quemada_hasta": None},
    ]))
    monkeypatch.setattr(config, "resolve_ig_accounts_path", lambda: pool)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "data" / "brands")
    monkeypatch.setattr(ingest_ig, "get_session", lambda cuenta=None: object())
    monkeypatch.setattr(ingest_ig, "_sleep", lambda: None)
    estado = {"get_json": [], "descargas": [], "fallar": []}

    def get_json(session, url, params=None):
        estado["get_json"].append(url)
        if estado["fallar"]:
            raise estado["fallar"].pop(0)
        if "web_profile_info" in url:
            datos = json.loads((FIX / "web_profile_info.json").read_text())
            datos["data"]["user"]["username"] = params["username"]
            return datos
        if "/feed/user/" in url:
            return json.loads((FIX / "feed_user.json").read_text())
        raise AssertionError(f"URL inesperada {url}")

    def download(session, url, dest):
        estado["descargas"].append(url)
        dest.write_bytes(b"\x00\x00\x00\x18ftypmp42" + url.encode() if ".mp4" in url else _png(url))
        return True

    monkeypatch.setattr(ingest_ig, "_get_json", get_json)
    monkeypatch.setattr(ingest_ig, "_download", download)
    return estado


def _assets(cx, account_id=1) -> list[dict]:
    return [dict(r) for r in db.rows(
        cx, "SELECT * FROM brand_assets WHERE account_id = ? ORDER BY id", (account_id,))]


def _fotos_propias(cx, account_id=1) -> list[dict]:
    """Fotos del feed (no los cuadros que el Task 5 saca de los videos)."""
    return [a for a in _assets(cx, account_id)
            if a["tipo"] == "imagen" and "cuadro_de_video" not in (a["tags_json"] or "")]


def test_ingerir_baja_fotos_de_cuentas_activas(cx, ig_falso) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, 1, "candidata.sin.aprobar", "candidata")
    ig_seguidos.fijar_estado(cx, 1, "descartada.x", "descartada")
    r = ig_seguidos.ingerir(cx, 1, por_cuenta=12)
    assert r["cuentas"] == 1 and r["errores"] == [] and r["cortado"] is False
    fotos = _fotos_propias(cx)
    assert len(fotos) == 2                                   # foto suelta + foto del carrusel
    f = fotos[0]
    assert f["proveedor"] == "ig_seguidos"
    assert f["autor"] == "@cafe.tacuba"
    assert f["licencia"] == "Instagram (terceros)"
    assert f["url_origen"] == "https://www.instagram.com/p/CfOtO1/"
    assert f["ig_handle"] == "cafe.tacuba"
    assert f["source_post_id"] == "9001"
    assert (f["ancho"], f["alto"]) == (40, 50)
    assert json.loads(f["tags_json"])["caption"] == "Noche de vinilos en la terraza"
    assert all("candidata" not in u and "descartada" not in u for u in ig_falso["get_json"])
    cuenta = ig_seguidos.listar(cx, 1, estado="activa")[0]
    assert cuenta["bio"] == "Mezcal y vinilos · CDMX"
    assert cuenta["ig_user_id"] == "111"
    assert cuenta["scraped_at"]


def test_ingerir_es_idempotente(cx, ig_falso) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_seguidos.ingerir(cx, 1)
    antes = len(_assets(cx))
    descargas = len(ig_falso["descargas"])
    r = ig_seguidos.ingerir(cx, 1)
    assert r["assets"] == 0
    assert len(_assets(cx)) == antes
    assert len(ig_falso["descargas"]) == descargas          # post ya ingerido: ni se baja


def test_nombre_de_archivo_sin_datos_de_ig(cx, ig_falso, tmp_path) -> None:
    """Review Focus 5: nombre = ig_<sha>.<ext>, dentro de data/brands/<slug>/assets/."""
    from src.assets import biblioteca
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_seguidos.ingerir(cx, 1)
    raiz = biblioteca.ruta_de("pensionmas", "x").parent.resolve()
    assert str(raiz).startswith(str(tmp_path.resolve()))
    for a in _assets(cx):
        assert re.fullmatch(r"ig_[0-9a-f]{20}\.(jpg|png|webp|mp4)", a["archivo"])
        assert a["archivo"].startswith(f"ig_{a['sha'][:20]}")
        ruta = biblioteca.ruta_de("pensionmas", a["archivo"]).resolve()
        assert ruta.parent == raiz and ruta.is_file()


def test_perfil_privado_no_baja_nada(cx, ig_falso, monkeypatch) -> None:
    real = ingest_ig._get_json

    def privado(session, url, params=None):
        datos = real(session, url, params)
        if "web_profile_info" in url:
            datos["data"]["user"]["is_private"] = True
        return datos

    monkeypatch.setattr(ingest_ig, "_get_json", privado)
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    r = ig_seguidos.ingerir(cx, 1)
    assert r["assets"] == 0
    cuenta = ig_seguidos.listar(cx, 1)[0]
    assert cuenta["privada"] == 1 and "privad" in cuenta["notas"]
    assert not any("/feed/user/" in u for u in ig_falso["get_json"])


def test_ingerir_sin_cuentas_activas_no_toca_ig(cx, ig_falso) -> None:
    assert ig_seguidos.ingerir(cx, 1) == {"cuentas": 0, "assets": 0, "errores": [], "cortado": False}
    assert ig_falso["get_json"] == []
```
(Agregar `import re` a los imports del archivo.)

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -k "ingerir or nombre_de_archivo or privado" -v`
Expected: FAIL con `AttributeError: module 'src.assets.ig_seguidos' has no attribute 'ingerir'`.

- [ ] **Step 3: Implementar**

En `src/assets/ig_seguidos.py`, los imports quedan así:
```python
import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from src import db, import_followees, ingest_ig
from src.assets import biblioteca
```
Y debajo de `_HANDLE_RE`:
```python
LICENCIA = "Instagram (terceros)"
_CODIGO_RE = re.compile(r"[^A-Za-z0-9_-]")
_EXT_POR_FORMATO = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


@dataclass(frozen=True)
class _Origen:
    handle: str
    codigo: str       # shortcode del post, saneado
    post_id: str
    caption: str


def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
```
Y al final del archivo:
```python
def _medios(item: dict[str, Any]) -> Iterator[tuple[int, str, str]]:
    """(índice, tipo, url) de cada medio del post. En este task solo fotos."""
    if item.get("media_type") == ingest_ig._MEDIA_CARRUSEL:
        medios = item.get("carousel_media") or []
    else:
        medios = [item]
    for i, m in enumerate(medios):
        if m.get("media_type") == ingest_ig._MEDIA_FOTO:
            url = ingest_ig._best_url(m)
            if url:
                yield i, "imagen", url


def _registrar(cx, account_id: int, slug: str, origen: _Origen, tmp: Path, *, tipo: str,
               dims: tuple[int, int] | None = None,
               tags_extra: dict[str, Any] | None = None) -> tuple[dict[str, Any] | None, bool]:
    """Mueve `tmp` a la biblioteca y crea la fila. Devuelve (fila, es_nueva).

    El nombre en disco sale SOLO del sha y de una extensión de lista cerrada:
    ningún dato de IG (handle, caption, URL) toca la ruta.
    """
    sha = hashlib.sha256(tmp.read_bytes()).hexdigest()
    previa = db.rows(cx, "SELECT * FROM brand_assets WHERE account_id = ? AND sha = ?",
                     (account_id, sha))
    if previa:
        return dict(previa[0]), False
    if tipo == "imagen":
        try:
            with Image.open(tmp) as im:
                ext = _EXT_POR_FORMATO.get(im.format or "")
                ancho, alto = im.size
        except OSError:
            return None, False
        if ext is None:
            return None, False
    else:
        ext = "mp4"
        ancho, alto = dims if dims else (None, None)
    archivo = f"ig_{sha[:20]}.{ext}"
    destino = biblioteca.ruta_de(slug, archivo)
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(tmp), destino)
    tags = {"fuente": PROVEEDOR, "caption": origen.caption[:500], **(tags_extra or {})}
    aid = db.insert(cx, "brand_assets", account_id=account_id, tipo=tipo, archivo=archivo,
                    sha=sha, proveedor=PROVEEDOR, autor=f"@{origen.handle}",
                    licencia=LICENCIA,
                    url_origen=f"https://www.instagram.com/p/{origen.codigo}/",
                    ig_handle=origen.handle, source_post_id=origen.post_id,
                    ancho=ancho, alto=alto,
                    tags_json=json.dumps(tags, ensure_ascii=False))
    return dict(db.get(cx, "brand_assets", aid)), True


def _bajar(cx, account_id: int, slug: str, session: Any, origen: _Origen,
           tipo: str, url: str) -> int:
    """Descarga un medio a un tempdir y lo registra. 1 si quedó un asset nuevo."""
    with tempfile.TemporaryDirectory() as tmp:
        crudo = Path(tmp) / "crudo"
        if not ingest_ig._download(session, url, crudo):
            return 0
        _, nueva = _registrar(cx, account_id, slug, origen, crudo, tipo=tipo)
        return int(nueva)


def _ya_ingerido(cx, account_id: int, handle: str, post_id: str) -> bool:
    return bool(db.rows(
        cx, "SELECT 1 FROM brand_assets WHERE account_id = ? AND proveedor = ?"
            " AND ig_handle = ? AND source_post_id = ? LIMIT 1",
        (account_id, PROVEEDOR, handle, post_id)))


def _ingerir_cuenta(cx, account_id: int, slug: str, cuenta: dict[str, Any],
                    session: Any, por_cuenta: int) -> int:
    """Perfil (bio, privada) + últimos `por_cuenta` posts. Devuelve assets nuevos."""
    h = cuenta["ig_handle"]
    perfil = ingest_ig.fetch_profile(session, h)
    privada = bool(perfil.get("is_private"))
    db.update(cx, "brand_ig_cuentas", cuenta["id"],
              nombre=(perfil.get("full_name") or "").strip() or h,
              bio=perfil.get("biography") or None, ig_user_id=str(perfil["id"]),
              privada=int(privada), scraped_at=_ahora(),
              notas="perfil privado: no se puede ingerir" if privada else None)
    if privada:
        return 0
    ingest_ig._sleep()
    nuevos = 0
    for item in ingest_ig.fetch_posts(session, str(perfil["id"]), por_cuenta):
        codigo = _CODIGO_RE.sub("", str(item.get("code") or ""))
        post_id = str(item.get("pk") or item.get("id") or codigo)
        if not codigo or _ya_ingerido(cx, account_id, h, post_id):
            continue
        origen = _Origen(handle=h, codigo=codigo, post_id=post_id,
                         caption=str((item.get("caption") or {}).get("text") or ""))
        bajados = sum(_bajar(cx, account_id, slug, session, origen, tipo, url)
                      for _, tipo, url in _medios(item))
        nuevos += bajados
        if bajados:
            ingest_ig._sleep()
    return nuevos


def ingerir(cx, account_id: int, *, por_cuenta: int = 12,
            progreso: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    """Baja los últimos `por_cuenta` posts de cada cuenta ACTIVA de la marca."""
    resultado: dict[str, Any] = {"cuentas": 0, "assets": 0, "errores": [], "cortado": False}
    cuentas = listar(cx, account_id, estado="activa")
    if not cuentas:
        return resultado
    slug = db.get(cx, "accounts", account_id)["slug"]
    rot = ingest_ig.SesionRotatoria()
    for i, cuenta in enumerate(cuentas):
        if progreso:
            progreso(int(100 * i / len(cuentas)), f"@{cuenta['ig_handle']}")
        try:
            resultado["assets"] += _ingerir_cuenta(cx, account_id, slug, cuenta,
                                                   rot.session, por_cuenta)
            resultado["cuentas"] += 1
        except LookupError as exc:
            resultado["errores"].append(f"@{cuenta['ig_handle']}: {exc}")
    return resultado
```
Nota: un carrusel con medios a medio bajar cuenta como «ya ingerido» en la siguiente corrida, porque `_ya_ingerido` mira el `pk` del post. Es aceptable: se pierde un medio de ese post y no hay riesgo de duplicar.

- [ ] **Step 4: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -v`
Expected: PASS.

- [ ] **Step 5: Lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/assets/ig_seguidos.py tests/test_ig_seguidos.py
git commit -m "feat(ig-seguidos): ingerir fotos de cuentas activas a brand_assets" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: reels y videos de carrusel con primer cuadro

**Files:**
- Modify: `src/assets/ig_seguidos.py` (`_medios`, `_bajar` y `primer_cuadro`, que es nueva)
- Modify: `tests/test_ig_seguidos.py`

**Interfaces:**
```python
def primer_cuadro(video: Path, destino: Path) -> Path    # ffmpeg; CalledProcessError/TimeoutExpired si falla
# Cada video produce 2 filas: el PNG (tipo='imagen', tags.cuadro_de_video=True)
# y el mp4 (tipo='video', tags.poster=<archivo del PNG>, ancho/alto del PNG).
```

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_ig_seguidos.py`:
```python
import shutil
import subprocess


@pytest.fixture
def cuadro_falso(monkeypatch):
    def falso(video, destino):
        destino.write_bytes(_png(video.read_bytes().decode("latin-1")))
        return destino
    monkeypatch.setattr(ig_seguidos, "primer_cuadro", falso)


def test_ingerir_reels_y_videos_de_carrusel(cx, ig_falso, cuadro_falso) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    r = ig_seguidos.ingerir(cx, 1)
    videos = [a for a in _assets(cx) if a["tipo"] == "video"]
    cuadros = [a for a in _assets(cx) if "cuadro_de_video" in (a["tags_json"] or "")]
    assert len(videos) == 2 and len(cuadros) == 2
    assert r["assets"] == 4                                  # 2 fotos + 2 videos (el cuadro no cuenta)
    reel = next(v for v in videos if v["source_post_id"] == "9003")
    poster = json.loads(reel["tags_json"])["poster"]
    assert poster in {c["archivo"] for c in cuadros}
    assert reel["archivo"].endswith(".mp4")
    assert (reel["ancho"], reel["alto"]) == (40, 50)         # dimensiones del cuadro
    assert reel["url_origen"] == "https://www.instagram.com/p/ReEl3/"
    assert len(_fotos_propias(cx)) == 2                      # la prueba del Task 4 sigue valiendo


def test_video_sin_cuadro_se_salta(cx, ig_falso, monkeypatch) -> None:
    def roto(video, destino):
        raise subprocess.CalledProcessError(1, "ffmpeg")
    monkeypatch.setattr(ig_seguidos, "primer_cuadro", roto)
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_seguidos.ingerir(cx, 1)
    assert [a for a in _assets(cx) if a["tipo"] == "video"] == []
    assert len(_fotos_propias(cx)) == 2


@pytest.mark.lento
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="sin ffmpeg")
def test_primer_cuadro_real(tmp_path) -> None:
    video = tmp_path / "v.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "color=c=red:s=64x96:d=1", "-pix_fmt", "yuv420p", str(video)], check=True)
    png = ig_seguidos.primer_cuadro(video, tmp_path / "p.png")
    with Image.open(png) as im:
        assert im.size == (64, 96)
        assert im.getpixel((10, 10))[0] > 200
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -k "reels or sin_cuadro or primer_cuadro" -v -m "lento or not lento"`
Expected: FAIL. `primer_cuadro` no existe, y `monkeypatch.setattr` truena con `AttributeError`.

- [ ] **Step 3: Implementar**

Agregar `import subprocess` a los imports. Agregar la rama de video a `_medios`, que queda así:
```python
def _medios(item: dict[str, Any]) -> Iterator[tuple[int, str, str]]:
    """(índice, tipo, url) de cada medio: fotos, reels y videos dentro de carruseles."""
    if item.get("media_type") == ingest_ig._MEDIA_CARRUSEL:
        medios = item.get("carousel_media") or []
    else:
        medios = [item]
    for i, m in enumerate(medios):
        tipo = m.get("media_type")
        if tipo == ingest_ig._MEDIA_FOTO:
            url = ingest_ig._best_url(m)
            if url:
                yield i, "imagen", url
        elif tipo == ingest_ig._MEDIA_VIDEO:
            versiones = m.get("video_versions") or []
            if versiones and versiones[0].get("url"):
                yield i, "video", versiones[0]["url"]
```
Agregar `primer_cuadro` y reemplazar `_bajar`:
```python
def primer_cuadro(video: Path, destino: Path) -> Path:
    """Primer cuadro del video como PNG (el póster en la biblioteca y en el editor)."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video),
                    "-frames:v", "1", str(destino)],
                   check=True, capture_output=True, timeout=60)
    return destino


def _bajar(cx, account_id: int, slug: str, session: Any, origen: _Origen,
           tipo: str, url: str) -> int:
    """Descarga un medio a un tempdir y lo registra. 1 si quedó un asset nuevo.

    Un video deja dos filas: su primer cuadro (imagen, buscable como foto) y el
    mp4, que apunta al cuadro en tags.poster. Sin cuadro no se guarda el video.
    """
    with tempfile.TemporaryDirectory() as tmp:
        crudo = Path(tmp) / "crudo"
        if not ingest_ig._download(session, url, crudo):
            return 0
        if tipo == "imagen":
            _, nueva = _registrar(cx, account_id, slug, origen, crudo, tipo="imagen")
            return int(nueva)
        try:
            cuadro = primer_cuadro(crudo, Path(tmp) / "cuadro.png")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return 0
        poster, _ = _registrar(cx, account_id, slug, origen, cuadro, tipo="imagen",
                               tags_extra={"cuadro_de_video": True})
        if poster is None:
            return 0
        _, nueva = _registrar(cx, account_id, slug, origen, crudo, tipo="video",
                              dims=(poster["ancho"], poster["alto"]),
                              tags_extra={"poster": poster["archivo"]})
        return int(nueva)
```

- [ ] **Step 4: Correr y ver verde (con la prueba lenta)**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -v -m "lento or not lento"`
Expected: PASS, incluida `test_primer_cuadro_real`, que usa el ffmpeg local y no toca la red.

- [ ] **Step 5: Lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/assets/ig_seguidos.py tests/test_ig_seguidos.py
git commit -m "feat(ig-seguidos): reels y videos de carrusel con primer cuadro como póster" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: rotación del pool y corte por límite de IG

**Files:**
- Modify: `src/assets/ig_seguidos.py` (`ingerir`)
- Modify: `tests/test_ig_seguidos.py`

**Interfaces:**
```python
# ingerir(): IngestRateLimited o HTTPError => quema la cookie, rota y REINTENTA la misma
# cuenta. Sin cookies sanas => cortado=True y para. Si se cortó sin bajar nada,
# lanza IngestRateLimited (el job termina en error, no en un "ok" vacío).
```

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_ig_seguidos.py`:
```python
from curl_cffi.requests.exceptions import HTTPError


def test_rate_limit_rota_y_reintenta_la_misma_cuenta(cx, ig_falso, cuadro_falso, tmp_path) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_falso["fallar"].append(ingest_ig.IngestRateLimited("HTTP 429"))
    r = ig_seguidos.ingerir(cx, 1)
    assert r["cortado"] is False and r["cuentas"] == 1 and r["assets"] == 4
    pool = json.loads((tmp_path / "ig_accounts.json").read_text())
    assert pool[0]["quemada_hasta"] and not pool[1]["quemada_hasta"]


def test_http_error_quema_igual(cx, ig_falso, cuadro_falso) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_falso["fallar"].append(HTTPError("400 checkpoint_required"))
    assert ig_seguidos.ingerir(cx, 1)["cuentas"] == 1


def test_pool_agotado_sin_nada_lanza(cx, ig_falso) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_falso["fallar"].extend([ingest_ig.IngestRateLimited("429")] * 2)
    with pytest.raises(ingest_ig.IngestRateLimited):
        ig_seguidos.ingerir(cx, 1)


def test_pool_agotado_a_media_corrida_devuelve_cortado(cx, ig_falso, cuadro_falso, monkeypatch) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, 1, "zz.segunda", "activa")
    real = ingest_ig._get_json

    def segunda_limitada(session, url, params=None):
        if params and params.get("username") == "zz.segunda":
            raise ingest_ig.IngestRateLimited("429")
        return real(session, url, params)

    monkeypatch.setattr(ingest_ig, "_get_json", segunda_limitada)
    r = ig_seguidos.ingerir(cx, 1)
    assert r["cortado"] is True and r["cuentas"] == 1 and r["assets"] == 4


def test_handle_inexistente_es_error_por_cuenta(cx, ig_falso, cuadro_falso, monkeypatch) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    ig_seguidos.fijar_estado(cx, 1, "aa.no.existe", "activa")
    real = ingest_ig._get_json

    def sin_usuario(session, url, params=None):
        if params and params.get("username") == "aa.no.existe":
            return {"data": {"user": None}}
        return real(session, url, params)

    monkeypatch.setattr(ingest_ig, "_get_json", sin_usuario)
    r = ig_seguidos.ingerir(cx, 1)
    assert r["cuentas"] == 1 and len(r["errores"]) == 1 and "aa.no.existe" in r["errores"][0]
```
⚠️ Se asume que `ig_accounts.marcar_quemada` escribe `quemada_hasta` en el JSON del pool (lo dice el docstring de `SesionRotatoria`). Si la llave se llama distinto, se ajusta la aserción de la primera prueba, no el código.

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -k "rate_limit or http_error or pool_agotado or inexistente" -v`
Expected: FAIL. Las tres primeras truenan con la excepción sin atrapar, y `cortado` sigue en `False`. `test_handle_inexistente_es_error_por_cuenta` ya pasa con el Task 4; se deja como prueba de regresión.

- [ ] **Step 3: Implementar**

Agregar `from curl_cffi.requests.exceptions import HTTPError` a los imports y reemplazar `ingerir`:
```python
def ingerir(cx, account_id: int, *, por_cuenta: int = 12,
            progreso: Callable[[int, str], None] | None = None) -> dict[str, Any]:
    """Baja los últimos `por_cuenta` posts de cada cuenta ACTIVA de la marca.

    Rate limit o HTTPError (p. ej. checkpoint_required): quema la cookie, rota y
    reintenta la MISMA cuenta, igual que import_followees._listar_con_pool. Sin
    cookies sanas se corta; si se cortó sin bajar nada, lanza IngestRateLimited
    para que el job termine en error y no en un 'ok' vacío.
    """
    resultado: dict[str, Any] = {"cuentas": 0, "assets": 0, "errores": [], "cortado": False}
    cuentas = listar(cx, account_id, estado="activa")
    if not cuentas:
        return resultado
    slug = db.get(cx, "accounts", account_id)["slug"]
    rot = ingest_ig.SesionRotatoria()
    for i, cuenta in enumerate(cuentas):
        if progreso:
            progreso(int(100 * i / len(cuentas)), f"@{cuenta['ig_handle']}")
        while True:
            if not rot.disponible():
                resultado["cortado"] = True
                break
            try:
                resultado["assets"] += _ingerir_cuenta(cx, account_id, slug, cuenta,
                                                       rot.session, por_cuenta)
                resultado["cuentas"] += 1
                break
            except (ingest_ig.IngestRateLimited, HTTPError):
                rot.rotar_por_quemada()
            except LookupError as exc:
                resultado["errores"].append(f"@{cuenta['ig_handle']}: {exc}")
                break
        if resultado["cortado"]:
            break
    if resultado["cortado"] and resultado["assets"] == 0:
        raise ingest_ig.IngestRateLimited("todas las cuentas scraper están en reposo")
    return resultado
```

- [ ] **Step 4: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -v`
Expected: PASS.

- [ ] **Step 5: Lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/assets/ig_seguidos.py tests/test_ig_seguidos.py
git commit -m "feat(ig-seguidos): rotar cookie y cortar limpio ante rate limit de IG" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: handlers `ig.importar_seguidos` e `ig.ingerir`

**Files:**
- Modify: `src/jobs/handlers.py` (import, 2 funciones y `HANDLERS`)
- Modify: `tests/test_ig_seguidos.py`

**Interfaces:**
```python
def ig_importar_seguidos(cx, job) -> dict   # payload {"semilla": str, "limite": int|None}
def ig_ingerir(cx, job) -> dict             # payload {"por_cuenta": int}
HANDLERS["ig.importar_seguidos"], HANDLERS["ig.ingerir"]
```

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_ig_seguidos.py`:
```python
from src import jobs
from src.jobs import handlers


def _job(cx, tipo, payload, account_id=1) -> dict:
    jid = jobs.crear(cx, tipo, account_id, payload)
    return dict(db.get(cx, "jobs", jid))


def test_handler_importar_seguidos(cx, following_falso) -> None:
    job = _job(cx, "ig.importar_seguidos", {"semilla": "@pensionmas", "limite": 30})
    r = handlers.HANDLERS["ig.importar_seguidos"](cx, job)
    assert r == {"nuevas": 3, "ya": 0, "total": 4}
    assert following_falso == [("pensionmas", 30)]


def test_handler_ingerir_reporta_progreso(cx, ig_falso, cuadro_falso) -> None:
    ig_seguidos.fijar_estado(cx, 1, "cafe.tacuba", "activa")
    job = _job(cx, "ig.ingerir", {"por_cuenta": 5})
    r = handlers.HANDLERS["ig.ingerir"](cx, job)
    assert r["cuentas"] == 1 and r["assets"] == 4
    assert "@cafe.tacuba" in (db.get(cx, "jobs", job["id"])["log"] or "")


def test_handler_ingerir_por_cuenta_acotado(cx, ig_falso, monkeypatch) -> None:
    vistos = {}
    monkeypatch.setattr(ig_seguidos, "ingerir",
                        lambda cx, aid, *, por_cuenta, progreso: vistos.setdefault("n", por_cuenta) and {})
    handlers.HANDLERS["ig.ingerir"](cx, _job(cx, "ig.ingerir", {"por_cuenta": 999}))
    assert vistos["n"] == 50
```

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py -k handler -v`
Expected: FAIL con `KeyError: 'ig.importar_seguidos'`.

- [ ] **Step 3: Implementar**

En `src/jobs/handlers.py`, debajo de `from src import fuentes as fuentes_mod`:
```python
from src.assets import ig_seguidos
```
Antes de `HANDLERS`:
```python
def ig_importar_seguidos(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {semilla, limite}. Following de la semilla -> candidatas de la marca."""
    payload = json.loads(job["payload_json"] or "{}")
    _marca_de(cx, job["account_id"])  # truena si la cuenta ya no existe
    jobs.progresar(cx, job["id"], 5, f"Leyendo a quién sigue @{payload['semilla']}…")
    return ig_seguidos.importar_seguidos(cx, job["account_id"], payload["semilla"],
                                         payload.get("limite"))


def ig_ingerir(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {por_cuenta}. Últimos posts de las cuentas activas -> brand_assets."""
    payload = json.loads(job["payload_json"] or "{}")
    _marca_de(cx, job["account_id"])
    por_cuenta = max(1, min(int(payload.get("por_cuenta") or 12), 50))
    return ig_seguidos.ingerir(
        cx, job["account_id"], por_cuenta=por_cuenta,
        progreso=lambda pct, msg: jobs.progresar(cx, job["id"], pct, msg))
```
En `HANDLERS`, debajo de `"sourcing.ig_scrape": sourcing_ig_scrape,`:
```python
    "ig.importar_seguidos": ig_importar_seguidos,
    "ig.ingerir": ig_ingerir,
```

- [ ] **Step 4: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos.py tests/test_jobs.py -v`
Expected: PASS. Si `jobs.progresar` no escribe `msg` en `jobs.log`, la aserción de `test_handler_ingerir_reporta_progreso` se ajusta a la columna real (leer `src/jobs/__init__.py:90`).

- [ ] **Step 5: Lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/jobs/handlers.py tests/test_ig_seguidos.py
git commit -m "feat(jobs): handlers ig.importar_seguidos e ig.ingerir" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: proveedor `ig_seguidos` en la búsqueda del editor

**Files:**
- Create: `src/assets/proveedores/ig_seguidos.py`
- Modify: `src/assets/proveedores/__init__.py` (registro)
- Modify: `src/assets/buscar.py` (proveedor implícito)
- Create: `tests/test_ig_seguidos_proveedor.py`

**Interfaces:**
```python
class IgSeguidosProvider(base.Proveedor):   # constructor del plan 3: (*, cx, account_id, slug, creds, config)
    nombre = "ig_seguidos"; etiqueta = "Seguidos de IG"; tipos = ("imagen", "video")
    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]
    # url = "local:assets/<archivo>"; preview_url = "/brands/<slug>/files/assets/<poster o archivo>"
# buscar.py
def _proveedores_extra(cx, account_id: int) -> list[str]   # ["ig_seguidos"] si la marca tiene assets de IG
```

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_ig_seguidos_proveedor.py`:
```python
"""Proveedor local «Seguidos de IG»: busca en brand_assets, nunca en la red."""
from __future__ import annotations

import json

import pytest

import config
from src import assets, db
from src.assets import biblioteca, buscar
from src.assets.proveedores import PROVEEDORES
from src.assets.proveedores.ig_seguidos import IgSeguidosProvider


@pytest.fixture
def cx(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(assets, "BRANDS_DIR", tmp_path / "data" / "brands")
    c = db.connect(tmp_path / "t.db")
    db.init_db(c)  # siembra gdlscene como cuenta 1: pensionmas = 2, daisies = 3
    db.insert(c, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    db.insert(c, "accounts", slug="daisies", ig_handle="@d", nombre="D", ciudad="CDMX")
    yield c
    c.close()


def _asset(cx, account_id, handle, caption, *, tipo="imagen", sha, extra=None) -> int:
    archivo = f"ig_{sha[:20]}.{'mp4' if tipo == 'video' else 'png'}"
    return db.insert(cx, "brand_assets", account_id=account_id, tipo=tipo, archivo=archivo,
                     sha=sha, proveedor="ig_seguidos", autor=f"@{handle}",
                     licencia="Instagram (terceros)", url_origen="https://www.instagram.com/p/X/",
                     ig_handle=handle, source_post_id="1", ancho=40, alto=50,
                     tags_json=json.dumps({"fuente": "ig_seguidos", "caption": caption, **(extra or {})}))


def test_registrado() -> None:
    assert PROVEEDORES["ig_seguidos"] is IgSeguidosProvider


def test_busca_por_handle_y_caption(cx) -> None:
    _asset(cx, 2, "cafe.tacuba", "Noche de vinilos", sha="a" * 64)
    _asset(cx, 2, "mercado.roma", "Playa y mezcal", sha="b" * 64)
    p = IgSeguidosProvider(cx=cx, account_id=2, slug="pensionmas")
    assert [c.ig_handle for c in p.buscar("@cafe")] == ["cafe.tacuba"]
    assert [c.ig_handle for c in p.buscar("PLAYA")] == ["mercado.roma"]
    assert len(p.buscar("")) == 2
    c = p.buscar("vinilos")[0]
    assert c.proveedor == "ig_seguidos" and c.tipo == "imagen"
    assert c.url == f"local:assets/ig_{'a' * 20}.png"
    assert c.preview_url == f"/brands/pensionmas/files/assets/ig_{'a' * 20}.png"
    assert c.autor == "@cafe.tacuba" and c.licencia == "Instagram (terceros)"


def test_comodines_like_no_se_cuelan(cx) -> None:
    _asset(cx, 2, "cafe.tacuba", "100% vinilo", sha="a" * 64)
    _asset(cx, 2, "otra", "nada", sha="b" * 64)
    p = IgSeguidosProvider(cx=cx, account_id=2, slug="pensionmas")
    assert [c.ig_handle for c in p.buscar("%")] == ["cafe.tacuba"]
    assert p.buscar("e_t") == []                            # "_" literal, no comodín ("cafe.tacuba" tiene "e.t")


def test_video_usa_poster_como_preview(cx) -> None:
    _asset(cx, 2, "cafe.tacuba", "reel", tipo="video", sha="c" * 64,
           extra={"poster": f"ig_{'d' * 20}.png"})
    p = IgSeguidosProvider(cx=cx, account_id=2, slug="pensionmas")
    v = p.buscar("", tipo="video")[0]
    assert v.url.endswith(".mp4")
    assert v.preview_url == f"/brands/pensionmas/files/assets/ig_{'d' * 20}.png"


def test_excluye_cuentas_descartadas_y_assets_descartados(cx) -> None:
    _asset(cx, 2, "cafe.tacuba", "uno", sha="a" * 64)
    aid = _asset(cx, 2, "mercado.roma", "dos", sha="b" * 64)
    db.insert(cx, "brand_ig_cuentas", account_id=2, ig_handle="cafe.tacuba", estado="descartada")
    db.update(cx, "brand_assets", aid, descartada=1)
    assert IgSeguidosProvider(cx=cx, account_id=2, slug="pensionmas").buscar("") == []


def test_proveedor_aisla_marcas(cx) -> None:
    """Review Focus 4."""
    _asset(cx, 2, "cafe.tacuba", "uno", sha="a" * 64)
    assert IgSeguidosProvider(cx=cx, account_id=3, slug="daisies").buscar("") == []
    assert buscar.buscar(cx, 3, "daisies", "uno", proveedores=["ig_seguidos"]) == []


def test_buscar_unificado_incluye_ig_si_hay_assets(cx) -> None:
    _asset(cx, 2, "cafe.tacuba", "vinilos", sha="a" * 64)
    res = buscar.buscar(cx, 2, "pensionmas", "vinilos", proveedores=["ig_seguidos"])
    assert [c.proveedor for c in res] == ["ig_seguidos"]
    assert "ig_seguidos" in buscar._proveedores_extra(cx, 2)
    assert buscar._proveedores_extra(cx, 3) == []


def test_importar_devuelve_la_fila_sin_descargar(cx, monkeypatch) -> None:
    aid = _asset(cx, 2, "cafe.tacuba", "vinilos", sha="a" * 64)
    cand = IgSeguidosProvider(cx=cx, account_id=2, slug="pensionmas").buscar("")[0]
    monkeypatch.setattr(biblioteca, "descargar", lambda *a, **k: pytest.fail("no debe bajar"))
    fila = biblioteca.importar(cx, 2, "pensionmas", cand)
    assert fila["id"] == aid


def test_importar_rechaza_asset_de_otra_marca(cx) -> None:
    """Review Focus 4: un id_origen de la marca 1 no se importa en la 2."""
    _asset(cx, 2, "cafe.tacuba", "vinilos", sha="a" * 64)
    cand = IgSeguidosProvider(cx=cx, account_id=2, slug="pensionmas").buscar("")[0]
    with pytest.raises(biblioteca.AssetInvalido):
        biblioteca.importar(cx, 3, "daisies", cand)
```
`importar` del plan 3 manda las URL `local:assets/...` a `_importar_local`, que busca la fila por `account_id + archivo` y lanza `AssetInvalido` si no es de la marca: no hay descarga ni cambio en `biblioteca.py`.

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos_proveedor.py -v`
Expected: ERROR en la colección, `ModuleNotFoundError: No module named 'src.assets.proveedores.ig_seguidos'`.

- [ ] **Step 3: Implementar**

`src/assets/proveedores/ig_seguidos.py`:
```python
"""Proveedor «Seguidos de IG»: assets ya ingeridos por ig.ingerir (local, sin red)."""
from __future__ import annotations

import json
from typing import Any

from src import db
from src.assets import Candidata
from src.assets.proveedores import base

_LIMITE = 100


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class IgSeguidosProvider(base.Proveedor):
    """Sin llave ni hosts: lee brand_assets con el cx/account_id/slug que le pasa
    buscar_con_avisos (constructor del plan 3)."""
    nombre = "ig_seguidos"
    etiqueta = "Seguidos de IG"
    tipos = ("imagen", "video")

    def buscar(self, q: str, *, tipo: str = "imagen", n: int = 20) -> list[Candidata]:
        if tipo not in self.tipos:
            return []
        sql = """
            SELECT a.* FROM brand_assets a
             WHERE a.account_id = ? AND a.proveedor = 'ig_seguidos' AND a.tipo = ?
               AND COALESCE(a.descartada, 0) = 0
               AND a.ig_handle NOT IN (
                   SELECT ig_handle FROM brand_ig_cuentas
                    WHERE account_id = ? AND estado = 'descartada')
        """
        params: list[Any] = [self.account_id, tipo, self.account_id]
        texto = (q or "").strip().lstrip("@").lower()
        if texto:
            patron = f"%{_escapar_like(texto)}%"
            sql += (" AND (lower(a.ig_handle) LIKE ? ESCAPE '\\'"
                    " OR lower(a.tags_json) LIKE ? ESCAPE '\\')")
            params += [patron, patron]
        sql += " ORDER BY a.id DESC LIMIT ?"
        params.append(max(1, min(int(n), _LIMITE)))
        return [self._candidata(dict(f)) for f in db.rows(self.cx, sql, tuple(params))]

    def _candidata(self, f: dict[str, Any]) -> Candidata:
        tags = json.loads(f["tags_json"] or "{}")
        vista = tags.get("poster") or f["archivo"]
        return Candidata(
            proveedor=self.nombre, id_origen=str(f["id"]), tipo=f["tipo"],
            url=f"local:assets/{f['archivo']}",          # lo resuelve biblioteca._importar_local
            preview_url=f"/brands/{self.slug}/files/assets/{vista}",   # endpoint del plan 1
            ancho=f["ancho"], alto=f["alto"], autor=f["autor"], licencia=f["licencia"],
            url_origen=f["url_origen"], ig_handle=f["ig_handle"],
            source_post_id=f["source_post_id"])
```
⚠️ Hay que fijarse en la regla de ESCAPE: dentro del `"..."` de Python, `'\\'` llega a SQLite como `'\'`, que es un carácter de escape válido.

En `src/assets/proveedores/__init__.py`, importar `IgSeguidosProvider` y agregarlo a la tupla de la que sale `PROVEEDORES = {c.nombre: c for c in (...)}`. No hay ciclo: `ig_seguidos.py` importa `Candidata` de `src.assets`, no de `buscar.py`.

En `src/assets/buscar.py`:
```python
def _proveedores_extra(cx, account_id: int) -> list[str]:
    """Proveedores activos sin fila en brand_sources: ig_seguidos se activa solo
    cuando la marca ya tiene assets ingeridos de IG."""
    hay = db.rows(cx, "SELECT 1 FROM brand_assets WHERE account_id = ?"
                      " AND proveedor = 'ig_seguidos' LIMIT 1", (account_id,))
    return ["ig_seguidos"] if hay else []
```
En `buscar_con_avisos`, al final de la rama `if proveedores is None:` (después del fallback a `carpeta`/`pexels`), agregar `nombres += _proveedores_extra(cx, account_id)`. El `dict.fromkeys(nombres)` existente evita duplicados.
⚠️ `Carpeta` también devuelve los assets de IG con la misma `url` (`local:assets/...`). El dedup por `url` deja una sola; según el round-robin puede salir con `proveedor="carpeta"`. El atribución vive en la fila de `brand_assets`, así que `importar` devuelve la misma fila en ambos casos.

- [ ] **Step 4: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_ig_seguidos_proveedor.py tests/test_ig_seguidos.py tests/ -k "asset or buscar or ig_seguidos" -v`
Expected: PASS, incluidas las pruebas del plan 3, que no deben romperse con `_proveedores_extra`.

- [ ] **Step 5: Lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/
git add src/assets/ tests/test_ig_seguidos_proveedor.py
git commit -m "feat(assets): proveedor local ig_seguidos en la búsqueda del editor" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: router `/brands/{slug}/fuentes/ig`

**Files:**
- Create: `api/routers/ig_seguidos.py`
- Modify: `api/app.py` (import y `include_router`)
- Create: `tests/test_api_ig_seguidos.py`

**Interfaces:**
```
GET  /brands/{slug}/fuentes/ig/cuentas?estado=      editor   -> list[CuentaIG]
POST /brands/{slug}/fuentes/ig/cuentas              manager  {ig_handle, estado} -> CuentaIG (upsert)
POST /brands/{slug}/fuentes/ig/importar-seguidos    manager  {semilla, limite=200} -> 202 {job_id}
POST /brands/{slug}/fuentes/ig/ingerir              manager  {por_cuenta=12} -> 202 {job_id}
```

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_api_ig_seguidos.py`:
```python
"""API de la fuente «Seguidos de IG». Sin red: solo encola jobs y cura cuentas."""
from __future__ import annotations

import json

import pytest

from src import db
from src.assets import ig_seguidos


@pytest.fixture
def marcas(api_cliente):
    cli, cx, H = api_cliente
    a = db.insert(cx, "accounts", slug="pensionmas", ig_handle="@p", nombre="P", ciudad="CDMX")
    b = db.insert(cx, "accounts", slug="daisies", ig_handle="@d", nombre="D", ciudad="CDMX")
    return cli, cx, H, a, b


def test_listar_y_curar(marcas) -> None:
    cli, cx, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    r = cli.post("/brands/pensionmas/fuentes/ig/cuentas",
                 json={"ig_handle": "@Cafe.Tacuba", "estado": "activa"})
    assert r.status_code == 200
    assert r.json()["ig_handle"] == "cafe.tacuba" and r.json()["origen"] == "manual"
    r = cli.get("/brands/pensionmas/fuentes/ig/cuentas", params={"estado": "activa"})
    assert [c["ig_handle"] for c in r.json()] == ["cafe.tacuba"]


def test_handle_invalido_422(marcas) -> None:
    cli, _, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    r = cli.post("/brands/pensionmas/fuentes/ig/cuentas",
                 json={"ig_handle": "../etc", "estado": "activa"})
    assert r.status_code == 422 and r.json()["campo"] == "ig_handle"
    r = cli.post("/brands/pensionmas/fuentes/ig/importar-seguidos", json={"semilla": "a b"})
    assert r.status_code == 422 and r.json()["campo"] == "semilla"


def test_estado_invalido_422(marcas) -> None:
    cli, _, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    r = cli.get("/brands/pensionmas/fuentes/ig/cuentas", params={"estado": "todas"})
    assert r.status_code == 422


def test_encola_jobs(marcas) -> None:
    cli, cx, H, a, _ = marcas
    uid = H.usuario("m@x.com", marcas=((a, "manager"),))
    H.login(uid)
    r = cli.post("/brands/pensionmas/fuentes/ig/importar-seguidos",
                 json={"semilla": "@PensionMas", "limite": 100})
    assert r.status_code == 202
    job = db.get(cx, "jobs", r.json()["job_id"])
    assert (job["tipo"], job["account_id"], job["creado_por"]) == ("ig.importar_seguidos", a, uid)
    assert json.loads(job["payload_json"]) == {"semilla": "pensionmas", "limite": 100}
    r = cli.post("/brands/pensionmas/fuentes/ig/ingerir", json={"por_cuenta": 8})
    assert r.status_code == 202
    assert json.loads(db.get(cx, "jobs", r.json()["job_id"])["payload_json"]) == {"por_cuenta": 8}


def test_limites_de_payload(marcas) -> None:
    cli, _, H, a, _ = marcas
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    assert cli.post("/brands/pensionmas/fuentes/ig/ingerir",
                    json={"por_cuenta": 500}).status_code == 422
    assert cli.post("/brands/pensionmas/fuentes/ig/importar-seguidos",
                    json={"semilla": "x", "limite": 100000}).status_code == 422


def test_editor_lee_pero_no_encola(marcas) -> None:
    cli, cx, H, a, _ = marcas
    ig_seguidos.fijar_estado(cx, a, "cafe.tacuba", "candidata")
    H.login(H.usuario("e@x.com", marcas=((a, "editor"),)))
    assert cli.get("/brands/pensionmas/fuentes/ig/cuentas").status_code == 200
    assert cli.post("/brands/pensionmas/fuentes/ig/ingerir", json={}).status_code == 403
    assert cli.post("/brands/pensionmas/fuentes/ig/cuentas",
                    json={"ig_handle": "x", "estado": "activa"}).status_code == 403


def test_router_otra_marca_403(marcas) -> None:
    """Review Focus 4."""
    cli, cx, H, a, b = marcas
    ig_seguidos.fijar_estado(cx, b, "secreta.de.daisies", "activa")
    H.login(H.usuario("m@x.com", marcas=((a, "manager"),)))
    assert cli.get("/brands/daisies/fuentes/ig/cuentas").status_code == 403
    assert cli.post("/brands/daisies/fuentes/ig/ingerir", json={}).status_code == 403
    assert cli.post("/brands/daisies/fuentes/ig/cuentas",
                    json={"ig_handle": "x", "estado": "activa"}).status_code == 403
```
⚠️ Se asume que `marca_para` responde 403 (no 404) cuando el usuario no tiene la marca. Si responde 404 a propósito (para no revelar que existe), se cambian las aserciones a 404 y se anota. Lo que importa es que no responda 2xx.

- [ ] **Step 2: Correr y ver que fallan**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_api_ig_seguidos.py -v`
Expected: FAIL con 404 en todas las rutas.

- [ ] **Step 3: Implementar**

`api/routers/ig_seguidos.py`:
```python
"""Fuente «Seguidos de IG» por marca: curar cuentas y encolar importación/ingesta.

Lo que pega a Instagram va SIEMPRE por la cola (carril IG global, jobs.TIPOS_IG);
este router nunca hace requests a IG.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError
from src import jobs
from src.assets import ig_seguidos

router = APIRouter(prefix="/brands/{slug}/fuentes/ig", tags=["ig_seguidos"])

Estado = Literal["candidata", "activa", "descartada"]


class CuentaIn(BaseModel):
    ig_handle: str
    estado: Estado = "activa"


class ImportarIn(BaseModel):
    semilla: str
    limite: int = Field(200, ge=1, le=2000)


class IngerirIn(BaseModel):
    por_cuenta: int = Field(12, ge=1, le=50)


def _handle(texto: str, campo: str) -> str:
    try:
        return ig_seguidos.normalizar_handle(texto)
    except ValueError as e:
        raise ApiError(422, "validacion", str(e), campo) from e


@router.get("/cuentas")
def listar_cuentas(slug: str, estado: Estado | None = None,
                   user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user, minimo="editor")
    return ig_seguidos.listar(cx, fila["id"], estado=estado)


@router.post("/cuentas")
def fijar_cuenta(slug: str, datos: CuentaIn,
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    return ig_seguidos.fijar_estado(cx, fila["id"], _handle(datos.ig_handle, "ig_handle"),
                                    datos.estado)


@router.post("/importar-seguidos", status_code=202)
def importar_seguidos(slug: str, datos: ImportarIn,
                      user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    payload = {"semilla": _handle(datos.semilla, "semilla"), "limite": datos.limite}
    return {"job_id": jobs.crear(cx, "ig.importar_seguidos", fila["id"], payload,
                                 creado_por=user["id"])}


@router.post("/ingerir", status_code=202)
def ingerir(slug: str, datos: IngerirIn,
            user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    return {"job_id": jobs.crear(cx, "ig.ingerir", fila["id"],
                                 {"por_cuenta": datos.por_cuenta}, creado_por=user["id"])}
```
En `api/app.py` se agrega `ig_seguidos` a la tupla de imports de routers, en orden alfabético (entre `fuentes_api` y `lotes`), y `app.include_router(ig_seguidos.router)` junto a `fuentes_api.router`.

⚠️ El 422 del `Literal` en el query `estado` lo emite FastAPI con su propio cuerpo, que puede no tener `campo`. Por eso la prueba solo mira el status.

- [ ] **Step 4: Correr y ver verde**

Run: `/Users/ricardo/Work/personal/instagod/.venv/bin/pytest tests/test_api_ig_seguidos.py tests/test_ig_seguidos.py -v`
Expected: PASS.

- [ ] **Step 5: Lint y commit**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
git add api/routers/ig_seguidos.py api/app.py tests/test_api_ig_seguidos.py
git commit -m "feat(api): /fuentes/ig para curar cuentas y encolar importación e ingesta" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 10: panel «Instagram» en Ajustes → Fuentes

**Files:**
- Create: `frontend/hooks/use-ig-seguidos.ts`
- Create: `frontend/app/b/[slug]/settings/_components/ig-seguidos-panel.tsx`
- Modify: `frontend/app/b/[slug]/settings/_components/tab-fuentes.tsx`

**Interfaces:**
```ts
export interface CuentaIG { id: number; ig_handle: string; nombre: string | null;
  estado: "candidata" | "activa" | "descartada"; origen: string; avatar_url: string | null;
  bio: string | null; privada: number; scraped_at: string | null; notas: string | null }
useCuentasIG(slug), useFijarCuentaIG(slug), useImportarSeguidos(slug), useIngerirIG(slug)
IgSeguidosPanel({ slug, puedeEditar })
```

No hay pruebas de componentes en `frontend/`. Este task se verifica con `pnpm lint`, `pnpm build` y una pasada manual en el navegador contra la API local (Step 5).

- [ ] **Step 1: Hook**

`frontend/hooks/use-ig-seguidos.ts`:
```ts
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, post } from "@/lib/api";

// api/routers/ig_seguidos.py
export type EstadoIG = "candidata" | "activa" | "descartada";

export interface CuentaIG {
  id: number;
  ig_handle: string;
  nombre: string | null;
  estado: EstadoIG;
  origen: string; // "manual" | "seguido_de:<handle>"
  avatar_url: string | null;
  bio: string | null;
  privada: number;
  scraped_at: string | null;
  notas: string | null;
}

const clave = (slug: string) => ["ig-cuentas", slug];

export function useCuentasIG(slug: string) {
  return useQuery<CuentaIG[], ApiError>({
    queryKey: clave(slug),
    queryFn: () => get<CuentaIG[]>(`/brands/${slug}/fuentes/ig/cuentas`),
    enabled: !!slug,
    retry: false,
  });
}

export function useFijarCuentaIG(slug: string) {
  const qc = useQueryClient();
  return useMutation<CuentaIG, ApiError, { ig_handle: string; estado: EstadoIG }>({
    mutationFn: (datos) => post<CuentaIG>(`/brands/${slug}/fuentes/ig/cuentas`, datos),
    onSuccess: () => qc.invalidateQueries({ queryKey: clave(slug) }),
  });
}

export function useImportarSeguidos(slug: string) {
  return useMutation<{ job_id: number }, ApiError, { semilla: string; limite?: number }>({
    mutationFn: (datos) => post<{ job_id: number }>(`/brands/${slug}/fuentes/ig/importar-seguidos`, datos),
  });
}

export function useIngerirIG(slug: string) {
  return useMutation<{ job_id: number }, ApiError, { por_cuenta?: number }>({
    mutationFn: (datos) => post<{ job_id: number }>(`/brands/${slug}/fuentes/ig/ingerir`, datos),
  });
}

export function invalidarCuentasIG(qc: ReturnType<typeof useQueryClient>, slug: string) {
  return qc.invalidateQueries({ queryKey: clave(slug) });
}
```
⚠️ Hay que confirmar la firma de `post` en `lib/api.ts` (`post<T>(path, body)`). Si recibe el cuerpo de otra forma, se ajusta aquí.

- [ ] **Step 2: Panel**

`frontend/app/b/[slug]/settings/_components/ig-seguidos-panel.tsx`:
```tsx
"use client";

import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useJob } from "@/hooks/use-job";
import {
  type CuentaIG,
  type EstadoIG,
  invalidarCuentasIG,
  useCuentasIG,
  useFijarCuentaIG,
  useImportarSeguidos,
  useIngerirIG,
} from "@/hooks/use-ig-seguidos";

function Avatar({ c }: { c: CuentaIG }) {
  const [roto, setRoto] = useState(false);
  const iniciales = (c.nombre || c.ig_handle).slice(0, 2).toUpperCase();
  if (!c.avatar_url || roto) {
    return (
      <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
        {iniciales}
      </div>
    );
  }
  // URL firmada del CDN de IG: puede expirar o negarse al hotlink; cae a iniciales.
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={c.avatar_url}
      alt=""
      referrerPolicy="no-referrer"
      onError={() => setRoto(true)}
      className="size-10 shrink-0 rounded-full object-cover"
    />
  );
}

function Fila({ c, puedeEditar, onEstado, ocupado }: {
  c: CuentaIG; puedeEditar: boolean; ocupado: boolean;
  onEstado: (handle: string, estado: EstadoIG) => void;
}) {
  return (
    <li className="flex items-start gap-3 py-2">
      <Avatar c={c} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <a href={`https://www.instagram.com/${c.ig_handle}/`} target="_blank" rel="noreferrer"
             className="truncate text-sm font-medium hover:underline">@{c.ig_handle}</a>
          {c.privada ? <Badge variant="outline">privada</Badge> : null}
          <Badge variant={c.estado === "activa" ? "default" : "secondary"}>{c.estado}</Badge>
        </div>
        {c.nombre && c.nombre !== c.ig_handle ? (
          <p className="truncate text-xs text-muted-foreground">{c.nombre}</p>
        ) : null}
        {c.bio ? <p className="line-clamp-2 text-xs text-muted-foreground">{c.bio}</p> : null}
        {c.notas ? <p className="text-xs text-amber-600">{c.notas}</p> : null}
      </div>
      {puedeEditar ? (
        <div className="flex shrink-0 gap-1">
          {c.estado !== "activa" ? (
            <Button size="sm" variant="outline" disabled={ocupado}
                    onClick={() => onEstado(c.ig_handle, "activa")}>Aprobar</Button>
          ) : null}
          {c.estado !== "descartada" ? (
            <Button size="sm" variant="ghost" disabled={ocupado}
                    onClick={() => onEstado(c.ig_handle, "descartada")}>Descartar</Button>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

export function IgSeguidosPanel({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const qc = useQueryClient();
  const cuentas = useCuentasIG(slug);
  const fijar = useFijarCuentaIG(slug);
  const importar = useImportarSeguidos(slug);
  const ingerir = useIngerirIG(slug);
  const [semilla, setSemilla] = useState("");
  const [manual, setManual] = useState("");
  const [verDescartadas, setVerDescartadas] = useState(false);
  const [jobId, setJobId] = useState<number | null>(null);
  const job = useJob(slug, jobId);

  const estadoJob = job.data?.estado;
  useEffect(() => {
    if (!estadoJob || estadoJob === "cola" || estadoJob === "corriendo") return;
    if (estadoJob === "ok") toast.success("Listo");
    else toast.error(job.data?.log?.split("\n").pop() || "El job falló");
    invalidarCuentasIG(qc, slug);
    setJobId(null);
  }, [estadoJob, job.data?.log, qc, slug]);

  const corriendo = jobId !== null;
  const lista = (cuentas.data ?? []).filter((c) => verDescartadas || c.estado !== "descartada");
  const activas = (cuentas.data ?? []).filter((c) => c.estado === "activa").length;

  const onEstado = (ig_handle: string, estado: EstadoIG) =>
    fijar.mutate({ ig_handle, estado }, { onError: (e) => toast.error(e.detalle ?? e.message) });

  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">Instagram (seguidos)</h3>
        <p className="text-xs text-muted-foreground">
          Importa a quién sigue una cuenta, aprueba las que sirven y baja sus fotos y reels a la
          biblioteca. Contenido de terceros: revisa el permiso antes de publicarlo.
        </p>
      </div>

      {puedeEditar ? (
        <div className="flex flex-wrap gap-2">
          <Input value={semilla} onChange={(e) => setSemilla(e.target.value)}
                 placeholder="@cuenta semilla" className="w-48" />
          <Button size="sm" disabled={!semilla.trim() || corriendo || importar.isPending}
                  onClick={() => importar.mutate({ semilla }, {
                    onSuccess: (r) => { setJobId(r.job_id); setSemilla(""); },
                    onError: (e) => toast.error(e.detalle ?? e.message),
                  })}>
            Importar seguidos
          </Button>
          <Button size="sm" variant="secondary" disabled={!activas || corriendo || ingerir.isPending}
                  onClick={() => ingerir.mutate({}, {
                    onSuccess: (r) => setJobId(r.job_id),
                    onError: (e) => toast.error(e.detalle ?? e.message),
                  })}>
            Bajar fotos de {activas} activas
          </Button>
        </div>
      ) : null}

      {corriendo ? (
        <p className="text-xs text-muted-foreground">
          {job.data?.estado === "cola" ? "En cola (otra marca puede estar usando Instagram)…" : null}
          {job.data?.estado === "corriendo" ? `${job.data.progreso ?? 0}% · ${job.data.log?.split("\n").pop() ?? ""}` : null}
        </p>
      ) : null}

      {cuentas.isLoading ? <Skeleton className="h-24 w-full" /> : null}
      {cuentas.error ? <p className="text-xs text-destructive">{cuentas.error.detalle}</p> : null}

      <ul className="divide-y">
        {lista.map((c) => (
          <Fila key={c.id} c={c} puedeEditar={puedeEditar} onEstado={onEstado} ocupado={fijar.isPending} />
        ))}
      </ul>
      {cuentas.data && lista.length === 0 ? (
        <p className="text-xs text-muted-foreground">Sin cuentas. Importa desde una semilla o agrega una.</p>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        {puedeEditar ? (
          <>
            <Input value={manual} onChange={(e) => setManual(e.target.value)}
                   placeholder="@agregar a mano" className="w-48" />
            <Button size="sm" variant="outline" disabled={!manual.trim() || fijar.isPending}
                    onClick={() => fijar.mutate({ ig_handle: manual, estado: "activa" }, {
                      onSuccess: () => setManual(""),
                      onError: (e) => toast.error(e.detalle ?? e.message),
                    })}>
              Agregar
            </Button>
          </>
        ) : null}
        <Button size="sm" variant="ghost" onClick={() => setVerDescartadas((v) => !v)}>
          {verDescartadas ? "Ocultar descartadas" : "Ver descartadas"}
        </Button>
      </div>
    </section>
  );
}
```
⚠️ Antes de compilar hay que confirmar tres cosas: las variantes de `Badge` (`default`/`secondary`/`outline`), las de `Button` (`outline`/`ghost`/`secondary`) y `size="sm"` en `components/ui/`. Si `useJob` ya lanza toasts por su cuenta, se quitan los de aquí para no duplicarlos (comparar con `preset-editor.tsx:154`).

- [ ] **Step 3: Montarlo en la pestaña**

En `frontend/app/b/[slug]/settings/_components/tab-fuentes.tsx`, agregar el import `import { IgSeguidosPanel } from "./ig-seguidos-panel";` e insertar después de `<FotosPanel ... />`:
```tsx
      <Separator />
      <IgSeguidosPanel slug={slug} puedeEditar={puedeEditar} />
```
Hay que revisar también el panel de assets del plan 3 (`grep -rn "fuente_asset\|ig_handle" frontend/app/b/[slug]/templates`). Si la capa guarda la atribución sin `ig_handle`, se agrega `ig_handle: cand.ig_handle ?? null`; el spec §4 pide que la capa guarde `@handle`.

- [ ] **Step 4: Lint y build**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2/frontend && pnpm lint && pnpm build
```
Expected: sin errores.

- [ ] **Step 5: Pasada manual (local, sin IG)**

Hay que levantar la API y el frontend como indica el README del repo, entrar a `http://localhost:3000/b/pensionmas/settings` → Fuentes y comprobar lo siguiente:
- Agregar `@cafe.tacuba` a mano la muestra como `activa`.
- «Descartar» la oculta, y «Ver descartadas» la vuelve a mostrar.
- Un usuario `editor` no ve los botones.

**No** se pulsa «Importar seguidos» ni «Bajar fotos» con el worker corriendo: eso pega a IG con una cookie real del pool y requiere aprobación de Ricardo en el momento.

- [ ] **Step 6: Commit**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
git add frontend/hooks/use-ig-seguidos.ts "frontend/app/b/[slug]/settings/_components/ig-seguidos-panel.tsx" "frontend/app/b/[slug]/settings/_components/tab-fuentes.tsx"
git commit -m "feat(frontend): panel Instagram (seguidos) en Ajustes → Fuentes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 11: verificación final

- [ ] **Step 1: Suite completa**

```bash
cd /Users/ricardo/Work/personal/instagod/.claude/worktrees/editor-v2
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -q -m lento tests/test_ig_seguidos.py
/Users/ricardo/Work/personal/instagod/.venv/bin/ruff check src/ tests/ api/
cd frontend && pnpm lint && pnpm build
```
Expected: todo en verde. Si algo falla, se reporta con la salida y no se marca el plan como terminado.

- [ ] **Step 2: Revisar los 5 puntos del Review Focus**

```bash
/Users/ricardo/Work/personal/instagod/.venv/bin/pytest -v tests/test_ig_seguidos.py tests/test_ig_seguidos_proveedor.py tests/test_api_ig_seguidos.py tests/test_jobs.py \
  -k "gdlscene or carril_ig or curaduria or aisla or otra_marca or nombre_de_archivo"
```
Expected: 8 pruebas PASS.

- [ ] **Step 3: Confirmar que gdlscene no cambió**

```bash
git diff master --stat -- src/import_followees.py src/ingest_ig.py src/ig_accounts.py
```
Expected: salida vacía.

- [ ] **Step 4: Pendientes que este plan NO cierra (anotar en la nota de sesión)**

- La prueba de contrato `ig_real` (Task 3, Step 6) sigue sin correr. Hay que correrla con aprobación para confirmar `profile_pic_url`, `is_private` y `video_versions`.
- La primera ingesta real en la VM requiere aprobación y deploy aparte. Lleva `rembg` del plan 3 y la columna nueva.
- El permiso de uso del contenido de terceros es responsabilidad de la marca. El panel lo advierte, pero no lo bloquea.
