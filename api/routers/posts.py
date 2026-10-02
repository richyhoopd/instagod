"""Post simple: encolar generación."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.routers.plantillas import _plantilla_de_marca
from src import jobs

router = APIRouter(prefix="/brands/{slug}", tags=["posts"])


class NuevoPost(BaseModel):
    template_id: int
    tema: str = Field(min_length=1)
    entidad_id: int | None = None
    campos: dict[str, Any] | None = None
    imagen: str | None = None


@router.post("/posts", status_code=202)
def crear_post(slug: str, datos: NuevoPost, user: dict = Depends(usuario_actual),
               cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    _plantilla_de_marca(cx, fila["id"], datos.template_id)

    payload: dict[str, Any] = {"template_id": datos.template_id, "tema": datos.tema}
    if datos.entidad_id is not None:
        payload["entidad_id"] = datos.entidad_id
    if datos.campos is not None:
        payload["campos"] = datos.campos
    if datos.imagen is not None:
        payload["imagen"] = datos.imagen

    job_id = jobs.crear(cx, "post.generar", fila["id"], payload, creado_por=user["id"])
    return {"job_id": job_id}
