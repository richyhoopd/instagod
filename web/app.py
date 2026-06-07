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

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config
from src import db

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
           solo: str = "") -> HTMLResponse:
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
    return templates.TemplateResponse(request, "bandas.html", {
        "bandas": items, "order": order, "todas": todas, "solo": solo,
        "candidatas": candidatas, "activas": activas, "sin_scrapear": sin_scrapear,
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
    return templates.TemplateResponse(request, "_band_edit.html", {"b": band})


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
                  generos: str = Form(""), prioridad: int = Form(3),
                  n_integrantes: str = Form(""), notas: str = Form(""),
                  activa: int = Form(0)) -> HTMLResponse:
    import json
    generos_json = None
    if generos.strip():
        generos_json = json.dumps([g.strip() for g in generos.split(",") if g.strip()],
                                  ensure_ascii=False)
    tipos_ok = {"banda", "solista", "foro", "evento", "colectivo"}
    cx = db.connect()
    try:
        db.update(cx, "bands", band_id,
                  nombre=nombre.strip(),
                  tipo=tipo if tipo in tipos_ok else "banda",
                  ig_handle=ig_handle.strip().lstrip("@") or None,
                  spotify_id=spotify_id.strip() or None,
                  ciudad=ciudad.strip() or None,
                  generos=generos_json,
                  prioridad=max(1, min(5, prioridad)),
                  n_integrantes=int(n_integrantes) if n_integrantes.strip().isdigit() else None,
                  notas=notas.strip() or None,
                  activa=1 if activa else 0)
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
             WHERE q.status = ? AND substr(q.scheduled_datetime,1,7) = ?
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
    """Marca el plan del mes como 'listo' y lanza el envío masivo a Telegram."""
    ym = _mes_actual_plan(mes or None)
    if _telegram_busy():
        return HTMLResponse('⚠️ Ya hay una sesión de Telegram activa. Espera a que termine.')
    cx = db.connect()
    try:
        cx.execute("""UPDATE content_queue SET status = ?
                       WHERE status = ? AND substr(scheduled_datetime,1,7) = ?""",
                   (db.QUEUE_LISTO, db.QUEUE_BORRADOR, ym))
        cx.commit()
        n = db.rows(cx, "SELECT COUNT(*) c FROM content_queue WHERE status=? AND substr(scheduled_datetime,1,7)=?",
                    (db.QUEUE_LISTO, ym))[0]["c"]
    finally:
        cx.close()
    import subprocess
    import sys
    log = open(config.BASE_DIR / "data" / "generate_plan.log", "w")  # noqa: SIM115
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    subprocess.Popen([sys.executable, "-u", "-m", "src.generate_plan", "--mes", ym],
                     cwd=config.BASE_DIR, stdout=log, stderr=subprocess.STDOUT, env=env)
    return HTMLResponse(f'🚀 Enviando {n} post(s) de {ym} a <strong>Telegram</strong>. '
                        'Se componen y llegan UNO POR UNO (el primero en ~30s). '
                        'Aprueba/regenera cada uno conforme lleguen.')


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
    from src.generate_agenda import agrupar_por_evento, eventos_ventana, releases_ventana
    cx = db.connect()
    try:
        # Secciones EXCLUYENTES: "esta semana" = días 0-7; "este mes" = días 8-30,
        # para que un evento de esta semana NO aparezca también en el mes.
        shows7 = eventos_ventana(cx, 7)
        ids7 = {e["id"] for e in shows7}
        shows_resto = [e for e in eventos_ventana(cx, 30) if e["id"] not in ids7]
        rel7 = releases_ventana(cx, 7)
        ids_rel7 = {e["id"] for e in rel7}
        rel_resto = [e for e in releases_ventana(cx, 30) if e["id"] not in ids_rel7]
        ctx = {
            "shows_semana": agrupar_por_evento(shows7),
            "shows_mes": agrupar_por_evento(shows_resto),
            "releases_semana": rel7,
            "releases_mes": rel_resto,
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


@app.post("/eventos/anunciar", response_class=HTMLResponse)
def eventos_anunciar() -> HTMLResponse:
    """Lanza la sesión de anuncios (aprobación por Telegram), como Generar memes."""
    bloqueo = _lanzar_sesion("src.generate_anuncios")
    return bloqueo or HTMLResponse(
        '🚀 Sesión de anuncios lanzada — las tarjetas de eventos con fecha futura '
        'te llegan a <strong>Telegram</strong> en ~30s. Al aprobar se publican de inmediato.')


@app.post("/eventos/agenda/{modo}/{periodo}", response_class=HTMLResponse)
def eventos_agenda(modo: str, periodo: str) -> HTMLResponse:
    """Genera shows (agenda) o releases (música nueva), semanal o mensual."""
    if periodo not in ("semanal", "mensual") or modo not in ("shows", "releases"):
        raise HTTPException(400, "modo/periodo inválido")
    bloqueo = _lanzar_sesion("src.generate_agenda", "--modo", modo, "--periodo", periodo)
    if bloqueo:
        return bloqueo
    if modo == "shows":
        return HTMLResponse(f'🗓 Agenda {periodo} (shows futuros) en camino a '
                            '<strong>Telegram</strong>. Al aprobar se publica de inmediato.')
    return HTMLResponse(f'🎵 Música nueva {periodo} (releases recientes) en camino a '
                        '<strong>Telegram</strong>. Al aprobar se publica de inmediato.')


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
    cx = db.connect()
    try:
        db.update(cx, "events", event_id,
                  tipo=tipo if tipo in ("fecha", "flyer", "release") else "flyer",
                  fecha_evento=fecha_evento.strip() or None,
                  lugar=lugar.strip() or None,
                  ciudad=ciudad.strip() or None,
                  status=status if status in ("nuevo", "anunciado", "pasado") else "nuevo")
        evento = db.rows(cx, """
            SELECT e.*, b.nombre AS banda_nombre FROM events e
              JOIN bands b ON b.id = e.band_id WHERE e.id = ?
        """, (event_id,))[0]
    finally:
        cx.close()
    return templates.TemplateResponse(request, "_event_row.html", {"e": evento})


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
