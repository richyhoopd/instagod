"""Trabajos asíncronos del portal: slideshows y su cola de jobs."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, no_encontrado
from src import db, jobs, marcas

router = APIRouter(prefix="/brands/{slug}", tags=["trabajos"])

_CAMPOS_JOB = ("id", "tipo", "estado", "progreso", "log", "queue_id", "created_at", "finished_at")


def _resumen(fila: dict) -> dict:
    return {k: fila.get(k) for k in _CAMPOS_JOB}


def _job_de_marca(cx, account_id: int, jid: int) -> dict:
    fila = db.get(cx, "jobs", jid)
    if fila is None or fila["account_id"] != account_id:
        raise no_encontrado("ese trabajo")
    return fila


class NuevoSlideshow(BaseModel):
    tema: str = Field(min_length=3)
    formato: str | None = None
    estilo: str | None = None
    fuentes: list[str] | None = None
    n_slides: int = Field(default=6, ge=1, le=10)
    aspect: str = "4:5"
    contexto: str | None = None


@router.post("/slideshows", status_code=202)
def crear_slideshow(slug: str, datos: NuevoSlideshow, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    m = marcas.cargar_por_id(cx, fila["id"])

    formato = datos.formato or m.formatos[0]
    if formato not in m.formatos:
        raise ApiError(422, "validacion", f"Formato no habilitado: {formato}", "formato")

    estilos = marcas.estilos_de(m)
    estilo = datos.estilo or (next(iter(m.estilos), None) or "tiktok_bold")
    if estilo not in estilos:
        raise ApiError(422, "validacion", f"Estilo inexistente: {estilo}", "estilo")

    fuentes = datos.fuentes if datos.fuentes is not None else m.fuentes
    payload = {"tema": datos.tema, "formato": formato, "estilo": estilo, "fuentes": fuentes,
              "n_slides": datos.n_slides, "aspect": datos.aspect, "contexto": datos.contexto}
    job_id = jobs.crear(cx, "slideshow.generar", fila["id"], payload, creado_por=user["id"])
    return {"job_id": job_id}


@router.get("/jobs")
def listar_jobs(slug: str, estado: str | None = None, user: dict = Depends(usuario_actual),
                cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    sql = "SELECT * FROM jobs WHERE account_id = ?"
    params: list = [fila["id"]]
    if estado:
        sql += " AND estado = ?"
        params.append(estado)
    sql += " ORDER BY id DESC"
    return [_resumen(f) for f in db.rows(cx, sql, params)]


@router.get("/jobs/{jid}")
def detalle_job(slug: str, jid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    return _job_de_marca(cx, fila["id"], jid)


@router.post("/jobs/{jid}/cancel")
def cancelar_job(slug: str, jid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    _job_de_marca(cx, fila["id"], jid)
    if not jobs.cancelar(cx, jid):
        raise ApiError(422, "validacion", "No se puede cancelar: el job ya no está en cola")
    return {"ok": True}
