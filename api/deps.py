"""Dependencias FastAPI: conexión, usuario de la cookie, permisos por marca."""
from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, Request

from api.errors import no_autenticado, no_encontrado, sin_permiso
from src import db, users

COOKIE = "instagod_session"
_ORDEN_ROL = {"editor": 1, "manager": 2, "admin": 3}


def get_cx() -> Iterator:
    cx = db.connect()
    try:
        yield cx
    finally:
        cx.close()


def usuario_actual(request: Request, cx=Depends(get_cx)) -> dict:
    u = users.usuario_de_sesion(cx, request.cookies.get(COOKIE, ""))
    if not u:
        raise no_autenticado()
    return u


def requiere_admin(user: dict = Depends(usuario_actual)) -> dict:
    if not user.get("is_admin"):
        raise sin_permiso("Solo administradores")
    return user


def marca_para(slug: str, cx, user: dict, minimo: str = "editor") -> tuple[dict, str]:
    """Fila de accounts + rol efectivo del usuario. 404 si no existe, 403 si no alcanza."""
    fila = db.get_account(cx, slug)
    if not fila:
        raise no_encontrado(f"la marca {slug!r}")
    rol = users.rol_en(cx, user, fila["id"])
    if not rol or _ORDEN_ROL[rol] < _ORDEN_ROL[minimo]:
        raise sin_permiso()
    return fila, rol
