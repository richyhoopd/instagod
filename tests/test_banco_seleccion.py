# tests/test_banco_seleccion.py
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytz

import config
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


def test_personas_recientes_default_es_timezone_aware(cx, monkeypatch) -> None:
    """El default de `ahora` debe usar config.TIMEZONE, no datetime.now() naive.

    Mismo bug que ya mordió a approval.aprobar (ver src/approval.py:44): si la
    máquina reporta la hora en otro huso y el default cae a datetime.now() sin
    tz, el corte de la ventana se calcula sobre un instante distinto al resto
    del motor y compara mal contra scheduled_datetime (que SIEMPRE se guarda
    tz-aware). Aquí simulamos ese desfase: now(tz=CDMX) da mediodía correcto,
    pero now() naive (lo que devolvería un host en otro huso) da las 22:00.
    """
    bid, p1, _, f1, _ = _banda_con_dos_personas(cx)
    tz = pytz.timezone(config.TIMEZONE)

    class _FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 8, 3, 12, 0)
            return tz.localize(base) if tz else datetime(2026, 8, 3, 22, 0)

    monkeypatch.setattr(planner, "datetime", _FakeDT)

    ahora_correcto = tz.localize(datetime(2026, 8, 3, 12, 0))
    # 45 días - 6h antes del mediodía CDMX: dentro de la ventana SOLO si el
    # corte usa el "ahora" tz-aware correcto (12:00), no el naive (22:00).
    scheduled = ahora_correcto - timedelta(days=45) + timedelta(hours=6)
    db.insert(cx, "content_queue", tipo="meme", band_id=bid, photo_id=f1,
              status="publicado", scheduled_datetime=scheduled.isoformat())

    assert planner.personas_recientes(cx, dias=45) == {p1}


def test_sin_persona_sigue_funcionando(cx) -> None:
    """Fotos sin cara (foro) no se excluyen: persona_id NULL nunca es 'reciente'."""
    bid = db.insert(cx, "bands", nombre="Foro", ig_handle="f", tipo="foro", prioridad=1)
    fid = db.insert(cx, "photos", band_id=bid, path="x.jpg", source_post_id="x",
                    usable_meme=1, nitidez=50.0)
    sel = planner.seleccionar(cx, max_posts=1, ahora=datetime(2026, 8, 3))
    assert [f["photo_id"] for f in sel] == [fid]
