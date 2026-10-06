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
    cifras,
    compose,
    db,
    host,
    image_sources,
    slideshow_compile,
    slideshow_model,
    slideshow_script,
)
from src import fuentes as fuentes_mod


class CifrasFueraDeFacts(RuntimeError):
    """El guion citó cifras que no están en `facts`, aun tras regenerar una vez.
    La pieza se descarta (no se encola)."""


def generar(cx, tema: str, *, marca: str = "gdlscene", formato: str | None = None,
            estilo: str | None = None, fuentes: tuple[str, ...] | None = None,
            n_slides: int = 6, aspect: str = "4:5", contexto: str | None = None,
            dry_run: bool = False, progreso=None, creado_por: int | None = None,
            topic_id: int | None = None,
            notificar_telegram: bool = True,
            hechos: dict | None = None,
            no_verificados: list[str] | None = None,
            entity_id: int | None = None,
            receta: str | None = None,
            imagenes_preferidas: list[str] | None = None,
            extra_brief: dict | None = None) -> int | None:
    """Genera el set con el PERFIL de la marca; queue_id o None en dry-run.

    `progreso`: callback opcional `(pct: int, msg: str) -> None` (p. ej.
    `jobs.progresar`), para que el caller reporte avance sin acoplarse al
    motor de jobs. `creado_por`: user_id del portal que disparó la generación
    (Fase 2); si se da, marca la fila de `content_queue` con `origen='api'`.
    `topic_id`: fila de `topic_suggestions` que originó el tema (Fase 3); si
    se da, se marca `usado_en_queue_id` al encolar (tolerante si ya no existe).

    Recetas (spec 2026-10-06): con `hechos` (los `facts` del item) toda cifra
    del guion debe estar ahí; si no, se regenera UNA vez con la lista de
    cifras prohibidas y si vuelve a fallar se levanta CifrasFueraDeFacts.
    `no_verificados` mencionados → ⚠️ en la tarjeta de Telegram.
    `imagenes_preferidas`: URLs de la media del item, antes que la cascada.
    Aspecto 9:16 → además manda un ZIP de PNGs al Telegram de la marca.
    """
    from src import marcas as marcas_mod

    def _reportar(pct: int, msg: str) -> None:
        if progreso is not None:
            progreso(pct, msg)

    m = marcas_mod.cargar(cx, marca)
    formato = formato or (m.formatos[0] if m.formatos else "listicle")
    if formato not in m.formatos:
        raise ValueError(f"La marca {m.slug} no tiene habilitado el formato "
                         f"{formato!r} (permitidos: {m.formatos})")
    catalogo = marcas_mod.estilos_de(m)
    estilo = estilo or (next(iter(m.estilos)) if m.estilos else "tiktok_bold")
    if estilo not in catalogo:
        raise ValueError(f"Estilo {estilo!r} no existe para {m.slug} "
                         f"(disponibles: {sorted(catalogo)})")
    fuentes = tuple(fuentes) if fuentes else tuple(fuentes_mod.orden_imagen(cx, m))
    prompt_formato = m.prompts.get("por_formato", {}).get(formato)
    contexto_full = "\n\n".join(x for x in (m.voz, prompt_formato, contexto) if x) or None

    _reportar(10, "guion")
    guion = slideshow_script.generar_guion(tema, formato=formato,
                                           n_slides=n_slides,
                                           contexto=contexto_full)
    advertencias: list[str] = []
    if hechos is not None:
        fuera = cifras.cifras_fuera(cifras.textos_de_guion(guion), hechos)
        if fuera:
            _reportar(25, "regenerando: cifras fuera de facts")
            guion = slideshow_script.generar_guion(
                tema, formato=formato, n_slides=n_slides, contexto=contexto_full,
                feedback=("Estas cifras NO están en los datos verificados y no "
                          f"pueden aparecer: {', '.join(fuera)}. Cita solo cifras "
                          "de FACTS, tal cual; si no hay cifra, no pongas número."))
            fuera = cifras.cifras_fuera(cifras.textos_de_guion(guion), hechos)
            if fuera:
                raise CifrasFueraDeFacts(
                    f"cifras fuera de facts tras regenerar, se descarta: {fuera}")
        advertencias = cifras.menciones_no_verificadas(
            cifras.textos_de_guion(guion), hechos, no_verificados)
    hints = [sl["image_hint"] for sl in guion["slides"]]
    _reportar(40, "imágenes")
    providers = image_sources.providers_default(
        cx, slug=m.slug, creds=config.account_creds(m.slug))
    orden_fuentes = list(fuentes)
    if imagenes_preferidas:
        providers = {**providers, "entidad": image_sources.ListaProvider(imagenes_preferidas)}
        # Solo fotos del item: una foto de otro lugar en la ficha de una
        # propiedad engaña. Si faltan, se repiten las del item.
        orden_fuentes = ["entidad"]
    imagenes = image_sources.resolver(
        hints, orden_fuentes, cx=cx, slug=m.slug, providers=providers)
    if imagenes_preferidas:
        propias = [i for i in imagenes if i is not None]
        if propias:
            imagenes = [i if i is not None else propias[k % len(propias)]
                        for k, i in enumerate(imagenes)]
    sin_imagen = sum(1 for i in imagenes if i is None)
    if sin_imagen:
        print(f"[slideshow] {sin_imagen}/{len(imagenes)} slides sin imagen "
              "(fondo sólido)")
    brief = {"tema": tema, "formato": formato, "estilo": estilo,
             "fuentes": list(fuentes), "n_slides": n_slides,
             "contexto": contexto, "aspect": aspect, "marca": m.slug,
             "notificar_telegram": notificar_telegram}
    if receta or entity_id is not None:
        brief.update({"receta": receta, "entity_id": entity_id,
                      "advertencias": advertencias, **(extra_brief or {})})
    show = slideshow_compile.compilar(guion, estilo=estilo, imagenes=imagenes,
                                      aspect_ratio=aspect, brief=brief,
                                      formato=formato, account_slug=m.slug,
                                      estilos=catalogo)
    errores = slideshow_model.validar(show)
    if errores:
        raise RuntimeError(f"Contrato inválido, no se encola: {errores}")

    _reportar(60, "render")
    pngs = []
    for i in range(len(show.slides)):
        ctx = slideshow_compile.contexto_slide(show, i)
        pngs.append(compose.render_card("slide.html", ctx, prefix=f"slide{i}"))
    if dry_run:
        print("[slideshow] dry-run, PNGs en:")
        for p in pngs:
            print(f"  {p}")
        return None

    _reportar(85, "subiendo")
    ts = int(time.time())
    urls = [host.upload(str(p), public_id=f"ss{ts}_{i}")
            for i, p in enumerate(pngs)]

    caption_extra = m.prompts.get("caption_extra")
    caption_final = "\n\n".join(x for x in (show.caption, caption_extra) if x)
    hashtags = m.prompts.get("hashtags")
    if hashtags:
        caption_final = "\n".join(x for x in (caption_final, " ".join(hashtags)) if x)
    show.caption = caption_final

    qid = approval.encolar_pendiente(
        cx, tipo="slideshow", caption=show.caption,
        imagen_url=json.dumps(urls), template=estilo,
        tema_semilla=f"slideshow {formato}: {tema}", account_id=m.id)
    campos_extra = {"creado_por": creado_por, "origen": "api"} if creado_por is not None else {}
    if entity_id is not None:
        campos_extra["entity_id"] = entity_id
    if receta:
        # Marca de receta para el cooldown del planeador (src/recetas.py).
        campos_extra["formato_patron"] = f"receta:{receta}"
    db.update(cx, "content_queue", qid,
              slideshow_json=slideshow_model.a_json(show), **campos_extra)
    if topic_id is not None:
        try:
            db.update(cx, "topic_suggestions", topic_id, usado_en_queue_id=qid)
        except ValueError:
            pass
    if notificar_telegram:
        caption_tg = show.caption
        if advertencias:
            caption_tg = ("⚠️ Menciona datos SIN VERIFICAR: "
                          f"{', '.join(advertencias)}\n\n{show.caption}")
        approval.enviar_a_telegram(caption_tg, json.dumps(urls), qid,
                                   account_slug=m.slug, cx=cx)
        if aspect == "9:16":
            zip_916(pngs, qid, m.slug)
        print(f"[slideshow] q{qid} ({m.slug}) enviado a Telegram ({len(urls)} slides)")
    else:
        # Piezas de un plan (spec 2026-08-28): la curación vive en el portal.
        print(f"[slideshow] q{qid} ({m.slug}) encolado sin Telegram ({len(urls)} slides)")
    _reportar(100, "listo")
    return qid


def zip_916(pngs, qid: int, slug: str) -> str | None:
    """Empaqueta los PNG 9:16 (TikTok, temporal) y los manda al Telegram de la
    marca como documento. Devuelve la ruta del ZIP; nunca levanta."""
    import zipfile
    from pathlib import Path

    from src import avisos_marca
    try:
        destino = config.BASE_DIR / "data" / "exports" / f"{slug}_q{qid}_9x16.zip"
        destino.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            for i, p in enumerate(pngs, 1):
                z.write(p, arcname=f"{slug}_q{qid}_{i:02d}.png")
        avisos_marca.enviar_documento(
            slug, destino, caption=f"q{qid} · PNG 9:16 para TikTok (subir a mano)")
        return str(destino)
    except Exception as e:  # noqa: BLE001 — el ZIP es un extra, no tumba la pieza
        print(f"[slideshow] ZIP 9:16 de q{qid} falló: {e}")
        return None


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera un slideshow y lo manda a aprobación")
    ap.add_argument("--tema", required=True)
    ap.add_argument("--marca", default="gdlscene")
    ap.add_argument("--formato", default=None)
    ap.add_argument("--estilo", default=None)
    ap.add_argument("--fuentes", default=None,
                    help="orden de fuentes separado por comas: banco,covers,pexels,pinterest"
                         " (default: perfil de la marca)")
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
        fuentes = (tuple(f.strip() for f in args.fuentes.split(",") if f.strip())
                   if args.fuentes else None)
        generar(cx, args.tema, marca=args.marca, formato=args.formato,
                estilo=args.estilo, fuentes=fuentes,
                n_slides=args.n_slides, aspect=args.aspect,
                contexto=args.contexto, dry_run=args.dry_run)
    finally:
        cx.close()


if __name__ == "__main__":
    main()
