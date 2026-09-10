"""Endpoints de plantillas/diseños del portal."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import no_encontrado
from api.routers.fuentes_api import listar_photos
from src import marcas, plantillas
from src.plantillas import contrato as contrato_mod
from src.plantillas import fuentes_tipograficas, preview
from src.plantillas import layout as layout_mod

router = APIRouter(prefix="/brands/{slug}", tags=["posts"])


def _plantilla_de_marca(cx, account_id: int, template_id: int) -> dict:
    """Fila de brand_templates, o 404 si no existe o es de otra cuenta.

    El aislamiento entre marcas es la parte que más importa de este router:
    un template_id ajeno debe fallar ANTES de encolar nada o de tocar disco.
    """
    tpl = plantillas.obtener(cx, template_id)
    if tpl is None or tpl["account_id"] != account_id:
        raise no_encontrado("ese diseño")
    return tpl


@router.get("/templates")
def listar_templates(slug: str,
                     estado: str | None = Query(
                         None, pattern="^(activa|borrador|archivada)$"),
                     user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    activas = plantillas.listar(cx, fila["id"], estado=estado or "activa")
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
        raise no_encontrado("ese diseño")
    return FileResponse(png, media_type="image/png",
                        headers={"Cache-Control": "private, max-age=300"})


# ---------------------------------------------------------------------------
# Editor visual: crear, guardar versiones, historial, revertir, publicar.
# ---------------------------------------------------------------------------

class DisenoNuevo(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    aspecto: str = Field(pattern="^(4:5|9:16)$")
    layout: dict[str, Any] | None = None
    contrato: dict[str, Any] | None = None


class DisenoGuardado(BaseModel):
    layout: dict[str, Any]
    contrato: dict[str, Any] | None = None
    mensaje: str | None = Field(default=None, max_length=200)


def _vista(fila) -> dict[str, Any]:
    """Cómo ve el portal un diseño. Nunca expone el HTML: es derivado."""
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "descripcion": fila["descripcion"],
        "aspecto": fila["aspecto"],
        "estado": fila["estado"],
        "version_actual": fila["version_actual"],
        "contrato": plantillas.contrato_de(fila),
        "layout": plantillas.layout_de(fila),
        "editable": plantillas.es_editable(fila),
    }


def _version_vista(fila) -> dict[str, Any]:
    return {"version": fila["version"], "mensaje": fila["mensaje_usuario"],
            "creado_en": fila["creado_en"]}


@router.get("/templates/{tid}")
def obtener_diseno(slug: str, tid: int, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    fila = _plantilla_de_marca(cx, marca["id"], tid)
    return _vista(fila)


@router.post("/templates", status_code=201)
def crear_diseno(slug: str, cuerpo: DisenoNuevo, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    contrato_dict = cuerpo.contrato or {
        "aspecto": cuerpo.aspecto,
        "base": list(contrato_mod.CAMPOS_BASE),
        "extras": [],
    }
    layout_dict = cuerpo.layout or layout_mod.vacio(cuerpo.aspecto)
    try:
        tid = plantillas.crear(cx, marca["id"], cuerpo.nombre, "",
                               contrato_dict, layout=layout_dict,
                               creado_por=user["id"])
    except contrato_mod.ContratoInvalido as exc:
        raise HTTPException(422, str(exc)) from exc
    return _vista(plantillas.obtener(cx, tid))


@router.patch("/templates/{tid}")
def guardar_diseno(slug: str, tid: int, cuerpo: DisenoGuardado,
                   user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    fila = _plantilla_de_marca(cx, marca["id"], tid)
    contrato_dict = cuerpo.contrato or plantillas.contrato_de(fila)
    try:
        plantillas.nueva_version(cx, tid, "", contrato_dict,
                                 mensaje_usuario=cuerpo.mensaje,
                                 layout=cuerpo.layout)
    except contrato_mod.ContratoInvalido as exc:
        raise HTTPException(422, str(exc)) from exc
    return _vista(plantillas.obtener(cx, tid))


@router.post("/templates/{tid}/duplicate", status_code=201)
def duplicar_diseno(slug: str, tid: int, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    fila = _plantilla_de_marca(cx, marca["id"], tid)
    layout_existente = plantillas.layout_de(fila)
    if layout_existente is None:
        # Legacy sin capas: la copia arranca un lienzo en blanco, editable.
        layout_nuevo = layout_mod.vacio(fila["aspecto"])
        nombre_nuevo = f"{fila['nombre']} (editable)"
    else:
        layout_nuevo = layout_existente
        nombre_nuevo = f"{fila['nombre']} (copia)"
    contrato_dict = plantillas.contrato_de(fila)
    try:
        tid_nuevo = plantillas.crear(cx, marca["id"], nombre_nuevo, "",
                                     contrato_dict, descripcion=fila["descripcion"],
                                     layout=layout_nuevo, creado_por=user["id"])
    except contrato_mod.ContratoInvalido as exc:
        raise HTTPException(422, str(exc)) from exc
    return _vista(plantillas.obtener(cx, tid_nuevo))


@router.get("/templates/{tid}/versions")
def listar_versiones(slug: str, tid: int, user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> list[dict]:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _plantilla_de_marca(cx, marca["id"], tid)
    filas = plantillas.versiones(cx, tid)
    # Historial: la más reciente primero, como cualquier persona lo espera.
    return [_version_vista(f) for f in reversed(filas)]


@router.post("/templates/{tid}/revert/{n}")
def revertir_diseno(slug: str, tid: int, n: int, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _plantilla_de_marca(cx, marca["id"], tid)
    try:
        plantillas.revertir(cx, tid, n)
    except ValueError as exc:
        raise no_encontrado("esa versión") from exc
    return _vista(plantillas.obtener(cx, tid))


@router.post("/templates/{tid}/activate")
def activar_diseno(slug: str, tid: int, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _plantilla_de_marca(cx, marca["id"], tid)
    plantillas.activar(cx, tid)
    return _vista(plantillas.obtener(cx, tid))


@router.post("/templates/{tid}/archive")
def archivar_diseno(slug: str, tid: int, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _plantilla_de_marca(cx, marca["id"], tid)
    plantillas.archivar(cx, tid)
    return _vista(plantillas.obtener(cx, tid))


@router.get("/fonts")
def listar_fuentes(slug: str, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> list[dict]:
    """Catálogo de tipografías (globales + propias) para el selector del editor."""
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    return [{"familia": f["familia"], "propia": f["propia"]}
            for f in fuentes_tipograficas.catalogo(cx, marca["id"])]


@router.get("/stickers")
def listar_stickers(slug: str, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> list[dict]:
    """Las fotos de la marca, para arrastrarlas como sticker en el editor."""
    marca_para(slug, cx, user, minimo="manager")
    fotos = listar_photos(slug, user=user, cx=cx)
    return [{"nombre": f["nombre"], "url": f["url"]} for f in fotos]
