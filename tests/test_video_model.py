"""Contrato del motor de video: preset tolerante, validación y round-trip."""
from __future__ import annotations

import json

from src import video_model
from src.video_model import Video, VideoPreset


def _video(**kw) -> Video:
    datos: dict = dict(titulo="Mi vecino rompió la puerta",
                       cuerpo=" ".join(["palabra"] * 120), preset=VideoPreset())
    datos.update(kw)
    return Video(**datos)


def test_preset_desde_vacio_da_defaults() -> None:
    for crudo in (None, "", "{}", "no-es-json", "[1,2]", '"texto"'):
        preset = video_model.preset_desde(crudo)
        assert preset.voz == "es-MX-JorgeNeural"
        assert preset.fondos == list(video_model.FONDOS)


def test_preset_desde_pisa_solo_campos_validos() -> None:
    preset = video_model.preset_desde(json.dumps({
        "voz": "es-MX-DaliaNeural",
        "palabras_subtitulo": 2,
        "voz_formantes": 0.9,
        "fondos": ["mosaico", "inventado", "espejo"],
        "clave_desconocida": "x",
        "lufs": "no-es-numero",      # tipo equivocado → se ignora
    }))
    assert preset.voz == "es-MX-DaliaNeural"
    assert preset.palabras_subtitulo == 2
    assert preset.voz_formantes == 0.9
    # los fondos inexistentes se filtran, no revientan
    assert preset.fondos == ["mosaico", "espejo"]
    # un lufs de tipo equivocado deja el default, no un string
    assert preset.lufs == -14.0
    assert not hasattr(preset, "clave_desconocida")


def test_preset_desde_fondos_todos_invalidos_cae_al_default() -> None:
    preset = video_model.preset_desde({"fondos": ["inventado", "otro"]})
    assert preset.fondos == list(video_model.FONDOS)


def test_preset_desde_acepta_dict_y_preset() -> None:
    p = VideoPreset(voz="es-ES-AlvaroNeural")
    assert video_model.preset_desde(p) is p
    assert video_model.preset_desde({"voz": "es-ES-AlvaroNeural"}).voz == "es-ES-AlvaroNeural"


def test_validar_acepta_pieza_sana() -> None:
    assert video_model.validar(_video()) == []


def test_validar_rechaza_cuerpo_corto_y_largo() -> None:
    assert any("corto" in e for e in video_model.validar(_video(cuerpo="dos palabras")))
    largo = " ".join(["x"] * 500)
    assert any("largo" in e for e in video_model.validar(_video(cuerpo=largo)))


def test_validar_rechaza_titulo_vacio_y_preset_roto() -> None:
    assert any("titulo" in e for e in video_model.validar(_video(titulo="   ")))
    roto = VideoPreset(voz="", fondos=[], palabras_subtitulo=9,
                       fondo_min_s=0, voz_formantes=3.0)
    errores = video_model.validar(_video(preset=roto))
    assert len(errores) == 5


def test_validar_rechaza_reel_mas_largo_que_el_tope_de_la_marca() -> None:
    """La duración solo se conoce tras renderizar; ahí se corta la publicación."""
    preset = VideoPreset(max_duracion_s=90.0)
    assert video_model.validar(_video(preset=preset, duracion_s=65.0)) == []
    errores = video_model.validar(_video(preset=preset, duracion_s=140.0))
    assert any("140s" in e and "90s" in e for e in errores), errores
    # sin duración medida (antes del render) no se juzga el largo
    assert video_model.validar(_video(preset=preset)) == []


def test_validar_rechaza_rango_de_palabras_incoherente() -> None:
    for malo in (VideoPreset(palabras_min=200, palabras_max=100),
                 VideoPreset(palabras_min=5, palabras_max=100),
                 VideoPreset(palabras_min=90, palabras_max=9999)):
        assert any("palabras_min" in e for e in video_model.validar(_video(preset=malo)))


def test_round_trip_json_conserva_preset_y_pieza() -> None:
    original = _video(preset=VideoPreset(voz="es-MX-DaliaNeural",
                                         fondos=["espejo"],
                                         cta_marca="@shit.book"),
                      semilla="shitbook-42", duracion_s=48.5,
                      caption="pie del post")
    vuelto = video_model.desde_json(video_model.a_json(original))
    assert vuelto == original
    assert vuelto.preset.cta_marca == "@shit.book"


def test_desde_json_ignora_claves_desconocidas() -> None:
    """Un video_json de una versión futura no debe reventar al cargarse."""
    crudo = json.dumps({"titulo": "t", "cuerpo": "c", "preset": {},
                        "campo_del_futuro": 1})
    video = video_model.desde_json(crudo)
    assert video.titulo == "t"
    assert not hasattr(video, "campo_del_futuro")
