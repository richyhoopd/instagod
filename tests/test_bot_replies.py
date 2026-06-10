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


# ---------- Álbum de 2 fotos: principal + inset (circulito) ----------

def test_partir_album_caption_en_primera() -> None:
    fotos = [{"message_id": 10, "caption": "Kabala, Joss, bajista"},
             {"message_id": 11, "caption": None}]
    principal, inset = bot.partir_album(fotos)
    assert principal["message_id"] == 10
    assert inset["message_id"] == 11


def test_partir_album_caption_en_segunda() -> None:
    # Telegram pone la descripción en la foto donde la escribiste: esa manda.
    fotos = [{"message_id": 10, "caption": None},
             {"message_id": 11, "caption": "Kabala, Joss, bajista"}]
    principal, inset = bot.partir_album(fotos)
    assert principal["message_id"] == 11
    assert inset["message_id"] == 10


def test_partir_album_sin_caption_usa_orden() -> None:
    fotos = [{"message_id": 11, "caption": None}, {"message_id": 10, "caption": None}]
    principal, inset = bot.partir_album(fotos)
    assert principal["message_id"] == 10 and inset["message_id"] == 11


def test_partir_album_foto_unica_sin_inset() -> None:
    principal, inset = bot.partir_album([{"message_id": 5, "caption": "x"}])
    assert principal["message_id"] == 5 and inset is None
