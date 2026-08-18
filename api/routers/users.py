"""Administración de usuarios (solo admin)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field

from api import mail
from api.deps import get_cx, requiere_admin
from api.errors import ApiError, conflicto, no_encontrado
from src import db, users

router = APIRouter(prefix="/users", tags=["users"], dependencies=[Depends(requiere_admin)])


class MarcaRol(BaseModel):
    slug: str
    rol: str


class Invitar(BaseModel):
    email: EmailStr
    nombre: str | None = None
    is_admin: bool = False
    marcas: list[MarcaRol] = Field(default_factory=list)


class Editar(BaseModel):
    nombre: str | None = None
    activo: bool | None = None
    is_admin: bool | None = None
    marcas: list[MarcaRol] | None = None


def _resolver_marcas(cx, marcas: list[MarcaRol]) -> list[tuple[int, str]]:
    out = []
    for m in marcas:
        if m.rol not in users.ROLES:
            raise ApiError(422, "validacion", f"Rol inválido: {m.rol}", "rol")
        fila = db.get_account(cx, m.slug)
        if not fila:
            raise no_encontrado(f"la marca {m.slug!r}")
        out.append((fila["id"], m.rol))
    return out


def _vista(cx, uid: int) -> dict:
    u = users.por_id(cx, uid)
    u["marcas"] = users.marcas_de(cx, uid)
    return u


def _mandar_link(cx, request: Request, uid: int, email: str) -> None:
    tok = users.crear_magic_link(cx, uid)
    mail.enviar_magic_link(email, str(request.url_for("auth_callback")) + f"?token={tok}")


@router.get("")
def listar(cx=Depends(get_cx)) -> list[dict]:
    return users.listar(cx)


@router.post("/invite", status_code=201)
def invitar(datos: Invitar, request: Request, cx=Depends(get_cx)) -> dict:
    asignaciones = _resolver_marcas(cx, datos.marcas)
    try:
        uid = users.crear_usuario(cx, datos.email, datos.nombre, is_admin=datos.is_admin)
    except ValueError as e:
        raise conflicto(str(e), "email") from e
    for account_id, rol in asignaciones:
        users.asignar_marca(cx, uid, account_id, rol)
    _mandar_link(cx, request, uid, datos.email.lower())
    return _vista(cx, uid)


@router.patch("/{uid}")
def editar(uid: int, datos: Editar, cx=Depends(get_cx)) -> dict:
    if not users.por_id(cx, uid):
        raise no_encontrado(f"el usuario {uid}")
    campos = {}
    if datos.nombre is not None:
        campos["nombre"] = datos.nombre.strip() or None
    if datos.activo is not None:
        campos["activo"] = 1 if datos.activo else 0
    if datos.is_admin is not None:
        campos["is_admin"] = 1 if datos.is_admin else 0
    if campos:
        db.update(cx, "users", uid, **campos)
    if datos.marcas is not None:
        nuevas = _resolver_marcas(cx, datos.marcas)
        for m in users.marcas_de(cx, uid):
            users.quitar_marca(cx, uid, m["account_id"])
        for account_id, rol in nuevas:
            users.asignar_marca(cx, uid, account_id, rol)
    return _vista(cx, uid)


@router.post("/{uid}/reinvitar")
def reinvitar(uid: int, request: Request, cx=Depends(get_cx)) -> dict:
    u = users.por_id(cx, uid)
    if not u:
        raise no_encontrado(f"el usuario {uid}")
    _mandar_link(cx, request, uid, u["email"])
    return {"ok": True}


@router.delete("/{uid}/sessions")
def cerrar_sesiones(uid: int, cx=Depends(get_cx)) -> dict:
    if not users.por_id(cx, uid):
        raise no_encontrado(f"el usuario {uid}")
    return {"cerradas": users.cerrar_sesiones_de(cx, uid)}
