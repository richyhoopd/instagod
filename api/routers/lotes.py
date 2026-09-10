"""Lotes de memes de banda (gdlscene): planear con criterios, curar y mandar.

Es el puerto al portal de la pantalla `/plan` del GUI htmx (`web/app.py`), que
solo corría en local. Mismo motor (`src.planner` + `src.send_plan`), misma
semántica: lo que quitas NO regresa, eliminar es lista negra, y el envío deja
las piezas en `aprobacion='pendiente'` para que el approval-daemon resuelva los
botones de Telegram.

Solo gdlscene: `src.planner` escribe `content_queue` con el `account_id` por
default (1 = gdlscene) y sus consultas no filtran por cuenta, así que dejar
entrar otra marca le crearía piezas ajenas en silencio. Ver el 422 de `_gdlscene`.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import config
from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, conflicto, no_encontrado
from src import db, jobs, planner

router = APIRouter(prefix="/brands/{slug}", tags=["lotes"])

_MES_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class NuevoLote(BaseModel):
    mes: str = Field(min_length=7, max_length=7)
    criterio: Literal["impacto", "engagement"] = "impacto"
    replan: bool = False


class EditarPieza(BaseModel):
    tema_semilla: str | None = Field(None, max_length=200)


def _gdlscene(slug: str, cx, user: dict) -> dict:
    """Marca del path con permiso de editor, restringida a gdlscene."""
    fila, _ = marca_para(slug, cx, user)
    if fila["slug"] != "gdlscene":
        raise ApiError(422, "no_aplica",
                       "Los lotes de memes de banda solo existen para gdlscene",
                       "slug")
    return fila


def _mes_valido(mes: str) -> str:
    if not _MES_RE.match(mes or ""):
        raise ApiError(422, "validacion", "El mes va como 2026-10", "mes")
    return mes


def _pieza_de_marca(cx, account_id: int, qid: int) -> dict:
    """Fila del borrador si es de la marca y sigue siendo curable."""
    fila = db.get(cx, "content_queue", qid)
    if fila is None or fila.get("account_id") != account_id:
        raise no_encontrado("esa pieza del lote")
    if fila["status"] != db.QUEUE_BORRADOR or fila["aprobacion"] is not None:
        raise conflicto("Esa pieza ya salió del borrador; se cura desde la cola")
    return fila


def _piezas(cx, mes: str) -> list[dict]:
    """Borrador del mes con lo que la tarjeta necesita para pintarse."""
    return db.rows(cx, """
        SELECT q.id, q.tema_semilla, q.scheduled_datetime, q.photo_id,
               b.id AS band_id, b.nombre AS banda, b.tipo, b.prioridad,
               b.followers_ig, b.ig_handle
          FROM content_queue q JOIN bands b ON b.id = q.band_id
         WHERE q.status = ? AND q.aprobacion IS NULL AND q.tipo = 'meme'
           AND substr(q.scheduled_datetime,1,7) = ?
         ORDER BY q.scheduled_datetime
    """, (db.QUEUE_BORRADOR, mes))


def _job_vivo(cx, account_id: int, mes: str) -> int | None:
    """Envío del mismo mes aún en cola o corriendo (evita mandar dos veces)."""
    fila = cx.execute(
        "SELECT id FROM jobs WHERE tipo = 'lote.enviar' AND account_id = ? "
        "AND estado IN ('cola', 'corriendo') "
        "AND json_extract(payload_json, '$.mes') = ? LIMIT 1",
        (account_id, mes)).fetchone()
    return fila["id"] if fila else None


def _reemplazo(nueva: dict | None) -> dict | None:
    """Fila nueva que entró al slot, o None si el pool se agotó."""
    if not nueva:
        return None
    return {"id": nueva["id"]}


# --------------------------------------------------------------------- lectura

@router.get("/lotes")
def listar_lotes(slug: str, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> list[dict]:
    """Meses que tienen borrador por curar, del más reciente al más viejo."""
    fila = _gdlscene(slug, cx, user)
    meses = db.rows(cx, """
        SELECT substr(scheduled_datetime,1,7) AS mes, COUNT(*) AS piezas
          FROM content_queue
         WHERE status = ? AND aprobacion IS NULL AND tipo = 'meme'
         GROUP BY mes ORDER BY mes DESC
    """, (db.QUEUE_BORRADOR,))
    for m in meses:
        m["job_id"] = _job_vivo(cx, fila["id"], m["mes"])
    return meses


@router.get("/lotes/{mes}")
def detalle_lote(slug: str, mes: str, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    fila = _gdlscene(slug, cx, user)
    _mes_valido(mes)
    piezas = _piezas(cx, mes)
    return {"mes": mes, "piezas": piezas, "job_id": _job_vivo(cx, fila["id"], mes),
            "caps": config.MONTHLY_CAP, "slots": config.POSTING_SLOTS}


@router.get("/lotes/foto/{photo_id}")
def servir_foto(slug: str, photo_id: int, user: dict = Depends(usuario_actual),
                cx=Depends(get_cx)) -> FileResponse:
    """La foto original del disco (las piezas del borrador aún no tienen render)."""
    _gdlscene(slug, cx, user)
    foto = db.get(cx, "photos", photo_id)
    if foto is None:
        raise no_encontrado("esa foto")
    ruta = Path(foto["path"])
    if not ruta.is_absolute():
        ruta = config.BASE_DIR / ruta
    if not ruta.exists():
        raise no_encontrado("el archivo de esa foto")
    return FileResponse(ruta)


# ---------------------------------------------------------------- planeación

@router.post("/lotes", status_code=201)
def crear_lote(slug: str, datos: NuevoLote, user: dict = Depends(usuario_actual),
               cx=Depends(get_cx)) -> dict:
    """Planea el mes (síncrono: son consultas, no renders) y devuelve el borrador.

    `replan` NO borra: marca el borrador previo como descartado, que es lo que
    hace que `seleccionar` traiga fotos distintas (ver `planner.plan_month`).
    """
    fila = _gdlscene(slug, cx, user)
    mes = _mes_valido(datos.mes)
    if _job_vivo(cx, fila["id"], mes):
        raise conflicto(f"El lote de {mes} se está mandando a Telegram ahora mismo")
    y, m = int(mes[:4]), int(mes[5:])
    resumen = planner.plan_month(y, m, replan=datos.replan,
                                 criterio=datos.criterio, cx=cx)
    if resumen.get("existentes") and not datos.replan:
        raise conflicto(f"Ya hay un borrador de {mes} con {resumen['existentes']} "
                        "piezas. Marca 'rehacer' para tirarlo y planear de nuevo.",
                        "replan")
    return {"mes": mes, "resumen": resumen, "piezas": _piezas(cx, mes)}


# ------------------------------------------------------------------- curación

@router.patch("/lotes/piezas/{qid}")
def editar_pieza(slug: str, qid: int, datos: EditarPieza,
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    """Tema semilla de la pieza. Vacío = tema libre (el caption lo decide el LLM)."""
    fila = _gdlscene(slug, cx, user)
    _pieza_de_marca(cx, fila["id"], qid)
    tema = (datos.tema_semilla or "").strip() or None
    db.update(cx, "content_queue", qid, tema_semilla=tema)
    return {"id": qid, "tema_semilla": tema}


@router.post("/lotes/piezas/{qid}/cambiar")
def cambiar_pieza(slug: str, qid: int, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> dict:
    """Saca esta foto del lote y mete otra banda en su slot. No regresa."""
    fila = _gdlscene(slug, cx, user)
    _pieza_de_marca(cx, fila["id"], qid)
    return {"reemplazo": _reemplazo(planner.reemplazar(qid, cx=cx))}


@router.post("/lotes/piezas/{qid}/flyer")
def marcar_flyer(slug: str, qid: int, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    """No era foto de banda, era un flyer: se registra como evento y se reemplaza."""
    fila = _gdlscene(slug, cx, user)
    _pieza_de_marca(cx, fila["id"], qid)
    return {"reemplazo": _reemplazo(planner.marcar_flyer(qid, cx=cx))}


@router.delete("/lotes/piezas/{qid}")
def eliminar_pieza(slug: str, qid: int, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    """Lista negra: la foto NUNCA se vuelve a sugerir, ni tras reclasificar."""
    fila = _gdlscene(slug, cx, user)
    _pieza_de_marca(cx, fila["id"], qid)
    return {"reemplazo": _reemplazo(planner.eliminar(qid, cx=cx))}


# --------------------------------------------------------------------- envío

@router.post("/lotes/{mes}/enviar", status_code=202)
def enviar_lote(slug: str, mes: str, user: dict = Depends(usuario_actual),
                cx=Depends(get_cx)) -> dict:
    """Encola el envío a Telegram. Corre en el worker (cada render pica ~550 MB)."""
    fila = _gdlscene(slug, cx, user)
    _mes_valido(mes)
    vivo = _job_vivo(cx, fila["id"], mes)
    if vivo:
        raise conflicto(f"El lote de {mes} ya se está mandando (job {vivo})")
    piezas = _piezas(cx, mes)
    if not piezas:
        raise conflicto(f"No hay borradores por mandar en {mes}")
    job_id = jobs.crear(cx, "lote.enviar", fila["id"], {"mes": mes},
                        creado_por=user["id"])
    return {"job_id": job_id, "piezas": len(piezas)}
