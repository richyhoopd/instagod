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
from datetime import date, datetime
from typing import Any

import config

# Tolerancia de fecha para considerar dos releases "el mismo" (Spotify gana).
_VENTANA_DIAS = 30
# Sufijos de tipo que el match de título ignora ("Noche (álbum)" == "Noche").
_SUFIJO_TIPO = re.compile(r"\s*\((?:sencillo|álbum|album|ep)\)\s*$", re.IGNORECASE)

SYSTEM_PROMPT = """\
Decides si el caption de un post de Instagram de una banda ANUNCIA un \
lanzamiento de música NUEVA Y PROPIA. Respondes ÚNICAMENTE un objeto JSON, sin \
explicación, con:
- "es_release": true SOLO si el caption anuncia explícitamente música nueva \
propia ya publicada o que se estrena: un sencillo, álbum o EP "ya disponible", \
"fuera ahora", "ya en todas las plataformas", con link de preventa/estreno/escucha. \
false en cualquier otro caso.
- "titulo": el nombre del sencillo/álbum/EP tal como aparece, o null.
- "tipo": "sencillo", "album" o null.
- "fecha": fecha del lanzamiento en formato YYYY-MM-DD si el caption la da, o null \
(se usará la fecha del post). Usa la fecha del post como referencia para resolver años.

NO marques es_release para: anuncios de shows/conciertos/fechas, covers o música \
de OTROS artistas, "muy pronto"/"se viene"/teasers sin fecha de salida, \
agradecimientos, fotos sin anuncio. Ante la duda, es_release=false."""


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

    resumen = {"revisados": 0, "releases_nuevos": 0, "saltados_dedupe": 0, "fallidos": 0}
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
        if not data.get("es_release"):
            continue

        titulo = data.get("titulo")
        if not titulo:
            print(f"⚠ {shortcode}: es_release sin título; no se inserta")
            continue

        fecha_evento = str(data["fecha"])[:10] if data.get("fecha") else post.get("fecha")
        if fecha_evento:
            fecha_evento = fecha_evento[:10]
        source_post_id = f"ig:{shortcode}"

        if _es_dupe(cx, post["band_id"], source_post_id, str(titulo), fecha_evento):
            print(f"↷ {shortcode}: '{titulo}' ya existe (Spotify gana); se salta")
            resumen["saltados_dedupe"] += 1
            continue

        db.insert(cx, "events", band_id=post["band_id"], tipo="release",
                  titulo=str(titulo)[:200], fecha_evento=fecha_evento,
                  cover_url=post.get("path"), source_post_id=source_post_id,
                  status="nuevo", parseado_por_llm=1)
        resumen["releases_nuevos"] += 1
        print(f"✓ {shortcode}: release '{titulo}' ({fecha_evento})")

    return resumen
