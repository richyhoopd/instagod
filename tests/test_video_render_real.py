"""Render real del reel: TTS + ffmpeg producen un mp4 válido.

Marcado `lento`: llama a edge-tts (red) y corre ffmpeg. Es el único test que
prueba que el pipeline completo entrega un archivo reproducible — el resto de
la suite usa dobles.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from src import video_model, video_render
from src.video_model import Video, VideoPreset

pytestmark = pytest.mark.lento

_CUERPO = (
    "Mi vecino tocó la puerta a las tres de la mañana. "
    "Dijo que su perro había entrado a mi patio. "
    "Yo no tengo patio y tampoco tengo vecino con perro. "
    "Cerré la puerta y encendí todas las luces de la casa. "
    "Al día siguiente la puerta tenía rasguños por dentro. "
    "Nunca volví a abrir de noche y cambié la cerradura esa misma tarde."
)


def _ffprobe(path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
                    reason="requiere ffmpeg/ffprobe")
def test_render_produce_mp4_vertical_con_audio(tmp_path) -> None:
    import config
    personaje = config.BASE_DIR / "data/brands/shitbook/personaje.png"
    video = Video(
        titulo="Mi vecino tocó a las tres de la mañana",
        cuerpo=_CUERPO,
        preset=VideoPreset(cta_texto="sigue la historia",
                           cta_marca="@shit.book",
                           etiqueta_tarjeta="r/nosleep"),
        semilla="test-render-1")
    assert video_model.validar(video) == []

    salida = tmp_path / "reel.mp4"
    pasos: list[tuple[int, str]] = []
    dur = video_render.render(
        video, salida,
        personaje=personaje if personaje.exists() else None,
        progreso=lambda pct, msg: pasos.append((pct, msg)))

    assert salida.exists() and salida.stat().st_size > 50_000
    assert dur > 10, f"duración sospechosamente corta: {dur}s"
    # el callback de progreso avanza (lo consume la UI de jobs)
    assert pasos and pasos[-1][0] >= 90

    meta = _ffprobe(salida)
    v = next(s for s in meta["streams"] if s["codec_type"] == "video")
    a = next(s for s in meta["streams"] if s["codec_type"] == "audio")
    assert (v["width"], v["height"]) == (video_model.W, video_model.H)
    assert v["codec_name"] == "h264"
    assert a["codec_name"] == "aac"
    # duración declarada ≈ la medida (tolerancia de 1.5 s por el fade final)
    assert abs(float(meta["format"]["duration"]) - dur) < 1.5
