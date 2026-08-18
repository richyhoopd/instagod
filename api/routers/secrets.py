"""Secretos por marca (manager+). La API jamás devuelve valores."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, no_encontrado
from src import secrets_store as ss

router = APIRouter(prefix="/brands/{slug}/secrets", tags=["secrets"])


class Valor(BaseModel):
    valor: str


def _requiere_store() -> None:
    if not ss.habilitado():
        raise ApiError(503, "secretos_apagados",
                       "Falta INSTAGOD_MASTER_KEY en el servidor: no se pueden guardar secretos")


def _clave_valida(clave: str) -> None:
    if clave not in ss.CLAVES:
        raise no_encontrado(f"la clave de secreto {clave!r}")


@router.get("")
def listar(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _requiere_store()
    return ss.listar_meta(cx, fila["id"])


@router.put("/{clave}")
def poner(slug: str, clave: str, datos: Valor, user: dict = Depends(usuario_actual),
          cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _clave_valida(clave)
    _requiere_store()
    try:
        ss.guardar(cx, fila["id"], clave, datos.valor, user_id=user["id"])
    except ValueError as e:
        raise ApiError(422, "validacion", str(e), "valor") from e
    return next(m for m in ss.listar_meta(cx, fila["id"]) if m["clave"] == clave)


@router.delete("/{clave}", status_code=204)
def quitar(slug: str, clave: str, user: dict = Depends(usuario_actual),
           cx=Depends(get_cx)) -> Response:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _clave_valida(clave)
    if not ss.borrar(cx, fila["id"], clave):
        raise no_encontrado(f"el secreto {clave} en {slug}")
    return Response(status_code=204)
