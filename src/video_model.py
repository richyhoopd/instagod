"""Contrato del motor de video: preset de marca + pieza renderizable.

Mismo rol que `slideshow_model` para carruseles: aquí vive la FORMA de los
datos (preset de la marca + guion de la pieza) y su validación, nada de
render ni de red. `video_render` consume estos objetos; `generate_video` los
arma y los guarda en `content_queue.video_json`.

Dos niveles:
  - `VideoPreset`: configuración estable de la marca (voz, personaje, CTA,
    estética de subtítulos y tarjeta). Vive en `accounts.video_json`.
  - `Video`: la pieza concreta (título + cuerpo narrado + semilla de fondos +
    el preset con el que se renderizó). Vive en `content_queue.video_json`.

Un preset a medias NO revienta: `preset_desde` cae a defaults campo por campo
(mismo criterio tolerante que `marcas._json_o`), porque un JSON mal editado en
el portal no debe impedir generar contenido.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# Lienzo vertical de reel. IG exige 9:16 para Reels; no es configurable por
# marca a propósito (cambiarlo invalida todas las coordenadas del render).
W, H, FPS = 1080, 1920, 30

# Fondos disponibles en `video_render.placas`. El preset elige el subconjunto
# y el orden sale de la semilla de la pieza (reproducible).
FONDOS = ("mosaico", "cara_gigante", "deep_fried", "espejo", "duotono",
          "enjambre", "invertido")

# Voces de edge-tts probadas en español MX. El preset puede nombrar cualquier
# voz de edge-tts; esta tupla es solo el catálogo que ofrece el portal.
VOCES = ("es-MX-JorgeNeural", "es-MX-DaliaNeural", "es-MX-CecilioNeural",
         "es-MX-RenataNeural", "es-ES-AlvaroNeural")

_MAX_PALABRAS_CUERPO = 400
_MIN_PALABRAS_CUERPO = 20


@dataclass
class VideoPreset:
    """Cómo suena y se ve el video de ESTA marca.

    `personaje_path`: PNG con transparencia (el narrador que rebota abajo y de
    paso genera los fondos). Relativo a `config.BASE_DIR`, igual que
    `accounts.logo_path`. Sin personaje el render sigue: solo omite el
    narrador y usa fondos de color plano.
    """
    voz: str = "es-MX-JorgeNeural"
    rate: str = "+22%"
    pitch: str = "-8Hz"
    # Procesado de voz: tono/formantes al 86 % (susurro ronco de proximidad).
    # 1.0 = voz limpia de edge-tts, sin cadena de efectos.
    voz_formantes: float = 0.86
    voz_respiracion: float = 0.02
    personaje_path: str | None = None
    etiqueta_tarjeta: str = ""
    autor_tarjeta: str = "anónimo · hace 3 h"
    cta_hablado: str = ""
    cta_texto: str = ""
    cta_marca: str = ""
    color_acento: str = "#FFE600"
    color_fondo: str = "#3B2414"
    fondos: list[str] = field(default_factory=lambda: list(FONDOS))
    # Segundos mínimos que dura un fondo antes de poder cambiar (los cortes
    # caen en fin de frase, pero sin piso el video parpadea).
    fondo_min_s: float = 2.5
    palabras_subtitulo: int = 3
    lufs: float = -14.0
    # Largo objetivo del guion (palabras) y techo duro de duración. 220
    # palabras a rate +22% dan ~84 s: justo al filo de los 90 s que IG
    # recomienda para Reels, así que el default baja a 170 (~65 s).
    palabras_min: int = 90
    palabras_max: int = 170
    max_duracion_s: float = 90.0


@dataclass
class Video:
    """La pieza: lo que se narra, con qué preset y con qué semilla de fondos."""
    titulo: str
    cuerpo: str
    preset: VideoPreset
    semilla: str = ""
    fuente_url: str | None = None
    caption: str = ""
    # Lo llena `generate_video` tras renderizar (duración real medida con
    # ffprobe y ruta local del mp4); el portal los muestra sin re-sondear.
    duracion_s: float | None = None
    video_path: str | None = None


def preset_desde(crudo: "str | dict | VideoPreset | None") -> VideoPreset:
    """`accounts.video_json` → VideoPreset, tolerante campo por campo.

    JSON malformado, tipo equivocado o clave desconocida → se ignora ese
    campo y queda el default (nunca lanza): un preset mal editado en el
    portal no debe tumbar la generación, igual que en `marcas._json_o`.
    """
    if isinstance(crudo, VideoPreset):
        return crudo
    datos: dict = {}
    if isinstance(crudo, dict):
        datos = crudo
    elif crudo:
        try:
            parsed = json.loads(crudo)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            datos = parsed

    preset = VideoPreset()
    for campo, default in asdict(preset).items():
        valor = datos.get(campo)
        if valor is None:
            continue
        if campo == "fondos":
            validos = [f for f in valor if f in FONDOS] if isinstance(valor, list) else []
            if validos:
                preset.fondos = validos
            continue
        # El tipo lo manda el DEFAULT del campo, no el valor recibido: así un
        # "lufs": "-14" (string) se descarta en vez de dejar un str donde el
        # render espera float y reventar mucho después, en ffmpeg.
        if isinstance(default, bool):
            if isinstance(valor, bool):
                setattr(preset, campo, valor)
        elif isinstance(default, float):
            if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                setattr(preset, campo, float(valor))
        elif isinstance(default, int):
            if isinstance(valor, int) and not isinstance(valor, bool):
                setattr(preset, campo, valor)
        elif isinstance(valor, str):
            # Campos de texto (voz, colores, CTA) y los `str | None` cuyo
            # default es None: solo se aceptan strings.
            setattr(preset, campo, valor)
    return preset


def validar(video: Video) -> list[str]:
    """Problemas que impiden renderizar/publicar. Lista vacía = contrato OK.

    Se valida ANTES de gastar TTS y render (minutos de CPU) y antes de
    encolar: una pieza inválida nunca debe llegar a `content_queue`.
    """
    errores: list[str] = []
    if not video.titulo.strip():
        errores.append("titulo vacío")
    palabras = len(video.cuerpo.split())
    if palabras < _MIN_PALABRAS_CUERPO:
        errores.append(f"cuerpo muy corto ({palabras} palabras, mínimo {_MIN_PALABRAS_CUERPO})")
    if palabras > _MAX_PALABRAS_CUERPO:
        errores.append(f"cuerpo muy largo ({palabras} palabras, máximo {_MAX_PALABRAS_CUERPO})")
    p = video.preset
    if not p.voz.strip():
        errores.append("preset sin voz")
    if not p.fondos:
        errores.append("preset sin fondos")
    if p.palabras_subtitulo < 1 or p.palabras_subtitulo > 6:
        errores.append("palabras_subtitulo fuera de 1..6")
    if p.fondo_min_s <= 0:
        errores.append("fondo_min_s debe ser > 0")
    if not 0.5 <= p.voz_formantes <= 1.5:
        errores.append("voz_formantes fuera de 0.5..1.5")
    if p.palabras_min < 20 or p.palabras_max > _MAX_PALABRAS_CUERPO or p.palabras_min >= p.palabras_max:
        errores.append("palabras_min/palabras_max incoherentes")
    if p.max_duracion_s <= 0:
        errores.append("max_duracion_s debe ser > 0")
    # La duración solo se conoce DESPUÉS de renderizar: `generate_video`
    # re-valida con ella puesta para no subir un reel más largo del tope.
    if video.duracion_s is not None and video.duracion_s > p.max_duracion_s:
        errores.append(f"video de {video.duracion_s:.0f}s, máximo {p.max_duracion_s:.0f}s")
    return errores


def a_json(video: Video) -> str:
    return json.dumps(asdict(video), ensure_ascii=False)


def desde_json(crudo: str) -> Video:
    """JSON de `content_queue.video_json` → Video (con su preset)."""
    datos = json.loads(crudo)
    preset = preset_desde(datos.get("preset"))
    campos = {k: v for k, v in datos.items()
              if k in Video.__dataclass_fields__ and k != "preset"}
    return Video(preset=preset, **campos)
