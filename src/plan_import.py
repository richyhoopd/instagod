"""Importa un plan de contenido renderizado afuera (carpetas por plataforma) a
`content_queue` como BORRADORES calendarizados.

El plan trae `calendario.csv` (fecha,tipo,formato,etapa,tema,id,slides) y
`<plataforma>/<post|reel|historia>/<fecha>_<id>/` con PNGs, `reel.mp4`,
`caption.txt` o `notas.txt`. Dos pasos, porque los archivos viven en la Mac y
la DB en la VM:

1. `manifiesto()` (Mac): sube cada archivo único a Cloudinary (dedup por sha1,
   caché en `<plan>/build/cloudinary.json`) y arma la lista de filas.
2. `cargar()` (VM): inserta las filas. Idempotente por
   (account_id, plataforma, formato, scheduled_datetime, tema_semilla).

Todo entra con status='borrador', aprobacion NULL, origen='import': el
publisher no lo toca (filas_due exige programado+aprobado y solo instagram sin
historias).
"""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pytz

PLATAFORMAS = ("instagram", "facebook", "tiktok")
# Hora local de cada pieza: feed a las 19:00; historias del día escalonadas.
HORA_FEED = 19
HORAS_HISTORIA = (10, 13, 16, 21)


def _sha1(ruta: Path) -> str:
    return hashlib.sha1(ruta.read_bytes()).hexdigest()


def _iso(fecha: str, hora: int, tz: str) -> str:
    local = pytz.timezone(tz).localize(datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H"))
    return local.isoformat()


def _leer(ruta: Path) -> str:
    return ruta.read_text(encoding="utf-8").strip() if ruta.exists() else ""


def manifiesto(plan: Path, *, tz: str, subir_imagen: Callable[[Path, str], str],
               subir_video: Callable[[Path, str], str],
               cache_ruta: Path | None = None) -> list[dict[str, Any]]:
    """Filas listas para `cargar`, una por (entrada del calendario × plataforma)."""
    cache_ruta = cache_ruta or plan / "build" / "cloudinary.json"
    cache: dict[str, str] = json.loads(cache_ruta.read_text()) if cache_ruta.exists() else {}

    def url(ruta: Path, video: bool) -> str:
        h = _sha1(ruta)
        if h not in cache:
            pid = f"plan-{h[:20]}"
            cache[h] = subir_video(ruta, pid) if video else subir_imagen(ruta, pid)
            cache_ruta.parent.mkdir(parents=True, exist_ok=True)
            cache_ruta.write_text(json.dumps(cache, indent=1))
        return cache[h]

    with (plan / "calendario.csv").open(encoding="utf-8") as f:
        entradas = list(csv.DictReader(f))

    filas: list[dict[str, Any]] = []
    historias_del_dia: dict[str, int] = {}
    for e in entradas:
        es_historia = e["tipo"] == "historia"
        formato = "historia" if es_historia else e["formato"]
        if es_historia:
            n = historias_del_dia.get(e["fecha"], 0)
            historias_del_dia[e["fecha"]] = n + 1
            hora = HORAS_HISTORIA[min(n, len(HORAS_HISTORIA) - 1)]
        else:
            hora = HORA_FEED
        carpeta_rel = Path(formato) / f"{e['fecha']}_{e['id']}"
        for plataforma in PLATAFORMAS:
            d = plan / plataforma / carpeta_rel
            if not d.is_dir():
                raise FileNotFoundError(d)
            if formato == "reel":
                tipo, media = "video", url(d / "reel.mp4", True)
            else:
                pngs = sorted(d.glob("*.png"))
                if not pngs:
                    raise FileNotFoundError(f"sin PNG en {d}")
                urls = [url(p, False) for p in pngs]
                tipo = "slideshow"
                media = urls[0] if len(urls) == 1 else json.dumps(urls)
            caption = _leer(d / "caption.txt") or _leer(d / "notas.txt")
            filas.append({
                "tipo": tipo, "plataforma": plataforma, "etapa": e["etapa"],
                "formato": formato, "aspecto": "9:16" if es_historia or formato == "reel" else "4:5",
                "caption": caption, "imagen_url": media,
                "tema_semilla": f"{e['tema']} · {e['id']}",
                "scheduled_datetime": _iso(e["fecha"], hora, tz),
            })
    return filas


def cargar(cx, account_id: int, filas: list[dict[str, Any]]) -> tuple[int, int]:
    """Inserta las filas como borrador. Devuelve (insertadas, ya_existían)."""
    from src import db

    nuevas = repetidas = 0
    for f in filas:
        ya = cx.execute(
            "SELECT 1 FROM content_queue WHERE account_id=? AND origen='import' "
            "AND plataforma=? AND formato=? AND scheduled_datetime=? AND tema_semilla=?",
            (account_id, f["plataforma"], f["formato"], f["scheduled_datetime"],
             f["tema_semilla"])).fetchone()
        if ya:
            repetidas += 1
            continue
        db.insert(cx, "content_queue", account_id=account_id, status="borrador",
                  origen="import", **f)
        nuevas += 1
    cx.commit()
    return nuevas, repetidas
