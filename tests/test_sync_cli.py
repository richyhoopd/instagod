"""Tests del Frente C: CLI de sync diario + generador del LaunchAgent.

El entrypoint corre `sync_posts` (mockeado, sin red ni Sheet) y deja rastro en
un log; el script de instalación genera un plist válido sin tocar launchctl.
Spec: docs/superpowers/specs/2026-06-07-afinacion-datos-design.md (Frente C).
"""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from src import ig_insights

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "instalar_sync_diario.sh"


# ---------- entrypoint CLI ----------

def test_main_escribe_log_y_regresa_0(tmp_path, monkeypatch) -> None:
    log = tmp_path / "sync_metrics.log"
    resumen = {"posts": 18, "insights_fallidos": 2, "vinculados": 14, "warning": None}
    monkeypatch.setattr(ig_insights, "sync_posts", lambda cx: resumen)

    code = ig_insights.main(db_path=tmp_path / "t.db", log_path=log)

    assert code == 0
    linea = log.read_text(encoding="utf-8").strip()
    assert "posts=18" in linea
    assert "sin_insights=2" in linea
    assert "vinculados=14" in linea
    assert linea.split(" · ", 1)[0]  # timestamp ISO al inicio


def test_main_crea_directorio_del_log(tmp_path, monkeypatch) -> None:
    log = tmp_path / "data" / "sync_metrics.log"  # 'data' no existe aún
    monkeypatch.setattr(
        ig_insights, "sync_posts",
        lambda cx: {"posts": 1, "insights_fallidos": 0, "vinculados": 0, "warning": None},
    )

    assert ig_insights.main(db_path=tmp_path / "t.db", log_path=log) == 0
    assert log.exists()


def test_main_loguea_warning(tmp_path, monkeypatch) -> None:
    log = tmp_path / "sync_metrics.log"
    resumen = {"posts": 3, "insights_fallidos": 0, "vinculados": 0,
               "warning": "Sheet no disponible"}
    monkeypatch.setattr(ig_insights, "sync_posts", lambda cx: resumen)

    ig_insights.main(db_path=tmp_path / "t.db", log_path=log)

    assert "warning=Sheet no disponible" in log.read_text(encoding="utf-8")


def test_main_error_loguea_y_regresa_1(tmp_path, monkeypatch) -> None:
    log = tmp_path / "sync_metrics.log"

    def revienta(cx):
        raise RuntimeError("Graph API 500")

    monkeypatch.setattr(ig_insights, "sync_posts", revienta)

    code = ig_insights.main(db_path=tmp_path / "t.db", log_path=log)

    assert code == 1
    linea = log.read_text(encoding="utf-8").strip()
    assert "ERROR" in linea
    assert "Graph API 500" in linea


# ---------- generador del plist ----------

@pytest.mark.skipif(shutil.which("bash") is None, reason="bash no disponible")
def test_script_sintaxis_valida() -> None:
    r = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.mark.skipif(shutil.which("plutil") is None, reason="plutil es de macOS")
def test_plist_generado_es_valido_y_tiene_rutas(tmp_path) -> None:
    dest = tmp_path / "com.gdlscene.sync-metrics.plist"
    env = {**os.environ, "PLIST_DEST": str(dest)}

    r = subprocess.run(["bash", str(SCRIPT), "--solo-generar"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    assert dest.exists()

    # plutil -lint confirma XML/plist bien formado.
    lint = subprocess.run(["plutil", "-lint", str(dest)], capture_output=True, text=True)
    assert lint.returncode == 0, lint.stdout + lint.stderr

    data = plistlib.loads(dest.read_bytes())
    venv_py = str(REPO / ".venv" / "bin" / "python")
    assert data["ProgramArguments"] == [venv_py, "-m", "src.ig_insights"]
    assert data["WorkingDirectory"] == str(REPO)
    assert data["StartCalendarInterval"] == {"Hour": 21, "Minute": 30}
    log = str(REPO / "data" / "launchd_sync.log")
    assert data["StandardOutPath"] == log
    assert data["StandardErrorPath"] == log
    assert data["Label"] == "com.gdlscene.sync-metrics"
