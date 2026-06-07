"""Clasificación de géneros por banda con LLM (Frente A de afinación de datos).

Spotify no devuelve géneros a esta app (cap de dev-mode), así que el género se
infiere con DeepSeek a partir de lo que SÍ tenemos: nombre, bio, category_ig,
tipo y los captions de las fotos de la banda. El `genero_principal` se restringe
a la taxonomía cerrada `config.GENEROS` (segmentable, sin fragmentar tags); los
matices van como subtags libres en `bands.generos`.

Reglas de origen: el batch toca bandas con `generos_fuente` NULL o `'llm'` —
NUNCA pisa `'manual'` (lo curado a mano en la GUI gana). Errores por banda (LLM
caído o JSON no parseable) se loggean y la corrida sigue.

Uso:
    python -m src.clasifica_generos                 # todas las activas pendientes
    python -m src.clasifica_generos handle1 handle2 # solo esos ig_handle
    python -m src.clasifica_generos --solo-faltantes  # solo sin genero_principal
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import config
from src import db
from src.parse_events import extraer_json

# Hasta ~10 captions por banda: dan contexto del sonido/escena sin inflar el prompt.
_MAX_CAPTIONS = 10

SYSTEM_PROMPT = """\
Clasificas el género musical de un proyecto de la escena independiente. Respondes \
ÚNICAMENTE un objeto JSON, sin explicación, con:
- "genero_principal": EXACTAMENTE uno de esta lista cerrada (cópialo literal):
{generos}
- "subtags": lista de 0 a 4 matices libres (subgéneros, escenas, descriptores) \
en minúsculas, p. ej. ["d-beat", "crust"]. [] si no hay.
Elige el género que mejor describa el sonido a partir del nombre, la bio y los \
captions. Si dudas, usa el más cercano de la lista; NUNCA inventes uno fuera de \
ella.""".format(generos=", ".join(config.GENEROS))


def mapear_genero(valor: str | None) -> str | None:
    """Normaliza el género del LLM contra config.GENEROS; None si no mapea.

    Tolerante: match exacto (casefold), luego substring en cualquier dirección
    ("Indie Rock" → "indie", "post punk" → "post-punk" no, pero "post-punk core"
    sí). Evita fragmentar la taxonomía cuando el LLM agrega adjetivos.
    """
    if not valor:
        return None
    v = valor.strip().casefold()
    for g in config.GENEROS:
        if v == g.casefold():
            return g
    for g in config.GENEROS:
        gc = g.casefold()
        if gc in v or v in gc:
            return g
    return None


def _construir_contexto(cx, banda: dict[str, Any]) -> str:
    """Texto que se manda al LLM: ficha de la banda + sus captions más largos."""
    partes = [f"NOMBRE: {banda['nombre']}"]
    if banda.get("tipo"):
        partes.append(f"TIPO: {banda['tipo']}")
    if banda.get("category_ig"):
        partes.append(f"CATEGORÍA IG: {banda['category_ig']}")
    if banda.get("ciudad"):
        partes.append(f"CIUDAD: {banda['ciudad']}")
    if banda.get("bio"):
        partes.append(f"BIO: {banda['bio']}")
    captions = db.rows(cx, """
        SELECT caption_original FROM photos
         WHERE band_id = ? AND caption_original IS NOT NULL AND caption_original != ''
         ORDER BY LENGTH(caption_original) DESC
         LIMIT ?
    """, (banda["id"], _MAX_CAPTIONS))
    if captions:
        textos = [c["caption_original"][:400] for c in captions]
        partes.append("CAPTIONS DE SUS POSTS:\n" + "\n---\n".join(textos))
    return "\n".join(partes)


def _llm_clasificar(contexto: str) -> dict[str, Any] | None:
    """Una llamada a DeepSeek; devuelve el dict del JSON o None si no parsea."""
    from openai import OpenAI

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en el .env")
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": contexto},
        ],
        temperature=0,  # clasificación, no creatividad
        max_tokens=200,
        response_format={"type": "json_object"},
    )
    return extraer_json(resp.choices[0].message.content or "")


def _bandas_a_clasificar(cx, handles: list[str] | None,
                         solo_faltantes: bool) -> list[dict[str, Any]]:
    """Bandas activas elegibles: fuente NULL o 'llm' (nunca 'manual')."""
    cond = ["activa = 1", "(generos_fuente IS NULL OR generos_fuente = 'llm')"]
    params: list[Any] = []
    if solo_faltantes:
        cond.append("(genero_principal IS NULL OR genero_principal = '')")
    if handles:
        marks = ", ".join("?" * len(handles))
        cond.append(f"ig_handle IN ({marks})")
        params.extend(handles)
    return db.rows(cx, f"SELECT * FROM bands WHERE {' AND '.join(cond)} ORDER BY id", params)


def clasificar(cx=None, handles: list[str] | None = None,
               solo_faltantes: bool = False) -> dict[str, int]:
    """Clasifica las bandas elegibles. Devuelve resumen {clasificadas/falladas/saltadas}.

    `saltadas` = activas con fuente 'manual' (protegidas); las contamos para que
    el resumen explique por qué no se tocaron todas las activas.
    """
    propia = cx is None
    if propia:
        cx = db.connect()
        db.init_db(cx)
    try:
        bandas = _bandas_a_clasificar(cx, handles, solo_faltantes)
        # Conteo informativo de las protegidas a mano dentro del mismo recorte.
        scond = ["activa = 1", "generos_fuente = 'manual'"]
        sparams: list[Any] = []
        if handles:
            marks = ", ".join("?" * len(handles))
            scond.append(f"ig_handle IN ({marks})")
            sparams.extend(handles)
        saltadas = db.rows(cx, f"SELECT COUNT(*) n FROM bands WHERE {' AND '.join(scond)}",
                           sparams)[0]["n"]

        res = {"clasificadas": 0, "falladas": 0, "saltadas": saltadas}
        for banda in bandas:
            etiqueta = banda.get("ig_handle") or banda["nombre"]
            try:
                data = _llm_clasificar(_construir_contexto(cx, banda))
            except Exception as exc:  # noqa: BLE001 — una banda no debe tumbar la corrida
                res["falladas"] += 1
                print(f"✗ {etiqueta}: LLM falló ({exc})")
                continue
            if not isinstance(data, dict):
                res["falladas"] += 1
                print(f"✗ {etiqueta}: respuesta no parseable")
                continue
            genero = mapear_genero(data.get("genero_principal"))
            if genero is None:
                res["falladas"] += 1
                print(f"✗ {etiqueta}: género fuera de taxonomía "
                      f"({data.get('genero_principal')!r}) — sin tocar")
                continue
            subtags = data.get("subtags") or []
            subtags = [str(s).strip() for s in subtags if str(s).strip()] \
                if isinstance(subtags, list) else []
            db.update(cx, "bands", banda["id"],
                      genero_principal=genero,
                      generos=json.dumps(subtags, ensure_ascii=False),
                      generos_fuente="llm")
            res["clasificadas"] += 1
            print(f"✓ {etiqueta}: {genero} {subtags}")
        return res
    finally:
        if propia:
            cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clasificación de géneros con LLM (Frente A)")
    parser.add_argument("handles", nargs="*", help="ig_handle de bandas específicas")
    parser.add_argument("--solo-faltantes", action="store_true",
                        help="solo bandas sin genero_principal")
    args = parser.parse_args()
    try:
        res = clasificar(handles=args.handles or None, solo_faltantes=args.solo_faltantes)
        print(f"\nResumen → clasificadas: {res['clasificadas']}, "
              f"falladas: {res['falladas']}, saltadas (manual): {res['saltadas']}")
    except KeyboardInterrupt:
        sys.exit("\nClasificación interrumpida.")
