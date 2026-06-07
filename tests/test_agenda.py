"""Tests de la agenda: ventana de fechas (nunca pasados) y armado del digest."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytz

import config
from src import db
from src.generate_agenda import (
    _fila_tarjeta,
    _rango_releases,
    _rango_shows,
    eventos_ventana,
    releases_ventana,
)


def _cx(tmp_path):
    cx = db.connect(tmp_path / "t.db")
    db.init_db(cx)
    return cx


def test_ventana_excluye_pasados_y_lejanos(tmp_path) -> None:
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Kabala")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 4, 12, 0))

    def ev(delta_dias: int, **extra):
        return db.insert(cx, "events", band_id=bid, tipo="fecha",
                         fecha_evento=(hoy + timedelta(days=delta_dias)).strftime("%Y-%m-%d"),
                         **extra)

    ev(-1)                       # ayer → fuera (regla: nunca flyers pasados)
    e_hoy = ev(0)                # hoy → dentro
    e_semana = ev(6)             # dentro de la semana
    e_mes = ev(25)               # solo en la mensual
    ev(31)                       # fuera incluso de la mensual
    ev(3, status="pasado")       # status pasado → fuera aunque la fecha sea futura

    semanal = [e["id"] for e in eventos_ventana(cx, 7, hoy=hoy)]
    mensual = [e["id"] for e in eventos_ventana(cx, 30, hoy=hoy)]
    assert semanal == [e_hoy, e_semana]
    assert mensual == [e_hoy, e_semana, e_mes]
    cx.close()


def test_ventana_incluye_anunciados(tmp_path) -> None:
    """La agenda lista todo lo vigente, esté o no anunciado individualmente."""
    cx = _cx(tmp_path)
    bid = db.insert(cx, "bands", nombre="Los Baxters")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 4, 12, 0))
    db.insert(cx, "events", band_id=bid, tipo="fecha", status="anunciado",
              fecha_evento="2026-06-19")
    assert len(eventos_ventana(cx, 30, hoy=hoy)) == 1
    cx.close()


def test_fila_tarjeta_shows() -> None:
    fila = _fila_tarjeta({"fecha_evento": "2026-06-19", "banda_nombre": "Los Baxters",
                          "lugar": "Anexo Independencia", "ciudad": "Guadalajara"}, "shows")
    assert fila["banda"] == "Los Baxters" and fila["dia"] == "19" and fila["mes"] == "jun"
    assert fila["lugar"] == "Anexo Independencia · Guadalajara"
    assert fila["cover"] == ""  # shows no llevan portada
    sin_lugar = _fila_tarjeta({"fecha_evento": "2026-07-01", "banda_nombre": "Kabala",
                               "lugar": None, "ciudad": None}, "shows")
    assert sin_lugar["lugar"] == "" and sin_lugar["mes"] == "jul"


def test_fila_tarjeta_releases_usa_titulo_y_portada() -> None:
    fila = _fila_tarjeta({"fecha_evento": "2026-05-29", "banda_nombre": "SilentNoir",
                          "titulo": "Ecos (álbum)", "cover_url": "http://x/c.jpg",
                          "lugar": "ignorar", "ciudad": "X"}, "releases")
    assert fila["banda"] == "SilentNoir" and fila["lugar"] == "Ecos (álbum)"
    assert fila["cover"] == "http://x/c.jpg"


def test_releases_ventana_mira_al_pasado() -> None:
    import sqlite3, tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd)
    cx = db.connect(path)
    db.init_db(cx)
    bid = db.insert(cx, "bands", nombre="SilentNoir")
    hoy = pytz.timezone(config.TIMEZONE).localize(datetime(2026, 6, 5, 12, 0))
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-05-29",
              titulo="Ecos (álbum)")          # hace 7 días → dentro de mensual y semanal
    db.insert(cx, "events", band_id=bid, tipo="release", fecha_evento="2026-04-01")  # viejo
    db.insert(cx, "events", band_id=bid, tipo="fecha", fecha_evento="2026-05-29")    # show, no release
    semanal = releases_ventana(cx, 7, hoy=hoy)
    mensual = releases_ventana(cx, 30, hoy=hoy)
    assert len(semanal) == 1 and semanal[0]["titulo"] == "Ecos (álbum)"
    assert len(mensual) == 1   # el de abril queda fuera de 30 días
    cx.close()


def test_chunks_para_slider() -> None:
    from src.generate_agenda import _MAX_EN_TARJETA, _chunks
    items = list(range(25))
    slides = _chunks(items, _MAX_EN_TARJETA)
    assert sum(len(s) for s in slides) == 25      # no se pierde ninguno
    assert all(len(s) <= _MAX_EN_TARJETA for s in slides)
    assert len(slides) >= 3                         # 25 no cabe en una slide
    assert _chunks([], 10) == [[]]                  # vacío → una slide vacía


def test_carousel_urls_detecta_json(tmp_path) -> None:
    from publish import _carousel_urls
    assert _carousel_urls('["http://a.jpg","http://b.jpg"]') == ["http://a.jpg", "http://b.jpg"]
    assert _carousel_urls("https://res.cloudinary.com/x.png") == []  # url simple
    assert _carousel_urls("") == []


def test_rango_shows_y_releases() -> None:
    hoy = datetime(2026, 6, 4)
    assert _rango_shows(hoy, 7) == "4 al 11 de junio"
    assert _rango_shows(hoy, 30) == "4 de junio al 4 de julio"
    assert _rango_releases(hoy, 7) == "28 de mayo al 4 de junio"
