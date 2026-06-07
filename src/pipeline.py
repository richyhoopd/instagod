"""Pipeline de datos (scraping masivo): ingesta → clasifica → Spotify → eventos.

Encadena los pasos que NO tocan Telegram, así que es seguro correrlo mientras la
GUI está abierta y sin chocar con bot.py / generate*.py. Es el "botón grande"
del scraping masivo: una corrida deja toda la DB lista para que solo cures y
generes contenido.

Orden (cada paso es idempotente y tolera que el anterior falle):
  1. ingest_ig      — perfil + fotos de cada banda ACTIVA con handle
  2. classify       — caras/nitidez/flyers de las fotos nuevas
  3. enrich_spotify — popularity/géneros/releases (si hay llaves válidas)
  4. parse_events   — fecha/lugar de los flyers con DeepSeek

No incluye `import_followees` (eso se corre aparte, una vez, para descubrir
candidatas) ni nada de Telegram (los memes/anuncios siguen pasando por tu
aprobación, a propósito).

Uso:
    python -m src.pipeline                  # todas las bandas activas
    python -m src.pipeline kabala_oficial   # solo esos handles
    python -m src.pipeline --skip spotify   # salta pasos (ingest|classify|spotify|events)
"""
from __future__ import annotations

import argparse
import sys
import time

from src import classify, db, enrich_spotify, ingest_ig, parse_events, spotify_match


def _bandas_activas(handles: list[str] | None) -> list[str]:
    cx = db.connect()
    try:
        bandas = [b["ig_handle"] for b in db.list_bands(cx) if b.get("ig_handle")]
    finally:
        cx.close()
    if handles:
        quiero = {h.lstrip("@").lower() for h in handles}
        bandas = [h for h in bandas if h.lower() in quiero]
    return bandas


def run(handles: list[str] | None = None, skip: set[str] | None = None,
        rescan: bool = False) -> None:
    skip = skip or set()
    objetivo = _bandas_activas(handles)
    if not objetivo:
        print("No hay bandas activas con handle. Importa candidatas "
              "(python -m src.import_followees) y actívalas en la GUI.")
        return

    print(f"═══ PIPELINE sobre {len(objetivo)} banda(s) activa(s) ═══\n")
    t0 = time.time()

    if "ingest" not in skip:
        print("── 1/4 Ingesta de Instagram ──")
        # Pasamos `handles` (no `objetivo`): sin handles, la ingesta solo baja las
        # bandas NUEVAS (scraped_at IS NULL). Clasificación/Spotify/eventos sí
        # corren sobre todo (son idempotentes y baratos).
        ingest_ig.ingest(handles, rescan=rescan)
    if "classify" not in skip:
        print("\n── 2/4 Clasificación de fotos ──")
        classify.clasificar(objetivo)
    if "spotify" not in skip:
        print("\n── 3/4 Enriquecimiento Spotify ──")
        # Primero resolvemos spotify_id por links de agregadores (sin LLM) y luego
        # enriquecemos SOLO las que siguen 'pendiente'. Las que ya tienen id no se
        # tocan aquí: su data viva (popularity/releases) la trae el cron de novedades.
        try:
            cx = db.connect()
            try:
                spotify_match.resolver_links(cx)
            finally:
                cx.close()
            enrich_spotify.enrich(objetivo, solo_pendientes=True)
        except RuntimeError as exc:  # faltan llaves → no abortamos el pipeline
            print(f"   (saltado: {exc})")
    if "events" not in skip:
        print("\n── 4/4 Parseo de eventos ──")
        parse_events.parse_all()

    print(f"\n═══ Pipeline terminado en {time.time() - t0:.0f}s. "
          "Cura en la GUI y genera contenido. ═══")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de datos (scraping masivo)")
    parser.add_argument("handles", nargs="*", help="limitar a estos ig_handle")
    parser.add_argument("--skip", default="",
                        help="pasos a saltar, coma-separados: ingest,classify,spotify,events")
    parser.add_argument("--rescan", action="store_true",
                        help="re-escrapear también bandas ya scrapeadas")
    args = parser.parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    try:
        run(args.handles or None, skip, rescan=args.rescan)
    except KeyboardInterrupt:
        sys.exit("\nPipeline interrumpido.")
