"""Tests de fusión de eventos: misma fecha + mismo foro (venue_id) = un evento, varias bandas."""
from __future__ import annotations

from src.generate_agenda import agrupar_por_evento


def _ev(i, fecha, venue_id, banda, handle=None, lugar="lo que sea"):
    return {"id": i, "fecha_evento": fecha, "venue_id": venue_id,
            "lugar": lugar, "banda_nombre": banda, "banda_handle": handle}


def test_dos_bandas_mismo_evento_se_fusionan() -> None:
    evs = [
        _ev(1, "2026-06-14", 1, "Cuerda", "cuerda", lugar="Garibaldi #580"),
        _ev(2, "2026-06-14", 1, "Cuerda Cultura Medios", "cuerdacmedios", lugar="Garibaldi #580"),
    ]
    g = agrupar_por_evento(evs)
    assert len(g) == 1
    assert g[0]["banda_nombre"] == "Cuerda · Cuerda Cultura Medios"
    assert g[0]["lugar"] == "Garibaldi #580"
    assert set(g[0]["handles"]) == {"cuerda", "cuerdacmedios"}


def test_misma_banda_flyer_repetido_se_colapsa() -> None:
    evs = [
        _ev(1, "2026-06-05", 2, "Duck Fizz", lugar="Foro Boletomóvil"),
        _ev(2, "2026-06-05", 2, "Duck Fizz", lugar="Foro Boletomovil"),  # typo del OCR, mismo venue_id
    ]
    g = agrupar_por_evento(evs)
    assert len(g) == 1
    assert g[0]["banda_nombre"] == "Duck Fizz"   # una sola vez


def test_distinto_foro_o_fecha_no_se_fusiona() -> None:
    evs = [
        _ev(1, "2026-06-05", 1, "A", lugar="Foro X"),
        _ev(2, "2026-06-05", 2, "B", lugar="Foro Y"),      # otro foro
        _ev(3, "2026-06-06", 1, "C", lugar="Foro X"),      # otra fecha
    ]
    assert len(agrupar_por_evento(evs)) == 3


def test_sin_lugar_no_se_fusiona() -> None:
    evs = [_ev(1, "2026-06-05", None, "A", lugar=None), _ev(2, "2026-06-05", None, "B", lugar=None)]
    assert len(agrupar_por_evento(evs)) == 2  # sin foro no hay forma de saber si es el mismo


def test_agrupa_por_venue_id_aunque_el_texto_difiera() -> None:
    """El caso real del 23-ago: 'REY' y 'Hake al Rey' resuelven al mismo foro."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "SilentNoir", "silentnoirofficial"),
        _ev(2, "2026-08-23", 7, "Hake Al Rey", "hakealrey"),
    ])
    assert len(grupos) == 1
    assert set(grupos[0]["handles"]) == {"silentnoirofficial", "hakealrey"}
    assert grupos[0]["ids"] == [1, 2]


def test_no_agrupa_venues_distintos() -> None:
    """Salas distintas son foros distintos: C3 Stage y C3 Rooftop no se funden."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a"),
        _ev(2, "2026-08-23", 8, "B", "b"),
    ])
    assert len(grupos) == 2


def test_sin_venue_id_fusiona_si_el_lugar_normaliza_igual() -> None:
    """Respaldo por texto: el dedup que ya corría en producción antes del
    catálogo. Comparar dos cadenas idénticas no es adivinar."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", None, "A", "a", lugar="Foro Anexo Independencia"),
        _ev(2, "2026-08-23", None, "B", "b", lugar="ANEXO INDEPENDENCIA"),
    ])
    assert len(grupos) == 1
    assert set(grupos[0]["handles"]) == {"a", "b"}


def test_sin_venue_id_no_fusiona_lugares_distintos() -> None:
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", None, "A", "a", lugar="Foro X"),
        _ev(2, "2026-08-23", None, "B", "b", lugar="Foro Y"),
    ])
    assert len(grupos) == 2


def test_sin_venue_id_ni_lugar_cada_evento_va_solo() -> None:
    """La cadena vacía es 'no hay lugar': no puede fusionar a todos entre sí."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", None, "A", "a", lugar=None),
        _ev(2, "2026-08-23", None, "B", "b", lugar=""),
        _ev(3, "2026-08-23", None, "C", "c", lugar="   "),
    ])
    assert len(grupos) == 3


def test_venue_id_manda_sobre_el_texto_del_lugar() -> None:
    """Con foro resuelto, el texto no opina: ni fusiona lo que el catálogo
    separó (C3 Stage vs C3 Rooftop mal escritos) ni separa lo que unió."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a", lugar="C3"),
        _ev(2, "2026-08-23", 8, "B", "b", lugar="C3"),      # mismo texto, otro foro
    ])
    assert len(grupos) == 2
    juntos = agrupar_por_evento([
        _ev(3, "2026-08-23", 7, "A", "a", lugar="REY"),
        _ev(4, "2026-08-23", 7, "B", "b", lugar="Hake al Rey"),
    ])
    assert len(juntos) == 1


def test_un_evento_con_venue_id_no_se_mezcla_con_uno_sin_el() -> None:
    """Claves de ramas distintas nunca colisionan (el discriminante)."""
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a", lugar="Hake Al Rey"),
        _ev(2, "2026-08-23", None, "B", "b", lugar="Hake Al Rey"),
    ])
    assert len(grupos) == 2


def test_no_agrupa_fechas_distintas() -> None:
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a"),
        _ev(2, "2026-08-24", 7, "B", "b"),
    ])
    assert len(grupos) == 2


def test_no_repite_la_misma_banda() -> None:
    grupos = agrupar_por_evento([
        _ev(1, "2026-08-23", 7, "A", "a"),
        _ev(2, "2026-08-23", 7, "A", "a"),
    ])
    assert grupos[0]["bandas"] == ["A"]
    assert grupos[0]["ids"] == [1, 2]


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
