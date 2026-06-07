"""ENTRYPOINT Proceso A — sesión de generación (local, on-demand).

Lee filas `pending` del Sheet, genera caption + imagen para cada una, las manda
a aprobar por Telegram y, conforme apruebas, sube a Cloudinary, asigna horario y
marca el Sheet. Corre en tu máquina; termina cuando resuelves todo el lote.

Uso:  python generate.py
"""
from __future__ import annotations

import asyncio

import config
from src import caption as caption_mod
from src import compose as compose_mod
from src import db, host, scheduler, sheets, telegram_bot


def _build_item(row: dict) -> dict:
    """Genera caption + imagen para una fila pending y arma el item de aprobación."""
    tipo = db.tipo_de_actor(row.get("banda"))
    cap = caption_mod.generate_caption(
        banda=row.get("banda", ""),
        integrante=row.get("integrante", ""),
        rol=row.get("rol", ""),
        tema_semilla=row.get("tema_semilla") or None,
        tipo=tipo,
    )
    template = compose_mod.random_template()
    png = compose_mod.compose(
        caption=cap,
        foto_url=row.get("foto_url", ""),
        foto_inset_url=row.get("foto_inset_url") or None,
        template=template,
        row_id=row.get("id"),
    )
    return {
        "row_id": row.get("id"),
        "caption": cap,
        "image_path": str(png),
        "meta": {
            "banda": row.get("banda", ""),
            "integrante": row.get("integrante", ""),
            "rol": row.get("rol", ""),
            "tema_semilla": row.get("tema_semilla") or None,
            "foto_url": row.get("foto_url", ""),
            "foto_inset_url": row.get("foto_inset_url") or None,
            "tipo": tipo,
            "template": template,
            "rechazados": [],  # captions rechazados acumulados para el prompt
        },
    }


def _regenerate(item: dict) -> tuple[str, str]:
    """Recompone la imagen.

    Si `_solo_recomponer` (botón de plantilla): conserva el caption y recompone con
    `meta["template"]`. Si `texto_exacto`/`feedback`: comandos de Telegram. Sin
    nada: regenera el caption evitando los previos.
    """
    meta = item["meta"]
    if meta.get("_solo_recomponer"):
        cap = item["caption"]
    elif meta.get("texto_exacto"):
        cap = meta["texto_exacto"]
    else:
        meta["rechazados"].append(item["caption"])
        cap = caption_mod.generate_caption(
            banda=meta["banda"], integrante=meta["integrante"], rol=meta["rol"],
            tema_semilla=meta["tema_semilla"], rechazados=meta["rechazados"],
            tipo=meta.get("tipo", "banda"), feedback=meta.get("feedback"),
        )
    png = compose_mod.compose(
        caption=cap,
        foto_url=meta["foto_url"],
        foto_inset_url=meta["foto_inset_url"],
        template=meta.get("template", "clasica"),
        row_id=item["row_id"],
    )
    return cap, str(png)


async def main() -> None:
    rows = sheets.get_pending_rows()
    if not rows:
        print("No hay filas pending. Nada que generar.")
        return

    print(f"Generando {len(rows)} meme(s)…")
    # _build_item usa Playwright (sync API): debe correr fuera del loop asyncio.
    items = [await asyncio.to_thread(_build_item, r) for r in rows]
    registry = {str(it["row_id"]): it for it in items}

    decisions = await telegram_bot.run_approval_batch(items, _regenerate)

    for d in decisions:
        row_id = d["row_id"]
        item = registry[str(row_id)]
        if d["action"] == "approved":
            url = host.upload(item["image_path"], public_id=f"meme_{row_id}")
            slot = scheduler.assign_slot(row_id)  # marca status=approved + scheduled_datetime
            sheets.update_row(
                row_id,
                caption_generado=item["caption"],
                caption_final=d["caption"],
                imagen_compuesta_url=url,
            )
            print(f"✅ id={row_id} aprobado → publica {slot}")
        else:
            sheets.update_row(
                row_id,
                caption_generado=item["caption"],
                status=sheets.STATUS_REJECTED,
                notas="rechazado en sesión de generación",
            )
            print(f"❌ id={row_id} rechazado")

    print("Lote resuelto.")


if __name__ == "__main__":
    asyncio.run(main())
