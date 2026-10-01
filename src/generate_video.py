"""Entrypoint del motor de video (reels narrados, Proceso A no-bloqueante).

CLI/jobs → historia (topic_suggestions o texto a mano) → guion (LLM) →
voz + subtítulos + fondos (`video_render`) → Cloudinary → encolar + Telegram.
El approval-daemon resuelve la aprobación; `publisher` publica el Reel.

Gemelo de `generate_slideshow` para video: mismas piezas (marca, approval,
host, content_queue) y mismo contrato de `progreso`, pero la pieza es un mp4
en vez de una lista de PNGs.

Uso:
  python -m src.generate_video --marca shitbook --topic 42
  python -m src.generate_video --marca shitbook --titulo "..." --cuerpo-archivo h.txt
  python -m src.generate_video --marca shitbook --topic 42 --sin-llm --dry-run
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import config
from src import approval, db, host, video_model, video_render, video_script

OUT_DIR = config.BASE_DIR / "out"


def _historia_de_topic(cx, account_id: int, topic_id: int) -> dict:
    """Fila de `topic_suggestions` de ESTA cuenta, o ValueError.

    El filtro por `account_id` es aislamiento, no cosmética: sin él, un
    topic_id de otra marca se podría narrar y publicar en esta cuenta.
    """
    filas = db.rows(
        cx, "SELECT * FROM topic_suggestions WHERE id = ? AND account_id = ?",
        (topic_id, account_id))
    if not filas:
        raise ValueError(f"El tema {topic_id} no existe o no es de la cuenta {account_id}")
    return filas[0]


def _publicar_en_cola(cx, m, video, mp4: Path, *, ts: int,
                      topic_id: int | None = None,
                      creado_por: int | None = None,
                      notificar_telegram: bool = True,
                      reportar=lambda pct, msg: None) -> int:
    """Sube el mp4 a Cloudinary y lo deja en la cola de aprobación.

    Compartido por `generar` (render nuevo) e `importar` (mp4 ya hecho) para
    que una pieza importada sea indistinguible de una generada: mismo caption
    con extras de marca, mismo `video_json`, misma notificación.
    """
    reportar(92, "subiendo")
    url = host.upload_video(str(mp4), public_id=f"reel{ts}")

    caption_extra = m.prompts.get("caption_extra")
    caption_final = "\n\n".join(x for x in (video.caption, caption_extra) if x)
    hashtags = m.prompts.get("hashtags")
    if hashtags:
        caption_final = "\n".join(x for x in (caption_final, " ".join(hashtags)) if x)
    video.caption = caption_final

    qid = approval.encolar_pendiente(
        cx, tipo="video", caption=video.caption, imagen_url=url,
        tema_semilla=video.titulo, account_id=m.id)
    campos_extra = {"creado_por": creado_por, "origen": "api"} if creado_por is not None else {}
    db.update(cx, "content_queue", qid,
              video_json=video_model.a_json(video), **campos_extra)
    if topic_id is not None:
        try:
            db.update(cx, "topic_suggestions", topic_id, usado_en_queue_id=qid)
        except ValueError:
            pass
    if notificar_telegram:
        approval.enviar_a_telegram(video.caption, url, qid,
                                   account_slug=m.slug, cx=cx, es_video=True)
        print(f"[video] q{qid} ({m.slug}) enviado a Telegram "
              f"({video.duracion_s:.1f}s)")
    else:
        print(f"[video] q{qid} ({m.slug}) encolado sin Telegram")
    reportar(100, "listo")
    return qid


def generar(cx, *, marca: str = "shitbook", topic_id: int | None = None,
            titulo: str | None = None, cuerpo: str | None = None,
            usar_llm: bool = True, bg_video: str | None = None,
            dry_run: bool = False, progreso=None, creado_por: int | None = None,
            notificar_telegram: bool = True) -> int | None:
    """Genera el reel con el PRESET de la marca; queue_id o None en dry-run.

    La historia viene de `topic_id` (fuente de contenido) o de `titulo`+`cuerpo`
    (a mano). `usar_llm=False` narra la historia tal cual, sin reescribir.
    `progreso`: callback `(pct, msg)` opcional, igual que en slideshows.
    """
    from src import marcas as marcas_mod

    def _reportar(pct: int, msg: str) -> None:
        if progreso is not None:
            progreso(pct, msg)

    m = marcas_mod.cargar(cx, marca)
    preset = m.video

    _reportar(5, "historia")
    if topic_id is not None:
        fila = _historia_de_topic(cx, m.id, topic_id)
        titulo = titulo or fila["titulo"]
        cuerpo = cuerpo or (fila["resumen"] or "")
        fuente_url = fila.get("url")
    else:
        fuente_url = None
    if not (titulo and cuerpo):
        raise ValueError("Falta la historia: pasa --topic o --titulo + --cuerpo")

    _reportar(10, "guion")
    if usar_llm:
        guion = video_script.generar_guion(
            titulo, cuerpo, min_palabras=preset.palabras_min,
            max_palabras=preset.palabras_max,
            contexto=m.prompts.get("caption_extra") or None)
    else:
        guion = video_script.guion_directo(titulo, cuerpo)

    video = video_model.Video(
        titulo=guion["titulo"], cuerpo=guion["cuerpo"], preset=preset,
        semilla=f"{m.slug}-{topic_id or int(time.time())}",
        fuente_url=fuente_url, caption=guion.get("caption") or "")

    # Validar ANTES del render: el TTS + ffmpeg son minutos de CPU, no se
    # gastan en una pieza que de todos modos no se puede encolar.
    errores = video_model.validar(video)
    if errores:
        raise ValueError(f"Contrato de video inválido: {'; '.join(errores)}")

    personaje = config._resolve(preset.personaje_path) if preset.personaje_path else None
    if personaje is not None and not personaje.exists():
        print(f"[video] personaje no encontrado en {personaje}, sigo sin él",
              file=sys.stderr)
        personaje = None

    OUT_DIR.mkdir(exist_ok=True)
    ts = int(time.time())
    mp4 = OUT_DIR / f"reel-{m.slug}-{ts}.mp4"
    _reportar(15, "render")
    video.duracion_s = video_render.render(
        video, mp4, personaje=personaje,
        bg_video=Path(bg_video) if bg_video else None,
        progreso=progreso)
    video.video_path = str(mp4)

    # Ahora sí se conoce la duración real: si el reel se pasó del tope de la
    # marca, se corta aquí y NO se sube ni se encola (IG recomienda ≤90 s y un
    # reel larguísimo se abandona a la mitad). El mp4 queda en `out/` para
    # inspeccionarlo.
    errores = video_model.validar(video)
    if errores:
        raise ValueError(f"Video renderizado fuera de contrato: {'; '.join(errores)} "
                         f"(archivo: {mp4})")

    if dry_run:
        print(f"[video] dry-run: {mp4} ({video.duracion_s:.1f}s)")
        return None

    return _publicar_en_cola(cx, m, video, mp4, ts=ts, topic_id=topic_id,
                             creado_por=creado_por,
                             notificar_telegram=notificar_telegram,
                             reportar=_reportar)


def importar(cx, ruta_mp4: str | Path, *, marca: str = "shitbook",
             titulo: str | None = None, cuerpo: str = "",
             caption: str = "", fuente_url: str | None = None,
             usar_llm: bool = True, creado_por: int | None = None,
             notificar_telegram: bool = False) -> int:
    """Encola un mp4 YA renderizado (fuera de instagod) como pieza de la marca.

    Para los reels del prototipo `shitbook-videos`: están hechos y aprobados a
    ojo, lo que falta es que vivan en la cola para poder calendarizarlos. No se
    re-renderiza ni se pasa por el LLM.

    El `cuerpo` es solo para el registro en `video_json` (de dónde salió la
    pieza); no se valida contra los topes de palabras del preset porque el
    audio ya está grabado y no se puede reescribir.
    """
    from src import marcas as marcas_mod

    mp4 = Path(ruta_mp4).expanduser().resolve()
    if not mp4.exists():
        raise FileNotFoundError(f"No existe el video: {mp4}")

    m = marcas_mod.cargar(cx, marca)
    if not caption and usar_llm and cuerpo:
        caption = video_script.generar_caption(
            titulo or mp4.stem, cuerpo,
            contexto=m.prompts.get("caption_extra") or None)
    video = video_model.Video(
        titulo=titulo or mp4.stem, cuerpo=cuerpo, preset=m.video,
        semilla=f"{m.slug}-import-{mp4.stem}", fuente_url=fuente_url,
        caption=caption, video_path=str(mp4),
        duracion_s=video_render.duracion(mp4))

    # Solo se exige lo que sigue siendo cierto de un mp4 ya hecho: que entre en
    # el tope de duración de la marca. Con el audio grabado no tiene sentido
    # juzgar el largo del guion.
    if video.duracion_s > m.video.max_duracion_s:
        raise ValueError(f"{mp4.name}: dura {video.duracion_s:.0f}s, el tope de "
                         f"{m.slug} es {m.video.max_duracion_s:.0f}s")

    return _publicar_en_cola(cx, m, video, mp4, ts=int(time.time()),
                             creado_por=creado_por,
                             notificar_telegram=notificar_telegram)


def _historia_hermana(mp4: Path) -> dict[str, str]:
    """Metadatos del .txt que acompaña al mp4 en el prototipo shitbook-videos.

    Formato: `TITLE: ...` / `SOURCE: url` / línea en blanco / historia. Busca
    `<mp4 sin extensión>.txt` junto al video y en `../stories/`. Si no hay
    archivo, devuelve {} y el llamador cae al nombre del archivo.
    """
    nombre = mp4.stem + ".txt"
    for candidato in (mp4.with_suffix(".txt"),
                      mp4.parent.parent / "stories" / nombre,
                      mp4.parent / "stories" / nombre):
        if candidato.exists():
            texto = candidato.read_text(encoding="utf-8")
            break
    else:
        return {}

    meta: dict[str, str] = {}
    cuerpo: list[str] = []
    for linea in texto.splitlines():
        if linea.startswith("TITLE:") and "titulo" not in meta:
            meta["titulo"] = linea[len("TITLE:"):].strip()
        elif linea.startswith("SOURCE:") and "url" not in meta:
            meta["url"] = linea[len("SOURCE:"):].strip()
        else:
            cuerpo.append(linea)
    meta["cuerpo"] = "\n".join(cuerpo).strip()
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description="Genera un reel narrado y lo manda a aprobación")
    ap.add_argument("--marca", default="shitbook")
    ap.add_argument("--topic", type=int, help="id de topic_suggestions con la historia")
    ap.add_argument("--titulo")
    ap.add_argument("--cuerpo", help="historia en línea (o usa --cuerpo-archivo)")
    ap.add_argument("--cuerpo-archivo", help="archivo .txt con la historia")
    ap.add_argument("--bg-video", help="mp4 de fondo en vez de las placas del personaje")
    ap.add_argument("--sin-llm", action="store_true",
                    help="narra la historia tal cual, sin reescribirla con el LLM")
    ap.add_argument("--dry-run", action="store_true",
                    help="renderiza el mp4 local y NO sube ni encola")
    ap.add_argument("--importar", nargs="+", metavar="MP4",
                    help="encola mp4 YA renderizados en vez de generar uno nuevo; "
                         "el título sale del TITLE: del .txt hermano o del nombre")
    ap.add_argument("--telegram", action="store_true",
                    help="con --importar: además notifica por Telegram")
    args = ap.parse_args()

    cuerpo = args.cuerpo
    if args.cuerpo_archivo:
        cuerpo = Path(args.cuerpo_archivo).read_text(encoding="utf-8")

    cx = db.connect()
    try:
        db.init_db(cx)
        if args.importar:
            for ruta in args.importar:
                mp4 = Path(ruta).expanduser()
                meta = _historia_hermana(mp4)
                try:
                    qid = importar(cx, mp4, marca=args.marca,
                                   titulo=meta.get("titulo"),
                                   cuerpo=meta.get("cuerpo", ""),
                                   fuente_url=meta.get("url"),
                                   usar_llm=not args.sin_llm,
                                   notificar_telegram=args.telegram)
                    print(f"[video] {mp4.name} -> q{qid}")
                except Exception as exc:  # noqa: BLE001 — un mp4 malo no corta el lote
                    print(f"[video] {mp4.name}: {exc}", file=sys.stderr)
            return
        generar(cx, marca=args.marca, topic_id=args.topic, titulo=args.titulo,
                cuerpo=cuerpo, usar_llm=not args.sin_llm, bg_video=args.bg_video,
                dry_run=args.dry_run,
                progreso=lambda pct, msg: print(f"[video] {pct}% {msg}"))
    finally:
        cx.close()


if __name__ == "__main__":
    main()
