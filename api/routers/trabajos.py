"""Trabajos asíncronos del portal: slideshows y su cola de jobs."""
from __future__ import annotations

from typing import Literal

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
    tema: str | None = Field(default=None, min_length=3)
    topic_id: int | None = None
    formato: str | None = None
    estilo: str | None = None
    fuentes: list[str] | None = None
    n_slides: int = Field(default=6, ge=1, le=10)
    aspect: Literal["4:5", "9:16", "1:1", "16:9"] = "4:5"
    contexto: str | None = None


def _topic_de_marca(cx, account_id: int, tid: int) -> dict:
    fila = db.get(cx, "topic_suggestions", tid)
    if fila is None or fila["account_id"] != account_id:
        raise no_encontrado("ese tema")
    return fila


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

    tema = datos.tema
    contexto = datos.contexto
    if datos.topic_id is not None:
        topic = _topic_de_marca(cx, fila["id"], datos.topic_id)
        if topic["descartado"]:
            raise ApiError(422, "validacion", "Ese tema ya fue descartado", "topic_id")
        tema = tema or topic["titulo"]
        if contexto is None:
            # Filtrar None (H7): un topic sin resumen o sin url no debe meter
            # el texto literal "None" en el contexto que ve el LLM.
            contexto = "\n".join(x for x in (topic.get("resumen"), topic.get("url")) if x) or None
    elif not tema:
        raise ApiError(422, "validacion", "tema es requerido si no se da topic_id", "tema")

    fuentes = datos.fuentes if datos.fuentes is not None else m.fuentes
    payload = {"tema": tema, "formato": formato, "estilo": estilo, "fuentes": fuentes,
              "n_slides": datos.n_slides, "aspect": datos.aspect, "contexto": contexto}
    if datos.topic_id is not None:
        payload["topic_id"] = datos.topic_id
    job_id = jobs.crear(cx, "slideshow.generar", fila["id"], payload, creado_por=user["id"])
    return {"job_id": job_id}


class NuevoVideo(BaseModel):
    """Reel narrado: o un topic de la marca, o una historia escrita a mano."""
    topic_id: int | None = None
    titulo: str | None = Field(None, max_length=300)
    cuerpo: str | None = Field(None, max_length=20000)
    sin_llm: bool = False


# Mínimo de palabras que `video_model.validar` exige al guion. Sin LLM el
# cuerpo se narra tal cual, así que se revisa al encolar y no en el worker.
_PALABRAS_MIN_GUION = 20


@router.post("/videos", status_code=202)
def crear_video(slug: str, datos: NuevoVideo, user: dict = Depends(usuario_actual),
                cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    titulo = (datos.titulo or "").strip()
    cuerpo = (datos.cuerpo or "").strip()

    if datos.topic_id is not None:
        if titulo or cuerpo:
            raise ApiError(422, "validacion",
                           "Da un topic_id o una historia escrita, no ambos", "topic_id")
        topic = _topic_de_marca(cx, fila["id"], datos.topic_id)
        if topic["descartado"]:
            raise ApiError(422, "validacion", "Ese tema ya fue descartado", "topic_id")
        # El motor narra el `resumen` del topic; sin él falla al final en el worker.
        if not (topic.get("resumen") or "").strip():
            raise ApiError(422, "validacion", "Ese tema no tiene historia que narrar", "topic_id")
        cuerpo = topic["resumen"]
        payload: dict = {"topic_id": datos.topic_id}
    else:
        if not titulo:
            raise ApiError(422, "validacion", "titulo es requerido si no se da topic_id", "titulo")
        if not cuerpo:
            raise ApiError(422, "validacion", "cuerpo es requerido si no se da topic_id", "cuerpo")
        payload = {"titulo": titulo, "cuerpo": cuerpo}

    if datos.sin_llm:
        if len(cuerpo.split()) < _PALABRAS_MIN_GUION:
            raise ApiError(422, "validacion",
                           f"Sin LLM la historia se narra tal cual: mínimo "
                           f"{_PALABRAS_MIN_GUION} palabras", "cuerpo")
        payload["sin_llm"] = True

    job_id = jobs.crear(cx, "video.generar", fila["id"], payload, creado_por=user["id"])
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
