"""Agenda de eventos (semanal/mensual): digest de la tabla events → tarjeta → IG.

Junta los eventos con fecha futura dentro de la ventana (7 o 30 días a partir
de HOY — los flyers de shows pasados nunca entran), arma la tarjeta con la
plantilla propia `templates/agenda.html` (todos los eventos con fecha y lugar)
y la manda a aprobar por Telegram. Al aprobar se publica DE INMEDIATO (igual
que los anuncios: una agenda caduca).

La curación es la de siempre: los eventos salen del OCR+LLM pero se corrigen
a mano en la GUI (/eventos) antes de generar. La agenda lista TODO lo vigente,
esté o no anunciado individualmente.

Uso:
    python -m src.generate_agenda                # semanal (7 días)
    python -m src.generate_agenda --periodo mensual
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
import unicodedata
from datetime import datetime, timedelta
from typing import Any

import pytz

import config
from src import approval, covers, db, host, sheets, telegram_bot
from src import compose as compose_mod
from src.generate_anuncios import _MESES


def _norm_venue(s: str | None) -> str:
    """Normaliza un lugar para comparar: sin acentos, minúsculas, solo alfanum."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def agrupar_por_evento(eventos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fusiona eventos con MISMA fecha + MISMO foro en uno solo con TODAS las bandas.

    Dos bandas que tocan en el mismo evento (o la misma banda con el flyer repetido)
    aparecen una sola vez, listando los participantes. Sin lugar no se fusiona
    (no hay forma de saber que es el mismo evento).
    """
    grupos: dict[tuple, dict] = {}
    orden: list[tuple] = []
    for e in eventos:
        fecha = (e.get("fecha_evento") or "")[:10]
        venue = _norm_venue(e.get("lugar"))
        clave = (fecha, venue) if venue else (fecha, f"__solo{e['id']}")
        g = grupos.get(clave)
        if g is None:
            g = {**e, "bandas": [], "handles": [], "ids": []}
            grupos[clave] = g
            orden.append(clave)
        g["ids"].append(e["id"])
        if e["banda_nombre"] not in g["bandas"]:
            g["bandas"].append(e["banda_nombre"])
            if e.get("banda_handle"):
                g["handles"].append(e["banda_handle"])
        if not g.get("lugar") and e.get("lugar"):
            g["lugar"] = e["lugar"]
    out = []
    for clave in orden:
        g = grupos[clave]
        g["banda_nombre"] = " · ".join(g["bandas"])  # todas las bandas del evento
        out.append(g)
    return out

_PERIODOS = {"semanal": 7, "mensual": 30}
_MES_ABREV = ["ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]
_MAX_EN_TARJETA = 10  # más que esto no se lee; el resto va en "+N más"

_PERIODOS = {"semanal": 7, "mensual": 30}
_MES_ABREV = ["ene", "feb", "mar", "abr", "may", "jun",
              "jul", "ago", "sep", "oct", "nov", "dic"]
_MAX_EN_TARJETA = 10  # más que esto no se lee; el resto va en "+N más"


def eventos_ventana(cx, dias: int, *, hoy: datetime | None = None) -> list[dict[str, Any]]:
    """SHOWS (fecha/flyer) de HOY a HOY+dias, nunca pasados ni releases."""
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    desde = hoy.strftime("%Y-%m-%d")
    hasta = (hoy + timedelta(days=dias)).strftime("%Y-%m-%d")
    return db.rows(cx, """
        SELECT e.*, b.nombre AS banda_nombre, b.ig_handle AS banda_handle
          FROM events e JOIN bands b ON b.id = e.band_id
         WHERE e.tipo != 'release'
           AND e.fecha_evento >= ? AND e.fecha_evento <= ?
           AND e.status != 'pasado' AND e.irrelevante = 0
         ORDER BY e.al_final, e.fecha_evento, b.nombre
    """, (desde, hasta))


def releases_proximos(cx, dias: int = 60, *, hoy: datetime | None = None) -> list[dict[str, Any]]:
    """RELEASES con fecha FUTURA (de HOY a HOY+dias): anuncios de "ya viene"."""
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    desde = hoy.strftime("%Y-%m-%d")
    hasta = (hoy + timedelta(days=dias)).strftime("%Y-%m-%d")
    return db.rows(cx, """
        SELECT e.*, b.nombre AS banda_nombre, b.ig_handle AS banda_handle
          FROM events e JOIN bands b ON b.id = e.band_id
         WHERE e.tipo = 'release'
           AND e.fecha_evento > ? AND e.fecha_evento <= ?
           AND e.irrelevante = 0
         ORDER BY e.fecha_evento, b.nombre
    """, (desde, hasta))


def releases_ventana(cx, dias: int, *, hoy: datetime | None = None,
                     solo_frescos: bool = False) -> list[dict[str, Any]]:
    """RELEASES que salieron en los últimos `dias` (de HOY-dias a HOY).

    solo_frescos=True excluye los ya 'anunciado' (criterio de frescura del
    semanal: nunca repite lo que ya salió en un carrusel aprobado).
    """
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    desde = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
    hasta = hoy.strftime("%Y-%m-%d")
    fresco = "AND e.status != 'anunciado'" if solo_frescos else ""
    return db.rows(cx, f"""
        SELECT e.*, b.nombre AS banda_nombre, b.ig_handle AS banda_handle
          FROM events e JOIN bands b ON b.id = e.band_id
         WHERE e.tipo = 'release'
           AND e.fecha_evento >= ? AND e.fecha_evento <= ?
           AND e.irrelevante = 0
           {fresco}
         ORDER BY e.fecha_evento DESC, b.nombre
    """, (desde, hasta))


def _fila_tarjeta(ev: dict[str, Any], modo: str) -> dict[str, str]:
    """Fila para la tarjeta: shows → venue; releases → título + portada del álbum."""
    d = datetime.fromisoformat(ev["fecha_evento"][:10])
    if modo == "releases":
        sub = ev.get("titulo") or ""
        cover = ev.get("cover_url") or ""
    else:
        cover = ""
        sub = ev.get("lugar") or ""
        if ev.get("ciudad") and ev.get("ciudad") not in sub:
            sub = f"{sub} · {ev['ciudad']}" if sub else ev["ciudad"]
    return {"dia": str(d.day), "mes": _MES_ABREV[d.month - 1],
            "banda": ev["banda_nombre"], "lugar": sub, "cover": cover}


def _rango_shows(hoy: datetime, dias: int) -> str:
    fin = hoy + timedelta(days=dias)
    if hoy.month == fin.month:
        return f"{hoy.day} al {fin.day} de {_MESES[hoy.month - 1]}"
    return (f"{hoy.day} de {_MESES[hoy.month - 1]} al "
            f"{fin.day} de {_MESES[fin.month - 1]}")


def _rango_releases(hoy: datetime, dias: int) -> str:
    ini = hoy - timedelta(days=dias)
    if hoy.month == ini.month:
        return f"{ini.day} al {hoy.day} de {_MESES[hoy.month - 1]}"
    return (f"{ini.day} de {_MESES[ini.month - 1]} al "
            f"{hoy.day} de {_MESES[hoy.month - 1]}")


# Config visual/textual por modo.
_MODO = {
    "shows": {
        "titulo_card": "La Agenda",
        "kicker": {"semanal": "la escena, esta semana", "mensual": "la escena, este mes"},
        "caption_head": {"semanal": "La agenda de la semana:", "mensual": "La agenda del mes:"},
        "rango": _rango_shows, "ventana": eventos_ventana, "extra_txt": "fechas más en camino",
    },
    "releases": {
        "titulo_card": "Música Nueva",
        "kicker": {"semanal": "lo que salió esta semana", "mensual": "lo que salió este mes"},
        "caption_head": {"semanal": "Lo nuevo de la semana:", "mensual": "Lo nuevo del mes:"},
        "rango": _rango_releases, "ventana": releases_ventana, "extra_txt": "lanzamientos más",
    },
}


def _chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)] or [[]]


def _phash(path) -> "Any | None":
    """Hash perceptual (dHash 8x8) para detectar flyers visualmente iguales."""
    import cv2
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    img = cv2.resize(img, (9, 8))
    return (img[:, 1:] > img[:, :-1]).flatten()


def _es_duplicado(h, vistos, umbral: int = 8) -> bool:
    import numpy as np
    return any(int(np.count_nonzero(h != v)) <= umbral for v in vistos)


_IG_CAROUSEL_MAX = 10  # IG topa el carrusel en 10 (portada + 9 flyers)

_MAX_RELEASES_SLIDE = 4      # grid 2×2: más de 4 no se lee
_MAX_MINIS_PORTADA = 6       # pila de portadas en la cover

_BADGES = {"sencillo": "Sencillo", "álbum": "Álbum", "live session": "Live session"}


def _parse_titulo(titulo: str | None) -> tuple[str, str]:
    """Separa "Obra (sencillo)" → ("Obra", "Sencillo"); sin sufijo → "Estreno"."""
    if not titulo:
        return "", "Estreno"
    t = titulo.strip()
    for sufijo, badge in _BADGES.items():
        marca = f"({sufijo})"
        if t.lower().endswith(marca):
            return t[: -len(marca)].strip(), badge
    return t, "Estreno"


def _caption_releases(eventos: list[dict[str, Any]], periodo: str, *, omitidos: int = 0) -> str:
    """Caption del carrusel: línea por release + bloque de tags únicos al final."""
    lineas = [_MODO["releases"]["caption_head"][periodo]]
    handles: list[str] = []
    for ev in eventos:
        d = datetime.fromisoformat(ev["fecha_evento"][:10])
        obra, _ = _parse_titulo(ev.get("titulo"))
        linea = f"• {d.day} {_MES_ABREV[d.month - 1]} — {ev['banda_nombre']}"
        if obra:
            linea += f": {obra}"
        lineas.append(linea)
        h = ev.get("banda_handle")
        if h and h not in handles:
            handles.append(h)
    if omitidos:
        lineas.append(f"…y +{omitidos} lanzamientos más.")
    lineas += ["", "🔖 Guarda el post y comparte tu favorita."]
    if handles:  # etiqueta a todas las bandas del carrusel
        lineas += ["", " ".join(f"@{h}" for h in handles)]
    return "\n".join(lineas)


def build_releases_carousel(periodo: str, *, hoy: datetime | None = None,
                            solo_frescos: bool = False) -> tuple[str, list[str], list[int]]:
    """Carrusel de música nueva: PORTADA (collage+lineup) + grids 2×2 + CTA.

    Las portadas se bajan a data/covers/ (covers.asegurar_cover) y se renderizan
    como file:// — inmunes al filtro DNS que bloquea i.scdn.co. Abre su propia
    conexión SQLite (se llama desde un hilo aparte).

    Devuelve (caption, pngs, evento_ids); evento_ids son los events.id de los
    releases realmente incluidos (la rebanada `visibles`), para marcarlos
    'anunciado' al aprobar.
    """
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    dias = _PERIODOS[periodo]
    cx = db.connect()
    try:
        releases = releases_ventana(cx, dias, hoy=hoy, solo_frescos=solo_frescos)
    finally:
        cx.close()
    if not releases:
        return "", [], []

    kicker = _MODO["releases"]["kicker"][periodo]
    rango = _rango_releases(hoy, dias)

    # Slides: 4 por grid; el carrusel topa en 10 (portada + 8 grids + CTA).
    visibles = releases[: _MAX_RELEASES_SLIDE * (_IG_CAROUSEL_MAX - 2)]
    omitidos = len(releases) - len(visibles)

    # Portadas locales una sola vez (sirven para portada y grids).
    locales: dict[int, str | None] = {}
    for ev in visibles:
        p = covers.asegurar_cover(ev.get("cover_url"))
        locales[ev["id"]] = compose_mod._to_src(str(p)) if p else None

    minis = [{"src": locales[e["id"]], "inicial": (e["banda_nombre"] or "?")[0].upper()}
             for e in visibles[:_MAX_MINIS_PORTADA]]
    lineup: list[str] = []
    for e in visibles:
        if e["banda_nombre"] not in lineup:
            lineup.append(e["banda_nombre"])
    cover = compose_mod.render_card("release_cover.html", {
        "kicker": kicker, "rango": rango, "minis": minis, "lineup": lineup,
    }, prefix="rel_cover")
    pngs = [str(cover)]

    slides = _chunks(visibles, _MAX_RELEASES_SLIDE)
    for i, slide in enumerate(slides, start=1):
        filas = []
        for ev in slide:
            obra, badge = _parse_titulo(ev.get("titulo"))
            d = datetime.fromisoformat(ev["fecha_evento"][:10])
            filas.append({
                "cover_src": locales[ev["id"]],
                "inicial": (ev["banda_nombre"] or "?")[0].upper(),
                "banda": ev["banda_nombre"], "obra": obra, "badge": badge,
                "fecha": f"{d.day} {_MES_ABREV[d.month - 1]}",
            })
        png = compose_mod.render_card("release_grid.html", {
            "kicker": kicker, "releases": filas, "pagina": i, "paginas": len(slides),
        }, prefix=f"rel_grid_s{i}")
        pngs.append(str(png))

    cta = compose_mod.render_card("release_cta.html", {"kicker": kicker}, prefix="rel_cta")
    pngs.append(str(cta))

    evento_ids = [ev["id"] for ev in visibles]
    return _caption_releases(visibles, periodo, omitidos=omitidos), pngs, evento_ids


def _unicos_flyers(eventos: list[dict[str, Any]]) -> tuple[list[tuple[dict, "Any"]], int]:
    """Dedup visual de flyers: devuelve [(evento, ruta_abs)] únicos + nº omitidos.

    Solo entran eventos con flyer_path existente; descarta los visualmente
    iguales (dos artistas subiendo el mismo cartel) vía _phash.
    """
    from pathlib import Path
    unicos, vistos = [], []
    for e in eventos:
        if not e.get("flyer_path"):
            continue
        p = Path(e["flyer_path"])
        p = p if p.is_absolute() else (config.BASE_DIR / p)
        if not p.exists():
            continue
        h = _phash(p)
        if h is None or _es_duplicado(h, vistos):
            continue
        vistos.append(h)
        unicos.append((e, p))
    omitidos = max(0, len([e for e in eventos if e.get("flyer_path")]) - len(unicos))
    return unicos, omitidos


def _caption_agenda(unicos: list[tuple[dict, "Any"]], periodo: str, rango: str,
                    *, sufijo: str = "") -> str:
    """Caption de una agenda: encabezado + línea por evento (fusionado) + @tags.

    sufijo se añade al encabezado (p. ej. " (Parte 1/2)") cuando hay partes.
    """
    grupos = agrupar_por_evento([e for e, _ in unicos])
    lema = "semana" if periodo == "semanal" else "mes"
    lineas = [f"La agenda de la {lema} ({rango}){sufijo}:"]
    handles: list[str] = []
    for g in grupos:
        d = datetime.fromisoformat(g["fecha_evento"][:10])
        linea = f"• {d.day} {_MES_ABREV[d.month - 1]} — {g['banda_nombre']}"
        if g.get("lugar"):
            linea += f" en {g['lugar']}"
        lineas.append(linea)
        for h in g.get("handles", []):
            if h and h not in handles:
                handles.append(h)
    lineas += ["", "↗ Comparte y comenta a quién vas a ver."]
    if handles:  # etiqueta a todos los artistas de los flyers
        lineas += ["", " ".join(f"@{h}" for h in handles)]
    return "\n".join(lineas)


def build_agenda_carousel(periodo: str, *, hoy: datetime | None = None) -> tuple[str, list[str]]:
    """Carrusel de la agenda: PORTADA + las fotos de los flyers con fecha en el rango.

    Omite flyers visualmente duplicados (dos artistas subiendo el mismo cartel).
    Devuelve (caption_ig, [rutas_png]); pngs[0] es la portada. Abre su propia
    conexión SQLite (lo llama un hilo aparte; las conexiones no cruzan hilos).
    """
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    dias = _PERIODOS[periodo]
    cx = db.connect()
    try:
        eventos = eventos_ventana(cx, dias, hoy=hoy)
    finally:
        cx.close()

    unicos, omitidos = _unicos_flyers(eventos)
    kicker = "la escena, esta semana" if periodo == "semanal" else "la escena, este mes"
    # Reservamos lugar para la PORTADA y el CTA final (carrusel IG topa en 10).
    flyers = unicos[:_IG_CAROUSEL_MAX - 2]

    rango = _rango_shows(hoy, dias)
    cover = compose_mod.render_card("agenda_cover.html",
                                    {"kicker": kicker, "rango": rango}, prefix="agenda_cover")
    pngs = [str(cover)]
    for i, (e, p) in enumerate(flyers, start=1):
        png = compose_mod.render_card("agenda_flyer.html", {
            "flyer_url": compose_mod._to_src(str(p)), "pagina": i, "paginas": len(flyers),
        }, prefix="agenda_flyer")
        pngs.append(str(png))
    # Última página: CTA de comparte/comenta.
    cta = compose_mod.render_card("agenda_cta.html", {"kicker": kicker}, prefix="agenda_cta")
    pngs.append(str(cta))

    # Caption: eventos (fusionando misma fecha+foro) + ETIQUETAS de cada @handle.
    caption = _caption_agenda(unicos, periodo, rango)
    if omitidos:
        print(f"   (se omitieron {omitidos} flyer(s) duplicados)")
    return caption, pngs


def build_agenda_partes(periodo: str, *, hoy: datetime | None = None) -> list[dict[str, Any]]:
    """Parte la agenda en bloques de ≤8 flyers → cada parte cabe en un carrusel.

    A diferencia de build_agenda_carousel (que recorta a 8 y descarta el resto),
    aquí TODOS los flyers únicos se reparten en partes. Cada parte = portada
    (con "Parte k/N" si hay más de una) + ≤8 flyers + CTA (≤10 slides, el tope
    de IG). Devuelve una lista de dicts {caption, pngs, evento_ids, parte, partes};
    [] si no hay flyers con imagen y fecha en la ventana.
    """
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    dias = _PERIODOS[periodo]
    cx = db.connect()
    try:
        eventos = eventos_ventana(cx, dias, hoy=hoy)
    finally:
        cx.close()

    unicos, omitidos = _unicos_flyers(eventos)
    if not unicos:
        return []
    if omitidos:
        print(f"   (se omitieron {omitidos} flyer(s) duplicados)")

    kicker = "la escena, esta semana" if periodo == "semanal" else "la escena, este mes"
    rango = _rango_shows(hoy, dias)
    bloques = _chunks(unicos, _IG_CAROUSEL_MAX - 2)  # 8 flyers por parte
    partes_n = len(bloques)

    salida: list[dict[str, Any]] = []
    for k, bloque in enumerate(bloques, start=1):
        ctx = {"kicker": kicker, "rango": rango, "parte": k, "partes": partes_n}
        cover = compose_mod.render_card("agenda_cover.html", ctx, prefix="agenda_cover")
        pngs = [str(cover)]
        for i, (e, p) in enumerate(bloque, start=1):
            png = compose_mod.render_card("agenda_flyer.html", {
                "flyer_url": compose_mod._to_src(str(p)),
                "pagina": i, "paginas": len(bloque),
            }, prefix="agenda_flyer")
            pngs.append(str(png))
        cta = compose_mod.render_card("agenda_cta.html", {"kicker": kicker}, prefix="agenda_cta")
        pngs.append(str(cta))

        sufijo = f" (Parte {k}/{partes_n})" if partes_n > 1 else ""
        caption = _caption_agenda(bloque, periodo, rango, sufijo=sufijo)
        salida.append({
            "caption": caption, "pngs": pngs,
            "evento_ids": [e["id"] for e, _ in bloque],
            "parte": k, "partes": partes_n,
        })
    return salida


def build_card(eventos: list[dict[str, Any]], periodo: str, modo: str = "shows",
               *, hoy: datetime | None = None, out_path=None) -> tuple[str, list[str]]:
    """Compone la(s) tarjeta(s). Si no caben todos, parte en SLIDES (carrusel).

    Devuelve (caption_ig, [rutas_png]). Una lista de 1 png = post normal; más de
    1 = carrusel que cubre todo el periodo.
    """
    hoy = hoy or datetime.now(pytz.timezone(config.TIMEZONE))
    cfg = _MODO[modo]
    dias = _PERIODOS[periodo]
    # Shows: fusiona misma-fecha+mismo-foro en un evento con todas las bandas.
    if modo == "shows":
        eventos = agrupar_por_evento(eventos)
    slides = _chunks(eventos, _MAX_EN_TARJETA)
    paginas = len(slides)

    pngs = []
    for i, slide in enumerate(slides, start=1):
        # out_path solo aplica a 1 slide (pruebas); en carrusel se autogenera.
        op = out_path if (paginas == 1 and out_path) else None
        png = compose_mod.render_card("agenda.html", {
            "titulo_card": cfg["titulo_card"],
            "kicker": cfg["kicker"][periodo],
            "rango": cfg["rango"](hoy, dias),
            "eventos": [_fila_tarjeta(e, modo) for e in slide],
            "extra": "",
            "handle": "@gdlscene",
            "pagina": i, "paginas": paginas,
        }, out_path=op, prefix=f"{modo}_{periodo}_s{i}")
        pngs.append(str(png))

    lineas = [cfg["caption_head"][periodo]]
    for ev in eventos:
        d = datetime.fromisoformat(ev["fecha_evento"][:10])
        linea = f"• {d.day} {_MES_ABREV[d.month - 1]} — {ev['banda_nombre']}"
        sub = ev.get("titulo") if modo == "releases" else ev.get("lugar")
        if sub:
            linea += (f": {sub}" if modo == "releases" else f" en {sub}")
        if ev.get("banda_handle"):
            linea += f" (@{ev['banda_handle']})"
        lineas.append(linea)
    return "\n".join(lineas), pngs


def generar_segmento_agenda(cx, account_id: int, *, periodo: str, modo: str) -> None:
    """Generador NO-BLOQUEANTE para el motor de segmentos (dispatcher).

    Arma el carrusel (reusa build_agenda_carousel/build_releases_carousel según
    modo), sube los PNG al host (mismo patrón que main(): URL simple o JSON-list
    si es carrusel) y en vez de bloquear con request_carousel_approval ENCOLA la
    propuesta (approval.encolar_pendiente) y la manda a Telegram con botones
    (approval.enviar_a_telegram). El daemon de aprobación resuelve después.

    Firma con periodo/modo keyword-only para que
    functools.partial(generar_segmento_agenda, periodo=, modo=) deje (cx,
    account_id) posicionales y cumpla el contrato Callable[[Any, int], None] de
    Segment. NO toca main() (vía manual).
    """
    import json

    if modo == "shows":
        # Parte la agenda en bloques de ≤8 flyers; cada parte = un carrusel independiente.
        partes = build_agenda_partes(periodo)
        if not partes:
            print(f"⚠️ {modo} {periodo}: sin flyers con imagen y fecha en la ventana; no se encola.")
            return
        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
        for parte in partes:
            urls = [host.upload(p, public_id=f"shows_{periodo}_{ahora:%Y%m%d}_pt{parte['parte']}_{i}")
                    for i, p in enumerate(parte["pngs"])]
            imagen = urls[0] if len(urls) == 1 else json.dumps(urls)
            qid = approval.encolar_pendiente(
                cx, tipo="anuncio", caption=parte["caption"], imagen_url=imagen,
                tema_semilla=f"shows {periodo} pt{parte['parte']}",
                evento_ids=json.dumps(parte["evento_ids"]),
                account_id=account_id)
            approval.enviar_a_telegram(parte["caption"], imagen, qid)
            print(f"✅ shows {periodo} parte {parte['parte']}/{parte['partes']}: "
                  f"encolada (queue_id={qid}) y enviada a Telegram.")
        return
    else:
        # Frescura: el semanal solo incluye lo NO anunciado; el mensual es recap.
        solo_frescos = (periodo == "semanal")
        caption, pngs, evento_ids = build_releases_carousel(periodo, solo_frescos=solo_frescos)
        min_req = (config.SEGMENT_MIN_RELEASES_SEMANAL if periodo == "semanal"
                   else config.SEGMENT_MIN_RELEASES_MENSUAL)
        if len(evento_ids) < min_req:
            print(f"⏭ {modo} {periodo}: solo {len(evento_ids)} release(s) "
                  f"fresco(s) (< {min_req}); no se genera.")
            return

    ahora = datetime.now(pytz.timezone(config.TIMEZONE))
    urls = [host.upload(p, public_id=f"{modo}_{periodo}_{ahora:%Y%m%d}_{i}")
            for i, p in enumerate(pngs)]
    # 1 imagen → URL simple; carrusel → JSON list (publish.py lo detecta).
    imagen = urls[0] if len(urls) == 1 else json.dumps(urls)

    queue_id = approval.encolar_pendiente(
        cx, tipo="anuncio", caption=caption, imagen_url=imagen,
        tema_semilla=f"{modo} {periodo}", account_id=account_id,
        evento_ids=json.dumps(evento_ids) if evento_ids else None)
    approval.enviar_a_telegram(caption, imagen, queue_id)
    print(f"✅ {modo} {periodo}: encolado (queue_id={queue_id}) y enviado a Telegram para aprobación.")


async def main(periodo: str, modo: str = "shows") -> None:
    import json
    cx = db.connect()
    try:
        db.init_db(cx)
        eventos = _MODO[modo]["ventana"](cx, _PERIODOS[periodo])
        if not eventos:
            que = "shows con fecha futura" if modo == "shows" else "releases recientes"
            print(f"No hay {que} en la ventana {periodo}. Cura/escrapea más, o corre el pipeline.")
            return
        if modo == "shows":
            # Agenda = PORTADA + carrusel de las fotos de los flyers (dedup visual).
            caption, pngs = await asyncio.to_thread(build_agenda_carousel, periodo)
            if len(pngs) < 2:
                print("No hay flyers CON IMAGEN y fecha en la ventana. Marca flyers y ponles fecha.")
                return
        else:
            # Música nueva = carrusel: portada (collage+lineup) + grids 2×2 + CTA.
            # main() = flujo manual: incluye todo (no solo-frescos) y marca
            # 'anunciado' con su lógica existente (_marcar_anunciados, abajo).
            caption, pngs, _ids = await asyncio.to_thread(build_releases_carousel, periodo)
            if not pngs:
                print("No hay releases en la ventana.")
                return
        print(f"{modo} {periodo}: {len(pngs)} slide(s) (portada + flyers)…")

        aprobado = await telegram_bot.request_carousel_approval(caption, pngs)
        if not aprobado:
            print(f"❌ {modo} {periodo} rechazado — corrige en la GUI y vuelve a correr")
            return

        ahora = datetime.now(pytz.timezone(config.TIMEZONE))
        urls = [host.upload(p, public_id=f"{modo}_{periodo}_{ahora:%Y%m%d}_{i}")
                for i, p in enumerate(pngs)]
        # 1 imagen → URL simple; carrusel → JSON list (publish.py lo detecta).
        imagen = urls[0] if len(urls) == 1 else json.dumps(urls)
        sheet_id = sheets.append_row(
            fecha_captura=ahora.strftime("%Y-%m-%d"),
            banda="@gdlscene",
            tema_semilla=f"{modo} {periodo}",
            caption_generado=caption,
            caption_final=caption,
            imagen_compuesta_url=imagen,
            status=sheets.STATUS_APPROVED,
            scheduled_datetime=ahora.isoformat(),  # inmediata: caduca
        )
        db.insert(cx, "content_queue", tipo="anuncio",
                  tema_semilla=f"{modo} {periodo}", status=db.QUEUE_EN_SHEET,
                  sheet_row_id=str(sheet_id))
        if modo == "releases":
            # Lo que entró al carrusel queda 'anunciado': la GUI colapsa la
            # sección y evita re-publicar lo mismo por accidente.
            tope = _MAX_RELEASES_SLIDE * (_IG_CAROUSEL_MAX - 2)
            _marcar_anunciados(cx, eventos[:tope])
        carr = f" (carrusel de {len(urls)})" if len(urls) > 1 else ""
        print(f"✅ {modo} {periodo}{carr} → Sheet id={sheet_id}")
        # Regla editorial: agendas y música nueva caducan → publicar AL MOMENTO
        # corriendo el worker local (el de GitHub es solo respaldo horario).
        publicado = await asyncio.to_thread(_publicar_ahora)
        if publicado:
            print("🚀 publicado en IG ahora mismo.")
        else:
            print("⚠️ no se pudo publicar al momento; el worker horario lo reintenta (≤1h).")
    finally:
        cx.close()


def _marcar_anunciados(cx, eventos: list[dict[str, Any]]) -> int:
    """Marca como 'anunciado' los releases cubiertos por un carrusel aprobado."""
    n = 0
    for ev in eventos:
        if ev.get("status") != "anunciado":
            db.update(cx, "events", ev["id"], status="anunciado")
            n += 1
    return n


def _publicar_ahora() -> bool:
    """Corre publish.py local (publica TODO lo vencido, incluida la fila recién

    aprobada). Local porque el worker de GitHub corre el código PUSHEADO, que
    puede ir atrás del local (ej. soporte de carrusel). True si terminó bien.
    """
    import subprocess
    try:
        proc = subprocess.run([sys.executable, str(config.BASE_DIR / "publish.py")],
                              capture_output=True, text=True, timeout=600,
                              cwd=str(config.BASE_DIR))
        print(proc.stdout.strip())
        if proc.returncode != 0:
            print(proc.stderr.strip()[-400:], file=sys.stderr)
        # "Publicado" de verdad solo si el worker reportó al menos un ✅.
        return proc.returncode == 0 and "✅" in proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"⚠️ publish.py local falló: {exc}", file=sys.stderr)
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agenda/Música nueva semanal o mensual")
    parser.add_argument("--periodo", choices=list(_PERIODOS), default="semanal")
    parser.add_argument("--modo", choices=list(_MODO), default="shows")
    parser.add_argument("--segmento", action="store_true",
                        help="modo motor: encola y manda a Telegram (no bloquea, sin poller)")
    args = parser.parse_args()
    if args.segmento:
        # Camino no-bloqueante: encola + envía a Telegram; el daemon de aprobación resuelve.
        cx = db.connect()
        db.init_db(cx)
        try:
            generar_segmento_agenda(cx, 1, periodo=args.periodo, modo=args.modo)
        finally:
            cx.close()
    else:
        try:
            asyncio.run(main(args.periodo, args.modo))
        except KeyboardInterrupt:
            sys.exit("\nSesión interrumpida.")
