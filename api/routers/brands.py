"""Marcas: lista por rol, alta (admin), detalle y edición básica (manager)."""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from api.deps import get_cx, marca_para, requiere_admin, usuario_actual
from api.errors import ApiError, conflicto, sin_permiso
from src import db, marcas, users

router = APIRouter(prefix="/brands", tags=["brands"])
_SLUG_RE = re.compile(r"^[a-z0-9_]{2,32}$")
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _handle(v: str) -> str:
    v = (v or "").strip()
    return v if v.startswith("@") else f"@{v}"


class NuevaMarca(BaseModel):
    slug: str
    nombre: str = Field(min_length=1, max_length=80)
    ig_handle: str = Field(min_length=1, max_length=60)
    ciudad: str = "México"
    timezone: str = "America/Mexico_City"
    color_marca: str = "#1b5e3f"

    @field_validator("slug")
    @classmethod
    def _slug(cls, v):
        if not _SLUG_RE.match(v):
            raise ValueError("solo minúsculas, dígitos y guion bajo (2-32)")
        return v

    @field_validator("color_marca")
    @classmethod
    def _color(cls, v):
        if not _COLOR_RE.match(v):
            raise ValueError("color hex #RRGGBB")
        return v


class EditarMarca(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    ig_handle: str | None = Field(default=None, min_length=1, max_length=60)
    ciudad: str | None = None
    timezone: str | None = None
    color_marca: str | None = None
    activa: bool | None = None
    descripcion: str | None = Field(default=None, max_length=600)
    sitio_web: str | None = Field(default=None, max_length=200)
    hashtags_default: str | None = Field(default=None, max_length=400)

    @field_validator("color_marca")
    @classmethod
    def _color(cls, v):
        if v is not None and not _COLOR_RE.match(v):
            raise ValueError("color hex #RRGGBB")
        return v


def _resumen(fila: dict, rol: str) -> dict:
    return {"id": fila["id"], "slug": fila["slug"], "nombre": fila["nombre"],
            "ig_handle": fila["ig_handle"], "ciudad": fila["ciudad"],
            "timezone": fila["timezone"], "color_marca": fila["color_marca"],
            "activa": fila["activa"], "logo_path": fila.get("logo_path"), "rol": rol,
            "creds_faltantes": marcas.claves_faltantes(fila["slug"])}


@router.get("")
def listar(user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    if user["is_admin"]:
        return [_resumen(f, "admin") for f in db.list_accounts(cx, solo_activas=False)]
    return [_resumen(db.get_account(cx, m["slug"]), m["rol"]) for m in users.marcas_de(cx, user["id"])]


@router.post("", status_code=201, dependencies=[Depends(requiere_admin)])
def crear(datos: NuevaMarca, cx=Depends(get_cx)) -> dict:
    if db.get_account(cx, datos.slug):
        raise conflicto(f"Ya existe la marca {datos.slug}", "slug")
    db.insert(cx, "accounts", slug=datos.slug, nombre=datos.nombre.strip(),
              ig_handle=_handle(datos.ig_handle), ciudad=datos.ciudad,
              timezone=datos.timezone, color_marca=datos.color_marca)
    return _resumen(db.get_account(cx, datos.slug), "admin")


@router.get("/{slug}")
def detalle(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, rol = marca_para(slug, cx, user)
    return {**fila, "rol": rol}


@router.patch("/{slug}")
def editar(slug: str, datos: EditarMarca, user: dict = Depends(usuario_actual),
           cx=Depends(get_cx)) -> dict:
    fila, rol = marca_para(slug, cx, user, minimo="manager")
    campos = {k: v for k, v in datos.model_dump().items() if v is not None}
    if "activa" in campos:
        if rol != "admin":
            raise sin_permiso("Solo un admin activa/desactiva marcas")
        campos["activa"] = 1 if campos["activa"] else 0
    if "nombre" in campos:
        campos["nombre"] = campos["nombre"].strip()
        if not campos["nombre"]:
            raise ApiError(422, "validacion", "El nombre no puede quedar vacío", "nombre")
    if "ciudad" in campos:
        campos["ciudad"] = campos["ciudad"].strip()
    if "ig_handle" in campos:
        campos["ig_handle"] = _handle(campos["ig_handle"])
    if campos:
        db.update(cx, "accounts", fila["id"], **campos)
    fila, rol = marca_para(slug, cx, user)
    return {**fila, "rol": rol}
