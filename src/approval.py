"""Flujo de aprobación ASÍNCRONO (no bloqueante).

Los generadores ENCOLAN propuestas (status borrador + aprobacion pendiente) y
mandan a Telegram con botones vía sendMessage directo — sin poller. El daemon
(único poller) resuelve: aprobar → elige slot de alto tráfico, escribe el Sheet
approved y marca en_sheet; rechazar → descartado. publish.py publica luego.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from src import db, timing


def encolar_pendiente(cx, *, tipo: str, caption: str, imagen_url: str,
                      band_id: int | None = None, member_id: int | None = None,
                      photo_id: int | None = None, event_id: int | None = None,
                      template: str | None = None, formato_patron: str | None = None,
                      tema_semilla: str | None = None, account_id: int = 1) -> int:
    """Crea el item pendiente de aprobación. Devuelve queue_id.

    status sigue su ciclo normal ('borrador'); la compuerta humana vive en la
    columna separada 'aprobacion' (la DB tiene CHECK fijo en status).
    """
    return db.insert(cx, "content_queue", tipo=tipo, status="borrador",
                     aprobacion="pendiente", caption=caption, imagen_url=imagen_url,
                     band_id=band_id, member_id=member_id, photo_id=photo_id,
                     event_id=event_id, template=template, formato_patron=formato_patron,
                     tema_semilla=tema_semilla, account_id=account_id)


def aprobar(cx, queue_id: int, *, ahora: datetime | None = None,
            ventana_trafico: str = "meme", audiencia: list[dict[str, Any]] | None = None,
            _escribir_sheet: Callable[..., int] | None = None) -> datetime:
    """Aprueba: elige slot de alto tráfico, escribe Sheet approved, marca en_sheet."""
    ahora = ahora or datetime.now()
    fila = db.get(cx, "content_queue", queue_id)
    slot = timing.elegir_slot(ventana_trafico, ahora, audiencia=audiencia or [])
    escribir = _escribir_sheet or _sheet_real
    sheet_id = escribir(caption=fila.get("caption"),
                        imagen=fila.get("imagen_url"),
                        scheduled=slot.isoformat())
    db.update(cx, "content_queue", queue_id, aprobacion="aprobado", status="en_sheet",
              sheet_row_id=str(sheet_id), scheduled_datetime=slot.isoformat())
    return slot


def rechazar(cx, queue_id: int) -> None:
    db.update(cx, "content_queue", queue_id, aprobacion="rechazado", status="descartado")


def _sheet_real(*, caption, imagen, scheduled) -> int:
    """Escribe la fila approved en el Sheet (igual que generate_agenda)."""
    from src import sheets
    return sheets.append_row(banda="@gdlscene", caption_generado=caption,
                             caption_final=caption, imagen_compuesta_url=imagen,
                             status=sheets.STATUS_APPROVED, scheduled_datetime=scheduled)


# --------- Telegram: helpers PUROS + envío (sin poller) ---------

def construir_botones(queue_id: int) -> list[list[dict[str, str]]]:
    """Payload de teclado inline (Aprobar/Rechazar) como dict puro. PURO/testeable.

    Devuelve el array `inline_keyboard` listo para reply_markup; el daemon lo
    parsea de vuelta con `parsear_callback`.
    """
    return [[
        {"text": "✅ Aprobar", "callback_data": f"aprobar:{queue_id}"},
        {"text": "❌ Rechazar", "callback_data": f"rechazar:{queue_id}"},
    ]]


def parsear_callback(data: str) -> tuple[str, int]:
    """'aprobar:123' → ('aprobar', 123). PURO/testeable. Lanza si la acción no es válida."""
    accion, _, qid = data.partition(":")
    if accion not in ("aprobar", "rechazar"):
        raise ValueError(f"Acción de callback desconocida: {accion!r}")
    return accion, int(qid)


def enviar_a_telegram(caption: str, imagen_url: str, queue_id: int) -> None:
    """sendMessage con los 2 botones inline (sin poller). Lo usan los generadores.

    Manda el caption + el link de la imagen y el teclado Aprobar/Rechazar. El
    daemon (único poller) recibe el callback y resuelve.
    """
    import json

    import requests

    import config

    # requests (no urllib): trae certifi, así no truena con el cert verify de la
    # red de Ricardo (el resolver/proxy mete un cert que urllib rechaza).
    texto = f"{caption}\n\n{imagen_url}".strip()
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": texto,
        "reply_markup": json.dumps({"inline_keyboard": construir_botones(queue_id)}),
    }
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    r = requests.post(url, data=payload, timeout=15)
    r.raise_for_status()
