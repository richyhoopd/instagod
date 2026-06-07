# Carrusel Música Nueva v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carrusel IG de releases con portadas locales (inmunes al filtro DNS), grid 2×2 (4/slide), portada con collage+lineup, CTA, y caption con tags de todas las bandas.

**Architecture:** `src/covers.py` baja/cachea portadas (requests → fallback DoH+IP) a `data/covers/`. `generate_agenda.build_releases_carousel()` (análogo a `build_agenda_carousel`) renderiza portada + N grids + CTA con `compose.render_card` y arma el caption con tags. Modo shows intacto.

**Tech Stack:** Python (`.venv/bin/python`), requests/urllib3/certifi, Jinja2 + Playwright (motor existente), pytest.

**⚠️ Reglas de sesión:** NO `git commit`/`git add`. NO tocar `src/planner.py` ni `web/`. Comentarios en español. NO correr `src/check_releases.py` ni `enrich` (API rate-limited); descargar portadas individuales (CDN) SÍ está bien.

---

### Task A: `src/covers.py` — caché local de portadas con fallback DoH

**Files:**
- Create: `src/covers.py`
- Test: `tests/test_covers.py` (nuevo)

- [ ] **Step 1: Test failing primero**

`tests/test_covers.py`:

```python
"""Caché de portadas: ruta estable, hit sin red, descarga con fallback."""
from __future__ import annotations

import requests

from src import covers


def test_ruta_cache_estable(tmp_path) -> None:
    a = covers._ruta_cache("https://i.scdn.co/image/abc", base=tmp_path)
    b = covers._ruta_cache("https://i.scdn.co/image/abc", base=tmp_path)
    c = covers._ruta_cache("https://i.scdn.co/image/OTRA", base=tmp_path)
    assert a == b and a != c and a.suffix == ".jpg" and a.parent == tmp_path


def test_cache_hit_no_descarga(tmp_path, monkeypatch) -> None:
    url = "https://i.scdn.co/image/abc"
    p = covers._ruta_cache(url, base=tmp_path)
    p.write_bytes(b"JPEGFAKE")

    def boom(*a, **k):
        raise AssertionError("no debió tocar la red")
    monkeypatch.setattr(covers, "_descargar", boom)
    assert covers.asegurar_cover(url, base=tmp_path) == p


def test_descarga_normal_y_escribe(tmp_path, monkeypatch) -> None:
    url = "https://i.scdn.co/image/abc"
    monkeypatch.setattr(covers, "_descargar", lambda u: b"BYTESIMG")
    p = covers.asegurar_cover(url, base=tmp_path)
    assert p is not None and p.read_bytes() == b"BYTESIMG"


def test_fallback_doh_si_dns_falla(tmp_path, monkeypatch) -> None:
    url = "https://i.scdn.co/image/abc"

    def dns_roto(u):
        raise requests.ConnectionError("NameResolutionError")
    monkeypatch.setattr(covers, "_descargar", dns_roto)
    monkeypatch.setattr(covers, "_descargar_via_doh", lambda u: b"VIADOH")
    p = covers.asegurar_cover(url, base=tmp_path)
    assert p is not None and p.read_bytes() == b"VIADOH"


def test_falla_total_regresa_none(tmp_path, monkeypatch) -> None:
    def roto(u):
        raise requests.ConnectionError("x")
    monkeypatch.setattr(covers, "_descargar", roto)
    monkeypatch.setattr(covers, "_descargar_via_doh", roto)
    assert covers.asegurar_cover("https://x/y", base=tmp_path) is None
```

- [ ] **Step 2: Verificar que falla**

Run: `.venv/bin/python -m pytest tests/test_covers.py -v`
Expected: FAIL `ModuleNotFoundError: No module named 'src.covers'`

- [ ] **Step 3: Implementar**

`src/covers.py`:

```python
"""Caché local de portadas (Spotify/YouTube) para las tarjetas.

El filtro DNS de la máquina bloquea `i.scdn.co` (CDN de imágenes de Spotify):
el resolver del sistema responde vacío SOLO para ese host, así que ni el
navegador ni Playwright pueden bajar las portadas. La red en sí no está
bloqueada: el host resuelve bien vía DoH y conectar por IP funciona.

Estrategia: descargar UNA vez a `data/covers/{hash}.jpg` y renderizar siempre
desde archivo local (file://). Descarga: requests normal → si el DNS falla,
fallback DoH (dns.google) + conexión por IP con SNI del host real.

Uso:
    from src import covers
    path = covers.asegurar_cover(url)   # Path local o None si no se pudo
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from urllib.parse import urlparse

import certifi
import requests
import urllib3

import config

_TIMEOUT = 15


def _dir_covers() -> Path:
    p = config.BASE_DIR / "data" / "covers"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _ruta_cache(url: str, *, base: Path | None = None) -> Path:
    """Ruta determinista por URL (hash corto): misma portada → mismo archivo."""
    h = hashlib.sha1(url.encode()).hexdigest()[:16]
    return (base or _dir_covers()) / f"{h}.jpg"


def _descargar(url: str) -> bytes:
    r = requests.get(url, timeout=_TIMEOUT)
    r.raise_for_status()
    return r.content


def _descargar_via_doh(url: str) -> bytes:
    """Resuelve el host vía DoH (dns.google) y conecta por IP con SNI.

    Esquiva el resolver local que filtra i.scdn.co; el certificado se valida
    contra el hostname REAL (server_hostname), no contra la IP.
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""
    r = requests.get("https://dns.google/resolve",
                     params={"name": host, "type": "A"}, timeout=_TIMEOUT)
    r.raise_for_status()
    ips = [a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1]
    if not ips:
        raise requests.ConnectionError(f"DoH sin respuesta A para {host}")
    pool = urllib3.HTTPSConnectionPool(
        ips[0], 443, server_hostname=host, assert_hostname=host,
        ca_certs=certifi.where(), timeout=_TIMEOUT)
    ruta = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    resp = pool.request("GET", ruta, headers={"Host": host})
    if resp.status != 200:
        raise requests.ConnectionError(f"{host} via IP respondió {resp.status}")
    return resp.data


def asegurar_cover(url: str | None, *, base: Path | None = None) -> Path | None:
    """Devuelve la ruta local de la portada (cacheada o recién bajada), o None."""
    if not url:
        return None
    destino = _ruta_cache(url, base=base)
    if destino.exists():
        return destino
    try:
        data = _descargar(url)
    except (requests.RequestException, OSError):
        try:
            data = _descargar_via_doh(url)
        except Exception as exc:  # red rota de verdad: la tarjeta usa placeholder
            print(f"⚠️ portada no disponible ({exc})", file=sys.stderr)
            return None
    destino.write_bytes(data)
    return destino
```

- [ ] **Step 4: Tests pasan**

Run: `.venv/bin/python -m pytest tests/test_covers.py -v` → 5 PASS

- [ ] **Step 5: Prueba real (una portada de Spotify bloqueada por DNS)**

```bash
.venv/bin/python -c "
from src import covers
p = covers.asegurar_cover('https://i.scdn.co/image/ab67616d0000b273c55307e0ad500999feb96d70')
print(p, p.stat().st_size if p else 0, 'bytes')"
```
Expected: ruta en `data/covers/` con >10KB (pasó por el fallback DoH).

---

### Task B: Plantillas `release_cover.html`, `release_grid.html`, `release_cta.html`

**Files:**
- Create: `templates/release_cover.html`
- Create: `templates/release_grid.html`
- Create: `templates/release_cta.html`

Marca: paper `#faf8f3`, verde `#1b5e3f`, Tinos (serif) + Poppins (sans), 1080×1350, nodo raíz `.card` (lo screenshotea el motor). Fuentes vía `{{ fonts_dir }}` como las demás plantillas.

- [ ] **Step 1: `templates/release_cover.html`** (portada: collage + lineup)

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  @font-face { font-family:'Tinos'; src:url('{{ fonts_dir }}/Tinos-Bold.ttf') format('truetype'); font-weight:700; }
  @font-face { font-family:'Tinos'; src:url('{{ fonts_dir }}/Tinos-Italic.ttf') format('truetype'); font-weight:400; font-style:italic; }
  @font-face { font-family:'Poppins'; src:url('{{ fonts_dir }}/Poppins-SemiBold.ttf') format('truetype'); font-weight:600; }
  :root { --green:#1b5e3f; --paper:#faf8f3; --w:1080px; --h:1350px; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:var(--w); height:var(--h); }
  .card { width:var(--w); height:var(--h); background:var(--green); color:var(--paper);
          display:flex; flex-direction:column; align-items:center; justify-content:center;
          text-align:center; padding:70px 80px; position:relative; overflow:hidden; }
  .kicker { font-family:'Poppins',sans-serif; font-weight:600; font-size:30px; letter-spacing:8px;
            text-transform:uppercase; opacity:.85; }
  .titulo { font-family:'Tinos',serif; font-weight:700; font-size:132px; line-height:.95; margin-top:22px; }
  .rango { font-family:'Tinos',serif; font-style:italic; font-size:46px; margin-top:24px; opacity:.95; }

  /* Pila de portadas: rotaciones alternadas + traslape, como discos sobre la mesa */
  .pila { display:flex; justify-content:center; align-items:center; margin-top:54px; height:300px; }
  .pila img, .pila .ph { width:240px; height:240px; object-fit:cover; border-radius:10px; flex:none;
              box-shadow:0 14px 34px rgba(0,0,0,.45); border:6px solid var(--paper); margin:0 -26px; }
  .pila .ph { background:#14492f; display:flex; align-items:center; justify-content:center;
              font-family:'Tinos',serif; font-weight:700; font-size:96px; color:var(--paper); }
  .pila > *:nth-child(odd)  { transform:rotate(-5deg); }
  .pila > *:nth-child(even) { transform:rotate(4deg) translateY(14px); }
  .pila > *:nth-child(3)    { transform:rotate(-2deg) translateY(-10px); }

  /* Lineup: los nombres llaman a los fans de cada banda desde el feed */
  .lineup { margin-top:56px; font-family:'Poppins',sans-serif; font-weight:600; font-size:26px;
            letter-spacing:2px; text-transform:uppercase; line-height:1.7; opacity:.92; max-width:880px; }
  .lineup .dot { opacity:.55; padding:0 10px; }
  .pie { position:absolute; bottom:60px; left:0; right:0; font-family:'Tinos',serif;
         font-weight:700; font-size:46px; letter-spacing:1px; }
  .pie .line { display:inline-block; width:110px; height:4px; background:var(--paper);
               vertical-align:middle; margin:0 20px; opacity:.8; }
</style>
</head>
<body>
  <div class="card">
    <div class="kicker">{{ kicker }}</div>
    <div class="titulo">Música<br>Nueva</div>
    <div class="rango">{{ rango }}</div>
    <div class="pila">
      {% for m in minis %}
        {% if m.src %}<img src="{{ m.src }}">{% else %}<div class="ph">{{ m.inicial }}</div>{% endif %}
      {% endfor %}
    </div>
    <div class="lineup">
      {%- for n in lineup -%}
        {{ n }}{% if not loop.last %}<span class="dot">·</span>{% endif %}
      {%- endfor -%}
    </div>
    <div class="pie"><span class="line"></span>@gdlscene<span class="line"></span></div>
  </div>
</body>
</html>
```

- [ ] **Step 2: `templates/release_grid.html`** (slide 2×2 adaptativo)

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  @font-face { font-family:'Tinos'; src:url('{{ fonts_dir }}/Tinos-Regular.ttf') format('truetype'); font-weight:400; }
  @font-face { font-family:'Tinos'; src:url('{{ fonts_dir }}/Tinos-Bold.ttf') format('truetype'); font-weight:700; }
  @font-face { font-family:'Tinos'; src:url('{{ fonts_dir }}/Tinos-Italic.ttf') format('truetype'); font-weight:400; font-style:italic; }
  @font-face { font-family:'Poppins'; src:url('{{ fonts_dir }}/Poppins-SemiBold.ttf') format('truetype'); font-weight:600; }
  :root { --green:#1b5e3f; --paper:#faf8f3; --ink:#0a0a0a; --w:1080px; --h:1350px; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:var(--w); height:var(--h); }
  .card { width:var(--w); height:var(--h); background:var(--paper); display:flex; flex-direction:column; }

  .head { padding:54px 80px 26px; text-align:center; border-bottom:6px solid var(--green); }
  .kicker { font-family:'Poppins',sans-serif; font-weight:600; font-size:24px; letter-spacing:6px;
            color:var(--green); text-transform:uppercase; margin-bottom:8px; }
  .titulo { font-family:'Tinos',serif; font-weight:700; font-size:84px; line-height:1; color:var(--ink); }

  .grid { flex:1; display:grid; grid-template-columns:repeat(2, 1fr); gap:34px 44px;
          padding:44px 80px; align-content:center; min-height:0; }
  /* 1 o 2 releases: una sola columna centrada, sin celdas fantasma */
  .grid.n1 { grid-template-columns:minmax(0, 620px); justify-content:center; }
  .grid.n2 { grid-template-columns:repeat(2, 1fr); align-content:center; }

  .celda { display:flex; flex-direction:column; min-width:0; }
  .cuadro { position:relative; width:100%; aspect-ratio:1/1; border-radius:12px; overflow:hidden;
            box-shadow:0 10px 26px rgba(0,0,0,.22); background:var(--green); }
  .cuadro img { width:100%; height:100%; object-fit:cover; display:block; }
  .cuadro .ph { width:100%; height:100%; display:flex; align-items:center; justify-content:center;
                font-family:'Tinos',serif; font-weight:700; font-size:150px; color:var(--paper); }
  .banda { font-family:'Tinos',serif; font-weight:700; font-size:36px; color:var(--ink);
           line-height:1.08; margin-top:18px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .obra { font-family:'Tinos',serif; font-style:italic; font-size:27px; color:#555; margin-top:4px;
          white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .meta { display:flex; align-items:center; gap:14px; margin-top:12px; }
  .badge { font-family:'Poppins',sans-serif; font-weight:600; font-size:17px; letter-spacing:2px;
           text-transform:uppercase; color:var(--paper); background:var(--green);
           padding:6px 16px; border-radius:999px; }
  .fecha { font-family:'Poppins',sans-serif; font-weight:600; font-size:20px; letter-spacing:1px;
           color:var(--green); text-transform:uppercase; }

  .footer { display:flex; align-items:center; justify-content:center; gap:22px; padding:0 80px 48px; }
  .footer .line { flex:1; height:4px; background:var(--green); max-width:230px; }
  .footer .handle { font-family:'Tinos',serif; font-weight:700; color:var(--green); font-size:42px; white-space:nowrap; }
</style>
</head>
<body>
  <div class="card">
    <div class="head">
      <div class="kicker">{{ kicker }}{% if paginas > 1 %} · {{ pagina }}/{{ paginas }}{% endif %}</div>
      <div class="titulo">Música Nueva</div>
    </div>
    <div class="grid {% if releases|length == 1 %}n1{% elif releases|length == 2 %}n2{% endif %}">
      {% for r in releases %}
      <div class="celda">
        <div class="cuadro">
          {% if r.cover_src %}<img src="{{ r.cover_src }}">{% else %}<div class="ph">{{ r.inicial }}</div>{% endif %}
        </div>
        <div class="banda">{{ r.banda }}</div>
        <div class="obra">{{ r.obra }}</div>
        <div class="meta"><span class="badge">{{ r.badge }}</span><span class="fecha">{{ r.fecha }}</span></div>
      </div>
      {% endfor %}
    </div>
    <div class="footer"><div class="line"></div><div class="handle">@gdlscene</div><div class="line"></div></div>
  </div>
</body>
</html>
```

- [ ] **Step 3: `templates/release_cta.html`**

```html
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<style>
  @font-face { font-family:'Tinos'; src:url('{{ fonts_dir }}/Tinos-Bold.ttf') format('truetype'); font-weight:700; }
  @font-face { font-family:'Tinos'; src:url('{{ fonts_dir }}/Tinos-Italic.ttf') format('truetype'); font-weight:400; font-style:italic; }
  @font-face { font-family:'Poppins'; src:url('{{ fonts_dir }}/Poppins-SemiBold.ttf') format('truetype'); font-weight:600; }
  :root { --green:#1b5e3f; --paper:#faf8f3; --w:1080px; --h:1350px; }
  * { margin:0; padding:0; box-sizing:border-box; }
  html, body { width:var(--w); height:var(--h); }
  .card { width:var(--w); height:var(--h); background:var(--paper); color:var(--green);
          display:flex; flex-direction:column; align-items:center; justify-content:center;
          text-align:center; padding:80px; position:relative; }
  .arroba { font-family:'Poppins',sans-serif; font-weight:600; font-size:30px; letter-spacing:5px;
            text-transform:uppercase; opacity:.8; margin-bottom:24px; }
  .grande { font-family:'Tinos',serif; font-weight:700; font-size:112px; line-height:1; }
  .sub { font-family:'Tinos',serif; font-style:italic; font-size:44px; margin-top:36px; max-width:800px; }
  .acciones { display:flex; gap:40px; margin-top:56px; font-family:'Poppins',sans-serif;
              font-weight:600; font-size:38px; }
  .acciones span { background:var(--green); color:var(--paper); padding:16px 36px; border-radius:16px; }
  .pie { position:absolute; bottom:70px; left:0; right:0; font-family:'Tinos',serif;
         font-weight:700; font-size:50px; }
</style>
</head>
<body>
  <div class="card">
    <div class="arroba">{{ kicker }}</div>
    <div class="grande">¿Ya las<br>escuchaste?</div>
    <div class="sub">Guarda este post para el finde y comparte tu favorita en tu historia.</div>
    <div class="acciones"><span>🔖 Guarda</span><span>↗ Comparte</span></div>
    <div class="pie">@gdlscene</div>
  </div>
</body>
</html>
```

- [ ] **Step 4: Smoke render de las 3 plantillas con datos dummy**

```bash
.venv/bin/python - <<'EOF'
from src import compose
minis = [{"src": None, "inicial": c} for c in "KSML"]
p1 = compose.render_card("release_cover.html", {
    "kicker": "lo que salió esta semana", "rango": "1 al 7 de junio",
    "minis": minis, "lineup": ["kabala", "SilentNoir", "miraflores", "a l a m e d a"]},
    prefix="smoke_cover")
rel = [{"cover_src": None, "inicial": "K", "banda": "kabala", "obra": "Nuevo Sencillo",
        "badge": "Sencillo", "fecha": "5 jun"}] * 4
p2 = compose.render_card("release_grid.html", {
    "kicker": "lo que salió esta semana", "releases": rel, "pagina": 1, "paginas": 2},
    prefix="smoke_grid")
p3 = compose.render_card("release_cta.html", {"kicker": "lo que salió esta semana"},
    prefix="smoke_cta")
print(p1, p2, p3, sep="\n")
EOF
```
Expected: 3 PNGs sin error. Abrirlos (Read tool) y verificar: nada cortado, jerarquía clara, grid sin overflow.

---

### Task C: `build_releases_carousel` + caption con tags en `generate_agenda.py`

**Files:**
- Modify: `src/generate_agenda.py`
- Test: `tests/test_releases_carousel.py` (nuevo)

- [ ] **Step 1: Tests failing primero**

`tests/test_releases_carousel.py`:

```python
"""Carrusel de música nueva: parse de badge, chunks de 4, caption con tags."""
from __future__ import annotations

from src.generate_agenda import _caption_releases, _parse_titulo, _chunks


def test_parse_titulo_badge() -> None:
    assert _parse_titulo("Nuevo Sencillo (sencillo)") == ("Nuevo Sencillo", "Sencillo")
    assert _parse_titulo("Gran Disco (álbum)") == ("Gran Disco", "Álbum")
    assert _parse_titulo("Yorke | Parsons (Sesiones Bilbao) (live session)") \
        == ("Yorke | Parsons (Sesiones Bilbao)", "Live session")
    assert _parse_titulo("Sin Sufijo") == ("Sin Sufijo", "Estreno")
    assert _parse_titulo(None) == ("", "Estreno")


def test_chunks_de_cuatro() -> None:
    assert [len(c) for c in _chunks(list(range(9)), 4)] == [4, 4, 1]


def test_caption_releases_etiqueta_a_todos() -> None:
    evs = [
        {"fecha_evento": "2026-06-04", "banda_nombre": "a l a m e d a",
         "banda_handle": "alammedda", "titulo": "Yorke | Parsons (live session)"},
        {"fecha_evento": "2026-06-05", "banda_nombre": "kabala",
         "banda_handle": "kabala_oficial", "titulo": "X (sencillo)"},
        {"fecha_evento": "2026-06-05", "banda_nombre": "kabala",  # repetida → 1 tag
         "banda_handle": "kabala_oficial", "titulo": "Y (sencillo)"},
    ]
    cap = _caption_releases(evs, "semanal", omitidos=2)
    assert "@alammedda" in cap and "@kabala_oficial" in cap
    assert cap.count("@kabala_oficial") == 1   # tags únicos, en bloque final
    assert "• 4 jun — a l a m e d a" in cap
    assert "+2 lanzamientos más" in cap
```

- [ ] **Step 2: Verificar que falla**

Run: `.venv/bin/python -m pytest tests/test_releases_carousel.py -v`
Expected: FAIL ImportError (`_caption_releases`, `_parse_titulo` no existen)

- [ ] **Step 3: Implementar en `src/generate_agenda.py`**

Agregar import arriba (junto a los demás `from src import ...`): `from src import covers`.

Agregar después de `_IG_CAROUSEL_MAX`:

```python
_MAX_RELEASES_SLIDE = 4      # grid 2×2: más de 4 no se lee
_MAX_MINIS_PORTADA = 6       # pila de portadas en la cover

_BADGES = {"sencillo": "Sencillo", "álbum": "Álbum", "live session": "Live session"}


def _parse_titulo(titulo: str | None) -> tuple[str, str]:
    """Separa "Obra (sencillo)" → ("Obra", "Sencillo"); sin sufijo → "Estreno"."""
    if not titulo:
        return "", "Estreno"
    t = titulo.strip()
    for sufijo, badge in _BADGES.items():
        marca = f"({sufijo})"
        if t.lower().endswith(marca):
            return t[: -len(marca)].strip(), badge
    return t, "Estreno"


def _caption_releases(eventos: list[dict[str, Any]], periodo: str, *, omitidos: int = 0) -> str:
    """Caption del carrusel: línea por release + bloque de tags únicos al final."""
    lineas = [_MODO["releases"]["caption_head"][periodo]]
    handles: list[str] = []
    for ev in eventos:
        d = datetime.fromisoformat(ev["fecha_evento"][:10])
        obra, _ = _parse_titulo(ev.get("titulo"))
        linea = f"• {d.day} {_MES_ABREV[d.month - 1]} — {ev['banda_nombre']}"
        if obra:
            linea += f": {obra}"
        lineas.append(linea)
        h = ev.get("banda_handle")
        if h and h not in handles:
            handles.append(h)
    if omitidos:
        lineas.append(f"…y +{omitidos} lanzamientos más.")
    lineas += ["", "🔖 Guarda el post y comparte tu favorita."]
    if handles:  # etiqueta a todas las bandas del carrusel
        lineas += ["", " ".join(f"@{h}" for h in handles)]
    return "\n".join(lineas)


def build_releases_carousel(periodo: str, *, hoy: datetime | None = None) -> tuple[str, list[str]]:
    """Carrusel de música nueva: PORTADA (collage+lineup) + grids 2×2 + CTA.

    Las portadas se bajan a data/covers/ (covers.asegurar_cover) y se renderizan
    como file:// — inmunes al filtro DNS que bloquea i.scdn.co. Abre su propia
    conexión SQLite (se llama desde un hilo aparte).
    """
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    dias = _PERIODOS[periodo]
    cx = db.connect()
    try:
        releases = releases_ventana(cx, dias, hoy=hoy)
    finally:
        cx.close()
    if not releases:
        return "", []

    kicker = _MODO["releases"]["kicker"][periodo]
    rango = _rango_releases(hoy, dias)

    # Slides: 4 por grid; el carrusel topa en 10 (portada + 8 grids + CTA).
    visibles = releases[: _MAX_RELEASES_SLIDE * (_IG_CAROUSEL_MAX - 2)]
    omitidos = len(releases) - len(visibles)

    # Portadas locales una sola vez (sirven para portada y grids).
    locales: dict[int, str | None] = {}
    for ev in visibles:
        p = covers.asegurar_cover(ev.get("cover_url"))
        locales[ev["id"]] = compose_mod._to_src(str(p)) if p else None

    minis = [{"src": locales[e["id"]], "inicial": (e["banda_nombre"] or "?")[0].upper()}
             for e in visibles[:_MAX_MINIS_PORTADA]]
    lineup: list[str] = []
    for e in visibles:
        if e["banda_nombre"] not in lineup:
            lineup.append(e["banda_nombre"])
    cover = compose_mod.render_card("release_cover.html", {
        "kicker": kicker, "rango": rango, "minis": minis, "lineup": lineup,
    }, prefix="rel_cover")
    pngs = [str(cover)]

    slides = _chunks(visibles, _MAX_RELEASES_SLIDE)
    for i, slide in enumerate(slides, start=1):
        filas = []
        for ev in slide:
            obra, badge = _parse_titulo(ev.get("titulo"))
            d = datetime.fromisoformat(ev["fecha_evento"][:10])
            filas.append({
                "cover_src": locales[ev["id"]],
                "inicial": (ev["banda_nombre"] or "?")[0].upper(),
                "banda": ev["banda_nombre"], "obra": obra, "badge": badge,
                "fecha": f"{d.day} {_MES_ABREV[d.month - 1]}",
            })
        png = compose_mod.render_card("release_grid.html", {
            "kicker": kicker, "releases": filas, "pagina": i, "paginas": len(slides),
        }, prefix=f"rel_grid_s{i}")
        pngs.append(str(png))

    cta = compose_mod.render_card("release_cta.html", {"kicker": kicker}, prefix="rel_cta")
    pngs.append(str(cta))

    return _caption_releases(visibles, periodo, omitidos=omitidos), pngs
```

En `main()`, sustituir la rama releases (el `else` que llama a `build_card`):

```python
        else:
            # Música nueva = carrusel: portada (collage+lineup) + grids 2×2 + CTA.
            caption, pngs = await asyncio.to_thread(build_releases_carousel, periodo)
            if not pngs:
                print("No hay releases en la ventana.")
                return
```

NO tocar `build_card` ni la rama shows. `_fila_tarjeta` queda (lo usa el modo shows y tests existentes).

- [ ] **Step 4: Tests**

Run: `.venv/bin/python -m pytest tests/test_releases_carousel.py tests/test_agenda.py -v` → PASS
Run: `.venv/bin/python -m pytest tests/ -q` → sin fallas nuevas

- [ ] **Step 5: Render real (sin Telegram/Sheet)**

```bash
.venv/bin/python - <<'EOF'
from src.generate_agenda import build_releases_carousel
cap, pngs = build_releases_carousel("mensual")
print(cap); print(); [print(p) for p in pngs]
EOF
```
Expected: portada + ~4 grids + CTA con los 15 releases reales (incluye los 2 de YouTube), portadas visibles (bajadas vía covers.py), caption con todos los @handles. Inspeccionar los PNGs visualmente.

---

### Task D: Verificación visual + entrega (inline, lo hace el controlador)

- [ ] Abrir los PNGs del render real y revisar: portadas cargadas, sin overflow, collage/lineup legibles, badges correctos (live session para los 2 de YouTube).
- [ ] Suite completa verde.
- [ ] Entregar a Ricardo para aprobación visual antes de publicar nada.
