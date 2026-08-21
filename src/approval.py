"""Flujo de aprobación ASÍNCRONO (no bloqueante).

Los generadores ENCOLAN propuestas (status borrador + aprobacion pendiente) y
mandan a Telegram con botones vía sendMessage directo — sin poller. El daemon
(único poller) resuelve: aprobar → elige slot de alto tráfico, escribe el Sheet
approved y marca en_sheet; rechazar → descartado. publish.py publica luego.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from src import db


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
            user_id: int | None = None,
            _escribir_sheet: Callable[..., int] | None = None,
            _publicar: Callable[[], None] | None = None,
            _slot_meme: Callable[[datetime, str | None, list[str] | None], datetime] | None = None,
            ) -> datetime:
    """Aprueba: elige slot, escribe Sheet si la marca lo usa (legacy) o deja
    'programado' para que el publisher DB la tome (Fase 2, sin Sheet).

    Regla anti-doble-publicación: marca CON SHEET_ID publica por Sheet/Actions
    (status='en_sheet'); marca SIN SHEET_ID publica el publisher DB
    (status='programado'). Ya NO es error que falte SHEET_ID.
    """
    # OJO timezone: usar la hora de la cuenta (config.TIMEZONE), NO datetime.now()
    # naive. La máquina puede estar en otro huso (+04) y el "inmediato" saldría
    # con fecha futura que get_due_rows (que compara en CST) nunca ve vencida.
    if ahora is None:
        import pytz

        import config
        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
    fila = db.get(cx, "content_queue", queue_id)
    from src import marcas as marcas_mod
    marca = marcas_mod.cargar_por_id(cx, fila.get("account_id") or 1)
    creds = _creds_de(marca.slug)
    sheet_id = creds.get("SHEET_ID")
    # malla propia solo si la marca la define; None = malla global de gdlscene
    slots = marca.posting_slots
    # Anuncios/agendas se publican de inmediato; memes van a la malla editorial
    # (POSTING_SLOTS, 4/día contra el Sheet, o la malla propia de la marca):
    # N aprobaciones seguidas caen en N huecos DISTINTOS. timing.elegir_slot
    # (un solo horario semanal) haría chocar todo un batch en el mismo datetime.
    inmediato = fila.get("tipo") == "anuncio"
    if inmediato:
        slot = ahora
    elif sheet_id:
        slot = (_slot_meme or _siguiente_hueco)(ahora, sheet_id, slots)
    else:
        from src import scheduler
        slot = scheduler.next_free_slot_db(cx, fila.get("account_id") or 1,
                                           now=ahora, slots=slots)

    if sheet_id:
        escribir = _escribir_sheet or _sheet_real
        try:
            sheet_row = escribir(caption=fila.get("caption"),
                                 imagen=fila.get("imagen_url"),
                                 scheduled=slot.isoformat(),
                                 sheet_id=sheet_id,
                                 banda=marca.ig_handle or f"@{marca.slug}")
        except Exception as exc:
            # El espejo al Sheet falló, pero la aprobación NO se revierte:
            # cae a 'programado' (la toma el publisher DB) con el error
            # a la vista, accionable, sin bloquear al aprobador. `intentos`
            # sí se resetea (ciclo de aprobación nuevo, no de publicación).
            db.update(cx, "content_queue", queue_id, aprobacion="aprobado",
                      status="programado", scheduled_datetime=slot.isoformat(),
                      aprobado_por=user_id, error=("espejo sheet: " + str(exc))[:200],
                      intentos=0)
        else:
            db.update(cx, "content_queue", queue_id, aprobacion="aprobado", status="en_sheet",
                      sheet_row_id=str(sheet_row), scheduled_datetime=slot.isoformat(),
                      aprobado_por=user_id, error=None, intentos=0)
    else:
        # Reset error/intentos: una fila re-aprobada (p. ej. tras revivirla
        # con reprogramar, o una re-aprobación manual) no debe seguir
        # viéndose como error de un intento de publicación viejo.
        db.update(cx, "content_queue", queue_id, aprobacion="aprobado", status="programado",
                  scheduled_datetime=slot.isoformat(), aprobado_por=user_id,
                  error=None, intentos=0)
    # La foto del meme queda usada (mismo contrato que el plan mensual): no se
    # vuelve a sugerir aunque el clasificador la siga viendo usable.
    if fila.get("photo_id"):
        db.update(cx, "photos", fila["photo_id"], usada=1)
    # Motor de frescura: los releases incluidos en el carrusel quedan 'anunciado'
    # para que el semanal solo-fresco no los vuelva a publicar.
    if fila.get("evento_ids"):
        import json
        for eid in json.loads(fila["evento_ids"]):
            db.update(cx, "events", eid, status="anunciado")
    if inmediato:
        (_publicar or _publicar_ahora)()
    return slot


def _creds_de(slug: str) -> dict:
    import config as cfg
    return cfg.account_creds(slug)


def _siguiente_hueco(ahora: datetime, sheet_id: str | None = None,
                     slots: list[str] | None = None) -> datetime:
    """Próximo hueco libre de la malla de la marca (lee su Sheet). Import tardío: testeable."""
    from src import scheduler
    return scheduler.next_free_slot(ahora, sheet_id=sheet_id, slots=slots)


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


def rechazar(cx, queue_id: int, *, user_id: int | None = None) -> None:
    """Rechaza: quien resuelve también queda registrado en `aprobado_por`."""
    db.update(cx, "content_queue", queue_id, aprobacion="rechazado", status="descartado",
              aprobado_por=user_id)


def _sheet_real(*, caption, imagen, scheduled, sheet_id=None,
                banda="@gdlscene") -> int:
    """Escribe la fila approved en el Sheet de la marca (igual que generate_agenda)."""
    from src import sheets
    return sheets.append_row(banda=banda, caption_generado=caption,
                             caption_final=caption, imagen_compuesta_url=imagen,
                             status=sheets.STATUS_APPROVED, scheduled_datetime=scheduled,
                             sheet_id=sheet_id)


# --------- Telegram: helpers PUROS + envío (sin poller) ---------

def construir_botones(queue_id: int, *, regenerable: bool = False) -> list[list[dict[str, str]]]:
    """Payload de teclado inline como dict puro. PURO/testeable.

    Devuelve el array `inline_keyboard` listo para reply_markup; el daemon lo
    parsea de vuelta con `parsear_callback`. Los memes individuales llevan
    además 🔄/🎨 (regenerable=True); los carruseles/anuncios no (su imagen es
    determinista, no hay nada que regenerar).
    """
    filas = [[
        {"text": "✅ Aprobar", "callback_data": f"aprobar:{queue_id}"},
        {"text": "❌ Rechazar", "callback_data": f"rechazar:{queue_id}"},
    ]]
    if regenerable:
        filas.append([
            {"text": "🔄 Regenerar", "callback_data": f"regenerar:{queue_id}"},
            {"text": "🎨 Plantilla", "callback_data": f"plantilla:{queue_id}"},
        ])
    return filas


def parsear_callback(data: str) -> tuple[str, int]:
    """'aprobar:123' → ('aprobar', 123). PURO/testeable. Lanza si la acción no es válida."""
    accion, _, qid = data.partition(":")
    if accion not in ("aprobar", "rechazar", "regenerar", "plantilla"):
        raise ValueError(f"Acción de callback desconocida: {accion!r}")
    return accion, int(qid)


# --------- Regenerar / cambiar plantilla (flujo asíncrono, estado en DB) ---------

def _sin_handle(caption: str, ig_handle: str | None) -> str:
    """Quita el '\\n\\n@handle' final que se anexa al caption para el Sheet. PURO."""
    sufijo = f"\n\n@{ig_handle}" if ig_handle else ""
    if sufijo and caption.endswith(sufijo):
        return caption[: -len(sufijo)]
    return caption


def _datos_meme(cx, queue_id: int) -> dict[str, Any]:
    filas = db.rows(cx, """
        SELECT q.id, q.caption, q.template, q.rechazados, q.photo_id,
               b.nombre AS banda, b.tipo, b.ig_handle, p.path AS foto_path
          FROM content_queue q
          JOIN bands b ON b.id = q.band_id
          LEFT JOIN photos p ON p.id = q.photo_id
         WHERE q.id = ?
    """, (queue_id,))
    if not filas or not filas[0]["foto_path"]:
        raise ValueError(f"queue {queue_id} no es un meme regenerable (sin banda o sin foto)")
    return filas[0]


def _recomponer(cx, fila: dict[str, Any], cap: str, template: str) -> tuple[str, str]:
    """Compone, sube y actualiza la fila. Devuelve (caption_final, url)."""
    import time

    from src import compose as compose_mod
    from src import host
    png = compose_mod.compose(caption=cap, foto_url=fila["foto_path"],
                              template=template, row_id=f"q{fila['id']}")
    # public_id ÚNICO por versión: Telegram y Cloudinary cachean por URL — si se
    # re-subiera con el mismo public_id, el mensaje editado mostraría la imagen vieja.
    url = host.upload(str(png), public_id=f"q{fila['id']}_v{int(time.time())}")
    cap_final = cap + (f"\n\n@{fila['ig_handle']}" if fila.get("ig_handle") else "")
    db.update(cx, "content_queue", fila["id"],
              caption=cap_final, imagen_url=url, template=template)
    return cap_final, url


def regenerar_meme(cx, queue_id: int) -> tuple[str, str]:
    """Caption nuevo (LLM, sin repetir los ya rechazados) + recomposición."""
    import json

    from src import caption as caption_mod
    fila = _datos_meme(cx, queue_id)
    rechazados = json.loads(fila["rechazados"] or "[]")
    actual = _sin_handle(fila["caption"] or "", fila.get("ig_handle"))
    if actual:
        rechazados.append(actual)
    cap = caption_mod.generate_caption(banda=fila["banda"], rechazados=rechazados,
                                       tipo=fila.get("tipo") or "banda")
    db.update(cx, "content_queue", queue_id, rechazados=json.dumps(rechazados))
    return _recomponer(cx, fila, cap, fila["template"] or "clasica")


def cambiar_plantilla(cx, queue_id: int) -> tuple[str, str]:
    """Recompone el MISMO caption con la siguiente plantilla (clasica→verde→onion)."""
    from src import compose as compose_mod
    fila = _datos_meme(cx, queue_id)
    template = compose_mod.siguiente_template(fila["template"] or "clasica")
    cap = _sin_handle(fila["caption"] or "", fila.get("ig_handle"))
    return _recomponer(cx, fila, cap, template)


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


def enviar_a_telegram(caption: str, imagen_url: str, queue_id: int,
                      *, regenerable: bool = False,
                      account_slug: str = "gdlscene", cx=None) -> None:
    """Manda la propuesta a Telegram con botones Aprobar/Rechazar (y 🔄/🎨 si
    es un meme individual regenerable).

    - Carrusel (>=2 URLs): sendMediaGroup con las fotos, luego sendMessage con
      caption + botones (Telegram no permite botones en media groups).
    - Single (1 URL): sendPhoto con caption + botones.
    - Sin imagen: sendMessage solo texto + botones (fallback).

    Usa requests (trae certifi, sin problemas de certs de red).

    Con `cx`: guarda `tg_chat_id`/`tg_message_id` del mensaje final (el que
    lleva los botones) para que `notificar_resolucion` pueda editarlo luego.
    Sin `cx` (llamadas legacy): comportamiento idéntico al de antes.
    """
    import json

    import requests

    creds = _creds_de(account_slug)
    token = creds.get("TELEGRAM_BOT_TOKEN")
    chat_id = creds.get("TELEGRAM_CHAT_ID")
    if not token:
        raise RuntimeError(
            f"Falta TELEGRAM_BOT_TOKEN__{account_slug.upper()} en el .env")
    if not chat_id:
        raise RuntimeError(
            f"Falta TELEGRAM_CHAT_ID__{account_slug.upper()} en el .env")
    base_url = f"https://api.telegram.org/bot{token}"
    botones = {"inline_keyboard": construir_botones(queue_id, regenerable=regenerable)}
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
        final = r2

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
        final = r

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
        final = r

    if cx is not None:
        import sys
        try:
            resultado = final.json()["result"]
            db.update(cx, "content_queue", queue_id,
                      tg_chat_id=str(resultado["chat"]["id"]),
                      tg_message_id=str(resultado["message_id"]))
        except (KeyError, ValueError) as exc:
            print(f"[approval] no se pudo leer message_id/chat.id de Telegram "
                 f"para queue {queue_id}: {exc}", file=sys.stderr)


def notificar_resolucion(cx, queue_id: int, texto: str) -> bool:
    """Avisa la resolución (aprobado/rechazado/programado) en el chat de
    Telegram donde se mandó la propuesta: quita los botones del mensaje
    original y contesta `texto` en reply.

    Tolerante: sin tg_chat_id/tg_message_id en la fila, sin token de la marca,
    o cualquier fallo de red/API → devuelve False (aviso a stderr), NUNCA
    lanza — esto corre desde el publisher/daemon y no debe tumbarlo.
    """
    import sys

    import requests

    token: str | None = None
    chat_id: str | None = None
    try:
        fila = db.get(cx, "content_queue", queue_id)
        if not fila or not fila.get("tg_chat_id") or not fila.get("tg_message_id"):
            return False
        from src import marcas as marcas_mod
        marca = marcas_mod.cargar_por_id(cx, fila.get("account_id") or 1)
        creds = _creds_de(marca.slug)
        token = creds.get("TELEGRAM_BOT_TOKEN")
        if not token:
            return False

        import json

        base_url = f"https://api.telegram.org/bot{token}"
        chat_id = fila["tg_chat_id"]
        message_id = fila["tg_message_id"]

        try:
            r1 = requests.post(
                f"{base_url}/editMessageReplyMarkup",
                data={"chat_id": chat_id, "message_id": message_id,
                     "reply_markup": json.dumps({"inline_keyboard": []})},
                timeout=20,
            )
            r1.raise_for_status()
        except Exception as exc:
            # Quitar los botones es best-effort (mensaje ya editado/borrado,
            # permisos, etc.): NO debe impedir el aviso de abajo — sigue.
            print(f"[approval] no se pudieron quitar los botones en queue {queue_id}: "
                 f"{_error_seguro(exc, token=token, chat_id=chat_id)}", file=sys.stderr)
        r2 = requests.post(
            f"{base_url}/sendMessage",
            data={"chat_id": chat_id, "text": texto, "reply_to_message_id": message_id},
            timeout=20,
        )
        r2.raise_for_status()
        return True
    except Exception as exc:
        print(f"[approval] notificar_resolucion falló para queue {queue_id}: "
             f"{_error_seguro(exc, token=token, chat_id=chat_id)}", file=sys.stderr)
        return False


def _error_seguro(exc: Exception, *, token: str | None = None,
                  chat_id: str | None = None) -> str:
    """Texto de error SIN secretos: nunca la URL cruda (trae el bot token).

    requests.HTTPError trae la URL completa (con el token) en su __str__ y en
    resp.url — de esa solo se loguea el status code. Cualquier otra excepción
    se castea a texto y se redactan token/chat_id si aparecen ahí (p. ej. un
    ConnectionError también puede traer la URL en su mensaje).
    """
    import requests
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"HTTP {exc.response.status_code}"
    msg = str(exc)
    if token:
        msg = msg.replace(token, "***")
    if chat_id:
        msg = msg.replace(str(chat_id), "***")
    return msg[:200]
