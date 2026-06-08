"""Tests de fusión de eventos: misma fecha + mismo foro = un evento, varias bandas."""
from __future__ import annotations

from src.generate_agenda import _norm_venue, agrupar_por_evento


def test_norm_venue_tolera_acentos_y_typos() -> None:
    assert _norm_venue("Foro Boletomóvil") == _norm_venue("Foro Boletomovil")
    assert _norm_venue("  C3   STAGE!! ") == "c3 stage"
    assert _norm_venue(None) == ""


def _ev(i, fecha, banda, lugar, handle=None):
    return {"id": i, "fecha_evento": fecha, "banda_nombre": banda,
            "lugar": lugar, "banda_handle": handle}


def test_dos_bandas_mismo_evento_se_fusionan() -> None:
    evs = [
        _ev(1, "2026-06-14", "Cuerda", "Garibaldi #580", "cuerda"),
        _ev(2, "2026-06-14", "Cuerda Cultura Medios", "Garibaldi #580", "cuerdacmedios"),
    ]
    g = agrupar_por_evento(evs)
    assert len(g) == 1
    assert g[0]["banda_nombre"] == "Cuerda · Cuerda Cultura Medios"
    assert g[0]["lugar"] == "Garibaldi #580"
    assert set(g[0]["handles"]) == {"cuerda", "cuerdacmedios"}


def test_misma_banda_flyer_repetido_se_colapsa() -> None:
    evs = [
        _ev(1, "2026-06-05", "Duck Fizz", "Foro Boletomóvil"),
        _ev(2, "2026-06-05", "Duck Fizz", "Foro Boletomovil"),  # typo del OCR
    ]
    g = agrupar_por_evento(evs)
    assert len(g) == 1
    assert g[0]["banda_nombre"] == "Duck Fizz"   # una sola vez


def test_distinto_foro_o_fecha_no_se_fusiona() -> None:
    evs = [
        _ev(1, "2026-06-05", "A", "Foro X"),
        _ev(2, "2026-06-05", "B", "Foro Y"),      # otro foro
        _ev(3, "2026-06-06", "C", "Foro X"),      # otra fecha
    ]
    assert len(agrupar_por_evento(evs)) == 3


def test_sin_lugar_no_se_fusiona() -> None:
    evs = [_ev(1, "2026-06-05", "A", None), _ev(2, "2026-06-05", "B", None)]
    assert len(agrupar_por_evento(evs)) == 2  # sin foro no hay forma de saber si es el mismo


def test_al_final_ordena_ultimo(tmp_path):
    from datetime import datetime

    import pytz

    import config
    from src import db
    from src.generate_agenda import eventos_ventana
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="B")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 5, 12, 0))
    # CDMX (al_final) con fecha TEMPRANA; local con fecha posterior
    db.insert(cx, "events", band_id=bid, tipo="fecha", fecha_evento="2026-06-06",
              lugar="CDMX", al_final=1)
    db.insert(cx, "events", band_id=bid, tipo="fecha", fecha_evento="2026-06-10", lugar="GDL")
    evs = eventos_ventana(cx, 7, hoy=hoy)
    # el local (al_final=0) va primero aunque su fecha sea posterior; CDMX al final
    assert evs[0]["lugar"] == "GDL"
    assert evs[-1]["lugar"] == "CDMX"
    cx.close()
