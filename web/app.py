"""GUI local de curación de la DB de bandas (FastAPI + Jinja2 + HTMX).

Solo corre en localhost, sin auth: es la herramienta personal para corregir
nombres, prioridades y (en fases siguientes) fotos, miembros y eventos, sin
tocar SQL ni el Sheet a mano.

Uso:  uvicorn web.app:app --reload
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config
from src import db, spotify_match

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

app = FastAPI(title="@gdlscene — curación")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@app.on_event("startup")
def _startup() -> None:
    """Garantiza que el esquema exista antes de servir la primera vista."""
    cx = db.connect()
    db.init_db(cx)
    cx.close()


def _band_view(band: dict[str, Any]) -> dict[str, Any]:
    """Agrega campos derivados que la plantilla necesita (géneros legibles)."""
    band = dict(band)
    band["generos_str"] = ", ".join(db.generos_list(band))
    return band


@app.get("/", response_class=HTMLResponse)
def index() -> RedirectResponse:
    return RedirectResponse("/bandas")


@app.get("/bandas", response_class=HTMLResponse)
def bandas(request: Request, order: str = "prioridad", todas: int = 0,
           solo: str = "", genero: str = "") -> HTMLResponse:
    cx = db.connect()
    try:
        items = [_band_view(b) for b in db.list_bands(cx, solo_activas=not todas, order=order)]
        candidatas = db.rows(cx, "SELECT COUNT(*) n FROM bands WHERE activa = 0")[0]["n"]
        activas = db.rows(cx, "SELECT COUNT(*) n FROM bands WHERE activa = 1")[0]["n"]
        sin_scrapear = db.rows(cx, "SELECT COUNT(*) n FROM bands "
                               "WHERE activa = 1 AND scraped_at IS NULL AND ig_handle IS NOT NULL")[0]["n"]
    finally:
        cx.close()
    if solo == "sin_scrapear":
        items = [b for b in items if not b.get("scraped_at") and b.get("ig_handle")]
    if genero in config.GENEROS:
        items = [b for b in items if b.get("genero_principal") == genero]
    return templates.TemplateResponse(request, "bandas.html", {
        "bandas": items, "order": order, "todas": todas, "solo": solo,
        "candidatas": candidatas, "activas": activas, "sin_scrapear": sin_scrapear,
        "genero": genero if genero in config.GENEROS else "",
        "generos_taxonomia": config.GENEROS,
    })


@app.post("/bandas", response_class=HTMLResponse)
def crear_banda(request: Request, nombre: str = Form(...),
                ig_handle: str = Form("")) -> HTMLResponse:
    cx = db.connect()
    try:
        bid = db.upsert_band(cx, nombre.strip(), ig_handle.strip().lstrip("@") or None)
        band = _band_view(db.get(cx, "bands", bid))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_band_row.html", {"b": band})


@app.get("/bandas/{band_id}/edit", response_class=HTMLResponse)
def editar_banda_form(request: Request, band_id: int) -> HTMLResponse:
    cx = db.connect()
    try:
        band = _band_view(db.get(cx, "bands", band_id))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_band_edit.html",
                                      {"b": band, "generos_taxonomia": config.GENEROS})


@app.get("/bandas/{band_id}/row", response_class=HTMLResponse)
def fila_banda(request: Request, band_id: int) -> HTMLResponse:
    """Fila en modo lectura (para cancelar una edición)."""
    cx = db.connect()
    try:
        band = _band_view(db.get(cx, "bands", band_id))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_band_row.html", {"b": band})


@app.post("/bandas/{band_id}", response_class=HTMLResponse)
def guardar_banda(request: Request, band_id: int,
                  nombre: str = Form(...), tipo: str = Form("banda"),
                  ig_handle: str = Form(""),
                  spotify_id: str = Form(""), ciudad: str = Form(""),
                  genero_principal: str = Form(""),
                  generos: str = Form(""), prioridad: int = Form(3),
                  n_integrantes: str = Form(""), notas: str = Form(""),
                  activa: int = Form(0)) -> HTMLResponse:
    import json
    generos_json = None
    if generos.strip():
        generos_json = json.dumps([g.strip() for g in generos.split(",") if g.strip()],
                                  ensure_ascii=False)
    # Fuera de la taxonomía → None (la GUI manda la lista cerrada, pero blindamos).
    gp = genero_principal.strip()
    gp = gp if gp in config.GENEROS else None
    tipos_ok = {"banda", "solista", "foro", "evento", "colectivo"}
    cx = db.connect()
    try:
        cambios: dict[str, Any] = dict(
            nombre=nombre.strip(),
            tipo=tipo if tipo in tipos_ok else "banda",
            ig_handle=ig_handle.strip().lstrip("@") or None,
            spotify_id=spotify_id.strip() or None,
            ciudad=ciudad.strip() or None,
            generos=generos_json,
            genero_principal=gp,
            prioridad=max(1, min(5, prioridad)),
            n_integrantes=int(n_integrantes) if n_integrantes.strip().isdigit() else None,
            notas=notas.strip() or None,
            activa=1 if activa else 0,
        )
        # Si el género cambió desde la GUI, queda curado a mano: el batch no lo pisa.
        actual = db.get(cx, "bands", band_id)
        if actual and (actual.get("genero_principal") or None) != gp:
            cambios["generos_fuente"] = "manual"
        db.update(cx, "bands", band_id, **cambios)
        band = _band_view(db.get(cx, "bands", band_id))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_band_row.html", {"b": band})


@app.post("/bandas/{band_id}/tipo", response_class=HTMLResponse)
def cambiar_tipo(request: Request, band_id: int, tipo: str = Form(...)) -> HTMLResponse:
    """Cambia SOLO el tipo de actor (inline, sirve para activas y candidatas)."""
    tipos_ok = {"banda", "solista", "foro", "evento", "colectivo"}
    cx = db.connect()
    try:
        if tipo in tipos_ok:
            db.update(cx, "bands", band_id, tipo=tipo)
        band = _band_view(db.get(cx, "bands", band_id))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_band_row.html", {"b": band})


@app.post("/bandas/{band_id}/activar", response_class=HTMLResponse)
def activar_banda(request: Request, band_id: int) -> HTMLResponse:
    """Aprueba una candidata: activa=1 y limpia la nota de candidata."""
    cx = db.connect()
    try:
        actual = db.get(cx, "bands", band_id)
        notas = None if (actual and (actual.get("notas") or "").startswith("candidata")) \
            else (actual.get("notas") if actual else None)
        db.update(cx, "bands", band_id, activa=1, notas=notas)
        band = _band_view(db.get(cx, "bands", band_id))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_band_row.html", {"b": band})


@app.post("/bandas/{band_id}/borrar", response_class=HTMLResponse)
def borrar_banda(band_id: int) -> HTMLResponse:
    """Elimina una banda (y en cascada sus fotos/miembros/eventos)."""
    cx = db.connect()
    try:
        cx.execute("DELETE FROM bands WHERE id = ?", (band_id,))
        cx.commit()
    finally:
        cx.close()
    return HTMLResponse("")  # HTMX quita la fila


# ---------- Detalle de banda: miembros + galería de fotos (curación visual) ----------

def _detalle_ctx(cx, band_id: int) -> dict[str, Any]:
    band = db.get(cx, "bands", band_id)
    if band is None:
        raise HTTPException(404, f"No existe la banda id={band_id}")
    members = db.rows(cx, "SELECT * FROM members WHERE band_id = ? ORDER BY id", (band_id,))
    fotos = db.rows(cx, """
        SELECT p.*, m.nombre AS member_nombre FROM photos p
          LEFT JOIN members m ON m.id = p.member_id
         WHERE p.band_id = ? ORDER BY p.usable_meme DESC, p.fecha DESC
    """, (band_id,))
    return {"b": _band_view(band), "members": members, "fotos": fotos}


@app.get("/bandas/{band_id}/detalle", response_class=HTMLResponse)
def banda_detalle(request: Request, band_id: int) -> HTMLResponse:
    cx = db.connect()
    try:
        ctx = _detalle_ctx(cx, band_id)
    finally:
        cx.close()
    return templates.TemplateResponse(request, "banda_detalle.html", ctx)


@app.post("/bandas/{band_id}/members", response_class=HTMLResponse)
def crear_member(request: Request, band_id: int, nombre: str = Form(...),
                 rol: str = Form(""), ig_handle: str = Form("")) -> HTMLResponse:
    cx = db.connect()
    try:
        mid = db.insert(cx, "members", band_id=band_id, nombre=nombre.strip(),
                        rol=rol.strip() or None,
                        ig_handle=ig_handle.strip().lstrip("@") or None)
        member = db.get(cx, "members", mid)
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_member_row.html", {"m": member})


@app.post("/members/{member_id}", response_class=HTMLResponse)
def guardar_member(request: Request, member_id: int, nombre: str = Form(...),
                   rol: str = Form(""), ig_handle: str = Form("")) -> HTMLResponse:
    cx = db.connect()
    try:
        db.update(cx, "members", member_id, nombre=nombre.strip(),
                  rol=rol.strip() or None,
                  ig_handle=ig_handle.strip().lstrip("@") or None)
        member = db.get(cx, "members", member_id)
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_member_row.html", {"m": member})


@app.post("/members/{member_id}/borrar", response_class=HTMLResponse)
def borrar_member(member_id: int) -> HTMLResponse:
    cx = db.connect()
    try:
        cx.execute("DELETE FROM members WHERE id = ?", (member_id,))
        cx.commit()
    finally:
        cx.close()
    return HTMLResponse("")  # HTMX quita la fila


# ---------- Fotos: servir thumbnails + toggles de curación ----------

@app.get("/foto/{photo_id}")
def servir_foto(photo_id: int) -> FileResponse:
    cx = db.connect()
    try:
        photo = db.get(cx, "photos", photo_id)
    finally:
        cx.close()
    if photo is None:
        raise HTTPException(404)
    path = Path(photo["path"])
    if not path.is_absolute():
        path = config.BASE_DIR / path
    if not path.exists():
        raise HTTPException(404, f"Archivo no encontrado: {path}")
    return FileResponse(path)


@app.post("/fotos/{photo_id}", response_class=HTMLResponse)
def guardar_foto(request: Request, photo_id: int, usable_meme: int = Form(0),
                 usada: int = Form(0), member_id: str = Form("")) -> HTMLResponse:
    cx = db.connect()
    try:
        db.update(cx, "photos", photo_id,
                  usable_meme=1 if usable_meme else 0,
                  usada=1 if usada else 0,
                  member_id=int(member_id) if member_id.strip().isdigit() else None)
        foto = db.rows(cx, """
            SELECT p.*, m.nombre AS member_nombre FROM photos p
              LEFT JOIN members m ON m.id = p.member_id WHERE p.id = ?
        """, (photo_id,))[0]
        members = db.rows(cx, "SELECT * FROM members WHERE band_id = ? ORDER BY id",
                          (foto["band_id"],))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_photo_card.html",
                                      {"f": foto, "members": members})


@app.post("/fotos/{photo_id}/flyer", response_class=HTMLResponse)
def foto_marcar_flyer(photo_id: int) -> HTMLResponse:
    """Marca una foto como flyer: la registra en Eventos y la saca de memes.

    Reemplaza la tarjeta por una confirmación visible (la foto ya suele estar gris,
    así que sin esto parecería que no pasó nada).
    """
    from src.classify import _registrar_flyer
    cx = db.connect()
    try:
        foto = db.get(cx, "photos", photo_id)
        if foto is None:
            raise HTTPException(404)
        _registrar_flyer(cx, foto)
        db.update(cx, "photos", photo_id, usable_meme=0)
    finally:
        cx.close()
    return HTMLResponse(
        '<div style="background:#eef7ef; border:1px solid #2c7a39; border-radius:8px; '
        'padding:18px 14px; text-align:center; color:#2c7a39; font-size:13px;">'
        '🏴 <strong>Marcada como flyer</strong><br>Está en '
        '<a href="/eventos">Eventos</a> para ponerle fecha.</div>')


@app.post("/fotos/{photo_id}/a-cola", response_class=HTMLResponse)
def foto_a_cola(photo_id: int, tema_semilla: str = Form("")) -> HTMLResponse:
    """Crea una fila 'listo' en content_queue a partir de una foto curada."""
    cx = db.connect()
    try:
        foto = db.get(cx, "photos", photo_id)
        if foto is None:
            raise HTTPException(404)
        db.insert(cx, "content_queue", tipo="meme", band_id=foto["band_id"],
                  member_id=foto["member_id"], photo_id=photo_id,
                  tema_semilla=tema_semilla.strip() or None, status=db.QUEUE_LISTO)
    finally:
        cx.close()
    return HTMLResponse('<span class="chip">en cola ✓</span>')


# ---------- Banco de caras por persona: corrección de agrupamiento ----------

@app.get("/banda/{band_id}/caras", response_class=HTMLResponse)
def caras(request: Request, band_id: int) -> HTMLResponse:
    cx = db.connect()
    try:
        banda = db.get(cx, "bands", band_id)
        if not banda:
            raise HTTPException(status_code=404, detail="banda no encontrada")
        personas = db.rows(cx, """
            SELECT p.id, p.etiqueta_auto, m.nombre, m.rol,
                   (SELECT count(*) FROM face_signatures f WHERE f.persona_id = p.id) AS n_fotos
              FROM personas p LEFT JOIN members m ON m.id = p.member_id
             WHERE p.band_id = ? ORDER BY n_fotos DESC
        """, (band_id,))
        for p in personas:
            p["fotos"] = db.rows(cx, """
                SELECT id FROM photos WHERE persona_id = ? ORDER BY nitidez DESC LIMIT 6
            """, (p["id"],))
        return templates.TemplateResponse(
            request, "caras.html", {"banda": banda, "personas": personas})
    finally:
        cx.close()


@app.post("/personas/{persona_id}/nombrar")
def persona_nombrar(persona_id: int, nombre: str = Form(...), rol: str = Form("")) -> Response:
    cx = db.connect()
    try:
        persona = db.get(cx, "personas", persona_id)
        if not persona:
            raise HTTPException(status_code=404, detail="persona no encontrada")
        if persona["member_id"]:
            db.update(cx, "members", persona["member_id"], nombre=nombre, rol=rol or None)
        else:
            mid = db.insert(cx, "members", band_id=persona["band_id"],
                            nombre=nombre, rol=rol or None)
            db.update(cx, "personas", persona_id, member_id=mid)
        return Response(status_code=200)
    finally:
        cx.close()


@app.post("/personas/{persona_id}/fusionar")
def persona_fusionar(persona_id: int, otra_id: int = Form(...)) -> Response:
    """Absorbe `otra_id` en `persona_id`: mismo humano mal separado por el clustering."""
    cx = db.connect()
    try:
        if otra_id == persona_id:
            raise HTTPException(status_code=400,
                                detail="una persona no se fusiona consigo misma")
        persona = db.get(cx, "personas", persona_id)
        otra = db.get(cx, "personas", otra_id)
        if not persona or not otra:
            raise HTTPException(status_code=404, detail="persona no encontrada")
        if persona["band_id"] != otra["band_id"]:
            raise HTTPException(status_code=400,
                                detail="las dos personas deben ser de la misma banda")
        cx.execute("UPDATE face_signatures SET persona_id = ? WHERE persona_id = ?",
                   (persona_id, otra_id))
        cx.execute("UPDATE photos SET persona_id = ? WHERE persona_id = ?",
                   (persona_id, otra_id))
        cx.execute("DELETE FROM personas WHERE id = ?", (otra_id,))
        cx.commit()
        return Response(status_code=200)
    finally:
        cx.close()


@app.post("/personas/{persona_id}/descartar")
def persona_descartar(persona_id: int) -> Response:
    """Grupo mal armado: sus fotos salen del banco (no se borran del disco)."""
    cx = db.connect()
    try:
        if not db.get(cx, "personas", persona_id):
            raise HTTPException(status_code=404, detail="persona no encontrada")
        cx.execute("UPDATE photos SET usable_meme = 0, persona_id = NULL "
                   "WHERE persona_id = ?", (persona_id,))
        cx.execute("DELETE FROM face_signatures WHERE persona_id = ?", (persona_id,))
        cx.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
        cx.commit()
        return Response(status_code=200)
    finally:
        cx.close()


# ---------- Catálogo de foros: cola de curación + fusión ----------

# Parecido mínimo para PRESELECCIONAR nada — solo para etiquetar "(sugerido)".
# Por debajo de esto la sugerencia es ruido: `GRAL.MANUEL pm COVER M.DIEGUEZ #71`
# contra cualquier foro real puntúa ~0.08 y sugerirlo invita a ligar basura.
_UMBRAL_SUGERENCIA = 0.6


@app.get("/venues", response_class=HTMLResponse)
def venues_vista(request: Request) -> HTMLResponse:
    from src import venues as venues_mod
    cx = db.connect()
    try:
        foros = db.rows(cx, "SELECT * FROM venues ORDER BY nombre")
        for v in foros:
            v["alias"] = db.rows(
                cx, "SELECT id, alias_visto FROM venue_alias WHERE venue_id = ? ORDER BY id",
                (v["id"],))
        candidatos = [(v["id"], v["nombre"]) for v in foros]
        huerfanos = venues_mod.huerfanos(cx)
        for h in huerfanos:
            sug = venues_mod.sugerencias(h["alias_visto"], candidatos, tope=1)
            h["sugerencia"] = (sug[0][0] if sug and sug[0][2] >= _UMBRAL_SUGERENCIA
                               else None)
        return templates.TemplateResponse(
            request, "venues.html", {"foros": foros, "huerfanos": huerfanos})
    finally:
        cx.close()


@app.post("/venues/alias/{alias_id}/asignar")
def venue_alias_asignar(alias_id: int, venue_id: str = Form("")) -> Response:
    """Liga el alias a un foro y REAPUNTA los eventos que lo usan.

    `venue_id` vacío es "no elegí nada": el <select> arranca sin foro
    seleccionado a propósito (asignar es un acto deliberado), así que un submit
    distraído no debe tronar ni ligar nada.
    """
    from src import venues as venues_mod
    if not venue_id.strip():
        return Response(status_code=200)
    try:
        destino = int(venue_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="venue_id inválido") from None
    cx = db.connect()
    try:
        alias = db.get(cx, "venue_alias", alias_id)
        if not alias:
            raise HTTPException(status_code=404, detail="alias no encontrado")
        if not db.get(cx, "venues", destino):
            raise HTTPException(status_code=404, detail="foro no encontrado")
        aid = venues_mod.asignar_alias(cx, destino, alias["alias_visto"])
        if aid is not None:
            venues_mod.reresolver_eventos_de_alias(cx, aid)
        return Response(status_code=200)
    finally:
        cx.close()


@app.post("/venues/alias/{alias_id}/desasignar")
def venue_alias_desasignar(alias_id: int) -> Response:
    """Deshace una asignación: el alias vuelve a la cola de huérfanos.

    Sin esto, un alias mal ligado (el LLM metiendo 'C3 Rooftop' dentro de
    'C3 Stage') salía de la GUI para siempre: la cola solo muestra los que no
    tienen foro y `fusionar` une pero nunca separa.
    """
    from src import venues as venues_mod
    cx = db.connect()
    try:
        if not db.get(cx, "venue_alias", alias_id):
            raise HTTPException(status_code=404, detail="alias no encontrado")
        venues_mod.desasignar_alias(cx, alias_id)
        venues_mod.reresolver_eventos_de_alias(cx, alias_id)
        return Response(status_code=200)
    finally:
        cx.close()


@app.post("/venues/alias/{alias_id}/no-es-lugar")
def venue_alias_basura(alias_id: int) -> Response:
    from src import venues as venues_mod
    cx = db.connect()
    try:
        if not db.get(cx, "venue_alias", alias_id):
            raise HTTPException(status_code=404, detail="alias no encontrado")
        venues_mod.marcar_no_es_lugar(cx, alias_id)
        venues_mod.reresolver_eventos_de_alias(cx, alias_id)
        return Response(status_code=200)
    finally:
        cx.close()


@app.post("/venues/nuevo")
def venue_nuevo(nombre: str = Form(...), alias_id: int | None = Form(None)) -> Response:
    """Crea un foro nuevo y liga el huérfano que originó el alta, si lo hay.

    Si el nombre ya resuelve a un foro del catálogo, REUSA ese foro en vez de
    insertar otro. El formulario viene precargado con el texto del huérfano, así
    que "Crear foro" sobre `Hake al Rey` con `Hake Al Rey` ya en el catálogo era
    el camino corto a partir un foro en dos: el viejo se quedaba con sus eventos
    pero perdía su alias, y los eventos nuevos resolvían al foro vacío.
    """
    from src import venues as venues_mod
    nombre = nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="nombre vacío")
    cx = db.connect()
    try:
        vid = venues_mod.resolver(cx, nombre)
        if vid is None:
            vid = db.insert(cx, "venues", nombre=nombre)
        aid = venues_mod.asignar_alias(cx, vid, nombre)
        if aid is not None:
            venues_mod.reresolver_eventos_de_alias(cx, aid)
        if alias_id:
            alias = db.get(cx, "venue_alias", alias_id)
            if alias:
                aid = venues_mod.asignar_alias(cx, vid, alias["alias_visto"])
                if aid is not None:
                    venues_mod.reresolver_eventos_de_alias(cx, aid)
        return Response(status_code=200)
    finally:
        cx.close()


@app.post("/venues/{venue_id}/fusionar")
def venue_fusionar(venue_id: int, otro_id: int = Form(...)) -> Response:
    """Absorbe `otro_id` en `venue_id`: mismo foro registrado dos veces."""
    from src import venues as venues_mod
    cx = db.connect()
    try:
        if venue_id == otro_id:
            raise HTTPException(status_code=400,
                                detail="un foro no se fusiona consigo mismo")
        if not db.get(cx, "venues", venue_id) or not db.get(cx, "venues", otro_id):
            raise HTTPException(status_code=404, detail="foro no encontrado")
        venues_mod.fusionar(cx, venue_id, otro_id)
        return Response(status_code=200)
    finally:
        cx.close()


# ---------- Plan mensual de contenido (pantalla de badges) ----------

def _mes_actual_plan(mes: str | None) -> str:
    if mes and len(mes) == 7:
        return mes
    from src.planner import proximo_mes
    y, m = proximo_mes()
    return f"{y:04d}-{m:02d}"


_MESES_NOMBRE = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _opciones_meses() -> list[dict]:
    """Mes actual + los siguientes 5, para el selector del plan."""
    hoy = datetime.now()
    out = []
    y, m = hoy.year, hoy.month
    for _ in range(6):
        out.append({"valor": f"{y:04d}-{m:02d}",
                    "label": f"{_MESES_NOMBRE[m - 1]} {y}"})
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


@app.get("/plan", response_class=HTMLResponse)
def plan(request: Request, mes: str | None = None) -> HTMLResponse:
    ym = _mes_actual_plan(mes)
    cx = db.connect()
    try:
        posts = db.rows(cx, """
            SELECT q.id, q.tema_semilla, q.scheduled_datetime, q.photo_id,
                   b.nombre AS banda_nombre, b.tipo, b.prioridad, b.followers_ig
              FROM content_queue q JOIN bands b ON b.id = q.band_id
             WHERE q.status = ? AND q.aprobacion IS NULL
               AND substr(q.scheduled_datetime,1,7) = ?
             ORDER BY q.scheduled_datetime
        """, (db.QUEUE_BORRADOR, ym))
        bandas = len({p["banda_nombre"] for p in posts})
        agendados = db.rows(cx, "SELECT COUNT(*) c FROM content_queue "
                            "WHERE status='publicado' AND substr(scheduled_datetime,1,7)=?", (ym,))[0]["c"]
    finally:
        cx.close()
    return templates.TemplateResponse(request, "plan.html", {
        "posts": posts, "mes": ym, "bandas": bandas, "agendados": agendados,
        "meses": _opciones_meses(),
    })


@app.get("/programados", response_class=HTMLResponse)
def programados(request: Request) -> HTMLResponse:
    """Posts aprobados y agendados: qué se publica y a qué fecha/hora."""
    import pytz
    cx = db.connect()
    try:
        filas = db.rows(cx, """
            SELECT q.id, q.scheduled_datetime, q.photo_id, q.sheet_row_id, q.meme_url,
                   q.tipo AS qtipo, b.nombre AS banda_nombre, b.tipo
              FROM content_queue q LEFT JOIN bands b ON b.id = q.band_id
             WHERE q.status = ? AND q.scheduled_datetime IS NOT NULL
             ORDER BY q.scheduled_datetime
        """, (db.QUEUE_PUBLICADO,))
    finally:
        cx.close()
    ahora = datetime.now(pytz.timezone(config.TIMEZONE)).isoformat()
    return templates.TemplateResponse(request, "programados.html",
                                      {"filas": filas, "ahora": ahora})


@app.post("/plan/generar", response_class=HTMLResponse)
def plan_generar(mes: str = Form(""), replan: int = Form(0)) -> RedirectResponse:
    from src import planner
    ym = _mes_actual_plan(mes or None)
    y, m = map(int, ym.split("-"))
    planner.plan_month(y, m, replan=bool(replan))
    return RedirectResponse(f"/plan?mes={ym}", status_code=303)


@app.post("/plan/{queue_id}/tema", response_class=HTMLResponse)
def plan_tema(queue_id: int, tema_semilla: str = Form("")) -> HTMLResponse:
    cx = db.connect()
    try:
        db.update(cx, "content_queue", queue_id, tema_semilla=tema_semilla.strip() or None)
    finally:
        cx.close()
    return HTMLResponse('<span class="chip">guardado ✓</span>')


@app.post("/plan/{queue_id}/quitar", response_class=HTMLResponse)
def plan_quitar(request: Request, queue_id: int) -> HTMLResponse:
    """Quita un post y lo SUSTITUYE por otro para mantener el plan lleno."""
    from src import planner
    reemplazo = planner.reemplazar(queue_id)
    if reemplazo is None:
        return HTMLResponse("")  # sin reemplazo (pool agotado): solo se quita
    return templates.TemplateResponse(request, "_plan_card.html", {"p": reemplazo})


@app.post("/plan/{queue_id}/flyer", response_class=HTMLResponse)
def plan_marcar_flyer(request: Request, queue_id: int) -> HTMLResponse:
    """Reclasifica el post como flyer: lo manda a Eventos y rellena el slot."""
    from src import planner
    reemplazo = planner.marcar_flyer(queue_id)
    if reemplazo is None:
        return HTMLResponse('<span class="muted">→ flyer (a Eventos)</span>')
    return templates.TemplateResponse(request, "_plan_card.html", {"p": reemplazo})


@app.post("/plan/{queue_id}/eliminar", response_class=HTMLResponse)
def plan_eliminar(request: Request, queue_id: int) -> HTMLResponse:
    """Lista negra: la foto nunca se vuelve a sugerir. Rellena el slot con otra."""
    from src import planner
    reemplazo = planner.eliminar(queue_id)
    if reemplazo is None:
        return HTMLResponse('<span class="muted">🗑 eliminada (no reaparece)</span>')
    return templates.TemplateResponse(request, "_plan_card.html", {"p": reemplazo})


@app.post("/plan/enviar", response_class=HTMLResponse)
def plan_enviar(mes: str = Form("")) -> HTMLResponse:
    """Lanza el envío ASÍNCRONO del plan a Telegram (compatible con el daemon).

    Ya NO abre un poller propio (viejo generate_plan): usa src.send_plan, que
    encola cada meme a 'pendiente' y lo manda con botones. El approval-daemon
    (único poller) resuelve las aprobaciones — de hecho lo REQUIERE vivo.
    """
    ym = _mes_actual_plan(mes or None)
    cx = db.connect()
    try:
        n = db.rows(cx, "SELECT COUNT(*) c FROM content_queue "
                    "WHERE status=? AND aprobacion IS NULL AND tipo='meme' "
                    "AND substr(scheduled_datetime,1,7)=?",
                    (db.QUEUE_BORRADOR, ym))[0]["c"]
    finally:
        cx.close()
    if not n:
        return HTMLResponse(f'No hay borradores por mandar en {ym} '
                            '(¿ya los enviaste todos?).')
    bloqueo = _lanzar_sesion("src.send_plan", "--mes", ym)
    return bloqueo or HTMLResponse(
        f'🚀 Enviando {n} post(s) de {ym} a <strong>Telegram</strong>. '
        'Se componen y llegan UNO POR UNO (el primero en ~30s). '
        'Aprueba/regenera cada uno conforme lleguen (los procesa el daemon).')


# ---------- Cola: qué está por sincronizar al Sheet ----------

@app.get("/cola", response_class=HTMLResponse)
def cola(request: Request) -> HTMLResponse:
    cx = db.connect()
    try:
        filas = db.rows(cx, """
            SELECT q.*, b.nombre AS banda_nombre, m.nombre AS member_nombre,
                   p.id AS foto_id
              FROM content_queue q
              LEFT JOIN bands b ON b.id = q.band_id
              LEFT JOIN members m ON m.id = q.member_id
              LEFT JOIN photos p ON p.id = q.photo_id
             ORDER BY q.status = 'listo' DESC, q.id DESC
        """)
    finally:
        cx.close()
    listos = sum(1 for f in filas if f["status"] == db.QUEUE_LISTO)
    return templates.TemplateResponse(request, "cola.html",
                                      {"filas": filas, "listos": listos})


@app.post("/cola/sync", response_class=HTMLResponse)
def cola_sync() -> RedirectResponse:
    """Empuja las filas 'listo' al Sheet (mismo código que python -m src.sync_sheet)."""
    from src import sync_sheet
    sync_sheet.sync()
    return RedirectResponse("/cola", status_code=303)


@app.post("/cola/{queue_id}/descartar", response_class=HTMLResponse)
def cola_descartar(queue_id: int) -> HTMLResponse:
    cx = db.connect()
    try:
        db.update(cx, "content_queue", queue_id, status=db.QUEUE_DESCARTADO)
    finally:
        cx.close()
    return HTMLResponse('<span class="muted">descartado</span>')


@app.post("/cola/pull", response_class=HTMLResponse)
def cola_pull() -> RedirectResponse:
    """Regreso Sheet→DB: rechazos liberan fotos, published marca publicado."""
    from src import sync_sheet
    sync_sheet.pull_status()
    return RedirectResponse("/cola", status_code=303)


@app.post("/cola/generar", response_class=HTMLResponse)
def cola_generar() -> HTMLResponse:
    """Lanza una sesión de generate.py (Proceso A) en segundo plano."""
    import subprocess
    import sys
    if _daemon_poller_activo():
        return HTMLResponse(_MSG_DAEMON_POLLER)
    if _telegram_busy():
        return HTMLResponse(
            '⚠️ Ya hay una sesión de Telegram activa (bot.py u otra generación). '
            'Espera a que termines esa aprobación antes de lanzar otra.')
    subprocess.Popen([sys.executable, str(config.BASE_DIR / "generate.py")],
                     cwd=config.BASE_DIR,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return HTMLResponse('🚀 Sesión lanzada — los memes de las filas <em>pending</em> '
                        'del Sheet te llegan a <strong>Telegram</strong> en ~30s.')


# ---------- Pipeline de datos (scraping masivo, NO toca Telegram) ----------

_PIPELINE_LOG = config.BASE_DIR / "data" / "pipeline.log"


def _pipeline_corriendo() -> bool:
    import subprocess
    return subprocess.run(["pgrep", "-f", r"src\.pipeline"],
                          capture_output=True).returncode == 0


def _pipeline_status_ctx(request: Request) -> dict:
    """Estado actual del pipeline: corriendo + log + progreso real desde la DB."""
    corriendo = _pipeline_corriendo()
    lineas: list[str] = []
    if _PIPELINE_LOG.exists():
        texto = _PIPELINE_LOG.read_text(errors="replace").strip().splitlines()
        lineas = texto[-18:]  # cola del log
    # Progreso por DB: sirve aunque el proceso no escriba log (refleja lo escrito).
    cx = db.connect()
    try:
        stats = {
            "activas": db.rows(cx, "SELECT COUNT(*) c FROM bands WHERE activa=1")[0]["c"],
            "con_fotos": db.rows(cx, "SELECT COUNT(DISTINCT band_id) c FROM photos")[0]["c"],
            "fotos": db.rows(cx, "SELECT COUNT(*) c FROM photos")[0]["c"],
            "clasificadas": db.rows(cx, "SELECT COUNT(*) c FROM photos WHERE faces_count IS NOT NULL")[0]["c"],
            "usables": db.rows(cx, "SELECT COUNT(*) c FROM photos WHERE usable_meme=1")[0]["c"],
            "eventos": db.rows(cx, "SELECT COUNT(*) c FROM events")[0]["c"],
        }
    finally:
        cx.close()
    return {"corriendo": corriendo, "lineas": lineas, "stats": stats,
            "vacio": not _PIPELINE_LOG.exists() and not corriendo}


@app.post("/pipeline", response_class=HTMLResponse)
def lanzar_pipeline(request: Request, skip: str = Form("")) -> HTMLResponse:
    """Corre ingest→classify→spotify→events sobre las bandas activas, en background."""
    import subprocess
    import sys
    if _pipeline_corriendo():
        return templates.TemplateResponse(request, "_pipeline_status.html", _pipeline_status_ctx(request))
    _PIPELINE_LOG.parent.mkdir(parents=True, exist_ok=True)
    args = ["--skip", skip] if skip else []
    log = open(_PIPELINE_LOG, "w")  # noqa: SIM115 — vive con el subproceso
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}  # log en vivo, sin buffer
    subprocess.Popen([sys.executable, "-u", "-m", "src.pipeline", *args],
                     cwd=config.BASE_DIR, stdout=log, stderr=subprocess.STDOUT, env=env)
    return templates.TemplateResponse(request, "_pipeline_status.html", _pipeline_status_ctx(request))


@app.get("/pipeline/status", response_class=HTMLResponse)
def pipeline_status(request: Request) -> HTMLResponse:
    """Panel de progreso del pipeline (lo refresca el polling de HTMX)."""
    return templates.TemplateResponse(request, "_pipeline_status.html", _pipeline_status_ctx(request))


# ---------- Clasificación desde la GUI (Fase 3) ----------

@app.post("/bandas/{band_id}/clasificar", response_class=HTMLResponse)
def clasificar_banda(band_id: int, redo: int = Form(0)) -> RedirectResponse:
    """Corre el clasificador (caras/nitidez/flyers) sobre las fotos de la banda."""
    from src import classify
    cx = db.connect()
    try:
        band = db.get(cx, "bands", band_id)
    finally:
        cx.close()
    if band and band.get("ig_handle"):
        classify.clasificar([band["ig_handle"]], redo=bool(redo))
    return RedirectResponse(f"/bandas/{band_id}/detalle", status_code=303)


@app.post("/bandas/{band_id}/spotify", response_class=HTMLResponse)
def reenriquecer_spotify(request: Request, band_id: int) -> HTMLResponse:
    """Re-enriquece una banda con Spotify y devuelve su fila actualizada."""
    from src import enrich_spotify
    cx = db.connect()
    try:
        band = db.get(cx, "bands", band_id)
        if band:
            try:
                etiqueta = enrich_spotify.enrich_band(enrich_spotify.get_client(), cx, band)
                print(f"♻ Spotify {band['nombre']}: {etiqueta}")
            except Exception as exc:  # noqa: BLE001 — mostrar el error en la fila, no tirar la GUI
                print(f"♻ Spotify {band['nombre']}: ❌ {exc}")
        band = _band_view(db.get(cx, "bands", band_id))
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_band_row.html", {"b": band})


# ---------- Eventos: flyers detectados y fechas (se parsean en Fase 5) ----------

@app.get("/calendario", response_class=HTMLResponse)
def calendario(request: Request) -> HTMLResponse:
    """Vista de los calendarios de flyers/eventos, agrupados por semana y mes.

    Separada del plan de memes: con flyers NO se hacen memes, solo calendarios.
    """
    from src.generate_agenda import (
        agrupar_por_evento,
        eventos_ventana,
        releases_proximos,
        releases_ventana,
    )
    cx = db.connect()
    try:
        # "Esta semana" (días 0-7) = lo que Ricardo postea miér/jue antes del finde.
        # "Todo el mes" = TODO lo registrado en la ventana de 30 días (incluida esta
        # semana) — coherente con lo que genera el botón "post mensual".
        shows7 = eventos_ventana(cx, 7)
        shows_mes = eventos_ventana(cx, 30)
        rel7 = releases_ventana(cx, 7)
        rel_mes = releases_ventana(cx, 30)
        ctx = {
            "shows_semana": agrupar_por_evento(shows7),
            "shows_mes": agrupar_por_evento(shows_mes),
            "releases_proximos": releases_proximos(cx, 60),
            "releases_semana": rel7,
            "releases_mes": rel_mes,
            "sin_fecha": db.rows(cx, """
                SELECT e.id, e.flyer_path, b.nombre AS banda_nombre FROM events e
                  JOIN bands b ON b.id = e.band_id
                 WHERE e.tipo = 'flyer' AND e.fecha_evento IS NULL
                   AND e.status != 'pasado' AND e.irrelevante = 0
                 ORDER BY e.id DESC
            """),
        }
    finally:
        cx.close()
    return templates.TemplateResponse(request, "calendario.html", ctx)


@app.post("/eventos/borrar", response_class=HTMLResponse)
def eventos_borrar(ids: str = Form(...)) -> RedirectResponse:
    """Quita una fecha del agenda (borra esos eventos). `ids` coma-separados."""
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    cx = db.connect()
    try:
        for eid in id_list:
            cx.execute("DELETE FROM events WHERE id = ?", (eid,))
        cx.commit()
    finally:
        cx.close()
    return RedirectResponse("/calendario", status_code=303)


@app.post("/eventos/al-final", response_class=HTMLResponse)
def eventos_al_final(ids: str = Form(...)) -> RedirectResponse:
    """Manda esos eventos al FINAL del carrusel (toggle al_final). Ej: fechas de CDMX."""
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    cx = db.connect()
    try:
        for eid in id_list:
            actual = db.get(cx, "events", eid)
            if actual:
                db.update(cx, "events", eid, al_final=0 if actual.get("al_final") else 1)
    finally:
        cx.close()
    return RedirectResponse("/calendario", status_code=303)


@app.post("/eventos/{event_id}/irrelevante", response_class=HTMLResponse)
def evento_irrelevante(request: Request, event_id: int) -> HTMLResponse:
    """Toggle de la lista negra: flyers de fechas pasadas o que no son flyers."""
    cx = db.connect()
    try:
        actual = db.get(cx, "events", event_id)
        if actual is None:
            raise HTTPException(404)
        db.update(cx, "events", event_id,
                  irrelevante=0 if actual.get("irrelevante") else 1)
        evento = db.rows(cx, """
            SELECT e.*, b.nombre AS banda_nombre FROM events e
              JOIN bands b ON b.id = e.band_id WHERE e.id = ?
        """, (event_id,))[0]
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_event_row.html", {"e": evento})


@app.post("/eventos/parsear", response_class=HTMLResponse)
def eventos_parsear() -> RedirectResponse:
    """Pasa los flyers pendientes por DeepSeek para extraer fecha/lugar/ciudad."""
    from src import parse_events
    parse_events.parse_all()
    return RedirectResponse("/eventos", status_code=303)


def _telegram_busy() -> bool:
    """¿Hay ya un proceso usando el bot de Telegram? (bot.py o cualquier generate*)."""
    import subprocess
    patrones = [r"python.*bot\.py", r"src\.generate"]
    return any(subprocess.run(["pgrep", "-f", p], capture_output=True).returncode == 0
               for p in patrones)


# Flujos BLOQUEANTES (abren su propio poller y esperan tu aprobación): chocan con
# el daemon de aprobación, que es el poller permanente. Si el daemon corre (lo
# normal), se rechazan con un mensaje claro en vez de lanzar un proceso que muere.
_MSG_DAEMON_POLLER = (
    '⚠️ El daemon de aprobación es el único poller de Telegram (corre siempre). '
    'Este flujo manual abriría un segundo poller y chocaría. '
    'Para memes: manda la foto directo al bot (el daemon la procesa). '
    'Para agenda/música nueva: usa los botones de Agenda (flujo del motor).')


def _daemon_poller_activo() -> bool:
    from src import poller_lock
    return poller_lock.daemon_pid() is not None


def _lanzar_sesion(modulo: str, *args: str) -> HTMLResponse | None:
    """Lanza un módulo que usa el bot de Telegram; None si otro ya lo ocupa."""
    import subprocess
    import sys
    if _telegram_busy():
        return HTMLResponse(
            '⚠️ Ya hay una sesión de Telegram activa (bot.py u otra generación). '
            'Espera a que termines esa aprobación antes de lanzar otra.')
    log = open(config.BASE_DIR / "data" / "telegram_session.log", "w")  # noqa: SIM115
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    subprocess.Popen([sys.executable, "-u", "-m", modulo, *args], cwd=config.BASE_DIR,
                     stdout=log, stderr=subprocess.STDOUT, env=env)
    return None


@app.post("/novedades", response_class=HTMLResponse)
def lanzar_novedades() -> HTMLResponse:
    """Lanza la detección de novedades (releases nuevos) con aviso por Telegram."""
    bloqueo = _lanzar_sesion("src.novedades")
    return bloqueo or HTMLResponse(
        '🔄 Buscando novedades — los releases nuevos detectados te llegan a '
        '<strong>Telegram</strong> en cuanto estén.')


@app.post("/followees/sync", response_class=HTMLResponse)
def sync_followees() -> HTMLResponse:
    """Importa las cuentas que sigue @gdlscene como bandas candidatas (activa=0)."""
    from src import import_followees
    from src.ingest_ig import IngestRateLimited
    try:
        r = import_followees.importar()
    except IngestRateLimited as exc:
        return HTMLResponse(f"⚠️ IG limitó la sesión ({exc}) — reintenta en unas horas.")
    except Exception as exc:  # noqa: BLE001 — mostrar el error en el panel, no tirar la GUI
        return HTMLResponse(f"❌ {exc}")
    if r["nuevas"]:
        return HTMLResponse(
            f'✅ <strong>{r["nuevas"]}</strong> candidatas nuevas (de {r["total"]} seguidas) · '
            f'<a href="/bandas?todas=1">revisarlas</a>')
    return HTMLResponse(f"✅ Sin cuentas nuevas — las {r['total']} seguidas ya están en la DB.")


@app.post("/eventos/anunciar", response_class=HTMLResponse)
def eventos_anunciar() -> HTMLResponse:
    """Lanza la sesión de anuncios (aprobación por Telegram), como Generar memes."""
    if _daemon_poller_activo():
        return HTMLResponse(_MSG_DAEMON_POLLER)
    bloqueo = _lanzar_sesion("src.generate_anuncios")
    return bloqueo or HTMLResponse(
        '🚀 Sesión de anuncios lanzada — las tarjetas de eventos con fecha futura '
        'te llegan a <strong>Telegram</strong> en ~30s. Al aprobar se publican de inmediato.')


@app.post("/eventos/agenda/{modo}/{periodo}", response_class=HTMLResponse)
def eventos_agenda(modo: str, periodo: str) -> HTMLResponse:
    """Genera shows (agenda) o releases (música nueva), semanal o mensual."""
    if periodo not in ("semanal", "mensual") or modo not in ("shows", "releases"):
        raise HTTPException(400, "modo/periodo inválido")
    bloqueo = _lanzar_sesion("src.generate_agenda", "--segmento", "--modo", modo, "--periodo", periodo)
    if bloqueo:
        return bloqueo
    if modo == "shows":
        return HTMLResponse(f'🗓 Agenda {periodo} en camino a <strong>Telegram</strong> '
                            '(en partes si hay muchos flyers). Al aprobar se publica de inmediato.')
    return HTMLResponse(f'🎵 Música nueva {periodo} en camino a <strong>Telegram</strong>. '
                        'Al aprobar se publica de inmediato.')


_EVENTOS_ORDER = {
    "fecha_asc": "e.fecha_evento IS NULL, e.fecha_evento ASC",
    "fecha_desc": "e.fecha_evento IS NULL, e.fecha_evento DESC",
    "tipo": "e.tipo, e.fecha_evento",
    "nuevo": "e.status = 'nuevo' DESC, e.fecha_evento IS NULL, e.fecha_evento",
}


# Filtro "incompletos": lo que el parseo automático no pudo llenar y hay que
# corregir a mano — sin fecha, o sin lugar (los releases no llevan lugar).
_EVENTOS_INCOMPLETOS = """
    (e.fecha_evento IS NULL OR e.fecha_evento = '')
    OR (e.tipo != 'release' AND (e.lugar IS NULL OR e.lugar = ''))
"""


@app.get("/eventos", response_class=HTMLResponse)
def eventos(request: Request, order: str = "nuevo", solo: str = "") -> HTMLResponse:
    orden = _EVENTOS_ORDER.get(order, _EVENTOS_ORDER["nuevo"])
    if solo == "irrelevantes":
        where = "WHERE e.irrelevante = 1"
    elif solo == "incompletos":
        where = f"WHERE e.irrelevante = 0 AND ({_EVENTOS_INCOMPLETOS})"
    else:
        where = "WHERE e.irrelevante = 0"
    cx = db.connect()
    try:
        filas = db.rows(cx, f"""
            SELECT e.*, b.nombre AS banda_nombre FROM events e
              JOIN bands b ON b.id = e.band_id
              {where}
             ORDER BY {orden}
        """)
    finally:
        cx.close()
    return templates.TemplateResponse(request, "eventos.html",
                                      {"eventos": filas, "order": order, "solo": solo})


@app.post("/eventos/{event_id}", response_class=HTMLResponse)
def guardar_evento(request: Request, event_id: int, tipo: str = Form("flyer"),
                   fecha_evento: str = Form(""), lugar: str = Form(""),
                   ciudad: str = Form(""), status: str = Form("nuevo")) -> HTMLResponse:
    from src import venues as venues_mod
    cx = db.connect()
    try:
        previo = db.get(cx, "events", event_id)
        nuevo_lugar = lugar.strip() or None
        db.update(cx, "events", event_id,
                  tipo=tipo if tipo in ("fecha", "flyer", "release") else "flyer",
                  fecha_evento=fecha_evento.strip() or None,
                  lugar=nuevo_lugar,
                  ciudad=ciudad.strip() or None,
                  status=status if status in ("nuevo", "anunciado", "pasado") else "nuevo")
        # Tercer camino que escribe `events.lugar` (los otros dos son
        # parse_events y detect_releases_ig): si el texto cambió, el venue_id
        # viejo dejó de aplicar. Dejarlo pegado fusionaría el evento con el foro
        # equivocado en la agenda — una corrección a mano haría desaparecer un show.
        if previo and (previo.get("lugar") or None) != nuevo_lugar:
            vid = venues_mod.resolver(cx, nuevo_lugar) if nuevo_lugar else None
            db.update(cx, "events", event_id, venue_id=vid)
            if nuevo_lugar and vid is None:
                venues_mod.registrar_desconocido(cx, nuevo_lugar)
        evento = db.rows(cx, """
            SELECT e.*, b.nombre AS banda_nombre FROM events e
              JOIN bands b ON b.id = e.band_id WHERE e.id = ?
        """, (event_id,))[0]
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_event_row.html", {"e": evento})


@app.get("/segmentos", response_class=HTMLResponse)
def segmentos(request: Request) -> HTMLResponse:
    """Estado del motor de segmentos + preview del contenido que usaría hoy."""
    from src import segments_vista
    from src.catalogo import REGISTRO
    cx = db.connect()
    try:
        vista = segments_vista.vista_segmentos(cx, REGISTRO)
    finally:
        cx.close()
    return templates.TemplateResponse(
        request, "segmentos.html",
        {"segmentos": vista, "daemon_activo": _daemon_poller_activo()})


@app.get("/cover/{event_id}")
def servir_cover(event_id: int):
    """Portada de un release vía caché data/covers (el DNS local mata i.scdn.co)."""
    from src import covers
    cx = db.connect()
    try:
        evento = db.get(cx, "events", event_id)
    finally:
        cx.close()
    if evento is None or not evento.get("cover_url"):
        raise HTTPException(404)
    url = evento["cover_url"]
    if not url.startswith(("http://", "https://")):  # ruta local (foto del post IG)
        p = Path(url)
        p = p if p.is_absolute() else config.BASE_DIR / p
        if p.exists():
            return FileResponse(p)
        raise HTTPException(404)
    local = covers.asegurar_cover(url)
    if local:
        return FileResponse(local)
    return RedirectResponse(url)  # último recurso: que el browser lo intente


@app.get("/flyer/{event_id}")
def servir_flyer(event_id: int) -> FileResponse:
    cx = db.connect()
    try:
        evento = db.get(cx, "events", event_id)
    finally:
        cx.close()
    if evento is None or not evento.get("flyer_path"):
        raise HTTPException(404)
    path = Path(evento["flyer_path"])
    if not path.is_absolute():
        path = config.BASE_DIR / path
    if not path.exists():
        raise HTTPException(404, f"Archivo no encontrado: {path}")
    return FileResponse(path)


# ============================== Publicado ====================================
# Posts ya publicados en IG con sus métricas; resumen por banda con sugerencia
# de prioridad. Spec: docs/superpowers/specs/2026-06-07-pagina-publicado-design.md

_STALE_HOURS = 6
_ORDEN_POSTS = {
    "fecha": "p.timestamp DESC",
    "likes": "p.likes DESC",
    # ER aproximado en SQL para ordenar; el cálculo fino vive en band_stats
    "er": "CASE WHEN p.reach > 0 THEN (p.likes + 2.0*p.comments + 3.0*COALESCE(p.saved,0)) / p.reach END DESC",
}


def _publicado_posts(cx, banda: int, orden: str) -> list[dict[str, Any]]:
    where = "WHERE p.band_id = ?" if banda else ""
    params: tuple = (banda,) if banda else ()
    order_sql = _ORDEN_POSTS.get(orden, _ORDEN_POSTS["fecha"])
    return db.rows(cx, f"""
        SELECT p.*, b.nombre AS banda_nombre
          FROM ig_posts p LEFT JOIN bands b ON b.id = p.band_id
          {where}
         ORDER BY {order_sql} NULLS LAST, p.timestamp DESC
    """, params)


@app.get("/publicado", response_class=HTMLResponse)
def publicado(request: Request, banda: int = 0, orden: str = "fecha",
              error: str = "", aviso: str = "") -> HTMLResponse:
    from src import ig_insights
    cx = db.connect()
    try:
        posts = _publicado_posts(cx, banda, orden)
        stats = ig_insights.band_stats(cx)
        bandas = db.list_bands(cx, solo_activas=False, order="nombre")
        ultimo = ig_insights.last_sync(cx)
    finally:
        cx.close()
    stale = True
    if ultimo:
        try:
            edad = datetime.now() - datetime.fromisoformat(ultimo)
            stale = edad.total_seconds() > _STALE_HOURS * 3600
        except ValueError:
            pass
    return templates.TemplateResponse(request, "publicado.html", {
        "posts": posts, "stats": stats, "bandas": bandas, "ultimo": ultimo,
        "stale": stale, "banda": banda, "orden": orden,
        "error": error, "aviso": aviso,
    })


@app.post("/publicado/sync")
def publicado_sync() -> RedirectResponse:
    """Sync completo contra la Graph API. Errores → banner, nunca página rota."""
    from urllib.parse import quote

    from src import ig_insights
    cx = db.connect()
    try:
        res = ig_insights.sync_posts(cx)
    except Exception as exc:  # noqa: BLE001 — token vencido, sin red, etc.
        return RedirectResponse(f"/publicado?error={quote(str(exc)[:300])}", status_code=303)
    finally:
        cx.close()
    aviso = f"Sync: {res['posts']} posts, {res['insights_fallidos']} sin insights"
    if res.get("warning"):
        aviso += f" — {res['warning']}"
    return RedirectResponse(f"/publicado?aviso={quote(aviso)}", status_code=303)


@app.post("/publicado/{post_id}/banda", response_class=HTMLResponse)
def publicado_asignar_banda(request: Request, post_id: int,
                            band_id: int = Form(0)) -> HTMLResponse:
    """Asigna banda a mano a un post manual/viejo. Devuelve la card actualizada."""
    cx = db.connect()
    try:
        db.update(cx, "ig_posts", post_id, band_id=band_id or None)
        post = db.rows(cx, """
            SELECT p.*, b.nombre AS banda_nombre
              FROM ig_posts p LEFT JOIN bands b ON b.id = p.band_id
             WHERE p.id = ?
        """, (post_id,))[0]
        bandas = db.list_bands(cx, solo_activas=False, order="nombre")
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_ig_post_card.html",
                                      {"p": post, "bandas": bandas})


@app.post("/publicado/banda/{band_id}/prioridad", response_class=HTMLResponse)
def publicado_aplicar_prioridad(request: Request, band_id: int,
                                prioridad: int = Form(...)) -> HTMLResponse:
    """Aplica la prioridad sugerida. Devuelve la fila del resumen actualizada."""
    from src import ig_insights
    cx = db.connect()
    try:
        db.update(cx, "bands", band_id, prioridad=max(1, min(5, prioridad)))
        stats = ig_insights.band_stats(cx)
    finally:
        cx.close()
    fila = next((s for s in stats if s["band_id"] == band_id), None)
    if fila is None:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "_publicado_banda_row.html", {"s": fila})


# ============================== Spotify match ================================
# Completar spotify_id de bandas activas 'pendiente': búsqueda en vivo + elección
# manual, y un botón para el resolvedor por links de bio.
# Spec: docs/superpowers/specs/2026-06-07-afinacion-datos-design.md (Frente B).

@app.get("/spotify", response_class=HTMLResponse)
def spotify_view(request: Request, aviso: str = "") -> HTMLResponse:
    """Bandas activas sin id, cada una con su top-5 de candidatos (búsqueda en vivo).

    Si Spotify no responde, la página carga igual con el error visible y sin
    candidatos (el usuario aún puede pegar un id a mano o marcar "no está").
    """
    cx = db.connect()
    try:
        pendientes = db.rows(cx, """
            SELECT * FROM bands
             WHERE activa = 1 AND spotify_status = 'pendiente'
               AND tipo IN ('banda','solista')
             ORDER BY prioridad DESC, nombre COLLATE NOCASE
        """)
    finally:
        cx.close()

    error_global = None
    sp = None
    try:
        sp = spotify_match.get_client()
    except Exception as exc:  # noqa: BLE001 — sin credenciales/Spotify caído: degradar
        error_global = f"Spotify no disponible: {exc}"

    for b in pendientes:
        b["candidatos"] = []
        b["search_error"] = None
        if sp is None:
            continue
        try:
            b["candidatos"] = spotify_match.candidatos(sp, b["nombre"])
        except Exception as exc:  # noqa: BLE001 — un fallo puntual no tira la página
            b["search_error"] = str(exc)

    return templates.TemplateResponse(request, "spotify.html",
                                      {"bandas": pendientes, "error_global": error_global,
                                       "aviso": aviso})


@app.post("/spotify/{band_id}/elegir", response_class=HTMLResponse)
def spotify_elegir(request: Request, band_id: int,
                   spotify_id: str = Form(...)) -> HTMLResponse:
    """Guarda el id elegido, marca 'ok' y registra releases. Devuelve vacío (HTMX
    quita la fila)."""
    spotify_id = spotify_id.strip()
    if not spotify_id:
        raise HTTPException(400, "spotify_id vacío")
    cx = db.connect()
    try:
        if db.get(cx, "bands", band_id) is None:
            raise HTTPException(404)
        db.update(cx, "bands", band_id, spotify_id=spotify_id, spotify_status="ok")
        try:
            spotify_match._registrar_releases(spotify_match.get_client(), cx,
                                              band_id, spotify_id)
        except Exception as exc:  # noqa: BLE001 — el id ya quedó guardado; releases es bonus
            print(f"♫ releases de {band_id}: ❌ {exc}")
    finally:
        cx.close()
    return HTMLResponse("")


@app.post("/spotify/{band_id}/no-esta", response_class=HTMLResponse)
def spotify_no_esta(band_id: int) -> HTMLResponse:
    """Marca que la banda no está en Spotify (no se vuelve a buscar). HTMX quita la fila."""
    cx = db.connect()
    try:
        if db.get(cx, "bands", band_id) is None:
            raise HTTPException(404)
        db.update(cx, "bands", band_id, spotify_status="no_esta")
    finally:
        cx.close()
    return HTMLResponse("")


@app.post("/spotify/resolver-links", response_class=HTMLResponse)
def spotify_resolver_links() -> RedirectResponse:
    """Corre el resolvedor por links de bio y vuelve a /spotify con el resumen."""
    from urllib.parse import quote
    cx = db.connect()
    try:
        try:
            res = spotify_match.resolver_links(cx)
            aviso = (f"Links: {res['resueltas']} resueltas de {res['revisadas']} "
                     f"({res['sin_link']} sin Spotify, {res['fallidas']} caídas)")
        except Exception as exc:  # noqa: BLE001 — rate limit u otro: mostrarlo, no tirar la GUI
            aviso = f"Resolvedor falló: {exc}"
    finally:
        cx.close()
    return RedirectResponse(f"/spotify?aviso={quote(aviso)}", status_code=303)


# ============================== Deezer match =================================
# Completar deezer_id de bandas activas 'pendiente': búsqueda en vivo + elección
# manual, y un botón para el auto-match exacto por nombre.
# Spec: docs/superpowers/specs/2026-06-08-deezer-releases-design.md

# Tope de búsquedas en vivo al cargar /deezer: arriba de esto pedimos correr el
# auto-match primero (96 búsquedas en una carga rozaría el ~50 req/5s de Deezer).
_DEEZER_BUSQUEDA_VIVO_MAX = 15


@app.get("/deezer", response_class=HTMLResponse)
def deezer_view(request: Request, aviso: str = "") -> HTMLResponse:
    """Bandas activas sin deezer_id. Candidatos en vivo solo si quedan pocas."""
    from src import deezer, deezer_match
    cx = db.connect()
    try:
        pendientes = db.rows(cx, """
            SELECT * FROM bands
             WHERE activa = 1 AND deezer_status = 'pendiente'
               AND tipo IN ('banda','solista')
             ORDER BY prioridad DESC, nombre COLLATE NOCASE
        """)
        muchas = len(pendientes) > _DEEZER_BUSQUEDA_VIVO_MAX
        for b in pendientes:
            b["candidatos"] = []
            b["search_error"] = None
            if muchas:
                continue  # demasiadas: el banner pide correr Auto-match primero
            try:
                b["candidatos"] = deezer_match.candidatos(cx, b["id"])
            except deezer.DeezerError as exc:
                b["search_error"] = str(exc)
    finally:
        cx.close()
    return templates.TemplateResponse(request, "deezer.html",
                                      {"bandas": pendientes, "aviso": aviso,
                                       "muchas": muchas})


@app.post("/deezer/{band_id}/elegir", response_class=HTMLResponse)
def deezer_elegir(request: Request, band_id: int,
                  deezer_id: str = Form(...)) -> HTMLResponse:
    from src import deezer_match
    deezer_id = deezer_id.strip()
    if not deezer_id:
        raise HTTPException(400, "deezer_id vacío")
    cx = db.connect()
    try:
        if db.get(cx, "bands", band_id) is None:
            raise HTTPException(404)
        try:
            deezer_match.elegir(cx, band_id, deezer_id)
        except Exception as exc:  # noqa: BLE001 — el id ya quedó; releases es bonus
            print(f"♫ releases Deezer de {band_id}: ❌ {exc}")
    finally:
        cx.close()
    return HTMLResponse("")


@app.post("/deezer/{band_id}/no-esta", response_class=HTMLResponse)
def deezer_no_esta(band_id: int) -> HTMLResponse:
    from src import deezer_match
    cx = db.connect()
    try:
        if db.get(cx, "bands", band_id) is None:
            raise HTTPException(404)
        deezer_match.marcar_no_esta(cx, band_id)
    finally:
        cx.close()
    return HTMLResponse("")


@app.post("/deezer/resolver-auto")
def deezer_resolver_auto() -> RedirectResponse:
    from urllib.parse import quote

    from src import deezer_match
    cx = db.connect()
    try:
        res = deezer_match.resolver_preciso(cx)
    finally:
        cx.close()
    aviso = (f"Match: {res['ok_link']} por link + {res['ok_spotify']} por Spotify; "
             f"{res['sin_confirmar']} sin confirmar (revísalas abajo).")
    return RedirectResponse(f"/deezer?aviso={quote(aviso)}", status_code=303)


@app.post("/deezer/purgar")
def deezer_purgar() -> RedirectResponse:
    from urllib.parse import quote

    from src import deezer_match
    cx = db.connect()
    try:
        res = deezer_match.purgar(cx)
    finally:
        cx.close()
    aviso = (f"Purga: {res['bandas']} bandas des-ligadas, {res['releases']} releases "
             "de Deezer borrados. Corre el match preciso de nuevo.")
    return RedirectResponse(f"/deezer?aviso={quote(aviso)}", status_code=303)


@app.get("/marcas", response_class=HTMLResponse)
def marcas_vista(request: Request) -> HTMLResponse:
    """Marcas registradas + checklist de credenciales de .env por marca."""
    from src import marcas as marcas_mod
    cx = db.connect()
    try:
        db.init_db(cx)
        lista = marcas_mod.listar(cx, solo_activas=False)
        slug_editar = request.query_params.get("slug", "")
        editar = None
        if slug_editar:
            try:
                editar = marcas_mod.cargar(cx, slug_editar)
            except ValueError:
                editar = None
    finally:
        cx.close()
    filas = [{"m": m, "faltan": marcas_mod.creds_faltantes(m.slug)}
             for m in lista]
    return templates.TemplateResponse(request, "marcas.html", {
        "filas": filas, "mensaje": request.query_params.get("msg", ""),
        "editar": editar,
    })


@app.post("/marcas/guardar", response_class=HTMLResponse)
def marcas_guardar(slug: str = Form(...), nombre: str = Form(""),
                   ig_handle: str = Form(""), color_marca: str = Form(""),
                   voz: str = Form(""), fuentes_imagen: str = Form(""),
                   formatos: str = Form(""), posting_slots: str = Form(""),
                   estilos_json: str = Form(""), logo_path: str = Form(""),
                   activa: str = Form("1")) -> HTMLResponse:
    """Upsert del PERFIL de la marca. Los secretos van en .env, nunca aquí."""
    import json as json_mod
    slug = slug.strip().lower()
    if estilos_json.strip():
        try:
            json_mod.loads(estilos_json)
        except ValueError as e:
            return HTMLResponse(f"⚠️ estilos_json inválido: {e}")
    campos = {
        "nombre": nombre.strip() or slug,
        "ig_handle": ig_handle.strip(),
        "color_marca": color_marca.strip() or "#1b5e3f",
        "voz": voz.strip(),
        "fuentes_imagen": json_mod.dumps(
            [f.strip() for f in fuentes_imagen.split(",") if f.strip()])
            if fuentes_imagen.strip() else None,
        "formatos": json_mod.dumps(
            [f.strip() for f in formatos.split(",") if f.strip()])
            if formatos.strip() else None,
        "posting_slots": posting_slots.strip() or None,
        "estilos_json": estilos_json.strip() or None,
        "logo_path": logo_path.strip() or None,
        "activa": 1 if activa == "1" else 0,
    }
    cx = db.connect()
    try:
        db.init_db(cx)
        fila = db.rows(cx, "SELECT id FROM accounts WHERE slug = ?", (slug,))
        if fila:
            db.update(cx, "accounts", fila[0]["id"], **campos)
        else:
            db.insert(cx, "accounts", slug=slug, ciudad="", **campos)
    finally:
        cx.close()
    return HTMLResponse(f"✅ Marca {slug} guardada. "
                        '<a href="/marcas">volver</a>')


@app.get("/slideshows", response_class=HTMLResponse)
def slideshows_vista(request: Request) -> HTMLResponse:
    """Form para generar un slideshow (motor genérico, spec 2026-08-09)."""
    from src import marcas as marcas_mod
    cx = db.connect()
    try:
        db.init_db(cx)
        marcas_activas = [m.slug for m in marcas_mod.listar(cx, solo_activas=True)]
    finally:
        cx.close()
    return templates.TemplateResponse(request, "slideshows.html", {
        "formatos": sorted(config.SLIDESHOW_FORMATOS),
        "estilos": sorted(config.SLIDESHOW_ESTILOS),
        "marcas_activas": marcas_activas,
    })


@app.post("/slideshows/generar", response_class=HTMLResponse)
def slideshows_generar(tema: str = Form(...), marca: str = Form("gdlscene"),
                       formato: str = Form(""), estilo: str = Form(""),
                       fuentes: str = Form(""), n_slides: int = Form(6),
                       contexto: str = Form("")) -> HTMLResponse:
    """Lanza el generador de slideshows detached; llega a Telegram a aprobar."""
    args = ["--tema", tema, "--marca", marca, "--n-slides", str(n_slides)]
    if formato.strip():
        args += ["--formato", formato.strip()]
    if estilo.strip():
        args += ["--estilo", estilo.strip()]
    if fuentes.strip():
        args += ["--fuentes", fuentes.strip()]
    if contexto.strip():
        args += ["--contexto", contexto.strip()]
    bloqueo = _lanzar_sesion("src.generate_slideshow", *args)
    if bloqueo:
        return bloqueo
    return HTMLResponse("⏳ Generando slideshow… llegará a Telegram para aprobar.")
