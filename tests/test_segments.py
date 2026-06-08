"""Registro de segmentos: cadencia (toca_hoy) y claves de ventana (idempotencia).

Funciones PURAS de calendario. Deciden si un formato recurrente debe encolarse
hoy y bajo qué clave de período, lo que evita duplicar propuestas en la cola.
"""
from __future__ import annotations

from datetime import datetime

from src.segments import (
    Segment,
    toca_hoy,
    ventana_actual,
    ventana_de,
    ventana_mensual,
)


def _seg(tipo, **cad):
    cad["tipo"] = tipo
    return Segment(clave="x" + ("_mensual" if tipo == "mensual" else "_semanal"),
                   nombre="X", generador=lambda cx, aid: None,
                   cadencia=cad, ventana_trafico="meme")


# ---------- toca_hoy ----------

def test_diario_siempre_toca() -> None:
    seg = _seg("diario")
    for dia in range(1, 9):
        assert toca_hoy(seg, datetime(2026, 6, dia)) is True


def test_semanal_solo_su_dia() -> None:
    ahora = datetime(2026, 6, 10, 20, 0)        # un miércoles cualquiera
    dow = ahora.weekday()
    assert toca_hoy(_seg("semanal", dow=dow), ahora) is True
    assert toca_hoy(_seg("semanal", dow=(dow + 1) % 7), ahora) is False


def test_mensual_solo_su_dia_de_mes() -> None:
    assert toca_hoy(_seg("mensual", dia_mes=10), datetime(2026, 6, 10)) is True
    assert toca_hoy(_seg("mensual", dia_mes=10), datetime(2026, 6, 11)) is False
    # default dia_mes=1 cuando no se especifica
    assert toca_hoy(_seg("mensual"), datetime(2026, 6, 1)) is True
    assert toca_hoy(_seg("mensual"), datetime(2026, 6, 2)) is False


def test_cadencia_desconocida_no_toca() -> None:
    assert toca_hoy(_seg("anual"), datetime(2026, 6, 1)) is False


# ---------- ventanas (claves de idempotencia) ----------

def test_ventana_mensual_formato() -> None:
    assert ventana_mensual(datetime(2026, 6, 8)) == "2026-06"
    assert ventana_mensual(datetime(2026, 12, 1)) == "2026-12"


def test_ventana_de_semanal_vs_mensual_por_sufijo() -> None:
    ahora = datetime(2026, 6, 8)
    assert ventana_de("agenda_mensual", ahora) == "2026-06"   # sufijo _mensual
    sem = ventana_de("agenda_semanal", ahora)
    assert sem.startswith("2026-W")                            # ISO week


def test_ventana_actual_usa_mensual_si_cadencia_mensual() -> None:
    ahora = datetime(2026, 6, 8)
    assert ventana_actual(_seg("mensual", dia_mes=1), ahora) == "2026-06"
    assert ventana_actual(_seg("semanal", dow=0), ahora).startswith("2026-W")
