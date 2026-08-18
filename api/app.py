"""API JSON del portal de colaboradores. Uso: uvicorn api.app:app --port 8100"""
from __future__ import annotations

import importlib

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from api.errors import ApiError, manejar_api_error
from api.routers import auth, system
from src import db


def create_app() -> FastAPI:
    # auth.py guarda el rate limiter en globals del módulo; recargarlo aquí
    # da contadores limpios en cada create_app() (cada test de api_cliente
    # reimporta api.app, pero un módulo ya en sys.modules no se recarga solo).
    importlib.reload(system)
    importlib.reload(auth)

    app = FastAPI(title="instagod API", docs_url="/docs", redoc_url=None)
    app.add_exception_handler(ApiError, manejar_api_error)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_, exc: RequestValidationError):
        e = exc.errors()[0] if exc.errors() else {}
        campo = ".".join(str(p) for p in e.get("loc", [])[1:]) or None
        return JSONResponse({"error": "validacion", "detalle": e.get("msg", "Datos inválidos"),
                             "campo": campo}, status_code=422)

    @app.on_event("startup")
    def _startup() -> None:
        cx = db.connect()
        try:
            db.init_db(cx)
        finally:
            cx.close()

    app.include_router(system.router)
    app.include_router(auth.router)
    return app


app = create_app()
