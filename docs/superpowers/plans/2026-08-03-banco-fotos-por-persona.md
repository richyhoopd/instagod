# Banco de fotos por persona — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el banco de fotos garantice cobertura de cada integrante de una banda, y que la selección de foto para meme deje de premiar la nitidez y pase a rotar entre personas distintas.

**Architecture:** Tres módulos nuevos con una responsabilidad cada uno — `dedup_fotos` (colapsa near-duplicados con el pHash que ya existe), `faces` (detecta con YuNet y firma con SFace, ambos incluidos en OpenCV), `banco` (política de cupo, pura y sin IO). Los embeddings se persisten para poder reagrupar sin reprocesar imágenes.

**Tech Stack:** Python 3.14, OpenCV 4.13 (`FaceDetectorYN` + `FaceRecognizerSF`), onnxruntime 1.26 (ya instalado por RapidOCR), SQLite, FastAPI + HTMX para la GUI.

## Global Constraints

- **Sin dependencias nuevas de Python.** OpenCV 4.13.0 y onnxruntime 1.26 ya están instalados. No agregar `insightface`, `dlib`, `face_recognition`, PyTorch ni scikit-learn.
- **Python 3.14:** nada que requiera compilar extensiones de C.
- **No se borra ninguna foto ya registrada en `photos`.** El criterio nuevo solo marca `usable_meme=0`. Solo se borran descargas temporales que nunca llegaron a la DB.
- Umbrales de configuración (valores de arranque, calibrables):
  ```
  FACE_DET_SCORE_MIN        0.6
  FACE_CARA_MIN_FRAC        0.05
  FACE_COS_MISMA_PERSONA    0.363
  FOTOS_POR_PERSONA         5
  FOTOS_GRUPALES            3
  DEDUP_HAMMING_MAX         8
  BD_POSTS_A_MIRAR          50
  ANTI_REPETICION_DIAS      45
  ```
- **Migraciones idempotentes.** Tablas nuevas en `src/schema.sql` con `CREATE TABLE IF NOT EXISTS`; columnas nuevas en `db._MIGRATIONS`. `ADD COLUMN` nunca lleva cláusula `REFERENCES` (SQLite lo prohíbe con `foreign_keys=ON` y default no-NULL).
- **Toda tabla nueva debe registrarse en `db.TABLES`**, o `db.insert`/`db.update` la rechazan.
- Correr la suite con `.venv/bin/python -m pytest`. Dos fallos son **preexistentes** y no cuentan como regresión: `test_planner.py::test_plan_month_salta_slots_pasados` y `test_segmentos_web.py::test_segmentos_lista_catalogo_y_preview`.
- Commits sin firma de Claude ni `Co-Authored-By`. Identidad: `richyhoopd <theilluminatiduck@gmail.com>`.

---

### Task 1: Esquema de personas y firmas faciales

**Files:**
- Modify: `src/schema.sql` (agregar al final)
- Modify: `src/db.py:23-74` (TABLES), `src/db.py:103-166` (_MIGRATIONS), `src/db.py:169` (init_db, índices)
- Test: `tests/test_banco_fotos.py`

**Interfaces:**
- Consumes: nada.
- Produces: tablas `personas` (id, band_id, member_id, etiqueta_auto, created_at) y `face_signatures` (id, photo_id, persona_id, bbox, det_score, embedding, created_at); columna `photos.persona_id`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_banco_fotos.py
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


def test_migracion_crea_personas_y_firmas(cx) -> None:
    tablas = {r["name"] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"personas", "face_signatures"} <= tablas
    assert "persona_id" in {r["name"] for r in cx.execute("PRAGMA table_info(photos)")}
    # Sin registro en TABLES, db.insert las rechaza.
    assert "personas" in db.TABLES and "face_signatures" in db.TABLES
    assert "persona_id" in db.TABLES["photos"]


def test_migracion_es_idempotente(cx) -> None:
    db.init_db(cx)
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    assert db.get(cx, "personas", pid)["band_id"] == bid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_banco_fotos.py -v`
Expected: FAIL — `assert {'personas','face_signatures'} <= tablas` (las tablas no existen).

- [ ] **Step 3: Write minimal implementation**

Agregar al final de `src/schema.sql`:

```sql
-- -----------------------------------------------------------------------------
-- personas — grupo automático de caras dentro de una banda ("persona A de
-- Kabala"). member_id la liga a `members` cuando Ricardo le pone nombre y rol
-- en la GUI; hasta entonces es anónima pero utilizable para dar variedad.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS personas (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    band_id       INTEGER NOT NULL,
    member_id     INTEGER,
    etiqueta_auto TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- -----------------------------------------------------------------------------
-- face_signatures — una fila por cara detectada. `embedding` es el vector de
-- 128 float32 de SFace, L2-normalizado, como BLOB (512 bytes). Guardarlo
-- permite reagrupar con otro umbral sin volver a procesar imágenes.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS face_signatures (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id   INTEGER NOT NULL,
    persona_id INTEGER,
    bbox       TEXT NOT NULL,
    det_score  REAL NOT NULL,
    embedding  BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

En `src/db.py`, dentro de `TABLES`:

```python
    "personas": {"band_id", "member_id", "etiqueta_auto"},
    "face_signatures": {"photo_id", "persona_id", "bbox", "det_score", "embedding"},
```

Y agregar `"persona_id"` al set de `TABLES["photos"]`.

En `_MIGRATIONS`, dentro de `"photos"`:

```python
        # Banco por persona: cara dominante de la foto (NULL = sin cara o sin agrupar).
        "persona_id": "INTEGER",
```

En `init_db`, junto a los otros índices:

```python
                "CREATE INDEX IF NOT EXISTS idx_personas_band ON personas(band_id)",
                "CREATE INDEX IF NOT EXISTS idx_firmas_photo ON face_signatures(photo_id)",
                "CREATE INDEX IF NOT EXISTS idx_firmas_persona ON face_signatures(persona_id)",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_banco_fotos.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/schema.sql src/db.py tests/test_banco_fotos.py
git commit -m "feat(banco): esquema de personas y firmas faciales"
```

---

### Task 2: Agrupamiento de firmas (funciones puras)

**Files:**
- Create: `src/faces.py`
- Test: `tests/test_faces.py`

**Interfaces:**
- Consumes: nada.
- Produces: `faces.similitud(a: np.ndarray, b: np.ndarray) -> float`; `faces.agrupar(firmas: list[np.ndarray], umbral: float) -> list[list[int]]` (devuelve listas de índices, ordenadas por tamaño de grupo descendente).

Nota de diseño: `firma()` (Task 3) devuelve vectores **L2-normalizados**, así que la similitud coseno es el producto punto. Eso mantiene estas dos funciones triviales y testeables sin imágenes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_faces.py
from __future__ import annotations

import numpy as np
import pytest

from src import faces


def _vec(*componentes: float) -> np.ndarray:
    """Vector L2-normalizado de 128 dims a partir de sus primeras componentes."""
    v = np.zeros(128, dtype=np.float32)
    v[:len(componentes)] = componentes
    return v / np.linalg.norm(v)


def test_similitud_identica_es_uno() -> None:
    a = _vec(1, 0, 0)
    assert faces.similitud(a, a) == pytest.approx(1.0, abs=1e-6)


def test_similitud_ortogonal_es_cero() -> None:
    assert faces.similitud(_vec(1, 0), _vec(0, 1)) == pytest.approx(0.0, abs=1e-6)


def test_agrupar_junta_parecidas_y_separa_distintas() -> None:
    # a1 y a2 casi idénticas; b claramente distinta.
    a1, a2, b = _vec(1, 0.02), _vec(1, 0.05), _vec(0, 1)
    grupos = faces.agrupar([a1, a2, b], umbral=0.363)
    assert sorted(len(g) for g in grupos) == [1, 2]
    juntos = next(g for g in grupos if len(g) == 2)
    assert set(juntos) == {0, 1}


def test_agrupar_es_transitivo() -> None:
    """Encadenamiento: a~b, b~c, pero a y c apenas por debajo del umbral."""
    a, b, c = _vec(1, 0), _vec(1, 1), _vec(0, 1)
    grupos = faces.agrupar([a, b, c], umbral=0.7)
    assert len(grupos) == 1 and len(grupos[0]) == 3


def test_agrupar_sin_firmas() -> None:
    assert faces.agrupar([], umbral=0.363) == []


def test_agrupar_ordena_por_tamano() -> None:
    a1, a2, a3, b = _vec(1, 0.01), _vec(1, 0.02), _vec(1, 0.03), _vec(0, 1)
    grupos = faces.agrupar([a1, b, a2, a3], umbral=0.363)
    assert len(grupos[0]) == 3  # el grupo grande va primero
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_faces.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.faces'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/faces.py
"""Detección y firma facial con los modelos que ya trae OpenCV.

YuNet (detector) y SFace (reconocedor) vienen incluidos en OpenCV ≥4.5.4 como
`FaceDetectorYN` y `FaceRecognizerSF`; los pesos son dos ONNX que se cachean en
`data/models/`. Se eligieron sobre InsightFace/dlib porque no agregan ninguna
dependencia de Python ni compilan extensiones de C — la misma razón por la que
el OCR vive en RapidOCR.

`similitud` y `agrupar` son PURAS y no tocan disco ni modelos: toda la política
de agrupamiento se puede probar con vectores sintéticos.
"""
from __future__ import annotations

import numpy as np


def similitud(a: "np.ndarray", b: "np.ndarray") -> float:
    """Coseno entre dos firmas. Asume vectores L2-normalizados (los da `firma`)."""
    return float(np.dot(a, b))


def agrupar(firmas: list["np.ndarray"], umbral: float) -> list[list[int]]:
    """Agrupa índices de firmas por similitud ≥ umbral (enlace simple).

    Enlace simple = transitivo: si a se parece a b y b a c, los tres caen en el
    mismo grupo aunque a y c no se parezcan directamente. Es lo correcto aquí:
    las caras de una misma persona forman una cadena a través de poses
    intermedias (frontal → tres cuartos → perfil).

    Devuelve los grupos ordenados de mayor a menor tamaño.
    """
    n = len(firmas)
    padre = list(range(n))

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if similitud(firmas[i], firmas[j]) >= umbral:
                ri, rj = raiz(i), raiz(j)
                if ri != rj:
                    padre[ri] = rj

    grupos: dict[int, list[int]] = {}
    for i in range(n):
        grupos.setdefault(raiz(i), []).append(i)
    return sorted(grupos.values(), key=len, reverse=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_faces.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/faces.py tests/test_faces.py
git commit -m "feat(faces): agrupamiento de firmas por enlace simple"
```

---

### Task 3: Modelos ONNX, detección y firma

**Files:**
- Modify: `src/faces.py`
- Modify: `config.py:123-130` (junto a los otros `CLASSIFY_*`)
- Test: `tests/test_faces.py`
- Test fixture: `tests/fixtures/caras/dos_personas.jpg`

**Interfaces:**
- Consumes: `faces.similitud`, `faces.agrupar` (Task 2).
- Produces:
  - `faces.Cara` — dataclass con `bbox: tuple[int,int,int,int]`, `det_score: float`, `landmarks: np.ndarray`, `frac_area: float`
  - `faces.detectar(img: np.ndarray) -> list[Cara]`
  - `faces.firma(img: np.ndarray, cara: Cara) -> np.ndarray` (128 float32, L2-normalizado)
  - `faces.asegurar_modelos() -> tuple[Path, Path]` — (yunet, sface), descarga y cachea

- [ ] **Step 1: Write the failing test**

Preparar el fixture primero (una vez, a mano):

```bash
mkdir -p tests/fixtures/caras
# Copiar una foto REAL del banco con exactamente dos personas visibles y
# reducirla para que pese poco. Elegir una donde las dos caras se vean de frente.
.venv/bin/python -c "
import cv2
img = cv2.imread('data/photos/kabala_oficial/DbZG9knGpXW_0.jpg')
h, w = img.shape[:2]
esc = 640 / max(h, w)
cv2.imwrite('tests/fixtures/caras/dos_personas.jpg',
            cv2.resize(img, (int(w*esc), int(h*esc))),
            [cv2.IMWRITE_JPEG_QUALITY, 85])
"
```

Verificar a ojo que la imagen resultante tiene dos caras claras; si no, elegir otra foto del banco. Ajustar el número esperado en el test al número real de caras del fixture elegido.

```python
# tests/test_faces.py — agregar
from pathlib import Path

import cv2

_FIXTURE = Path(__file__).parent / "fixtures" / "caras" / "dos_personas.jpg"


@pytest.mark.skipif(not _FIXTURE.exists(), reason="falta el fixture de caras")
def test_detectar_encuentra_las_caras() -> None:
    img = cv2.imread(str(_FIXTURE))
    caras = faces.detectar(img)
    assert len(caras) == 2
    for c in caras:
        assert c.det_score >= 0.6
        assert 0 < c.frac_area < 1
        x, y, w, h = c.bbox
        assert w > 0 and h > 0


@pytest.mark.skipif(not _FIXTURE.exists(), reason="falta el fixture de caras")
def test_firma_normalizada_y_estable() -> None:
    img = cv2.imread(str(_FIXTURE))
    cara = faces.detectar(img)[0]
    f1 = faces.firma(img, cara)
    assert f1.shape == (128,) and f1.dtype == np.float32
    assert np.linalg.norm(f1) == pytest.approx(1.0, abs=1e-5)
    # Determinista: la misma entrada da la misma firma.
    assert faces.similitud(f1, faces.firma(img, cara)) == pytest.approx(1.0, abs=1e-5)


@pytest.mark.skipif(not _FIXTURE.exists(), reason="falta el fixture de caras")
def test_dos_personas_distintas_no_se_agrupan() -> None:
    img = cv2.imread(str(_FIXTURE))
    caras = faces.detectar(img)
    firmas = [faces.firma(img, c) for c in caras]
    assert len(faces.agrupar(firmas, umbral=0.363)) == 2


def test_detectar_imagen_sin_caras() -> None:
    assert faces.detectar(np.zeros((200, 200, 3), dtype=np.uint8)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_faces.py -v`
Expected: FAIL — `AttributeError: module 'src.faces' has no attribute 'detectar'`.

- [ ] **Step 3: Write minimal implementation**

En `config.py`, junto a los `CLASSIFY_*` (línea ~130):

```python
# ---------- Reconocimiento facial (banco por persona) ----------
FACE_DET_SCORE_MIN = float(_get("FACE_DET_SCORE_MIN", "0.6") or "0.6")
FACE_CARA_MIN_FRAC = float(_get("FACE_CARA_MIN_FRAC", "0.05") or "0.05")
# Similitud coseno de SFace para "misma persona" (valor del sample de OpenCV).
FACE_COS_MISMA_PERSONA = float(_get("FACE_COS_MISMA_PERSONA", "0.363") or "0.363")
MODELS_DIR = _get("MODELS_DIR", "./data/models")
```

Y junto a `resolve_photos_dir` (línea ~232):

```python
def resolve_models_dir() -> Path:
    p = _resolve(MODELS_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p
```

En `src/faces.py`:

```python
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

import config

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
_YUNET = ("face_detection_yunet_2023mar.onnx",
          f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx")
_SFACE = ("face_recognition_sface_2021dec.onnx",
          f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx")
_TIMEOUT = 120

_detector = None
_reconocedor = None


@dataclass(frozen=True)
class Cara:
    bbox: tuple[int, int, int, int]      # x, y, w, h
    det_score: float
    landmarks: "np.ndarray"              # 5 puntos (10 valores) que pide SFace
    frac_area: float                     # área de la cara / área de la imagen


def _bajar(nombre: str, url: str) -> Path:
    """Descarga el modelo a data/models/ con escritura atómica. Falla ruidosa."""
    destino = config.resolve_models_dir() / nombre
    if destino.exists() and destino.stat().st_size > 0:
        return destino
    print(f"⬇️  bajando modelo {nombre}…", file=sys.stderr)
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    tmp = destino.with_suffix(destino.suffix + ".part")
    tmp.write_bytes(resp.content)
    tmp.replace(destino)
    return destino


def asegurar_modelos() -> tuple[Path, Path]:
    """Rutas locales de (YuNet, SFace), bajándolos la primera vez."""
    return _bajar(*_YUNET), _bajar(*_SFACE)


def _motores():
    """Detector y reconocedor, creados una vez por proceso."""
    global _detector, _reconocedor
    if _detector is None or _reconocedor is None:
        import cv2
        yunet, sface = asegurar_modelos()
        _detector = cv2.FaceDetectorYN_create(
            str(yunet), "", (320, 320), config.FACE_DET_SCORE_MIN)
        _reconocedor = cv2.FaceRecognizerSF_create(str(sface), "")
    return _detector, _reconocedor


def detectar(img: "np.ndarray") -> list[Cara]:
    """Caras de la imagen que superan score y tamaño mínimos."""
    det, _ = _motores()
    alto, ancho = img.shape[:2]
    det.setInputSize((ancho, alto))
    _, crudas = det.detect(img)
    if crudas is None:
        return []
    area_img = float(alto * ancho)
    salida: list[Cara] = []
    for fila in crudas:
        x, y, w, h = (int(v) for v in fila[:4])
        score = float(fila[-1])
        frac = (w * h) / area_img
        if score < config.FACE_DET_SCORE_MIN or frac < config.FACE_CARA_MIN_FRAC:
            continue
        salida.append(Cara(bbox=(x, y, w, h), det_score=score,
                           landmarks=fila[:-1].astype(np.float32), frac_area=frac))
    return salida


def firma(img: "np.ndarray", cara: Cara) -> "np.ndarray":
    """Vector de 128 float32 L2-normalizado que identifica a la persona."""
    _, rec = _motores()
    alineada = rec.alignCrop(img, cara.landmarks.reshape(1, -1))
    vec = rec.feature(alineada).flatten().astype(np.float32)
    norma = float(np.linalg.norm(vec))
    return vec / norma if norma else vec
```

Nota: `detect()` de YuNet devuelve filas de 15 valores — bbox (4), 5 landmarks (10) y score (1). `alignCrop` espera esa fila completa menos el score, que es justo lo que se guarda en `landmarks`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_faces.py -v`
Expected: PASS (10 tests). La primera corrida baja 37 MB de modelos; las siguientes usan el caché.

Si `test_detectar_encuentra_las_caras` falla por número de caras, ajustar el fixture o el número esperado — no relajar `FACE_DET_SCORE_MIN`.

- [ ] **Step 5: Commit**

```bash
git add src/faces.py tests/test_faces.py tests/fixtures/caras config.py
git commit -m "feat(faces): detector YuNet y firma SFace con caché de modelos"
```

---

### Task 4: Deduplicación de near-duplicados

**Files:**
- Create: `src/dedup_fotos.py`
- Test: `tests/test_dedup_fotos.py`

**Interfaces:**
- Consumes: `imghash.phash`, `imghash.es_duplicado` (ya existen en `src/imghash.py`).
- Produces: `dedup_fotos.agrupar_duplicadas(fotos: list[dict], umbral: int) -> list[list[dict]]` — cada grupo ordenado con el representante (mayor `nitidez`) primero. Cada dict necesita al menos `id`, `hash` (np.ndarray de `phash`) y `nitidez`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedup_fotos.py
from __future__ import annotations

import numpy as np

from src import dedup_fotos


def _hash(bits: str) -> np.ndarray:
    """Hash de 64 bits desde una cadena de 0/1 (se rellena con ceros)."""
    v = np.zeros(64, dtype=bool)
    for i, c in enumerate(bits):
        v[i] = c == "1"
    return v


def test_colapsa_casi_identicas_y_elige_la_mas_nitida() -> None:
    fotos = [
        {"id": 1, "hash": _hash("1010"), "nitidez": 50.0},
        {"id": 2, "hash": _hash("1011"), "nitidez": 90.0},  # 1 bit de diferencia
        {"id": 3, "hash": _hash("0101" + "1" * 40), "nitidez": 70.0},
    ]
    grupos = dedup_fotos.agrupar_duplicadas(fotos, umbral=8)
    assert len(grupos) == 2
    grande = next(g for g in grupos if len(g) == 2)
    assert grande[0]["id"] == 2  # la más nítida encabeza el grupo
    assert {f["id"] for f in grande} == {1, 2}


def test_sin_duplicados_cada_una_su_grupo() -> None:
    fotos = [
        {"id": 1, "hash": _hash("1" * 64), "nitidez": 10.0},
        {"id": 2, "hash": _hash("0" * 64), "nitidez": 20.0},
    ]
    assert len(dedup_fotos.agrupar_duplicadas(fotos, umbral=8)) == 2


def test_lista_vacia() -> None:
    assert dedup_fotos.agrupar_duplicadas([], umbral=8) == []


def test_foto_sin_hash_se_conserva_sola() -> None:
    """Imagen ilegible (phash=None): nunca se agrupa, nunca se pierde."""
    fotos = [
        {"id": 1, "hash": None, "nitidez": 10.0},
        {"id": 2, "hash": _hash("1010"), "nitidez": 20.0},
    ]
    grupos = dedup_fotos.agrupar_duplicadas(fotos, umbral=8)
    assert len(grupos) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_dedup_fotos.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.dedup_fotos'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/dedup_fotos.py
"""Colapsa fotos near-duplicadas dentro de una banda.

El problema de variedad del banco no es que falten fotos: es que hay diez casi
idénticas de la misma sesión. Reusa el dHash de `src/imghash.py`, ya probado en
producción para deduplicar flyers de agenda.

`agrupar_duplicadas` es PURA: recibe hashes ya calculados, no toca disco.
"""
from __future__ import annotations

from typing import Any

import numpy as np


def agrupar_duplicadas(fotos: list[dict[str, Any]], umbral: int) -> list[list[dict[str, Any]]]:
    """Agrupa por distancia de Hamming ≤ umbral; representante (más nítido) primero.

    Una foto con `hash` None (imagen ilegible) siempre queda sola: preferimos
    conservar de más a perder una buena por un hash que no se pudo calcular.
    """
    grupos: list[list[dict[str, Any]]] = []
    for foto in fotos:
        h = foto.get("hash")
        destino = None
        if h is not None:
            for grupo in grupos:
                cabeza = grupo[0].get("hash")
                if cabeza is not None and int(np.count_nonzero(h != cabeza)) <= umbral:
                    destino = grupo
                    break
        if destino is None:
            grupos.append([foto])
        else:
            destino.append(foto)
    return [sorted(g, key=lambda f: f.get("nitidez") or 0.0, reverse=True)
            for g in grupos]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_dedup_fotos.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/dedup_fotos.py tests/test_dedup_fotos.py
git commit -m "feat(banco): dedup de near-duplicados por pHash"
```

---

### Task 5: Política de cupo por persona

**Files:**
- Create: `src/banco.py`
- Modify: `config.py` (agregar `FOTOS_POR_PERSONA`, `FOTOS_GRUPALES`, `DEDUP_HAMMING_MAX`, `ANTI_REPETICION_DIAS`)
- Test: `tests/test_banco.py`

**Interfaces:**
- Consumes: nada (pura).
- Produces: `banco.puntuar(foto: dict) -> float`; `banco.aplicar_cupo(fotos: list[dict], por_persona: int, grupales: int, minimo_sin_caras: int) -> set[int]` — devuelve los `id` que entran al banco. Cada foto: `id`, `nitidez`, `caras` (lista de dicts con `persona_idx`, `det_score`, `frac_area`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_banco.py
from __future__ import annotations

from src import banco


def _foto(fid: int, nitidez: float, personas: list[int], **kw):
    """Foto con una cara por persona listada."""
    return {"id": fid, "nitidez": nitidez,
            "caras": [{"persona_idx": p, "det_score": kw.get("score", 0.9),
                       "frac_area": kw.get("frac", 0.2)} for p in personas]}


def test_cupo_reparte_por_persona_no_por_banda() -> None:
    """El caso que motiva el diseño: 10 del vocalista no deben tapar al baterista."""
    fotos = [_foto(i, nitidez=100 - i, personas=[0]) for i in range(10)]
    fotos += [_foto(100 + i, nitidez=10, personas=[1]) for i in range(3)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4)
    de_p0 = {f["id"] for f in fotos if f["caras"][0]["persona_idx"] == 0} & dentro
    de_p1 = {f["id"] for f in fotos if f["caras"][0]["persona_idx"] == 1} & dentro
    assert len(de_p0) == 5          # topada, aunque tenga 10 candidatas
    assert len(de_p1) == 3          # todas, aunque sean menos nítidas


def test_cupo_prefiere_cara_grande_y_confiable() -> None:
    """Nitidez alta con cara diminuta al fondo pierde contra un retrato."""
    lejos = _foto(1, nitidez=200, personas=[0], frac=0.01, score=0.65)
    retrato = _foto(2, nitidez=80, personas=[0], frac=0.35, score=0.99)
    dentro = banco.aplicar_cupo([lejos, retrato], por_persona=1, grupales=0,
                                minimo_sin_caras=4)
    assert dentro == {2}


def test_grupales_tienen_su_propio_cupo() -> None:
    grupales = [_foto(i, nitidez=50, personas=[0, 1, 2]) for i in range(6)]
    dentro = banco.aplicar_cupo(grupales, por_persona=5, grupales=3, minimo_sin_caras=4)
    assert len(dentro) == 3


def test_degradacion_sin_caras() -> None:
    """Foro/paisaje: sin caras, conserva las más nítidas hasta el mínimo."""
    fotos = [{"id": i, "nitidez": float(i), "caras": []} for i in range(10)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4)
    assert dentro == {9, 8, 7, 6}


def test_una_sola_persona_no_gasta_cupo_grupal() -> None:
    fotos = [_foto(i, nitidez=50, personas=[0]) for i in range(8)]
    dentro = banco.aplicar_cupo(fotos, por_persona=5, grupales=3, minimo_sin_caras=4)
    assert len(dentro) == 5


def test_sin_fotos() -> None:
    assert banco.aplicar_cupo([], por_persona=5, grupales=3, minimo_sin_caras=4) == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_banco.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.banco'`.

- [ ] **Step 3: Write minimal implementation**

En `config.py`, junto a los `FACE_*` de la Task 3:

```python
FOTOS_POR_PERSONA = int(_get("FOTOS_POR_PERSONA", "5") or "5")
FOTOS_GRUPALES = int(_get("FOTOS_GRUPALES", "3") or "3")
FOTOS_MINIMO_SIN_CARAS = int(_get("FOTOS_MINIMO_SIN_CARAS", "4") or "4")
DEDUP_HAMMING_MAX = int(_get("DEDUP_HAMMING_MAX", "8") or "8")
ANTI_REPETICION_DIAS = int(_get("ANTI_REPETICION_DIAS", "45") or "45")
```

```python
# src/banco.py
"""Política del banco: qué fotos se conservan por banda.

PURO y sin IO — recibe fotos con sus caras ya agrupadas y devuelve qué ids
entran. Vive aparte porque es la pieza que se va a ajustar con el tiempo y debe
poder probarse sin imágenes ni base de datos.

El cupo es POR PERSONA, no por banda: un tope por banda puede llenarse con
diez fotos del vocalista y dejar al baterista fuera, que es exactamente el
problema que este banco resuelve.
"""
from __future__ import annotations

from typing import Any


def puntuar(foto: dict[str, Any]) -> float:
    """Qué tan buena es como retrato: nitidez × confianza × tamaño de la cara.

    Sin caras cae a la nitidez sola. El factor de tamaño evita que gane una
    foto nitidísima donde la persona sale de 20 píxeles al fondo.
    """
    nitidez = float(foto.get("nitidez") or 0.0)
    caras = foto.get("caras") or []
    if not caras:
        return nitidez
    mejor = max(caras, key=lambda c: c.get("frac_area", 0.0))
    return nitidez * float(mejor.get("det_score", 0.0)) * float(mejor.get("frac_area", 0.0))


def aplicar_cupo(fotos: list[dict[str, Any]], por_persona: int, grupales: int,
                 minimo_sin_caras: int) -> set[int]:
    """Ids que entran al banco.

    Tres cubetas independientes: una por persona (fotos de una sola cara), una
    de grupales (2+ caras), y la degradación sin caras para foros y paisajes.
    """
    ordenadas = sorted(fotos, key=puntuar, reverse=True)
    individuales = [f for f in ordenadas if len(f.get("caras") or []) == 1]
    de_grupo = [f for f in ordenadas if len(f.get("caras") or []) >= 2]
    sin_caras = [f for f in ordenadas if not (f.get("caras") or [])]

    dentro: set[int] = set()
    usado: dict[int, int] = {}
    for f in individuales:
        idx = f["caras"][0]["persona_idx"]
        if usado.get(idx, 0) < por_persona:
            usado[idx] = usado.get(idx, 0) + 1
            dentro.add(f["id"])

    dentro.update(f["id"] for f in de_grupo[:grupales])

    # Degradación: solo si la banda no dio material con caras.
    if not dentro:
        dentro.update(f["id"] for f in sin_caras[:minimo_sin_caras])
    return dentro
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_banco.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/banco.py tests/test_banco.py config.py
git commit -m "feat(banco): política de cupo por persona"
```

---

### Task 6: Procesar una banda de punta a punta

**Files:**
- Modify: `src/banco.py`
- Test: `tests/test_banco_fotos.py`

**Interfaces:**
- Consumes: `dedup_fotos.agrupar_duplicadas`, `faces.detectar`, `faces.firma`, `faces.agrupar`, `banco.aplicar_cupo`.
- Produces: `banco.procesar_banda(cx, band_id: int, *, _analizador=None) -> dict` con claves `personas`, `fotos_dentro`, `fotos_fuera`, `duplicadas`. Persiste `personas`, `face_signatures`, `photos.persona_id` y `photos.usable_meme`.

El parámetro `_analizador` inyecta la función `(path) -> (hash, nitidez, [(bbox, score, frac, firma)])` para poder probar sin modelos ni imágenes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_banco_fotos.py — agregar
import numpy as np

from src import banco


def _hash(bits: str) -> np.ndarray:
    v = np.zeros(64, dtype=bool)
    for i, c in enumerate(bits):
        v[i] = c == "1"
    return v


def _vec(*componentes: float) -> np.ndarray:
    v = np.zeros(128, dtype=np.float32)
    v[:len(componentes)] = componentes
    return v / np.linalg.norm(v)


def _analizador_falso(mapa):
    """Devuelve un analizador que consulta `mapa` por nombre de archivo."""
    def analizar(path):
        return mapa[str(path).split("/")[-1]]
    return analizar


def test_procesar_banda_crea_personas_y_marca_banco(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    for n in ("a.jpg", "b.jpg", "c.jpg"):
        db.insert(cx, "photos", band_id=bid, path=n, source_post_id=n[0])
    # a y b son la MISMA persona; c es otra.
    mapa = {
        "a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.99, 0.25, _vec(1, 0.01))]),
        "b.jpg": (_hash("0" * 64), 80.0, [((0, 0, 50, 50), 0.98, 0.25, _vec(1, 0.02))]),
        "c.jpg": (_hash("0101" * 16), 70.0, [((0, 0, 50, 50), 0.97, 0.25, _vec(0, 1))]),
    }
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    assert res["personas"] == 2
    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    assert len(personas) == 2
    assert all(p["etiqueta_auto"].startswith("persona ") for p in personas)
    firmas = db.rows(cx, "SELECT * FROM face_signatures")
    assert len(firmas) == 3
    assert all(f["persona_id"] is not None for f in firmas)
    # Con cupo por defecto (5/persona) las tres entran al banco.
    assert res["fotos_dentro"] == 3
    assert all(p["usable_meme"] == 1
               for p in db.rows(cx, "SELECT usable_meme FROM photos"))


def test_procesar_banda_dedup_saca_la_copia(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    for n in ("a.jpg", "b.jpg"):
        db.insert(cx, "photos", band_id=bid, path=n, source_post_id=n[0])
    igual = _hash("1" * 64)
    mapa = {
        "a.jpg": (igual, 50.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))]),
        "b.jpg": (igual, 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))]),
    }
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    assert res["duplicadas"] == 1
    # La menos nítida queda fuera del banco pero NO se borra ni se marca descartada.
    fila_a = db.rows(cx, "SELECT * FROM photos WHERE path = 'a.jpg'")[0]
    assert fila_a["usable_meme"] == 0 and fila_a["descartada"] == 0


def test_procesar_banda_sin_caras_degrada(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="Foro", ig_handle="f", tipo="foro")
    for i in range(6):
        db.insert(cx, "photos", band_id=bid, path=f"{i}.jpg", source_post_id=str(i))
    mapa = {f"{i}.jpg": (_hash(bin(i + 3)[2:].zfill(64)), float(i * 10), [])
            for i in range(6)}
    res = banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    assert res["personas"] == 0
    assert res["fotos_dentro"] == 4  # FOTOS_MINIMO_SIN_CARAS


def test_procesar_banda_es_idempotente(cx, tmp_path, monkeypatch) -> None:
    """Correrla dos veces no duplica personas ni firmas."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    mapa = {"a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))
    assert len(db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))) == 1
    assert len(db.rows(cx, "SELECT * FROM face_signatures")) == 1


def test_reprocesar_conserva_el_nombre_capturado_a_mano(cx, tmp_path, monkeypatch) -> None:
    """El batch NUNCA pisa lo manual: si nombraste una cara, sigue nombrada."""
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda")
    db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a")
    mapa = {"a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0.01))])}
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    # Ricardo la nombra en la GUI.
    persona = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))[0]
    mid = db.insert(cx, "members", band_id=bid, nombre="Fercho", rol="baterista")
    db.update(cx, "personas", persona["id"], member_id=mid)

    # Entra una foto nueva de la MISMA persona y se reprocesa.
    db.insert(cx, "photos", band_id=bid, path="b.jpg", source_post_id="b")
    mapa["b.jpg"] = (_hash("0" * 64), 80.0, [((0, 0, 50, 50), 0.9, 0.2, _vec(1, 0.02))])
    banco.procesar_banda(cx, bid, _analizador=_analizador_falso(mapa))

    personas = db.rows(cx, "SELECT * FROM personas WHERE band_id = ?", (bid,))
    assert len(personas) == 1
    assert personas[0]["member_id"] == mid  # el nombre sobrevivió al reproceso
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_banco_fotos.py -v`
Expected: FAIL — `AttributeError: module 'src.banco' has no attribute 'procesar_banda'`.

- [ ] **Step 3: Write minimal implementation**

Agregar a `src/banco.py`:

```python
import json
from pathlib import Path

import numpy as np

import config
from src import db, dedup_fotos, faces, imghash


def _centroide(vecs: list["np.ndarray"]) -> "np.ndarray":
    """Vector medio L2-normalizado de un grupo de firmas."""
    media = np.mean(np.stack(vecs), axis=0).astype(np.float32)
    norma = float(np.linalg.norm(media))
    return media / norma if norma else media


def _centroides_nombrados(cx, band_id: int) -> list[tuple[int, "np.ndarray"]]:
    """(member_id, centroide) de las personas de la banda que ya tienen nombre."""
    filas = db.rows(cx, """
        SELECT p.member_id, f.embedding
          FROM personas p JOIN face_signatures f ON f.persona_id = p.id
         WHERE p.band_id = ? AND p.member_id IS NOT NULL
    """, (band_id,))
    por_member: dict[int, list["np.ndarray"]] = {}
    for fila in filas:
        por_member.setdefault(fila["member_id"], []).append(
            np.frombuffer(fila["embedding"], dtype=np.float32))
    return [(mid, _centroide(vs)) for mid, vs in por_member.items()]


def _member_mas_parecido(nombradas: list[tuple[int, "np.ndarray"]],
                         centroide: "np.ndarray") -> int | None:
    """member_id del nombrado más parecido, o None si ninguno alcanza el umbral."""
    mejor, mejor_sim = None, config.FACE_COS_MISMA_PERSONA
    for member_id, c in nombradas:
        sim = faces.similitud(c, centroide)
        if sim >= mejor_sim:
            mejor, mejor_sim = member_id, sim
    return mejor


def _analizar_real(path: Path):
    """(hash, nitidez, [(bbox, det_score, frac_area, firma)]) de una foto en disco."""
    import cv2
    from src import classify
    img = cv2.imread(str(path))
    if img is None:
        return None, 0.0, []
    gris = classify.cargar_normalizada(path)
    nitidez = classify.medir_nitidez(gris) if gris is not None else 0.0
    detectadas = [(c.bbox, c.det_score, c.frac_area, faces.firma(img, c))
                  for c in faces.detectar(img)]
    return imghash.phash(path), nitidez, detectadas


def procesar_banda(cx, band_id: int, *, _analizador=None) -> dict:
    """Deduplica, agrupa caras, aplica cupo y persiste. Idempotente."""
    analizar = _analizador or _analizar_real
    filas = db.rows(cx, """
        SELECT id, path, nitidez FROM photos
         WHERE band_id = ? AND descartada = 0
    """, (band_id,))
    if not filas:
        return {"personas": 0, "fotos_dentro": 0, "fotos_fuera": 0, "duplicadas": 0}

    analizadas: list[dict] = []
    for fila in filas:
        p = Path(fila["path"])
        if not p.is_absolute():
            p = config.BASE_DIR / p
        h, nitidez, caras = analizar(p)
        analizadas.append({"id": fila["id"], "hash": h, "nitidez": nitidez,
                           "caras_raw": caras})

    # 1. Dedup: solo el representante de cada grupo compite por el cupo.
    grupos_dup = dedup_fotos.agrupar_duplicadas(analizadas, config.DEDUP_HAMMING_MAX)
    representantes = [g[0] for g in grupos_dup]
    duplicadas = sum(len(g) - 1 for g in grupos_dup)

    # 2. Agrupar TODAS las caras de la banda en personas.
    plano: list[tuple[int, tuple, float, float, "np.ndarray"]] = []
    for foto in representantes:
        for bbox, score, frac, vec in foto["caras_raw"]:
            plano.append((foto["id"], bbox, score, frac, vec))
    grupos_persona = faces.agrupar([p[4] for p in plano], config.FACE_COS_MISMA_PERSONA)
    idx_de_cara = {}
    for i, grupo in enumerate(grupos_persona):
        for j in grupo:
            idx_de_cara[j] = i

    # 3. Persistir personas. Antes de recrearlas, guardamos el centroide de las
    #    que YA tienen nombre para volver a pegárselo al grupo equivalente: el
    #    batch nunca pisa lo manual (misma regla que `generos_fuente`).
    nombradas = _centroides_nombrados(cx, band_id)
    cx.execute("DELETE FROM face_signatures WHERE photo_id IN "
               "(SELECT id FROM photos WHERE band_id = ?)", (band_id,))
    cx.execute("DELETE FROM personas WHERE band_id = ?", (band_id,))

    ids_persona: list[int] = []
    for i, grupo in enumerate(grupos_persona):
        centroide = _centroide([plano[j][4] for j in grupo])
        member_id = _member_mas_parecido(nombradas, centroide)
        ids_persona.append(db.insert(cx, "personas", band_id=band_id,
                                     member_id=member_id,
                                     etiqueta_auto=f"persona {chr(65 + i)}"))
    for j, (photo_id, bbox, score, frac, vec) in enumerate(plano):
        db.insert(cx, "face_signatures", photo_id=photo_id,
                  persona_id=ids_persona[idx_de_cara[j]],
                  bbox=json.dumps(list(bbox)), det_score=score,
                  embedding=np.asarray(vec, dtype=np.float32).tobytes())

    # 4. Cupo.
    para_cupo = []
    for foto in representantes:
        caras = [{"persona_idx": idx_de_cara[j], "det_score": p[2], "frac_area": p[3]}
                 for j, p in enumerate(plano) if p[0] == foto["id"]]
        para_cupo.append({"id": foto["id"], "nitidez": foto["nitidez"], "caras": caras})
    dentro = aplicar_cupo(para_cupo, config.FOTOS_POR_PERSONA, config.FOTOS_GRUPALES,
                          config.FOTOS_MINIMO_SIN_CARAS)

    # 5. Marcar. NUNCA se borra ni se marca `descartada`: solo sale del banco.
    caras_por_foto: dict[int, list[int]] = {}
    for j, p in enumerate(plano):
        caras_por_foto.setdefault(p[0], []).append(j)
    for foto in analizadas:
        entra = foto["id"] in dentro
        indices = caras_por_foto.get(foto["id"], [])
        # La persona de la foto es la de la cara MÁS GRANDE (la protagonista).
        persona_id = None
        if indices:
            dominante = max(indices, key=lambda j: plano[j][3])
            persona_id = ids_persona[idx_de_cara[dominante]]
        caras_foto = indices
        db.update(cx, "photos", foto["id"],
                  usable_meme=1 if entra else 0,
                  es_grupal=1 if len(caras_foto) >= 2 else 0,
                  faces_count=len(caras_foto),
                  nitidez=round(foto["nitidez"], 1),
                  persona_id=persona_id)
    cx.commit()
    return {"personas": len(grupos_persona), "fotos_dentro": len(dentro),
            "fotos_fuera": len(analizadas) - len(dentro), "duplicadas": duplicadas}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_banco_fotos.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/banco.py tests/test_banco_fotos.py
git commit -m "feat(banco): procesar banda (dedup + personas + cupo) idempotente"
```

---

### Task 7: Selección con anti-repetición por persona

**Files:**
- Modify: `src/planner.py:59-77` (la query de `seleccionar`)
- Test: `tests/test_banco_seleccion.py`

**Interfaces:**
- Consumes: `photos.persona_id` (Task 1), `config.ANTI_REPETICION_DIAS` (Task 5).
- Produces: `planner.personas_recientes(cx, dias: int, ahora=None) -> set[int]` — personas que salieron en un post dentro de la ventana.

Este es el cambio más pequeño del plan y el más visible: la anti-repetición pasa de ser por archivo a ser por cara.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_banco_seleccion.py
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src import db, planner


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def _banda_con_dos_personas(cx):
    bid = db.insert(cx, "bands", nombre="K", ig_handle="k", tipo="banda", prioridad=1)
    p1 = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    p2 = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona B")
    f1 = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                   usable_meme=1, nitidez=100.0, persona_id=p1)
    f2 = db.insert(cx, "photos", band_id=bid, path="b.jpg", source_post_id="b",
                   usable_meme=1, nitidez=10.0, persona_id=p2)
    return bid, p1, p2, f1, f2


def test_personas_recientes_detecta_la_publicada(cx) -> None:
    bid, p1, p2, f1, _ = _banda_con_dos_personas(cx)
    ahora = datetime(2026, 8, 3, 12, 0)
    db.insert(cx, "content_queue", tipo="meme", band_id=bid, photo_id=f1,
              status="publicado",
              scheduled_datetime=(ahora - timedelta(days=10)).isoformat())
    assert planner.personas_recientes(cx, dias=45, ahora=ahora) == {p1}


def test_persona_fuera_de_ventana_no_cuenta(cx) -> None:
    bid, p1, _, f1, _ = _banda_con_dos_personas(cx)
    ahora = datetime(2026, 8, 3, 12, 0)
    db.insert(cx, "content_queue", tipo="meme", band_id=bid, photo_id=f1,
              status="publicado",
              scheduled_datetime=(ahora - timedelta(days=100)).isoformat())
    assert planner.personas_recientes(cx, dias=45, ahora=ahora) == set()


def test_seleccionar_evita_persona_reciente(cx) -> None:
    """Aunque su foto sea MUCHO más nítida, no repite la misma cara."""
    bid, p1, p2, f1, f2 = _banda_con_dos_personas(cx)
    ahora = datetime(2026, 8, 3, 12, 0)
    db.insert(cx, "content_queue", tipo="meme", band_id=bid, photo_id=f1,
              status="publicado",
              scheduled_datetime=(ahora - timedelta(days=5)).isoformat())
    sel = planner.seleccionar(cx, max_posts=1, ahora=ahora)
    assert [f["photo_id"] for f in sel] == [f2]


def test_sin_persona_sigue_funcionando(cx) -> None:
    """Fotos sin cara (foro) no se excluyen: persona_id NULL nunca es 'reciente'."""
    bid = db.insert(cx, "bands", nombre="Foro", ig_handle="f", tipo="foro", prioridad=1)
    fid = db.insert(cx, "photos", band_id=bid, path="x.jpg", source_post_id="x",
                    usable_meme=1, nitidez=50.0)
    sel = planner.seleccionar(cx, max_posts=1, ahora=datetime(2026, 8, 3))
    assert [f["photo_id"] for f in sel] == [fid]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_banco_seleccion.py -v`
Expected: FAIL — `AttributeError: module 'src.planner' has no attribute 'personas_recientes'`.

- [ ] **Step 3: Write minimal implementation**

En `src/planner.py`, agregar antes de `seleccionar`:

```python
def personas_recientes(cx, dias: int, ahora: "datetime | None" = None) -> set[int]:
    """Personas que ya salieron en un post dentro de la ventana de `dias`.

    Mira `content_queue` (no `photos.usada`) porque ahí vive la fecha del post.
    """
    from datetime import datetime as _dt, timedelta as _td
    ahora = ahora or _dt.now()
    corte = (ahora - _td(days=dias)).isoformat()
    filas = db.rows(cx, """
        SELECT DISTINCT p.persona_id
          FROM content_queue q JOIN photos p ON p.id = q.photo_id
         WHERE p.persona_id IS NOT NULL
           AND q.status IN ('en_sheet', 'publicado')
           AND q.scheduled_datetime >= ?
    """, (corte,))
    return {f["persona_id"] for f in filas}
```

Cambiar la firma y la query de `seleccionar`:

```python
def seleccionar(cx, max_posts: int, ahora: "datetime | None" = None) -> list[dict[str, Any]]:
```

Agregar `p.persona_id` al SELECT y, después de traer `fotos`, filtrar:

```python
    # Anti-repetición POR CARA, no por archivo: lo que el ojo nota es que
    # vuelva a salir la misma persona, no que se repita el mismo jpg.
    recientes = personas_recientes(cx, config.ANTI_REPETICION_DIAS, ahora)
    if recientes:
        frescas = [f for f in fotos if f["persona_id"] not in recientes]
        # Si una banda se queda sin material fresco, mejor repetir cara que
        # dejarla fuera del plan: el filtro es preferencia, no prohibición.
        bandas_frescas = {f["band_id"] for f in frescas}
        fotos = frescas + [f for f in fotos if f["band_id"] not in bandas_frescas]
```

Asegurar `import config` en `planner.py` si no está.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_banco_seleccion.py -v`
Expected: PASS (4 tests).

Luego la suite completa: `.venv/bin/python -m pytest`
Expected: solo los 2 fallos preexistentes documentados en Global Constraints.

- [ ] **Step 5: Commit**

```bash
git add src/planner.py tests/test_banco_seleccion.py
git commit -m "feat(banco): anti-repetición por persona en la selección de fotos"
```

---

### Task 8: Comando para procesar el acervo existente

**Files:**
- Modify: `src/banco.py` (agregar `main` y CLI)
- Test: `tests/test_banco_fotos.py`

**Interfaces:**
- Consumes: `banco.procesar_banda` (Task 6).
- Produces: `banco.procesar(handles: list[str] | None = None, *, limite_por_banda: int = 40, _cx=None) -> dict` con `bandas`, `personas`, `fotos_dentro`, `duplicadas`, `fallidas`.

`limite_por_banda` implementa el "perezoso" del spec: se analizan las N mejores por nitidez, no las 7,712.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_banco_fotos.py — agregar
def test_procesar_recorre_bandas_activas(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    b1 = db.insert(cx, "bands", nombre="A", ig_handle="a", tipo="banda", activa=1)
    b2 = db.insert(cx, "bands", nombre="B", ig_handle="b", tipo="banda", activa=0)
    db.insert(cx, "photos", band_id=b1, path="a.jpg", source_post_id="a")
    db.insert(cx, "photos", band_id=b2, path="b.jpg", source_post_id="b")
    mapa = {
        "a.jpg": (_hash("1" * 64), 90.0, [((0, 0, 5, 5), 0.9, 0.2, _vec(1, 0))]),
        "b.jpg": (_hash("0" * 64), 90.0, [((0, 0, 5, 5), 0.9, 0.2, _vec(0, 1))]),
    }
    res = banco.procesar(_cx=cx, _analizador=_analizador_falso(mapa))
    assert res["bandas"] == 1  # solo la activa
    assert res["personas"] == 1


def test_procesar_banda_caida_no_tumba_el_lote(cx, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(banco.config, "BASE_DIR", tmp_path)
    b1 = db.insert(cx, "bands", nombre="A", ig_handle="a", tipo="banda", activa=1)
    b2 = db.insert(cx, "bands", nombre="B", ig_handle="b", tipo="banda", activa=1)
    db.insert(cx, "photos", band_id=b1, path="rota.jpg", source_post_id="r")
    db.insert(cx, "photos", band_id=b2, path="b.jpg", source_post_id="b")

    def analizar(path):
        if "rota" in str(path):
            raise OSError("imagen corrupta")
        return _hash("0" * 64), 90.0, [((0, 0, 5, 5), 0.9, 0.2, _vec(0, 1))]

    res = banco.procesar(_cx=cx, _analizador=analizar)
    assert res["fallidas"] == ["a"]
    assert res["bandas"] == 1  # la sana sí se procesó
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_banco_fotos.py -v`
Expected: FAIL — `AttributeError: module 'src.banco' has no attribute 'procesar'`.

- [ ] **Step 3: Write minimal implementation**

En `procesar_banda`, cambiar la query para respetar el límite perezoso:

```python
    filas = db.rows(cx, """
        SELECT id, path, nitidez FROM photos
         WHERE band_id = ? AND descartada = 0
         ORDER BY nitidez DESC
         LIMIT ?
    """, (band_id, limite))
```

y agregar el parámetro `limite: int = 40` a la firma de `procesar_banda`.

Agregar al final de `src/banco.py`:

```python
def procesar(handles: list[str] | None = None, *, limite_por_banda: int = 40,
             _cx=None, _analizador=None) -> dict:
    """Corre el banco sobre las bandas activas. Una caída aislada no tumba el lote."""
    propia = _cx is None
    cx = _cx or db.connect()
    resumen = {"bandas": 0, "personas": 0, "fotos_dentro": 0,
               "duplicadas": 0, "fallidas": []}
    try:
        if propia:
            db.init_db(cx)
        q = "SELECT id, nombre, ig_handle FROM bands WHERE activa = 1"
        params: tuple = ()
        if handles:
            marcas = ",".join("?" * len(handles))
            q += f" AND lower(ig_handle) IN ({marcas})"
            params = tuple(h.lstrip("@").lower() for h in handles)
        for banda in db.rows(cx, q + " ORDER BY prioridad, id", params):
            print(f"▶ @{banda['ig_handle']} ({banda['nombre']})")
            try:
                r = procesar_banda(cx, banda["id"], limite=limite_por_banda,
                                   _analizador=_analizador)
            except Exception as exc:  # noqa: BLE001 — banda rota no tumba la corrida
                print(f"   ❌ {exc}")
                resumen["fallidas"].append(banda["ig_handle"])
                continue
            resumen["bandas"] += 1
            resumen["personas"] += r["personas"]
            resumen["fotos_dentro"] += r["fotos_dentro"]
            resumen["duplicadas"] += r["duplicadas"]
            print(f"   ✅ {r['personas']} persona(s) · {r['fotos_dentro']} al banco "
                  f"· {r['duplicadas']} duplicada(s)")
        return resumen
    finally:
        if propia:
            cx.close()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Banco de fotos por persona")
    parser.add_argument("handles", nargs="*", help="handles específicos (vacío = todas)")
    parser.add_argument("--limite", type=int, default=40,
                        help="fotos por banda a analizar (default 40)")
    args = parser.parse_args()
    try:
        res = procesar(args.handles or None, limite_por_banda=args.limite)
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido.")
    print(f"\nResumen: {res['bandas']} banda(s) · {res['personas']} persona(s) · "
          f"{res['fotos_dentro']} foto(s) al banco · {res['duplicadas']} duplicada(s)"
          + (f" · fallidas: {', '.join(res['fallidas'])}" if res["fallidas"] else ""))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_banco_fotos.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add src/banco.py tests/test_banco_fotos.py
git commit -m "feat(banco): comando para procesar el acervo por bandas"
```

---

### Task 9: Fetch selectivo en Business Discovery

**Files:**
- Modify: `src/business_discovery.py` (función `traer`, y `guardar_media`)
- Test: `tests/test_business_discovery.py`

**Interfaces:**
- Consumes: `banco.procesar_banda` (Task 6), `config.BD_POSTS_A_MIRAR` (Task 5).
- Produces: `business_discovery.traer(..., selectivo: bool = False)` — con `selectivo=True` mira `BD_POSTS_A_MIRAR` posts, procesa el banco y **borra del disco** las descargas que no entraron.

Clave del spec: pedir 50 posts cuesta lo mismo en cuota que pedir 12. Lo caro es guardar, no consultar.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_business_discovery.py — agregar
def test_traer_selectivo_borra_lo_que_no_entra(cx, tmp_path, monkeypatch) -> None:
    """Las fotos que no entran al banco se borran del disco y de la DB."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])
    medias = [_media(shortcode=f"S{i}") for i in range(3)]
    _mock_get(monkeypatch, _perfil(medias=medias))

    # El banco solo deja la primera.
    def fake_procesar(conn, band_id, **kw):
        ids = [r["id"] for r in db.rows(conn, "SELECT id FROM photos ORDER BY id")]
        for pid in ids[1:]:
            db.update(conn, "photos", pid, usable_meme=0)
        db.update(conn, "photos", ids[0], usable_meme=1)
        return {"personas": 1, "fotos_dentro": 1, "fotos_fuera": len(ids) - 1,
                "duplicadas": 0}

    monkeypatch.setattr(bd.banco, "procesar_banda", fake_procesar)
    res = bd.traer(["kabala_oficial"], _cx=cx, selectivo=True)

    assert res["fotos"] == 1
    assert len(db.rows(cx, "SELECT id FROM photos")) == 1
    assert len(list((tmp_path / "kabala_oficial").glob("*.jpg"))) == 1


def test_traer_no_selectivo_conserva_todo(cx, tmp_path, monkeypatch) -> None:
    """El modo por defecto no borra nada: compatible con lo ya traído."""
    monkeypatch.setattr(bd.config, "FB_IG_USER_ID", "999")
    monkeypatch.setattr(bd.config, "FB_PAGE_ACCESS_TOKEN", "tok")
    monkeypatch.setattr(bd.config, "resolve_photos_dir", lambda: tmp_path)
    monkeypatch.setattr(bd.config, "BASE_DIR", tmp_path)
    monkeypatch.setattr(bd, "_descargar", lambda u, d: (d.write_bytes(b"j"), True)[1])
    _mock_get(monkeypatch, _perfil(medias=[_media(shortcode=f"S{i}") for i in range(3)]))
    res = bd.traer(["kabala_oficial"], _cx=cx)
    assert res["fotos"] == 3
    assert len(db.rows(cx, "SELECT id FROM photos")) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_business_discovery.py -v`
Expected: FAIL — `TypeError: traer() got an unexpected keyword argument 'selectivo'`.

- [ ] **Step 3: Write minimal implementation**

En `config.py`, junto a los otros parámetros del banco:

```python
BD_POSTS_A_MIRAR = int(_get("BD_POSTS_A_MIRAR", "50") or "50")
```

En `src/business_discovery.py`, agregar `from src import banco` a los imports y cambiar `traer`:

```python
def traer(handles: list[str], *, max_posts: int | None = None, activar: bool = False,
          selectivo: bool = False, _cx=None) -> dict[str, Any]:
```

En el docstring, agregar:

```
    `selectivo=True`: mira `BD_POSTS_A_MIRAR` posts, corre el banco por persona y
    BORRA las descargas que no entraron al cupo. Pedir 50 posts cuesta lo mismo
    en cuota que pedir 12 — lo caro es guardar, no consultar.
```

Sustituir la línea del `max_posts` por defecto dentro de `fetch_cuenta` en el bucle:

```python
            mirar = config.BD_POSTS_A_MIRAR if selectivo else max_posts
            try:
                bd_data = fetch_cuenta(handle, max_posts=mirar, ig_id=ig_id)
```

Y después de `guardar_media`, antes de actualizar `scraped_at`:

```python
            if selectivo:
                banco.procesar_banda(cx, band_id)
                nuevas = _podar_fuera_del_banco(cx, band_id, {n["shortcode"] for n in nuevas})
```

Agregar la función auxiliar:

```python
def _podar_fuera_del_banco(cx, band_id: int, shortcodes_nuevos: set[str]) -> list[dict]:
    """Borra de disco y de la DB las fotos RECIÉN traídas que no entraron al banco.

    Solo toca lo de esta corrida (`shortcodes_nuevos`): una foto vieja que salga
    del cupo se marca `usable_meme=0` pero NUNCA se borra — regla del spec.
    """
    fuera = db.rows(cx, """
        SELECT id, path, source_post_id FROM photos
         WHERE band_id = ? AND usable_meme = 0
    """, (band_id,))
    borradas = 0
    for fila in fuera:
        if fila["source_post_id"] not in shortcodes_nuevos:
            continue
        p = Path(fila["path"])
        if not p.is_absolute():
            p = config.BASE_DIR / p
        p.unlink(missing_ok=True)
        cx.execute("DELETE FROM face_signatures WHERE photo_id = ?", (fila["id"],))
        cx.execute("DELETE FROM photos WHERE id = ?", (fila["id"],))
        borradas += 1
    cx.commit()
    if borradas:
        print(f"   🗑  {borradas} descarga(s) fuera del cupo, borradas")
    return db.rows(cx, "SELECT id, source_post_id FROM photos WHERE band_id = ?",
                   (band_id,))
```

Agregar el flag al CLI:

```python
    parser.add_argument("--selectivo", action="store_true",
                        help=f"mira {config.BD_POSTS_A_MIRAR} posts y guarda solo lo que entra al banco")
```

y pasarlo: `traer(objetivos, max_posts=args.max_posts, activar=args.activar, selectivo=args.selectivo)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_business_discovery.py -v`
Expected: PASS (31 tests).

- [ ] **Step 5: Commit**

```bash
git add src/business_discovery.py tests/test_business_discovery.py config.py
git commit -m "feat(banco): fetch selectivo en business discovery"
```

---

### Task 10: GUI de corrección de caras

**Files:**
- Modify: `web/app.py` (rutas nuevas)
- Create: `web/templates/caras.html`
- Test: `tests/test_caras_web.py`

**Interfaces:**
- Consumes: tablas `personas` y `face_signatures` (Task 1).
- Produces: `GET /banda/{band_id}/caras`, `POST /personas/{persona_id}/nombrar`, `POST /personas/{persona_id}/fusionar`, `POST /personas/{persona_id}/descartar`.

**Recordatorio operativo:** las rutas nuevas en `web/app.py` requieren **reiniciar uvicorn** (corre en 127.0.0.1:8742 sin `--reload`). Las plantillas sí se recargan solas.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_caras_web.py
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db


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


def test_vista_caras_lista_personas(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    fid = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                    persona_id=pid, usable_meme=1)
    db.insert(cx, "face_signatures", photo_id=fid, persona_id=pid,
              bbox="[0,0,10,10]", det_score=0.9, embedding=b"\x00" * 512)
    r = cli.get(f"/banda/{bid}/caras")
    assert r.status_code == 200
    assert "persona A" in r.text


def test_nombrar_persona_crea_member(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    r = cli.post(f"/personas/{pid}/nombrar",
                 data={"nombre": "Fercho", "rol": "baterista"})
    assert r.status_code in (200, 303)
    miembros = db.rows(cx, "SELECT * FROM members WHERE band_id = ?", (bid,))
    assert len(miembros) == 1
    assert miembros[0]["nombre"] == "Fercho" and miembros[0]["rol"] == "baterista"
    assert db.get(cx, "personas", pid)["member_id"] == miembros[0]["id"]


def test_nombrar_dos_veces_actualiza_sin_duplicar(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    cli.post(f"/personas/{pid}/nombrar", data={"nombre": "Fercho", "rol": "bat"})
    cli.post(f"/personas/{pid}/nombrar", data={"nombre": "Fernando", "rol": "batería"})
    miembros = db.rows(cx, "SELECT * FROM members WHERE band_id = ?", (bid,))
    assert len(miembros) == 1 and miembros[0]["nombre"] == "Fernando"


def test_fusionar_personas(cliente) -> None:
    """Dos grupos que son la misma persona: se fusionan sin perder firmas."""
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    p1 = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    p2 = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona B")
    f1 = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                   persona_id=p2)
    db.insert(cx, "face_signatures", photo_id=f1, persona_id=p2,
              bbox="[0,0,1,1]", det_score=0.9, embedding=b"\x00" * 512)
    r = cli.post(f"/personas/{p1}/fusionar", data={"otra_id": str(p2)})
    assert r.status_code in (200, 303)
    assert db.get(cx, "personas", p2) is None
    assert db.rows(cx, "SELECT persona_id FROM face_signatures")[0]["persona_id"] == p1
    assert db.get(cx, "photos", f1)["persona_id"] == p1


def test_descartar_persona_saca_sus_fotos_del_banco(cliente) -> None:
    cli, cx = cliente
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala_oficial")
    pid = db.insert(cx, "personas", band_id=bid, etiqueta_auto="persona A")
    fid = db.insert(cx, "photos", band_id=bid, path="a.jpg", source_post_id="a",
                    persona_id=pid, usable_meme=1)
    r = cli.post(f"/personas/{pid}/descartar")
    assert r.status_code in (200, 303)
    assert db.get(cx, "photos", fid)["usable_meme"] == 0
    assert db.get(cx, "personas", pid) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_caras_web.py -v`
Expected: FAIL — 404 en `/banda/{bid}/caras`.

- [ ] **Step 3: Write minimal implementation**

Crear `web/templates/caras.html`. Revisar antes `web/templates/banda_detalle.html` para copiar el nombre exacto del bloque que define `base.html` (el ejemplo asume `contenido`; si difiere, ajustarlo):

```html
{% extends "base.html" %}
{% block contenido %}
<h1>Caras de {{ banda.nombre }}</h1>
<p><a href="/banda/{{ banda.id }}">← volver a la banda</a></p>

{% for p in personas %}
<section class="persona">
  <h2>{{ p.etiqueta_auto }}{% if p.nombre %} — {{ p.nombre }}{% if p.rol %} ({{ p.rol }}){% endif %}{% endif %}</h2>
  <p>{{ p.n_fotos }} foto(s)</p>
  <div class="miniaturas">
    {% for f in p.fotos %}
      <img src="/foto/{{ f.id }}" alt="" width="120">
    {% endfor %}
  </div>
  <form hx-post="/personas/{{ p.id }}/nombrar" hx-swap="none">
    <input name="nombre" placeholder="nombre" value="{{ p.nombre or '' }}">
    <input name="rol" placeholder="rol" value="{{ p.rol or '' }}">
    <button type="submit">Guardar</button>
  </form>
  <form hx-post="/personas/{{ p.id }}/fusionar" hx-swap="none">
    <select name="otra_id">
      {% for otra in personas if otra.id != p.id %}
        <option value="{{ otra.id }}">{{ otra.etiqueta_auto }}</option>
      {% endfor %}
    </select>
    <button type="submit">Fusionar con…</button>
  </form>
  <button hx-post="/personas/{{ p.id }}/descartar" hx-confirm="¿Sacar del banco todas sus fotos?">Descartar</button>
</section>
{% else %}
<p>Esta banda no tiene caras agrupadas todavía. Corre
   <code>python -m src.banco {{ banda.ig_handle }}</code>.</p>
{% endfor %}
{% endblock %}
```

En `web/app.py`:

```python
@app.get("/banda/{band_id}/caras", response_class=HTMLResponse)
def caras(request: Request, band_id: int):
    cx = db.connect()
    try:
        banda = db.get(cx, "bands", band_id)
        if not banda:
            raise HTTPException(status_code=404, detail="banda no encontrada")
        personas = db.rows(cx, """
            SELECT p.id, p.etiqueta_auto, m.nombre, m.rol,
                   (SELECT count(*) FROM face_signatures f WHERE f.persona_id = p.id) AS n_fotos
              FROM personas p LEFT JOIN members m ON m.id = p.member_id
             WHERE p.band_id = ? ORDER BY n_fotos DESC
        """, (band_id,))
        for p in personas:
            p["fotos"] = db.rows(cx, """
                SELECT id FROM photos WHERE persona_id = ? ORDER BY nitidez DESC LIMIT 6
            """, (p["id"],))
        return templates.TemplateResponse(
            "caras.html", {"request": request, "banda": banda, "personas": personas})
    finally:
        cx.close()


@app.post("/personas/{persona_id}/nombrar")
def persona_nombrar(persona_id: int, nombre: str = Form(...), rol: str = Form("")):
    cx = db.connect()
    try:
        persona = db.get(cx, "personas", persona_id)
        if not persona:
            raise HTTPException(status_code=404, detail="persona no encontrada")
        if persona["member_id"]:
            db.update(cx, "members", persona["member_id"], nombre=nombre, rol=rol or None)
        else:
            mid = db.insert(cx, "members", band_id=persona["band_id"],
                            nombre=nombre, rol=rol or None)
            db.update(cx, "personas", persona_id, member_id=mid)
        return Response(status_code=204)
    finally:
        cx.close()


@app.post("/personas/{persona_id}/fusionar")
def persona_fusionar(persona_id: int, otra_id: int = Form(...)):
    """Absorbe `otra_id` en `persona_id`: mismo humano mal separado por el clustering."""
    cx = db.connect()
    try:
        if not db.get(cx, "personas", persona_id) or not db.get(cx, "personas", otra_id):
            raise HTTPException(status_code=404, detail="persona no encontrada")
        cx.execute("UPDATE face_signatures SET persona_id = ? WHERE persona_id = ?",
                   (persona_id, otra_id))
        cx.execute("UPDATE photos SET persona_id = ? WHERE persona_id = ?",
                   (persona_id, otra_id))
        cx.execute("DELETE FROM personas WHERE id = ?", (otra_id,))
        cx.commit()
        return Response(status_code=204)
    finally:
        cx.close()


@app.post("/personas/{persona_id}/descartar")
def persona_descartar(persona_id: int):
    """Grupo mal armado: sus fotos salen del banco (no se borran del disco)."""
    cx = db.connect()
    try:
        if not db.get(cx, "personas", persona_id):
            raise HTTPException(status_code=404, detail="persona no encontrada")
        cx.execute("UPDATE photos SET usable_meme = 0, persona_id = NULL "
                   "WHERE persona_id = ?", (persona_id,))
        cx.execute("DELETE FROM face_signatures WHERE persona_id = ?", (persona_id,))
        cx.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        cx.commit()
        return Response(status_code=204)
    finally:
        cx.close()
```

`web/app.py:16` ya importa `FastAPI, Form, HTTPException, Request` pero **no** `Response`: agregarlo a esa línea. La ruta `/foto/{photo_id}` ya existe (`web/app.py:258`) y sirve la imagen local, así que las miniaturas de la plantilla funcionan sin código nuevo.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_caras_web.py -v`
Expected: PASS (5 tests).

Suite completa: `.venv/bin/python -m pytest`
Expected: solo los 2 fallos preexistentes.

Y a mano: reiniciar uvicorn y abrir `http://127.0.0.1:8742/banda/2/caras` (Kabala).

- [ ] **Step 5: Commit**

```bash
git add web/app.py web/templates/caras.html tests/test_caras_web.py
git commit -m "feat(banco): GUI de corrección de caras por banda"
```

---

### Task 11: Calibración contra el acervo real

**Files:**
- Create: `scripts/calibrar_caras.py`
- Modify: `docs/superpowers/specs/2026-08-03-banco-fotos-por-persona-design.md` (anotar los umbrales finales)

**Interfaces:**
- Consumes: `banco.procesar`, `faces.agrupar`.
- Produces: reporte en consola; sin API nueva.

Los umbrales del spec son puntos de arranque, no verdades. Esta tarea existe para convertirlos en números medidos. Como los embeddings quedan guardados, reagrupar con otro umbral cuesta segundos.

- [ ] **Step 1: Correr el banco sobre 5 bandas conocidas**

```bash
.venv/bin/python -m src.banco kabala_oficial los_baxters extranoenemigo_ \
  duckfizz staditche --limite 40
```

Anotar por banda: personas encontradas, fotos al banco, duplicadas.

- [ ] **Step 2: Escribir el script de barrido de umbral**

```python
# scripts/calibrar_caras.py
"""Barre FACE_COS_MISMA_PERSONA sobre las firmas YA guardadas.

No reprocesa imágenes: lee `face_signatures` y reagrupa en memoria. Sirve para
elegir el umbral con datos en vez de con el valor del sample de OpenCV.
"""
import sys

import numpy as np

from src import db, faces

BANDAS = sys.argv[1:] or ["kabala_oficial"]
cx = db.connect()
for handle in BANDAS:
    fila = db.rows(cx, "SELECT id, nombre FROM bands WHERE ig_handle = ?", (handle,))
    if not fila:
        print(f"@{handle}: no está en bands"); continue
    firmas = db.rows(cx, """
        SELECT f.embedding FROM face_signatures f
          JOIN photos p ON p.id = f.photo_id
         WHERE p.band_id = ?
    """, (fila[0]["id"],))
    vecs = [np.frombuffer(f["embedding"], dtype=np.float32) for f in firmas]
    print(f"\n@{handle} — {len(vecs)} cara(s)")
    for u in (0.25, 0.30, 0.363, 0.42, 0.50):
        grupos = faces.agrupar(vecs, u)
        tam = sorted((len(g) for g in grupos), reverse=True)[:6]
        print(f"  umbral {u:.3f} → {len(grupos)} persona(s), tamaños {tam}")
cx.close()
```

- [ ] **Step 3: Correrlo y elegir el umbral**

```bash
.venv/bin/python scripts/calibrar_caras.py kabala_oficial los_baxters staditche
```

Criterio de elección: el umbral más alto en el que el número de personas todavía coincide con el número real de integrantes de la banda. Umbral muy bajo funde a todos en una sola persona; muy alto parte a la misma persona en varias.

Contrastar contra la realidad: Kabala y Los Baxters son bandas (3-5 integrantes); STADITCHE es foro y debería dar pocas personas o ninguna.

- [ ] **Step 4: Fijar el valor y documentarlo**

Si el barrido señala un umbral distinto de 0.363, ponerlo en `.env` como `FACE_COS_MISMA_PERSONA` y anotar en el spec, en la sección de Configuración, el valor elegido con el dato que lo justifica.

- [ ] **Step 5: Commit**

```bash
git add scripts/calibrar_caras.py docs/superpowers/specs/2026-08-03-banco-fotos-por-persona-design.md
git commit -m "chore(banco): script de calibración de umbral facial"
```

---

### Task 12: Retirar los cascades de Haar de classify.py

**Files:**
- Modify: `src/classify.py:48-51` (constantes), `src/classify.py:97-131` (`_solapan`, `contar_caras`), `src/classify.py:80-90` (agregar `cargar_color`), `src/classify.py:264-300` (`clasificar_foto`)
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: `faces.detectar` (Task 3).
- Produces: `classify.cargar_color(path: Path) -> np.ndarray | None`; `classify.contar_caras(img_color) -> int`.

**Cambio de firma decidido por Ricardo (3-ago):** la versión de Haar devolvía `(total, claras)` porque distinguía detecciones débiles de fuertes. YuNet ya filtra por score y tamaño dentro de `faces.detectar`, así que las dos cuentas serían idénticas. En vez de arrastrar una tupla con el mismo número repetido, `contar_caras` devuelve **un solo `int`** y se ajustan sus dos consumidores.

El spec pide que YuNet reemplace a Haar. Si no se hace, `classify` y `banco` usan detectores distintos y se pisan el `faces_count` mutuamente según cuál corra al final.

**Lo que NO se toca:** `hay_persona()` sigue con HOG + `_UPPER`. Detecta gente de espaldas o sin cara visible, que es justo lo que un detector facial no puede hacer. Solo se retiran los cascades **faciales** (`_FRONTAL`, `_PERFIL`) y su ayudante `_solapan`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classify.py — agregar
import numpy as np

from src import classify, faces


def test_contar_caras_usa_yunet(monkeypatch) -> None:
    """contar_caras delega en faces.detectar, no en cascades."""
    llamado = {}

    def fake_detectar(img):
        llamado["si"] = True
        return [
            faces.Cara(bbox=(0, 0, 50, 50), det_score=0.9,
                       landmarks=np.zeros(14, dtype=np.float32), frac_area=0.2),
            faces.Cara(bbox=(60, 0, 40, 40), det_score=0.8,
                       landmarks=np.zeros(14, dtype=np.float32), frac_area=0.1),
        ]

    monkeypatch.setattr(classify.faces, "detectar", fake_detectar)
    assert classify.contar_caras(np.zeros((300, 300, 3), dtype=np.uint8)) == 2
    assert llamado.get("si") is True


def test_contar_caras_sin_caras(monkeypatch) -> None:
    monkeypatch.setattr(classify.faces, "detectar", lambda img: [])
    assert classify.contar_caras(np.zeros((300, 300, 3), dtype=np.uint8)) == 0


def test_cargar_color_normaliza_ancho(tmp_path) -> None:
    import cv2
    p = tmp_path / "grande.jpg"
    cv2.imwrite(str(p), np.full((2000, 3000, 3), 128, dtype=np.uint8))
    img = classify.cargar_color(p)
    assert img is not None
    assert img.shape[1] == classify._ANCHO_NORM
    assert img.ndim == 3


def test_cargar_color_ilegible(tmp_path) -> None:
    p = tmp_path / "no_es_imagen.jpg"
    p.write_bytes(b"basura")
    assert classify.cargar_color(p) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_classify.py -v`
Expected: FAIL — `AttributeError: module 'src.classify' has no attribute 'cargar_color'` y `classify.faces` no existe.

- [ ] **Step 3: Write minimal implementation**

En `src/classify.py`, agregar `from src import faces` a los imports y borrar estas líneas:

```python
_FRONTAL = [cv2.CascadeClassifier(_HAAR + n) for n in ...]
_PERFIL = cv2.CascadeClassifier(_HAAR + "haarcascade_profileface.xml")
```

Conservar `_HAAR` y `_UPPER` (los usa `hay_persona`). Borrar la función `_solapan` completa.

Agregar junto a `cargar_normalizada`:

```python
def cargar_color(path: Path) -> "np.ndarray | None":
    """Imagen BGR normalizada a _ANCHO_NORM. YuNet necesita color, no gris."""
    import cv2
    img = cv2.imread(str(path))
    if img is None:
        return None
    alto, ancho = img.shape[:2]
    esc = _ANCHO_NORM / float(ancho)
    return cv2.resize(img, (_ANCHO_NORM, max(1, int(alto * esc))))
```

Reemplazar `contar_caras` completa:

```python
def contar_caras(img_color: "np.ndarray") -> int:
    """Cuántas caras usables tiene la imagen, según YuNet.

    `faces.detectar` ya filtra por score y tamaño mínimos, así que no hay
    distinción entre detecciones "totales" y "claras" como en la época de Haar.
    """
    return len(faces.detectar(img_color))
```

En `clasificar_foto`, cargar también la versión en color y ajustar a la firma nueva. Las dos variables `total` y `claras` se colapsan en una, `caras`:

```python
    gris = cargar_normalizada(path)
    color = cargar_color(path)
    if gris is None or color is None:
        db.update(cx, "photos", foto["id"], usable_meme=0, faces_count=0, nitidez=0.0)
        return "ilegible"

    nitidez = medir_nitidez(gris)
    caras = contar_caras(color)
```

Y en el resto de `clasificar_foto`, sustituir cada uso de `claras` por `caras` y cada uso de `total` por `caras`. Son cinco: la condición de `hay_persona` (`claras == 0`), la llamada a `decidir_usable(claras, ...)`, `faces_count=total`, `es_grupal=1 if claras >= 2 else 0`, y el mensaje de log (`f"{claras} cara(s)"`).

`decidir_usable` **no cambia de firma**: su primer parámetro se sigue llamando `caras_claras` y recibe el mismo número.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_classify.py -v`
Expected: PASS. Los tests preexistentes de `test_classify.py` que llamen `contar_caras(gris)` con imagen en gris deben actualizarse a color — revisarlos uno por uno; si alguno esperaba un conteo específico de Haar, recalibrar el número con YuNet en vez de forzar el resultado viejo.

Suite completa: `.venv/bin/python -m pytest`
Expected: solo los 2 fallos preexistentes.

- [ ] **Step 5: Commit**

```bash
git add src/classify.py tests/test_classify.py
git commit -m "refactor(classify): YuNet reemplaza los cascades de Haar"
```

---

## Notas de ejecución

**Orden:** las tareas 1→6 son secuenciales (cada una consume la anterior). La 7 depende de la 1. La 9 depende de la 6. La 12 depende de la 3 y conviene hacerla **antes de la 11**, para calibrar con un solo detector en juego. Las 10 y 11 van al final.

**Quién manda sobre `usable_meme`:** tanto `classify.clasificar_foto` como `banco.procesar_banda` escriben `faces_count`, `es_grupal` y `usable_meme`. El orden correcto es **classify primero** (detecta flyers y los manda a `events`, mide nitidez) y **banco después** — el banco tiene la última palabra porque es el que conoce el cupo. Correrlos al revés deja fotos marcadas usables que el cupo había sacado.

**Trabajo previo, fuera de este plan** (del spec): el `IG_ACCESS_TOKEN` sigue expirado desde el 1-ago y no se publica en Instagram; hay 32 cuentas pendientes en `data/nuevas_seguidas_pendientes.txt`; y 1,119 fotos recién bajadas sin clasificar, que son justamente el mejor material de prueba para la Task 11.

**Riesgo conocido:** SFace se entrenó mayoritariamente con caras frontales. En fotos de concierto (poca luz, contraluz, humo) va a fallar más. La degradación está prevista —esas fotos caen a "sin caras" y compiten por el cupo mínimo— pero si el banco de una banda queda vacío, es señal de que hay que bajar `FACE_DET_SCORE_MIN` para esa banda, no de que el sistema esté roto.
