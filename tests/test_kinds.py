import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.plantillas import kinds

FIX = Path(__file__).parent / "fixtures" / "kinds"
DISPONIBLES = sorted(p.stem for p in FIX.glob("*.json"))
FUENTES = {"titulo": "Poppins-Bold", "texto": "Poppins-SemiBold"}


def _marca():
    return SimpleNamespace(id=1, slug="prueba", nombre="Prueba", ig_handle="prueba",
                           color_marca="#7A4CFF", voz="", fuentes=[], formatos=["4x5"],
                           estilos={}, logo_path=None, activa=True, prompts={})


def _asset(slot):
    return {"src": f"file:///tmp/{slot}.png", "archivo": f"assets/{slot}.png",
            "fuente_asset": {"proveedor": "prueba", "autor": None, "licencia": None,
                             "url": None, "ig_handle": None}}


def render_fixture(kind):
    spec = kinds.validar_spec(kind, json.loads((FIX / f"{kind}.json").read_text())["spec"])
    assets = {s["id"]: _asset(s["id"]) for s in kinds.slots(kind, spec)}
    return spec, kinds.render(kind, spec, tokens=kinds.tokens_de(_marca(), spec["tema"]),
                              fuentes=FUENTES, assets=assets, handle="@prueba")


@pytest.mark.parametrize("kind", DISPONIBLES)
def test_fixture_renderiza(kind):
    _, html = render_fixture(kind)
    ids = re.findall(r'data-id="([^"]+)"', html)
    assert "titulo" in ids or kind == "meme"
    assert len(ids) == len(set(ids)), f"ids repetidos en {kind}"
    for i in ids:
        assert re.fullmatch(r"[a-z][a-z0-9_-]{0,24}", i), i
    assert "{{" not in html
    assert "box-shadow" not in html and "text-shadow" not in html
    # El DSL exige coordenadas explícitas en cada capa.
    for estilo in re.findall(r'data-tipo="[a-z]+"[^>]*style="([^"]*)"', html):
        assert "left:" in estilo and "top:" in estilo and "width:" in estilo


@pytest.mark.parametrize("kind", DISPONIBLES)
def test_requeridos_propios(kind):
    req = set(kinds.esquema(kind)["required"]) - {"titulo"}
    spec = json.loads((FIX / f"{kind}.json").read_text())["spec"]
    for r in req:
        incompleto = {k: v for k, v in spec.items() if k != r}
        with pytest.raises(kinds.SpecInvalido, match=r):
            kinds.validar_spec(kind, incompleto)


def test_estan_todos_los_del_lote_a():
    assert {"side", "stat", "vs", "compare", "list", "cta"} <= set(DISPONIBLES)
