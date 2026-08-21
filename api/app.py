"""API JSON del portal de colaboradores. Uso: uvicorn api.app:app --port 8100"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from api.errors import ApiError, manejar_api_error
from api.ratelimit import Limitador
from api.routers import auth, brands, cola, pruebas, secrets, system, trabajos, users
from src import db


@asynccontextmanager
async def _lifespan(app: FastAPI):
    cx = db.connect()
    try:
        db.init_db(cx)
    finally:
        cx.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="instagod API", docs_url="/docs", redoc_url=None, lifespan=_lifespan)
    # Rate limiters en app.state (no globals de módulo): cada create_app()
    # arranca con contadores limpios, aislados entre apps/tests.
    app.state.limite_email = Limitador(5, 3600)
    app.state.limite_ip = Limitador(5, 3600)
    app.add_exception_handler(ApiError, manejar_api_error)
    app.add_middleware(CORSMiddleware, allow_origins=[config.APP_URL], allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(RequestValidationError)
    async def _validacion(_, exc: RequestValidationError):
        e = exc.errors()[0] if exc.errors() else {}
        campo = ".".join(str(p) for p in e.get("loc", [])[1:]) or None
        return JSONResponse({"error": "validacion", "detalle": e.get("msg", "Datos inválidos"),
                             "campo": campo}, status_code=422)

    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(brands.router)
    app.include_router(secrets.router)
    app.include_router(pruebas.router)
    app.include_router(cola.router)
    app.include_router(trabajos.router)
    return app


app = create_app()
