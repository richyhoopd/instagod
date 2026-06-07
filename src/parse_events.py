"""Parseo de eventos con LLM (Fase 5): flyer (OCR) + caption → datos estructurados.

Por cada evento con `parseado_por_llm=0` junta el texto OCR del flyer y el
caption original del post, se lo pasa a DeepSeek a temperatura 0 (extracción,
no creatividad) y obtiene JSON `{tipo, fecha, lugar, ciudad}`. Solo rellena
campos que el evento no tenga ya (lo curado a mano en la GUI gana).

La fecha del post acompaña al prompt para resolver referencias relativas
("este viernes", "21 NOV") al año correcto.

Uso:
    python -m src.parse_events            # todos los pendientes
    python -m src.parse_events --solo 3   # un evento específico (id)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import config
from src import db
from src.classify import texto_ocr_fuerte

_TIPOS = {"fecha", "flyer", "release"}

SYSTEM_PROMPT = """\
Extraes datos de eventos musicales a partir del texto OCR de un flyer de Instagram \
y el caption del post. Respondes ÚNICAMENTE un objeto JSON, sin explicación, con:
- "tipo": "fecha" (show/concierto), "release" (lanzamiento de música) o "flyer" \
(no se distingue).
- "fecha": fecha del evento en formato YYYY-MM-DD, o null si no es deducible. Usa la \
fecha del post como referencia para resolver años y días relativos. Si el OCR da día \
y mes sin año, asume el año del post (o el siguiente si esa fecha ya pasó al postear).
- "lugar": nombre del venue/foro tal como aparece, o null.
- "ciudad": ciudad si aparece o es deducible del venue, o null.
Si el texto es ilegible o no hay datos, devuelve los campos en null. NUNCA inventes \
fecha ni lugar: solo lo que el texto soporte."""


def extraer_json(texto: str) -> dict[str, Any] | None:
    """Primer objeto JSON dentro de la respuesta del LLM (tolera ```json ...```)."""
    m = re.search(r"\{.*\}", texto, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except ValueError:
        return None


def _llm_extraer(prompt: str) -> dict[str, Any] | None:
    from openai import OpenAI

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en el .env")
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0,  # extracción de datos: nada de creatividad
        max_tokens=200,
    )
    return extraer_json(resp.choices[0].message.content or "")


def parse_event(cx, evento: dict[str, Any]) -> str:
    """Parsea un evento y persiste. Devuelve etiqueta para el log."""
    partes = []
    if evento.get("flyer_path"):
        path = Path(evento["flyer_path"])
        if not path.is_absolute():
            path = config.BASE_DIR / path
        if path.exists():
            ocr = texto_ocr_fuerte(path)
            if ocr:
                partes.append(f"TEXTO OCR DEL FLYER:\n{ocr[:1500]}")
    foto = db.rows(cx, """
        SELECT caption_original, fecha FROM photos
         WHERE band_id = ? AND source_post_id = ? AND caption_original IS NOT NULL
         LIMIT 1
    """, (evento["band_id"], evento["source_post_id"]))
    if foto:
        partes.append(f"CAPTION DEL POST:\n{foto[0]['caption_original'][:800]}")
        if foto[0].get("fecha"):
            partes.append(f"FECHA DEL POST: {foto[0]['fecha'][:10]}")
    if not partes:
        return "sin texto que parsear (ni OCR ni caption)"

    data = _llm_extraer("\n\n".join(partes))
    if data is None:
        return "el LLM no devolvió JSON válido"

    cambios: dict[str, Any] = {"parseado_por_llm": 1}
    # Solo rellenamos huecos: lo curado a mano en la GUI no se pisa.
    if not evento.get("fecha_evento") and data.get("fecha"):
        cambios["fecha_evento"] = str(data["fecha"])[:10]
    if not evento.get("lugar") and data.get("lugar"):
        cambios["lugar"] = str(data["lugar"])[:120]
    if not evento.get("ciudad") and data.get("ciudad"):
        cambios["ciudad"] = str(data["ciudad"])[:80]
    if data.get("tipo") in _TIPOS and evento.get("tipo") == "flyer":
        cambios["tipo"] = data["tipo"]
    db.update(cx, "events", evento["id"], **cambios)

    detalle = {k: v for k, v in cambios.items() if k != "parseado_por_llm"}
    return f"→ {detalle}" if detalle else "parseado: sin datos nuevos"


def parse_all(solo: int | None = None) -> None:
    cx = db.connect()
    try:
        db.init_db(cx)
        # No gastar LLM en irrelevantes (salvo que se pida un id explícito).
        where = ("WHERE e.parseado_por_llm = 0 AND e.irrelevante = 0"
                 if solo is None else "WHERE e.id = ?")
        params = () if solo is None else (solo,)
        eventos = db.rows(cx, f"""
            SELECT e.*, b.nombre AS banda_nombre FROM events e
              JOIN bands b ON b.id = e.band_id {where} ORDER BY e.id
        """, params)
        if not eventos:
            print("No hay eventos por parsear.")
            return
        print(f"Parseando {len(eventos)} evento(s) con DeepSeek…")
        for ev in eventos:
            print(f"▶ #{ev['id']} {ev['banda_nombre']}: {parse_event(cx, ev)}")
    finally:
        cx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Parseo de eventos con LLM (Fase 5)")
    parser.add_argument("--solo", type=int, default=None, help="id de un evento específico")
    args = parser.parse_args()
    try:
        parse_all(args.solo)
    except KeyboardInterrupt:
        sys.exit("\nParseo interrumpido.")
