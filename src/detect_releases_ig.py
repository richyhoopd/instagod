"""Detección de releases en captions nuevos de IG (Frente B, modo novedades).

Por cada post nuevo de una banda existente, DeepSeek (temp=0, json_object) decide
si el caption ANUNCIA música nueva propia (sencillo/álbum/EP "ya disponible",
"fuera ahora", link de preventa/estreno). Si sí, se crea un evento tipo
'release' con la portada = foto local del post (las tarjetas renderizan file://).

Spotify gana: si la banda ya tiene un release con título similar y fecha a
±30 días (típicamente metido por el cron de Spotify, con mejor portada), no se
duplica. Tampoco se reinserta el mismo post dos veces (dedupe por source_post_id).

Lo llama el orquestador `src/novedades.py` con los posts que produjo el modo
novedades de la ingesta; aquí solo se define el contrato `detectar(cx, posts)`.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any

import config

# Tolerancia de fecha para considerar dos releases "el mismo" (Spotify gana).
_VENTANA_DIAS = 30
# Sufijos de tipo que el match de título ignora ("Noche (álbum)" == "Noche").
_SUFIJO_TIPO = re.compile(r"\s*\((?:sencillo|álbum|album|ep)\)\s*$", re.IGNORECASE)

SYSTEM_PROMPT = """\
Lees el caption de un post de Instagram de una banda y decides si anuncia un \
LANZAMIENTO de música propia o un EVENTO en vivo. Respondes ÚNICAMENTE un objeto \
JSON, sin explicación, con:
- "es_release": true SOLO si anuncia música nueva propia ya publicada o que se \
estrena (sencillo/álbum/EP "ya disponible", "fuera ahora", "en todas las \
plataformas", preventa/estreno). false si no.
- "es_show": true SOLO si anuncia un EVENTO EN VIVO con FECHA (tocada, concierto, \
fiesta, presentación, estreno presencial) — algo a lo que la gente va. false si no.
- "titulo": nombre del release (si es_release) o del evento (si es_show), o null.
- "tipo": "sencillo", "album" o null (solo para release).
- "fecha": fecha en formato YYYY-MM-DD del lanzamiento o del evento si el caption \
la da, o null (se usará la del post). Usa la fecha del post para resolver años.
- "lugar": venue/foro del evento si aparece, o null (solo para show).
- "ciudad": ciudad del evento si aparece, o null (solo para show).

Un post puede ser ambos (un estreno presencial es release + show); marca los dos. \
NO marques nada para: covers o música de OTROS, "muy pronto"/teasers sin fecha, \
agradecimientos, fotos sin anuncio. Ante la duda, ambos false."""


def _extraer_json(texto: str) -> dict[str, Any] | None:
    """Primer objeto JSON dentro de la respuesta del LLM (tolera ```json ...```)."""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def _llm_release(caption: str, fecha_post: str | None) -> dict[str, Any] | None:
    """Pregunta a DeepSeek si el caption anuncia un release. Cliente perezoso."""
    from openai import OpenAI

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en el .env")
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    prompt = f"CAPTION DEL POST:\n{caption[:1200]}"
    if fecha_post:
        prompt += f"\n\nFECHA DEL POST: {fecha_post[:10]}"
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0,  # decisión binaria + extracción: nada de creatividad
        max_tokens=200,
    )
    return _extraer_json(resp.choices[0].message.content or "")


def _normaliza_titulo(titulo: str | None) -> str:
    """Título comparable: casefold + sin sufijo (sencillo)/(álbum)/(EP)."""
    if not titulo:
        return ""
    return _SUFIJO_TIPO.sub("", titulo).strip().casefold()


def _parse_fecha(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return datetime.strptime(str(valor)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _titulos_similares(a: str, b: str) -> bool:
    """Match exacto o contención en cualquier dirección (ya normalizados)."""
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _es_dupe(cx, band_id: int, source_post_id: str, titulo: str,
             fecha_evento: str | None) -> bool:
    """True si ya hay un release equivalente (mismo post, o título+fecha cercanos)."""
    existentes = db_rows_releases(cx, band_id)
    for ev in existentes:
        if ev["source_post_id"] == source_post_id:
            return True  # mismo post ya registrado
    norm_nuevo = _normaliza_titulo(titulo)
    f_nuevo = _parse_fecha(fecha_evento)
    for ev in existentes:
        if not _titulos_similares(norm_nuevo, _normaliza_titulo(ev.get("titulo"))):
            continue
        f_viejo = _parse_fecha(ev.get("fecha_evento"))
        # Sin fechas comparables no podemos descartar: el título similar manda.
        if f_nuevo is None or f_viejo is None:
            return True
        if abs((f_nuevo - f_viejo).days) <= _VENTANA_DIAS:
            return True  # Spotify (u otro) ya lo tiene; su portada es mejor
    return False


def db_rows_releases(cx, band_id: int) -> list[dict[str, Any]]:
    """Releases existentes de la banda (para el dedupe)."""
    from src import db

    return db.rows(cx, """
        SELECT id, titulo, fecha_evento, source_post_id
          FROM events WHERE band_id = ? AND tipo = 'release'
    """, (band_id,))


def detectar(cx, posts: list[dict[str, Any]]) -> dict[str, int]:
    """Detecta releases en captions nuevos y los inserta como events tipo 'release'.

    `posts`: [{band_id, shortcode, caption, path, fecha}, ...] (del modo novedades).
    Devuelve {revisados, releases_nuevos, saltados_dedupe, fallidos}.
    """
    from src import db

    resumen = {"revisados": 0, "releases_nuevos": 0, "saltados_dedupe": 0,
               "fallidos": 0, "nuevos": []}
    for post in posts:
        resumen["revisados"] += 1
        caption = (post.get("caption") or "").strip()
        shortcode = post.get("shortcode")
        if not caption:
            continue  # nada que analizar: ni LLM

        try:
            data = _llm_release(caption, post.get("fecha"))
        except Exception as exc:  # noqa: BLE001 — LLM caído no debe tumbar la corrida
            print(f"⚠ {shortcode}: LLM falló ({exc}); se salta")
            resumen["fallidos"] += 1
            continue
        if data is None:
            print(f"⚠ {shortcode}: el LLM no devolvió JSON válido; se salta")
            resumen["fallidos"] += 1
            continue
        es_r = bool(data.get("es_release"))
        es_s = bool(data.get("es_show"))

        # SHOW (evento en vivo → agenda de shows). Puede coexistir con el release
        # (un estreno presencial es ambos): si también es release usa una llave
        # aparte (#show) para tener una fila en CADA calendario. Show-solo usa la
        # llave del post (y si la imagen ya hizo flyer, lo deja a parse_events).
        if es_s:
            if _registrar_show(cx, post, data, sufijo="#show" if es_r else ""):
                resumen["releases_nuevos"] += 1
                resumen["nuevos"].append({
                    "banda": _nombre_banda(cx, post["band_id"]),
                    "titulo": data.get("titulo") or "(show)",
                    "fecha": (str(data.get("fecha"))[:10] if data.get("fecha")
                              else post.get("fecha"))})

        if not es_r:
            continue

        titulo = data.get("titulo")
        if not titulo:
            print(f"⚠ {shortcode}: es_release sin título; no se inserta")
            continue

        fecha_evento = str(data["fecha"])[:10] if data.get("fecha") else post.get("fecha")
        if fecha_evento:
            fecha_evento = fecha_evento[:10]
        # Llave unificada: el shortcode bare (mismo que usa classify para el flyer).
        source_post_id = shortcode

        # ¿Ya hay un evento de ESTE post (flyer que creó classify, o release de una
        # corrida previa, o el viejo 'ig:')? Entonces se ACTUALIZA en sitio, no se
        # inserta otra fila → un post = un evento.
        existente = cx.execute(
            "SELECT id, tipo FROM events WHERE band_id=? AND source_post_id IN (?, ?)",
            (post["band_id"], shortcode, f"ig:{shortcode}")).fetchone()

        # Dedup vs Spotify/Deezer (otra fuente con el mismo título+fecha cercanos).
        if existente is None and _es_dupe(cx, post["band_id"], source_post_id,
                                          str(titulo), fecha_evento):
            print(f"↷ {shortcode}: '{titulo}' ya existe (Spotify gana); se salta")
            resumen["saltados_dedupe"] += 1
            continue

        # cover_url para la tarjeta (file://) y flyer_path para que la GUI sirva
        # la imagen local vía /flyer/{id} (cover_url crudo no es URL servible).
        campos = dict(tipo="release", titulo=str(titulo)[:200], fecha_evento=fecha_evento,
                      cover_url=post.get("path"), flyer_path=post.get("path"),
                      source_post_id=source_post_id, status="nuevo", parseado_por_llm=1)
        if existente:
            db.update(cx, "events", existente["id"], **campos)
        else:
            db.insert(cx, "events", band_id=post["band_id"], **campos)
        resumen["releases_nuevos"] += 1
        resumen["nuevos"].append({"banda": _nombre_banda(cx, post["band_id"]),
                                  "titulo": str(titulo), "fecha": fecha_evento})
        print(f"✓ {shortcode}: release '{titulo}' ({fecha_evento})")

    return resumen


def _registrar_show(cx, post: dict[str, Any], data: dict[str, Any],
                    sufijo: str = "") -> bool:
    """Crea un evento tipo='fecha' (agenda) desde el caption. Devuelve True si insertó.

    La llave es `shortcode+sufijo`: vacío para show-solo (y si ya hay evento del
    post, lo deja a parse_events); '#show' para el show acompañante de un release
    (coexiste con la fila del release en su propio calendario).
    """
    from src import db

    shortcode = post.get("shortcode")
    llave = f"{shortcode}{sufijo}"
    ya = cx.execute(
        "SELECT 1 FROM events WHERE band_id=? AND source_post_id IN (?, ?)",
        (post["band_id"], llave, f"ig:{llave}")).fetchone()
    if ya:
        return False
    fecha = (str(data["fecha"])[:10] if data.get("fecha") else post.get("fecha"))
    db.insert(cx, "events", band_id=post["band_id"], tipo="fecha",
              titulo=(data.get("titulo") or None), fecha_evento=fecha,
              lugar=(data.get("lugar") or None), ciudad=(data.get("ciudad") or None),
              flyer_path=post.get("path"), cover_url=post.get("path"),
              source_post_id=llave, status="nuevo", parseado_por_llm=1)
    print(f"✓ {llave}: show '{data.get('titulo') or '?'}' ({fecha})")
    return True


def backfill_eventos(cx, dias: int = 30, hoy=None) -> dict[str, int]:
    """Re-analiza por caption los posts con fotos pero SIN evento (últimos `dias`).

    Rellena el hueco de posts ya ingeridos cuyo flyer no se detectó por imagen y
    cuyo caption nunca pasó por el detector (corte por post conocido).
    """
    from src import db

    hoy = hoy or datetime.now()
    desde = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
    # Un post (band_id, source_post_id) representado por su foto más informativa,
    # que tenga caption y NO tenga ya un evento de ese post.
    filas = db.rows(cx, """
        SELECT p.band_id, p.source_post_id AS shortcode, p.path,
               MAX(p.caption_original) AS caption, MAX(p.fecha) AS fecha
          FROM photos p
         WHERE p.source_post_id IS NOT NULL AND p.fecha >= ?
           AND p.caption_original IS NOT NULL AND p.caption_original != ''
           AND NOT EXISTS (SELECT 1 FROM events e
                            WHERE e.band_id = p.band_id
                              AND e.source_post_id IN (p.source_post_id,
                                                       'ig:' || p.source_post_id))
         GROUP BY p.band_id, p.source_post_id
    """, (desde,))
    posts = [{"band_id": f["band_id"], "shortcode": f["shortcode"],
              "caption": f["caption"], "path": f["path"], "fecha": f["fecha"]}
             for f in filas]
    print(f"Backfill: {len(posts)} post(s) con fotos y sin evento por revisar…")
    return detectar(cx, posts)


def _nombre_banda(cx, band_id: int) -> str:
    row = cx.execute("SELECT nombre FROM bands WHERE id=?", (band_id,)).fetchone()
    return row["nombre"] if row else "?"


def purgar_releases_dup(cx) -> int:
    """Colapsa releases duplicados del mismo post/fecha (banda, fecha_evento).

    Conserva la fila con título (y, a igualdad, la de source_post_id más
    informativa). Devuelve cuántas filas se borraron. Limpieza única para los
    duplicados creados antes del merge por shortcode.
    """
    from src import db

    grupos: dict[tuple, list[dict]] = {}
    for ev in db.rows(cx, "SELECT * FROM events WHERE tipo='release'"):
        grupos.setdefault((ev["band_id"], ev["fecha_evento"]), []).append(ev)
    borradas = 0
    for filas in grupos.values():
        if len(filas) < 2:
            continue
        # mejor = con título; desempate: source_post_id no nulo más largo
        mejor = sorted(filas, key=lambda e: (bool(e["titulo"]),
                                             len(e["source_post_id"] or "")), reverse=True)[0]
        for e in filas:
            if e["id"] != mejor["id"]:
                cx.execute("DELETE FROM events WHERE id=?", (e["id"],))
                borradas += 1
    cx.commit()
    return borradas
