"""Perfil de marca: prompts del LLM, presets de slideshow (con preview) y logo."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

import config
from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, no_encontrado
from src import db, jobs, marcas, slideshow_script

router = APIRouter(prefix="/brands/{slug}", tags=["perfil"])

_NOMBRE_RE = re.compile(r"^[a-z0-9_]{2,32}$")
_EXT_LOGO = {"png", "svg", "jpg", "jpeg"}
_MAX_LOGO = 2 * 1024 * 1024

# Rutas base (constantes de módulo para poder monkeypatchearlas en tests).
PREVIEWS_DIR = config.BASE_DIR / "data" / "previews"
BRANDS_DIR = config.BASE_DIR / "data" / "brands"


def _valida_nombre_preset(nombre: str) -> None:
    if not _NOMBRE_RE.match(nombre):
        raise ApiError(422, "validacion",
                       "El nombre debe ser minúsculas/dígitos/guion bajo (2-32)", "nombre")


# ---------- prompts ----------

class PromptsIn(BaseModel):
    voz: str = Field(max_length=4000)
    caption_extra: str = Field(default="", max_length=500)
    por_formato: dict[str, str] = Field(default_factory=dict)
    hashtags: list[str] = Field(default_factory=list)

    @field_validator("hashtags")
    @classmethod
    def _valida_hashtags(cls, v):
        if len(v) > 30:
            raise ValueError("máximo 30 hashtags")
        for h in v:
            if not h.startswith("#"):
                raise ValueError("cada hashtag debe empezar con '#'")
        return v


class ProbarIn(BaseModel):
    tema: str = Field(min_length=1, max_length=200)
    formato: str | None = None


def _contexto(m: marcas.Marca, formato: str) -> str:
    partes = [m.voz]
    extra = m.prompts.get("por_formato", {}).get(formato)
    if extra:
        partes.append(extra)
    if m.prompts.get("caption_extra"):
        partes.append(m.prompts["caption_extra"])
    return "\n".join(p for p in partes if p)


def _prueba_fallida(e: Exception, slug: str) -> ApiError:
    creds = config.account_creds(slug)
    detalle = str(e)
    for secreto in (creds.get("LLM_API_KEY"), config.DEEPSEEK_API_KEY, config.ANTHROPIC_API_KEY):
        if secreto:
            detalle = detalle.replace(secreto, "***")
    return ApiError(502, "prueba_fallida",
                    f"No se pudo generar el guion de prueba: {detalle[:200]}")


@router.get("/prompts")
def ver_prompts(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user)
    m = marcas.cargar_por_id(cx, fila["id"])
    return {"voz": m.voz, **m.prompts}


@router.put("/prompts")
def guardar_prompts(slug: str, datos: PromptsIn, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    m = marcas.cargar_por_id(cx, fila["id"])
    invalidos = [f for f in datos.por_formato if f not in m.formatos]
    if invalidos:
        raise ApiError(422, "validacion",
                       f"Formato(s) no habilitados para la marca: {', '.join(invalidos)}",
                       "por_formato")
    prompts = {"caption_extra": datos.caption_extra, "por_formato": datos.por_formato,
              "hashtags": datos.hashtags}
    db.update(cx, "accounts", fila["id"], voz=datos.voz.strip(),
             prompts_json=json.dumps(prompts, ensure_ascii=False))
    m = marcas.cargar_por_id(cx, fila["id"])
    return {"voz": m.voz, **m.prompts}


@router.post("/prompts/probar")
def probar_prompt(slug: str, datos: ProbarIn, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    m = marcas.cargar_por_id(cx, fila["id"])
    formato = datos.formato or m.formatos[0]
    if formato not in m.formatos:
        raise ApiError(422, "validacion", f"Formato no habilitado: {formato}", "formato")
    contexto = _contexto(m, formato)
    try:
        return slideshow_script.generar_guion(datos.tema, formato=formato, n_slides=4,
                                              contexto=contexto)
    except Exception as e:  # noqa: BLE001 — cualquier falla del LLM se redacta y sube 502
        raise _prueba_fallida(e, slug) from e


# ---------- presets ----------

@router.get("/presets")
def listar_presets(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    m = marcas.cargar_por_id(cx, fila["id"])
    catalogo = marcas.estilos_de(m)
    return [{"nombre": nombre, **valor, "propio": nombre in m.estilos}
            for nombre, valor in sorted(catalogo.items())]


@router.put("/presets/{nombre}")
def guardar_preset(slug: str, nombre: str, datos: dict, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    _valida_nombre_preset(nombre)
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    m = marcas.cargar_por_id(cx, fila["id"])
    texto = datos.get("texto")
    if not isinstance(texto, str) or not texto.strip():
        raise ApiError(422, "validacion", "texto es requerido", "texto")
    roles = datos.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise ApiError(422, "validacion", "roles no puede estar vacío", "roles")
    estilos = dict(m.estilos)
    estilos[nombre] = datos
    db.update(cx, "accounts", fila["id"], estilos_json=json.dumps(estilos, ensure_ascii=False))
    return {**datos, "nombre": nombre, "propio": True}


@router.delete("/presets/{nombre}", status_code=204)
def borrar_preset(slug: str, nombre: str, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> None:
    _valida_nombre_preset(nombre)
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    m = marcas.cargar_por_id(cx, fila["id"])
    if nombre not in m.estilos:
        raise no_encontrado(f"el preset propio {nombre!r}")
    estilos = dict(m.estilos)
    del estilos[nombre]
    db.update(cx, "accounts", fila["id"], estilos_json=json.dumps(estilos, ensure_ascii=False))


@router.post("/presets/{nombre}/preview", status_code=202)
def preview_preset(slug: str, nombre: str, datos: dict | None = None,
                   user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    _valida_nombre_preset(nombre)
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    m = marcas.cargar_por_id(cx, fila["id"])
    if nombre not in marcas.estilos_de(m):
        raise no_encontrado(f"el preset {nombre!r}")
    texto = (datos or {}).get("texto", "")
    job_id = jobs.crear(cx, "preset.preview", fila["id"], {"nombre": nombre, "texto": texto},
                        creado_por=user["id"])
    return {"job_id": job_id}


# ---------- logo ----------

@router.post("/logo")
def subir_logo(slug: str, archivo: UploadFile = File(...),
               user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    # Endpoint SÍNCRONO a propósito: la dependencia get_cx abre una conexión
    # sqlite3 en el hilo del threadpool de FastAPI; un handler `async def`
    # correría en el event loop (otro hilo) y sqlite3 la rechaza.
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    nombre = archivo.filename or ""
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if ext not in _EXT_LOGO:
        raise ApiError(422, "validacion",
                       "Formato de logo no soportado (png, svg, jpg)", "archivo")
    contenido = archivo.file.read()
    if len(contenido) > _MAX_LOGO:
        raise ApiError(422, "validacion", "El logo no puede pesar más de 2 MB", "archivo")
    dest_dir = BRANDS_DIR / fila["slug"]
    dest_dir.mkdir(parents=True, exist_ok=True)
    for anterior in dest_dir.glob("logo.*"):
        anterior.unlink()
    dest = dest_dir / f"logo.{ext}"
    dest.write_bytes(contenido)
    rel = f"data/brands/{fila['slug']}/logo.{ext}"
    db.update(cx, "accounts", fila["id"], logo_path=rel)
    return {"logo_path": rel}


# ---------- archivos servidos ----------

@router.get("/files/previews/{nombre}.png")
def archivo_preview(slug: str, nombre: str, user: dict = Depends(usuario_actual),
                    cx=Depends(get_cx)) -> FileResponse:
    _valida_nombre_preset(nombre)
    fila, _ = marca_para(slug, cx, user)
    path = PREVIEWS_DIR / fila["slug"] / f"{nombre}.png"
    if not path.is_file():
        raise no_encontrado("ese preview")
    return FileResponse(path, media_type="image/png")


@router.get("/files/logo")
def archivo_logo(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> FileResponse:
    fila, _ = marca_para(slug, cx, user)
    carpeta = BRANDS_DIR / fila["slug"]
    candidatos = sorted(carpeta.glob("logo.*")) if carpeta.is_dir() else []
    if not candidatos:
        raise no_encontrado("el logo de la marca")
    return FileResponse(candidatos[0])
