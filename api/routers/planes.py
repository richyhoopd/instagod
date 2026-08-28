"""Planes de contenido masivo del portal (spec 2026-08-28).

Ciclo: crear (objetivo → job de temas) → curar temas → generar (job de lote)
→ curar piezas con los endpoints de cola existentes → aprobar en bloque aquí
(server-side: el bucle de N requests del cliente era el cuello de la biblioteca).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import config
from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, conflicto, no_encontrado
from src import approval, db, jobs, marcas, planes, slideshow_model

router = APIRouter(prefix="/brands/{slug}", tags=["planes"])

# Fuentes de imagen que el motor conoce (src/image_sources.py); la validación
# fina (keys presentes, flags) la hace el propio motor al generar.
_FUENTES_IMAGEN = {"banco", "covers", "carpeta", "pexels", "unsplash", "pinterest"}


class NuevoPlan(BaseModel):
    tipo_periodo: Literal["semana", "mes"]
    periodo: str = Field(min_length=6, max_length=8)
    objetivo: str = Field(min_length=10, max_length=2000)
    n_piezas: int = Field(10, ge=1, le=30)
    n_slides: int = Field(6, ge=1, le=10)
    aspect: str = "4:5"
    estilo: str | None = None
    formatos: list[str] | None = None
    fuentes_imagen: list[str] | None = None
    fuentes_info: list[Literal["prompt", "noticias"]] = ["prompt"]


class NuevoTopic(BaseModel):
    titulo: str = Field(min_length=3, max_length=200)
    formato: str | None = None
    hook: str | None = Field(None, max_length=300)


class EditarTopic(BaseModel):
    titulo: str | None = Field(None, min_length=3, max_length=200)
    formato: str | None = None
    hook: str | None = Field(None, max_length=300)
    estado: Literal["aprobado", "descartado"] | None = None


class AprobarPlan(BaseModel):
    queue_ids: list[int] | None = None


def _plan_de_marca(cx, account_id: int, pid: int) -> dict:
    plan = planes.detalle(cx, pid)
    if plan is None or plan["account_id"] != account_id:
        raise no_encontrado("ese plan")
    return plan


def _job_vivo_de(cx, pid: int) -> int | None:
    """Job de plan aún en cola o corriendo para ese plan (evita dobles lotes)."""
    fila = cx.execute(
        "SELECT id FROM jobs WHERE tipo IN ('plan.proponer_temas', 'plan.generar') "
        "AND estado IN ('cola', 'corriendo') "
        "AND json_extract(payload_json, '$.plan_id') = ? LIMIT 1", (pid,)).fetchone()
    return fila["id"] if fila else None


@router.post("/plans", status_code=202)
def crear_plan(slug: str, datos: NuevoPlan, user: dict = Depends(usuario_actual),
               cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    if not planes.validar_periodo(datos.tipo_periodo, datos.periodo):
        raise ApiError(422, "validacion",
                       "El periodo no coincide con el tipo (semana: 2026-W36, mes: 2026-09)",
                       "periodo")
    if datos.aspect not in slideshow_model.ASPECT_RATIOS:
        raise ApiError(422, "validacion", "Aspecto desconocido", "aspect")
    m = marcas.cargar_por_id(cx, fila["id"])
    permitidos = m.formatos or list(config.SLIDESHOW_FORMATOS)
    if datos.formatos:
        malos = set(datos.formatos) - set(permitidos)
        if malos:
            raise ApiError(422, "validacion",
                           f"Formatos no habilitados para la marca: {sorted(malos)}",
                           "formatos")
    if datos.fuentes_imagen:
        malas = set(datos.fuentes_imagen) - _FUENTES_IMAGEN
        if malas:
            raise ApiError(422, "validacion",
                           f"Fuentes de imagen desconocidas: {sorted(malas)}",
                           "fuentes_imagen")
    if datos.estilo and datos.estilo not in marcas.estilos_de(m):
        raise ApiError(422, "validacion", "Ese estilo no existe para la marca", "estilo")

    cfg = {"n_piezas": datos.n_piezas, "n_slides": datos.n_slides,
           "aspect": datos.aspect, "estilo": datos.estilo,
           "formatos": datos.formatos or permitidos,
           "fuentes_imagen": datos.fuentes_imagen,
           "fuentes_info": datos.fuentes_info}
    pid = planes.crear(cx, fila["id"], tipo_periodo=datos.tipo_periodo,
                       periodo=datos.periodo, objetivo=datos.objetivo,
                       config=cfg, creado_por=user["id"])
    job_id = jobs.crear(cx, "plan.proponer_temas", fila["id"], {"plan_id": pid},
                        creado_por=user["id"])
    return {"plan_id": pid, "job_id": job_id}


@router.get("/plans")
def listar_planes(slug: str, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    return planes.listar(cx, fila["id"])


@router.get("/plans/{pid}")
def detalle_plan(slug: str, pid: int, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    plan["job_id"] = _job_vivo_de(cx, pid)
    return plan


@router.post("/plans/{pid}/topics", status_code=201)
def agregar_topic(slug: str, pid: int, datos: NuevoTopic,
                  user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    if plan["estado"] not in ("temas", "curacion"):
        raise ApiError(422, "validacion",
                       "Solo se pueden agregar temas con el plan en curación de temas",
                       "estado")
    tid = planes.agregar_topic(cx, pid, titulo=datos.titulo,
                               formato=datos.formato, hook=datos.hook)
    return db.get(cx, "plan_topics", tid)


@router.patch("/plans/{pid}/topics/{tid}")
def editar_topic(slug: str, pid: int, tid: int, datos: EditarTopic,
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    _plan_de_marca(cx, fila["id"], pid)
    topic = db.get(cx, "plan_topics", tid)
    if topic is None or topic["plan_id"] != pid:
        raise no_encontrado("ese tema")
    campos = {k: v for k, v in datos.model_dump().items() if v is not None}
    if not campos:
        return topic
    try:
        planes.editar_topic(cx, tid, **campos)
    except ValueError:
        raise ApiError(422, "validacion",
                       "Ese tema ya generó su pieza y no se puede editar") from None
    return db.get(cx, "plan_topics", tid)


@router.post("/plans/{pid}/generar", status_code=202)
def generar_plan(slug: str, pid: int, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    if plan["estado"] != "temas":
        raise ApiError(422, "validacion",
                       "El plan no está en curación de temas", "estado")
    if plan["topics_aprobados"] == 0:
        raise ApiError(422, "validacion", "No hay temas aprobados que generar")
    if _job_vivo_de(cx, pid):
        raise conflicto("Este plan ya tiene un trabajo en curso")
    job_id = jobs.crear(cx, "plan.generar", fila["id"], {"plan_id": pid},
                        creado_por=user["id"])
    return {"job_id": job_id}


@router.post("/plans/{pid}/aprobar")
def aprobar_plan(slug: str, pid: int, datos: AprobarPlan,
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    """Aprobación en lote server-side: cada pieza toma su siguiente slot libre.

    Secuencial a propósito (igual que el lote de la biblioteca): `approval.aprobar`
    elige el siguiente hueco libre y N aprobaciones seguidas deben caer en N
    horarios DISTINTOS. Una pieza que falla no detiene al resto: se reporta.
    """
    fila, _ = marca_para(slug, cx, user)
    plan = _plan_de_marca(cx, fila["id"], pid)
    if plan["estado"] not in ("curacion", "aprobado"):
        raise ApiError(422, "validacion", "El plan no está en curación", "estado")
    pendientes = [p["id"] for p in plan["piezas"] if p["aprobacion"] == "pendiente"]
    if datos.queue_ids is not None:
        elegidas = set(datos.queue_ids)
        pendientes = [qid for qid in pendientes if qid in elegidas]

    aprobadas, fallidas = [], []
    for qid in pendientes:
        try:
            slot = approval.aprobar(cx, qid, user_id=user["id"])
            aprobadas.append({"queue_id": qid, "slot": slot.isoformat()})
        except (ValueError, RuntimeError):
            # Mensaje interno nunca se expone (puede traer detalle del Sheet);
            # el front muestra cuántas fallaron y el usuario reintenta.
            fallidas.append(qid)

    restantes = cx.execute(
        "SELECT COUNT(*) FROM content_queue WHERE plan_id = ? "
        "AND status != 'descartado' AND aprobacion = 'pendiente'", (pid,)).fetchone()[0]
    estado = plan["estado"]
    if restantes == 0 and aprobadas:
        db.update(cx, "content_plans", pid, estado="aprobado")
        estado = "aprobado"
    return {"aprobadas": aprobadas, "fallidas": fallidas, "plan_estado": estado}
