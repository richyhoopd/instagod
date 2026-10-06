"""Feeds de catálogo, entidades y recetas por marca (spec 2026-10-06).

Rutas mínimas: alta/lista de feeds, disparar sync, listar entidades del
catálogo, listar recetas y generar una pieza desde (receta, entidad). Todo lo
pesado va al worker como job (`feeds.sync`, `receta.generar`).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from api.deps import get_cx, marca_para, usuario_actual
from api.errors import ApiError, conflicto, no_encontrado
from src import db, entidades, jobs, recetas

router = APIRouter(prefix="/brands/{slug}", tags=["feeds"])


class NuevoFeed(BaseModel):
    url: str = Field(min_length=10, max_length=500)
    intervalo_min: int = Field(360, ge=15, le=10080)

    @field_validator("url")
    @classmethod
    def _url(cls, v):
        v = v.strip()
        if not v.startswith(("https://", "http://")):
            raise ValueError("la URL del feed debe ser absoluta (https://…)")
        return v


class Generar(BaseModel):
    entidad_id: int


def _feed_de(cx, account_id: int, feed_id: int) -> dict:
    feed = db.get(cx, "brand_feeds", feed_id)
    if feed is None or feed["account_id"] != account_id:
        raise no_encontrado("ese feed")
    return feed


@router.get("/feeds")
def listar_feeds(slug: str, user: dict = Depends(usuario_actual),
                 cx=Depends(get_cx)) -> list[dict]:
    marca, _ = marca_para(slug, cx, user)
    return db.rows(cx, "SELECT * FROM brand_feeds WHERE account_id = ? ORDER BY id",
                   (marca["id"],))


@router.post("/feeds", status_code=201)
def crear_feed(slug: str, datos: NuevoFeed, user: dict = Depends(usuario_actual),
               cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user, "manager")
    if db.rows(cx, "SELECT id FROM brand_feeds WHERE account_id = ? AND url = ?",
               (marca["id"], datos.url)):
        raise conflicto("Ese feed ya está registrado", "url")
    fid = db.insert(cx, "brand_feeds", account_id=marca["id"], url=datos.url,
                    intervalo_min=datos.intervalo_min)
    return db.get(cx, "brand_feeds", fid)


@router.post("/feeds/{feed_id}/sync", status_code=202)
def sincronizar_feed(slug: str, feed_id: int, user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user)
    _feed_de(cx, marca["id"], feed_id)
    jid = jobs.crear(cx, "feeds.sync", marca["id"], {"feed_id": feed_id},
                     creado_por=user.get("id"))
    return {"job_id": jid}


@router.get("/entidades")
def listar_entidades(slug: str, todas: bool = False, user: dict = Depends(usuario_actual),
                     cx=Depends(get_cx)) -> list[dict]:
    marca, _ = marca_para(slug, cx, user)
    out = []
    for e in entidades.listar(cx, marca["id"], solo_activas=not todas):
        a = entidades.atributos_de(e)
        out.append({"id": e["id"], "slug": e["slug"], "nombre": e["nombre"],
                    "tipo": e["tipo"], "activa": e["activa"],
                    "status": a.get("status"), "url": a.get("url"),
                    "facts": a.get("facts") or {},
                    "unverified": a.get("unverified") or [],
                    "media": len(a.get("media") or []),
                    "updated_at": a.get("updated_at")})
    return out


@router.get("/recetas")
def listar_recetas(slug: str, user: dict = Depends(usuario_actual),
                   cx=Depends(get_cx)) -> list[dict]:
    marca, _ = marca_para(slug, cx, user)
    return recetas.listar(cx, marca["id"], solo_activas=False)


@router.post("/recetas/{receta}/generar", status_code=202)
def generar(slug: str, receta: str, datos: Generar, user: dict = Depends(usuario_actual),
            cx=Depends(get_cx)) -> dict:
    marca, _ = marca_para(slug, cx, user)
    r = recetas.por_slug(cx, marca["id"], receta)
    if r is None or not r["activa"]:
        raise no_encontrado("esa receta")
    e = entidades.obtener(cx, datos.entidad_id)
    if e is None or e["account_id"] != marca["id"]:
        raise no_encontrado("esa entidad")
    if not e["activa"]:
        raise ApiError(422, "no_aplica", "La entidad no está activa", "entidad_id")
    if r["item_types"] and e["tipo"] not in r["item_types"]:
        raise ApiError(422, "no_aplica",
                       f"La receta {receta} no aplica a tipo {e['tipo']!r}", "entidad_id")
    jid = jobs.crear(cx, "receta.generar", marca["id"],
                     {"receta": receta, "entidad_id": e["id"]},
                     creado_por=user.get("id"))
    return {"job_id": jid}
