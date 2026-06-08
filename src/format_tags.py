"""Atributos de FORMATO por post para el eje formato del cerebro de engagement.

Tres orígenes: derivado (¿integrante?, ¿tema?), capturado (template) y semántico
(patrón vía LLM contra taxonomía cerrada config.FORMATO_PATRONES). El helper de
join cruza estos atributos con las métricas de ig_posts para que engagement.py
aprenda qué formato rinde. El etiquetado LLM copia el patrón de clasifica_generos.
"""
from __future__ import annotations

from typing import Any, Callable

import config
from src import db


def mapear_patron(valor: str | None) -> str:
    """Normaliza el patrón del LLM contra la taxonomía; 'otro' si no mapea."""
    if not valor:
        return "otro"
    v = valor.strip().lower().replace(" ", "_")
    # quita acentos básicos para el match
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        v = v.replace(a, b)
    return v if v in config.FORMATO_PATRONES else "otro"


def atributos_de_cola(cx) -> list[dict[str, Any]]:
    """Atributos de formato de cada item de content_queue (para inspección/test)."""
    filas = db.rows(cx, """
        SELECT id AS queue_id, member_id, tema_semilla, template, formato_patron
          FROM content_queue
    """)
    return [{
        "queue_id": f["queue_id"],
        "tiene_integrante": f["member_id"] is not None,
        "tiene_tema": bool((f["tema_semilla"] or "").strip()),
        "template": f["template"],
        "patron": f["formato_patron"] or "otro",
    } for f in filas]


def atributos_por_post(cx) -> list[dict[str, Any]]:
    """Cruza atributos de formato con métricas de ig_posts (vía queue_id).

    PURO sobre la DB de lectura: devuelve filas que engagement.score_formatos
    consume para aprender qué formato rinde. Solo posts del bot (con queue_id).
    """
    return db.rows(cx, """
        SELECT p.media_id, p.reach, p.shares, p.saved, p.likes, p.comments,
               (q.member_id IS NOT NULL)            AS tiene_integrante,
               (TRIM(COALESCE(q.tema_semilla,'')) != '') AS tiene_tema,
               q.template, COALESCE(q.formato_patron,'otro') AS patron
          FROM ig_posts p JOIN content_queue q ON q.id = p.queue_id
         WHERE p.reach IS NOT NULL
    """)


# ---------- Etiquetador LLM (patrón DeepSeek de clasifica_generos) ----------

_SYSTEM_PROMPT = """\
Clasifica el patrón de formato del meme. Responde ÚNICAMENTE un objeto JSON con:
- "patron": EXACTAMENTE uno de esta lista (cópialo literal):
{patrones}
Elige el que mejor describe la estructura del meme. Si no hay match claro, usa "otro".\
""".format(patrones=", ".join(config.FORMATO_PATRONES))


def _llm_real(prompt: str) -> str:
    """Llamada real a DeepSeek; devuelve el texto del mensaje (JSON string)."""
    from openai import OpenAI

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en el .env")
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=100,
        response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


def etiquetar_post(caption: str, *, _llm: Callable[[str], str] | None = None) -> str:
    """Etiqueta un caption con el patrón de taxonomía vía LLM.

    `_llm` es inyectable para testing sin red (recibe prompt, devuelve JSON string).
    Retorna el patrón normalizado (nunca falla: 'otro' como fallback).
    """
    from src.parse_events import extraer_json

    llm = _llm if _llm is not None else _llm_real
    try:
        raw = llm(caption)
        d = extraer_json(raw)
        return mapear_patron(d.get("patron") if isinstance(d, dict) else None)
    except Exception:  # LLM caído o JSON inparseable → fallback silencioso
        return "otro"


def etiquetar_publicados(cx, *, _llm=None) -> dict[str, int]:
    """Backfill: etiqueta content_queue.formato_patron desde ig_posts.caption.

    Cubre posts históricos publicados cuyo caption vive en ig_posts (la columna
    content_queue.caption es nueva y puede estar vacía para ellos).
    Solo toca filas donde q.formato_patron IS NULL.
    Devuelve {"etiquetados": N, "fallados": M}.
    """
    pendientes = db.rows(cx, """
        SELECT q.id AS queue_id, p.caption
          FROM ig_posts p JOIN content_queue q ON q.id = p.queue_id
         WHERE p.caption IS NOT NULL AND p.caption != ''
           AND q.formato_patron IS NULL
    """)
    res = {"etiquetados": 0, "fallados": 0}
    for fila in pendientes:
        try:
            patron = etiquetar_post(fila["caption"], _llm=_llm)
            db.update(cx, "content_queue", fila["queue_id"], formato_patron=patron)
            res["etiquetados"] += 1
        except Exception:
            res["fallados"] += 1
    return res


def etiquetar_cola(cx) -> dict[str, int]:
    """Etiqueta con LLM los items de content_queue que no tienen formato_patron.

    Solo toca filas con caption no nulo y formato_patron NULL.
    Devuelve {"etiquetados": N, "fallados": M}.
    """
    pendientes = db.rows(cx, """
        SELECT id, caption FROM content_queue
         WHERE formato_patron IS NULL AND caption IS NOT NULL AND caption != ''
    """)
    res = {"etiquetados": 0, "fallados": 0}
    for fila in pendientes:
        try:
            patron = etiquetar_post(fila["caption"])
            db.update(cx, "content_queue", fila["id"], formato_patron=patron)
            res["etiquetados"] += 1
        except Exception:
            res["fallados"] += 1
    return res
