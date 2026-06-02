"""ENTRYPOINT Proceso B — worker de publicación (GitHub Actions cron).

Sin interacción. Lee filas `approved` cuyo `scheduled_datetime <= ahora`, las
publica en Instagram y marca el Sheet. No requiere Playwright (la imagen ya está
compuesta y hosteada).

Uso:  python publish.py
"""
from __future__ import annotations

from src import instagram, sheets


def main() -> None:
    due = sheets.get_due_rows()
    if not due:
        print("No hay nada por publicar ahora.")
        return

    print(f"Publicando {len(due)} meme(s)…")
    for row in due:
        row_id = row.get("id")
        image_url = row.get("imagen_compuesta_url", "")
        caption = row.get("caption_final") or row.get("caption_generado", "")
        if not image_url:
            sheets.update_row(row_id, status=sheets.STATUS_ERROR, notas="sin imagen_compuesta_url")
            print(f"⚠️  id={row_id} sin imagen_compuesta_url → error")
            continue
        try:
            post_id = instagram.publish(image_url, caption)
            sheets.update_row(row_id, status=sheets.STATUS_PUBLISHED, ig_post_id=post_id)
            print(f"✅ id={row_id} publicado (ig_post_id={post_id})")
        except Exception as exc:  # noqa: BLE001
            sheets.update_row(row_id, status=sheets.STATUS_ERROR, notas=str(exc)[:400])
            print(f"❌ id={row_id} falló: {exc}")


if __name__ == "__main__":
    main()
