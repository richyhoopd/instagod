"""Comandos de reply del flujo interactivo (texto:/feedback: sobre la foto del bot).

Solo el núcleo PURO (parse_reply_command); el handler async no se testea,
igual que el resto de la cáscara de polling.
"""
from __future__ import annotations

import bot


def test_parse_texto_exacto() -> None:
    assert bot.parse_reply_command("texto: Mi titular exacto") == \
        ("texto", "Mi titular exacto")


def test_parse_feedback() -> None:
    assert bot.parse_reply_command("Feedback: más corto y sobre el bajista") == \
        ("feedback", "más corto y sobre el bajista")


def test_parse_ignora_texto_normal() -> None:
    assert bot.parse_reply_command("jajaja buenísimo") is None
    assert bot.parse_reply_command("") is None
    assert bot.parse_reply_command(None) is None


def test_parse_comando_vacio_es_none() -> None:
    # "texto:" sin contenido no debe disparar nada.
    assert bot.parse_reply_command("texto:   ") is None
