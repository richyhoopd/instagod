"""Siembra única del catálogo de foros.

Orden deliberado, de lo barato y seguro a lo caro e incierto:

1. Los foros y eventos que Ricardo YA sigue (`bands` tipo foro/evento) entran
   como venues con su nombre y su handle de alias. Es el catálogo gratis.
2. Los `events.lugar` distintos se agrupan con `venues.normalizar`, que colapsa
   mayúsculas, arrobas, paréntesis y prefijos sin ayuda de nadie.
3. Solo lo que sigue ambiguo va al LLM, en UNA llamada.
4. Lo que el LLM no agrupa queda huérfano para curación en la GUI.

Idempotente y respetuoso de lo manual: un alias con origen='manual' no se toca.
"""
from __future__ import annotations

from typing import Any, Callable

import config
from src import db, venues

_TIPOS_VENUE = ("foro", "evento")

_PROMPT = """Eres un asistente que ordena nombres de foros y venues de la escena
musical de Guadalajara. Te doy una lista de textos crudos extraídos por OCR de
carteles de conciertos. Agrupa los que se refieran al MISMO lugar y dale a cada
grupo un nombre canónico limpio.

Reglas:
- Salas distintas del mismo edificio son lugares DISTINTOS (C3 Stage y C3
  Rooftop van separados).
- Si un texto no es un lugar (nombre de banda, dirección suelta, basura de OCR),
  NO lo incluyas en ningún grupo.
- Un texto que no puedas asignar con confianza, déjalo fuera.

Devuelve SOLO un JSON: [{"canonico": "Nombre Limpio", "alias": ["texto1", ...]}]

Textos:
"""


def sembrar_desde_bands(cx) -> int:
    """Crea venues desde las cuentas de tipo foro/evento. Devuelve cuántos creó."""
    creados = 0
    marcas = ",".join("?" * len(_TIPOS_VENUE))
    for b in db.rows(cx, f"""
        SELECT nombre, ig_handle, ciudad FROM bands
         WHERE tipo IN ({marcas}) AND activa = 1 ORDER BY id
    """, _TIPOS_VENUE):
        if venues.resolver(cx, b["nombre"]) is not None:
            continue
        vid = db.insert(cx, "venues", nombre=b["nombre"], ciudad=b["ciudad"],
                        ig_handle=b["ig_handle"])
        creados += 1
        for texto in (b["nombre"], b["ig_handle"]):
            if texto and venues.normalizar(texto):
                venues.asignar_alias(cx, vid, texto)
    return creados


def lugares_distintos(cx) -> list[str]:
    """Textos crudos distintos de `events.lugar`, en orden estable."""
    return [r["lugar"] for r in db.rows(cx, """
        SELECT DISTINCT lugar FROM events
         WHERE lugar IS NOT NULL AND trim(lugar) != ''
         ORDER BY lugar
    """)]


def agrupar_mecanico(lugares: list[str]) -> dict[str, list[str]]:
    """Clave normalizada → textos crudos que caen en ella. PURA."""
    grupos: dict[str, list[str]] = {}
    for l in lugares:
        clave = venues.normalizar(l)
        if clave:
            grupos.setdefault(clave, []).append(l)
    return grupos


def _llm_agrupar(pendientes: list[str]) -> list[dict[str, Any]]:
    """UNA llamada a DeepSeek con todos los textos ambiguos."""
    if not pendientes:
        return []
    from openai import OpenAI
    from src.parse_events import extraer_json
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": _PROMPT + "\n".join(pendientes)}],
        temperature=0,
    )
    data = extraer_json(resp.choices[0].message.content or "")
    if isinstance(data, dict):
        data = data.get("grupos") or []
    return data if isinstance(data, list) else []


def sembrar(cx, *, _llm: Callable[[list[str]], list[dict]] | None = None) -> dict:
    """Siembra completa. Devuelve {venues, alias, huerfanos, pendientes_llm}."""
    llm = _llm or _llm_agrupar
    db.init_db(cx)
    creados = sembrar_desde_bands(cx)

    grupos = agrupar_mecanico(lugares_distintos(cx))
    # Lo que ya resuelve contra el catálogo no se toca; el resto es "pendiente".
    pendientes = [textos[0] for clave, textos in grupos.items()
                  if venues.resolver(cx, textos[0]) is None]

    alias_nuevos = 0
    for grupo in llm(pendientes):
        canonico = (grupo.get("canonico") or "").strip()
        alias = [a for a in (grupo.get("alias") or []) if a and a.strip()]
        if not canonico or not alias:
            continue
        vid = venues.resolver(cx, canonico)
        if vid is None:
            vid = db.insert(cx, "venues", nombre=canonico)
            creados += 1
        for texto in [canonico, *alias]:
            clave = venues.normalizar(texto)
            if not clave:
                continue
            filas = db.rows(cx, "SELECT id, origen FROM venue_alias WHERE alias_norm = ?",
                            (clave,))
            if filas and filas[0]["origen"] == "manual":
                continue          # el batch NUNCA pisa lo curado a mano
            if filas:
                db.update(cx, "venue_alias", filas[0]["id"], venue_id=vid, origen="llm")
            else:
                db.insert(cx, "venue_alias", venue_id=vid, alias_norm=clave,
                          alias_visto=texto, origen="llm")
            alias_nuevos += 1

    # Lo que sigue sin resolver entra a la cola de curación.
    for clave, textos in grupos.items():
        if venues.resolver(cx, textos[0]) is None:
            venues.registrar_desconocido(cx, textos[0])
    cx.commit()
    return {"venues": creados, "alias": alias_nuevos,
            "huerfanos": len(venues.huerfanos(cx)),
            "pendientes_llm": len(pendientes)}
