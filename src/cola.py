"""Operaciones de cola de contenido para la API del portal (Fase 2).

Encapsula la derivación de estado (`estado_de`) y las mutaciones que
expone el router de cola (Task 7): listar/filtrar, ver detalle,
reprogramar, editar caption y descartar. No conoce HTTP: trabaja solo
sobre filas crudas de `content_queue` vía `src.db`.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src import db

# Estados derivados que ve el portal (no son la columna `status` cruda: se
# calculan a partir de status + aprobacion + error, ver `estado_de`).
# "borrador" (Fase 2, fix G5): filas legacy (plan mensual, origen != 'api')
# en status borrador/listo sin aprobación aún — NO son "generando" (nadie
# está generando nada ahí) y NO son aprobables desde el portal (la compuerta
# de aprobar/rechazar sigue exigiendo 'pendiente').
ESTADOS = (
    "generando", "borrador", "pendiente", "programado", "publicado",
    "rechazado", "error", "descartado",
)

# Estados desde los que se puede mover el horario o editar el caption.
# "error" incluido (fix round 1, revisión Task 6): reprogramar es la vía para
# revivir una fila atorada por el publisher (marcador "[publicando]" de un
# crash a medias, o topada en MAX_INTENTOS) — sin esto quedaría sin salida.
_EDITABLES = ("pendiente", "programado", "error")
# Estados desde los que se puede descartar (→ status='descartado').
_ELIMINABLES = ("pendiente", "rechazado", "error")
# status crudos que ocupan un slot de la malla (mismos que scheduler._taken_db).
_STATUS_OCUPA_SLOT = ("en_sheet", "programado", "publicado")


def estado_de(fila: dict[str, Any]) -> str:
    """Deriva el estado que ve el portal a partir de una fila de content_queue.

    Prioridad evaluada en orden (la primera que aplica gana):
    descartado > rechazado > publicado > error > programado > pendiente >
    generando > borrador > pendiente (fallback).

    "generando" vs "borrador" (fix G5): con aprobacion NULL, "generando" es
    EXCLUSIVO del flujo API (origen='api') mientras el worker arma el
    slideshow; una fila legacy (plan mensual, origen != 'api') en
    borrador/listo sin aprobación todavía es "borrador" — nadie la está
    generando, y no es aprobable desde el portal (esa compuerta exige
    'pendiente').
    """
    status = fila.get("status")
    aprobacion = fila.get("aprobacion")
    error = fila.get("error")
    origen = fila.get("origen")

    if status == "descartado" and aprobacion != "rechazado":
        return "descartado"
    if aprobacion == "rechazado":
        return "rechazado"
    if status == "publicado":
        return "publicado"
    if error and status != "publicado" and status != "en_sheet":
        return "error"
    if aprobacion == "aprobado" and status in ("en_sheet", "programado"):
        return "programado"
    if aprobacion == "pendiente":
        return "pendiente"
    if aprobacion is None and status == "borrador" and origen == "api":
        return "generando"
    if aprobacion is None and status in ("borrador", "listo") and origen != "api":
        return "borrador"
    return "pendiente"


def listar(cx, account_id: int, *, desde: str | None = None, hasta: str | None = None,
           estado: str | None = None) -> list[dict[str, Any]]:
    """Filas de `content_queue` de la marca, con estado derivado (campo "estado").

    `desde`/`hasta` (ISO) filtran por `scheduled_datetime`, o por `created_at`
    si la fila todavía no tiene horario asignado. `estado` filtra por el
    estado derivado (post-cómputo, no la columna `status` cruda). Nunca
    devuelve filas de otra cuenta.
    """
    filas = db.rows(
        cx,
        "SELECT * FROM content_queue WHERE account_id = ? "
        "ORDER BY COALESCE(scheduled_datetime, created_at) ASC",
        (account_id,),
    )
    resultado = []
    for fila in filas:
        momento = fila.get("scheduled_datetime") or fila.get("created_at") or ""
        if desde and momento < desde:
            continue
        if hasta and momento > hasta:
            continue
        fila["estado"] = estado_de(fila)
        if estado and fila["estado"] != estado:
            continue
        resultado.append(fila)
    return resultado


def detalle(cx, queue_id: int) -> dict[str, Any] | None:
    """Una fila con estado derivado y `slideshow_json` parseado en "slides_data".

    None si el id no existe. `slides_data` tolera JSON ausente o inválido:
    en ambos casos queda en None (nunca truena la vista de detalle).
    """
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None:
        return None
    fila["estado"] = estado_de(fila)
    raw = fila.get("slideshow_json")
    try:
        fila["slides_data"] = json.loads(raw) if raw else None
    except (TypeError, ValueError):
        fila["slides_data"] = None
    return fila


def reprogramar(cx, queue_id: int, nueva_iso: str) -> None:
    """Cambia `scheduled_datetime`. Solo si el estado derivado es
    pendiente/programado; ValueError("estado") si no.

    ValueError("choque") si otra fila programada/en_sheet/publicada de la
    MISMA cuenta ya ocupa ese minuto (comparación normalizada a
    "YYYY-MM-DDTHH:MM", excluyendo la propia fila).

    ValueError("formato") si `nueva_iso` no es una fecha ISO válida (p. ej.
    texto libre desde un input mal validado en el front).
    """
    try:
        datetime.fromisoformat(nueva_iso)
    except ValueError:
        raise ValueError("formato") from None

    fila = db.get(cx, "content_queue", queue_id)
    if fila is None or estado_de(fila) not in _EDITABLES:
        raise ValueError("estado")

    minuto = nueva_iso[:16]
    placeholders = ", ".join("?" * len(_STATUS_OCUPA_SLOT))
    ocupados = db.rows(
        cx,
        f"SELECT scheduled_datetime FROM content_queue "
        f"WHERE account_id = ? AND status IN ({placeholders}) "
        f"AND id != ? AND scheduled_datetime IS NOT NULL",
        (fila["account_id"], *_STATUS_OCUPA_SLOT, queue_id),
    )
    if any(str(r["scheduled_datetime"])[:16] == minuto for r in ocupados):
        raise ValueError("choque")

    # Reset de intentos/error: reprogramar es la vía del operador para revivir
    # una fila atorada (marcador "[publicando]" de un crash a medias, o ya
    # topada en MAX_INTENTOS) — sin esto seguiría excluida de filas_due.
    db.update(cx, "content_queue", queue_id, scheduled_datetime=nueva_iso,
              intentos=0, error=None)


def editar_caption(cx, queue_id: int, caption: str) -> None:
    """Cambia el caption. Solo si el estado derivado es pendiente/programado;
    ValueError("estado") si no."""
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None or estado_de(fila) not in _EDITABLES:
        raise ValueError("estado")
    db.update(cx, "content_queue", queue_id, caption=caption)


def _resolver_image_url(cx, fila: dict[str, Any], valor: str | None,
                        actual: str | None) -> str | None:
    """Valida/traduce el fondo pedido para un slide.

    None → sin foto; el valor ya guardado pasa tal cual (re-mandar el estado
    actual nunca falla); "/brands/<slug>/files/fotos/<nombre>" → ruta local
    del banco (ValueError("foto") si no existe); http(s) → url_segura o
    ValueError("url"). Cualquier otra cosa (file://, rutas arbitrarias) se
    rechaza: el render la cargaría con Playwright vía file://.
    """
    from src import image_sources
    from src.topics import url_segura

    if valor is None or valor == actual:
        return valor
    slug = db.rows(cx, "SELECT slug FROM accounts WHERE id = ?",
                   (fila["account_id"],))
    prefijo = f"/brands/{slug[0]['slug']}/files/fotos/" if slug else None
    if prefijo and valor.startswith(prefijo):
        nombre = valor[len(prefijo):]
        ruta = image_sources.BRANDS_DIR / slug[0]["slug"] / "fotos" / nombre
        if "/" in nombre or ".." in nombre or not ruta.is_file():
            raise ValueError("foto")
        return str(ruta)
    if not url_segura(valor):
        raise ValueError("url")
    return valor


def editar_slides(cx, queue_id: int, slides: list[dict[str, Any]]) -> None:
    """Aplica textos y foto de fondo por slide sobre `slideshow_json`.

    `slides` trae el estado COMPLETO deseado: un dict por slide con
    `texts` (uno por text_item, mismo orden) e `image_url` (None = fondo
    sólido). La estructura debe coincidir con la guardada — esto edita, no
    agrega ni quita slides/textos. No re-renderiza: el caller encola el job
    `slideshow.rerender` después.

    ValueError("estado" | "tipo" | "estructura" | "url" | "foto").
    """
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None or estado_de(fila) not in _EDITABLES:
        raise ValueError("estado")
    if fila["tipo"] != "slideshow" or not fila["slideshow_json"]:
        raise ValueError("tipo")
    show = json.loads(fila["slideshow_json"])
    if len(slides) != len(show["slides"]):
        raise ValueError("estructura")
    for pedido, slide in zip(slides, show["slides"]):
        textos = pedido.get("texts") or []
        if len(textos) != len(slide["text_items"]):
            raise ValueError("estructura")
        if any(not (t or "").strip() for t in textos):
            raise ValueError("estructura")
        actual = (slide.get("image_urls") or [None])[0]
        url = _resolver_image_url(cx, fila, pedido.get("image_url"), actual)
        for item, texto in zip(slide["text_items"], textos):
            item["text"] = texto.strip()
        slide["image_urls"] = [url] if url else []
    db.update(cx, "content_queue", queue_id, slideshow_json=json.dumps(show))


def eliminar(cx, queue_id: int) -> None:
    """Descarta la fila (status='descartado'). Solo si el estado derivado es
    pendiente/rechazado/error; ValueError("estado") si no."""
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None or estado_de(fila) not in _ELIMINABLES:
        raise ValueError("estado")
    db.update(cx, "content_queue", queue_id, status="descartado")
