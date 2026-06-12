# Dedupe de releases entre bandas por flyer — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un release publicado por varias cuentas (post colab o flyer re-subido) produce UNA tarjeta a nombre de la primera cuenta, con las demás como créditos `(con @handles)` en el caption.

**Architecture:** Dos señales de duplicado cross-banda — shortcode compartido (exacto) y pHash del flyer (visual, dHash 8×8 umbral 8, ya usado en shows). Merge en detección (`detect_releases_ig`) vía columna JSON `events.creditos`; red de seguridad al armar el carrusel (`build_releases_carousel`). `_phash`/`_es_duplicado` se mueven a `src/imghash.py` para evitar import circular.

**Tech Stack:** Python 3 + sqlite + cv2/numpy (ya en deps), pytest. Spec: `docs/superpowers/specs/2026-06-13-release-flyer-dedup-design.md`.

---

### Task 1: `src/imghash.py` (mover pHash a módulo compartido)

**Files:**
- Create: `src/imghash.py`
- Modify: `src/generate_agenda.py:190-202` (defs `_phash`/`_es_duplicado` → import con alias)
- Test: `tests/test_imghash.py`

- [ ] **Step 1: test que falla** — `tests/test_imghash.py`:

```python
"""pHash compartido: igual↔igual, distinto↔distinto, ilegible→None."""
from __future__ import annotations

import numpy as np

from src import imghash


def _img(path, seed: int) -> None:
    import cv2
    rng = np.random.default_rng(seed)
    cv2.imwrite(str(path), rng.integers(0, 255, (64, 64, 3), dtype=np.uint8))


def test_misma_imagen_es_duplicado(tmp_path) -> None:
    _img(tmp_path / "a.jpg", seed=1)
    _img(tmp_path / "b.jpg", seed=1)
    ha, hb = imghash.phash(tmp_path / "a.jpg"), imghash.phash(tmp_path / "b.jpg")
    assert imghash.es_duplicado(ha, [hb])


def test_imagen_distinta_no_es_duplicado(tmp_path) -> None:
    _img(tmp_path / "a.jpg", seed=1)
    _img(tmp_path / "b.jpg", seed=2)
    assert not imghash.es_duplicado(imghash.phash(tmp_path / "a.jpg"),
                                    [imghash.phash(tmp_path / "b.jpg")])


def test_ilegible_regresa_none(tmp_path) -> None:
    (tmp_path / "x.jpg").write_bytes(b"no soy imagen")
    assert imghash.phash(tmp_path / "x.jpg") is None
```

- [ ] **Step 2: correr y ver FAIL** — `.venv/bin/python -m pytest tests/test_imghash.py -q` → `ModuleNotFoundError: src.imghash`
- [ ] **Step 3: implementación** — `src/imghash.py` (cuerpo idéntico al actual de generate_agenda):

```python
"""pHash de imágenes (dHash 8×8) para detectar flyers visualmente iguales.

Compartido por generate_agenda (dedupe de shows al render) y
detect_releases_ig (dedupe cross-banda de releases en detección).
"""
from __future__ import annotations


def phash(path) -> "Any | None":
    """Hash perceptual (dHash 8x8): 64 bits; None si la imagen no se puede leer."""
    import cv2
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    img = cv2.resize(img, (9, 8))
    return (img[:, 1:] > img[:, :-1]).flatten()


def es_duplicado(h, vistos, umbral: int = 8) -> bool:
    """True si h difiere en ≤ umbral bits de alguno de `vistos`."""
    import numpy as np
    return any(int(np.count_nonzero(h != v)) <= umbral for v in vistos)
```

En `generate_agenda.py`, borrar los defs `_phash` y `_es_duplicado` y poner (mantiene monkeypatches y llamadas internas):

```python
from src.imghash import es_duplicado as _es_duplicado, phash as _phash
```

- [ ] **Step 4: verificar verde** — `.venv/bin/python -m pytest tests/test_imghash.py tests/test_agenda.py tests/test_releases_carousel.py -q`
- [ ] **Step 5: commit** — `git add src/imghash.py src/generate_agenda.py tests/test_imghash.py && git commit -m "refactor: pHash a src/imghash (compartido shows/releases)"`

### Task 2: migración `events.creditos`

**Files:**
- Modify: `src/db.py` (TABLES["events"] + lista de migraciones, ver patrón en init_db ~línea 174)
- Test: `tests/test_db_y_sync.py` (agregar test al final)

- [ ] **Step 1: test que falla**:

```python
def test_migracion_creditos_releases(tmp_path) -> None:
    """Columna events.creditos (JSON de band_ids fusionados por dedupe de flyer)."""
    cx = db.connect(tmp_path / "m.db")
    db.init_db(cx)
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(events)")}
    assert "creditos" in cols and "creditos" in db.TABLES["events"]
    cx.close()
```

- [ ] **Step 2: FAIL** → `.venv/bin/python -m pytest tests/test_db_y_sync.py -q -k creditos`
- [ ] **Step 3: implementar** — en `db.py`: agregar `"creditos"` al set `TABLES["events"]` y `("events", "creditos", "TEXT")` a la lista de migraciones idempotentes (mismo patrón que las columnas existentes tipo `titulo`/`cover_url`).
- [ ] **Step 4: verde** + suite de db: `.venv/bin/python -m pytest tests/test_db_y_sync.py -q`
- [ ] **Step 5: commit** — `git commit -am "feat: columna events.creditos (band_ids fusionados)"`

### Task 3: dedupe cross-banda en detección + merge de créditos

**Files:**
- Modify: `src/detect_releases_ig.py` (helpers nuevos + hook en `detectar` antes del insert, ~línea 205)
- Test: `tests/test_detect_releases_ig.py`

- [ ] **Step 1: tests que fallan** (seguir fixtures/mocks existentes del archivo: `cx` y monkeypatch de `_llm_release`):

```python
# ---------- dedupe cross-banda: post colab / mismo flyer ----------

def test_post_colab_fusiona_credito(cx, monkeypatch):
    """Mismo shortcode publicado por 2 bandas = 1 event con crédito."""
    a = db.insert(cx, "bands", nombre="CCÑA", activa=1)
    b = db.insert(cx, "bands", nombre="STADITCHE", activa=1)
    db.insert(cx, "events", band_id=a, tipo="release", titulo="La 4T Del Perreo",
              fecha_evento="2026-06-10", source_post_id="COLAB1",
              cover_url="data/photos/a/COLAB1_0.jpg", status="nuevo")
    monkeypatch.setattr(dr, "_llm_release", lambda c, f: {
        "es_release": True, "es_show": False,
        "titulo": "La 4T Del Perreo", "fecha": "2026-06-10"})
    res = dr.detectar(cx, [{"band_id": b, "shortcode": "COLAB1",
                            "caption": "ya salió", "path": "data/photos/b/COLAB1_2.jpg",
                            "fecha": "2026-06-10"}])
    evs = db.rows(cx, "SELECT * FROM events WHERE tipo='release'")
    assert len(evs) == 1 and res["fusionados"] == 1
    import json
    assert json.loads(evs[0]["creditos"]) == [b]


def test_mismo_flyer_otro_post_fusiona(cx, monkeypatch, tmp_path):
    """Banda B re-sube el flyer de A como post propio (shortcode distinto)."""
    import config as cfg
    import numpy as np, cv2
    monkeypatch.setattr(cfg, "BASE_DIR", tmp_path)
    rng = np.random.default_rng(7)
    img = rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)
    (tmp_path / "data").mkdir()
    cv2.imwrite(str(tmp_path / "data" / "f1.jpg"), img)
    cv2.imwrite(str(tmp_path / "data" / "f2.jpg"), img)  # mismo flyer, otro archivo
    a = db.insert(cx, "bands", nombre="A", activa=1)
    b = db.insert(cx, "bands", nombre="B", activa=1)
    db.insert(cx, "events", band_id=a, tipo="release", titulo="EP Nuevo",
              fecha_evento="2026-06-10", source_post_id="POST_A",
              flyer_path="data/f1.jpg", cover_url="data/f1.jpg", status="nuevo")
    monkeypatch.setattr(dr, "_llm_release", lambda c, f: {
        "es_release": True, "es_show": False, "titulo": "EP Nuevo", "fecha": "2026-06-11"})
    res = dr.detectar(cx, [{"band_id": b, "shortcode": "POST_B",
                            "caption": "x", "path": "data/f2.jpg", "fecha": "2026-06-11"}])
    assert res["fusionados"] == 1
    assert len(db.rows(cx, "SELECT 1 FROM events WHERE tipo='release'")) == 1


def test_flyer_distinto_si_inserta(cx, monkeypatch, tmp_path):
    """Imagen distinta = release distinto: se inserta normal."""
    # mismo arreglo que arriba pero f2 con seed distinta → 2 events, fusionados == 0
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_detect_releases_ig.py -q -k "colab or flyer"`
- [ ] **Step 3: implementación** en `detect_releases_ig.py`:

```python
def _dupe_cross_banda(cx, band_id: int, source_post_id: str, path: str | None,
                      fecha_evento: str | None) -> dict | None:
    """Release equivalente de OTRA banda: post colab (mismo shortcode) o mismo
    flyer re-subido (pHash ≤ umbral) con fecha cercana."""
    from src import db
    candidatos = db.rows(cx, """
        SELECT id, band_id, source_post_id, fecha_evento, flyer_path, cover_url, creditos
          FROM events WHERE tipo='release' AND band_id != ?""", (band_id,))
    for ev in candidatos:
        if ev["source_post_id"] == source_post_id:
            return ev
    if not path:
        return None
    from pathlib import Path
    import config
    from src.imghash import es_duplicado, phash
    p = Path(path)
    h = phash(p if p.is_absolute() else config.BASE_DIR / p)
    if h is None:
        return None
    f_nuevo = _parse_fecha(fecha_evento)
    for ev in candidatos:
        f_viejo = _parse_fecha(ev.get("fecha_evento"))
        if f_nuevo and f_viejo and abs((f_nuevo - f_viejo).days) > _VENTANA_DIAS:
            continue
        local = ev.get("flyer_path") or ev.get("cover_url") or ""
        if not local or local.startswith("http"):
            continue
        q = Path(local)
        q = q if q.is_absolute() else config.BASE_DIR / q
        if not q.exists():
            continue
        hv = phash(q)
        if hv is not None and es_duplicado(h, [hv]):
            return ev
    return None


def _agregar_credito(cx, ev: dict, band_id: int) -> None:
    """Anexa band_id a creditos del event (sin duplicar ni acreditar al dueño)."""
    import json
    from src import db
    actuales = json.loads(ev.get("creditos") or "[]")
    if band_id != ev["band_id"] and band_id not in actuales:
        actuales.append(band_id)
        db.update(cx, "events", ev["id"], creditos=json.dumps(actuales))
```

Hook en `detectar()` (después del lookup de `existente`, antes de `_es_dupe`); inicializar `"fusionados": 0` en `resumen`:

```python
        if existente is None:
            cross = _dupe_cross_banda(cx, post["band_id"], source_post_id,
                                      post.get("path"), fecha_evento)
            if cross is not None:
                _agregar_credito(cx, cross, post["band_id"])
                print(f"↷ {shortcode}: '{titulo}' ya existe de otra banda "
                      f"(event {cross['id']}); crédito fusionado")
                resumen["fusionados"] += 1
                continue
```

- [ ] **Step 4: verde** — `.venv/bin/python -m pytest tests/test_detect_releases_ig.py -q`
- [ ] **Step 5: commit** — `git commit -am "feat: dedupe cross-banda de releases (shortcode colab + pHash de flyer)"`

### Task 4: caption con créditos + red de seguridad al render

**Files:**
- Modify: `src/generate_agenda.py` (`_caption_releases` ~225, `build_releases_carousel` ~259-265; helpers nuevos `_handles_creditos` y `_fusionar_duplicados`)
- Test: `tests/test_releases_carousel.py`

- [ ] **Step 1: tests que fallan** (estilo del archivo existente; sin Playwright — probar los helpers y el caption):

```python
def test_fusionar_duplicados_por_shortcode_y_creditos():
    evs = [
        {"id": 1, "band_id": 10, "source_post_id": "S1", "creditos": None,
         "cover_url": "http://x", "flyer_path": None},
        {"id": 2, "band_id": 20, "source_post_id": "S1", "creditos": None,
         "cover_url": "http://x", "flyer_path": None},
    ]
    unicos = ga._fusionar_duplicados(evs)
    import json
    assert [e["id"] for e in unicos] == [1]
    assert json.loads(unicos[0]["creditos"]) == [20]


def test_caption_releases_con_creditos():
    ev = {"fecha_evento": "2026-06-10", "banda_nombre": "CCÑA", "banda_handle": "angelxcecena",
          "titulo": "La 4T Del Perreo", "creditos_handles": ["cabronxxit0s", "staditche"]}
    cap = ga._caption_releases([ev], "semanal")
    assert "(con @cabronxxit0s @staditche)" in cap
```

- [ ] **Step 2: FAIL** — `.venv/bin/python -m pytest tests/test_releases_carousel.py -q -k "fusionar or creditos"`
- [ ] **Step 3: implementación** — `_fusionar_duplicados(releases)` (shortcode visto → fusiona; si no, pHash de cover/flyer local vs vistos → fusiona; créditos = band_id + créditos de la copia, sin duplicar), `_handles_creditos(cx, eventos)` (resuelve band_ids→ig_handle en una query y anota `ev["creditos_handles"]`), línea del caption agrega `(con @h1 @h2)` si hay handles. En `build_releases_carousel`: `releases = _fusionar_duplicados(releases)` y `_handles_creditos(cx, releases)` dentro del `try` con la conexión abierta.
- [ ] **Step 4: verde** — `.venv/bin/python -m pytest tests/test_releases_carousel.py tests/test_agenda.py tests/test_caption.py -q`
- [ ] **Step 5: commit** — `git commit -am "feat: carrusel de releases fusiona dupes y acredita (con @handles)"`

### Task 5: limpieza de datos + artwork del caso real + verificación end-to-end

**Files:** ninguno nuevo (comandos one-shot sobre la BD de producción)

- [ ] **Step 1:** fusionar dupes actuales: créditos de 406 (Lxs cabronxxxit0s) y 456 (STADITCHE) al event 384 (CCÑA, el más antiguo), `irrelevante=1` a 406/456 — vía python -c reutilizando `_agregar_credito`.
- [ ] **Step 2:** resolver `deezer_id` de CCÑA: `deezer.buscar_artista("CCÑA")` + confirmar "La 4T Del Perreo" en su discografía → `db.update(bands, deezer_id=..., deezer_status='ok')`; correr `deezer.mejorar_covers_ig(cx)` → portada oficial del EP.
- [ ] **Step 3:** suite completa `.venv/bin/python -m pytest -q` (las 3 fallas de test_scraped_mark son preexistentes).
- [ ] **Step 4:** regenerar y mandar el carrusel corregido (`generar_segmento_agenda(periodo='semanal', modo='releases')`) → avisar a Ricardo que descarte 1220/1221.
- [ ] **Step 5: commit final** de docs/plan actualizado si hubo desviaciones.
