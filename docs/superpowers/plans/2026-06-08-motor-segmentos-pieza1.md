# Motor de Segmentos (Pieza 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backbone que genera segmentos recurrentes en cadencia, los pre-filtra con un cerebro de engagement (banda + formato), los entrega a Telegram sin bloquear para aprobación de cualquier curador, y los publica en horario de alto tráfico, con cola dinámica que se reordena por desempeño.

**Architecture:** Núcleo PURO (scoring de engagement, timing, taxonomía, rerank) separado de la capa IO (DB/Telegram/IG). Etiquetado de formato alimenta el eje formato. Un registro declarativo de segmentos + dispatcher idempotente disparan generadores no-bloqueantes; un único daemon de aprobación posee el poller de Telegram. Arranque en frío explícito (reglas de Ricardo) que migra a data-driven al acumular métricas.

**Tech Stack:** Python 3 (`.venv/bin/python`), SQLite (`src/db.py`), DeepSeek (patrón `src/clasifica_generos.py`), python-telegram-bot, pytest.

**⚠️ Reglas de sesión:** Verificar `git config user.email` = `theilluminatiduck@gmail.com` antes de cualquier commit (regla de identidad). NO tocar `web/planner.py`-style del otro agente sin necesidad; coordinar. SQLite en WAL: `PRAGMA wal_checkpoint(TRUNCATE)` antes de copiar la DB. Comentarios en español. Núcleo puro = sin IO adentro.

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/format_tags.py` (nuevo) | Atributos de formato por post: derivar (integrante/tema), capturar (template), etiquetar (LLM patrón), join a métricas. |
| `src/engagement.py` (nuevo) | Núcleo PURO: `score_bandas`, `score_formatos`, `elegir_candidatos`, `rerank_cola` + estrategia cold-start. |
| `src/timing.py` (nuevo) | Núcleo PURO: `elegir_slot` con prioridad de fuentes (audiencia IG → desempeño → default). |
| `src/audience.py` (nuevo) | Fetcher read-only de `online_followers` → tabla `audience_activity`. |
| `src/segments.py` (nuevo) | Registro declarativo `Segment` + catálogo (los 4 vivos). |
| `src/segment_runner.py` (nuevo) | Dispatcher idempotente; CLI. |
| `src/approval.py` (nuevo) | Flujo asíncrono: encolar `pendiente_aprobacion` + enviar a Telegram con botones (sendMessage, sin poller). |
| `src/approval_daemon.py` (nuevo) | Único poller; callbacks ✓/✗ + flujo de memes; al aprobar → timing + agenda. |
| `config.py` (mod) | `FORMATO_PATRONES`, defaults de timing por segmento, umbrales cold-start. |
| `src/db.py` + `src/schema.sql` (mod) | Migraciones aditivas: columnas + tablas nuevas. |

Orden de construcción: **A** (datos/migraciones) → **B** (format_tags) → **C** (engagement puro) → **D** (timing+audience) → **E** (registro+dispatcher) → **F** (approval asíncrono+daemon) → **G** (migrar 4 segmentos) → **H** (rerank). Cada tarea es testeable sola.

---

### Task A: Migraciones de datos (columnas + tablas nuevas)

**Files:**
- Modify: `src/schema.sql` (append), `src/db.py` (`_MIGRATIONS`, `init_db`, `TABLES`, constante de estado)
- Test: `tests/test_motor_migraciones.py` (nuevo)

- [ ] **Step 1: Test (failing)**

`tests/test_motor_migraciones.py`:
```python
"""Migraciones del motor de segmentos: columnas y tablas nuevas, idempotentes."""
from __future__ import annotations

from src import db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_columnas_formato_en_content_queue(tmp_path) -> None:
    cx = _cx(tmp_path)
    cols = {r["name"] for r in cx.execute("PRAGMA table_info(content_queue)")}
    assert {"template", "formato_patron"} <= cols


def test_columna_aprobacion_y_propuesta(tmp_path) -> None:
    # La compuerta humana es una columna SEPARADA de status (status tiene un
    # CHECK fijo en la DB viva que NO se puede ampliar sin recrear la tabla).
    cx = _cx(tmp_path)
    qid = db.insert(cx, "content_queue", tipo="meme", aprobacion="pendiente",
                    caption="hola", imagen_url="http://x/y.jpg")
    f = db.get(cx, "content_queue", qid)
    assert f["aprobacion"] == "pendiente" and f["caption"] == "hola"


def test_tablas_audience_y_segment_runs(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.insert(cx, "audience_activity", account_id=1, dow=4, hora=19, valor=120)
    db.insert(cx, "segment_runs", segmento="agenda_semanal", account_id=1, ventana="2026-W23")
    assert db.rows(cx, "SELECT valor FROM audience_activity")[0]["valor"] == 120
    assert db.rows(cx, "SELECT segmento FROM segment_runs")[0]["segmento"] == "agenda_semanal"


def test_idempotente(tmp_path) -> None:
    cx = _cx(tmp_path)
    db.init_db(cx)  # 2a corrida no truena
    assert db.rows(cx, "SELECT count(*) c FROM audience_activity")[0]["c"] == 0
```

- [ ] **Step 2: Verificar que falla**

Run: `.venv/bin/python -m pytest tests/test_motor_migraciones.py -v`
Expected: FAIL (`no such column: template` / `no such table: audience_activity`).

- [ ] **Step 3: schema.sql — append**

Al final de `src/schema.sql`:
```sql
-- -----------------------------------------------------------------------------
-- audience_activity — "seguidores en línea" de IG (online_followers) por
-- día-de-semana y hora, por cuenta. Alimenta timing de alto tráfico.
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audience_activity (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL DEFAULT 1,
    dow         INTEGER NOT NULL,                 -- 0=lunes … 6=domingo
    hora        INTEGER NOT NULL,                 -- 0-23 (hora local de la cuenta)
    valor       INTEGER NOT NULL,                 -- seguidores online promedio
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (account_id, dow, hora)
);

-- -----------------------------------------------------------------------------
-- segment_runs — idempotencia del dispatcher: 1 corrida por segmento+ventana.
-- ventana = clave de periodo (ej. '2026-W23' semanal, '2026-06' mensual).
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS segment_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    segmento    TEXT NOT NULL,
    account_id  INTEGER NOT NULL DEFAULT 1,
    ventana     TEXT NOT NULL,
    corrido_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (segmento, account_id, ventana)
);
```

- [ ] **Step 4: db.py — migraciones, whitelist, init**

(a) En `_MIGRATIONS["content_queue"]` agregar (compuerta de aprobación como columna SEPARADA de status — verificado: la DB viva tiene `CHECK (status IN (...))` que rechazaría un status nuevo, y recrear la tabla con datos vivos + otros agentes es peligroso):
```python
        "template": "TEXT",
        "formato_patron": "TEXT",
        "aprobacion": "TEXT",            # NULL | 'pendiente' | 'aprobado' | 'rechazado'
        "caption": "TEXT",               # caption de la propuesta (hasta aprobarse)
        "imagen_url": "TEXT",            # URL Cloudinary de la propuesta (o JSON-list si carrusel)
```

(b) NO se toca `status` ni su CHECK. La compuerta humana vive en `aprobacion`. `status` sigue su ciclo normal (borrador→en_sheet→publicado). Un item recién encolado: `status='borrador', aprobacion='pendiente'`. Al aprobar: `aprobacion='aprobado', status='en_sheet'`. Al rechazar: `aprobacion='rechazado', status='descartado'`.

(c) Agregar `audience_activity` y `segment_runs` a la whitelist `TABLES` de db.py con sus columnas escribibles, y ampliar las columnas escribibles de `content_queue` con las nuevas (`template`, `formato_patron`, `aprobacion`, `caption`, `imagen_url`):
```python
    "audience_activity": {"account_id", "dow", "hora", "valor", "updated_at"},
    "segment_runs": {"segmento", "account_id", "ventana", "corrido_at"},
```

(d) `init_db`: `executescript` ya crea las tablas nuevas (están en schema.sql); el loop de `_MIGRATIONS` agrega las columnas. Nada más que añadir.

- [ ] **Step 5: Tests + suite**

Run: `.venv/bin/python -m pytest tests/test_motor_migraciones.py -v` → 4 PASS
Run: `.venv/bin/python -m pytest tests/ -q` → sin fallas nuevas

- [ ] **Step 6: Commit**

```bash
git config user.email   # debe ser theilluminatiduck@gmail.com
git add src/schema.sql src/db.py tests/test_motor_migraciones.py
git commit -m "motor: migraciones (template/formato_patron, audience_activity, segment_runs)"
```

---

### Task B: Etiquetado de formato (`src/format_tags.py`)

**Files:**
- Create: `src/format_tags.py`, `tests/test_format_tags.py`
- Modify: `config.py` (taxonomía `FORMATO_PATRONES`)

- [ ] **Step 1: config — taxonomía cerrada**

En `config.py`, junto a `GENEROS`:
```python
# Taxonomía CERRADA de patrones de formato de meme (eje formato del engagement).
# El LLM mapea cada caption a UNO de estos; lo que no mapea cae a 'otro'.
FORMATO_PATRONES = [
    "absurdo_domestico",     # integrante + objeto/situación cotidiana (los del microondas)
    "declaracion_personaje",  # "X asegura que…", declaración deadpan de un integrante
    "dato_falso",            # estadística inventada ("el 73% de los bajistas…")
    "comunicado",            # comunicado/reporte institucional satírico
    "otro",
]
```

- [ ] **Step 2: Test (failing)**

`tests/test_format_tags.py`:
```python
"""Etiquetado de formato: derivación de atributos y mapeo de taxonomía."""
from __future__ import annotations

from src import db, format_tags


def test_mapear_patron_contra_taxonomia() -> None:
    assert format_tags.mapear_patron("absurdo_domestico") == "absurdo_domestico"
    assert format_tags.mapear_patron("ABSURDO DOMÉSTICO") == "absurdo_domestico"
    assert format_tags.mapear_patron("categoria_inventada") == "otro"
    assert format_tags.mapear_patron(None) == "otro"


def test_atributos_derivados(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala")
    mid = db.insert(cx, "members", band_id=bid, nombre="Carlos", rol="guitarra")
    q1 = db.insert(cx, "content_queue", tipo="meme", band_id=bid, member_id=mid,
                   tema_semilla="microondas", template="clasica", formato_patron="absurdo_domestico")
    q2 = db.insert(cx, "content_queue", tipo="meme", band_id=bid)  # sin integrante ni tema
    attrs = {a["queue_id"]: a for a in format_tags.atributos_de_cola(cx)}
    assert attrs[q1]["tiene_integrante"] and attrs[q1]["tiene_tema"]
    assert attrs[q1]["template"] == "clasica" and attrs[q1]["patron"] == "absurdo_domestico"
    assert not attrs[q2]["tiene_integrante"] and not attrs[q2]["tiene_tema"]
```

- [ ] **Step 3: Verificar que falla** → ImportError.

- [ ] **Step 4: Implementar `src/format_tags.py`**

```python
"""Atributos de FORMATO por post para el eje formato del cerebro de engagement.

Tres orígenes: derivado (¿integrante?, ¿tema?), capturado (template) y semántico
(patrón vía LLM contra taxonomía cerrada config.FORMATO_PATRONES). El helper de
join cruza estos atributos con las métricas de ig_posts para que engagement.py
aprenda qué formato rinde. El etiquetado LLM copia el patrón de clasifica_generos.
"""
from __future__ import annotations

from typing import Any

import config
from src import db


def mapear_patron(valor: str | None) -> str:
    """Normaliza el patrón del LLM contra la taxonomía; 'otro' si no mapea."""
    if not valor:
        return "otro"
    v = valor.strip().lower().replace(" ", "_")
    # quita acentos básicos para el match
    for a, b in (("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u")):
        v = v.replace(a, b)
    return v if v in config.FORMATO_PATRONES else "otro"


def atributos_de_cola(cx) -> list[dict[str, Any]]:
    """Atributos de formato de cada item de content_queue (para inspección/test)."""
    filas = db.rows(cx, """
        SELECT id AS queue_id, member_id, tema_semilla, template, formato_patron
          FROM content_queue
    """)
    return [{
        "queue_id": f["queue_id"],
        "tiene_integrante": f["member_id"] is not None,
        "tiene_tema": bool((f["tema_semilla"] or "").strip()),
        "template": f["template"],
        "patron": f["formato_patron"] or "otro",
    } for f in filas]


def atributos_por_post(cx) -> list[dict[str, Any]]:
    """Cruza atributos de formato con métricas de ig_posts (vía queue_id).

    PURO sobre la DB de lectura: devuelve filas que engagement.score_formatos
    consume para aprender qué formato rinde. Solo posts del bot (con queue_id).
    """
    return db.rows(cx, """
        SELECT p.media_id, p.reach, p.shares, p.saved, p.likes, p.comments,
               (q.member_id IS NOT NULL)            AS tiene_integrante,
               (TRIM(COALESCE(q.tema_semilla,'')) != '') AS tiene_tema,
               q.template, COALESCE(q.formato_patron,'otro') AS patron
          FROM ig_posts p JOIN content_queue q ON q.id = p.queue_id
         WHERE p.reach IS NOT NULL
    """)
```

(El etiquetado LLM real — `etiquetar_cola(cx, handles)` con DeepSeek temp=0, copia de `clasifica_generos._llm_clasificar` — se agrega en Step 6; el test del LLM se hace con doble, sin red.)

- [ ] **Step 5: Tests + commit**

Run: `.venv/bin/python -m pytest tests/test_format_tags.py -v` → PASS
```bash
git add src/format_tags.py tests/test_format_tags.py config.py
git commit -m "motor: format_tags (atributos derivados + taxonomia de patron)"
```

- [ ] **Step 6: Etiquetador LLM (TDD con doble)**

Test que inyecta un cliente LLM falso y verifica que `etiquetar_post(caption, llm=fake)` mapea por taxonomía:
```python
def test_etiquetar_post_mapea(monkeypatch) -> None:
    from src import format_tags
    fake = lambda prompt: '{"patron": "absurdo doméstico"}'
    assert format_tags.etiquetar_post("El baterista usó el microondas", _llm=fake) == "absurdo_domestico"
    fake2 = lambda prompt: '{"patron": "no_existe"}'
    assert format_tags.etiquetar_post("x", _llm=fake2) == "otro"
```
Implementar `etiquetar_post(caption, *, _llm=None)`: si `_llm` None usa DeepSeek (patrón clasifica_generos: temp=0, `response_format=json_object`, prompt con `", ".join(config.FORMATO_PATRONES)`), parsea con `parse_events.extraer_json`, `return mapear_patron(d.get("patron"))`. Más `etiquetar_cola(cx)` que recorre items sin `formato_patron` y los actualiza. Commit.

---

### Task C: Cerebro de engagement — núcleo PURO (`src/engagement.py`)

**Files:**
- Create: `src/engagement.py`, `tests/test_engagement.py`
- Modify: `config.py` (umbrales + pesos cold-start)

- [ ] **Step 1: config — umbrales y pesos**

```python
# Cerebro de engagement (motor de segmentos) ---------------------------------
ENGAGEMENT_MIN_POSTS = 2          # < esto por banda → cold-start (prioridad+followers)
SHARES_PESO = 3.0                 # shares = crecimiento (reshare regala audiencia)
ANTIREPEAT_DIAS = 14             # penaliza bandas publicadas en los últimos N días
# Pesos cold-start del eje FORMATO (reglas ya probadas por Ricardo).
FORMATO_PESOS_COLDSTART = {
    "absurdo_domestico": 1.5, "declaracion_personaje": 1.2,
    "dato_falso": 1.0, "comunicado": 0.9, "otro": 1.0,
}
```

- [ ] **Step 2: Test (failing)** — `tests/test_engagement.py`:

```python
"""Cerebro de engagement: scoring puro de banda y formato + cold-start."""
from __future__ import annotations

from src import engagement


def test_score_formatos_cold_start_usa_reglas() -> None:
    # Sin datos suficientes → pesos de Ricardo (absurdo_domestico manda).
    pesos = engagement.score_formatos([], min_posts=2)
    assert pesos["absurdo_domestico"] > pesos["comunicado"]


def test_score_formatos_aprende_de_datos() -> None:
    # absurdo_domestico con reach/shares altos sube por encima de su peso base.
    posts = [
        {"patron": "absurdo_domestico", "reach": 1368, "shares": 30, "saved": 5},
        {"patron": "absurdo_domestico", "reach": 1140, "shares": 10, "saved": 2},
        {"patron": "comunicado", "reach": 200, "shares": 0, "saved": 0},
        {"patron": "comunicado", "reach": 180, "shares": 1, "saved": 0},
    ]
    pesos = engagement.score_formatos(posts, min_posts=2)
    assert pesos["absurdo_domestico"] > pesos["comunicado"] * 2


def test_score_bandas_anti_repeticion() -> None:
    # Misma señal base, pero una publicó ayer → debe quedar debajo.
    bandas = [
        {"band_id": 1, "er": 0.1, "shares": 5, "prioridad": 3, "followers_ig": 1000,
         "n_posts": 3, "dias_desde_ultimo": 1},
        {"band_id": 2, "er": 0.1, "shares": 5, "prioridad": 3, "followers_ig": 1000,
         "n_posts": 3, "dias_desde_ultimo": 60},
    ]
    orden = [b["band_id"] for b in engagement.score_bandas(bandas, min_posts=2)]
    assert orden == [2, 1]


def test_score_bandas_cold_start_por_followers() -> None:
    bandas = [
        {"band_id": 1, "er": None, "shares": 0, "prioridad": 3, "followers_ig": 500,
         "n_posts": 0, "dias_desde_ultimo": None},
        {"band_id": 2, "er": None, "shares": 0, "prioridad": 3, "followers_ig": 5000,
         "n_posts": 0, "dias_desde_ultimo": None},
    ]
    orden = [b["band_id"] for b in engagement.score_bandas(bandas, min_posts=2)]
    assert orden == [2, 1]  # sin datos → más followers primero
```

- [ ] **Step 3: Verificar que falla** → ImportError.

- [ ] **Step 4: Implementar `src/engagement.py`** (PURO; las queries van en funciones `_cargar_*` separadas, no probadas aquí):

```python
"""Cerebro de engagement (núcleo PURO). Decide QUÉ generar y reordena la cola.

Dos ejes:
  - BANDA: a quién conviene (ER ya pondera saved×3 en ig_insights) + shares
    (crecimiento) + anti-repetición (repartir, no siempre las mismas). Cold-start
    por (prioridad, followers_ig) cuando la banda tiene < min_posts.
  - FORMATO: qué conviene. Aprende de reach+shares por patrón; cold-start con las
    reglas ya probadas por Ricardo (config.FORMATO_PESOS_COLDSTART).

Las funciones de scoring son PURAS (reciben listas de dicts, devuelven orden/pesos)
para testearse sin red. La capa IO (_cargar_bandas, _cargar_formatos) hace queries.
"""
from __future__ import annotations

from typing import Any

import config


def score_formatos(posts: list[dict[str, Any]], *, min_posts: int) -> dict[str, float]:
    """Peso por patrón de formato. Mezcla reglas (cold-start) con desempeño real.

    Desempeño de un patrón = promedio de (reach + SHARES_PESO*shares) de sus posts,
    normalizado. Si un patrón tiene < min_posts ejemplos, conserva su peso de regla.
    """
    base = dict(config.FORMATO_PESOS_COLDSTART)
    porp: dict[str, list[float]] = {}
    for p in posts:
        val = (p.get("reach") or 0) + config.SHARES_PESO * (p.get("shares") or 0)
        porp.setdefault(p["patron"], []).append(val)
    aprendidos = {k: sum(v) / len(v) for k, v in porp.items() if len(v) >= min_posts}
    if not aprendidos:
        return base
    techo = max(aprendidos.values()) or 1.0
    out = dict(base)
    for k, v in aprendidos.items():  # data manda donde hay; escala 0.5–2.0
        out[k] = 0.5 + 1.5 * (v / techo)
    return out


def _clave_banda(b: dict[str, Any], *, min_posts: int) -> tuple:
    """Clave de orden DESC: con datos usa engagement; sin datos, followers."""
    tiene_datos = (b.get("n_posts") or 0) >= min_posts and b.get("er") is not None
    if tiene_datos:
        score = b["er"] + config.SHARES_PESO * 0.001 * (b.get("shares") or 0)
    else:
        score = (b.get("followers_ig") or 0) / 1e6  # cold-start, escala chica
    # anti-repetición: penaliza si publicó hace poco
    dd = b.get("dias_desde_ultimo")
    pen = 0.0 if dd is None or dd >= config.ANTIREPEAT_DIAS else \
        (config.ANTIREPEAT_DIAS - dd) / config.ANTIREPEAT_DIAS
    return (-(score - pen), b.get("prioridad") or 3)


def score_bandas(bandas: list[dict[str, Any]], *, min_posts: int) -> list[dict[str, Any]]:
    """Ordena bandas por conveniencia (desc). PURO."""
    return sorted(bandas, key=lambda b: _clave_banda(b, min_posts=min_posts))
```

- [ ] **Step 5: Tests + commit**

Run: `.venv/bin/python -m pytest tests/test_engagement.py -v` → 4 PASS
```bash
git add src/engagement.py tests/test_engagement.py config.py
git commit -m "motor: cerebro de engagement (scoring puro banda+formato, cold-start)"
```

- [ ] **Step 6: Capa IO + `elegir_candidatos` (TDD con DB tmp)**

Agregar `_cargar_bandas(cx, account_id)` (reusa/extiende `ig_insights.band_stats`, agrega `dias_desde_ultimo` y `shares` por banda), `_cargar_formatos(cx)` = `format_tags.atributos_por_post(cx)`, y `elegir_candidatos(cx, n, *, account_id)` que cruza ambos ejes y elige fotos no usadas de las bandas top con el patrón de mayor peso disponible. Test con DB tmp poblada. Commit.

---

### Task D: Timing de alto tráfico (`src/timing.py` + `src/audience.py`)

**Files:**
- Create: `src/timing.py`, `src/audience.py`, `tests/test_timing.py`
- Modify: `config.py` (defaults por segmento)

- [ ] **Step 1: config — defaults de alto tráfico (cold-start)**

```python
# Slot de alto tráfico por defecto por segmento (cold-start: hasta que IG
# online_followers tenga datos). (dow 0=lun..6=dom, hora 24h local).
TIMING_DEFAULTS = {
    "agenda_semanal":   (3, 19),   # jueves 7pm: arranque de finde
    "agenda_mensual":   (0, 19),   # lunes 7pm
    "releases_semanal": (4, 18),   # viernes 6pm: día de estrenos
    "releases_mensual": (4, 18),
    "meme":             (2, 20),   # miércoles 8pm
}
TIMING_DEFAULT_FALLBACK = (3, 19)
```

- [ ] **Step 2: Test (failing)** — `tests/test_timing.py`:

```python
"""Timing de alto tráfico: prioridad de fuentes y arranque en frío."""
from __future__ import annotations

from datetime import datetime

from src import timing


def test_default_cuando_no_hay_audiencia() -> None:
    # Sin audiencia → usa TIMING_DEFAULTS (agenda_semanal = jueves 19h).
    ahora = datetime(2026, 6, 8, 10, 0)  # lunes
    slot = timing.elegir_slot("agenda_semanal", ahora, audiencia=[])
    assert slot.weekday() == 3 and slot.hour == 19 and slot > ahora


def test_usa_audiencia_si_existe() -> None:
    # Audiencia con pico claro sábado 21h → gana al default.
    aud = [{"dow": 5, "hora": 21, "valor": 900}, {"dow": 1, "hora": 9, "valor": 10}]
    slot = timing.elegir_slot("meme", datetime(2026, 6, 8, 10, 0), audiencia=aud)
    assert slot.weekday() == 5 and slot.hour == 21


def test_segmento_desconocido_usa_fallback() -> None:
    slot = timing.elegir_slot("formato_raro", datetime(2026, 6, 8, 10, 0), audiencia=[])
    assert slot.weekday() == 3 and slot.hour == 19
```

- [ ] **Step 3: Verificar que falla** → ImportError.

- [ ] **Step 4: Implementar `src/timing.py`** (PURO):

```python
"""Selector de slot de alto tráfico (núcleo PURO).

Prioridad de fuente: (1) audiencia de IG (online_followers) si hay datos →
(2) [futuro] desempeño por hora de tus posts → (3) default por segmento.
Hoy IG devuelve online_followers VACÍO (<100 seguidores), así que arranca en (3);
el módulo ya consume (1) en cuanto audience.py la pueble.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import config


def _proximo(ahora: datetime, dow: int, hora: int) -> datetime:
    """Próximo datetime futuro que caiga en ese día-de-semana y hora."""
    cand = ahora.replace(hour=hora, minute=0, second=0, microsecond=0)
    dias = (dow - ahora.weekday()) % 7
    cand += timedelta(days=dias)
    if cand <= ahora:
        cand += timedelta(days=7)
    return cand


def elegir_slot(segmento: str, ahora: datetime, *,
                audiencia: list[dict[str, Any]] | None = None) -> datetime:
    """Próximo slot de alto tráfico para el segmento. PURO."""
    if audiencia:
        pico = max(audiencia, key=lambda a: a["valor"])
        return _proximo(ahora, pico["dow"], pico["hora"])
    dow, hora = config.TIMING_DEFAULTS.get(segmento, config.TIMING_DEFAULT_FALLBACK)
    return _proximo(ahora, dow, hora)
```

- [ ] **Step 5: Tests + commit**

Run: `.venv/bin/python -m pytest tests/test_timing.py -v` → 3 PASS
```bash
git add src/timing.py tests/test_timing.py config.py
git commit -m "motor: timing de alto trafico (default + audiencia, puro)"
```

- [ ] **Step 6: `src/audience.py` (fetcher read-only)**

`fetch_online_followers(account_id)`: GET `/{uid}/insights?metric=online_followers&period=lifetime` (creds vía `config.account_creds` por cuenta), parsea `values[].value` (dict hora→valor), agrega por dow+hora, upsert a `audience_activity`. Si IG devuelve vacío (caso actual), no escribe nada y loguea. `cargar(cx, account_id)` lee la tabla para pasársela a `timing.elegir_slot`. Test del PARSEO con payload fijo (sin red). Commit.

---

### Task E: Registro de segmentos + dispatcher

**Files:**
- Create: `src/segments.py`, `src/segment_runner.py`, `tests/test_segment_runner.py`

- [ ] **Step 1: Test (failing)** — `tests/test_segment_runner.py`:

```python
"""Dispatcher: dispara segmentos que tocan hoy, idempotente por ventana."""
from __future__ import annotations

from datetime import datetime

from src import db, segment_runner, segments


def test_ventana_semanal_y_mensual() -> None:
    assert segments.ventana_de("agenda_semanal", datetime(2026, 6, 8)) == "2026-W24"
    assert segments.ventana_de("releases_mensual", datetime(2026, 6, 8)) == "2026-06"


def test_dispatch_idempotente(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    corridos = []
    seg = segments.Segment("demo", "Demo", lambda cx, acc: corridos.append(1),
                           cadencia={"tipo": "semanal", "dow": 6}, ventana_trafico="meme")
    hoy = datetime(2026, 6, 14)  # domingo (dow 6) → toca
    segment_runner.dispatch(cx, [seg], ahora=hoy, account_id=1)
    segment_runner.dispatch(cx, [seg], ahora=hoy, account_id=1)  # 2a vez NO repite
    assert corridos == [1]


def test_no_dispara_si_no_toca_hoy(tmp_path) -> None:
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    corridos = []
    seg = segments.Segment("demo", "Demo", lambda cx, acc: corridos.append(1),
                           cadencia={"tipo": "semanal", "dow": 6}, ventana_trafico="meme")
    segment_runner.dispatch(cx, [seg], ahora=datetime(2026, 6, 10), account_id=1)  # miércoles
    assert corridos == []
```

- [ ] **Step 2: Verificar que falla** → ImportError.

- [ ] **Step 3: Implementar `src/segments.py`**:

```python
"""Registro declarativo de segmentos de contenido recurrente.

Cada Segment ata una CLAVE a su generador, su cadencia y su ventana de tráfico.
Agregar un formato nuevo (Pieza 2) = escribir el generador + registrar aquí.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable


@dataclass(frozen=True)
class Segment:
    clave: str
    nombre: str
    generador: Callable[[Any, int], None]   # (cx, account_id) -> encola propuestas
    cadencia: dict                           # {"tipo": "semanal"|"mensual"|"diario", "dow"?, "dia_mes"?}
    ventana_trafico: str                     # clave en config.TIMING_DEFAULTS
    activo: bool = True


def ventana_de(_clave: str, ahora: datetime) -> str:
    """Clave de periodo para idempotencia (no depende del segmento, solo del tipo)."""
    # se resuelve por cadencia en toca_hoy; aquí formato estable por fecha
    iso = ahora.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"  # semanal por defecto


def ventana_mensual(ahora: datetime) -> str:
    return f"{ahora.year}-{ahora.month:02d}"


def toca_hoy(seg: Segment, ahora: datetime) -> bool:
    c = seg.cadencia
    if c["tipo"] == "diario":
        return True
    if c["tipo"] == "semanal":
        return ahora.weekday() == c["dow"]
    if c["tipo"] == "mensual":
        return ahora.day == c.get("dia_mes", 1)
    return False


def ventana_actual(seg: Segment, ahora: datetime) -> str:
    return ventana_mensual(ahora) if seg.cadencia["tipo"] == "mensual" else ventana_de(seg.clave, ahora)
```

(Ajustar `test_ventana_de` para usar `ventana_actual` o exponer `ventana_de` que delegue según tipo — mantener UNA firma; el test arriba llama `ventana_de(clave, fecha)` así que `ventana_de` debe resolver semanal vs mensual por la clave: implementar `ventana_de` mirando si la clave termina en `_mensual`.)

Corrección de `ventana_de` para satisfacer el test tal cual:
```python
def ventana_de(clave: str, ahora: datetime) -> str:
    if clave.endswith("_mensual"):
        return f"{ahora.year}-{ahora.month:02d}"
    iso = ahora.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
```

- [ ] **Step 4: Implementar `src/segment_runner.py`**:

```python
"""Dispatcher idempotente del registro de segmentos.

Dispara los segmentos cuya cadencia toca hoy y que NO se han corrido en su
ventana actual (segment_runs). Un generador que truena no tumba a los demás.
CLI:  python -m src.segment_runner [--cuenta gdlscene] [--force]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import config
from src import db, segments
from src.segments import Segment


def _ya_corrio(cx, seg: Segment, ventana: str, account_id: int) -> bool:
    return bool(db.rows(cx,
        "SELECT 1 FROM segment_runs WHERE segmento=? AND account_id=? AND ventana=?",
        (seg.clave, account_id, ventana)))


def dispatch(cx, registro: list[Segment], *, ahora: datetime | None = None,
             account_id: int = 1, force: bool = False) -> list[str]:
    ahora = ahora or datetime.now()
    corridos = []
    for seg in registro:
        if not seg.activo or not segments.toca_hoy(seg, ahora):
            continue
        ventana = segments.ventana_de(seg.clave, ahora)
        if not force and _ya_corrio(cx, seg, ventana, account_id):
            continue
        try:
            seg.generador(cx, account_id)
            db.insert(cx, "segment_runs", segmento=seg.clave,
                      account_id=account_id, ventana=ventana)
            corridos.append(seg.clave)
        except Exception as exc:  # un segmento roto no tumba la tanda
            print(f"⚠️ segmento {seg.clave} falló: {exc}", file=sys.stderr)
    return corridos


def main() -> int:
    from src.catalogo import REGISTRO   # catálogo real (Task G)
    parser = argparse.ArgumentParser(description="Dispatcher de segmentos")
    parser.add_argument("--cuenta", default="gdlscene")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    cx = db.connect()
    try:
        db.init_db(cx)
        acc = db.get_account(cx, args.cuenta)
        account_id = acc["id"] if acc else 1
        hechos = dispatch(cx, REGISTRO, account_id=account_id, force=args.force)
        print(f"Segmentos disparados: {hechos or 'ninguno (no tocaba o ya corrieron)'}")
    finally:
        cx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Tests + commit**

Run: `.venv/bin/python -m pytest tests/test_segment_runner.py -v` → 3 PASS
```bash
git add src/segments.py src/segment_runner.py tests/test_segment_runner.py
git commit -m "motor: registro de segmentos + dispatcher idempotente"
```

---

### Task F: Flujo de aprobación asíncrono + daemon

**Files:**
- Create: `src/approval.py`, `src/approval_daemon.py`, `tests/test_approval.py`
- Modify: `src/telegram_bot.py` (extraer helper de botones reusable, sin romper firmas existentes)

- [ ] **Step 1: Test del flujo de estado (failing)** — `tests/test_approval.py`:

```python
"""Aprobación asíncrona: encolar pendiente y resolver (aprobar/rechazar)."""
from __future__ import annotations

from datetime import datetime

from src import approval, db


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_encolar_pendiente(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    qid = approval.encolar_pendiente(cx, tipo="meme", band_id=bid,
                                     caption="hola", imagen_url="http://x/y.jpg")
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "pendiente" and fila["status"] == "borrador"
    assert fila["caption"] == "hola" and fila["imagen_url"] == "http://x/y.jpg"


def test_aprobar_agenda_slot(tmp_path, monkeypatch) -> None:
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="x", imagen_url="u")
    slot = approval.aprobar(cx, qid, ahora=datetime(2026, 6, 8, 10, 0),
                            ventana_trafico="meme", audiencia=[],
                            _escribir_sheet=lambda **k: 99)  # doble: no toca Sheet real
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "aprobado" and fila["status"] == "en_sheet"
    assert fila["sheet_row_id"] == "99"
    assert slot.hour == 20  # default meme = miércoles 20h


def test_rechazar(tmp_path) -> None:
    cx = _cx(tmp_path)
    qid = approval.encolar_pendiente(cx, tipo="meme", caption="x", imagen_url="u")
    approval.rechazar(cx, qid)
    fila = db.get(cx, "content_queue", qid)
    assert fila["aprobacion"] == "rechazado" and fila["status"] == "descartado"
```

- [ ] **Step 2: Verificar que falla** → ImportError.

- [ ] **Step 3: Implementar `src/approval.py`**:

```python
"""Flujo de aprobación ASÍNCRONO (no bloqueante).

Los generadores ENCOLAN propuestas (status pendiente_aprobacion) y mandan a
Telegram con botones vía sendMessage directo — sin poller. El daemon (único
poller) resuelve: aprobar → elige slot de alto tráfico, escribe el Sheet
approved y marca en_sheet; rechazar → descartado. publish.py publica luego.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from src import db, timing


def encolar_pendiente(cx, *, tipo: str, caption: str, imagen_url: str,
                      band_id: int | None = None, member_id: int | None = None,
                      photo_id: int | None = None, event_id: int | None = None,
                      template: str | None = None, formato_patron: str | None = None,
                      tema_semilla: str | None = None, account_id: int = 1) -> int:
    """Crea el item pendiente de aprobación. Devuelve queue_id.

    status sigue su ciclo normal ('borrador'); la compuerta humana vive en la
    columna separada 'aprobacion' (la DB tiene CHECK fijo en status).
    """
    return db.insert(cx, "content_queue", tipo=tipo, status="borrador",
                     aprobacion="pendiente", caption=caption, imagen_url=imagen_url,
                     band_id=band_id, member_id=member_id, photo_id=photo_id,
                     event_id=event_id, template=template, formato_patron=formato_patron,
                     tema_semilla=tema_semilla, account_id=account_id)


def aprobar(cx, queue_id: int, *, ahora: datetime | None = None,
            ventana_trafico: str = "meme", audiencia: list[dict[str, Any]] | None = None,
            _escribir_sheet: Callable[..., int] | None = None) -> datetime:
    """Aprueba: elige slot de alto tráfico, escribe Sheet approved, marca en_sheet."""
    ahora = ahora or datetime.now()
    fila = db.get(cx, "content_queue", queue_id)
    slot = timing.elegir_slot(ventana_trafico, ahora, audiencia=audiencia or [])
    escribir = _escribir_sheet or _sheet_real
    sheet_id = escribir(caption=fila.get("caption"),
                        imagen=fila.get("imagen_url"),
                        scheduled=slot.isoformat())
    db.update(cx, "content_queue", queue_id, aprobacion="aprobado", status="en_sheet",
              sheet_row_id=str(sheet_id), scheduled_datetime=slot.isoformat())
    return slot


def rechazar(cx, queue_id: int) -> None:
    db.update(cx, "content_queue", queue_id, aprobacion="rechazado", status="descartado")


def _sheet_real(*, caption, imagen, scheduled) -> int:
    """Escribe la fila approved en el Sheet (igual que generate_agenda)."""
    from src import sheets
    return sheets.append_row(banda="@gdlscene", caption_generado=caption,
                             caption_final=caption, imagen_compuesta_url=imagen,
                             status=sheets.STATUS_APPROVED, scheduled_datetime=scheduled)
```

(Resuelto en pre-vuelo: las columnas `caption`/`imagen_url`/`aprobacion` se agregan en Task A; el Sheet es la fuente al PUBLICAR, content_queue es el staging de la propuesta PENDIENTE. `_sheet_real` usa la firma real de `sheets.append_row` — verificar sus kwargs exactos contra `src/sheets.py` al implementar.)

- [ ] **Step 4: Tests + commit**

Run: `.venv/bin/python -m pytest tests/test_approval.py -v` → 3 PASS
```bash
git add src/approval.py tests/test_approval.py
git commit -m "motor: flujo de aprobacion asincrono (encolar/aprobar/rechazar + slot)"
```

- [ ] **Step 5: `src/approval_daemon.py` (único poller)**

Proceso persistente con python-telegram-bot: `CallbackQueryHandler` para botones `aprobar:{qid}` / `rechazar:{qid}` → llama `approval.aprobar`/`rechazar` (cargando audiencia con `audience.cargar`). Pliega el `MessageHandler` del flujo de memes de `bot.py` (mover su lógica aquí o importarla) para que haya UN solo poller. Guardia: no arrancar si ya hay otro daemon (pgrep/lock). `run_polling()`. Helper `approval.enviar_a_telegram(caption, imagen_url, queue_id)` que hace `sendMessage` con los 2 botones (sin poller) — lo usan los generadores. Verificación manual documentada (no test automatizado del poller). Commit.

---

### Task G: Migrar los 4 segmentos vivos + catálogo

**Files:**
- Create: `src/catalogo.py`, `tests/test_catalogo.py`
- Modify: `src/generate_agenda.py` (extraer generador no-bloqueante reusable)

- [ ] **Step 1: Test (failing)** — el catálogo expone los 4 segmentos con cadencia correcta:

```python
"""Catálogo: los 4 segmentos vivos registrados con su cadencia/ventana."""
from src.catalogo import REGISTRO

def test_catalogo_tiene_los_cuatro() -> None:
    claves = {s.clave for s in REGISTRO}
    assert {"agenda_semanal", "agenda_mensual",
            "releases_semanal", "releases_mensual"} <= claves

def test_cadencias() -> None:
    por = {s.clave: s for s in REGISTRO}
    assert por["agenda_semanal"].cadencia["tipo"] == "semanal"
    assert por["releases_mensual"].cadencia["tipo"] == "mensual"
    assert por["agenda_semanal"].ventana_trafico == "agenda_semanal"
```

- [ ] **Step 2: Verificar que falla** → ImportError.

- [ ] **Step 3: Refactor en `generate_agenda.py`** — extraer un generador no-bloqueante:

Crear `generar_segmento_agenda(cx, account_id, *, periodo, modo)` que arma el carrusel (reusa `build_agenda_carousel`/`build_releases_carousel`), sube a Cloudinary/host, y en vez de `request_carousel_approval` (bloqueante) llama `approval.encolar_pendiente` + `approval.enviar_a_telegram`. NO tocar `main()` existente (queda como vía manual); el generador nuevo es aparte.

- [ ] **Step 4: Implementar `src/catalogo.py`**:

```python
"""Catálogo real de segmentos registrados en el motor (lo lee el dispatcher)."""
from __future__ import annotations

from functools import partial

from src.segments import Segment
from src.generate_agenda import generar_segmento_agenda

REGISTRO = [
    Segment("agenda_semanal", "Agenda — esta semana",
            partial(generar_segmento_agenda, periodo="semanal", modo="shows"),
            cadencia={"tipo": "semanal", "dow": 1}, ventana_trafico="agenda_semanal"),
    Segment("agenda_mensual", "Agenda — este mes",
            partial(generar_segmento_agenda, periodo="mensual", modo="shows"),
            cadencia={"tipo": "mensual", "dia_mes": 1}, ventana_trafico="agenda_mensual"),
    Segment("releases_semanal", "Música nueva — semana",
            partial(generar_segmento_agenda, periodo="semanal", modo="releases"),
            cadencia={"tipo": "semanal", "dow": 4}, ventana_trafico="releases_semanal"),
    Segment("releases_mensual", "Música nueva — mes",
            partial(generar_segmento_agenda, periodo="mensual", modo="releases"),
            cadencia={"tipo": "mensual", "dia_mes": 1}, ventana_trafico="releases_mensual"),
]
```

(Ajustar la firma de `generar_segmento_agenda` para que `partial(..., periodo=, modo=)` deje `(cx, account_id)` como posicionales — coincide con el contrato `Callable[[Any,int],None]` de Segment.)

- [ ] **Step 5: Tests + commit**

Run: `.venv/bin/python -m pytest tests/test_catalogo.py -q` → PASS
Run: `.venv/bin/python -m pytest tests/ -q` → sin fallas nuevas
```bash
git add src/catalogo.py src/generate_agenda.py tests/test_catalogo.py
git commit -m "motor: catalogo con los 4 segmentos vivos (generadores no-bloqueantes)"
```

---

### Task H: Re-ranker dinámico de la cola

**Files:**
- Modify: `src/engagement.py` (`rerank_cola`), `tests/test_engagement.py`
- Create: `src/rerank_runner.py` (cron)

- [ ] **Step 1: Test (failing)** — agregar a `tests/test_engagement.py`:

```python
def test_rerank_reordena_futuros_por_score() -> None:
    from src import engagement
    # dos items futuros; el de patrón ganador debe quedar en el slot más cercano
    items = [
        {"queue_id": 1, "patron": "comunicado", "band_score": 0.1, "scheduled": "2026-06-10T20:00"},
        {"queue_id": 2, "patron": "absurdo_domestico", "band_score": 0.1, "scheduled": "2026-06-11T20:00"},
    ]
    pesos = {"absurdo_domestico": 2.0, "comunicado": 0.5}
    nuevo = engagement.rerank_cola(items, pesos_formato=pesos)
    # el ganador (2) toma el slot más temprano (10), el otro el 11
    asignado = {r["queue_id"]: r["scheduled"] for r in nuevo}
    assert asignado[2] == "2026-06-10T20:00" and asignado[1] == "2026-06-11T20:00"
```

- [ ] **Step 2: Verificar que falla** → AttributeError.

- [ ] **Step 3: Implementar `rerank_cola` en `engagement.py`** (PURO):

```python
def rerank_cola(items: list[dict[str, Any]], *, pesos_formato: dict[str, float]) -> list[dict[str, Any]]:
    """Reasigna los slots futuros a los items mejor puntuados (formato×banda).

    Los slots (scheduled) se mantienen como conjunto; se reparten al orden nuevo:
    el item de mayor score toma el slot más temprano. PURO.
    """
    slots = sorted(i["scheduled"] for i in items)
    rank = sorted(items, key=lambda i: -(pesos_formato.get(i["patron"], 1.0) * (i.get("band_score") or 0.0)
                                         + pesos_formato.get(i["patron"], 1.0)))
    return [{**it, "scheduled": slot} for it, slot in zip(rank, slots)]
```

- [ ] **Step 4: Tests + commit**

Run: `.venv/bin/python -m pytest tests/test_engagement.py -v` → PASS
```bash
git add src/engagement.py tests/test_engagement.py
git commit -m "motor: rerank dinamico de cola por desempeno (puro)"
```

- [ ] **Step 5: `src/rerank_runner.py` (cron)**

Lee items futuros no publicados de content_queue (status en_sheet, scheduled futuro), carga pesos vía `engagement._cargar_formatos`/`score_formatos` + band_score, llama `rerank_cola`, actualiza `scheduled_datetime` en DB y en el Sheet (vía sheets.update_row). CLI `python -m src.rerank_runner [--cuenta]`. Verificación manual con la DB viva (dry-run primero). Commit.

---

## Notas de integración (post-plan, NO en este plan)
- **Crons**: agregar al sistema (launchd ahora, cron-in-container después) `segment_runner` diario (~09:00) y `rerank_runner` semanal. El `approval_daemon` corre persistente (reemplaza el patrón de correr generate_* a mano).
- **Pieza 2** (formatos nuevos): cada uno = generador + entrada en `catalogo.REGISTRO`. Ya no toca infraestructura.
- **Multi-cuenta**: las firmas llevan `account_id`; el cableado de creds por cuenta es Fase B (otro spec).

## Self-review (hecho)
- Cobertura del spec: etiquetado formato (B), cerebro 2 ejes (C), timing+audiencia (D), registro+dispatcher (E), aprobación asíncrona+daemon (F), migración 4 segmentos (G), rerank dinámico (H), migraciones (A). ✓
- Riesgos señalados inline (no placeholders ocultos): el modelo exacto de columnas caption/imagen en content_queue debe verificarse contra la DB viva ANTES de Task F (la fuente del caption hoy es el Sheet, no content_queue) — la tarea lo dice explícito. El CHECK de status en Task A igual. Estas son verificaciones reales, no TODOs.
- Consistencia de tipos: `Segment` (clave/generador/cadencia/ventana_trafico), `elegir_slot(segmento, ahora, *, audiencia)`, `score_formatos(posts, *, min_posts)`, `score_bandas(bandas, *, min_posts)` usados consistentes entre tareas. ✓
