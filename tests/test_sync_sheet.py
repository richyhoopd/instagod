"""Sync cola ↔ Sheet: aislamiento por cuenta en `pull_status`.

Los ids de fila del Sheet son auto-incrementales POR HOJA: dos marcas
distintas pueden tener filas con el mismo sheet_row_id. pull_status solo lee
el Sheet de gdlscene (v1), así que debe ignorar cualquier fila de
content_queue que no sea de esa cuenta (account_id != 1), aunque su
sheet_row_id coincida con uno del Sheet leído.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src import db, sheets, sync_sheet


@pytest.fixture()
def cx(tmp_path: Path):
    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    yield conn
    conn.close()


def test_pull_status_ignora_filas_de_otra_cuenta(cx, monkeypatch) -> None:
    # gdlscene (account_id=1): sheet_row_id "7" → debe actualizarse.
    qid_gdl = db.insert(cx, "content_queue", account_id=1,
                        status=db.QUEUE_EN_SHEET, sheet_row_id="7")
    # otra marca (account_id=2): MISMO sheet_row_id "7" por colisión entre
    # Sheets — no debe tocarse aunque el Sheet leído (de gdlscene) tenga esa
    # fila como publicada.
    qid_otra = db.insert(cx, "content_queue", account_id=2,
                         status=db.QUEUE_EN_SHEET, sheet_row_id="7")

    monkeypatch.setattr(sheets, "_records",
                        lambda: [{"id": "7", "status": sheets.STATUS_PUBLISHED}])

    cambios = sync_sheet.pull_status(cx)

    assert cambios == 1
    assert db.get(cx, "content_queue", qid_gdl)["status"] == db.QUEUE_PUBLICADO
    assert db.get(cx, "content_queue", qid_otra)["status"] == db.QUEUE_EN_SHEET
