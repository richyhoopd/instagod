"""Cola de contenido del portal: listar, editar, aprobar/rechazar, regenerar, slots."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, conflicto, no_encontrado
from src import approval, cola, jobs, marcas, scheduler

router = APIRouter(prefix="/brands/{slug}", tags=["cola"])

# Campos que expone el listado (no el detalle completo, que incluye slides_data).
_CAMPOS_LISTA = ("id", "tipo", "estado", "caption", "imagen_url", "scheduled_datetime",
                 "tema_semilla", "template", "error", "creado_por", "aprobado_por")


def _resumen(fila: dict) -> dict:
    return {k: fila.get(k) for k in _CAMPOS_LISTA}


def _item_de_marca(cx, account_id: int, qid: int) -> dict:
    """Detalle de la fila si es de la marca; 404 si no existe o es de otra."""
    item = cola.detalle(cx, qid)
    if item is None or item["account_id"] != account_id:
        raise no_encontrado("ese item de la cola")
    return item


class EditarItem(BaseModel):
    caption: str | None = None
    scheduled_datetime: str | None = None


@router.get("/queue")
def listar(slug: str, desde: str | None = None, hasta: str | None = None,
          estado: str | None = None, user: dict = Depends(usuario_actual),
          cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    items = cola.listar(cx, fila["id"], desde=desde, hasta=hasta, estado=estado)
    return [_resumen(f) for f in items]


@router.get("/queue/{qid}")
def detalle(slug: str, qid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    return _item_de_marca(cx, fila["id"], qid)


@router.patch("/queue/{qid}")
def editar(slug: str, qid: int, datos: EditarItem, user: dict = Depends(usuario_actual),
          cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    _item_de_marca(cx, fila["id"], qid)
    if datos.caption is not None:
        try:
            cola.editar_caption(cx, qid, datos.caption)
        except ValueError:
            raise ApiError(422, "validacion", "No se puede editar el caption en este estado",
                          "caption") from None
    if datos.scheduled_datetime is not None:
        try:
            cola.reprogramar(cx, qid, datos.scheduled_datetime)
        except ValueError as e:
            if str(e) == "choque":
                raise conflicto("Ese horario ya está ocupado", "scheduled_datetime") from None
            if str(e) == "formato":
                raise ApiError(422, "validacion", "scheduled_datetime no es una fecha ISO válida",
                              "scheduled_datetime") from None
            raise ApiError(422, "validacion", "No se puede reprogramar en este estado",
                          "scheduled_datetime") from None
    return cola.detalle(cx, qid)


@router.post("/queue/{qid}/aprobar")
def aprobar(slug: str, qid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    item = _item_de_marca(cx, fila["id"], qid)
    if item["estado"] != "pendiente":
        raise ApiError(422, "validacion", "Solo se puede aprobar un item pendiente", "estado")
    try:
        slot = approval.aprobar(cx, qid, user_id=user["id"])
    except Exception as e:  # noqa: BLE001
        raise ApiError(422, "validacion", str(e)) from e
    approval.notificar_resolucion(cx, qid, f"✅ Aprobado desde el portal para {slot}")
    return {"ok": True, "scheduled_datetime": slot.isoformat()}


@router.post("/queue/{qid}/rechazar")
def rechazar(slug: str, qid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    item = _item_de_marca(cx, fila["id"], qid)
    if item["estado"] != "pendiente":
        raise ApiError(422, "validacion", "Solo se puede rechazar un item pendiente", "estado")
    approval.rechazar(cx, qid, user_id=user["id"])
    approval.notificar_resolucion(cx, qid, "❌ Rechazado desde el portal")
    return {"ok": True}


@router.post("/queue/{qid}/regenerar", status_code=202)
def regenerar(slug: str, qid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    item = _item_de_marca(cx, fila["id"], qid)
    if item["tipo"] != "slideshow" or item["estado"] not in ("pendiente", "rechazado"):
        raise ApiError(422, "validacion",
                       "Solo se puede regenerar un slideshow pendiente o rechazado")
    job_id = jobs.crear(cx, "slideshow.regenerar", fila["id"], {"queue_id": qid},
                        creado_por=user["id"])
    return {"job_id": job_id}


@router.delete("/queue/{qid}", status_code=204)
def eliminar(slug: str, qid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> None:
    fila, _ = marca_para(slug, cx, user)
    _item_de_marca(cx, fila["id"], qid)
    try:
        cola.eliminar(cx, qid)
    except ValueError:
        raise ApiError(422, "validacion", "No se puede eliminar en este estado") from None


@router.get("/slots/proximos")
def slots_proximos(slug: str, n: int = 5, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> list[str]:
    fila, _ = marca_para(slug, cx, user)
    marca = marcas.cargar_por_id(cx, fila["id"])
    slots = scheduler.slots_proximos_db(cx, fila["id"], n, slots=marca.posting_slots)
    return [s.isoformat() for s in slots]
