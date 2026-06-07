"""ENTRYPOINT Proceso B — worker de publicación (GitHub Actions cron).

Sin interacción. Lee filas `approved` cuyo `scheduled_datetime <= ahora`, las
publica en Instagram y marca el Sheet. No requiere Playwright (la imagen ya está
compuesta y hosteada).

Uso:  python publish.py
"""
from __future__ import annotations

import json

from src import instagram, sheets


def _carousel_urls(image_url: str) -> list[str]:
    """Si imagen_compuesta_url es un JSON list (carrusel), lo devuelve; si no, []."""
    raw = (image_url or "").strip()
    if not raw.startswith("["):
        return []
    try:
        val = json.loads(raw)
        return [str(u) for u in val] if isinstance(val, list) else []
    except ValueError:
        return []


def _es_agenda(row: dict) -> bool:
    """¿La fila es una agenda/música-nueva? (tema_semilla o carrusel)."""
    tema = str(row.get("tema_semilla", "")).lower()
    return (any(k in tema for k in ("agenda", "shows", "música nueva", "musica nueva",
                                    "releases")) or bool(_carousel_urls(row.get("imagen_compuesta_url", ""))))


def main() -> None:
    due = sheets.get_due_rows()
    if not due:
        print("No hay nada por publicar ahora.")
        return

    # PRIORIDAD: agendas semanales/mensuales primero (caducan), luego el resto.
    due.sort(key=lambda r: (0 if _es_agenda(r) else 1, str(r.get("scheduled_datetime", ""))))
    print(f"Publicando {len(due)} pieza(s) (agendas primero)…")
    for row in due:
        row_id = row.get("id")
        image_url = row.get("imagen_compuesta_url", "")
        caption = row.get("caption_final") or row.get("caption_generado", "")
        if not image_url:
            sheets.update_row(row_id, status=sheets.STATUS_ERROR, notas="sin imagen_compuesta_url")
            print(f"⚠️  id={row_id} sin imagen_compuesta_url → error")
            continue
        try:
            urls = _carousel_urls(image_url)  # JSON list = carrusel
            post_id = (instagram.publish_carousel(urls, caption) if urls
                       else instagram.publish(image_url, caption))
            sheets.update_row(row_id, status=sheets.STATUS_PUBLISHED, ig_post_id=post_id)
            print(f"✅ id={row_id} publicado (ig_post_id={post_id})")
        except Exception as exc:  # noqa: BLE001
            sheets.update_row(row_id, status=sheets.STATUS_ERROR, notas=str(exc)[:400])
            print(f"❌ id={row_id} falló: {exc}")


if __name__ == "__main__":
    main()
