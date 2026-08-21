"""Fuentes de contenido (imagen/info), banco de fotos y temas sugeridos por marca."""
from __future__ import annotations

import json
import re
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, no_encontrado
from src import db, fuentes, jobs, topics

router = APIRouter(prefix="/brands/{slug}", tags=["fuentes"])

_EXT_FOTO = {"jpg", "jpeg", "png", "webp"}
_MAX_FOTO = 8 * 1024 * 1024
_MAX_FOTOS_POR_REQUEST = 10
_NOMBRE_FOTO_RE = re.compile(r"^[a-z0-9_.-]+$")
_CHUNK = 64 * 1024


def _leer_con_tope(archivo: UploadFile, tope: int) -> bytes:
    """Lee `archivo` por chunks, abortando con 422 ANTES de tener el archivo
    completo en memoria si supera `tope` (H5)."""
    piezas: list[bytes] = []
    total = 0
    while chunk := archivo.file.read(_CHUNK):
        total += len(chunk)
        if total > tope:
            raise ApiError(422, "validacion", "archivo demasiado grande", "archivos")
        piezas.append(chunk)
    return b"".join(piezas)

_JOB_TIPO_POR_PROVIDER = {
    "rss": "sourcing.rss_fetch",
    "newsapi": "sourcing.newsapi_fetch",
    "ig_accounts": "sourcing.ig_scrape",
}

_MENSAJES_VALIDACION = {
    "provider": "Proveedor no válido para ese tipo de fuente",
    "config": "La configuración no cumple el esquema del proveedor",
    "ids": "La lista de ids debe ser exactamente las fuentes de la marca, sin repetir",
    "fuente": "No existe esa fuente",
}

# Ruta base (constante de módulo para poder monkeypatchearla en tests).
BRANDS_DIR = config.BASE_DIR / "data" / "brands"


def _error_validacion(e: ValueError) -> ApiError:
    campo = str(e)
    return ApiError(422, "validacion", _MENSAJES_VALIDACION.get(campo, campo), campo)


# ---------- sources ----------

class FuenteIn(BaseModel):
    kind: str
    provider: str
    config: dict | None = None
    activa: bool = True


class FuentePatch(BaseModel):
    config: dict | None = None
    activa: bool | None = None


class OrdenIn(BaseModel):
    ids: list[int]


def _resumen_fuente(fila: dict) -> dict:
    return {k: fila.get(k) for k in
            ("id", "kind", "provider", "config", "activa", "orden", "ultimo_run",
             "ultimo_error", "created_at")}


def _fila_fuente(cx, sid: int) -> dict | None:
    fila = db.get(cx, "brand_sources", sid)
    if fila is None:
        return None
    raw = fila.get("config_json")
    try:
        fila["config"] = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        fila["config"] = {}
    return fila


def _fuente_de_marca(cx, account_id: int, sid: int) -> dict:
    fila = _fila_fuente(cx, sid)
    if fila is None or fila["account_id"] != account_id:
        raise no_encontrado("esa fuente")
    return fila


@router.get("/sources")
def listar_sources(slug: str, kind: str | None = None, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    filas = fuentes.listar(cx, fila["id"], kind=kind)
    return [_resumen_fuente(f) for f in filas]


@router.post("/sources", status_code=201)
def crear_source(slug: str, datos: FuenteIn, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    try:
        sid = fuentes.crear(cx, fila["id"], datos.kind, datos.provider, datos.config)
    except ValueError as e:
        raise _error_validacion(e) from e
    if datos.activa is False:
        fuentes.actualizar(cx, sid, activa=False)
    return _resumen_fuente(_fila_fuente(cx, sid))


@router.patch("/sources/{sid}")
def actualizar_source(slug: str, sid: int, datos: FuentePatch, user: dict = Depends(usuario_actual),
                      cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _fuente_de_marca(cx, fila["id"], sid)
    try:
        fuentes.actualizar(cx, sid, config=datos.config, activa=datos.activa)
    except ValueError as e:
        raise _error_validacion(e) from e
    return _resumen_fuente(_fila_fuente(cx, sid))


@router.delete("/sources/{sid}", status_code=204)
def borrar_source(slug: str, sid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> None:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _fuente_de_marca(cx, fila["id"], sid)
    fuentes.borrar(cx, sid)


@router.put("/sources/orden")
def reordenar_sources(slug: str, datos: OrdenIn, user: dict = Depends(usuario_actual),
                      cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    try:
        fuentes.reordenar(cx, fila["id"], datos.ids)
    except ValueError as e:
        raise _error_validacion(e) from e
    return {"ok": True}


@router.post("/sources/{sid}/run", status_code=202)
def correr_source(slug: str, sid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    fuente = _fuente_de_marca(cx, fila["id"], sid)
    tipo = _JOB_TIPO_POR_PROVIDER.get(fuente["provider"])
    if tipo is None:
        raise ApiError(422, "validacion",
                       "Esta fuente no es ejecutable (proveedor estático)", "provider")
    job_id = jobs.crear(cx, tipo, fila["id"], {"source_id": sid}, creado_por=user["id"])
    return {"job_id": job_id}


# ---------- fotos ----------

def _valida_nombre_foto(nombre: str) -> None:
    if not _NOMBRE_FOTO_RE.match(nombre):
        raise ApiError(422, "validacion", "Nombre de archivo inválido", "nombre")


def _ruta_foto(carpeta_base, nombre: str):
    """Resuelve `nombre` dentro de `carpeta_base`; 422 si el path resultante se sale
    de la carpeta (ej. nombre="..", que sí matchea el regex de nombre pero es un
    intento de traversal a nivel de filesystem)."""
    carpeta = carpeta_base.resolve()
    candidato = (carpeta / nombre).resolve()
    if candidato.parent != carpeta:
        raise ApiError(422, "validacion", "Nombre de archivo inválido", "nombre")
    return candidato


@router.get("/photos")
def listar_photos(slug: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    carpeta = BRANDS_DIR / fila["slug"] / "fotos"
    if not carpeta.is_dir():
        return []
    archivos = sorted(p for p in carpeta.iterdir() if p.is_file())
    return [{
        "nombre": p.name,
        "tamano": p.stat().st_size,
        "mtime": int(p.stat().st_mtime),
        "url": f"/brands/{slug}/files/fotos/{p.name}",
    } for p in archivos]


@router.post("/photos")
def subir_photos(slug: str, archivos: list[UploadFile] = File(...),
                 user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    # Endpoint SÍNCRONO a propósito: get_cx abre sqlite3 en el hilo del
    # threadpool; un handler async correría en el event loop (otro hilo).
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    if len(archivos) > _MAX_FOTOS_POR_REQUEST:
        raise ApiError(422, "validacion",
                       f"Máximo {_MAX_FOTOS_POR_REQUEST} fotos por request", "archivos")

    # Validar TODO antes de escribir nada: una foto inválida a mitad del
    # request no debe dejar fotos previas ya guardadas en disco.
    contenidos = []
    for archivo in archivos:
        nombre = archivo.filename or ""
        ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
        if ext not in _EXT_FOTO:
            raise ApiError(422, "validacion",
                           "Formato de foto no soportado (jpg, jpeg, png, webp)", "archivos")
        contenido = _leer_con_tope(archivo, _MAX_FOTO)
        contenidos.append((ext, contenido))

    dest_dir = BRANDS_DIR / fila["slug"] / "fotos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    guardadas = []
    for ext, contenido in contenidos:
        nuevo_nombre = f"{uuid4().hex[:12]}.{ext}"
        (dest_dir / nuevo_nombre).write_bytes(contenido)
        guardadas.append(nuevo_nombre)
    return {"guardadas": guardadas}


@router.delete("/photos/{nombre}", status_code=204)
def borrar_photo(slug: str, nombre: str, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> None:
    _valida_nombre_foto(nombre)
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    carpeta = BRANDS_DIR / fila["slug"] / "fotos"
    candidato = _ruta_foto(carpeta, nombre)
    if not candidato.is_file():
        raise no_encontrado("esa foto")
    candidato.unlink()


@router.get("/files/fotos/{nombre}")
def archivo_foto(slug: str, nombre: str, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> FileResponse:
    _valida_nombre_foto(nombre)
    fila, _ = marca_para(slug, cx, user)
    carpeta = BRANDS_DIR / fila["slug"] / "fotos"
    candidato = _ruta_foto(carpeta, nombre)
    if not candidato.is_file():
        raise no_encontrado("esa foto")
    headers = {"X-Content-Type-Options": "nosniff"}
    return FileResponse(candidato, headers=headers)


# ---------- topics ----------

def _topic_de_marca(cx, account_id: int, tid: int) -> dict:
    fila = db.get(cx, "topic_suggestions", tid)
    if fila is None or fila["account_id"] != account_id:
        raise no_encontrado("ese tema")
    return fila


@router.get("/topics")
def listar_topics(slug: str, usados: bool = False, user: dict = Depends(usuario_actual),
                  cx=Depends(get_cx)) -> list[dict]:
    fila, _ = marca_para(slug, cx, user)
    return topics.listar(cx, fila["id"], incluir_usados=usados)


@router.post("/topics/{tid}/descartar")
def descartar_topic(slug: str, tid: int, user: dict = Depends(usuario_actual), cx=Depends(get_cx)) -> dict:
    fila, _ = marca_para(slug, cx, user, minimo="manager")
    _topic_de_marca(cx, fila["id"], tid)
    topics.descartar(cx, tid)
    return {"ok": True}
