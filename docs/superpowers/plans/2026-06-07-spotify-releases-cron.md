# Spotify Releases Cron Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich anti-saturación (fail-fast + throttle + lock), matchear bandas faltantes, y cron launchd diario que registra releases nuevos en `events` y avisa por Telegram.

**Architecture:** Todo lo que llama Spotify pasa por un lock file (`data/.spotify.lock`) y un cliente spotipy sin reintentos (ante 429 se aborta con mensaje, lo procesado queda). `src/check_releases.py` (nuevo) itera bandas activas con `spotify_id`, reusa `_registrar_releases` y notifica por `sendMessage` HTTP directo (sin polling → no choca con bot.py). launchd lo corre 1×/día.

**Tech Stack:** Python 3 (`.venv/bin/python`), spotipy, requests, SQLite (`src/db.py`), pytest, launchd.

**⚠️ Reglas de esta sesión:** NO hacer `git commit` (working tree compartido con otra sesión que trabaja el sistema de prioridad). NO tocar `planner.py` ni `web/`. En `config.py` solo AGREGAR variables en la sección Spotify. Los pasos de "Commit" de la convención se sustituyen por "verificar tests"; al final se entrega la lista de archivos para que Ricardo commitee cuando guste.

---

### Task 1: Lock file de Spotify + throttle en config

**Files:**
- Modify: `config.py` (sección Spotify, ~línea 79)
- Modify: `src/enrich_spotify.py`
- Test: `tests/test_spotify_lock.py` (nuevo)

- [ ] **Step 1: Agregar config**

En `config.py`, después de `SPOTIFY_RELEASE_DAYS`:

```python
# Pausa entre bandas al llamar Spotify (anti rate-limit; ~2 llamadas/banda).
SPOTIFY_THROTTLE_S = float(_get("SPOTIFY_THROTTLE_S", "0.6") or "0.6")
# Lock para que dos procesos (pipeline, cron, GUI) no llamen Spotify a la vez.
SPOTIFY_LOCK_PATH = _get("SPOTIFY_LOCK_PATH", "./data/.spotify.lock")
```

- [ ] **Step 2: Test del lock (failing)**

`tests/test_spotify_lock.py`:

```python
"""Lock de Spotify: exclusión entre procesos, locks muertos se roban."""
from __future__ import annotations

import os

import pytest

from src.enrich_spotify import SpotifyOcupado, spotify_lock


def test_lock_exclusivo(tmp_path) -> None:
    lock = tmp_path / "s.lock"
    with spotify_lock(lock):
        with pytest.raises(SpotifyOcupado):
            with spotify_lock(lock):
                pass
    # al salir se libera
    with spotify_lock(lock):
        pass


def test_lock_muerto_se_roba(tmp_path) -> None:
    lock = tmp_path / "s.lock"
    lock.write_text("99999999")  # pid que no existe
    with spotify_lock(lock):  # no debe levantar
        assert lock.read_text() == str(os.getpid())
```

- [ ] **Step 3: Correr y ver que falla**

Run: `.venv/bin/python -m pytest tests/test_spotify_lock.py -v`
Expected: FAIL con `ImportError: cannot import name 'SpotifyOcupado'`

- [ ] **Step 4: Implementar el lock**

En `src/enrich_spotify.py` (después de los imports, antes de `get_client`):

```python
import contextlib
import os
import time
from pathlib import Path


class SpotifyOcupado(RuntimeError):
    """Otro proceso está usando Spotify (lock tomado por un pid vivo)."""


def _pid_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, ValueError):
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def spotify_lock(path: str | Path | None = None):
    """Exclusión entre procesos que llaman Spotify (pipeline, cron, GUI).

    Creación atómica (O_EXCL). Si el lock existe pero su pid ya murió
    (proceso matado a media corrida), se roba en vez de quedar trabado.
    """
    lock = Path(path) if path else config._resolve(config.SPOTIFY_LOCK_PATH)
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            pid = int(lock.read_text().strip())
        except (ValueError, OSError):
            pid = None
        if pid and _pid_vivo(pid):
            raise SpotifyOcupado(f"Spotify en uso por pid {pid} ({lock})")
        lock.unlink(missing_ok=True)  # lock muerto → robar
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
```

- [ ] **Step 5: Correr tests**

Run: `.venv/bin/python -m pytest tests/test_spotify_lock.py -v`
Expected: 2 PASS

---

### Task 2: Cliente fail-fast + throttle + manejo de 429 en enrich

**Files:**
- Modify: `src/enrich_spotify.py` (`get_client`, `enrich`)
- Test: `tests/test_spotify_failfast.py` (nuevo)

- [ ] **Step 1: Test del corte por 429 (failing)**

`tests/test_spotify_failfast.py`:

```python
"""Ante 429, enrich corta la corrida con mensaje en vez de colgarse."""
from __future__ import annotations

from spotipy import SpotifyException

from src.enrich_spotify import RateLimitado, _checar_429


def test_checar_429_convierte_y_lee_retry_after() -> None:
    exc = SpotifyException(429, -1, "rate", headers={"Retry-After": "120"})
    try:
        _checar_429(exc)
        raise AssertionError("debió levantar RateLimitado")
    except RateLimitado as rl:
        assert rl.retry_after == 120


def test_checar_429_ignora_otros_errores() -> None:
    exc = SpotifyException(404, -1, "not found", headers={})
    _checar_429(exc)  # no levanta: el caller decide qué hacer con el 404
```

- [ ] **Step 2: Correr y ver que falla**

Run: `.venv/bin/python -m pytest tests/test_spotify_failfast.py -v`
Expected: FAIL con `ImportError: cannot import name 'RateLimitado'`

- [ ] **Step 3: Implementar fail-fast**

En `src/enrich_spotify.py`:

```python
class RateLimitado(RuntimeError):
    """Spotify regresó 429: cortar la corrida (lo guardado queda)."""

    def __init__(self, retry_after: int | None):
        self.retry_after = retry_after
        espera = f"~{retry_after // 60 + 1} min" if retry_after else "un rato"
        super().__init__(f"Rate limit de Spotify; reintenta en {espera}.")


def _checar_429(exc: SpotifyException) -> None:
    """Si el error es 429, lo convierte a RateLimitado (corte limpio)."""
    if exc.http_status == 429:
        try:
            retry = int((exc.headers or {}).get("Retry-After", ""))
        except ValueError:
            retry = None
        raise RateLimitado(retry) from exc
```

Agregar el import: `from spotipy import SpotifyException` (junto a `import spotipy`).

Cambiar `get_client()` para que spotipy NO reintente (el backoff infinito era el "cuelgue"):

```python
def get_client() -> spotipy.Spotify:
    if not (config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET):
        raise RuntimeError("Faltan SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET en el .env")
    # retries=0: ante 429 falla YA y nosotros cortamos con mensaje claro,
    # en vez del backoff infinito de spotipy que parece un cuelgue.
    return spotipy.Spotify(retries=0, status_retries=0, auth_manager=SpotifyClientCredentials(
        client_id=config.SPOTIFY_CLIENT_ID,
        client_secret=config.SPOTIFY_CLIENT_SECRET,
    ))
```

- [ ] **Step 4: Usar lock + throttle + corte en `enrich()`**

Reemplazar el cuerpo del loop de `enrich()`:

```python
def enrich(handles: list[str] | None = None, *, solo_faltantes: bool = False) -> None:
    """Enriquece bandas activas (o `handles`); `solo_faltantes` = sin spotify_id."""
    cx = db.connect()
    try:
        db.init_db(cx)
        bandas = db.list_bands(cx)
        if handles:
            quiero = {h.lstrip("@").lower() for h in handles}
            bandas = [b for b in bandas if (b.get("ig_handle") or "").lower() in quiero]
        if solo_faltantes:
            bandas = [b for b in bandas if not b.get("spotify_id")]
        if not bandas:
            print("No hay bandas que enriquecer.")
            return
        try:
            with spotify_lock():
                sp = get_client()
                print(f"Enriqueciendo {len(bandas)} banda(s) con Spotify…")
                for band in bandas:
                    try:
                        print(f"▶ {band['nombre']}: {enrich_band(sp, cx, band)}")
                    except SpotifyException as exc:
                        _checar_429(exc)
                        print(f"▶ {band['nombre']}: ❌ Spotify respondió mal ({exc.http_status})")
                    time.sleep(config.SPOTIFY_THROTTLE_S)
        except SpotifyOcupado as exc:
            print(f"⏭ {exc} — corre de nuevo cuando termine.")
        except RateLimitado as exc:
            print(f"🛑 {exc} Lo ya procesado quedó guardado.")
    finally:
        cx.close()
```

Y el CLI al final del archivo gana el flag:

```python
    parser.add_argument("--faltantes", action="store_true",
                        help="solo bandas activas SIN spotify_id")
    args = parser.parse_args()
    try:
        enrich(args.handles or None, solo_faltantes=args.faltantes)
```

OJO: los `except SpotifyException` internos de `enrich_band` (sp.artist con id inválido) y `_registrar_releases` deben dejar pasar el 429: agregar `_checar_429(exc)` como primera línea de esos `except`.

- [ ] **Step 5: Correr TODOS los tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: todos PASS (incluye los existentes de `test_enrich_spotify.py`)

---

### Task 3: `_registrar_releases` devuelve detalles (para el aviso de Telegram)

**Files:**
- Modify: `src/enrich_spotify.py` (`_registrar_releases`, `enrich_band`)
- Test: `tests/test_check_releases.py` (nuevo)

- [ ] **Step 1: Test (failing)**

`tests/test_check_releases.py`:

```python
"""Cron de releases: registro con detalle y formato del aviso de Telegram."""
from __future__ import annotations

from src import db
from src.enrich_spotify import _registrar_releases


class _FakeSpotify:
    """Devuelve un catálogo fijo; suficiente para probar inserción + dedupe."""

    def __init__(self, albums):
        self._albums = albums

    def artist_albums(self, artist_id, include_groups="", limit=10):
        return {"items": self._albums}


def _album(aid: str, nombre: str, fecha: str, tipo: str = "single"):
    return {"id": aid, "name": nombre, "release_date": fecha,
            "album_type": tipo, "images": [{"url": f"http://img/{aid}.jpg"}]}


def test_registrar_releases_devuelve_detalle_y_dedupea(tmp_path) -> None:
    from datetime import datetime
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="Kabala")
    hoy = datetime.now().strftime("%Y-%m-%d")
    sp = _FakeSpotify([_album("a1", "Nuevo Sencillo", hoy),
                       _album("a2", "Disco Viejo", "2019-01-01")])

    nuevos = _registrar_releases(sp, cx, bid, "spotify-id-x")
    assert [n["titulo"] for n in nuevos] == ["Nuevo Sencillo (sencillo)"]
    # segunda corrida: dedupe por id de álbum
    assert _registrar_releases(sp, cx, bid, "spotify-id-x") == []
```

- [ ] **Step 2: Correr y ver que falla**

Run: `.venv/bin/python -m pytest tests/test_check_releases.py -v`
Expected: FAIL (`_registrar_releases` hoy devuelve int, no lista)

- [ ] **Step 3: Cambiar el retorno a lista de dicts**

En `_registrar_releases`, acumular detalle en vez de contar:

```python
def _registrar_releases(sp: spotipy.Spotify, cx, band_id: int, artist_id: str) -> list[dict]:
    """Inserta releases recientes en events (dedupe por id de álbum).

    Devuelve los nuevos como [{"titulo", "fecha", "cover_url"}] para que el
    cron arme el aviso de Telegram; lista vacía = nada nuevo.
    """
    try:
        albums = sp.artist_albums(artist_id, include_groups="album,single", limit=10)
    except SpotifyException as exc:
        _checar_429(exc)
        return []
    nuevos: list[dict] = []
    for alb in albums.get("items", []):
        if not es_release_reciente(alb.get("release_date")):
            continue
        ya = db.rows(cx, "SELECT 1 FROM events WHERE band_id = ? AND source_post_id = ?",
                     (band_id, alb["id"]))
        if ya:
            continue
        # El tipo (álbum/single) enriquece el copy del anuncio de música nueva.
        clase = "álbum" if alb.get("album_type") == "album" else "sencillo"
        imgs = alb.get("images") or []
        titulo = f"{alb.get('name')} ({clase})" if alb.get("name") else None
        db.insert(cx, "events", band_id=band_id, tipo="release",
                  fecha_evento=alb.get("release_date"), titulo=titulo,
                  cover_url=imgs[0]["url"] if imgs else None,
                  source_post_id=alb["id"], status="nuevo")
        nuevos.append({"titulo": titulo, "fecha": alb.get("release_date"),
                       "cover_url": imgs[0]["url"] if imgs else None})
    return nuevos
```

En `enrich_band`, ajustar el uso (era int):

```python
    nuevos = _registrar_releases(sp, cx, band["id"], artista["id"])
    confianza = "link" if confirmado_por_link else "exacto"
    extra = f" · {len(nuevos)} release(s) nuevos → events" if nuevos else ""
```

- [ ] **Step 4: Correr tests**

Run: `.venv/bin/python -m pytest tests/test_check_releases.py tests/test_enrich_spotify.py -v`
Expected: PASS

---

### Task 4: `src/check_releases.py` — el script del cron

**Files:**
- Create: `src/check_releases.py`
- Test: `tests/test_check_releases.py` (ampliar)

- [ ] **Step 1: Test del formato del mensaje (failing)**

Agregar a `tests/test_check_releases.py`:

```python
def test_formato_mensaje() -> None:
    from src.check_releases import formato_mensaje
    nuevos = [
        {"banda": "Kabala", "titulo": "Nuevo Sencillo (sencillo)", "fecha": "2026-06-05"},
        {"banda": "Los Baxters", "titulo": "Disco (álbum)", "fecha": "2026-06-01"},
    ]
    msg = formato_mensaje(nuevos)
    assert "🎵" in msg and "Kabala" in msg and "Disco (álbum)" in msg
    assert formato_mensaje([]) == ""
```

- [ ] **Step 2: Correr y ver que falla**

Run: `.venv/bin/python -m pytest tests/test_check_releases.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'src.check_releases'`

- [ ] **Step 3: Implementar el script**

`src/check_releases.py`:

```python
"""Cron de releases: revisa Spotify y avisa por Telegram (sin polling).

Pensado para launchd (1×/día): itera bandas activas con `spotify_id`, registra
releases nuevos en `events` (tipo='release', con portada) reutilizando
`enrich_spotify._registrar_releases`, y si hubo nuevos manda UN mensaje simple
al chat de Telegram vía sendMessage HTTP directo — sin polling, así nunca
choca con bot.py.

Si otro proceso tiene el lock de Spotify (pipeline corriendo), se salta la
corrida en silencio: mañana hay otra. Ante 429 corta limpio; el dedupe hace
idempotente la siguiente corrida.

Uso:
    python -m src.check_releases            # corrida normal (cron)
    python -m src.check_releases --dry-run  # sin Telegram, solo imprime
"""
from __future__ import annotations

import argparse
import sys
import time

import requests
from spotipy import SpotifyException

import config
from src import db
from src.enrich_spotify import (
    RateLimitado,
    SpotifyOcupado,
    _checar_429,
    _registrar_releases,
    get_client,
    spotify_lock,
)


def formato_mensaje(nuevos: list[dict]) -> str:
    """Arma el aviso de Telegram: una línea por release, vacío si no hay."""
    if not nuevos:
        return ""
    lineas = [f"🎵 {len(nuevos)} release(s) nuevos en la escena:"]
    lineas += [f"• {n['banda']} — {n['titulo']} ({n['fecha']})" for n in nuevos]
    lineas.append("Genera la tarjeta desde la GUI → Calendarios.")
    return "\n".join(lineas)


def avisar_telegram(texto: str) -> bool:
    """sendMessage directo (sin polling). True si Telegram aceptó."""
    if not (config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID):
        print("Sin TELEGRAM_BOT_TOKEN/CHAT_ID: no aviso.", file=sys.stderr)
        return False
    r = requests.post(
        f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": config.TELEGRAM_CHAT_ID, "text": texto}, timeout=15)
    return r.ok


def check(dry_run: bool = False) -> list[dict]:
    """Una pasada completa. Devuelve los releases nuevos encontrados."""
    cx = db.connect()
    nuevos: list[dict] = []
    try:
        db.init_db(cx)
        bandas = [b for b in db.list_bands(cx) if b.get("spotify_id")]
        if not bandas:
            print("No hay bandas con spotify_id.")
            return []
        sp = get_client()
        print(f"Revisando releases de {len(bandas)} banda(s)…")
        for band in bandas:
            try:
                hallados = _registrar_releases(sp, cx, band["id"], band["spotify_id"])
            except SpotifyException as exc:
                _checar_429(exc)
                print(f"▶ {band['nombre']}: ❌ ({exc.http_status})")
                continue
            for n in hallados:
                nuevos.append({"banda": band["nombre"], **n})
                print(f"▶ {band['nombre']}: 🆕 {n['titulo']} ({n['fecha']})")
            time.sleep(config.SPOTIFY_THROTTLE_S)
    finally:
        cx.close()
    if nuevos and not dry_run:
        avisar_telegram(formato_mensaje(nuevos))
    print(f"Listo: {len(nuevos)} release(s) nuevos.")
    return nuevos


def main() -> int:
    parser = argparse.ArgumentParser(description="Cron de releases de Spotify")
    parser.add_argument("--dry-run", action="store_true", help="no manda Telegram")
    args = parser.parse_args()
    try:
        with spotify_lock():
            check(dry_run=args.dry_run)
    except SpotifyOcupado:
        print("⏭ Spotify en uso (¿pipeline corriendo?); me salto esta corrida.")
        return 0
    except RateLimitado as exc:
        print(f"🛑 {exc} Lo registrado quedó; la próxima corrida continúa.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Correr tests + dry-run real**

Run: `.venv/bin/python -m pytest tests/test_check_releases.py -v`
Expected: PASS

Run: `.venv/bin/python -m src.check_releases --dry-run`
Expected: recorre las bandas con spotify_id sin error (puede hallar 0 nuevos).

---

### Task 5: launchd plist (1×/día 10:00 + al prender)

**Files:**
- Create: `~/Library/LaunchAgents/com.gdlscene.releases.plist` (FUERA del repo)
- Create: `data/logs/` (lo crea el plist al loguear)

- [ ] **Step 1: Escribir el plist**

`~/Library/LaunchAgents/com.gdlscene.releases.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.gdlscene.releases</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/ricardo/Work/personal/instagod/.venv/bin/python</string>
    <string>-m</string>
    <string>src.check_releases</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/ricardo/Work/personal/instagod</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>10</integer><key>Minute</key><integer>0</integer></dict>
  <!-- Corre también al iniciar sesión: cubre el caso "la Mac estaba apagada
       a las 10". El dedupe hace inofensiva la corrida extra. -->
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key>
  <string>/Users/ricardo/Work/personal/instagod/data/logs/releases.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/ricardo/Work/personal/instagod/data/logs/releases.log</string>
</dict>
</plist>
```

- [ ] **Step 2: Crear carpeta de logs y cargar el agente**

```bash
mkdir -p /Users/ricardo/Work/personal/instagod/data/logs
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gdlscene.releases.plist
```

Nota: `RunAtLoad` dispara una corrida inmediata al bootstrap — sirve de prueba real.

- [ ] **Step 3: Verificar**

```bash
launchctl list | grep gdlscene
tail -20 /Users/ricardo/Work/personal/instagod/data/logs/releases.log
```

Expected: el job listado y el log con "Revisando releases de N banda(s)…".

---

### Task 6: Matchear las 58 faltantes + verificación final

**Files:** ninguno (corridas de scripts ya implementados)

- [ ] **Step 1: Corrida de match**

```bash
.venv/bin/python -m src.enrich_spotify --faltantes
```

Expected: matches exactos/por-link guardados; anotar la lista de "match dudoso"
y "sin match" que imprime, y entregársela a Ricardo para curar en la GUI (♻).

- [ ] **Step 2: Verificar tarjeta de música nueva con portadas**

Desde la GUI (Eventos → música nueva semana/mes) o:

```bash
sqlite3 data/gdlscene.db "SELECT count(*), sum(cover_url IS NOT NULL) FROM events WHERE tipo='release';"
```

Expected: los releases nuevos traen `cover_url`. Si hay viejos sin portada:

```bash
.venv/bin/python -c "from src.enrich_spotify import backfill_release_titles; backfill_release_titles()"
```

- [ ] **Step 3: Suite completa + entrega**

```bash
.venv/bin/python -m pytest tests/ -v
```

Expected: todo PASS. Entregar a Ricardo: lista de dudosas, conteo de nuevos
matches, y lista de archivos tocados para commit manual:
`config.py`, `src/enrich_spotify.py`, `src/check_releases.py`,
`tests/test_spotify_lock.py`, `tests/test_spotify_failfast.py`,
`tests/test_check_releases.py`, `docs/superpowers/`.
