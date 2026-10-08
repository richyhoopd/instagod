"""Assets de la marca para el editor v2: buscar en proveedores, importar a la
biblioteca, subir, descartar y quitar fondo (job). Los bytes se sirven en
GET /brands/{slug}/files/assets/{archivo} (plan 1), no aquí."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, no_encontrado
from src import db, jobs
from src.assets import Candidata, biblioteca, buscar
from src.assets.proveedores import PROVEEDORES

router = APIRouter(prefix="/brands/{slug}", tags=["assets"])

_CHUNK = 64 * 1024


def _con_src(fila: dict) -> dict:
    return {**dict(fila), "src": f"assets/{fila['archivo']}"}


def _asset_de_marca(cx, account_id: int, aid: int) -> dict:
    fila = db.get(cx, "brand_assets", aid)
    if fila is None or fila["account_id"] != account_id:
        raise no_encontrado("ese asset")
    return dict(fila)


class CandidataIn(BaseModel):
    proveedor: str
    id_origen: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    tipo: Literal["imagen", "video"]
    url: str = Field(max_length=2000)
    preview_url: str = Field("", max_length=2000)
    ancho: int | None = None
    alto: int | None = None
    autor: str | None = Field(None, max_length=200)
    licencia: str | None = Field(None, max_length=100)
    url_origen: str | None = Field(None, max_length=2000)
    ig_handle: str | None = Field(None, max_length=60)
    source_post_id: str | None = Field(None, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)


class AssetPatch(BaseModel):
    descartada: bool


@router.get("/assets/buscar")
def buscar_assets(slug: str, q: str = Query(..., min_length=1, max_length=200),
                  tipo: Literal["imagen", "video"] = "imagen",
                  proveedores: str | None = Query(None, max_length=200),
                  n: int = Query(20, ge=1, le=60),
                  user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    lista = [p.strip() for p in proveedores.split(",") if p.strip()] if proveedores else None
    resultados, avisos = buscar.buscar_con_avisos(cx, marca["id"], marca["slug"], q, tipo=tipo,
                                                  proveedores=lista, n=n)
    return {"resultados": [c.a_dict() for c in resultados], "avisos": avisos}


@router.get("/assets")
def listar_assets(slug: str, tipo: Literal["imagen", "video"] | None = None,
                  user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    sql = "SELECT * FROM brand_assets WHERE account_id = ? AND descartada = 0"
    params: list = [marca["id"]]
    if tipo:
        sql += " AND tipo = ?"
        params.append(tipo)
    return [_con_src(f) for f in db.rows(cx, sql + " ORDER BY id DESC LIMIT 500", tuple(params))]


@router.post("/assets/importar", status_code=201)
def importar_asset(slug: str, datos: CandidataIn, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    if datos.proveedor not in PROVEEDORES:
        raise ApiError(422, "validacion", "Proveedor desconocido", "proveedor")
    es_local = datos.url.startswith("local:")
    if es_local != (datos.proveedor == "carpeta") or (
            not es_local and not datos.url.startswith("https://")):
        raise ApiError(422, "validacion", "URL inválida para ese proveedor", "url")
    cand = Candidata(**datos.model_dump(exclude={"tags"}))
    tags = [t.strip()[:40] for t in datos.tags if t.strip()] or None
    try:
        fila = biblioteca.importar(cx, marca["id"], marca["slug"], cand, tags=tags)
    except biblioteca.AssetInvalido as e:
        if str(e).startswith("descarga falló"):
            raise ApiError(502, "origen", str(e)[:200]) from e
        raise ApiError(422, "validacion", str(e)[:200], "url") from e
    return _con_src(fila)


@router.post("/assets/subir", status_code=201)
def subir_asset(slug: str, archivo: UploadFile = File(...),
                user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    tope = max(biblioteca.TOPES.values())
    demasiado = ApiError(413, "validacion", "archivo demasiado grande", "archivo")
    if archivo.size is not None and archivo.size > tope:
        raise demasiado
    datos = bytearray()
    while chunk := archivo.file.read(_CHUNK):
        datos += chunk
        if len(datos) > tope:
            raise demasiado
    try:
        fila, _ = biblioteca.guardar_bytes(cx, marca["id"], marca["slug"], bytes(datos),
                                           proveedor="subida", meta={"licencia": "propia"})
    except biblioteca.AssetInvalido as e:
        raise ApiError(422, "validacion", str(e)[:200], "archivo") from e
    return _con_src(fila)


@router.patch("/assets/{aid}")
def editar_asset(slug: str, aid: int, datos: AssetPatch, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    _asset_de_marca(cx, marca["id"], aid)
    db.update(cx, "brand_assets", aid, descartada=int(datos.descartada))
    cx.commit()
    return _con_src(db.get(cx, "brand_assets", aid))


@router.post("/assets/{aid}/recorte", status_code=202)
def recortar_asset(slug: str, aid: int, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, minimo="manager")
    asset = _asset_de_marca(cx, marca["id"], aid)
    if asset["tipo"] != "imagen":
        raise ApiError(422, "validacion", "Solo se puede quitar el fondo a imágenes", "tipo")
    if asset["descartada"]:
        raise ApiError(409, "conflicto", "El asset está descartado")
    jid = jobs.crear(cx, "asset.recorte", marca["id"], {"asset_id": aid},
                     creado_por=user["id"])
    return {"job_id": jid}
