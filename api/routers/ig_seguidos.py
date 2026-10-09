"""Fuente «Seguidos de IG» por marca: curar cuentas y encolar importación/ingesta.

Lo que pega a Instagram va SIEMPRE por la cola (carril IG global, jobs.TIPOS_IG);
este router nunca hace requests a IG.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError
from src import jobs
from src.assets import ig_seguidos

router = APIRouter(prefix="/brands/{slug}/fuentes/ig", tags=["ig_seguidos"])

Estado = Literal["candidata", "activa", "descartada"]


class CuentaIn(BaseModel):
    ig_handle: str
    estado: Estado = "activa"


class ImportarIn(BaseModel):
    semilla: str
    limite: int = Field(200, ge=1, le=2000)


class IngerirIn(BaseModel):
    por_cuenta: int = Field(12, ge=1, le=50)


def _handle(texto: str, campo: str) -> str:
    try:
        return ig_seguidos.normalizar_handle(texto)
    except ValueError as e:
        raise ApiError(422, "validacion", str(e), campo) from e


@router.get("/cuentas")
def listar_cuentas(slug: str, estado: Estado | None = None,
                   user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user, minimo="editor")
    return ig_seguidos.listar(cx, fila["id"], estado=estado)


@router.post("/cuentas")
def fijar_cuenta(slug: str, datos: CuentaIn,
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    return ig_seguidos.fijar_estado(cx, fila["id"], _handle(datos.ig_handle, "ig_handle"),
                                    datos.estado)


@router.post("/importar-seguidos", status_code=202)
def importar_seguidos(slug: str, datos: ImportarIn,
                      user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    payload = {"semilla": _handle(datos.semilla, "semilla"), "limite": datos.limite}
    return {"job_id": jobs.crear(cx, "ig.importar_seguidos", fila["id"], payload,
                                 creado_por=user["id"])}


@router.post("/ingerir", status_code=202)
def ingerir(slug: str, datos: IngerirIn,
            user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    return {"job_id": jobs.crear(cx, "ig.ingerir", fila["id"],
                                 {"por_cuenta": datos.por_cuenta}, creado_por=user["id"])}
