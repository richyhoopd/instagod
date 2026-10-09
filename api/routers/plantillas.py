"""Endpoints de plantillas/diseños del portal."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import no_encontrado
from api.routers.brands import _SLUG_RE
from api.routers.fuentes_api import listar_photos
from src import compose, jobs, marcas, plantillas
from src.image_sources import BRANDS_DIR
from src.plantillas import contrato as contrato_mod
from src.plantillas import escena as escena_mod
from src.plantillas import fuentes_tipograficas, preview

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
                         None, pattern="^(activa|borrador|archivada|todas)$"),
                     user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    # Sin parámetro sigue siendo «activas» (lo usa el creador de posts);
    # el editor pide `todas` para su lista. `listar` filtra siempre por la
    # cuenta de la marca, `todas` solo quita el filtro de estado.
    filtro = None if estado == "todas" else (estado or "activa")
    activas = plantillas.listar(cx, fila["id"], estado=filtro)
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
    aspecto: str = Field(pattern="^(4:5|1:1|9:16)$")
    layout: dict[str, Any] | None = None
    contrato: dict[str, Any] | None = None


class DisenoGuardado(BaseModel):
    layout: dict[str, Any]
    contrato: dict[str, Any] | None = None
    mensaje: str | None = Field(default=None, max_length=200)


class VistaPrevia(BaseModel):
    layout: dict[str, Any]
    contrato: dict[str, Any] | None = None
    aspecto: str = Field(pattern="^(4:5|1:1|9:16)$")


class MensajeChat(BaseModel):
    mensaje: str = Field(min_length=1, max_length=2000)
    modo: Literal["crear", "editar"] = "editar"
    escena: dict | None = None
    formato: Literal["4x5", "1x1", "9x16"] | None = None


class PedirDiseno(BaseModel):
    instruccion: str = Field(min_length=1, max_length=2000)
    aspecto: str = Field(pattern="^(4:5|1:1|9:16)$")
    template_id: int | None = None


def _vista(fila) -> dict[str, Any]:
    """Cómo ve el portal un diseño. Nunca expone el HTML: es derivado.

    Un layout guardado que no se puede convertir a v2 (malformado en la BD) no
    tumba la lectura: sale `layout: None`, `editable: False` y el motivo en
    `layout_error`. La BD no se toca; el diseño se puede duplicar o sustituir.
    """
    try:
        layout, error = plantillas.escena_de(fila), None
    except escena_mod.EscenaInvalida as exc:
        layout, error = None, str(exc)
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "descripcion": fila["descripcion"],
        "aspecto": fila["aspecto"],
        "estado": fila["estado"],
        "version_actual": fila["version_actual"],
        "contrato": plantillas.contrato_de(fila),
        "layout": layout,
        "editable": error is None and plantillas.es_editable(fila),
        "layout_error": error,
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
    layout_dict = cuerpo.layout or escena_mod.normalizar(None, cuerpo.aspecto)
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
    lienzo = cuerpo.layout.get("lienzo")
    # Sin guardas de tipo: un lienzo str o un formato lista se dejan pasar tal
    # cual y `nueva_version` los rechaza con 422 al validar.
    formato = (lienzo.get("formato")
               if cuerpo.layout.get("v") == 2 and isinstance(lienzo, dict) else None)
    if (cuerpo.contrato is None and isinstance(formato, str)
            and formato in escena_mod.ASPECTO_DE_FORMATO):
        # El editor cambia de formato sin mandar el contrato: el aspecto lo
        # dicta el lienzo, y `nueva_version` lo copia a brand_templates.aspecto.
        contrato_dict = {**contrato_dict, "aspecto": escena_mod.ASPECTO_DE_FORMATO[formato]}
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
        # `plantillas.validar_diseno` (v1 o v2) no revisa el aspecto, y
        # `a_html` lo indexa a pelo (`LIENZO[contrato["aspecto"]]`,
        # src/plantillas/layout.py:371).
        contrato_mod.validar(contrato_dict)
        plantillas.validar_diseno(
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
    """OBSOLETO desde editor v2: lo reemplaza POST /templates/{tid}/chat. Se borra cuando v2 esté en prod.

    Encola al asistente: le pide un diseño al modelo y devuelve las capas.

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
    # Crudo, no `escena_de`: la copia conserva el layout tal cual (v1 sigue v1,
    # v2 sigue v2); convertir de más reescribiría el diseño sin que nadie lo pida.
    layout_existente = plantillas.layout_de(fila)
    if layout_existente is None:
        # Legacy sin capas: la copia arranca un lienzo en blanco, editable.
        layout_nuevo = escena_mod.normalizar(None, fila["aspecto"])
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


@router.post("/templates/{tid}/chat", status_code=202)
def chat_diseno(slug: str, tid: int, cuerpo: MensajeChat, user: dict = Depends(usuario_actual),
                cx=Depends(get_cx)) -> dict:
    """Un mensaje del chat del editor v2 (crear o editar). Aislamiento antes de encolar."""
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    fila = _plantilla_de_marca(cx, marca["id"], tid)
    # El chat escribe directo en la plantilla: solo en borradores.
    if fila["estado"] != "borrador":
        raise HTTPException(409, "El chat solo funciona en borradores.")
    job_id = jobs.crear(cx, "diseno.chat", marca["id"],
                        {"template_id": tid, **cuerpo.model_dump()}, creado_por=user["id"])
    return {"job_id": job_id}


@router.get("/templates/{tid}/chat")
def historial_chat(slug: str, tid: int, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> list[dict]:
    """Historial del chat: las versiones que nacieron de un mensaje, en orden."""
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _plantilla_de_marca(cx, marca["id"], tid)
    out = []
    for f in plantillas.versiones(cx, tid):
        meta = json.loads(f.get("llm_meta") or "{}")
        if not f.get("mensaje_usuario") or "modo" not in meta:
            continue
        out.append({"version": f["version"], "mensaje": f["mensaje_usuario"],
                    "respuesta": meta.get("respuesta"), "modo": meta["modo"],
                    "kind": meta.get("kind"), "creado_en": f.get("creado_en")})
    return out


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


_TIPO_ASSET = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml",
               ".mp4": "video/mp4", ".webm": "video/webm"}
_ARCHIVO_ASSET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


@router.get("/files/assets/{archivo}")
def archivo_asset(slug: str, archivo: str, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> FileResponse:
    """Los bytes de una imagen o video de la biblioteca de la marca.

    Es lo que pinta el lienzo del editor para una capa con `src: assets/<archivo>`.
    Mismo blindaje que `archivo_fuente`: nombre por regex (fullmatch: un salto de
    línea al final no pasa), ruta resuelta dentro de la carpeta de ESTA marca (un
    symlink que apunte fuera no pasa) y lista blanca de extensiones. El SVG va con
    CSP sandbox: abierto directo en el navegador no puede correr scripts.
    """
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    if not _SLUG_RE.match(marca["slug"]) or not _ARCHIVO_ASSET.fullmatch(archivo):
        raise no_encontrado("ese archivo")
    carpeta = (BRANDS_DIR / marca["slug"] / "assets").resolve()
    ruta = (carpeta / archivo).resolve()
    tipo = _TIPO_ASSET.get(ruta.suffix.lower())
    if tipo is None or not ruta.is_relative_to(carpeta) or not ruta.is_file():
        raise no_encontrado("ese archivo")
    headers = {"X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=86400"}
    if tipo == "image/svg+xml":
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'; sandbox")
    return FileResponse(ruta, media_type=tipo, headers=headers)


@router.get("/stickers")
def listar_stickers(slug: str, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> list[dict]:
    """Las fotos de la marca, para arrastrarlas como sticker en el editor."""
    marca_para(slug, cx, user, minimo="manager")
    fotos = listar_photos(slug, user=user, cx=cx)
    return [{"nombre": f["nombre"], "url": f["url"]} for f in fotos]
