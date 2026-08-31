"""Post simple: encolar generación y servir plantillas/preview del portal."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import no_encontrado
from src import jobs, marcas, plantillas
from src.plantillas import preview

router = APIRouter(prefix="/brands/{slug}", tags=["posts"])


def _plantilla_de_marca(cx, account_id: int, template_id: int) -> dict:
    """Fila de brand_templates, o 404 si no existe o es de otra cuenta.

    El aislamiento entre marcas es la parte que más importa de este router:
    un template_id ajeno debe fallar ANTES de encolar nada o de tocar disco.
    """
    tpl = plantillas.obtener(cx, template_id)
    if tpl is None or tpl["account_id"] != account_id:
        raise no_encontrado("esa plantilla")
    return tpl


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


@router.get("/templates")
def listar_templates(slug: str, user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    activas = plantillas.listar(cx, fila["id"], estado="activa")
    return [
        {
            "id": t["id"],
            "slug": t["slug"],
            "nombre": t["nombre"],
            "descripcion": t["descripcion"],
            "aspecto": t["aspecto"],
            "version_actual": t["version_actual"],
            "contrato": plantillas.contrato_de(t),
        }
        for t in activas
    ]


@router.get("/templates/{tid}/preview.png")
def preview_template(slug: str, tid: int, user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> FileResponse:
    """Preview cacheado (src/plantillas/preview.py) con datos de muestra."""
    fila, _ = marca_para(slug, cx, user)
    m = marcas.cargar_por_id(cx, fila["id"])
    try:
        png = preview.png_de(cx, m, tid)
    except ValueError:
        raise no_encontrado("esa plantilla")
    return FileResponse(png, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})
