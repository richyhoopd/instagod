"""Errores JSON uniformes de la API: {error, detalle, campo}."""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, error: str, detalle: str, campo: str | None = None):
        super().__init__(detalle)
        self.status, self.error, self.detalle, self.campo = status, error, detalle, campo

    def cuerpo(self) -> dict:
        return {"error": self.error, "detalle": self.detalle, "campo": self.campo}


def no_autenticado() -> ApiError:
    return ApiError(401, "no_autenticado", "Inicia sesión")


def sin_permiso(detalle: str = "No tienes permiso sobre esta marca") -> ApiError:
    return ApiError(403, "sin_permiso", detalle)


def no_encontrado(que: str) -> ApiError:
    return ApiError(404, "no_encontrado", f"No existe {que}")


def conflicto(detalle: str, campo: str | None = None) -> ApiError:
    return ApiError(409, "conflicto", detalle, campo)


def cred_faltante(clave: str) -> ApiError:
    return ApiError(422, "cred_faltante", f"Falta configurar {clave} en la marca", clave)


async def manejar_api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(exc.cuerpo(), status_code=exc.status)
