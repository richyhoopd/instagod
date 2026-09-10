"""Endpoints de plantillas/diseños del portal."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import no_encontrado
from api.routers.fuentes_api import listar_photos
from src import compose, jobs, marcas, plantillas
from src.image_sources import BRANDS_DIR
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
            "estado": t["estado"],
            "version_actual": t["version_actual"],
            "contrato": plantillas.contrato_de(t),
            "editable": plantillas.es_editable(t),
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


class VistaPrevia(BaseModel):
    layout: dict[str, Any]
    contrato: dict[str, Any] | None = None
    aspecto: str = Field(pattern="^(4:5|9:16)$")


class PedirDiseno(BaseModel):
    instruccion: str = Field(min_length=1, max_length=2000)
    aspecto: str = Field(pattern="^(4:5|9:16)$")
    template_id: int | None = None


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


@router.post("/templates/preview", status_code=202)
def vista_previa(slug: str, cuerpo: VistaPrevia, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    """Encola el trabajo que renderiza el diseño en pantalla, sin guardarlo."""
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    contrato_dict = cuerpo.contrato or {
        "aspecto": cuerpo.aspecto,
        "base": list(contrato_mod.CAMPOS_BASE),
        "extras": [],
    }
    # Se valida aquí, no en el worker: un diseño roto debe dar error en
    # pantalla al instante, no un trabajo que falla treinta segundos después.
    try:
        # El contrato primero, en el mismo orden que `plantillas._validado`:
        # `layout.validar` no revisa el aspecto, y `a_html` lo indexa a pelo
        # (`LIENZO[contrato["aspecto"]]`, src/plantillas/layout.py:371).
        contrato_mod.validar(contrato_dict)
        layout_mod.validar(
            cuerpo.layout, contrato_dict,
            familias=fuentes_tipograficas.familias(cx, marca["id"]))
    except contrato_mod.ContratoInvalido as exc:
        raise HTTPException(422, str(exc)) from exc
    job_id = jobs.crear(cx, "template.preview", marca["id"],
                        {"layout": cuerpo.layout, "contrato": contrato_dict,
                         "aspecto": cuerpo.aspecto},
                        creado_por=user["id"])
    return {"job_id": job_id}


@router.post("/templates/design", status_code=202)
def pedir_diseno(slug: str, cuerpo: PedirDiseno, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    """Encola al asistente: le pide un diseño al modelo y devuelve las capas.

    El asistente propone, no guarda: el handler nunca escribe en
    `brand_templates` ni en `template_versions`, así que aquí no hay nada que
    validar contra un contrato todavía — eso pasa dentro del job, contra el
    diseño que de verdad devuelva el modelo.
    """
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    if cuerpo.template_id is not None:
        # Aislamiento: partir de un diseño ajeno es 404, no un job que falle
        # después dentro del worker.
        _plantilla_de_marca(cx, marca["id"], cuerpo.template_id)
    job_id = jobs.crear(cx, "template.disenar", marca["id"],
                        {"template_id": cuerpo.template_id,
                         "instruccion": cuerpo.instruccion, "aspecto": cuerpo.aspecto},
                        creado_por=user["id"])
    return {"job_id": job_id}


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


# Extensiones que el navegador sabe leer como tipografía. Es lista blanca:
# lo que no esté aquí no se sirve, aunque exista el archivo.
_TIPO_FUENTE = {".ttf": "font/ttf", ".otf": "font/otf",
                ".woff": "font/woff", ".woff2": "font/woff2"}


@router.get("/files/fonts/{familia}")
def archivo_fuente(slug: str, familia: str, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> FileResponse:
    """Los bytes de una tipografía, para que el lienzo del editor dibuje igual que
    el render final.

    Se pide por FAMILIA, que es lo único que el catálogo le da al portal: el
    nombre del archivo se resuelve aquí dentro, así que nada de lo que manda el
    navegador llega a tocar una ruta de disco, y el aislamiento entre marcas sale
    del propio catálogo, que ya es por cuenta.
    """
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    catalogo = {f["familia"]: f
                for f in fuentes_tipograficas.catalogo(cx, marca["id"])}
    fuente = catalogo.get(familia)
    if fuente is None:
        raise no_encontrado("esa tipografía")
    ruta = (Path(fuente["archivo"]) if fuente["propia"]
            else compose.FONTS_DIR / fuente["archivo"])
    ruta = ruta.resolve()
    # El `archivo` de una tipografía propia sale de la BD. El día que se puedan
    # subir por el portal, este endpoint no debe poder convertirse en un lector
    # de archivos arbitrarios: solo se sirve lo que vive en las dos carpetas
    # permitidas y tiene extensión de tipografía.
    carpetas = (compose.FONTS_DIR.resolve(), BRANDS_DIR.resolve())
    if (ruta.suffix.lower() not in _TIPO_FUENTE
            or not any(ruta.is_relative_to(c) for c in carpetas)
            or not ruta.is_file()):
        raise no_encontrado("esa tipografía")
    return FileResponse(ruta, media_type=_TIPO_FUENTE[ruta.suffix.lower()],
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Cache-Control": "public, max-age=604800"})


@router.get("/stickers")
def listar_stickers(slug: str, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> list[dict]:
    """Las fotos de la marca, para arrastrarlas como sticker en el editor."""
    marca_para(slug, cx, user, minimo="manager")
    fotos = listar_photos(slug, user=user, cx=cx)
    return [{"nombre": f["nombre"], "url": f["url"]} for f in fotos]
