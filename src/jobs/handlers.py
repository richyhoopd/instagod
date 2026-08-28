"""Handlers de jobs: despachados por `tipo` desde `src.jobs.worker`.

Cada handler recibe `(cx, job)` (la fila de `jobs`, ya en estado 'corriendo')
y devuelve el dict que se guarda en `resultado_json` al terminar. Reportan
avance vía `jobs.progresar` (el worker no sabe nada del payload interno).
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

import config
from src import (
    compose,
    db,
    generate_slideshow,
    host,
    ingest_ig,
    jobs,
    marcas,
    slideshow_compile,
    slideshow_model,
    topics,
)
from src import fuentes as fuentes_mod


def _marca_de(cx: sqlite3.Connection, account_id: int) -> str:
    """Slug de la cuenta del job. NUNCA cae a un default: un account_id viejo
    o borrado no debe terminar generando contenido bajo la marca equivocada
    (p. ej. 'gdlscene' por default) — mejor que el job truene y quede en
    estado='error' (el worker ya sabe manejar esa excepción)."""
    cuenta = db.get(cx, "accounts", account_id)
    if cuenta is None:
        raise ValueError(f"No existe la cuenta {account_id} del job")
    return cuenta["slug"]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _sellar_ultimo_run(cx: sqlite3.Connection, source_id: int, error: str | None) -> None:
    """Sella `ultimo_run`/`ultimo_error` de una fuente. Se llama SIEMPRE desde
    un `finally` (H3) — si ese `db.update` revienta (ej. borraron la fuente a
    mitad del job), la excepción original que se estaba propagando NO debe
    quedar enmascarada por esta falla secundaria de sellado."""
    try:
        db.update(cx, "brand_sources", source_id, ultimo_run=_ts(), ultimo_error=error)
    except Exception as exc:  # noqa: BLE001 — no enmascarar la excepción original
        print(f"[jobs] no se pudo sellar ultimo_run de la fuente {source_id}: {exc}")


def _fuente_de(cx: sqlite3.Connection, account_id: int, source_id: int, kind: str) -> dict[str, Any]:
    """Fuente de `account_id` con `source_id` y `kind` esperados. ValueError si no
    existe o es de otra cuenta (aislamiento: `fuentes.listar` ya filtra por cuenta,
    así que una fuente ajena simplemente no aparece en la lista)."""
    for f in fuentes_mod.listar(cx, account_id, kind=kind):
        if f["id"] == source_id:
            return f
    raise ValueError(f"La fuente {source_id} no existe o no pertenece a la cuenta {account_id}")


def generar_slideshow(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {tema, formato, estilo, fuentes, n_slides, aspect, contexto}."""
    payload = json.loads(job["payload_json"] or "{}")
    fuentes = payload.get("fuentes")
    qid = generate_slideshow.generar(
        cx, payload["tema"],
        marca=_marca_de(cx, job["account_id"]),
        formato=payload.get("formato"),
        estilo=payload.get("estilo"),
        fuentes=tuple(fuentes) if fuentes else None,
        n_slides=payload.get("n_slides", 6),
        aspect=payload.get("aspect", "4:5"),
        contexto=payload.get("contexto"),
        progreso=lambda pct, msg: jobs.progresar(cx, job["id"], pct, msg),
        creado_por=job.get("creado_por"),
        topic_id=payload.get("topic_id"),
    )
    db.update(cx, "jobs", job["id"], queue_id=qid)
    return {"queue_id": qid}


def regenerar_slideshow(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {queue_id}. Descarta la fila vieja y regenera con el mismo brief."""
    payload = json.loads(job["payload_json"] or "{}")
    queue_id = payload["queue_id"]
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None:
        raise ValueError(f"No existe content_queue.id={queue_id}")
    brief = json.loads(fila["slideshow_json"])["brief"]
    db.update(cx, "content_queue", queue_id, status="descartado")

    fuentes = brief.get("fuentes")
    nuevo_qid = generate_slideshow.generar(
        cx, brief["tema"],
        marca=_marca_de(cx, job["account_id"]),
        formato=brief.get("formato"),
        estilo=brief.get("estilo"),
        fuentes=tuple(fuentes) if fuentes else None,
        n_slides=brief.get("n_slides", 6),
        aspect=brief.get("aspect", "4:5"),
        contexto=brief.get("contexto"),
        progreso=lambda pct, msg: jobs.progresar(cx, job["id"], pct, msg),
        creado_por=job.get("creado_por"),
        notificar_telegram=brief.get("notificar_telegram", True),
    )
    db.update(cx, "jobs", job["id"], queue_id=nuevo_qid)
    return {"queue_id": nuevo_qid}


def rerender_slideshow(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {queue_id}. Re-renderiza los PNGs desde el slideshow_json
    guardado (editado por el portal) SIN volver a llamar al LLM ni re-elegir
    fondos, sube a Cloudinary y actualiza imagen_url. El estado no cambia.
    """
    payload = json.loads(job["payload_json"] or "{}")
    queue_id = payload["queue_id"]
    fila = db.get(cx, "content_queue", queue_id)
    if fila is None or not fila["slideshow_json"]:
        raise ValueError(f"No existe slideshow en content_queue.id={queue_id}")
    show = slideshow_model.desde_json(fila["slideshow_json"])

    jobs.progresar(cx, job["id"], 20, "render")
    pngs = []
    for i in range(len(show.slides)):
        ctx = slideshow_compile.contexto_slide(show, i)
        pngs.append(compose.render_card("slide.html", ctx, prefix=f"slide{i}"))

    jobs.progresar(cx, job["id"], 70, "subiendo")
    ts = int(time.time())
    urls = [host.upload(str(p), public_id=f"ss{ts}_{i}")
            for i, p in enumerate(pngs)]

    db.update(cx, "content_queue", queue_id, imagen_url=json.dumps(urls))
    db.update(cx, "jobs", job["id"], queue_id=queue_id)
    return {"queue_id": queue_id}


def sourcing_rss_fetch(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {source_id}. Baja cada URL de la fuente RSS y guarda temas nuevos.

    `ultimo_run` se sella en un `finally`: pase lo que pase (URLs rotas o un
    fallo inesperado a mitad del loop), la fuente deja de estar "vencida" y
    `encolar_fuentes_vencidas` no la re-encola en el siguiente tick (H3).
    """
    payload = json.loads(job["payload_json"] or "{}")
    source_id = payload["source_id"]
    fuente = _fuente_de(cx, job["account_id"], source_id, "info")
    urls = fuente["config"].get("urls", [])

    nuevos = 0
    error: str | None = None
    try:
        for url in urls:
            try:
                items = topics.fetch_rss(url)
                nuevos += topics.guardar(cx, job["account_id"], items, "rss")
            except Exception as exc:  # noqa: BLE001 — una URL rota no debe tumbar las demás
                error = str(exc)
        return {"nuevos": nuevos}
    finally:
        _sellar_ultimo_run(cx, source_id, error)


def sourcing_newsapi_fetch(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {source_id}. Usa NEWSAPI_KEY de la marca; sin key, error accionable.

    `ultimo_run` se sella en un `finally` que envuelve TODO el cuerpo (incluida
    la validación de la key): antes, un `ValueError("Falta NEWSAPI_KEY")`
    reventaba antes de tocar `brand_sources`, así que la fuente seguía
    "vencida" y el siguiente `encolar_fuentes_vencidas` la re-encolaba de
    inmediato — tormenta de jobs en error (H3).
    """
    payload = json.loads(job["payload_json"] or "{}")
    source_id = payload["source_id"]
    fuente = _fuente_de(cx, job["account_id"], source_id, "info")
    slug = _marca_de(cx, job["account_id"])
    cfg = fuente["config"]

    error: str | None = None
    try:
        key = config.account_creds(slug).get("NEWSAPI_KEY")
        if not key:
            raise ValueError("Falta NEWSAPI_KEY")
        items = topics.fetch_newsapi(cfg["query"], key, idioma=cfg.get("idioma", "es"),
                                     pais=cfg.get("pais"), estricto=True)
        nuevos = topics.guardar(cx, job["account_id"], items, "newsapi")
        return {"nuevos": nuevos}
    except Exception as exc:  # noqa: BLE001 — se sella el error y se relanza (job en error)
        error = str(exc)
        raise
    finally:
        _sellar_ultimo_run(cx, source_id, error)


_SHORTCODE_RE = re.compile(r"[^A-Za-z0-9_-]")


def sourcing_ig_scrape(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {source_id}. Descarga hasta `max_por_cuenta` fotos por cada @cuenta
    a `data/brands/<slug>/fotos/`. Best-effort por cuenta: una cuenta rota o privada
    se anota en `ultimo_error` y se sigue con la siguiente — JAMÁS reintenta ni rota
    de sesión (a diferencia de `ingest_ig.ingest`, pensado para corridas manuales).

    Si NINGUNA cuenta produjo fotos y hubo errores, el job termina en error de
    verdad (no un "ok" con 0 fotos que esconde que el scrape falló, H6)."""
    payload = json.loads(job["payload_json"] or "{}")
    source_id = payload["source_id"]
    fuente = _fuente_de(cx, job["account_id"], source_id, "imagen")
    slug = _marca_de(cx, job["account_id"])
    cfg = fuente["config"]
    cuentas = cfg.get("cuentas", [])
    max_por_cuenta = cfg.get("max_por_cuenta") or 10

    # Sin sesión sana no hay nada que hacer: error accionable, se propaga tal
    # cual (el mensaje de get_session ya dice qué configurar).
    session = ingest_ig.get_session()

    dest_dir = config.BASE_DIR / "data" / "brands" / slug / "fotos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_dir_resuelta = dest_dir.resolve()

    total = 0
    errores: list[str] = []
    for cuenta in cuentas:
        # `cuenta` ya pasó por `_CUENTA_IG_RE` en `validar_config` (solo
        # [A-Za-z0-9._] tras la @), así que `handle` no puede traer "../".
        handle = cuenta.lstrip("@")
        try:
            user = ingest_ig.fetch_profile(session, handle)
            if user.get("is_private"):
                errores.append(f"@{handle}: perfil privado")
                continue
            ingest_ig._sleep()  # pausa entre el request de perfil y el de posts
            items = ingest_ig.fetch_posts(session, user["id"], max_por_cuenta)
        except Exception as exc:  # noqa: BLE001 — una cuenta rota no debe tumbar las demás
            errores.append(f"@{handle}: {exc}")
            continue

        bajadas = 0
        for item in items:
            if bajadas >= max_por_cuenta:
                break
            shortcode = _SHORTCODE_RE.sub("", str(item.get("code") or ""))[:40]
            for i, url in ingest_ig._image_urls(item):
                if bajadas >= max_por_cuenta:
                    break
                nombre = f"{handle}_{shortcode}_{i}.jpg"
                dest = dest_dir / nombre
                # Contención: pase lo que pase con `nombre`, el archivo JAMÁS
                # se escribe fuera de `dest_dir` (H1). Con handle y shortcode
                # ya saneados esto no debería disparar nunca; es cinturón.
                if dest.resolve().parent != dest_dir_resuelta:
                    errores.append(f"@{handle}: nombre de archivo inseguro, item salteado")
                    continue
                if dest.exists():
                    continue
                if ingest_ig._download(session, url, dest):
                    bajadas += 1
        total += bajadas

    db.update(cx, "brand_sources", source_id, ultimo_run=_ts(),
             ultimo_error="; ".join(errores) if errores else None)
    if total == 0 and errores:
        raise RuntimeError("scrape sin resultados: " + "; ".join(errores)[:200])
    return {"bajadas": total, "errores": errores}


def preset_preview(cx: sqlite3.Connection, job: dict[str, Any]) -> dict[str, Any]:
    """payload: {nombre, texto}. Renderiza un slide de 1 hoja con el preset `nombre`
    y lo copia a `data/previews/<slug>/<nombre>.png`."""
    payload = json.loads(job["payload_json"] or "{}")
    nombre = payload["nombre"]
    texto = (payload.get("texto") or "").strip() or "Así se ve tu preset"
    slug = _marca_de(cx, job["account_id"])
    m = marcas.cargar_por_id(cx, job["account_id"])
    catalogo = marcas.estilos_de(m)
    if nombre not in catalogo:
        raise ValueError(f"El preset {nombre!r} no existe para {slug} "
                         f"(disponibles: {sorted(catalogo)})")

    guion = {"tema": "preview", "hook": texto, "caption": "", "cta": "",
             "slides": [{"text": texto, "rol": "hook", "image_hint": ""}]}
    show = slideshow_compile.compilar(
        guion, estilo=nombre, imagenes=[None], aspect_ratio="4:5",
        brief={"tema": "preview"}, formato="libre", account_slug=slug,
        estilos=catalogo)
    errores = slideshow_model.validar(show)
    if errores:
        raise RuntimeError(f"Contrato inválido, no se genera preview: {errores}")
    ctx = slideshow_compile.contexto_slide(show, 0)
    png = compose.render_card("slide.html", ctx, prefix=f"preview_{slug}_{nombre}")

    dest_dir = config.BASE_DIR / "data" / "previews" / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{nombre}.png"
    shutil.copyfile(png, dest)
    return {"path": str(dest)}


HANDLERS = {
    "slideshow.generar": generar_slideshow,
    "slideshow.regenerar": regenerar_slideshow,
    "slideshow.rerender": rerender_slideshow,
    "sourcing.rss_fetch": sourcing_rss_fetch,
    "sourcing.newsapi_fetch": sourcing_newsapi_fetch,
    "sourcing.ig_scrape": sourcing_ig_scrape,
    "preset.preview": preset_preview,
}
