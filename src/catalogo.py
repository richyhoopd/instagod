"""Catálogo real de segmentos registrados en el motor (lo lee el dispatcher)."""
from __future__ import annotations

from functools import partial

from src.generate_agenda import generar_segmento_agenda
from src.segments import Segment

REGISTRO = [
    Segment("agenda_semanal", "Agenda — esta semana",
            partial(generar_segmento_agenda, periodo="semanal", modo="shows"),
            cadencia={"tipo": "semanal", "dow": 1}, ventana_trafico="agenda_semanal"),
    Segment("agenda_mensual", "Agenda — este mes",
            partial(generar_segmento_agenda, periodo="mensual", modo="shows"),
            cadencia={"tipo": "mensual", "dia_mes": 1}, ventana_trafico="agenda_mensual"),
    Segment("releases_semanal", "Música nueva — semana",
            partial(generar_segmento_agenda, periodo="semanal", modo="releases"),
            cadencia={"tipo": "semanal", "dow": 4}, ventana_trafico="releases_semanal"),
    Segment("releases_mensual", "Música nueva — mes",
            partial(generar_segmento_agenda, periodo="mensual", modo="releases"),
            cadencia={"tipo": "mensual", "dia_mes": 1}, ventana_trafico="releases_mensual"),
]
