"""Vista de segmentos para la GUI: estado, pendientes y preview de contenido."""
from __future__ import annotations

from datetime import datetime

import pytest

from src import db, segments
from src import segments_vista as sv


@pytest.fixture()
def cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    yield cx
    cx.close()


def _seg(clave="agenda_semanal", dow=1):
    cadencia = ({"tipo": "mensual", "dia_mes": 1} if clave.endswith("_mensual")
                else {"tipo": "semanal", "dow": dow})
    return segments.Segment(clave, clave, lambda cx, acc: None,
                            cadencia=cadencia, ventana_trafico="meme")


# ---------- cadencia humana / próxima corrida (PURO) ----------

def test_cadencia_humana() -> None:
    assert sv.cadencia_humana(_seg("agenda_semanal", dow=1)) == "cada martes"
    assert sv.cadencia_humana(_seg("releases_mensual")) == "el día 1 de cada mes"


def test_proxima_corrida_semanal() -> None:
    # miércoles 10-jun → el próximo martes es 16-jun
    prox = sv.proxima_corrida(_seg("agenda_semanal", dow=1), datetime(2026, 6, 10, 12, 0))
    assert prox.strftime("%Y-%m-%d") == "2026-06-16"


def test_proxima_corrida_hoy_si_toca() -> None:
    # martes 9-jun a mediodía → toca HOY
    prox = sv.proxima_corrida(_seg("agenda_semanal", dow=1), datetime(2026, 6, 9, 12, 0))
    assert prox.strftime("%Y-%m-%d") == "2026-06-09"


def test_proxima_corrida_mensual() -> None:
    prox = sv.proxima_corrida(_seg("releases_mensual"), datetime(2026, 6, 10, 12, 0))
    assert prox.strftime("%Y-%m-%d") == "2026-07-01"


# ---------- vista completa contra DB ----------

def test_vista_releases_gate_de_frescura(cx) -> None:
    bid = db.insert(cx, "bands", nombre="Kabala", ig_handle="kabala", activa=1)
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Single A",
              fecha_evento="2026-06-09", status="nuevo")
    db.insert(cx, "events", band_id=bid, tipo="release", titulo="Single B",
              fecha_evento="2026-06-08", status="anunciado")  # NO fresco

    vista = sv.vista_segmentos(cx, [_seg("releases_semanal", dow=4)],
                               ahora=datetime(2026, 6, 10, 12, 0))
    v = vista[0]
    assert v["clave"] == "releases_semanal"
    # semanal = solo frescos: 1 de 2 → bajo el mínimo de 3 → no se genera
    assert v["preview"]["frescos"] == 1
    assert v["preview"]["se_genera"] is False
    titulos = [e["titulo"] for e in v["preview"]["eventos"]]
    assert titulos == ["Single A"]


def test_vista_shows_eventos_y_flyers(cx) -> None:
    bid = db.insert(cx, "bands", nombre="Karacel", ig_handle="karacel", activa=1)
    db.insert(cx, "events", band_id=bid, tipo="fecha", titulo="Tocada",
              fecha_evento="2026-06-12", lugar="Foro X", status="nuevo")

    vista = sv.vista_segmentos(cx, [_seg("agenda_semanal", dow=1)],
                               ahora=datetime(2026, 6, 10, 12, 0))
    v = vista[0]
    evs = v["preview"]["eventos"]
    assert len(evs) == 1 and evs[0]["banda"] == "Karacel"
    # sin flyer_path no hay slide: el carrusel no se genera
    assert evs[0]["tiene_flyer"] is False
    assert v["preview"]["flyers_usables"] == 0
    assert v["preview"]["se_genera"] is False


def test_vista_estado_y_pendientes(cx) -> None:
    # corrida registrada en la ventana actual + item pendiente en la cola
    db.insert(cx, "segment_runs", segmento="agenda_semanal", account_id=1,
              ventana="2026-W24")
    db.insert(cx, "content_queue", tipo="anuncio", status="borrador",
              aprobacion="pendiente", caption="La agenda de la semana…",
              imagen_url='["https://x/1.png", "https://x/2.png"]',
              tema_semilla="shows semanal pt1")

    vista = sv.vista_segmentos(cx, [_seg("agenda_semanal", dow=1)],
                               ahora=datetime(2026, 6, 10, 12, 0))
    v = vista[0]
    assert v["ya_corrio"] is True
    assert len(v["pendientes"]) == 1
    p = v["pendientes"][0]
    assert p["caption"].startswith("La agenda")
    assert p["urls"] == ["https://x/1.png", "https://x/2.png"]
