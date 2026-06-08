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
                      tema_semilla: str | None = None, account_id: int = 1,
                      evento_ids: str | None = None) -> int:
    """Crea el item pendiente de aprobación. Devuelve queue_id.

    status sigue su ciclo normal ('borrador'); la compuerta humana vive en la
    columna separada 'aprobacion' (la DB tiene CHECK fijo en status).

    evento_ids: JSON list de events.id incluidos en el carrusel, para marcarlos
    'anunciado' al aprobar (motor de frescura, Task X2).
    """
    return db.insert(cx, "content_queue", tipo=tipo, status="borrador",
                     aprobacion="pendiente", caption=caption, imagen_url=imagen_url,
                     band_id=band_id, member_id=member_id, photo_id=photo_id,
                     event_id=event_id, template=template, formato_patron=formato_patron,
                     tema_semilla=tema_semilla, account_id=account_id,
                     evento_ids=evento_ids)


def aprobar(cx, queue_id: int, *, ahora: datetime | None = None,
            ventana_trafico: str = "meme", audiencia: list[dict[str, Any]] | None = None,
            _escribir_sheet: Callable[..., int] | None = None,
            _publicar: Callable[[], None] | None = None) -> datetime:
    """Aprueba: elige slot o publica inmediato (anuncios), escribe Sheet, marca en_sheet."""
    # OJO timezone: usar la hora de la cuenta (config.TIMEZONE), NO datetime.now()
    # naive. La máquina puede estar en otro huso (+04) y el "inmediato" saldría
    # con fecha futura que get_due_rows (que compara en CST) nunca ve vencida.
    if ahora is None:
        import pytz
        import config
        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
    fila = db.get(cx, "content_queue", queue_id)
    # Anuncios/agendas se publican de inmediato; memes se calendarizan en slot de alto tráfico.
    inmediato = fila.get("tipo") == "anuncio"
    if inmediato:
        slot = ahora
    else:
        slot = timing.elegir_slot(ventana_trafico, ahora, audiencia=audiencia or [])
    escribir = _escribir_sheet or _sheet_real
    sheet_id = escribir(caption=fila.get("caption"),
                        imagen=fila.get("imagen_url"),
                        scheduled=slot.isoformat())
    db.update(cx, "content_queue", queue_id, aprobacion="aprobado", status="en_sheet",
              sheet_row_id=str(sheet_id), scheduled_datetime=slot.isoformat())
    # Motor de frescura: los releases incluidos en el carrusel quedan 'anunciado'
    # para que el semanal solo-fresco no los vuelva a publicar.
    if fila.get("evento_ids"):
        import json
        for eid in json.loads(fila["evento_ids"]):
            db.update(cx, "events", eid, status="anunciado")
    if inmediato:
        (_publicar or _publicar_ahora)()
    return slot


def _publicar_ahora() -> None:
    """Dispara publish.py como subproceso desacoplado (no bloquea el callback de Telegram)."""
    import subprocess
    import sys

    import config
    try:
        subprocess.Popen(
            [sys.executable, str(config.BASE_DIR / "publish.py")],
            cwd=str(config.BASE_DIR),
        )
    except OSError as e:
        import sys as _sys
        print(f"[approval] No se pudo lanzar publish.py: {e}", file=_sys.stderr)


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


def _urls_de_imagen(imagen_url: str) -> list[str]:
    """Parsea imagen_url: JSON-lista → list; string plano → [string]; vacío → []. PURO."""
    import json
    if not imagen_url:
        return []
    try:
        parsed = json.loads(imagen_url)
        if isinstance(parsed, list):
            return parsed
        # json.loads de una cadena sin comillas extras devuelve str
        return [imagen_url]
    except (json.JSONDecodeError, ValueError):
        return [imagen_url]


def enviar_a_telegram(caption: str, imagen_url: str, queue_id: int) -> None:
    """Manda la propuesta a Telegram con botones Aprobar/Rechazar.

    - Carrusel (>=2 URLs): sendMediaGroup con las fotos, luego sendMessage con
      caption + botones (Telegram no permite botones en media groups).
    - Single (1 URL): sendPhoto con caption + botones.
    - Sin imagen: sendMessage solo texto + botones (fallback).

    Usa requests (trae certifi, sin problemas de certs de red).
    """
    import json

    import requests

    import config

    base_url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}"
    chat_id = config.TELEGRAM_CHAT_ID
    botones = {"inline_keyboard": construir_botones(queue_id)}
    urls = _urls_de_imagen(imagen_url)

    if len(urls) >= 2:
        # Enviar fotos como álbum
        media = [{"type": "photo", "media": u} for u in urls[:10]]
        r = requests.post(
            f"{base_url}/sendMediaGroup",
            data={"chat_id": chat_id, "media": json.dumps(media)},
            timeout=20,
        )
        r.raise_for_status()
        # Botones van en mensaje separado (Telegram no los permite en media groups)
        r2 = requests.post(
            f"{base_url}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": caption[:4000],
                "reply_markup": json.dumps(botones),
            },
            timeout=20,
        )
        r2.raise_for_status()

    elif len(urls) == 1:
        r = requests.post(
            f"{base_url}/sendPhoto",
            data={
                "chat_id": chat_id,
                "photo": urls[0],
                "caption": caption[:1000],
                "reply_markup": json.dumps(botones),
            },
            timeout=20,
        )
        r.raise_for_status()

    else:
        # Sin imagen: solo texto + botones
        r = requests.post(
            f"{base_url}/sendMessage",
            data={
                "chat_id": chat_id,
                "text": caption,
                "reply_markup": json.dumps(botones),
            },
            timeout=20,
        )
        r.raise_for_status()
