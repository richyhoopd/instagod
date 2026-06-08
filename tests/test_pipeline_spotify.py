"""Tests del Frente C: pipeline Spotify solo-pendientes + botón Novedades + cron.

- `enrich(solo_pendientes=True)` solo toca bandas 'pendiente' (las que ya tienen
  id las refresca el cron de releases, no el pipeline).
- El paso spotify del pipeline corre `resolver_links` y luego `enrich` con
  `solo_pendientes=True`.
- El botón "🔄 Novedades" lanza `src.novedades` vía `_lanzar_sesion`.
- El script genera un LaunchAgent válido (diario 09:00) sin tocar launchctl.
"""
from __future__ import annotations

import contextlib
import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src import db

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "instalar_novedades_diario.sh"


# ---------- enrich(solo_pendientes=True) ----------

def test_enrich_solo_pendientes_filtra_por_estado(tmp_path, monkeypatch) -> None:
    from src import enrich_spotify

    db_path = tmp_path / "enrich.db"
    conn = db.connect(db_path)
    db.init_db(conn)
    db.insert(conn, "bands", nombre="Pendiente")  # default spotify_status='pendiente'
    db.insert(conn, "bands", nombre="YaOk", spotify_status="ok", spotify_id="zzz")
    db.insert(conn, "bands", nombre="Descartada", spotify_status="no_esta")
    conn.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    vistas: list[str] = []
    monkeypatch.setattr(enrich_spotify, "get_client", lambda: object())
    monkeypatch.setattr(enrich_spotify, "spotify_lock", contextlib.nullcontext)
    monkeypatch.setattr(enrich_spotify, "enrich_band",
                        lambda sp, cx, band: vistas.append(band["nombre"]) or "ok")

    enrich_spotify.enrich(solo_pendientes=True)

    assert vistas == ["Pendiente"]  # ni 'ok' ni 'no_esta'


def test_enrich_default_no_filtra_pendientes(tmp_path, monkeypatch) -> None:
    """Sin solo_pendientes el comportamiento previo no cambia (incluye 'ok')."""
    from src import enrich_spotify

    db_path = tmp_path / "enrich2.db"
    conn = db.connect(db_path)
    db.init_db(conn)
    db.insert(conn, "bands", nombre="Pendiente")
    db.insert(conn, "bands", nombre="YaOk", spotify_status="ok", spotify_id="zzz")
    conn.close()

    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))

    vistas: list[str] = []
    monkeypatch.setattr(enrich_spotify, "get_client", lambda: object())
    monkeypatch.setattr(enrich_spotify, "spotify_lock", contextlib.nullcontext)
    monkeypatch.setattr(enrich_spotify, "enrich_band",
                        lambda sp, cx, band: vistas.append(band["nombre"]) or "ok")

    enrich_spotify.enrich()

    assert "Pendiente" in vistas
    assert "YaOk" in vistas


# ---------- paso spotify del pipeline ----------

def test_pipeline_spotify_resuelve_links_y_enriquece_pendientes(monkeypatch) -> None:
    from src import enrich_spotify, pipeline, spotify_match

    monkeypatch.setattr(pipeline, "_bandas_activas", lambda h: ["kabala"])
    # Saltamos los pasos que tocan red/IG/LLM; solo nos interesa spotify.
    monkeypatch.setattr(pipeline.ingest_ig, "ingest", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.classify, "clasificar", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.parse_events, "parse_all", lambda *a, **k: None)

    resolver_cx: list[object] = []
    monkeypatch.setattr(spotify_match, "resolver_links",
                        lambda cx: resolver_cx.append(cx) or {})

    enrich_calls: list[dict] = []

    def fake_enrich(objetivo=None, **kw):
        enrich_calls.append({"objetivo": objetivo, "kw": kw})

    monkeypatch.setattr(enrich_spotify, "enrich", fake_enrich)

    pipeline.run(skip={"ingest", "classify", "events"})

    assert len(resolver_cx) == 1            # resolver_links corrió una vez
    assert enrich_calls == [{"objetivo": ["kabala"], "kw": {"solo_pendientes": True}}]


def test_pipeline_spotify_orden_resolver_antes_de_enrich(monkeypatch) -> None:
    from src import enrich_spotify, pipeline, spotify_match

    monkeypatch.setattr(pipeline, "_bandas_activas", lambda h: ["x"])
    monkeypatch.setattr(pipeline.ingest_ig, "ingest", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.classify, "clasificar", lambda *a, **k: None)
    monkeypatch.setattr(pipeline.parse_events, "parse_all", lambda *a, **k: None)

    orden: list[str] = []
    monkeypatch.setattr(spotify_match, "resolver_links",
                        lambda cx: orden.append("resolver") or {})
    monkeypatch.setattr(enrich_spotify, "enrich",
                        lambda *a, **k: orden.append("enrich"))

    pipeline.run(skip={"ingest", "classify", "events"})

    assert orden == ["resolver", "enrich"]


# ---------- botón Novedades ----------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "web.db"
    orig = db.connect
    monkeypatch.setattr(db, "connect", lambda *a, **k: orig(db_path))
    cx = db.connect()
    db.init_db(cx)
    cx.close()

    from web.app import app
    with TestClient(app) as c:
        yield c


def test_boton_novedades_lanza_modulo(client, monkeypatch) -> None:
    from web import app as webapp

    lanzados: list[tuple] = []
    monkeypatch.setattr(webapp, "_lanzar_sesion",
                        lambda modulo, *a: lanzados.append((modulo, a)) or None)

    resp = client.post("/novedades")

    assert resp.status_code == 200
    assert lanzados == [("src.novedades", ())]


def test_boton_novedades_respeta_bloqueo(client, monkeypatch) -> None:
    from fastapi.responses import HTMLResponse

    from web import app as webapp

    monkeypatch.setattr(webapp, "_lanzar_sesion",
                        lambda *a: HTMLResponse("⚠️ ocupado"))

    resp = client.post("/novedades")
    assert resp.status_code == 200
    assert "ocupado" in resp.text


def test_panel_pipeline_muestra_boton_novedades(client) -> None:
    # El botón vive en el panel de pipeline (cargado por HTMX vía /pipeline/status).
    resp = client.get("/pipeline/status")
    assert resp.status_code == 200
    assert "/novedades" in resp.text
    assert "Novedades" in resp.text


# ---------- generador del plist ----------

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash no disponible")
def test_script_sintaxis_valida() -> None:
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("plutil") is None, reason="plutil es de macOS")
def test_plist_generado_es_valido_y_tiene_rutas(tmp_path) -> None:
    dest = tmp_path / "com.gdlscene.novedades.plist"
    env = {**os.environ, "PLIST_DEST": str(dest)}

    r = subprocess.run(["bash", str(SCRIPT), "--solo-generar"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert dest.exists()

    lint = subprocess.run(["plutil", "-lint", str(dest)], capture_output=True, text=True)
    assert lint.returncode == 0, lint.stdout + lint.stderr

    data = plistlib.loads(dest.read_bytes())
    venv_py = str(REPO / ".venv" / "bin" / "python")
    assert data["ProgramArguments"] == [venv_py, "-m", "src.novedades"]
    assert data["WorkingDirectory"] == str(REPO)
    assert data["StartCalendarInterval"] == {"Hour": 9, "Minute": 0}
    log = str(REPO / "data" / "launchd_novedades.log")
    assert data["StandardOutPath"] == log
    assert data["StandardErrorPath"] == log
    assert data["Label"] == "com.gdlscene.novedades"


# ---------- pipeline incremental: ingest(nuevas) + novedades(ya scrapeadas) ----------

def _stub_pipeline(monkeypatch):
    """Mockea todo el pipeline salvo el paso ingest; devuelve el registro de llamadas."""
    from src import pipeline
    llamadas = {"ingest": [], "novedades": 0}
    monkeypatch.setattr(pipeline, "_bandas_activas", lambda h: ["x"])
    monkeypatch.setattr(pipeline.ingest_ig, "ingest",
                        lambda handles=None, **k: llamadas["ingest"].append((handles, k.get("rescan", False))))
    monkeypatch.setattr(pipeline.ingest_ig, "novedades",
                        lambda *a, **k: llamadas.__setitem__("novedades", llamadas["novedades"] + 1))
    return pipeline, llamadas


def test_pipeline_sin_handles_es_incremental(monkeypatch) -> None:
    pipeline, llamadas = _stub_pipeline(monkeypatch)
    pipeline.run(skip={"classify", "spotify", "events"})
    # bandas nuevas completas (ingest sin handles, sin rescan) + novedades de las scrapeadas
    assert llamadas["ingest"] == [(None, False)]
    assert llamadas["novedades"] == 1


def test_pipeline_rescan_no_corre_novedades(monkeypatch) -> None:
    pipeline, llamadas = _stub_pipeline(monkeypatch)
    pipeline.run(skip={"classify", "spotify", "events"}, rescan=True)
    # rescan = re-scrape completo explícito; no se duplica con novedades
    assert llamadas["ingest"] == [(None, True)]
    assert llamadas["novedades"] == 0


def test_pipeline_con_handles_no_corre_novedades(monkeypatch) -> None:
    pipeline, llamadas = _stub_pipeline(monkeypatch)
    monkeypatch.setattr(pipeline, "_bandas_activas", lambda h: ["x"])
    pipeline.run(handles=["kabala"], skip={"classify", "spotify", "events"})
    assert llamadas["ingest"] == [(["kabala"], False)]
    assert llamadas["novedades"] == 0
