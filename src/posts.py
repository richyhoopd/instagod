"""Orquesta un post simple: campos, imagen, render y fila en la cola.

Es el equivalente de src/generate_slideshow.py para la pieza de una sola
imagen, pero sin nada del dominio musical: habla de entidades y plantillas,
no de bandas y memes.
"""
from __future__ import annotations

import json
from typing import Any

from . import db, host, image_sources, plantillas
from . import fuentes as fuentes_mod
from .plantillas import generador, render


def resolver_imagen(cx, marca, *, entidad_id: int | None = None,
                    hint: str | None = None, manual: str | None = None) -> str | None:
    """Manual > foto de la entidad > cascada de la marca > nada."""
    if manual:
        return manual
    if entidad_id:
        filas = db.rows(
            cx,
            "SELECT path FROM photos WHERE entity_id = ? AND usable_meme = 1 "
            "  AND descartada = 0 AND usada = 0 ORDER BY id LIMIT 1",
            (entidad_id,),
        )
        if filas:
            return filas[0]["path"]
    if hint:
        cascada = list(fuentes_mod.orden_imagen(cx, marca))
        candidatas = image_sources.resolver([hint], cascada, cx=cx, slug=marca.slug)
        if candidatas and candidatas[0] is not None:
            return candidatas[0].ruta_o_url
    return None


def crear_post(cx, marca, *, template_id: int, tema: str,
               entidad_id: int | None = None,
               campos_manuales: dict[str, Any] | None = None,
               imagen_manual: str | None = None,
               creado_por: int | None = None) -> int:
    tpl = plantillas.obtener(cx, template_id)
    if tpl is None or tpl["account_id"] != marca.id:
        raise ValueError("plantilla")
    ct = plantillas.contrato_de(tpl)

    entidad = db.get(cx, "brand_entities", entidad_id) if entidad_id else None
    campos = campos_manuales or generador.generar_campos(
        ct, marca=marca, tema=tema, entidad=entidad)

    campos["imagen"] = resolver_imagen(
        cx, marca, entidad_id=entidad_id,
        hint=campos.get("titular") or tema, manual=imagen_manual)

    png = render.render(cx, marca, tpl, campos)
    url = host.upload(str(png))

    return db.insert(
        cx, "content_queue", tipo="post", account_id=marca.id,
        template_id=template_id, template_version=tpl["version_actual"],
        entity_id=entidad_id, campos_json=json.dumps(campos, ensure_ascii=False),
        aspecto=ct.get("aspecto", "4:5"), imagen_url=url,
        caption=campos.get("titular"), tema_semilla=tema,
        status="borrador", creado_por=creado_por, origen="api",
        # `aprobacion='pendiente'` NO es opcional: la fila se inserta DESPUÉS
        # de renderizar, así que la pieza ya está lista y lo que falta es la
        # revisión humana. Con NULL, `cola.estado_de` la deriva como
        # "generando" (origen='api' + aprobacion NULL significa "el worker
        # todavía la está armando") y entonces NO se puede editar ni aprobar.
        # Es el mismo contrato que usa el flujo de slideshows vía
        # approval.encolar_pendiente (src/approval.py:31).
        aprobacion="pendiente",
    )


def rerender(cx, marca, queue_id: int) -> str:
    """Vuelve a dibujar con los campos que ya están guardados. Sin LLM."""
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None or fila["account_id"] != marca.id:
        raise ValueError("pieza")
    if fila["tipo"] != "post":
        raise ValueError("tipo")
    tpl = plantillas.obtener(cx, fila["template_id"])
    if tpl is None:
        raise ValueError("plantilla")

    campos = json.loads(fila["campos_json"] or "{}")
    png = render.render(cx, marca, tpl, campos, row_id=f"q{queue_id}")
    url = host.upload(str(png), public_id=f"post_{queue_id}")
    db.update(cx, "content_queue", queue_id, imagen_url=url,
              caption=campos.get("titular"))
    return url
