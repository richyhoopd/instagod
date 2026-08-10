"""Entrypoint del motor de slideshows (Proceso A, no-bloqueante).

CLI/GUI → guion (LLM) → imágenes (cascada de fuentes) → compilar → render →
Cloudinary → encolar + Telegram. El approval-daemon resuelve la aprobación;
publish.py publica el carrusel. NO abre poller de Telegram.

Uso:
  python -m src.generate_slideshow --tema "cafeterías de GDL" \
      --formato listicle --estilo tiktok_bold --fuentes pexels,banco --dry-run
"""
from __future__ import annotations

import argparse
import json
import time

import config
from src import (
    approval,
    compose,
    db,
    host,
    image_sources,
    slideshow_compile,
    slideshow_model,
    slideshow_script,
)


def generar(cx, tema: str, *, formato: str = "listicle",
            estilo: str = "tiktok_bold", fuentes: tuple[str, ...] = ("pexels",),
            n_slides: int = 6, aspect: str = "4:5", contexto: str | None = None,
            dry_run: bool = False) -> int | None:
    """Genera el set completo; queue_id, o None en dry-run."""
    guion = slideshow_script.generar_guion(tema, formato=formato,
                                           n_slides=n_slides, contexto=contexto)
    hints = [sl["image_hint"] for sl in guion["slides"]]
    imagenes = image_sources.resolver(hints, list(fuentes), cx=cx)
    sin_imagen = sum(1 for i in imagenes if i is None)
    if sin_imagen:
        print(f"[slideshow] {sin_imagen}/{len(imagenes)} slides sin imagen "
              "(fondo sólido)")
    brief = {"tema": tema, "formato": formato, "estilo": estilo,
             "fuentes": list(fuentes), "n_slides": n_slides,
             "contexto": contexto, "aspect": aspect}
    show = slideshow_compile.compilar(guion, estilo=estilo, imagenes=imagenes,
                                      aspect_ratio=aspect, brief=brief,
                                      formato=formato)
    errores = slideshow_model.validar(show)
    if errores:
        raise RuntimeError(f"Contrato inválido, no se encola: {errores}")

    pngs = []
    for i in range(len(show.slides)):
        ctx = slideshow_compile.contexto_slide(show, i)
        pngs.append(compose.render_card("slide.html", ctx, prefix=f"slide{i}"))
    if dry_run:
        print("[slideshow] dry-run, PNGs en:")
        for p in pngs:
            print(f"  {p}")
        return None

    ts = int(time.time())
    urls = [host.upload(str(p), public_id=f"ss{ts}_{i}")
            for i, p in enumerate(pngs)]
    qid = approval.encolar_pendiente(
        cx, tipo="slideshow", caption=show.caption,
        imagen_url=json.dumps(urls), template=estilo,
        tema_semilla=f"slideshow {formato}: {tema}")
    db.update(cx, "content_queue", qid,
              slideshow_json=slideshow_model.a_json(show))
    approval.enviar_a_telegram(show.caption, json.dumps(urls), qid)
    print(f"[slideshow] q{qid} enviado a Telegram ({len(urls)} slides)")
    return qid


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera un slideshow y lo manda a aprobación")
    ap.add_argument("--tema", required=True)
    ap.add_argument("--formato", default="listicle",
                    choices=sorted(config.SLIDESHOW_FORMATOS))
    ap.add_argument("--estilo", default="tiktok_bold",
                    choices=sorted(config.SLIDESHOW_ESTILOS))
    ap.add_argument("--fuentes", default="pexels",
                    help="orden de fuentes separado por comas: banco,covers,pexels,pinterest")
    ap.add_argument("--n-slides", type=int, default=6)
    ap.add_argument("--aspect", default="4:5",
                    choices=sorted(slideshow_model.ASPECT_RATIOS))
    ap.add_argument("--contexto", default=None,
                    help="voz/instrucciones extra para el guion")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cx = db.connect()
    try:
        db.init_db(cx)
        generar(cx, args.tema, formato=args.formato, estilo=args.estilo,
                fuentes=tuple(f.strip() for f in args.fuentes.split(",") if f.strip()),
                n_slides=args.n_slides, aspect=args.aspect,
                contexto=args.contexto, dry_run=args.dry_run)
    finally:
        cx.close()


if __name__ == "__main__":
    main()
