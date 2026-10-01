"""Render del reel narrado: texto -> mp4 vertical 1080x1920.

Sin API keys: voz con edge-tts (gratis), tiempos por palabra del propio TTS
(no hace falta Whisper), tarjetas y subtítulos con Pillow, composición con
ffmpeg. Deliberadamente NO usa libass ni drawtext: el ffmpeg de Homebrew no
los trae, así que todo el texto entra como secuencia de PNG.

Tipografías: las del repo (`templates/assets/fonts`), no las de macOS — el
prototipo usaba Impact/Arial Black del sistema y eso no existe en el servidor.

Este módulo no sabe nada de la DB ni de Instagram: recibe un `video_model.Video`
y escribe un archivo. Lo orquesta `generate_video`.
"""
from __future__ import annotations

import asyncio
import random
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

import config
from src.video_model import FPS, H, W, Video, VideoPreset

FONTS_DIR = config.BASE_DIR / "templates" / "assets" / "fonts"
# Anton sustituye a Impact (condensada, muy pesada); Poppins-Bold a Arial Black.
F_DISPLAY = FONTS_DIR / "Anton-Regular.ttf"
F_UI = FONTS_DIR / "Poppins-Bold.ttf"

# Silencio entre las tres partes narradas (título / cuerpo / CTA).
_GAP_S = 0.35
# Colchón al final para que el outro no corte en seco.
_COLA_S = 1.2
# Tope de bitrate: el grano por cuadro mata la compresión y sin tope un reel
# de 60 s salía en ~700 MB con crf 20. Con 8M quedaba en ~60 MB (8 Mbps) —
# muy por encima de lo que Instagram conserva (recomprime a ~4 Mbps) y lento
# de subir. 4.5M da el mismo resultado visible en ~35 MB.
_MAXRATE, _BUFSIZE = "4500k", "9000k"


class FaltaEdgeTTS(RuntimeError):
    """edge-tts no está instalado. Mensaje accionable en vez de ImportError."""


def _hex_a_rgb(valor: str, default: tuple[int, int, int]) -> tuple[int, int, int]:
    """'#RRGGBB' → (r,g,b). Valor inválido → `default` (nunca lanza: el color
    viene de un preset editable en el portal)."""
    crudo = (valor or "").strip().lstrip("#")
    if len(crudo) != 6:
        return default
    try:
        return tuple(int(crudo[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _wrap(draw: ImageDraw.ImageDraw, texto: str, fnt, max_w: int) -> list[str]:
    lineas: list[str] = []
    cur = ""
    for palabra in texto.split():
        test = f"{cur} {palabra}".strip()
        if draw.textlength(test, font=fnt) <= max_w or not cur:
            cur = test
        else:
            lineas.append(cur)
            cur = palabra
    lineas.append(cur)
    return lineas


# --------------------------------------------------------------------------- #
# Voz
# --------------------------------------------------------------------------- #

async def _tts(texto: str, preset: VideoPreset, out: Path) -> list[tuple[float, float, str]]:
    """Genera el mp3 y devuelve [(inicio_s, fin_s, palabra)] del propio TTS."""
    try:
        import edge_tts
    except ModuleNotFoundError as exc:  # pragma: no cover - entorno
        raise FaltaEdgeTTS(
            "Falta edge-tts (motor de voz): pip install -r requirements.txt"
        ) from exc

    comm = edge_tts.Communicate(texto, preset.voz, rate=preset.rate,
                                pitch=preset.pitch, boundary="WordBoundary")
    palabras: list[tuple[float, float, str]] = []
    with out.open("wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                ini = chunk["offset"] / 1e7
                palabras.append((ini, ini + chunk["duration"] / 1e7, chunk["text"]))
    return con_puntuacion(texto, palabras)


def con_puntuacion(texto: str, palabras: list[tuple[float, float, str]]):
    """El TTS devuelve palabras SIN puntuación; se recupera del texto original.

    Sin esto los bloques de subtítulo no cortan en fin de frase (y los fondos,
    que cambian en los puntos, tampoco).
    """
    salida, cur, low = [], 0, texto.lower()
    for ini, fin, palabra in palabras:
        i = low.find(palabra.lower(), cur)
        if i < 0:
            salida.append((ini, fin, palabra))
            continue
        j = i + len(palabra)
        while j < len(texto) and texto[j] in ".,!?;:…\"')":
            j += 1
        salida.append((ini, fin, texto[i:j]))
        cur = j
    return salida


def duracion(path: Path) -> float:
    """Duración en segundos vía ffprobe."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(out)


def bloques(palabras: list[tuple[float, float, str]], max_palabras: int = 3):
    """Agrupa palabras en bloques de subtítulo que cortan en puntuación."""
    bloque: list[tuple[float, float, str]] = []
    for w in palabras:
        bloque.append(w)
        if len(bloque) >= max_palabras or re.search(r"[.,!?;:]$", w[2]):
            yield bloque
            bloque = []
    if bloque:
        yield bloque


def cortes_de_fondo(palabras: list[tuple[float, float, str]],
                    min_s: float) -> list[float]:
    """Instantes donde cambia el fondo: fin de frase, con piso de `min_s`."""
    cortes = [0.0]
    for _, fin, texto in palabras:
        if re.search(r"[.!?…]$", texto) and fin - cortes[-1] >= min_s:
            cortes.append(fin)
    return cortes


# --------------------------------------------------------------------------- #
# Tarjetas y subtítulos (Pillow)
# --------------------------------------------------------------------------- #

def tarjeta_titulo(titulo: str, preset: VideoPreset, avatar: Path | None,
                   out: Path) -> None:
    """Tarjeta tipo post de foro: etiqueta, autor, título y votos."""
    acento = _hex_a_rgb(preset.color_acento, (255, 230, 0))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f_titulo = _font(F_UI, 58)
    f_meta = _font(F_UI, 30)
    pad, card_w = 48, W - 120
    lineas = _wrap(d, titulo, f_titulo, card_w - 2 * pad)
    card_h = 190 + len(lineas) * 80 + 110
    x0, y0 = 60, 330
    d.rounded_rectangle((x0, y0, x0 + card_w, y0 + card_h), 36,
                        fill=(255, 255, 255, 255))

    if avatar and avatar.exists():
        cara = ImageOps.fit(Image.open(avatar).convert("RGBA"), (110, 110),
                            centering=(0.5, 0.3))
        mask = Image.new("L", (110, 110), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 110, 110), fill=255)
        fondo = Image.new("RGBA", (110, 110), acento + (255,))
        fondo.paste(cara, (0, 0), cara)
        img.paste(fondo, (x0 + pad, y0 + 44), mask)
    tx = x0 + pad + (135 if avatar and avatar.exists() else 0)
    d.text((tx, y0 + 52), preset.etiqueta_tarjeta, font=f_meta, fill=(20, 20, 20))
    d.text((tx, y0 + 98), preset.autor_tarjeta, font=_font(F_UI, 24),
           fill=(130, 130, 130))

    y = y0 + 190
    for linea in lineas:
        d.text((x0 + pad, y), linea, font=f_titulo, fill=(15, 15, 15))
        y += 80
    # Votos/comentarios decorativos: fijos por semilla en `render` (el rng que
    # entra aquí ya viene sembrado con el nombre de la pieza).
    img.save(out)


def tarjeta_subtitulo(palabras: list[str], actual: int, preset: VideoPreset,
                      out: Path) -> None:
    """Bloque de 1-3 palabras con borde negro; la palabra actual en el acento."""
    acento = _hex_a_rgb(preset.color_acento, (255, 230, 0))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    mayus = [w.upper() for w in palabras]
    size = 132
    fnt = _font(F_DISPLAY, size)
    while d.textlength(" ".join(mayus), font=fnt) > W - 120 and size > 70:
        size -= 6
        fnt = _font(F_DISPLAY, size)
    total = d.textlength(" ".join(mayus), font=fnt)
    x, y = (W - total) / 2, 760
    for i, w in enumerate(mayus):
        color = acento if i == actual else (255, 255, 255)
        d.text((x, y), w, font=fnt, fill=color, stroke_width=12,
               stroke_fill=(0, 0, 0))
        x += d.textlength(w + " ", font=fnt)
    img.save(out)


def tarjeta_outro(preset: VideoPreset, out: Path) -> None:
    acento = _hex_a_rgb(preset.color_acento, (255, 230, 0))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for texto, size, y, color in ((preset.cta_marca, 150, 560, acento),
                                  (preset.cta_texto, 60, 760, (255, 255, 255))):
        if not texto:
            continue
        fnt = _font(F_DISPLAY, size)
        tw = d.textlength(texto, font=fnt)
        d.text(((W - tw) / 2, y), texto, font=fnt, fill=color,
               stroke_width=10, stroke_fill=(0, 0, 0))
    img.save(out)


# --------------------------------------------------------------------------- #
# Fondos
# --------------------------------------------------------------------------- #

def placas(personaje: Path | None, preset: VideoPreset, rng: random.Random,
           out_dir: Path) -> list[Path]:
    """Fondos a partir del personaje de la marca, en orden aleatorio sembrado.

    Sin personaje: una sola placa de color plano (el reel sigue saliendo).
    Todas se oscurecen al 55 % para que el subtítulo blanco siga legible.
    """
    base = _hex_a_rgb(preset.color_fondo, (59, 36, 20))
    acento = _hex_a_rgb(preset.color_acento, (255, 214, 0))

    def guardar(img: Image.Image, nombre: str) -> Path:
        img = ImageEnhance.Brightness(img.convert("RGB")).enhance(0.55)
        path = out_dir / f"placa-{nombre}.png"
        img.save(path)
        return path

    if personaje is None or not personaje.exists():
        return [guardar(Image.new("RGB", (W, H), base), "plano")]

    bicho = Image.open(personaje).convert("RGBA")
    ratio = bicho.height / bicho.width

    def mosaico() -> Image.Image:
        img = Image.new("RGBA", (W, H), acento + (255,))
        chico = bicho.resize((180, int(180 * ratio)))
        for fila, y in enumerate(range(-60, H, 240)):
            for col, x in enumerate(range(-40 + (fila % 2) * 90, W, 200)):
                b = ImageOps.mirror(chico) if (fila + col) % 2 else chico
                img.alpha_composite(b.rotate(rng.uniform(-25, 25), expand=True), (x, y))
        return img

    def cara_gigante() -> Image.Image:
        w, h = bicho.size
        cara = bicho.crop((int(w * 0.1), int(h * 0.17), int(w * 0.9), int(h * 0.57)))
        return ImageOps.fit(cara, (W, H)).filter(ImageFilter.GaussianBlur(3))

    def deep_fried() -> Image.Image:
        img = ImageOps.fit(bicho, (W, H), centering=(0.5, 0.35)).convert("RGB")
        img = ImageEnhance.Color(img).enhance(3.5)
        img = ImageEnhance.Contrast(img).enhance(2.2)
        img = ImageOps.posterize(
            img.filter(ImageFilter.SHARPEN).filter(ImageFilter.SHARPEN), 3)
        tmp = out_dir / "fried.jpg"
        img.resize((W // 4, H // 4)).save(tmp, quality=6)
        return Image.open(tmp).resize((W, H), Image.NEAREST)

    def espejo() -> Image.Image:
        mitad = ImageOps.fit(bicho, (W // 2, H // 2), centering=(0.5, 0.3))
        img = Image.new("RGBA", (W, H), base + (255,))
        img.alpha_composite(mitad, (0, 0))
        img.alpha_composite(ImageOps.mirror(mitad), (W // 2, 0))
        img.alpha_composite(ImageOps.flip(mitad), (0, H // 2))
        img.alpha_composite(ImageOps.flip(ImageOps.mirror(mitad)), (W // 2, H // 2))
        return img

    def duotono() -> Image.Image:
        gris = ImageOps.grayscale(ImageOps.fit(bicho, (W, H), centering=(0.5, 0.4)))
        return ImageOps.colorize(gris, black=base, white=acento)

    def enjambre() -> Image.Image:
        img = Image.new("RGBA", (W, H), base + (255,))
        for _ in range(28):
            size = rng.randint(120, 420)
            b = bicho.resize((size, int(size * ratio)))
            if rng.random() < 0.5:
                b = ImageOps.mirror(b)
            b = b.rotate(rng.uniform(-180, 180), expand=True)
            img.alpha_composite(b, (rng.randint(-150, W - 100), rng.randint(-150, H - 100)))
        return img

    def invertido() -> Image.Image:
        ajustado = ImageOps.fit(bicho, (W, H), centering=(0.5, 0.3))
        img = Image.new("RGB", (W, H), base)
        img.paste(ajustado, (0, 0), ajustado)
        return ImageOps.invert(img)

    disponibles = {"mosaico": mosaico, "cara_gigante": cara_gigante,
                   "deep_fried": deep_fried, "espejo": espejo,
                   "duotono": duotono, "enjambre": enjambre,
                   "invertido": invertido}
    elegidos = [(n, disponibles[n]) for n in preset.fondos if n in disponibles]
    if not elegidos:
        return [guardar(Image.new("RGB", (W, H), base), "plano")]
    rng.shuffle(elegidos)
    return [guardar(fn(), nombre) for nombre, fn in elegidos]


# --------------------------------------------------------------------------- #
# Composición
# --------------------------------------------------------------------------- #

def _cadena_voz(preset: VideoPreset, n_audios: int) -> list[str]:
    """filter_complex de audio: concat de partes + color de voz + loudnorm.

    `voz_formantes` baja tono y formantes SIN cambiar la duración (asetrate +
    atempo inverso): los tiempos por palabra del TTS siguen siendo válidos,
    que es lo que sincroniza los subtítulos.
    """
    filt = [f"[{i}:a]apad=pad_dur={_GAP_S}[a{i}]" for i in range(n_audios)]
    filt.append("".join(f"[a{i}]" for i in range(n_audios))
                + f"concat=n={n_audios}:v=0:a=1[dry]")
    k = preset.voz_formantes
    if abs(k - 1.0) < 0.01 and preset.voz_respiracion <= 0:
        filt.append(f"[dry]loudnorm=I={preset.lufs}:TP=-1.5:LRA=11[out]")
        return filt
    filt.append(
        f"[dry]aresample=44100,asetrate=44100*{k},aresample=44100,atempo=1/{k},"
        "highpass=f=60,equalizer=f=140:t=q:w=1:g=6,"
        "equalizer=f=3000:t=q:w=1.5:g=-4,equalizer=f=7500:t=q:w=2:g=5,"
        "acompressor=threshold=0.05:ratio=8:attack=5:release=120:makeup=4,"
        "aecho=0.8:0.5:35:0.18[wet]"
    )
    if preset.voz_respiracion > 0:
        filt.append(f"anoisesrc=c=brown:a={preset.voz_respiracion}:r=44100[aire]")
        filt.append("[wet][aire]amix=inputs=2:duration=first:weights=1 1,"
                    f"loudnorm=I={preset.lufs}:TP=-1.5:LRA=11[out]")
    else:
        filt.append(f"[wet]loudnorm=I={preset.lufs}:TP=-1.5:LRA=11[out]")
    return filt


def _secuencia(frames: list[tuple[Path, float]], total: float, dir_: Path) -> None:
    """Secuencia de PNGs a `FPS`: cada cuadro es un symlink al PNG vigente.

    Symlinks y no copias: un reel de 60 s son 1800 cuadros y copiar PNGs de
    1080x1920 llenaría el disco por pieza.
    """
    dir_.mkdir(parents=True, exist_ok=True)
    k = 0
    for f in range(int(total * FPS) + 1):
        t = f / FPS
        while k + 1 < len(frames) and frames[k + 1][1] <= t:
            k += 1
        (dir_ / f"{f:05d}.png").symlink_to(frames[k][0])


def render(video: Video, out: Path, *, personaje: Path | None = None,
           bg_video: Path | None = None, progreso=None) -> float:
    """Renderiza la pieza a `out` (mp4). Devuelve la duración real en segundos.

    `personaje`: PNG del narrador ya resuelto a ruta absoluta (el preset lo
    guarda relativo a BASE_DIR; resolverlo es tarea del caller).
    `bg_video`: fondo de video propio; si se da, reemplaza a las placas.
    `progreso`: callback `(pct, msg)` opcional, igual que en el motor de
    slideshows — para que `jobs.progresar` reporte avance sin acoplarse.
    """
    def _rep(pct: int, msg: str) -> None:
        if progreso is not None:
            progreso(pct, msg)

    preset = video.preset
    tmp = Path(tempfile.mkdtemp(prefix="instagod-video-"))
    rng = random.Random(video.semilla or video.titulo)

    # --- Voz de las tres partes, con su timeline absoluto ------------------
    _rep(15, "voz")
    partes = [("titulo", video.titulo), ("cuerpo", video.cuerpo)]
    if preset.cta_hablado:
        partes.append(("cta", preset.cta_hablado))
    timeline, offset, audios = [], 0.0, []
    for nombre, texto in partes:
        mp3 = tmp / f"{nombre}.mp3"
        palabras = asyncio.run(_tts(texto, preset, mp3))
        timeline.append((nombre, offset,
                         [(s + offset, e + offset, t) for s, e, t in palabras]))
        audios.append(mp3)
        offset += duracion(mp3) + _GAP_S
    total = offset + _COLA_S

    # --- Pista de imágenes -------------------------------------------------
    _rep(45, "subtítulos")
    tarjeta_titulo(video.titulo, preset, personaje, tmp / "titulo.png")
    tarjeta_outro(preset, tmp / "outro.png")

    frames: list[tuple[Path, float]] = [(tmp / "titulo.png", timeline[1][1])]
    palabras_cuerpo = timeline[1][2]
    n = 0
    for bloque in bloques(palabras_cuerpo, preset.palabras_subtitulo):
        texto = [t for _, _, t in bloque]
        for i, (s, _e, _t) in enumerate(bloque):
            png = tmp / f"sub{n:04d}.png"
            tarjeta_subtitulo(texto, i, preset, png)
            frames.append((png, s))
            n += 1
    if len(timeline) > 2:
        frames.append((tmp / "outro.png", timeline[2][1]))
    else:
        frames.append((tmp / "outro.png", offset - _GAP_S))
    _secuencia(frames, total, tmp / "seq")

    # --- Fondos ------------------------------------------------------------
    if bg_video is None:
        _rep(60, "fondos")
        plates = placas(personaje, preset, rng, tmp)
        cortes = cortes_de_fondo(palabras_cuerpo, preset.fondo_min_s)
        bg_frames = [(plates[i % len(plates)], t) for i, t in enumerate(cortes)]
        _secuencia(bg_frames, total, tmp / "bgseq")

    # --- Audio -------------------------------------------------------------
    _rep(70, "audio")
    audio = tmp / "voz.wav"
    inputs: list[str] = []
    for mp3 in audios:
        inputs += ["-i", str(mp3)]
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs,
                    "-filter_complex", ";".join(_cadena_voz(preset, len(audios))),
                    "-map", "[out]", "-ar", "44100", str(audio)], check=True)

    # --- Video -------------------------------------------------------------
    _rep(80, "render")
    if bg_video is not None:
        bg_in = ["-stream_loop", "-1", "-i", str(bg_video)]
        bg_f = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},fps={FPS},setsar=1[bg]")
    else:
        bg_in = ["-framerate", str(FPS), "-i", str(tmp / "bgseq" / "%05d.png")]
        bg_f = "[0:v]noise=alls=12:allf=t,format=yuv420p,setsar=1[bg]"

    inputs_v = [*bg_in, "-framerate", str(FPS), "-i", str(tmp / "seq" / "%05d.png")]
    if personaje is not None and personaje.exists():
        # El narrador abajo al centro: rebota y se ladea mientras habla.
        inputs_v += ["-loop", "1", "-i", str(personaje)]
        filt = ";".join([
            bg_f,
            "[2:v]scale=560:-1,rotate='0.06*sin(2*PI*t*2.2)':c=none:"
            "ow=rotw(0.08):oh=roth(0.08)[bicho]",
            "[1:v]format=rgba[txt]",
            "[bg][bicho]overlay=x='(W-w)/2':"
            "y='H-h-40-abs(28*sin(2*PI*t*3.1))':shortest=0[b1]",
            "[b1][txt]overlay=0:0:eof_action=repeat[v]",
        ])
        mapa_audio = "3:a"
    else:
        filt = ";".join([bg_f, "[1:v]format=rgba[txt]",
                         "[bg][txt]overlay=0:0:eof_action=repeat[v]"])
        mapa_audio = "2:a"

    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", *inputs_v, "-i", str(audio),
        "-filter_complex", filt, "-map", "[v]", "-map", mapa_audio,
        "-t", f"{total:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-maxrate", _MAXRATE, "-bufsize", _BUFSIZE, "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
    ], check=True)
    _rep(90, "listo")
    return duracion(out)
