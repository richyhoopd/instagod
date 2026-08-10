"""ENTRYPOINT Proceso B — worker de publicación (GitHub Actions cron).

Sin interacción. Lee filas `approved` cuyo `scheduled_datetime <= ahora` y las
publica en TODAS las redes habilitadas (IG, X, FB) con el mismo caption ya
aprobado en Telegram. Cada red guarda su id en su columna; la fila pasa a
`published` cuando todas las habilitadas tienen id. Si una red falla, la fila
sigue `approved` y el cron siguiente reintenta SOLO la que falta (columna
vacía = pendiente), sin duplicar en las demás.

Uso:  python publish.py
"""
from __future__ import annotations

import json

import config
from src import facebook, instagram, sheets, x_twitter

# (columna en el Sheet, etiqueta para notas, módulo, habilitada)
PLATFORMS = [
    ("ig_post_id", "ig", instagram, True),
    ("tw_post_id", "x", x_twitter, config.CROSSPOST_X),
    ("fb_post_id", "fb", facebook, config.CROSSPOST_FB),
]


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
    """¿La fila es una agenda/música-nueva? (tema_semilla o carrusel).

    Nota: cualquier carrusel JSON-list (incluidos los slideshows) cae aquí
    también, a propósito — es solo cuestión de orden de publicación, no de
    tratarlos como agenda en ningún otro sentido (aceptado en v1)."""
    tema = str(row.get("tema_semilla", "")).lower()
    return (any(k in tema for k in ("agenda", "shows", "música nueva", "musica nueva",
                                    "releases")) or bool(_carousel_urls(row.get("imagen_compuesta_url", ""))))


def publish_row(row: dict) -> tuple[bool, list[str]]:
    """Publica una fila en las redes habilitadas que aún no tengan post id.

    Escribe cada id al Sheet INMEDIATAMENTE (si el job muere a medias no hay
    duplicados). Devuelve (todas_listas, errores).
    """
    row_id = row.get("id")
    image_url = row.get("imagen_compuesta_url", "")
    caption = row.get("caption_final") or row.get("caption_generado", "")
    urls = _carousel_urls(image_url)  # JSON list = carrusel

    errores: list[str] = []
    todas_listas = True
    for col, tag, mod, enabled in PLATFORMS:
        if not enabled:
            continue
        if str(row.get(col, "")).strip():
            continue  # ya publicada en esta red (reintento parcial)
        try:
            post_id = (mod.publish_carousel(urls, caption) if urls
                       else mod.publish(image_url, caption))
            sheets.update_row(row_id, **{col: post_id})
            print(f"  ✅ {tag}: {post_id}")
        except Exception as exc:  # noqa: BLE001
            todas_listas = False
            errores.append(f"{tag}: {exc}")
            print(f"  ❌ {tag}: {exc}")
    return todas_listas, errores


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
        if not row.get("imagen_compuesta_url", ""):
            sheets.update_row(row_id, status=sheets.STATUS_ERROR, notas="sin imagen_compuesta_url")
            print(f"⚠️  id={row_id} sin imagen_compuesta_url → error")
            continue
        print(f"id={row_id}:")
        todas_listas, errores = publish_row(row)
        if todas_listas:
            sheets.update_row(row_id, status=sheets.STATUS_PUBLISHED, notas="")
            print(f"✅ id={row_id} publicado en todas las redes habilitadas")
        else:
            # Sigue approved: el cron siguiente reintenta solo las columnas vacías.
            sheets.update_row(row_id, notas=" | ".join(errores)[:400])
            print(f"⏳ id={row_id} parcial; reintento en el siguiente cron")


if __name__ == "__main__":
    main()
