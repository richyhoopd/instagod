"""Reacomodo de capas entre 4:5, 1:1 y 9:16 por su anclaje."""
from __future__ import annotations

import copy

import pytest

from src.plantillas import escena as E
from tests.test_escena_esquema import _escena


def _por_id(esc: dict) -> dict:
    return {c["id"]: c for c in esc["capas"]}


def test_4x5_a_9x16():
    esc = _escena()
    original = copy.deepcopy(esc)
    nueva = E.reformatear(esc, "9x16")
    assert esc == original                                  # no muta
    assert nueva["lienzo"]["w"] == 1080 and nueva["lienzo"]["h"] == 1920
    assert nueva["lienzo"]["formato"] == "9x16"
    c = _por_id(nueva)
    assert c["c_titular"]["y"] == 196                       # top
    assert c["c_foto"]["y"] == 600 + 570                    # bottom: dy = 570
    assert c["c_clip"]["y"] == 0 + 285                      # center: dy/2
    assert c["c_caja"]["y"] == 1200 + 570


def test_a_sangre_se_estira():
    esc = _escena()
    esc["capas"][1].update(x=0, y=0, w=1080, h=1350, anclaje="center")
    c = _por_id(E.reformatear(esc, "1x1"))
    assert (c["c_foto"]["x"], c["c_foto"]["y"], c["c_foto"]["w"], c["c_foto"]["h"]) == (
        0, 0, 1080, 1080)


def test_el_grupo_recalcula_su_caja():
    c = _por_id(E.reformatear(_escena(), "9x16"))
    logo, caja, grupo = c["c_logo"], c["c_caja"], c["g_marca"]
    assert grupo["x"] == min(logo["x"], caja["x"])
    assert grupo["y"] == min(logo["y"], caja["y"])
    assert grupo["y"] + grupo["h"] == max(logo["y"] + logo["h"], caja["y"] + caja["h"])


def test_ida_y_vuelta_conserva_posiciones():
    esc = _escena()
    vuelta = E.reformatear(E.reformatear(esc, "9x16"), "4x5")
    assert [(c["x"], c["y"]) for c in vuelta["capas"] if c["tipo"] != "group"] == [
        (c["x"], c["y"]) for c in esc["capas"] if c["tipo"] != "group"]


def test_el_resultado_es_valido_para_su_aspecto():
    from tests.test_escena_esquema import CONTRATO
    E.validar(E.reformatear(_escena(), "9x16"), {**CONTRATO, "aspecto": "9:16"})


def test_formato_desconocido():
    with pytest.raises(E.EscenaInvalida):
        E.reformatear(_escena(), "16x9")


@pytest.mark.parametrize("malo", [None, [], {"lienzo": None, "capas": []},
                                  {"lienzo": {"w": 1, "h": 1}, "capas": [1]}])
def test_entrada_mal_tipada_es_escena_invalida(malo):
    with pytest.raises(E.EscenaInvalida):
        E.reformatear(malo, "1x1")
